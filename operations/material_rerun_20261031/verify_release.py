#!/usr/bin/env python3
"""Check this public checkpoint offline without executing analysis code."""
import ast
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

REPO = Path(__file__).resolve().parents[2]
LABEL = 'material_rerun_20261031'
MAN = REPO / 'manifests' / LABEL
CHECKSUMS = MAN / 'PUBLIC_SHA256SUMS.txt'
ROOTS = [REPO / kind / LABEL for kind in
         ('code', 'results', 'docs', 'manifests', 'operations')]
IDENTITY_KEYS = {'row_id', 'game_id', 'recipient_id', 'opponent_id',
                 'chooser_user_id', 'disconnected_user_id', 'user_id',
                 'username', 'usernames', 'author_ids', 'author_user_ids'}
# Construct path markers without embedding a real private path in this file.
PRIVATE_PATH = re.compile('/' + r'(?:Users|Volumes|workspace/scratch|var/folders)/')
CREDENTIAL = re.compile(r'(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_]{16,}'
                        r'|BEGIN [A-Z ]*PRIVATE KEY')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def path_for(name):
    p = PurePosixPath(name)
    require(bool(name) and not p.is_absolute() and '..' not in p.parts
            and '\\' not in name, 'Unsafe publication path')
    target = REPO / name
    require(target.resolve().is_relative_to(REPO), 'Path escapes repository')
    require(not target.is_symlink(), 'Publication symlink is not allowed')
    return target


def read_json(path):
    return json.loads(path.read_text())


def contains_identity_key(obj):
    if isinstance(obj, dict):
        return bool(set(k.lower() for k in obj) & IDENTITY_KEYS) or any(
            contains_identity_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_identity_key(v) for v in obj)
    return False


def verify():
    inventory = {}
    for line in CHECKSUMS.read_text().splitlines():
        h, name = line.split('  ', 1)
        require(re.fullmatch('[0-9a-f]{64}', h), 'Invalid SHA-256')
        require(name not in inventory, 'Duplicate inventory path: ' + name)
        p = path_for(name)
        require(p.is_file(), 'Missing publication file: ' + name)
        require(digest(p.read_bytes()) == h, 'Checksum mismatch: ' + name)
        inventory[name] = h
    actual = {'README.md'}
    for root in ROOTS:
        for p in root.rglob('*'):
            if '__pycache__' in p.parts or p == CHECKSUMS:
                continue
            require(not p.is_symlink(), 'Symlink found: ' + str(p))
            if p.is_file():
                actual.add(p.relative_to(REPO).as_posix())
    require(actual == set(inventory), 'Public inventory differs from files on disk')

    packages = read_json(MAN / 'PACKAGE_INDEX.json')
    source_files = set()
    python_files = shell_files = 0
    for entry in packages:
        m = read_json(path_for(entry['manifest']))
        require(m['package'] == entry['package'], 'Package identity mismatch')
        require(m['archive_sha256'] == entry['archive_sha256'], 'Archive hash mismatch')
        require(len(m['files']) == entry['source_files'], 'Source count mismatch')
        originals = [x['path'] for x in m['files'] + m['omitted_files']]
        require(len(originals) == len(set(originals)), 'Duplicate original path')
        for f in m['files']:
            name = 'code/' + LABEL + '/' + m['package'] + '/' + f['published_path']
            p = path_for(name)
            data = p.read_bytes()
            require(digest(data) == f['published_sha256'], 'Source hash mismatch: ' + name)
            source_files.add(name)
            ext = Path(f['path']).suffix
            if ext == '.py':
                ast.parse(data.decode('utf-8'), filename=name)
                python_files += 1
            elif ext in ('.sh', '.command'):
                subprocess.run(['bash', '-n', str(p)], check=True, capture_output=True)
                shell_files += 1
    require(source_files == {n for n in actual if n.startswith('code/' + LABEL + '/')},
            'Source manifest coverage mismatch')

    groups = read_json(MAN / 'RESULT_INDEX.json')
    report_files = set()
    for group in groups:
        m = read_json(path_for(group['manifest']))
        require(m['group'] == group['group'] and m['reviewed_status'] == group['status'],
                'Report status mismatch')
        require(m['whole_paper_complete'] is False, 'Unexpected completion claim')
        require(len(m['files']) == group['published_files'], 'Report count mismatch')
        originals = {x['path']: x for x in m['original_report_manifest']}
        require(len(originals) == m['all_report_entries_verified'], 'Sealed inventory mismatch')
        seen = set()
        for f in m['files'] + m['omitted_files']:
            if not f.get('provenance'):
                require(f['original_path'] not in seen, 'Duplicate report mapping')
                seen.add(f['original_path'])
                old = originals[f['original_path']]
                require(old['sha256'] == f['original_sha256'] and
                        old['bytes'] == f['original_bytes'], 'Report provenance mismatch')
            if 'published_path' not in f:
                continue
            name = f['published_path']
            require(name.startswith('results/' + LABEL + '/' + group['group'] + '/'),
                    'Report path outside its group')
            data = path_for(name).read_bytes()
            require(digest(data) == f['published_sha256'] and len(data) == f['published_bytes'],
                    'Published report mismatch: ' + name)
            report_files.add(name)
        require(seen == set(originals), 'Report provenance coverage mismatch')
    require(report_files | {'results/' + LABEL + '/README.md'} ==
            {n for n in actual if n.startswith('results/' + LABEL + '/')},
            'Report manifest coverage mismatch')

    for name in actual:
        p = path_for(name)
        if p.suffix in ('.png', '.pdf'):
            continue
        text = p.read_text()
        require(not PRIVATE_PATH.search(text), 'Private absolute path: ' + name)
        require(not CREDENTIAL.search(text), 'Credential-like content: ' + name)
        if p.suffix == '.json':
            obj = json.loads(text)
            if name in report_files:
                require(not contains_identity_key(obj), 'Individual identity field: ' + name)
        if name in report_files and p.suffix in ('.csv', '.tsv'):
            rows = csv.reader(io.StringIO(text), delimiter='\t' if p.suffix == '.tsv' else ',')
            header = next(rows, [])
            require(not set(x.lower() for x in header) & IDENTITY_KEYS,
                    'Individual identity column: ' + name)
        if name.startswith('operations/') and p.suffix == '.py':
            ast.parse(text, filename=name)

    result_root = REPO / 'results' / LABEL
    review = read_json(result_root / 'noniv_batch/PUBLICATION_REVIEW.json')
    require(review['complete_families'] == review['total_families'] == 11,
            'Unexpected non-IV completion count')
    iv = read_json(result_root / 'iv_partial/receipt/STATUS.json')
    require(iv['status'] == 'PARTIAL' and len(iv['completed']) == 14
            and len(iv['failed_or_blocked']) == 4, 'Unexpected IV completion status')
    v = read_json(REPO / 'docs' / LABEL / 'IV_VALIDATION.json')
    require(v['production_repair_run_performed'] is False and v['result'] == 'PASS'
            and v['batch_and_companion_tests'] + v['original_uniform_tests'] == 112,
            'Repair-validation boundary changed')
    print(json.dumps(dict(status='PUBLIC_CHECKPOINT_VERIFIED', packages=len(packages),
          public_files=len(actual), source_files=len(source_files),
          python_syntax_checked=python_files, shell_syntax_checked=shell_files,
          report_groups=len(groups), report_files=len(report_files),
          analyses_executed=False, whole_paper_complete=False), indent=2))


if __name__ == '__main__':
    verify()
