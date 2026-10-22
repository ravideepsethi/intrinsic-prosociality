"""Color-shift predictions and pre-outcome power; never reports post y."""
from scipy.special import expit
from common import *
from design import design,counterfactual,MODELS
from stats import account_intercepts

IMPLEMENTED=int(pd.Timestamp('2025-11-18T07:22:00Z').timestamp()*1000)
ANNOUNCED=int(pd.Timestamp('2025-12-22T22:35:00Z').timestamp()*1000)
def week_values(d,value):
    z=pd.DataFrame(dict(week=pd.to_datetime(d.t,unit='ms',utc=True).dt.tz_localize(None).dt.to_period('W-SUN').dt.start_time,
                        color=d.color.to_numpy(),value=np.asarray(value)))
    return z.groupby(['week','color']).value.mean().unstack('color').reindex(columns=['white','black'])

def mde(null):
    null=np.asarray(null,float);critical=np.quantile(abs(null),.95)
    lo=0.;hi=max(1e-7,10*np.std(null))
    for _ in range(70):
        mid=(lo+hi)/2
        if np.mean(abs(null+mid)>critical)<.8:lo=mid
        else:hi=mid
    return hi,critical

def block_null(pre,npost,block,reps=10000,seed=2026092601):
    x=np.asarray(pre,float);x=x-x.mean();n=8+npost
    if len(x)<max(32,2*block):raise ValueError('At least 32 complete pre weeks required')
    rng=np.random.default_rng(seed+block+npost)
    starts=rng.integers(0,len(x)-block+1,size=(reps,int(np.ceil(n/block))))
    draws=x[(starts[:,:,None]+np.arange(block)).reshape(reps,-1)[:,:n]]
    return draws[:,8:].mean(axis=1)-draws[:,:8].mean(axis=1)

def predicted_changes(training,target,fits):
    result={}
    for model,f in fits.items():
        if f['status']!='ESTIMATED':continue
        X,_,_=design(training,model,f['curvature']);ids,a,base=account_intercepts(X@f['beta'],training.y.to_numpy(float),training.chooser.to_numpy())
        old=counterfactual(target,advantage=0.);new=counterfactual(target,advantage=11.782457)
        A,_,_=design(old,model,f['curvature']);B,_,_=design(new,model,f['curvature'])
        ix=np.searchsorted(ids,target.chooser.to_numpy());valid=ix<len(ids)
        valid[valid]&=ids[ix[valid]]==target.chooser.to_numpy()[valid]
        alpha=np.full(len(target),np.log(base/(1-base)));alpha[valid]=a[ix[valid]]
        result[model]=100*(expit(alpha+B@f['beta'])-expit(alpha+A@f['beta']))
    return result

def run_policy(training,fits,project,work,report,explicit=None):
    work,report=map(Path,(work,report))
    path=Path(explicit) if explicit else Path(project)/'derived/replication_36m/mechanism_color_inputs_v100/manifest.json'
    target=training;actual=False;m=None
    status=dict(status='POST_POLICY_SAMPLE_AND_CALIBRATION_DEPENDENCIES_OPEN',
        expected_manifest=str(path),behavioral_coefficients_opened=False,visibility='UNIDENTIFIED',
        note='Pre-policy transported predictions are a planning diagnostic; not the frozen post-cohort prediction/MDE test.')
    if path.exists():
        m=read(path)
        checks=dict(format='MECHANISM_COLOR_INPUTS_V1',pool_and_previous_adjacency_certified=True,
          chronology_through='2026-04',cohort_uses_only_preimplementation_information=True,
          actual_stratum_calibration_reviewed=True,missing_clock_and_material_rules_aligned=True)
        for k,v in checks.items():
            if m.get(k)!=v:raise RuntimeError('Policy contract unresolved: '+k)
        for k in ('producer_receipt','calibration_review','censor_source'):
            r=m[k];p=Path(r['path']);p=p if p.is_absolute() else path.parent/p;auth(p,work,r['sha256'])
        censor=int(pd.Timestamp(m['censor_utc']).timestamp()*1000);paths=[]
        for r in m['files']:
            p=Path(r['path']);p=p if p.is_absolute() else path.parent/p;auth(p,work,r['sha256'],r['rows']);paths.append(p)
        c=connect(work/'tmp/policy',2,2048)
        try:
            target=c.execute(f"SELECT * FROM {scan(paths)} WHERE fixed_regular_cohort IS TRUE AND pool_main IS TRUE AND ply>10 AND cp>=-100 AND cp<100 AND g>=-575 AND g<575 AND t<{censor}").fetchdf()
        finally:c.close()
        if target.game_id.duplicated().any():raise RuntimeError('Policy game keys duplicated')
        old=counterfactual(target,advantage=0.)
        if max(np.max(abs((target.rg-old.rg).to_numpy()),initial=0),np.max(abs((target.rc-old.rc).to_numpy()),initial=0),np.max(abs((target.ki-old.ki).to_numpy()),initial=0),np.max(abs((target.kj-old.kj).to_numpy()),initial=0))>1e-6:
            raise RuntimeError('Policy adapter must carry exact old-formula counterfactual payoffs at stored states')
        actual=True;status.update(status='PREDICTION_POWER_SCREEN_READY',manifest_sha256=sha(path),censor_utc=m['censor_utc'])
    # Post y is never aggregated or used in this module. Pre y supplies noise only.
    pre=target[target.t<IMPLEMENTED].copy()
    preweekly=week_values(pre,100*pre.y.to_numpy(float))
    start=pd.to_datetime(pre.t.min(),unit='ms',utc=True).tz_localize(None) if len(pre) else pd.Timestamp('2100-01-01')
    end=min(pd.Timestamp('2025-11-17'),pd.to_datetime(pre.t.max(),unit='ms',utc=True).tz_localize(None)) if len(pre) else start
    complete=preweekly[(preweekly.index>=start.normalize())&(preweekly.index+pd.Timedelta(days=7)<=end)]
    # Missing color or missing calendar weeks are not filled with zeros.
    complete=complete.dropna();diff=complete.white-complete.black
    contiguous=bool(len(diff)>0 and np.all(np.diff(diff.index.values)==np.timedelta64(7,'D')))
    estimates=[];power=[]
    if actual:
        periods={}
        for label,lo,hi in [('unannounced',IMPLEMENTED,ANNOUNCED),('announced',ANNOUNCED,int(pd.Timestamp(m['censor_utc']).timestamp()*1000))]:
            t=target[target.t.between(lo,hi-1)].copy()
            if len(t):periods[label]=t
    else:periods={'pre_policy_transport':training}
    for label,t in periods.items():
        delta=predicted_changes(training,t,fits);pred={}
        for model,v in delta.items():
            w=week_values(t,v).dropna()
            if actual:
                lo=IMPLEMENTED if label=='unannounced' else ANNOUNCED
                hi=ANNOUNCED if label=='unannounced' else int(pd.Timestamp(m['censor_utc']).timestamp()*1000)
                wl=pd.to_datetime(w.index,utc=True).astype('int64')//1000000
                w=w[(wl>=lo)&(wl+7*DAY<=hi)]
            effect=float((w.white-w.black).mean()) if len(w) else np.nan;pred[model]=effect
            estimates.append(dict(period=label,model=model,white_shift_pp=float(w.white.mean()),black_shift_pp=float(w.black.mean()),
              statistic_prediction_pp=effect,complete_weeks=len(w),target_rows=len(t),actual_frozen_cohort=actual,
              prediction_interval_status='Conditional fitted-parameter prediction; uncertainty not propagated, no preference bound',
              awareness=1.,includes_exact_both_action_and_opponent_stake_changes=True))
        if not pred:continue
        lengths=[len(w)] if actual else [4,8]
        if not contiguous or len(diff)<32:continue
        for npost in lengths:
            if npost<1:continue
            for block in (4,8):
                null=block_null(diff.to_numpy(),npost,block);minimum,critical=mde(null)
                for i,a in enumerate(sorted(pred)):
                    for b in sorted(pred)[i+1:]:
                        for awareness in (.05,.1,.2,.5,1.):
                            contrast=awareness*(pred[a]-pred[b])
                            power.append(dict(period=label,model_a=a,model_b=b,awareness=awareness,post_weeks=npost,
                              block_weeks=block,predicted_difference_pp=contrast,mde_pp=minimum,
                              power_at_fitted_predictions=float(np.mean(abs(null+contrast)>critical)),
                              detectable_at_80_percent=bool(abs(contrast)>=minimum),actual_frozen_cohort=actual,
                              meaning='Pre-noise conditional power screen; awareness assumed and parameter uncertainty unpropagated'))
    table(estimates,report/'color_model_predictions.parquet');table(power,report/'color_pairwise_power.parquet')
    status.update(pre_complete_weeks=len(diff),pre_weeks_contiguous=contiguous,
                  prediction_parameter_uncertainty='NOT_PROPAGATED; no automatic GO or preference bound',
                  post_outcomes_used=False,mechanism_shares_released=False)
    if actual and not power:status['status']='PREDICTIONS_ONLY_INSUFFICIENT_POWER_INPUTS'
    if actual and power and not any(r['detectable_at_80_percent'] for r in power):status['status']='NO_DISCRIMINATION_AT_FITTED_PREDICTIONS'
    write(report/'POLICY_STATUS.json',status)
