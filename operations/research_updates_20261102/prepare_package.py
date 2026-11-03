#!/usr/bin/env python3
"""Restore a checksum-verified original package locally; never execute it."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT=Path(__file__).resolve().parents[2]
MAN=ROOT/'manifests/research_updates_20261102'

def sha(data):return hashlib.sha256(data).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)

def validate_archive(path,manifest):
    require(sha(path.read_bytes())==manifest['archive_sha256'],'Archive checksum differs')
    with zipfile.ZipFile(path) as z:
        require(z.testzip() is None,'Archive CRC failed')
        files=[x for x in z.infolist() if not x.is_dir() and '__pycache__' not in PurePosixPath(x.filename).parts and '__MACOSX' not in PurePosixPath(x.filename).parts]
        expected={x['archive_member']:x for x in manifest['files']+manifest['omitted']}
        require(len(files)==len(expected) and {x.filename for x in files}==set(expected),'Archive member inventory differs')
        for info in files:
            p=PurePosixPath(info.filename)
            require(not p.is_absolute() and '..' not in p.parts,'Unsafe archive member')
            require(not stat.S_ISLNK(info.external_attr>>16),'Archive symlinks unsupported')
            r=expected[info.filename];data=z.read(info)
            require(len(data)==r['original_bytes'] and sha(data)==r['original_sha256'],'Archive member checksum differs')
    return expected

def prepare(package,archive,output):
    choices=json.loads((MAN/'SOURCE_PACKAGE_INDEX.json').read_text())
    entry=next((x for x in choices if x['package']==package),None)
    require(entry is not None,'Unknown source package')
    require(not output.exists(),'Output already exists')
    manifest=json.loads((ROOT/entry['manifest']).read_text())
    expected=validate_archive(archive,manifest)
    for item in manifest['files']:
        require(sha((ROOT/item['path']).read_bytes())==item['published_sha256'],'Public source changed')
    output.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for name in expected:
            rel=PurePosixPath(name).parts[1:]
            require(bool(rel),'Missing package-relative path')
            p=output.joinpath(*rel);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
    return dict(status='ORIGINAL_PACKAGE_RESTORED',package=package,files=len(expected),output=str(output),analyses_executed=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package',required=True)
    p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();print(json.dumps(prepare(args.package,args.archive,args.output),indent=2))
