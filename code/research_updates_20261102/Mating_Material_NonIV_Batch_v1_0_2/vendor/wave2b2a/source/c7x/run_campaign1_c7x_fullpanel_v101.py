#!/usr/bin/env python3
"""Full-Stage-07 exploratory direct-reciprocity extension (C7X).

This is deliberately separate from the prespecified C7 2% pair-cluster
analysis.  It freezes and validates all exposure classifications before
joining the focal kindness outcome, uses compressed Parquet checkpoints, and
retains every attempted estimate regardless of sign or estimability.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import shutil
import time
import traceback
from typing import Any, Mapping, Sequence
import uuid

import campaign1_nonprofile_common_v102 as common
import c7x_duplicate_order_diagnostic_v101 as order_diagnostic


SCRIPT_VERSION = "1.0.1"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
STAGE07_RELATIVE = Path("derived/replication/analysis_panel_24m_sf100k")
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_FAIR_ROWS = 17_328_130
PAIR_SEED = 2_026_082_203
PAIR_SAMPLE_DENOMINATOR = 50
DAY_MS = 86_400_000
ORDER_MULTIPLIER = 10_000_000_000
MINIMUM_FREE_BYTES = 20 * 1024**3
OUTPUT_NAME = "dynamics_campaign1_c7x_fullpanel_v101"
STATE_NAME = "dynamics_campaign1_c7x_fullpanel_v101_PRIVATE"
PRIMARY_MODEL = "X_C7X_latest_reversed_arm_chooser_ply_fe_chooser_cluster"
LEGACY_PLANNED_MODEL = "X_C7X_latest_reversed_arm_chooser_fe_chooser_cluster"
EXPECTED_MODEL_NAMES = (
    PRIMARY_MODEL,
    LEGACY_PLANNED_MODEL,
    "X_C7X_latest_reversed_arm_chooser_ply_fe_pair_cluster",
    "X_C7X_latest_reversed_arm_pooled_ply_adjusted_chooser_cluster",
    "X_C7X_latest_reversed_arm_same_speed_chooser_ply_fe",
    "X_C7X_any_prior_arm_exclusive_histories_chooser_ply_fe",
    "X_C7X_latest_reversed_arm_tie_independent_chooser_ply_fe",
    "X_C7X_latest_reversed_arm_ply_gt10_chooser_ply_fe",
    "X_C7X_latest_reversed_arm_nontournament_chooser_ply_fe",
    "X_C7X_latest_reversed_arm_le7d_chooser_ply_fe",
    "X_C7X_latest_reversed_arm_le30d_chooser_ply_fe",
    "X_C7X_latest_reversed_arm_le180d_chooser_ply_fe",
    "X_C7X_latest_reversed_arm_le365d_chooser_ply_fe",
)
OLD_SAMPLE_EXPECTED = {
    "latest_benefactor": 33,
    "latest_claimer": 557,
    "same_speed_benefactor": 29,
    "same_speed_claimer": 534,
    "exclusive_benefactor_only": 28,
    "exclusive_claimer_only": 543,
    "conflicting_histories": 19,
}
OLD_OUTCOME_EXPECTED = {
    "benefactor_rows": 33,
    "benefactor_kind_draws": 12,
    "claimer_rows": 557,
    "claimer_kind_draws": 25,
}


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--execution-pointer", type=Path)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="16GB")
    return parser.parse_args(argv)


def finite(value: Any) -> Any:
    """Convert NumPy scalars and non-finite floats to public JSON values."""
    if isinstance(value, Mapping):
        return {str(key): finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(item) for item in value]
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def ply_band_sql(field: str) -> str:
    """The eight frozen bands used by the certified equality/FEN audit."""
    return f"""
      CASE
        WHEN CAST({field} AS BIGINT) <= 4 THEN 0
        WHEN CAST({field} AS BIGINT) <= 6 THEN 1
        WHEN CAST({field} AS BIGINT) <= 8 THEN 2
        WHEN CAST({field} AS BIGINT) <= 10 THEN 3
        WHEN CAST({field} AS BIGINT) <= 20 THEN 4
        WHEN CAST({field} AS BIGINT) <= 40 THEN 5
        WHEN CAST({field} AS BIGINT) <= 80 THEN 6
        ELSE 7
      END
    """.strip()


def authenticate_package(root: Path) -> list[dict[str, Any]]:
    manifest = root / "PACKAGE_CONTENTS.sha256"
    if not manifest.is_file():
        raise RuntimeError("Package manifest is missing")
    rows: list[dict[str, Any]] = []
    listed: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, raw_path = line.split(maxsplit=1)
        relative = raw_path.lstrip("* ")
        if relative.startswith("./"):
            relative = relative[2:]
        path = root / relative
        if not path.is_file() or common.sha256_file(path) != expected:
            raise RuntimeError(f"Packaged file authentication failed: {relative}")
        rows.append(
            {
                "file": relative,
                "bytes": path.stat().st_size,
                "sha256": expected,
            }
        )
        listed.add(relative)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    if listed != actual:
        raise RuntimeError(
            "Package manifest path set changed: "
            f"missing={sorted(actual-listed)} extra={sorted(listed-actual)}"
        )
    return rows


def parquet_checkpoint(
    *, output: Path, receipt: Path, config_sha256: str, status: str,
    expected_rows: int | None = None,
) -> dict[str, Any] | None:
    _, _, _, pq = common.import_dependencies()
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial private checkpoint exists: {output.name}")
    saved = common.load_json(receipt)
    actual_rows = int(pq.ParquetFile(output).metadata.num_rows)
    checks = {
        "status": status,
        "config_sha256": config_sha256,
        "output_rows": actual_rows,
        "output_bytes": output.stat().st_size,
        "output_sha256": common.sha256_file(output),
    }
    if expected_rows is not None and actual_rows != expected_rows:
        raise RuntimeError(f"Checkpoint row authority changed: {output.name}")
    for key, value in checks.items():
        if saved.get(key) != value:
            raise RuntimeError(f"Private checkpoint mismatch: {output.name} {key}")
    return saved


def checkpoint_receipt(
    *, output: Path, config_sha256: str, status: str,
    qa: Mapping[str, Any],
) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    payload = {
        "status": status,
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": common.sha256_file(output),
        "qa": finite(dict(qa)),
        "privacy": "PRIVATE ROW-LEVEL PARQUET; DO NOT PUBLISH",
    }
    return payload


def build_prior_arms(
    *, stage_paths: Sequence[Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c7x_prior_arms_private.parquet"
    receipt = state / "c7x_prior_arms_receipt.json"
    saved = parquet_checkpoint(
        output=output,
        receipt=receipt,
        config_sha256=config_sha256,
        status="C7X_PRIOR_ARMS_PRIVATE_OK",
    )
    if saved is not None:
        print("C7X_PRIOR_ARMS_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved

    print("C7X_PRIOR_ARMS_BUILD_BEGIN", flush=True)
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/prior_arms",
    )
    speed = common.speed_code_sql("p.api_speed")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH raw AS (
          SELECT
            LEAST(CAST(p.chooser_user_id AS BIGINT),
                  CAST(p.disconnected_user_id AS BIGINT)) AS low_id,
            GREATEST(CAST(p.chooser_user_id AS BIGINT),
                     CAST(p.disconnected_user_id AS BIGINT)) AS high_id,
            CAST(p.chooser_user_id AS BIGINT) AS prior_chooser_id,
            CAST(p.disconnected_user_id AS BIGINT) AS prior_disconnected_id,
            CAST(p.utc_ms AS BIGINT) AS prior_utc_ms,
            CAST(p.archive_ordinal AS BIGINT) AS prior_archive_ordinal,
            (CAST(p.utc_ms AS HUGEINT) * {ORDER_MULTIPLIER}
             + CAST(p.archive_ordinal AS HUGEINT)) AS event_order,
            CAST(p.game_id AS VARCHAR) AS prior_game_id,
            CAST({speed} AS INTEGER) AS prior_speed_code,
            CAST(CASE WHEN CAST(p.kind_draw AS BOOLEAN) THEN 1 ELSE 0 END
                 AS TINYINT) AS prior_arm,
            CAST(
              CAST(p.kind_draw AS BOOLEAN)
              AND CAST(p.timeout_chooser_win AS BOOLEAN)
              AS BOOLEAN
            ) AS prior_arm_overlap
          FROM read_parquet(
            {common.path_list_literal(stage_paths)}, union_by_name=true
          ) p
          WHERE p.chooser_user_id IS NOT NULL
            AND p.disconnected_user_id IS NOT NULL
            AND p.utc_ms IS NOT NULL
            AND p.archive_ordinal IS NOT NULL
            AND (
              CAST(p.kind_draw AS BOOLEAN)
              OR CAST(p.timeout_chooser_win AS BOOLEAN)
            )
          )
          SELECT raw.*,
            CAST(COUNT(*) OVER (
              PARTITION BY low_id, high_id, prior_chooser_id,
                           prior_disconnected_id, event_order
            ) AS INTEGER) AS prior_source_order_multiplicity
          FROM raw
          ORDER BY low_id, high_id, prior_chooser_id,
                   prior_disconnected_id, event_order, prior_game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa_row = connection.execute(
        f"""
        SELECT
          COUNT(*) AS rows,
          COUNT(DISTINCT prior_game_id) AS unique_games,
          COUNT(*) FILTER (WHERE prior_arm=1) AS mercy_rows,
          COUNT(*) FILTER (WHERE prior_arm=0) AS claim_rows,
          COUNT(*) FILTER (WHERE prior_arm_overlap) AS overlap_rows,
          COUNT(*) FILTER (WHERE prior_arm NOT IN (0,1)) AS bad_arm_rows,
          COUNT(*) FILTER (
            WHERE low_id IS NULL OR high_id IS NULL
               OR prior_chooser_id IS NULL OR prior_disconnected_id IS NULL
               OR event_order IS NULL OR prior_game_id IS NULL
          ) AS null_key_rows
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    diagnostic = order_diagnostic.diagnose(
        connection,
        temporary,
        known_rows=int(qa_row[0]),
        known_unique_game_ids=int(qa_row[1]),
        known_null_total_order_fields=int(qa_row[6]),
    )
    connection.close()
    qa = {
        "rows": int(qa_row[0]),
        "unique_games": int(qa_row[1]),
        "mercy_rows": int(qa_row[2]),
        "claim_rows": int(qa_row[3]),
        "overlap_rows": int(qa_row[4]),
        "bad_arm_rows": int(qa_row[5]),
        "null_key_rows": int(qa_row[6]),
        "rows_in_duplicate_pair_role_order_keys": diagnostic[
            "rows_in_duplicate_source_order_groups"
        ],
        "maximum_source_order_multiplicity": diagnostic[
            "maximum_duplicate_group_rows"
        ],
        "duplicate_order_diagnostic": diagnostic,
    }
    if (
        qa["rows"] <= 0
        or qa["rows"] != qa["unique_games"]
        or qa["mercy_rows"] + qa["claim_rows"] != qa["rows"]
        or qa["overlap_rows"]
        or qa["bad_arm_rows"]
        or qa["null_key_rows"]
        or not diagnostic["branch_authorized"]
    ):
        raise RuntimeError(f"C7X prior-arm row conservation failed: {qa}")
    os.replace(temporary, output)
    saved = checkpoint_receipt(
        output=output,
        config_sha256=config_sha256,
        status="C7X_PRIOR_ARMS_PRIVATE_OK",
        qa=qa,
    )
    common.atomic_json(receipt, saved)
    print(
        "C7X_PRIOR_ARMS_BUILD_OK "
        f"rows={qa['rows']:,} mercy={qa['mercy_rows']:,} "
        f"claim={qa['claim_rows']:,} "
        f"duplicate_groups={diagnostic['duplicate_source_order_groups']:,} "
        f"branch={diagnostic['selected_recovery_branch']}",
        flush=True,
    )
    return output, saved


def build_fair_focal(
    *, stage_paths: Sequence[Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c7x_fair_focal_private.parquet"
    receipt = state / "c7x_fair_focal_receipt.json"
    saved = parquet_checkpoint(
        output=output,
        receipt=receipt,
        config_sha256=config_sha256,
        status="C7X_FAIR_FOCAL_PRIVATE_OK",
        expected_rows=EXPECTED_FAIR_ROWS,
    )
    if saved is not None:
        forbidden = {"kind_draw", "outcome_kind_draw"}.intersection(
            pq.ParquetFile(output).schema_arrow.names
        )
        if forbidden:
            raise RuntimeError(f"Focal-outcome fields entered C7X focal cache: {forbidden}")
        print("C7X_FAIR_FOCAL_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved

    print("C7X_FAIR_FOCAL_BUILD_BEGIN", flush=True)
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/fair_focal",
    )
    speed = common.speed_code_sql("s.api_speed")
    eval_bin = common.eval_bin_sql("s.engine_eval_cp_disconnected")
    hour_week = common.hour_of_week_sql("s.api_last_move_at_ms")
    ply_band = ply_band_sql("s.ply_count")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT
            CAST(s.game_id AS VARCHAR) AS game_id,
            LEAST(CAST(s.chooser_user_id AS BIGINT),
                  CAST(s.disconnected_user_id AS BIGINT)) AS low_id,
            GREATEST(CAST(s.chooser_user_id AS BIGINT),
                     CAST(s.disconnected_user_id AS BIGINT)) AS high_id,
            CAST(s.chooser_user_id AS BIGINT) AS chooser_id,
            CAST(s.disconnected_user_id AS BIGINT) AS opponent_id,
            CAST(s.utc_ms AS BIGINT) AS focal_utc_ms,
            CAST(s.archive_ordinal AS BIGINT) AS focal_archive_ordinal,
            (CAST(s.utc_ms AS HUGEINT) * {ORDER_MULTIPLIER}
             + CAST(s.archive_ordinal AS HUGEINT)) AS event_order,
            CAST({speed} AS INTEGER) AS speed_code,
            CAST({eval_bin} AS INTEGER) AS eval_bin,
            CAST(date_diff(
              'month', DATE '2023-11-01',
              strptime(s.month || '-01', '%Y-%m-%d')
            ) AS INTEGER) AS month_code,
            CAST({hour_week} AS INTEGER) AS hour_of_week,
            CAST(s.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
            CAST(s.chooser_win_premium_v2 AS DOUBLE) AS win_premium,
            CAST(s.chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock,
            CAST(s.disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock,
            CAST(s.chooser_elo AS DOUBLE) AS chooser_elo,
            CAST(s.disconnected_elo AS DOUBLE) AS opponent_elo,
            CAST(s.chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
            CAST(s.disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
            CAST(s.tournament_like_event AS DOUBLE) AS tournament,
            CAST(s.ply_count AS BIGINT) AS ply_count,
            CAST({ply_band} AS INTEGER) AS ply_band,
            CAST(hash(CAST(s.game_id AS VARCHAR))
                 % 9223372036854775807 AS BIGINT) AS row_hash,
            CAST(hash(
              LEAST(CAST(s.chooser_user_id AS BIGINT),
                    CAST(s.disconnected_user_id AS BIGINT)),
              GREATEST(CAST(s.chooser_user_id AS BIGINT),
                       CAST(s.disconnected_user_id AS BIGINT))
            ) % 9223372036854775807 AS BIGINT) AS pair_hash
          FROM read_parquet(
            {common.path_list_literal(stage_paths)}, union_by_name=true
          ) s
          WHERE CAST(s.fair_competitive AS BOOLEAN)
          ORDER BY low_id, high_id, chooser_id, opponent_id,
                   event_order, game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa_row = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
          COUNT(*) FILTER (
            WHERE low_id IS NULL OR high_id IS NULL
               OR chooser_id IS NULL OR opponent_id IS NULL
               OR event_order IS NULL OR ply_count IS NULL
          )
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    schema_names = set(pq.ParquetFile(temporary).schema_arrow.names)
    forbidden = {"kind_draw", "outcome_kind_draw"}.intersection(schema_names)
    qa = {
        "rows": int(qa_row[0]),
        "unique_games": int(qa_row[1]),
        "null_key_rows": int(qa_row[2]),
        "focal_outcome_columns_present": sorted(forbidden),
    }
    if (
        qa["rows"] != EXPECTED_FAIR_ROWS
        or qa["unique_games"] != EXPECTED_FAIR_ROWS
        or qa["null_key_rows"]
        or forbidden
    ):
        raise RuntimeError(f"C7X fair-focal row conservation failed: {qa}")
    os.replace(temporary, output)
    saved = checkpoint_receipt(
        output=output,
        config_sha256=config_sha256,
        status="C7X_FAIR_FOCAL_PRIVATE_OK",
        qa=qa,
    )
    common.atomic_json(receipt, saved)
    print(f"C7X_FAIR_FOCAL_BUILD_OK rows={qa['rows']:,}", flush=True)
    return output, saved


def build_latest_arm(
    *, focal: Path, prior: Path, state: Path, threads: int,
    memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c7x_latest_reversed_arm_private.parquet"
    receipt = state / "c7x_latest_reversed_arm_receipt.json"
    saved = parquet_checkpoint(
        output=output,
        receipt=receipt,
        config_sha256=config_sha256,
        status="C7X_LATEST_REVERSED_ARM_PRIVATE_OK",
    )
    if saved is not None:
        forbidden = {"kind_draw", "outcome_kind_draw"}.intersection(
            pq.ParquetFile(output).schema_arrow.names
        )
        if forbidden:
            raise RuntimeError("Focal outcome entered latest-arm checkpoint")
        print("C7X_LATEST_REVERSED_ARM_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved

    print("C7X_LATEST_REVERSED_ARM_ASOF_BEGIN", flush=True)
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/latest_arm",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT
            f.*,
            p.prior_arm AS latest_prior_arm,
            p.prior_speed_code AS latest_prior_speed_code,
            p.prior_utc_ms AS latest_prior_utc_ms,
            p.prior_archive_ordinal AS latest_prior_archive_ordinal,
            p.prior_game_id AS latest_prior_game_id,
            p.prior_source_order_multiplicity AS
              latest_prior_source_order_multiplicity,
            CAST(EXISTS (
              SELECT 1
              FROM read_parquet({common.sql_literal(prior)}) px
              WHERE f.low_id = px.low_id
                AND f.high_id = px.high_id
                AND f.opponent_id = px.prior_chooser_id
                AND f.chooser_id = px.prior_disconnected_id
                AND f.event_order = px.event_order
            ) AS BOOLEAN) AS focal_source_order_tied_with_prior
          FROM read_parquet({common.sql_literal(focal)}) f
          ASOF JOIN read_parquet({common.sql_literal(prior)}) p
            ON f.low_id = p.low_id
           AND f.high_id = p.high_id
           AND f.opponent_id = p.prior_chooser_id
           AND f.chooser_id = p.prior_disconnected_id
           AND ROW(f.focal_utc_ms, f.focal_archive_ordinal, f.game_id)
               > ROW(p.prior_utc_ms, p.prior_archive_ordinal, p.prior_game_id)
          ORDER BY f.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa_row = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
          COUNT(*) FILTER (WHERE latest_prior_arm=1),
          COUNT(*) FILTER (WHERE latest_prior_arm=0),
          COUNT(*) FILTER (WHERE latest_prior_arm NOT IN (0,1)),
          COUNT(*) FILTER (
            WHERE ROW(latest_prior_utc_ms, latest_prior_archive_ordinal,
                      latest_prior_game_id)
               >= ROW(focal_utc_ms, focal_archive_ordinal, game_id)
          ),
          COUNT(*) FILTER (
            WHERE latest_prior_source_order_multiplicity > 1
          ),
          COUNT(*) FILTER (WHERE focal_source_order_tied_with_prior)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    forbidden = {"kind_draw", "outcome_kind_draw"}.intersection(
        pq.ParquetFile(temporary).schema_arrow.names
    )
    qa = {
        "rows": int(qa_row[0]),
        "unique_games": int(qa_row[1]),
        "latest_benefactor": int(qa_row[2]),
        "latest_claimer": int(qa_row[3]),
        "bad_arm_rows": int(qa_row[4]),
        "nonprior_order_rows": int(qa_row[5]),
        "selected_prior_duplicate_source_key_rows": int(qa_row[6]),
        "focal_source_key_tied_with_prior_rows": int(qa_row[7]),
        "focal_outcome_columns_present": sorted(forbidden),
    }
    if (
        qa["rows"] <= 0
        or qa["rows"] != qa["unique_games"]
        or qa["latest_benefactor"] + qa["latest_claimer"] != qa["rows"]
        or qa["bad_arm_rows"]
        or qa["nonprior_order_rows"]
        or forbidden
    ):
        raise RuntimeError(f"C7X latest-arm ASOF QA failed: {qa}")
    os.replace(temporary, output)
    saved = checkpoint_receipt(
        output=output,
        config_sha256=config_sha256,
        status="C7X_LATEST_REVERSED_ARM_PRIVATE_OK",
        qa=qa,
    )
    common.atomic_json(receipt, saved)
    print(
        "C7X_LATEST_REVERSED_ARM_ASOF_OK "
        f"rows={qa['rows']:,} benefactor={qa['latest_benefactor']:,} "
        f"claimer={qa['latest_claimer']:,}",
        flush=True,
    )
    return output, saved


def build_classification(
    *, latest: Path, prior: Path, state: Path, threads: int,
    memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c7x_classification_private.parquet"
    receipt = state / "c7x_classification_receipt.json"
    saved = parquet_checkpoint(
        output=output,
        receipt=receipt,
        config_sha256=config_sha256,
        status="C7X_CLASSIFICATION_PRIVATE_OK",
    )
    if saved is not None:
        if saved.get("qa", {}).get("old_sample_validation") != OLD_SAMPLE_EXPECTED:
            raise RuntimeError("Saved C7X old-sample validation changed")
        forbidden = {"kind_draw", "outcome_kind_draw"}.intersection(
            pq.ParquetFile(output).schema_arrow.names
        )
        if forbidden:
            raise RuntimeError("Focal outcome entered C7X classification checkpoint")
        print("C7X_CLASSIFICATION_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved

    print("C7X_CLASSIFICATION_ENRICHMENT_BEGIN", flush=True)
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/classification",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT
            b.*,
            ps.prior_arm AS same_speed_prior_arm,
            CAST(pm.prior_game_id IS NOT NULL AS BOOLEAN) AS any_prior_mercy,
            CAST(pc.prior_game_id IS NOT NULL AS BOOLEAN) AS any_prior_claim,
            CAST(
              (pm.prior_game_id IS NOT NULL)
              AND (pc.prior_game_id IS NOT NULL)
              AS BOOLEAN
            ) AS conflicting_prior_arm_history,
            CAST(
              NOT b.focal_source_order_tied_with_prior
              AND b.latest_prior_source_order_multiplicity = 1
              AS BOOLEAN
            ) AS tie_break_independent,
            CAST(
              hash(b.low_id, b.high_id, {PAIR_SEED})
              % {PAIR_SAMPLE_DENOMINATOR} = 0
              AS BOOLEAN
            ) AS historical_pair_sample,
            CAST(
              (b.focal_utc_ms - b.latest_prior_utc_ms) / {DAY_MS}.0
              AS DOUBLE
            ) AS latest_gap_days
          FROM read_parquet({common.sql_literal(latest)}) b
          ASOF LEFT JOIN read_parquet({common.sql_literal(prior)}) ps
            ON b.low_id = ps.low_id
           AND b.high_id = ps.high_id
           AND b.opponent_id = ps.prior_chooser_id
           AND b.chooser_id = ps.prior_disconnected_id
           AND b.speed_code = ps.prior_speed_code
           AND ROW(b.focal_utc_ms, b.focal_archive_ordinal, b.game_id)
               > ROW(ps.prior_utc_ms, ps.prior_archive_ordinal,
                     ps.prior_game_id)
          ASOF LEFT JOIN (
            SELECT * FROM read_parquet({common.sql_literal(prior)})
            WHERE prior_arm=1
          ) pm
            ON b.low_id = pm.low_id
           AND b.high_id = pm.high_id
           AND b.opponent_id = pm.prior_chooser_id
           AND b.chooser_id = pm.prior_disconnected_id
           AND ROW(b.focal_utc_ms, b.focal_archive_ordinal, b.game_id)
               > ROW(pm.prior_utc_ms, pm.prior_archive_ordinal,
                     pm.prior_game_id)
          ASOF LEFT JOIN (
            SELECT * FROM read_parquet({common.sql_literal(prior)})
            WHERE prior_arm=0
          ) pc
            ON b.low_id = pc.low_id
           AND b.high_id = pc.high_id
           AND b.opponent_id = pc.prior_chooser_id
           AND b.chooser_id = pc.prior_disconnected_id
           AND ROW(b.focal_utc_ms, b.focal_archive_ordinal, b.game_id)
               > ROW(pc.prior_utc_ms, pc.prior_archive_ordinal,
                     pc.prior_game_id)
          ORDER BY b.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    base = connection.execute(
        f"""
        SELECT
          COUNT(*) AS rows,
          COUNT(DISTINCT game_id) AS unique_games,
          COUNT(*) FILTER (WHERE latest_prior_arm=1) AS latest_benefactor,
          COUNT(*) FILTER (WHERE latest_prior_arm=0) AS latest_claimer,
          COUNT(DISTINCT chooser_id) AS chooser_clusters,
          COUNT(DISTINCT pair_hash) AS pair_clusters,
          COUNT(*) FILTER (WHERE same_speed_prior_arm=1) AS same_benefactor,
          COUNT(*) FILTER (WHERE same_speed_prior_arm=0) AS same_claimer,
          COUNT(*) FILTER (
            WHERE any_prior_mercy AND NOT any_prior_claim
          ) AS benefactor_only,
          COUNT(*) FILTER (
            WHERE any_prior_claim AND NOT any_prior_mercy
          ) AS claimer_only,
          COUNT(*) FILTER (WHERE conflicting_prior_arm_history) AS conflicting,
          COUNT(*) FILTER (WHERE tie_break_independent) AS tie_independent,
          COUNT(*) FILTER (
            WHERE latest_gap_days < 0 OR NOT isfinite(latest_gap_days)
          ) AS bad_gap_rows,
          COUNT(*) FILTER (WHERE ply_count IS NULL OR ply_band NOT BETWEEN 0 AND 7)
            AS bad_ply_rows
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    historical = connection.execute(
        f"""
        SELECT
          COUNT(*) FILTER (
            WHERE historical_pair_sample AND latest_prior_arm=1
          ),
          COUNT(*) FILTER (
            WHERE historical_pair_sample AND latest_prior_arm=0
          ),
          COUNT(*) FILTER (
            WHERE historical_pair_sample AND same_speed_prior_arm=1
          ),
          COUNT(*) FILTER (
            WHERE historical_pair_sample AND same_speed_prior_arm=0
          ),
          COUNT(*) FILTER (
            WHERE historical_pair_sample
              AND any_prior_mercy AND NOT any_prior_claim
          ),
          COUNT(*) FILTER (
            WHERE historical_pair_sample
              AND any_prior_claim AND NOT any_prior_mercy
          ),
          COUNT(*) FILTER (
            WHERE historical_pair_sample AND conflicting_prior_arm_history
          )
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    overlap = connection.execute(
        f"""
        WITH chooser_support AS (
          SELECT chooser_id,
            BOOL_OR(latest_prior_arm=1) AS has_benefactor,
            BOOL_OR(latest_prior_arm=0) AS has_claimer
          FROM read_parquet({common.sql_literal(temporary)})
          GROUP BY chooser_id
        ), pair_support AS (
          SELECT pair_hash,
            BOOL_OR(latest_prior_arm=1) AS has_benefactor,
            BOOL_OR(latest_prior_arm=0) AS has_claimer
          FROM read_parquet({common.sql_literal(temporary)})
          GROUP BY pair_hash
        )
        SELECT
          (SELECT COUNT(*) FROM chooser_support
           WHERE has_benefactor AND has_claimer),
          (SELECT COUNT(*) FROM pair_support
           WHERE has_benefactor AND has_claimer)
        """
    ).fetchone()
    recency = connection.execute(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE latest_gap_days <= 7 AND latest_prior_arm=1),
          COUNT(*) FILTER (WHERE latest_gap_days <= 7 AND latest_prior_arm=0),
          COUNT(*) FILTER (WHERE latest_gap_days <= 30 AND latest_prior_arm=1),
          COUNT(*) FILTER (WHERE latest_gap_days <= 30 AND latest_prior_arm=0),
          COUNT(*) FILTER (WHERE latest_gap_days <= 180 AND latest_prior_arm=1),
          COUNT(*) FILTER (WHERE latest_gap_days <= 180 AND latest_prior_arm=0),
          COUNT(*) FILTER (WHERE latest_gap_days <= 365 AND latest_prior_arm=1),
          COUNT(*) FILTER (WHERE latest_gap_days <= 365 AND latest_prior_arm=0)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    old_validation = {
        "latest_benefactor": int(historical[0]),
        "latest_claimer": int(historical[1]),
        "same_speed_benefactor": int(historical[2]),
        "same_speed_claimer": int(historical[3]),
        "exclusive_benefactor_only": int(historical[4]),
        "exclusive_claimer_only": int(historical[5]),
        "conflicting_histories": int(historical[6]),
    }
    qa = {
        "rows": int(base[0]),
        "unique_games": int(base[1]),
        "latest_benefactor": int(base[2]),
        "latest_claimer": int(base[3]),
        "chooser_clusters": int(base[4]),
        "pair_clusters": int(base[5]),
        "same_speed_benefactor": int(base[6]),
        "same_speed_claimer": int(base[7]),
        "exclusive_benefactor_only": int(base[8]),
        "exclusive_claimer_only": int(base[9]),
        "conflicting_histories": int(base[10]),
        "tie_break_independent_rows": int(base[11]),
        "tie_break_dependent_rows": int(base[0]) - int(base[11]),
        "bad_gap_rows": int(base[12]),
        "bad_ply_rows": int(base[13]),
        "within_chooser_both_latest_arms": int(overlap[0]),
        "within_pair_both_latest_arms": int(overlap[1]),
        "recency_support": {
            "le7_benefactor": int(recency[0]),
            "le7_claimer": int(recency[1]),
            "le30_benefactor": int(recency[2]),
            "le30_claimer": int(recency[3]),
            "le180_benefactor": int(recency[4]),
            "le180_claimer": int(recency[5]),
            "le365_benefactor": int(recency[6]),
            "le365_claimer": int(recency[7]),
        },
        "old_sample_validation": old_validation,
        "focal_kind_outcome_read": False,
    }
    forbidden = {"kind_draw", "outcome_kind_draw"}.intersection(
        pq.ParquetFile(temporary).schema_arrow.names
    )
    if (
        qa["rows"] <= 0
        or qa["rows"] != qa["unique_games"]
        or qa["latest_benefactor"] + qa["latest_claimer"] != qa["rows"]
        or qa["bad_gap_rows"]
        or qa["bad_ply_rows"]
        or old_validation != OLD_SAMPLE_EXPECTED
        or forbidden
    ):
        raise RuntimeError(
            "C7X classification or exact old-sample validation failed: "
            f"qa={qa} forbidden={sorted(forbidden)}"
        )
    os.replace(temporary, output)
    saved = checkpoint_receipt(
        output=output,
        config_sha256=config_sha256,
        status="C7X_CLASSIFICATION_PRIVATE_OK",
        qa=qa,
    )
    common.atomic_json(receipt, saved)
    print("C7X_OLD_SAMPLE_SUPPORT_REPRODUCTION_OK", flush=True)
    print(
        "C7X_CLASSIFICATION_ENRICHMENT_OK "
        f"rows={qa['rows']:,} benefactor={qa['latest_benefactor']:,} "
        f"claimer={qa['latest_claimer']:,} "
        f"within_chooser_both={qa['within_chooser_both_latest_arms']:,}",
        flush=True,
    )
    return output, saved


def freeze_support(
    *, classification_receipt: Mapping[str, Any], state: Path,
    config_sha256: str,
) -> dict[str, Any]:
    path = state / "c7x_support_frozen_before_focal_outcome.json"
    qa = dict(classification_receipt["qa"])
    payload = {
        "status": "C7X_FULLPANEL_SUPPORT_FROZEN_BEFORE_FOCAL_OUTCOME",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "classification_sha256": classification_receipt["output_sha256"],
        "full_stage07_classification": finite(qa),
        "primary_minimum_rows_per_arm": 1_000,
        "primary_minimum_clusters": 100,
        "primary_support_pass": (
            int(qa["latest_benefactor"]) >= 1_000
            and int(qa["latest_claimer"]) >= 1_000
            and int(qa["chooser_clusters"]) >= 100
        ),
        "old_2pct_sample_gate_remains_failed": True,
        "old_c7_lineage_mutated": False,
        "epistemic_label": "X",
        "focal_kind_outcome_read": False,
    }
    if path.is_file():
        saved = common.load_json(path)
        for key in (
            "config_sha256",
            "classification_sha256",
            "full_stage07_classification",
            "primary_support_pass",
            "focal_kind_outcome_read",
        ):
            if saved.get(key) != payload.get(key):
                raise RuntimeError(f"Frozen C7X support changed: {key}")
        return saved
    common.atomic_json(path, payload)
    return payload


def build_model_cache(
    *, classification: Path, stage_paths: Sequence[Path], state: Path,
    threads: int, memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c7x_model_private.parquet"
    receipt = state / "c7x_model_receipt.json"
    classification_rows = common.parquet_rows([classification])
    saved = parquet_checkpoint(
        output=output,
        receipt=receipt,
        config_sha256=config_sha256,
        status="C7X_MODEL_PRIVATE_OK",
        expected_rows=classification_rows,
    )
    if saved is not None:
        print("C7X_MODEL_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved

    print("C7X_FOCAL_OUTCOME_JOIN_BEGIN", flush=True)
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/model_cache",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT c.*, CAST(s.outcome_kind_draw AS DOUBLE) AS kind
          FROM read_parquet({common.sql_literal(classification)}) c
          INNER JOIN read_parquet(
            {common.path_list_literal(stage_paths)}, union_by_name=true
          ) s ON CAST(s.game_id AS VARCHAR) = c.game_id
          ORDER BY c.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa_row = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
          COUNT(*) FILTER (WHERE kind IS NULL),
          SUM(CAST(kind AS BIGINT))
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    qa = {
        "rows": int(qa_row[0]),
        "unique_games": int(qa_row[1]),
        "null_kind_rows": int(qa_row[2]),
        "kind_draws": int(qa_row[3]),
    }
    if (
        qa["rows"] != classification_rows
        or qa["unique_games"] != classification_rows
        or qa["null_kind_rows"]
    ):
        raise RuntimeError(f"C7X focal outcome join failed: {qa}")
    os.replace(temporary, output)
    saved = checkpoint_receipt(
        output=output,
        config_sha256=config_sha256,
        status="C7X_MODEL_PRIVATE_OK",
        qa=qa,
    )
    common.atomic_json(receipt, saved)
    print(
        f"C7X_FOCAL_OUTCOME_JOIN_OK rows={qa['rows']:,} "
        f"kind_draws={qa['kind_draws']:,}",
        flush=True,
    )
    return output, saved


def load_model(path: Path, threads: int) -> dict[str, Any]:
    _, _, pa, pq = common.import_dependencies()
    pa.set_cpu_count(int(threads))
    columns = (
        "kind", "latest_prior_arm", "same_speed_prior_arm",
        "any_prior_mercy", "any_prior_claim", "historical_pair_sample",
        "tie_break_independent", "latest_gap_days", "chooser_id", "pair_hash",
        "row_hash", "eval_bin", "speed_code", "month_code", "hour_of_week",
        "ply_count", "ply_band", "draw_payoff", "win_premium",
        "chooser_clock", "opponent_clock", "chooser_elo", "opponent_elo",
        "chooser_rd", "opponent_rd", "tournament",
    )
    table = pq.read_table(path, columns=list(columns), use_threads=True)
    nullable = {
        "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
        "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
        "latest_gap_days",
    }
    return {
        name: common.arrow_numpy(table, name, nullable_float=name in nullable)
        for name in table.column_names
    }


def controls(data: Mapping[str, Any], indices: Any) -> dict[str, Any]:
    return {
        name: data[name][indices]
        for name in (
            "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
            "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
            "tournament",
        )
    }


def attempt_model(
    *, data: Mapping[str, Any], sample: Any, exposure: Any, model: str,
    cluster_field: str, include_chooser_fe: bool,
    include_ply_fe: bool, minimum_arm_rows: int,
) -> dict[str, Any]:
    np = common.import_numpy()
    sample = np.asarray(sample, dtype=bool)
    exposure = np.asarray(exposure, dtype=np.float64)
    indices = np.flatnonzero(sample)
    treated = int(np.count_nonzero(exposure[indices] == 1.0))
    control = int(np.count_nonzero(exposure[indices] == 0.0))
    clusters = int(np.unique(data[cluster_field][indices]).size) if indices.size else 0
    support = {
        "model": model,
        "status": "ATTEMPT_PENDING",
        "epistemic_label": "X",
        "rows_requested": int(indices.size),
        "benefactor_rows_requested": treated,
        "claimer_rows_requested": control,
        "clusters_requested": clusters,
        "cluster": cluster_field,
        "chooser_fixed_effects": include_chooser_fe,
        "ply_band_fixed_effects": include_ply_fe,
        "causal_claim": False,
    }
    if (
        indices.size < 1_000
        or treated < minimum_arm_rows
        or control < minimum_arm_rows
        or clusters < 100
    ):
        return {
            **support,
            "status": "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT",
            "minimum_arm_rows": minimum_arm_rows,
        }
    fixed_effects: dict[str, Any] = {
        "eval_bin": data["eval_bin"][indices],
        "speed": data["speed_code"][indices],
        "month": data["month_code"][indices],
        "hour_of_week": data["hour_of_week"][indices],
    }
    if include_chooser_fe:
        fixed_effects = {
            "chooser": data["chooser_id"][indices],
            **fixed_effects,
        }
    if include_ply_fe:
        fixed_effects["ply_band"] = data["ply_band"][indices]
    try:
        fitted = common.fit_hdfe_cluster(
            outcome=data["kind"][indices],
            exposures={"benefactor_minus_claimer": exposure[indices]},
            numeric_controls=controls(data, indices),
            fixed_effects=fixed_effects,
            clusters=data[cluster_field][indices],
            row_ids=data["row_hash"][indices],
            specification={
                "model": model,
                "epistemic_label": "X",
                "analysis_role": "post-gate exploratory C7X",
                "cluster": cluster_field,
                "chooser_fixed_effects": include_chooser_fe,
                "ply_band_fixed_effects": include_ply_fe,
                "causal_claim": False,
            },
        )
        term = fitted.pop("results")[0]
        return finite(
            {
                **support,
                **fitted,
                **term,
                "status": "ESTIMATED",
                "effect_percentage_points": 100.0 * term["coefficient"],
                "standard_error_percentage_points": 100.0
                * term["standard_error"],
            }
        )
    except (RuntimeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        return {
            **support,
            "status": "ESTIMATION_FAILURE_RETAINED",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }


def descriptive_row(
    *, data: Mapping[str, Any], sample: Any, exposure: Any, label: str,
) -> dict[str, Any]:
    np = common.import_numpy()
    sample = np.asarray(sample, dtype=bool)
    exposure = np.asarray(exposure, dtype=np.float64)
    treated = sample & (exposure == 1.0)
    control = sample & (exposure == 0.0)
    nt = int(np.count_nonzero(treated))
    nc = int(np.count_nonzero(control))
    yt = int(np.sum(data["kind"][treated]))
    yc = int(np.sum(data["kind"][control]))
    rt = yt / nt if nt else math.nan
    rc = yc / nc if nc else math.nan
    return finite(
        {
            "analysis": label,
            "benefactor_rows": nt,
            "benefactor_kind_draws": yt,
            "benefactor_kind_rate_pct": 100.0 * rt,
            "claimer_rows": nc,
            "claimer_kind_draws": yc,
            "claimer_kind_rate_pct": 100.0 * rc,
            "benefactor_minus_claimer_raw_pp": 100.0 * (rt - rc),
            "inferential_p_value": None,
            "inference_note": (
                "raw counts and rates only; use clustered adjusted model attempts"
            ),
            "epistemic_label": "X",
            "causal_claim": False,
        }
    )


def estimate_all(
    model_cache: Path, support: Mapping[str, Any], threads: int
) -> dict[str, Any]:
    np = common.import_numpy()
    data = load_model(model_cache, threads)
    latest = np.asarray(data["latest_prior_arm"], dtype=np.int64)
    all_rows = np.ones(latest.size, dtype=bool)
    exposure = (latest == 1).astype(np.float64)
    attempts: list[dict[str, Any]] = []
    attempts.append(
        attempt_model(
            data=data,
            sample=all_rows,
            exposure=exposure,
            model=PRIMARY_MODEL,
            cluster_field="chooser_id",
            include_chooser_fe=True,
            include_ply_fe=True,
            minimum_arm_rows=1_000,
        )
    )
    attempts.append(
        attempt_model(
            data=data,
            sample=all_rows,
            exposure=exposure,
            model=LEGACY_PLANNED_MODEL,
            cluster_field="chooser_id",
            include_chooser_fe=True,
            include_ply_fe=False,
            minimum_arm_rows=1_000,
        )
    )
    attempts.append(
        attempt_model(
            data=data,
            sample=all_rows,
            exposure=exposure,
            model="X_C7X_latest_reversed_arm_chooser_ply_fe_pair_cluster",
            cluster_field="pair_hash",
            include_chooser_fe=True,
            include_ply_fe=True,
            minimum_arm_rows=1_000,
        )
    )
    attempts.append(
        attempt_model(
            data=data,
            sample=all_rows,
            exposure=exposure,
            model="X_C7X_latest_reversed_arm_pooled_ply_adjusted_chooser_cluster",
            cluster_field="chooser_id",
            include_chooser_fe=False,
            include_ply_fe=True,
            minimum_arm_rows=1_000,
        )
    )

    same = np.asarray(data["same_speed_prior_arm"], dtype=np.int64)
    same_sample = (same == 1) | (same == 0)
    attempts.append(
        attempt_model(
            data=data,
            sample=same_sample,
            exposure=(same == 1).astype(np.float64),
            model="X_C7X_latest_reversed_arm_same_speed_chooser_ply_fe",
            cluster_field="chooser_id",
            include_chooser_fe=True,
            include_ply_fe=True,
            minimum_arm_rows=1,
        )
    )

    mercy = np.asarray(data["any_prior_mercy"], dtype=bool)
    claim = np.asarray(data["any_prior_claim"], dtype=bool)
    exclusive = mercy ^ claim
    attempts.append(
        attempt_model(
            data=data,
            sample=exclusive,
            exposure=mercy.astype(np.float64),
            model="X_C7X_any_prior_arm_exclusive_histories_chooser_ply_fe",
            cluster_field="chooser_id",
            include_chooser_fe=True,
            include_ply_fe=True,
            minimum_arm_rows=1,
        )
    )

    tie_independent = np.asarray(data["tie_break_independent"], dtype=bool)
    attempts.append(
        attempt_model(
            data=data,
            sample=tie_independent,
            exposure=exposure,
            model="X_C7X_latest_reversed_arm_tie_independent_chooser_ply_fe",
            cluster_field="chooser_id",
            include_chooser_fe=True,
            include_ply_fe=True,
            minimum_arm_rows=1,
        )
    )
    ply = np.asarray(data["ply_count"], dtype=np.int64)
    attempts.append(
        attempt_model(
            data=data,
            sample=ply > 10,
            exposure=exposure,
            model="X_C7X_latest_reversed_arm_ply_gt10_chooser_ply_fe",
            cluster_field="chooser_id",
            include_chooser_fe=True,
            include_ply_fe=True,
            minimum_arm_rows=1,
        )
    )
    tournament = np.asarray(data["tournament"], dtype=np.float64)
    attempts.append(
        attempt_model(
            data=data,
            sample=np.isfinite(tournament) & (tournament == 0.0),
            exposure=exposure,
            model="X_C7X_latest_reversed_arm_nontournament_chooser_ply_fe",
            cluster_field="chooser_id",
            include_chooser_fe=True,
            include_ply_fe=True,
            minimum_arm_rows=1,
        )
    )

    gap = np.asarray(data["latest_gap_days"], dtype=np.float64)
    for days in (7, 30, 180, 365):
        attempts.append(
            attempt_model(
                data=data,
                sample=gap <= days,
                exposure=exposure,
                model=f"X_C7X_latest_reversed_arm_le{days}d_chooser_ply_fe",
                cluster_field="chooser_id",
                include_chooser_fe=True,
                include_ply_fe=True,
                minimum_arm_rows=1,
            )
        )

    descriptive: list[dict[str, Any]] = [
        descriptive_row(
            data=data,
            sample=all_rows,
            exposure=exposure,
            label="latest_reversed_arm_all_gaps",
        ),
        descriptive_row(
            data=data,
            sample=same_sample,
            exposure=(same == 1).astype(np.float64),
            label="latest_reversed_arm_same_speed",
        ),
        descriptive_row(
            data=data,
            sample=exclusive,
            exposure=mercy.astype(np.float64),
            label="any_prior_arm_exclusive_histories",
        ),
        descriptive_row(
            data=data,
            sample=tie_independent,
            exposure=exposure,
            label="latest_reversed_arm_tie_independent",
        ),
        descriptive_row(
            data=data,
            sample=ply > 10,
            exposure=exposure,
            label="latest_reversed_arm_ply_gt10",
        ),
    ]
    historical_sample = np.asarray(data["historical_pair_sample"], dtype=bool)
    old_outcome_replication = descriptive_row(
        data=data,
        sample=historical_sample,
        exposure=exposure,
        label="historical_2pct_latest_reversed_arm_replication",
    )
    observed_old_outcomes = {
        key: old_outcome_replication.get(key) for key in OLD_OUTCOME_EXPECTED
    }
    if observed_old_outcomes != OLD_OUTCOME_EXPECTED:
        raise RuntimeError(
            "C7X old-sample focal-outcome replication failed: "
            f"{observed_old_outcomes}"
        )
    descriptive.append(old_outcome_replication)
    gap_bands = (
        ("gap_0_7_days", gap <= 7),
        ("gap_8_30_days", (gap > 7) & (gap <= 30)),
        ("gap_31_180_days", (gap > 30) & (gap <= 180)),
        ("gap_over_180_days", gap > 180),
    )
    for label, mask in gap_bands:
        descriptive.append(
            descriptive_row(
                data=data,
                sample=mask,
                exposure=exposure,
                label=label,
            )
        )

    observed_models = tuple(row["model"] for row in attempts)
    if observed_models != EXPECTED_MODEL_NAMES:
        raise RuntimeError(
            f"C7X model inventory changed: observed={observed_models}"
        )
    primary = next(row for row in attempts if row["model"] == PRIMARY_MODEL)
    return finite(
        {
            "status": "C7X_FULLPANEL_EXPLORATORY_ESTIMATION_COMPLETE",
            "epistemic_label": "X",
            "primary_model": PRIMARY_MODEL,
            "legacy_planned_model": LEGACY_PLANNED_MODEL,
            "total_order_rule": ["utc_ms", "archive_ordinal", "game_id"],
            "ply_bands": ["0-4", "5-6", "7-8", "9-10", "11-20", "21-40", "41-80", "81+"],
            "expected_model_names": list(EXPECTED_MODEL_NAMES),
            "primary": primary,
            "model_attempts": attempts,
            "descriptive_counts_and_rates": descriptive,
            "old_sample_outcome_replication": old_outcome_replication,
            "support": support,
            "models_attempted": len(attempts),
            "models_estimated": sum(row["status"] == "ESTIMATED" for row in attempts),
            "models_failed_or_low_support_retained": sum(
                row["status"] != "ESTIMATED" for row in attempts
            ),
            "old_2pct_c7_result_changed": False,
            "holm_family": "not included",
            "causal_claim": False,
            "claim_boundary": (
                "Post-gate, outcome-informed, full-Stage-07 conditional association. "
                "It is not a causal effect of receiving mercy and is not a census "
                "of prior interactions outside Stage 07."
            ),
        }
    )


def flatten_models(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "model", "status", "epistemic_label", "rows_requested",
        "benefactor_rows_requested", "claimer_rows_requested",
        "clusters_requested", "cluster", "chooser_fixed_effects",
        "ply_band_fixed_effects", "rows",
        "clusters", "coefficient", "effect_percentage_points", "standard_error",
        "standard_error_percentage_points", "t_cluster", "p_value_two_sided",
        "outcome_mean", "absorption_iterations", "absorption_tolerance",
        "absorption_last_adjustment", "sample_specification_sha256",
        "error_type", "error_message", "causal_claim",
    )
    return [{field: row.get(field) for field in fields} for row in rows]


def report_hashes(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "file": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name != "report_file_hashes.tsv"
    ]


def write_report_manifest(root: Path) -> None:
    rows = report_hashes(root)
    lines = ["file\tbytes\tsha256"] + [
        f"{row['file']}\t{row['bytes']}\t{row['sha256']}" for row in rows
    ]
    common.atomic_text(root / "report_file_hashes.tsv", "\n".join(lines) + "\n")


def update_pointer(
    path: Path | None, *, status: str, run_id: str, output: Path,
    state: Path, root: Path,
) -> None:
    if path is None:
        return
    success = output / "_SUCCESS.json"
    failure = output / "FAILURE_DIAGNOSTIC.json"
    common.atomic_json(
        path,
        {
            "status": status,
            "created_utc": common.utc_now(),
            "run_id": run_id,
            "result_root": str(output),
            "state_root": str(state),
            "package_root": str(root),
            "success_sha256": common.sha256_file(success) if success.is_file() else None,
            "failure_sha256": common.sha256_file(failure) if failure.is_file() else None,
        },
    )


def execute(args: argparse.Namespace) -> Path:
    started = time.time()
    root = package_root()
    package_rows = authenticate_package(root)
    project = args.project_root.expanduser().resolve()
    if project != PROJECT_AUTHORITY:
        raise RuntimeError(f"Project authority path changed: {project}")
    if not 1 <= args.threads <= 16:
        raise RuntimeError("Threads must be between 1 and 16")
    state = (
        args.state_root.expanduser().resolve()
        if args.state_root
        else project / "derived/replication" / STATE_NAME
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
    update_pointer(
        args.execution_pointer,
        status="C7X_EXECUTION_STARTED",
        run_id=run_id,
        output=output,
        state=state,
        root=root,
    )

    try:
        print("C7X_FULLPANEL_AUTHENTICATION_BEGIN", flush=True)
        stage_root = project / STAGE07_RELATIVE
        stage_auth = common.authenticate_stage07(
            stage_root, EXPECTED_STAGE07_SUCCESS_SHA256
        )
        stage_paths = common.stage07_paths(stage_root)
        plan = root / (
            "payload/docs/"
            "dynamics_paper2_campaign1_c7x_fullpanel_exploratory_plan_"
            "v1_0_1_2026-08-27.md"
        )
        prior_result = root / "payload/authorities/prior_c7/c7_results.json"
        prior_payload = common.load_json(prior_result)
        if (
            prior_payload.get("support_gate", {}).get(
                "benefactor_facing_fair_opportunities"
            ) != 33
            or prior_payload.get("support_gate", {}).get("gate_pass") is not False
        ):
            raise RuntimeError("Packaged prespecified C7 authority changed")
        config = {
            "script_version": SCRIPT_VERSION,
            "script_sha256": common.sha256_file(Path(__file__)),
            "common_sha256": common.sha256_file(Path(common.__file__)),
            "plan_sha256": common.sha256_file(plan),
            "prior_c7_result_sha256": common.sha256_file(prior_result),
            "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
            "package_manifest_sha256": common.sha256_json(package_rows),
            "threads": args.threads,
            "memory_limit": args.memory_limit,
            "pair_seed": PAIR_SEED,
            "pair_sample_denominator": PAIR_SAMPLE_DENOMINATOR,
            "epistemic_label": "X",
            "primary_model": PRIMARY_MODEL,
        }
        config_sha256 = common.sha256_json(config)
        state_config = state / "configuration.json"
        if state_config.is_file():
            saved = common.load_json(state_config)
            if saved.get("config_sha256") != config_sha256:
                raise RuntimeError("C7X private state belongs to another configuration")
        else:
            common.atomic_json(
                state_config,
                {
                    "status": "C7X_FULLPANEL_PRIVATE_STATE_CREATED",
                    "created_utc": common.utc_now(),
                    "config_sha256": config_sha256,
                    "config": config,
                    "privacy": "PRIVATE; DO NOT PUBLISH ROW-LEVEL CHECKPOINTS",
                },
            )
        common.atomic_json(
            output / "input_authorities.json",
            {
                "config": config,
                "config_sha256": config_sha256,
                "stage07": stage_auth,
                "prior_prespecified_c7": {
                    "status": prior_payload.get("status"),
                    "gate": prior_payload.get("support_gate"),
                    "result_sha256": common.sha256_file(prior_result),
                    "lineage_mutated": False,
                },
            },
        )
        print("C7X_FULLPANEL_AUTHENTICATION_OK", flush=True)

        prior, prior_receipt = build_prior_arms(
            stage_paths=stage_paths,
            state=state,
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
        )
        duplicate_diagnostic = prior_receipt["qa"]["duplicate_order_diagnostic"]
        common.atomic_json(
            output / "c7x_duplicate_order_diagnostic.json",
            finite(duplicate_diagnostic),
        )
        print(
            "C7X_DUPLICATE_ORDER_BRANCH_FROZEN "
            f"groups={duplicate_diagnostic['duplicate_source_order_groups']:,} "
            f"branch={duplicate_diagnostic['selected_recovery_branch']}",
            flush=True,
        )
        focal, focal_receipt = build_fair_focal(
            stage_paths=stage_paths,
            state=state,
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
        )
        latest, latest_receipt = build_latest_arm(
            focal=focal,
            prior=prior,
            state=state,
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
        )
        classification, classification_receipt = build_classification(
            latest=latest,
            prior=prior,
            state=state,
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
        )
        support = freeze_support(
            classification_receipt=classification_receipt,
            state=state,
            config_sha256=config_sha256,
        )
        common.atomic_json(output / "c7x_support_frozen.json", finite(support))
        common.atomic_json(
            output / "private_checkpoint_authentication.json",
            finite(
                {
                    "prior_arms": prior_receipt,
                    "fair_focal": focal_receipt,
                    "latest_arm": latest_receipt,
                    "classification": classification_receipt,
                    "private_paths_are_provenance_only": True,
                }
            ),
        )
        print(
            "C7X_FULLPANEL_SUPPORT_FROZEN "
            f"pass={support['primary_support_pass']} "
            f"benefactor={support['full_stage07_classification']['latest_benefactor']:,} "
            f"claimer={support['full_stage07_classification']['latest_claimer']:,}",
            flush=True,
        )

        model_cache, model_receipt = build_model_cache(
            classification=classification,
            stage_paths=stage_paths,
            state=state,
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
        )
        results = estimate_all(model_cache, support, args.threads)
        primary = results["primary"]
        common.atomic_json(output / "c7x_results.json", results)
        common.write_csv(
            output / "c7x_model_attempts.csv",
            flatten_models(results["model_attempts"]),
        )
        common.write_csv(
            output / "c7x_descriptive_counts_rates.csv",
            results["descriptive_counts_and_rates"],
        )
        common.atomic_json(
            output / "c7x_primary_interpretation.json",
            finite(
                {
                    "status": primary.get("status"),
                    "model": PRIMARY_MODEL,
                    "effect_percentage_points": primary.get(
                        "effect_percentage_points"
                    ),
                    "standard_error_percentage_points": primary.get(
                        "standard_error_percentage_points"
                    ),
                    "p_value_two_sided": primary.get("p_value_two_sided"),
                    "epistemic_label": "X",
                    "causal_claim": False,
                    "old_c7_gate_changed": False,
                    "paper_use": (
                        "Potential exploratory direct-reciprocity evidence only; "
                        "interpret after stability across clustering, pooled, "
                        "same-speed, history, and recency companions."
                    ),
                    "claim_boundary": results["claim_boundary"],
                }
            ),
        )
        success = {
            "status": "DYNAMICS_CAMPAIGN1_C7X_FULLPANEL_V101_OK",
            "created_utc": common.utc_now(),
            "runtime_seconds": time.time() - started,
            "config_sha256": config_sha256,
            "stage07_rows": EXPECTED_STAGE07_ROWS,
            "fair_focal_rows": EXPECTED_FAIR_ROWS,
            "classified_rows": classification_receipt["output_rows"],
            "full_support": support["full_stage07_classification"],
            "primary": primary,
            "old_sample_outcome_replication": results[
                "old_sample_outcome_replication"
            ],
            "models_attempted": results["models_attempted"],
            "models_estimated": results["models_estimated"],
            "models_failed_or_low_support_retained": results[
                "models_failed_or_low_support_retained"
            ],
            "model_cache_rows": model_receipt["output_rows"],
            "duplicate_order_diagnostic": duplicate_diagnostic,
            "total_order_rule": ["utc_ms", "archive_ordinal", "game_id"],
            "game_stage_control": "eight ply-band fixed effects in v1.0.1 primary",
            "epistemic_label": "X",
            "causal_claim": False,
            "old_2pct_c7_gate_remains_failed": True,
            "old_c7_lineage_mutated": False,
            "holm_family": "not included",
            "private_state_root": str(state),
            "public_output_root": str(output),
        }
        common.atomic_json(output / "_SUCCESS.json", finite(success))
        write_report_manifest(output)
        update_pointer(
            args.execution_pointer,
            status=success["status"],
            run_id=run_id,
            output=output,
            state=state,
            root=root,
        )
        print(f"DYNAMICS_CAMPAIGN1_C7X_FULLPANEL_V101_OK: {output}", flush=True)
        if primary.get("status") == "ESTIMATED":
            print(
                "C7X_PRIMARY_BENEFACTOR_MINUS_CLAIMER "
                f"effect_pp={primary['effect_percentage_points']:.9g} "
                f"se_pp={primary['standard_error_percentage_points']:.9g} "
                f"p={primary['p_value_two_sided']:.9g}",
                flush=True,
            )
        else:
            print(
                "C7X_PRIMARY_NOT_ESTIMATED_RETAINED "
                f"status={primary.get('status')}",
                flush=True,
            )
        return output
    except BaseException as error:
        diagnostic = {
            "status": "DYNAMICS_CAMPAIGN1_C7X_FULLPANEL_V101_FAILED_CLOSED",
            "created_utc": common.utc_now(),
            "runtime_seconds": time.time() - started,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
            "favorable_null_and_adverse_outputs_retained": True,
            "private_checkpoints_resumable": True,
            "old_c7_lineage_mutated": False,
            "git_mutated": False,
        }
        common.atomic_json(output / "FAILURE_DIAGNOSTIC.json", diagnostic)
        write_report_manifest(output)
        update_pointer(
            args.execution_pointer,
            status=diagnostic["status"],
            run_id=run_id,
            output=output,
            state=state,
            root=root,
        )
        raise


def run_self_test() -> None:
    duckdb, np, _, _ = common.import_dependencies()
    common.self_test()
    order_diagnostic.self_test()
    if OLD_SAMPLE_EXPECTED != {
        "latest_benefactor": 33,
        "latest_claimer": 557,
        "same_speed_benefactor": 29,
        "same_speed_claimer": 534,
        "exclusive_benefactor_only": 28,
        "exclusive_claimer_only": 543,
        "conflicting_histories": 19,
    }:
        raise RuntimeError("C7X historical support authority changed")

    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE synthetic_prior(
          low_id BIGINT, high_id BIGINT,
          prior_chooser_id BIGINT, prior_disconnected_id BIGINT,
          prior_utc_ms BIGINT, prior_archive_ordinal BIGINT,
          event_order HUGEINT, prior_game_id VARCHAR,
          prior_speed_code INTEGER, prior_arm TINYINT
        );
        INSERT INTO synthetic_prior VALUES
          (1,2,2,1,100,1,100,'p12_mercy',2,1),
          (1,2,2,1,200,2,200,'p12_claim',3,0),
          (3,4,4,3,100,3,100,'p34_mercy',2,1),
          (5,6,5,6,80,4,80,'p56_same_orientation',2,1),
          (5,6,6,5,90,5,90,'p56_claim',2,0),
          (7,8,8,7,100,1,10001,'a',2,1),
          (7,8,8,7,100,1,10001,'c',2,0);
        CREATE TABLE synthetic_focal(
          game_id VARCHAR, low_id BIGINT, high_id BIGINT,
          chooser_id BIGINT, opponent_id BIGINT,
          focal_utc_ms BIGINT, focal_archive_ordinal BIGINT,
          event_order HUGEINT,
          speed_code INTEGER
        );
        INSERT INTO synthetic_focal VALUES
          ('f12',1,2,1,2,250,1,250,2),
          ('f34',3,4,3,4,150,1,150,2),
          ('f56',5,6,5,6,120,1,120,2),
          ('b',7,8,7,8,100,1,10001,2);
        CREATE TABLE synthetic_latest AS
        SELECT f.*, p.prior_arm AS latest_prior_arm,
               p.prior_speed_code AS latest_prior_speed_code,
               p.prior_utc_ms AS latest_prior_utc_ms
        FROM synthetic_focal f
        ASOF JOIN synthetic_prior p
          ON f.low_id=p.low_id AND f.high_id=p.high_id
         AND f.opponent_id=p.prior_chooser_id
         AND f.chooser_id=p.prior_disconnected_id
         AND ROW(f.focal_utc_ms,f.focal_archive_ordinal,f.game_id)
             > ROW(p.prior_utc_ms,p.prior_archive_ordinal,p.prior_game_id);
        """
    )
    rows = connection.execute(
        """
        SELECT b.game_id, b.latest_prior_arm, ps.prior_arm,
               pm.prior_game_id IS NOT NULL,
               pc.prior_game_id IS NOT NULL
        FROM synthetic_latest b
        ASOF LEFT JOIN synthetic_prior ps
          ON b.low_id=ps.low_id AND b.high_id=ps.high_id
         AND b.opponent_id=ps.prior_chooser_id
         AND b.chooser_id=ps.prior_disconnected_id
         AND b.speed_code=ps.prior_speed_code
         AND ROW(b.focal_utc_ms,b.focal_archive_ordinal,b.game_id)
             > ROW(ps.prior_utc_ms,ps.prior_archive_ordinal,ps.prior_game_id)
        ASOF LEFT JOIN (
          SELECT * FROM synthetic_prior WHERE prior_arm=1
        ) pm
          ON b.low_id=pm.low_id AND b.high_id=pm.high_id
         AND b.opponent_id=pm.prior_chooser_id
         AND b.chooser_id=pm.prior_disconnected_id
         AND ROW(b.focal_utc_ms,b.focal_archive_ordinal,b.game_id)
             > ROW(pm.prior_utc_ms,pm.prior_archive_ordinal,pm.prior_game_id)
        ASOF LEFT JOIN (
          SELECT * FROM synthetic_prior WHERE prior_arm=0
        ) pc
          ON b.low_id=pc.low_id AND b.high_id=pc.high_id
         AND b.opponent_id=pc.prior_chooser_id
         AND b.chooser_id=pc.prior_disconnected_id
         AND ROW(b.focal_utc_ms,b.focal_archive_ordinal,b.game_id)
             > ROW(pc.prior_utc_ms,pc.prior_archive_ordinal,pc.prior_game_id)
        ORDER BY b.game_id
        """
    ).fetchall()
    connection.close()
    expected = [
        ("b", 1, 1, True, False),
        ("f12", 0, 1, True, True),
        ("f34", 1, 1, True, False),
        ("f56", 0, 0, False, True),
    ]
    if rows != expected:
        raise RuntimeError(f"C7X ASOF role/latest/history self-test failed: {rows}")

    synthetic = {
        "kind": np.asarray([1.0, 0.0, 1.0, 0.0]),
        "latest_prior_arm": np.asarray([1, 1, 0, 0]),
    }
    raw = descriptive_row(
        data=synthetic,
        sample=np.ones(4, dtype=bool),
        exposure=(synthetic["latest_prior_arm"] == 1).astype(float),
        label="synthetic",
    )
    if raw["benefactor_rows"] != 2 or raw["claimer_rows"] != 2:
        raise RuntimeError("C7X descriptive self-test failed")
    print("DYNAMICS_CAMPAIGN1_C7X_FULLPANEL_SELF_TEST_OK", flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        return
    if not args.execute:
        print("Dry run only. Pass --execute to authenticate data and run C7X.")
        return
    execute(args)


if __name__ == "__main__":
    main()
