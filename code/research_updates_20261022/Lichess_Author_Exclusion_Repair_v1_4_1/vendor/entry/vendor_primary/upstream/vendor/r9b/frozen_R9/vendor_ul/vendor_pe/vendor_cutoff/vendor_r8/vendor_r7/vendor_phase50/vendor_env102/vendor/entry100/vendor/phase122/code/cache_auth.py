"""Fixed phase membership and authentication of the completed local-first run."""
from pathlib import Path
import contextlib,hashlib,json,os,sys

PACKAGE=Path(__file__).resolve().parents[1]
VENDOR=PACKAGE/'vendor/local_first'
sys.path.insert(0,str(VENDOR/'code'))
from local_contract import *
import local_cache as cache
import run_local_first as local_run
import prepare_expansion as original_plan

PHASES=(10,25,50,100)
PHASE_VERSION='1.0.0'
UPSTREAM_PACKAGE_SHA='6ce63bd9831edcd606bfce22500155502008209ba7368c63984a06a51faa0082'
UPSTREAM_RUN='21715769dd17'
UPSTREAM_PLAN='9d6f58b570508cfae33e60c72a04e723969336ab05cda3adda7106b8c0f51456'
UPSTREAM_TARGETS=32726880
PHASE_REL='derived/replication/run2_phased_v100_PRIVATE'

def verify_release():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        sha,name=line.split('  ',1);io.checked(io.child(PACKAGE,name),sha)
    io.checked(VENDOR/'PACKAGE_MANIFEST.sha256',UPSTREAM_PACKAGE_SHA)

def threshold(percent):
    if percent not in PHASES[:-1]:raise ValueError('Finite thresholds are 10, 25 and 50 percent')
    return ((1<<256)*percent//100).to_bytes(32,'big')

def phase_of(rank,previous=False):
    if previous:return 0
    if not isinstance(rank,bytes) or len(rank)!=32:raise ValueError('Expected a 32-byte rank')
    return next((p for p in PHASES[:-1] if rank<threshold(p)),100)

def phase_sql(alias='f'):
    return ('CASE WHEN '+alias+'.previous_frame THEN 0 '+
        ' '.join(f"WHEN {alias}.retrieval_rank<from_hex('{threshold(p).hex()}') THEN {p}" for p in PHASES[:-1])+
        ' ELSE 100 END')

def selection_sql(percent,alias='f'):
    if percent not in PHASES:raise ValueError('Choose 10, 25, 50 or 100')
    return ('NOT '+alias+'.previous_frame'+
        (f" AND {alias}.retrieval_rank<from_hex('{threshold(percent).hex()}')" if percent<100 else ''))

def verify_stage_job(job):
    result=io.complete(Path(job['path']),job['conf'])
    if result is None:raise RuntimeError('Missing completed upstream stage: '+job['path'])
    return dict(path=job['path'],receipt_sha256=io.sha(Path(job['path'])/'_DONE.json'))

def authenticate(a):
    pointer_path=a.plan or a.desktop/'RUN2_LOCAL_FIRST_LATEST_PRIVATE.json'
    pointer=io.load(pointer_path);root=Path(pointer['root']);ready=Path(pointer['ready'])
    project=a.project_root.resolve()
    for p in (root,ready):
        if project not in p.resolve().parents:raise RuntimeError('Prepared run is outside the mounted project')
    config=io.load(root/'config.json')
    if root.name!=UPSTREAM_RUN or io.cfgsha(config)[:12]!=root.name:raise RuntimeError('Expected the reviewed local-first run 21715769dd17')
    if config['package_sha256']!=UPSTREAM_PACKAGE_SHA or config['version']!='1.0.1':
        raise RuntimeError('Unexpected upstream producer; completed inputs were not replaced or rebuilt')
    if pointer['config_sha256']!=UPSTREAM_PLAN:raise RuntimeError('Expected the reviewed local-first plan')
    io.complete(ready,UPSTREAM_PLAN)
    summary=io.load(ready/'summary.json')
    if summary['frame_rows']!=FRAME_ROWS or summary['remaining_api_targets']!=UPSTREAM_TARGETS:
        raise RuntimeError('Prepared row accounting differs from the reviewed report')
    manifest=io.load(ready/'ANALYSIS_INPUTS_PRIVATE.json')
    if manifest['merged_candidate_metadata']!=pointer['merged_metadata'] or manifest['target_file']!=str(ready/'targets.parquet'):
        raise RuntimeError('Prepared pointer disagrees with its authenticated manifest')
    ledgers=manifest['denominator']
    if len(ledgers)!=len(ex.MONTHS):raise RuntimeError('Expected every one of the 21 months')
    jobs=[dict(path=str(Path(p).parent),conf=UPSTREAM_PLAN) for p in ledgers]
    jobs += [dict(path=str(Path(pointer['merged_metadata']).parent),conf=UPSTREAM_PLAN),
             dict(path=str(root/'candidate_index'),conf=io.cfgsha(config))]
    evidence=io.mapped(verify_stage_job,jobs,a.workers,'Checking completed Parquets for reuse')
    for m,p in zip(ex.MONTHS,ledgers):
        if io.load(Path(p).parent/'_DONE.json')['month']!=m:raise RuntimeError('Upstream month order changed')
    if sum(pq.ParquetFile(p).metadata.num_rows for p in ledgers)!=FRAME_ROWS:raise RuntimeError('Frame row total changed')
    expected_index_rows=io.load(root/'candidate_index/_DONE.json')['rows']
    if len(np.load(root/'candidate_index/game_ids.npy',mmap_mode='r',allow_pickle=False))!=expected_index_rows:
        raise RuntimeError('Candidate index size changed')
    return dict(pointer=pointer,root=str(root),ready=str(ready),ledgers=ledgers,
        eligibility_ledgers=ledgers,metadata=pointer['merged_metadata'],
        index=str(root/'candidate_index/game_ids.npy'),manifest=manifest,summary=summary,
        input_receipts=evidence,pointer_sha256=io.sha(pointer_path))

def open_readonly(path):
    import sqlite3
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
    try:db.execute('PRAGMA query_only=ON')
    except BaseException:db.close();raise
    return contextlib.closing(db)

def report_zip(folder,desktop,stem):
    ex.report_zip(folder,desktop/(stem+'.zip'))
    io.log('RETURN THIS AGGREGATE REPORT: '+str(desktop/(stem+'.zip')))

def schema_empty_targets(path):
    io.table(path,pa.table({'game_id':pa.array([],type=pa.string()),'utc_ms':pa.array([],type=pa.int64()),
                          'speed_partition':pa.array([],type=pa.string())}))
