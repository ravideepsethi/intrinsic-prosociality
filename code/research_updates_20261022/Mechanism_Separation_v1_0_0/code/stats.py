"""Exact conditional likelihood, chooser FE LPM, and cluster inference.

Conditional likelihood uses log elementary symmetric polynomials with reverse
automatic differentiation of the recursion. No rare-event/Poisson substitute.
"""
import numpy as np
from numba import njit
from scipy.optimize import minimize
from scipy.special import expit

def groups(ids):
    ids=np.asarray(ids);_,g=np.unique(ids,return_inverse=True)
    order=np.argsort(g,kind='stable');g=g[order]
    starts=np.r_[0,np.flatnonzero(g[1:]!=g[:-1])+1].astype(np.int64)
    ends=np.r_[starts[1:],len(g)].astype(np.int64)
    return order,starts,ends

@njit(cache=True)
def conditional_kernel(eta,y,starts,ends):
    residual=np.zeros(len(y));values=np.zeros(len(starts))
    for group in range(len(starts)):
        lo=starts[group];hi=ends[group];n=hi-lo;m=int(np.sum(y[lo:hi]));sign=1.
        if m==0 or m==n:continue
        if m>n//2:m=n-m;sign=-1.
        z=sign*eta[lo:hi];z=z-np.mean(z)
        F=np.full((n+1,m+1),-np.inf);F[:,0]=0.
        for t in range(1,n+1):
            for k in range(1,min(t,m)+1):
                F[t,k]=np.logaddexp(F[t-1,k],F[t-1,k-1]+z[t-1])
        target=y[lo:hi] if sign>0 else 1-y[lo:hi]
        values[group]=np.dot(target,z)-F[n,m]
        adj=np.zeros(m+1);adj[m]=1.;incl=np.zeros(n)
        for t in range(n,0,-1):
            old=np.zeros(m+1)
            old[0]+=adj[0]
            for k in range(1,min(t,m)+1):
                take=np.exp(F[t-1,k-1]+z[t-1]-F[t,k])
                incl[t-1]+=adj[k]*take
                old[k-1]+=adj[k]*take
                old[k]+=adj[k]*(1-take)
            adj=old
        residual[lo:hi]=sign*(target-incl)
    return values,residual

def conditional_value(X,y,ids,beta):
    order,starts,ends=groups(ids);xx=np.asarray(X)[order];yy=np.asarray(y,float)[order]
    return conditional_kernel(xx@beta,yy,starts,ends)[0].sum()

def demean(X,ids):
    a=np.asarray(X,float);one=a.ndim==1
    if one:a=a[:,None]
    _,g=np.unique(ids,return_inverse=True);n=np.bincount(g)
    sums=np.zeros((len(n),a.shape[1]));np.add.at(sums,g,a)
    z=a-sums[g]/n[g,None]
    return z[:,0] if one else z

def cr1(n,g,p):
    return g/(g-1)*(n-1)/(n-g-p) if g>1 and n>g+p else np.nan

def cluster_scores(X,residual,starts):
    return np.add.reduceat(X*residual[:,None],starts,axis=0)

def lpm(X,y,ids):
    order,st,en=groups(ids);X=np.asarray(X,float)[order];y=np.asarray(y,float)[order];ids=np.asarray(ids)[order]
    keep=np.repeat(en-st>=2,en-st);X=X[keep];y=y[keep];ids=ids[keep]
    if len(y)<2:return {'status':'INSUFFICIENT_ROWS'}
    order,st,en=groups(ids);X=demean(X,ids);Y=demean(y,ids)
    gram=X.T@X;scale=np.sqrt(np.maximum(np.diag(gram),1e-30));h=gram/scale[:,None]/scale[None,:]
    v,u=np.linalg.eigh((h+h.T)/2);ok=v>max(v.max(initial=0)*1e-10,1e-12)
    inv=(u[:,ok]/v[ok])@u[:,ok].T/scale[:,None]/scale[None,:]
    beta=inv@(X.T@Y);r=Y-X@beta;scores=cluster_scores(X,r,st)
    cov=inv@(scores.T@scores)@inv*cr1(len(y),len(st),int(ok.sum()))
    identified=np.sum(u[:,~ok]**2,axis=1)<1e-7
    return dict(status='ESTIMATED',beta=beta,cov=cov,identified=identified,rank=int(ok.sum()),
                n=len(y),accounts=len(st),grants=int(y.sum()),residual=r,
                df_resid=len(y)-len(st)-int(ok.sum()))

def fit_conditional(X,y,ids,bounds=None,start=None,inference=True,maxiter=250):
    X=np.asarray(X,float);y=np.asarray(y,float);ids=np.asarray(ids)
    if not np.isfinite(X).all() or not np.isin(y,[0,1]).all():raise ValueError('Nonfinite design or nonbinary outcome')
    if len(y)==0:return dict(status='NO_OUTCOME_VARIATION',n=0,accounts=0,full_n=0,full_accounts=0)
    order,st,en=groups(ids);X=X[order];y=y[order];ids=ids[order]
    sy=np.add.reduceat(y,st);ng=en-st;valid=(sy>0)&(sy<ng);keep=np.repeat(valid,ng)
    full_n=len(y);full_g=len(st);X=X[keep];y=y[keep];ids=ids[keep]
    p=X.shape[1]
    if len(y)==0:return dict(status='NO_OUTCOME_VARIATION',n=0,accounts=0,full_n=full_n,full_accounts=full_g)
    _,st,en=groups(ids);m=np.minimum(np.add.reduceat(y,st),en-st-np.add.reduceat(y,st))
    cells=(en-st+1)*(m+1)
    if cells.max(initial=0)>50000000:raise RuntimeError('Exact conditional recursion exceeds 50M cells for one chooser; no accounts silently dropped')
    # Remove only within-group constant columns; retain weak directions for support reporting.
    wx=demean(X,ids);sd=np.sqrt(np.mean(wx*wx,axis=0));active=sd>1e-10
    del wx
    if not active.any():return dict(status='NO_WITHIN_VARIATION',n=len(y),accounts=len(st))
    scale=sd[active];Z=np.ascontiguousarray(X[:,active]/scale)
    bb=[(None,None)]*p if bounds is None else bounds
    bnds=[bb[k] for k in np.flatnonzero(active)]
    # Bounds are signs/zero only; positive rescaling leaves their meaning unchanged.
    initial=np.zeros(len(scale)) if start is None else np.asarray(start)[active]*scale
    norm=max(1,len(st))
    def fun(b):
        ll,r=conditional_kernel(Z@b,y,st,en)
        return -ll.sum()/norm,-Z.T@r/norm
    opt=minimize(fun,initial,jac=True,method='L-BFGS-B',bounds=bnds,
                 options=dict(maxiter=maxiter,ftol=1e-12,gtol=2e-7,maxls=40,maxcor=20))
    objective,gradient=fun(opt.x);pg=gradient.copy()
    for j,(lo,hi) in enumerate(bnds):
        if lo is not None and opt.x[j]<=lo+1e-7:pg[j]=min(pg[j],0)
        if hi is not None and opt.x[j]>=hi-1e-7:pg[j]=max(pg[j],0)
    converged=bool(opt.success and np.max(abs(pg),initial=0)<2e-5)
    beta=np.zeros(p);beta[active]=opt.x/scale
    boundary=np.zeros(p,bool)
    for j,k in enumerate(np.flatnonzero(active)):
        lo,hi=bnds[j];boundary[k]=(lo is not None and opt.x[j]<=lo+1e-5) or (hi is not None and opt.x[j]>=hi-1e-5)
    cov=np.full((p,p),np.nan);identified=np.zeros(p,bool);rank=None;condition=None
    if inference and converged:
        H=np.empty((len(scale),len(scale)))
        for j in range(len(scale)):
            delta=2e-4*(1+abs(opt.x[j]));b1=opt.x.copy();b2=opt.x.copy();b1[j]+=delta;b2[j]-=delta
            H[:,j]=(fun(b1)[1]-fun(b2)[1])/(2*delta)*norm
        H=(H+H.T)/2;v,u=np.linalg.eigh(H);ok=v>max(v.max(initial=0)*1e-9,1e-9)
        inv=(u[:,ok]/v[ok])@u[:,ok].T;rank=int(ok.sum())
        condition=float(v.max()/v[ok].min()) if rank else np.inf
        _,r=conditional_kernel(Z@opt.x,y,st,en);score=cluster_scores(Z,r,st)
        factor=len(st)/(len(st)-1)*(len(y)-1)/(len(y)-rank) if len(st)>1 and len(y)>rank else np.nan
        cv=inv@(score.T@score)@inv*factor
        cov[np.ix_(active,active)]=cv/scale[:,None]/scale[None,:]
        identified[active]=np.sum(u[:,~ok]**2,axis=1)<1e-6
    return dict(status='ESTIMATED' if converged else 'OPTIMIZER_NOT_CONVERGED',beta=beta,cov=cov,
                identified=identified,boundary=boundary,rank=rank,condition=condition,
                n=len(y),accounts=len(st),grants=int(y.sum()),full_n=full_n,full_accounts=full_g,
                loglik=-objective*norm,iterations=int(opt.nit),gradient_max=float(np.max(abs(pg),initial=0)),
                message=str(opt.message),switcher_ids=np.unique(ids))

def account_intercepts(offset,y,ids,pseudo_count=20.):
    """Explicit additional baseline model, trained only on the supplied outcomes."""
    unique,g=np.unique(ids,return_inverse=True);n=np.bincount(g);s=np.bincount(g,weights=y)
    base=np.clip(np.mean(y),1e-7,1-1e-7);target=(s+pseudo_count*base)/(n+pseudo_count)
    lo=np.full(len(n),-60.);hi=np.full(len(n),60.)
    for _ in range(70):
        mid=(lo+hi)/2;actual=np.bincount(g,weights=expit(mid[g]+offset))/n
        low=actual<target;lo=np.where(low,mid,lo);hi=np.where(low,hi,mid)
    return unique,(lo+hi)/2,base

def residualize(X,Z,ids):
    x=demean(X,ids);z=demean(Z,ids)
    return x-z@np.linalg.lstsq(z,x,rcond=1e-10)[0] if z.shape[1] else x

def lpm_stream(d,builder,block_size=50000):
    """Two passes over complete chooser blocks, no census-size dense design."""
    d=d.sort_values('chooser',kind='stable').reset_index(drop=True)
    ids=d.chooser.to_numpy();starts=np.r_[0,np.flatnonzero(ids[1:]!=ids[:-1])+1];ends=np.r_[starts[1:],len(d)]
    slices=[];lo=0
    for hi in ends:
        if hi-lo>=block_size:slices.append((lo,int(hi)));lo=int(hi)
    if lo<len(d):slices.append((lo,len(d)))
    S=b=None;n=g=grants=0;names=None
    for lo,hi in slices:
        part=d.iloc[lo:hi];ct=part.groupby('chooser').chooser.transform('size');part=part[ct>=2]
        if not len(part):continue
        X,names=builder(part);X=demean(X,part.chooser);Y=demean(100*part.y.to_numpy(float),part.chooser)
        if S is None:S=np.zeros((X.shape[1],X.shape[1]));b=np.zeros(X.shape[1])
        S+=X.T@X;b+=X.T@Y;n+=len(part);g+=part.chooser.nunique();grants+=int(part.y.sum())
    if S is None:return dict(status='INSUFFICIENT_ROWS'),[]
    scale=np.sqrt(np.maximum(np.diag(S),1e-30));H=S/scale[:,None]/scale[None,:]
    v,u=np.linalg.eigh((H+H.T)/2);ok=v>max(v.max(initial=0)*1e-10,1e-12)
    inv=(u[:,ok]/v[ok])@u[:,ok].T/scale[:,None]/scale[None,:];beta=inv@b;meat=np.zeros_like(S)
    for lo,hi in slices:
        part=d.iloc[lo:hi];ct=part.groupby('chooser').chooser.transform('size');part=part[ct>=2]
        if not len(part):continue
        X,_=builder(part);X=demean(X,part.chooser);Y=demean(100*part.y.to_numpy(float),part.chooser)
        st=np.r_[0,np.flatnonzero(np.diff(part.chooser.to_numpy())!=0)+1]
        score=cluster_scores(X,Y-X@beta,st);meat+=score.T@score
    cov=inv@meat@inv*cr1(n,g,int(ok.sum()))
    return dict(status='ESTIMATED',beta=beta,cov=cov,identified=np.sum(u[:,~ok]**2,axis=1)<1e-7,
                rank=int(ok.sum()),n=n,accounts=g,grants=grants),names
