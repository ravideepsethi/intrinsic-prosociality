"""Reuse returned game metadata, then retrieve only unresolved eligible IDs."""
from rebuild_common import *
import math
sys.path.insert(0,str(cache_auth.VENDOR/'comparison_original'))
import expansion_common as expansion
import prepare_expansion as original_plan
import download_expansion as download
import metadata_http

def ready_sql():
    # All hash bands undergo the same validation; old membership is not eligibility.
    return original_plan.readiness_sql().replace("CASE WHEN f.previous_frame THEN 'PREVIOUS_FRAME_REUSE'\n        WHEN",'CASE WHEN')

def metadata_union(c,paths,query):
    cols=expansion.META_FIELDS
    selects=[]
    for p in paths:
        names=pq.ParquetFile(p).schema_arrow.names
        require(set(cols+['game_id'])<=set(names),'Metadata schema incomplete: '+str(p))
        flag='coalesce(m.cached_conflict_or_prior_flag,FALSE)' if 'cached_conflict_or_prior_flag' in names else "coalesce(m.record_errors,'')<>''"
        selects.append('SELECT m.game_id,'+','.join('m.'+x for x in cols)+','+flag+' prior_flag FROM '+parq([p])+' m SEMI JOIN '+parq([query])+' q ON m.game_id=q.game_id')
    c.execute('CREATE VIEW metadata_sources AS '+' UNION ALL '.join(selects))
    fields=['game_id']+['max('+k+') AS '+k for k in cols]
    fields+=['('+' OR '.join(['bool_or(prior_flag)']+['count(DISTINCT '+k+')>1' for k in cols])+') cached_conflict_or_prior_flag']
    return 'SELECT '+','.join(fields)+' FROM metadata_sources GROUP BY game_id'

def plan(a,run,conf,b):
    query=run/'PRIVATE/locally_eligible/queries.parquet'
    def build(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            copy_query(c,metadata_union(c,b['metadata'],query),tmp/'known.parquet')
            c.execute('CREATE VIEW f AS SELECT * FROM '+parq([query]));c.execute('CREATE VIEW m AS SELECT * FROM '+parq([tmp/'known.parquet']))
            c.execute('CREATE VIEW quarantine AS SELECT game_id FROM '+parq(b['quarantine']))
            require(c.execute('SELECT count(*),count(DISTINCT game_id) FROM quarantine').fetchone()==(3,3),'Inherited metadata quarantine changed')
            copy_query(c,'SELECT f.row_id,f.game_id,'+ready_sql()+''' disposition,(q.game_id IS NOT NULL) inherited_quarantine
                FROM f LEFT JOIN m USING(game_id) LEFT JOIN quarantine q ON f.game_id=q.game_id ORDER BY f.row_id''',tmp/'dispositions.parquet')
            c.execute('CREATE VIEW d AS SELECT * FROM '+parq([tmp/'dispositions.parquet']))
            copy_query(c,"SELECT f.game_id,f.utc_ms,f.speed_partition FROM f JOIN d USING(row_id,game_id) WHERE d.disposition NOT IN ('CACHED_POOL_METADATA','CACHED_NONPOOL') AND NOT inherited_quarantine ORDER BY f.game_id",tmp/'targets.parquet')
            counts=dict(c.execute('SELECT disposition,count(*) FROM d GROUP BY disposition').fetchall())
            n=pq.ParquetFile(tmp/'targets.parquet').metadata.num_rows
            info=dict(locally_eligible=pq.ParquetFile(query).metadata.num_rows,metadata_counts=counts,
              missing_metadata_targets=n,known_quarantine_candidates=c.execute('SELECT count(*) FROM d WHERE inherited_quarantine').fetchone()[0],
              API_requests_at_most_initial=math.ceil(n/300),estimated_hours_at_25_games_per_second=n/25/3600,
              estimate_is_scenario_not_benchmark=True,first_pair_and_cooldown_applied_before_requests=True)
            save(tmp/'summary.json',info);return info
        finally:c.close()
    path,info=stage(run/'PRIVATE/metadata_plan',conf,build,[query]+b['metadata']+b['quarantine'])
    save(run/'report/metadata_plan.json',load(path/'summary.json'))
    log(f'Metadata audit: {info["missing_metadata_targets"]:,} eligible games require lookup; completed local records reused.')
    return path

def retrieve(a,run,conf,b):
    root=plan(a,run,conf,b);target=root/'targets.parquet';total=pq.ParquetFile(target).metadata.num_rows
    out=run/'PRIVATE/download';out.mkdir(exist_ok=True);dc=key([conf,sha(target)])
    if total:
        global_lock=Path.home()/'.cache/lichess_research_api'
        with download.exclusive(global_lock/'one_request.lock','Another Lichess metadata downloader is running; resume this command after it finishes.'):
            download.check_other_api_jobs(a.project)
            sql=download.connect(out/'checkpoint.sqlite3',dc,sha(target))
            try:
                require(sql.execute('PRAGMA quick_check').fetchone()[0]=='ok','Metadata checkpoint damaged')
                client=metadata_http.Client(global_lock/'cooldown.json');started=time.monotonic();fresh=0
                for k,rows in enumerate(download.batches(target)):
                    found,missing,flags,reused=download.process_batch(sql,k,rows,client)
                    if not reused:fresh+=len(rows)
                    elapsed=time.monotonic()-started;done=min((k+1)*300,total)
                    if not reused or (k+1)%1000==0 or done==total:
                        rate=fresh/max(elapsed,.001);eta=(total-done)/rate/3600 if rate else None
                        log(f'Metadata {done:,}/{total:,}; returned {len(found)}/{len(rows)}; flags {flags}; remaining ETA '+(f'{eta:.2f} h' if eta is not None else 'pending new request timing'))
                    require(flags<=max(3,len(found)*.05),'More than 5% metadata flags in a batch; saved responses retained for review')
                download.export_saved(sql,target,out/'finished',dc)
            finally:sql.close()
    else:
        def empty(tmp):
            pq.write_table(pa.Table.from_pylist([],schema=expansion.metadata_schema()),tmp/'downloaded_metadata.parquet')
            pq.write_table(pa.table({'game_id':pa.array([],pa.string())}),tmp/'not_returned.parquet')
            save(tmp/'SUMMARY.json',dict(requested=0,returned=0,not_returned=0,returned_with_metadata_flags=0))
            return dict(rows=0)
        stage(out/'finished',dc,empty,[target])
    summary=load(out/'finished/SUMMARY.json');save(run/'report/metadata_download.json',summary)
    query=run/'PRIVATE/locally_eligible/queries.parquet';known=root/'known.parquet';fresh=out/'finished/downloaded_metadata.parquet'
    def reconcile(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+parq([query]));c.execute('CREATE VIEW oldmeta AS SELECT * FROM '+parq([known]));c.execute('CREATE VIEW newmeta AS SELECT * FROM '+parq([fresh]))
            # Fresh data may fill missing fields, but may not silently overwrite a conflict.
            tests=['(o.'+k+' IS NOT NULL AND n.'+k+' IS NOT NULL AND o.'+k+' IS DISTINCT FROM n.'+k+')' for k in expansion.META_FIELDS]
            bad=c.execute('SELECT count(*) FROM oldmeta o JOIN newmeta n USING(game_id) WHERE '+' OR '.join(tests)).fetchone()[0]
            require(bad==0,'New metadata conflicts with cached nonmissing fields; reconciliation required')
            # A prior flag is not silently cleared by repeating the same response.
            fields=['coalesce(o.game_id,n.game_id) game_id']+['coalesce(n.'+k+',o.'+k+') AS '+k for k in expansion.META_FIELDS]
            fields+=["(coalesce(o.cached_conflict_or_prior_flag,FALSE) OR coalesce(n.record_errors,'')<>'') cached_conflict_or_prior_flag"]
            copy_query(c,'SELECT '+','.join(fields)+' FROM oldmeta o FULL JOIN newmeta n USING(game_id)',tmp/'metadata.parquet')
            c.execute('CREATE VIEW m AS SELECT * FROM '+parq([tmp/'metadata.parquet']))
            c.execute('CREATE VIEW quarantine AS SELECT game_id FROM '+parq(b['quarantine']))
            copy_query(c,'SELECT f.row_id,f.game_id,'+ready_sql()+''' disposition,(q.game_id IS NOT NULL) inherited_quarantine
              FROM f LEFT JOIN m USING(game_id) LEFT JOIN quarantine q ON f.game_id=q.game_id ORDER BY f.row_id''',tmp/'dispositions.parquet')
            c.execute('CREATE VIEW d AS SELECT * FROM '+parq([tmp/'dispositions.parquet']))
            unresolved=c.execute("SELECT count(*) FROM d WHERE disposition NOT IN ('CACHED_POOL_METADATA','CACHED_NONPOOL') AND NOT inherited_quarantine").fetchone()[0]
            info=dict(new_unresolved_rows=unresolved,existing_quarantine_rows=c.execute('SELECT count(*) FROM d WHERE inherited_quarantine').fetchone()[0],
                      dispositions=dict(c.execute('SELECT disposition,count(*) FROM d GROUP BY 1').fetchall()))
            save(run/'report/metadata_completion.json',info)
            require(unresolved==0,f'{unresolved:,} additional metadata rows remain unresolved. Frames are blocked; no available-case exclusion was invented. Return the checkpoint report.')
            sql='''SELECT f.*,m.anchor_ms,m.tc_base_s,m.tc_inc_s,m.status,
              CASE WHEN f.recipient_color='white' THEN m.white_rating ELSE m.black_rating END recipient_rating,
              CASE WHEN f.recipient_color='white' THEN m.black_rating ELSE m.white_rating END opponent_rating,
              CASE WHEN f.recipient_color='white' THEN m.white_username ELSE m.black_username END recipient_username,
              CASE WHEN f.recipient_color='white' THEN m.black_username ELSE m.white_username END opponent_username,
              m.status IN ('mate','resign','stalemate') ordinary_narrow,m.status='timeout' active_timeout
              FROM f JOIN m USING(game_id) JOIN d USING(row_id,game_id)
              WHERE d.disposition='CACHED_POOL_METADATA' AND NOT d.inherited_quarantine ORDER BY row_id'''
            copy_query(c,sql,tmp/'queries.parquet');return dict(info,pool_rows=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows)
        finally:c.close()
    dest,_=stage(run/'PRIVATE/metadata_complete',conf,reconcile,[query,known,fresh]+b['quarantine'])
    cached_inputs.identity_check(dest/'queries.parquet',b['source'],run/'PRIVATE/identity',conf,a.memory_gb-2,min(2,a.workers))
