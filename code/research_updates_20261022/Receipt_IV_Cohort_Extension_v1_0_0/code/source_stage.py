"""Recover explicit labels from existing local files; no API client is present."""
from __future__ import annotations
import concurrent.futures as cf,multiprocessing as mp,shutil,sys
from collections import Counter
from common import *
from cohort_logic import source_reduce_sql,source_classify_sql
sys.path.insert(0,str(PACKAGE/'vendor'))
import build_game_source as original

NORMALIZE=original.normalize
def normalize_record(obj):
    r=NORMALIZE(obj)
    # A full native game omits winner for a draw. Reduced Parquets with a
    # missing winner column supply no winner evidence, not a fabricated draw.
    if r is not None and isinstance(obj,dict) and {'id','players','status'}<=set(obj):
        r['winner_present']=True
    return r

def init_worker(index):
    original.init_worker(index);original.normalize=normalize_record

def prepare_targets(opportunities,feature_sources,work,auth,code,threads,memory_mb,inputs):
    key=digest(dict(code=code,opportunities=opportunities,inputs=inputs))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb);outs=[]
        try:
            for month,p in sorted(opportunities.items()):
                src=feature_sources[month];sc=set.intersection(*(columns(q) for q in src))
                c.execute('CREATE OR REPLACE VIEW o AS SELECT * FROM '+scan(p))
                c.execute('CREATE OR REPLACE VIEW f AS SELECT f.* FROM '+scan(src)+' f SEMI JOIN o USING(game_id)')
                n=pq.ParquetFile(p).metadata.num_rows
                if c.execute('SELECT count(*),count(DISTINCT game_id) FROM f').fetchone()!=(n,n):
                    raise RuntimeError('Target metadata is not one-to-one: '+month)
                if 'api_winner' in sc:
                    winner="nullif(lower(trim(f.api_winner)),'')"
                elif {'timeout_chooser_win','timeout_chooser_loss'}<=sc:
                    winner="CASE WHEN f.timeout_chooser_win THEN o.color WHEN f.timeout_chooser_loss THEN CASE WHEN o.color='white' THEN 'black' ELSE 'white' END END"
                else:raise RuntimeError('No authenticated winner metadata: '+month)
                created='f.api_created_at_ms' if 'api_created_at_ms' in sc else 'NULL::BIGINT'
                bad=c.execute(f'''SELECT count(*) FROM o JOIN f USING(game_id) WHERE
                    (o.timeout_chooser_win AND ({winner}) IS DISTINCT FROM o.color)
                    OR (o.grant=1 AND ({winner}) IS NOT NULL)
                    OR (({winner}) IS NOT NULL AND ({winner}) NOT IN ('white','black'))''').fetchone()[0]
                if bad:raise RuntimeError('Target winner consistency failure: '+month)
                dest=tmp/(month+'.parquet')
                copy(c,f'''SELECT o.game_id,o.month,o.utc_ms,o.archive_ordinal,
                    o.chooser_user_id p1,o.disconnected_user_id p2,{winner} expected_winner,
                    CAST({created} AS BIGINT) api_created_at_ms FROM o JOIN f USING(game_id)''',dest)
                outs.append(dest)
            n=copy(c,'SELECT * FROM '+scan(outs),tmp/'targets_PRIVATE.parquet')
            c.execute('CREATE VIEW t AS SELECT * FROM '+scan(tmp/'targets_PRIVATE.parquet'))
            bad=c.execute("SELECT count(*) FROM t WHERE NOT regexp_full_match(game_id,'[A-Za-z0-9]{8}') OR game_id IS NULL OR p1=p2 OR p1<0 OR p2<0").fetchone()[0]
            if bad or c.execute('SELECT count(DISTINCT game_id) FROM t').fetchone()[0]!=n:
                raise RuntimeError('Source target identity validation failed')
            copy(c,'SELECT DISTINCT user_id,month FROM (SELECT p1 user_id,month FROM t UNION ALL SELECT p2,month FROM t)',tmp/'target_user_months_PRIVATE.parquet')
            copy(c,'SELECT DISTINCT user_id FROM '+scan(tmp/'target_user_months_PRIVATE.parquet'),tmp/'target_users_PRIVATE.parquet')
            a=c.execute('SELECT game_id FROM t ORDER BY game_id').to_arrow_table()
            np.save(tmp/'target_ids.npy',np.asarray(a['game_id'].to_pylist(),dtype='S8'),allow_pickle=False)
            for p in outs:p.unlink()
            return dict(rows=n,months=sorted(opportunities),source_timestamp_check='exact API milliseconds when retained; otherwise PGN start-second agreement',
                source_block_used_as_game_source=False)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(Path(work)/'targets'/key,key,inputs,build,auth)

def roots(project,desktop,extra):
    ans=original.default_roots(Path(project),Path.home(),Path(desktop))
    for base in ['derived/replication_36m','derived/replication']:
        d=Path(project)/base
        if d.is_dir():
            ans += [p for p in d.iterdir() if p.is_dir() and any(x in p.name.lower() for x in ('api','stage04','enrich')) and not p.name.endswith('_PRIVATE')]
    return list(dict.fromkeys([*ans,*[Path(p).expanduser().resolve() for p in extra]]))

def recover(project,desktop,extra,target_root,work,auth,code,workers,threads,memory_mb):
    base=Path(work)/'source';base.mkdir(parents=True,exist_ok=True)
    target=Path(target_root)/'targets_PRIVATE.parquet';index=Path(target_root)/'target_ids.npy'
    binding=dict(target_sha256=sha(target),target_index_sha256=sha(index),code_sha256=code)
    inventory=original.discover(roots(project,desktop,extra),base)
    successes=[];errors=[]
    with cf.ProcessPoolExecutor(max_workers=min(workers,8),mp_context=mp.get_context('spawn'),initializer=init_worker,initargs=(str(index),)) as pool:
        pending={pool.submit(original.scan,j,base/'evidence',binding,False):j for j in inventory['jobs']}
        with heartbeat('Recovering source from existing API files'):
            for count,f in enumerate(cf.as_completed(pending),1):
                job=pending[f]
                try:successes.append(f.result())
                except Exception as e:errors.append(dict(file_id=job['file_id'],path=job['path'],exception=type(e).__name__,error=str(e)))
                if count%100==0 or count==len(pending):log(f'Source files {count}/{len(pending)}; failed {len(errors)}')
    successes.sort(key=lambda r:r['input']['path'])
    totals=Counter()
    for r in successes:totals.update(r['counts'])
    write_json(base/'SCAN_STATUS_PRIVATE.json',dict(receipts=successes,errors=errors,inventory=inventory,counts=dict(totals)))
    snapshots=[dict(path=r['output'],sha256=r['output_sha256'],fingerprint=stamp(r['output'])) for r in successes]
    snapshots.append(dict(path=str(target),sha256=binding['target_sha256'],fingerprint=stamp(target)))
    key=digest(dict(code=code,inputs=snapshots,inventory=inventory,errors=errors))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            paths=[r['output'] for r in successes]
            if not paths:
                p=tmp/'empty_evidence_PRIVATE.parquet';pq.write_table(pa.Table.from_pylist([],schema=original.SCHEMA),p);paths=[p]
            c.execute('CREATE VIEW evidence AS SELECT * FROM '+scan(paths))
            c.execute('CREATE VIEW targets AS SELECT * FROM '+scan(target))
            copy(c,source_reduce_sql(),tmp/'source_candidates_PRIVATE.parquet')
            c.execute('CREATE VIEW recovered AS SELECT * FROM '+scan(tmp/'source_candidates_PRIVATE.parquet'))
            copy(c,source_classify_sql(original.SOURCES),tmp/'source_by_game_PRIVATE.parquet')
            c.execute('CREATE VIEW s AS SELECT * FROM '+scan(tmp/'source_by_game_PRIVATE.parquet'))
            if c.execute('SELECT count(*),count(DISTINCT game_id) FROM s').fetchone()!=c.execute('SELECT count(*),count(*) FROM targets').fetchone():
                raise RuntimeError('Source layer lost target rows')
            copy(c,"SELECT * FROM s WHERE source_status<>'recovered'",tmp/'unresolved_source_ids_PRIVATE.parquet')
            cols=['month','source_status','source','rows']
            counts=[dict(zip(cols,r)) for r in c.execute('SELECT month,source_status,source,count(*) FROM s GROUP BY ALL ORDER BY 1,2,3').fetchall()]
            issue_count=len(errors)+len(inventory['errors'])+sum(x['reason']!='root_absent' for x in inventory['skipped'])+totals['malformed_lines']+totals['nested_archives_unopened']
            return dict(counts=counts,input_files=len(inventory['jobs']),completed_files=len(successes),scan_issues=issue_count,
                malformed_lines=totals['malformed_lines'],nested_archives_unopened=totals['nested_archives_unopened'],
                source_files_changed_or_failed=len(errors),network_requests=0,
                interpretation='Known explicit labels and unresolved records; incomplete local coverage is not proof that fresh collection is required')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(base/'reduced'/key,key,snapshots,build,auth)
