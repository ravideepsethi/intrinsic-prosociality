"""Separate process: resume ONLY the authenticated old move/engine acquisition."""
import argparse,fcntl,json,os,shutil,sys
from pathlib import Path
from types import SimpleNamespace
from lineage import verify,units,RUN_KEY,ENGINE_SHA,digest

def engine_candidates(project,desktop,explicit):
    for v in [explicit,os.environ.get('A1_TRAJ_STOCKFISH'),shutil.which('stockfish'),
              '/opt/homebrew/bin/stockfish','/usr/local/bin/stockfish']:
        if v:yield Path(v).expanduser()
    for root in [project/'tools',project/'bin',project/'engines',project/'replication_package',
                 Path('/opt/homebrew/Cellar/stockfish'),Path('/usr/local/Cellar/stockfish'),desktop]:
        if not root.is_dir():continue
        for base,dirs,files in os.walk(root):
            dirs[:]=[s for s in sorted(dirs) if not s.startswith('.') and s not in
                     {'PRIVATE','derived','output','node_modules','site-packages','data','raw'}]
            if len(Path(base).relative_to(root).parts)>=5:dirs[:]=[]
            for n in files:
                if 'stockfish' in n.lower():yield Path(base)/n
def find_engine(project,desktop,explicit):
    seen=set()
    for p in engine_candidates(project,desktop,explicit):
        try:
            p=p.resolve()
            if p in seen:continue
            seen.add(p)
            if p.is_file() and os.access(p,os.X_OK) and p.stat().st_size<200*1024**2 and digest(p)==ENGINE_SHA:return p
        except OSError:continue
    raise RuntimeError('Pinned SF18 binary not found. Pass --stockfish /absolute/path/to/the/existing/binary.')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--run',type=Path,required=True);ap.add_argument('--desktop',type=Path,required=True)
    ap.add_argument('--workers',type=int,default=10);ap.add_argument('--stockfish');ap.add_argument('--cache-only',action='store_true')
    a=ap.parse_args();legacy=Path(__file__).resolve().parent/'legacy'
    lock=open(a.run/'RUN.lock','a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('The earlier responsibility run is active. Let it finish; this command can then reuse it.')
    d=verify(a.run,legacy);u=units(a.run,d);pending=sum(not x['ready'] for x in u)
    print(f'ENGINE_CHECKPOINTS: {len(u)-pending}/{len(u)} verified; {pending} batches pending.',flush=True)
    if not pending:return
    engine=find_engine(a.project,a.desktop,a.stockfish)
    # These original modules have absolute imports. The subprocess prevents A1 name collisions.
    sys.path.insert(0,str(legacy))
    import common,trajectory
    common.require(1<=a.workers<=10,'Workers must be 1–10')
    api_lock=open(a.project/'output/TENURE_RESPONSIBILITY_API.lock','a')
    try:fcntl.flock(api_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('The responsibility API lock is in use; no second client was started.')
    db=common.connect(a.run,threads=2,memory='2GB')
    args=SimpleNamespace(stockfish=str(engine),workers=a.workers,fetch_games=not a.cache_only,reuse_a1=True)
    try:trajectory.build(db,a.project,a.run,args,RUN_KEY)
    finally:db.close();api_lock.close();lock.close()
    print('ACQUISITION_COMPLETE: original checkpoints preserved; new A2 analysis follows.',flush=True)
if __name__=='__main__':main()
