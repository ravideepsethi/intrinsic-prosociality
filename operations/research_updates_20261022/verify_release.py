#!/usr/bin/env python3
"""Verify this source publication without reading research data or using network."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
MANIFESTS = REPO / 'manifests/research_updates_20261022'
SOURCES = REPO / 'code/research_updates_20261022'


def main():
    expected = {}
    for line in (MANIFESTS / 'PUBLIC_SHA256SUMS.txt').read_text().splitlines():
        value, name = line.split('  ', 1)
        path = REPO / name
        if not path.resolve().is_relative_to(REPO) or path.is_symlink():
            raise ValueError('Unsafe publication path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != value:
            raise ValueError('Publication hash mismatch: ' + name)
        expected[name] = value
    actual = set()
    for root in [SOURCES, MANIFESTS, REPO/'docs/research_updates_20261022',
                 REPO/'operations/research_updates_20261022']:
        for p in root.rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts or p.name == 'PUBLIC_SHA256SUMS.txt':
                continue
            actual.add(str(p.relative_to(REPO)))
    actual.add('README.md')
    if actual != set(expected):
        raise ValueError('Publication inventory mismatch')
    python_count, shell_count = 0, 0
    seen_python, seen_shell = set(), set()
    packages = json.loads((MANIFESTS/'PACKAGE_INDEX.json').read_text())
    for package in packages:
        manifest = json.loads((REPO / package['manifest']).read_text())
        for entry in manifest['files']:
            p = SOURCES / package['package'] / entry['published_path']
            data = p.read_bytes()
            value = hashlib.sha256(data).hexdigest()
            if value != entry['published_sha256']:
                raise ValueError('Package source mismatch')
            suffix = Path(entry['path']).suffix
            if suffix == '.py':
                python_count += 1
                if value not in seen_python:
                    ast.parse(data.decode(), filename=str(p))
                    seen_python.add(value)
            elif suffix in {'.command', '.sh'}:
                shell_count += 1
                if value not in seen_shell:
                    subprocess.run(['bash', '-n', str(p)], check=True, capture_output=True)
                    seen_shell.add(value)
    print(json.dumps({'status':'PUBLIC_SOURCE_RELEASE_VERIFIED',
                      'packages':len(packages),'published_files':len(expected),
                      'python_files':python_count,'unique_python_files':len(seen_python),
                      'shell_files':shell_count,'unique_shell_files':len(seen_shell),
                      'production_analyses_executed':False},indent=2))


if __name__ == '__main__':
    main()
