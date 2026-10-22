import sys, tempfile, unittest, json, zipfile, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from r9_common import *
import r9_scores as sc, r9_models as fits, r9_inputs as inp, r9_report as report

def ms(s):return int(np.datetime64(s,'ms').astype(np.int64))

def synthetic(n=4200):
    rng=np.random.default_rng(92026)
    d=dict(row_id=np.arange(n,dtype=np.uint64),recipient_id=rng.integers(1,501,n),opponent_id=rng.integers(501,1001,n),
        archive_start_ms=ms('2024-05-01')+rng.integers(0,65*DAY,n),month_code=rng.integers(6,8,n),
        tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n,dtype=int),recipient_rating=rng.normal(1600,65,n),opponent_rating=rng.normal(1600,65,n),
        n_7d=rng.integers(6,80,n),counterparts_7d=rng.integers(3,6,n),expected_7d=rng.uniform(.02,.10,n),
        adjusted_7d=rng.normal(0,.09,n),pre_games_30d=rng.integers(5,500,n),environment_supported=rng.random(n)>.2)
    for days in (30,90):
        fair=rng.integers(0,8,n);kind=np.minimum(fair,rng.poisson(.7,n))
        d.update({f'fair_{days}':fair,f'kind_{days}':kind})
        for k in ('disconnect','receipt','claim'):d[f'{k}_{days}']=rng.integers(0,30,n)
    for k in r.ENV:
        d[k]=rng.uniform(.01,.20,n);d[k][~d['environment_supported']]=np.nan
    d['received']=(rng.random(n)<np.clip(.2+1.5*d['adjusted_7d'],.02,.85)).astype(int)
    d['y']=(rng.random(n)<.06+.04*d['received']).astype(int)
    d['reached']=((rng.random(n)<.5)|d['y'].astype(bool)).astype(int)
    for k in ('analysis_entry_90','recipient_disconnect_main','active_timeout'):d[k]=(rng.random(n)<.1).astype(int)
    d['complete90']=np.ones(n,bool)
    a={'row_id':d['row_id']}
    for tag in 'ABC':
        for k,dest in [('n','n_7d'),('counterparts','counterparts_7d'),('expected','expected_7d'),('adjusted','adjusted_7d')]:
            a[k+'_'+tag]=d[dest].copy()
    a['adjusted_B']=.8*d['adjusted_7d']+rng.normal(0,.03,n)
    a['adjusted_C']=d['adjusted_7d']+rng.normal(0,.02,n)
    a['n_C'][:50]=2
    return d,a

class DonorTests(unittest.TestCase):
    def fixture(self):
        t=np.array([ms(s) for s in ['2023-11-10','2023-12-01','2024-01-01','2024-01-02','2024-01-03','2024-01-04','2024-02-01','2024-03-01','2024-04-01','2025-11-02']])
        h=dict(j=np.ones(10,dtype=np.int64),i=np.array([8,2,3,3,2,4,5,2,6,7]),t=t,y=np.array([1,1,0,1,0,1,0,1,1,0]),cell=np.arange(10,dtype=np.int16))
        q=dict(row_id=np.arange(3,dtype=np.uint64),frame=np.zeros(3,np.int8),opponent_id=np.ones(3,dtype=np.int64),recipient_id=np.array([2,99,3]),
            archive_start_ms=np.full(3,ms('2024-01-02')),anchor_ms=np.full(3,ms('2024-01-04')),month_code=np.full(3,2,np.int16))
        ref=np.zeros((2,24,4,4,500),float)
        for m in range(24):ref[:,m,:,:,:]=.02+m*.002+np.arange(500)[None,None,None,:]*.00001
        ref[:,0]=np.nan
        return h,q,ref

    def test_donor_month_all_pair_exclusion_ties_breadth_fallback(self):
        h,q,ref=self.fixture();out,fb=sc.score(h,q,ref);sc.oracle(h,q,ref,out)
        self.assertEqual(out['n_A'][0],7)
        self.assertEqual(out['n_B'][0],2) # excludes exact start, and all j-to-i decisions
        self.assertEqual(out['n_C'][0],3) # excludes exact anchor
        self.assertEqual(out['counterparts_B'][0],2)
        self.assertEqual(out['counterparts_C'][0],3)
        self.assertEqual(out['fallback_donors_A'][0],2) # initial unavailable month and terminal overflow
        self.assertTrue(any(x['model_month_code']==23 and x['donor_month_code']==24 for x in fb))
        self.assertTrue(np.all(out['n_A']>=out['n_B']+out['n_C']))

    def test_no_pair_leakage_into_before_or_after(self):
        h,q,ref=self.fixture();a,_=sc.score(h,q,ref)
        h['y']=h['y'].copy();h['y'][h['i']==2]=1-h['y'][h['i']==2]
        b,_=sc.score(h,q,ref)
        for tag in 'ABC':self.assertAlmostEqual(a['adjusted_'+tag][0],b['adjusted_'+tag][0])

    def test_focal_month_change_does_not_change_donor_month_score(self):
        h,q,ref=self.fixture();a,_=sc.score(h,q,ref);q['month_code']+=1;b,_=sc.score(h,q,ref)
        np.testing.assert_array_equal(a['adjusted_A'],b['adjusted_A'])
        self.assertFalse(np.array_equal(a['cross_month_donors'],b['cross_month_donors']))

    def test_fallback_never_uses_future_model(self):
        _,_,ref=self.fixture();mapping,_=sc.model_map(ref,np.arange(-1,26))
        self.assertTrue(all(v<=k[0] or v==-1 for k,v in mapping.items()))
        self.assertEqual(mapping[(0,1,2)],-1)

    def test_numerical_baseline_gate_is_not_rounding_based(self):
        target={'n':2000,'coefficient_pp':.281,'standard_error_pp':.108}
        compare_numbers(dict(target,coefficient_pp=.281+1e-11),target)
        with self.assertRaises(RuntimeError):compare_numbers(dict(target,coefficient_pp=.281+1e-6),target)
        with self.assertRaises(RuntimeError):compare_numbers(dict(target,n=1999),target)

class ModelTests(unittest.TestCase):
    def test_disk_design_equals_frozen_R7_transforms_and_FE(self):
        d,_=synthetic()
        with tempfile.TemporaryDirectory() as td:
            for level in LEVELS:
                oldx,names,traits,groups=r.feature_design(d,level)
                x,nn,t,gg=fits.design(d,level,Path(td))
                self.assertEqual(nn,names)
                np.testing.assert_allclose(x,oldx,rtol=1e-12,atol=1e-12)
                for k,name in enumerate(r.T15):np.testing.assert_allclose(t[:,k],traits[name],rtol=1e-12,atol=1e-12)
                for a,b in zip(groups,gg):np.testing.assert_array_equal(a,b)

    def test_bounded_estimator_matches_frozen_R7_and_units(self):
        d,a=synthetic()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);r.io.table(root/'input.parquet',pa.table(d));r.io.table(root/'scores.parquet',pa.table(a))
            reference,_=models.estimate(dict(d),'iv','S0','X0_ENV_indicator',part_a=False,calibration=False)
            job=fits.make_job(root/'input.parquet',root/'scores.parquet',root/'fits','test',label='primary',sample='S0',level='X0_ENV_indicator',primary_sd=.07,balance=True,figure=True,implied_bias=True)
            info=fits.fit_job(job);out=u.load(Path(job['output'])/'result.json')
            for got,want in zip(out['estimates'],reference['B_estimates']):
                for k in ('coefficient','standard_error','iv_coefficient','iv_standard_error'):
                    if k in want:self.assertAlmostEqual(got[k],want[k],places=10)
                if 'coefficient' in got:
                    self.assertAlmostEqual(got['coefficient_pp_per_primary_SD'],got['coefficient']*7)
                    self.assertAlmostEqual(got['coefficient_pp_per_fixed_0_0594'],got['coefficient']*5.94)
            self.assertAlmostEqual(out['estimates'][-1]['partial_first_stage_R2'],reference['B_estimates'][-1]['partial_first_stage_R2'],places=12)
            np.testing.assert_allclose(out['estimates'][-1]['AR95_intervals_pp'],reference['B_estimates'][-1]['AR95_intervals_pp'],rtol=1e-8)
            self.assertEqual(sum(x['n'] for x in out['figure5']),len(d['row_id']))
            self.assertEqual(len(out['figure5']),20)
            self.assertLessEqual(max(x['n'] for x in out['figure5'])-min(x['n'] for x in out['figure5']),1)
            self.assertEqual(len(out['implied_bias']),2)
            self.assertTrue(all(x['prediction_rule_uncertainty_included'] for x in out['implied_bias']))
            self.assertEqual(len(out['balance']),7)
            self.assertEqual(fits.fit_job(job)['n'],info['n']) # authenticated resume
            changed=dict(job);changed['input']=str(root/'other.parquet');r.io.table(root/'other.parquet',pa.table(d))
            with self.assertRaises(RuntimeError):fits.fit_job(changed)

    def test_common_rows_and_full_before_are_distinct(self):
        d,a=synthetic(4000)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);r.io.table(root/'input.parquet',pa.table(d));r.io.table(root/'scores.parquet',pa.table(a))
            base=dict(input=str(root/'input.parquet'),scores=str(root/'scores.parquet'),variant='B')
            full=fits.load_data(base,root/'full');common=fits.load_data(dict(base,cohort='common'),root/'common')
            self.assertEqual(len(full['row_id']),4000);self.assertEqual(len(common['row_id']),3950)
            np.testing.assert_array_equal(full['adjusted_7d'],a['adjusted_B'])
            a['expected_C']=a['expected_A']+.1
            r.io.table(root/'c.parquet',pa.table(a))
            after=fits.load_data(dict(base,scores=str(root/'c.parquet'),variant='C',cohort='common'),root/'after')
            np.testing.assert_array_equal(after['expected_7d'],a['expected_A'][50:])
            a['n_B'][0]=4;r.io.table(root/'bad.parquet',pa.table(a))
            with self.assertRaises(RuntimeError):fits.load_data(dict(base,scores=str(root/'bad.parquet')),root/'bad')

    def test_entry_ignores_unused_null_receipt_and_competitive_fields(self):
        d,a=synthetic(100)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);t=pa.table(d)
            t=t.set_column(t.schema.get_field_index('received'),'received',pa.nulls(100))
            t=t.append_column('comp_adjusted_7d',pa.nulls(100))
            r.io.table(root/'input.parquet',t);r.io.table(root/'scores.parquet',pa.table(a))
            got=fits.load_data(dict(input=str(root/'input.parquet'),scores=str(root/'scores.parquet'),variant='A',kind='entry',level='X0'),root/'work')
            self.assertEqual(len(got['row_id']),100)
            self.assertNotIn('received',got);self.assertNotIn('comp_adjusted_7d',got)

    def test_stacked_covariance_matches_dense_OR_and_paired_difference(self):
        rng=np.random.default_rng(42)
        l=dict(recipient_id=np.array([1,2,4,5,1]),opponent_id=np.array([2,3,5,6,8]),date=np.array([1,2,2,3,4]),y=rng.normal(size=5))
        rr=dict(recipient_id=np.array([3,7,1,5]),opponent_id=np.array([4,5,2,8]),date=np.array([1,3,5,4]),y=rng.normal(size=4))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);r.io.table(root/'l.parquet',pa.table(l));r.io.table(root/'r.parquet',pa.table(rr))
            v=fits.covariance_sql(root/'l.parquet',root/'r.parquet','y','y',root,1)
            i=np.r_[l['recipient_id'],rr['recipient_id']];j=np.r_[l['opponent_id'],rr['opponent_id']];day=np.r_[l['date'],rr['date']]
            s=np.zeros((9,2));s[:5,0]=l['y'];s[5:,1]=rr['y'];want=np.zeros((2,2))
            for a in range(9):
                for b in range(9):
                    if len({int(i[a]),int(j[a])}&{int(i[b]),int(j[b])}) or day[a]==day[b]:want+=np.outer(s[a],s[b])
            np.testing.assert_allclose(v,want,rtol=1e-13,atol=1e-13)
            codes=r.stats.cmp.covariance_codes(i,j,day)
            np.testing.assert_allclose(v,rm.shared_meat(s,codes,True),rtol=1e-13,atol=1e-13)
            delta=s[:,0]-s[:,1]
            self.assertAlmostEqual(v[0,0]+v[1,1]-2*v[0,1],float(rm.shared_meat(delta,codes,True)[0,0]),places=12)

    def test_learning_chronology_strict_start_and_left_censoring(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r.io.table(p/'q.parquet',pa.table(dict(row_id=np.arange(4,dtype=np.uint64),recipient_id=[1,2,3,4],archive_start_ms=[10,10,10,10],fair_90=[1,0,0,0])))
            r.io.table(p/'f.parquet',pa.table(dict(person=[1,2,3],first_competitive_ms=[9,10,11])))
            out=inp.learning_flags(p/'q.parquet',[str(p/'f.parquet')],p/'flags','test',1)
            flags=r.arrays(r.io.read(out));self.assertEqual(flags['experienced_full'].tolist(),[True,False,False,False])

    def test_report_exports_only_aggregate_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'report').mkdir();(p/'report/INFLUENCE_PRIVATE.parquet').write_text('must not export')
            (p/'desktop').mkdir();report.export(p,p/'desktop','0123456789abcdef',25,'TEST',{})
            z=next((p/'desktop').glob('*.zip'))
            self.assertEqual(u.sha(z),Path(str(z)+'.sha256').read_text().split()[0])
            with zipfile.ZipFile(z) as f:
                self.assertFalse(any('PRIVATE' in n for n in f.namelist()))
                manifest=json.loads(f.read('REPORT_MANIFEST.json'))
                for item in manifest:self.assertEqual(hashlib.sha256(f.read(item['path'])).hexdigest(),item['sha256'])

if __name__=='__main__':unittest.main()
