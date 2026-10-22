"""Continue the exact reviewed 50% coverage with one additional January flag.

This is a disclosed available-case amendment before 50% estimation, not a
metadata repair. All three focal identities stay in the frame accounting.
"""
from phase50_common import *
import phase50_inputs as checkpoint
import checkpoint_recovery25 as earlier
import phase_recovery as prior
import cached_inputs
import shutil

EVIDENCE=RELEASE/'evidence/failed50'
POLICY='v101_phase50_three_audited_flags_april2024_january2025_june2025'
REASON='CACHE_CONFLICT_OR_PRIOR_FLAG'
require_rows=earlier.require_rows


def expected_month(month):
    d={r['disposition']:r['rows'] for r in io.load(EVIDENCE/'frame_dispositions.json') if r['month']==month}
    endings=[r for r in io.load(EVIDENCE/'coverage_by_ending.json') if r['month']==month]
    return dict(month=month,selected_frame_rows=sum(d.values()),pool_rows=d.get('CACHED_POOL_METADATA',0),
                ordinary_rows=sum(r['rows'] for r in endings if r['status'] in core.NARROW),
                unresolved_rows=d.get(REASON,0),dispositions=d,ending_counts=endings)


def assert_month(actual,expected):
    for k in ('month','selected_frame_rows','pool_rows','ordinary_rows','unresolved_rows','dispositions'):
        if actual.get(k)!=expected[k]:raise RuntimeError('Reviewed 50% coverage changed: '+expected['month']+'/'+k)
    key=lambda r:(r['month'],r['status'],r['speed'])
    if sorted(actual['ending_counts'],key=key)!=sorted(expected['ending_counts'],key=key):
        raise RuntimeError('Reviewed 50% ending counts changed: '+expected['month'])


def bind_previous(a,local,phase):
    auth=io.load(EVIDENCE/'authority.json');conf=auth['config_sha256']
    root=a.project_root/'derived/replication/run2_phase50_analysis_v100_PRIVATE'/conf[:12]
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=conf or config['code_sha256']!=auth['code_sha256'] or config['version']!='1.0.0':
        raise RuntimeError('Reviewed 50% coverage producer changed')
    if config['local_receipts']!=local['input_receipts'] or config['phase']!=phase:
        raise RuntimeError('Reviewed 50% coverage sources changed')
    io.checked(root/'report/summary.json',auth['summary_sha256'])
    if io.load(root/'report/summary.json')['estimates']:
        raise RuntimeError('Expected the reviewed coverage-only report')
    return dict(root=str(root),conf=conf,summary_sha256=auth['summary_sha256'])


def coverage_job(job):
    if not job.get('reuse'):return checkpoint.coverage_job(job)
    threads_one();source=Path(job['reuse']['root'])/'coverage'/job['month']
    receipt=io.complete(source,job['reuse']['conf'])
    if receipt is None:raise RuntimeError('Completed 50% coverage is missing: '+job['month'])
    info=io.load(source/'coverage.json');assert_month(info,expected_month(job['month']))
    names=('coverage.json','pool.parquet','membership_PRIVATE.parquet','unresolved_PRIVATE.parquet')
    if not set(names)<={r['path'] for r in receipt['files']}:raise RuntimeError('Coverage receipt omits required files')
    def build(tmp):
        for name in names:
            try:os.link(source/name,tmp/name)
            except OSError:shutil.copyfile(source/name,tmp/name)
        return dict(info,reused_from_config_sha256=job['reuse']['conf'],source_receipt_sha256=io.sha(source/'_DONE.json'))
    return stable_stage(job['output'],job['conf'],build,[source/'_DONE.json']+[source/n for n in names])[1]


def same(a,b):
    if isinstance(a,float) and isinstance(b,float) and np.isnan(a) and np.isnan(b):return True
    return a==b


def describe_metadata(merged,fresh,cache):
    """Aggregate diagnostics only; never choose a conflicting value."""
    def compare(rows):
        present=[k for k in ex.META_FIELDS if rows and merged.get(k) is not None and rows[0].get(k) is not None]
        return dict(compared_nonmissing_fields=len(present),fields_differing=[k for k in present if not same(merged[k],rows[0][k])])
    errors=sorted(set(code for r in fresh for code in (r.get('record_errors') or '').split(';') if code))
    safe_codes=[s if s.replace('_','').isalnum() and s.upper()==s else 'OTHER_ERROR_CODE_REDACTED' for s in errors]
    differences=[k for k in ex.META_FIELDS if fresh and cache and fresh[0].get(k) is not None and cache[0].get(k) is not None and not same(fresh[0][k],cache[0][k])]
    inherited=bool(cache and cache[0].get('cached_conflict_or_prior_flag'))
    return dict(saved_response_records=len(fresh),pre_download_cache_records=len(cache),response_error_codes=safe_codes,
        pre_download_cache_flag=inherited,response_vs_cache_fields_differing=differences,
        compared_sources_explain_flag=bool(errors or inherited or differences),
        merged_vs_response=compare(fresh),merged_vs_pre_download_cache=compare(cache),
        missing_merged_fields=[k for k in ex.META_FIELDS if merged.get(k) is None],
        missing_response_fields=[k for k in ex.META_FIELDS if fresh and fresh[0].get(k) is None],
        metadata_values_repaired=False,full_metadata_reconciliation_complete=False)


def audit_quarantine(a,up,phase,coverage,root,conf,memory):
    reviewed=root.parent/'quarantine_original'
    if not prior.reuse_v101_quarantine(a,up,phase['phase10'],reviewed,conf):
        raise RuntimeError('Original April quarantine audit unavailable')
    paths=[coverage/m/'unresolved_PRIVATE.parquet' for m in ex.MONTHS]
    pools=[coverage/m/'pool.parquet' for m in ex.MONTHS]
    ledgers={m:Path(up['ledgers'][ex.MONTHS.index(m)]) for m in ('2024-04','2025-01','2025-06')}
    metadata={m:cached_inputs.metadata_for_month(phase['metadata'],m) for m in ledgers}
    responses={m:Path(phase['root'])/f'download/{band}/finished/downloaded_metadata.parquet' for m,band in [('2025-01',50),('2025-06',25)]}
    cache_paths=cached_inputs.metadata_for_month(up['metadata'],'2025-01')
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            rows=[]
            for month,path in zip(ex.MONTHS,paths):
                rows.extend((month,g,d) for g,d in c.execute('SELECT game_id,disposition FROM '+io.parq([path])).fetchall())
            expected=[('2024-04',REASON),('2025-01',REASON),('2025-06',REASON)]
            if sorted((m,d) for m,g,d in rows)!=expected or len({g for m,g,d in rows})!=3:
                raise RuntimeError('Unresolved records differ from the exact reviewed three-record coverage')
            ids={m:g for m,g,d in rows}
            old=c.execute('SELECT game_id FROM '+io.parq([reviewed/'frame_record_PRIVATE.parquet'])).fetchall()
            if old!=[(ids['2024-04'],)]:raise RuntimeError('April quarantine identity changed')
            records=[]
            for month,lo,hi,label in [('2024-04',None,10,'april'),('2025-01',25,50,'january'),('2025-06',10,25,'june')]:
                where='game_id='+io.lit(ids[month])
                record=require_rows(c,'SELECT * FROM '+io.parq([ledgers[month]])+' WHERE '+where,tmp/(label+'_frame_PRIVATE.parquet'),label+' frame')
                rank=record['retrieval_rank']
                if record['previous_frame'] or record['local_eligibility']!='POTENTIALLY_ELIGIBLE' or not isinstance(rank,bytes) or len(rank)!=32 or not (bytes(32) if lo is None else threshold(lo))<=rank<threshold(hi):
                    raise RuntimeError(label+' flag outside its fixed hash band')
                if record.get('month',month)!=month:raise RuntimeError(label+' ledger month changed')
                merged=require_rows(c,'SELECT * FROM '+io.parq(metadata[month])+' WHERE '+where,tmp/(label+'_merged_PRIVATE.parquet'),label+' merged metadata')
                if merged.get('cached_conflict_or_prior_flag') is not True:raise RuntimeError(label+' merged flag changed')
                c.execute('CREATE OR REPLACE VIEW f AS SELECT * FROM '+io.parq([tmp/(label+'_frame_PRIVATE.parquet')]))
                c.execute('CREATE OR REPLACE VIEW m AS SELECT * FROM '+io.parq([tmp/(label+'_merged_PRIVATE.parquet')]))
                if c.execute('SELECT '+original_plan.readiness_sql()+' FROM f JOIN m USING(game_id)').fetchall()!=[(REASON,)]:
                    raise RuntimeError(label+' readiness disposition changed')
                item=dict(month=month,phase_band=f'{lo or 0}–{hi}%',reason=REASON,identity_bound_to_reviewed_coverage=True,hash_band_verified=True)
                if month=='2024-04':item['identity_matches_prior_audit']=True
                else:
                    path=tmp/(label+'_completed_response_PRIVATE.parquet')
                    n=io.copy(c,'SELECT * FROM '+io.parq([responses[month]])+' WHERE '+where,path)
                    if n>1:raise RuntimeError(label+' saved response duplicates its game identity')
                    fresh=io.read(path).to_pylist()
                    if month=='2025-06':
                        if n!=1 or not fresh[0].get('record_errors'):raise RuntimeError('June saved-response flag changed')
                    # If the fixed retrieval plan requested the January game, it must have its saved response.
                    if month=='2025-01' and record.get('retrieval_disposition')=='NEEDS_API' and n!=1:
                        raise RuntimeError('January requested game lacks its completed saved response')
                    prior_cache=[]
                    if month=='2025-01':
                        cp=tmp/'january_pre_download_cache_PRIVATE.parquet'
                        cn=io.copy(c,'SELECT * FROM '+io.parq(cache_paths)+' WHERE '+where,cp)
                        if cn>1:raise RuntimeError('January pre-download aggregate has duplicate identities')
                        prior_cache=io.read(cp).to_pylist()
                    item.update(describe_metadata(merged,fresh,prior_cache))
                records.append(item)
            if c.execute('SELECT count(*) FROM '+io.parq(pools)+' WHERE game_id IN ('+','.join(io.lit(g) for g in ids.values())+')').fetchone()[0]:
                raise RuntimeError('Quarantined record entered the retained pool')
            io.table(tmp/'quarantined_records_PRIVATE.parquet',pa.table(dict(month=[r[0] for r in rows],game_id=[r[1] for r in rows],disposition=[r[2] for r in rows])))
            info=dict(policy=POLICY,review_date='2026-10-07',phase_percent=50,quarantined_rows=3,
                counts_by_cohort=dict(new_phase25=2,increment_25_50=1,new_phase50=3,old_author_clean=0,pooled=3),
                fixed_frame_rows_retained=True,focal_records_used_in_models=False,substitute_rows_added=0,
                records=records,full_metadata_reconciliation_complete=False,
                amendment_scope='The single January 2025 flag in authenticated coverage 6d102a8fae12; no other new exclusions.',
                additional_quarantines_authorized=False,
                scope='Available-case interim analysis before any 50% behavioral estimates. All three focal records remain unresolved.',
                scientific_limit='Three rows are not a bound on coefficient bias. Factual histories and exposure spacing are preserved.')
            io.js(tmp/'summary.json',info);return info
        finally:finish_connection(c,tmp/'spill')
    deps=paths+pools+[reviewed/'_DONE.json',reviewed/'frame_record_PRIVATE.parquet']+list(ledgers.values())+list(responses.values())+cache_paths
    for value in metadata.values():deps+=value
    result=stable_stage(root,conf,build,deps)
    io.log('THREE_RECORD_QUARANTINE_AUDITED: April 2024, January 2025, June 2025; fixed frame retained; no replacements.')
    return result
