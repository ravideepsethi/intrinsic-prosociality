#!/usr/bin/env python3
"""Offline checks of likelihood, chronology, roles, coverage and checkpoint behavior."""
import argparse,itertools,json,tempfile,types,unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb
from scipy.special import logsumexp
from scipy.optimize._numdiff import approx_derivative
import hmm,stable_hmm as sh,followup_models as fm,opportunity_followup as op
import self_test_v100 as prior
import prepare_sequences as prep
from features import design,subset,replace_outcomes
from util import *


class FollowupTests(unittest.TestCase):
    def test_log_likelihood_bridge_and_weighted_gradients(self):
        d=prior.tiny();d['account_weights']=np.array([2.,1.,0.,1.])
        for family in fm.FAMILIES:
            m=sh.Layout(4,3,3,family,[1,2]);old=hmm.Layout(4,3,3,family,[1,2]);v=old.start(41)
            new=m.objective(v,d);expected=old.objective(v,d)
            self.assertAlmostEqual(new[0],expected[0],places=12)
            np.testing.assert_allclose(new[1],expected[1],atol=1e-12)
            numeric=approx_derivative(lambda x:m.objective(x,d)[0],v,method='3-point').ravel()
            np.testing.assert_allclose(new[1],numeric,rtol=3e-5,atol=3e-7)
            self.assertEqual(m.bounds(7),old.bounds())

    def test_extreme_logits_against_exhaustive_log_path_sum(self):
        d=prior.tiny();m=sh.Layout(4,3,2,'unrestricted',[1,2]);v=m.start(9)
        v[m.s['a']]=[-950.,200.];v[m.s['gamma']]=1000.;v[m.s['initial']]=[-500.,1.]
        z,ee,tt,ii=m.logits(v,d)
        actual=sh.forward_backward(d['y'],d['ptr'],ee,tt,ii,z['lp'],np.ones(4))[0]
        for i in range(4):
            lo,hi=d['ptr'][i:i+2];paths=[]
            for j in range(2):
                for states in itertools.product([0,1],repeat=int(hi-lo)):
                    val=z['lp'][j]+sh.lsig(ii[j] if states[0] else -ii[j])
                    for t,e in enumerate(states):
                        r=lo+t
                        if t:val+=sh.lsig(tt[r,j,states[t-1]] if e else -tt[r,j,states[t-1]])
                        val+=sh.lsig(ee[r,j,e] if d['y'][r] else -ee[r,j,e])
                    paths.append(val)
            self.assertAlmostEqual(actual[i],logsumexp(paths),places=9)
        value,gradient=m.objective(v,d);self.assertTrue(np.isfinite(value) and np.isfinite(gradient).all())
        pred=sh.predict(dict(family='unrestricted',J=2,parameters=v.tolist()),d)
        np.testing.assert_allclose(np.bincount(d['ids'],weights=pred['log_score']),actual,atol=1e-9)
        self.assertLess(pred['log_score'].min(),-700.)  # no hidden probability floor

    def test_forecast_decomposition_and_no_current_or_future_leak(self):
        d=prior.tiny();m=sh.Layout(4,3,3,'gate',[1,2]);v=m.start(11)
        fit=dict(family='gate',J=3,parameters=v.tolist());p=sh.predict(fit,d);old,extra=hmm.predict(fit,d)
        np.testing.assert_allclose(old,p['probability'],atol=1e-12)
        mask=np.ones(len(old),bool);mask[d['ptr'][:-1]]=False
        np.testing.assert_allclose((p['receipt_entry_contribution']+p['receipt_stay_contribution'])[mask],(extra['receipt_input_1']-extra['receipt_input_0'])[mask],atol=1e-12)
        for row in np.flatnonzero(mask):
            y=d['y'].copy();y[row:]=1-y[row:];other=sh.predict(fit,replace_outcomes(d,y))
            for k in ['probability','receipt_entry_contribution','receipt_stay_contribution']:
                self.assertAlmostEqual(p[k][row],other[k][row],places=12)
        y=d['y'].copy();y[d['period']==1]=1-y[d['period']==1]
        np.testing.assert_allclose(p['train_posterior'],sh.predict(fit,replace_outcomes(d,y))['train_posterior'],atol=1e-12)

    def test_simulation_rate_calibration_and_persistent_type(self):
        d=prior.tiny();m=sh.Layout(4,3,3,'willingness',[1,2]);v=m.start(20)
        fit=dict(family='willingness',J=3,parameters=v.tolist())
        truth=fm.calibrated_truth(fit,d,4.,True)
        self.assertAlmostEqual(sh.expected_grants(truth,d),4.,places=7)
        self.assertAlmostEqual(fm.structure(truth,d)['reference_gap'],.03,places=10)
        draws=np.array([sh.simulate(truth,d,s).sum() for s in range(800)])
        self.assertLess(abs(draws.mean()-4.),5*draws.std(ddof=1)/np.sqrt(len(draws)))
        np.testing.assert_array_equal(sh.simulate(truth,d,15),sh.simulate(truth,d,15))
        # Perfect persistent type separation creates all-zero or all-one histories, never a redraw each row.
        z,ee,tt,ii=m.logits(v,d);ee[:,0,:]=-1000;ee[:,1:,:]=1000
        y=sh.simulate_kernel(d['ptr'],ee,tt,ii,np.array([.5,.25,.25]),104)
        for lo,hi in zip(d['ptr'][:-1],d['ptr'][1:]):self.assertEqual(len(set(y[lo:hi])),1)

    def test_roles_strict_future_and_claim_conservation(self):
        db=duckdb.connect();anchor=1700000000000
        q=pd.DataFrame(dict(row_id=[1,2],recipient_id=[10,999],opponent_id=[20,888],anchor_ms=[anchor]*2,game_id=['anchor01','anchor02']))
        # Valid chooser / own disconnect; original partner; equal-time; pre-anchor start; competitive.
        p=pd.DataFrame(dict(game_id=['later001','later002','later003','later004','later005','later006'],
          chooser_user_id=[10,31,10,10,10,10],disconnected_user_id=[30,10,20,33,34,35],
          utc_ms=[anchor+1,anchor+1,anchor+1,anchor,anchor-1,anchor+1],
          api_last_move_at_ms=[anchor+DAY,anchor+10*DAY,anchor+DAY,anchor,anchor+DAY,anchor+DAY],board=[0,0,0,0,0,2],y=[1,0,0,1,0,0]))
        db.register('iv',q);db.register('source',p)
        chooser=db.execute(op.role_sql('chooser')).df().set_index('row_id');own=db.execute(op.role_sql('self_disconnected')).df().set_index('row_id')
        self.assertEqual(chooser.loc[1,'chooser_n_lost_90'],1);self.assertEqual(chooser.loc[1,'chooser_n_all_90'],2)
        self.assertEqual(own.loc[1,'self_disconnected_n_lost_7'],0);self.assertEqual(own.loc[1,'self_disconnected_n_lost_30'],1)
        self.assertEqual(chooser.loc[2].sum(),0);self.assertEqual(own.loc[2].sum(),0)
        self.assertEqual(chooser.loc[1,'chooser_g_lost_90'],1);db.close()

    def test_both_colors_api_status_and_incomplete_months(self):
        db=duckdb.connect();a=1700000000000
        q=pd.DataFrame(dict(row_id=[1],recipient_id=[10],opponent_id=[20],anchor_ms=[a],game_id=['anchor01'],recipient_name=['a'],opponent_name=['b']))
        p=pd.DataFrame(dict(game_id=['later001','later002','later003','later004'],utc_ms=[a+DAY,a+8*DAY,a+DAY,a],
          white_id=[10,31,10,10],black_id=[30,10,20,33],white=['a','c','a','a'],black=['d','a','b','e'],
          start_ms=[a+DAY,a+8*DAY,a+DAY,a],t=[a+2*DAY,a+9*DAY,a+DAY,a+DAY],status=['timeout','outoftime','timeout','timeout']))
        db.register('iv',q);db.register('named_iv',q);db.register('traffic',p)
        values=db.execute(op.count_games_sql()).df().iloc[0]
        self.assertEqual(values.corpus_games_7,1);self.assertEqual(values.corpus_games_30,2)
        values=db.execute(op.count_games_sql('traffic',True)).df().iloc[0]
        self.assertEqual(values.api_timeout_90,1);self.assertEqual(values.api_outoftime_90,1)
        full=set(op.ds.MONTHS);self.assertTrue(op.coverage_mask([a],full)[0])
        full.remove('2024-01');self.assertFalse(op.coverage_mask([a],full)[0]);db.close()

    def test_checkpoint_tampering_and_budget_extension_identity(self):
        from run_followup import settings_for_identity,package_report
        args=types.SimpleNamespace(bootstrap_refits=120,recovery_reps=20,workers=2,seed=1,starts=8,stages=['models'])
        before=binding(settings_for_identity(args));args.bootstrap_refits=200;args.recovery_reps=40;args.workers=4
        self.assertEqual(before,binding(settings_for_identity(args)))
        args.starts=12;self.assertNotEqual(before,binding(settings_for_identity(args)))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'checkpoint.json';atomic_json(p,dict(value=1));certify(p,'x');self.assertTrue(ready(p,'x'))
            atomic_json(p,dict(value=2))
            with self.assertRaisesRegex(RuntimeError,'checksum'):ready(p,'x')
            report=root/'report';report.mkdir();csv_write(report/'bad.csv',[dict(recipient_id=123)])
            with self.assertRaisesRegex(RuntimeError,'Private identifier'):package_report(report,root,'fixture')

    def test_broader_source_io_bridges_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=root/'PRIVATE';report=root/'report';private.mkdir();report.mkdir();(root/'evidence').mkdir()
            a=1700000000000;db=duckdb.connect()
            q=pd.DataFrame(dict(row_id=[1,2],recipient_id=[10,90],opponent_id=[20,91],anchor_ms=[a,a],
              archive_start_ms=[a-1000,a-2000],game_id=['anchor01','anchor02']))
            source=pd.DataFrame(dict(game_id=q.game_id,disconnected_user_id=q.recipient_id,chooser_user_id=q.opponent_id,
              disconnected_username_norm=['A','x'],chooser_username_norm=['B','y']))
            db.register('iv',q);db.register('source',source)
            traffic=pd.DataFrame(dict(game_id=['anchor01','anchor02','later001','later002'],
              utc_ms=[a-1000,a-2000,a+DAY,a+10*DAY],white_id=[20,90,10,30],black_id=[10,91,30,10]))
            p=root/'traffic.parquet';traffic.to_parquet(p,index=False);pf=op.pq.ParquetFile(p)
            atomic_json(root/'evidence/chronology_contract.json',dict(entries=[dict(path='traffic.parquet',file_index='1',bytes=p.stat().st_size,
              rows=len(traffic),row_groups=pf.metadata.num_row_groups)]))
            with patch.object(op,'PKG',root):
                dest,s=op.chronology(db,root,private,report,'io-test');self.assertEqual(s['status'],'CHRONOLOGY_COUNTS_COMPLETE')
                values=op.aligned(dest,q.row_id.to_numpy());np.testing.assert_array_equal(values['corpus_games_90'],[2,0])
                resumed,_=op.chronology(db,root,private,report,'io-test');self.assertEqual(dest,resumed)
            api=pd.DataFrame(dict(game_id=['later001','later002'],api_status=['timeout','outoftime'],
              api_created_at_ms=[a+DAY,a+10*DAY],api_last_move_at_ms=[a+2*DAY,a+11*DAY],
              white_username_norm=['a','c'],black_username_norm=['c','a'],api_speed=['blitz','blitz'],api_rated=[True,True],api_variant=['standard','standard']))
            p=root/'api.parquet';api.to_parquet(p,index=False)
            items=[dict(month='2023-11',source='synthetic',paths=[str(p)],expected_rows=2,receipts=[])]
            with patch.object(op.ds,'discover',return_value=(items,[])):
                dest,months,s=op.api_candidates(db,root,private,report,'io-test')
                self.assertEqual(months,{'2023-11'});values=op.aligned(dest,q.row_id.to_numpy())
                np.testing.assert_array_equal(values['api_timeout_90'],[1,0]);np.testing.assert_array_equal(values['api_outoftime_90'],[1,0])
                self.assertFalse(op.coverage_mask([a],months)[0])
                op.api_candidates(db,root,private,report,'io-test')
            api['status']=['outoftime','outoftime'];api.to_parquet(p,index=False)
            conflict=db.execute(op.ds.normal_sql([p])).df().alias_conflict
            np.testing.assert_array_equal(conflict,[True,False]);db.close()


DAY=prep.DAY


def smoke():
    import concurrent.futures as cf,multiprocessing as mp
    from run_followup import package_report
    root=Path(tempfile.mkdtemp(prefix='construal_followup_smoke_'));private=root/'PRIVATE';report=root/'report';private.mkdir();report.mkdir()
    source=root/'source.parquet';prior.fixture(N=240).to_parquet(source,index=False)
    db=duckdb.connect();db.execute('SET threads=1');prep.source_view(db,[source])
    seq,_=prep.prepare(db,private,report,'synthetic-v110',100,100,20260921,300)
    df=pd.read_parquet(seq);dev=df[df.cohort=='development'];train=subset(design(dev),dev.period.to_numpy()==0)
    frame=df[df.cohort=='evaluation'];ev=design(frame)
    # Small synthetic fitted-model starting points, not authenticated real results.
    initial={}
    for family in fm.FAMILIES:
        m=sh.Layout(train['X'].shape[1],train['H'].shape[1],2,family,train['cost_indices'])
        initial[family]=dict(family=family,J=2,parameters=m.start(2).tolist())
    args=types.SimpleNamespace(bound_grid=[7.,12.],starts=2,refit_starts=2,recovery_starts=2,
      seed=20260921,maxiter=25,ridge=1e-6,bootstrap_refits=2,recovery_reps=1)
    with cf.ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
        fits,grid,path,risk=fm.numerical_grid(train,ev,frame,initial,private,report,'synthetic-v110',args,pool)
        fm.bootstrap(train,path,ev,risk,fits,grid,private,report,'synthetic-v110',args,pool)
        fm.recovery(train,path,ev,fits,private,report,'synthetic-v110',args,pool)
    # Resume exactly one cached attempt and detect identity changes without refitting.
    p=next((private/'fits').glob('*.json'));self_fit=json.loads(p.read_text());require(ready(p,'synthetic-v110'),'Fit receipt missing')
    require(len(pd.read_csv(report/'recovery_draws.csv'))==12,'Incomplete recovery scenarios')
    require('percentile95_low' not in pd.read_csv(report/'refit_bootstrap_summary.csv'),'Intervals leaked below 100 refits')
    require((pd.read_csv(report/'refit_bootstrap_summary.csv').interval_status=='INSUFFICIENT_CONVERGED_REFITS').all(),'Unsupported interval status')
    atomic_text(report/'SYNTHETIC_ONLY.txt','Software validation only. Toy data and intentionally capped iterations; not production evidence.\n')
    package_report(report,root,'synthetic_smoke');db.close();print('FOLLOWUP_SYNTHETIC_OK',root,flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--smoke',action='store_true');args=ap.parse_args()
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(prior.NumericalTests),unittest.defaultTestLoader.loadTestsFromTestCase(FollowupTests)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    if args.smoke:smoke()
    print('CONSTRUAL_FOLLOWUP_OFFLINE_TESTS_OK',flush=True)
