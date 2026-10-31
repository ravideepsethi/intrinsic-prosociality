from test_environment import *
del ModelTests,RateTests,OperationalTests
import env_recovery


class ProgressTests(unittest.TestCase):
    def test_saved_fit_is_reported_even_when_next_fit_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run';root.mkdir();desktop=Path(td)/'desktop';desktop.mkdir()
            d=model_data(3200);io.table(root/'good.parquet',pa.table(d))
            bad={k:v.copy() for k,v in d.items()};bad['comp_adjusted_7d'][:]=np.nan
            # A recorded label inconsistency raises in the worker, before any
            # erroneous estimates are committed. Keep support so the gate runs.
            bad['comp_adjusted_7d']=d['comp_adjusted_7d'].copy()
            bad['status'][:]='timeout';bad['active_timeout'][:]=False
            io.table(root/'bad.parquet',pa.table(bad))
            jobs=[runner.model_job(root/(name+'.parquet'),'entry',name,False,root/'models'/name,'x',None) for name in ('good','bad')]
            calls=[];start=time.monotonic()
            def progress(status):
                reporting.export(root,desktop,'x',status,start)
                calls.append(io.load(root/'report/summary.json'))
            with self.assertRaises(RuntimeError):runner.model_map(jobs,Runtime(root),1,5,'fixture fits',progress)
            self.assertGreaterEqual(len(calls),2)
            self.assertEqual(calls[0]['completed_model_checkpoints'],1)
            self.assertEqual(calls[-1]['completed_model_checkpoints'],1)
            self.assertEqual(calls[-1]['status'],'MODEL_STAGE_FAILED_PARTIAL_RESULTS')
            self.assertEqual(calls[-1]['checked_numerical_fits'],1)
            self.assertEqual({r['cohort'] for r in io.load(root/'report/estimates.json')},{'good'})
            self.assertEqual(io.load(root/'report/numerical_progress.json')[0]['status'],'CONVERGED')
            self.assertTrue((root/'report/failure_summary.json').is_file())

    def test_v101_preparation_reused_without_reusing_old_numeric_models(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);binding={'fixture':True}
            rel=io.load(PACKAGE/'evidence/recovery_authority.json')['additional_previous_releases'][0]
            config=env_recovery.previous_config(binding,rel);conf=io.cfgsha(config)
            root=p/OUTPUT_REL/conf[:12];io.js(root/'config.json',config)
            def build(tmp):
                for c in COHORTS:io.table(tmp/(c+'.parquet'),pa.table({'row_id':[1]}))
                io.js(tmp/'bins.json',{'edges':[0]})
            io.stage(root/'prepared_entry',conf,build)
            io.js(root/'models/quick_pooled/result.json',{'unverified':'old model'})
            before=io.sha(root/'prepared_entry/_DONE.json')
            got=env_recovery.adopt_prepared(p,binding,p/'new','new')
            self.assertTrue(got['adopted']);self.assertEqual(got['source_config_sha256'],conf)
            self.assertEqual(io.sha(root/'prepared_entry/_DONE.json'),before)
            self.assertFalse((p/'new/models').exists())

if __name__=='__main__':unittest.main()
