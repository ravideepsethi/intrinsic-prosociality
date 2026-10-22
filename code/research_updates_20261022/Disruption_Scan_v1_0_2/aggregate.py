"""Authenticate and aggregate cached API records; never read the kindness outcome."""
from pathlib import Path
import numpy as np,pandas as pd,pyarrow.parquet as pq
from support import *

def api_month(item,root,code,workers,memory):
 root=Path(root);root.mkdir(parents=True,exist_ok=True);m=item['month'];log('API records: '+m)
 with heartbeat('Hashing API inputs '+m):rec=records(item['paths'])
 signature=sig(dict(code=code,item=item,records=rec));cache=root/'events.parquet'
 if resumed(root,signature):log('Reusing verified API cache '+m);return read(root/'_DONE.json')['extra']
 js(root/'inputs_PRIVATE.json',dict(item=item,files=rec))
 c=connect(root,workers,memory)
 try:
  with heartbeat('Normalizing and auditing '+m):
   c.execute('CREATE OR REPLACE VIEW raw AS '+normal_sql(item['paths']))
   a,b=bounds(m)
   checks=c.execute(f'''SELECT count(*) n,count(DISTINCT game_id) unique_games,
       count(*) FILTER(WHERE game_id IS NULL OR NOT regexp_full_match(game_id,'[A-Za-z0-9]{{8}}')) bad_ids,
       count(*) FILTER(WHERE alias_conflict) alias_conflicts,
       count(*) FILTER(WHERE start_ms<{a} OR start_ms>={b}) wrong_creation_month,
       count(*) FILTER(WHERE start_ms IS NULL OR t IS NULL OR t<start_ms OR t-start_ms>{7*DAY}) bad_timing,
       count(*) FILTER(WHERE white IS NULL OR black IS NULL OR white=black) bad_accounts,
       count(*) FILTER(WHERE rated IS DISTINCT FROM TRUE OR variant IS DISTINCT FROM 'standard') nonstandard_or_unrated
       FROM raw''').fetchdf().to_dict('records')[0]
   js(root/'input_audit.json',checks)
   if checks['n']!=item['expected_rows'] or checks['unique_games']!=checks['n'] or checks['bad_ids'] or checks['alias_conflicts'] or checks['wrong_creation_month']:
    raise RuntimeError('API identity/coverage/alias audit failed for '+m+': '+str(checks))
   csv(c,'''SELECT status,speed,count(*) n,
      count(*) FILTER(WHERE t IS NULL) missing_timestamp,
      count(*) FILTER(WHERE start_ms IS NULL OR t<start_ms) impossible_order,
      count(*) FILTER(WHERE t%1000=0) timestamps_on_second,
      count(*) FILTER(WHERE t%60000=0) timestamps_on_minute,
      quantile_cont((t-start_ms)/1000.0,[.01,.5,.99]) recorded_duration_seconds
      FROM raw GROUP BY status,speed ORDER BY status,speed''',root/'timestamp_audit.csv')
   copy(c,f'''SELECT game_id,start_ms,t,white,black,status,speed,{fold_sql()}::UTINYINT AS fold
        FROM raw WHERE rated AND variant='standard' AND status IN ('timeout','outoftime')
        AND speed IN ({','.join(map(lit,SPEEDS))}) AND t>=start_ms AND t-start_ms<={7*DAY}
        AND start_ms>={a} AND start_ms<{b} AND t>={START} AND t<{END}
        AND (white IS NULL OR black IS NULL OR white<>black)
        ORDER BY t,game_id''',cache)
   c.execute('CREATE OR REPLACE VIEW events AS SELECT * FROM '+parq([cache]))
   copy(c,'''SELECT (t//60000)::BIGINT AS minute,fold,speed,status,count(*)::BIGINT n
      FROM events GROUP BY minute,fold,speed,status''',root/'minute_counts.parquet')
   csv(c,'''SELECT (t//86400000)::BIGINT AS utc_day,status,speed,count(*) n,
      count(*) FILTER(WHERE fold=3) missing_named_pair,
      count(DISTINCT game_id) games FROM events GROUP BY utc_day,status,speed ORDER BY utc_day,status,speed''',root/'daily_counts.csv')
   diag=c.execute('''SELECT count(*) included,count(*) FILTER(WHERE fold=0) discovery,
      count(*) FILTER(WHERE fold=1) validation,count(*) FILTER(WHERE fold=2) cross_group,
      count(*) FILTER(WHERE fold=3) unknown_pair FROM events''').fetchdf().to_dict('records')[0]
   # Never silently classify a materially broken timestamp month as normal zero traffic.
   usable=(checks['bad_timing']/max(checks['n'],1)<=.001 and checks['bad_accounts']/max(checks['n'],1)<=.02 and diag['discovery']>=1000 and diag['validation']>=1000)
   extra=dict(month=m,source=item['source'],signature=signature,coverage_usable=usable,**checks,**diag)
   js(root/'summary.json',extra)
   done(root,signature,[cache,root/'minute_counts.parquet',root/'input_audit.json',root/'timestamp_audit.csv',root/'daily_counts.csv',root/'summary.json',root/'inputs_PRIVATE.json'],extra)
   return extra
 finally:c.close()

def traffic_month(project,month,root,code,workers,memory):
 """Count archived starts, a traffic diagnostic, not exact concurrent games at risk."""
 root=Path(root);root.mkdir(parents=True,exist_ok=True);authority=read(PKG/'evidence/chronology_contract.json')
 entries=[e for e in authority['entries'] if '/month='+month+'/' in e['path']]
 if not entries:return dict(month=month,available=False,reason='NO_FROZEN_CHRONOLOGY_ENTRIES')
 paths=[];metadata=[]
 for e in entries:
  p=relocate(project,e['path'])
  if not p.is_file():return dict(month=month,available=False,reason='MISSING_CHRONOLOGY_FILE')
  pf=pq.ParquetFile(p)
  if p.stat().st_size!=int(e['bytes']) or pf.metadata.num_rows!=int(e['rows']) or pf.metadata.num_row_groups!=int(e['row_groups']):
   raise RuntimeError('Chronology metadata differs from frozen authority: '+str(p))
  paths.append(p);metadata.append(dict(path=str(p),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns,rows=pf.metadata.num_rows))
 # Content digests protect subsequent reuse; the upstream authority pins file metadata, not full byte hashes.
 with heartbeat('Hashing chronology '+month):
  for x,p in zip(metadata,paths):x['sha256']=sha(p)
 signature=sig(dict(code=code,entries=entries,inputs=metadata))
 if resumed(root,signature):return read(root/'_DONE.json')['extra']
 js(root/'inputs_PRIVATE.json',dict(frozen_entries=entries,files=metadata,authority='frozen size/row count/row-group count; full current content hashes recorded'))
 c=connect(root,workers,memory)
 try:
  a,b=bounds(month)
  with heartbeat('Counting archived game starts '+month):
   chunks=[]
   for p in paths:
    speed=next(v.split('=',1)[1] for v in p.parts if v.startswith('speed='))
    chunks.append(f'SELECT utc_ms,{lit(speed)} AS speed FROM '+parq([p]))
   c.execute('CREATE OR REPLACE VIEW starts AS '+' UNION ALL '.join(chunks))
   copy(c,f'''SELECT (utc_ms//60000)::BIGINT AS minute,speed,count(*)::BIGINT n
      FROM starts WHERE utc_ms>={a} AND utc_ms<{b} GROUP BY minute,speed''',root/'starts.parquet')
   n=c.execute(f'SELECT count(*) FROM starts WHERE utc_ms>={a} AND utc_ms<{b}').fetchone()[0]
   extra=dict(month=month,available=True,starts=n,signature=signature)
   done(root,signature,[root/'starts.parquet',root/'inputs_PRIVATE.json'],extra);return extra
 finally:c.close()
