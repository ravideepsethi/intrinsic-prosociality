#!/usr/bin/env python3
"""Collector and disclosure-boundary test for reference-demand v1.0.3."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
import zipfile

import collect_kindness_reference_demand_results_v103 as collector
import kindness_price_elasticity_common_v102 as common
import run_kindness_reference_demand_v103 as module


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="reference_demand_collector_test_") as temp:
        root = Path(temp)
        output = root / "output"
        package = root / "package"
        desktop = root / "desktop"
        output.mkdir()
        package.mkdir()
        (package / "README_FIRST.md").write_text("synthetic package\n", encoding="utf-8")
        headline = {
            "headline_object": "reference-dependent demand schedule, not one global elasticity",
            "global_signed_log_elasticity_status": "NOT_MATHEMATICALLY_DEFINED",
            "primary_loss_side_scalar_companion": {
                "model": module.PRIMARY_LOSS_MODEL,
                "estimate": -0.08,
                "ci95_low": -0.10,
                "ci95_high": -0.06,
            },
            "primary_zero_reference_companion": {
                "coefficient_percentage_points": 0.22,
                "ci95_low_pp": 0.18,
                "ci95_high_pp": 0.26,
            },
            "primary_full_schedule_companion": {
                "loss_magnitude_slope_pp_per_rating_point": -0.01,
                "positive_side_slope_pp_per_rating_point": 0.001,
            },
            "prior_v102_opportunity_cost_elasticity": {
                "elasticity_estimate": 0.1570280092407992
            },
            "claim_boundary": "synthetic noncausal boundary",
        }
        common.atomic_json(
            output / "_SUCCESS.json",
            {
                "status": "KINDNESS_REFERENCE_DEMAND_V103_OK",
                "headline": headline,
                "models_attempted": 7,
                "models_estimated": 6,
                "models_failed_retained": 1,
            },
        )
        module.write_report_manifest(output)
        pointer = root / "pointer.json"
        common.atomic_json(
            pointer,
            {
                "output_root": str(output),
                "package_root": str(package),
                "run_id": "20260826T000000Z",
            },
        )
        args = argparse.Namespace(
            execution_pointer=pointer,
            launch_log=None,
            desktop=desktop,
        )
        zip_path, sidecar, inspection = collector.execute(args)
        if not zip_path.is_file() or not sidecar.is_file():
            raise RuntimeError("Collector did not create authenticated bundle and sidecar")
        if inspection.get("loss_log_elasticity") != -0.08:
            raise RuntimeError("Collector inspection changed headline loss elasticity")
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            if any(name.lower().endswith(".parquet") for name in names):
                raise RuntimeError("Collector leaked Parquet into public result bundle")
            if "COLLECTION_MANIFEST.json" not in names:
                raise RuntimeError("Collector bundle lacks manifest")
        expected_digest = sidecar.read_text(encoding="utf-8").split()[0]
        if common.sha256_file(zip_path) != expected_digest:
            raise RuntimeError("Collector sidecar does not authenticate bundle")
    print("KINDNESS_REFERENCE_DEMAND_COLLECTOR_TEST_OK")


if __name__ == "__main__":
    main()
