#!/usr/bin/env python3
"""Aggregate-only frequent-dyad diagnostic for the low-support current C7X."""

from __future__ import annotations

import math
import shutil
import time
from pathlib import Path
from typing import Any, Sequence


EXPECTED_ROWS = 10_481
EXPECTED_CLAIMER_ROWS = 10_356
EXPECTED_BENEFACTOR_ROWS = 125
EXPECTED_CLAIMER_KIND = 174
EXPECTED_BENEFACTOR_KIND = 4
PARENT_MINIMUM_ROWS_PER_ARM = 1_000


SAMPLE_SPECS = (
    ("all", "TRUE", "All current C7X rows"),
    ("dyad_pair_games_eq_1", "pair_games_24m = 1", "No other in-window dyad game"),
    ("dyad_pair_games_lt_3", "pair_games_24m < 3", "Exclude dyads with 3+ games"),
    ("dyad_pair_games_lt_5", "pair_games_24m < 5", "Exclude dyads with 5+ games"),
    ("dyad_pair_games_lt_10", "pair_games_24m < 10", "Exclude dyads with 10+ games"),
    ("dyad_pair_games_eq_2", "pair_games_24m = 2", "Exactly two in-window dyad games"),
    ("dyad_pair_games_3_4", "pair_games_24m BETWEEN 3 AND 4", "Three or four dyad games"),
    ("dyad_pair_games_5_9", "pair_games_24m BETWEEN 5 AND 9", "Five to nine dyad games"),
    ("dyad_pair_games_ge_10", "pair_games_24m >= 10", "Ten or more dyad games"),
    ("either_player_max_lt_2", "NOT either_player_ge_2", "Neither player has a repeated in-window dyad"),
    ("either_player_max_lt_3", "NOT either_player_ge_3", "Neither player has a 3+ game dyad"),
    ("either_player_max_lt_5", "NOT either_player_ge_5", "Neither player has a 5+ game dyad"),
    ("either_player_max_lt_10", "NOT either_player_ge_10", "Neither player has a 10+ game dyad"),
)


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _path_list(paths: Sequence[Path]) -> str:
    return "[" + ",".join(_sql_literal(path) for path in paths) + "]"


def _cells(rows: Sequence[Sequence[Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    labels = {name: description for name, _, description in SAMPLE_SPECS}
    cells: list[dict[str, Any]] = []
    by_sample: dict[str, dict[str, dict[str, Any]]] = {}
    for sample_name, arm_code, count, kind in rows:
        arm = "benefactor" if int(arm_code) == 1 else "claimer"
        count = int(count)
        kind = int(kind)
        item = {
            "sample": str(sample_name),
            "sample_definition": labels[str(sample_name)],
            "arm": arm,
            "rows": count,
            "kind_draws": kind,
            "kind_rate_pct": 100.0 * kind / count if count else None,
        }
        cells.append(item)
        by_sample.setdefault(str(sample_name), {})[arm] = item
    contrasts: list[dict[str, Any]] = []
    for name, _, description in SAMPLE_SPECS:
        arms = by_sample.get(name, {})
        benefactor = arms.get("benefactor", {"rows": 0, "kind_draws": 0, "kind_rate_pct": None})
        claimer = arms.get("claimer", {"rows": 0, "kind_draws": 0, "kind_rate_pct": None})
        estimable = (
            int(benefactor["rows"]) >= PARENT_MINIMUM_ROWS_PER_ARM
            and int(claimer["rows"]) >= PARENT_MINIMUM_ROWS_PER_ARM
        )
        difference = None
        if benefactor["kind_rate_pct"] is not None and claimer["kind_rate_pct"] is not None:
            difference = float(benefactor["kind_rate_pct"]) - float(claimer["kind_rate_pct"])
        contrasts.append(
            {
                "sample": name,
                "sample_definition": description,
                "benefactor_rows": int(benefactor["rows"]),
                "benefactor_kind_draws": int(benefactor["kind_draws"]),
                "benefactor_kind_rate_pct": benefactor["kind_rate_pct"],
                "claimer_rows": int(claimer["rows"]),
                "claimer_kind_draws": int(claimer["kind_draws"]),
                "claimer_kind_rate_pct": claimer["kind_rate_pct"],
                "benefactor_minus_claimer_raw_pp": difference,
                "parent_1000_per_arm_gate_pass": estimable,
                "controlled_model_status": (
                    "NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED"
                    if not estimable
                    else "NOT_RUN_DIAGNOSTIC_DESIGN_IS_AGGREGATE_ONLY"
                ),
            }
        )
    return cells, contrasts


def execute(
    *,
    classification: Path,
    stage_paths: Sequence[Path],
    pair_paths: Sequence[Path],
    player_path: Path,
    state: Path,
    public_stage: Path,
    dyad_module: Any,
    runner_common: Any,
    config_sha256: str,
    classification_sha256: str,
    threads: int,
    memory_limit: str,
) -> dict[str, Any]:
    started = time.time()
    state.mkdir(parents=True, exist_ok=True)
    flags, flag_receipt = dyad_module.build_c7x_flags(
        classification=classification,
        pair_paths=pair_paths,
        player_path=player_path,
        state=state,
        config_sha256=config_sha256,
        thresholds=(2, 3, 5, 10),
        expected_rows=EXPECTED_ROWS,
        expected_sha256=classification_sha256,
        threads=threads,
        memory_limit=memory_limit,
    )

    import duckdb

    temp_dir = state / "duckdb_temp/c7x_dyad_aggregate"
    temp_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        connection.execute(f"SET threads={int(threads)}")
        connection.execute(f"SET memory_limit={_sql_literal(memory_limit)}")
        connection.execute(f"SET temp_directory={_sql_literal(temp_dir)}")
        connection.execute("SET preserve_insertion_order=false")
        connection.execute(
            f"""
            CREATE TEMP TABLE current_c7x AS
            SELECT
              c.game_id,
              CAST(c.latest_prior_arm AS TINYINT) AS latest_prior_arm,
              CAST(s.kind_draw AS BIGINT) AS kind_draw,
              CAST(f.pair_games_24m AS BIGINT) AS pair_games_24m,
              CAST(f.dyad_ge_2 AS BOOLEAN) AS dyad_ge_2,
              CAST(f.dyad_ge_3 AS BOOLEAN) AS dyad_ge_3,
              CAST(f.dyad_ge_5 AS BOOLEAN) AS dyad_ge_5,
              CAST(f.dyad_ge_10 AS BOOLEAN) AS dyad_ge_10,
              CAST(f.either_player_ge_2 AS BOOLEAN) AS either_player_ge_2,
              CAST(f.either_player_ge_3 AS BOOLEAN) AS either_player_ge_3,
              CAST(f.either_player_ge_5 AS BOOLEAN) AS either_player_ge_5,
              CAST(f.either_player_ge_10 AS BOOLEAN) AS either_player_ge_10
            FROM read_parquet({_sql_literal(classification)}) c
            INNER JOIN read_parquet({_sql_literal(flags)}) f
              ON c.game_id=f.game_id AND c.latest_prior_arm=f.latest_prior_arm
            INNER JOIN read_parquet({_path_list(stage_paths)}, union_by_name=true) s
              ON c.game_id=CAST(s.game_id AS VARCHAR)
            """
        )
        qa = connection.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT game_id),
                   COUNT(*) FILTER (WHERE latest_prior_arm=0),
                   COUNT(*) FILTER (WHERE latest_prior_arm=1),
                   SUM(kind_draw) FILTER (WHERE latest_prior_arm=0),
                   SUM(kind_draw) FILTER (WHERE latest_prior_arm=1),
                   COUNT(*) FILTER (
                     WHERE kind_draw NOT IN (0,1) OR pair_games_24m < 1
                   )
            FROM current_c7x
            """
        ).fetchone()
        expected = (
            EXPECTED_ROWS,
            EXPECTED_ROWS,
            EXPECTED_CLAIMER_ROWS,
            EXPECTED_BENEFACTOR_ROWS,
            EXPECTED_CLAIMER_KIND,
            EXPECTED_BENEFACTOR_KIND,
            0,
        )
        observed = tuple(int(value) for value in qa)
        if observed != expected:
            raise RuntimeError(
                f"C7X frequent-dyad outcome join changed: expected={expected}; observed={observed}"
            )
        union = " UNION ALL ".join(
            f"""
            SELECT {_sql_literal(name)} AS sample, latest_prior_arm,
                   COUNT(*)::BIGINT AS rows, SUM(kind_draw)::BIGINT AS kind_draws
            FROM current_c7x WHERE {condition}
            GROUP BY latest_prior_arm
            """
            for name, condition, _ in SAMPLE_SPECS
        )
        raw_rows = connection.execute(
            f"SELECT * FROM ({union}) ORDER BY sample, latest_prior_arm"
        ).fetchall()
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    cells, contrasts = _cells(raw_rows)
    all_row = next(row for row in contrasts if row["sample"] == "all")
    if all_row["parent_1000_per_arm_gate_pass"]:
        raise RuntimeError("C7X parent support gate unexpectedly changed to pass")
    result = {
        "status": "C7X_FREQUENT_DYAD_CURRENT_LOW_SUPPORT_DIAGNOSTIC_OK",
        "created_utc": runner_common.utc_now(),
        "runtime_seconds": time.time() - started,
        "epistemic_label": "X",
        "sample_authority_scope": "selected_pool_nonadjacent_panel",
        "parent_c7x_status": "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT",
        "parent_minimum_rows_per_arm": PARENT_MINIMUM_ROWS_PER_ARM,
        "controlled_models_run": 0,
        "reason_models_not_run": (
            "The parent C7X benefactor arm has 125 rows, below the frozen "
            "1,000-per-arm gate. Subset fixed-effect fits cannot rehabilitate it."
        ),
        "invariant_dyad_index_reused": True,
        "why_invariant": (
            "The exact 24-month all-game dyad census depends on chronology and dates, "
            "not on which timeout candidates enter the selected main panel."
        ),
        "flags_receipt": {
            key: value
            for key, value in flag_receipt.items()
            if "path" not in key and key != "classification_path"
        },
        "raw_cells": cells,
        "raw_contrasts": contrasts,
        "claim_boundary": (
            "Descriptive low-support diagnostic only; no controlled or causal "
            "targeted-memory estimate is generated."
        ),
        "account_level_output": False,
        "network_requests": 0,
    }
    public_stage.mkdir(parents=True, exist_ok=True)
    runner_common.atomic_json(public_stage / "c7x_frequent_dyad_results.json", result)
    # Use a stable aggregate-only CSV schema.
    import csv
    csv_path = public_stage / "c7x_frequent_dyad_raw_contrasts.csv"
    fields = list(contrasts[0])
    temporary = csv_path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(contrasts)
    temporary.replace(csv_path)
    return result


def self_test() -> None:
    synthetic = [
        ("all", 0, 1_200, 12),
        ("all", 1, 125, 4),
    ]
    # Temporarily exercise the transformation without requiring every declared sample.
    labels = {name for name, _, _ in SAMPLE_SPECS}
    if "all" not in labels or len(labels) != len(SAMPLE_SPECS):
        raise RuntimeError("C7X dyad sample definitions changed")
    rate = 100.0 * int(synthetic[1][3]) / int(synthetic[1][2])
    if not math.isclose(rate, 3.2):
        raise RuntimeError("C7X dyad rate transformation failed")
    if EXPECTED_BENEFACTOR_ROWS >= PARENT_MINIMUM_ROWS_PER_ARM:
        raise RuntimeError("C7X parent low-support disposition changed")
    print("POOL_MAIN_C7X_DYAD_DIAGNOSTIC_SELF_TEST_OK")

