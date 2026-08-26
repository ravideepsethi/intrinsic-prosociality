#!/usr/bin/env python3
"""Collect, authenticate, and inspect public C1/C9 corrective outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any


FORBIDDEN_PRIVATE_SUFFIXES = {
    ".parquet", ".npz", ".npy", ".pickle", ".pkl", ".feather", ".arrow"
}


def sha256_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def copy_public_result(pointer_path: Path, destination: Path) -> dict[str, Any]:
    if not pointer_path.is_file():
        return {
            "status": "NO_EXECUTION_POINTER",
            "pointer": str(pointer_path),
            "copied": False,
        }
    pointer = read_json(pointer_path)
    source = Path(pointer["result_root"])
    if not source.is_dir():
        raise RuntimeError(f"Execution pointer result root is missing: {source}")
    forbidden = [
        str(p) for p in source.rglob("*")
        if p.is_file() and p.suffix.lower() in FORBIDDEN_PRIVATE_SUFFIXES
    ]
    if forbidden:
        raise RuntimeError(
            f"Refusing to collect row-level/private-looking result files: {forbidden}"
        )
    shutil.copytree(source, destination)
    return {
        **pointer,
        "copied": True,
        "copied_as": str(destination),
    }


def inspect_c1(root: Path) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    if success.is_file():
        receipt = read_json(success)
        if receipt.get("status") != "DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_OK":
            raise RuntimeError("C1 success status mismatch during collection")
        with (root / "c1_prior_result_state_dependence.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        primary = next(row for row in rows if row.get("model") == "C1_30min")
        streak = read_json(root / "c1_secondary_streak3_STATUS.json")
        bridge = read_json(root / "c1_result_bridge_validation.json")
        return {
            "status": receipt["status"],
            "success_sha256": sha256_file(success),
            "primary": {
                key: primary.get(key) for key in (
                    "effect_pp", "se_pp", "p_value_two_sided", "rows",
                    "chooser_clusters", "raw_loss_rate_pct", "raw_win_rate_pct",
                    "decoded_rows_before_complete_case_filter",
                    "complete_case_preservation_share",
                )
            },
            "secondary_streak3": streak,
            "bridge": {
                "needed_result_rows": bridge["needed_result_rows"],
                "resolved_bridge_rows": bridge["resolved_bridge_rows"],
                "raw_result_code_counts": bridge["raw_result_code_counts"],
                "chooser_result_counts": bridge["chooser_result_counts"],
                "perspective_validation": bridge["perspective_validation"],
            },
        }
    failure = root / "FAILURE_DIAGNOSTIC.json"
    return {
        "status": "FAILED",
        "diagnostic": read_json(failure) if failure.is_file() else None,
    }


def inspect_c9(root: Path) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    if success.is_file():
        receipt = read_json(success)
        if receipt.get("status") != "DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_OK":
            raise RuntimeError("C9 success status mismatch during collection")
        primary = read_json(root / "c9_primary_later_session.json")
        inventory = read_json(root / "c9_checkpoint_recovery_inventory.json")
        if inventory.get("new_randomizations_drawn") != 0:
            raise RuntimeError("C9 collector found newly drawn randomizations")
        return {
            "status": receipt["status"],
            "success_sha256": sha256_file(success),
            "primary": {
                key: primary.get(key) for key in (
                    "observed_numerator", "observed_denominator",
                    "observed_rate_pct", "null_mean_rate_pct",
                    "excess_percentage_points", "randomization_p_two_sided",
                    "randomizations", "holm_adjusted_p_value",
                )
            },
            "checkpoint_recovery": inventory,
            "exact_b2_reproduction": receipt.get("exact_b2_reproduction"),
        }
    failure = root / "FAILURE_DIAGNOSTIC.json"
    return {
        "status": "FAILED",
        "diagnostic": read_json(failure) if failure.is_file() else None,
    }


def render_summary(c1: dict[str, Any], c9: dict[str, Any]) -> str:
    lines = ["CAMPAIGN 1 C1/C9 CORRECTIVE RESULT INSPECTION", ""]
    lines.append(f"C9 status: {c9.get('status')}")
    if c9.get("primary"):
        p = c9["primary"]
        lines.extend([
            f"C9 later-session excess: {p['excess_percentage_points']} percentage points",
            f"C9 observed/null rates: {p['observed_rate_pct']}% / {p['null_mean_rate_pct']}%",
            f"C9 raw randomization p: {p['randomization_p_two_sided']}",
            f"C9 new randomizations drawn: {c9['checkpoint_recovery']['new_randomizations_drawn']}",
        ])
    elif c9.get("diagnostic"):
        lines.append(f"C9 error: {c9['diagnostic'].get('error')}")

    lines.extend(["", f"C1 status: {c1.get('status')}"])
    if c1.get("primary"):
        p = c1["primary"]
        lines.extend([
            f"C1 30m effect (loss minus win): {p['effect_pp']} percentage points",
            f"C1 clustered SE / raw p: {p['se_pp']} / {p['p_value_two_sided']}",
            f"C1 rows / chooser clusters: {p['rows']} / {p['chooser_clusters']}",
            "C1 raw-code support: 0, 1, 2 (explicitly decoded)",
            f"C1 streak secondary status: {c1['secondary_streak3'].get('status')}",
        ])
    elif c1.get("diagnostic"):
        lines.append(f"C1 error: {c1['diagnostic'].get('error')}")
    lines.extend([
        "",
        "Invalid Run A and Run B C1 estimates are excluded from interpretation and Holm.",
        "Final Holm adjustment remains pending the other effective-plan family members.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--launch-root", type=Path, required=True)
    ap.add_argument("--package-root", type=Path, required=True)
    ap.add_argument("--destination-dir", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    launch = args.launch_root.resolve()
    package = args.package_root.resolve()
    stage = launch / "authenticated_upload_stage"
    stage.mkdir(parents=True, exist_ok=False)
    results = stage / "public_results"
    results.mkdir()

    c9_pointer = copy_public_result(launch / "c9_execution_pointer.json", results / "C9")
    c1_pointer = copy_public_result(launch / "c1_execution_pointer.json", results / "C1")

    shutil.copytree(launch / "logs", stage / "logs")
    sources = stage / "executed_package_source"
    sources.mkdir()
    for name in (
        "README_FIRST.md",
        "RUN_CAMPAIGN1_C1_C9_CORRECTIVE_v1_0_0.command",
        "PACKAGE_CONTENTS.sha256",
    ):
        source = package / name
        if source.is_file():
            shutil.copy2(source, sources / name)
    shutil.copytree(package / "payload" / "code", sources / "code")
    shutil.copytree(package / "payload" / "docs", sources / "docs")

    c9_inspection = (
        inspect_c9(results / "C9") if c9_pointer.get("copied")
        else {"status": c9_pointer["status"]}
    )
    c1_inspection = (
        inspect_c1(results / "C1") if c1_pointer.get("copied")
        else {"status": c1_pointer["status"]}
    )
    inspection = {
        "status": "CAMPAIGN1_C1_C9_CORRECTIVE_COLLECTION_COMPLETE",
        "run_id": args.run_id,
        "c9_execution": c9_pointer,
        "c1_execution": c1_pointer,
        "c9_inspection": c9_inspection,
        "c1_inspection": c1_inspection,
        "private_row_level_files_included": False,
    }
    (stage / "inspection.json").write_text(
        json.dumps(inspection, indent=2, sort_keys=True) + "\n"
    )
    summary_text = render_summary(c1_inspection, c9_inspection)
    (stage / "RESULTS_SUMMARY.txt").write_text(summary_text)

    manifest = []
    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
        manifest.append({
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "file": str(path.relative_to(stage)),
        })
    (stage / "COLLECTION_MANIFEST.json").write_text(
        json.dumps({"files": manifest}, indent=2, sort_keys=True) + "\n"
    )

    args.destination_dir.mkdir(parents=True, exist_ok=True)
    bundle = args.destination_dir / f"CAMPAIGN1_C1_C9_CORRECTIVE_RESULTS_{args.run_id}.zip"
    if bundle.exists():
        raise RuntimeError(f"Refusing to overwrite existing result bundle: {bundle}")
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(p for p in stage.rglob("*") if p.is_file()):
            zf.write(path, arcname=str(path.relative_to(stage)))
    digest = sha256_file(bundle)
    sidecar = bundle.with_suffix(bundle.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {bundle.name}\n")

    print(summary_text, end="")
    print("CAMPAIGN1_CORRECTIVE_RESULT_BUNDLE_READY")
    print(f"Upload this file: {bundle}")
    print(f"Bundle SHA-256: {digest}")
    print(f"Sidecar: {sidecar}")


if __name__ == "__main__":
    main()
