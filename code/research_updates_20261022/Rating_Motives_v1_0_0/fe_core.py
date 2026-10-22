"""FE primitives extracted unchanged from Pool_Pooled_Competitive_K_v1_0_0/fe_engine.py."""
from pathlib import Path
import numpy as np
from scipy import sparse

def onehot(codes, levels):
    return sparse.csr_matrix((np.ones(len(codes)), (np.arange(len(codes)), codes)),
                             shape=(len(codes), levels))



def groups(frame):
    user = frame['chooser']
    if len(user) == 0: raise ValueError('Empty chooser block')
    if (np.diff(user) < 0).any(): raise ValueError('Chooser rows are not sorted')
    starts = np.r_[True, user[1:] != user[:-1]]
    g = np.cumsum(starts)-1
    counts = np.bincount(g)
    A = sparse.csr_matrix((np.ones(len(user)), (g, np.arange(len(user)))), shape=(len(counts),len(user)))
    return g, counts, A


def nonsingletons(frame):
    g, n, _ = groups(frame)
    keep = n[g] >= 2
    return {k:v[keep] for k,v in frame.items()}


def iter_blocks(path, batch_rows=32768):
    """PyArrow stream with complete chooser clusters across record boundaries."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    tail = None
    last_user = None
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_rows, use_threads=False):
        table = pa.Table.from_batches([batch])
        if tail is not None: table = pa.concat_tables([tail, table])
        ids = table['chooser'].to_numpy()
        first_tail = np.searchsorted(ids, ids[-1], side='left')
        tail = table.slice(int(first_tail))
        if first_tail:
            block = table.slice(0,int(first_tail))
            vals = {name:block[name].to_numpy() for name in block.column_names}
            if last_user is not None and vals['chooser'][0] <= last_user:
                raise RuntimeError('Chooser cluster split across blocks')
            last_user = vals['chooser'][-1]
            yield vals
    if tail is not None and len(tail):
        vals = {name:tail[name].to_numpy() for name in tail.column_names}
        if last_user is not None and vals['chooser'][0] <= last_user:
            raise RuntimeError('Non-contiguous chooser cluster')
        yield vals


def solve(S,b,C):
    """Scaled eigensolve; tests each requested contrast's estimability."""
    diagonal=np.diag(S).copy()
    cutoff=max(float(diagonal.max(initial=0))*1e-13,1e-12)
    active=diagonal>cutoff
    scale=np.zeros(len(b));scale[active]=1/np.sqrt(diagonal[active])
    H=scale[:,None]*((S+S.T)/2)*scale[None,:]
    values,vectors=np.linalg.eigh(H)
    maximum=float(values.max(initial=0))
    if float(values.min(initial=0)) < -max(1e-8,maximum*1e-8):
        raise RuntimeError('Within-chooser Gram matrix is not positive semidefinite')
    keep=values>max(maximum*1e-10,1e-12)
    V=vectors[:,keep];rank=int(keep.sum())
    inverse=((V/values[keep])@V.T)*scale[:,None]*scale[None,:]
    beta=inverse@b
    # A zero-variance coefficient direction cannot identify a contrast.
    Cs=C*scale
    residual=Cs-(Cs@V)@V.T
    rel=np.linalg.norm(residual,axis=1)/np.maximum(np.linalg.norm(Cs,axis=1),1e-30)
    identified=(rel<1e-6)&(np.linalg.norm(C[:,~active],axis=1)<1e-12)
    identified[np.linalg.norm(C,axis=1)==0]=True
    return dict(beta=beta,bread=inverse,rank=rank,identified=identified,
                projection_error=rel,condition_number=maximum/values[keep][0] if rank else None)

