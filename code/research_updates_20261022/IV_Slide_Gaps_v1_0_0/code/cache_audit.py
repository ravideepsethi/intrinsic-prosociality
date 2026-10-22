"""Bounded, read-only cache discovery. No profile values leave this audit."""
from __future__ import annotations
from common import *
import gzip, re, time, shlex, subprocess
import io as stdio

GEO = {'country', 'flag', 'country_code', 'countrycode', 'profile_country', 'profile_flag'}
JSON_KEYS = {'json', 'raw_json', 'profile_json', 'response', 'body', 'payload', 'data',
             'profile', 'response_json', 'api_json', 'raw', 'json_response', 'raw_response'}

def geo_paths(field_type, prefix):
    found = []
    if prefix.rsplit('.', 1)[-1].lower() in GEO:
        found.append(prefix)
    if pa.types.is_struct(field_type):
        for field in field_type:
            found.extend(geo_paths(field.type, prefix+'.'+field.name))
    elif pa.types.is_list(field_type) or pa.types.is_large_list(field_type):
        found.extend(geo_paths(field_type.value_type, prefix+'[]'))
    return found

def inspect_object(obj, present, nonempty, parent='', depth=0):
    """Only retain canonical geography field names and counts, never values."""
    if depth > 8:
        return
    if isinstance(obj, str) and parent.lower() in JSON_KEYS:
        try:
            obj = json.loads(obj)
        except (ValueError, TypeError):
            return
    if isinstance(obj, list):
        for value in obj[:500]:
            inspect_object(value, present, nonempty, parent, depth+1)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            leaf = str(key).lower().removeprefix('profile.')
            if leaf in GEO:
                canonical = ('profile.' if parent.lower() == 'profile' or str(key).lower().startswith('profile.') else '') + leaf
                present[canonical] = present.get(canonical, 0)+1
                if value is not None and value != '' and value != [] and value != {}:
                    nonempty[canonical] = nonempty.get(canonical, 0)+1
            if isinstance(value, (dict, list)) or str(key).lower() in JSON_KEYS:
                inspect_object(value, present, nonempty, str(key), depth+1)

def inspect_file(path, label):
    result = dict(file_label=label, suffix=''.join(path.suffixes[-2:]), status='INSPECTED',
                  schema_geo_fields=[], sampled_geo_field_occurrences={}, sampled_nonempty_geo_occurrences={},
                  rows_sampled=0, full_file_scanned=False)
    present, nonempty = {}, {}
    suffix = path.suffix.lower()
    if suffix == '.parquet':
        pf = pq.ParquetFile(path)
        result['file_rows'] = pf.metadata.num_rows
        result['identity_field_names'] = [s for s in pf.schema_arrow.names if s.lower() in
                                          ('id', 'user_id', 'userid', 'username', 'user', 'account_id', 'account', 'name')]
        result['snapshot_time_field_names'] = [s for s in pf.schema_arrow.names if s.lower() in
                                               ('snapshot_at', 'snapshot_utc', 'queried_at', 'retrieved_at', 'fetched_at', 'updated_at')]
        selected = []
        for field in pf.schema_arrow:
            found = geo_paths(field.type, field.name)
            # Limit exported field names to safe canonical locations.
            result['schema_geo_fields'].extend(sorted(set(
                ('profile.' if '.profile.' in '.'+s or s.startswith('profile.') else '') + s.rsplit('.', 1)[-1]
                for s in found)))
            if found or field.name.lower() in JSON_KEYS:
                selected.append(field.name)
        result['structured_geo_schema_present'] = bool(result['schema_geo_fields'])
        if selected:
            batch = next(pf.iter_batches(batch_size=256, columns=selected, use_threads=False), None)
            if batch is not None:
                records = batch.to_pylist()
                result['rows_sampled'] = len(records)
                for record in records:
                    inspect_object(record, present, nonempty)
    elif suffix in ('.csv', '.tsv'):
        with path.open(newline='', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader(f, delimiter='\t' if suffix == '.tsv' else ',')
            fields = reader.fieldnames or []
            result['schema_geo_fields'] = [s for s in fields if s.lower().replace('profile.', '') in GEO]
            for k, row in enumerate(reader):
                if k >= 256:
                    break
                result['rows_sampled'] += 1
                inspect_object(row, present, nonempty)
    elif suffix in ('.json', '.jsonl', '.ndjson', '.gz', '.zst'):
        opener = gzip.open if suffix == '.gz' else open
        jsonl = suffix in ('.jsonl', '.ndjson') or path.name.endswith(('.jsonl.gz', '.ndjson.gz', '.jsonl.zst', '.ndjson.zst'))
        stream = (stdio.TextIOWrapper(pa.input_stream(path, compression='zstd'), encoding='utf-8', errors='replace')
                  if suffix == '.zst' else opener(path, 'rt', encoding='utf-8', errors='replace'))
        with stream as f:
            if jsonl:
                total = 0
                for _ in range(256):
                    line = f.readline(1_000_001)
                    if not line:
                        break
                    total += len(line)
                    if len(line) > 1_000_000 or total > 8_000_000:
                        result['status'] = 'PARTIAL_SAMPLE_SIZE_LIMIT'
                        break
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    inspect_object(obj, present, nonempty)
                    result['rows_sampled'] += 1
            else:
                content = f.read(8_000_001)
                if len(content) > 8_000_000:
                    result['status'] = 'SKIPPED_LARGE_SINGLE_JSON'
                else:
                    obj = json.loads(content)
                    sample = obj[:256] if isinstance(obj, list) else obj
                    inspect_object(sample, present, nonempty)
                    result['rows_sampled'] = len(sample) if isinstance(sample, list) else 1
                    result['full_file_scanned'] = not isinstance(obj, list) or len(obj) <= 256
    else:
        result['status'] = 'FORMAT_NOT_INSPECTED'
    result['schema_geo_fields'] = sorted(set(result['schema_geo_fields']))
    result['sampled_geo_field_occurrences'] = present
    result['sampled_nonempty_geo_occurrences'] = nonempty
    return result

def discover_profile_files(project, extra_paths=()):
    start = time.monotonic()
    files, explicit_files, visited, truncated = set(), set(), 0, False
    allowed = ('.parquet', '.json', '.jsonl', '.ndjson', '.json.gz', '.jsonl.gz', '.ndjson.gz',
               '.json.zst', '.jsonl.zst', '.ndjson.zst', '.csv', '.tsv')
    roots = [project] + [Path(p).expanduser().resolve() for p in extra_paths]
    for root in roots:
        explicit = root != project
        if root.is_file():
            files.add(root)
            explicit_files.add(root)
            continue
        if not root.is_dir():
            continue
        for directory, dirs, names in os.walk(root, followlinks=False):
            visited += 1
            p = Path(directory)
            depth = len(p.relative_to(root).parts)
            dirs[:] = sorted(n for n in dirs if not n.startswith('.') and n not in
                             ('venv', 'env', 'node_modules', '__pycache__') and
                             not n.startswith('iv_slide_gaps_'))
            if depth >= 8:
                if dirs:
                    truncated = True
                dirs[:] = []
            for name in sorted(names):
                q = p/name
                relative = str(q.relative_to(root)).lower()
                if (explicit or any(word in relative for word in ('profile', 'patron', 'country', 'flag'))) and name.lower().endswith(allowed):
                    files.add(q)
                    if explicit:
                        explicit_files.add(q)
            if visited >= 15000 or len(files) >= 1000 or time.monotonic()-start > 45:
                truncated = True
                break
    ranked = sorted(files, key=lambda p: (p not in explicit_files,
                    not any(s in p.name.lower() for s in ('profile', 'country', 'flag')), str(p)))
    return ranked[:250], dict(directories_visited=visited, candidates_found=len(files),
                             inspected_file_limit=250, discovery_truncated=truncated or len(ranked)>250,
                             discovery_seconds=time.monotonic()-start)

def audit_profiles(project, private_directory, extra_paths=()):
    paths, summary = discover_profile_files(project, extra_paths)
    rows, private = [], []
    for k, path in enumerate(paths):
        label = f'profile_candidate_{k+1:03d}'
        private.append(dict(file_label=label, path=str(path)))
        try:
            rows.append(inspect_file(path, label))
        except Exception as error:
            rows.append(dict(file_label=label, status='INSPECTION_ERROR', error_type=type(error).__name__))
    io.js(private_directory/'profile_paths_PRIVATE.json', private)
    nonempty = sum(bool(r.get('sampled_nonempty_geo_occurrences')) for r in rows)
    fields = sum(bool(r.get('schema_geo_fields') or r.get('sampled_geo_field_occurrences')) for r in rows)
    summary.update(files_inspected=len(rows), files_with_geo_fields=fields,
                   files_with_sampled_nonempty_geo_values=nonempty,
                   status='NONEMPTY_GEO_FIELD_FOUND' if nonempty else 'GEO_FIELD_FOUND_CONTENT_UNCONFIRMED' if fields else 'NOT_FOUND_IN_BOUNDED_AUDIT',
                   country_balance_run=False, profile_identity_join_validated=False,
                   current_profile_is_predetermined_baseline=False,
                   interpretation='Field discovery only. Verify snapshot date, stable account-ID join and IV coverage before treating current self-reported geography as a baseline balance covariate. A bounded negative search is not proof the field was never retained.')
    return rows, summary

def parse_run2_processes(output, project):
    known = {'run_optimized.py': 'analysis', 'run_phase_analysis.py': 'analysis',
             'run_cached.py': 'analysis', 'run_download.py': 'downloader',
             'run_local_first.py': 'preparation_or_download', 'run_phases.py': 'phased_run',
             'run_phased.py': 'phased_run', 'run_reduced_download.py': 'downloader'}
    found = []
    for line in output.splitlines():
        match = re.match(r'^\s*(\d+)\s+(\S+)\s+(\S+)\s+(.*)$', line)
        if not match:
            continue
        pid, elapsed, cpu, command = match.groups()
        if str(project) not in command and not re.search(r'(?i)(run2_|iv_runs_2_3)', command):
            continue
        try:
            args = shlex.split(command)
        except ValueError:
            continue
        scripts = [Path(arg).name for arg in args if Path(arg).name in known]
        if not scripts or not any('python' in Path(arg).name.lower() for arg in args[:2]):
            continue
        # Raw argv may contain paths/account names; never include it in the report.
        found.append(dict(process_id=int(pid), elapsed=elapsed, CPU_percent=cpu,
                          script=scripts[0], role=known[scripts[0]]))
    return found[:30]

def process_snapshot(project):
    try:
        result = subprocess.run(['ps', '-axo', 'pid=,etime=,%cpu=,command='],
                                capture_output=True, text=True, timeout=5, check=True)
        found = parse_run2_processes(result.stdout, project)
        return dict(status='MATCHING_PROCESS_OBSERVED' if found else 'NO_MATCHING_PROCESS_OBSERVED',
                    processes=found, scope='Recognized Run 2 Python commands on this machine at this instant',
                    progress_or_success_inferred=False)
    except Exception as error:
        return dict(status='PROCESS_SNAPSHOT_UNAVAILABLE', error_type=type(error).__name__)

def audit_run2_status(project, desktop, private_directory):
    """Export status scalars from local receipts, not an assertion of live health."""
    candidates = []
    for p in sorted(desktop.glob('RUN2*LATEST_PRIVATE.json')):
        try:
            pointer = io.load(p)
        except Exception:
            continue
        for key in ('root', 'ready'):
            if key in pointer:
                root = Path(pointer[key]).expanduser().resolve()
                if root.is_relative_to(project):
                    for sub in ('summary.json', '_DONE.json', 'report/summary.json', 'report/_DONE.json', 'status.json', 'progress.json'):
                        if (root/sub).is_file():
                            candidates.append(root/sub)
    replication = project/'derived/replication'
    if replication.is_dir():
        for parent in sorted(replication.glob('run2*PRIVATE')):
            for name in ('*/report/summary.json', '*/report/_DONE.json', '*/summary.json', '*/status.json', '*/progress.json'):
                candidates.extend(parent.glob(name))
    rows, private = [], []
    keep = re.compile(r'^(status|phase|phase_fraction|fraction|n|rows|completed|complete|planned|pending|failed|running|retrieved|returned|available|unavailable|downloaded|total|updated_at|created_at|config_sha256)(_|$)', re.I)
    for k, path in enumerate(sorted(set(candidates))[:100]):
        if path.stat().st_size > 2_000_000:
            continue
        try:
            obj = io.load(path)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        safe = {key:value for key,value in obj.items() if keep.search(key) and isinstance(value, (int, float, bool, type(None)))}
        if isinstance(obj.get('status'), str):
            safe['status'] = obj['status'][:300]
        label = f'run2_status_candidate_{k+1:03d}'
        rows.append(dict(file_label=label, kind=path.name, file_modified_UTC_epoch=path.stat().st_mtime, **safe))
        private.append(dict(file_label=label, path=str(path)))
    io.js(private_directory/'run2_status_paths_PRIVATE.json', private)
    return dict(status='LOCAL_RECEIPTS_CAPTURED' if rows else 'NO_MATCHING_LOCAL_STATUS_RECEIPTS_FOUND',
                process_snapshot=process_snapshot(project), full_frame_completion_certified=False,
                note='Read-only snapshot. A phase-complete receipt is not full-frame completion; return for review.',
                receipts=rows)
