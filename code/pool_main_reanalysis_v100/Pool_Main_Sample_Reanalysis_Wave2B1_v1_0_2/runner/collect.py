#!/usr/bin/env python3
"""Collect authenticated Wave 2B1 aggregate outputs into a public return ZIP."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner import common
from runner.orchestrate import EXPECTED_STATUSES, STAGES, completed_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--transfer-root", type=Path, required=True)
    return parser.parse_args()


def _write_module_table(path: Path, modules: list[dict[str, Any]]) -> None:
    fields = (
        "stage",
        "status",
        "success_sha256",
        "summary_sha256",
        "manifest_files_authenticated",
    )
    rows = ["\t".join(fields)]
    for module in modules:
        rows.append("\t".join(str(module.get(field, "")) for field in fields))
    common.atomic_text(path, "\n".join(rows) + "\n")


def _scope(auth: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "POOL_MAIN_WAVE2B1_SCOPE_DECLARED_OK",
        "sample_authority": common.compact_sample_lineage(auth),
        "included_current_after_this_bundle": [
            "A3 arm-blind all-game 7-day/30-day activity linkage and selected outcome gate",
            "A1/A3/B1 frozen dynamic core and three-primary Holm family",
            "A1 post-outcome evidence audits and remaining prespecified A1/A2 analyses",
            "B2 first-grant timing randomization analysis",
            "second-wave sampled user and dyad histories",
            "prespecified second-wave E1/F2 results and four-slot Holm family",
            "postprimary second-wave robustness grid and independent E1 numerical audit",
            "C7R full-panel pre-focal first-versus-repeat meeting analysis",
        ],
        "intentionally_not_duplicated": [
            "chooser-leniency IV branch, already launched separately; its requested selection-role decomposition must be checked when branches are merged",
        ],
        "still_blocked_after_wave2b1": [
            "Campaign-1 C1/C6/C7/C9/C12/C13 recovery modules and targeted-memory/ply retrofits (Wave 2B2)",
            "Patron matching and Patron heterogeneity (Wave 3)",
            "unified manuscript tables, figures, abstract sample count, and section 5-6 numerical revision (Wave 3)",
        ],
        "manuscript_policy": (
            "Do not paste any Wave 2B1 number into the manuscript until the separate IV branch, "
            "Wave 2B2, and Wave 3 are reconciled into the manuscript-wide authority ledger."
        ),
    }


def _summary_markdown(scope: dict[str, Any], modules: list[dict[str, Any]]) -> str:
    lines = [
        "# Pool-main reanalysis — Wave 2B1 return",
        "",
        "This archive contains aggregate-only results rebuilt from the certified "
        "pool/non-adjacent 24-month main sample.",
        "",
        "## Sample authority",
        "",
        f"- Fingerprint: `{scope['sample_authority']['fingerprint']}`",
        f"- Rows: {scope['sample_authority']['rows']:,}",
        f"- Fair rows: {scope['sample_authority']['fair_rows']:,}",
        f"- Kind draws: {scope['sample_authority']['kind_draws']:,}",
        "",
        "## Authenticated modules",
        "",
    ]
    for module in modules:
        lines.append(f"- `{module['stage']}` — `{module['status']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "The separately running chooser-IV branch is not duplicated here. Campaign/targeted-memory "
            "modules remain for Wave 2B2; Patron and unified manuscript artifacts remain for Wave 3.",
            "",
            "No identifier-bearing or private row-level checkpoint is included.",
            "",
        ]
    )
    return "\n".join(lines)


def _verify_bundle_manifest(root: Path) -> int:
    manifest = root / "REPORT_FILE_HASHES.tsv"
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    for row in rows:
        path = root / row["relative_path"]
        if not path.is_file():
            raise RuntimeError(f"Collected bundle member missing: {path}")
        if path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Collected bundle size mismatch: {path}")
        if common.sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Collected bundle checksum mismatch: {path}")
    return len(rows)


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    public_base = args.public_base.expanduser().resolve()
    private_base = args.private_base.expanduser().resolve()
    transfer_root = args.transfer_root.expanduser().resolve()
    status_path = public_base / "WAVE2B1_RUN_STATUS.json"
    status = common.load_json(status_path)
    if status.get("status") != "POOL_MAIN_WAVE2B1_ALL_STAGES_OK":
        raise RuntimeError("Wave 2B1 did not complete the full stage chain")
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    if (status.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Wave 2B1 run receipt belongs to another sample")

    modules: list[dict[str, Any]] = []
    for stage in STAGES:
        root = Path(status["result_roots"][stage])
        verified = completed_result(root, EXPECTED_STATUSES[stage])
        if verified is None:
            raise RuntimeError(f"Completed Wave 2B1 module is missing: {stage}")
        modules.append({"stage": stage, **verified})

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"POOL_MAIN_REANALYSIS_WAVE2B1_RESULTS_{stamp}"
    public_base.mkdir(parents=True, exist_ok=True)
    staging = public_base / f".{name}.staging"
    final = public_base / name
    if staging.exists() or final.exists():
        raise RuntimeError(f"Return bundle target already exists: {staging} or {final}")
    staging.mkdir(parents=True)
    try:
        results_root = staging / "results"
        results_root.mkdir()
        for module in modules:
            source = Path(module["root"])
            destination = results_root / module["stage"]
            shutil.copytree(source, destination)

        receipts = staging / "receipts"
        receipts.mkdir()
        for path in (
            public_base / "PREFLIGHT.json",
            public_base / "PROJECT_VIEW_PREPARED.json",
            status_path,
        ):
            if not path.is_file():
                raise RuntimeError(f"Wave 2B1 public receipt is missing: {path}")
            shutil.copy2(path, receipts / path.name)
        binding_root = private_base / "bindings"
        if not binding_root.is_dir():
            raise RuntimeError("Source-binding receipts are missing")
        shutil.copytree(binding_root, receipts / "source_bindings")
        if (public_base / "logs").is_dir():
            shutil.copytree(public_base / "logs", staging / "logs")

        evidence = staging / "authority"
        evidence.mkdir()
        for name_part in (
            "SAMPLE_AUTHORITY.json",
            "DYNAMICS_REBUILD_PREFLIGHT.json",
            "WAVE2A_SUCCESS.json",
        ):
            shutil.copy2(common.PACKAGE_ROOT / "authority" / name_part, evidence / name_part)

        scope = _scope(auth)
        common.atomic_json(staging / "PUBLICATION_SCOPE.json", scope)
        common.atomic_text(staging / "README.md", _summary_markdown(scope, modules))
        _write_module_table(staging / "MODULE_STATUS.tsv", modules)
        success = {
            "status": "POOL_MAIN_REANALYSIS_WAVE2B1_RESULTS_OK",
            "created_at_utc": common.utc_now(),
            "sample_authority": common.compact_sample_lineage(auth),
            "modules": len(modules),
            "module_statuses": {row["stage"]: row["status"] for row in modules},
            "account_level_files_transferred": False,
            "private_row_level_files_transferred": False,
            "network_requests": 0,
        }
        common.atomic_json(staging / "_SUCCESS.json", success)
        privacy = common.privacy_scan(staging)
        common.atomic_json(staging / "PRIVACY_SCAN.json", privacy)
        common.write_manifest_tsv(staging, "REPORT_FILE_HASHES.tsv")
        success["manifest_files_authenticated"] = _verify_bundle_manifest(staging)
        # Keep _SUCCESS inside its already-manifested form; the independent count
        # is written to a separate side receipt outside the bundle below.
        os.replace(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    transfer_root.mkdir(parents=True, exist_ok=True)
    archive = transfer_root / f"{name}.zip"
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    if archive.exists() or sidecar.exists():
        raise RuntimeError(f"Transfer artifact already exists: {archive}")
    common.zip_tree(final, archive)
    with zipfile.ZipFile(archive) as handle:
        bad = handle.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC validation failed: {bad}")
    digest = common.sha256_file(archive)
    common.atomic_text(sidecar, f"{digest}  {archive.name}\n")
    external = {
        "status": "POOL_MAIN_REANALYSIS_WAVE2B1_TRANSFER_OK",
        "created_at_utc": common.utc_now(),
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": digest,
        "sidecar": str(sidecar),
        "zip_crc_clean": True,
        "bundle_manifest_files_authenticated": _verify_bundle_manifest(final),
        "sample_fingerprint": auth["fingerprint"],
    }
    common.atomic_json(public_base / "WAVE2B1_TRANSFER.json", external)
    print("POOL_MAIN_REANALYSIS_WAVE2B1_TRANSFER_OK", flush=True)
    print(f"RESULT_ZIP: {archive}", flush=True)
    print(f"RESULT_SIDECAR: {sidecar}", flush=True)
    print(f"RESULT_SHA256: {digest}", flush=True)
    return archive, sidecar


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
