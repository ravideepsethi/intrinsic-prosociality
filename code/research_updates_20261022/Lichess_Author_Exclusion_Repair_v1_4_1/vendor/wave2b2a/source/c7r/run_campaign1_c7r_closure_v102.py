#!/usr/bin/env python3
"""Campaign 1 C7R repeat-pair and relationship closure.

The support/prevalence caches are frozen without the focal kindness outcome.
Only after all conservation and switcher checks pass is the outcome joined.
All public products are aggregate-only.
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
import c7r_modeling_v102 as modeling


SCRIPT_VERSION = "1.0.2"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
STAGE07_RELATIVE = Path("derived/replication/analysis_panel_24m_sf100k")
HISTORY_STATE_RELATIVE = Path(
    "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
)
C7X_STATE_RELATIVE = Path(
    "derived/replication/dynamics_campaign1_c7x_fullpanel_v101_PRIVATE"
)
STATE_RELATIVE = Path(
    "derived/replication/dynamics_campaign1_c7r_closure_v102_PRIVATE"
)
OUTPUT_RELATIVE = Path("output/dynamics_campaign1_c7r_closure_v102")
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_HISTORY_SUCCESS_SHA256 = (
    "62e4b8335b188f374f83bf1debedc19c62a91769f89a7c12368a628cb26d6de5"
)
EXPECTED_HISTORY_STATUS = "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK"
EXPECTED_C7X_CLASSIFICATION_SHA256 = (
    "998b6087806b8300718897537b67828cc893259d96023a92d91de9ed64e331ed"
)
EXPECTED_C7X_CLASSIFICATION_ROWS = 27_627
EXPECTED_C7X_PRIMARY_COEFFICIENT = 0.14556932160589928
EXPECTED_C7X_PRIMARY_STANDARD_ERROR = 0.020351569816937143
EXPECTED_C7X_CONFIG_SHA256 = (
    "205f106fcfc2dbe2495e25d1d7acb3b2848f8a7bd577603e5a8a77466a20ff1f"
)
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_FAIR_ROWS = 17_328_130
EXPECTED_PAIR_EVENT_ROWS = 154_693_194
PAIR_SEED = 2_026_082_203
PAIR_SAMPLE_DENOMINATOR = 50
PAIR_BUCKETS = 16
MINIMUM_FREE_BYTES = 25 * 1024**3
PLY_BANDS = ("0-4", "5-6", "7-8", "9-10", "11-20", "21-40", "41-80", "81+")
FAIRNESS_BINS = (
    "disconnected_clearly_better",
    "disconnected_better",
    "roughly_equal",
    "modestly_worse_excluded",
    "clearly_worse",
)
FIRST_MEETING_MODEL_NAMES = (
    "X_C7R_fair_vs_clearly_worse_all_meetings",
    "X_C7R_fair_vs_clearly_worse_first_meetings",
    "X_C7R_fair_vs_clearly_worse_repeat_meetings",
    "X_C7R_fair_repeat_interaction_all_meetings",
    "X_C7R_repeat_association_within_fair",
    "X_C7R_nonnegative_vs_costly_all_meetings",
    "X_C7R_nonnegative_vs_costly_first_meetings",
    "X_C7R_nonnegative_vs_costly_repeat_meetings",
    "X_C7R_positive_vs_negative_all_meetings",
    "X_C7R_positive_vs_negative_first_meetings",
    "X_C7R_positive_vs_negative_repeat_meetings",
)
C7X_RELATIONSHIP_MODEL_NAMES = (
    "X_C7R_C7X_primary_exact_replication",
    "X_C7R_C7X_chooser_switchers_only",
    "X_C7R_C7X_chooser_and_opponent_fe",
    "X_C7R_C7X_directed_pair_fe_chooser_cluster",
    "X_C7R_C7X_directed_pair_fe_unordered_pair_cluster",
    "X_C7R_C7X_directed_pair_fe_ply_gt10",
    "X_C7R_C7X_le7d_exact_chooser_fe",
    "X_C7R_C7X_le7d_directed_pair_fe",
)


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


def pair_sequence_band_sql(field: str) -> str:
    return f"""
      CASE
        WHEN CAST({field} AS BIGINT) = 1 THEN '1'
        WHEN CAST({field} AS BIGINT) = 2 THEN '2'
        WHEN CAST({field} AS BIGINT) <= 5 THEN '3-5'
        WHEN CAST({field} AS BIGINT) <= 10 THEN '6-10'
        ELSE '11+'
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
        rows.append({"file": relative, "bytes": path.stat().st_size, "sha256": expected})
        listed.add(relative)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    if listed != actual:
        raise RuntimeError(
            f"Package manifest inventory changed: missing={sorted(actual-listed)} "
            f"extra={sorted(listed-actual)}"
        )
    return rows


def config_payload(root: Path) -> dict[str, Any]:
    contract = root / "payload/docs/C7R_FROZEN_ANALYSIS_CONTRACT_20260828.md"
    return {
        "script_version": SCRIPT_VERSION,
        "contract_sha256": common.sha256_file(contract),
        "main_script_sha256": common.sha256_file(Path(__file__).resolve()),
        "modeling_script_sha256": common.sha256_file(
            root / "payload/code/c7r_modeling_v102.py"
        ),
        "common_script_sha256": common.sha256_file(
            root / "payload/code/campaign1_nonprofile_common_v102.py"
        ),
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "history_success_sha256": EXPECTED_HISTORY_SUCCESS_SHA256,
        "c7x_classification_sha256": EXPECTED_C7X_CLASSIFICATION_SHA256,
        "pair_seed": PAIR_SEED,
        "pair_sample_denominator": PAIR_SAMPLE_DENOMINATOR,
        "first_meeting_models": list(FIRST_MEETING_MODEL_NAMES),
        "c7x_relationship_models": list(C7X_RELATIONSHIP_MODEL_NAMES),
        "ply_bands": list(PLY_BANDS),
        "epistemic_label": "X",
        "causal_claim": False,
    }


def pair_paths(state: Path) -> list[Path]:
    paths = [state / "pair_history_processed" / f"bucket_{index:02d}.parquet" for index in range(PAIR_BUCKETS)]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Pair-history bucket authority incomplete: {missing[:4]}")
    return paths


def pair_event_paths(state: Path) -> list[Path]:
    root = state / "pair_events"
    paths = sorted(path for path in root.rglob("*.parquet") if path.is_file())
    if not paths:
        raise RuntimeError(f"Raw sampled pair-event authority is missing: {root}")
    return paths


def validate_history_public_authority(
    public: Mapping[str, Any], summary: Mapping[str, Any],
    observed_summary_sha256: str,
) -> int:
    """Validate the frozen physical v1.0.0 history run's public receipts."""
    if public.get("status") != EXPECTED_HISTORY_STATUS:
        raise RuntimeError(
            "Pair-history public status changed: "
            f"expected={EXPECTED_HISTORY_STATUS} observed={public.get('status')}"
        )
    if public.get("summary_sha256") != observed_summary_sha256:
        raise RuntimeError("Pair-history public summary hash changed")
    if summary.get("status") != EXPECTED_HISTORY_STATUS:
        raise RuntimeError("Pair-history summary status changed")
    processed_pair_rows = int(summary.get("processed_pair_rows", -1))
    if processed_pair_rows <= 0:
        raise RuntimeError("Pair-history public processed-row authority is invalid")
    if int(summary.get("pair_sample_denominator", -1)) != PAIR_SAMPLE_DENOMINATOR:
        raise RuntimeError("Pair-history sampling denominator changed")
    if int(summary.get("identifier_buckets", -1)) != PAIR_BUCKETS:
        raise RuntimeError("Pair-history identifier-bucket count changed")
    if summary.get("hypothesis_effect_estimated") is not False:
        raise RuntimeError("Pair-history build crossed its hypothesis boundary")
    if summary.get("patron_profile_input_read") is not False:
        raise RuntimeError("Pair-history build read prohibited patron/profile input")
    if public.get("checkpoint_config_sha256") != summary.get("checkpoint_config_sha256"):
        raise RuntimeError("Pair-history checkpoint configuration authority changed")
    return processed_pair_rows


def authenticate_pair_history(
    state: Path,
    processed_paths: Sequence[Path],
    event_paths: Sequence[Path],
) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    project = state.parents[2]
    success = project / "output/dynamic_second_wave_history_v100/20260822T150914Z/_SUCCESS.json"
    if not success.is_file() or common.sha256_file(success) != EXPECTED_HISTORY_SUCCESS_SHA256:
        raise RuntimeError("Pair-history public success authority changed or is missing")
    public = common.load_json(success)
    summary_path = success.parent / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError("Pair-history public summary is missing")
    summary = common.load_json(summary_path)
    processed_pair_rows = validate_history_public_authority(
        public, summary, common.sha256_file(summary_path)
    )
    checkpoint_config_sha256 = str(summary["checkpoint_config_sha256"])
    authenticated: list[dict[str, Any]] = []
    for bucket, path in enumerate(processed_paths):
        receipt_path = state / "pair_bucket_receipts" / f"bucket_{bucket:02d}.json"
        if not receipt_path.is_file():
            raise RuntimeError(f"Pair-history receipt missing: bucket {bucket}")
        receipt = common.load_json(receipt_path)
        actual = {
            "bucket": bucket,
            "rows": int(pq.ParquetFile(path).metadata.num_rows),
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        }
        expected = {
            "status": "DYNAMIC_SECOND_WAVE_PAIR_BUCKET_OK",
            "config_sha256": checkpoint_config_sha256,
            "bucket": bucket,
            "output_path": str(path),
            "output_rows": actual["rows"],
            "output_bytes": actual["bytes"],
            "output_sha256": actual["sha256"],
        }
        for key, value in expected.items():
            if receipt.get(key) != value:
                raise RuntimeError(f"Pair-history checkpoint mismatch: bucket={bucket} key={key}")
        authenticated.append(actual)
    if sum(row["rows"] for row in authenticated) != processed_pair_rows:
        raise RuntimeError("Pair-history physical rows do not conserve")
    processed_hashes = [row["sha256"] for row in authenticated]
    if common.sha256_json(processed_hashes) != public.get(
        "private_pair_bucket_bundle_sha256"
    ):
        raise RuntimeError("Pair-history public/private bucket bundle changed")

    event_root = state / "pair_events"
    event_receipt_path = state / "pair_events_receipt.json"
    if not event_receipt_path.is_file():
        raise RuntimeError("Raw sampled pair-event receipt is missing")
    event_receipt = common.load_json(event_receipt_path)
    event_manifest = common.directory_manifest(event_root)
    if len(event_manifest) != len(event_paths):
        raise RuntimeError("Raw sampled pair-event inventory changed during authentication")
    event_rows = sum(int(row["rows"]) for row in event_manifest)
    expected_event = {
        "status": "DYNAMIC_SECOND_WAVE_PAIR_EVENTS_OK",
        "config_sha256": checkpoint_config_sha256,
        "file_manifest_sha256": common.sha256_json(event_manifest),
        "rows": EXPECTED_PAIR_EVENT_ROWS,
    }
    for key, value in expected_event.items():
        if event_receipt.get(key) != value:
            raise RuntimeError(f"Raw sampled pair-event checkpoint mismatch: {key}")
    if event_rows != EXPECTED_PAIR_EVENT_ROWS:
        raise RuntimeError("Raw sampled pair-event physical rows do not conserve")
    return {
        "success_sha256": EXPECTED_HISTORY_SUCCESS_SHA256,
        "processed_bucket_files": len(authenticated),
        "processed_rows": processed_pair_rows,
        "physical_bucket_manifest_sha256": common.sha256_json(authenticated),
        "raw_pair_event_files": len(event_manifest),
        "raw_pair_event_rows": event_rows,
        "raw_pair_event_manifest_sha256": common.sha256_json(event_manifest),
    }


def checkpoint(
    *, output: Path, receipt: Path, config_sha256: str, status: str,
    expected_rows: int | None = None,
) -> dict[str, Any] | None:
    _, _, _, pq = common.import_dependencies()
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial private checkpoint: {output.name}")
    saved = common.load_json(receipt)
    observed = {
        "status": status,
        "config_sha256": config_sha256,
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": common.sha256_file(output),
    }
    if expected_rows is not None and observed["output_rows"] != expected_rows:
        raise RuntimeError(f"Checkpoint row authority changed: {output.name}")
    for key, value in observed.items():
        if saved.get(key) != value:
            raise RuntimeError(f"Private checkpoint mismatch: {output.name} {key}")
    return saved


def finish_checkpoint(
    *, output: Path, receipt: Path, config_sha256: str, status: str,
    qa: Mapping[str, Any],
) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    saved = {
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
    common.atomic_json(receipt, saved)
    return saved


def build_pair_support_cache(
    *, stage_paths: Sequence[Path], history_paths: Sequence[Path],
    event_paths: Sequence[Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c7r_pair_support_private.parquet"
    receipt = state / "c7r_pair_support_receipt.json"
    saved = checkpoint(
        output=output, receipt=receipt, config_sha256=config_sha256,
        status="C7R_PAIR_SUPPORT_OUTCOME_FREE_OK",
    )
    if saved is not None:
        forbidden = {"kind_draw", "outcome_kind_draw", "kind"}.intersection(
            pq.ParquetFile(output).schema_arrow.names
        )
        if forbidden:
            raise RuntimeError("Focal outcome entered pair-support checkpoint")
        print("C7R_PAIR_SUPPORT_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved
    print("C7R_PAIR_SUPPORT_BUILD_BEGIN", flush=True)
    connection = duckdb.connect()
    common.configure_duckdb(
        connection, threads=threads, memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/pair_support",
    )
    speed = common.speed_code_sql("t.api_speed")
    evaluation = common.eval_bin_sql("t.engine_eval_cp_disconnected")
    hour = common.hour_of_week_sql("t.api_last_move_at_ms")
    ply = ply_band_sql("t.ply_count")
    sequence_band = pair_sequence_band_sql("h.pair_sequence")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    # The focal table is deliberately outcome-free. It contains every Stage 07
    # row in the deterministic pair sample, not only fair targets.
    connection.execute(
        f"""
        CREATE TEMP TABLE sampled_focals AS
          SELECT
            LEAST(
              CAST(chooser_user_id AS BIGINT),
              CAST(disconnected_user_id AS BIGINT)
            ) AS low_id,
            GREATEST(
              CAST(chooser_user_id AS BIGINT),
              CAST(disconnected_user_id AS BIGINT)
            ) AS high_id,
            CAST(game_id AS VARCHAR) AS game_id,
            CAST(chooser_user_id AS BIGINT) AS chooser_user_id,
            CAST(disconnected_user_id AS BIGINT) AS disconnected_user_id,
            CAST(engine_fairness_bin AS VARCHAR) AS engine_fairness_bin,
            CAST(fair_competitive AS BOOLEAN) AS fair_competitive,
            CAST(clearly_worse AS BOOLEAN) AS clearly_worse,
            CAST(draw_nonnegative AS BOOLEAN) AS draw_nonnegative,
            CAST(draw_strict_positive AS BOOLEAN) AS draw_strict_positive,
            CAST(draw_costly AS BOOLEAN) AS draw_costly,
            CAST(engine_eval_cp_disconnected AS DOUBLE)
              AS engine_eval_cp_disconnected,
            CAST(api_speed AS VARCHAR) AS api_speed,
            CAST(month AS VARCHAR) AS month,
            CAST(api_last_move_at_ms AS BIGINT) AS api_last_move_at_ms,
            CAST(ply_count AS BIGINT) AS ply_count,
            CAST(chooser_draw_payoff_v2 AS DOUBLE) AS chooser_draw_payoff_v2,
            CAST(chooser_win_premium_v2 AS DOUBLE) AS chooser_win_premium_v2,
            CAST(chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock_last_obs_s,
            CAST(disconnected_clock_last_obs_s AS DOUBLE)
              AS disconnected_clock_last_obs_s,
            CAST(chooser_elo AS DOUBLE) AS chooser_elo,
            CAST(disconnected_elo AS DOUBLE) AS disconnected_elo,
            CAST(chooser_pre_rd_v2 AS DOUBLE) AS chooser_pre_rd_v2,
            CAST(disconnected_pre_rd_v2 AS DOUBLE) AS disconnected_pre_rd_v2,
            CAST(tournament_like_event AS DOUBLE) AS tournament_like_event
          FROM read_parquet(
            {common.path_list_literal(stage_paths)}, union_by_name=true
          )
          WHERE game_id IS NOT NULL
            AND chooser_user_id IS NOT NULL
            AND disconnected_user_id IS NOT NULL
            AND hash(
              LEAST(
                CAST(chooser_user_id AS BIGINT),
                CAST(disconnected_user_id AS BIGINT)
              ),
              GREATEST(
                CAST(chooser_user_id AS BIGINT),
                CAST(disconnected_user_id AS BIGINT)
              ),
              {PAIR_SEED}
            ) % {PAIR_SAMPLE_DENOMINATOR}=0
        """
    )
    connection.execute(
        "CREATE TEMP TABLE target_pairs AS "
        "SELECT DISTINCT low_id, high_id FROM sampled_focals"
    )
    connection.execute(
        f"""
        COPY (
          WITH selected_history AS (
            SELECT
              CAST(e.low_id AS BIGINT) AS low_id,
              CAST(e.high_id AS BIGINT) AS high_id,
              CAST(e.utc_ms AS BIGINT) AS utc_ms,
              CAST(e.archive_ordinal AS BIGINT) AS archive_ordinal,
              CAST(e.game_id AS VARCHAR) AS game_id
            FROM read_parquet(
              {common.path_list_literal(event_paths)}, union_by_name=true
            ) e
            SEMI JOIN target_pairs p
              ON p.low_id=CAST(e.low_id AS BIGINT)
             AND p.high_id=CAST(e.high_id AS BIGINT)
          ), sequenced AS (
            SELECT *, ROW_NUMBER() OVER (
              PARTITION BY low_id, high_id
              ORDER BY utc_ms, archive_ordinal, game_id
            ) AS pair_sequence
            FROM selected_history
          )
          SELECT
            t.low_id, t.high_id, t.game_id,
            CAST(h.pair_sequence AS BIGINT) AS pair_sequence,
            CAST(h.pair_sequence=1 AS BOOLEAN) AS first_meeting,
            CAST(h.pair_sequence>1 AS BOOLEAN) AS repeat_meeting,
            CAST({sequence_band} AS VARCHAR) AS pair_sequence_band,
            t.chooser_user_id AS chooser_id,
            t.disconnected_user_id AS opponent_id,
            CAST(hash(t.low_id, t.high_id) % 9223372036854775807 AS BIGINT)
              AS pair_hash,
            CAST(hash(t.game_id) % 9223372036854775807 AS BIGINT)
              AS row_hash,
            t.engine_fairness_bin AS fairness_bin,
            t.fair_competitive AS fair,
            t.clearly_worse AS clearly_worse,
            t.draw_nonnegative,
            t.draw_strict_positive,
            t.draw_costly,
            CAST({evaluation} AS INTEGER) AS eval_bin,
            CAST({speed} AS INTEGER) AS speed_code,
            CAST(date_diff(
              'month', DATE '2023-11-01',
              strptime(t.month || '-01', '%Y-%m-%d')
            ) AS INTEGER) AS month_code,
            CAST({hour} AS INTEGER) AS hour_of_week,
            t.ply_count,
            CAST({ply} AS INTEGER) AS ply_band,
            t.chooser_draw_payoff_v2 AS draw_payoff,
            t.chooser_win_premium_v2 AS win_premium,
            t.chooser_clock_last_obs_s AS chooser_clock,
            t.disconnected_clock_last_obs_s AS opponent_clock,
            t.chooser_elo,
            t.disconnected_elo AS opponent_elo,
            t.chooser_pre_rd_v2 AS chooser_rd,
            t.disconnected_pre_rd_v2 AS opponent_rd,
            t.tournament_like_event AS tournament
          FROM sampled_focals t
          INNER JOIN sequenced h
            ON h.low_id=t.low_id AND h.high_id=t.high_id AND h.game_id=t.game_id
          ORDER BY t.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    direct = connection.execute(
        "SELECT COUNT(*), COUNT(DISTINCT game_id) FROM sampled_focals"
    ).fetchone()
    qa_row = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
          COUNT(*) FILTER (WHERE pair_sequence=1),
          COUNT(*) FILTER (WHERE pair_sequence>1),
          COUNT(*) FILTER (WHERE pair_sequence IS NULL OR pair_sequence<1),
          COUNT(*) FILTER (
            WHERE chooser_id IS NULL OR opponent_id IS NULL OR ply_band NOT BETWEEN 0 AND 7
          )
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    crosscheck = connection.execute(
        f"""
        WITH certified AS (
          SELECT CAST(game_id AS VARCHAR) AS game_id,
            CAST(pair_sequence AS BIGINT) AS pair_sequence
          FROM read_parquet(
            {common.path_list_literal(history_paths)}, union_by_name=true
          )
          WHERE CAST(is_stage07_target AS BOOLEAN)
        ), fair_output AS (
          SELECT game_id, pair_sequence
          FROM read_parquet({common.sql_literal(temporary)})
          WHERE fair
        ), compared AS (
          SELECT
            o.game_id AS output_game_id,
            c.game_id AS certified_game_id,
            o.pair_sequence AS output_pair_sequence,
            c.pair_sequence AS certified_pair_sequence
          FROM fair_output o
          FULL OUTER JOIN certified c ON c.game_id=o.game_id
        )
        SELECT
          (SELECT COUNT(*) FROM fair_output),
          (SELECT COUNT(DISTINCT game_id) FROM fair_output),
          (SELECT COUNT(*) FROM certified),
          (SELECT COUNT(DISTINCT game_id) FROM certified),
          COUNT(*) FILTER (
            WHERE output_game_id IS NULL OR certified_game_id IS NULL
          ),
          COUNT(*) FILTER (
            WHERE output_game_id IS NOT NULL AND certified_game_id IS NOT NULL
              AND output_pair_sequence<>certified_pair_sequence
          )
        FROM compared
        """
    ).fetchone()
    connection.close()
    forbidden = {"kind_draw", "outcome_kind_draw", "kind"}.intersection(
        pq.ParquetFile(temporary).schema_arrow.names
    )
    qa = {
        "rows": int(qa_row[0]),
        "unique_games": int(qa_row[1]),
        "first_meetings": int(qa_row[2]),
        "repeat_meetings": int(qa_row[3]),
        "bad_pair_sequence_rows": int(qa_row[4]),
        "bad_key_or_ply_rows": int(qa_row[5]),
        "direct_stage07_pair_sample_rows": int(direct[0]),
        "direct_stage07_pair_sample_unique_games": int(direct[1]),
        "fair_rows_crosschecked": int(crosscheck[0]),
        "fair_unique_games_crosschecked": int(crosscheck[1]),
        "certified_fair_target_rows": int(crosscheck[2]),
        "certified_fair_target_unique_games": int(crosscheck[3]),
        "fair_crosscheck_missing_rows": int(crosscheck[4]),
        "fair_crosscheck_pair_sequence_mismatches": int(crosscheck[5]),
        "focal_outcome_columns_present": sorted(forbidden),
        "focal_kind_outcome_read": False,
        "pair_sequence_source": "authenticated raw sampled pair-event layer",
    }
    if (
        qa["rows"] <= 0
        or qa["rows"] != qa["unique_games"]
        or qa["rows"] != qa["first_meetings"] + qa["repeat_meetings"]
        or qa["rows"] != qa["direct_stage07_pair_sample_rows"]
        or qa["rows"] != qa["direct_stage07_pair_sample_unique_games"]
        or qa["fair_rows_crosschecked"] != qa["fair_unique_games_crosschecked"]
        or qa["certified_fair_target_rows"]
        != qa["certified_fair_target_unique_games"]
        or qa["fair_rows_crosschecked"] != qa["certified_fair_target_rows"]
        or qa["fair_crosscheck_missing_rows"]
        or qa["fair_crosscheck_pair_sequence_mismatches"]
        or qa["bad_pair_sequence_rows"]
        or qa["bad_key_or_ply_rows"]
        or forbidden
    ):
        raise RuntimeError(f"C7R pair-support conservation failed: {qa}")
    os.replace(temporary, output)
    saved = finish_checkpoint(
        output=output, receipt=receipt, config_sha256=config_sha256,
        status="C7R_PAIR_SUPPORT_OUTCOME_FREE_OK", qa=qa,
    )
    shutil.rmtree(state / "duckdb_temp/pair_support", ignore_errors=True)
    print(
        f"C7R_PAIR_SUPPORT_BUILD_OK rows={qa['rows']:,} "
        f"first={qa['first_meetings']:,} repeat={qa['repeat_meetings']:,}",
        flush=True,
    )
    return output, saved


def freeze_pair_prevalence(
    *, support_cache: Path, state: Path, config_sha256: str,
) -> dict[str, Any]:
    duckdb, _, _, _ = common.import_dependencies()
    path = state / "c7r_repeat_prevalence_frozen_before_outcome.json"
    connection = duckdb.connect()
    contexts = connection.execute(
        f"""
        SELECT context, rows, repeat_rows FROM (
          SELECT 'all_sampled' AS context, COUNT(*) AS rows,
            COUNT(*) FILTER (WHERE repeat_meeting) AS repeat_rows
          FROM read_parquet({common.sql_literal(support_cache)})
          UNION ALL
          SELECT 'fair', COUNT(*), COUNT(*) FILTER (WHERE repeat_meeting)
          FROM read_parquet({common.sql_literal(support_cache)}) WHERE fair
          UNION ALL
          SELECT 'clearly_worse', COUNT(*), COUNT(*) FILTER (WHERE repeat_meeting)
          FROM read_parquet({common.sql_literal(support_cache)}) WHERE clearly_worse
        ) ORDER BY context
        """
    ).fetchall()
    fairness = connection.execute(
        f"""
        SELECT fairness_bin, COUNT(*) AS rows,
          COUNT(*) FILTER (WHERE repeat_meeting) AS repeat_rows
        FROM read_parquet({common.sql_literal(support_cache)})
        GROUP BY fairness_bin ORDER BY fairness_bin
        """
    ).fetchall()
    sequence = connection.execute(
        f"""
        SELECT pair_sequence_band, COUNT(*) AS rows,
          COUNT(*) FILTER (WHERE fair) AS fair_rows,
          COUNT(*) FILTER (WHERE clearly_worse) AS clearly_worse_rows
        FROM read_parquet({common.sql_literal(support_cache)})
        GROUP BY pair_sequence_band
        ORDER BY CASE pair_sequence_band WHEN '1' THEN 1 WHEN '2' THEN 2
          WHEN '3-5' THEN 3 WHEN '6-10' THEN 4 ELSE 5 END
        """
    ).fetchall()
    support = connection.execute(
        f"""
        SELECT COUNT(DISTINCT chooser_id), COUNT(DISTINCT opponent_id),
          COUNT(DISTINCT pair_hash),
          COUNT(DISTINCT ROW(chooser_id, opponent_id))
        FROM read_parquet({common.sql_literal(support_cache)})
        """
    ).fetchone()
    connection.close()

    def prevalence_row(label: str, rows: int, repeat_rows: int) -> dict[str, Any]:
        return {
            "scope": label,
            "rows": int(rows),
            "first_meeting_rows": int(rows) - int(repeat_rows),
            "repeat_meeting_rows": int(repeat_rows),
            "repeat_meeting_share_pct": 100.0 * int(repeat_rows) / int(rows) if rows else None,
        }

    payload = {
        "status": "C7R_REPEAT_PREVALENCE_FROZEN_BEFORE_FOCAL_OUTCOME",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "support_cache_sha256": common.sha256_file(support_cache),
        "pair_sample_rule": f"hash(low_id,high_id,{PAIR_SEED}) % {PAIR_SAMPLE_DENOMINATOR} = 0",
        "first_meeting_definition": "pair_sequence == 1 in certified rated chronology beginning 2013",
        "scope_limit": "does not observe casual, off-platform, or pre-2013 relationships",
        "contexts": [prevalence_row(*row) for row in contexts],
        "fairness_bins": [prevalence_row(str(row[0]), int(row[1]), int(row[2])) for row in fairness],
        "pair_sequence_bands": [
            {
                "pair_sequence_band": str(row[0]),
                "rows": int(row[1]),
                "fair_rows": int(row[2]),
                "clearly_worse_rows": int(row[3]),
            }
            for row in sequence
        ],
        "identity_support": {
            "chooser_ids": int(support[0]),
            "opponent_ids": int(support[1]),
            "unordered_pairs": int(support[2]),
            "directed_pairs": int(support[3]),
        },
        "focal_kind_outcome_read": False,
        "epistemic_label": "X",
        "causal_claim": False,
    }
    if path.is_file():
        saved = common.load_json(path)
        for key in (
            "config_sha256", "support_cache_sha256", "contexts",
            "fairness_bins", "pair_sequence_bands", "identity_support",
            "focal_kind_outcome_read",
        ):
            if saved.get(key) != payload.get(key):
                raise RuntimeError(f"Frozen C7R repeat prevalence changed: {key}")
        return saved
    common.atomic_json(path, payload)
    print("C7R_REPEAT_PREVALENCE_FROZEN_BEFORE_OUTCOME_OK", flush=True)
    return payload


def build_pair_model_cache(
    *, support_cache: Path, stage_paths: Sequence[Path], state: Path,
    threads: int, memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c7r_pair_model_private.parquet"
    receipt = state / "c7r_pair_model_receipt.json"
    rows = common.parquet_rows([support_cache])
    saved = checkpoint(
        output=output, receipt=receipt, config_sha256=config_sha256,
        status="C7R_PAIR_MODEL_PRIVATE_OK", expected_rows=rows,
    )
    if saved is not None:
        print("C7R_PAIR_MODEL_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved
    print("C7R_PAIR_FOCAL_OUTCOME_JOIN_BEGIN", flush=True)
    connection = duckdb.connect()
    common.configure_duckdb(
        connection, threads=threads, memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/pair_model",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT c.*, CAST(s.outcome_kind_draw AS DOUBLE) AS kind
          FROM read_parquet({common.sql_literal(support_cache)}) c
          INNER JOIN read_parquet(
            {common.path_list_literal(stage_paths)}, union_by_name=true
          ) s ON CAST(s.game_id AS VARCHAR)=c.game_id
          ORDER BY c.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa_row = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
          COUNT(*) FILTER (WHERE kind IS NULL), SUM(CAST(kind AS BIGINT))
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
    if qa["rows"] != rows or qa["unique_games"] != rows or qa["null_kind_rows"]:
        raise RuntimeError(f"C7R pair outcome join failed: {qa}")
    os.replace(temporary, output)
    saved = finish_checkpoint(
        output=output, receipt=receipt, config_sha256=config_sha256,
        status="C7R_PAIR_MODEL_PRIVATE_OK", qa=qa,
    )
    shutil.rmtree(state / "duckdb_temp/pair_model", ignore_errors=True)
    print(f"C7R_PAIR_FOCAL_OUTCOME_JOIN_OK rows={rows:,}", flush=True)
    return output, saved


PAIR_MODEL_COLUMNS = (
    "pair_sequence", "first_meeting", "repeat_meeting", "fair",
    "clearly_worse", "draw_nonnegative", "draw_strict_positive", "draw_costly",
    "chooser_id", "opponent_id", "pair_hash", "row_hash", "eval_bin",
    "speed_code", "month_code", "hour_of_week", "ply_count", "ply_band",
    "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
    "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd", "tournament",
    "kind",
)


def load_numpy(path: Path, columns: Sequence[str], threads: int) -> dict[str, Any]:
    _, _, pa, pq = common.import_dependencies()
    pa.set_cpu_count(int(threads))
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


def current_controls(data: Mapping[str, Any], indices: Any, *, include_draw_payoff: bool) -> dict[str, Any]:
    names = [
        "win_premium", "chooser_clock", "opponent_clock", "chooser_elo",
        "opponent_elo", "chooser_rd", "opponent_rd", "tournament",
    ]
    if include_draw_payoff:
        names.insert(0, "draw_payoff")
    return {name: data[name][indices] for name in names}


def attempt_hdfe(
    *, data: Mapping[str, Any], sample: Any, exposures: Mapping[str, Any],
    model: str, fixed_effect_names: Sequence[str], cluster_name: str = "chooser_id",
    include_draw_payoff: bool = True, minimum_rows_per_binary_arm: int = 1,
    maximum_iterations: int = 2_000,
) -> dict[str, Any]:
    np = common.import_numpy()
    sample = np.asarray(sample, dtype=bool)
    indices = np.flatnonzero(sample)
    support = {
        "model": model,
        "status": "ATTEMPT_PENDING",
        "rows_requested": int(indices.size),
        "clusters_requested": int(np.unique(data[cluster_name][indices]).size) if indices.size else 0,
        "cluster": cluster_name,
        "fixed_effects_requested": list(fixed_effect_names),
        "epistemic_label": "X",
        "causal_claim": False,
    }
    for name, values in exposures.items():
        selected = np.asarray(values)[indices]
        support[f"{name}_ones_requested"] = int(np.count_nonzero(selected == 1))
        support[f"{name}_zeros_requested"] = int(np.count_nonzero(selected == 0))
        if (
            support[f"{name}_ones_requested"] < minimum_rows_per_binary_arm
            or support[f"{name}_zeros_requested"] < minimum_rows_per_binary_arm
        ):
            return {**support, "status": "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT"}
    if indices.size < 1_000 or support["clusters_requested"] < 100:
        return {**support, "status": "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT"}
    try:
        fitted = common.fit_hdfe_cluster(
            outcome=data["kind"][indices],
            exposures={name: np.asarray(values)[indices] for name, values in exposures.items()},
            numeric_controls=current_controls(data, indices, include_draw_payoff=include_draw_payoff),
            fixed_effects={name: data[name][indices] for name in fixed_effect_names},
            clusters=data[cluster_name][indices],
            row_ids=data["row_hash"][indices],
            specification={
                "model": model,
                "analysis_role": "post-gate exploratory C7R",
                "cluster": cluster_name,
                "causal_claim": False,
                "epistemic_label": "X",
            },
            absorption_maximum_iterations=maximum_iterations,
        )
        return finite({**support, **fitted, "status": "ESTIMATED"})
    except (RuntimeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        return {
            **support,
            "status": "ESTIMATION_FAILURE_RETAINED",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }


def estimate_first_meeting_models(model_cache: Path, threads: int) -> list[dict[str, Any]]:
    np = common.import_numpy()
    data = load_numpy(model_cache, PAIR_MODEL_COLUMNS, threads)
    all_rows = np.ones(data["kind"].size, dtype=bool)
    first = np.asarray(data["first_meeting"], dtype=bool)
    repeat = np.asarray(data["repeat_meeting"], dtype=bool)
    fair = np.asarray(data["fair"], dtype=bool)
    worse = np.asarray(data["clearly_worse"], dtype=bool)
    fairness_sample = fair | worse
    fairness_exposure = fair.astype(np.float64)
    base_fe = ("chooser_id", "speed_code", "month_code", "hour_of_week", "ply_band")
    attempts = [
        attempt_hdfe(
            data=data, sample=fairness_sample & scope,
            exposures={"fair_minus_clearly_worse": fairness_exposure}, model=model,
            fixed_effect_names=base_fe, include_draw_payoff=True,
        )
        for scope, model in (
            (all_rows, FIRST_MEETING_MODEL_NAMES[0]),
            (first, FIRST_MEETING_MODEL_NAMES[1]),
            (repeat, FIRST_MEETING_MODEL_NAMES[2]),
        )
    ]
    attempts.append(
        attempt_hdfe(
            data=data, sample=fairness_sample,
            exposures={
                "fair": fairness_exposure,
                "repeat": repeat.astype(np.float64),
                "fair_x_repeat": (fair & repeat).astype(np.float64),
            },
            model=FIRST_MEETING_MODEL_NAMES[3], fixed_effect_names=base_fe,
            include_draw_payoff=True,
        )
    )
    attempts.append(
        attempt_hdfe(
            data=data, sample=fair,
            exposures={"repeat_meeting": repeat.astype(np.float64)},
            model=FIRST_MEETING_MODEL_NAMES[4],
            fixed_effect_names=("chooser_id", "eval_bin", "speed_code", "month_code", "hour_of_week", "ply_band"),
            include_draw_payoff=True,
        )
    )
    nonnegative = np.asarray(data["draw_nonnegative"], dtype=bool)
    positive = np.asarray(data["draw_strict_positive"], dtype=bool)
    costly = np.asarray(data["draw_costly"], dtype=bool)
    price_fe = ("chooser_id", "eval_bin", "speed_code", "month_code", "hour_of_week", "ply_band")
    for scope, suffix, model in (
        (all_rows, "all", FIRST_MEETING_MODEL_NAMES[5]),
        (first, "first", FIRST_MEETING_MODEL_NAMES[6]),
        (repeat, "repeat", FIRST_MEETING_MODEL_NAMES[7]),
    ):
        del suffix
        attempts.append(
            attempt_hdfe(
                data=data, sample=fair & scope & (nonnegative | costly),
                exposures={"nonnegative_minus_costly": nonnegative.astype(np.float64)},
                model=model, fixed_effect_names=price_fe, include_draw_payoff=False,
            )
        )
    for scope, model in (
        (all_rows, FIRST_MEETING_MODEL_NAMES[8]),
        (first, FIRST_MEETING_MODEL_NAMES[9]),
        (repeat, FIRST_MEETING_MODEL_NAMES[10]),
    ):
        attempts.append(
            attempt_hdfe(
                data=data, sample=fair & scope & (positive | costly),
                exposures={"positive_minus_negative": positive.astype(np.float64)},
                model=model, fixed_effect_names=price_fe, include_draw_payoff=False,
            )
        )
    if tuple(row["model"] for row in attempts) != FIRST_MEETING_MODEL_NAMES:
        raise RuntimeError("C7R first-meeting model inventory changed")
    return attempts


def pair_rates(model_cache: Path) -> list[dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        SELECT scope, meeting, rows, kind_draws FROM (
          SELECT 'all_sampled' AS scope,
            CASE WHEN first_meeting THEN 'first' ELSE 'repeat' END AS meeting,
            COUNT(*) AS rows, SUM(CAST(kind AS BIGINT)) AS kind_draws
          FROM read_parquet({common.sql_literal(model_cache)}) GROUP BY meeting
          UNION ALL
          SELECT 'fair', CASE WHEN first_meeting THEN 'first' ELSE 'repeat' END,
            COUNT(*), SUM(CAST(kind AS BIGINT))
          FROM read_parquet({common.sql_literal(model_cache)}) WHERE fair GROUP BY 2
          UNION ALL
          SELECT 'clearly_worse', CASE WHEN first_meeting THEN 'first' ELSE 'repeat' END,
            COUNT(*), SUM(CAST(kind AS BIGINT))
          FROM read_parquet({common.sql_literal(model_cache)}) WHERE clearly_worse GROUP BY 2
          UNION ALL
          SELECT fairness_bin, CASE WHEN first_meeting THEN 'first' ELSE 'repeat' END,
            COUNT(*), SUM(CAST(kind AS BIGINT))
          FROM read_parquet({common.sql_literal(model_cache)}) GROUP BY fairness_bin, 2
        ) ORDER BY scope, meeting
        """
    ).fetchall()
    connection.close()
    return [
        {
            "scope": str(row[0]),
            "meeting": str(row[1]),
            "rows": int(row[2]),
            "kind_draws": int(row[3]),
            "kind_rate_pct": 100.0 * int(row[3]) / int(row[2]),
        }
        for row in rows
    ]


def authenticate_c7x_classification(project: Path, root: Path) -> tuple[Path, dict[str, Any]]:
    _, _, _, pq = common.import_dependencies()
    authority = common.load_json(root / "payload/frozen_c7x/private_checkpoint_authentication.json")["classification"]
    if (
        authority.get("output_sha256") != EXPECTED_C7X_CLASSIFICATION_SHA256
        or int(authority.get("output_rows", -1)) != EXPECTED_C7X_CLASSIFICATION_ROWS
        or authority.get("config_sha256") != EXPECTED_C7X_CONFIG_SHA256
    ):
        raise RuntimeError("Packaged C7X classification authority changed")
    path = project / C7X_STATE_RELATIVE / "c7x_classification_private.parquet"
    if not path.is_file():
        raise RuntimeError(
            "Authenticated C7X classification checkpoint is missing; run certified C7X v1.0.1 first"
        )
    observed = {
        "path": str(path),
        "rows": int(pq.ParquetFile(path).metadata.num_rows),
        "bytes": path.stat().st_size,
        "sha256": common.sha256_file(path),
    }
    if observed["rows"] != EXPECTED_C7X_CLASSIFICATION_ROWS or observed["sha256"] != EXPECTED_C7X_CLASSIFICATION_SHA256:
        raise RuntimeError("Physical C7X classification checkpoint changed")
    forbidden = {"kind", "kind_draw", "outcome_kind_draw"}.intersection(
        pq.ParquetFile(path).schema_arrow.names
    )
    if forbidden:
        raise RuntimeError("C7X classification contains focal outcome")
    return path, observed


def freeze_c7x_support(classification: Path, state: Path, config_sha256: str) -> dict[str, Any]:
    duckdb, _, _, _ = common.import_dependencies()
    path = state / "c7r_c7x_relationship_support_frozen_before_outcome.json"
    connection = duckdb.connect()
    base = connection.execute(
        f"""
        WITH chooser AS (
          SELECT chooser_id, BOOL_OR(latest_prior_arm=1) AS one,
            BOOL_OR(latest_prior_arm=0) AS zero
          FROM read_parquet({common.sql_literal(classification)}) GROUP BY chooser_id
        ), opponent AS (
          SELECT opponent_id, BOOL_OR(latest_prior_arm=1) AS one,
            BOOL_OR(latest_prior_arm=0) AS zero
          FROM read_parquet({common.sql_literal(classification)}) GROUP BY opponent_id
        ), unordered_pair AS (
          SELECT pair_hash, BOOL_OR(latest_prior_arm=1) AS one,
            BOOL_OR(latest_prior_arm=0) AS zero
          FROM read_parquet({common.sql_literal(classification)}) GROUP BY pair_hash
        ), directed_pair AS (
          SELECT chooser_id, opponent_id, BOOL_OR(latest_prior_arm=1) AS one,
            BOOL_OR(latest_prior_arm=0) AS zero, COUNT(*) AS rows
          FROM read_parquet({common.sql_literal(classification)})
          GROUP BY chooser_id, opponent_id
        )
        SELECT
          (SELECT COUNT(*) FROM read_parquet({common.sql_literal(classification)})),
          (SELECT COUNT(*) FROM chooser WHERE one AND zero),
          (SELECT COUNT(*) FROM opponent WHERE one AND zero),
          (SELECT COUNT(*) FROM unordered_pair WHERE one AND zero),
          (SELECT COUNT(*) FROM directed_pair WHERE one AND zero),
          (SELECT COALESCE(SUM(rows),0) FROM directed_pair WHERE one AND zero)
        """
    ).fetchone()
    recency = connection.execute(
        f"""
        WITH d AS (
          SELECT chooser_id, opponent_id,
            BOOL_OR(latest_prior_arm=1) AS one,
            BOOL_OR(latest_prior_arm=0) AS zero, COUNT(*) AS rows
          FROM read_parquet({common.sql_literal(classification)})
          WHERE latest_gap_days<=7 GROUP BY chooser_id, opponent_id
        )
        SELECT COUNT(*) FILTER (WHERE one AND zero),
          COALESCE(SUM(rows) FILTER (WHERE one AND zero),0),
          COUNT(*) FILTER (WHERE one), COUNT(*) FILTER (WHERE zero)
        FROM d
        """
    ).fetchone()
    connection.close()
    payload = {
        "status": "C7R_C7X_RELATIONSHIP_SUPPORT_FROZEN_BEFORE_FOCAL_OUTCOME",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "classification_sha256": EXPECTED_C7X_CLASSIFICATION_SHA256,
        "rows": int(base[0]),
        "chooser_arm_switchers": int(base[1]),
        "opponent_arm_switchers": int(base[2]),
        "unordered_pair_arm_switchers": int(base[3]),
        "directed_pair_arm_switchers": int(base[4]),
        "rows_in_directed_pair_switchers": int(base[5]),
        "le7d_directed_pair_arm_switchers": int(recency[0]),
        "le7d_rows_in_directed_pair_switchers": int(recency[1]),
        "le7d_directed_pairs_with_benefactor": int(recency[2]),
        "le7d_directed_pairs_with_claimer": int(recency[3]),
        "focal_kind_outcome_read": False,
        "epistemic_label": "X",
        "causal_claim": False,
    }
    if payload["rows"] != EXPECTED_C7X_CLASSIFICATION_ROWS or payload["chooser_arm_switchers"] != 370 or payload["unordered_pair_arm_switchers"] != 320:
        raise RuntimeError(f"C7X outcome-free support failed certified gates: {payload}")
    if path.is_file():
        saved = common.load_json(path)
        for key, value in payload.items():
            if key != "created_utc" and saved.get(key) != value:
                raise RuntimeError(f"Frozen C7X relationship support changed: {key}")
        return saved
    common.atomic_json(path, payload)
    print("C7R_C7X_RELATIONSHIP_SUPPORT_FROZEN_BEFORE_OUTCOME_OK", flush=True)
    return payload


def build_c7x_model_cache(
    *, classification: Path, stage_paths: Sequence[Path], state: Path,
    threads: int, memory_limit: str, config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c7r_c7x_model_private.parquet"
    receipt = state / "c7r_c7x_model_receipt.json"
    saved = checkpoint(
        output=output, receipt=receipt, config_sha256=config_sha256,
        status="C7R_C7X_MODEL_PRIVATE_OK", expected_rows=EXPECTED_C7X_CLASSIFICATION_ROWS,
    )
    if saved is not None:
        print("C7R_C7X_MODEL_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved
    connection = duckdb.connect()
    common.configure_duckdb(
        connection, threads=threads, memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c7x_model",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT c.*, CAST(s.outcome_kind_draw AS DOUBLE) AS kind
          FROM read_parquet({common.sql_literal(classification)}) c
          INNER JOIN read_parquet(
            {common.path_list_literal(stage_paths)}, union_by_name=true
          ) s ON CAST(s.game_id AS VARCHAR)=c.game_id
          ORDER BY c.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa_row = connection.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT game_id), COUNT(*) FILTER (WHERE kind IS NULL), SUM(CAST(kind AS BIGINT)) FROM read_parquet({common.sql_literal(temporary)})"
    ).fetchone()
    connection.close()
    qa = {
        "rows": int(qa_row[0]), "unique_games": int(qa_row[1]),
        "null_kind_rows": int(qa_row[2]), "kind_draws": int(qa_row[3]),
    }
    if qa["rows"] != EXPECTED_C7X_CLASSIFICATION_ROWS or qa["unique_games"] != qa["rows"] or qa["null_kind_rows"]:
        raise RuntimeError(f"C7R C7X focal outcome join failed: {qa}")
    os.replace(temporary, output)
    saved = finish_checkpoint(
        output=output, receipt=receipt, config_sha256=config_sha256,
        status="C7R_C7X_MODEL_PRIVATE_OK", qa=qa,
    )
    shutil.rmtree(state / "duckdb_temp/c7x_model", ignore_errors=True)
    print("C7R_C7X_FOCAL_OUTCOME_JOIN_OK", flush=True)
    return output, saved


C7X_MODEL_COLUMNS = (
    "kind", "latest_prior_arm", "latest_gap_days", "chooser_id", "opponent_id",
    "pair_hash", "row_hash", "eval_bin", "speed_code", "month_code",
    "hour_of_week", "ply_count", "ply_band", "draw_payoff", "win_premium",
    "chooser_clock", "opponent_clock", "chooser_elo", "opponent_elo",
    "chooser_rd", "opponent_rd", "tournament",
)


def attempt_exact_c7x(
    *, data: Mapping[str, Any], sample: Any, model: str, high_dimensional: Any,
    high_dimensional_name: str, clusters: Any,
) -> dict[str, Any]:
    np = common.import_numpy()
    indices = np.flatnonzero(np.asarray(sample, dtype=bool))
    exposure = (np.asarray(data["latest_prior_arm"]) == 1).astype(np.float64)
    treated = int(np.count_nonzero(exposure[indices] == 1))
    control = int(np.count_nonzero(exposure[indices] == 0))
    cluster_count = int(np.unique(np.asarray(clusters)[indices]).size) if indices.size else 0
    support = {
        "model": model, "status": "ATTEMPT_PENDING", "rows_requested": int(indices.size),
        "benefactor_rows_requested": treated, "claimer_rows_requested": control,
        "clusters_requested": cluster_count, "high_dimensional_fixed_effect": high_dimensional_name,
        "epistemic_label": "X", "causal_claim": False,
    }
    if indices.size < 1_000 or treated < 1 or control < 1 or cluster_count < 100:
        return {**support, "status": "NOT_ESTIMABLE_RETAINED_LOW_SUPPORT"}
    try:
        fitted = modeling.fit_exact_oneway_cluster(
            outcome=data["kind"][indices],
            exposures={"benefactor_minus_claimer": exposure[indices]},
            numeric_controls=current_controls(data, indices, include_draw_payoff=True),
            categorical_controls={
                name: data[name][indices]
                for name in ("eval_bin", "speed_code", "month_code", "hour_of_week", "ply_band")
            },
            high_dimensional_effect=np.asarray(high_dimensional)[indices],
            high_dimensional_name=high_dimensional_name,
            clusters=np.asarray(clusters)[indices],
            row_ids=data["row_hash"][indices],
            specification={
                "model": model, "analysis_role": "post-gate exploratory C7R C7X closure",
                "epistemic_label": "X", "causal_claim": False,
            },
        )
        return finite({**support, **fitted, "status": "ESTIMATED"})
    except (RuntimeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        return {
            **support, "status": "ESTIMATION_FAILURE_RETAINED",
            "error_type": type(error).__name__, "error_message": str(error),
        }


def estimate_c7x_relationship_models(
    model_cache: Path, threads: int, *, enforce_certified_reproduction: bool = True
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    np = common.import_numpy()
    data = load_numpy(model_cache, C7X_MODEL_COLUMNS, threads)
    n = data["kind"].size
    all_rows = np.ones(n, dtype=bool)
    exposure = (np.asarray(data["latest_prior_arm"]) == 1).astype(np.float64)
    primary = attempt_hdfe(
        data=data, sample=all_rows, exposures={"benefactor_minus_claimer": exposure},
        model=C7X_RELATIONSHIP_MODEL_NAMES[0],
        fixed_effect_names=("chooser_id", "eval_bin", "speed_code", "month_code", "hour_of_week", "ply_band"),
        include_draw_payoff=True,
    )
    if primary.get("status") != "ESTIMATED":
        raise RuntimeError(f"C7R C7X primary replication failed: {primary}")
    primary_term = primary["results"][0]
    reproduction = {
        "expected_coefficient": EXPECTED_C7X_PRIMARY_COEFFICIENT,
        "observed_coefficient": primary_term["coefficient"],
        "absolute_coefficient_difference": abs(primary_term["coefficient"] - EXPECTED_C7X_PRIMARY_COEFFICIENT),
        "expected_standard_error": EXPECTED_C7X_PRIMARY_STANDARD_ERROR,
        "observed_standard_error": primary_term["standard_error"],
        "absolute_standard_error_difference": abs(primary_term["standard_error"] - EXPECTED_C7X_PRIMARY_STANDARD_ERROR),
        "tolerance": 1e-6,
    }
    reproduction["pass"] = (
        reproduction["absolute_coefficient_difference"] <= reproduction["tolerance"]
        and reproduction["absolute_standard_error_difference"] <= reproduction["tolerance"]
    )
    reproduction["gate_enforced"] = enforce_certified_reproduction
    if enforce_certified_reproduction and not reproduction["pass"]:
        raise RuntimeError(f"Certified C7X primary failed reproduction gate: {reproduction}")
    chooser_switcher_rows, chooser_switchers = modeling.switcher_mask(data["chooser_id"], exposure)
    directed = modeling.directed_pair_codes(data["chooser_id"], data["opponent_id"])
    directed_switcher_rows, directed_switchers = modeling.switcher_mask(directed, exposure)
    attempts: list[dict[str, Any]] = [primary]
    attempts.append(
        attempt_hdfe(
            data=data, sample=chooser_switcher_rows,
            exposures={"benefactor_minus_claimer": exposure},
            model=C7X_RELATIONSHIP_MODEL_NAMES[1],
            fixed_effect_names=("chooser_id", "eval_bin", "speed_code", "month_code", "hour_of_week", "ply_band"),
            include_draw_payoff=True,
        )
    )
    attempts.append(
        attempt_hdfe(
            data=data, sample=all_rows,
            exposures={"benefactor_minus_claimer": exposure},
            model=C7X_RELATIONSHIP_MODEL_NAMES[2],
            fixed_effect_names=("chooser_id", "opponent_id", "eval_bin", "speed_code", "month_code", "hour_of_week", "ply_band"),
            include_draw_payoff=True, maximum_iterations=10_000,
        )
    )
    attempts.append(
        attempt_exact_c7x(
            data=data, sample=all_rows, model=C7X_RELATIONSHIP_MODEL_NAMES[3],
            high_dimensional=directed, high_dimensional_name="directed_pair",
            clusters=data["chooser_id"],
        )
    )
    attempts.append(
        attempt_exact_c7x(
            data=data, sample=all_rows, model=C7X_RELATIONSHIP_MODEL_NAMES[4],
            high_dimensional=directed, high_dimensional_name="directed_pair",
            clusters=data["pair_hash"],
        )
    )
    attempts.append(
        attempt_exact_c7x(
            data=data, sample=np.asarray(data["ply_count"]) > 10,
            model=C7X_RELATIONSHIP_MODEL_NAMES[5], high_dimensional=directed,
            high_dimensional_name="directed_pair", clusters=data["chooser_id"],
        )
    )
    le7 = np.asarray(data["latest_gap_days"], dtype=np.float64) <= 7
    attempts.append(
        attempt_exact_c7x(
            data=data, sample=le7, model=C7X_RELATIONSHIP_MODEL_NAMES[6],
            high_dimensional=data["chooser_id"], high_dimensional_name="chooser",
            clusters=data["chooser_id"],
        )
    )
    attempts.append(
        attempt_exact_c7x(
            data=data, sample=le7, model=C7X_RELATIONSHIP_MODEL_NAMES[7],
            high_dimensional=directed, high_dimensional_name="directed_pair",
            clusters=data["chooser_id"],
        )
    )
    if tuple(row["model"] for row in attempts) != C7X_RELATIONSHIP_MODEL_NAMES:
        raise RuntimeError("C7R C7X relationship model inventory changed")
    support = {
        "chooser_switchers_recomputed": chooser_switchers,
        "rows_in_chooser_switchers_recomputed": int(np.count_nonzero(chooser_switcher_rows)),
        "directed_pair_switchers_recomputed": directed_switchers,
        "rows_in_directed_pair_switchers_recomputed": int(np.count_nonzero(directed_switcher_rows)),
    }
    return attempts, {"certified_primary_reproduction": reproduction, "recomputed_support": support}


def flatten_models(models: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in models:
        base = {
            key: model.get(key)
            for key in (
                "model", "status", "rows_requested", "rows", "clusters_requested",
                "clusters", "cluster", "high_dimensional_fixed_effect", "error_type",
                "error_message", "epistemic_label", "causal_claim",
            )
        }
        results = model.get("results")
        if isinstance(results, list) and results:
            for term in results:
                rows.append(
                    finite(
                        {
                            **base, **term,
                            "effect_percentage_points": 100.0 * term["coefficient"],
                            "standard_error_percentage_points": 100.0 * term["standard_error"],
                        }
                    )
                )
        else:
            rows.append(base)
    return rows


def write_report_hashes(public: Path) -> list[dict[str, Any]]:
    rows = [
        {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        }
        for path in sorted(public.iterdir())
        if path.is_file() and path.name not in {"report_file_hashes.tsv", "_SUCCESS.json"}
    ]
    text = "file\tbytes\tsha256\n" + "".join(
        f"{row['file']}\t{row['bytes']}\t{row['sha256']}\n" for row in rows
    )
    common.atomic_text(public / "report_file_hashes.tsv", text)
    return rows


def execute(args: argparse.Namespace) -> Path:
    started = time.time()
    root = package_root()
    project = args.project_root.resolve()
    state = (args.state_root or project / STATE_RELATIVE).resolve()
    output_root = (args.output_root or project / OUTPUT_RELATIVE).resolve()
    run_id = args.run_id or common.utc_run_id()
    final = output_root / run_id
    if final.exists():
        raise RuntimeError(f"C7R public run already exists: {final}")
    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    state.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(state).free < MINIMUM_FREE_BYTES:
        raise RuntimeError("Less than 25 GiB free at C7R private state root")
    package_auth = authenticate_package(root)
    config = config_payload(root)
    config_sha256 = common.sha256_json(config)
    stage_root = project / STAGE07_RELATIVE
    print("C7R_STAGE07_AUTHENTICATION_BEGIN", flush=True)
    stage_auth = common.authenticate_stage07(stage_root, EXPECTED_STAGE07_SUCCESS_SHA256)
    stage_paths = common.stage07_paths(stage_root)
    print("C7R_STAGE07_AUTHENTICATION_OK", flush=True)
    history_state = project / HISTORY_STATE_RELATIVE
    history_paths = pair_paths(history_state)
    event_paths = pair_event_paths(history_state)
    print("C7R_PAIR_HISTORY_AUTHENTICATION_BEGIN", flush=True)
    history_auth = authenticate_pair_history(
        history_state, history_paths, event_paths
    )
    print("C7R_PAIR_HISTORY_AUTHENTICATION_OK", flush=True)
    c7x_classification, c7x_auth = authenticate_c7x_classification(project, root)
    print("C7R_C7X_CLASSIFICATION_AUTHENTICATION_OK", flush=True)
    support_cache, support_receipt = build_pair_support_cache(
        stage_paths=stage_paths, history_paths=history_paths,
        event_paths=event_paths, state=state,
        threads=args.threads, memory_limit=args.memory_limit, config_sha256=config_sha256,
    )
    prevalence = freeze_pair_prevalence(
        support_cache=support_cache, state=state, config_sha256=config_sha256,
    )
    c7x_support = freeze_c7x_support(c7x_classification, state, config_sha256)
    # This line is the explicit outcome-access boundary.
    print("C7R_ALL_SUPPORT_FROZEN_NOW_JOINING_FOCAL_OUTCOMES", flush=True)
    pair_model_cache, pair_model_receipt = build_pair_model_cache(
        support_cache=support_cache, stage_paths=stage_paths, state=state,
        threads=args.threads, memory_limit=args.memory_limit, config_sha256=config_sha256,
    )
    c7x_model_cache, c7x_model_receipt = build_c7x_model_cache(
        classification=c7x_classification, stage_paths=stage_paths, state=state,
        threads=args.threads, memory_limit=args.memory_limit, config_sha256=config_sha256,
    )
    rates = pair_rates(pair_model_cache)
    first_models = estimate_first_meeting_models(pair_model_cache, args.threads)
    c7x_models, c7x_qa = estimate_c7x_relationship_models(c7x_model_cache, args.threads)
    common.atomic_json(staging / "input_authentication.json", {
        "status": "C7R_INPUTS_AUTHENTICATED_OK", "package": package_auth,
        "stage07": stage_auth, "pair_history": history_auth,
        "c7x_classification": c7x_auth, "config": config,
        "config_sha256": config_sha256,
    })
    common.atomic_json(staging / "repeat_pair_prevalence_before_outcome.json", prevalence)
    prevalence_csv = list(prevalence["contexts"]) + list(prevalence["fairness_bins"])
    common.write_csv(staging / "repeat_pair_prevalence.csv", prevalence_csv)
    common.write_csv(staging / "pair_sequence_bands.csv", prevalence["pair_sequence_bands"])
    common.write_csv(staging / "repeat_kindness_rates.csv", rates)
    common.atomic_json(staging / "first_meeting_models.json", first_models)
    common.write_csv(staging / "first_meeting_models.csv", flatten_models(first_models))
    common.atomic_json(staging / "c7x_relationship_support_before_outcome.json", c7x_support)
    common.atomic_json(staging / "c7x_relationship_models.json", {
        "models": c7x_models, "qa": c7x_qa,
    })
    common.write_csv(staging / "c7x_relationship_models.csv", flatten_models(c7x_models))
    private_auth = {
        "pair_support": support_receipt,
        "pair_model": pair_model_receipt,
        "c7x_model": c7x_model_receipt,
        "private_paths_are_provenance_only": True,
    }
    common.atomic_json(staging / "private_checkpoint_authentication.json", private_auth)
    results = {
        "status": "CAMPAIGN1_C7R_CLOSURE_ESTIMATION_COMPLETE",
        "script_version": SCRIPT_VERSION,
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "epistemic_label": "X",
        "causal_claim": False,
        "first_meeting_scope_limit": prevalence["scope_limit"],
        "repeat_prevalence": prevalence,
        "repeat_kindness_rates": rates,
        "first_meeting_models": first_models,
        "c7x_relationship_support": c7x_support,
        "c7x_relationship_models": c7x_models,
        "c7x_qa": c7x_qa,
        "models_attempted": len(first_models) + len(c7x_models),
        "expected_models": len(FIRST_MEETING_MODEL_NAMES) + len(C7X_RELATIONSHIP_MODEL_NAMES),
        "runtime_seconds": time.time() - started,
        "privacy": "aggregate-only public output; row-level Parquets remain private",
    }
    common.atomic_json(staging / "c7r_results.json", results)
    report_hashes = write_report_hashes(staging)
    success = {
        "status": "CAMPAIGN1_C7R_CLOSURE_OK",
        "created_utc": common.utc_now(),
        "script_version": SCRIPT_VERSION,
        "config_sha256": config_sha256,
        "public_run": str(final),
        "report_files_hashed": len(report_hashes),
        "report_manifest_sha256": common.sha256_file(staging / "report_file_hashes.tsv"),
        "models_attempted": results["models_attempted"],
        "expected_models": results["expected_models"],
        "certified_c7x_primary_reproduction_pass": c7x_qa["certified_primary_reproduction"]["pass"],
        "focal_outcome_joined_only_after_support_freeze": True,
        "privacy_scan_required": True,
        "final_ok": True,
        "runtime_seconds": time.time() - started,
    }
    common.atomic_json(staging / "_SUCCESS.json", success)
    output_root.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    if args.execution_pointer:
        common.atomic_json(args.execution_pointer, {
            "status": "C7R_EXECUTION_POINTER_OK", "public_run": str(final),
            "state_root": str(state), "package_root": str(root),
            "run_id": run_id, "success_sha256": common.sha256_file(final / "_SUCCESS.json"),
        })
    print(
        f"CAMPAIGN1_C7R_CLOSURE_PRODUCTION_OK public={final} "
        f"seconds={time.time()-started:.1f}", flush=True,
    )
    return final


def self_test() -> None:
    common.self_test()
    modeling.self_test()
    if len(FIRST_MEETING_MODEL_NAMES) != 11 or len(C7X_RELATIONSHIP_MODEL_NAMES) != 8:
        raise RuntimeError("Frozen C7R model count changed")
    if len(set(FIRST_MEETING_MODEL_NAMES + C7X_RELATIONSHIP_MODEL_NAMES)) != 19:
        raise RuntimeError("C7R model names are not unique")
    if pair_sequence_band_sql("x").count("WHEN") != 4:
        raise RuntimeError("Pair-sequence band SQL changed")
    if ply_band_sql("x").count("WHEN") != 7:
        raise RuntimeError("Ply-band SQL changed")
    synthetic_summary = {
        "status": EXPECTED_HISTORY_STATUS,
        "processed_pair_rows": 123_456,
        "pair_sample_denominator": PAIR_SAMPLE_DENOMINATOR,
        "identifier_buckets": PAIR_BUCKETS,
        "checkpoint_config_sha256": "synthetic_checkpoint_config",
        "hypothesis_effect_estimated": False,
        "patron_profile_input_read": False,
    }
    synthetic_public = {
        "status": EXPECTED_HISTORY_STATUS,
        "summary_sha256": "synthetic_summary_sha256",
        "checkpoint_config_sha256": "synthetic_checkpoint_config",
    }
    if validate_history_public_authority(
        synthetic_public, synthetic_summary, "synthetic_summary_sha256"
    ) != 123_456:
        raise RuntimeError("Processed pair-history authority was not preserved")
    incorrect = dict(synthetic_public)
    incorrect["status"] = "DYNAMIC_SECOND_WAVE_HISTORY_V101_OK"
    try:
        validate_history_public_authority(
            incorrect, synthetic_summary, "synthetic_summary_sha256"
        )
    except RuntimeError:
        pass
    else:
        raise RuntimeError("History v1.0.0 authority-label regression test failed")
    print("CAMPAIGN1_C7R_MAIN_SELF_TEST_OK")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if not args.execute:
        raise SystemExit("Use --self-test or --execute")
    if args.threads < 1 or args.threads > 8:
        raise SystemExit("--threads must be between 1 and 8")
    try:
        execute(args)
    except Exception as error:
        traceback.print_exc()
        print(f"CAMPAIGN1_C7R_CLOSURE_FAILED {type(error).__name__}: {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
