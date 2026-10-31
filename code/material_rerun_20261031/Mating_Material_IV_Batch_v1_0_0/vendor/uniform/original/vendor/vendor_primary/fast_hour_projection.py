"""Equivalent sparse FE basis for the nearly nested last-move-hour model.

Date and hour-of-week dummies are replaced by differences from a reference
category within each last-move hour. Those differences are usually zero.
One cell dummy per start month is redundant with the date dummies and omitted.
The original FE space is preserved. No observations, controls or FE dimensions
are changed; all original group means are checked after projection.
"""
import time
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import lsmr


def basis(groups):
    if len(groups)!=4:
        raise ValueError('Expected cell, start date, start hour-of-week, last-move hour')
    n=len(groups[0]);codes=[];counts=[];values=[]
    for g in groups:
        value,code,count=np.unique(g,return_inverse=True,return_counts=True)
        if len(code)!=n:raise ValueError('FE row count mismatch')
        values.append(value);codes.append(code);counts.append(count)
    cell,date,week,hour=codes;nh=len(counts[-1])
    # Every cell contains exactly one start month. A month indicator is a sum
    # of date dummies, so the most frequent cell in that month is redundant.
    months=np.asarray(groups[1],dtype='datetime64[D]').astype('datetime64[M]').astype(np.int64)
    low=np.full(len(counts[0]),np.iinfo(np.int64).max,dtype=np.int64)
    high=np.full(len(counts[0]),np.iinfo(np.int64).min,dtype=np.int64)
    np.minimum.at(low,cell,months);np.maximum.at(high,cell,months)
    if not np.array_equal(low,high):raise ValueError('A cell crosses exposure months')
    keep=np.ones(len(counts[0]),bool)
    for month in np.unique(low):
        ix=np.flatnonzero(low==month);keep[ix[np.argmax(counts[0][ix])]]=False
    mapping=np.full(len(keep),-1,dtype=np.int64);mapping[keep]=np.arange(keep.sum())
    rows=[np.arange(n)];cols=[hour.copy()];data=[np.ones(n)]
    use=keep[cell];rows.append(np.flatnonzero(use));cols.append(nh+mapping[cell[use]]);data.append(np.ones(use.sum()))
    offset=nh+int(keep.sum());changes=[]
    for code,count in [(date,counts[1]),(week,counts[2])]:
        cross=sparse.coo_matrix((np.ones(n),(hour,code)),shape=(nh,len(count))).tocsr()
        reference=np.asarray(cross.argmax(axis=1)).ravel()
        del cross
        ref=reference[hour];use=code!=ref;rr=np.flatnonzero(use)
        rows.extend([rr,rr]);cols.extend([offset+code[use],offset+ref[use]])
        data.extend([np.ones(len(rr)),-np.ones(len(rr))]);changes.append(len(rr));offset+=len(count)
    rr=np.concatenate(rows);cc=np.concatenate(cols);vv=np.concatenate(data)
    del rows,cols,data
    norm=np.sqrt(np.bincount(cc,weights=vv*vv,minlength=offset));norm[norm==0]=1.
    A=sparse.coo_matrix((vv/norm[cc],(rr,cc)),shape=(n,offset)).tocsr()
    return A,codes,counts,dict(rows=n,columns=offset,nonzeros=A.nnz,
        omitted_redundant_cell_dummies=int((~keep).sum()),time_difference_rows=changes)


def absorb_last_move(v,groups,tol=1e-10,log=None):
    start=time.monotonic();log=log or (lambda message:None)
    if v.dtype!=np.float64 or not v.flags.owndata or not v.flags.f_contiguous:
        raise ValueError('Expected owned Fortran float64 buffer')
    if not np.isfinite(v).all():raise ValueError('Nonfinite projection input')
    scale=max(1.,float(np.max(np.abs(v))));threshold=tol*scale
    A,codes,counts,info=basis(groups)
    log('Last-move-hour FE: equivalent sparse contrasts; '+str(info))
    iterations=[];worst=0.;total_initial=0.;total_final=0.
    for k in range(v.shape[1]):
        target=v[:,k];initial=float(target@target);total_initial+=initial;nit=0
        for refinement in range(3):
            fit=lsmr(A,target,atol=1e-14,btol=1e-14,conlim=1e14,maxiter=10000)
            target-=A@fit[0];nit+=int(fit[2])
            error=max(float(np.max(np.abs(np.bincount(c,weights=target,minlength=len(ct))/ct)))
                      for c,ct in zip(codes,counts))
            if np.isfinite(error) and error<=threshold:break
        if not np.isfinite(target).all() or error>threshold:
            raise RuntimeError('Last-move-hour original-FE orthogonality check failed: '+str(error))
        final=float(target@target)
        if final>initial+1e-10*max(initial,np.finfo(float).tiny):
            raise RuntimeError('Last-move-hour projection increased sum of squares')
        total_final+=final;iterations.append(nit);worst=max(worst,error)
        elapsed=(time.monotonic()-start)/60
        log(f'Last-move-hour FE column {k+1}/{v.shape[1]} complete; iterations={nit}; '
            f'max original-group mean={error:.3e}; elapsed={elapsed:.1f} min')
    diag=dict(info,solver='sparse_reference_contrasts_LSMR',status='CONVERGED',iterations=max(iterations),
        iterations_by_column=iterations,maximum_group_mean=worst,
        absolute_tolerance_original_units=threshold,no_rows_removed=True,no_ridge=True,
        original_FE_space_preserved=True,elapsed_seconds=time.monotonic()-start,
        final_to_initial_sum_of_squares=total_final/total_initial if total_initial else 0.)
    return v,diag
