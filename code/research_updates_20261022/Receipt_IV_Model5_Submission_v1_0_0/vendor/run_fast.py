#!/usr/bin/env python3
"""Authenticated continuation of an existing Uniform90 v1.0.0 run."""
from fast_bootstrap import *
import run_uniform90 as original
import argparse,fcntl,subprocess,signal,platform,contextlib

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resume-root',type=Path)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=None,help='Default: detected CPU count')
    p.add_argument('--memory-gb',type=float,default=None,help='Default: 75%% of detected physical memory, leaving at least 3.5 GiB')
    p.add_argument('--offline',action='store_true')
    p.add_argument('--preflight-only',action='store_true')
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--_stage',choices=original.STAGES,help=argparse.SUPPRESS)
    return p

def verify():
    manifest=FAST_ROOT/'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        digest,name=line.split('  ',1);p=(FAST_ROOT/name).resolve()
        require(p.is_relative_to(FAST_ROOT),'Unsafe package path')
        require(sha(p)==digest,'Optimized package changed: '+name)
    return sha(manifest),original.verify()

def bind_resume(a,parent_manifest):
    require(a.resume_root is not None,'Pass --resume-root for the existing v1.0.0 run')
    a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve()
    run=a.resume_root.expanduser().resolve()
    require(run.parent==a.project/'derived/replication/receipt_iv_uniform90_v100_PRIVATE',
            'Resume root must be an existing Uniform90 v1.0.0 directory in this project')
    require((run/'config.json').is_file(),'Existing config.json is missing; no new run was created')
    config=load(run/'config.json');conf=key(config)
    require(run.name==conf[:12],'Resume directory/configuration mismatch')
    require(config.get('version')=='1.0.0' and config.get('rule')==RULE90,'Scientific definition changed')
    require(config.get('manifest_sha256')==parent_manifest,'Original producer manifest differs')
    require(config.get('project')==str(a.project),'Project path differs from original configuration')
    for name in ('r12_root','r9_root','local_plan','reuse_run','reuse_chronology'):
        require(name in config,'Missing original binding: '+name)
        setattr(a,name,Path(config[name]) if config[name] is not None else None)
    return run,conf

def install_engines(memory_gb,workers=4):
    os.environ['UNIFORM90_MEMORY_GIB']=str(memory_gb)
    os.environ['UNIFORM90_WORKERS']=str(workers)
    import fast_features,fast_models,fast_comparisons
    sys.modules['uniform_features']=fast_features
    sys.modules['uniform_models']=fast_models
    sys.modules['uniform_comparisons']=fast_comparisons

def main():
    a=parser().parse_args()
    if a.self_test:
        return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(FAST_ROOT/'tests'),'-v'],cwd=FAST_ROOT)
    manifest,parent_manifest=verify()
    hardware=resources(a.workers,a.memory_gb)
    a.workers=hardware['workers'];a.memory_gb=hardware['memory_budget_gib']
    run,conf=bind_resume(a,parent_manifest)
    install_engines(a.memory_gb,a.workers)
    if a._stage:
        if a._stage!='metadata' or a.offline:frozen.u.no_network()
        with heartbeat('Stage '+a._stage):original.execute(a,run,conf)
        return 0
    require(shutil.disk_usage(run).free>=100*2**30,'At least 100 GiB free is required for the remaining comparison stages')
    a.result_dir.mkdir(parents=True,exist_ok=True)
    with original.prior_locks(a.project,run),(run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('The original/optimized Uniform90 run is still active. Stop its terminal with Ctrl-C and wait for the prompt before resuming.')
        previous=run/'report/execution.json'
        if previous.exists() and not (run/'report/execution_before_v101.json').exists():
            shutil.copy2(previous,run/'report/execution_before_v101.json')
        execution=dict(execution_version=EXECUTION_VERSION,execution_manifest_sha256=manifest,
            original_manifest_sha256=parent_manifest,scientific_configuration_sha256=conf,
            original_definition_unchanged=True,completed_checkpoints_reused=True,
            python=platform.python_version(),workers_requested=a.workers,memory_budget_gib=a.memory_gb,
            hardware=hardware,model_workers='memory-reserved scheduler; up to four independent fits',fe_threads_per_fit=4,
            model_matrix='Parallel-column R9 grouping; owned RAM buffer when it fits, bounded disk buffer otherwise',
            covariance='R9 exact NumPy CR0 within reservation; otherwise adaptively partitioned exact CR0',
            volume='Order-preserving uint64 lookup; existing verified v100 parts retained',
            model_order='Legacy replay, full uniform90 main IV, balance and remaining bridges with memory-reserved parallelism, comparisons',
            ETA='Per-stage measured progress; full private-data runtime has not been benchmarked')
        save(previous,execution)
        history=run/'PRIVATE/execution_versions';history.mkdir(exist_ok=True)
        save(history/(manifest+'.json'),execution)
        save(a.result_dir/'UNIFORM90_LATEST_PRIVATE.json',dict(root=str(run),configuration_sha256=conf,execution_version=EXECUTION_VERSION))
        statepath=run/'PRIVATE/STATE.json';state=load(statepath) if statepath.exists() else {};progress=0
        log(f'HARDWARE: {hardware["physical_memory_gib"]:.1f} GiB RAM, {hardware["logical_cpu_cores"]} CPU cores; compute allowance {a.memory_gb:.1f} GiB, up to {a.workers} workers')
        log('FAST_RESUME_V102: '+str(run)+'; existing checkpoints are verified and reused. No history, sample, score or covariance formula changes.')
        for name in original.STAGES:
            started=time.monotonic();state[name]=dict(status='RUNNING',execution_version=EXECUTION_VERSION);save(statepath,state)
            with (run/'run.log').open('a',buffering=1) as logf:
                child=subprocess.Popen([sys.executable,str(FAST_ROOT/'run_fast.py'),*sys.argv[1:],'--_stage',name],
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
                try:
                    for line in child.stdout:print(line,end='',flush=True);logf.write(line)
                    code=child.wait()
                except KeyboardInterrupt:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=20)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    state[name]=dict(status='INTERRUPTED',execution_version=EXECUTION_VERSION);save(statepath,state)
                    original.checkpoint(a,run,conf,state,progress,'Interrupted; rerun the same optimized command to resume')
                    return 130
            state[name]=dict(status='COMPLETE' if code==0 else 'FAILED',exit_code=code,
                             seconds=time.monotonic()-started,execution_version=EXECUTION_VERSION);save(statepath,state)
            if code:
                original.checkpoint(a,run,conf,state,progress,'Stage '+name+' failed; see run.log');return code
            if name in original.MILESTONES:
                progress=original.MILESTONES[name];original.checkpoint(a,run,conf,state,progress)
            if a.preflight_only and name=='authenticate':
                original.checkpoint(a,run,conf,state,0,preflight=True);return 0
        log('COMPLETE: return UNIFORM90_IV_'+conf[:12]+'_100.zip and its .sha256 for review.')
    return 0

if __name__=='__main__':raise SystemExit(main())
