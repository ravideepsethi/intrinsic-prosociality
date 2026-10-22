#!/usr/bin/env python3
"""Run the frozen 10% analyses with phase-independent indexes and feature reuse."""
from phase_features import *
from phase_reporting import *
import phase_inputs as inputs_code
import cached_inputs as prior_inputs
import phase_recovery as recovery
import performance_cache as cache
import performance_histories as fast
import performance_screen as screen
import performance_chronology as chron
import performance_migration as migration
from performance_runtime import Runtime
import argparse,fcntl,time,contextlib

ANALYSIS_REL='derived/replication/run2_phase_analysis_v110_PRIVATE'
CACHE_REL='derived/replication/run2_feature_cache_v1_PRIVATE'

def execute(a):
    no_network();started=time.monotonic();verify_release()
    a.project_root=a.project_root.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    a.workers=max(1,min(a.workers,10,os.cpu_count() or 1,int(max(1,(a.memory_gb-2)//1.5))))
    worker_memory=max(.5,(a.memory_gb-2)/a.workers)
    io.log(f'Local workers: {a.workers}; budget {a.memory_gb:g} GiB; per-worker DuckDB cap {worker_memory:.2f} GiB; API requests: zero')
    with io.heartbeat('Authenticating completed local inputs and immutable 10% snapshot'):
        local=authenticate(a);phase=inputs_code.authenticate_phase(a,local)
    sources=recovery.authenticate_coverage(a,local,phase)
    config=dict(version=VERSION,code_sha256=io.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),local_plan=UPSTREAM_PLAN,
        local_receipts=local['input_receipts'],phase=phase,specifications=SPECS,authors=list(AUTHORS),
        metadata_snapshot='completed_phase10_only',metadata_policy=recovery.POLICY,
        prior_coverage_receipts=[r['receipt_sha256'] for r in sources],execution='early_eligibility_indexed_histories_immutable_features')
    conf=io.cfgsha(config);root=a.project_root/ANALYSIS_REL/conf[:12];root.mkdir(parents=True,exist_ok=True)
    shared=a.project_root/CACHE_REL;a.desktop.mkdir(parents=True,exist_ok=True);runtime=Runtime(root)
    with contextlib.ExitStack() as locks:
        lock=locks.enter_context((root/'RUN.lock').open('a+'))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This optimized analysis is already running')
        io.js(root/'config.json',config)
        io.js(a.desktop/'RUN2_PHASE_010_ANALYSIS_LATEST_PRIVATE.json',dict(root=str(root),config_sha256=conf))
        jobs=[dict(r,output=str(root/'coverage'/r['month']),conf=conf) for r in sources]
        coverage=runtime.mapped(recovery.reuse_coverage_job,jobs,a.workers,'Reusing completed coverage Parquets')
        recovery.assert_reviewed_coverage(coverage)
        if sum(r['selected_frame_rows'] for r in coverage)!=phase['summary']['additional_frame_rows']:raise RuntimeError('Fixed 10% frame changed')
        with runtime.stage('Reusing the explicit one-record quarantine'):
            if not recovery.reuse_v101_quarantine(a,local,phase,root/'quarantine',conf):
                recovery.quarantine(local['ledgers'][ex.MONTHS.index('2024-04')],prior_inputs.metadata_for_month(phase['metadata'],'2024-04'),
                    str(Path(phase['root'])/'download/10/finished/downloaded_metadata.parquet'),
                    [str(root/'coverage'/m/'pool.parquet') for m in ex.MONTHS],root/'quarantine',conf,a.memory_gb)
        export(root,a.desktop,conf,coverage,'AVAILABLE_CASE_COVERAGE_COMPLETE_ANALYSIS_PENDING',started)
        with runtime.stage('Authenticating research sources'):
            source=inputs_code.research_inputs(a.project_root,a.workers)
            legacy=migration.authenticate(a,local,phase,source,locks)
        binding=root/'INPUTS_PRIVATE.json'
        if binding.exists() and io.cfgsha(io.load(binding))!=io.cfgsha(source):raise RuntimeError('Research input binding changed')
        io.js(binding,source);ids=list(source['author_ids'].values())
        ordinary=[str(root/'coverage'/m/'pool.parquet') for m in ex.MONTHS]
        with runtime.stage('Original numerical reproduction and shared query preparation'):
            prepared,prepinfo=prepare_queries(ordinary,source['comparison'],root/'prepared',conf,a.memory_gb,
                legacy_outcomes=source['legacy_outcome_parent']['path'],write_shards=False)
        queries=prepared/'queries.parquet'
        with runtime.stage('Checking global account identities'):
            identity,identityinfo=prior_inputs.identity_check(queries,source,root/'identity',conf,a.memory_gb,a.workers)
        with runtime.stage('Early history, cooldown and author eligibility'):
            cheap,cheapinfo=screen.cheap(queries,source['stream'],ids,root/'early',conf,a.memory_gb)
        io.log(f"Early screening: {cheapinfo['new_rows_kept']:,} new queries retained; {cheapinfo['new_rows_skipped']:,} excluded with recorded reasons")
        modules=[PACKAGE/'code'/n for n in ('performance_histories.py','performance_cache.py')]
        lineage=[{k:r[k] for k in ('month','shard','sha256','rows')} for r in source['parts']]
        history_def=cache.definition('monthly_behavior_events_v1',dict(parts=lineage,authors=ids,counts=list(audit.COUNTS)),modules)
        main_def=cache.definition('main_keys_and_future_choices_v1',dict(panels=[r['sha256'] for r in source['panels']]),modules)
        index_def=cache.definition('monthly_lag7_score_sufficient_statistics_v1',dict(parts=lineage,cutoffs=[int(v)-7*DAY for v in STARTS]),modules)
        ref_def=cache.definition('author_clean_reference_v1',dict(parts=lineage,authors=ids,deltas=[io.sha(p) for p in source['deltas']]),[Path(authors.__file__),Path(num.__file__)])
        refconf=io.cfgsha(ref_def);refroot=shared/'reference'/refconf
        removedjobs=[dict(parts=[r['path'] for r in source['parts'] if r['month']==m],ids=ids,conf=refconf,output=str(refroot/'removed'/m)) for m in MONTHS]
        runtime.mapped(authors.extract_author_month,removedjobs,a.workers,'Reusable author reference exclusions')
        with runtime.stage('Reusable author-clean reference'):
            reference,_=authors.prepare_reference(source,[Path(j['output'])/'removed.parquet' for j in removedjobs],refroot/'models',refconf)
        score_def=cache.definition('lag7_pair_excluded_scores_v1',dict(index=io.cfgsha(index_def),reference=refconf,authors=ids),modules+[Path(num.__file__)])
        outcome_def=cache.definition('history_and_later_choice_v1',dict(history=io.cfgsha(history_def),main=io.cfgsha(main_def),authors=ids,panel_end=core.PANEL_END),modules+[Path(audit.__file__)])
        chron_def=cache.definition('first_pair_predecessor_volume_v1',dict(files=source['chron']),[PACKAGE/'code/performance_chronology.py',PACKAGE/'code/phase_chronology.py',PACKAGE/'code/cached_chronology.py',PACKAGE/'code/performance_cache.py',Path(rebuild.__file__)])
        # Completed old features enter the same immutable cache, with their
        # independently authenticated producer and sources checked above.
        if legacy:
            imports=[];lr=Path(legacy['root'])
            for kind,definition,filename,prefix in [('scores',score_def,'scores.parquet','score'),('outcomes',outcome_def,'outcomes.parquet','outcome')]:
                for s in range(16):
                    folder=lr/kind/f'{s:02}'
                    if (folder/'_DONE.json').exists():
                        j=dict(queries=str(lr/'prepared'/f'{prefix}_{s:02}.parquet'),legacy_feature=str(folder/filename),legacy_conf=legacy['conf'],
                            filename=filename,memory=worker_memory,conf=conf,output=str(root/'adopted'/kind/f'{s:02}'))
                        imports.append(cache.attach(j,shared,kind,definition,s))
            runtime.mapped(migration.import_job,imports,a.workers,'Adopting completed v1.0.2 features')
        idxconf=io.cfgsha(index_def)
        ijobs=[dict(parts=[r['path'] for r in source['parts'] if r['shard']==s],memory=worker_memory,conf=idxconf,output=str(shared/'score_index'/idxconf/f'{s:02}')) for s in range(16)]
        scorejobs=[]
        for s in range(16):
            j=dict(queries=str(cheap/f'score_{s:02}.parquet'),index=ijobs[s]['output'],index_job=ijobs[s],reference=str(reference),authors=ids,memory=worker_memory,
                conf=conf,output=str(root/'scores'/f'{s:02}'))
            scorejobs.append(cache.attach(j,shared,'scores',score_def,s))
        runtime.mapped(fast.score_job,scorejobs,a.workers,'Reusable score indexes and missing scores; originals only for legacy rows')
        scorepaths=[str(Path(j['output'])/'scores.parquet') for j in scorejobs]
        with runtime.stage('Early finite-score support'):
            support,supportinfo=screen.supported(cheap/'queries.parquet',scorepaths,root/'support',conf,a.memory_gb)
        hconf=io.cfgsha(history_def);mconf=io.cfgsha(main_def)
        hjobs=[dict(parts=[r['path'] for r in source['parts'] if r['month']==m],authors=ids,memory=worker_memory,conf=hconf,output=str(shared/'history_index'/hconf/m)) for m in MONTHS]
        mjobs=[dict(panel=r['path'],memory=worker_memory,conf=mconf,output=str(shared/'main_index'/mconf/f'{k:02}')) for k,r in enumerate(source['panels'])]
        runtime.mapped(fast.history_index_job,hjobs,a.workers,'Reusable recipient histories')
        runtime.mapped(fast.main_index_job,mjobs,a.workers,'Reusable later-choice and entry indexes')
        rjobs=[dict(queries=str(queries),keys=str(Path(j['output'])/'keys.parquet'),memory=worker_memory,conf=conf,output=str(root/'roles'/f'{k:02}')) for k,j in enumerate(mjobs)]
        runtime.mapped(fast.role_job,rjobs,a.workers,'Original main-panel role checks')
        with runtime.stage('Exact entry labels'):
            labels,_=inputs_code.entry_labels(queries,[str(Path(j['output'])/'roles.parquet') for j in rjobs],source['entry_universe'],root/'entry_labels',conf,a.memory_gb)
        def outcome_jobs(qroot,prefix,outroot):
            jobs=[]
            for s in range(16):
                j=dict(queries=str(qroot/f'{prefix}_{s:02}.parquet'),authors=ids,memory=worker_memory,conf=conf,
                    histories=[str(Path(r['output'])/f'{s:02}.parquet') for r in hjobs],futures=[str(Path(r['output'])/f'{s:02}.parquet') for r in mjobs],output=str(outroot/f'{s:02}'))
                jobs.append(cache.attach(j,shared,'outcomes',outcome_def,s))
            return jobs
        oldjobs=outcome_jobs(cheap,'old_outcome',root/'old_outcomes')
        runtime.mapped(fast.outcome_job,oldjobs,a.workers,'Legacy outcomes for the independent reconstruction check')
        with runtime.stage('Original feature verification before chronology'):
            check_before_chronology(cheap/'queries.parquet',prepared/'baseline_original.parquet',scorepaths,
                [str(Path(j['output'])/'outcomes.parquet') for j in oldjobs],labels/'entry.parquet',root/'baseline_feature_check',conf,a.memory_gb)
        export(root,a.desktop,conf,coverage,'ORIGINAL_FEATURES_VERIFIED_CHRONOLOGY_PENDING',started)
        cj=dict(queries=str(support/'chron_queries.parquet'),memory=a.memory_gb,worker_memory=worker_memory,
                conf=conf,output=str(root/'chronology'),parts_root=str(root/'chron_parts'),legacy=legacy)
        cj=cache.attach(cj,shared,'chronology',chron_def,'all')
        with runtime.stage('Chronology cache lookup, scan and merge'):
            chrinfo=chron.run(cj,source['chron'],a.workers,runtime)
        chronpath=root/'chronology/features.parquet'
        with runtime.stage('First-pair and adjacency eligibility before new follow-up'):
            work,workinfo=screen.after_chronology(support/'queries.parquet',chronpath,root/'work',conf,a.memory_gb,labels/'entry.parquet')
        ojobs=outcome_jobs(work,'outcome',root/'outcomes')
        runtime.mapped(fast.outcome_job,ojobs,a.workers,'Follow-up only for surviving queries; reuse earlier features')
        with runtime.stage('Assembling frozen model samples'):
            assembled,assembly=combine(work/'queries.parquet',prepared/'baseline_original.parquet',scorepaths,
                [str(Path(j['output'])/'outcomes.parquet') for j in ojobs],chronpath,source['stream'],ids,root/'assembled',conf,a.memory_gb,labels/'entry.parquet')
        for cohort in COHORTS:
            for family in SPECS:
                job=dict(sample=str(assembled/(family+'_'+cohort+'.parquet')),family=family,cohort=cohort,output=str(root/'models'/(family+'_'+cohort)),conf=conf)
                runtime.mapped(model_job,[job],1,'Frozen '+family+' regression: '+cohort)
                export(root,a.desktop,conf,coverage,'MODEL_RESULTS_PARTIAL',started,dict(sample_accounting=assembly['sample_accounting']))
        export(root,a.desktop,conf,coverage,'PHASE_010_AVAILABLE_CASE_ANALYSIS_COMPLETE',started,
            dict(preparation={k:v for k,v in prepinfo.items() if k not in ('files','config_sha256')},sample_accounting=assembly['sample_accounting'],
                original_features_reproduced=assembly['original_features_reproduced'],author_targets_excluded=assembly['author_targets_excluded'],
                original_author_rows_retained_for_verification=True,new_author_games_excluded_early=cheapinfo['dispositions'].get('author_focal_game',0),
                chronology={k:v for k,v in chrinfo.items() if k not in ('files','config_sha256')},
                identity={k:v for k,v in identityinfo.items() if k not in ('files','config_sha256')},workers=a.workers,memory_gb=a.memory_gb,
                feature_flow_scope='model-work subset; early/support/work disposition Parquets preserve all prepared candidates',
                cache_design='phase-independent sources and exact game/role/time keys; current row IDs rebound'))
        io.log('10% analyses finished. The continuous downloader remains independent.')

def main():
    workers,memory=defaults();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=BASE);p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=workers);p.add_argument('--memory-gb',type=float,default=memory)
    p.add_argument('--plan',type=Path,help='Completed local-first pointer if moved')
    a=p.parse_args()
    if a.workers<1 or a.memory_gb<4:p.error('Use at least one worker and 4 GiB memory')
    execute(a)

if __name__=='__main__':main()
