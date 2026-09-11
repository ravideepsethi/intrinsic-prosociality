"""Behavioral gates for new matches, profile missingness, and resumable output."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from runner import run as r


def panel_rows():
    result = []
    assignments = [("kind_a", True, True), ("kind_b", True, True)]
    assignments += [(f"control_{i}", False, True) for i in range(7)]
    assignments += [("worse_kind", True, False), ("worse_control", False, False)]
    for i, (name, kind, fair) in enumerate(assignments):
        result.append({"chooser_username_norm": name, "kind_draw": kind, "fair_competitive": fair,
            "clearly_worse": not fair, "excluded_middle": False, "api_speed": "Blitz",
            "chooser_elo": 1500.0, "chooser_draw_payoff_v2": -0.5,
            "chooser_win_premium_v2": 1.0, "tournament_like_event": False,
            "utc_ms": 1700000000000+i, "month": "2023-11", "game_id": f"game{i}"})
    return result


class RebuildTests(unittest.TestCase):
    def test_original_planner_and_bundled_sample_authority(self):
        r.planner.self_test()
        authority, report = r.auth.verify_report_package()
        self.assertEqual(authority["rows"], 41534331)
        self.assertEqual(len(report["panel_outputs"]), 24)
        bindings = json.loads((r.ROOT / "authority/SOURCE_BINDINGS.json").read_text())
        for binding in bindings:
            self.assertEqual(r.auth.sha256_file(r.ROOT / binding["packaged_path"]), binding["sha256"])

    def test_rebuild_missingness_and_reusable_checkpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            panel = root / "panel.parquet"
            pq.write_table(pa.Table.from_pylist(panel_rows()), panel)
            args = SimpleNamespace(threads=2, memory_limit="256MB")
            expected = {"rows": 11, "kind_draws": 3, "fair_rows": 9, "fair_kind_draws": 2,
                "choosers": 11, "fair_choosers": 9, "fair_kind_choosers": 2}
            sample = {"month_records": [{"path": panel}], "authority": expected}
            summary, sr = r.checkpoint(root, "summary", "test", lambda d: r.run_summary(d, args, sample))
            self.assertEqual(sr["summary"]["any_kind_choosers"], 3)
            summary_path = summary / "chooser_summary_private.parquet"
            matches, mr = r.checkpoint(root, "matches", "test", lambda d: r.run_matching(d, args, summary_path))
            self.assertEqual(mr["summary"]["selected_controls"], 7)
            self.assertEqual(mr["summary"]["exact_three_groups"], 2)
            db = duckdb.connect()
            db.execute(f"CREATE VIEW chooser_summary AS SELECT * FROM read_parquet({r.q(summary_path)})")
            db.execute(f"CREATE VIEW acquisition_users AS SELECT * FROM read_parquet({r.q(matches/'acquisition_users_private.parquet')})")
            pairs = r.records(db, f"SELECT * FROM read_parquet({r.q(matches/'matching_pairs_private.parquet')})")
            # Independent implementation of the frozen hash-rank round robin.
            seed = r.planner.DESIGN_SEED
            kinds = sorted(["kind_a", "kind_b"], key=lambda s: (hashlib.sha256(f"{seed}|kind|{s}".encode()).hexdigest(), s))
            controls = sorted([f"control_{i}" for i in range(7)], key=lambda s: (hashlib.sha256(f"{seed}|control|{s}".encode()).hexdigest(), s))
            expected_pairs = {(kinds[i % 2], c, i//2+1) for i, c in enumerate(controls[:6])}
            actual = {(p["kind_chooser_id"], p["control_chooser_id"], p["control_slot"]) for p in pairs if p["kind_ever_fair_kind"]}
            self.assertEqual(actual, expected_pairs)
            users = r.records(db, "SELECT * FROM acquisition_users ORDER BY username_norm")
            missing_id, nonreturn_id, former_kind_id = controls[:3]
            profiles = []
            for u in users:
                if u["username_norm"] == missing_id:
                    continue
                former_kind = u["username_norm"] == former_kind_id
                profiles.append({"username_norm": u["username_norm"], "returned": u["username_norm"] != nonreturn_id,
                    "acquisition_role": "kind" if former_kind else u["acquisition_role"],
                    "match_cell": u["match_cell"],
                    "matched_kind_chooser_id": u["username_norm"] if former_kind else u["matched_kind_chooser_id"],
                    "control_slot": 0 if former_kind else u["control_slot"]})
            snapshot = root / "snapshot.parquet"
            pq.write_table(pa.Table.from_pylist(profiles), snapshot)
            # There is deliberately no Patron outcome column in this fixture.
            r.load_profile_membership(db, snapshot, certify=False)
            result = r.build_coverage(db)
            gate = result["gates"]["primary_fair_kind_groups"]
            self.assertEqual(gate["unplanned_target_accounts"], 1)
            self.assertEqual(gate["planned_nonreturns"], 1)
            self.assertEqual(gate["status"], "BLOCKED_INCOMPLETE_AUGUST_PROFILE_COVERAGE")
            self.assertEqual(sum(x["formerly_kind_now_control"] for x in result["coverage"] if x["scope"] == "primary_fair_kind_groups"), 1)
            db.close()
            # Execute the actual coverage checkpoint and report writer on small
            # data, replacing only the fixed full-snapshot row-count assertion.
            original_loader = r.load_profile_membership
            with patch.object(r, "load_profile_membership", side_effect=lambda db, path: original_loader(db, path, certify=False)):
                covered, cr = r.checkpoint(root, "coverage", "test", lambda d: r.run_coverage(d, args, summary_path, matches, snapshot))
            aggregate = r.auth.load_json(covered / "aggregate_coverage.json")
            sample["authority"].update({"status": "SYNTHETIC", "sample_name": "SYNTHETIC", "report_sha256": "SYNTHETIC", "main_predicate": "SYNTHETIC", "months": 1})
            sample.update({"status": "SYNTHETIC", "fingerprint": "SYNTHETIC", "panel_root": root})
            public = root / "report"
            public.mkdir()  # Regression: report targets may already exist.
            names = r.make_report(public, {"synthetic": True}, sample, {"summary": sr, "matches": mr, "coverage": cr}, aggregate, 1.0)
            for name in names:
                text = (public/name).read_text()
                for account in [u["username_norm"] for u in users]:
                    self.assertNotIn('"'+account+'"', text)
                    self.assertNotIn('\t'+account+'\t', text)
            # Verify reuse, never recomputation, and fail closed if altered.
            _, reused = r.checkpoint(root, "summary", "test", lambda _: self.fail("must reuse"))
            self.assertEqual(sr, reused)
            with summary_path.open("ab") as stream:
                stream.write(b"corruption")
            with self.assertRaises(RuntimeError):
                r.read_checkpoint(summary, "test")

    def test_profile_complete_does_not_impute_nonreturns(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = duckdb.connect()
            db.register("input", pa.Table.from_pylist(panel_rows()))
            db.execute("CREATE VIEW stage07 AS SELECT * FROM input")
            r.planner.build_chooser_summary(db)
            r.planner.build_matching(db)
            users = r.records(db, "SELECT * FROM acquisition_users")
            profiles = [{"username_norm": u["username_norm"], "returned": u["acquisition_role"] == "kind",
                "acquisition_role": u["acquisition_role"], "match_cell": u["match_cell"],
                "matched_kind_chooser_id": u["matched_kind_chooser_id"], "control_slot": u["control_slot"]} for u in users]
            path = root / "snapshot.parquet"
            pq.write_table(pa.Table.from_pylist(profiles), path)
            r.load_profile_membership(db, path, certify=False)
            gate = r.build_coverage(db)["gates"]["primary_fair_kind_groups"]
            self.assertEqual(gate["status"], "PASS_PLANNED_MEMBERSHIP_ONLY")
            self.assertEqual(gate["planned_nonreturns"], 6)
            self.assertFalse(gate["models_estimated"])
            db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
