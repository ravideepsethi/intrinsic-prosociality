#!/usr/bin/env python3
"""Verify and package disclosure-safe Wave-2A results for return."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from runner import common
from runner.dynamics_preflight import authenticate_wave1


FEN_STATUS = "POOL_MAIN_EQUALITY_FEN_AUDIT_V200_OK"
CROSSING_STATUS = "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_OK"
CROSSING_VERIFY_STATUS = "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_VERIFIED_OK"
DYNAMIC_STATUSES = {
    "POOL_MAIN_WAVE2B_PREFLIGHT_READY",
    "POOL_MAIN_WAVE2B_PREFLIGHT_BLOCKED",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave1-public", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--transfer-root", type=Path, required=True)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    common.verify_package_manifest()
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    fingerprint = auth["fingerprint"]
    public = args.public_base.expanduser().resolve()
    private = args.private_base.expanduser().resolve()
    fen = public / "equality_fen"
    fen_success_path = fen / "_SUCCESS.json"
    if not fen_success_path.is_file():
        raise RuntimeError("FEN/equality completion receipt is missing")
    fen_success = common.load_json(fen_success_path)
    if fen_success.get("status") != FEN_STATUS:
        raise RuntimeError("FEN/equality completion status changed")
    if fen_success.get("sample_fingerprint") != fingerprint:
        raise RuntimeError("FEN/equality output belongs to another sample")

    fen_code = common.PACKAGE_ROOT / "source/fen/code"
    fen_common = common.load_source_module(
        fen_code / "equality_fen_common.py", "wave2a_collect_fen_common"
    )
    fen_common.verify_report_manifest(fen, fen / "report_file_hashes.tsv")
    fen_privacy = fen_common.privacy_scan_public_output(fen)

    crossing = public / "crossing_default_audit"
    crossing_success = common.load_json(crossing / "_SUCCESS.json")
    crossing_verified = common.load_json(crossing / "_VERIFIED.json")
    if crossing_success.get("status") != CROSSING_STATUS:
        raise RuntimeError("Crossing/default decomposition completion status changed")
    if crossing_verified.get("status") != CROSSING_VERIFY_STATUS:
        raise RuntimeError("Crossing/default decomposition verification status changed")
    if (crossing_success.get("sample_authority") or {}).get("fingerprint") != fingerprint:
        raise RuntimeError("Crossing/default decomposition belongs to another sample")
    if crossing_verified.get("sample_fingerprint") != fingerprint:
        raise RuntimeError("Crossing verifier belongs to another sample")
    crossing_privacy = common.privacy_scan(crossing)

    dynamics_path = public / "DYNAMICS_REBUILD_PREFLIGHT.json"
    if not dynamics_path.is_file():
        raise RuntimeError("Dynamics rebuild inventory receipt is missing")
    dynamics = common.load_json(dynamics_path)
    if dynamics.get("status") not in DYNAMIC_STATUSES:
        raise RuntimeError("Dynamics rebuild inventory status changed")
    if (dynamics.get("sample_authority") or {}).get("fingerprint") != fingerprint:
        raise RuntimeError("Dynamics inventory belongs to another sample")
    wave1 = authenticate_wave1(
        Path(auth["authority"]["default_project_root"]),
        args.wave1_public.expanduser().resolve(),
        fingerprint,
    )
    if wave1["status"] != "POOL_MAIN_WAVE1_INPUTS_AUTHENTICATED_OK":
        raise RuntimeError("Wave-1 authorities changed before collection")

    transfer = args.transfer_root.expanduser().resolve()
    transfer.mkdir(parents=True, exist_ok=True)
    run_id = common.utc_now().replace("-", "").replace(":", "")
    name = f"POOL_MAIN_REANALYSIS_WAVE2A_RESULTS_{run_id}"
    archive = transfer / f"{name}.zip"
    sidecar = transfer / f"{name}.zip.sha256"
    if archive.exists() or sidecar.exists():
        raise RuntimeError(f"Transfer destination already exists: {archive}")

    temporary_parent = Path(tempfile.mkdtemp(prefix="pool_main_wave2a_transfer_", dir=transfer))
    staging = temporary_parent / name
    try:
        staging.mkdir()
        modules = staging / "modules"
        modules.mkdir()
        common.copytree_filtered(fen, modules / "equality_fen")
        common.copytree_filtered(crossing, modules / "crossing_default_audit")
        for filename in (
            "PREFLIGHT.json",
            "DYNAMICS_REBUILD_PREFLIGHT.json",
            "WAVE2A_RUN_STATUS.json",
            "RUN_COMMAND.txt",
        ):
            source = public / filename
            if source.is_file():
                shutil.copy2(source, staging / filename)
        logs = public / "_logs"
        if logs.is_dir():
            common.copytree_filtered(logs, staging / "logs")
        for directory in ("source", "runner", "authority", "evidence"):
            common.copytree_filtered(
                common.PACKAGE_ROOT / directory, staging / directory
            )
        for filename in (
            "README_FIRST.md",
            "COMMENT_REVIEW_AND_V101_AMENDMENT.md",
            "WAVE1_AUTHENTICATED_REVIEW.md",
            "ANALYSIS_RESET_LEDGER.md",
            "ANALYSIS_RESET_LEDGER.json",
            "requirements.lock.txt",
            "PACKAGE_MANIFEST.sha256",
        ):
            source = common.PACKAGE_ROOT / filename
            if source.is_file():
                shutil.copy2(source, staging / filename)

        summary = {
            "status": "POOL_MAIN_REANALYSIS_WAVE2A_TRANSFER_OK",
            "created_at_utc": common.utc_now(),
            "sample_authority": common.compact_sample_lineage(auth),
            "completed_modules": {
                "equality_fen": FEN_STATUS,
                "crossing_default_audit": CROSSING_STATUS,
                "crossing_default_verification": CROSSING_VERIFY_STATUS,
                "dynamics_rebuild_inventory": dynamics["status"],
            },
            "fen_public_privacy": fen_privacy,
            "crossing_public_privacy": crossing_privacy,
            "wave1_inputs": wave1["status"],
            "excluded_private_material": [
                "game and user identifiers",
                "hashed terminal-position cache",
                "local engine/equality row cache",
                "crossing chooser/game-key caches and model checkpoints",
                "model checkpoints and DuckDB spill",
            ],
            "scope_note": (
                "Wave 2A recomputes equality/FEN analyses, the manuscript's adjacent "
                "displayed-gap crossing, and a post-Wave-1 1500/high-RD decomposition. "
                "It freezes new-sample "
                "support and dependencies for chronology-driven analyses but does not "
                "label those analyses current; they require Wave 2B."
            ),
        }
        common.atomic_json(staging / "_SUCCESS.json", summary)
        common.atomic_text(
            staging / "UPLOAD_THIS.txt",
            f"Upload {archive.name} and {sidecar.name} for authenticated review and Wave 2B.\n",
        )
        privacy = common.privacy_scan(staging)
        common.atomic_json(staging / "PRIVACY_AUDIT.json", privacy)
        common.write_manifest_tsv(staging)
        common.zip_tree(staging, archive)
        common.atomic_text(sidecar, f"{common.sha256_file(archive)}  {archive.name}\n")
    finally:
        shutil.rmtree(temporary_parent)

    result = {
        "status": "POOL_MAIN_REANALYSIS_WAVE2A_TRANSFER_OK",
        "archive": str(archive),
        "archive_sha256": common.sha256_file(archive),
        "sidecar": str(sidecar),
        "dynamics_rebuild_status": dynamics["status"],
    }
    print(result["status"], flush=True)
    print(f"UPLOAD: {archive}", flush=True)
    print(f"UPLOAD: {sidecar}", flush=True)
    return result


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
