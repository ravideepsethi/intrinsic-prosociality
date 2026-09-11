#!/usr/bin/env python3
"""Create the isolated project view and bind the first dynamics producer."""

from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path
from typing import Any

from runner import common
from runner.bind_source import bind_source, recorded_git_state_function


A3_RUN_ID = "POOL_MAIN_WAVE2B1_A3"
CORE_RUN_ID = "POOL_MAIN_WAVE2B1_CORE"
POSTAUDIT_RUN_ID = "POOL_MAIN_WAVE2B1_POSTAUDIT"
REMAINING_RUN_ID = "POOL_MAIN_WAVE2B1_REMAINING"
FEASIBILITY_RUN_ID = "POOL_MAIN_WAVE2B1_FEASIBILITY"
SECOND_RUN_ID = "POOL_MAIN_WAVE2B1_SECOND"
C7R_RUN_ID = "POOL_MAIN_WAVE2B1_C7R"
DESIGN_RUN_ID = "POOL_MAIN_WAVE2B1_FROZEN_DESIGN_GATE"

STAGE_STATUS = "POOL_MAIN_STAGE07_ADAPTER_V100_OK"
DESIGN_STATUS = "POOL_MAIN_WAVE2B1_FROZEN_DESIGN_GATE_OK"
REENTRY_STATUS = "POOL_MAIN_WAVE2B1_REENTRY_CONTRACT_BRIDGE_OK"


def _ensure_link(target: Path, link: Path) -> None:
    target = target.resolve()
    if link.is_symlink():
        if link.resolve() != target:
            raise RuntimeError(f"Existing symlink has another target: {link}")
        return
    if link.exists():
        raise RuntimeError(f"Refusing to replace existing path in project view: {link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, link)


def _copy_exact(source: Path, destination: Path) -> None:
    if destination.is_file():
        if common.sha256_file(destination) != common.sha256_file(source):
            raise RuntimeError(f"Existing project-view source differs: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _write_legacy_manifest(root: Path) -> Path:
    manifest = root / "report_file_hashes.tsv"
    rows = common.output_manifest(root, exclude=[manifest])
    text = "sha256\tbytes\tpath\n" + "".join(
        f"{row['sha256']}\t{row['bytes']}\t{row['relative_path']}\n" for row in rows
    )
    common.atomic_text(manifest, text)
    return manifest


def _build_stage_adapter(auth: dict[str, Any], view: Path) -> dict[str, Any]:
    root = view / "derived/replication/analysis_panel_24m_sf100k"
    root.mkdir(parents=True, exist_ok=True)
    records = auth["month_records"]
    for row in records:
        _ensure_link(
            Path(row["path"]),
            root / f"month={row['month']}/analysis_panel.parquet",
        )
    path_text = "".join(
        str(root / f"month={row['month']}/analysis_panel.parquet") + "\n"
        for row in records
    )
    common.atomic_text(root / "_manifests/analysis_panel_paths.txt", path_text)
    month_text = "month,output_size_bytes,output_sha256\n" + "".join(
        f"{row['month']},{row['size_bytes']},{row['expected_sha256']}\n"
        for row in records
    )
    common.atomic_text(root / "_manifests/month_status.csv", month_text)
    authority = auth["authority"]
    schema = auth["report"]["panel_outputs"][0]["schema"]
    success_path = root / "_SUCCESS.json"
    success = {
        "status": STAGE_STATUS,
        "script_version": "pool-main-wave2b1-adapter-v1.0.0",
        "script_sha256": common.sha256_file(Path(__file__).resolve()),
        "sample_authority": common.compact_sample_lineage(auth),
        "global_qa": {
            "rows": int(authority["rows"]),
            "kind_draws": int(authority["kind_draws"]),
            "fair_rows": int(authority["fair_rows"]),
            "fair_kind_draws": int(authority["fair_kind_draws"]),
        },
        "output_schema": schema,
        "physical_files_are_symlinks_to_certified_pool_main_panel": True,
        "source_panel_mutated": False,
    }
    if success_path.is_file():
        saved = common.load_json(success_path)
        if saved != success:
            raise RuntimeError("Existing Stage-07 adapter belongs to another authority")
    else:
        common.atomic_json(success_path, success)
    return {
        "root": root,
        "success": success,
        "success_sha256": common.sha256_file(success_path),
        "producer_sha256": success["script_sha256"],
    }


def _build_design_bridge(view: Path, adapter: dict[str, Any]) -> dict[str, Any]:
    root = view / "output/dynamic_prosociality_feasibility_v101" / DESIGN_RUN_ID
    root.mkdir(parents=True, exist_ok=True)
    success_path = root / "_SUCCESS.json"
    success = {
        "status": DESIGN_STATUS,
        "script_version": "1.0.1",
        "script_sha256": common.sha256_file(Path(__file__).resolve()),
        "analysis_plan_sha256": "b11b546ea6fde608140619cffadffad1a7aab054b6fd1a9dcbee8900c98d0a6f",
        "stage07_success_sha256": adapter["success_sha256"],
        "effect_estimates_produced": False,
        "account_level_outputs_retained": False,
        "a3_all_game_chronology_linkage_run": False,
        "a1_exposure_overlap_summary": {
            "non_tournament_like": {
                "primary_90pct_mercy_retention_gate_pass": True,
                "interpretation": (
                    "Inherited frozen design decision only; new-sample support is "
                    "recomputed by the bound core producer."
                ),
            }
        },
        "outcome_selection_reopened": False,
    }
    if success_path.is_file() and common.load_json(success_path) != success:
        raise RuntimeError("Existing design bridge differs from the frozen authority")
    if not success_path.exists():
        common.atomic_json(success_path, success)
    _write_legacy_manifest(root)
    return {
        "root": root,
        "status": DESIGN_STATUS,
        "script_sha256": success["script_sha256"],
        "success_sha256": common.sha256_file(success_path),
    }


def _build_reentry_bridge(view: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    root = (
        view
        / "output/reentry_source_contract_audits"
        / "POOL_MAIN_WAVE2B1_source_contract_final_v121"
    )
    root.mkdir(parents=True, exist_ok=True)
    chronology = frozen["canonical_chronology"]
    summary_path = root / "final_audit_summary.json"
    summary = {
        "status": REENTRY_STATUS,
        "producer_ready": True,
        "version": "1.2.1",
        "script_sha256": common.sha256_file(Path(__file__).resolve()),
        "decision": {"blockers": []},
        "v110_canonical_chronology_authentication": {
            "chronology": {
                "rows_inspected": int(chronology["rows"]),
                "parquet_files": int(chronology["files"]),
                "manifest_sha256": chronology["manifest_sha256"],
            }
        },
        "clock_contract": {
            "contract_recovered": True,
            "clock_field": "disc_clock_s",
            "exact_operator": ">=",
            "exact_threshold_seconds": 347.0,
        },
        "scope": "Semantic contract bridge; no sample-dependent result imported.",
    }
    if summary_path.is_file() and common.load_json(summary_path) != summary:
        raise RuntimeError("Existing reentry bridge differs from the frozen authority")
    if not summary_path.exists():
        common.atomic_json(summary_path, summary)
    _write_legacy_manifest(root)
    return {
        "root": root,
        "status": REENTRY_STATUS,
        "script_sha256": summary["script_sha256"],
    }


def _install_sources(view: Path) -> dict[str, Path]:
    package = common.PACKAGE_ROOT
    repo = view / "replication_package"
    code = repo / "code"
    docs = repo / "docs"
    code.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    _copy_exact(package / "source/core/08_make_core_paper_results.py", code / "08_make_core_paper_results.py")
    docs_by_name = {
        "dynamic_prosociality_second_wave_analysis_plan.md": "dynamic_prosociality_second_wave_analysis_plan.md",
        "dynamic_prosociality_second_wave_source_contract_amendment.md": "dynamic_prosociality_second_wave_source_contract_amendment.md",
        "dynamic_prosociality_second_wave_implementation_amendment.md": "dynamic_prosociality_second_wave_implementation_amendment.md",
        "dynamic_prosociality_second_wave_postprimary_analysis.md": "dynamic_prosociality_second_wave_postprimary_analysis.md",
        "dynamic_prosociality_second_wave_e1_audit.md": "dynamic_prosociality_second_wave_e1_audit.md",
    }
    for source_name, target_name in docs_by_name.items():
        _copy_exact(package / "source/docs" / source_name, docs / target_name)
    adjacent = {
        "Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md": "Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md",
        "dynamic_prosociality_arm_partition_amendment.md": "Dynamic_Prosociality_Arm_Partition_Amendment_v1_0_2_2026-08-22.md",
        "dynamic_prosociality_parallel_execution_note.md": "Dynamic_Prosociality_Parallel_Execution_Note_v1_0_0_2026-08-22.md",
        "dynamic_prosociality_postoutcome_audit_plan.md": "Dynamic_Prosociality_PostOutcome_Audit_Plan_v1_0_0_2026-08-22.md",
        "dynamic_prosociality_postaudit_boolean_recovery.md": "Dynamic_Prosociality_PostAudit_Boolean_Recovery_Note_v1_0_1_2026-08-22.md",
        "dynamic_prosociality_second_wave_analysis_plan.md": "Dynamic_Prosociality_Second_Wave_Analysis_Plan_v1_0_0_2026-08-22.md",
    }
    for source_name, target_name in adjacent.items():
        source = package / "source/docs" / source_name
        _copy_exact(source, code / target_name)
    return {"repo": repo, "code": code, "docs": docs}


def prepare(
    *, project: Path, sample: Path, private_base: Path, public_base: Path
) -> dict[str, Any]:
    project = project.expanduser().resolve()
    private_base = private_base.expanduser().resolve()
    public_base = public_base.expanduser().resolve()
    auth = common.authenticate_sample(sample, verify_hashes=False)
    frozen = common.load_json(common.PACKAGE_ROOT / "authority/DYNAMICS_REBUILD_PREFLIGHT.json")
    if (frozen.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Frozen Wave-2A gate and selected sample differ")
    view = private_base / "project_view"
    view.mkdir(parents=True, exist_ok=True)
    marker = view / "POOL_MAIN_WAVE2B1_PROJECT_VIEW.json"
    marker_value = {
        "status": "POOL_MAIN_WAVE2B1_PROJECT_VIEW_OK",
        "sample_authority": common.compact_sample_lineage(auth),
        "source_project": str(project),
        "network_requests": 0,
    }
    if marker.is_file() and common.load_json(marker) != marker_value:
        raise RuntimeError("Existing project view belongs to another sample or project")
    if not marker.exists():
        common.atomic_json(marker, marker_value)
    installed = _install_sources(view)
    adapter = _build_stage_adapter(auth, view)
    design = _build_design_bridge(view, adapter)
    reentry = _build_reentry_bridge(view, frozen)
    chronology_root = (
        project
        / "derived/glicko2_replay/rating_events_replay_sorted_v2_time"
        / "events_replay_sorted_time"
    )
    if not chronology_root.is_dir():
        raise RuntimeError(f"Canonical chronology root is missing: {chronology_root}")
    _ensure_link(
        chronology_root,
        view
        / "derived/glicko2_replay/rating_events_replay_sorted_v2_time"
        / "events_replay_sorted_time",
    )
    rating_input_root = project / "derived/replication/rating_replay_inputs"
    if not rating_input_root.is_dir():
        raise RuntimeError(f"Rating replay input root is missing: {rating_input_root}")
    _ensure_link(
        rating_input_root,
        view / "derived/replication/rating_replay_inputs",
    )

    source = common.PACKAGE_ROOT / "source/dynamics/10b_build_a3_chronology_gate.py"
    generated = installed["code"] / source.name
    binding = bind_source(
        source,
        generated,
        constants={
            "PROJECT_AUTHORITY": view,
            "EXPECTED_STAGE07_STATUS": STAGE_STATUS,
            "EXPECTED_STAGE07_ROWS": int(auth["authority"]["rows"]),
            "EXPECTED_STAGE07_SUCCESS_SHA256": adapter["success_sha256"],
            "EXPECTED_STAGE07_SCRIPT_SHA256": adapter["producer_sha256"],
            "EXPECTED_V101_RUN_ID": DESIGN_RUN_ID,
            "EXPECTED_V101_STATUS": DESIGN_STATUS,
            "EXPECTED_V101_SCRIPT_SHA256": design["script_sha256"],
            "EXPECTED_V101_TRANSFER_SHA256": "design-authority-not-a-transfer",
            "EXPECTED_PRIMARY_COHORT_ROWS": int(
                frozen["new_sample_support_counts"]["a3_first_fair_recipient"]["rows"]
            ),
            "EXPECTED_GIT_HEAD": common.PUBLIC_REPOSITORY_HEAD,
            "EXPECTED_REENTRY_STATUS": REENTRY_STATUS,
            "EXPECTED_REENTRY_SCRIPT_SHA256": reentry["script_sha256"],
        },
        functions={"git_state": recorded_git_state_function()},
        receipt=private_base / "bindings/10b_build_a3_chronology_gate.json",
    )
    prepared = {
        "status": "POOL_MAIN_WAVE2B1_PROJECT_VIEW_PREPARED_OK",
        "created_at_utc": common.utc_now(),
        "project": str(project),
        "project_view": str(view),
        "sample_root": str(auth["sample_root"]),
        "public_base": str(public_base),
        "private_base": str(private_base),
        "sample_authority": common.compact_sample_lineage(auth),
        "stage07_adapter": {k: str(v) if isinstance(v, Path) else v for k, v in adapter.items() if k != "success"},
        "design_bridge": {k: str(v) if isinstance(v, Path) else v for k, v in design.items()},
        "reentry_bridge": {k: str(v) if isinstance(v, Path) else v for k, v in reentry.items()},
        "chronology_root": str(chronology_root),
        "rating_input_root": str(rating_input_root),
        "first_binding": binding,
        "run_ids": {
            "a3": A3_RUN_ID,
            "core": CORE_RUN_ID,
            "postaudit": POSTAUDIT_RUN_ID,
            "remaining": REMAINING_RUN_ID,
            "feasibility": FEASIBILITY_RUN_ID,
            "second": SECOND_RUN_ID,
            "c7r": C7R_RUN_ID,
        },
    }
    common.atomic_json(public_base / "PROJECT_VIEW_PREPARED.json", prepared)
    print(prepared["status"], flush=True)
    return prepared
