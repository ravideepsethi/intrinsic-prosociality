#!/usr/bin/env python3
"""Verify the shipped package or only its frozen source inputs; stdlib only."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources-only', action='store_true',
                        help='Check frozen inputs; allow locally regenerated outputs.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.sources_only:
        entries = [(e['sha256'], e['file']) for e in
                   json.loads((root/'SOURCE_MANIFEST.json').read_text())['entries']]
    else:
        entries = [line.split('  ', 1) for line in
                   (root/'MANIFEST.sha256').read_text().splitlines() if line]
    failures = []
    for expected, name in entries:
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            failures.append(name + ': missing or outside package')
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(name + ': SHA-256 mismatch')
    if failures:
        raise SystemExit('VERIFICATION FAILED\n' + '\n'.join(failures))
    print(f'PACKAGE_VERIFIED_OK: {len(entries)} SHA-256 checks passed')


if __name__ == '__main__':
    main()
