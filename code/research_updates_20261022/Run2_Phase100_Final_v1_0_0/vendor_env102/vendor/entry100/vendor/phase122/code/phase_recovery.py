"""Reuse verified coverage; quarantine the one evidenced unresolved focal record.

This is an explicit available-case interim amendment, not a repair of the flag.
No conflicting value is chosen, no status/role is imputed, and no row replaces
the flagged draw from the fixed frame. The original immutable snapshot remains.
"""
from cached_common import *
import cached_inputs as prior_inputs
import shutil

PRIOR_CONF='4f3e99d97c05dece80092203ffac759201c5d9060fdf6eb79aa32ed44fac8810'
PRIOR_CODE_SHA='09d4eec062b0be83d6e8e06f946d607338018b48929662f55ecd1c0a524ddc7f'
POLICY='v101_available_case_interim_one_2024_04_cache_flag_retained_in_fixed_frame'

def reuse_v101_quarantine(a,local,phase,root,conf):
    """Import the exact completed one-record audit from the uploaded v1.0.1 run."""
    expected=io.load(PACKAGE/'evidence/v101_summary.json')
    prior_conf=expected['config_sha256']
    previous=a.project_root/'derived/replication/run2_phase_analysis_v101_PRIVATE'/prior_conf[:12]
    if not previous.exists():return False
    config=io.load(previous/'config.json')
    if (io.cfgsha(config)!=prior_conf or
        config['code_sha256']!='837fc3486dae3f8724583d09822be43cc5166933d8dafa2de3a11708b87445af' or
        config['local_receipts']!=local['input_receipts'] or config['phase']!=phase):
        raise RuntimeError('Previous quarantine source binding changed')
    source=previous/'quarantine';receipt=io.complete(source,prior_conf)
    if receipt is None:raise RuntimeError('Previous quarantine audit is incomplete')
    if io.load(source/'summary.json')!=io.load(PACKAGE/'evidence/v101_metadata_quarantine.json'):
        raise RuntimeError('Previous quarantine differs from the uploaded report')
    files=[r['path'] for r in receipt['files']]
    def build(tmp):
        for name in files:
            src=io.child(source,name);dst=io.child(tmp,name);dst.parent.mkdir(parents=True,exist_ok=True)
            try:os.link(src,dst)
            except OSError:shutil.copyfile(src,dst)
        return dict(io.load(source/'summary.json'),reused_from_config_sha256=prior_conf,
                    source_receipt_sha256=io.sha(source/'_DONE.json'))
    stable_stage(root,conf,build,[source/'_DONE.json']+[io.child(source,n) for n in files])
    io.log('Reused the completed v1.0.1 one-record quarantine audit')
    return True

def validated_source(job):
    root=Path(job['source'])
    receipt=io.complete(root,PRIOR_CONF)
    if receipt is None:raise RuntimeError('Missing completed coverage checkpoint: '+str(root))
    info=io.load(root/'coverage.json')
    if info['month']!=job['month']:raise RuntimeError('Coverage checkpoint has the wrong month')
    if pq.ParquetFile(root/'pool.parquet').metadata.num_rows!=info['pool_rows']:
        raise RuntimeError('Coverage Parquet count does not match its receipt')
    for key in info:
        if key in receipt and receipt[key]!=info[key]:raise RuntimeError('Coverage receipt differs: '+key)
    return dict(month=job['month'],source=str(root),receipt_sha256=io.sha(root/'_DONE.json'),info=info)

def assert_reviewed_coverage(coverage):
    """Only the exact uploaded failure is amended; not a generic ignore-errors flag."""
    expected=io.load(PACKAGE/'evidence/prior_failed_frame_dispositions.json')
    actual=[dict(month=r['month'],disposition=k,rows=v) for r in coverage for k,v in r['dispositions'].items()]
    key=lambda r:(r['month'],r['disposition'])
    if sorted(actual,key=key)!=sorted(expected,key=key):raise RuntimeError('Coverage differs from the reviewed one-record failure')
    endings=[r for c in coverage for r in c['ending_counts']]
    key=lambda r:(r['month'],r['status'],r['speed'])
    if sorted(endings,key=key)!=sorted(io.load(PACKAGE/'evidence/prior_failed_coverage_by_ending.json'),key=key):
        raise RuntimeError('Ending counts differ from the reviewed coverage')
    summary=io.load(PACKAGE/'evidence/prior_failed_summary.json')
    for field,reported in [('selected_frame_rows','fixed_additional_frame_rows'),('pool_rows','pool_games_before_chronology'),
                           ('ordinary_rows','ordinary_games_before_chronology'),('unresolved_rows','unresolved_selected_rows')]:
        if sum(r[field] for r in coverage)!=summary[reported]:raise RuntimeError('Reviewed coverage total differs: '+field)
    if sum(r['unresolved_rows'] for r in coverage)!=1:raise RuntimeError('Expected exactly the one reviewed metadata flag')

def authenticate_coverage(a,local,phase):
    root=a.project_root/'derived/replication/run2_phase_analysis_v100_PRIVATE'/PRIOR_CONF[:12]
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=PRIOR_CONF or config['code_sha256']!=PRIOR_CODE_SHA:
        raise RuntimeError('Previous coverage producer differs from the verified v1.0.0 run')
    if config['local_receipts']!=local['input_receipts'] or config['phase']!=phase:
        raise RuntimeError('Previous coverage used different source inputs')
    jobs=[dict(source=str(root/'coverage'/m),month=m) for m in ex.MONTHS]
    sources=io.mapped(validated_source,jobs,a.workers,'Verifying completed coverage for reuse')
    assert_reviewed_coverage([r['info'] for r in sources])
    return sources

def reuse_coverage_job(job):
    threads_one()
    source=Path(job['source'])
    io.checked(source/'_DONE.json',job['receipt_sha256'])
    def build(tmp):
        for name in ('pool.parquet','coverage.json'):
            # Hard links reuse bytes on the same SSD. Only read them afterwards;
            # cross-device fallback is an ordinary copy, never a source edit.
            try:os.link(source/name,tmp/name)
            except OSError:shutil.copyfile(source/name,tmp/name)
        return dict(job['info'],reused_from_config_sha256=PRIOR_CONF,
                    source_receipt_sha256=job['receipt_sha256'])
    return stable_stage(Path(job['output']),job['conf'],build,
                        [source/'_DONE.json',source/'pool.parquet',source/'coverage.json'])[1]

def quarantine(ledger,metadata,response,pools,root,conf,memory):
    """Retain private row evidence and export only aggregate field diagnostics."""
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([ledger])+' f WHERE '+selection_sql(10))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq(metadata))
            readiness=original_plan.readiness_sql()
            c.execute("CREATE TEMP TABLE unknown AS SELECT f.*,("+readiness+") current_metadata_status FROM f LEFT JOIN m USING(game_id) WHERE f.local_eligibility='POTENTIALLY_ELIGIBLE' AND ("+readiness+") NOT IN ('CACHED_POOL_METADATA','CACHED_NONPOOL')")
            counts=c.execute('SELECT current_metadata_status,count(*) FROM unknown GROUP BY 1').fetchall()
            if counts!=[('CACHE_CONFLICT_OR_PRIOR_FLAG',1)]:
                raise RuntimeError('Quarantine does not match the one reviewed April cache flag')
            io.copy(c,'SELECT * FROM unknown',tmp/'frame_record_PRIVATE.parquet')
            io.copy(c,'SELECT m.* FROM m SEMI JOIN unknown u USING(game_id)',tmp/'merged_record_PRIVATE.parquet')
            io.copy(c,'SELECT r.* FROM '+io.parq([response])+' r SEMI JOIN unknown u USING(game_id)',tmp/'completed_response_PRIVATE.parquet')
            overlap=c.execute('SELECT count(*) FROM '+io.parq(pools)+' p SEMI JOIN unknown u USING(game_id)').fetchone()[0]
            if overlap:raise RuntimeError('Flagged focal record occurs in the retained pool sample')
            merged=io.read(tmp/'merged_record_PRIVATE.parquet').to_pylist()
            fresh=io.read(tmp/'completed_response_PRIVATE.parquet').to_pylist()
            if len(merged)!=1:raise RuntimeError('Quarantined ID does not have exactly one merged record')
            # An agreeing exported response cannot erase an inherited conflict:
            # merged first-value fields can hide other conflicting cache values.
            differences=[];overlap_fields=0
            if len(fresh)==1:
                for field in ex.META_FIELDS:
                    left=merged[0].get(field);right=fresh[0].get(field)
                    if left is not None and right is not None:
                        overlap_fields+=1
                        if left!=right:differences.append(field)
            info=dict(policy=POLICY,month='2024-04',quarantined_rows=1,
                reason='CACHE_CONFLICT_OR_PRIOR_FLAG',fixed_frame_rows_retained=True,
                focal_record_used_in_models=False,substitute_rows_added=0,
                completed_response_records=len(fresh),
                completed_response_with_error_flag=sum(bool(r.get('record_errors')) for r in fresh),
                compared_nonmissing_metadata_fields=overlap_fields,fields_differing_from_completed_response=differences,
                full_metadata_reconciliation_complete=False,
                scope='Available-case interim analysis; record remains unresolved, not repaired.',
                scientific_limit='One excluded row is not by itself a bound on a regression coefficient or proof of exclusion validity.')
            io.js(tmp/'summary.json',info);return info
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[ledger,response]+metadata+pools)
