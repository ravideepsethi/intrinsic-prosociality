"""Small adapter around unchanged, reviewed R7/R8 producers."""
from pathlib import Path
import os, sys
for _k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[_k]='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor_r8/code'))
sys.path.insert(0,str(ROOT/'vendor_r8/vendor_r7/code'))
import r8_util as u
import r7_common as r
import r7_models as models
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from preliminary_core import STARTS, DAY
VERSION='1.0.0'

def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1)
        p=(ROOT/name).resolve()
        u.require(p.is_relative_to(ROOT), 'Unsafe manifest member')
        u.require(u.sha(p)==digest,'Package bytes changed: '+name)

def bind(project,explicit=None):
    root,paths,binding=u.bind_r7(project,explicit)
    e=binding['environment']['config']['binding']
    ref=Path(project)/'derived/replication/run2_feature_cache_v1_PRIVATE/reference'/e['reference_conf']/'models'
    r.env_common.checked_stage_files(ref,e['reference_conf'],['clean.npy'])
    model=np.load(ref/'clean.npy',allow_pickle=False,mmap_mode='r')
    u.require(model.shape==(2,24,4,4,500),'Unexpected monthly reference dimensions')
    parts=[dict(v,path=str(u.relocate(v['path'],project))) for v in e['source']['parts']]
    u.require(len(parts)==384 and sum(v['rows'] for v in parts)==47587020,'Historical donor contract differs')
    u.require(len({v['path'] for v in parts})==384,'Duplicate donor path')
    for s in range(16):
        rows=[v for v in parts if v['shard']==s]
        u.require(len(rows)==24 and len({v['month'] for v in rows})==24,'Incomplete donor shard')
    return paths,binding,parts,ref/'clean.npy'

def fit(input_path,output,conf,variant,selection='all',level='X0',scores=None,material=None):
    deps=[input_path]+([scores] if scores else [])+([material] if material else [])
    def build(tmp):
        d=r.load_fit_columns(input_path)
        mask=np.ones(len(d['row_id']),bool)
        if material:
            a=r.arrays(r.io.read(material))
            u.require(np.array_equal(d['row_id'],a['row_id']),'Material row order differs')
            mask &= a['material_valid']
            if selection=='neutral':mask &= a['material_neutral']
        if scores:
            a=r.arrays(r.io.read(scores))
            u.require(np.array_equal(d['row_id'],a['row_id']),'Score row order differs')
            u.require(np.all(a['n_24h']>=5) and np.isfinite(a['adjusted_24h']).all(),'New history unsupported on frozen rows')
            if variant=='lag24h':
                # X0 history controls deliberately remain the archived values.
                d['adjusted_7d']=a['adjusted_24h']
        d=r.subset(d,mask)
        label=variant+'__'+selection+'__'+level
        result,_=models.estimate(d,'iv',label,level,part_a=False,calibration=False,release_inputs=True)
        for rows in result.values():
            for row in rows:
                row.update(history_cutoff=variant,exposure_screen=selection,
                    nuisance_reference='frozen_author_clean_monthly_lag7',controls_timing='frozen_R7',
                    expanded_exposure_cohort=False,material_screen_changes_donor_history=False)
        r.io.js(tmp/'result.json',result)
        return dict(n=len(d['row_id']),variant=variant,selection=selection,level=level)
    return r.stable_stage(Path(output),conf,build,deps)

def fit_job(job):
    r.threads_one();u.no_network()
    return fit(**job)[1]
