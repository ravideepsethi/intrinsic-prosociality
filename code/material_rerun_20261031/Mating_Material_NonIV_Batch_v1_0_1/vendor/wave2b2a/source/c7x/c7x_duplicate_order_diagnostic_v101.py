#!/usr/bin/env python3
"""Outcome-blind duplicate-order diagnostic for Campaign 1 C7X v1.0.1.

The failed v1.0.0 package treated every repeated (timestamp, archive ordinal)
within an oriented pair as a fatal duplicate.  The original C7 ordering rule,
however, was lexicographic in timestamp, archive ordinal, and game ID.  This
module classifies the collisions before any focal kindness outcome is read and
selects the only permitted recovery branch.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

import campaign1_nonprofile_common_v102 as common


SCRIPT_VERSION = "1.0.1"
BRANCH_TIEBREAK = "LEXICOGRAPHIC_UTC_ARCHIVE_GAME_ID"
BRANCH_NO_COLLISIONS = "UTC_ARCHIVE_UNIQUE_GAME_ID_TIEBREAK_DORMANT"


def diagnose(
    connection: Any,
    prior_path: Path,
    *,
    known_rows: int | None = None,
    known_unique_game_ids: int | None = None,
    known_null_total_order_fields: int | None = None,
) -> dict[str, Any]:
    """Return aggregate collision facts and a fail-closed branch decision."""
    literal = common.sql_literal(prior_path)
    row = connection.execute(
        f"""
        WITH collision_groups AS (
          SELECT
            low_id, high_id, prior_chooser_id, prior_disconnected_id,
            event_order,
            COUNT(*) AS group_rows,
            COUNT(DISTINCT prior_game_id) AS distinct_game_ids,
            COUNT(DISTINCT prior_arm) AS distinct_arms
          FROM read_parquet({literal})
          GROUP BY ALL
          HAVING COUNT(*) > 1
        )
        SELECT
          COUNT(*) AS collision_groups,
          COALESCE(SUM(group_rows), 0) AS rows_in_collision_groups,
          COALESCE(SUM(group_rows - 1), 0) AS excess_rows,
          COALESCE(MAX(group_rows), 0) AS maximum_group_rows,
          COUNT(*) FILTER (
            WHERE distinct_game_ids <> group_rows
          ) AS groups_with_repeated_game_ids,
          COUNT(*) FILTER (WHERE distinct_arms > 1) AS mixed_arm_groups
        FROM collision_groups
        """
    ).fetchone()
    if (
        known_rows is None
        or known_unique_game_ids is None
        or known_null_total_order_fields is None
    ):
        total = connection.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT prior_game_id),
              COUNT(*) FILTER (
                WHERE prior_utc_ms IS NULL
                   OR prior_archive_ordinal IS NULL
                   OR prior_game_id IS NULL
              )
            FROM read_parquet({literal})
            """
        ).fetchone()
        known_rows = int(total[0])
        known_unique_game_ids = int(total[1])
        known_null_total_order_fields = int(total[2])
    payload = {
        "status": "C7X_DUPLICATE_ORDER_DIAGNOSTIC_COMPLETE",
        "script_version": SCRIPT_VERSION,
        "focal_kind_outcome_read": False,
        "prior_rows": int(known_rows),
        "unique_prior_game_ids": int(known_unique_game_ids),
        "null_total_order_fields": int(known_null_total_order_fields),
        "duplicate_source_order_groups": int(row[0]),
        "rows_in_duplicate_source_order_groups": int(row[1]),
        "duplicate_source_order_excess_rows": int(row[2]),
        "maximum_duplicate_group_rows": int(row[3]),
        "groups_with_repeated_game_ids": int(row[4]),
        "mixed_mercy_claim_groups": int(row[5]),
        "v100_failure_reproduced_as_source_order_collisions": int(row[0]) > 0,
        "total_order_rule": ["utc_ms", "archive_ordinal", "game_id"],
        "game_id_direction": "ascending; latest prior is lexicographic maximum",
        "tie_dependent_sensitivity": (
            "exclude focal rows sharing the source key with an eligible prior "
            "or whose selected prior belongs to a duplicate source-key group"
        ),
        "causal_claim": False,
        "epistemic_label": "X",
    }
    if payload["prior_rows"] <= 0:
        raise RuntimeError("C7X duplicate-order diagnostic found no prior rows")
    if payload["prior_rows"] != payload["unique_prior_game_ids"]:
        raise RuntimeError(
            "C7X diagnostic found repeated game IDs; deterministic recovery is forbidden"
        )
    if payload["null_total_order_fields"]:
        raise RuntimeError("C7X diagnostic found null total-order fields")
    if payload["groups_with_repeated_game_ids"]:
        raise RuntimeError("C7X collision groups contain repeated game IDs")
    payload["selected_recovery_branch"] = (
        BRANCH_TIEBREAK
        if payload["duplicate_source_order_groups"]
        else BRANCH_NO_COLLISIONS
    )
    payload["branch_authorized"] = True
    return payload


def self_test() -> None:
    duckdb, _, _, _ = common.import_dependencies()
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE prior(
          low_id BIGINT, high_id BIGINT, prior_chooser_id BIGINT,
          prior_disconnected_id BIGINT, event_order HUGEINT,
          prior_utc_ms BIGINT, prior_archive_ordinal BIGINT,
          prior_game_id VARCHAR, prior_arm TINYINT
        );
        INSERT INTO prior VALUES
          (1,2,2,1,10001,100,1,'a',1),
          (1,2,2,1,10001,100,1,'b',0),
          (1,2,2,1,20002,200,2,'c',1);
        """
    )
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "prior.parquet"
        connection.execute(
            f"COPY prior TO {common.sql_literal(path)} (FORMAT PARQUET)"
        )
        result = diagnose(connection, path)
    connection.close()
    if (
        result["duplicate_source_order_groups"] != 1
        or result["rows_in_duplicate_source_order_groups"] != 2
        or result["selected_recovery_branch"] != BRANCH_TIEBREAK
    ):
        raise RuntimeError(f"C7X duplicate-order diagnostic self-test failed: {result}")
    print("C7X_DUPLICATE_ORDER_DIAGNOSTIC_SELF_TEST_OK", flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test:
        raise SystemExit("This module is called by the authenticated C7X runner")
    self_test()


if __name__ == "__main__":
    main()
