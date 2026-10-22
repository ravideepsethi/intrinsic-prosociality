#!/usr/bin/env python3
"""Regression test: missing rare classical early-stage support must not kill R10."""
from pathlib import Path
import sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_synthetic import frame_synthetic
import numpy as np
import pandas as pd
import r10
from r10_math import (construct_design,chooser_crossproducts,chooser_within,
    model_indices,stage_vector,estimable_linear)


def one_case(remove_early):
    df=frame_synthetic()
    # Remove one (or two) exact interaction cells, preserving original
    # chooser IDs and all other parts of the frozen design.
    excluded=[1] if not remove_early else [0,1]
    df=df.loc[~((df.speed_i==4)&df.stage.isin(excluded))].reset_index(drop=True)
    assert not ((df.speed_i==4)&(df.stage==1)).any()
    X,y=construct_design(df)
    xx,xy,G,W=chooser_crossproducts(X,y,df.chooser.to_numpy())
    models=r10.compute_models(xx,xy)
    mod=models[4]
    assert mod['rank_info']['rank']<len(mod['labels'])
    l=mod['labels'];idinfo=mod['identification'];p=len(l)
    zero_interaction=np.zeros(p);zero_interaction[l.index('stage_5_6_X_classical')]=1
    assert not estimable_linear(zero_interaction,idinfo)[0]
    rebound=stage_vector(4,4,7,l)-stage_vector(4,4,6,l)
    assert estimable_linear(rebound,idinfo)[0], 'Classical 81+ vs 41–80 is estimable'
    rise=stage_vector(4,4,6,l)
    if remove_early:assert not estimable_linear(rise,idinfo)[0], 'Classical lacks 0–4 reference'
    # Unidentified effects must be NULL, not guessed from the pseudoinverse.
    row=r10.report_row(4,'classical','stage_5_6_minus_0_4',
                       stage_vector(4,4,1,l),mod['beta'],
                       np.eye(p),identification=idinfo)
    assert row['status']=='NOT_ESTIMABLE' and row['estimate_pp'] is None
    raterow=r10.report_row(4,'classical','81plus minus 41_80',
                           rebound,mod['beta'],np.eye(p),identification=idinfo)
    assert raterow['status']=='ESTIMATED' and np.isfinite(raterow['estimate_pp'])
    # Compare predictions on observed design to direct within-account LS.
    xw,yw,_,_,counts,starts,acc=chooser_within(X,y,df.chooser.to_numpy())
    direct=np.linalg.lstsq(xw[:,mod['ix']],yw,rcond=1e-10)[0]
    p1=xw[:,mod['ix']]@direct
    p2=xw[:,mod['ix']]@mod['beta']
    assert np.max(np.abs(p1-p2))<2e-6
    payload={k:{'ix':v['ix'],'labels':v['labels'],'beta':v['beta']} for k,v in models.items()}
    saved=r10.account_batches
    try:
        r10.account_batches=lambda *args:iter([df])
        _,meats,zsums,sums_xw,N,G2=r10.pass_two_task((0,'testfixture',4096,payload))
    finally:r10.account_batches=saved
    assert N==len(df) and G2==G
    pos=df.pos.to_numpy(dtype=int);st=df.stage.to_numpy(dtype=int);sp=df.speed_i.to_numpy(dtype=int)
    regions=(pos>=2).astype(int)
    des={'pos_n':np.bincount(pos,minlength=5),
         'stage_n':np.bincount(st,minlength=8),
         'region_stage_n':np.bincount(regions*8+st,minlength=16).reshape(2,8),
         'speed_stage_n':np.bincount(sp*8+st,minlength=40).reshape(5,8)}
    oldgrants=r10.EXPECTED['grants'];r10.EXPECTED['grants']=int(df.grant.sum())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'public').mkdir()
            summary=r10.generate_tables(root,models,meats,zsums,sums_xw,des,G,N,W)
            d=pd.read_csv(root/'public'/'R10_panel_D_speed_stage.csv')
            z=d[(d.group=='classical')&(d.estimand=='stage_5_6 minus 0_4')]
            assert len(z)==1 and z.iloc[0]['status']=='NOT_ESTIMABLE'
            assert pd.isna(z.iloc[0]['estimate_pp'])
            f=d[(d.group=='classical')&(d.estimand=='81plus minus 41_80')]
            assert len(f)==1 and f.iloc[0]['status']=='ESTIMATED'
            if remove_early:
                q=d[(d.group=='classical')&(d.estimand=='41_80 minus 0_4')]
                assert len(q)==1 and q.iloc[0]['status']=='NOT_ESTIMABLE'
            out=pd.read_csv(root/'public'/'R10_nonidentification_audit.csv')
            assert 'stage_5_6_X_classical' in set(out.nonestimable_term)
            assert len(summary['metadata'])==4
    finally:r10.EXPECTED['grants']=oldgrants
    print('PASS rank-aware R10 with absent classical stages',excluded)

if __name__=='__main__':
    one_case(False)
    one_case(True)
    print('ALL UNIDENTIFIED CLASSICAL INTERACTION TESTS PASSED')
