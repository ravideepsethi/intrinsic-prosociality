from pathlib import Path
import hashlib
root=Path(__file__).resolve().parent
for line in (root/'SHA256SUMS.txt').read_text().splitlines():
    digest,name=line.split('  ',1);p=(root/name).resolve()
    assert p.is_relative_to(root),'Manifest path escapes package'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,'Package checksum mismatch: '+name
print('R11_PACKAGE_SHA256_OK',flush=True)
