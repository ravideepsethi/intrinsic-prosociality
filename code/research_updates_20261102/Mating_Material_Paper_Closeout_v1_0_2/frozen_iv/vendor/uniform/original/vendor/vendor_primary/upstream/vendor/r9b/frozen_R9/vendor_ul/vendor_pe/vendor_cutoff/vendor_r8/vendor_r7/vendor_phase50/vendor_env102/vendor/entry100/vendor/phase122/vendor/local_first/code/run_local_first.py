#!/usr/bin/env python3
"""Prepare an eligibility-filtered Run 2 request list, then optionally resume it."""
from local_contract import *
import argparse, collections, json, math, platform, sqlite3, shutil, shlex, contextlib
import prior_support as support
import local_cache as cache
import prepare_expansion as original_plan
import original_resume
import metadata_http as http

def candidate_index(ledgers,out,conf,memory,workers):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,workers)
        try:
            query='SELECT game_id FROM '+io.parq(ledgers)+" WHERE local_eligibility='POTENTIALLY_ELIGIBLE' AND NOT previous_frame ORDER BY game_id"
            n=c.execute('SELECT count(*) FROM ('+query+')').fetchone()[0]
            make_index(c,query,tmp/'game_ids.npy',n)
            return dict(rows=n,includes_all_endings=True,outcomes_used=False)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(out,conf,build,ledgers)

def plan_month(job):
    threads_one()
    metadata_paths=job['metadata'] if isinstance(job['metadata'],list) else [job['metadata']]
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW frame AS SELECT * FROM '+io.parq([job['ledger']]))
            c.execute('CREATE VIEW metadata AS SELECT * FROM '+io.parq(metadata_paths))
            if job['notreturned']:
                c.execute('CREATE VIEW absent AS SELECT DISTINCT game_id FROM '+io.parq(job['notreturned']))
            else:c.execute('CREATE VIEW absent AS SELECT NULL::VARCHAR AS game_id WHERE FALSE')
            readiness=original_plan.readiness_sql()
            query=f'''SELECT f.*,({readiness}) AS metadata_status,
                coalesce(m.cached_conflict_or_prior_flag,FALSE) AS cache_conflict_or_flag,
                m.source IS NULL AS missing_api_source,m.status IS NULL AS missing_api_status,
                m.api_start_ms IS NULL AS missing_api_start,m.anchor_ms IS NULL AS missing_api_anchor,
                CASE WHEN f.local_eligibility<>'POTENTIALLY_ELIGIBLE' THEN 'LOCAL_RULE_EXCLUSION'
                     WHEN f.previous_frame THEN 'PREVIOUS_FRAME_REUSE'
                     WHEN ({readiness})='CACHED_NONPOOL' THEN 'EXPLICIT_NONPOOL'
                     WHEN ({readiness})='CACHED_POOL_METADATA' THEN 'LOCAL_POOL_METADATA_READY'
                     WHEN a.game_id IS NOT NULL THEN 'PRIOR_API_NONRETURN_GAP'
                     ELSE 'NEEDS_API' END AS retrieval_disposition
                FROM frame f LEFT JOIN metadata m USING(game_id) LEFT JOIN absent a USING(game_id)'''
            nr=io.copy(c,query,tmp/'ledger.parquet')
            view=io.parq([tmp/'ledger.parquet'])
            counts=dict(c.execute('SELECT retrieval_disposition,count(*) FROM '+view+' GROUP BY 1').fetchall())
            reasons=dict(c.execute("SELECT local_eligibility,count(*) FROM "+view+" WHERE retrieval_disposition='LOCAL_RULE_EXCLUSION' GROUP BY 1").fetchall())
            missing={k:int(c.execute('SELECT count(*) FROM '+view+" WHERE retrieval_disposition='NEEDS_API' AND "+k).fetchone()[0])
                     for k in ('missing_api_source','missing_api_status','missing_api_start','missing_api_anchor','cache_conflict_or_flag')}
            if nr!=pq.ParquetFile(job['ledger']).metadata.num_rows:raise RuntimeError('Metadata merge duplicated or lost a frame row')
            io.copy(c,'SELECT game_id,utc_ms,speed_partition,retrieval_rank FROM '+view+" WHERE retrieval_disposition='NEEDS_API'",tmp/'targets.parquet')
            return dict(month=job['month'],rows=nr,counts=counts,local_exclusions=reasons,remaining_missing_fields=missing)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['ledger']]+metadata_paths+job['notreturned'])[1]

def final_plan(ledgers,metadata,notreturned,out,conf,memory,workers,inputs):
    def month_metadata(m):
        parent=Path(metadata).parent
        if (parent/'empty_metadata.parquet').exists():
            files=list((parent/'by_month'/('month='+m)).glob('*.parquet'))
            return list(map(str,sorted(files))) if files else [str(parent/'empty_metadata.parquet')]
        return [str(metadata)]
    jobs=[dict(ledger=p,metadata=month_metadata(m),notreturned=notreturned,month=m,
               output=str(out/'months'/m),conf=conf,memory=memory/workers) for m,p in zip(ex.MONTHS,ledgers)]
    rows=io.mapped(plan_month,jobs,workers,'Reducing API requests without resampling')
    def build(tmp):
        c=io.conn(tmp/'spill',memory,workers)
        try:
            targets=[str(Path(j['output'])/'targets.parquet') for j in jobs]
            n=io.copy(c,'SELECT game_id,utc_ms,speed_partition FROM '+io.parq(targets)+' ORDER BY retrieval_rank,game_id',tmp/'targets.parquet')
            total=collections.Counter();exclusions=collections.Counter();missing=collections.Counter()
            for r in rows:total.update(r['counts']);exclusions.update(r['local_exclusions']);missing.update(r['remaining_missing_fields'])
            if sum(total.values())!=FRAME_ROWS:raise RuntimeError('Entire denominator was not accounted for')
            if total['NEEDS_API']!=n:raise RuntimeError('Reduced target count differs')
            # API targets must be a subset of the inherited new-game target list.
            # Cache conflicts discovered since the old inventory may legitimately add a
            # formerly cached new game; these are reported, never silently ignored.
            newly_unresolved=c.execute('SELECT count(*) FROM '+io.parq([tmp/'targets.parquet'])+' t ANTI JOIN '+io.parq([inputs['original_targets']])+' b USING(game_id)').fetchone()[0]
            summary=dict(status='LOCAL_FIRST_TARGETS_READY',frame_rows=FRAME_ROWS,
                         original_api_targets=ORIGINAL_TARGETS,remaining_api_targets=n,
                         targets_avoided_net=ORIGINAL_TARGETS-n,
                         reduction_percent=100*(1-n/ORIGINAL_TARGETS),
                         formerly_cached_games_requiring_resolution=newly_unresolved,
                         disposition_counts=dict(total),local_exclusion_counts=dict(exclusions),remaining_missing_fields=dict(missing),
                         baseline_rate_ids_per_second=RATE,estimated_api_hours_at_baseline=n/RATE/3600,
                         primary_request_batches=math.ceil(n/300),network_requests=0,stockfish_searches=0,
                         all_frame_rows_preserved=True,all_endings_retained_for_entry=True,
                         historical_count_validation_rows=2682330,historical_count_mismatches=0,
                         new_placebo_effects_estimated=False,abstract_gate_cleared=False,
                         metadata_of_ineligible_rows_may_remain_unobserved=True,
                         author_exclusion_applied_to_targets_and_prior_decision_counts=True)
            io.js(tmp/'summary.json',summary);write_rows(tmp,'by_month',rows)
            manifest=dict(version=VERSION,original_preparation_config=PREP_CONF,config_sha256=conf,
                          denominator=[str(Path(j['output'])/'ledger.parquet') for j in jobs],
                          original_frame=inputs['frame'],merged_candidate_metadata=str(metadata),
                          original_cached_metadata=inputs['cache'],prior_api_nonreturn_files=notreturned,
                          target_file=str(out/'ready/targets.parquet'),
                          subsequent_requirements=['author-clean reference/score fitting','global identity reconciliation',
                           'first-observed-pair and previous nonadjacency','frozen prospective exposure spacing',
                           'exact follow-up and entry/outcome construction','frozen expanded comparison estimates'],
                          physical_sampling_rule_changed=False,statistical_eligibility_rules_changed=False,
                          retrieval_protocol_amendment='Apply necessary predetermined conditions before metadata retrieval; retain all frame rows and record unobserved metadata.',
                          input_lineage_sha256=inputs['lineage_sha256'])
            io.js(tmp/'ANALYSIS_INPUTS_PRIVATE.json',manifest)
            return dict(target_rows=n)
        finally:finish_connection(c,tmp/'spill')
    folder,info=io.stage(out/'ready',conf,build)
    return folder,io.load(folder/'summary.json')

def public_report(root,ready,desktop,extras):
    report=root/'report';report.mkdir(exist_ok=True)
    summary=io.load(ready/'summary.json');summary.update(extras)
    io.js(report/'summary.json',summary)
    for suffix in ('json','csv','parquet'):
        shutil.copyfile(ready/('by_month.'+suffix),report/('by_month.'+suffix))
    (report/'READ_RESULTS.txt').write_text(
        'Run 2 local-first retrieval\n\n'
        'Every one of the 61,158,951 fixed frame rows remains in a private ledger. No sample has been topped up or replaced. '
        'The preparation reads no later-kindness outcomes and makes no network calls.\n\n'
        'Necessary pre-download exclusions are: either author account; insufficient 97-day prior coverage; '
        'fewer than five lag-7 qualifying prior decisions by the opponent after removing all decisions involving the focal recipient and either author account. '
        'The unchanged historical-count implementation is checked against all 2,682,330 original spaced90 rows. '
        'Passing these checks does not certify eligibility: pool, identity, nonadjacency, first pair, prospective risk, and follow-up gates still apply.\n\n'
        'Existing PGN-derived frame Parquets and API caches are reused. No PGN flag is substituted for API pool source, exact API lastMoveAt, or timeout status. '
        'API/cache disagreements remain marked even if a newer API response is available. Known three-pass nonreturns remain explicit gaps.\n\n'
        'Metadata for locally ineligible rows may remain unknown, so complete source/ending descriptive statistics for the entire raw frame cannot be claimed. '
        'This does not alter the frozen eligible comparison population.\n\n'
        'The runtime projection divides remaining IDs by the previously observed 29.05 IDs/s, before retries/export. It is not a new measured network benchmark. '
        'Preparation does not estimate the expanded placebo, clear exclusion, or clear the abstract/title gate.\n')
    io.js(report/'REPORT_MANIFEST.json',[dict(path=p.name,bytes=p.stat().st_size,sha256=io.sha(p))
           for p in sorted(report.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json'])
    result=pack_report(report,desktop,'RUN2_LOCAL_FIRST_REPORT_'+root.name)
    io.log('RETURN THIS SMALL AGGREGATE REPORT: '+result)
    return summary

def prepare(a):
    start=time.monotonic();verify_package();project=a.project_root.resolve();desktop=a.desktop.resolve()
    if not project.is_dir():raise RuntimeError('Connect XT_Pro or set --project-root')
    desktop.mkdir(parents=True,exist_ok=True)
    with io.heartbeat('Authenticating existing prepared frame and historical inputs'):
        inputs=support.authenticate(project,a.workers)
    definition=dict(version=VERSION,package_sha256=io.sha(ROOT/'PACKAGE_MANIFEST.sha256'),
         frame_receipt=inputs['frame_receipt_sha'],history_lineage=inputs['lineage_sha256'],
         source_sample=inputs['source_sample_sha256'],original_cache_receipt=inputs['cache_receipt_sha'],
         authors=inputs['author_ids'],extra_roots=list(map(str,a.extra_cache_root)),
         count_floor=5,count_lag_days=7,prior_history_days=97)
    conf=io.cfgsha(definition);root=project/OUT_REL/conf[:12];root.mkdir(parents=True,exist_ok=True)
    with dl.exclusive(root/'RUN.lock','This local-first preparation or download is already running'),old_download_lock(desktop) as oldroot:
        io.js(root/'config.json',definition)
        io.log(f'Local preparation: {a.workers} workers; total DuckDB memory budget {a.memory_gb:g} GiB; ZERO API calls.')
        io.log('Private work: '+str(root))
        frame_gib=sum(Path(p).stat().st_size for p in inputs['frame'])/1024**3
        ex.require_disk(root,max(20,8+6*frame_gib))
        ledgers,checks,flows=support.prepare(inputs,root,conf,a.workers,a.memory_gb)
        index,_=candidate_index(ledgers,root/'candidate_index',conf,a.memory_gb,a.workers);index=index/'game_ids.npy'
        with io.heartbeat('Snapshotting existing completed and partial API requests'):
            snapshot=cache.sqlite_snapshot(oldroot,inputs['original_targets'])
        snap_id=io.cfgsha(snapshot)[:16]
        io.js(root/('old_api_snapshot_'+snap_id+'_PRIVATE.json'),snapshot)
        oldmeta,oldmissing,oldresults=cache.import_sqlite(snapshot,inputs['original_targets'],index,root/'old_api'/snap_id,a.workers)
        inv_path=root/'CACHE_INVENTORY_PRIVATE.json'
        if not inv_path.exists() or a.refresh_caches:
            with io.heartbeat('Finding additional local API and PGN-derived cache fields'):
                inventory=cache.discover(project,desktop,root,inputs['original_inventory'],a.workers,a.extra_cache_root)
            io.js(inv_path,inventory)
        inventory=io.load(inv_path)
        groups=cache.oldcache.group_jobs(inventory['files'])
        jobs=[dict(files=g,index=str(index),output=str(root/'additional_caches'/io.cfgsha(g)[:20]),
                   conf=io.cfgsha([conf,g])) for g in groups]
        scans=io.mapped(cache.scan_group,jobs,a.workers,'Reading additional local cache records') if jobs else []
        parts=[inputs['cache']]+oldmeta+[str(Path(j['output'])/'metadata.parquet') for j in jobs]
        retrieve_conf=io.cfgsha([conf,snap_id,inventory,[(str(p),io.sha(p)) for p in parts]])
        retrieve=root/'retrieval'/retrieve_conf[:16]
        with io.heartbeat('Reconciling all observed metadata fields'):
            merged,_=cache.aggregate(parts,ledgers,index,retrieve/'merged',retrieve_conf,a.memory_gb,a.workers)
        ready,summary=final_plan(ledgers,merged/'metadata.parquet',oldmissing,retrieve,retrieve_conf,a.memory_gb,a.workers,inputs)
        pointer=dict(root=str(root),ready=str(ready),config_sha256=retrieve_conf,original_api_snapshot=snapshot,
                     eligibility_ledgers=ledgers,merged_metadata=str(merged/'metadata.parquet'),prior_nonreturns=oldmissing)
        io.js(root/'LATEST_PLAN_PRIVATE.json',pointer)
        io.js(desktop/'RUN2_LOCAL_FIRST_LATEST_PRIVATE.json',pointer)
        extras=dict(local_seconds=time.monotonic()-start,workers=a.workers,memory_gb=a.memory_gb,
                    additional_cache_files=len(inventory['files']),additional_cache_parse_gaps=sum(r['cache_parse_gaps'] for r in scans),
                    unchanged_original_cache_files_reused=inventory['unchanged_original_cache_files_reused'],
                    sqlite_records_reused=sum(r['reused_records'] for r in oldresults),
                    sqlite_nonreturns_preserved=sum(r['prior_three_pass_nonreturns'] for r in oldresults),
                    unconsumed_cache_format_counts=dict(collections.Counter(r['reason'] for r in inventory['unconsumed'])))
        public_report(root,ready,desktop,extras)
        io.log(f"READY: {summary['remaining_api_targets']:,} API targets; {summary['reduction_percent']:.1f}% net reduction from the original list.")
        io.log(f"Remaining API projection: {summary['estimated_api_hours_at_baseline']:.1f} h at the historical rate, before retries/export. Preparation made zero requests.")
        io.log('Reduced download command: bash '+shlex.quote(str(ROOT/'RUN_REDUCED_DOWNLOAD.command')))
        return pointer

def load_plan(a):
    pointer=io.load(a.plan or (a.desktop/'RUN2_LOCAL_FIRST_LATEST_PRIVATE.json'))
    ready=Path(pointer['ready']);root=Path(pointer['root'])
    if io.cfgsha(io.load(root/'config.json'))!=root.name and io.cfgsha(io.load(root/'config.json'))[:12]!=root.name:
        raise RuntimeError('Local plan configuration differs')
    if io.load(root/'config.json')['package_sha256']!=io.sha(ROOT/'PACKAGE_MANIFEST.sha256'):raise RuntimeError('Plan belongs to a different code package')
    io.complete(ready,pointer['config_sha256'])
    return pointer

def show_status(pointer):
    ready=Path(pointer['ready']);folder=ready.parent/'download';total=pq.ParquetFile(ready/'targets.parquet').metadata.num_rows;done=0
    if (folder/'checkpoint.sqlite3').exists():
        with contextlib.closing(sqlite3.connect((folder/'checkpoint.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
            done=int(db.execute('SELECT coalesce(sum(requested),0) FROM batches').fetchone()[0])
    if done>total:raise RuntimeError('Download count exceeds bound target list')
    io.log(f'Reduced download: {done:,}/{total:,} IDs accounted for; {total-done:,} remain.')
    io.log(f'At historical {RATE:g} IDs/s: {(total-done)/RATE/3600:.1f} h remaining before retries/export.')
    return total,done

def download(a):
    verify_package();pointer=load_plan(a);root=Path(pointer['root']);ready=Path(pointer['ready']);target=ready/'targets.parquet'
    folder=ready.parent/'download';folder.mkdir(exist_ok=True)
    if a.mode=='status':show_status(pointer);return
    with dl.exclusive(root/'RUN.lock','This local-first run is already active'),old_download_lock(a.desktop) as oldroot:
        # Refreshing only the old request evidence is cheap and prevents duplicates if
        # the original downloader was restarted between preparation and this command.
        current=cache.sqlite_snapshot(oldroot,str(prep_root(a.project_root)/'requests/targets.parquet'))
        def evidence(s):return None if s is None else {k:s[k] for k in ('meta','batches','responses')}
        if evidence(current)!=evidence(pointer['original_api_snapshot']):
            raise RuntimeError('The original downloader added responses after this plan. Rerun RUN_LOCAL_FIRST.command to reuse them; prior local stages are checkpointed. No requests were sent.')
        total,done=show_status(pointer)
        if not (folder/'finished/_DONE.json').exists():
            original_resume.wait_for_other_collectors(a.project_root)
            api_root=Path.home()/'.cache/lichess_research_api'
            with dl.exclusive(api_root/'one_request.lock','Another cooperating Lichess API job is active'):
                dl.check_other_api_jobs(a.project_root)
                db=dl.connect(folder/'checkpoint.sqlite3',pointer['config_sha256'],io.sha(target))
                client=http.Client(api_root/'cooldown.json');started=time.monotonic();new=0
                try:
                    saved={int(k):(h,int(n)) for k,h,n in db.execute('SELECT batch,request_sha,requested FROM batches')}
                    ex.require_disk(folder,2+(max(0,total-done)*450+total*150)/1024**3)
                    for k,rows in enumerate(dl.batches(target)):
                        ids=[r['game_id'] for r in rows]
                        if k in saved:
                            if saved[k]!=(dl.binding(ids),len(rows)):raise RuntimeError('Saved reduced batch identity differs')
                            continue
                        found,missing,flags,reused=dl.process_batch(db,k,rows,client);new+=len(rows)
                        elapsed=time.monotonic()-started;rate=new/max(.001,elapsed);left=total-done-new
                        if (k+1)%10==0 or flags or not left:io.log(f'Reduced list: {done+new:,}/{total:,}; {rate:.2f} IDs/s; ETA {left/max(rate,.001)/3600:.1f} h')
                        if flags>max(3,len(found)*.05):raise RuntimeError('Over 5% metadata flags in a batch; all received evidence is saved for inspection')
                    with io.heartbeat('Verifying saved responses and exporting reduced metadata'):
                        dl.export_saved(db,target,folder/'finished',pointer['config_sha256'])
                    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                finally:db.close()
        else:io.complete(folder/'finished',pointer['config_sha256']);io.log('Reduced metadata retrieval already complete; no API requests.')
        # Keep reconciliation evidence together; a new response never erases a conflict.
        paths=[pointer['merged_metadata'],str(folder/'finished/downloaded_metadata.parquet')]
        with io.heartbeat('Merging downloaded fields with all prior cache evidence'):
            merged,_=cache.aggregate(paths,pointer['eligibility_ledgers'],None,folder/'merged_final',pointer['config_sha256'],a.memory_gb,a.workers)
        io.js(folder/'ANALYSIS_INPUTS_PRIVATE.json',dict(io.load(ready/'ANALYSIS_INPUTS_PRIVATE.json'),
            merged_candidate_metadata=str(merged/'metadata.parquet'),download_summary=str(folder/'finished/SUMMARY.json'),
            additional_nonreturn_file=str(folder/'finished/not_returned.parquet'),expanded_effects_estimated=False))
        report=root/'download_report';report.mkdir(exist_ok=True)
        io.js(report/'summary.json',dict(io.load(folder/'finished/SUMMARY.json'),
            original_frame_rows=FRAME_ROWS,original_api_targets=ORIGINAL_TARGETS,
            reduced_target_rows=total,abstract_gate_cleared=False,
            subsequent_stage='Frozen expanded entry/placebo estimation with identity/source reconciliation',
            preserved_local_preparation_summary=io.load(ready/'summary.json')))
        (report/'READ_RESULTS.txt').write_text('Reduced metadata retrieval is complete. This is not an expanded placebo estimate.\n'
            'The private analysis-input manifest combines the unchanged frame, eligibility ledger, cache evidence, and reduced API return. '
            'Missing IDs and metadata conflicts remain explicit. Global identity and frozen analysis construction still apply.\n')
        path=pack_report(report,a.desktop,'RUN2_REDUCED_DOWNLOAD_REPORT_'+pointer['config_sha256'][:12])
        io.log('RETURN THIS SMALL AGGREGATE REPORT: '+path)

def main():
    w,m=defaults();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['prepare','download','status'])
    p.add_argument('--project-root',type=Path,default=BASE)
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=w);p.add_argument('--memory-gb',type=float,default=m)
    p.add_argument('--extra-cache-root',type=Path,action='append',default=[])
    p.add_argument('--refresh-caches',action='store_true');p.add_argument('--plan',type=Path)
    a=p.parse_args();a.project_root=a.project_root.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    a.workers=max(1,min(10,a.workers));a.memory_gb=max(2,a.memory_gb)
    a.workers=min(a.workers,max(1,int(a.memory_gb//1.5)))
    os.umask(0o077)
    try:
        if a.mode=='prepare':prepare(a)
        else:download(a)
    except KeyboardInterrupt:io.log('Interrupted; completed checkpoints and API responses remain reusable.');raise SystemExit(130)
    except Exception as exc:io.log('STOPPED: '+str(exc));raise SystemExit(2)
if __name__=='__main__':main()
