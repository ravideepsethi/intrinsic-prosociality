"""Same exact shared-account OR date CR0, with adaptive storage."""
from fast_bootstrap import *
import finish_covariance as bounded
import r7_memory
import math

def covariance(path, columns, root, memory=4., buckets=None):
    path=Path(path); root=Path(root)
    n=pq.ParquetFile(path).metadata.num_rows
    require(n>0 and len(columns)>0, 'Empty covariance input')
    use_ram, estimate=ram_fits(n,len(columns),'covariance')
    if buckets is not None: use_ram=False  # explicit bounded-path verification
    if not use_ram:
        # Preserve completed old partition leaves when available. Otherwise
        # size partitions to the frame, instead of imposing 128 on every fit.
        checksum=sha(path)
        if buckets is None:
            for ident in sorted(root.glob('*/identity.json')):
                old=load(ident)
                if (old.get('input_sha256')==checksum and old.get('columns')==columns
                    and old.get('algorithm')==bounded.ALGORITHM
                    and old.get('duckdb_version')==bounded.duckdb.__version__):
                    buckets=int(old['buckets']); break
        if buckets is None:
            buckets=min(128,max(8,2**math.ceil(math.log2(max(1,n/1500000)))))
        log(f'Covariance: bounded disk path, {n:,} rows, {buckets} partitions; RAM reservation would be {estimate:.2f} GiB')
        return bounded.covariance(path,columns,root,memory,buckets=buckets)
    identity=dict(algorithm='R9_shared_meat_adaptive_v101',input_sha256=sha(path),
                  columns=columns,n=n,numpy_version=np.__version__)
    conf=key(identity)
    def build(tmp):
        started=time.monotonic()
        log(f'Covariance: R9 NumPy path, {n:,} rows; conservative reservation {estimate:.2f} GiB')
        def read(name):
            a=pq.read_table(path,columns=[name]).column(0)
            require(a.null_count==0,'Null covariance field: '+name)
            return a.to_numpy(zero_copy_only=False)
        actors=[read(k) for k in ('recipient_id','opponent_id','date')]
        require(all(a.dtype.kind in 'iu' for a in actors),'Covariance IDs must be integers')
        require(not np.any(actors[0]==actors[1]),'Self pair in covariance')
        scores=np.empty((n,len(columns)),dtype=np.float64,order='F')
        for k,name in enumerate(columns):
            a=read(name);require(np.isfinite(a).all(),'Nonfinite influence: '+name)
            scores[:,k]=a
        del a
        codes=frozen.r.stats.cmp.covariance_codes(*actors)
        del actors;gc.collect()
        V=r7_memory.shared_meat(scores,codes,True)
        require(np.isfinite(V).all(),'Nonfinite covariance matrix')
        save(tmp/'result.json',dict(identity=identity,matrix=V.tolist(),seconds=time.monotonic()-started,
             conservative_reservation_gib=estimate,formula='accounts-pairs+dates-account_dates+pair_dates'))
        return dict(rows=n,execution_version=EXECUTION_VERSION)
    out,_=stage(root/('numpy_'+conf[:16]),conf,build)
    return np.array(load(out/'result.json')['matrix'],dtype=float)
