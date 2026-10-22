#!/usr/bin/env python3
"""Pure NumPy numerical tests; no private inputs or extra packages."""
import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
import pandas as pd
from r10_math import (STAGE,SPEED,POSITION,MONTHS,construct_design,chooser_crossproducts,
    chooser_within,identified,solve_gram,model_indices,stage_vector,position_vector,contrast,holm)
from r10 import adjusted_rate_results

rng=np.random.default_rng(110025)


def frame_synthetic():
    # Make every stage/speed/position sufficiently supported and include chooser singletons.
    nacc=76
    sizes=rng.integers(11,29,nacc)
    sizes[:3]=1
    acc=np.repeat([f'account_{i:03}' for i in range(nacc)],sizes)
    n=len(acc)
    pos=rng.integers(0,5,n,dtype=np.int8)
    stage=rng.integers(0,8,n,dtype=np.int8)
    speed=rng.integers(0,5,n,dtype=np.int8)
    month=rng.integers(0,24,n,dtype=np.int8)
    kappa=np.exp(rng.normal(2.5,.55,n))
    rd1=np.exp(rng.normal(3.5,.5,n));rd2=np.exp(rng.normal(3.5,.5,n))
    gap=rng.normal(0,350,n)
    c1=rng.uniform(0,100,n);c2=rng.uniform(0,100,n)
    c1[rng.choice(n,13,replace=False)]=np.nan
    c2[rng.choice(n,10,replace=False)]=np.nan
    df=pd.DataFrame(dict(chooser=acc,grant=rng.binomial(1,.075,n),pos=pos,stage=stage,
       speed_i=speed,month_i=month,kappa=kappa,rd_chooser=rd1,rd_opponent=rd2,
       clock_chooser=c1,clock_opponent=c2,gap=gap))
    return df


def numeric_checks():
    df=frame_synthetic();x,y=construct_design(df);ids=df.chooser.to_numpy()
    xx,xy,G,within=chooser_crossproducts(x,y,ids)
    xw,yw,_,_,_,_,_=chooser_within(x,y,ids)
    assert np.max(np.abs(xx-xw.T@xw))<1e-8
    assert np.max(np.abs(xy-xw.T@yw))<1e-8
    assert within == sum(n for n in df.groupby('chooser').size() if n>=2)
    # Explicit account FE equivalence by least-squares on small artificial data.
    users=pd.factorize(df.chooser)[0]
    dummy=(users[:,None]==np.arange(G)[None,:]).astype(float)
    for m in (1,2,3,4):
        idx,labs=model_indices(m)
        b,inv,mineig=solve_gram(xx[np.ix_(idx,idx)],xy[idx])
        direct=np.linalg.lstsq(np.column_stack([x[:,idx],dummy]),y,rcond=1e-11)[0][:len(idx)]
        err=float(np.max(np.abs(b-direct)))
        assert err<2e-6,(m,err)
        print('PASS within chooser FE == dense dummy OLS, model',m,'max_error',err)
    # Distinguish conditional profiles from baseline interactions.
    _,lab3=model_indices(3)
    assert abs(sum(stage_vector(3,1,7,lab3))-2)<1e-12
    assert abs(sum(stage_vector(3,0,7,lab3))-1)<1e-12
    _,lab4=model_indices(4)
    assert abs(sum(stage_vector(4,3,6,lab4))-2)<1e-12
    assert abs(sum(stage_vector(4,0,6,lab4))-1)<1e-12
    p=[.01,.0001,.4]
    assert list(np.argsort(holm(p)))==list(np.argsort(p))
    print('PASS stage-region and stage-speed contrast encoding and Holm monotonicity')
    # Validate account-clustered covariance against explicitly grouped score outer products.
    ix,labs=model_indices(2)
    xm=xw[:,ix]
    b,inv,_=solve_gram(xx[np.ix_(ix,ix)],xy[ix])
    err=yw-xm@b
    starts=np.r_[0,1+np.flatnonzero(ids[1:]!=ids[:-1])]
    scores=np.add.reduceat(xm*err[:,None],starts,axis=0)
    meat=scores.T@scores
    cov=(G/(G-1))*inv@meat@inv
    L=position_vector(4,labs)-position_vector(3,labs)
    est,se,_,_,_=contrast(b,cov,L)
    assert se>0 and np.isfinite(est)
    print('PASS clustered covariance and focal position contrast',round(est,4),round(se,4))
    # Using exact cluster moment construction, verify adjusted rate equals brute force
    # account-intercept predictions when changing stage/position across all rows.
    n=len(y);p2=len(ix)
    z=np.column_stack([scores,np.add.reduceat(y,starts),np.diff(np.r_[starts,n])])
    pos=df.pos.to_numpy(dtype=int);st=df.stage.to_numpy(dtype=int)
    groupid=np.repeat(np.arange(G),np.diff(np.r_[starts,n]))
    posct=np.bincount(groupid*4+np.maximum(0,pos-1),weights=(pos>0),minlength=G*4).reshape(G,4)
    stct=np.bincount(groupid*7+np.maximum(0,st-1),weights=(st>0),minlength=G*7).reshape(G,7)
    z=np.column_stack([z,posct,stct])
    meta={'id':2,'beta':b,'bread':inv,'labels':labs,'zsum':z.sum(axis=0),'mu_y':y.mean()}
    des={'pos_n':np.bincount(pos,minlength=5).astype(float),
         'stage_n':np.bincount(st,minlength=8).astype(float)}
    rates,lookup=adjusted_rate_results(meta,des,z.T@z,G)
    for kind,j in [('stage',0),('stage',6),('position',1),('position',4)]:
        vv=position_vector if kind=='position' else lambda k,lab:stage_vector(2,0,k,lab)
        eff=np.asarray([vv(int(k),labs)@b for k in (pos if kind=='position' else st)])
        desired=float(vv(j,labs)@b)
        brute=float(y.mean()+desired-eff.mean())
        assert abs(lookup[kind,j]['T']-brute)<1e-8,(kind,j,lookup[kind,j]['T'],brute)
    print('PASS standardized adjusted rates reproduce counterfactual direct averages')

if __name__=='__main__':numeric_checks();print('ALL R10 NUMERIC SYNTHETIC TESTS PASSED')
