"""Capped-fit probability predictions; all calibration outcomes are pre-policy."""
from io_utils import *
import sys
sys.path.insert(0,str(ROOT/'vendor'))
from design import design,counterfactual,value
from numeric import expit

END_MONTH={'full':'2025-10','fold0':'2024-10','fold1':'2025-04'}

def calibrate(offset,y,ids,pseudo_count=20.):
    """Same account shrinkage as the audited model; global fallback solves its offset."""
    offset,y,ids=map(np.asarray,(offset,y,ids))
    if not len(y) or not np.isfinite(offset).all():raise ValueError('Invalid calibration data')
    unique,g=np.unique(ids,return_inverse=True);n=np.bincount(g);s=np.bincount(g,weights=y)
    base=float(np.clip(y.mean(),1e-7,1-1e-7));target=(s+pseudo_count*base)/(n+pseudo_count)
    lo=np.full(len(n),-80.);hi=np.full(len(n),80.)
    for _ in range(55):
        mid=(lo+hi)/2;actual=np.bincount(g,weights=expit(mid[g]+offset))/n
        low=actual<target;lo=np.where(low,mid,lo);hi=np.where(low,hi,mid)
    alpha=(lo+hi)/2;error=float(np.max(abs(np.bincount(g,weights=expit(alpha[g]+offset))/n-target)))
    if error>1e-8:raise RuntimeError('Account probability calibration failed')
    lower,upper=-80.,80.
    for _ in range(55):
        mid=(lower+upper)/2
        if expit(mid+offset).mean()<base:lower=mid
        else:upper=mid
    return unique,alpha,(lower+upper)/2,base,error

def match_alpha(ids,unique,alpha,fallback):
    ix=np.searchsorted(unique,ids);ok=ix<len(unique)
    ok[ok]&=unique[ix[ok]]==np.asarray(ids)[ok]
    a=np.full(len(ids),fallback,dtype=float);a[ok]=alpha[ix[ok]]
    return a,ok

def offsets(d,fit,end_month,batch_size=100000):
    beta=np.asarray(fit['beta'],float);eta=np.empty(len(d))
    for lo in range(0,len(d),batch_size):
        hi=min(len(d),lo+batch_size);z=d.iloc[lo:hi].copy()
        # Probabilities need a calendar-level extrapolation; conditional validation did not.
        # Freeze the last fitted calendar effect beyond the fit's training window.
        month=z.month.astype(str);z['month']=month.where(month<=end_month,end_month)
        X,names,_=design(z,fit['model'],fit['curvature'])
        if names!=fit['names']:raise RuntimeError('Audited coefficient/design ordering differs')
        eta[lo:hi]=X@beta
    if not np.isfinite(eta).all():raise RuntimeError('Nonfinite old-formula index')
    return eta

def index_change(d,fit):
    """Exact change in every substantive term, at identical factual states."""
    new=counterfactual(d,advantage=ADVANTAGE);b=dict(zip(fit['names'],fit['beta']))
    dg=new.rg.to_numpy()-d.rg.to_numpy();dc=new.rc.to_numpy()-d.rc.to_numpy()
    dk=new.ki.to_numpy()-d.ki.to_numpy();dko=new.kj.to_numpy()-d.kj.to_numpy()
    delta=-b.get('own_cost',0.)*dk+b.get('opponent_stake',0.)*dko+b.get('draw_frame',0.)*dg
    delta-=b.get('extra_loss',0.)*(np.maximum(-new.rg.to_numpy(),0)-np.maximum(-d.rg.to_numpy(),0))
    if fit['model']=='curved':
        old_u=value(d.rc,fit['curvature'])-value(d.rg,fit['curvature'])
        new_u=value(new.rc,fit['curvature'])-value(new.rg,fit['curvature'])
        delta-=b['utility_cost']*(new_u-old_u)
    if np.max(abs((dc-dg)-dk),initial=0)>1e-8:raise RuntimeError('Counterfactual premium identity failed')
    return delta,dg,dc,dk,dko

def load(path,training=False,end=None):
    cols=list(REQUIRED if training else PREDICT_FIELDS)
    d=pd.read_parquet(path,columns=cols)
    if end is not None:d=d[d.month.astype(str)<=end].reset_index(drop=True)
    return compact(d)

def prediction_job(job):
    training,target,fitpath,model,stage,label,work,package_hash=job
    work=Path(work);fit=read(fitpath);end=END_MONTH[stage]
    if fit['status']!='ESTIMATED' or fit['model']!=model:raise RuntimeError('Invalid repaired fit')
    output=work/'predictions'/f'{label}_{model}_{stage}.parquet'
    key=digest(dict(version=VERSION,package=package_hash,training=stamp(training),target=stamp(target),
                    fit_sha256=sha(fitpath),calendar='carry_last_fitted_month',baseline='pre_only_pseudocount20_offset_matched_global'))
    old=reusable(output,key)
    if old:return old
    tr=load(training,True,end);eta=offsets(tr,fit,end)
    ids,alpha,fallback,base,error=calibrate(eta,tr.y.to_numpy(float),tr.chooser.to_numpy())
    cal=work/'calibration'/f'{label}_{model}_{stage}.parquet'
    frame(pd.DataFrame({'chooser':ids,'alpha':alpha}),cal)
    ntrain=len(tr);cal_max=int(tr.t.max());del tr,eta
    if cal_max>=IMPLEMENTED:raise RuntimeError('Post-policy outcome entered calibration')
    # Target y is deliberately absent from the prediction projection.
    d=load(target,False);oldeta=offsets(d,fit,end);parts=[];unseen=0
    for lo in range(0,len(d),100000):
        hi=min(len(d),lo+100000);z=d.iloc[lo:hi]
        a,seen=match_alpha(z.chooser.to_numpy(),ids,alpha,fallback);unseen+=int((~seen).sum())
        delta,dg,dc,dk,dko=index_change(z,fit)
        p0=expit(a+oldeta[lo:hi]);p1=expit(a+oldeta[lo:hi]+delta)
        chunk=pd.DataFrame(dict(week_ms=weeks(z.t),color=z.color.astype(str).to_numpy(),
             n=np.ones(len(z),dtype=np.int64),sum_old=p0,sum_new=p1,sum_delta_pp=100*(p1-p0),
             sum_dG=dg,sum_dC=dc,sum_dk=dk,sum_dko=dko,sum_abs_dG=abs(dg),sum_abs_dk=abs(dk)))
        parts.append(chunk.groupby(['week_ms','color'],observed=True).sum().reset_index())
    out=pd.concat(parts,ignore_index=True).groupby(['week_ms','color'],observed=True).sum().reset_index()
    for name in ('old','new','delta_pp','dG','dC','dk','dko','abs_dG','abs_dk'):
        out['mean_'+name]=out['sum_'+name]/out.n
    out['model']=model;out['fit_stage']=stage;out['target']=label
    frame(out,output)
    result=receipt(output,key,model=model,fit_stage=stage,target=label,target_rows=len(d),training_rows=ntrain,
        unseen_target_rows=unseen,calibration_last_timestamp_ms=cal_max,calibration_base_rate=base,
        calibration_max_error=error,calendar_rule='carry last fitted month after training end',
        prediction_uncertainty='Fixed-fit predictions; fold range is sensitivity, not a confidence interval')
    log(f'{label}: {model}/{stage} predicted {len(d):,} opportunities; no post y used')
    return result
