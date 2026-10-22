#!/usr/bin/env python3
"""Independent probability, gradient, timing and covariance checks. Offline."""
import argparse,itertools,json,math,tempfile,types,unittest
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb
from scipy import sparse
from scipy.special import expit,logsumexp
from scipy.optimize._numdiff import approx_derivative
import hmm,static_models,features,model_analysis as ma,prepare_sequences as prep
import receipt_tests as rt


def tiny():
    rng=np.random.default_rng(394);counts=np.array([1,4,7,2]);n=int(counts.sum())
    return dict(X=sparse.csr_matrix(rng.normal(size=(n,4))),
      H=np.c_[np.ones(n),rng.integers(0,2,n),rng.normal(size=n)],y=rng.integers(0,2,n).astype(float),
      ptr=np.r_[0,np.cumsum(counts)].astype(np.int64),ids=np.repeat(np.arange(4),counts),accounts=np.arange(4),
      F=rng.integers(0,2,n).astype(float)-1,cost_indices=[1,2],
      period=np.concatenate([np.r_[np.zeros(max(1,k//2)),np.ones(k-max(1,k//2))] for k in counts]).astype(np.int64))


class NumericalTests(unittest.TestCase):
    def test_hmm_matches_exhaustive_state_and_fixed_type_sum(self):
        d=tiny();m=hmm.Layout(4,3,2,'unrestricted',[1,2]);v=m.start(74)
        z,pe,pt,initial=m.probabilities(v,d)
        out=hmm.fb(d['y'],d['ptr'],pe,pt,initial,z['lp'],np.ones(4))[0]
        for i in range(4):
            lo,hi=d['ptr'][i:i+2];prob=0.
            for j in range(2):
                for states in itertools.product([0,1],repeat=int(hi-lo)):
                    p=math.exp(z['lp'][j])*(initial[j] if states[0] else 1-initial[j])
                    for t,e in enumerate(states):
                        r=lo+t
                        if t:p*=pt[r,j,states[t-1]] if e else 1-pt[r,j,states[t-1]]
                        p*=pe[r,j,e] if d['y'][r] else 1-pe[r,j,e]
                    prob+=p
            self.assertAlmostEqual(out[i],math.log(prob),places=11)

    def test_weighted_analytic_gradients(self):
        d=tiny();d['account_weights']=np.array([2.,1.,0.,1.])
        for family in ma.SWITCH:
            m=hmm.Layout(4,3,3,family,[1,2]);v=m.start(41)
            numeric=approx_derivative(lambda x:m.objective(x,d)[0],v,method='3-point').ravel()
            np.testing.assert_allclose(m.objective(v,d)[1],numeric,rtol=3e-5,atol=3e-7)
        for family in ('static_level','static_selectivity','normal_selectivity'):
            m=static_models.Static(4,3,family);v=m.start(41)
            numeric=approx_derivative(lambda x:m.objective(x,d)[0],v,method='3-point').ravel()
            np.testing.assert_allclose(m.objective(v,d)[1],numeric,rtol=3e-5,atol=3e-7)

    def test_filter_chain_rule_and_no_future_outcome_leak(self):
        d=tiny();m=hmm.Layout(4,3,3,'willingness',[1,2]);v=m.start(20)
        z,pe,pt,initial=m.probabilities(v,d)
        p,e,q,ll=hmm.filter_forecasts(d['y'],d['ptr'],d['period'],pe,pt,initial,np.exp(z['lp']))
        brute=hmm.fb(d['y'],d['ptr'],pe,pt,initial,z['lp'],np.ones(4))[0]
        np.testing.assert_allclose(ll,brute,atol=1e-10)
        np.testing.assert_allclose(-np.bincount(d['ids'],weights=ma.losses(d['y'],p)),ll,atol=1e-10)
        flipped=d['y'].copy();flipped[d['period']==1]=1-flipped[d['period']==1]
        p2,_,q2,_=hmm.filter_forecasts(flipped,d['ptr'],d['period'],pe,pt,initial,np.exp(z['lp']))
        np.testing.assert_allclose(q,q2,atol=1e-12)
        np.testing.assert_allclose(p[d['period']==0],p2[d['period']==0],atol=1e-12)
        for i in range(4):
            rows=np.arange(d['ptr'][i],d['ptr'][i+1]);first=rows[d['period'][rows]==1]
            if len(first):self.assertAlmostEqual(p[first[0]],p2[first[0]],places=12)

    def test_static_updates_match_joint_sequence_likelihood(self):
        d=tiny()
        for family in ['static_level','static_selectivity','normal_selectivity']:
            m=static_models.Static(4,3,family);z,lp,_=m.decode(m.start(10),d)
            p,q=static_models.static_filter(d['y'],d['ptr'],d['period'],z,lp)
            exact=logsumexp(static_models.static_ll(d['y'],d['ptr'],z,lp),axis=1)
            np.testing.assert_allclose(-np.bincount(d['ids'],weights=ma.losses(d['y'],p)),exact,atol=1e-10)

    def test_receipt_forecasts_use_only_prior_outcomes(self):
        d=tiny();m=hmm.Layout(4,3,3,'gate',[1,2]);v=m.start(11)
        fit=dict(family='gate',J=3,parameters=v.tolist())
        p,extra=hmm.predict(fit,d)
        observed=np.where(d['H'][:,1]==1,extra['receipt_input_1'],extra['receipt_input_0'])
        active=np.ones(len(p),bool);active[d['ptr'][:-1]]=False
        np.testing.assert_allclose(observed[active],p[active],atol=1e-12)
        for r in np.flatnonzero(active):
            flipped=dict(d);flipped['y']=d['y'].copy();flipped['y'][r:]=1-flipped['y'][r:]
            _,other=hmm.predict(fit,flipped)
            for k in ('receipt_input_0','receipt_input_1'):
                self.assertAlmostEqual(extra[k][r],other[k][r],places=12)

    def test_nested_embeddings_preserve_probabilities(self):
        d=tiny()
        for family in ['gate','willingness']:
            m=hmm.Layout(4,3,3,family,[1,2]);v=m.start(6)
            fit=dict(family=family,J=3,seed=6,parameters=v.tolist())
            w=hmm.embed(fit,'unrestricted',d);other=hmm.Layout(4,3,3,'unrestricted',[1,2])
            a=m.probabilities(v,d);b=other.probabilities(w,d)
            for x,y in zip(a[1:],b[1:]):np.testing.assert_allclose(x,y,atol=1e-14)

    def test_shared_account_or_date_covariance_against_pair_sum(self):
        rng=np.random.default_rng(5);i=np.array([1,1,3,4,6,8]);j=np.array([2,3,4,2,7,1]);day=np.array([1,2,1,3,3,2])
        scores=rng.normal(size=(6,3));codes=rt.cmp.covariance_codes(i,j,day)
        pair=np.zeros((6,6))
        for a in range(6):
            for b in range(6):pair[a,b]=bool(set([i[a],j[a]])&set([i[b],j[b]])) or day[a]==day[b]
        np.testing.assert_allclose(rt.fs.shared_meat(scores,codes,True),scores.T@pair@scores,atol=1e-12)

    def test_future_join_timing_same_opponent_and_empty_followup(self):
        db=duckdb.connect();anchor=1704067200000
        iv=pd.DataFrame(dict(row_id=[0,1],recipient_id=[10,99],opponent_id=[20,98],game_id=['anchor','empty'],anchor_ms=[anchor,anchor]))
        # First two otherwise qualifying choices are excluded: same benefactor or game began before exposure.
        src=pd.DataFrame(dict(game_id=['same','prior_start','first','later','beyond'],chooser_user_id=[10]*5,
          disconnected_user_id=[20,30,31,32,33],api_last_move_at_ms=anchor+np.array([1,2,3,40,95])*prep.DAY,
          utc_ms=anchor+np.array([.5,-.1,2.5,39.,94.])*prep.DAY,archive_ordinal=np.arange(5),board=[2]*5,y=[1,1,0,1,1]))
        db.register('iv',iv);db.register('source',src);out=db.execute(rt.future_sql()).fetchdf().sort_values('row_id')
        self.assertEqual(out.iloc[0].n_competitive_7,1);self.assertEqual(out.iloc[0].g_competitive_90,1)
        self.assertEqual(out.iloc[0].first_choice['gid'],'first');self.assertEqual(out.iloc[1].n_competitive_90,0)
        db.close()

    def test_receipt_build_strict_prior_history_and_resume(self):
        anchor=1704067200000;start=anchor-3600000
        src=pd.DataFrame(dict(game_id=['prior','at_start','during','future'],chooser_user_id=[10]*4,
          disconnected_user_id=[30]*4,api_last_move_at_ms=[start-1,start,start+1,anchor+prep.DAY],
          utc_ms=[start-100,start-100,start-100,anchor+100],archive_ordinal=np.arange(4),
          board=[2]*4,y=[1,1,1,0]))
        iv=pd.DataFrame(dict(row_id=[0,1],recipient_id=[10,99],opponent_id=[20,98],game_id=['anchor','empty'],
          anchor_ms=[anchor]*2,archive_start_ms=[start]*2,complete90=[True]*2,reached=[True,False],
          y=[False,False],outcome_gid=['future',None],outcome_t=pd.Series([anchor+prep.DAY,None],dtype='Int64')))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=root/'PRIVATE';report=root/'report';private.mkdir();report.mkdir()
            path=root/'iv.parquet';iv.to_parquet(path,index=False)
            db=duckdb.connect();db.register('source',src)
            out=rt.build(db,path,private,report,'toy_receipt');a=pd.read_parquet(out)
            self.assertEqual(a.prior_main_n.tolist(),[1,0]);self.assertEqual(a.prior_main_g.tolist(),[1,0])
            self.assertEqual(a.n_competitive_90.tolist(),[1,0])
            pd.testing.assert_frame_equal(a,pd.read_parquet(rt.build(db,path,private,report,'toy_receipt')))
            db.close()

    def test_receipt_iv_against_explicit_fixed_effect_projection(self):
        rng=np.random.default_rng(164);n=3000;anchor=1704067200000
        d=dict(recipient_id=rng.integers(0,1200,n),opponent_id=rng.integers(1200,2400,n),
          recipient_rating=rng.uniform(1450,1750,n),opponent_rating=rng.uniform(1450,1750,n),
          n_7d=rng.poisson(30,n),counterparts_7d=rng.poisson(20,n),expected_7d=rng.uniform(.01,.1,n),
          pre_games_30d=rng.poisson(60,n),month_code=np.zeros(n),tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n),
          archive_start_ms=anchor+rng.integers(0,20,n)*prep.DAY,adjusted_7d=rng.normal(0,.1,n))
        for days in (30,90):
            d[f'fair_{days}']=rng.poisson(20,n);d[f'kind_{days}']=rng.binomial(d[f'fair_{days}'],.03)
            for name in ('disconnect','receipt','claim'):d[f'{name}_{days}']=rng.poisson(5,n)
        d['received']=rng.binomial(1,expit(-1+8*d['adjusted_7d'])).astype(bool)
        y=rng.binomial(1,expit(-2+.5*d['received']+.001*(d['recipient_rating']-1600)))
        rows,scores,idx=rt.fit_group(d,np.ones(n,bool),{'next_grant_90':y.astype(float)},'synthetic')
        self.assertTrue(rows[0]['supported']);self.assertEqual(len(idx),n)
        xs,_,_,_,groups,_=rt.es.controls(d,True)
        Z=np.column_stack(xs+[np.ones(n)]+[(g==v).astype(float) for g in groups for v in np.unique(g)[1:]])
        raw=np.column_stack([d['adjusted_7d'],d['received'],y]);res=raw-Z@np.linalg.lstsq(Z,raw,rcond=1e-11)[0]
        z,t,yy=res.T;beta=(z@yy)/(z@t);influence=100*z*(yy-beta*t)/(z@t)
        codes=rt.cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1])
        se=np.sqrt(rt.fs.shared_meat(influence,codes,True)[0,0])
        self.assertAlmostEqual(rows[0]['effect'],100*beta,places=7)
        self.assertAlmostEqual(rows[0]['SE'],se,places=7)
        np.testing.assert_allclose(scores[:,0],influence,rtol=1e-7,atol=1e-9)


def fixture(N=300,T=48):
    rng=np.random.default_rng(771);chooser=np.repeat(np.arange(1000,1000+N),T);n=len(chooser)
    months=np.array(prep.MONTHS);mi=np.tile(np.repeat(np.arange(24),T//24),N)
    starts=np.array([pd.Timestamp(m+'-01',tz='UTC').value//1000000 for m in months])[mi]
    starts+=np.tile(np.arange(T)%2,N)*8*prep.DAY+np.repeat(np.arange(N)%9,T)*10000
    board_cp=rng.choice([-500,-200,0,200,500],n,p=[.45,.1,.3,.08,.07]);board=np.select([board_cp<=-300,board_cp< -100,board_cp<=100,board_cp<300],[0,1,2,3],4)
    ply=rng.choice([2,4,20,30,60],n);latent=rng.choice([0,1],N,p=[.8,.2])
    prob=expit(-6.2+3*latent[chooser-1000]+1.2*(board>=2)+.3*(ply==2))
    y=rng.binomial(1,prob).astype(bool)
    return pd.DataFrame(dict(month=months[mi],game_id=['synthetic_'+str(j) for j in range(n)],
      chooser_user_id=chooser,disconnected_user_id=1000+(chooser-999)%N,
      chooser_username_norm=['synthetic_user_'+str(i) for i in chooser],
      disconnected_username_norm=['synthetic_user_'+str(i) for i in 1000+(chooser-999)%N],
      api_created_at_ms=starts,api_last_move_at_ms=starts+1200000,utc_ms=starts,archive_ordinal=np.arange(n),
      outcome_kind_draw=y,kind_draw=y,engine_eval_cp_disconnected=board_cp,ply_count=ply,
      api_status='timeout',five_second_rule_passed=True,sf100k_nodes_requested=100000,
      api_speed=rng.choice(['blitz','rapid'],n),chooser_color=rng.choice(['white','black'],n),
      chooser_elo=rng.integers(1000,2200,n),disconnected_elo=rng.integers(1000,2200,n),
      chooser_pre_rd_v2=rng.uniform(40,80,n),disconnected_pre_rd_v2=rng.uniform(40,80,n),
      chooser_pre_sigma_v2=.06,disconnected_pre_sigma_v2=.06,
      chooser_draw_payoff_v2=rng.normal(0,5,n),chooser_win_premium_v2=rng.uniform(5,20,n),
      chooser_clock_last_obs_s=rng.uniform(5,300,n),disconnected_clock_last_obs_s=rng.uniform(5,300,n)))


def smoke():
    import auxiliary_tests as aux
    root=Path(tempfile.mkdtemp(prefix='construal_synthetic_'));private=root/'PRIVATE';report=root/'report'
    private.mkdir();report.mkdir();df=fixture(N=600)
    # A game archived in October but anchored in November must not enter prior giving.
    crossing=df.iloc[[0]].copy();crossing['game_id']='synthetic_boundary';crossing['month']='2024-10'
    crossing['api_created_at_ms']=prep.SPLIT-3600000;crossing['utc_ms']=prep.SPLIT-3600000
    crossing['api_last_move_at_ms']=prep.SPLIT+60000;crossing['archive_ordinal']=len(df)
    crossing['outcome_kind_draw']=True;crossing['kind_draw']=True
    df=pd.concat([df,crossing],ignore_index=True);path=root/'source.parquet';df.to_parquet(path,index=False)
    db=duckdb.connect();db.execute('SET threads=1');prep.source_view(db,[path])
    seq,cohort=prep.prepare(db,private,report,'synthetic_v1',250,250,64,300)
    before=pd.read_parquet(seq);after=prep.prepare(db,private,report,'synthetic_v1',250,250,64,300)[0]
    pd.testing.assert_frame_equal(before,pd.read_parquet(after))
    require=__import__('util').require
    require(not set(before[before.cohort=='development'].chooser)&set(before[before.cohort=='evaluation'].chooser),'Cohort overlap')
    require((before.qualifying_receipts<=before.receipt_risks).all(),'Receipt conservation')
    hist=pd.read_parquet(private/'accounts.parquet').set_index('chooser').g_train.sort_index()
    actual=df[df.api_last_move_at_ms<prep.SPLIT].groupby('chooser_user_id').outcome_kind_draw.sum().sort_index()
    np.testing.assert_array_equal(hist.to_numpy(),actual.to_numpy())
    prep.ply2_tables(db,report);aux.ply2_regression(db,report)
    args=types.SimpleNamespace(support_grid=[2],normal_grid=[3],starts=2,seed=34,maxiter=25,ridge=1e-5,workers=2,
      recovery_accounts=60,recovery_reps=1,bootstrap_refits=1)
    fits,full,path_full=ma.select_fit(before,private,report,'synthetic_v1',args)
    ev,d,pred,details,primary=ma.score(before,fits,private,report,'synthetic_v1')
    ma.bootstrap_refits(full,path_full,ev,d,fits,pred,private,report,'synthetic_v1',args)
    ma.recovery(before,private,report,'synthetic_v1',args)
    # A toy returned-profile snapshot exercises all four held-out Patron fits.
    profile=df[['chooser_username_norm']].drop_duplicates().rename(columns={'chooser_username_norm':'username_norm'})
    profile['returned']=True;profile['patron']=np.arange(len(profile))%4==0;profile['created_at_ms']=1600000000000
    profilepath=root/'profiles.parquet';profile.to_parquet(profilepath,index=False)
    patron_status=aux.patron(db,profilepath,before,fits,private,report)
    require(patron_status['status']=='SELECTED_SNAPSHOT_PREDICTION_COMPLETE','Patron validation branch did not run')
    require(all(np.isfinite(p).all() and (p>0).all() and (p<1).all() for p in pred.values()),'Invalid held-out probabilities')
    (report/'SYNTHETIC_ONLY.txt').write_text('Software validation only; no production estimates. Optimisation iterations intentionally capped.\n')
    from run_construal import package_report
    package_report(report,root,'synthetic_smoke')
    print('END_TO_END_SYNTHETIC_OK',root,flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--smoke',action='store_true');a=ap.parse_args()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(NumericalTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    if a.smoke:smoke()
    print('CONSTRUAL_OFFLINE_TESTS_OK',flush=True)
