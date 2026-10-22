"""Consume the completed state attachment and the pinned historical cohort."""
from common import *
import design

AUTH = PACKAGE/'authority'
ACCOUNT_POLICY = load(AUTH/'reviewed_state_ACCOUNT_POLICY.json')
STATE_CODE = '401f6a9d6e99b7e62be8087555392e1699a7d0f54e4bd732f4e868cf78d5e322'
HISTORICAL_RELATIVE = 'derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet'
HISTORICAL_SHA = '3bc55d83f113cd7c5942348b16ae9ff5e940ae8aad13f9db3d99a6a526ef250c'
HISTORICAL_BYTES = 295180899

def snap(p): return dict(**receipt(p),fingerprint=stamp(p))

def verify_package():
    expected=set()
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,n=line.split('  ',1);p=(PACKAGE/n).resolve();expected.add(n)
        if not p.is_relative_to(PACKAGE.resolve()) or sha(p)!=h:
            raise RuntimeError('Package checksum failure: '+n)
    for d in ('code','vendor'):
        if any(str(p.relative_to(PACKAGE)) not in expected for p in (PACKAGE/d).glob('*.py')):
            raise RuntimeError('Unmanifested executable module')
    if load(PACKAGE/'DESIGN_FREEZE.json')!=clean(design.freeze()):
        raise RuntimeError('Design code and freeze disagree')

def safe_child(root,rel):
    p=(Path(root)/rel).resolve()
    if not p.is_relative_to(Path(root).resolve()):raise RuntimeError('Receipt path escapes its stage')
    return p

def authenticate(project,work):
    auth=work/'authentication';snaps=[]
    rp=project/'derived/replication_36m/receipt_iv_state_diagnostics_v100_PRIVATE/READY_FOR_IV_SPECIFICATION_PRIVATE.json'
    ready=load(rp);snaps.append(snap(rp))
    if ready.get('status')!='STATES_ATTACHED_AND_CUTOFF_DIAGNOSTICS_COMPLETE' or ready.get('account_policy')!=ACCOUNT_POLICY:
        raise RuntimeError('Completed author-inclusive state diagnostics are required')
    mp=relocated(ready['manifest'],project).resolve()
    snaps.append(checked(mp,ready['manifest_receipt'],auth));m=load(mp)
    if m.get('code_signature')!=STATE_CODE or m.get('account_policy')!=ACCOUNT_POLICY:
        raise RuntimeError('State-attachment producer or account policy changed')
    if any(m.get(k) is not None for k in ('mechanics_censor','final_iv_eligible_n','new_IV_estimate')):
        raise RuntimeError('Expected the reviewed pre-estimation state manifest')
    paths=[relocated(p,project).resolve() for p in m['analysis_paths']]
    if len(paths)!=16 or len(set(paths))!=16:raise RuntimeError('Expected 16 distinct enriched shards')
    refs={relocated(r['path'],project).resolve():r for r in m['receipts']}
    for p in paths:
        dp=p.parent/'_DONE.json'
        if dp not in refs:raise RuntimeError('Enriched shard lacks its receipt')
        snaps.append(checked(dp,refs[dp],auth));done=load(dp)
        records=[r for r in done['files'] if safe_child(dp.parent,r['path'])==p]
        if len(records)!=1:raise RuntimeError('Enriched shard is not uniquely receipted')
        snaps.append(checked(p,records[0],auth))
    if sum(pq.ParquetFile(p).metadata.num_rows for p in paths)!=design.EXPECTED['first_pair']:
        raise RuntimeError('Enriched first-pair row count differs')
    dp=relocated(m['diagnostics_root'],project)/'_DONE.json'
    snaps.append(checked(dp,m['diagnostics_receipt'],auth));ds=load(dp)
    summary=load(AUTH/'reviewed_state_SUMMARY.json')
    for k in ('status','first_pair_rows','calendar_primary_rows','calendar_common5_10_rows',
              'primary_RD_rows_restored','primary_missing_RD_rows','primary_nonreachers_retained'):
        if ds['result'].get(k)!=summary[k]:raise RuntimeError('Reviewed diagnostics count changed: '+k)
    # The returned diagnostic CSV is pinned independently of the local receipt chain.
    dname='CUTOFF_SAMPLE_COUNTS.csv';cp=dp.parent/dname
    wanted=sha(AUTH/('reviewed_state_'+dname))
    snaps.append(checked(cp,dict(sha256=wanted),auth))
    hp=project/HISTORICAL_RELATIVE
    snaps.append(checked(hp,dict(sha256=HISTORICAL_SHA,bytes=HISTORICAL_BYTES),auth))
    if pq.ParquetFile(hp).metadata.num_rows!=design.EXPECTED['historical']:
        raise RuntimeError('Historical primary row count differs')
    return dict(paths=list(map(str,paths)),historical_path=str(hp),snapshots=snaps,
        state_manifest=str(mp),authority='Reviewed producer/counts and local READY receipt chain; exact public cutoff table and exact historical cohort SHA.')
