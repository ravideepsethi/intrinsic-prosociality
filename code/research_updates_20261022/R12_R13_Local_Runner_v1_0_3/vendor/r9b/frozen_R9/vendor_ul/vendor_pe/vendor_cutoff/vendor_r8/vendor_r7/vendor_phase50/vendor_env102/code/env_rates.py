"""Pair-excluded, pre-month environment rates from a bounded local scan.

The numerator is a certified active-resolution event, not every physical drop.
Both roles share the identical game-start window and author-clean game universe.
Resolution time must also precede the cutoff. Focal-pair games are subtracted
from BOTH numerator and denominator; all arithmetic is integer until division.
"""
from env_common import *

COUNTS=['games','own','chooser']

def requests(inputs,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            for k,path in enumerate(inputs):
                checked_columns(path,['recipient_id','opponent_id','month_code'])
            sql=' UNION ALL '.join('SELECT opponent_id person,recipient_id partner,month_code FROM '+io.parq([p]) for p in inputs)
            c.execute('CREATE TEMP TABLE q AS SELECT DISTINCT * FROM ('+sql+')')
            months=[r[0] for r in c.execute('SELECT DISTINCT month_code FROM q ORDER BY 1').fetchall()]
            if any(m<0 or m>=len(STARTS) for m in months):raise RuntimeError('Unknown month code')
            windows=[dict(month_code=m,lo=int(STARTS[m])-97*DAY,hi=int(STARTS[m])-7*DAY,
                complete=int(STARTS[m])-97*DAY>=int(STARTS[0]) and int(STARTS[m])-7*DAY<=core.PANEL_END) for m in months]
            io.table(tmp/'windows.parquet',pa.Table.from_pylist(windows))
            io.copy(c,'SELECT * FROM q ORDER BY person,partner,month_code',tmp/'requests.parquet')
            io.copy(c,'SELECT DISTINCT person FROM q ORDER BY person',tmp/'people.parquet')
            io.copy(c,'SELECT DISTINCT person,partner FROM q ORDER BY person,partner',tmp/'pairs.parquet')
            return dict(windows=windows,request_rows=c.execute('SELECT count(*) FROM q').fetchone()[0])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,inputs)

def panel_job(job):
    threads_one()
    def build(tmp):
        io.checked(job['path'],job['sha256'],job['bytes'])
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW p AS SELECT game_id,utc_ms::BIGINT start_ms,api_last_move_at_ms::BIGINT end_ms,disconnected_user_id::BIGINT i,chooser_user_id::BIGINT j FROM '+io.parq([job['path']]))
            n,u,bad=c.execute('SELECT count(*),count(DISTINCT game_id),sum((i IS NULL OR j IS NULL OR i=j OR start_ms IS NULL OR end_ms IS NULL OR end_ms<start_ms)::BIGINT) FROM p').fetchone()
            if n!=u or bad:raise RuntimeError('Invalid certified panel event keys/times')
            ids=','.join(map(str,job['authors']))
            n=io.copy(c,'SELECT * FROM p WHERE i NOT IN ('+ids+') AND j NOT IN ('+ids+') ORDER BY start_ms,game_id',tmp/'events.parquet')
            lo,hi=c.execute('SELECT min(start_ms),max(start_ms) FROM '+io.parq([tmp/'events.parquet'])).fetchone()
            return dict(rows=n,minimum=lo,maximum=hi)
        finally:finish_connection(c,tmp/'spill')
    return stage(job,build,[job['path']])

def bounds(path):
    p=pq.ParquetFile(path);ix=p.schema_arrow.names.index('utc_ms');spans=[]
    for r in range(p.metadata.num_row_groups):
        st=p.metadata.row_group(r).column(ix).statistics
        if not st or not st.has_min_max:return None,None
        spans.append((int(st.min),int(st.max)))
    return (min(x[0] for x in spans),max(x[1] for x in spans)) if spans else (None,None)

def chronology_jobs(records,windows,panels,req,root,conf,memory):
    active=[w for w in windows if w['complete']]
    if not active:raise RuntimeError('No complete pre-game history windows')
    lower=min(w['lo'] for w in active);upper=max(w['hi'] for w in active);jobs=[];skipped=0
    for record in records:
        path=Path(record['path'])
        if io.sig(path)!=record['signature']:raise RuntimeError('Chronology input changed: '+str(path))
        pf=pq.ParquetFile(path)
        if pf.metadata.num_rows!=record['rows']:raise RuntimeError('Chronology row count changed')
        lo,hi=bounds(path)
        if lo is not None and (lo>=upper or hi<lower):skipped+=1;continue
        events=[p['path'] for p in panels if p['minimum'] is None or lo is None or (p['minimum']<=hi and p['maximum']>=lo)]
        jobs.append(dict(record=record,events=events,queries=str(req),lower=lower,upper=upper,memory=memory,
            conf=conf,rows=record['rows'],output=str(root/f'{record["file_index"]:04}')))
    return jobs,dict(files_considered=len(records),files_outside_time_range=skipped,files_in_range=len(jobs),
        candidate_rows_before_row_group_and_person_pruning=sum(j['rows'] for j in jobs),lower_ms=lower,upper_ms_exclusive=upper,
        result_code_used=False,chronology_ordering_or_adjacency_rebuilt=False)

def chronology_job(job):
    threads_one();record=job['record'];path=Path(record['path']);req=Path(job['queries'])
    def build(tmp):
        if io.sig(path)!=record['signature']:raise RuntimeError('Chronology signature changed before scan')
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE TEMP TABLE people AS SELECT * FROM '+io.parq([req/'people.parquet']))
            c.execute('CREATE TEMP TABLE pairs AS SELECT * FROM '+io.parq([req/'pairs.parquet']))
            c.execute('CREATE TEMP TABLE windows AS SELECT * FROM '+io.parq([req/'windows.parquet'])+' WHERE complete')
            where=f'utc_ms>={job["lower"]} AND utc_ms<{job["upper"]} AND white_id>=0 AND black_id>=0 AND white_id<>black_id'
            c.execute('CREATE TEMP TABLE g AS SELECT game_id,utc_ms::BIGINT start_ms,white_id::BIGINT w,black_id::BIGINT b FROM '+io.parq([path])+' WHERE '+where+' AND (white_id IN (SELECT person FROM people) OR black_id IN (SELECT person FROM people))')
            ids=','.join(map(str,job['authors']))
            c.execute('DELETE FROM g WHERE w IN ('+ids+') OR b IN ('+ids+')')
            if job['events']:
                c.execute('CREATE VIEW main AS SELECT * FROM '+io.parq(job['events'])+f' WHERE start_ms>={job["lower"]} AND start_ms<{job["upper"]}')
            else:c.execute('CREATE VIEW main AS SELECT NULL::VARCHAR game_id,NULL::BIGINT start_ms,NULL::BIGINT end_ms,NULL::BIGINT i,NULL::BIGINT j WHERE FALSE')
            bad=c.execute('SELECT count(*) FROM g JOIN main m USING(game_id) WHERE g.start_ms<>m.start_ms OR NOT ((g.w=m.i AND g.b=m.j) OR (g.w=m.j AND g.b=m.i))').fetchone()[0]
            if bad:raise RuntimeError('Certified event disagrees with canonical game identity/time')
            c.execute('CREATE TEMP TABLE linked AS SELECT g.*,m.end_ms,m.i,m.j FROM g LEFT JOIN main m USING(game_id)')
            ng=c.execute('SELECT count(*) FROM g').fetchone()[0]
            if c.execute('SELECT count(*) FROM linked').fetchone()[0]!=ng:raise RuntimeError('Duplicate certified event across panels')
            c.execute('DROP TABLE g')
            c.execute('CREATE VIEW e AS SELECT w person,b partner,start_ms,end_ms,i,j FROM linked WHERE w IN (SELECT person FROM people) UNION ALL SELECT b,w,start_ms,end_ms,i,j FROM linked WHERE b IN (SELECT person FROM people)')
            terms='count(*)::BIGINT games,coalesce(sum((e.person=e.i AND e.end_ms<w.hi)::BIGINT),0)::BIGINT own,coalesce(sum((e.person=e.j AND e.end_ms<w.hi)::BIGINT),0)::BIGINT chooser'
            for label,pair in [('person',False),('pair',True)]:
                keys='e.person,'+('e.partner,' if pair else '')+'w.month_code'
                extra=' SEMI JOIN pairs p ON e.person=p.person AND e.partner=p.partner' if pair else ''
                sql='SELECT '+keys+','+terms+' FROM e JOIN windows w ON e.start_ms>=w.lo AND e.start_ms<w.hi'+extra+' GROUP BY '+keys
                io.copy(c,sql,tmp/(label+'.parquet'))
            if io.sig(path)!=record['signature']:raise RuntimeError('Chronology changed during scan')
            return dict(relevant_games=ng,source_rows=record['rows'])
        finally:finish_connection(c,tmp/'spill')
    return stage(job,build,[path,req/'requests.parquet',req/'windows.parquet']+job['events'])

def combine(req,partroots,events,root,conf,memory,threads):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,threads)
        try:
            for label,keys in [('person','person,month_code'),('pair','person,partner,month_code')]:
                c.execute('CREATE TEMP TABLE '+label+'_counts AS SELECT '+keys+','+','.join('sum('+v+')::BIGINT '+v for v in COUNTS)+' FROM '+io.parq([Path(r)/(label+'.parquet') for r in partroots])+' GROUP BY '+keys)
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([req/'requests.parquet']))
            c.execute('CREATE VIEW w AS SELECT * FROM '+io.parq([req/'windows.parquet']))
            # Independently check ALL needed numerator events found in canonical games.
            c.execute('CREATE VIEW people AS SELECT * FROM '+io.parq([req/'people.parquet']))
            c.execute('CREATE VIEW main AS SELECT * FROM '+io.parq(events))
            expected=c.execute('SELECT coalesce(sum((m.i IN (SELECT person FROM people))::BIGINT),0),coalesce(sum((m.j IN (SELECT person FROM people))::BIGINT),0) FROM main m JOIN w ON w.complete AND m.start_ms>=w.lo AND m.start_ms<w.hi AND m.end_ms<w.hi').fetchone()
            actual=c.execute('SELECT coalesce(sum(own),0),coalesce(sum(chooser),0) FROM person_counts').fetchone()
            if expected!=actual:raise RuntimeError('Active-resolution numerator not completely matched to canonical game universe: '+str((expected,actual)))
            fields=','.join('(coalesce(p.'+v+',0)-coalesce(b.'+v+',0))::BIGINT '+v for v in COUNTS)
            c.execute('CREATE TEMP TABLE counts AS SELECT q.*,w.complete,w.lo,w.hi,'+fields+' FROM q JOIN w USING(month_code) LEFT JOIN person_counts p USING(person,month_code) LEFT JOIN pair_counts b USING(person,partner,month_code)')
            if c.execute('SELECT count(*) FROM counts WHERE games<0 OR own<0 OR chooser<0 OR own+chooser>games').fetchone()[0]:raise RuntimeError('Impossible pair-excluded environment counts')
            sql='SELECT *,complete AND games>0 AS environment_supported,CASE WHEN complete AND games>0 THEN own::DOUBLE/games ELSE NULL END opponent_observed_disconnect_rate,CASE WHEN complete AND games>0 THEN chooser::DOUBLE/games ELSE NULL END opponent_observed_chooser_rate,CASE WHEN complete AND games>0 THEN ln(1+games) ELSE NULL END log_opponent_games90 FROM counts'
            rows=io.copy(c,sql+' ORDER BY person,partner,month_code',tmp/'rates.parquet')
            cover=[dict(complete=bool(a),positive_denominator=bool(b),request_rows=n) for a,b,n in c.execute('SELECT complete,games>0,count(*) FROM counts GROUP BY 1,2 ORDER BY 1,2').fetchall()]
            io.js(tmp/'coverage.json',dict(coverage=cover,matched_numerator_counts=list(actual),focal_pair_excluded_from_both_counts=True))
            return dict(rows=rows)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[req/'requests.parquet']+[Path(r)/(v+'.parquet') for r in partroots for v in ('person','pair')]+events)

def attach(input_path,rates,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([input_path]))
            c.execute('CREATE VIEW r AS SELECT * FROM '+io.parq([rates]))
            n=pq.ParquetFile(input_path).metadata.num_rows
            incoming=set(pq.ParquetFile(rates).schema_arrow.names)-{'person','partner','month_code'}
            collisions=incoming & set(pq.ParquetFile(input_path).schema_arrow.names)
            if collisions:raise RuntimeError('Unexpected existing environment columns: '+str(sorted(collisions)))
            fields='a.*,r.* EXCLUDE(person,partner,month_code)'
            join=' FROM a JOIN r ON a.opponent_id=r.person AND a.recipient_id=r.partner AND a.month_code=r.month_code'
            if c.execute('SELECT count(*),count(DISTINCT a.row_id)'+join).fetchone()!=(n,n):raise RuntimeError('Environment join changed rows')
            io.copy(c,'SELECT '+fields+join+' ORDER BY a.row_id',tmp/'model.parquet')
            return dict(rows=n,environment_supported=c.execute('SELECT count(*)'+join+' WHERE r.environment_supported').fetchone()[0])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[input_path,rates])
