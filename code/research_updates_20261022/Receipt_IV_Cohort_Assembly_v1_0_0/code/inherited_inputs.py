"""Read completed histories and pinned old membership; never rebuild them."""
from common import *

AUTH=PACKAGE/'authority'
HISTORY='derived/replication_36m/receipt_iv_history_extension_v100_PRIVATE'

def verify_package():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,n=line.split('  ',1);p=PACKAGE/n
        if not p.resolve().is_relative_to(PACKAGE.resolve()) or sha(p)!=h:
            raise RuntimeError('Package checksum failure: '+n)

def authenticated_stage(root,auth,expected_receipt=None):
    root=Path(root)
    if expected_receipt:
        possible=[root/n for n in ('_DONE.json','_SUCCESS.json','complete.json') if (root/n).is_file()]
        possible=[p for p in possible if sha(p)==expected_receipt]
        if len(possible)!=1:raise RuntimeError('Pinned completed-stage receipt not found: '+str(root))
        rp=possible[0]
    else:rp=root/'_DONE.json'
    snap=checked(rp,dict(sha256=expected_receipt or sha(rp)),auth)
    r=load(rp);out=[]
    for e in r['files']:
        rel=e.get('path',e.get('relative_path'))
        if not rel:raise RuntimeError('Receipt entry lacks a relative path')
        p=(root/rel).resolve()
        if not p.is_relative_to(root.resolve()):raise RuntimeError('Receipt path escapes its stage')
        out.append(checked(p,e,auth))
    return r,[snap,*out]

def history(project,auth):
    base=Path(project)/HISTORY;pins=load(AUTH/'pins.json')
    rp=base/'READY_FOR_COHORT_EXTENSION.json';ready=load(rp)
    cp=base/'INPUT_CONTRACT_PRIVATE.json';contract=load(cp)
    if ready['status']!='ALL_SOURCE_IV_HISTORIES_AND_REFERENCES_READY' or contract['code_signature']!=pins['history_code_signature']:
        raise RuntimeError('Successful reviewed history extension is required')
    if sha(cp)!=ready['input_contract_sha256']:raise RuntimeError('History input contract changed')
    for field,filename in [('historical_projection_bridge','HISTORICAL_PROJECTION_BRIDGE.json'),
          ('reference_bridge','REFERENCE_BRIDGE.json'),('identity_check','IDENTITY_NAMESPACE_CHECK.json')]:
        if ready[field]!=load(AUTH/'reviewed_history'/filename):raise RuntimeError('History review bridge differs: '+field)
    snaps=[checked(rp,dict(sha256=sha(rp)),auth),checked(cp,dict(sha256=sha(cp)),auth)]
    opportunities={};stage_receipts={}
    for m in ready['new_month_products']:
        root=relocated(m['root'],project)
        checked(root/'_DONE.json',m['receipt'],auth)
        done,ss=authenticated_stage(root,auth);snaps+=ss
        if done['result']['rows']!=m['result']['rows']:raise RuntimeError('History stage count differs')
        opportunities[m['month']]=str(root/'opportunities_PRIVATE.parquet');stage_receipts[m['month']]=ss[0]
    if set(opportunities)!=set(NEW_MONTHS):raise RuntimeError('Added history months incomplete')
    if sum(pq.ParquetFile(p).metadata.num_rows for p in opportunities.values())!=pins['expected_new_history_rows']:
        raise RuntimeError('Added history row total differs')
    roots=[p.parent for p in (base/'months/2023-11').glob('*/_DONE.json')]
    candidates=[]
    for root in roots:
        r=load(root/'_DONE.json')
        if r.get('key')==digest(dict(code=pins['history_code_signature'],month='2023-11',inputs=r.get('inputs'),bridge=True)):
            candidates.append(root)
    if len(candidates)!=1:raise RuntimeError('Reviewed November history bridge is missing or ambiguous')
    br,ss=authenticated_stage(candidates[0],auth);snaps+=ss
    if br['result']['rows']!=pins['expected_bridge_rows']:raise RuntimeError('November bridge row count differs')
    opportunities['2023-11']=str(candidates[0]/'opportunities_PRIVATE.parquet')
    reference=relocated(ready['reference_root'],project)
    rr,ss=authenticated_stage(reference,auth);snaps+=ss
    manifest=load(reference/'HISTORY_INPUT_MANIFEST_PRIVATE.json');records=[]
    for rec in manifest['records']:
        p=relocated(rec['path'],project)
        # Reuse a previous byte check only with the exact immutable fingerprint.
        local=base/'authentication'/(digest(str(p.resolve()))+'.json')
        cached=load(local) if local.is_file() else None
        if cached and cached.get('fingerprint')==stamp(p) and cached.get('sha256')==rec['sha256']:
            write_json(Path(auth)/(digest(str(p.resolve()))+'.json'),cached)
        s=checked(p,rec,auth);snaps.append(s);records.append(dict(rec,path=str(p)))
    if len(records)!=512 or {(r['month'],r['shard']) for r in records}!={(m,s) for m in MONTHS for s in range(16)}:
        raise RuntimeError('512-shard history manifest differs')
    if sum(r['rows'] for r in records)!=pins['expected_all_history_rows']:raise RuntimeError('History total differs')
    return dict(opportunities=opportunities,reference=str(reference/'reference_extended_boundary.npy'),
        records=records,snapshots=snaps,authority='Reviewed counts/code plus local receipt chain; public ZIP does not independently pin READY bytes')

def old_membership(project,auth):
    report=load(AUTH/'main_sample_report.json');root=relocated(report['private_output_root'],project)
    er=next(x for x in report['stages'] if x['relative_path']=='eligibility')
    done,snaps=authenticated_stage(root/'eligibility',auth,er['receipt_sha256'])
    eligibility=[r['path'] for r in snaps[1:] if r['path'].endswith('.parquet')]
    if not eligibility or sum(pq.ParquetFile(p).metadata.num_rows for p in eligibility)!=47587020:
        raise RuntimeError('Pinned 24-month eligibility coverage differs')
    if any(not {'game_id','source','previous_classification_status'}<=columns(p) for p in eligibility):
        raise RuntimeError('Original membership columns absent')
    panels=[]
    for r in report['panel_outputs']:
        p=root/r['relative_path'];s=checked(p,r,auth);snaps.append(s)
        if pq.ParquetFile(p).metadata.num_rows!=r['rows']:raise RuntimeError('Original main panel count changed')
        panels.append(dict(month=r['month'],path=str(p),**{k:r[k] for k in ('sha256','rows')}))
    if len(panels)!=24 or sum(r['rows'] for r in panels)!=41534331:raise RuntimeError('Original main panel coverage changed')
    return dict(eligibility=eligibility,panels=panels,snapshots=snaps)

def chronology(project,auth):
    records=[];prior=Path(project)/HISTORY/'authentication/observed_chronology'
    for r in load(AUTH/'chronology_metadata.json'):
        folder=relocated(r['path'],project);paths=sorted(folder.glob('*.parquet'))
        if len(paths)!=r['parts'] or sum(pq.ParquetFile(p).metadata.num_rows for p in paths)!=r['rows']:
            raise RuntimeError('Known chronology partition changed: '+r['month']+'/'+r['speed'])
        for p in paths:
            needed={'game_id','utc_ms','archive_ordinal','white_id','black_id'}
            if not needed<=columns(p):raise RuntimeError('Canonical start chronology columns absent')
            previous=prior/(digest(str(p.resolve()))+'.json')
            if previous.is_file():
                q=load(previous)
                if q.get('fingerprint')!=stamp(p):raise RuntimeError('Previously bound chronology fingerprint changed')
                dest=Path(auth)/'observed_chronology'/previous.name
                if not dest.exists():write_json(dest,q)
            # Binding is deferred to each checkpoint, avoiding a large startup hash pass.
            records.append(dict(path=str(p),month=r['month'],speed=r['speed'],rows=pq.ParquetFile(p).metadata.num_rows,
                fingerprint=stamp(p)))
    if sum(r['rows'] for r in records)!=2957732699:raise RuntimeError('32-month chronology total changed')
    # The original census globbed every speed in this canonical root. Do not
    # silently replace that scope with the five inventoried replay pools.
    known={Path(r['path']).resolve() for r in records}
    canonical=Path(project)/'derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time'
    observed={p.resolve() for m in MONTHS for p in canonical.glob('speed=*/month='+m+'/*.parquet')}
    extra=observed-known
    for p in sorted(extra):
        if not {'game_id','utc_ms','archive_ordinal','white_id','black_id'}<=columns(p):
            raise RuntimeError('Additional canonical speed partition lacks original chronology fields')
        records.append(dict(path=str(p),month=p.parent.name.split('=',1)[1],speed=p.parent.parent.name.split('=',1)[1],
            rows=pq.ParquetFile(p).metadata.num_rows,fingerprint=stamp(p),additional_canonical_speed_partition=True))
    if known-observed:raise RuntimeError('Inventoried chronology is absent from the original canonical scope')
    return records

def feature_sources(project,auth):
    out={};snaps=[]
    for r in load(AUTH/'history_feature_sources.json'):
        p=relocated(r['path'],project);s=checked(p,r,auth);snaps.append(s)
        out.setdefault(r['month'],[]).append(str(p))
    return out,snaps
