"""All-game UTC activity phase, with two-year stability and held-out outcomes.
The offset is conditional on an evening-activity convention, not geolocation.
"""
from __future__ import annotations
import concurrent.futures, csv, math, multiprocessing, time
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from utils import *
from core import rate_table, gradient_table

LOW=1698796800000  # 2023-11-01 00:00 UTC
SPLIT=1730419200000  # 2024-11-01
HIGH=1761955200000  # 2025-11-01 (exclusive)
CHRONO_REL='derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time'

def inspect(project,override=None):
    root=Path(override) if override else project/CHRONO_REL
    manifest=ROOT/'evidence/chronology_input_manifest.tsv'; chosen=[]
    with manifest.open() as f: rows=list(csv.DictReader(f,delimiter='\t'))
    for r in rows:
        if int(r['utc_ms_max'])<LOW or int(r['utc_ms_min'])>=HIGH: continue
        tail='speed='+r['path'].split('/speed=',1)[1]; p=root/tail
        require(p.is_file(),'Chronology source missing: '+str(p))
        meta=pq.ParquetFile(p)
        require(p.stat().st_size==int(r['bytes']) and meta.metadata.num_rows==int(r['rows']), 'Chronology differs from saved manifest: '+str(p))
        require({'utc_ms','white_id','black_id'}<=set(meta.schema_arrow.names),'Chronology schema missing UTC time/player IDs')
        chosen.append(dict(path=str(p),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns,rows=meta.metadata.num_rows,
          month=next(v.split('=',1)[1] for v in p.parts if v.startswith('month='))))
    require(bool(chosen),'No in-window chronology sources')
    months={r['month'] for r in chosen}; expected={f'{y}-{m:02}' for y in [2023,2024,2025] for m in range(1,13) if '2023-11'<=f'{y}-{m:02}'<='2025-10'}
    require(expected<=months,'All-game chronology missing panel months')
    return chosen,dict(manifest_sha256=sha(manifest),files=len(chosen),source_rows=sum(r['rows'] for r in chosen),
      scope='ordinary-game chronology, both player roles, UTC 2023-11 through 2025-10, current chooser IDs',
      authentication='bundled manifest byte sizes, Parquet row counts and schema; source body hashes were not supplied by that manifest',
      source_files=chosen)

def worker(job):
    r,accounts,out,identity,memory=job; out=Path(out)
    if valid(out,identity): return dict(path=str(out),reused=True,bytes=r['bytes'])
    db=connection(memory,1,out.parent/('spill_'+out.stem)); start=time.monotonic()
    db.execute(f'CREATE TEMP TABLE wanted AS SELECT chooser FROM read_parquet({qs(accounts)})')
    db.execute('CREATE TEMP TABLE hour_basis AS SELECT range h,cos(2*pi()*(range+.5)/24) c,sin(2*pi()*(range+.5)/24) s FROM range(24)')
    sql=f'''WITH legs AS (SELECT unnest([white_id,black_id])::BIGINT chooser,
       ((utc_ms//3600000)%24)::INTEGER h, CASE WHEN utc_ms<{SPLIT} THEN 1 ELSE 2 END period
       FROM read_parquet({qs(r['path'])},hive_partitioning=false)
       WHERE utc_ms>={LOW} AND utc_ms<{HIGH} AND white_id<>black_id),
      selected AS (SELECT l.* FROM legs l JOIN wanted w USING(chooser))
      SELECT chooser,period,{qs(r['month'])} AS month,count(*)::BIGINT games,sum(c) c,sum(s) s
      FROM selected JOIN hour_basis USING(h) GROUP BY chooser,period'''
    parquet(db,out,sql); db.close(); certify(out,identity,source=r,elapsed_seconds=time.monotonic()-start)
    return dict(path=str(out),reused=False,bytes=r['bytes'],elapsed_seconds=time.monotonic()-start)

def phase(n,c,s):
    n,c,s=np.broadcast_arrays(np.asarray(n,float),np.asarray(c,float),np.asarray(s,float))
    R=np.divide(np.hypot(c,s),n,out=np.zeros_like(n),where=n>0)
    hour=(np.arctan2(s,c)*12/np.pi)%24
    return hour,R
def distance(a,b): return np.abs((a-b+12)%24-12)
def band(hour,ok,evening=20):
    offset=(evening-hour+12)%24-12
    rounded=((np.floor((offset+1.5)/3)*3+12)%24-12).astype(int)
    return np.where(ok,np.char.add('proxy_UTC',np.array([f'{v:+d}' for v in rounded])), 'unclassified')

def finalize_proxy(db,run,paths):
    files='['+','.join(qs(p) for p in paths)+']'
    ag=run/'PRIVATE'/'activity_account_moments.parquet'
    parquet(db,ag,f'''SELECT chooser,sum(games)::BIGINT n,sum(c) c,sum(s) s,count(DISTINCT month) AS months,
      coalesce(sum(games) FILTER(WHERE period=1),0)::BIGINT n1,coalesce(sum(c) FILTER(WHERE period=1),0) c1,
      coalesce(sum(s) FILTER(WHERE period=1),0) s1,count(DISTINCT month) FILTER(WHERE period=1) months1,
      coalesce(sum(games) FILTER(WHERE period=2),0)::BIGINT n2,coalesce(sum(c) FILTER(WHERE period=2),0) c2,
      coalesce(sum(s) FILTER(WHERE period=2),0) s2,count(DISTINCT month) FILTER(WHERE period=2) months2
      FROM read_parquet({files}) GROUP BY chooser''')
    db.execute(f'CREATE OR REPLACE TEMP VIEW moments AS SELECT * FROM read_parquet({qs(ag)})')
    out=run/'PRIVATE'/'activity_proxy.parquet'; temp=out.with_suffix('.partial.parquet'); writer=None
    try:
        for b in db.execute('SELECT a.chooser,m.* EXCLUDE(chooser) FROM accounts a LEFT JOIN moments m USING(chooser) ORDER BY a.chooser').fetch_record_batch(100000):
            d=b.to_pydict()
            for k in d:
                if k!='chooser': d[k]=np.array([v if v is not None else 0 for v in d[k]])
            h,R=phase(d['n'],d['c'],d['s']); h1,R1=phase(d['n1'],d['c1'],d['s1']); h2,R2=phase(d['n2'],d['c2'],d['s2'])
            ok=(d['n']>=50)&(d['months']>=3)&(R>=.15)
            ok1=(d['n1']>=50)&(d['months1']>=3)&(R1>=.15); ok2=(d['n2']>=50)&(d['months2']>=3)&(R2>=.15)
            delta=distance(h1,h2); stable=ok1&ok2&(delta<=3)
            t=pa.table(dict(chooser=np.asarray(d['chooser'],np.int64),games=d['n'].astype(np.int64),games_year1=d['n1'].astype(np.int64),
                games_year2=d['n2'].astype(np.int64),active_months=d['months'].astype(np.int32),concentration=R,
                phase_utc_hour=h,phase_year1_utc_hour=h1,phase_year2_utc_hour=h2,
                full_supported=ok,year1_supported=ok1,year2_supported=ok2,stable_years=stable,
                year_difference_hours=delta,activity_band=band(h,ok),year1_band=band(h1,ok1),
                stable_band=band(h,ok&stable),evening18_band=band(h,ok,18),evening22_band=band(h,ok,22)))
            if writer is None: writer=pq.ParquetWriter(temp,t.schema,compression='zstd')
            writer.write_table(t)
    finally:
        if writer: writer.close()
    os.replace(temp,out)
    db.execute(f'CREATE OR REPLACE TEMP VIEW activity_proxy AS SELECT * FROM read_parquet({qs(out)})')
    db.execute('CREATE OR REPLACE TEMP VIEW activity_joined AS SELECT j.*,z.* EXCLUDE(chooser) FROM joined j JOIN activity_proxy z USING(chooser)')
    export(db,run/'report'/'06_activity_proxy_coverage.csv','''SELECT coalesce(p.flag_status,'not_acquired') flag_status,
      z.full_supported,z.year1_supported,z.year2_supported,z.stable_years,count(*) accounts,
      avg(games) mean_ordinary_games,median(games) median_ordinary_games,
      median(concentration) median_concentration,
      median(year_difference_hours) FILTER(WHERE year1_supported AND year2_supported) median_supported_year_difference_hours
      FROM activity_proxy z JOIN accounts a USING(chooser) LEFT JOIN profile_lookup p USING(username) GROUP BY ALL ORDER BY ALL''')
    for b in ['activity_band','stable_band','evening18_band','evening22_band']:
        rate_table(db,run/'report'/f'06_{b}_state_rates.csv',b+',flag_status,state',source='activity_joined')
        gradient_table(db,run/'report'/f'06_{b}_board_gradient.csv',b+',flag_status',source='activity_joined')
    rate_table(db,run/'report'/'06_year1_proxy_year2_rates.csv','year1_band,flag_status,state',"month>='2024-11'",source='activity_joined')
    gradient_table(db,run/'report'/'06_year1_proxy_year2_gradient.csv','year1_band,flag_status',"month>='2024-11'",source='activity_joined')
    export(db,run/'report'/'06_flag_country_activity_crosscheck.csv','''SELECT p.iso_code,z.activity_band,z.stable_years,count(*) accounts
      FROM activity_proxy z JOIN accounts a USING(chooser) JOIN profile_lookup p USING(username)
      WHERE p.iso_code IS NOT NULL GROUP BY ALL ORDER BY ALL''')
    dump(run/'report'/'ACTIVITY_METHOD.json',dict(status='COMPLETE',minimum_games=50,minimum_active_months=3,minimum_circular_concentration=.15,
      stability='Both years meet the thresholds and circular activity phases differ by at most 3 hours.',
      convention='Circular mean of UTC hour-bin centers; illustrative offset assumes local activity phase at 20:00. Rounded into 3-hour bands.',
      sensitivity='18:00 and 22:00 local-phase conventions; stable-both-years subset; year-1 proxy applied only to year-2 decisions.',
      missing='Sparse or diffuse histories remain unclassified. Account-level values are private.',
      limitations='Not observed time zone, longitude, nationality or residence. Flags do not train this proxy. Similar setter/non-setter curves do not prove geographic generalizability.'))

def run_activity(db,project,run,args,identity):
    chosen,receipt=inspect(project,args.chronology_root)
    dump(run/'PRIVATE'/'CHRONOLOGY_SOURCES.json',receipt)
    summary={k:v for k,v in receipt.items() if k!='source_files'}; dump(run/'report'/'CHRONOLOGY_SCOPE.json',summary)
    task_identity=signature([identity,receipt]); folder=run/'PRIVATE'/'activity_parts'; folder.mkdir(parents=True,exist_ok=True)
    jobs=[(r,str(run/'PRIVATE/accounts.parquet'),str(folder/f'part_{i:04}.parquet'),task_identity,args.worker_memory) for i,r in enumerate(chosen)]
    total=sum(r['bytes'] for r in chosen); done=0; start=time.monotonic()
    log(f'ACTIVITY_SCAN {len(jobs)} files; {total/1e9:.1f} GB compressed source; {args.workers} workers')
    with Heartbeat('All-game activity scan'),concurrent.futures.ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        futures=[pool.submit(worker,j) for j in jobs]
        for i,f in enumerate(concurrent.futures.as_completed(futures),1):
            result=f.result(); done+=result['bytes']; elapsed=time.monotonic()-start
            eta=elapsed*(total-done)/max(done,1)/3600
            log(f'ACTIVITY_FILES {i}/{len(jobs)}; byte-based ETA {eta:.2f} h; reused={result["reused"]}')
    with Heartbeat('Activity aggregation and support tables'):
        finalize_proxy(db,run,[j[2] for j in jobs])
