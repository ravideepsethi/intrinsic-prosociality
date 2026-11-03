"""Recover the fixed frame before either historical-support exclusion."""
from rebuild_common import *

def receipt_stream(a,run,conf,b):
    selection=primary.build_selection(a,run,conf,b['primary'])
    def build(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW raw AS SELECT * FROM '+parq([b['primary']['raw']]))
            c.execute('CREATE VIEW flags AS SELECT * FROM '+parq([selection]))
            copy_query(c,'SELECT raw.*,flags.spaced90 AS rebuilt_spaced90,flags.observation_complete AS rebuilt_observation_complete FROM raw JOIN flags USING(row_id) WHERE flags.spaced90 ORDER BY recipient_id,archive_start_ms,row_id',tmp/'stream.parquet')
            n=c.execute('SELECT count(*) FROM '+parq([tmp/'stream.parquet'])).fetchone()[0]
            require(n==4226388,'Pre-window receipt stream differs from the completed primary build')
            ids=c.execute('SELECT row_id FROM '+parq([tmp/'stream.parquet'])+' WHERE rebuilt_observation_complete ORDER BY row_id').fetchnumpy()['row_id']
            require(np.array_equal(ids,frozen.col(b['primary']['primary'],'row_id')),'Pre-window stream does not recover the completed main sample')
            return dict(selected_before_windows=n,after_windows=len(ids),main_sample_reproduced=True)
        finally:c.close()
    path,info=stage(run/'PRIVATE/receipt_stream',conf,build,[selection,b['primary']['raw'],b['primary']['primary']])
    save(run/'report/receipt_stream.json',{k:v for k,v in info.items() if k not in ('files','dependencies')})
    return path/'stream.parquet'

def candidates(a,run,conf,b):
    if b.get('candidate_run'):
        from repair_reuse import copy_candidate_reports
        copy_candidate_reports(run,b)
        log('Completed receipt selection and 26,643,193 supported candidate scores reused read-only.')
        return
    stream=receipt_stream(a,run,conf,b);parts=b['local']['ledgers'];authors=b['primary']['bound']['binding']['author_ids']
    def build(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+parq(parts));c.execute('CREATE VIEW stream AS SELECT * FROM '+parq([stream]))
            n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM f').fetchone()
            require(n==u==cache_auth.FRAME_ROWS,'Full fixed candidate frame differs')
            # New namespace IDs do not depend on subsequent eligibility or metadata availability.
            copy_query(c,'SELECT *,4398046511104+row_number() OVER(ORDER BY game_id)::BIGINT AS row_id FROM f ORDER BY game_id',tmp/'full_frame.parquet')
            c.execute('CREATE VIEW allq AS SELECT * FROM '+parq([tmp/'full_frame.parquet']))
            ids=','.join(map(str,authors));start=int(phase_inputs.core.STARTS[0]);end=int(phase_inputs.core.PANEL_END)
            sql=f'''SELECT f.*,p.anchor_ms previous_selected_anchor,
                (f.recipient_id NOT IN ({ids}) AND f.opponent_id NOT IN ({ids})) AS author_clean,
                f.utc_ms-{97*DAY}>={start} AS history_complete,
                f.utc_ms+{90*DAY}<{end} AS start_calendar_complete,
                (p.anchor_ms IS NULL OR f.utc_ms>p.anchor_ms+{90*DAY}) AS at_risk_90
                FROM allq f ASOF LEFT JOIN stream p ON f.recipient_id=p.recipient_id AND f.utc_ms>p.anchor_ms'''
            copy_query(c,sql,tmp/'dispositions.parquet')
            c.execute('CREATE VIEW d AS SELECT * FROM '+parq([tmp/'dispositions.parquet']))
            counts=[];where='TRUE'
            for label,cut in [('fixed_hash_frame','TRUE'),('phase100_additional_games','NOT previous_frame'),('author_clean','author_clean'),('history97','history_complete'),
                              ('start_calendar90','start_calendar_complete'),('rebuilt_receipt_cooldown','at_risk_90')]:
                where+=' AND '+cut;counts.append(dict(step=label,rows=c.execute('SELECT count(*) FROM d WHERE '+where).fetchone()[0]))
            # No old support field participates. Complete scores determine the remaining support.
            months='CASE '+' '.join('WHEN month='+quote(m)+f' THEN {j}' for j,m in enumerate(phase_inputs.core.MONTHS))+' END'
            copy_query(c,'SELECT row_id,game_id,recipient_id,opponent_id,utc_ms,utc_ms archive_start_ms,'+months+'''::BIGINT month_code,
                recipient_color,speed_partition,previous_frame legacy_hash_member,FALSE previous_frame,at_risk_90,
                n7_author_clean legacy_prior_count FROM d WHERE '''+where+' ORDER BY row_id',tmp/'queries.parquet')
            save(tmp/'flow.json',counts);return dict(rows=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows,full_frame_rows=n)
        finally:c.close()
    path,_=stage(run/'PRIVATE/candidates',conf,build,parts+[stream])
    save(run/'report/candidate_flow.json',load(path/'flow.json'))
    query=path/'queries.parquet';qdir=inputs.query_shards(query,run/'PRIVATE/candidate_score_queries',conf)
    base=b['primary']['bound'];jobs=[]
    for s in range(16):
        jobs.append(dict(query=str(qdir/f'{s:02}.parquet'),reference=base['reference'],authors=authors,
          parts=[p for p in base['parts'] if p['shard']==s],out=str(run/'PRIVATE/candidate_scores'/f'{s:02}.parquet'),
          key=key([conf,'alltime_before_metadata',s,sha(qdir/f'{s:02}.parquet'),sha(base['reference'])])))
    mapped(cutoffs.donor_job,jobs,min(2,a.workers),'All-time-five scores before metadata')
    scores=[j['out'] for j in jobs]
    def choose(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([query]));c.execute('CREATE VIEW s AS SELECT * FROM '+parq(scores))
            ensure_unique(c,'q');ensure_unique(c,'s')
            ensure(c,'SELECT count(*) FROM q FULL JOIN s USING(row_id) WHERE q.row_id IS NULL OR s.row_id IS NULL','Candidate scores do not cover every query')
            keep='s.n_A>=5 AND isfinite(s.adjusted_A) AND isfinite(s.expected_A)'
            copy_query(c,'SELECT q.*,'+keep+' total_five_supported FROM q JOIN s USING(row_id) ORDER BY row_id',tmp/'support_dispositions.parquet')
            copy_query(c,'SELECT q.* FROM q JOIN s USING(row_id) WHERE '+keep+' ORDER BY row_id',tmp/'queries.parquet')
            copy_query(c,'SELECT s.* FROM s JOIN q USING(row_id) WHERE '+keep+' ORDER BY row_id',tmp/'scores.parquet')
            n,added=c.execute('SELECT count(*),count(*) FILTER(WHERE legacy_prior_count<5) FROM '+parq([tmp/'queries.parquet'])).fetchone()
            return dict(supported_queries=n,previously_failed_prior_count=added,old_prior_count_used_for_selection=False)
        finally:c.close()
    dest,info=stage(run/'PRIVATE/supported',conf,choose,[query]+scores)
    save(run/'report/alltime_support.json',{k:v for k,v in info.items() if k not in ('files','dependencies')})

def legacy_chronology(a,run,conf,b):
    q=run/'PRIVATE/supported/queries.parquet';fr=Path(b['frame_root']);fc=b['frame_conf']
    # Read all authenticated immutable chronology blocks, not only retained old frames.
    receipt=load(fr/'chronology/_DONE.json');oldkey=receipt['cache_definition_sha256']
    shared=a.project/'derived/replication/run2_feature_cache_v1_PRIVATE/chronology'/oldkey/'all'
    definition=load(shared/'definition.json')
    require(frozen.r.io.cfgsha(definition)==oldkey,'Chronology cache definition changed')
    require(definition['kind']=='first_pair_predecessor_volume_v1','Wrong chronology cache kind')
    require(definition['source']['files']==b['source']['chron'],'Chronology sources changed')
    modules={}
    # Producer hash checks use the imported, byte-frozen upstream modules.
    import phase_chronology,cached_chronology
    for m in (chron,phase_chronology,cached_chronology,cache,cached_chronology.rebuild):modules[Path(m.__file__).name]=Path(m.__file__)
    require(set(definition['code'])<=set(modules),'Unrecognized chronology producer')
    for name,digest in definition['code'].items():require(sha(modules[name])==digest,'Chronology producer differs: '+name)
    own=run/'PRIVATE/feature_cache/chronology'/oldkey/'all';own.mkdir(parents=True,exist_ok=True)
    save(own/'definition.json',definition)
    # Hard links retain authenticated immutable blocks; all new blocks go in this run.
    for src in sorted((shared/'blocks').iterdir()):
        if '.partial_' in src.name or not src.is_dir():continue
        check_stage(src/'records.parquet',oldkey)
        dst=own/'blocks'/src.name
        if not dst.exists():
            dst.mkdir(parents=True)
            for f in src.iterdir():
                if f.is_file():
                    try:os.link(f,dst/f.name)
                    except OSError:shutil.copy2(f,dst/f.name)
    job=dict(queries=str(q),memory=a.memory_gb-2,worker_memory=3.,conf=conf,
      output=str(run/'PRIVATE/chronology'),parts_root=str(run/'PRIVATE/chron_parts'),legacy=None)
    job=cache.attach(job,run/'PRIVATE/feature_cache','chronology',definition,'all')
    runtime=performance_runtime.Runtime(run/'PRIVATE')
    info=chron.run(job,b['source']['chron'],min(2,a.workers),runtime)
    save(run/'report/chronology_reuse.json',{k:v for k,v in info.items() if k not in ('files','dependencies')})
    def choose(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([q]));c.execute('CREATE VIEW x AS SELECT * FROM '+parq([run/'PRIVATE/chronology/features.parquet']))
            ensure(c,'SELECT count(*) FROM q FULL JOIN x USING(row_id) WHERE q.row_id IS NULL OR x.row_id IS NULL','Chronology query coverage changed')
            copy_query(c,'SELECT q.*,x.* EXCLUDE(row_id) FROM q JOIN x USING(row_id) WHERE x.eligible_main AND x.first_observed_pair ORDER BY row_id',tmp/'queries.parquet')
            return dict(rows=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows)
        finally:c.close()
    _,info=stage(run/'PRIVATE/locally_eligible',conf,choose,[q,run/'PRIVATE/chronology/features.parquet'])
    save(run/'report/local_eligibility.json',{k:v for k,v in info.items() if k not in ('files','dependencies')})

def chronology(a,run,conf,b):
    if b.get('chronology_run'):
        from repair_completed import import_chronology
        return import_chronology(run,conf,b)
    from repair_chronology import run_chronology
    return run_chronology(a,run,conf,b)
