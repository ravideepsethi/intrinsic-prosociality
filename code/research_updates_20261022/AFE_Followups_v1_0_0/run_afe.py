#!/usr/bin/env python3
"""Read-only source analyses, isolated output, resumable stages, public report ZIP."""
from __future__ import annotations
import argparse, contextlib, fcntl, hashlib, json, os, shutil, sys, time, traceback, zipfile
from pathlib import Path
from common import *

MODULES=('payoffs','patron','iv','transmission','blackout','recovery')

def verify_package():
    manifest=read(PKG/'PACKAGE_MANIFEST.json')
    for e in manifest['files']:check_file(PKG/e['path'],e['sha256'],e['bytes'])
    return sha(PKG/'PACKAGE_MANIFEST.json')

def export(root,desktop,status,config):
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=root/'reports'/('AFE_FOLLOWUPS_REPORT_'+stamp);folder.mkdir(parents=True)
    for name in MODULES:
        public=root/name/'public'
        if public.is_dir() and name in status and not status[name].get('status','').startswith('FAILED'):
            shutil.copytree(public,folder/name)
    js(folder/'RUN_STATUS.json',status);js(folder/'RUN_CONFIGURATION.json',config)
    shutil.copy2(PKG/'ANALYSIS_PLAN.md',folder/'ANALYSIS_PLAN.md')
    shutil.copy2(PKG/'PACKAGE_MANIFEST.json',folder/'CODE_MANIFEST.json')
    rows=['# AFE follow-up report','', 'No private row-level data are included.','']
    for name,entry in status.items():rows.append(f"- {name}: {entry.get('status','unknown')}")
    rows+=['','These are new exploratory analyses. Scientific support is determined by estimates and uncertainty, not by successful program completion.','Missing inputs and numerical failures are retained explicitly. No raw data, usernames, game IDs, exposure IDs or account-level caches are packaged.']
    (folder/'READ_RESULTS.md').write_text('\n'.join(rows)+'\n')
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    dest=desktop/(folder.name+'.zip')
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file():z.write(p,str(Path(folder.name)/p.relative_to(folder)))
    side=dest.with_name(dest.name+'.sha256');side.write_text(sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD: '+str(dest));log('UPLOAD: '+str(side));return dest

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--project',default='/Volumes/XT_Pro/lichess_kindness')
    ap.add_argument('--desktop',default=str(Path.home()/'Desktop/Lichess_Desktop'))
    ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--memory',default='6GB')
    ap.add_argument('--modules',default=','.join(MODULES))
    ap.add_argument('--simulations',type=int,default=10)
    ap.add_argument('--recovery-accounts',type=int,default=3000)
    ap.add_argument('--preflight-only',action='store_true')
    args=ap.parse_args();requested=args.modules.split(',')
    if set(requested)-set(MODULES):ap.error('Unknown module')
    if not 1<=args.workers<=10:ap.error('workers must be between 1 and 10')
    if args.simulations<1 or args.recovery_accounts<1:ap.error('Recovery counts must be positive')
    digest=verify_package();project=Path(args.project).resolve()
    if not project.is_dir():raise FileNotFoundError('Project drive is not mounted: '+str(project))
    config=dict(version='1.0.0',package_manifest_sha256=digest,project=str(project),workers=args.workers,memory=args.memory,
        simulations=args.simulations,recovery_accounts=args.recovery_accounts,environment=environment())
    signature=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    root=project/'derived/replication/afe_followups_v100_PRIVATE'/signature[:12];root.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This exact AFE run is already active')
    js(root/'config.json',config)
    if not (root/'DESIGN_FREEZE.json').exists():js(root/'DESIGN_FREEZE.json',dict(created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),config=config,plan_sha256=sha(PKG/'ANALYSIS_PLAN.md')))
    statuses={};start=time.monotonic()
    try:
        log('Checking source hashes, exact sample, and optional inputs')
        inputs=resolve_inputs(project);js(root/'INPUTS_PRIVATE.json',inputs)
        stage_signature=hashlib.sha256(json.dumps(dict(config=signature,inputs=inputs),sort_keys=True).encode()).hexdigest()
        statuses['preflight']=dict(status='COMPLETE',rows=41534331,optional_input_status=inputs['status'])
        if not args.preflight_only:
            from static_analyses import payoff_audit,patron_reversal
            from transmission import transmission,iv_sensitivity
            from recovery import blackout_feasibility,recovery
            runners=dict(payoffs=payoff_audit,patron=patron_reversal,iv=iv_sensitivity,transmission=transmission,blackout=blackout_feasibility,
                recovery=lambda i,r,w,m:recovery(i,r,w,m,args.simulations,args.recovery_accounts))
            for name in requested:
                directory=root/name;directory.mkdir(exist_ok=True);stage_start=time.monotonic()
                try:
                    if verify_resume(directory,stage_signature):
                        log(name+': verified checkpoint reused');statuses[name]=read(directory/'_DONE.json')['result'];continue
                    log('Starting '+name)
                    with heartbeat(name):result=runners[name](inputs,directory,args.workers,args.memory)
                    result['elapsed_seconds']=time.monotonic()-stage_start
                    done(directory,stage_signature,result['status'],extra=dict(result=result));statuses[name]=result
                except Exception as e:
                    statuses[name]=dict(status='FAILED_OR_MISSING_INPUT',error_type=type(e).__name__,message=str(e),elapsed_seconds=time.monotonic()-stage_start)
                    js(directory/'ERROR.json',dict(**statuses[name],traceback=traceback.format_exc()))
                    log(name+' did not complete: '+str(e))
                js(root/'RUN_STATUS.json',statuses)
    except Exception as e:
        statuses['preflight']=dict(status='FAILED',error_type=type(e).__name__,message=str(e));js(root/'PREFLIGHT_ERROR.json',dict(**statuses['preflight'],traceback=traceback.format_exc()))
    finally:
        statuses['runtime']=dict(status='RECORDED',elapsed_seconds=time.monotonic()-start)
        js(root/'RUN_STATUS.json',statuses);export(root,args.desktop,statuses,config)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    failures=[k for k,v in statuses.items() if v.get('status','').startswith('FAILED')]
    if failures:log('Finished with incomplete modules: '+', '.join(failures));return 2
    log('AFE_FOLLOWUPS_RUN_FINISHED — inspect the report for scientific support and limitations');return 0

if __name__=='__main__':sys.exit(main())
