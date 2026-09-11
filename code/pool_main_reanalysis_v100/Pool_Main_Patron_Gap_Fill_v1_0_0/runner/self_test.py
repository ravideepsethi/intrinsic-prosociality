"""Offline behavioral tests; no production authentication bypass or live calls."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner import fetch, run
from runner.normalizer import frozen as n
from source import pool_sample_common_v100 as auth


class FakeClock:
    def __init__(self):
        self.now = 1_800_000_000.0
        self.waits = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        assert 0 <= seconds <= 30
        self.waits.append(seconds)
        self.now += seconds


class FakeTransport:
    def __init__(self, clock, replies):
        self.clock, self.replies, self.calls = clock, iter(replies), []

    def __call__(self, users):
        self.calls.append((self.clock.time(), list(users)))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, tuple):
            return reply
        return 200, {}, json.dumps(reply).encode()


def target(user, role="control", reason="queried_nonreturn", primary=True):
    return {"username_norm": user, "new_role": role, "new_match_cell": "cell_x",
        "primary_fair_kind_group": primary, "gap_reason": reason}


class GapFillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = FakeClock()

    def fetch(self, users, replies):
        transport = FakeTransport(self.clock, replies)
        result = fetch.run_fetch(self.root / "requests", "config", users,
            transport=transport, clock=self.clock, log=lambda _: None)
        return result, transport

    def test_retry_only_omissions_keep_first_success_and_actual_dates(self):
        start = self.clock.time()
        state, transport = self.fetch(["alpha", "beta", "gamma"], [
            [{"id": "alpha", "patron": True}], [{"id": "beta"}], []])
        self.assertEqual([c[1] for c in transport.calls], [["alpha", "beta", "gamma"], ["beta", "gamma"], ["gamma"]])
        self.assertEqual([c[0]-start for c in transport.calls], [0, 60, 120])
        rows = fetch.supplement_rows([target("alpha", "kind"), target("beta"), target("gamma")], state)
        self.assertTrue(rows[0]["patron"])
        self.assertFalse(rows[1]["patron"])
        self.assertFalse(rows[1]["patron_field_present"])
        self.assertIsNone(rows[2]["patron"])
        self.assertFalse(rows[2]["returned"])
        self.assertEqual(rows[0]["queried_at_utc"], n.iso_from_epoch(start))
        self.assertEqual(rows[1]["queried_at_utc"], n.iso_from_epoch(start+60))
        self.assertTrue(all(r["august_outcome_recovered"] is False for r in rows))

    def test_completed_checkpoint_resume_makes_zero_network_requests(self):
        self.fetch(["alpha", "beta"], [[{"id": "beta"}, {"id": "alpha", "patron": True}]])
        state, transport = self.fetch(["alpha", "beta"], [])
        self.assertEqual(transport.calls, [])
        self.assertEqual(state["rounds"], 1)
        self.assertEqual(len(state["best"]), 2)

    def test_corrupt_raw_response_stops_before_network(self):
        self.fetch(["alpha"], [[{"id": "alpha"}]])
        body = self.root / "requests/attempt_000001/response_body.bin"
        body.write_bytes(b"[]")
        with self.assertRaisesRegex(fetch.FetchStopped, "hash differs"):
            self.fetch(["alpha"], [])

    def test_request_membership_is_authenticated(self):
        self.fetch(["alpha"], [[{"id": "alpha"}]])
        with self.assertRaisesRegex(fetch.FetchStopped, "frozen remaining-account set"):
            self.fetch(["beta"], [])

    def test_429_wait_persists_across_failed_invocation(self):
        transport = FakeTransport(self.clock, [(429, {"Retry-After": "90"}, b"limited")] * 4)
        with self.assertRaisesRegex(fetch.FetchStopped, "Transport attempts exhausted"):
            fetch.run_fetch(self.root / "requests", "config", ["alpha"],
                transport=transport, clock=self.clock, log=lambda _: None)
        self.assertTrue(all(b[0]-a[0] >= 90 for a, b in zip(transport.calls, transport.calls[1:])))
        previous = fetch.replay(self.root / "requests", "config", ["alpha"])["next_allowed"]
        _, resumed = self.fetch(["alpha"], [[{"id": "alpha"}]])
        self.assertGreaterEqual(resumed.calls[0][0], previous)

    def test_interrupted_post_gets_durable_recovery_wait(self):
        directory = self.root / "requests/attempt_000001"
        directory.mkdir(parents=True)
        start = self.clock.time()
        auth.atomic_json(directory / "REQUEST.json", {"config_sha256": "config", "usernames": ["alpha"],
            "round": 1, "started_epoch": start-20, "started_at_utc": n.iso_from_epoch(start-20)})
        (directory / "response_body.bin").write_bytes(b"uncommitted bytes")
        state, transport = self.fetch(["alpha"], [[{"id": "alpha"}]])
        self.assertGreaterEqual(transport.calls[0][0], start+60)
        self.assertEqual((directory / "uncommitted_response_body.bin").read_bytes(), b"uncommitted bytes")
        self.assertEqual(state["queries"]["alpha"], 2)

    def test_no_successful_http_never_imputes_patron_zero(self):
        transport = FakeTransport(self.clock, [TimeoutError()] * 4)
        with self.assertRaises(fetch.FetchStopped):
            fetch.run_fetch(self.root / "requests", "config", ["alpha"],
                transport=transport, clock=self.clock, log=lambda _: None)
        state = fetch.replay(self.root / "requests", "config", ["alpha"])
        row = fetch.supplement_rows([target("alpha")], state)[0]
        self.assertIsNone(row["patron"])
        self.assertIsNone(row["http_status"])
        self.assertIsNone(row["queried_at_utc"])
        self.assertEqual(row["request_count"], 4)

    def test_bad_payload_stops_duplicates_extras_and_string_flag(self):
        cases = [[{"id": "alpha"}, {"id": "alpha"}], [{"id": "unknown"}], [{"id": "alpha", "patron": "false"}]]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                fetch.decode(json.dumps(payload).encode(), ["alpha"], 1, "2026-09-11T00:00:00Z")

    def test_public_report_contains_counts_not_account_data(self):
        users = ["fixture_secret_alpha", "fixture_secret_beta"]
        state, _ = self.fetch(users, [[{"id": users[0], "profile": {"bio": "fixture_private_bio"}}], [], []])
        rows = fetch.supplement_rows([target(u) for u in users], state)
        output = self.root / "report"
        result = run.build_report(output, rows=rows, configuration={"target_count": 2}, config_sha="config",
            state=state, complete=True, private_files=[], elapsed=1.0)
        self.assertEqual(result["status"], "COMPLETE_WITH_UNAVAILABLE_ACCOUNTS")
        self.assertEqual(result["current_profiles_returned"], 1)
        for path in output.iterdir():
            content = path.read_text()
            for forbidden in users + ["fixture_private_bio", "raw_user_json", "patron_color"]:
                self.assertNotIn(forbidden, content)
        self.assertEqual(sum(r["still_unavailable"] for r in fetch.aggregate(rows) if r["scope"] == "all_target_groups"), 1)

    def test_source_and_report_bindings_and_exact_gap_decomposition(self):
        for binding in json.loads((run.ROOT / "authority/SOURCE_BINDINGS.json").read_text()):
            self.assertEqual(auth.sha256_file(run.ROOT / binding["packaged_path"]), binding["sha256"])
        run.bundled_authority()
        auth.verify_report_package()
        rows = []
        for role, reason, primary, count in [
            ("control", "not_planned_in_august", True, 77), ("control", "not_planned_in_august", False, 45),
            ("control", "queried_nonreturn", True, 100), ("control", "queried_nonreturn", False, 26),
            ("kind", "queried_nonreturn", True, 30), ("kind", "queried_nonreturn", False, 7)]:
            for _ in range(count):
                rows.append(target(f"fixture{len(rows)}", role, reason, primary))
        run.validate_target_counts(rows)
        rows[0]["primary_fair_kind_group"] = False
        with self.assertRaises(RuntimeError):
            run.validate_target_counts(rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
