"""Symmetric alternating-projection CG, verified against original FE means.

For orthogonal group-demeaning operators Pj, S=P1 P2 ... Pk ... P2 P1
is symmetric positive semidefinite. Solve (I-S) a=(I-S)v in its range;
v-a is the joint FE residual. No dense FE matrix or ridge penalty is used.
"""
from common import *
from scipy.sparse.linalg import LinearOperator,cg
import inspect

def encode(groups):
    return [np.unique(g,return_inverse=True)[1].astype(np.int32) for g in groups]

def peel(groups):
    keep=np.ones(len(groups[0]),bool);iterations=0
    while True:
        drop=np.zeros(len(keep),bool)
        for g in groups:
            counts=np.bincount(g[keep],minlength=int(g.max())+1)
            drop|=keep&(counts[g]<2)
        if not drop.any():return keep,iterations
        keep[drop]=False;iterations+=1
        if not keep.any():return keep,iterations

def absorb_column(v,groups,gate=1e-9,maxiter=4000,progress=None):
    den=[np.bincount(g).astype(float) for g in groups]
    scale=max(1.,float(np.max(np.abs(v),initial=0)));y=np.asarray(v,float)/scale
    active=[i for i,d in enumerate(den) if len(d)>1]
    if not active:active=[0]
    order=active+active[-2::-1]
    def cycle(x):
        z=np.array(x,copy=True)
        for i in order:
            g=groups[i];z-=np.bincount(g,weights=z,minlength=len(den[i]))[g]/den[i][g]
        return z
    def matvec(x):return x-cycle(x)
    op=LinearOperator((len(y),len(y)),matvec=matvec,rmatvec=matvec,dtype=float)
    b=matvec(y);iteration=[0];start=time.monotonic();last=[start]
    def callback(x):
        iteration[0]+=1
        if progress and time.monotonic()-last[0]>30:
            progress(iteration[0],time.monotonic()-start);last[0]=time.monotonic()
    kwargs=dict(maxiter=maxiter,callback=callback,atol=0.)
    kwargs['rtol' if 'rtol' in inspect.signature(cg).parameters else 'tol']=1e-12
    a,info=cg(op,b,**kwargs)
    z=(y-a)*scale
    # Absolute means in the original units, plus a short exact-polishing pass.
    error=float('inf')
    for j in range(21):
        error=max(float(np.max(np.abs(np.bincount(g,weights=z)/d))) for g,d in zip(groups,den))
        if np.isfinite(z).all() and error<=gate:break
        z=cycle(z)
    require(np.isfinite(z).all() and error<=gate,
        f'FE projection failed: cg_stop={info}, iterations={iteration[0]}, max_group_mean={error:.3g}, required={gate}; no estimate exported')
    return z,dict(iterations=iteration[0],cg_stop=int(info),max_group_mean=error,gate=gate,seconds=time.monotonic()-start)

def solve(W,y):
    # Normal equations involve only the small residualized regressor matrix.
    k=W.shape[1];xx=np.zeros((k,k));xy=np.zeros(k)
    for lo in range(0,len(y),100000):
        x=np.asarray(W[lo:lo+100000]);v=y[lo:lo+100000];xx+=x.T@x;xy+=x.T@v
    scale=np.sqrt(np.maximum(np.diag(xx),0));scale=np.where(scale>1e-12,scale,1.)
    z=xx/scale[:,None]/scale[None,:];val,Q=np.linalg.eigh((z+z.T)/2)
    good=val>max(1e-10,float(val.max(initial=0))*1e-10)
    inverse=(Q[:,good]/val[good])@Q[:,good].T/scale[:,None]/scale[None,:]
    return dict(beta=inverse@xy,inverse=inverse,scale=scale,null=Q[:,~good],rank=int(good.sum()),
                residual_sd=np.sqrt(np.maximum(np.diag(xx),0)/max(1,len(y))),eigenvalues=val)

def estimable(fit,w):
    z=np.asarray(w)/fit['scale']
    return bool(np.linalg.norm(z@fit['null'])<=1e-7*max(1e-12,np.linalg.norm(z)))

def covariance_join(a,b):
    """Cross-model covariance from matching sorted cluster IDs; bounded temporary memory."""
    ids_a,inf_a=a;ids_b,inf_b=b
    _,ia,ib=np.intersect1d(ids_a,ids_b,assume_unique=True,return_indices=True)
    out=np.zeros((inf_a.shape[1],inf_b.shape[1]))
    for lo in range(0,len(ia),50000):
        out+=inf_a[ia[lo:lo+50000]].T@inf_b[ib[lo:lo+50000]]
    return out
