#!/usr/bin/env python3
"""Estimate the zero-coded first-opportunity A1 companion and verify Stage 07.

This post-result audit authenticates the certified A1 core result and private
recipient checkpoint, exactly reproduces the frozen conditional headline and
its existing reach/any-grant companions, then estimates the missing
unconditional analogue of the headline:

    reached_fair_chooser_within_90d * first_subsequent_kind_draw

Recipients with complete 90-day coverage who never reach a fair chooser
opportunity are coded zero. Only aggregate CSV/JSON/Markdown output is public.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.0"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
CORE_RUN_ID = "20260822T022146Z"

EXPECTED_BASE_PRODUCER_SHA256 = (
    "2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713"
)
EXPECTED_CORE_SUCCESS_SHA256 = (
    "bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009"
)
EXPECTED_CORE_SUMMARY_SHA256 = (
    "fa49fb15e095fb961a3f4cca5b937d903bc890467ed8404e37683858dd20a269"
)
EXPECTED_CORE_MANIFEST_SHA256 = (
    "e2724dab02a2b7b7c10f68b63ed40ddc67f2345947aa923d851912df946d16d8"
)
EXPECTED_PRIVATE_RECIPIENT_SHA256 = (
    "41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d"
)
EXPECTED_RECIPIENT_ROWS = 2_556_782

EXPECTED_FULL_FOLLOWUP_ROWS = 2_185_073
EXPECTED_FULL_FOLLOWUP_TREATED = 65_085
EXPECTED_FULL_FOLLOWUP_CONTROL = 2_119_988
EXPECTED_HEADLINE_ROWS = 1_029_558
EXPECTED_HEADLINE_TREATED = 30_051
EXPECTED_HEADLINE_CONTROL = 999_507

EXPECTED_REPRODUCTIONS = {
    "primary_total_path_conditional_choice": {
        "rows": EXPECTED_HEADLINE_ROWS,
        "treated_rows": EXPECTED_HEADLINE_TREATED,
        "control_rows": EXPECTED_HEADLINE_CONTROL,
        "coefficient": 0.010046862925197863,
        "standard_error": 0.0012280635224883034,
    },
    "mandatory_reach_companion": {
        "rows": EXPECTED_FULL_FOLLOWUP_ROWS,
        "treated_rows": EXPECTED_FULL_FOLLOWUP_TREATED,
        "control_rows": EXPECTED_FULL_FOLLOWUP_CONTROL,
        "coefficient": -0.001997581215042843,
        "standard_error": 0.0018786044050148217,
    },
    "mandatory_unconditional_kind_companion": {
        "rows": EXPECTED_FULL_FOLLOWUP_ROWS,
        "treated_rows": EXPECTED_FULL_FOLLOWUP_TREATED,
        "control_rows": EXPECTED_FULL_FOLLOWUP_CONTROL,
        "coefficient": 0.004957039963181425,
        "standard_error": 0.0007177473533220234,
    },
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--base-producer", type=Path)
    parser.add_argument("--core-result-root", type=Path)
    parser.add_argument("--core-state-root", type=Path)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--hash-workers", type=int, default=4)
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--verify-stage07-hashes", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    if not materialized:
        raise RuntimeError(f"Refusing to write an empty CSV: {path}")
    fields: list[str] = []
    for row in materialized:
        for field in row:
            if field not in fields:
                fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow(
                {
                    key: json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (list, dict, tuple))
                    else value
                    for key, value in row.items()
                }
            )
    os.replace(temporary, path)


def import_base(path: Path) -> ModuleType:
    if not path.is_file():
        raise RuntimeError(f"Certified base producer is missing: {path}")
    actual = sha256_file(path)
    if actual != EXPECTED_BASE_PRODUCER_SHA256:
        raise RuntimeError(
            "Certified base-producer SHA-256 mismatch: "
            f"expected={EXPECTED_BASE_PRODUCER_SHA256} actual={actual}"
        )
    spec = importlib.util.spec_from_file_location("a1_certified_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import certified base producer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authenticate_core_result(base: ModuleType, root: Path) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    summary = root / "summary.json"
    manifest = root / "report_file_hashes.tsv"
    expected = {
        success: EXPECTED_CORE_SUCCESS_SHA256,
        summary: EXPECTED_CORE_SUMMARY_SHA256,
        manifest: EXPECTED_CORE_MANIFEST_SHA256,
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"Certified core authority mismatch: {path}")
    receipt = load_json(success)
    if receipt.get("status") != "DYNAMIC_PROSOCIALITY_CORE_V102_OK":
        raise RuntimeError("Certified core status changed")
    authenticated = base.authenticate_manifest(root, manifest)
    return {
        "root": str(root),
        "status": receipt["status"],
        "success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "summary_sha256": EXPECTED_CORE_SUMMARY_SHA256,
        "manifest_sha256": EXPECTED_CORE_MANIFEST_SHA256,
        "report_files_authenticated": authenticated,
    }


def authenticate_private_recipient(root: Path) -> dict[str, Any]:
    path = root / "recipient_with_chronology_private.parquet"
    receipt = root / "recipient_with_chronology_receipt.json"
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Private recipient checkpoint is missing: {path}")
    actual = sha256_file(path)
    if actual != EXPECTED_PRIVATE_RECIPIENT_SHA256:
        raise RuntimeError("Private recipient checkpoint SHA-256 mismatch")
    saved = load_json(receipt)
    if saved.get("output_sha256") != EXPECTED_PRIVATE_RECIPIENT_SHA256:
        raise RuntimeError("Private recipient receipt SHA-256 mismatch")
    if int(saved.get("rows", -1)) != EXPECTED_RECIPIENT_ROWS:
        raise RuntimeError("Private recipient receipt row count mismatch")
    return {
        "path": str(path),
        "receipt": str(receipt),
        "sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
        "rows": EXPECTED_RECIPIENT_ROWS,
    }


def verify_stage07_files(
    base: ModuleType, root: Path, workers: int, enabled: bool
) -> dict[str, Any]:
    authority = base.authenticate_stage07(root, verify_hashes=False)
    result: dict[str, Any] = {
        "root": str(root),
        "success_sha256": authority["success_sha256"],
        "selected_input_bytes": int(authority["selected_input_bytes"]),
        "parquet_hashes_verified": False,
        "hash_workers": 0,
        "months": 24,
    }
    if not enabled:
        return result
    status_path = root / "_manifests/month_status.csv"
    with status_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 24:
        raise RuntimeError("Stage-07 month-status row count changed")
    expected = {
        row["month"]: row["output_sha256"]
        for row in rows
    }
    paths = list(authority["paths"])
    worker_count = max(1, min(int(workers), len(paths)))
    started = time.monotonic()
    print(
        f"STAGE07_PARQUET_HASH_VERIFICATION_BEGIN workers={worker_count}",
        flush=True,
    )

    def hash_one(path: Path) -> tuple[str, str, int]:
        month = path.parent.name.split("=", 1)[1]
        return month, sha256_file(path), path.stat().st_size

    completed: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count
    ) as executor:
        futures = [executor.submit(hash_one, path) for path in paths]
        for index, future in enumerate(
            concurrent.futures.as_completed(futures), start=1
        ):
            month, actual, size = future.result()
            if actual != expected.get(month):
                raise RuntimeError(f"Stage-07 Parquet SHA mismatch: {month}")
            completed[month] = {
                "month": month,
                "sha256": actual,
                "bytes": int(size),
            }
            print(
                f"STAGE07_PARQUET_HASH_OK month={month} "
                f"progress={index}/24",
                flush=True,
            )
    elapsed = time.monotonic() - started
    result.update(
        {
            "parquet_hashes_verified": True,
            "hash_workers": worker_count,
            "elapsed_seconds": elapsed,
            "files": [completed[month] for month in base.MAIN_MONTHS],
        }
    )
    print(
        f"STAGE07_PARQUET_HASH_VERIFICATION_OK elapsed={elapsed:.1f}s",
        flush=True,
    )
    return result


def assert_reproduction(row: dict[str, Any], label: str) -> None:
    expected = EXPECTED_REPRODUCTIONS[label]
    for field in ("rows", "treated_rows", "control_rows"):
        if int(row[field]) != int(expected[field]):
            raise RuntimeError(
                f"Certified reproduction count changed: {label} {field}"
            )
    for field in ("coefficient", "standard_error"):
        if not math.isclose(
            float(row[field]),
            float(expected[field]),
            rel_tol=0.0,
            abs_tol=5e-15,
        ):
            raise RuntimeError(
                f"Certified reproduction estimate changed: {label} {field}"
            )


def estimate_models(
    base: ModuleType, recipient_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    _, np, _, _ = base.import_dependencies()
    data = base.load_recipient_arrays(recipient_path)
    support = base.common_support_weights(data)
    first = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(
        bool
    )
    full_followup = first & data["a1_90d_followup_eligible"].astype(bool)
    reached = data["reached_fair_chooser_within_90d"].astype(bool)
    conditional = full_followup & reached
    if int(np.count_nonzero(full_followup & support["eligible"])) != (
        EXPECTED_FULL_FOLLOWUP_ROWS
    ):
        raise RuntimeError("Full-follow-up common-support sample changed")
    if int(np.count_nonzero(conditional & support["eligible"])) != (
        EXPECTED_HEADLINE_ROWS
    ):
        raise RuntimeError("Conditional-choice common-support sample changed")

    reproductions: list[dict[str, Any]] = []
    reproduction_specs = (
        (
            "first_subsequent_kind_draw",
            conditional,
            "primary_total_path_conditional_choice",
        ),
        (
            "reached_fair_chooser_within_90d",
            full_followup,
            "mandatory_reach_companion",
        ),
        (
            "any_fair_kind_grant_within_90d",
            full_followup,
            "mandatory_unconditional_kind_companion",
        ),
    )
    for outcome, sample, label in reproduction_specs:
        row = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name=outcome,
            sample=sample,
            estimand=label,
            state_conditioned=False,
            binary_outcome=True,
        )
        assert_reproduction(row, label)
        row["audit_status"] = "certified_exact_reproduction"
        reproductions.append(row)
        print(
            f"CERTIFIED_MODEL_REPRODUCED_OK estimand={label} "
            f"rows={int(row['rows']):,} "
            f"coefficient_pp={float(row['coefficient_percentage_points']):.6f}",
            flush=True,
        )

    first_kind = np.asarray(
        data["first_subsequent_kind_draw"], dtype=np.float64
    )
    if np.any(~np.isfinite(first_kind[reached])):
        raise RuntimeError("Reached recipients have missing first-choice outcomes")
    zero_coded = np.zeros(first_kind.size, dtype=np.float64)
    zero_coded[reached] = first_kind[reached]
    if np.any((zero_coded != 0.0) & (zero_coded != 1.0)):
        raise RuntimeError("Zero-coded first-choice outcome is not binary")
    data["first_subsequent_kind_draw_zero_nonreacher"] = zero_coded
    label = "post_result_unconditional_first_opportunity_zero_nonreacher"
    result = base.fit_recipient_outcome(
        data=data,
        support=support,
        outcome_name="first_subsequent_kind_draw_zero_nonreacher",
        sample=full_followup,
        estimand=label,
        state_conditioned=False,
        binary_outcome=True,
    )
    result.update(
        {
            "audit_label": label,
            "post_result_secondary": True,
            "primary_holm_family_reopened": False,
            "nonreacher_rule": "zero",
            "reacher_rule": "first_subsequent_kind_draw",
            "followup_requirement": "complete_90d_panel_coverage",
        }
    )
    exact_counts = (
        int(result["rows"]),
        int(result["treated_rows"]),
        int(result["control_rows"]),
    )
    if exact_counts != (
        EXPECTED_FULL_FOLLOWUP_ROWS,
        EXPECTED_FULL_FOLLOWUP_TREATED,
        EXPECTED_FULL_FOLLOWUP_CONTROL,
    ):
        raise RuntimeError(f"New unconditional sample changed: {exact_counts}")
    print(
        "A1_UNCONDITIONAL_FIRST_OPPORTUNITY_OK "
        f"rows={int(result['rows']):,} "
        f"coefficient_pp={float(result['coefficient_percentage_points']):.6f} "
        f"se_pp={float(result['standard_error_percentage_points']):.6f} "
        f"p={float(result['p_value_raw']):.6g}",
        flush=True,
    )
    sample_receipt = {
        "full_followup_rows": int(result["rows"]),
        "treated_rows": int(result["treated_rows"]),
        "control_rows": int(result["control_rows"]),
        "reached_rows": int(np.count_nonzero(conditional & support["eligible"])),
        "nonreacher_rows": int(
            np.count_nonzero(full_followup & support["eligible"] & ~reached)
        ),
        "outcome_definition": (
            "reached_fair_chooser_within_90d * first_subsequent_kind_draw"
        ),
    }
    return reproductions, result, sample_receipt


def directory_manifest(root: Path) -> list[dict[str, Any]]:
    excluded = {"_SUCCESS.json", "report_file_hashes.tsv"}
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in excluded:
            continue
        rows.append(
            {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "path": str(path.relative_to(root)),
            }
        )
    return rows


def build_report(result: dict[str, Any], stage07: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# A1 unconditional first-opportunity audit",
            "",
            "**Status:** post-result secondary sensitivity; the frozen primary family is unchanged.",
            "",
            "## Exact estimand",
            "",
            "The sample includes first-pair, arm-eligible recipients with complete 90-day panel coverage. The outcome equals the recipient's first later fair-choice kindness indicator when such an opportunity occurs and zero otherwise.",
            "",
            "## Result",
            "",
            f"- Effect: {float(result['coefficient_percentage_points']):+.6f} percentage points.",
            f"- SE: {float(result['standard_error_percentage_points']):.6f} percentage points.",
            f"- p-value: {float(result['p_value_raw']):.6g}.",
            f"- Rows: {int(result['rows']):,} ({int(result['treated_rows']):,} mercy; {int(result['control_rows']):,} claim).",
            f"- Weighted control mean: {100 * float(result['weighted_control_mean']):.4f}%.",
            "",
            "## Distinction from the existing companion",
            "",
            "The certified `mandatory_unconditional_kind_companion` is one when a recipient grants at any fair opportunity within 90 days. This audit instead preserves the headline's first-opportunity outcome and changes only the nonreacher rule.",
            "",
            "## Authentication",
            "",
            "The frozen headline, reach companion, and existing any-grant companion reproduced exactly before the new model.",
            f"Stage-07 Parquet hashes verified in this run: `{bool(stage07['parquet_hashes_verified'])}`.",
            "",
            "## Interpretation",
            "",
            "This result addresses outcome-observation selection on the same first-opportunity outcome. It remains observational because the focal opponent chooses mercy and mercy also changes the recipient's material game outcome.",
            "",
        ]
    )


def execute(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    project = args.project_root.expanduser().resolve()
    if project != PROJECT_AUTHORITY or not project.is_dir():
        raise RuntimeError(f"XT_Pro project authority is unavailable: {project}")
    if args.threads < 1 or args.hash_workers < 1:
        raise RuntimeError("Thread and hash-worker counts must be positive")
    package = script_path.parent
    base_path = (
        args.base_producer.expanduser().resolve()
        if args.base_producer
        else package / "10c_estimate_dynamic_prosociality_core.py"
    )
    base = import_base(base_path)
    core_result = (
        args.core_result_root.expanduser().resolve()
        if args.core_result_root
        else project / "output/dynamic_prosociality_core_v102" / CORE_RUN_ID
    )
    core_state = (
        args.core_state_root.expanduser().resolve()
        if args.core_state_root
        else project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    )
    stage07_root = (
        args.stage07_root.expanduser().resolve()
        if args.stage07_root
        else project / "derived/replication/analysis_panel_24m_sf100k"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project / "output/a1_unconditional_first_opportunity_audit_v100"
    )
    run_id = args.run_id or default_run_id()
    final = output_root / run_id
    staging = output_root / f".staging_{run_id}_{uuid.uuid4().hex}"
    if final.exists():
        raise RuntimeError(f"Output run already exists: {final}")
    output_root.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=False)

    core = authenticate_core_result(base, core_result)
    recipient = authenticate_private_recipient(core_state)
    stage07 = verify_stage07_files(
        base,
        stage07_root,
        workers=args.hash_workers,
        enabled=args.verify_stage07_hashes,
    )
    config = {
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(script_path),
        "base_producer_sha256": EXPECTED_BASE_PRODUCER_SHA256,
        "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "private_recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
        "stage07_success_sha256": base.EXPECTED_STAGE07_SUCCESS_SHA256,
        "stage07_parquet_hashes_requested": bool(args.verify_stage07_hashes),
        "threads": int(args.threads),
        "hash_workers": int(args.hash_workers),
        "memory_limit": str(args.memory_limit),
        "estimand": (
            "complete-90d first-opportunity kindness with nonreachers zero"
        ),
    }
    input_receipt = {
        "status": "A1_UNCONDITIONAL_FIRST_OPPORTUNITY_INPUTS_AUTHENTICATED_OK",
        "created_utc": utc_now(),
        "config_sha256": sha256_json(config),
        "core": core,
        "private_recipient": recipient,
        "stage07": stage07,
        "account_level_outputs_published": False,
    }
    atomic_write_json(staging / "receipts/input_authorities.json", input_receipt)

    reproductions, result, sample_receipt = estimate_models(
        base, Path(recipient["path"])
    )
    write_csv(staging / "results/certified_reproductions.csv", reproductions)
    write_csv(
        staging / "results/unconditional_first_opportunity.csv", [result]
    )
    atomic_write_json(staging / "receipts/sample_receipt.json", sample_receipt)
    atomic_write_text(
        staging / "A1_UNCONDITIONAL_FIRST_OPPORTUNITY_REPORT.md",
        build_report(result, stage07),
    )
    summary = {
        "status": "A1_UNCONDITIONAL_FIRST_OPPORTUNITY_AUDIT_V100_OK",
        "run_id": run_id,
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(script_path),
        "config": config,
        "config_sha256": sha256_json(config),
        "certified_reproductions": reproductions,
        "unconditional_first_opportunity": result,
        "sample_receipt": sample_receipt,
        "stage07": stage07,
        "post_result_secondary": True,
        "primary_holm_family_reopened": False,
        "account_level_outputs_published": False,
    }
    atomic_write_json(staging / "summary.json", summary)
    manifest_rows = directory_manifest(staging)
    write_csv(staging / "report_file_hashes.tsv", manifest_rows)
    # Rewrite the comma-delimited helper output as a canonical TSV manifest.
    csv_path = staging / "report_file_hashes.tsv"
    with csv_path.open(encoding="utf-8", newline="") as stream:
        parsed = list(csv.DictReader(stream))
    temporary = csv_path.with_name(csv_path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["sha256", "bytes", "path"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(parsed)
    os.replace(temporary, csv_path)
    success = {
        "status": "A1_UNCONDITIONAL_FIRST_OPPORTUNITY_AUDIT_V100_OK",
        "run_id": run_id,
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(script_path),
        "config_sha256": sha256_json(config),
        "report_manifest_sha256": sha256_file(csv_path),
        "report_files": len(manifest_rows),
        "headline_reproduced": True,
        "reach_companion_reproduced": True,
        "any_grant_companion_reproduced": True,
        "stage07_parquet_hashes_verified": bool(
            stage07["parquet_hashes_verified"]
        ),
        "account_level_outputs_published": False,
        "elapsed_seconds": time.monotonic() - started,
    }
    atomic_write_json(staging / "_SUCCESS.json", success)
    os.replace(staging, final)
    archive_base = output_root / f"a1_unconditional_first_opportunity_{run_id}"
    archive = Path(
        shutil.make_archive(
            str(archive_base),
            "zip",
            root_dir=final.parent,
            base_dir=final.name,
        )
    )
    archive_sha = sha256_file(archive)
    print(
        f"A1_UNCONDITIONAL_FIRST_OPPORTUNITY_AUDIT_V100_OK "
        f"elapsed={(time.monotonic() - started) / 60:.1f}m",
        flush=True,
    )
    print(f"public_result_root: {final}", flush=True)
    print(f"public_result_zip: {archive}", flush=True)
    print(f"public_result_zip_sha256: {archive_sha}", flush=True)
    return {
        "success": success,
        "result_root": str(final),
        "result_zip": str(archive),
        "result_zip_sha256": archive_sha,
    }


def self_test(script_path: Path) -> None:
    base_path = script_path.with_name("10c_estimate_dynamic_prosociality_core.py")
    base = import_base(base_path)
    base.run_numerical_self_test()
    _, np, _, _ = base.import_dependencies()
    reached = np.asarray([True, False, True, False])
    first = np.asarray([1.0, np.nan, 0.0, np.nan])
    zero = np.zeros(first.size, dtype=np.float64)
    zero[reached] = first[reached]
    if not np.array_equal(zero, np.asarray([1.0, 0.0, 0.0, 0.0])):
        raise RuntimeError("Zero-coded outcome construction self-test failed")
    if sha256_file(script_path) == EXPECTED_BASE_PRODUCER_SHA256:
        raise RuntimeError("Audit script was confused with the base producer")
    print("A1_UNCONDITIONAL_FIRST_OPPORTUNITY_AUDIT_V100_SELF_TEST_OK")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    script_path = Path(__file__).resolve()
    if args.self_test:
        self_test(script_path)
    if args.execute:
        execute(args, script_path)
    if not args.self_test and not args.execute:
        raise SystemExit("Pass --self-test and/or --execute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
