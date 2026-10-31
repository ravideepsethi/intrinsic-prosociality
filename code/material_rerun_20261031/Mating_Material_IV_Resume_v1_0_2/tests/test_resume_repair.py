"""Production failures reproduced; repaired solvers checked against direct oracles."""
import sys,tempfile,unittest,json,hashlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
import comparisons, resume_guard
from types import SimpleNamespace
import model_kernel as model
import r7_memory as algebra
from fast_two_way import absorb


class RepairTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def file(self,path,data):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.table(data),p);return p

    def test_nested_chronology_cache_and_exact_coverage(self):
        old=self.root/'old';(old/'report').mkdir(parents=True)
        save(old/'report/chronology90.json',dict(rows=4,reused=2,missing=2))
        q=self.file('q.parquet',dict(row_id=[1,2,3,4]))
        h=self.file('old/PRIVATE/chronology_plan90/hits.parquet',dict(row_id=[1,3],eligible_main=[True,False]))
        f=self.file('old/PRIVATE/chronology_merge90/complete/features.parquet',dict(row_id=[2,4],eligible_main=[False,True]))
        with patch.object(comparisons.c,'check_stage',side_effect=lambda path,conf:path):
            parts=comparisons.chronology_parts(old)
        self.assertEqual(parts,[h,f])
        out=self.root/'combined/features.parquet';out.parent.mkdir()
        comparisons.combine_chronology(q,parts,out,1.)
        self.assertEqual(pq.read_table(out).to_pydict(),dict(row_id=[1,2,3,4],eligible_main=[True,False,False,True]))
        # Missing, extra and duplicate IDs must still block.
        for ids in ([2],[2,5],[2,2]):
            bad=self.file('bad.parquet',dict(row_id=ids,eligible_main=[True]*len(ids)))
            with self.assertRaises(RuntimeError):comparisons.combine_chronology(q,[h,bad],out,1.)

    def test_required_chronology_remainder_cannot_be_silently_ignored(self):
        old=self.root/'old';(old/'report').mkdir(parents=True)
        save(old/'report/chronology90.json',dict(rows=4,reused=2,missing=2))
        self.file('old/PRIVATE/chronology_plan90/hits.parquet',dict(row_id=[1,3]))
        with patch.object(comparisons.c,'check_stage',side_effect=lambda p,c: require(p.is_file(),'Missing authenticated part')):
            with self.assertRaisesRegex(RuntimeError,'Missing authenticated part'):comparisons.chronology_parts(old)

    def hard_data(self):
        # Many cells/hours nested in months; only rare crossing observations
        # connect the months. This is the failing last-move-hour design.
        blocks=18;per=240
        a=np.repeat(np.arange(blocks),per)
        b=3*a+np.tile(np.arange(per)%3,blocks)
        a=np.r_[a,np.arange(blocks-1)]
        b=np.r_[b,3*np.arange(1,blocks)]
        rng=np.random.default_rng(144)
        y=rng.normal(size=(len(a),3))
        y[:,0]+=np.sin(a/2)+b/7
        return a.astype('int64'),b.astype('int64'),y

    def oracle(self,y,groups):
        dummy=[]
        for g in groups:
            _,ix=np.unique(g,return_inverse=True);dummy.append(np.eye(ix.max()+1)[ix])
        X=np.column_stack(dummy)
        return y-X@np.linalg.lstsq(X,y,rcond=1e-12)[0]

    def test_slow_hour_case_exceeds_old_limit_new_matches_dense(self):
        a,b,y=self.hard_data();plans=[algebra._plan(g,len(a)) for g in (a,b)]
        old=y[:,0].copy();work=np.empty(len(a))
        for _ in range(1000):
            for p in plans:old-=algebra._group_means(old,p,work)[p[0]]
        tol=1e-10*max(1.,abs(y).max())
        self.assertGreater(max(abs(algebra._group_means(old,p,work)).max() for p in plans),tol)
        got=y.copy();diag,_=absorb(got,plans,2,tol)
        np.testing.assert_allclose(got,self.oracle(y,[a,b]),atol=2e-8,rtol=2e-8)
        self.assertTrue(all(r['orthogonality']<=tol for r in diag))

    def test_disconnected_components_and_identical_factors(self):
        rng=np.random.default_rng(3)
        for a,b in [(np.repeat(np.arange(8),30),np.repeat(np.arange(8),30)),
                    (np.repeat(np.arange(12),40),np.repeat(np.arange(6),80)+np.tile(np.arange(40)%2,12)*6)]:
            y=rng.normal(size=(len(a),3));v=y.copy();plans=[algebra._plan(g,len(a)) for g in (a,b)]
            diag,meta=absorb(v,plans,2,1e-9)
            np.testing.assert_allclose(v,self.oracle(y,[a,b]),atol=1e-8,rtol=1e-8)
            self.assertGreater(meta['components'],1)

    def test_two_way_full_FWL_in_ram_and_disk(self):
        a,b,y=self.hard_data();rng=np.random.default_rng(21)
        controls=np.column_stack([rng.normal(size=len(a)),np.ones(len(a))])
        raw=np.column_stack([y,controls]);dummies=[]
        for g in (a,b):
            _,ix=np.unique(g,return_inverse=True);dummies.append(np.eye(ix.max()+1)[ix])
        X=np.column_stack(dummies+[controls]);want=y-X@np.linalg.lstsq(X,y,rcond=1e-12)[0]
        for disk in (False,True):
            folder=self.root/str(disk);folder.mkdir()
            if disk:
                v=np.memmap(folder/'input.dat',dtype='float64',mode='w+',shape=raw.shape,order='F');v[:]=raw
            else:v=raw.copy(order='F')
            got,_,diag=model.project(v,[a,b],3,folder)
            np.testing.assert_allclose(got,want,atol=3e-8,rtol=3e-8)
            self.assertIn('Schur',diag['solver'])

    def test_primary_reuse_rejects_changed_numbers_and_identity(self):
        original=read(ROOT/'authority/iv_batch_partial/PRIMARY.json')
        result={'estimates':[dict(r) for r in original]}
        resume_guard.verify_primary(result,original)
        for field,value in [('n','1'),('coefficient','2')]:
            changed=json.loads(json.dumps(result));changed['estimates'][0][field]=value
            with self.assertRaises(RuntimeError):resume_guard.verify_primary(changed,original)

    def test_completed_reports_are_checked_without_rerunning_models(self):
        auth=self.root/'authority';auth.mkdir();run=self.root/'run';(run/'report').mkdir(parents=True)
        p=run/'report/SUPPLEMENTS.csv';p.write_text('valid\n')
        save(auth/'REPORT_MANIFEST.json',[dict(path='receipt/SUPPLEMENTS.csv',bytes=p.stat().st_size,sha256=sha(p))])
        before=p.stat().st_mtime_ns
        self.assertEqual(resume_guard.verify_reports(run,auth),1)
        self.assertEqual(before,p.stat().st_mtime_ns)
        p.write_text('wrong\n')
        with self.assertRaises(RuntimeError):resume_guard.verify_reports(run,auth)

    def test_runner_launches_only_unfinished_stages(self):
        import pipeline
        run=self.root/'run';(run/'PRIVATE').mkdir(parents=True);result=self.root/'desktop';result.mkdir()
        initial=read(ROOT/'authority/iv_batch_partial/STATUS.json')['stages']
        save(run/'PRIVATE/STATE.json',initial)
        a=SimpleNamespace(_stage=None,result_dir=result,preflight_only=False,workers=2,memory_gb=6.)
        launched=[]
        def child(argv,**kwargs):
            launched.append(argv[-1]);return SimpleNamespace(stdout=[],wait=lambda:0)
        with patch.object(pipeline,'arguments',return_value=a),patch.object(pipeline,'verify_package'),\
             patch.object(pipeline,'setup',return_value=(run,resume_guard.EXPECTED_CONF)),\
             patch.object(pipeline,'verify_resume'),patch.object(pipeline,'checkpoint'),\
             patch.object(pipeline.shutil,'disk_usage',return_value=SimpleNamespace(free=10**15)),\
             patch.object(pipeline.subprocess,'Popen',side_effect=child):
            self.assertEqual(pipeline.main(),0)
            self.assertEqual(launched,[s for s in pipeline.STAGES if initial[s]['status']!='COMPLETE'])
            launched.clear();self.assertEqual(pipeline.main(),0);self.assertEqual(launched,[])
        final=read(run/'PRIVATE/STATE.json')
        for name in initial:
            if initial[name]['status']=='COMPLETE':self.assertEqual(final[name],initial[name])

if __name__=='__main__':unittest.main()
