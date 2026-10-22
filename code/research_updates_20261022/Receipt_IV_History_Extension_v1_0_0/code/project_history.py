"""Build reusable added-month histories; never label an unknown row main-eligible."""
from __future__ import annotations
import time
from common import *
from history_logic import project_batch,projected_schema,num

def build_month(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    month=job['month'];started=time.monotonic()
    key=digest(dict(code=job['code_sha'],month=month,inputs=job['inputs'],bridge=job['bridge']))
    dest=Path(job['work'])/'months'/month/key
    def producer(tmp):
        c=connection(tmp/'spill',1,job['memory_mb'])
        try:
            c.execute('CREATE VIEW b AS SELECT * FROM '+scan(job['base']))
            c.execute('CREATE VIEW a AS SELECT * FROM '+scan(job['anchor_paths']))
            c.execute('CREATE VIEW sr AS SELECT h.* FROM '+scan(job['source_paths'])+' h SEMI JOIN b USING(game_id)')
            source_cols=set().union(*(columns(p) for p in job['source_paths']))
            required={'game_id','outcome_kind_draw','timeout_chooser_win','tc_base_s','tc_inc_s','tournament_like_event'}
            adapter=job.get('arm_adapter','stored_timeout_chooser_win')
            if adapter=='october_api_winner':
                required.remove('timeout_chooser_win');required.update(['api_status','api_winner','api_draw','candidate_chooser_color_norm'])
                # Exact Stage05 arm rule applied to the registered October source.
                bad=c.execute("""SELECT count(*) FROM sr JOIN b USING(game_id) WHERE
                    lower(trim(api_status)) IS DISTINCT FROM 'timeout'
                    OR try_cast(api_draw AS BOOLEAN) IS NULL
                    OR lower(trim(candidate_chooser_color_norm)) IS DISTINCT FROM b.color
                    OR (try_cast(api_draw AS BOOLEAN) IS FALSE AND coalesce(lower(trim(api_winner)),'') NOT IN ('white','black'))
                    OR (try_cast(api_draw AS BOOLEAN) IS TRUE AND nullif(lower(trim(api_winner)),'') IS NOT NULL)""").fetchone()[0]
                if bad:raise RuntimeError('October API winner/draw adapter validation failed')
                c.execute("""CREATE VIEW s AS SELECT *,
                    (try_cast(api_draw AS BOOLEAN) IS FALSE AND lower(trim(api_winner))=lower(trim(candidate_chooser_color_norm)))
                    AS timeout_chooser_win FROM sr""")
                source_cols.add('timeout_chooser_win')
            elif adapter=='stored_timeout_chooser_win':c.execute('CREATE VIEW s AS SELECT * FROM sr')
            else:raise RuntimeError('Unknown frozen arm adapter')
            for path in job['source_paths']:
                if not required<=columns(path):raise RuntimeError('Required original IV source fields absent in '+str(path))
            n=job['expected_rows']
            for view in ('b','a','s'):
                if c.execute(f'SELECT count(*),count(DISTINCT game_id) FROM {view}').fetchone()!=(n,n):
                    raise RuntimeError(month+': nonunique or incomplete '+view+' input')
            if c.execute('SELECT count(*) FROM b ANTI JOIN a USING(game_id)').fetchone()[0] or c.execute('SELECT count(*) FROM b ANTI JOIN s USING(game_id)').fetchone()[0]:
                raise RuntimeError(month+': source/anchor game sets differ')
            bad=c.execute('''SELECT count(*) FROM b JOIN a USING(game_id) JOIN s USING(game_id)
                WHERE a.valid_timing IS NOT TRUE OR a.start_ms IS DISTINCT FROM b.utc_ms
                OR a.anchor_ms<b.utc_ms OR a.competitive IS DISTINCT FROM (b.cp>=-100)
                OR b.grant IS DISTINCT FROM CAST(s.outcome_kind_draw AS DOUBLE)
                OR s.timeout_chooser_win IS NULL OR s.tc_base_s IS NULL OR s.tc_inc_s IS NULL
                OR NOT isfinite(s.tc_base_s) OR NOT isfinite(s.tc_inc_s)
                OR s.tc_base_s<0 OR s.tc_inc_s<0 OR s.tournament_like_event IS NULL
                OR b.color NOT IN ('white','black') OR b.color IS NULL
                OR b.chooser IS NULL OR b.opponent IS NULL OR b.chooser='' OR b.opponent=''
                OR b.chooser=b.opponent''').fetchone()[0]
            if bad:raise RuntimeError(f'{month}: {bad} source/anchor/arm consistency failures')
            if job['bridge']:
                bad=c.execute('''SELECT count(*) FROM s JOIN b USING(game_id) JOIN a USING(game_id)
                    WHERE CAST(s.kind_draw AS DOUBLE) IS DISTINCT FROM b.grant
                    OR s.fair_competitive IS DISTINCT FROM (b.cp>=-100)
                    OR s.api_last_move_at_ms IS DISTINCT FROM a.anchor_ms''').fetchone()[0]
                if bad:raise RuntimeError('Original IV arm, competitive flag or decision time differs')
            identity_reads=[]
            if job['bridge']:
                if not {'chooser_user_id','disconnected_user_id','archive_ordinal'}<=source_cols:
                    raise RuntimeError('Historical bridge lacks original identities/order')
                ids='s.chooser_user_id';other='s.disconnected_user_id';order='s.archive_ordinal';extra=''
            else:
                identity_paths=[]
                for ix,rec in enumerate(job['identity']):
                    p=rec['path'];needed={'game_id','utc_ms','archive_ordinal','white_id','black_id','white_elo','black_elo'}
                    if not needed<=columns(p):raise RuntimeError('Canonical identity/order columns absent: '+p)
                    target=tmp/f'identity_source_{ix:02d}_PRIVATE.parquet'
                    query=f'''SELECT h.game_id,h.utc_ms,h.archive_ordinal,h.white_id,h.black_id,h.white_elo,h.black_elo,
                        {lit(rec['speed'])} AS canonical_speed FROM {scan(p)} h
                        SEMI JOIN b ON h.game_id=b.game_id'''
                    count=copy(c,query,target);identity_paths.append(target)
                    identity_reads.append(dict(speed=rec['speed'],mode=rec['mode'],input_rows=rec['rows'],target_rows=count))
                c.execute('CREATE VIEW k AS SELECT * FROM '+scan(identity_paths))
                if c.execute('SELECT count(*),count(DISTINCT game_id) FROM k').fetchone()!=(n,n):
                    raise RuntimeError(month+': canonical identity/order coverage not one-to-one')
                if c.execute('SELECT count(*) FROM b ANTI JOIN k USING(game_id)').fetchone()[0]:raise RuntimeError('Missing canonical focal games')
                ids="CASE WHEN b.color='white' THEN k.white_id ELSE k.black_id END"
                other="CASE WHEN b.color='white' THEN k.black_id ELSE k.white_id END"
                order='k.archive_ordinal';extra=' JOIN k USING(game_id)'
                bad=c.execute('''SELECT count(*) FROM b JOIN k USING(game_id)
                    WHERE k.utc_ms IS DISTINCT FROM b.utc_ms OR k.canonical_speed IS DISTINCT FROM b.speed
                    OR (CASE WHEN b.color='white' THEN k.white_elo ELSE k.black_elo END) IS DISTINCT FROM b.rating
                    OR (CASE WHEN b.color='white' THEN k.black_elo ELSE k.white_elo END) IS DISTINCT FROM b.opp_rating
                    OR k.archive_ordinal IS NULL OR k.white_id IS NULL OR k.black_id IS NULL
                    OR k.white_id=k.black_id''').fetchone()[0]
                if bad:raise RuntimeError(f'{month}: {bad} canonical role/rating/start mismatches')
                for name,expr in [('chooser_user_id',ids),('disconnected_user_id',other)]:
                    if name in source_cols:
                        bad=c.execute(f'SELECT count(*) FROM b JOIN s USING(game_id) JOIN k USING(game_id) WHERE s.{name} IS NOT NULL AND s.{name} IS DISTINCT FROM ({expr})').fetchone()[0]
                        if bad:raise RuntimeError(month+': canonical identities disagree with source IDs')
            src_fields=[x for x in ('api_source','lookup_source') if x in source_cols]
            if len(src_fields)==2:
                bad=c.execute("SELECT count(*) FROM s WHERE api_source IS NOT NULL AND lookup_source IS NOT NULL AND lower(trim(api_source))<>lower(trim(lookup_source))").fetchone()[0]
                if bad:raise RuntimeError('Conflicting explicit API source fields')
            source_expr='NULL::VARCHAR' if not src_fields else 'lower(trim(coalesce('+','.join('CAST(s.'+f+' AS VARCHAR)' for f in src_fields)+',NULL)))'
            query=f'''SELECT b.game_id,b.utc_ms,a.anchor_ms,CAST({order} AS BIGINT) archive_ordinal,
                CAST({ids} AS BIGINT) chooser_user_id,CAST({other} AS BIGINT) disconnected_user_id,
                b.chooser,b.opponent,b.color,b.speed,b.rating,b.opp_rating,b.grant,b.cp,b.ply,
                CAST(s.timeout_chooser_win AS BOOLEAN) timeout_chooser_win,
                CAST(s.tc_base_s AS DOUBLE) tc_base_s,CAST(s.tc_inc_s AS DOUBLE) tc_inc_s,
                CAST(s.tournament_like_event AS BOOLEAN) tournament_like_event,
                {source_expr} AS explicit_source_label,
                NULL::BOOLEAN AS extended_pool_nonadjacent_eligible,
                NULL::BOOLEAN AS final_iv_eligible,
                {lit(month)} AS month
                FROM b JOIN a USING(game_id) JOIN s USING(game_id){extra}'''
            features=tmp/'opportunities_PRIVATE.parquet';count=copy(c,query,features)
            if count!=n:raise RuntimeError('Feature projection lost rows')
            f=scan(features)
            bad=c.execute(f'''SELECT count(*) FROM {f} WHERE chooser_user_id IS NULL OR disconnected_user_id IS NULL
                OR chooser_user_id<0 OR disconnected_user_id<0 OR chooser_user_id>={job['n_users']}
                OR disconnected_user_id>={job['n_users']} OR chooser_user_id=disconnected_user_id
                OR archive_ordinal IS NULL OR (grant=1 AND timeout_chooser_win)''').fetchone()[0]
            if bad:raise RuntimeError(f'{month}: {bad} invalid global IDs or arms')
            copy(c,f'''SELECT DISTINCT chooser AS username,chooser_user_id AS user_id FROM {f}
                UNION SELECT DISTINCT opponent,disconnected_user_id FROM {f}''',tmp/'identity_pairs_PRIVATE.parquet')
            source_counts=[dict(label=x[0],rows=x[1]) for x in c.execute(f'SELECT explicit_source_label,count(*) FROM {f} GROUP BY 1').fetchall()]
        finally:c.close()
        writers=[pq.ParquetWriter(tmp/f'shard-{i:02d}.parquet',projected_schema(),compression='zstd') for i in range(16)]
        count=training=fair=realtime=0
        try:
            for b in pq.ParquetFile(tmp/'opportunities_PRIVATE.parquet').iter_batches(batch_size=131072,use_threads=False):
                p,shards=project_batch(pa.Table.from_batches([b]));count+=len(p)
                training+=int(arr(p,'arm',bool).sum());fair+=int(arr(p,'fair',bool).sum());realtime+=int(arr(p,'rt',bool).sum())
                for k,w in enumerate(writers):
                    ix=np.flatnonzero(shards==k)
                    if len(ix):w.write_table(p.take(pa.array(ix)),row_group_size=131072)
        finally:
            for w in writers:w.close()
        if count!=n:raise RuntimeError('History projection lost rows')
        return dict(month=month,rows=count,training_rows=training,competitive_rows=fair,realtime_rows=realtime,
            arm_adapter=adapter,
            shard_count=16,identity_reads=identity_reads,source_label_coverage=source_counts,
            extended_pool_eligibility='NOT_BUILT',final_iv_eligible_n=None,
            elapsed_seconds=time.monotonic()-started)
    with heartbeat('Building history '+month):root,done=stage(dest,key,job['inputs'],producer,job['auth_root'])
    log(f'{month}: {done["result"]["rows"]:,} history rows ready')
    return dict(month=month,root=str(root),receipt=receipt(root/'_DONE.json'),result=done['result'])

def identity_check(months,work,auth_root,threads,memory_mb,code_sha):
    inputs=[dict(**r['receipt'],fingerprint=stamp(r['receipt']['path'])) for r in months]
    paths=[Path(r['root'])/'identity_pairs_PRIVATE.parquet' for r in months]
    key=digest(dict(code=code_sha,inputs=inputs))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            c.execute('CREATE VIEW identities AS SELECT * FROM '+scan(paths))
            name_conflicts=c.execute('SELECT count(*) FROM (SELECT username FROM identities GROUP BY 1 HAVING count(DISTINCT user_id)>1)').fetchone()[0]
            id_conflicts=c.execute('SELECT count(*) FROM (SELECT user_id FROM identities GROUP BY 1 HAVING count(DISTINCT username)>1)').fetchone()[0]
            if name_conflicts or id_conflicts:raise RuntimeError('ID/name namespace conflicts across added months and old-month bridge')
            count=copy(c,'SELECT DISTINCT username,user_id FROM identities',tmp/'identity_map_PRIVATE.parquet')
            return dict(status='OBSERVED_ID_NAME_CONSISTENCY_PASSED',unique_accounts=count,
                name_conflicts=0,id_conflicts=0,scope='eight added months plus November 2023 bridge; no invented IDs')
        finally:c.close()
    root,r=stage(Path(work)/'identity_check'/key,key,inputs,build,auth_root)
    return root,r
