#!/usr/bin/env python3
"""Test three-group/ five-speed standardized predictions and IF moment algebra."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from r10_math import (model_indices,stage_vector,chooser_within,construct_design,solve_gram,solve_gram_rank_aware)
import r10
from test_synthetic import frame_synthetic


def run_test():
    frame=frame_synthetic();X,y=construct_design(frame)
    Xw,yw,xbar,ybar,counts,starts,acc=chooser_within(X,y,frame.chooser.to_numpy())
    models={}
    for m in (1,2,3,4):
        ii,labs=model_indices(m)
        XX=Xw[:,ii].T@Xw[:,ii]
        XY=Xw[:,ii].T@yw
        beta,bread,info,identity=solve_gram_rank_aware(XX,XY)
        models[m]={'ix':ii,'labels':labs,'beta':beta,'bread':bread,'id':m,'identification':identity}
    # Monkeypatch the data generator to exercise pass_two_task without filesystem.
    old=r10.account_batches
    try:
        r10.account_batches=lambda *args:iter([frame])
        payload={m:{'ix':models[m]['ix'],'labels':models[m]['labels'],'beta':models[m]['beta']} for m in models}
        b,MM,SS,SX,N,G=r10.pass_two_task((0,'synthetic.parquet',4096,payload))
    finally:r10.account_batches=old
    assert N==len(y) and G==len(counts)
    region=(frame.pos.to_numpy()>=2).astype(int)
    speed=frame.speed_i.to_numpy(dtype=int)
    stage=frame.stage.to_numpy(dtype=int)
    for m in (3,4):
        groups=region if m==3 else speed
        ng=2 if m==3 else 5
        group_st=np.zeros((ng,8),float)
        for g,s in zip(groups,stage):group_st[g,s]+=1
        mod=models[m];mod['zsum']=SS[m];mod['sum_xw']=SX[m]
        des={'region_stage_n':group_st,'speed_stage_n':group_st}
        rates,look=r10.adjusted_rate_results(mod,des,MM[m],G)
        ii=mod['ix'];beta=mod['beta'];labs=mod['labels']
        fit=ybar[acc]+Xw[:,ii]@beta
        for g in range(ng):
            for s in range(8):
                allst=np.array([float(stage_vector(m,g,int(k),labs)@beta) for k in stage])
                counter=float(stage_vector(m,g,s,labs)@beta)
                brute=float((fit+(counter-allst))[groups==g].mean())
                v=look[g,s]['T']
                assert abs(v-brute)<1e-8,(m,g,s,v,brute)
                assert np.isfinite(look[g,s]['se'])
        print('PASS group-stage adjusted-rate IF moments for model',m,'with',ng,'groups')
    # All score columns sum to zero globally up to round-off; rank gate can fail only for focal.
    for m in models:
        p=len(models[m]['beta'])
        assert np.max(np.abs(SS[m][:p]))<1e-6
    print('PASS chooser-score moment sums and complete-group accounting')

if __name__=='__main__':run_test();print('ALL GROUP-MOMENT SYNTHETIC TESTS PASSED')
