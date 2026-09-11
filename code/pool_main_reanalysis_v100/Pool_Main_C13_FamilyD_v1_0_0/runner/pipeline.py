"""Rebuild C13 denominators before opening its new ambient numerators."""
from __future__ import annotations
import hashlib
from pathlib import Path
import tempfile
import time
import os
import pyarrow.parquet as pq
from runner import common,models


def preserve_incomplete(state):
    pairs=[('c13_fair_base_private.parquet','c13_fair_base_receipt.json'),
           ('c13_denominator_support_private.parquet','c13_denominator_support_frozen.json'),
           ('c13_kind_events_private.parquet','c13_kind_events_receipt.json'),
           ('c13_model_private.parquet','c13_model_receipt.json')]
    for prefix in ('denominator','kind'):
        for group in ('cell','chooser_cell','speed','chooser_speed'):
            pairs.append((f'c13_daily_{prefix}_{group}_private.parquet',f'c13_daily_{prefix}_{group}_receipt.json'))
    moved=[]
    for data,receipt in pairs:
        a,b=state/data,state/receipt
        if a.exists()!=b.exists():
            stash=state/'interrupted_checkpoints';stash.mkdir(parents=True,exist_ok=True)
            dest=Path(tempfile.mkdtemp(prefix='preserved_',dir=stash))
            for path in (a,b):
                if path.exists(): os.replace(path,dest/path.name)
            moved.append({'data':data,'receipt':receipt,'preserved_at':str(dest)})
    return moved


def validate_support(c13,state,digest,support):
    path=state/'c13_denominator_support_private.parquet'
    if support.get('config_sha256')!=digest or support.get('ambient_kindness_numerator_read') is not False:
        raise RuntimeError('C13 support was not frozen under this configuration')
    if support.get('output_sha256')!=common.sha256_file(path) or support['rows']!=c13.EXPECTED_FAIR_ROWS:
        raise RuntimeError('C13 frozen support binding failed')
    if support['support_threshold_other_fair_opportunities']!=c13.SUPPORT_THRESHOLD:
        raise RuntimeError('C13 support threshold changed')
    cols=pq.ParquetFile(path).schema_arrow.names
    if any('ambient' in name or 'kind' in name for name in cols):
        raise RuntimeError('Outcome field in denominator-only cache')
    return {'status':'C13_NEW_SAMPLE_SUPPORT_FROZEN_BEFORE_AMBIENT_NUMERATOR',
            'config_sha256':digest,'support_receipt_sha256':common.sha256_file(state/'c13_denominator_support_frozen.json'),
            'support_cache_sha256':support['output_sha256'],'primary_supported_rows':support['primary_supported_rows'],
            'new_sample_support_rebuilt':True,'old_sample_support_count_enforced':False,
            'threshold_other_fair_opportunities':c13.SUPPORT_THRESHOLD}


def execute(c13,stage_paths,state,public,digest,threads,memory):
    state.mkdir(parents=True,exist_ok=True);public.mkdir(parents=True,exist_ok=True)
    recovered=preserve_incomplete(state)
    common.atomic_json(public/'INTERRUPTED_CHECKPOINTS.json',{'preserved':recovered})
    def log(s): print('['+common.utc_now()+'] '+s,flush=True)
    kwargs={'state':state,'threads':threads,'memory_limit':memory,'config_sha256':digest}
    log('C13_BUILD_DENOMINATOR_BASE')
    base,base_receipt=c13.build_base(stage07_paths=stage_paths,**kwargs)
    log('C13_BUILD_DAILY_DENOMINATORS')
    daily=c13.build_daily_denominators(base=base,**kwargs)
    log('C13_BUILD_AND_FREEZE_SUPPORT')
    support_cache,support=c13.build_support_cache(base=base,daily=daily,**kwargs)
    gate=validate_support(c13,state,digest,support)
    gate_path=state/'C13_SUPPORT_GATE.json'
    if gate_path.exists() and common.load_json(gate_path)!=gate:
        raise RuntimeError('Frozen support gate changed on restart')
    common.atomic_json(gate_path,gate)
    common.atomic_json(public/'C13_SUPPORT_GATE.json',gate)
    common.atomic_json(public/'c13_support_frozen.json',support)
    c13.common.write_csv(public/'c13_support_by_cell.csv',support['support_by_cell'])
    log(f"C13_SUPPORT_READY supported={support['primary_supported_rows']:,} thin={support['primary_thin_excluded_rows']:,}")
    # The first numerator read is deliberately below the durable support gate.
    common.atomic_json(state/'NUMERATOR_READ_AUTHORIZATION.json',{
        'config_sha256':digest,'support_gate_sha256':common.sha256_file(gate_path),
        'authorized_after_new_support_freeze':True})
    log('C13_BUILD_FAIR_KINDNESS_NUMERATOR')
    kind=c13.build_kind_events(base=base,stage07_paths=stage_paths,**kwargs)
    log('C13_BUILD_DAILY_KINDNESS_COUNTS')
    daily_kind=c13.build_daily_kind(kind_events=kind,**kwargs)
    log('C13_BUILD_LAGGED_LEAVE_CHOOSER_OUT_MODEL_CACHE')
    model=c13.build_model_cache(support=support_cache,kind_events=kind,daily_kind=daily_kind,**kwargs)
    model_receipt=common.load_json(state/'c13_model_receipt.json')
    for name in ('c13_fair_base_receipt.json','c13_kind_events_receipt.json','c13_model_receipt.json'):
        common.atomic_json(public/name,common.load_json(state/name))
    log('C13_ESTIMATION_PRIMARY_AND_QUARTILES_FIRST')
    result,checkpoint_info=models.estimate(c13,model,state/'model_checkpoints',digest,model_receipt['output_sha256'])
    common.atomic_json(public/'c13_results.json',result)
    common.atomic_json(public/'MODEL_CHECKPOINTS.json',checkpoint_info)
    for filename,key in [('c13_models.csv','models'),('c13_model_attempts.csv','model_attempts'),
                         ('c13_adjusted_quartile_model.csv','quartile_model'),('c13_descriptive_quartiles.csv','descriptive_quartiles')]:
        if result[key]: c13.common.write_csv(public/filename,result[key])
    return {'result_status':result['status'],'primary_estimable':result['primary_estimable'],
            'primary':result['primary'],'model_attempts_total':result['model_attempts_total'],
            'models_estimated':result['models_estimated'],'retained_model_failures':result['retained_model_failures'],
            'extended_absorption_successes':result['extended_absorption_successes'],
            'primary_supported_rows':support['primary_supported_rows']}
