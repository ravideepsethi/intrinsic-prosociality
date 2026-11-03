"""One offline, restartable command; stages release memory in separate processes."""
from common_retained import *
import argparse,subprocess,fcntl,zipfile,traceback,datetime,signal
from zoneinfo import ZoneInfo
STAGES=['preflight','balance_ladder','spaced_balance_frames','act_stakes','spaced_compliers','export']
DEPENDENCIES={name:['preflight'] for name in STAGES if name!='preflight'}
DEPENDENCIES['export']=[s for s in STAGES if s not in ('preflight','export')]
LEGACY='af114813b1add1405ce5f4a40d6968648f6dbc79ffa49199b185085371411ab3'

def arguments(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop');p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    p.add_argument('--preflight-only',action='store_true');p.add_argument('--_stage',choices=STAGES,help=argparse.SUPPRESS)
    return p.parse_args(argv)

def setup(a):
    a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve();require(a.project.is_dir(),'Project drive not mounted: '+str(a.project))
    a.parent=a.project/'derived/replication/mating_material_iv_batch_v100_PRIVATE'/PARENT_CONF[:16]
    a.closeout=a.project/'derived/replication/mating_material_paper_closeout_v100_PRIVATE'/CLOSEOUT_CONF[:16]
    a.legacy_root=a.project/'derived/replication/receipt_iv_uniform90_v100_PRIVATE'/LEGACY[:12]
    old=read(a.legacy_root/'config.json');require(c.key(old)==LEGACY,'Legacy input configuration differs')
    for k in ('r12_root','r9_root','local_plan','reuse_run','reuse_chronology'):setattr(a,k,Path(old[k]) if old[k] is not None else None)
    a.offline=True;hw=c.resources(a.workers,a.memory_gb);a.workers=min(10,hw['workers']);a.memory_gb=min(11.,hw['memory_budget_gib'])
    os.environ['UNIFORM90_MEMORY_GIB']=str(a.memory_gb);os.environ['UNIFORM90_WORKERS']=str(a.workers);os.environ['CLOSEOUT_SQL_GB']='1.5'
    from fast_digest_cache import install
    install(c.frozen.r.io)
    config=dict(version='1.0.0',package_sha256=sha(ROOT/'PACKAGE_MANIFEST.sha256'),project=str(a.project),iv_parent=PARENT_CONF,closeout_parent=CLOSEOUT_CONF,legacy_parent=LEGACY,scope='revised RA note: exactly three analysis families',scope_sha256='6c94a18ddb6b76b65d13dbbd85b4c17c6861f3336234944fe4f325b7486e85c3',production_network=False)
    conf=c.key(config);run=a.project/'derived/replication/mating_material_three_runs_v100_PRIVATE'/conf[:16]
    for p in (run/'PRIVATE',run/'report',a.result_dir):p.mkdir(parents=True,exist_ok=True)
    if (run/'config.json').exists():require(read(run/'config.json')==config,'Run configuration changed')
    else:save(run/'config.json',config)
    return run,conf

def closeout_auth(a):
    require(c.key(read(a.closeout/'config.json'))==CLOSEOUT_CONF,'Closeout configuration differs')
    for r in read(ROOT/'authority/INPUT_REPORT_HASHES.json'):
        if not r['target'].startswith('closeout/'):continue
        p=a.closeout/Path(r['target']).relative_to('closeout')
        require(p.is_file() and sha(p)==r['sha256'],'Reviewed closeout aggregate changed: '+str(p))

def execute(a,run,conf):
    if a._stage=='preflight':
        preflight(a,run,conf);closeout_auth(a)
        require(shutil.disk_usage(run).free>=80*2**30,'Need 80 GiB free for disk-backed model buffers and diagnostic frames')
        save(run/'report/SCOPE.json',read(ROOT/'METHOD.json'));return
    auth=read(run/'PRIVATE/AUTHENTICATED.json');guard(auth)
    if a._stage=='balance_ladder':
        from balance_retained import run_ladder;run_ladder(a,run,conf,auth)
    elif a._stage=='spaced_balance_frames':
        from frames_retained import spaced_frames;spaced_frames(a,run,conf,auth)
    elif a._stage=='act_stakes':
        from frames_retained import act_features
        from systems import fit_system
        f=act_features(a,run,conf,auth)
        out=fit_system(a,run,conf,'receipt_position_stakes',Path(auth['paths']['spaced']),Path(auth['paths']['spaced_scores']),'act',f)
        publish(out,run,'table_D5_panelB_raw.csv');shutil.copy2(out/'result.json',run/'report/ACT_SYSTEM.json')
    elif a._stage=='spaced_compliers':
        from systems import run_compliers;run_compliers(a,run,conf,auth)
    elif a._stage=='export':
        from retained_export import export;export(a,run,conf)
    else:raise RuntimeError('Stage outside the three authorized analysis families')
    guard(auth)

def archive(a,run,conf,state):
    full=all(state.get(k,{}).get('status')=='COMPLETE' for k in STAGES)
    status=dict(status='THREE_RUNS_COMPLETE_MANUSCRIPT_PENDING' if full else 'PARTIAL',stages=state,configuration=conf,whole_paper_complete=False,private_rows_exported=False)
    save(run/'report/STATUS.json',status)
    files=[p for p in sorted((run/'report').rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    save(run/'report/REPORT_MANIFEST.json',[record(p,run/'report') for p in files])
    destination=a.result_dir/f'MATERIAL_THREE_RUNS_{conf[:16]}_RETURN.zip';tmp=destination.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((run/'report').rglob('*')):
            if p.is_file():z.write(p,'report/'+p.relative_to(run/'report').as_posix())
        if (run/'run.log').exists():z.write(run/'run.log','run.log')
        z.write(ROOT/'PACKAGE_MANIFEST.sha256','EXECUTED_PACKAGE.sha256');z.write(ROOT/'METHOD.json','EXECUTED_METHOD.json')
    os.replace(tmp,destination);Path(str(destination)+'.sha256').write_text(sha(destination)+'  '+destination.name+'\n')
    save(a.result_dir/'MATERIAL_THREE_RUNS_LATEST_PRIVATE.json',dict(root=str(run),configuration=conf,return_zip=str(destination),status=status['status']))
    log('Return this single file: '+str(destination));return destination

def main(argv=None):
    a=arguments(argv);verify_package();b.no_network();run,conf=setup(a)
    if a._stage:
        with heartbeat('Authorized analysis '+a._stage):execute(a,run,conf)
        return 0
    zone=ZoneInfo('America/Toronto');start=datetime.datetime.now(datetime.timezone.utc)
    print('Expected first-run runtime: 2–4 hours provisionally; slow external-drive I/O can extend this. Completed stages are verified and skipped.',flush=True)
    print('Toronto start: '+start.astimezone(zone).strftime('%Y-%m-%d %I:%M %p %Z')+'; provisional finish '+(start+datetime.timedelta(hours=2)).astimezone(zone).strftime('%Y-%m-%d %I:%M %p %Z')+' to '+(start+datetime.timedelta(hours=4)).astimezone(zone).strftime('%Y-%m-%d %I:%M %p %Z'),flush=True)
    print('Private checkpoints: '+str(run),flush=True)
    statepath=run/'PRIVATE/STATE.json';state=read(statepath) if statepath.exists() else {}
    with (run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This retained-analysis run is already active')
        for name in STAGES:
            if name!='preflight' and state.get(name,{}).get('status')=='COMPLETE':
                for rec in state[name]['outputs']:p=run/'report'/rec['path'];require(p.is_file() and sha(p)==rec['sha256'],'Saved stage report changed: '+rec['path'])
                log(name+': verified completed stage; skipped');continue
            if a.preflight_only and name!='preflight':break
            if any(state.get(k,{}).get('status')!='COMPLETE' for k in DEPENDENCIES.get(name,[])):
                state[name]=dict(status='BLOCKED',dependencies=DEPENDENCIES[name]);save(statepath,state);archive(a,run,conf,state);continue
            started=time.monotonic()
            state[name]=dict(status='RUNNING');save(statepath,state)
            args=[sys.executable,str(ROOT/'run.py'),'--project',str(a.project),'--result-dir',str(a.result_dir),'--workers',str(a.workers),'--memory-gb',str(a.memory_gb),'--_stage',name]
            with (run/'run.log').open('a',buffering=1) as log_file:
                process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
                try:
                    for line in process.stdout:print(line,end='',flush=True);log_file.write(line)
                    code=process.wait()
                except KeyboardInterrupt:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    state[name]=dict(status='INTERRUPTED',seconds=time.monotonic()-started);save(statepath,state);archive(a,run,conf,state);return 130
            # Bind all available nonvolatile aggregates, including a model
            # which finished writing before an interrupted previous attempt.
            outputs=[record(p,run/'report') for p in (run/'report').rglob('*') if p.is_file() and p not in (run/'report/STATUS.json',run/'report/REPORT_MANIFEST.json')]
            state[name]=dict(status='COMPLETE' if code==0 else 'FAILED',exit_code=code,seconds=time.monotonic()-started,outputs=outputs);save(statepath,state);archive(a,run,conf,state)
            log(name+': '+state[name]['status']+f'; {state[name]["seconds"]/60:.1f} min')
            if name=='preflight' and code:return code
    print('Toronto finish/pause: '+datetime.datetime.now(zone).strftime('%Y-%m-%d %I:%M %p %Z'))
    return 0 if all(state.get(k,{}).get('status')=='COMPLETE' for k in (['preflight'] if a.preflight_only else STAGES)) else 1

if __name__=='__main__':raise SystemExit(main())
