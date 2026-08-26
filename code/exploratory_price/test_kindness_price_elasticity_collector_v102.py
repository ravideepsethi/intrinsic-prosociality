#!/usr/bin/env python3
"""Synthetic integration test for the public aggregate collector."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
import zipfile

import collect_kindness_price_elasticity_results_v102 as collector
import kindness_price_elasticity_common_v102 as common
import run_kindness_price_elasticity_v102 as runner


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="kindness_elasticity_collector_") as temporary:
        root = Path(temporary)
        output = root / "output" / "TEST123"
        output.mkdir(parents=True)
        package = Path(__file__).resolve().parents[2]
        common.atomic_json(
            output / "_SUCCESS.json",
            {
                "status": "KINDNESS_PRICE_ELASTICITY_V102_OK",
                "models_attempted": 3,
                "models_estimated": 2,
                "models_failed_retained": 1,
                "primary": {
                    "primary_model": "synthetic_primary",
                    "elasticity_estimate": -0.12,
                    "elasticity_ci95_low": -0.2,
                    "elasticity_ci95_high": -0.04,
                    "direction": "negative",
                    "claim_boundary": "associational",
                },
            },
        )
        common.atomic_json(output / "model_attempts.json", [{"status": "FAILED_RETAINED"}])
        runner.write_report_manifest(output)
        pointer = root / "pointer.json"
        common.atomic_json(
            pointer,
            {
                "output_root": str(output),
                "package_root": str(package),
                "run_id": "TEST123",
            },
        )
        log = root / "launcher.log"
        common.atomic_text(log, "synthetic launcher log\n")
        desktop = root / "desktop"
        zip_path, sidecar, inspection = collector.execute(
            argparse.Namespace(
                execution_pointer=pointer,
                launch_log=log,
                desktop=desktop,
            )
        )
        if not zip_path.is_file() or not sidecar.is_file() or not inspection["scientific_success"]:
            raise RuntimeError("Synthetic collector did not create authenticated outputs")
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            if "COLLECTION_MANIFEST.json" not in names:
                raise RuntimeError("Synthetic result ZIP lacks its collection manifest")
            if any(name.lower().endswith(".parquet") for name in names):
                raise RuntimeError("Synthetic collector leaked a Parquet file")
    print("KINDNESS_PRICE_ELASTICITY_COLLECTOR_TEST_OK", flush=True)


if __name__ == "__main__":
    main()
