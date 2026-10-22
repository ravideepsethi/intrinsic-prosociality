"""Optional synthetic throughput/RSS probe; no network or private data."""
import sys,time,json,resource,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from ul_scores import *

def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',type=int,default=500000);p.add_argument('--queries',type=int,default=100000)
    a=p.parse_args();rng=np.random.default_rng(775)
    judges=np.arange(1,250000,dtype=np.int64);judges=judges[r.num.user_hash(judges)%np.uint64(16)==0]
    h=dict(j=rng.choice(judges,a.rows),i=rng.integers(250001,500000,a.rows),t=rng.integers(0,730*DAY,a.rows),
        y=rng.binomial(1,.04,a.rows),cell=rng.integers(0,500,a.rows))
    q=dict(row_id=np.arange(a.queries),frame=(rng.random(a.queries)>.27).astype(np.int8),opponent_id=rng.choice(judges,a.queries),
        recipient_id=rng.integers(250001,500000,a.queries),month_code=rng.integers(0,24,a.queries),
        archive_start_ms=rng.integers(0,730*DAY,a.queries))
    q['anchor_ms']=q['archive_start_ms']+600000
    ref=rng.uniform(.001,.07,(2,24,4,4,500));start=time.monotonic();full,*_=score(h,q,ref)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
    print(json.dumps(dict(synthetic=True,rows=a.rows,queries=a.queries,seconds=time.monotonic()-start,peak_rss_gib=rss/1024**3)))

if __name__=='__main__':main()
