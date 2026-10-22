"""One shared, projected chronology pass; monthly carry avoids a second huge event copy."""
from util import *
import concurrent.futures as cf

def merit_imports():
    sys.path.insert(0,str(ROOT/'vendor/merit'))
    sys.path.insert(0,str(ROOT/'vendor/merit/source'))
    import pool_wave1_common as authority
    import prepare as projection
    return authority,projection

def catalog(project):
    authority,_=merit_imports()
    main=authority.authenticate_sample(Path(project)/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE',verify_hashes=False,hash_workers=1)
    require(main['fingerprint']=='a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30','Wrong main sample')
    manifest=ROOT/'authority/chronology.tsv'
    require(sha(manifest)=='c169bf9e346defde62047a3c2048758c296b1f0598fee70d2cc1e660121536d8','Chronology authority damaged')
    rows=pd.read_csv(manifest,sep='\t').to_dict('records')
    require(len(rows)==852 and sum(int(r['rows']) for r in rows)==7763847245,'Chronology manifest totals changed')
    used=[]
    for r in rows:
        speed=re.search(r'speed=([^/]+)',r['path'])[1].lower();month=re.search(r'month=([0-9-]+)',r['path'])[1]
        if speed not in SPEEDS or month>'2025-10':continue
        p=relocated(r['path'],project);f=pq.ParquetFile(p)
        require(p.stat().st_size==int(r['bytes']) and f.metadata.num_rows==int(r['rows']),'Chronology footer/count mismatch: '+str(p))
        require({'white_id','black_id','utc_ms','game_id','archive_ordinal','result_code','white_rating_diff','black_rating_diff'}<=set(f.schema_arrow.names),'Chronology fields missing')
        used.append(dict(path=str(p),bytes=int(r['bytes']),rows=int(r['rows']),month=month,speed=speed,speed_code=SPEEDS.index(speed),stat=snapshot(p)))
    for speed in SPEEDS:
        got={r['month'] for r in used if r['speed']==speed}
        require({'2023-10',*MONTHS}<=got,'Incomplete recent chronology: '+speed)
    return dict(main=main,chronology=used,history_semantics='observed rated starts, standard real-time speeds, history beginning 2013')

def project_job(task):
    r,run,key=task;out=Path(run)/'PRIVATE/focal'/r['month'];k=digest([key,r['expected_sha256']])
    if cached(out,k):return str(out/'rows.parquet')
    from resume import parent_root,parent_key,adopt_checkpoint
    if adopt_checkpoint(parent_root(run)/'PRIVATE/focal'/r['month'],out,
            digest([parent_key(),r['expected_sha256']]),k,r['path']):
        return str(out/'rows.parquet')
    _,projection=merit_imports();src=Path(r['path']);auth=checked(src,r['expected_sha256'])
    c=db(out/'spill',2,1)
    try:
        c.execute('CREATE VIEW src AS SELECT * FROM '+scan(src))
        bad=c.execute('''SELECT count(*) FROM src WHERE game_id IS NULL OR utc_ms IS NULL OR utc_ms<=0
          OR chooser_user_id IS NULL OR outcome_kind_draw IS NULL OR engine_eval_cp_disconnected IS NULL
          OR engine_eval_is_mate IS NULL OR ply_count IS NULL OR
          NOT coalesce(sf100k_nodes_requested=100000 AND sf100k_fen_turn_matches_disconnected_color
          AND side_to_move_after_last=disconnected_color AND api_status='timeout' AND five_second_rule_passed,false)''').fetchone()[0]
        require(bad==0,'Invalid focal chronology/evaluation fields')
        sql=projection.projection_sql('src',r['month']).replace('SELECT ', 'SELECT game_id::VARCHAR game_id,utc_ms::BIGINT t,archive_ordinal::BIGINT ordinal,',1)
        n=copy(c,sql,out/'rows.parquet');require(n==r['rows'],'Focal projection changed sample size')
        require(c.execute('SELECT count(DISTINCT game_id) FROM '+scan(out/'rows.parquet')).fetchone()[0]==n,'Duplicate focal game')
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    unchanged([auth]);commit(out,k,source=auth,rows=n);return str(out/'rows.parquet')

def prefix_job(task):
    r,run,key=task;out=Path(run)/'PRIVATE/prefix'/(r['speed']+'_'+r['month']);k=digest([key,r])
    from timestamp_recovery import overlay_path
    overlay=overlay_path(run,r['path'],key)
    if overlay:k=digest([key,r,sha(overlay),sha(overlay.parent/'overlay_receipt.json')])
    if cached(out,k):return str(out/'counts.parquet')
    from resume import parent_root,parent_key,adopt_checkpoint
    if not overlay and adopt_checkpoint(parent_root(run)/'PRIVATE/prefix'/(r['speed']+'_'+r['month']),out,
            digest([parent_key(),r]),k,r['path']):return str(out/'counts.parquet')
    require(snapshot(r['path'])==r['stat'],'Chronology changed after preflight')
    # Hash the consumed file once. All Parquet computation projects three columns.
    auth=checked(r['path']);c=db(out/'spill',1.5,1)
    try:
        c.execute('CREATE VIEW needed AS SELECT chooser FROM '+scan(Path(run)/'PRIVATE/needed.parquet'))
        if overlay:
            c.execute('CREATE VIEW correction AS SELECT * FROM '+scan(overlay))
            c.execute('CREATE TEMP TABLE raw AS SELECT s.white_id,s.black_id,CASE WHEN o.game_id IS NOT NULL '
                'AND (s.utc_ms IS NULL OR s.utc_ms<=0) THEN o.utc_ms ELSE s.utc_ms END utc_ms FROM '+scan(r['path'])+
                ' s LEFT JOIN correction o USING(game_id,white_id,black_id) WHERE '
                's.white_id IN(SELECT chooser FROM needed) OR s.black_id IN(SELECT chooser FROM needed)')
        else:
            c.execute('CREATE TEMP TABLE raw AS SELECT white_id,black_id,utc_ms FROM '+scan(r['path'])+
                ' WHERE white_id IN(SELECT chooser FROM needed) OR black_id IN(SELECT chooser FROM needed)')
        bound=int(pd.Timestamp('2023-10-01',tz='UTC').timestamp()*1000)
        require(c.execute(f'SELECT count(*) FROM raw WHERE utc_ms IS NULL OR utc_ms<=0 OR utc_ms>={bound}').fetchone()[0]==0,
            'Invalid analysis-chooser prefix timestamp: '+r['path']+'; see TIMESTAMP_AUDIT.json')
        n=copy(c,f'''WITH e AS (SELECT white_id::BIGINT chooser,utc_ms::BIGINT t FROM raw
            UNION ALL SELECT black_id::BIGINT chooser,utc_ms::BIGINT t FROM raw)
            SELECT chooser,{r['speed_code']}::TINYINT speed_code,count(*)::BIGINT n,max(t)::BIGINT last_t
            FROM e JOIN needed USING(chooser) GROUP BY chooser''',out/'counts.parquet')
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    unchanged([auth]);commit(out,k,source=auth,rows=n,verified_timestamp_overlay=str(overlay) if overlay else None);return str(out/'counts.parquet')

def initial_state(run,prefix,key,threads,memory):
    out=Path(run)/'PRIVATE/history/initial'
    if cached(out,key):return out
    c=db(out/'spill',memory,threads)
    try:
        copy(c,'SELECT chooser,speed_code,sum(n)::BIGINT n,max(last_t)::BIGINT last_t FROM '+scan(prefix)+' GROUP BY chooser,speed_code',out/'counts.parquet')
        copy(c,'''SELECT chooser,max(last_t)::BIGINT last_t,NULL::VARCHAR last_gid,
            NULL::INTEGER last_result,NULL::DOUBLE last_diff,2::INTEGER last_tie,
            0::BIGINT pos15,0::BIGINT pos30,0::BIGINT pos60,
            true cens15,true cens30,true cens60,NULL::BIGINT start30 FROM '''+scan(out/'counts.parquet')+' GROUP BY chooser',out/'carry.parquet')
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    commit(out,key);return out

def month_history(month,records,run,previous,key,threads,memory):
    out=Path(run)/'PRIVATE/history'/month
    k=digest([key,month,sha(previous/'_DONE.json'),[r['stat'] for r in records]])
    if cached(out,k):return out
    for r in records:require(snapshot(r['path'])==r['stat'],'History source changed after timestamp audit: '+r['path'])
    auth=[checked(r['path']) for r in records]
    c=db(out/'spill',memory,threads)
    try:
        c.execute('CREATE VIEW needed AS SELECT chooser FROM '+scan(Path(run)/'PRIVATE/needed.parquet'))
        c.execute('CREATE VIEW carry AS SELECT * FROM '+scan(previous/'carry.parquet'))
        c.execute('CREATE VIEW counts AS SELECT * FROM '+scan(previous/'counts.parquet'))
        parts=[f'''SELECT game_id::VARCHAR game_id,utc_ms::BIGINT t,archive_ordinal::BIGINT ordinal,
            white_id::BIGINT white_id,black_id::BIGINT black_id,result_code::INTEGER result_code,
            white_rating_diff::DOUBLE white_diff,black_rating_diff::DOUBLE black_diff,{r['speed_code']}::TINYINT speed_code
            FROM {scan(r['path'])} WHERE white_id IN(SELECT chooser FROM needed)
            OR black_id IN(SELECT chooser FROM needed)''' for r in records]
        c.execute('CREATE TEMP TABLE raw AS '+' UNION ALL '.join(parts))
        lo=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)
        hi=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin()).timestamp()*1000)
        require(c.execute(f'''SELECT count(*) FROM raw WHERE result_code IS NULL OR result_code NOT IN (0,1,2)
            OR t IS NULL OR t<{lo} OR t>={hi} OR white_id IS NULL OR black_id IS NULL OR game_id IS NULL OR white_id=black_id''').fetchone()[0]==0,'Invalid history result code/time or month boundary')
        c.execute('''CREATE TEMP TABLE events AS WITH e AS (
            SELECT game_id,t,ordinal,white_id chooser,speed_code,result_code-1 result,white_diff rating_diff FROM raw
            UNION ALL SELECT game_id,t,ordinal,black_id chooser,speed_code,1-result_code result,black_diff rating_diff FROM raw)
            SELECT e.*,count(*) OVER(PARTITION BY chooser,t)::INTEGER tie_n FROM e JOIN needed USING(chooser)''')
        c.execute('DROP TABLE raw')
        # No start ordered outcome is called an ordinary completed loss. These keys
        # are retained privately for a later join to actual ending metadata.
        c.execute('''CREATE TEMP TABLE ordered AS SELECT e.*,
            coalesce(lag(t) OVER w,a.last_t) prev_t,
            coalesce(lag(game_id) OVER w,a.last_gid) prev_gid,
            coalesce(lag(result) OVER w,a.last_result) prev_result,
            coalesce(lag(tie_n) OVER w,a.last_tie) prev_tie,
            coalesce(a.pos15,0) carry15,coalesce(a.pos30,0) carry30,coalesce(a.pos60,0) carry60,
            coalesce(a.cens15,true) carry_cens15,coalesce(a.cens30,true) carry_cens30,coalesce(a.cens60,true) carry_cens60,
            a.start30 carry_start30,
            coalesce(b.n,0)+count(*) OVER(PARTITION BY e.chooser,e.speed_code ORDER BY t
                RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)::BIGINT prior_same_speed
            FROM events e LEFT JOIN carry a USING(chooser) LEFT JOIN counts b USING(chooser,speed_code)
            WINDOW w AS (PARTITION BY e.chooser ORDER BY e.t,e.ordinal,e.game_id)''')
        c.execute('DROP TABLE events')
        breaks=','.join(f'''sum(CASE WHEN prev_t IS NULL OR t-prev_t>={g}*60000 THEN 1 ELSE 0 END)
            OVER(PARTITION BY chooser ORDER BY t,ordinal,game_id ROWS UNBOUNDED PRECEDING)::BIGINT sid{g}''' for g in (15,30,60))
        c.execute('CREATE TEMP TABLE sessions AS SELECT *, '+breaks+' FROM ordered')
        c.execute('DROP TABLE ordered')
        cols=[]
        for g in (15,30,60):
            cols += [f'row_number() OVER(PARTITION BY chooser,sid{g} ORDER BY t,ordinal,game_id)+CASE WHEN sid{g}=0 THEN carry{g} ELSE 0 END AS pos{g}',
                f'(sid{g}=0 AND carry_cens{g}) AS cens{g}']
        cols.append('CASE WHEN sid30=0 THEN coalesce(carry_start30,min(t) OVER(PARTITION BY chooser,sid30)) ELSE min(t) OVER(PARTITION BY chooser,sid30) END AS start30')
        c.execute('CREATE TEMP TABLE annotated AS SELECT *, '+','.join(cols)+' FROM sessions')
        c.execute('DROP TABLE sessions')
        # Speed counts and last session position carry across all calendar boundaries.
        copy(c,'''WITH fresh AS (SELECT chooser,speed_code,count(*)::BIGINT n,max(t)::BIGINT last_t
            FROM annotated GROUP BY chooser,speed_code),combined AS (SELECT * FROM counts UNION ALL SELECT * FROM fresh)
            SELECT chooser,speed_code,sum(n)::BIGINT n,max(last_t)::BIGINT last_t FROM combined GROUP BY chooser,speed_code''',out/'counts.parquet')
        latest='''SELECT chooser,t AS last_t,game_id AS last_gid,result AS last_result,rating_diff AS last_diff,tie_n AS last_tie,
            pos15,pos30,pos60,cens15,cens30,cens60,start30 FROM annotated
            QUALIFY row_number() OVER(PARTITION BY chooser ORDER BY t DESC,ordinal DESC,game_id DESC)=1'''
        c.execute('CREATE TEMP TABLE latest AS '+latest)
        copy(c,'SELECT * FROM latest UNION ALL SELECT carry.* FROM carry ANTI JOIN latest USING(chooser)',out/'carry.parquet')
        qa=dict(month=month,history_rows=c.execute('SELECT count(*) FROM annotated').fetchone()[0])
        if month in MONTHS:
            c.execute('CREATE VIEW focal AS SELECT * FROM '+scan(Path(run)/'PRIVATE/focal'/month/'rows.parquet'))
            checks=c.execute('''SELECT count(*),count(*) FILTER(WHERE a.game_id IS NULL),count(*) FILTER(WHERE
                f.t IS DISTINCT FROM a.t OR f.speed_code IS DISTINCT FROM a.speed_code)
                FROM focal f LEFT JOIN annotated a USING(chooser,game_id)''').fetchone()
            expected=pq.ParquetFile(Path(run)/'PRIVATE/focal'/month/'rows.parquet').metadata.num_rows
            require(checks==(expected,0,0),'Focal/history identity mismatch: '+str(checks))
            cols=['prior_same_speed','tie_n','prev_t','prev_gid','prev_result','prev_tie']+[str(n)+str(g) for g in (15,30,60) for n in ('pos','cens')]
            copy(c,'SELECT f.*,'+','.join('a.'+x for x in cols)+' FROM focal f JOIN annotated a USING(chooser,game_id)',out/'focal_history.parquet')
            qa.update(focal_rows=expected,tied_focal_rows=c.execute('SELECT count(*) FROM focal f JOIN annotated a USING(chooser,game_id) WHERE tie_n>1').fetchone()[0])
        # Descriptive composition at each session-position band, including complete
        # all-rated histories, does not use future length as a regression control.
        copy(c,'''SELECT chooser,start30,max(pos30)::BIGINT observed_session_length,
            bool_or(cens30) left_censored,max(t) last_t
            FROM annotated GROUP BY chooser,start30''',out/'sessions30.parquet')
        js(out/'QA.json',qa)
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    unchanged(auth);commit(out,k,sources=auth,**qa)
    log(month+': history linked; '+format(qa.get('focal_rows',0),',')+' focal opportunities')
    return out

def parallel_jobs(fn,tasks,workers,label):
    done=[];t0=time.monotonic()
    with cf.ProcessPoolExecutor(max_workers=workers) as ex:
        futures=[ex.submit(fn,t) for t in tasks]
        with heartbeat(label):
            for f in cf.as_completed(futures):
                done.append(f.result())
                if len(done)%10==0 or len(done)==len(tasks):
                    elapsed=time.monotonic()-t0;eta=elapsed/max(1,len(done))*(len(tasks)-len(done))/60
                    log(f'{label}: {len(done)}/{len(tasks)}; measured remaining ~{eta:.0f} min')
    return done

def prepare_history(cat,run,key,budget,io_workers,memory):
    workers,_=slots(budget,io_workers)
    files=parallel_jobs(project_job,[(r,str(run),key) for r in cat['main']['month_records']],workers,'Projecting certified pool sample')
    c=db(Path(run)/'PRIVATE/spill_needed',memory,workers)
    try:copy(c,'SELECT DISTINCT chooser FROM '+scan(files),Path(run)/'PRIVATE/needed.parquet')
    finally:c.close();shutil.rmtree(Path(run)/'PRIVATE/spill_needed',ignore_errors=True)
    from resume import timestamp_audit
    audit=timestamp_audit(cat,run)
    from timestamp_recovery import recover
    return recover(cat,run,key,audit)

def run_history(cat,run,key,budget,io_workers,memory):
    audit=load(Path(run)/'report/TIMESTAMP_AUDIT.json')
    require(audit['status'] in ('PASS_NO_ANALYSIS_CHOOSER_AFFECTED','PASS_VERIFIED_TIMESTAMP_OVERLAY'),
        'History remains blocked: invalid timestamps involve analysis choosers. See TIMESTAMP_AUDIT.json; no rows or accounts silently dropped.')
    prefix=[r for r in cat['chronology'] if r['month']<'2023-10']
    workers,_=slots(budget,io_workers)
    pf=parallel_jobs(prefix_job,[(r,str(run),key) for r in prefix],workers,'Counting prior rated starts')
    threads,_=slots(budget,min(4,budget))
    prev=initial_state(run,pf,key,threads,memory)
    for month in ['2023-10']+MONTHS:
        threads,_=slots(budget,min(4,budget))
        with heartbeat('Reconstructing sessions '+month):
            prev=month_history(month,[r for r in cat['chronology'] if r['month']==month],run,prev,key,threads,memory)
    return [str(Path(run)/'PRIVATE/history'/m/'focal_history.parquet') for m in MONTHS]
