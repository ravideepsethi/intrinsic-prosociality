"""FWL and a full, cross-role account covariance; no diagonal-only contrasts."""
from .common import *
import math

def codes(a):return np.unique(a,return_inverse=True)[1]

def fe_rank(groups):
    if len(groups)==1:return int(groups[0].max()+1)
    if len(groups)!=2:raise ValueError('One or two FE dimensions supported')
    small,big=sorted(groups,key=lambda x:int(x.max()))
    ns=int(small.max()+1);nb=int(big.max()+1)
    first=np.full(nb,ns,np.int64);np.minimum.at(first,big,small)
    pairs=np.unique(first[big]*ns+small);parent=np.arange(ns)
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for e in pairs:
        i,j=divmod(int(e),ns);a,b=root(i),root(j)
        if a!=b:parent[a]=b
    components=len({root(i) for i in range(ns)})
    return ns+nb-components

def absorb(a,groups,tol=2e-11,max_iter=2000,compute_rank=True):
    out=np.array(a,float,order='F',copy=True);groups=[codes(g) for g in groups]
    for iteration in range(1,max_iter+1):
        change=0.
        for g in groups:
            n=np.bincount(g)
            for j in range(out.shape[1]):
                m=np.bincount(g,weights=out[:,j])/n
                change=max(change,float(np.max(np.abs(m))));out[:,j]-=m[g]
        if len(groups)==1 or change<tol:return out,iteration,fe_rank(groups) if compute_rank else None
    raise RuntimeError('Fixed effects did not converge; fit withheld')

def shared_covariance(c,actors,influence,parameters):
    """Exact inclusion-exclusion over unique sets of up to 3 accounts per row."""
    h=np.asarray(influence,float)
    if h.ndim==1:h=h[:,None]
    n,k=h.shape
    if parameters>=n:raise RuntimeError('No residual degrees of freedom')
    ids=np.sort(np.asarray(actors,np.int64),axis=1).copy()
    for j in (2,1):ids[ids[:,j]==ids[:,j-1],j]=-1
    ids=np.sort(ids,axis=1)
    table=dict(a=ids[:,0],b=ids[:,1],c=ids[:,2])
    table.update({f'u{j}':h[:,j] for j in range(k)})
    c.register('score_rows',pa.table(table))
    values=','.join(f'u{j}' for j in range(k))
    sums=','.join(f'sum(u{j}) s{j}' for j in range(k))
    products=','.join(f'coalesce(sum(s{i}*s{j}),0)' for i in range(k) for j in range(i,k))
    queries=[('id',f'SELECT a id,{values} FROM score_rows WHERE a>=0 UNION ALL SELECT b id,{values} FROM score_rows WHERE b>=0 UNION ALL SELECT c id,{values} FROM score_rows WHERE c>=0'),
      ('a,b',f'SELECT a,b,{values} FROM score_rows WHERE a>=0 AND b>=0 UNION ALL SELECT a,c b,{values} FROM score_rows WHERE a>=0 AND c>=0 UNION ALL SELECT b a,c b,{values} FROM score_rows WHERE b>=0 AND c>=0'),
      ('a,b,c',f'SELECT a,b,c,{values} FROM score_rows WHERE a>=0')]
    parts=[]
    try:
        for group,query in queries:
            row=c.execute(f'SELECT {products} FROM (SELECT {group},{sums} FROM ({query}) GROUP BY {group})').fetchone()
            v=np.zeros((k,k));p=0
            for i in range(k):
                for j in range(i,k):v[i,j]=v[j,i]=row[p];p+=1
            parts.append(v)
    finally:c.unregister('score_rows')
    return (parts[0]-parts[1]+parts[2])*(n-1)/(n-parameters)

def fit_ols(c,x,y,groups,actors,names,targets):
    if y.ndim==1:y=y[:,None]
    if not np.isfinite(x).all() or not np.isfinite(y).all():raise RuntimeError('Nonfinite regressors/outcomes; no silent row deletion')
    a,it,rank_fe=absorb(np.column_stack([x,y]),groups);k=x.shape[1];xr=a[:,:k];yr=a[:,k:]
    rms=np.sqrt(np.mean(xr*xr,axis=0));use=rms>1e-12
    info=dict(rows=len(x),fixed_effect_rank=rank_fe,absorb_iterations=it,dropped_constant_controls=[s for s,u in zip(names,use) if not u],
      covariance='shared_account_any_role_HC1; includes recipient, exposure opponent, later opponent; no date clusters',
      original_controls=names,targets=targets)
    if any(t in info['dropped_constant_controls'] for t in targets):return dict(info,status='TARGET_NO_VARIATION'),None
    names=[s for s,u in zip(names,use) if u];rms=rms[use];xr=np.ascontiguousarray(xr[:,use]);xr/=rms
    gram=xr.T@xr;ev=np.linalg.eigvalsh(gram);condition=float(ev[-1]/ev[0]) if ev[0]>0 else float('inf')
    info.update(controls=names,regressors=len(names),standardized_gram_condition=condition)
    if not np.isfinite(condition) or condition>1e10:return dict(info,status='COLLINEAR_NOT_ESTIMATED'),None
    inv=np.linalg.inv(gram);b=inv@(xr.T@yr);res=yr-xr@b
    ix=[names.index(t) for t in targets];derivative=(xr@inv[:,ix])/rms[ix]
    cov=[]
    for j in range(y.shape[1]):
        cov.append(shared_covariance(c,actors,derivative*res[:,j,None],len(names)+rank_fe))
    vif=np.diag(inv)*len(x)
    info.update(status='ESTIMATED',normal_equation_max=float(np.max(np.abs(xr.T@res))),
      variance_inflation_factors={t:float(vif[names.index(t)]) for t in targets},
      residual_stake_sd_rating_points={t:float(5*rms[names.index(t)]/np.sqrt(vif[names.index(t)])) for t in ('giver_cost_5','recipient_benefit_5') if t in names},
      covariance_min_eigenvalues=[float(np.linalg.eigvalsh(v).min()) for v in cov],
      historical_scores_and_potential_stakes_fixed=True)
    return info,dict(coefficients=b[ix]/rms[ix,None],covariances=cov,targets=targets)

def contrast(beta,v,weights,eligible=True):
    w=np.asarray(weights,float);estimate=float(w@beta);variance=float(w@v@w)
    r=dict(estimate_pp=100*estimate,variance_negative=variance<0,supported=False)
    if not eligible:r['inference_status']='INSUFFICIENT_SUPPORT';return r
    if not np.isfinite(variance) or variance<=0:r['inference_status']='NONPOSITIVE_VARIANCE_NOT_REPAIRED';return r
    se=math.sqrt(variance);r.update(supported=True,inference_status='nominal_large_sample',standard_error_pp=100*se,
      ci95_low_pp=100*(estimate-1.959963984540054*se),ci95_high_pp=100*(estimate+1.959963984540054*se),
      p_two_sided=math.erfc(abs(estimate/se)/math.sqrt(2)))
    return r

def holm(pvalues):
    p=np.array([v if v is not None and np.isfinite(v) else 1. for v in pvalues]);order=np.argsort(p)
    out=np.empty(len(p));last=0.
    for rank,j in enumerate(order):last=max(last,min(1.,float(p[j])*(len(p)-rank)));out[j]=last
    return out.tolist()
