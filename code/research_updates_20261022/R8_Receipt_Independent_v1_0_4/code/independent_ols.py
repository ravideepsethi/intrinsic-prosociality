"""Analytic cell-FE elimination and dense nuisance Schur complement.

Independent of R7's iterative FE absorption. Redundant nuisance directions
are resolved with an explicitly recorded eigenbasis; no ridge is used.
"""
import numpy as np

def require(condition,message):
    if not condition:raise RuntimeError(message)

def cross(left,right):
    # Avoid the BLAS self-transpose fast path and record independently summed moments.
    return np.einsum('ni,nj->ij',left,right,optimize=False)

def project(x,raw,groups):
    require(len(groups)==3,'Independent audit needs the original three FE groups')
    require(x.ndim==2 and x.shape[1]==7,'Independent audit needs NH controls')
    n=len(x);codes=[np.unique(g,return_inverse=True)[1] for g in groups]
    sizes=[int(c.max())+1 for c in codes];cell,day,hour=codes;nc,nd,nh=sizes
    counts=[np.bincount(c,minlength=k).astype(float) for c,k in zip(codes,sizes)]
    require(all((v>0).all() for v in counts),'Empty FE group')
    width=x.shape[1]+len(raw);sums=[np.zeros((k,width)) for k in sizes];moment=np.zeros((width,width))
    for start in range(0,n,32768):
        stop=min(n,start+32768);block=np.column_stack([x[start:stop]]+[v[start:stop] for v in raw])
        require(np.isfinite(block).all(),'Nonfinite independent audit input; no rows omitted')
        moment+=cross(block,block)
        for c,k,total in zip(codes,sizes,sums):
            for j in range(width):total[:,j]+=np.bincount(c[start:stop],weights=block[:,j],minlength=k)
    cd=np.bincount(cell*nd+day,minlength=nc*nd).reshape(nc,nd).astype(float)
    ch=np.bincount(cell*nh+hour,minlength=nc*nh).reshape(nc,nh).astype(float)
    dh=np.bincount(day*nh+hour,minlength=nd*nh).reshape(nd,nh).astype(float)
    cmean=sums[0]/counts[0][:,None]
    after_cell=moment-sums[0].T@cmean
    dd=np.diag(counts[1])-cd.T@(cd/counts[0][:,None])
    hh=np.diag(counts[2])-ch.T@(ch/counts[0][:,None])
    dayhour=dh-cd.T@(ch/counts[0][:,None])
    daydense=sums[1]-cd.T@cmean;hourdense=sums[2]-ch.T@cmean
    k=x.shape[1]
    nuisance=np.block([[dd,dayhour,daydense[:,:k]],
        [dayhour.T,hh,hourdense[:,:k]],
        [daydense[:,:k].T,hourdense[:,:k].T,after_cell[:k,:k]]])
    rhs=np.vstack([daydense[:,k:],hourdense[:,k:],after_cell[:k,k:]])
    scale=np.sqrt(np.maximum(np.diag(nuisance),1.))
    normalized=nuisance/scale[:,None]/scale[None,:]
    normalized=(normalized+normalized.T)/2
    eigen,vectors=np.linalg.eigh(normalized);cut=max(float(eigen.max()),1.)*1e-12
    require(float(eigen.min())>=-100*cut,'Independent nuisance Gram is non-PSD; no repair applied')
    use=eigen>cut
    beta=((vectors[:,use]/eigen[use])@(vectors[:,use].T@(rhs/scale[:,None])))/scale[:,None]
    normal_error=float(np.max(np.abs(nuisance@beta-rhs)))
    require(normal_error<2e-8*max(1.,float(np.max(np.abs(rhs)))),'Independent nuisance normal equations failed')
    target_cell=cmean[:,k:]-(cd@beta[:nd]+ch@beta[nd:nd+nh]+sums[0][:,:k]@beta[nd+nh:])/counts[0][:,None]
    result=np.empty((n,len(raw)),dtype=float,order='F')
    for start in range(0,n,32768):
        stop=min(n,start+32768);block=np.column_stack([v[start:stop] for v in raw])
        result[start:stop]=block-target_cell[cell[start:stop]]-beta[:nd][day[start:stop]]-beta[nd:nd+nh][hour[start:stop]]-x[start:stop]@beta[nd+nh:]
    means=[]
    for c,k,count in zip(codes,sizes,counts):
        means.append(max(float(np.max(np.abs(np.bincount(c,weights=result[:,j],minlength=k)/count))) for j in range(result.shape[1])))
    require(max(means)<2e-8,'Independent FE orthogonality certificate failed')
    control_error=float(np.max(np.abs(cross(x,result))))
    require(control_error<2e-8*max(1.,float(n)),'Independent NH orthogonality certificate failed')
    diag=dict(method='analytic cell elimination plus day/hour/NH Schur complement',rows=n,groups=sizes,
        nuisance_columns=len(nuisance),nuisance_rank=int(use.sum()),redundant_nuisance_directions=int((~use).sum()),
        normalized_eigenvalue_cutoff=cut,smallest_retained_eigenvalue=float(eigen[use].min()),
        nuisance_normal_equation_max_error=normal_error,FE_max_group_means=means,NH_normal_equation_max_error=control_error,
        no_rows_removed=True,no_ridge=True,trait_columns_removed=0,raw_Gram_summation='einsum optimize=False in 32768-row blocks')
    return result,diag
