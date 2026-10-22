"""Roots, absolute effects, conservative ratio intervals and decision rules."""
from __future__ import annotations
from g_common import *
from g_design import *
from g_fe import statistics,solve,quadratic
from g_outcome import exchange,solve_curve

def revealed_roots(fit,templates,knots):
    rows=[]
    for r in templates.to_dict('records'):
        d0=pd.DataFrame([r]);d0['vf']=0.;d0['mate']=0.;d0['dr']=0.;d0['stm']=0
        def mixed(z):
            x=g2_design(z,'MU')[0];share=float(r.get('ultrabullet_share',0))
            if share>0:
                ultra=z.copy();ultra['speed']=0;x=(1-share)*x+share*g2_design(ultra,'MU')[0]
            return x
        x0=mixed(d0)[0];b=fit['full']['beta']
        def fn(x):
            z=pd.DataFrame([r]*len(x));z['vf']=x;z['mate']=0.;z['dr']=100.;z['stm']=0
            return (mixed(z)-x0)@b
        root,status=solve_curve(fn);rows.append(dict(cell=int(r['cell']),Xr=root,status=status,N=int(r['N'])))
    return rows

def vector_stats(fits,g1,templates,knots,g1_values=None):
    result={k:float(v) for k,v in statistics(fits).items()}
    result.update({'within:'+k:float(v) for k,v in statistics(fits,'within_r2').items()})
    for m,fit in fits.items():
        result[m+':brier']=fit['brier'];result[m+':within_r2']=fit['within_r2']
        for i,label in enumerate(['gap_competitive','gap_clearly_worse','clock_competitive','eval100_competitive']):
            q=fit['contrast'][i];result[m+':'+label]=100*float(q[:-1]@fit['full']['beta']/q[-1]) if q[-1]>0 else np.nan
    for label in ['gap_competitive','gap_clearly_worse','clock_competitive']:
        result['difference:'+label]=result['MU:'+label]-result['MR:'+label]
    for r in revealed_roots(fits['MU'],templates,knots):result['Xr:'+str(r['cell'])]=r['Xr']
    result.update(outcome_statistics(g1,templates) if g1_values is None else g1_values)
    return result

def outcome_statistics(g1,templates):
    result={};er=exchange(g1,templates)
    for r in er:
        for field in ['X_w','X_eq']:result[f'{field}:{r["cell"]}:{r["rating_edge"]}:{r["f_to_move"]}']=r[field]
    for r in templates.to_dict('records'):
        z=pd.DataFrame([r]);p=g1.predict(z)[0]
        for kind in ['gap100','double_clock','eval100']:
            changed=counterfactual(z,kind);q=g1.predict(changed)[0]
            for j,field in enumerate(['win','draw','loss']):result[f'G1_APE:{r["cell"]}:{kind}:{field}']=float(q[j]-p[j])
    return result

def partial_statistics(store,weights=None):
    weights=np.ones(len(store.counts)) if weights is None else weights;H=np.einsum('b,bij->ij',weights,store.forms['full'],optimize=True)
    Htrain=np.einsum('b,bij->ij',weights,store.forms['train'],optimize=True);Htest=np.einsum('b,bij->ij',weights,store.forms['test'],optimize=True)
    test_n=float(weights@store.counts[:,1]);test_full=quadratic(Htest,solve(Htrain)['beta'])/test_n
    full=solve(H);meta=load(store.path/'META.json');out={}
    for block,indices in meta['blocks'].items():
        keep=[j for j in range(H.shape[0]) if j not in indices];restricted=solve(H[np.ix_(keep,keep)])
        out['partial_R2:'+block]=(restricted['sse']-full['sse'])/restricted['sse'] if restricted['sse']>0 else np.nan
        smaller=solve(Htrain[np.ix_(keep,keep)]);out['added_test_gain:'+block]=quadratic(Htest[np.ix_(keep,keep)],smaller['beta'])/test_n-test_full
    return out

def interval(values,alpha=.05):
    v=np.asarray(values,float)
    if not np.isfinite(v).all():
        # Unknown roots are retained, not conditionally dropped. Worst-case bounds.
        lo=np.where(np.isfinite(v),v,-np.inf);hi=np.where(np.isfinite(v),v,np.inf)
        return float(np.quantile(lo,alpha/2,method='inverted_cdf')),float(np.quantile(hi,1-alpha/2,method='inverted_cdf'))
    return tuple(map(float,np.quantile(v,[alpha/2,1-alpha/2])))

def eiv_reliability(x,weights,error_variance):
    """Weighted cross-cell reliability with a supplied centered error variance."""
    x=np.asarray(x,float);weights=np.asarray(weights,float);weights=weights/weights.sum()
    variance=float(weights@(x-weights@x)**2)
    return 1-error_variance/variance if variance>0 and np.isfinite(error_variance) else np.nan

def eiv_secondary(x,w,slope,xdraws,slopes):
    """Prespecified slope/reliability, conditional on the classical EIV assumptions.

    Full cross-cell Xw error covariance is estimated from G1 families, so shared
    G1 errors across cells are retained. The error variance is held fixed when
    applying the correction within the combined bootstrap, as a known-variance
    plug-in calculation. It does not correct correlation between Xr and Xw errors.
    """
    xdraws=np.asarray(xdraws,float);w=np.asarray(w,float);w=w/w.sum()
    error=np.nan
    if len(x)>=2 and len(xdraws)>=20 and np.isfinite(xdraws).all():
        # Xw repeats exactly for all ten block draws in a G1 family.
        sigma=np.cov(xdraws[::10],rowvar=False,ddof=1)
        error=float(w@np.diag(sigma)-w@sigma@w)
        error=max(0.,error)
    reliability=eiv_reliability(x,w,error)
    corrected=slope/reliability if np.isfinite(reliability) and reliability>0 else np.nan
    draws=[]
    for xx,ss in zip(xdraws,slopes):
        rr=eiv_reliability(xx,w,error)
        draws.append(ss/rr if np.isfinite(ss) and np.isfinite(rr) and rr>0 else np.nan)
    return dict(eiv_reliability=reliability,eiv_centered_error_variance=error,eiv_slope=corrected,eiv_slope_draws=np.array(draws))

def exchange_summary(point,replicates,templates,weight_file):
    array={k:np.array([r.get(k,np.nan) for r in replicates]) for k in point if k.startswith(('Xr:','X_w:'))}
    cells=[];excluded=[]
    for cc in templates.cell:
        k='Xr:'+str(cc);kw=f'X_w:{cc}:100:0';good=np.isfinite(array[k])&np.isfinite(array[kw])
        if np.isfinite(point[k]) and np.isfinite(point[kw]) and good.mean()>=.975:cells.append(int(cc))
        else:excluded.append(dict(cell=int(cc),resolved_share=float(good.mean())))
    # Freeze after the first 50 G1 draws, before outcome classification; includes both stages' variation.
    if Path(weight_file).exists():weights=load(weight_file)
    else:
        weights={}
        for cc in templates.cell:
            xr=array['Xr:'+str(cc)];xw=array[f'X_w:{cc}:100:0'];ok=np.isfinite(xr)&np.isfinite(xw)
            if ok.sum()>1:
                var=float(np.var(xr[ok],ddof=1)+np.var(xw[ok],ddof=1))
                weights[str(cc)]=1/var if var>1e-12 else None
        save(weight_file,weights)
    cells=[cc for cc in cells if weights.get(str(cc)) is not None]
    if not cells:return dict(R=np.nan,draws=np.full(len(replicates),np.nan),slope=np.nan,slope_draws=np.full(len(replicates),np.nan),intercept=np.nan,intercept_draws=np.full(len(replicates),np.nan),eiv_reliability=np.nan,eiv_centered_error_variance=np.nan,eiv_slope=np.nan,eiv_slope_draws=np.full(len(replicates),np.nan),status='unresolved',cells=[],excluded=excluded,coverage=0.)
    w=np.array([weights[str(cc)] for cc in cells]);xr=np.array([point[f'Xr:{cc}'] for cc in cells]);xw=np.array([point[f'X_w:{cc}:100:0'] for cc in cells])
    r=float(w@xr/(w@xw)) if w@xw>0 else np.nan
    a=np.column_stack([np.ones(len(cells)),xw]);coef=np.linalg.lstsq(a*np.sqrt(w)[:,None],xr*np.sqrt(w),rcond=None)[0]
    draws=[];slopes=[];intercepts=[];bad=0
    for j in range(len(replicates)):
        xx=np.array([array[f'X_w:{cc}:100:0'][j] for cc in cells]);yy=np.array([array[f'Xr:{cc}'][j] for cc in cells])
        if not np.isfinite(np.r_[xx,yy]).all() or w@xx<=0:draws.append(np.nan);slopes.append(np.nan);intercepts.append(np.nan);bad+=1
        else:
            draws.append(float(w@yy/(w@xx)));ab=np.column_stack([np.ones(len(cells)),xx]);bb=np.linalg.lstsq(ab*np.sqrt(w)[:,None],yy*np.sqrt(w),rcond=None)[0];intercepts.append(float(bb[0]));slopes.append(float(bb[1]))
    coverage=float(templates.loc[templates.cell.isin(cells),'N'].sum()/templates.N.sum())
    eiv=eiv_secondary(xw,w,float(coef[1]),np.column_stack([array[f'X_w:{cc}:100:0'] for cc in cells]),slopes)
    return dict(R=r,draws=np.array(draws),slope=float(coef[1]),slope_draws=np.array(slopes),intercept=float(coef[0]),intercept_draws=np.array(intercepts),
        status='unresolved' if bad/len(replicates)>.025 or not np.isfinite(r) or len(cells)<2 else 'resolved',cells=cells,excluded=excluded,coverage=coverage,invalid_fraction=bad/len(replicates),**eiv)

def monte_carlo_endpoints(values,families,resamples=1000,seed=SEED+123):
    """Resample G1 families with all ten paired block draws, never as independent G1 fits."""
    v=np.asarray(values,float);families=np.asarray(families);unique=np.unique(families);group=[np.flatnonzero(families==f) for f in unique]
    if not np.isfinite(v).all():return np.inf,np.inf
    rng=np.random.default_rng(seed);endpoints=[]
    for _ in range(resamples):
        ix=np.concatenate([group[j] for j in rng.integers(len(group),size=len(group))]);endpoints.append(np.quantile(v[ix],[.025,.975]))
    return tuple(np.std(endpoints,axis=0,ddof=1))

def decision_endpoints(point,records,exchange_info):
    families=[r['family'] for r in records];rules={
       'MRU:gain':(0.,),'D10':(0.,),'D25':(0.,),'R':(.8,1.25),
       'difference:gap_competitive':(-.10,.10),'difference:gap_clearly_worse':(-.05,.05),'difference:clock_competitive':(-.10,.10),
       'primeD10':(0.,),'primeD25':(0.,),'MRUprime:gain':(0.,)}
    rows=[];all_resolved=True
    for name,thresholds in rules.items():
        values=exchange_info['draws'] if name=='R' else [r['statistics'].get(name,np.nan) for r in records]
        low,high=interval(values);se_low,se_high=monte_carlo_endpoints(values,families)
        if name=='R' and exchange_info['status']=='unresolved':
            resolved=False
        else:resolved=all(np.isfinite(ep) and np.isfinite(se) and min(abs(ep-t) for t in thresholds)>2*se for ep,se in [(low,se_low),(high,se_high)])
        all_resolved &= resolved
        rows.append(dict(statistic=name,ci_low=low,ci_high=high,mcse_low=se_low,mcse_high=se_high,thresholds=list(thresholds),simulation_resolved=bool(resolved)))
    return rows,bool(all_resolved)

def sufficiency(bounds,simulation_ok=True,prefix=''):
    if bounds['MRUprime:gain' if prefix else 'MRU:gain'][0]<=0:return 'benchmark improvement unresolved'
    if not simulation_ok:return 'unresolved by simulation'
    if bounds[prefix+'D10'][1]<0:return 'approximately sufficient'
    if bounds[prefix+'D25'][0]>0:return 'insufficient estimated index'
    return 'intermediate'
def equivalence(ci,margin,simulation_ok=True):
    if not simulation_ok:return 'unresolved by simulation'
    lo,hi=ci;l,u=margin
    if lo>=l and hi<=u:return 'inside equivalence margin'
    if hi<l or lo>u:return 'entirely outside equivalence margin'
    return 'inconclusive'
