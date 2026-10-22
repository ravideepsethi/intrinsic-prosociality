"""Consume the pinned completed products. No repair, replay or API fallback."""
from __future__ import annotations
import csv
from common import *

AUTH=PACKAGE/'authority'
FIRST='derived/replication_36m/color_change_firstpass_v100'
CACHE='derived/replication_36m/receipt_iv_extension_v100'
STAGE07='derived/replication/analysis_panel_24m_sf100k'

def verify_package():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,name=line.split('  ',1)
        p=PACKAGE/name
        if not p.resolve().is_relative_to(PACKAGE.resolve()) or sha(p)!=h:
            raise RuntimeError('Package integrity failure: '+name)

def record_file(project, rec, auth_root):
    return checked(relocated(rec['path'],project),rec,auth_root,Path(project)/CACHE)

def anchors(project, month, auth_root):
    """Recompute the v103 key; missing caches never trigger their old producer."""
    reuse=next(r for r in load(AUTH/'monthly_reuse.json') if r['month']==month)
    folder=Path(project)/CACHE/'monthly'/month/reuse['key']
    rp=folder/'complete.json'
    snapshots=[checked(rp,dict(sha256=reuse['complete_sha256']),auth_root)]
    old=load(rp)
    if old['key']!=reuse['key']:raise RuntimeError('Monthly cache key mismatch')
    paths=old['result']['anchor_files']
    if month in ('2025-11','2025-12','2026-02'):
        d=next(x for x in load(AUTH/'diagnostic_reuse.json') if x['kind']=='timing' and x['month']==month)
        # These are exact v103 inputs. Reject changed metadata rather than guessing a new key.
        inputs=[stamp(relocated(x,project)) for x in paths]+[stamp(relocated(d['private']['path'],project))]
        key=v103_digest(dict(code=load(AUTH/'pins.json')['v103_code_signature'],diagnostic=d,monthly=old['result'],inputs=inputs))
        dest=Path(project)/CACHE/'cached_finalizer_v103/timing'/month/key
        rp=dest/'complete.json'
        r=load(rp)
        if r['key']!=key or r['inputs']!=inputs:raise RuntimeError('Finalized timing cache identity mismatch')
        expected_audit=load(AUTH/'timing'/month/'timestamp_finalization.json')
        if r['result']['audit']!=expected_audit:raise RuntimeError('Finalized timing disagrees with reviewed result')
        listed={x['name']:x['sha256'] for x in r['public_files']}
        if listed.get('timestamp_finalization.json')!=sha(AUTH/'timing'/month/'timestamp_finalization.json'):
            raise RuntimeError('Finalized timing audit hash mismatch')
        for x in r['public_files']:
            if sha(dest/x['name'])!=x['sha256']:raise RuntimeError('Finalized timing public artifact mismatch')
        old=r;paths=r['result']['monthly']['anchor_files']
        snapshots.append(checked(rp,dict(sha256=sha(rp)),auth_root))
    listed={a['path']:a for a in old['artifacts']}
    if not set(paths)<=set(listed):raise RuntimeError('Unreceipted anchor path')
    for p in paths:snapshots.append(record_file(project,listed[p],auth_root))
    return [str(relocated(p,project)) for p in paths],snapshots

def old_histories(project,auth_root):
    a=load(AUTH/'prior_authority.json')
    p=Path(project)/'derived/replication/comparison_tests_v110_PRIVATE'/a['comparison_run']/'lineage_PRIVATE.json'
    snapshots=[checked(p,dict(sha256=a['comparison_lineage_sha256']),auth_root)]
    line=load(p);records=[]
    for shard,parts in enumerate(line['projections']):
        for r in parts:
            s=record_file(project,r,auth_root);snapshots.append(s)
            pf=pq.ParquetFile(s['path'])
            if pf.metadata.num_rows!=int(r['rows']):raise RuntimeError('Historical projection row count changed')
            required={'j','i','t','start','ord','gid','y','arm','fair','rt','cell'}
            if not required<=set(pf.schema_arrow.names):raise RuntimeError('Historical projection schema changed')
            records.append(dict(month=r['month'],shard=shard,path=s['path'],sha256=s['sha256'],bytes=s['bytes'],rows=int(r['rows'])))
    if len(records)!=384 or {(r['month'],r['shard']) for r in records}!={(m,s) for m in OLD_MONTHS for s in range(16)}:
        raise RuntimeError('Historical projection coverage differs')
    if sum(r['rows'] for r in records)!=47587020:raise RuntimeError('Historical projection total differs')
    return records,snapshots

def pilot_deltas(project,auth_root):
    a=load(AUTH/'prior_authority.json')
    root=Path(project)/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/a['iv_run']
    success=load(root/'_SUCCESS.json')
    if success.get('config_sha256')!=a['iv_config_sha256'] or success.get('report_zip_sha256')!=a['iv_report_sha256']:
        raise RuntimeError('Historical pilot reference authority differs')
    records=[];snapshots=[]
    for month in OLD_MONTHS:
        d=root/'projection'/('month='+month);p=d/'_COMPLETE.json';r=load(p)
        if r.get('config_sha256')!=a['iv_config_sha256']:raise RuntimeError('Pilot delta configuration differs')
        entries=[x for x in r['files'] if x['path']=='reference_deltas.npz']
        if len(entries)!=1:raise RuntimeError('Missing or ambiguous reference delta receipt')
        e=entries[0];s=checked(d/e['path'],e,auth_root)
        snapshots.extend([checked(p,dict(sha256=sha(p)),auth_root),s]);records.append(s)
    return records,snapshots

def canonical_sources(project,month,auth_root):
    replay=load(AUTH/'replay_receipts.json')
    hits=[r for r in replay if r['contract']['month']==month]
    if hits:
        if {r['contract']['speed'] for r in hits}!=set(SPEEDS) or len(hits)!=5:
            raise RuntimeError('Incomplete pinned replay target set')
        records=[]
        for r in hits:
            x=r['outputs']['targets'];s=record_file(project,x,auth_root)
            if pq.ParquetFile(s['path']).metadata.num_rows!=int(x['rows']):raise RuntimeError('Replay target count differs')
            records.append(dict(**s,speed=r['contract']['speed'],rows=int(x['rows']),mode='completed_replay_targets'))
        return records
    # Narrow identity/order projection of five known completed chronology files.
    # No rating state is updated. Full byte hashes are newly recorded for these inputs.
    records=[]
    for r in load(AUTH/'chronology_metadata.json'):
        if r['month']!=month:continue
        root=relocated(r['path'],project);paths=sorted(root.glob('*.parquet'))
        if len(paths)!=r['parts'] or sum(pq.ParquetFile(p).metadata.num_rows for p in paths)!=r['rows']:
            raise RuntimeError('Chronology metadata changed: '+month+'/'+r['speed'])
        for p in paths:
            s=observed_binding(p,auth_root)
            records.append(dict(**s,speed=r['speed'],rows=pq.ParquetFile(p).metadata.num_rows,mode='new_narrow_identity_order_scan'))
    if {r['speed'] for r in records}!=set(SPEEDS):raise RuntimeError('Missing chronology speeds')
    return records

def month_job(project,month,auth_root,work,memory_mb,bridge=False):
    rec=next(r for r in load(AUTH/'normalized_sources.json') if r['month']==month)
    base=record_file(project,rec['output'],auth_root)
    anchor_paths,anchor_inputs=anchors(project,month,auth_root)
    # Stockfish projections omit the time controls and chooser-win arm. Recover
    # them from the already authenticated Stage05/Stage07 or historical panel,
    # not from the reduced Stockfish files and not by inferring wins from !draw.
    source=[]
    for r in load(AUTH/'history_feature_sources.json'):
        if r['month']==month:source.append(record_file(project,r,auth_root))
    if not source:raise RuntimeError('Missing authenticated source panels')
    identity=[] if bridge else canonical_sources(project,month,auth_root)
    inputs=[base,*anchor_inputs,*source,*identity]
    return dict(month=month,base=base['path'],anchor_paths=anchor_paths,source_paths=[r['path'] for r in source],
        identity=identity,inputs=inputs,expected_rows=int(rec['output']['rows']),bridge=bridge,
        arm_adapter='october_api_winner' if month=='2023-10' else 'stored_timeout_chooser_win',
        work=str(work),memory_mb=memory_mb,auth_root=str(auth_root),n_users=load(AUTH/'pins.json')['n_users'])

def historical_iv(project,auth_root):
    authority=load(AUTH/'reviewed_iv.json')
    e=next(x for x in authority['files'] if x['path']=='spaced90.parquet')
    p=Path(project)/'derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet'
    r=checked(p,e,auth_root,Path(project)/CACHE)
    if pq.ParquetFile(p).metadata.num_rows!=2682330:raise RuntimeError('Historical IV benchmark count changed')
    return dict(status='HISTORICAL_ANALYSIS_BYTES_UNCHANGED',rows=2682330,sha256=r['sha256']),r
