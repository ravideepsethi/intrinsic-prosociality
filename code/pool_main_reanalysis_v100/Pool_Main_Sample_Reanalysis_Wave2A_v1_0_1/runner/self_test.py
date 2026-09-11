#!/usr/bin/env python3
"""Offline release checks; optionally run the full FEN pipeline on synthetic data."""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from runner import common
from runner.dynamics_preflight import source_inventory, support_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-fen-smoke", action="store_true")
    return parser.parse_args()


def run_command(argv: list[str], environment: dict[str, str]) -> None:
    completed = subprocess.run(
        argv,
        cwd=common.PACKAGE_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(completed.stdout, end="", flush=True)
    if completed.returncode:
        raise RuntimeError(f"Synthetic/self-test command exited {completed.returncode}: {argv}")


def syntax_inventory() -> int:
    count = 0
    for path in sorted(common.PACKAGE_ROOT.rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += 1
    return count


def dynamics_sql_smoke() -> None:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    with tempfile.TemporaryDirectory(prefix="pool_main_wave2a_dynamic_smoke_") as directory:
        root = Path(directory)
        frame = pd.DataFrame(
            {
                "game_id": [f"g{index}" for index in range(6)],
                "archive_ordinal": list(range(6)),
                "utc_ms": [1_700_000_000_000 + index * 1000 for index in range(6)],
                "api_last_move_at_ms": [
                    1_700_000_000_500 + index * 1000 for index in range(6)
                ],
                "chooser_username_norm": ["chooser"] * 6,
                "chooser_user_id": [10] * 6,
                "disconnected_username_norm": ["r0", "r0", "r1", "r2", "r3", "r4"],
                "disconnected_user_id": [20, 20, 21, 22, 23, 24],
                "fair_competitive": [True] * 6,
                "tournament_like_event": [False] * 6,
                "kind_draw": [True, False, True, False, False, False],
                "timeout_chooser_win": [False, True, False, True, True, True],
                "timeout_draw_no_mating_material": [False] * 6,
                "timeout_chooser_loss": [False] * 6,
                "ply_count": [5, 11, 7, 13, 9, 15],
            }
        )
        panel = root / "analysis_panel.parquet"
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), panel)
        result = support_counts(
            {"month_records": [{"path": panel}]},
            root / "spill",
            threads=1,
            memory_limit="1GB",
        )
        cohort = result["a3_first_fair_recipient"]
        if cohort["rows"] != 5 or cohort["invalid_arm_partition"] != 0:
            raise RuntimeError(f"Dynamics cohort SQL smoke test failed: {cohort}")
        if result["b1_repeat_granter"]["choosers"] != 1:
            raise RuntimeError("Dynamics B1 support SQL smoke test failed")


def fen_self_tests(full_smoke: bool) -> None:
    fen = common.PACKAGE_ROOT / "source/fen"
    code = fen / "code"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(common.PACKAGE_ROOT), str(code), environment.get("PYTHONPATH", "")])
    )
    dummy = common.PACKAGE_ROOT
    commands = (
        [str(code / "03_make_synthetic_fixture.py"), "--root", str(dummy), "--self-test"],
        [
            str(code / "00_build_position_design.py"),
            "--package-root", str(fen),
            "--project-root", str(dummy),
            "--private-root", str(dummy),
            "--public-root", str(dummy),
            "--self-test",
        ],
        [
            str(code / "01_run_equality_fen_audit.py"),
            "--package-root", str(fen),
            "--project-root", str(dummy),
            "--private-root", str(dummy),
            "--public-root", str(dummy),
            "--self-test",
        ],
        [
            str(code / "02_verify_equality_fen_audit.py"),
            "--package-root", str(fen),
            "--public-root", str(dummy),
            "--self-test",
        ],
    )
    for values in commands:
        run_command([sys.executable, "-B", "-u", *values], environment)
    if not full_smoke:
        return
    with tempfile.TemporaryDirectory(prefix="pool_main_wave2a_fen_smoke_") as directory:
        root = Path(directory)
        fixture = root / "fixture"
        private = root / "private"
        public = root / "public"
        run_command(
            [
                sys.executable,
                "-B",
                "-u",
                str(code / "03_make_synthetic_fixture.py"),
                "--root",
                str(fixture),
                "--rows",
                "24000",
            ],
            environment,
        )
        shared = [
            "--package-root", str(fen),
            "--project-root", str(fixture),
            "--private-root", str(private),
            "--public-root", str(public),
            "--synthetic",
        ]
        run_command(
            [sys.executable, "-B", "-u", str(code / "00_build_position_design.py"), *shared],
            environment,
        )
        run_command(
            [sys.executable, "-B", "-u", str(code / "01_run_equality_fen_audit.py"), *shared],
            environment,
        )
        run_command(
            [
                sys.executable,
                "-B",
                "-u",
                str(code / "02_verify_equality_fen_audit.py"),
                "--package-root",
                str(fen),
                "--public-root",
                str(public),
                "--synthetic",
            ],
            environment,
        )
        success = common.load_json(public / "_SUCCESS.json")
        if success.get("status") != "POOL_MAIN_EQUALITY_FEN_AUDIT_V200_OK":
            raise RuntimeError("Synthetic FEN completion status changed")


def crossing_self_test() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(common.PACKAGE_ROOT), environment.get("PYTHONPATH", "")])
    )
    environment["MPLBACKEND"] = "Agg"
    with tempfile.TemporaryDirectory(prefix="pool_main_wave2a_crossing_smoke_") as directory:
        root = Path(directory)
        fixture = root / "fixture"
        public = root / "public"
        private = root / "private"
        run_command(
            [
                sys.executable,
                "-B",
                "-u",
                "-m",
                "runner.make_crossing_fixture",
                "--root",
                str(fixture),
                "--rows",
                "48000",
            ],
            environment,
        )
        run_command(
            [
                sys.executable,
                "-B",
                "-u",
                "-m",
                "runner.crossing_audit",
                "--sample-root",
                str(fixture),
                "--public-root",
                str(public),
                "--private-root",
                str(private),
                "--threads",
                "2",
                "--memory-limit",
                "2GB",
                "--batch-rows",
                "8192",
                "--synthetic",
            ],
            environment,
        )
        run_command(
            [
                sys.executable,
                "-B",
                "-u",
                "-m",
                "runner.verify_crossing_audit",
                "--public-root",
                str(public),
            ],
            environment,
        )
        success = common.load_json(public / "_SUCCESS.json")
        verified = common.load_json(public / "_VERIFIED.json")
        if success.get("status") != "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_OK":
            raise RuntimeError("Synthetic crossing completion status changed")
        if verified.get("status") != "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_VERIFIED_OK":
            raise RuntimeError("Synthetic crossing verification status changed")


def main() -> int:
    args = parse_args()
    package = common.verify_package_manifest()
    common.verify_package_manifest(common.PACKAGE_ROOT / "source/fen")
    common.verify_runtime_dependencies()
    authority, report = common.verify_report_package()
    if common.sample_fingerprint(report, authority["report_sha256"]) != authority[
        "sample_fingerprint"
    ]:
        raise RuntimeError("Selected-sample fingerprint self-test failed")
    python_files = syntax_inventory()
    inventory = source_inventory()
    if inventory["status"] != "BUNDLED_DYNAMIC_SOURCE_INVENTORY_OK":
        raise RuntimeError("Bundled dynamics source inventory failed")
    dynamics_sql_smoke()
    crossing_self_test()
    fen_self_tests(args.full_fen_smoke)
    print(
        "POOL_MAIN_REANALYSIS_WAVE2A_SELF_TEST_OK "
        f"package_files={package['files']} python_files={python_files} "
        f"dynamic_sources={inventory['files']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
