"""Meaningful synthetic checks; expected runtime 15-60 seconds.
Run: project_python -m unittest discover -s tests -v
No project data are used and no synthetic result is certified as real evidence.
"""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
from common import *
import engine
from panel import normalize_month
from analysis import dose_month,summarize,visibility_status
from grace import grace_month
from run import PLAN,plot_weekly,write_report

REF=PACKAGE/"vendor/stage06_reference_19ad.py"

class MathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.prod=load_stage06(REF,REFERENCE_SHA)

    def test_vectorized_against_source_update(self):
        rng=np.random.default_rng(92)
        for _ in range(100):
            r,opp=rng.uniform(600,2700,2);rd,orrd=rng.uniform(45,500,2);c=rng.choice([-1.,1.])
            for a in (0.,ADVANTAGE):
                E,K,d,w=payoffs(r,opp,rd,orrd,c,a)
                for score,expected in ((.5,d),(1.,w)):
                    actual=self.prod.update_one(r,rd,.09,opp,orrd,score,.75,45.,500.,.1,c*a/2,-c*a/2)[0]
                    self.assertAlmostEqual(float(expected),actual,places=9)

    def test_symmetric_zero_thresholds_and_spread(self):
        for color in (-1.,1.):
            E,K,d,w=payoffs(1500,1500+color*ADVANTAGE,45,45,color,ADVANTAGE)
            self.assertAlmostEqual(float(E),.5,places=14)
            self.assertAlmostEqual(float(d),0,places=12)
        old=payoffs(1500,1500,45,45,1,0)
        new=payoffs(1500,1500,45,45,1,ADVANTAGE)
        self.assertGreater(float(new[3]-new[2]-(old[3]-old[2])),0)
        self.assertLess(abs(float(new[2]-old[2])),.25)

    def make_args(self,ow,ob,ts):
        n=len(ts)
        return [np.zeros(n,np.int64),np.ones(n,np.int64),np.full(n,1500.),np.full(n,1500.),np.asarray(ts,np.int64),np.ones(n,np.int8),np.asarray(ow,float),np.asarray(ob,float)]

    def state(self):return [np.full(2,80.,np.float32),np.full(2,.09,np.float32),np.ones(2,np.uint32)*10,np.full(2,CUTOFF_MS-86400000,np.int64)]

    def test_both_null_does_not_commit_inflation(self):
        fn,_=engine.configure(self.prod,False);s=self.state();before=[a.copy() for a in s]
        pre=fn(*s,*self.make_args([np.nan],[np.nan],[CUTOFF_MS]))
        self.assertGreater(pre[0,0],before[0][0])
        for a,b in zip(s,before):np.testing.assert_array_equal(a,b)

    def test_one_sided_null_updates_both(self):
        fn,_=engine.configure(self.prod,False);s=self.state()
        fn(*s,*self.make_args([np.nan],[0],[CUTOFF_MS]))
        np.testing.assert_array_equal(s[2],[11,11])
        np.testing.assert_array_equal(s[3],[CUTOFF_MS,CUTOFF_MS])

    def test_cutoff_and_phase(self):
        fn,_=engine.configure(self.prod,False);s=self.state()
        p=fn(*s,*self.make_args([np.nan,np.nan],[np.nan,np.nan],[CUTOFF_MS-1,CUTOFF_MS]))
        self.assertEqual(p[0,8],0.)
        self.assertLess(p[1,8],0.)
        self.assertGreater(p[1,9],0.)
        self.assertEqual(phase(np.array([BRACKET_START_MS-1,BRACKET_START_MS,CUTOFF_MS])).tolist(),["pre","transition_bracket","post"])

    def test_jit_parity_when_available(self):
        try:import numba
        except ImportError:self.skipTest("Numba not installed: Python backend remains supported")
        fn,backend=engine.configure(self.prod,True)
        self.assertEqual(backend,"numba_verified")
        s=self.state();result=fn(*s,*self.make_args([0],[0],[CUTOFF_MS]))
        self.assertLess(result[0,8],0)

    def test_invalid_state_fails(self):
        with self.assertRaises(ValueError):payoffs(1500,1500,-1,45,1,0)
        with self.assertRaises(RuntimeError):load_stage06(REF) # not the certified finalizer SHA

    def test_month_checkpoint_restart_preserves_sequence(self):
        fn,_=engine.configure(self.prod,False)
        times=np.arange(10,dtype=np.int64)*86400000+CUTOFF_MS-3*86400000
        args=self.make_args([0,np.nan,0,0,0,0,0,0,0,0],[0,np.nan,0,0,0,0,0,0,0,0],times)
        whole=self.state();wanted=fn(*whole,*args)
        split=self.state();first=fn(*split,*[a[:4] for a in args])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'state.parquet'
            write_frame(pd.DataFrame({'user_id':np.arange(2),'rd':split[0],'sigma':split[1],'games_seen':split[2],'last_seen_ms':split[3]}),p)
            from types import SimpleNamespace
            restored=self.prod.load_checkpoint(p,2,SimpleNamespace(default_rd=500.,default_sigma=.09))
            second=fn(*restored,*[a[4:] for a in args])
        np.testing.assert_array_equal(np.vstack([first,second]),wanted)
        for a,b in zip(restored,whole):np.testing.assert_array_equal(a,b)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.project=self.root/"project";self.work=self.root/"work";self.report=self.root/"report"
        self.report.mkdir(parents=True)
    def tearDown(self):self.tmp.cleanup()

    def source_frame(self,n=12):
        rating=np.repeat(1500.,n);opp=rating+np.linspace(-40,40,n)
        color=np.where(np.arange(n)%2==0,"white","black")
        rd=np.full(n,45.);or_=np.full(n,50.)
        e,k,d,w=payoffs(rating,opp,rd,or_,np.where(color=="white",1,-1),0)
        return pd.DataFrame({"game_id":[f"g{i}" for i in range(n)],"utc_ms":pd.Timestamp('2025-01-05').value//10**6+np.arange(n)*86400000,
          "chooser_username_norm":[f"p{i}" for i in range(n)],"disconnected_username_norm":[f"q{i}" for i in range(n)],
          "chooser_color":color,"api_speed":"blitz","chooser_elo":rating,"disconnected_elo":opp,
          "outcome_kind_draw":np.arange(n)%5==0,"engine_eval_cp_disconnected":0,
          "chooser_pre_rd_v2":rd,"disconnected_pre_rd_v2":or_,"chooser_draw_payoff_v2":d,"chooser_win_premium_v2":w-d,
          "chooser_user_id":np.arange(n),"both_ratingdiff_null":False})

    def normalize_fixture(self,df=None):
        if df is None:df=self.source_frame()
        path=self.root/"source.parquet";write_frame(df,path)
        item={"month":"2025-01","kind":"certified_stage07","paths":[str(path)],"expected_sha256":sha(path),"expected_rows":len(df)}
        rec=normalize_month((str(self.project),str(self.work),item,256))
        return path,item,rec

    def test_parquet_normalization_dose_and_resume(self):
        path,item,first=self.normalize_fixture()
        second=normalize_month((str(self.project),str(self.work),item,256))
        self.assertEqual(first["output"]["sha256"],second["output"]["sha256"])
        write_frame(pd.DataFrame({"user_id":np.arange(12),"speed":"blitz","games_seen":200}),self.work/"established_2023_10.parquet")
        dose=dose_month((str(self.project),str(self.work),"2025-01",256))
        self.assertEqual(dose["rows"],12);self.assertEqual(dose["valid_state_rows"],12)
        df=pd.read_parquet(dose["output"]["path"])
        np.testing.assert_allclose(df.delta_kappa,df.d_C-df.d_G)
        self.assertLess(dose["stored_old_draw_max_abs_difference"],1e-9)
        self.assertTrue(df.established_at_2023_10.all())
        # Restart is bound to input content metadata and rejects a changed source.
        raw=self.source_frame();raw.loc[0,"chooser_elo"]=1400;write_frame(raw,path)
        with self.assertRaises(RuntimeError):normalize_month((str(self.project),str(self.work),item,256))

    def test_duplicate_join_rejected(self):
        df=self.source_frame();df.loc[1,"game_id"]=df.loc[0,"game_id"]
        with self.assertRaises(RuntimeError):self.normalize_fixture(df)

    def test_extension_timestamp_join_uses_ids_not_row_order(self):
        df=self.source_frame(4).drop(columns=['utc_ms']).rename(columns={
          'chooser_username_norm':'candidate_chooser','disconnected_username_norm':'likely_disconnected_player',
          'chooser_color':'candidate_chooser_color','chooser_elo':'candidate_chooser_elo','disconnected_elo':'likely_disconnected_elo',
          'engine_eval_cp_disconnected':'sf100k_eval_cp_disconnected'})
        source=self.root/'sf/part_00000.parquet';write_frame(df,source)
        write_json(source.with_suffix('.done.json'),{'error_rows':0,'rows':4,'part_sha256':sha(source)})
        aux=self.project/'derived/replication/pgn_timeforfeit_candidates/month=2025-11/api_target_candidates_ge5s_or_missing.parquet'
        write_frame(pd.DataFrame({'game_id':['g3','g2','g1','g0'],'utc_date':['2025.11.04','2025.11.03','2025.11.02','2025.11.01'],'utc_time':'00:00:00'}),aux)
        item={'month':'2025-11','kind':'sf100k_extension','paths':[str(source)]}
        rec=normalize_month((str(self.project),str(self.work),item,256))
        out=pd.read_parquet(rec['output']['path']).set_index('game_id')
        self.assertEqual(out.loc['g0','utc_ms'],pd.Timestamp('2025-11-01').value//10**6)
        self.assertEqual(out.loc['g3','utc_ms'],pd.Timestamp('2025-11-04').value//10**6)

    def test_post_replay_chooser_side_join_and_missing_state(self):
        _,_,nr=self.normalize_fixture()
        base=pd.read_parquet(nr['output']['path'])
        base['utc_ms']=CUTOFF_MS+100000+np.arange(len(base))*1000
        base['month']='2025-11';base['source_kind']='sf100k_extension'
        month_base=self.work/'base/month=2025-11/opportunities.parquet';write_frame(base,month_base)
        white=base.color.eq('white').to_numpy()
        raw=pd.DataFrame({'game_id':base.game_id,'utc_ms':base.utc_ms,
          'white_id':np.where(white,np.arange(12),100+np.arange(12)),
          'black_id':np.where(white,100+np.arange(12),np.arange(12)),
          'white_elo':np.where(white,base.rating,base.opp_rating),'black_elo':np.where(white,base.opp_rating,base.rating),
          'white_pre_rd':np.where(white,45.,50.),'black_pre_rd':np.where(white,50.,45.),
          'white_prior_games':200.,'black_prior_games':350.,
          'white_last_ms':base.utc_ms-100*86400000,'black_last_ms':base.utc_ms-80*86400000,
          'white_rating_diff':0.,'black_rating_diff':0.})
        for speed in SPEEDS:write_frame(raw if speed=='blitz' else raw.iloc[:0],self.work/f'replay/speed={speed}/month=2025-11/targets.parquet')
        write_frame(pd.DataFrame({'user_id':np.arange(12),'speed':'blitz','games_seen':200}),self.work/'established_2023_10.parquet')
        rec=dose_month((str(self.project),str(self.work),'2025-11',256))
        df=pd.read_parquet(rec['output']['path'])
        self.assertTrue(df.rd.eq(45).all())
        self.assertTrue(df.opp_rd.eq(50).all())
        self.assertTrue(df.loc[df.color.eq('white'),'d_G'].lt(0).all())
        self.assertTrue(df.loc[df.color.eq('black'),'d_G'].gt(0).all())
        self.assertTrue(df.loc[df.color.eq('black'),'prior_games'].eq(350).all())

    def test_self_player_excluded_not_recovered(self):
        df=self.source_frame();df.loc[0,"disconnected_username_norm"]=df.loc[0,"chooser_username_norm"]
        _,_,rec=self.normalize_fixture(df)
        self.assertEqual(rec["self_player_rows_excluded_downstream"],1)
        write_frame(pd.DataFrame({"user_id":[1],"speed":["blitz"],"games_seen":[200]}),self.work/"established_2023_10.parquet")
        d=dose_month((str(self.project),str(self.work),"2025-01",256))
        self.assertEqual(d["rows"],11)

    def test_grace_candidate_denominator_and_material(self):
        month="2026-01";n=20
        cand=self.project/"derived/replication/pgn_timeforfeit_candidates"/f"month={month}"/"api_target_candidates_ge5s_or_missing.parquet"
        frame=pd.DataFrame({"game_id":[f"a{i}" for i in range(n)],"utc_date":"2026.01.30","utc_time":"12:00:00",
          "candidate_chooser_color":"white","fen_after_last_move":"7k/8/8/8/8/8/8/KQ6 w - - 0 1",
          "result":"1-0","disconnected_clock_last_obs_s":10})
        write_frame(frame,cand)
        api_root=self.project/"derived/replication_36m/api_timeout_enrichment_extension"/f"month={month}"
        write_frame(pd.DataFrame({"game_id":frame.game_id,"api_status":["timeout"]*10+["outoftime"]*10,"api_speed":"blitz","api_rated":True}),api_root/"responses/unit-000.parquet")
        write_json(api_root/"_SUCCESS.json",{"final_ok":True})
        out=grace_month((str(self.project),str(self.work),month))
        daily=pd.read_parquet(out["outputs"]["daily"]["path"])
        self.assertEqual(int(daily.targeted_timeforfeit_games.sum()),20)
        self.assertEqual(float(daily.active_share_targeted.iloc[0]),.5)
        self.assertEqual(daily.material_group.iloc[0],"chooser_up_3plus")
        self.assertIn("NOT all",out["denominator"])

    def test_visibility_and_power_not_falsely_certified(self):
        self.assertIsNone(visibility_status()["exact_visibility_share"])
        self.assertIsNone(PLAN["grace_production_cutoff"])
        self.assertTrue(PLAN["power_gate"]["status"].startswith("PENDING"))

    def test_aggregate_report_pipeline(self):
        _,_,nr=self.normalize_fixture()
        write_frame(pd.DataFrame({"user_id":np.arange(12),"speed":"blitz","games_seen":200}),self.work/"established_2023_10.parquet")
        dr=dose_month((str(self.project),str(self.work),"2025-01",256))
        raw=self.work/'replay/speed=blitz/month=2025-11'
        diag=pd.DataFrame({'month':['2025-11']*2,'speed':['blitz']*2,'color':['white']*2,'phase':['pre','post'],'outcome':[.5,.5],'rd_bin':[0,0],'gap_bin':[4,4],
          'n':[10,10],'sum_error':[0.,.1],'sum_abs_error':[3.,3.1],'sum_squared_error':[2.,2.1],
          'abs_gt_1':[0,0],'abs_gt_2':[0,0],'sum_old_abs_error':[3.,4.]})
        write_frame(diag,raw/'diagnostics.parquet')
        write_frame(pd.DataFrame({'hour_ms':[CUTOFF_MS//3600000*3600000],'speed':['blitz'],'n_games':[100],'both_null':[0],'negative_elapsed_sides':[0]}),raw/'hourly_games.parquet')
        summarize(self.work,self.report,2)
        plot_weekly(self.report)
        summary=write_report(self.report,self.work,[nr],[dr],{})
        self.assertFalse(summary['behavioral_estimates_run'])
        m=pd.read_parquet(self.report/'matched_reconstruction.parquet')
        self.assertAlmostEqual(m.mae_difference.iloc[0],.01)
        self.assertTrue((self.report/'weekly_fixed_cohort_difference.svg').exists())

    def test_weekly_plot_keeps_policy_dates_with_pandas3_microsecond_dates(self):
        rows=[]
        for week in ('2025-11-03','2025-11-24','2025-12-29','2026-01-12'):
            for color,grants in (('white',3),('black',2)):
                rows.append({'week':week,'color':color,'opportunities':100,'grants':grants,
                    'board_state':'competitive','established_at_2023_10':True})
        write_frame(pd.DataFrame(rows),self.report/'weekly_color_grant_descriptive.parquet')
        plot_weekly(self.report)
        svg=(self.report/'weekly_fixed_cohort_difference.svg').read_text()
        self.assertIn('Nov 18 convention',svg)
        self.assertIn('Dec 22 announcement',svg)

if __name__=="__main__":unittest.main()
