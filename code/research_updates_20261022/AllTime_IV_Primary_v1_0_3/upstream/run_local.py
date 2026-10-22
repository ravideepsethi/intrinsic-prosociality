#!/usr/bin/env python3
"""Run each scientific task in an isolated process, retaining checkpoints and logs."""
from __future__ import annotations
import argparse, fcntl, os, platform, shutil, subprocess, sys, traceback, zipfile, signal
from pathlib import Path
# Set before importing NumPy/Arrow or any inherited estimator.
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']:
    os.environ[name]='1'
from local_common import *

# Runtime repairs retain the original cache schemas and scientific definitions.
CACHE_LINEAGE_MANIFEST_SHA256 = '18e6eee5a7e0576ae16b2420de9e11a5059d3210369b34ac227c3ae6bec7c40d'
RELEASE_VERSION = '1.0.3'

STAGE_MODULES={'archive-probe':'archive_probe','opportunities':'opportunities','matched':'matched','iv':'iv_followups','cutoffs':'cutoffs','ply':'descriptives','part-b':'completed_games'}
DEFAULT_STAGES=['opportunities','matched','iv','cutoffs','ply']

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11.)
    p.add_argument('--shards',type=int,default=256)
    p.add_argument('--stages',nargs='+',choices=list(STAGE_MODULES)+['all'],default=DEFAULT_STAGES)
    p.add_argument('--sample-root',type=Path);p.add_argument('--r9-root',type=Path);p.add_argument('--matched-frame',type=Path)
    p.add_argument('--archive-root',type=Path,action='append',help='Repeat for multiple monthly-archive directories')
    p.add_argument('--output-root',type=Path,help='Default: project/derived/replication/r12_r13_followups_v100_PRIVATE')
    p.add_argument('--result-dir',type=Path,help='Aggregate ZIP destination; default project/reports/R12_R13')
    p.add_argument('--games',type=int,default=2000000,help='Part b game draw (500000 is the authorized smaller alternative)')
    p.add_argument('--speeds',nargs='+',choices=['bullet','blitz','rapid','classical'],default=['bullet','blitz','rapid','classical'])
    p.add_argument('--seed',type=int,default=20261014);p.add_argument('--candidate-multiplier',type=float,default=8.)
    p.add_argument('--metadata-source',type=Path,action='append',help='Explicit Parquet/NDJSON/SQLite historical metadata source')
    p.add_argument('--fetch-metadata',action='store_true',help='Permit sequential public game-export requests for unresolved candidate metadata')
    p.add_argument('--max-metadata-games',type=int,default=10000000)
    p.add_argument('--flag-policy',choices=['strict-connected','api-status-proxy'],default='api-status-proxy',help='Default implements the requested no-timeout status screen; strict mode additionally requires historical connection telemetry')
    p.add_argument('--engine',type=Path,help='Original Stockfish executable; SHA256 must match the opportunity sample')
    p.add_argument('--preflight-only',action='store_true');p.add_argument('--self-test',action='store_true')
    p.add_argument('--_worker',choices=list(STAGE_MODULES),help=argparse.SUPPRESS)
    return p

def verify_package():
    manifest=ROOT/'PACKAGE_MANIFEST.sha256'
    require(manifest.is_file(),'Package manifest missing')
    for line in manifest.read_text().splitlines():
        expected,name=line.split('  ',1);p=(ROOT/name).resolve()
        require(p.is_relative_to(ROOT),'Unsafe package manifest path')
        require(sha(p)==expected,'Runner package checksum changed: '+name)
    return sha(manifest)

def configuration(a,package_sha):
    # Completion-size/engine options have their own keyed PRIVATE subdirectory.
    return dict(version='1.0.0',package_manifest_sha256=CACHE_LINEAGE_MANIFEST_SHA256,project=str(a.project.resolve()),shards=a.shards,
                sample_root=str(a.sample_root) if a.sample_root else None,r9_root=str(a.r9_root) if a.r9_root else None,
                matched_frame=str(a.matched_frame) if a.matched_frame else None,archive_roots=[str(p.resolve()) for p in a.archive_root or []])

def preflight(a,run):
    require(a.project.is_dir(),'Project is not mounted: '+str(a.project))
    require(1<=a.workers<=10,'Use 1–10 workers');require(4<=a.memory_gb<=11,'Use a total memory budget between 4 and 11 GiB')
    require(a.shards>=64 and a.shards%16==0,'Use at least 64 shards, in multiples of 16')
    require(a.games in [500000,2000000],'Production part-b draws must be 500000 or 2000000 games')
    require(a.candidate_multiplier>=1,'Candidate multiplier must be >=1')
    run.mkdir(parents=True,exist_ok=True)
    require(shutil.disk_usage(run).free>=20*2**30,'At least 20 GiB free is required; archive/cutoff and part-b work may need substantially more')
    packages={}
    import importlib.metadata
    for name in ['numpy','pandas','pyarrow','duckdb','scipy','zstandard','python-chess']:packages[name]=importlib.metadata.version(name)
    save(run/'report/runtime.json',dict(python=platform.python_version(),platform=platform.platform(),packages=packages,
         workers_cap=a.workers,memory_budget_gib=a.memory_gb,individual_stage_concurrency_is_bounded=True))

def readme(run,state,a):
    template=(ROOT/'REPORT_METHODS.txt').read_text()
    status='\n'.join(f"{name}: {record['status']}" for name,record in state.items())
    notes=[]
    if (run/'report/ALL_GAMES_STATUS.json').exists():
        s=load(run/'report/ALL_GAMES_STATUS.json');notes+=['Archive months used: '+', '.join(s['months_used']),'Archive months missing/failed: '+', '.join(s['months_missing_or_failed'])]
    bridge=run/'report/cutoff_cohort_bridge.json'
    if bridge.exists():
        b=load(bridge);notes.append('Cutoff-5 rebuilt/certified overlap: '+json.dumps({x:b[x] for x in ['rebuilt_cutoff5','overlap_with_certified_R9','certified_R9','same_cohort']}))
    part=run/'report/completed_game_sample_notes.json'
    if part.exists():
        b=load(part);notes+=['Completed-game flag policy: '+b['flag_policy'],b['flag_limitation'],b['position_rule']]
    (run/'report/README.txt').write_text('R12 remaining items and R13\n\nSTATUS\n'+status+'\n\n'+'\n'.join(notes)+'\n\n'+template)

def package(run,a,state,k):
    report=run/'report';report.mkdir(parents=True,exist_ok=True)
    accepted=ROOT/'accepted/position_contrasts_alt.csv'
    shutil.copy2(accepted,report/accepted.name)
    save(report/'accepted_item_1.json',dict(status='Previously accepted, carried forward without re-estimation',R11_run='7c05df5188a7',
         covariance_file='covariance_column1.npz',covariance_sha256='8d158466132d7e88d30e9fdbba1cbd1693a3ce7b0bb922162b6725c45e659e4b',csv_sha256=sha(accepted)))
    readme(run,state,a);save(report/'STATUS.json',state)
    forbidden={'game_id','chooser_id','recipient_id','opponent_id','chooser_user_id','recipient_user_id','fen','pgn','username','person'}
    for p in report.glob('*.csv'):
        with p.open() as f:headers=next(csv.reader(f))
        require(not forbidden&set(headers),'Private identifier field in report CSV: '+p.name)
    files=[p for p in sorted(report.iterdir()) if p.is_file() and p.suffix in ['.csv','.json','.txt'] and p.name!='REPORT_MANIFEST.json']
    save(report/'REPORT_MANIFEST.json',[dict(file=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in files])
    dest=a.result_dir or a.project/'reports/R12_R13';dest.mkdir(parents=True,exist_ok=True)
    done=all(state.get(s,{}).get('status')=='COMPLETE' for s in DEFAULT_STAGES)
    full=done and state.get('part-b',{}).get('status')=='COMPLETE'
    tag='COMPLETE' if full else 'LOCAL_COMPLETE_R13B_PENDING' if done else 'CHECKPOINT'
    path=dest/f'R12_R13_{k[:12]}_{tag}.zip';tmp=path.with_name(path.name+'.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[report/'REPORT_MANIFEST.json']:z.write(p,'report/'+p.name)
        if (run/'run.log').exists():z.write(run/'run.log','run.log')
    os.replace(tmp,path);Path(str(path)+'.sha256').write_text(sha(path)+'  '+path.name+'\n')
    if (run/'run.log').exists():shutil.copy2(run/'run.log',dest/f'R12_R13_{k[:12]}.log')
    log('Aggregate report: '+str(path))

def main():
    a=parser().parse_args();a.project=a.project.expanduser().resolve()
    if a.self_test:
        return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)
    ps=verify_package();cfg=configuration(a,ps);k=key(cfg)
    run=(a.output_root or a.project/'derived/replication/r12_r13_followups_v100_PRIVATE')/k[:12]
    if a._worker:
        import importlib
        importlib.import_module(STAGE_MODULES[a._worker]).run(a,run,k);return 0
    preflight(a,run);save(run/'PRIVATE/RUN_CONFIG.json',cfg)

    state_path=run/'PRIVATE/STATE.json';state=load(state_path) if state_path.exists() else {}
    if a.preflight_only:
        for name,p in [('opportunities',a.sample_root or a.project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'),
                       ('R9',a.r9_root or a.project/'derived/replication/r9_certified_leave_pair_out_v100_PRIVATE/4028bf3e1857')]:log(f'{name}: {p} (exists={p.is_dir()})')
        log('Preflight passed. Detailed source hashes are checked inside each stage.');return 0
    stages=list(STAGE_MODULES) if 'all' in a.stages else list(dict.fromkeys(a.stages));failures=[]
    with (run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This run is already active; do not launch a second writer')
        save(run/'report/execution_package.json',dict(release_version=RELEASE_VERSION,
            actual_package_manifest_sha256=ps,cache_lineage_manifest_sha256=CACHE_LINEAGE_MANIFEST_SHA256,
            cache_compatibility='1.0.3 retains verified 1.0.0/1.0.1/1.0.2 checkpoints; cutoff volume reads the upstream [size, mtime_ns] signature; completed merged histories are reused before query preparation; all samples, estimators, and output schemas are unchanged'))
        for stage in stages:
            state[stage]=dict(status='RUNNING');save(state_path,state)
            log('Starting '+stage)
            args=sys.argv[1:]+['--_worker',stage]
            with (run/'run.log').open('a',buffering=1) as output:
                output.write(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+' STAGE '+stage+'\n')
                child=subprocess.Popen([sys.executable,str(ROOT/'run_local.py'),*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
                try:
                    for line in child.stdout:print(line,end='',flush=True);output.write(line)
                    code=child.wait()
                except KeyboardInterrupt:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=20)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    state[stage]=dict(status='INTERRUPTED');save(state_path,state);package(run,a,state,k);raise
            state[stage]=dict(status='COMPLETE' if code==0 else 'FAILED',exit_code=code);save(state_path,state)
            if code:failures.append(stage)
            package(run,a,state,k)
        if failures:log('Stages needing attention: '+', '.join(failures)+'. See the log; successful stages/checkpoints are retained.')
    return 1 if failures else 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:
        log(type(e).__name__+': '+str(e));traceback.print_exc();sys.exit(1)
