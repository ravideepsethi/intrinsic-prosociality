#!/usr/bin/env python3
from pathlib import Path
import hashlib
root = Path(__file__).resolve().parent
count = 0
for line in (root / 'SHA256SUMS.txt').read_text().splitlines():
    expected, relative = line.split('  ', 1)
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise SystemExit('Invalid package path')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Package checksum failed: ' + relative)
    count += 1
print(f'FIGURE PACKAGE VERIFIED: {count} files')
