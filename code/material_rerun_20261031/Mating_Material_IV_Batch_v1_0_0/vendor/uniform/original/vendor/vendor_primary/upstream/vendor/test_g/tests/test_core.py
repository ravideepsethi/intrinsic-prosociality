"""Scientific invariants and direct-fit checks, using synthetic data only."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import chess
import numpy as np
import pandas as pd
from scipy.special import logit
from g_design import *
from g_fe import *
from g_data import CascadeReservoir,pgn_summary,eligible_reason,precision_interval
from g_outcome import OutcomeModel,solve_curve
from g_statistics import interval,sufficiency,equivalence,monte_carlo_endpoints,eiv_reliability,eiv_secondary

def fixture(accounts=35,observations=15,seed=12):
    rng=np.random.default_rng(seed);n=accounts*observations
    d=pd.DataFrame(dict(chooser=np.repeat(np.arange(accounts),observations),group=np.repeat(np.arange(accounts)%5-1,observations),
       game_id=['G%07d'%i for i in range(n)],event_ms=np.arange(n),archive_ordinal=np.arange(n),
       vf=rng.normal(0,240,n),mate=np.zeros(n),dr=rng.normal(0,130,n),mean_r=rng.uniform(900,2300,n),
       clock_f=rng.uniform(2,60,n),clock_g=rng.uniform(2,60,n),base=np.full(n,180.),inc=rng.integers(0,3,n),
       stm=np.zeros(n),ply=rng.integers(11,190,n),speed=rng.integers(0,5,n),month_code=rng.integers(0,24,n),
       premium=rng.uniform(1,20,n),rd_c=rng.uniform(50,150,n),rd_d=rng.uniform(50,150,n),
       y=rng.binomial(1,.15,n),year=np.repeat(2,n),flagged=np.zeros(n,bool)))
    d['board']=-d.vf;d['train']=assign_split(d);return d

class CoreTests(unittest.TestCase):
    def test_orientation(self):
        d=fixture();z=opposite(opposite(d));np.testing.assert_allclose(d[['vf','dr','clock_f','clock_g','stm','mate']],z[['vf','dr','clock_f','clock_g','stm','mate']])
        # A disconnect has the opponent to move. Map identical board state from both POVs.
        b=chess.Board();b.push_san('e4');self.assertEqual(b.turn,chess.BLACK)
        disconnected_cp=-80;chooser_cp=-disconnected_cp
        x=d.iloc[:1].copy();x['vf']=chooser_cp;x['dr']=100.;x['stm']=0;x['clock_f']=175.;x['clock_g']=180.
        other=opposite(x);self.assertEqual(other.vf.iloc[0],disconnected_cp);self.assertEqual(other.stm.iloc[0],1)
        np.testing.assert_allclose(raw_features(opposite(other))[0],raw_features(x)[0])
    def test_symmetry_coherence(self):
        d=fixture();m=OutcomeModel();X,n,_=raw_features(d,True);m.names=n;m.beta=np.random.default_rng(3).normal(0,.03,(X.shape[1],2))
        p=m.predict(d);q=m.predict(opposite(d));np.testing.assert_allclose(p.sum(1),1,atol=1e-14);np.testing.assert_allclose(p,q[:,[2,1,0]],atol=1e-14)
    def test_training_only_fe_quadratic(self):
        d=fixture();X=np.column_stack([d.vf/100,d.dr/100]);zt,zf,train,blocks,layout=within_forms(d,X)
        H=zt[train].T@zt[train];fit=solve(H)
        # Direct explicit account-dummy least squares, training observations only.
        F=np.eye(d.chooser.nunique())[d.chooser];Z=np.column_stack([X,F]);b=np.linalg.lstsq(Z[train],d.y.to_numpy()[train],rcond=None)[0]
        np.testing.assert_allclose(b[:2],fit['beta'],atol=1e-10)
        observed=np.mean((d.y.to_numpy()[~train]-Z[~train]@b)**2)
        self.assertAlmostEqual(observed,quadratic(zt[~train].T@zt[~train],fit['beta'])/(~train).sum(),places=12)
        d2=d.copy();d2.loc[~train,'y']=1-d2.loc[~train,'y'];z2=within_forms(d2,X)[0]
        np.testing.assert_allclose(z2[train],zt[train])
        # Repeated block resampling equals repeated whole accounts, including their training FE.
        weights=block_draw(14);ww=weights[blocks];hh=(zt[train]*ww[train,None]).T@zt[train]
        wb=np.linalg.lstsq(Z[train]*np.sqrt(ww[train,None]),d.y.to_numpy()[train]*np.sqrt(ww[train]),rcond=None)[0]
        np.testing.assert_allclose(wb[:2],solve(hh)['beta'],atol=1e-10)
    def test_counterfactual_rebuild(self):
        d=fixture();z=counterfactual(d,'gap100');np.testing.assert_allclose(z.dr-d.dr,100);np.testing.assert_allclose(z.mean_r-d.mean_r,50)
        z=counterfactual(d,'double_clock');np.testing.assert_allclose(z.clock_f,2*d.clock_f)
    def test_natural_tails(self):
        knots=[-2,-1,0,1,2];x=np.array([3.,4.,5.]);z=natural(x,knots);np.testing.assert_allclose(z[2]-z[1],z[1]-z[0],atol=1e-14)
    def test_cascade_exact_greedy(self):
        quotas={(0,0):7,(0,1):6,(0,2):5};games=[]
        for i in range(100):games.append(dict(game_id=f'G{i:07d}',speed=0,ply=11+(i%3)*10))
        with tempfile.TemporaryDirectory() as td:
            r=CascadeReservoir(td,quotas)
            for g in games:r.add(g,{},'moves')
            selected={(p['speed'],p['bin']):[] for p in r.records()}
            for p in r.records():selected[(p['speed'],p['bin'])].append(p['row']['game_id'])
            used=set()
            for b in [2,1,0]:
                eligible=[g for g in games if g['ply']>=11+10*b and g['game_id'] not in used]
                want=sorted(eligible,key=lambda g:hash64(g['game_id'],f'{SEED}:0:{b}'))[:quotas[(0,b)]]
                expected={g['game_id'] for g in want};self.assertEqual(expected,set(selected[(0,b)]));used|=expected
            self.assertEqual(len(used),18);r.close()
    def test_roots_and_bad_ratios(self):
        root,status=solve_curve(lambda x:x-125);self.assertEqual(status,'resolved');self.assertAlmostEqual(root,125,places=6)
        self.assertNotEqual(solve_curve(lambda x:np.sin(x))[1],'resolved')
        lo,hi=interval([np.nan]*3+list(np.arange(97)));self.assertTrue(np.isneginf(lo));self.assertTrue(np.isposinf(hi))
    def test_rule_ci(self):
        self.assertLess(precision_interval(100,100)[1],.99);self.assertGreater(precision_interval(1000,1000)[1],.99)
    def test_eiv_secondary(self):
        x=np.array([-2.,0.,2.]);w=np.ones(3)
        self.assertAlmostEqual(eiv_reliability(x,w,2/3),.75)
        rng=np.random.default_rng(31);base=x+rng.normal(0,.1,(50,3));draws=np.repeat(base,10,axis=0)
        r=eiv_secondary(x,w,1.,draws,np.ones(500))
        self.assertGreater(r['eiv_slope'],1.);self.assertLess(r['eiv_reliability'],1.)
        self.assertEqual(len(r['eiv_slope_draws']),500)
        draws[0,0]=np.nan;r=eiv_secondary(x,w,1.,draws,np.ones(500));self.assertTrue(np.isnan(r['eiv_slope']))
    def test_pgn_clocks(self):
        h={'Site':'https://lichess.org/AbCd1234','TimeControl':'180+0','Result':'1-0','Event':'Rated Blitz game','WhiteElo':'1500','BlackElo':'1600','Termination':'Normal'}
        r=pgn_summary(h,'1. e4 {[%clk 0:03:00]} e5 {[%clk 0:02:58]} 2. Nf3 {[%clk 0:02:57]} Nc6 {[%clk 0:02:55]} 1-0')
        self.assertEqual(r['ply'],4);self.assertEqual(r['clock_white'],177);self.assertEqual(r['clock_black'],175)

if __name__=='__main__':unittest.main(verbosity=2)
