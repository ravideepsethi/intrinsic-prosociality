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
    from metadata_batches import plan as bounded_plan
    return bounded_plan(a,run,conf,b)

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
    from metadata_batches import complete
    return complete(a,run,conf,b,root,out/'finished/downloaded_metadata.parquet')
