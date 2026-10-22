#!/usr/bin/env python3
"""Build the versioned release ZIP and SHA-256 sidecar from this source tree."""
from pathlib import Path
import hashlib,json,zipfile

root=Path(__file__).resolve().parent
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
    return h.hexdigest()

files=[p for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
       and p.suffix not in ('.pyc','.pyo') and p!=root/'PACKAGE_MANIFEST.json']
for p in root.glob('*.command'):p.chmod(0o755)
records=[dict(path=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=sha(p)) for p in files]
(root/'PACKAGE_MANIFEST.json').write_text(json.dumps(dict(version='1.0.1',files=records),indent=2)+'\n')
dest=root.parent/(root.name+'.zip')
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in files+[root/'PACKAGE_MANIFEST.json']:z.write(p,str(Path(root.name)/p.relative_to(root)))
digest=sha(dest);dest.with_suffix('.zip.sha256').write_text(digest+'  '+dest.name+'\n')
print(json.dumps(dict(path=str(dest),sha256=digest,bytes=dest.stat().st_size,files=len(files)+1)))
