"""Independent atomic, authenticated checkpoints for C9 ply sensitivity batches."""
from __future__ import annotations
import os
import tempfile
import time
from pathlib import Path
import numpy as np
from runner import common, ply_engine as engine


def paths(state,start,stop):
    p = state/'randomizations'/f'c9_ply_{start:04d}_{stop-1:04d}.npz'
    return p,p.with_suffix('.json')


def validate_arrays(values,sims):
    expected = engine.blank_totals(sims)
    if set(values) != set(expected):
        raise RuntimeError('Checkpoint array names changed')
    for key,template in expected.items():
        a = values[key]
        if a.shape != template.shape or a.dtype != np.dtype('int64') or np.any(a < 0):
            raise RuntimeError('Invalid integer totals: '+key)
    for law in engine.LAWS:
        for rule in engine.RULES:
            prefix = law+'__'+rule+'__'
            for suffix in ('num','den'):
                if not np.array_equal(values[prefix+'same7_'+suffix]+values[prefix+'later7_'+suffix],values[prefix+'total7_'+suffix]):
                    raise RuntimeError('Ply partitions do not conserve totals')
            for category in ('same7','later7','total7'):
                if np.any(values[prefix+category+'_num'] > values[prefix+category+'_den']):
                    raise RuntimeError('Ply numerator exceeds denominator')
                if np.any(values[prefix+category+'_den'] > values[law+'__all__'+category+'_den']):
                    raise RuntimeError('Ply mask is not a subset of all opportunities')
            for category in ('same7','later7'):
                if np.any(values[prefix+category+'_users'] > values[prefix+'eligible_anchor_users']):
                    raise RuntimeError('Contributing chooser count exceeds eligible anchors')
    for category in ('same7','later7'):
        for suffix in ('num','den'):
            if not np.array_equal(values['original__all__'+category+'_'+suffix],values['baseline__'+category+'_'+suffix]):
                raise RuntimeError('Unrestricted mask differs from original C9')
    for suffix in ('num','den'):
        if not np.array_equal(values['original__all__total7_'+suffix],values['baseline__b2_'+suffix][:,2]):
            raise RuntimeError('Unrestricted seven-day mask differs from B2')


def authenticate(state,start,stop,digest):
    path,receipt = paths(state,start,stop)
    if not path.exists() and not receipt.exists():
        return None
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError('Incomplete ply checkpoint pair')
    saved = common.load_json(receipt)
    expected = {'status':'C9_PLY_BATCH_COMPLETE','config_sha256':digest,'start':start,'stop_exclusive':stop,
                'sha256':common.sha256_file(path),'bytes':path.stat().st_size,
                'original_and_B2_all_arrays_reproduced':True}
    for key,value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError('Ply checkpoint mismatch: '+key)
    with np.load(path,allow_pickle=False) as z:
        validate_arrays(dict(z),stop-start)
    return saved


def preserve_incomplete(state,draws=4999,batch=250):
    preserved = []
    root = state/'interrupted_checkpoints'
    root.mkdir(parents=True,exist_ok=True)
    for start in range(0,draws,batch):
        stop = min(start+batch,draws)
        path,receipt = paths(state,start,stop)
        if path.exists() != receipt.exists():
            dest = Path(tempfile.mkdtemp(prefix=f'batch_{start:04d}_',dir=root))
            for f in (path,receipt):
                if f.exists():
                    os.replace(f,dest/f.name)
            preserved.append({'start':start,'stop_exclusive':stop,'preserved_at':str(dest)})
    return preserved


def compare_reference(values,start,stop,references):
    original = Path(references['c9_state'])/'randomizations'/f'c9_{start:04d}_{stop-1:04d}.npz'
    b2 = Path(references['b2_state'])/'randomizations'/f'b2_{start:04d}_{stop-1:04d}.npz'
    with np.load(original,allow_pickle=False) as z:
        for name in z.files:
            if not np.array_equal(values['baseline__'+name],z[name]):
                raise RuntimeError(f'Original C9 draw reproduction failed: {start}:{stop} {name}')
    with np.load(b2,allow_pickle=False) as z:
        for name,key in [('numerators','num'),('denominators','den')]:
            if not np.array_equal(values['baseline__b2_'+key],z[name]):
                raise RuntimeError(f'B2 draw reproduction failed: {start}:{stop} {name}')


def worker(start,stop,state_text,digest,references):
    started = time.monotonic()
    state = Path(state_text)
    path,receipt = paths(state,start,stop)
    if path.exists() or receipt.exists():
        raise RuntimeError('Worker was sent an existing checkpoint')
    values = engine.simulate(start,stop)
    validate_arrays(values,stop-start)
    compare_reference(values,start,stop,references)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            np.savez_compressed(f,**values)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    saved = {'status':'C9_PLY_BATCH_COMPLETE','config_sha256':digest,'start':start,'stop_exclusive':stop,
             'sha256':common.sha256_file(path),'bytes':path.stat().st_size,'created_utc':common.utc_now(),
             'original_seed_components':[2026082201,start,stop],
             'conditioned_seed_components':[2026082201,*engine.STRATIFIED_SEED_TAG,start,stop],
             'original_and_B2_all_arrays_reproduced':True,'elapsed_seconds':time.monotonic()-started}
    common.atomic_json(receipt,saved)
    return saved
