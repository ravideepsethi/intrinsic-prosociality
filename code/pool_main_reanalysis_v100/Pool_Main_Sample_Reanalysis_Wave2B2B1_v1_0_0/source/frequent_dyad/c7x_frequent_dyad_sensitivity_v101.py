#!/usr/bin/env python3
"""C7X sensitivity to whole-window dyad frequency, using certified models.

The focal outcome is joined only after the C7X classification and dyad-frequency
flags have been authenticated.  The adjusted models exactly reuse the certified
C7X/C7R estimators and covariate contract.  Public output is aggregate only.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
from typing import Any, Mapping, Sequence
import uuid

import campaign1_nonprofile_common_v102 as authority_common
import c7r_modeling_v102 as authority_modeling


SCRIPT_VERSION = "1.0.1"
STATUS = "C7X_FREQUENT_DYAD_SENSITIVITY_V101_OK"
QA_STATUS = "C7X_FREQUENT_DYAD_SENSITIVITY_V101_QA_OK"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
STAGE07_RELATIVE = Path("derived/replication/analysis_panel_24m_sf100k")
C7X_RELATIVE = Path(
    "derived/replication/dynamics_campaign1_c7x_fullpanel_v101_PRIVATE/"
    "c7x_classification_private.parquet"
)
FREQUENCY_STATE_RELATIVE = Path(
    "derived/replication/frequent_dyad_census_24m_v101_PRIVATE"
)
OUTPUT_RELATIVE = Path("output/c7x_frequent_dyad_sensitivity_v101")
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_C7X_SHA256 = (
    "998b6087806b8300718897537b67828cc893259d96023a92d91de9ed64e331ed"
)
EXPECTED_COMMON_ENGINE_SHA256 = (
    "f629876216c797180265d1b848a4424f211fe9a43cffa4dabdb3de67acbc5f1c"
)
EXPECTED_PAIR_ENGINE_SHA256 = (
    "8fe65619941f5d2712827d47ea8a56053a9d865857959243f8908c8cadcaa817"
)
EXPECTED_ROWS = 27_627
EXPECTED_BENEFACTOR_ROWS = 2_208
EXPECTED_CLAIMER_ROWS = 25_419
EXPECTED_BENEFACTOR_KIND = 915
EXPECTED_CLAIMER_KIND = 1_247

# Certified 2026-08-28 authorities.
EXPECTED_CHOOSER_COEFFICIENT = 0.14556932160589928
EXPECTED_CHOOSER_STANDARD_ERROR = 0.020351569816937143
EXPECTED_CHOOSER_GROUPS = 20_353
EXPECTED_CHOOSER_SWITCHERS = 370
EXPECTED_CHOOSER_SWITCHER_ROWS = 2_213
EXPECTED_DIRECTED_PAIR_COEFFICIENT = 0.12978153938638437
EXPECTED_DIRECTED_PAIR_CHOOSER_CLUSTER_SE = 0.030495801391880323
EXPECTED_DIRECTED_PAIR_UNORDERED_CLUSTER_SE = 0.03259236410387049
EXPECTED_DIRECTED_PAIR_GROUPS = 23_339
EXPECTED_DIRECTED_PAIR_SWITCHERS = 160
EXPECTED_DIRECTED_PAIR_SWITCHER_ROWS = 828
AUTHORITY_C7X_RESULT_ZIP_SHA256 = (
    "23d9d1013f8e3c65f10b801b068f1016d02a522894176e39b1599076ccf6ae6d"
)
AUTHORITY_C7R_RESULT_ZIP_SHA256 = (
    "03ffd429e07eb57bc6af1a88634ecdbd12eeadc0803817c2fb94a0e6ba79b2de"
)

MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 34)
)
NUMERIC_CONTROLS = (
    "draw_payoff",
    "win_premium",
    "chooser_clock",
    "opponent_clock",
    "chooser_elo",
    "opponent_elo",
    "chooser_rd",
    "opponent_rd",
    "tournament",
)
CONTEXT_EFFECTS = (
    "eval_bin",
    "speed_code",
    "month_code",
    "hour_of_week",
    "ply_band",
)
MODEL_NAMES = (
    "chooser_context_hdfe_chooser_cluster",
    "directed_pair_context_fe_chooser_cluster",
    "directed_pair_context_fe_unordered_pair_cluster",
)
SAMPLE_SPECS = (
    ("all", "All C7X classified opportunities"),
    ("pair_lt_3", "Dyad played exactly 2 games in the 24-month window"),
    ("pair_lt_5", "Dyad played 2-4 games in the 24-month window"),
    ("pair_lt_10", "Dyad played 2-9 games in the 24-month window"),
    ("pair_eq_2", "Dyad played exactly 2 games"),
    ("pair_3_4", "Dyad played 3-4 games"),
    ("pair_5_9", "Dyad played 5-9 games"),
    ("pair_ge_10", "Dyad played at least 10 games"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(json_safe(value), indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write an empty CSV: {path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: canonical_json(value)
                    if isinstance(value, (dict, list, tuple))
                    else "" if value is None
                    else value
                    for key, value in row.items()
                }
            )
    os.replace(temporary, path)


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_path_list(paths: Sequence[Path]) -> str:
    return "[" + ",".join(sql_literal(path) for path in paths) + "]"


def import_dependencies() -> tuple[Any, Any, Any]:
    duckdb, np, _, pq = authority_common.import_dependencies()
    observed = {
        "duckdb": duckdb.__version__,
        "pyarrow": __import__("pyarrow").__version__,
    }
    expected = {"duckdb": "1.5.2", "pyarrow": "24.0.0"}
    if observed != expected:
        raise RuntimeError(f"Dependency authority changed: {observed} != {expected}")
    return duckdb, np, pq


def require_schema(pq: Any, path: Path, required: set[str], label: str) -> list[str]:
    if not path.is_file():
        raise RuntimeError(f"{label} is missing: {path}")
    names = list(pq.ParquetFile(path).schema_arrow.names)
    missing = required.difference(names)
    if missing:
        raise RuntimeError(f"{label} schema is missing {sorted(missing)}; found={names}")
    return names


def stage07_paths(
    root: Path, *, expected_success_sha256: str, allow_incomplete_months: bool,
    synthetic_test_mode: bool,
) -> tuple[list[Path], str, dict[str, Any]]:
    success = root / "_SUCCESS.json"
    if not success.is_file():
        raise RuntimeError(f"Stage 07 success authority is missing: {success}")
    observed = sha256_file(success)
    if expected_success_sha256 and observed != expected_success_sha256:
        raise RuntimeError(
            f"Stage 07 success SHA-256 changed: {observed} != {expected_success_sha256}"
        )
    paths = sorted(root.glob("month=*/analysis_panel.parquet"))
    if not paths:
        raise RuntimeError(f"No Stage 07 Parquet files found under {root}")
    months = tuple(path.parent.name.removeprefix("month=") for path in paths)
    if not allow_incomplete_months and months != MAIN_MONTHS:
        raise RuntimeError(f"Stage 07 month coverage changed: {months}")
    if synthetic_test_mode:
        authentication = {
            "mode": "synthetic_test",
            "monthly_files": len(paths),
        }
    else:
        authentication = authority_common.authenticate_stage07(
            root, expected_success_sha256
        )
    return paths, observed, authentication


def authenticate_frequency_flags(
    *, flags: Path, receipt: Path, classification_sha256: str, expected_rows: int,
) -> dict[str, Any]:
    if not flags.is_file() or not receipt.is_file():
        raise RuntimeError(
            "Completed C7X frequency flags are missing. Run the v1.0.1 frequent-"
            f"dyad census first: flags={flags}, receipt={receipt}"
        )
    saved = load_json(receipt)
    if saved.get("status") != "C7X_FREQUENT_DYAD_FLAGS_PRIVATE_OK":
        raise RuntimeError(f"Frequency-flag receipt status changed: {saved.get('status')}")
    observed_sha = sha256_file(flags)
    expected = {
        "output_sha256": observed_sha,
        "output_bytes": flags.stat().st_size,
        "rows": expected_rows,
        "classification_sha256": classification_sha256,
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"C7X frequency-flag receipt mismatch: {key}")
    return saved


def authenticate_estimation_engines() -> dict[str, Any]:
    root = Path(__file__).resolve().parent
    engines = {
        "campaign1_nonprofile_common_v102.py": EXPECTED_COMMON_ENGINE_SHA256,
        "c7r_modeling_v102.py": EXPECTED_PAIR_ENGINE_SHA256,
    }
    for filename, expected in engines.items():
        observed = sha256_file(root / filename)
        if observed != expected:
            raise RuntimeError(
                f"Certified estimation engine changed: {filename} {observed} != {expected}"
            )
    return {
        "status": "CERTIFIED_C7X_C7R_ESTIMATION_ENGINES_AUTHENTICATED_OK",
        "files": engines,
        "c7x_result_zip_sha256": AUTHORITY_C7X_RESULT_ZIP_SHA256,
        "c7r_result_zip_sha256": AUTHORITY_C7R_RESULT_ZIP_SHA256,
    }


def sample_masks(np: Any, pair_games: Any) -> list[tuple[str, str, Any]]:
    pair_games = np.asarray(pair_games, dtype=np.int64)
    definitions = {
        "all": np.ones(pair_games.size, dtype=bool),
        "pair_lt_3": pair_games < 3,
        "pair_lt_5": pair_games < 5,
        "pair_lt_10": pair_games < 10,
        "pair_eq_2": pair_games == 2,
        "pair_3_4": (pair_games >= 3) & (pair_games <= 4),
        "pair_5_9": (pair_games >= 5) & (pair_games <= 9),
        "pair_ge_10": pair_games >= 10,
    }
    return [(name, description, definitions[name]) for name, description in SAMPLE_SPECS]


def raw_estimate(
    np: Any, data: Mapping[str, Any], sample: str, description: str, mask: Any,
) -> dict[str, Any]:
    mask = np.asarray(mask, dtype=bool)
    y = np.asarray(data["kind"], dtype=np.float64)[mask]
    x = np.asarray(data["latest_prior_arm"], dtype=np.float64)[mask]
    clusters = np.asarray(data["chooser_id"])[mask]
    n = int(y.size)
    n1 = int(np.count_nonzero(x == 1))
    n0 = int(np.count_nonzero(x == 0))
    y1 = int(np.sum(y[x == 1]))
    y0 = int(np.sum(y[x == 0]))
    p1 = y1 / n1 if n1 else math.nan
    p0 = y0 / n0 if n0 else math.nan
    difference = p1 - p0 if n1 and n0 else math.nan
    iid_se = (
        math.sqrt(p1 * (1.0 - p1) / n1 + p0 * (1.0 - p0) / n0)
        if n1 and n0 else math.nan
    )
    cluster_se = math.nan
    cluster_count = 0
    if n1 and n0 and n > 2:
        cluster_codes, cluster_count = authority_common.factor_codes(clusters)
        if cluster_count > 1:
            residual = y - np.where(x == 1, p1, p0)
            score_intercept = np.bincount(
                cluster_codes, weights=residual, minlength=cluster_count
            )
            score_arm = np.bincount(
                cluster_codes, weights=x * residual, minlength=cluster_count
            )
            influence = (
                -score_intercept / n0
                + score_arm * (1.0 / n0 + 1.0 / n1)
            )
            correction = (cluster_count / (cluster_count - 1.0)) * (
                (n - 1.0) / (n - 2.0)
            )
            cluster_se = math.sqrt(max(0.0, correction * float(influence @ influence)))
    return json_safe(
        {
            "sample": sample,
            "sample_description": description,
            "observations": n,
            "benefactor_observations": n1,
            "benefactor_kind_draws": y1,
            "benefactor_kindness_rate_pct": 100.0 * p1,
            "claimer_observations": n0,
            "claimer_kind_draws": y0,
            "claimer_kindness_rate_pct": 100.0 * p0,
            "benefactor_minus_claimer_pp": 100.0 * difference,
            "iid_standard_error_pp": 100.0 * iid_se,
            "chooser_clusters": cluster_count,
            "chooser_clustered_standard_error_pp": 100.0 * cluster_se,
            "chooser_clustered_t": difference / cluster_se
            if math.isfinite(cluster_se) and cluster_se > 0 else None,
        }
    )


def controls(data: Mapping[str, Any], indices: Any) -> dict[str, Any]:
    return {name: data[name][indices] for name in NUMERIC_CONTROLS}


def switcher_support(
    np: Any, groups: Any, exposure: Any, indices: Any,
) -> dict[str, int]:
    selected_groups = np.asarray(groups)[indices]
    selected_exposure = np.asarray(exposure, dtype=np.float64)[indices]
    absorbed_groups = int(np.unique(selected_groups).size) if indices.size else 0
    if not indices.size:
        return {
            "absorbed_groups": 0,
            "identifying_groups_with_both_arms": 0,
            "observations_in_identifying_groups": 0,
        }
    rows, switchers = authority_modeling.switcher_mask(
        selected_groups, selected_exposure
    )
    return {
        "absorbed_groups": absorbed_groups,
        "identifying_groups_with_both_arms": switchers,
        "observations_in_identifying_groups": int(np.count_nonzero(rows)),
    }


def flattened_model(
    base: Mapping[str, Any], fitted: Mapping[str, Any], *, retries: int = 0,
) -> dict[str, Any]:
    results = fitted.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError(f"Expected one exposure result: {results}")
    term = results[0]
    return json_safe(
        {
            **dict(base),
            "status": "ESTIMATED",
            "rows_estimated": fitted.get("rows"),
            "clusters": fitted.get("clusters"),
            "coefficient": term.get("coefficient"),
            "benefactor_effect_pp": 100.0 * float(term["coefficient"]),
            "standard_error": term.get("standard_error"),
            "standard_error_pp": 100.0 * float(term["standard_error"]),
            "t_cluster": term.get("t_cluster"),
            "p_value_two_sided": term.get("p_value_two_sided"),
            "matrix_rank": fitted.get("matrix_rank"),
            "smallest_singular_value": fitted.get("smallest_singular_value"),
            "cluster_correction": fitted.get("cluster_correction"),
            "numeric_controls_retained": fitted.get("numeric_controls", NUMERIC_CONTROLS),
            "fixed_effects": fitted.get(
                "fixed_effects", fitted.get("categorical_fixed_effects", CONTEXT_EFFECTS)
            ),
            "estimator": fitted.get("estimator", "certified_multiway_hdfe"),
            "absorption_iterations": fitted.get("absorption_iterations"),
            "absorption_retries": retries,
            "sample_specification_sha256": fitted.get("sample_specification_sha256"),
            "error_type": None,
            "error_message": None,
        }
    )


def attempt_chooser_model(
    np: Any, data: Mapping[str, Any], sample: str, description: str, mask: Any,
) -> dict[str, Any]:
    indices = np.flatnonzero(np.asarray(mask, dtype=bool))
    exposure = (np.asarray(data["latest_prior_arm"]) == 1).astype(np.float64)
    selected = exposure[indices]
    support = switcher_support(np, data["chooser_id"], exposure, indices)
    clusters = int(np.unique(data["chooser_id"][indices]).size) if indices.size else 0
    base = {
        "sample": sample,
        "sample_description": description,
        "model": MODEL_NAMES[0],
        "observations": int(indices.size),
        "benefactor_observations": int(np.count_nonzero(selected == 1)),
        "claimer_observations": int(np.count_nonzero(selected == 0)),
        "cluster_variable": "chooser_id",
        "clusters_requested": clusters,
        "high_dimensional_fixed_effect": "chooser_id",
        **support,
    }
    if support["identifying_groups_with_both_arms"] == 0:
        return {**base, "status": "NO_WITHIN_GROUP_ARM_VARIATION"}
    if indices.size < 1_000 or clusters < 100:
        return {**base, "status": "NOT_ESTIMABLE_LOW_SUPPORT"}
    specification = {
        "model": MODEL_NAMES[0],
        "analysis_role": "post-gate exploratory C7X frequent-dyad sensitivity",
        "cluster": "chooser_id",
        "causal_claim": False,
        "epistemic_label": "X",
    }
    try:
        retries = 0
        try:
            fitted = authority_common.fit_hdfe_cluster(
                outcome=data["kind"][indices],
                exposures={"benefactor_minus_claimer": exposure[indices]},
                numeric_controls=controls(data, indices),
                fixed_effects={
                    name: data[name][indices]
                    for name in ("chooser_id", *CONTEXT_EFFECTS)
                },
                clusters=data["chooser_id"][indices],
                row_ids=data["row_hash"][indices],
                specification=specification,
            )
        except RuntimeError as error:
            if not authority_common.is_hdfe_absorption_nonconvergence(error):
                raise
            retries = 1
            fitted = authority_common.fit_hdfe_cluster(
                outcome=data["kind"][indices],
                exposures={"benefactor_minus_claimer": exposure[indices]},
                numeric_controls=controls(data, indices),
                fixed_effects={
                    name: data[name][indices]
                    for name in ("chooser_id", *CONTEXT_EFFECTS)
                },
                clusters=data["chooser_id"][indices],
                row_ids=data["row_hash"][indices],
                specification=specification,
                absorption_maximum_iterations=10_000,
            )
        return flattened_model(base, fitted, retries=retries)
    except (RuntimeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        return {
            **base,
            "status": "ESTIMATION_FAILURE_RETAINED",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }


def attempt_directed_pair_model(
    np: Any, data: Mapping[str, Any], directed: Any, sample: str,
    description: str, mask: Any, *, unordered_pair_cluster: bool,
) -> dict[str, Any]:
    indices = np.flatnonzero(np.asarray(mask, dtype=bool))
    exposure = (np.asarray(data["latest_prior_arm"]) == 1).astype(np.float64)
    selected = exposure[indices]
    support = switcher_support(np, directed, exposure, indices)
    cluster_values = data["pair_hash"] if unordered_pair_cluster else data["chooser_id"]
    cluster_label = "unordered_pair" if unordered_pair_cluster else "chooser_id"
    model = MODEL_NAMES[2] if unordered_pair_cluster else MODEL_NAMES[1]
    clusters = int(np.unique(cluster_values[indices]).size) if indices.size else 0
    base = {
        "sample": sample,
        "sample_description": description,
        "model": model,
        "observations": int(indices.size),
        "benefactor_observations": int(np.count_nonzero(selected == 1)),
        "claimer_observations": int(np.count_nonzero(selected == 0)),
        "cluster_variable": cluster_label,
        "clusters_requested": clusters,
        "high_dimensional_fixed_effect": "directed_pair",
        **support,
    }
    if support["identifying_groups_with_both_arms"] == 0:
        return {**base, "status": "NO_WITHIN_GROUP_ARM_VARIATION"}
    if indices.size < 1_000 or clusters < 100:
        return {**base, "status": "NOT_ESTIMABLE_LOW_SUPPORT"}
    try:
        fitted = authority_modeling.fit_exact_oneway_cluster(
            outcome=data["kind"][indices],
            exposures={"benefactor_minus_claimer": exposure[indices]},
            numeric_controls=controls(data, indices),
            categorical_controls={
                name: data[name][indices] for name in CONTEXT_EFFECTS
            },
            high_dimensional_effect=np.asarray(directed)[indices],
            high_dimensional_name="directed_pair",
            clusters=np.asarray(cluster_values)[indices],
            row_ids=data["row_hash"][indices],
            specification={
                "model": model,
                "analysis_role": "post-gate exploratory C7X frequent-dyad sensitivity",
                "epistemic_label": "X",
                "causal_claim": False,
            },
        )
        return flattened_model(base, fitted)
    except (RuntimeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        return {
            **base,
            "status": "ESTIMATION_FAILURE_RETAINED",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }


def public_file_manifest(root: Path) -> list[dict[str, Any]]:
    excluded = {"file_manifest.tsv", "_SUCCESS.json"}
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        rows.append(
            {"file": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    return rows


def scalar_close(observed: Any, expected: float, tolerance: float) -> bool:
    return (
        observed is not None
        and math.isfinite(float(observed))
        and abs(float(observed) - expected) <= tolerance
    )


def execute(args: argparse.Namespace) -> Path:
    started = time.time()
    duckdb, np, pq = import_dependencies()
    project = args.project_root.resolve()
    stage_root = (args.stage07_root or project / STAGE07_RELATIVE).resolve()
    classification = (args.c7x_classification or project / C7X_RELATIVE).resolve()
    frequency_state = (
        args.frequency_state_root or project / FREQUENCY_STATE_RELATIVE
    ).resolve()
    flags = frequency_state / "c7x_frequency_flags_private.parquet"
    flags_receipt_path = frequency_state / "c7x_frequency_flags_receipt.json"
    output_root = (args.output_root or project / OUTPUT_RELATIVE).resolve()
    run_id = args.run_id or utc_run_id()
    final = output_root / run_id
    if final.exists():
        raise RuntimeError(f"Output run already exists: {final}")
    if args.threads < 1 or args.threads > 10:
        raise RuntimeError("--threads must be between 1 and 10")
    if not re.fullmatch(r"[1-9][0-9]*(?:KB|MB|GB|TB)", args.memory_limit.upper()):
        raise RuntimeError("--memory-limit must look like 8GB or 12000MB")
    if not args.synthetic_test_mode:
        observed_contract = (
            args.expected_rows,
            args.expected_benefactor_rows,
            args.expected_claimer_rows,
            args.expected_benefactor_kind,
            args.expected_claimer_kind,
        )
        expected_contract = (
            EXPECTED_ROWS,
            EXPECTED_BENEFACTOR_ROWS,
            EXPECTED_CLAIMER_ROWS,
            EXPECTED_BENEFACTOR_KIND,
            EXPECTED_CLAIMER_KIND,
        )
        if observed_contract != expected_contract:
            raise RuntimeError("Production C7X baseline contract cannot be overridden")

    engine_authentication = authenticate_estimation_engines()
    required_classification = {
        "game_id", "chooser_id", "opponent_id", "latest_prior_arm",
        "row_hash", "pair_hash", *NUMERIC_CONTROLS, *CONTEXT_EFFECTS,
    }
    classification_names = require_schema(
        pq, classification, required_classification, "C7X classification"
    )
    forbidden_outcomes = {"kind", "kind_draw", "outcome_kind_draw"}.intersection(
        classification_names
    )
    if forbidden_outcomes:
        raise RuntimeError(
            f"C7X classification unexpectedly contains outcomes: {forbidden_outcomes}"
        )
    classification_sha = sha256_file(classification)
    if args.c7x_sha256 and classification_sha != args.c7x_sha256:
        raise RuntimeError(
            f"C7X classification SHA-256 changed: {classification_sha} != {args.c7x_sha256}"
        )
    flag_names = require_schema(
        pq,
        flags,
        {
            "game_id", "latest_prior_arm", "pair_games_24m", "dyad_ge_2",
            "dyad_ge_3", "dyad_ge_5", "dyad_ge_10",
        },
        "C7X frequency flags",
    )
    if {"kind", "kind_draw", "outcome_kind_draw"}.intersection(flag_names):
        raise RuntimeError("Frozen frequency flags unexpectedly contain the focal outcome")
    flags_receipt = authenticate_frequency_flags(
        flags=flags,
        receipt=flags_receipt_path,
        classification_sha256=classification_sha,
        expected_rows=args.expected_rows,
    )
    stage_paths, stage_success_sha, stage_authentication = stage07_paths(
        stage_root,
        expected_success_sha256=args.stage07_success_sha256,
        allow_incomplete_months=args.allow_incomplete_months,
        synthetic_test_mode=args.synthetic_test_mode,
    )
    stage_names = require_schema(
        pq,
        stage_paths[0],
        {"game_id", "chooser_user_id", "disconnected_user_id", "outcome_kind_draw"},
        "Stage 07 analysis panel",
    )

    temp_base = (
        args.temp_directory
        or project / "derived/replication/c7x_frequent_dyad_sensitivity_v101_PRIVATE"
    ).resolve()
    temp_directory = temp_base / f"{run_id}_{uuid.uuid4().hex}"
    connection = duckdb.connect()
    columns = (
        "kind", "latest_prior_arm", "chooser_id", "opponent_id",
        "pair_games_24m", "row_hash", "pair_hash", "eval_bin", "speed_code",
        "month_code", "hour_of_week", "ply_band", *NUMERIC_CONTROLS,
    )
    try:
        authority_common.configure_duckdb(
            connection,
            threads=args.threads,
            memory_limit=args.memory_limit.upper(),
            temp_directory=temp_directory,
        )
        classification_sql = sql_literal(classification)
        flags_sql = sql_literal(flags)
        stage_sql = sql_path_list(stage_paths)
        class_qa = connection.execute(
            f"""
            SELECT COUNT(*)::UBIGINT,
                   COUNT(DISTINCT CAST(game_id AS VARCHAR))::UBIGINT,
                   COUNT(*) FILTER (WHERE CAST(latest_prior_arm AS INTEGER) NOT IN (0,1))::UBIGINT,
                   COUNT(*) FILTER (WHERE ply_band NOT BETWEEN 0 AND 7 OR ply_band IS NULL)::UBIGINT
            FROM read_parquet({classification_sql})
            """
        ).fetchone()
        flags_qa = connection.execute(
            f"""
            SELECT COUNT(*)::UBIGINT,
                   COUNT(DISTINCT CAST(game_id AS VARCHAR))::UBIGINT,
                   COUNT(*) FILTER (WHERE CAST(latest_prior_arm AS INTEGER) NOT IN (0,1))::UBIGINT,
                   COUNT(*) FILTER (WHERE CAST(pair_games_24m AS UBIGINT) < 2)::UBIGINT,
                   COUNT(*) FILTER (
                     WHERE CAST(dyad_ge_2 AS BOOLEAN) != (CAST(pair_games_24m AS UBIGINT) >= 2)
                        OR CAST(dyad_ge_3 AS BOOLEAN) != (CAST(pair_games_24m AS UBIGINT) >= 3)
                        OR CAST(dyad_ge_5 AS BOOLEAN) != (CAST(pair_games_24m AS UBIGINT) >= 5)
                        OR CAST(dyad_ge_10 AS BOOLEAN) != (CAST(pair_games_24m AS UBIGINT) >= 10)
                   )::UBIGINT
            FROM read_parquet({flags_sql})
            """
        ).fetchone()
        if tuple(map(int, class_qa)) != (
            args.expected_rows, args.expected_rows, 0, 0
        ):
            raise RuntimeError(f"C7X classification conservation failed: {class_qa}")
        if tuple(map(int, flags_qa)) != (
            args.expected_rows, args.expected_rows, 0, 0, 0
        ):
            raise RuntimeError(f"Frequency-flag conservation failed: {flags_qa}")

        connection.execute(
            f"""
            CREATE TEMP TABLE focal AS
            SELECT c.*,
                   CAST(f.pair_games_24m AS UBIGINT) AS pair_games_24m,
                   CAST(c.latest_prior_arm AS TINYINT) !=
                     CAST(f.latest_prior_arm AS TINYINT) AS arm_mismatch
            FROM read_parquet({classification_sql}) c
            INNER JOIN read_parquet({flags_sql}) f
              ON CAST(c.game_id AS VARCHAR)=CAST(f.game_id AS VARCHAR)
            """
        )
        focal_qa = connection.execute(
            """
            SELECT COUNT(*)::UBIGINT, COUNT(DISTINCT game_id)::UBIGINT,
                   COUNT(*) FILTER (WHERE arm_mismatch)::UBIGINT
            FROM focal
            """
        ).fetchone()
        if tuple(map(int, focal_qa)) != (args.expected_rows, args.expected_rows, 0):
            raise RuntimeError(f"Classification/flag join failed: {focal_qa}")

        connection.execute(
            f"""
            CREATE TEMP TABLE analytic AS
            SELECT
              CAST(p.outcome_kind_draw AS TINYINT) AS kind,
              CAST(f.latest_prior_arm AS TINYINT) AS latest_prior_arm,
              CAST(f.chooser_id AS BIGINT) AS chooser_id,
              CAST(f.opponent_id AS BIGINT) AS opponent_id,
              CAST(f.pair_games_24m AS BIGINT) AS pair_games_24m,
              CAST(f.row_hash AS BIGINT) AS row_hash,
              CAST(f.pair_hash AS BIGINT) AS pair_hash,
              CAST(f.eval_bin AS INTEGER) AS eval_bin,
              CAST(f.speed_code AS INTEGER) AS speed_code,
              CAST(f.month_code AS INTEGER) AS month_code,
              CAST(f.hour_of_week AS INTEGER) AS hour_of_week,
              CAST(f.ply_band AS INTEGER) AS ply_band,
              CAST(f.draw_payoff AS DOUBLE) AS draw_payoff,
              CAST(f.win_premium AS DOUBLE) AS win_premium,
              CAST(f.chooser_clock AS DOUBLE) AS chooser_clock,
              CAST(f.opponent_clock AS DOUBLE) AS opponent_clock,
              CAST(f.chooser_elo AS DOUBLE) AS chooser_elo,
              CAST(f.opponent_elo AS DOUBLE) AS opponent_elo,
              CAST(f.chooser_rd AS DOUBLE) AS chooser_rd,
              CAST(f.opponent_rd AS DOUBLE) AS opponent_rd,
              CAST(f.tournament AS DOUBLE) AS tournament,
              CAST(p.chooser_user_id AS BIGINT) != f.chooser_id AS chooser_mismatch,
              CAST(p.disconnected_user_id AS BIGINT) != f.opponent_id AS opponent_mismatch,
              CAST(f.game_id AS VARCHAR) AS game_id
            FROM focal f
            INNER JOIN read_parquet({stage_sql}, union_by_name=true) p
              ON CAST(p.game_id AS VARCHAR)=CAST(f.game_id AS VARCHAR)
            """
        )
        analytic_qa = connection.execute(
            """
            SELECT COUNT(*)::UBIGINT, COUNT(DISTINCT game_id)::UBIGINT,
                   COUNT(*) FILTER (WHERE kind NOT IN (0,1) OR kind IS NULL)::UBIGINT,
                   COUNT(*) FILTER (WHERE chooser_mismatch OR opponent_mismatch)::UBIGINT,
                   COUNT(*) FILTER (WHERE pair_games_24m < 2)::UBIGINT,
                   COUNT(*) FILTER (
                     WHERE chooser_id IS NULL OR opponent_id IS NULL
                        OR row_hash IS NULL OR pair_hash IS NULL
                        OR eval_bin IS NULL OR speed_code IS NULL
                        OR month_code IS NULL OR hour_of_week IS NULL
                        OR ply_band IS NULL
                   )::UBIGINT
            FROM analytic
            """
        ).fetchone()
        if tuple(map(int, analytic_qa)) != (
            args.expected_rows, args.expected_rows, 0, 0, 0, 0
        ):
            raise RuntimeError(f"Stage07/C7X analytic join failed: {analytic_qa}")
        fetched = connection.execute(
            "SELECT " + ",".join(columns) + " FROM analytic ORDER BY game_id"
        ).fetchall()
    finally:
        connection.close()
        shutil.rmtree(temp_directory, ignore_errors=True)

    integer_columns = set(columns[:12])
    data: dict[str, Any] = {}
    for position, name in enumerate(columns):
        values = [row[position] for row in fetched]
        if name in integer_columns:
            data[name] = np.asarray(values, dtype=np.int64)
        else:
            data[name] = np.asarray(
                [float("nan") if value is None else value for value in values],
                dtype=np.float64,
            )
    if data["kind"].size != args.expected_rows:
        raise RuntimeError("In-memory analytic row conservation failed")

    exposure = (data["latest_prior_arm"] == 1).astype(np.float64)
    directed = authority_modeling.directed_pair_codes(
        data["chooser_id"], data["opponent_id"]
    )
    masks = sample_masks(np, data["pair_games_24m"])
    raw_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    mask_by_name: dict[str, Any] = {}
    for sample, description, mask in masks:
        mask_by_name[sample] = mask
        raw_rows.append(raw_estimate(np, data, sample, description, mask))
        model_rows.append(
            attempt_chooser_model(np, data, sample, description, mask)
        )
        model_rows.append(
            attempt_directed_pair_model(
                np, data, directed, sample, description, mask,
                unordered_pair_cluster=False,
            )
        )
        model_rows.append(
            attempt_directed_pair_model(
                np, data, directed, sample, description, mask,
                unordered_pair_cluster=True,
            )
        )

    raw_by_sample = {row["sample"]: row for row in raw_rows}
    model_by_key = {(row["sample"], row["model"]): row for row in model_rows}
    full_raw = raw_by_sample["all"]
    expected_baseline = {
        "observations": args.expected_rows,
        "benefactor_observations": args.expected_benefactor_rows,
        "benefactor_kind_draws": args.expected_benefactor_kind,
        "claimer_observations": args.expected_claimer_rows,
        "claimer_kind_draws": args.expected_claimer_kind,
    }
    observed_baseline = {key: int(full_raw[key]) for key in expected_baseline}
    if observed_baseline != expected_baseline:
        raise RuntimeError(
            f"Published raw C7X baseline did not reproduce: {observed_baseline} != "
            f"{expected_baseline}"
        )

    chooser = model_by_key[("all", MODEL_NAMES[0])]
    directed_chooser = model_by_key[("all", MODEL_NAMES[1])]
    directed_unordered = model_by_key[("all", MODEL_NAMES[2])]
    tolerance = args.authority_tolerance
    baseline_reproduction = {
        "raw_counts_reproduced_exactly": observed_baseline == expected_baseline,
        "tolerance_on_coefficient_and_standard_error_scale": tolerance,
        "chooser": {
            "expected_coefficient": EXPECTED_CHOOSER_COEFFICIENT,
            "observed_coefficient": chooser.get("coefficient"),
            "expected_standard_error": EXPECTED_CHOOSER_STANDARD_ERROR,
            "observed_standard_error": chooser.get("standard_error"),
            "expected_groups": EXPECTED_CHOOSER_GROUPS,
            "observed_groups": chooser.get("absorbed_groups"),
            "expected_switchers": EXPECTED_CHOOSER_SWITCHERS,
            "observed_switchers": chooser.get("identifying_groups_with_both_arms"),
            "expected_switcher_rows": EXPECTED_CHOOSER_SWITCHER_ROWS,
            "observed_switcher_rows": chooser.get("observations_in_identifying_groups"),
        },
        "directed_pair_chooser_cluster": {
            "expected_coefficient": EXPECTED_DIRECTED_PAIR_COEFFICIENT,
            "observed_coefficient": directed_chooser.get("coefficient"),
            "expected_standard_error": EXPECTED_DIRECTED_PAIR_CHOOSER_CLUSTER_SE,
            "observed_standard_error": directed_chooser.get("standard_error"),
            "expected_groups": EXPECTED_DIRECTED_PAIR_GROUPS,
            "observed_groups": directed_chooser.get("absorbed_groups"),
            "expected_switchers": EXPECTED_DIRECTED_PAIR_SWITCHERS,
            "observed_switchers": directed_chooser.get("identifying_groups_with_both_arms"),
            "expected_switcher_rows": EXPECTED_DIRECTED_PAIR_SWITCHER_ROWS,
            "observed_switcher_rows": directed_chooser.get("observations_in_identifying_groups"),
        },
        "directed_pair_unordered_pair_cluster": {
            "expected_coefficient": EXPECTED_DIRECTED_PAIR_COEFFICIENT,
            "observed_coefficient": directed_unordered.get("coefficient"),
            "expected_standard_error": EXPECTED_DIRECTED_PAIR_UNORDERED_CLUSTER_SE,
            "observed_standard_error": directed_unordered.get("standard_error"),
        },
        "authority_sources": engine_authentication,
        "synthetic_test_mode": args.synthetic_test_mode,
    }
    exact_pass = (
        chooser.get("status") == "ESTIMATED"
        and directed_chooser.get("status") == "ESTIMATED"
        and directed_unordered.get("status") == "ESTIMATED"
        and scalar_close(chooser.get("coefficient"), EXPECTED_CHOOSER_COEFFICIENT, tolerance)
        and scalar_close(chooser.get("standard_error"), EXPECTED_CHOOSER_STANDARD_ERROR, tolerance)
        and int(chooser.get("absorbed_groups", -1)) == EXPECTED_CHOOSER_GROUPS
        and int(chooser.get("identifying_groups_with_both_arms", -1)) == EXPECTED_CHOOSER_SWITCHERS
        and int(chooser.get("observations_in_identifying_groups", -1)) == EXPECTED_CHOOSER_SWITCHER_ROWS
        and scalar_close(directed_chooser.get("coefficient"), EXPECTED_DIRECTED_PAIR_COEFFICIENT, tolerance)
        and scalar_close(directed_chooser.get("standard_error"), EXPECTED_DIRECTED_PAIR_CHOOSER_CLUSTER_SE, tolerance)
        and int(directed_chooser.get("absorbed_groups", -1)) == EXPECTED_DIRECTED_PAIR_GROUPS
        and int(directed_chooser.get("identifying_groups_with_both_arms", -1)) == EXPECTED_DIRECTED_PAIR_SWITCHERS
        and int(directed_chooser.get("observations_in_identifying_groups", -1)) == EXPECTED_DIRECTED_PAIR_SWITCHER_ROWS
        and scalar_close(directed_unordered.get("coefficient"), EXPECTED_DIRECTED_PAIR_COEFFICIENT, tolerance)
        and scalar_close(directed_unordered.get("standard_error"), EXPECTED_DIRECTED_PAIR_UNORDERED_CLUSTER_SE, tolerance)
    )
    baseline_reproduction["exact_authoritative_model_reproduction_pass"] = (
        None if args.synthetic_test_mode else exact_pass
    )
    if not args.synthetic_test_mode and not exact_pass:
        raise RuntimeError(
            "Exact authoritative C7X/C7R baseline reproduction failed: "
            f"{baseline_reproduction}"
        )

    bin_names = ("pair_eq_2", "pair_3_4", "pair_5_9", "pair_ge_10")
    support_rows: list[dict[str, Any]] = []
    for sample in bin_names:
        raw = raw_by_sample[sample]
        support_rows.append(
            {
                "pair_frequency_bin": sample,
                "description": raw["sample_description"],
                "all_observations": raw["observations"],
                "benefactor_observations": raw["benefactor_observations"],
                "share_of_all_benefactor_observations_pct": (
                    100.0 * int(raw["benefactor_observations"])
                    / args.expected_benefactor_rows
                ),
                "claimer_observations": raw["claimer_observations"],
                "share_of_all_claimer_observations_pct": (
                    100.0 * int(raw["claimer_observations"])
                    / args.expected_claimer_rows
                ),
                "benefactor_share_within_bin_pct": (
                    100.0 * int(raw["benefactor_observations"])
                    / int(raw["observations"])
                    if int(raw["observations"]) else None
                ),
            }
        )

    qa = {
        "status": QA_STATUS,
        "classification_row_conservation": data["kind"].size == args.expected_rows,
        "stage07_join_row_conservation": data["kind"].size == args.expected_rows,
        "raw_baseline_counts_reproduced": observed_baseline == expected_baseline,
        "exact_frequency_bins_partition_full_sample": sum(
            int(np.count_nonzero(mask_by_name[name])) for name in bin_names
        ) == args.expected_rows,
        "nested_dyad_samples_monotone": (
            int(np.count_nonzero(mask_by_name["pair_lt_3"]))
            <= int(np.count_nonzero(mask_by_name["pair_lt_5"]))
            <= int(np.count_nonzero(mask_by_name["pair_lt_10"]))
            <= args.expected_rows
        ),
        "full_chooser_model_estimated": chooser.get("status") == "ESTIMATED",
        "full_directed_pair_models_estimated": (
            directed_chooser.get("status") == "ESTIMATED"
            and directed_unordered.get("status") == "ESTIMATED"
        ),
        "exact_authoritative_baseline_reproduced": (
            True if args.synthetic_test_mode else exact_pass
        ),
        "aggregate_only_public_output": True,
    }
    if not all(value for value in qa.values() if isinstance(value, bool)):
        raise RuntimeError(
            f"QA gate failed: {qa}; full_models="
            f"{[model_by_key[('all', name)] for name in MODEL_NAMES]}"
        )

    config = {
        "status": "C7X_FREQUENT_DYAD_SENSITIVITY_CONFIGURATION_V101",
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "project_root": str(project),
        "stage07_root": str(stage_root),
        "c7x_classification": str(classification),
        "frequency_state_root": str(frequency_state),
        "output_root": str(output_root),
        "run_id": run_id,
        "threads": args.threads,
        "memory_limit": args.memory_limit.upper(),
        "samples": [name for name, _ in SAMPLE_SPECS],
        "model_contract": {
            "raw": "difference in arm-specific sample means; chooser-clustered inference",
            "chooser": {
                "fixed_effects": ["chooser_id", *CONTEXT_EFFECTS],
                "numeric_controls": list(NUMERIC_CONTROLS),
                "cluster": "chooser_id",
                "engine": "certified Campaign 1 HDFE v1.0.2",
            },
            "directed_pair": {
                "high_dimensional_fixed_effect": "ordered chooser-opponent pair",
                "context_fixed_effects": list(CONTEXT_EFFECTS),
                "numeric_controls": list(NUMERIC_CONTROLS),
                "clusters": ["chooser_id", "unordered pair"],
                "engine": "certified C7R exact-oneway v1.0.2",
            },
        },
        "frequency_timing": "whole-window pair counts; may include games after the focal outcome",
        "synthetic_test_mode": args.synthetic_test_mode,
    }
    config_sha = sha256_json(config)
    input_auth = {
        "status": "C7X_FREQUENT_DYAD_SENSITIVITY_INPUTS_AUTHENTICATED_OK",
        "stage07": {
            "root": str(stage_root),
            "files": len(stage_paths),
            "success_sha256": stage_success_sha,
            "schema": stage_names,
            "physical_authentication": stage_authentication,
        },
        "classification": {
            "path": str(classification),
            "sha256": classification_sha,
            "rows": args.expected_rows,
            "focal_outcome_present": False,
        },
        "frequency_flags": {
            "path": str(flags),
            "sha256": flags_receipt["output_sha256"],
            "rows": flags_receipt["rows"],
            "receipt": str(flags_receipt_path),
            "focal_outcome_present": False,
        },
        "estimation_engines": engine_authentication,
    }

    elapsed = time.time() - started
    summary = {
        "status": STATUS,
        "created_utc": utc_now(),
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "config_sha256": config_sha,
        "elapsed_seconds": elapsed,
        "full_sample_raw": full_raw,
        "baseline_reproduction": baseline_reproduction,
        "raw_sensitivity": raw_rows,
        "fixed_effect_sensitivity": model_rows,
        "support_by_pair_frequency": support_rows,
        "interpretation_limits": [
            "Repeated matching is a familiarity proxy, not a direct friendship measure.",
            "Whole-window frequency may include post-outcome rematches and is descriptive.",
            "The either-player exclusion is not estimated because it nearly eliminates C7X support.",
            "Directed-pair FE may be unidentified after strict low-frequency restrictions; support is reported explicitly.",
        ],
    }

    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    try:
        write_csv(staging / "raw_rate_sensitivity.csv", raw_rows)
        write_csv(staging / "fixed_effect_sensitivity.csv", model_rows)
        write_csv(staging / "support_by_pair_frequency.csv", support_rows)
        atomic_json(staging / "baseline_reproduction.json", baseline_reproduction)
        atomic_json(staging / "input_authentication.json", input_auth)
        atomic_json(staging / "run_config.json", config)
        atomic_json(staging / "qa.json", qa)
        atomic_json(staging / "summary.json", summary)
        result_readme = f"""# C7X frequent-dyad outcome sensitivity ({run_id})

Status: `{STATUS}`

This aggregate-only report re-estimates the C7X benefactor-versus-claimer
comparison after excluding dyads that met at least 3, 5, or 10 times anywhere
in the 24-month window. It also reports separate results for exactly 2, 3--4,
5--9, and 10+ games.

The full-sample gate exactly reproduces the certified C7X/C7R design before any
restricted result is accepted: chooser plus context HDFE, and directed-pair FE
with the same nine numeric controls and five context effects. The certified
targets are 14.556932 pp for chooser FE and 12.978154 pp for directed-pair FE.

## Files

- `raw_rate_sensitivity.csv`: arm rates and raw differences for every sample.
- `fixed_effect_sensitivity.csv`: certified-specification chooser and directed-
  pair models, including both chooser- and unordered-pair-clustered inference.
- `support_by_pair_frequency.csv`: exact-bin arm composition.
- `baseline_reproduction.json`: exact checks against the August 28 authorities.
- `summary.json`: complete machine-readable aggregate report.
- `input_authentication.json`, `run_config.json`, and `qa.json`: provenance and
  fail-closed gates.

## Interpretation

The dyad count is a familiarity proxy, not proof of friendship. Because the
count covers the full 24-month window, it may include rematches occurring after
the focal decision. These are descriptive robustness checks, not a
pre-treatment conditioning strategy. A separate historical-count analysis
must count pair meetings strictly before the prior grant or claim.

No row-level identifiers or outcomes are included in this public report.
"""
        atomic_text(staging / "README_results.md", result_readme)
        manifest_rows = public_file_manifest(staging)
        manifest_text = "file\tbytes\tsha256\n" + "".join(
            f"{row['file']}\t{row['bytes']}\t{row['sha256']}\n"
            for row in manifest_rows
        )
        atomic_text(staging / "file_manifest.tsv", manifest_text)
        atomic_json(
            staging / "_SUCCESS.json",
            {
                "status": STATUS,
                "created_utc": utc_now(),
                "run_id": run_id,
                "config_sha256": config_sha,
                "report_manifest_sha256": sha256_file(staging / "file_manifest.tsv"),
                "aggregate_only": True,
                "exact_authoritative_baseline_reproduced": (
                    True if not args.synthetic_test_mode else None
                ),
            },
        )
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    pointer = {
        "status": STATUS,
        "created_utc": utc_now(),
        "run_id": run_id,
        "output_dir": str(final),
        "success_sha256": sha256_file(final / "_SUCCESS.json"),
        "summary_sha256": sha256_file(final / "summary.json"),
        "config_sha256": config_sha,
    }
    atomic_json(output_root / "latest_execution.json", pointer)
    if args.execution_pointer:
        atomic_json(args.execution_pointer.resolve(), pointer)
    print(f"{STATUS}: {final}", flush=True)
    return final


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Certified-specification C7X sensitivity to whole-window frequent dyads"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument(
        "--stage07-success-sha256", default=EXPECTED_STAGE07_SUCCESS_SHA256
    )
    parser.add_argument("--c7x-classification", type=Path)
    parser.add_argument("--c7x-sha256", default=EXPECTED_C7X_SHA256)
    parser.add_argument("--frequency-state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execution-pointer", type=Path)
    parser.add_argument("--temp-directory", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--expected-rows", type=int, default=EXPECTED_ROWS)
    parser.add_argument(
        "--expected-benefactor-rows", type=int, default=EXPECTED_BENEFACTOR_ROWS
    )
    parser.add_argument(
        "--expected-claimer-rows", type=int, default=EXPECTED_CLAIMER_ROWS
    )
    parser.add_argument(
        "--expected-benefactor-kind", type=int, default=EXPECTED_BENEFACTOR_KIND
    )
    parser.add_argument(
        "--expected-claimer-kind", type=int, default=EXPECTED_CLAIMER_KIND
    )
    parser.add_argument("--authority-tolerance", type=float, default=1e-6)
    parser.add_argument("--allow-incomplete-months", action="store_true")
    parser.add_argument("--synthetic-test-mode", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("Pass --execute after reviewing the package README")
    if not math.isfinite(args.authority_tolerance) or args.authority_tolerance <= 0:
        parser.error("--authority-tolerance must be finite and positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        execute(args)
        return 0
    except BaseException as exc:
        print(
            f"C7X_FREQUENT_DYAD_SENSITIVITY_V101_FAILED: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
