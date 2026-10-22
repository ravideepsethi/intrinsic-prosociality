"""One narrow chronology pass, checkpointed by file, then bounded user shards."""
from __future__ import annotations
import shutil,time
from common import *
from cohort_logic import compress_sql,rematch_logic,EVENTS

BUCKETS=128
def file_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    rec=job['record'];p=Path(rec['path'])
    if stamp(p)!=rec['fingerprint']:raise RuntimeError('Chronology changed before projection')
    inp=observed_binding(p,job['auth']);inputs=[inp,*job['target_inputs']]
    key=digest(dict(code=job['code'],record=rec,inputs=inputs,buckets=BUCKETS))
    def build(tmp):
        started=time.monotonic();c=connection(tmp/'spill',job['threads'],job['memory_mb'])
        try:
            month=rec['month'];ix=MONTHS.index(month)
            lo=int(STARTS[ix]);hi=int(STARTS[ix+1]) if ix+1<len(STARTS) else 1777593600000
            # Exact inherited extraction: invalid starts and missing player IDs
            # were omitted before the original observed-event windows.
            h='(SELECT * FROM '+scan(p)+' WHERE utc_ms>0 AND white_id IS NOT NULL AND black_id IS NOT NULL)'
            # Validate the temporal scope used by the compression proof.
            bounds=c.execute(f'SELECT min(utc_ms),max(utc_ms),count(*) FILTER(WHERE utc_ms IS NULL) FROM {h}').fetchone()
            if bounds[2] or (bounds[0] is not None and (bounds[0]<lo or bounds[1]>=hi)):
                raise RuntimeError('Chronology contains a start outside its declared month')
            c.execute('CREATE VIEW users AS SELECT * FROM '+scan(Path(job['targets'])/'target_users_PRIVATE.parquet'))
            c.execute('CREATE VIEW mu AS SELECT user_id FROM '+scan(Path(job['targets'])/'target_user_months_PRIVATE.parquet')+' WHERE month='+lit(month))
            query=f'''SELECT h.game_id,v.user_id,v.opponent_id,h.utc_ms,h.archive_ordinal,
                mu.user_id IS NOT NULL has_target_month
                FROM {h} h CROSS JOIN LATERAL (VALUES (h.white_id,h.black_id),(h.black_id,h.white_id)) v(user_id,opponent_id)
                SEMI JOIN users u ON v.user_id=u.user_id LEFT JOIN mu ON v.user_id=mu.user_id'''
            selected=tmp/'selected_PRIVATE.parquet';n=copy(c,query,selected)
            c.execute('CREATE VIEW selected AS SELECT * FROM '+scan(selected))
            bad=c.execute('''SELECT count(*) FROM selected WHERE game_id IS NULL OR user_id IS NULL
                OR opponent_id IS NULL OR archive_ordinal IS NULL OR user_id=opponent_id OR user_id<0''').fetchone()[0]
            if bad:raise RuntimeError('Invalid selected chronology event')
            q=f'SELECT *,{lit(month)} AS month,CAST(user_id%{BUCKETS} AS INTEGER) AS ub FROM ({compress_sql()})'
            c.execute('SET partitioned_write_max_open_files=64')
            retained=c.execute('COPY ('+q+') TO '+lit(tmp/'events')+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(ub),ROW_GROUP_SIZE 131072)').fetchone()[0]
            selected.unlink()
            return dict(month=month,speed=rec['speed'],input_games=rec['rows'],selected_player_events=n,
                retained_events=int(retained),elapsed_seconds=time.monotonic()-started,
                additional_canonical_speed_partition=rec.get('additional_canonical_speed_partition',False),
                authority=inp['authority'],compression='full focal user-months; first/last two other user-file segments')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    root,done=stage(Path(job['work'])/'chronology'/digest(str(p.resolve()))[:20]/key,key,inputs,build,job['auth'])
    return dict(root=str(root),receipt=receipt(root/'_DONE.json'),result=done['result'],files=done['files'])

def side_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    inputs=job['inputs'];key=digest(dict(code=job['code'],bucket=job['bucket'],inputs=inputs))
    def build(tmp):
        c=connection(tmp/'spill',1,job['memory_mb'])
        try:
            b=job['bucket'];target=scan(Path(job['targets'])/'targets_PRIVATE.parquet')
            c.execute(f'''CREATE VIEW all_targets AS SELECT game_id,p1 user_id,month FROM {target} WHERE p1%{BUCKETS}={b}
                UNION ALL SELECT game_id,p2,month FROM {target} WHERE p2%{BUCKETS}={b}''')
            if job['paths']:c.execute('CREATE VIEW all_events AS SELECT * FROM '+scan(job['paths']))
            else:c.execute('''CREATE VIEW all_events AS SELECT NULL::VARCHAR game_id,NULL::BIGINT user_id,NULL::BIGINT opponent_id,
                    NULL::BIGINT utc_ms,NULL::BIGINT archive_ordinal,NULL::VARCHAR AS month WHERE FALSE''')
            duplicate=c.execute('SELECT count(*) FROM (SELECT user_id,game_id FROM all_events GROUP BY ALL HAVING count(*)>1)').fetchone()[0]
            if duplicate:raise RuntimeError('Duplicate canonical player-event identity across files')
            sizes={}
            for label,where_t,where_e in [('new',"month<>'2023-11'",'TRUE'),
                ('bridge',"month='2023-11'","month>='2023-10' AND month<='2025-11'")]:
                c.execute('CREATE OR REPLACE VIEW targets AS SELECT game_id,user_id FROM all_targets WHERE '+where_t)
                c.execute('CREATE OR REPLACE VIEW ev AS SELECT '+EVENTS+' FROM all_events WHERE '+where_e)
                sizes[label]=copy(c,rematch_logic.side_query(),tmp/(label+'_sides_PRIVATE.parquet'))
            return dict(bucket=b,**sizes)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    root,done=stage(Path(job['work'])/'sides'/f'bucket-{job["bucket"]:03d}'/key,key,inputs,build,job['auth'])
    return dict(root=str(root),receipt=receipt(root/'_DONE.json'),result=done['result'])

def census(side_products,target_root,old,work,auth,code,threads,memory_mb,expected_bridge_rows=2015809):
    inputs=[dict(**r['receipt'],fingerprint=stamp(r['receipt']['path'])) for r in side_products]
    inputs += old['snapshots']
    target=Path(target_root)/'targets_PRIVATE.parquet'
    inputs.append(dict(path=str(target),sha256=sha(target),fingerprint=stamp(target)))
    key=digest(dict(code=code,inputs=inputs,expected_bridge_rows=expected_bridge_rows))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            c.execute('CREATE VIEW all_focal AS SELECT * FROM '+scan(target))
            for label,where in [('new',"month<>'2023-11'"),('bridge',"month='2023-11'")]:
                paths=[Path(r['root'])/(label+'_sides_PRIVATE.parquet') for r in side_products]
                c.execute('CREATE OR REPLACE VIEW sides AS SELECT * FROM '+scan(paths))
                c.execute('CREATE OR REPLACE VIEW f AS SELECT game_id,p1,p2 FROM all_focal WHERE '+where)
                if c.execute('SELECT count(*) FROM (SELECT game_id,user_id FROM sides GROUP BY ALL HAVING count(*)<>1)').fetchone()[0]:
                    raise RuntimeError('Focal sides are not unique')
                n=copy(c,rematch_logic.census_query(),tmp/(label+'_adjacency_PRIVATE.parquet'))
                if n!=c.execute('SELECT count(*) FROM f').fetchone()[0]:raise RuntimeError('Census lost focal games')
            c.execute('CREATE VIEW b AS SELECT * FROM '+scan(tmp/'bridge_adjacency_PRIVATE.parquet'))
            c.execute('CREATE VIEW old_all AS SELECT * FROM '+scan(old['eligibility']))
            c.execute('CREATE VIEW old_bridge AS SELECT a.* FROM old_all a SEMI JOIN b USING(game_id)')
            if c.execute('SELECT count(*),count(DISTINCT game_id) FROM old_bridge').fetchone()!=(expected_bridge_rows,expected_bridge_rows):
                raise RuntimeError('Original November membership coverage differs')
            bad=c.execute('''SELECT count(*) FROM b FULL OUTER JOIN old_bridge o USING(game_id)
                WHERE b.game_id IS NULL OR o.game_id IS NULL
                OR b.previous_classification_status IS DISTINCT FROM o.previous_classification_status''').fetchone()[0]
            if bad:raise RuntimeError(f'Original November adjacency bridge differs in {bad} rows')
            copy(c,'SELECT game_id,source,previous_classification_status FROM old_bridge',tmp/'old_bridge_membership_PRIVATE.parquet')
            bridge=dict(status='EXACT_NOVEMBER_2023_PREVIOUS_STATUS_BRIDGE_OK',rows=expected_bridge_rows,different_rows=0,
                old_history_scope='2023-10 through 2025-11; original rated-standard observed chronology')
            c.execute('CREATE VIEW a AS SELECT * FROM '+scan(tmp/'new_adjacency_PRIVATE.parquet'))
            counts=[dict(month=r[0],previous_status=r[1],rows=r[2]) for r in c.execute('''SELECT t.month,a.previous_classification_status,count(*)
                FROM a JOIN all_focal t USING(game_id) GROUP BY 1,2 ORDER BY 1,2''').fetchall()]
            return dict(bridge=bridge,counts=counts,new_rows=sum(r['rows'] for r in counts),
                literal_end_to_start_rematches_certified=False,extended_history_scope='2023-09 through 2026-04',
                original_24_month_membership_changed=False)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(Path(work)/'adjacency'/key,key,inputs,build,auth)
