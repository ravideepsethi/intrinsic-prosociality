from pathlib import Path
import tempfile,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from mc_io import *
import mc_history as h
import mc_inputs as inp
import mc_sample as sm
import mc_predict as pred
import mc_inference as inf

def write_df(p,rows):
    frame(rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows),p)
    return str(p)

def output_record(p):
    return dict(path=str(p),sha256=sha(p),bytes=Path(p).stat().st_size,rows=pq.ParquetFile(p).metadata.num_rows)

def state_rows(times):
    n=len(times);rng=np.random.default_rng(81)
    d=pd.DataFrame(dict(game_id=[f'g{i:08}' for i in range(n)],chooser=np.arange(n)%12+1,opponent=np.arange(n)%12+21,
        t=times,speed='blitz',color=np.where(np.arange(n)%2,'black','white'),y=(np.arange(n)%7==0).astype(int),
        cp=0.,ply=30,rating=1500.,opp_rating=1500.+rng.integers(-300,301,n),rd=70.,opp_rd=65.,
        clock=20.,opp_clock=25.,prior_starts=400,history_days=900.,inactivity_days=2.,opp_prior_starts=300,state='equal'))
    d['month']=[pd.Timestamp(int(t),unit='ms',tz='UTC').strftime('%Y-%m') for t in times]
    d['g']=d.opp_rating-d.rating
    e,k,rg,rc=payoff(d.rating,d.opp_rating,d.rd,d.opp_rd)
    d['rg']=rg;d['rc']=rc;d['ki']=k/2;d['kj']=payoff(d.opp_rating,d.rating,d.opp_rd,d.rd)[1]/2
    return d

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"quoted root's path";self.root.mkdir()
        self.work=self.root/'work';self.report=self.root/'report';self.report.mkdir()
    def tearDown(self):self.tmp.cleanup()

    def test_utc_week_units_and_crossing_weeks(self):
        dates=['2025-11-16T23:59:59Z','2025-11-17T00:00:00Z','2025-12-22T22:35:00Z']
        for date in dates:
            t=ms(date);expected=ms(str(pd.Timestamp(date).normalize()-pd.Timedelta(days=pd.Timestamp(date).weekday())))
            self.assertEqual(int(week_ms(t)),expected)
        w={r['name']:r for r in inf.windows()}
        self.assertEqual(len(w['unannounced']['post']),4)
        self.assertEqual(len(w['announced_jan7']['post']),1)
        self.assertEqual(len(w['pooled_jan30']['post']),8)
        self.assertNotIn(int(week_ms(IMPLEMENTED)),w['pooled_jan30']['post'])
        self.assertNotIn(int(week_ms(ANNOUNCED)),w['pooled_jan30']['post'])
        self.assertEqual(w['pooled_jan30']['post_offsets'].tolist(),[9,10,11,12,14,15,16,17])

    def history_fixture(self):
        events=[];gid=0
        def event(t,a,b):
            nonlocal gid
            gid+=1;events.append(dict(game_id=f'h{gid:07}',utc_ms=t,white_id=a,black_id=b,archive_ordinal=gid))
        first=ms('2024-10-01T00:00:00Z')
        for i in range(99):event(first+i*1000,1,2)
        for j in range(1,5):event(IMPLEMENTED-j*WEEK,1,2)
        # Player 3 has three qualifying bins; a start exactly at cutoff must not fill the fourth.
        for j in range(2,5):event(IMPLEMENTED-j*WEEK,3,4)
        event(IMPLEMENTED,3,4);event(IMPLEMENTED+1,1,2)
        for month in ('2025-12','2026-01'):event(ms(month+'-03T12:00:00Z'),1,2)
        records=[]
        for month,d in pd.DataFrame(events).groupby(pd.to_datetime(pd.DataFrame(events).utc_ms,unit='ms').dt.strftime('%Y-%m')):
            p=self.root/'chron'/f'{month}.parquet';write_df(p,d)
            records.append(dict(speed='blitz',month=month,path=str(p),rows=len(d),size=p.stat().st_size,old_summary=None))
        return records

    def test_fixed_roster_strict_cutoff_and_cached_delta(self):
        records=self.history_fixture();candidate=h.activity_candidates('blitz',records,self.work,512)
        self.assertEqual(set(pd.read_parquet(candidate).user_id),{1,2})
        oldneed=self.root/'old_needed.parquet';write_df(oldneed,[dict(speed='blitz',user_id=1)])
        needed=self.root/'needed.parquet';write_df(needed,[dict(speed='blitz',user_id=i) for i in (1,2)])
        missing=self.root/'missing.parquet';write_df(missing,[dict(speed='blitz',user_id=2)])
        rec=records[0];raw=Path(rec['path']);old=self.root/'old_summary.parquet'
        write_df(old,[dict(user_id=1,n=99,first_ms=ms('2024-10-01T00:00:00Z'),last_ms=ms('2024-10-01T00:00:00Z')+98000)])
        source=dict(fingerprint={k:v for k,v in stamp(raw).items() if k!='ctime_ns'},sha256=sha(raw),expected_sha256=None)
        key=digest(dict(version='1.0.0',input=source,needed={k:v for k,v in stamp(oldneed).items() if k!='ctime_ns'},semantics='prior_recorded_starts'))
        write(old.with_suffix('.json'),dict(key=key,source=source,output=output_record(old)))
        rec['old_summary']=str(old)
        outputs=[h.summary_job((r,str(needed),str(missing),str(oldneed),str(self.work),512)) for r in records]
        self.assertTrue(read(Path(outputs[0]).with_suffix('.json'))['reused_old_summary'])
        self.assertEqual(pd.read_parquet(outputs[0]).sort_values('user_id').n.tolist(),[99,99])
        before=stamp(outputs[0]);self.assertEqual(h.summary_job((rec,str(needed),str(missing),str(oldneed),str(self.work),512)),outputs[0])
        self.assertEqual(before,stamp(outputs[0]))
        roster=h.roster('blitz',records,candidate,self.work,512);d=pd.read_parquet(roster)
        self.assertTrue(d.fixed_regular_cohort.all());self.assertEqual(d.prior_starts.tolist(),[103,103])
        self.assertTrue((d.last_ms<IMPLEMENTED).all())
        # Corrupted completed counts must stop, never be silently regenerated.
        write_df(Path(outputs[0]),[dict(user_id=1,n=999,first_ms=0,last_ms=1)])
        with self.assertRaisesRegex(RuntimeError,'changed'):h.summary_job((rec,str(needed),str(missing),str(oldneed),str(self.work),512))

    def test_history_excludes_focal_and_simultaneous_starts(self):
        t=ms('2025-11-03T12:00:00Z');records=[]
        for month,events in [('2025-10',[dict(game_id='old',utc_ms=t-5*DAY,white_id=1,black_id=2,archive_ordinal=1)]),
                             ('2025-11',[dict(game_id='prior',utc_ms=t-1000,white_id=1,black_id=2,archive_ordinal=2),
                                         dict(game_id='focal',utc_ms=t,white_id=1,black_id=3,archive_ordinal=3),
                                         dict(game_id='same',utc_ms=t,white_id=1,black_id=4,archive_ordinal=4)])]:
            p=self.root/(month+'.parquet');write_df(p,events);records.append(dict(speed='blitz',month=month,path=str(p)))
        write_df(self.work/'history_summary/blitz_2025-10.parquet',[
            dict(user_id=1,n=10,first_ms=t-400*DAY,last_ms=t-5*DAY),dict(user_id=2,n=1,first_ms=t-5*DAY,last_ms=t-5*DAY)])
        base=self.root/'base.parquet';write_df(base,[dict(game_id='focal',chooser=1,opponent=3,t=t+500,speed='blitz')])
        out=h.feature_job(('blitz','2025-11',records,str(base),str(self.work),512));d=pd.read_parquet(out).set_index('role')
        self.assertEqual(d.loc[1,'prior_starts'],11);self.assertEqual(d.loc[1,'history_days'],400)
        self.assertAlmostEqual(d.loc[1,'inactivity_days'],1000/DAY)
        self.assertEqual(d.loc[0,'prior_starts'],0);self.assertEqual(d.loc[0,'history_days'],0)
        self.assertTrue((d.history_anchor_ms==t).all())

    def test_needed_union_and_rated_start_exposure(self):
        candidate=self.root/'candidate.parquet';write_df(candidate,[dict(speed='blitz',user_id=1)])
        old=self.root/'old.parquet';write_df(old,[dict(speed='blitz',user_id=1)])
        post=self.root/'post.parquet';write_df(post,[dict(speed='blitz',chooser=1,opponent=2)])
        needed,missing=h.needed_users([candidate],[post],old,self.work,512)
        self.assertEqual(set(pd.read_parquet(needed).user_id),{1,2});self.assertEqual(pd.read_parquet(missing).user_id.tolist(),[2])
        rp=self.root/'roster.parquet';write_df(rp,[dict(speed='blitz',user_id=1,fixed_regular_cohort=True)])
        p=self.root/'events.parquet';t=ms('2025-11-25T00:00:00Z')
        write_df(p,[dict(white_id=1,black_id=2,utc_ms=t),dict(white_id=2,black_id=1,utc_ms=t+1000),
                    dict(white_id=1,black_id=2,utc_ms=t+2000),dict(white_id=3,black_id=4,utc_ms=t+3000)])
        out=h.exposure_job((dict(path=str(p),speed='blitz',month='2025-11'),[str(rp)],str(self.work),512))
        d=pd.read_parquet(out).set_index('color');self.assertEqual(d.loc['white','rated_player_starts'],2)
        self.assertEqual(d.loc['black','rated_player_starts'],1);self.assertEqual(d.active_roster_accounts.tolist(),[1,1])

    def post_fixture(self,month='2025-11',mismatch=False):
        t=ms(month+'-25T00:00:00Z');d=state_rows([t+i*1000 for i in range(10)])
        d['speed']=list(SPEEDS)*2;d['grant']=d.y;d['chooser_user_id']=d.chooser
        d['utc_ms']=d.t;d['chooser_clock']=d.clock;d['opp_clock']=d.opp_clock
        d['draw_old']=d.rg;d['win_old']=d.rc;d['K_old']=2*d.ki;d['valid_state']=True
        hist=d[['game_id','chooser_user_id','utc_ms','color','grant','rating','opp_rating','cp','ply','speed']].copy()
        hist['disconnected_user_id']=d.opponent
        if mismatch:hist.loc[0,'ply']+=1
        first=self.root/inp.FIRST;p=first/'dose'/f'month={month}'/'opportunities.parquet';write_df(p,d)
        write(p.with_suffix('.json'),dict(output=output_record(p)))
        hp=self.root/'history'/f'{month}.parquet';write_df(hp,hist)
        member=d[['game_id']].assign(month=month,source='pool',source_status='recovered',
            previous_classification_status='not_mutually_adjacent_observed',pool_nonadjacent_eligible=True)
        mr=self.root/'membership';rel=f'membership/month={month}/membership_PRIVATE.parquet';mp=mr/rel;write_df(mp,member)
        write(mr/'_DONE.json',dict(files=[dict(output_record(mp),path=rel)]))
        for speed in SPEEDS:
            x=d[d.speed.eq(speed)];white=x.color.eq('white').to_numpy();score=np.where(x.y,.5,1.)
            wc=np.where(white,score,1-score);e,k,_,_=payoff(x.rating,x.opp_rating,x.rd,x.opp_rd,np.where(white,1,-1),ADVANTAGE)
            predval=k*(score-e)
            r=pd.DataFrame(dict(game_id=x.game_id,utc_ms=x.utc_ms,white_id=np.where(white,x.chooser,x.opponent),
                black_id=np.where(white,x.opponent,x.chooser),result_code=(wc*2).astype(int),
                white_rating_diff=np.where(white,np.rint(predval),0),black_rating_diff=np.where(white,0,np.rint(predval)),
                white_pred=np.where(white,predval,0),black_pred=np.where(white,0,predval)))
            rp=first/'replay'/f'speed={speed}'/f'month={month}';pp=rp/'targets.parquet';write_df(pp,r)
            write(rp/'_SUCCESS.json',dict(outputs=dict(targets=output_record(pp))))
        return dict(opportunities={month:str(hp)},opportunity_receipts=[output_record(hp)],membership_root=str(mr))

    def test_post_identity_payoff_parity_and_restart(self):
        b=self.post_fixture();job=(str(self.root),str(self.work),'2025-11',b,512)
        out=inp.prepare_post(job);d=pd.read_parquet(out)
        self.assertEqual(len(d),10);self.assertTrue(np.allclose(d.ki,d.rc-d.rg))
        self.assertTrue(np.allclose(d.pred_new,d.stored_pred));old=stamp(out)
        self.assertEqual(out,inp.prepare_post(job));self.assertEqual(old,stamp(out))

    def test_post_identity_mismatch_stops(self):
        b=self.post_fixture(mismatch=True)
        with self.assertRaisesRegex(RuntimeError,'identity join failed'):inp.prepare_post((str(self.root),str(self.work),'2025-11',b,512))

    def test_pre_only_predictions_invariant_to_post_choices(self):
        times=[ms('2025-10-01T00:00:00Z')+i*1000 for i in range(160)]+[IMPLEMENTED+DAY+i*1000 for i in range(40)]
        d=state_rows(times);p=self.root/'all.parquet';write_df(p,d)
        a=pred.predict_state(p,'equal',self.work,self.report,512,models=('curved','strength'))
        d.loc[d.t>=BRACKET,'y']=1-d.loc[d.t>=BRACKET,'y'];p2=self.root/'changed.parquet';write_df(p2,d)
        r2=self.root/'report2';r2.mkdir()
        b=pred.predict_state(p2,'equal',self.root/'work2',r2,512,models=('curved','strength'))
        pd.testing.assert_frame_equal(a,b)
        cal=pd.read_parquet(self.report/'equal_baseline_calibration.parquet')
        self.assertTrue(np.allclose(cal.pre_rate_pp,cal.predicted_pre_rate_pp,atol=1e-9))
        # At nonzero rating gaps the K change remains in the strength model.
        self.assertTrue(np.isfinite(a.mechanical_delta_pp).all())

    def test_all_seven_frozen_fit_designs_and_color_reversal(self):
        d=state_rows([ms('2026-01-02T00:00:00Z')]*20)
        for state in ('equal','losing'):
            for model in pred.MODELS:
                fit=read(ROOT/'authority/fits'/(f'rd110_{model}_full.json' if state=='equal' else f'losing_{model}_full.json'))
                old,change=pred.fixed_offsets(d,fit)
                self.assertEqual(len(old),20);self.assertTrue(np.isfinite(change).all())
        equal=state_rows([IMPLEMENTED+DAY]*2);equal['opp_rating']=equal.rating;equal['g']=0
        fit=read(ROOT/'authority/fits/rd110_framing_full.json');_,shift=pred.fixed_offsets(equal,fit)
        self.assertLess(shift[0],0);self.assertGreater(shift[1],0)

    def test_bootstrap_calendar_gaps_and_zero_effect(self):
        x=np.random.default_rng(4).normal(size=103);w=inf.windows()[-1]
        a=inf.block_noise(x,w['pre_offsets'],w['post_offsets'],4,2000)
        b=inf.block_noise(x,w['pre_offsets'],np.arange(8,16),4,2000)
        self.assertFalse(np.array_equal(a,b));self.assertAlmostEqual(a.mean(),0,places=12)
        md,critical=inf.mde(a);self.assertGreater(md,0);self.assertLess(np.mean(abs(a)>critical),.055)

    def inference_fixture(self):
        weeks=np.arange(int(week_ms(START)),ms('2026-02-02T00:00:00Z'),WEEK);data=[];fore=[];gates=[]
        for j,t in enumerate(weeks):
            for color in ('white','black'):
                grants=3+(j%5 if color=='white' else (2*j)%3)
                for k in range(40):data.append(dict(state='equal',t=int(t+DAY),color=color,y=int(k<grants),chooser=k))
                for model in ('curved','strength'):
                    # Known 0.2pp post composition shift plus color-specific mechanical effect.
                    base=10.+(color=='white')*.2*(t>IMPLEMENTED)
                    shift=(-.1 if color=='white' else .1) if model=='curved' else 0.
                    fore.append(dict(state='equal',model=model,baseline='account20',week_ms=t,color=color,
                        old_rate_pp=base,new_rate_pp=base+shift,mechanical_delta_pp=shift))
            gates.append(dict(state='equal',week_ms=int(t),eligible_before_membership=80,unknown_source_n=0,
                unmapped_pool_adjacency_n=0,clock_rule_violation_n=0))
        p=self.root/'rates.parquet';write_df(p,data);fore=pd.DataFrame(fore)
        table(fore,self.report/'equal_weekly_predictions')
        return p,fore,gates

    def test_conditional_comparison_total_forecast_and_manifest(self):
        p,f,g=self.inference_fixture();r=inf.run_comparison(p,{'equal':f},g,self.work,self.report,reps=500)
        self.assertEqual(r['status'],'MATCHED_DESCRIPTIVE_COMPARISON_COMPLETE');self.assertEqual(r['behavior_windows_estimated'],5)
        d=pd.read_parquet(self.report/'matched_predictions.parquet');x=d[d.model.eq('curved')]
        self.assertTrue(np.allclose(x.mechanical_shift_pp,-.2));self.assertTrue(np.allclose(x.no_policy_composition_change_pp,.2))
        self.assertTrue(np.allclose(x.total_prediction_full_awareness_pp,0))
        self.assertTrue(read(self.report/'PREDICTIONS_SEALED.json')['post_outcomes_used_in_predictions'] is False)
        a=pd.read_parquet(self.report/'conditional_point_fit_comparisons.parquet');self.assertFalse(a.unconditional_rejection.any())
        self.assertFalse(a.parameter_uncertainty_propagated.any())

    def test_unknown_source_withholds_affected_behavior_window(self):
        p,f,g=self.inference_fixture();badweek=int(inf.windows()[0]['post'][0])
        for row in g:
            if row['week_ms']==badweek:row['unknown_source_n']=1
        r=inf.run_comparison(p,{'equal':f},g,self.work,self.report,reps=500)
        self.assertEqual(r['behavior_windows_estimated'],2)
        actual=pd.read_parquet(self.report/'matched_weekly_rates.parquet')
        self.assertNotIn(badweek,set(actual.week_ms))
        power=pd.read_parquet(self.report/'matched_pairwise_power.parquet')
        self.assertTrue(power.both_pre_policy_compatible.all())

    def test_coverage_handles_missing_week_and_subfive_clock(self):
        p,f,g=self.inference_fixture();w=inf.windows()[0];allweeks=np.r_[w['pre'],w['post']]
        self.assertTrue(inf.coverage_ok(g,'equal',allweeks)[0])
        g=[r for r in g if r['week_ms']!=allweeks[0]]
        self.assertFalse(inf.coverage_ok(g,'equal',allweeks)[0])
        g[0]['clock_rule_violation_n']=1
        self.assertFalse(inf.coverage_ok(g,'equal',[g[0]['week_ms']])[0])

    def test_sql_sample_fixed_roster_ignores_rolling_regular_flag(self):
        months=['2025-10',*POST_MONTHS];pre=[];post=[];rosters=[]
        for speed in SPEEDS:
            rp=self.root/'roster'/(speed+'.parquet')
            write_df(rp,[dict(speed=speed,user_id=1,prior_starts=103,history_days=400.,fixed_regular_cohort=True)])
            rosters.append(str(rp))
        for month in months:
            d=state_rows([ms(month+'-25T00:00:00Z')+i*1000 for i in range(12)]);d['regular']=False
            d['game_id']=month+'_'+d.game_id
            p=self.root/'narrow'/(month+'.parquet')
            if month in POST_MONTHS:
                d['source']='pool';d['source_status']='recovered';d['previous_classification_status']='not_mutually_adjacent_observed'
                d['pool_main']=True;d['actual_score']=1.;d['observed']=1.;d['stored_pred']=1.;d['pred_old']=1.;d['pred_new']=1.
                features=d[['game_id','prior_starts','history_days','inactivity_days']].assign(role=1)
                features=pd.concat([features,features.assign(role=0)],ignore_index=True)
                for speed in SPEEDS:
                    write_df(self.work/'post_features'/f'{speed}_{month}.parquet',features if speed=='blitz' else features.iloc[:0])
                d=d.drop(columns=['prior_starts','history_days','inactivity_days','opp_prior_starts']);post.append(write_df(p,d))
            else:pre.append(write_df(p,d))
        target,gates=sm.assemble(dict(pre=pre),post,rosters,self.work,self.report,512)
        actual=pd.read_parquet(target);self.assertEqual(len(actual),4);self.assertEqual(set(actual.chooser),{1})
        before=stamp(target);sm.assemble(dict(pre=pre),post,rosters,self.work,self.report,512);self.assertEqual(before,stamp(target))

if __name__=='__main__':unittest.main(verbosity=2)
