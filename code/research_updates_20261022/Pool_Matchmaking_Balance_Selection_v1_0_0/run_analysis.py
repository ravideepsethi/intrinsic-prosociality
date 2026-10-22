#!/usr/bin/env python3
"""Run the existing-frame matchmaking balance and selection diagnostic offline."""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
import platform
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import analysis as a

PKG = Path(__file__).resolve().parent
AUTH = {
    'config_sha256': 'ccbc4331487512b8b7ce41b620a8699ed056f6961a25b49c65ad52c2c0da013c',
    'comparison_sha256': '8bc92d15b9a63e4cc1191ab8342aedd918a36bd341d9a8ddc427e93bb9f156ae',
    'comparison_bytes': 173_517_733, 'comparison_rows': 1_661_563,
    'eligible_main_rows': 1_527_795,
    'relative_root': 'derived/replication/chooser_iv_main_rebuild_v100_PRIVATE/ccbc43314875',
}
NUMERIC_COLUMNS = ('sample_row', 'archive_start_ms', 'month_code', 'recipient_id', 'opponent_id',
    'recipient_rating', 'opponent_rating', 'tc_base_s', 'tc_inc_s', 'own_fair90', 'own_kind90',
    'own_fair_n', 'own_kind_n', 'own_history_complete', 'active_timeout', 'passive_outoftime',
    'eligible_main', 'recipient_disconnect_main', 'recipient_chooser_main', 'recipient_fair_arm_main',
    'actual_iv_exposure')
STRING_COLUMNS = ('game_id', 'status', 'previous_classification_status', 'recipient_identity_state', 'opponent_identity_state')


def clean(x):
    if isinstance(x, dict): return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [clean(v) for v in x]
    if isinstance(x, np.ndarray): return clean(x.tolist())
    if isinstance(x, np.generic): return clean(x.item())
    if isinstance(x, float) and not np.isfinite(x): return None
    return x


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def canonical(x):
    return hashlib.sha256(json.dumps(clean(x), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.partial_' + uuid.uuid4().hex)
    tmp.write_text(json.dumps(clean(value), indent=2, sort_keys=True, allow_nan=False) + '\n')
    os.replace(tmp, path)


def log(message):
    print(dt.datetime.now(dt.timezone.utc).strftime('[%Y-%m-%d %H:%M:%SZ] ') + message, flush=True)


@contextlib.contextmanager
def heartbeat(label):
    stop = threading.Event()
    def beat():
        while not stop.wait(45): log(label + ' — working')
    worker = threading.Thread(target=beat, daemon=True); worker.start()
    try: yield
    finally: stop.set(); worker.join()


def verify_sources():
    bindings = json.loads((PKG / 'evidence/SOURCE_BINDINGS.json').read_text())
    for name, expected in bindings['files'].items():
        folder = 'source' if name in ('comparison_core.py', 'iv_numerics.py', 'preliminary_core.py') else 'evidence'
        if digest(PKG / folder / name) != expected: raise RuntimeError('Source binding mismatch: ' + name)


def verify_input(project, authority=AUTH):
    root = project / authority['relative_root']
    conf_path, done_path = root / 'config.json', root / 'analysis/_DONE.json'
    data_path = root / 'analysis/comparison.parquet'
    for p in (conf_path, done_path, data_path):
        if not p.is_file(): raise RuntimeError('Required comparison checkpoint is missing: ' + str(p))
    conf = json.loads(conf_path.read_text()); done = json.loads(done_path.read_text())
    if canonical(conf) != authority['config_sha256'] or done.get('config_sha256') != authority['config_sha256']:
        raise RuntimeError('Comparison configuration does not match the returned authority')
    records = [x for x in done.get('files', []) if x.get('path') == 'comparison.parquet']
    if len(records) != 1 or records[0].get('sha256') != authority['comparison_sha256'] or int(records[0].get('bytes', -1)) != authority['comparison_bytes']:
        raise RuntimeError('Comparison receipt does not match the returned authority')
    before = data_path.stat(); sig = [before.st_size, before.st_mtime_ns]
    if before.st_size != authority['comparison_bytes']: raise RuntimeError('Comparison byte count changed')
    log('Authenticating the 174 MB comparison frame')
    if digest(data_path) != authority['comparison_sha256']: raise RuntimeError('Comparison full SHA-256 mismatch')
    after = data_path.stat()
    if [after.st_size, after.st_mtime_ns] != sig: raise RuntimeError('Comparison file changed during authentication')
    return data_path, dict(comparison_sha256=authority['comparison_sha256'], bytes=before.st_size,
        signature=sig, source_config_sha256=authority['config_sha256'], comparison_fully_hashed=True,
        main_panel_or_chronology_reread=False)


def load_frame(path, expected_rows=AUTH['comparison_rows'], expected_nonadj=AUTH['eligible_main_rows']):
    db = duckdb.connect(':memory:'); db.execute('SET threads=1'); db.execute("SET memory_limit='512MB'")
    try:
        fields = ','.join('"' + x + '"' for x in NUMERIC_COLUMNS + STRING_COLUMNS)
        data = db.execute('SELECT ' + fields + ' FROM read_parquet(?, hive_partitioning=false)', [str(path)]).fetchnumpy()
    finally: db.close()
    for name, value in data.items():
        if np.ma.isMaskedArray(value) and np.any(np.ma.getmaskarray(value)):
            raise RuntimeError('Missing values in required field: ' + name)
        data[name] = np.asarray(value)
    n = len(data['sample_row'])
    if n != expected_rows or len(np.unique(data['sample_row'])) != n or len(np.unique(data['game_id'])) != n:
        raise RuntimeError('Comparison row count or game/sample-key uniqueness failed')
    for name in NUMERIC_COLUMNS:
        if not np.isfinite(data[name]).all(): raise RuntimeError('Nonfinite values in: ' + name)
    if np.any(data['recipient_id'] == data['opponent_id']): raise RuntimeError('Self-pair encountered')
    if np.any((data['recipient_rating'] <= 0) | (data['opponent_rating'] <= 0)):
        raise RuntimeError('Invalid recorded rating')
    if np.any((data['tc_base_s'] <= 0) | (data['tc_inc_s'] < 0)):
        raise RuntimeError('Invalid exact time control')
    if not np.array_equal(data['eligible_main'], data['previous_classification_status'] == a.NONADJ):
        raise RuntimeError('Eligibility and predecessor classification disagree')
    if int(data['eligible_main'].sum()) != expected_nonadj: raise RuntimeError('New-screen comparison count changed')
    if not np.array_equal(data['active_timeout'], data['status'] == 'timeout') or not np.array_equal(data['passive_outoftime'], data['status'] == 'outoftime'):
        raise RuntimeError('Recorded ending flags and API status disagree')
    if np.any(data['recipient_disconnect_main'] & data['recipient_chooser_main']):
        raise RuntimeError('Main-sample role flags overlap')
    for name in ('recipient_disconnect_main', 'recipient_chooser_main', 'recipient_fair_arm_main', 'actual_iv_exposure'):
        if np.any(data[name] & ~(data['eligible_main'] & data['active_timeout'])):
            raise RuntimeError('Main-role or exposure flag outside its recorded active/eligible subset')
    if np.any((data['own_kind90'] < 0) | (data['own_fair90'] < data['own_kind90'])):
        raise RuntimeError('Invalid historical kindness numerator/denominator')
    start = int(dt.datetime(2023, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    end = int(dt.datetime(2025, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    if np.any((data['archive_start_ms'] < start) | (data['archive_start_ms'] >= end)):
        raise RuntimeError('Comparison start time outside the main observation window')
    if not np.array_equal(data['own_history_complete'], data['archive_start_ms'] - 97 * a.DAY >= start):
        raise RuntimeError('Prior-history completeness flag does not follow the documented time rule')
    qa = dict(rows=n, eligible_main=int(data['eligible_main'].sum()),
        own_history_complete=int(data['own_history_complete'].sum()),
        nonadj_history_complete=int((data['eligible_main'] & data['own_history_complete']).sum()),
        own_fair_duplicate_field_mismatches=int(np.sum(data['own_fair90'] != data['own_fair_n'])),
        own_kind_duplicate_field_mismatches=int(np.sum(data['own_kind90'] != data['own_kind_n'])),
        # This is timing coverage, not a count of all pool games in those months.
        month_counts={str(int(k)): int(v) for k, v in zip(*np.unique(data['month_code'], return_counts=True))},
        status_counts={str(k): int(v) for k, v in zip(*np.unique(data['status'], return_counts=True))},
        focal_identity_states={str(k): int(v) for k, v in zip(*np.unique(data['recipient_identity_state'], return_counts=True))},
        first_start_UTC=dt.datetime.fromtimestamp(int(data['archive_start_ms'].min()) / 1000, dt.timezone.utc).isoformat(),
        last_start_UTC=dt.datetime.fromtimestamp(int(data['archive_start_ms'].max()) / 1000, dt.timezone.utc).isoformat())
    # Account and game values never enter report payloads.
    for name in STRING_COLUMNS: data.pop(name)
    return a.derived(data), qa


def flatten(results):
    rows = []
    for result in results:
        spec = result['specification']['name']
        for outcome in result.get('estimates', []):
            for contrast in outcome['contrasts']:
                rows.append(dict(specification=spec, outcome=outcome['outcome'], family=outcome['family'],
                    n=result['n'], rows_with_gap_variation=result.get('rows_with_residual_gap_variation'),
                    mean=outcome['mean'], sd=outcome['sd'], **contrast))
    return rows


def csv_bytes(rows):
    if not rows: return b''
    fields = sorted({k for r in rows for k in r})
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fields)
    writer.writeheader(); writer.writerows(clean(rows))
    return stream.getvalue().encode()


def report_payload(summary, qa, support, raw, results):
    def j(x): return (json.dumps(clean(x), indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    return {
        'SUMMARY.json': j(summary), 'INPUT_QA.json': j(qa), 'DESIGN.json': j(a.CONTRACT),
        'MODEL_RESULTS.json': j(results), 'ESTIMATES.csv': csv_bytes(flatten(results)),
        'LOCAL_CELL_SUPPORT.csv': csv_bytes(support), 'RAW_GAP_TABLE.csv': csv_bytes(raw),
        'REPORT.md': (
            '# Matchmaking balance and selection diagnostic\n\n'
            'This is a post-hoc diagnostic on the frozen, randomly oriented pool-game comparison frame. '
            'The primary is local5_primary, including exact clock, five-minute start bin and 50-point focal-rating bin. '
            'Inspect its retained variation and precision before interpreting it. Coarser and within-focal models '
            'have separate support and cannot silently replace it.\n\n'
            'recipient means the randomly oriented focal player here; it does not mean the eventual draw recipient. '
            'The primary comparison is restricted to observed nonadjacency and complete lagged baseline history. '
            'The all_dates_nonadj_selection companion retains earlier dates; pool_parent_context retains the parent pool frame. '
            'active_given_candidate is a separately conditioned, post-assignment diagnostic.\n\n'
            'History is the 90-day window ending seven days before focal start. Prior rates are undefined without '
            'prior opportunities; floor1 and floor5 are separate selected-history companions. Main balance outcomes '
            'retain zero prior opportunities as an observed baseline category when calendar coverage is complete.\n\n'
            'Linear slopes are per +100 opponent rating points holding focal rating and the specified environment fixed. '
            'Selection results use percentage points; standardized balance uses outcome SD. All p values are exploratory. '
            'The fixed 0.05-SD equivalence diagnostic is a descriptive tolerance, not proof of random assignment.\n\n'
            'active_timeout/passive_outoftime are recorded status categories. Main role flags additionally inherit '
            'the certified opportunity screens. The residual role category is retained. These are not counts of '
            'deliberate waits. No current-game kind-grant incidence or relative-strength kindness surface is estimated.\n\n'
            'Queue waits, conduct scores, blocking, historical preferences, pre-game RD and recent all-game volume '
            'are absent from this comparison schema. Game starts do not identify queue entry. Source hashes '
            'authenticate the comparison used here; the full chronology and main panel were not reread. '
            'Null balance or selection tests do not establish unconfounded assignment or a causal response '
            'conditional on a realized board state. No failures or nonpositive covariances were repaired.\n'
        ).encode(),
    }


def export_report(desktop, payload, run_id, partial=False):
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    stem = 'POOL_MATCHMAKING_BALANCE_SELECTION_' + ('PARTIAL_' if partial else 'RESULTS_') + stamp + '_' + run_id
    dest = desktop / (stem + '.zip')
    hashes = ''.join(hashlib.sha256(value).hexdigest() + '  ' + name + '\n' for name, value in sorted(payload.items()))
    with zipfile.ZipFile(dest, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, value in payload.items(): z.writestr(name, value)
        z.writestr('REPORT_MANIFEST.sha256', hashes)
    Path(str(dest) + '.sha256').write_text(digest(dest) + '  ' + dest.name + '\n')
    log('UPLOAD ' + str(dest)); log('UPLOAD ' + str(dest) + '.sha256')
    return dest


def checkpoint(path, config_sha, function):
    if path.exists():
        old = json.loads(path.read_text())
        if old['config_sha256'] != config_sha or canonical(old['result']) != old['result_sha256']:
            raise RuntimeError('Analysis checkpoint integrity failure: ' + path.name)
        return old['result'], True
    result = function()
    write_json(path, dict(config_sha256=config_sha, result_sha256=canonical(result), result=result))
    return result, False


def run(args):
    if not args.project_root.is_dir(): raise RuntimeError('Project drive/root is unavailable')
    if not args.desktop.is_dir(): raise RuntimeError('Desktop output directory is unavailable')
    verify_sources()
    config = dict(contract=a.CONTRACT, package_manifest_sha256=digest(PKG / 'PACKAGE_MANIFEST.sha256'),
        authority=AUTH, numpy=np.__version__, duckdb=duckdb.__version__,
        numerical_threads={key: os.environ.get(key) for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS')})
    config_sha = canonical(config)
    root = args.project_root / 'derived/replication/pool_matchmaking_balance_selection_v100_PRIVATE' / config_sha[:12]
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / '.run.lock').open('a+')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This matchmaking diagnostic is already running')
    with lock:
        write_json(root / 'config.json', config)
        path, authenticated = verify_input(args.project_root)
        start = time.monotonic(); results = []; support = []; raw = []; qa = {}
        try:
            log('Loading the authenticated comparison columns')
            d, qa = load_frame(path)
            with heartbeat('Measuring local-cell support'):
                support, reused = checkpoint(root / 'local_support.json', config_sha, lambda: a.support_inventory(d))
            raw, reused = checkpoint(root / 'raw_gap_table.json', config_sha, lambda: a.raw_tables(d))
            for spec in a.SPECS:
                log('Estimating/resuming ' + spec['name'])
                def estimate():
                    begin = time.monotonic()
                    try:
                        with heartbeat(spec['name']): result = a.fit_spec(d, spec)
                    except RuntimeError as error:
                        # Numerical failure is retained; changing the model is not a retry policy.
                        result = dict(specification=spec, supported=False, reason=str(error), n=int(a.frame_mask(d, spec).sum()))
                    result['elapsed_seconds'] = time.monotonic() - begin
                    return result
                result, reused = checkpoint(root / 'models' / (spec['name'] + '.json'), config_sha, estimate)
                results.append(result)
                log(spec['name'] + (': reused' if reused else ': complete') + (' (unsupported; see report)' if not result['supported'] else ''))
            after = path.stat()
            if [after.st_size, after.st_mtime_ns] != authenticated['signature']:
                raise RuntimeError('Comparison changed while estimating; results withheld')
            unsupported = [r['specification']['name'] for r in results if not r['supported']]
            summary = dict(status='MATCHMAKING_DIAGNOSTIC_COMPLETE' + ('_WITH_UNSUPPORTED_MODELS' if unsupported else ''),
                configuration_sha256=config_sha, input=authenticated, unsupported_models=unsupported,
                models_attempted=len(results), primary_model='local5_primary',
                unsupported_outcome_covariances={x['specification']['name']:x.get('unsupported_outcome_covariances', []) for x in results},
                invocation_elapsed_seconds=time.monotonic() - start, network_requests=0, stockfish_searches=0,
                platform=platform.platform(), input_unchanged_by_signature=True, private_rows_transferred=False,
                causal_assignment_certified=False)
            payload = report_payload(summary, qa, support, raw, results)
            write_json(root / 'SUMMARY.json', summary)
            export_report(args.desktop, payload, config_sha[:12])
        except BaseException as error:
            summary = dict(status='STOPPED_PARTIAL', configuration_sha256=config_sha,
                error_type=type(error).__name__, error=str(error), completed_models=len(results),
                invocation_elapsed_seconds=time.monotonic() - start, input=authenticated)
            export_report(args.desktop, report_payload(summary, qa, support, raw, results), config_sha[:12], True)
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root', type=Path, default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop', type=Path, default=Path.home() / 'Desktop/Lichess_Desktop')
    run(p.parse_args())


if __name__ == '__main__': main()
