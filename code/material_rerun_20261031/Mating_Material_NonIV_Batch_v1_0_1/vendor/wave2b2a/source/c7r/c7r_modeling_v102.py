#!/usr/bin/env python3
"""Memory-bounded estimators for the Campaign 1 C7R closure."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import campaign1_nonprofile_common_v102 as common


SCRIPT_VERSION = "1.0.2"


def directed_pair_codes(chooser: Any, opponent: Any) -> Any:
    """Return stable dense codes for ordered chooser-opponent pairs."""
    np = common.import_numpy()
    pairs = np.rec.fromarrays(
        [np.asarray(chooser, dtype=np.int64), np.asarray(opponent, dtype=np.int64)],
        names=("chooser", "opponent"),
    )
    _, codes = np.unique(pairs, return_inverse=True)
    return codes.astype(np.int64, copy=False)


def switcher_mask(groups: Any, exposure: Any) -> tuple[Any, int]:
    """Rows in groups that contain both binary exposure arms."""
    np = common.import_numpy()
    codes, count = common.factor_codes(groups)
    x = np.asarray(exposure, dtype=np.float64)
    has_zero = np.bincount(codes, weights=(x == 0), minlength=count) > 0
    has_one = np.bincount(codes, weights=(x == 1), minlength=count) > 0
    switchers = has_zero & has_one
    return switchers[codes], int(np.count_nonzero(switchers))


def _prepared_columns(
    *, exposures: Mapping[str, Any], numeric_controls: Mapping[str, Any],
    categorical_controls: Mapping[str, Any],
) -> tuple[list[Any], list[str], list[str]]:
    np = common.import_numpy()
    columns: list[Any] = []
    names: list[str] = []
    exposure_names = list(exposures)
    for name, values in exposures.items():
        columns.append(np.asarray(values, dtype=np.float64))
        names.append(name)
    for name, values in numeric_controls.items():
        raw = np.asarray(values, dtype=np.float64)
        observed = raw[np.isfinite(raw)]
        if observed.size == 0:
            continue
        median = float(np.median(observed))
        missing = ~np.isfinite(raw)
        filled = raw.copy()
        filled[missing] = median
        scale = float(np.std(filled))
        if not math.isfinite(scale) or scale <= 1e-12:
            continue
        columns.append((filled - float(np.mean(filled))) / scale)
        names.append("z_" + name)
        if np.any(missing):
            columns.append(missing.astype(np.float64))
            names.append(name + "_missing")
    for name, values in categorical_controls.items():
        codes, groups = common.factor_codes(values)
        # The first level is the reference category. These are deliberately
        # explicit only for small context effects in the <=27,627-row C7X fits.
        for level in range(1, groups):
            columns.append((codes == level).astype(np.float64))
            names.append(f"FE_{name}_{level}")
    return columns, names, exposure_names


def fit_exact_oneway_cluster(
    *, outcome: Any, exposures: Mapping[str, Any],
    numeric_controls: Mapping[str, Any], categorical_controls: Mapping[str, Any],
    high_dimensional_effect: Any, high_dimensional_name: str, clusters: Any,
    row_ids: Any, specification: Mapping[str, Any],
) -> dict[str, Any]:
    """Exact one-way within estimator with explicit small context effects.

    This avoids iterative absorption for the short-recency C7X samples. The
    nuisance categorical coefficients are never exported. The finite-sample
    correction matches the frozen C7X estimator by counting only substantive
    regressors, not absorbed or explicit fixed-effect nuisance parameters.
    """
    np = common.import_numpy()
    y = np.asarray(outcome, dtype=np.float64)
    n = y.size
    if n < 1_000:
        raise RuntimeError(f"{specification.get('model')}: fewer than 1,000 rows")
    columns, names, exposure_names = _prepared_columns(
        exposures=exposures,
        numeric_controls=numeric_controls,
        categorical_controls=categorical_controls,
    )
    if not columns:
        raise RuntimeError("Model contains no regressors")
    x = np.column_stack(columns)
    finite = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    if not np.all(finite):
        y = y[finite]
        x = x[finite]
        clusters = np.asarray(clusters)[finite]
        row_ids = np.asarray(row_ids)[finite]
        high_dimensional_effect = np.asarray(high_dimensional_effect)[finite]
    else:
        clusters = np.asarray(clusters)
        row_ids = np.asarray(row_ids)
        high_dimensional_effect = np.asarray(high_dimensional_effect)
    codes, groups = common.factor_codes(high_dimensional_effect)
    denominator = np.bincount(codes, minlength=groups).astype(np.float64)
    stacked = np.column_stack([y, x])
    for column in range(stacked.shape[1]):
        means = np.bincount(
            codes, weights=stacked[:, column], minlength=groups
        ) / denominator
        stacked[:, column] -= means[codes]
    y_within = stacked[:, 0]
    x_within = stacked[:, 1:]
    norms = np.sqrt(np.sum(x_within * x_within, axis=0))
    retained = norms > 1e-10
    for exposure in exposure_names:
        if not retained[names.index(exposure)]:
            raise RuntimeError(f"Exposure has no residual variation: {exposure}")
    x_within = x_within[:, retained]
    retained_names = [name for name, keep in zip(names, retained) if keep]
    beta, _, rank, singular = np.linalg.lstsq(x_within, y_within, rcond=None)
    if int(rank) != x_within.shape[1]:
        raise RuntimeError(f"Rank-deficient exact one-way model: {rank}/{x_within.shape[1]}")
    residual = y_within - x_within @ beta
    bread = np.linalg.inv(x_within.T @ x_within)
    cluster_codes, cluster_count = common.factor_codes(clusters)
    if cluster_count < 100:
        raise RuntimeError(f"Too few clusters for inference: {cluster_count}")
    scores = np.empty((cluster_count, x_within.shape[1]), dtype=np.float64)
    for column in range(x_within.shape[1]):
        scores[:, column] = np.bincount(
            cluster_codes,
            weights=residual * x_within[:, column],
            minlength=cluster_count,
        )
    correction_rank = sum(
        bool(keep) and not name.startswith("FE_")
        for name, keep in zip(names, retained)
    )
    correction = (cluster_count / (cluster_count - 1)) * (
        (y.size - 1) / (y.size - correction_rank)
    )
    covariance = bread @ (scores.T @ scores) @ bread * correction
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    results: list[dict[str, Any]] = []
    for exposure in exposure_names:
        position = retained_names.index(exposure)
        coefficient = float(beta[position])
        standard_error = float(standard_errors[position])
        t_value = coefficient / standard_error if standard_error > 0 else math.nan
        results.append(
            {
                "term": exposure,
                "coefficient": coefficient,
                "standard_error": standard_error,
                "t_cluster": t_value,
                "p_value_two_sided": common.normal_two_sided_p(t_value),
            }
        )
    return {
        **dict(specification),
        "rows": int(y.size),
        "clusters": cluster_count,
        "high_dimensional_fixed_effect": high_dimensional_name,
        "high_dimensional_groups": groups,
        "categorical_fixed_effects": list(categorical_controls),
        "results": results,
        "outcome_mean": float(np.mean(y)),
        "exposure_means": {
            name: float(np.mean(np.asarray(values)[finite] if not np.all(finite) else values))
            for name, values in exposures.items()
        },
        "matrix_rank": int(rank),
        "smallest_singular_value": float(singular[-1]),
        "cluster_correction": correction,
        "correction_rank_excluding_fixed_effect_nuisance": correction_rank,
        "estimator": "exact_oneway_with_explicit_small_context_effects",
        "sample_specification_sha256": common.sample_fingerprint(
            row_ids, specification
        ),
    }


def self_test() -> None:
    np = common.import_numpy()
    rng = np.random.default_rng(20260828)
    groups = np.repeat(np.arange(400), 12)
    n = groups.size
    periods = np.tile(np.arange(6), n // 6)
    exposure = rng.integers(0, 2, size=n).astype(float)
    control = rng.normal(size=n)
    group_effect = rng.normal(scale=0.4, size=400)[groups]
    period_effect = np.linspace(-0.2, 0.2, 6)[periods]
    outcome = (
        0.27 * exposure + 0.11 * control + group_effect + period_effect
        + rng.normal(scale=0.05, size=n)
    )
    exact = fit_exact_oneway_cluster(
        outcome=outcome,
        exposures={"x": exposure},
        numeric_controls={"control": control},
        categorical_controls={"period": periods},
        high_dimensional_effect=groups,
        high_dimensional_name="group",
        clusters=groups,
        row_ids=np.arange(n),
        specification={"model": "c7r_exact_synthetic"},
    )
    coefficient = exact["results"][0]["coefficient"]
    if abs(coefficient - 0.27) > 0.01:
        raise RuntimeError(f"Exact one-way coefficient mismatch: {coefficient}")
    mask, switchers = switcher_mask(groups, exposure)
    if switchers != 400 or not np.all(mask):
        raise RuntimeError("Switcher support self-test failed")
    directed = directed_pair_codes(groups, np.roll(groups, 1))
    if directed.size != n:
        raise RuntimeError("Directed-pair coding self-test failed")
    print("C7R_MODELING_SELF_TEST_OK")


if __name__ == "__main__":
    self_test()
