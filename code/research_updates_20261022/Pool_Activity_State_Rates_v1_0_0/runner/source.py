from __future__ import annotations
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .common import load_json,sha256_file,canonical_json

FIELDS=['chooser','n','f','l','k','a','b']


def load_census(private,reference,threads=8):
    private=Path(private)
    census=private/'chooser_counts_private.parquet'
    receipt=private/'chooser_counts_receipt.json'
    contract_path=private/'CONTRACT.json'
    for p in (census,receipt,contract_path):
        if not p.is_file():raise RuntimeError('Verified chooser-support cache is missing: '+str(p))
    contract=load_json(contract_path)
    if contract!=reference['source_contract']:raise RuntimeError('Source census contract differs from returned support audit')
    payload={k:v for k,v in contract.items() if k!='sha256'}
    if hashlib.sha256(canonical_json(payload).encode()).hexdigest()!=contract['sha256']:
        raise RuntimeError('Source contract digest is invalid')
    saved=load_json(receipt)
    digest=sha256_file(census)
    if saved.get('contract')!=contract['sha256'] or saved.get('sha256')!=digest:
        raise RuntimeError('Source census receipt/checksum mismatch')
    before={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in (census,receipt,contract_path)}
    pa.set_cpu_count(threads);pa.set_io_thread_count(threads)
    table=pq.ParquetFile(census).read(columns=FIELDS,use_threads=True)
    frame=table.to_pandas();del table
    if list(frame.columns)!=FIELDS or frame.isna().any().any():raise RuntimeError('Census columns or null checks failed')
    if any(not pd.api.types.is_integer_dtype(frame[c]) for c in FIELDS):raise RuntimeError('Census must contain integer IDs and counts')
    if frame.chooser.duplicated().any():raise RuntimeError('Duplicate chooser in source census')
    if (frame[FIELDS[1:]]<0).any().any() or (frame.n<=0).any():raise RuntimeError('Negative counts or empty chooser')
    if ((frame.f+frame.l>frame.n)|(frame.a>frame.f)|(frame.b>frame.l)|(frame.k>frame.n)|
        (frame.a+frame.b>frame.k)|(frame.k-frame.a-frame.b>frame.n-frame.f-frame.l)).any():
        raise RuntimeError('Inconsistent source sufficient statistics')
    lineage=dict(source_census_machine_path=str(census),source_census_sha256=digest,
                 source_contract_sha256=contract['sha256'],sample_fingerprint=contract['sample_fingerprint'],
                 upstream_report=reference['upstream_return_archive'],upstream_report_sha256=reference['upstream_return_sha256'],
                 reused_existing_private_census=True,raw_panel_rescanned=False)
    return frame,lineage,before


def verify_baseline(frame,authority,reference):
    from .statistics import inputs
    n,both,w,_,d=inputs(frame)
    counts=dict(rows=int(frame.n.sum()),choosers=len(frame),kind_draws=int(frame.k.sum()),
                fair_rows=int(frame.f.sum()),fair_kind_draws=int(frame.a.sum()),
                fair_choosers=int((frame.f>0).sum()),fair_kind_choosers=int((frame.a>0).sum()))
    for name,value in counts.items():
        if value!=authority[name]:raise RuntimeError('Sample-authority count mismatch: '+name)
    support=reference['current_support']
    actual=dict(choosers_seen_in_both_states=int(both.sum()),contrast_choosers=int((n>0).sum()),
                contrast_rows=int(n.sum()),contrast_singleton_choosers=int((n==1).sum()),
                opportunities_from_both_state_choosers=int(n[both].sum()),
                state_varying_choosers_with_no_grant_in_contrast=int((both&((frame.a+frame.b).to_numpy()==0)).sum()))
    for name,value in actual.items():
        if value!=support[name]:raise RuntimeError('Returned support count mismatch: '+name)
    weights=w[both]
    beta=float(np.average(d,weights=weights))
    G=actual['contrast_choosers'];N=actual['contrast_rows']
    q=G/(G-1)*(N-1)/(N-G-1)
    score=weights*(d-beta)
    se=float(np.sqrt(q*(score@score)/(weights.sum()**2)))
    expected=reference['current_minimal_reference']
    if abs(100*beta-expected['reproduced_estimate_pp'])>1e-8 or abs(100*se-expected['reproduced_se_pp'])>1e-8:
        raise RuntimeError('Original FE coefficient or as-reported clustered SE did not reproduce')
    if not np.isclose(weights.sum(),support['identifying_weight_sum'],rtol=1e-12,atol=1e-7):
        raise RuntimeError('Identifying-weight sum mismatch')
    zero=(frame.a.to_numpy()[both]+frame.b.to_numpy()[both])==0
    if abs(float(weights[zero].sum()/weights.sum())-support['share_identifying_weight_no_grant_in_contrast'])>1e-10:
        raise RuntimeError('Nongranter identifying-weight share mismatch')
    return dict(status='CURRENT_SUPPORT_AND_FE_REFERENCE_REPRODUCED',counts=counts,support_counts=actual,
                estimate_pp=100*beta,as_reported_se_pp=100*se,as_reported_finite_sample_correction=q,
                equal_chooser_sample_keeps_all_observed_nongranters=True)


def verify_unchanged(before):
    for name,expected in before.items():
        p=Path(name)
        if (p.stat().st_size,p.stat().st_mtime_ns)!=expected:raise RuntimeError('Source census changed during run: '+name)
