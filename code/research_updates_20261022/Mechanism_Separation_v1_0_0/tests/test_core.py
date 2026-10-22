import itertools,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import numpy as np
import pandas as pd
from scipy.special import expit,logsumexp
from common import payoff,frame,sha,write,DAY
from stats import conditional_kernel,fit_conditional,groups,lpm,lpm_stream,account_intercepts
from design import controls,design,counterfactual
from support import cost_support
from history import summary_task,features_task
from policy import block_null,mde

def fixture(accounts=600,repeats=24,seed=42):
    rng=np.random.default_rng(seed);n=accounts*repeats;ids=np.repeat(np.arange(accounts),repeats)
    months=np.tile(np.array([str(m) for m in pd.period_range('2023-11','2025-10',freq='M')]),accounts)
    if repeats!=24:raise ValueError('Fixture uses 24 months')
    g=rng.integers(-300,301,n);rating=1500+rng.normal(0,200,n)
    rd=np.full(n,45.);opp_rd=rng.uniform(45,150,n)
    _,K,rg,rc=payoff(rating,rating+g,rd,opp_rd);_,Ko,_,_=payoff(rating+g,rating,opp_rd,rd)
    t=pd.to_datetime(months+'-15',utc=True).astype('int64')//1000000
    alpha=rng.normal(-3,.5,accounts);p=expit(alpha[ids]+.22*g/100)
    return pd.DataFrame(dict(game_id=['g'+str(i) for i in range(n)],chooser=ids,opponent=ids+100000,t=t,
        month=months,speed=rng.choice(['blitz','bullet'],n),color=rng.choice(['white','black'],n),
        y=(rng.random(n)<p).astype(np.int8),cp=rng.integers(-100,100,n),ply=rng.integers(11,100,n),
        rating=rating,opp_rating=rating+g,g=g,rd=rd,opp_rd=opp_rd,rg=rg,rc=rc,ki=K/2,kj=Ko/2,
        clock=rng.uniform(5,100,n),opp_clock=rng.uniform(5,100,n),prior_starts=rng.integers(100,1000,n),
        history_days=rng.uniform(365,1500,n),inactivity_days=rng.uniform(.01,2,n),opp_prior_starts=rng.integers(0,1000,n),
        regular=True,tier2=True,state='equal'))

class Core(unittest.TestCase):
    def test_exact_likelihood_and_gradient(self):
        rng=np.random.default_rng(4)
        for n in (3,5,8):
            for k in range(1,n):
                z=rng.normal(0,3,n);y=np.r_[np.ones(k),np.zeros(n-k)]
                sets=list(itertools.combinations(range(n),k));s=np.array([sum(z[list(a)]) for a in sets]);logz=logsumexp(s)
                prob=np.zeros(n)
                for a,w in zip(sets,np.exp(s-logz)):prob[list(a)]+=w
                ll,res=conditional_kernel(z,y,np.array([0]),np.array([n]))
                self.assertAlmostEqual(ll[0],y@z-logz,places=10)
                np.testing.assert_allclose(res,y-prob,atol=1e-10)
    def test_extreme_index_is_stable(self):
        z=np.array([-800.,-400.,400.,800.]);y=np.array([0.,0.,1.,1.])
        ll,r=conditional_kernel(z,y,np.array([0]),np.array([4]));self.assertTrue(np.isfinite(ll).all());self.assertTrue(np.isfinite(r).all())
    def test_conditional_fit_recovers_known_slope(self):
        rng=np.random.default_rng(19);ids=np.repeat(np.arange(2500),4);X=rng.normal(size=(len(ids),1))
        y=rng.binomial(1,expit(-1+rng.normal(size=2500)[ids]+.7*X[:,0]))
        f=fit_conditional(X,y,ids,inference=True)
        self.assertEqual(f['status'],'ESTIMATED');self.assertLess(abs(f['beta'][0]-.7),.09)
        self.assertTrue(f['identified'][0]);self.assertGreater(f['cov'][0,0],0)
    def test_invariant_accounts_drop(self):
        f=fit_conditional(np.arange(12).reshape(-1,1),np.zeros(12),np.repeat([1,2,3],4))
        self.assertEqual(f['status'],'NO_OUTCOME_VARIATION')
    def test_lpm_and_stream_agree(self):
        rng=np.random.default_rng(8);d=pd.DataFrame(dict(chooser=np.repeat(np.arange(80),6),y=rng.integers(0,2,480),x=rng.normal(size=480)))
        a=lpm(d[['x']].to_numpy(),100*d.y.to_numpy(float),d.chooser.to_numpy())
        b,_=lpm_stream(d,lambda x:(x[['x']].to_numpy(),['x']),block_size=31)
        np.testing.assert_allclose(a['beta'],b['beta'],atol=1e-10);np.testing.assert_allclose(a['cov'],b['cov'],rtol=1e-9)
    def test_intercepts_are_explicit_smoothed_baselines(self):
        ids=np.repeat(np.arange(20),10);offset=np.linspace(-1,1,200);y=np.zeros(200);y[::17]=1
        unique,a,base=account_intercepts(offset,y,ids)
        for i in unique:
            m=ids==i;self.assertAlmostEqual(expit(a[i]+offset[m]).mean(),(y[m].sum()+20*base)/(10+20),places=10)
    def test_premium_even_not_constant(self):
        _,k,a,b=payoff(1500,np.array([1400,1500,1600]),45,45)
        self.assertAlmostEqual(k[0],k[2]);self.assertGreater(k[0],k[1]);np.testing.assert_allclose(b-a,k/2)
    def test_color_has_nonzero_premium_change(self):
        d=fixture(4);old=counterfactual(d);new=counterfactual(d,advantage=11.782457)
        self.assertGreater(np.max(abs(new.ki-old.ki)),0)
        np.testing.assert_allclose((new.rc-old.rc)-(new.rg-old.rg),new.ki-old.ki,atol=1e-12)
    def test_floor_sample_never_gets_two_stake_label(self):
        d=fixture();d['g']=0;d['opp_rating']=d.rating;d=counterfactual(d)
        r=cost_support(d);self.assertFalse(r['two_stakes']);self.assertEqual(r['status'],'OPPONENT_RD_BUNDLE_ONLY')
    def test_unknown_cue_rejected(self):
        d=fixture(2);d['patron']=np.nan
        with self.assertRaises(ValueError):design(d,'framing',cue='patron')
    def test_bootstrap_is_reproducible_and_mde_positive(self):
        rng=np.random.default_rng(1);x=rng.normal(size=100)
        a=block_null(x,4,4,reps=2000);b=block_null(x,4,4,reps=2000)
        np.testing.assert_array_equal(a,b);minimum,critical=mde(a);self.assertGreater(minimum,critical)
    def test_history_boundaries_and_focal_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=Path(tmp);frame(pd.DataFrame(dict(user_id=[1,2],speed=['blitz','blitz'])),w/'needed_users.parquet')
            def ts(x):return int(pd.Timestamp(x,tz='UTC').timestamp()*1000)
            dates={'2022-01':['2022-01-01 20:00'], '2023-10':['2023-10-31 20:00'],
                   '2023-11':['2023-11-01 20:00','2023-11-08 20:00','2023-11-15 20:00','2023-11-22 20:00','2023-11-29 20:00']}
            records=[]
            for month,dd in dates.items():
                p=w/(month+'.parquet');events=pd.DataFrame(dict(game_id=[('focal' if t=='2023-11-29 20:00' else t) for t in dd],utc_ms=[ts(t) for t in dd],white_id=1,black_id=2))
                frame(events,p);r=dict(speed='blitz',month=month,path=str(p),rows=len(events),size=p.stat().st_size);records.append(r)
                summary_task((r,str(w),256))
            # Millisecond API/whole-second PGN difference must not admit focal y.
            frame(pd.DataFrame(dict(game_id=['focal'],chooser=[1],opponent=[2],t=[ts('2023-11-29 20:00')+500],speed=['blitz'])),w/'narrow/2023-11.parquet')
            out=features_task(('blitz','2023-11',records,str(w),256));h=pd.read_parquet(out)
            self.assertEqual(len(h),2);self.assertTrue((h.prior_starts==6).all())
            self.assertTrue(h[['week1','week2','week3','week4']].all().all());self.assertTrue((h.inactivity_days==7).all())
            self.assertTrue((h.history_days>365).all())

if __name__=='__main__':unittest.main()
