#!/usr/bin/env python3
"""Local, resumable receipt-IV cohort assembly. Author exclusion is deferred."""
import os
for _key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_key]='1'
import argparse,concurrent.futures as cf,fcntl,multiprocessing as mp,platform,resource,shutil,time,traceback
from common import *
import contracts,spine,chronology,followup,report

def code_signature():
    return digest({str(p.relative_to(PACKAGE)):sha(p) for d in ('code','vendor') for p in sorted((PACKAGE/d).glob('*.py'))})

def jobs_run(jobs,fn,workers,label,benchmark=None):
    if not jobs:return []
    results={};at=0;started=time.monotonic();pending={};fresh=done=0
    total=sum(j.get('record',{}).get('rows',0) for j in jobs)
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        try:
            while pending or at<len(jobs):
                # Refill immediately whenever a worker finishes; no batch-wide waits.
                while len(pending)<workers and at<len(jobs):pending[ex.submit(fn,jobs[at])]=at;at+=1
                ready,_=cf.wait(pending,return_when=cf.FIRST_COMPLETED)
                for f in ready:
                    idx=pending.pop(f);r=f.result();results[idx]=r
                    if benchmark:
                        nr=r['result']['total_rows'];done+=nr
                        if not r['reused']:fresh+=nr
                        elapsed=time.monotonic()-started;eta=(total-done)/(fresh/elapsed)/3600 if fresh else None
                        write_json(benchmark,dict(files_done=len(results),files_total=len(jobs),rows_done=done,rows_total=total,
                            invocation_seconds=elapsed,remaining_query_pass_hours=eta,estimate_is_query_pass_only=True,
                            reused_files=sum(v['reused'] for v in results.values())))
                        log(f'{label}: {len(results)}/{len(jobs)}; '+(f'query-pass ETA {eta:.2f} hours' if eta is not None else 'reusing completed work'))
                    else:log(f'{label}: {len(results)}/{len(jobs)} complete or reused')
        finally:
            for f in pending:f.cancel()
    return [results[k] for k in range(len(jobs))]

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=ORIGINAL_PROJECT)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10);ap.add_argument('--memory-gb',type=int,default=8)
    args=ap.parse_args(argv)
    if not 1<=args.workers<=10:ap.error('workers must be 1–10')
    if not 4<=args.memory_gb<=64:ap.error('memory-gb must be 4–64')
    project=args.project_root.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    if not project.is_dir() or not desktop.is_dir():ap.error('Project drive and Lichess_Desktop must exist')
    contracts.inherited_inputs.verify_package()
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(max(soft,min(8192,hard if hard!=resource.RLIM_INFINITY else 8192)),hard))
    work=project/'derived/replication_36m/receipt_iv_cohort_assembly_v100_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=(work/'run.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This cohort assembly is already running')
    started=time.monotonic();code=code_signature();auth=work/'authentication'
    runid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    public=project/'output/receipt_iv_cohort_assembly_v100'/('RECEIPT_IV_COHORT_ASSEMBLY_'+runid);public.mkdir(parents=True)
    config=dict(version=VERSION,code_signature=code,workers_limit=args.workers,memory_budget_gb=args.memory_gb,
        account_policy=contracts.ACCOUNT_POLICY,python=platform.python_version(),duckdb=duckdb.__version__,pyarrow=pa.__version__,numpy=np.__version__,
        author_exclusion_applied=False,mechanics_censor=None,behavioral_estimation=False)
    write_json(public/'RUN_CONFIGURATION.json',config);write_json(public/'ACCOUNT_POLICY.json',contracts.ACCOUNT_POLICY)
    write_json(public/'GATES.json',report.GATES)
    errors=[];phase='authenticate';summary=None
    heavy=min(2,args.workers);per_mb=max(512,(args.memory_gb*1024-2048)//heavy);serial_mb=args.memory_gb*1024-1536
    common=dict(work=str(work),auth=str(auth),code=code,threads=max(1,args.workers//heavy),memory_mb=per_mb)
    try:
        with heartbeat('Authenticating completed source, history and score products'):
            inp=contracts.authenticate(project,work)
        binding=digest(dict(code=code,inputs=inp['snapshots'],chronology=inp['chronology'],account_policy=contracts.ACCOUNT_POLICY))
        runroot=work/'runs'/binding;runroot.mkdir(parents=True,exist_ok=True)
        write_json(runroot/'INPUT_CONTRACT_PRIVATE.json',inp)
        if shutil.disk_usage(work).free<32*1024**3:raise RuntimeError('At least 32 GiB free working space is required; completed inputs are untouched')
        phase='merge_source_supplements';jobs=[]
        for m in MONTHS:
            paths=[inp['choices'][m]];mem=inp['memberships'].get(m);delta=inp['deltas'].get(m);opp=inp['opportunities'].get(m)
            if mem:paths += [mem,opp]
            if delta:paths.append(delta)
            jobs.append(dict(**common,month=m,choice=inp['choices'][m],membership=mem,delta=delta,opportunity=opp,inputs=[contracts.snap(p) for p in paths]))
        months=jobs_run(jobs,spine.month_job,heavy,'Monthly source overlays')
        if sum(p['result']['main_rows'] for p in months)!=55467033 or sum(p['result']['unknown_rows'] for p in months)!=195582:
            raise RuntimeError('Merged source-screen totals differ from reviewed completion')
        phase='prepare_exposure_queries'
        with heartbeat('Joining precomputed scores and preparing exposure queries'):
            prepared=spine.prepare(inp,months,runroot,code,args.workers,serial_mb,auth)
        phase='first_pair_and_volume_query'
        meta=load(prepared/'query_metadata.json')
        # Arrays lie outside DuckDB's memory limit. Reserve explicit per-process
        # space; memory-mapped shared query arrays do not need per-worker copies.
        estimate=384*1024**2+16*meta['rows']+8*meta['pairs']
        scan_workers=max(1,min(args.workers,int((args.memory_gb*1024**3-2*1024**3)//estimate)))
        log(f'Chronology query workers: {scan_workers} (limit {args.workers}; memory-budgeted arrays)')
        records=inp['chronology'];first=list(dict.fromkeys(np.linspace(0,len(records)-1,min(scan_workers,len(records))).astype(int)))
        order=first+[k for k in range(len(records)) if k not in first]
        jobs=[dict(**common,record=records[k],queries=str(prepared),query_receipt=contracts.snap(prepared/'_DONE.json'),old_cache=inp['old_cache']) for k in order]
        scans=jobs_run(jobs,chronology.file_job,scan_workers,'First-pair and volume queries',public/'CHRONOLOGY_BENCHMARK.json')
        phase='first_pair_cohort'
        with heartbeat('Merging first-pair and activity counts'):
            firstpair=chronology.merge(scans,prepared,runroot,code,args.workers,serial_mb,auth)
        phase='historical_count_events';jobs=[]
        for m in MONTHS:
            rr=[r for r in inp['history'] if r['month']==m]
            jobs.append(dict(**common,month=m,paths=[r['path'] for r in rr],inputs=[dict(**r,fingerprint=stamp(r['path'])) for r in rr]))
        histories=jobs_run(jobs,followup.history_month_job,heavy,'Predetermined history event partitions')
        phase='followup_and_spacing';jobs=[]
        stage_inputs=[contracts.snap(Path(p['root'])/'_DONE.json') for p in months+histories]+[contracts.snap(firstpair/'_DONE.json')]
        for bucket in range(16):
            collect=lambda products,folder:[str(f) for p in products for f in sorted((Path(p['root'])/folder/f'bucket={bucket}').glob('*.parquet'))]
            jobs.append(dict(**common,bucket=bucket,queries=[str(p) for p in sorted((firstpair/'queries'/f'bucket={bucket}').glob('*.parquet'))],
                events=collect(histories,'events'),outcomes=collect(months,'outcomes'),inputs=stage_inputs))
        enriched=jobs_run(jobs,followup.bucket_job,heavy,'Outcome, history and spacing buckets')
        phase='final_assembly'
        with heartbeat('Checking row identities and writing aggregate diagnostics'):
            assembled,done=report.assemble(enriched,months,firstpair,prepared,runroot,code,args.workers,serial_mb,auth)
        phase='final_input_check';unchanged(inp['snapshots']);unchanged(inp['chronology'])
        ready=dict(status=done['result']['status'],manifest=str(assembled/'ASSEMBLY_MANIFEST_PRIVATE.json'),
            manifest_receipt=contracts.snap(assembled/'ASSEMBLY_MANIFEST_PRIVATE.json'),assembly_receipt=contracts.snap(assembled/'_DONE.json'),
            account_policy=contracts.ACCOUNT_POLICY,mechanics_censor=None,final_iv_eligible_n=None)
        write_json(work/'READY_FOR_CENSOR_AND_IV_SPECIFICATION_PRIVATE.json',ready)
        for p in assembled.iterdir():
            if p.name.startswith(('COHORT_COUNTS.','SCORE_SUPPORT.','POLICY_AVAILABILITY.','MEMBERSHIP_COUNTS.')):shutil.copy2(p,public/p.name)
        summary=done['result']
    except Exception as e:
        errors.append(dict(stage=phase,exception=type(e).__name__,message=str(e) if isinstance(e,RuntimeError) else 'See private error details'))
        write_json(work/'errors'/runid/'error_PRIVATE.json',dict(stage=phase,error=str(e),traceback=traceback.format_exc()))
        log('Stopped at '+phase+': '+errors[-1]['message'])
    summary=dict(summary or dict(status='PARTIAL_ASSEMBLY',final_iv_eligible_n=None,new_IV_estimate=None),
        elapsed_seconds=time.monotonic()-started,author_accounts_retained=True,author_exclusion_applied=False,errors=errors)
    write_json(public/'SUMMARY.json',summary);write_json(public/'ERRORS.json',errors)
    (public/'READ_ME_FIRST.txt').write_text('This is cohort assembly, not a new IV estimate. Both author accounts remain included by explicit instruction.\n'
        'Calendar-complete counts are provisional until the mechanics censor is frozen; no final IV denominator is claimed.\n'
        'Unknown later-choice membership is flagged. Nonreachers have no assigned later color. New-month RD calibration remains open.\n'
        'Upload this aggregate ZIP and its SHA-256 sidecar. Individual game/account rows remain on XT_Pro.\n'
        'Run the same command to resume completed checkpoints. No source API requests, score rebuild, rating replay or engine search occurs.\n')
    zp=report.zip_report(public,desktop);log(summary['status']);print('UPLOAD: '+str(zp),flush=True);print('UPLOAD: '+str(zp)+'.sha256',flush=True)
    return 1 if errors else 0

if __name__=='__main__':raise SystemExit(main())
