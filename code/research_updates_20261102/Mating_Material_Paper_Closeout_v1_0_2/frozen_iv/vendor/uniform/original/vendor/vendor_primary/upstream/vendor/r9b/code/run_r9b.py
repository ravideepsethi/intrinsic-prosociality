#!/usr/bin/env python3
"""Offline R9b follow-on; separate immutable output and aggregate-only reports."""
from r9b_common import *
import r9b_inputs as inputs, r9b_models as models
import argparse,fcntl,shutil,zipfile,traceback

def export(root,desktop,conf,progress,status,extra,plan):
    report=root/'report';report.mkdir(exist_ok=True)
    tables={k:[] for k in ['J1_OLS','J2_hours','J3_exposure_specifications','J4_balance','J4_joint_balance','J5_subgroups','J5_compliers',
        'J6_score_models','J6_first_stages','J6_system','J7_act_result','J7_first_stages','J7_system']}
    complete=[]
    for job in plan:
        path=Path(job['output'])/'result.json'
        if not (path.parent/'_DONE.json').exists():continue
        data=u.load(path);complete.append(job['name']+'__'+job['level'])
        name=job['name']
        if name=='primary90':
            tables['J1_OLS'] += [x for x in data['estimates'] if x.get('estimator')=='OLS']
            tables['J5_subgroups'] += [dict(x,subgroup=['all','all']) for x in data['estimates'] if x.get('estimator')=='first_stage']
        if name in [s[0] for s in SPECIFICATIONS]:tables['J3_exposure_specifications']+=data['estimates']
        if name.startswith('hour_'):tables['J2_hours']+=data['estimates']
        if name.startswith('subgroup_'):tables['J5_subgroups']+=data['estimates']
        if job.get('kind')=='compliers':tables['J5_compliers']+=data['compliers']
        if name.startswith('J6_'):
            tables['J6_score_models']+=data['estimates'];tables['J6_first_stages']+=data['first_stages'];tables['J6_system']+=data['system']
        if job.get('kind')=='act':
            tables['J7_act_result']+=data['act_contrasts'];tables['J7_first_stages']+=data['first_stages'];tables['J7_system']+=data['system']
        tables['J4_balance']+=data['balance'];tables['J4_joint_balance']+=data['joint_balance']
    for name,rows in tables.items():r.write_rows(report,name,rows)
    summary=dict(status=status,configuration_sha256=conf,parent_configuration_sha256=R9_CONF,progress_percent=progress,
        completed_models=len(complete),planned_models=len(plan),completed_model_names=complete,definition=DEFINITION_B,
        report_contains='aggregates only; no game or account rows',**extra)
    for level in LEVELS:
        valid=[x for x in tables['J5_subgroups'] if x.get('control_level')==level and x.get('estimator')=='first_stage' and x.get('subgroup')!=['all','all'] and x.get('supported')]
        summary.setdefault('subgroup_summary',[]).append(dict(control_level=level,supported_groups=len(valid),
            negative_first_stages=sum(x['coefficient']<0 for x in valid),intervals_above_zero=sum(x['ci_low']>0 for x in valid)))
    r.io.js(report/'summary.json',summary)
    for f in (PACKAGE/'figure5').glob('*'):shutil.copy2(f,report/f.name)
    if (root/'preflight.json').exists():shutil.copy2(root/'preflight.json',report/'preflight.json')
    if (root/'score_audits.json').exists():shutil.copy2(root/'score_audits.json',report/'score_audits.json')
    inventory=[]
    for p in sorted(report.iterdir()):
        if p.is_file() and p.name!='REPORT_MANIFEST.json':inventory.append(dict(path=p.name,sha256=u.sha(p),bytes=p.stat().st_size))
    r.io.js(report/'REPORT_MANIFEST.json',inventory)
    dest=desktop/f'R9B_REPORT_{conf[:12]}_{progress:03}.zip';temporary=dest.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,p.name)
    os.replace(temporary,dest);dest.with_suffix('.zip.sha256').write_text(u.sha(dest)+'  '+dest.name+'\n')
    u.log('Aggregate checkpoint '+dest.name+'; progress '+str(progress)+'%')

def base_reproduction(root):
    expected=u.load(PACKAGE/'evidence/A_receipt.json');rows=[]
    for level in LEVELS:
        new=u.load(root/'fits'/('primary90__'+level)/'result.json')['estimates']
        for estimate in ['first_stage','reduced_form','2SLS']:
            for outcome in (['y','reached'] if estimate=='reduced_form' else ['received' if estimate=='first_stage' else 'y']):
                old=next(x for x in expected if x.get('control_level')==level and x.get('cohort')=='full' and x.get('estimator')==estimate and x.get('outcome')==outcome)
                now=next(x for x in new if x.get('estimator')==estimate and x.get('outcome')==outcome)
                coef='iv_coefficient' if estimate=='2SLS' else 'coefficient';se='iv_standard_error' if estimate=='2SLS' else 'standard_error'
                u.require(now['n']==old['n'] and now['row_set_sha256']==old['row_set_sha256'],'Baseline row identity failed')
                u.require(np.isclose(now['coefficient'],old[coef],atol=2e-10,rtol=1e-8),'Baseline coefficient differs: '+level+estimate+outcome)
                u.require(np.isclose(now['standard_error'],old[se],atol=2e-10,rtol=1e-8),'Baseline SE differs: '+level+estimate+outcome)
                rows.append(dict(level=level,estimator=estimate,outcome=outcome,passed=True,
                    coefficient_difference=now['coefficient']-old[coef],SE_difference=now['standard_error']-old[se]))
    r.io.js(root/'baseline_reproduction.json',rows);return rows

def make_plan(source,scores,act,root,conf):
    jobs=[];nall=pq.ParquetFile(source).metadata.num_rows
    def add(name,level,**options):
        candidate=options.get('candidate','spaced90');n={'all':nall,'spaced30':3838184,'first':967594}.get(candidate,2682329)
        if options.get('subgroup'):n=min(n,1550000)
        reservation=1.4+n*(1050 if options.get('kind')=='act' else 860)/1024**3
        if options.get('hour'):reservation=max(reservation,5.)
        jobs.append(dict(name=name,input=str(source),scores=str(scores),output=str(root/'fits'/(name+'__'+level)),conf=conf,
            level=level,memory_gb=max(2.,reservation),**options))
    for level in LEVELS:
        for name,candidate,rich,repeat,fe in SPECIFICATIONS:
            add(name,level,candidate=candidate,rich=rich,repeat=repeat,fe=fe,ols=name=='primary90',
                balance=name in ('primary90_without_recipient_history','repeated_recipient_FE'))
        for hour in ['start','last_move']:add('hour_'+hour,level,hour=hour,ols=True)
        for kind,values in [('speed',range(4)),('rating',range(4)),('prior',range(3)),('month',range(24))]:
            for value in values:add('subgroup_'+kind+'_'+str(value),level,subgroup=[kind,value])
        add('compliers',level,kind='compliers')
        for label,score,floor in [('competitive5','competitive',5),('competitive3','competitive',3),('noncompetitive5','noncompetitive',5)]:
            for instrument in [score,'A']:add('J6_'+label+'_'+instrument,level,instruments=[instrument],support=[[score,floor]])
        for label,instruments,kind in [('two_scores',['competitive','noncompetitive'],'two_score'),('joint_rows_A',['A'],'regular')]:
            add('J6_'+label,level,instruments=instruments,kind=kind,support=[['competitive',5],['noncompetitive',5]])
        add('act_result',level,kind='act',act=str(act))
    return jobs

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--r9-root',type=Path);p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args();u.require(1<=a.workers<=10 and 10.5<=a.memory_gb<=11,'Use 1–10 workers and 10.5–11 GiB')
    check_package();r.threads_one();u.no_network()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve();desktop.mkdir(parents=True,exist_ok=True)
    parent=a.r9_root or project/'derived/replication/r9_certified_leave_pair_out_v100_PRIVATE'/R9_CONF[:12]
    config=dict(version=VERSION,definition=DEFINITION_B,package_sha256=u.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'))
    conf=r.io.cfgsha(config);root=project/'derived/replication/r9b_remaining_diagnostics_v100_PRIVATE'/conf[:12]
    u.require(not root.resolve().is_relative_to(parent.resolve()),'R9b cannot write inside R9')
    root.mkdir(parents=True,exist_ok=True);lock=(root/'RUN.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (root/'config.json').exists():u.require(u.load(root/'config.json')==config,'R9b configuration changed')
    else:r.io.js(root/'config.json',config)
    progress=0;plan=[];extra=dict(resource_policy=dict(workers=a.workers,total_planning_GiB=a.memory_gb,BLAS_threads=1,
        ENV_concurrent_workers=2,ENV_DuckDB_GB=3,ENV_OOM_serial_retry_GB=8,projected_Parquet=True),
        optional_J8='OMITTED',run_started_UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    try:
        u.log('R9b starts; provisional total ETA 2–4 hours, revised from completed-task throughput. No API or engine work.')
        with heartbeat('Authenticate certified R9 and frozen wider exposure frames',10,180):bound=inputs.bind(project,parent)
        r.io.js(root/'INPUTS_PRIVATE.json',bound)
        prep=inputs.prepare_source(bound,root/'source',conf,a.memory_gb)
        act=inputs.act_features(bound,project,root/'act_features',conf,a.memory_gb)
        r.io.js(root/'preflight.json',dict(parent_report_reproduced=True,original_expanded_rows=7432712,primary_rows=2682329,
            act_features_rows=pq.ParquetFile(act).metadata.num_rows,source_files_authenticated=True))
        with heartbeat('Authenticate and prepare existing behavior-history indexes',10,170):ojobs=inputs.outcome_jobs(bound,prep,root,conf)
        runtime.mapped(fast.outcome_job,ojobs,min(2,a.workers),a.memory_gb,'Clean wider-frame recipient histories and outcomes',25,150)
        source=inputs.assemble_source(bound,prep,ojobs,root/'clean_source',conf,a.memory_gb)
        queries=inputs.query_shards(source,root/'queries',conf);sjobs=[]
        for s in range(16):
            parts=[x for x in bound['parts'] if x['shard']==s]
            sjobs.append(dict(shard=s,parts=parts,queries=str(queries/f'{s:02}.parquet'),reference=bound['reference'],authors=bound['binding']['author_ids'],
                output=str(root/'scores'/f'{s:02}'),conf=conf,memory_gb=1.+sum(x['rows'] for x in parts)*650/1024**3))
        runtime.mapped(inputs.donor_job,sjobs,a.workers,a.memory_gb,'One donor pass: pooled, competitive and noncompetitive Score A',25,120)
        scores=inputs.combine_scores(sjobs,bound,source,root/'combined_scores',conf,a.memory_gb)
        r.io.js(root/'score_audits.json',[dict(shard=j['shard'],audit=u.load(Path(j['output'])/'audit.json')) for j in sjobs])
        progress=25;export(root,desktop,conf,progress,'SCORES_AND_FROZEN_ROW_BRIDGES_COMPLETE',extra,plan)
        with heartbeat('Extend only missing environment histories',55,110):source,extra['environment']=inputs.environment(bound,source,root/'environment',conf,a.memory_gb,a.workers)
        r.io.js(root/'PREPARED_INPUTS_PRIVATE.json',dict(source=str(source),scores=str(scores),act=str(act)))
        plan=make_plan(source,scores,act,root,conf);r.io.js(root/'MODEL_PLAN_PRIVATE.json',plan)
        baseline=[j for j in plan if j['name']=='primary90']
        runtime.mapped(models.fit_job,baseline,a.workers,a.memory_gb,'Primary OLS and exact R9 numerical reproduction',10,90)
        extra['baseline_reproduction']=base_reproduction(root)
        progress=50;export(root,desktop,conf,progress,'BASELINE_REPRODUCED_OLS_COMPLETE',extra,plan)
        first=[j for j in plan if not j['name'].startswith(('J6_','subgroup_')) and j['name']!='primary90']
        runtime.mapped(models.fit_job,first,a.workers,a.memory_gb,'Hours, exposure variants, balance, compliers and act/result',45,45)
        progress=75;export(root,desktop,conf,progress,'EXPOSURE_AND_ACT_RESULT_MODELS_COMPLETE',extra,plan)
        remaining=[j for j in plan if j['name'].startswith(('J6_','subgroup_'))]
        runtime.mapped(models.fit_job,remaining,a.workers,a.memory_gb,'Subgroup first stages and score partitions',40,0)
        progress=100;extra['run_completed_UTC']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        export(root,desktop,conf,progress,'R9B_COMPLETE',extra,plan)
        u.log('FINISHED. Return R9B_REPORT_'+conf[:12]+'_100.zip, its .sha256, and this log. ETA: complete.')
    except BaseException as error:
        extra['error']=dict(type=type(error).__name__,message=str(error))
        try:export(root,desktop,conf,progress,'STOPPED_RETURN_LOG',extra,plan)
        except Exception:traceback.print_exc()
        raise
    finally:lock.close()
if __name__=='__main__':main()
