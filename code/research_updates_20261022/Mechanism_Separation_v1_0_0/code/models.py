"""Candidate models, forward validation, and observed-vs-predicted arms."""
from scipy.special import expit
from common import *
from design import *
from stats import fit_conditional,conditional_kernel,groups,account_intercepts

FOLDS=(('2024-10','2024-11','2025-04'),('2025-04','2025-05','2025-10'))

def fit_one(d,model,inference=True,cue=None,start=None):
    full_n=len(d);full_accounts=d.chooser.nunique()
    counts=d.groupby('chooser').y.agg(['sum','count'])
    switchers=counts.index[(counts['sum']>0)&(counts['sum']<counts['count'])]
    # Exact likelihood contribution is zero outside these groups. Filter before
    # allocating the dense design, preserving all rows within retained accounts.
    d=d[d.chooser.isin(switchers)]
    cc=controls(d);best=None
    for p in (CURVATURE if model=='curved' else (.5,)):
        X,names,bounds=design(d,model,p,cue,cc)
        r=fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),bounds,start,inference=False)
        r.update(model=model,curvature=p,names=names,cue=cue,full_n=full_n,full_accounts=full_accounts)
        if r['status']=='ESTIMATED' and (best is None or r['loglik']>best['loglik']):best=r
    if best is None:return r
    if inference:
        X,names,bounds=design(d,model,best['curvature'],cue,cc)
        rr=fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),bounds,best['beta'],inference=True)
        rr.update(model=model,curvature=best['curvature'],names=names,cue=cue,full_n=full_n,full_accounts=full_accounts);best=rr
    return best

def score_months(d,fit):
    if fit['status']!='ESTIMATED':return []
    X,_,_=design(d,fit['model'],fit['curvature'],fit.get('cue'))
    # The score compares within chooser-month allocation of grants. Counts are
    # conditioned statistics, not baseline estimates learned from held-out y.
    ids=pd.MultiIndex.from_arrays([d.chooser,d.month]).factorize()[0]
    order,st,en=groups(ids);yy=d.y.to_numpy(float)[order]
    ll,_=conditional_kernel(X[order]@fit['beta'],yy,st,en)
    months=d.month.to_numpy()[order][st];grants=np.add.reduceat(yy,st);n=en-st
    df=pd.DataFrame(dict(month=months,ll=ll,n=n,informative=(grants>0)&(grants<n)))
    z=df.groupby('month',sort=True).agg(loglik=('ll','sum'),rows=('n','sum'),informative_groups=('informative','sum')).reset_index()
    z['model']=fit['model'];z['cue']=fit.get('cue') or '';return z.to_dict('records')

def compare(d,work,report,label,inference=True,cue=None,save=True,fit_full=True):
    work,report=map(Path,(work,report));work.mkdir(parents=True,exist_ok=True)
    fits={};scores=[];coeff=[]
    data_hash=hashlib.sha256(pd.util.hash_pandas_object(d,index=False).values.tobytes()).hexdigest() if save else ''
    for model in MODELS:
        path=work/(label+'_'+model+('_'+cue if cue else '')+'.json')
        key=digest(dict(version=VERSION,label=label,model=model,cue=cue,n=len(d),
                        design_hash=data_hash))
        if not fit_full:
            fit=dict(status='NOT_REQUIRED_FOR_HELDOUT_SELECTION',names=[])
        elif save and path.exists():
            stored=read(path)
            if stored['key']!=key:raise RuntimeError('Model cache differs: '+str(path))
            fit=stored['fit']
            for name in ('beta','cov','identified','boundary','switcher_ids'):
                if name in fit:fit[name]=np.asarray(fit[name],dtype=bool if name in ('identified','boundary') else float)
        else:
            log(label+': conditional logit '+model+(' with '+cue if cue else ''))
            fit=fit_one(d,model,inference,cue)
            if save:write(path,dict(key=key,fit=fit))
        fits[model]=fit
        for j,name in enumerate(fit.get('names',[])):
            if 'beta' not in fit:continue
            usable=fit['status']=='ESTIMATED' and inference and fit['identified'][j] and not fit['boundary'].any()
            variance=fit['cov'][j,j] if usable else np.nan
            se=np.sqrt(max(0,variance)) if np.isfinite(variance) else np.nan
            coeff.append(dict(sample=label,cue=cue or '',model=model,term=name,beta=fit['beta'][j],se=se,
                              lo=fit['beta'][j]-1.96*se,hi=fit['beta'][j]+1.96*se,
                              interval_status='INTERIOR_IDENTIFIED_WALD' if np.isfinite(se) else 'NO_WALD_INTERVAL',
                              model_status=fit['status'],n=fit.get('n'),grants=fit.get('grants'),accounts=fit.get('accounts')))
        for fold,(end,start,stop) in enumerate(FOLDS):
            train=d[d.month<=end];test=d[d.month.between(start,stop)]
            if not len(train) or not len(test):continue
            cp=work/(label+'_'+model+('_'+cue if cue else '')+f'_fold{fold}.json')
            if save and cp.exists():
                v=read(cp)
                if v['key']!=key:raise RuntimeError('Forward model cache differs')
                rows=v['scores']
            else:
                f=fit_one(train,model,False,cue);rows=score_months(test,f)
                for row in rows:row['fold']=fold;row['training_status']=f['status']
                if not rows:rows=[dict(model=model,fold=fold,training_status=f['status'],month=start,loglik=np.nan,rows=len(test),informative_groups=0)]
                if save:write(cp,dict(key=key,scores=rows,fit=f))
            scores+=rows
    if save:
        table(coeff,report/(label+'_model_coefficients.parquet'))
        table(scores,report/(label+'_heldout_scores.parquet'))
        table(pairwise(scores),report/(label+'_heldout_comparisons.parquet'))
    return fits,scores

def pairwise(scores,seed=2026092601):
    df=pd.DataFrame(scores)
    if df.empty or 'loglik' not in df:return []
    p=df.pivot_table(index='month',columns='model',values='loglik',aggfunc='sum')
    result=[];rng=np.random.default_rng(seed)
    for i,a in enumerate(p.columns):
        for b in p.columns[i+1:]:
            delta=(p[a]-p[b]).dropna().to_numpy();n=len(delta)
            if n<2:continue
            boot=delta[rng.integers(0,n,size=(2000,n))].mean(axis=1)
            result.append(dict(model_a=a,model_b=b,months=n,mean_month_logscore_difference=delta.mean(),
                 se=delta.std(ddof=1)/np.sqrt(n),lo=np.quantile(boot,.025),hi=np.quantile(boot,.975),
                 interpretation='Predictive comparison on held-out chooser-month variation; not causal inference'))
    return result

def decision(scores):
    df=pd.DataFrame(scores)
    if df.empty or df.get('training_status',pd.Series(dtype=str)).ne('ESTIMATED').any():return 'FIT_FAILURE'
    p=df.pivot_table(index='month',columns='model',values='loglik',aggfunc='sum')
    if p.shape[1]!=len(MODELS) or p.isna().any().any() or len(p)<2:return 'INSUFFICIENT_VALIDATION'
    best=p.sum().idxmax()
    for other in p.columns:
        if other==best:continue
        d=(p[best]-p[other]).to_numpy()
        if d.mean()<=2*d.std(ddof=1)/np.sqrt(len(d)):return 'INDISTINGUISHABLE'
    return best

def compatible_models(scores):
    df=pd.DataFrame(scores)
    if df.empty or df.get('training_status',pd.Series(dtype=str)).ne('ESTIMATED').any():return []
    p=df.pivot_table(index='month',columns='model',values='loglik',aggfunc='sum')
    if p.shape[1]!=len(MODELS) or p.isna().any().any() or len(p)<2:return []
    best=p.sum().idxmax();retained=[]
    for model in p.columns:
        difference=(p[best]-p[model]).to_numpy()
        if model==best or difference.mean()<=2*difference.std(ddof=1)/np.sqrt(len(difference)):retained.append(model)
    return retained

def prediction_profiles(d,fits,report,label):
    rows=[]
    # Use an outcome-independent deterministic standardization sample to bound RAM.
    take=(pd.util.hash_pandas_object(d.game_id,index=False).to_numpy()%100)<5
    stand=d.loc[take] if take.sum()>=1000 else d
    for model,f in fits.items():
        if f['status']!='ESTIMATED':continue
        X,_,_=design(d,model,f['curvature'],f.get('cue'))
        ids,alpha,base=account_intercepts(X@f['beta'],d.y.to_numpy(),d.chooser.to_numpy())
        ix=np.searchsorted(ids,stand.chooser.to_numpy());a=alpha[ix]
        ref=counterfactual(stand,g=0);Z,_,_=design(ref,model,f['curvature'],f.get('cue'));zero=Z@f['beta']
        for gap in (-300,-200,-100,-50,0,50,100,200,300):
            cf=counterfactual(stand,g=gap);W,_,_=design(cf,model,f['curvature'],f.get('cue'));eta=W@f['beta']
            rows.append(dict(sample=label,model=model,gap=gap,index_difference=float(np.mean(eta-zero)),
                pp_difference=float(100*np.mean(expit(a+eta)-expit(a+zero))),
                probability=float(expit(a+eta).mean()),standardization_rows=len(stand),
                interpretation='Conditional model prediction; absolute probabilities additionally use training-only smoothed intercepts'))
    table(rows,Path(report)/(label+'_predicted_gap_profiles.parquet'));return rows
