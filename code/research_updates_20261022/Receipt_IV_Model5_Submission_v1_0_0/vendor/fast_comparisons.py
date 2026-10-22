"""Rebuild entry and ordinary placebo on the expanded fixed hash frame."""
from fast_bootstrap import *
import fast_features as features90
import fast_models as model90
import rebuild_common as legacy
import rebuild_metadata as metadata
import repair_chronology as repair

def prepare90(a,run,conf):
    # Authenticate old rule/cache lineage before reading reusable facts. New
    # candidate membership is never imported from that completed selection.
    b=legacy.prepare(a,run,conf)
    mark_legacy_reports(run)
    b['legacy_candidate_run']=b.pop('candidate_run');b['legacy_chronology_run']=b.pop('chronology_run')
    from run_finish import PARENT_CONF
    parent=a.project/'derived/replication/alltime_entry_placebo_v103_PRIVATE'/PARENT_CONF[:12]
    if parent.is_dir():
        require(key(load(parent/'config.json'))==PARENT_CONF,'Completed metadata parent configuration changed')
        p=parent/'PRIVATE/metadata_complete/metadata.parquet'
        if p.is_file():
            check_stage(p,PARENT_CONF);b['metadata'].append(str(p))
    save(run/'PRIVATE/BINDING90.json',b);save(run/'report/rebuild_definition.json',RULE90)
    return b

def chronology90(a,run,conf,b):
    query=run/'PRIVATE/supported/queries.parquet'
    oldq=Path(b['legacy_candidate_run'])/'PRIVATE/supported/queries.parquet'
    oldx=Path(b['legacy_chronology_run'])/'PRIVATE/chronology/features.parquet'
    def plan(tmp):
        c=conn(tmp)
        try:
            view(c,'q',query);view(c,'oq',oldq);view(c,'ox',oldx)
            # IDs are generated from the full frame before either set of cuts.
            bridge(c,'q','oq',['game_id','recipient_id','opponent_id','archive_start_ms'],'Chronology reusable identity')
            assert_coverage(c,'oq','ox')
            copy_query(c,'SELECT q.row_id,ox.* EXCLUDE(row_id) FROM q JOIN oq USING(row_id) JOIN ox USING(row_id) ORDER BY row_id',tmp/'hits.parquet')
            copy_query(c,'SELECT q.* FROM q ANTI JOIN oq USING(row_id) ORDER BY row_id',tmp/'missing.parquet')
            return dict(rows=pq.ParquetFile(query).metadata.num_rows,reused=pq.ParquetFile(tmp/'hits.parquet').metadata.num_rows,missing=pq.ParquetFile(tmp/'missing.parquet').metadata.num_rows)
        finally:c.close()
    prep,info=stage(run/'PRIVATE/chronology_plan90',conf,plan,[query,oldq,oldx]);parts=[prep/'hits.parquet']
    if info['missing']:
        q=prep/'missing.parquet'
        p,stats=chron.previous.prepare_chronology(q,run/'PRIVATE/chronology_scan_plan90',conf,4.)
        scanconf=key([conf,'new_comparison_chronology',sha(q)])
        jobs=[dict(r,latest=stats['latest_start'],people=str(p/'people.parquet'),pairs=str(p/'pairs.parquet'),focal=str(p/'focal.parquet'),roles=str(p/'roles.parquet'),memory=3.,conf=scanconf,output=str(run/'PRIVATE/chronology_scans90'/f"{r['file_index']:04}")) for r in b['source']['chron'] if r['minimum'] is None or r['minimum']<=stats['latest_start']]
        mapped(chron.chronology_job,jobs,min(a.workers,2),'Cached local chronology for newly eligible comparison rows')
        folder,stats=repair.bounded_merge(q,[Path(j['output']) for j in jobs],run/'PRIVATE/chronology_merge90',conf,4.)
        parts.append(folder/'features.parquet')
    def combine(tmp):
        c=conn(tmp)
        try:
            view(c,'q',query);view(c,'x',parts);assert_coverage(c,'q','x')
            copy_query(c,'SELECT q.*,x.* EXCLUDE(row_id) FROM q JOIN x USING(row_id) WHERE eligible_main AND first_observed_pair ORDER BY row_id',tmp/'queries.parquet')
            return dict(rows=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows)
        finally:c.close()
    stage(run/'PRIVATE/locally_eligible',conf,combine,[query]+parts)
    save(run/'report/chronology90.json',info)

def metadata90(a,run,conf,b):
    root=metadata.plan(a,run,conf,b);n=pq.ParquetFile(root/'targets.parquet').metadata.num_rows
    report=load(run/'report/metadata_plan.json');report['first_pair_and_cooldown_applied_before_requests']=False
    report['first_pair_applied_before_requests']=True;report['receipt_cooldown_applied']=False
    save(run/'report/metadata_plan.json',report)
    if a.offline and n:raise RuntimeError(f'OFFLINE_HOLD: {n:,} expanded-comparison games need metadata. Receipt results are retained. Rerun without --offline to fetch only these IDs.')
    metadata.retrieve(a,run,conf,b)
    # The unchanged cache producer's old summary field is execution metadata,
    # not a new scientific screen. Correct it in the exported run description.
    save(run/'report/metadata_plan.json',report)

def frames90(a,run,conf,b,receipt_run):
    src=run/'PRIVATE/metadata_complete/queries.parquet'
    src=features90.behavior(a,run,conf,b['primary']['bound'],src)
    src=features90.volume(a,run,conf,b['primary']['bound'],src)
    jobs=[]
    base=b['primary']['bound']['features']
    for k,p in enumerate(base['futures']):
        roles=check_stage(Path(p)/'keys.parquet',base['main_conf'])
        jobs.append(dict(queries=str(src),keys=str(roles),memory=3.,conf=conf,output=str(run/'PRIVATE/roles'/f'{k:02}')))
    mapped(fast.role_job,jobs,min(a.workers,2),'Expanded entry roles')
    roles=[str(Path(j['output'])/'roles.parquet') for j in jobs]
    flags=receipt_run/'PRIVATE/selection90/flags.parquet';raw=b['primary']['raw']
    def label(tmp):
        c=conn(tmp,a.memory_gb-2)
        try:
            view(c,'q',src);view(c,'m',roles);ensure_unique(c,'m');view(c,'raw',raw);view(c,'flags',flags)
            ensure(c,"SELECT count(*) FROM q JOIN m USING(row_id) WHERE q.status<>'timeout' OR NOT ((q.recipient_id=m.i AND q.opponent_id=m.j) OR (q.recipient_id=m.j AND q.opponent_id=m.i))",'Main-panel role or focal-pair mismatch')
            c.execute('CREATE VIEW s AS SELECT raw.game_id,raw.recipient_id,flags.supported,flags.uniform_keep FROM raw JOIN flags USING(row_id)')
            ensure(c,'SELECT count(*) FROM (SELECT game_id,recipient_id FROM s GROUP BY 1,2 HAVING count(*)>1)','Duplicate receipt exposure key')
            copy_query(c,f'''SELECT q.*,
              coalesce(q.recipient_id=m.i,FALSE) recipient_disconnect_main,
              coalesce(q.recipient_id=m.i AND m.fair_competitive AND (m.kind_draw OR m.timeout_chooser_win),FALSE) recipient_fair_arm_main,
              coalesce(s.supported,FALSE) supported_receipt_entry,
              coalesce(s.uniform_keep,FALSE) analysis_entry_uniform90,
              q.anchor_ms+{90*DAY}<{int(phase_inputs.core.PANEL_END)} complete90
              FROM q LEFT JOIN m USING(row_id) LEFT JOIN s ON q.game_id=s.game_id AND q.recipient_id=s.recipient_id ORDER BY q.row_id''',tmp/'model.parquet')
            view(c,'l',tmp/'model.parquet');ensure_unique(c,'l',pq.ParquetFile(src).metadata.num_rows)
            labels=['active_timeout','recipient_disconnect_main','recipient_fair_arm_main','supported_receipt_entry','analysis_entry_uniform90']
            ensure(c,'SELECT count(*) FROM l WHERE '+' OR '.join(f'({y} AND NOT {x})' for x,y in zip(labels[:-1],labels[1:])),'Entry labels not nested')
            save(tmp/'counts.json',{x:c.execute('SELECT count(*) FROM l WHERE '+x).fetchone()[0] for x in labels})
            return dict(rows=pq.ParquetFile(src).metadata.num_rows)
        finally:c.close()
    labeled,_=stage(run/'PRIVATE/labeled90',conf,label,[src,raw,flags]+roles)
    save(run/'report/entry_label_counts.json',load(labeled/'counts.json'))
    from rebuild_frames import pool_rates
    bb=dict(b['primary'],known_rates=[str(pool_rates(a,run,conf,b))])
    source=primary.environment(a,run,conf,bb,labeled/'model.parquet');sc=run/'PRIVATE/supported/scores.parquet'
    def finish(tmp):
        c=conn(tmp,a.memory_gb-2)
        try:
            view(c,'q',source);view(c,'s',sc);ensure_unique(c,'q');ensure_unique(c,'s')
            ensure(c,'SELECT count(*) FROM q WHERE NOT eligible_main OR NOT first_observed_pair OR tc_base_s<=0 OR NOT history_window_complete','Comparison eligibility rule failed')
            ensure(c,'SELECT count(*) FROM q LEFT JOIN s USING(row_id) WHERE s.row_id IS NULL OR n_A<5 OR NOT isfinite(adjusted_A) OR NOT isfinite(expected_A)','Comparison support incomplete')
            counts=[]
            for tag,where in [('F','TRUE'),('O','ordinary_narrow AND complete90')]:
                copy_query(c,'SELECT * FROM q WHERE '+where+' ORDER BY row_id',tmp/(tag+'.parquet'))
                copy_query(c,'SELECT s.* FROM s JOIN q USING(row_id) WHERE '+where+' ORDER BY row_id',tmp/(tag+'_scores.parquet'))
                n,people=c.execute('SELECT count(*),count(DISTINCT recipient_id) FROM q WHERE '+where).fetchone();counts.append(dict(frame=tag,rows=n,recipients=people))
            save(tmp/'counts.json',counts);return dict(rows=pq.ParquetFile(source).metadata.num_rows)
        finally:c.close()
    folder,_=stage(run/'PRIVATE/frames90',conf,finish,[source,sc]);csv_out(run/'report/comparison_frame_counts.csv',load(folder/'counts.json'))

def models90(a,run,conf,b,receipt_run):
    frame=run/'PRIVATE/frames90';plan=[]
    for tag,outs in [('F',['analysis_entry_uniform90','recipient_disconnect_main','active_timeout']),('O',['y','reached'])]:
        for balance in (False,True):
            job=model90.job_for(run,conf,'uniform_'+tag+('_balance' if balance else ''),frame/(tag+'.parquet'),frame/(tag+'_scores.parquet'),balance=balance)
            job.update(outcomes=outs,iv=False);plan.append(job)
    save(run/'PRIVATE/COMPARISON_PLAN90.json',plan)
    from fast_scheduler import fits as schedule_fits
    for job in schedule_fits(plan):model90.export_models(run)
    receipt=model90.job_for(receipt_run,conf,'uniform_unspaced','','')
    diff=model90.contrast(run,conf,receipt,plan[2],'uniform_receipt_minus_ordinary',['rf_y','rf_reached'])
    csv_out(run/'report/receipt_minus_ordinary.csv',diff)
    row=next(r for r in load(Path(plan[2]['output'])/'result.json')['estimates'] if r['term']=='rf_y')
    margin=.015*SD/.0594;se=row['standard_error']
    save(run/'report/ordinary_equivalence.json',dict(original_margin_pp=.015,original_score_sd=.0594,margin_pp=margin,
        coefficient_pp=row['coefficient'],se_pp=se,ci90_low_pp=row['coefficient']-1.6448536269514722*se if se else None,
        ci90_high_pp=row['coefficient']+1.6448536269514722*se if se else None,
        equivalent=(bool(row['coefficient']-1.6448536269514722*se>-margin and row['coefficient']+1.6448536269514722*se<margin) if se else None)))
