#!/usr/bin/env python3
"""Continue through 100%, writing 25/50/75/100% reports and two live ETAs."""
from continuous_common import *
import argparse
import time
import zipfile
import checkpoint_75 as middle
from progress_eta import Progress
import metadata_http as http
import original_resume


def marker_path(addon, percent):
    return addon / f'REPORT_{percent:03}_DONE.json'


def completed_report(root, addon, desktop, percent, controller_conf):
    marker = marker_path(addon, percent)
    if not marker.exists():
        return False
    r = io.load(marker)
    if r['controller_conf'] != controller_conf:
        raise RuntimeError('Checkpoint report belongs to a different continuation')
    report = root / 'phase_results' / str(percent) / 'report'
    manifest = report / 'REPORT_MANIFEST.json'
    io.checked(manifest, r['manifest_sha256'])
    for item in io.load(manifest):
        io.checked(io.child(report, item['path']), item['sha256'], item['bytes'])
    io.checked(root / 'phase_results' / str(percent) / 'ANALYSIS_INPUTS_PRIVATE.json', r['inputs_sha256'])
    archive = desktop / f'RUN2_PHASE_{percent:03}_REPORT_{root.name}.zip'
    sidecar = Path(str(archive)+'.sha256')
    if not archive.is_file() or not sidecar.is_file():
        report_zip(report, desktop, archive.stem)
    else:
        io.checked(archive, sidecar.read_text().split()[0])
    return True


def publish(up, state, root, addon, a, conf, controller_conf, percent, plan75):
    if completed_report(root, addon, a.desktop, percent, controller_conf):
        io.log(f'Checkpoint {percent}% report already saved and verified; reused.')
        return
    if percent == 75:
        folders = [root/'download'/str(p)/'finished' for p in (10,25,50)] + [addon/'snapshot75/finished']
        plan_row = plan75['summary']
        month_rows = [r for r in io.load(Path(state['plan'])/'by_month.json') if 0<r['phase_percent']<=50] + plan75['by_month']
    else:
        folders = [root/'download'/str(p)/'finished' for p in pc.PHASES if p<=percent]
        plan_row = next(r for r in state['summary']['phases'] if r['through_percent']==percent)
        month_rows = [r for r in io.load(Path(state['plan'])/'by_month.json') if 0<r['phase_percent']<=percent]
    parts = [state['metadata']] + [str(f/'downloaded_metadata.parquet') for f in folders]
    output = root/'phase_results'/str(percent)
    output.mkdir(parents=True, exist_ok=True)
    ex.require_disk(output, 2 + sum(Path(p).stat().st_size for p in parts)*2/1024**3)
    merged, _ = cache.aggregate(parts, up['eligibility_ledgers'], None, output/'merged',
                                io.cfgsha([conf,percent]), a.memory_gb, a.workers)
    sums = [io.load(f/'SUMMARY.json') for f in folders]
    inputs = dict(version=pc.PHASE_VERSION, continuation_version=VERSION,
        upstream_manifest=up['manifest'], fixed_denominator=up['ledgers'],
        additional_frame_selection_sql=selection(percent), old_frame_selection_sql='f.previous_frame',
        through_percent=percent, inherited_rank_seed=ex.ORDER_SEED.decode('ascii'),
        all_frame_rows_preserved=True, original_cached_metadata=up['manifest']['original_cached_metadata'],
        merged_candidate_metadata=str(merged/'metadata.parquet'),
        nonreturn_files=state['nonreturns']+[str(f/'not_returned.parquet') for f in folders],
        full_historical_and_prospective_anchor_stream_required=True,
        final_sample_and_rules_unchanged=True, interim_estimates_are_descriptive=True,
        abstract_gate_cleared=False, expanded_effects_estimated=False,
        subsequent_requirements=up['manifest']['subsequent_requirements'])
    io.js(output/'ANALYSIS_INPUTS_PRIVATE.json', inputs)
    report = output/'report'; report.mkdir(exist_ok=True)
    summary = dict(plan_row, upstream_run=pc.UPSTREAM_RUN, through_percent=percent,
        requested=sum(s['requested'] for s in sums), returned=sum(s['returned'] for s in sums),
        not_returned=sum(s['not_returned'] for s in sums),
        metadata_flags=sum(s['returned_with_metadata_flags'] for s in sums),
        sqlite_audit=io.load(root/'SQLITE_AUDIT.json'), behavioral_estimates_computed=False,
        abstract_gate_cleared=False, phase_membership_includes_cached_and_uncached=True,
        all_requested_ids_accounted=True, metadata_conflicts_retained=True,
        continuation_version=VERSION, automatic_continuation=percent<100,
        stopping_rule='save fixed 25/50/75/100% reports; continue automatically through 100%; final design retained')
    if summary['requested'] != plan_row['cumulative_targets']:
        raise RuntimeError('Cumulative checkpoint denominator differs')
    summary['status'] = ('PHASE_METADATA_ACCOUNTED_WITH_GAPS' if summary['not_returned'] or
                         summary['metadata_flags'] else 'PHASE_METADATA_ACCOUNTED')
    io.js(report/'summary.json', summary)
    write_rows(report, 'by_month', month_rows)
    (report/'READ_RESULTS.txt').write_text(
        f'Fixed {percent}% metadata checkpoint. The downloader continues automatically through 100%.\n'
        'The same inherited full SHA-256 rank selects cached, uncached, excluded and nonreturned games.\n'
        'All ending types and the full original denominator remain represented.\n'
        'The 75% report excludes any above-threshold games returned in its boundary request; those responses remain saved for 100%.\n'
        'This report contains retrieval accounting, not behavioral estimates. Global identity alignment, frozen histories,\n'
        'author-clean score fitting, follow-up construction and clustered estimation remain the analysis step.\n'
        'Interim results describe stability and precision; final sample membership and specification remain fixed.\n')
    report_zip(report, a.desktop, f'RUN2_PHASE_{percent:03}_REPORT_{root.name}')
    io.js(marker_path(addon,percent), dict(controller_conf=controller_conf,
        manifest_sha256=io.sha(report/'REPORT_MANIFEST.json'),
        inputs_sha256=io.sha(output/'ANALYSIS_INPUTS_PRIVATE.json')))
    io.js(root/'LATEST_ANALYSIS_PRIVATE.json', dict(through_percent=percent,
        manifest=str(output/'ANALYSIS_INPUTS_PRIVATE.json')))
    io.log(f'CHECKPOINT_{percent:03}_SAVED' + ('; continuing automatically.' if percent<100 else '; full download complete.'))


def download_band(root, addon, percent, band, tracker, on75=None):
    target = band['target']; folder = root/'download'/str(percent)
    folder.mkdir(parents=True, exist_ok=True)
    finished = folder/'finished'
    if (finished/'_DONE.json').is_file():
        if percent==100 and on75:
            with pc.open_readonly(folder/'checkpoint.sqlite3') as db:
                on75(db, target)
        io.log(f'Existing {percent}% request band is complete; no API calls for this band.')
        return
    ex.require_disk(folder, 2+(max(0,band['total']-band['done'])*450+band['total']*150)/1024**3)
    db = dl.connect(folder/'checkpoint.sqlite3', band['conf'], band['sha256'])
    client = http.Client(Path.home()/'.cache/lichess_research_api/cooldown.json')
    started = time.monotonic(); added = 0
    try:
        if percent==100 and on75:
            on75(db,target)
        saved = {int(k):(h,int(n)) for k,h,n in db.execute('SELECT batch,request_sha,requested FROM batches')}
        tracker.set_stage(f'downloading the existing band ending at {percent}%')
        for k, rows in enumerate(dl.batches(target)):
            if k in saved:
                if saved[k] != (dl.binding([r['game_id'] for r in rows]),len(rows)):
                    raise RuntimeError('Saved request binding changed')
                continue
            found, missing, flags, _ = dl.process_batch(db,k,rows,client)
            added += len(rows); tracker.advance(len(rows))
            if flags > max(3,len(found)*.05):
                raise RuntimeError('More than 5% metadata flags in a batch; saved responses remain reusable')
            if percent==100 and on75:
                on75(db,target)
            tracker.set_stage(f'downloading the existing band ending at {percent}%')
        with tracker.local_work(f'exporting the {percent}% request band to Parquet'):
            dl.export_saved(db,target,finished,band['conf'])
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        db.close()
        io.js(addon/f'INVOCATION_BAND_{percent}.json', dict(new_accounted_ids=added,
            elapsed_seconds=time.monotonic()-started, network_requests=client.requests,
            http_seconds=client.http_seconds))


def execute_download(up, state, root, addon, a, conf, controller_conf, bands, plan75):
    targets = {r['through_percent']:r['cumulative_targets'] for r in state['summary']['phases']
               if r['through_percent'] in CHECKPOINTS}
    targets[75] = plan75['summary']['cumulative_targets']
    tracker = Progress(sum(b['done'] for b in bands.values()), targets, RATE, io.log, a.eta_seconds)
    for p in CHECKPOINTS:
        if completed_report(root,addon,a.desktop,p,controller_conf):
            tracker.completed_reports.add(p)
    io.log('ETAs cover remaining retrieval at the observed rate. Local Parquet export/report time is additional. Updates every '+str(a.eta_seconds)+' seconds, including during retries.')
    snapshot_conf = io.cfgsha([conf,75,bands[100]['sha256'],plan75['prefix_targets'],'original-batch-prefix-v1'])

    def at75(db,target):
        if 75 in tracker.completed_reports:
            return
        if tracker.done < targets[75]:
            return
        if not middle.prefix_available(db,plan75['prefix_targets']):
            return
        with tracker.local_work('saving the exact 75% snapshot and report'):
            middle.export_prefix(db,target,plan75['prefix_targets'],addon/'snapshot75/finished',snapshot_conf)
            publish(up,state,root,addon,a,conf,controller_conf,75,plan75)
        tracker.report_done(75)

    with tracker:
        for percent in (25,50,100):
            download_band(root,addon,percent,bands[percent],tracker,at75 if percent==100 else None)
            with tracker.local_work(f'saving the cumulative {percent}% report'):
                publish(up,state,root,addon,a,conf,controller_conf,percent,plan75)
            tracker.report_done(percent)
    if tracker.completed_reports != set(CHECKPOINTS) or tracker.done != targets[100]:
        raise RuntimeError('Final continuation accounting is incomplete')
    io.log('CONTINUOUS_DOWNLOAD_100_COMPLETE. Reports at 25%, 50%, 75% and 100% are saved on the Desktop.')


def run(a):
    verify_release()
    if not a.project_root.is_dir():
        raise RuntimeError('Connect XT_Pro or set IV_PROJECT_ROOT')
    with io.heartbeat('Authenticating the completed local-first and 10% checkpoints'):
        up = pc.authenticate(a)
        root, conf, state, bands = load_existing(a,up)
    controller_conf = io.cfgsha(dict(version=VERSION, package_sha256=io.sha(CONTROLLER_PACKAGE/'PACKAGE_MANIFEST.sha256'),
                                    inherited_config=conf, checkpoints=list(CHECKPOINTS)))
    addon = root/'continuous_v100'/controller_conf[:12]
    if a.mode=='status':
        done = sum(b['done'] for b in bands.values())
        total = sum(b['total'] for b in bands.values())
        io.log(f'Fixed API targets accounted: {done:,}/{total:,}; remaining {(total-done)/RATE/3600:.1f} h at the prior rate.')
        for p in CHECKPOINTS:
            marker = marker_path(addon,p)
            io.log(f'{p}% report: '+('saved' if marker.exists() else 'pending'))
        return
    with dl.exclusive(root/'RUN.lock','Another phased or continuous downloader is active; pause it with Ctrl-C first'), \
         dl.exclusive(Path(up['root'])/'RUN.lock','Pause the local-first preparation or reduced downloader first'), \
         old_download_lock(a.desktop):
        original_resume.wait_for_other_collectors(a.project_root)
        with dl.exclusive(Path.home()/'.cache/lichess_research_api/one_request.lock','Another cooperating Lichess API job is active'):
            dl.check_other_api_jobs(a.project_root)
            # A previous process may have completed a request after initial
            # verification but before we acquired the shared run lock.
            for p,band in bands.items():
                _,band['done'] = legacy.progress(root/'download'/str(p),band['target'],band['conf'])
            addon.mkdir(parents=True,exist_ok=True)
            io.js(addon/'config.json',dict(version=VERSION,inherited_config=conf,controller_config=controller_conf,
                original_request_lists_unchanged=True,checkpoints=list(CHECKPOINTS)))
            io.log(f'Reusing completed 10% and all further saved responses; {a.workers} local workers, {a.memory_gb:g} GiB budget.')
            plan75 = middle.prepare(up,state,root,addon,a,controller_conf)
            for row in state['summary']['phases']+[plan75['summary']]:
                if row['through_percent'] in CHECKPOINTS:
                    io.log(f"Checkpoint {row['through_percent']}%: {row['cumulative_targets']:,} cumulative API targets.")
            execute_download(up,state,root,addon,a,conf,controller_conf,bands,plan75)


def main():
    workers,memory = defaults()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['download','status'])
    p.add_argument('--project-root',type=Path,default=BASE)
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--plan',type=Path)
    p.add_argument('--phase-pointer',type=Path)
    p.add_argument('--workers',type=int,default=workers)
    p.add_argument('--memory-gb',type=float,default=memory)
    p.add_argument('--eta-seconds',type=int,default=30)
    a = p.parse_args()
    a.project_root=a.project_root.expanduser().resolve(); a.desktop=a.desktop.expanduser().resolve()
    if a.workers<1 or a.memory_gb<2 or not 5<=a.eta_seconds<=60:
        p.error('Use at least one worker, 2 GiB memory, and ETA updates between 5 and 60 seconds')
    a.workers=max(1,min(10,a.workers,int(a.memory_gb//1.5)))
    os.umask(0o077)
    try:
        run(a)
    except KeyboardInterrupt:
        io.log('Interrupted. Saved API responses, completed Parquets and reports remain reusable. Rerun RUN_TO_100.command.'); raise SystemExit(130)
    except Exception as exc:
        io.log('STOPPED: '+str(exc)+'. Saved work remains reusable.'); raise SystemExit(2)


if __name__=='__main__':
    main()
