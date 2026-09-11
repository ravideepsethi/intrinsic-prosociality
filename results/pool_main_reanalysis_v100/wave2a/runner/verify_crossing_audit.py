#!/usr/bin/env python3
"""Independently verify aggregate output from the Wave-2A crossing audit."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import pandas as pd

from runner import common
from runner.crossing_audit import DISPLAY_GAPS, STATUS, VERIFY_STATUS, holm_adjust


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root", type=Path, required=True)
    return parser.parse_args()


def verify_manifest(root: Path) -> int:
    path = root / "REPORT_FILE_HASHES.tsv"
    if not path.is_file():
        raise RuntimeError("Crossing report manifest is missing")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    names = set()
    for row in rows:
        relative = row["relative_path"]
        candidate = root / relative
        if relative in names or not candidate.is_file():
            raise RuntimeError(f"Crossing manifest path is duplicate or missing: {relative}")
        names.add(relative)
        if candidate.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Crossing manifest byte mismatch: {relative}")
        if common.sha256_file(candidate) != row["sha256"]:
            raise RuntimeError(f"Crossing manifest SHA-256 mismatch: {relative}")
    unlisted = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "REPORT_FILE_HASHES.tsv"
    } - names
    if unlisted:
        raise RuntimeError(f"Unlisted crossing output files: {sorted(unlisted)}")
    return len(rows)


def require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"{name} lacks columns: {missing}")


def verify_exact(root: Path, success: dict[str, Any]) -> dict[str, Any]:
    frame = pd.read_csv(root / "tables/exact_zero_1500_rd_decomposition.csv")
    require_columns(
        frame,
        {"dimension", "category", "rows", "kind_draws", "kind_rate_pct", "share_of_exact_zero_pct"},
        "exact-zero decomposition",
    )
    overall = frame.loc[frame.dimension.eq("all")]
    if len(overall) != 1:
        raise RuntimeError("Exact-zero decomposition lacks one overall row")
    total = int(overall.iloc[0].rows)
    if total != int(success["zero_identity_qa"]["exact_zero_tolerance_rows"]):
        raise RuntimeError("Exact-zero total disagrees with success receipt")
    expected_sizes = {"rating_1500_status": 3, "rd_status": 3, "rating_x_rd": 6}
    for dimension, size in expected_sizes.items():
        subset = frame.loc[frame.dimension.eq(dimension)]
        if len(subset) != size or int(subset.rows.sum()) != total:
            raise RuntimeError(f"Exact-zero partition does not conserve: {dimension}")
    nonempty = frame.rows.gt(0)
    computed = 100.0 * frame.loc[nonempty, "kind_draws"] / frame.loc[nonempty, "rows"]
    if not (computed - frame.loc[nonempty, "kind_rate_pct"]).abs().le(1e-9).all():
        raise RuntimeError("Exact-zero raw rates do not reconcile with counts")
    return {"rows": len(frame), "exact_zero_rows": total}


def verify_schedule(root: Path) -> dict[str, Any]:
    frame = pd.read_csv(root / "tables/displayed_gap_m12_p12_schedule.csv")
    require_columns(
        frame,
        {"displayed_gap", "reference_gap", "estimate_pp", "se_pp", "p_value_two_sided", "p_value_holm_24"},
        "displayed-gap schedule",
    )
    if len(frame) != 25 or set(frame.displayed_gap.astype(int)) != set(DISPLAY_GAPS):
        raise RuntimeError("Displayed-gap schedule is not complete -12...+12")
    reference = frame.loc[frame.displayed_gap.eq(-1)]
    if len(reference) != 1 or float(reference.iloc[0].estimate_pp) != 0.0:
        raise RuntimeError("Displayed-gap reference row changed")
    tests = frame.loc[~frame.displayed_gap.eq(-1)].copy()
    expected = holm_adjust(tests.p_value_two_sided.astype(float).tolist())
    if max(abs(a - b) for a, b in zip(expected, tests.p_value_holm_24.astype(float), strict=True)) > 1e-12:
        raise RuntimeError("Displayed-gap Holm adjustment failed independent reproduction")
    return {"rows": len(frame), "tests": len(tests)}


def verify_models(root: Path, success: dict[str, Any]) -> dict[str, Any]:
    joint = pd.read_csv(root / "tables/joint_adjacent_gap_models.csv")
    require_columns(joint, {"scope", "subset", "term", "estimate_pp", "se_pp", "t"}, "joint models")
    if len(joint) != 12:
        raise RuntimeError("Joint adjacent table must contain 12 term rows")
    if set(joint.scope) != {"all", "long_ply_gt_10"}:
        raise RuntimeError("Joint adjacent scopes changed")
    if set(joint.subset) != {"all", "exclude_both_1500", "both_established_nondefault"}:
        raise RuntimeError("Joint adjacent subsets changed")
    contrasts = pd.read_csv(root / "tables/controlled_local_crossing_contrasts.csv")
    require_columns(
        contrasts,
        {"specification", "estimand", "estimate_pp", "se_pp", "t", "ci95_low_pp", "ci95_high_pp"},
        "controlled contrasts",
    )
    required_specs = {
        "baseline_all",
        "split_exact_zero_1500_rd",
        "exclude_both_1500",
        "both_established_nondefault",
    }
    if set(contrasts.specification) != required_specs:
        raise RuntimeError("Controlled crossing specification set changed")
    for row in contrasts.itertuples(index=False):
        if float(row.se_pp) <= 0 or not math.isfinite(float(row.estimate_pp)):
            raise RuntimeError("Controlled contrast is nonfinite or has nonpositive SE")
        if abs(float(row.t) - float(row.estimate_pp) / float(row.se_pp)) > 1e-8:
            raise RuntimeError("Controlled t statistic does not reconcile")
        if abs(float(row.ci95_low_pp) - (float(row.estimate_pp) - 1.959963984540054 * float(row.se_pp))) > 1e-8:
            raise RuntimeError("Controlled lower confidence limit does not reconcile")
    reproduction = success["controlled_baseline_reproduction"]["status"]
    if not success.get("synthetic") and reproduction != "WAVE1_CONTROLLED_LOCAL_BASELINE_EXACTLY_REPRODUCED_WITHIN_1E_7_PP":
        raise RuntimeError("Production controlled baseline was not authenticated to Wave 1")
    return {"joint_terms": len(joint), "controlled_contrasts": len(contrasts)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.public_root.expanduser().resolve()
    success = common.load_json(root / "_SUCCESS.json")
    if success.get("status") != STATUS:
        raise RuntimeError("Crossing completion status changed")
    existing = root / "_VERIFIED.json"
    if existing.is_file():
        verify_manifest(root)
        saved = common.load_json(existing)
        if saved.get("status") != VERIFY_STATUS or saved.get("sample_fingerprint") != (success.get("sample_authority") or {}).get("fingerprint"):
            raise RuntimeError("Existing crossing verification receipt changed")
        print(VERIFY_STATUS)
        return saved
    manifest_files = verify_manifest(root)
    exact = verify_exact(root, success)
    schedule = verify_schedule(root)
    models = verify_models(root, success)
    privacy = common.privacy_scan(root)
    result = {
        "status": VERIFY_STATUS,
        "created_at_utc": common.utc_now(),
        "sample_fingerprint": (success.get("sample_authority") or {}).get("fingerprint"),
        "manifest_files_before_verifier_receipt": manifest_files,
        "exact_zero": exact,
        "displayed_gap_schedule": schedule,
        "models": models,
        "privacy": privacy,
    }
    common.atomic_json(existing, result)
    common.write_manifest_tsv(root)
    print(VERIFY_STATUS)
    return result


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
