#!/usr/bin/env python3
"""Offline analysis of the completed fixed 10% sample, alongside the downloader."""
from phase_features import *
from phase_reporting import *
import argparse,fcntl,time
import phase_inputs as inputs_code
import cached_inputs as prior_inputs
import phase_chronology as chronology
import cached_histories as histories
import phase_recovery as recovery

ANALYSIS_REL='derived/replication/run2_phase_analysis_v102_PRIVATE'

def execute(a):
    no_network();started=time.monotonic();verify_release()
    a.project_root=a.project_root.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    a.workers=max(1,min(a.workers,10,int(max(1,(a.memory_gb-2)//1.5))))
    io.log(f'Local workers: {a.workers}; memory budget {a.memory_gb:g} GiB; API requests: zero')
    with io.heartbeat('Authenticating completed local inputs and immutable 10% snapshot'):
        local=authenticate(a);phase=inputs_code.authenticate_phase(a,local)
    sources=recovery.authenticate_coverage(a,local,phase)
    config=dict(version=VERSION,code_sha256=io.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),
                local_plan=UPSTREAM_PLAN,local_receipts=local['input_receipts'],
                phase=phase,specifications=SPECS,authors=list(AUTHORS),metadata_snapshot='completed_phase10_only',
                metadata_policy=recovery.POLICY,prior_coverage_receipts=[r['receipt_sha256'] for r in sources])
    conf=io.cfgsha(config);root=a.project_root/ANALYSIS_REL/conf[:12];root.mkdir(parents=True,exist_ok=True)
    a.desktop.mkdir(parents=True,exist_ok=True)
    with (root/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This 10% analysis is already running')
        io.js(root/'config.json',config)
        io.js(a.desktop/'RUN2_PHASE_010_ANALYSIS_LATEST_PRIVATE.json',dict(root=str(root),config_sha256=conf))
        jobs=[dict(r,output=str(root/'coverage'/r['month']),conf=conf) for r in sources]
        coverage=io.mapped(recovery.reuse_coverage_job,jobs,a.workers,'Reusing completed coverage Parquets')
        if sum(r['selected_frame_rows'] for r in coverage)!=phase['summary']['additional_frame_rows']:
            raise RuntimeError('Fixed 10% frame does not reproduce the completed report')
        recovery.assert_reviewed_coverage(coverage)
        with io.heartbeat('Preserving and diagnosing the one flagged focal record'):
            if not recovery.reuse_v101_quarantine(a,local,phase,root/'quarantine',conf):
                recovery.quarantine(local['ledgers'][ex.MONTHS.index('2024-04')],
                    prior_inputs.metadata_for_month(phase['metadata'],'2024-04'),
                    str(Path(phase['root'])/'download/10/finished/downloaded_metadata.parquet'),
                    [str(root/'coverage'/m/'pool.parquet') for m in ex.MONTHS],root/'quarantine',conf,a.memory_gb)
        export(root,a.desktop,conf,coverage,'AVAILABLE_CASE_COVERAGE_COMPLETE_ANALYSIS_PENDING',started)
        io.log('One flagged April 2024 focal record is quarantined and retained in the fixed frame. Proceeding with the verified available-case sample; no replacement row or API call.')
        io.log(f"Pool games before chronology: {sum(r['pool_rows'] for r in coverage):,}; ordinary endings: {sum(r['ordinary_rows'] for r in coverage):,}")
        with io.heartbeat('Authenticating history and chronology inputs'):source=inputs_code.research_inputs(a.project_root,a.workers)
        binding=root/'INPUTS_PRIVATE.json'
        if binding.exists() and io.cfgsha(io.load(binding))!=io.cfgsha(source):
            raise RuntimeError('Research input binding changed; completed analysis checkpoints were not reused')
        io.js(binding,source)
        ordinary=[str(root/'coverage'/m/'pool.parquet') for m in ex.MONTHS]
        with io.heartbeat('Reproducing original placebo and entry estimates; preparing shared queries'):
            prepared,prepinfo=prepare_queries(ordinary,source['comparison'],root/'prepared',conf,a.memory_gb,
                legacy_outcomes=source['legacy_outcome_parent']['path'])
        io.log('ORIGINAL_SCHEMA_RECOVERED; original placebo and entry estimates reproduced')
        export(root,a.desktop,conf,coverage,'ORIGINAL_SCHEMA_AND_ESTIMATES_VERIFIED_ANALYSIS_PENDING',started)
        queries=prepared/'queries.parquet'
        with io.heartbeat('Checking global account identities'):
            identity,identityinfo=prior_inputs.identity_check(queries,source,root/'identity',conf,a.memory_gb,a.workers)
        ids=list(source['author_ids'].values())
        removedjobs=[dict(parts=[r['path'] for r in source['parts'] if r['month']==m],ids=ids,
            output=str(root/'removed'/m),conf=conf) for m in MONTHS]
        io.mapped(authors.extract_author_month,removedjobs,a.workers,'Removing author decisions from the historical reference')
        reference,_=authors.prepare_reference(source,[Path(j['output'])/'removed.parquet' for j in removedjobs],root/'reference',conf)
        scorejobs=[dict(queries=str(prepared/f'score_{s:02}.parquet'),parts=[r['path'] for r in source['parts'] if r['shard']==s],
            shard=s,reference=str(reference),authors=ids,conf=conf,output=str(root/'scores'/f'{s:02}')) for s in range(16)]
        io.mapped(histories.score_job,scorejobs,a.workers,'Exact author-clean leniency scores')
        hjobs=[dict(queries=str(queries),parts=[r['path'] for r in source['parts'] if r['month']==m],month=m,authors=ids,
            memory=a.memory_gb/a.workers,output=str(root/'history'/m),conf=conf) for m in MONTHS]
        io.mapped(histories.history_month_job,hjobs,a.workers,'Recipient histories')
        fjobs=[dict(queries=str(queries),panel=r['path'],memory=a.memory_gb/a.workers,output=str(root/'future'/f'{k:02}'),conf=conf)
            for k,r in enumerate(source['panels'])]
        io.mapped(inputs_code.future_and_roles_job,fjobs,a.workers,'Certified main-panel future choices')
        ojobs=[dict(queries=str(prepared/f'outcome_{s:02}.parquet'),shard=s,authors=ids,
            original_histories=[str(Path(j['output'])/f'original_{s:02}.parquet') for j in hjobs],
            clean_histories=[str(Path(j['output'])/f'clean_{s:02}.parquet') for j in hjobs],
            futures=[str(Path(j['output'])/f'{s:02}.parquet') for j in fjobs],output=str(root/'outcomes'/f'{s:02}'),conf=conf) for s in range(16)]
        io.mapped(histories.outcomes_job,ojobs,a.workers,'Complete 90-day outcomes')
        with io.heartbeat('Constructing exact original entry definitions'):
            labels,_=inputs_code.entry_labels(queries,[str(Path(j['output'])/'roles.parquet') for j in fjobs],source['entry_universe'],root/'entry_labels',conf,a.memory_gb)
        with io.heartbeat('Verifying original features before the long chronology scan'):
            check_before_chronology(queries,prepared/'baseline_original.parquet',
                [str(Path(j['output'])/'scores.parquet') for j in scorejobs],
                [str(Path(j['output'])/'outcomes.parquet') for j in ojobs],labels/'entry.parquet',
                root/'baseline_feature_check',conf,a.memory_gb)
        io.log('ORIGINAL_FEATURES_REPRODUCED_BEFORE_CHRONOLOGY')
        export(root,a.desktop,conf,coverage,'ORIGINAL_FEATURES_VERIFIED_CHRONOLOGY_PENDING',started)
        cprep,cpinfo=chronology.prepare_chronology(queries,root/'chron_queries',conf,a.memory_gb)
        if cpinfo['rows']:
            # Future files cannot affect any chronological feature; older files remain.
            chjobs=[dict(r,latest=cpinfo['latest_start'],people=str(cprep/'people.parquet'),pairs=str(cprep/'pairs.parquet'),
                focal=str(cprep/'focal.parquet'),roles=str(cprep/'roles.parquet'),memory=a.memory_gb/a.workers,conf=conf,output=str(root/'chron_parts'/f"{r['file_index']:04}"))
                for r in source['chron'] if r['minimum'] is None or r['minimum']<=cpinfo['latest_start']]
            chjobs.sort(key=lambda r:r['rows'],reverse=True)
            io.log(f'Chronology: {len(chjobs)} files; all earlier history retained. This is the longest local step.')
            io.mapped(chronology.chronology_job,chjobs,a.workers,'First meetings, adjacency and all-game volume')
            with io.heartbeat('Combining chronological features'):
                chrout,chrinfo=chronology.merge_chronology(queries,cprep,[Path(j['output']) for j in chjobs],root/'chronology',conf,a.memory_gb,a.workers)
        else:
            def empty(tmp):io.table(tmp/'features.parquet',pa.table({'row_id':pa.array([],type=pa.int64()),'eligible_main':pa.array([],type=pa.bool_()),'first_observed_pair':pa.array([],type=pa.bool_()),'pre_games_30d':pa.array([],type=pa.int64())}))
            chrout,chrinfo=io.stage(root/'chronology',conf,empty)
        with io.heartbeat('Assembling samples and verifying the original features'):
            assembled,assembly=combine(queries,prepared/'baseline_original.parquet',[str(Path(j['output'])/'scores.parquet') for j in scorejobs],
                [str(Path(j['output'])/'outcomes.parquet') for j in ojobs],chrout/'features.parquet',source['stream'],ids,root/'assembled',conf,a.memory_gb,labels/'entry.parquet')
        mjobs=[dict(sample=str(assembled/(family+'_'+cohort+'.parquet')),family=family,cohort=cohort,
                    output=str(root/'models'/(family+'_'+cohort)),conf=conf)
               for cohort in COHORTS for family in SPECS]
        # Fits materialize dense absorbed-design and cluster-score arrays. Run one
        # at a time; parallel Parquet/history workers do not overlap this stage.
        for job in mjobs:
            io.mapped(model_job,[job],1,'Frozen '+job['family']+' regression: '+job['cohort'])
            export(root,a.desktop,conf,coverage,'MODEL_RESULTS_PARTIAL',started,
                   dict(sample_accounting=assembly['sample_accounting']))
        export(root,a.desktop,conf,coverage,'PHASE_010_AVAILABLE_CASE_ANALYSIS_COMPLETE',started,
            dict(preparation={k:v for k,v in prepinfo.items() if k not in ('files','config_sha256')},
                 sample_accounting=assembly['sample_accounting'],original_features_reproduced=assembly['original_features_reproduced'],
                 author_targets_excluded=assembly['author_targets_excluded'],
                 chronology={k:v for k,v in chrinfo.items() if k not in ('files','config_sha256')},
                 identity={k:v for k,v in identityinfo.items() if k not in ('files','config_sha256')},
                 workers=a.workers,memory_gb=a.memory_gb))
        io.log('10% analyses finished. The continuous downloader remains independent.')

def main():
    workers,memory=defaults();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=BASE);p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=workers);p.add_argument('--memory-gb',type=float,default=memory)
    p.add_argument('--plan',type=Path,help='Completed local-first pointer, if moved from its normal Desktop path')
    a=p.parse_args()
    if a.workers<1 or a.memory_gb<4:p.error('Use at least one worker and 4 GiB memory')
    execute(a)

if __name__=='__main__':main()
