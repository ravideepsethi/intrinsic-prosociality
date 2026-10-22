import contextlib,io,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from common import *
from numerics import *
from design import *
from estimate import *
from report import family_report,monthly_report
import inputs,run,estimate

def fixture(n=900,seed=123):
    rng=np.random.default_rng(seed);p=rng.integers(0,2,n);date=np.where(p,675,500)+rng.integers(0,25,n)
    d=dict(chooser=rng.integers(0,45,n,dtype=np.int64),y=rng.binomial(1,.12,n),deficit=rng.integers(0,9,n),
        eval10=-110-10*rng.integers(0,6,n),stage_code=rng.integers(0,3,n),clock_c=rng.uniform(50,300,n),
        clock_d=rng.uniform(150,400,n),rating=rng.uniform(1400,2200,n),rating_gap=rng.normal(0,200,n),
        date_code=date,month_code=np.where(p,2025*12+9,2025*12+3),period=p)
    return d

def save_fixture(path,d):
    import datetime
    b={k:v for k,v in d.items() if k not in ('period','month_code')}
    b['cp']=d['eval10'].astype(float);b['long_clock_cut']=np.repeat(60,len(d['y']))
    b['position_date']=[datetime.date(2023,11,1)+datetime.timedelta(days=int(t)) for t in d['date_code']]
    b['cal_month']=[t.strftime('%Y-%m') for t in b['position_date']]
    pq.write_table(pa.Table.from_pydict(b),path)

class EstimationTests(unittest.TestCase):
    def test_absorption_matches_dense_with_disconnected_groups(self):
        rng=np.random.default_rng(1);n=120
        groups=encode([np.repeat(np.arange(30),4),rng.integers(0,10,n),np.repeat([0,1],60)])
        D=np.column_stack([np.eye(g.max()+1)[g] for g in groups]);A=rng.normal(size=(n,4))
        expected=A-D@np.linalg.lstsq(D,A,rcond=1e-12)[0]
        actual=np.column_stack([absorb_column(A[:,i],groups)[0] for i in range(4)])
        np.testing.assert_allclose(actual,expected,atol=2e-9)

    def test_contrast_weights_bias_and_contamination_free_placebos(self):
        d=np.arange(9);w=WEIGHTS['one_sided_linear']
        np.testing.assert_allclose(w[:5],[.5,0,-.5,-1,1],atol=1e-14)
        self.assertAlmostEqual(w@(3+2*d),0);self.assertAlmostEqual(w@(d>=4),1)
        self.assertAlmostEqual(WEIGHTS['symmetric']@(d*d),0)
        self.assertAlmostEqual(bias_multiplier(w),2.5)
        for n,qv in WEIGHTS.items():
            if n.startswith('placebo'):self.assertAlmostEqual(qv@(d>=4),0)

    def test_peel_and_rank_detection(self):
        g=encode([np.array([0,0,1,2]),np.array([0,0,1,1])]);keep,_=peel(g)
        self.assertEqual(keep.tolist(),[True,True,False,False])
        x=np.arange(10,dtype=float);f=solve(np.column_stack([x,x]),2*x)
        self.assertFalse(estimable(f,np.array([1.,0.])));self.assertTrue(estimable(f,np.array([1.,1.])))

    def test_cross_model_covariance_retains_shared_clusters(self):
        a=(np.array([1,3,5]),np.array([[1.,2.],[3.,4.],[5.,6.]]))
        b=(np.array([2,3,5]),np.array([[9.],[2.],[7.]]))
        np.testing.assert_equal(covariance_join(a,b),np.array([[41.],[50.]]))

    def test_full_fit_dense_coefficients_CR0_reports_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'input.parquet';d=fixture();save_fixture(p,d)
            task=dict(id='primary__blitz',key='test',source=str(p),out=str(root/'fit'),spec=FAMILIES[0],speed='blitz',memory=1.)
            with contextlib.redirect_stdout(io.StringIO()):r=fit_task(task)
            model=read(root/'fit/MODEL.json');self.assertEqual(r['status'],'COMPLETE')
            actual,_=read_model(p,FAMILIES[0],1,root/'read_spill');actual,g,counts=setup(actual,['pre','post'])
            X=np.column_stack([column(actual,j,2) for j in range(24)]);y=100*actual['y'].astype(float)
            D=np.column_stack([np.eye(v.max()+1)[v] for v in g]);A=np.column_stack([X,y])
            R=A-D@np.linalg.lstsq(D,A,rcond=1e-12)[0];fit=solve(R[:,:-1],R[:,-1])
            with np.load(root/'fit/covariance.npz') as z:
                np.testing.assert_allclose(z['beta'],fit['beta'],atol=2e-7)
                mu,J,anchor,_=profile_maps(actual,['pre','post'],24,fit['beta'])
                ids,inf=influence(actual['chooser'],R[:,:-1],R[:,-1]-R[:,:-1]@fit['beta'],fit['inverse'],J,anchor)
                np.testing.assert_allclose(z['profile'],inf.T@inf,atol=2e-7)
            before=(root/'fit/MODEL.json').stat().st_mtime_ns
            with contextlib.redirect_stdout(io.StringIO()):self.assertTrue(fit_task(task)['reused'])
            self.assertEqual(before,(root/'fit/MODEL.json').stat().st_mtime_ns)
            second={**task,'id':'primary__bullet','speed':'bullet','out':str(root/'fit_bullet'),'key':'test2'}
            with contextlib.redirect_stdout(io.StringIO()):r2=fit_task(second)
            family_report(root,'primary',[r,r2]);self.assertTrue((root/'report/primary/adjusted_profiles.pdf').exists())
            with (root/'report/primary/threshold_and_policy_tests.csv').open() as f:
                for row in csv.DictReader(f):
                    if row['speed']=='blitz_minus_bullet' and row['inference']=='chooser_CR0':
                        self.assertAlmostEqual(float(row['estimate_pp']),0,places=8)
                        self.assertLess(float(row['se_pp']),1e-6)
            with (root/'fit/chooser_profiles.npz').open('ab') as f:f.write(b'tamper')
            with self.assertRaises(RuntimeError):fit_task(task)

    def test_monthly_and_empty_models(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'input.parquet';d=fixture();save_fixture(p,d)
            for m in ('2025-03','2025-09','2024-01'):
                spec=dict(name='monthly_'+m,month=m,clock_multiple=0)
                t=dict(id=spec['name']+'__blitz',key=m,source=str(p),out=str(root/m),spec=spec,speed='blitz',memory=1.)
                with contextlib.redirect_stdout(io.StringIO()):r=fit_task(t)
                if m=='2024-01':self.assertEqual(r['status'],'NO_ROWS')
                else:
                    self.assertEqual(r['status'],'COMPLETE');monthly_report(root,[r])

    def test_partial_column_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'input.parquet';save_fixture(p,fixture())
            task=dict(id='interrupted',key='test',source=str(p),out=str(root/'fit'),spec=FAMILIES[0],speed='blitz',memory=1.)
            real=estimate.absorb_column;calls=[0]
            def fail_once(*args,**kwargs):
                calls[0]+=1
                if calls[0]==3:raise RuntimeError('simulated interruption')
                return real(*args,**kwargs)
            with contextlib.redirect_stdout(io.StringIO()),patch.object(estimate,'absorb_column',fail_once):
                with self.assertRaisesRegex(RuntimeError,'simulated'):fit_task(task)
            saved=read(root/'fit/columns/00.json')['file']['sha256']
            calls=[0]
            def count(*args,**kwargs):calls[0]+=1;return real(*args,**kwargs)
            with contextlib.redirect_stdout(io.StringIO()),patch.object(estimate,'absorb_column',count):r=fit_task(task)
            self.assertEqual(r['status'],'COMPLETE');self.assertEqual(calls[0],23)

    def test_authenticated_cache_prepare_launcher_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            project=Path(td);up=project/'feasibility';records=[];total=0;key='f'*64;identity='sample-test'
            for i,m in enumerate(MONTHS):
                d=fixture(120,300+i);n=len(d['y']);total+=n
                import datetime
                day=datetime.date.fromisoformat(m+'-15');date_code=(day-datetime.date(2023,11,1)).days
                feature=dict(game_id=[m+str(j) for j in range(n)],month=[m]*n,chooser=d['chooser'],y=d['y'],deficit=d['deficit'],
                    cp=d['eval10'].astype(float),eval10=d['eval10'],stage=np.array(['ply_21_40']*n),clock_c=d['clock_c'],clock_d=d['clock_d'],
                    rating=d['rating'],rating_gap=d['rating_gap'],position_date=[day]*n,long_clock_cut=np.repeat(60,n),
                    region=['finite_lost']*n,mate=np.zeros(n,bool),speed=['blitz']*n)
                src=project/(m+'.source');src.write_text('synthetic upstream source '+m)
                path=up/'PRIVATE/months'/m/'features.parquet';path.parent.mkdir(parents=True)
                pq.write_table(pa.Table.from_pydict(feature),path)
                r=dict(month=m,path=str(src),rows=n,expected_sha256=sha(src));records.append(r)
                write(path.parent/'DONE.json',dict(key=digest([key,m,r['expected_sha256']]),source_sha256=r['expected_sha256'],
                    source_stamp=stamp(src),output=record(path),counts={'rows':n}))
            write(up/'PRIVATE/CONFIG.json',dict(key=key,input_identity=identity))
            write(up/'PRIVATE/FINAL.json',dict(key=key,status=dict(status='COMPLETE',rows=total),report_files=[]))
            write(up/'report/input_authority.json',dict(input_identity=identity))
            write(up/'PRIVATE/INPUT_BINDING.json',dict(identity=identity,rows=records,manifest_sha256='test'))
            expected=dict(configuration_sha256=key,rows=total,input_identity=identity)
            b=inputs.authenticate(project,up,expected)
            self.assertEqual(b['rows'],total)
            with patch.object(run,'authenticate',lambda project,explicit:inputs.authenticate(project,up,expected)), \
                 patch.object(run,'verify_package',lambda:'testpackage'),patch.object(run,'FAMILIES',[FAMILIES[0]]), \
                 patch.object(run,'MONTHS',['2025-03','2025-09']):
                out=io.StringIO()
                args=['--project',str(project),'--result-dir',str(project/'results'),'--workers','2','--memory-gb','4']
                with contextlib.redirect_stdout(out):status=run.main(args)
                self.assertEqual(status,0,out.getvalue())
                with contextlib.redirect_stdout(out):self.assertEqual(run.main(args),0,out.getvalue())
            p=next((project/'results').glob('*_100.zip'))
            with zipfile.ZipFile(p) as z:
                self.assertTrue(all(n.startswith('report/') for n in z.namelist()))
                for r in json.loads(z.read('report/REPORT_MANIFEST.json')):
                    self.assertEqual(hashlib.sha256(z.read('report/'+r['path'])).hexdigest(),r['sha256'])
            with Path(b['files'][0]['path']).open('ab') as f:f.write(b'tamper')
            with self.assertRaises(RuntimeError):inputs.authenticate(project,up,expected)

if __name__=='__main__':unittest.main()
