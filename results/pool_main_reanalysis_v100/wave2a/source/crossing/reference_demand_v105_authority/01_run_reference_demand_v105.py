#!/usr/bin/env python3
"""Run the append-only ply-adjusted reference-demand closure v1.0.5."""

from __future__ import annotations

import argparse
import gc
import importlib.util
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import kindness_price_elasticity_common_v102 as numerical
import reference_demand_v105_common as audit
import run_kindness_price_elasticity_v102 as legacy


PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
PLY_LABELS = ("0_4", "5_6", "7_8", "9_10", "11_20", "21_40", "41_80", "81_plus")


def load_v104_module() -> Any:
    path = Path(__file__).with_name("00_run_reference_demand_v104.py")
    spec = importlib.util.spec_from_file_location("executed_v104_authority", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load exact v1.0.4 executed analysis source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V104 = load_v104_module()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--cache-path", type=Path, required=True)
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


def t_value(term: Mapping[str, Any]) -> float:
    return float(term["coefficient_probability_units"]) / float(term["standard_error_probability_units"])


def p_value(term: Mapping[str, Any]) -> float:
    return float(term["p_value_two_sided"])


def base_spec(model: str, role: str, sample: str) -> dict[str, Any]:
    return {
        "model": model,
        "epistemic_label": "X",
        "analysis_role": role,
        "sample": sample,
        "outcome": "indicator for kind draw",
        "cluster": "chooser account (lossless private integer mapping)",
        "game_stage": "eight frozen ply bands; long means ply_count > 10",
        "causal_claim": False,
        "unique_zero_claim": False,
        "structural_loss_aversion_claim": False,
        "multiple_testing_family": "outside Campaign 1 confirmatory Holm family",
    }


def checkpointed(
    *, private_root: Path, config_sha256: str, model: str,
    fit: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = private_root / "model_checkpoints" / f"{model}.json"
    if path.is_file():
        saved = audit.load_json(path)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("model") != model
            or saved.get("status") != "REFERENCE_DEMAND_V105_MODEL_CHECKPOINT_OK"
        ):
            raise RuntimeError(f"Checkpoint configuration changed: {model}")
        print(f"V105_MODEL_CHECKPOINT_AUTHENTICATED model={model}", flush=True)
        return dict(saved["result"]), dict(saved["attempt"])
    print(f"V105_MODEL_BEGIN model={model}", flush=True)
    started = time.time()
    result = audit.json_ready(fit())
    attempt = {
        "model": model,
        "status": "ESTIMATED",
        "runtime_seconds": time.time() - started,
        "error": None,
    }
    audit.atomic_json(path, {
        "status": "REFERENCE_DEMAND_V105_MODEL_CHECKPOINT_OK",
        "created_utc": audit.utc_now(),
        "config_sha256": config_sha256,
        "model": model,
        "attempt": attempt,
        "result": result,
    })
    print(f"V105_MODEL_OK model={model}", flush=True)
    gc.collect()
    return dict(result), attempt


def add_ply_dummies(regressors: dict[str, Any], data: Mapping[str, Any], idx: Any) -> None:
    legacy.add_dummies(regressors, data["ply_band"][idx], "ply_band")


def stage_controls(
    data: Mapping[str, Any], idx: Any, *, month_trends: bool
) -> dict[str, Any]:
    controls = V104.current_controls(data, idx, month_trends=month_trends)
    add_ply_dummies(controls, data, idx)
    return controls


def fit_lpm(
    *, data: Mapping[str, Any], mask: Any, model: str, role: str,
    regressors_builder: Callable[[Any], dict[str, Any]],
    fixed_effects_builder: Callable[[Any], list[Any]],
    exposure_names: Sequence[str],
) -> dict[str, Any]:
    _, np, _, _ = numerical.import_dependencies()
    idx = np.flatnonzero(mask)
    if idx.size < 1_000:
        raise RuntimeError(f"{model}: fewer than 1,000 rows")
    result = numerical.fit_lpm_cluster(
        outcome=data["kind"][idx],
        regressors=regressors_builder(idx),
        clusters=data["chooser_index"][idx],
        fixed_effects=fixed_effects_builder(idx),
        exposure_names=tuple(exposure_names),
        row_ids=data["row_hash"][idx],
        specification=base_spec(model, role, f"rows_selected={idx.size}"),
    )
    result["price_mean"] = float(np.mean(data["price"][idx]))
    result["outcome_mean"] = float(np.mean(data["kind"][idx]))
    result["short_rows"] = int(np.count_nonzero(data["ply_count"][idx] <= 10))
    result["long_rows"] = int(np.count_nonzero(data["ply_count"][idx] > 10))
    return audit.json_ready(result)


def load_augmented_arrays(cache: Path) -> dict[str, Any]:
    _, np, _, pq = numerical.import_dependencies()
    data = legacy.load_arrays(cache)
    table = pq.read_table(cache, columns=["ply_count", "ply_band", "log_ply"])
    for field in ("ply_count", "ply_band", "log_ply"):
        data[field] = numerical.arrow_numpy(table, field, nullable_float=False)
    del table
    rows = int(data["kind"].size)
    if any(int(data[field].size) != rows for field in ("ply_count", "ply_band", "log_ply")):
        raise RuntimeError("Augmented ply columns do not conserve rows")
    ply = np.asarray(data["ply_count"], dtype=np.int64)
    bands = np.asarray(data["ply_band"], dtype=np.int64)
    expected = np.select(
        [ply <= 4, ply <= 6, ply <= 8, ply <= 10, ply <= 20, ply <= 40, ply <= 80],
        [0, 1, 2, 3, 4, 5, 6], default=7,
    )
    if np.any(ply < 0) or not np.array_equal(bands, expected):
        raise RuntimeError("Augmented ply count or band mapping changed")
    if not np.allclose(data["log_ply"], np.log1p(ply), rtol=0, atol=1e-14):
        raise RuntimeError("Augmented log-ply field changed")
    return data


def compare_v104_models(
    observed: Sequence[Mapping[str, Any]], expected_path: Path,
    *, tolerance_pp: float, synthetic: bool,
) -> dict[str, Any]:
    if synthetic:
        return {
            "status": "REFERENCE_DEMAND_V105_SYNTHETIC_V104_GATE_OK",
            "models": len(observed), "terms_compared": 0,
            "maximum_coefficient_difference_pp": None,
            "maximum_se_difference_pp": None,
        }
    expected = audit.load_json(expected_path)
    observed_map = {str(row["model"]): row for row in observed}
    expected_map = {str(row["model"]): row for row in expected}
    if set(observed_map) != set(expected_map):
        raise RuntimeError("v1.0.4 exact-replication model inventory changed")
    max_coefficient = 0.0
    max_se = 0.0
    terms_compared = 0
    for model in sorted(expected_map):
        left = observed_map[model]
        right = expected_map[model]
        for key in ("rows_raw", "chooser_clusters", "fixed_effect_count", "matrix_rank"):
            if int(left.get(key, -1)) != int(right.get(key, -1)):
                raise RuntimeError(f"v1.0.4 replication support changed: {model} {key}")
        left_terms = {str(row["term"]): row for row in left.get("terms", [])}
        right_terms = {str(row["term"]): row for row in right.get("terms", [])}
        if set(left_terms) != set(right_terms):
            raise RuntimeError(f"v1.0.4 replication term inventory changed: {model}")
        for term in sorted(right_terms):
            coefficient = abs(
                float(left_terms[term]["coefficient_percentage_points"])
                - float(right_terms[term]["coefficient_percentage_points"])
            )
            standard_error = abs(
                float(left_terms[term]["standard_error_percentage_points"])
                - float(right_terms[term]["standard_error_percentage_points"])
            )
            max_coefficient = max(max_coefficient, coefficient)
            max_se = max(max_se, standard_error)
            terms_compared += 1
        if "elasticity" in right:
            difference = abs(float(left["elasticity"]["estimate"]) - float(right["elasticity"]["estimate"]))
            if difference > tolerance_pp:
                raise RuntimeError(f"v1.0.4 elasticity replication changed: {model}")
    if max_coefficient > tolerance_pp or max_se > tolerance_pp:
        raise RuntimeError(
            f"v1.0.4 full replication failed: coefficient={max_coefficient}; se={max_se}"
        )
    return {
        "status": "REFERENCE_DEMAND_V105_ALL_141_V104_MODELS_REPLICATED_OK",
        "models": len(observed_map),
        "terms_compared": terms_compared,
        "maximum_coefficient_difference_pp": max_coefficient,
        "maximum_se_difference_pp": max_se,
        "tolerance_pp": tolerance_pp,
        "expected_model_results_sha256": audit.sha256_file(expected_path),
    }


def run_v104_gate(
    *, data: Mapping[str, Any], package_root: Path, private_root: Path,
    config_sha256: str, synthetic: bool, tolerance: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    v104_package = package_root / "frozen_authorities/v104/executed_package_source"
    v104_contract = V104.audit.load_contract(v104_package)
    gate_root = private_root / "v104_exact_replication"
    gate_root.mkdir(parents=True, exist_ok=True)
    support, gap, exact, nonzero, log_scale, log_magnitude = V104.support_and_algebra(
        data, v104_contract, synthetic=synthetic
    )
    replication, replication_results, replication_attempts = V104.run_replication_gates(
        data=data, private_root=gate_root, config_sha256=config_sha256,
        contract=v104_contract, synthetic=synthetic,
    )
    _, zero_results, zero_attempts = V104.run_zero_family(
        data=data, exact=exact, private_root=gate_root,
        config_sha256=config_sha256, contract=v104_contract,
    )
    decomposition_results, decomposition_attempts = V104.run_decomposition(
        data=data, gap=gap, nonzero=nonzero, log_scale=log_scale,
        log_magnitude=log_magnitude, private_root=gate_root,
        config_sha256=config_sha256, contract=v104_contract,
    )
    _, gap_results, gap_attempts = V104.run_gap_schedule(
        data=data, gap=gap, log_scale=log_scale, private_root=gate_root,
        config_sha256=config_sha256, contract=v104_contract,
    )
    results = replication_results + zero_results + decomposition_results + gap_results
    attempts = replication_attempts + zero_attempts + decomposition_attempts + gap_attempts
    if len(results) != 141 or len(attempts) != 141:
        raise RuntimeError("v1.0.4 replication family no longer has 141 models")
    comparison = compare_v104_models(
        results,
        package_root / "frozen_authorities/v104/public_results/tables/model_results.json",
        tolerance_pp=tolerance,
        synthetic=synthetic,
    )
    comparison["legacy_replication_gate"] = replication
    comparison["support"] = support
    return comparison, results, attempts


def ply_descriptives(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    _, np, _, _ = numerical.import_dependencies()
    y = np.asarray(data["kind"], dtype=np.float64)
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    bands = np.asarray(data["ply_band"], dtype=np.int64)
    definitions = (
        ("all", np.ones(y.size, dtype=bool)),
        ("costly", draw < 0),
        ("exact_zero", draw == 0),
        ("favorable", draw > 0),
    )
    rows: list[dict[str, Any]] = []
    for sign, sign_mask in definitions:
        for band, label in enumerate(PLY_LABELS):
            mask = sign_mask & (bands == band)
            n = int(np.count_nonzero(mask))
            kinds = int(np.sum(y[mask]))
            probability = kinds / n if n else math.nan
            rows.append({
                "draw_sign": sign,
                "ply_band": label,
                "rows": n,
                "kind_draws": kinds,
                "chooser_accounts": int(np.unique(data["chooser_index"][mask]).size),
                "kind_rate_pct": 100.0 * probability if n else None,
                "binomial_se_pp": 100.0 * math.sqrt(probability * (1.0 - probability) / n) if n else None,
            })
    return rows


def scope_masks(data: Mapping[str, Any]) -> dict[str, Any]:
    _, np, _, _ = numerical.import_dependencies()
    rows = data["kind"].size
    return {
        "all": np.ones(rows, dtype=bool),
        "long_ply_gt_10": np.asarray(data["ply_count"]) > 10,
    }


def run_zero_family(
    *, data: Mapping[str, Any], private_root: Path, config_sha256: str,
    windows: Sequence[float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    exact = draw == 0.0
    table: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for scope, scope_mask in scope_masks(data).items():
        for window in windows:
            mask = scope_mask & (np.abs(draw) <= float(window))
            token = str(window).replace(".", "p")
            name_a = f"P_zero_tristate_{scope}_w{token}_negative_omitted"
            def fit_a(mask=mask, model=name_a):
                return fit_lpm(
                    data=data, mask=mask, model=model,
                    role="stage_adjusted_exact_zero_tristate",
                    regressors_builder=lambda idx: {
                        "exact_zero_minus_negative": exact[idx].astype(float),
                        "positive_minus_negative": (draw[idx] > 0).astype(float),
                        **stage_controls(data, idx, month_trends=True),
                    },
                    fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["price_bin20"][idx]],
                    exposure_names=("exact_zero_minus_negative", "positive_minus_negative"),
                )
            result_a, attempt_a = checkpointed(
                private_root=private_root, config_sha256=config_sha256,
                model=name_a, fit=fit_a,
            )
            name_b = f"P_zero_tristate_{scope}_w{token}_exact_omitted"
            def fit_b(mask=mask, model=name_b):
                return fit_lpm(
                    data=data, mask=mask, model=model,
                    role="stage_adjusted_exact_zero_tristate",
                    regressors_builder=lambda idx: {
                        "negative_minus_exact": (draw[idx] < 0).astype(float),
                        "positive_minus_exact": (draw[idx] > 0).astype(float),
                        **stage_controls(data, idx, month_trends=True),
                    },
                    fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["price_bin20"][idx]],
                    exposure_names=("negative_minus_exact", "positive_minus_exact"),
                )
            result_b, attempt_b = checkpointed(
                private_root=private_root, config_sha256=config_sha256,
                model=name_b, fit=fit_b,
            )
            results.extend((result_a, result_b)); attempts.extend((attempt_a, attempt_b))
            exact_negative = model_term(result_a, "exact_zero_minus_negative")
            positive_negative = model_term(result_a, "positive_minus_negative")
            positive_exact = model_term(result_b, "positive_minus_exact")
            table.append({
                "scope": scope,
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
                "fixed_effects": "chooser + premium20; current state + month trends + ply-band controls",
                "causal": False,
            })
    return table, results, attempts


def run_piecewise_family(
    *, data: Mapping[str, Any], private_root: Path, config_sha256: str,
    windows: Sequence[float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    terms = ("loss_magnitude", "gain_magnitude", "exact_zero_level", "strictly_positive_level")
    for scope, scope_mask in scope_masks(data).items():
        for window in windows:
            mask = scope_mask & (np.abs(draw) <= float(window))
            token = str(window).replace(".", "p")
            model = f"P_local_piecewise_{scope}_w{token}"
            def fit(mask=mask, model=model):
                return fit_lpm(
                    data=data, mask=mask, model=model,
                    role="stage_adjusted_local_piecewise_shape",
                    regressors_builder=lambda idx: {
                        "loss_magnitude": np.maximum(-draw[idx], 0.0),
                        "gain_magnitude": np.maximum(draw[idx], 0.0),
                        "exact_zero_level": (draw[idx] == 0).astype(float),
                        "strictly_positive_level": (draw[idx] > 0).astype(float),
                        **stage_controls(data, idx, month_trends=True),
                    },
                    fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["price_bin20"][idx]],
                    exposure_names=terms,
                )
            result, attempt = checkpointed(
                private_root=private_root, config_sha256=config_sha256,
                model=model, fit=fit,
            )
            results.append(result); attempts.append(attempt)
            row: dict[str, Any] = {
                "scope": scope,
                "window_abs_draw_payoff_le": window,
                "rows": result["rows_raw"],
                "chooser_clusters": result["chooser_clusters"],
                "causal": False,
            }
            for term_name in terms:
                term = model_term(result, term_name)
                row[f"{term_name}_pp"] = term["coefficient_percentage_points"]
                row[f"{term_name}_se_pp"] = term["standard_error_percentage_points"]
                row[f"{term_name}_t"] = t_value(term)
            rows.append(row)
    return rows, results, attempts


def run_e_family(
    *, data: Mapping[str, Any], gap: Any, nonzero: Any, log_scale: Any,
    log_magnitude: Any, private_root: Path, config_sha256: str, rd_cutoff: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    log_abs_draw = np.full(draw.size, np.nan, dtype=np.float64)
    log_abs_draw[nonzero] = np.log(np.abs(draw[nonzero]))
    log_chooser_rd = np.log(np.asarray(data["chooser_rd"], dtype=np.float64))
    log_opponent_rd = np.log(np.asarray(data["opponent_rd"], dtype=np.float64))
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for scope, scope_mask in scope_masks(data).items():
        definitions: list[tuple[str, Any, Callable[[Any], dict[str, Any]], Callable[[Any], list[Any]], tuple[str, ...]]] = []
        active = nonzero & scope_mask
        definitions.append(("E1", active, lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_abs_draw_payoff": log_abs_draw[idx], **stage_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_abs_draw_payoff")))
        definitions.append(("E2", active, lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **stage_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
        local = active & (np.abs(gap) <= 30)
        definitions.append(("E3", local, lambda idx: {"log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **stage_controls(data, idx, month_trends=True)}, lambda idx: [data["chooser_index"][idx], gap[idx]], ("log_K", "log_abs_half_minus_E")))
        definitions.append(("E4", local, lambda idx: {"log_chooser_rd": log_chooser_rd[idx], "log_opponent_rd": log_opponent_rd[idx], "log_abs_half_minus_E": log_magnitude[idx], **stage_controls(data, idx, month_trends=True)}, lambda idx: [data["chooser_index"][idx], gap[idx]], ("log_chooser_rd", "log_opponent_rd", "log_abs_half_minus_E")))
        definitions.append(("E5a", active & (data["chooser_rd"] <= rd_cutoff), lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **stage_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
        definitions.append(("E5b", active & (data["opponent_rd"] <= rd_cutoff), lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **stage_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
        definitions.append(("E5c", active & (data["chooser_rd"] <= rd_cutoff) & (data["opponent_rd"] <= rd_cutoff), lambda idx: {"strictly_favorable": (draw[idx] > 0).astype(float), "log_K": log_scale[idx], "log_abs_half_minus_E": log_magnitude[idx], **stage_controls(data, idx, month_trends=False)}, lambda idx: [data["chooser_index"][idx], data["month_code"][idx]], ("strictly_favorable", "log_K", "log_abs_half_minus_E")))
        for label, mask, regressors, fixed_effects, exposures in definitions:
            model = f"P_{label}_ply_adjusted_{scope}"
            fit = lambda mask=mask, model=model, regressors=regressors, fixed_effects=fixed_effects, exposures=exposures: fit_lpm(
                data=data, mask=mask, model=model,
                role="stage_adjusted_E1_E5_decomposition",
                regressors_builder=regressors,
                fixed_effects_builder=fixed_effects,
                exposure_names=exposures,
            )
            result, attempt = checkpointed(
                private_root=private_root, config_sha256=config_sha256,
                model=model, fit=fit,
            )
            results.append(result); attempts.append(attempt)
    return results, attempts


def run_side_decompositions(
    *, data: Mapping[str, Any], nonzero: Any, log_scale: Any,
    log_magnitude: Any, private_root: Path, config_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    draw = np.asarray(data["draw_payoff"], dtype=np.float64)
    log_abs_draw = np.full(draw.size, np.nan, dtype=np.float64)
    log_abs_draw[nonzero] = np.log(np.abs(draw[nonzero]))
    km_results: list[dict[str, Any]] = []
    km_attempts: list[dict[str, Any]] = []
    logd_results: list[dict[str, Any]] = []
    logd_attempts: list[dict[str, Any]] = []
    side_masks = {"costly": draw < 0, "favorable": draw > 0}
    for scope, scope_mask in scope_masks(data).items():
        for side, side_mask in side_masks.items():
            mask = scope_mask & side_mask
            model = f"P_side_K_M_{side}_{scope}"
            def fit_km(mask=mask, model=model):
                return fit_lpm(
                    data=data, mask=mask, model=model,
                    role="post_v104_side_specific_K_M_decomposition",
                    regressors_builder=lambda idx: {
                        "log_K": log_scale[idx],
                        "log_abs_half_minus_E": log_magnitude[idx],
                        **stage_controls(data, idx, month_trends=False),
                    },
                    fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["month_code"][idx]],
                    exposure_names=("log_K", "log_abs_half_minus_E"),
                )
            result, attempt = checkpointed(
                private_root=private_root, config_sha256=config_sha256,
                model=model, fit=fit_km,
            )
            km_results.append(result); km_attempts.append(attempt)
            logd_model = f"P_side_log_abs_D_{side}_{scope}"
            def fit_logd(mask=mask, model=logd_model):
                result = fit_lpm(
                    data=data, mask=mask, model=model,
                    role="stage_adjusted_side_specific_log_magnitude",
                    regressors_builder=lambda idx: {
                        "log_abs_draw_payoff": log_abs_draw[idx],
                        **stage_controls(data, idx, month_trends=True),
                    },
                    fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["price_bin20"][idx]],
                    exposure_names=("log_abs_draw_payoff",),
                )
                term = model_term(result, "log_abs_draw_payoff")
                result["mean_scaled_association"] = float(term["coefficient_probability_units"]) / float(result["outcome_mean"])
                return result
            logd_result, logd_attempt = checkpointed(
                private_root=private_root, config_sha256=config_sha256,
                model=logd_model, fit=fit_logd,
            )
            logd_results.append(logd_result); logd_attempts.append(logd_attempt)
    return km_results, km_attempts, logd_results, logd_attempts


def run_gap_schedule(
    *, data: Mapping[str, Any], gap: Any, log_scale: Any,
    private_root: Path, config_sha256: str, scope: str,
    scope_mask: Any, minimum: int, maximum: int, reference: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = numerical.import_dependencies()
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    reference_mask = scope_mask & (gap == reference)
    reference_rows = int(np.count_nonzero(reference_mask))
    reference_choosers = np.unique(data["chooser_index"][reference_mask])
    for variant, include_log_scale in (("primary", False), ("plus_log_K_sensitivity", True)):
        rows.append({
            "scope": scope, "displayed_gap": reference,
            "reference_gap": reference, "variant": variant,
            "coefficient_pp": 0.0, "se_pp": None, "t": None,
            "target_rows": reference_rows, "reference_rows": reference_rows,
            "rows": reference_rows, "chooser_clusters": int(reference_choosers.size),
            "identifying_choosers_with_both_gaps": None,
            "estimation": "omitted reference", "causal": False,
        })
        for target in range(minimum, maximum + 1):
            if target == reference:
                continue
            mask = scope_mask & ((gap == target) | (gap == reference))
            target_mask = scope_mask & (gap == target)
            target_rows = int(np.count_nonzero(target_mask))
            target_choosers = np.unique(data["chooser_index"][target_mask])
            identifying = int(np.intersect1d(target_choosers, reference_choosers, assume_unique=True).size)
            token = f"{target:+d}".replace("+", "p").replace("-", "m")
            ref_token = f"{reference:+d}".replace("+", "p").replace("-", "m")
            model = f"P_gap_{scope}_{token}_vs_{ref_token}_{variant}"
            def fit(mask=mask, model=model, target=target, include_log_scale=include_log_scale):
                def regressors(idx: Any) -> dict[str, Any]:
                    values = {
                        "target_gap_minus_reference": (gap[idx] == target).astype(float),
                        **stage_controls(data, idx, month_trends=False),
                    }
                    if include_log_scale:
                        values["log_K"] = log_scale[idx]
                    return values
                return fit_lpm(
                    data=data, mask=mask, model=model,
                    role="stage_adjusted_displayed_gap_pairwise_schedule",
                    regressors_builder=regressors,
                    fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["month_code"][idx]],
                    exposure_names=("target_gap_minus_reference",),
                )
            result, attempt = checkpointed(
                private_root=private_root, config_sha256=config_sha256,
                model=model, fit=fit,
            )
            results.append(result); attempts.append(attempt)
            term = model_term(result, "target_gap_minus_reference")
            rows.append({
                "scope": scope, "displayed_gap": target,
                "reference_gap": reference, "variant": variant,
                "coefficient_pp": term["coefficient_percentage_points"],
                "se_pp": term["standard_error_percentage_points"],
                "t": t_value(term), "p_value_two_sided": p_value(term),
                "target_rows": target_rows, "reference_rows": reference_rows,
                "rows": result["rows_raw"],
                "chooser_clusters": result["chooser_clusters"],
                "identifying_choosers_with_both_gaps": identifying,
                "estimation": "separate two-gap comparison; chooser and month FE; current state + ply bands; chooser-clustered",
                "causal": False,
            })
    return rows, results, attempts


def run_adjacent_gap(
    *, data: Mapping[str, Any], gap: Any, private_root: Path,
    config_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for scope, scope_mask in scope_masks(data).items():
        mask = scope_mask & ((gap == -1) | (gap == 0) | (gap == 1))
        model = f"P_joint_gap_m1_0_p1_{scope}"
        def fit(mask=mask, model=model):
            return fit_lpm(
                data=data, mask=mask, model=model,
                role="stage_adjusted_joint_adjacent_gap",
                regressors_builder=lambda idx: {
                    "gap_0_minus_gap_m1": (gap[idx] == 0).astype(float),
                    "gap_p1_minus_gap_m1": (gap[idx] == 1).astype(float),
                    **stage_controls(data, idx, month_trends=False),
                },
                fixed_effects_builder=lambda idx: [data["chooser_index"][idx], data["month_code"][idx]],
                exposure_names=("gap_0_minus_gap_m1", "gap_p1_minus_gap_m1"),
            )
        result, attempt = checkpointed(
            private_root=private_root, config_sha256=config_sha256,
            model=model, fit=fit,
        )
        results.append(result); attempts.append(attempt)
    return results, attempts


def flatten_models(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        for term in result.get("terms", []):
            rows.append({
                "model": result.get("model"),
                "analysis_role": result.get("analysis_role"),
                "epistemic_label": result.get("epistemic_label"),
                "term": term.get("term"),
                "coefficient_pp": term.get("coefficient_percentage_points"),
                "se_pp": term.get("standard_error_percentage_points"),
                "t": term.get("t_cluster"),
                "p_value_two_sided": term.get("p_value_two_sided"),
                "rows": result.get("rows_raw"),
                "chooser_clusters": result.get("chooser_clusters"),
                "fixed_effect_count": result.get("fixed_effect_count"),
                "absorption_method": result.get("absorption_method"),
                "matrix_rank": result.get("matrix_rank"),
                "short_rows": result.get("short_rows"),
                "long_rows": result.get("long_rows"),
                "causal": False,
            })
    return rows


def selected_terms(results: Sequence[Mapping[str, Any]], model: str, terms: Sequence[str]) -> dict[str, Any]:
    result = next(row for row in results if row["model"] == model)
    return {term: model_term(result, term) for term in terms}


def component_self_test() -> None:
    import numpy as np  # type: ignore
    draw = np.array([-0.4, -0.1, 0.0, 0.1, 0.4])
    loss = np.maximum(-draw, 0.0)
    gain = np.maximum(draw, 0.0)
    if loss.tolist() != [0.4, 0.1, 0.0, 0.0, 0.0]:
        raise RuntimeError("Local loss-slope component self-test failed")
    if gain.tolist() != [0.0, 0.0, 0.0, 0.1, 0.4]:
        raise RuntimeError("Local gain-slope component self-test failed")
    if int(np.count_nonzero(draw == 0)) != 1:
        raise RuntimeError("Exact-zero component self-test failed")
    print("REFERENCE_DEMAND_V105_ANALYSIS_COMPONENT_SELFTEST_OK", flush=True)


def execute(args: argparse.Namespace) -> None:
    started = time.time()
    package_root = args.package_root.resolve()
    project = args.project_root.resolve()
    private_root = args.private_root.resolve()
    public_root = args.public_root.resolve()
    cache = args.cache_path.resolve()
    if args.threads != 8 or args.memory_limit != "16GB":
        raise RuntimeError("v1.0.5 requires exactly 8 workers and 16GB")
    if not args.synthetic and project != PROJECT_AUTHORITY:
        raise RuntimeError(f"Production project authority changed: {project}")
    package_receipt = audit.verify_package_manifest(package_root)
    contract = audit.load_contract(package_root)
    frozen_v104 = audit.authenticate_frozen_v104(package_root, contract)
    environment = (
        {"status": "SYNTHETIC_ENVIRONMENT_NOT_CERTIFIED"}
        if args.synthetic else audit.verify_environment(contract)
    )
    if not cache.is_file():
        raise RuntimeError(f"Augmented cache is missing: {cache}")
    cache_receipt_path = cache.with_name(contract["augmented_private_cache"]["receipt"])
    if not cache_receipt_path.is_file():
        raise RuntimeError("Augmented cache receipt is missing")
    cache_receipt = audit.load_json(cache_receipt_path)
    if (
        cache_receipt.get("status") != "REFERENCE_DEMAND_V105_AUGMENTED_CACHE_OK"
        or cache_receipt.get("output_sha256") != audit.sha256_file(cache)
        or int(cache_receipt.get("output_bytes", -1)) != cache.stat().st_size
    ):
        raise RuntimeError("Augmented cache authentication failed")
    if not args.synthetic:
        expected_cache = (
            project / contract["augmented_private_cache"]["relative_parent"]
            / contract["augmented_private_cache"]["filename"]
        ).resolve()
        if cache != expected_cache:
            raise RuntimeError("Production augmented cache path changed")
        if int(cache_receipt.get("rows", -1)) != int(contract["original_private_cache"]["rows"]):
            raise RuntimeError("Production augmented cache support changed")
    private_root.mkdir(parents=True, exist_ok=True)
    public_root.mkdir(parents=True, exist_ok=True)
    before = audit.path_snapshot([cache])
    config = {
        "status": "REFERENCE_DEMAND_V105_PRIVATE_CONFIGURATION",
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
            raise RuntimeError("Private root belongs to another v1.0.5 configuration")
    else:
        audit.atomic_json(config_path, {
            **config, "config_sha256": config_sha256,
            "created_utc": audit.utc_now(),
        })
    print("Loading authenticated ply-augmented cache...", flush=True)
    data = load_augmented_arrays(cache)
    v104_package = package_root / "frozen_authorities/v104/executed_package_source"
    v104_contract = V104.audit.load_contract(v104_package)
    support, gap, exact, nonzero, log_scale, log_magnitude = V104.support_and_algebra(
        data, v104_contract, synthetic=args.synthetic
    )
    support["minimum_ply"] = int(data["ply_count"].min())
    support["maximum_ply"] = int(data["ply_count"].max())
    support["short_rows"] = int((data["ply_count"] <= 10).sum())
    support["long_rows"] = int((data["ply_count"] > 10).sum())

    print("Running exact 141-model v1.0.4 replication gate...", flush=True)
    v104_gate, v104_results, v104_attempts = run_v104_gate(
        data=data, package_root=package_root, private_root=private_root,
        config_sha256=config_sha256, synthetic=args.synthetic,
        tolerance=float(contract["replication_tolerance_pp"]),
    )
    print(v104_gate["status"], flush=True)

    print("Running ply-adjusted and long-game closure family...", flush=True)
    zero_table, zero_results, zero_attempts = run_zero_family(
        data=data, private_root=private_root, config_sha256=config_sha256,
        windows=contract["zero_windows"],
    )
    piecewise_table, piecewise_results, piecewise_attempts = run_piecewise_family(
        data=data, private_root=private_root, config_sha256=config_sha256,
        windows=contract["zero_windows"],
    )
    e_results, e_attempts = run_e_family(
        data=data, gap=gap, nonzero=nonzero, log_scale=log_scale,
        log_magnitude=log_magnitude, private_root=private_root,
        config_sha256=config_sha256, rd_cutoff=float(contract["rd_cutoff"]),
    )
    km_results, km_attempts, logd_results, logd_attempts = run_side_decompositions(
        data=data, nonzero=nonzero, log_scale=log_scale,
        log_magnitude=log_magnitude, private_root=private_root,
        config_sha256=config_sha256,
    )
    scopes = scope_masks(data)
    gap_contract = contract["displayed_gap"]
    full_gap_table, full_gap_results, full_gap_attempts = run_gap_schedule(
        data=data, gap=gap, log_scale=log_scale, private_root=private_root,
        config_sha256=config_sha256, scope="all", scope_mask=scopes["all"],
        minimum=int(gap_contract["full_minimum"]),
        maximum=int(gap_contract["full_maximum"]),
        reference=int(gap_contract["reference"]),
    )
    long_gap_table, long_gap_results, long_gap_attempts = run_gap_schedule(
        data=data, gap=gap, log_scale=log_scale, private_root=private_root,
        config_sha256=config_sha256, scope="long_ply_gt_10",
        scope_mask=scopes["long_ply_gt_10"],
        minimum=int(gap_contract["long_near_minimum"]),
        maximum=int(gap_contract["long_near_maximum"]),
        reference=int(gap_contract["reference"]),
    )
    adjacent_results, adjacent_attempts = run_adjacent_gap(
        data=data, gap=gap, private_root=private_root,
        config_sha256=config_sha256,
    )
    new_results = (
        zero_results + piecewise_results + e_results + km_results + logd_results
        + full_gap_results + long_gap_results + adjacent_results
    )
    new_attempts = (
        zero_attempts + piecewise_attempts + e_attempts + km_attempts + logd_attempts
        + full_gap_attempts + long_gap_attempts + adjacent_attempts
    )
    if len(new_results) != int(contract["new_model_family"]["new_models"]):
        raise RuntimeError(f"New frozen model count changed: {len(new_results)}")
    all_results = v104_results + new_results
    all_attempts = v104_attempts + new_attempts
    if len(all_results) != int(contract["new_model_family"]["total_required_models"]):
        raise RuntimeError(f"Total frozen model count changed: {len(all_results)}")
    if any(row.get("status") != "ESTIMATED" for row in all_attempts):
        raise RuntimeError("One or more required models were not estimated")
    after = audit.path_snapshot([cache])
    audit.assert_snapshot_unchanged(before, after)

    tables = public_root / "tables"
    receipts = public_root / "receipts"
    audit.write_csv(tables / "ply_sign_by_band.csv", ply_descriptives(data))
    audit.write_csv(tables / "stage_adjusted_exact_zero_contrasts.csv", zero_table)
    audit.write_csv(tables / "stage_adjusted_local_piecewise.csv", piecewise_table)
    audit.write_csv(tables / "stage_adjusted_E1_E5_terms.csv", flatten_models(e_results))
    audit.write_csv(tables / "side_specific_K_M_terms.csv", flatten_models(km_results))
    logd_rows = flatten_models(logd_results)
    for row in logd_rows:
        result = next(item for item in logd_results if item["model"] == row["model"])
        row["outcome_mean"] = result["outcome_mean"]
        row["mean_scaled_association"] = result["mean_scaled_association"]
    audit.write_csv(tables / "side_specific_log_abs_D.csv", logd_rows)
    audit.write_csv(
        tables / "stage_adjusted_displayed_gap_schedule.csv",
        full_gap_table + long_gap_table,
    )
    audit.write_csv(tables / "joint_adjacent_gap_models.csv", flatten_models(adjacent_results))
    audit.write_csv(tables / "all_new_model_terms.csv", flatten_models(new_results))
    audit.write_csv(tables / "model_attempts.csv", all_attempts)
    audit.atomic_json(tables / "all_model_results.json", all_results)
    audit.atomic_json(receipts / "input_authorities.json", {
        "package": package_receipt,
        "environment": environment,
        "frozen_v104": frozen_v104,
    })
    audit.atomic_json(receipts / "augmented_cache_authentication.json", {
        "status": "REFERENCE_DEMAND_V105_AUGMENTED_CACHE_AUTHENTICATED_OK",
        "synthetic": bool(args.synthetic),
        "cache_sha256": audit.sha256_file(cache),
        "cache_bytes": cache.stat().st_size,
        "cache_receipt": cache_receipt,
        "support": support,
    })
    audit.atomic_json(receipts / "v104_exact_replication_gate.json", v104_gate)
    audit.atomic_json(receipts / "input_no_mutation.json", {
        "status": "AUTHENTICATED_AUGMENTED_CACHE_UNCHANGED_AFTER_ANALYSIS",
        "before": before, "after": after,
    })

    zero_all = next(row for row in zero_table if row["scope"] == "all" and float(row["window_abs_draw_payoff_le"]) == 0.5)
    zero_long = next(row for row in zero_table if row["scope"] == "long_ply_gt_10" and float(row["window_abs_draw_payoff_le"]) == 0.5)
    interpretation = {
        "status": "REFERENCE_DEMAND_V105_INTERPRETATION_COMPLETE",
        "synthetic": bool(args.synthetic),
        "v104_replication_gate": v104_gate["status"],
        "primary_zero_window_0p5_all": zero_all,
        "primary_zero_window_0p5_long": zero_long,
        "E2_ply_adjusted_all": selected_terms(
            e_results, "P_E2_ply_adjusted_all",
            ("strictly_favorable", "log_K", "log_abs_half_minus_E"),
        ),
        "E2_ply_adjusted_long": selected_terms(
            e_results, "P_E2_ply_adjusted_long_ply_gt_10",
            ("strictly_favorable", "log_K", "log_abs_half_minus_E"),
        ),
        "adjacent_gap_all": selected_terms(
            adjacent_results, "P_joint_gap_m1_0_p1_all",
            ("gap_0_minus_gap_m1", "gap_p1_minus_gap_m1"),
        ),
        "adjacent_gap_long": selected_terms(
            adjacent_results, "P_joint_gap_m1_0_p1_long_ply_gt_10",
            ("gap_0_minus_gap_m1", "gap_p1_minus_gap_m1"),
        ),
        "costly_K_M_all": selected_terms(
            km_results, "P_side_K_M_costly_all", ("log_K", "log_abs_half_minus_E"),
        ),
        "costly_K_M_long": selected_terms(
            km_results, "P_side_K_M_costly_long_ply_gt_10", ("log_K", "log_abs_half_minus_E"),
        ),
        "claim_boundary": "Exploratory reduced-form associations only; no causal price, unique-zero, RD, or structural loss-aversion claim.",
    }
    audit.atomic_json(public_root / "interpretation.json", interpretation)
    analysis = {
        "status": audit.ANALYSIS_STATUS,
        "created_utc": audit.utc_now(),
        "synthetic": bool(args.synthetic),
        "support": support,
        "v104_replication_gate": v104_gate["status"],
        "v104_models": len(v104_results),
        "new_models": len(new_results),
        "total_required_models": len(all_results),
        "zero_windows": list(contract["zero_windows"]),
        "ply_bands": contract["ply"]["bands"],
        "runtime_seconds": time.time() - started,
        "causal_claims_authorized": False,
        "unique_zero_claim_authorized": False,
        "structural_loss_aversion_claim_authorized": False,
    }
    audit.atomic_json(public_root / "analysis_complete.json", analysis)
    print("KINDNESS_REFERENCE_DEMAND_CLOSURE_V105_ANALYSIS_COMPLETE", flush=True)
    print(f"v1.0.4 models replicated: {len(v104_results)}", flush=True)
    print(f"New v1.0.5 models: {len(new_results)}", flush=True)
    print(f"Total models: {len(all_results)}", flush=True)
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
