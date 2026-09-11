#!/usr/bin/env python3
"""Authenticate the selected panel and write a compact Wave-1 input receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from runner import common


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--hash-workers", type=int, default=8)
    parser.add_argument("--skip-full-hash", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    if not 1 <= args.hash_workers <= 10:
        raise SystemExit("--hash-workers must be between 1 and 10")
    runtime = common.verify_runtime_dependencies()
    auth = common.authenticate_sample(
        args.sample_root,
        verify_hashes=not args.skip_full_hash,
        hash_workers=args.hash_workers,
    )
    receipt = {
        "status": "POOL_MAIN_REANALYSIS_WAVE1_PREFLIGHT_OK",
        "created_at_utc": common.utc_now(),
        "wave_version": common.WAVE_VERSION,
        "sample_authority": common.compact_sample_lineage(auth),
        "sample_success_sha256": auth["success_sha256"],
        "schema_columns": len(auth["schema"]),
        "monthly_files_authenticated": len(auth["month_records"]),
        "full_monthly_hashes_recomputed": auth["hashes_recomputed"],
        "runtime": runtime,
        "guardrails": {
            "old_full_panel_outputs_are_current": False,
            "old_sample_dependent_private_caches_may_be_reused": False,
            "full_histories_may_be_used_as_upstream_history": True,
            "literal_immediate_rematches_certified": False,
        },
    }
    common.atomic_json(args.receipt, receipt)
    print(receipt["status"], flush=True)
    print(f"sample_fingerprint: {auth['fingerprint']}", flush=True)
    print(f"rows: {auth['authority']['rows']:,}", flush=True)
    print(f"kind_draws: {auth['authority']['kind_draws']:,}", flush=True)
    print(f"fair_rows: {auth['authority']['fair_rows']:,}", flush=True)
    print(
        "scope_note: observed predecessor non-adjacency is certified; literal end-to-start rematch timing is not",
        flush=True,
    )
    return receipt


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
