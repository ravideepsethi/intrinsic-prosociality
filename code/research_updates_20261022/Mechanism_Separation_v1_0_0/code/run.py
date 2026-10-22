#!/usr/bin/env python3
"""Finite mechanism comparison; existing inputs only, resumable stages."""
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS'):
    os.environ[_key]='1'
import argparse,fcntl,multiprocessing,platform,shutil,threading,traceback,zipfile
from datetime import datetime,timezone
from concurrent.futures import ProcessPoolExecutor,as_completed
from common import *
from prepare import sources,narrow_month,needed_users,join_history
from history import catalog,summary_task,features_task
from support import make_support,surface,estimate_cost,mechanical_curves
from models import compare,prediction_profiles,decision,compatible_models
from recovery import prepare_recovery,recovery_task,summarize_recovery
from extras import index_scaling,cue_data,run_cues
from policy import run_policy
from figures import figures

def verify():
    p=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        expected,name=line.split('  ',1)
        if sha(ROOT/name)!=expected:raise RuntimeError('Package integrity failed: '+name)
    return sha(p)

def parallel(fn,tasks,workers):
    if workers==1:return [fn(t) for t in tasks]
    result=[]
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as ex:
        fs=[ex.submit(fn,t) for t in tasks]
        for f in as_completed(fs):result.append(f.result())
    return result

def zip_report(report,desktop):
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    p=desktop/(Path(report).name+'.zip');tmp=p.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(Path(report).rglob('*')):
            if f.is_file():z.write(f,Path(report).name+'/'+str(f.relative_to(report)))
    os.replace(tmp,p);text(Path(str(p)+'.sha256'),sha(p)+'  '+p.name+'\n');log('RESULT_TO_UPLOAD '+str(p));return p

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10)
    ap.add_argument('--memory-gb',type=float,default=8.)
    ap.add_argument('--phase',choices=['all','prepare','support','models','recovery','cost','policy'],default='all')
    ap.add_argument('--cue-manifest',type=Path)
    ap.add_argument('--policy-manifest',type=Path)
    ap.add_argument('--simulation-reps',type=int,default=20)
    a=ap.parse_args()
    if not 1<=a.workers<=10 or not 4<=a.memory_gb<=24:ap.error('Use 1-10 workers and 4-24 GB DuckDB budget')
    if a.simulation_reps<2:ap.error('At least 2 simulation repetitions')
    project=a.project_root.expanduser().resolve()
    if not project.is_dir():ap.error('Project volume not found')
    work=project/'derived/replication/mechanism_separation_v100_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=open(work/'run.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('This mechanism package is already running; no second writer started')
    code=verify();plan=read(ROOT/'FROZEN_PLAN.json');identity=dict(package_sha256=code,project=str(project),simulation_reps=a.simulation_reps)
    idpath=work/'RUN_IDENTITY.json'
    if idpath.exists() and read(idpath)!=identity:raise RuntimeError('Run settings changed; preserve original cache and review before mixing results')
    write(idpath,identity)
    public=work/'public_results';public.mkdir(exist_ok=True)
    start=time.monotonic();stop=threading.Event()
    def heartbeat():
        while not stop.wait(45):log(f'Mechanism analysis working; elapsed {(time.monotonic()-start)/60:.1f} min')
    threading.Thread(target=heartbeat,daemon=True).start()
    status=dict(status='RUNNING',version=VERSION,phase=a.phase,uses_production_inputs=True,mechanism_shares_released=False,
       behavioral_policy_estimate_released=False,private_cache=str(work),history_semantics=plan['sample']['history_semantics'])
    error=None
    try:
        records=sources(project);base=[str(work/'narrow'/f'{m}.parquet') for m in MONTHS]
        inputs=catalog(project)
        write(public/'INPUT_CATALOG.json',dict(pool=[dict(path=str(p),**r) for p,r in records],chronology=inputs,
           authentication='Pinned source size/row inventory; actual complete-file SHA256 retained in private authentication and exported checksum ledger'))
        if a.phase in ('all','prepare','support'):
            parallel(narrow_month,[(str(p),r,str(work)) for p,r in records],a.workers)
            needed_users(work,base,min(a.workers,8),int(a.memory_gb*1024))
            log('Building/reusing activity counts from existing chronology; no ratings or engine positions are replayed')
            memory=max(512,int(a.memory_gb*1024/a.workers))
            parallel(summary_task,[(r,str(work),memory) for r in inputs],a.workers)
            hw=min(a.workers,4);hm=max(768,int(a.memory_gb*1024/hw))
            parallel(features_task,[(s,m,inputs,str(work),hm) for s in SPEEDS for m in MONTHS],hw)
            for m in MONTHS:join_history(work,m)
        paths=[work/'analysis'/f'{m}.parquet' for m in MONTHS]
        if not all(p.exists() for p in paths):raise RuntimeError('Prepared months missing; run --phase prepare or --phase all')
        for p in paths:
            r=read(p.with_suffix('.json'));auth(p,work,r['output']['sha256'])
        if a.phase not in ('all','prepare','support'):
            for p,r in records:auth(p,work,r['sha256'],r['rows'],r['size_bytes'])
        if a.phase=='prepare':status['status']='PREPARATION_COMPLETE';return
        c=connect(work/'tmp/load',min(a.workers,8),int(a.memory_gb*1024))
        try:
            attrition=c.execute(f"SELECT month,state,count(*) AS screened_rows,sum(y) AS screened_grants,sum(regular::INTEGER) AS regular_rows,sum(tier2::INTEGER) AS tier2_rows FROM {scan(paths)} GROUP BY ALL ORDER BY month,state").fetchdf()
            table(attrition,public/'monthly_regularity_attrition.parquet')
        finally:c.close()
        def load_sample(label):
            tier,state=label.split('_');flag='regular' if tier=='regular' else 'tier2'
            cc=connect(work/'tmp/load',min(a.workers,8),int(a.memory_gb*1024))
            try:return cc.execute(f'SELECT * FROM {scan(paths)} WHERE {flag} IS TRUE AND state={q(state)} ORDER BY chooser,t,game_id').fetchdf()
            finally:cc.close()
        primary=load_sample('regular_equal')
        if primary.empty:raise RuntimeError('No primary regular rows; inspect activity outputs')
        nonfloor=primary.loc[primary.rd>=45.01,'ki']*2
        kcuts=np.quantile(nonfloor,[.25,.5,.75]) if len(nonfloor) else np.array([np.inf,np.inf,np.inf])
        write(public/'K_GROUP_CUTPOINTS.json',dict(cuts=kcuts,reference='Primary regular roughly-equal opportunities; same cuts in every sensitivity'))
        mechanical_curves(primary,kcuts,public)
        samples=[f'{tier}_{state}' for tier in ('regular','tier2') for state in ('equal','losing')]
        supports={}
        for label in samples:
            x=primary if label=='regular_equal' else load_sample(label)
            supports[label]=make_support(x,public,label)
            del x
        if a.phase=='support':status['status']='SUPPORT_COMPLETE';return
        fitted={}
        if a.phase in ('all','models','recovery','policy'):
            for label in samples:
                if a.phase in ('recovery','policy') and label!='regular_equal':continue
                x=primary if label=='regular_equal' else load_sample(label)
                changed=x.groupby('chooser').y.agg(['sum','count']);ns=int(((changed['sum']>0)&(changed['sum']<changed['count'])).sum())
                if ns<100 or x.y.sum()<100:
                    write(public/(label+'_MODEL_STATUS.json'),dict(status='INSUFFICIENT_SWITCHERS',switchers=ns));del x;continue
                stage=work/'analysis_stages'/(label+'.json');stage_key=digest(dict(inputs=[stamp(p) for p in paths],label=label,code=code))
                # Model-level receipts permit a restart in the middle of this stage.
                fit,scores=compare(x,work/'models',public,label)
                fitted[label]=fit
                if a.phase in ('all','models') and not stage.exists():
                    surface(x,kcuts,public,label)
                    ids=fit['strength'].get('switcher_ids',[])
                    if len(ids):surface(x[x.chooser.isin(ids)],kcuts,public,label+'_logit_sample')
                    index_scaling(x,public,label);prediction_profiles(x,fit,public,label)
                    write(stage,dict(key=stage_key))
                elif stage.exists() and read(stage)['key']!=stage_key:raise RuntimeError('Analysis stage identity differs')
                if a.phase in ('all','models') and label.startswith('regular'):
                    cue_report=public/('information_'+label);cue_report.mkdir(exist_ok=True)
                    cd,manifest=cue_data(project,work,x,cue_report,a.cue_manifest)
                    if cd is not None:run_cues(cd,manifest,work/label/digest(manifest)[:16],cue_report)
                write(public/(label+'_MODEL_STATUS.json'),dict(status='MODEL_COMPARISON_COMPLETE',selection=decision(scores),compatible_models=compatible_models(scores),
                    candidate_status={k:v['status'] for k,v in fit.items()},switchers=ns,
                    coefficient_interpretation='Payoff coefficients remain bundled where support gate fails. Chooser FE do not eliminate heterogeneous gap slopes.'))
                del x
        if a.phase in ('all','recovery') and 'regular_equal' in fitted:
            path,probabilities=prepare_recovery(primary,fitted['regular_equal'],work)
            tasks=[(path,p,model,r,str(work),plan['seed']) for model,p in probabilities for r in range(a.simulation_reps)]
            # Full-design matrices are memory intensive; at most two independent
            # refits run together. Preprocessing uses up to ten workers.
            rw=min(a.workers,2 if a.memory_gb>=8 else 1)
            rows=parallel(recovery_task,tasks,rw);summarize_recovery(rows,public,a.simulation_reps)
        if a.phase in ('all','cost'):
            for label in samples:
                x=primary if label=='regular_equal' else load_sample(label)
                estimate_cost(x,supports[label],public,label);del x
        if a.phase in ('all','policy') and 'regular_equal' in fitted:
            run_policy(primary,fitted['regular_equal'],project,work,public,a.policy_manifest)
        figures(public);status['status']='REQUESTED_STAGES_COMPLETE'
    except Exception as exc:
        error=exc;status.update(status='PARTIAL_RESULTS_REVIEW_REQUIRED',error=str(exc),traceback=traceback.format_exc())
        log('STOPPED: '+str(exc))
    finally:
        stop.set();status['elapsed_seconds']=time.monotonic()-start
        status['policy_status']=read(public/'POLICY_STATUS.json') if (public/'POLICY_STATUS.json').exists() else {'status':'NOT_RUN'}
        write(public/'SUMMARY.json',status);shutil.copy2(ROOT/'FROZEN_PLAN.json',public/'FROZEN_PLAN.json')
        write(public/'ENVIRONMENT.json',dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__,pandas=pd.__version__,pyarrow=pa.__version__,duckdb=duckdb.__version__,package_sha256=code))
        hashes=[]
        for p in sorted((work/'authentication').glob('*.json')):
            r=read(p);hashes.append(dict(path=r['fingerprint']['path'],size_bytes=r['fingerprint']['size'],sha256=r['sha256'],pinned_sha256=r['expected_sha256']))
        table(hashes,public/'input_checksums.parquet')
        text(public/'READ_ME_FIRST.md',report_note(status))
        stamp_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        report=project/'output/mechanism_separation_v100'/('MECHANISM_RESULT_'+stamp_id)
        shutil.copytree(public,report);zip_report(report,a.desktop);lock.close()
    if error:raise SystemExit(1)

def report_note(s):
    return f'''# Mechanism separation results\n\nStatus: **{s['status']}**. Requested phase: {s['phase']}.\n\nRead the support tables before coefficients. `*_cost_or_bundle` reports either conditional premium slopes or one opponent-RD bundle coefficient. It never treats the bundle as an own-cost bound.\n\n`*_surface` and `*_L_S_G` are descriptive percentage-point profiles; `*_index_scaling` reports supported conditional index contrasts. Full-sample and logit-sample LPMs are separate. `*_model_coefficients`, `*_heldout_scores`, and `*_heldout_comparisons` compare specified models, with an explicit training-only baseline for probability predictions. No model is automatically called deference.\n\n`recovery_confusion` includes indistinguishable outcomes and failures. It is a specified-model simulation, not a proof of causal identification. No decomposition shares are released.\n\nInformation-test subfolders report historical cue availability and, where eligible, same-sample incremental prediction. Current Patron/title snapshots do not establish historical visibility.\n\n`color_model_predictions`, `color_pairwise_power`, and `POLICY_STATUS` distinguish pre-policy planning transport from the actual frozen-cohort test. No post-policy behavioral coefficient is computed. Visibility and prediction-parameter uncertainty remain explicit limitations; no automatic GO or price-preference bound follows.\n\nActivity and experience count prior recorded rated-game **starts**, not completed games or account age. The original chronology is reused; no API acquisition, identity recovery, rating replay, or Stockfish run is launched.\n\nPrivate account/game rows stay in the external-drive cache. This archive contains aggregate tables, methods, and checksums.\n'''

if __name__=='__main__':main()
