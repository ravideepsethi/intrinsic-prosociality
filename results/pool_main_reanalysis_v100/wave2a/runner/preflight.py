#!/usr/bin/env python3
"""Authenticate the selected sample, Wave-1 authorities, code, and resources."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from runner import common
from runner.dynamics_preflight import authenticate_wave1


STATUS = "POOL_MAIN_REANALYSIS_WAVE2A_PREFLIGHT_OK"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave1-public", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--min-free-gb", type=float, default=80.0)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    package = common.verify_package_manifest()
    fen_package = common.verify_package_manifest(common.PACKAGE_ROOT / "source/fen")
    runtime = common.verify_runtime_dependencies()
    project = args.project_root.expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError(f"Project root is unavailable: {project}")
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    expected_sample = (
        project / auth["authority"]["default_sample_root_relative"]
    ).resolve()
    if auth["sample_root"].resolve() != expected_sample:
        raise RuntimeError(
            "The FEN authority contract requires the certified sample at "
            f"{expected_sample}; observed {auth['sample_root']}"
        )
    wave1_authority = common.load_json(common.PACKAGE_ROOT / "authority/WAVE1_AUTHORITY.json")
    if auth["success_sha256"] != wave1_authority["sample_success_sha256"]:
        raise RuntimeError("Selected-sample success receipt SHA-256 mismatch")
    wave1 = authenticate_wave1(
        project,
        args.wave1_public.expanduser().resolve(),
        auth["fingerprint"],
    )
    if wave1["status"] != "POOL_MAIN_WAVE1_INPUTS_AUTHENTICATED_OK":
        raise RuntimeError("Wave-1 Stage 08/09 authorities are unavailable or changed")
    private = args.private_base.expanduser().resolve()
    private.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(private).free / 1024**3
    if free_gb < args.min_free_gb:
        raise RuntimeError(
            f"Insufficient free space: {free_gb:.1f} GiB available at {private}; "
            f"require at least {args.min_free_gb:.1f} GiB"
        )
    result = {
        "status": STATUS,
        "created_at_utc": common.utc_now(),
        "package": package,
        "fen_package": fen_package,
        "runtime": runtime,
        "sample_authority": common.compact_sample_lineage(auth),
        "sample_success_sha256": auth["success_sha256"],
        "monthly_files_footer_and_size_authenticated": len(auth["month_records"]),
        "full_monthly_hashes": "performed once by outcome-blind FEN design stage",
        "wave1": wave1,
        "resources": {
            "private_base": str(private),
            "free_gb": free_gb,
            "minimum_free_gb": args.min_free_gb,
        },
        "scope": {
            "recomputed_in_wave2a": [
                "equality/FEN commonness audit",
                "engine-zero placebo-knot audit",
            ],
            "inventoried_not_reestimated": [
                "A1/A3/B1 dynamics",
                "repeat-dyad and second-wave dynamics",
                "Campaign and targeted-memory dynamics",
                "chooser-leniency analyses",
            ],
            "old_sample_dependent_dynamic_caches_current": False,
        },
    }
    common.atomic_json(args.receipt.expanduser().resolve(), result)
    print(STATUS, flush=True)
    return result


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
