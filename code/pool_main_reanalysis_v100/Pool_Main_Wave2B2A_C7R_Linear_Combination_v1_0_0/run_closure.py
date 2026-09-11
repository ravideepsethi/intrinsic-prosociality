#!/usr/bin/env python3
"""Recover the C7R repeat-meeting fairness contrast and clustered SE."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


PACKAGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE_ROOT / "source"))
import campaign1_nonprofile_common_v102 as frozen  # noqa: E402


SCRIPT_VERSION = "1.0.0"
MODEL_NAME = "X_C7R_fair_repeat_interaction_all_meetings"
EXPECTED_CACHE_SHA256 = "05e3a7a245da7bfe72ea7e628fbd3e2a7a8c01555c76f5889ac6249f648d6f7a"
EXPECTED_CACHE_BYTES = 63_820_554
EXPECTED_CACHE_ROWS = 830_991
EXPECTED_REFERENCE_SHA256 = "8fa37cf49cab2f667bc2750892d4c30a67e88e44a53d0a7dcc291aed72445751"
EXPECTED_C7R_SUCCESS_SHA256 = "a022d7490a378b1176fb38997e8ab6cc8af2a28b5d1a92cbd678cc9f3ac8dee8"
EXPECTED_FROZEN_SOURCE_SHA256 = "f629876216c797180265d1b848a4424f211fe9a43cffa4dabdb3de67acbc5f1c"
EXPECTED_SAMPLE_FINGERPRINT = "a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30"
EXPECTED_RESULTS = {
    "fair": (0.015943340790702507, 0.0005465562360270706),
    "repeat": (0.001323140961929891, 0.000667147785112481),
    "fair_x_repeat": (-0.0031497184121758058, 0.001375177462798302),
}
MODEL_COLUMNS = (
    "first_meeting", "repeat_meeting", "fair", "clearly_worse",
    "chooser_id", "row_hash", "speed_code", "month_code", "hour_of_week",
    "ply_band", "draw_payoff", "win_premium", "chooser_clock",
    "opponent_clock", "chooser_elo", "opponent_elo", "chooser_rd",
    "opponent_rd", "tournament", "kind",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial_{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def normal_two_sided_p(value: float) -> float:
    return math.erfc(abs(value) / math.sqrt(2.0))


def load_model_cache(path: Path, threads: int) -> dict[str, Any]:
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    pa.set_cpu_count(int(threads))
    metadata = pq.ParquetFile(path).metadata
    if metadata.num_rows != EXPECTED_CACHE_ROWS:
        raise RuntimeError(
            f"C7R cache row count changed: {metadata.num_rows:,} != {EXPECTED_CACHE_ROWS:,}"
        )
    table = pq.read_table(path, columns=list(MODEL_COLUMNS), use_threads=True)
    nullable = {
        "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
        "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
    }
    data = {
        name: frozen.arrow_numpy(table, name, nullable_float=name in nullable)
        for name in table.column_names
    }
    if data["kind"].size != EXPECTED_CACHE_ROWS:
        raise RuntimeError("C7R cache materialization lost rows")
    return data


def fit_hdfe_with_covariance(
    *, outcome: Any, exposures: Mapping[str, Any],
    numeric_controls: Mapping[str, Any], fixed_effects: Mapping[str, Any],
    clusters: Any, row_ids: Any, specification: Mapping[str, Any],
    absorption_tolerance: float = 1e-9,
    absorption_maximum_iterations: int = 2_000,
) -> dict[str, Any]:
    """Frozen v1.0.2 HDFE estimator with exposure covariance additionally returned.

    Every estimation operation through the clustered sandwich matrix is copied
    from ``fit_hdfe_cluster`` in the authenticated frozen source. The only
    extension is serialization of the exposure block of the covariance matrix
    and prespecified linear contrasts calculated from that matrix.
    """
    import numpy as np

    y = np.asarray(outcome, dtype=np.float64)
    n = y.size
    if n < 1_000:
        raise RuntimeError(f"{specification.get('model')}: fewer than 1,000 rows")
    weights = np.ones(n, dtype=np.float64)
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
    if not columns:
        raise RuntimeError("Model contains no regressors")
    x = np.column_stack(columns)
    finite = np.isfinite(y) & np.isfinite(weights) & (weights > 0)
    finite &= np.all(np.isfinite(x), axis=1)
    for values in fixed_effects.values():
        finite &= np.asarray(values).reshape(-1).shape[0] == n
    if not np.all(finite):
        y = y[finite]
        x = x[finite]
        weights = weights[finite]
        clusters = np.asarray(clusters)[finite]
        row_ids = np.asarray(row_ids)[finite]
        fixed_effects = {
            name: np.asarray(values)[finite] for name, values in fixed_effects.items()
        }
    else:
        clusters = np.asarray(clusters)
        row_ids = np.asarray(row_ids)
    transformed, iterations, last = frozen._absorb_matrix(
        np.column_stack([y, x]),
        weights,
        list(fixed_effects.values()),
        tolerance=absorption_tolerance,
        maximum_iterations=absorption_maximum_iterations,
    )
    y_resid = transformed[:, 0]
    x_resid = transformed[:, 1:]
    norms = np.sqrt(np.sum(weights[:, None] * x_resid * x_resid, axis=0))
    retained = norms > 1e-10
    for exposure in exposure_names:
        index = names.index(exposure)
        if not retained[index]:
            raise RuntimeError(f"Exposure has no residual variation: {exposure}")
    x_resid = x_resid[:, retained]
    retained_names = [name for name, keep in zip(names, retained) if keep]
    root_weight = np.sqrt(weights)
    weighted_x = x_resid * root_weight[:, None]
    weighted_y = y_resid * root_weight
    beta, _, rank, singular = np.linalg.lstsq(weighted_x, weighted_y, rcond=None)
    if int(rank) != x_resid.shape[1]:
        raise RuntimeError(f"Rank-deficient HDFE model: {rank}/{x_resid.shape[1]}")
    residual = y_resid - x_resid @ beta
    bread = np.linalg.inv(weighted_x.T @ weighted_x)
    cluster_codes, groups = frozen.factor_codes(clusters)
    if groups < 100:
        raise RuntimeError(f"Too few clusters for inference: {groups}")
    scores = np.empty((groups, x_resid.shape[1]), dtype=np.float64)
    score_weight = weights * residual
    for column in range(x_resid.shape[1]):
        scores[:, column] = np.bincount(
            cluster_codes,
            weights=score_weight * x_resid[:, column],
            minlength=groups,
        )
    correction = (groups / (groups - 1)) * ((y.size - 1) / (y.size - rank))
    covariance = bread @ (scores.T @ scores) @ bread * correction
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    results: list[dict[str, Any]] = []
    exposure_positions: dict[str, int] = {}
    for exposure in exposure_names:
        position = retained_names.index(exposure)
        exposure_positions[exposure] = position
        coefficient = float(beta[position])
        standard_error = float(standard_errors[position])
        t_value = coefficient / standard_error if standard_error > 0 else math.nan
        results.append(
            {
                "term": exposure,
                "coefficient": coefficient,
                "standard_error": standard_error,
                "t_cluster": t_value,
                "p_value_two_sided": normal_two_sided_p(t_value),
            }
        )
    exposure_covariance = {
        left: {
            right: float(covariance[exposure_positions[left], exposure_positions[right]])
            for right in exposure_names
        }
        for left in exposure_names
    }
    return {
        **dict(specification),
        "rows": int(y.size),
        "clusters": groups,
        "results": results,
        "exposure_covariance": exposure_covariance,
        "outcome_mean": float(np.average(y, weights=weights)),
        "numeric_controls": retained_names[len(exposure_names):],
        "fixed_effects": list(fixed_effects),
        "matrix_rank": int(rank),
        "smallest_singular_value": float(singular[-1]),
        "absorption_iterations": iterations,
        "absorption_tolerance": absorption_tolerance,
        "absorption_maximum_iterations": absorption_maximum_iterations,
        "absorption_last_adjustment": last,
        "cluster_correction": correction,
        "sample_specification_sha256": frozen.sample_fingerprint(row_ids, specification),
    }


def linear_contrast(
    fit: Mapping[str, Any], weights: Mapping[str, float], name: str
) -> dict[str, Any]:
    estimates = {row["term"]: float(row["coefficient"]) for row in fit["results"]}
    covariance = fit["exposure_covariance"]
    coefficient = sum(weights[term] * estimates[term] for term in weights)
    variance = sum(
        weights[left] * weights[right] * float(covariance[left][right])
        for left in weights for right in weights
    )
    standard_error = math.sqrt(max(variance, 0.0))
    t_value = coefficient / standard_error if standard_error > 0 else math.nan
    return {
        "contrast": name,
        "weights": dict(weights),
        "coefficient": coefficient,
        "coefficient_percentage_points": 100.0 * coefficient,
        "standard_error": standard_error,
        "standard_error_percentage_points": 100.0 * standard_error,
        "t_cluster": t_value,
        "p_value_two_sided": normal_two_sided_p(t_value),
        "ci95": [coefficient - 1.96 * standard_error, coefficient + 1.96 * standard_error],
        "ci95_percentage_points": [
            100.0 * (coefficient - 1.96 * standard_error),
            100.0 * (coefficient + 1.96 * standard_error),
        ],
    }


def verify_reference(reference_path: Path) -> dict[str, Any]:
    if sha256_file(reference_path) != EXPECTED_REFERENCE_SHA256:
        raise RuntimeError("Wave 2B2A first-meeting model authority changed")
    models = load_json(reference_path)
    matches = [row for row in models if row.get("model") == MODEL_NAME]
    if len(matches) != 1 or matches[0].get("status") != "ESTIMATED":
        raise RuntimeError("Wave 2B2A interaction reference is missing or ambiguous")
    return matches[0]


def compare_frozen_result(fit: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    observed = {row["term"]: row for row in fit["results"]}
    published = {row["term"]: row for row in reference["results"]}
    checks = []
    for term, expected_constants in EXPECTED_RESULTS.items():
        if term not in observed or term not in published:
            raise RuntimeError(f"Missing frozen coefficient: {term}")
        expected_coefficient, expected_se = expected_constants
        row = {
            "term": term,
            "coefficient_absolute_difference_from_returned_wave2b2a": abs(
                float(observed[term]["coefficient"]) - float(published[term]["coefficient"])
            ),
            "standard_error_absolute_difference_from_returned_wave2b2a": abs(
                float(observed[term]["standard_error"]) - float(published[term]["standard_error"])
            ),
            "coefficient_absolute_difference_from_frozen_constant": abs(
                float(observed[term]["coefficient"]) - expected_coefficient
            ),
            "standard_error_absolute_difference_from_frozen_constant": abs(
                float(observed[term]["standard_error"]) - expected_se
            ),
        }
        row["pass"] = max(value for key, value in row.items() if key.endswith("difference_from_returned_wave2b2a") or key.endswith("difference_from_frozen_constant")) <= 5e-10
        checks.append(row)
    if not all(row["pass"] for row in checks):
        raise RuntimeError(f"Closure rerun did not reproduce Wave 2B2A: {checks}")
    if fit["sample_specification_sha256"] != reference["sample_specification_sha256"]:
        raise RuntimeError("Closure model row/specification fingerprint changed")
    return {"status": "FROZEN_WAVE2B2A_MODEL_REPRODUCED_OK", "tolerance": 5e-10, "checks": checks}


def write_manifest(root: Path) -> None:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "REPORT_FILE_HASHES.tsv":
            continue
        rows.append((path.relative_to(root).as_posix(), path.stat().st_size, sha256_file(path)))
    text = "file\tbytes\tsha256\n" + "".join(
        f"{relative}\t{size}\t{digest}\n" for relative, size, digest in rows
    )
    atomic_text(root / "REPORT_FILE_HASHES.tsv", text)


def privacy_scan(root: Path) -> dict[str, Any]:
    forbidden = {"game_id", "chooser_id", "opponent_id", "username", "username_norm"}
    violations = []
    for path in root.rglob("*.csv"):
        with path.open(encoding="utf-8", newline="") as stream:
            header = next(csv.reader(stream), [])
        overlap = sorted(forbidden & {str(value).lower() for value in header})
        if overlap:
            violations.append({"file": path.relative_to(root).as_posix(), "columns": overlap})
    if violations:
        raise RuntimeError(f"Public-output privacy scan failed: {violations}")
    return {
        "status": "C7R_LINEAR_COMBINATION_PUBLIC_PRIVACY_OK",
        "forbidden_identifier_columns": sorted(forbidden),
        "violations": 0,
        "private_row_level_files_transferred": False,
    }


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    started = time.time()
    cache = args.model_cache.expanduser().resolve()
    public = args.c7r_public.expanduser().resolve()
    output_base = args.output_base.expanduser().resolve()
    transfer = args.transfer_root.expanduser().resolve()
    package_source = PACKAGE_ROOT / "source/campaign1_nonprofile_common_v102.py"
    if sha256_file(package_source) != EXPECTED_FROZEN_SOURCE_SHA256:
        raise RuntimeError("Bundled frozen estimator source changed")
    if not cache.is_file() or cache.stat().st_size != EXPECTED_CACHE_BYTES:
        raise RuntimeError(f"Authenticated C7R model cache is missing or changed: {cache}")
    print("Hashing the 64 MB authenticated C7R model cache", flush=True)
    if sha256_file(cache) != EXPECTED_CACHE_SHA256:
        raise RuntimeError("C7R model-cache SHA-256 changed")
    success_path = public / "_SUCCESS.json"
    reference_path = public / "first_meeting_models.json"
    if not success_path.is_file() or sha256_file(success_path) != EXPECTED_C7R_SUCCESS_SHA256:
        raise RuntimeError("Wave 2B2A C7R public success authority changed")
    success = load_json(success_path)
    reference = verify_reference(reference_path)
    print("Loading authenticated C7R comparison columns", flush=True)
    data = load_model_cache(cache, args.threads)
    import numpy as np

    fair = np.asarray(data["fair"], dtype=bool)
    worse = np.asarray(data["clearly_worse"], dtype=bool)
    repeat = np.asarray(data["repeat_meeting"], dtype=bool)
    indices = np.flatnonzero(fair | worse)
    controls = (
        "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
        "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd", "tournament",
    )
    fixed_effects = ("chooser_id", "speed_code", "month_code", "hour_of_week", "ply_band")
    print(f"Re-estimating frozen interaction model on {indices.size:,} rows", flush=True)
    fit = fit_hdfe_with_covariance(
        outcome=data["kind"][indices],
        exposures={
            "fair": fair[indices].astype(np.float64),
            "repeat": repeat[indices].astype(np.float64),
            "fair_x_repeat": (fair & repeat)[indices].astype(np.float64),
        },
        numeric_controls={name: data[name][indices] for name in controls},
        fixed_effects={name: data[name][indices] for name in fixed_effects},
        clusters=data["chooser_id"][indices],
        row_ids=data["row_hash"][indices],
        specification={
            "model": MODEL_NAME,
            "analysis_role": "post-gate exploratory C7R",
            "cluster": "chooser_id",
            "causal_claim": False,
            "epistemic_label": "X",
        },
    )
    reproduction = compare_frozen_result(fit, reference)
    first_gradient = linear_contrast(fit, {"fair": 1.0}, "fairness_gradient_first_meetings")
    repeat_gradient = linear_contrast(
        fit,
        {"fair": 1.0, "fair_x_repeat": 1.0},
        "fairness_gradient_repeat_meetings",
    )
    interaction = linear_contrast(
        fit,
        {"fair_x_repeat": 1.0},
        "repeat_minus_first_fairness_gradient",
    )
    covariance_value = float(fit["exposure_covariance"]["fair"]["fair_x_repeat"])

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"POOL_MAIN_WAVE2B2A_C7R_LINEAR_COMBINATION_{stamp}"
    output_base.mkdir(parents=True, exist_ok=True)
    staging = output_base / f".{name}.partial_{os.getpid()}"
    final = output_base / name
    if staging.exists() or final.exists():
        raise RuntimeError(f"Output target already exists: {name}")
    staging.mkdir()
    authentication = {
        "status": "C7R_LINEAR_COMBINATION_INPUTS_AUTHENTICATED_OK",
        "sample_fingerprint": EXPECTED_SAMPLE_FINGERPRINT,
        "model_cache": {
            "path_machine_specific": str(cache),
            "bytes": cache.stat().st_size,
            "rows": EXPECTED_CACHE_ROWS,
            "sha256": EXPECTED_CACHE_SHA256,
        },
        "wave2b2a_c7r_success": {
            "path_machine_specific": str(success_path),
            "sha256": EXPECTED_C7R_SUCCESS_SHA256,
            "status": success["status"],
        },
        "wave2b2a_first_meeting_models_sha256": EXPECTED_REFERENCE_SHA256,
        "frozen_common_source_sha256": EXPECTED_FROZEN_SOURCE_SHA256,
        "network_requests": 0,
    }
    result = {
        "status": "C7R_LINEAR_COMBINATION_CLOSURE_OK",
        "created_at_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "sample_fingerprint": EXPECTED_SAMPLE_FINGERPRINT,
        "model": MODEL_NAME,
        "estimand_note": (
            "The repeat-meeting fairness gradient is beta_fair + beta_fair_x_repeat. "
            "Its variance uses the chooser-clustered covariance from the unchanged frozen model."
        ),
        "first_meeting_gradient": first_gradient,
        "repeat_meeting_gradient": repeat_gradient,
        "repeat_minus_first_gradient": interaction,
        "fair_fair_x_repeat_covariance": covariance_value,
        "model_results": fit["results"],
        "exposure_covariance": fit["exposure_covariance"],
        "model_diagnostics": {
            key: fit[key] for key in (
                "rows", "clusters", "matrix_rank", "smallest_singular_value",
                "absorption_iterations", "absorption_tolerance",
                "absorption_maximum_iterations", "absorption_last_adjustment",
                "cluster_correction", "sample_specification_sha256",
            )
        },
        "reproduction": reproduction,
        "interpretation": (
            "The fairness gradient remains positive at repeat meetings but is smaller "
            "than at first meetings; the interaction is descriptive, not causal."
        ),
        "original_repeat_only_nonconvergence_preserved": True,
        "repeat_only_model_retried": False,
        "private_row_level_files_transferred": False,
    }
    atomic_json(staging / "INPUT_AUTHENTICATION.json", authentication)
    atomic_json(staging / "c7r_linear_combination.json", result)
    with (staging / "c7r_linear_combination.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "contrast", "coefficient_percentage_points",
                "standard_error_percentage_points", "t_cluster",
                "p_value_two_sided", "ci95_low_percentage_points",
                "ci95_high_percentage_points",
            ),
        )
        writer.writeheader()
        for row in (first_gradient, repeat_gradient, interaction):
            writer.writerow(
                {
                    "contrast": row["contrast"],
                    "coefficient_percentage_points": row["coefficient_percentage_points"],
                    "standard_error_percentage_points": row["standard_error_percentage_points"],
                    "t_cluster": row["t_cluster"],
                    "p_value_two_sided": row["p_value_two_sided"],
                    "ci95_low_percentage_points": row["ci95_percentage_points"][0],
                    "ci95_high_percentage_points": row["ci95_percentage_points"][1],
                }
            )
    atomic_text(
        staging / "README.md",
        "# C7R first/repeat linear-combination closure\n\n"
        "This aggregate-only addendum re-estimates the already returned Wave 2B2A "
        "interaction model without changing its sample, controls, fixed effects, "
        "clustering, tolerance, or finite-sample correction. It serializes the "
        "exposure covariance needed for the repeat-meeting fairness gradient and "
        "checks all three fitted coefficients and standard errors against Wave 2B2A.\n\n"
        "The original standalone repeat-only numerical failure remains part of the "
        "record and was not overwritten or silently retried.\n",
    )
    atomic_json(staging / "PRIVACY_SCAN.json", privacy_scan(staging))
    atomic_json(
        staging / "_SUCCESS.json",
        {
            "status": "POOL_MAIN_WAVE2B2A_C7R_LINEAR_COMBINATION_OK",
            "created_at_utc": utc_now(),
            "sample_fingerprint": EXPECTED_SAMPLE_FINGERPRINT,
            "frozen_model_reproduced": True,
            "private_row_level_files_transferred": False,
            "network_requests": 0,
            "runtime_seconds": time.time() - started,
        },
    )
    write_manifest(staging)
    os.replace(staging, final)

    transfer.mkdir(parents=True, exist_ok=True)
    archive = transfer / f"{name}.zip"
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    if archive.exists() or sidecar.exists():
        raise RuntimeError(f"Transfer target already exists: {archive}")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in sorted(item for item in final.rglob("*") if item.is_file()):
            handle.write(path, (Path(name) / path.relative_to(final)).as_posix())
    with zipfile.ZipFile(archive) as handle:
        bad = handle.testzip()
    if bad is not None:
        raise RuntimeError(f"Result ZIP CRC failure: {bad}")
    digest = sha256_file(archive)
    atomic_text(sidecar, f"{digest}  {archive.name}\n")
    print("POOL_MAIN_WAVE2B2A_C7R_LINEAR_COMBINATION_OK", flush=True)
    print(f"RESULT_ZIP: {archive}", flush=True)
    print(f"RESULT_SIDECAR: {sidecar}", flush=True)
    print(f"RESULT_SHA256: {digest}", flush=True)
    print(f"RUNTIME_SECONDS: {time.time() - started:.1f}", flush=True)
    return archive, sidecar


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--c7r-public", type=Path, required=True)
    parser.add_argument("--output-base", type=Path, required=True)
    parser.add_argument("--transfer-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    return parser.parse_args(argv)


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
