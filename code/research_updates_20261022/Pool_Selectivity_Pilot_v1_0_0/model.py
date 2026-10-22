"""Exploratory panel-mixture comparison, not a recovered moral-preference model.

V_ikc = alpha_k + theta_k F_c + X_c beta.
Common controls include board-by-stage effects except one reference cell in
each region. In the nested model theta is common. K is fixed at three.
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.optimize import minimize
from scipy.special import expit, logsumexp, betaln, gammaln
from util import log, require, atomic_json, csv_write, certify, ready

FEATURES=['cell','speed','season','color','gap','rating','crd','drd','premium','loss','cclock','dclock','cvol','dvol']

def fit_encoder(df):
    spec={}
    for name in FEATURES:
        values=sorted(df[name].unique().tolist())
        if name=='cell':
            require(5 in values and 21 in values,'Pilot lacks reference cells (clearly worse/equal at plies 21–40). Increase pilot accounts.')
            omit=[5,21]
        else: omit=[df.groupby(name)['n'].sum().idxmax().item() if hasattr(df.groupby(name)['n'].sum().idxmax(),'item') else df.groupby(name)['n'].sum().idxmax()]
        spec[name]={'observed':values,'columns':[v for v in values if v not in omit],'reference':omit}
    return spec

def encode(df, spec):
    row=[];col=[]; names=[]; unknown={}; offset=0
    for feature, s in spec.items():
        vals=df[feature].to_numpy()
        unknown[feature]=int(df.loc[~df[feature].isin(s['observed']),'n'].sum())
        for val in s['columns']:
            idx=np.flatnonzero(vals==val); row.append(idx);col.append(np.full(len(idx),offset))
            names.append(f'{feature}={val}');offset+=1
    rr=np.concatenate(row) if row else np.array([],dtype=int)
    cc=np.concatenate(col) if col else np.array([],dtype=int)
    X=sparse.csr_matrix((np.ones(len(rr)),(rr,cc)),shape=(len(df),offset))
    return X,names,unknown

def arrays(df, X, accounts):
    ids=np.searchsorted(accounts,df.chooser.to_numpy())
    require(np.all(ids<len(accounts)) and np.all(accounts[ids]==df.chooser.to_numpy()),'Unseen account in pilot')
    return dict(X=X,ids=ids.astype(np.int32),F=df.competitive.to_numpy(dtype=float),
                n=df.n.to_numpy(dtype=float),g=df.g.to_numpy(dtype=float),N=len(accounts))

def save_arrays(path,d):
    with path.open('wb') as f:
        np.savez_compressed(f,data=d['X'].data,indices=d['X'].indices,indptr=d['X'].indptr,
          shape=np.array(d['X'].shape),ids=d['ids'],F=d['F'],n=d['n'],g=d['g'],N=np.array(d['N']))

def load_arrays(path):
    with np.load(path) as z:
        return dict(X=sparse.csr_matrix((z['data'],z['indices'],z['indptr']),shape=tuple(z['shape'])),
          **{k:z[k] for k in ['ids','F','n','g']},N=int(z['N']))

def unpack(v,P,K,heterogeneous):
    a=v[:K]; width=K if heterogeneous else 1
    t=v[K:K+width]; t=t if heterogeneous else np.repeat(t,K)
    b=v[K+width:K+width+P]
    logits=np.r_[0.,v[K+width+P:]]
    lp=logits-logsumexp(logits)
    return a,t,b,lp

def components(v,d,K,heterogeneous):
    a,t,b,lp=unpack(v,d['X'].shape[1],K,heterogeneous)
    base=d['X']@b; ell=np.empty((d['N'],K))
    for k in range(K):
        z=base+a[k]+t[k]*d['F']
        ell[:,k]=np.bincount(d['ids'],weights=d['g']*z-d['n']*np.logaddexp(0,z),minlength=d['N'])
    joint=ell+lp; ll=logsumexp(joint,axis=1)
    q=np.exp(joint-ll[:,None])
    return base,ell,ll,q

def objective(v,d,K,heterogeneous,ridge=1e-6):
    P=d['X'].shape[1]; a,t,b,lp=unpack(v,P,K,heterogeneous)
    base,ell,ll,q=components(v,d,K,heterogeneous)
    common=np.zeros(len(d['n']));ga=[];gt=[]
    for k in range(K):
        residual=q[d['ids'],k]*(d['n']*expit(base+a[k]+t[k]*d['F'])-d['g'])
        common+=residual;ga.append(residual.sum());gt.append(residual@d['F'])
    gb=np.asarray(d['X'].T@common).ravel()/d['N'] + ridge*b
    gl=np.exp(lp[1:])-q[:,1:].mean(axis=0)
    gt=np.array(gt) if heterogeneous else np.array([sum(gt)])
    grad=np.r_[np.array(ga)/d['N'],gt/d['N'],gb,gl]
    loss=-ll.mean()+0.5*ridge*(b@b)
    return float(loss),grad

def fit_once(task):
    data_path,output,heterogeneous,K,seed,maxiter,warm,ridge,identity=task
    output=Path(output)
    if ready(output,identity): return str(output)
    d=load_arrays(data_path);P=d['X'].shape[1];rng=np.random.default_rng(seed)
    if warm is not None:
        a,t,b,lp=unpack(np.array(warm),P,K,False)
        v=np.r_[a+rng.normal(0,.08,K),t+rng.normal(0,.25,K),b,lp[1:]-lp[0]]
    else:
        a=np.linspace(-7.,-2.,K)+rng.normal(0,.3,K)
        t=np.array([1.5])+rng.normal(0,.2,1)
        weights=np.array([.84,.14,.02]) if K==3 else np.ones(K)/K
        v=np.r_[a,t,np.zeros(P),np.log(weights[1:]/weights[0])]
    width=K if heterogeneous else 1
    bounds=[(-16.,3.)]*K+[(-12.,12.)]*width+[(-8.,8.)]*P+[(-10.,10.)]*(K-1)
    start=time.monotonic(); iteration=[0]
    def callback(_):
        iteration[0]+=1
        if iteration[0]%50==0: log(f'{output.stem}: iteration {iteration[0]}, elapsed {(time.monotonic()-start)/60:.1f} min')
    log('FIT '+output.stem)
    opt=minimize(objective,v,args=(d,K,heterogeneous,ridge),jac=True,method='L-BFGS-B',bounds=bounds,
      options=dict(maxiter=maxiter,maxfun=maxiter*3,ftol=1e-10,gtol=2e-6,maxls=35,maxcor=15),callback=callback)
    base,ell,ll,q=components(opt.x,d,K,heterogeneous)
    a,t,b,lp=unpack(opt.x,P,K,heterogeneous)
    boundary=[j for j,(lo,hi) in enumerate(bounds) if min(abs(opt.x[j]-lo),abs(opt.x[j]-hi))<1e-4]
    gradient=objective(opt.x,d,K,heterogeneous,ridge)[1]
    result=dict(heterogeneous=bool(heterogeneous),K=K,seed=seed,parameters=opt.x.tolist(),
      alpha=a.tolist(),theta=t.tolist(),weights=np.exp(lp).tolist(),
      success=bool(opt.success),message=str(opt.message),iterations=int(opt.nit),
      objective=float(opt.fun),train_log_likelihood=float(ll.sum()),gradient_max_abs=float(abs(gradient).max()),
      boundary_parameters=boundary,elapsed_seconds=time.monotonic()-start,
      qualification='Exploratory bounded finite-mixture fit. Not an identification test or causal preference estimate.')
    require(np.isfinite(opt.fun) and np.isfinite(opt.x).all(),'Nonfinite optimizer result')
    atomic_json(output,result);certify(output,identity)
    log(f'FINISHED {output.stem}: converged={opt.success}, iterations={opt.nit}, boundary={len(boundary)}')
    return str(output)

def choose_fit(paths):
    values=[json.loads(Path(p).read_text()) for p in paths]
    converged=[v for v in values if v['success']]
    best=min(converged or values,key=lambda r:r['objective'])
    return best,values

def predict(fit,train,test):
    v=np.array(fit['parameters']);K=fit['K'];hetero=fit['heterogeneous']
    _,_,_,q=components(v,train,K,hetero)
    a,t,b,lp=unpack(v,test['X'].shape[1],K,hetero)
    base=test['X']@b;p=np.zeros(len(test['n']));ell=np.empty((test['N'],K))
    for k in range(K):
        z=base+a[k]+t[k]*test['F'];p+=q[test['ids'],k]*expit(z)
        ell[:,k]=np.bincount(test['ids'],weights=test['g']*z-test['n']*np.logaddexp(0,z),minlength=test['N'])
    # Joint sequence prediction integrates a fixed account type ONCE. No year-two updating.
    joint=logsumexp(np.log(np.maximum(q,1e-300))+ell,axis=1)
    return np.clip(p,1e-12,1-1e-12),joint,q

def eb_baseline(train_df,test_df):
    """Train-only beta-binomial smoothing in each of 2 regions × 3 stage bands."""
    def group(df):
        stage=df.cell.to_numpy()%8
        return df.competitive.to_numpy()*3+np.where(stage<=3,0,np.where(stage<=5,1,2))
    tr=train_df.copy();te=test_df.copy();tr['ebcell']=group(tr);te['ebcell']=group(te)
    counts=tr.groupby(['chooser','ebcell'],as_index=False)[['n','g']].sum()
    allaccounts=sorted(tr.chooser.unique());grid=__import__('pandas').MultiIndex.from_product([allaccounts,range(6)],names=['chooser','ebcell'])
    counts=counts.set_index(['chooser','ebcell']).reindex(grid,fill_value=0).reset_index()
    priors=[]
    for cell in range(6):
        s=counts[(counts.ebcell==cell)&(counts.n>0)];n=s.n.to_numpy();g=s.g.to_numpy()
        if len(s)==0:
            mean=float((tr.g.sum()+.5)/(tr.n.sum()+1));a,b=mean*20,(1-mean)*20;success=False
        else:
            mean=float((g.sum()+.5)/(n.sum()+1))
            def fun(v):
                a,b=np.exp(v);return -np.mean(betaln(g+a,n-g+b)-betaln(a,b))
            opt=minimize(fun,np.log([mean*20,(1-mean)*20]),method='L-BFGS-B',bounds=[(-12,14),(-12,14)])
            a,b=np.exp(opt.x);success=bool(opt.success)
        priors.append(dict(ebcell=cell,a=float(a),b=float(b),converged=success))
    ps=__import__('pandas').DataFrame(priors);counts=counts.merge(ps,on='ebcell')
    counts['prob']=(counts.g+counts.a)/(counts.n+counts.a+counts.b)
    pred=te[['chooser','ebcell']].merge(counts[['chooser','ebcell','prob']],on=['chooser','ebcell'],how='left',sort=False).prob.to_numpy()
    require(np.isfinite(pred).all(),'Missing EB baseline predictions')
    return np.clip(pred,1e-12,1-1e-12),priors

def score_models(predictions,df,accounts,report,joint):
    ids=np.searchsorted(accounts,df.chooser.to_numpy());n=df.n.to_numpy();g=df.g.to_numpy();F=df.competitive.to_numpy()
    scores=[];accountloss={}
    for name,p in predictions.items():
        loss=-(g*np.log(p)+(n-g)*np.log1p(-p))
        accountloss[name]=np.bincount(ids,weights=loss,minlength=len(accounts))
        for region,mask in [('all',np.ones(len(df),bool)),('competitive',F==1),('clearly_worse',F==0)]:
            nn=n[mask].sum()
            if not nn: continue
            scores.append(dict(model=name,region=region,opportunities=int(nn),
              actual_rate=float(g[mask].sum()/nn),predicted_rate=float((n[mask]*p[mask]).sum()/nn),
              log_loss_per_opportunity=float(loss[mask].sum()/nn),
              brier=float((g[mask]*(1-p[mask])**2+(n[mask]-g[mask])*p[mask]**2).sum()/nn)))
    csv_write(report/'heldout_scores.csv',scores)
    ns=np.bincount(ids,weights=n,minlength=len(accounts));active=ns>0;rows=[]
    for baseline in [n for n in predictions if n!='selectivity']:
        diff=accountloss[baseline]-accountloss['selectivity'];m=int(active.sum());avg=float(diff.sum()/ns.sum())
        se=float(np.sqrt(m/(m-1)*np.sum((diff[active]-avg*ns[active])**2))/ns.sum()) if m>1 else None
        rows.append(dict(comparison='selectivity vs '+baseline,metric='opportunity_weighted_log_score_gain',
           gain=avg,conditional_cluster_SE=se,accounts=m,
           interpretation='Positive favors selectivity; SE conditions on fitted models and does not include refitting uncertainty.'))
        avg_equal=float(np.mean(diff[active]/ns[active]))
        rows.append(dict(comparison='selectivity vs '+baseline,metric='equal_account_mean_log_score_gain',
           gain=avg_equal,conditional_cluster_SE=float(np.std(diff[active]/ns[active],ddof=1)/np.sqrt(m)) if m>1 else None,
           accounts=m,interpretation='Positive favors selectivity; observed year-two accounts only.'))
    if 'level_only' in joint and 'selectivity' in joint:
        diff=joint['selectivity'][active]-joint['level_only'][active]
        rows.append(dict(comparison='selectivity vs level_only',metric='joint_sequence_log_score_gain_per_account',
         gain=float(diff.mean()),conditional_cluster_SE=float(diff.std(ddof=1)/np.sqrt(len(diff))) if len(diff)>1 else None,
         accounts=int(active.sum()),interpretation='Integrates each fixed latent type once over the entire held-out history.'))
    csv_write(report/'heldout_comparisons.csv',rows)
    calibration=[]
    bins=np.array([0,.001,.0025,.005,.01,.02,.05,.10,.25,.5,1.00001])
    for name,p in predictions.items():
        for region,mask in [('competitive',F==1),('clearly_worse',F==0)]:
            for j in range(len(bins)-1):
                sel=mask&(p>=bins[j])&(p<bins[j+1]);nn=n[sel].sum()
                if nn: calibration.append(dict(model=name,region=region,lower=bins[j],upper=bins[j+1],
                  n=int(nn),actual_rate=float(g[sel].sum()/nn),predicted_rate=float((n[sel]*p[sel]).sum()/nn)))
    csv_write(report/'heldout_calibration.csv',calibration)
    return rows
