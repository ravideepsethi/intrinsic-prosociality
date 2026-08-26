#!/usr/bin/env python3
"""C13 lagged leave-one-chooser-out ambient-kindness associations.

v1.0.4 preserves the v1.0.3 outcome-blind denominator correction and fixes one
numerator assertion: 669,503 is the kindness count in all 47,587,020 Stage-07
rows, while the C13 fair sample contains 487,170 kindness outcomes among
17,328,130 rows.  The latter value was independently recorded by the certified
Stage-09 artifact before Campaign 1.  Every primary, sensitivity, nonlinear,
quartile, rating-band, and speed model is attempted, and model-level numerical
or support failures are retained instead of silently skipped.
"""

from __future__ import annotations

import gc
import math
import os
from pathlib import Path
import shutil
import time
from typing import Any, Mapping, Sequence
import uuid

import campaign1_nonprofile_common_v102 as common


SCRIPT_VERSION = "1.0.4"
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_FAIR_ROWS = 17_328_130
EXPECTED_ALL_STAGE07_KIND_DRAWS = 669_503
EXPECTED_FAIR_KIND_DRAWS = 487_170
EXPECTED_PRIMARY_SUPPORTED_ROWS = 17_101_141
EXPECTED_PRIMARY_OTHER_N28_MIN = 0
EXPECTED_PRIMARY_OTHER_N28_P10 = 28_081.0
EXPECTED_PRIMARY_OTHER_N28_MEDIAN = 136_490.0
WAVE0_PRIMARY_SUPPORTED_ROWS = 17_104_149
WAVE0_PRIMARY_OTHER_N28_MIN = 0
WAVE0_PRIMARY_OTHER_N28_P10 = 27_902.0
WAVE0_PRIMARY_OTHER_N28_MEDIAN = 136_108.0
SUPPORT_THRESHOLD = 5_000
DAY_MS = 86_400_000
STRICT_ABSORPTION_TOLERANCE = 1e-9
STRICT_ABSORPTION_ITERATIONS = 2_000
EXTENDED_ABSORPTION_TOLERANCE = 1e-7
EXTENDED_ABSORPTION_ITERATIONS = 25_000


def _authenticate_file(
    output: Path, receipt: Path, config_sha256: str, expected_rows: int | None = None
) -> dict[str, Any] | None:
    _, _, _, pq = common.import_dependencies()
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial C13 checkpoint: {output}")
    saved = common.load_json(receipt)
    actual_rows = int(pq.ParquetFile(output).metadata.num_rows)
    if (
        saved.get("config_sha256") != config_sha256
        or saved.get("output_sha256") != common.sha256_file(output)
        or saved.get("rows") != actual_rows
        or (expected_rows is not None and actual_rows != expected_rows)
    ):
        raise RuntimeError(f"C13 checkpoint mismatch: {output}")
    return saved


def build_base(
    *, stage07_paths: Sequence[Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c13_fair_base_private.parquet"
    receipt = state / "c13_fair_base_receipt.json"
    saved = _authenticate_file(output, receipt, config_sha256, EXPECTED_FAIR_ROWS)
    if saved:
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C13 base checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c13_base",
    )
    speed = common.speed_code_sql("s.api_speed")
    chooser_band = common.rating_band_sql("s.chooser_elo")
    eval_bin = common.eval_bin_sql("s.engine_eval_cp_disconnected")
    hour_week = common.hour_of_week_sql("s.api_last_move_at_ms")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT
            CAST(s.game_id AS VARCHAR) AS game_id,
            CAST(s.chooser_user_id AS BIGINT) AS chooser_id,
            CAST(s.chooser_username_norm AS VARCHAR) AS loo_chooser,
            CAST(floor(CAST(s.api_last_move_at_ms AS DOUBLE) / {DAY_MS}) AS INTEGER)
              AS decision_day_index,
            CAST(floor(
              (floor(CAST(s.api_last_move_at_ms AS DOUBLE) / {DAY_MS}) - 19660) / 7.0
            ) AS INTEGER) AS calendar_week,
            CAST({speed} AS INTEGER) AS speed_code,
            CAST({chooser_band} AS INTEGER) AS chooser_rating_band,
            CAST({eval_bin} AS INTEGER) AS eval_bin,
            CAST({hour_week} AS INTEGER) AS hour_of_week,
            CAST(s.tournament_like_event AS BOOLEAN) AS tournament,
            CAST(s.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
            CAST(s.chooser_win_premium_v2 AS DOUBLE) AS win_premium,
            CAST(s.chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock,
            CAST(s.disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock,
            CAST(s.chooser_elo AS DOUBLE) AS chooser_elo,
            CAST(s.disconnected_elo AS DOUBLE) AS opponent_elo,
            CAST(s.chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
            CAST(s.disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
            CAST(hash(CAST(s.game_id AS VARCHAR)) % 9223372036854775807 AS BIGINT)
              AS row_hash
          FROM read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true) s
          WHERE CAST(s.fair_competitive AS BOOLEAN)
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
               COUNT(*) FILTER (WHERE chooser_id IS NULL OR loo_chooser IS NULL),
               COUNT(*) FILTER (WHERE speed_code NOT BETWEEN 0 AND 5),
               COUNT(*) FILTER (WHERE chooser_rating_band NOT BETWEEN 0 AND 3),
               COUNT(*) FILTER (WHERE decision_day_index IS NULL)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    if qa[0] != EXPECTED_FAIR_ROWS or qa[0] != qa[1] or any(qa[2:]):
        raise RuntimeError(f"C13 fair base authority failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "C13_FAIR_DENOMINATOR_BASE_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "rows": int(qa[0]),
        "output_sha256": common.sha256_file(output),
        "ambient_kindness_numerator_read": False,
        "privacy": "PRIVATE ROW-LEVEL DENOMINATOR BASE; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c13_base", ignore_errors=True)
    return output, saved


DAILY_GROUPS: dict[str, tuple[str, ...]] = {
    "cell": ("decision_day_index", "speed_code", "chooser_rating_band"),
    "chooser_cell": (
        "decision_day_index", "loo_chooser", "speed_code", "chooser_rating_band"
    ),
    "speed": ("decision_day_index", "speed_code"),
    "chooser_speed": ("decision_day_index", "loo_chooser", "speed_code"),
}


def build_daily_denominators(
    *, base: Path, state: Path, threads: int, memory_limit: str,
    config_sha256: str
) -> dict[str, Path]:
    duckdb, _, _, _ = common.import_dependencies()
    outputs: dict[str, Path] = {}
    for label, fields in DAILY_GROUPS.items():
        output = state / f"c13_daily_denominator_{label}_private.parquet"
        receipt = state / f"c13_daily_denominator_{label}_receipt.json"
        saved = _authenticate_file(output, receipt, config_sha256)
        if saved:
            outputs[label] = output
            continue
        if output.exists() or receipt.exists():
            raise RuntimeError(f"Partial C13 daily denominator checkpoint: {label}")
        connection = duckdb.connect()
        common.configure_duckdb(
            connection,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=state / f"duckdb_temp/c13_denominator_{label}",
        )
        field_sql = ", ".join(fields)
        temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
        connection.execute(
            f"""
            COPY (
              SELECT {field_sql}, COUNT(*)::BIGINT AS opportunities
              FROM read_parquet({common.sql_literal(base)})
              GROUP BY {field_sql}
              ORDER BY {field_sql}
            ) TO {common.sql_literal(temporary)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        qa = connection.execute(
            f"SELECT COUNT(*), SUM(opportunities) FROM read_parquet({common.sql_literal(temporary)})"
        ).fetchone()
        connection.close()
        if qa[0] <= 0 or qa[1] != EXPECTED_FAIR_ROWS:
            raise RuntimeError(f"C13 daily denominator row conservation failed: {label} {qa}")
        os.replace(temporary, output)
        common.atomic_json(
            receipt,
            {
                "status": f"C13_DAILY_DENOMINATOR_{label.upper()}_PRIVATE_OK",
                "created_utc": common.utc_now(),
                "config_sha256": config_sha256,
                "rows": int(qa[0]),
                "opportunities": int(qa[1]),
                "output_sha256": common.sha256_file(output),
                "ambient_kindness_numerator_read": False,
            },
        )
        shutil.rmtree(state / f"duckdb_temp/c13_denominator_{label}", ignore_errors=True)
        outputs[label] = output
    return outputs


def _rolling_sql(
    path: Path, *, partitions: Sequence[str], value: str, prefix: str,
    include_washout: bool
) -> str:
    partition = ", ".join(partitions)
    fields = ", ".join(("decision_day_index", *partitions))
    expressions = [
        f"COALESCE(SUM({value}) OVER (PARTITION BY {partition} ORDER BY decision_day_index RANGE BETWEEN 14 PRECEDING AND 1 PRECEDING),0)::BIGINT AS {prefix}14",
        f"COALESCE(SUM({value}) OVER (PARTITION BY {partition} ORDER BY decision_day_index RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING),0)::BIGINT AS {prefix}28",
        f"COALESCE(SUM({value}) OVER (PARTITION BY {partition} ORDER BY decision_day_index RANGE BETWEEN 56 PRECEDING AND 1 PRECEDING),0)::BIGINT AS {prefix}56",
    ]
    if include_washout:
        expressions.append(
            f"COALESCE(SUM({value}) OVER (PARTITION BY {partition} ORDER BY decision_day_index RANGE BETWEEN 35 PRECEDING AND 8 PRECEDING),0)::BIGINT AS {prefix}28_washout7"
        )
    return (
        f"SELECT {fields}, " + ", ".join(expressions)
        + f" FROM read_parquet({common.sql_literal(path)})"
    )


def build_support_cache(
    *, base: Path, daily: Mapping[str, Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c13_denominator_support_private.parquet"
    receipt = state / "c13_denominator_support_frozen.json"
    saved = _authenticate_file(output, receipt, config_sha256, EXPECTED_FAIR_ROWS)
    if saved:
        if int(saved.get("primary_supported_rows", -1)) != EXPECTED_PRIMARY_SUPPORTED_ROWS:
            raise RuntimeError("Frozen C13 support no longer matches the v1.0.2 reconstruction")
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C13 support checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c13_support",
    )
    cell = _rolling_sql(
        daily["cell"],
        partitions=("speed_code", "chooser_rating_band"),
        value="opportunities",
        prefix="n",
        include_washout=True,
    )
    chooser_cell = _rolling_sql(
        daily["chooser_cell"],
        partitions=("loo_chooser", "speed_code", "chooser_rating_band"),
        value="opportunities",
        prefix="n",
        include_washout=True,
    )
    speed = _rolling_sql(
        daily["speed"],
        partitions=("speed_code",),
        value="opportunities",
        prefix="n",
        include_washout=False,
    )
    chooser_speed = _rolling_sql(
        daily["chooser_speed"],
        partitions=("loo_chooser", "speed_code"),
        value="opportunities",
        prefix="n",
        include_washout=False,
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH cell AS ({cell}), chooser_cell AS ({chooser_cell}),
               speed AS ({speed}), chooser_speed AS ({chooser_speed})
          SELECT b.*,
            (c.n14 - cc.n14)::BIGINT AS cell_other_n14,
            (c.n28 - cc.n28)::BIGINT AS cell_other_n28,
            (c.n56 - cc.n56)::BIGINT AS cell_other_n56,
            (c.n28_washout7 - cc.n28_washout7)::BIGINT
              AS cell_other_n28_washout7,
            (sp.n14 - cs.n14)::BIGINT AS speed_other_n14,
            (sp.n28 - cs.n28)::BIGINT AS speed_other_n28,
            (sp.n56 - cs.n56)::BIGINT AS speed_other_n56
          FROM read_parquet({common.sql_literal(base)}) b
          INNER JOIN cell c USING (decision_day_index, speed_code, chooser_rating_band)
          INNER JOIN chooser_cell cc
            USING (decision_day_index, loo_chooser, speed_code, chooser_rating_band)
          INNER JOIN speed sp USING (decision_day_index, speed_code)
          INNER JOIN chooser_speed cs USING (decision_day_index, loo_chooser, speed_code)
          ORDER BY b.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*) AS rows,
          COUNT(DISTINCT game_id) AS unique_games,
          COUNT(*) FILTER (WHERE cell_other_n28 >= {SUPPORT_THRESHOLD}) AS cell28,
          COUNT(*) FILTER (WHERE cell_other_n14 >= {SUPPORT_THRESHOLD}) AS cell14,
          COUNT(*) FILTER (WHERE cell_other_n56 >= {SUPPORT_THRESHOLD}) AS cell56,
          COUNT(*) FILTER (WHERE cell_other_n28_washout7 >= {SUPPORT_THRESHOLD}) AS washout,
          COUNT(*) FILTER (WHERE speed_other_n14 >= {SUPPORT_THRESHOLD}) AS speed14,
          COUNT(*) FILTER (WHERE speed_other_n28 >= {SUPPORT_THRESHOLD}) AS speed28,
          COUNT(*) FILTER (WHERE speed_other_n56 >= {SUPPORT_THRESHOLD}) AS speed56,
          COUNT(*) FILTER (
            WHERE cell_other_n14 < 0 OR cell_other_n28 < 0 OR cell_other_n56 < 0
               OR cell_other_n28_washout7 < 0 OR speed_other_n14 < 0
               OR speed_other_n28 < 0 OR speed_other_n56 < 0
          ) AS negative_denominators,
          MIN(cell_other_n28),
          quantile_cont(cell_other_n28, 0.10),
          median(cell_other_n28)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    by_cell = connection.execute(
        f"""
        SELECT speed_code, chooser_rating_band, COUNT(*) AS focal_rows,
               COUNT(*) FILTER (WHERE cell_other_n28 >= {SUPPORT_THRESHOLD})
                 AS supported_rows,
               median(cell_other_n28) AS median_other_n28
        FROM read_parquet({common.sql_literal(temporary)})
        GROUP BY ALL ORDER BY 1,2
        """
    ).fetchall()
    connection.close()
    if (
        qa[0] != EXPECTED_FAIR_ROWS
        or qa[0] != qa[1]
        or qa[2] != EXPECTED_PRIMARY_SUPPORTED_ROWS
        or qa[9] != 0
        or int(qa[10]) != EXPECTED_PRIMARY_OTHER_N28_MIN
        or float(qa[11]) != EXPECTED_PRIMARY_OTHER_N28_P10
        or float(qa[12]) != EXPECTED_PRIMARY_OTHER_N28_MEDIAN
    ):
        raise RuntimeError(
            "C13 frozen support failed to reproduce the corrected v1.0.2 reconstruction: "
            f"rows={qa[0]} unique={qa[1]} primary={qa[2]} "
            f"expected={EXPECTED_PRIMARY_SUPPORTED_ROWS} negative={qa[9]} "
            f"min/p10/median={qa[10:13]}"
        )
    os.replace(temporary, output)
    support_by_spec = {
        "cell_28d": int(qa[2]),
        "cell_14d": int(qa[3]),
        "cell_56d": int(qa[4]),
        "cell_28d_washout7": int(qa[5]),
        "speed_14d": int(qa[6]),
        "speed_28d": int(qa[7]),
        "speed_56d": int(qa[8]),
    }
    saved = {
        "status": "C13_DENOMINATOR_SUPPORT_FROZEN_BEFORE_AMBIENT_NUMERATOR",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "rows": int(qa[0]),
        "output_sha256": common.sha256_file(output),
        "support_threshold_other_fair_opportunities": SUPPORT_THRESHOLD,
        "primary_supported_rows": int(qa[2]),
        "primary_thin_excluded_rows": int(qa[0] - qa[2]),
        "primary_supported_share": float(qa[2] / qa[0]),
        "support_by_specification": support_by_spec,
        "primary_other_n28_min": int(qa[10]),
        "primary_other_n28_p10": float(qa[11]),
        "primary_other_n28_median": float(qa[12]),
        "support_by_cell": [
            {
                "speed_code": int(row[0]),
                "chooser_rating_band": int(row[1]),
                "focal_rows": int(row[2]),
                "supported_rows": int(row[3]),
                "median_other_n28": float(row[4]),
            }
            for row in by_cell
        ],
        "ambient_kindness_numerator_read": False,
        "support_authority": "outcome-blind v1.0.2 exact reconstruction",
        "superseded_wave0_supported_rows": WAVE0_PRIMARY_SUPPORTED_ROWS,
        "wave0_minus_corrected_rows": (
            WAVE0_PRIMARY_SUPPORTED_ROWS - EXPECTED_PRIMARY_SUPPORTED_ROWS
        ),
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c13_support", ignore_errors=True)
    return output, saved


def build_kind_events(
    *, base: Path, stage07_paths: Sequence[Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> Path:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c13_kind_events_private.parquet"
    receipt = state / "c13_kind_events_receipt.json"
    saved = _authenticate_file(output, receipt, config_sha256, EXPECTED_FAIR_ROWS)
    if saved:
        if (
            int(saved.get("unique_game_ids", -1)) != EXPECTED_FAIR_ROWS
            or int(saved.get("kind_draws", -1)) != EXPECTED_FAIR_KIND_DRAWS
            or int(saved.get("invalid_kind_rows", -1)) != 0
        ):
            raise RuntimeError("C13 kindness numerator checkpoint changed")
        return output
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C13 kindness event checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c13_kind_events",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT b.game_id, b.decision_day_index, b.chooser_id, b.loo_chooser,
                 b.speed_code, b.chooser_rating_band,
                 CAST(s.outcome_kind_draw AS BIGINT) AS kind
          FROM read_parquet({common.sql_literal(base)}) b
          INNER JOIN read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true) s
            ON CAST(s.game_id AS VARCHAR) = b.game_id
          ORDER BY b.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT game_id), SUM(kind), COUNT(*) FILTER (WHERE kind IS NULL OR kind NOT BETWEEN 0 AND 1) FROM read_parquet({common.sql_literal(temporary)})"
    ).fetchone()
    connection.close()
    if qa != (EXPECTED_FAIR_ROWS, EXPECTED_FAIR_ROWS, EXPECTED_FAIR_KIND_DRAWS, 0):
        raise RuntimeError(f"C13 kindness numerator authority failed: {qa}")
    os.replace(temporary, output)
    common.atomic_json(
        receipt,
        {
            "status": "C13_KINDNESS_NUMERATOR_EVENTS_PRIVATE_OK",
            "created_utc": common.utc_now(),
            "config_sha256": config_sha256,
            "rows": int(qa[0]),
            "unique_game_ids": int(qa[1]),
            "kind_draws": int(qa[2]),
            "invalid_kind_rows": int(qa[3]),
            "output_sha256": common.sha256_file(output),
            "privacy": "PRIVATE ROW-LEVEL OUTCOME CACHE; DO NOT PUBLISH",
        },
    )
    shutil.rmtree(state / "duckdb_temp/c13_kind_events", ignore_errors=True)
    return output


def build_daily_kind(
    *, kind_events: Path, state: Path, threads: int, memory_limit: str,
    config_sha256: str
) -> dict[str, Path]:
    duckdb, _, _, _ = common.import_dependencies()
    outputs: dict[str, Path] = {}
    for label, fields in DAILY_GROUPS.items():
        output = state / f"c13_daily_kind_{label}_private.parquet"
        receipt = state / f"c13_daily_kind_{label}_receipt.json"
        saved = _authenticate_file(output, receipt, config_sha256)
        if saved:
            if int(saved.get("kind_draws", -1)) != EXPECTED_FAIR_KIND_DRAWS:
                raise RuntimeError(f"C13 daily kindness checkpoint changed: {label}")
            outputs[label] = output
            continue
        if output.exists() or receipt.exists():
            raise RuntimeError(f"Partial C13 daily kindness checkpoint: {label}")
        connection = duckdb.connect()
        common.configure_duckdb(
            connection,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=state / f"duckdb_temp/c13_kind_{label}",
        )
        field_sql = ", ".join(fields)
        temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
        connection.execute(
            f"""
            COPY (
              SELECT {field_sql}, COUNT(*)::BIGINT AS opportunities,
                     SUM(kind)::BIGINT AS kind_draws
              FROM read_parquet({common.sql_literal(kind_events)})
              GROUP BY {field_sql}
              ORDER BY {field_sql}
            ) TO {common.sql_literal(temporary)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        qa = connection.execute(
            f"SELECT COUNT(*), SUM(opportunities), SUM(kind_draws) FROM read_parquet({common.sql_literal(temporary)})"
        ).fetchone()
        connection.close()
        if qa[0] <= 0 or qa[1] != EXPECTED_FAIR_ROWS or qa[2] != EXPECTED_FAIR_KIND_DRAWS:
            raise RuntimeError(f"C13 daily kindness row conservation failed: {label} {qa}")
        os.replace(temporary, output)
        common.atomic_json(
            receipt,
            {
                "status": f"C13_DAILY_KIND_{label.upper()}_PRIVATE_OK",
                "created_utc": common.utc_now(),
                "config_sha256": config_sha256,
                "rows": int(qa[0]),
                "opportunities": int(qa[1]),
                "kind_draws": int(qa[2]),
                "output_sha256": common.sha256_file(output),
            },
        )
        shutil.rmtree(state / f"duckdb_temp/c13_kind_{label}", ignore_errors=True)
        outputs[label] = output
    return outputs


def build_model_cache(
    *, support: Path, kind_events: Path, daily_kind: Mapping[str, Path],
    state: Path, threads: int, memory_limit: str, config_sha256: str
) -> Path:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c13_model_private.parquet"
    receipt = state / "c13_model_receipt.json"
    saved = _authenticate_file(output, receipt, config_sha256, EXPECTED_FAIR_ROWS)
    if saved:
        return output
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C13 model checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c13_model",
    )
    cell = _rolling_sql(
        daily_kind["cell"],
        partitions=("speed_code", "chooser_rating_band"),
        value="kind_draws",
        prefix="k",
        include_washout=True,
    )
    chooser_cell = _rolling_sql(
        daily_kind["chooser_cell"],
        partitions=("loo_chooser", "speed_code", "chooser_rating_band"),
        value="kind_draws",
        prefix="k",
        include_washout=True,
    )
    speed = _rolling_sql(
        daily_kind["speed"],
        partitions=("speed_code",),
        value="kind_draws",
        prefix="k",
        include_washout=False,
    )
    chooser_speed = _rolling_sql(
        daily_kind["chooser_speed"],
        partitions=("loo_chooser", "speed_code"),
        value="kind_draws",
        prefix="k",
        include_washout=False,
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH cell AS ({cell}), chooser_cell AS ({chooser_cell}),
               speed AS ({speed}), chooser_speed AS ({chooser_speed}),
          focal_kind AS (
            SELECT game_id, kind
            FROM read_parquet({common.sql_literal(kind_events)})
          ),
          joined AS (
            SELECT s.*, e.kind,
              (c.k14 - cc.k14)::BIGINT AS cell_other_k14,
              (c.k28 - cc.k28)::BIGINT AS cell_other_k28,
              (c.k56 - cc.k56)::BIGINT AS cell_other_k56,
              (c.k28_washout7 - cc.k28_washout7)::BIGINT
                AS cell_other_k28_washout7,
              (sp.k14 - cs.k14)::BIGINT AS speed_other_k14,
              (sp.k28 - cs.k28)::BIGINT AS speed_other_k28,
              (sp.k56 - cs.k56)::BIGINT AS speed_other_k56
            FROM read_parquet({common.sql_literal(support)}) s
            INNER JOIN focal_kind e USING (game_id)
            INNER JOIN cell c USING (decision_day_index, speed_code, chooser_rating_band)
            INNER JOIN chooser_cell cc
              USING (decision_day_index, loo_chooser, speed_code, chooser_rating_band)
            INNER JOIN speed sp USING (decision_day_index, speed_code)
            INNER JOIN chooser_speed cs USING (decision_day_index, loo_chooser, speed_code)
          )
          SELECT *,
            cell_other_k14::DOUBLE / NULLIF(cell_other_n14, 0) AS ambient_cell_14,
            cell_other_k28::DOUBLE / NULLIF(cell_other_n28, 0) AS ambient_cell_28,
            cell_other_k56::DOUBLE / NULLIF(cell_other_n56, 0) AS ambient_cell_56,
            cell_other_k28_washout7::DOUBLE / NULLIF(cell_other_n28_washout7, 0)
              AS ambient_cell_28_washout7,
            speed_other_k14::DOUBLE / NULLIF(speed_other_n14, 0) AS ambient_speed_14,
            speed_other_k28::DOUBLE / NULLIF(speed_other_n28, 0) AS ambient_speed_28,
            speed_other_k56::DOUBLE / NULLIF(speed_other_n56, 0) AS ambient_speed_56
          FROM joined
          ORDER BY game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id), SUM(kind),
          COUNT(*) FILTER (
            WHERE cell_other_k14 < 0 OR cell_other_k28 < 0 OR cell_other_k56 < 0
               OR cell_other_k28_washout7 < 0 OR speed_other_k14 < 0
               OR speed_other_k28 < 0 OR speed_other_k56 < 0
               OR cell_other_k14 > cell_other_n14
               OR cell_other_k28 > cell_other_n28
               OR cell_other_k56 > cell_other_n56
               OR cell_other_k28_washout7 > cell_other_n28_washout7
               OR speed_other_k14 > speed_other_n14
               OR speed_other_k28 > speed_other_n28
               OR speed_other_k56 > speed_other_n56
          ),
          COUNT(*) FILTER (
            WHERE ambient_cell_28 IS NOT NULL
              AND (ambient_cell_28 < 0 OR ambient_cell_28 > 1)
          )
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    if qa != (EXPECTED_FAIR_ROWS, EXPECTED_FAIR_ROWS, EXPECTED_FAIR_KIND_DRAWS, 0, 0):
        raise RuntimeError(f"C13 model-cache validation failed: {qa}")
    os.replace(temporary, output)
    common.atomic_json(
        receipt,
        {
            "status": "C13_AMBIENT_MODEL_PRIVATE_OK",
            "created_utc": common.utc_now(),
            "config_sha256": config_sha256,
            "rows": int(qa[0]),
            "kind_draws": int(qa[2]),
            "output_sha256": common.sha256_file(output),
            "privacy": "PRIVATE ROW-LEVEL MODEL CACHE; DO NOT PUBLISH",
        },
    )
    shutil.rmtree(state / "duckdb_temp/c13_model", ignore_errors=True)
    return output


def _load_model(path: Path) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    columns = (
        "chooser_id", "speed_code", "chooser_rating_band", "eval_bin",
        "hour_of_week", "calendar_week", "tournament", "draw_payoff",
        "win_premium", "chooser_clock", "opponent_clock", "chooser_elo",
        "opponent_elo", "chooser_rd", "opponent_rd", "row_hash", "kind",
        "cell_other_n14", "cell_other_n28", "cell_other_n56",
        "cell_other_n28_washout7", "speed_other_n14", "speed_other_n28",
        "speed_other_n56", "ambient_cell_14", "ambient_cell_28",
        "ambient_cell_56", "ambient_cell_28_washout7", "ambient_speed_14",
        "ambient_speed_28", "ambient_speed_56",
    )
    table = pq.read_table(path, columns=list(columns))
    nullable = {
        "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
        "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
        "ambient_cell_14", "ambient_cell_28", "ambient_cell_56",
        "ambient_cell_28_washout7", "ambient_speed_14", "ambient_speed_28",
        "ambient_speed_56",
    }
    return {
        name: common.arrow_numpy(table, name, nullable_float=name in nullable)
        for name in columns
    }


def _controls(data: dict[str, Any], indices: Any) -> dict[str, Any]:
    return {
        name: data[name][indices]
        for name in (
            "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
            "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
        )
    }


def _fixed_effects(data: dict[str, Any], indices: Any) -> dict[str, Any]:
    return {
        "chooser": data["chooser_id"][indices],
        "speed_x_chooser_rating_band": (
            data["speed_code"][indices] * 10 + data["chooser_rating_band"][indices]
        ),
        "calendar_week": data["calendar_week"][indices],
        "eval_bin": data["eval_bin"][indices],
        "hour_of_week": data["hour_of_week"][indices],
        "tournament": data["tournament"][indices],
    }


def _fit(
    *, data: dict[str, Any], sample: Any, exposures: Mapping[str, Any], label: str,
    analysis_role: str, absorption_tolerance: float,
    absorption_maximum_iterations: int,
) -> dict[str, Any]:
    np = common.import_numpy()
    indices = np.flatnonzero(sample)
    return common.fit_hdfe_cluster(
        outcome=data["kind"][indices],
        exposures={name: values[indices] for name, values in exposures.items()},
        numeric_controls=_controls(data, indices),
        fixed_effects=_fixed_effects(data, indices),
        clusters=data["chooser_id"][indices],
        row_ids=data["row_hash"][indices],
        specification={
            "model": label,
            "epistemic_label": "X",
            "analysis_role": analysis_role,
            "ambient_exposure_unit": "percentage points",
            "fixed_effects": "chooser + cell + calendar-week + current-state",
            "cluster": "chooser",
            "causal_claim": False,
        },
        absorption_tolerance=absorption_tolerance,
        absorption_maximum_iterations=absorption_maximum_iterations,
    )


def _retainable_model_failure(error: BaseException) -> bool:
    if common.is_hdfe_absorption_nonconvergence(error):
        return True
    if isinstance(error, RuntimeError):
        return str(error).startswith(
            (
                "Exposure has no residual variation:",
                "Rank-deficient HDFE model:",
                "Too few clusters for inference:",
                "Model contains no regressors",
            )
        ) or "fewer than 1,000 rows" in str(error)
    return type(error).__name__ == "LinAlgError"


def _attempt_model(
    *, data: dict[str, Any], sample: Any, exposures: Mapping[str, Any],
    label: str, analysis_role: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    np = common.import_numpy()
    requested_rows = int(np.count_nonzero(sample))
    requested_clusters = int(np.unique(data["chooser_id"][sample]).size)
    attempt: dict[str, Any] = {
        "model": label,
        "epistemic_label": "X",
        "analysis_role": analysis_role,
        "requested_rows": requested_rows,
        "requested_chooser_clusters": requested_clusters,
        "strict_absorption_tolerance": STRICT_ABSORPTION_TOLERANCE,
        "strict_absorption_maximum_iterations": STRICT_ABSORPTION_ITERATIONS,
        "extended_absorption_tolerance": EXTENDED_ABSORPTION_TOLERANCE,
        "extended_absorption_maximum_iterations": EXTENDED_ABSORPTION_ITERATIONS,
        "strict_error": None,
        "extended_error": None,
    }
    print(
        f"C13_MODEL_STRICT_BEGIN model={label} rows={requested_rows:,} "
        f"clusters={requested_clusters:,}",
        flush=True,
    )
    try:
        fitted = _fit(
            data=data,
            sample=sample,
            exposures=exposures,
            label=label,
            analysis_role=analysis_role,
            absorption_tolerance=STRICT_ABSORPTION_TOLERANCE,
            absorption_maximum_iterations=STRICT_ABSORPTION_ITERATIONS,
        )
        attempt.update(
            {
                "strict_status": "ESTIMATED",
                "extended_status": "NOT_NEEDED",
                "final_status": "ESTIMATED_STRICT",
                "numerical_estimate_emitted": True,
            }
        )
        print(f"C13_MODEL_STRICT_OK model={label}", flush=True)
        return _flatten(fitted), attempt
    except BaseException as strict_error:
        if not _retainable_model_failure(strict_error):
            raise
        attempt["strict_status"] = "FAILED_RETAINED"
        attempt["strict_error"] = f"{type(strict_error).__name__}: {strict_error}"
        if not common.is_hdfe_absorption_nonconvergence(strict_error):
            attempt.update(
                {
                    "extended_status": "NOT_APPLICABLE",
                    "final_status": "UNESTIMABLE_RETAINED",
                    "numerical_estimate_emitted": False,
                }
            )
            print(
                f"C13_MODEL_UNESTIMABLE_RETAINED model={label} "
                f"error={type(strict_error).__name__}: {strict_error}",
                flush=True,
            )
            return [], attempt
    print(f"C13_MODEL_EXTENDED_RETRY_BEGIN model={label}", flush=True)
    try:
        fitted = _fit(
            data=data,
            sample=sample,
            exposures=exposures,
            label=label,
            analysis_role=analysis_role,
            absorption_tolerance=EXTENDED_ABSORPTION_TOLERANCE,
            absorption_maximum_iterations=EXTENDED_ABSORPTION_ITERATIONS,
        )
        attempt.update(
            {
                "extended_status": "ESTIMATED",
                "final_status": "ESTIMATED_EXTENDED_ABSORPTION",
                "numerical_estimate_emitted": True,
            }
        )
        print(f"C13_MODEL_EXTENDED_RETRY_OK model={label}", flush=True)
        return _flatten(fitted), attempt
    except BaseException as extended_error:
        if not _retainable_model_failure(extended_error):
            raise
        attempt.update(
            {
                "extended_status": "FAILED_RETAINED",
                "extended_error": f"{type(extended_error).__name__}: {extended_error}",
                "final_status": "UNESTIMABLE_AFTER_EXTENDED_RETRY_RETAINED",
                "numerical_estimate_emitted": False,
            }
        )
        print(
            f"C13_MODEL_EXTENDED_FAILURE_RETAINED model={label} "
            f"error={type(extended_error).__name__}: {extended_error}",
            flush=True,
        )
        return [], attempt


def _flatten(fitted: dict[str, Any]) -> list[dict[str, Any]]:
    shared = {key: value for key, value in fitted.items() if key != "results"}
    return [
        {
            **shared,
            **result,
            "focal_effect_percentage_points": 100.0 * result["coefficient"],
            "focal_standard_error_percentage_points": 100.0 * result["standard_error"],
        }
        for result in fitted["results"]
    ]


def estimate(model_cache: Path) -> dict[str, Any]:
    np = common.import_numpy()
    data = _load_model(model_cache)
    specifications = (
        ("ambient_cell_28", "cell_other_n28", "C13_primary_cell_28d"),
        ("ambient_cell_14", "cell_other_n14", "C13_sensitivity_cell_14d"),
        ("ambient_cell_56", "cell_other_n56", "C13_sensitivity_cell_56d"),
        (
            "ambient_cell_28_washout7", "cell_other_n28_washout7",
            "C13_sensitivity_cell_28d_washout7",
        ),
        ("ambient_speed_14", "speed_other_n14", "C13_sensitivity_speed_14d"),
        ("ambient_speed_28", "speed_other_n28", "C13_sensitivity_speed_28d"),
        ("ambient_speed_56", "speed_other_n56", "C13_sensitivity_speed_56d"),
    )
    models: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for rate_name, denominator_name, label in specifications:
        sample = (
            (data[denominator_name] >= SUPPORT_THRESHOLD)
            & np.isfinite(data[rate_name])
        )
        rows, attempt = _attempt_model(
            data=data,
            sample=sample,
            exposures={"ambient_kindness_percentage_points": 100.0 * data[rate_name]},
            label=label,
            analysis_role="primary" if label == "C13_primary_cell_28d" else "planned_sensitivity",
        )
        for row in rows:
            row["ambient_definition"] = rate_name
            row["support_denominator"] = denominator_name
        models.extend(rows)
        attempt["ambient_definition"] = rate_name
        attempt["support_denominator"] = denominator_name
        attempts.append(attempt)
        gc.collect()
    primary_sample = (
        (data["cell_other_n28"] >= SUPPORT_THRESHOLD)
        & np.isfinite(data["ambient_cell_28"])
    )
    primary_ambient_pp = 100.0 * data["ambient_cell_28"]
    centered_ambient_pp = primary_ambient_pp - float(
        np.mean(primary_ambient_pp[primary_sample])
    )
    nonlinear, nonlinear_attempt = _attempt_model(
        data=data,
        sample=primary_sample,
        exposures={
            "ambient_pp_centered_linear": centered_ambient_pp,
            "ambient_pp_centered_squared": centered_ambient_pp * centered_ambient_pp,
        },
        label="C13_exploratory_quadratic_primary_ambient_rate",
        analysis_role="exploratory_nonlinearity",
    )
    for row in nonlinear:
        row["ambient_definition"] = "ambient_cell_28"
        row["heterogeneity_or_nonlinearity"] = "quadratic"
    models.extend(nonlinear)
    nonlinear_attempt["ambient_definition"] = "ambient_cell_28"
    attempts.append(nonlinear_attempt)
    for dimension, values in (
        ("chooser_rating_band", range(4)),
        ("speed_code", range(6)),
    ):
        for value in values:
            sample = primary_sample & (data[dimension] == value)
            subgroup, subgroup_attempt = _attempt_model(
                data=data,
                sample=sample,
                exposures={"ambient_kindness_percentage_points": primary_ambient_pp},
                label=f"C13_exploratory_primary_by_{dimension}_{value}",
                analysis_role="exploratory_heterogeneity",
            )
            for row in subgroup:
                row["ambient_definition"] = "ambient_cell_28"
                row["heterogeneity_dimension"] = dimension
                row["heterogeneity_value"] = value
            models.extend(subgroup)
            subgroup_attempt["ambient_definition"] = "ambient_cell_28"
            subgroup_attempt["heterogeneity_dimension"] = dimension
            subgroup_attempt["heterogeneity_value"] = value
            attempts.append(subgroup_attempt)
            gc.collect()
    primary_rates = data["ambient_cell_28"][primary_sample]
    edges = np.quantile(primary_rates, [0.25, 0.50, 0.75])
    quartile = np.zeros(data["kind"].size, dtype=np.int8)
    quartile[primary_sample] = (
        np.searchsorted(edges, data["ambient_cell_28"][primary_sample], side="right") + 1
    )
    quartile_exposures = {
        f"ambient_quartile_{value}_vs_1": (quartile == value).astype(float)
        for value in (2, 3, 4)
    }
    quartile_model, quartile_attempt = _attempt_model(
        data=data,
        sample=primary_sample,
        exposures=quartile_exposures,
        label="C13_primary_adjusted_ambient_quartiles",
        analysis_role="planned_sensitivity",
    )
    quartile_attempt["ambient_definition"] = "ambient_cell_28"
    attempts.append(quartile_attempt)
    descriptive: list[dict[str, Any]] = []
    for value in range(1, 5):
        mask = primary_sample & (quartile == value)
        descriptive.append(
            {
                "ambient_quartile": value,
                "opportunities": int(np.count_nonzero(mask)),
                "choosers": int(np.unique(data["chooser_id"][mask]).size),
                "kind_draws": int(np.sum(data["kind"][mask])),
                "kind_rate_pct": 100.0 * float(np.mean(data["kind"][mask])),
                "ambient_rate_pct_mean": 100.0 * float(np.mean(data["ambient_cell_28"][mask])),
                "ambient_rate_pct_min": 100.0 * float(np.min(data["ambient_cell_28"][mask])),
                "ambient_rate_pct_max": 100.0 * float(np.max(data["ambient_cell_28"][mask])),
            }
        )
    primary = next(
        (
            row for row in models
            if row.get("model") == "C13_primary_cell_28d"
            and row.get("term") == "ambient_kindness_percentage_points"
        ),
        None,
    )
    failed_attempts = [
        row for row in attempts if row["numerical_estimate_emitted"] is not True
    ]
    extended_successes = [
        row for row in attempts
        if row["final_status"] == "ESTIMATED_EXTENDED_ABSORPTION"
    ]
    status = (
        "C13_AMBIENT_NORM_ESTIMATION_COMPLETE"
        if not failed_attempts
        else "C13_AMBIENT_NORM_COMPLETED_WITH_RETAINED_MODEL_FAILURES"
    )
    return {
        "status": status,
        "epistemic_label": "X",
        "models": models,
        "model_attempts": attempts,
        "model_attempts_total": len(attempts),
        "models_estimated": sum(bool(row["numerical_estimate_emitted"]) for row in attempts),
        "extended_absorption_successes": len(extended_successes),
        "retained_model_failures": len(failed_attempts),
        "primary": primary,
        "primary_estimable": primary is not None,
        "quartile_edges_ambient_rate_pct": [100.0 * float(value) for value in edges],
        "quartile_model": quartile_model,
        "descriptive_quartiles": descriptive,
        "causal_claim": False,
        "interpretive_limit": "lagged leave-one-chooser-out association; not a causal peer effect",
    }


def execute(
    *, project: Path, state: Path, public_stage: Path, threads: int,
    memory_limit: str, config_sha256: str, source_base: Path,
    source_daily: Mapping[str, Path], wave0_authority: Mapping[str, Any],
    numerator_authority: Mapping[str, Any]
) -> dict[str, Any]:
    started = time.time()
    stage_root = project / "derived/replication/analysis_panel_24m_sf100k"
    if common.sha256_file(stage_root / "_SUCCESS.json") != EXPECTED_STAGE07_SUCCESS_SHA256:
        raise RuntimeError("C13 Stage 07 authority mismatch")
    stage_paths = common.stage07_paths(stage_root)
    if common.parquet_rows(stage_paths) != common.EXPECTED_STAGE07_ROWS:
        raise RuntimeError("C13 physical Stage 07 row count changed")
    if not source_base.is_file() or set(source_daily) != set(DAILY_GROUPS):
        raise RuntimeError("Authenticated v1.0.2 C13 denominator sources are incomplete")
    support_cache, support = build_support_cache(
        base=source_base,
        daily=source_daily,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    print(
        f"C13_OUTCOME_BLIND_SUPPORT_FROZEN supported={support['primary_supported_rows']:,} "
        f"thin={support['primary_thin_excluded_rows']:,}",
        flush=True,
    )
    public_stage.mkdir(parents=True, exist_ok=True)
    public_support = {key: value for key, value in support.items() if key != "output_sha256"}
    common.atomic_json(public_stage / "c13_support_frozen.json", public_support)
    common.write_csv(public_stage / "c13_support_by_cell.csv", support["support_by_cell"])
    reconciliation = {
        "status": "C13_V103_OUTCOME_BLIND_DENOMINATOR_CORRECTION_FROZEN",
        "created_utc": common.utc_now(),
        "timing": "after C12 outcomes; before any C13 ambient-kindness numerator or rate was read",
        "scientific_design_changed": False,
        "support_threshold_other_fair_opportunities": SUPPORT_THRESHOLD,
        "focal_fair_rows": EXPECTED_FAIR_ROWS,
        "wave0": {
            "supported_rows": WAVE0_PRIMARY_SUPPORTED_ROWS,
            "other_n28_min": WAVE0_PRIMARY_OTHER_N28_MIN,
            "other_n28_p10": WAVE0_PRIMARY_OTHER_N28_P10,
            "other_n28_median": WAVE0_PRIMARY_OTHER_N28_MEDIAN,
            "executable_producer_preserved": False,
            "disposition": "superseded denominator-feasibility aggregate; retained for provenance",
            "authority": dict(wave0_authority),
        },
        "corrected_reproducible_authority": {
            "supported_rows": support["primary_supported_rows"],
            "thin_excluded_rows": support["primary_thin_excluded_rows"],
            "supported_share": support["primary_supported_share"],
            "other_n28_min": support["primary_other_n28_min"],
            "other_n28_p10": support["primary_other_n28_p10"],
            "other_n28_median": support["primary_other_n28_median"],
            "algorithm": (
                "preceding 28 complete UTC days; speed-pool x frozen chooser-rating-band; "
                "subtract the focal chooser's own opportunities by normalized chooser identity"
            ),
            "source": "authenticated v1.0.2 Stage-07 denominator Parquets, reused read-only",
        },
        "wave0_minus_corrected_supported_rows": (
            WAVE0_PRIMARY_SUPPORTED_ROWS - support["primary_supported_rows"]
        ),
        "gate_passes_under_wave0": (
            WAVE0_PRIMARY_SUPPORTED_ROWS / EXPECTED_FAIR_ROWS > 0.95
        ),
        "gate_passes_under_correction": (
            support["primary_supported_rows"] / EXPECTED_FAIR_ROWS > 0.95
        ),
        "selection_on_c13_outcome": False,
    }
    common.atomic_json(public_stage / "c13_denominator_reconciliation_v103.json", reconciliation)
    print("C13_V103_DENOMINATOR_RECONCILIATION_FROZEN_BEFORE_NUMERATOR_OK", flush=True)
    kind_events = build_kind_events(
        base=source_base,
        stage07_paths=stage_paths,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    kind_receipt = common.load_json(state / "c13_kind_events_receipt.json")
    numerator_reconciliation = {
        "status": "C13_V104_FAIR_SAMPLE_NUMERATOR_AUTHORITY_CORRECTED",
        "created_utc": common.utc_now(),
        "focal_fair_rows": int(kind_receipt["rows"]),
        "unique_game_ids": int(kind_receipt["unique_game_ids"]),
        "fair_sample_kind_draws": int(kind_receipt["kind_draws"]),
        "invalid_kind_rows": int(kind_receipt["invalid_kind_rows"]),
        "all_stage07_rows": common.EXPECTED_STAGE07_ROWS,
        "all_stage07_kind_draws": EXPECTED_ALL_STAGE07_KIND_DRAWS,
        "superseded_v103_assertion": (
            "v1.0.3 incorrectly compared the fair-sample numerator with the "
            "all-Stage-07 kindness count"
        ),
        "preexisting_certified_authority": dict(numerator_authority),
        "timing": (
            "correction made after observing the aggregate fair-sample numerator "
            "count but before constructing ambient-kindness exposures or estimating "
            "any C13 association"
        ),
        "c13_coefficients_or_p_values_seen_before_correction": False,
        "selection_on_c13_model_result": False,
        "scientific_sample_or_model_changed": False,
    }
    common.atomic_json(
        public_stage / "c13_numerator_authority_correction_v104.json",
        numerator_reconciliation,
    )
    print(
        "C13_V104_FAIR_NUMERATOR_AUTHORITY_OK "
        f"rows={kind_receipt['rows']:,} kind_draws={kind_receipt['kind_draws']:,}",
        flush=True,
    )
    daily_kind = build_daily_kind(
        kind_events=kind_events,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    model_cache = build_model_cache(
        support=support_cache,
        kind_events=kind_events,
        daily_kind=daily_kind,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    result = estimate(model_cache)
    common.atomic_json(public_stage / "c13_results.json", result)
    common.write_csv(public_stage / "c13_models.csv", result["models"])
    common.write_csv(public_stage / "c13_model_attempts.csv", result["model_attempts"])
    if result["quartile_model"]:
        common.write_csv(public_stage / "c13_adjusted_quartile_model.csv", result["quartile_model"])
    common.write_csv(public_stage / "c13_descriptive_quartiles.csv", result["descriptive_quartiles"])
    summary = {
        "status": "CAMPAIGN1_C13_V104_COMPLETE",
        "result_status": result["status"],
        "created_utc": common.utc_now(),
        "runtime_seconds": time.time() - started,
        "primary_supported_rows": support["primary_supported_rows"],
        "superseded_wave0_supported_rows": WAVE0_PRIMARY_SUPPORTED_ROWS,
        "wave0_minus_corrected_supported_rows": (
            WAVE0_PRIMARY_SUPPORTED_ROWS - support["primary_supported_rows"]
        ),
        "denominator_correction_frozen_before_numerator": True,
        "source_v102_denominator_parquets_reused_read_only": True,
        "fair_sample_kind_draws": EXPECTED_FAIR_KIND_DRAWS,
        "all_stage07_kind_draws": EXPECTED_ALL_STAGE07_KIND_DRAWS,
        "numerator_authority_correction": numerator_reconciliation,
        "primary": result["primary"],
        "primary_estimable": result["primary_estimable"],
        "model_attempts_total": result["model_attempts_total"],
        "models_estimated": result["models_estimated"],
        "extended_absorption_successes": result["extended_absorption_successes"],
        "retained_model_failures": result["retained_model_failures"],
        "account_level_output": False,
        "api_requests": 0,
        "profile_or_patron_reads": 0,
    }
    common.atomic_json(public_stage / "summary.json", summary)
    return summary


def self_test() -> None:
    np = common.import_numpy()
    total_n, chooser_n = 10_000, 250
    total_k, chooser_k = 400, 25
    other_n = total_n - chooser_n
    other_k = total_k - chooser_k
    rate = other_k / other_n
    if other_n != 9_750 or other_k != 375 or not math.isclose(rate, 0.038461538461538464):
        raise RuntimeError("C13 leave-one-chooser-out self-test failed")
    coefficient_probability_per_pct = 0.0002
    if not math.isclose(100.0 * coefficient_probability_per_pct, 0.02):
        raise RuntimeError("C13 percentage-point reporting self-test failed")
    original_fit = globals()["_fit"]

    def unestimable_stub(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Exposure has no residual variation: x")

    globals()["_fit"] = unestimable_stub
    try:
        recovered, attempt = _attempt_model(
            data={"chooser_id": np.arange(8)},
            sample=np.ones(8, dtype=bool),
            exposures={"x": np.arange(8, dtype=float)},
            label="C13_retained_failure_self_test",
            analysis_role="self_test",
        )
    finally:
        globals()["_fit"] = original_fit
    if (
        recovered
        or attempt["final_status"] != "UNESTIMABLE_RETAINED"
        or attempt["numerical_estimate_emitted"] is not False
    ):
        raise RuntimeError("C13 retained-model-failure self-test failed")
    if (
        EXPECTED_PRIMARY_SUPPORTED_ROWS != 17_101_141
        or WAVE0_PRIMARY_SUPPORTED_ROWS - EXPECTED_PRIMARY_SUPPORTED_ROWS != 3_008
    ):
        raise RuntimeError("C13 denominator-correction self-test failed")
    if (
        EXPECTED_FAIR_KIND_DRAWS != 487_170
        or EXPECTED_ALL_STAGE07_KIND_DRAWS != 669_503
        or EXPECTED_FAIR_KIND_DRAWS >= EXPECTED_ALL_STAGE07_KIND_DRAWS
    ):
        raise RuntimeError("C13 numerator-authority self-test failed")
    print("CAMPAIGN1_C13_V104_SELF_TEST_OK")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
