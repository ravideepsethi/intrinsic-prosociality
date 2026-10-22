from pathlib import Path
import hashlib
root=Path(__file__).resolve().parent
for line in (root/'SHA256SUMS.txt').read_text().splitlines():
    digest,rel=line.split('  ',1);path=root/rel
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise SystemExit('Package file changed: '+rel)
print('PACKAGE_SHA256_OK',flush=True)
