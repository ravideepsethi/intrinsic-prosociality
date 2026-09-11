"""Checkpoint the unchanged C13 model family, prioritizing the two paper rows."""
from __future__ import annotations
import gc
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from runner import common


def validate_result(rows,attempt,label):
    if attempt['model']!=label or not isinstance(attempt['numerical_estimate_emitted'],bool):
        raise RuntimeError('Model checkpoint label/status mismatch')
    if bool(rows)!=attempt['numerical_estimate_emitted']:
        raise RuntimeError('Model estimate/status inconsistency')
    for row in rows:
        if row['model']!=label or row['causal_claim'] is not False or row['epistemic_label']!='X':
            raise RuntimeError('Model interpretation changed')
        for field in ('coefficient','standard_error','p_value_two_sided'):
            if not math.isfinite(row[field]): raise RuntimeError('Nonfinite model result: '+field)
        if row['standard_error']<0 or not 0<=row['p_value_two_sided']<=1:
            raise RuntimeError('Invalid model inference')


class ModelCheckpoints:
    def __init__(self,c13,directory,digest,model_sha):
        self.original=c13._attempt_model
        self.directory=directory;directory.mkdir(parents=True,exist_ok=True)
        self.digest=digest;self.model_sha=model_sha
        self.reused=0;self.new=0

    def __call__(self,**kwargs):
        label=kwargs['label']
        if not label.replace('_','').isalnum(): raise RuntimeError('Invalid model label')
        request={'config_sha256':self.digest,'model_cache_sha256':self.model_sha,'label':label,
                 'role':kwargs['analysis_role'],'terms':list(kwargs['exposures']),
                 'requested_rows':int(np.count_nonzero(kwargs['sample']))}
        path=self.directory/(label+'.json')
        if path.exists():
            saved=common.load_json(path)
            if saved['request']!=request: raise RuntimeError('Model restart request differs: '+label)
            content={'rows':saved['rows'],'attempt':saved['attempt']}
            if hashlib.sha256(common.canonical_json(content).encode()).hexdigest()!=saved['result_sha256']:
                raise RuntimeError('Model checkpoint content hash mismatch: '+label)
            validate_result(saved['rows'],saved['attempt'],label)
            self.reused+=1
            print('C13_MODEL_REUSED '+label,flush=True)
            return saved['rows'],saved['attempt']
        started=time.monotonic()
        rows,attempt=self.original(**kwargs)
        validate_result(rows,attempt,label)
        content={'rows':rows,'attempt':attempt}
        saved={**content,'request':request,'elapsed_seconds':time.monotonic()-started,
               'created_utc':common.utc_now(),
               'result_sha256':hashlib.sha256(common.canonical_json(content).encode()).hexdigest()}
        common.atomic_json(path,saved);self.new+=1
        return rows,attempt


def estimate(c13,model_cache,directory,digest,model_sha):
    data=c13._load_model(model_cache)
    cached=ModelCheckpoints(c13,directory,digest,model_sha)
    original_attempt=c13._attempt_model;original_load=c13._load_model
    c13._attempt_model=cached
    c13._load_model=lambda path:data
    try:
        # Same samples, exposures and helper as the frozen estimate(); only order differs.
        sample=(data['cell_other_n28']>=c13.SUPPORT_THRESHOLD)&np.isfinite(data['ambient_cell_28'])
        rate=data['ambient_cell_28']
        cached(data=data,sample=sample,exposures={'ambient_kindness_percentage_points':100.0*rate},
               label='C13_primary_cell_28d',analysis_role='primary')
        if not np.any(sample):
            raise RuntimeError('No C13 primary supported rows; primary failure checkpoint retained')
        edges=np.quantile(rate[sample],[.25,.5,.75])
        quartile=np.zeros(data['kind'].size,dtype=np.int8)
        quartile[sample]=np.searchsorted(edges,rate[sample],side='right')+1
        cached(data=data,sample=sample,
               exposures={f'ambient_quartile_{value}_vs_1':(quartile==value).astype(float) for value in (2,3,4)},
               label='C13_primary_adjusted_ambient_quartiles',analysis_role='planned_sensitivity')
        del sample,rate,edges,quartile
        gc.collect()
        result=c13.estimate(model_cache)
    finally:
        c13._attempt_model=original_attempt;c13._load_model=original_load
    if result['model_attempts_total']!=19:
        raise RuntimeError('The frozen 19-model C13 family changed')
    return result,{'new_models':cached.new,'checkpoint_reads':cached.reused,'frozen_model_attempts':19,
                   'primary_and_adjusted_quartiles_attempted_first':True}
