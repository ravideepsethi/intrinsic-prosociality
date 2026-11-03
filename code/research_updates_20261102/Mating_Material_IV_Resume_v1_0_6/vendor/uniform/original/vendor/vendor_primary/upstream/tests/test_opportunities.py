import unittest,tempfile
import pandas as pd
import numpy as np
from pathlib import Path
from local_common import *
import opportunities as o

class OpportunityTests(unittest.TestCase):
    def test_source_sql_projection_and_restart(self):
        src=pd.DataFrame(dict(chooser_user_id=[1,2,1],outcome_kind_draw=[0,1,0],engine_eval_cp_disconnected=[-100,300,-300],
           ply_count=[4,40,81],sf100k_nodes_requested=[100000]*3,sf100k_fen_turn_matches_disconnected_color=[True]*3,
           disconnected_color=['white']*3,sf100k_disconnected_color_for_perspective=['white']*3,side_to_move_after_last=['white']*3,
           api_status=['timeout']*3,five_second_rule_passed=[True]*3,api_rated=[True]*3,api_variant=['standard']*3,
           api_speed=['bullet','blitz','rapid'],chooser_elo=[1500,2000,1800],disconnected_elo=[1600,1800,2000],
           chooser_clock_last_obs_s=[10.,20.,30.],disconnected_clock_last_obs_s=[10.,20.,30.],chooser_win_premium_v2=[6.]*3,
           chooser_pre_rd_v2=[60.]*3,disconnected_pre_rd_v2=[60.]*3,sf100k_stockfish_name=['fixture']*3,
           sf100k_stockfish_sha256=['0'*64]*3,sf100k_threads=[1]*3,sf100k_hash_mb=[16]*3,sf100k_eval_method=['uci_go_nodes']*3))
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);p=td/'source.parquet';out=td/'projection.parquet';src.to_parquet(p,index=False)
            job=dict(path=str(p),out=str(out),key='fixture',month='2023-11',sha=sha(p),rows=3)
            o.project_month(job);before=out.stat().st_mtime_ns;o.project_month(job);self.assertEqual(before,out.stat().st_mtime_ns)
            result=pd.read_parquet(out);np.testing.assert_array_equal(result.position,[2,4,0]);np.testing.assert_array_equal(result.stage,[0,5,7])
            np.testing.assert_array_equal(result.gap,[100,-200,200])

    def fixture(self):
        rng=np.random.default_rng(48);n=8000
        return pd.DataFrame(dict(chooser=np.repeat(np.arange(400),20),y=rng.binomial(1,.2,n),
             board=rng.choice([-400,-200,-75,-25,25,75,150,250,400,800],n),ply=rng.integers(0,110,n),
             position=rng.integers(0,5,n),stage=rng.integers(0,8,n),month_code=rng.integers(0,24,n),
             speed_code=rng.integers(1,5,n),gap=rng.integers(-800,801,n),chooser_rating=rng.integers(1000,2600,n),
             clock_c=rng.uniform(0,300,n),clock_d=rng.uniform(0,300,n),premium=rng.uniform(1,12,n),
             rd_c=rng.uniform(20,100,n),rd_d=rng.uniform(20,100,n),intensity=rng.integers(0,3,n)))

    def test_clocks_nested_in_r11(self):
        d=self.fixture();x,n,W,terms=o.clock_design(d);old,names,ix=o.frozen_design.design(d);old=old[:,ix['column1']];names=[names[j] for j in ix['column1']]
        for role in ['clock_c','clock_d']:
            np.testing.assert_allclose(x[:,n.index('log1p_'+role+':noncompetitive')]+x[:,n.index('log1p_'+role+':competitive')],old[:,names.index('log1p_'+role)])
        np.testing.assert_array_equal(W[4],W[1]-W[0]);np.testing.assert_array_equal(W[5],W[3]-W[2])

    def test_stacked_bucket_covariance_against_dense_scores(self):
        d=self.fixture();d['position']=np.select([d.board<=-300,d.board<=-101,d.board<=100,d.board<=299],[0,1,2,3],default=4)
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);p=td/'fixture.parquet';d.to_parquet(p,index=False)
            one=td/'one.npz';o.bucket_job(dict(paths=[p],out=one,key='first',phase=1))
            fits={};manual=np.zeros((400,46));at=0
            with np.load(one) as z:
                for model in o.MODELS:
                    sub=d.loc[o.selection(d,model)];X,names,W,terms=o.build(sub,model);y=sub.y.to_numpy(float)*100
                    means=pd.DataFrame(X).groupby(sub.chooser.to_numpy()).transform('mean').to_numpy();X-=means
                    y-=pd.Series(y).groupby(sub.chooser.to_numpy()).transform('mean').to_numpy()
                    f=solve(z[model+'_xx'],z[model+'_xy']);f['g']=len(np.unique(sub.chooser));fits[model]=f
                    scaled=X/f['scale'];bb=np.linalg.lstsq(scaled,y,rcond=1e-10)[0]/f['scale']
                    np.testing.assert_allclose(W@f['beta'],W@bb,atol=3e-6)
                    scores=pd.DataFrame(X*(y-X@f['beta'])[:,None]).groupby(sub.chooser.to_numpy()).sum()
                    manual[scores.index,at:at+len(W)]=scores.to_numpy()@f['bread']@W.T*np.sqrt(f['g']/(f['g']-1));at+=len(W)
            two=td/'two.npz';o.bucket_job(dict(paths=[p],out=two,key='second',phase=2,fits=fits))
            with np.load(two) as z:np.testing.assert_allclose(z['stacked_covariance'],manual.T@manual,atol=1e-6,rtol=1e-8)
            # Rating groups share chooser clusters: their off-diagonal block is not discarded.
            self.assertGreater(np.max(np.abs((manual.T@manual)[4:8,8:12])),1e-5)

if __name__=='__main__':unittest.main()
