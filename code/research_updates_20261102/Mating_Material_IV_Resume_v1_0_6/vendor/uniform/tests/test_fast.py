import sys,tempfile,unittest,contextlib,io
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fast_bootstrap as c
sys.path.insert(0,str(c.FAST_ROOT/'original/tests'))
import test_uniform90 as fixture
import uniform_features as oldf
import uniform_models as oldm
import fast_features as f
import fast_models as m
import fast_covariance as cov
import run_fast as runner
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

class Optimization(unittest.TestCase):
    def setUp(self):
        self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__()
    def tearDown(self):self.silence.__exit__(None,None,None)

    def query(self,root,people,times):
        root.mkdir(parents=True,exist_ok=True)
        keys=oldf.moments(people,times);order=np.argsort(keys,kind='stable')
        for name,v in [('keys',keys[order]),('order',order),('people',np.unique(people))]:np.save(root/(name+'.npy'),v)
        c.save(root/'meta.json',dict(minimum=int(times.min()),maximum=int(times.max())))
        return keys[order],order

    def test_packed_exact_boundaries_duplicates_and_absent_accounts(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);rng=np.random.default_rng(18);D=c.DAY
            people=rng.integers(1,60,1200);times=rng.integers(100,731,1200)*D
            people[:6]=1;times[:6]=100*D
            keys,order=self.query(r/'query',people,times)
            packed=f.prepare_packed(r/'query','test');meta=c.load(packed/'meta.json')
            k=np.load(packed/'packed.npy');ids=np.unique(people)
            t=np.r_[rng.integers(10,731,12000)*D,10*D,100*D,10*D-1,100*D-1]
            w=rng.integers(1,100,len(t));b=rng.integers(100,200,len(t));w[-4:]=1
            delta=np.zeros(len(keys)+1,np.int64);want=delta.copy()
            oldf.accumulate90(t,w,b,keys,ids,want)
            keep=(t>=meta['base'])&(t<times.max())
            f.accumulate_packed(t[keep],w[keep],b[keep],k,ids,delta,meta)
            np.testing.assert_array_equal(delta,want)
            # repeated query timestamps must remain separate rows
            np.testing.assert_array_equal(np.diff(k[:6]),np.zeros(5,np.uint64))

    def test_packing_falls_back_when_integer_range_does_not_fit(self):
        with tempfile.TemporaryDirectory() as td:
            q=Path(td)/'query';self.query(q,np.arange(10),np.arange(10,dtype=np.int64)*((1<<62)//10))
            out=f.prepare_packed(q,'large');self.assertFalse(c.load(out/'meta.json')['supported'])
            self.assertFalse((out/'packed.npy').exists())

    def test_volume_reuses_existing_parts_and_matches_original(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);D=c.DAY;src=fixture.write(r/'source.parquet',dict(row_id=[0,1,2,3],recipient_id=[1,1,2,4],archive_start_ms=np.array([100,101,120,130])*D))
            records=[]
            for k in range(3):
                p=fixture.write(r/f'chron{k}.parquet',dict(utc_ms=np.array([9,10,100,101,119,120])*D,white_id=[1,1,1,1,2,2],black_id=[4,4,4,4,4,4]))
                records.append(dict(path=str(p),signature=c.frozen.r.io.sig(p),rows=6))
            b={'binding':{'source':{'chron':records}}};a=SimpleNamespace(workers=2,memory_gb=11)
            out=oldf.volume(a,r/'run','test',b,src);expected=pq.read_table(out).to_pydict()
            parts=list((r/'run/PRIVATE/volume90/parts').glob('*.npz'))
            snapshots={p:(p.stat().st_mtime_ns,c.sha(p)) for p in parts}
            # Simulate interruption after all per-file receipts, before final merge.
            out.unlink();Path(str(out)+'.ok.json').unlink()
            got=f.volume(a,r/'run','test',b,src)
            self.assertEqual(pq.read_table(got).to_pydict(),expected)
            self.assertTrue(all((p.stat().st_mtime_ns,c.sha(p))==s for p,s in snapshots.items()))
            # Force one unfinished file to use the new lookup path.
            p=parts[0];p.unlink();Path(str(p)+'.ok.json').unlink();got.unlink();Path(str(got)+'.ok.json').unlink()
            got=f.volume(a,r/'run','test',b,src)
            self.assertEqual(pq.read_table(got).to_pydict(),expected)

    def test_covariance_matches_direct_pairwise_and_disk_with_role_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);rng=np.random.default_rng(9);n=90
            i=rng.integers(1,15,n);j=rng.integers(1,15,n);j=np.where(i==j,j+20,j);date=rng.integers(1,8,n)
            s=rng.normal(size=(n,6));s[:n//2,1::2]=0;s[n//2:,::2]=0
            i=np.r_[i,i[:5]];j=np.r_[j,j[:5]];date=np.r_[date,date[:5]];s=np.vstack([s,s[:5]])
            cols=[f'v{k}' for k in range(6)]
            p=fixture.write(r/'input.parquet',dict(recipient_id=i,opponent_id=j,date=date,**{x:s[:,k] for k,x in enumerate(cols)}))
            related=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(date[:,None]==date)
            want=s.T@related@s
            got=cov.covariance(p,cols,r/'fast');disk=cov.covariance(p,cols,r/'disk',.2,buckets=4)
            np.testing.assert_allclose(got,want,atol=1e-10);np.testing.assert_allclose(got,disk,atol=1e-10)
            with patch.object(cov.r7_memory,'shared_meat',side_effect=AssertionError('recomputed')):
                np.testing.assert_array_equal(cov.covariance(p,cols,r/'fast'),got)
            # A regenerated byte-identical transient file may have a new mtime.
            p.touch()
            with patch.object(cov.r7_memory,'shared_meat',side_effect=AssertionError('recomputed')):
                np.testing.assert_array_equal(cov.covariance(p,cols,r/'fast'),got)

    def compare_results(self,left,right):
        self.assertEqual(len(left['estimates']),len(right['estimates']))
        for a,b in zip(left['estimates'],right['estimates']):
            for k in ('n','row_set_sha256','controls','term','units','supported'):self.assertEqual(a[k],b[k])
            for k in ('coefficient','standard_error','ci95_low','ci95_high','p_value','wald_F'):
                if k in a and a[k] is not None:np.testing.assert_allclose(a[k],b[k],rtol=2e-7,atol=2e-9)
        for a,b in zip(left['joint_balance'],right['joint_balance']):
            self.assertEqual(a['supported'],b['supported'])
            if a['supported']:
                self.assertEqual(a['df'],b['df']);np.testing.assert_allclose(a['chi2'],b['chi2'],rtol=2e-7,atol=2e-9)

    def test_full_models_and_balance_agree_with_v100(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,scores=fixture.synthetic(root,4000);oldcov=oldm.covariance
            table=pq.read_table(src)
            for dst,source in [('analysis_entry_uniform90','y'),('recipient_disconnect_main','received'),('active_timeout','reached')]:
                table=table.append_column(dst,table[source])
            pq.write_table(table,src)
            variants=[dict(legacy=True),{},dict(balance=True),dict(outcomes=['analysis_entry_uniform90','recipient_disconnect_main','active_timeout'],iv=False),dict(outcomes=['y','reached'],iv=False,balance=True)]
            for k,options in enumerate(variants):
                old=oldm.job_for(root,'fit',f'old{k}',src,scores);old.update(options)
                new=m.job_for(root,'fit',f'new{k}',src,scores);new.update(options)
                with patch.object(oldm,'covariance',side_effect=lambda p,cols,r,mem:oldcov(p,cols,r,mem,buckets=4)):oldm.fit(old)
                m.fit(new)
                self.compare_results(c.load(Path(old['output'])/'result.json'),c.load(Path(new['output'])/'result.json'))
                with patch.object(m,'build_buffer',side_effect=AssertionError('completed model recomputed')):m.fit(new)

    def test_contrast_matches_v100_and_keeps_cross_sample_covariance(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,scores=fixture.synthetic(root,3500)
            jobs=[]
            for label,legacy in [('left',False),('right',True)]:
                job=m.job_for(root,'contrast',label,src,scores,legacy=legacy);m.fit(job);jobs.append(job)
            oldcov=oldm.covariance
            with patch.object(oldm,'covariance',side_effect=lambda p,cols,r,mem:oldcov(p,cols,r,mem,buckets=4)):
                want=oldm.contrast(root,'contrast',*jobs,'old_contrast',['first_stage','rf_y','iv_y'])
            got=m.contrast(root,'contrast',*jobs,'new_contrast',['first_stage','rf_y','iv_y'])
            for a,b in zip(want,got):
                for k in ('coefficient','standard_error','p_value'):np.testing.assert_allclose(a[k],b[k],rtol=2e-6,atol=2e-9)

    def test_detected_hardware_policy(self):
        policy=c.resources(total_gib=18,cores=12)
        self.assertEqual(policy["memory_budget_gib"],13.5);self.assertEqual(policy["workers"],12)
        with self.assertRaises(RuntimeError):c.resources(12,18,total_gib=18,cores=12)

    def test_stage_routing_installs_optimized_engines(self):
        with patch.dict(sys.modules),patch.dict(c.os.environ):
            runner.install_engines(13.5,12)
            self.assertIs(sys.modules['uniform_features'],f)
            self.assertIs(sys.modules['uniform_models'],m)
            self.assertEqual(sys.modules['uniform_comparisons'].__name__,'fast_comparisons')
            self.assertEqual(c.worker_limit(),12);self.assertEqual(c.memory_budget(),13.5)

    def test_concurrent_scheduler_matches_serial_and_skips_partial_exports(self):
        import fast_scheduler
        with tempfile.TemporaryDirectory() as td,patch.dict(c.os.environ,{'UNIFORM90_MEMORY_GIB':'13.5','UNIFORM90_WORKERS':'8'}):
            root=Path(td);(root/'report').mkdir();src,scores=fixture.synthetic(root)
            jobs=[m.job_for(root,'parallel',name,src,scores,balance=balance) for name,balance in [('a',False),('b',True)]]
            completed=list(fast_scheduler.fits(jobs));self.assertEqual(len(completed),2)
            serial=m.job_for(root,'parallel','serial',src,scores);m.fit(serial)
            self.compare_results(c.load(Path(jobs[0]['output'])/'result.json'),c.load(Path(serial['output'])/'result.json'))
            partial=root/'PRIVATE/models/not_done.partial_example';partial.mkdir()
            (partial/'result.json').write_text('incomplete JSON')
            m.export_models(root)  # must not inspect a concurrently written result
            self.assertTrue((root/'report/model_estimates.csv').exists())

    def test_ram_policy_and_disk_projection_fallback(self):
        self.assertTrue(c.ram_fits(7500000,24,'design')[0]);self.assertFalse(c.ram_fits(30000000,24,'design')[0])
        self.assertTrue(c.ram_fits(7500000,12,'covariance')[0]);self.assertFalse(c.ram_fits(50000000,6,'covariance')[0])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,scores=fixture.synthetic(root);job=m.job_for(root,'fallback','disk',src,scores)
            with patch.object(m,'ram_fits',return_value=(False,20.)):
                m.fit(job)
            diag=c.load(Path(job['output'])/'numerical_diagnostics.json');self.assertEqual(diag['storage_engine'],'parallel_disk_FWL')
            original=oldm.job_for(root,'fallback','reference',src,scores);oldcov=oldm.covariance
            with patch.object(oldm,'covariance',side_effect=lambda p,cols,r,mem:oldcov(p,cols,r,mem,buckets=4)):oldm.fit(original)
            self.compare_results(c.load(Path(job['output'])/'result.json'),c.load(Path(original['output'])/'result.json'))

    def test_resume_requires_original_configuration_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            # Match the original producer, which records canonical project paths.
            # macOS temporary directories may be spelled /var or /private/var.
            p=Path(td).resolve();config=dict(version='1.0.0',rule=c.RULE90,manifest_sha256='original',project=str(p),
                r12_root='/r12',r9_root=None,local_plan=None,reuse_run='/old',reuse_chronology='/chron')
            conf=c.key(config);root=p/'derived/replication/receipt_iv_uniform90_v100_PRIVATE'/conf[:12];root.mkdir(parents=True)
            c.save(root/'config.json',config);a=SimpleNamespace(project=p,result_dir=p/'out',resume_root=root)
            got=runner.bind_resume(a,'original');self.assertEqual(got,(root,conf));self.assertEqual(a.reuse_run,Path('/old'))
            with self.assertRaisesRegex(RuntimeError,'manifest'):runner.bind_resume(a,'wrong')
            config['rule']=dict(c.RULE90,spacing_days=90);c.save(root/'config.json',config)
            with self.assertRaisesRegex(RuntimeError,'mismatch'):runner.bind_resume(a,'original')

    def test_resume_canonicalizes_symlinked_project_paths(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td).resolve();project=base/'real_project';project.mkdir()
            alias=base/'project_alias';alias.symlink_to(project,target_is_directory=True)
            config=dict(version='1.0.0',rule=c.RULE90,manifest_sha256='original',project=str(project),
                r12_root='/r12',r9_root=None,local_plan=None,reuse_run='/old',reuse_chronology='/chron')
            conf=c.key(config);relative=Path('derived/replication/receipt_iv_uniform90_v100_PRIVATE')/conf[:12]
            root=project/relative;root.mkdir(parents=True);c.save(root/'config.json',config)
            before=(root/'config.json').read_bytes()
            a=SimpleNamespace(project=alias,result_dir=alias/'out',resume_root=alias/relative)
            self.assertEqual(runner.bind_resume(a,'original'),(root,conf))
            self.assertEqual(a.project,project);self.assertEqual(a.result_dir,project/'out')
            self.assertEqual((root/'config.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
