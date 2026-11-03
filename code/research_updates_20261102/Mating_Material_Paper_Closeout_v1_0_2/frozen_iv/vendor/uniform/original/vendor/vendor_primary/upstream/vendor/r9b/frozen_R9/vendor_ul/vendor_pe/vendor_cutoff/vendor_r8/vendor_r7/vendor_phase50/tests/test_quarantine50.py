import sys,unittest,tempfile,json
from pathlib import Path
from unittest import mock
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from phase50_common import *
import phase50_common as common
import phase50_recovery as fix
sys.path.insert(0,str(UPSTREAM/'tests'))
import test_checkpoint_recovery25 as parent


def fixture(root):
    f=parent.fixture(root)
    # Expand the coherent old fixture to the actual new band. Fresh January
    # data have no error flag; disagreement with cached data generates a flag.
    schemas=ex.metadata_schema();merged_schema=pa.schema([x for x in schemas if x.name!='record_errors']+[pa.field('cached_conflict_or_prior_flag',pa.bool_())])
    f['up']['ledgers']=[];metas=[]
    for month in ex.MONTHS:
        rows=[]
        if month in ('2024-04','2025-01','2025-06'):
            name={'2024-04':'APRIL001','2025-01':'JANUA001','2025-06':'JUNE0001'}[month]
            rank={'2024-04':bytes(32),'2025-01':threshold(25),'2025-06':threshold(10)}[month]
            row=dict(f['record'],game_id=name,month=month,retrieval_rank=rank,retrieval_disposition='NEEDS_API')
            rows=[row]
            meta=dict(f['raw'],game_id=name,cached_conflict_or_prior_flag=True);meta.pop('record_errors')
            metas.append(meta)
        path=root/'ledgers'/(month+'.parquet')
        io.table(path,pa.Table.from_pylist(rows or [dict(f['record'],game_id='UNUSED00',month=month)]))
        f['up']['ledgers'].append(str(path))
    io.table(f['metadata'],pa.Table.from_pylist(metas,schema=merged_schema))
    io.table(f['coverage']/'2025-01/unresolved_PRIVATE.parquet',pa.table(dict(game_id=['JANUA001'],disposition=[fix.REASON])))
    raw=dict(f['raw'],game_id='JANUA001',white_rating=1500.,record_errors=None)
    f['january_response']=Path(f['phase']['root'])/'download/50/finished/downloaded_metadata.parquet'
    io.table(f['january_response'],pa.Table.from_pylist([raw],schema=schemas))
    cached=dict(raw,white_rating=1499.,cached_conflict_or_prior_flag=False);cached.pop('record_errors')
    f['cache']=root/'pre_download.parquet';io.table(f['cache'],pa.Table.from_pylist([cached],schema=merged_schema))
    f['up']['metadata']=str(f['cache']);f['january_raw']=raw
    return f


def audit(f):
    with mock.patch.object(fix.prior,'reuse_v101_quarantine',return_value=True):
        return common.audit_quarantine(None,f['up'],f['phase'],f['coverage'],f['root'],'test',.5)


class QuarantineTests(unittest.TestCase):
    def test_three_flags_with_clean_new_response_conflicting_with_cache(self):
        with tempfile.TemporaryDirectory() as td:
            f=fixture(Path(td));out,info=audit(f)
            self.assertEqual(info['counts_by_cohort'],dict(new_phase25=2,increment_25_50=1,new_phase50=3,old_author_clean=0,pooled=3))
            jan=next(r for r in info['records'] if r['month']=='2025-01')
            self.assertEqual(jan['response_error_codes'],[])
            self.assertEqual(jan['response_vs_cache_fields_differing'],['white_rating'])
            self.assertTrue(jan['compared_sources_explain_flag']);self.assertFalse(jan['metadata_values_repaired'])
            for value in ('JANUA001','APRIL001','JUNE0001','user_a','user_b'):self.assertNotIn(value,(out/'summary.json').read_text())
            with mock.patch.object(fix,'require_rows',side_effect=AssertionError('must reuse')):self.assertEqual(audit(f)[1],info)

    def test_extra_changed_missing_or_retained_rows_stop(self):
        for case in ('extra','april_identity','january_reason','old_band','boundary50','no_june_error','missing_january_response','duplicate_january_response','retained_pool'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as td:
                f=fixture(Path(td))
                if case=='extra':io.table(f['coverage']/'2025-07/unresolved_PRIVATE.parquet',pa.table(dict(game_id=['OTHER001'],disposition=[fix.REASON])))
                elif case=='april_identity':io.table(f['coverage']/'2024-04/unresolved_PRIVATE.parquet',pa.table(dict(game_id=['OTHER001'],disposition=[fix.REASON])))
                elif case=='january_reason':io.table(f['coverage']/'2025-01/unresolved_PRIVATE.parquet',pa.table(dict(game_id=['JANUA001'],disposition=['NO_CACHE'])))
                elif case in ('old_band','boundary50'):
                    path=Path(f['up']['ledgers'][ex.MONTHS.index('2025-01')]);rows=io.read(path).to_pylist();rows[0]['retrieval_rank']=threshold(10 if case=='old_band' else 50);io.table(path,pa.Table.from_pylist(rows))
                elif case=='no_june_error':io.table(f['response'],pa.Table.from_pylist([dict(f['raw'],record_errors='')],schema=ex.metadata_schema()))
                elif case=='missing_january_response':io.table(f['january_response'],pa.Table.from_pylist([],schema=ex.metadata_schema()))
                elif case=='duplicate_january_response':io.table(f['january_response'],pa.Table.from_pylist([f['january_raw']]*2,schema=ex.metadata_schema()))
                elif case=='retained_pool':io.table(f['coverage']/'2025-01/pool.parquet',pa.table(dict(game_id=['JANUA001'])))
                with self.assertRaises(RuntimeError):audit(f)

    def test_flag_without_known_cause_is_explicitly_unresolved(self):
        row={k:None for k in ex.META_FIELDS};row['cached_conflict_or_prior_flag']=True
        d=fix.describe_metadata(row,[],[])
        self.assertFalse(d['compared_sources_explain_flag']);self.assertFalse(d['full_metadata_reconciliation_complete'])
        self.assertFalse(d['metadata_values_repaired'])

    def test_saved_coverage_reused_and_source_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'prior/coverage/2025-01';info=fix.expected_month('2025-01')
            def build(tmp):
                io.js(tmp/'coverage.json',info)
                for name in ('pool.parquet','membership_PRIVATE.parquet','unresolved_PRIVATE.parquet'):
                    io.table(tmp/name,pa.table(dict(game_id=['synthetic'])))
                return info
            io.stage(src,'prior',build)
            job=dict(reuse=dict(root=str(root/'prior'),conf='prior'),month='2025-01',output=str(root/'copy'),conf='new')
            with mock.patch.object(fix.checkpoint,'coverage_job',side_effect=AssertionError('must reuse')):r=fix.coverage_job(job)
            self.assertEqual(r['unresolved_rows'],1);self.assertEqual(io.sha(src/'pool.parquet'),io.sha(root/'copy/pool.parquet'))
            with (src/'pool.parquet').open('ab') as stream:stream.write(b'changed')
            with self.assertRaises(RuntimeError):fix.coverage_job(dict(job,output=str(root/'bad')))

    def test_binding_rejects_different_source_or_report(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ev=root/'evidence';local=dict(input_receipts=['frozen']);phase=dict(snapshot='50%')
            config=dict(version='1.0.0',code_sha256='code',local_receipts=local['input_receipts'],phase=phase);conf=io.cfgsha(config)
            old=root/'derived/replication/run2_phase50_analysis_v100_PRIVATE'/conf[:12]
            io.js(old/'config.json',config);io.js(old/'report/summary.json',dict(estimates=[]))
            io.js(ev/'authority.json',dict(config_sha256=conf,code_sha256='code',summary_sha256=io.sha(old/'report/summary.json')))
            with mock.patch.object(fix,'EVIDENCE',ev):
                self.assertEqual(fix.bind_previous(SimpleNamespace(project_root=root),local,phase)['conf'],conf)
                with self.assertRaisesRegex(RuntimeError,'sources changed'):fix.bind_previous(SimpleNamespace(project_root=root),local,dict(snapshot='75%'))
                io.js(old/'report/summary.json',dict(estimates=['changed']))
                with self.assertRaises(RuntimeError):fix.bind_previous(SimpleNamespace(project_root=root),local,phase)

if __name__=='__main__':unittest.main()
