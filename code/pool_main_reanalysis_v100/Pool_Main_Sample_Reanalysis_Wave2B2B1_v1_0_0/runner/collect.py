#!/usr/bin/env python3
"""Collect aggregate-only Wave 2B2B1 outputs into a checksummed ZIP."""

from __future__ import annotations

import argparse
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner import common
from runner.orchestrate import MODULE_STATUSES, _completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--transfer-root", type=Path, required=True)
    return parser.parse_args()


def _scope(auth: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "POOL_MAIN_WAVE2B2B1_SCOPE_DECLARED_OK",
        "sample_authority": common.compact_sample_lineage(auth),
        "included": [
            "C6 frozen non-exploitation model and treatment-blind support gate",
            "C10 denial-decay diagnostics",
            "C6 pre-scoped ply>10 exposure and later-event robustness checks, outside Holm",
            "C12 recipient pre-opportunity experience models on a fresh deterministic 2% recipient sample",
            "C12 v1.0.3 explicit 2400+ model attempt",
            "C7X frequent-dyad raw diagnostic using the invariant exact all-game dyad index",
        ],
        "c7x_policy": (
            "No frequent-dyad fixed-effect model is fit: the parent selected-panel C7X "
            "benefactor arm has 125 rows, below its frozen 1,000-per-arm gate."
        ),
        "c6_ply_policy": (
            "The frozen C6 primary is unchanged. Ply variants are pre-scoped secondary "
            "robustness checks and are not added to the confirmatory Holm family."
        ),
        "still_blocked": [
            "C9 fresh 4,999-draw conditional randomization and its ply sensitivity",
            "C13 ambient-exposure rebuild",
            "Campaign-family-D authenticated Holm closure, including explicit C5 p=1 handling",
            "Patron matching and Patron heterogeneity on the new main sample",
            "final unified manuscript tables, figures, and authority ledger",
        ],
        "manuscript_policy": (
            "Results may enter a tracked provisional manuscript only after this return "
            "archive is reviewed. Final Sections 5-6 and paper-wide claims remain gated "
            "on C9, C13, Holm reconciliation, and Wave 3 Patron work."
        ),
    }


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    public = args.public_base.expanduser().resolve()
    private = args.private_base.expanduser().resolve()
    transfer = args.transfer_root.expanduser().resolve()
    status_path = public / "WAVE2B2B1_RUN_STATUS.json"
    status = common.load_json(status_path)
    if status.get("status") != "POOL_MAIN_WAVE2B2B1_ALL_STAGES_OK":
        raise RuntimeError("Wave 2B2B1 stage chain is not certified complete")
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    if (status.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Wave 2B2B1 status belongs to another sample")
    config_sha256 = str(status["config_sha256"])
    modules = {}
    roots = {
        "c6_c10": public / "modules/c6_c10",
        "c6_ply": public / "modules/c6_ply_retrofit",
        "c12": public / "modules/c12",
        "c7x_dyad": public / "modules/c7x_frequent_dyad",
    }
    for name, root in roots.items():
        completed = _completed(
            root, MODULE_STATUSES[name], auth["fingerprint"], config_sha256
        )
        if completed is None:
            raise RuntimeError(f"Wave 2B2B1 module disappeared before collection: {name}")
        modules[name] = completed

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"POOL_MAIN_REANALYSIS_WAVE2B2B1_RESULTS_{stamp}"
    staging = public / f".{name}.staging"
    final = public / name
    if staging.exists() or final.exists():
        raise RuntimeError(f"Wave 2B2B1 collection target already exists: {name}")
    staging.mkdir(parents=True)
    try:
        results = staging / "results"
        results.mkdir()
        for module, root in roots.items():
            shutil.copytree(root, results / module)

        receipts = staging / "receipts"
        receipts.mkdir()
        for path in (public / "PREFLIGHT.json", status_path):
            if not path.is_file():
                raise RuntimeError(f"Wave 2B2B1 receipt is missing: {path}")
            shutil.copy2(path, receipts / path.name)
        shutil.copy2(private / "WAVE2B2B1_CONFIG.json", receipts / "WAVE2B2B1_CONFIG.json")
        shutil.copytree(private / "source_bindings", receipts / "source_bindings")

        executed = staging / "executed_source"
        common.copytree_filtered(
            private / "execution_packages/campaign_pool_main", executed / "campaign_pool_main"
        )
        common.copytree_filtered(common.PACKAGE_ROOT / "runner", executed / "runner")

        authority = staging / "authority"
        authority.mkdir()
        for filename in (
            "SAMPLE_AUTHORITY.json",
            "WAVE2B1_RUN_STATUS.json",
            "WAVE2B2A_RUN_STATUS.json",
        ):
            shutil.copy2(common.PACKAGE_ROOT / "authority" / filename, authority / filename)
        shutil.copy2(
            common.PACKAGE_ROOT / "authority/C7X_PRIVATE_CHECKPOINT_AUTHENTICATION.json",
            authority / "C7X_CHECKPOINT_AUTHENTICATION.json",
        )

        common.atomic_json(staging / "PUBLICATION_SCOPE.json", _scope(auth))
        common.atomic_text(
            staging / "README.md",
            "# Pool-main reanalysis — Wave 2B2B1\n\n"
            "Aggregate-only C6/C10, C6 ply, C12, and C7X frequent-dyad results "
            "on the certified pool/observed-nonadjacent 24-month panel.\n\n"
            "C7X frequent-dyad results are descriptive because the frozen parent "
            "support gate failed. See `PUBLICATION_SCOPE.json` for claim boundaries "
            "and remaining manuscript gates.\n",
        )
        success = {
            "status": "POOL_MAIN_REANALYSIS_WAVE2B2B1_RESULTS_OK",
            "created_at_utc": common.utc_now(),
            "sample_authority": common.compact_sample_lineage(auth),
            "config_sha256": config_sha256,
            "modules": {key: MODULE_STATUSES[key] for key in roots},
            "account_level_files_transferred": False,
            "private_row_level_files_transferred": False,
            "network_requests": 0,
        }
        common.atomic_json(staging / "_SUCCESS.json", success)
        common.atomic_json(staging / "PRIVACY_SCAN.json", common.privacy_scan(staging))
        common.write_manifest_tsv(staging)
        os.replace(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    transfer.mkdir(parents=True, exist_ok=True)
    archive = transfer / f"{name}.zip"
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    if archive.exists() or sidecar.exists():
        raise RuntimeError(f"Transfer artifact already exists: {archive}")
    common.zip_tree(final, archive)
    with zipfile.ZipFile(archive) as handle:
        bad = handle.testzip()
    if bad is not None:
        raise RuntimeError(f"Wave 2B2B1 ZIP CRC failure: {bad}")
    digest = common.sha256_file(archive)
    common.atomic_text(sidecar, f"{digest}  {archive.name}\n")
    common.atomic_json(
        public / "WAVE2B2B1_TRANSFER.json",
        {
            "status": "POOL_MAIN_REANALYSIS_WAVE2B2B1_TRANSFER_OK",
            "created_at_utc": common.utc_now(),
            "archive": str(archive),
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": digest,
            "sidecar": str(sidecar),
            "zip_crc_clean": True,
            "sample_fingerprint": auth["fingerprint"],
        },
    )
    print("POOL_MAIN_REANALYSIS_WAVE2B2B1_TRANSFER_OK", flush=True)
    print(f"RESULT_ZIP: {archive}", flush=True)
    print(f"RESULT_SIDECAR: {sidecar}", flush=True)
    print(f"RESULT_SHA256: {digest}", flush=True)
    return archive, sidecar


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
