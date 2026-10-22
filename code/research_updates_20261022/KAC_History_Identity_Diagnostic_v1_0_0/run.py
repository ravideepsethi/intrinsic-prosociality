#!/usr/bin/env python3
import os
for _name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_name]='1'
from util import *
import argparse, concurrent.futures as cf, fcntl, multiprocessing as mp, traceback, zipfile
import identity


def verify_package():
    p=ROOT/'PACKAGE_MANIFEST.json'
    for r in load(p)['files']:
        f=ROOT/r['path']
        require(f.is_file() and f.stat().st_size==r['bytes'] and sha(f)==r['sha256'],'PACKAGE_DAMAGED')
    return sha(p)


def lock(path):
    h=Path(path).open('a')
    try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        h.close();raise RuntimeError('RELATED_RUN_STILL_ACTIVE_NO_DUPLICATE_STARTED') from None
    return h


def build_catalog(project):
    sys.path.insert(0,str(ROOT/'vendor/merit/source'))
    import pool_wave1_common as a
    main=a.authenticate_sample(project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE',
        verify_hashes=False,hash_workers=1)
    require(main['fingerprint']==load(ROOT/'AUTHORITY.json')['sample_fingerprint'],'WRONG_CERTIFIED_SAMPLE')
    p=ROOT/'authority/chronology.tsv'
    require(sha(p)=='c169bf9e346defde62047a3c2048758c296b1f0598fee70d2cc1e660121536d8','CHRONOLOGY_MANIFEST_DAMAGED')
    rows=pd.read_csv(p,sep='\t').to_dict('records')
    require(len(rows)==852 and sum(int(r['rows']) for r in rows)==7763847245,'CHRONOLOGY_INVENTORY_CHANGED')
    records=[]
    for row in rows:
        month=re.search(r'month=([0-9-]+)',row['path'])[1]
        speed=re.search(r'speed=([^/]+)',row['path'])[1].lower()
        if speed not in SPEEDS or month<'2023-10' or month>'2025-11':continue
        path=relocated(row['path'],project)
        # Optional November 2025 neighbors are not required for panel coverage.
        if month=='2025-11' and not path.is_file():continue
        footer=pq.ParquetFile(path)
        require(path.stat().st_size==int(row['bytes']) and footer.metadata.num_rows==int(row['rows']),
            'CHRONOLOGY_COUNT_OR_SIZE_CHANGED')
        required={'game_id','utc_ms','archive_ordinal','white_id','black_id'}
        require(required<=set(footer.schema_arrow.names),'CHRONOLOGY_IDENTITY_COLUMNS_MISSING')
        records.append(dict(path=str(path),month=month,speed=speed,speed_code=SPEEDS.index(speed),
            rows=int(row['rows']),bytes=int(row['bytes']),stat=snapshot(path)))
    for month in ['2023-10']+MONTHS:
        require({r['speed'] for r in records if r['month']==month}==set(SPEEDS),'MONTH_SPEED_COVERAGE_MISSING')
    return main,records


def read_focal_receipt(parent,main_record,parent_key):
    directory=parent/'PRIVATE/focal'/main_record['month']
    receipt=load(directory/'_DONE.json')
    require(receipt['key']==digest([parent_key,main_record['expected_sha256']]),'FOCAL_RECEIPT_KEY_CHANGED')
    source=receipt['source']
    require(source['sha256']==main_record['expected_sha256'] and str(source['path'])==str(main_record['path']),
        'FOCAL_SOURCE_LINEAGE_CHANGED')
    require(snapshot(main_record['path'])==source['stat'],'CERTIFIED_SOURCE_CHANGED_SINCE_PROJECTION')
    focal=directory/'rows.parquet'
    entries=[r for r in receipt['files'] if r['path']=='rows.parquet']
    require(len(entries)==1 and focal.stat().st_size==entries[0]['bytes'],'FOCAL_FILE_RECEIPT_MISSING')
    require(pq.ParquetFile(focal).metadata.num_rows==main_record['rows'],'FOCAL_COUNT_CHANGED')
    return dict(path=str(focal),sha256=entries[0]['sha256'],stat=snapshot(focal),source=source,
        receipt_sha256=sha(directory/'_DONE.json'),month=main_record['month'])


def inventory(parent,records,parent_key):
    """Inventory only: complete checkpoint hashes are checked by the next resume."""
    rows=[]
    prev=parent/'PRIVATE/history/initial/_DONE.json'
    if prev.is_file():require(load(prev)['key']==parent_key,'INITIAL_HISTORY_KEY_CHANGED')
    else:raise RuntimeError('INITIAL_HISTORY_RECEIPT_MISSING')
    for month in ['2023-10']+MONTHS:
        folder=parent/'PRIVATE/history'/month;p=folder/'_DONE.json'
        item=dict(month=month,completion_receipt_present=p.is_file())
        if p.is_file():
            r=load(p)
            require(prev.is_file(),'HISTORY_CHAIN_GAP')
            expected=digest([parent_key,month,sha(prev),[x['stat'] for x in records if x['month']==month]])
            require(r['key']==expected,'HISTORY_CHAIN_OR_SOURCE_CHANGED')
            # Cheap size checks identify absent outputs without re-reading all data.
            for f in r['files']:
                path=folder/f['path']
                require(not Path(f['path']).is_absolute() and '..' not in Path(f['path']).parts,'UNSAFE_CHECKPOINT_MEMBER')
                require(path.is_file() and path.stat().st_size==f['bytes'],'COMPLETED_HISTORY_FILE_MISSING_OR_RESIZED')
            item.update(focal_rows=r.get('focal_rows',0),receipt_sha256=sha(p),
                receipt_chain_and_sizes_checked=True,full_output_hashes_rechecked=False)
        else:
            item['uncommitted_files_present']=folder.is_dir() and any(folder.glob('*.parquet'))
        rows.append(item);prev=p
    return rows


def month_job(task):
    month, focal, records, run, key, threads, memory=task
    out=Path(run)/'PRIVATE/month_checks'/month
    k=digest([key,month,focal,records])
    for r in records:require(snapshot(r['path'])==r['stat'],'CHRONOLOGY_CHANGED_DURING_DIAGNOSTIC')
    require(snapshot(focal['path'])==focal['stat'],'FOCAL_CHANGED_DURING_DIAGNOSTIC')
    if cached(out,k):
        answer=load(out/'SUMMARY.json');answer['reused']=True;return answer
    require(sha(focal['path'])==focal['sha256'],'FOCAL_CHECKSUM_FAILED')
    t0=time.monotonic();c=db(out/'spill',memory,threads)
    try:answer=identity.compare_month(c,focal['path'],records,out)
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    for r in records:require(snapshot(r['path'])==r['stat'],'CHRONOLOGY_CHANGED_DURING_DIAGNOSTIC')
    require(snapshot(focal['path'])==focal['stat'],'FOCAL_CHANGED_DURING_DIAGNOSTIC')
    answer.update(month=month,seconds=round(time.monotonic()-t0,3),reused=False,
        source_files=len(records),source_rows=sum(r['rows'] for r in records),
        full_chronology_hashes_recomputed=False,chronology_count_size_and_stability_checked=True)
    js(out/'SUMMARY.json',answer);commit(out,k)
    return answer


def deep_job(task):
    month, focal, records, project, run, key, threads, memory=task
    run=Path(run);out=run/'PRIVATE/target_checks'/month
    bad=run/'PRIVATE/month_checks'/month/'bad_focal.parquet'
    n=pq.ParquetFile(bad).metadata.num_rows
    require(n>0,'NO_FAILED_FOCAL_ROWS_FOR_DEEP_CHECK')
    if n>10000:
        return dict(month=month,status='TARGETED_PROBE_LIMIT_EXCEEDED',failing_focal_rows=n,
            note='All failures remain in the private Parquet; no observations excluded.')
    k=digest([key,month,sha(bad),focal,records,'candidate_probe_v1'])
    require(snapshot(focal['source']['path'])==focal['source']['stat'],'CERTIFIED_SOURCE_CHANGED')
    for r in records:require(snapshot(r['path'])==r['stat'],'CHRONOLOGY_CHANGED')
    if cached(out,k):return load(out/'SUMMARY.json')
    t0=time.monotonic()
    # Authenticate the entire certified monthly file only for months with failures.
    source=checked(focal['source']['path'],focal['source']['sha256'])
    c=db(out/'spill',memory,threads)
    try:canonical=identity.certified_targets(c,source['path'],bad,out)
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    c=db(out/'spill',memory,threads)
    try:comparison=identity.probe(c,out/'canonical_targets.parquet',records,month,out)
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    c=db(out/'spill',memory,threads)
    try:producer=identity.upstream(c,out/'canonical_targets.parquet',
        [r for r in records if r['month']==month],project,month,out)
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    unchanged([source])
    for r in records:require(snapshot(r['path'])==r['stat'],'CHRONOLOGY_CHANGED_DURING_PROBE')
    answer=dict(month=month,status='TARGETS_INSPECTED_REPAIR_NOT_APPLIED',
        certified_source_sha256=source['sha256'],failing_focal_rows=n,
        canonical=canonical,candidates=comparison,declared_upstream=producer,
        seconds=round(time.monotonic()-t0,3))
    js(out/'SUMMARY.json',answer);commit(out,k,certified_source=source,chronology_sources=records)
    return answer


def neighborhood(records,month):
    center=pd.Period(month,freq='M');months={str(center-1),month,str(center+1)}
    return [r for r in records if r['month'] in months]


def export(run,desktop,tag):
    report=Path(run)/'report';items=[]
    for p in sorted(report.rglob('*.json')):
        if p.name!='REPORT_MANIFEST.json':items.append(dict(path=str(p.relative_to(report)),bytes=p.stat().st_size,sha256=sha(p)))
    js(report/'REPORT_MANIFEST.json',dict(files=items))
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    dest=desktop/f'KAC_HISTORY_IDENTITY_DIAGNOSTIC_{tag}_{Path(run).name}.zip'
    temp=dest.with_suffix('.partial.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for r in items:z.write(report/r['path'],'report/'+r['path'])
        z.write(report/'REPORT_MANIFEST.json','report/REPORT_MANIFEST.json')
        for name in ('README.md','VALIDATION.md','PACKAGE_MANIFEST.json'):
            z.write(ROOT/name,name)
    os.replace(temp,dest);textfile(dest.with_suffix('.zip.sha256'),sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_RESULT '+str(dest));return dest


def publish_month(run,answer):
    js(run/'report/month_checks'/f'{answer["month"]}.json',answer)
    log(f'{answer["month"]}: {answer["focal_rows"]:,} focal games; '
        f'{answer["failing_focal_rows"]:,} identity failures'
        + (' (cached)' if answer.get('reused') else f'; {answer["seconds"]/60:.1f} min'))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--worker-budget',type=int,default=10)
    ap.add_argument('--io-workers',type=int,default=3)
    ap.add_argument('--self-test',action='store_true')
    args=ap.parse_args();package_sha=verify_package()
    if args.self_test:
        import test_identity;test_identity.main();return
    require(1<=args.worker_budget<=10 and 1<=args.io_workers<=3,'USE_BUDGET_1_TO_10_AND_IO_1_TO_3')
    auth=load(ROOT/'AUTHORITY.json');project=args.project_root.resolve()
    require(str(project)==auth['parent_config']['project'],'PROJECT_DIFFERS_FROM_REVIEWED_RUN')
    parent=project/'output/kac_repetition_sensitivity_v100'/auth['parent_run']
    actual=load(parent/'report/CONFIG.json')
    # Performance settings may differ on a harmless resume; scientific config must not.
    for k in ('version','package_sha','project','amendment_sha'):
        require(actual.get(k)==auth['parent_config'][k],'PARENT_CONFIG_CHANGED')
    require(sha(ROOT/'authority/PARENT_PACKAGE_MANIFEST.json')==actual['package_sha'],'PARENT_PACKAGE_AUTHORITY_CHANGED')
    locks=[]
    roots=[parent,project/'output/kac_companion_analyses_v100/9560b33ec926b6ca',
        project/'output/kac_companion_recovery_v102/740c76ad339f76e4',
        project/'output/kac_companion_resume_v101/23716a25c7252fd1']
    for root in roots:
        if root.is_dir():locks.append(lock(root/'RUN.lock'))
    conf=dict(version='1.0.0',package_sha=package_sha,project=str(project),
        parent_run=auth['parent_run'],first_month=auth['failure_month'])
    key=digest(conf);run=project/'output/kac_history_identity_diagnostic_v100'/key[:16]
    run.mkdir(parents=True,exist_ok=True);locks.append(lock(run/'RUN.lock'))
    js(run/'report/CONFIG.json',dict(**conf,worker_budget=args.worker_budget,io_workers=args.io_workers,
        duckdb=duckdb.__version__,pyarrow=pa.__version__,python=sys.version.split()[0]))
    status=dict(status='IN_PROGRESS',source_files_modified=False,existing_checkpoints_modified=False,
        models_rerun=0,account_exclusions=0,focal_exclusions=0,api_requests=0,timestamps_imputed=0,
        scientific_gates_relaxed=False,strict_timestamp_status='UNRESOLVED')
    try:
        log('Checking frozen inputs and inventorying completed history checkpoints')
        main_sample,records=build_catalog(project)
        inv=inventory(parent,records,auth['parent_key'])
        js(run/'report/PARENT_CHECKPOINTS.json',dict(months=inv,
            full_output_hashes_rechecked=False,note='Inventory only; completed months are not rebuilt or modified.'))
        required=[m for m in MONTHS if m>=auth['failure_month']]
        main_by_month={r['month']:r for r in main_sample['month_records']}
        focals={m:read_focal_receipt(parent,main_by_month[m],auth['parent_key']) for m in required}
        budget,_=slots(args.worker_budget,args.io_workers*2)
        workers=min(args.io_workers,max(1,budget//2));threads=max(1,min(2,budget//workers))
        memory=min(3.,max(1.,memory_gb()*.35/workers))
        js(run/'report/RESOURCE_PLAN.json',dict(month_workers=workers,threads_each=threads,
            maximum_simultaneous_query_threads=workers*threads,memory_gb_each=memory,
            full_panel_rows=main_sample['authority']['rows'],months_to_check=len(required),
            completed_history_months=sum(x['completion_receipt_present'] for x in inv)))
        def task(m):return (m,focals[m],[r for r in records if r['month']==m],str(run),key,threads,memory)
        first=auth['failure_month'];answers=[]
        log('Inspecting the failed August 2024 identities first; sessions are not being rebuilt')
        with heartbeat('August identity check'):
            answer=month_job(task(first));answers.append(answer);publish_month(run,answer)
            status['reviewed_failure_reproduced']=answer['replicated_parent_check']==auth['expected_failed_join']
            if answer['failing_focal_rows']:
                deep=deep_job((first,focals[first],neighborhood(records,first),str(project),str(run),key,threads,memory))
                js(run/'report/target_checks'/f'{first}.json',deep)
        js(run/'report/STATUS.json',status);export(run,args.desktop,'EARLY')
        remaining=[m for m in required if m!=first]
        log(f'Checking {len(remaining)} later months with {workers} jobs, {threads} query threads each')
        with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
            pending={ex.submit(month_job,task(m)):m for m in remaining}
            start=time.monotonic();done=0
            with heartbeat('Later-month identity preflight'):
                for f in cf.as_completed(pending):
                    answer=f.result();answers.append(answer);publish_month(run,answer);done+=1
                    eta=(time.monotonic()-start)/done*(len(remaining)-done)/60
                    log(f'Month scans {done}/{len(remaining)}; measured scan time remaining about {eta:.0f} min, plus target probes')
        for answer in sorted(answers,key=lambda x:x['month']):
            month=answer['month']
            if month==first or not answer['failing_focal_rows']:continue
            threads_now,_=slots(args.worker_budget,2)
            log(month+': inspecting failed identities and producer-declared input Parquets')
            with heartbeat('Target probe '+month):
                deep=deep_job((month,focals[month],neighborhood(records,month),str(project),str(run),key,threads_now,memory))
            js(run/'report/target_checks'/f'{month}.json',deep)
        status.update(status='DIAGNOSTIC_COMPLETE_REPAIR_NOT_APPLIED',months_checked=len(answers),
            focal_rows_checked=sum(x['focal_rows'] for x in answers),
            failing_focal_rows=sum(x['failing_focal_rows'] for x in answers),
            failing_months=[x['month'] for x in sorted(answers,key=lambda x:x['month']) if x['failing_focal_rows']])
    except Exception as exc:
        textfile(run/'PRIVATE/ERROR.txt',traceback.format_exc())
        reason=str(exc) if isinstance(exc,RuntimeError) and re.fullmatch(r'[A-Z0-9_]+',str(exc)) else type(exc).__name__
        status.update(status='DIAGNOSTIC_BLOCKED',reason=reason,private_error_file='PRIVATE/ERROR.txt')
        log('Diagnostic stopped: '+reason)
    finally:
        js(run/'report/STATUS.json',status)
        export(run,args.desktop,'RESULT' if status['status']=='DIAGNOSTIC_COMPLETE_REPAIR_NOT_APPLIED' else 'PARTIAL')
    if status['status']=='DIAGNOSTIC_BLOCKED':raise SystemExit(1)
    log('Diagnostic complete. Upload the RESULT ZIP and .sha256. The repetition fit has not restarted.')


if __name__=='__main__':main()
