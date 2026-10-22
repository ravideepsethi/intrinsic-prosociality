import unittest, tempfile, sys, json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from primary_common import *
import primary_inputs as pi
import primary_models as pm
from types import SimpleNamespace

def fixture(folder,n=6000):
    rng=np.random.default_rng(471);i=rng.integers(1,151,n);j=rng.integers(201,351,n)
    z=rng.uniform(-.15,.15,n);received=rng.random(n)<(.35+1.2*z)
    d=dict(row_id=np.arange(n),game_id=np.array([f'g{k:07d}' for k in range(n)]),recipient_id=i,opponent_id=j,
           archive_start_ms=(1700000000000+rng.integers(0,45*DAY,n)),month_code=rng.integers(0,2,n),
           tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n),recipient_rating=rng.normal(1700,100,n),opponent_rating=rng.normal(1700,100,n),
           received=received,y=rng.random(n)<(.2+.15*received),reached=np.ones(n,bool),
           # Deliberately set ALL historical support and selection flags false.
           n_7d=np.zeros(n),counterparts_7d=np.zeros(n),adjusted_7d=np.full(n,np.nan),expected_7d=np.full(n,np.nan),
           spaced90=np.zeros(n,bool),spaced30=np.zeros(n,bool),first_recipient=np.zeros(n,bool),
           pre_games_30d=rng.integers(1,100,n),environment_supported=np.ones(n,bool))
    d['anchor_ms']=d['archive_start_ms']+60000
    for days in (30,90):
        fair=rng.integers(0,40,n);d[f'fair_{days}']=fair;d[f'kind_{days}']=rng.binomial(fair,.1)
        for x in ('disconnect','receipt','claim'):d[f'{x}_{days}']=rng.integers(0,10,n)
    for x in frozen.r.ENV:d[x]=rng.normal(size=n)
    scores=dict(row_id=np.arange(n),n_A=rng.integers(5,50,n),counterparts_A=rng.integers(1,5,n),expected_A=rng.uniform(.1,.3,n),adjusted_A=z)
    p=folder/'source.parquet';s=folder/'scores.parquet';pq.write_table(pa.table(d),p);pq.write_table(pa.table(scores),s)
    return p,s,d,scores

class Rules(unittest.TestCase):
    def test_newly_supported_earlier_exposure_displaces_old_later_one(self):
        person=np.array([1,1,1,2]);start=np.array([0,20,92,0])*DAY;anchor=start+DAY
        old=pi.spacing_flags(person,start,anchor,np.array([False,True,True,True]))['spaced90']
        new=pi.spacing_flags(person,start,anchor,np.ones(4,bool))['spaced90']
        self.assertEqual(old.tolist(),[False,True,False,True]);self.assertEqual(new.tolist(),[True,False,True,True])

    def test_spacing_strict_boundary_and_admin_cut_order(self):
        person=np.ones(3,int);start=np.array([0,91,92])*DAY;anchor=start+DAY
        chosen=pi.spacing_flags(person,start,anchor,np.ones(3,bool))['spaced90']
        self.assertEqual(chosen.tolist(),[True,False,True])
        # A selected exposure failing the later observation cut still sets cooldown.
        self.assertEqual((chosen&np.array([False,True,True])).tolist(),[False,False,True])

    def test_pair_exclusion_all_times_and_no_prior_requirement(self):
        h=dict(j=np.ones(7,np.int64)*200,i=np.array([1,1,2,3,4,5,6]),t=np.arange(7,dtype=np.int64)+1700000000000,
               y=np.array([1,1,0,1,0,1,0]),cell=np.ones(7,np.int64)*250)
        q=dict(row_id=np.array([0]),opponent_id=np.array([200]),recipient_id=np.array([1]),month_code=np.array([0]),
               archive_start_ms=np.array([1699000000000]),anchor_ms=np.array([1699000001000]),frame=np.array([0]))
        ref=np.full((1,24,4,4,500),.2)
        score,_=inputs.alltime(h,q,ref)
        self.assertEqual(score['n'][0],5);self.assertAlmostEqual(score['adjusted'][0],.2)
        A,B,C,sel,diag,_=frozen.r9_scores.score(h,q,ref)
        self.assertEqual(B['n'][0],0);self.assertEqual(C['n'][0],5);self.assertEqual(A['n'][0],5)
        frozen.r9_scores.oracle(h,q,ref,A,B,C,sel,diag)

    def test_primary_estimation_ignores_legacy_support_and_spacing(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,d,_=fixture(root)
            job=pm.r9bjob(p,s,root,'test','primary','X0_ENV_indicator',ols=True)
            ids,use=models.select(job);self.assertEqual(use.sum(),6000)
            got=iv.iv_fit(p,s,frozen.r.X0+frozen.r.ENV+['env_supported'])
            direct=models.estimate(job)['estimates'];fs=next(x for x in direct if x.get('estimator')=='first_stage')
            ivrow=next(x for x in direct if x.get('estimator')=='2SLS')
            self.assertAlmostEqual(got['first_stage'],fs['coefficient_pp'],places=8)
            self.assertAlmostEqual(got['iv'],ivrow['coefficient_pp'],places=8)
            self.assertAlmostEqual(got['iv_se'],ivrow['standard_error_pp'],places=8)
            # An independent dense dummy projection checks coefficients, not just two wrappers.
            v,groups,actors,meta,names,_=models.buffer(job)
            allnames=names+meta['controls'];take=[allnames.index(x) for x in ('z_A','received','y')]
            controls=v[:,len(names):];dummies=[]
            for g in groups:
                codes=np.unique(g,return_inverse=True)[1];dummies.append(np.eye(codes.max()+1)[codes])
            X=np.column_stack([controls,*dummies]);T=v[:,take];res=T-X@np.linalg.lstsq(X,T,rcond=1e-12)[0]
            expected=100*(res[:,0]@res[:,2])/(res[:,0]@res[:,1])
            self.assertAlmostEqual(got['iv'],expected,places=7)

    def test_score_row_misalignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,d,score=fixture(root,2400);score['row_id']=score['row_id'][::-1];pq.write_table(pa.table(score),s)
            with self.assertRaises(RuntimeError):models.select(pm.r9bjob(p,s,root,'x','x','X0'))

    def test_cache_tampering_and_changed_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'state.json';save(p,{'n':5});seal(p,'one');self.assertTrue(cached(p,'one'))
            with self.assertRaises(RuntimeError):cached(p,'two')
            save(p,{'n':6})
            with self.assertRaises(RuntimeError):pi.verified_receipt(p)

    def test_timing_controls_use_each_own_history(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,d,score=fixture(root)
            for name in ('B','C'):
                for field in ('n','counterparts','expected','adjusted'):score[field+'_'+name]=score[field+'_A'].copy()
            score['n_B'][:10]=0;score['adjusted_B'][:10]=np.nan;pq.write_table(pa.table(score),s)
            a=SimpleNamespace(memory_gb=11)
            source,sc=pm.subset(a,root,'test',p,s,'before','s.n_B>=5 AND isfinite(s.adjusted_B)')
            self.assertEqual(pq.ParquetFile(source).metadata.num_rows,5990)
            job=pm.r9job(source,sc,root,'test','before_B','X0',variant='B')
            _,_,_,meta,_,_=frozen.r9_models.build_buffer(job)
            self.assertEqual(meta['history_controls_donor_set'],'B');self.assertEqual(meta['n'],5990)

    def test_joint_trait_balance_runs_on_new_rows(self):
        from primary_balance import balance
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,_,_=fixture(root);balance(p,s,root,'test')
            import csv
            with (root/'report/balance_contrast.csv').open() as handle:rows=list(csv.DictReader(handle))
            joint=[x for x in rows if x['row_type']=='joint_test'];self.assertEqual(len(joint),4)
            self.assertEqual({int(x['exposures']) for x in joint},{6000})
            self.assertEqual({int(x['df']) for x in joint},{7,15})

    def test_wider_source_replaces_old_spacing_and_reuses_features(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,d,score=fixture(root,2500)
            d.update(complete90=np.ones(2500,bool),history_window_complete=np.ones(2500,bool))
            # First flags represent first observed exposure, independently of support.
            d['first_recipient'][0]=True
            pq.write_table(pa.table(d),p)
            b=dict(raw=str(p),all_scores=[str(s)],known_features=[str(p)],bound={})
            a=SimpleNamespace(memory_gb=11)
            ensure=pi.ensure_unique
            def small(c,view,expected=None):return ensure(c,view,2500 if view=='raw' else expected)
            person=d['recipient_id'];start=d['archive_start_ms'];anchor=d['anchor_ms'];order=np.lexsort((d['row_id'],start,person))
            expected=int(pi.spacing_flags(person[order],start[order],anchor[order],np.ones(2500,bool))['spaced90'].sum())
            with patch.object(pi,'ensure_unique',side_effect=small),patch.object(pi,'EXPECTED_N',expected):
                selected=pi.build_selection(a,root,'test',b)
            clean,known=pi.rebuild_wider_features(a,root,'test',b,selected)
            out=pq.read_table(clean).to_pydict()
            self.assertEqual(sum(out['spaced90']),expected)
            self.assertEqual(sum(out['first_recipient']),1)
            self.assertEqual(out['y'],list(d['y']))
            self.assertEqual(len(out['row_id']),2500)
            # Re-running must reuse byte-identical cached files.
            before=sha(clean);again,_=pi.rebuild_wider_features(a,root,'test',b,selected);self.assertEqual(before,sha(again))

    def test_diagnostic_plan_and_actual_primary_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,_,_=fixture(root,2400)
            with patch.object(pm,'subset',return_value=(p,s)):
                jobs=pm.diagnostic_plan(SimpleNamespace(memory_gb=11),root,'test',dict(primary=str(p)),(str(p),str(s)),str(s),str(p),str(p),str(p))
            self.assertTrue(len(jobs)>100)
            frozen.runtime.capacity(jobs,10,11)
            frozen.runtime.capacity(jobs,10,10.5)
            for job in jobs:
                if job['name'].startswith(('hour_','subgroup_','compliers','donor_','act_result')):
                    self.assertEqual(job['candidate'],'all')
                self.assertLessEqual(job['memory_gb'],11)
            self.assertEqual(next(j for j in jobs if j['name']=='spacing30__X0')['candidate'],'spaced30')
            self.assertEqual(next(j for j in jobs if j['name']=='first_common_controls__X0')['candidate'],'first')

if __name__=='__main__':unittest.main()
