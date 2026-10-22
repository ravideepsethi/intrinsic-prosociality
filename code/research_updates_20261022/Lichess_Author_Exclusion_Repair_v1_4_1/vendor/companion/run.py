#!/usr/bin/env python3
"""Companion runner: recover arena, estimate hour checks and repetition, disclose gaps."""
from __future__ import annotations
import os
for v in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[v]='1'
from util import *
import argparse, fcntl, traceback, zipfile

def package_check():
    p=ROOT/'PACKAGE_MANIFEST.json'
    if not p.is_file():raise RuntimeError('Package manifest missing')
    for row in load(p)['files']:
        file=ROOT/row['path'];require(file.is_file() and sha(file)==row['sha256'],'Package damaged: '+str(file))
    return sha(p)

def arena(out):
    d=load(ROOT/'authority/arena_by_board_merit.json');js(out/'arena/verified_result.json',d)
    manuscript=r'''\paragraph{The position gradient in arena games.}
In the companion sample, the competitive-minus-clearly-worse gradient is
0.882 percentage points smaller in arena games than in pool games
(95\,\% confidence interval: 0.823 to 0.941 points smaller).
The comparison uses 6,078,928 opportunities from 301,490 chooser accounts,
with chooser and time-control-by-month fixed effects and the recorded
rating, board-stage, clock, and rating-uncertainty controls.
Both formats pass the observed-nonadjacency screen; the model includes all
game stages. The difference concerns the additive position gradient.
Arena play differs from pool play in several respects, so this comparison
does not identify an effect of competitive intensity alone.
'''
    textfile(out/'arena/manuscript_insert.tex',manuscript)
    textfile(out/'arena/README.md','Recovered completed arena v1.0.2 result; no rerun. Source archive SHA256: a4c72643573f45eb918517f5b8270dc5f6cd02546247ce8117d56826c4252197. All 213 entries in its manifest were verified during preparation. Interaction arena × competitive = −0.8818547812853582 pp; SE 0.029946981773814007; 95% CI [−0.9405500226469672, −0.8231595399237494]. Arena late-tournament and price analyses are separate and remain outside this result.\n')
    return dict(status='RECOVERED_COMPLETED_RESULT',gradient_change_pp=-0.8818547812853582)

def readiness(project,run):
    from incidents import paths
    receipt,iv=paths(project)
    d=dict(running_jobs=reservations(),receipt_panel=dict(path=str(receipt),exists=receipt.is_file()),
        iv_panel=dict(path=str(iv),exists=iv.is_file()),
        A5_ordinary_loss=dict(status='ENDING_METADATA_REQUIRED',
            reason='Canonical chronology has starts and results, but no ending type or verified game completion timestamp. Preceding disconnections must not be classified as ordinary games by absence from the screened opportunity panel.',
            needed=['game_id','rated standard real-time membership','status: mate/resign/draw/stalemate/outoftime/timeout/other',
                'verified game completion time before focal start','chooser-specific result and rating change','coverage and source receipt'],
            private_keys_written='PRIVATE/history/month=*/focal_history.parquet retains immediate predecessor key, time, tie flag and decoded result; these are not published'),
        timeout_share_design=dict(status='SOURCE_ALIGNMENT_REQUIRED',
            reason='Existing hourly rated-game counts use start cohorts. A timeout-share numerator needs matching start cohorts, ending-type coverage, and an explicit clock-screen universe. Exact-hour FEs in this package are an additional sensitivity, not a completion of that promised share test.'),
        temporal_concentration=dict(status='NOT_REESTIMATED',reason='The original post-first-grant conditional reallocation needs an incident-adjusted state model. Receipt/IV hour checks do not validate that separate benchmark.'))
    raw=Path(project)/'raw/lichess_pgn_standard'
    d['local_raw_archives']=[dict(name=p.name,bytes=p.stat().st_size) for p in sorted(raw.glob('*.zst'))] if raw.exists() else []
    # Bounded footer inventory only: identify retained ending/history products
    # without reading their account rows or walking the large API-response trees.
    import itertools
    base=Path(project)/'derived/replication';inventory=[];seen=set()
    for pattern in ('*history*','*chooser_iv*','*ordinary*','*all_game*'):
        for folder in itertools.islice(base.glob(pattern),20):
            if not folder.is_dir():continue
            for depth in ('*.parquet','*/*.parquet','*/*/*.parquet'):
                for p in itertools.islice(folder.glob(depth),12):
                    if not p.is_file() or str(p.parent) in seen:continue
                    seen.add(str(p.parent))
                    try:
                        f=pq.ParquetFile(p);inventory.append(dict(path=str(p),rows=f.metadata.num_rows,columns=f.schema_arrow.names))
                    except Exception as e:inventory.append(dict(path=str(p),error=str(e)))
    d['bounded_history_and_ending_schema_inventory']=inventory
    js(Path(run)/'report/SOURCE_READINESS.json',d);return d

def export(run,desktop,tag):
    run=Path(run);desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    shutil.rmtree(run/'report/solver_diagnostics',ignore_errors=True)
    for failure in (run/'PRIVATE/hour_solvers').glob('*/*/FAILURE.json'):
        target=run/'report/solver_diagnostics'/failure.parent.parent.name/failure.parent.name
        target.mkdir(parents=True,exist_ok=True);shutil.copyfile(failure,target/'FAILURE.json')
        system=failure.parent/'failed_system.npz'
        if system.is_file():shutil.copyfile(system,target/'failed_system.npz')
    dest=desktop/('KAC_COMPANION_RECOVERY_'+tag+'_'+run.name+'.zip');tmp=dest.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((run/'report').rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(run/'report')))
        for p in [ROOT/'README.md',ROOT/'ANALYSIS_PLAN.md',ROOT/'REPAIR_NOTES.md',ROOT/'PACKAGE_MANIFEST.json']:
            z.write(p,p.name)
    os.replace(tmp,dest);textfile(dest.with_suffix('.zip.sha256'),sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_RESULT '+str(dest));return dest

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--worker-budget',type=int,default=10);ap.add_argument('--io-workers',type=int,default=3)
    ap.add_argument('--memory-gb',type=float,default=None);ap.add_argument('--self-test',action='store_true')
    ap.add_argument('--preflight-only',action='store_true');ap.add_argument('--stage',choices=['all','hours','repetition'],default='all')
    a=ap.parse_args();package_sha=package_check()
    require(1<=a.worker_budget<=10 and 1<=a.io_workers<=a.worker_budget,'Use 1–10 workers and an IO cap no greater than the budget')
    if a.self_test:
        import self_test;self_test.main();return
    import self_test;self_test.quick()
    require(a.project_root.is_dir(),'Project root not mounted: '+str(a.project_root))
    memory=a.memory_gb or min(12.,max(3.,memory_gb()*.4))
    require(memory>=2,'Memory budget too small')
    # Operational CPU/IO caps do not change the statistical design or resume ID.
    conf=dict(version=VERSION,package_sha=package_sha,project=str(a.project_root.resolve()),design_sha=sha(ROOT/'ANALYSIS_PLAN.md'))
    from resume import lock_parent,adopt_models,cache_summary
    parent_lock=lock_parent(a.project_root) # held until this process exits
    key=digest(conf);run=a.project_root/'output/kac_companion_recovery_v102'/key[:16]
    run.mkdir(parents=True,exist_ok=True);lock=(run/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This companion run is already active; do not start a duplicate')
    js(run/'report/CONFIG.json',dict(**conf,worker_budget=a.worker_budget,io_workers=a.io_workers,memory_gb=memory))
    states=dict(arena=arena(run/'report'),A2=dict(status='SEPARATE_RESULT_NOT_RERUN'))
    adopt_models(run,key)
    readiness(a.project_root,run);js(run/'report/STATUS.json',states);export(run,a.desktop,'READINESS')
    if a.preflight_only:return
    try:
        cat=None;history_ok=False
        if a.stage in ('all','repetition'):
            slots(a.worker_budget,1)
            from history import catalog,prepare_history,run_history
            log('Authenticating history; reusing projections and verifying the single affected game timestamp')
            cat=catalog(a.project_root)
            js(run/'report/HISTORY_INPUTS.json',dict(history_files=len(cat['chronology']),history_rows=sum(r['rows'] for r in cat['chronology']),
                sample_fingerprint=cat['main']['fingerprint'],sample_rows=sum(r['rows'] for r in cat['main']['month_records']),
                semantics=cat['history_semantics']))
            audit=prepare_history(cat,run,key,a.worker_budget,a.io_workers,memory)
            cache_summary(run)
            history_ok=audit['status'] in ('PASS_NO_ANALYSIS_CHOOSER_AFFECTED','PASS_VERIFIED_TIMESTAMP_OVERLAY')
            states['history_timestamp_audit']=dict(status=audit['status'],affected_chooser_file_counts=audit['affected_chooser_file_counts'])
            js(run/'report/STATUS.json',states);export(run,a.desktop,'AUDIT')
            if not history_ok:log('History is blocked by timestamps involving analysis choosers. Hour models continue independently. Upload the AUDIT ZIP.')
        if a.stage in ('all','hours'):
            for stage in ('receipt','iv'):
                slots(a.worker_budget,1)
                log('Starting '+stage+' hour comparisons on existing frozen Parquet rows')
                cmd=[sys.executable,'-u',str(ROOT/'incidents.py'),stage,'--project',str(a.project_root),'--run',str(run),'--key',key]
                logfile=run/'report'/(stage+'_hour.log')
                with logfile.open('a') as f,heartbeat(stage+' hour comparisons'):
                    proc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
                states[stage+'_hours']=dict(status='ESTIMATED' if proc.returncode==0 else 'BLOCKED_OR_FAILED',returncode=proc.returncode,log=logfile.name)
                js(run/'report/STATUS.json',states);export(run,a.desktop,'PARTIAL')
                if proc.returncode:log(stage+' hour comparison stopped; inspect '+str(logfile)+'. Other independent stages continue.')
        if a.stage in ('all','repetition') and history_ok:
            slots(a.worker_budget,1)
            from repetition import run as estimate
            log('Resuming validated history counts and reconstructing remaining sessions')
            require(shutil.disk_usage(run).free>=40*1024**3,'At least 40 GiB free is required before the history stage; existing checkpoints are preserved')
            files=run_history(cat,run,key,a.worker_budget,a.io_workers,memory)
            states['repetition']=estimate(files,run,key,a.worker_budget,memory)
            states['ordinary_loss']=dict(status='ENDING_METADATA_REQUIRED',predecessor_links_prepared=True)
        elif a.stage in ('all','repetition'):
            states['repetition']=dict(status='BLOCKED_AFFECTED_CHOOSER_TIMESTAMP',details='TIMESTAMP_AUDIT.json')
        states['completion']='REQUEST_PARTLY_RESOLVED_SEE_SOURCE_READINESS'
    except Exception as exc:
        states['last_error']=dict(type=type(exc).__name__,message=str(exc));textfile(run/'report/ERROR.txt',traceback.format_exc())
        js(run/'report/STATUS.json',states);export(run,a.desktop,'PARTIAL');raise
    finally:
        cache_summary(run)
        js(run/'report/STATUS.json',states)
    export(run,a.desktop,'RESULT')
    log('Finished available stages. See STATUS.json: a completed run is not a claim that every manuscript TODO is resolved.')

if __name__=='__main__':main()
