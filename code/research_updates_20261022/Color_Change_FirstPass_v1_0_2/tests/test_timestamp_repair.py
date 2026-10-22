"""Regression checks for the returned 2023-10 failure. Expected runtime: 5-30 s.
Only small temporary Parquets are used; no installed project files are changed.
"""
import sys,tempfile,unittest
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
from common import *
import timestamps
from panel import normalize_month,normalize_all
from run import PLAN


class TimestampRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.project=self.root/"project";self.work=self.root/"work"

    def tearDown(self):self.tmp.cleanup()

    def source(self,month,native=False):
        df=pd.DataFrame({"game_id":["b","a"],"candidate_chooser":["alice","bob"],
            "likely_disconnected_player":["charlie","dave"],"candidate_chooser_color":["white","black"],
            "candidate_chooser_elo":[1500.,1600.],"likely_disconnected_elo":[1600.,1500.],
            "api_speed":"blitz","outcome_kind_draw":[True,False],"sf100k_eval_cp_disconnected":0.})
        if native:df["utc_ms"]=[self.time(month,2),self.time(month,1)]
        p=self.root/f"engine/{month}/part_00000.parquet";write_frame(df,p)
        write_json(p.with_suffix(".done.json"),{"error_rows":0,"rows":2,"part_sha256":sha(p)})
        return {"month":month,"kind":"sf100k_extension","paths":[str(p)]}

    @staticmethod
    def time(month,day):return int(pd.Timestamp(f"{month}-{day:02}T12:34:56Z").timestamp()*1000)

    def auxiliary(self,month,relative,ids=("a","b"),mode="parts"):
        df=pd.DataFrame({"game_id":ids})
        if mode=="parts":
            df["utc_date"]=[f"{month}-{1 if x=='a' else 2:02}".replace("-",".") for x in ids]
            df["utc_time"]="12:34:56"
        elif mode=="utc_ts":
            df["utc_ts"]=[f"{month}-{1 if x=='a' else 2:02} 12:34:56" for x in ids]
        else:df["utc_ms"]=[self.time(month,1 if x=="a" else 2) for x in ids]
        p=self.project/relative;write_frame(df,p);return p

    def registry(self,month,paths):
        p=self.root/"registry.json"
        write_json(p,{"source_receipt_sha256":"synthetic-fixture-only","months":{month:{"files":[
            {"relative_path":str(x.relative_to(self.project)),"sha256":sha(x),"size_bytes":x.stat().st_size} for x in paths]}}})
        return p

    def assert_times(self,receipt,month):
        out=pd.read_parquet(receipt["output"]["path"]).set_index("game_id")
        self.assertEqual(int(out.loc["a","utc_ms"]),self.time(month,1))
        self.assertEqual(int(out.loc["b","utc_ms"]),self.time(month,2))

    def test_returned_frozen_plan_is_unchanged(self):
        self.assertEqual(PLAN,read_json(PACKAGE/"vendor/frozen_plan_v100.json"))

    def test_v100_native_and_modern_caches_are_reused(self):
        for native,month in ((True,"2025-01"),(False,"2026-01")):
            with self.subTest(native=native):
                item=self.source(month,native);files=[Path(item["paths"][0])]
                if not native:
                    files.append(self.auxiliary(month,f"derived/replication/pgn_timeforfeit_candidates/month={month}/api_target_candidates_ge5s_or_missing.parquet"))
                rec=normalize_month((self.project,self.work,item,256))
                old_key=digest({"version":"1.0.0","month":month,"sources":[stamp(p) for p in files],"expected_sha256":None})
                self.assertEqual(rec["key"],old_key)
                # Model the old receipt, which had no new timestamp-audit fields.
                for key in ("timestamp_source","timestamp_authentication","timestamp_join"):rec.pop(key)
                rec["old_receipt_sentinel"]=True
                write_json(Path(rec["output"]["path"]).with_suffix(".json"),rec)
                with patch("panel.copy_query",side_effect=AssertionError("recomputed completed month")):
                    reused=normalize_month((self.project,self.work,item,256))
                self.assertEqual(reused,rec)

    def test_registered_historical_layout_all_four_months(self):
        authority=read_json(PACKAGE/"vendor/historical_timestamp_sources.json")
        for month in ("2023-10","2025-11","2025-12","2026-02"):
            with self.subTest(month=month):
                item=self.source(month);registered=authority["months"][month]["files"]
                paths=[]
                # Real documented relative paths; synthetic checksums and data.
                for i,entry in enumerate(registered):
                    ids=("a","b","unrelated","unrelated") if i==0 else ("unrelated",)
                    paths.append(self.auxiliary(month,entry["relative_path"],ids,mode="utc_ts" if month=="2026-02" else "parts"))
                with patch.object(timestamps,"SOURCE_REGISTRY",self.registry(month,paths)):
                    rec=normalize_month((self.project,self.work,item,256))
                self.assertEqual(rec["timestamp_source"]["kind"],"registered_historical_source")
                self.assertEqual(rec["timestamp_join"]["matched_rows"],2)
                self.assert_times(rec,month)

    def test_registered_source_hash_mismatch_stops(self):
        month="2023-10";item=self.source(month)
        p=self.auxiliary(month,"historical/source.parquet");registry=self.registry(month,[p])
        data=read_json(registry);data["months"][month]["files"][0]["sha256"]="0"*64;write_json(registry,data)
        with patch.object(timestamps,"SOURCE_REGISTRY",registry):
            with self.assertRaisesRegex(RuntimeError,"SHA-256 mismatch"):
                normalize_month((self.project,self.work,item,256))

    def test_shared_historical_hash_receipt_avoids_second_scan(self):
        month="2025-11";p=self.auxiliary(month,"historical/shared.parquet")
        spec={"files":[{"path":str(p),"expected_sha256":sha(p),"expected_bytes":p.stat().st_size}]}
        first=timestamps.authenticate_sources(spec,self.work)
        with patch.object(timestamps,"sha",side_effect=AssertionError("rehashed shared shard")):
            second=timestamps.authenticate_sources(spec,self.work)
        self.assertEqual(first[0]["sha256"],second[0]["sha256"])

    def test_existing_replay_fallback_is_exact_keyed_lookup(self):
        month="2023-10";item=self.source(month)
        historical=self.auxiliary(month,"historical/no-time.parquet")
        write_frame(pd.DataFrame({"game_id":["a","b"],"old_payoff":[2.,3.]}),historical)
        registry=self.registry(month,[historical])
        for speed in SPEEDS:
            rel=f"derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time/speed={speed}/month={month}/part-00000.parquet"
            self.auxiliary(month,rel,ids=("a","b") if speed=="blitz" else ("irrelevant",),mode="utc_ms")
        with patch.object(timestamps,"SOURCE_REGISTRY",registry):
            rec=normalize_month((self.project,self.work,item,256))
        self.assertEqual(rec["timestamp_source"]["kind"],"existing_replay_timestamps")
        self.assert_times(rec,month)

    def test_target_timestamp_keys_missing_or_duplicated_stop(self):
        for ids,message in ((("a",),"covers 1/2"),(("a","a","b"),"Duplicate timestamp-source")):
            with self.subTest(ids=ids):
                month="2023-10";item=self.source(month)
                p=self.auxiliary(month,"historical/source.parquet",ids=ids)
                with patch.object(timestamps,"SOURCE_REGISTRY",self.registry(month,[p])):
                    with self.assertRaisesRegex(RuntimeError,message):normalize_month((self.project,self.work,item,256))

    def test_wrong_epoch_units_stop(self):
        month="2023-10";item=self.source(month)
        p=self.auxiliary(month,"historical/source.parquet",mode="utc_ms")
        df=pd.read_parquet(p);df["utc_ms"]//=1000;write_frame(df,p)
        with patch.object(timestamps,"SOURCE_REGISTRY",self.registry(month,[p])):
            with self.assertRaisesRegex(RuntimeError,"wrong epoch units"):normalize_month((self.project,self.work,item,256))

    def test_timestamp_priority_preserves_v100_when_utc_ts_also_exists(self):
        month="2025-01";item=self.source(month,True);p=Path(item["paths"][0])
        df=pd.read_parquet(p).rename(columns={"utc_ms":"api_created_at_ms"})
        df["utc_ts"]="2024-01-01 00:00:00";write_frame(df,p)
        write_json(p.with_suffix(".done.json"),{"error_rows":0,"rows":2,"part_sha256":sha(p)})
        rec=normalize_month((self.project,self.work,item,256));self.assert_times(rec,month)

    def test_spawn_workers_record_every_failure_and_keep_completed_month(self):
        items=[self.source("2025-01",True),self.source("2023-10"),self.source("2026-02")]
        for item in items:item["available"]=True
        def pool(max_workers):
            return ProcessPoolExecutor(max_workers=max_workers,mp_context=multiprocessing.get_context("spawn"))
        with patch("panel.catalog",return_value=items),patch("panel.ProcessPoolExecutor",side_effect=pool):
            with self.assertRaisesRegex(RuntimeError,"Normalization needs repair"):
                normalize_all(self.project,self.work,2,256)
        status=read_json(self.work/"normalization_status.json")
        self.assertEqual(status["completed_months"],["2025-01"])
        self.assertEqual({x["month"] for x in status["failures"]},{"2023-10","2026-02"})
        self.assertTrue((self.work/"base/month=2025-01/opportunities.json").is_file())

if __name__=="__main__":unittest.main()
