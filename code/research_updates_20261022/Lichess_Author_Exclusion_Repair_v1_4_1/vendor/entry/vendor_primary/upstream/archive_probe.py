"""Small, read-only PGN header audit. Exports aggregate diagnostics only."""
import bz2
import gzip
import io
import re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import sys
import zstandard
from local_common import ROOT, MONTHS, csv_out, save, log
sys.path.insert(0, str(ROOT / 'vendor/r11'))
import all_games


@contextmanager
def open_text(path):
    path = Path(path)
    if path.name.endswith('.zst'):
        with path.open('rb') as raw:
            with zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as stream:
                with io.TextIOWrapper(stream, encoding='utf-8-sig', errors='strict') as text:
                    yield text
    elif path.name.endswith('.gz'):
        with gzip.open(path, 'rt', encoding='utf-8-sig') as text:
            yield text
    elif path.name.endswith('.bz2'):
        with bz2.open(path, 'rt', encoding='utf-8-sig') as text:
            yield text
    else:
        with path.open(encoding='utf-8-sig') as text:
            yield text


def event_class(value):
    if value is None:
        return 'missing'
    if value.strip() in ('', '?', '-', '??'):
        return 'empty_or_placeholder'
    if value.startswith('Rated '):
        return 'rated_exact_prefix'
    if value.strip().casefold().startswith('rated '):
        return 'rated_after_case_whitespace_normalization'
    if value.strip().casefold().startswith('casual '):
        return 'casual'
    return 'other_unresolved'


def probe_one(path, month, limit=64):
    path = Path(path)
    row = dict(month=month, source_name=path.name, source_bytes=path.stat().st_size,
               games_sampled=0, reached_eof=False, event_classes={},
               header_presence={}, parser_dispositions={}, parser_errors={},
               status='SAMPLED', error_type='')
    events, headers, results, errors = Counter(), Counter(), Counter(), Counter()
    try:
        with open_text(path) as f:
            stream = all_games.iter_games(f)
            while row['games_sampled'] < limit:
                try:
                    tags, body = next(stream)
                except StopIteration:
                    row['reached_eof'] = True
                    break
                row['games_sampled'] += 1
                events[event_class(tags.get('Event'))] += 1
                for name in ('Event', 'Site', 'UTCDate', 'Date', 'UTCTime', 'Result',
                             'TimeControl', 'Variant', 'SetUp', 'FEN', 'WhiteElo',
                             'BlackElo', 'Termination', 'PlyCount'):
                    if name in tags:
                        headers[name] += 1
                try:
                    _, disposition = all_games.game_record(tags, body, month)
                    results[disposition] += 1
                except Exception as exc:
                    # Known reader errors contain no account/game identifiers.
                    text = str(exc)
                    allowed = ('Unknown ratedness in monthly PGN',
                               'PGN date lies outside the named month',
                               'Unknown PGN result', 'Missing or unknown PGN TimeControl',
                               'Missing/truncated/mismatched PGN final result',
                               'Unrecognized SAN token; median scan stopped instead of silently skipping a game')
                    errors[text if text in allowed else type(exc).__name__] += 1
    except Exception as exc:
        row['status'] = 'READ_FAILED'
        row['error_type'] = type(exc).__name__
    row.update(event_classes=dict(events), header_presence=dict(headers),
               parser_dispositions=dict(results), parser_errors=dict(errors))
    return row


def run(a, run, k):
    roots = a.archive_root or [a.project / 'raw', a.project / 'archives', a.project / 'data', a.project.parent]
    discovery, inventory = all_games.discover(roots)
    rows = []
    for rec in discovery:
        if not rec['candidates']:
            rows.append(dict(month=rec['month'], status='MISSING', source_name='',
                             source_bytes=0, games_sampled=0))
        for p in rec['candidates']:
            row = probe_one(p, rec['month'])
            rows.append(row)
            log(f'Archive probe {rec["month"]}: {row["games_sampled"]} headers; {row["event_classes"]}')
    csv_out(run / 'report/archive_header_probe.csv', rows)
    save(run / 'report/archive_probe_notes.json', dict(
        requested_months=MONTHS, games_per_file_limit=64,
        purpose='Diagnose rejected archive headers and missing files; not a complete-file census',
        privacy='Header presence counts and fixed event categories only; no account names, game IDs, PGNs, or raw event strings',
        sources_read_only=True, network_requests=0, engine_evaluations=0,
        sample_limitation='A valid prefix does not certify full coverage, EOF, ratedness of later games, or archive authenticity'))
