"""Rebuild arena matching before reading outcomes; reuse the original Patron models."""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
from next_common import *

def modules():
    sys.path.insert(0,str(ROOT/'source/patron'))
    # Each family runs in its own subprocess, so these original package imports are isolated.
    mod=load(ROOT/'source/patron/runner/run.py','arena_patron_producer')
    if not getattr(mod.prior,'arena_utc_configured',False):
        original=mod.prior.connect
        def utc(path,args,temporary):
            c=original(path,args,temporary);c.execute("SET TimeZone='UTC'");return c
        mod.prior.connect=utc;mod.prior.arena_utc_configured=True
    return mod

def guard_patron(mod, audits):
    original=mod.common.fit_absorbed_ols
    def fit(frame, **kw):
        try:r=original(frame,**kw)
        except RuntimeError as e:
            if not any(s in str(e) for s in ['empty estimation sample','no regressors survive FE absorption','fewer than two clusters']):raise
            rows=[{'model':kw['model_name'],'variable':x,'status':'not_estimable','coefficient_pp':np.nan,
                   'se_pp':np.nan,'statistic':np.nan,'p_two_sided_approx':np.nan,
                   'ci95_low_pp':np.nan,'ci95_high_pp':np.nan,'reason':str(e)} for x in kw['regressors']]
            audit={'model':kw['model_name'],'status':'UNSUPPORTED','reason':str(e),'candidate_rows':len(frame)}
            audits.append(audit)
            return mod.common.OLSResult(model={'model':kw['model_name'],'n':0,'rank':0,'status':'not_estimable','arena_estimability_audit':audit},
              coefficients=pd.DataFrame(rows),covariance=np.empty((0,0)),kept_names=[])
        # Audit the full within-FE span, including terms the original deterministic reducer drops.
        names=list(kw['regressors']);cols=list(dict.fromkeys([kw['y_col'],kw['fe_col']]+names+([kw['cluster_col']] if kw.get('cluster_col') else [])))
        f=frame[cols].copy();x=f[names].apply(pd.to_numeric,errors='coerce').to_numpy(dtype=float)
        valid=np.isfinite(x).all(axis=1)&np.isfinite(pd.to_numeric(f[kw['y_col']],errors='coerce'))&f[kw['fe_col']].notna().to_numpy()
        if kw.get('cluster_col'):valid &= f[kw['cluster_col']].notna().to_numpy()
        x=x[valid];codes,levels=pd.factorize(f.loc[valid,kw['fe_col']].astype(str),sort=True)
        for j in range(x.shape[1]):x[:,j]=mod.common._demean_by_codes(x[:,j],codes,len(levels))
        scale=np.sqrt(np.mean(x*x,axis=0));x/=np.where(scale>1e-10,scale,1.)
        gram=x.T@x/max(1,len(x));ev,vec=np.linalg.eigh((gram+gram.T)/2)
        pos=ev>max(1e-10,float(ev[-1])*1e-10)
        identified=(np.sum(vec[:,~pos]**2,axis=1)<1e-8)&(scale>1e-10)
        invalid={name for name,ok in zip(names,identified) if not ok}
        zero_outcomes=np.unique(pd.to_numeric(f.loc[valid,kw['y_col']],errors='coerce')).size<2
        if zero_outcomes:invalid.update(names)
        before=list(r.kept_names);keep=[i for i,n in enumerate(before) if n not in invalid]
        for i,row in r.coefficients.iterrows():
            if row['variable'] in invalid:
                r.coefficients.loc[i,'status']='not_estimable'
                r.coefficients.loc[i,'reason']='No outcome variation' if zero_outcomes else 'Individual term is not identified in the full within-FE design'
                for field in ['coefficient_pp','se_pp','statistic','p_two_sided_approx','ci95_low_pp','ci95_high_pp']:
                    if field in r.coefficients:r.coefficients.loc[i,field]=np.nan
        # Preserve only identified covariance coordinates for original contrast construction.
        r.covariance=r.covariance[np.ix_(keep,keep)];r.kept_names=[before[i] for i in keep]
        audit={'model':kw['model_name'],'status':'ESTIMATED_WITH_SUPPORT_AUDIT','n':len(x),
          'scaled_design_rank':int(pos.sum()),'original_retained_terms':before,'nonestimable_terms':sorted(invalid),
          'zero_outcome_variation':zero_outcomes}
        audits.append(audit);r.model['arena_estimability_audit']=audit
        return r
    mod.common.fit_absorbed_ols=fit

def run(sample, root, args, contract):
    mod=modules();prior=mod.prior
    mod.VERSION='arena-next-1.0.0';mod.WAVE3A_CONFIG=contract
    state=Path(root)/'private/patron';public=Path(root)/'public/patron'
    state.mkdir(parents=True,exist_ok=True);public.mkdir(parents=True,exist_ok=True)
    pa_args=SimpleNamespace(threads=args.threads,memory_limit=args.memory)
    # All input validations are the original ones, except the new arena census already authenticated above.
    snapshot=prior.authenticate_snapshot(args.project)
    with heartbeat('Rebuilding the arena Patron design'):
        summary,sr=prior.checkpoint(state,'summary',contract,lambda d:prior.run_summary(d,pa_args,sample))
        matches,mr=prior.checkpoint(state,'matching',contract,lambda d:prior.run_matching(d,pa_args,summary/'chooser_summary_private.parquet'))
        coverage,cr=prior.checkpoint(state,'coverage',contract,lambda d:prior.run_coverage(d,pa_args,summary/'chooser_summary_private.parquet',matches,snapshot))
        # Checkpoint metadata nests returned producer fields under result; read its original format explicitly.
        c=db(state/'target_count_spill',args.memory,args.threads)
        try:target_rows=c.execute('SELECT count(*) FROM '+parq(matches/'acquisition_users_private.parquet')).fetchone()[0]
        finally:c.close()
        design,dr=prior.checkpoint(state,'design',contract,lambda d:mod.build_design(d,pa_args,sample,
          matches/'acquisition_users_private.parquet',snapshot,target_rows))
    c=db(state/'outcomes_spill',args.memory,args.threads)
    try:
        qa,_,_=mod.models.outcome_qa(c,snapshot,fixture=False)
        frame=mod.load_frames(c,design/'chooser_design_features_private.parquet',snapshot)
    finally:c.close()
    require(len(frame)==target_rows and frame['username_norm'].nunique()==target_rows,'Patron join changed the arena matching denominator')
    js(public/'SNAPSHOT_QA.json',qa)
    bounds=mod.missing_outcome_bounds(frame);js(public/'MISSING_OUTCOME_BOUNDS.json',bounds)
    flow=frame.groupby(['group_ever_kind_fair','acquisition_role','outcome_status'],observed=True).agg(
      accounts=('username_norm','size'),opportunities=('total_opps','sum'),kind_draws=('total_kind_count','sum')).reset_index()
    flow.to_csv(public/'outcome_coverage.csv',index=False)
    for file in ['aggregate_coverage.json']:
        shutil.copy2(coverage/file,public/file)
    support=read(design/'preoutcome_support_receipt.json');js(public/'PREOUTCOME_SUPPORT.json',support)
    audits=[];guard_patron(mod,audits)
    primary={};limited=None
    try:primary=mod.main_models(frame,state,contract,public,support)
    except RuntimeError as e:
        # The original large-pool minimum requirement may fail in arenas. Retain completed fits and report it.
        if 'Required main-paper estimate is not identified:' not in str(e):raise
        limited=str(e)
    corrected=mod.corrected_date_models(frame,state,contract,public)
    # Audit records are also inside each model checkpoint, so resuming cannot erase them.
    audited_models=read(public/'chooser_models.json')+read(public/'corrected_dates_models.json')
    js(public/'NUMERICAL_AUDIT.json',[m['arena_estimability_audit'] for m in audited_models])
    js(public/'ARENA_SCOPE.json',{'profile_date':'fixed August 2026 snapshot','new_profile_queries':0,
      'matching_seed':prior.planner.DESIGN_SEED,'matching_before_profile_outcomes':True,
      'old_confirmatory_labels_are_source_family_labels_only':True,'arena_results_are_new_subsample_analyses':True,
      'target_accounts':target_rows,'primary_missing_bounds':{k:v for k,v in bounds.items() if k!='by_cell'},
      'required_term_support_limit':limited,'missing_controls_are_not_assumed_nonpatrons':True})
    return {'status':'COMPLETE_WITH_SUPPORT_LIMITS' if limited else 'COMPLETE','primary':primary,
      'corrected_dates':corrected,'target_accounts':target_rows,'support_limit':limited,'new_profile_queries':0}
