"""Continue the reviewed 25% frame with two explicit unresolved focal records.

Only the immutable c7362f8697b5 coverage is admitted. The old identity must
match its earlier audit; the June identity must match a flagged saved 10–25%
response. No values are repaired, imputed, or selected from conflicting sources.
"""
from cached_common import *
import checkpoint_inputs as checkpoint
import phase_recovery as prior
import cached_inputs
import shutil

EVIDENCE=PACKAGE/'evidence/phase25_failed'
POLICY='v122_available_case_interim_two_flags_2024_04_and_2025_06'
REASON='CACHE_CONFLICT_OR_PRIOR_FLAG'


def expected_month(month):
    dispositions={r['disposition']:r['rows'] for r in io.load(EVIDENCE/'frame_dispositions.json') if r['month']==month}
    endings=[r for r in io.load(EVIDENCE/'coverage_by_ending.json') if r['month']==month]
    return dict(month=month,selected_frame_rows=sum(dispositions.values()),
        pool_rows=dispositions.get('CACHED_POOL_METADATA',0),
        ordinary_rows=sum(r['rows'] for r in endings if r['status'] in core.NARROW),
        unresolved_rows=dispositions.get(REASON,0),dispositions=dispositions,ending_counts=endings)


def assert_month(actual,expected):
    for key in ('month','selected_frame_rows','pool_rows','ordinary_rows','unresolved_rows','dispositions'):
        if actual.get(key)!=expected[key]:raise RuntimeError('Reviewed 25% coverage changed: '+expected['month']+'/'+key)
    order=lambda r:(r['month'],r['status'],r['speed'])
    if sorted(actual['ending_counts'],key=order)!=sorted(expected['ending_counts'],key=order):
        raise RuntimeError('Reviewed 25% ending counts changed: '+expected['month'])


def bind_previous(a,local,phase):
    authority=io.load(EVIDENCE/'authority.json');conf=authority['config_sha256']
    root=a.project_root/'derived/replication/run2_phase25_analysis_v120_PRIVATE'/conf[:12]
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=conf or config['code_sha256']!=authority['code_sha256'] or config['version']!='1.2.1':
        raise RuntimeError('Reviewed 25% coverage producer changed')
    if config['local_receipts']!=local['input_receipts'] or config['phase']!=phase:
        raise RuntimeError('Reviewed 25% coverage sources changed')
    io.checked(root/'report/summary.json',authority['summary_sha256'])
    return dict(root=str(root),conf=conf,summary_sha256=authority['summary_sha256'])


def coverage_job(job):
    if not job.get('reuse'):return checkpoint.coverage_job(job)
    threads_one();source=Path(job['reuse']['root'])/'coverage'/job['month']
    receipt=io.complete(source,job['reuse']['conf'])
    if receipt is None:raise RuntimeError('Reviewed 25% month checkpoint missing: '+job['month'])
    info=io.load(source/'coverage.json');assert_month(info,expected_month(job['month']))
    names=('coverage.json','pool.parquet','membership_PRIVATE.parquet','unresolved_PRIVATE.parquet')
    if not set(names)<={r['path'] for r in receipt['files']}:raise RuntimeError('Coverage receipt omits a required file')
    def build(tmp):
        for name in names:
            try:os.link(source/name,tmp/name)
            except OSError:shutil.copyfile(source/name,tmp/name)
        return dict(info,reused_from_config_sha256=job['reuse']['conf'],source_receipt_sha256=io.sha(source/'_DONE.json'))
    return stable_stage(job['output'],job['conf'],build,[source/'_DONE.json']+[source/n for n in names])[1]


def require_rows(c,query,path,label):
    n=io.copy(c,query,path)
    if n!=1:raise RuntimeError(label+' must have exactly one authenticated record')
    return io.read(path).to_pylist()[0]


def audit_quarantine(a,up,phase,coverage,root,conf,memory):
    reviewed=root.parent/'quarantine_original'
    if not prior.reuse_v101_quarantine(a,up,phase['phase10'],reviewed,conf):
        raise RuntimeError('Original April quarantine audit unavailable')
    paths=[coverage/m/'unresolved_PRIVATE.parquet' for m in ex.MONTHS]
    ledger=Path(up['ledgers'][ex.MONTHS.index('2025-06')])
    metadata=cached_inputs.metadata_for_month(phase['metadata'],'2025-06')
    response=Path(phase['root'])/'download/25/finished/downloaded_metadata.parquet'
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            rows=[]
            for month,path in zip(ex.MONTHS,paths):
                rows.extend((month,g,d) for g,d in c.execute('SELECT game_id,disposition FROM '+io.parq([path])).fetchall())
            if sorted((m,d) for m,g,d in rows)!=[('2024-04',REASON),('2025-06',REASON)] or len({g for m,g,d in rows})!=2:
                raise RuntimeError('Unresolved records differ from the reviewed two-record frame')
            ids={m:g for m,g,d in rows}
            old=c.execute('SELECT game_id FROM '+io.parq([reviewed/'frame_record_PRIVATE.parquet'])).fetchall()
            if old!=[(ids['2024-04'],)]:raise RuntimeError('April quarantine identity changed')
            gid=ids['2025-06'];where='game_id='+io.lit(gid)
            record=require_rows(c,'SELECT * FROM '+io.parq([ledger])+' WHERE '+where,tmp/'june_frame_PRIVATE.parquet','June frame')
            rank=record['retrieval_rank']
            if record['previous_frame'] or record['local_eligibility']!='POTENTIALLY_ELIGIBLE' or not isinstance(rank,bytes) or not threshold(10)<=rank<threshold(25):
                raise RuntimeError('June flag is not in the fixed new 10–25% band')
            if record.get('month','2025-06')!='2025-06':raise RuntimeError('June ledger month changed')
            merged=require_rows(c,'SELECT * FROM '+io.parq(metadata)+' WHERE '+where,tmp/'june_merged_PRIVATE.parquet','June merged metadata')
            if merged.get('cached_conflict_or_prior_flag') is not True:raise RuntimeError('June merged flag changed')
            fresh=require_rows(c,'SELECT * FROM '+io.parq([response])+' WHERE '+where,tmp/'june_completed_response_PRIVATE.parquet','June saved response')
            error_codes=sorted(set(filter(None,(fresh.get('record_errors') or '').split(';'))))
            if not error_codes:raise RuntimeError('June identity does not have the new saved-response flag')
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([tmp/'june_frame_PRIVATE.parquet']))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq([tmp/'june_merged_PRIVATE.parquet']))
            if c.execute('SELECT '+original_plan.readiness_sql()+' FROM f JOIN m USING(game_id)').fetchall()!=[(REASON,)]:
                raise RuntimeError('June readiness disposition changed')
            pools=[coverage/m/'pool.parquet' for m in ex.MONTHS]
            if c.execute('SELECT count(*) FROM '+io.parq(pools)+' WHERE game_id IN ('+','.join(io.lit(g) for g in ids.values())+')').fetchone()[0]:
                raise RuntimeError('Quarantined record entered the retained pool')
            # Save exact membership locally; only aggregate diagnostics enter the public ZIP.
            io.table(tmp/'quarantined_records_PRIVATE.parquet',pa.table(dict(month=[r[0] for r in rows],game_id=[r[1] for r in rows],disposition=[r[2] for r in rows])))
            overlap=[k for k in ex.META_FIELDS if merged.get(k) is not None and fresh.get(k) is not None]
            differing=[k for k in overlap if merged[k]!=fresh[k]]
            known_codes=[s if s.replace('_','').isalnum() and s.upper()==s else 'OTHER_ERROR_CODE_REDACTED' for s in error_codes]
            info=dict(policy=POLICY,review_date='2026-10-05',quarantined_rows=2,
                fixed_frame_rows_retained=True,focal_records_used_in_models=False,substitute_rows_added=0,
                counts_by_cohort=dict(new_phase10=1,increment_10_25=1,new_phase25=2,old_author_clean=0,pooled=2),
                records=[dict(month='2024-04',phase_band='0–10%',reason=REASON,identity_matches_prior_audit=True),
                         dict(month='2025-06',phase_band='10–25%',reason=REASON,saved_response_records=1,
                              response_error_codes=known_codes,compared_nonmissing_metadata_fields=len(overlap),
                              fields_differing_from_completed_response=differing,
                              missing_merged_fields=[k for k in ex.META_FIELDS if merged.get(k) is None],
                              missing_response_fields=[k for k in ex.META_FIELDS if fresh.get(k) is None])],
                full_metadata_reconciliation_complete=False,
                scope='Explicit available-case interim amendment before any 25% behavioral estimates; both records remain unresolved.',
                scientific_limit='The two-row count does not bound coefficient bias. Factual histories and exposure spacing are preserved.')
            io.js(tmp/'summary.json',info);return info
        finally:finish_connection(c,tmp/'spill')
    result=stable_stage(root,conf,build,paths+[reviewed/'_DONE.json',reviewed/'frame_record_PRIVATE.parquet',ledger,response]+metadata+
                        [coverage/m/'pool.parquet' for m in ex.MONTHS])
    io.log('TWO_RECORD_QUARANTINE_AUDITED: April 2024 original + June 2025 flagged response; fixed frame retained; no replacements.')
    return result
