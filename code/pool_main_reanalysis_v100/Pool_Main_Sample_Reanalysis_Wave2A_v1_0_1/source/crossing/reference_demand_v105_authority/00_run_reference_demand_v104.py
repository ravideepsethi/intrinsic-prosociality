#!/usr/bin/env python3
"""Run the prospectively frozen reference-demand closure audit v1.0.4."""

from __future__ import annotations

import argparse
import gc
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import kindness_price_elasticity_common_v102 as numerical
import reference_demand_v104_common as audit
import run_kindness_price_elasticity_v102 as legacy
import run_kindness_reference_demand_v103 as prior


PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
TOLERANCE = 5e-10


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--cache-path", type=Path)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def model_term(result: Mapping[str, Any], term: str) -> dict[str, Any]:
    for row in result.get("terms", []):
        if row.get("term") == term:
            return dict(row)
    raise RuntimeError(f"Model {result.get('model')} lacks term {term}")


def t_value(row: Mapping[str, Any]) -> float:
    return float(row["coefficient_probability_units"]) / float(row["standard_error_probability_units"])


def base_spec(model: str, role: str, sample: str) -> dict[str, Any]:
    return {
        "model": model,
        "epistemic_label": "V" if role == "validation" else "X",
        "analysis_role": role,
        "sample": sample,
        "outcome": "indicator for kind draw",
        "cluster": "chooser account (lossless private integer mapping)",
        "causal_claim": False,
        "structural_loss_aversion_claim": False,
        "multiple_testing_family": "outside Campaign 1 confirmatory Holm family",
    }


def current_controls(
    data: Mapping[str, Any], indices: Any, *, month_trends: bool
) -> dict[str, Any]:
    controls: dict[str, Any] = {}
    engine, _ = legacy.standardized(data["engine_eval_cp"][indices])
    controls["z_engine_eval_cp"] = engine
    controls["z_engine_eval_cp_sq"] = engine * engine
    for source, label in (
        ("log_chooser_clock", "chooser_clock"),
        ("log_opponent_clock", "opponent_clock"),
    ):
        standardized, missing = legacy.standardized(data[source][indices])
        controls[f"z_{label}"] = standardized
        if missing is not None:
            controls[f"{label}_missing"] = missing
    controls["tournament"] = data["tournament"][indices].astype(float)
    legacy.add_dummies(controls, data["speed_code"][indices], "speed")
    if month_trends:
        month, _ = legacy.standardized(data["month_code"][indices])
        controls["z_month"] = month
        controls["z_month_sq"] = month * month
    return controls


def checkpointed(
    *, private_root: Path, config_sha256: str, model: str,
    fit: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = private_root / "model_checkpoints" / f"{model}.json"
    if path.is_file():
        saved = audit.load_json(path)
        if saved.get("config_sha256") != config_sha256 or saved.get("model") != model:
            raise RuntimeError(f"Checkpoint configuration changed: {model}")
        if saved.get("status") != "REFERENCE_DEMAND_V104_MODEL_CHECKPOINT_OK":
            raise RuntimeError(f"Checkpoint status changed: {model}")
        print(f"V104_MODEL_CHECKPOINT_AUTHENTICATED model={model}", flush=True)
        return dict(saved["result"]), dict(saved["attempt"])
    print(f"V104_MODEL_BEGIN model={model}", flush=True)
    started = time.time()
    result = audit.json_ready(fit())
    attempt = {
        "model": model,
        "status": "ESTIMATED",
        "runtime_seconds": time.time() - started,
        "error": None,
    }
    audit.atomic_json(path, {
        "status": "REFERENCE_DEMAND_V104_MODEL_CHECKPOINT_OK",
        "created_utc": audit.utc_now(),
        "config_sha256": config_sha256,
        "model": model,
        "attempt": attempt,
        "result": result,
    })
    print(f"V104_MODEL_OK model={model}", flush=True)
    gc.collect()
    return dict(result), attempt


def fit_lpm(
    *, data: Mapping[str, Any], mask: Any, model: str, role: str,
    regressors_builder: Callable[[Any], dict[str, Any]],
    fixed_effects_builder: Callable[[Any], list[Any]],
    exposure_names: Sequence[str],
) -> dict[str, Any]:
    _, np, _, _ = numerical.import_dependencies()
    indices = np.flatnonzero(mask)
    if indices.size < 1_000:
        raise RuntimeError(f"{model}: fewer than 1,000 rows")
    regressors = regressors_builder(indices)
    result = numerical.fit_lpm_cluster(
        outcome=data["kind"][indices],
        regressors=regressors,
        clusters=data["chooser_index"][indices],
        fixed_effects=fixed_effects_builder(indices),
        exposure_names=tuple(exposure_names),
        row_ids=data["row_hash"][indices],
        specification=base_spec(model, role, f"rows_selected={indices.size}"),
    )
    result["price_mean"] = float(np.mean(data["price"][indices]))
    return audit.json_ready(result)


def support_and_algebra(
    data: Mapping[str, Any], contract: Mapping[str, Any], *, synthetic: bool
) -> tuple[dict[str, Any], Any, Any, Any, Any, Any]:
    _, np, _, _ = numerical.import_dependencies()
    rows = int(data["kind"].size)
    kinds = int(np.sum(data["kind"]))
    choosers = int(np.unique(data["chooser_index"]).size)
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    price = np.asarray(data["price"], dtype=np.float64)
    chooser_rating = np.asarray(data["chooser_elo"], dtype=np.float64)
    opponent_rating = np.asarray(data["opponent_elo"], dtype=np.float64)
    if not np.all(np.isfinite(draw)) or not np.all(np.isfinite(price)) or np.any(price <= 0):
        raise RuntimeError("Payoff or premium support is invalid")
    if not np.all(np.isfinite(chooser_rating)) or not np.all(np.isfinite(opponent_rating)):
        raise RuntimeError("Displayed ratings contain missing or nonfinite values")
    if not np.all(chooser_rating == np.rint(chooser_rating)) or not np.all(opponent_rating == np.rint(opponent_rating)):
        raise RuntimeError("Displayed ratings are not exact integers")
    gap = np.rint(opponent_rating - chooser_rating).astype(np.int64)
    exact = draw == 0.0
    tolerant = np.abs(draw) <= float(contract["exact_zero_tolerance"])
    if not np.array_equal(exact, tolerant):
        raise RuntimeError("Literal and tolerance-based exact-zero definitions differ")
    sign_alignment = ((gap > 0) == (draw > 0)) & ((gap < 0) == (draw < 0)) & ((gap == 0) == exact)
    if not np.all(sign_alignment):
        raise RuntimeError(f"Displayed rating-gap sign fails payoff-sign alignment in {int(np.count_nonzero(~sign_alignment))} rows")
    scale = 2.0 * price
    nonzero = ~exact
    magnitude = np.abs(draw[nonzero]) / scale[nonzero]
    if np.any(magnitude <= 0) or np.any(magnitude >= 0.5) or not np.all(np.isfinite(magnitude)):
        raise RuntimeError("Expected-score distance is outside (0,0.5) on nonzero rows")
    log_scale = np.log(scale)
    log_magnitude = np.full(rows, np.nan, dtype=np.float64)
    log_magnitude[nonzero] = np.log(magnitude)
    identity_error = float(np.max(np.abs(np.log(np.abs(draw[nonzero])) - log_scale[nonzero] - log_magnitude[nonzero])))
    if identity_error > 5e-12:
        raise RuntimeError(f"Log decomposition identity failed: {identity_error}")
    if not synthetic:
        frozen = contract["private_cache"]
        observed = {
            "rows": rows,
            "kind_draws": kinds,
            "choosers": choosers,
            "exact_zero_rows": int(np.count_nonzero(exact)),
        }
        expected = {key: int(frozen[key]) for key in observed}
        if observed != expected:
            raise RuntimeError(f"Frozen cache support changed: expected={expected}; observed={observed}")
    support = {
        "status": "REFERENCE_DEMAND_V104_ALGEBRA_AND_SUPPORT_OK",
        "rows": rows,
        "kind_draws": kinds,
        "choosers": choosers,
        "exact_zero_rows": int(np.count_nonzero(exact)),
        "strict_negative_rows": int(np.count_nonzero(draw < 0)),
        "strict_positive_rows": int(np.count_nonzero(draw > 0)),
        "literal_equals_tolerance_zero": True,
        "displayed_rating_integer_rows": rows,
        "payoff_sign_matches_displayed_gap_rows": rows,
        "log_identity_maximum_absolute_error": identity_error,
        "log_zero_policy": "exact-zero rows excluded; no floor or offset",
    }
    return support, gap, exact, nonzero, log_scale, log_magnitude


def raw_rate_rows(data: Mapping[str, Any], gap: Any, exact: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    y = np.asarray(data["kind"], dtype=np.float64)
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    boundary: list[dict[str, Any]] = []
    definitions = (
        ("costly_m0p1_to_0", (draw >= -0.1) & (draw < 0)),
        ("exact_zero", exact),
        ("favorable_0_to_0p1", (draw > 0) & (draw <= 0.1)),
    )
    for label, mask in definitions:
        n = int(np.count_nonzero(mask))
        kinds = int(np.sum(y[mask]))
        p = kinds / n if n else math.nan
        boundary.append({"boundary_bin": label, "rows": n, "kind_draws": kinds, "chooser_accounts": int(np.unique(data["chooser_index"][mask]).size), "kind_rate_pct": 100.0 * p, "binomial_se_pp": 100.0 * math.sqrt(p * (1.0 - p) / n) if n else None})
    schedule: list[dict[str, Any]] = []
    categories: list[tuple[str, Any]] = [("gap_lt_m30", gap < -30)]
    categories.extend((str(value), gap == value) for value in range(-30, 31))
    categories.append(("gap_gt_30", gap > 30))
    for label, mask in categories:
        n = int(np.count_nonzero(mask))
        kinds = int(np.sum(y[mask]))
        p = kinds / n if n else math.nan
        schedule.append({"displayed_gap": label, "rows": n, "kind_draws": kinds, "chooser_accounts": int(np.unique(data["chooser_index"][mask]).size), "kind_rate_pct": 100.0 * p if n else None, "binomial_se_pp": 100.0 * math.sqrt(p * (1.0 - p) / n) if n else None})
    return boundary, schedule


def run_replication_gates(
    *, data: Mapping[str, Any], private_root: Path, config_sha256: str,
    contract: Mapping[str, Any], synthetic: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    all_rows = np.ones(data["kind"].size, dtype=bool)
    definitions: list[tuple[str, Callable[[], dict[str, Any]]]] = []
    definitions.append(("V_stage08_piecewise_level_premium", lambda: prior.fit_reference_piecewise(data=data, mask=all_rows, model="V_stage08_piecewise_level_premium", role="validation", premium_mode="level")))
    definitions.append(("V_v103_piecewise_premium20_fe", lambda: prior.fit_reference_piecewise(data=data, mask=all_rows, model="V_v103_piecewise_premium20_fe", role="validation", premium_mode="bin20_fe")))
    definitions.append(("V_v103_zero_w0p5_premium20_fe", lambda: prior.fit_zero_contrast(data=data, mask=np.abs(data["draw_payoff"]) <= 0.5, model="V_v103_zero_w0p5_premium20_fe", role="validation", premium_mode="bin20_fe")))
    definitions.append(("V_v103_loss_log_premium20_fe", lambda: prior.fit_side_model(data=data, mask=data["draw_payoff"] < 0, model="V_v103_loss_log_premium20_fe", side="loss", transform="log", premium_mode="bin20_fe")))
    for model, fit in definitions:
        result, attempt = checkpointed(private_root=private_root, config_sha256=config_sha256, model=model, fit=fit)
        results.append(result)
        attempts.append(attempt)
    observed = {
        "stage08_positive_draw_payoff_pp": model_term(results[0], "positive_draw_payoff")["coefficient_percentage_points"],
        "stage08_negative_draw_payoff_pp": model_term(results[0], "negative_draw_payoff")["coefficient_percentage_points"],
        "stage08_draw_nonnegative_pp": model_term(results[0], "draw_nonnegative")["coefficient_percentage_points"],
        "v103_piecewise_positive_draw_payoff_pp": model_term(results[1], "positive_draw_payoff")["coefficient_percentage_points"],
        "v103_piecewise_negative_draw_payoff_pp": model_term(results[1], "negative_draw_payoff")["coefficient_percentage_points"],
        "v103_piecewise_draw_nonnegative_pp": model_term(results[1], "draw_nonnegative")["coefficient_percentage_points"],
        "v103_zero_w0p5_pp": model_term(results[2], "above_cutoff")["coefficient_percentage_points"],
        "v103_loss_log_coefficient_pp": model_term(results[3], "log_reference_loss_magnitude")["coefficient_percentage_points"],
        "v103_loss_log_mean_scaled_elasticity": results[3]["elasticity"]["estimate"],
    }
    expected = {
        "stage08_positive_draw_payoff_pp": contract["stage08_expected"]["positive_draw_payoff_pp"],
        "stage08_negative_draw_payoff_pp": contract["stage08_expected"]["negative_draw_payoff_pp"],
        "stage08_draw_nonnegative_pp": contract["stage08_expected"]["draw_nonnegative_pp"],
        "v103_piecewise_positive_draw_payoff_pp": contract["v103_expected"]["piecewise_positive_draw_payoff_pp"],
        "v103_piecewise_negative_draw_payoff_pp": contract["v103_expected"]["piecewise_negative_draw_payoff_pp"],
        "v103_piecewise_draw_nonnegative_pp": contract["v103_expected"]["piecewise_draw_nonnegative_pp"],
        "v103_zero_w0p5_pp": contract["v103_expected"]["zero_w0p5_pp"],
        "v103_loss_log_coefficient_pp": contract["v103_expected"]["loss_log_coefficient_pp"],
        "v103_loss_log_mean_scaled_elasticity": contract["v103_expected"]["loss_log_mean_scaled_elasticity"],
    }
    differences = {key: float(observed[key]) - float(expected[key]) for key in expected}
    if not synthetic and any(abs(value) > float(contract["replication_tolerance_pp"]) for value in differences.values()):
        raise RuntimeError(f"Replication gate failed: {differences}")
    receipt = {"status": "REFERENCE_DEMAND_V104_REPLICATION_GATES_OK", "synthetic": synthetic, "expected": expected if not synthetic else None, "observed": observed, "differences": differences if not synthetic else None, "tolerance": contract["replication_tolerance_pp"], "new_interpretation_blocked_until_gate": True}
    return receipt, results, attempts


def run_zero_family(
    *, data: Mapping[str, Any], exact: Any, private_root: Path,
    config_sha256: str, contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    table: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for window in contract["zero_windows"]:
        mask = np.abs(draw) <= float(window)
        name_a = f"X_zero_tristate_w{str(window).replace('.', 'p')}_negative_omitted"
        def fit_a(mask=mask, model=name_a):
            return fit_lpm(
                data=data, mask=mask, model=model, role="exact_zero_tristate",
                regressors_builder=lambda idx: {
                    "exact_zero_minus_negative": exact[idx].astype(float),
                    "positive_minus_negative": (draw[idx] > 0).astype(float),
                },
                fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["price_bin20"][idx]],
                exposure_names=("exact_zero_minus_negative", "positive_minus_negative"),
            )
        result_a, attempt_a = checkpointed(private_root=private_root, config_sha256=config_sha256, model=name_a, fit=fit_a)
        name_b = f"X_zero_tristate_w{str(window).replace('.', 'p')}_exact_omitted"
        def fit_b(mask=mask, model=name_b):
            return fit_lpm(
                data=data, mask=mask, model=model, role="exact_zero_tristate",
                regressors_builder=lambda idx: {
                    "negative_minus_exact": (draw[idx] < 0).astype(float),
                    "positive_minus_exact": (draw[idx] > 0).astype(float),
                },
                fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["price_bin20"][idx]],
                exposure_names=("negative_minus_exact", "positive_minus_exact"),
            )
        result_b, attempt_b = checkpointed(private_root=private_root, config_sha256=config_sha256, model=name_b, fit=fit_b)
        results.extend((result_a, result_b)); attempts.extend((attempt_a, attempt_b))
        exact_negative = model_term(result_a, "exact_zero_minus_negative")
        positive_negative = model_term(result_a, "positive_minus_negative")
        positive_exact = model_term(result_b, "positive_minus_exact")
        table.append({
            "window_abs_draw_payoff_le": window,
            "rows": result_a["rows_raw"],
            "negative_rows": int(np.count_nonzero(mask & (draw < 0))),
            "exact_zero_rows": int(np.count_nonzero(mask & exact)),
            "positive_rows": int(np.count_nonzero(mask & (draw > 0))),
            "exact_minus_negative_pp": exact_negative["coefficient_percentage_points"],
            "exact_minus_negative_se_pp": exact_negative["standard_error_percentage_points"],
            "exact_minus_negative_t": t_value(exact_negative),
            "positive_minus_negative_pp": positive_negative["coefficient_percentage_points"],
            "positive_minus_negative_se_pp": positive_negative["standard_error_percentage_points"],
            "positive_minus_negative_t": t_value(positive_negative),
            "positive_minus_exact_pp": positive_exact["coefficient_percentage_points"],
            "positive_minus_exact_se_pp": positive_exact["standard_error_percentage_points"],
            "positive_minus_exact_t": t_value(positive_exact),
            "fixed_effects": "chooser + premium20",
            "causal": False,
        })
    return table, results, attempts


def run_decomposition(
    *, data: Mapping[str, Any], gap: Any, nonzero: Any,
    log_scale: Any, log_magnitude: Any, private_root: Path,
    config_sha256: str, contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    log_abs_draw = np.full(draw.size, np.nan, dtype=np.float64)
    log_abs_draw[nonzero] = np.log(np.abs(draw[nonzero]))
    log_chooser_rd = np.log(np.asarray(data["chooser_rd"], dtype=np.float64))
    log_opponent_rd = np.log(np.asarray(data["opponent_rd"], dtype=np.float64))
    if not np.all(np.isfinite(log_chooser_rd)) or not np.all(np.isfinite(log_opponent_rd)):
        raise RuntimeError("Rating deviations are not strictly positive and finite")
    definitions: list[tuple[str, Any, Callable[[Any], dict[str, Any]], Callable[[Any], list[Any]], tuple[str, ...]]] = []
    definitions.append(("E1_sign_plus_log_abs_draw", nonzero, lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_abs_draw_payoff": log_abs_draw[idx], **current_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_abs_draw_payoff")))
    definitions.append(("E2_sign_logK_logM", nonzero, lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **current_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
    local = nonzero & (np.abs(gap) <= 30)
    definitions.append(("E3_logK_logM_within_exact_gap", local, lambda idx: {"log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **current_controls(data, idx, month_trends=True)}, lambda idx: [data["chooser_index"][idx], gap[idx]], ("log_K", "log_abs_half_minus_E")))
    definitions.append(("E4_own_opponent_RD_within_exact_gap", local, lambda idx: {"log_chooser_rd": log_chooser_rd[idx], "log_opponent_rd": log_opponent_rd[idx], "log_abs_half_minus_E": log_magnitude[idx], **current_controls(data, idx, month_trends=True)}, lambda idx: [data["chooser_index"][idx], gap[idx]], ("log_chooser_rd", "log_opponent_rd", "log_abs_half_minus_E")))
    cutoff = float(contract["rd_cutoff"])
    definitions.append(("E5a_chooser_rd_le_110", nonzero & (data["chooser_rd"] <= cutoff), lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **current_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
    definitions.append(("E5b_opponent_rd_le_110", nonzero & (data["opponent_rd"] <= cutoff), lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **current_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
    definitions.append(("E5c_both_rd_le_110", nonzero & (data["chooser_rd"] <= cutoff) & (data["opponent_rd"] <= cutoff), lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **current_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for model, mask, regressors, fixed_effects, exposures in definitions:
        fit = lambda mask=mask, model=model, regressors=regressors, fixed_effects=fixed_effects, exposures=exposures: fit_lpm(data=data, mask=mask, model=model, role="E1_E5_sign_magnitude_decomposition", regressors_builder=regressors, fixed_effects_builder=fixed_effects, exposure_names=exposures)
        result, attempt = checkpointed(private_root=private_root, config_sha256=config_sha256, model=model, fit=fit)
        results.append(result); attempts.append(attempt)
    return results, attempts


def run_gap_schedule(
    *, data: Mapping[str, Any], gap: Any, log_scale: Any,
    private_root: Path, config_sha256: str, contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    reference = int(contract["displayed_gap_reference"])
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    reference_mask = gap == reference
    reference_rows = int(np.count_nonzero(reference_mask))
    reference_choosers = np.unique(data["chooser_index"][reference_mask])
    for variant, include_log_scale in (("primary", False), ("plus_log_K_sensitivity", True)):
        rows.append({"displayed_gap": reference, "reference_gap": reference, "variant": variant, "coefficient_pp": 0.0, "se_pp": None, "t": None, "target_rows": reference_rows, "reference_rows": reference_rows, "rows": reference_rows, "chooser_clusters": int(reference_choosers.size), "identifying_choosers_with_both_gaps": None, "estimation": "omitted reference"})
        for target in range(int(contract["displayed_gap_min"]), int(contract["displayed_gap_max"]) + 1):
            if target == reference:
                continue
            mask = (gap == target) | (gap == reference)
            target_mask = gap == target
            target_rows = int(np.count_nonzero(target_mask))
            target_choosers = np.unique(data["chooser_index"][target_mask])
            identifying_choosers = int(np.intersect1d(target_choosers, reference_choosers, assume_unique=True).size)
            model = f"X_gap_{target:+d}_vs_{reference:+d}_{variant}".replace("+", "p").replace("-", "m")
            def fit(mask=mask, model=model, target=target, include_log_scale=include_log_scale):
                def build(idx: Any) -> dict[str, Any]:
                    regressors = {"target_gap_minus_reference": (gap[idx] == target).astype(float), **current_controls(data, idx, month_trends=False)}
                    if include_log_scale:
                        regressors["log_K"] = log_scale[idx]
                    return regressors
                return fit_lpm(data=data, mask=mask, model=model, role="displayed_integer_gap_pairwise_schedule", regressors_builder=build, fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], exposure_names=("target_gap_minus_reference",))
            result, attempt = checkpointed(private_root=private_root, config_sha256=config_sha256, model=model, fit=fit)
            results.append(result); attempts.append(attempt)
            term = model_term(result, "target_gap_minus_reference")
            rows.append({"displayed_gap": target, "reference_gap": reference, "variant": variant, "coefficient_pp": term["coefficient_percentage_points"], "se_pp": term["standard_error_percentage_points"], "t": t_value(term), "p_value_two_sided": term["p_value_two_sided"], "target_rows": target_rows, "reference_rows": reference_rows, "rows": result["rows_raw"], "chooser_clusters": result["chooser_clusters"], "identifying_choosers_with_both_gaps": identifying_choosers, "estimation": "separate two-gap comparison; chooser and month FE; chooser-clustered", "causal": False})
    return rows, results, attempts


def flatten_models(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in results:
        for term in model.get("terms", []):
            rows.append({
                "model": model.get("model"),
                "analysis_role": model.get("analysis_role"),
                "epistemic_label": model.get("epistemic_label"),
                "term": term.get("term"),
                "coefficient_pp": term.get("coefficient_percentage_points"),
                "se_pp": term.get("standard_error_percentage_points"),
                "t": term.get("t_cluster"),
                "p_value_two_sided": term.get("p_value_two_sided"),
                "rows": model.get("rows_raw"),
                "chooser_clusters": model.get("chooser_clusters"),
                "fixed_effect_count": model.get("fixed_effect_count"),
                "absorption_method": model.get("absorption_method"),
                "absorption_max_scaled_group_mean": model.get("absorption_max_scaled_group_mean"),
                "matrix_rank": model.get("matrix_rank"),
                "causal": False,
            })
    return rows


def component_self_test() -> None:
    import numpy as np  # type: ignore
    rng = np.random.default_rng(20260827)
    n = 12_000
    chooser = np.arange(n) % 300
    observation = np.arange(n) // 300
    gap = ((observation + 7 * chooser) % 61) - 30
    scale = 5.0 + ((3 * observation + chooser) % 17) / 4.0
    magnitude = 0.01 + np.abs(gap) / 100.0
    draw = np.sign(gap) * scale * magnitude
    exact = draw == 0
    if np.count_nonzero(exact) == 0 or not np.all((gap == 0) == exact):
        raise RuntimeError("Exact-zero component self-test failed")
    nonzero = ~exact
    error = np.max(np.abs(np.log(np.abs(draw[nonzero])) - np.log(scale[nonzero]) - np.log(magnitude[nonzero])))
    if error > 1e-12:
        raise RuntimeError("Log-identity component self-test failed")
    latent = 0.015 + 0.002 * (draw > 0) - 0.0004 * np.log(np.abs(draw) + 1e-8)
    y = rng.random(n) < np.clip(latent, 0.001, 0.2)
    if y.sum() < 100:
        raise RuntimeError("Synthetic outcome component support failed")
    print("KINDNESS_REFERENCE_DEMAND_V104_COMPONENT_SELFTEST_OK", flush=True)


def execute(args: argparse.Namespace) -> None:
    started = time.time()
    package_root = args.package_root.resolve()
    project = args.project_root.resolve()
    private_root = args.private_root.resolve()
    public_root = args.public_root.resolve()
    if args.threads != 8 or args.memory_limit != "16GB":
        raise RuntimeError("v1.0.4 requires exactly 8 workers and the 16GB memory ceiling")
    if not args.synthetic and project != PROJECT_AUTHORITY:
        raise RuntimeError(f"Production project authority changed: {project}")
    package_receipt = audit.verify_package_manifest(package_root)
    contract = audit.load_contract(package_root)
    private_root.mkdir(parents=True, exist_ok=True)
    public_root.mkdir(parents=True, exist_ok=True)

    authority: dict[str, Any]
    if args.synthetic:
        if args.cache_path is None:
            raise RuntimeError("Synthetic execution requires --cache-path")
        cache = args.cache_path.resolve()
        authority = {"status": "SYNTHETIC_CACHE_AUTHORITY_OK", "cache": str(cache)}
        environment = {"status": "SYNTHETIC_ENVIRONMENT_NOT_CERTIFIED"}
    else:
        environment = audit.verify_environment(contract)
        stage = numerical.authenticate_stage07(project / numerical.STAGE07_RELATIVE)
        v103 = audit.authenticate_v103(project / "replication_package", package_root)
        prior_cache = prior.authenticate_prior_v102_cache(project=project, scratch_state=private_root, threads=args.threads, memory_limit=args.memory_limit)
        if prior_cache is None:
            raise RuntimeError("Immutable v1.0.2 private model cache is absent")
        cache, cache_receipt = prior_cache
        if cache.resolve() != (project / contract["private_cache"]["relative_path"]).resolve():
            raise RuntimeError("Private cache path changed")
        if cache.stat().st_size != int(contract["private_cache"]["bytes"]) or audit.sha256_file(cache) != contract["private_cache"]["sha256"]:
            raise RuntimeError("Private cache bytes changed")
        authority = {"status": "REFERENCE_DEMAND_V104_AUTHORITIES_AUTHENTICATED_OK", "stage07": stage, "v103": v103, "cache_receipt": cache_receipt, "cache_sha256": contract["private_cache"]["sha256"]}
    if not cache.is_file():
        raise RuntimeError(f"Model cache is missing: {cache}")
    before = audit.path_snapshot([cache])
    config = {
        "status": "REFERENCE_DEMAND_V104_PRIVATE_CONFIGURATION",
        "synthetic": bool(args.synthetic),
        "package_manifest_sha256": package_receipt["manifest_sha256"],
        "contract_sha256": audit.sha256_file(package_root / audit.CONTRACT_RELATIVE),
        "analysis_script_sha256": audit.sha256_file(Path(__file__)),
        "cache_sha256": audit.sha256_file(cache),
        "threads": args.threads,
        "memory_limit": args.memory_limit,
    }
    config_sha256 = numerical.sha256_json(config)
    config_path = private_root / "configuration.json"
    if config_path.is_file():
        saved = audit.load_json(config_path)
        if saved.get("config_sha256") != config_sha256:
            raise RuntimeError("Private root belongs to a different configuration")
    else:
        audit.atomic_json(config_path, {**config, "config_sha256": config_sha256, "created_utc": audit.utc_now()})

    print("Loading authenticated private model cache...", flush=True)
    data = legacy.load_arrays(cache)
    support, gap, exact, nonzero, log_scale, log_magnitude = support_and_algebra(data, contract, synthetic=args.synthetic)
    boundary, raw_gap = raw_rate_rows(data, gap, exact)
    replication, replication_results, replication_attempts = run_replication_gates(data=data, private_root=private_root, config_sha256=config_sha256, contract=contract, synthetic=args.synthetic)
    zero_table, zero_results, zero_attempts = run_zero_family(data=data, exact=exact, private_root=private_root, config_sha256=config_sha256, contract=contract)
    decomposition_results, decomposition_attempts = run_decomposition(data=data, gap=gap, nonzero=nonzero, log_scale=log_scale, log_magnitude=log_magnitude, private_root=private_root, config_sha256=config_sha256, contract=contract)
    gap_table, gap_results, gap_attempts = run_gap_schedule(data=data, gap=gap, log_scale=log_scale, private_root=private_root, config_sha256=config_sha256, contract=contract)
    all_results = replication_results + zero_results + decomposition_results + gap_results
    attempts = replication_attempts + zero_attempts + decomposition_attempts + gap_attempts
    if any(row["status"] != "ESTIMATED" for row in attempts):
        raise RuntimeError("One or more frozen required models were not estimated")
    after = audit.path_snapshot([cache])
    audit.assert_snapshot_unchanged(before, after)

    tables = public_root / "tables"
    receipts = public_root / "receipts"
    audit.write_csv(tables / "exact_zero_boundary_rates.csv", boundary)
    audit.write_csv(tables / "exact_zero_contrasts.csv", zero_table)
    audit.write_csv(tables / "displayed_integer_gap_raw_schedule.csv", raw_gap)
    audit.write_csv(tables / "displayed_integer_gap_adjusted_schedule.csv", gap_table)
    audit.write_csv(tables / "decomposition_models.csv", flatten_models(decomposition_results))
    audit.write_csv(tables / "all_model_terms.csv", flatten_models(all_results))
    audit.write_csv(tables / "model_attempts.csv", attempts)
    audit.atomic_json(tables / "model_results.json", all_results)
    audit.atomic_json(receipts / "input_authorities.json", {"package": package_receipt, "environment": environment, "authority": authority})
    audit.atomic_json(receipts / "private_cache_authentication.json", {"status": "IMMUTABLE_PRIVATE_CACHE_AUTHENTICATED_OK", "synthetic": args.synthetic, "cache_sha256": audit.sha256_file(cache), "cache_bytes": cache.stat().st_size, "support": support})
    audit.atomic_json(receipts / "input_no_mutation.json", {"status": "AUTHENTICATED_INPUT_UNCHANGED_AFTER_ANALYSIS", "before": before, "after": after})
    audit.atomic_json(receipts / "replication_gates.json", replication)

    e2 = next(row for row in decomposition_results if row["model"] == "E2_sign_logK_logM")
    e3 = next(row for row in decomposition_results if row["model"] == "E3_logK_logM_within_exact_gap")
    e4 = next(row for row in decomposition_results if row["model"] == "E4_own_opponent_RD_within_exact_gap")
    interpretation = {
        "status": "REFERENCE_DEMAND_V104_INTERPRETATION_COMPLETE",
        "synthetic": bool(args.synthetic),
        "exact_zero_primary_window_0p5": next(row for row in zero_table if float(row["window_abs_draw_payoff_le"]) == 0.5),
        "E2": {name: model_term(e2, name) for name in ("strictly_favorable", "log_K", "log_abs_half_minus_E")},
        "E3_within_gap": {name: model_term(e3, name) for name in ("log_K", "log_abs_half_minus_E")},
        "E4_RD_components": {name: model_term(e4, name) for name in ("log_chooser_rd", "log_opponent_rd", "log_abs_half_minus_E")},
        "claim_boundary": "Exploratory reduced-form associations only; no causal RD, unique-zero, or structural loss-aversion claim.",
        "exact_zero_policy": "literal zero; tolerance equivalence authenticated; excluded from logarithms without flooring",
        "displayed_gap_schedule": "pair-specific comparisons to g=-1; not one joint categorical regression",
    }
    audit.atomic_json(public_root / "interpretation.json", interpretation)
    analysis = {
        "status": audit.ANALYSIS_STATUS,
        "created_utc": audit.utc_now(),
        "synthetic": bool(args.synthetic),
        "support": support,
        "replication_gates": replication["status"],
        "required_models": len(attempts),
        "zero_windows": list(contract["zero_windows"]),
        "displayed_gap_range": [contract["displayed_gap_min"], contract["displayed_gap_max"]],
        "displayed_gap_reference": contract["displayed_gap_reference"],
        "runtime_seconds": time.time() - started,
        "causal_claims_authorized": False,
        "structural_loss_aversion_claim_authorized": False,
    }
    audit.atomic_json(public_root / "analysis_complete.json", analysis)
    print("KINDNESS_REFERENCE_DEMAND_CLOSURE_V104_ANALYSIS_COMPLETE", flush=True)
    print(f"Models: {len(attempts)}", flush=True)
    print(f"Runtime seconds: {time.time() - started:.3f}", flush=True)


def main() -> int:
    args = parse_args()
    if args.self_test:
        component_self_test()
        return 0
    execute(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
