"""One reusable activity extraction from recorded starts, never rating replay.

Old months collapse to per-user counts/first/last start. Each focal month then
uses that month and its predecessor for exact 7-day windows; no daily rounding.
"""
import re
from common import *

def catalog(project,stop='2025-10'):
    rows=pd.read_csv(ROOT/'authority/chronology.tsv',sep='\t').to_dict('records');out=[]
    for r in rows:
        s=re.search(r'speed=([^/]+)',r['path'])[1];m=re.search(r'month=([^/]+)',r['path'])[1]
        if s not in SPEEDS or m>stop:continue
        suffix=r['path'].split('/lichess_kindness/',1)[1]
        out.append(dict(speed=s,month=m,path=str(Path(project)/suffix),rows=int(r['rows']),size=int(r['bytes'])))
    for s in SPEEDS:
        found={r['month'] for r in out if r['speed']==s}
        required={str(x) for x in pd.period_range('2023-10',stop,freq='M')}
        if not required<=found:raise RuntimeError('Chronology lacks required activity months: '+s)
    return out

def summary_task(task):
    rec,work,memory=task;work=Path(work);s=rec['speed'];m=rec['month'];p=Path(rec['path'])
    evidence=auth(p,work,rows=rec['rows'],size=rec['size'])
    need=work/'needed_users.parquet';out=work/'history_summary'/f'{s}_{m}.parquet'
    key=digest(dict(version=VERSION,input=evidence,needed=stamp(need),semantics='prior_recorded_starts'))
    if reuse(out,key):return str(out)
    if not {'white_id','black_id','utc_ms','game_id'}<=cols(p):raise RuntimeError('Chronology schema differs: '+str(p))
    c=connect(work/'tmp'/('hs_'+s+'_'+m),1,memory)
    try:
        c.execute(f'CREATE TEMP TABLE users AS SELECT user_id FROM {scan(need)} WHERE speed={q(s)}')
        # Lateral unnest scans each game once and preserves its two player sides.
        sql=f"""SELECT e.user_id,count(*)::BIGINT n,min(e.utc_ms)::BIGINT first_ms,max(e.utc_ms)::BIGINT last_ms
          FROM (SELECT UNNEST([white_id,black_id]) user_id,utc_ms FROM {scan(p)} WHERE white_id<>black_id) e
          SEMI JOIN users u ON e.user_id=u.user_id GROUP BY e.user_id"""
        copy(c,sql,out);done(out,key,source=evidence,month=m,speed=s)
        log('History counts complete: '+s+'/'+m);return str(out)
    finally:c.close()

def features_task(task):
    s,m,records,work,memory=task;work=Path(work);lookup={r['month']:r for r in records if r['speed']==s}
    prev=str(pd.Period(m,'M')-1);curr=Path(lookup[m]['path']);previous=Path(lookup[prev]['path'])
    summaries=[work/'history_summary'/f'{s}_{x}.parquet' for x in sorted(lookup) if x<m]
    base=work/'narrow'/f'{m}.parquet';out=work/'history_features'/f'{s}_{m}.parquet'
    key=digest(dict(version=VERSION,inputs=[stamp(p) for p in [base,curr,previous]+summaries]))
    if reuse(out,key):return str(out)
    month_start=int(pd.Timestamp(m+'-01',tz='UTC').timestamp()*1000)
    c=connect(work/'tmp'/('hf_'+s+'_'+m),1,memory)
    try:
        c.execute(f"""CREATE TEMP TABLE targets AS SELECT game_id,chooser user_id,t,1 player_role FROM {scan(base)} WHERE speed={q(s)}
          UNION ALL SELECT game_id,opponent,t,0 FROM {scan(base)} WHERE speed={q(s)}""")
        c.execute('CREATE TEMP TABLE users AS SELECT DISTINCT user_id FROM targets')
        # Validate namespace and start-time provenance on the actual target games.
        aligned=c.execute(f"""SELECT count(*),count(*) FILTER(WHERE e.game_id IS NULL OR t.user_id NOT IN(e.white_id,e.black_id)
          OR abs(t.t-e.utc_ms)>1000) FROM targets t LEFT JOIN {scan(curr)} e USING(game_id)""").fetchone()
        expected=c.execute('SELECT count(*) FROM targets').fetchone()[0]
        if aligned[1] or aligned[0]!=expected:raise RuntimeError(f'{s}/{m}: target chronology identity/time mismatch {aligned}')
        # PGN times can be whole seconds while API starts retain milliseconds.
        # Align the anchor to its own chronology event before counting, otherwise
        # an API timestamp 500 ms later could count the focal game as prior.
        c.execute(f'UPDATE targets SET t=e.utc_ms FROM {scan(curr)} e WHERE targets.game_id=e.game_id')
        c.execute(f"""CREATE TEMP TABLE prefix AS SELECT h.user_id,sum(n)::BIGINT n,min(first_ms)::BIGINT first_ms,
          max(last_ms)::BIGINT last_ms FROM {scan(summaries)} h SEMI JOIN users u USING(user_id) GROUP BY h.user_id""")
        c.execute(f"""CREATE TEMP TABLE events AS WITH z AS (
          SELECT e.user_id,e.utc_ms::BIGINT event_ms,count(*)::BIGINT n
          FROM (SELECT UNNEST([white_id,black_id]) user_id,utc_ms FROM {scan([previous,curr])} WHERE white_id<>black_id) e
          SEMI JOIN users u ON e.user_id=u.user_id GROUP BY e.user_id,e.utc_ms)
          SELECT *,sum(CASE WHEN event_ms>={month_start} THEN n ELSE 0 END)
          OVER(PARTITION BY user_id ORDER BY event_ms ROWS UNBOUNDED PRECEDING)::BIGINT current_count,
          min(event_ms) OVER(PARTITION BY user_id)::BIGINT first_local FROM z""")
        c.execute(f"""CREATE TEMP TABLE lookups AS SELECT t.*,k.j,t.t-k.j*{7*DAY} boundary_ms
          FROM targets t CROSS JOIN range(4) k(j)""")
        c.execute("""CREATE TEMP TABLE matched AS SELECT t.*,e.event_ms,e.current_count,e.first_local
          FROM lookups t ASOF LEFT JOIN events e ON t.user_id=e.user_id AND t.boundary_ms>e.event_ms""")
        # No event exactly at a boundary contributes to the preceding interval.
        sql=f"""WITH f AS (SELECT a.game_id,a.player_role,a.user_id,max(a.t) t,
          max(a.current_count) FILTER(WHERE j=0) current_count,
          max(a.event_ms) FILTER(WHERE j=0) last_local,min(a.first_local) first_local,
          coalesce(bool_or(j=0 AND event_ms>=t-{7*DAY}),false) week1,
          coalesce(bool_or(j=1 AND event_ms>=t-{14*DAY}),false) week2,
          coalesce(bool_or(j=2 AND event_ms>=t-{21*DAY}),false) week3,
          coalesce(bool_or(j=3 AND event_ms>=t-{28*DAY}),false) week4
          FROM matched a GROUP BY a.game_id,a.player_role,a.user_id)
          SELECT f.game_id,f.player_role,coalesce(p.n,0)+coalesce(f.current_count,0) AS prior_starts,
          CASE WHEN coalesce(p.first_ms,f.first_local)<f.t THEN (f.t-coalesce(p.first_ms,f.first_local))/{DAY}.0 END history_days,
          CASE WHEN coalesce(f.last_local,p.last_ms)<f.t THEN (f.t-coalesce(f.last_local,p.last_ms))/{DAY}.0 END inactivity_days,
          week1,week2,week3,week4 FROM f LEFT JOIN prefix p USING(user_id)"""
        copy(c,sql,out);done(out,key,target_rows=aligned[0],identity_time_mismatches=aligned[1],
            history_anchor='Focal chronology start after API/PGN reconciliation; all equal-time starts excluded');
        log('Past-only activity complete: '+s+'/'+m);return str(out)
    finally:c.close()
