#!/usr/bin/env python3
"""Small offline tests with independent algebra/explicit-row benchmarks."""
import math,tempfile,unittest,sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.optimize._numdiff import approx_derivative
from common import *
from static_analyses import payoff_audit,patron_reversal,profile_view
from transmission import outcome_sql,fit_responses,build_followup,transmission
from recovery import mixture_objective,unpack,recovery

def regression_data(n=3000):
    rng=np.random.default_rng(927);person=np.arange(n)%300;opponent=1000+rng.integers(0,500,n)
    t=PANEL_START+DAY*(150+rng.integers(0,20,n));z=rng.normal(0,.05,n)
    d=dict(row_id=np.arange(n),recipient_id=person,opponent_id=opponent,archive_start_ms=t,
        recipient_rating=1400+rng.normal(0,80,n),opponent_rating=1400+rng.normal(0,80,n),
        month_code=np.full(n,5),tc_base_s=np.full(n,300),tc_inc_s=np.full(n,3),
        n_7d=rng.integers(5,50,n),counterparts_7d=rng.integers(5,20,n),expected_7d=np.full(n,.02),
        adjusted_7d=z,pre_games_30d=rng.integers(1,80,n))
    d['received']=rng.random(n)<np.clip(.2+2*z,.01,.99)
    d['y']=rng.random(n)<(.15+.05*d['received']);d['reached']=d['y']|(rng.random(n)<.7)
    for days in (90,30):
        d[f'fair_{days}']=rng.integers(0,30,n);d[f'kind_{days}']=rng.binomial(d[f'fair_{days}'],.1)
        d[f'disconnect_{days}']=rng.integers(0,50,n);d[f'receipt_{days}']=rng.binomial(d[f'disconnect_{days}'],.1)
        d[f'claim_{days}']=d[f'disconnect_{days}']-d[f'receipt_{days}']
    return d

def panel_fixture(path,n=3600):
    rng=np.random.default_rng(44);j=rng.integers(1,81,n);i=1000+rng.integers(1,121,n);fair=rng.random(n)<.6
    rating=1400+rng.integers(-200,201,n);gap=rng.integers(-300,301,n);e=1/(1+10**(gap/400));k=rng.uniform(6,15,n)
    y=rng.random(n)<(.07+.03*(i%3==0));start=PANEL_START+DAY*(100+rng.integers(0,300,n))
    cols=dict(game_id=np.array([f'G{x:07d}' for x in range(n)]),chooser_user_id=j,disconnected_user_id=i,
       chooser_username_norm=np.array(['u'+str(x) for x in j]),disconnected_username_norm=np.array(['u'+str(x) for x in i]),
       kind_draw=y,outcome_kind_draw=y,fair_competitive=fair,clearly_worse=~fair,
       utc_ms=start,api_last_move_at_ms=start+60000,archive_ordinal=np.arange(n),
       chooser_draw_payoff_v2=2*k*(.5-e),chooser_win_payoff_v2=2*k*(1-e),chooser_win_premium_v2=k,
       chooser_elo=rating,disconnected_elo=rating+gap,chooser_color=np.full(n,'white'),
       white_rating_diff_pgn=np.rint(np.where(y,2*k*(.5-e),2*k*(1-e))).astype(int),black_rating_diff_pgn=np.zeros(n,int),
       timeout_chooser_win=~y,month=np.where(np.arange(n)%2,'2024-03','2024-04'),api_speed=np.where(np.arange(n)%2,'blitz','rapid'),
       ply_count=rng.integers(2,81,n),engine_eval_cp_disconnected=np.where(fair,0,-400),chooser_pre_rd_v2=rng.uniform(40,100,n),
       disconnected_pre_rd_v2=rng.uniform(40,100,n),chooser_clock_last_obs_s=rng.uniform(5,200,n),disconnected_clock_last_obs_s=rng.uniform(5,200,n),
       tc_base_s=np.full(n,300.),tc_inc_s=np.full(n,3.))
    pq.write_table(pa.table(cols),path)
    return cols

class AFETests(unittest.TestCase):
    def test_future_join_boundaries_and_nonreachers(self):
        c=duckdb.connect();anchor=PANEL_START+120*DAY
        q=pd.DataFrame(dict(row_id=[1,2],recipient_id=[10,20],opponent_id=[99,98],anchor_ms=[anchor]*2,game_id=['expose1','expose2']))
        rows=[]
        # Include a prior-start game, a benefactor game, a tied anchor and an over-horizon game, all excluded.
        for gid,j,i,start,end,fair,y in [('valid',10,50,anchor+1,anchor+7*DAY,True,True),('worse',10,51,anchor+2,anchor+30*DAY,False,True),('oldstart',10,51,anchor-1,anchor+1,True,True),('benefactor',10,99,anchor+1,anchor+2,True,True),('tie',10,51,anchor,anchor,True,True),('late',10,51,anchor+1,anchor+90*DAY+1,True,True)]:
            rows.append(dict(game_id=gid,chooser_user_id=j,disconnected_user_id=i,utc_ms=start,api_last_move_at_ms=end,archive_ordinal=len(rows),fair_competitive=fair,clearly_worse=not fair,kind_draw=y))
        c.register('q',q);c.register('panel',pd.DataFrame(rows));out=c.execute(outcome_sql()).fetchdf().set_index('row_id')
        self.assertEqual(out.loc[1,'grants_competitive_7'],1);self.assertEqual(out.loc[1,'grants_clearly_worse_7'],0)
        self.assertEqual(out.loc[1,'grants_clearly_worse_30'],1);self.assertEqual(out.loc[1,'opportunities_competitive_90'],1)
        self.assertEqual(out.loc[2,'opportunities_competitive_90'],0);self.assertEqual(out.loc[1,'first_competitive']['gid'],'valid');c.close()

    def test_streaming_fwl_and_shared_covariance(self):
        rng=np.random.default_rng(8);n=2500;j=rng.integers(0,70,n);i=100+rng.integers(0,90,n);day=rng.integers(0,40,n)
        x=rng.normal(size=n);z=rng.normal(size=n);y=.35*x-.2*z+np.sin(j)+rng.normal(size=n)
        f=pd.DataFrame(dict(j=j,i=i,day=day,y=y,constant=1.,x=x,z=z))
        with tempfile.TemporaryDirectory() as td:
            c=connection(td,1,'1GB');c.register('source',f)
            r=streaming_lpm(c,'SELECT * FROM source',['constant','x','z'],['x'],Path(td)/'fit',True)[0]
            X=np.column_stack([np.eye(70)[j],x,z]);beta=np.linalg.lstsq(X,y,rcond=None)[0]
            self.assertAlmostEqual(r['coefficient'],beta[-2],places=10)
            xr=np.column_stack([x,z]);yr=y.copy()
            for k in np.unique(j):
                sel=j==k;xr[sel]-=xr[sel].mean(axis=0);yr[sel]-=yr[sel].mean()
            inv=np.linalg.inv(xr.T@xr);s=(xr@inv[:,0])*(yr-xr@beta[-2:])
            mask=((j[:,None]==j)|(j[:,None]==i)|(i[:,None]==j)|(i[:,None]==i)|(day[:,None]==day))
            var=float(s@mask@s)
            self.assertAlmostEqual(r['standard_error_pp']/100,math.sqrt(var),places=9);c.close()

    def test_profile_missing_is_not_false(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'p.parquet';pq.write_table(pa.Table.from_pylist([dict(username_norm='a',returned=True,patron=False,created_at_ms=1),dict(username_norm='b',returned=False,patron=None,created_at_ms=None)]),p)
            c=duckdb.connect();profile_view(c,dict(snapshot=str(p)));self.assertEqual(c.execute('SELECT count(*) FROM profiles WHERE returned AND patron=FALSE').fetchone()[0],1)
            pq.write_table(pa.Table.from_pylist([dict(username_norm='a',returned=True,patron=False,created_at_ms=1)]*2),p)
            with self.assertRaises(RuntimeError):profile_view(c,dict(snapshot=str(p)))
            c.close()

    def test_followup_bridge_and_strict_pretreatment_history(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'panel.parquet';values=panel_fixture(p,4)
            anchor=PANEL_START+150*DAY
            values['chooser_user_id']=np.array([99,10,10,10]);values['disconnected_user_id']=np.array([10,50,51,52])
            values['disconnected_username_norm']=np.array(['u10','u50','u51','u52'])
            values['utc_ms']=np.array([anchor-1000,anchor+1,anchor-DAY,anchor-5000])
            values['api_last_move_at_ms']=np.array([anchor,anchor+DAY,anchor-1000,anchor-1000])
            values['fair_competitive']=np.ones(4,bool);values['clearly_worse']=np.zeros(4,bool);values['kind_draw']=np.array([True,True,False,True])
            pq.write_table(pa.table(values),p)
            q=root/'q.parquet';pq.write_table(pa.Table.from_pylist([dict(row_id=0,recipient_id=10,opponent_id=99,game_id='G0000000',anchor_ms=anchor,archive_start_ms=anchor-1000,received=True,y=True,reached=True,outcome_gid='G0000001',outcome_t=anchor+DAY,complete90=True)]),q)
            s=root/'s.parquet';pq.write_table(pa.Table.from_pylist([dict(username_norm='u10',returned=True,patron=True,created_at_ms=anchor-10*DAY)]),s)
            inp=dict(panels=[str(p)],history=[str(p)],iv=str(q),snapshot=str(s))
            c=connection(root/'follow',1,'1GB');view_panel(c,inp);build_followup(c,inp,root/'follow')
            a=pq.read_table(root/'follow/analysis.parquet').to_pydict()
            # Histories exactly tied with the focal game start are excluded, including both tied events.
            self.assertEqual(a['prior_observed_opportunities'],[0]);self.assertEqual(a['prior_observed_grants'],[0])
            self.assertAlmostEqual(a['account_age_days'][0],10-1000/DAY,places=8)
            self.assertEqual(a['grants_competitive_90'],[1]);c.close()

    def test_static_modules_on_full_synthetic_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'panel.parquet';panel_fixture(p)
            s=root/'profiles.parquet';pq.write_table(pa.Table.from_pylist([dict(username_norm='u'+str(i),returned=True,patron=i%3==0,created_at_ms=PANEL_START-100*DAY) for i in range(1001,1121)]),s)
            inp=dict(panels=[str(p)],snapshot=str(s));a=payoff_audit(inp,root/'payoff',1,'1GB');self.assertEqual(a['identity_errors'],0)
            b=patron_reversal(inp,root/'patron',1,'1GB');self.assertEqual(len(b['estimates']),4)
            self.assertTrue(all(r.get('supported') for r in b['estimates']))

    def test_iv_units_and_zero_delta(self):
        import expanded_stats as es
        d=regression_data();ys=dict(next_grant_competitive_90=d['y'].astype(float),grants_competitive_90=d['y'].astype(float))
        r=fit_responses(d,ys,'synthetic')
        old=es.estimate(d,dict(name='test',family='iv',rich=True,fe=False,repeat=False,balance=False))
        b=next(x for x in old['estimates'] if x.get('estimator')=='2SLS')
        self.assertAlmostEqual(r[0]['effect'],b['iv_coefficient_pp'],places=10)
        self.assertAlmostEqual(r[0]['se'],b['iv_standard_error_pp'],places=10)
        self.assertAlmostEqual(r[0]['effect']/100,r[1]['effect'],places=10)

    def test_end_to_end_transmission_and_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);n=3000;d=regression_data(n);d['recipient_id']=np.arange(100000,100000+n)
            p=root/'panel.parquet';cols=panel_fixture(p,2*n)
            d['anchor_ms']=d['archive_start_ms']+60000
            d['game_id']=cols['game_id'][:n];d['outcome_gid']=cols['game_id'][n:]
            d['outcome_t']=d['anchor_ms']+DAY;d['reached']=np.ones(n,bool);d['complete90']=np.ones(n,bool)
            cols['chooser_user_id']=np.r_[d['opponent_id'],d['recipient_id']]
            cols['disconnected_user_id']=np.r_[d['recipient_id'],np.arange(900000,900000+n)]
            cols['disconnected_username_norm']=np.array(['u'+str(v) for v in cols['disconnected_user_id']])
            cols['chooser_username_norm']=np.array(['u'+str(v) for v in cols['chooser_user_id']])
            cols['utc_ms']=np.r_[d['archive_start_ms'],d['anchor_ms']+1000]
            cols['api_last_move_at_ms']=np.r_[d['anchor_ms'],d['outcome_t']]
            cols['kind_draw']=np.r_[d['received'],d['y']];cols['fair_competitive']=np.ones(2*n,bool);cols['clearly_worse']=np.zeros(2*n,bool)
            pq.write_table(pa.table(cols),p);q=root/'iv.parquet';pq.write_table(pa.table(d),q)
            inp=dict(panels=[str(p)],iv=str(q))
            result=transmission(inp,root/'trans',1,'1GB');self.assertEqual(result['estimate_rows'],45)
            result=recovery(inp,root/'recovery',1,'1GB',simulations=2,accounts=3500)
            self.assertEqual(result['status'],'RESTRICTED_RECOVERY_PROBE_COMPLETE')
            self.assertEqual(result['replications'],2)

    def test_sensitivity_polynomial_matches_direct_refits(self):
        import expanded_stats as es,followup_stats as fs,iv_numerics as num,comparison_core as cmp
        d=regression_data();xs,names,_,_,groups,_=es.controls(d,True)
        r,_=num.partial_out(np.column_stack(xs+[d['adjusted_7d'],d['received'],d['y']]),groups,len(names));z,t,y=r.T
        codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]);meat=lambda s:fs.shared_meat(s,codes,True)
        zd=float(z@t);b0=float(z@y)/zd;slope=float(z@z)/(100*REFERENCE_SD*zd)
        V=meat(np.column_stack([z*(y-b0*t),z*(slope*t-z/(100*REFERENCE_SD))]))/zd**2
        for delta in [-.04,0,.02,.04]:
            fit=fs.iv_fit(y-delta/(100*REFERENCE_SD)*z,t,z,meat)
            self.assertAlmostEqual(b0-delta*slope,fit['iv_coefficient'],places=12)
            self.assertAlmostEqual(V[0,0]+2*delta*V[0,1]+delta**2*V[1,1],fit['iv_standard_error']**2,places=12)

    def test_recovery_analytic_gradient(self):
        rng=np.random.default_rng(3);n=160;people=np.repeat(np.arange(40),4);y=rng.binomial(1,.1,n).astype(float)
        offset=rng.normal(0,.3,n);rows=rng.integers(0,n,90);lags=rng.uniform(.01,100,90)
        p=np.array([-5.,math.log(2),-1.,.7,math.log(.1)])
        fun=lambda v:mixture_objective(v,y,people,offset,rows,lags,40)[0]
        analytic=mixture_objective(p,y,people,offset,rows,lags,40)[1]
        numeric=approx_derivative(fun,p,method='3-point').ravel();np.testing.assert_allclose(analytic,numeric,rtol=1e-5,atol=1e-6)

    def test_checkpoint_detects_changed_output(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'result.txt';p.write_text('original');done(td,'abc')
            self.assertTrue(verify_resume(td,'abc'));p.write_text('changed')
            with self.assertRaises(RuntimeError):verify_resume(td,'abc')

if __name__=='__main__':unittest.main(verbosity=2)
