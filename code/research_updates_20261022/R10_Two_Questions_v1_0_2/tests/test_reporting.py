#!/usr/bin/env python3
"""Full R10 reporting and covariance calculator on wholly synthetic accounts."""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
import pandas as pd
import r10
from r10_math import model_indices,construct_design,solve_gram,solve_gram_rank_aware,chooser_within
from test_synthetic import frame_synthetic

def run_reporting():
    df=frame_synthetic();x,y=construct_design(df)
    xw,yw,_,_,counts,_,_=chooser_within(x,y,df.chooser.to_numpy())
    models={}
    for m in (1,2,3,4):
        idx,labs=model_indices(m)
        S=xw[:,idx].T@xw[:,idx]
        beta,inv,info,identity=solve_gram_rank_aware(S,xw[:,idx].T@yw)
        models[m]={'ix':idx,'labels':labs,'beta':beta,'bread':inv,'omitted':[],
                   'min_eig':info['smallest_identified_scaled_eigenvalue'],
                   'rank_info':info,'identification':identity}
    payload={m:{'ix':models[m]['ix'],'labels':models[m]['labels'],'beta':models[m]['beta']} for m in models}
    old=r10.account_batches
    try:
        r10.account_batches=lambda *args:iter([df])
        _,meat,zsum,sums_xw,N,G=r10.pass_two_task((0,'dummy',32768,payload))
    finally:r10.account_batches=old
    pos=df.pos.to_numpy();stage=df.stage.to_numpy();speed=df.speed_i.to_numpy()
    region=(pos>=2).astype(int)
    pstage=np.bincount(region*8+stage,minlength=16).reshape(2,8).astype(float)
    sstage=np.bincount(speed*8+stage,minlength=40).reshape(5,8).astype(float)
    des={'pos_n':np.bincount(pos,minlength=5).astype(float),
        'stage_n':np.bincount(stage,minlength=8).astype(float),
        'region_stage_n':pstage,'speed_stage_n':sstage}
    o=r10.EXPECTED['grants'];r10.EXPECTED['grants']=int(df.grant.sum())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'public').mkdir()
            W=int(counts[counts>=2].sum())
            summary=r10.generate_tables(root,models,meat,zsum,sums_xw,des,G,N,W)
            for name in ('R10_panel_A_positions.csv','R10_panel_B_stage.csv',
                'R10_panel_C_region_stage.csv','R10_panel_D_speed_stage.csv',
                'R10_adjusted_rates.csv','R10_MAIN_REGRESSION_TABLE.tex'):
                assert (root/'public'/name).exists(),name
            pA=pd.read_csv(root/'public'/'R10_panel_A_positions.csv')
            pB=pd.read_csv(root/'public'/'R10_panel_B_stage.csv')
            C=pd.read_csv(root/'public'/'R10_panel_C_region_stage.csv')
            D=pd.read_csv(root/'public'/'R10_panel_D_speed_stage.csv')
            assert len(pA)==4*7,len(pA)
            assert len(pB)==4*13,len(pB)
            assert len(C)==2*(7+3)+2,len(C)
            assert len(D)==5*(7+3)+4*2+2,len(D)
            assert pA.holm_p_7.between(0,1).all()
            assert pB.holm_p_13.between(0,1).all()
            assert C.se_pp.ge(0).all() and D.se_pp.ge(0).all()
            tex=(root/'public'/'R10_MAIN_REGRESSION_TABLE.tex').read_text()
            assert r'\begin{table}' in tex and r'\end{table}' in tex
    finally:r10.EXPECTED['grants']=o
    print('PASS full synthetic reporting: 4 models, A/B/C/D contrasts, CIs, Holm, LaTeX')

if __name__=='__main__':run_reporting()
