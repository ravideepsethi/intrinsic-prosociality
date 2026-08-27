#!/usr/bin/env python3
"""Create a compact synthetic project tree for end-to-end package validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from patron_stage10_common import (
    atomic_write_json,
    atomic_write_text,
    impute_within_cell,
    sha256_file,
    utc_now,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    return parser.parse_args()


def verify_nullable_integer_fractional_median() -> None:
    """Regression test for the real-data failure recovered in v1.0.1."""
    frame = pd.DataFrame(
        {
            "match_cell": ["fixture_cell", "fixture_cell", "fixture_cell"],
            "nullable_count": pd.Series([1, 2, pd.NA], dtype="Int64"),
        }
    )
    imputed, indicators, diagnostics = impute_within_cell(
        frame,
        ["nullable_count"],
        "match_cell",
    )
    if imputed["nullable_count"].dtype != np.dtype("float64"):
        raise RuntimeError("Nullable-integer imputation did not produce float64")
    if imputed.loc[2, "nullable_count"] != 1.5:
        raise RuntimeError("Fractional within-cell median was not preserved")
    if indicators != ["nullable_count__missing"]:
        raise RuntimeError("Nullable-integer missing indicator differs")
    if diagnostics["nullable_count"]["missing"] != 1:
        raise RuntimeError("Nullable-integer missingness diagnostic differs")
    print("PATRON_STAGE10_NULLABLE_INTEGER_IMPUTATION_REGRESSION_OK")


def fair_bin(value: int) -> str:
    if value == 0:
        return "00"
    if value <= 4:
        return f"0{value}"
    if value <= 9:
        return "05_09"
    if value <= 20:
        return "10_20"
    if value <= 50:
        return "21_50"
    if value <= 100:
        return "51_100"
    return "101_plus"


def build_panel(groups: int = 80) -> tuple[pd.DataFrame, list[dict]]:
    rows: list[dict] = []
    users: list[dict] = []
    evaluations = [400] * 6 + [200] * 6 + [0] * 6 + [-200] * 6 + [-400] * 12
    for group in range(groups):
        speed = "blitz" if group % 2 == 0 else "rapid"
        match_cell = f"10_20__{speed}"
        kind_user = f"fixture_kind_{group:04d}"
        group_users = [(kind_user, "kind", 0)] + [
            (f"fixture_control_{group:04d}_{slot}", "control", slot) for slot in [1, 2, 3]
        ]
        pattern = group % 4
        for username, role, slot in group_users:
            fair_kind_indices: set[int] = set()
            worse_kind_indices: set[int] = set()
            middle_kind_indices: set[int] = set()
            if role == "kind":
                if pattern == 0:
                    fair_kind_indices = {12, 13, 14, 15, 16}
                elif pattern == 1:
                    worse_kind_indices = {24, 25, 26}
                elif pattern == 2:
                    fair_kind_indices = {6, 7, 12, 13, 14, 15, 16, 17}
                    worse_kind_indices = {24, 25}
                else:
                    fair_kind_indices = {0, 6, 12}
            for opportunity, evaluation in enumerate(evaluations):
                fair = evaluation >= -100
                worse = evaluation <= -300
                middle = not fair and not worse
                if evaluation >= 300:
                    bin_name = "disconnected_clearly_better"
                elif evaluation > 100:
                    bin_name = "disconnected_better"
                elif evaluation >= -100:
                    bin_name = "roughly_equal"
                elif evaluation > -300:
                    bin_name = "modestly_worse_excluded"
                else:
                    bin_name = "clearly_worse"
                favorable = opportunity % 2 == 0
                kind = opportunity in fair_kind_indices or opportunity in worse_kind_indices or opportunity in middle_kind_indices
                month = "2024-01" if opportunity < 18 else "2024-02"
                chooser_elo = 1300 + 10 * (group % 80) + slot * 5
                disconnected_elo = chooser_elo + ((opportunity % 9) - 4) * 25
                rows.append(
                    {
                        "month": month,
                        "chooser_username_norm": username,
                        "kind_draw": kind,
                        "engine_eval_cp_disconnected": float(evaluation),
                        "engine_eval_cp_disconnected_capped600": float(evaluation),
                        "engine_fairness_bin": bin_name,
                        "fair_competitive": fair,
                        "clearly_worse": worse,
                        "excluded_middle": middle,
                        "chooser_draw_payoff_v2": 2.0 if favorable else -2.0,
                        "chooser_win_payoff_v2": 6.0,
                        "chooser_win_premium_v2": 4.0 if favorable else 8.0,
                        "draw_nonnegative": favorable,
                        "draw_costly": not favorable,
                        "api_speed": speed,
                        "tournament_like_event": opportunity % 5 == 0,
                        "chooser_elo": float(chooser_elo),
                        "disconnected_elo": float(disconnected_elo),
                        "chooser_clock_last_obs_s": float(3 + (opportunity * 7) % 240),
                        "disconnected_clock_last_obs_s": float(2 + (opportunity * 11) % 240),
                        "rating_gap": float(chooser_elo - disconnected_elo),
                        "avg_rating": float((chooser_elo + disconnected_elo) / 2),
                    }
                )
        users.extend(
            {
                "username": username,
                "role": role,
                "slot": slot,
                "matched_kind": kind_user,
                "speed": speed,
                "match_cell": match_cell,
                "group": group,
                "pattern": pattern,
            }
            for username, role, slot in group_users
        )
    return pd.DataFrame(rows), users


def build_snapshot(panel: pd.DataFrame, users: list[dict]) -> pd.DataFrame:
    aggregate = panel.groupby("chooser_username_norm", sort=True).agg(
        total_opps=("kind_draw", "size"),
        total_kind_count=("kind_draw", "sum"),
        fair_opps=("fair_competitive", "sum"),
        clearly_worse_opps=("clearly_worse", "sum"),
        excluded_middle_opps=("excluded_middle", "sum"),
        mean_chooser_elo=("chooser_elo", "mean"),
        sd_chooser_elo=("chooser_elo", lambda values: float(np.std(values, ddof=0))),
        chooser_elo_n=("chooser_elo", "size"),
        share_tournament=("tournament_like_event", "mean"),
        active_months=("month", "nunique"),
    )
    fair = panel[panel["fair_competitive"]].groupby("chooser_username_norm").agg(
        fair_kind_count=("kind_draw", "sum"),
        mean_draw_payoff_fair=("chooser_draw_payoff_v2", "mean"),
        mean_win_premium_fair=("chooser_win_premium_v2", "mean"),
    )
    worse = panel[panel["clearly_worse"]].groupby("chooser_username_norm").agg(
        clearly_worse_kind_count=("kind_draw", "sum")
    )
    middle = panel[panel["excluded_middle"]].groupby("chooser_username_norm").agg(
        excluded_middle_kind_count=("kind_draw", "sum")
    )
    aggregate = aggregate.join([fair, worse, middle]).fillna(0)

    output: list[dict] = []
    for query_index, user in enumerate(users):
        a = aggregate.loc[user["username"]]
        group = int(user["group"])
        returned = not (user["username"] in {"fixture_kind_0079", "fixture_control_0078_3"})
        fair_kind = bool(a["fair_kind_count"] > 0)
        worse_kind = bool(a["clearly_worse_kind_count"] > 0)
        ever_kind = bool(a["total_kind_count"] > 0)
        patron = None
        if returned:
            if user["role"] == "kind" and fair_kind:
                patron = group % 4 == 0 or group % 9 == 0
            elif user["role"] == "kind" and worse_kind:
                patron = group % 17 == 1
            else:
                patron = (group * 3 + int(user["slot"])) % 29 == 0
        perfs = {
            "bullet": {"rating": int(a["mean_chooser_elo"] - 40), "games": 25 + group},
            "blitz": {"rating": int(a["mean_chooser_elo"]), "games": 100 + group},
            "rapid": {"rating": int(a["mean_chooser_elo"] + 30), "games": 60 + group},
        }
        output.append(
            {
                "query_index": query_index,
                "canonical_batch_index": 0,
                "username_norm": user["username"],
                "acquisition_role": user["role"],
                "matched_kind_chooser_id": user["matched_kind"],
                "control_slot": user["slot"],
                "selected_controls": 3,
                "nested_1to1_available": True,
                "exact_1to3_group": True,
                "total_opps": int(a["total_opps"]),
                "total_kind_count": int(a["total_kind_count"]),
                "fair_opps": int(a["fair_opps"]),
                "fair_kind_count": int(a["fair_kind_count"]),
                "clearly_worse_opps": int(a["clearly_worse_opps"]),
                "clearly_worse_kind_count": int(a["clearly_worse_kind_count"]),
                "excluded_middle_opps": int(a["excluded_middle_opps"]),
                "excluded_middle_kind_count": int(a["excluded_middle_kind_count"]),
                "mean_chooser_elo": float(a["mean_chooser_elo"]),
                "sd_chooser_elo": float(a["sd_chooser_elo"]),
                "chooser_elo_n": int(a["chooser_elo_n"]),
                "mean_draw_payoff_fair": float(a["mean_draw_payoff_fair"]),
                "mean_win_premium_fair": float(a["mean_win_premium_fair"]),
                "share_tournament": float(a["share_tournament"]),
                "first_opportunity_utc_ms": 1704067200000,
                "last_opportunity_utc_ms": 1706745600000,
                "active_months": int(a["active_months"]),
                "modal_speed_group": user["speed"],
                "modal_speed_opps": int(a["total_opps"]),
                "ever_kind_any_state": ever_kind,
                "ever_kind_fair_state": fair_kind,
                "ever_kind_clearly_worse_state": worse_kind,
                "fair_opp_bin": fair_bin(int(a["fair_opps"])),
                "total_opp_bin": "21_50",
                "historical_common_support_2_20": 2 <= int(a["fair_opps"]) <= 20,
                "match_cell": user["match_cell"],
                "batch_id": "fixture_batch_0001",
                "batch_index": 0,
                "request_position": query_index,
                "username_requested": user["username"],
                "returned": returned,
                "username_returned": user["username"] if returned else None,
                "queried_at_utc": "2026-08-26T22:00:00+00:00",
                "http_status": 200,
                "patron": patron,
                "patron_field_present": bool(patron) if returned else None,
                "patron_color": "blue" if patron else None,
                "title": "BOT" if user["username"] in {"fixture_kind_0004", "fixture_control_0004_1"} else None,
                "disabled": False if returned else None,
                "tos_violation": False if returned else None,
                "created_at_ms": 1400000000000 + group * 1000000 if returned else None,
                "seen_at_ms": 1787700000000 - group * 100000 if returned and group % 7 != 0 else None,
                "play_time_total_seconds": 10000 + group * 100 if returned and group % 11 != 0 else None,
                "count_all": 200 + group if returned else None,
                "count_rated": 180 + group if returned else None,
                "count_win": 90 + group // 2 if returned else None,
                "count_loss": 70 + group // 3 if returned else None,
                "count_draw": 20 + group // 4 if returned else None,
                "perfs_json": json.dumps(perfs, sort_keys=True) if returned else None,
            }
        )
    return pd.DataFrame(output)


def write_manifest(root: Path, filename: str, paths: list[Path], order: str) -> str:
    if order == "sha_first":
        lines = ["sha256\tbytes\tpath"]
        for path in paths:
            lines.append(f"{sha256_file(path)}\t{path.stat().st_size}\t{path.relative_to(root).as_posix()}")
    else:
        lines = ["sha256\tbytes\tpath"]
        for path in paths:
            lines.append(f"{sha256_file(path)}\t{path.stat().st_size}\t{path.relative_to(root).as_posix()}")
    target = root / filename
    atomic_write_text(target, "\n".join(lines) + "\n")
    return sha256_file(target)


def main() -> None:
    args = parse_args()
    verify_nullable_integer_fractional_median()
    root = args.fixture_root.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise RuntimeError(f"Synthetic fixture root must be new or empty: {root}")
    stage07_root = root / "derived/replication/analysis_panel_24m_sf100k"
    snapshot_root = root / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED"
    plan_root = root / "derived/replication/patron_profile_acquisition_24m_plan_v100"
    code_root = root / "replication_package/code"
    for path in [stage07_root, snapshot_root, plan_root, code_root]:
        path.mkdir(parents=True, exist_ok=True)

    panel, users = build_panel()
    snapshot = build_snapshot(panel, users)
    for month, frame in panel.groupby("month", sort=True):
        month_root = stage07_root / f"month={month}"
        month_root.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(month_root / "analysis_panel.parquet", index=False, compression="zstd")
    atomic_write_text(code_root / "07_build_analysis_panel.py", "# synthetic Stage 07 authority\n")
    atomic_write_json(
        stage07_root / "_SUCCESS.json",
        {
            "created_at": utc_now(),
            "status": "STAGE07_24M_CERTIFIED_OK",
            "script_sha256": sha256_file(code_root / "07_build_analysis_panel.py"),
            "global_qa": {
                "rows": len(panel),
                "months": int(panel["month"].nunique()),
                "kind_draws": int(panel["kind_draw"].sum()),
            },
        },
    )

    snapshot_path = snapshot_root / "profile_snapshot_24m_private_lossless.parquet"
    snapshot.to_parquet(snapshot_path, index=False, compression="zstd")
    coverage = snapshot.groupby("acquisition_role").agg(requested=("username_norm", "size"), returned=("returned", "sum"), patrons=("patron", "sum")).reset_index()
    coverage.to_csv(snapshot_root / "coverage_by_role.tsv", sep="\t", index=False)
    snapshot_manifest_sha = write_manifest(
        snapshot_root,
        "audit_file_hashes.tsv",
        [snapshot_path, snapshot_root / "coverage_by_role.tsv"],
        "sha_first",
    )
    atomic_write_json(
        snapshot_root / "_SUCCESS.json",
        {
            "created_utc": utc_now(),
            "status": "PROFILE_SNAPSHOT_24M_CERTIFIED_OK",
            "audit_file_hashes_sha256": snapshot_manifest_sha,
            "final_qa": {
                "normalized_rows": len(snapshot),
                "returned_profiles": int(snapshot["returned"].sum()),
                "unreturned_profiles": int((~snapshot["returned"]).sum()),
                "patrons": int(snapshot["patron"].fillna(False).sum()),
            },
        },
    )

    matching_rows = []
    for user in users:
        if user["role"] == "control":
            matching_rows.append(
                {
                    "kind_chooser_id": user["matched_kind"],
                    "control_chooser_id": user["username"],
                    "match_cell": user["match_cell"],
                    "kind_rank": int(user["group"] + 1),
                    "control_rank": int(user["group"] + 1 + (user["slot"] - 1) * 80),
                    "control_slot": int(user["slot"]),
                    "cell_exact_1to3_support": True,
                    "cell_exact_1to1_support": True,
                    "kind_ever_fair_kind": user["pattern"] != 1,
                    "kind_ever_clearly_worse_kind": user["pattern"] in {1, 2},
                }
            )
    matching_path = plan_root / "matching_pairs_1to3_private.parquet"
    pd.DataFrame(matching_rows).to_parquet(matching_path, index=False, compression="zstd")
    plan_manifest_sha = write_manifest(plan_root, "plan_file_hashes.tsv", [matching_path], "sha_first")
    atomic_write_json(
        plan_root / "_SUCCESS.json",
        {
            "created_utc": utc_now(),
            "status": "PROFILE_ACQUISITION_PLAN_CERTIFIED_OK",
            "plan_file_hashes_sha256": plan_manifest_sha,
        },
    )
    print("PATRON_STAGE10_SYNTHETIC_FIXTURE_OK")
    print(root)


if __name__ == "__main__":
    main()
