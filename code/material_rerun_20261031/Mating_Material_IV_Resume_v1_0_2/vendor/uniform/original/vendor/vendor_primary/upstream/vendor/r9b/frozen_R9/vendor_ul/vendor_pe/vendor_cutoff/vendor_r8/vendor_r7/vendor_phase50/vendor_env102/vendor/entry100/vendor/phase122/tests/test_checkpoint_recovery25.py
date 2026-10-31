import sys,tempfile,unittest,json,hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from cached_common import *
import checkpoint_recovery25 as fix
import checkpoint_reporting as report


def fixture(root):
    coverage=root/'coverage';old=root/'quarantine_original';phase=root/'phase'
    empty=pa.table(dict(game_id=pa.array([],pa.string()),disposition=pa.array([],pa.string())))
    for month in ex.MONTHS:
        io.table(coverage/month/'unresolved_PRIVATE.parquet',empty)
        io.table(coverage/month/'pool.parquet',pa.table(dict(game_id=pa.array([],pa.string()))))
    for month,gid in [('2024-04','APRIL001'),('2025-06','JUNE0001')]:
        io.table(coverage/month/'unresolved_PRIVATE.parquet',pa.table(dict(game_id=[gid],disposition=[fix.REASON])))
    def old_build(tmp):
        io.table(tmp/'frame_record_PRIVATE.parquet',pa.table(dict(game_id=['APRIL001'])))
    io.stage(old,'test',old_build)
    ledger=root/'june.parquet'
    record=dict(game_id='JUNE0001',month='2025-06',previous_frame=False,local_eligibility='POTENTIALLY_ELIGIBLE',retrieval_rank=threshold(10),utc_ms=int(STARTS[19]),speed_partition='blitz')
    io.table(ledger,pa.Table.from_pylist([record]))
    raw={f.name:None for f in ex.metadata_schema()}
    raw.update(game_id='JUNE0001',source='pool',status='resign',api_start_ms=int(STARTS[19]),anchor_ms=int(STARTS[19])+1000,rated=True,variant='standard',speed='blitz',tc_base_s=180,tc_inc_s=0,white_username='user_a',black_username='user_b',black_rating=1500.,winner='black',record_errors='MISSING_WHITE_RATING')
    response=phase/'download/25/finished/downloaded_metadata.parquet'
    io.table(response,pa.Table.from_pylist([raw],schema=ex.metadata_schema()))
    schema=pa.schema([f for f in ex.metadata_schema() if f.name!='record_errors']+[pa.field('cached_conflict_or_prior_flag',pa.bool_())])
    merged=dict(raw,cached_conflict_or_prior_flag=True);merged.pop('record_errors')
    metadata=root/'metadata.parquet';io.table(metadata,pa.Table.from_pylist([merged],schema=schema))
    up=dict(ledgers=[str(ledger)]*len(ex.MONTHS));ph=dict(root=str(phase),metadata=str(metadata),phase10={})
    return dict(coverage=coverage,old=old,ledger=ledger,response=response,metadata=metadata,record=record,raw=raw,up=up,phase=ph,root=root/'quarantine')


def audit(f):
    with mock.patch.object(fix.prior,'reuse_v101_quarantine',return_value=True):
        return fix.audit_quarantine(None,f['up'],f['phase'],f['coverage'],f['root'],'test',.5)


class Recovery25Tests(unittest.TestCase):
    def test_saved_response_audit_counts_privacy_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            f=fixture(Path(td));out,r=audit(f);s=io.load(out/'summary.json')
            self.assertEqual(s['quarantined_rows'],2)
            self.assertEqual(s['counts_by_cohort'],dict(new_phase10=1,increment_10_25=1,new_phase25=2,old_author_clean=0,pooled=2))
            self.assertEqual(s['records'][1]['response_error_codes'],['MISSING_WHITE_RATING'])
            self.assertIn('white_rating',s['records'][1]['missing_response_fields'])
            self.assertEqual(s['records'][1]['fields_differing_from_completed_response'],[])
            for private in ('APRIL001','JUNE0001','user_a','user_b'):
                self.assertNotIn(private,(out/'summary.json').read_text())
            with mock.patch.object(fix,'require_rows',side_effect=AssertionError('must reuse completed audit')):
                self.assertEqual(audit(f)[1],r)

    def test_audit_rejects_extra_changed_unflagged_or_retained_records(self):
        cases=('extra','april_identity','june_reason','old_band','no_response_flag','missing_response','retained_pool')
        for case in cases:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as td:
                f=fixture(Path(td))
                if case=='extra':io.table(f['coverage']/'2025-07/unresolved_PRIVATE.parquet',pa.table(dict(game_id=['OTHER001'],disposition=[fix.REASON])))
                elif case=='april_identity':io.table(f['coverage']/'2024-04/unresolved_PRIVATE.parquet',pa.table(dict(game_id=['OTHER001'],disposition=[fix.REASON])))
                elif case=='june_reason':io.table(f['coverage']/'2025-06/unresolved_PRIVATE.parquet',pa.table(dict(game_id=['JUNE0001'],disposition=['NO_CACHE'])))
                elif case=='old_band':io.table(f['ledger'],pa.Table.from_pylist([dict(f['record'],retrieval_rank=bytes(32))]))
                elif case=='no_response_flag':io.table(f['response'],pa.Table.from_pylist([dict(f['raw'],record_errors='')],schema=ex.metadata_schema()))
                elif case=='missing_response':io.table(f['response'],pa.Table.from_pylist([],schema=ex.metadata_schema()))
                elif case=='retained_pool':io.table(f['coverage']/'2025-06/pool.parquet',pa.table(dict(game_id=['JUNE0001'])))
                with self.assertRaises(RuntimeError):audit(f)

    def test_reviewed_coverage_reuse_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'prior/coverage/2025-06';info=fix.expected_month('2025-06')
            def build(tmp):
                io.js(tmp/'coverage.json',info)
                for name in ('pool.parquet','membership_PRIVATE.parquet','unresolved_PRIVATE.parquet'):
                    io.table(tmp/name,pa.table(dict(game_id=['saved'])))
                return info
            io.stage(source,'prior',build)
            job=dict(reuse=dict(root=str(root/'prior'),conf='prior'),month='2025-06',output=str(root/'coverage'),conf='new')
            with mock.patch.object(fix.checkpoint,'coverage_job',side_effect=AssertionError('must not rebuild joins')):
                got=fix.coverage_job(job)
            self.assertEqual(got['pool_rows'],482243)
            self.assertEqual(io.sha(root/'coverage/pool.parquet'),io.sha(source/'pool.parquet'))
            with (source/'pool.parquet').open('ab') as stream:stream.write(b'tamper')
            with self.assertRaisesRegex(RuntimeError,'changed'):fix.coverage_job(dict(job,output=str(root/'bad')))

    def test_prior_binding_rejects_changed_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ev=root/'evidence';local=dict(input_receipts=['verified']);phase=dict(snapshot='25%')
            config=dict(version='1.2.1',code_sha256='code',local_receipts=local['input_receipts'],phase=phase)
            conf=io.cfgsha(config);prior=root/'derived/replication/run2_phase25_analysis_v120_PRIVATE'/conf[:12]
            io.js(prior/'config.json',config);io.js(prior/'report/summary.json',dict(status='coverage'))
            io.js(ev/'authority.json',dict(config_sha256=conf,code_sha256='code',summary_sha256=io.sha(prior/'report/summary.json')))
            with mock.patch.object(fix,'EVIDENCE',ev):
                self.assertEqual(fix.bind_previous(SimpleNamespace(project_root=root),local,phase)['conf'],conf)
                with self.assertRaisesRegex(RuntimeError,'sources changed'):fix.bind_previous(SimpleNamespace(project_root=root),local,dict(snapshot='50%'))

    def test_export_reports_band_specific_quarantine_counts(self):
        # No estimation: exercise the aggregate report path with unsupported fits.
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);f=fixture(root);audit(f)
            (root/'desktop').mkdir()
            for cohort in report.COHORTS:
                io.js(root/'models'/('ordinary_'+cohort)/'result.json',dict(estimates=[dict(cohort=cohort,family='ordinary',specification='ordinary90_placebo',outcome='y',supported=False,reason='synthetic')],balance=[],joint_balance=[]))
            coverage=[fix.expected_month(m) for m in ex.MONTHS]
            got=report.export(root,root/'desktop','test',coverage,'MODEL_RESULTS_PARTIAL',0)
            self.assertEqual({r['cohort']:r['quarantined_focal_records'] for r in got['estimates']},dict(new_phase10=1,increment_10_25=1,new_phase25=2,old_author_clean=0,pooled=2))
            self.assertFalse(got['full_phase_metadata_resolved'])


if __name__=='__main__':unittest.main()
