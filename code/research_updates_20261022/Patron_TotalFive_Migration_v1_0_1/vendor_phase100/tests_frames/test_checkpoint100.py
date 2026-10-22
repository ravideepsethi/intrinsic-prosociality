import sys,tempfile,unittest,shutil
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from phase100_common import *
import phase100_inputs as cp
sys.path.insert(0,str(UPSTREAM/'tests'))
import test_cached as fixture

class FinalCheckpointTests(unittest.TestCase):
    def test_full_original_bands_required_and_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);phase=root/'phase';result=phase/'phase_results/100';conf='synthetic'
            up=dict(ledgers=['ledger'],manifest=dict(original_cached_metadata='cached'))
            auth=io.load(UPSTREAM/'evidence/checkpoint_authority.json')
            controller=io.cfgsha(dict(version='1.0.0',package_sha256=auth['continuous_package_sha'],inherited_config=conf,checkpoints=[25,50,75,100]))
            marker=phase/'continuous_v100'/controller[:12]/'REPORT_100_DONE.json'
            for p in (10,25,50,100):
                target=phase/'plan'/f'targets_{p}.parquet';io.table(target,pa.table(dict(game_id=[str(p)])))
                io.stage(phase/'download'/str(p)/'finished',io.cfgsha([conf,p,io.sha(target)]),
                    lambda tmp:dict(requested=1,returned=1,not_returned=0,returned_with_metadata_flags=0))
            io.stage(result/'merged',io.cfgsha([conf,100]),lambda tmp:io.table(tmp/'metadata.parquet',pa.table(dict(game_id=['a']))))
            row=dict(through_percent=100,cumulative_targets=4,incremental_targets=1,additional_frame_rows=9)
            io.js(phase/'plan/summary.json',dict(phases=[row]))
            inputs=dict(through_percent=100,fixed_denominator=up['ledgers'],upstream_manifest=up['manifest'],
                additional_frame_selection_sql=selection_sql(100),merged_candidate_metadata=str(result/'merged/metadata.parquet'),
                original_cached_metadata='cached',full_historical_and_prospective_anchor_stream_required=True,all_frame_rows_preserved=True,final_sample_and_rules_unchanged=True)
            io.js(result/'ANALYSIS_INPUTS_PRIVATE.json',inputs)
            io.js(result/'report/summary.json',dict(row,requested=4,returned=4,not_returned=0,metadata_flags=0,all_requested_ids_accounted=True))
            q=result/'report/summary.json';io.js(result/'report/REPORT_MANIFEST.json',[dict(path=q.name,sha256=io.sha(q),bytes=q.stat().st_size)])
            evidence=root/'evidence/checkpoint100';evidence.mkdir(parents=True)
            for name in ('summary.json','REPORT_MANIFEST.json'):shutil.copyfile(result/'report'/name,evidence/name)
            old=dict(root=str(phase),config_sha256=conf)
            with mock.patch.object(cp.old,'authenticate_phase',return_value=old),mock.patch.object(cp,'RELEASE',root):
                with self.assertRaisesRegex(RuntimeError,'CHECKPOINT_100_SAVED'):cp.authenticate_checkpoint(SimpleNamespace(),up)
                io.js(marker,dict(controller_conf=controller,inputs_sha256=io.sha(result/'ANALYSIS_INPUTS_PRIVATE.json'),manifest_sha256=io.sha(result/'report/REPORT_MANIFEST.json')))
                got=cp.authenticate_checkpoint(SimpleNamespace(),up);self.assertEqual(got['summary']['requested'],4)
                self.assertFalse((phase/'download/75').exists())
                with (result/'merged/metadata.parquet').open('ab') as f:f.write(b'changed')
                with self.assertRaises(RuntimeError):cp.authenticate_checkpoint(SimpleNamespace(),up)

    def test_maximum_hash_included_without_overflow_and_old_frame_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rows=[];metadata=[]
            for k,rank in enumerate([bytes(32),threshold(75),bytes([255])*32,bytes(32)]):
                rows.append(dict(game_id=f'G{k:07}',utc_ms=fixture.T,speed_partition='blitz',retrieval_rank=rank,previous_frame=k==3,
                    local_eligibility='POTENTIALLY_ELIGIBLE',recipient_color='white',recipient_id=k,opponent_id=100+k,n7_author_clean=6))
                metadata.append(dict(game_id=f'G{k:07}',source='pool',status=['mate','timeout','resign','draw'][k],api_start_ms=fixture.T,anchor_ms=fixture.T+1,
                    rated=True,variant='standard',speed='blitz',tc_base_s=180,tc_inc_s=0,white_username='w',black_username='b',white_rating=1500.,black_rating=1500.,winner='white',cached_conflict_or_prior_flag=False))
            ledger=fixture.put(root,'ledger.parquet',pa.Table.from_pylist(rows));meta=fixture.put(root,'metadata.parquet',pa.Table.from_pylist(metadata))
            got=cp.coverage_job(dict(ledger=ledger,metadata=[meta],month=MONTHS[6],memory=.5,conf='test',output=str(root/'coverage')))
            self.assertEqual((got['selected_frame_rows'],got['ordinary_rows']),(3,2))
            self.assertEqual(io.read(root/'coverage/pool.parquet')['status'].to_pylist(),['mate','timeout','resign'])

    def test_nested_bands_rebind_ids_and_require_all_old_features(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);assembled=root/'assembled';prior=root/'prior'
            membership=fixture.put(root,'membership.parquet',dict(game_id=['a','b','c'],retrieval_rank=[bytes(32),threshold(75),bytes([255])*32]))
            for family in ('ordinary','entry'):
                full=pa.table(dict(row_id=[100,200,300],game_id=['a','b','c'],y=[True,False,True],value=[.1,.2,.3]))
                old=pa.table(dict(row_id=[9],game_id=['old'],y=[False],value=[.4]))
                for label in ('new_phase100','pooled'):io.table(assembled/(family+'_'+label+'.parquet'),full)
                for base in (assembled,prior/'assembled'):io.table(base/(family+'_old_author_clean.parquet'),old)
                io.table(prior/'assembled'/(family+'_new_phase75.parquet'),pa.table(dict(row_id=[7],game_id=['a'],y=[True],value=[.1])))
            out,info=cp.split_samples(assembled,[membership],dict(root=str(prior)),root/'split','test',.5)
            self.assertEqual(io.read(out/'entry_increment_75_100.parquet')['game_id'].to_pylist(),['b','c'])
            self.assertTrue(all(v['game_identity_and_all_features_reproduced'] for v in io.load(out/'bridge.json')['checks']))
            io.table(prior/'assembled/entry_new_phase75.parquet',pa.table(dict(row_id=[7],game_id=['a'],y=[False],value=[.1])))
            with self.assertRaisesRegex(RuntimeError,'features changed'):cp.split_samples(assembled,[membership],dict(root=str(prior)),root/'bad','test',.5)

if __name__=='__main__':unittest.main()
