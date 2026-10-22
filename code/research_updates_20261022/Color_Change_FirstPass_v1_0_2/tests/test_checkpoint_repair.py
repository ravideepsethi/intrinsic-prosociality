"""Producer-to-replay regression checks. Expected runtime: 5-30 seconds.
Synthetic Parquets only. Production source/hash requirements are not bypassed
outside these isolated tests.
"""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
from common import *
import checkpoints,replay,engine
from analysis import build_established_cohort


class CheckpointRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.producer=load_stage06(PACKAGE/"vendor/stage06_reference_19ad.py",REFERENCE_SHA)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.project=self.root/"project";self.work=self.root/"work"
        self.authority=self.root/"authority.json";write_json(self.authority,{"checkpoints":{}})
        self.patcher=patch.object(checkpoints,"AUTHORITY_PATH",self.authority);self.patcher.start()
        write_json(self.project/"derived/glicko2_replay/user_dictionary_v1/summary.json",{"total_global_users":4})

    def tearDown(self):self.patcher.stop();self.tmp.cleanup()

    def make_checkpoint(self,speed="blitz",month="2025-10"):
        config=SimpleNamespace(**checkpoints.POLICY,output_root=str(self.project/"derived/replication/glicko2_cost_layer"),script_sha256=REFERENCE_SHA)
        last=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthEnd()).timestamp()*1000)
        state=(np.full(4,80.,np.float32),np.full(4,.09,np.float32),np.full(4,200,np.uint32),np.full(4,last,np.int64))
        # This is the real original writer, including its metadata semantics.
        m=self.producer.write_checkpoint(config,speed,month,*state,400,400,0)
        authority=read_json(self.authority)
        authority["checkpoints"].setdefault(month,{})[speed]={"checkpoint_parquet_sha256":m["sha256"]}
        write_json(self.authority,authority)
        return Path(m["path"]),m,state

    def make_events(self,speed,month):
        start=int(pd.Timestamp(month+'-19T00:00:00Z').timestamp()*1000)
        df=pd.DataFrame({"game_id":[f"{speed}_{month}_{i}" for i in range(3)],"archive_ordinal":[1,2,3],
            "utc_ms":np.arange(3,dtype=np.int64)*1000+start,"white_id":[0,2,0],"black_id":[1,3,3],
            "white_elo":[1500,1600,1490],"black_elo":[1510,1700,1690],
            "white_rating_diff":[1.,np.nan,-1.],"black_rating_diff":[-1.,np.nan,1.],"result_code":[2,1,0]})
        p=self.project/f"derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time/speed={speed}/month={month}/part-00000.parquet"
        write_frame(df,p)
        return p,df

    def test_actual_inventory_producer_records_data_digest(self):
        cp,m,_=self.make_checkpoint()
        text=(PACKAGE/"vendor/foundation_inventory_source.txt").read_text()
        source=text[text.index('def inventory_dictionary_and_checkpoints('):]
        namespace={"Path":Path,"Any":Any,"pq":pq,"read_json":read_json}
        exec(compile(source,'foundation_inventory_source.txt','exec'),namespace)
        found=namespace["inventory_dictionary_and_checkpoints"](self.project)["stage06_checkpoints"][0]
        self.assertTrue(found["path"].endswith('.json'))
        self.assertEqual(found["sha256"],sha(cp))
        self.assertNotEqual(found["sha256"],sha(cp.with_suffix('.json')))
        rec=checkpoints.authenticate_checkpoint(self.project,self.work,"blitz","2025-10")
        self.assertEqual(rec["status"],"CHECKPOINT_AUTHENTICATED")
        self.assertEqual(rec["data_sha256"],found["sha256"])

    def test_preflight_receipt_avoids_second_checkpoint_scan(self):
        cp,_,_=self.make_checkpoint()
        checkpoints.authenticate_checkpoint(self.project,self.work,"blitz","2025-10")
        actual_sha=checkpoints.sha
        def checked_sha(p):
            if Path(p)==cp:raise AssertionError("Checkpoint data read twice")
            return actual_sha(p)
        with patch.object(checkpoints,"sha",side_effect=checked_sha):
            rec=checkpoints.authenticate_checkpoint(self.project,self.work,"blitz","2025-10")
        self.assertEqual(rec["verification"],"verified receipt reused")

    def test_changed_checkpoint_data_is_rejected_against_independent_pin(self):
        cp,m,_=self.make_checkpoint()
        checkpoints.authenticate_checkpoint(self.project,self.work,"blitz","2025-10")
        df=pd.read_parquet(cp);df.loc[0,"rd"]=120.;write_frame(df,cp)
        m["size_bytes"]=cp.stat().st_size;write_json(cp.with_suffix('.json'),m)
        with self.assertRaisesRegex(RuntimeError,"Parquet data checksum differs"):
            checkpoints.authenticate_checkpoint(self.project,self.work,"blitz","2025-10")
        rec=read_json(self.work/"checkpoint_authentication/blitz_2025-10.json")
        self.assertEqual(rec["status"],"CHECKPOINT_AUTHENTICATION_FAILED")
        self.assertNotEqual(rec["data_sha256"],rec["expected_data_sha256"])

    def test_metadata_hash_and_policy_mismatches_are_rejected(self):
        cp,m,_=self.make_checkpoint()
        wrong=dict(m,sha256='0'*64);write_json(cp.with_suffix('.json'),wrong)
        with self.assertRaisesRegex(RuntimeError,"data hash differs"):
            checkpoints.authenticate_checkpoint(self.project,self.work,"blitz","2025-10")
        wrong=dict(m,speed='bullet',both_null_policy='update');write_json(cp.with_suffix('.json'),wrong)
        with self.assertRaisesRegex(RuntimeError,"policy or identity mismatch"):
            checkpoints.authenticate_checkpoint(self.project,self.work,"blitz","2025-10")
        rec=read_json(self.work/"checkpoint_authentication/blitz_2025-10.json")
        self.assertEqual(set(rec["policy_mismatches"]),{'speed','both_null_policy'})

    def test_preflight_checks_all_pools_before_replay(self):
        for speed in SPEEDS:
            for month in ('2023-10','2025-10'):self.make_checkpoint(speed,month)
            for month in POST_MONTHS:self.make_events(speed,month)
        out=checkpoints.preflight_all(self.project,self.work,10,self.producer.REQUIRED_REPLAY_COLUMNS)
        self.assertEqual(out['status'],'REPLAY_PREFLIGHT_OK')
        self.assertEqual(len(out['checkpoints']),10);self.assertEqual(len(out['events']),15)
        cohort=build_established_cohort(self.project,self.work)
        self.assertEqual(pq.ParquetFile(cohort).metadata.num_rows,20)
        checkpoints.checkpoint_path(self.project,'bullet','2025-10').unlink()
        checkpoints.checkpoint_path(self.project,'rapid','2023-10').unlink()
        with self.assertRaisesRegex(RuntimeError,'2 problem'):
            checkpoints.preflight_all(self.project,self.work,10,self.producer.REQUIRED_REPLAY_COLUMNS)
        self.assertEqual(len(read_json(self.work/'replay_preflight.json')['failures']),2)

    def test_full_three_month_replay_from_original_writer_and_resume(self):
        cp,_,initial=self.make_checkpoint()
        all_events=[]
        for month in POST_MONTHS:
            _,df=self.make_events('blitz',month);all_events.append(df)
            write_frame(pd.DataFrame({'game_id':df.game_id,'speed':'blitz'}),self.work/f'base/month={month}/opportunities.parquet')
        task=(str(self.project),str(self.work),'blitz',str(PACKAGE/'vendor/stage06_reference_19ad.py'),False)
        with patch.object(replay,'load_stage06',return_value=self.producer):
            first=replay.speed_replay(task)
            self.assertEqual([r['contract']['month'] for r in first],list(POST_MONTHS))
            self.assertEqual(sum(r['target_rows'] for r in first),9)
            with patch.object(self.producer,'load_checkpoint',side_effect=AssertionError('replayed completed month')):
                second=replay.speed_replay(task)
        self.assertEqual([r['key'] for r in first],[r['key'] for r in second])
        # Compare the actual on-disk terminal checkpoint with one uninterrupted
        # kernel sequence, including the both-null game in every month.
        expected=[v.copy() for v in initial]
        fn,_=engine.configure(self.producer,False);df=pd.concat(all_events,ignore_index=True)
        fn(*expected,df.white_id.to_numpy(np.int64),df.black_id.to_numpy(np.int64),
            df.white_elo.to_numpy(float),df.black_elo.to_numpy(float),df.utc_ms.to_numpy(np.int64),
            df.result_code.to_numpy(np.int8),df.white_rating_diff.to_numpy(float),df.black_rating_diff.to_numpy(float))
        restored=self.producer.load_checkpoint(Path(first[-1]['outputs']['checkpoint']['path']),4,SimpleNamespace(default_rd=500.,default_sigma=.09))
        for a,b in zip(restored,expected):np.testing.assert_array_equal(a,b)

if __name__=='__main__':unittest.main()
