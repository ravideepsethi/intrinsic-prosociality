"""Optional synthetic memory/time probe; no production data or network."""
import sys,time,json,resource,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from iv_history import *
def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',type=int,default=1000000);p.add_argument('--queries',type=int,default=100000)
    args=p.parse_args();rng=np.random.default_rng(2418);n=args.rows;nq=args.queries
    judges=np.arange(1,250000,dtype=np.int64);judges=judges[r.num.user_hash(judges)%np.uint64(16)==0]
    h=dict(j=rng.choice(judges,n),i=rng.integers(250001,500000,n),t=rng.integers(STARTS[0],STARTS[-1]+28*DAY,n),
        y=rng.binomial(1,.2,n),cell=rng.integers(0,500,n))
    months=rng.integers(1,24,nq)
    q=dict(row_id=np.arange(nq),opponent_id=rng.choice(judges,nq),recipient_id=rng.integers(250001,500000,nq),
        month_code=months,archive_start_ms=np.asarray(STARTS)[months]+rng.integers(0,25*DAY,nq))
    reference=rng.uniform(.02,.4,(2,24,4,4,500));start=time.monotonic();result=score(h,q,reference)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform!='darwin':rss*=1024
    print(json.dumps(dict(synthetic=True,rows=n,queries=nq,seconds=time.monotonic()-start,peak_rss_gib=rss/1024**3,
        supported_24h=int(np.sum(result['24h']['n']>=5)),nuisance_fits='frozen'),indent=2))
if __name__=='__main__':main()
