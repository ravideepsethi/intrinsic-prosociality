"""Authenticate only files consumed by this stage; do not rescan game history."""
from common import *

AUTH = PACKAGE/'authority'
ASSEMBLY_CODE = '2bb959770ecdd68a5356be72ededa7569f4595b53408fa207772ce4bd79b1220'
POST_MONTHS = ('2025-11','2025-12','2026-01')
ACCOUNT_POLICY = load(AUTH/'assembly_ACCOUNT_POLICY.json')

def snap(p):
    return dict(**receipt(p),fingerprint=stamp(p))

def verify_package():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,n=line.split('  ',1);p=PACKAGE/n
        if not p.resolve().is_relative_to(PACKAGE.resolve()) or sha(p)!=h:
            raise RuntimeError('Package checksum failure: '+n)

def safe_child(root,rel):
    p=(Path(root)/rel).resolve()
    if not p.is_relative_to(Path(root).resolve()):raise RuntimeError('Receipt path escapes its stage')
    return p

def authenticate_assembly(project,work):
    auth=work/'authentication';snaps=[]
    rp=project/'derived/replication_36m/receipt_iv_cohort_assembly_v100_PRIVATE/READY_FOR_CENSOR_AND_IV_SPECIFICATION_PRIVATE.json'
    ready=load(rp);snaps.append(snap(rp))
    if ready.get('status')!='COHORT_ASSEMBLED_CENSOR_AND_ESTIMATION_GATES_OPEN':
        raise RuntimeError('The completed cohort assembly is required')
    if ready.get('account_policy')!=ACCOUNT_POLICY:
        raise RuntimeError('Author-inclusive account policy changed')
    mp=relocated(ready['manifest'],project);dp=mp.parent/'_DONE.json'
    snaps.extend([checked(mp,ready['manifest_receipt'],auth),checked(dp,ready['assembly_receipt'],auth)])
    manifest=load(mp);done=load(dp)
    if manifest.get('code_signature')!=ASSEMBLY_CODE or manifest.get('account_policy')!=ACCOUNT_POLICY:
        raise RuntimeError('Reviewed assembly producer or account policy differs')
    if any(manifest.get(k) is not None for k in ('mechanics_censor','final_iv_eligible_n','new_IV_estimate')):
        raise RuntimeError('Expected the reviewed pre-estimation assembly')
    pin=load(AUTH/'assembly_SUMMARY.json')
    for k in ('known_main_rows','first_pair_rows','calendar_primary_rows_before_mechanics',
              'common5_10_rows_before_mechanics','primary_rows_with_missing_recipient_RD'):
        if done['result'].get(k)!=pin[k]:raise RuntimeError('Reviewed count changed: '+k)
    me=[r for r in done['files'] if r['path']==mp.name]
    if len(me)!=1 or me[0]['sha256']!=sha(mp):raise RuntimeError('Assembly receipt does not bind its manifest')
    paths=[relocated(p,project).resolve() for p in manifest['analysis_paths']]
    if len(paths)!=16 or len(set(paths))!=16:raise RuntimeError('Expected 16 distinct analysis shards')
    refs={relocated(r['path'],project).resolve():r for r in manifest['receipts']}
    for p in paths:
        dp=p.parent/'_DONE.json'
        if dp not in refs:raise RuntimeError('Analysis shard lacks its parent receipt')
        snaps.append(checked(dp,refs[dp],auth));d=load(dp)
        rows=[r for r in d['files'] if safe_child(dp.parent,r['path'])==p]
        if len(rows)!=1:raise RuntimeError('Analysis shard is not uniquely receipted')
        snaps.append(checked(p,rows[0],auth))
    if sum(pq.ParquetFile(p).metadata.num_rows for p in paths)!=18754435:
        raise RuntimeError('Reviewed first-pair cohort row count differs')
    return dict(paths=list(map(str,paths)),manifest=str(mp),snapshots=snaps,
                authority='Reviewed producer/counts plus local READY receipt chain; the public result did not independently pin private READY bytes.')

def authenticate_states(project,work):
    auth=work/'authentication';snaps=[];targets=[];cps=[]
    records=load(AUTH/'replay_receipts.json')
    if len(records)!=15 or {(r['contract']['month'],r['contract']['speed']) for r in records}!={(m,s) for m in POST_MONTHS for s in SPEEDS}:
        raise RuntimeError('Replay authority does not cover all 15 speed-months')
    for r in records:
        a=r['outputs']['targets'];p=relocated(a['path'],project)
        snaps.append(checked(p,a,auth))
        if pq.ParquetFile(p).metadata.num_rows!=a['rows']:raise RuntimeError('Target-state row count changed')
        targets.append(dict(path=str(p),month=r['contract']['month'],speed=r['contract']['speed']))
    cp_authority=load(AUTH/'checkpoint_authority.json')['checkpoints']['2023-10']
    for s in SPEEDS:
        a=cp_authority[s];p=relocated(a['metadata_relative_path'],project).with_suffix('.parquet')
        snaps.append(checked(p,{'sha256':a['checkpoint_parquet_sha256']},auth))
        if not {'user_id','games_seen'}<=columns(p):raise RuntimeError('Established-history checkpoint schema changed')
        cps.append(dict(path=str(p),speed=s))
    return dict(targets=targets,checkpoints=cps,snapshots=snaps,
                authority='Exact replay target and October 2023 checkpoint hashes from reviewed color package.')
