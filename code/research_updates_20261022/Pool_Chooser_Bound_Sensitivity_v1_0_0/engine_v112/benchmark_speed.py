#!/usr/bin/env python3
"""Reproducible synthetic speed measurement; never an empirical result.

Run with the same Python environment as RUN_FOLLOWUP.command. The timed loop
excludes first-use Numba compilation. This compares arithmetic, not storage
or multiprocess throughput, and is not a guaranteed full-job speedup.
"""
import os
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMBA_NUM_THREADS']:
    os.environ[key]='1'
import bootstrap_path
import argparse,json,time
from dataclasses import asdict
import numpy as np
from fixture import fixture
from prepare import encode,subset
from model import Model as ReferenceModel,CORE,fit as reference_fit
from engine import fit as fast_fit
from fast_static import FastStaticModel


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-fits',action='store_true')
    args=parser.parse_args()
    arrays,meta=encode(fixture(100,100,36),1)
    d=subset(arrays['development'],arrays['development']['period']<2)
    rng=np.random.default_rng(91);rows=[]
    def tile(factor):
        out={k:np.tile(v,(factor,1) if v.ndim==2 else factor) for k,v in d.items() if k not in ['ptr','ids']}
        out['ids']=np.tile(d['ids'],factor)+np.repeat(np.arange(factor)*(len(d['ptr'])-1),len(d['y']))
        out['ptr']=np.r_[0,np.cumsum(np.tile(np.diff(d['ptr']),factor))]
        return out
    for name in ['desert','both','type_cells']:
        spec=next(s for s in CORE if s.name==name)
        for weighted in [False,True]:
            big=tile(100)
            if weighted:
                N=len(big['ptr'])-1;big['aw']=rng.multinomial(N,np.ones(N)/N).astype(float)
            slow=ReferenceModel(spec,6,meta);fast=FastStaticModel(spec,6,meta);v=slow.start(13)
            times=[]
            for model in [slow,fast]:
                model.objective(v,big,.001)
                samples=[]
                for _ in range(7):
                    t=time.monotonic();model.objective(v,big,.001);samples.append(time.monotonic()-t)
                times.append(float(np.median(samples)))
            a,g=slow.objective(v,big,.001);b,h=fast.objective(v,big,.001)
            np.testing.assert_allclose(a,b,rtol=1e-10,atol=1e-10)
            np.testing.assert_allclose(g,h,rtol=1e-10,atol=1e-10)
            row=dict(kind='objective',model=name,opportunities=len(big['y']),J=6,weighted=weighted,
                reference_seconds=times[0],compiled_seconds=times[1],ratio=times[0]/times[1],
                objective_difference=abs(a-b),max_gradient_difference=float(np.max(abs(g-h))))
            rows.append(row);print(json.dumps(row),flush=True)
    if args.full_fits:
        # Distinct generated accounts give a nondegenerate fit comparison.
        arrays,meta=encode(fixture(750,100,48,seed=87),1)
        train=subset(arrays['development'],arrays['development']['period']<2)
        N=len(train['ptr'])-1;train['aw']=rng.multinomial(N,np.ones(N)/N).astype(float)
        for name in ['desert','both']:
            spec=next(s for s in CORE if s.name==name);runs=[]
            for fn in [reference_fit,fast_fit]:runs.append(fn(train,spec,3,meta,17,maxiter=1200,ridge=.001))
            a,b=runs
            row=dict(kind='full_fit',model=name,opportunities=len(train['y']),J=3,
                reference_seconds=a['elapsed_seconds'],compiled_seconds=b['elapsed_seconds'],
                ratio=a['elapsed_seconds']/b['elapsed_seconds'],reference_success=a['success'],
                compiled_success=b['success'],objective_difference=abs(a['objective']-b['objective']),
                iterations=[a['iterations'],b['iterations']])
            rows.append(row);print(json.dumps(row),flush=True)
    return rows


if __name__=='__main__':main()
