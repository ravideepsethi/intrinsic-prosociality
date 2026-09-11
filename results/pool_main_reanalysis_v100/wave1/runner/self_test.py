#!/usr/bin/env python3
"""Offline release and estimator checks; never opens the production panel."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from runner import common


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-controlled-smoke",
        action="store_true",
        help="Also fit and render the controlled model on its deterministic synthetic cache.",
    )
    return parser.parse_args()


def verify_sources() -> None:
    authority = common.load_json(common.PACKAGE_ROOT / "authority/SOURCE_AUTHORITY.json")
    if authority.get("status") != "POOL_MAIN_REANALYSIS_WAVE1_SOURCE_AUTHORITY_OK":
        raise RuntimeError("Unexpected source-authority status")
    for record in authority.get("sources", []):
        path = common.PACKAGE_ROOT / record["relative_path"]
        if not path.is_file() or common.sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Frozen source checksum failed: {path}")


def numerical_self_tests() -> None:
    stage08_path = common.PACKAGE_ROOT / "source/core/08_make_core_paper_results.py"
    stage09_path = common.PACKAGE_ROOT / "source/core/09_build_panel_robustness.py"
    nonparam_path = (
        common.PACKAGE_ROOT
        / "source/structural/rating_gap_nonparametric_closure_parallel.py"
    )
    stage08 = common.load_source_module(stage08_path, "wave1_selftest_stage08")
    stage08.run_numerical_self_test()
    stage09 = common.load_source_module(stage09_path, "wave1_selftest_stage09")
    stage09.run_self_test()
    nonparam = common.load_source_module(
        nonparam_path, "rating_gap_nonparametric_closure_parallel"
    )
    nonparam.self_test()


def controlled_smoke_test() -> None:
    engine_path = common.PACKAGE_ROOT / "source/controlled/reference_price_model_v110.py"
    renderer_path = (
        common.PACKAGE_ROOT / "source/controlled/controlled_reference_price_figure.py"
    )
    engine = common.load_source_module(engine_path, "reference_price_model_v110")
    renderer = common.load_source_module(
        renderer_path, "controlled_reference_price_figure"
    )
    if renderer.ENGINE_SHA256 != common.sha256_file(engine_path):
        raise RuntimeError("Controlled renderer and frozen model engine disagree")
    old_argv = sys.argv[:]
    with tempfile.TemporaryDirectory(prefix="pool_main_wave1_smoke_") as directory:
        root = Path(directory)
        model = root / "model"
        private = root / "private"
        figure = root / "figure"
        scratch = root / "scratch"
        try:
            sys.argv = [
                str(engine_path),
                "--out",
                str(model),
                "--private",
                str(private),
                "--threads",
                "2",
                "--memory",
                "2GB",
                "--batch-rows",
                "8192",
                "--smoke-test",
            ]
            if engine.main() != 0:
                raise RuntimeError("Controlled v1.1.0 synthetic smoke run failed")
            sys.argv = [
                str(renderer_path),
                "--source-run",
                str(model),
                "--source-private",
                str(private),
                "--out",
                str(figure),
                "--scratch",
                str(scratch),
                "--threads",
                "2",
                "--memory",
                "2GB",
                "--batch-rows",
                "8192",
                "--synthetic-validation",
            ]
            if renderer.main() != 0:
                raise RuntimeError("Controlled v1.1.1 synthetic render failed")
            receipt = common.load_json(figure / "receipts/completion_receipt.json")
            if receipt.get("status") != "CONTROLLED_REFERENCE_PRICE_FIX_COMPLETE":
                raise RuntimeError("Controlled synthetic completion receipt is invalid")
        finally:
            sys.argv = old_argv


def main() -> int:
    args = parse_args()
    common.verify_runtime_dependencies()
    authority, report = common.verify_report_package()
    fingerprint = common.sample_fingerprint(report, authority["report_sha256"])
    if fingerprint != authority["sample_fingerprint"]:
        raise RuntimeError("Sample fingerprint self-test failed")
    verify_sources()
    numerical_self_tests()
    if args.full_controlled_smoke:
        controlled_smoke_test()
    print("POOL_MAIN_REANALYSIS_WAVE1_SELF_TEST_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
