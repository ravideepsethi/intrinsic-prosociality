import tempfile,unittest,sys,json
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc
import duckdb
from types import SimpleNamespace
from unittest.mock import patch
import receipt_companions as r
from receipt_numerics import sparse_absorb,fit,conditional_censor_mask
from engagement import Targets,scan_windows,activity_join_sql
from result_common import checkpoint,save,sha,DAY

def full_dummy(groups):
    return np.column_stack([np.eye(len(np.unique(g)))[np.unique(g,return_inverse=True)[1]] for g in groups])

class ProjectionTests(unittest.TestCase):
    def setUp(self):self.rng=np.random.default_rng(153)
    def test_four_FE_match_explicit_weighted_dummy_projection(self):
        n=500;groups=[self.rng.integers(k,size=n) for k in (8,3,19,22)]
        w=np.exp(self.rng.normal(size=n));x=self.rng.normal(size=(n,5));D=full_dummy(groups)
        expected=x-D@np.linalg.lstsq(D*np.sqrt(w[:,None]),x*np.sqrt(w[:,None]),rcond=None)[0]
        actual,_,error=sparse_absorb(x,w,groups)
        np.testing.assert_allclose(actual,expected,atol=3e-9,rtol=1e-9)
        self.assertLessEqual(error,1e-10)
    def test_disconnected_and_redundant_fixed_effects(self):
        n=400;g=np.repeat(np.arange(20),20);h=g//5
        groups=[g,h,g.copy(),h.copy()];w=self.rng.uniform(.1,1,n);x=self.rng.normal(size=(n,3))
        actual,_,_=sparse_absorb(x,w,groups)
        expected=x.copy()
        for k in np.unique(g):expected[g==k]-=np.average(x[g==k],weights=w[g==k],axis=0)
        np.testing.assert_allclose(actual,expected,atol=1e-9)
    def test_chooser_and_two_way_variance_against_full_dummy_WLS(self):
        n=600;g=[self.rng.integers(k,size=n) for k in (7,4,13,16)]
        w=self.rng.uniform(.1,2,n);t=self.rng.integers(2,size=n).astype(float)
        x=self.rng.normal(size=(n,2));y=.12*t+x@np.array([.3,-.7])+self.rng.normal(size=n)
        cluster=self.rng.integers(40,size=n);D=full_dummy(g)
        A=np.column_stack([t,x,D]);sw=np.sqrt(w)
        beta=np.linalg.lstsq(A*sw[:,None],y*sw,rcond=None)[0]
        bread=np.linalg.pinv(A.T@(w[:,None]*A),rcond=1e-12)
        influence=w*(y-A@beta)*(A@bread[0])
        def meat(c):
            _,ix=np.unique(c,return_inverse=True);s=np.bincount(ix,weights=influence);return s@s
        _,inter=np.unique(np.column_stack([cluster,g[2]]),axis=0,return_inverse=True)
        v=meat(cluster)+meat(g[2])-meat(inter)
        self.assertGreater(v,0)
        got=fit(y,t,x,['a','b'],w,g,cluster,np.arange(n),r.common,r.core,True,g[2])
        self.assertAlmostEqual(got['estimate'],100*beta[0],places=7)
        self.assertAlmostEqual(got['se'],100*np.sqrt(v),places=7)
    def test_same_model_as_original_two_FE_producer(self):
        import estimation
        n=400;g=[self.rng.integers(k,size=n) for k in (8,4)]
        w=self.rng.uniform(.1,1,n);t=self.rng.integers(2,size=n);x=self.rng.normal(size=(n,2))
        y=self.rng.integers(2,size=n);cluster=self.rng.integers(50,size=n)
        old=estimation.fit(y,t,x,['a','b'],w,g,cluster,np.arange(n))
        new=fit(y,t,x,['a','b'],w,g,cluster,np.arange(n),r.common,r.core)
        for k in ('estimate','se','ci_low','ci_high'):self.assertAlmostEqual(old[k],new[k],places=10)
    def test_conditional_censor_ties_and_complete_window(self):
        a=np.full(7,1000);delta=np.full(7,100.)
        nxt=np.array([np.nan,1100,1099,1101,1000+91*DAY,np.nan,np.nan])
        reached=np.array([1,1,1,1,1,0,1],bool);complete=np.array([1,1,1,1,1,1,0],bool)
        np.testing.assert_array_equal(conditional_censor_mask(reached,a,delta,nxt,complete),[1,1,0,1,1,0,0])

    def test_conditional_censor_nullable_integer_through_actual_arrow_loader(self):
        anchor=np.full(6,1700000000000,dtype=np.int64);delta=np.full(6,1000)
        values=[None,0,int(anchor[0]+999),int(anchor[0]+1000),int(anchor[0]+1001),None]
        reached=np.array([1,1,1,1,1,0],bool)
        integer=pa.table({'recipient_next_disconnection_utc_ms':pa.array(values,type=pa.int64())})
        floating=pa.table({'recipient_next_disconnection_utc_ms':pa.array(values,type=pa.float64())})
        for table in (integer,floating):
            nxt=r.core.arrow_column_numpy(table,'recipient_next_disconnection_utc_ms',np,pa)
            got=conditional_censor_mask(reached,anchor,delta,nxt,np.ones(6,bool))
            np.testing.assert_array_equal(got,[1,1,0,1,1,0])

    def test_conditional_censor_rejects_broken_present_chronology(self):
        with self.assertRaisesRegex(RuntimeError,'Next disconnection'):
            conditional_censor_mask([True],[1000],[100],[999],[True])
        with self.assertRaisesRegex(RuntimeError,'first-choice time'):
            conditional_censor_mask([True],[1000],[-1],[-1],[True])
        with self.assertRaisesRegex(RuntimeError,'first-choice time'):
            conditional_censor_mask([True],[1000],[91*DAY],[-1],[True])

class ActivityTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_scan_matches_brute_force_all_roles_and_time_boundaries(self):
        anchor=1700000000000
        ids=np.array([9,2,150]);anchors=np.array([anchor,anchor+20,anchor+50])
        targets=Targets(ids,anchors)
        times=np.array([anchor,anchor+1,anchor+600000,anchor+1800000,anchor+3600000,
                        anchor+30*DAY,anchor+30*DAY+1,anchor+22,anchor+52,0,anchor+90])
        white=np.array([9,9,9,9,9,9,9,2,150,9,2]);black=np.array([1,2,1,1,1,1,1,9,9,2,2])
        path=self.p/'events.parquet';pq.write_table(pa.table({'utc_ms':times,'white_id':white,'black_id':black}),path,row_group_size=3)
        fake=type('History',(),{'integers':staticmethod(lambda x:pc.fill_null(pc.cast(x,pa.int64()),-1).to_numpy(zero_copy_only=False))})
        scan_windows(path,targets,self.p/'out.npz',fake,batch_size=2)
        counts=[];first=[]
        for uid,a in zip(ids,anchors):
            ts=times[((white==uid)|(black==uid))&(white!=black)&(times>a)&(times<=a+30*DAY)]
            counts.append(len(ts));first.append(int(ts.min()) if len(ts) else np.iinfo(np.int64).max)
        with np.load(self.p/'out.npz') as z:
            np.testing.assert_array_equal(z['counts'],counts);np.testing.assert_array_equal(z['first'],first)
    def test_sparse_id_lookup_and_no_events(self):
        t=Targets([100_000_000,2],[1000,1000]);self.assertIsNone(t.dense)
        np.testing.assert_array_equal(t.lookup(np.array([-1,2,100_000_001,100_000_000])),[-1,1,-1,0])
    def test_activity_reuse_requires_account_game_and_anchor_match(self):
        now=pa.table({'cohort_row_id':[0,1,2],'recipient_user_id':[10,20,30],
                      'exposure_game_id':['a','b-new','c'],'exposure_anchor_utc_ms':[1000,2000,3001]})
        old=pa.table({'recipient_user_id':[10,20,30],'exposure_game_id':['a','b','c'],
                      'exposure_anchor_utc_ms':[1000,2000,3000],'games_within_30d':[4,8,12],
                      'first_next_game_utc_ms':[1001,2001,3002]})
        pq.write_table(now,self.p/'now.parquet');pq.write_table(old,self.p/'old.parquet')
        c=duckdb.connect();c.register('selected_ids',pa.table({'cohort_row_id':[0,1,2]}))
        result=c.execute(activity_join_sql(self.p/'now.parquet',self.p/'old.parquet',r.util.parquet)).fetchall();c.close()
        self.assertEqual([x[3] for x in result],[4,None,None])
    def test_checkpoint_reuse_and_corruption_detection(self):
        calls=[]
        def build(p):calls.append(1);save(p/'result.json',{'x':1});return {'count':1}
        loc,_=checkpoint(self.p,'test','one',build)
        checkpoint(self.p,'test','one',build);self.assertEqual(len(calls),1)
        with self.assertRaises(RuntimeError):checkpoint(self.p,'test','two',build)
        (loc/'result.json').write_text('{}')
        with self.assertRaises(RuntimeError):checkpoint(self.p,'test','one',build)

class PipelineTests(unittest.TestCase):
    def test_six_model_job_reuses_checkpoint_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);project=root/'project';out=root/'report';rng=np.random.default_rng(614);n=800
            parents=r.load(r.ROOT/'authority/PARENTS.json');rid=parents['receipt_run_id']
            parent=project/'derived/replication/mating_material_receipt_v100_PRIVATE'/rid[:16]
            source=parent/'PRIVATE/recipient/recipient_private.parquet';source.parent.mkdir(parents=True)
            D=rng.integers(2,size=n).astype(bool);y=(rng.random(n)<(.1+.1*D)).astype(float)
            anchor=1704067200000+rng.integers(15,size=n)*3600000+1000
            delta=rng.integers(1,20,size=n).astype(float)*3600000
            nxt=pa.array([int(anchor[j]+delta[j]-1) if j%3==0 else None for j in range(n)],type=pa.int64())
            values=dict(cohort_row_id=np.arange(n),recipient_user_id=np.arange(n)+1000,
                exposure_chooser_user_id=rng.integers(100,size=n),received_mercy=D,
                exposure_claimed_win=~D,arm_eligible=np.ones(n,bool),exposure_no_mating_draw=np.zeros(n,bool),
                exposure_chooser_loss=np.zeros(n,bool),first_ever_pair=np.ones(n,bool),
                a1_90d_followup_eligible=np.ones(n,bool),exposure_cell_code=np.zeros(n,np.int64),
                exposure_month_code=np.zeros(n,np.int64),reached_fair_chooser_within_90d=np.ones(n,bool),
                first_subsequent_kind_draw=y,first_subsequent_delta_ms=delta,
                recipient_next_disconnection_utc_ms=nxt,exposure_anchor_utc_ms=anchor)
            values.update({name:rng.normal(size=n) for name in r.core.EXPOSURE_CONTROLS})
            pq.write_table(pa.table(values),source)
            d,support=r.load_receipt(source);ix=np.arange(n);X,names=r.core.model_controls(d,ix,state_conditioned=False)
            ref=fit(y,D,X,names,support['weights'],[d['exposure_cell_code'],d['exposure_month_code']],
                    d['exposure_chooser_user_id'],ix,r.common,r.core)
            model=parent/'report/models/conditional.json';save(model,ref)
            sample=dict(all_fresh_exposures=n,common_support=n,common_support_complete90=n,complete90_reached=n)
            result=parent/'report/RESULTS.json';save(result,{'summary':{'sample':sample}})
            receipts=[{'path':str(p.relative_to(parent)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in (source,model)]
            save(parent/'_SUCCESS.json',dict(status='RECEIPT_COMPLETE_MORE_FAMILIES_PENDING',run_id=rid,files=receipts))
            parents=dict(parents,receipt_result_sha256=sha(result));real_load=r.load
            def patched_load(p):
                if Path(p)==r.ROOT/'authority/PARENTS.json':return parents
                if Path(p)==r.ROOT/'authority/receipt_RESULTS.json':return {'summary':{'sample':sample}}
                return real_load(p)
            calls=[]
            def activity(folder,*a):
                calls.append(1);counts=(rng.random(n)<(.85+.03*D)).astype(np.int64)*3
                first=np.where(counts>0,anchor+rng.integers(1,4000,size=n)*1000,np.iinfo(np.int64).max)
                pq.write_table(pa.table(dict(cohort_row_id=ix,games_within_30d=counts,
                      first_next_game_utc_ms=first,exposure_anchor_utc_ms=anchor)),folder/'activity_PRIVATE.parquet')
                return {'rows':n,'fixture':True}
            original=sha(source)
            a=SimpleNamespace(project=project,report=out,workers=1,memory_gb=2)
            with patch.object(r,'load',patched_load),patch.object(r,'SUPPORT_N',n),patch.object(r,'COMPLETE90_N',n),patch.object(r,'CONDITIONAL_N',n),patch.object(r,'build_activity',activity):
                r.run(a);r.run(a)
            self.assertEqual(len(calls),1)
            with (out/'RECEIPT_COMPANIONS.csv').open() as handle:
                rows=list(__import__('csv').DictReader(handle))
            self.assertEqual(len(rows),6);self.assertTrue(all(float(z['se'])>0 for z in rows))
            censored=[z for z in rows if z['specification']=='conditional_censored_at_next_competitive_disconnection'][0]
            self.assertEqual(int(censored['rows']),n-int((np.arange(n)%3==0).sum()))
            self.assertEqual(sum(z['units']=='log points' for z in rows),1)
            self.assertEqual(sha(source),original)
            self.assertEqual(real_load(out/'STATUS.json')['status'],'COMPLETE')

if __name__=='__main__':unittest.main()
