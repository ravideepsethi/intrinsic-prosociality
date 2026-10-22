#!/usr/bin/env python3
"""Update color predictions from reviewed fixed fits and the pre-policy cache."""
import os
for _name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_name] = '1'
import argparse, fcntl, platform, shutil, threading, traceback, zipfile
from datetime import datetime, timezone
from common import *
from runner import execute


def verify_package():
    manifest = ROOT / 'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        expected, name = line.split('  ', 1)
        if sha(ROOT / name) != expected:
            raise RuntimeError('Package checksum mismatch: ' + name)
    return sha(manifest)


def archive(public, project, desktop):
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = project / 'output/color_rd110_predictions_v100' / ('COLOR_RD110_PREDICTIONS_RESULT_' + run_id)
    shutil.copytree(public, report)
    desktop.mkdir(parents=True, exist_ok=True)
    out = desktop / (report.name + '.zip')
    partial = out.with_suffix('.partial.zip')
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():
                z.write(p, report.name + '/' + p.relative_to(report).as_posix())
    os.replace(partial, out)
    text(Path(str(out) + '.sha256'), sha(out) + '  ' + out.name + '\n')
    log('RESULT_TO_UPLOAD ' + str(out))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--desktop', type=Path, default=Path.home() / 'Desktop/Lichess_Desktop')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--memory-gb', type=float, default=3.)
    a = parser.parse_args()
    if not 1 <= a.threads <= 10 or not 1 <= a.memory_gb <= 12:
        parser.error('Use 1–10 preparation threads and 1–12 GB DuckDB memory')
    project = a.project_root.expanduser().resolve()
    if not project.is_dir():
        parser.error('Project directory not found')
    code = verify_package()
    reference = read(ROOT / 'authority/reference.json')
    source = project / 'derived/replication/mechanism_separation_v100_PRIVATE'
    work = project / 'derived/replication/color_rd110_predictions_v100_PRIVATE'
    work.mkdir(parents=True, exist_ok=True)
    lock = open(work / 'run.lock', 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('This prediction update is already running')
    source_lock = None
    if (source / 'run.lock').exists():
        source_lock = open(source / 'run.lock', 'r')
        try:
            fcntl.flock(source_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('The source mechanism cache is being written; let that run finish')
    start = time.monotonic()
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(45):
            log(f'Color prediction update working; elapsed {(time.monotonic() - start) / 60:.1f} minutes')
    threading.Thread(target=heartbeat, daemon=True).start()
    public = work / 'public_results'
    public.mkdir(exist_ok=True)
    status = dict(status='RUNNING', version='1.0.0', post_policy_outcomes_read=False)
    error = None
    try:
        status.update(execute(source, work, public, reference, code,
                              threads=a.threads, memory_mb=int(a.memory_gb * 1024)))
    except Exception as exc:
        error = exc
        status.update(status='PARTIAL_OUTPUT_DO_NOT_INTERPRET', error=str(exc), traceback=traceback.format_exc())
        log('STOPPED: ' + str(exc))
    finally:
        stop.set()
        status['elapsed_seconds'] = time.monotonic() - start
        write(public / 'SUMMARY.json', status)
        write(public / 'ENVIRONMENT.json', dict(python=platform.python_version(), platform=platform.platform(),
            numpy=np.__version__, pandas=pd.__version__, pyarrow=pa.__version__, duckdb=duckdb.__version__, package_sha256=code))
        for name in ('METHODS.md', 'FROZEN_PLAN.json', 'POST_POLICY_DEPENDENCIES.md'):
            shutil.copy2(ROOT / name, public / name)
        text(public / 'READ_ME_FIRST.md', '# Color prediction update\n\nStatus: **' + status['status'] + '**.\n\n'
            'Read PRIMARY_READOUT.csv, same_sample_old_vs_corrected.csv, planning_MDE.csv, and pairwise_power.csv. '
            'These are transported predictions and conditional planning calculations using only November 2023–October 2025 rows. '
            'No post-policy behavioral estimate or causal rejection is produced.\n\n'
            'All candidate coefficients are frozen reviewed fits. Baseline grant probabilities require an additional pre-policy calibration model. '
            'Baseline and training-fold alternatives are sensitivities, not confidence intervals. Parameter uncertainty is not propagated. '
            'Do not turn a planning screen into a GO decision, mechanism share, or preference bound. '
            'See METHODS.md and POST_POLICY_DEPENDENCIES.md. If status is PARTIAL_OUTPUT_DO_NOT_INTERPRET, send the ZIP for diagnosis.\n')
        archive(public, project, a.desktop.expanduser().resolve())
        lock.close()
        if source_lock is not None:
            source_lock.close()
    if error:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
