"""Monthly bounded-history scans; parallel speeds, sequential months per speed."""
import re, shutil
from common import *
from measures import prior_features,stakes,add_ratios

def catalog(project,start):
    found=[]
    for r in pd.read_csv(ROOT/'authority/chronology.tsv',sep='\t').to_dict('records'):
        speed=re.search(r'speed=([^/]+)',r['path'])[1];month=re.search(r'month=([^/]+)',r['path'])[1]
        if speed not in SPEEDS or not start<=month<=MONTHS[-1]:continue
        suffix=r['path'].split('/lichess_kindness/',1)[1]
        found.append(dict(speed=speed,month=month,path=str(Path(project)/suffix),rows=int(r['rows']),bytes=int(r['bytes'])))
    expected={(s,str(m)) for s in SPEEDS for m in pd.period_range(start,MONTHS[-1],freq='M')}
    if len(found)!=len(expected) or {(r['speed'],r['month']) for r in found}!=expected:
        raise RuntimeError('Chronology catalog lacks a required speed/month or contains multiple parts')
    return found

def histogram(c,source,excluded_ids,path):
    """Each previous-month active account contributes its latest pregame rating.

    Ambiguous latest-second ratings and missing latest ratings are excluded and
    separately counted. Actual game/rating history is otherwise unchanged.
    """
    c.execute(f'''CREATE OR REPLACE TEMP TABLE snapshot AS WITH z AS NOT MATERIALIZED (
      SELECT unnest([white_id,black_id])::BIGINT user_id,utc_ms::BIGINT t,
             unnest([white_elo,black_elo])::DOUBLE rating FROM {scan(source)}),
      latest AS (SELECT user_id,max(t) t FROM z GROUP BY user_id)
      SELECT z.user_id,min(z.rating) rating,count(DISTINCT z.rating) distinct_ratings,
             count(*)-count(z.rating) missing_ratings
      FROM z JOIN latest USING(user_id,t) WHERE z.user_id NOT IN ({','.join(map(str,excluded_ids))})
      GROUP BY z.user_id''')
    valid='distinct_ratings=1 AND missing_ratings=0 AND isfinite(rating) AND rating>0'
    qa=c.execute(f'''SELECT count(*) active_accounts,count(*) FILTER(WHERE {valid}) eligible_accounts,
       count(*) FILTER(WHERE distinct_ratings>1) ambiguous_latest_rating,
       count(*) FILTER(WHERE missing_ratings>0 OR rating IS NULL OR NOT isfinite(rating) OR rating<=0) missing_latest_rating
       FROM snapshot''').df().iloc[0].to_dict()
    copy(c,f'SELECT rating,count(*)::BIGINT n FROM snapshot WHERE {valid} GROUP BY rating ORDER BY rating',path)
    c.execute('DROP TABLE snapshot');return qa

def align(c,targets,source,speed,month):
    c.execute(f'CREATE OR REPLACE TEMP TABLE targets AS SELECT * FROM {scan(targets)} WHERE speed={q(speed)}')
    c.execute(f'''CREATE OR REPLACE TEMP TABLE aligned AS SELECT a.*,h.utc_ms::BIGINT history_t,
      h.white_id,h.black_id,h.white_elo,h.black_elo FROM targets a LEFT JOIN {scan(source)} h USING(game_id)''')
    n=c.execute('SELECT count(*) FROM targets').fetchone()[0]
    joined,bad=c.execute('''SELECT count(*),count(*) FILTER(WHERE history_t IS NULL OR white_id IS NULL OR black_id IS NULL
        OR abs(t-history_t)>1000 OR user_id<>CASE color WHEN 'white' THEN white_id ELSE black_id END
        OR opponent_id<>CASE color WHEN 'white' THEN black_id ELSE white_id END
        OR rating IS DISTINCT FROM CASE color WHEN 'white' THEN white_elo ELSE black_elo END
        OR opponent_rating IS DISTINCT FROM CASE color WHEN 'white' THEN black_elo ELSE white_elo END) FROM aligned''').fetchone()
    if n!=joined or bad:raise RuntimeError(f'{speed}/{month}: focal chronology reconciliation failed: n={n}, joined={joined}, bad={bad}')
    # Floor-second alignment prevents the focal PGN observation being prior to
    # its own API start, which may have nonzero milliseconds.
    c.execute('CREATE OR REPLACE TEMP TABLE targets AS SELECT * EXCLUDE(history_t,white_id,black_id,white_elo,black_elo) REPLACE(history_t AS t) FROM aligned')
    c.execute('DROP TABLE aligned');return n

def speed_task(job):
    speed,records,work,ids,buckets,memory,threads,run_key=job;work=Path(work)
    folder=work/'history'/speed;folder.mkdir(parents=True,exist_ok=True)
    records=sorted((r for r in records if r['speed']==speed),key=lambda r:r['month'])
    previous_tail=None;previous_hist=None;results=[];evidence=[];last_completed=None
    # Validate all historical receipts; only the newest tail is retained.
    for i,rec in enumerate(records):
        month=rec['month'];monthdir=folder/month;receipt=monthdir/'_DONE.json'
        e=history_evidence(rec['path'],rec['rows'],rec['bytes']);evidence.append(e)
        key=digest(dict(run=run_key,input=e,prior=[x for x in evidence[:-1]]))
        if receipt.exists():
            d=read(receipt)
            if d['key']!=key:raise RuntimeError('History input/config changed: '+str(receipt))
            for f in d['permanent_files']:verify(f)
            shutil.rmtree(monthdir/'current',ignore_errors=True)
            shutil.rmtree(monthdir/'spill',ignore_errors=True)
            for f in monthdir.glob('features_*.parquet'):f.unlink()
            if previous_tail is not None:shutil.rmtree(previous_tail,ignore_errors=True)
            previous_tail=monthdir/'tail';previous_hist=monthdir/'histogram.parquet';last_completed=d
            if month in MONTHS:results.append(str(work/'analysis'/f'{speed}_{month}.parquet'))
            continue
        # A partial month is fully rebuildable; previous completed month is intact.
        if previous_tail is not None:
            for f in last_completed['tail_files']:verify(f)
        shutil.rmtree(monthdir,ignore_errors=True);monthdir.mkdir(parents=True)
        current=monthdir/'current';tail=monthdir/'tail';tail.mkdir()
        con=connect(monthdir/'spill',threads,memory);source=Path(rec['path']);beg=time.monotonic()
        try:
            lower=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)
            upper=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin()).timestamp()*1000)
            # Narrow validation scan also checks malformed identities before any unnest.
            bad=con.execute(f'''SELECT count(*) FROM {scan(source)} WHERE game_id IS NULL OR utc_ms IS NULL
              OR utc_ms<{lower} OR utc_ms>={upper} OR white_id IS NULL OR black_id IS NULL
              OR white_id<0 OR black_id<0 OR white_id=black_id''').fetchone()[0]
            if bad:raise RuntimeError('Invalid chronology identities or source-month boundaries')
            con.execute(f'CREATE TEMP TABLE needed AS SELECT user_id FROM {scan(work/"needed_users.parquet")} WHERE speed={q(speed)}')
            hist=monthdir/'histogram.parquet';population=histogram(con,source,list(ids.values()),hist)
            n=align(con,work/'targets'/f'{month}.parquet',source,speed,month) if month in MONTHS else 0
            if month in MONTHS and previous_hist is None:raise RuntimeError('A previous-month reference is required')
            if month not in MONTHS:con.execute('CREATE TEMP TABLE targets(user_id BIGINT)')
            log(f'{speed}/{month}: scanning {rec["rows"]:,} source games; {n:,} focal opportunities')
            sql=f'''SELECT z.*,z.user_id%{buckets} bucket FROM (
                SELECT game_id,utc_ms::BIGINT t,unnest([white_id,black_id])::BIGINT user_id,
                       unnest([white_elo,black_elo])::DOUBLE rating FROM {scan(source)}) z
                SEMI JOIN needed USING(user_id)'''
            con.execute(f'COPY ({sql}) TO {q(current)} (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket))')
            features=[]
            for bucket in range(buckets):
                parts=sorted((current/f'bucket={bucket}').glob('*.parquet'))
                if previous_tail is not None and (previous_tail/f'{bucket}.parquet').exists():parts.append(previous_tail/f'{bucket}.parquet')
                if not parts:continue
                history=con.execute(f'SELECT user_id,t,game_id,rating FROM {scan(parts)} ORDER BY user_id,t,game_id').df()
                # Duplicate source games would distort windows. Cross-month
                # duplicates are ruled out by disjoint source-month timestamps.
                if history.duplicated(['user_id','game_id']).any():raise RuntimeError('Duplicate account/game in history')
                if n:
                    targets=con.execute(f'SELECT * FROM targets WHERE user_id%{buckets}={bucket} ORDER BY user_id,t,game_id').df()
                    if len(targets):
                        values=prior_features(history,targets)
                        result=add_ratios(pd.concat([stakes(targets,pd.read_parquet(previous_hist)),values],axis=1))
                        out=monthdir/f'features_{bucket}.parquet';frame(result,out);features.append(out)
                # Keep 101 observations to detect a tied time straddling the last-100 cutoff.
                u=history.user_id.to_numpy();ends=np.r_[np.flatnonzero(np.diff(u))+1,len(u)]
                starts=np.r_[0,ends[:-1]]
                indices=np.flatnonzero(np.arange(len(u))>=np.repeat(ends-101,ends-starts)) if len(u) else np.array([],dtype=int)
                frame(history.iloc[indices],tail/f'{bucket}.parquet')
                del history
            permanent=[hist]
            if month in MONTHS:
                analysis=work/'analysis'/f'{speed}_{month}.parquet'
                if features:copy(con,'SELECT * FROM '+scan(features),analysis)
                else:
                    empty=con.execute('SELECT * FROM targets LIMIT 0').df()
                    frame(add_ratios(pd.concat([stakes(empty,pd.read_parquet(previous_hist)),prior_features(pd.DataFrame(),empty)],axis=1)),analysis)
                if pq.ParquetFile(analysis).metadata.num_rows!=n:raise RuntimeError('History features did not conserve target rows')
                permanent.append(analysis);results.append(str(analysis))
            if history_evidence(source,rec['rows'],rec['bytes'])!=e:raise RuntimeError('Source changed while reading')
            d=dict(key=key,speed=speed,month=month,source=e,population=population,targets=n,
                seconds=time.monotonic()-beg,permanent_files=[record(p) for p in permanent],
                tail_files=[record(p) for p in sorted(tail.glob('*.parquet'))])
            write(receipt,d)
            if previous_tail is not None:shutil.rmtree(previous_tail,ignore_errors=True)
            previous_tail=tail;previous_hist=hist;last_completed=d
            log(f'{speed}/{month}: checkpoint complete ({d["seconds"]/60:.1f} minutes)')
        finally:con.close();shutil.rmtree(monthdir/'spill',ignore_errors=True)
        shutil.rmtree(current,ignore_errors=True)
        for f in monthdir.glob('features_*.parquet'):f.unlink()
    if last_completed:
        for f in last_completed['tail_files']:verify(f)
    return results
