#!/usr/bin/env python3
"""Authenticate this public release using only the Python standard library."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys

def main():
    root = Path(__file__).resolve().parents[2]
    manifest = root/'manifests/pool_main_reanalysis_v100/REPO_FILE_HASHES.sha256'
    seen = set()
    for line in manifest.read_text(encoding='utf-8').splitlines():
        expected, relative = line.split('  ', 1)
        p = PurePosixPath(relative)
        if p.is_absolute() or '..' in p.parts or relative in seen:
            raise RuntimeError('Invalid or duplicate manifest path: '+relative)
        seen.add(relative)
        target = root.joinpath(*p.parts)
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Missing or changed file: '+relative)
    sample = json.loads((root/'manifests/pool_main_reanalysis_v100/SAMPLE_DECISION.json').read_text())
    if sample['main_sample']['opportunities'] != 41534331:
        raise RuntimeError('Incorrect main sample')
    print(f'PUBLIC RELEASE VERIFIED: {len(seen):,} SHA-256 file hashes match.')
    print('Main sample: 41,534,331. This check runs no models and uses no network.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
