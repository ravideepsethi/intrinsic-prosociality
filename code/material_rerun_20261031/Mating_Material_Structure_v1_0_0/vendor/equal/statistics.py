"""Chooser-level sufficient statistics for the binary FE-only desert contrast."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

LABELS=('original_FE','inverse_count_FE','equal_chooser')
PAIRS=((1,0),(2,0),(2,1))
Z95=1.959963984540054


def inputs(frame):
    f=frame.f.to_numpy(dtype=float)
    l=frame.l.to_numpy(dtype=float)
    n=f+l
    both=(f>0)&(l>0)
    w=np.divide(f*l,n,out=np.zeros(len(n)),where=n>0)
    activity_adjusted=np.divide(w,n,out=np.zeros(len(n)),where=n>0)
    d=frame.a.to_numpy(dtype=float)[both]/f[both]-frame.b.to_numpy(dtype=float)[both]/l[both]
    return n,both,w,activity_adjusted,d


def interval(estimate,se):
    if se is None:return dict(se_pp=None,ci_low_pp=None,ci_high_pp=None,p_normal=None)
    p=math.erfc(abs(estimate/se)/math.sqrt(2)) if se>0 else (1.0 if estimate==0 else 0.0)
    return dict(se_pp=100*se,ci_low_pp=100*(estimate-Z95*se),ci_high_pp=100*(estimate+Z95*se),p_normal=p)


def estimate(d,weights,scope='all_state_varying_choosers'):
    """Joint chooser-cluster sandwich; paired comparisons retain covariance."""
    d=np.asarray(d,dtype=float)
    weights=np.asarray(weights,dtype=float)
    G=len(d)
    if weights.shape!=(G,3) or G<1 or not np.isfinite(weights).all() or not np.isfinite(d).all():
        raise ValueError('Invalid chooser statistics')
    if np.any(weights<=0):raise ValueError('All three estimators must retain every state-varying chooser')
    normalized=weights/weights.sum(axis=0)
    coefficients=normalized.T@d
    influence=normalized*(d[:,None]-coefficients)
    covariance=(G/(G-1))*(influence.T@influence) if G>1 else None
    models=[]
    for j,label in enumerate(LABELS):
        se=math.sqrt(max(0,float(covariance[j,j]))) if covariance is not None else None
        models.append(dict(scope=scope,estimator=label,choosers=G,estimate_pp=100*float(coefficients[j]),
                           effective_choosers=1/float(normalized[:,j]@normalized[:,j]),
                           **interval(float(coefficients[j]),se)))
    differences=[]
    for j,k in PAIRS:
        change=float(coefficients[j]-coefficients[k])
        # Direct paired influence avoids subtractive loss in covariance algebra.
        score=influence[:,j]-influence[:,k]
        se=math.sqrt(G/(G-1)*float(score@score)) if G>1 else None
        differences.append(dict(scope=scope,comparison=LABELS[j]+'_minus_'+LABELS[k],choosers=G,
                                estimate_pp=100*change,**interval(change,se)))
    return pd.DataFrame(models),pd.DataFrame(differences),covariance


def activity_distribution(counts,weights,population):
    """Fractional allocation of activity ties; no selection on outcomes/IDs."""
    counts=np.asarray(counts,dtype=np.int64)
    weights=np.asarray(weights,dtype=float)
    if len(counts)==0 or np.any(counts<=0) or weights.shape!=(len(counts),3):
        raise ValueError('Invalid activity distribution')
    values,inverse,frequency=np.unique(counts,return_inverse=True,return_counts=True)
    grouped=np.column_stack([np.bincount(inverse,weights=weights[:,j]) for j in range(3)])
    upper=np.cumsum(frequency,dtype=np.int64)
    lower=upper-frequency
    G=len(counts)
    totals=weights.sum(axis=0)
    N=int(counts.sum())
    def band(start,end,**labels):
        allocated=np.maximum(0,np.minimum(upper,end)-np.maximum(lower,start))
        fraction=allocated/frequency
        included=allocated>0
        shares=(fraction@grouped)/totals
        return dict(population=population,**labels,chooser_equivalents=float(allocated.sum()),
                    min_opportunities=int(values[included].min()),max_opportunities=int(values[included].max()),
                    opportunity_share=float((allocated@values)/N),
                    original_FE_weight_share=float(shares[0]),inverse_count_FE_weight_share=float(shares[1]),
                    equal_chooser_weight_share=float(shares[2]),tie_rule='equal fractional allocation within activity-count ties')
    deciles=[band(j*G/10,(j+1)*G/10,decile=j+1) for j in range(10)]
    top=[band((1-p)*G,G,top_fraction=p) for p in (.001,.01,.05,.10)]
    for key in ('opportunity_share','original_FE_weight_share','inverse_count_FE_weight_share','equal_chooser_weight_share'):
        if not np.isclose(sum(r[key] for r in deciles),1,atol=1e-12):raise RuntimeError('Decile shares do not conserve: '+key)
    return pd.DataFrame(deciles),pd.DataFrame(top)


def activity_terciles(n,d,weights):
    # Empirical cutoffs keep identical activity counts together. Group sizes
    # need not be equal when a cutoff has many ties.
    cutoffs=np.quantile(n,[1/3,2/3],method='inverted_cdf').astype(np.int64)
    groups=np.searchsorted(cutoffs,n,side='left')
    estimates=[];contrasts=[];support=[]
    for j,name in enumerate(('light','medium','heavy')):
        mask=groups==j
        if not mask.any():
            support.append(dict(activity_group=name,choosers=0,opportunities=0,min_opportunities=None,max_opportunities=None))
            continue
        result,pairs,_=estimate(d[mask],weights[mask],scope=name)
        estimates.append(result);contrasts.append(pairs)
        support.append(dict(activity_group=name,choosers=int(mask.sum()),opportunities=int(n[mask].sum()),
                            min_opportunities=int(n[mask].min()),max_opportunities=int(n[mask].max())))
    definition=dict(ranking_population='same state-varying choosers as primary comparison',
                    activity='competitive plus clearly-worse opportunities',
                    lower_cutoff_inclusive=int(cutoffs[0]),middle_cutoff_inclusive=int(cutoffs[1]),
                    tie_rule='keep identical opportunity counts together; group sizes may differ',
                    outcome_based_selection=False)
    combined_estimates=pd.DataFrame([row for table in estimates for row in table.to_dict('records')])
    combined_contrasts=pd.DataFrame([row for table in contrasts for row in table.to_dict('records')])
    return combined_estimates,combined_contrasts,pd.DataFrame(support),definition


def granting_rates(frame):
    rows=[]
    for name,n,k in [('all_pool_opportunities',frame.n,frame.k),
                     ('competitive_or_clearly_worse',frame.f+frame.l,frame.a+frame.b),
                     ('competitive_only',frame.f,frame.a)]:
        positive=n>0;n=n[positive].to_numpy(dtype=float);k=k[positive].to_numpy(dtype=float)
        rows.append(dict(sample=name,choosers=len(n),opportunities=int(n.sum()),kind_draws=int(k.sum()),
                         ever_grant_choosers=int((k>0).sum()),ever_grant_chooser_pct=float((k>0).mean()*100),
                         opportunity_grant_rate_pct=float(k.sum()/n.sum()*100),
                         equal_chooser_mean_grant_rate_pct=float((k/n).mean()*100),
                         note='Observed ever-grant status is descriptive only; no regression selects on granting.'))
    return pd.DataFrame(rows)
