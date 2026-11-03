import os,sys,tempfile,unittest,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from common_retained import *
from frames_retained import prospective_keep
from retained_export import f5_wide
from systems import fit_system
from balance_retained import fit_balance,calibration
from types import SimpleNamespace

def fixture(root,n=3200):
    path=ROOT/'frozen_iv/tests/test_estimators.py';spec=importlib.util.spec_from_file_location('original_fixture',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source,scores=module.fixture(root,n);rng=np.random.default_rng(928)
    source_data=pq.ParquetFile(source).read().to_pydict();source_data['pre_games_30d']=rng.integers(5,120,n)
    for k in ('fair','kind','disconnect','receipt','claim'):
        source_data['recent_'+k+'_90']=rng.integers(0,8,n)
    source_data['recent_kind_90']=np.minimum(source_data['recent_kind_90'],source_data['recent_fair_90'])
    pq.write_table(pa.table(source_data),source)
    return source,scores

class RetainedTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.p=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_prospective_cooldown_ignores_future_and_simultaneous_exposures(self):
        events=dict(recipient_id=np.array([1,1,2,3]),anchor_ms=np.array([100,200*DAY,20,500]))
        person=np.array([1,1,2,3,4]);start=np.array([90*DAY+100,90*DAY+101,20,499,100])
        np.testing.assert_array_equal(prospective_keep(events,person,start),[False,True,True,True,True])
    def test_stream_filter_rejects_misalignment_and_preserves_rows(self):
        s=self.p/'source.parquet';z=self.p/'scores.parquet';pq.write_table(pa.table(dict(row_id=np.arange(7),payload=['text']*7)),s);pq.write_table(pa.table(dict(row_id=np.arange(7),score=np.arange(7)/10)),z)
        out=self.p/'out';out.mkdir();mask=np.array([1,0,1,1,0,0,1],bool);filter_pair(s,z,out,mask);np.testing.assert_array_equal(col(out/'source.parquet','row_id'),[0,2,3,6])
        pq.write_table(pa.table(dict(row_id=np.arange(7)[::-1],score=np.arange(7)/10)),z)
        with self.assertRaisesRegex(RuntimeError,'aligned'):filter_pair(s,z,out,mask)
    def test_shared_account_or_date_meat_handles_cross_roles(self):
        rng=np.random.default_rng(122);n=40;actors=dict(row_id=np.arange(n),recipient_id=rng.integers(0,8,n),opponent_id=rng.integers(0,8,n),date=rng.integers(0,7,n))
        actors['opponent_id'][actors['recipient_id']==actors['opponent_id']]+=10;s=rng.normal(size=(n,3));i,j,d=actors['recipient_id'],actors['opponent_id'],actors['date']
        dep=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(d[:,None]==d)
        np.testing.assert_allclose(meat_factory(actors,self.p)(s),s.T@dep@s,atol=1e-10)
    def test_complier_ratios_and_fifteen_trait_ladder_and_calibration(self):
        source,sc=fixture(self.p);a=SimpleNamespace(workers=2,memory_gb=3);run=self.p/'run';run.mkdir();os.environ['UNIFORM90_WORKERS']='2';os.environ['UNIFORM90_MEMORY_GIB']='3'
        out=fit_system(a,run,'synthetic','compliers',source,sc,'compliers');r=read(out/'result.json');self.assertEqual(len(r['compliers']),11)
        controls=self.p/'oracle';controls.mkdir();job=kernel.job_for(run,'synthetic','oracle',source,sc,legacy=True);v,g,_,target,_,_=kernel.build_buffer(job,controls);res,_,_=kernel.project(v,g,len(target),controls)
        raw=col(source,'received')*col(source,'recipient_rating');expected=res[:,0]@raw/(res[:,0]@res[:,target.index('received')]);actual=next(x for x in r['compliers'] if x['trait']=='recipient_rating')['coefficient'];self.assertAlmostEqual(actual,expected,6)
        r=fit_balance(run,'synthetic',source,sc,'ladder',True,True);self.assertEqual(len(r['estimates']),15);self.assertEqual(len(r['joint_tests']),2)
        calibration(run,'synthetic',source,sc);self.assertEqual(len(csv_rows(run/'report/table_D2_implied_bias.csv')),2)
    def test_F5_wide_preserves_original_units_and_sources(self):
        r=f5_wide([dict(sample='spaced',term='iv_y',n=100,coefficient=.3,standard_error=.1,source_file='x.csv',source_row=2),dict(sample='spaced',term='first_stage',n=100,coefficient=7,standard_error=.02,source_file='x.csv',source_row=1)])
        self.assertEqual(len(r),1);self.assertEqual(r[0]['iv_y_source_row'],2);self.assertEqual(r[0]['first_stage_coefficient'],7)


    def test_act_controls_and_estimates_against_dense_FWL(self):
        source,sc=fixture(self.p);a=SimpleNamespace(workers=2,memory_gb=3);run=self.p/'run';run.mkdir()
        os.environ['UNIFORM90_WORKERS']='2';os.environ['UNIFORM90_MEMORY_GIB']='3'
        n=rows(source);rng=np.random.default_rng(12);f=self.p/'act.parquet'
        board=np.resize([-50,50,200,500],n);giver=rng.uniform(3,15,n);recipient=rng.uniform(3,15,n)
        pq.write_table(pa.table(dict(row_id=np.arange(n),board_cp=board,giver_cost=giver,recipient_benefit=recipient)),f)
        result=read(fit_system(a,run,'synthetic','act',source,sc,'act',f)/'result.json')
        self.assertEqual(len(result['first_stages']),6);self.assertEqual(len(result['estimates']),7)
        expected_controls=list(kernel.frozen.r.X0)+list(kernel.frozen.r.ENV)+['env_supported','giver_cost_5','recipient_benefit_5','band_1','band_2','band_3']
        self.assertEqual(result['estimates'][0]['controls'],expected_controls)
        self.assertNotIn('z',expected_controls)
        oracle=self.p/'oracle_act';oracle.mkdir();job=kernel.job_for(run,'synthetic','oracle_act',source,sc,legacy=True)
        v,groups,actors,targets,meta,events=kernel.build_buffer(job,oracle)
        band=np.searchsorted([0,100,300],board,side='right')
        mods=np.column_stack([(band==j).astype(float) for j in range(4)]+[(giver-giver.mean())/5,(recipient-recipient.mean())/5])
        nuisance=np.column_stack([v[:,len(targets):],mods[:,1:]])
        for group in groups:
            _,inverse=np.unique(group,return_inverse=True);nuisance=np.column_stack([nuisance,np.eye(inverse.max()+1)[inverse]])
        Y=col(source,'y');D=col(source,'received')[:,None]*mods;Z=col(sc,'adjusted_A')[:,None]*mods
        T=np.column_stack([Y,D,Z]);R=T-nuisance@np.linalg.lstsq(nuisance,T,rcond=1e-10)[0]
        beta=np.linalg.solve(R[:,7:].T@R[:,1:7],R[:,7:].T@R[:,0])
        np.testing.assert_allclose(result['system'][0]['coefficients'],beta,rtol=2e-7,atol=2e-7)
        with self.assertRaisesRegex(RuntimeError,'authorized'):fit_system(a,run,'synthetic','excluded',source,sc,'two_score')

if __name__=='__main__':unittest.main()

