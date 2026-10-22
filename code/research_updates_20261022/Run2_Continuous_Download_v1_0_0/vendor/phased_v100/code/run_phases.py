#!/usr/bin/env python3
"""Reuse the completed local-first run; download fixed nested phases and stop."""
from phase_common import *
import argparse,collections,math,shlex,time
import sqlite_reuse as reuse
import original_resume
import metadata_http as http

def month_plan(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([job['ledger']]))
            bad=c.execute('SELECT count(*) FROM f WHERE retrieval_rank IS NULL OR octet_length(retrieval_rank)<>32 OR previous_frame IS NULL').fetchone()[0]
            if bad:raise RuntimeError('Invalid inherited hash rank or old-frame membership')
            if job['refresh_metadata']:
                c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq(job['metadata']))
                if job['nonreturns']:c.execute('CREATE VIEW a AS SELECT DISTINCT game_id FROM '+io.parq(job['nonreturns']))
                else:c.execute('CREATE VIEW a AS SELECT NULL::VARCHAR AS game_id WHERE FALSE')
                ready=original_plan.readiness_sql()
                disposition=f"""CASE WHEN f.local_eligibility<>'POTENTIALLY_ELIGIBLE' THEN 'LOCAL_RULE_EXCLUSION'
                    WHEN f.previous_frame THEN 'PREVIOUS_FRAME_REUSE'
                    WHEN ({ready})='CACHED_NONPOOL' THEN 'EXPLICIT_NONPOOL'
                    WHEN ({ready})='CACHED_POOL_METADATA' THEN 'LOCAL_POOL_METADATA_READY'
                    WHEN a.game_id IS NOT NULL THEN 'PRIOR_API_NONRETURN_GAP'
                    ELSE 'NEEDS_API' END"""
                source='f LEFT JOIN m USING(game_id) LEFT JOIN a USING(game_id)'
            else:disposition='f.retrieval_disposition';source='f'
            c.execute('CREATE TABLE compact AS SELECT f.game_id,f.utc_ms,f.speed_partition,f.retrieval_rank,'+
                phase_sql()+' AS phase_percent,('+disposition+') AS retrieval_disposition FROM '+source)
            n=c.execute('SELECT count(*) FROM compact').fetchone()[0]
            if n!=pq.ParquetFile(job['ledger']).metadata.num_rows:raise RuntimeError('Cache join duplicated or lost frame rows')
            counts=[dict(phase_percent=int(p),disposition=d,rows=int(n)) for p,d,n in
                    c.execute('SELECT phase_percent,retrieval_disposition,count(*) FROM compact GROUP BY 1,2 ORDER BY 1,2').fetchall()]
            target_counts={}
            for p in PHASES:
                target_counts[str(p)]=io.copy(c,'SELECT game_id,utc_ms,speed_partition,retrieval_rank FROM compact '+
                    f"WHERE phase_percent={p} AND retrieval_disposition='NEEDS_API'",tmp/f'targets_{p}.parquet')
            io.js(tmp/'counts.json',counts)
            return dict(month=job['month'],rows=n,counts=counts,target_counts=target_counts)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['ledger']]+job['metadata']+job['nonreturns'])[1]

def build_plan(up,root,a,conf,metadata,nonreturns,refresh_metadata):
    parent=Path(metadata).parent
    def for_month(month):
        if (parent/'empty_metadata.parquet').exists():
            found=sorted((parent/'by_month'/('month='+month)).glob('*.parquet'))
            return list(map(str,found)) if found else [str(parent/'empty_metadata.parquet')]
        return [metadata]
    jobs=[dict(ledger=p,month=m,metadata=for_month(m) if refresh_metadata else [],nonreturns=nonreturns if refresh_metadata else [],
               refresh_metadata=refresh_metadata,memory=a.memory_gb/a.workers,conf=conf,output=str(root/'months'/m))
          for m,p in zip(ex.MONTHS,up['ledgers'])]
    results=io.mapped(month_plan,jobs,a.workers,'Partitioning existing request lists into fixed phases')
    def combine(tmp):
        c=io.conn(tmp/'spill',a.memory_gb,a.workers)
        try:
            total=collections.Counter();by_month=[]
            for row in results:
                for rec in row['counts']:
                    total[(rec['phase_percent'],rec['disposition'])]+=rec['rows']
                    by_month.append(dict(month=row['month'],**rec))
            frame_rows=sum(total.values())
            if frame_rows!=FRAME_ROWS:raise RuntimeError('Phase partition does not cover the entire fixed frame')
            if sum(v for (p,d),v in total.items() if p==0)!=ex.OLD_ROWS:raise RuntimeError('Old comparison frame changed')
            phases=[]
            for percent in PHASES:
                parts=[str(Path(j['output'])/f'targets_{percent}.parquet') for j in jobs]
                n=io.copy(c,'SELECT game_id,utc_ms,speed_partition FROM '+io.parq(parts)+
                    ' ORDER BY retrieval_rank,game_id',tmp/f'targets_{percent}.parquet')
                if n!=total[(percent,'NEEDS_API')]:raise RuntimeError('Phase request accounting differs')
                phases.append(dict(through_percent=percent,incremental_targets=n,
                    cumulative_targets=sum(total[(p,'NEEDS_API')] for p in PHASES if p<=percent),
                    additional_frame_rows=sum(v for (p,d),v in total.items() if 0<p<=percent),
                    original_frame_rows=ex.OLD_ROWS,
                    cached_pool_rows=sum(v for (p,d),v in total.items() if 0<p<=percent and d=='LOCAL_POOL_METADATA_READY'),
                    prior_nonreturn_gaps=sum(v for (p,d),v in total.items() if 0<p<=percent and d=='PRIOR_API_NONRETURN_GAP')))
            summary=dict(frame_rows=frame_rows,phases=phases,original_remaining_targets=up['summary']['remaining_api_targets'],
                final_remaining_targets=sum(p['incremental_targets'] for p in phases),
                additional_targets_avoided_net=up['summary']['remaining_api_targets']-sum(p['incremental_targets'] for p in phases),
                phase_selection='same inherited SHA-256 rank, thresholds floor(2^256 * percent/100)',
                cached_games_included_in_phase_membership=True,all_months_included=True,
                original_sample_reused_separately=True,full_final_target_unchanged=True,
                new_coefficients_used_for_sampling=False,behavioral_estimates_computed=False)
            io.js(tmp/'summary.json',summary);write_rows(tmp,'by_month',by_month)
            return dict(frame_rows=frame_rows,target_rows=summary['final_remaining_targets'])
        finally:finish_connection(c,tmp/'spill')
    folder,_=io.stage(root/'plan',conf,combine)
    return folder,io.load(folder/'summary.json')

def bootstrap(up,root,a,conf):
    source_path=root/'sqlite_sources_PRIVATE.json'
    if source_path.exists():
        sources=io.load(source_path)
        for r in sources:
            if reuse.database_signature(r['path'])!=r['signature']:
                raise RuntimeError('An external SQLite cache changed after the phased plan was frozen. Its saved responses need reconciliation before continuing: '+r['path'])
    else:
        with io.heartbeat('Inspecting the existing SQLite inventory and request bindings'):
            sources=reuse.collect_sources(up,a)
        io.js(source_path,sources)
    parts,missing,audit=reuse.import_sources(sources,up,root/'sqlite_reuse',a,conf)
    io.js(root/'SQLITE_AUDIT.json',audit)
    matched=sum(r['reused_records'] for r in audit)
    nonreturns=list(up['pointer']['prior_nonreturns'])+missing
    refresh=matched>0 or sum(r['prior_nonreturns'] for r in audit)>0
    metadata=up['metadata']
    if refresh:
        with io.heartbeat('Reconciling verified SQLite fields with recovered metadata'):
            merged,_=cache.aggregate([metadata]+parts,up['eligibility_ledgers'],None,root/'merged_sqlite',conf,a.memory_gb,a.workers)
        metadata=str(merged/'metadata.parquet')
    io.log(f'SQLite inspection: {len(sources)} locations; {matched:,} matching metadata records reused.')
    plan,summary=build_plan(up,root,a,conf,metadata,nonreturns,refresh)
    report=root/'plan_report';report.mkdir(exist_ok=True)
    io.js(report/'summary.json',dict(summary,sqlite_audit=audit,workers=a.workers,memory_gb=a.memory_gb,
        network_requests=0,stockfish_searches=0,upstream_run=UPSTREAM_RUN))
    for suffix in ('json','csv','parquet'):shutil.copyfile(plan/('by_month.'+suffix),report/('by_month.'+suffix))
    report_zip(report,a.desktop,'RUN2_PHASE_PLAN_REPORT_'+root.name)
    return dict(plan=str(plan),metadata=metadata,nonreturns=nonreturns,summary=summary)

def progress(folder,target,conf):
    total=pq.ParquetFile(target).metadata.num_rows;done=0
    if (folder/'checkpoint.sqlite3').exists():
        with open_readonly(folder/'checkpoint.sqlite3') as db:
            meta=dict(db.execute('SELECT key,value FROM meta'))
            if meta.get('config_sha256')!=conf or meta.get('target_sha256')!=io.sha(target):
                raise RuntimeError('Phase checkpoint no longer matches its fixed target file')
            done=int(db.execute('SELECT coalesce(sum(requested),0) FROM batches').fetchone()[0])
    if done>total:raise RuntimeError('Saved phase count exceeds its target list')
    return total,done

def download_band(root,plan,percent,conf,a):
    target=Path(plan)/f'targets_{percent}.parquet';folder=root/'download'/str(percent);folder.mkdir(parents=True,exist_ok=True)
    band_conf=io.cfgsha([conf,percent,io.sha(target)])
    total,done=progress(folder,target,band_conf)
    io.log(f'Phase {percent}% increment: {done:,}/{total:,} targets accounted; projected remaining {(total-done)/RATE/3600:.1f} h at the prior rate.')
    finished=folder/'finished'
    if (finished/'_DONE.json').exists():
        io.complete(finished,band_conf);io.log(f'Phase {percent}% increment already complete; no new requests.');return folder
    ex.require_disk(folder,2+(max(0,total-done)*450+total*150)/1024**3)
    db=dl.connect(folder/'checkpoint.sqlite3',band_conf,io.sha(target))
    client=http.Client(Path.home()/'.cache/lichess_research_api/cooldown.json');started=time.monotonic();new=0
    try:
        saved={int(k):(h,int(n)) for k,h,n in db.execute('SELECT batch,request_sha,requested FROM batches')}
        with io.heartbeat(f'Phase {percent}% metadata retrieval; each response is checkpointed'):
            for k,rows in enumerate(dl.batches(target)):
                if k in saved:
                    if saved[k]!=(dl.binding([r['game_id'] for r in rows]),len(rows)):raise RuntimeError('Phase request binding changed')
                    continue
                found,missing,flags,_=dl.process_batch(db,k,rows,client);new+=len(rows)
                rate=new/max(.001,time.monotonic()-started);left=total-done-new
                if (k+1)%10==0 or flags or not left:
                    io.log(f'Phase {percent}% increment {done+new:,}/{total:,}; {rate:.2f} IDs/s; ETA {left/max(rate,.001)/3600:.1f} h')
                if flags>max(3,len(found)*.05):raise RuntimeError('More than 5% metadata flags in a batch; received evidence remains saved')
        with io.heartbeat(f'Exporting phase {percent}% metadata to Parquet'):
            dl.export_saved(db,target,finished,band_conf)
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:db.close()
    io.js(folder/'INVOCATION.json',dict(new_accounted_ids=new,elapsed_seconds=time.monotonic()-started,
        network_requests=client.requests,http_seconds=client.http_seconds))
    return folder

def publish_phase(up,state,root,a,conf,percent):
    folders=[root/'download'/str(p)/'finished' for p in PHASES if p<=percent]
    metadata_parts=[state['metadata']]+[str(f/'downloaded_metadata.parquet') for f in folders]
    output=root/'phase_results'/str(percent)
    with io.heartbeat(f'Reconciling cumulative phase {percent}% metadata'):
        merged,_=cache.aggregate(metadata_parts,up['eligibility_ledgers'],None,output/'merged',
                                 io.cfgsha([conf,percent]),a.memory_gb,a.workers)
    sums=[io.load(f/'SUMMARY.json') for f in folders]
    plan_row=next(p for p in state['summary']['phases'] if p['through_percent']==percent)
    # Selection is applied to the whole additional frame, not to cached or
    # successfully returned rows. Historical/exposure streams stay complete.
    inputs=dict(version=PHASE_VERSION,upstream_manifest=up['manifest'],
        fixed_denominator=up['ledgers'],additional_frame_selection_sql=selection_sql(percent),
        old_frame_selection_sql='f.previous_frame',through_percent=percent,
        inherited_rank_seed=ex.ORDER_SEED.decode('ascii'),all_frame_rows_preserved=True,
        original_cached_metadata=up['manifest']['original_cached_metadata'],
        merged_candidate_metadata=str(merged/'metadata.parquet'),
        nonreturn_files=state['nonreturns']+[str(f/'not_returned.parquet') for f in folders],
        full_historical_and_prospective_anchor_stream_required=True,
        final_sample_and_rules_unchanged=True,interim_estimates_are_descriptive=True,
        abstract_gate_cleared=False,expanded_effects_estimated=False,
        subsequent_requirements=up['manifest']['subsequent_requirements'])
    io.js(output/'ANALYSIS_INPUTS_PRIVATE.json',inputs)
    report=output/'report';report.mkdir(exist_ok=True)
    summary=dict(plan_row,upstream_run=UPSTREAM_RUN,through_percent=percent,
        requested=sum(s['requested'] for s in sums),returned=sum(s['returned'] for s in sums),
        not_returned=sum(s['not_returned'] for s in sums),metadata_flags=sum(s['returned_with_metadata_flags'] for s in sums),
        sqlite_audit=io.load(root/'SQLITE_AUDIT.json'),behavioral_estimates_computed=False,
        abstract_gate_cleared=False,phase_membership_includes_cached_and_uncached=True,
        all_requested_ids_accounted=True,metadata_conflicts_retained=True,
        stopping_rule='automatic operational stop at requested fixed phase; final 100% design retained')
    if summary['requested']!=plan_row['cumulative_targets']:raise RuntimeError('Cumulative phase denominator differs')
    summary['status']='PHASE_METADATA_ACCOUNTED_WITH_GAPS' if summary['not_returned'] or summary['metadata_flags'] else 'PHASE_METADATA_ACCOUNTED'
    io.js(report/'summary.json',summary)
    rows=io.load(Path(state['plan'])/'by_month.json')
    write_rows(report,'by_month',[r for r in rows if 0<r['phase_percent']<=percent])
    (report/'READ_RESULTS.txt').write_text(
        'This fixed phase includes cached and uncached games in every month. All ending types are retained.\n'
        'The full original denominator is referenced in the private analysis manifest; no failed request is silently dropped.\n'
        'Completed requests, partial responses, nonreturns and metadata conflicts remain saved.\n'
        'This is a metadata checkpoint, not a placebo coefficient. Global identity alignment, frozen exposure and outcome construction,\n'
        'author-clean score fitting, clustered estimation and the specified diagnostics remain the analysis step.\n'
        'Interim findings describe stability and precision. The planned 100% analysis and specification remain fixed.\n')
    report_zip(report,a.desktop,f'RUN2_PHASE_{percent:03}_REPORT_'+root.name)
    io.js(root/'LATEST_ANALYSIS_PRIVATE.json',dict(through_percent=percent,manifest=str(output/'ANALYSIS_INPUTS_PRIVATE.json')))
    return summary

def run(a):
    verify_release();a.desktop.mkdir(parents=True,exist_ok=True)
    if not a.project_root.is_dir():raise RuntimeError('Connect XT_Pro or set IV_PROJECT_ROOT')
    with io.heartbeat('Authenticating completed local-first outputs'):
        up=authenticate(a)
    definition=dict(version=PHASE_VERSION,package_sha256=io.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),
        upstream_run=UPSTREAM_RUN,upstream_plan=UPSTREAM_PLAN,input_receipts=up['input_receipts'],
        phases=list(PHASES),phase_rule='inherited rank < floor(2^256 * percent/100)',
        extra_sqlite=list(map(str,a.extra_sqlite)))
    conf=io.cfgsha(definition);root=a.project_root/PHASE_REL/conf[:12]
    if a.mode=='status':
        if not (root/'STATE_PRIVATE.json').exists():io.log('No phased plan yet. Run RUN_PHASE_10.command.');return
        state=io.load(root/'STATE_PRIVATE.json')
        for p in PHASES:
            target=Path(state['plan'])/f'targets_{p}.parquet'
            band_conf=io.cfgsha([conf,p,io.sha(target)])
            total,done=progress(root/'download'/str(p),target,band_conf)
            io.log(f'Through {p}% incremental band: {done:,}/{total:,}; remaining {(total-done)/RATE/3600:.1f} h at prior rate')
        return
    root.mkdir(parents=True,exist_ok=True)
    if not (root/'STATE_PRIVATE.json').exists():ex.require_disk(root,8)
    with dl.exclusive(root/'RUN.lock','This phased download is already active'),\
         dl.exclusive(Path(up['root'])/'RUN.lock','Pause the local-first preparation or reduced downloader first'),\
         old_download_lock(a.desktop):
        if a.mode=='download':original_resume.wait_for_other_collectors(a.project_root)
        global_lock=Path.home()/'.cache/lichess_research_api/one_request.lock'
        with contextlib.ExitStack() as stack:
            if a.mode=='download':
                stack.enter_context(dl.exclusive(global_lock,'Another cooperating Lichess API job is active'))
                dl.check_other_api_jobs(a.project_root)
            io.js(root/'config.json',definition)
            io.log(f'Reusing local-first run {UPSTREAM_RUN}; {a.workers} local workers, {a.memory_gb:g} GiB budget. No history rebuild or broad cache rescan.')
            state=bootstrap(up,root,a,conf);io.js(root/'STATE_PRIVATE.json',state)
            io.js(a.desktop/'RUN2_PHASED_LATEST_PRIVATE.json',dict(root=str(root),package=str(PACKAGE),config_sha256=conf))
            for p in state['summary']['phases']:
                io.log(f"Through {p['through_percent']}%: {p['additional_frame_rows']:,} added frame rows; {p['cumulative_targets']:,} cumulative targets; {p['cumulative_targets']/RATE/3600:.1f} h at prior rate.")
            if a.mode=='prepare':io.log('PHASE_PLAN_READY; zero API requests.');return
            for percent in PHASES:
                if percent>a.through:break
                download_band(root,state['plan'],percent,conf,a)
                publish_phase(up,state,root,a,conf,percent)
            io.log(f'PHASE_{a.through}_COMPLETE. Stopped automatically. The same command resumes safely; the next phase reuses completed bands.')

def main():
    w,m=defaults();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['prepare','download','status'])
    p.add_argument('--through',type=int,choices=PHASES,default=10)
    p.add_argument('--project-root',type=Path,default=BASE)
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--plan',type=Path)
    p.add_argument('--workers',type=int,default=w);p.add_argument('--memory-gb',type=float,default=m)
    p.add_argument('--extra-sqlite',type=Path,action='append',default=[])
    a=p.parse_args();a.project_root=a.project_root.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    a.memory_gb=max(2,a.memory_gb);a.workers=max(1,min(10,a.workers,int(a.memory_gb//1.5)))
    a.extra_sqlite=[x.expanduser().resolve() for x in a.extra_sqlite]
    os.umask(0o077)
    try:run(a)
    except KeyboardInterrupt:io.log('Interrupted; committed API responses and completed Parquets remain reusable.');raise SystemExit(130)
    except Exception as exc:io.log('STOPPED: '+str(exc));raise SystemExit(2)

if __name__=='__main__':main()
