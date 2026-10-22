"""Synthetic scientific checks. Expected runtime: 5–20 seconds, no private inputs."""
import sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from io_utils import *
from inputs import validate_rows,prepare_month,policy_input
from predict import calibrate,match_alpha,offsets,index_change,prediction_job
from design import design,counterfactual
from inference import (windows,block_null,mde,weekly_difference,weekly_outcomes,
                       summaries,analyze_power,pre_diagnostics,observed_comparison)
from numeric import expit,numpy_expit

def fixture(start='2023-11-06',nweeks=100,perweek=40):
    rng=np.random.default_rng(1811);n=nweeks*perweek
    t=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)+np.repeat(np.arange(nweeks),perweek)*7*DAY+DAY
    rating=rng.integers(1300,2200,n).astype(float);gap=rng.integers(-570,571,n).astype(float)
    d=pd.DataFrame(dict(game_id=['fixture_%07d'%i for i in range(n)],chooser=['player_%04d'%(i%83) for i in range(n)],
      t=t,speed=np.resize(['blitz','rapid','bullet'],n),color=np.resize(['white','black'],n),
      y=(rng.random(n)<.08).astype(int),cp=rng.integers(-90,90,n),ply=rng.integers(11,81,n),
      rating=rating,opp_rating=rating+gap,g=gap,rd=rng.uniform(45,110,n),opp_rd=rng.uniform(45,110,n),
      rg=0.,rc=0.,ki=0.,kj=0.,clock=rng.uniform(0,180,n),opp_clock=rng.uniform(0,180,n),
      month=pd.to_datetime(t,unit='ms',utc=True).strftime('%Y-%m'),history_days=700.,prior_starts=600.,
      inactivity_days=2.,opp_prior_starts=550.))
    return counterfactual(d,advantage=0.)

class ScientificChecks(unittest.TestCase):
    def test_utc_week_keys_against_stdlib_and_duckdb(self):
        epoch=datetime(1970,1,1,tzinfo=timezone.utc)
        rng=np.random.default_rng(2026092602)
        sample=np.r_[[-1,0,1,IMPLEMENTED,ANNOUNCED,1763337600000-1,1763337600000,1763337600000+1],
                     rng.integers(1577836800000,1830297600000,1000)]
        expected=[]
        for v in sample:
            d=epoch+timedelta(milliseconds=int(v))
            monday=(d-timedelta(days=d.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
            expected.append(int((monday-epoch).total_seconds()*1000))
        actual=weeks(sample)
        np.testing.assert_array_equal(actual,expected)
        c=duckdb.connect()
        try:
            c.register('checks',pd.DataFrame({'t':sample}))
            sql=c.execute("SELECT epoch_ms(date_trunc('week',epoch_ms(t))) AS monday FROM checks").fetchnumpy()['monday']
        finally:c.close()
        np.testing.assert_array_equal(actual,sql)
        self.assertTrue(np.all((actual<=sample)&(sample<actual+7*DAY)))
        self.assertEqual(len(complete_weeks(ANNOUNCED,ANNOUNCED)),0)
        with self.assertRaisesRegex(ValueError,'finite'):weeks([np.nan])
        with self.assertRaisesRegex(ValueError,'integer'):weeks([1.5])

    def test_numpy_logistic_extremes_and_reference_values(self):
        x=np.array([-np.inf,-1000.,-np.log(3.),0.,np.log(3.),1000.,np.inf])
        with np.errstate(over='raise',invalid='raise'):
            p=numpy_expit(x)
        np.testing.assert_allclose(p,[0.,0.,.25,.5,.75,1.,1.],atol=2e-16,rtol=0.)
        self.assertTrue(np.isnan(numpy_expit(np.nan)))
        self.assertEqual(float(numpy_expit(0.)),.5)

    def test_calendar_and_announcement_gap(self):
        self.assertEqual(pd.to_datetime(IMPLEMENTED,unit='ms',utc=True).isoformat(),'2025-11-18T07:22:00+00:00')
        self.assertEqual(pd.to_datetime(ANNOUNCED,unit='ms',utc=True).isoformat(),'2025-12-22T22:35:00+00:00')
        w={x['period']:x for x in windows()}
        np.testing.assert_array_equal(w['unannounced']['pre_offsets'],np.arange(8))
        np.testing.assert_array_equal(w['unannounced']['post_offsets'],[9,10,11,12])
        np.testing.assert_array_equal(w['announced']['post_offsets'],[14,15,16,17])
        np.testing.assert_array_equal(w['unannounced']['post'],[1763942400000,1764547200000,1765152000000,1765756800000])
        np.testing.assert_array_equal(w['announced']['post'],[1766966400000,1767571200000,1768176000000,1768780800000])
        for v in w.values():
            self.assertTrue((v['pre']+7*DAY<=IMPLEMENTED).all())
            self.assertTrue((v['post']>=IMPLEMENTED).all())
            self.assertTrue(((v['post']+7*DAY<=ANNOUNCED)|(v['post']>=ANNOUNCED)).all())

    def test_payoffs_and_every_model_index_against_full_rebuild(self):
        d=fixture('2025-12-29',2,50)
        validate_rows(d)
        new=counterfactual(d,advantage=ADVANTAGE)
        for model in MODELS:
            f=read(ROOT/'authority/fits'/f'{model}_full.json')
            delta,dg,dc,dk,_=index_change(d,f)
            np.testing.assert_allclose(delta,offsets(new,f,'2025-10')-offsets(d,f,'2025-10'),atol=2e-13)
            np.testing.assert_allclose(dc-dg,dk,atol=1e-13)
        bad=d.copy();bad.loc[0,'rg']=np.nan
        with self.assertRaisesRegex(RuntimeError,'Nonfinite'):validate_rows(bad)
        bad=d.copy();bad.loc[0,'month']='2025-11'
        with self.assertRaisesRegex(RuntimeError,'Timestamp/month'):validate_rows(bad)

    def test_account_and_unseen_calibration(self):
        eta=np.linspace(-2,3,100);y=(np.arange(100)%13==0).astype(float);ids=np.array(['a','b']*50)
        unique,a,fallback,base,error=calibrate(eta,y,ids)
        aa,seen=match_alpha(ids,unique,a,fallback)
        self.assertTrue(seen.all());self.assertLess(error,1e-8)
        for k in unique:
            ix=ids==k;target=(y[ix].sum()+20*base)/(ix.sum()+20)
            self.assertAlmostEqual(expit(aa[ix]+eta[ix]).mean(),target,places=10)
        self.assertAlmostEqual(expit(fallback+eta).mean(),base,places=10)
        b,known=match_alpha(np.array(['a','unknown']),unique,a,fallback)
        self.assertFalse(known[1]);self.assertEqual(b[1],fallback)

    def test_forecasts_ignore_post_y_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);tr=fixture(nweeks=60);target=fixture('2025-11-24',9)
            frame(tr,p/'train.parquet');frame(target,p/'target_a.parquet')
            target.y=1-target.y;frame(target,p/'target_b.parquet')
            common=(str(ROOT/'authority/fits/framing_full.json'),'framing','full')
            j=(str(p/'train.parquet'),str(p/'target_a.parquet'),*common,'a',str(p/'work'),'test')
            first=prediction_job(j);second=prediction_job((str(p/'train.parquet'),str(p/'target_b.parquet'),*common,'b',str(p/'work'),'test'))
            a=pd.read_parquet(first['output']['path']).drop(columns='target')
            b=pd.read_parquet(second['output']['path']).drop(columns='target')
            pd.testing.assert_frame_equal(a,b)
            self.assertLess(first['calibration_last_timestamp_ms'],IMPLEMENTED)
            m=stamp(first['output']['path']);self.assertEqual(prediction_job(j),first)
            self.assertEqual(stamp(first['output']['path']),m)
            old=weekly_outcomes(p/'target_a.parquet',p,IMPLEMENTED)
            self.assertEqual(len(old),0)

    def test_calendar_resampling_and_directional_power(self):
        rng=np.random.default_rng(14);series=np.cumsum(rng.normal(0,.03,104))
        w=windows()[1]
        null=block_null(series,w['pre_offsets'],w['post_offsets'],8,5000)
        with self.assertRaisesRegex(ValueError,'Invalid calendar offsets'):
            block_null(series,w['pre_offsets'],[-2906,9,10,11],8,5000)
        adjacent=block_null(series,np.arange(8),np.arange(8,12),8,5000)
        self.assertFalse(np.array_equal(null,adjacent))
        for direction in (-1,1):
            minimum,critical=mde(null,direction)
            self.assertGreaterEqual(np.mean(abs(null+direction*minimum)>critical),.8)
            self.assertLess(np.mean(abs(null+direction*(minimum-1e-5))>critical),.801)
        df=pd.DataFrame({'week_ms':[1,1,2],'color':['white','black','white'],'v':[1.,2.,3.]})
        with self.assertRaisesRegex(ValueError,'Missing'):weekly_difference(df,'v',[1,2])

    def test_authenticated_preparation_and_fail_closed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=fixture(nweeks=3);d['regular']=True;d['state']='equal'
            d.loc[0,'regular']=False;frame(d,p/'source.parquet');h=sha(p/'source.parquet')
            r=prepare_month((str(p/'source.parquet'),h,'2023-11',str(p/'work'),384))
            self.assertEqual(r['rows'],len(d)-1)
            with open(p/'source.parquet','ab') as f:f.write(b'changed')
            with self.assertRaisesRegex(RuntimeError,'SHA mismatch'):auth(p/'source.parquet',p/'work',h)
            write(p/'manifest.json',{'format':'MECHANISM_COLOR_INPUTS_V1'})
            with self.assertRaisesRegex(RuntimeError,'Unresolved policy evidence'):policy_input(p/'manifest.json',p/'work',1,384)

    def test_complete_synthetic_power_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=fixture(nweeks=103);frame(d,p/'training.parquet')
            paths=[]
            for model in ('framing','strength','curved'):
                job=(str(p/'training.parquet'),str(p/'training.parquet'),str(ROOT/'authority/fits'/f'{model}_full.json'),model,'full','planning',str(p/'work'),'test')
                paths.append(prediction_job(job)['output']['path'])
            lo=int(d.t.min()-DAY);hi=lo+103*7*DAY
            pp,spec=summaries(paths,lo,hi,False)
            weekly=weekly_outcomes(p/'training.parquet',p,IMPLEMENTED)
            power,nulls,_=analyze_power(weekly,pp,spec,lo,hi,p/'report',2000)
            pre_diagnostics(weekly,spec,lo,hi,p/'report')
            self.assertEqual(len(power),3*3*5*2)
            self.assertTrue(power.conditional_power.between(0,1).all())
            self.assertFalse(power.automatic_go.any())
            self.assertFalse(power.parameter_uncertainty_propagated.any())
            self.assertEqual(len(nulls),6)
            self.assertEqual(len(pd.read_parquet(p/'report/pre_placebo_statistics.parquet')),36)

    def test_evidenced_adapter_and_optional_descriptive_statistic(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);source=fixture(nweeks=117);source['fixed_regular_cohort']=True;source['pool_main']=True
            frame(source,p/'source.parquet')
            # Synthetic receipts exercise the contract; these are not production evidence.
            evidence={}
            for name in ('producer_receipt','calibration_review','censor_source'):
                write(p/(name+'.json'),{'fixture_only':True})
                evidence[name]={'path':name+'.json','sha256':sha(p/(name+'.json'))}
            manifest=dict(format='MECHANISM_COLOR_INPUTS_V2',pool_and_previous_adjacency_certified=True,
                cohort_uses_only_preimplementation_information=True,actual_stratum_calibration_reviewed=True,
                missing_clock_and_material_rules_aligned=True,calibration_rd_cap=110,
                payoff_convention='anchored_novol_noreg_old_formula',cohort_information_cutoff_utc='2025-11-18T07:22:00Z',
                chronology_through='2026-01',censor_utc='2026-01-30T00:00:00Z',
                coverage_start_utc='2023-11-06T00:00:00Z',coverage_end_utc='2026-02-02T00:00:00Z',
                files=[dict(path='source.parquet',sha256=sha(p/'source.parquet'),rows=len(source))],**evidence)
            write(p/'manifest.json',manifest)
            meta=policy_input(p/'manifest.json',p/'work',1,384)
            tr=source[source.t<int(pd.Timestamp('2025-11-01',tz='UTC').timestamp()*1000)]
            frame(tr[list(REQUIRED)],p/'training.parquet')
            job=(str(p/'training.parquet'),meta['path'],str(ROOT/'authority/fits/framing_full.json'),'framing','full','actual',str(p/'work'),'test')
            pr=prediction_job(job)
            pp,spec=summaries([pr['output']['path']],meta['coverage_start_ms'],meta['coverage_end_ms'],True)
            weekly=weekly_outcomes(meta['path'],p,IMPLEMENTED)
            _,nulls,_=analyze_power(weekly,pp,spec,meta['coverage_start_ms'],meta['coverage_end_ms'],p/'report',2000)
            stats=observed_comparison(meta['path'],p,spec,pp,nulls,p/'report')
            self.assertEqual(len(stats),6)
            self.assertTrue(np.isfinite([x['observed_change_pp'] for x in stats]).all())
            bad=dict(manifest,cohort_information_cutoff_utc='2025-12-01T00:00:00Z')
            write(p/'bad.json',bad)
            with self.assertRaisesRegex(RuntimeError,'Cohort information cutoff'):policy_input(p/'bad.json',p/'work',1,384)

if __name__=='__main__':unittest.main()
