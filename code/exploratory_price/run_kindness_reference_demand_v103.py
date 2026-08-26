#!/usr/bin/env python3
"""Estimate the reference-dependent demand schedule for kind draws.

This post-outcome corrective module distinguishes two Glicko-2 objects that the
paper has always kept conceptually separate:

* chooser_draw_payoff_v2 locates the draw relative to the chooser's pre-game
  rating and is the paper's operative, reference-dependent price margin;
* chooser_win_premium_v2 is the true opportunity cost and is retained as a
  control and as the secondary estimand from the immutable v1.0.2 lineage.

Because draw payoff is signed and crosses zero, a single global log elasticity
is not defined.  The module therefore reports the signed demand schedule,
matched-window and local-slope contrasts around zero, a conventional log
elasticity on the strictly positive loss-magnitude support, gain-side response
sensitivities, nonparametric bins, and all attempted heterogeneity estimates.
Every new estimate is exploratory (X), associational, and retained regardless
of sign or significance.  Certified Stage07 and Stage08 quantities are
authenticated before any new result is interpreted.
"""

from __future__ import annotations

import argparse
import gc
import math
from pathlib import Path
import shutil
import time
import traceback
from typing import Any, Callable, Mapping, Sequence

import kindness_price_elasticity_common_v102 as common
import run_kindness_price_elasticity_v102 as legacy


SCRIPT_VERSION = "1.0.3"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
STATE_NAME = "kindness_reference_demand_v103_PRIVATE"
OUTPUT_NAME = "kindness_reference_demand_v103"
PRIOR_STATE_NAME = "kindness_price_elasticity_v102_PRIVATE"
MINIMUM_FREE_BYTES = 20 * 1024**3
STRICT_AUDIT_TOLERANCE_PP = 5e-10

PRIMARY_LOSS_MODEL = "X_primary_loss_log_elasticity_chooser_fe_premium20_fe"
PRIMARY_REFERENCE_MODEL = "X_primary_reference_piecewise_chooser_fe_premium20_fe"
PRIMARY_MATCHED_MODEL = "X_primary_zero_crossing_w0p5_chooser_fe_premium20_fe"

WINDOWS = (0.5, 1.0, 2.0, 4.0, 6.0)
DONUTS = (0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0)
LOCAL_WINDOWS = (0.25, 0.5, 1.0, 2.0, 4.0)
PLACEBO_CUTOFFS = (-6.0, -4.0, -2.0, -1.0, 0.0, 1.0, 2.0, 4.0, 6.0)
PLACEBO_WINDOW = 0.5

SIGNED_BOUNDS = (
    -math.inf, -6.0, -4.0, -2.0, -1.0, -0.5, -0.25, -0.1,
    0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 6.0, math.inf,
)
SIGNED_LABELS = (
    "draw_lt_m6", "m6_to_m4", "m4_to_m2", "m2_to_m1",
    "m1_to_m0p5", "m0p5_to_m0p25", "m0p25_to_m0p1", "m0p1_to_0",
    "0_to_0p1", "0p1_to_0p25", "0p25_to_0p5", "0p5_to_1",
    "1_to_2", "2_to_4", "4_to_6", "draw_ge_6",
)
SIGNED_REFERENCE_BIN = 7
DENSITY_BOUNDS = (
    -math.inf, -1.0, -0.5, -0.25, -0.1, -0.05, -0.025, -0.01,
    0.0, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, math.inf,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--execution-pointer", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def finite(value: Any) -> Any:
    return legacy.finite(value)


def retained_error(error: BaseException) -> bool:
    return legacy.retained_error(error)


def safe_token(value: float) -> str:
    sign = "m" if value < 0 else ""
    return sign + f"{abs(value):g}".replace(".", "p")


def term_map(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["term"]): dict(row) for row in result.get("terms", [])}


def ci_from_term(row: Mapping[str, Any]) -> tuple[float, float]:
    coefficient = float(row.get("coefficient_probability_units", row.get("coefficient")))
    standard_error = float(
        row.get("standard_error_probability_units", row.get("standard_error_clustered"))
    )
    critical = 1.959963984540054
    return coefficient - critical * standard_error, coefficient + critical * standard_error


def base_specification(
    model: str, role: str, sample: str, *, premium_control: str
) -> dict[str, Any]:
    return {
        "model": model,
        "epistemic_label": "V" if role == "validation" else "X",
        "analysis_role": role,
        "sample": sample,
        "outcome": "indicator for kind draw",
        "operative_price_margin": (
            "chooser_draw_payoff_v2 relative to chooser pre-game rating; "
            "signed and reference-dependent"
        ),
        "true_opportunity_cost": (
            "chooser_win_premium_v2: rating points forgone by drawing instead of claiming"
        ),
        "premium_control": premium_control,
        "cluster": "chooser_username_norm mapped losslessly to chooser_index",
        "causal_claim": False,
        "structural_parameter_claim": False,
        "multiple_testing_family": "outside Campaign 1 confirmatory Holm family",
    }


def checkpoint_path(state: Path, model: str) -> Path:
    safe = "".join(
        character if character.isalnum() or character in "_-" else "_"
        for character in model
    )
    return state / "model_checkpoints" / f"{safe}.json"


def attempt_model(
    *, state: Path, config_sha256: str, attempts: list[dict[str, Any]],
    results: list[dict[str, Any]], model: str, fit: Callable[[], dict[str, Any]],
) -> None:
    checkpoint = checkpoint_path(state, model)
    if checkpoint.is_file():
        saved = common.load_json(checkpoint)
        if saved.get("config_sha256") != config_sha256 or saved.get("model") != model:
            raise RuntimeError(f"Model checkpoint configuration changed: {model}")
        attempts.append(dict(saved["attempt"]))
        if saved.get("result") is not None:
            results.append(dict(saved["result"]))
        print(f"REFERENCE_MODEL_CHECKPOINT_AUTHENTICATED model={model}", flush=True)
        return

    print(f"REFERENCE_MODEL_BEGIN model={model}", flush=True)
    started = time.time()
    attempt = {
        "model": model,
        "status": None,
        "error": None,
        "runtime_seconds": None,
    }
    result: dict[str, Any] | None = None
    try:
        result = finite(fit())
        results.append(result)
        attempt["status"] = "ESTIMATED"
        print(f"REFERENCE_MODEL_OK model={model}", flush=True)
    except BaseException as error:
        if not retained_error(error):
            raise
        attempt["status"] = "FAILED_RETAINED"
        attempt["error"] = f"{type(error).__name__}: {error}"
        print(f"REFERENCE_MODEL_FAILED_RETAINED model={model} error={error}", flush=True)
    attempt["runtime_seconds"] = time.time() - started
    attempts.append(attempt)
    common.atomic_json(
        checkpoint,
        finite(
            {
                "status": "KINDNESS_REFERENCE_MODEL_CHECKPOINT_OK",
                "created_utc": common.utc_now(),
                "config_sha256": config_sha256,
                "model": model,
                "attempt": attempt,
                "result": result,
            }
        ),
    )
    gc.collect()


def find_result(
    results: Sequence[Mapping[str, Any]], model: str, *, required: bool = True
) -> dict[str, Any] | None:
    matches = [dict(row) for row in results if row.get("model") == model]
    if len(matches) == 1:
        return matches[0]
    if required:
        raise RuntimeError(f"Expected exactly one result for {model}; found {len(matches)}")
    return None


def authenticate_prior_v102_cache(
    *, project: Path, scratch_state: Path, threads: int, memory_limit: str
) -> tuple[Path, dict[str, Any]] | None:
    """Authenticate and reuse the immutable v1.0.2 model Parquet read-only."""
    duckdb, _, _, pq = common.import_dependencies()
    prior = project / "derived/private" / PRIOR_STATE_NAME
    configuration = prior / "configuration.json"
    base = prior / "fair_price_base_private.parquet"
    base_receipt_path = prior / "fair_price_base_receipt.json"
    cache = prior / "fair_price_model_private.parquet"
    cache_receipt_path = prior / "fair_price_model_receipt.json"
    required = (configuration, base, base_receipt_path, cache, cache_receipt_path)
    existence = [path.exists() for path in required]
    if not any(existence):
        return None
    if not all(path.is_file() for path in required):
        raise RuntimeError(f"Prior v1.0.2 private cache is partial: {prior}")

    config = common.load_json(configuration)
    base_receipt = common.load_json(base_receipt_path)
    cache_receipt = common.load_json(cache_receipt_path)
    config_sha = config.get("config_sha256")
    if (
        not isinstance(config_sha, str)
        or base_receipt.get("config_sha256") != config_sha
        or cache_receipt.get("config_sha256") != config_sha
        or base_receipt.get("output_sha256") != common.sha256_file(base)
        or cache_receipt.get("output_sha256") != common.sha256_file(cache)
        or int(base_receipt.get("rows", -1)) != common.EXPECTED_FAIR_ROWS
        or int(cache_receipt.get("rows", -1)) != common.EXPECTED_FAIR_ROWS
        or int(base_receipt.get("kind_draws", -1)) != common.EXPECTED_FAIR_KIND_DRAWS
        or int(cache_receipt.get("kind_draws", -1)) != common.EXPECTED_FAIR_KIND_DRAWS
        or int(base_receipt.get("choosers", -1)) != common.EXPECTED_FAIR_CHOOSERS
        or int(cache_receipt.get("choosers", -1)) != common.EXPECTED_FAIR_CHOOSERS
        or int(pq.ParquetFile(base).metadata.num_rows) != common.EXPECTED_FAIR_ROWS
        or int(pq.ParquetFile(cache).metadata.num_rows) != common.EXPECTED_FAIR_ROWS
    ):
        raise RuntimeError("Prior v1.0.2 private cache failed receipt authentication")

    schema_names = set(pq.ParquetFile(cache).schema_arrow.names)
    missing = sorted(set(legacy.MODEL_COLUMNS) - schema_names)
    if missing:
        raise RuntimeError(f"Prior v1.0.2 model cache lacks columns: {missing}")

    connection = duckdb.connect()
    temp_root = scratch_state / "duckdb_temp/v102_read_only_auth"
    common.configure_duckdb(
        connection, threads=threads, memory_limit=memory_limit, temp_directory=temp_root
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          SUM(kind)::BIGINT,
          COUNT(DISTINCT chooser_index)::BIGINT,
          MIN(row_id)::BIGINT,
          MAX(row_id)::BIGINT,
          COUNT(*) FILTER (
            WHERE draw_payoff IS NULL OR NOT isfinite(draw_payoff)
               OR price IS NULL OR NOT isfinite(price) OR price <= 0
          )::BIGINT,
          COUNT(DISTINCT row_hash)::BIGINT
        FROM read_parquet({common.sql_literal(cache)})
        """
    ).fetchone()
    connection.close()
    shutil.rmtree(temp_root, ignore_errors=True)
    expected = (
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_KIND_DRAWS,
        common.EXPECTED_FAIR_CHOOSERS,
        0,
        common.EXPECTED_FAIR_ROWS - 1,
        0,
        common.EXPECTED_FAIR_ROWS,
    )
    if qa != expected:
        raise RuntimeError(f"Prior v1.0.2 model cache row conservation changed: {qa}")

    receipt = {
        **cache_receipt,
        "reuse_status": "V102_PRIVATE_MODEL_PARQUET_AUTHENTICATED_READ_ONLY",
        "source_state_root": str(prior),
        "source_configuration_sha256": config_sha,
        "row_conservation_qa": list(qa),
        "v103_writes_to_prior_state": False,
    }
    print("REFERENCE_V102_PRIVATE_CACHE_AUTHENTICATED_READ_ONLY_OK", flush=True)
    return cache, receipt


def obtain_model_cache(
    *, project: Path, stage_paths: Sequence[Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    reused = authenticate_prior_v102_cache(
        project=project,
        scratch_state=state,
        threads=threads,
        memory_limit=memory_limit,
    )
    if reused is not None:
        cache, receipt = reused
        return cache, {"status": "REUSED_V102_BASE_READ_ONLY"}, receipt

    print("REFERENCE_V102_CACHE_ABSENT_BUILDING_SEPARATE_V103_PARQUET", flush=True)
    cache_state = state / "cache_build"
    cache_state.mkdir(parents=True, exist_ok=True)
    base, base_receipt = legacy.build_fair_base(
        paths=stage_paths,
        state=cache_state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    cache, cache_receipt = legacy.build_model_cache(
        base=base,
        state=cache_state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    return cache, base_receipt, {
        **cache_receipt,
        "reuse_status": "SEPARATE_V103_COMPRESSED_PARQUET_BUILT",
        "v102_private_state_mutated": False,
    }


def premium_terms(
    data: Mapping[str, Any], indices: Any, mode: str
) -> tuple[dict[str, Any], list[Any]]:
    regressors: dict[str, Any] = {}
    fixed_effects: list[Any] = []
    if mode == "level":
        regressors["win_premium"] = data["price"][indices]
    elif mode == "log":
        regressors["log_win_premium"] = data["log_price"][indices]
    elif mode == "log_cubic":
        z, _ = legacy.standardized(data["log_price"][indices])
        regressors["log_win_premium_z"] = z
        regressors["log_win_premium_z2"] = z * z
        regressors["log_win_premium_z3"] = z * z * z
    elif mode == "bin20_fe":
        fixed_effects.append(data["price_bin20"][indices])
    elif mode == "none":
        pass
    else:
        raise ValueError(f"Unknown premium control mode: {mode}")
    return regressors, fixed_effects


def fit_reference_piecewise(
    *, data: Mapping[str, Any], mask: Any, model: str, role: str,
    premium_mode: str, adjusted: bool = False,
) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    indices = np.flatnonzero(mask)
    if indices.size < 1_000:
        raise RuntimeError(f"{model}: fewer than 1,000 rows")
    draw = data["draw_payoff"][indices]
    regressors = legacy.reference_piecewise(draw)
    premium, extra_fe = premium_terms(data, indices, premium_mode)
    regressors.update(premium)
    if adjusted:
        regressors.update(legacy.adjusted_controls(data, indices))
    result = common.fit_lpm_cluster(
        outcome=data["kind"][indices],
        regressors=regressors,
        clusters=data["chooser_index"][indices],
        fixed_effects=[data["chooser_index"][indices], *extra_fe],
        exposure_names=(
            "positive_draw_payoff", "negative_draw_payoff", "draw_nonnegative"
        ),
        row_ids=data["row_hash"][indices],
        specification=base_specification(
            model, role, f"rows_selected={indices.size}", premium_control=premium_mode
        ),
    )
    result.update(
        {
            "reference_function": "piecewise linear with nonnegative indicator",
            "adjusted_controls": adjusted,
            "draw_payoff_mean": float(np.mean(draw)),
            "draw_payoff_median": float(np.median(draw)),
            "win_premium_mean": float(np.mean(data["price"][indices])),
        }
    )
    return finite(result)


def fit_zero_contrast(
    *, data: Mapping[str, Any], mask: Any, model: str, role: str,
    premium_mode: str, cutoff: float = 0.0,
) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    indices = np.flatnonzero(mask)
    if indices.size < 1_000:
        raise RuntimeError(f"{model}: fewer than 1,000 rows")
    draw = data["draw_payoff"][indices]
    regressors: dict[str, Any] = {
        "above_cutoff": (draw >= cutoff).astype(np.float64)
    }
    premium, extra_fe = premium_terms(data, indices, premium_mode)
    regressors.update(premium)
    result = common.fit_lpm_cluster(
        outcome=data["kind"][indices],
        regressors=regressors,
        clusters=data["chooser_index"][indices],
        fixed_effects=[data["chooser_index"][indices], *extra_fe],
        exposure_names=("above_cutoff",),
        row_ids=data["row_hash"][indices],
        specification=base_specification(
            model, role, f"rows_selected={indices.size}", premium_control=premium_mode
        ),
    )
    result.update(
        {
            "cutoff": cutoff,
            "draw_minimum": float(np.min(draw)),
            "draw_maximum": float(np.max(draw)),
            "left_rows": int(np.count_nonzero(draw < cutoff)),
            "right_rows": int(np.count_nonzero(draw >= cutoff)),
        }
    )
    return finite(result)


def fit_local_polynomial(
    *, data: Mapping[str, Any], mask: Any, model: str, order: int,
    premium_mode: str,
) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    indices = np.flatnonzero(mask)
    if indices.size < 1_000:
        raise RuntimeError(f"{model}: fewer than 1,000 rows")
    draw = np.asarray(data["draw_payoff"][indices], dtype=np.float64)
    nonnegative = (draw >= 0).astype(np.float64)
    regressors: dict[str, Any] = {"draw_nonnegative": nonnegative}
    for power in range(1, order + 1):
        base = draw ** power
        regressors[f"draw_power_{power}"] = base
        regressors[f"draw_power_{power}_x_nonnegative"] = base * nonnegative
    premium, extra_fe = premium_terms(data, indices, premium_mode)
    regressors.update(premium)
    result = common.fit_lpm_cluster(
        outcome=data["kind"][indices],
        regressors=regressors,
        clusters=data["chooser_index"][indices],
        fixed_effects=[data["chooser_index"][indices], *extra_fe],
        exposure_names=("draw_nonnegative",),
        row_ids=data["row_hash"][indices],
        specification=base_specification(
            model,
            "exploratory_local_reference_shape",
            f"rows_selected={indices.size}",
            premium_control=premium_mode,
        ),
    )
    result.update(
        {
            "local_polynomial_order": order,
            "kernel": "uniform within declared symmetric window",
            "causal_rdd_claim": False,
            "note": (
                "The cutoff term is a descriptive local intercept contrast, not a "
                "causal RDD estimand; draw payoff and relative rating are the same "
                "underlying ordering variable."
            ),
        }
    )
    return finite(result)


def fit_side_model(
    *, data: Mapping[str, Any], mask: Any, model: str, side: str,
    transform: str, premium_mode: str, adjusted: bool = False,
    override_exposure: Any | None = None,
) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    indices = np.flatnonzero(mask)
    if indices.size < 1_000:
        raise RuntimeError(f"{model}: fewer than 1,000 rows")
    draw = np.asarray(data["draw_payoff"][indices], dtype=np.float64)
    magnitude = -draw if side == "loss" else draw
    if np.any(magnitude <= 0) or not np.all(np.isfinite(magnitude)):
        raise RuntimeError(f"{model}: {side}-side magnitude is not strictly positive")
    if override_exposure is not None:
        exposure = np.asarray(override_exposure, dtype=np.float64)[indices]
    elif transform == "log":
        exposure = np.log(magnitude)
    elif transform == "level":
        exposure = magnitude
    else:
        raise ValueError(f"Unknown side transform: {transform}")
    exposure_name = f"{'log_' if transform == 'log' else ''}reference_{side}_magnitude"
    regressors: dict[str, Any] = {exposure_name: exposure}
    premium, extra_fe = premium_terms(data, indices, premium_mode)
    regressors.update(premium)
    if adjusted:
        regressors.update(legacy.adjusted_controls(data, indices))
    result = common.fit_lpm_cluster(
        outcome=data["kind"][indices],
        regressors=regressors,
        clusters=data["chooser_index"][indices],
        fixed_effects=[data["chooser_index"][indices], *extra_fe],
        exposure_names=(exposure_name,),
        row_ids=data["row_hash"][indices],
        specification=base_specification(
            model,
            "exploratory_reference_side_elasticity",
            f"strictly_{side}_side_rows={indices.size}",
            premium_control=premium_mode,
        ),
    )
    common.add_lpm_elasticity(
        result,
        term=exposure_name,
        price_scale=None if transform == "log" else float(np.mean(magnitude)),
    )
    probabilities = (0.005, 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 0.995)
    result.update(
        {
            "reference_side": side,
            "magnitude_transform": transform,
            "magnitude_mean": float(np.mean(magnitude)),
            "magnitude_median": float(np.median(magnitude)),
            "magnitude_quantile_probabilities": list(probabilities),
            "magnitude_quantile_values": [
                float(value) for value in np.quantile(magnitude, probabilities)
            ],
            "adjusted_controls": adjusted,
            "interpretation_boundary": (
                "A conventional price elasticity only on the loss side."
                if side == "loss"
                else "A responsiveness-to-rating-gain measure, not a price elasticity."
            ),
        }
    )
    return finite(result)


def run_validation(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    model = "V_certified_stage08_full24_piecewise_reproduction_v103"
    mask = np.ones(data["kind"].size, dtype=bool)
    attempt_model(
        state=state,
        config_sha256=config_sha256,
        attempts=attempts,
        results=results,
        model=model,
        fit=lambda: fit_reference_piecewise(
            data=data,
            mask=mask,
            model=model,
            role="validation",
            premium_mode="level",
        ),
    )
    fitted = find_result(results, model)
    assert fitted is not None
    terms = term_map(fitted)
    observed = {
        "beta_plus_pp_per_rating_point": float(
            terms["positive_draw_payoff"]["coefficient_percentage_points"]
        ),
        "beta_minus_pp_per_rating_point": float(
            terms["negative_draw_payoff"]["coefficient_percentage_points"]
        ),
        "threshold_jump_pp": float(
            terms["draw_nonnegative"]["coefficient_percentage_points"]
        ),
    }
    differences = {
        key: observed[key] - common.EXPECTED_STAGE08_FULL_PIECEWISE[key]
        for key in observed
    }
    if any(abs(value) > STRICT_AUDIT_TOLERANCE_PP for value in differences.values()):
        raise RuntimeError(f"Certified Stage08 reproduction failed: {differences}")
    receipt = {
        "status": "REFERENCE_STAGE08_EXACT_REPRODUCTION_OK",
        "expected": common.EXPECTED_STAGE08_FULL_PIECEWISE,
        "observed": observed,
        "differences": differences,
        "tolerance_pp": STRICT_AUDIT_TOLERANCE_PP,
        "validation_precedes_new_interpretation": True,
    }
    print("REFERENCE_STAGE08_EXACT_REPRODUCTION_OK", flush=True)
    return receipt


def run_piecewise_family(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> None:
    _, np, _, _ = common.import_dependencies()
    all_rows = np.ones(data["kind"].size, dtype=bool)
    definitions = (
        (PRIMARY_REFERENCE_MODEL, "bin20_fe", False),
        ("X_reference_piecewise_chooser_fe_level_premium", "level", False),
        ("X_reference_piecewise_chooser_fe_log_premium", "log", False),
        ("X_reference_piecewise_chooser_fe_log_cubic_premium", "log_cubic", False),
        ("X_reference_piecewise_chooser_fe_premium20_fe_adjusted", "bin20_fe", True),
    )
    for model, premium_mode, adjusted in definitions:
        attempt_model(
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
            model=model,
            fit=lambda model=model, premium_mode=premium_mode, adjusted=adjusted: (
                fit_reference_piecewise(
                    data=data,
                    mask=all_rows,
                    model=model,
                    role="exploratory_reference_schedule",
                    premium_mode=premium_mode,
                    adjusted=adjusted,
                )
            ),
        )

    draw = data["draw_payoff"]
    for window in WINDOWS:
        mask = np.abs(draw) <= window
        for premium_mode in ("level", "bin20_fe"):
            model = (
                f"X_reference_piecewise_abs_le_{safe_token(window)}_chooser_fe_"
                f"{'premium20_fe' if premium_mode == 'bin20_fe' else 'level_premium'}"
            )
            attempt_model(
                state=state,
                config_sha256=config_sha256,
                attempts=attempts,
                results=results,
                model=model,
                fit=lambda model=model, mask=mask, premium_mode=premium_mode: (
                    fit_reference_piecewise(
                        data=data,
                        mask=mask,
                        model=model,
                        role="exploratory_local_reference_schedule",
                        premium_mode=premium_mode,
                    )
                ),
            )


def run_matched_windows(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = common.import_dependencies()
    draw = data["draw_payoff"]
    headline_rows: list[dict[str, Any]] = []
    donut_rows: list[dict[str, Any]] = []

    for window in WINDOWS:
        mask = np.abs(draw) <= window
        for premium_mode in ("level", "bin20_fe"):
            model = (
                PRIMARY_MATCHED_MODEL
                if window == 0.5 and premium_mode == "bin20_fe"
                else f"X_zero_crossing_w{safe_token(window)}_chooser_fe_"
                f"{'premium20_fe' if premium_mode == 'bin20_fe' else 'level_premium'}"
            )
            attempt_model(
                state=state,
                config_sha256=config_sha256,
                attempts=attempts,
                results=results,
                model=model,
                fit=lambda model=model, mask=mask, premium_mode=premium_mode: (
                    fit_zero_contrast(
                        data=data,
                        mask=mask,
                        model=model,
                        role="exploratory_matched_reference_window",
                        premium_mode=premium_mode,
                    )
                ),
            )
            fitted = find_result(results, model, required=False)
            if fitted is None:
                attempt = next(row for row in attempts if row["model"] == model)
                headline_rows.append(
                    {
                        "model": model,
                        "window": window,
                        "donut": 0.0,
                        "premium_control": premium_mode,
                        "status": attempt["status"],
                        "error": attempt["error"],
                    }
                )
            else:
                term = term_map(fitted)["above_cutoff"]
                low, high = ci_from_term(term)
                coefficient = float(term["coefficient_probability_units"])
                outcome_mean = float(fitted["outcome_mean"])
                headline_rows.append(
                    {
                        "model": model,
                        "window": window,
                        "donut": 0.0,
                        "premium_control": premium_mode,
                        "status": "ESTIMATED",
                        "coefficient_probability_units": term["coefficient_probability_units"],
                        "coefficient_percentage_points": term["coefficient_percentage_points"],
                        "standard_error_percentage_points": term["standard_error_percentage_points"],
                        "ci95_low_pp": 100.0 * low,
                        "ci95_high_pp": 100.0 * high,
                        "mean_scaled_relative_change": coefficient / outcome_mean,
                        "mean_scaled_ci95_low": low / outcome_mean,
                        "mean_scaled_ci95_high": high / outcome_mean,
                        "t_cluster": term["t_cluster"],
                        "p_value_two_sided": term["p_value_two_sided"],
                        "rows": fitted["rows_raw"],
                        "chooser_clusters": fitted["chooser_clusters"],
                        "outcome_mean": outcome_mean,
                    }
                )

        for donut in DONUTS:
            if donut <= 0 or donut >= window:
                continue
            model = (
                f"X_zero_donut_w{safe_token(window)}_d{safe_token(donut)}_"
                "chooser_fe_level_premium"
            )
            donut_mask = (np.abs(draw) <= window) & (np.abs(draw) >= donut)
            attempt_model(
                state=state,
                config_sha256=config_sha256,
                attempts=attempts,
                results=results,
                model=model,
                fit=lambda model=model, donut_mask=donut_mask: fit_zero_contrast(
                    data=data,
                    mask=donut_mask,
                    model=model,
                    role="exploratory_reference_donut_grid",
                    premium_mode="level",
                ),
            )
            fitted = find_result(results, model, required=False)
            if fitted is None:
                attempt = next(row for row in attempts if row["model"] == model)
                donut_rows.append(
                    {
                        "model": model,
                        "window": window,
                        "donut": donut,
                        "status": attempt["status"],
                        "error": attempt["error"],
                    }
                )
            else:
                term = term_map(fitted)["above_cutoff"]
                low, high = ci_from_term(term)
                coefficient = float(term["coefficient_probability_units"])
                outcome_mean = float(fitted["outcome_mean"])
                donut_rows.append(
                    {
                        "model": model,
                        "window": window,
                        "donut": donut,
                        "status": "ESTIMATED",
                        "coefficient_percentage_points": term["coefficient_percentage_points"],
                        "standard_error_percentage_points": term["standard_error_percentage_points"],
                        "ci95_low_pp": 100.0 * low,
                        "ci95_high_pp": 100.0 * high,
                        "mean_scaled_relative_change": coefficient / outcome_mean,
                        "t_cluster": term["t_cluster"],
                        "p_value_two_sided": term["p_value_two_sided"],
                        "rows": fitted["rows_raw"],
                        "chooser_clusters": fitted["chooser_clusters"],
                    }
                )
    return headline_rows, donut_rows


def run_local_shape_and_placebos(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    _, np, _, _ = common.import_dependencies()
    draw = data["draw_payoff"]
    placebo_rows: list[dict[str, Any]] = []
    for window in LOCAL_WINDOWS:
        mask = np.abs(draw) <= window
        for order in (1, 2):
            model = (
                f"X_local_order{order}_reference_w{safe_token(window)}_"
                "chooser_fe_level_premium"
            )
            attempt_model(
                state=state,
                config_sha256=config_sha256,
                attempts=attempts,
                results=results,
                model=model,
                fit=lambda model=model, mask=mask, order=order: fit_local_polynomial(
                    data=data,
                    mask=mask,
                    model=model,
                    order=order,
                    premium_mode="level",
                ),
            )

    for cutoff in PLACEBO_CUTOFFS:
        mask = np.abs(draw - cutoff) <= PLACEBO_WINDOW
        model = (
            f"X_placebo_cutoff_{safe_token(cutoff)}_w{safe_token(PLACEBO_WINDOW)}_"
            "chooser_fe_level_premium"
        )
        attempt_model(
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
            model=model,
            fit=lambda model=model, mask=mask, cutoff=cutoff: fit_zero_contrast(
                data=data,
                mask=mask,
                model=model,
                role="exploratory_reference_placebo_cutoff",
                premium_mode="level",
                cutoff=cutoff,
            ),
        )
        fitted = find_result(results, model, required=False)
        if fitted is None:
            attempt = next(row for row in attempts if row["model"] == model)
            placebo_rows.append(
                {
                    "model": model,
                    "cutoff": cutoff,
                    "window": PLACEBO_WINDOW,
                    "status": attempt["status"],
                    "error": attempt["error"],
                }
            )
        else:
            term = term_map(fitted)["above_cutoff"]
            low, high = ci_from_term(term)
            placebo_rows.append(
                {
                    "model": model,
                    "cutoff": cutoff,
                    "window": PLACEBO_WINDOW,
                    "status": "ESTIMATED",
                    "coefficient_percentage_points": term["coefficient_percentage_points"],
                    "standard_error_percentage_points": term["standard_error_percentage_points"],
                    "ci95_low_pp": 100.0 * low,
                    "ci95_high_pp": 100.0 * high,
                    "t_cluster": term["t_cluster"],
                    "p_value_two_sided": term["p_value_two_sided"],
                    "rows": fitted["rows_raw"],
                    "chooser_clusters": fitted["chooser_clusters"],
                }
            )
    return placebo_rows


def side_masks_and_transforms(data: Mapping[str, Any]) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    loss = draw < 0
    gain = draw > 0
    if np.count_nonzero(loss) < 1_000 or np.count_nonzero(gain) < 1_000:
        raise RuntimeError("Reference-price sides lack support")
    loss_magnitude = np.where(loss, -draw, np.nan)
    gain_magnitude = np.where(gain, draw, np.nan)
    loss_values = loss_magnitude[loss]
    gain_values = gain_magnitude[gain]
    loss_p005, loss_p01, loss_p99, loss_p995 = np.quantile(
        loss_values, [0.005, 0.01, 0.99, 0.995]
    )
    gain_p005, gain_p01, gain_p99, gain_p995 = np.quantile(
        gain_values, [0.005, 0.01, 0.99, 0.995]
    )
    return {
        "loss": loss,
        "gain": gain,
        "loss_magnitude": loss_magnitude,
        "gain_magnitude": gain_magnitude,
        "loss_trim_p005_p995": loss & (loss_magnitude >= loss_p005) & (loss_magnitude <= loss_p995),
        "loss_trim_p01_p99": loss & (loss_magnitude >= loss_p01) & (loss_magnitude <= loss_p99),
        "gain_trim_p005_p995": gain & (gain_magnitude >= gain_p005) & (gain_magnitude <= gain_p995),
        "gain_trim_p01_p99": gain & (gain_magnitude >= gain_p01) & (gain_magnitude <= gain_p99),
        "loss_log_winsor_p005_p995": np.where(
            loss, np.log(np.clip(loss_magnitude, loss_p005, loss_p995)), np.nan
        ),
        "loss_log_winsor_p01_p99": np.where(
            loss, np.log(np.clip(loss_magnitude, loss_p01, loss_p99)), np.nan
        ),
        "gain_log_winsor_p005_p995": np.where(
            gain, np.log(np.clip(gain_magnitude, gain_p005, gain_p995)), np.nan
        ),
        "gain_log_winsor_p01_p99": np.where(
            gain, np.log(np.clip(gain_magnitude, gain_p01, gain_p99)), np.nan
        ),
        "loss_quantiles": [float(loss_p005), float(loss_p01), float(loss_p99), float(loss_p995)],
        "gain_quantiles": [float(gain_p005), float(gain_p01), float(gain_p99), float(gain_p995)],
    }


def run_side_elasticities(
    *, data: Mapping[str, Any], side_data: Mapping[str, Any], state: Path,
    config_sha256: str, attempts: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> None:
    definitions = (
        (PRIMARY_LOSS_MODEL, "loss", "log", "bin20_fe", side_data["loss"], False, None),
        ("X_loss_log_elasticity_chooser_fe_level_premium", "loss", "log", "level", side_data["loss"], False, None),
        ("X_loss_log_elasticity_chooser_fe_log_premium", "loss", "log", "log", side_data["loss"], False, None),
        ("X_loss_log_elasticity_chooser_fe_log_cubic_premium", "loss", "log", "log_cubic", side_data["loss"], False, None),
        ("X_loss_log_elasticity_chooser_fe_premium20_fe_adjusted", "loss", "log", "bin20_fe", side_data["loss"], True, None),
        ("X_loss_level_slope_chooser_fe_premium20_fe", "loss", "level", "bin20_fe", side_data["loss"], False, None),
        ("X_loss_log_elasticity_trim_p005_p995_premium20_fe", "loss", "log", "bin20_fe", side_data["loss_trim_p005_p995"], False, None),
        ("X_loss_log_elasticity_trim_p01_p99_premium20_fe", "loss", "log", "bin20_fe", side_data["loss_trim_p01_p99"], False, None),
        ("X_loss_log_elasticity_winsor_p005_p995_premium20_fe", "loss", "log", "bin20_fe", side_data["loss"], False, side_data["loss_log_winsor_p005_p995"]),
        ("X_loss_log_elasticity_winsor_p01_p99_premium20_fe", "loss", "log", "bin20_fe", side_data["loss"], False, side_data["loss_log_winsor_p01_p99"]),
        ("X_gain_log_response_chooser_fe_premium20_fe", "gain", "log", "bin20_fe", side_data["gain"], False, None),
        ("X_gain_log_response_chooser_fe_level_premium", "gain", "log", "level", side_data["gain"], False, None),
        ("X_gain_level_slope_chooser_fe_premium20_fe", "gain", "level", "bin20_fe", side_data["gain"], False, None),
        ("X_gain_log_response_trim_p005_p995_premium20_fe", "gain", "log", "bin20_fe", side_data["gain_trim_p005_p995"], False, None),
        ("X_gain_log_response_trim_p01_p99_premium20_fe", "gain", "log", "bin20_fe", side_data["gain_trim_p01_p99"], False, None),
        ("X_gain_log_response_winsor_p005_p995_premium20_fe", "gain", "log", "bin20_fe", side_data["gain"], False, side_data["gain_log_winsor_p005_p995"]),
        ("X_gain_log_response_winsor_p01_p99_premium20_fe", "gain", "log", "bin20_fe", side_data["gain"], False, side_data["gain_log_winsor_p01_p99"]),
    )
    for model, side, transform, premium_mode, mask, adjusted, override in definitions:
        attempt_model(
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
            model=model,
            fit=lambda model=model, side=side, transform=transform,
                       premium_mode=premium_mode, mask=mask, adjusted=adjusted,
                       override=override: (
                fit_side_model(
                    data=data,
                    mask=mask,
                    model=model,
                    side=side,
                    transform=transform,
                    premium_mode=premium_mode,
                    adjusted=adjusted,
                    override_exposure=override,
                )
            ),
        )


def run_side_ppml(
    *, data: Mapping[str, Any], side_data: Mapping[str, Any], state: Path,
    config_sha256: str, attempts: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> None:
    _, np, _, _ = common.import_dependencies()
    for side in ("loss", "gain"):
        model = f"X_{side}_conditional_chooser_fe_poisson_log_magnitude_controls"
        mask = side_data[side]

        def fit(model: str = model, side: str = side, mask: Any = mask) -> dict[str, Any]:
            indices = np.flatnonzero(mask)
            draw = data["draw_payoff"][indices]
            magnitude = -draw if side == "loss" else draw
            exposure = f"log_reference_{side}_magnitude"
            regressors: dict[str, Any] = {
                exposure: np.log(magnitude),
                "log_win_premium": data["log_price"][indices],
            }
            eval_z, _ = legacy.standardized(data["engine_eval_cp"][indices])
            regressors["engine_eval_z"] = eval_z
            regressors["engine_eval_z2"] = eval_z * eval_z
            result = common.conditional_fe_poisson(
                outcome=data["kind"][indices],
                regressors=regressors,
                chooser_codes=data["chooser_index"][indices],
                exposure_name=exposure,
                specification=base_specification(
                    model,
                    "exploratory_reference_side_log_link_sensitivity",
                    f"strictly_{side}_side_rows={indices.size}",
                    premium_control="log",
                ),
            )
            result["reference_side"] = side
            result["interpretation_boundary"] = (
                "Direct loss-side elasticity under conditional Poisson QMLE."
                if side == "loss"
                else "Gain responsiveness, not price elasticity."
            )
            return finite(result)

        attempt_model(
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
            model=model,
            fit=fit,
        )


def run_heterogeneity(
    *, data: Mapping[str, Any], side_data: Mapping[str, Any], state: Path,
    config_sha256: str, attempts: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    _, np, _, _ = common.import_dependencies()
    grids: list[tuple[str, Any, Sequence[int], Sequence[str]]] = [
        ("rating_band", data["rating_band"], range(4), ("below_1600", "1600_1999", "2000_2399", "2400_plus")),
        ("speed", data["speed_code"], range(6), ("ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence")),
        ("eval_band", data["eval_band"], range(5), ("below_0cp", "0_100cp", "101_300cp", "301_600cp", "above_600cp")),
        ("temporal_half", (data["month_code"] >= 12).astype(int), range(2), ("first12", "second12")),
        ("rating_certainty", data["both_rd_le_110"], range(2), ("either_rd_above_110", "both_rd_le_110")),
        ("activity_quartile", data["activity_quartile"], range(4), ("q1", "q2", "q3", "q4")),
        ("lagged_kindness", data["prior_kind_stratum"], range(3), ("none_prior", "one_prior", "two_plus_prior")),
    ]
    metadata: list[dict[str, Any]] = []
    for dimension, values, levels, labels in grids:
        for level, label in zip(levels, labels, strict=True):
            mask = side_data["loss"] & (np.asarray(values) == level)
            model = f"X_loss_log_heterogeneity_{dimension}_{label}_chooser_fe_level_premium"
            metadata.append(
                {
                    "model": model,
                    "dimension": dimension,
                    "level": int(level),
                    "label": label,
                    "requested_loss_rows": int(np.count_nonzero(mask)),
                    "requested_choosers": int(
                        np.unique(data["chooser_index"][mask]).size
                    ),
                }
            )
            attempt_model(
                state=state,
                config_sha256=config_sha256,
                attempts=attempts,
                results=results,
                model=model,
                fit=lambda model=model, mask=mask: fit_side_model(
                    data=data,
                    mask=mask,
                    model=model,
                    side="loss",
                    transform="log",
                    premium_mode="level",
                ),
            )
    return metadata


def signed_band_codes(draw: Any) -> Any:
    _, np, _, _ = common.import_dependencies()
    internal = np.asarray(SIGNED_BOUNDS[1:-1], dtype=np.float64)
    return np.digitize(np.asarray(draw, dtype=np.float64), internal, right=False).astype(
        np.int64
    )


def run_nonparametric_schedule(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    _, np, _, _ = common.import_dependencies()
    model = "X_nonparametric_signed_reference_bands_chooser_fe_premium20_fe"
    codes = signed_band_codes(data["draw_payoff"])
    realized = sorted(int(value) for value in np.unique(codes))
    if SIGNED_REFERENCE_BIN not in realized:
        raise RuntimeError("Predetermined just-below-zero reference bin is empty")

    def fit() -> dict[str, Any]:
        regressors = {
            f"signed_band_{level}": (codes == level).astype(np.float64)
            for level in realized
            if level != SIGNED_REFERENCE_BIN
        }
        result = common.fit_lpm_cluster(
            outcome=data["kind"],
            regressors=regressors,
            clusters=data["chooser_index"],
            fixed_effects=(data["chooser_index"], data["price_bin20"]),
            exposure_names=tuple(regressors),
            row_ids=data["row_hash"],
            specification=base_specification(
                model,
                "exploratory_nonparametric_reference_schedule",
                "all certified fair rows",
                premium_control="bin20_fe",
            ),
        )
        result["reference_bin"] = SIGNED_REFERENCE_BIN
        result["reference_bin_label"] = SIGNED_LABELS[SIGNED_REFERENCE_BIN]
        result["predetermined_bounds"] = list(SIGNED_BOUNDS)
        return finite(result)

    attempt_model(
        state=state,
        config_sha256=config_sha256,
        attempts=attempts,
        results=results,
        model=model,
        fit=fit,
    )
    fitted = find_result(results, model, required=False)
    if fitted is None:
        attempt = next(row for row in attempts if row["model"] == model)
        placeholder = {
            "model": model,
            "status": attempt["status"],
            "error": attempt["error"],
        }
        return [placeholder], [placeholder], placeholder

    terms = term_map(fitted)
    coefficients: dict[int, float] = {SIGNED_REFERENCE_BIN: 0.0}
    for level in realized:
        if level != SIGNED_REFERENCE_BIN:
            coefficients[level] = float(
                terms[f"signed_band_{level}"]["coefficient_probability_units"]
            )
    shares = {level: float(np.mean(codes == level)) for level in realized}
    weighted_effect = sum(shares[level] * coefficients[level] for level in realized)
    overall_mean = float(np.mean(data["kind"]))
    draw = data["draw_payoff"]
    rows: list[dict[str, Any]] = []
    for level in realized:
        mask = codes == level
        values = draw[mask]
        raw_rate = float(np.mean(data["kind"][mask]))
        adjusted_rate = overall_mean + coefficients[level] - weighted_effect
        rows.append(
            {
                "signed_band": level,
                "label": SIGNED_LABELS[level],
                "lower_bound": SIGNED_BOUNDS[level],
                "upper_bound": SIGNED_BOUNDS[level + 1],
                "reference_bin": level == SIGNED_REFERENCE_BIN,
                "rows": int(np.count_nonzero(mask)),
                "choosers": int(np.unique(data["chooser_index"][mask]).size),
                "kind_draws": int(np.sum(data["kind"][mask])),
                "draw_payoff_mean": float(np.mean(values)),
                "draw_payoff_median": float(np.median(values)),
                "draw_payoff_minimum": float(np.min(values)),
                "draw_payoff_maximum": float(np.max(values)),
                "reference_loss_magnitude_mean": (
                    float(np.mean(-values)) if np.all(values < 0) else None
                ),
                "reference_gain_magnitude_mean": (
                    float(np.mean(values)) if np.all(values >= 0) else None
                ),
                "raw_kind_rate": raw_rate,
                "raw_kind_rate_pct": 100.0 * raw_rate,
                "adjusted_kind_rate_centered_to_overall_mean": adjusted_rate,
                "adjusted_kind_rate_pct": 100.0 * adjusted_rate,
                "bin_effect_relative_to_just_below_zero_probability_units": coefficients[level],
                "bin_effect_relative_to_just_below_zero_pp": 100.0 * coefficients[level],
            }
        )

    arcs: list[dict[str, Any]] = []
    loss_rows = sorted(
        [row for row in rows if row["reference_loss_magnitude_mean"] is not None],
        key=lambda row: float(row["reference_loss_magnitude_mean"]),
    )
    gain_rows = sorted(
        [row for row in rows if row["reference_gain_magnitude_mean"] is not None],
        key=lambda row: float(row["reference_gain_magnitude_mean"]),
    )
    for side, ordered, price_field in (
        ("loss", loss_rows, "reference_loss_magnitude_mean"),
        ("gain", gain_rows, "reference_gain_magnitude_mean"),
    ):
        for left, right in zip(ordered[:-1], ordered[1:], strict=True):
            p0, p1 = float(left[price_field]), float(right[price_field])
            for rate_field, label in (
                ("raw_kind_rate", "raw"),
                (
                    "adjusted_kind_rate_centered_to_overall_mean",
                    "chooser_fe_premium20_fe_adjusted",
                ),
            ):
                q0, q1 = float(left[rate_field]), float(right[rate_field])
                price_change = (p1 - p0) / ((p1 + p0) / 2.0)
                quantity_change = (
                    (q1 - q0) / ((q1 + q0) / 2.0)
                    if q1 + q0 > 0
                    else math.nan
                )
                arcs.append(
                    finite(
                        {
                            "side": side,
                            "interpretation": (
                                "reference-loss arc elasticity"
                                if side == "loss"
                                else "rating-gain response arc; not a price elasticity"
                            ),
                            "left_band": left["signed_band"],
                            "right_band": right["signed_band"],
                            "rate_series": label,
                            "left_magnitude_mean": p0,
                            "right_magnitude_mean": p1,
                            "left_kind_rate": q0,
                            "right_kind_rate": q1,
                            "midpoint_arc_elasticity_or_response": (
                                quantity_change / price_change
                                if price_change != 0
                                else math.nan
                            ),
                        }
                    )
                )

    left = next(row for row in rows if row["signed_band"] == SIGNED_REFERENCE_BIN)
    right = next(row for row in rows if row["signed_band"] == SIGNED_REFERENCE_BIN + 1)
    zero_crossing = {
        "status": "DESCRIPTIVE_ADJACENT_PREDETERMINED_BINS",
        "left_bin": left,
        "right_bin": right,
        "raw_difference_pp": 100.0 * (right["raw_kind_rate"] - left["raw_kind_rate"]),
        "adjusted_difference_pp": 100.0 * (
            right["adjusted_kind_rate_centered_to_overall_mean"]
            - left["adjusted_kind_rate_centered_to_overall_mean"]
        ),
        "raw_relative_change_from_left": (
            (right["raw_kind_rate"] - left["raw_kind_rate"])
            / left["raw_kind_rate"]
            if left["raw_kind_rate"] > 0
            else None
        ),
        "adjusted_relative_change_from_left": (
            (
                right["adjusted_kind_rate_centered_to_overall_mean"]
                - left["adjusted_kind_rate_centered_to_overall_mean"]
            )
            / left["adjusted_kind_rate_centered_to_overall_mean"]
            if left["adjusted_kind_rate_centered_to_overall_mean"] > 0
            else None
        ),
        "elasticity_at_zero": None,
        "elasticity_status": "UNDEFINED_BECAUSE_REFERENCE_PRICE_EQUALS_ZERO",
    }
    return rows, arcs, finite(zero_crossing)


def support_and_balance(data: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _, np, _, _ = common.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    loss = draw < 0
    zero = draw == 0
    gain = draw > 0
    probabilities = (0.0, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.995, 1.0)
    support = {
        "status": "REFERENCE_PRICE_SUPPORT_FROZEN_BEFORE_OUTCOME_MODELS",
        "rows": int(draw.size),
        "loss_rows": int(np.count_nonzero(loss)),
        "zero_rows": int(np.count_nonzero(zero)),
        "gain_rows": int(np.count_nonzero(gain)),
        "loss_share": float(np.mean(loss)),
        "zero_share": float(np.mean(zero)),
        "gain_share": float(np.mean(gain)),
        "draw_payoff_quantile_probabilities": list(probabilities),
        "draw_payoff_quantile_values": [float(value) for value in np.quantile(draw, probabilities)],
        "loss_magnitude_quantile_values": [
            float(value) for value in np.quantile(-draw[loss], probabilities)
        ],
        "gain_magnitude_quantile_values": [
            float(value) for value in np.quantile(draw[gain], probabilities)
        ],
        "single_global_log_elasticity_defined": False,
        "reason": "draw payoff has negative, zero, and positive support",
    }
    balance: list[dict[str, Any]] = []
    fields = (
        "price", "engine_eval_cp", "chooser_elo", "opponent_elo", "chooser_rd",
        "opponent_rd", "log_chooser_clock", "log_opponent_clock", "tournament",
        "month_code", "speed_code",
    )
    for window in WINDOWS:
        within = np.abs(draw) <= window
        left = within & (draw < 0)
        right = within & (draw >= 0)
        for field in fields:
            values = np.asarray(data[field], dtype=np.float64)
            left_values = values[left & np.isfinite(values)]
            right_values = values[right & np.isfinite(values)]
            if left_values.size == 0 or right_values.size == 0:
                continue
            pooled = values[within & np.isfinite(values)]
            scale = float(np.std(pooled))
            difference = float(np.mean(right_values) - np.mean(left_values))
            balance.append(
                {
                    "window": window,
                    "field": field,
                    "left_rows_finite": int(left_values.size),
                    "right_rows_finite": int(right_values.size),
                    "left_mean": float(np.mean(left_values)),
                    "right_mean": float(np.mean(right_values)),
                    "right_minus_left": difference,
                    "standardized_difference_pooled_sd": (
                        difference / scale if scale > 0 else None
                    ),
                }
            )
    return finite(support), finite(balance)


def reference_density_bins(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Outcome-blind predetermined density table around the zero reference."""
    _, np, _, _ = common.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    internal = np.asarray(DENSITY_BOUNDS[1:-1], dtype=np.float64)
    codes = np.digitize(draw, internal, right=False)
    rows: list[dict[str, Any]] = []
    for level in range(len(DENSITY_BOUNDS) - 1):
        mask = codes == level
        count = int(np.count_nonzero(mask))
        values = draw[mask]
        rows.append(
            finite(
                {
                    "density_bin": level,
                    "lower_bound": DENSITY_BOUNDS[level],
                    "upper_bound": DENSITY_BOUNDS[level + 1],
                    "rows": count,
                    "row_share": count / draw.size,
                    "choosers": (
                        int(np.unique(data["chooser_index"][mask]).size) if count else 0
                    ),
                    "draw_payoff_mean": float(np.mean(values)) if count else None,
                    "draw_payoff_minimum": float(np.min(values)) if count else None,
                    "draw_payoff_maximum": float(np.max(values)) if count else None,
                    "outcome_blind": True,
                }
            )
        )
    return rows


def loss_local_elasticity_table(
    *, data: Mapping[str, Any], side_data: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    _, np, _, _ = common.import_dependencies()
    level_model_name = "X_loss_level_slope_chooser_fe_premium20_fe"
    log_model_name = PRIMARY_LOSS_MODEL
    level_model = find_result(results, level_model_name, required=False)
    log_model = find_result(results, log_model_name, required=False)
    rows: list[dict[str, Any]] = []
    if log_model is not None:
        elasticity = log_model["elasticity"]
        rows.append(
            {
                "source_model": log_model_name,
                "estimand": "loss_side_log_elasticity_mean_scaled_LPM",
                "evaluation_probability": None,
                "loss_magnitude": None,
                "estimate": elasticity["estimate"],
                "standard_error": elasticity["standard_error_delta_quantity_fixed"],
                "ci95_low": elasticity["ci95_low"],
                "ci95_high": elasticity["ci95_high"],
                "quantity_denominator": log_model["outcome_mean"],
                "causal": False,
            }
        )
    if level_model is None:
        return rows or [{"status": "LOSS_LEVEL_MODEL_FAILED_RETAINED"}]
    term = term_map(level_model)["reference_loss_magnitude"]
    beta = float(term["coefficient_probability_units"])
    se = float(term["standard_error_probability_units"])
    quantity = float(level_model["outcome_mean"])
    loss_values = side_data["loss_magnitude"][side_data["loss"]]
    probabilities = (0.1, 0.25, 0.5, 0.75, 0.9)
    critical = 1.959963984540054
    for probability, magnitude in zip(
        probabilities, np.quantile(loss_values, probabilities), strict=True
    ):
        estimate = beta * float(magnitude) / quantity
        standard_error = se * float(magnitude) / quantity
        rows.append(
            {
                "source_model": level_model_name,
                "estimand": "mean_scaled_local_loss_elasticity_from_level_slope",
                "evaluation_probability": probability,
                "loss_magnitude": float(magnitude),
                "estimate": estimate,
                "standard_error": standard_error,
                "ci95_low": estimate - critical * standard_error,
                "ci95_high": estimate + critical * standard_error,
                "quantity_denominator": quantity,
                "causal": False,
                "definition": "beta_loss * loss_magnitude / loss-side sample mean kindness",
            }
        )
    return finite(rows)


def run_prior_v102_summary(root: Path) -> dict[str, Any]:
    path = root / "payload/prior_evidence/v102_primary_interpretation.json"
    if not path.is_file():
        raise RuntimeError("Packaged v1.0.2 primary interpretation is missing")
    payload = common.load_json(path)
    if (
        payload.get("primary_model")
        != "X_primary_lpm_log_price_chooser_fe_draw50_fe_adjusted"
        or abs(float(payload.get("elasticity_estimate")) - 0.1570280092407992) > 1e-15
    ):
        raise RuntimeError("Packaged v1.0.2 primary result changed")
    return {
        **payload,
        "status_in_v103": "RETAINED_IMMUTABLE_SECONDARY_OPPORTUNITY_COST_RESULT",
        "not_the_reference_dependent_headline": True,
    }


def not_defined_or_not_identified() -> list[dict[str, Any]]:
    return [
        {
            "analysis": "Single global log elasticity with respect to signed draw payoff",
            "status": "NOT_MATHEMATICALLY_DEFINED",
            "reason": "Draw payoff has negative, zero, and positive support; log(draw payoff) is not a real-valued regressor on the full support.",
            "replacement_reported": "signed schedule, zero contrasts, and separate loss/gain sides",
            "saved_for_later": False,
        },
        {
            "analysis": "Elasticity exactly at the pre-game-rating reference",
            "status": "NOT_MATHEMATICALLY_DEFINED",
            "reason": "The price magnitude is zero at the reference, so a proportional price change and log derivative are undefined.",
            "replacement_reported": "matched-window differences and local slopes",
            "saved_for_later": False,
        },
        {
            "analysis": "Structural reference-dependent utility-cost elasticity",
            "status": "NOT_IDENTIFIED_WITHOUT_A_VALUE_FUNCTION",
            "reason": "A structural subjective cost would require specifying and identifying v(win payoff)-v(draw payoff), including reference curvature and loss aversion. The paper estimates reduced-form behavior and does not impose that primitive.",
            "replacement_reported": "reduced-form reference-dependent demand schedule",
            "saved_for_later": False,
        },
        {
            "analysis": "Causal reference-price elasticity",
            "status": "NOT_IDENTIFIED",
            "reason": "Draw payoff and relative rating are the same ordering variable under the Glicko update and are not randomly assigned. Estimates are within-chooser conditional associations, not causal price effects.",
            "replacement_reported": "chooser-FE descriptive schedule plus placebos and balance diagnostics",
            "saved_for_later": False,
        },
        {
            "analysis": "Dollar-price elasticity",
            "status": "NOT_DEFINED",
            "reason": "The reference margin is denominated in rating points and has no supported cardinal dollar conversion.",
            "replacement_reported": "rating-point slopes and elasticities",
            "saved_for_later": False,
        },
        {
            "analysis": "November 18 2025 color-advantage rule-change event study in this authority",
            "status": "NOT_ESTIMABLE_IN_CURRENT_CERTIFIED_24M_AUTHORITY_PRIOR_BRANCH_EXISTS",
            "reason": "The certified Stage07 authority ends in October 2025. A separate post-change reference-location branch already exists and is not concealed or reserved here.",
            "replacement_reported": "none in this lineage",
            "saved_for_later": False,
        },
    ]


def flatten_models(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in results:
        elasticity = model.get("elasticity") or {}
        for term in model.get("terms", []):
            is_elasticity = term.get("term") == elasticity.get("term")
            rows.append(
                finite(
                    {
                        "model": model.get("model"),
                        "epistemic_label": model.get("epistemic_label"),
                        "analysis_role": model.get("analysis_role"),
                        "status": model.get("status"),
                        "reference_side": model.get("reference_side"),
                        "term": term.get("term"),
                        "coefficient_probability_units": term.get(
                            "coefficient_probability_units", term.get("coefficient")
                        ),
                        "coefficient_percentage_points": term.get(
                            "coefficient_percentage_points"
                        ),
                        "standard_error_probability_units": term.get(
                            "standard_error_probability_units",
                            term.get("standard_error_clustered"),
                        ),
                        "standard_error_percentage_points": term.get(
                            "standard_error_percentage_points"
                        ),
                        "t_cluster": term.get("t_cluster"),
                        "p_value_two_sided": term.get("p_value_two_sided"),
                        "rows_raw": model.get(
                            "rows_raw", model.get("rows_informative_positive_total")
                        ),
                        "rows_identifying": model.get("rows_identifying"),
                        "chooser_clusters": model.get(
                            "chooser_clusters",
                            model.get("chooser_groups_informative_positive_total"),
                        ),
                        "outcome_mean": model.get("outcome_mean"),
                        "elasticity_or_response_estimate": (
                            elasticity.get("estimate") if is_elasticity else None
                        ),
                        "elasticity_or_response_se": (
                            elasticity.get(
                                "standard_error_delta_quantity_fixed",
                                elasticity.get("standard_error"),
                            )
                            if is_elasticity
                            else None
                        ),
                        "elasticity_or_response_ci95_low": (
                            elasticity.get("ci95_low") if is_elasticity else None
                        ),
                        "elasticity_or_response_ci95_high": (
                            elasticity.get("ci95_high") if is_elasticity else None
                        ),
                        "causal_claim": model.get("causal_claim", False),
                    }
                )
            )
    return rows


def interpretation(
    *, results: Sequence[Mapping[str, Any]], matched: Sequence[Mapping[str, Any]],
    validation: Mapping[str, Any], prior_v102: Mapping[str, Any],
) -> dict[str, Any]:
    primary_loss = find_result(results, PRIMARY_LOSS_MODEL)
    primary_reference = find_result(results, PRIMARY_REFERENCE_MODEL)
    assert primary_loss is not None and primary_reference is not None
    matched_row = next(
        row for row in matched if row.get("model") == PRIMARY_MATCHED_MODEL
    )
    loss_elasticity = primary_loss["elasticity"]
    reference_terms = term_map(primary_reference)
    return finite(
        {
            "headline_object": "reference-dependent demand schedule, not one global elasticity",
            "operative_price_margin": "signed chooser_draw_payoff_v2 relative to pre-game rating",
            "true_opportunity_cost_control": "chooser_win_premium_v2",
            "global_signed_log_elasticity": None,
            "global_signed_log_elasticity_status": "NOT_MATHEMATICALLY_DEFINED",
            "primary_loss_side_scalar_companion": {
                "model": PRIMARY_LOSS_MODEL,
                "estimate": loss_elasticity["estimate"],
                "ci95_low": loss_elasticity["ci95_low"],
                "ci95_high": loss_elasticity["ci95_high"],
                "definition": "mean-scaled LPM elasticity of kindness with respect to strictly positive reference-loss magnitude",
                "causal": False,
            },
            "primary_zero_reference_companion": matched_row,
            "primary_full_schedule_companion": {
                "model": PRIMARY_REFERENCE_MODEL,
                "positive_side_slope_pp_per_rating_point": reference_terms[
                    "positive_draw_payoff"
                ]["coefficient_percentage_points"],
                "loss_magnitude_slope_pp_per_rating_point": reference_terms[
                    "negative_draw_payoff"
                ]["coefficient_percentage_points"],
                "nonnegative_indicator_pp": reference_terms["draw_nonnegative"][
                    "coefficient_percentage_points"
                ],
                "indicator_warning": "full-range functional-form component; not a clean discontinuity",
            },
            "validation": validation,
            "prior_v102_opportunity_cost_elasticity": prior_v102,
            "claim_boundary": (
                "All v1.0.3 estimates are exploratory within-chooser conditional "
                "associations. The design identifies a reduced-form reference-dependent "
                "schedule, not a causal or structural price elasticity."
            ),
        }
    )


def report_hashes(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "report_file_hashes.tsv":
            continue
        rows.append(
            {
                "file": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": common.sha256_file(path),
            }
        )
    return rows


def write_report_manifest(root: Path) -> None:
    rows = report_hashes(root)
    lines = ["file\tbytes\tsha256"] + [
        f"{row['file']}\t{row['bytes']}\t{row['sha256']}" for row in rows
    ]
    common.atomic_text(root / "report_file_hashes.tsv", "\n".join(lines) + "\n")


def execute(args: argparse.Namespace) -> Path:
    started = time.time()
    root = package_root()
    package_rows = common.package_manifest(root)
    project = args.project_root.expanduser().resolve()
    if project != PROJECT_AUTHORITY:
        raise RuntimeError(f"Project authority path changed: {project}")
    if args.threads < 1 or args.threads > 16:
        raise RuntimeError("Threads must be between 1 and 16")
    state = (
        args.state_root.expanduser().resolve()
        if args.state_root
        else project / "derived/private" / STATE_NAME
    )
    state.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(state).free < MINIMUM_FREE_BYTES:
        raise RuntimeError("Fewer than 20 GiB free on the private-checkpoint volume")
    run_id = args.run_id or common.utc_run_id()
    output_parent = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project / "output" / OUTPUT_NAME
    )
    output = output_parent / run_id
    if output.exists():
        raise RuntimeError(f"Output run already exists: {output}")
    output.mkdir(parents=True)
    if args.execution_pointer:
        common.atomic_json(
            args.execution_pointer,
            {
                "status": "KINDNESS_REFERENCE_DEMAND_EXECUTION_POINTER",
                "created_utc": common.utc_now(),
                "run_id": run_id,
                "output_root": str(output),
                "state_root": str(state),
                "package_root": str(root),
            },
        )

    try:
        print("KINDNESS_REFERENCE_DEMAND_AUTHENTICATION_BEGIN", flush=True)
        stage_root = project / common.STAGE07_RELATIVE
        stage_auth = common.authenticate_stage07(stage_root)
        stage_paths = common.stage07_paths(stage_root)
        plan_path = root / "payload/docs/kindness_reference_demand_exploratory_plan_v1_0_3_2026-08-25.md"
        amendment_path = root / "payload/docs/kindness_reference_demand_v1_0_3_postoutcome_correction.md"
        config = {
            "script_version": SCRIPT_VERSION,
            "script_sha256": common.sha256_file(Path(__file__)),
            "common_sha256": common.sha256_file(Path(common.__file__)),
            "legacy_cache_builder_sha256": common.sha256_file(Path(legacy.__file__)),
            "plan_sha256": common.sha256_file(plan_path),
            "amendment_sha256": common.sha256_file(amendment_path),
            "stage07_success_sha256": common.EXPECTED_STAGE07_SUCCESS_SHA256,
            "package_manifest_sha256": common.sha256_json(package_rows),
            "threads": args.threads,
            "memory_limit": args.memory_limit,
            "headline_object": "reference-dependent signed demand schedule",
            "primary_loss_model": PRIMARY_LOSS_MODEL,
            "primary_reference_model": PRIMARY_REFERENCE_MODEL,
            "primary_matched_model": PRIMARY_MATCHED_MODEL,
            "all_new_models_epistemic_label": "X",
        }
        config_sha256 = common.sha256_json(config)
        state_config = state / "configuration.json"
        if state_config.is_file():
            saved = common.load_json(state_config)
            if saved.get("config_sha256") != config_sha256:
                raise RuntimeError("Private state belongs to a different v1.0.3 configuration")
        else:
            common.atomic_json(
                state_config,
                {
                    "status": "KINDNESS_REFERENCE_DEMAND_PRIVATE_STATE_CREATED",
                    "created_utc": common.utc_now(),
                    "config_sha256": config_sha256,
                    "config": config,
                    "privacy": "PRIVATE; DO NOT PUBLISH ROW-LEVEL CHECKPOINTS",
                },
            )
        prior_v102 = run_prior_v102_summary(root)
        common.atomic_json(
            output / "input_authorities.json",
            {
                "config": config,
                "config_sha256": config_sha256,
                "stage07": stage_auth,
                "prior_v102": prior_v102,
            },
        )
        print("KINDNESS_REFERENCE_DEMAND_AUTHENTICATION_OK", flush=True)

        cache, base_receipt, cache_receipt = obtain_model_cache(
            project=project,
            stage_paths=stage_paths,
            state=state,
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
        )
        common.atomic_json(
            output / "private_cache_authentication.json",
            finite({"base": base_receipt, "model_cache": cache_receipt}),
        )
        data = legacy.load_arrays(cache)
        _, np, _, _ = common.import_dependencies()
        if (
            data["kind"].size != common.EXPECTED_FAIR_ROWS
            or int(data["kind"].sum()) != common.EXPECTED_FAIR_KIND_DRAWS
            or int(np.unique(data["chooser_index"]).size) != common.EXPECTED_FAIR_CHOOSERS
        ):
            raise RuntimeError("Loaded reference-demand arrays lost certified support")

        support, balance = support_and_balance(data)
        density = reference_density_bins(data)
        common.atomic_json(output / "reference_price_support.json", support)
        common.write_csv(output / "reference_balance_by_window.csv", balance)
        common.write_csv(output / "reference_density_bins.csv", density)
        side_data = side_masks_and_transforms(data)

        attempts: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        validation = run_validation(
            data=data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        run_piecewise_family(
            data=data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        matched, donuts = run_matched_windows(
            data=data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        placebos = run_local_shape_and_placebos(
            data=data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        run_side_elasticities(
            data=data,
            side_data=side_data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        schedule, arcs, adjacent_zero = run_nonparametric_schedule(
            data=data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        heterogeneity = run_heterogeneity(
            data=data,
            side_data=side_data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        run_side_ppml(
            data=data,
            side_data=side_data,
            state=state,
            config_sha256=config_sha256,
            attempts=attempts,
            results=results,
        )
        local_elasticities = loss_local_elasticity_table(
            data=data, side_data=side_data, results=results
        )
        primary_interpretation = interpretation(
            results=results,
            matched=matched,
            validation=validation,
            prior_v102=prior_v102,
        )

        common.atomic_json(output / "stage08_replication_audit.json", validation)
        common.atomic_json(output / "model_attempts.json", finite(attempts))
        common.write_csv(output / "model_attempts.csv", [finite(row) for row in attempts])
        common.atomic_json(output / "reference_model_results.json", finite(results))
        common.write_csv(output / "reference_model_results.csv", flatten_models(results))
        common.write_csv(output / "matched_window_contrasts.csv", matched)
        common.write_csv(output / "donut_grid.csv", donuts)
        common.write_csv(output / "placebo_cutoffs.csv", placebos)
        common.write_csv(output / "reference_schedule_bins.csv", schedule)
        common.write_csv(output / "reference_schedule_arcs.csv", arcs)
        common.atomic_json(output / "adjacent_zero_bins.json", adjacent_zero)
        common.write_csv(output / "loss_side_local_elasticities.csv", local_elasticities)
        common.write_csv(output / "heterogeneity_support.csv", heterogeneity)
        common.atomic_json(
            output / "not_defined_or_not_identified.json",
            not_defined_or_not_identified(),
        )
        common.atomic_json(
            output / "primary_interpretation.json", primary_interpretation
        )

        success = {
            "status": "KINDNESS_REFERENCE_DEMAND_V103_OK",
            "created_utc": common.utc_now(),
            "runtime_seconds": time.time() - started,
            "config_sha256": config_sha256,
            "rows": common.EXPECTED_FAIR_ROWS,
            "kind_draws": common.EXPECTED_FAIR_KIND_DRAWS,
            "choosers": common.EXPECTED_FAIR_CHOOSERS,
            "models_attempted": len(attempts),
            "models_estimated": sum(row["status"] == "ESTIMATED" for row in attempts),
            "models_failed_retained": sum(row["status"] != "ESTIMATED" for row in attempts),
            "headline": primary_interpretation,
            "epistemic_label": "X",
            "causal_claim": False,
            "global_signed_log_elasticity_defined": False,
            "holm_family": "not included; exploratory post-outcome corrective module",
            "prior_v102_lineage_mutated": False,
            "private_state_root": str(state),
            "public_output_root": str(output),
        }
        common.atomic_json(output / "_SUCCESS.json", finite(success))
        write_report_manifest(output)
        loss = primary_interpretation["primary_loss_side_scalar_companion"]
        zero = primary_interpretation["primary_zero_reference_companion"]
        print(f"KINDNESS_REFERENCE_DEMAND_V103_OK: {output}", flush=True)
        print(
            "REFERENCE_LOSS_LOG_ELASTICITY "
            f"estimate={loss['estimate']:.9g} "
            f"ci95=[{loss['ci95_low']:.9g},{loss['ci95_high']:.9g}]",
            flush=True,
        )
        print(
            "REFERENCE_ZERO_W0P5_CONTRAST "
            f"pp={zero['coefficient_percentage_points']:.9g} "
            f"ci95_pp=[{zero['ci95_low_pp']:.9g},{zero['ci95_high_pp']:.9g}]",
            flush=True,
        )
        print("GLOBAL_SIGNED_LOG_ELASTICITY_NOT_DEFINED", flush=True)
        return output
    except BaseException as error:
        diagnostic = {
            "status": "KINDNESS_REFERENCE_DEMAND_V103_FAILED_CLOSED",
            "created_utc": common.utc_now(),
            "runtime_seconds": time.time() - started,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
            "favorable_null_and_adverse_outputs_retained": True,
            "private_checkpoints_resumable": True,
            "prior_v102_lineage_mutated": False,
        }
        common.atomic_json(output / "FAILURE_DIAGNOSTIC.json", diagnostic)
        write_report_manifest(output)
        raise


def run_self_test() -> None:
    _, np, _, _ = common.import_dependencies()
    common.run_self_test()
    if (
        PRIMARY_LOSS_MODEL
        != "X_primary_loss_log_elasticity_chooser_fe_premium20_fe"
        or PRIMARY_REFERENCE_MODEL
        != "X_primary_reference_piecewise_chooser_fe_premium20_fe"
        or PRIMARY_MATCHED_MODEL
        != "X_primary_zero_crossing_w0p5_chooser_fe_premium20_fe"
    ):
        raise RuntimeError("v1.0.3 primary labels changed")
    if common.EXPECTED_FAIR_ROWS != 17_328_130:
        raise RuntimeError("Certified fair support changed")
    probe = np.asarray([-7.0, -5.0, -3.0, -1.5, -0.75, -0.3, -0.15, -0.01, 0.0, 0.15, 0.3, 0.75, 1.5, 3.0, 5.0, 7.0])
    expected = np.arange(len(SIGNED_LABELS), dtype=np.int64)
    if not np.array_equal(signed_band_codes(probe), expected):
        raise RuntimeError("Signed reference-band boundary self-test failed")
    inventory = not_defined_or_not_identified()
    if len(inventory) != 6 or any(row.get("saved_for_later") for row in inventory):
        raise RuntimeError("Disclosure inventory changed")
    if not math.isnan(float(finite(math.nan) or math.nan)):
        raise RuntimeError("Finite serializer self-test changed")
    print("KINDNESS_REFERENCE_DEMAND_MAIN_SELF_TEST_OK", flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        return
    if not args.execute:
        print("Dry run only. Pass --execute to authenticate data and estimate.")
        return
    execute(args)


if __name__ == "__main__":
    main()
