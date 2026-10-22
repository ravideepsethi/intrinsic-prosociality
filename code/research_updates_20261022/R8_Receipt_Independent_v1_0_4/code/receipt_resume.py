#!/usr/bin/env python3
"""Match R7's exact A1 numerical path, keep strict checks, reuse other R8 reports."""
from __future__ import annotations
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[name]='1'
import sys,argparse,hashlib,json,time,fcntl,shutil,zipfile,traceback
from pathlib import Path

PACKAGE=Path(__file__).resolve().parents[1]
BASE_ZIP_SHA='cd68036045754eb35278c3f707207b379ffce3bd98ec09804c24203b5609d1ed'
BASE_MANIFEST_SHA='78b681be0dae396983519aa9be72b26cf9d619ef75261911a3084716ddcdbff2'
VERSION='1.0.1'

def initialize(base):
    global m,u,np
    sys.path.insert(0,str(Path(base)/'code'))
    import r8_receipt as m
    import r8_util as u
    import numpy as np
    import run_r8
    u.require(run_r8.verify_package()==BASE_MANIFEST_SHA,'The original R8 v1.0.0 package differs')
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        want,name=line.split('  ',1);p=PACKAGE/name
        u.require(p.resolve().is_relative_to(PACKAGE.resolve()) and u.sha(p)==want,'Receipt-resume package SHA changed: '+name)

def archive_rows(archived,sample,outcome,rows,rowhash):
    selected=[v for v in archived if v.get('sample')==sample and v.get('control_level')=='X0'
        and v.get('analysis')=='A1' and v.get('dependent')==outcome
        and v.get('instrument')=='pooled' and v.get('recipient_FE') is False]
    u.require(len(selected)==15 and len({v['trait'] for v in selected})==15,'Ambiguous R7 A1 coefficient block')
    for v in selected:
        u.require(v['n']==rows and v['row_set_sha256']==rowhash,'R7 A1 row count or ordered row digest differs')
        u.require(v['controls']==m.r.NH and v['units']=='percentage points per trait SD','R7 A1 control/units contract differs')
    byname={v['trait']:v for v in selected}
    u.require(set(byname)==set(m.r.T15),'R7 A1 trait identities differ')
    return byname

def matched_r_squared(d,sample,archived,report):
    """Use R7 A1 column order, score column, rank rule and per-outcome pseudoinverse."""
    x,names,traits,groups=m.r.feature_design(d,'X0')
    inh=[i for i,name in enumerate(names) if name not in m.r.X0[7:]]
    nh=x[:,inh]
    t30=np.column_stack([traits[k] for k in m.r.T30])
    t=np.column_stack([t30]+[traits[k] for k in m.r.T15 if k not in m.r.T30])
    del t30
    # Identical to the frozen R7 producer. Score is included in its joint FE projection.
    outcomes=['received','y'] if sample=='S0' else ['analysis_entry_90','recipient_disconnect_main','y']
    y=np.column_stack([np.asarray(d[k],float) for k in outcomes]);z=np.asarray(d['adjusted_7d'],float)
    u.require(np.isfinite(y).all() and np.isfinite(z).all(),'R7 full-frame outcomes/score have missing values; no rows dropped or imputed')
    rowhash=m.r.design.row_digest(d['row_id'])
    targets={k:archive_rows(archived,sample,k,len(y),rowhash) for k in outcomes}
    old={};audit=[];details=dict(sample=sample,n=len(y),row_set_sha256=rowhash,controls=m.r.NH,
        outcomes_in_projection_order=outcomes,score_column_included=True,
        coefficient_tolerance=dict(rtol=3e-6,atol=2e-9),acceptance_tolerance_relaxed=False)
    # Reproduce the original R8 checker on S0 so the failed comparison can be diagnosed.
    if sample=='S0':
        with u.heartbeat('Receipt audit: original R8 numerical path'):
            old_outcomes=['y','received'];yy=np.column_stack([d[k] for k in old_outcomes]).astype(float)
            oldt=np.column_stack([traits[k] for k in m.r.T15])
            a,_=m.rm.project(x[:,:7],[oldt[:,j] for j in range(15)]+[yy[:,j] for j in range(2)],groups)
            gram=a[:,:15].T@a[:,:15]
            b=np.linalg.solve(gram,a[:,:15].T@a[:,15:])
            old={k:b[:,j].copy() for j,k in enumerate(old_outcomes)}
            details['old_R8_Gram_condition_number']=float(np.linalg.cond(gram))
            del a,gram,b,oldt,yy
    u.log(f'Receipt resume: exact R7 A1 fit check on {sample}, {len(y):,} rows')
    with u.heartbeat('Receipt resume: '+sample+' exact R7 A1 projection'):
        raw=[t[:,j] for j in range(15)]+[y[:,j] for j in range(len(outcomes))]+[z]
        a,control_rank=m.rm.project(nh,raw,groups)
        T=a[:,:15];G=T.T@T
        tolerance=max(float(np.linalg.norm(G,2)),1)*1e-12
        rank=int(np.linalg.matrix_rank(G,tol=tolerance))
        details.update(trait_rank=rank,control_rank=control_rank,Gram_condition_number=float(np.linalg.cond(G)),
            point_estimator='R7: pinv(T.T @ T, rcond=1e-12) @ (T.T @ outcome), separately for each outcome',
            FE_design='same R7 controls, T15/outcome/score column order and owned-buffer FE projection')
        u.require(rank==15,'Frozen R7 T15 rank condition failed; no ridge or dropped traits')
        bread=np.linalg.pinv(G,rcond=1e-12);rows=[]
        for j,outcome in enumerate(outcomes):
            Y=a[:,15+j];b=bread@(T.T@Y);e=Y-T@b
            for i,name in enumerate(m.r.T15):
                expected=float(targets[outcome][name]['coefficient']);observed=float(b[i])
                passed=bool(np.isclose(observed,expected,rtol=3e-6,atol=2e-9))
                oldvalue=float(old[outcome][i]) if outcome in old else None
                audit.append(dict(sample=sample,outcome=outcome,trait=name,expected_coefficient=expected,
                    matched_R7_coefficient=observed,difference=observed-expected,
                    expected_pp=100*expected,matched_R7_pp=100*observed,difference_pp=100*(observed-expected),
                    original_R8_coefficient=oldvalue,original_R8_difference=None if oldvalue is None else oldvalue-expected,
                    original_R8_passed=None if oldvalue is None else bool(np.isclose(oldvalue,expected,rtol=3e-6,atol=2e-9)),
                    passed=passed))
            rss=float(e@e);nhss=float(Y@Y);center=y[:,j]-y[:,j].mean();total=float(center@center)
            rows.append(dict(sample=sample,n=len(y),outcome=outcome,trait_incremental_partial_R2=1-rss/nhss,
                FE_plus_NH_plus_traits_R2=1-rss/total,trait_count=15,all_trait_coefficients_reproduced=False,
                row_set_sha256=rowhash,prediction='in_sample',
                note='Full R2 includes fixed effects and NH; partial R2 measures additional trait fit. Neither is out-of-sample calibration. Exact frozen R7 numerical path.'))
    allpassed=all(v['passed'] for v in audit)
    details.update(all_coefficients_reproduced=allpassed,failed_coefficients=sum(not v['passed'] for v in audit))
    if report is not None:
        u.table(report,'receipt_reproduction_'+sample,audit);u.save(Path(report)/('receipt_fit_diagnostics_'+sample+'.json'),details)
    for v in audit:
        if not v['passed']:
            u.log(f"R7_A1_MISMATCH {sample} {v['outcome']} {v['trait']}: expected {v['expected_coefficient']:.17g}, got {v['matched_R7_coefficient']:.17g}, delta {v['difference']:.17g}")
    u.require(allpassed,'Exact R7 A1 coefficients still differ; see receipt_reproduction_'+sample+'.csv. The strict reproduction gate was retained.')
    for row in rows:row['all_trait_coefficients_reproduced']=True
    u.log(f'Receipt resume: {sample} all {len(audit)} archived trait coefficients reproduced')
    return rows

def prove_model_inputs(r7,paths,report):
    """Bind the actual completed R7 model job's input bytes, beyond its source-stage receipt."""
    rows=[]
    for sample in ('S0','F50'):
        folder=r7/'models'/(sample+'_X0_pooled_pooled')
        m.r.env_common.checked_stage_files(folder,u.R7_CONF,['result.json','dependencies_PRIVATE.json'])
        deps=u.load(folder/'dependencies_PRIVATE.json')
        u.require(len(deps)==1,'R7 model input receipt is ambiguous')
        actual=u.sha(paths[sample]);expected=deps[0]['sha256']
        rows.append(dict(sample=sample,input_SHA256=actual,R7_model_input_SHA256=expected,passed=actual==expected))
    u.table(report,'R7_model_input_byte_checks',rows)
    u.require(all(r['passed'] for r in rows),'Prepared input bytes differ from those used in the completed R7 model; no refit or tolerance bypass')

def runtime_config():
    import scipy
    return dict(version='1.0.0',package_manifest_SHA256=BASE_MANIFEST_SHA,R7_config=u.R7_CONF,
        numpy=u.np.__version__,pandas=u.pd.__version__,pyarrow=u.pa.__version__,duckdb=u.duckdb.__version__,scipy=scipy.__version__)

def guard_original_run(project):
    basekey=u.digest(runtime_config());old=project/'derived/replication/r8_current_data_v100_PRIVATE'/basekey[:12]
    lock=None
    if (old/'RUN.lock').exists():
        lock=(old/'RUN.lock').open('r')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close();raise RuntimeError('The original R8 run is still active. Let the clock module finish, then rerun this receipt-resume command.')
    return old,basekey,lock

def export(run,desktop,key,old,basekey,state,error=None):
    public=run/'PUBLIC';public.mkdir(parents=True,exist_ok=True)
    report=run/'receipt/report';dest=public/'receipt'
    if dest.exists():shutil.rmtree(dest)
    dest.mkdir(parents=True,exist_ok=True)
    if state=='COMPLETE':shutil.copytree(report,dest,dirs_exist_ok=True)
    else:
        # Diagnostic allowlist. Failed fits never become reported estimates.
        for p in report.glob('*'):
            if p.is_file() and (p.name.startswith('receipt_reproduction_') or p.name.startswith('receipt_fit_diagnostics_') or p.name.startswith('R7_model_input_byte_checks.')):
                shutil.copy2(p,dest/p.name)
    states={'receipt':dict(state=state,error=error)}
    previous=u.load(old/'STATE.json').get('modules',{}) if (old/'STATE.json').exists() else {}
    for name in ('patron','clocks'):
        target=public/name
        if target.exists():shutil.rmtree(target)
        states[name]=dict(state='NOT_REUSED')
        if previous.get(name,{}).get('state')=='COMPLETE':
            try:
                u.require(u.verify_cached(old/name,u.digest([basekey,name])),'Original '+name+' completion is unavailable')
                shutil.copytree(old/name/'report',target)
                baseline=old/name/('baseline_gate' if name=='clocks' else 'baseline')
                if baseline.exists():
                    for p in baseline.iterdir():
                        if p.is_file() and p.name!='_DONE.json':
                            out=target/'baseline'/p.name;out.parent.mkdir(exist_ok=True);shutil.copy2(p,out)
                states[name]=dict(state='COMPLETE',reused=True,original_config_sha256=basekey)
            except Exception as e:
                if target.exists():shutil.rmtree(target)
                states[name]=dict(state='NOT_REUSED',reason=str(e))
    import run_r8
    status='R8_CURRENT_DATA_COMPLETE_WITH_RECEIPT_RESUME' if all(v['state']=='COMPLETE' for v in states.values()) else 'R8_RECEIPT_RESUME_PARTIAL'
    u.save(public/'SUMMARY.json',dict(status=status,version=VERSION,configuration_sha256=key,module_states=states,
        open_work=run_r8.OPEN_WORK,root_cause_confirmed=False,reproduction_tolerance_relaxed=False,
        engine_searches=0,network_requests=0))
    u.save(public/'R8_LEDGER.json',dict(item1=states['patron'],item2=states['receipt'],item4=states['receipt'],item3_2=states['clocks'],remaining=run_r8.OPEN_WORK))
    u.save(public/'PATCH_VALIDATION.json',u.load(PACKAGE/'VALIDATION.json'))
    (public/'READ_ME.md').write_text('Receipt resume uses the exact R7 A1 numerical projection and pseudoinverse. All original coefficient tolerances remain. The actual Mac root cause is not established by the initial log alone.\n\nOnly successfully reproduced receipt estimates are exported. Completed Patron and clock reports are copied only after their original configuration, hashes and input signatures verify. They are not rerun.\n\nWinning-chances, per-ply replay and paper-wide author invariance remain open.\n')
    u.save(public/'REPORT_MANIFEST.json',[dict(path=str(p.relative_to(public)),bytes=p.stat().st_size,sha256=u.sha(p)) for p in sorted(public.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json'])
    name='R8_RECEIPT_RESUME_REPORT_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+key[:12]+'.zip'
    out=desktop/name
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(public.rglob('*')):
            if p.is_file():z.write(p,'R8_RECEIPT_RESUME_REPORT/'+str(p.relative_to(public)))
    with zipfile.ZipFile(out) as z:u.require(z.testzip() is None,'Receipt-resume report CRC failed')
    (desktop/(name+'.sha256')).write_text(u.sha(out)+'  '+name+'\n')
    u.log('RESULT_ZIP '+str(out));u.log('RESULT_SHA256 '+str(desktop/(name+'.sha256')))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-package',type=Path,required=True)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop');p.add_argument('--r7-root',type=Path)
    p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--check-only',action='store_true');a=p.parse_args()
    initialize(a.base_package);u.no_network();u.require(10<=a.memory_gb<=11,'Use a 10–11 GiB working-memory budget')
    old,basekey,oldlock=guard_original_run(a.project_root)
    config=dict(base=runtime_config(),patch_manifest_SHA256=u.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),version=VERSION)
    key=u.digest(config);run=a.project_root/'derived/replication/r8_receipt_resume_v101_PRIVATE'/key[:12]
    run.mkdir(parents=True,exist_ok=True);a.desktop.mkdir(parents=True,exist_ok=True)
    lock=(run/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This receipt resume is already running')
    u.save(run/'CONFIG_PRIVATE.json',dict(config,arguments=vars(a),key=key))
    work=run/'receipt';report=work/'report';report.mkdir(parents=True,exist_ok=True)
    k=u.digest([key,'receipt']);state='BLOCKED';error=None
    try:
        r7,paths,binding=u.bind_r7(a.project_root,a.r7_root)
        prove_model_inputs(r7,paths,report)
        m.r_squared=matched_r_squared
        if a.check_only:
            d=m.r.load_fit_columns(paths['S0']);matched_r_squared(d,'S0',u.load(r7/'report/A_joint_balance.json'),report)
            state='DIAGNOSTIC_PASSED_NOT_ESTIMATED'
        elif u.verify_cached(work,k):state='COMPLETE';u.log('Receipt completion verified; existing fit reused')
        else:
            u.log('Receipt-only resume; matched R7 A1 numerics; original tolerances retained. Estimated 1–3 hours, unbenchmarked.')
            m.run(a,work,k);u.require(u.verify_cached(work,k),'Receipt lacks valid completion');state='COMPLETE'
    except Exception as e:
        error=str(e);u.log('RECEIPT_BLOCKED '+error);traceback.print_exc()
    finally:
        u.save(run/'STATE.json',dict(receipt=dict(state=state,error=error),key=key))
        export(run,a.desktop,key,old,basekey,state,error)
        if oldlock:oldlock.close()
    return 0 if state in ('COMPLETE','DIAGNOSTIC_PASSED_NOT_ESTIMATED') else 2

if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('Interrupted; receipt checkpoints retained.',flush=True);raise SystemExit(130)
