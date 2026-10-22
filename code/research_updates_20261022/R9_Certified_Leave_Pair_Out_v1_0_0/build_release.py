"""Build a deterministic file inventory, then ZIP and SHA256 sidecar."""
from pathlib import Path
import hashlib,zipfile
root=Path(__file__).resolve().parent
files=sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.pyc') and p!=root/'PACKAGE_MANIFEST.sha256')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(root/'PACKAGE_MANIFEST.sha256').write_text(''.join(sha(p)+'  '+p.relative_to(root).as_posix()+'\n' for p in files))
target=root.with_suffix('.zip')
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in files+[root/'PACKAGE_MANIFEST.sha256']:z.write(p,root.name+'/'+p.relative_to(root).as_posix())
target.with_suffix('.zip.sha256').write_text(sha(target)+'  '+target.name+'\n')
print(target.name,target.stat().st_size,sha(target),len(files)+1,'files')
