#!/usr/bin/env python3
"""Deterministic numerical and pipeline contract tests; no production data."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
import numpy as np
import pandas as pd
from scipy.special import expit,logsumexp
from scipy.optimize._numdiff import approx_derivative
import duckdb
from fixture import fixture
from prepare import encode,subset,perception_subset,prepare,source_view,C0,C1
from model import Model,Spec,CORE,PERCEPTION,fit,predict,simulate,transfer,normal_weights
from diagnostics import paired
from io_utils import binding,json_write,json_read
from analysis import safe_result


class NumericalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame=fixture(100,100,36)
        cls.arrays,cls.meta=encode(cls.frame,1)
        cls.d=subset(cls.arrays['development'],cls.arrays['development']['period']==0)
        cls.small=subset(cls.d,cls.d['ids']<16)
        cls.meta['reference_group_weights']=[.25]*4

    def test_analytic_gradients_all_families(self):
        meta=dict(self.meta,board_factor=[.05,.3,.65,.8,.94])
        for spec in CORE+PERCEPTION+[Spec('calibrated',surface='calibrated')]:
            with self.subTest(model=spec.name):
                m=Model(spec,2,meta);v=m.start(19)
                # Keep the finite-difference point interior, including all factor cells.
                for key in ['A','cell_effect','eta','prior']:
                    if key in m.slices:v[m.slices[key]]+=np.random.default_rng(2).normal(0,.03,len(v[m.slices[key]]))
                value,g=m.objective(v,self.small,1e-4)
                gn=approx_derivative(lambda x:m.objective(x,self.small,1e-4)[0],v,method='3-point').ravel()
                self.assertTrue(np.isfinite(value))
                self.assertLess(np.max(abs(g-gn)/(1+abs(gn))),2e-5)

    def test_single_type_gradient(self):
        m=Model(Spec('single'),1,self.meta);v=m.start(4)
        _,g=m.objective(v,self.small)
        gn=approx_derivative(lambda x:m.objective(x,self.small)[0],v).ravel()
        np.testing.assert_allclose(g,gn,atol=2e-5)

    def test_account_weighted_gradient(self):
        d=dict(self.small);d['aw']=np.arange(len(d['ptr'])-1)%3
        m=Model(Spec('both'),2,self.meta);v=m.start(8)
        _,g=m.objective(v,d)
        gn=approx_derivative(lambda x:m.objective(x,d)[0],v).ravel()
        np.testing.assert_allclose(g,gn,atol=2e-5)

    def test_index_anchors(self):
        for s in [Spec('sep'),Spec('free',surface='free'),Spec('cal',surface='calibrated')]:
            m=Model(s,3,dict(self.meta,board_factor=[.05,.3,.65,.8,.94]));dec=m.decode(m.start(2))
            self.assertAlmostEqual(dec['A'][C0],0.)
            self.assertAlmostEqual(dec['A'][C1],1.)

    def test_normal_weights_and_derivatives(self):
        b=np.array([-1000.,-350.,-99.,0.,210.,1000.]);sd=np.full(len(b),130.)
        w,dw=normal_weights(b,sd);np.testing.assert_allclose(w.sum(axis=1),1.,atol=1e-14)
        numeric=(normal_weights(b,sd+.001)[0]-normal_weights(b,sd-.001)[0])/.002
        np.testing.assert_allclose(dw,numeric,atol=1e-10)
        np.testing.assert_allclose(dw.sum(axis=1),0.,atol=1e-14)

    def test_zero_noise_recovers_static(self):
        d=perception_subset(self.d,self.meta['support'],True)
        base=Model(Spec('accurate'),2,self.meta);v=base.start(3)
        noisy=Model(Spec('noisy',perception=True),2,self.meta)
        res=dict(spec=asdict(base.spec),J=2,bound=12,parameters=v.tolist())
        vn=transfer(res,noisy,self.meta);vn[noisy.slices['sigma']]=0
        a,b,_=base.emissions(v,d);c,e,_=noisy.emissions(vn,d)
        np.testing.assert_allclose(a,c,atol=1e-12);np.testing.assert_allclose(b,e,atol=1e-12)

    def test_filter_equals_joint_likelihood(self):
        m=Model(Spec('test',tier_priors=True),3,self.meta);v=m.start(5)
        res=dict(spec=asdict(m.spec),J=3,bound=12,parameters=v.tolist())
        p,ll=predict(res,self.small,self.meta)
        logp,logq,c=m.emissions(v,self.small)
        obs=np.where(self.small['y'][:,None],logp,logq)
        truth=logsumexp(np.add.reduceat(obs,self.small['ptr'][:-1],axis=0)+c['dec']['lp'][self.small['group']],axis=1)
        np.testing.assert_allclose(np.add.reduceat(ll,self.small['ptr'][:-1]),truth,atol=1e-11)
        self.assertTrue(np.all((p>=0)&(p<=1)))

    def test_no_future_outcome_leakage(self):
        m=Model(Spec('test'),2,self.meta);res=dict(spec=asdict(m.spec),J=2,bound=12,parameters=m.start(8).tolist())
        original=self.arrays['evaluation'];p,_=predict(res,original,self.meta)
        changed=dict(original);changed['y']=original['y'].copy();row=20
        changed['y'][row]=1-changed['y'][row];new,_=predict(res,changed,self.meta)
        np.testing.assert_allclose(p[:row+1],new[:row+1],atol=0.)

    def test_scaling_uses_early_development_only(self):
        changed=self.frame.copy();mask=(changed.cohort=='evaluation')|(changed.period==2)
        changed.loc[mask,'y']=1-changed.loc[mask,'y']
        changed.loc[mask,'crd']=999.
        _,meta=encode(changed,1)
        self.assertEqual(meta['support'],self.meta['support'])
        np.testing.assert_allclose(meta['means'],self.meta['means'])
        np.testing.assert_allclose(meta['scales'],self.meta['scales'])

    def test_missing_initial_rating_does_not_borrow_future(self):
        changed=self.frame.copy()
        account=changed.chooser.iloc[0]
        first=changed.index[changed.chooser==account][0]
        changed.loc[changed.chooser==account,'rating']=2600.
        changed.loc[first,'rating']=np.nan
        arrays,_=encode(changed,1)
        d=arrays['development'];i=np.flatnonzero(d['accounts']==account)[0]
        self.assertEqual(d['group'][i],1)

    def test_nested_index_probabilities(self):
        m=Model(Spec('both'),3,self.meta);v=m.start(4)
        base=dict(spec=asdict(m.spec),J=3,bound=12,parameters=v.tolist())
        for spec in [Spec('free_index',surface='free'),Spec('type_cells',surface='type_cells')]:
            other=Model(spec,3,self.meta);vv=transfer(base,other,self.meta)
            p=m.emissions(v,self.small)[0];q=other.emissions(vv,self.small)[0]
            np.testing.assert_allclose(p,q,atol=1e-11)

    def test_cost_normalization(self):
        from model import parameters
        m=Model(Spec('both',tier_priors=True),3,self.meta)
        res=dict(spec=asdict(m.spec),J=3,bound=12,parameters=m.start(4).tolist())
        rows,_=parameters(res,self.meta,[.1,.2,.3,.4])
        self.assertAlmostEqual(sum(r['share']*r['normalized_cost_multiplier'] for r in rows),1.)

    def test_zero_cost_not_reported_as_identified(self):
        from model import parameters
        m=Model(Spec('both'),2,self.meta);v=m.start(4);v[m.slices['amplitude']]=0
        rows,_=parameters(dict(spec=asdict(m.spec),J=2,bound=12,parameters=v.tolist()),self.meta)
        self.assertTrue(all(r['normalized_cost_multiplier'] is None for r in rows))
        self.assertTrue(all(not r['cost_identified'] for r in rows))

    def test_extreme_log_probabilities(self):
        m=Model(Spec('extreme',perception=True),2,self.meta);v=m.start(1)
        v[m.slices['alpha']]=[-900,900]
        value,g=m.objective(v,self.small)
        self.assertTrue(np.isfinite(value));self.assertTrue(np.isfinite(g).all())

    def test_jensen_decomposition(self):
        from scipy.special import ndtr
        w=np.array([ndtr(-1),ndtr(1)-ndtr(-1),1-ndtr(1)])
        A=np.array([0,.2,1]);p=w@expit(-6+4*A);pm=expit(-6+4*(w@A));p0=expit(-5.2)
        self.assertAlmostEqual(p,.023049903126961476)
        self.assertAlmostEqual((p-pm)+(pm-p0),p-p0)
        self.assertGreater(p-pm,0)

    def test_paired_scores_identical(self):
        ll=np.linspace(-3,-.01,len(self.small['y']))
        value=paired(self.small,ll,ll,np.ones(len(ll),bool))
        self.assertEqual(value['gain'],0.);self.assertEqual(value['equal_account_gain'],0.)

    def test_resampling_changes_likelihood_not_sequence(self):
        m=Model(Spec('test'),1,self.meta);v=m.start(4)
        d=dict(self.small);d['aw']=np.ones(len(d['ptr'])-1)*2
        a,g=m.objective(v,self.small);b,h=m.objective(v,d)
        self.assertAlmostEqual(a,b);np.testing.assert_allclose(g,h,atol=1e-12)

    def test_type_draw_persists(self):
        m=Model(Spec('test'),2,self.meta);r=dict(spec=asdict(m.spec),J=2,bound=12,parameters=m.start(4).tolist())
        d,types,p=simulate(r,self.small,self.meta,np.random.default_rng(2))
        lp=m.emissions(np.array(r['parameters']),self.small)[0]
        np.testing.assert_allclose(p,np.exp(lp[np.arange(len(p)),types[self.small['ids']]]))

    def test_small_optimization(self):
        r=fit(self.d,Spec('test','level'),1,self.meta,5,maxiter=800,ridge=1e-4)
        self.assertTrue(r['success'],r['message'])
        self.assertTrue(np.isfinite(r['objective']))
        self.assertLessEqual(r['projected_gradient'],2.5e-5)

    def test_numerical_bound_expansion(self):
        a=Model(Spec('noise',perception=True),2,self.meta,12.)
        b=Model(Spec('noise',perception=True),2,self.meta,24.)
        for name in ['alpha','theta','amplitude','prior','sigma']:
            k=a.slices[name].start
            self.assertGreater(b.bounds[k][1],a.bounds[k][1])


class ContractTests(unittest.TestCase):
    def test_resume_signature_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'fit.json'
            self.assertEqual(safe_result(p,'a',lambda:7),7)
            self.assertEqual(safe_result(p,'a',lambda:8),7)
            with self.assertRaises(RuntimeError):safe_result(p,'b',lambda:8)

    def test_source_sql_and_payoff_reconstruction(self):
        df=fixture(30,30,36)
        rename={'chooser':'chooser_user_id','t':'api_last_move_at_ms','start_ms':'api_created_at_ms',
          'y':'outcome_kind_draw','ply':'ply_count','rating':'chooser_elo','opponent_rating':'disconnected_elo',
          'speed':'api_speed','tc_base':'tc_base_s','tc_inc':'tc_inc_s','premium':'chooser_win_premium_v2',
          'draw_payoff':'chooser_draw_payoff_v2','win_payoff':'chooser_win_payoff_v2',
          'crd':'chooser_pre_rd_v2','drd':'disconnected_pre_rd_v2','cvol':'chooser_pre_sigma_v2','dvol':'disconnected_pre_sigma_v2',
          'cclock':'chooser_clock_last_obs_s','dclock':'disconnected_clock_last_obs_s',
          'b':'engine_eval_cp_disconnected','b_raw':'engine_eval_cp_disconnected_raw',
          'is_mate':'engine_eval_is_mate','score_type':'sf100k_score_type_side_to_move'}
        df=df.rename(columns=rename)
        df['disconnected_user_id']='other_'+df.chooser_user_id
        df['api_status']='timeout';df['five_second_rule_passed']=True;df['sf100k_nodes_requested']=100000
        df['chooser_color']=np.where(df.color==1,'white','black')
        df=df.drop(columns=['board','stage','cohort','period','expected_score','loss'])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'private').mkdir();(root/'report').mkdir()
            df.to_parquet(root/'source.parquet',index=False)
            db=duckdb.connect();source_view(db,[root/'source.parquet'])
            args=SimpleNamespace(seed=71,dev_accounts=25,eval_accounts=25,timing_guard_seconds=300)
            p=prepare(db,root/'private',root/'report',args,production=False)
            result=pd.read_parquet(p);self.assertEqual(result.chooser.nunique(),50)
            np.testing.assert_allclose(result.expected_score,.5-result.draw_payoff/(2*result.premium))
            self.assertFalse(result[['chooser','game_id']].duplicated().any())
            self.assertEqual(set(result.cohort),{'development','evaluation'})
            db.close()


if __name__=='__main__':unittest.main(verbosity=2)
