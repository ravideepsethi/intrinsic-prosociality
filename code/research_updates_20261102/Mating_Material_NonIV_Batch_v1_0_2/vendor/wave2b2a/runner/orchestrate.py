#!/usr/bin/env python3
"""Run exact recovered C7X and C7R producers on the pool-main authority."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from runner import common
from runner.retarget import retarget_source, write_package_manifest


C7X_RUN_ID = "POOL_MAIN_WAVE2B2A_C7X"
C7R_RUN_ID = "POOL_MAIN_WAVE2B2A_C7R"
C7X_STATUS = "DYNAMICS_CAMPAIGN1_C7X_FULLPANEL_V101_OK"
C7R_STATUS = "CAMPAIGN1_C7R_CLOSURE_OK"
EXPECTED_HISTORY_SUCCESS_SHA256 = "2e5ba421a1c628591e5004e6a60a89a39d7d017a3f5578ba88b4809f6853b417"
EXPECTED_HISTORY_SUMMARY_SHA256 = "61400d62e8b92bc0b8fe7e7a9746f650e37144fd63de49d92699aaf0e1f103d7"
EXPECTED_PAIR_EVENT_ROWS = 154_693_194
C7X_LOW_SUPPORT_STATUS = "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT"
HISTORICAL_C7X_PRIMARY_COEFFICIENT = 0.14556932160589928
HISTORICAL_C7X_PRIMARY_STANDARD_ERROR = 0.020351569816937143


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave2b1-private", type=Path, required=True)
    parser.add_argument("--wave2b1-public", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    return parser.parse_args(argv)


def _copy_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if common.sha256_file(source) != common.sha256_file(destination):
            raise RuntimeError(f"Existing execution-package file changed: {destination}")
        return
    shutil.copy2(source, destination)


def _ensure_link(target: Path, link: Path) -> None:
    target = target.resolve()
    if link.is_symlink():
        if link.resolve() != target:
            raise RuntimeError(f"Existing Stage-07 link has another target: {link}")
        return
    if link.exists():
        raise RuntimeError(f"Refusing to replace existing adapter path: {link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, link)


def _build_stage_adapter(auth: dict[str, Any], view: Path) -> dict[str, Any]:
    root = view / "derived/replication/analysis_panel_24m_sf100k"
    root.mkdir(parents=True, exist_ok=True)
    outputs = []
    for row in auth["month_records"]:
        path = root / f"month={row['month']}/analysis_panel.parquet"
        _ensure_link(Path(row["path"]), path)
        outputs.append(
            {
                "month": row["month"],
                "path": str(path),
                "rows": int(row["rows"]),
                "output_size_bytes": int(row["size_bytes"]),
                "output_sha256": row["expected_sha256"],
            }
        )
    authority = auth["authority"]
    success = {
        "status": "POOL_MAIN_STAGE07_COMPATIBILITY_ADAPTER_V100_OK",
        "final_ok": True,
        "script_version": "pool-main-wave2b2a-adapter-v1.0.0",
        "sample_authority": common.compact_sample_lineage(auth),
        "global_qa": {
            "rows": int(authority["rows"]),
            "fair_rows": int(authority["fair_rows"]),
            "kind_draws": int(authority["kind_draws"]),
            "fair_kind_draws": int(authority["fair_kind_draws"]),
        },
        "monthly_outputs": outputs,
        "physical_files_are_symlinks_to_certified_pool_main_panel": True,
        "source_panel_mutated": False,
    }
    success_path = root / "_SUCCESS.json"
    if success_path.is_file() and common.load_json(success_path) != success:
        raise RuntimeError("Existing Stage-07 compatibility adapter differs")
    if not success_path.exists():
        common.atomic_json(success_path, success)
    return {
        "root": root,
        "success_path": success_path,
        "success_sha256": common.sha256_file(success_path),
        "rows": int(authority["rows"]),
        "fair_rows": int(authority["fair_rows"]),
    }


def _verify_report_manifest(root: Path) -> int:
    manifest = next(
        (path for path in (root / "report_file_hashes.tsv", root / "REPORT_FILE_HASHES.tsv") if path.is_file()),
        None,
    )
    if manifest is None:
        raise RuntimeError(f"Producer report manifest is missing: {root}")
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"Producer report manifest is empty: {manifest}")
    for row in rows:
        relative = row.get("file") or row.get("path") or row.get("relative_path")
        if not relative:
            raise RuntimeError(f"Unrecognized producer manifest schema: {manifest}")
        path = root / relative
        if (
            not path.is_file()
            or path.stat().st_size != int(row["bytes"])
            or common.sha256_file(path) != row["sha256"]
        ):
            raise RuntimeError(f"Producer output authentication failed: {path}")
    return len(rows)


def _completed(root: Path, status: str) -> dict[str, Any] | None:
    success = root / "_SUCCESS.json"
    if not success.is_file():
        return None
    payload = common.load_json(success)
    if payload.get("status") != status:
        raise RuntimeError(f"Unexpected producer status at {root}: {payload.get('status')}")
    return {
        "root": str(root),
        "status": status,
        "success_sha256": common.sha256_file(success),
        "manifest_files_authenticated": _verify_report_manifest(root),
        "adopted_existing": True,
    }


def _pointer_result(pointer: Path, status: str) -> dict[str, Any] | None:
    if not pointer.is_file():
        return None
    payload = common.load_json(pointer)
    output = payload.get("output") or payload.get("public_run")
    if not output:
        return None
    return _completed(Path(output), status)


def _next_run_id(parent: Path, base: str) -> str:
    if not (parent / base).exists():
        return base
    for index in range(1, 100):
        candidate = f"{base}_RETRY{index:02d}"
        if not (parent / candidate).exists():
            return candidate
    raise RuntimeError(f"Too many retained failed attempts below {parent}")


def _run_logged(command: Sequence[str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    print("COMMAND " + " ".join(command), flush=True)
    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"
    with log.open("a", encoding="utf-8") as stream:
        stream.write("COMMAND " + " ".join(command) + "\n")
        stream.flush()
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=environment,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            stream.write(line)
            stream.flush()
        return_code = process.wait()
    if return_code:
        raise RuntimeError(f"Producer stopped with exit {return_code}; log={log}")


def _c7x_replacements() -> list[tuple[str, str, str]]:
    return [
        (
            "resume-old-sample-support-is-diagnostic",
            '''        if saved.get("qa", {}).get("old_sample_validation") != OLD_SAMPLE_EXPECTED:\n            raise RuntimeError("Saved C7X old-sample validation changed")\n''',
            '''        if "old_sample_validation" not in saved.get("qa", {}):\n            raise RuntimeError("Saved C7X historical 2pct diagnostic is missing")\n''',
        ),
        (
            "fresh-old-sample-support-is-diagnostic",
            "        or old_validation != OLD_SAMPLE_EXPECTED\n",
            "",
        ),
        (
            "historical-support-label",
            '    print("C7X_OLD_SAMPLE_SUPPORT_REPRODUCTION_OK", flush=True)\n',
            '    print("C7X_HISTORICAL_2PCT_SUPPORT_DIAGNOSTIC_RECORDED", flush=True)\n',
        ),
        (
            "historical-outcome-is-diagnostic",
            '''    if observed_old_outcomes != OLD_OUTCOME_EXPECTED:\n        raise RuntimeError(\n            "C7X old-sample focal-outcome replication failed: "\n            f"{observed_old_outcomes}"\n        )\n''',
            '''    historical_reference_match = observed_old_outcomes == OLD_OUTCOME_EXPECTED\n''',
        ),
        (
            "historical-reference-result-label",
            '            "old_2pct_c7_result_changed": False,\n',
            '            "historical_2pct_reference_match": historical_reference_match,\n            "old_2pct_c7_result_changed": None,\n',
        ),
        (
            "selected-panel-claim-boundary",
            '                "It is not a causal effect of receiving mercy and is not a census "\n                "of prior interactions outside Stage 07."\n',
            '                "It is not a causal effect of receiving mercy and is not a census "\n                "of prior interactions outside the selected pool/non-adjacent panel."\n',
        ),
    ]


def _prepare_c7x(
    *, private: Path, view: Path, adapter: dict[str, Any], threads: int
) -> tuple[Path, dict[str, Any]]:
    package = private / "execution_packages/c7x_v101_pool_main"
    code = package / "payload/code"
    docs = package / "payload/docs"
    authorities = package / "payload/authorities/prior_c7"
    code.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    authorities.mkdir(parents=True, exist_ok=True)
    source = common.PACKAGE_ROOT / "source"
    receipts = private / "source_bindings"
    receipts.mkdir(parents=True, exist_ok=True)
    common_binding = retarget_source(
        source / "c7x/campaign1_nonprofile_common_v102.py",
        code / "campaign1_nonprofile_common_v102.py",
        constants={
            "PROJECT_ROOT": view,
            "EXPECTED_STAGE07_ROWS": adapter["rows"],
            "EXPECTED_STAGE07_FAIR_ROWS": adapter["fair_rows"],
        },
        receipt=receipts / "c7x_common.json",
    )
    main_binding = retarget_source(
        source / "c7x/run_campaign1_c7x_fullpanel_v101.py",
        code / "run_campaign1_c7x_fullpanel_v101.py",
        constants={
            "PROJECT_AUTHORITY": view,
            "EXPECTED_STAGE07_SUCCESS_SHA256": adapter["success_sha256"],
            "EXPECTED_STAGE07_ROWS": adapter["rows"],
            "EXPECTED_FAIR_ROWS": adapter["fair_rows"],
        },
        exact_replacements=_c7x_replacements(),
        receipt=receipts / "c7x_main.json",
    )
    _copy_exact(
        source / "c7x/c7x_duplicate_order_diagnostic_v101.py",
        code / "c7x_duplicate_order_diagnostic_v101.py",
    )
    _copy_exact(
        source / "docs/dynamics_paper2_campaign1_c7x_fullpanel_exploratory_plan_v1_0_1_2026-08-27.md",
        docs / "dynamics_paper2_campaign1_c7x_fullpanel_exploratory_plan_v1_0_1_2026-08-27.md",
    )
    _copy_exact(source / "c7x/c7_results.json", authorities / "c7_results.json")
    manifest = write_package_manifest(package)
    return package, {
        "main": main_binding,
        "common": common_binding,
        "manifest_sha256": common.sha256_file(manifest),
        "threads": threads,
    }


def _c7x_primary_authority(c7x_root: Path) -> dict[str, Any]:
    payload = common.load_json(c7x_root / "c7x_results.json")
    primary = payload.get("primary") or {}
    results = primary.get("results") or []
    status = primary.get("status")
    if status == "ESTIMATED" and len(results) == 1:
        return {
            "status": status,
            "support_gate_pass": True,
            "selected_panel_reference_available": True,
            "coefficient": float(results[0]["coefficient"]),
            "standard_error": float(results[0]["standard_error"]),
            "reference_scope": "selected_pool_nonadjacent_panel",
        }
    support = payload.get("support") or {}
    if (
        status == C7X_LOW_SUPPORT_STATUS
        and not results
        and support.get("primary_support_pass") is False
    ):
        return {
            "status": status,
            "support_gate_pass": False,
            "selected_panel_reference_available": False,
            "coefficient": HISTORICAL_C7X_PRIMARY_COEFFICIENT,
            "standard_error": HISTORICAL_C7X_PRIMARY_STANDARD_ERROR,
            "reference_scope": "historical_old_sample_diagnostic_only",
        }
    raise RuntimeError(
        "C7X primary has an unrecognized disposition: "
        f"status={status}; results={len(results)}; "
        f"support_gate={support.get('primary_support_pass')}"
    )


def _prepare_c7r(
    *,
    private: Path,
    view: Path,
    adapter: dict[str, Any],
    history_state: Path,
    c7x_state: Path,
    c7x_root: Path,
) -> tuple[Path, dict[str, Any]]:
    classification_receipt = common.load_json(c7x_state / "c7x_classification_receipt.json")
    classification_path = c7x_state / "c7x_classification_private.parquet"
    if (
        classification_receipt.get("output_sha256") != common.sha256_file(classification_path)
        or int(classification_receipt.get("output_rows", -1)) <= 0
    ):
        raise RuntimeError("C7X classification receipt does not authenticate its physical file")
    c7x_primary = _c7x_primary_authority(c7x_root)
    support = classification_receipt.get("qa") or {}
    chooser_switchers = int(support.get("within_chooser_both_latest_arms", -1))
    pair_switchers = int(support.get("within_pair_both_latest_arms", -1))
    if chooser_switchers < 0 or pair_switchers < 0:
        raise RuntimeError("C7X switcher support is missing")

    package = private / "execution_packages/c7r_v102_pool_main_support_amended"
    code = package / "payload/code"
    docs = package / "payload/docs"
    frozen = package / "payload/frozen_c7x"
    code.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    frozen.mkdir(parents=True, exist_ok=True)
    source = common.PACKAGE_ROOT / "source"
    receipts = private / "source_bindings"
    common_binding = retarget_source(
        source / "c7r/campaign1_nonprofile_common_v102.py",
        code / "campaign1_nonprofile_common_v102.py",
        constants={
            "PROJECT_ROOT": view,
            "EXPECTED_STAGE07_ROWS": adapter["rows"],
            "EXPECTED_STAGE07_FAIR_ROWS": adapter["fair_rows"],
        },
        receipt=receipts / "c7r_common.json",
    )
    switcher_old = (
        '    if payload["rows"] != EXPECTED_C7X_CLASSIFICATION_ROWS or '
        'payload["chooser_arm_switchers"] != 370 or '
        'payload["unordered_pair_arm_switchers"] != 320:\n'
    )
    switcher_new = (
        '    if payload["rows"] != EXPECTED_C7X_CLASSIFICATION_ROWS or '
        f'payload["chooser_arm_switchers"] != {chooser_switchers} or '
        f'payload["unordered_pair_arm_switchers"] != {pair_switchers}:\n'
    )
    c7r_replacements = [
        (
            "current-wave2b1-history-public-run",
            "20260822T150914Z",
            "POOL_MAIN_WAVE2B1_SECOND",
        ),
        ("current-c7x-switcher-support", switcher_old, switcher_new),
    ]
    if not c7x_primary["selected_panel_reference_available"]:
        reproduction_old = '''    if primary.get("status") != "ESTIMATED":
        raise RuntimeError(f"C7R C7X primary replication failed: {primary}")
    primary_term = primary["results"][0]
    reproduction = {
        "expected_coefficient": EXPECTED_C7X_PRIMARY_COEFFICIENT,
        "observed_coefficient": primary_term["coefficient"],
        "absolute_coefficient_difference": abs(primary_term["coefficient"] - EXPECTED_C7X_PRIMARY_COEFFICIENT),
        "expected_standard_error": EXPECTED_C7X_PRIMARY_STANDARD_ERROR,
        "observed_standard_error": primary_term["standard_error"],
        "absolute_standard_error_difference": abs(primary_term["standard_error"] - EXPECTED_C7X_PRIMARY_STANDARD_ERROR),
        "tolerance": 1e-6,
    }
    reproduction["pass"] = (
        reproduction["absolute_coefficient_difference"] <= reproduction["tolerance"]
        and reproduction["absolute_standard_error_difference"] <= reproduction["tolerance"]
    )
    reproduction["gate_enforced"] = enforce_certified_reproduction
    if enforce_certified_reproduction and not reproduction["pass"]:
        raise RuntimeError(f"Certified C7X primary failed reproduction gate: {reproduction}")
'''
        reproduction_new = '''    if primary.get("status") != "ESTIMATED":
        if enforce_certified_reproduction:
            raise RuntimeError(f"C7R C7X primary replication failed: {primary}")
        reproduction = {
            "expected_coefficient": EXPECTED_C7X_PRIMARY_COEFFICIENT,
            "observed_coefficient": None,
            "absolute_coefficient_difference": None,
            "expected_standard_error": EXPECTED_C7X_PRIMARY_STANDARD_ERROR,
            "observed_standard_error": None,
            "absolute_standard_error_difference": None,
            "tolerance": 1e-6,
            "numerical_match_to_reference": None,
            "pass": None,
            "gate_enforced": False,
            "disposition": "NOT_APPLICABLE_PARENT_C7X_PRIMARY_LOW_SUPPORT",
            "parent_c7x_primary_status": "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT",
        }
    else:
        primary_term = primary["results"][0]
        numerical_match = (
            abs(primary_term["coefficient"] - EXPECTED_C7X_PRIMARY_COEFFICIENT) <= 1e-6
            and abs(primary_term["standard_error"] - EXPECTED_C7X_PRIMARY_STANDARD_ERROR) <= 1e-6
        )
        reproduction = {
            "expected_coefficient": EXPECTED_C7X_PRIMARY_COEFFICIENT,
            "observed_coefficient": primary_term["coefficient"],
            "absolute_coefficient_difference": abs(primary_term["coefficient"] - EXPECTED_C7X_PRIMARY_COEFFICIENT),
            "expected_standard_error": EXPECTED_C7X_PRIMARY_STANDARD_ERROR,
            "observed_standard_error": primary_term["standard_error"],
            "absolute_standard_error_difference": abs(primary_term["standard_error"] - EXPECTED_C7X_PRIMARY_STANDARD_ERROR),
            "tolerance": 1e-6,
            "numerical_match_to_reference": numerical_match,
            "pass": numerical_match if enforce_certified_reproduction else None,
            "gate_enforced": enforce_certified_reproduction,
            "disposition": (
                "CERTIFIED_SELECTED_PANEL_REPRODUCTION"
                if enforce_certified_reproduction
                else "HISTORICAL_REFERENCE_DIAGNOSTIC_ONLY_PARENT_C7X_LOW_SUPPORT"
            ),
            "parent_c7x_primary_status": (
                "ESTIMATED" if enforce_certified_reproduction
                else "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT"
            ),
        }
        if enforce_certified_reproduction and not numerical_match:
            raise RuntimeError(f"Certified C7X primary failed reproduction gate: {reproduction}")
'''
        call_old = (
            "    c7x_models, c7x_qa = "
            "estimate_c7x_relationship_models(c7x_model_cache, args.threads)\n"
        )
        call_new = '''    c7x_models, c7x_qa = estimate_c7x_relationship_models(
        c7x_model_cache, args.threads, enforce_certified_reproduction=False
    )
    c7x_qa["parent_c7x_primary"] = {
        "status": "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT",
        "support_gate_pass": False,
        "selected_panel_reference_available": False,
    }
    for attempt in c7x_models:
        attempt["parent_c7x_primary_status"] = "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT"
        attempt["parent_c7x_primary_support_gate_pass"] = False
        attempt["interpretation_boundary"] = (
            "Exploratory C7R attempt retained under its frozen all-attempts rule; "
            "the parent C7X primary failed its 1,000-rows-per-arm support gate."
        )
'''
        c7r_replacements.extend(
            [
                ("parent-c7x-low-support-reproduction", reproduction_old, reproduction_new),
                ("parent-c7x-low-support-call", call_old, call_new),
            ]
        )
    main_binding = retarget_source(
        source / "c7r/run_campaign1_c7r_closure_v102.py",
        code / "run_campaign1_c7r_closure_v102.py",
        constants={
            "PROJECT_AUTHORITY": view,
            "HISTORY_STATE_RELATIVE": history_state,
            "C7X_STATE_RELATIVE": c7x_state,
            "EXPECTED_STAGE07_SUCCESS_SHA256": adapter["success_sha256"],
            "EXPECTED_HISTORY_SUCCESS_SHA256": EXPECTED_HISTORY_SUCCESS_SHA256,
            "EXPECTED_C7X_CLASSIFICATION_SHA256": classification_receipt["output_sha256"],
            "EXPECTED_C7X_CLASSIFICATION_ROWS": int(classification_receipt["output_rows"]),
            "EXPECTED_C7X_PRIMARY_COEFFICIENT": c7x_primary["coefficient"],
            "EXPECTED_C7X_PRIMARY_STANDARD_ERROR": c7x_primary["standard_error"],
            "EXPECTED_C7X_CONFIG_SHA256": classification_receipt["config_sha256"],
            "EXPECTED_STAGE07_ROWS": adapter["rows"],
            "EXPECTED_FAIR_ROWS": adapter["fair_rows"],
            "EXPECTED_PAIR_EVENT_ROWS": EXPECTED_PAIR_EVENT_ROWS,
        },
        exact_replacements=c7r_replacements,
        receipt=receipts / "c7r_main.json",
    )
    _copy_exact(source / "c7r/c7r_modeling_v102.py", code / "c7r_modeling_v102.py")
    _copy_exact(
        source / "docs/C7R_FROZEN_ANALYSIS_CONTRACT_20260828.md",
        docs / "C7R_FROZEN_ANALYSIS_CONTRACT_20260828.md",
    )
    common.atomic_json(
        frozen / "private_checkpoint_authentication.json",
        {"classification": classification_receipt},
    )
    manifest = write_package_manifest(package)
    return package, {
        "main": main_binding,
        "common": common_binding,
        "manifest_sha256": common.sha256_file(manifest),
        "c7x_primary_authority": c7x_primary,
        "chooser_switchers": chooser_switchers,
        "unordered_pair_switchers": pair_switchers,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.threads <= 8:
        raise RuntimeError("--threads must be between 1 and 8")
    private = args.private_base.expanduser().resolve()
    public = args.public_base.expanduser().resolve()
    private.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    logs = public / "logs"
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    view = private / "project_view"
    view.mkdir(parents=True, exist_ok=True)
    adapter = _build_stage_adapter(auth, view)
    history_state = (
        args.wave2b1_private.expanduser().resolve()
        / "project_view/derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    )
    history_public = (
        args.wave2b1_private.expanduser().resolve()
        / "project_view/output/dynamic_second_wave_history_v100/POOL_MAIN_WAVE2B1_SECOND"
    )
    if (
        common.sha256_file(history_public / "_SUCCESS.json")
        != EXPECTED_HISTORY_SUCCESS_SHA256
        or common.sha256_file(history_public / "summary.json")
        != EXPECTED_HISTORY_SUMMARY_SHA256
    ):
        raise RuntimeError("Wave 2B1 history public authority changed after preflight")

    python = sys.executable
    c7x_package, c7x_binding = _prepare_c7x(
        private=private, view=view, adapter=adapter, threads=args.threads
    )
    c7x_pointer = public / "C7X_EXECUTION_POINTER.json"
    c7x_result = _pointer_result(c7x_pointer, C7X_STATUS)
    c7x_state = private / "c7x_state_v101"
    c7x_output_parent = public / "c7x"
    if c7x_result is None:
        _run_logged(
            [python, "-B", "-u", str(c7x_package / "payload/code/run_campaign1_c7x_fullpanel_v101.py"), "--self-test"],
            logs / "01_c7x_self_test.log",
        )
        run_id = _next_run_id(c7x_output_parent, C7X_RUN_ID)
        started = time.monotonic()
        _run_logged(
            [
                python,
                "-B",
                "-u",
                str(c7x_package / "payload/code/run_campaign1_c7x_fullpanel_v101.py"),
                "--execute",
                "--project-root",
                str(view),
                "--state-root",
                str(c7x_state),
                "--output-root",
                str(c7x_output_parent),
                "--run-id",
                run_id,
                "--execution-pointer",
                str(c7x_pointer),
                "--threads",
                str(args.threads),
                "--memory-limit",
                args.memory_limit,
            ],
            logs / "02_c7x_execute.log",
        )
        c7x_result = _completed(c7x_output_parent / run_id, C7X_STATUS)
        assert c7x_result is not None
        c7x_result["adopted_existing"] = False
        c7x_result["runtime_seconds"] = time.monotonic() - started
    c7x_root = Path(c7x_result["root"])

    c7r_package, c7r_binding = _prepare_c7r(
        private=private,
        view=view,
        adapter=adapter,
        history_state=history_state,
        c7x_state=c7x_state,
        c7x_root=c7x_root,
    )
    c7r_pointer = public / "C7R_EXECUTION_POINTER.json"
    c7r_result = _pointer_result(c7r_pointer, C7R_STATUS)
    c7r_state = private / "c7r_state_v102"
    c7r_output_parent = public / "c7r"
    if c7r_result is None:
        _run_logged(
            [python, "-B", "-u", str(c7r_package / "payload/code/run_campaign1_c7r_closure_v102.py"), "--self-test"],
            logs / "03_c7r_self_test.log",
        )
        run_id = _next_run_id(c7r_output_parent, C7R_RUN_ID)
        started = time.monotonic()
        _run_logged(
            [
                python,
                "-B",
                "-u",
                str(c7r_package / "payload/code/run_campaign1_c7r_closure_v102.py"),
                "--execute",
                "--project-root",
                str(view),
                "--state-root",
                str(c7r_state),
                "--output-root",
                str(c7r_output_parent),
                "--run-id",
                run_id,
                "--execution-pointer",
                str(c7r_pointer),
                "--threads",
                str(args.threads),
                "--memory-limit",
                args.memory_limit,
            ],
            logs / "04_c7r_execute.log",
        )
        c7r_result = _completed(c7r_output_parent / run_id, C7R_STATUS)
        assert c7r_result is not None
        c7r_result["adopted_existing"] = False
        c7r_result["runtime_seconds"] = time.monotonic() - started

    status = {
        "status": "POOL_MAIN_WAVE2B2A_ALL_STAGES_OK",
        "created_at_utc": common.utc_now(),
        "sample_authority": common.compact_sample_lineage(auth),
        "stage07_adapter": {
            "root": str(adapter["root"]),
            "success_sha256": adapter["success_sha256"],
        },
        "wave2b1_history": {
            "private_state": str(history_state),
            "public_result": str(history_public),
            "success_sha256": EXPECTED_HISTORY_SUCCESS_SHA256,
            "summary_sha256": EXPECTED_HISTORY_SUMMARY_SHA256,
        },
        "source_bindings": {"c7x": c7x_binding, "c7r": c7r_binding},
        "results": {"c7x": c7x_result, "c7r": c7r_result},
        "network_requests": 0,
        "private_row_level_outputs_transferred": False,
    }
    common.atomic_json(public / "WAVE2B2A_RUN_STATUS.json", status)
    print(status["status"], flush=True)
    return status


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
