"""Fixed pre-implementation eligibility and incremental exact start histories."""
from mc_io import *

def activity_candidates(speed,records,work,memory):
    work=Path(work);ps=[r['path'] for r in records if r['speed']==speed and r['month'] in ('2025-10','2025-11')]
    inputs=[auth(p,work) for p in ps];out=work/'candidates'/(speed+'.parquet')
    key=digest(dict(version=VERSION,inputs=inputs,cutoff=IMPLEMENTED,definition='four_strict_prior_7day_start_windows'))
    if cache(out,key,work):return str(out)
    c=connect(work/'tmp'/('candidates_'+speed),2,memory)
    try:
        terms=[f'bool_or(t>={IMPLEMENTED-j*WEEK} AND t<{IMPLEMENTED-(j-1)*WEEK}) w{j}' for j in range(1,5)]
        sql=f'''WITH e AS (SELECT UNNEST([white_id,black_id]) user_id,utc_ms t FROM {scan(ps)}
            WHERE utc_ms>={IMPLEMENTED-4*WEEK} AND utc_ms<{IMPLEMENTED} AND white_id<>black_id
            AND white_id IS NOT NULL AND black_id IS NOT NULL), a AS (
            SELECT user_id,{','.join(terms)} FROM e GROUP BY user_id)
            SELECT user_id,{q(speed)}::VARCHAR speed FROM a WHERE w1 AND w2 AND w3 AND w4'''
        copy(c,sql,out);unchanged(inputs);commit(out,key,input_snapshots=inputs,uses_post_policy_activity=False)
        return str(out)
    finally:c.close()

def needed_users(candidates,post,old_needed,work,memory):
    work=Path(work);out=work/'history_needed.parquet';missing=work/'history_missing_from_old.parquet'
    inputs=[auth(p,work) for p in [*candidates,*post,old_needed]]
    key=digest(dict(version=VERSION,inputs=inputs))
    if cache(out,key,work) and cache(missing,key,work):return str(out),str(missing)
    c=connect(work/'tmp/needed',2,memory)
    try:
        copy(c,f'''SELECT DISTINCT speed,user_id FROM {scan(candidates)} UNION
            SELECT DISTINCT speed,chooser user_id FROM {scan(post)} UNION SELECT DISTINCT speed,opponent FROM {scan(post)}''',out)
        copy(c,f'SELECT n.* FROM {scan(out)} n ANTI JOIN {scan(old_needed)} o USING(speed,user_id)',missing)
        unchanged(inputs);commit(out,key,input_snapshots=inputs);commit(missing,key,input_snapshots=inputs)
        return str(out),str(missing)
    finally:c.close()

def summary_job(job):
    rec,needed,missing,old_needed,work,memory=job;work=Path(work);p=Path(rec['path']);speed=rec['speed'];month=rec['month']
    cached_old=Path(rec['old_summary']) if rec.get('old_summary') else None
    old_valid=False;ins=[auth(needed,work),auth(missing,work)]
    if cached_old is not None and cached_old.is_file() and cached_old.with_suffix('.json').is_file():
        r=read(cached_old.with_suffix('.json'));evidence=r.get('source',{});f=evidence.get('fingerprint',{})
        actual=stamp(p);simple={k:actual[k] for k in ('path','size','mtime_ns')}
        old_need_stamp={k:v for k,v in stamp(old_needed).items() if k!='ctime_ns'}
        expected=digest(dict(version='1.0.0',input=evidence,needed=old_need_stamp,semantics='prior_recorded_starts'))
        if f!=simple or r.get('key')!=expected:raise RuntimeError('Existing history summary lineage changed: '+speed+'/'+month)
        ins.append(record_auth(cached_old,r['output'],work));old_valid=True
    if old_valid:
        # The original byte hash and exact recorded fingerprint are inherited;
        # do not reread a multi-billion-game archive merely to copy its counts.
        source=dict(path=str(p.resolve()),sha256=evidence['sha256'],fingerprint=stamp(p))
        write(work/'authentication'/(digest(str(p.resolve()))+'.json'),source)
    else:source=auth(p,work,rows=rec['rows'],size=rec['size'])
    ins.append(source)
    out=work/'history_summary'/f'{speed}_{month}.parquet';key=digest(dict(version=VERSION,inputs=ins,old_valid=old_valid))
    if cache(out,key,work):return str(out)
    c=connect(work/'tmp'/('summary_'+speed+'_'+month),2,memory)
    try:
        selected=missing if old_valid else needed
        c.execute(f'CREATE VIEW users AS SELECT user_id FROM {scan(selected)} WHERE speed={q(speed)}')
        nusers=c.execute('SELECT count(*) FROM users').fetchone()[0]
        delta='SELECT NULL::BIGINT user_id,0::BIGINT n,NULL::BIGINT first_ms,NULL::BIGINT last_ms WHERE FALSE'
        if nusers:
            delta=f'''SELECT e.user_id,count(*)::BIGINT n,min(e.utc_ms)::BIGINT first_ms,max(e.utc_ms)::BIGINT last_ms
                FROM (SELECT UNNEST([white_id,black_id]) user_id,utc_ms FROM {scan(p)}
                WHERE white_id<>black_id) e SEMI JOIN users u USING(user_id) GROUP BY e.user_id'''
        if old_valid:
            old=f'SELECT h.user_id,h.n,h.first_ms,h.last_ms FROM {scan(cached_old)} h SEMI JOIN (SELECT user_id FROM {scan(needed)} WHERE speed={q(speed)}) u USING(user_id)'
            sql=old+' UNION ALL '+delta
        else:sql=delta
        copy(c,sql,out)
        bad=c.execute(f'SELECT count(*)-count(DISTINCT user_id),count(*) FILTER(WHERE n<=0 OR first_ms>last_ms) FROM {scan(out)}').fetchone()
        if bad!=(0,0):raise RuntimeError('History summary conservation failed')
        unchanged(ins);commit(out,key,input_snapshots=ins,reused_old_summary=old_valid,newly_counted_users=nusers,speed=speed,month=month)
        log(f'History {speed}/{month}: cached users reused={old_valid}; missing-user set={nusers:,}')
        return str(out)
    finally:c.close()

def roster(speed,records,candidate,work,memory):
    work=Path(work);summaries=[work/'history_summary'/f'{speed}_{r["month"]}.parquet' for r in records if r['speed']==speed and r['month']<'2025-11']
    curr=[r['path'] for r in records if r['speed']==speed and r['month']=='2025-11']
    ins=[auth(p,work) for p in [candidate,*summaries,*curr]];out=work/'roster'/(speed+'.parquet')
    key=digest(dict(version=VERSION,inputs=ins,cutoff=IMPLEMENTED))
    if cache(out,key,work):return str(out)
    c=connect(work/'tmp'/('roster_'+speed),2,memory)
    try:
        c.execute('CREATE VIEW u AS SELECT * FROM '+scan(candidate))
        c.execute(f'''CREATE VIEW p AS SELECT h.user_id,sum(n)::BIGINT n,min(first_ms)::BIGINT first_ms,max(last_ms)::BIGINT last_ms
            FROM {scan(summaries)} h SEMI JOIN u USING(user_id) GROUP BY h.user_id''')
        c.execute(f'''CREATE VIEW e AS SELECT x.user_id,count(*)::BIGINT n,min(utc_ms)::BIGINT first_ms,max(utc_ms)::BIGINT last_ms
            FROM (SELECT UNNEST([white_id,black_id]) user_id,utc_ms FROM {scan(curr)}
            WHERE utc_ms<{IMPLEMENTED} AND white_id<>black_id) x SEMI JOIN u USING(user_id) GROUP BY x.user_id''')
        sql=f'''WITH a AS (SELECT u.*,coalesce(p.n,0)+coalesce(e.n,0) prior_starts,
            least(p.first_ms,e.first_ms) first_ms,greatest(p.last_ms,e.last_ms) last_ms
            FROM u LEFT JOIN p USING(user_id) LEFT JOIN e USING(user_id))
            SELECT *,({IMPLEMENTED}-first_ms)/{DAY}.0 history_days,
            prior_starts>=100 AND first_ms<={IMPLEMENTED-365*DAY} fixed_regular_cohort FROM a'''
        copy(c,sql,out)
        bad=c.execute(f'SELECT count(*) FROM {scan(out)} WHERE last_ms>={IMPLEMENTED} OR first_ms>last_ms').fetchone()[0]
        if bad:raise RuntimeError('Post-policy activity reached the fixed roster')
        unchanged(ins);commit(out,key,input_snapshots=ins,eligibility_date_ms=IMPLEMENTED,post_activity_required=False)
        return str(out)
    finally:c.close()

def feature_job(job):
    speed,month,records,base,work,memory=job;work=Path(work)
    prev=str(pd.Period(month,'M')-1)
    current=[r['path'] for r in records if r['speed']==speed and r['month']==month]
    local=[r['path'] for r in records if r['speed']==speed and r['month'] in (month,prev)]
    summary=[work/'history_summary'/f'{speed}_{r["month"]}.parquet' for r in records if r['speed']==speed and r['month']<month]
    ins=[auth(p,work) for p in [base,*local,*summary]];out=work/'post_features'/f'{speed}_{month}.parquet'
    key=digest(dict(version=VERSION,inputs=ins,speed=speed,month=month))
    if cache(out,key,work):return str(out)
    start=ms(month+'-01T00:00:00Z');c=connect(work/'tmp'/('features_'+speed+'_'+month),2,memory)
    try:
        c.execute(f'''CREATE TEMP TABLE t AS SELECT game_id,chooser user_id,t,1 AS role FROM {scan(base)} WHERE speed={q(speed)}
            UNION ALL SELECT game_id,opponent,t,0 FROM {scan(base)} WHERE speed={q(speed)}''')
        c.execute('CREATE VIEW u AS SELECT DISTINCT user_id FROM t')
        n=c.execute('SELECT count(*) FROM t').fetchone()[0]
        mapped=c.execute(f'''SELECT count(*),count(*) FILTER(WHERE e.game_id IS NULL OR t.user_id NOT IN(e.white_id,e.black_id)
            OR abs(t.t-e.utc_ms)>1000) FROM t LEFT JOIN {scan(current)} e USING(game_id)''').fetchone()
        if mapped!=(n,0):raise RuntimeError('Focal start identity mismatch')
        c.execute(f'UPDATE t SET t=e.utc_ms FROM {scan(current)} e WHERE t.game_id=e.game_id')
        c.execute(f'''CREATE VIEW p AS SELECT h.user_id,sum(n)::BIGINT n,min(first_ms)::BIGINT first_ms,max(last_ms)::BIGINT last_ms
            FROM {scan(summary)} h SEMI JOIN u USING(user_id) GROUP BY h.user_id''')
        c.execute(f'''CREATE TEMP TABLE e AS WITH a AS (SELECT x.user_id,utc_ms::BIGINT event_ms,count(*)::BIGINT n
            FROM (SELECT UNNEST([white_id,black_id]) user_id,utc_ms FROM {scan(local)} WHERE white_id<>black_id) x
            SEMI JOIN u USING(user_id) GROUP BY x.user_id,utc_ms)
            SELECT *,sum(CASE WHEN event_ms>={start} THEN n ELSE 0 END) OVER(PARTITION BY user_id ORDER BY event_ms)::BIGINT current_count,
            min(event_ms) OVER(PARTITION BY user_id)::BIGINT first_local FROM a''')
        # Strict greater-than excludes the focal game and every simultaneous start.
        sql=f'''WITH z AS (SELECT t.*,e.event_ms,e.current_count,e.first_local FROM t ASOF LEFT JOIN e
            ON t.user_id=e.user_id AND t.t>e.event_ms)
            SELECT z.game_id,z.role,z.t history_anchor_ms,
            coalesce(p.n,0)+coalesce(z.current_count,0) prior_starts,
            CASE WHEN coalesce(p.first_ms,z.first_local)<z.t THEN (z.t-coalesce(p.first_ms,z.first_local))/{DAY}.0 ELSE 0 END history_days,
            CASE WHEN coalesce(z.event_ms,p.last_ms)<z.t THEN (z.t-coalesce(z.event_ms,p.last_ms))/{DAY}.0 ELSE 0 END inactivity_days
            FROM z LEFT JOIN p USING(user_id)'''
        copy(c,sql,out)
        nn,nu=c.execute(f'SELECT count(*),count(DISTINCT (game_id,role)) FROM {scan(out)}').fetchone()
        if nn!=n or nu!=n:raise RuntimeError('Post history features lost/duplicated targets')
        unchanged(ins);commit(out,key,input_snapshots=ins,strict_prior_starts=True,zero_history_days_only_when_no_prior=True)
        return str(out)
    finally:c.close()

def exposure_job(job):
    rec,roster_paths,work,memory=job;work=Path(work);p=rec['path'];s=rec['speed'];m=rec['month']
    ins=[auth(x,work) for x in [p,*roster_paths]];key=digest(dict(version=VERSION,inputs=ins))
    out=work/'exposure'/f'{s}_{m}.parquet'
    if cache(out,key,work):return str(out)
    c=connect(work/'tmp'/('exposure_'+s+'_'+m),2,memory)
    try:
        copy(c,f'''SELECT {q(s)} speed,epoch_ms(date_trunc('week',epoch_ms(e.utc_ms)))::BIGINT week_ms,v.color,
            count(*) rated_player_starts,count(DISTINCT v.user_id) active_roster_accounts
            FROM {scan(p)} e CROSS JOIN LATERAL (VALUES (white_id,'white'),(black_id,'black')) v(user_id,color)
            JOIN {scan(roster_paths)} r ON v.user_id=r.user_id AND r.speed={q(s)}
            WHERE r.fixed_regular_cohort AND e.white_id<>e.black_id GROUP BY ALL''',out)
        unchanged(ins);commit(out,key,input_snapshots=ins);return str(out)
    finally:c.close()
