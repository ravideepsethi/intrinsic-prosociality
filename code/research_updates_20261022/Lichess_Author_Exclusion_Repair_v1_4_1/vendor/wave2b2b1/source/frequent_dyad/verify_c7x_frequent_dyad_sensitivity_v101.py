#!/usr/bin/env python3
"""Independent aggregate verifier for C7X frequent-dyad sensitivity v1.0.1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence


STATUS = "C7X_FREQUENT_DYAD_SENSITIVITY_V101_OK"
QA_STATUS = "C7X_FREQUENT_DYAD_SENSITIVITY_V101_QA_OK"
SAMPLES = [
    "all", "pair_lt_3", "pair_lt_5", "pair_lt_10",
    "pair_eq_2", "pair_3_4", "pair_5_9", "pair_ge_10",
]
MODELS = [
    "chooser_context_hdfe_chooser_cluster",
    "directed_pair_context_fe_chooser_cluster",
    "directed_pair_context_fe_unordered_pair_cluster",
]
EXPECTED_CHOOSER_COEFFICIENT = 0.14556932160589928
EXPECTED_CHOOSER_STANDARD_ERROR = 0.020351569816937143
EXPECTED_DIRECTED_PAIR_COEFFICIENT = 0.12978153938638437
EXPECTED_DIRECTED_PAIR_CHOOSER_CLUSTER_SE = 0.030495801391880323
EXPECTED_DIRECTED_PAIR_UNORDERED_CLUSTER_SE = 0.03259236410387049
AUTHORITY_TOLERANCE = 1e-6


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def integer(row: dict[str, str], key: str) -> int:
    return int(row[key])


def floating(row: dict[str, str], key: str) -> float:
    return float(row[key])


def close(observed: float, expected: float, tolerance: float = AUTHORITY_TOLERANCE) -> bool:
    return math.isfinite(observed) and abs(observed - expected) <= tolerance


def verify_manifest(root: Path, expected_sha256: str) -> None:
    manifest = root / "file_manifest.tsv"
    if sha256_file(manifest) != expected_sha256:
        raise RuntimeError("Public file-manifest SHA-256 changed")
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["file", "bytes", "sha256"]:
            raise RuntimeError(f"File-manifest schema changed: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise RuntimeError("Public file manifest is empty")
    seen: set[str] = set()
    for row in rows:
        relative = row["file"]
        if relative in seen or relative.startswith("/") or ".." in Path(relative).parts:
            raise RuntimeError(f"Unsafe or duplicate public path: {relative}")
        seen.add(relative)
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Manifested public file is missing: {relative}")
        if path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Public file byte size changed: {relative}")
        if sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Public file SHA-256 changed: {relative}")


def verify_output(
    root: Path,
    *,
    expected_rows: int,
    expected_benefactor_rows: int,
    expected_claimer_rows: int,
    expected_benefactor_kind: int,
    expected_claimer_kind: int,
    synthetic_test_mode: bool,
) -> dict[str, Any]:
    success = load_json(root / "_SUCCESS.json")
    if success.get("status") != STATUS or success.get("aggregate_only") is not True:
        raise RuntimeError("Success marker changed or aggregate-only gate failed")
    if synthetic_test_mode:
        if success.get("exact_authoritative_baseline_reproduced") is not None:
            raise RuntimeError("Synthetic run claimed production baseline reproduction")
    elif success.get("exact_authoritative_baseline_reproduced") is not True:
        raise RuntimeError("Exact authoritative baseline success gate failed")
    verify_manifest(root, str(success["report_manifest_sha256"]))

    qa = load_json(root / "qa.json")
    if qa.get("status") != QA_STATUS:
        raise RuntimeError("QA status changed")
    gates = {key: value for key, value in qa.items() if isinstance(value, bool)}
    if not gates or not all(gates.values()):
        raise RuntimeError(f"A QA gate failed: {gates}")

    summary = load_json(root / "summary.json")
    if summary.get("status") != STATUS:
        raise RuntimeError("Summary status changed")
    baseline = load_json(root / "baseline_reproduction.json")
    if baseline.get("raw_counts_reproduced_exactly") is not True:
        raise RuntimeError("Raw baseline reproduction gate failed")
    if synthetic_test_mode:
        if baseline.get("exact_authoritative_model_reproduction_pass") is not None:
            raise RuntimeError("Synthetic baseline marker changed")
    elif baseline.get("exact_authoritative_model_reproduction_pass") is not True:
        raise RuntimeError("Authoritative model reproduction gate failed")

    raw_rows = read_csv(root / "raw_rate_sensitivity.csv")
    if [row["sample"] for row in raw_rows] != SAMPLES:
        raise RuntimeError("Raw-sensitivity sample inventory or order changed")
    raw = {row["sample"]: row for row in raw_rows}
    full = raw["all"]
    expected = {
        "observations": expected_rows,
        "benefactor_observations": expected_benefactor_rows,
        "benefactor_kind_draws": expected_benefactor_kind,
        "claimer_observations": expected_claimer_rows,
        "claimer_kind_draws": expected_claimer_kind,
    }
    observed = {key: integer(full, key) for key in expected}
    if observed != expected:
        raise RuntimeError(f"Raw baseline changed: {observed} != {expected}")

    for row in raw_rows:
        n = integer(row, "observations")
        n1 = integer(row, "benefactor_observations")
        n0 = integer(row, "claimer_observations")
        y1 = integer(row, "benefactor_kind_draws")
        y0 = integer(row, "claimer_kind_draws")
        if n1 + n0 != n or not (0 <= y1 <= n1 and 0 <= y0 <= n0):
            raise RuntimeError(f"Raw count conservation failed: {row}")
        if n1 and n0:
            p1 = 100.0 * y1 / n1
            p0 = 100.0 * y0 / n0
            difference = p1 - p0
            iid_se = 100.0 * math.sqrt(
                (y1 / n1) * (1.0 - y1 / n1) / n1
                + (y0 / n0) * (1.0 - y0 / n0) / n0
            )
            for key, wanted in (
                ("benefactor_kindness_rate_pct", p1),
                ("claimer_kindness_rate_pct", p0),
                ("benefactor_minus_claimer_pp", difference),
                ("iid_standard_error_pp", iid_se),
            ):
                if abs(floating(row, key) - wanted) > 1e-10:
                    raise RuntimeError(f"Raw calculation changed for {key}: {row}")

    n_all = integer(full, "observations")
    n_lt3 = integer(raw["pair_lt_3"], "observations")
    n_lt5 = integer(raw["pair_lt_5"], "observations")
    n_lt10 = integer(raw["pair_lt_10"], "observations")
    n_bins = [integer(raw[name], "observations") for name in SAMPLES[4:]]
    if not (n_lt3 <= n_lt5 <= n_lt10 <= n_all):
        raise RuntimeError("Nested dyad-sample counts are not monotone")
    if sum(n_bins) != n_all:
        raise RuntimeError("Exact dyad-frequency bins do not partition the full sample")
    if n_lt3 != n_bins[0] or n_lt5 != sum(n_bins[:2]) or n_lt10 != sum(n_bins[:3]):
        raise RuntimeError("Nested and exact-bin dyad samples disagree")

    support = read_csv(root / "support_by_pair_frequency.csv")
    if [row["pair_frequency_bin"] for row in support] != SAMPLES[4:]:
        raise RuntimeError("Support-bin inventory changed")
    if sum(integer(row, "all_observations") for row in support) != expected_rows:
        raise RuntimeError("Support table does not conserve the full sample")
    if sum(integer(row, "benefactor_observations") for row in support) != expected_benefactor_rows:
        raise RuntimeError("Support table does not conserve benefactor observations")
    if sum(integer(row, "claimer_observations") for row in support) != expected_claimer_rows:
        raise RuntimeError("Support table does not conserve claimer observations")

    model_rows = read_csv(root / "fixed_effect_sensitivity.csv")
    expected_keys = [(sample, model) for sample in SAMPLES for model in MODELS]
    if [(row["sample"], row["model"]) for row in model_rows] != expected_keys:
        raise RuntimeError("Fixed-effect model inventory or order changed")
    models = {(row["sample"], row["model"]): row for row in model_rows}
    allowed_statuses = {
        "ESTIMATED",
        "NO_WITHIN_GROUP_ARM_VARIATION",
        "NOT_ESTIMABLE_LOW_SUPPORT",
        "ESTIMATION_FAILURE_RETAINED",
    }
    for row in model_rows:
        n = integer(row, "observations")
        if n != integer(raw[row["sample"]], "observations"):
            raise RuntimeError(f"Model and raw sample sizes disagree: {row}")
        groups = integer(row, "absorbed_groups")
        switchers = integer(row, "identifying_groups_with_both_arms")
        switcher_rows = integer(row, "observations_in_identifying_groups")
        if not (0 <= switchers <= groups <= n):
            raise RuntimeError(f"Invalid fixed-effect support counts: {row}")
        if not (0 <= switcher_rows <= n):
            raise RuntimeError(f"Invalid identifying-row count: {row}")
        status = row["status"]
        if status not in allowed_statuses:
            raise RuntimeError(f"Unknown model status: {status}")
        if status == "ESTIMATED":
            for key in ("coefficient", "benefactor_effect_pp", "standard_error"):
                if not row.get(key) or not math.isfinite(floating(row, key)):
                    raise RuntimeError(f"Estimated model has invalid {key}: {row}")
            if floating(row, "standard_error") < 0:
                raise RuntimeError(f"Estimated model has negative standard error: {row}")
        elif status == "NO_WITHIN_GROUP_ARM_VARIATION" and switchers != 0:
            raise RuntimeError(f"No-variation model reports switchers: {row}")

    for model in MODELS:
        if models[("all", model)]["status"] != "ESTIMATED":
            raise RuntimeError(f"Full model was not estimated: {model}")
    if not synthetic_test_mode:
        chooser = models[("all", MODELS[0])]
        directed_chooser = models[("all", MODELS[1])]
        directed_unordered = models[("all", MODELS[2])]
        exact_checks = (
            close(floating(chooser, "coefficient"), EXPECTED_CHOOSER_COEFFICIENT),
            close(floating(chooser, "standard_error"), EXPECTED_CHOOSER_STANDARD_ERROR),
            close(floating(directed_chooser, "coefficient"), EXPECTED_DIRECTED_PAIR_COEFFICIENT),
            close(floating(directed_chooser, "standard_error"), EXPECTED_DIRECTED_PAIR_CHOOSER_CLUSTER_SE),
            close(floating(directed_unordered, "coefficient"), EXPECTED_DIRECTED_PAIR_COEFFICIENT),
            close(floating(directed_unordered, "standard_error"), EXPECTED_DIRECTED_PAIR_UNORDERED_CLUSTER_SE),
        )
        if not all(exact_checks):
            raise RuntimeError("Certified full-sample coefficient or SE changed")

    forbidden_tokens = (
        "game_id", "chooser_id", "opponent_id", "chooser_user_id",
        "disconnected_user_id",
    )
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".parquet", ".arrow", ".feather"}:
            raise RuntimeError(f"Private binary data leaked into public output: {path.name}")
        if path.is_file() and path.suffix.lower() in {".csv", ".tsv"}:
            header = path.open("r", encoding="utf-8").readline().lower()
            if any(token in header for token in forbidden_tokens):
                raise RuntimeError(f"Identifier column leaked into public output: {path.name}")

    return {
        "status": "C7X_FREQUENT_DYAD_SENSITIVITY_V101_INDEPENDENT_VERIFICATION_OK",
        "run_id": success.get("run_id"),
        "observations": expected_rows,
        "benefactor_observations": expected_benefactor_rows,
        "claimer_observations": expected_claimer_rows,
        "samples_verified": SAMPLES,
        "models_verified": MODELS,
        "exact_authoritative_baseline_verified": not synthetic_test_mode,
        "aggregate_only": True,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=27_627)
    parser.add_argument("--expected-benefactor-rows", type=int, default=2_208)
    parser.add_argument("--expected-claimer-rows", type=int, default=25_419)
    parser.add_argument("--expected-benefactor-kind", type=int, default=915)
    parser.add_argument("--expected-claimer-kind", type=int, default=1_247)
    parser.add_argument("--synthetic-test-mode", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        result = verify_output(
            args.output_dir.resolve(),
            expected_rows=args.expected_rows,
            expected_benefactor_rows=args.expected_benefactor_rows,
            expected_claimer_rows=args.expected_claimer_rows,
            expected_benefactor_kind=args.expected_benefactor_kind,
            expected_claimer_kind=args.expected_claimer_kind,
            synthetic_test_mode=args.synthetic_test_mode,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except BaseException as exc:
        print(f"C7X_FREQUENT_DYAD_V101_VERIFICATION_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
