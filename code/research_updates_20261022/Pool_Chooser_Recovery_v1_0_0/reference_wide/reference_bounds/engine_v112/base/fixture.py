"""Synthetic designs for software checks, never evidence about the paper."""
import numpy as np
import pandas as pd
from scipy.special import expit
from prepare import START,VALID,SPLIT


def fixture(dev_accounts=120,eval_accounts=120,opportunities=36,seed=71):
    rng=np.random.default_rng(seed);rows=[]
    for i in range(dev_accounts+eval_accounts):
        kind=i%3;rating=[1450,1800,2200,2500][i%4]
        for j in range(opportunities):
            period=min(2,3*j//opportunities)
            c=int(rng.integers(100));board=c//20;stage=(c//5)%4;q=c%5
            b=[-650,-200,0,200,650][board]+rng.uniform(-30,30)
            premium=float(rng.uniform(3,15));E=(q+.5)/5;draw=2*premium*(.5-E)
            t=[START,VALID,SPLIT][period]+int((j+1)*86400000+i*1000)
            logit=-5.2+kind*.7+(.2+.4*kind)*board-.035*premium-.02*max(0,-draw)
            rows.append(dict(chooser=f'synthetic_{i:06d}',game_id=f'fixture_{i}_{j}',
              cohort='development' if i<dev_accounts else 'evaluation',t=t,start_ms=t-600000,
              month=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m'),
              y=int(rng.random()<expit(logit)),board=board,stage=stage,ply=[2,8,25,60][stage],
              rating=rating+rng.normal(0,30),opponent_rating=1800+rng.normal(0,200),
              speed='blitz' if i%2 else 'rapid',tc_base=300 if i%2 else 600,tc_inc=3.,
              color=j%2,premium=premium,draw_payoff=draw,win_payoff=draw+premium,
              crd=rng.uniform(40,100),drd=rng.uniform(40,100),cvol=.06,dvol=.06,
              cclock=rng.uniform(5,300),dclock=rng.uniform(5,300),
              b=b,b_raw=b,is_mate=False,score_type='cp',expected_score=E,loss=max(0,-draw),period=period))
    return pd.DataFrame(rows).sort_values(['chooser','t','game_id']).reset_index(drop=True)
