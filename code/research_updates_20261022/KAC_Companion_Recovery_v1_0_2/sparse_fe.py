"""Stable rectangular least-squares absorption, with exact FE-cell compression.

Unlike v1.0.1, never form the singular normal system for the numerical solve.
Within an identical FE tuple, the weighted mean is sufficient for fitting FE
coefficients. The within-tuple residual is retained in the original rows.
"""
import hashlib,json,os
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import lsmr

LAST_DIAGNOSTIC={}
CHECKPOINT_ROOT=None
MODEL_KEY=None

def configure(root,key):
    global CHECKPOINT_ROOT,MODEL_KEY
    CHECKPOINT_ROOT=Path(root);MODEL_KEY=key

def array_hash(a):
    a=np.ascontiguousarray(a)
    h=hashlib.sha256();h.update(str(a.dtype).encode());h.update(str(a.shape).encode())
    h.update(memoryview(a).cast('B'));return h.hexdigest()

def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.partial')
    tmp.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n');os.replace(tmp,path)

def absorb(matrix,weights,groups,tolerance=1e-10,relative=False):
    global LAST_DIAGNOSTIC
    A=np.asarray(matrix,dtype=float);w=np.asarray(weights,dtype=float)
    if A.ndim!=2 or len(w)!=len(A) or not np.isfinite(A).all() or not np.isfinite(w).all() or np.any(w<=0):
        raise ValueError('Invalid FE matrix or weights')
    codes=[np.unique(g,return_inverse=True)[1] for g in groups]
    if not codes or any(len(g)!=len(A) for g in codes):raise ValueError('Invalid FE group lengths')
    tuples,inverse=np.unique(np.column_stack(codes),axis=0,return_inverse=True)
    cw=np.bincount(inverse,weights=w,minlength=len(tuples))
    den=[np.bincount(g,weights=w) for g in codes];dims=[len(d) for d in den]
    offsets=np.cumsum([0]+dims)
    # Remove only exactly nested FEs from the solve, retaining their validation.
    active=[]
    for i,di in enumerate(dims):
        nested=False
        for j,dj in enumerate(dims):
            if i==j or dj<di or (dj==di and j>i):continue
            pairs=np.unique(tuples[:,[j,i]],axis=0)
            if len(pairs)==dj:nested=True;break
        if not nested:active.append(i)
    adims=[dims[i] for i in active];ao=np.cumsum([0]+adims)
    adiag=np.concatenate([den[i] for i in active]);invdiag=1/np.sqrt(adiag)
    m=len(tuples)
    row=np.repeat(np.arange(m),len(active))
    col=np.column_stack([tuples[:,i]+ao[j] for j,i in enumerate(active)]).ravel()
    val=np.repeat(np.sqrt(cw),len(active))*invdiag[col]
    D=sparse.coo_matrix((val,(row,col)),shape=(m,int(ao[-1]))).tocsr()
    del row,col,val
    gate=tolerance*(max(1.,float(np.abs(A).max())) if relative else 1.)
    identity=dict(model_key=MODEL_KEY,matrix_sha256=array_hash(A),weight_sha256=array_hash(w),
        tuple_sha256=array_hash(tuples),inverse_sha256=array_hash(inverse),gate=gate,active=active,
        algorithm='rectangular_lsmr_v2')
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    folder=CHECKPOINT_ROOT/key[:20] if CHECKPOINT_ROOT else None
    if folder:
        folder.mkdir(parents=True,exist_ok=True);write_json(folder/'IDENTITY.json',identity)
    result=A.copy();iters=[];errors=[];reused=0;diagnostics=[]
    for column in range(A.shape[1]):
        means=np.bincount(inverse,weights=w*A[:,column],minlength=m)/cw
        center=float(np.average(A[:,column],weights=w))
        scale=max(1.,float(np.max(np.abs(means-center))))
        b=(means-center)*np.sqrt(cw)/scale
        coef=np.zeros(D.shape[1]);total=0;from_cache=False
        cp=folder/f'column_{column:03d}.npz' if folder else None
        meta=folder/f'column_{column:03d}.json' if folder else None
        if cp and cp.is_file() and meta.is_file():
            record=json.loads(meta.read_text())
            if record['identity']!=key or hashlib.sha256(cp.read_bytes()).hexdigest()!=record['sha256']:
                raise RuntimeError('Damaged FE-column checkpoint')
            with np.load(cp,allow_pickle=False) as z:coef=z['coef']
            if coef.shape!=(D.shape[1],) or not np.isfinite(coef).all():raise RuntimeError('Invalid FE-column cache')
            total=record['iterations'];from_cache=True
        err=float('inf');last=None
        for stage,limit in enumerate((0,500,2000,8000,20000)):
            if stage:
                # Restart on the residual RHS: compatible with older SciPy,
                # and no singular normal equations even in refinement.
                remaining=b-D@coef
                last=lsmr(D,remaining,atol=1e-14,btol=1e-14,conlim=0.,maxiter=limit)
                coef+=last[0];total+=int(last[2])
            fitted=center+(D@coef)*scale/np.sqrt(cw)
            r=A[:,column]-fitted[inverse]
            group_means=[np.bincount(g,weights=w*r,minlength=n)/d for g,n,d in zip(codes,dims,den)]
            err=max(float(np.max(np.abs(v))) for v in group_means)
            if np.isfinite(r).all() and err<=gate:break
            if from_cache:raise RuntimeError('Cached FE column failed original orthogonality gate')
        detail=dict(column=column,iterations=total,group_mean_residual=err,gate=gate,
            lsmr_stop=int(last[1]) if last else None,lsmr_condition=float(last[6]) if last else None,
            reused=from_cache)
        diagnostics.append(detail)
        if not np.isfinite(r).all() or err>gate:
            if folder:
                write_json(folder/'FAILURE.json',detail)
                # Algebraic diagnostics only; no game/account IDs or timestamp labels.
                gram=(D.T@D).tocoo()
                np.savez_compressed(folder/'failed_system.npz',row=gram.row,col=gram.col,value=gram.data,
                    shape=np.asarray(gram.shape),rhs=D.T@b,diagonal=adiag,cell_weight=cw,
                    gate=np.asarray(gate),scale=np.asarray(scale),candidate=coef)
            raise RuntimeError(f'Rectangular FE projection did not pass: column={column}, mean={err:.3e}, gate={gate:.3e}; column checkpoints preserved')
        result[:,column]=r
        if from_cache:reused+=1
        elif cp:
            tmp=cp.with_suffix('.partial.npz');np.savez_compressed(tmp,coef=coef);os.replace(tmp,cp)
            write_json(meta,dict(identity=key,sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),iterations=total,**{k:v for k,v in detail.items() if k!='iterations'}))
        iters.append(total);errors.append(err)
    LAST_DIAGNOSTIC=dict(method='rectangular_LSMR_exact_FE_tuple_compression',tolerance=gate,
        max_weighted_group_mean=max(errors),iterations_by_column=iters,levels=dims,
        exactly_nested_groups_removed=[i for i in range(len(groups)) if i not in active],
        original_rows=len(A),unique_FE_tuples=m,rectangular_nnz=D.nnz,
        ridge=0.,rows_dropped=0,all_original_FE_levels_checked=True,reused_columns=reused,columns=diagnostics)
    if folder:
        write_json(folder/'SUCCESS.json',LAST_DIAGNOSTIC)
        (folder/'FAILURE.json').unlink(missing_ok=True);(folder/'failed_system.npz').unlink(missing_ok=True)
    return result,max(iters),max(errors)

def weighted_absorb(matrix,weights,fixed_effects,*,tolerance=1e-10,maximum_iterations=2000):
    return absorb(matrix,weights,fixed_effects,tolerance)

def unweighted_absorb(a,groups,tol=1e-10,max_iter=1000):
    z,it,_=absorb(a,np.ones(len(a)),groups,tol,relative=True)
    return z,it
