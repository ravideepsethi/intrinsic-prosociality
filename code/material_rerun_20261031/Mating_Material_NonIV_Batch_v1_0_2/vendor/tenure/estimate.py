"""Sparse LPM; exact one-way absorption and cluster sandwich for several targets."""
import numpy as np
from scipy import sparse, stats
from common import require

def fit(d,targets,cats,nums,absorb,cluster):
    n0=len(d['y'])
    if n0<3:return {'status':'INSUFFICIENT_ROWS','eligible_n':n0}
    a={k:np.asarray(v) for k,v in d.items()}
    _,g0=np.unique(a[absorb].astype(str),return_inverse=True);ct=np.bincount(g0)
    mask=ct[g0]>1
    a={k:v[mask] for k,v in a.items()};n=len(a['y'])
    if n<3:return {'status':'INSUFFICIENT_NON_SINGLETON_ROWS','eligible_n':n0}
    _,g=np.unique(a[absorb].astype(str),return_inverse=True);G=int(g.max())+1
    ng=np.bincount(g).astype(float);y=a['y'].astype(float)
    require(np.isin(y,[0,1]).all(),'Nonbinary outcome')
    cols=[];names=[];levels={}
    for s in targets+nums:
        v=a[s].astype(float);require(np.isfinite(v).all(),'Nonfinite covariate '+s)
        cols.append(sparse.csr_matrix(v[:,None]));names.append(s)
    for s in cats:
        lv,c=np.unique(a[s].astype(str),return_inverse=True);levels[s]=lv.tolist()
        if len(lv)>1:
            ix=c>0;cols.append(sparse.csr_matrix((np.ones(ix.sum()),(np.flatnonzero(ix),c[ix]-1)),shape=(n,len(lv)-1)))
            names.extend(s+':'+v for v in lv[1:])
    X=sparse.hstack(cols,format='csr');D=sparse.csr_matrix((np.ones(n),(g,np.arange(n))),shape=(G,n))
    sx=D@X;mx=sx.multiply((1/ng)[:,None]);sy=np.bincount(g,weights=y)
    A=(X.T@X-sx.T@mx).toarray();A=(A+A.T)/2
    b=np.asarray(X.T@y-sx.T@(sy/ng)).ravel();active=np.diag(A)>1e-10;ix=np.flatnonzero(active)
    base=dict(eligible_n=n0,n=n,absorbed_groups=G,dropped_singletons=n0-n,grants=int(y.sum()),targets=targets,controls=dict(cats=cats,nums=nums),categorical_levels=levels)
    if not len(ix):return dict(**base,status='NO_WITHIN_VARIATION')
    scale=np.sqrt(np.diag(A)[ix]);Z=A[np.ix_(ix,ix)]/np.outer(scale,scale)
    ev,V=np.linalg.eigh(Z);require(ev.min()>-1e-7,'Indefinite within cross product')
    keep=ev>max(1e-11,ev.max()*1e-10);rank=int(keep.sum())
    Bsmall=(V[:,keep]/ev[keep])@V[:,keep].T/np.outer(scale,scale)
    B=np.zeros_like(A);B[np.ix_(ix,ix)]=Bsmall;beta=B@b
    residual=y-X@beta-(sy/ng-mx@beta)[g]
    _,cl=np.unique(a[cluster].astype(str),return_inverse=True);C=int(cl.max())+1
    df=n-G-rank
    if C<2 or df<1:return dict(**base,status='INSUFFICIENT_DF')
    influences=[];identified=[]
    for j in range(len(targets)):
        ok=active[j]
        if ok:ok=np.sum(V[np.flatnonzero(ix==j)[0],~keep]**2)<1e-8
        identified.append(bool(ok));v=np.asarray(X@B[:,j]-np.asarray(mx@B[:,j])[g])*residual
        influences.append(np.bincount(cl,weights=v,minlength=C))
    S=np.vstack(influences);cov=S@S.T*C/(C-1)*(n-1)/df
    critical=stats.t.ppf(.975,C-1);est={}
    for j,s in enumerate(targets):
        if not identified[j]:est[s]={'status':'NOT_IDENTIFIED'};continue
        se=float(np.sqrt(max(0,cov[j,j])));v=float(beta[j]);p=float(2*stats.t.sf(abs(v/se),C-1)) if se>0 else None
        est[s]=dict(status='ESTIMATED',coefficient_pp=100*v,se_pp=100*se,ci_low_pp=100*(v-critical*se),ci_high_pp=100*(v+critical*se),p_value=p)
    target=a[targets[0]].astype(float);ts=np.bincount(g,weights=target)
    supp={}
    if np.isin(target,[0,1]).all():
        w=ts*(ng-ts)/ng;ss=w.sum()
        supp=dict(treatment_switchers=int((w>0).sum()),switchers_with_outcome_variation=int(((w>0)&(sy>0)&(sy<ng)).sum()),never_granter_identifying_weight_share=float(w[sy==0].sum()/ss) if ss else None)
    maxres=float(np.max(np.abs(np.bincount(g,weights=residual))))
    require(maxres<1e-5,'Absorbed residuals do not sum to zero')
    return dict(**base,status='ESTIMATED',estimates=est,target_covariance_pp2=(10000*cov).tolist(),clusters=C,residual_df=df,within_rank=rank,max_abs_group_residual_sum=maxres,support=supp,se='CR1, full rank including absorbed effects; cluster='+cluster)

def sqlfit(db,query,targets,cats,nums,absorb='chooser',cluster='chooser'):
    cols=list(dict.fromkeys(['y',absorb,cluster]+targets+cats+nums))
    d=db.execute('SELECT '+','.join('"'+s+'"' for s in cols)+' FROM ('+query+')').fetchnumpy()
    return fit(d,targets,cats,nums,absorb,cluster)
