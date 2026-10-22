#!/usr/bin/env python3
"""Independent A1 audit and checkpointed R8 prior-experience IV analyses."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS'):os.environ[name]='1'
import sys,argparse,time,json,math,gc,fcntl,shutil,zipfile,traceback
from pathlib import Path
import receipt_resume as base
import independent_ols as independent
import history_scope
from scipy import linalg
PACKAGE=Path(__file__).resolve().parents[1]
VERSION='1.0.4'
V103_MANIFEST_SHA='bfe29103dba03479e3cd53ebd042b262475a0403f8586902d262458327ccc723'

def close(got,want,rtol=3e-6):
    return got is None and want is None or got is not None and want is not None and bool(base.np.isclose(got,want,rtol=rtol,atol=2e-9))

def audit_a1(d,archived,current,report):
    u=base.u;np=base.np;m=base.m
    x,names,traits,groups=m.r.feature_design(d,'X0')
    t=[traits[k] for k in m.r.T15];outs=['received','y','score'];raw=t+[np.asarray(d[k],float) for k in ('received','y','adjusted_7d')]
    rowhash=m.r.design.row_digest(d['row_id'])
    for out in ('received','y'):base.archive_rows(archived,'S0',out,len(d['row_id']),rowhash)
    with u.heartbeat('Independent A1 cell elimination and Schur complement'):
        residual,diag=independent.project(x[:,:7],raw,groups)
    del x,traits,raw,t;gc.collect()
    T=residual[:,:15];Y=residual[:,15:];G=independent.cross(T,T);H=independent.cross(T,Y)
    u.require(np.linalg.matrix_rank(G,tol=max(float(np.linalg.norm(G,2)),1.)*1e-12)==15,'Independent T15 rank differs; no traits removed')
    with u.heartbeat('Independent A1 pivoted QR'):
        bqr,_,rank,_=linalg.lstsq(T.copy(order='F'),Y.copy(order='F'),cond=1e-12,lapack_driver='gelsy',overwrite_a=True,check_finite=False)
    u.require(rank==15,'QR T15 rank differs; no traits removed')
    bsolve=np.linalg.solve(G,H);bread=np.linalg.inv(G);native=float(np.sqrt(float(Y[:,2]@Y[:,2])/len(Y)))
    current={(r['outcome'],r['trait'],r['field']):r['observed'] for r in current}
    expected={(r['dependent'],r['trait']):r for r in archived if r.get('sample')=='S0' and r.get('analysis')=='A1'
        and r.get('control_level')=='X0' and r.get('instrument')=='pooled' and r.get('recipient_FE') is False}
    rows=[];fit=[];covariances=[]
    for j,out in enumerate(outs):
        scale=1/native if out=='score' else 1.;b=bqr[:,j]*scale;e=(Y[:,j]-T@bqr[:,j])*scale
        with u.heartbeat('Independent A1 covariance '+out):V=bread@m.rm.covariance(d)(T*e[:,None])@bread
        covariances.append(V)
        for i,trait in enumerate(m.r.T15):
            se=math.sqrt(V[i,i]) if V[i,i]>0 and np.isfinite(V[i,i]) else None
            want=expected[(out,trait)]
            rows.append(dict(sample='S0',outcome=out,trait=trait,independent_QR_coefficient=float(b[i]),
                independent_normal_equation_coefficient=float(bsolve[i,j]*scale),independent_SE=se,
                current_R7_coefficient=current[(out,trait,'coefficient')],current_R7_SE=current.get((out,trait,'standard_error')),
                archived_R7_coefficient=want['coefficient'],archived_R7_SE=want.get('standard_error'),
                QR_matches_normal_equations=close(float(b[i]),float(bsolve[i,j]*scale)),
                independent_matches_current_coefficient=close(float(b[i]),current[(out,trait,'coefficient')]),
                independent_matches_current_SE=close(se,current.get((out,trait,'standard_error'))),
                archived_coefficient_reproduced=close(float(b[i]),want['coefficient']),
                archived_SE_reproduced=close(se,want.get('standard_error')),
                rtol=3e-6,atol=2e-9,status='INDEPENDENT_NUMERICAL_AUDIT_NOT_A_NEW_PAPER_RESULT'))
        if out!='score':
            rss=float(e@e);base_ss=float(Y[:,j]@Y[:,j]);y=np.asarray(d[out],float);center=y-y.mean();total=float(center@center)
            oldb=np.array([expected[(out,k)]['coefficient'] for k in m.r.T15])
            normal=float(np.max(np.abs(G@oldb-H[:,j])))
            fit.append(dict(sample='S0',outcome=out,n=len(y),row_set_sha256=rowhash,
                candidate_partial_R2=1-rss/base_ss,candidate_full_R2=1-rss/total,
                archived_beta_normal_equation_max_error=normal,
                archived_beta_relative_normal_equation_error=normal/max(1.,float(np.max(np.abs(H[:,j])))),
                status='DIAGNOSTIC_CANDIDATE_R2_A1_ARCHIVE_CHECK_REMAINS_EXPLICIT'))
    calibration=[];moment=independent.cross(residual,residual);extra=[m.r.T15.index(k) for k in m.r.X0[7:]]
    full=moment-moment[:,extra]@np.linalg.solve(moment[np.ix_(extra,extra)],moment[extra,:])
    for controls,S in [('NH',moment),('full_model',full)]:
        for j,out in enumerate(('received','y')):
            point=100*m.r.SD['pooled']*float(S[-1,:15]@bqr[:,j])/float(S[-1,-1])
            calibration.append(dict(sample='S0',outcome=out,calibration_controls=controls,
                method='in_sample',independent_point_pp=point,status='POINT_CHECK_ONLY_NO_A3_SE_OR_CROSSFIT_CLAIM'))
    validated=all(r['QR_matches_normal_equations'] and r['independent_matches_current_coefficient'] and r['independent_matches_current_SE'] for r in rows)
    old_passed=all(r['archived_coefficient_reproduced'] and r['archived_SE_reproduced'] for r in rows)
    diag.update(independent_matches_current_R7=validated,archived_A1_reproduced=old_passed,
        finding='CURRENT_R7_CONFIRMED_ARCHIVED_A1_DIFFERS' if validated and not old_passed else 'REVIEW_DIAGNOSTICS',
        current_R7_reference='verified original-producer Mac trace with the same pinned input bytes',
        rows=len(d['row_id']),row_set_sha256=rowhash,trait_rank=rank,Gram_condition_number=float(np.linalg.cond(G)),
        historical_root_cause_identified=False,tolerance_relaxed=False,no_headline_promotion=True)
    u.table(report,'A1_independent_audit',rows);u.table(report,'A1_candidate_fit_statistics',fit)
    u.table(report,'A3_independent_point_checks',calibration);u.save(Path(report)/'A1_independent_diagnostics.json',diag)
    np.savez_compressed(Path(report)/'A1_aggregate_normal_equations.npz',Gram=G,outcome_moments=H,covariances=np.array(covariances))
    u.require(validated,'Independent A1 QR/normal equations/current R7 comparison failed; experience not started')
    return diag

def core_gate(d,r7,report):
    u=base.u;m=base.m
    got,_,_=m.group_iv(d,'full_S0_core_reproduction')
    source=u.load(r7/'report/B_estimates.json')
    rows=[]
    for estimator,outcome,fields in [('first_stage','received',[('first_stage_pp','coefficient_pp'),('first_stage_SE_pp','standard_error_pp')]),
        ('reduced_form','y',[('reduced_form_pp','coefficient_pp'),('reduced_form_SE_pp','standard_error_pp')]),
        ('2SLS','y',[('iv_pp','iv_coefficient_pp'),('iv_SE_pp','iv_standard_error_pp')])]:
        want=[r for r in source if r.get('sample')=='S0' and r.get('control_level')=='X0' and r.get('instrument')=='pooled'
              and r.get('recipient_FE') is False and r.get('estimator')==estimator and r.get('outcome')==outcome]
        u.require(len(want)==1 and want[0]['n']==got['n'] and want[0]['row_set_sha256']==got['row_set_sha256'],'Core S0 archive contract differs')
        for observed,expected in fields:rows.append(dict(estimator=estimator,field=expected,observed=got[observed],expected=want[0][expected],passed=close(got[observed],want[0][expected],2e-7)))
    u.table(report,'core_IV_reproduction',rows);u.require(all(r['passed'] for r in rows),'Core S0 IV point/SE reproduction failed')
    return got

def calibration_point_archive_check(r7,report):
    u=base.u;archived=u.load(r7/'report/A_predicted_outcome.json');rows=u.load(report/'A3_independent_point_checks.json')
    for row in rows:
        match=[r for r in archived if r.get('sample')=='S0' and r.get('control_level')=='X0' and r.get('instrument')=='pooled'
            and r.get('recipient_FE') is False and r.get('method')=='in_sample' and r.get('predicted_outcome')==row['outcome']
            and r.get('calibration_controls')==row['calibration_controls']]
        u.require(len(match)==1,'Ambiguous archived A3 point-check row')
        row.update(archived_point_pp=match[0]['coefficient_pp'],archived_point_reproduced=close(row['independent_point_pp'],match[0]['coefficient_pp'],2e-7),
            archived_SE_or_crossfit_reproduction_claimed=False)
    u.table(report,'A3_independent_point_checks',rows)

def reuse_v103_audit(project,audit,auditkey):
    """Verify the earlier independent audit and adopt its aggregate outputs."""
    u=base.u
    config=dict(base=base.runtime_config(),manifest_SHA256=V103_MANIFEST_SHA,version='1.0.3')
    oldkey=u.digest(config)
    prior=Path(project)/'derived/replication/r8_receipt_independent_v103_PRIVATE'/oldkey[:12]
    source=prior/'audit'
    if not (source/'_DONE.json').exists():return False
    oldlock=None
    try:
        if (prior/'RUN.lock').exists():
            oldlock=(prior/'RUN.lock').open('r')
            try:fcntl.flock(oldlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('The v1.0.3 independent run is still active')
        stored=u.load(prior/'CONFIG_PRIVATE.json')
        u.require(all(stored.get(k)==v for k,v in config.items()) and stored.get('key')==oldkey,
                  'Prior independent-audit configuration changed')
        u.require(u.verify_cached(source,u.digest([oldkey,'audit'])),'Earlier A1 audit is incomplete')
        diag=u.load(source/'report/A1_independent_diagnostics.json')
        u.require(diag.get('independent_matches_current_R7') is True and diag.get('tolerance_relaxed') is False,
                  'Earlier independent A1 audit did not pass its current-fit check')
        u.require(diag.get('rows')==2682329 and diag.get('row_set_sha256')==
                  '47cf7dbfcadde463159bd8b6c3abeec465317e2e7f53d58e63eb4b5a899366ba',
                  'Earlier A1 audit uses a different exposure cohort')
        u.require(all(r['passed'] for r in u.load(source/'report/core_IV_reproduction.json')),
                  'Earlier core S0 IV gate was not passed')
        audit.mkdir(parents=True,exist_ok=True);dest=audit/'report';dest.mkdir(exist_ok=True)
        for f in (source/'report').iterdir():
            if f.is_file():shutil.copy2(f,dest/f.name)
        u.save(dest/'AUDIT_REUSE.json',dict(reused=True,source_version='1.0.3',
            source_configuration_sha256=oldkey,source_receipt_sha256=u.sha(source/'_DONE.json'),
            source_outputs_and_dependencies_verified=True,source_modified=False))
        dependencies=[r['path'] for r in u.load(source/'_DONE.json').get('inputs',[])]+[source/'_DONE.json']
        u.certify(audit,auditkey,dependencies)
        u.log('A1_AUDIT_REUSED verified v1.0.3 output; no A1 or core-IV refit')
        return True
    finally:
        if oldlock:oldlock.close()

def experience(a,paths,binding,work,key,report):
    u=base.u;m=base.m
    split,coverage=history_scope.prior_frame(paths,binding,a.project_root,work,key,a.memory_gb,report)
    u.save(report/'prior_experience_coverage.json',coverage)
    d=m.r.load_fit_columns(paths['S0']);s=m.r.arrays(m.r.io.read(split))
    u.require(base.np.array_equal(d['row_id'],s['row_id']),'Experience attachment changed frozen row order')
    rows=[];contrasts=[];pooled=[]
    for label,col in [('full_recorded_history','faced_recorded'),('past90_days','faced90')]:
        one,delta=m.split_fits(d,s[col],label,work/'fits',key);rows+=one;contrasts.append(delta)
        checkpoint=work/('pooled_'+label);k=u.digest([key,'pooled',label])
        if u.verify_cached(checkpoint,k):result=u.load(checkpoint/'result.json')
        else:
            checkpoint.mkdir(parents=True,exist_ok=True);result=m.pooled_interaction(d,s[col],label)
            u.save(checkpoint/'result.json',result);u.certify(checkpoint,k,[paths['S0'],split])
        pooled.append(result);u.log(('75%: full-recorded-history experience fit complete' if label=='full_recorded_history' else 'Experience split completed: '+label))
        u.table(report,'experience_IV',rows);u.table(report,'experience_contrasts',contrasts);u.table(report,'pooled_interaction_IV',pooled)
    for val,label in [(0,'no_choice90'),(1,'choices90_never_granted'),(2,'granted90')]:
        checkpoint=work/('secondary90_'+str(val));k=u.digest([key,'secondary90',val])
        if u.verify_cached(checkpoint,k):one=u.load(checkpoint/'result.json')
        else:
            checkpoint.mkdir(parents=True,exist_ok=True);one,_,_=m.group_iv(m.r.subset(d,s['group90']==val),label)
            u.save(checkpoint/'result.json',one);u.certify(checkpoint,k,[paths['S0'],split])
        rows.append(dict(one,split='past90_days_three_groups'));u.table(report,'experience_IV',rows)
    definitions={
        'full_recorded_history':'Any prior completed chooser-side competitive grant or claim before exposure anchor_ms',
        'past90_days':'Frozen Table S3.7 fair_90>0; all competitive opportunities in [game start-97d, game start-7d), including nonarm resolutions',
        'past90_days_three_groups':'Frozen fair_90/kind_90 groups; grants are counted by kind_90; labels do not imply every fair opportunity was grant/claim eligible'}
    for row in rows:row['history_definition']=definitions[row['split']]
    u.table(report,'experience_IV',rows)
    u.save(report/'experience_definitions.json',dict(definitions,nesting_assumed=False,
        scope_difference_rows=coverage['recent_opportunity_without_prior_grant_or_claim_rows'],
        exact_recent_counts_reproduced=True,all_discordant_rows_explained=True))
    u.save(report/'EXPERIENCE_COMPLETION.json',dict(status='R8_ITEM4_COMPLETE',author_clean=True,network_requests=0,stockfish_searches=0,
        row_set_unchanged=True,score_reestimated=False,prior_history_scope=coverage['source_window'],primary_history_replaced_by90d=False,
        history_scopes_validated=True,frozen_90day_split_preserved=True,
        causal_identification_certified=False,A1_archive_reproduction_not_claimed=True))
    return split

def export(run,desktop,key,old,basekey,a1_state,exp_state,error):
    u=base.u;public=run/'PUBLIC'
    if public.exists():shutil.rmtree(public)
    public.mkdir();source=run/'report';target=public/'receipt';target.mkdir()
    for p in source.iterdir():
        if p.is_file() and (exp_state=='COMPLETE' or not p.name.startswith(('experience_','pooled_interaction_','EXPERIENCE_COMPLETION'))):shutil.copy2(p,target/p.name)
    previous=u.load(old/'STATE.json').get('modules',{}) if (old/'STATE.json').exists() else {};states={}
    for name in ('patron','clocks'):
        states[name]=dict(state='NOT_REUSED');dest=public/name
        if previous.get(name,{}).get('state')=='COMPLETE':
            try:
                u.log('Report export: verifying completed '+name+' checkpoints')
                with u.heartbeat('Report export: verify and copy completed '+name+' reports'):
                    u.require(u.verify_cached(old/name,u.digest([basekey,name])),'Original completed module unavailable')
                    shutil.copytree(old/name/'report',dest)
                    baseline=old/name/('baseline_gate' if name=='clocks' else 'baseline')
                    if baseline.exists():
                        for p in baseline.iterdir():
                            if p.is_file() and p.name!='_DONE.json':out=dest/'baseline'/p.name;out.parent.mkdir(exist_ok=True);shutil.copy2(p,out)
                states[name]=dict(state='COMPLETE',reused=True,original_config_sha256=basekey)
            except Exception as e:
                if dest.exists():shutil.rmtree(dest)
                states[name]=dict(state='NOT_REUSED',reason=str(e))
    states['A1']=dict(state=a1_state);states['experience_IV']=dict(state=exp_state,error=error)
    import run_r8
    summary=dict(status='R8_PARTIAL_A1_REMAINS_OPEN',version=VERSION,module_states=states,configuration_sha256=key,
        item2='BLOCKED_ARCHIVED_A1_NOT_REPRODUCED',item4=exp_state,open_work=run_r8.OPEN_WORK,
        historical_root_cause_identified=False,coefficient_tolerance_relaxed=False,no_headline_promotion=True,network_requests=0,stockfish_searches=0)
    u.save(public/'SUMMARY.json',summary);u.save(public/'VALIDATION.json',u.load(PACKAGE/'VALIDATION.json'))
    u.save(public/'R8_LEDGER.json',dict(item1=states['patron'],item2=summary['item2'],item3_2=states['clocks'],item4=states['experience_IV'],remaining=run_r8.OPEN_WORK))
    (public/'READ_ME.md').write_text('Item 4 is complete only when experience_IV.state is COMPLETE. The archived R7 A1 reproduction failure remains explicit. Independent A1 coefficients and candidate R2 are numerical diagnostics; no historical A1 replacement or manuscript promotion is certified. All sources and scores are frozen. Never faced means no prior qualifying choice in the recorded source window, not a lifetime claim.\n')
    u.save(public/'REPORT_MANIFEST.json',[dict(path=str(p.relative_to(public)),bytes=p.stat().st_size,sha256=u.sha(p)) for p in sorted(public.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json'])
    out=desktop/('R8_RECEIPT_INDEPENDENT_REPORT_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+key[:12]+'.zip')
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(public.rglob('*')):
            if p.is_file():z.write(p,'R8_RECEIPT_INDEPENDENT_REPORT/'+str(p.relative_to(public)))
    with zipfile.ZipFile(out) as z:u.require(z.testzip() is None,'Report CRC failed')
    out.with_suffix('.zip.sha256').write_text(u.sha(out)+'  '+out.name+'\n');u.log('RESULT_ZIP '+str(out));u.log('RESULT_SHA256 '+str(out.with_suffix('.zip.sha256')))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-package',type=Path,required=True)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'));p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--r7-root',type=Path);p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--audit-only',action='store_true');a=p.parse_args()
    base.initialize(a.base_package);u=base.u;u.no_network();u.require(10<=a.memory_gb<=11,'Use a 10–11 GiB budget')
    old,basekey,oldlock=base.guard_original_run(a.project_root);config=dict(base=base.runtime_config(),manifest_SHA256=u.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),version=VERSION)
    key=u.digest(config);run=a.project_root/'derived/replication/r8_receipt_independent_v104_PRIVATE'/key[:12];run.mkdir(parents=True,exist_ok=True);a.desktop.mkdir(parents=True,exist_ok=True)
    lock=(run/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This independent audit is already running')
    u.save(run/'CONFIG_PRIVATE.json',dict(config,key=key,arguments=vars(a)));report=run/'report'
    if report.exists():shutil.rmtree(report)
    report.mkdir()
    a1_state='NOT_VALIDATED';exp_state='BLOCKED';error=None
    try:
        r7,paths,binding=u.bind_r7(a.project_root,a.r7_root);base.prove_model_inputs(r7,paths,report)
        ref=u.load(PACKAGE/'evidence/S0_TRACE_REFERENCE.json')
        u.require(u.sha(paths['S0'])==next(r['input_SHA256'] for r in ref['model_input_proof'] if r['sample']=='S0'),'S0 differs from verified original-producer trace')
        audit=run/'audit';auditkey=u.digest([key,'audit'])
        if u.verify_cached(audit,auditkey) or reuse_v103_audit(a.project_root,audit,auditkey):
            for f in (audit/'report').iterdir():shutil.copy2(f,report/f.name)
            diag=u.load(report/'A1_independent_diagnostics.json')
        else:
            audit.mkdir(exist_ok=True);ar=audit/'report';ar.mkdir(exist_ok=True);d=base.m.r.load_fit_columns(paths['S0'])
            core_gate(d,r7,ar);u.log('25%: core S0 point estimates and SEs reproduced')
            diag=audit_a1(d,u.load(r7/'report/A_joint_balance.json'),ref['current_A1'],ar)
            calibration_point_archive_check(r7,ar)
            del d;gc.collect();u.pa.default_memory_pool().release_unused();u.certify(audit,auditkey,[paths['S0'],r7/'report/A_joint_balance.json',r7/'report/B_estimates.json'])
            for f in ar.iterdir():shutil.copy2(f,report/f.name)
        a1_state='INDEPENDENT_CURRENT_FIT_VALIDATED_ARCHIVE_OPEN';u.log('50%: independent A1 audit validated; historical archive difference remains explicit')
        if a.audit_only:exp_state='NOT_RUN_AUDIT_ONLY'
        else:
            work=run/'experience';expkey=u.digest([key,'experience'])
            if u.verify_cached(work,expkey):
                for f in (work/'report').iterdir():shutil.copy2(f,report/f.name)
                exp_state='COMPLETE';u.log('Experience completion checkpoint verified')
            else:
                work.mkdir(exist_ok=True);er=work/'report'
                if er.exists():shutil.rmtree(er)
                er.mkdir()
                split=experience(a,paths,binding,work,expkey,er);u.certify(work,expkey,[paths['S0'],split,r7/'report/summary.json'])
                for f in er.iterdir():shutil.copy2(f,report/f.name)
                exp_state='COMPLETE'
            u.log('100%: R8 item 4 complete; item 2 remains open on the historical A1 record')
    except Exception as e:
        error=str(e);u.log('STOPPED '+error);traceback.print_exc()
        ar=run/'audit/report'
        if ar.exists():
            for f in ar.iterdir():
                if f.is_file():shutil.copy2(f,report/f.name)
        er=run/'experience/report'
        if er.exists():
            for f in er.iterdir():
                if f.is_file() and f.name.startswith(('history_scope_','prior_experience_coverage.')):
                    shutil.copy2(f,report/f.name)
    finally:
        u.save(run/'STATE.json',dict(A1=a1_state,experience=exp_state,error=error));export(run,a.desktop,key,old,basekey,a1_state,exp_state,error)
        if oldlock:oldlock.close()
    return 0 if exp_state in ('COMPLETE','NOT_RUN_AUDIT_ONLY') else 2

if __name__=='__main__':raise SystemExit(main())
