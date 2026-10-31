"""Read-only adoption of completed v1.0.2 features and chronology file parts."""
from cached_common import *
from performance_cache import feature_stage,BEHAVIOR_KEYS,CHRON_KEYS
import fcntl

V102_CODE='be1f6f51672c362590cf68828c29d851360705eba98f4390e744303a0b183b68'

def authenticate(a,local,phase,source,locks):
    found=[];parent=a.project_root/'derived/replication/run2_phase_analysis_v102_PRIVATE'
    for root in sorted(parent.glob('*')):
        if not (root/'config.json').is_file():continue
        config=io.load(root/'config.json');conf=io.cfgsha(config)
        if (config.get('code_sha256')!=V102_CODE or conf[:12]!=root.name or
            config.get('phase')!=phase or config.get('local_receipts')!=local['input_receipts']):continue
        lock=locks.enter_context((root/'RUN.lock').open('a+'))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('The v1.0.2 analysis is still active. Pause THAT analysis with Ctrl-C, then rerun. Keep the downloader running. Its completed checkpoints will be reused.')
        if not (root/'prepared/_DONE.json').exists():continue
        if io.cfgsha(io.load(root/'INPUTS_PRIVATE.json'))!=io.cfgsha(source):raise RuntimeError('v1.0.2 feature source binding differs')
        if io.complete(root/'prepared',conf) is None:continue
        found.append(dict(root=str(root),conf=conf))
    if len(found)>1:raise RuntimeError('More than one compatible v1.0.2 analysis; refusing ambiguous adoption')
    return found[0] if found else None

def import_job(job):
    threads_one();source=Path(job['legacy_feature']).parent
    if io.complete(source,job['legacy_conf']) is None:raise RuntimeError('Legacy feature stage is not complete')
    def produce(query,tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            names=pq.ParquetFile(job['legacy_feature']).schema_arrow.names
            fields=['f.row_id']
            for name in names:
                if name=='row_id':continue
                field='CASE WHEN q.previous_frame THEN f.'+name+' ELSE NULL END' if name.startswith('original_') else 'f.'+name
                fields.append(field+' AS '+name)
            path=tmp/'features.parquet'
            io.copy(c,'SELECT '+','.join(fields)+' FROM '+io.parq([query])+' q JOIN '+io.parq([job['legacy_feature']])+' f USING(row_id)',path)
            return path
        finally:finish_connection(c,tmp/'spill')
    return feature_stage(job,job['filename'],BEHAVIOR_KEYS,produce)

def reuse_chron_part(job):
    source=Path(job['legacy_part'])
    if not (source/'_DONE.json').exists():return None
    if io.complete(source,job['legacy_conf']) is None:return None
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW r AS SELECT * FROM '+io.parq([job['roles']]))
            c.execute('CREATE VIEW old AS SELECT row_id,game_id,recipient_id,opponent_id,archive_start_ms FROM '+io.parq([job['legacy_queries']])+' WHERE NOT previous_frame')
            # Rebind local row IDs through exact game/role/state keys.
            c.execute('''CREATE TEMP TABLE mapping AS SELECT DISTINCT old.row_id old_row,r.sample_row FROM r JOIN old
                ON r.game_id=old.game_id AND r.archive_start_ms=old.archive_start_ms
                AND ((r.role=0 AND r.user_id=old.recipient_id AND r.opponent_id=old.opponent_id)
                  OR (r.role=1 AND r.user_id=old.opponent_id AND r.opponent_id=old.recipient_id))''')
            count=c.execute('SELECT count(DISTINCT sample_row) FROM r').fetchone()[0]
            n,u=c.execute('SELECT count(*),count(DISTINCT sample_row) FROM mapping').fetchone()
            if n!=count or u!=count:raise RuntimeError('Legacy chronology part does not cover the current query states')
            n=io.copy(c,'SELECT m.sample_row,c.* EXCLUDE(sample_row) FROM '+io.parq([source/'candidates.parquet'])+' c JOIN mapping m ON c.sample_row=m.old_row',tmp/'candidates.parquet')
            io.copy(c,'SELECT p.* FROM '+io.parq([source/'pairs.parquet'])+' p SEMI JOIN '+io.parq([job['pairs']])+' q USING(pair_key)',tmp/'pairs.parquet')
            return dict(input_rows=job['rows'],retained_query_roles=n,file_index=job['file_index'],adopted_v102=True)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(job['output'],job['conf'],build,[source/'_DONE.json',source/'candidates.parquet',source/'pairs.parquet',job['roles'],job['pairs'],job['legacy_queries']])[1]
