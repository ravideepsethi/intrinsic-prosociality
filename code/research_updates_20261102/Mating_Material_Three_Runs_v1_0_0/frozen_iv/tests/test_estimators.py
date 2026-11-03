import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
import model_kernel as m,fast_models as old,supp_core as supp
from types import SimpleNamespace

def fixture(root,n=3200):
    rng=np.random.default_rng(812);person=rng.integers(1,240,n);opponent=rng.integers(241,480,n)
    z=rng.uniform(.001,.2,n);d=rng.random(n)<(.15+2*z)
    reached=rng.random(n)<.8;y=(rng.random(n)<(.07+.06*d)) & reached
    start=int(c.phase_inputs.core.STARTS[6])+rng.integers(0,60,n)*DAY+rng.integers(0,24,n)*3600000
    fair=rng.integers(0,10,n);kind=np.minimum(fair,rng.binomial(2,.05,n));sup=rng.random(n)>.1
    data=dict(row_id=np.arange(n),game_id=np.array(['g'+str(k).zfill(7) for k in range(n)]),recipient_id=person,opponent_id=opponent,
      archive_start_ms=start,anchor_ms=start+30000,month_code=np.full(n,6),tc_base_s=np.full(n,300),tc_inc_s=np.zeros(n),
      recipient_rating=rng.integers(1300,1600,n),opponent_rating=rng.integers(1300,1600,n),received=d,y=y,reached=reached,
      fair_90=fair,kind_90=kind,disconnect_90=rng.integers(0,10,n),receipt_90=rng.binomial(2,.04,n),claim_90=rng.integers(0,10,n),pre_games_90d=rng.integers(10,300,n),
      environment_supported=sup,log_opponent_games90=np.where(sup,rng.normal(4,.5,n),np.nan),
      opponent_observed_disconnect_rate=np.where(sup,rng.uniform(.01,.05,n),np.nan),opponent_observed_chooser_rate=np.where(sup,rng.uniform(.01,.05,n),np.nan))
    data.update(outcome_gid=np.where(reached,['f'+str(k).zfill(7) for k in range(n)],''),
                outcome_start=np.where(reached,start+DAY,0),outcome_t=np.where(reached,start+DAY+30000,0))
    score=dict(row_id=np.arange(n),n_A=rng.integers(5,100,n),counterparts_A=rng.integers(2,5,n),expected_A=rng.uniform(.01,.04,n),adjusted_A=z)
    src=root/'source.parquet';sc=root/'scores.parquet';pq.write_table(pa.table(data),src);pq.write_table(pa.table(score),sc);return src,sc

class EstimatorTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.src,self.sc=fixture(self.root)
    def tearDown(self):self.temp.cleanup()
    def job(self,where):return m.job_for(self.root,'numeric','test',self.src,self.sc,**where)
    def test_original_buffer_and_dense_fwl_oracle(self):
        root=self.root/'one';root.mkdir();job=self.job({});a,g,actors,targets,meta,e=m.build_buffer(job,root)
        rr=self.root/'two';rr.mkdir();b,gg,aa,tt,mm,ee=old.build_buffer(job,rr)
        np.testing.assert_array_equal(a,b)
        for x,y in zip(g,gg):np.testing.assert_array_equal(x,y)
        width=len(targets);x=np.asarray(a[:,width:]);effects=[]
        for group in g:
            unique,code=np.unique(group,return_inverse=True);effects.append(np.eye(len(unique))[code])
        X=np.column_stack(effects+[x]);wanted=a[:,:width]-X@np.linalg.lstsq(X,a[:,:width],rcond=1e-12)[0]
        actual,rank,diag=m.project(a.copy(order='F'),g,width,root)
        np.testing.assert_allclose(actual,wanted,atol=2e-7,rtol=2e-7)
    def test_covariance_matches_pairwise_dependency_oracle(self):
        rng=np.random.default_rng(61);n=30;u=rng.normal(size=(n,3));r=rng.integers(0,8,n);o=rng.integers(8,16,n);d=rng.integers(0,6,n)
        # Ensure shared roles and repeated unordered pairs are represented.
        o[4]=r[1];r[6]=o[1];r[10],o[10]=o[0],r[0]
        o[o==r]+=20
        dep=(r[:,None]==r)|(r[:,None]==o)|(o[:,None]==r)|(o[:,None]==o)|(d[:,None]==d)
        wanted=u.T@dep.astype(float)@u
        p=self.root/'infl.parquet';pq.write_table(pa.table(dict(row_id=np.arange(n),recipient_id=r,opponent_id=o,date=d,a=u[:,0],b=u[:,1],c=u[:,2])),p)
        from fast_covariance import covariance
        got=covariance(p,['a','b','c'],self.root/'cov',memory=1.)
        np.testing.assert_allclose(got,wanted,atol=1e-11,rtol=1e-11)
    def test_recipient_weights_and_weighted_projection_dense(self):
        design=self.root/'design';supp.prepare_design(self.src,self.sc,design,validate_real=False)
        info=read(design/'design.json');v=np.memmap(design/'base.dat',dtype=float,mode='r',shape=(info['n'],info['p']),order='F')
        w=np.load(design/'weights.npy');person=np.load(design/'recipient_id.npy')
        for p in np.unique(person):self.assertAlmostEqual(w[person==p].sum(),1.,places=12)
        groups=[np.load(design/f'group{k}.npy') for k in range(3)];effects=[]
        for g in groups:
            _,codes=np.unique(g,return_inverse=True);effects.append(np.eye(codes.max()+1)[codes])
        X=np.column_stack(effects+[v[:,6:]]);sw=np.sqrt(w);coef=np.linalg.lstsq(X*sw[:,None],v[:,:6]*sw[:,None],rcond=1e-12)[0]
        wanted=v[:,:6]-X@coef
        got=supp.project_design(design,self.root/'weighted',weighted=True)
        np.testing.assert_allclose(got,wanted,atol=3e-7,rtol=3e-7)
        terms=supp.compute_terms(got,w,include_s5=False,include_ols=False)
        iv=next(t for t in terms if t['term']=='iv_y')['beta']
        expected=np.dot(w*wanted[:,0],wanted[:,2])/np.dot(w*wanted[:,0],wanted[:,1])
        self.assertAlmostEqual(iv,expected,places=9)
    def test_extra_effect_options_append_without_changing_controls(self):
        folder=self.root/'fe';folder.mkdir();job=self.job(dict(recipient_fe=True));v,g,actors,_,meta,_=m.build_buffer(job,folder)
        self.assertEqual(len(g),4);np.testing.assert_array_equal(g[-1],actors['recipient_id'])
        self.assertTrue(meta['recipient_fe'])

if __name__=='__main__':unittest.main()
