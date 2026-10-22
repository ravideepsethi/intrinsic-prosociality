"""Cross-checked cross-products; independent scalar reductions validate BLAS."""
from __future__ import annotations
import numpy as np
from scipy.linalg.blas import dsyrk
from threadpoolctl import threadpool_info


def matvec(X,b):
    return np.einsum('ij,j->i',X,b,optimize=False)


def _blas_gram(X):
    U=dsyrk(1.,np.asarray(X,dtype=np.float64,order='F'),trans=1,lower=0)
    U=np.triu(U)
    return U+np.triu(U,1).T


def _error(X,G,diag,probes,reference):
    scale=np.sqrt(np.maximum(diag,0))
    diag_error=float(np.max(np.abs(np.diag(G)-diag)/np.maximum(diag,1.)))
    gv=np.einsum('ij,jk->ik',G,probes,optimize=False)
    energy=np.sqrt(np.maximum(np.einsum('ij,ij->j',probes,reference,optimize=False),0))
    denom=np.maximum(scale[:,None]*energy[None,:],1.)
    return max(diag_error,float(np.max(np.abs(gv-reference)/denom)))


def gram(X,audit=None):
    """Validate every diagonal and three deterministic projection identities."""
    if X.ndim!=2 or not np.isfinite(X).all():raise ValueError('Nonfinite Gram input')
    k=X.shape[1];rng=np.random.default_rng(104729+k)
    probes=rng.choice([-1.,1.],size=(k,3))/np.sqrt(max(k,1))
    diag=np.einsum('ij,ij->j',X,X,optimize=False)
    projected=np.einsum('ij,jk->ik',X,probes,optimize=False)
    reference=np.einsum('ij,ik->jk',X,projected,optimize=False)
    G=_blas_gram(X);before=_error(X,G,diag,probes,reference)
    fallback=before>1e-10
    if fallback:G=np.einsum('ni,nj->ij',X,X,optimize=False)
    after=_error(X,G,diag,probes,reference)
    if after>1e-10 or not np.isfinite(G).all():
        raise ValueError(f'Independent Gram validation failed: original={before:.3g}, final={after:.3g}')
    if audit is not None:
        audit['gram_calls']=audit.get('gram_calls',0)+1
        audit['gram_fallbacks']=audit.get('gram_fallbacks',0)+int(fallback)
        audit['max_initial_gram_error']=max(audit.get('max_initial_gram_error',0.),before)
        audit['max_final_gram_error']=max(audit.get('max_final_gram_error',0.),after)
    return G


def check_centering(Z,starts,audit):
    totals=np.add.reduceat(Z,starts,axis=0)
    absolute=np.add.reduceat(np.abs(Z),starts,axis=0)
    error=float(np.max(np.abs(totals)/np.maximum(absolute,1.)))
    audit['max_centering_error']=max(audit.get('max_centering_error',0.),error)
    if error>1e-9:raise ValueError(f'Within-chooser centering failed: {error:.3g}')


def backend():
    return threadpool_info()


def positive_weight_nullspace(unweighted,weighted):
    """Positive account weights cannot create variation in an exact null direction."""
    diagonal=np.diag(unweighted);scale=np.zeros(len(diagonal));active=diagonal>1e-12
    scale[active]=1/np.sqrt(diagonal[active])
    H=scale[:,None]*unweighted*scale[None,:]
    eig,V=np.linalg.eigh((H+H.T)/2)
    null=V[:,np.abs(eig)<max(float(eig.max())*1e-12,1e-14)]
    directions=scale[:,None]*null
    residual=np.einsum('ij,jk->ik',weighted,directions,optimize=False)
    variance=np.einsum('ij,ij->j',directions,residual,optimize=False)
    bound=np.einsum('ij,i,ij->j',directions,np.diag(weighted),directions,optimize=False)
    error=float(np.max(np.abs(variance)/np.maximum(bound,1e-12),initial=0))
    if error>1e-9:raise ValueError(f'Positive-weight nullspace consistency failed: {error:.6g}')
    return {'null_directions_checked':null.shape[1],'max_relative_variance':error,'threshold':1e-9}
