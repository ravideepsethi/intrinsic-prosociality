#!/usr/bin/env python3
"""Rebuild the rating-gap / expected-score / K-RD decomposition and plots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runner import common


STATUS = "POOL_MAIN_RATING_GAP_KRD_DECOMPOSITION_OK"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--hash-workers", type=int, default=8)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    if not 1 <= args.threads <= 10:
        raise SystemExit("--threads must be between 1 and 10")
    auth = common.authenticate_sample(
        args.sample_root, verify_hashes=True, hash_workers=args.hash_workers
    )
    output = args.output_root.resolve()
    settings_path = output / "settings.json"
    if settings_path.is_file():
        saved = common.verify_lineaged_json(settings_path, STATUS, auth["fingerprint"])
        required = [
            output / "mechanical_validation.csv",
            output / "fe_model_coefficients.csv",
            output / "rating_gap_curves.csv",
            output / "private_cache/rating_gap_krd_derived_private.parquet",
        ]
        if not all(path.is_file() and path.stat().st_size > 0 for path in required):
            raise RuntimeError("Existing K/RD completion receipt has missing outputs")
        return saved
    if output.exists():
        raise RuntimeError(
            f"Incomplete K/RD output exists; preserve it for diagnosis and choose a fresh root: {output}"
        )

    source_path = common.PACKAGE_ROOT / "source/structural/rating_gap_krd_decomposition.py"
    render_path = common.PACKAGE_ROOT / "source/structural/render_rating_gap_krd.py"
    source = common.source_record(source_path, "surface_package_v1.0.0")
    module = common.load_source_module(source_path, "pool_main_krd_source")
    module.ROOT = auth["sample_root"].parents[2]
    module.PANEL = auth["panel_root"]
    module.EXPECTED_ROWS = auth["authority"]["rows"]
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            str(source_path),
            "--out-root",
            str(output),
            "--threads",
            str(args.threads),
            "--memory-limit",
            args.memory_limit,
        ]
        module.main()
    finally:
        sys.argv = old_argv

    render = common.load_source_module(render_path, "pool_main_krd_render")
    try:
        sys.argv = [str(render_path), "--out-root", str(output)]
        render.main()
    finally:
        sys.argv = old_argv

    saved = common.load_json(settings_path)
    if saved.get("status") != "RATING_GAP_KRD_DECOMPOSITION_OK":
        raise RuntimeError("K/RD source producer did not complete")
    saved["upstream_producer_status"] = saved["status"]
    saved["status"] = STATUS
    saved["sample_authority"] = common.compact_sample_lineage(auth)
    saved["source_program"] = source
    saved["render_program"] = common.source_record(render_path, "surface_package_v1.0.0")
    saved["adapter"] = common.source_record(Path(__file__).resolve(), "pool_main_adapter")
    saved["scientific_status"] = (
        "exploratory diagnostic re-estimated on the selected pool/observed-nonadjacent sample"
    )
    common.atomic_json(settings_path, saved)
    print(STATUS, flush=True)
    return saved


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
