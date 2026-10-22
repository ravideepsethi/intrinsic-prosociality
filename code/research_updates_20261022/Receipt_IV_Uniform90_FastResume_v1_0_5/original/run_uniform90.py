#!/usr/bin/env python3
"""Run the complete uniform90/no-spacing migration and diagnostics."""
from uniform_common import *
import argparse,fcntl,subprocess,signal,zipfile,platform,contextlib
STAGES=['authenticate','selection','features','receipt_models','comparison_auth','comparison_candidates','comparison_chronology','metadata','comparison_frames','comparison_models']
MILESTONES={'selection':25,'features':50,'receipt_models':75,'comparison_models':100}

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11.)
    for name in ['r12-root','r9-root','local-plan','reuse-run','reuse-chronology']:p.add_argument('--'+name,type=Path)
    p.add_argument('--offline',action='store_true',help='Stop with a metadata-needs report if expanded comparisons require uncached game metadata. No stockfish is used in any mode.')
    p.add_argument('--preflight-only',action='store_true');p.add_argument('--self-test',action='store_true')
    p.add_argument('--_stage',choices=STAGES,help=argparse.SUPPRESS)
    return p

def verify():
    manifest=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        digest,name=line.split('  ',1);p=(ROOT/name).resolve()
        require(p.is_relative_to(ROOT),'Unsafe package manifest path');require(sha(p)==digest,'Package file changed: '+name)
    return sha(manifest)

def checkpoint(a,run,conf,state,progress,error=None,preflight=False):
    status='FAILED' if error else ('PREFLIGHT_COMPLETE' if preflight else 'COMPLETE' if progress==100 else 'IN_PROGRESS')
    save(run/'report/STATUS.json',dict(status=status,configuration_sha256=conf,version=VERSION,milestone_percent=progress,
        stages=state,error=error,receipt_models_complete=state.get('receipt_models',{}).get('status')=='COMPLETE',
        expanded_entry_and_placebo_complete=state.get('comparison_models',{}).get('status')=='COMPLETE',rule=RULE90))
    records=[]
    for prefix,folder in [('receipt',run/'report'),('comparisons',run/'comparisons/report')]:
        if folder.exists():
            for p in sorted(folder.iterdir()):
                if p.is_file():records.append((prefix+'/'+p.name,p))
    dest=a.result_dir/('UNIFORM90_IV_'+conf[:12]+f'_{progress:03}.zip');tmp=dest.with_suffix('.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,p in records:z.write(p,name)
        z.writestr('REPORT_MANIFEST.json',json.dumps([dict(path=n,sha256=sha(p),bytes=p.stat().st_size) for n,p in records],indent=2))
        z.write(ROOT/'README.txt','README.txt')
        if (run/'run.log').exists():z.write(run/'run.log','run.log')
    os.replace(tmp,dest);Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('CHECKPOINT_SAVED '+str(dest))

def execute(a,run,conf):
    if a._stage=='authenticate':
        primary.bind(a,run,conf);mark_legacy_reports(run);save(run/'report/definition90.json',RULE90);return
    b=load(run/'PRIVATE/BOUND.json')
    if a._stage=='selection':receipt_selection(a,run,conf,b)
    elif a._stage=='features':
        from uniform_features import receipt_frames
        receipt_frames(a,run,conf,b)
    elif a._stage=='receipt_models':
        from uniform_models import receipt_models,overlap_audit
        receipt_models(a,run,conf,b);overlap_audit(a,run,conf)
    else:
        import uniform_comparisons as comp
        cr=run/'comparisons';(cr/'PRIVATE').mkdir(parents=True,exist_ok=True);(cr/'report').mkdir(exist_ok=True)
        if a._stage=='comparison_auth':comp.prepare90(a,cr,conf);return
        cb=load(cr/'PRIVATE/BINDING90.json')
        if a._stage=='comparison_candidates':
            from uniform_candidates import candidates
            candidates(a,cr,conf,cb)
        elif a._stage=='comparison_chronology':comp.chronology90(a,cr,conf,cb)
        elif a._stage=='metadata':comp.metadata90(a,cr,conf,cb)
        elif a._stage=='comparison_frames':comp.frames90(a,cr,conf,cb,run)
        elif a._stage=='comparison_models':comp.models90(a,cr,conf,cb,run)

@contextlib.contextmanager
def prior_locks(project,run):
    with contextlib.ExitStack() as stack:
        for p in sorted((project/'derived/replication').glob('*PRIVATE/*/RUN.lock')):
            if p.parent==run:continue
            f=stack.enter_context(p.open('r'))
            try:fcntl.flock(f.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Another research run is active: '+str(p.parent)+'. Stop that terminal before resuming this run.')
        yield

def main():
    a=parser().parse_args()
    if a.self_test:return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)
    manifest=verify();a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve()
    a.r12_root=(a.r12_root or a.project/'derived/replication/r12_r13_followups_v100_PRIVATE'/R12_PREFIX).expanduser().resolve()
    a.reuse_run=(a.reuse_run or a.project/'derived/replication/alltime_entry_placebo_v100_PRIVATE/56739829cf4a').expanduser().resolve()
    a.reuse_chronology=(a.reuse_chronology or a.project/'derived/replication/alltime_entry_placebo_v102_PRIVATE/25d22fd1d9e9').expanduser().resolve()
    for k in ('r9_root','local_plan'):
        if getattr(a,k) is not None:setattr(a,k,getattr(a,k).expanduser().resolve())
    require(a.project.is_dir(),'Project drive is not mounted: '+str(a.project))
    require(1<=a.workers<=10 and 10.5<=a.memory_gb<=11,'Use 1–10 workers and 10.5–11 GiB')
    config=dict(version=VERSION,manifest_sha256=manifest,rule=RULE90,project=str(a.project),
        **{k:str(getattr(a,k)) if getattr(a,k) is not None else None for k in ('r12_root','r9_root','local_plan','reuse_run','reuse_chronology')})
    conf=key(config);run=a.project/'derived/replication/receipt_iv_uniform90_v100_PRIVATE'/conf[:12]
    (run/'PRIVATE').mkdir(parents=True,exist_ok=True);(run/'report').mkdir(exist_ok=True);a.result_dir.mkdir(parents=True,exist_ok=True)
    if a._stage:
        if a._stage!='metadata' or a.offline:frozen.u.no_network()
        with heartbeat('Stage '+a._stage):execute(a,run,conf)
        return 0
    require(shutil.disk_usage(run).free>=100*2**30,'At least 100 GiB free is required for new frames, disk-backed models, and comparison chronology spill')
    if (run/'config.json').exists():require(load(run/'config.json')==config,'Run definition differs')
    else:save(run/'config.json',config)
    statepath=run/'PRIVATE/STATE.json';state=load(statepath) if statepath.exists() else {};progress=0
    save(run/'report/execution.json',dict(python=platform.python_version(),workers_requested=a.workers,memory_budget_gib=a.memory_gb,
        large_parallel_tasks_at_most=2,model_workers=1,model_matrix='disk backed',duckdb_covariance_gb=4.,
        metadata='reuse authenticated cached records; serial fetch of unresolved IDs unless --offline',
        ETA='Stage/task ETA after measured throughput; total runtime not benchmarked for this new full frame'))
    with prior_locks(a.project,run),(run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This Uniform90 run is already active')
        save(a.result_dir/'UNIFORM90_LATEST_PRIVATE.json',dict(root=str(run),configuration_sha256=conf))
        log('Uniform90: all eligible exposures; no spacing; retained legacy results; 25/50/75/100 stage checkpoints. Largest jobs use at most two workers; models run serially.')
        for name in STAGES:
            started=time.monotonic();state[name]=dict(status='RUNNING');save(statepath,state)
            with (run/'run.log').open('a',buffering=1) as logf:
                child=subprocess.Popen([sys.executable,str(ROOT/'run_uniform90.py'),*sys.argv[1:],'--_stage',name],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
                try:
                    for line in child.stdout:print(line,end='',flush=True);logf.write(line)
                    code=child.wait()
                except KeyboardInterrupt:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=20)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    state[name]=dict(status='INTERRUPTED');save(statepath,state);checkpoint(a,run,conf,state,progress,'Interrupted; rerun the same command to resume');return 130
            state[name]=dict(status='COMPLETE' if code==0 else 'FAILED',exit_code=code,seconds=time.monotonic()-started);save(statepath,state)
            if code:checkpoint(a,run,conf,state,progress,'Stage '+name+' failed; see run.log');return code
            if name in MILESTONES:progress=MILESTONES[name];checkpoint(a,run,conf,state,progress)
            if a.preflight_only and name=='authenticate':checkpoint(a,run,conf,state,0,preflight=True);return 0
        log('COMPLETE: return UNIFORM90_IV_'+conf[:12]+'_100.zip and its .sha256 for review.')
    return 0

if __name__=='__main__':raise SystemExit(main())
