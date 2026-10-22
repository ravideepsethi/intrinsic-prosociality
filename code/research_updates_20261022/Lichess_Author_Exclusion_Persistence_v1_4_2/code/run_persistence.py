"""Finish persistence using the original producer; retain all nineteen completed families."""
from engine import *
from compare import compare_all,FORBIDDEN
import persistence
import argparse,fcntl,platform,traceback,zipfile,uuid
from concurrent.futures import ThreadPoolExecutor

PARENT=read(ROOT/'PARENT.json')


def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        expected,name=line.split('  ',1);p=(ROOT/name).resolve()
        require(ROOT.resolve() in p.parents and p.is_file() and sha(p)==expected,'Changed package file: '+name)


def authenticate_parent(project):
    parent=project/'derived/replication/author_exclusion_repair_v141_PRIVATE'/PARENT['run_id']
    require(parent.is_dir(),'Completed v141 run missing: '+str(parent))
    cfg=read(parent/'PRIVATE/CONFIG.json')
    require(digest(cfg)[:16]==PARENT['run_id'] and cfg['code']==PARENT['code'],'v141 configuration changed')
    require(sha(parent/'report/REPORT_HASHES.json')==PARENT['report_sha256'],'Returned v141 manifest changed')
    for r in read(ROOT/'evidence/V141_REPORT_HASHES.json'):
        rel=Path(r['file']);require(not rel.is_absolute() and '..' not in rel.parts,'Unsafe report path')
        p=parent/'report'/rel
        require(p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Returned v141 report changed: '+str(rel))
    return parent


def authenticate_inputs(parent,workers):
    auths={v:read(parent/'PRIVATE/inputs'/(v+'_AUTH.json')) for v in ('included','excluded')}
    for v,auth in auths.items():
        require(auth['variant']==v and auth['fingerprint']==PARENT['sample_fingerprints'][v],'Wrong paired sample')
        require(auth['author_policy']==POLICY,'Author policy changed')
        rr=auth['month_records']
        require([r['month'] for r in rr]==MONTHS,'Missing panel months')
        fingerprint=digest([v,POLICY,[{k:x for k,x in r.items() if k!='verified_signature'} for r in rr]])
        require(fingerprint==auth['fingerprint'],'Input manifest/fingerprint changed')
        require(sha(auth['success_path'])==auth['success_sha256'],'Input certification changed')
    records={r['path']:r for d in auths.values() for r in d['month_records']}
    def check(r):
        require(Path(r['path']).stat().st_size==r['size_bytes'] and sha(r['path'])==r['expected_sha256'],'Panel checksum changed')
        return r['path'],signature(r['path'])
    with ThreadPoolExecutor(max_workers=min(4,workers)) as pool,heartbeat('Authenticate paired Parquets; expected 3–15 minutes'):
        stamps=dict(pool.map(check,records.values()))
    return auths,stamps


def adopt(parent,run):
    original=read(parent/'PRIVATE/STAGES.json');families=read(parent/'report/EXECUTION_STATUS.json')['paired_families']
    require(len(families)==19 and 'state_persistence' not in families,'Unexpected completed family inventory')
    require(read(parent/'report/CLAIM_STATUS.json')['all_retained_manuscript_items_have_verified_excluded_outputs'],
            'Prior manuscript coverage was not complete')
    statuses={}
    for family in families:
        for v in ('included','excluded'):
            key=v+'/'+family;r=original[key];require(r['status']=='COMPLETE','Incomplete retained stage')
            verify(r['receipt'])
            for f in r['aggregate_files']:verify(f)
            src=parent/'report/tables'/v/family;dst=run/'report/tables'/v/family
            shutil.copytree(src,dst,dirs_exist_ok=True)
            write(run/'report/stage_summaries'/v/(family+'.json'),read(r['receipt']['path']))
            src2=parent/'report/stage_summaries'/v/family
            if src2.is_dir():shutil.copytree(src2,run/'report/stage_summaries'/v/family,dirs_exist_ok=True)
            statuses[key]=r
    for name in ('current_audits','audit_tables'):
        shutil.copytree(parent/'report'/name,run/'report'/name,dirs_exist_ok=True)
    for name in ('main_counts.csv','main_counts.parquet','removals_by_month.csv','removals_by_month.parquet','POLICY.json'):
        shutil.copy2(parent/'report'/name,run/'report'/name)
    write(run/'report/REUSE_V141.json',dict(parent=PARENT['run_id'],completed_families=families,
        retained_paired_stages=38,temporal_randomizations_rerun=0,iv_fits_rerun=0,
        old_persistence_candidates_retained_as_results=False))
    return statuses,families


def coverage(run,parent,statuses):
    rows=pd.read_csv(parent/'report/remaining_coverage.csv')
    for v in ('included','excluded'):
        rows.loc[rows.family=='state_persistence',v]=statuses.get(v+'/state_persistence',{}).get('status','NOT_RUN')
    table(run/'report/remaining_coverage',rows)
    items=pd.read_csv(parent/'report/manuscript_coverage.csv')
    paired_done=all(statuses.get(v+'/state_persistence',{}).get('status')=='COMPLETE' for v in ('included','excluded'))
    mask=items.families.str.contains('state_persistence',regex=False,na=False)
    items.loc[mask,'status']='COMPLETE' if paired_done else 'PERSISTENCE_REPRODUCTION_PENDING'
    table(run/'report/manuscript_coverage',items)
    accepted={'COMPLETE','NOT_AN_ANALYSIS','EXISTING_AUTHOR_EXCLUDED_RESULT_VERIFIED','EXISTING_FRAMEWORK_PERSISTENCE_VERIFIED','ALL_CURRENT_RECEIPT_IV_MODELS_AUTHOR_CLEAN_VERIFIED','ENTRY_AND_ORDINARY_AUTHOR_CLEAN_RESULTS_VERIFIED'}
    covered=all(all(s in accepted for s in str(x).split(';')) for x in items.status)
    write(run/'report/CLAIM_STATUS.json',dict(all_analyses_excluded=paired_done and covered,
        all_requested_paired_stages_finished=paired_done,
        original_persistence_reproduced=statuses.get('included/state_persistence',{}).get('status')=='COMPLETE',
        no_substantive_difference_established=False,manuscript_numerical_reconciliation_complete=False,
        review_required=True,reason='Review the final paired results and reconcile manuscript counts and notes. Already-excluded IV/audited families have no new included counterfactual.'))


def checkpoint(run,destination,percent,remaining):
    write(run/'report/RUNTIME_ESTIMATE.json',dict(checkpoint_percent=percent,remaining_minutes=remaining,
        next_checkpoint_percent={0:25,25:50,50:75,75:100,100:100}[percent],
        next_checkpoint_minutes={0:[3,15],25:[3,12],50:[3,12],75:[1,5],100:[0,0]}[percent]))
    files=[dict(file=str(p.relative_to(run/'report')),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted((run/'report').rglob('*')) if p.is_file() and p.name!='REPORT_HASHES.json']
    write(run/'report/REPORT_HASHES.json',files);destination.mkdir(parents=True,exist_ok=True)
    target=destination/f'AUTHOR_EXCLUSION_REPORT_{run.name}_{percent:03d}.zip';temporary=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((run/'report').rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(run/'report')))
    temporary.replace(target);target.with_suffix('.zip.sha256').write_text(sha(target)+'  '+target.name+'\n')
    log(f'CHECKPOINT {percent}%: {target}; remaining approximately {remaining[0]}–{remaining[1]} minutes.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--workers',type=int,default=10);parser.add_argument('--memory-gb',type=float,default=11)
    parser.add_argument('--estimate-only',action='store_true');a=parser.parse_args()
    if a.estimate_only:
        print('Planning ETA: 15–45 minutes, including fresh verification of 48 Parquets and two original persistence fits. No other analysis refits.');return 0
    verify_package();a.project=a.project.expanduser().resolve()
    require(a.project.is_dir(),'Project volume unavailable');require(1<=a.workers<=10 and a.memory_gb>=4,'Use 1–10 workers and at least 4 GiB memory')
    require(shutil.disk_usage(a.project).free>=12*2**30,'At least 12 GiB free working space required for persistence aggregates and spill')
    versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__)
    cfg=dict(version='1.4.2',parent=PARENT,package_sha256=sha(ROOT/'PACKAGE_MANIFEST.sha256'),versions=versions)
    run=a.project/'derived/replication/author_exclusion_persistence_v142_PRIVATE'/digest(cfg)[:16]
    (run/'PRIVATE').mkdir(parents=True,exist_ok=True);(run/'report').mkdir(exist_ok=True)
    lock=(run/'RUNNING.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    parent_lock=None;statuses={};start=time.monotonic()
    try:
        write(run/'PRIVATE/CONFIG.json',cfg)
        parent=a.project/'derived/replication/author_exclusion_repair_v141_PRIVATE'/PARENT['run_id']
        require(parent.is_dir(),'Completed v141 run missing: '+str(parent))
        parent_lock=(parent/'RUNNING.lock').open('a+');fcntl.flock(parent_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        authenticate_parent(a.project)
        saved=read(run/'PRIVATE/STAGES.json') if (run/'PRIVATE/STAGES.json').exists() else {}
        statuses,families=adopt(parent,run)
        for v in ('included','excluded'):
            key=v+'/state_persistence'
            if saved.get(key,{}).get('status')=='COMPLETE':
                old=saved[key];verify(old['receipt'])
                require(read(old['receipt']['path'])['sample_fingerprint']==PARENT['sample_fingerprints'][v],'Resumed persistence sample changed')
                for f in old['aggregate_files']:verify(f)
                statuses[key]=old
        coverage(run,parent,statuses);checkpoint(run,a.result_dir,0,[15,45])
        auths,stamps=authenticate_inputs(parent,a.workers)
        checkpoint(run,a.result_dir,25,[7,30])
        for v,percent in [('included',50),('excluded',75)]:
            key=v+'/state_persistence';started=time.monotonic()
            if statuses.get(key,{}).get('status')=='COMPLETE':log('Verified completed original persistence fit retained: '+v)
            else:
                out=run/'PRIVATE/results'/v/uuid.uuid4().hex
                log('Fit original persistence: '+v+'; expected 3–12 minutes.')
                try:
                    with heartbeat('Original persistence '+v):result=persistence.run_stage(auths[v],v,out,a.workers,a.memory_gb)
                finally:
                    # Preserve aggregate diagnostics even if strict reproduction fails.
                    if (out/'report').is_dir():shutil.copytree(out/'report',run/'report/tables'/v/'state_persistence/report',dirs_exist_ok=True)
                files=[record(p) for p in sorted((run/'report/tables'/v/'state_persistence').rglob('*')) if p.is_file()]
                receipt=run/'PRIVATE/stage_receipts'/v/'state_persistence.json'
                write(receipt,dict(stage='state_persistence',variant=v,sample_fingerprint=auths[v]['fingerprint'],result=result,code_sha256=sha(persistence.__file__)))
                write(run/'report/stage_summaries'/v/'state_persistence.json',read(receipt))
                statuses[key]=dict(status='COMPLETE',seconds=time.monotonic()-started,receipt=record(receipt),aggregate_files=files)
                write(run/'PRIVATE/STAGES.json',statuses)
            coverage(run,parent,statuses);checkpoint(run,a.result_dir,percent,[4,18] if v=='included' else [1,5])
        for path,stamp in stamps.items():require(signature(path)==stamp,'Panel changed during persistence analysis')
        summary=compare_all(run,families+['state_persistence'])
        coverage(run,parent,statuses)
        require(summary['tables_requiring_alignment_review']==0,'Unresolved comparison table alignment')
        write(run/'report/EXECUTION_STATUS.json',dict(status='COMPLETED_REVIEW_REQUIRED',failed_stages=[],paired_families=families+['state_persistence'],comparison=summary,elapsed_minutes=(time.monotonic()-start)/60))
        checkpoint(run,a.result_dir,100,[0,0]);log('Return the _100.zip and .sha256 for final review.');return 0
    except BaseException as e:
        write(run/'PRIVATE/STAGES.json',statuses)
        write(run/'report/CLAIM_STATUS.json',dict(all_analyses_excluded=False,no_substantive_difference_established=False,review_required=True,status='BLOCKED'))
        write(run/'report/EXECUTION_STATUS.json',dict(status='BLOCKED',error=str(e),traceback=traceback.format_exc(),elapsed_minutes=(time.monotonic()-start)/60))
        checkpoint(run,a.result_dir,0,[0,0]);raise
    finally:
        if parent_lock:parent_lock.close()
        lock.close()


if __name__=='__main__':sys.exit(main())
