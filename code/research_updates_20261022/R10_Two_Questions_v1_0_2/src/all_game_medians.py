#!/usr/bin/env python3
"""Optional R10 all-standard-rated-game ply-median source probe/aggregation.

This is separate from the full 41.5m opportunity regression. Nothing should
be described as an all-game median until the underlying all-game source has
been certified as one row per rated standard game for all 24 months.
"""
from __future__ import annotations
import argparse,datetime as dt,json,os,sys,hashlib,csv,time
from pathlib import Path

def quote(z):return "'"+str(z).replace("'","''")+"'"
def ident(z):return '"'+str(z).replace('"','""')+'"'
def now():return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

def select_files(root):
    root=Path(root).expanduser()
    if root.is_file() and root.suffix=='.parquet':return [root]
    if not root.is_dir():return []
    files=[]
    for f in root.rglob('*.parquet'):
        name=str(f)
        if not any(f'month={y}-{m:02}' in name or f'{y}-{m:02}' in f.name
                   for y,m in [(yy,mm) for yy in range(2023,2026) for mm in range(1,13)
                               if (2023,11)<=(yy,mm)<=(2025,10)]):continue
        if any(z in name for z in ('_audit','_temporary','.tmp.')):continue
        files.append(f)
    return sorted(set(files))

def probe_one(path):
    import pyarrow.parquet as pq
    paths=select_files(path)
    if not paths:return {'path':str(path),'candidate_files':0,'note':'No 24-month partition-identified Parquet files'}
    try:
        pf=pq.ParquetFile(paths[0]);fields=pf.schema_arrow.names
        return {'path':str(path),'candidate_files':len(paths),'first_file':str(paths[0]),
                'first_file_rows':pf.metadata.num_rows,
                'first_file_schema':fields,
                'observed_ply_alias':next((z for z in ('ply_count','ply','plies','num_plies') if z in fields),None),
                'observed_gameid_alias':next((z for z in ('game_id','id','gameId') if z in fields),None),
                'observed_speed_alias':next((z for z in ('speed','api_speed','speed_category') if z in fields),None),
                'note':'Schema inventory only; not proof of full coverage or uniqueness'}
    except Exception as e:return {'path':str(path),'error':str(e)}

def weighted_median(hist):
    vals=sorted((int(p),int(n)) for p,n in hist if n>0)
    N=sum(n for _,n in vals)
    if not N:raise ValueError('No rows for speed')
    indices=[(N-1)//2,N//2]
    result=[];cumulative=0
    for p,n in vals:
        cumulative+=n
        while len(result)<len(indices) and cumulative>indices[len(result)]:result.append(p)
        if len(result)==2:break
    return (result[0]+result[1])/2

def main():
    ap=argparse.ArgumentParser(description='Probe or compute all rated standard game median plies')
    ap.add_argument('--probe',action='store_true')
    ap.add_argument('--project-root',default='/Volumes/XT_Pro/lichess_kindness')
    ap.add_argument('--source',help='Authenticated all rated standard one-row-per-game Parquet directory')
    ap.add_argument('--certification',help='Existing certified lineage manifest confirming one row per game, not a guessed file')
    ap.add_argument('--out',default=str(Path.home()/'Desktop'/'Lichess_Desktop'))
    ap.add_argument('--memory-gb',type=int,default=11)
    ap.add_argument('--workers',type=int,default=10)
    args=ap.parse_args()
    output=Path(args.out).expanduser();output.mkdir(parents=True,exist_ok=True)
    if args.probe:
        candidates=[Path(args.project_root)/'derived'/'replication'/'rating_replay_inputs',
                    Path(args.project_root)/'derived'/'glicko2_replay'/'rating_events_replay_sorted_v2_time'/'events_replay_sorted_time']
        if args.source:candidates.insert(0,Path(args.source))
        findings=[probe_one(p) for p in candidates]
        dest=output/f'R10_ALL_GAMES_SOURCE_PROBE_{now()}.json'
        dest.write_text(json.dumps(findings,indent=2)+'\n')
        print(f'Probe written to {dest}');return
    if not args.source or not args.certification:
        ap.error('To compute all-game medians, specify both --source and --certification. Source schema and one-game-per-row status must be authenticated first.')
    cert=Path(args.certification)
    if not cert.exists():raise FileNotFoundError(cert)
    paths=select_files(args.source)
    if not paths:raise ValueError('No monthly Parquet files selected; run --probe')
    import duckdb
    c=duckdb.connect(':memory:')
    c.execute(f'SET threads={int(args.workers)}')
    c.execute('SET memory_limit='+quote(f'{int(args.memory_gb)}GB'))
    source='read_parquet(['+','.join(quote(str(p)) for p in paths)+'],union_by_name=true,hive_partitioning=true)'
    desc=c.execute('DESCRIBE SELECT * FROM '+source+' LIMIT 0').fetchall()
    byname={r[0].lower():r[0] for r in desc}
    def alias(names):return next((byname[z.lower()] for z in names if z.lower() in byname),None)
    ply=alias(('ply_count','ply','plies','num_plies'));sp=alias(('api_speed','speed','speed_category'))
    mo=alias(('month','partition_month','game_month'))
    gid=alias(('game_id','gameId','id'))
    if not ply or not sp or not mo or not gid:
        raise ValueError(f'Missing game, speed, month, or ply field: {sorted(byname)}')
    # Validate coverage + exact official row count from monthly Lichess standard-rated DB.
    cp=f'TRY_CAST({ident(ply)} AS BIGINT)'
    speed=f'LOWER(TRY_CAST({ident(sp)} AS VARCHAR))'
    month=f'SUBSTR(TRY_CAST({ident(mo)} AS VARCHAR),1,7)'
    c.execute('CREATE TEMP VIEW allgames AS SELECT '+cp+' ply, '+speed+' speed, '+month+' month, '+ident(gid)+' game_id FROM '+source)
    stats=c.execute("""SELECT COUNT(*),COUNT(DISTINCT month),MIN(month),MAX(month),
                       SUM(CASE WHEN ply<0 OR ply IS NULL OR speed NOT IN
                       ('ultrabullet','bullet','blitz','rapid','classical') OR game_id IS NULL
                       THEN 1 ELSE 0 END) FROM allgames
                       WHERE month BETWEEN '2023-11' AND '2025-10'""").fetchone()
    if tuple(stats)!=(2231251938,24,'2023-11','2025-10',0):
        raise ValueError(f'All-games coverage does not match official 24-month total: {stats}')
    # This source still requires its external certificate asserting no duplicate game IDs.
    # A 2.23-billion-row COUNT(DISTINCT) is intentionally not done automatically.
    print('Coverage exact; computing counts by game speed and ply (all endings).')
    data=c.execute("""SELECT speed,ply,COUNT(*) n FROM allgames
                      WHERE month BETWEEN '2023-11' AND '2025-10'
                      GROUP BY speed,ply ORDER BY speed,ply""").fetchall()
    hist={sp:[] for sp in ('ultrabullet','bullet','blitz','rapid','classical')}
    for speed,ply,n in data:hist[speed].append((ply,n))
    dest=output/f'R10_ALL_GAME_MEDIAN_PLIES_{now()}.csv'
    with dest.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=('speed','n_games','median_plies','median_definition','validation'))
        writer.writeheader()
        for speed,arr in hist.items():
            writer.writerow({'speed':speed,'n_games':sum(v for _,v in arr),
                'median_plies':weighted_median(arr),'median_definition':'exact weighted median of integer plies',
                'validation':f'coverage matched total; uniqueness must be verified by lineage receipt {cert.name}'})
    print(f'Median table: {dest} (unique-game certification must be checked against supplied manifest)')

if __name__=='__main__':main()
