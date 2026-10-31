from test_environment import *
del ModelTests,RateTests,OperationalTests
import env_status
import env_recovery

class StatusRegressionTests(unittest.TestCase):
    def test_real_null_parquet_conversion_then_full_model(self):
        d=model_data();n=len(d['row_id']);d['previous_frame'][:]=True;d['status']=np.asarray([None]*n)
        expected=oldmodels.estimate(d,'old_author_clean','competitive_supported')
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);io.table(p/'legacy.parquet',pa.table(d))
            self.assertTrue(pa.types.is_null(pq.ParquetFile(p/'legacy.parquet').schema_arrow.field('status').type))
            c=io.conn(p/'spill',1,1)
            try:io.copy(c,'SELECT * FROM '+io.parq([p/'legacy.parquet']),p/'prepared.parquet')
            finally:c.close()
            a=arrays(io.read(p/'prepared.parquet'))
            self.assertTrue(np.isnan(a['status']).all())
            # Precisely the old incorrect predicate: NaN was counted as observed.
            self.assertTrue(all(v is not None for v in a['status']))
            self.assertFalse(np.array_equal(a['active_timeout'],a['status']=='timeout'))
            _,audit=env_status.validate(a,'old_author_clean')
            self.assertEqual(audit['missing_legacy_rows'],n)
            self.assertEqual(audit['missing_status_rows_excluded_from_entry_models'],0)
            job=dict(input=str(p/'prepared.parquet'),kind='entry',cohort='old_author_clean',environment=False,conf='x',output=str(p/'model'))
            models.model_job(job);out=io.load(p/'model/result.json')
            for row in out['estimates']:
                self.assertFalse(row['outcome'].startswith('ending_'))
                if row['outcome'] not in ENTRY_COLUMNS:continue
                target=next(x for x in expected['estimates'] if x['control_level']=='XC' and x['outcome']==row['outcome'] and x['instrument']==row['instrument'])
                self.assertEqual(row['n'],n)
                for key in ('coefficient','standard_error'):
                    if key in target:self.assertAlmostEqual(target[key],row[key],10)

    def test_null_string_integer_and_nan_representations(self):
        for column in (pa.nulls(3),pa.nulls(3,pa.string()),pa.nulls(3,pa.int32()),pa.array([np.nan]*3)):
            a=arrays(pa.table(dict(status=column,previous_frame=[True]*3,active_timeout=[True,False,True])))
            known,r=env_status.validate(a)
            self.assertFalse(known.any());self.assertTrue(r['valid']);self.assertEqual(r['missing_legacy_rows'],3)

    def test_known_disagreement_caught_even_when_legacy_status_missing(self):
        a=dict(status=np.array([None,np.nan,'mate','timeout'],object),previous_frame=np.array([True,True,False,False]),active_timeout=np.array([True,False,True,True]))
        _,r=env_status.inspect(a)
        self.assertEqual(r['recorded_timeout_label_mismatches'],1)
        with self.assertRaisesRegex(RuntimeError,'Status audit failed'):env_status.validate(a)
        a['active_timeout'][2]=False;self.assertTrue(env_status.validate(a)[1]['valid'])

    def test_missing_expansion_and_invalid_nonmissing_labels_not_suppressed(self):
        for status in (np.nan,None,'nan','None','',3):
            a=dict(status=np.array([status],object),previous_frame=np.array([False]),active_timeout=np.array([False]))
            with self.assertRaisesRegex(RuntimeError,'Status audit failed'):env_status.validate(a)
        for status in ('nan','None','',3):
            a=dict(status=np.array([status],object),previous_frame=np.array([True]),active_timeout=np.array([False]))
            with self.assertRaisesRegex(RuntimeError,'Status audit failed'):env_status.validate(a)

    def test_failure_audit_written_before_model_stop(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for cohort in COHORTS:io.table(p/'prepared'/(cohort+'.parquet'),pa.table(dict(status=['mate'],previous_frame=[False],active_timeout=[True])))
            out,receipt=env_status.audit_prepared(p/'prepared',p/'audit','x')
            self.assertFalse(receipt['valid'])
            self.assertEqual(len(io.load(out/'status_coverage.json')),5)
            self.assertTrue((out/'status_coverage.csv').is_file())

class RecoveryTests(unittest.TestCase):
    def fixture(self,p):
        binding={'fixture':True};expected=env_recovery.previous_config(binding);oldconf=io.cfgsha(expected)
        old=p/OUTPUT_REL/oldconf[:12];io.js(old/'config.json',expected)
        def build(tmp):
            for cohort in COHORTS:io.table(tmp/(cohort+'.parquet'),pa.table({'row_id':[1]}))
            io.js(tmp/'bins.json',dict(edges=[0]))
        io.stage(old/'prepared_entry',oldconf,build)
        return binding,old

    def test_adopts_only_completed_exact_preparation_and_keeps_old_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);binding,old=self.fixture(p);oldsha=io.sha(old/'prepared_entry/_DONE.json')
            io.js(old/'models/quick_pooled/result.json',dict(should_not_be_reused=True))
            result=env_recovery.adopt_prepared(p,binding,p/'new','newconf')
            self.assertTrue(result['adopted']);self.assertEqual(result['old_models_reused'],0)
            self.assertEqual(io.sha(old/'prepared_entry/_DONE.json'),oldsha)
            self.assertFalse((p/'new/models').exists())
            self.assertIsNotNone(io.complete(p/'new/prepared_entry','newconf'))
            self.assertFalse(env_recovery.adopt_prepared(p,binding,p/'new','newconf')['adopted'])

    def test_changed_preparation_rejected_and_incomplete_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);binding,old=self.fixture(p)
            (old/'prepared_entry/bins.json').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'size changed|checksum changed'):env_recovery.adopt_prepared(p,binding,p/'new','newconf')
            (old/'prepared_entry/_DONE.json').unlink()
            self.assertFalse(env_recovery.adopt_prepared(p,binding,p/'new','newconf')['adopted'])

if __name__=='__main__':unittest.main()
