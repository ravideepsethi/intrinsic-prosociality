#!/usr/bin/env python3
"""Run the pool-main Wave 2B1 dynamics chain in an isolated project view.

The public producers in this package were written against the former Stage-07
authority.  This runner does not edit their estimators.  Instead, immediately
before each producer runs, it renders a syntax-checked copy in which only the
module-level authority constants and repository-state guard are rebound to the
authenticated pool/non-adjacent sample and the just-completed upstream files.
"""

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
from typing import Any, Callable, Sequence

from runner import common, prepare
from runner.bind_source import (
    bind_source,
    recorded_git_dict_function,
    recorded_git_state_function,
    recorded_git_string_function,
)


A1_EVIDENCE_RUN_ID = "POOL_MAIN_WAVE2B1_A1_EVIDENCE"
A1_UNCONDITIONAL_RUN_ID = "POOL_MAIN_WAVE2B1_A1_UNCONDITIONAL"
POSTPRIMARY_RUN_ID = prepare.SECOND_RUN_ID + "_postprimary_v100"
E1_AUDIT_RUN_ID = prepare.SECOND_RUN_ID + "_e1_audit_v101"

STAGES = (
    "a3_gate",
    "dynamic_core",
    "postoutcome_audit",
    "remaining_a1_a2",
    "a1_evidence_gap",
    "a1_unconditional",
    "second_wave_feasibility",
    "b2_first_grant",
    "second_wave_histories",
    "second_wave_results",
    "second_wave_postprimary",
    "e1_numerical_audit",
    "c7r_first_repeat",
)

EXPECTED_STATUSES = {
    "a3_gate": "A3_CHRONOLOGY_POOLED_FEASIBILITY_GATE_OK",
    "dynamic_core": "DYNAMIC_PROSOCIALITY_CORE_V102_OK",
    "postoutcome_audit": "DYNAMIC_PROSOCIALITY_POSTOUTCOME_AUDIT_V101_OK",
    "remaining_a1_a2": "REMAINING_DYNAMIC_COMPLETION_V100_OK",
    "a1_evidence_gap": "A1_EVIDENCE_GAP_AUDIT_V100_OK",
    "a1_unconditional": "A1_UNCONDITIONAL_FIRST_OPPORTUNITY_AUDIT_V100_OK",
    "second_wave_feasibility": "DYNAMIC_SECOND_WAVE_FEASIBILITY_V100_OK",
    "b2_first_grant": "DYNAMIC_SECOND_WAVE_B2_V100_OK",
    "second_wave_histories": "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK",
    "second_wave_results": "DYNAMIC_SECOND_WAVE_RESULTS_V100_OK",
    "second_wave_postprimary": "DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_OK",
    "e1_numerical_audit": "DYNAMIC_SECOND_WAVE_E1_AUDIT_V101_OK",
    "c7r_first_repeat": "C7R_FULLPANEL_PREFOCAL_V100_OK",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--worker-memory", default="3GB")
    parser.add_argument("--batch-rows", type=int, default=500_000)
    parser.add_argument("--start-at", choices=STAGES, default=STAGES[0])
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    return common.load_json(path)


def sha(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"Required authority is missing: {path}")
    return common.sha256_file(path)


def q(path: Path) -> str:
    return str(path.resolve())


def verify_report_manifest(root: Path) -> int:
    """Verify a producer manifest without assuming its column ordering/case."""
    candidates = (root / "report_file_hashes.tsv", root / "REPORT_FILE_HASHES.tsv")
    manifest = next((path for path in candidates if path.is_file()), None)
    if manifest is None:
        raise RuntimeError(f"Result hash manifest is missing: {root}")
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"Result hash manifest is empty: {manifest}")
    for row in rows:
        relative = row.get("path") or row.get("relative_path")
        digest = row.get("sha256")
        size = row.get("bytes")
        if relative is None or digest is None or size is None:
            raise RuntimeError(f"Unrecognized result manifest schema: {manifest}")
        candidate = root / relative
        if not candidate.is_file():
            raise RuntimeError(f"Result member is missing: {candidate}")
        if candidate.stat().st_size != int(size) or common.sha256_file(candidate) != digest:
            raise RuntimeError(f"Result member checksum failed: {candidate}")
    return len(rows)


def completed_result(root: Path, expected_status: str) -> dict[str, Any] | None:
    success = root / "_SUCCESS.json"
    if not success.is_file():
        return None
    saved = load_json(success)
    if saved.get("status") != expected_status:
        raise RuntimeError(
            f"Existing result has unexpected status: {root}: {saved.get('status')!r}"
        )
    files = verify_report_manifest(root)
    return {
        "root": str(root),
        "status": expected_status,
        "success_sha256": sha(success),
        "summary_sha256": sha(root / "summary.json") if (root / "summary.json").is_file() else None,
        "manifest_files_authenticated": files,
        "adopted_existing": True,
    }


def execute_stage(
    *,
    name: str,
    command: Sequence[str],
    result_root: Path,
    expected_status: str,
    logs: Path,
) -> dict[str, Any]:
    existing = completed_result(result_root, expected_status)
    if existing is not None:
        print(f"WAVE2B1_STAGE_ADOPTED name={name} root={result_root}", flush=True)
        return existing
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{STAGES.index(name) + 1:02d}_{name}.log"
    print(f"WAVE2B1_STAGE_BEGIN name={name}", flush=True)
    print("COMMAND " + " ".join(command), flush=True)
    started = time.monotonic()
    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"
    with log_path.open("a", encoding="utf-8") as log:
        log.write("COMMAND " + " ".join(command) + "\n")
        log.flush()
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
            log.write(line)
            log.flush()
        return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(
            f"Wave 2B1 stage failed: {name}; return_code={return_code}; log={log_path}"
        )
    authenticated = completed_result(result_root, expected_status)
    if authenticated is None:
        raise RuntimeError(f"Stage returned zero but did not certify its result: {name}")
    authenticated["adopted_existing"] = False
    authenticated["runtime_seconds"] = time.monotonic() - started
    authenticated["log"] = str(log_path)
    print(f"WAVE2B1_STAGE_OK name={name} root={result_root}", flush=True)
    return authenticated


def bind(
    *,
    source_relative: str,
    destination: Path,
    constants: dict[str, Any],
    private_base: Path,
    functions: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = common.PACKAGE_ROOT / "source/dynamics" / source_relative
    receipt = private_base / "bindings" / (destination.name + ".binding.json")
    return bind_source(
        source,
        destination,
        constants=constants,
        functions=functions,
        receipt=receipt,
    )


def model(summary: dict[str, Any], estimand: str) -> dict[str, Any]:
    matches = [row for row in summary["a1_models"] if row.get("estimand") == estimand]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one A1 model named {estimand}; found {len(matches)}")
    return matches[0]


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.workers <= 32:
        raise RuntimeError("--workers must be between 1 and 32")
    if args.batch_rows < 10_000 or args.batch_rows > 5_000_000:
        raise RuntimeError("--batch-rows must be between 10,000 and 5,000,000")
    private_base = args.private_base.expanduser().resolve()
    public_base = args.public_base.expanduser().resolve()
    private_base.mkdir(parents=True, exist_ok=True)
    public_base.mkdir(parents=True, exist_ok=True)
    prepared = prepare.prepare(
        project=args.project_root,
        sample=args.sample_root,
        private_base=private_base,
        public_base=public_base,
    )
    view = Path(prepared["project_view"])
    code = view / "replication_package/code"
    docs = view / "replication_package/docs"
    stage07 = view / "derived/replication/analysis_panel_24m_sf100k"
    chronology = Path(prepared["chronology_root"])
    rating_inputs = Path(prepared["rating_input_root"])
    frozen = load_json(common.PACKAGE_ROOT / "authority/DYNAMICS_REBUILD_PREFLIGHT.json")
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    authority = auth["authority"]
    support = frozen["new_sample_support_counts"]
    recipient_support = support["a3_first_fair_recipient"]
    b1_support = support["b1_repeat_granter"]
    python = sys.executable
    workers8 = min(args.workers, 8)
    logs = public_base / "logs"
    bindings: dict[str, Any] = {"10b": prepared["first_binding"]}
    results: dict[str, Any] = {}

    roots = {
        "a3_gate": view / "output/dynamic_prosociality_a3_chronology_gate_v100" / prepare.A3_RUN_ID,
        "dynamic_core": view / "output/dynamic_prosociality_core_v102" / prepare.CORE_RUN_ID,
        "postoutcome_audit": view / "output/dynamic_prosociality_core_v102_postaudit" / prepare.POSTAUDIT_RUN_ID,
        "remaining_a1_a2": view / "output/remaining_dynamic_completion_v100" / prepare.REMAINING_RUN_ID,
        "a1_evidence_gap": view / "output/a1_evidence_gap_audit_v100" / A1_EVIDENCE_RUN_ID,
        "a1_unconditional": view / "output/a1_unconditional_first_opportunity_audit_v100" / A1_UNCONDITIONAL_RUN_ID,
        "second_wave_feasibility": view / "output/dynamic_second_wave_feasibility_v100" / prepare.FEASIBILITY_RUN_ID,
        "b2_first_grant": view / "output/dynamic_second_wave_b2_v100" / prepare.SECOND_RUN_ID,
        "second_wave_histories": view / "output/dynamic_second_wave_history_v100" / prepare.SECOND_RUN_ID,
        "second_wave_results": view / "output/dynamic_second_wave_results_v100" / prepare.SECOND_RUN_ID,
        "second_wave_postprimary": view / "output/dynamic_second_wave_postprimary_v100" / POSTPRIMARY_RUN_ID,
        "e1_numerical_audit": view / "output/dynamic_second_wave_e1_audit_v101" / E1_AUDIT_RUN_ID,
        "c7r_first_repeat": view / "output/c7r_fullpanel_prefocal_v100" / prepare.C7R_RUN_ID,
    }

    selected_start = STAGES.index(args.start_at)

    def active(stage: str) -> bool:
        position = STAGES.index(stage)
        return selected_start <= position

    def need(stage: str) -> dict[str, Any]:
        found = completed_result(roots[stage], EXPECTED_STATUSES[stage])
        if found is None:
            raise RuntimeError(
                f"Upstream stage {stage} is required but incomplete. "
                f"Resume without --start-at or start at {stage}."
            )
        results.setdefault(stage, found)
        return found

    # 1. Blinded A3 chronology gate.
    if active("a3_gate"):
        script = code / "10b_build_a3_chronology_gate.py"
        results["a3_gate"] = execute_stage(
            name="a3_gate",
            command=(
                python,
                "-u",
                q(script),
                "--project-root", q(view),
                "--analysis-plan", q(code / "Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md"),
                "--stage07-root", q(stage07),
                "--chronology-root", q(chronology),
                "--reentry-audit-root", prepared["reentry_bridge"]["root"],
                "--prior-feasibility-root", prepared["design_bridge"]["root"],
                "--state-root", q(view / "derived/replication/dynamic_prosociality_a3_chronology_gate_v100_PRIVATE"),
                "--output-root", q(view / "output/dynamic_prosociality_a3_chronology_gate_v100"),
                "--run-id", prepare.A3_RUN_ID,
                "--threads", str(args.workers),
                "--memory-limit", args.memory_limit,
                "--batch-rows", str(args.batch_rows),
                "--execute",
            ),
            result_root=roots["a3_gate"],
            expected_status=EXPECTED_STATUSES["a3_gate"],
            logs=logs,
        )
    else:
        need("a3_gate")

    a3_root = roots["a3_gate"]
    a3_success = load_json(a3_root / "_SUCCESS.json")
    a3_input = load_json(a3_root / "input_authentication.json")
    a3_private = view / "derived/replication/dynamic_prosociality_a3_chronology_gate_v100_PRIVATE/a3_30d_activity_private_no_treatment.parquet"
    a3_alias = view / "output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z"
    if not a3_alias.exists():
        os.symlink(a3_root, a3_alias)
    elif not a3_alias.is_symlink() or a3_alias.resolve() != a3_root.resolve():
        raise RuntimeError(f"C7R A3 compatibility alias is occupied: {a3_alias}")

    # 2. Frozen A1/A3/B1 core.
    core_script = code / "10c_estimate_dynamic_prosociality_core.py"
    bindings["10c"] = bind(
        source_relative="10c_estimate_dynamic_prosociality_core.py",
        destination=core_script,
        private_base=private_base,
        constants={
            "PROJECT_AUTHORITY": view,
            "EXPECTED_GIT_HEAD": common.PUBLIC_REPOSITORY_HEAD,
            "EXPECTED_STAGE07_STATUS": prepare.STAGE_STATUS,
            "EXPECTED_STAGE07_ROWS": int(authority["rows"]),
            "EXPECTED_STAGE07_KIND_DRAWS": int(authority["kind_draws"]),
            "EXPECTED_STAGE07_FAIR_ROWS": int(authority["fair_rows"]),
            "EXPECTED_STAGE07_FAIR_KIND_DRAWS": int(authority["fair_kind_draws"]),
            "EXPECTED_STAGE07_FAIR_CHOOSERS": int(authority["fair_choosers"]),
            "EXPECTED_STAGE07_FAIR_KIND_CHOOSERS": int(authority["fair_kind_choosers"]),
            "EXPECTED_STAGE07_SUCCESS_SHA256": sha(stage07 / "_SUCCESS.json"),
            "EXPECTED_STAGE07_SCRIPT_SHA256": load_json(stage07 / "_SUCCESS.json")["script_sha256"],
            "EXPECTED_A3_GATE_RUN_ID": prepare.A3_RUN_ID,
            "EXPECTED_A3_GATE_STATUS": EXPECTED_STATUSES["a3_gate"],
            "EXPECTED_A3_GATE_SCRIPT_SHA256": a3_success["script_sha256"],
            "EXPECTED_A3_GATE_SUCCESS_SHA256": sha(a3_root / "_SUCCESS.json"),
            "EXPECTED_A3_GATE_ZIP_SHA256": "direct-run-no-intermediate-transfer",
            "EXPECTED_A3_PRIVATE_SHA256": sha(a3_private),
            "EXPECTED_A3_PRIVATE_ROWS": int(recipient_support["rows"]),
            "EXPECTED_A3_ACCOUNTS_ANY_30D": int(
                a3_success["pooled_gate"]["accounts_any_30d"]
            ),
            "EXPECTED_RECIPIENT_MERCY": int(recipient_support["received_mercy"]),
            "EXPECTED_RECIPIENT_CLAIMED": int(recipient_support["claimed_win"]),
            "EXPECTED_RECIPIENT_NONARM": int(recipient_support["no_mating_draw"]) + int(recipient_support["chooser_loss"]),
            "EXPECTED_RECIPIENT_ARM_ELIGIBLE": int(recipient_support["received_mercy"]) + int(recipient_support["claimed_win"]),
            "EXPECTED_A3_PRIMARY": a3_success["pooled_gate"]["a3_primary_outcome_selected"],
            "EXPECTED_CHRONOLOGY_MANIFEST_SHA256": sha(a3_root / "chronology_input_manifest.tsv"),
            "EXPECTED_CHRONOLOGY_FOOTER_PLAN_SHA256": a3_input["chronology_footer_plan_sha256"],
            "EXPECTED_B1_CHOOSERS": int(b1_support["choosers"]),
            "EXPECTED_B1_OPPORTUNITIES": int(b1_support["opportunities"]),
            "EXPECTED_B1_KIND_DRAWS": int(b1_support["kind_draws"]),
        },
        functions={"git_state": recorded_git_state_function()},
    )
    if active("dynamic_core"):
        results["dynamic_core"] = execute_stage(
            name="dynamic_core",
            command=(
                python, "-u", q(core_script),
                "--project-root", q(view),
                "--analysis-plan", q(code / "Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md"),
                "--arm-amendment", q(code / "Dynamic_Prosociality_Arm_Partition_Amendment_v1_0_2_2026-08-22.md"),
                "--stage07-root", q(stage07),
                "--a3-gate-root", q(a3_root),
                "--a3-private-cache", q(a3_private),
                "--chronology-root", q(chronology),
                "--state-root", q(view / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"),
                "--output-root", q(view / "output/dynamic_prosociality_core_v102"),
                "--run-id", prepare.CORE_RUN_ID,
                "--threads", str(args.workers),
                "--chronology-workers", str(min(args.workers, 4)),
                "--b1-workers", str(min(args.workers, 5)),
                "--memory-limit", args.memory_limit,
                "--batch-rows", str(args.batch_rows),
                "--execute",
            ),
            result_root=roots["dynamic_core"],
            expected_status=EXPECTED_STATUSES["dynamic_core"],
            logs=logs,
        )
    else:
        need("dynamic_core")

    core_root = roots["dynamic_core"]
    core_state = view / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    core_summary = load_json(core_root / "summary.json")
    core_hashes = {
        "success": sha(core_root / "_SUCCESS.json"),
        "summary": sha(core_root / "summary.json"),
        "manifest": sha(core_root / "report_file_hashes.tsv"),
        "recipient": sha(core_state / "recipient_with_chronology_private.parquet"),
        "overlap": sha(core_state / "recipient_overlap_propensity_private.parquet"),
        "b1_sample": sha(core_state / "b1_repeat_granter_private.parquet"),
        "b1_propensity": sha(core_state / "b1_crossfit_propensity_private.parquet"),
    }

    # 3. Core post-outcome audit.
    post_script = code / "10d_audit_dynamic_prosociality_core.py"
    bindings["10d"] = bind(
        source_relative="10d_audit_dynamic_prosociality_core.py",
        destination=post_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "CORE_RUN_ID": prepare.CORE_RUN_ID,
            "EXPECTED_CORE_SUCCESS_SHA256": core_hashes["success"],
            "EXPECTED_CORE_SUMMARY_SHA256": core_hashes["summary"],
            "EXPECTED_CORE_MANIFEST_SHA256": core_hashes["manifest"],
            "EXPECTED_PRIVATE_RECIPIENT_SHA256": core_hashes["recipient"],
            "EXPECTED_BASE_PRODUCER_SHA256": sha(core_script),
            "CORE_INDEX_ROWS": int(recipient_support["rows"]),
        },
    )
    if active("postoutcome_audit"):
        results["postoutcome_audit"] = execute_stage(
            name="postoutcome_audit",
            command=(
                python, "-u", q(post_script),
                "--project-root", q(view),
                "--base-producer", q(core_script),
                "--post-audit-plan", q(code / "Dynamic_Prosociality_PostOutcome_Audit_Plan_v1_0_0_2026-08-22.md"),
                "--core-result-root", q(core_root),
                "--core-state-root", q(core_state),
                "--private-state-root", q(view / "derived/replication/dynamic_prosociality_core_v102_POSTAUDIT_PRIVATE"),
                "--output-root", q(view / "output/dynamic_prosociality_core_v102_postaudit"),
                "--run-id", prepare.POSTAUDIT_RUN_ID,
                "--threads", str(args.workers),
                "--memory-limit", args.memory_limit,
                "--execute",
            ),
            result_root=roots["postoutcome_audit"],
            expected_status=EXPECTED_STATUSES["postoutcome_audit"],
            logs=logs,
        )
    elif selected_start > STAGES.index("postoutcome_audit"):
        need("postoutcome_audit")

    # 4. Remaining prespecified A1/A2 analyses.
    remaining_script = code / "12_complete_remaining_dynamic_analyses.py"
    bindings["12"] = bind(
        source_relative="12_complete_remaining_dynamic_analyses.py",
        destination=remaining_script,
        private_base=private_base,
        constants={
            "PROJECT_AUTHORITY": view,
            "CORE_RUN_ID": prepare.CORE_RUN_ID,
            "EXPECTED_BASE_CODE_SHA256": sha(core_script),
            "EXPECTED_STAGE07_SUCCESS_SHA256": sha(stage07 / "_SUCCESS.json"),
            "EXPECTED_CORE_SUCCESS_SHA256": core_hashes["success"],
            "EXPECTED_PRIVATE_RECIPIENT_SHA256": core_hashes["recipient"],
            "EXPECTED_RECIPIENT_ROWS": int(recipient_support["rows"]),
            "EXPECTED_STAGE07_ROWS": int(authority["rows"]),
        },
    )
    if active("remaining_a1_a2"):
        results["remaining_a1_a2"] = execute_stage(
            name="remaining_a1_a2",
            command=(
                python, "-u", q(remaining_script),
                "--project-root", q(view),
                "--base-code", q(core_script),
                "--run-id", prepare.REMAINING_RUN_ID,
                "--threads", str(args.workers),
                "--memory-limit", args.memory_limit,
                "--execute",
            ),
            result_root=roots["remaining_a1_a2"],
            expected_status=EXPECTED_STATUSES["remaining_a1_a2"],
            logs=logs,
        )
    elif selected_start > STAGES.index("remaining_a1_a2"):
        need("remaining_a1_a2")

    # 5-6. Post-result A1 evidence audits, parameterized by the rebuilt core.
    headline = model(core_summary, "primary_total_path_conditional_choice")
    reach = model(core_summary, "mandatory_reach_companion")
    unconditional = model(core_summary, "mandatory_unconditional_kind_companion")
    raw_reachers = [
        row for row in core_summary["a1_a3_overlap_sensitivities"]
        if row.get("estimand") == "A1_total_path_crossfit_overlap_population"
    ]
    if len(raw_reachers) != 1:
        raise RuntimeError("Rebuilt core lacks the unique raw A1 reacher audit row")

    evidence_script = code / "a1_evidence_gap_audit_v100.py"
    bindings["a1_evidence"] = bind(
        source_relative="a1_audits/a1_evidence_gap_audit_v100.py",
        destination=evidence_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "CORE_RUN_ID": prepare.CORE_RUN_ID,
            "EXPECTED_BASE_PRODUCER_SHA256": sha(core_script),
            "EXPECTED_CORE_SUCCESS_SHA256": core_hashes["success"],
            "EXPECTED_CORE_SUMMARY_SHA256": core_hashes["summary"],
            "EXPECTED_CORE_MANIFEST_SHA256": core_hashes["manifest"],
            "EXPECTED_PRIVATE_RECIPIENT_SHA256": core_hashes["recipient"],
            "EXPECTED_OVERLAP_PROPENSITY_SHA256": core_hashes["overlap"],
            "EXPECTED_HEADLINE_COEFFICIENT": headline["coefficient"],
            "EXPECTED_HEADLINE_STANDARD_ERROR": headline["standard_error"],
            "EXPECTED_HEADLINE_ROWS": int(headline["rows"]),
            "EXPECTED_HEADLINE_TREATED": int(headline["treated_rows"]),
            "EXPECTED_HEADLINE_CONTROL": int(headline["control_rows"]),
            "EXPECTED_RAW_REACHERS": int(raw_reachers[0]["rows"]),
        },
    )
    if active("a1_evidence_gap"):
        results["a1_evidence_gap"] = execute_stage(
            name="a1_evidence_gap",
            command=(
                python, "-u", q(evidence_script),
                "--project-root", q(view),
                "--base-producer", q(core_script),
                "--core-result-root", q(core_root),
                "--core-state-root", q(core_state),
                "--stage07-root", q(stage07),
                "--private-state-root", q(view / "derived/replication/a1_evidence_gap_audit_v100_PRIVATE"),
                "--output-root", q(view / "output/a1_evidence_gap_audit_v100"),
                "--run-id", A1_EVIDENCE_RUN_ID,
                "--threads", str(args.workers),
                "--memory-limit", args.memory_limit,
                "--execute",
            ),
            result_root=roots["a1_evidence_gap"],
            expected_status=EXPECTED_STATUSES["a1_evidence_gap"],
            logs=logs,
        )
    elif selected_start > STAGES.index("a1_evidence_gap"):
        need("a1_evidence_gap")

    reproductions = {
        row["estimand"]: {
            "rows": int(row["rows"]),
            "treated_rows": int(row["treated_rows"]),
            "control_rows": int(row["control_rows"]),
            "coefficient": row["coefficient"],
            "standard_error": row["standard_error"],
        }
        for row in (headline, reach, unconditional)
    }
    unconditional_script = code / "a1_unconditional_first_opportunity_audit_v100.py"
    bindings["a1_unconditional"] = bind(
        source_relative="a1_audits/a1_unconditional_first_opportunity_audit_v100.py",
        destination=unconditional_script,
        private_base=private_base,
        constants={
            "PROJECT_AUTHORITY": view,
            "CORE_RUN_ID": prepare.CORE_RUN_ID,
            "EXPECTED_BASE_PRODUCER_SHA256": sha(core_script),
            "EXPECTED_CORE_SUCCESS_SHA256": core_hashes["success"],
            "EXPECTED_CORE_SUMMARY_SHA256": core_hashes["summary"],
            "EXPECTED_CORE_MANIFEST_SHA256": core_hashes["manifest"],
            "EXPECTED_PRIVATE_RECIPIENT_SHA256": core_hashes["recipient"],
            "EXPECTED_RECIPIENT_ROWS": int(recipient_support["rows"]),
            "EXPECTED_FULL_FOLLOWUP_ROWS": int(reach["rows"]),
            "EXPECTED_FULL_FOLLOWUP_TREATED": int(reach["treated_rows"]),
            "EXPECTED_FULL_FOLLOWUP_CONTROL": int(reach["control_rows"]),
            "EXPECTED_HEADLINE_ROWS": int(headline["rows"]),
            "EXPECTED_HEADLINE_TREATED": int(headline["treated_rows"]),
            "EXPECTED_HEADLINE_CONTROL": int(headline["control_rows"]),
            "EXPECTED_REPRODUCTIONS": reproductions,
        },
    )
    if active("a1_unconditional"):
        results["a1_unconditional"] = execute_stage(
            name="a1_unconditional",
            command=(
                python, "-u", q(unconditional_script),
                "--project-root", q(view),
                "--base-producer", q(core_script),
                "--core-result-root", q(core_root),
                "--core-state-root", q(core_state),
                "--stage07-root", q(stage07),
                "--output-root", q(view / "output/a1_unconditional_first_opportunity_audit_v100"),
                "--run-id", A1_UNCONDITIONAL_RUN_ID,
                "--threads", str(args.workers),
                "--hash-workers", str(min(args.workers, 8)),
                "--memory-limit", args.memory_limit,
                "--execute",
            ),
            result_root=roots["a1_unconditional"],
            expected_status=EXPECTED_STATUSES["a1_unconditional"],
            logs=logs,
        )
    elif selected_start > STAGES.index("a1_unconditional"):
        need("a1_unconditional")

    # 7. Second-wave feasibility gate.
    feasibility_script = code / "10e_audit_dynamic_second_wave_feasibility.py"
    bindings["10e"] = bind(
        source_relative="10e_audit_dynamic_second_wave_feasibility.py",
        destination=feasibility_script,
        private_base=private_base,
        constants={
            "EXPECTED_GIT_HEAD": common.PUBLIC_REPOSITORY_HEAD,
            "EXPECTED_STAGE07_STATUS": prepare.STAGE_STATUS,
            "EXPECTED_STAGE07_ROWS": int(authority["rows"]),
            "EXPECTED_STAGE07_FAIR_ROWS": int(authority["fair_rows"]),
            "EXPECTED_STAGE07_KIND_DRAWS": int(authority["kind_draws"]),
            "EXPECTED_STAGE07_SCRIPT_SHA256": load_json(stage07 / "_SUCCESS.json")["script_sha256"],
            "EXPECTED_STAGE07_SUCCESS_SHA256": sha(stage07 / "_SUCCESS.json"),
            "EXPECTED_CORE_RUN_ID": prepare.CORE_RUN_ID,
            "EXPECTED_CORE_SUCCESS_SHA256": core_hashes["success"],
            "EXPECTED_CORE_SCRIPT_SHA256": sha(core_script),
            "EXPECTED_B1_SAMPLE_SHA256": core_hashes["b1_sample"],
            "EXPECTED_B1_PROPENSITY_SHA256": core_hashes["b1_propensity"],
            "EXPECTED_B1_CHOOSERS": int(b1_support["choosers"]),
            "EXPECTED_B1_ROWS": int(b1_support["opportunities"]),
            "EXPECTED_B1_KIND_DRAWS": int(b1_support["kind_draws"]),
            "EXPECTED_A3_GATE_RUN_ID": prepare.A3_RUN_ID,
            "EXPECTED_A3_GATE_SUCCESS_SHA256": sha(a3_root / "_SUCCESS.json"),
            "EXPECTED_CHRONOLOGY_MANIFEST_SHA256": sha(a3_root / "chronology_input_manifest.tsv"),
        },
        functions={"git_state": recorded_git_state_function()},
    )
    if active("second_wave_feasibility"):
        results["second_wave_feasibility"] = execute_stage(
            name="second_wave_feasibility",
            command=(
                python, "-u", q(feasibility_script),
                "--project-root", q(view),
                "--analysis-plan", q(code / "Dynamic_Prosociality_Second_Wave_Analysis_Plan_v1_0_0_2026-08-22.md"),
                "--stage07-root", q(stage07),
                "--core-root", q(core_root),
                "--core-state-root", q(core_state),
                "--a3-gate-root", q(a3_root),
                "--rating-input-root", q(rating_inputs),
                "--output-root", q(view / "output/dynamic_second_wave_feasibility_v100"),
                "--run-id", prepare.FEASIBILITY_RUN_ID,
                "--threads", str(args.workers),
                "--memory-limit", args.memory_limit,
                "--execute",
            ),
            result_root=roots["second_wave_feasibility"],
            expected_status=EXPECTED_STATUSES["second_wave_feasibility"],
            logs=logs,
        )
    else:
        need("second_wave_feasibility")

    feasibility_root = roots["second_wave_feasibility"]
    feasibility_hash = sha(feasibility_root / "_SUCCESS.json")
    plan2 = docs / "dynamic_prosociality_second_wave_analysis_plan.md"
    source_amendment = docs / "dynamic_prosociality_second_wave_source_contract_amendment.md"
    implementation = docs / "dynamic_prosociality_second_wave_implementation_amendment.md"

    # 8. First-grant timing/randomization analysis.
    b2_script = code / "10f_estimate_b2_first_grant_dynamics.py"
    bindings["10f"] = bind(
        source_relative="10f_estimate_b2_first_grant_dynamics.py",
        destination=b2_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "EXPECTED_CORE_CODE_SHA256": sha(core_script),
            "EXPECTED_FEASIBILITY_SUCCESS_SHA256": feasibility_hash,
            "EXPECTED_CORE_SUCCESS_SHA256": core_hashes["success"],
            "EXPECTED_B1_SAMPLE_SHA256": core_hashes["b1_sample"],
            "EXPECTED_B1_PROPENSITY_SHA256": core_hashes["b1_propensity"],
            "EXPECTED_CHOOSERS": int(b1_support["choosers"]),
            "EXPECTED_ROWS": int(b1_support["opportunities"]),
            "EXPECTED_KIND_DRAWS": int(b1_support["kind_draws"]),
        },
        functions={"authenticate_git": recorded_git_string_function()},
    )
    if active("b2_first_grant"):
        results["b2_first_grant"] = execute_stage(
            name="b2_first_grant",
            command=(
                python, "-u", q(b2_script),
                "--project-root", q(view),
                "--core-code", q(core_script),
                "--analysis-plan", q(plan2),
                "--source-amendment", q(source_amendment),
                "--implementation-amendment", q(implementation),
                "--feasibility-root", q(feasibility_root),
                "--core-root", q(core_root),
                "--core-state", q(core_state),
                "--state-root", q(view / "derived/replication/dynamic_second_wave_b2_v100_PRIVATE"),
                "--output-root", q(view / "output/dynamic_second_wave_b2_v100"),
                "--run-id", prepare.SECOND_RUN_ID,
                "--workers", str(workers8),
                "--execute",
            ),
            result_root=roots["b2_first_grant"],
            expected_status=EXPECTED_STATUSES["b2_first_grant"],
            logs=logs,
        )
    else:
        need("b2_first_grant")
    b2_root = roots["b2_first_grant"]

    # 9. User and dyad histories over the canonical 7.76B-row chronology.
    history_script = code / "10g_build_dynamic_second_wave_histories.py"
    bindings["10g"] = bind(
        source_relative="10g_build_dynamic_second_wave_histories.py",
        destination=history_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "EXPECTED_FEASIBILITY_SUCCESS_SHA256": feasibility_hash,
            "EXPECTED_A3_SUCCESS_SHA256": sha(a3_root / "_SUCCESS.json"),
            "EXPECTED_CHRONOLOGY_MANIFEST_SHA256": sha(a3_root / "chronology_input_manifest.tsv"),
            "EXPECTED_STAGE07_SUCCESS_SHA256": sha(stage07 / "_SUCCESS.json"),
            "EXPECTED_STAGE07_ROWS": int(authority["rows"]),
            "EXPECTED_STAGE07_FAIR_ROWS": int(authority["fair_rows"]),
        },
        functions={"authenticate_git": recorded_git_string_function()},
    )
    history_state = view / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    if active("second_wave_histories"):
        results["second_wave_histories"] = execute_stage(
            name="second_wave_histories",
            command=(
                python, "-u", q(history_script),
                "--project-root", q(view),
                "--analysis-plan", q(plan2),
                "--source-amendment", q(source_amendment),
                "--implementation-amendment", q(implementation),
                "--stage07-root", q(stage07),
                "--a3-root", q(a3_root),
                "--feasibility-root", q(feasibility_root),
                "--state-root", q(history_state),
                "--output-root", q(view / "output/dynamic_second_wave_history_v100"),
                "--run-id", prepare.SECOND_RUN_ID,
                "--workers", str(workers8),
                "--worker-memory", args.worker_memory,
                "--execute",
            ),
            result_root=roots["second_wave_histories"],
            expected_status=EXPECTED_STATUSES["second_wave_histories"],
            logs=logs,
        )
    else:
        need("second_wave_histories")
    history_root = roots["second_wave_histories"]

    # 10. Prespecified second-wave results and four-slot Holm family.
    second_script = code / "10h_estimate_dynamic_second_wave.py"
    stage08 = code / "08_make_core_paper_results.py"
    bindings["10h"] = bind(
        source_relative="10h_estimate_dynamic_second_wave.py",
        destination=second_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "EXPECTED_STAGE07_SUCCESS_SHA256": sha(stage07 / "_SUCCESS.json"),
            "EXPECTED_STAGE08_SHA256": sha(stage08),
            "EXPECTED_CORE_SUCCESS_SHA256": core_hashes["success"],
            "EXPECTED_FEASIBILITY_SUCCESS_SHA256": feasibility_hash,
        },
        functions={"authenticate_git": recorded_git_string_function()},
    )
    if active("second_wave_results"):
        results["second_wave_results"] = execute_stage(
            name="second_wave_results",
            command=(
                python, "-u", q(second_script),
                "--project-root", q(view),
                "--analysis-plan", q(plan2),
                "--source-amendment", q(source_amendment),
                "--implementation-amendment", q(implementation),
                "--history-root", q(history_root),
                "--history-state", q(history_state),
                "--b2-root", q(b2_root),
                "--stage07-root", q(stage07),
                "--state-root", q(view / "derived/replication/dynamic_second_wave_estimation_v100_PRIVATE"),
                "--output-root", q(view / "output/dynamic_second_wave_results_v100"),
                "--run-id", prepare.SECOND_RUN_ID,
                "--workers", str(workers8),
                "--worker-memory", args.worker_memory,
                "--execute",
            ),
            result_root=roots["second_wave_results"],
            expected_status=EXPECTED_STATUSES["second_wave_results"],
            logs=logs,
        )
    else:
        need("second_wave_results")
    second_root = roots["second_wave_results"]

    # 11. Additional robustness and exploratory second-wave analyses.
    postprimary_script = code / "11a_estimate_dynamic_second_wave_postprimary.py"
    bindings["11a"] = bind(
        source_relative="11a_estimate_dynamic_second_wave_postprimary.py",
        destination=postprimary_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "SOURCE_RUN_ID": prepare.SECOND_RUN_ID,
            "DEFAULT_RUN_ID": POSTPRIMARY_RUN_ID,
            "EXPECTED_SOURCE_B2_SCRIPT_SHA": sha(b2_script),
            "EXPECTED_SOURCE_ESTIMATOR_SHA": sha(second_script),
            "EXPECTED_STAGE08_SHA": sha(stage08),
            "EXPECTED_SOURCE_B2_SUCCESS_SHA": sha(b2_root / "_SUCCESS.json"),
            "EXPECTED_SOURCE_HISTORY_SUCCESS_SHA": sha(history_root / "_SUCCESS.json"),
            "EXPECTED_SOURCE_RESULTS_SUCCESS_SHA": sha(second_root / "_SUCCESS.json"),
            "EXPECTED_B1_SAMPLE_SHA": core_hashes["b1_sample"],
            "EXPECTED_B1_PROPENSITY_SHA": core_hashes["b1_propensity"],
            "EXPECTED_B2_CHOOSERS": int(b1_support["choosers"]),
            "EXPECTED_B2_ROWS": int(b1_support["opportunities"]),
            "EXPECTED_B2_KIND_DRAWS": int(b1_support["kind_draws"]),
        },
        functions={"authenticate_git": recorded_git_dict_function()},
    )
    if active("second_wave_postprimary"):
        results["second_wave_postprimary"] = execute_stage(
            name="second_wave_postprimary",
            command=(
                python, "-u", q(postprimary_script),
                "--project-root", q(view),
                "--run-id", POSTPRIMARY_RUN_ID,
                "--workers", str(workers8),
                "--worker-memory", args.worker_memory,
                "--execute",
            ),
            result_root=roots["second_wave_postprimary"],
            expected_status=EXPECTED_STATUSES["second_wave_postprimary"],
            logs=logs,
        )
    else:
        need("second_wave_postprimary")
    postprimary_root = roots["second_wave_postprimary"]

    # 12. Independent E1 numerical/specification audit.
    e1_script = code / "11b_audit_dynamic_second_wave_e1.py"
    bindings["11b"] = bind(
        source_relative="11b_audit_dynamic_second_wave_e1.py",
        destination=e1_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "SOURCE_RUN_ID": prepare.SECOND_RUN_ID,
            "POSTPRIMARY_RUN_ID": POSTPRIMARY_RUN_ID,
            "DEFAULT_RUN_ID": E1_AUDIT_RUN_ID,
            "EXPECTED_ADDITIONAL_SCRIPT_SHA": sha(postprimary_script),
            "EXPECTED_SOURCE_ESTIMATOR_SHA": sha(second_script),
            "EXPECTED_STAGE08_SHA": sha(stage08),
            "EXPECTED_SOURCE_RESULTS_SUCCESS_SHA": sha(second_root / "_SUCCESS.json"),
            "EXPECTED_SOURCE_RESULTS_SUMMARY_SHA": sha(second_root / "summary.json"),
            "EXPECTED_POSTPRIMARY_SUCCESS_SHA": sha(postprimary_root / "_SUCCESS.json"),
            "EXPECTED_POSTPRIMARY_SUMMARY_SHA": sha(postprimary_root / "summary.json"),
        },
        functions={"authenticate_git": recorded_git_dict_function()},
    )
    if active("e1_numerical_audit"):
        results["e1_numerical_audit"] = execute_stage(
            name="e1_numerical_audit",
            command=(
                python, "-u", q(e1_script),
                "--project-root", q(view),
                "--run-id", E1_AUDIT_RUN_ID,
                "--workers", str(workers8),
                "--execute",
            ),
            result_root=roots["e1_numerical_audit"],
            expected_status=EXPECTED_STATUSES["e1_numerical_audit"],
            logs=logs,
        )
    else:
        need("e1_numerical_audit")

    # 13. Full-panel pre-focal first/repeat-meeting analysis.
    c7r_script = code / "run_c7r_fullpanel_prefocal_v100.py"
    bindings["c7r"] = bind(
        source_relative="c7r_fullpanel_prefocal/run_c7r_fullpanel_prefocal_v100.py",
        destination=c7r_script,
        private_base=private_base,
        constants={
            "PROJECT_ROOT": view,
            "DESKTOP_ROOT": view / "transient_transfer",
            "EXPECTED_CHRONOLOGY_MANIFEST_SHA256": sha(a3_root / "chronology_input_manifest.tsv"),
            "EXPECTED_STAGE07_SUCCESS_SHA256": sha(stage07 / "_SUCCESS.json"),
            "EXPECTED_STAGE07_ROWS": int(authority["rows"]),
            "EXPECTED_STAGE07_FAIR_ROWS": int(authority["fair_rows"]),
        },
    )
    if active("c7r_first_repeat"):
        results["c7r_first_repeat"] = execute_stage(
            name="c7r_first_repeat",
            command=(
                python, "-u", q(c7r_script),
                "--project-root", q(view),
                "--desktop-root", q(view / "transient_transfer"),
                "--state-root", q(view / "derived/replication/c7r_fullpanel_prefocal_v100_PRIVATE"),
                "--output-root", q(view / "output/c7r_fullpanel_prefocal_v100"),
                "--run-id", prepare.C7R_RUN_ID,
                "--threads", str(args.workers),
                "--memory", args.memory_limit,
                "--shards", str(min(args.workers, 8)),
                "--execute",
            ),
            result_root=roots["c7r_first_repeat"],
            expected_status=EXPECTED_STATUSES["c7r_first_repeat"],
            logs=logs,
        )

    receipt = {
        "status": (
            "POOL_MAIN_WAVE2B1_ALL_STAGES_OK"
            if selected_start == 0
            else "POOL_MAIN_WAVE2B1_REQUESTED_STAGE_RANGE_OK"
        ),
        "created_at_utc": common.utc_now(),
        "wave_version": common.WAVE_VERSION,
        "sample_authority": common.compact_sample_lineage(auth),
        "project_view": str(view),
        "stage_range": {"start_at": args.start_at, "stop_after": STAGES[-1]},
        "stages": results,
        "result_roots": {name: str(path) for name, path in roots.items()},
        "source_bindings": {
            name: {
                "generated_path": value["generated_path"],
                "generated_sha256": value["generated_sha256"],
                "source_sha256": value["source"]["sha256"],
                "estimator_function_bodies_changed": value["estimator_function_bodies_changed"],
            }
            for name, value in bindings.items()
        },
        "chooser_iv_included": False,
        "chooser_iv_disposition": (
            "Already launched as a separate authenticated branch; intentionally not duplicated. "
            "Confirm its requested role-selection decomposition when the branches are merged."
        ),
        "network_requests": 0,
    }
    common.atomic_json(public_base / "WAVE2B1_RUN_STATUS.json", receipt)
    print(receipt["status"], flush=True)
    return receipt


def main() -> int:
    args = parse_args()
    try:
        run(args)
    except Exception as exc:
        failure = {
            "status": "POOL_MAIN_WAVE2B1_FAILED_CLOSED",
            "created_at_utc": common.utc_now(),
            "type": type(exc).__name__,
            "message": str(exc),
        }
        args.public_base.expanduser().resolve().mkdir(parents=True, exist_ok=True)
        common.atomic_json(
            args.public_base.expanduser().resolve() / "WAVE2B1_FAILURE.json", failure
        )
        print(f"POOL_MAIN_WAVE2B1_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
