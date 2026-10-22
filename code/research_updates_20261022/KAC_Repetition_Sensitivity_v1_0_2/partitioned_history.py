"""Resumable monthly sessions; bounded annotation replaces the large window step."""
from util import *
from history_checks import Checks,FEATURES
from partition_annotation import worker

BUCKETS=512

def ident(s):return '"'+s.replace('"','""')+'"'

def full_signature(c,relation,columns):
    a=','.join(map(ident,columns));b=','.join(map(ident,reversed(columns)))
    row=c.execute(f'SELECT count(*),bit_xor(hash({a})),sum(hash({b})::HUGEINT) FROM {relation}').fetchone()
    return [str(int(x or 0)) for x in row]

def create_inputs(month,records,run,previous,key,threads,memory,work):
    out=work/'inputs';k=digest([key,'session_partitions',BUCKETS])
    if cached(out,k):
        rec=load(out/'_DONE.json');unchanged(rec['sources'])
        return out
    auth=[checked(r['path']) for r in records]
    c=db(work/'spill_input',memory,threads)
    try:
        c.execute('CREATE TEMP TABLE needed AS SELECT chooser FROM '+scan(Path(run)/'PRIVATE/needed.parquet'))
        checks_tracker=Checks(c,run,month,Path(run)/'PRIVATE/history'/month)
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
        checks_tracker.raw()
        c.execute('''CREATE TEMP TABLE events AS WITH e AS (
            SELECT game_id,t,ordinal,white_id chooser,speed_code,result_code-1 result,white_diff rating_diff
            FROM raw r SEMI JOIN needed n ON r.white_id=n.chooser
            UNION ALL SELECT game_id,t,ordinal,black_id chooser,speed_code,1-result_code result,black_diff rating_diff
            FROM raw r SEMI JOIN needed n ON r.black_id=n.chooser)
            SELECT e.*,count(*) OVER(PARTITION BY chooser,t)::INTEGER tie_n FROM e''')
        checks_tracker.stage('events')
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
        checks_tracker.stage('ordered')
        c.execute('DROP TABLE events')
        breaks=','.join(f'''sum(CASE WHEN prev_t IS NULL OR t-prev_t>={g}*60000 THEN 1 ELSE 0 END)
            OVER(PARTITION BY chooser ORDER BY t,ordinal,game_id ROWS UNBOUNDED PRECEDING)::BIGINT sid{g}''' for g in (15,30,60))
        c.execute('CREATE TEMP TABLE sessions AS SELECT *, '+breaks+' FROM ordered')
        checks_tracker.stage('sessions')
        c.execute('DROP TABLE ordered')
        columns=[r[0] for r in c.execute('DESCRIBE sessions').fetchall()]
        before=full_signature(c,'sessions',columns)
        temp=out/'rows.partial';final=out/'rows'
        if temp.exists():shutil.rmtree(temp)
        out.mkdir(parents=True,exist_ok=True)
        c.execute('COPY (SELECT *,chooser%'+str(BUCKETS)+' AS bucket FROM sessions) TO '+q(temp)+
            ' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket),ROW_GROUP_SIZE 131072)')
        if final.exists():shutil.rmtree(final)
        temp.rename(final)
        files=sorted(final.glob('bucket=*/*.parquet'));require(files,'No session partitions written')
        c.execute('CREATE VIEW partitioned_sessions AS SELECT '+','.join(map(ident,columns))+' FROM '+scan(files))
        checks_tracker.stage('partitioned_sessions')
        after=full_signature(c,'partitioned_sessions',columns)
        require(before==after,'Full session values changed while partitioning')
        checks_tracker.report.update(status='SESSION_INPUTS_VERIFIED',
            full_session_values_before=before,full_session_values_after=after,
            partition_buckets=BUCKETS,annotation_method='Arrow and NumPy; whole chooser partitions')
        checks_tracker.write();js(out/'CHECKS.json',checks_tracker.report)
    finally:c.close();shutil.rmtree(work/'spill_input',ignore_errors=True)
    unchanged(auth);commit(out,k,sources=auth,columns=columns,rows=int(before[0]))
    log(month+': session inputs checkpointed; '+format(int(before[0]),',')+' player events')
    return out

def run_month(month,records,run,previous,key,threads,memory):
    run=Path(run);previous=Path(previous);out=run/'PRIVATE/history'/month
    k=digest([key,month,sha(previous/'_DONE.json'),[r['stat'] for r in records]])
    if cached(out,k):return out
    for r in records:require(snapshot(r['path'])==r['stat'],'History source changed after preflight')
    work=run/'PRIVATE/history_work'/month
    inputs=create_inputs(month,records,run,previous,k,threads,memory,work)
    receipt=load(inputs/'_DONE.json');columns=receipt['columns'];input_sha=sha(inputs/'_DONE.json')
    tasks=[]
    for folder in sorted((inputs/'rows').glob('bucket=*'),key=lambda p:int(p.name.split('=')[1])):
        bucket=int(folder.name.split('=')[1]);paths=sorted(folder.glob('*.parquet'))
        require(0<=bucket<BUCKETS and paths,'Invalid chooser partition')
        task_key=digest([k,input_sha,bucket,'numpy_annotation_v1'])
        tasks.append((paths,str(work/'annotated'/str(bucket)),task_key,bucket,BUCKETS,columns))
    cap=max(1,min(threads,3,int(memory/2)))
    from history import parallel_jobs
    destinations=sorted(parallel_jobs(worker,tasks,cap,'Annotating sessions '+month))
    row_total=sum(load(Path(p)/'CHECKS.json')['rows'] for p in destinations)
    require(row_total==receipt['rows'],'Annotation partition row count differs')
    c=db(work/'spill_finalize',memory,threads)
    try:
        c.execute('CREATE TEMP TABLE needed AS SELECT chooser FROM '+scan(run/'PRIVATE/needed.parquet'))
        tracker=Checks(c,run,month,out)
        tracker.report=load(inputs/'CHECKS.json');tracker.report['status']='FINALIZING'
        first=tracker.report['stages'][0]
        tracker.expected=[first['rows'],int(first['xor_identity_checksum']),int(first['sum_identity_checksum'])]
        c.execute('CREATE VIEW annotated AS SELECT * FROM '+scan([Path(p)/'annotated.parquet' for p in destinations]))
        tracker.stage('annotated')
        tracker.report['annotation_partition_checks']=dict(partitions=len(destinations),rows=row_total,
            all_original_columns_preserved=True,all_written_columns_equal=True,gap_session_ids_checked=True)
        c.execute('CREATE VIEW counts AS SELECT * FROM '+scan(previous/'counts.parquet'))
        c.execute('CREATE VIEW carry AS SELECT * FROM '+scan(previous/'carry.parquet'))
        copy(c,'''WITH fresh AS (SELECT chooser,speed_code,count(*)::BIGINT n,max(t)::BIGINT last_t
            FROM annotated GROUP BY chooser,speed_code),combined AS (SELECT * FROM counts UNION ALL SELECT * FROM fresh)
            SELECT chooser,speed_code,sum(n)::BIGINT n,max(last_t)::BIGINT last_t FROM combined GROUP BY chooser,speed_code''',out/'counts.parquet')
        c.execute('CREATE TEMP TABLE latest AS SELECT * FROM '+scan([Path(p)/'latest.parquet' for p in destinations]))
        require(c.execute('SELECT count(*)=count(DISTINCT chooser) FROM latest').fetchone()[0],
            'Chooser appears in multiple carry partitions')
        copy(c,'SELECT * FROM latest UNION ALL SELECT carry.* FROM carry ANTI JOIN latest USING(chooser)',out/'carry.parquet')
        qa=dict(month=month,history_rows=row_total,annotation_method='whole_chooser_arrow_numpy',
            annotation_partitions=len(destinations))
        if month in MONTHS:
            c.execute('CREATE VIEW focal AS SELECT * FROM '+scan(run/'PRIVATE/focal'/month/'rows.parquet'))
            tracker.features()
            copy(c,'SELECT f.*,'+','.join('a.'+x for x in FEATURES)+
                ',CAST(f.speed_code=1 AND f.chooser IN(SELECT chooser FROM '+scan(run/'PRIVATE/uncertain_prefix/choosers.parquet')+
                ') AS TINYINT) prefix_count_uncertain FROM focal f JOIN focal_features a USING(chooser,game_id)',out/'focal_history.parquet')
            tracker.written(out/'focal_history.parquet')
            qa.update(focal_rows=tracker.n,tied_focal_rows=c.execute('SELECT count(*) FROM focal_features WHERE tie_n>1').fetchone()[0])
        copy(c,'SELECT * FROM '+scan([Path(p)/'sessions30.parquet' for p in destinations]),out/'sessions30.parquet')
        tracker.finish();js(out/'QA.json',qa)
    finally:c.close();shutil.rmtree(work/'spill_finalize',ignore_errors=True)
    unchanged(receipt['sources']);commit(out,k,sources=receipt['sources'],**qa)
    shutil.rmtree(work)
    log(month+': history linked; '+format(qa.get('focal_rows',0),',')+' focal opportunities')
    return out
