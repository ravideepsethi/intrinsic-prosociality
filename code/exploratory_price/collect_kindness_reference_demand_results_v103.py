#!/usr/bin/env python3
"""Collect and inspect public aggregate outputs from reference-demand v1.0.3."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile
from typing import Any, Sequence
import zipfile

import kindness_price_elasticity_common_v102 as common


SCRIPT_VERSION = "1.0.3"
DEFAULT_DESKTOP = Path("/Users/u6025368/Desktop/Lichess_Desktop")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-pointer", type=Path, required=True)
    parser.add_argument("--launch-log", type=Path)
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP)
    return parser.parse_args(argv)


def copy_package(source: Path, destination: Path) -> None:
    def ignored(_: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name == "__pycache__" or name.endswith(".pyc") or name.endswith(".zip")
        }

    shutil.copytree(source, destination, ignore=ignored)


def verify_report_manifest(output: Path) -> list[dict[str, Any]]:
    manifest = output / "report_file_hashes.tsv"
    if not manifest.is_file():
        raise RuntimeError("Public result manifest is missing")
    rows: list[dict[str, Any]] = []
    lines = manifest.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "file\tbytes\tsha256":
        raise RuntimeError("Public result manifest header changed")
    for line in lines[1:]:
        relative, size, digest = line.split("\t")
        path = output / relative
        if (
            not path.is_file()
            or path.stat().st_size != int(size)
            or common.sha256_file(path) != digest
        ):
            raise RuntimeError(f"Public result authentication failed: {relative}")
        rows.append({"file": relative, "bytes": int(size), "sha256": digest})
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != "report_file_hashes.tsv"
    }
    expected = {str(row["file"]) for row in rows}
    if actual != expected:
        raise RuntimeError(
            f"Public result inventory changed: missing={sorted(expected-actual)} "
            f"extra={sorted(actual-expected)}"
        )
    return rows


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "COLLECTION_MANIFEST.json":
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": common.sha256_file(path),
            }
        )
    return rows


def create_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(source).as_posix())


def inspect_output(output: Path) -> dict[str, Any]:
    success = output / "_SUCCESS.json"
    failure = output / "FAILURE_DIAGNOSTIC.json"
    if success.is_file():
        payload = common.load_json(success)
        headline = payload.get("headline", {})
        loss = headline.get("primary_loss_side_scalar_companion", {})
        zero = headline.get("primary_zero_reference_companion", {})
        schedule = headline.get("primary_full_schedule_companion", {})
        prior = headline.get("prior_v102_opportunity_cost_elasticity", {})
        return {
            "status": payload.get("status"),
            "scientific_success": True,
            "models_attempted": payload.get("models_attempted"),
            "models_estimated": payload.get("models_estimated"),
            "models_failed_retained": payload.get("models_failed_retained"),
            "headline_object": headline.get("headline_object"),
            "global_signed_log_elasticity_status": headline.get(
                "global_signed_log_elasticity_status"
            ),
            "loss_log_model": loss.get("model"),
            "loss_log_elasticity": loss.get("estimate"),
            "loss_log_ci95_low": loss.get("ci95_low"),
            "loss_log_ci95_high": loss.get("ci95_high"),
            "zero_w0p5_contrast_pp": zero.get("coefficient_percentage_points"),
            "zero_w0p5_ci95_low_pp": zero.get("ci95_low_pp"),
            "zero_w0p5_ci95_high_pp": zero.get("ci95_high_pp"),
            "full_loss_slope_pp_per_point": schedule.get(
                "loss_magnitude_slope_pp_per_rating_point"
            ),
            "full_gain_slope_pp_per_point": schedule.get(
                "positive_side_slope_pp_per_rating_point"
            ),
            "prior_v102_premium_elasticity": prior.get("elasticity_estimate"),
            "claim_boundary": headline.get("claim_boundary"),
        }
    if failure.is_file():
        payload = common.load_json(failure)
        return {
            "status": payload.get("status"),
            "scientific_success": False,
            "failure_type": payload.get("error_type"),
            "failure_message": payload.get("error_message"),
        }
    raise RuntimeError("Neither success nor failure result exists")


def execute(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any]]:
    pointer = common.load_json(args.execution_pointer)
    output = Path(pointer["output_root"])
    package = Path(pointer["package_root"])
    run_id = str(pointer["run_id"])
    if not output.is_dir() or not package.is_dir():
        raise RuntimeError("Execution pointer targets are missing")
    public_manifest = verify_report_manifest(output)
    inspection = inspect_output(output)
    desktop = args.desktop.expanduser().resolve()
    desktop.mkdir(parents=True, exist_ok=True)
    zip_path = desktop / f"KINDNESS_REFERENCE_DEMAND_RESULTS_{run_id}.zip"
    sidecar = zip_path.with_suffix(zip_path.suffix + ".sha256")
    if zip_path.exists() or sidecar.exists():
        raise RuntimeError(f"Refusing to overwrite an existing result bundle: {zip_path}")

    with tempfile.TemporaryDirectory(
        prefix="kindness_reference_demand_collection_"
    ) as temporary:
        stage = Path(temporary)
        shutil.copytree(output, stage / "public_results")
        copy_package(package, stage / "executed_package_source")
        if args.launch_log and args.launch_log.is_file():
            (stage / "logs").mkdir()
            shutil.copy2(args.launch_log, stage / "logs" / args.launch_log.name)
        common.atomic_json(stage / "inspection.json", inspection)
        collection = {
            "status": "KINDNESS_REFERENCE_DEMAND_COLLECTION_OK",
            "created_utc": common.utc_now(),
            "run_id": run_id,
            "inspection": inspection,
            "public_result_files_authenticated": len(public_manifest),
            "contains_private_row_level_data": False,
            "parquet_files_in_bundle": 0,
            "collector_version": SCRIPT_VERSION,
        }
        if any(path.suffix.lower() == ".parquet" for path in stage.rglob("*")):
            raise RuntimeError("Collector detected Parquet row-level data in public bundle")
        collection["files"] = inventory(stage)
        collection["files_fingerprint_sha256"] = common.sha256_json(
            collection["files"]
        )
        common.atomic_json(stage / "COLLECTION_MANIFEST.json", collection)
        create_zip(stage, zip_path)
    digest = common.sha256_file(zip_path)
    common.atomic_text(sidecar, f"{digest}  {zip_path.name}\n")
    return zip_path, sidecar, inspection


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    zip_path, sidecar, inspection = execute(args)
    print("\nKINDNESS REFERENCE-DEMAND RESULT INSPECTION", flush=True)
    print(f"Status: {inspection.get('status')}", flush=True)
    if inspection.get("scientific_success"):
        print(f"Headline object: {inspection.get('headline_object')}", flush=True)
        print(
            "Loss-side log elasticity / 95% CI: "
            f"{inspection.get('loss_log_elasticity')} / "
            f"[{inspection.get('loss_log_ci95_low')}, "
            f"{inspection.get('loss_log_ci95_high')}]",
            flush=True,
        )
        print(
            "Zero-reference ±0.5 contrast (pp) / 95% CI: "
            f"{inspection.get('zero_w0p5_contrast_pp')} / "
            f"[{inspection.get('zero_w0p5_ci95_low_pp')}, "
            f"{inspection.get('zero_w0p5_ci95_high_pp')}]",
            flush=True,
        )
        print(
            "Full-schedule loss/gain slopes (pp per rating point): "
            f"{inspection.get('full_loss_slope_pp_per_point')} / "
            f"{inspection.get('full_gain_slope_pp_per_point')}",
            flush=True,
        )
        print(
            "Global signed log elasticity: "
            f"{inspection.get('global_signed_log_elasticity_status')}",
            flush=True,
        )
        print(
            "Retained v1.0.2 opportunity-cost elasticity: "
            f"{inspection.get('prior_v102_premium_elasticity')}",
            flush=True,
        )
        print(f"Claim boundary: {inspection.get('claim_boundary')}", flush=True)
        print(
            "Models attempted / estimated / failed-retained: "
            f"{inspection.get('models_attempted')} / "
            f"{inspection.get('models_estimated')} / "
            f"{inspection.get('models_failed_retained')}",
            flush=True,
        )
    else:
        print(
            f"Failure: {inspection.get('failure_type')}: "
            f"{inspection.get('failure_message')}",
            flush=True,
        )
    print("\nKINDNESS_REFERENCE_DEMAND_RESULT_BUNDLE_READY", flush=True)
    print(f"Upload this file: {zip_path}", flush=True)
    print(f"Bundle SHA-256: {common.sha256_file(zip_path)}", flush=True)
    print(f"Sidecar: {sidecar}", flush=True)


if __name__ == "__main__":
    main()
