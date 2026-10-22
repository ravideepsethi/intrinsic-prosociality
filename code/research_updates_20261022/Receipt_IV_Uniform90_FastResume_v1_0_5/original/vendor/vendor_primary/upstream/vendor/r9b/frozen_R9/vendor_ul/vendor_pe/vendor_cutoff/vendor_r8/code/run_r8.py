#!/usr/bin/env python3
"""Isolated modules, immutable configuration, resumable checkpoints, aggregate ZIP."""
from r8_util import *
import argparse,fcntl,subprocess,sys,shutil,zipfile,traceback

MODULES=['receipt','patron','clocks']
OPEN_WORK=[
    dict(item='3(1)',status='OPEN_NEW_ENGINE_WORK_REQUIRED',reason='Winning-chances training requires 2,000,000 new 100k-node evaluations and verified out-of-fold calibration. This package makes no engine searches.'),
    dict(item='3(3)',status='OPEN_REPLAY_PRODUCER_UNBOUND',reason='The exact 20,000-chooser / 260,863-row replay producer and per-ply score cache have not been authenticated. No ACPL or cumulative-loss estimate is substituted.'),
    dict(item='5',status='PARTIAL_AUTHOR_CHECK_NOT_PAPER_WIDE',reason='R7 receipt results are author-clean. This run rebuilds author-clean Patron histories and gradient samples. Table 2 persistence and Table 4 diffusion producers, and a full Table 1 contrast/ratio reproduction, remain to be bound; paper-wide displayed-precision invariance is not certified.')]

def verify_package():
    rows=(ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines()
    require(rows,'Package manifest is empty')
    for line in rows:
        want,name=line.split('  ',1);p=ROOT/name
        require(p.resolve().is_relative_to(ROOT.resolve()),'Manifest path escapes the package')
        require(p.is_file() and sha(p)==want,'Package SHA changed: '+name)
    return sha(ROOT/'PACKAGE_MANIFEST.sha256')

def export(run,desktop,key,requested,states,t0):
    report=run/'REPORT'
    if report.exists():shutil.rmtree(report)
    report.mkdir(parents=True,exist_ok=True)
    for name in requested:
        source=run/name/'report';target=report/name
        if source.exists() and states.get(name,{}).get('state')=='COMPLETE':shutil.copytree(source,target,dirs_exist_ok=True)
        baseline=run/name/('baseline_gate' if name=='clocks' else 'baseline')
        if states.get(name,{}).get('state')=='COMPLETE' and baseline.exists() and (baseline/'_DONE.json').exists() and verify_cached(baseline,load(baseline/'_DONE.json')['key']):
            dest=report/name/'baseline';dest.mkdir(parents=True,exist_ok=True)
            for p in baseline.iterdir():
                if p.is_file() and p.name!='_DONE.json':shutil.copy2(p,dest/p.name)
    complete=all(states.get(n,{}).get('state')=='COMPLETE' for n in requested)
    status='CURRENT_DATA_SCOPE_COMPLETE_R8_REMAINS_OPEN' if complete else 'CURRENT_DATA_SCOPE_PARTIAL_R8_REMAINS_OPEN'
    summary=dict(status=status,version=VERSION,configuration_sha256=key,requested_modules=requested,
        module_states=states,open_work=OPEN_WORK,network_requests=0,stockfish_searches=0,
        elapsed_seconds=time.monotonic()-t0,live_data_run=True,production_results_verified_on_build_machine=False)
    save(report/'SUMMARY.json',summary)
    ledger=[dict(item='1',module='patron',status=states.get('patron',{}).get('state','NOT_RUN')),
        dict(item='2',module='receipt',status=states.get('receipt',{}).get('state','NOT_RUN')),
        dict(item='4',module='receipt',status=states.get('receipt',{}).get('state','NOT_RUN')),
        dict(item='3(2)',module='clocks',status=states.get('clocks',{}).get('state','NOT_RUN'))]+OPEN_WORK
    save(report/'R8_LEDGER.json',ledger)
    lines=['# R8 current-data results','',status,'',
        'This archive contains aggregate estimates only. It does not close all five R8 items.',
        'No network requests, profile refreshes, game downloads, or Stockfish searches were made.','',
        '| Module | State |','| --- | --- |']
    lines += [f"| {n} | {states.get(n,{}).get('state','NOT_RUN')} |" for n in MODULES]
    lines += ['',
        'Receipt: predicted-outcome coefficients and full first-order uncertainty reuse completed R7; R² supplements reproduce every joint trait coefficient. Experience groups use the complete recorded all-source chronology and separately report the existing 90-day groups. “Never faced” is left-censored, not a lifetime claim.',
        'The separately fitted experience difference includes covariance across groups. Its AR-type set is a conservative projection of two marginal 97.5% AR sets. The pooled common-control interacted difference is a distinct estimand and has a Wald interval only.',
        'Patron: reproduce original August-only counts and coefficients before exclusions. Remove author games from affected histories, keep stored matches, then show all-returned and unflagged estimates. Bounds optimize coefficient-specific signed weights; they are identification bounds, not confidence intervals. Full-profile bounds apply to returned profiles; unavailable profiles are included in the simpler fixed FE/exposure-design bounds.',
        'Clocks: reproduce the original natural-spline contrasts and chooser-clustered standard errors before fitting author-clean baseline and clock sensitivities. Categories use the last observed clock divided by initial base seconds; the 50–100% category is the reference. Increments can produce values above 100%. Clocks are readings at the chooser’s last move before the countdown.',
        'All reported associations, balance calibrations, and experience comparisons remain subject to the paper’s identification assumptions. Observed-trait calibration is not identified bias from all selection.',
        '', '## Still open','']
    lines += [f"- {r['item']}: {r['reason']}" for r in OPEN_WORK]
    (report/'SUMMARY.md').write_text('\n'.join(lines)+'\n')
    shutil.copy2(ROOT/'R8_SPEC.md',report/'R8_SPEC.md')
    shutil.copy2(ROOT/'VALIDATION.json',report/'PACKAGE_VALIDATION.json')
    hashes=[dict(path=str(p.relative_to(report)),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(report.rglob('*'))
        if p.is_file() and p.name!='REPORT_MANIFEST.json']
    save(report/'REPORT_MANIFEST.json',hashes)
    name='R8_CURRENT_DATA_RESULT_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+key[:12]+'.zip'
    out=desktop/name;tmp=out.with_name(name+'.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'R8_CURRENT_DATA_RESULT/'+str(p.relative_to(report)))
    with zipfile.ZipFile(tmp) as z:require(z.testzip() is None,'Result archive CRC failed')
    os.replace(tmp,out);(desktop/(name+'.sha256')).write_text(sha(out)+'  '+name+'\n')
    log('RESULT_ZIP '+str(out));log('RESULT_SHA256 '+str(desktop/(name+'.sha256')))
    return complete

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--r7-root',type=Path);p.add_argument('--workers',type=int,default=10)
    p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--modules',nargs='+',choices=MODULES,default=MODULES)
    p.add_argument('--status',action='store_true');a=p.parse_args()
    require(1<=a.workers<=10,'Use 1–10 workers');require(4<=a.memory_gb<=11,'Use a 4–11 GiB working-memory budget')
    require('receipt' not in a.modules or a.memory_gb>=10,'Full-frame receipt/F50 fit checks require a 10–11 GiB working-memory budget')
    require(a.project_root.is_dir(),'Connect the existing XT_Pro project before running')
    no_network();package=verify_package();require(sys.version_info>=(3,10),'Python 3.10+ required')
    require(hasattr(Path('.'),'is_relative_to'),'Python 3.10+ required')
    # Paths/resources do not change the estimand; package and runtime versions do.
    config=dict(version=VERSION,package_manifest_SHA256=package,R7_config=R7_CONF,
        numpy=np.__version__,pandas=pd.__version__,pyarrow=pa.__version__,duckdb=duckdb.__version__)
    import scipy
    config['scipy']=scipy.__version__;key=digest(config)
    run=a.project_root/'derived/replication/r8_current_data_v100_PRIVATE'/key[:12]
    if a.status:
        log('R8 state '+str(run));textpath=run/'STATE.json'
        print(json.dumps(load(textpath) if textpath.exists() else {'status':'NOT_STARTED'},indent=2));return 0
    a.desktop.mkdir(parents=True,exist_ok=True);run.mkdir(parents=True,exist_ok=True)
    require(shutil.disk_usage(run).free>=20*2**30,'Less than 20 GiB free on the project volume; allow space for projections and SQL spill before starting')
    lock=(run/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This R8 configuration is already running; use --status')
    os.chmod(run,0o700);t0=time.monotonic();save(run/'CONFIG_PRIVATE.json',dict(config,key=key,arguments=vars(a)))
    states=load(run/'STATE.json').get('modules',{}) if (run/'STATE.json').exists() else {}
    log('R8 current-data scope; no new engine work. Estimated 3–6 hours on the R7 Mac, unbenchmarked; first source hashes may add time.')
    for name in a.modules:
        work=run/name;k=digest([key,name]);old=states.get(name,{})
        # Completed modules are hash-checked again; signature changes stop reuse.
        try:
            if verify_cached(work,k):
                states[name]=dict(state='COMPLETE',resumed=True,seconds=old.get('seconds'));log(name+': completed checkpoint verified')
                continue
            states[name]=dict(state='RUNNING');save(run/'STATE.json',dict(modules=states,key=key))
            cmd=[sys.executable,'-u',str(ROOT/'code'/('r8_'+name+'.py')),'--project-root',str(a.project_root),
                '--work',str(work),'--key',k,'--memory-gb',str(a.memory_gb)]
            if name=='receipt' and a.r7_root:cmd+=['--r7-root',str(a.r7_root)]
            if name=='clocks':cmd+=['--workers',str(a.workers)]
            began=time.monotonic();log(name+': start')
            with heartbeat(name+' module'):result=subprocess.run(cmd,check=False)
            if result.returncode!=0:raise RuntimeError('Module exited '+str(result.returncode)+'; inspect this log and the private checkpoints')
            require(verify_cached(work,k),'Module returned without a valid completion receipt')
            states[name]=dict(state='COMPLETE',resumed=False,seconds=time.monotonic()-began)
        except Exception as e:
            states[name]=dict(state='BLOCKED',reason=str(e));log(name+': BLOCKED — '+str(e))
        finally:save(run/'STATE.json',dict(modules=states,key=key))
    complete=export(run,a.desktop,key,a.modules,states,t0)
    if complete:save(run/'SCOPE_SUCCESS.json',dict(key=key,scope='requested current-data modules',R8_all_complete=False))
    log('Re-run the same command to resume; return the result ZIP, sidecar and terminal log.')
    return 0 if complete else 2

if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:log('Interrupted. Completed checkpoints are retained.');raise SystemExit(130)
