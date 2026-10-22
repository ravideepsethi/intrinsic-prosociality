"""Bounded, read-only check of the recovered portable download location."""
from __future__ import annotations
import sqlite3
from common import *

CONFIG='628dfb8f80a89dd04d287b40326c408ae13c20e4bd4eabb7bec71b03b697d37f'
STEM='CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_628dfb8f80a8_PRIVATE'

def inspect(desktop):
    desktop=Path(desktop);root=desktop/STEM;p=root/'checkpoint.sqlite3'
    out=dict(root=str(root),checkpoint_exists=p.is_file(),network_requests=0,
        download_completion_certified=False,used_for_estimation=False)
    for name in ['CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_REPORT_628dfb8f80a8.zip',
                 'CHOOSER_COMPARISON_EXPANSION_RETURN_628dfb8f80a8_PRIVATE.zip']:
        q=desktop/name;out[name]=dict(exists=q.is_file(),bytes=q.stat().st_size if q.is_file() else None)
    if not p.is_file():
        out.update(status='CHECKPOINT_NOT_AT_THIS_DESKTOP',interpretation='This does not establish absence on another laptop; no collection is started.')
        return out
    required=['inputs/TRANSFER.json','inputs/DESIGN_FREEZE.json','inputs/INPUT_MANIFEST.json']
    if not all((root/n).is_file() for n in required):
        return dict(out,status='CHECKPOINT_INPUT_BINDING_INCOMPLETE')
    transfer=load(root/required[0]);freeze=load(root/required[1]);manifest=load(root/required[2])
    if any(x.get('config_sha256')!=CONFIG for x in [transfer,freeze,manifest]):
        return dict(out,status='CHECKPOINT_CONFIG_MISMATCH')
    entries={x['path']:x for x in manifest.get('files',[])}
    if not {'targets.parquet','TRANSFER.json','DESIGN_FREEZE.json'}<=set(entries):
        return dict(out,status='CHECKPOINT_INPUT_MANIFEST_INCOMPLETE')
    for name in ['TRANSFER.json','DESIGN_FREEZE.json']:
        if sha(root/'inputs'/name)!=entries[name]['sha256']:return dict(out,status='CHECKPOINT_INPUT_HASH_MISMATCH')
    with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        meta=dict(db.execute('SELECT key,value FROM meta').fetchall())
        if meta.get('config_sha256')!=CONFIG or meta.get('target_sha256')!=entries['targets.parquet']['sha256']:
            return dict(out,status='CHECKPOINT_TARGET_BINDING_MISMATCH')
        count,requested,returned,flagged,first,last=db.execute('SELECT count(*),coalesce(sum(requested),0),coalesce(sum(returned),0),coalesce(sum(flagged),0),min(batch),max(batch) FROM batches').fetchone()
        responses=db.execute('SELECT count(*) FROM responses').fetchone()[0]
    out.update(status='BOUND_CHECKPOINT_COUNTS_READ',completed_batches=count,requested_in_completed_batches=requested,
        returned_in_completed_batches=returned,flagged_in_completed_batches=flagged,
        expected_target_rows=int(transfer['target_rows']),saved_response_records=responses,
        completed_batch_indices_contiguous=(count==0 or (first==0 and last==count-1)),
        all_target_count_accounted=(requested==int(transfer['target_rows'])),
        interpretation='Counts are a snapshot. Response hashes and per-batch target bindings were not audited; this is not certification of a completed random comparison sample.')
    return out
