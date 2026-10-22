#!/usr/bin/env python3
"""Aggregate-only result packaging: private account/row Parquets never enter ZIP."""
import argparse,hashlib,json,shutil,zipfile
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--desktop',required=True)
ap.add_argument('--tag',required=True);ap.add_argument('--status',required=True);ap.add_argument('--timestamp',required=True)
a=ap.parse_args()
root=Path(a.out);desk=Path(a.desktop)
report=desk/f'FRAMEWORK_{a.tag}_REPORT_{a.timestamp}.zip'
meta={'status':a.status,'package':'Framework_AE_Completion_v1_2_0',
 'partial_or_failed_run':a.status!='COMPLETE',
 'privacy':'Public aggregate reports only. No account IDs, source Parquets, usernames, profiles, raw JSON or private estimates.'}
files=[]
for folder in sorted(root.rglob('public')):
 if not folder.is_dir():continue
 for p in sorted(folder.rglob('*')):
  if p.is_file() and p.suffix.lower() in ('.csv','.txt','.json','.md'):
   if '_PRIVATE' in p.name:raise RuntimeError('Private file proposed for public report')
   files.append((p,str(p.relative_to(root))))
with zipfile.ZipFile(report,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 z.writestr('REPORT_STATUS.json',json.dumps(meta,indent=2)+'\n')
 for p,name in files:z.write(p,name)
sha=hashlib.sha256(report.read_bytes()).hexdigest()
side=report.with_suffix(report.suffix+'.sha256')
side.write_text(f'{sha}  {report.name}\n')
print('Report ZIP',report,'files',len(files),'SHA-256',sha,flush=True)
