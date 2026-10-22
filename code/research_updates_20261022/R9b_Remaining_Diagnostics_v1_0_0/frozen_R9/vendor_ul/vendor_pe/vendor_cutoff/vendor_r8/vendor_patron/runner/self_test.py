"""Behavioral validation of new-design binding, bounds, and frozen estimators."""
import contextlib
import hashlib
import io
import itertools
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa

from runner import run as r
from runner import gap_sensitivity as gap
from source import acquisition_planner_v100 as planner
from source import synthetic_fixture_v101 as fixture


class PatronRebuildTests(unittest.TestCase):
    def test_exact_authorities_and_original_imputation(self):
        fixture.verify_nullable_integer_fractional_median()
        status,config=r.get_wave3a_authority()
        self.assertEqual(status["sample"]["rows"],41534331)
        self.assertEqual(config["snapshot_sha256"],r.prior.SNAPSHOT_SHA)
        gap_config,gap_status=gap.authority(r.ROOT)
        self.assertEqual(gap_config["wave3a_config_sha256"],r.WAVE3A_CONFIG)
        self.assertEqual(gap_status["current_profiles_returned"],122)
        for item in json.loads((r.ROOT/"authority/SOURCE_BINDINGS.json").read_text()):
            self.assertEqual(r.auth.sha256_file(r.ROOT/item["packaged_path"]),item["sha256"])

    def test_bounds_are_exact_over_all_missing_binary_completions(self):
        d=pd.DataFrame({"group_ever_kind_fair":[True]*7,
            "match_cell":["a","a","a","b","b","b","b"],
            "is_kind_role":[1,0,0,1,1,0,0],
            "returned":[True,True,False,False,True,True,False],
            "patron":[1,0,None,None,0,1,None],
            "outcome_status":["observed_outcome","observed_outcome","not_planned_in_august","queried_nonreturn","observed_outcome","observed_outcome","queried_nonreturn"]})
        result=r.missing_outcome_bounds(d)
        raw=[]; fe=[]
        for values in itertools.product([0,1],repeat=3):
            filled=d.copy()
            filled.loc[~filled["returned"],"patron"]=values
            filled["patron_pp"]=100.0*filled["patron"]
            treated=filled["is_kind_role"].astype(bool)
            raw.append(float(filled.loc[treated,"patron_pp"].mean()-filled.loc[~treated,"patron_pp"].mean()))
            # Explicit dummy-variable least squares, independent of the bound
            # formula and the inherited absorbed-OLS implementation.
            x=np.column_stack([np.ones(len(d)),d["is_kind_role"],(d["match_cell"]=="b").astype(int)])
            fe.append(float(np.linalg.lstsq(x,filled["patron_pp"],rcond=None)[0][1]))
        self.assertAlmostEqual(result["raw_lower_pp"],min(raw))
        self.assertAlmostEqual(result["raw_upper_pp"],max(raw))
        self.assertAlmostEqual(result["cell_fe_lower_pp"],min(fe))
        self.assertAlmostEqual(result["cell_fe_upper_pp"],max(fe))

    def test_full_new_design_and_estimation_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            args=SimpleNamespace(threads=2,memory_limit="512MB")
            panel,users=fixture.build_panel(groups=80)
            panel["utc_ms"]=1700000000000+np.arange(len(panel))*1000
            panel["game_id"]=[f"synthetic_game_{i}" for i in range(len(panel))]
            snapshot=fixture.build_snapshot(panel,users)
            paths=[]
            for month,chunk in panel.groupby("month"):
                path=root/(month+".parquet")
                chunk.to_parquet(path,index=False)
                paths.append({"month":str(month),"path":path})
            db=duckdb.connect()
            db.register("input",panel)
            db.execute("CREATE VIEW stage07 AS SELECT * FROM input")
            planner.build_chooser_summary(db)
            planner.build_matching(db)
            acquisition=root/"acquisition.parquet"
            db.execute(f"COPY acquisition_users TO {r.q(acquisition)} (FORMAT PARQUET)")
            target=db.execute("SELECT * FROM acquisition_users").fetchdf()
            # The old design metadata is intentionally stale, and one selected
            # new control has no snapshot row. Only new design fields may bind.
            snapshot["total_opps"]=999999
            snapshot["match_cell"]="obsolete_cell"
            primary_controls=db.execute("""SELECT a.username_norm FROM acquisition_users a JOIN chooser_summary k
                ON k.chooser_id=a.matched_kind_chooser_id WHERE a.acquisition_role='control' AND k.ever_kind_fair_state
                ORDER BY a.username_norm""").fetchall()
            missing_id=primary_controls[0][0]
            recovered=snapshot.loc[snapshot["username_norm"]==missing_id].copy()
            snapshot=snapshot.loc[snapshot["username_norm"]!=missing_id]
            snapshot_path=root/"snapshot.parquet"
            snapshot.to_parquet(snapshot_path,index=False)
            db.close()
            design=root/"design"
            design.mkdir()
            qa=r.build_design(design,args,{"month_records":paths},acquisition,snapshot_path,len(target))
            self.assertEqual(qa["history_mismatches"],0)
            db=duckdb.connect()
            frame=r.load_frames(db,design/"chooser_design_features_private.parquet",snapshot_path)
            db.close()
            self.assertEqual(len(frame),len(target))
            self.assertNotIn("obsolete_cell",set(frame["match_cell"]))
            self.assertEqual(frame["total_opps"].unique().tolist(),[36])
            missing_row=frame.loc[frame["username_norm"]==missing_id].iloc[0]
            self.assertFalse(missing_row["returned"])
            self.assertTrue(pd.isna(missing_row["patron"]))
            self.assertEqual(missing_row["outcome_status"],"not_planned_in_august")
            bounds=r.missing_outcome_bounds(frame)
            self.assertGreater(bounds["control_missing"],0)
            public=root/"public"
            support=r.auth.load_json(design/"preoutcome_support_receipt.json")
            result=r.main_models(frame,root/"state","synthetic",public,support)
            self.assertEqual(result["models"],34)
            corrected=r.corrected_date_models(frame,root/"state","synthetic",public)
            self.assertEqual(corrected["models"],4)
            # One synthetic newly queried control exercises the real append,
            # cache producer, outcome join and all ten supplemented fits.
            recovered["queried_at_utc"]=gap.GAP_OBSERVATION
            recovered["returned"]=True
            recovered["patron"]=True
            recovered["patron_field_present"]=True
            recovered["http_status"]=200
            recovered["patron_color"]=None
            supplement=root/"supplement.parquet"
            recovered.to_parquet(supplement,index=False)
            augmented=root/"augmented"
            augmented.mkdir()
            combined=augmented/"dated_combined_profiles_private.parquet"
            old_sha=r.auth.sha256_file(snapshot_path)
            with duckdb.connect() as db:
                qa=gap.combined_profiles(db,snapshot_path,supplement,combined,r.PROFILE_FEATURES)
            self.assertEqual(qa["returned"],1)
            r.build_design(augmented,args,{"month_records":paths},acquisition,combined,len(target))
            with duckdb.connect() as db:
                supplemented=gap.load_frame(db,augmented)
            now=supplemented.loc[supplemented["username_norm"]==missing_id].iloc[0]
            self.assertTrue(now["returned"])
            self.assertTrue(now["patron"])
            self.assertFalse(now["august_planned"])
            self.assertEqual(now["queried_at_utc"],gap.GAP_OBSERVATION)
            self.assertEqual(now["profile_observation_source"],"september_11_gap_fill")
            self.assertEqual(r.auth.sha256_file(snapshot_path),old_sha)
            old=frame.set_index("username_norm").drop(index=missing_id)
            new=supplemented.set_index("username_norm").loc[old.index]
            pd.testing.assert_frame_equal(old[["patron","queried_at_utc","total_opps","match_cell"]],
                new[["patron","queried_at_utc","total_opps","match_cell"]])
            supplemental_public=root/"supplemented_public"
            augmented_summary=gap.core_models(supplemented,root/"augmented_state","synthetic",supplemental_public)
            self.assertEqual(augmented_summary["models"],6)
            self.assertEqual(augmented_summary["corrected_date_models"],4)
            self.assertEqual(augmented_summary["primary_accounts"],result["primary_accounts"]+1)
            tightened=r.missing_outcome_bounds(supplemented)
            self.assertEqual(tightened["control_missing"],bounds["control_missing"]-1)
            self.assertLess(tightened["raw_upper_pp"]-tightened["raw_lower_pp"],bounds["raw_upper_pp"]-bounds["raw_lower_pp"])
            merged=root/"merged_results"
            gap.merge_public(merged,public,supplemental_public)
            comparison=pd.read_csv(merged/"CORE_PATRON_COMPARISON.csv")
            self.assertEqual(set(comparison["profile_cohort"]),{"august_only",gap.LABEL})
            self.assertEqual(comparison.groupby("profile_cohort")["model"].nunique().tolist(),[10,10])
            # Attempting to append that same account a second time must fail.
            with duckdb.connect() as db, self.assertRaises(RuntimeError):
                gap.combined_profiles(db,combined,supplement,root/"duplicate.parquet",r.PROFILE_FEATURES)
            # Exercise aggregate collection from the actual model outputs.
            sample={"status":"SYNTHETIC", "fingerprint":"SYNTHETIC", "panel_root":root,
                "authority":{"status":"SYNTHETIC","sample_name":"SYNTHETIC","report_sha256":"SYNTHETIC",
                    "main_predicate":"SYNTHETIC","rows":len(panel),"kind_draws":int(panel["kind_draw"].sum()),
                    "fair_rows":int(panel["fair_competitive"].sum()),"fair_kind_draws":int((panel["fair_competitive"]&panel["kind_draw"]).sum()),"months":2}}
            with contextlib.redirect_stdout(io.StringIO()):
                r.collect_report(root/"return",merged,{"synthetic":True},sample,{"synthetic":True},root/"transfer")
            archive=next((root/"transfer").glob("*.zip"))
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                manifest=next(n for n in z.namelist() if n.endswith("/REPORT_FILE_HASHES.tsv"))
                import csv
                for item in csv.DictReader(io.StringIO(z.read(manifest).decode()),delimiter="\t"):
                    data=z.read(archive.stem+"/"+item["relative_path"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(),item["sha256"])
                    self.assertFalse(item["relative_path"].endswith(".parquet"))
                    for username in target["username_norm"]:
                        self.assertNotIn(username.encode(),data)
            missing_dates=frame.loc[frame["returned"]&frame["seen_at_ms"].isna()]
            self.assertGreater(len(missing_dates),0)
            self.assertTrue(missing_dates["corrected_recency"].isna().all())
            # A resumed fit must recover its covariance, so the desert contrast
            # retains its off-diagonal term rather than summing marginal SEs.
            c=r.CheckpointCollector(root/"resume_test","synthetic")
            tiny=pd.DataFrame({"patron_pp":[10,0,30,10,40,50,0,20],"a":[1,0,1,0,1,0,1,0],
                "b":[1,1,0,0,1,0,0,1],"match_cell":["x"]*4+["y"]*4})
            fit1=c.run(tiny,name="contrast",regressors=["a","b"],standardize=[],differences=[("a","b","a_minus_b")])
            fit2=c.run(tiny,name="contrast",regressors=["a","b"],standardize=[],differences=[("a","b","a_minus_b")])
            np.testing.assert_array_equal(fit1.covariance,fit2.covariance)
            self.assertEqual(c.contrasts[0],c.contrasts[1])
            # Changed checkpoint bytes must be rejected before reuse.
            saved=root/"resume_test/contrast/fit.json"
            saved.write_text(saved.read_text()+" ")
            with self.assertRaises(RuntimeError):
                c.run(tiny,name="contrast",regressors=["a","b"],standardize=[],differences=[("a","b","a_minus_b")])

    def test_gap_membership_and_dates_fail_closed(self):
        coverage=[]; supplement=[]
        for role,planned,primary,count in [
            ("control",False,True,77),("control",False,False,45),
            ("control",True,True,100),("control",True,False,26),
            ("kind",True,True,30),("kind",True,False,7)]:
            for _ in range(count):
                user=f"synthetic_target_{len(coverage)}"
                row={"username_norm":user,"new_role":role,"new_match_cell":"test_cell",
                    "primary_fair_kind_group":primary,"august_planned":planned,"august_returned":False}
                coverage.append(row)
                supplement.append({**row,"returned":not planned,
                    "gap_reason":"queried_nonreturn" if planned else "not_planned_in_august",
                    "observation_source":"current_profile_gap_fill","august_outcome_recovered":False,
                    "queried_at_utc":gap.GAP_OBSERVATION,"request_count":3 if planned else 1})
        with tempfile.TemporaryDirectory() as temporary, duckdb.connect() as db:
            root=Path(temporary)
            a=root/"coverage.parquet"; b=root/"supplement.parquet"
            pd.DataFrame(coverage).to_parquet(a,index=False)
            pd.DataFrame(supplement).to_parquet(b,index=False)
            self.assertEqual(gap.validate_membership(db,a,b)["recovered_primary"],77)
            supplement[0]["primary_fair_kind_group"]=False
            pd.DataFrame(supplement).to_parquet(b,index=False)
            with self.assertRaises(RuntimeError):
                gap.validate_membership(db,a,b)


if __name__=="__main__":
    unittest.main(verbosity=2,buffer=True)
