#!/usr/bin/env python3
"""Run the Parquet-first nonparametric relative-strength closure on new K/RD data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runner import common
from runner.run_krd import STATUS as KRD_STATUS


STATUS = "POOL_MAIN_RATING_GAP_NONPARAMETRIC_CLOSURE_V110_OK"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--krd-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--prep-threads", type=int, default=8)
    parser.add_argument("--prep-memory-limit", default="12GB")
    parser.add_argument("--model-workers", type=int, default=4)
    parser.add_argument("--worker-threads", type=int, default=1)
    parser.add_argument("--worker-memory-limit", default="2.5GB")
    parser.add_argument("--hash-workers", type=int, default=8)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    if not 1 <= args.prep_threads <= 10:
        raise SystemExit("--prep-threads must be between 1 and 10")
    if not 1 <= args.model_workers <= 10 or not 1 <= args.worker_threads <= 10:
        raise SystemExit("Model workers and worker threads must be between 1 and 10")
    auth = common.authenticate_sample(
        args.sample_root, verify_hashes=False, hash_workers=args.hash_workers
    )
    krd_settings = args.krd_root.resolve() / "settings.json"
    common.verify_lineaged_json(krd_settings, KRD_STATUS, auth["fingerprint"])
    output = args.output_root.resolve()
    settings_path = output / "settings.json"
    if settings_path.is_file():
        saved = common.verify_lineaged_json(settings_path, STATUS, auth["fingerprint"])
        if not (output / "fe_nonparametric_curves.parquet").is_file():
            raise RuntimeError("Existing nonparametric receipt has missing outputs")
        return saved

    source_path = (
        common.PACKAGE_ROOT
        / "source/structural/rating_gap_nonparametric_closure_parallel.py"
    )
    render_path = (
        common.PACKAGE_ROOT
        / "source/structural/render_rating_gap_nonparametric_closure.py"
    )
    source = common.source_record(source_path, "rating_gap_nonparametric_v1.1.0")
    module = common.load_source_module(
        source_path, "rating_gap_nonparametric_closure_parallel"
    )
    module.ROOT = auth["sample_root"].parents[2]
    module.SOURCE_ROOT = args.krd_root.resolve()
    module.SOURCE_SETTINGS = krd_settings
    module.SOURCE_CACHE = args.krd_root.resolve() / "private_cache/rating_gap_krd_derived_private.parquet"
    module.EXPECTED_ROWS = auth["authority"]["rows"]
    module.EXPECTED_SOURCE_STATUS = KRD_STATUS
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            str(source_path),
            "--out-root",
            str(output),
            "--prep-threads",
            str(args.prep_threads),
            "--prep-memory-limit",
            args.prep_memory_limit,
            "--model-workers",
            str(args.model_workers),
            "--worker-threads",
            str(args.worker_threads),
            "--worker-memory-limit",
            args.worker_memory_limit,
        ]
        module.main()
    finally:
        sys.argv = old_argv

    render = common.load_source_module(render_path, "pool_main_nonparametric_render")
    try:
        sys.argv = [str(render_path), "--out-root", str(output)]
        render.main()
    finally:
        sys.argv = old_argv

    saved = common.load_json(settings_path)
    if saved.get("status") != "RATING_GAP_NONPARAMETRIC_CLOSURE_V110_OK":
        raise RuntimeError("Nonparametric source producer did not complete")
    saved["upstream_producer_status"] = saved["status"]
    saved["status"] = STATUS
    saved["sample_authority"] = common.compact_sample_lineage(auth)
    saved["source_program"] = source
    saved["render_program"] = common.source_record(
        render_path, "rating_gap_nonparametric_v1.1.0"
    )
    saved["adapter"] = common.source_record(Path(__file__).resolve(), "pool_main_adapter")
    common.atomic_json(settings_path, saved)
    print(STATUS, flush=True)
    return saved


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
