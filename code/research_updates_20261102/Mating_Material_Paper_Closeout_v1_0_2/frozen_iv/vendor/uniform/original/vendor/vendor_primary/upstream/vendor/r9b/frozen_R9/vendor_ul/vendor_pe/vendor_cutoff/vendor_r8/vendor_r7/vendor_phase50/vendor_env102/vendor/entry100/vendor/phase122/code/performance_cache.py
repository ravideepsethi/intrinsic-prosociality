"""Immutable, phase-independent Parquet feature blocks; row IDs are rebound.

Cache identity includes the computation and authenticated sources. Exact game,
role and timing keys prevent reuse across different opportunities. No live
downloader state or fitted coefficient enters a cache key.
"""
from cached_common import *
import fcntl,uuid,shutil

BEHAVIOR_KEYS=['game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','month_code','previous_frame']
CHRON_KEYS=['game_id','recipient_id','opponent_id','archive_start_ms']

def definition(kind,source,files):
    return dict(kind=kind,source=source,code={Path(p).name:io.sha(p) for p in files})

def feature_stage(job,filename,keys,produce):
    """produce(query_path, temporary_directory) returns a row_id keyed Parquet."""
    def build(tmp):
        cache=Path(job['cache']);cache.mkdir(parents=True,exist_ok=True)
        with (cache/'CACHE.lock').open('a+') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            identity=cache/'definition.json'
            if identity.exists() and io.load(identity)!=job['cache_definition']:
                raise RuntimeError('Feature cache definition changed')
            if not identity.exists():io.js(identity,job['cache_definition'])
            blocks=[]
            for p in sorted((cache/'blocks').glob('*')):
                if '.partial_' in p.name:continue
                if io.complete(p,job['cache_conf']) is None:raise RuntimeError('Unrecognized cache block')
                blocks.append(p/'records.parquet')
            c=io.conn(tmp/'spill',job['memory'],1)
            try:
                c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([job['queries']]))
                total=c.execute('SELECT count(*) FROM q').fetchone()[0]
                keylist=','.join(keys);join=' USING('+keylist+')'
                parts=[];hitn=0;feature_names=None
                if blocks:
                    c.execute('CREATE VIEW cached AS SELECT * FROM '+io.parq(blocks))
                    feature_names=sorted(set(pq.ParquetFile(blocks[0]).schema_arrow.names)-set(keys))
                    duplicates=c.execute('SELECT count(*) FROM (SELECT '+keylist+',count(*) n FROM cached GROUP BY '+keylist+' HAVING count(*)>1)').fetchone()[0]
                    if duplicates:raise RuntimeError('Duplicate immutable feature cache keys')
                    hitn=io.copy(c,'SELECT q.row_id,cached.* EXCLUDE('+keylist+') FROM q JOIN cached'+join,tmp/'hits.parquet')
                    parts.append(tmp/'hits.parquet')
                    missing='SELECT q.* FROM q ANTI JOIN cached'+join
                else:missing='SELECT * FROM q'
                miss=io.copy(c,missing+' ORDER BY q.row_id',tmp/'missing.parquet')
                if hitn+miss!=total:raise RuntimeError('Feature cache changed query count')
                if miss or not parts:
                    compute=tmp/'compute';compute.mkdir()
                    path=Path(produce(tmp/'missing.parquet',compute))
                    c.execute('CREATE VIEW fresh AS SELECT * FROM '+io.parq([path]))
                    fresh_names=sorted(set(pq.ParquetFile(path).schema_arrow.names)-{'row_id'})
                    if feature_names is not None and feature_names!=fresh_names:raise RuntimeError('Feature cache schema changed')
                    feature_names=fresh_names
                    assert_rows(c,'SELECT * FROM fresh',miss,'New feature block')
                    c.execute('CREATE VIEW missing AS SELECT * FROM '+io.parq([tmp/'missing.parquet']))
                    if c.execute('SELECT count(*) FROM missing FULL OUTER JOIN fresh USING(row_id) WHERE missing.row_id IS NULL OR fresh.row_id IS NULL').fetchone()[0]:
                        raise RuntimeError('New feature block has different row IDs')
                    if miss:
                        query='SELECT '+','.join(['missing.'+k for k in keys]+['fresh.'+k for k in feature_names])+' FROM missing JOIN fresh USING(row_id)'
                        def publish(dest):
                            io.copy(c,query,dest/'records.parquet')
                            return dict(rows=miss,keys=keys)
                        io.stage(cache/'blocks'/uuid.uuid4().hex,job['cache_conf'],publish)
                    parts.append(path)
                fields=','.join(['row_id']+feature_names)
                union=' UNION ALL '.join('SELECT '+fields+' FROM '+io.parq([p]) for p in parts)
                n=io.copy(c,'SELECT * FROM ('+union+') ORDER BY row_id',tmp/filename)
                if n!=total:raise RuntimeError('Cached feature assembly changed row count')
            finally:finish_connection(c,tmp/'spill')
            for name in ('hits.parquet','missing.parquet'):(tmp/name).unlink(missing_ok=True)
            shutil.rmtree(tmp/'compute',ignore_errors=True)
            return dict(rows=total,cache_hits=hitn,computed_rows=miss,cache_definition_sha256=job['cache_conf'])
    return stable_stage(job['output'],job['conf'],build,[job['queries']])[1]

def attach(job,root,kind,definition,partition):
    conf=io.cfgsha(definition)
    return dict(job,cache=str(Path(root)/kind/conf/str(partition)),cache_definition=definition,cache_conf=conf)
