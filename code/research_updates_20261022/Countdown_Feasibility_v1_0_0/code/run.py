#!/usr/bin/env python3
"""Local-only material-threshold feasibility. No regressions or external acquisition."""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
from common import *
from project import REQUIRED, fields, material_sql, project_month
from reports import summarize
import argparse, concurrent.futures as cf, csv, fcntl, multiprocessing as mp, platform, shutil, sys, traceback, zipfile

NOTES = '''Countdown feasibility v1.0.0
These are descriptive support tables, not adjusted regressions or causal estimates.
No API calls, Stockfish searches, receipt-IV fits or source modifications.
Inputs: authenticated author-excluded 24-month pool/nonadjacent main panel.
Material deficit = chooser material minus disconnected-player material. Values: 1,3,3,5,9.
All rows retained in private feature cache. Material/evaluation/clock coverage is reported explicitly.
Finite lost = raw non-mate cp < -100. Competitive includes cp >= -100; mate cases separate.
Main period labels use final-move UTC date: pre < 2025-07-19; post >= 2025-08-11; middle = buffer.
These are calendar proxies; deployment timing is not established by these outputs.
Clock cuts are last-observed-clock proxies, not disconnection clocks or guaranteed common support.
Common cuts in both periods: ultraBullet/bullet 40s; blitz 60s; rapid 120s; classical 300s.
Above means strictly greater. Twice-long sensitivity doubles these same cutoffs.
Stages: ply <=10, 11–20, 21–40, 41–80, 81+; these feasibility bins do not freeze the later regression.
eval10 = 10*floor(cp/10), including negative scores. Mate values never enter these bins.
Overlap cells: API speed × period × stage × eval10 × both clock bins; finite-lost cases only.
Cell overlap and chooser overlap do not establish residual variation after all regression fixed effects.
Unique chooser counts in different cells/months are not additive.
All rate columns are unadjusted percentages. No independence-based standard errors are supplied.
Quantiles prefixed approx use DuckDB approx_quantile; counts, sums and distinct counts are exact.
piece_signature order: chooser P,N,B,R,Q, then disconnected P,N,B,R,Q, comma-separated.
Composition report keeps top 30 combinations per speed/period/deficit; percent_of_group shows coverage.
Weekly clock minima/quantiles cannot establish deployment timing or actual countdown duration.
Only report/ aggregate files are exported. Account IDs, game IDs and positions stay in PRIVATE/.
No feature recovery is attempted from unbound external sources. A coverage report identifies missing work.
Rerun the same command to resume. Completed month files and source hashes are verified before reuse.
'''

def verify_package():
    manifest=ROOT/'PACKAGE_MANIFEST.json'; rows=read(manifest)
    for r in rows:
        rel=Path(r['path']); require(not rel.is_absolute() and '..' not in rel.parts,'Unsafe package member')
        p=ROOT/rel; require(p.is_file() and sha(p)==r['sha256'],'Package checksum differs: '+str(rel))
    return sha(manifest)

def export(run, result_dir, key, progress, status, records):
    report=Path(run)/'report';report.mkdir(parents=True,exist_ok=True)
    write(report/'STATUS.json',{**status,'progress_percent':progress,'version':VERSION,
        'configuration_sha256':key,'API_requests':0,'engine_evaluations':0,'regressions_run':0,
        'causal_estimates_produced':False})
    (report/'README.txt').write_text(NOTES)
    with (report/'monthly_coverage.csv').open('w',newline='') as f:
        cols=['month','reused','elapsed_seconds']+(list(records[0]['counts']) if records else [])
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for r in sorted(records,key=lambda x:x['month']):w.writerow({k:r[k] for k in cols[:3]}|r['counts'])
    manifest=[dict(path=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(report.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    write(report/'REPORT_MANIFEST.json',manifest)
    dest=Path(result_dir)/f'COUNTDOWN_FEASIBILITY_{key[:12]}_{progress:03}.zip';dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,'report/'+p.name)
    os.replace(temp,dest); Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('CHECKPOINT_SAVED '+str(dest));return dest

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--input-manifest',type=Path)
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args(argv)
    require(a.project.is_dir(),'Project directory is not mounted')
    require(a.workers>=1 and a.memory_gb>=3,'Use at least one worker and 3 GB memory')
    code=verify_package(); log('PACKAGE_SHA256_OK')
    a.project=a.project.resolve();a.result_dir=a.result_dir.resolve()
    bootstrap=digest([VERSION,code,str(a.project),'discovery'])
    root=a.project/'derived/replication/countdown_feasibility_v100_PRIVATE'
    run=root/bootstrap[:12];records=[];key=bootstrap;status={'status':'RUNNING','phase':'input_discovery'}
    run.mkdir(parents=True,exist_ok=True)
    # One launcher per project; this lock never touches an upstream producer's files.
    with (root/'run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('A countdown feasibility run is already active')
        try:
            binding, rejected=discover(a.project,a.input_manifest)
            key=digest([VERSION,code,binding['identity'],str(a.project)])
            run=root/key[:12];(run/'report').mkdir(parents=True,exist_ok=True)
            (run/'PRIVATE').mkdir(exist_ok=True)
            write(run/'PRIVATE/INPUT_BINDING.json',binding)
            write(run/'PRIVATE/CONFIG.json',dict(key=key,code=code,input_identity=binding['identity']))
            write(run/'report/input_authority.json',dict(manifest_sha256=binding['manifest_sha256'],
                input_identity=binding['identity'],months=MONTHS,rows=sum(r['rows'] for r in binding['rows']),
                author_accounts_excluded=2,source='author-excluded pool/nonadjacent 24-month main',
                other_invalid_candidates=rejected))
            schemas=[]
            for r in binding['rows']:
                n=fields(r['path']);mat=material_sql(n)
                schemas.append(dict(month=r['month'],rows=r['rows'],has_final_fen=mat['has_fen'],
                    has_piece_counts=mat['has_counts'],missing_required=sorted(set(REQUIRED)-n),
                    cached_feature_fields=sorted(x for x in n if any(t in x.lower() for t in ('fen','material','pawns','moves','pgn')))))
            write(run/'report/schema_coverage.json',schemas)
            if any(x['missing_required'] for x in schemas):
                write(run/'report/other_cache_candidates.json',cached_inventory(a.project))
                raise RuntimeError('Main-panel schema lacks required fields; inspect schema_coverage.json')
            if not all(x['has_final_fen'] or x['has_piece_counts'] for x in schemas):
                write(run/'report/other_cache_candidates.json',cached_inventory(a.project))
                raise RuntimeError('Some months have neither cached final FENs nor complete piece counts; no acquisition attempted')
            workers=min(a.workers,4,max(1,int((a.memory_gb-1.5)/1.6)))
            per_worker=min(2.,max(.5,(a.memory_gb-1.5)*.55/workers))
            summary_memory=max(1.,(a.memory_gb-1.5)*.6)
            require(shutil.disk_usage(root).free>=8*1024**3,'At least 8 GiB free disk is required for features and spill')
            write(run/'report/runtime.json',dict(python=platform.python_version(),duckdb=duckdb.__version__,
                platform=platform.platform(),requested_workers=a.workers,active_workers=workers,
                total_budget_decimal_gb=a.memory_gb,duckdb_gb_per_worker=per_worker,
                duckdb_gb_summary=summary_memory,elapsed_estimates='Live projection ETA excludes summary until measured',
                input_bytes=sum(Path(r['path']).stat().st_size for r in binding['rows'])))
            status.update(phase='monthly_projection',completed_months=0,total_months=24)
            log(f'24 months; {workers} workers; {per_worker:.2f} GB DuckDB per worker. No API / engine / IV work.')
            log('Initial finish ETA unavailable. The first completed months provide measured projection timing.')
            started=time.monotonic(); emitted=set()
            tasks=[dict(record=r,out=str(run/'PRIVATE/months'/r['month']),config=key,memory_gb=per_worker) for r in binding['rows']]
            with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
                futures={pool.submit(project_month,t):t for t in tasks}
                pending=set(futures)
                while pending:
                    done,pending=cf.wait(pending,timeout=30,return_when=cf.FIRST_COMPLETED)
                    for f in done:
                        try:records.append(f.result())
                        except Exception:
                            for x in pending:x.cancel()
                            raise
                    elapsed=time.monotonic()-started
                    remaining=elapsed/max(len(records),1)*(24-len(records)) if records else None
                    eta=f'{remaining/60:.1f} min' if remaining is not None else 'pending measurement'
                    log(f'Months {len(records)}/24; projection ETA {eta}; final summary still pending')
                    status.update(completed_months=len(records),projection_eta_minutes=None if remaining is None else remaining/60)
                    for threshold,progress in [(6,25),(12,50),(18,75)]:
                        if len(records)>=threshold and progress not in emitted:
                            export(run,a.result_dir,key,progress,status,records);emitted.add(progress)
            for r in records:require(stamp(next(x['path'] for x in binding['rows'] if x['month']==r['month']))==r['source_stamp'],'Source changed after projection')
            status.update(phase='aggregate_support',completed_months=24)
            # A COMPLETE report is reusable only after all sources and month receipts have been rechecked.
            final=run/'PRIVATE/FINAL.json'
            if final.exists():
                saved=read(final);require(saved['key']==key,'Final receipt differs')
                for rr in saved['report_files']:verify(rr)
                verify(saved['support']['overlap_cells'])
                status=saved['status'];export(run,a.result_dir,key,100,status,records)
                log(status['status']+': verified saved feasibility results reused.')
                return 0 if status['status']=='COMPLETE' else 2
            def announce(done,total,eta):
                log(f'Aggregate tables {done}/{total}; finish ETA ~{eta/60:.1f} min (table-time extrapolation)')
            with heartbeat('Final support tables'):
                result=summarize(run,records,summary_memory,workers,announce)
            for r in records:require(stamp(next(x['path'] for x in binding['rows'] if x['month']==r['month']))==r['source_stamp'],'Source changed during summaries')
            missing=sum(r['counts']['missing_material'] for r in records)
            status.update(status='COMPLETE' if missing==0 else 'PARTIAL_MATERIAL_COVERAGE',phase='finished',
                rows=result['rows'],missing_material_rows=missing,completed_months=24,
                elapsed_seconds=time.monotonic()-started,feasibility_only=True,
                regression_readiness='Requires review of support tables and a frozen model specification')
            export(run,a.result_dir,key,100,status,records)
            # Exclude the checkpoint status and changing runtime summaries from immutable aggregate receipts.
            immutable=[record(x) for x in sorted((run/'report').glob('*.csv')) if x.name!='monthly_coverage.csv']
            write(final,dict(key=key,status=status,report_files=immutable,support=result))
            log(status['status']+': upload the 100.zip and its .sha256.');return 0 if missing==0 else 2
        except Exception as e:
            status.update(status='BLOCKED',error=str(e),phase=status.get('phase','unknown'))
            (run/'PRIVATE').mkdir(parents=True,exist_ok=True)
            (run/'PRIVATE/ERROR.txt').write_text(traceback.format_exc())
            if status['phase']=='input_discovery':
                (run/'report').mkdir(parents=True,exist_ok=True)
                write(run/'report/other_cache_candidates.json',cached_inventory(a.project))
            export(run,a.result_dir,key,min(75,len(records)//6*25),status,records)
            log('BLOCKED: '+str(e));return 2

if __name__=='__main__':sys.exit(main())
