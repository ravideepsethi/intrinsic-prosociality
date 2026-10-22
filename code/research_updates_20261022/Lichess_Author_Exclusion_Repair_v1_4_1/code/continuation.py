#!/usr/bin/env python3
"""Continue the specifically reviewed v100 result; never schedule its 14 completed fits."""
from engine import *
from compare import export_tables,compare_all
from run import verify_package,preflight,coverage,current_audits,package,STAGES
from runtime import announce
import argparse,concurrent.futures as cf,fcntl,subprocess,traceback,uuid

AUTHORITY=read(ROOT/'PARENT_AUTHORITY.json')
COMPLETED=AUTHORITY['completed']
NEW_STAGES=['rating_gap','nonparametric','session','activity']

def checked_link(src,dst):
    src=Path(src).resolve();dst=Path(dst);dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.is_symlink():require(dst.resolve()==src,'Continuation reference points elsewhere')
    elif dst.exists():raise RuntimeError('Refusing to replace an existing output: '+str(dst))
    else:dst.symlink_to(src,target_is_directory=src.is_dir())

def verify_parent(parent):
    cfg=read(parent/'PRIVATE/CONFIG.json')
    require(digest(cfg)[:16]==AUTHORITY['run_id']==parent.name,'Wrong parent configuration or run')
    require(cfg['code']==AUTHORITY['v100_code'] and cfg['upstream_manifest']==AUTHORITY['v100_upstream'],'Unreviewed parent programs')
    require(sha(parent/'report/REPORT_HASHES.json')==AUTHORITY['report_manifest_sha256'],'Parent report changed since review')
    require(sha(parent/'report/EXECUTION_STATUS.json')==AUTHORITY['execution_status_sha256'],'Parent run has not finished as reviewed')
    for f in read(ROOT/'evidence/returned_v100/REPORT_HASHES.json'):
        p=parent/'report'/f['file'];require(p.is_relative_to(parent/'report') and '..' not in Path(f['file']).parts,'Unsafe parent manifest member')
        require(p.is_file() and p.stat().st_size==f['bytes'] and sha(p)==f['sha256'],'Parent aggregate no longer matches returned report: '+f['file'])
    return read(parent/'PRIVATE/STAGES.json')

def adopt_inputs(parent,run,args):
    """Hash unique input files once per launch, with bounded concurrent SSD readers."""
    common=module('continuation_original_authority',ROOT/'vendor/wave1/runner/common.py')
    original=common.authenticate_sample(args.project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE',verify_hashes=False,hash_workers=args.io_workers)
    authentic={r['month']:r for r in original['month_records']}
    auths={v:read(parent/'PRIVATE/inputs'/(v+'_AUTH.json')) for v in ('included','excluded')}
    tasks={}
    for v,a in auths.items():
        require(a['variant']==v and a['original_fingerprint']==original['fingerprint'],'Parent input lineage differs')
        require(a['author_policy']['accounts']==list(AUTHORS),'Parent author policy differs')
        require(digest([v,a['author_policy'],a['month_records']])==a['fingerprint'],'Parent input fingerprint differs')
        require(sha(a['success_path'])==a['success_sha256'],'Parent input receipt changed')
        require([r['month'] for r in a['month_records']]==MONTHS,'Incomplete parent input months')
        for r in a['month_records']:
            if v=='included':require(r['expected_sha256']==authentic[r['month']]['expected_sha256'],'Original source checksum authority differs')
            key=str(Path(r['path']).resolve())
            if key in tasks:require(tasks[key]['expected_sha256']==r['expected_sha256'],'Conflicting source hash')
            tasks[key]=r
    def check(r):
        p=Path(r['path']);sig=signature(p)
        require(sha(p)==r['expected_sha256'] and pq.ParquetFile(p).metadata.num_rows==r['rows'],'Changed parent input: '+r['month'])
        require(signature(p)==sig,'Input changed during authentication')
        return str(p.resolve()),sig
    with heartbeat('Verify reusable Parquets'),cf.ThreadPoolExecutor(max_workers=min(args.workers,args.io_workers)) as pool:
        stamps=dict(pool.map(check,tasks.values()))
    folder=run/'PRIVATE/inputs';folder.mkdir(parents=True,exist_ok=True)
    # Verify that the retained files have no author in either role, using only identity columns.
    c=db(folder/'spill_verify',args.memory_gb,args.workers)
    try:
        for r in auths['excluded']['month_records']:
            pair=names_pair(r['path'])
            n=c.execute('SELECT count(*) FROM '+scan(r['path'])+' s WHERE '+author_sql(pair)).fetchone()[0]
            require(n==0,'Author survived parent excluded input: '+r['month'])
    finally:c.close()
    counts=pd.read_csv(ROOT/'evidence/returned_v100/main_counts.csv').set_index('variant')
    for v,a in auths.items():
        require(all(int(counts.loc[v,k])==n for k,n in a['census'].items()),'Parent census differs from reviewed return')
        for r in a['month_records']:
            r['verified_signature']=stamps[str(Path(r['path']).resolve())]
            require(signature(r['path'])==r['verified_signature'],'Input changed during adoption')
        a['verification_session']=os.environ['AUTHOR_EXCLUSION_SESSION']
        # Retain the producer's original scientific fingerprint and sample-root paths.
        write(folder/(v+'_AUTH.json'),a)
    for name in ('main_counts','removals_by_month'):
        for ext in ('.csv','.parquet'):shutil.copy2(parent/'report'/(name+ext),run/'report'/(name+ext))
    write(run/'report/INPUT_REUSE.json',{'status':'VERIFIED_PARENT_FULL_WIDTH_PARQUETS_REUSED','unique_files_hashed':len(tasks),'parent_run':parent.name,'author_hits_in_excluded_inputs':0,'author_accounts':2,'refiltered_full_panels':False})
    return auths

def adopt_completed(parent,run,parent_status,statuses,auths):
    for stage in COMPLETED:
        for v in ('included','excluded'):
            token=v+'/'+stage;p=parent_status[token]
            require(p['status']=='COMPLETE','Expected completed parent stage unavailable: '+token)
            receipt=verify(p['receipt']);r=read(receipt)
            require(r['stage']==stage and r['variant']==v and r['sample_fingerprint']==auths[v]['fingerprint'],'Completed stage has different sample lineage')
            for f in p['aggregate_files']:verify(f)
            source=parent/'report/tables'/v/stage;target=run/'report/tables'/v/stage
            shutil.copytree(source,target,dirs_exist_ok=True)
            dest=run/'PRIVATE/stage_receipts'/v/(stage+'.json');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(receipt,dest)
            statuses[token]=dict(status='COMPLETE',seconds=p.get('seconds',0),origin='REUSED_REVIEWED_V100',receipt=record(dest),aggregate_files=[record(f) for f in sorted(target.rglob('*.csv'))])
            log('Verified completed fit retained: '+token)
    write(run/'report/REUSE.json',{'completed_fits_retained':2*len(COMPLETED),'families':COMPLETED,'parent_run':parent.name,'completed_fits_scheduled_again':0})

def recover_rating(parent,run,auth,statuses):
    """Recover an originally completed producer after its aggregate-export failure.

    No pre-existing output checksum is invented: record the new capture explicitly.
    Settings and stage receipt must agree, and their source hashes must be exact.
    """
    src=parent/'PRIVATE/results/included/rating_gap';receipt=parent/'PRIVATE/stage_receipts/included/rating_gap.json'
    if not receipt.is_file() or not (src/'settings.json').is_file():return False
    r=read(receipt);settings=read(src/'settings.json')
    require(r['result']==settings and r['sample_fingerprint']==auth['fingerprint'],'Rating-gap completion receipts disagree')
    require(settings['status']=='POOL_MAIN_RATING_GAP_KRD_DECOMPOSITION_OK','Rating-gap producer did not finish')
    require(settings['sample_authority']['fingerprint']==auth['fingerprint'],'Rating-gap source sample differs')
    for field,rel in [('source_program','source/structural/rating_gap_krd_decomposition.py'),('render_program','source/structural/render_rating_gap_krd.py'),('adapter','runner/run_krd.py')]:
        require(settings[field]['sha256']==sha(ROOT/'vendor/wave1'/rel),'Rating-gap source program changed')
    cache=src/'private_cache/rating_gap_krd_derived_private.parquet'
    require(cache.is_file(),'Completed rating-gap private cache missing')
    val=pd.read_csv(src/'mechanical_validation.csv')
    require(len(val)==1 and int(val.iloc[0]['n'])==pq.ParquetFile(cache).metadata.num_rows,'Rating-gap cache census differs from completion output')
    new=run/'PRIVATE/results/included/rating_gap';checked_link(src,new)
    files=export_tables(run,'included','rating_gap');require(len(files)==9,'Incomplete rating-gap aggregate set')
    dest=run/'PRIVATE/stage_receipts/included/rating_gap.json';dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(receipt,dest)
    capture={'receipt':record(receipt),'settings':record(src/'settings.json'),'cache':record(cache),'files':[record(p) for p in files]}
    write(run/'PRIVATE/RECOVERED_RATING_CAPTURE.json',capture)
    statuses['included/rating_gap']=dict(status='COMPLETE',origin='RECOVERED_COMPLETED_PRODUCER_EXPORT',seconds=0,receipt=record(dest),aggregate_files=capture['files'])
    write(run/'report/RATING_RECOVERY.json',{'status':'COMPLETED_PRODUCER_RECOVERED_WITHOUT_REFIT','tables':len(files),'preexisting_aggregate_checksums_available':False,'validation':'Original successful stage receipt equals lineaged settings; exact producer source hashes; cache row count agrees with mechanical validation; new capture checksums saved privately.'})
    return True

def diagnostic(run,parent,token,exc=None):
    """Return stack locations and generic error categories, never raw account data."""
    import re
    v,stage=token.split('/');p=parent/'PRIVATE/logs'/(v+'_'+stage+'.log')
    text=p.read_text(errors='replace') if p.exists() else ''
    frames=[{'file':Path(a).name,'line':int(b),'function':c} for a,b,c in re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',text)]
    errors=re.findall(r'^([A-Za-z_]+(?:Error|Exception)):',text,re.M)
    safe_messages=['Completed session authority differs/missing','Unmanifested history file','Changed factual history','Session focal coverage differs','Session history does not match certified main events','Session retained row coverage differs','No space left on device','Out of Memory','Binder Error','Parser Error','Permission denied','No such file or directory']
    write(run/'report/diagnostics'/(token.replace('/','_')+'.json'),{'log_present':p.exists(),'stack':frames[-12:],'error_classes':errors[-4:],'known_messages':[m for m in safe_messages if m in text],'caught_error_class':type(exc).__name__ if exc else None,'raw_log_returned':False})

def run_stage(args,run,v,stage):
    cmd=[sys.executable,str(ROOT/'code/adapters.py'),'--run',str(run),'--project',str(args.project),'--variant',v,'--stage',stage,'--workers',str(args.workers),'--memory-gb',str(args.memory_gb),'--shards',str(args.shards)]
    if args.session_root:cmd+=['--session-root',str(args.session_root)]
    p=run/'PRIVATE/logs'/(v+'_'+stage+'.log');p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a') as f:
        child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        try:
            with heartbeat(v+'/'+stage):
                for line in child.stdout:print(line,end='',flush=True);f.write(line);f.flush()
            rc=child.wait()
        except BaseException:
            child.terminate();child.wait();raise
    require(rc==0,'Stage failed: '+v+'/'+stage+'; private log retained')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--io-workers',type=int,default=4,choices=range(1,5))
    p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--shards',type=int,default=256)
    p.add_argument('--session-root',type=Path);p.add_argument('--estimate-only',action='store_true')
    args=p.parse_args()
    if args.estimate_only:
        print('Expected 1.5–6 hours, provisional: cache authentication, six remaining/new fits and reuse of the completed session baseline, and current-result audits. Fourteen completed fits are reused. No API/Stockfish/history reconstruction.');return 0
    verify_package();versions=preflight(args);args.project=args.project.expanduser().resolve()
    parent=args.project/'derived/replication/author_exclusion_reestimate_v100_PRIVATE'/AUTHORITY['run_id']
    require(parent.is_dir(),'Reviewed v100 private cache missing: '+str(parent))
    lock=(parent/'RUNNING.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('v100 is still running; continuation did not start')
    cfg={'version':'1.2.0','parent':AUTHORITY,'code':{p.name:sha(p) for p in sorted((ROOT/'code').glob('*.py'))},'upstream':sha(ROOT/'UPSTREAM_FILES.json'),'shards':args.shards,'versions':versions}
    run=args.project/'derived/replication/author_exclusion_continue_v120_PRIVATE'/digest(cfg)[:16]
    (run/'report').mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True)
    own=(run/'RUNNING.lock').open('a+')
    try:fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This continuation is already running')
    statusfile=run/'PRIVATE/STAGES.json';statuses=read(statusfile) if statusfile.exists() else {};start=time.monotonic()
    os.environ['AUTHOR_EXCLUSION_SESSION']=uuid.uuid4().hex
    write(run/'PRIVATE/CONFIG.json',cfg);write(run/'report/ENVIRONMENT.json',versions)
    write(run/'report/POLICY.json',{**{k:v for k,v in POLICY.items() if k!='accounts'},'author_accounts':2})
    try:
        jobs=[(v,s) for s in NEW_STAGES for v in ('included','excluded')]
        announce(jobs,statuses,run,inputs=True,audit=True)
        prior=verify_parent(parent)
        diagnostic(run,parent,'included/session')
        auths=adopt_inputs(parent,run,args);adopt_completed(parent,run,prior,statuses,auths)
        if statuses.get('included/rating_gap',{}).get('status')!='COMPLETE':
            recover_rating(parent,run,auths['included'],statuses)
        elif (run/'PRIVATE/RECOVERED_RATING_CAPTURE.json').exists():
            for r in read(run/'PRIVATE/RECOVERED_RATING_CAPTURE.json').values():
                if isinstance(r,list):
                    for item in r:verify(item)
                else:verify(r)
        write(statusfile,statuses);coverage(run,statuses);package(run,args.result_dir,25)
        failures=[]
        for i,(v,s) in enumerate(jobs):
            token=v+'/'+s
            announce(jobs[i:],statuses,run,audit=True)
            previous=statuses.get(token,{})
            if previous.get('status')=='COMPLETE':
                verify(previous['receipt'])
                for f in previous['aggregate_files']:verify(f)
                continue
            if v=='excluded' and statuses.get('included/'+s,{}).get('status')!='COMPLETE':statuses[token]={'status':'BLOCKED_BASELINE'};write(statusfile,statuses);continue
            if s=='nonparametric' and statuses.get(v+'/rating_gap',{}).get('status')!='COMPLETE':statuses[token]={'status':'BLOCKED_DEPENDENCY'};write(statusfile,statuses);continue
            begin=time.monotonic()
            try:
                run_stage(args,run,v,s)
                files=export_tables(run,v,s);require(bool(files),'No aggregate output from '+token)
                receipt=run/'PRIVATE/stage_receipts'/v/(s+'.json')
                statuses[token]={'status':'COMPLETE','origin':'CONTINUATION_FIT','seconds':time.monotonic()-begin,'receipt':record(receipt),'aggregate_files':[record(f) for f in files]}
            except Exception as exc:
                statuses[token]={'status':'FAILED','error_type':type(exc).__name__};failures.append(token)
                log(str(exc));diagnostic(run,run,token,exc)
            write(statusfile,statuses);coverage(run,statuses)
            if i==3:package(run,args.result_dir,50)
        package(run,args.result_dir,75)
        audits=current_audits(args,run)
        for family,status in audits.items():
            if status['status']=='BLOCKED':diagnostic(run,run,'audit/'+family)
        paired=[s for s in STAGES if all(statuses.get(v+'/'+s,{}).get('status')=='COMPLETE' for v in ('included','excluded'))]
        summary=compare_all(run,paired);coverage(run,statuses)
        write(run/'report/EXECUTION_STATUS.json',{'status':'CONTINUATION_FINISHED_GLOBAL_COVERAGE_PENDING','paired_families':paired,'failed_stages':failures,'seconds':time.monotonic()-start,'comparison':summary,'audits':audits})
        package(run,args.result_dir,100)
        log('Finished. Return the _100.zip and sidecar. Paper-wide coverage remains pending.');return 2
    except BaseException as exc:
        write(run/'PRIVATE/FAILURE.json',{'error':str(exc),'traceback':traceback.format_exc()})
        write(run/'report/EXECUTION_STATUS.json',{'status':'BLOCKED','error_class':type(exc).__name__})
        coverage(run,statuses);package(run,args.result_dir,0);raise
    finally:own.close();lock.close()

if __name__=='__main__':sys.exit(main())
