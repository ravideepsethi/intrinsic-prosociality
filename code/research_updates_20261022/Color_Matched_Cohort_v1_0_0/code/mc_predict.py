"""Pre-outcome baseline calibration and fixed-fit, matched-state forecasts."""
from mc_io import *
from model_design import design,counterfactual,MODELS

def solve_intercept(offset,target):
    lo=float(logit(target)-np.max(offset)-1);hi=float(logit(target)-np.min(offset)+1)
    for _ in range(52):
        mid=(lo+hi)/2
        if expit(offset+mid).mean()<target:lo=mid
        else:hi=mid
    return (lo+hi)/2

def calibrate(offset,y,ids,pseudo=20):
    offset=np.asarray(offset,float);y=np.asarray(y,float);ids=np.asarray(ids,np.int64)
    if not np.isfinite(offset).all() or not np.isin(y,[0,1]).all():raise ValueError('Invalid pre-policy calibration input')
    base=float(y.mean())
    if not 0<base<1:raise ValueError('Need both pre-policy outcomes')
    fallback=solve_intercept(offset,base)
    ui,gi=np.unique(ids,return_inverse=True)
    if pseudo is None:return ui,np.full(len(ui),fallback),fallback,dict(pre_rate_pp=100*base,global_shift=0.,max_account_error=None)
    n=np.bincount(gi);s=np.bincount(gi,weights=y);target=(s+pseudo*base)/(n+pseudo)
    low=np.full(len(ui),np.inf);high=np.full(len(ui),-np.inf)
    np.minimum.at(low,gi,offset);np.maximum.at(high,gi,offset)
    lo=logit(target)-high-1;hi=logit(target)-low+1
    for _ in range(48):
        mid=(lo+hi)/2;v=np.bincount(gi,weights=expit(offset+mid[gi]))/n
        below=v<target;lo=np.where(below,mid,lo);hi=np.where(below,hi,mid)
    a=(lo+hi)/2;error=float(np.max(abs(np.bincount(gi,weights=expit(offset+a[gi]))/n-target)))
    if error>1e-8:raise RuntimeError('Account calibration did not converge')
    shift=solve_intercept(offset+a[gi],base);a+=shift
    # New accounts use the pooled pre-policy baseline, already rate-matched.
    return ui,a,fallback,dict(pre_rate_pp=100*base,global_shift=shift,max_account_error=error)

def match_intercepts(ids,ui,alpha,fallback):
    ids=np.asarray(ids,np.int64);pos=np.searchsorted(ui,ids);safe=np.minimum(pos,len(ui)-1)
    known=(pos<len(ui))&(ui[safe]==ids)
    return np.where(known,alpha[safe],fallback),known

def fixed_offsets(d,fit):
    old=np.empty(len(d));delta=np.empty(len(d));beta=np.asarray(fit['beta'])
    for lo in range(0,len(d),75000):
        hi=min(len(d),lo+75000);x=d.iloc[lo:hi].copy()
        # Pre-policy fit has no future month coefficient. Freeze the final
        # fitted October effect when transporting to November and later.
        x.loc[x.month>'2025-10','month']='2025-10'
        xo=counterfactual(x,advantage=0.);xn=counterfactual(x,advantage=ADVANTAGE)
        a,names,_=design(xo,fit['model'],fit['curvature']);b,names2,_=design(xn,fit['model'],fit['curvature'])
        if names!=fit['names'] or names2!=names:raise RuntimeError('Frozen fit design does not match')
        old[lo:hi]=a@beta;delta[lo:hi]=(b-a)@beta
    if not np.isfinite(old).all() or not np.isfinite(delta).all():raise RuntimeError('Nonfinite forecast')
    return old,delta

def predict_state(target,state,work,report,memory,models=MODELS):
    work=Path(work);report=Path(report);snap=auth(target,work)
    c=connect(work/'tmp'/('forecast_load_'+state),2,memory)
    try:d=c.execute('SELECT * FROM '+scan(target)+' WHERE state='+q(state)+' ORDER BY chooser,t,game_id').fetchdf()
    finally:c.close()
    if d.empty:raise RuntimeError('No matched rows in '+state)
    # Counts and baseline outcomes use only the unambiguously pre-policy side.
    train=d.t.to_numpy(np.int64)<BRACKET
    if train.sum()<100:raise RuntimeError('Insufficient pre-policy calibration rows')
    weeks=week_ms(d.t);colors=d.color.to_numpy()
    # Use factorized (week,color) pairs rather than pandas datetime resolutions.
    pairs=pd.MultiIndex.from_arrays([weeks,colors]);gi,levels=pd.factorize(pairs,sort=True)
    counts=np.bincount(gi);wk=np.array([v[0] for v in levels],np.int64);co=np.array([v[1] for v in levels])
    results=[];calibrations=[]
    for model in models:
        fp=ROOT/'authority/fits'/(f'rd110_{model}_full.json' if state=='equal' else f'losing_{model}_full.json')
        fit=read(fp)
        if fit['status']!='ESTIMATED':raise RuntimeError('Frozen model fit is not converged')
        out=work/'forecasts'/f'{state}_{model}.parquet'
        key=digest(dict(version=VERSION,input=snap,fit=sha(fp),calibration_cutoff=BRACKET,month_transport='carry_final_fitted_month'))
        old=cache(out,key,work)
        if old:
            results.append(pd.read_parquet(out));calibrations.extend(old['calibrations']);continue
        eta,change=fixed_offsets(d,fit);rows=[];cals=[]
        variants=[('account20',20)]
        if model in ('curved','framing','strength'):variants += [('account5',5),('account100',100),('pooled',None)]
        for baseline,pseudo in variants:
            ui,alpha,fallback,cal=calibrate(eta[train],d.y.to_numpy()[train],d.chooser.to_numpy()[train],pseudo)
            a,known=match_intercepts(d.chooser.to_numpy(),ui,alpha,fallback)
            po=expit(a+eta);pn=expit(a+eta+change)
            old_mean=np.bincount(gi,weights=po)/counts;new_mean=np.bincount(gi,weights=pn)/counts
            v=pd.DataFrame(dict(state=state,model=model,baseline=baseline,week_ms=wk,color=co,n=counts,
                old_rate_pp=100*old_mean,new_rate_pp=100*new_mean,mechanical_delta_pp=100*(new_mean-old_mean),
                fallback_account_rows=np.bincount(gi,weights=~known).astype(np.int64)))
            rows.append(v);cal.update(state=state,model=model,baseline=baseline,pre_rows=int(train.sum()),pre_accounts=len(ui),
                post_rows=int((~train).sum()),post_fallback_rows=int((~known&~train).sum()),
                predicted_pre_rate_pp=100*float(po[train].mean()),parameter_uncertainty_propagated=False)
            cals.append(cal)
        combined=pd.concat(rows,ignore_index=True);frame(combined,out)
        commit(out,key,calibrations=cals,input_snapshot=snap,fit_sha256=sha(fp));results.append(combined);calibrations.extend(cals)
        log(state+'/'+model+': matched predictions complete; post outcomes unused')
    result=pd.concat(results,ignore_index=True)
    table(result,report/(state+'_weekly_predictions'));table(calibrations,report/(state+'_baseline_calibration'))
    return result
