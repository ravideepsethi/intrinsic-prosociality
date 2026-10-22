#!/usr/bin/env python3
"""Run Test G v2.1 locally. PGN streaming requires the explicit approval flag; no Lichess API calls."""
from __future__ import annotations
import os
for variable in ['OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']:
    os.environ[variable]='1'
import argparse,fcntl,json,logging,sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'code'))
from g_common import *
from g_inputs import prepare,account_partitions
from g_data import inventory,sample_games
from g_engine import align,evaluate_sample
from g_outcome import train_primary,predict_chunks
from g_fe import *
from g_validate import validate_blocks
from g_bootstrap import bootstrap,fit_stores,extra_statistics
from g_statistics import vector_stats,partial_statistics
from g_reports import *
from g_optional import run_g3
from g_robustness import run_robustness,overlap

class Tee:
    def __init__(self,console,stream):self.console=console;self.stream=stream
    def write(self,text):self.console.write(text);self.stream.write(text);self.stream.flush()
    def flush(self):self.console.flush();self.stream.flush()
    def isatty(self):return False

def point_moments(paths,model,knots,folder,key,subset='all',random=False):
    k=digest([key,'moments',subset,random,knots]);folder=Path(folder)
    if done(folder,k):return read_stores(folder)
    stores=build_moments(paths,model,knots,folder,subset=subset,random=random)
    checkpoint(folder,k,paths,list(folder.glob('*/*.npy'))+list(folder.glob('*/META.json')))
    return stores

def probability_point(run):
    folder=run/'g2/probabilities_PRIVATE';folder.mkdir(exist_ok=True,parents=True)
    def callback(index,d,p):
        atomic_parquet(pd.DataFrame({'game_id':d.game_id,'omega':p[:,0],'draw':p[:,1],'loss':p[:,2],'expected_score':p[:,0]+.5*p[:,1]}),folder/f'b{index:03d}.parquet')
    return callback

def reliability_report(run):
    files=sorted((run/'bootstrap/reliability').glob('b*.npz'));sumvar=0.;N=0;families=0;first=0.;second=0.
    for f in files:
        r=np.load(f);n=int(r['n']);families=n;sumvar+=float((r['m2']/max(1,n-1)).sum());N+=len(r['mean'])
    for p in (run/'g2/probabilities_PRIVATE').glob('*.parquet'):
        x=logit(np.clip(pd.read_parquet(p,columns=['omega']).omega.to_numpy(),PROB_CLIP,1-PROB_CLIP));first+=x.sum();second+=x@x
    cross=second/max(1,N)-(first/max(1,N))**2;value=1-(sumvar/max(1,N))/cross if cross>0 else np.nan
    table(run/'report','tabG2a_stability',[dict(reliability=value,mean_bootstrap_logit_variance=sumvar/max(1,N),point_logit_variance=cross,G1_draws=families,
        interpretation='Sampling instability diagnostic, not a test of misspecification and not a direction-of-bias claim',ci_status='Descriptive variance-component diagnostic; no scientific equivalence interval or classification is attached')],default_meta(run,N))

def runner(a,run,key):
    fill_unrun(run,'Awaiting required prior gates')
    paths=prepare(a,run,key)
    # Inventory and status validation precede new engine calls, G1 and G2.
    pg,rules=inventory(a,run,key);package(run,a.desktop,'PHASE025','SOURCE_INVENTORY_COMPLETE')
    p1=sum(MONTHS.index(m)<12 for m in pg);p2=len(pg)-p1
    if (p1<4 or p2<4) and not a.approve_missing_pgn_streams:
        save(run/'report/DOWNLOAD_PROPOSAL.json',dict(reason='Fewer than four surviving months in each year',P1=p1,P2=p2,
            missing_months=[m for m in MONTHS if m not in pg],method='Approval required: stream-decompress, verify published SHA256, sample without retaining full dumps',downloads_started=False))
        raise GateError('NEEDS_PGN_DOWNLOAD_APPROVAL','The source-coverage rule fails. The aggregate report lists missing months; no PGNs have been downloaded.')
    if a.approve_missing_pgn_streams:
        missing=[m for m in MONTHS if m not in pg]
        save(run/'report/PGN_STREAM_AUTHORIZATION.json',dict(explicit_cli_flag=True,months=missing,time=now(),full_files_stored=False))
        for month in missing:pg[month]=f'https://database.lichess.org/standard/lichess_db_standard_rated_{month}.pgn.zst'
    if a.stop_after=='inventory':return 'STOPPED_AFTER_INVENTORY'
    engine,config=align(a,run,key);package(run,a.desktop,'PHASE050','ENGINE_ALIGNMENT_PASSED')
    if a.stop_after=='g0':return 'STOPPED_AFTER_G0'
    sample=sample_games(a,run,paths,pg,rules,key);positions=evaluate_sample(a,run,sample,engine,config,key)
    accounts=account_partitions(a,run,paths,key);model,templates,merge=train_primary(a,run,positions,accounts,key)
    package(run,a.desktop,'PHASE075','G1_CALIBRATION_AND_STABILITY_PASSED')
    if a.stop_after=='g1':return 'STOPPED_AFTER_G1'
    (run/'g2').mkdir(exist_ok=True);knots=init_knots(accounts,model,run)
    point_dir=run/'g2/point';pk=digest([key,'point',knots]);callback=probability_point(run)
    if done(point_dir,pk):stores=read_stores(point_dir)
    else:
        stores=build_moments(accounts,model,knots,point_dir,probability_store=callback)
        checkpoint(point_dir,pk,accounts+[run/'g2/KNOTS.json'],list(point_dir.glob('*/*.npy'))+list(point_dir.glob('*/META.json'))+list((run/'g2/probabilities_PRIVATE').glob('*.parquet')))
    fits=fit_stores(stores);point=vector_stats(fits,model,templates,knots);point.update(partial_statistics(stores['MRU']))
    variants={};variant_fits={}
    for variant in ['roughly_equal','year2_groups','competitive','unflagged','random_holdout']:
        subset='all' if variant=='random_holdout' else variant
        variants[variant]=point_moments(accounts,model,knots,run/'g2'/variant,key,subset,variant=='random_holdout');variant_fits[variant]=fit_stores(variants[variant])
    point.update(extra_statistics(variants,variant_fits))
    losses=log_losses(accounts,model,knots,fits);point.update({'logloss:'+k:v for k,v in statistics({m:dict(brier=v) for m,v in losses.items()}).items()});point.update({'logloss:'+m+':loss':v for m,v in losses.items()})
    wald,cov=chooser_wald(accounts,model,knots,fits['MRU']['full'],load(point_dir/'MRU/META.json'));save(run/'report/MRU_WALD.json',wald)
    save(run/'g2/POINT_ESTIMATES.json',point);save(run/'report/POINT_ESTIMATES_NO_FINAL_INFERENCE.json',dict(status='Point estimates; paired bootstrap intervals required before classification',values=point));overlap(a,run,accounts,positions)
    validate_blocks(accounts,model,knots,run)
    package(run,a.desktop,'POINT','POINT_ESTIMATES_AND_NUMERICAL_GATES_COMPLETE_NO_FINAL_CLASSIFICATION')
    if a.stop_after=='point':return 'STOPPED_BEFORE_BOOTSTRAP'
    records,exchange_info,mc,stopping=bootstrap(a,run,accounts,positions,model,templates,merge,knots,stores,variants,point,key)
    write_results(run,point,records,exchange_info,mc,stopping,fits,templates);reliability_report(run)
    package(run,a.desktop,'CORE','G1_G2_COMBINED_BOOTSTRAP_COMPLETE')
    optional=run_g3(a,run,positions,model,knots,merge)
    robust=run_robustness(a,run,accounts,positions,model,templates,merge,point)
    pending=[k+': '+v for k,v in optional.items() if v!='estimated']
    pending += [r.get('case','')+': '+r['status'] for r in robust if r.get('status')!='ESTIMATED']
    save(run/'report/COMPLETION_SCOPE.json',dict(core='G-data, G0, G1, G2a–f and combined uncertainty completed',secondary=optional,
        pending_or_failed_sensitivities=pending,all_requested_parts_estimated=not pending,approved_missing_month_streams=a.approve_missing_pgn_streams,no_api_requests=True))
    return 'COMPLETE' if not pending else 'CORE_COMPLETE_SECONDARY_GATES_REPORTED'

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    p.add_argument('--positions',type=int,default=2000000);p.add_argument('--shards',type=int,default=256)
    p.add_argument('--max-g1-draws',type=int,default=500);p.add_argument('--engine');p.add_argument('--extra-pgn-root',action='append',default=[])
    p.add_argument('--optional-manifest',type=Path);p.add_argument('--stop-after',choices=['inventory','g0','g1','point','all'],default='all')
    p.add_argument('--approve-missing-pgn-streams',action='store_true',help='Explicit operator approval for all missing Nov 2023–Oct 2025 PGNs; use only after reviewing the blocked-run inventory')
    a=p.parse_args(argv);a.project_root=a.project_root.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    require(500000<=a.positions<=2000000,'Positions must be between 500,000 and 2,000,000')
    require(a.max_g1_draws in range(50,501,50),'G1 draws must be a multiple of 50, from 50 through 500')
    require(1<=a.workers<=10 and a.memory_gb>=4 and a.shards>=128,'Execution limits must preserve the physical account partitions')
    require(a.project_root.is_dir(),'Project root not found: '+str(a.project_root),'PROJECT_ROOT_MISSING')
    provenance=code_provenance();configuration=dict(protocol=load(ROOT/'FROZEN_PROTOCOL.json'),code=provenance['code_sha256'],sample_authority=sha(ROOT/'vendor_sample/authority/SAMPLE_AUTHORITY.json'),
        positions=a.positions,shards=a.shards,max_g1_draws=a.max_g1_draws,extra_pgn_roots=a.extra_pgn_root,approved_missing_pgn_streams=a.approve_missing_pgn_streams,
        optional_manifest_sha256=sha(a.optional_manifest) if a.optional_manifest else None)
    key=digest(configuration);run=a.project_root/'derived/replication/test_g_v210_PRIVATE'/key[:12];run.mkdir(parents=True,exist_ok=True);(run/'report').mkdir(exist_ok=True)
    lock=(run/'RUN.lock').open('a')
    try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise GateError('RUN_ALREADY_ACTIVE','This Test G configuration is already running')
    output=(run/'RUN.log').open('a',buffering=1);sys.stdout=Tee(sys.stdout,output)
    logging.getLogger('chess.pgn').setLevel(logging.CRITICAL) # Parse errors are raised without exporting a board.
    save(run/'CONFIGURATION.json',configuration);save(run/'report/PROVENANCE.json',dict(provenance,run_date=now(),configuration_sha256=key,
      workers=a.workers,memory_budget_gb=a.memory_gb,source_policy='Missing-month streaming explicitly approved' if a.approve_missing_pgn_streams else 'No PGN downloads; no new API requests'))
    log('Test G '+VERSION+' configuration '+key[:12]);log('Private checkpoints: '+str(run))
    try:
        with heartbeat('Test G runner'):status=runner(a,run,key)
        package(run,a.desktop,'PHASE100' if status in ('COMPLETE','CORE_COMPLETE_SECONDARY_GATES_REPORTED') else 'STOPPED',status)
        shutil.copy2(run/'RUN.log',a.desktop/f'TEST_G_{run.name}.log');log(status);return 0
    except GateError as exc:
        log('STOP '+exc.code+': '+str(exc));save(run/'report/BLOCKED.json',dict(code=exc.code,reason=str(exc),time=now(),no_api_calls=True,approved_streaming_enabled=a.approve_missing_pgn_streams))
        fill_unrun(run,exc.code);package(run,a.desktop,'BLOCKED',exc.code);shutil.copy2(run/'RUN.log',a.desktop/f'TEST_G_{run.name}.log');return 2
    except KeyboardInterrupt:
        log('Interrupted; completed checkpoints are reusable.');package(run,a.desktop,'INTERRUPTED','INTERRUPTED');shutil.copy2(run/'RUN.log',a.desktop/f'TEST_G_{run.name}.log');return 130
    except Exception as exc:
        (run/'TRACEBACK_PRIVATE.txt').write_text(traceback.format_exc());log('Unexpected '+type(exc).__name__+'; private traceback retained locally.')
        save(run/'report/BLOCKED.json',dict(code='UNEXPECTED_'+type(exc).__name__,time=now(),diagnostic=safe_error_location(exc),message='No empirical completion claimed. Private traceback remains in the run directory.'))
        fill_unrun(run,'UNEXPECTED_'+type(exc).__name__);package(run,a.desktop,'BLOCKED','UNEXPECTED_ERROR');shutil.copy2(run/'RUN.log',a.desktop/f'TEST_G_{run.name}.log');return 1
    finally:output.flush();fcntl.flock(lock.fileno(),fcntl.LOCK_UN);lock.close()

if __name__=='__main__':
    try:raise SystemExit(main())
    except GateError as exc:print(exc.code+': '+str(exc),file=sys.stderr);raise SystemExit(2)
