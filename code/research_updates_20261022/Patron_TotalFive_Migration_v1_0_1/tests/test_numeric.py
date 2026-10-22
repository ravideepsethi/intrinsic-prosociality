import sys, unittest, tempfile, json, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import patron_models as models
from patron_common import *
def dense_kernel(i,j,date):
    return ((i[:,None]==i[None,:])|(i[:,None]==j[None,:])|(j[:,None]==i[None,:])|(j[:,None]==j[None,:])|(date[:,None]==date[None,:])).astype(float)

class NumericTests(unittest.TestCase):
    def test_weighted_and_unweighted_against_dense_wls_and_2sls(self):
        rng=np.random.default_rng(128);n=240;g1=rng.integers(0,7,n);g2=rng.integers(0,4,n)
        x=rng.normal(size=(n,3));z=rng.normal(size=n)+x[:,0]+g1/5
        d=.7*z+.5*x[:,1]+rng.normal(size=n);y=.3*d+.2*x[:,0]+rng.normal(size=n)
        C=np.column_stack([np.eye(7)[g1],np.eye(4)[g2],x]);i=rng.integers(0,25,n);j=(i+rng.integers(1,25,n))%25;date=rng.integers(0,13,n)
        K=dense_kernel(i,j,date);codes=models.covariance_codes(i,j,date)
        for weights in [np.ones(n),rng.choice([1.,1.5,5.,19.],n)]:
            w=weights/weights.mean();root=np.sqrt(w);matrix=np.array(np.column_stack([z,d,y,x]),order='F')
            res,rank,diag=models.partial(matrix,[g1,g2],w,3)
            fits,infs=models.fit_residuals(res,w,codes,['received','patron'],'patron');self.assertEqual(diag['status'],'CONVERGED')
            X=np.column_stack([C,z]);bread=np.linalg.pinv((X*root[:,None]).T@(X*root[:,None]),rcond=1e-12)
            for outcome,outcome_name in [(d,'received'),(y,'patron')]:
                beta=np.linalg.lstsq(X*root[:,None],outcome*root,rcond=1e-12)[0];resid=outcome-X@beta
                influence=(bread@X.T)[-1]*w*resid;var=float(influence@K@influence)
                fit=next(r for r in fits if r['outcome']==outcome_name and r['estimator']!='2SLS')
                self.assertAlmostEqual(fit['coefficient'],beta[-1],places=8)
                self.assertAlmostEqual(fit['variance'],var,places=8)
                np.testing.assert_allclose(infs[outcome_name],influence,atol=2e-9,rtol=2e-8)
            # Dense complete-system IV oracle, including all nuisance regressors.
            Xiv=np.column_stack([C,d]);Z=np.column_stack([C,z]);ZW=Z.T*w
            zwz_inv=np.linalg.pinv(ZW@Z,rcond=1e-12);xz=Xiv.T@(w[:,None]*Z)
            A=np.linalg.pinv(xz@zwz_inv@xz.T,rcond=1e-12)@xz@zwz_inv@ZW
            beta=A@y;influence=A[-1]*(y-Xiv@beta)
            fit=next(r for r in fits if r['estimator']=='2SLS')
            self.assertAlmostEqual(fit['coefficient'],beta[-1],places=8)
            self.assertAlmostEqual(fit['variance'],float(influence@K@influence),places=8)
    def test_covariance_counts_overlap_once(self):
        i=np.array([1,2,1,7,3,2]);j=np.array([2,1,3,8,1,4]);date=np.array([0,0,1,0,1,2]);rng=np.random.default_rng(2);s=rng.normal(size=(6,3))
        actual=models.shared_meat(s,models.covariance_codes(i,j,date),True)
        np.testing.assert_allclose(actual,s.T@dense_kernel(i,j,date)@s,atol=1e-12)
    def test_global_weight_scaling_invariance(self):
        rng=np.random.default_rng(9);n=90;g=np.arange(n)%5;v=np.array(rng.normal(size=(n,5)),order='F');w=rng.uniform(1,19,n)
        a,_,_=models.partial(v.copy(order='F'),[g],w,2);b,_,_=models.partial(v.copy(order='F'),[g],w*37,2)
        np.testing.assert_allclose(a,b,atol=1e-9)
        codes=models.covariance_codes(np.arange(n)%13,100+np.arange(n)%17,np.arange(n)%7)
        fa,_=models.fit_residuals(a,w,codes,['patron']);fb,_=models.fit_residuals(b,w*37,codes,['patron'])
        self.assertAlmostEqual(fa[0]['coefficient'],fb[0]['coefficient'],places=10)
        self.assertAlmostEqual(fa[0]['variance'],fb[0]['variance'],places=10)
    def test_invalid_weights_and_negative_variance_rejected(self):
        v=np.ones((12,2),order='F');w=np.ones(12);w[0]=0
        with self.assertRaisesRegex(RuntimeError,'Invalid weighted'):models.weighted_absorb(v,[np.arange(12)%3],w)
        self.assertFalse(models.infer(.1,-.01,100)['supported'])

def write(p,rows):pq.write_table(pa.Table.from_pylist(rows),p)

def make_fixture(root,n=6000):
    rng=np.random.default_rng(812);root.mkdir();rows=[];scores=[];accounts=[]
    for i in range(40):
        inside=i%10!=1;p=(1. if i%3==0 else .5) if inside else 0.
        observed=inside and (i%3==0 or i%5!=0)
        accounts.append(dict(recipient_id=i+1,in_original_chooser_universe=inside,profile_returned=observed,
            patron=(i%11==0) if observed else None,sampling_fraction=p,query_ms=1790000000000,original_ever_kind=i%3==0,identity_resolved=True))
    for k in range(n):
        i=k%40;fair=int(rng.integers(1,9)) if i%10!=1 else 0
        t=1700000000000+int(rng.integers(0,25))*DAY+int(rng.integers(0,4))*3600000
        z=float(rng.uniform(-.2,.2));d=bool(rng.random()<.3+.5*z)
        rows.append(dict(row_id=k+1,recipient_id=i+1,opponent_id=100+int(rng.integers(0,80)),archive_start_ms=t,
            month_code=4,tc_base_s=300.,tc_inc_s=0.,recipient_rating=float(rng.uniform(1300,1600)),opponent_rating=float(rng.uniform(1300,1600)),
            received=d,y=bool(rng.random()<.05),reached=bool(rng.random()<.6),fair_90=fair,kind_90=int(rng.integers(0,fair+1)),
            disconnect_90=int(rng.integers(0,10)),receipt_90=int(rng.integers(0,3)),claim_90=int(rng.integers(0,5)),pre_games_30d=int(rng.integers(0,100)),
            environment_supported=k%7!=0,log_opponent_games90=float(rng.uniform(0,6)),opponent_observed_disconnect_rate=float(rng.uniform(0,.1)),
            opponent_observed_chooser_rate=float(rng.uniform(0,.1)),first_recipient=k<40 and i%2==0))
        scores.append(dict(row_id=k+1,n_A=20,counterparts_A=15,expected_A=.05,adjusted_A=z,n_B=10,counterparts_B=8,expected_B=.04,adjusted_B=z+.01))
    source=root/'source.parquet';score=root/'scores.parquet';acc=root/'accounts.parquet';write(source,rows);write(score,scores);write(acc,accounts)
    counts={}
    for name,rr in [('S0',rows),('first_reference',[r for r in rows if r['first_recipient']])]:
        people={r['recipient_id'] for r in rr};observed={i for i in people if accounts[i-1]['profile_returned']}
        counts[name]=dict(exposures=len(rr),recipients=len(people),observed_exposures=sum(r['recipient_id'] in observed for r in rr),observed_recipients=len(observed),patron_recipients=sum(bool(accounts[i-1]['patron']) for i in people))
    bound=dict(accounts=str(acc),paths=dict(S0=str(source),S0_scores=str(score),expanded=str(source),expanded_scores=str(score)))
    return bound,counts
