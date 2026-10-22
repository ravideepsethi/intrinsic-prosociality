#!/usr/bin/env python3
from __future__ import annotations
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
from common import *
from design import *
from inputs import authenticate,prepare
from estimate import fit_task
from report import family_report,monthly_report
import argparse,concurrent.futures as cf,fcntl,multiprocessing as mp,platform,traceback

def export(run,result,key,progress,status):
    report=Path(run)/'report';report.mkdir(parents=True,exist_ok=True)
    write(report/'STATUS.json',dict(**status,progress_percent=progress,configuration_sha256=key,
        api_requests=0,engine_evaluations=0,version=VERSION,causal_identification_established=False))
    shutil.copyfile(ROOT/'INTERPRETATION.txt',report/'INTERPRETATION.txt')
    files=[p for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    write(report/'REPORT_MANIFEST.json',[dict(path=str(p.relative_to(report)),bytes=p.stat().st_size,sha256=sha(p)) for p in files])
    dest=Path(result)/f'COUNTDOWN_ESTIMATION_{key[:12]}_{progress:03}.zip';dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(tmp,dest);Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('CHECKPOINT_SAVED '+str(dest))

def make_task(run,key,prepared,spec):
    ident=task_id(spec,prepared['speed']);out=Path(run)/'PRIVATE/models'/ident
    c=db(out.parent/'count_spill',.4,1)
    try:
        _,where,_=selection(spec);n=c.execute('SELECT count(*) FROM '+scan(prepared['path'])+' WHERE '+where).fetchone()[0]
    finally:c.close()
    k=12 if spec.get('month') else 24
    reserved=.65+n*(k+30)*8/1e9
    return dict(id=ident,key=digest([key,prepared['sha256'],spec,prepared['speed']]),source=prepared['path'],
        out=str(out),spec=spec,speed=prepared['speed'],source_stamp=prepared['verified_stamp'],memory=reserved,rows=n,work=max(1,n)*(k+1))

def schedule(tasks,workers,budget,results,remaining_work,benchmark_rate=None):
    pending=sorted(tasks,key=lambda t:t['work'],reverse=True);active={};reserved=0.;measured_work=0.;measured_seconds=0.
    cap=budget-1.5;require(cap>=1.,'Memory budget must be at least 3 GB')
    for t in pending:require(t['memory']<=cap,f"{t['id']} needs estimated {t['memory']:.1f} GB plus 1.5 GB headroom; increase --memory-gb")
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        while pending or active:
            for t in list(pending):
                if len(active)>=workers:break
                if reserved+t['memory']<=cap:
                    pending.remove(t);f=pool.submit(fit_task,t);active[f]=t;reserved+=t['memory']
                    log(f"START {t['id']}: {t['rows']:,} rows, reserved {t['memory']:.1f} GB")
            done,_=cf.wait(active,timeout=30,return_when=cf.FIRST_COMPLETED)
            for f in done:
                t=active.pop(f);reserved-=t['memory']
                try:r=f.result()
                except Exception:
                    for x in active:x.cancel()
                    raise
                results.append(r)
                if t['rows']>=5000 and not r.get('reused') and r['status']=='COMPLETE':
                    measured_work+=t['work'];measured_seconds+=r['seconds']
                log('MODEL_DONE '+t['id']+' '+r['status'])
            weighted_memory=sum(t['memory']*t['work'] for t in tasks)/max(1,sum(t['work'] for t in tasks))
            parallel=max(1.,min(float(workers),cap/max(.1,weighted_memory)))
            serial_rate=measured_seconds/measured_work if measured_work else benchmark_rate
            rate=serial_rate/parallel if serial_rate is not None else None
            left=sum(t['work'] for t in pending)+sum(t['work'] for t in active.values())
            checkpoint=left*rate/60 if rate is not None else None
            finish=(left+remaining_work)*rate/60 if rate is not None else None
            log(f"Models this stage {len(tasks)-len(pending)-len(active)}/{len(tasks)}; {len(active)} workers; reserved {reserved:.1f}/{cap:.1f} GB; "
                +(f'next checkpoint ~{checkpoint:.1f} min, finish ~{finish:.1f} min; rough fit-time estimate, reporting extra' if checkpoint is not None else 'ETA pending first model'))

def main(argv=None):
    p=argparse.ArgumentParser(description='Cached countdown threshold estimation; no API or engine calls.')
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--reuse-feasibility-root',type=Path)
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=4);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args(argv);require(a.project.is_dir(),'Project is not mounted');require(a.memory_gb>=3 and a.workers>=1,'Invalid resource settings')
    code=verify_package();log('PACKAGE_SHA256_OK');started=time.monotonic();workers=min(4,a.workers)
    root=a.project/'derived/replication/countdown_estimation_v100_PRIVATE';root.mkdir(parents=True,exist_ok=True)
    key=digest([code,SPEC,str(a.project.resolve())]);run=root/key[:12];(run/'report').mkdir(parents=True,exist_ok=True)
    (run/'PRIVATE').mkdir(exist_ok=True);progress=0;results=[];status=dict(status='RUNNING',phase='authenticate_feasibility')
    with (root/'run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('A countdown estimation run is already active on this project')
        try:
            require(shutil.disk_usage(root).free>=16*1024**3,'At least 16 GiB of free project-drive space is required')
            write(run/'report/SPECIFICATION.json',SPEC)
            with heartbeat('Verifying completed feasibility cache'):binding=authenticate(a.project,a.reuse_feasibility_root)
            write(run/'PRIVATE/INPUT_BINDING.json',binding)
            write(run/'report/input_authority.json',{k:binding[k] for k in ('key','input_identity','rows','input_manifest_sha256')})
            final=run/'PRIVATE/FINAL.json'
            if final.exists():
                saved=read(final);require(saved['key']==key,'Final run key differs')
                for x in saved['report_files']:verify(x)
                export(run,a.result_dir,key,100,saved['status']);log('COMPLETE: saved verified estimates reused');return 0
            write(run/'report/runtime.json',dict(python=platform.python_version(),duckdb=duckdb.__version__,numpy=np.__version__,
                platform=platform.platform(),workers=workers,memory_budget_gb=a.memory_gb,
                method='symmetric alternating-projection conjugate gradients; original FE-mean gate',
                fit_threads_per_worker=1,checkpoint_units='phases, not equal durations'))
            status['phase']='prepare_numeric_cache'
            with heartbeat('Preparing narrow speed files from cached features'):prepared=prepare(binding,run,a.memory_gb,workers)
            for r in prepared['files']:r['verified_stamp']=stamp(r['path'])
            all_tasks=[]
            for spec in FAMILIES:
                all_tasks.extend(make_task(run,key,r,spec) for r in prepared['files'])
            for month in MONTHS:
                spec=dict(name='monthly_'+month,month=month,clock_multiple=0)
                all_tasks.extend(make_task(run,key,r,spec) for r in prepared['files'])
            table(run/'report/model_plan.csv',[{k:t[k] for k in ('id','speed','rows','memory','work')} for t in all_tasks])
            primary=[t for t in all_tasks if t['spec']['name']=='primary' and t['rows']>0]
            require(primary,'No primary rows')
            # Whole-chooser deterministic benchmark, keeping each selected chooser's complete sample.
            largest=max(primary,key=lambda t:t['rows']);bench=dict(largest)
            bench.update(id='benchmark',out=str(run/'PRIVATE/benchmark'),spec={**largest['spec'],'benchmark':True},
                key=digest([key,'benchmark',largest['source']]))
            status['phase']='benchmark'
            log('Benchmark: whole choosers with ID modulo 64 = 0; estimates stay private')
            b=fit_task(bench);rate=None
            if b['status']=='COMPLETE':
                n=b['counts']['input_rows'];rate=b['seconds']/max(1,n*25)
                write(run/'report/benchmark.json',dict(rows=n,seconds=b['seconds'],sampling='chooser modulo 64',
                    caution='Projection convergence and hardware contention can differ at full scale',
                    rough_total_fit_minutes=rate*sum(t['work'] for t in all_tasks)/workers/60))
                log(f"Benchmark {n:,} rows in {b['seconds']:.1f}s; rough total fits ~{rate*sum(t['work'] for t in all_tasks)/workers/60:.1f} min, plus reporting")
            groups=[(['primary'],25),(['clock_long','clock_twice'],50),(['calendar_august','calendar_september'],75)]
            finished=set()
            for families,pct in groups:
                status['phase']='+'.join(families)
                tasks=[t for t in all_tasks if t['spec']['name'] in families]
                future=sum(t['work'] for t in all_tasks if t['id'] not in finished and t not in tasks)
                schedule(tasks,workers,a.memory_gb,results,future,rate)
                for name in families:
                    with heartbeat('Joint covariance and figures: '+name):family_report(run,name,results)
                finished.update(t['id'] for t in tasks);progress=pct
                status.update(completed_models=len(results),total_models=len(all_tasks),elapsed_seconds=time.monotonic()-started)
                export(run,a.result_dir,key,progress,status)
            status['phase']='monthly_pretrend_diagnostics'
            tasks=[t for t in all_tasks if t['spec'].get('month')]
            schedule(tasks,workers,a.memory_gb,results,0,rate)
            with heartbeat('Monthly joint uncertainty and figures'):monthly_report(run,results)
            table(run/'report/all_model_status.csv',[dict(id=r['id'],status=r['status'],seconds=r['seconds'],**r.get('counts',{})) for r in results])
            for r in binding['files']:require(stamp(r['path'])==r['verified_stamp'],'Input feature changed during run')
            for r in prepared['files']:require(stamp(r['path'])==r['verified_stamp'],'Prepared feature changed during run')
            status.update(status='COMPLETE',phase='finished',completed_models=len(results),total_models=len(all_tasks),
                elapsed_seconds=time.monotonic()-started,interpretation='Adjusted descriptive contrasts; see limitations',
                unsupported_models=sum(r['status']!='COMPLETE' for r in results))
            export(run,a.result_dir,key,100,status)
            files=[record(x) for x in sorted((run/'report').rglob('*')) if x.is_file() and x.name not in ('STATUS.json','REPORT_MANIFEST.json')]
            write(final,dict(key=key,status=status,report_files=files));log('COMPLETE: upload the 100.zip and .sha256');return 0
        except Exception as e:
            status.update(status='BLOCKED',error=str(e),elapsed_seconds=time.monotonic()-started)
            (run/'PRIVATE/ERROR.txt').write_text(traceback.format_exc());export(run,a.result_dir,key,progress,status)
            log('BLOCKED: '+str(e));return 2

if __name__=='__main__':sys.exit(main())
