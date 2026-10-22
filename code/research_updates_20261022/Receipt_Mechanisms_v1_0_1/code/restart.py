"""Reuse only verified hash-cache entries and the unchanged focal projection."""
from common import *
import shutil

def previous_root(project):
    auth=read(PACKAGE/'authority/restart.json');key=auth['old_run_key']
    old=Path(project)/'derived/replication/receipt_mechanisms_v100_PRIVATE'/key[:12]
    if not (old/'config.json').exists():return None
    cfg=read(old/'config.json')
    if digest(cfg)!=key or cfg.get('version')!=auth['old_version'] or cfg.get('package_sha256')!=auth['old_package_manifest_sha256']:
        raise RuntimeError('Prior receipt-mechanism run does not match the reviewed failed run')
    return old

def seed_hash_cache(project,work):
    old=previous_root(project)
    if old is None:return
    copied=0
    for p in (old/'authenticated').glob('*.json'):
        r=read(p);sig=r.get('signature',{});target=Path(sig.get('path',''))
        if not target.is_file() or Path(project).resolve() not in target.resolve().parents:continue
        if sig!=signature(target) or p.name!=digest(sig)+'.json':continue
        if not isinstance(r.get('sha256'),str) or len(r['sha256'])!=64:continue
        dest=Path(work)/'authenticated'/p.name
        if not dest.exists():write(dest,r);copied+=1
    log(f'Reused {copied} existing source-hash cache records; every consumer still checks its required checksum')

def reuse_focal(project,work,binding,key):
    dest=Path(work)/'focal'
    if checkpoint_ok(dest,key):return
    old=previous_root(project)
    if old is None or not (old/'binding_PRIVATE.json').exists():return
    if digest(read(old/'binding_PRIVATE.json'))!=digest(binding):raise RuntimeError('Prior and current source bindings differ')
    oldkey=read(PACKAGE/'authority/restart.json')['old_run_key'];src=old/'focal'
    if not checkpoint_ok(src,oldkey):return
    dest.mkdir(parents=True,exist_ok=True)
    for rec in read(src/'_DONE.json')['files']:
        p=src/rec['path'];target=dest/rec['path']
        # Copy creates an independent result; it never mutates prior checkpoints.
        shutil.copy2(p,target)
    finish(dest,key,dict(reused_from=str(src),source_binding_sha256=digest(binding)))
    write(Path(work)/'restart_PRIVATE.json',dict(source=str(old),reused_focal=True,
      unsealed_month_files_reused=False,reason='Month outputs had no completed receipt for populated months'))
    log('Reused the verified focal metadata projection. Monthly joins will be checked again.')
