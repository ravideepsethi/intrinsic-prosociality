"""Scientific and restart invariants. Expected runtime: 10-30 seconds."""
import sys, tempfile, unittest, subprocess, shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from io_tools import *
from prepare import prepare_month,summarize
from power import residual_support,moving_block_noise,empirical_mde,weekly_screen,support_scenario
from grace import grace_month,complete_window_differences,finalize_grace

def put(df,p):
    frame(pd.DataFrame(df),p);return receipt(p)

def make_month(root,month,n=120):
    root=Path(root);first=root/'first';work=root/'followup';rng=np.random.default_rng(73+int(month[-2:]))
    start=ms(month+'-01');next_=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin()).timestamp()*1000)
    utc=np.linspace(start+1000,next_-1000,n).astype(np.int64);color=np.where(np.arange(n)%2==0,'white','black')
    sign=np.where(color=='white',1.,-1.);g=rng.integers(-30,31,n).astype(float)
    E=.5-g/1700;K=rng.uniform(20,30,n);Kn=K*1.0003;En=E+sign*.007
    score=rng.choice([0.,.5,1.],n);ownscore=np.where(color=='white',score,1-score)
    old=K*(.5-E);new=Kn*(.5-En);dc=Kn*(1-En)-K*(1-E)
    po=K*(ownscore-E);pn=Kn*(ownscore-En);current=np.where(utc>=CUTOFF,pn,po)
    observed=np.round(current);observed[3]=np.nan;rd=np.where(np.arange(n)%9==0,220.,45.)
    est=np.arange(n)%11!=0;returning=est&(rd>=200)
    ids=np.arange(n)%20
    d=dict(game_id=[f'{month}_{i}' for i in range(n)],utc_ms=utc,chooser=['u'+str(x) for x in ids],chooser_user_id=ids,
      color=color,speed=np.asarray(SPEEDS)[np.arange(n)%5],rating=np.full(n,1500.),opp_rating=1500+g,
      grant=((ownscore==.5)&(np.arange(n)%3!=0)).astype(float),cp=np.where(np.arange(n)%4==0,-400,0.),
      rd=rd,opp_rd=np.full(n,45.),prior_games=np.full(n,np.nan) if month<'2025-11' else np.full(n,300.),
      gap_days=np.full(n,np.nan) if month<'2025-11' else np.where(returning,200.,1.),
      established_at_2023_10=est,d_G=new-old,d_C=dc,delta_kappa=dc-new+old,K_old=K,E_old=E,K_new=Kn,E_new=En,
      g=g,rd_bin=np.where(rd>=200,4,0),gap_bin=np.searchsorted([-200,-50,-30,-ADVANTAGE,0,ADVANTAGE,30,50,200],g,side='right'),
      old_sign_flip_band=((sign==1)&(g>0)&(g<ADVANTAGE))|((sign==-1)&(g>-ADVANTAGE)&(g<0)),
      valid_state=np.ones(n,bool),chooser_clock=np.full(n,40.),opp_clock=np.full(n,60.),ply=np.full(n,30),
      high_rd_returning_strict=returning if month>='2025-11' else np.zeros(n,bool))
    df=pd.DataFrame(d);dose=first/'dose'/f'month={month}'/'opportunities.parquet';rec=put(df,dose);write_json(dose.with_suffix('.json'),dict(output=rec))
    base=first/'base'/f'month={month}'/'opportunities.parquet';baserec=put(df,base)
    whiteobs=np.where(color=='white',observed,-observed);blackobs=np.where(color=='black',observed,-observed)
    whitepred=np.where(color=='white',current,-current);blackpred=np.where(color=='black',current,-current)
    pool_spec=None
    if month<'2025-11':
        src=root/'sources'/f'{month}.parquet'
        sr=put(dict(game_id=df.game_id,pgn_result=np.where(score==1,'1-0',np.where(score==0,'0-1','1/2-1/2')),
          white_rating_diff_pgn=whiteobs,black_rating_diff_pgn=blackobs,
          white_realized_pred_ratingdiff_v2=whitepred,black_realized_pred_ratingdiff_v2=blackpred),src)
        write_json(base.with_suffix('.json'),dict(output=baserec,authentication=[sr]))
        pool=root/'pool'/f'{month}.parquet';pr=put(dict(game_id=df.game_id.iloc[::2]),pool);pool_spec=dict(path=str(pool),record=pr)
    else:
        write_json(base.with_suffix('.json'),dict(output=baserec,authentication=[]))
        for speed in SPEEDS:
            sel=df.speed==speed;dest=first/'replay'/f'speed={speed}'/f'month={month}'
            tr=put(dict(game_id=df.game_id[sel],result_code=(score[sel]*2).astype(int),white_rating_diff=whiteobs[sel],black_rating_diff=blackobs[sel],white_pred=whitepred[sel],black_pred=blackpred[sel]),dest/'targets.parquet')
            write_json(dest/'_SUCCESS.json',dict(outputs=dict(targets=tr)))
    return (str(root),str(first),str(work),month,pool_spec,384),df

def make_grace(root):
    root=Path(root);first=root/'first';work=root/'followup'
    candidate=root/'derived/replication/pgn_timeforfeit_candidates/month=2026-01/api_target_candidates_ge5s_or_missing.parquet'
    api=root/'derived/replication_36m/api_timeout_enrichment_extension/month=2026-01'
    colors=['white','black','white','white','white','black','white']
    results=['1-0','1/2-1/2','1-0','1/2-1/2','1-0','0-1','1-0']
    candidates=dict(game_id=[f'grace{i}' for i in range(7)],utc_date=['2026.01.30']*7,utc_time=['12:00:00']*7,
       candidate_chooser_color=colors,result=results,disconnected_clock_last_obs_s=[10.,10.,np.nan,8.,5.,np.nan,8.],
       fen_after_last_move=['8/8/8/8/8/8/4K3/4k3 w - - 0 1']*7)
    put(candidates,candidate);write_json(candidate.parent/'_SUCCESS.json',dict(final_ok=True))
    statuses=['timeout']*4+['outoftime']*2+['timeout']
    response=dict(game_id=candidates['game_id'],api_status=statuses,speed=['blitz']*6+['ultraBullet'],rated=[True]*6+[False],
       variant=['standard']*7,winner=['white',None,'white',None,'white','black','white'],is_draw=[False,True,False,True,False,False,False])
    compact=put(response,api/'responses/unit-00000.parquet')
    ck=api/'_checkpoints/unit-00000.success.json';write_json(ck,dict(final_ok=True,unit_index=0,missing_ids=0,artifacts=dict(compact=compact)))
    write_json(api/'_SUCCESS.json',dict(final_ok=True,month='2026-01',production=True,source_rows=7,selected_rows=7,requested_ids=7,returned_unique_ids=7,missing_ids=0,unit_count=1,unit_checkpoint_sha256=[dict(unit_index=0,sha256=sha(ck))],status_counts=dict(timeout=5,outoftime=2)))
    base=first/'base/month=2026-01/opportunities.parquet';r=put(dict(game_id=candidates['game_id'][:4],grant=[0.,1.,0.,0.]),base);write_json(base.with_suffix('.json'),dict(output=r))
    return str(root),str(first),str(work),'2026-01',384

class FollowupTests(unittest.TestCase):
    def test_spawned_full_runner_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for month in MONTHS:make_month(root,month,n=120)
            first=root/'derived/replication_36m/color_change_firstpass_v100';first.parent.mkdir(parents=True)
            shutil.move(root/'first',first)
            write_json(first/'FROZEN_PLAN.json',dict(advantage_elo=ADVANTAGE,color_cutoff_utc='2025-11-18T07:22:00Z'))
            (first/'run.lock').touch()
            driver=root/'spawn_driver.py'
            driver.write_text('import sys,multiprocessing\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(PACKAGE/'code'))+')\nfrom run import main\nif __name__=="__main__":\n multiprocessing.set_start_method("spawn")\n raise SystemExit(main())\n')
            cmd=[sys.executable,str(driver),'--project-root',str(root),'--desktop',str(root/'desktop'),'--workers','3','--memory-gb','4']
            for attempt in range(2):
                run=subprocess.run(cmd,text=True,capture_output=True,timeout=120)
                self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
                if attempt==1:self.assertIn('reuse verified narrow cache',run.stdout)
            reports=sorted((root/'output/color_change_followup_v100').glob('COLOR_FOLLOWUP_RESULT_*'))
            summary=read_json(reports[-1]/'SUMMARY.json');self.assertEqual(summary['status'],'DIAGNOSTICS_COMPLETE')
            self.assertEqual(summary['scientific_go'],'NOT_YET_ELIGIBLE');self.assertFalse(summary['causal_regressions_run'])
            self.assertTrue(list((root/'desktop').glob('COLOR_FOLLOWUP_RESULT_*.zip.sha256')))

    def test_exact_dates(self):
        values=[BRACKET-1,BRACKET,CUTOFF-1,CUTOFF,ANNOUNCEMENT-1,ANNOUNCEMENT,JAN7-1,JAN7,JAN30-1,JAN30]
        c=duckdb.connect();c.register('t',pd.DataFrame(dict(utc_ms=values)))
        got=c.execute('SELECT '+period_sql()+' FROM t').fetchnumpy();c.close()
        self.assertEqual(list(next(iter(got.values()))),['pre','transition','transition','implemented_unannounced','implemented_unannounced','announced_before_jan7','announced_before_jan7','jan7_to_jan30_scenario','jan7_to_jan30_scenario','jan30_onward_unclassified'])

    def test_prepare_calibration_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            work=Path(td)/'followup';report=Path(td)/'report';report.mkdir()
            for month in ['2025-10','2025-11','2025-12','2026-01']:
                task,df=make_month(td,month);r=prepare_month(task);out=Path(r['output']['path'])
                before=out.stat().st_mtime_ns;again=prepare_month(task);self.assertEqual(before,out.stat().st_mtime_ns)
                got=pd.read_parquet(out);self.assertEqual(len(got),len(df));self.assertEqual(got.observed.isna().sum(),1)
                self.assertTrue(np.allclose(got.predicted,got.stored_pred))
                if month=='2025-10':self.assertEqual(got.pool_main.sum(),60)
                else:self.assertTrue(got.pool_main.isna().all())
                self.assertGreater(((got.actual_score==.5)&(got.grant==0)).sum(),0)
            summarize(work,report,2,512)
            matched=pd.read_parquet(report/'matched_opportunity_calibration.parquet')
            self.assertFalse(matched.empty)
            self.assertTrue((matched['sample']=='all_source').all())
            ret=pd.read_parquet(report/'returning_support.parquet');self.assertGreater(ret.n.sum(),0)
            support=support_scenario(work,'test_jan7',JAN7,2,512)
            self.assertGreater(support['n'],0);self.assertGreater(support['choosers_in_both_periods'],0)
            self.assertLessEqual(support['residual_treatment_ss'],support['raw_treatment_centered_ss']+1e-7)
            self.assertEqual(support,support_scenario(work,'test_jan7',JAN7,2,512))

    def test_duplicate_aux_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            task,df=make_month(td,'2025-11');p=Path(td)/'first/replay/speed=blitz/month=2025-11/targets.parquet'
            x=pd.read_parquet(p);r=put(pd.concat([x,x.iloc[[0]]]),p);write_json(p.parent/'_SUCCESS.json',dict(outputs=dict(targets=r)))
            with self.assertRaisesRegex(RuntimeError,'coverage failure'):prepare_month(task)

    def test_changed_cache_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            task,df=make_month(td,'2025-11');r=prepare_month(task);p=Path(r['output']['path'])
            x=pd.read_parquet(p);x.loc[0,'d_G']+=1.;frame(x,p)
            with self.assertRaisesRegex(RuntimeError,'damaged'):prepare_month(task)

    def test_projection_against_dense_least_squares(self):
        rng=np.random.default_rng(321);n=300;person=rng.integers(0,25,n);week=rng.integers(0,8,n)
        controls=rng.normal(size=(n,2));treat=.3*controls[:,0]+person*.01+week*.05+rng.normal(size=n)
        a=np.column_stack([treat,controls,controls[:,0]*2])
        design=np.column_stack([np.eye(25)[person],np.eye(8)[week],controls])
        residual=treat-design@np.linalg.lstsq(design,treat,rcond=None)[0]
        result=residual_support(a.copy(),[person,week])
        self.assertAlmostEqual(result['residual_treatment_ss'],float(residual@residual),places=6)
        self.assertEqual(result['controls_rank'],2)

    def test_time_dependence_and_power(self):
        rng=np.random.default_rng(44);y=np.zeros(2000)
        for i in range(1,len(y)):y[i]=.85*y[i-1]+rng.normal()
        iid=moving_block_noise(y,8,8,1,10000,11);dependent=moving_block_noise(y,8,8,8,10000,11)
        self.assertGreater(dependent.var(),iid.var()*1.5)
        critical,mde,power=empirical_mde(dependent)
        self.assertGreater(mde,critical);self.assertGreaterEqual(power(mde),.8)
        self.assertLess(power(.5*mde),.8)

    def test_weekly_screen_timestamp_units(self):
        with tempfile.TemporaryDirectory() as td:
            rows=[]
            for i,w in enumerate(pd.date_range('2023-11-06','2026-01-26',freq='W-MON')):
                for color in ['white','black']:
                    rows.append(dict(sample='all_source',stratum='fixed_established',board_state='competitive',week=w,
                        color=color,grants=100+i%7+(color=='white')*(i%3),opportunities=10000))
            df=pd.DataFrame(rows);df.week=df.week.astype('datetime64[us]');frame(df,Path(td)/'weekly_cells.parquet')
            weekly_screen(td);got=pd.read_parquet(Path(td)/'weekly_power_screen.parquet')
            self.assertEqual(len(got),4);self.assertTrue((got.pre_weeks==106).all())
            pl=pd.read_parquet(Path(td)/'frozen_pre_placebos.parquet');self.assertEqual(len(pl),24);self.assertTrue(pl.complete.all())

    def test_grace_missing_clock_and_kindness(self):
        with tempfile.TemporaryDirectory() as td:
            task=make_grace(td);r=grace_month(task);x=pd.read_parquet(r['output']['path']);z=x.groupby('clock_frame').sum(numeric_only=True)
            self.assertEqual(z.loc['ge5_or_missing','targeted_candidates'],6)
            self.assertEqual(z.loc['ge5_or_missing','active_resolutions'],4)
            self.assertEqual(z.loc['ge5_observed','active_resolutions'],3)
            self.assertEqual(z.loc['ge5_or_missing','timeout_draws'],2)
            self.assertEqual(z.loc['ge5_or_missing','kindness_draws'],1)
            self.assertEqual(r['reconciliation']['active_missing_clock_wins'],1)
            self.assertEqual(r['reconciliation']['excluded_casual'],1)
            self.assertEqual(r,grace_month(task))
            report=Path(td)/'report';report.mkdir();finalize_grace(Path(td)/'first',Path(td)/'followup',report,[r],2,512)
            self.assertTrue((report/'GRACE_AND_IV_STATUS.json').is_file())

    def test_truncated_windows_never_estimated(self):
        def data(end):
            days=pd.date_range('2026-01-20',end,freq='D')
            return pd.DataFrame(dict(day=days,speed='blitz',material_group='within_2',clock_frame='ge5_observed',targeted_candidates=100,active_resolutions=20))
        x=complete_window_differences(data('2026-01-31'));r=x[x.day==pd.Timestamp('2026-01-30')].iloc[0]
        self.assertEqual(r.after_days,2);self.assertFalse(r.complete);self.assertTrue(pd.isna(r.change_pp))
        y=complete_window_differences(data('2026-02-05'));r=y[y.day==pd.Timestamp('2026-01-30')].iloc[0]
        self.assertTrue(r.complete);self.assertEqual(r.change_pp,0)
        d=data('2026-02-05');d=d[d.day!=pd.Timestamp('2026-01-25')]
        z=complete_window_differences(d);self.assertFalse(z[z.day==pd.Timestamp('2026-01-30')].iloc[0].complete)

if __name__=='__main__':unittest.main()
