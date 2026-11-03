"""Fixed material authority, isolated outputs, and bounded sequential execution."""
from closeout_common import *
import gc,csv,math,contextlib
import pyarrow.compute as pc
import model_kernel as kernel
ROOT=Path(__file__).resolve().parents[1]
CLOSEOUT_CONF='2854da0567adc38694949710ea608055f4d3157aaa92ebc5a9aa0ceb41d52aeb'
def col(p,k):return pq.ParquetFile(p).read(columns=[k],use_threads=False).column(0).to_numpy(zero_copy_only=False)
def csv_rows(p):
    with Path(p).open(newline='') as f:return list(csv.DictReader(f))
def write_csv(p,rr):
    rr=[{k:v for k,v in r.items() if 'holm' not in k.lower() and 'bonferroni' not in k.lower()} for r in rr]
    public_csv(p,rr)
def fit_meta(actors):return dict(n=len(actors['row_id']),recipients=len(np.unique(actors['recipient_id'])),opponents=len(np.unique(actors['opponent_id'])),account_clusters=len(np.union1d(actors['recipient_id'],actors['opponent_id'])),date_clusters=len(np.unique(actors['date'])))
def sql(folder,memory=1.5):
    d=connect(folder,memory);d.execute('SET threads=1');d.execute('SET preserve_insertion_order=false');return d
def append_columns(src,dst,columns):
    n=rows(src);require(all(len(v)==n for v in columns.values()),'Append column length mismatch')
    offset=0;writer=None
    try:
        for batch in pq.ParquetFile(src).iter_batches(batch_size=32768,use_threads=False):
            t=pa.Table.from_batches([batch]);hi=offset+len(t)
            for k,v in columns.items():
                if k in t.column_names:t=t.set_column(t.column_names.index(k),k,pa.array(v[offset:hi]))
                else:t=t.append_column(k,pa.array(v[offset:hi]))
            if writer is None:writer=pq.ParquetWriter(dst,t.schema,compression='zstd')
            writer.write_table(t);offset=hi
    finally:
        if writer:writer.close()
    require(offset==n,'Append lost rows')
def filter_pair(src,scores,out,keep):
    """Identical masks and stable physical row order, without a global sort."""
    keep=np.asarray(keep,bool);require(len(keep)==rows(src)==rows(scores),'Mask/input lengths differ')
    require(np.array_equal(col(src,'row_id'),col(scores,'row_id')),'Source/scores are not aligned')
    for p,name in [(src,'source.parquet'),(scores,'scores.parquet')]:
        pf=pq.ParquetFile(p);offset=0
        with pq.ParquetWriter(out/name,pf.schema_arrow,compression='zstd') as w:
            for ba in pf.iter_batches(batch_size=32768,use_threads=False):
                hi=offset+len(ba);w.write_table(pa.Table.from_batches([ba]).filter(pa.array(keep[offset:hi])));offset=hi
    require(rows(out/'source.parquet')==int(keep.sum()),'Filter count mismatch')
def stage_source(parent,relative,conf=PARENT_CONF):
    p=Path(parent)/relative;stage_record(p,conf);return p
def extended_buffer(job,root,extra):
    """Append evaluated targets to the frozen control/FE design one column at a time."""
    allocate=kernel.allocate_design
    kernel.allocate_design=lambda path,n,p:kernel.disk.disk_matrix(path,n,p)
    try:v,g,actors,targets,meta,events=kernel.build_buffer(job,root)
    finally:kernel.allocate_design=allocate
    k=len(targets);items=list(extra);n=len(v);new=kernel.disk.disk_matrix(root/'extended.dat',n,v.shape[1]+len(items))
    for j in range(k):new[:,j]=v[:,j]
    for j,name in enumerate(items):
        value=extra[name]() if callable(extra[name]) else extra[name]
        value=np.asarray(value,float);require(value.shape==(n,) and np.isfinite(value).all(),'Invalid target '+name)
        new[:,k+j]=value
    for j in range(k,v.shape[1]):new[:,j+len(items)]=v[:,j]
    del v;gc.collect();(root/'design.dat').unlink(missing_ok=True)
    return new,g,actors,targets+items,meta,events
def meat_factory(actors,root):
    from fast_covariance import covariance
    calls=[0]
    def meat(score):
        s=np.asarray(score);s=s[:,None] if s.ndim==1 else s
        require(len(s)==len(actors['row_id']) and np.isfinite(s).all(),'Invalid influence matrix')
        calls[0]+=1;d=root/('cov_'+str(calls[0]));d.mkdir();p=d/'scores.parquet';names=['v'+str(k) for k in range(s.shape[1])]
        with pq.ParquetWriter(p,pa.schema([(k,pa.int64()) for k in actors]+[(k,pa.float64()) for k in names]),compression='zstd') as w:
            for lo in range(0,len(s),65536):
                hi=min(len(s),lo+65536);t={k:np.asarray(v[lo:hi],np.int64) for k,v in actors.items()}
                t.update({k:np.asarray(s[lo:hi,j],float) for j,k in enumerate(names)});w.write_table(pa.table(t))
        V=covariance(p,names,d/'work',memory=1.5,buckets=16);shutil.rmtree(d);return V
    return meat
def frozen_systems():
    p=ROOT/'frozen_iv/vendor/uniform/original/vendor/vendor_primary/upstream/vendor/r9b/code'
    sys.path.insert(0,str(p));import r9b_common
    return r9b_common
def clear_design(root):
    gc.collect()
    for name in ('design.dat','extended.dat','residual.dat'):(root/name).unlink(missing_ok=True)
def publish(root,run,table_name):
    result=read(root/'result.json');rows_out=[]
    for key,v in result.items():
        if isinstance(v,list):rows_out += [dict(section=key,**r) for r in v if isinstance(r,dict)]
    write_csv(run/'report'/table_name,rows_out)
