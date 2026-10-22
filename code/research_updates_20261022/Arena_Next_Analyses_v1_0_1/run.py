#!/usr/bin/env python3
"""Next arena analyses: original core tables, B1, Patron, receipt/IV, and rank repairs."""
from __future__ import annotations
import argparse, fcntl, importlib.metadata, os, re, subprocess, traceback, zipfile
from next_common import *

STAGES=['core','robustness','rank_repair','episodes','patron','receipt_iv']

def parse_args():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--arena-run',type=Path)
    p.add_argument('--report-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--run-root',type=Path)
    p.add_argument('--workers',type=int,default=10)
    p.add_argument('--threads',type=int,default=8)
    p.add_argument('--memory',default='4GB')
    p.add_argument('--stage',choices=STAGES)
    p.add_argument('--self-test',action='store_true')
    return p.parse_args()

def publish_report(root, report_dir, statuses, elapsed, error=None):
    public=root/'public';public.mkdir(parents=True,exist_ok=True)
    failed=any(v.get('status')=='FAILED' for v in statuses.values()) or error is not None
    finished=len(statuses)==len(STAGES)
    status='ARENA_NEXT_ANALYSES_FAILED_OR_PARTIAL' if failed else ('ARENA_NEXT_ANALYSES_COMPLETE' if finished else 'ARENA_NEXT_ANALYSES_IN_PROGRESS')
    js(public/'RUN_STATUS.json',{'status':status,'stages':statuses,'elapsed_seconds':elapsed,'error':error,
      'version':VERSION,'repository_commit':REPO_COMMIT,'production_data_available_to_package_author':False,
      'main_pool_sample_changed':False,'stockfish_recomputed':False,'new_profile_queries':0,
      'entire_manuscript_analysis_complete':False,'causal_identification_certified':False,
      'environment':{x:importlib.metadata.version(x) for x in ['numpy','pandas','scipy','duckdb','pyarrow']}})
    shutil.copy2(ROOT/'ANALYSIS_SCOPE.md',public/'READ_FIRST.md')
    shutil.copy2(ROOT/'authority/REPOSITORY_SOURCES.json',public/'REPOSITORY_SOURCES.json')
    # Final transfer is aggregate-only, including on failures.
    forbidden={'username','username_norm','chooser_username_norm','disconnected_username_norm','game_id','chooser_user_id',
      'recipient_user_id','recipient_id','opponent_id','chooser_id','query_index','pilot_row','sample_row'}
    import pyarrow.parquet as pq
    for file in public.rglob('*'):
        if file.suffix=='.csv':
            with file.open() as f: names=next(csv.reader(f),[])
        elif file.suffix=='.parquet':names=pq.ParquetFile(file).schema_arrow.names
        else:continue
        require(not (set(names)&forbidden),'Private row identifiers in proposed report: '+str(file))
    js(public/'MANIFEST.json',{'files':inventory(public)})
    report_dir.mkdir(parents=True,exist_ok=True)
    path=report_dir/('ARENA_NEXT_ANALYSES_RESULTS_v101_'+root.name+'.zip');tmp=path.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(public.rglob('*')):
            if f.is_file():z.write(f,f.relative_to(public))
    os.replace(tmp,path);path.with_suffix('.zip.sha256').write_text(sha(path)+'  '+path.name+'\n')
    log('Report: '+str(path));return path

def execute_stage(args):
    require(args.run_root is not None,'Stage requires a run root')
    verify_package();config=read(args.run_root/'private/CONFIG.json');sample=read(args.run_root/'private/INPUTS.json')
    require(config['package_manifest_sha256']==sha(ROOT/'PACKAGE_MANIFEST.sha256'),'Run was created by different code')
    require(config['project']==str(args.project.resolve()) and config['memory']==args.memory,'Stage configuration differs')
    unchanged(sample['signatures']);contract=fingerprint(config);dest=args.run_root/'public'/args.stage
    old=stage_complete(dest,contract)
    if old:log('Verified completed stage: '+args.stage);return old['summary']
    log('Starting '+args.stage)
    with heartbeat('Arena '+args.stage):
        if args.stage in ['core','robustness']:
            from core_stage import run
            result=run(args.stage,sample,args.run_root,args)
        elif args.stage=='rank_repair':
            from rank_stage import run
            result=run(sample,args.run_root,args)
        else:
            module=__import__({'episodes':'episodes_stage','patron':'patron_stage','receipt_iv':'iv_stage'}[args.stage])
            result=module.run(sample,args.run_root,args,contract)
    unchanged(sample['signatures']);finish_stage(dest,contract,result);log('Finished '+args.stage+': '+result['status'])
    return result

def main():
    args=parse_args()
    require(1<=args.workers<=10 and 1<=args.threads<=10,'Worker and thread ceilings are ten')
    require(re.fullmatch('[1-6]GB',args.memory) is not None,'Use a DuckDB memory limit from 1GB to 6GB')
    for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']:
        os.environ[key]='1'
    os.environ.update(PYTHONUNBUFFERED='1',MPLBACKEND='Agg',TZ='UTC')
    if hasattr(time,'tzset'):time.tzset()
    if args.self_test:
        import tests
        return tests.run_tests()
    if args.stage:
        execute_stage(args);return 0
    args.project=args.project.expanduser().resolve();args.report_dir=args.report_dir.expanduser().resolve()
    arena=args.arena_run or args.project/'output/arena_replication_v102'/V102_RUN
    package=verify_package();parent=args.project/'output/arena_next_analyses_v101'
    require(args.project.is_dir(),'Project drive is not mounted: '+str(args.project))
    parent.mkdir(parents=True,exist_ok=True)
    lock=(parent/'RUN.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('An arena-next run is already running')
    baseconfig={'version':VERSION,'package_manifest_sha256':package,'repository_commit':REPO_COMMIT,
      'project':str(args.project),'arena_run':str(Path(arena).resolve()),'input_contract':V102_CONTRACT,
      'workers':args.workers,'threads':args.threads,'memory':args.memory,'stages':STAGES,
      'completed_v100_results_sha256':sha(ROOT/'authority/V100_COMPLETED_RESULTS.zip'),
      'primary_receipt_outcome':'next_all_source_opportunity_is_screened_arena_and_kind','profile_snapshot':'fixed_August'}
    conf=fingerprint(baseconfig)
    if args.run_root:root=args.run_root.expanduser().resolve()
    else:root=parent/('run_'+conf[:16])
    require(root!=Path(arena).resolve() and not root.is_relative_to(Path(arena).resolve()),'New outputs must be separate from v102 inputs')
    (root/'private').mkdir(parents=True,exist_ok=True);(root/'public').mkdir(exist_ok=True)
    if (root/'private/CONFIG.json').exists():require(read(root/'private/CONFIG.json')==baseconfig,'Existing run configuration changed')
    else:js(root/'private/CONFIG.json',baseconfig)
    start=time.monotonic();statuses={};error=None
    log('Arena next analyses '+VERSION+'; run='+str(root))
    log('Five completed v100 analysis families will be imported with their original receipts; receipt/IV is the only new analysis.')
    log('The chronology scan has not yet run on the production arena cohort; its duration is not benchmarked.')
    log('Memory-heavy models run sequentially; chronology uses at most four workers, score histories at most three.')
    try:
        sample=authenticate_arena(arena,root/'private',args.threads,args.memory)
        js(root/'private/INPUTS.json',sample);js(root/'public/INPUT_QA.json',sample['authority'])
        from reuse_completed import import_completed
        import_completed(root,conf,sample)
        free=shutil.disk_usage(root).free
        require(free>=12*1024**3,'Less than 12 GiB free for new caches and temporary spill')
        for name in STAGES:
            dest=root/'public'/name;old=stage_complete(dest,conf)
            if old:statuses[name]=old['summary'];log('Reusing complete '+name)
            else:
                argv=[sys.executable,str(ROOT/'run.py'),'--stage',name,'--project',str(args.project),'--run-root',str(root),
                  '--workers',str(args.workers),'--threads',str(args.threads),'--memory',args.memory]
                rc=subprocess.run(argv).returncode
                if rc==0:
                    result=stage_complete(dest,conf);require(result is not None,'Stage returned without a completion receipt')
                    statuses[name]=result['summary']
                else:statuses[name]={'status':'FAILED','exit_code':rc,'instruction':'Preserve the log and partial report; rerunning resumes completed stages.'}
            publish_report(root,args.report_dir,statuses,time.monotonic()-start)
        unchanged(sample['signatures'])
    except (Exception,KeyboardInterrupt) as e:
        error=repr(e);traceback.print_exc()
    finally:
        publish_report(root,args.report_dir,statuses,time.monotonic()-start,error)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    return 1 if error or any(x.get('status')=='FAILED' for x in statuses.values()) else 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:traceback.print_exc();sys.exit(1)
