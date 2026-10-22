"""Targeted continuation of the reviewed c5784554d40c84d9 result."""
from engine import *
from compare import compare_all,export_tables
import run as reporting
from continuation import diagnostic
import argparse,fcntl,subprocess,traceback,uuid,concurrent.futures as cf

PARENT=read(ROOT/'REPAIR_PARENT.json')
JOBS=[('excluded','session'),('included','nonparametric'),('excluded','nonparametric'),('excluded','mechanism')]

def remaining_estimate(run,statuses,next_index):
    ranges={'session':(10,45),'nonparametric':(7,30),'mechanism':(15,45)}
    pending=[]
    for index,(v,s) in enumerate(JOBS[next_index:],next_index):
        if statuses.get(v+'/'+s,{}).get('status')=='COMPLETE':continue
        low,high=ranges[s]
        baseline=statuses.get('included/nonparametric',{})
        if v=='excluded' and s=='nonparametric' and baseline.get('seconds'):
            minutes=baseline['seconds']/60;low,high=.7*minutes,1.5*minutes
        pending.append({'stage':v+'/'+s,'index':index,'low_minutes':low,'high_minutes':high})
    pending.append({'stage':'Framework audit and report','index':4,'low_minutes':1,'high_minutes':10})
    first=pending[0]['index'];checkpoint=50 if first==0 else 75 if first<3 else 100
    limit=0 if checkpoint==50 else 2 if checkpoint==75 else 4
    count=sum(r['index']<=limit for r in pending)
    total=[round(sum(r[k] for r in pending),1) for k in ('low_minutes','high_minutes')]
    nxt=[round(sum(r[k] for r in pending[:count]),1) for k in ('low_minutes','high_minutes')]
    result=dict(provisional=True,remaining_minutes=total,next_checkpoint=checkpoint,next_checkpoint_minutes=nxt,pending=pending)
    write(run/'report/RUNTIME_ESTIMATE.json',result)
    log(f'Estimated remaining {total[0]}–{total[1]} min; checkpoint {checkpoint:03d} in about {nxt[0]}–{nxt[1]} min (planning range).')
    return result

def parent_check(parent):
    cfg=read(parent/'PRIVATE/CONFIG.json');require(digest(cfg)[:16]==parent.name==PARENT['run_id'],'Wrong repair parent')
    require(cfg['code']==PARENT['v120_code'],'Parent continuation code differs')
    require(sha(parent/'report/REPORT_HASHES.json')==PARENT['report_manifest_sha256'],'Returned parent report changed')
    for r in read(ROOT/'evidence/returned_v120/REPORT_HASHES.json'):
        p=parent/'report'/r['file'];require('..' not in Path(r['file']).parts and p.is_relative_to(parent/'report'),'Unsafe report path')
        require(p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Reviewed parent table changed')
    return read(parent/'PRIVATE/STAGES.json')

def inputs(parent,run,args):
    auths={v:read(parent/'PRIVATE/inputs'/(v+'_AUTH.json')) for v in ('included','excluded')};unique={}
    for v,a in auths.items():
        require(a['author_policy']['accounts']==list(AUTHORS),'Author identity policy differs')
        original=[{k:val for k,val in r.items() if k!='verified_signature'} for r in a['month_records']]
        require(digest([v,a['author_policy'],original])==a['fingerprint'],'Parent input fingerprint differs')
        require(sha(a['success_path'])==a['success_sha256'],'Original parent input receipt changed')
        for r in a['month_records']:unique[str(Path(r['path']).resolve())]=r
    def check(r):
        require(sha(r['path'])==r['expected_sha256'],'Parent analysis input changed');return str(Path(r['path']).resolve()),signature(r['path'])
    with cf.ThreadPoolExecutor(max_workers=min(args.io_workers,args.workers)) as pool,heartbeat('Authenticate reusable analysis Parquets'):stamps=dict(pool.map(check,unique.values()))
    for v,a in auths.items():
        a['verification_session']=os.environ['AUTHOR_EXCLUSION_SESSION']
        for r in a['month_records']:r['verified_signature']=stamps[str(Path(r['path']).resolve())]
        write(run/'PRIVATE/inputs'/(v+'_AUTH.json'),a)
    return auths

def baseline_mechanism(args,run,auths,statuses):
    from audit_current import pinned_report
    source=args.project/'derived/replication/mechanism_rd_audit_resume_v101_PRIVATE/public_results'
    pinned_report(ROOT/'evidence/mechanism/report',source)
    target=run/'PRIVATE/results/included/mechanism/report'
    # Copy corresponding aggregate model and support products, not old source
    # inventories or unrelated prior descriptive corrections.
    root_names={'coefficients','heldout_scores','heldout_calibration','heldout_gap_calibration','conditional_score_diagnostics','common_index_profiles','model_comparisons','same_test_refitting_by_month','same_test_refitting_summary'}
    for p in source.rglob('*.csv'):
        rel=p.relative_to(source)
        if rel.parts[0] not in ('models','unrestricted') and p.stem not in root_names and not p.stem.startswith(('equal_','losing_')):continue
        dst=target/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    receipt=run/'PRIVATE/stage_receipts/included/mechanism.json';write(receipt,{'stage':'mechanism','variant':'included','sample_fingerprint':auths['included']['fingerprint'],'result':'Pinned completed regular-player and RD110 baseline'})
    files=export_tables(run,'included','mechanism');statuses['included/mechanism']={'status':'COMPLETE','origin':'PINNED_PRIOR_MECHANISM_BASELINE','receipt':record(receipt),'aggregate_files':[record(p) for p in files]}

def child(cmd,logfile,label):
    logfile.parent.mkdir(parents=True,exist_ok=True)
    with logfile.open('a') as f:
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        try:
            with heartbeat(label):
                for line in p.stdout:print(line,end='',flush=True);f.write(line);f.flush()
            return p.wait()
        except BaseException:p.terminate();p.wait();raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop');p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--io-workers',type=int,default=4,choices=range(1,5));p.add_argument('--shards',type=int,default=256);p.add_argument('--estimate-only',action='store_true');a=p.parse_args()
    if a.estimate_only:print('Expected 1–3 hours: authentication 5–15 min; bounded session summary 10–45 min; paired fixed-cutoff nonparametric fits 15–60 min; mechanism refit 15–45 min; Framework audit 1–10 min. No completed core fits or session regressions are refitted.');return 0
    reporting.verify_package();versions=reporting.preflight(a);import numba;versions['numba']=numba.__version__
    a.project=a.project.expanduser().resolve();parent=a.project/'derived/replication/author_exclusion_continue_v120_PRIVATE'/PARENT['run_id']
    require(parent.is_dir(),'Reviewed v120 cache missing');lock=(parent/'RUNNING.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    cfg={'version':'1.3.0','parent':PARENT,'code':{p.name:sha(p) for p in sorted((ROOT/'code').glob('*.py'))},'upstream':sha(ROOT/'UPSTREAM_FILES.json'),'versions':versions}
    run=a.project/'derived/replication/author_exclusion_repair_v130_PRIVATE'/digest(cfg)[:16];(run/'report').mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True)
    own=(run/'RUNNING.lock').open('a+');fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
    os.environ['AUTHOR_EXCLUSION_SESSION']=uuid.uuid4().hex;write(run/'PRIVATE/CONFIG.json',cfg);statusfile=run/'PRIVATE/STAGES.json';statuses=read(statusfile) if statusfile.exists() else {};start=time.monotonic()
    reporting.STAGES.append('mechanism');reporting.LABELS['mechanism']='Regular-player mechanism candidates, RD110 sensitivity, temporal folds and unrestricted diagnostics'
    try:
        log('Expected runtime 1–3 hours, provisional; existing completed fits are retained.')
        prior=parent_check(parent);auths=inputs(parent,run,a)
        for token,r in prior.items():
            if r.get('status')!='COMPLETE' or token.endswith('/nonparametric'):continue
            v,s=token.split('/');verify(r['receipt'])
            for f in r['aggregate_files']:verify(f)
            shutil.copytree(parent/'report/tables'/v/s,run/'report/tables'/v/s,dirs_exist_ok=True)
            statuses[token]=r
        for name in ('main_counts.csv','main_counts.parquet','removals_by_month.csv','removals_by_month.parquet','POLICY.json'):shutil.copy2(parent/'report'/name,run/'report'/name)
        if not (run/'report/PREVIOUS_APPROXIMATE_COMPARISON.json').exists():shutil.copy2(parent/'report/COMPARISON_SUMMARY.json',run/'report/PREVIOUS_APPROXIMATE_COMPARISON.json')
        (run/'report/current_audits').mkdir(exist_ok=True)
        for family in ('iv_current','reputation','stakes','mechanism'):
            shutil.copy2(parent/'report/current_audits'/(family+'.json'),run/'report/current_audits'/(family+'.json'))
        baseline_mechanism(a,run,auths,statuses)
        write(run/'report/ENVIRONMENT.json',versions);write(statusfile,statuses);reporting.coverage(run,statuses)
        remaining_estimate(run,statuses,0)
        reporting.package(run,a.result_dir,25)
        failures=[]
        for i,(v,s) in enumerate(JOBS):
            token=v+'/'+s;old=statuses.get(token,{})
            if old.get('status')=='COMPLETE':
                verify(old['receipt'])
                for f in old['aggregate_files']:verify(f)
                continue
            if v=='excluded' and s=='nonparametric' and statuses.get('included/nonparametric',{}).get('status')!='COMPLETE':statuses[token]={'status':'BLOCKED_BASELINE'};continue
            t=time.monotonic();cmd=[sys.executable,str(ROOT/'code/repair_worker.py'),'--project',str(a.project),'--run',str(run),'--parent',str(parent),'--variant',v,'--stage',s,'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
            try:
                require(child(cmd,run/'PRIVATE/logs'/(v+'_'+s+'.log'),token)==0,'Repair stage failed: '+token)
                files=export_tables(run,v,s);require(bool(files),'Missing aggregate output: '+token)
                receipt=run/'PRIVATE/stage_receipts'/v/(s+'.json');statuses[token]={'status':'COMPLETE','seconds':time.monotonic()-t,'receipt':record(receipt),'aggregate_files':[record(p) for p in files]}
            except Exception as exc:statuses[token]={'status':'FAILED','error_class':type(exc).__name__};failures.append(token);diagnostic(run,run,token,exc);log(str(exc))
            write(statusfile,statuses);reporting.coverage(run,statuses)
            log(f'Repair stage {i+1}/{len(JOBS)} finished in {(time.monotonic()-t)/60:.1f} minutes. Remaining stages: '+', '.join(s for _,s in JOBS[i+1:])+'; Framework audit follows.')
            remaining_estimate(run,statuses,i+1)
            if i==0:reporting.package(run,a.result_dir,50)
            if i==2:reporting.package(run,a.result_dir,75)
        cmd=[sys.executable,str(ROOT/'code/audit_current.py'),'--family','framework','--project',str(a.project),'--run',str(run),'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
        rc=child(cmd,run/'PRIVATE/logs/audit_framework.log','Framework audit')
        if rc:diagnostic(run,run,'audit/framework');failures.append('audit/framework')
        if statuses.get('excluded/mechanism',{}).get('status')=='COMPLETE':write(run/'report/current_audits/mechanism.json',{'status':'AUTHOR_EXCLUDED_REGULAR_MODELS_REFITTED','scope':'Regular equal/losing candidates and RD110 audit; earlier tier2 and sampled model families remain pending'})
        paired=[s for s in reporting.STAGES if all(statuses.get(v+'/'+s,{}).get('status')=='COMPLETE' for v in ('included','excluded'))]
        summary=compare_all(run,paired);reporting.coverage(run,statuses)
        write(run/'report/RUNTIME_ESTIMATE.json',{'finished':True,'elapsed_minutes':round((time.monotonic()-start)/60,1),'remaining_minutes':[0,0],'failed_stages':failures})
        write(run/'report/EXECUTION_STATUS.json',{'status':'TARGETED_REPAIR_FINISHED_GLOBAL_COVERAGE_PENDING','seconds':time.monotonic()-start,'failed_stages':failures,'paired_families':paired,'comparison':summary,'session_regressions_refitted':False,'nonparametric_reference':'common exact author-excluded K distribution'})
        reporting.package(run,a.result_dir,100);log('Return the new _100.zip and sidecar. Whole-paper certification remains open.');return 2
    except BaseException as exc:
        write(run/'PRIVATE/FAILURE.json',{'error':str(exc),'traceback':traceback.format_exc()});write(run/'report/EXECUTION_STATUS.json',{'status':'BLOCKED','error_class':type(exc).__name__});reporting.package(run,a.result_dir,0);raise
    finally:own.close();lock.close()

if __name__=='__main__':sys.exit(main())
