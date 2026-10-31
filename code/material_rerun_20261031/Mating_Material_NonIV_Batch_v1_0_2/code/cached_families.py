"""Reuse factual caches; rebuild analytical decisions before every estimator."""
from bindings import *

def reputation(a,auth,out):
    import_vendor('reputation','code');import core,inputs,analysis
    old=unique_path((a.project/'derived/replication/reputation_v100_PRIVATE').glob('1d4e350c2249*/DESIGN_FREEZE.json'),'Reputation design').parent
    require(read(old/'DESIGN_FREEZE.json')==read(ROOT/'authority/reputation/DESIGN.json'),'Original pair sampling design changed')
    merged=unique_path(old.glob('merged_history/*/features.parquet'),'Factual reputation features').parent
    require(core.cached(merged) is not None,'Factual reputation cache is unsealed')
    oldrecords=[record(merged/'features.parquet'),record(merged/'events.parquet')]
    projected=[];returns=[];census=[]
    # Projection is sequential and streaming: one Arrow batch per process, no
    # simultaneous copies of a complete month. Model stages use the shared cap.
    for broad,records in [(False,auth['records']),(True,auth['all_source_records'])]:
        for k,r in enumerate(records):
            folder=out/'PRIVATE'/('return_projection' if broad else 'main_projection')/r['month']
            job=dict(source=dict(path=r['path'],month=r['month'],fingerprint=core.stamp(r['path'])),
                     folder=str(folder),denominator=5,broad=broad,month_code=k)
            inputs.projection_job(job)
            (returns if broad else projected).append(folder/'panel.parquet')
            if not broad:census.extend(core.load(folder/'census.json'))
            log(('Reputation return ' if broad else 'Reputation focal ')+r['month']+' complete')
    c=db(out/'PRIVATE/spill_bridge',a.memory_gb-2,a.workers)
    history=out/'PRIVATE/factual_history';history.mkdir(parents=True,exist_ok=True)
    try:
        freshcols=pq.ParquetFile(projected[0]).schema_arrow.names
        checks={k:'n.'+ident(k) for k in freshcols if k not in ('gid','y')}
        flow=guarded_join(c,merged/'features.parquet',projected,history/'features.parquet',old_id='gid',new_id='gid',
                         replacements={'y':'n.y'},checks=checks,cover_fresh=True)
        # Preserve the original qid for factual history; it is a join key, not
        # an ordinal used to index newly constructed prediction arrays.
        dest=history/'events.parquet'
        if dest.exists():require(dest.resolve()==(merged/'events.parquet').resolve(),'Factual event link changed')
        else:dest.symlink_to((merged/'events.parquet').resolve())
    finally:c.close()
    scope='ALL_SOURCE_MATERIAL_RESTRICTED_24M: active eligible decisions; historical meetings unchanged'
    feature=out/'PRIVATE/features';qa=analysis.make_features(history,returns,feature,a.workers,int((a.memory_gb-2)*1000),scope)
    results=out/'PRIVATE/analyses'
    # Individual historical regression JSON files have no commit receipts.
    # Recompute those fits on an interrupted family, retaining the sealed
    # projections and factual/return features instead of trusting loose JSON.
    if results.exists():results.rename(results.with_name('interrupted_analyses_'+str(time.time_ns())))
    result=analysis.run_analyses(feature/'analysis.parquet',results,scope)
    public_copy(results,out/'report')
    for p in (out/'report').glob('prediction_private*'):
        raise RuntimeError('Private prediction cache reached report')
    grouped=pd.DataFrame(census).groupby(['month','region'],as_index=False)[['n','grants']].sum()
    table(out/'report/full_panel_census',grouped);write(out/'report/INPUT_FLOW.json',flow);write(out/'report/FEATURE_QA.json',qa)
    require(int(grouped.loc[grouped.region=='all','n'].sum())==auth['census']['opportunities'],'Reputation full census differs')
    require(int(grouped.loc[grouped.region=='all','grants'].sum())==auth['census']['grants'],'Reputation grant census differs')
    for r in oldrecords:verify(r)
    unsupported=[r for r in result['module_status'] if r['status']!='COMPLETE']
    return dict(status='COMPLETE_WITH_UNSUPPORTED_AUXILIARIES' if unsupported else 'COMPLETE',**result,
                historical_games_rescanned=0,factual_cache_reused=True,prediction_refitted=True)

def stakes(a,auth,out):
    import_vendor('stakes','code');import prepare,report,common
    evidence=ROOT/'authority/stakes/Win_Premium_Stakes_Report'
    oldreport=unique_path([p for p in (a.project/'output/win_premium_stakes_v100').glob('*/RUN_TIME.json')
                         if sha(p)==sha(evidence/'RUN_TIME.json')],'Reviewed stakes report').parent
    old=a.project/'derived/replication/win_premium_stakes_v100_PRIVATE'/oldreport.name
    work=out/'PRIVATE/stakes';work.mkdir(parents=True,exist_ok=True)
    ids=prepare.author_ids(a.project,work)
    require(ids==read(old/'author_ids_PRIVATE.json')['author_ids'],'Factual stakes author namespace changed')
    targets={}
    for r in auth['records']:
        rec=dict(r,size_bytes=Path(r['path']).stat().st_size)
        targets[r['month']]=prepare.prepare_month((rec,work,ids,1500))
    receipts=sorted((old/'history').glob('*/*/_DONE.json'));require(len(receipts)==135,'Stakes history inventory changed')
    outputs=[];flows=[];source_records=[]
    c=db(work/'spill_bridge',a.memory_gb-2,a.workers)
    try:
        for rp in receipts:
            d=read(rp);source_records.append(record(rp))
            for r in d['permanent_files']:
                path=verify(r);source_records.append(record(path))
                if path.parent!=old/'analysis':continue
                dest=work/'analysis'/path.name
                cols=pq.ParquetFile(targets[d['month']]).schema_arrow.names
                checks=stakes_bridge_checks(cols)
                flow=guarded_join(c,path,targets[d['month']],dest,replacements={'y':'n.y'},checks=checks,cover_fresh=True,where='speed='+q(d['speed']))
                outputs.append(dest);flows.append(dict(month=d['month'],speed=d['speed'],**flow))
        require(len(set(outputs))==120,'Stakes output inventory differs')
        require(sum(r['after'] for r in flows)==auth['census']['competitive'],'Stakes competitive coverage differs')
        totals=c.execute('SELECT count(*) opportunities,sum(outcome_kind_draw)::BIGINT grants,count(DISTINCT chooser_user_id) FILTER(WHERE outcome_kind_draw=1) granters,'+
                         'sum(chooser_win_premium_v2) FILTER(WHERE outcome_kind_draw=1) total_forgone_rating_points,'+
                         'avg(chooser_win_premium_v2) FILTER(WHERE outcome_kind_draw=1) mean_grant_premium,'+
                         'median(chooser_win_premium_v2) FILTER(WHERE outcome_kind_draw=1) median_grant_premium FROM '+scan([r['path'] for r in auth['records']])).fetchdf()
        table(out/'report/all_position_rating_totals',totals)
    finally:c.close()
    # The summary reads original reference-population metadata only. It never
    # writes to history; avoid copying the multi-billion-game factual cache.
    hist=work/'history'
    if hist.exists():require(hist.resolve()==(old/'history').resolve(),'Stakes history link changed')
    else:hist.symlink_to((old/'history').resolve(),target_is_directory=True)
    n=report.summarize(work,out/'report',outputs,int((a.memory_gb-2)*1000))
    table(out/'report/material_bridge',flows)
    # Original stage_timings describe the historical cache build, not this run.
    (out/'report/stage_timings.csv').rename(out/'report/original_factual_history_build_timings.csv')
    write(out/'report/REUSE.json',dict(factual_rating_histories_and_ecdfs_reused=True,source_rows_replayed=0,
          analytical_grants_rebuilt=True,history_source_run=oldreport.name))
    for r in source_records:require(signature(r['path'])==r['verified_signature'],'Factual stakes source changed')
    return dict(status='COMPLETE',opportunities=n,historical_games_rescanned=0)

def stakes_bridge_checks(columns):
    checks={k:'n.'+ident(k) for k in columns if k not in ('game_id','y','t')}
    # The archived producer aligned API millisecond starts to factual PGN
    # second timestamps, allowing <=1000 ms. Preserve that aligned anchor.
    checks['t']='CASE WHEN o.t IS NOT NULL AND n.t IS NOT NULL AND abs(o.t-n.t)<=1000 THEN o.t ELSE NULL END'
    return checks

def countdown(a,auth,out):
    import_vendor('countdown','code');import inputs,run,design,report,common,feature_projection
    # Recreate the narrow features from the authenticated corrected panel using
    # the ORIGINAL feasibility projector. Cached FENs and counts are sufficient;
    # no engine, network, historical replay, or old-source stamp is needed.
    from concurrent.futures import ProcessPoolExecutor,as_completed
    import multiprocessing
    workers=min(3,a.workers)
    projection_key=digest([auth['fingerprint'],sha(Path(feature_projection.__file__))])
    jobs=[dict(record=dict(r,expected_sha256=r['sha256']),config=projection_key,
               out=str(out/'PRIVATE/projection'/r['month']),memory_gb=min(2.,(a.memory_gb-2)/workers))
          for r in auth['records']]
    projected=[]
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        futures=[pool.submit(feature_projection.project_month,j) for j in jobs]
        for future in as_completed(futures):
            result=future.result();projected.append(result)
            log(f'Countdown corrected features: {len(projected)}/24 months; {result["month"]} complete')
    projected.sort(key=lambda r:r['month'])
    require([r['month'] for r in projected]==MONTHS,'Countdown projection month inventory differs')
    require(sum(r['counts']['rows'] for r in projected)==auth['census']['opportunities'],'Countdown row census differs')
    require(sum(r['counts']['grants'] for r in projected)==auth['census']['grants'],'Countdown grant census differs')
    files=[dict(**r['output'],verified_stamp=common.stamp(r['output']['path'])) for r in projected]
    key=digest([projection_key,'countdown_original_spec',sha(ROOT/'vendor/countdown/code/design.py')])
    fresh=dict(key=key,files=files,rows=auth['census']['opportunities'],input_identity=auth['fingerprint'])
    write(out/'report/SPECIFICATION.json',design.SPEC)
    table(out/'report/feature_projection',[dict(month=r['month'],**r['counts'],reused=r['reused'],seconds=r['elapsed_seconds']) for r in projected])
    write(out/'report/RECOVERY.json',dict(features_reprojected_from_corrected_panels=True,
        projection_sha256=sha(Path(feature_projection.__file__)),original_feasibility_projection_unchanged=True,
        old_source_stamp_required=False,engine_searches=0,API_requests=0,regression_specification_changed=False))
    prepared=inputs.prepare(fresh,out,a.memory_gb,min(4,a.workers))
    for r in prepared['files']:r['verified_stamp']=common.stamp(r['path'])
    tasks=[]
    for spec in design.FAMILIES:
        tasks += [run.make_task(out,key,r,spec) for r in prepared['files']]
    for month in common.MONTHS:
        tasks += [run.make_task(out,key,r,dict(name='monthly_'+month,month=month,clock_multiple=0)) for r in prepared['files']]
    common.table(out/'report/model_plan.csv',[{k:t[k] for k in ('id','speed','rows','memory','work')} for t in tasks])
    results=[]
    for spec in design.FAMILIES:
        selected=[t for t in tasks if t['spec']['name']==spec['name']]
        run.schedule(selected,min(4,a.workers),a.memory_gb,results,0)
        report.family_report(out,spec['name'],results)
    monthly=[t for t in tasks if t['spec'].get('month')]
    run.schedule(monthly,min(4,a.workers),a.memory_gb,results,0);report.monthly_report(out,results)
    common.table(out/'report/all_model_status.csv',[dict(id=r['id'],status=r['status'],seconds=r['seconds'],**r.get('counts',{})) for r in results])
    unsupported=sum(r['status']!='COMPLETE' for r in results)
    return dict(status='COMPLETE_WITH_UNSUPPORTED_AUXILIARIES' if unsupported else 'COMPLETE',models=len(results),unsupported=unsupported,
                estimand='Original descriptive threshold/calendar contrasts, not a causal regression discontinuity')
