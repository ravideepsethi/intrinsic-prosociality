import sys,time,resource,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
from finish_covariance import covariance
import tempfile
root=Path(tempfile.mkdtemp(prefix='v104_covariance_benchmark_'))
print('Benchmark temporary directory:',root)
p=root/'input.parquet';n=8000000;writer=None;rng=np.random.default_rng(612)
started=time.monotonic()
try:
    for lo in range(0,n,65536):
        hi=min(n,lo+65536);size=hi-lo;rid=np.arange(lo,hi,dtype=np.int64)
        # Millions of distinct accounts and near-unique account/day keys;
        # both samples share accounts and dates, with many reversed pairs.
        i=rid%3000000;j=(rid*31+17)%3000000;j=np.where(i==j,j+3000000,j)
        d=dict(recipient_id=i,opponent_id=j,date=rid%730)
        for k in range(6):d['v'+str(k)]=rng.normal(scale=1e-7,size=size)*((rid%2)==(k%2))
        t=pa.table(d)
        if writer is None:writer=pq.ParquetWriter(p,t.schema,compression='zstd')
        writer.write_table(t)
finally:
    if writer:writer.close()
input_seconds=time.monotonic()-started;start=time.monotonic()
V=covariance(p,['v'+str(k) for k in range(6)],root/'work',4.)
result=dict(rows=n,columns=6,seconds=time.monotonic()-start,input_write_seconds=input_seconds,
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            input_bytes=p.stat().st_size,finite=bool(np.isfinite(V).all()),duckdb_decimal_gb=4.,workers=1)
(root/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
