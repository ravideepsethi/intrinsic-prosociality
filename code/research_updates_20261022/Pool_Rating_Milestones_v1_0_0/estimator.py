"""Two-pass exact within-chooser OLS with chooser-clustered covariance."""
from __future__ import annotations
import json
import numpy as np
from scipy import sparse
from scipy.stats import t as student_t
from fe_core import groups, solve
from milestone_model import specifications, select, design, common_design, target_names, PROFILE_REFERENCE


def subset(f, keep):
    return {k:v[keep] for k,v in f.items()}


def prepare_block(f, spec, common):
    keep=select(f,spec); original=subset(f,keep)
    if not len(original['y']): return original,None,None
    g,n,A=groups(original); retained=n[g]>=2
    if not retained.any(): return original,None,None
    small=subset(original,retained)
    shared=(common[0][keep][retained],common[1])
    return original,small,shared


class Moment:
    def __init__(self, spec, empty):
        self.spec=spec
        X,self.C,Z,self.names=design(empty,spec)
        p=X.shape[1];q=Z.shape[1]
        self.S=np.zeros((p,p));self.b=np.zeros(p)
        self.N=self.G=self.all_N=self.all_G=self.events=self.all_events=0
        self.pos_n=np.zeros(q,dtype=np.int64);self.pos_y=np.zeros(q,dtype=np.int64)
        self.pos_groups=np.zeros(q,dtype=np.int64);self.switchers=np.zeros(q,dtype=np.int64)
        self.months=np.zeros((q,24),dtype=np.int64)

    def add(self,original,f,common):
        self.all_N+=len(original['y']);self.all_events+=int(original['y'].sum())
        self.all_G+=len(np.unique(original['chooser']))
        if f is None: return
        X,_,Z,names=design(f,self.spec,common)
        if names!=self.names: raise RuntimeError('Design changed across blocks')
        g,n,A=groups(f);y=f['y'].astype(float);sums=A@X
        scaled=sparse.diags(1/np.sqrt(n))@sums
        self.S+=(X.T@X-scaled.T@scaled).toarray()
        self.b+=np.asarray(X.T@y).ravel()-np.asarray(sums.T@((A@y)/n)).ravel()
        self.N+=len(y);self.G+=len(n);self.events+=int(y.sum())
        exposure=(A@Z).toarray()
        self.pos_n+=np.asarray(Z.sum(axis=0)).ravel().astype(np.int64)
        self.pos_y+=np.asarray(Z.T@y).ravel().astype(np.int64)
        self.pos_groups+=(exposure>0).sum(axis=0)
        self.switchers+=((exposure>0)&(exposure<n[:,None])).sum(axis=0)
        for month in range(24):
            self.months[:,month]+=np.asarray(Z[f['month']==month].sum(axis=0)).ravel().astype(np.int64)

    def merge(self,other):
        for k in ('S','b','N','G','all_N','all_G','events','all_events','pos_n','pos_y','pos_groups','switchers','months'):
            setattr(self,k,getattr(self,k)+getattr(other,k))


def init_moments(empty):
    return {s['key']:Moment(s,empty) for s in specifications()}


def save_moments(path, moments):
    out={};meta={}
    for key,m in moments.items():
        meta[key]={k:getattr(m,k) for k in ('N','G','all_N','all_G','events','all_events')}
        for k in ('S','b','pos_n','pos_y','pos_groups','switchers','months'):
            out[key+'__'+k]=getattr(m,k)
    out['metadata']=np.array(json.dumps(meta))
    np.savez_compressed(path,**out)


def load_moments(path,empty):
    out=init_moments(empty)
    with np.load(path,allow_pickle=False) as z:
        meta=json.loads(str(z['metadata']))
        for key,m in out.items():
            for k,v in meta[key].items(): setattr(m,k,v)
            for k in ('S','b','pos_n','pos_y','pos_groups','switchers','months'):
                setattr(m,k,z[key+'__'+k].copy())
    return out


def fit(moments):
    models={}
    for key,m in moments.items():
        solution=solve(m.S,m.b,m.C)
        q=len(m.C)
        solution.update(estimates=m.C@solution['beta'],projection=solution['bread']@m.C.T,
                        meat=np.zeros((q,q)),score_sum=np.zeros(q))
        models[key]=solution
    return models


def score(f,models):
    common=common_design(f)
    for spec in specifications():
        _,small,shared=prepare_block(f,spec,common)
        if small is None:continue
        X,_,_,_=design(small,spec,shared)
        g,n,A=groups(small);model=models[spec['key']]
        e=small['y']-np.asarray(X@model['beta']).ravel()
        e-=np.asarray(A@e).ravel()[g]/n[g]
        scores=np.asarray((A@X.multiply(e[:,None]))@model['projection'])
        model['meat']+=scores.T@scores;model['score_sum']+=scores.sum(axis=0)


def holm(values):
    p=np.asarray(values,float);order=np.argsort(p,kind='stable')
    adjusted=np.maximum.accumulate((len(p)-np.arange(len(p)))*p[order])
    out=np.empty_like(p);out[order]=np.minimum(adjusted,1)
    return out


def finish(moments,models,min_rows=1000,min_switchers=100):
    rows=[];diagnostics=[];covariances={}
    for key,m in moments.items():
        model=models[key];N,G=m.N,m.G;rank=model['rank'];q=len(m.C)
        df=N-G-rank
        correction=G/(G-1)*(N-1)/df if G>1 and df>0 else None
        cov=model['meat']*correction if correction is not None else np.full((q,q),np.nan)
        critical=float(student_t.ppf(.975,G-1)) if G>1 else np.nan
        covariances[key+'__covariance']=cov
        covariances[key+'__estimate']=model['estimates']
        covariances[key+'__estimable']=model['identified']
        names=target_names(m.spec)
        for j,name in enumerate(names):
            reference=m.spec['mode']=='profile' and j==PROFILE_REFERENCE
            reasons=[]
            if not model['identified'][j]:reasons.append('not_estimable')
            if correction is None:reasons.append('insufficient_residual_degrees_of_freedom')
            if m.pos_n[j]<min_rows:reasons.append('fewer_than_1000_treated_or_bin_rows')
            if N-m.pos_n[j]<min_rows:reasons.append('fewer_than_1000_other_rows')
            if m.switchers[j]<min_switchers:reasons.append('fewer_than_100_switching_choosers')
            if np.count_nonzero(m.months[j])<6:reasons.append('fewer_than_6_months')
            if m.spec['mode']=='profile' and (m.pos_n[PROFILE_REFERENCE]<min_rows or m.switchers[PROFILE_REFERENCE]<min_switchers):
                reasons.append('insufficient_reference_support')
            if correction is not None and cov[j,j]<-1e-12: raise RuntimeError('Negative contrast variance')
            status='estimated' if not reasons else ';'.join(reasons)
            if reference and not reasons:status='reference'
            r=dict(specification=key,term=name,status=status,source_local_rows=m.all_N,
                   source_local_choosers=m.all_G,estimation_rows=N,chooser_clusters=G,
                   singleton_rows_dropped=m.all_N-N,kind_draws=m.events,
                   treated_or_bin_rows=int(m.pos_n[j]),treated_or_bin_grants=int(m.pos_y[j]),
                   treated_or_bin_choosers=int(m.pos_groups[j]),switching_choosers=int(m.switchers[j]),
                   represented_months=int(np.count_nonzero(m.months[j])),
                   treated_or_bin_rate_percent=100*m.pos_y[j]/m.pos_n[j] if m.pos_n[j] else None,
                   other_rate_percent=100*(m.events-m.pos_y[j])/(N-m.pos_n[j]) if N>m.pos_n[j] else None,
                   estimate_pp=None,cluster_se_pp=None,ci95_low_pp=None,ci95_high_pp=None,
                   p_two_sided=None,p_holm_primary=None,p_holm_secondary=None,
                   exploratory=True,within_design_rank=rank,CR1_factor=correction,
                   threshold=name.split('_')[-1] if m.spec['mode']=='by_threshold' else None)
            if not reasons:
                est=float(model['estimates'][j]);se=float(np.sqrt(max(cov[j,j],0)))
                p=float(2*student_t.sf(abs(est/se),G-1)) if se else (1. if est==0 else 0.)
                r.update(estimate_pp=100*est,cluster_se_pp=100*se,ci95_low_pp=100*(est-critical*se),
                         ci95_high_pp=100*(est+critical*se),p_two_sided=None if reference else p)
            rows.append(r)
        diagnostics.append(dict(specification=key,N=N,G=G,source_N=m.all_N,source_G=m.all_G,
                                rank=rank,absorbed_chooser_intercepts=G,residual_df=df,
                                CR1_factor=correction,condition_number=model['condition_number'],
                                maximum_abs_contrast_score_sum=float(np.max(np.abs(model['score_sum']))),
                                maximum_estimability_projection_error=float(np.max(model['projection_error'])),
                                terms=m.names))
    # Freeze the family even if a cell is unsupported: such attempts get p=1
    # in Holm arithmetic, while their reported p-value stays missing.
    for key,col in [('primary','p_holm_primary'),('secondary','p_holm_secondary')]:
        family=[r for r in rows if (r['specification']=='hundreds_primary' if key=='primary'
                else r['specification'] not in ('hundreds_primary','hundreds_distance_profile'))]
        adj=holm([r['p_two_sided'] if r['p_two_sided'] is not None else 1 for r in family])
        for r,p in zip(family,adj):r[col]=float(p);r[col+'_family_size']=len(family)
    return rows,diagnostics,covariances
