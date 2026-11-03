"""Weighted FE projection and the retained matched-design cluster estimators.

The four-FE projection uses a sparse, scaled dummy Gram system. Every column
must pass an independent weighted-group-mean check; a sparse least-squares
fallback handles difficult connected components. No fixed effects are dropped.
"""
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import cg, lsmr
from result_common import require,log

def sparse_absorb(matrix,weights,groups,tolerance=1e-10):
    z=np.array(matrix,dtype=float,copy=True,order='F');w=np.asarray(weights,float)
    require(z.shape[0]==len(w) and np.isfinite(z).all() and np.isfinite(w).all() and (w>0).all(),'Invalid weighted projection')
    codes=[np.unique(g,return_inverse=True)[1] for g in groups]
    sizes=[int(c.max())+1 for c in codes]
    sums=[np.bincount(c,weights=w,minlength=n) for c,n in zip(codes,sizes)]
    offsets=np.cumsum([0]+sizes);n=len(w);sw=np.sqrt(w)
    # Normalized weighted indicator columns have unit norm, including rare hours.
    rows=np.tile(np.arange(n),len(groups))
    columns=np.concatenate([c+offsets[k] for k,c in enumerate(codes)])
    values=np.concatenate([sw/np.sqrt(s[c]) for c,s in zip(codes,sums)])
    A=sparse.coo_matrix((values,(rows,columns)),shape=(n,int(offsets[-1]))).tocsr()
    del rows,columns,values
    gram=(A.T@A).tocsr();worst=0.;max_steps=0
    for j in range(z.shape[1]):
        col=z[:,j]
        for refinement in range(3):
            rhs=A.T@(sw*col)
            beta,info=cg(gram,rhs,rtol=1e-12,atol=1e-13,maxiter=8000)
            if info!=0 or not np.isfinite(beta).all():
                beta=lsmr(A,sw*col,atol=1e-14,btol=1e-14,maxiter=12000)[0]
            col-=A@beta/sw
            error=max(float(np.max(np.abs(np.bincount(c,weights=w*col,minlength=len(s))/s))) for c,s in zip(codes,sums))
            if error<=tolerance:break
        require(error<=tolerance,f'Four-FE projection failed its independent check, column {j}: {error}')
        worst=max(worst,error);max_steps=max(max_steps,refinement+1)
        if (j+1)%5==0 or j+1==z.shape[1]:log(f'Hour projection: {j+1}/{z.shape[1]} columns; max weighted group mean {worst:.2g}')
    return z,max_steps,worst

def variance_from_influence(influence,group):
    _,ix=np.unique(group,return_inverse=True);s=np.bincount(ix,weights=influence)
    return float(s@s),len(s)

def fit(y,D,X,names,w,groups,cluster,row_ids,common,core,binary=True,hour_cluster=None):
    y=np.asarray(y,float);D=np.asarray(D,float);w=np.asarray(w,float)
    require(len(y)>=100 and np.unique(D).size==2 and np.isfinite(y).all() and (w>0).all(),'Insufficient matched model support')
    if len(groups)==4:z,it,error=sparse_absorb(np.column_stack([y,D,X]),w,groups)
    else:z,it,error=core.weighted_absorb(np.column_stack([y,D,X]),w,groups)
    yy=z[:,0];xx=z[:,1:];k=xx.shape[1];gram=np.zeros((k,k));rhs=np.zeros(k)
    for first in range(0,len(y),131072):
        sl=slice(first,first+131072);wx=xx[sl]*w[sl,None]
        gram+=xx[sl].T@wx;rhs+=wx.T@yy[sl]
    model=common.solve(gram,rhs)
    require(common.estimable(np.eye(k)[0],model)[0],'Receipt contrast is not identified')
    u=yy-xx@model['beta'];influence=w*u*(xx@model['bread'][0])
    var,G=variance_from_influence(influence,cluster)
    require(G>1 and len(y)>model['rank'],'Insufficient cluster/sample degrees of freedom')
    correction=G/(G-1)*(len(y)-1)/(len(y)-model['rank']);scale=100 if binary else 1
    chooser=common.inference(float(model['beta'][0])*scale,var*correction*scale**2)
    principal=dict(chooser);covariance='exposure chooser CR1';extras={}
    if hour_cluster is not None:
        vh,H=variance_from_influence(influence,hour_cluster)
        # Same account/hour intersections are subtracted once (two-way CR0).
        _,both=np.unique(np.column_stack([cluster,hour_cluster]),axis=0,return_inverse=True)
        vp,_=variance_from_influence(influence,both);vv=var+vh-vp
        require(vv>=0,'Negative two-way variance; no estimate is silently substituted')
        principal=common.inference(float(model['beta'][0])*scale,vv*scale**2)
        covariance='exposure chooser OR exposure last-move UTC hour, CR0'
        extras=dict(hour_clusters=H,se_chooser_CR1=chooser['se'],p_chooser_CR1=chooser['p'],se_chooser_or_exposure_hour_CR0=principal['se'])
    require(principal['se'] is not None,'Undefined receipt uncertainty')
    treated=D>.5
    return dict(principal,**extras,rows=len(y),clusters=G,treated_rows=int(treated.sum()),control_rows=int((~treated).sum()),
        weighted_control_mean=float(np.average(y[~treated],weights=w[~treated]))*scale,
        weighted_treated_mean=float(np.average(y[treated],weights=w[treated]))*scale,
        units='percentage points' if binary else 'log points',covariance_description=covariance,
        chooser_CR1_correction=correction,rank=model['rank'],control_names=list(names),
        coefficient_names=['received_mercy']+list(names),coefficients=(model['beta']*scale).tolist(),
        absorption_iterations=int(it),absorption_max_weighted_mean=float(error),
        sample_sha256=__import__('hashlib').sha256(np.asarray(row_ids,dtype='<i8').tobytes()).hexdigest())

def conditional_censor_mask(reached,anchor,delta,next_disconnection,complete):
    """Keep reached choices no later than the next disconnection.

    The frozen Arrow loader fills null integers with -1. Floating nullable
    timestamps can instead arrive as NaN. A present timestamp is finite and
    positive, matching the completed producer's censored_outcome convention.
    This conditional sensitivity retains ties; the zero-coded primary does not.
    """
    anchor=np.asarray(anchor,float);delta=np.asarray(delta,float)
    nxt=np.asarray(next_disconnection,float);complete=np.asarray(complete,bool)
    reached=np.asarray(reached,bool)
    require(anchor.ndim==1 and all(x.shape==anchor.shape for x in (delta,nxt,complete,reached)),
            'Censoring arrays have different shapes')
    eligible=complete&reached;later=anchor+delta
    present=np.isfinite(nxt)&(nxt>0)
    require(np.all(np.isfinite(anchor[complete])&(anchor[complete]>0)),
            'Invalid exposure anchor in a complete censoring window')
    require(np.all(np.isfinite(delta[eligible])&(delta[eligible]>0)&(delta[eligible]<=90*86400000)),
            'Invalid first-choice time in a reached complete window')
    require(np.all(nxt[complete&present]>anchor[complete&present]),
            'Next disconnection must follow the exposure anchor')
    return eligible&(~present|(later<=nxt))
