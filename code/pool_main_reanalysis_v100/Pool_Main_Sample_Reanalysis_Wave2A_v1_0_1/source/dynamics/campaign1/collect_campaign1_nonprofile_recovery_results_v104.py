#!/usr/bin/env python3
"""Collect and authenticate aggregate-only non-profile recovery v1.0.4 results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
import zipfile


FORBIDDEN_PRIVATE_SUFFIXES = {
    ".parquet", ".npz", ".npy", ".pickle", ".pkl", ".feather", ".arrow"
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def authenticate_public_result(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise RuntimeError(f"Result root is missing: {root}")
    forbidden = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_PRIVATE_SUFFIXES
    ]
    if forbidden:
        raise RuntimeError(f"Private-looking files reached public results: {forbidden}")
    manifest_path = root / "report_file_hashes.tsv"
    if not manifest_path.is_file():
        raise RuntimeError("Public result lacks report_file_hashes.tsv")
    with manifest_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    expected = {row["file"] for row in rows}
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in {"report_file_hashes.tsv", "_SUCCESS.json"}
    }
    if expected != actual:
        raise RuntimeError(
            f"Public result manifest mismatch: missing={sorted(expected-actual)} "
            f"extra={sorted(actual-expected)}"
        )
    for row in rows:
        path = root / row["file"]
        if path.stat().st_size != int(row["bytes"]) or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Public result file changed: {row['file']}")
    success = root / "_SUCCESS.json"
    failure = root / "FAILURE_DIAGNOSTIC.json"
    if success.is_file():
        status = load_json(success).get("status")
        if status != "DYNAMICS_CAMPAIGN1_NONPROFILE_RECOVERY_V104_OK":
            raise RuntimeError(f"Unexpected success status: {status}")
    elif failure.is_file():
        status = load_json(failure).get("status")
    else:
        raise RuntimeError("Public result has neither success nor failure receipt")
    return {
        "status": status,
        "files_authenticated": len(rows),
        "report_manifest_sha256": sha256_file(manifest_path),
        "success_sha256": sha256_file(success) if success.is_file() else None,
        "failure_sha256": sha256_file(failure) if failure.is_file() else None,
        "private_row_level_files_included": False,
    }


def copy_result(pointer_path: Path, destination: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not pointer_path.is_file():
        raise RuntimeError(f"Execution pointer is missing: {pointer_path}")
    pointer = load_json(pointer_path)
    source = Path(pointer["result_root"])
    authentication = authenticate_public_result(source)
    if pointer.get("status") != authentication["status"]:
        raise RuntimeError("Execution pointer status disagrees with result receipt")
    if pointer.get("success_sha256") and pointer["success_sha256"] != authentication["success_sha256"]:
        raise RuntimeError("Execution pointer success hash mismatch")
    shutil.copytree(source, destination)
    return pointer, authentication


def render_summary(result_root: Path, authentication: dict[str, Any]) -> str:
    lines = ["CAMPAIGN 1 NON-PROFILE RECOVERY v1.0.4 RESULT INSPECTION", ""]
    lines.append(f"Overall status: {authentication['status']}")
    if (result_root / "summary.json").is_file():
        summary = load_json(result_root / "summary.json")
        modules = summary.get("modules", {})
        c6 = modules.get("C6_C10", {}).get("C6", {})
        c12 = modules.get("C12", {})
        c13 = modules.get("C13", {})
        lines.extend(
            [
                f"C6 status / gate: {c6.get('status')} / {c6.get('gate_pass')}",
                f"C10 status: {modules.get('C6_C10', {}).get('C10', {}).get('status')}",
                f"C7 status / gate: {modules.get('C7', {}).get('result_status')} / {modules.get('C7', {}).get('gate_pass')}",
                f"C12 status: {c12.get('status')}",
                "C12 2400+ supplement rows / clusters / status: "
                f"{c12.get('v103_supplement_requested_rows')} / "
                f"{c12.get('v103_supplement_requested_chooser_clusters')} / "
                f"{c12.get('v103_supplement_final_status')}",
                f"C12 attempts / retained failures: {c12.get('model_attempts_total')} / {c12.get('retained_model_failures')}",
                f"C13 status: {c13.get('status')}",
                "C13 Wave-0 / corrected supported rows: "
                f"{c13.get('superseded_wave0_supported_rows')} / "
                f"{c13.get('primary_supported_rows')}",
                f"C13 attempts / retained failures: {c13.get('model_attempts_total')} / {c13.get('retained_model_failures')}",
                "C13 all-panel / fair-sample kindness counts: "
                f"{c13.get('all_stage07_kind_draws')} / "
                f"{c13.get('fair_sample_kind_draws')}",
            ]
        )
        if c6.get("primary"):
            primary = c6["primary"]
            lines.append(
                "C6 primary mercy-minus-claim coefficient / raw p: "
                f"{primary.get('coefficient')} / {primary.get('p_value_raw')}"
            )
        c7_unadjusted = modules.get("C7", {}).get("unadjusted_primary")
        if c7_unadjusted:
            lines.append(
                "C7 exploratory unadjusted difference / Fisher p: "
                f"{c7_unadjusted.get('difference_percentage_points')} pp / "
                f"{c7_unadjusted.get('fisher_exact_two_sided_p_value')}"
            )
        if c12.get("primary"):
            primary = c12["primary"]
            lines.append(
                "C12 low-minus-high recipient-experience effect / p: "
                f"{primary.get('effect_percentage_points')} pp / "
                f"{primary.get('p_value_two_sided')}"
            )
        if c13.get("primary"):
            primary = c13["primary"]
            lines.append(
                "C13 focal effect per +1pp ambient kindness / p: "
                f"{primary.get('focal_effect_percentage_points')} pp / "
                f"{primary.get('p_value_two_sided')}"
            )
        family = summary.get("family_D", {})
        lines.extend(
            [
                "",
                f"Family D status: {family.get('status')}",
                f"Missing effective member(s): {family.get('missing_raw_p_values')}",
                f"Guaranteed rejections at 0.05: {family.get('bonferroni_guaranteed_rejections_at_0_05')}",
            ]
        )
    elif (result_root / "FAILURE_DIAGNOSTIC.json").is_file():
        failure = load_json(result_root / "FAILURE_DIAGNOSTIC.json")
        lines.extend(
            [
                f"Completed modules: {list(failure.get('completed_modules', {}))}",
                f"Failure type: {failure.get('error_type')}",
                f"Failure message: {failure.get('error')}",
                "The run failed closed; completed private checkpoints remain resumable.",
            ]
        )
    lines.extend(
        [
            "",
            "Every favorable, null, adverse, low-support, and unestimable model record is retained.",
            "The C13 denominator correction was frozen before its ambient-kindness numerator was read.",
            "The fair-sample numerator authority was corrected before any C13 model was estimated.",
            "C4/C5/C11/C14B still lack the separate profile authority; invalid C1 lineages remain excluded.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--destination-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    launch = args.launch_root.resolve()
    package = args.package_root.resolve()
    stage = launch / "authenticated_upload_stage"
    stage.mkdir(parents=True, exist_ok=False)
    result_destination = stage / "public_results"
    pointer, authentication = copy_result(
        launch / "execution_pointer.json", result_destination
    )
    shutil.copytree(launch / "logs", stage / "logs")
    shutil.copytree(
        package,
        stage / "executed_package_source",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    summary_text = render_summary(result_destination, authentication)
    (stage / "RESULTS_SUMMARY.txt").write_text(summary_text, encoding="utf-8")
    inspection = {
        "status": "CAMPAIGN1_NONPROFILE_RECOVERY_V104_COLLECTION_COMPLETE",
        "run_id": args.run_id,
        "execution_pointer": pointer,
        "result_authentication": authentication,
        "private_row_level_files_included": False,
    }
    (stage / "inspection.json").write_text(
        json.dumps(inspection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest: list[dict[str, Any]] = []
    for path in sorted(item for item in stage.rglob("*") if item.is_file()):
        manifest.append(
            {
                "file": path.relative_to(stage).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    (stage / "COLLECTION_MANIFEST.json").write_text(
        json.dumps({"files": manifest}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    args.destination_dir.mkdir(parents=True, exist_ok=True)
    bundle = args.destination_dir / f"CAMPAIGN1_NONPROFILE_RECOVERY_RESULTS_{args.run_id}.zip"
    if bundle.exists():
        raise RuntimeError(f"Refusing to overwrite result bundle: {bundle}")
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in stage.rglob("*") if item.is_file()):
            archive.write(path, arcname=path.relative_to(stage).as_posix())
    digest = sha256_file(bundle)
    sidecar = bundle.with_suffix(bundle.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {bundle.name}\n", encoding="utf-8")
    print(summary_text, end="")
    print("CAMPAIGN1_NONPROFILE_RECOVERY_V104_RESULT_BUNDLE_READY")
    print(f"Upload this file: {bundle}")
    print(f"Bundle SHA-256: {digest}")
    print(f"Sidecar: {sidecar}")


if __name__ == "__main__":
    main()
