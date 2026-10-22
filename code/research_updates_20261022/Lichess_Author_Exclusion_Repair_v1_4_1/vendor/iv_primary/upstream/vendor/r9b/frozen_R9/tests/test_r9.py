import sys,unittest,tempfile,copy,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from r9_common import *
import r9_scores as scoring, r9_models as fits, r9_inputs as inputs, r9_report as report
import ul_scores
def sample(n=5000):
    rng=np.random.default_rng(81279);z=rng.normal(0,.055,n)
    start=np.datetime64('2024-06-01','ms').astype(np.int64)+rng.integers(0,60*DAY,n)
    d=dict(row_id=np.arange(n,dtype=np.uint64),game_id=np.array(['synthetic'+str(k) for k in range(n)]),
        recipient_id=rng.integers(1,801,n),opponent_id=rng.integers(801,1601,n),archive_start_ms=start,
        anchor_ms=start+10000,month_code=np.full(n,7),tc_base_s=np.full(n,180),tc_inc_s=np.full(n,2),
        recipient_rating=rng.normal(1500,100,n),opponent_rating=rng.normal(1500,100,n),
        n_7d=rng.integers(5,70,n),counterparts_7d=rng.integers(3,5,n),expected_7d=rng.uniform(.1,.3,n),adjusted_7d=z,
        pre_games_30d=rng.poisson(20,n),complete90=np.ones(n,bool),complete=np.ones(n,bool),
        comp_n_7d=np.full(n,10),comp_counterparts_7d=np.full(n,7),comp_expected_7d=np.full(n,.2),comp_adjusted_7d=z*1.4)
    d['received']=rng.random(n)<np.clip(.2+1.8*z,.01,.99)
    d['y']=rng.random(n)<np.clip(.15+.07*d['received']+.2*z,.01,.99)
    d['reached']=rng.random(n)<.6
    for name,rate in [('analysis_entry_90',.08),('recipient_disconnect_main',.12),('active_timeout',.2)]:d[name]=rng.random(n)<rate
    for days in (30,90):
        fair=rng.poisson(3,n);fair[rng.random(n)<.2]=0
        d[f'fair_{days}']=fair;d[f'kind_{days}']=rng.binomial(fair,.17)
        for name in ('disconnect','receipt','claim'):d[f'{name}_{days}']=rng.poisson(2,n)
    d['games']=rng.integers(2,150,n);d['environment_supported']=rng.random(n)>.2
    d['log_opponent_games90']=np.log1p(d['games'])
    d['opponent_observed_disconnect_rate']=rng.binomial(d['games'],.03)/d['games']
    d['opponent_observed_chooser_rate']=rng.binomial(d['games'],.08)/d['games']
    for name in r.ENV:d[name][~d['environment_supported']]=np.nan
    return d

def fixture(p,n=5000):
    d=sample(n);n=len(d['row_id']);r.io.table(p/'data.parquet',pa.table(d))
    rng=np.random.default_rng(51)
    a=dict(row_id=d['row_id'],n_A=d['n_7d']+10,counterparts_A=d['counterparts_7d']+3,
        expected_A=np.clip(d['expected_7d']+.01,0,1),adjusted_A=d['adjusted_7d']*1.1+.005,
        n_B=d['n_7d']+4,counterparts_B=d['counterparts_7d']+1,
        expected_B=d['expected_7d']+.02,adjusted_B=d['adjusted_7d']*.9+rng.normal(0,.005,n),
        n_C=d['n_7d']+6,counterparts_C=d['counterparts_7d']+2,
        expected_C=d['expected_7d']+.005,adjusted_C=d['adjusted_7d']*1.2+rng.normal(0,.005,n),
        old_adjusted=d['adjusted_7d'],old_expected=d['expected_7d'],n_after_all=d['n_7d']+6,
        n_month_mismatch=d['n_7d']+8,n_fallback=np.ones(n,np.int64))
    r.io.table(p/'scores.parquet',pa.table(a));return d,a

def job(p,level='X0_ENV_indicator',variant='A',kind='iv',cohort='full',**kw):
    return fits.make_job(p/'data.parquet',p/'scores.parquet',p/('fit_'+variant+'_'+level),
        'test','S0' if kind=='iv' else ('F75' if kind=='entry' else 'O75'),kind,level,variant,cohort,**kw)

def history():
    rng=np.random.default_rng(111);n=5000;nq=70
    start=np.datetime64('2023-11-01','ms').astype(np.int64)
    h=dict(j=rng.integers(1,9,n),i=rng.integers(10,30,n),t=start+rng.integers(0,733*DAY,n),
        y=rng.integers(0,2,n),cell=rng.integers(0,500,n))
    q=dict(row_id=np.arange(nq,dtype=np.uint64),frame=np.where(np.arange(nq)%2,2,0),
        opponent_id=rng.integers(1,9,nq),recipient_id=rng.integers(10,35,nq),
        archive_start_ms=start+rng.integers(100*DAY,600*DAY,nq),month_code=rng.integers(4,20,nq))
    q['anchor_ms']=q['archive_start_ms']+2000
    ref=rng.uniform(.05,.5,(2,24,4,4,500));ref[:,0]=np.nan
    return h,q,ref

class ScoreTests(unittest.TestCase):
    def test_donor_month_all_rows_against_independent_masks_and_fallback(self):
        h,q,ref=history();A,B,C,sel,diag,meta=scoring.score(h,q,ref)
        check=scoring.oracle(h,q,ref,A,B,C,sel,diag,len(q['row_id']))
        self.assertEqual(check['queries_checked'],len(q['row_id']))
        self.assertTrue((diag['n_fallback']>0).all())
        self.assertTrue(any(x['donor_month_code']==24 and x['fallback_model_month_code']==23 for x in meta['fallback_model_map']))
        self.assertTrue(any(x['donor_month_code']==0 and x['fallback_model_month_code']==1 for x in meta['fallback_model_map']))

    def test_pair_mutation_boundaries_and_counterpart_breadth(self):
        t=np.datetime64('2024-06-01','ms').astype(np.int64)
        h=dict(j=np.ones(10,int),i=np.array([2,2,2,3,3,4,4,4,5,5]),t=t+np.array([-20,0,20,-20,0,0,10,11,20,40]),
            y=np.arange(10)%2,cell=np.zeros(10,int))
        q=dict(row_id=np.array([4]),frame=np.array([0]),opponent_id=np.array([1]),recipient_id=np.array([2]),
            archive_start_ms=np.array([t]),anchor_ms=np.array([t+10]),month_code=np.array([7]))
        ref=np.full((2,24,4,4,500),.2);A,B,C,*_=scoring.score(h,q,ref)
        self.assertEqual((A['n'][0],B['n'][0],C['n'][0]),(7,1,3))
        self.assertEqual((A['counterparts'][0],B['counterparts'][0],C['counterparts'][0]),(3,1,2))
        h2=copy.deepcopy(h);h2['y'][:3]=1-h2['y'][:3]
        np.testing.assert_array_equal(A['adjusted'],scoring.score(h2,q,ref)[0]['adjusted'])
        h2['y'][-1]=1-h2['y'][-1]
        self.assertAlmostEqual(abs(A['adjusted'][0]-scoring.score(h2,q,ref)[0]['adjusted'][0]),1/7)

    def test_donor_month_differs_from_focal_month_and_fold_holdouts_preserved(self):
        h,q,ref=history();ref[:,0]=ref[:,1]
        A,*_=scoring.score(h,q,ref);oldA,*_=ul_scores.score(h,q,ref)
        self.assertGreater(np.max(np.abs(A['adjusted']-oldA['adjusted'])),.001)
        changed=copy.deepcopy(q);changed['month_code']=(q['month_code']+1)%24
        np.testing.assert_allclose(A['adjusted'],scoring.score(h,changed,ref)[0]['adjusted'],atol=1e-14)

    def test_missing_all_models_fails_and_no_zero_imputation(self):
        h,q,ref=history();ref[:]=np.nan
        with self.assertRaisesRegex(RuntimeError,'No usable'):scoring.score(h,q,ref)

    def test_worker_filters_authors_and_preserves_full_learning_history_and_resumes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);j=123;i=456;author=789;t=np.datetime64('2024-06-01','ms').astype(np.int64)
            shard=int(r.num.user_hash(np.array([j]))[0]%np.uint64(16))
            h=dict(j=np.array([j]*16),i=np.array([i,i,author]+list(range(900,913))),t=t+np.arange(16)*100,
                y=np.arange(16)%2,arm=np.array([True]*15+[False]),fair=np.ones(16,bool),cell=np.arange(16)%4)
            r.io.table(p/'donor.parquet',pa.table(h))
            q=dict(row_id=np.array([5]),frame=np.array([0],np.int8),opponent_id=np.array([j]),recipient_id=np.array([i]),
                archive_start_ms=np.array([t+500]),anchor_ms=np.array([t+700]),month_code=np.array([7]),n_7d=np.array([5]))
            r.io.table(p/'q.parquet',pa.table(q));np.save(p/'ref.npy',np.full((2,24,4,4,500),.1))
            j0=dict(parts=[dict(path=str(p/'donor.parquet'),sha256=u.sha(p/'donor.parquet'),rows=16)],authors=[author],
                shard=shard,queries=str(p/'q.parquet'),reference=str(p/'ref.npy'),output=str(p/'score'),conf='test')
            got=scoring.score_job(j0);self.assertEqual(got['eligible_author_clean_donor_rows'],14)
            row=r.io.read(p/'score/scores.parquet').to_pylist()[0];self.assertEqual(row['n_A'],12)
            stamp=(p/'score/scores.parquet').stat().st_mtime_ns;scoring.score_job(j0)
            self.assertEqual(stamp,(p/'score/scores.parquet').stat().st_mtime_ns)

class ModelTests(unittest.TestCase):
    def test_streamed_design_and_full_estimator_match_frozen_R7_both_levels(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p)
            for level in LEVELS:
                j=job(p,level);v,groups,ids,meta,outs,_=fits.build_buffer(j)
                dd=copy.deepcopy(d)
                for oldn,new in [('n_7d','n_A'),('counterparts_7d','counterparts_A'),('expected_7d','expected_A'),('adjusted_7d','adjusted_A')]:dd[oldn]=a[new]
                xs,names,traits,gg=r.feature_design(dd,level);width=1+len(outs)+7
                np.testing.assert_allclose(v[:,width:],xs,rtol=0,atol=1e-13)
                for k in range(3):np.testing.assert_array_equal(groups[k],gg[k])
                np.testing.assert_allclose(v[:,1+len(outs):width],np.column_stack([traits[k] for k in r.T30]),atol=1e-13)
                got,_=fits.estimate(j);expected,inf=models.estimate(dd,'iv','S0',level,part_a=False,calibration=False)
                for x,y in zip(got['estimates'],expected['B_estimates']):
                    for key in ('coefficient','standard_error','iv_coefficient','iv_standard_error','partial_first_stage_R2'):
                        if key in y:self.assertAlmostEqual(x[key],y[key],10)
                    if 'AR95_intervals_pp' in y:np.testing.assert_allclose(x['AR95_intervals_pp'],y['AR95_intervals_pp'],atol=1e-8)
                self.assertAlmostEqual(got['joint_balance'][0]['wald_chi2'],expected['B_joint_balance'][0]['wald_chi2'],7)

    def test_before_full_never_drops_unsupported_and_common_rows_match(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p);a['n_B'][:3]=2;a['n_C'][3:8]=1;r.io.table(p/'scores.parquet',pa.table(a))
            result,inf=fits.estimate(job(p,variant='B'))
            self.assertIsNone(inf);self.assertEqual(result['estimates'][0]['unsupported_donor_rows'],3)
            self.assertEqual(result['estimates'][0]['n'],len(d['row_id']))
            masks=[]
            for v in ('A','B','C'):masks.append(fits.selection(job(p,variant=v,cohort='timing_common'))[1])
            self.assertEqual(masks[0].sum(),len(d['row_id'])-8)
            for v in masks[1:]:np.testing.assert_array_equal(v,masks[0])

    def test_all_three_history_controls_replaced_per_variant(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p)
            for variant in ('A','B','C'):
                v,*_=fits.build_buffer(job(p,level='X0',variant=variant))
                width=11
                for name,raw in [('log_opponent_prior_decisions',np.log1p(a['n_'+variant])),
                    ('log_opponent_prior_counterparts',np.log1p(a['counterparts_'+variant])),('opponent_history_expected_rate',a['expected_'+variant])]:
                    want=(raw-raw.mean())/max(raw.std(),1e-12)
                    np.testing.assert_allclose(v[:,width+r.X0.index(name)],want,atol=1e-13)

    def test_stacked_paired_IV_and_RF_against_joint_influence(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);fixture(p);jobs=[]
            for v in ('B','C'):
                j=job(p,variant=v,cohort='timing_common');fits.fit_job(j);jobs.append(j)
            cj=dict(left=jobs[1]['output'],right=jobs[0]['output'],label='after_minus_before',outcomes=['y','reached','iv_y'],
                level='X0_ENV_indicator',conf='test',output=str(p/'contrast'))
            fits.contrast_job(cj);rows=u.load(p/'contrast/result.json')
            a=r.arrays(r.io.read(Path(jobs[1]['output'])/'influence_PRIVATE.parquet'));b=r.arrays(r.io.read(Path(jobs[0]['output'])/'influence_PRIVATE.parquet'))
            codes=r.stats.cmp.covariance_codes(a['recipient_id'],a['opponent_id'],a['date'])
            for row,key in zip(rows,['y','reached','iv_y']):
                variance=float(shared_meat(a[key]-b[key],codes,True)[0,0])
                self.assertAlmostEqual(row['standard_error']**2,variance,10)
            # Shared same-row covariance differs materially from assuming independence.
            V=np.array(rows[2]['covariance_matrix']);self.assertNotAlmostEqual(V[0,1],0,8)

    def test_common_scale_preserves_IV_and_scales_all_slope_intervals(self):
        row=m7.inference(.02,.0001);row['outcome_mean_pp']=1.5;out=scaled(row,.05)
        self.assertAlmostEqual(out['coefficient_pp'],.1)
        self.assertAlmostEqual(out['standard_error_pp'],.05)
        self.assertAlmostEqual(out['ci90_low_pp'],5*(.02-1.6448536269514722*.01))
        self.assertAlmostEqual(out['coefficient_pp_per_legacy_SD'],100*BRIDGE_SD*.02)

    def test_figure_equal_bins_and_resume_dependency_gate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p,4403);j=job(p,figure=True);fits.fit_job(j)
            rows=u.load(Path(j['output'])/'result.json')['figure5'];bins=[x for x in rows if 'bin' in x]
            self.assertEqual(len(bins),20);self.assertEqual(sum(v['rows'] for v in bins),len(d['row_id']))
            self.assertLessEqual(max(v['rows'] for v in bins)-min(v['rows'] for v in bins),1)
            self.assertTrue(all('ci95_low_pp' in x for x in bins))
            stamp=(Path(j['output'])/'result.json').stat().st_mtime_ns;fits.fit_job(j)
            self.assertEqual(stamp,(Path(j['output'])/'result.json').stat().st_mtime_ns)
            a['expected_A'][0]+=.01;r.io.table(p/'scores.parquet',pa.table(a))
            with self.assertRaisesRegex(RuntimeError,'input changed'):fits.fit_job(j)

    def test_calibration_uses_X0_NH_and_full_primary_outer(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);fixture(p)
            j=dict(input=str(p/'data.parquet'),scores=str(p/'scores.parquet'),level='X0_ENV_indicator',conf='test',output=str(p/'G'))
            fits.calibration_job(j);rows=u.load(p/'G/result.json')
            self.assertEqual({v['outcome'] for v in rows},{'y','received'})
            for row in rows:
                self.assertEqual(row['training_controls'],r.NH);self.assertTrue(row['prediction_rule_uncertainty_included'])
                self.assertIn('env_supported',row['outer_controls'])

class ContractTests(unittest.TestCase):
    def test_baseline_replays_all_fourteen_complete_models_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p,4300);base=p/'baseline';(base/'scores_combined').mkdir(parents=True)
            paths={k:p/'data.parquet' for k in ('S0','F50','O50')}
            for sample_name in ('S0','F50','O50'):
                score=base/('ordinary_scores/scores.parquet' if sample_name=='O50' else 'scores_combined/'+sample_name+'.parquet')
                r.io.table(score,pa.table(dict(row_id=d['row_id'],n_all_time=a['n_A'],adjusted_all_time=a['adjusted_A'],
                    n_before=a['n_B'],n_after=a['n_C'],adjusted_before=a['adjusted_B'],adjusted_after=a['adjusted_C'])))
            material=p/'material.parquet';r.io.table(material,pa.table(dict(row_id=d['row_id'],material_valid=np.ones(len(d['row_id']),bool),
                material_neutral=np.arange(len(d['row_id']))%10!=0)))
            for level in old.LEVELS:
                for sample_name,kind in [('S0','iv'),('F50','entry'),('O50','ordinary')]:
                    score=base/('ordinary_scores/scores.parquet' if sample_name=='O50' else 'scores_combined/'+sample_name+'.parquet')
                    for screen in (('all','neutral') if sample_name=='S0' else ('all',)):
                        name=f'{sample_name}__{screen}__all_time__{level}'
                        j=inputs.ul_models.make_job(paths[sample_name],score,base/'fits'/name,BASE_CONF,sample_name,kind,level,screen,material if screen=='neutral' else None)
                        inputs.ul_models.fit_job(j)
                for variant in ('all_time','before','after'):
                    name=f'S0__timing_common__{variant}__{level}'
                    j=inputs.ul_models.make_job(paths['S0'],base/'scores_combined/S0.parquet',base/'fits'/name,BASE_CONF,'S0','iv',level,variant=variant,cohort='timing_common')
                    inputs.ul_models.fit_job(j)
            before={str(f):u.sha(f) for f in base.rglob('*') if f.is_file()}
            checks=inputs.replay_baseline(paths,base,material,p/'replay','r9-test',2,4)
            self.assertEqual(len(checks),14);self.assertTrue(all(x['passed'] for x in checks))
            self.assertEqual(before,{str(f):u.sha(f) for f in base.rglob('*') if f.is_file()})

    def test_combiner_replays_F50_after_row_id_rebinding_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p);paths={};base=p/'baseline';(base/'scores_combined').mkdir(parents=True)
            # Expanded F uses shifted row IDs; old F50 is a strict game subset.
            f={k:v.copy() for k,v in d.items()};f['row_id']=f['row_id']+100000
            oldf={k:v[::2] for k,v in d.items()}
            for name,data in [('S0',d),('F',f),('F50',oldf)]:
                paths[name]=p/(name+'.parquet');r.io.table(paths[name],pa.table(data))
            out=p/'shard';out.mkdir();ss=[];pp=[]
            for frame,dd in [(0,d),(2,f)]:
                aa={k:v.copy() for k,v in a.items()};aa['row_id']=dd['row_id'];aa['frame']=np.full(len(dd['row_id']),frame,np.int8)
                ss.append(pa.table(aa))
                replay=dict(row_id=dd['row_id'],frame=aa['frame'],n_all_time=aa['n_A'],counterparts_all_time=aa['counterparts_A'],
                    adjusted_all_time=aa['old_adjusted'],expected_all_time=aa['old_expected'],
                    raw_all_time=aa['old_adjusted']+aa['old_expected'],grants_all_time=aa['n_A']*(aa['old_adjusted']+aa['old_expected']),
                    n_before=aa['n_B'] if frame==0 else np.full(len(dd['row_id']),-1),n_after=aa['n_C'] if frame==0 else np.full(len(dd['row_id']),-1),
                    adjusted_before=aa['adjusted_B'] if frame==0 else np.full(len(dd['row_id']),np.nan),
                    adjusted_after=aa['adjusted_C'] if frame==0 else np.full(len(dd['row_id']),np.nan),
                    n_focal_interval=np.zeros(len(dd['row_id']),int) if frame==0 else np.full(len(dd['row_id']),-1))
                pp.append(pa.table(replay))
                if frame==0:oldscore={k:v for k,v in replay.items() if k!='frame'};r.io.table(base/'scores_combined/S0.parquet',pa.table(oldscore))
                else:
                    oldscore={k:v[::2] for k,v in replay.items() if k!='frame'};oldscore['row_id']=oldf['row_id']
                    r.io.table(base/'scores_combined/F50.parquet',pa.table(oldscore))
            r.io.table(out/'scores.parquet',pa.concat_tables(ss));r.io.table(out/'replay.parquet',pa.concat_tables(pp))
            values,info=scoring.combine([dict(output=str(out))],paths,base,p/'combined','test',1)
            self.assertTrue(info['baseline_scores_reproduced']);self.assertEqual(set(values),{'S0','F'})
            self.assertTrue(any(x['sample']=='F50' and x.get('score_reused_from_larger_frame') for x in info['baseline_checks']))
            bad=r.arrays(r.io.read(base/'scores_combined/F50.parquet'));bad['adjusted_all_time']=bad['adjusted_all_time'].copy();bad['adjusted_all_time'][0]+=.01
            r.io.table(base/'scores_combined/F50.parquet',pa.table(bad))
            with self.assertRaisesRegex(RuntimeError,'F50 score replay failed'):
                scoring.combine([dict(output=str(out))],paths,base,p/'bad','test',1)

    def test_nested_baseline_gate_detects_coefficient_and_SE_changes(self):
        x=dict(rows=[dict(coefficient=.28,standard_error=.1,supported=True)])
        self.assertEqual(assert_close(x,x,'test')['numbers_checked'],2)
        for key in ('coefficient','standard_error'):
            bad=copy.deepcopy(x);bad['rows'][0][key]+=.001
            with self.assertRaisesRegex(RuntimeError,'numerical replay'):assert_close(bad,x,'test')

    def test_ordinary_reuses_F_without_F_prospective_outcomes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p);o={k:v[::2] for k,v in d.items()}
            f={k:v for k,v in d.items() if k not in ('y','reached','complete90')}
            r.io.table(p/'F.parquet',pa.table(f));r.io.table(p/'O.parquet',pa.table(o))
            output,info=scoring.ordinary(dict(F=p/'F.parquet',O=p/'O.parquet'),p/'scores.parquet',p/'O_scores','test',1)
            self.assertEqual(pq.ParquetFile(output).metadata.num_rows,len(o['row_id']));self.assertEqual(info['extra_donor_scans'],0)
            o['recipient_id'][0]+=1;r.io.table(p/'badO.parquet',pa.table(o))
            with self.assertRaisesRegex(RuntimeError,'identity mismatch'):
                scoring.ordinary(dict(F=p/'F.parquet',O=p/'badO.parquet'),p/'scores.parquet',p/'bad','test',1)

    def test_phase100_discovery_ignores_live_metadata_and_selects_completed_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);desktop=p/'desktop';desktop.mkdir();root=p/'derived/replication/run2_phase100_analysis_v100_PRIVATE/abc/report'
            root.mkdir(parents=True);r.io.js(root/'summary.json',dict(phase_percent=100,status='PHASE_100_AVAILABLE_CASE_ANALYSIS_COMPLETE'))
            self.assertEqual(inputs.phase_candidates(p,desktop),[root.parent])

    def test_full_report_collects_required_models_and_keeps_private_rows_out(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,a=fixture(p,5200);run=p/'run';plan=[];lookup={}
            neutral=np.arange(len(d['row_id']))%10!=0
            r.io.table(p/'material.parquet',pa.table(dict(row_id=d['row_id'],material_valid=np.ones(len(neutral),bool),material_neutral=neutral)))
            for level in LEVELS:
                for v,cohort in [('A','full'),('A','neutral'),('B','full'),('A','timing_common'),('B','timing_common'),('C','timing_common')]:
                    j=fits.make_job(p/'data.parquet',p/'scores.parquet',run/'fits'/f'S0__{cohort}__{v}__{level}','test','S0','iv',level,v,cohort,
                        p/'material.parquet' if cohort=='neutral' else None,figure=(v=='A' and cohort=='full' and level==LEVELS[0]))
                    fits.fit_job(j);plan.append(j);lookup[(cohort,v,level)]=j['output']
                for s,kind in [('F75','entry'),('O75','ordinary')]:
                    j=fits.make_job(p/'data.parquet',p/'scores.parquet',run/'fits'/f'{s}__A__{level}','test',s,kind,level)
                    fits.fit_job(j);plan.append(j);lookup[(s,'A',level)]=j['output']
                for label,left,right,outs in [('after_minus_before',lookup[('timing_common','C',level)],lookup[('timing_common','B',level)],['y','reached','iv_y']),
                    ('S0_minus_ordinary',lookup[('full','A',level)],lookup[('O75','A',level)],['y','reached'])]:
                    fits.contrast_job(dict(left=left,right=right,label=label,outcomes=outs,level=level,conf='test',output=str(run/'contrasts'/(label+level))))
                fits.calibration_job(dict(input=str(p/'data.parquet'),scores=str(p/'scores.parquet'),level=level,conf='test',output=str(run/'calibration'/level)))
            r.io.js(run/'common_scale.json',dict(common_score_SD=.05))
            tables,complete=report.collect(run,.05)
            self.assertEqual(len(complete),16);self.assertEqual(len(tables['C_paired_timing']),6)
            self.assertEqual(len(tables['D_receipt_minus_placebo']),4);self.assertEqual(len(tables['G_implied_bias']),4)
            self.assertEqual(len(tables['F_joint_balance']),8)
            summary=report.export(run,p/'desktop','synthetic',75,'SYNTHETIC_TEST_ONLY',dict(comparison_frame=dict(phase_percent=75)))
            self.assertEqual(summary['common_score_SD'],.05)
            import zipfile
            with zipfile.ZipFile(next((p/'desktop').glob('*.zip'))) as z:
                self.assertIsNone(z.testzip());self.assertFalse(any('PRIVATE' in n for n in z.namelist()))
            for rec in u.load(run/'report/REPORT_MANIFEST.json'):self.assertEqual(u.sha(run/'report'/rec['path']),rec['sha256'])
            with self.assertRaisesRegex(RuntimeError,'Full S0 receipt contract'):
                report.validate(tables,plan,run,dict(frame_rows=dict(F=5200,O=5200)))

    def test_spawned_worker_memory_reservations(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);fixture(p);j=job(p)
            got=runtime.mapped(fits.fit_job,[j],2,4,'synthetic R9 worker',1)
            self.assertTrue(got[0]['influence_saved'])
            with self.assertRaisesRegex(RuntimeError,'exceeds'):runtime.capacity([dict(memory_gb=10)],10,11)

if __name__=='__main__':unittest.main()
