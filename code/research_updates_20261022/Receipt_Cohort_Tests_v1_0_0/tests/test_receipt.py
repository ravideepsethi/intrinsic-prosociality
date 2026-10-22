import unittest,tempfile,sys,csv,json,zipfile
from pathlib import Path
import numpy as np
import duckdb
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from numerics import absorb,fe_rank,shared_covariance,fit_ols,contrast,holm
from iv import date_covariance,conditional_scores,fit_iv,iv_design
from analysis import design,infer_weights,sample_info
from cache import bind_cache,open_data,load_scope
from common import sha,read,digest
from run import execute
from fixture import fixture

class NumericalTests(unittest.TestCase):
    def setUp(self):self.c=duckdb.connect();self.c.execute('SET threads=2')
    def tearDown(self):self.c.close()

    def test_full_cross_role_covariance_matches_pair_sum(self):
        actors=np.array([[1,2,3],[4,1,5],[2,3,1],[8,9,-1],[8,8,10]])
        h=np.arange(15).reshape(5,3)/19-0.3;v=np.zeros((3,3))
        for i in range(5):
            for j in range(5):
                if (set(actors[i])-{-1})&(set(actors[j])-{-1}):v+=np.outer(h[i],h[j])
        np.testing.assert_allclose(shared_covariance(self.c,actors,h,2),v*4/3,atol=1e-13)

    def test_date_cr0_matches_independent_pair_sum(self):
        actors=np.array([[1,2],[4,1],[2,3],[8,9],[9,8]]);day=np.array([1,2,3,1,4]);h=np.arange(15).reshape(5,3)/19-.3;v=np.zeros((3,3))
        for i in range(5):
            for j in range(5):
                if set(actors[i])&set(actors[j]) or day[i]==day[j]:v+=np.outer(h[i],h[j])
        np.testing.assert_allclose(date_covariance(self.c,actors,day,h),v,atol=1e-13)

    def test_absorbed_model_and_covariance_match_explicit_dummies(self):
        rng=np.random.default_rng(98);n=120;g=np.tile(np.arange(6),20);person=np.repeat(np.arange(20),6)
        x=rng.normal(size=(n,3));dummy=np.column_stack([np.eye(6)[g],np.eye(20)[person]])
        y=x@np.array([.2,.5,-.1])+dummy@rng.normal(size=26)+rng.normal(size=n)
        actors=np.column_stack([person,np.arange(n)+100,np.full(n,-1)])
        info,fit=fit_ols(self.c,x,y[:,None],[g,person],actors,['a','b','c'],['a','b','c'])
        full=np.column_stack([x,dummy]);bb=np.linalg.lstsq(full,y,rcond=None)[0];inv=np.linalg.pinv(full);res=y-full@bb
        np.testing.assert_allclose(fit['coefficients'][:,0],bb[:3],atol=1e-10)
        expected=shared_covariance(self.c,actors,inv[:3].T*res[:,None],int(np.linalg.matrix_rank(full)))
        np.testing.assert_allclose(fit['covariances'][0],expected,atol=1e-10)
        self.assertEqual(info['fixed_effect_rank'],np.linalg.matrix_rank(dummy))

    def test_disconnected_fe_components_and_threeway_projection(self):
        g=np.array([0,1,0,1,2,3,2,3]);p=np.array([0,0,1,1,2,2,3,3]);dummy=np.column_stack([np.eye(4)[g],np.eye(4)[p]])
        self.assertEqual(fe_rank([g,p]),np.linalg.matrix_rank(dummy))
        rng=np.random.default_rng(5);a=rng.normal(size=(80,4));groups=[np.arange(80)%4,np.arange(80)%7,np.arange(80)%3]
        m=np.column_stack([np.eye(int(v.max())+1)[v] for v in groups]);res,_,_=absorb(a,groups,compute_rank=False)
        np.testing.assert_allclose(res,a-m@np.linalg.lstsq(m,a,rcond=None)[0],atol=1e-9)

    def test_contrast_uses_cross_covariance_and_unsupported_is_not_null(self):
        b=np.array([.01,.03,.07,.04]);v=np.eye(4)*.001;v[0,3]=v[3,0]=.0003
        w=np.array([-.25,-.75,0,1]);r=contrast(b,v,w)
        self.assertAlmostEqual(r['estimate_pp'],1.5)
        self.assertAlmostEqual(r['standard_error_pp'],100*np.sqrt(w@v@w))
        self.assertNotAlmostEqual(r['standard_error_pp'],100*np.sqrt(np.sum(w*w*np.diag(v))))
        self.assertFalse(contrast(b,v,w,False)['supported'])
        self.assertEqual(holm([.04,.01]),[.04,.02]);self.assertEqual(holm([None,.01]),[1.,.02])

    def test_rank_deficient_targets_are_not_rescued(self):
        rng=np.random.default_rng(3);n=90;x=rng.normal(size=n);a=np.column_stack([np.arange(n),np.arange(n)+100,np.full(n,-1)])
        info,fit=fit_ols(self.c,np.column_stack([x,x]),rng.normal(size=(n,1)),[np.zeros(n,int)],a,['x','same'],['x'])
        self.assertIsNone(fit);self.assertEqual(info['status'],'COLLINEAR_NOT_ESTIMATED')

    def test_conditional_first_stage_reduces_to_scalar_robust_F(self):
        rng=np.random.default_rng(93);z=rng.normal(size=(1000,1));d=.5*z+rng.normal(size=(1000,1));z-=z.mean();d-=d.mean()
        slopes,h,_=conditional_scores(d,z);pi=float((z.T@d)[0,0]/(z.T@z)[0,0]);res=d[:,0]-pi*z[:,0]
        conventional=pi**2/(np.sum((z[:,0]*res)**2)/float((z.T@z)[0,0])**2)
        self.assertAlmostEqual(slopes[0]**2/float((h.T@h)[0,0]),conventional,places=9)

    def test_conditional_F_detects_near_rank_reduction(self):
        rng=np.random.default_rng(916);n=6000;z=rng.normal(size=(n,2));common=z[:,0]+z[:,1]
        d=np.column_stack([common+rng.normal(size=n),common+.001*z[:,1]+rng.normal(size=n)])
        slope,h,pi=conditional_scores(d,z);fs=slope*slope/np.sum(h*h,axis=0)
        self.assertLess(float(fs.max()),10);self.assertGreater(float(np.var(z@pi,axis=0).min()),1.5)

    def test_iv_matches_direct_exactly_identified_moments(self):
        rng=np.random.default_rng(191);n=900;x=rng.normal(size=(n,2));z=rng.normal(size=(n,2));endo=z@np.array([[.8,.2],[.1,.7]])+rng.normal(size=(n,2))
        y=(endo@np.array([.3,-.2])+x@np.array([.5,.7])+rng.normal(size=n))[:,None];g=np.arange(n)%4
        actors=np.column_stack([np.arange(n),np.arange(n)+n]);dates=np.arange(n)
        info,fit=fit_iv(self.c,x,endo,z,y,[g],actors,dates,['x1','x2'])
        w=np.column_stack([np.eye(4)[g],x]);res=lambda a:a-w@np.linalg.lstsq(w,a,rcond=None)[0]
        dr,zr,yr=res(endo),res(z),res(y);b=np.linalg.solve(zr.T@dr,zr.T@yr)
        h=(zr@np.linalg.inv(zr.T@dr).T)*(yr[:,0]-dr@b[:,0])[:,None]
        np.testing.assert_allclose(fit['coefficients'],b,atol=1e-10)
        np.testing.assert_allclose(fit['covariances'][0],h.T@h,atol=1e-10)
        self.assertEqual(info['status'],'ESTIMATED')

    def test_reduced_forms_survive_unidentified_treatment_system(self):
        rng=np.random.default_rng(24);n=700;x=rng.normal(size=(n,1));z=rng.normal(size=(n,2));v=z[:,0]+rng.normal(size=n)
        endo=np.column_stack([v,v]);y=rng.normal(size=(n,1));actors=np.column_stack([np.arange(n),np.arange(n)+n])
        info,fit=fit_iv(self.c,x,endo,z,y,[np.zeros(n,int)],actors,np.arange(n),['x'])
        self.assertEqual(info['status'],'REDUCED_FORM_ONLY_RANK_DEFICIENCY');self.assertIsNone(fit['coefficients'])
        self.assertEqual(fit['reduced_form'].shape,(2,1));self.assertTrue(np.isfinite(fit['reduced_covariances'][0]).all())

class IntegrationTests(unittest.TestCase):
    def test_complete_pipeline_restart_report_privacy_and_source_corruption(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);project=root/'project';desktop=root/'desktop';desktop.mkdir()
            authority,raw,parent=fixture(project)
            work,report=execute(project,desktop,2,8,authority=authority)
            self.assertEqual(read(work/'report/summary.json')['status'],'COMPLETE')
            self.assertEqual(read(work/'models/joint/summary.json')['status'],'ESTIMATED')
            self.assertEqual(read(work/'secondary_iv/summary.json')['status'],'ESTIMATED')
            with (work/'report/01_joint_model.csv').open() as f:rows=list(csv.DictReader(f))
            focal=[r for r in rows if r['outcome']=='y' and r['term'] in ('ahead_minus_equal','received_x_giver_cost_5')]
            self.assertEqual(len(focal),2);self.assertTrue(all(r['holm_p_family2'] for r in focal))
            data=read(work/'models/joint/summary.json');counts=data['sample']['band_counts'];self.assertEqual(sum(counts),len(raw['y']))
            with zipfile.ZipFile(report) as z:
                self.assertTrue(all('PRIVATE' not in x and not x.endswith('.parquet') for x in z.namelist()))
                manifest=json.loads(z.read('REPORT_MANIFEST.json'))
                import hashlib
                for r in manifest:self.assertEqual(hashlib.sha256(z.read(r['path'])).hexdigest(),r['sha256'])
            before=(work/'models/joint/_DONE.json').stat().st_mtime_ns
            execute(project,desktop,2,8,authority=authority)
            self.assertEqual(before,(work/'models/joint/_DONE.json').stat().st_mtime_ns)
            bad=parent/'months/2024-02/dose.parquet'
            with bad.open('ab') as f:f.write(b'corrupt')
            with self.assertRaisesRegex(RuntimeError,'size|Checksum'):bind_cache(project,work,2,authority)

    def test_position_orientation_weights_and_IV_control_separation(self):
        with tempfile.TemporaryDirectory() as t:
            authority,_,_=fixture(Path(t)/'p',n=800);binding=bind_cache(Path(t)/'p',Path(t)/'w',2,authority)
            c=duckdb.connect();open_data(c,binding);d=load_scope(c,'all_rd')
            _,names,targets,_,_,meta,_=design(d);self.assertIn('opponent_leniency',names)
            info=sample_info(d,'all_rd');w,_=infer_weights(targets,'ahead_minus_equal',info,meta)
            self.assertAlmostEqual(w[:2].sum(),-1);self.assertEqual(w[3],1)
            self.assertTrue(np.all(d['board_cp'][d['band']==3]>=300))
            from iv import augment
            aug,_=augment(c,binding,Path(t)/'p',Path(t)/'w',d);x,ivnames,endo,z,ivtargets,_,_=iv_design(aug)
            self.assertNotIn('opponent_leniency',ivnames);self.assertNotIn('adjusted_7d',ivnames)
            self.assertEqual(endo.shape[1],6);self.assertEqual(z.shape[1],6);self.assertEqual(len(ivtargets),6)
            np.testing.assert_allclose(z[:,:4].sum(axis=1),d['adjusted_7d']/.059411690344000595);c.close()

    def test_bad_cohort_is_rejected_without_filtering(self):
        with tempfile.TemporaryDirectory() as t:
            authority,_,_=fixture(Path(t)/'p',n=400);binding=bind_cache(Path(t)/'p',Path(t)/'w',2,authority)
            c=duckdb.connect();binding['expected']=dict(binding['expected'],expected_grants=1)
            with self.assertRaisesRegex(RuntimeError,'reconciliation'):open_data(c,binding)
            c.close()

if __name__=='__main__':unittest.main()
