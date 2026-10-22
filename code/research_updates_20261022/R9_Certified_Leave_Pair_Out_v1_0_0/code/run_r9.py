#!/usr/bin/env python3
"""One certified R9 configuration, resumable and entirely local."""
from r9_common import *
import r9_inputs as inputs, r9_scores as scores, r9_models as fits, r9_report as report
import argparse, fcntl, contextlib

def reproduce_job(job):
    ul_models.fit_job(job)
    got=u.load(Path(job['output'])/'result.json');want=u.load(job['baseline_result'])
    checks=compare_numbers(got,want)
    return dict(label=Path(job['output']).name,passed=True,coefficient_and_SE_checks=len(checks),
        maximum_absolute_difference=max((x['absolute_difference'] for x in checks),default=0.))

def certify_baseline(root,base,jobs,old_scores,paths,cutoff,conf,workers,memory):
    plan=[]
    for orig in jobs:
        j=dict(orig);label=Path(j['output']).name
        j.update(input=str(paths[j['sample']]),scores=str(old_scores[j['sample']]),output=str(root/'baseline_fits'/label),conf=conf,
            baseline_result=str(base/'fits'/label/'result.json'))
        if j.get('material'):j['material']=str(cutoff/'material/material.parquet')
        plan.append(j)
    checks=runtime.mapped(reproduce_job,plan,workers,memory,'Step 0: reproduce all fourteen saved models',35,150)
    def build(tmp):
        # Bind the saved model results to the separately authenticated aggregate report.
        bytable={k:[] for k in ('B_estimates','B_entry','B_placebo','B_timing','B_balance','B_joint_balance','B_indicator')}
        for j in sorted(jobs,key=lambda x:Path(x['output']).name):
            result=u.load(base/'fits'/Path(j['output']).name/'result.json')
            table='B_timing' if j['cohort']=='timing_common' else dict(S0='B_estimates',F50='B_entry',O50='B_placebo')[j['sample']]
            bytable[table]+=result['B_estimates']
            for k in ('B_balance','B_joint_balance','B_indicator'):bytable[k]+=result[k]
        aggregate=[]
        for k,v in bytable.items():aggregate+=compare_numbers(v,u.load(ROOT/'evidence/baseline'/(k+'.json')),k)
        cert=dict(status='BASELINE_REPRODUCED',baseline=BASELINE,models=14,all_passed=all(v['passed'] for v in checks),
            model_checks=checks,aggregate_coefficient_and_SE_checks=len(aggregate),
            coefficient_absolute_tolerance=2e-10,coefficient_relative_tolerance=2e-8,
            scores_reproduced=['S0','F50'],score_absolute_tolerance=2e-10,
            baseline_untouched=True,archived_reference_SD=r.SD['pooled'])
        r.io.js(tmp/'certificate.json',cert);return dict(passed=True)
    deps=[str(Path(j['output'])/'result.json') for j in plan]+[str(base/'fits'/Path(j['output']).name/'result.json') for j in jobs]
    r.stable_stage(root/'baseline_certification',conf,build,deps)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--baseline-root',type=Path);p.add_argument('--phase-root',type=Path)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    p.add_argument('--learning-split',choices=('none','both'),default='both')
    a=p.parse_args();u.require(1<=a.workers<=10 and 10.9<=a.memory_gb<=11,'Use 1–10 workers and --memory-gb 11')
    verify_package();r.threads_one();u.no_network();started=time.monotonic()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve();desktop.mkdir(parents=True,exist_ok=True)
    package_sha=u.sha(ROOT/'PACKAGE_MANIFEST.sha256');pointer=desktop/'R9_CERTIFIED_LATEST_PRIVATE.json'
    remembered=None
    if pointer.exists():
        candidate=u.load(pointer)
        if candidate.get('package_sha256')==package_sha:
            remembered=candidate
            if not a.phase_root:a.phase_root=Path(candidate['phase_root'])
    with heartbeat('Authenticate baseline and freeze largest completed comparison frames',8,180):
        paths,binding,parts,reference,cutoff,base,oldjobs=inputs.bind_baseline(project,a.baseline_root)
        selected,phase=inputs.select_frames(project,binding,parts,a.phase_root);paths.update(selected)
    conf=r.io.cfgsha(dict(version=VERSION,package_sha256=package_sha,baseline=BASELINE,phase=phase['config_sha256'],
        reference=u.sha(reference),spec=SPEC,learning_split=a.learning_split))
    root=project/'derived/replication/r9_certified_v100_PRIVATE'/conf[:12];root.mkdir(parents=True,exist_ok=True)
    progress=0;extra=dict(phase={k:v for k,v in phase.items() if k!='root'},learning_split=a.learning_split)
    extra['runtime']=dict(python=sys.version.split()[0],numpy=np.__version__,pyarrow=pa.__version__,duckdb=u.duckdb.__version__,
        pandas=u.pd.__version__,platform=u.platform.platform(),workers_ceiling=a.workers,memory_budget_GiB=a.memory_gb,BLAS_threads_per_process=1)
    with contextlib.ExitStack() as locks:
        lock=locks.enter_context((root/'RUN.lock').open('a+'))
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This R9 configuration is already running')
        # Read-only shared lock prevents concurrent baseline writes without modifying its lock file.
        previous=locks.enter_context((base/'RUN.lock').open('r'))
        try:fcntl.flock(previous,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Baseline is still running; no R9 inputs were modified')
        r.io.js(root/'config.json',dict(conf=conf,package_sha256=package_sha,spec=SPEC,phase=phase,learning_split=a.learning_split))
        r.io.js(root/'INPUTS_PRIVATE.json',dict(paths=paths,reference=str(reference),baseline=str(base)))
        r.io.js(pointer,dict(root=str(root),configuration_sha256=conf,package_sha256=package_sha,phase_root=phase['root']))
        try:
            with heartbeat('Verify frame identities, authors, and frozen Phase 50 features',5,175):
                extra['frame_checks']=inputs.frame_checks(paths,binding['author_ids'],root/'frame_checks',conf,a.memory_gb-2)['checks']
                queryroot=scores.prepare_queries(paths,root/'queries',conf)
            scan=[]
            for shard in range(16):
                part=[v for v in parts if v['shard']==shard];nq=pq.ParquetFile(queryroot/f'{shard:02}.parquet').metadata.num_rows
                scan.append(dict(shard=shard,parts=part,authors=binding['author_ids'],queries=str(queryroot/f'{shard:02}.parquet'),reference=str(reference),
                    output=str(root/'donor_scan'/f'{shard:02}'),conf=conf,memory_gb=.8+(sum(v['rows'] for v in part)*550+nq*850)/1024**3))
            runtime.mapped(scores.scan_job,scan,a.workers,a.memory_gb,'Step 0: one source donor scan and old score replay',30,140)
            with heartbeat('Compare reproduced S0/F50 scores to archived scores',3,135):
                old_scores,oldinfo=scores.combine([str(Path(j['output'])/'baseline_scores_PRIVATE.parquet') for j in scan],paths,root/'baseline_scores',conf,a.memory_gb-2,
                    archived={k:base/'scores_combined'/(k+'.parquet') for k in ('S0','F50')})
                old_scores['O50']=inputs.ordinary_subset(paths['O50'],old_scores['F50'],root/'baseline_ordinary_scores',conf,a.memory_gb-2)
            certify_baseline(root,base,oldjobs,old_scores,paths,cutoff,conf,a.workers,a.memory_gb)
            progress=25;report.export(root,desktop,conf,progress,'BASELINE_CERTIFIED',extra)
            newjobs=[dict(events=str(Path(j['output'])/'events_PRIVATE.parquet'),queries=j['queries'],reference=str(reference),
                output=str(root/'new_scores'/f'{j["shard"]:02}'),conf=conf,memory_gb=j['memory_gb']) for j in scan]
            scored=runtime.mapped(scores.new_score_job,newjobs,a.workers,a.memory_gb,'Donor-month A/B/C scores and rebuilt histories',20,110)
            fallback={}
            for shard in scored:
                for row in shard['fallback_models']:
                    key=(row['donor_month_code'],row['chooser_fold'],row['recipient_fold'],row['model_month_code'])
                    if key not in fallback:fallback[key]=dict(row,eligible_source_donor_rows_for_fold=0)
                    fallback[key]['eligible_source_donor_rows_for_fold']+=row['eligible_source_donor_rows_for_fold']
            extra['fallback_models']=[fallback[k] for k in sorted(fallback)]
            for row in extra['fallback_models']:
                row['donor_month']=str(np.datetime64('2023-11','M')+np.timedelta64(row['donor_month_code'],'M'))
                row['model_month']=str(np.datetime64('2023-11','M')+np.timedelta64(row['model_month_code'],'M')) if row['model_month_code']>=0 else None
            extra['fallback_source_count_note']='Source-donor rows per excluded recipient-fold model; the same donor can appear under several recipient folds. Frame-specific affected donor-focal assignments are in I_score_diagnostics.'
            monthly={}
            for shard in scored:
                for item in shard['unique_donors_by_month']:monthly[item['month_code']]=monthly.get(item['month_code'],0)+item['donors']
            extra['source_months']=[dict(month_code=m,month=str(np.datetime64('2023-11','M')+np.timedelta64(m,'M')),eligible_donor_rows=monthly[m]) for m in sorted(monthly)]
            new_scores,_=scores.combine([str(Path(j['output'])/'scores_PRIVATE.parquet') for j in newjobs],paths,root/'scores',conf,a.memory_gb-2,new=True)
            new_scores['O']=inputs.ordinary_subset(paths['O'],new_scores['F'],root/'ordinary_scores',conf,a.memory_gb-2)
            diagpath=report.diagnostics(paths,new_scores,old_scores,root/'score_diagnostics',conf,a.memory_gb-2)
            short=next(v for v in u.load(diagpath) if v['sample']=='S0')['before_fewer_than_five']
            u.require(short==0,'Full-S0 before-only support failed: '+str(short)+' rows below five; count saved in diagnostics, no rows dropped')
            with heartbeat('Prepare learning-history flags and frozen-definition ENV attachment',90,110):
                learning=inputs.learning_flags(paths['S0'],[str(Path(j['output'])/'first_competitive_PRIVATE.parquet') for j in scan],root/'learning_flags',conf,a.memory_gb-2) if a.learning_split=='both' else None
                attached,extra['environment']=inputs.environment(paths,binding,project,root/'environment',conf,a.memory_gb,a.workers)
                paths.update(attached)
            progress=50;report.export(root,desktop,conf,progress,'SCORES_AND_CONTROLS_COMPLETE',extra)
            common=dict(root=root/'fits',conf=conf)
            oldrows=u.load(ROOT/'evidence/baseline/B_estimates.json')
            allrow=next(v for v in oldrows if v['exposure_screen']=='all')
            neutralrow=next(v for v in oldrows if v['exposure_screen']=='neutral')
            timingrow=u.load(ROOT/'evidence/baseline/B_timing.json')[0]
            primary=fits.make_job(paths['S0'],new_scores['S0'],**common,label='A_full__X0_ENV_indicator',sample='S0_full',level='X0_ENV_indicator',
                balance=True,figure=True,implied_bias=True,expected_n=2682329,expected_row_hash=allrow['row_set_sha256'])
            pi=runtime.mapped(fits.fit_job,[primary],a.workers,a.memory_gb,'Primary S0 model and reference scale',8,70)[0]
            sd=pi['primary_score_SD'];extra['primary_score_SD']=sd
            jobs=[]
            for level in LEVELS:
                def add(label,sample,key='S0',**kw):
                    expected=(timingrow if kw.get('cohort')=='common' else neutralrow if kw.get('material') else allrow) if key=='S0' and not kw.get('learning') else None
                    if expected:kw.update(expected_n=expected['n'],expected_row_hash=expected['row_set_sha256'])
                    jobs.append(fits.make_job(paths[key],new_scores[key],**common,label=label+'__'+level,sample=sample,level=level,primary_sd=sd,**kw))
                if level!='X0_ENV_indicator':add('A_full','S0_full',balance=True,implied_bias=True)
                add('A_neutral','S0_neutral',material=str(cutoff/'material/material.parquet'),balance=True)
                add('B_full','S0_full',variant='B')
                for variant in ('A','B','C'):add('C_common_'+variant,'S0_common',variant=variant,cohort='common')
                add('D_ordinary','O'+str(phase['phase_percent']),key='O',kind='ordinary',balance=True)
                add('E_entry','F'+str(phase['phase_percent']),key='F',kind='entry',balance=True,influence=False)
                add('bridge_month','S0_full',history='old',log_kind='log1p')
                add('bridge_oldscore','S0_full',score_recipe='old',old_scores=str(old_scores['S0']))
                if learning:
                    for definition in ('full','90'):
                        for experienced in (False,True):
                            add('learning_'+definition+'_'+str(int(experienced)),'S0_learning',learning=str(learning),learning_definition=definition,experienced=experienced)
            r.io.js(root/'MODEL_PLAN_PRIVATE.json',[primary]+jobs)
            runtime.mapped(fits.fit_job,jobs,a.workers,a.memory_gb,'R9 models, balance, timing and optional learning splits',60,15)
            progress=75;report.export(root,desktop,conf,progress,'MODELS_COMPLETE_CONTRASTS_PENDING',extra)
            contrasts=[]
            for level in LEVELS:
                def contrast(label,left,right,fields):
                    contrasts.append(dict(label=label+'__'+level,level=level,left=str(root/'fits'/(left+'__'+level)),right=str(root/'fits'/(right+'__'+level)),
                        output=str(root/'contrasts'/(label+'__'+level)),conf=conf,fields=fields,primary_sd=sd,memory_gb=9.3,sql_memory=a.memory_gb-2))
                contrast('after_minus_before','C_common_C','C_common_B',['y','reached','iv_y'])
                contrast('S0_minus_ordinary','A_full','D_ordinary',['y','reached'])
                if learning:
                    for definition in ('full','90'):contrast('learning_'+definition+'_experienced_minus_unexposed','learning_'+definition+'_1','learning_'+definition+'_0',['y','reached','iv_y'])
            runtime.mapped(fits.contrast_job,contrasts,a.workers,a.memory_gb,'Stacked shared-covariance contrasts',15,0)
            gate,_=report.adoption(root);extra['elapsed_seconds']=time.monotonic()-started
            progress=100;status='COMPLETE_ADOPTION_REVIEW_REQUIRED' if gate['status'].startswith('REVIEW_REQUIRED') else 'COMPLETE_WITHIN_ADOPTION_THRESHOLD'
            report.export(root,desktop,conf,progress,status,extra)
            u.log('FINISHED: return R9_CERTIFIED_REPORT_'+conf[:12]+'_100.zip, its .zip.sha256 sidecar, and this log.')
        except BaseException as error:
            extra['error_type']=type(error).__name__;extra['elapsed_seconds']=time.monotonic()-started
            try:report.export(root,desktop,conf,progress,'STOPPED_RETURN_LOG',extra)
            except Exception as secondary:u.log('Stopped-report export failed: '+str(secondary))
            raise

if __name__=='__main__':main()
