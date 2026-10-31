#!/usr/bin/env python3
from env_common import *
import env_prepare as prepare
import env_rates as rates
import env_models as models
import env_report as reporting
import env_status
import env_recovery
import argparse,fcntl,concurrent.futures as cf,multiprocessing as mp
from performance_runtime import invoke

def model_map(jobs,runtime,workers,memory,label,on_update=None):
    jobs=sorted(jobs,key=lambda j:j['memory_estimate_gb'],reverse=True);budget=memory-1.5
    if any(j['memory_estimate_gb']>budget for j in jobs):raise RuntimeError(f'Model requires an estimated {max(j["memory_estimate_gb"] for j in jobs)+1.5:.1f} GiB total budget; completed reports/checkpoints remain reusable. Increase --memory-gb if RAM allows.')
    start=time.monotonic();pending={};metrics=[];failures=[];first_error=None
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        while jobs or pending:
            used=sum(j['memory_estimate_gb'] for j in pending.values())
            while len(pending)<workers:
                k=next((k for k,j in enumerate(jobs) if j['memory_estimate_gb']+used<=budget),None)
                if k is None:break
                job=jobs.pop(k);pending[pool.submit(invoke,models.model_job,job)]=job;used+=job['memory_estimate_gb']
            done,_=cf.wait(pending,timeout=30,return_when=cf.FIRST_COMPLETED)
            for f in done:
                job=pending.pop(f)
                try:
                    _,metric=f.result();metrics.append(metric)
                except Exception as exc:
                    if first_error is None:first_error=exc
                    failures.append(dict(kind=job['kind'],cohort=job['cohort'],environment=job['environment'],error_type=type(exc).__name__,estimates_from_failed_fit_included=False))
                    jobs=[]  # Finish already running fits; do not launch more after failure.
                    io.js(runtime.root/'failure_summary.json',dict(stage=label,failed_models=failures))
                if on_update:on_update('MODEL_STAGE_FAILED_PARTIAL_RESULTS' if failures else 'MODEL_STAGE_IN_PROGRESS')
            io.log(f'{label}: {len(metrics)} fits complete; {len(pending)} active; {len(jobs)} queued; {sum(j["memory_estimate_gb"] for j in pending.values()):.1f} GiB reserved')
    runtime.save(dict(stage=label,kind='memory_weighted_spawn',seconds=time.monotonic()-start,completed_jobs=len(metrics),workers=workers,reused_checkpoints=sum(m['reused_checkpoint'] for m in metrics),failed_jobs=len(failures)))
    if first_error is not None:raise first_error

def model_job(path,kind,cohort,env,root,conf,edges,reproduce=False):
    n=pq.ParquetFile(path).metadata.num_rows
    return dict(input=str(path),kind=kind,cohort=cohort,environment=env,edges=edges,reproduce=reproduce,conf=conf,
        memory_estimate_gb=.8+n*2000/1024**3,output=str(root),
        numerical_audit=str(root.parent.parent/'numerical_progress'/(root.name+'.json')))

def execute(a):
    started=time.monotonic();no_network();verify_package()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve();desktop.mkdir(parents=True,exist_ok=True)
    workers=max(1,min(a.workers,10,os.cpu_count() or 1,int(max(1,(a.memory_gb-2)//1.5))))
    wm=max(.5,(a.memory_gb-2)/workers)
    io.log(f'Up to {workers} workers; total memory budget {a.memory_gb:g} GiB; DuckDB per scan worker {wm:.2f} GiB; zero API calls.')
    with io.heartbeat('Authenticating completed entry diagnostics and receipt cohort'):
        binding=bind(project,a.entry_parent,a.parent)
    config=dict(version=VERSION,package_sha256=io.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),binding=binding,
        design='frozen_entry_bins_direct_roles_pair_excluded_observed_active_resolution_rates_common_sample_XC_ladder_v1')
    conf=io.cfgsha(config);root=project/OUTPUT_REL/conf[:12];root.mkdir(parents=True,exist_ok=True);runtime=Runtime(root)
    with (root/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This environment diagnostic is already running')
        io.js(root/'config.json',config)
        if (root/'failure_summary.json').exists():(root/'failure_summary.json').unlink()
        progress_report=lambda status:reporting.export(root,desktop,conf,status,started)
        try:
            with runtime.stage('Reuse compatible completed preparation from prior environment runs'):
                recovery=env_recovery.adopt_prepared(project,binding,root,conf)
                io.js(root/'recovery.json',recovery)
            with runtime.stage('Verified role classification and frozen score-bin boundaries'):
                eroot,_=prepare.entry_prepare(binding,root/'prepared_entry',conf,a.memory_gb-1)
            with runtime.stage('Audit legacy missing status and recorded expansion endings'):
                _,status_info=env_status.audit_prepared(eroot,root/'status_audit',conf)
            reporting.export(root,desktop,conf,'STATUS_AUDIT_COMPLETE_MODELS_PENDING' if status_info['valid'] else 'STATUS_AUDIT_FAILED_MODELS_NOT_RUN',started)
            if not status_info['valid']:raise RuntimeError('Status audit found a genuine recorded-status disagreement, invalid label or missing expansion metadata. Inspect status_coverage.json in the report above; no rows or labels changed.')
            edges=io.load(eroot/'bins.json')['edges']
            jobs=[model_job(eroot/(c+'.parquet'),'entry',c,False,root/'models'/('quick_'+c),conf,edges,True) for c in COHORTS]
            model_map(jobs,runtime,workers,a.memory_gb,'Reproduce entry results; role and score-bin diagnostics',on_update=progress_report)
            reporting.export(root,desktop,conf,'QUICK_ROLE_AND_SCORE_BIN_DIAGNOSTICS_COMPLETE',started)
            if a.quick_only:
                io.log('Quick-only run requested. Rerun without --quick-only to continue from these checkpoints.');return root
            shared=project/CACHE_REL;reference=shared/'reference'/binding['reference_conf']/'models'
            with runtime.stage('Check complete historical and future-choice indexes'):
                checked_stage_files(reference,binding['reference_conf'],['original.npy','clean.npy'])
                for r in binding['histories']:checked_stage_files(r,binding['history_conf'],[f'{s:02}.parquet' for s in range(16)])
                for r in binding['futures']:checked_stage_files(r,binding['main_conf'],[f'{s:02}.parquet' for s in range(16)])
                for s in range(16):checked_stage_files(shared/'score_index'/binding['index_conf']/f'{s:02}',binding['index_conf'],['people.parquet','pairs.parquet','events.parquet'])
            with runtime.stage('Prepare the frozen receipt cohort without re-spacing'):
                ivq,_=prepare.prepare_iv(binding,root/'iv_queries',conf)
            sjobs=[dict(queries=str(ivq/f'score_{s:02}.parquet'),index=str(shared/'score_index'/binding['index_conf']/f'{s:02}'),reference=str(reference),authors=binding['author_ids'],memory=wm,conf=conf,output=str(root/'iv_scores'/f'{s:02}')) for s in range(16)]
            runtime.mapped(prepare.iv_features_job,sjobs,workers,'Verify original scores and calculate author-clean receipt scores')
            odef=feature_cache.definition('history_and_later_choice_v1',dict(history=binding['history_conf'],main=binding['main_conf'],authors=binding['author_ids'],panel_end=core.PANEL_END),[UPSTREAM/'code'/n for n in ('performance_histories.py','performance_cache.py')]+[Path(audit.__file__)])
            ojobs=[]
            for s in range(16):
                j=dict(queries=str(ivq/f'outcome_{s:02}.parquet'),authors=binding['author_ids'],memory=wm,conf=conf,
                    histories=[str(Path(p)/f'{s:02}.parquet') for p in binding['histories']],futures=[str(Path(p)/f'{s:02}.parquet') for p in binding['futures']],output=str(root/'iv_outcomes'/f'{s:02}'))
                ojobs.append(feature_cache.attach(j,shared,'outcomes',odef,s))
            runtime.mapped(fast.outcome_job,ojobs,workers,'Cached author-clean receipt follow-up and exact original-feature bridge')
            with runtime.stage('Verify original recipient histories/outcomes and assemble clean receipt cohort'):
                ivroot,_=prepare.assemble_iv(ivq/'original.parquet',[str(Path(j['output'])/'scores.parquet') for j in sjobs],[str(Path(j['output'])/'outcomes.parquet') for j in ojobs],binding['author_ids'],root/'iv_assembled',conf,a.memory_gb-1)
            iv=ivroot/'receipt_iv.parquet';ordinary=Path(binding['parent'])/'secondary_prepared/new_phase25.parquet'
            model_map([model_job(iv,'iv','receipt_original_author_clean',False,root/'models/iv_full_support',conf,edges),model_job(ordinary,'ordinary','ordinary_new_phase25',False,root/'models/ordinary_full_support',conf,edges)],runtime,workers,a.memory_gb,'Receipt and ordinary-comparison baselines before environment support restrictions',on_update=progress_report)
            reporting.export(root,desktop,conf,'CLEAN_RECEIPT_AND_ORDINARY_BASELINES_COMPLETE_RATES_PENDING',started)
            with runtime.stage('Build distinct pair/month history requests'):
                req,reqinfo=rates.requests([eroot/'pooled.parquet',iv,ordinary],root/'rate_requests',conf,a.memory_gb-1)
            pjobs=[dict(r,authors=binding['author_ids'],memory=wm,conf=conf,output=str(root/'rate_panels'/f'{k:02}')) for k,r in enumerate(binding['source']['panels'])]
            runtime.mapped(rates.panel_job,pjobs,workers,'Project certified all-state events for both historical roles')
            panels=[]
            for j in pjobs:
                receipt=io.load(Path(j['output'])/'_DONE.json');panels.append(dict(path=str(Path(j['output'])/'events.parquet'),minimum=receipt['minimum'],maximum=receipt['maximum']))
            jobs,plan=rates.chronology_jobs(binding['source']['chron'],reqinfo['windows'],panels,req,root/'rate_chron_parts',conf,wm)
            for j in jobs:j['authors']=binding['author_ids']
            io.js(root/'scan_plan.json',plan)
            io.log(f'Bounded scan: {plan["files_in_range"]}/{plan["files_considered"]} chronology files; {plan["candidate_rows_before_row_group_and_person_pruning"]:,} candidate rows before pruning. Counts only; no chronology sort or adjacency rebuild.')
            runtime.mapped(rates.chronology_job,jobs,workers,'Count past games and observed active resolutions; checkpoint every file')
            with runtime.stage('Reconcile numerator coverage and subtract each focal pair from all counts'):
                rr,_=rates.combine(req,[j['output'] for j in jobs],[p['path'] for p in panels],root/'rates',conf,a.memory_gb-1,workers)
            reporting.export(root,desktop,conf,'ENVIRONMENT_COUNTS_COMPLETE_LINKED_MODELS_PENDING',started)
            fits=[]
            # Primary current 25% entry population plus its fixed disjoint download bands.
            specs=[('entry',c,eroot/(c+'.parquet')) for c in MAIN_COHORTS]+[('iv','receipt_original_author_clean',iv),('ordinary','ordinary_new_phase25',ordinary)]
            for kind,cohort,src in specs:
                with runtime.stage('Attach environment counts: '+cohort):
                    attached,_=rates.attach(src,rr/'rates.parquet',root/'environment_prepared'/cohort,conf,a.memory_gb-1)
                fits.append(model_job(attached/'model.parquet',kind,cohort,True,root/'models'/('environment_'+cohort),conf,edges))
            model_map(fits,runtime,workers,a.memory_gb,'Same-row rate-control ladder, balance, first stage, reduced form and 2SLS',on_update=progress_report)
            reporting.export(root,desktop,conf,'ENVIRONMENT_DIAGNOSTICS_COMPLETE',started)
            io.log('Complete. Return the aggregate report ZIP above. The continuous downloader remains independent.')
        except BaseException:
            reporting.export(root,desktop,conf,'STOPPED_WITH_PARTIAL_RESULTS',started)
            raise
    return root

def main():
    workers,memory=defaults();p=argparse.ArgumentParser(description='Local opponent-environment diagnostics with a quick first report and resumable bounded game-history scan.')
    p.add_argument('--project-root',type=Path,default=BASE);p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--parent',type=Path);p.add_argument('--entry-parent',type=Path)
    p.add_argument('--workers',type=int,default=workers);p.add_argument('--memory-gb',type=float,default=memory)
    p.add_argument('--quick-only',action='store_true',help='Save role/bin diagnostics and stop before the history-count scan; default runs everything continuously')
    a=p.parse_args()
    if a.workers<1 or a.memory_gb<4:p.error('Use at least one worker and at least 4 GiB memory')
    execute(a)
if __name__=='__main__':main()
