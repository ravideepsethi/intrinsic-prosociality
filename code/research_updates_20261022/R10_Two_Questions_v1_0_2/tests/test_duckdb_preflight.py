#!/usr/bin/env python3
"""Exercise *actual* DuckDB and Parquet syntax before touching the 41.5m rows.

Uses a private, temporary 24-month fixture with the input field names and types,
including nullable clocks and all stage, position, and speed categories. Contains
no Lichess data. No API, internet, external drive writes or source modification.
"""
from __future__ import annotations
import tempfile, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import r10
from r10_math import MONTHS, SPEED, model_indices


def main():
    stages=[2,5,7,9,15,30,60,90]
    evals=[-500,-200,0,150,350]
    rows=[]
    for month_i,month in enumerate(MONTHS):
        for pos,v in enumerate(evals):
            for stage_idx,ply in enumerate(stages):
                j=month_i*40+pos*8+stage_idx
                rows.append({
                    'chooser_user_id':f'account_{j%29:02d}',
                    'outcome_kind_draw':int(j%13==0),
                    'engine_eval_cp_disconnected':v,
                    'ply_count':ply,
                    'api_speed':SPEED[(month_i+pos+stage_idx)%5],
                    'month':month,
                    'chooser_win_premium_v2':4.0+(j%8),
                    'chooser_pre_rd_v2':35.0+(j%17),
                    'disconnected_pre_rd_v2':40.0+(j%21),
                    'chooser_clock_last_obs_s':None if j%11==0 else float(4+j%300),
                    'disconnected_clock_last_obs_s':float(5+j%300),
                    'chooser_elo':float(1200+j%700),
                    'disconnected_elo':float(1220+j%750),
                })
    data=pd.DataFrame(rows)
    counts={
        'opportunities':len(data),
        'grants':int(data.outcome_kind_draw.sum()),
        'competitive':int((data.engine_eval_cp_disconnected>=-100).sum()),
        'competitive_grants':int(data.loc[data.engine_eval_cp_disconnected>=-100,'outcome_kind_draw'].sum()),
        'clearly_worse':int((data.engine_eval_cp_disconnected<=-300).sum()),
        'clearly_worse_grants':int(data.loc[data.engine_eval_cp_disconnected<=-300,'outcome_kind_draw'].sum()),
        'choosers':int(data.chooser_user_id.nunique()),
    }
    with tempfile.TemporaryDirectory(prefix='r10_duckdb_sql_smoke_') as td:
        temp=Path(td)
        file=temp/'synthetic.parquet'
        pq.write_table(pa.Table.from_pandas(data,preserve_index=False),file,compression='zstd')
        root=temp/'run'
        (root/'public').mkdir(parents=True)
        (root/'private').mkdir(parents=True)
        c=r10.connect(root,2,4)
        original=r10.EXPECTED
        try:
            r10.EXPECTED=counts
            aliases=r10.main_view(c,[file])
            assert aliases['chooser']=='chooser_user_id'
            result=r10.preflight(c,root)
            assert result['n_months']==24 and result['invalid_rows']==0
            assert result['opportunities']==len(data)
            desc=r10.descriptives(c,root)
            assert int(desc['pos_n'].sum())==len(data)
            assert int(desc['stage_n'].sum())==len(data)
            files=r10.prepare_buckets(c,root,4,('chooser','grant','pos','stage','speed_i','month_i','kappa',
                   'rd_chooser','rd_opponent','clock_chooser','clock_opponent','gap'))
            assert len(files)==4 and all(f.exists() for f in files)
            count=grants=accounts=0
            pay={}
            for n in (1,2,3,4):
                ix,names=model_indices(n)
                pay[n]={'ix':ix,'labels':names,'beta':np.zeros(len(ix))}
            for i,f in enumerate(files):
                _,xx,xy,N,G,W,grant=r10.pass_one_task((i,f,37))
                assert xx.shape==(85,85) and xy.shape==(85,)
                count+=N;grants+=grant;accounts+=G
                _,meat,zsum,sum_xw,N2,G2=r10.pass_two_task((i,f,37,pay))
                assert (N,G)==(N2,G2)
                assert meat[2].shape==(len(pay[2]['ix'])+13,)*2
                assert meat[3].shape==(len(pay[3]['ix'])+20,)*2
                assert meat[4].shape==(len(pay[4]['ix'])+50,)*2
            assert count==len(data) and accounts==counts['choosers'] and grants==counts['grants']
        finally:
            r10.EXPECTED=original
            c.close()
    print('PASS R10 DuckDB SQL preflight, Parquet input, synthetic 24-month sample,')
    print('     descriptive query, partitioned bucket COPY/sort, chooser passes 1 and 2',flush=True)

if __name__=='__main__':main()
