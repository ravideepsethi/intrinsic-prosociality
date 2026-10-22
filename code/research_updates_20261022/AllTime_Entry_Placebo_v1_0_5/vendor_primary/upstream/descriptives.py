"""Exact game-weighted ply quantiles; monthly resumable local archive scans."""
import concurrent.futures as cf, multiprocessing as mp, sys
from local_common import *
sys.path.insert(0,str(ROOT/'vendor/r11'))
import all_games

def run(a,run,k):
    roots=a.archive_root or [a.project/'raw',a.project/'archives',a.project/'data',a.project.parent]
    discovery,inventory=all_games.discover(roots)
    jobs=[dict(d,out=str(run/'PRIVATE/ply'/f'{d["month"]}.json'),key=k) for d in discovery if d['candidates']]
    require(jobs,'No monthly PGN archives found. Pass --archive-root /path/to/monthly/archives.')
    # Two sequential archive readers usually saturate an external disk; avoid ten competing scans.
    with heartbeat('All-game ply histograms'),cf.ProcessPoolExecutor(max_workers=min(a.workers,2),mp_context=mp.get_context('spawn')) as pool:
        results=list(pool.map(all_games.safe_month,jobs))
    status=all_games.finish(results,run,discovery,inventory)
    import pandas as pd
    rows=pd.read_csv(run/'report/all_games_plies_by_speed.csv')
    rows=rows[rows.speed.isin(['bullet','blitz','rapid','classical'])]
    rows['months_missing']=','.join(status['months_missing_or_failed'])
    csv_out(run/'report/all_games_ply_quantiles.csv',rows.to_dict('records'))
    require(len(status['months_used'])>0,'No archive passed the complete-file scan')
    log('All-game quantiles: '+status['status'])
