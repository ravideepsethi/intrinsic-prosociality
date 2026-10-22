"""Serial public-game retrieval; saved responses survive interruption and resume."""
from pathlib import Path
import math,time
import recovery_util as u
from phase_bridge import *
import download_expansion as dl
import metadata_http as http
from metadata_worker import merge_sql,readiness

def reconcile(a,plan,finished):
    p=u.load(a.run/'PRIVATE/METADATA_PATHS.json');root=a.run/'PRIVATE/reconciled'
    def build(tmp):
        c=io.conn(tmp/'spill',a.memory_gb-2,1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([plan['eligible_candidates']]))
            fields=','.join('"'+k+'"' for k in ex.META_FIELDS)
            sources=['SELECT game_id,'+fields+',cached_conflict_or_prior_flag FROM '+io.parq([Path(folder)/'metadata.parquet' for folder in p['months']])+' SEMI JOIN f USING(game_id)',
                'SELECT game_id,'+fields+",coalesce(record_errors,'')<>'' cached_conflict_or_prior_flag FROM "+io.parq([finished/'downloaded_metadata.parquet'])]
            io.copy(c,merge_sql(sources),tmp/'metadata.parquet')
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq([tmp/'metadata.parquet']))
            sql='SELECT f.* EXCLUDE(metadata_status),'+readiness()+' metadata_status FROM f LEFT JOIN m USING(game_id)'
            io.copy(c,sql,tmp/'dispositions.parquet')
            total=pq.ParquetFile(plan['eligible_candidates']).metadata.num_rows
            u.require(pq.ParquetFile(tmp/'dispositions.parquet').metadata.num_rows==total,'Post-download reconciliation changed denominator')
            counts={s:n for s,n in c.execute('SELECT metadata_status,count(*) FROM ('+sql+') GROUP BY 1').fetchall()}
            unresolved=sum(n for s,n in counts.items() if s not in ('CACHED_POOL_METADATA','CACHED_NONPOOL'))
            # Account labels are retained but will be reconciled to the fixed global
            # dictionary during the full old+new comparison assembly.
            io.copy(c,"SELECT f.*,m.* EXCLUDE(game_id) FROM "+io.parq([tmp/'dispositions.parquet'])+" f JOIN m USING(game_id) WHERE f.metadata_status='CACHED_POOL_METADATA'",tmp/'pool_metadata_candidates.parquet')
            result=dict(eligible_candidates=total,metadata_status_counts=counts,unresolved_metadata=unresolved,
                status='RECOVERY_COMPLETE_WITH_GAPS' if unresolved else 'RECOVERY_COMPLETE',
                final_comparison_population_rebuilt=False,global_account_identity_verified=False,
                prior_cache_flags_preserved=True,profile_requests=0,models_run=False,
                next_steps=['Rebuild full old+new comparison population using total-five support and the new full receipt stream.',
                    'Resolve metadata gaps and verify global account identities; missing returns remain unknown.',
                    'Rebuild recipient histories, follow-up outcomes, and entry labels from the new receipt selection universe.',
                    'Estimate ordinary-game Patron placebo and receipt-minus-placebo with joint account/date covariance.',
                    'Freeze the union of corrected receipt and comparison accounts, then collect a separately dated Patron snapshot.'])
            u.save(tmp/'summary.json',result);return result
        finally:finish_connection(c,tmp/'spill')
    folder,info=stable_stage(root,a.conf,build,[plan['eligible_candidates'],finished/'downloaded_metadata.parquet']+[Path(f)/'metadata.parquet' for f in p['months']])
    u.save(a.run/'report/reconciliation.json',u.load(folder/'summary.json'))
    u.save(a.run/'PRIVATE/CONTINUATION.json',dict(configuration_sha256=a.conf,parent_configuration_sha256=u.PARENT_CONF,
        recovery_root=str(a.run),parent_root=str(u.parent(a)),full_frame_audit=str(u.parent(a)/'PRIVATE/comparison_audit'),
        selection_universe=str(u.parent(a)/'PRIVATE/selection_universe.parquet'),
        full_pre_window_receipt_stream=u.load(a.run/'PRIVATE/SCORE_PATHS.json')['stream'],
        new_candidate_dispositions=str(folder/'dispositions.parquet'),new_pool_metadata=str(folder/'pool_metadata_candidates.parquet'),
        metadata=str(folder/'metadata.parquet'),chronology=plan['chronology'],requests=plan,
        raw_response_database=str(a.run/'PRIVATE/download/checkpoint.sqlite3'),
        scope='New count-supported primary 90-day comparisons only; old supported comparison rows still require a full rebuild.',
        August_profile_snapshot_unchanged=True,new_profile_snapshot_collected=False,models_ready=False))
    return info['status']

def run(a):
    plan=u.load(a.run/'PRIVATE/REQUEST_PLAN.json');target=Path(plan['targets'])
    u.require(u.sha(target)==plan['target_sha256'],'Frozen API target list changed')
    u.require(pq.ParquetFile(target).metadata.num_rows==plan['target_rows'],'API target row count changed')
    root=a.run/'PRIVATE/download';root.mkdir(exist_ok=True);shared=Path.home()/'.cache/lichess_research_api'
    started=time.monotonic();new_accounted=0;mark75=False;total=plan['target_rows']
    with dl.exclusive(shared/'one_request.lock','Another Lichess comparison API downloader is active; rerun after it finishes'):
        dl.check_other_api_jobs(a.project)
        db=dl.connect(root/'checkpoint.sqlite3',a.conf,plan['target_sha256'])
        client=http.Client(shared/'cooldown.json')
        try:
            u.require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','Download checkpoint integrity failed')
            ex.require_disk(root,2+total*600/1024**3)
            number=math.ceil(total/300)
            u.log(f'Downloading only the frozen {total:,} missing game IDs; {number:,} batches; one request at a time.')
            for k,rows in enumerate(dl.batches(target)):
                nr,nm,flags,reused=dl.process_batch(db,k,rows,client)
                if not reused:new_accounted+=len(rows)
                accounted=min((k+1)*300,total);rate=new_accounted/max(.001,time.monotonic()-started)
                if not reused or (k+1)%1000==0 or accounted==total:
                    eta=(total-accounted)/rate/3600 if rate else None
                    u.log(f'API batch {k+1:,}/{number:,}; {accounted:,}/{total:,} IDs accounted; flags {flags}; '+(f'remaining ETA {eta:.1f} h' if eta is not None else 'verified saved batch'))
                if accounted>=total/2 and not mark75:
                    u.save(a.run/'report/download_progress.json',dict(target_rows=total,accounted_rows=accounted,network_requests_this_invocation=client.requests))
                    u.export(a,75,'DOWNLOAD_IN_PROGRESS');mark75=True
                if flags>max(3,len(nr)*.05):raise RuntimeError('More than 5% of a response batch has metadata flags. Evidence saved; inspect before resuming.')
            with u.pulse('Verifying saved API responses'):
                finished,s=dl.export_saved(db,target,root/'finished',a.conf)
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:db.close()
    u.save(a.run/'report/download.json',dict(u.load(finished/'SUMMARY.json'),network_requests_this_invocation=client.requests,
        elapsed_seconds_this_invocation=time.monotonic()-started,http_seconds_this_invocation=client.http_seconds))
    status=reconcile(a,plan,finished);u.export(a,100,status)

if __name__=='__main__':
    with u.pulse('Metadata retrieval / verification'):run(u.parser().parse_args())
