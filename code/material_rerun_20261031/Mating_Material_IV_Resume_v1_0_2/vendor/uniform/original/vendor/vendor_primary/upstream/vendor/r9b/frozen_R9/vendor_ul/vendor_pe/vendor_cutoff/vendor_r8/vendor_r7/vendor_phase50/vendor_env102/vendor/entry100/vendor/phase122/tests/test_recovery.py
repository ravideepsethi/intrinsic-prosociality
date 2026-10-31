import sys,tempfile,unittest,copy,json,time,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from cached_common import *
import phase_recovery as repair
import phase_reporting as report
import test_cached as fixture
from unittest import mock
from types import SimpleNamespace

CONF='synthetic-recovery-v101';put=fixture.put;T=fixture.T

def reviewed_coverage():
    bymonth={m:dict(month=m,dispositions={},ending_counts=[]) for m in ex.MONTHS}
    for r in io.load(PACKAGE/'evidence/prior_failed_frame_dispositions.json'):
        bymonth[r['month']]['dispositions'][r['disposition']]=r['rows']
    for r in io.load(PACKAGE/'evidence/prior_failed_coverage_by_ending.json'):
        bymonth[r['month']]['ending_counts'].append(r)
    for d in bymonth.values():
        counts=d['dispositions'];d.update(selected_frame_rows=sum(counts.values()),pool_rows=counts.get('CACHED_POOL_METADATA',0),
            ordinary_rows=sum(r['rows'] for r in d['ending_counts'] if r['status'] in core.NARROW),
            unresolved_rows=counts.get('CACHE_CONFLICT_OR_PRIOR_FLAG',0))
    return list(bymonth.values())

def quarantine_inputs(root,conflict=True,overlap=False):
    gid='Flag0001'
    frame=put(root,'frame.parquet',dict(game_id=[gid],utc_ms=[T],speed_partition=['blitz'],retrieval_rank=[bytes(32)],
        previous_frame=[False],local_eligibility=['POTENTIALLY_ELIGIBLE']))
    m=dict(game_id=gid,source='pool',status='resign',api_start_ms=T,anchor_ms=T+1000,rated=True,variant='standard',speed='blitz',
        tc_base_s=180,tc_inc_s=0,white_username='private_white_name',black_username='private_black_name',
        white_rating=1400.,black_rating=1500.,winner='white',white_provisional=False,black_provisional=False,
        cached_conflict_or_prior_flag=conflict)
    meta=put(root,'meta.parquet',pa.Table.from_pylist([m]))
    raw={k:v for k,v in m.items() if k!='cached_conflict_or_prior_flag'};raw['record_errors']=''
    response=put(root,'response.parquet',pa.Table.from_pylist([raw],schema=ex.metadata_schema()))
    pool=put(root,'pool.parquet',dict(game_id=[gid if overlap else 'Good0001']))
    return frame,[meta],response,[pool]

class RecoveryTests(unittest.TestCase):
    def test_v101_quarantine_import_reuses_private_records_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);expected=io.load(PACKAGE/'evidence/v101_summary.json');prior_conf=expected['config_sha256']
            old=root/'derived/replication/run2_phase_analysis_v101_PRIVATE'/prior_conf[:12]
            local=dict(input_receipts=['bound']);phase=dict(test='same completed snapshot')
            config=dict(code_sha256='837fc3486dae3f8724583d09822be43cc5166933d8dafa2de3a11708b87445af',local_receipts=local['input_receipts'],phase=phase)
            io.js(old/'config.json',config)
            audit=io.load(PACKAGE/'evidence/v101_metadata_quarantine.json')
            def build(tmp):
                io.js(tmp/'summary.json',audit)
                io.table(tmp/'frame_record_PRIVATE.parquet',pa.table(dict(game_id=['Flag0001'])))
                return audit
            io.stage(old/'quarantine',prior_conf,build)
            args=SimpleNamespace(project_root=root);dest=root/'new_quarantine'
            with mock.patch('phase_recovery.io.cfgsha',return_value=prior_conf):
                self.assertTrue(repair.reuse_v101_quarantine(args,local,phase,dest,CONF))
                self.assertEqual(io.load(dest/'summary.json'),audit)
                self.assertEqual(io.read(dest/'frame_record_PRIVATE.parquet')['game_id'].to_pylist(),['Flag0001'])
                self.assertTrue(repair.reuse_v101_quarantine(args,local,phase,dest,CONF))
                (old/'quarantine/frame_record_PRIVATE.parquet').write_bytes(b'changed')
                with self.assertRaises(RuntimeError):repair.reuse_v101_quarantine(args,local,phase,dest,CONF)

    def test_reviewed_coverage_exact_count_and_category(self):
        good=reviewed_coverage();repair.assert_reviewed_coverage(good)
        bad=copy.deepcopy(good);bad[5]['dispositions']['CACHE_CONFLICT_OR_PRIOR_FLAG']+=1
        with self.assertRaisesRegex(RuntimeError,'Coverage differs'):repair.assert_reviewed_coverage(bad)
        bad=copy.deepcopy(good);bad[5]['unresolved_rows']=0
        with self.assertRaisesRegex(RuntimeError,'coverage total'):repair.assert_reviewed_coverage(bad)

    def test_verified_parquets_reused_and_tampering_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'old'
            info=dict(month='2024-04',pool_rows=2,ordinary_rows=2,selected_frame_rows=2,unresolved_rows=0,
                dispositions=dict(CACHED_POOL_METADATA=2),ending_counts=[])
            def build(tmp):
                io.table(tmp/'pool.parquet',pa.table(dict(game_id=['Good0001','Good0002'])))
                io.js(tmp/'coverage.json',info);return info
            io.stage(source,repair.PRIOR_CONF,build)
            src=repair.validated_source(dict(source=str(source),month='2024-04'))
            before=io.sha(source/'pool.parquet');dest=root/'new'
            job=dict(src,output=str(dest),conf=CONF)
            receipt=repair.reuse_coverage_job(job)
            self.assertEqual(receipt['pool_rows'],2);self.assertEqual(io.sha(dest/'pool.parquet'),before)
            self.assertEqual(io.sha(source/'pool.parquet'),before)
            self.assertEqual(repair.reuse_coverage_job(job),receipt)
            # Change the completed source bytes: its producer receipt must reject it.
            (source/'pool.parquet').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'changed'):repair.validated_source(dict(source=str(source),month='2024-04'))

    def test_agreeing_response_does_not_erase_flag_and_public_report_is_aggregate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);args=quarantine_inputs(root);before=[io.sha(p) for p in [args[0],*args[1],args[2],*args[3]]]
            out,r=repair.quarantine(*args,root/'quarantine',CONF,.4)
            self.assertEqual(r['quarantined_rows'],1);self.assertFalse(r['full_metadata_reconciliation_complete'])
            self.assertEqual(r['fields_differing_from_completed_response'],[])
            self.assertEqual(io.read(out/'frame_record_PRIVATE.parquet')['game_id'].to_pylist(),['Flag0001'])
            self.assertEqual(before,[io.sha(p) for p in [args[0],*args[1],args[2],*args[3]]])
            self.assertEqual(repair.quarantine(*args,root/'quarantine',CONF,.4)[1],r)
            desktop=root/'desktop';desktop.mkdir()
            result=report.export(root,desktop,CONF,reviewed_coverage(),'TEST_AVAILABLE_CASE',time.monotonic())
            self.assertTrue(result['available_case_interim']);self.assertFalse(result['full_phase_metadata_resolved'])
            self.assertEqual(result['unresolved_selected_rows'],1);self.assertEqual(result['estimates'],[])
            with zipfile.ZipFile(next(desktop.glob('*.zip'))) as z:
                self.assertIn('metadata_quarantine.json',z.namelist())
                for n in z.namelist():
                    self.assertNotIn('_PRIVATE',n)
                    if n.endswith(('.json','.txt','.csv')):
                        for secret in ('Flag0001','private_white_name','private_black_name'):
                            self.assertNotIn(secret,z.read(n).decode())

    def test_flagged_focal_record_cannot_enter_retained_models(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);args=quarantine_inputs(root,overlap=True)
            with self.assertRaisesRegex(RuntimeError,'occurs in the retained pool'):
                repair.quarantine(*args,root/'quarantine',CONF,.4)

    def test_different_field_values_remain_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);args=quarantine_inputs(root)
            tab=io.read(args[2]);values=tab.to_pylist();values[0]['anchor_ms']+=17
            io.table(args[2],pa.Table.from_pylist(values,schema=tab.schema))
            _,r=repair.quarantine(*args,root/'quarantine',CONF,.4)
            self.assertEqual(r['fields_differing_from_completed_response'],['anchor_ms'])
            self.assertFalse(r['full_metadata_reconciliation_complete'])
            self.assertFalse(r['focal_record_used_in_models'])

    def test_unresolved_export_without_audit_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaisesRegex(RuntimeError,'completed explicit quarantine'):
                report.export(root,root/'desktop',CONF,reviewed_coverage(),'TEST',time.monotonic())

if __name__=='__main__':unittest.main()
