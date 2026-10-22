#!/usr/bin/env python3
"""Follow-up diagnostics using completed caches. Expected runtime: 30-90 minutes.
Restart: 5-15 minutes with complete caches. No replay, API, engine, or pip calls.
"""
from __future__ import annotations
import argparse, fcntl, platform, shutil, threading, traceback, zipfile
from concurrent.futures import ProcessPoolExecutor,as_completed
from io_tools import *
from prepare import pool_specs,prepare_month,summarize
from power import support_scenario,weekly_screen,PLACEBOS
from grace import grace_month,historical_inventory,finalize_grace

def verify_package():
    manifest=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        expected,name=line.split('  ',1)
        if sha(PACKAGE/name)!=expected:raise RuntimeError('Package checksum differs: '+name)
    return sha(manifest)

def run_parallel(function,tasks,workers,status_path):
    completed=[];failed=[]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        fs={executor.submit(function,t):t for t in tasks}
        for f in as_completed(fs):
            try:completed.append(f.result())
            except Exception as exc:
                failed.append(dict(task=str(fs[f]),error=str(exc),traceback=traceback.format_exc()));log(str(exc))
            write_json(status_path,dict(completed=completed,failures=failed,total_expected=len(tasks)))
    return completed,failed

def bundle(report,desktop):
    report,desktop=map(Path,(report,desktop));desktop.mkdir(parents=True,exist_ok=True)
    archive=desktop/(report.name+'.zip');temp=archive.with_suffix('.tmp.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,report.name+'/'+str(p.relative_to(report)))
    os.replace(temp,archive);atomic_text(Path(str(archive)+'.sha256'),sha(archive)+'  '+archive.name+'\n')
    log('Upload result: '+str(archive));return archive

def write_summary(report,work,failures,grace_results,support_results,pool_status,start):
    status=dict(status='DIAGNOSTICS_COMPLETE' if not failures else 'PARTIAL_RESULTS_REVIEW_REQUIRED',
       elapsed_seconds=round(time.monotonic()-start,1),failures=failures,pool_sample=pool_status,
       grace_months=[dict(month=x.get('month'),status=x.get('status')) for x in grace_results],
       support_scenarios=[x.get('scenario') for x in support_results],private_parquet_root=str(work),
       scientific_go='NOT_YET_ELIGIBLE',causal_regressions_run=False,iv_run=False,
       exact_visibility='UNIDENTIFIED',grace_deployment='UNIDENTIFIED',
       post_period_main_sample='Pool/observed-adjacency extension not certified; all-source results remain diagnostics')
    write_json(report/'SUMMARY.json',status)
    text=f"""# Color-change follow-up diagnostics

Computation: **{status['status']}**. Elapsed {status['elapsed_seconds']/60:.1f} minutes.

Read `SUMMARY.json` for failures and scope. Completed data are retained at `{work}`.

1. `matched_opportunity_calibration`: validation in actual board/cohort/RD/color/outcome cells, against the November 1–18 baseline. Missing baseline cells are missing, never zero. `draw_integer_distribution` separates displayed ties, both bands and recorded integer outcomes. Returners receive a separate validation table.
2. `dose_by_period`, `premium_by_band`, `returning_support`, `coverage`: exact timing windows, competitive/losing states, signed and absolute dose, history coverage and returning-player denominators. Rows for all accounts, established accounts and returners overlap; do not add their counts.
3. `residualized_support`: outcome-free variation in Post*dG after chooser/week effects and the listed diagnostic controls. January 7 and January 30 are prespecified truncation scenarios, not certified mechanics dates. Account tenure and final board/stage controls are not supplied here.
4. `weekly_power_screen`, `awareness_planning_scenarios`, `frozen_pre_placebos`: pre-period weekly-contrast MDEs with 4/8-week blocks and twelve fixed placebo dates. Their statistic is the mean White-minus-Black grant-rate difference over 4 or 8 weeks relative to the preceding 8 weeks. They are not A3 slope or threshold-DDD MDEs. Awareness and the smooth-profile slopes are planning scenarios, not measured quantities. The screen assumes sufficiently stable pre-period time dependence and is diagnostic, not confirmatory.
5. `grace_daily`, `grace_complete_window_diagnostics`, `GRACE_AND_IV_STATUS`, `FEBRUARY_LINEAGE`: selected-frame entry rates, separate observed/missing-clock frames, and complete-window flags. The historical February recut is timeout-only. Any `february_active_only` table is conditional on active resolution and cannot provide an entry denominator. `targeted_hourly` is not the platform-wide incident control. Incomplete windows have no estimated change.

Pool membership is authenticated for the existing November 2023–October 2025 sample. The certificate removes observed mutual adjacency; it does not certify removal of every literal immediate rematch. Unknown post-period membership is retained as unknown. Consequently pool-pre and all-source-post results must not be combined as a common-sample event study.

The code uses the already computed price shifts. The producer carries no fractional rating phase, so factual display visibility and cumulative informative feedback remain unidentified. No integer-rounding proxy is relabeled as exact visibility.

The result does not release a causal coefficient, IV estimate, causal bound or automatic GO decision. Review calibration, sample support and the unresolved source/censoring dependencies first. No raw PGNs, full-history replay, Stockfish, API calls, identity recovery, or environment installation was performed.
"""
    atomic_text(report/'READ_ME_FIRST.md',text)
    return status

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--workers',type=int,default=10)
    parser.add_argument('--memory-gb',type=float,default=8.)
    args=parser.parse_args()
    if not 1<=args.workers<=10:parser.error('workers must be 1-10')
    if not 4<=args.memory_gb<=32:parser.error('memory-gb must be 4-32; this bounds DuckDB, not total process RSS')
    project=args.project_root.expanduser().resolve();first=project/'derived/replication_36m/color_change_firstpass_v100'
    if not project.is_dir() or not (first/'FROZEN_PLAN.json').is_file():parser.error('Completed first-pass project/cache not found; check mounted XT_Pro')
    work=project/'derived/replication_36m/color_change_followup_v100';work.mkdir(parents=True,exist_ok=True)
    first_lock=open(first/'run.lock','r');lock=open(work/'run.lock','a+')
    try:
        fcntl.flock(first_lock,fcntl.LOCK_SH|fcntl.LOCK_NB);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('First pass or follow-up already running; no second writer started')
    stamp_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report=project/'output/color_change_followup_v100'/('COLOR_FOLLOWUP_RESULT_'+stamp_id);report.mkdir(parents=True,exist_ok=True)
    start=time.monotonic();stop=threading.Event();failures=[];gresults=[];support=[];pstatus={}
    def heartbeat():
        while not stop.wait(45):log(f'Follow-up running; elapsed {(time.monotonic()-start)/60:.1f} min')
    threading.Thread(target=heartbeat,daemon=True).start()
    try:
        codehash=verify_package()
        contract=dict(version=VERSION,package_sha256=codehash,cutoff_utc='2025-11-18T07:22:00Z',
          announcement_utc='2025-12-22T22:35:00Z',jan7_convention='2026-01-07T00:00:00Z; date-only information marker',
          dose_input='unchanged first-pass reconstructed states and payoff differences',
          cohort='at least 100 same-speed updates by October 31, 2023',
          returner='fixed established cohort, RD>=200, same-speed last-update gap>=90 days',
          support_truncation_scenarios=['2026-01-07T00:00:00Z','2026-01-30T00:00:00Z'],
          source_pool='certified observed-nonadjacency predicate; pre-period only',
          power_statistic='8 pre weeks; 4 or 8 post weeks; equal weekly weight; White-minus-Black grant rates',
          power_blocks=[4,8],bootstrap_repetitions=10000,power=.8,alpha=.05,placebos=list(PLACEBOS),
          outcomes_not_used_to_select_specification=True,formal_go=False)
        frozen=work/'RUN_CONTRACT.json'
        if frozen.is_file() and read_json(frozen)!=contract:raise RuntimeError('Existing follow-up contract differs; preserve it for review')
        write_json(frozen,contract);write_json(report/'RUN_CONTRACT.json',contract)
        fp=read_json(first/'FROZEN_PLAN.json')
        if fp.get('advantage_elo')!=ADVANTAGE or fp.get('color_cutoff_utc')!='2025-11-18T07:22:00Z':raise RuntimeError('First-pass formula/timing contract differs')
        if shutil.disk_usage(work).free<20*1024**3:raise RuntimeError('At least 20 GiB free needed for narrow Parquets, temporary matrices and SQL spill')
        memory_mb=int(args.memory_gb*1024);per_worker=max(384,memory_mb//args.workers)
        write_json(report/'ENVIRONMENT.json',dict(python=platform.python_version(),platform=platform.platform(),
          duckdb=duckdb.__version__,numpy=np.__version__,pandas=pd.__version__,pyarrow=pa.__version__,
          workers=args.workers,duckdb_memory_mb=memory_mb,expected_runtime='30-90 minutes initially; 5-15 minutes on a completed restart; estimates, not laptop benchmarks',
          memory_note='DuckDB budget plus Python overhead and at most one memory-mapped support scenario at a time; 16 GB RAM or more recommended'))
        pools,pstatus=pool_specs(project);write_json(report/'POOL_AUTHORITY_STATUS.json',pstatus)
        log(f'Expected runtime 30-90 min; {args.workers} independent monthly workers. Existing caches are read only.')
        tasks=[(str(project),str(first),str(work),m,pools.get(m),per_worker) for m in MONTHS]
        prepared,pfails=run_parallel(prepare_month,tasks,args.workers,report/'PREPARATION_STATUS.json');failures.extend(pfails)
        if pfails:raise RuntimeError('Some narrow months failed; completed months are retained. See PREPARATION_STATUS.json')
        summarize(work,report,args.workers,memory_mb)
        for name,end in [('through_jan6',JAN7),('before_jan30_scenario',JAN30)]:
            try:support.append(support_scenario(work,name,end,args.workers,memory_mb))
            except Exception as exc:failures.append(dict(stage='support_'+name,error=str(exc),traceback=traceback.format_exc()))
        write_json(report/'residualized_support.json',support)
        if support:
            flat=[{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in support]
            df=pd.DataFrame(flat);frame(df,report/'residualized_support.parquet');df.to_csv(report/'residualized_support.csv',index=False)
        weekly_screen(report)
        historical_inventory(project,report)
        tasks=[(str(project),str(first),str(work),m,min(2048,memory_mb//3)) for m in ('2026-01','2026-02','2026-03')]
        gresults,gfails=run_parallel(grace_month,tasks,min(3,max(1,args.workers//2)),report/'GRACE_STATUS.json');failures.extend(gfails)
        finalize_grace(first,work,report,gresults,args.workers,memory_mb)
    except Exception as exc:
        failures.append(dict(stage='run',error=str(exc),traceback=traceback.format_exc()));log('Review required: '+str(exc))
    finally:
        status=write_summary(report,work,failures,gresults,support,pstatus,start)
        write_json(report/('_COMPUTATION_COMPLETE.json' if not failures else 'FAILURE.json'),status)
        shutil.copy2(PACKAGE/'README.md',report/'PACKAGE_README.md')
        shutil.copy2(PACKAGE/'PACKAGE_MANIFEST.sha256',report/'EXECUTED_PACKAGE_MANIFEST.sha256')
        for source in sorted((PACKAGE/'code').glob('*.py')):
            dest=report/'executed_code'/source.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(source,dest)
        bundle(report,args.desktop);stop.set()
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close();fcntl.flock(first_lock,fcntl.LOCK_UN);first_lock.close()
    log(status['status']+' — scientific GO decision remains separate')
    return 0 if not failures else 2

if __name__=='__main__':raise SystemExit(main())

