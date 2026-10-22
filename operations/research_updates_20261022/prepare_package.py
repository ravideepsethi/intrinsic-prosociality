#!/usr/bin/env python3
"""Verify a public source snapshot and prepare its original local package.

The original archive is required because it contains the input certificates,
private configuration and other assets deliberately omitted from this release.
No source is executed, no network request is made, and no existing path is
overwritten. Run the restored package's own launcher afterwards.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[2]
MANIFESTS = REPO / 'manifests/research_updates_20261022'
SOURCES = REPO / 'code/research_updates_20261022'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name:
        raise ValueError('Unsafe archive path')
    return p


def public_form(data, spans):
    text = data.decode('utf-8')
    chunks, last = [], 0
    for span in spans:
        start, end = span['start'], span['end']
        if not (last <= start < end <= len(text)):
            raise ValueError('Invalid privacy-template span')
        chunks.extend([text[last:start], span['token']])
        last = end
    chunks.append(text[last:])
    return ''.join(chunks).encode('utf-8')


def verify_archive(manifest, archive, source_root):
    if digest(archive.read_bytes()) != manifest['archive_sha256']:
        raise ValueError('Original archive SHA-256 mismatch')
    expected = {x['path']: x for x in manifest['files'] + manifest['omitted_files']}
    if len(expected) != len(manifest['files']) + len(manifest['omitted_files']):
        raise ValueError('Duplicate manifest path')
    prefix = manifest['archive_root'].rstrip('/')
    contents = {}
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            safe_relative(member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('Archive symlinks are not accepted')
            if member.is_dir():
                continue
            if prefix:
                if not member.filename.startswith(prefix + '/'):
                    raise ValueError('Unexpected archive root')
                relative = member.filename[len(prefix) + 1:]
            else:
                relative = member.filename
            safe_relative(relative)
            if relative in contents or relative not in expected:
                raise ValueError('Duplicate or unregistered archive member')
            data = z.read(member)
            entry = expected[relative]
            if len(data) != entry['size'] or digest(data) != entry['sha256']:
                raise ValueError('Original member checksum mismatch: ' + relative)
            contents[relative] = data
    if set(contents) != set(expected):
        raise ValueError('Archive inventory mismatch')
    for entry in manifest['files']:
        safe_relative(entry['published_path'])
        published = source_root / entry['published_path']
        if published.is_symlink():
            raise ValueError('Public source symlink is not accepted')
        data = published.read_bytes()
        if digest(data) != entry['published_sha256']:
            raise ValueError('Public source checksum mismatch: ' + entry['published_path'])
        if data != public_form(contents[entry['path']], entry.get('redactions', [])):
            raise ValueError('Public source differs from authenticated original')
    return contents


def prepare(manifest, archive, source_root, output):
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Output must be a new directory')
    if output.resolve().is_relative_to(REPO):
        raise ValueError('Restore private assets outside the public checkout')
    contents = verify_archive(manifest, archive, source_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.prepare-package-', dir=output.parent))
    try:
        for relative, data in contents.items():
            target = temp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o700 if target.suffix in {'.sh', '.command'} else 0o600)
        # Refuse a concurrent destination creation instead of replacing it.
        output.mkdir(mode=0o700)
        for child in temp.iterdir():
            shutil.move(str(child), str(output / child.name))
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return len(contents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if Path(args.package).name != args.package:
        parser.error('Package must be a name from PACKAGE_INDEX.json')
    manifest = json.loads((MANIFESTS / (args.package + '.json')).read_text())
    count = prepare(manifest, args.archive, SOURCES / args.package, args.output)
    print(json.dumps({'status': 'ORIGINAL_PACKAGE_VERIFIED_AND_PREPARED',
                      'package': args.package, 'files': count,
                      'output': str(args.output.absolute()), 'analyses_executed': False}))


if __name__ == '__main__':
    main()
