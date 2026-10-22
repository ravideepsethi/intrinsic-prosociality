#!/usr/bin/env python3
"""Run 2 metadata continuation: fixed sample, live status, no duplicate API worker."""
from __future__ import annotations
from common import *
import argparse, contextlib, fcntl, math, shlex, sqlite3, subprocess, time
sys.path.insert(0,str(ROOT/'comparison_original'))
import download_expansion as download
import expansion_common as expansion
import metadata_http as http

CONF='628dfb8f80a89dd04d287b40326c408ae13c20e4bd4eabb7bec71b03b697d37f'
TARGETS_AT_PREPARATION=57087753
FRAME_ROWS=61158951
BASELINE_RATE=29.05

def checkpoint_root(desktop):return desktop/('CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_'+CONF[:12]+'_PRIVATE')

def counts(root):
    path=root/'checkpoint.sqlite3'
    if not path.exists():return dict(completed_batches=0,accounted_ids=0,returned_ids=0,metadata_flags=0)
    # Query the actual live WAL safely; never copy the database while it is active.
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=60) as db:
        m=dict(db.execute('SELECT key,value FROM meta'))
        if m.get('config_sha256')!=CONF:raise RuntimeError('Comparison checkpoint belongs to another fixed sample')
        r=db.execute('SELECT count(*),coalesce(sum(requested),0),coalesce(sum(returned),0),coalesce(sum(flagged),0) FROM batches').fetchone()
    return dict(zip(('completed_batches','accounted_ids','returned_ids','metadata_flags'),map(int,r)))

def status(root):
    c=counts(root);total=TARGETS_AT_PREPARATION
    transfer=root/'inputs/TRANSFER.json'
    if transfer.is_file():
        t=io.load(transfer)
        if t['config_sha256']!=CONF:raise RuntimeError('Wrong transfer configuration')
        total=int(t['target_rows'])
    if total!=TARGETS_AT_PREPARATION or c['accounted_ids']>total:raise RuntimeError('Fixed target count changed')
    remaining=total-c['accounted_ids'];s=dict(c,target_ids=total,frame_rows=FRAME_ROWS,
        remaining_ids=remaining,baseline_games_per_second=BASELINE_RATE,
        baseline_remaining_hours=remaining/BASELINE_RATE/3600,
        metadata_export_present=(root/'finished/_DONE.json').is_file(),
        comparison_effects_estimated=False,abstract_gate_cleared=False)
    print(f"Run 2: {c['accounted_ids']:,} / {total:,} metadata targets accounted for; {remaining:,} remain.",flush=True)
    print(f"At the previously observed {BASELINE_RATE:.2f} games/s: {s['baseline_remaining_hours']:.1f} hours ({s['baseline_remaining_hours']/24:.1f} days) of remaining download, before retries/export.",flush=True)
    print('The fixed 1-in-32 frame contains 61,158,951 games. It is not a further 1-in-32 sample of that count.',flush=True)
    return s

def active_collectors(lines, self_pid=None):
    """Return only PID and script basename; do not log process arguments or tokens."""
    self_pid=os.getpid() if self_pid is None else self_pid
    out=[]
    for line in lines:
        try:
            pid,command=line.strip().split(None,1);pid=int(pid);args=shlex.split(command)
        except ValueError:continue
        if pid==self_pid:continue
        scripts=[Path(arg) for arg in args if arg.endswith('.py')]
        for p in scripts:
            low=str(p).lower();name=p.name.lower()
            related=any(word in low for word in ('lichess','chooser','receipt','kac_'))
            network_hint=any(word in low for word in ('download','metadata','collector','fetch','enrich','source_recovery'))
            known=name in ('enrich_home.py','fast_home.py','download_expansion.py')
            ours=name=='run_comparison.py' and 'download' in args
            # The original cohort extension is entirely local; its run.py is not an API job.
            if known or ours or (related and network_hint):out.append((pid,p.name));break
    return out

def wait_for_other_collectors(project):
    while True:
        text=subprocess.check_output(['ps','-axo','pid=,command='],text=True)
        active=active_collectors(text.splitlines())
        try:download.check_other_api_jobs(project);message=''
        except RuntimeError as exc:message=str(exc)
        requested=os.environ.get('IV_WAIT_PID','').strip()
        if requested:
            pid=int(requested)
            if pid==os.getpid():raise RuntimeError('IV_WAIT_PID refers to this downloader')
            try:os.kill(pid,0);active.append((pid,'explicit_wait_pid'))
            except ProcessLookupError:pass
        if not active and not message:return
        io.log('Run 2 waiting for an existing collector: '+(', '.join(f'{name} (PID {pid})' for pid,name in active) or message))
        time.sleep(45)

def existing_or_unpack(a):
    desktop=a.desktop.expanduser().resolve();desktop.mkdir(parents=True,exist_ok=True)
    root=checkpoint_root(desktop);inp=root/'inputs'
    if (inp/'_DONE.json').is_file():
        with io.heartbeat('Verifying existing fixed comparison inputs'):
            receipt=io.complete(inp,CONF)
        if not receipt:raise RuntimeError('Missing input receipt')
        transfer=io.load(inp/'TRANSFER.json')
        manifest=io.load(inp/'INPUT_MANIFEST.json')
        if transfer['config_sha256']!=CONF or manifest['config_sha256']!=CONF:raise RuntimeError('Wrong comparison inputs')
        for r in manifest['files']:io.checked(io.child(inp,r['path']),r['sha256'],r['bytes'])
        if int(transfer['target_rows'])!=TARGETS_AT_PREPARATION:raise RuntimeError('Target sample changed')
        return root,transfer
    archive=download.select_archive(desktop,a.input)
    root,conf,transfer=download.unpack_input(archive,desktop)
    if conf!=CONF or int(transfer['target_rows'])!=TARGETS_AT_PREPARATION:raise RuntimeError('Unexpected expansion input')
    return root,transfer

def execute(a):
    verify_package();desktop=a.desktop.expanduser().resolve();root=checkpoint_root(desktop)
    s=status(root)
    if a.mode=='status':return
    wait_for_other_collectors(a.project_root.expanduser().resolve())
    root,transfer=existing_or_unpack(a);target=root/'inputs/targets.parquet'
    with download.exclusive(root/'RUN.lock','This comparison downloader is already active'):
        if (root/'finished/_DONE.json').exists():
            with io.heartbeat('Verifying completed metadata export'):io.complete(root/'finished',CONF)
            io.log('Metadata export already complete; no API calls or re-download.');save_report(root,desktop,0,0);return
        global_root=Path.home()/'.cache/lichess_research_api'
        with download.exclusive(global_root/'one_request.lock','Another cooperating Lichess API job is active'):
            download.check_other_api_jobs(a.project_root)
            db=download.connect(root/'checkpoint.sqlite3',CONF,io.sha(target))
            started=time.monotonic();client=http.Client(global_root/'cooldown.json');new_ids=0
            try:
                with io.heartbeat('Checking resumable download database'):
                    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SQLite integrity check failed')
                before=counts(root);total=int(transfer['target_rows'])
                expansion.require_disk(root,2+(max(0,total-before['accounted_ids'])*450+total*150)/1024**3)
                # Binding is checked before skipping a completed batch. The original
                # raw-response checksums are checked again during the final export.
                saved={int(k):(h,int(n)) for k,h,n in db.execute('SELECT batch,request_sha,requested FROM batches')}
                io.log('Serial API requests, 300 IDs each; committed batches are reused. Backoff and Retry-After remain enforced.')
                for k,rows in enumerate(download.batches(target)):
                    ids=[r['game_id'] for r in rows]
                    if k in saved:
                        if saved[k]!=(download.binding(ids),len(rows)):raise RuntimeError('Saved batch identity changed')
                        if (k+1)%5000==0:io.log(f'Checked {k+1:,} saved target batches')
                        continue
                    found,missing,flags,reused=download.process_batch(db,k,rows,client)
                    if not reused:new_ids+=len(rows)
                    elapsed=time.monotonic()-started;rate=new_ids/max(elapsed,.001)
                    remaining=max(0,total-before['accounted_ids']-new_ids)
                    if (k+1)%10==0 or flags or remaining==0:
                        io.log(f'Newly accounted {new_ids:,}; remaining {remaining:,}; {rate:.2f} IDs/s; ETA {remaining/max(rate,.001)/3600:.1f} h')
                    if flags>max(3,len(found)*.05):raise RuntimeError('Over 5% metadata flags in a batch; saved evidence retained for inspection')
                with io.heartbeat('Verifying raw response evidence and writing final Parquet exports'):
                    download.export_saved(db,target,root/'finished',CONF)
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            finally:db.close()
        save_report(root,desktop,client.requests,time.monotonic()-started)

def save_report(root,desktop,requests,elapsed):
    report=root/'priority_report';report.mkdir(exist_ok=True)
    s=status(root);s.update(network_requests_this_invocation=requests,seconds_this_invocation=elapsed,
        metadata_summary=io.load(root/'finished/SUMMARY.json'),
        next_stage='global_identity_and_cache_conflict_reconciliation_then_frozen_expanded_entry_and_placebo',
        ordinary_primary_endings=['mate','resign','stalemate'],ordinary_draw_sensitivity=True,
        all_endings_retained_for_entry=True,
        additional_comparison='ordinary_games_of_recipients_in_frozen_IV_cohort_secondary_selection_sensitive',
        sample_size_stopping_rule='fixed_1_in_32_no_outcome_based_stopping',
        planning_equivalence_margin_pp=.015,planning_TOST_alpha=.05,planning_CI_level=.90,
        target_standard_error_pp=.005125742681998789,
        historical_exclusion_sensitivity_pp_per_SD=.020386,
        abstract_and_Contagious_gate='NOT_CLEARED_WITHOUT_EXPANDED_COMPARISON_ESTIMATES')
    io.js(report/'summary.json',s)
    (report/'READ_RESULTS.txt').write_text(
        'Run 2 metadata continuation\n\n'
        'The download is a prerequisite, not an estimated placebo. The original 1/1024 models were not rerun. '
        'The expanded frame still requires verified global IDs, source/status reconciliation, author-clean histories, '
        'pool and nonadjacency eligibility, and the frozen entry/placebo estimation. No expanded-frame adapter was supplied in the original download package.\n\n'
        'The extra IV-recipient restriction is secondary: later cohort membership may select on future behavior. '
        'Keep the prospective all-frame entry test. Preserve all terminal endings for entry, and the narrow ordinary placebo (mate/resign/stalemate) separately from the draw sensitivity.\n\n'
        'Report the placebo estimate and 95% CI beside the 0.020386 pp per SD exclusion-sensitivity number. '
        'The prior precision plan uses a 90% CI and a ±0.015 pp equivalence margin; the ~0.005 pp target is a standard error, not that margin. '
        'A small point estimate alone does not establish exclusion. The handoff’s ±0.005 point-estimate rule may be reported descriptively, without replacing interval-based assessment.\n\n'
        'Until the expanded estimates are available, retain the main-text IV and v2 limitation: the existing placebo is centered near zero and its interval includes a direct effect large enough to matter. Do not clear the abstract or title gate from this download report.\n')
    out=pack_report(report,desktop,'IV_RUN2_DOWNLOAD_STATUS_'+CONF[:12])
    io.log('Metadata continuation complete; expanded comparison estimates have not yet been computed.')
    print('RETURN THIS SMALL AGGREGATE REPORT: '+out,flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['status','download'])
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--project-root',type=Path,default=BASE);p.add_argument('--input',type=Path)
    a=p.parse_args();os.umask(0o077)
    try:execute(a)
    except KeyboardInterrupt:io.log('Interrupted. Every completed request remains checkpointed.');raise SystemExit(130)
    except Exception as exc:io.log('STOPPED: '+str(exc));raise SystemExit(2)
if __name__=='__main__':main()
