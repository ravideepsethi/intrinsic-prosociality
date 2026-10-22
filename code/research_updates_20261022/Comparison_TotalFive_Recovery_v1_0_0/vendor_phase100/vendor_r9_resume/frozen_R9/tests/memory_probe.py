"""Optional synthetic memory/throughput probe; never run against research data."""
import sys,subprocess,tempfile,json,resource,time,gc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_r9 import fixture,job,np,r
import r9_models as fits

def main():
    if len(sys.argv)>1 and sys.argv[1]=='child':
        p=Path(sys.argv[2]);start=time.monotonic();j=job(p,kind='entry');fits.fit_job(j)
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform!='darwin':peak*=1024
        print(json.dumps(dict(rows=int(sys.argv[3]),peak_rss_gib=peak/1024**3,elapsed_seconds=time.monotonic()-start,
            reservation_gib=j['memory_gb'],platform=sys.platform)))
    else:
        n=int(sys.argv[1]) if len(sys.argv)>1 else 1000000
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p,n);rng=np.random.default_rng(615)
            d['recipient_id']=rng.integers(1,max(2,n//2),n);d['opponent_id']=rng.integers(n,n+n//2,n)
            r.io.table(p/'data.parquet',r.pa.table(d));del d,a;gc.collect()
            subprocess.run([sys.executable,__file__,'child',str(p),str(n)],check=True)

if __name__=='__main__':main()
