"""Execution-only repair for the authenticated R9 4028bf3e1857 checkpoint.

All scientific producers and their manifests remain byte-for-byte frozen.
Only ENV scheduler reservations, DuckDB limits and progress rendering change.
"""
from pathlib import Path
import argparse
import datetime
import shutil
import sys
import uuid

PACKAGE = Path(__file__).resolve().parents[1]
FROZEN = PACKAGE / 'frozen_R9'
sys.path.insert(0, str(FROZEN / 'code'))
import r9_common as c9
import r9_inputs as inputs
import r9_report as report
import run_r9
import duckdb

r, u, runtime = c9.r, c9.u, c9.runtime
VERSION = '1.0.1'
EXPECTED_CONF = '4028bf3e185783a17679ed3d5fee5b376028f37141e1e5ce09b93b068a6a6e0b'
FROZEN_MANIFEST_SHA = '450837fec023b0b4157345b640d9997b2779da71daa7f003d7562d17867e8874'
NORMAL_LIMIT_GB = 3.0  # DuckDB uses decimal GB.
NORMAL_RESERVATION_GIB = 4.5  # Includes Python, Arrow, allocator/headroom.
RETRY_LIMIT_GB = 8.0
RETRY_RESERVATION_GIB = 9.0

ORIGINAL_CONN = r.io.conn
ORIGINAL_MAPPED = runtime.mapped
ORIGINAL_ENV_JOB = r.env_rates.chronology_job
ORIGINAL_REPLAY = inputs.replay_baseline
ORIGINAL_EXPORT = report.export
ORIGINAL_HEARTBEAT = run_r9.heartbeat


def verify_package():
    for line in (PACKAGE / 'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = (PACKAGE / name).resolve()
        u.require(path.is_relative_to(PACKAGE), 'Unsafe repair package member')
        r.io.checked(path, digest)
    r.io.checked(FROZEN / 'PACKAGE_MANIFEST.sha256', FROZEN_MANIFEST_SHA)
    c9.verify_package()


def quiet_conn(*args, **kwargs):
    connection = ORIGINAL_CONN(*args, **kwargs)
    connection.execute('SET enable_progress_bar=false')
    return connection


def environment_attempt(job):
    """Top-level callable so spawn workers receive the repair on macOS too."""
    r.io.conn = quiet_conn
    resumed = (Path(job['output']) / '_DONE.json').exists()
    try:
        value = ORIGINAL_ENV_JOB(job)
    except duckdb.OutOfMemoryException as error:
        # OOM is not success. The parent waits for this entire pool to exit,
        # then retries only these unfinished parts with a larger serial limit.
        u.log('ENV part ' + Path(job['output']).name + ' reached its ' +
              str(job['memory']) + ' GB limit; queued for a serial retry')
        return dict(ok=False, error_type=type(error).__name__, message=str(error))
    return dict(ok=True, value=value, reused_checkpoint=resumed)


def map_environment(jobs, workers, memory, label, forecast_minutes,
                    tail_minutes=0, callback=None, *, mapper=None, audit=None):
    mapper = ORIGINAL_MAPPED if mapper is None else mapper
    audit = {} if audit is None else audit
    first = [dict(j, memory=NORMAL_LIMIT_GB, memory_gb=NORMAL_RESERVATION_GIB)
             for j in jobs]
    slots = min(2, workers)
    audit.update(tasks=len(jobs), normal_worker_limit=slots,
                 normal_duckdb_limit_decimal_GB=NORMAL_LIMIT_GB,
                 normal_reservation_GiB=NORMAL_RESERVATION_GIB,
                 retry_worker_limit=1, retry_duckdb_limit_decimal_GB=RETRY_LIMIT_GB,
                 retry_reservation_GiB=RETRY_RESERVATION_GIB,
                 total_planning_budget_GiB=memory,
                 estimated_reservations_not_an_OS_memory_cap=True,
                 original_ENV_SQL_unchanged=True,
                 progress_bars_disabled=True)
    u.log('ENV memory repair: up to 2 workers, 3 GB DuckDB each; '
          '4.5 GiB reserved per worker. OOM parts retry alone at 8 GB.')
    # Callback fires only when all requested outputs have succeeded, below.
    results = mapper(environment_attempt, first, slots, memory,
                     label + ' [3 GB / up to 2 workers]', forecast_minutes,
                     tail_minutes)
    failed = [i for i, value in enumerate(results) if not value['ok']]
    audit['serial_retry_tasks'] = len(failed)
    audit['existing_parts_reused'] = sum(v.get('reused_checkpoint', False) for v in results)
    if failed:
        # mapped() has left its executor context: no other ENV workers remain.
        retries = [dict(first[i], memory=RETRY_LIMIT_GB,
                        memory_gb=RETRY_RESERVATION_GIB) for i in failed]
        retried = mapper(environment_attempt, retries, 1, memory,
                         label + ' [8 GB serial memory retries]',
                         max(5, forecast_minutes * len(failed) / max(1, len(jobs))),
                         tail_minutes)
        for i, value in zip(failed, retried):
            if not value['ok']:
                audit['status'] = 'STOPPED_AT_SERIAL_MEMORY_LIMIT'
                raise RuntimeError('ENV part ' + Path(jobs[i]['output']).name +
                                   ' still exceeds the 8 GB serial DuckDB limit. '
                                   'Completed stages remain reusable. Return this log.\n' +
                                   value['message'])
            results[i] = value
    audit['completed_tasks'] = len(results)
    audit['status'] = 'COMPLETE'
    if callback:
        callback(len(results), len(jobs))
    return [v['value'] for v in results]


def resume_inputs(project):
    root = project / 'derived/replication/r9_certified_leave_pair_out_v100_PRIVATE' / EXPECTED_CONF[:12]
    config = u.load(root / 'config.json')
    u.require(r.io.cfgsha(config) == EXPECTED_CONF, 'Expected R9 configuration missing or changed')
    u.require(config['package_sha256'] == FROZEN_MANIFEST_SHA,
              'R9 scientific package differs from the reviewed run')
    u.require(config['version'] == '1.0.0' and config['baseline'] == c9.BASE_CONF
              and config['definition'] == c9.DEFINITION and config['learning'] is True,
              'Frozen R9 definitions changed')
    saved = u.load(root / 'INPUTS_PRIVATE.json')
    summary = u.load(root / 'report/summary.json')
    u.require(summary['configuration_sha256'] == EXPECTED_CONF,
              'Saved report belongs to another configuration')
    u.require(summary.get('baseline_scores_reproduced') is True and
              len(summary.get('baseline_models', [])) == 14 and
              all(x['passed'] for x in summary['baseline_models']),
              'The completed baseline/score gate is missing')
    phase_root = u.relocate(saved['comparison_root'], project).resolve()
    baseline = u.relocate(saved['baseline'], project).resolve()
    u.require(phase_root.is_relative_to(project) and baseline.is_relative_to(project),
              'Saved comparison/baseline path is outside this project')
    # Pin the original startup snapshot. Never switch to a later Phase 100
    # while resuming the already certified Phase 75 donor scores.
    return root, config, summary, phase_root, baseline


def install_repair(root, desktop, execution):
    """Hooks do not change a producer, statistical equation or stage config."""
    environment_audit = execution.setdefault('environment_scheduler', {})
    initialized = False
    audit_dir = None

    def save_audit():
        if audit_dir is not None:
            r.io.js(audit_dir / 'execution.json', execution)

    def replay(*args, **kwargs):
        nonlocal initialized, audit_dir
        # The original runner now holds RUN.lock. Snapshot only aggregate
        # reports before its normal resumable export replaces report files.
        stage_root = Path(args[3] if len(args) > 3 else kwargs['root'])
        conf = args[4] if len(args) > 4 else kwargs['conf']
        u.require(stage_root.parent.resolve() == root.resolve() and conf == EXPECTED_CONF,
                  'Repair attempted to enter another configuration')
        if not initialized:
            tag = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
            audit_dir = root / 'runtime_repairs' / (VERSION + '_' + tag)
            audit_dir.mkdir(parents=True)
            shutil.copytree(root / 'report', audit_dir / 'report_before_resume')
            for source in sorted(desktop.glob('R9_CERTIFIED_REPORT_' + EXPECTED_CONF[:12] + '_*.zip*')):
                if source.is_file():
                    shutil.copy2(source, audit_dir / source.name)
            execution['started_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            execution['prior_aggregate_report_preserved'] = True
            save_audit()
            initialized = True
        return ORIGINAL_REPLAY(*args, **kwargs)

    def mapped(fn, jobs, workers, memory, label, forecast_minutes, tail_minutes=0, callback=None):
        if fn is ORIGINAL_ENV_JOB:
            try:
                return map_environment(jobs, workers, memory, label, forecast_minutes,
                                       tail_minutes, callback, audit=environment_audit)
            finally:
                save_audit()
        return ORIGINAL_MAPPED(fn, jobs, workers, memory, label, forecast_minutes,
                               tail_minutes, callback)

    def export(root_arg, desktop_arg, conf, progress, status, extra, plan=()):
        u.require(Path(root_arg).resolve() == root.resolve() and conf == EXPECTED_CONF,
                  'Report configuration differs from the repair target')
        save_audit()
        return ORIGINAL_EXPORT(root_arg, desktop_arg, conf, progress, status,
                               dict(extra, execution_repair=execution), plan)

    def heartbeat(label, next_minutes, remaining_minutes):
        if label.startswith('Reuse frozen ENV rates'):
            # A lightweight outer heartbeat for request/merge phases. During
            # the scan, the scheduler supplies measured throughput ETAs too.
            return ORIGINAL_HEARTBEAT(label, 110, 180)
        return ORIGINAL_HEARTBEAT(label, next_minutes, remaining_minutes)

    inputs.replay_baseline = replay
    runtime.mapped = mapped
    report.export = export
    run_r9.heartbeat = heartbeat
    r.io.conn = quiet_conn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--desktop', type=Path, default=Path.home() / 'Desktop/Lichess_Desktop')
    parser.add_argument('--workers', type=int, default=10)
    parser.add_argument('--memory-gb', type=float, default=11)
    a = parser.parse_args()
    u.require(1 <= a.workers <= 10 and 10.5 <= a.memory_gb <= 11,
              'Use 1–10 workers, 10.5–11 GiB')
    verify_package()
    r.threads_one()
    u.no_network()
    project, desktop = a.project_root.expanduser().resolve(), a.desktop.expanduser().resolve()
    root, config, summary, phase_root, baseline = resume_inputs(project)
    if summary.get('progress_percent') == 100:
        u.log('This R9 run already reached 100%; nothing was changed. '
              'Use the existing 100% report and SHA256 sidecar.')
        return
    execution = dict(repair_version=VERSION,
                     repair_manifest_sha256=u.sha(PACKAGE / 'PACKAGE_MANIFEST.sha256'),
                     scientific_configuration_sha256=EXPECTED_CONF,
                     scientific_package_manifest_sha256=FROZEN_MANIFEST_SHA,
                     original_scientific_sources_unchanged=True,
                     completed_stages_verified_and_reused=True,
                     comparison_phase_pinned_to_original_startup=config['comparison_phase']['phase_percent'],
                     reason='Observed DuckDB OutOfMemoryException at 953.6 MiB limit in ENV chronology_job',
                     old_failed_partial_directories_retained=True)
    install_repair(root, desktop, execution)
    u.log('Resuming certified configuration ' + EXPECTED_CONF[:12] +
          '; completed stages will be verified and reused. ETA roughly 1.5–3 hours, '
          'possibly longer if serial retries or drive contention dominate.')
    sys.argv = [str(FROZEN / 'code/run_r9.py'), '--project-root', str(project),
                '--desktop', str(desktop), '--baseline-root', str(baseline),
                '--comparison-root', str(phase_root), '--workers', str(a.workers),
                '--memory-gb', str(a.memory_gb)]
    run_r9.main()


if __name__ == '__main__':
    main()
