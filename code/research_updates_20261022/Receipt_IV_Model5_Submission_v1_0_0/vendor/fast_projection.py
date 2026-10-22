"""Parallel independent-column FE projection, with the v100 certificates."""
from fast_bootstrap import *
import concurrent.futures as cf
import r7_memory as algebra
import rebuild_models as disk
import threading

def project(v,groups,width,root=None):
    n,p=v.shape;plans=[algebra._plan(g,n) for g in groups]
    disk_backed=isinstance(v,np.memmap);write_lock=threading.Lock()
    maximum=max(1.,max(float(np.max(np.abs(v[:,k]))) for k in range(p)))
    tolerance=1e-10*maximum
    threads=min(p,projection_threads(n,disk_backed))
    require(threads>=1,'Invalid FE thread count')
    log(f'FE projection: {threads} parallel columns, {n:,} rows')
    def column(k):
        # Columns are disjoint writable views; all FE grouping plans are shared
        # read-only. Each thread owns its two n-length work arrays.
        y=np.array(v[:,k],copy=True) if disk_backed else v[:,k]
        work=np.empty(n);shift=np.empty(n)
        energy0=float(y@y);previous=energy0
        for it in range(1,1001):
            largest=0.
            for plan in plans:
                means=algebra._group_means(y,plan,work)
                require(np.isfinite(means).all(),'Nonfinite FE group mean')
                largest=max(largest,float(np.abs(means).max()))
                np.take(means,plan[0],out=shift);y-=shift
            energy=float(y@y)
            require(np.isfinite(energy) and energy<=previous+1e-10*max(energy0,np.finfo(float).tiny),
                    'FE projection increased squared norm')
            previous=energy
            if largest<=tolerance:
                check=max(float(np.max(np.abs(algebra._group_means(y,plan,work)))) for plan in plans)
                if check<=tolerance:
                    if disk_backed:
                        # All other workers use private columns, so flushing
                        # and releasing this mapping cannot evict their work.
                        with write_lock:v[:,k]=y;disk.release_pages(v)
                    return it,check
        raise RuntimeError('FE orthogonality not attained in 1,000 iterations')
    with cf.ThreadPoolExecutor(max_workers=threads) as pool:diagnostics=list(pool.map(column,range(p)))
    del plans;gc.collect()
    if disk_backed:
        k=p-width;gram=np.zeros((k,k));cross=np.zeros((k,width))
        for lo in range(0,n,65536):
            x=np.asarray(v[lo:lo+65536,width:]);y=np.asarray(v[lo:lo+65536,:width])
            gram+=x.T@x;cross+=x.T@y
        beta=np.linalg.pinv(gram,rcond=1e-12)@cross
        result=disk.disk_matrix(Path(root)/'residual.dat',n,width)
        for lo in range(0,n,65536):result[lo:lo+65536]=v[lo:lo+65536,:width]-v[lo:lo+65536,width:]@beta
        disk.release_pages(result);disk.release_pages(v)
    else:
        x=v[:,width:];gram=x.T@x
        beta=np.linalg.pinv(gram,rcond=1e-12)@(x.T@v[:,:width]);del x
        for lo in range(0,n,32768):v[lo:lo+32768,:width]-=v[lo:lo+32768,width:]@beta
        v.resize((n,width),refcheck=False);result=v
    rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))
    return result,rank,dict(iterations=max(x[0] for x in diagnostics),column_iterations=[x[0] for x in diagnostics],
        orthogonality=[x[1] for x in diagnostics],tolerance=tolerance,threads=threads,
        solver='R9_group_means_parallel_independent_columns_v101')
