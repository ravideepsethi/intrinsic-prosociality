#!/usr/bin/env python3
from __future__ import annotations
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
from util import *
import argparse,fcntl,zipfile,traceback

def package_check():
    p=ROOT/'PACKAGE_MANIFEST.json'
    for r in load(p)['files']:
        f=ROOT/r['path'];require(f.is_file() and sha(f)==r['sha256'],'PACKAGE_DAMAGED: '+r['path'])
    return sha(p)

def lock_parents(project):
    from resume import lock_parent
    handles=[lock_parent(project)]
    auth=load(ROOT/'authority/diagnostic_authority.json')
    parent=project/'output/kac_companion_recovery_v102'/auth['parent_run']
    require(parent.is_dir(),'Reviewed recovery run missing')
    conf=load(parent/'report/CONFIG.json')
    require(all(conf.get(k)==v for k,v in auth['parent_config'].items()),'Reviewed recovery configuration changed')
    roots=[parent,project/'output/kac_companion_resume_v101/23716a25c7252fd1']
    for root in roots:
        if not root.is_dir():continue
        h=(root/'RUN.lock').open('a')
        try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('A companion job is running; no duplicate started') from None
        handles.append(h)
    return handles

def export(run, desktop, tag):
    files=[]
    for p in sorted((run/'report').rglob('*')):
        if p.is_file() and p.name!='REPORT_MANIFEST.json':
            files.append(dict(path=str(p.relative_to(run/'report')),bytes=p.stat().st_size,sha256=sha(p)))
    js(run/'report/REPORT_MANIFEST.json',dict(files=files))
    desktop.mkdir(parents=True,exist_ok=True)
    dest=desktop/('KAC_REPETITION_SENSITIVITY_'+tag+'_'+run.name+'.zip')
    tmp=dest.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((run/'report').rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(run/'report')))
        for n in ('README.md','ANALYSIS_AMENDMENT.md','DIAGNOSTIC_REVIEW.md','IDENTITY_RESUME_NOTES.md','PARTITION_RESUME_NOTES.md','PACKAGE_MANIFEST.json'):
            z.write(ROOT/n,n)
    os.replace(tmp,dest);textfile(dest.with_suffix('.zip.sha256'),sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_RESULT '+str(dest))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--worker-budget',type=int,default=10)
    ap.add_argument('--io-workers',type=int,default=3)
    ap.add_argument('--memory-gb',type=float,default=None)
    ap.add_argument('--self-test',action='store_true')
    a=ap.parse_args();package_sha=package_check()
    if a.self_test:
        log('Running synthetic tests; existing project data are not read or changed')
        import test_sensitivity;test_sensitivity.main()
        import test_resume;test_resume.main()
        import test_partitions;test_partitions.main();return
    require(1<=a.worker_budget<=10 and 1<=a.io_workers<=min(3,a.worker_budget),'Use a per-job budget of 1–10 and 1–3 IO workers')
    require(a.project_root.is_dir(),'External project drive is not mounted')
    locks=lock_parents(a.project_root)
    from handoff import lock_reviewed
    locks.extend(lock_reviewed(a.project_root))
    memory=a.memory_gb or min(12.,max(3.,memory_gb()*.4))
    require(memory>=2,'At least 2 GB memory budget is required')
    conf=dict(version=VERSION,package_sha=package_sha,project=str(a.project_root.resolve()),
              amendment_sha=sha(ROOT/'ANALYSIS_AMENDMENT.md'))
    key=digest(conf);run=a.project_root/'output/kac_repetition_sensitivity_v102'/key[:16]
    run.mkdir(parents=True,exist_ok=True)
    handle=(run/'RUN.lock').open('a')
    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This sensitivity run is already active') from None
    js(run/'report/CONFIG.json',dict(**conf,worker_budget=a.worker_budget,io_workers=a.io_workers,memory_gb=memory))
    js(run/'report/RUNTIME.json',dict(python=platform.python_version(),platform=platform.platform(),
        duckdb=duckdb.__version__,pyarrow=pa.__version__,numpy=np.__version__,pandas=pd.__version__))
    js(run/'report/RESOURCE_POLICY.json',dict(capacity_wait=False,worker_budget_scope='this_job',
        worker_budget=a.worker_budget,io_workers=a.io_workers,memory_gb=memory,
        annotation_workers=max(1,min(a.worker_budget,3,int(memory/2))),whole_chooser_partitions=512))
    states=dict(status='IN_PROGRESS',strict_parent_timestamp_verification='UNRESOLVED',
        receipt_iv='THIRTEEN_COMPLETED_FITS_NOT_RERUN',A2='NOT_RERUN',arena='COMPLETED_RESULT_NOT_RERUN',
        ordinary_loss='ENDING_METADATA_STILL_REQUIRED',incident_share='SEPARATE_DESIGN_STILL_OPEN',
        temporal_concentration='INCIDENT_ADJUSTMENT_STILL_OPEN',
        author_account_exclusion='NOT_APPLIED_ORIGINAL_FROZEN_SAMPLE')
    try:
        from history import catalog,run_history
        from handoff import prepare_latest
        slots(a.worker_budget,1)
        log('Checking existing Parquet sources and reusing authenticated focal projections')
        cat=catalog(a.project_root)
        js(run/'report/HISTORY_INPUTS.json',dict(history_files=len(cat['chronology']),
            history_rows=sum(r['rows'] for r in cat['chronology']),
            sample_fingerprint=cat['main']['fingerprint'],sample_rows=sum(r['rows'] for r in cat['main']['month_records']),
            semantics=cat['history_semantics']))
        with heartbeat('Checking and reusing completed history'):
            previous=prepare_latest(cat,run,key,a.worker_budget,a.io_workers,memory)
        js(run/'report/STATUS.json',states);export(run,a.desktop,'AUDIT')
        require(shutil.disk_usage(run).free>=40*1024**3,'At least 40 GiB free space is required for history and regression checkpoints')
        log('Resuming at December 2024 with whole-account Parquet annotation. No worker-capacity wait; both count scenarios are unchanged.')
        files=run_history(cat,run,key,a.worker_budget,a.io_workers,memory,previous)
        from repetition import run as estimate
        states['repetition']=estimate(files,run,key,a.worker_budget,memory)
        states['status']='SENSITIVITY_COMPLETE_TIMESTAMP_NOT_RECOVERED'
    except Exception as exc:
        # Private traceback can contain identifiers/paths. Export only a diagnostic class.
        textfile(run/'PRIVATE/ERROR.txt',traceback.format_exc())
        states.update(status='BLOCKED_OR_FAILED',error_type=type(exc).__name__,private_error_file='PRIVATE/ERROR.txt')
        log('Stopped safely: '+str(exc))
        raise
    finally:
        from resume import cache_summary
        cache_summary(run);js(run/'report/STATUS.json',states)
        export(run,a.desktop,'RESULT' if states['status']=='SENSITIVITY_COMPLETE_TIMESTAMP_NOT_RECOVERED' else 'PARTIAL')
    log('Both scenarios finished. Upload the RESULT ZIP and its .sha256. The source timestamp remains unrecovered.')

if __name__=='__main__':main()
