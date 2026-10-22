"""Independent numerical checks and integration tests; synthetic inputs only."""
from __future__ import annotations
import contextlib, io as stringio, itertools, tempfile, unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from next_common import *

def fixture(root,n=9600):
    rng=np.random.default_rng(160914);chooser=np.arange(n)%240
    months=pd.date_range('2023-11-01',periods=24,freq='MS',tz='UTC');mi=rng.integers(0,24,n)
    start=months[mi].asi8//1000000+(np.arange(n)%20)*86400000
    elo=rng.integers(1200,2501,n);opp=elo+rng.integers(-590,591,n);rd=rng.uniform(35,80,n);ord_=rng.uniform(35,80,n)
    gj=1/np.sqrt(1+3*(ord_/173.7178)**2/np.pi**2);e=1/(1+np.exp(-gj*(elo-opp)/173.7178))
    k=173.7178*gj/(1/(rd/173.7178)**2+gj**2*e*(1-e));pay=k*(.5-e);premium=k*.5
    cp=rng.integers(-590,591,n);fair=cp>=-100;worse=cp<=-300
    kind=rng.random(n)<np.where(chooser%3==0,.22,.025);ply=rng.integers(2,100,n)
    d={'month':months[mi].strftime('%Y-%m').to_numpy(),'game_id':[f'{i:08d}' for i in range(n)],
      'chooser_user_id':chooser+1,'disconnected_user_id':rng.integers(300,501,n),'chooser_username_norm':['fixture_'+str(x) for x in chooser],
      'disconnected_username_norm':['opponent_'+str(x) for x in range(n)],'utc_ms':start,'api_last_move_at_ms':start+120000,
      'archive_ordinal':np.arange(n),'kind_draw':kind,'outcome_kind_draw':kind,'timeout_chooser_win':~kind,
      'timeout_draw_no_mating_material':np.zeros(n,bool),'timeout_chooser_loss':np.zeros(n,bool),
      'engine_eval_cp_disconnected':cp.astype(float),'engine_eval_cp_disconnected_capped600':cp.astype(float),
      'fair_competitive':fair,'clearly_worse':worse,'excluded_middle':~(fair|worse),
      'engine_fairness_bin':np.select([cp>=300,cp>100,cp>=-100,cp>-300],['disconnected_clearly_better','disconnected_better','roughly_equal','modestly_worse_excluded'],default='clearly_worse'),
      'chooser_draw_payoff_v2':pay,'chooser_win_premium_v2':premium,'chooser_win_payoff_v2':pay+premium,
      'draw_nonnegative':pay>=0,'draw_costly':pay<0,'draw_strict_positive':pay>0,
      'api_speed':rng.choice(['bullet','blitz','rapid'],n),'tournament_like_event':np.ones(n,bool),
      'chooser_elo':elo,'disconnected_elo':opp,'rating_gap':elo-opp,'avg_rating':(elo+opp)/2,
      'chooser_pre_rd_v2':rd,'disconnected_pre_rd_v2':ord_,'ply_count':ply,'material_advantage_chooser':rng.integers(-10,11,n),
      'chooser_clock_last_obs_s':rng.uniform(5,180,n),'disconnected_clock_last_obs_s':rng.uniform(5,180,n),
      'tc_base_s':rng.choice([60.,180.,600.],n),'tc_inc_s':rng.choice([0.,2.],n),'time_control':['180+2']*n}
    d['disconnected_clock_last_obs_s'][::43]=np.nan
    schema=pa.schema([pa.field(s['name'],pa.type_for_alias(s['type'])) for s in read(ROOT/'authority/STAGE07_SCHEMA.json')])
    arrays=[]
    for field in schema:
        arrays.append(pa.array(d[field.name],type=field.type,from_pandas=True) if field.name in d else pa.nulls(n,type=field.type))
    table=pa.Table.from_arrays(arrays,schema=schema);root=Path(root);root.mkdir(parents=True,exist_ok=True)
    paths=[];mr=[]
    for i,m in enumerate(months.strftime('%Y-%m')):
        p=root/(m+'.parquet');pq.write_table(table.filter(pa.array(mi==i)),p,compression='zstd');paths.append(str(p));mr.append({'month':m,'path':str(p)})
    a={'rows':n,'kind_draws':int(kind.sum()),'fair_rows':int(fair.sum()),'fair_kind_draws':int(kind[fair].sum()),
      'choosers':len(set(chooser)),'fair_choosers':len(set(chooser[fair])),'fair_kind_choosers':len(set(chooser[fair&kind]))}
    return {'panels':paths,'month_records':mr,'authority':a},table

class AdapterTests(unittest.TestCase):
    def test_utc_is_explicit(self):
        from unittest.mock import patch
        import duckdb
        original=duckdb.connect
        def inherited(*a,**k):
            c=original(*a,**k);c.execute("SET TimeZone='America/Toronto'");return c
        with tempfile.TemporaryDirectory() as t,patch.object(duckdb,'connect',side_effect=inherited):
            c=db(t,'256MB',1)
            self.assertEqual(c.execute("SELECT current_setting('TimeZone')").fetchone()[0],'UTC');c.close()

    def test_checksum_resume_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'a.txt').write_text('first');finish_stage(p,'fixture',{'status':'COMPLETE'})
            self.assertIsNotNone(stage_complete(p,'fixture'))
            (p/'a.txt').write_text('other')
            with self.assertRaisesRegex(RuntimeError,'checksum'):stage_complete(p,'fixture')
            with self.assertRaisesRegex(RuntimeError,'escapes'):safe_child(p,'../elsewhere')

    def test_core_scaling_and_collinearity(self):
        import core_stage
        m=load(ROOT/'source/core/08_make_core_paper_results.py','test_core8')
        rng=np.random.default_rng(65);n=1200;g=np.arange(n)%60;x=rng.normal(size=n);z=rng.normal(size=n)
        y=.4*x+.2*z+rng.normal(size=60)[g]+rng.normal(0,.1,n)
        audit=[];fit=core_stage.guarded_fit(m,8,audit)
        r=fit(y,np.column_stack([x,z*1e7,np.ones(n)]),['target','big_control','constant'],g,fixed_effect_codes=(g,))
        explicit=np.column_stack([x,z,pd.get_dummies(g,dtype=float).to_numpy()]);beta=np.linalg.lstsq(explicit,y,rcond=None)[0]
        self.assertAlmostEqual(r['coefficients']['target'],beta[0],places=10)
        resid=y-explicit@np.linalg.lstsq(explicit,y,rcond=None)[0]
        scores=np.array([explicit[g==j].T@resid[g==j] for j in range(60)])
        inv=np.linalg.inv(explicit.T@explicit)
        covariance=(60/59)*((n-1)/(n-2))*inv@(scores.T@scores)@inv
        self.assertAlmostEqual(r['covariance'][0,0],covariance[0,0],places=12)
        self.assertTrue(np.isnan(r['coefficients']['constant']))
        core_stage.guard_contrasts(m)
        self.assertTrue(np.isfinite(m.linear_combination(r,{'target':1.})['se']))
        dup=fit(y,np.column_stack([x,2*x,z]),['one','two','control'],g,fixed_effect_codes=(g,))
        self.assertTrue(np.isnan(dup['coefficients']['one']) and np.isnan(dup['coefficients']['two']))
        self.assertAlmostEqual(dup['coefficients']['control'],beta[1],places=10)

    def test_core_and_robustness_full_producer_path(self):
        import core_stage
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);sample,table=fixture(root/'inputs')
            self.assertEqual(table.num_columns,157)
            args=SimpleNamespace(threads=2,memory='1GB')
            with contextlib.redirect_stdout(stringio.StringIO()):
                a=core_stage.run('core',sample,root,args);b=core_stage.run('robustness',sample,root,args)
            self.assertGreater(a['fits'],10);self.assertGreaterEqual(b['fits'],10)
            qa=read(root/'public/core/SOURCE_QA.json')
            self.assertEqual(qa['core']['rows'],len(table))
            self.assertTrue((root/'public/core/tables/table09_second_half_by_first_half_behavior.csv').is_file())

    def test_arena_exposure_rank_before_arm_and_no_skip(self):
        import iv_stage as iv
        with tempfile.TemporaryDirectory() as t:
            sample,table=fixture(Path(t)/'inputs',n=240)
            f=table.slice(0,3).to_pandas();f['disconnected_user_id']=500;f['utc_ms']=[10,20,30]
            f['api_last_move_at_ms']=[15,25,35];f['fair_competitive']=True;f['kind_draw']=[False,True,True];f['timeout_chooser_win']=[False,False,False]
            p=Path(t)/'first.parquet';f.to_parquet(p,index=False);c=db(Path(t)/'spill','256MB',1)
            result=c.execute(iv.exposure_query([p])).fetchdf();c.close()
            self.assertEqual(len(result),1);self.assertEqual(result.iloc[0]['game_id'],'00000000');self.assertFalse(result.iloc[0]['arm_eligible'])
        start=int(iv.STARTS[4]);h={'j':np.array([1,1,1]),'i':np.array([3,4,5]),'t':np.array([start+100,start+200,start+300]),
          'start':np.array([start+80,start+180,start+280]),'gid':np.array(['first001','arena002','arena003']),
          'ord':np.arange(3),'y':np.array([False,True,True]),'fair':np.ones(3,bool)}
        qd={'sample_row':np.array([0]),'recipient_id':np.array([1]),'opponent_id':np.array([2]),
          'archive_start_ms':np.array([start-100]),'anchor_ms':np.array([start]),'game_id':np.array(['expose00'])}
        out=iv.select_next(h,qd,np.array(['arena002','arena003']))
        self.assertEqual(out['outcome_gid'][0],'first001');self.assertFalse(out['next_arena_reached'][0]);self.assertFalse(out['next_arena_y'][0])
        h['start'][0]=start-1
        out=iv.select_next(h,qd,np.array(['arena002','arena003']))
        self.assertEqual(out['outcome_gid'][0],'arena002');self.assertTrue(out['next_arena_y'][0])

    def test_episode_builder_missing_clock_and_spawn(self):
        from episodes_stage import engine
        m=engine();saved={k:getattr(m,k) for k in ['EXPECTED_B1_CHOOSERS','EXPECTED_B1_OPPORTUNITIES','EXPECTED_B1_KIND_DRAWS',
          'EXPECTED_STAGE07_FAIR_CHOOSERS','EXPECTED_STAGE07_FAIR_KIND_CHOOSERS','EXPECTED_STAGE07_FAIR_ROWS',
          'EXPECTED_STAGE07_FAIR_KIND_DRAWS','B1_RANDOMIZATIONS','B1_RANDOMIZATION_BATCH']}
        try:
            with tempfile.TemporaryDirectory() as t:
                root=Path(t);sample,table=fixture(root/'inputs',n=2400);state=root/'state';state.mkdir()
                c=db(root/'spill','512MB',1);n,g,k=c.execute('SELECT count(*),count(DISTINCT chooser_index),sum(kind_draw::INTEGER) FROM ('+m.b1_sample_sql(sample['panels'])+')').fetchone();c.close()
                for key,val in {'EXPECTED_B1_CHOOSERS':g,'EXPECTED_B1_OPPORTUNITIES':n,'EXPECTED_B1_KIND_DRAWS':k,
                  'EXPECTED_STAGE07_FAIR_CHOOSERS':sample['authority']['fair_choosers'],'EXPECTED_STAGE07_FAIR_KIND_CHOOSERS':sample['authority']['fair_kind_choosers'],
                  'EXPECTED_STAGE07_FAIR_ROWS':sample['authority']['fair_rows'],'EXPECTED_STAGE07_FAIR_KIND_DRAWS':sample['authority']['fair_kind_draws'],
                  'B1_RANDOMIZATIONS':19,'B1_RANDOMIZATION_BATCH':10}.items():setattr(m,key,val)
                payload={'stage07':{'paths':sample['panels']},'threads':1,'memory_limit':'512MB','resume_config_sha256':'SYNTHETIC_ONLY','b1_workers':2}
                path,support=m.build_or_authenticate_b1_sample(payload,state)
                r=m.run_b1_conditional_randomization(payload,state,path,support)
                again=m.run_b1_conditional_randomization(payload,state,path,support)
                self.assertEqual(r['null_distribution_sha256'],again['null_distribution_sha256'])
                self.assertEqual(len(r['rows']),3);self.assertTrue(all(x['randomizations']==19 for x in r['rows']))
        finally:
            for k,v in saved.items():setattr(m,k,v)

    def test_original_iv_numerics_and_chronology(self):
        import iv_stage
        test=load(ROOT/'source/iv/test_rebuild.py','original_iv_tests')
        suite=unittest.defaultTestLoader.loadTestsFromModule(test)
        result=unittest.TextTestRunner(stream=stringio.StringIO()).run(suite)
        self.assertTrue(result.wasSuccessful(),str(result.errors)+str(result.failures))

    def test_original_patron_rebuild_with_stale_metadata_and_missing_control(self):
        import patron_stage
        m=patron_stage.modules();f=load(ROOT/'source/patron/source/synthetic_fixture_v101.py','patron_fixture')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);args=SimpleNamespace(threads=2,memory_limit='512MB');panel,users=f.build_panel(groups=80)
            panel['tournament_like_event']=True;panel['utc_ms']=1700000000000+np.arange(len(panel))*1000
            panel['game_id']=[f'{i:08d}' for i in range(len(panel))];snap=f.build_snapshot(panel,users)
            paths=[]
            for month,chunk in panel.groupby('month'):
                p=root/(month+'.parquet');chunk.to_parquet(p,index=False);paths.append({'month':month,'path':str(p)})
            c=db(root/'spill','512MB',1);c.register('input_panel',panel);c.execute('CREATE VIEW stage07 AS SELECT * FROM input_panel')
            m.prior.planner.build_chooser_summary(c);m.prior.planner.build_matching(c)
            target=c.execute('SELECT * FROM acquisition_users').fetchdf();acq=root/'acq.parquet';target.to_parquet(acq,index=False);c.close()
            missing=target.loc[target.acquisition_role=='control','username_norm'].iloc[0]
            snap=snap.loc[snap.username_norm!=missing].copy();snap['total_opps']=999999;snap['match_cell']='stale'
            sp=root/'snapshot.parquet';snap.to_parquet(sp,index=False);design=root/'design';design.mkdir()
            m.build_design(design,args,{'month_records':paths},acq,sp,len(target))
            c=db(root/'spill2','512MB',1);frame=m.load_frames(c,design/'chooser_design_features_private.parquet',sp);c.close()
            self.assertEqual(len(frame),len(target));self.assertNotIn('stale',set(frame.match_cell))
            self.assertEqual(frame.total_opps.unique().tolist(),[36]);missingrow=frame.loc[frame.username_norm==missing].iloc[0]
            self.assertFalse(missingrow.returned);self.assertTrue(pd.isna(missingrow.patron))
            bounds=m.missing_outcome_bounds(frame);self.assertGreater(bounds['control_missing'],0)
            audit=[];patron_stage.guard_patron(m,audit);public=root/'public';support=read(design/'preoutcome_support_receipt.json')
            with contextlib.redirect_stdout(stringio.StringIO()):
                try:m.main_models(frame,root/'state','SYNTHETIC_ONLY',public,support)
                except RuntimeError as e:
                    if 'Required main-paper estimate is not identified:' not in str(e):raise
                m.corrected_date_models(frame,root/'state','SYNTHETIC_ONLY',public)
            self.assertEqual(len(read(public/'chooser_models.json')),34);self.assertEqual(len(read(public/'corrected_dates_models.json')),4)

def run_tests():
    start=time.monotonic();suite=unittest.defaultTestLoader.loadTestsFromTestCase(AdapterTests)
    import integration_tests
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(integration_tests))
    import repair_tests
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(repair_tests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(f'ARENA_NEXT_SELF_TEST: tests={result.testsRun}; success={result.wasSuccessful()}; seconds={time.monotonic()-start:.2f}',flush=True)
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(run_tests())
