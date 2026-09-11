#!/usr/bin/env python3
"""Build the outcome-blind, private short-position commonness design."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

import equality_fen_common as common


DESIGN_FILE = "short_position_commonness_private.parquet"
DESIGN_RECEIPT = "position_design_receipt.json"
FORBIDDEN_OUTPUT_COLUMNS = {
    "kind_draw",
    "outcome_kind_draw",
    "chooser_username",
    "chooser_username_norm",
    "chooser_draw_payoff_v2",
    "chooser_win_premium_v2",
    "fen_after_last_move",
    "position_fen4",
    "board_fen1",
}
EXPECTED_OUTPUT_COLUMNS = [
    "game_id",
    "month",
    "archive_ordinal",
    "ply_count",
    "fen4_hash",
    "board_hash",
    "fen4_total_frequency",
    "board_total_frequency",
    "fen4_loo_frequency",
    "board_loo_frequency",
    "fen4_log1p_loo",
    "board_log1p_loo",
    "fen4_tier",
    "board_tier",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def tier_sql(column: str) -> str:
    return f"""
      CASE
        WHEN {column} = 1 THEN 'singleton'
        WHEN {column} BETWEEN 2 AND 9 THEN '2_9'
        WHEN {column} BETWEEN 10 AND 99 THEN '10_99'
        WHEN {column} BETWEEN 100 AND 999 THEN '100_999'
        ELSE '1000_plus'
      END
    """


def verify_existing(
    cache: Path,
    receipt_path: Path,
    expected_rows: int,
    authority_fingerprint: str,
    contract_sha256: str,
    package_manifest_sha256: str,
) -> dict[str, Any] | None:
    if not cache.is_file() or not receipt_path.is_file():
        return None
    receipt = common.load_json(receipt_path)
    if receipt.get("status") != common.DESIGN_STATUS:
        return None
    if int(receipt.get("rows", -1)) != int(expected_rows):
        return None
    if int(receipt.get("bytes", -1)) != int(cache.stat().st_size):
        return None
    if receipt.get("sha256") != common.sha256_file(cache):
        return None
    if list(receipt.get("columns", [])) != EXPECTED_OUTPUT_COLUMNS:
        return None
    if receipt.get("authority_fingerprint") != authority_fingerprint:
        return None
    if receipt.get("contract_sha256") != contract_sha256:
        return None
    if receipt.get("package_manifest_sha256") != package_manifest_sha256:
        return None
    return receipt


def self_test() -> None:
    forbidden_query_probe = {
        "game_id",
        "month",
        "archive_ordinal",
        "ply_count",
        "fen_after_last_move",
    }
    if "kind_draw" in forbidden_query_probe:
        raise RuntimeError("Outcome-blind design field test failed")
    if set(EXPECTED_OUTPUT_COLUMNS) & FORBIDDEN_OUTPUT_COLUMNS:
        raise RuntimeError("Private position design schema contains forbidden source columns")
    if tier_sql("frequency").count("WHEN") != 4:
        raise RuntimeError("Commonness tier SQL changed")
    print("KINDNESS_EQUALITY_FEN_POSITION_DESIGN_SELFTEST_OK")


def build_design(args: argparse.Namespace) -> dict[str, Any]:
    package_root = args.package_root.resolve()
    project = args.project_root.resolve()
    private_root = args.private_root.resolve()
    public_root = args.public_root.resolve()
    private_root.mkdir(parents=True, exist_ok=True)
    (public_root / "receipts").mkdir(parents=True, exist_ok=True)

    contract = common.load_contract(package_root)
    if not args.synthetic:
        common.verify_environment(contract)
        common.verify_package_manifest(package_root)
        repository = common.authenticate_repository(project, contract)
    else:
        repository = {"status": "SYNTHETIC_REPOSITORY_BYPASS"}

    authority = common.authenticate_authorities(
        project,
        package_root,
        contract,
        full_stage07_hash=not args.synthetic,
        synthetic=args.synthetic,
    )
    paths = authority["stage07_paths"]
    expected_rows = int(authority["stage07_short_rows"])
    contract_sha256 = common.sha256_file(package_root / common.CONTRACT_RELATIVE)
    package_manifest_sha256 = common.sha256_file(package_root / "PACKAGE_MANIFEST.sha256")
    authority_fingerprint = (
        common.sha256_file(project / "_SUCCESS.json")
        if args.synthetic
        else str(contract["stage07"]["sample_fingerprint"])
    )
    input_paths = [
        *paths,
        package_root / common.CONTRACT_RELATIVE,
        package_root / "PACKAGE_MANIFEST.sha256",
    ]
    before = common.path_snapshot(input_paths)

    cache = private_root / DESIGN_FILE
    private_receipt = private_root / DESIGN_RECEIPT
    existing = verify_existing(
        cache,
        private_receipt,
        expected_rows,
        authority_fingerprint,
        contract_sha256,
        package_manifest_sha256,
    )
    if existing is not None:
        common.progress("authenticated outcome-blind position design already exists; reusing")
        public_receipt = dict(existing)
        public_receipt.pop("private_cache_name", None)
        public_receipt["resumed"] = True
        common.atomic_write_json(public_root / "receipts" / DESIGN_RECEIPT, public_receipt)
        public_repository = {
            key: value for key, value in repository.items() if key != "repository"
        }
        common.atomic_write_json(
            public_root / "receipts" / "input_authorities.json",
            {
                "created_at_utc": common.utc_now(),
                "repository": public_repository,
                "stage07": {
                    "status": (
                        contract["stage07"]["status"]
                        if not args.synthetic
                        else "SYNTHETIC_STAGE07_OK"
                    ),
                    "success_sha256": (
                        contract["stage07"]["success_sha256"]
                        if not args.synthetic
                        else None
                    ),
                    "producer_sha256": (
                        contract["stage07"]["producer_sha256"]
                        if not args.synthetic
                        else None
                    ),
                    "rows": authority["stage07_rows"],
                    "kind_draws": authority["stage07_kind_draws"],
                    "short_rows": authority["stage07_short_rows"],
                    "monthly_files_authenticated": authority["authenticated_files"],
                    "full_monthly_sha256_recomputed": not args.synthetic,
                },
                "upstream": authority["input_authorities"],
                "input_snapshot_unchanged_after_design": True,
                "design_cache_resumed": True,
            },
        )
        return {
            "cache": cache,
            "receipt": existing,
            "authority": authority,
            "repository": repository,
            "input_snapshot": before,
        }

    spill = private_root / "duckdb_spill"
    spill.mkdir(parents=True, exist_ok=True)
    database = common.open_database(
        ":memory:",
        threads=int(contract["analysis"]["threads"]),
        memory_limit=str(contract["analysis"]["memory_limit"]),
    )
    database.execute(f"PRAGMA temp_directory='{str(spill).replace(chr(39), chr(39) * 2)}'")
    common.register_panel_view(database, paths)

    selected_columns = {
        "game_id",
        "month",
        "archive_ordinal",
        "ply_count",
        "fen_after_last_move",
    }
    if "kind_draw" in selected_columns or "outcome_kind_draw" in selected_columns:
        raise RuntimeError("Outcome field entered the design-stage selection")
    short_max = (
        int(contract["analysis"]["short_ply_max"])
        if not args.synthetic
        else int(common.load_json(project / "_SUCCESS.json")["short_ply_max"])
    )
    common.progress("building outcome-blind short-position source")
    database.execute(
        f"""
        CREATE OR REPLACE TABLE short_position_source AS
        WITH cleaned AS (
          SELECT
            CAST(game_id AS VARCHAR) AS game_id,
            CAST(month AS VARCHAR) AS month,
            CAST(archive_ordinal AS BIGINT) AS archive_ordinal,
            CAST(ply_count AS INTEGER) AS ply_count,
            regexp_replace(trim(CAST(fen_after_last_move AS VARCHAR)), '\\s+', ' ', 'g') AS fen_clean
          FROM panel
          WHERE CAST(ply_count AS INTEGER) <= {short_max}
        )
        SELECT
          game_id,
          month,
          archive_ordinal,
          ply_count,
          split_part(fen_clean, ' ', 1) AS board_fen1,
          concat_ws(
            ' ',
            split_part(fen_clean, ' ', 1),
            split_part(fen_clean, ' ', 2),
            split_part(fen_clean, ' ', 3),
            split_part(fen_clean, ' ', 4)
          ) AS position_fen4
        FROM cleaned
        """
    )
    qa = database.execute(
        """
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT game_id)::BIGINT AS distinct_games,
          SUM(CASE WHEN game_id IS NULL OR trim(game_id)='' THEN 1 ELSE 0 END)::BIGINT AS missing_game,
          SUM(CASE WHEN board_fen1 IS NULL OR trim(board_fen1)='' THEN 1 ELSE 0 END)::BIGINT AS missing_board,
          SUM(CASE WHEN position_fen4 IS NULL OR
                        array_length(string_split(position_fen4, ' ')) <> 4
                   THEN 1 ELSE 0 END)::BIGINT AS malformed_fen4,
          MIN(ply_count)::INTEGER AS minimum_ply,
          MAX(ply_count)::INTEGER AS maximum_ply
        FROM short_position_source
        """
    ).fetchdf().iloc[0].to_dict()
    if int(qa["rows"]) != expected_rows or int(qa["distinct_games"]) != expected_rows:
        raise RuntimeError(
            f"Short-position design row identity failed: expected={expected_rows}; qa={qa}"
        )
    for field in ("missing_game", "missing_board", "malformed_fen4"):
        if int(qa[field]) != 0:
            raise RuntimeError(f"Short-position design FEN QA failed: {field}={qa[field]}")
    if int(qa["maximum_ply"]) > short_max:
        raise RuntimeError("Short-position design exceeds the frozen ply threshold")

    common.progress("counting exact FEN4 and board-position frequencies")
    database.execute(
        """
        CREATE OR REPLACE TABLE fen4_frequency AS
        SELECT position_fen4, COUNT(*)::BIGINT AS frequency
        FROM short_position_source
        GROUP BY position_fen4
        """
    )
    database.execute(
        """
        CREATE OR REPLACE TABLE board_frequency AS
        SELECT board_fen1, COUNT(*)::BIGINT AS frequency
        FROM short_position_source
        GROUP BY board_fen1
        """
    )

    temporary = private_root / f".{DESIGN_FILE}.tmp"
    if temporary.exists():
        temporary.unlink()
    fen_tier = tier_sql("f.frequency")
    board_tier = tier_sql("b.frequency")
    escaped_temporary = str(temporary).replace("'", "''")
    common.progress("writing private hash-and-frequency design cache")
    database.execute(
        f"""
        COPY (
          SELECT
            s.game_id,
            s.month,
            s.archive_ordinal,
            s.ply_count,
            sha256(s.position_fen4) AS fen4_hash,
            sha256(s.board_fen1) AS board_hash,
            f.frequency AS fen4_total_frequency,
            b.frequency AS board_total_frequency,
            f.frequency - 1 AS fen4_loo_frequency,
            b.frequency - 1 AS board_loo_frequency,
            ln(1.0 + CAST(f.frequency - 1 AS DOUBLE)) AS fen4_log1p_loo,
            ln(1.0 + CAST(b.frequency - 1 AS DOUBLE)) AS board_log1p_loo,
            {fen_tier} AS fen4_tier,
            {board_tier} AS board_tier
          FROM short_position_source s
          JOIN fen4_frequency f USING (position_fen4)
          JOIN board_frequency b USING (board_fen1)
          ORDER BY s.month, s.archive_ordinal, s.game_id
        ) TO '{escaped_temporary}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    database.close()
    retained_spill_files = [path for path in spill.rglob("*") if path.is_file()]
    if retained_spill_files:
        raise RuntimeError(
            "Outcome-blind design left DuckDB spill files after close; "
            "raw position work state is not certified for retention"
        )

    footer = common.pq.ParquetFile(temporary)
    columns = list(footer.schema_arrow.names)
    rows = int(footer.metadata.num_rows)
    if rows != expected_rows:
        raise RuntimeError(f"Private design cache rows changed: {rows} != {expected_rows}")
    if columns != EXPECTED_OUTPUT_COLUMNS:
        raise RuntimeError(f"Private design cache schema changed: {columns}")
    overlap = set(columns) & FORBIDDEN_OUTPUT_COLUMNS
    if overlap:
        raise RuntimeError(f"Private design cache contains forbidden columns: {sorted(overlap)}")
    os.replace(temporary, cache)
    cache_sha = common.sha256_file(cache)

    summary_db = common.open_database(
        ":memory:",
        threads=int(contract["analysis"]["threads"]),
        memory_limit=str(contract["analysis"]["memory_limit"]),
    )
    escaped_cache = str(cache).replace("'", "''")
    summary = summary_db.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT game_id)::BIGINT AS distinct_games,
          MIN(fen4_total_frequency)::BIGINT AS minimum_fen4_frequency,
          MAX(fen4_total_frequency)::BIGINT AS maximum_fen4_frequency,
          MIN(board_total_frequency)::BIGINT AS minimum_board_frequency,
          MAX(board_total_frequency)::BIGINT AS maximum_board_frequency,
          SUM(CASE WHEN fen4_loo_frequency <> fen4_total_frequency - 1 THEN 1 ELSE 0 END)::BIGINT AS fen4_loo_failures,
          SUM(CASE WHEN board_loo_frequency <> board_total_frequency - 1 THEN 1 ELSE 0 END)::BIGINT AS board_loo_failures
        FROM read_parquet('{escaped_cache}')
        """
    ).fetchdf().iloc[0].to_dict()
    summary_db.close()
    if int(summary["distinct_games"]) != expected_rows:
        raise RuntimeError("Private design cache game identity changed")
    if int(summary["fen4_loo_failures"]) or int(summary["board_loo_failures"]):
        raise RuntimeError("Leave-one-out position frequency identity failed")

    receipt = {
        "status": common.DESIGN_STATUS,
        "created_at_utc": common.utc_now(),
        "rows": expected_rows,
        "short_ply_max": short_max,
        "bytes": int(cache.stat().st_size),
        "sha256": cache_sha,
        "columns": columns,
        "authority_fingerprint": authority_fingerprint,
        "sample_fingerprint": (
            None if args.synthetic else contract["stage07"]["sample_fingerprint"]
        ),
        "contract_sha256": contract_sha256,
        "package_manifest_sha256": package_manifest_sha256,
        "private_cache_name": DESIGN_FILE,
        "outcome_blind_source_columns": sorted(selected_columns),
        "outcome_columns_read": [],
        "fen_strings_retained_in_cache": False,
        "hashed_position_signatures_retained_private": True,
        "qa": common.json_ready({**qa, **summary}),
    }
    common.atomic_write_json(private_receipt, receipt)
    public_receipt = dict(receipt)
    public_receipt.pop("private_cache_name", None)
    public_receipt["resumed"] = False
    common.atomic_write_json(public_root / "receipts" / DESIGN_RECEIPT, public_receipt)
    after = common.path_snapshot(input_paths)
    common.assert_snapshot_unchanged(before, after)

    public_repository = {
        key: value for key, value in repository.items() if key != "repository"
    }
    public_authorities = {
        "created_at_utc": common.utc_now(),
        "repository": public_repository,
        "stage07": {
            "status": contract["stage07"]["status"] if not args.synthetic else "SYNTHETIC_STAGE07_OK",
            "success_sha256": (
                contract["stage07"]["success_sha256"] if not args.synthetic else None
            ),
            "producer_sha256": (
                contract["stage07"]["producer_sha256"] if not args.synthetic else None
            ),
            "rows": authority["stage07_rows"],
            "kind_draws": authority["stage07_kind_draws"],
            "short_rows": authority["stage07_short_rows"],
            "monthly_files_authenticated": authority["authenticated_files"],
            "full_monthly_sha256_recomputed": not args.synthetic,
        },
        "upstream": authority["input_authorities"],
        "input_snapshot_unchanged_after_design": True,
    }
    common.atomic_write_json(public_root / "receipts" / "input_authorities.json", public_authorities)
    return {
        "cache": cache,
        "receipt": receipt,
        "authority": authority,
        "repository": repository,
        "input_snapshot": before,
    }


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    result = build_design(args)
    print(common.DESIGN_STATUS)
    print(f"Rows: {result['receipt']['rows']:,}")
    print(f"Cache SHA-256: {result['receipt']['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
