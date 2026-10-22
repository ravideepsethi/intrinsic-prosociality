#!/usr/bin/env python3
"""Run pool-main Wave 2B2B1: C6/C10, C12, and scoped diagnostics."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from runner import common
from runner import c6_ply_retrofit
from runner import c7x_dyad_diagnostic
from runner.retarget import retarget_source, write_package_manifest


EXPECTED_RECIPIENT_SHA256 = "55ffdfae9179007fa6437930e3a838f112b28c7906c36ff6438521214cce261b"
EXPECTED_A2_SHA256 = "23c0fc7c07bbab8c59d91ce314c4ad358b29e33127e56a71d137a21fca24bac9"
EXPECTED_A2_ROWS = 1_527_217
EXPECTED_REMAINING_SUCCESS_SHA256 = "fdf62efba7739d5e985f6b3d350157d9a348cf8be7bef4cf51fcfd156dd5e0c9"
EXPECTED_HISTORY_SUCCESS_SHA256 = "2e5ba421a1c628591e5004e6a60a89a39d7d017a3f5578ba88b4809f6853b417"
EXPECTED_C7X_SHA256 = "27e351f5bd8c493c022e2c261590d5e21e8e32ed6ab5c51d20aae8bcec46912c"
EXPECTED_C7X_ROWS = 10_481
EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"

MODULE_STATUSES = {
    "c6_c10": "POOL_MAIN_WAVE2B2B1_C6_C10_OK",
    "c6_ply": "POOL_MAIN_WAVE2B2B1_C6_PLY_RETROFIT_OK",
    "c12": "POOL_MAIN_WAVE2B2B1_C12_OK",
    "c7x_dyad": "POOL_MAIN_WAVE2B2B1_C7X_DYAD_DIAGNOSTIC_OK",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave2b1-private", type=Path, required=True)
    parser.add_argument("--wave2b1-public", type=Path, required=True)
    parser.add_argument("--wave2b2a-private", type=Path, required=True)
    parser.add_argument("--wave2b2a-public", type=Path, required=True)
    parser.add_argument("--old-frequent-state", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--batch-rows", type=int, default=500_000)
    return parser.parse_args(argv)


def _ensure_link(target: Path, link: Path) -> None:
    target = target.expanduser().resolve()
    if not target.exists():
        raise RuntimeError(f"Compatibility-link target is missing: {target}")
    if link.is_symlink():
        if link.resolve() != target:
            raise RuntimeError(f"Existing compatibility link has another target: {link}")
        return
    if link.exists():
        raise RuntimeError(f"Refusing to replace existing compatibility path: {link}")
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
        "script_version": "pool-main-wave2b2b1-adapter-v1.0.0",
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
    if success_path.is_file():
        if common.load_json(success_path) != success:
            raise RuntimeError("Existing Stage-07 compatibility adapter differs")
    else:
        common.atomic_json(success_path, success)
    return {
        "root": root,
        "success_path": success_path,
        "success_sha256": common.sha256_file(success_path),
        "rows": int(authority["rows"]),
        "fair_rows": int(authority["fair_rows"]),
    }


def _build_view(args: argparse.Namespace, auth: dict[str, Any], private: Path) -> dict[str, Any]:
    view = private / "project_view"
    view.mkdir(parents=True, exist_ok=True)
    adapter = _build_stage_adapter(auth, view)
    b1_view = args.wave2b1_private.expanduser().resolve() / "project_view"
    b1_status = common.load_json(
        args.wave2b1_public.expanduser().resolve() / "WAVE2B1_RUN_STATUS.json"
    )
    links = {
        view / "derived/replication/dynamic_prosociality_core_v102_PRIVATE": (
            b1_view / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
        ),
        view / "derived/replication/remaining_dynamic_completion_v100_PRIVATE": (
            b1_view / "derived/replication/remaining_dynamic_completion_v100_PRIVATE"
        ),
        view / "derived/replication/dynamic_second_wave_history_v100_PRIVATE": (
            b1_view / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
        ),
        view / "output/remaining_dynamic_completion_v100/20260823T141145Z": Path(
            b1_status["result_roots"]["remaining_a1_a2"]
        ),
        view / "output/dynamic_second_wave_history_v100/20260822T150914Z": Path(
            b1_status["result_roots"]["second_wave_histories"]
        ),
        view / "output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z": (
            args.project_root.expanduser().resolve()
            / "output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z"
        ),
    }
    for link, target in links.items():
        _ensure_link(target, link)
    return {"view": view, "adapter": adapter, "links": {str(k): str(v) for k, v in links.items()}}


def _c12_replacements() -> list[tuple[str, str, str]]:
    return [
        (
            "pool-main-c12-source-scope",
            '"""C12 recipient pre-opportunity experience in the certified 2% user sample.\n\n'
            'v1.0.2 reuses the fully authenticated v1.0.1 Parquet checkpoints.  It preserves\n'
            'the v1.0.1 sample correction and adds a transparent numerical-recovery policy:\n'
            'each HDFE fit is attempted under the original strict tolerance; absorption-only\n'
            'nonconvergence receives one extended retry; any still-unestimable model is\n'
            'retained as a model-attempt record while the remaining analyses continue.\n'
            '"""\n',
            '"""C12 recipient pre-opportunity experience in a deterministic 2% user sample.\n\n'
            'The pool-main binding rebuilds every Parquet checkpoint on the selected panel,\n'
            'preserves the corrected sampling rule and frozen model equations, and retains\n'
            'the v1.0.2 transparent numerical-recovery policy.\n'
            '"""\n',
        ),
        (
            "new-sample-outcome-blind-focal-row-gate",
            """    if (\n        qa[0] != EXPECTED_V100_FOCAL_ROWS\n        or qa[0] != qa[1]\n""",
            """    if (\n        qa[0] <= 0\n        or qa[0] != qa[1]\n""",
        ),
        (
            "new-sample-focal-receipt",
            '        "v100_focal_rows_exactly_reproduced": True,\n',
            '        "new_sample_focal_rows_frozen_before_outcome": True,\n'
            '        "historical_v100_focal_rows_diagnostic": EXPECTED_V100_FOCAL_ROWS,\n'
            '        "v100_focal_rows_exactly_reproduced": False,\n',
        ),
        (
            "new-sample-modulo-note",
            '            "v1.0.1 recognizes the deterministic modulo alias between the "\n'
            '            "1-in-50 sample and 16 storage buckets; sample membership is unchanged"\n',
            '            "the deterministic modulo alias between the 1-in-50 sample and 16 "\n'
            '            "storage buckets is preserved; membership is freshly selected from "\n'
            '            "the pool-main panel"\n',
        ),
        (
            "new-sample-focal-log-label",
            '        f"C12_V100_FOCAL_ROWS_EXACT_REPRODUCTION_OK "\n',
            '        f"C12_POOL_MAIN_FOCAL_ROWS_OUTCOME_BLIND_FROZEN "\n',
        ),
        (
            "new-sample-summary-lineage",
            '        "sample_membership_changed_by_v101": False,\n'
            '        "v101_private_parquet_checkpoints_reused": True,\n',
            '        "sample_membership_changed_by_pool_main_reset": True,\n'
            '        "fresh_pool_main_private_parquet_checkpoints_built": True,\n'
            '        "v101_old_sample_private_checkpoints_reused": False,\n',
        ),
    ]


def _prepare_sources(
    *, private: Path, view: Path, adapter: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    package = private / "execution_packages/campaign_pool_main"
    code = package / "payload/code"
    code.mkdir(parents=True, exist_ok=True)
    receipts = private / "source_bindings"
    receipts.mkdir(parents=True, exist_ok=True)
    source = common.PACKAGE_ROOT / "source"
    common_binding = retarget_source(
        source / "campaign/campaign1_nonprofile_common_v102.py",
        code / "campaign1_nonprofile_common_v102.py",
        constants={
            "PROJECT_ROOT": view,
            "EXPECTED_STAGE07_ROWS": adapter["rows"],
            "EXPECTED_STAGE07_FAIR_ROWS": adapter["fair_rows"],
            "EXPECTED_RECIPIENT_ROWS": 2_369_530,
            "EXPECTED_USER_EVENT_ROWS": 309_961_276,
            "EXPECTED_PAIR_EVENT_ROWS": 154_693_194,
        },
        receipt=receipts / "campaign_common.json",
    )
    c6_binding = retarget_source(
        source / "campaign/campaign1_c6_c10_v100.py",
        code / "campaign1_c6_c10_v100.py",
        constants={
            "EXPECTED_RECIPIENT_SHA256": EXPECTED_RECIPIENT_SHA256,
            "EXPECTED_A2_CACHE_SHA256": EXPECTED_A2_SHA256,
            "EXPECTED_A2_CACHE_ROWS": EXPECTED_A2_ROWS,
            "EXPECTED_REMAINING_SUCCESS_SHA256": EXPECTED_REMAINING_SUCCESS_SHA256,
            "EXPECTED_STAGE07_SUCCESS_SHA256": adapter["success_sha256"],
            "EXPECTED_CHRONOLOGY_MANIFEST_SHA256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
        },
        receipt=receipts / "c6_c10.json",
    )
    c12_binding = retarget_source(
        source / "campaign/campaign1_c12_v102.py",
        code / "campaign1_c12_v102.py",
        constants={"EXPECTED_HISTORY_SUCCESS_SHA256": EXPECTED_HISTORY_SUCCESS_SHA256},
        exact_replacements=_c12_replacements(),
        receipt=receipts / "c12.json",
    )
    copied = {}
    for relative in (
        "campaign/campaign1_c12_supplement_v103.py",
        "engines/10c_estimate_dynamic_prosociality_core.py",
        "frequent_dyad/frequent_dyad_census_v101.py",
    ):
        origin = source / relative
        destination = code / Path(relative).name
        if destination.is_file():
            if common.sha256_file(origin) != common.sha256_file(destination):
                raise RuntimeError(f"Existing exact source copy changed: {destination}")
        else:
            shutil.copy2(origin, destination)
        copied[Path(relative).name] = common.source_record(origin, "recovered_frozen_producer")
    manifest = write_package_manifest(package)
    return package, {
        "common": common_binding,
        "c6_c10": c6_binding,
        "c12": c12_binding,
        "exact_copies": copied,
        "package_manifest_sha256": common.sha256_file(manifest),
    }


def _load_modules(code: Path) -> dict[str, Any]:
    campaign_common = common.load_source_module(
        code / "campaign1_nonprofile_common_v102.py", "campaign1_nonprofile_common_v102"
    )
    core = common.load_source_module(
        code / "10c_estimate_dynamic_prosociality_core.py", "pool_main_wave2b2b1_core"
    )
    c6 = common.load_source_module(
        code / "campaign1_c6_c10_v100.py", "pool_main_wave2b2b1_c6"
    )
    c12 = common.load_source_module(
        code / "campaign1_c12_v102.py", "campaign1_c12_v102"
    )
    c12_supplement = common.load_source_module(
        code / "campaign1_c12_supplement_v103.py", "pool_main_wave2b2b1_c12_supplement"
    )
    dyad = common.load_source_module(
        code / "frequent_dyad_census_v101.py", "pool_main_wave2b2b1_dyad"
    )
    return {
        "campaign_common": campaign_common,
        "core": core,
        "c6": c6,
        "c12": c12,
        "c12_supplement": c12_supplement,
        "dyad": dyad,
    }


def _verify_manifest(root: Path) -> int:
    manifest = root / "REPORT_FILE_HASHES.tsv"
    if not manifest.is_file():
        raise RuntimeError(f"Public-stage manifest is missing: {manifest}")
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"Public-stage manifest is empty: {manifest}")
    for row in rows:
        path = root / row["relative_path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(row["bytes"])
            or common.sha256_file(path) != row["sha256"]
        ):
            raise RuntimeError(f"Public-stage output changed: {path}")
    return len(rows)


def _completed(
    root: Path, status: str, fingerprint: str, config_sha256: str
) -> dict[str, Any] | None:
    success_path = root / "_SUCCESS.json"
    if not success_path.is_file():
        return None
    saved = common.load_json(success_path)
    if saved.get("status") != status:
        raise RuntimeError(f"Unexpected public-stage status: {root}")
    if (saved.get("sample_authority") or {}).get("fingerprint") != fingerprint:
        raise RuntimeError(f"Public stage belongs to another sample: {root}")
    if saved.get("config_sha256") != config_sha256:
        raise RuntimeError(f"Public stage belongs to another configuration: {root}")
    return {
        "root": str(root),
        "status": status,
        "success_sha256": common.sha256_file(success_path),
        "manifest_files_authenticated": _verify_manifest(root),
        "adopted_existing": True,
    }


def _finalize(
    *, root: Path, status: str, auth: dict[str, Any], config_sha256: str,
    summary: dict[str, Any], runtime: float
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    for wrapper in (root / "_SUCCESS.json", root / "REPORT_FILE_HASHES.tsv"):
        if wrapper.exists():
            wrapper.unlink()
    success = {
        "status": status,
        "created_at_utc": common.utc_now(),
        "sample_authority": common.compact_sample_lineage(auth),
        "config_sha256": config_sha256,
        "producer_status": summary.get("status"),
        "runtime_seconds": runtime,
        "account_level_output": False,
        "private_row_level_output": False,
        "network_requests": 0,
    }
    common.atomic_json(root / "_SUCCESS.json", success)
    common.write_manifest_tsv(root)
    return {
        "root": str(root),
        "status": status,
        "success_sha256": common.sha256_file(root / "_SUCCESS.json"),
        "manifest_files_authenticated": _verify_manifest(root),
        "adopted_existing": False,
        "runtime_seconds": runtime,
    }


def _run_stage(
    *, name: str, root: Path, auth: dict[str, Any], config_sha256: str, function: Any
) -> dict[str, Any]:
    existing = _completed(root, MODULE_STATUSES[name], auth["fingerprint"], config_sha256)
    if existing is not None:
        print(f"{name.upper()}_AUTHENTICATED_EXISTING_OK", flush=True)
        return existing
    started = time.monotonic()
    summary = function()
    result = _finalize(
        root=root,
        status=MODULE_STATUSES[name],
        auth=auth,
        config_sha256=config_sha256,
        summary=summary,
        runtime=time.monotonic() - started,
    )
    print(MODULE_STATUSES[name], flush=True)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    private = args.private_base.expanduser().resolve()
    public = args.public_base.expanduser().resolve()
    private.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    preflight = common.load_json(public / "PREFLIGHT.json")
    if preflight.get("status") != "POOL_MAIN_WAVE2B2B1_PREFLIGHT_READY":
        raise RuntimeError("Wave 2B2B1 preflight has not passed")
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    if (preflight.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Preflight belongs to another sample")
    view_info = _build_view(args, auth, private)
    view = Path(view_info["view"])
    adapter = view_info["adapter"]
    package, bindings = _prepare_sources(private=private, view=view, adapter=adapter)
    modules = _load_modules(package / "payload/code")
    campaign_common = modules["campaign_common"]
    core = modules["core"]
    c6 = modules["c6"]
    c12 = modules["c12"]
    c12_supplement = modules["c12_supplement"]
    dyad = modules["dyad"]

    config = {
        "wave_version": common.WAVE_VERSION,
        "sample_fingerprint": auth["fingerprint"],
        "adapter_success_sha256": adapter["success_sha256"],
        "recipient_sha256": EXPECTED_RECIPIENT_SHA256,
        "a2_sha256": EXPECTED_A2_SHA256,
        "history_success_sha256": EXPECTED_HISTORY_SUCCESS_SHA256,
        "c7x_classification_sha256": EXPECTED_C7X_SHA256,
        "chronology_manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
        "invariant_dyad_config_sha256": preflight["invariant_frequent_dyad_index"]["config_sha256"],
        "bindings": {
            key: value.get("generated_sha256")
            for key, value in bindings.items()
            if isinstance(value, dict) and value.get("generated_sha256")
        },
        "threads": int(args.threads),
        "workers": int(args.workers),
        "memory_limit": args.memory_limit,
        "batch_rows": int(args.batch_rows),
    }
    import hashlib
    config_sha256 = hashlib.sha256(
        common.canonical_json(config).encode("utf-8")
    ).hexdigest()
    common.atomic_json(private / "WAVE2B2B1_CONFIG.json", {"config": config, "config_sha256": config_sha256})

    recipient = view / "derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet"
    stage_paths = campaign_common.stage07_paths(Path(adapter["root"]))
    c6_state = private / "campaign_state/C6_C10"
    c6_public = public / "modules/c6_c10"
    results: dict[str, Any] = {}
    results["c6_c10"] = _run_stage(
        name="c6_c10",
        root=c6_public,
        auth=auth,
        config_sha256=config_sha256,
        function=lambda: c6.execute(
            project=view,
            package_root=package,
            state=c6_state,
            public_stage=c6_public,
            core=core,
            threads=args.threads,
            memory_limit=args.memory_limit,
            workers=args.workers,
            batch_rows=args.batch_rows,
            config_sha256=config_sha256,
        ),
    )

    c6_ply_public = public / "modules/c6_ply_retrofit"
    results["c6_ply"] = _run_stage(
        name="c6_ply",
        root=c6_ply_public,
        auth=auth,
        config_sha256=config_sha256,
        function=lambda: c6_ply_retrofit.execute(
            recipient=recipient,
            stage_paths=stage_paths,
            c6_state=c6_state,
            state=private / "campaign_state/C6_PLY",
            public_stage=c6_ply_public,
            core=core,
            c6=c6,
            campaign_common=campaign_common,
            config_sha256=config_sha256,
            threads=args.threads,
            memory_limit=args.memory_limit,
        ),
    )

    c12_public = public / "modules/c12"
    c12_state = private / "campaign_state/C12"

    def run_c12() -> dict[str, Any]:
        c12.execute(
            project=view,
            state=c12_state,
            public_stage=c12_public,
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
        )
        return c12_supplement.supplement(
            model_cache=c12_state / "c12_model_private.parquet",
            public_stage=c12_public,
        )

    results["c12"] = _run_stage(
        name="c12",
        root=c12_public,
        auth=auth,
        config_sha256=config_sha256,
        function=run_c12,
    )

    classification = (
        args.wave2b2a_private.expanduser().resolve()
        / "c7x_state_v101/c7x_classification_private.parquet"
    )
    old_dyad = args.old_frequent_state.expanduser().resolve()
    pair_paths = [
        old_dyad / f"frequent_pairs/pair_bucket={bucket:03d}/part-00000.parquet"
        for bucket in range(128)
    ]
    c7x_public = public / "modules/c7x_frequent_dyad"
    results["c7x_dyad"] = _run_stage(
        name="c7x_dyad",
        root=c7x_public,
        auth=auth,
        config_sha256=config_sha256,
        function=lambda: c7x_dyad_diagnostic.execute(
            classification=classification,
            stage_paths=stage_paths,
            pair_paths=pair_paths,
            player_path=old_dyad / "frequent_players_private.parquet",
            state=private / "c7x_frequent_dyad_state",
            public_stage=c7x_public,
            dyad_module=dyad,
            runner_common=common,
            config_sha256=config_sha256,
            classification_sha256=EXPECTED_C7X_SHA256,
            threads=args.threads,
            memory_limit=args.memory_limit,
        ),
    )

    status = {
        "status": "POOL_MAIN_WAVE2B2B1_ALL_STAGES_OK",
        "created_at_utc": common.utc_now(),
        "wave_version": common.WAVE_VERSION,
        "sample_authority": common.compact_sample_lineage(auth),
        "config_sha256": config_sha256,
        "stage07_adapter": {
            "root": str(adapter["root"]),
            "success_sha256": adapter["success_sha256"],
        },
        "source_bindings": bindings,
        "results": results,
        "scope": {
            "included": ["C6", "C10", "C6 ply retrofit", "C12", "C7X frequent-dyad diagnostic"],
            "not_included": ["C9 fresh randomization", "C13 ambient exposure", "Patron matching", "paper-wide Holm closure"],
        },
        "network_requests": 0,
        "private_row_level_outputs_transferred": False,
    }
    common.atomic_json(public / "WAVE2B2B1_RUN_STATUS.json", status)
    print(status["status"], flush=True)
    return status


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
