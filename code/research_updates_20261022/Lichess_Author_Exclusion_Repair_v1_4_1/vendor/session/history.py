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
    from uncertainty import source_is_uncertain,valid_prefix_sql
    uncertain=source_is_uncertain(run,r['path'])
    if uncertain:k=digest([key,r,sha(Path(run)/'PRIVATE/uncertain_prefix/_DONE.json'),'valid_timestamp_history'])
    if cached(out,k):return str(out/'counts.parquet')
    from resume import parent_root,parent_key,adopt_checkpoint
    if not uncertain and adopt_checkpoint(parent_root(run)/'PRIVATE/prefix'/(r['speed']+'_'+r['month']),out,
            digest([parent_key(),r]),k,r['path']):return str(out/'counts.parquet')
    require(snapshot(r['path'])==r['stat'],'Chronology changed after preflight')
    auth=checked(r['path']);c=db(out/'spill',1.5,1)
    try:
        c.execute('CREATE VIEW needed AS SELECT chooser FROM '+scan(Path(run)/'PRIVATE/needed.parquet'))
        c.execute('CREATE TEMP TABLE raw AS '+valid_prefix_sql(r['path'],'needed',run,uncertain))
        bound=int(pd.Timestamp('2023-10-01',tz='UTC').timestamp()*1000)
        require(c.execute(f'SELECT count(*) FROM raw WHERE utc_ms IS NULL OR utc_ms<=0 OR utc_ms>={bound}').fetchone()[0]==0,
            'Invalid analysis-chooser prefix timestamp: '+r['path']+'; see TIMESTAMP_AUDIT.json')
        n=copy(c,f'''WITH e AS (SELECT white_id::BIGINT chooser,utc_ms::BIGINT t FROM raw
            UNION ALL SELECT black_id::BIGINT chooser,utc_ms::BIGINT t FROM raw)
            SELECT chooser,{r['speed_code']}::TINYINT speed_code,count(*)::BIGINT n,max(t)::BIGINT last_t
            FROM e JOIN needed USING(chooser) GROUP BY chooser''',out/'counts.parquet')
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    unchanged([auth]);commit(out,k,source=auth,rows=n,uncertain_prefix_record_omitted=uncertain);return str(out/'counts.parquet')

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
    from partitioned_history import run_month
    return run_month(month,records,run,previous,key,threads,memory)


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
    from uncertainty import prepare
    return prepare(cat,run,key,audit)

def run_history(cat,run,key,budget,io_workers,memory,previous):
    audit=load(Path(run)/'report/UNCERTAINTY.json')
    require(audit['status']=='READY_FOR_SENSITIVITY_TIMESTAMP_STILL_UNRESOLVED',
        'Explicit uncertainty receipt required; strict timestamp-verified analysis remains unresolved.')
    prev=Path(previous)
    require(prev.name=='2024-11','Resume requires the verified November 2024 checkpoint')
    remaining=[m for m in MONTHS if m>prev.name]
    durations=[]
    for i,month in enumerate(remaining):
        threads,_=slots(budget,min(4,budget));started=time.monotonic()
        with heartbeat('Reconstructing sessions '+month):
            prev=month_history(month,[r for r in cat['chronology'] if r['month']==month],run,prev,key,threads,memory)
        elapsed=time.monotonic()-started
        if month=='2024-12':log('DECEMBER_HISTORY_VERIFIED: partition annotation and all identity checks passed; continuing automatically.')
        if elapsed>60:durations.append(elapsed)
        if durations:
            eta=float(np.median(durations))*(len(remaining)-i-1)/60
            log(f'History {i+1}/{len(remaining)} remaining months ready; measured remaining history about {eta:.0f} min; regressions follow.')
    return [str(Path(run)/'PRIVATE/history'/m/'focal_history.parquet') for m in MONTHS]
