#!/usr/bin/env python3
"""
Campaign 1 C9 — ignition-transfer serialization recovery v1.0.1.

The original v1.0.0 r1 producer completed all 4,999 conditional randomizations and
passed exact B2 reproduction, then failed while writing a CSV whose primary row had
three fields absent from the first row. This recovery:

  * authenticates every existing checkpoint and requires zero missing batches;
  * draws no new randomizations;
  * re-runs exact B2 reproduction;
  * gives every component row one explicit uniform schema; and
  * publishes aggregate outputs under a new public root.

Scientific contract
-------------------
C9 inherits the certified B2 repeat-granter conditional-randomization machinery:
  * 64,331 repeat granters
  * 1,017,944 B1 fair opportunities
  * 273,483 kind draws
  * chooser kind-draw totals fixed in every conditional draw
  * cross-fitted static propensities fixed
  * 4,999 randomizations
  * sequence-specific pseudo-first grant in EVERY randomization

Every draw recomputes all C9 partitions relative to that draw's pseudo-first grant.

Primary [C]:
  Later-session kindness excess within 7 days of pseudo-first grant
  = observed later-session rate - conditional-randomization null mean rate.
  Two-sided randomization p-value.

Secondary [S]:
  1. same-session excess minus later-session excess within 7 days;
  2. same-pool excess minus cross-pool excess within 24 hours.

Session authority
-----------------
Campaign 1 v1.0.3 applies. The certified chronology has game-start timestamps but no
universal game-end timestamp, so sessions use consecutive game-start gaps < 30 minutes.
Crucially, sessions are derived from ALL rated-game chronology, never from timeout-only
opportunities.

Implementation strategy
-----------------------
1. Authenticate all frozen authorities before estimation.
2. Recover the B1 chooser_index -> actual chooser_user_id/game_id bridge using Stage07
   NON-OUTCOME fields only; canonical speed is then taken from Stage07 `api_speed`
   rather than interpreting B1 `current_speed_code` as a literal label.
3. Authenticate the already-built private B1-row -> session-id cache and its receipt;
   missing or mismatched cache inputs are a hard stop and are never rebuilt here.
4. Recompute and publish the outcome-blind C9 support audit from authenticated inputs.
5. Authenticate and combine all 20 already-completed conditional-randomization
   checkpoints. This runner contains no missing-batch recomputation branch.
6. Reproduce the already-certified B2 randomization summary exactly as a hard
   implementation check before publishing C9.
7. Publish aggregate-only C9 results using a uniform component-row schema.

No Lichess API request. No profile/Patron read. No chronology rebuild. No mutation of
any frozen result directory. The existing v1.0.0 private checkpoints are read-only
inputs to this serialization-only recovery; missing checkpoints are a hard stop.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
PAYLOAD_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_GIT = "46abb7409621e98c74dc8aa3eb3b3885a644080d"
EXPECTED_BASE_SHA = "ded9965994b6c00ed613adc90eaff3f976b257e9eb6dafdda61819916dde49fe"
EXPECTED_AMD101_SHA = "01c0ed96bfca62b1659a98d978bedaaf9a4540fcdc5a30a075e2f032e35e05ee"
EXPECTED_AMD102_SHA = "7eeca3ab8591620a196badbd1b9d3184236d67a031cf9eff06b76584995c0049"
EXPECTED_AMD103_SHA = "96530f7ffd43b7d68ff84c794200f7db98b2b455ea2994efb5b73ce5cb370a07"
EXPECTED_AMD105_SHA = "14cb718408788ea15f94d555eaabc84c27f2dc42b1ca85c03b46daf43e366787"
EXPECTED_ORIGINAL_C9_RUNNER_SHA = "e553af77d16cf944a956b4ae266c3468806e08257a4aa1bff6fb953c619d8830"

EXPECTED_RECOVERY_EVIDENCE = {
    "prior_evidence/c9_v100_failed/FAILURE_DIAGNOSTIC.json":
        "c1bccdb1347d2e2d2edc4c65499af2f03107ad65a4c78681193153e04ad845f8",
    "prior_evidence/c9_v100_failed/c9_exact_b2_reproduction.json":
        "d7e9661aa55aba7eabc151099401afa37a6641994f421c44f75319701cc49074",
    "prior_evidence/c9_v100_failed/c9_partition_components.csv":
        "f0c8c6871f92cb7082865a1e0b3fe0257a18a5cc75c4e0d1aa9339a52caed9bf",
    "prior_evidence/c9_v100_failed/c9_support_frozen.json":
        "ada56d140a6e6232fc9339a7da6b607218e54c944005489ad00980a2170b4e0e",
}

B2_PRODUCER_COMMIT = "1418976974e1b7857407f1b2a717a5c11f9c88a1"
B2_PRODUCER_REL = "code/10f_estimate_b2_first_grant_dynamics.py"
B2_PRODUCER_BLOB = "58000cfb8b1581947d803e73300407037726539b"
B2_ANCHOR_MANIFEST_SHA = "19a89d0ce9161887a3b4f1807535c5ed685c1c14b56bcf5e123f350aa7e02331"

EXPECTED_B1_SHA = "08429d99aa839c0fc087e3d4d4de270c322086287c3814886f2bcd3bf32e7d56"
EXPECTED_PROP_SHA = "0aebdbb279c52308140a819c940655e4341524b3160bcc385cfa8a92030b02df"
EXPECTED_B2_SUCCESS_SHA = "0e4a58c848bb18a2d7d5fcb2a13b4176679c59e60c86aca2161870e0751ba558"
EXPECTED_B2_SUMMARY_SHA = "3e39fb453094c644201870191b42fe0dc9315a3ce209cd00bd600ef395d7045d"

EXPECTED_B1_ROWS = 1_017_944
EXPECTED_B1_CHOOSERS = 64_331
EXPECTED_B1_KIND = 273_483
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_CHRON_ROWS = 7_763_847_245
EXPECTED_CHRON_FILES = 852

RANDOMIZATIONS = 4_999
BATCH = 250
B2_SEED = 2026082201
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
C9_7D_MS = 7 * DAY_MS
C9_24H_MS = DAY_MS
SESSION_GAP_MS = 30 * 60 * 1000

PANEL_START_MS = int(dt.datetime(2023, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
PANEL_END_MS = int(dt.datetime(2025, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
SESSION_LEFT_MS = PANEL_START_MS - 2 * HOUR_MS

_WORKER_DATA: dict[str, Any] | None = None
_WORKER_PROB: Any | None = None
_WORKER_SLICES: list[tuple[int, int]] | None = None
_WORKER_SELECTIONS: list[Any] | None = None
_WORKER_SESSION: Any | None = None
_WORKER_SPEED: Any | None = None
_WORKER_B2: Any | None = None


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def run(cmd: list[str], cwd: Path | None = None) -> str:
    x = subprocess.run(
        cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
    )
    return x.stdout.strip()


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sqls(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    # Deterministic union of keys prevents late-row fields from being silently dropped
    # or raising after a partial file has already been written. Scientific component
    # rows are additionally required to have a uniform explicit schema below.
    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)


def authenticate_packaged_recovery_evidence() -> dict[str, Any]:
    expected=dict(EXPECTED_RECOVERY_EVIDENCE)
    expected["docs/dynamics_paper2_campaign1_v1_0_5_postoutcome_correction.md"] = (
        EXPECTED_AMD105_SHA
    )
    report={}
    for rel,want in expected.items():
        path=PAYLOAD_ROOT/rel
        if not path.is_file():
            raise RuntimeError(f"Packaged C9 recovery evidence missing: {path}")
        got=sha256_file(path)
        if got!=want:
            raise RuntimeError(
                f"Packaged C9 recovery evidence SHA mismatch {rel}: "
                f"expected={want} actual={got}"
            )
        report[rel]={"path":str(path),"sha256":got}

    failure=json.loads(
        (PAYLOAD_ROOT/"prior_evidence/c9_v100_failed/FAILURE_DIAGNOSTIC.json").read_text()
    )
    if failure.get("status")!="DYNAMICS_CAMPAIGN1_C9_V100_FAIL_CLOSED":
        raise RuntimeError("Packaged C9 failure status changed")
    # Python's set rendering can vary field order, so match the stable semantic pieces.
    error=str(failure.get("error",""))
    if "dict contains fields not in fieldnames" not in error:
        raise RuntimeError(f"Packaged C9 failure is not the serialization bug: {error}")
    for field in ("epistemic_label","interpretation","holm_adjusted_p_value"):
        if field not in error:
            raise RuntimeError(f"Packaged C9 failure omits expected field: {field}")

    exact=json.loads(
        (PAYLOAD_ROOT/"prior_evidence/c9_v100_failed/c9_exact_b2_reproduction.json").read_text()
    )
    if exact.get("status")!="C9_EXACT_B2_RANDOMIZATION_REPRODUCTION_OK":
        raise RuntimeError("Packaged failed run did not pass exact B2 reproduction")
    report["classification"]={
        "failure_type":"CSV_SERIALIZATION_ONLY",
        "scientific_randomization_complete":True,
        "exact_b2_reproduction_passed":True,
        "new_randomizations_authorized":False,
        "original_runner_sha256":EXPECTED_ORIGINAL_C9_RUNNER_SHA,
    }
    return report


def write_execution_pointer(path: Path | None, obj: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, obj)


def import_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import historical source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parquet_rows(path: Path) -> int:
    import pyarrow.parquet as pq
    return int(pq.ParquetFile(path).metadata.num_rows)


def total_rows(paths: list[Path]) -> int:
    import pyarrow.parquet as pq
    return sum(int(pq.ParquetFile(p).metadata.num_rows) for p in paths)


def setup_duckdb(tempdir: Path, threads: int, memory: str):
    import duckdb
    con = duckdb.connect()
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET memory_limit={sqls(memory)}")
    tempdir.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory={sqls(str(tempdir))}")
    con.execute("SET preserve_insertion_order=false")
    try:
        con.execute("PRAGMA enable_progress_bar")
    except Exception:
        pass
    return con


def stage07_paths(root: Path) -> list[Path]:
    paths = sorted(
        p for p in root.rglob("*.parquet")
        if "_manifests" not in p.parts
        and not any(part.startswith(".") for part in p.parts)
    )
    month_paths = [p for p in paths if any(part.startswith("month=") for part in p.parts)]
    return month_paths or paths


def chronology_manifest_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            p = Path(row["path"])
            rows.append({
                "file_index": int(row["file_index"]),
                "path": p,
                "bytes": int(row["bytes"]),
                "rows": int(row["rows"]),
                "utc_ms_min": int(row["utc_ms_min"]) if row["utc_ms_min"] else None,
                "utc_ms_max": int(row["utc_ms_max"]) if row["utc_ms_max"] else None,
                "footer_signature_sha256": row["footer_signature_sha256"],
            })
    return rows


def campaign_chron_paths(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Use metadata UTC coverage, not path naming, and include two-hour left boundary.
    chosen = []
    for row in rows:
        lo = row["utc_ms_min"]
        hi = row["utc_ms_max"]
        if lo is None or hi is None:
            continue
        if hi >= SESSION_LEFT_MS and lo < PANEL_END_MS:
            chosen.append(row)
    return chosen


def historical_b2_source(repo: Path, state: Path) -> Path:
    blob = run(
        ["git", "rev-parse", f"{B2_PRODUCER_COMMIT}:{B2_PRODUCER_REL}"], cwd=repo
    )
    if blob != B2_PRODUCER_BLOB:
        raise RuntimeError(f"Historical B2 blob mismatch: {blob}")
    source = run(
        ["git", "show", f"{B2_PRODUCER_COMMIT}:{B2_PRODUCER_REL}"], cwd=repo
    )
    path = state / "historical_b2_producer.py"
    path.write_text(source + ("" if source.endswith("\n") else "\n"))
    return path


def b1_stage07_mapping(con, b1: Path, s7_paths: list[Path], staging: Path) -> dict[str, Any]:
    """
    Resolve dense B1 chooser_index to real chooser_user_id and every B1 row to Stage07 game_id
    using only NON-OUTCOME fields. Try both plausible B1 time authorities.
    """
    s7_sql = "[" + ",".join(sqls(str(p)) for p in s7_paths) + "]"
    con.execute(f"""
    CREATE TEMP VIEW b1_nonoutcome AS
    SELECT
      CAST(b1_row_id AS BIGINT) AS b1_row_id,
      CAST(chooser_index AS BIGINT) AS chooser_index,
      CAST(sequence_index AS BIGINT) AS sequence_index,
      CAST(utc_ms AS BIGINT) AS b_utc_ms,
      CAST(current_eval_cp AS DOUBLE) AS eval_cp,
      CAST(current_chooser_elo AS DOUBLE) AS chooser_elo,
      CAST(current_opponent_elo AS DOUBLE) AS opponent_elo,
      CAST(current_ply_count AS DOUBLE) AS ply_count,
      CAST(current_speed_code AS VARCHAR) AS speed
    FROM read_parquet({sqls(str(b1))})
    """)

    attempts = []
    for time_field in ("api_last_move_at_ms", "utc_ms"):
        table = f"mapcand_{time_field}"
        con.execute(f"""
        CREATE TEMP TABLE {table} AS
        SELECT DISTINCT
          b.b1_row_id,
          b.chooser_index,
          CAST(s.game_id AS VARCHAR) AS game_id,
          CAST(s.chooser_user_id AS BIGINT) AS chooser_user_id,
          CAST(s.api_speed AS VARCHAR) AS canonical_speed
        FROM b1_nonoutcome b
        INNER JOIN read_parquet({s7_sql}, union_by_name=true) s
          ON b.b_utc_ms = CAST(s.{q(time_field)} AS BIGINT)
         AND b.eval_cp = CAST(s.engine_eval_cp_disconnected AS DOUBLE)
         AND b.chooser_elo = CAST(s.chooser_elo AS DOUBLE)
         AND b.opponent_elo = CAST(s.disconnected_elo AS DOUBLE)
         AND b.ply_count = CAST(s.ply_count AS DOUBLE)
        """)

        stats = con.execute(f"""
        WITH perrow AS (
          SELECT b1_row_id,
                 count(*) n,
                 count(DISTINCT chooser_user_id) nu,
                 count(DISTINCT game_id) ng
          FROM {table}
          GROUP BY 1
        ),
        perchooser AS (
          SELECT chooser_index,
                 count(DISTINCT chooser_user_id) nu,
                 count(*) candidate_rows
          FROM {table}
          GROUP BY 1
        )
        SELECT
          (SELECT count(*) FROM {table}),
          (SELECT count(*) FROM perrow),
          (SELECT count(*) FROM perrow WHERE n=1),
          (SELECT count(*) FROM perchooser),
          (SELECT count(*) FROM perchooser WHERE nu=1)
        """).fetchone()
        attempt = {
            "time_field": time_field,
            "candidate_rows": int(stats[0]),
            "b1_rows_with_candidate": int(stats[1]),
            "b1_rows_exactly_one_candidate": int(stats[2]),
            "chooser_indices_with_candidate": int(stats[3]),
            "chooser_indices_with_unique_user": int(stats[4]),
        }
        attempts.append(attempt)

    write_json(
        staging / "c9_b1_stage07_mapping_attempts.json",
        {
            "status": "C9_B1_STAGE07_MAPPING_ATTEMPTS_COMPLETE",
            "mapping_uses_kind_draw": False,
            "current_speed_code_used_as_literal_speed": False,
            "attempts": attempts,
        },
    )

    # Pick the attempt with most chooser indices uniquely mapped, then row coverage.
    attempts.sort(
        key=lambda x: (
            x["chooser_indices_with_unique_user"],
            x["b1_rows_exactly_one_candidate"],
            x["b1_rows_with_candidate"],
        ),
        reverse=True,
    )
    best = attempts[0]
    table = f"mapcand_{best['time_field']}"

    # Unique chooser map. Every repeat granter must map to one and only one actual user.
    con.execute(f"""
    CREATE TEMP TABLE chooser_map AS
    SELECT chooser_index, min(chooser_user_id) AS chooser_user_id
    FROM {table}
    GROUP BY chooser_index
    HAVING count(DISTINCT chooser_user_id)=1
    """)
    mapped_choosers = int(con.execute("SELECT count(*) FROM chooser_map").fetchone()[0])
    if mapped_choosers != EXPECTED_B1_CHOOSERS:
        raise RuntimeError(
            f"B1 chooser-index bridge incomplete: {mapped_choosers}/{EXPECTED_B1_CHOOSERS}; "
            f"attempts={attempts}"
        )

    # Now use the resolved actual user ID to force a unique game mapping for every B1 row.
    tf = best["time_field"]
    con.execute(f"""
    CREATE TEMP TABLE b1_game_candidates AS
    SELECT DISTINCT
      b.b1_row_id,
      b.chooser_index,
      b.sequence_index,
      cm.chooser_user_id,
      CAST(s.game_id AS VARCHAR) AS game_id,
      CAST(s.api_speed AS VARCHAR) AS canonical_speed
    FROM b1_nonoutcome b
    INNER JOIN chooser_map cm USING(chooser_index)
    INNER JOIN read_parquet({s7_sql}, union_by_name=true) s
      ON CAST(s.chooser_user_id AS BIGINT)=cm.chooser_user_id
     AND b.b_utc_ms = CAST(s.{q(tf)} AS BIGINT)
     AND b.eval_cp = CAST(s.engine_eval_cp_disconnected AS DOUBLE)
     AND b.chooser_elo = CAST(s.chooser_elo AS DOUBLE)
     AND b.opponent_elo = CAST(s.disconnected_elo AS DOUBLE)
     AND b.ply_count = CAST(s.ply_count AS DOUBLE)
    """)

    row_stats = con.execute("""
    WITH z AS (
      SELECT b1_row_id,count(*) n
      FROM b1_game_candidates GROUP BY 1
    )
    SELECT
      count(*) FILTER (WHERE n=1),
      count(*) FILTER (WHERE n>1),
      count(*)
    FROM z
    """).fetchone()
    unique_rows, ambiguous_rows, any_rows = map(int, row_stats)
    if unique_rows != EXPECTED_B1_ROWS or ambiguous_rows != 0:
        raise RuntimeError(
            f"B1->Stage07 game bridge not complete/unique: unique={unique_rows}, "
            f"ambiguous={ambiguous_rows}, any={any_rows}, expected={EXPECTED_B1_ROWS}; "
            f"attempts={attempts}"
        )

    bad_speed = int(con.execute("""
    SELECT count(*)
    FROM b1_game_candidates
    WHERE canonical_speed IS NULL OR trim(canonical_speed)=''
    """).fetchone()[0])
    if bad_speed != 0:
        raise RuntimeError(
            f"B1->Stage07 canonical speed unresolved on {bad_speed} B1 rows"
        )

    con.execute("""
    CREATE TEMP TABLE b1_game_map AS
    SELECT * FROM b1_game_candidates
    """)

    report = {
        "status": "C9_B1_STAGE07_NONOUTCOME_BRIDGE_OK",
        "mapping_uses_kind_draw": False,
        "attempts": attempts,
        "selected_time_field": tf,
        "mapped_chooser_indices": mapped_choosers,
        "mapped_b1_rows": unique_rows,
        "ambiguous_b1_rows": ambiguous_rows,
        "canonical_stage07_speed_rows_missing": bad_speed,
        "current_speed_code_used_as_literal_speed": False,
    }
    write_json(staging / "c9_b1_stage07_mapping.json", report)
    return report


def build_session_cache(
    con,
    b1: Path,
    prop: Path,
    chron_rows: list[dict[str, Any]],
    private_root: Path,
    staging: Path,
) -> tuple[Path, dict[str, Any]]:
    """
    Build all-game 30m start-to-start sessions for repeat-granter users, then attach only
    session ID to B1 rows. User IDs/game IDs never appear in the persisted C9 enriched cache.
    """
    chosen = campaign_chron_paths(chron_rows)
    if not chosen:
        raise RuntimeError("No chronology files selected for Campaign 1 window")
    for row in chosen:
        p = row["path"]
        if not p.is_file():
            raise RuntimeError(f"Chronology file missing: {p}")
        st = p.stat()
        if st.st_size != row["bytes"]:
            raise RuntimeError(f"Chronology source byte-size mismatch: {p}")
        if parquet_rows(p) != row["rows"]:
            raise RuntimeError(f"Chronology source row-count mismatch: {p}")

    chron_sql = "[" + ",".join(sqls(str(x["path"])) for x in chosen) + "]"

    print(
        f"C9_ALL_GAME_SESSION_BUILD_BEGIN files={len(chosen)} "
        f"metadata_rows={sum(x['rows'] for x in chosen):,}",
        flush=True,
    )

    con.execute("""
    CREATE TEMP TABLE repeat_users AS
    SELECT DISTINCT chooser_user_id AS user_id FROM chooser_map
    """)

    # Filter the 24m all-game chronology to the 64,331 B1 repeat granters.
    con.execute(f"""
    CREATE TEMP TABLE repeat_history AS
    SELECT
      CAST(c.white_id AS BIGINT) AS user_id,
      CAST(c.game_id AS VARCHAR) AS game_id,
      CAST(c.utc_ms AS BIGINT) AS game_start_ms
    FROM read_parquet({chron_sql}, union_by_name=true) c
    INNER JOIN repeat_users u ON CAST(c.white_id AS BIGINT)=u.user_id
    WHERE CAST(c.utc_ms AS BIGINT)>={SESSION_LEFT_MS}
      AND CAST(c.utc_ms AS BIGINT)<{PANEL_END_MS}

    UNION ALL

    SELECT
      CAST(c.black_id AS BIGINT) AS user_id,
      CAST(c.game_id AS VARCHAR) AS game_id,
      CAST(c.utc_ms AS BIGINT) AS game_start_ms
    FROM read_parquet({chron_sql}, union_by_name=true) c
    INNER JOIN repeat_users u ON CAST(c.black_id AS BIGINT)=u.user_id
    WHERE CAST(c.utc_ms AS BIGINT)>={SESSION_LEFT_MS}
      AND CAST(c.utc_ms AS BIGINT)<{PANEL_END_MS}
    """)

    hist_rows = int(con.execute("SELECT count(*) FROM repeat_history").fetchone()[0])
    hist_users = int(
        con.execute("SELECT count(DISTINCT user_id) FROM repeat_history").fetchone()[0]
    )
    if hist_users != EXPECTED_B1_CHOOSERS:
        raise RuntimeError(
            f"All-game chronology missing repeat granters: {hist_users}/{EXPECTED_B1_CHOOSERS}"
        )

    # Session ID = cumulative break at consecutive start gaps >=30m.
    con.execute(f"""
    CREATE TEMP TABLE repeat_sessionized AS
    WITH lagged AS (
      SELECT
        user_id,game_id,game_start_ms,
        lag(game_start_ms) OVER (
          PARTITION BY user_id ORDER BY game_start_ms,game_id
        ) AS prev_start_ms
      FROM repeat_history
    )
    SELECT
      user_id,game_id,game_start_ms,
      sum(
        CASE WHEN prev_start_ms IS NULL
                   OR game_start_ms-prev_start_ms >= {SESSION_GAP_MS}
             THEN 1 ELSE 0 END
      ) OVER (
        PARTITION BY user_id ORDER BY game_start_ms,game_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ) AS session_id
    FROM lagged
    """)

    con.execute("""
    CREATE TEMP TABLE b1_sessions AS
    SELECT
      m.b1_row_id,
      m.chooser_index,
      m.sequence_index,
      CAST(m.canonical_speed AS VARCHAR) AS canonical_speed,
      CAST(s.session_id AS BIGINT) AS session_id
    FROM b1_game_map m
    LEFT JOIN repeat_sessionized s
      ON s.user_id=m.chooser_user_id
     AND s.game_id=m.game_id
    """)

    sess = con.execute("""
    SELECT
      count(*) total,
      count(session_id) resolved,
      count(DISTINCT chooser_index) choosers,
      count(DISTINCT chooser_index) FILTER (WHERE session_id IS NOT NULL) resolved_choosers
    FROM b1_sessions
    """).fetchone()
    total, resolved, choosers, resolved_choosers = map(int, sess)
    share = resolved / total if total else 0.0
    if total != EXPECTED_B1_ROWS or choosers != EXPECTED_B1_CHOOSERS:
        raise RuntimeError("B1 session-cache cardinality changed")
    if share < 0.999:
        raise RuntimeError(
            f"Technical all-game session mapping below 99.9%: {resolved}/{total}={share:.6f}"
        )
    missing_speed = int(con.execute("""
    SELECT count(*) FROM b1_sessions
    WHERE canonical_speed IS NULL OR trim(canonical_speed)=''
    """).fetchone()[0])
    if missing_speed != 0:
        raise RuntimeError(
            f"Canonical Stage07 speed missing from {missing_speed} B1 session rows"
        )

    # Historical B2 load_inputs will supply outcome and propensity. Persist only row key,
    # sequence/session and speed, with NO actual user IDs.
    cache = private_root / "b1_c9_session_private.parquet"
    con.execute(f"""
    COPY (
      SELECT
        CAST(b.b1_row_id AS BIGINT) AS b1_row_id,
        CAST(b.chooser_index AS BIGINT) AS chooser_index,
        CAST(b.sequence_index AS BIGINT) AS sequence_index,
        CAST(s.session_id AS BIGINT) AS session_id,
        CAST(s.canonical_speed AS VARCHAR) AS speed
      FROM read_parquet({sqls(str(b1))}) b
      LEFT JOIN b1_sessions s USING(b1_row_id)
      ORDER BY chooser_index,sequence_index
    ) TO {sqls(str(cache))}
    (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    cache_rows = parquet_rows(cache)
    if cache_rows != EXPECTED_B1_ROWS:
        raise RuntimeError(f"C9 session private cache rows changed: {cache_rows}")

    report = {
        "status": "C9_ALL_GAME_SESSION_CACHE_OK",
        "session_definition": "consecutive all-rated-game start timestamps with gap < 30m",
        "timestamp_mode": "start_to_start_v1_0_3_fallback",
        "chronology_files_read": len(chosen),
        "chronology_metadata_rows_in_selected_files": sum(x["rows"] for x in chosen),
        "repeat_granter_all_game_rows": hist_rows,
        "repeat_granter_users": hist_users,
        "b1_rows": total,
        "b1_rows_with_session": resolved,
        "b1_session_resolution_share": share,
        "canonical_stage07_speed_rows_missing": missing_speed,
        "speed_source": "Stage07 api_speed via non-outcome B1-to-Stage07 row bridge",
        "persisted_private_cache": str(cache),
        "persisted_private_cache_sha256": sha256_file(cache),
        "persisted_cache_contains_actual_user_id": False,
        "persisted_cache_contains_game_id": False,
    }
    write_json(staging / "c9_session_mapping.json", report)
    print(
        f"C9_ALL_GAME_SESSION_BUILD_OK history_rows={hist_rows:,} "
        f"b1_session_share={share:.6f}",
        flush=True,
    )
    return cache, report


def outcome_blind_support(b1: Path, session_cache: Path, staging: Path) -> dict[str, Any]:
    """
    Support over every structurally possible anchor position. Does not read kind_draw.
    """
    import numpy as np
    import pyarrow.parquet as pq

    b = pq.read_table(
        b1,
        columns=["chooser_index", "sequence_index", "utc_ms"],
    ).to_pandas()
    s = pq.read_table(
        session_cache,
        columns=["chooser_index", "sequence_index", "session_id", "speed"],
    ).to_pandas()

    b = b.sort_values(["chooser_index", "sequence_index"], kind="stable").reset_index(drop=True)
    s = s.sort_values(["chooser_index", "sequence_index"], kind="stable").reset_index(drop=True)
    if not np.array_equal(b["chooser_index"].to_numpy(), s["chooser_index"].to_numpy()):
        raise RuntimeError("Support alignment chooser_index mismatch")
    if not np.array_equal(b["sequence_index"].to_numpy(), s["sequence_index"].to_numpy()):
        raise RuntimeError("Support alignment sequence_index mismatch")

    chooser = b["chooser_index"].to_numpy(dtype=np.int64)
    times = b["utc_ms"].to_numpy(dtype=np.int64)
    sessions = s["session_id"].to_numpy(dtype=np.int64)
    speeds = s["speed"].astype(str).to_numpy()

    boundaries = np.flatnonzero(np.r_[True, chooser[1:] != chooser[:-1], True])

    support = {
        "possible_anchor_rows": 0,
        "anchors_with_any_post_7d": 0,
        "anchors_with_later_session_post_7d": 0,
        "anchors_with_same_session_post_7d": 0,
        "anchors_with_any_post_24h": 0,
        "anchors_with_same_pool_post_24h": 0,
        "anchors_with_cross_pool_post_24h": 0,
        "later_session_opportunity_pairs_7d": 0,
        "same_session_opportunity_pairs_7d": 0,
        "same_pool_opportunity_pairs_24h": 0,
        "cross_pool_opportunity_pairs_24h": 0,
    }

    for a, z in zip(boundaries[:-1], boundaries[1:]):
        t = times[a:z]
        ss = sessions[a:z]
        sp = speeds[a:z]
        n = z - a
        for i in range(n):
            after = np.arange(n) > i
            dtm = t - t[i]
            w7 = after & (dtm <= C9_7D_MS)
            w24 = after & (dtm <= C9_24H_MS)
            same_s = ss == ss[i]
            same_p = sp == sp[i]
            support["possible_anchor_rows"] += 1
            if np.any(w7):
                support["anchors_with_any_post_7d"] += 1
            if np.any(w7 & ~same_s):
                support["anchors_with_later_session_post_7d"] += 1
            if np.any(w7 & same_s):
                support["anchors_with_same_session_post_7d"] += 1
            if np.any(w24):
                support["anchors_with_any_post_24h"] += 1
            if np.any(w24 & same_p):
                support["anchors_with_same_pool_post_24h"] += 1
            if np.any(w24 & ~same_p):
                support["anchors_with_cross_pool_post_24h"] += 1
            support["later_session_opportunity_pairs_7d"] += int(np.count_nonzero(w7 & ~same_s))
            support["same_session_opportunity_pairs_7d"] += int(np.count_nonzero(w7 & same_s))
            support["same_pool_opportunity_pairs_24h"] += int(np.count_nonzero(w24 & same_p))
            support["cross_pool_opportunity_pairs_24h"] += int(np.count_nonzero(w24 & ~same_p))

    result = {
        "status": "C9_OUTCOME_BLIND_SUPPORT_FROZEN",
        "kind_draw_read": False,
        "pseudo_first_grant_used": False,
        "support_definition": "all structurally possible B1 anchor positions",
        **{k: int(v) for k, v in support.items()},
    }
    write_json(staging / "c9_support_frozen.json", result)
    print("C9_OUTCOME_BLIND_SUPPORT_FROZEN_OK", flush=True)
    return result


def randomization_tail_p(observed: float, simulated) -> tuple[float, float, float]:
    import numpy as np
    finite = np.asarray(simulated, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise RuntimeError("No finite randomization values")
    lower = (1 + int(np.count_nonzero(finite <= observed))) / (finite.size + 1.0)
    upper = (1 + int(np.count_nonzero(finite >= observed))) / (finite.size + 1.0)
    return lower, upper, min(1.0, 2.0 * min(lower, upper))


def quantile(values, p: float) -> float:
    import numpy as np
    a = np.asarray(values, dtype=np.float64)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return math.nan
    return float(np.quantile(a, p, method="linear"))


def c9_totals(times, sessions, speeds, choices):
    """
    choices: simulations x n bool. Every simulation has >=1 grant.
    Returns C9 category totals plus B2 horizon totals for exact inheritance validation.
    """
    import numpy as np

    times = np.asarray(times, dtype=np.int64)
    sessions = np.asarray(sessions, dtype=np.int64)
    speeds = np.asarray(speeds)
    choices = np.asarray(choices, dtype=bool)
    simulations, n = choices.shape

    first = np.argmax(choices, axis=1)
    pos = np.arange(n, dtype=np.int64)[None, :]
    first_col = first[:, None]
    after = pos > first_col
    first_time = times[first][:, None]
    delta = times[None, :] - first_time

    session_at_first = sessions[first][:, None]
    speed_at_first = speeds[first][:, None]

    within7 = after & (delta <= C9_7D_MS)
    same_session_mask = within7 & (sessions[None, :] == session_at_first)
    later_session_mask = within7 & (sessions[None, :] != session_at_first)

    within24 = after & (delta <= C9_24H_MS)
    same_pool_mask = within24 & (speeds[None, :] == speed_at_first)
    cross_pool_mask = within24 & (speeds[None, :] != speed_at_first)

    def nd(mask):
        den = np.count_nonzero(mask, axis=1).astype(np.int64)
        num = np.count_nonzero(choices & mask, axis=1).astype(np.int64)
        return num, den

    same_num, same_den = nd(same_session_mask)
    later_num, later_den = nd(later_session_mask)
    sp_num, sp_den = nd(same_pool_mask)
    cp_num, cp_den = nd(cross_pool_mask)

    b2_num = np.zeros((simulations, 3), dtype=np.int64)
    b2_den = np.zeros_like(b2_num)
    for hidx, h in enumerate((6 * HOUR_MS, 24 * HOUR_MS, 168 * HOUR_MS)):
        mask = after & (delta <= h)
        b2_num[:, hidx], b2_den[:, hidx] = nd(mask)

    return {
        "same7_num": same_num,
        "same7_den": same_den,
        "later7_num": later_num,
        "later7_den": later_den,
        "samepool24_num": sp_num,
        "samepool24_den": sp_den,
        "crosspool24_num": cp_num,
        "crosspool24_den": cp_den,
        "b2_num": b2_num,
        "b2_den": b2_den,
    }


def load_session_vectors(path: Path):
    import numpy as np
    import pyarrow.parquet as pq
    t = pq.read_table(
        path, columns=["chooser_index", "sequence_index", "session_id", "speed"]
    ).to_pandas()
    t = t.sort_values(["chooser_index", "sequence_index"], kind="stable")
    return (
        t["chooser_index"].to_numpy(dtype=np.int64),
        t["sequence_index"].to_numpy(dtype=np.int64),
        t["session_id"].to_numpy(dtype=np.int64),
        t["speed"].astype(str).to_numpy(),
    )


def initialize_worker(
    b1_path: str,
    propensity_path: str,
    session_path: str,
    historical_b2_path: str,
) -> None:
    import numpy as np

    global _WORKER_DATA, _WORKER_PROB, _WORKER_SLICES, _WORKER_SELECTIONS
    global _WORKER_SESSION, _WORKER_SPEED, _WORKER_B2

    _WORKER_B2 = import_module_from_path(
        f"historical_b2_worker_{os.getpid()}", Path(historical_b2_path)
    )
    _WORKER_DATA, _WORKER_PROB = _WORKER_B2.load_inputs(
        Path(b1_path), Path(propensity_path)
    )
    _WORKER_SLICES = _WORKER_B2.chooser_slices(_WORKER_DATA["chooser_index"])

    sc, ssq, sess, speed = load_session_vectors(Path(session_path))
    dc = np.asarray(_WORKER_DATA["chooser_index"], dtype=np.int64)
    if not np.array_equal(sc, dc):
        raise RuntimeError("Worker session/B2 chooser order mismatch")

    # sequence_index is checked directly against B1 because historical B2 data may not
    # expose it in its returned dictionary.
    import pyarrow.parquet as pq
    bt = pq.read_table(
        Path(b1_path), columns=["chooser_index", "sequence_index"]
    ).to_pandas().sort_values(["chooser_index", "sequence_index"], kind="stable")
    if not np.array_equal(sc, bt["chooser_index"].to_numpy(dtype=np.int64)):
        raise RuntimeError("Worker sorted B1/session chooser alignment mismatch")
    if not np.array_equal(ssq, bt["sequence_index"].to_numpy(dtype=np.int64)):
        raise RuntimeError("Worker B1/session sequence alignment mismatch")

    # Historical B2 load_inputs is expected to preserve chooser/sequence sorted order.
    if dc.shape[0] != sess.shape[0]:
        raise RuntimeError("Worker session vector length mismatch")

    _WORKER_SESSION = sess
    _WORKER_SPEED = speed
    _WORKER_SELECTIONS = []
    for start, stop in _WORKER_SLICES:
        observed = _WORKER_DATA["kind_draw"][start:stop]
        log_odds = np.log(_WORKER_PROB[start:stop]) - np.log1p(-_WORKER_PROB[start:stop])
        _WORKER_SELECTIONS.append(
            _WORKER_B2.conditional_selection_probabilities(
                log_odds, int(np.count_nonzero(observed))
            )
        )


def batch_checkpoint_paths(state: Path, start: int, stop: int) -> tuple[Path, Path]:
    p = state / "randomizations" / f"c9_{start:04d}_{stop-1:04d}.npz"
    return p, p.with_suffix(".json")


def authenticate_checkpoint(
    path: Path, receipt: Path, start: int, stop: int, config_sha: str
) -> dict[str, Any] | None:
    import numpy as np
    if not path.exists() and not receipt.exists():
        return None
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Incomplete C9 checkpoint {start}")
    saved = json.loads(receipt.read_text())
    expected = {
        "status": "DYNAMICS_CAMPAIGN1_C9_RANDOMIZATION_BATCH_OK",
        "config_sha256": config_sha,
        "start": start,
        "stop_exclusive": stop,
        "seed_components": [B2_SEED, start, stop],
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
    }
    for k, v in expected.items():
        if saved.get(k) != v:
            raise RuntimeError(f"C9 checkpoint mismatch {start}: {k}")
    z = np.load(path)
    expected_shapes = {
        "same7_num": (stop-start,),
        "same7_den": (stop-start,),
        "later7_num": (stop-start,),
        "later7_den": (stop-start,),
        "samepool24_num": (stop-start,),
        "samepool24_den": (stop-start,),
        "crosspool24_num": (stop-start,),
        "crosspool24_den": (stop-start,),
        "b2_num": (stop-start,3),
        "b2_den": (stop-start,3),
    }
    for k, shape in expected_shapes.items():
        if z[k].shape != shape:
            raise RuntimeError(f"C9 checkpoint shape mismatch {start}: {k}")
    return saved


def worker_batch(start: int, stop: int, state_text: str, config_sha: str):
    import numpy as np

    if any(
        x is None for x in (
            _WORKER_DATA, _WORKER_PROB, _WORKER_SLICES,
            _WORKER_SELECTIONS, _WORKER_SESSION, _WORKER_SPEED, _WORKER_B2
        )
    ):
        raise RuntimeError("C9 worker was not initialized")

    state = Path(state_text)
    path, receipt = batch_checkpoint_paths(state, start, stop)
    if path.exists() or receipt.exists():
        raise RuntimeError(f"C9 worker received existing checkpoint {start}")

    sims = stop - start
    rng = np.random.default_rng(np.random.SeedSequence([B2_SEED, start, stop]))

    totals = {
        "same7_num": np.zeros(sims, dtype=np.int64),
        "same7_den": np.zeros(sims, dtype=np.int64),
        "later7_num": np.zeros(sims, dtype=np.int64),
        "later7_den": np.zeros(sims, dtype=np.int64),
        "samepool24_num": np.zeros(sims, dtype=np.int64),
        "samepool24_den": np.zeros(sims, dtype=np.int64),
        "crosspool24_num": np.zeros(sims, dtype=np.int64),
        "crosspool24_den": np.zeros(sims, dtype=np.int64),
        "b2_num": np.zeros((sims,3), dtype=np.int64),
        "b2_den": np.zeros((sims,3), dtype=np.int64),
    }

    started = time.time()
    for chooser_no, ((a, z), selection) in enumerate(
        zip(_WORKER_SLICES, _WORKER_SELECTIONS)
    ):
        observed = _WORKER_DATA["kind_draw"][a:z]
        n = z - a
        k = int(np.count_nonzero(observed))
        remaining = np.full(sims, k, dtype=np.int32)
        choices = np.zeros((sims, n), dtype=bool)

        # EXACT historical B2 draw loop. No extra RNG call occurs here.
        for position in range(n):
            left = n - position
            forced = remaining == left
            probability_now = selection[position, remaining]
            chosen = forced | (
                (remaining > 0) & (rng.random(sims) < probability_now)
            )
            choices[:, position] = chosen
            remaining -= chosen.astype(np.int32)

        if np.any(remaining != 0) or np.any(np.count_nonzero(choices, axis=1) != k):
            raise RuntimeError("C9 conditional sampler failed to preserve chooser totals")

        got = c9_totals(
            _WORKER_DATA["utc_ms"][a:z],
            _WORKER_SESSION[a:z],
            _WORKER_SPEED[a:z],
            choices,
        )
        for name in totals:
            totals[name] += got[name]

        if (chooser_no + 1) % 10_000 == 0:
            print(
                f"C9_RANDOMIZATION_CHOOSER_PROGRESS batch={start+1}-{stop} "
                f"choosers={chooser_no+1:,}/{len(_WORKER_SLICES):,}",
                flush=True,
            )

    tmp = path.with_suffix(".npz.tmp")
    with tmp.open("wb") as f:
        np.savez_compressed(f, **totals)
    os.replace(tmp, path)

    saved = {
        "status": "DYNAMICS_CAMPAIGN1_C9_RANDOMIZATION_BATCH_OK",
        "created_utc": now(),
        "config_sha256": config_sha,
        "start": start,
        "stop_exclusive": stop,
        "seed_components": [B2_SEED, start, stop],
        "output_path": str(path),
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
        "runtime_seconds": time.time() - started,
    }
    write_json(receipt, saved)
    return saved


def observed_totals(data, session, speed):
    import numpy as np
    slices = _chooser_slices(np.asarray(data["chooser_index"], dtype=np.int64))
    totals = {
        "same7_num": np.zeros(1, dtype=np.int64),
        "same7_den": np.zeros(1, dtype=np.int64),
        "later7_num": np.zeros(1, dtype=np.int64),
        "later7_den": np.zeros(1, dtype=np.int64),
        "samepool24_num": np.zeros(1, dtype=np.int64),
        "samepool24_den": np.zeros(1, dtype=np.int64),
        "crosspool24_num": np.zeros(1, dtype=np.int64),
        "crosspool24_den": np.zeros(1, dtype=np.int64),
        "b2_num": np.zeros((1,3), dtype=np.int64),
        "b2_den": np.zeros((1,3), dtype=np.int64),
    }
    for a, z in slices:
        choices = np.asarray(data["kind_draw"][a:z], dtype=bool)[None, :]
        got = c9_totals(data["utc_ms"][a:z], session[a:z], speed[a:z], choices)
        for name in totals:
            totals[name] += got[name]
    return totals


def _chooser_slices(chooser):
    import numpy as np
    boundaries = np.flatnonzero(np.r_[True, chooser[1:] != chooser[:-1], True])
    return [(int(a), int(z)) for a, z in zip(boundaries[:-1], boundaries[1:])]


def run_randomizations(
    b1: Path,
    prop: Path,
    session_cache: Path,
    historical_b2_path: Path,
    state: Path,
    config_sha: str,
    workers: int,
):
    import numpy as np

    specs = []
    pending = []
    for start in range(0, RANDOMIZATIONS, BATCH):
        stop = min(start + BATCH, RANDOMIZATIONS)
        p, r = batch_checkpoint_paths(state, start, stop)
        specs.append((start, stop, p, r))
        if authenticate_checkpoint(p, r, start, stop, config_sha) is None:
            pending.append((start, stop))

    print(
        f"C9_RANDOMIZATION_CHECKPOINTS existing={len(specs)-len(pending)} "
        f"pending={len(pending)} workers={workers}",
        flush=True,
    )

    inventory = {
        "status": "C9_RANDOMIZATION_CHECKPOINT_INVENTORY_AUTHENTICATED",
        "expected_batches": len(specs),
        "existing_batches": len(specs) - len(pending),
        "pending_batches": len(pending),
        "expected_randomizations": RANDOMIZATIONS,
        "require_existing": True,
        "new_randomizations_drawn": 0,
    }

    # This recovery runner has no recomputation branch.  Its only authorized
    # operation is to authenticate and combine the already-completed v1.0.0
    # checkpoints.  A missing or invalid batch therefore fails before any RNG
    # worker can be initialized.
    if pending:
        raise RuntimeError(
            "Serialization-only C9 recovery requires every existing checkpoint; "
            f"missing batches={pending}. No recomputation was attempted."
        )

    arrays = {
        "same7_num": [], "same7_den": [],
        "later7_num": [], "later7_den": [],
        "samepool24_num": [], "samepool24_den": [],
        "crosspool24_num": [], "crosspool24_den": [],
        "b2_num": [], "b2_den": [],
    }
    for start, stop, p, r in specs:
        authenticate_checkpoint(p, r, start, stop, config_sha)
        z = np.load(p)
        for name in arrays:
            arrays[name].append(np.asarray(z[name]))
    out = {k: np.concatenate(v, axis=0) for k, v in arrays.items()}
    if out["later7_num"].shape[0] != RANDOMIZATIONS:
        raise RuntimeError("C9 combined randomization count changed")
    return out, inventory


def rate(num, den):
    import numpy as np
    return np.divide(
        np.asarray(num, dtype=np.float64),
        np.asarray(den, dtype=np.float64),
        out=np.full(np.asarray(num).shape, np.nan, dtype=np.float64),
        where=np.asarray(den) > 0,
    )


def b2_validation(observed, sim, b2_public: Path) -> dict[str, Any]:
    """
    The C9 draw engine must reproduce certified B2 exactly. This proves that we inherited
    the historical conditional draws rather than merely a similar sampler.
    """
    import pandas as pd
    public = pd.read_csv(b2_public / "b2_first_grant_horizons.csv")
    obs_rates = rate(observed["b2_num"][0], observed["b2_den"][0])
    sim_rates = rate(sim["b2_num"], sim["b2_den"])

    checks = []
    for idx, hours in enumerate((6.0, 24.0, 168.0)):
        row = public.loc[public["horizon_hours"] == hours].iloc[0]
        vals = sim_rates[:, idx]
        null_mean = float(vals.mean())
        p = randomization_tail_p(float(obs_rates[idx]), vals)[2]
        got = {
            "horizon_hours": hours,
            "observed_numerator": int(observed["b2_num"][0, idx]),
            "observed_denominator": int(observed["b2_den"][0, idx]),
            "observed_rate": float(obs_rates[idx]),
            "null_mean_rate": null_mean,
            "randomization_p_two_sided": p,
        }
        exp = {
            "observed_numerator": int(row["observed_numerator"]),
            "observed_denominator": int(row["observed_denominator"]),
            "observed_rate": float(row["observed_rate"]),
            "null_mean_rate": float(row["null_mean_rate"]),
            "randomization_p_two_sided": float(row["randomization_p_two_sided"]),
        }
        for k in exp:
            if k in ("observed_numerator", "observed_denominator"):
                if got[k] != exp[k]:
                    raise RuntimeError(f"C9 did not reproduce certified B2 {hours}h {k}")
            else:
                if abs(got[k] - exp[k]) > 1e-12:
                    raise RuntimeError(
                        f"C9 did not reproduce certified B2 {hours}h {k}: "
                        f"got={got[k]} expected={exp[k]}"
                    )
        checks.append({"expected": exp, "reproduced": got})

    return {
        "status": "C9_EXACT_B2_RANDOMIZATION_REPRODUCTION_OK",
        "checks": checks,
        "historical_randomizations": RANDOMIZATIONS,
        "historical_seed": B2_SEED,
    }


def summarize_c9(observed, sim) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    import numpy as np

    categories = [
        ("same_session_7d", "same7_num", "same7_den", "S_component"),
        ("later_session_7d", "later7_num", "later7_den", "C_primary"),
        ("same_pool_24h", "samepool24_num", "samepool24_den", "S_component"),
        ("cross_pool_24h", "crosspool24_num", "crosspool24_den", "S_component"),
    ]
    rows = []
    sims = {}
    obs = {}

    for label, nk, dk, epistemic in categories:
        orate = float(rate(observed[nk][0], observed[dk][0]))
        vals = rate(sim[nk], sim[dk])
        finite = vals[np.isfinite(vals)]
        null = float(finite.mean())
        lo, up, p = randomization_tail_p(orate, finite)
        obs[label] = orate
        sims[label] = vals
        rows.append({
            "category": label,
            "epistemic_role": epistemic,
            "epistemic_label": "C" if epistemic == "C_primary" else "S",
            "holm_adjusted_p_value": (
                "PENDING_C5_C6_AND_FAMILY_COMPLETION"
                if epistemic == "C_primary" else None
            ),
            "interpretation": (
                "positive excess is consistent with habit/identity transfer beyond "
                "the initiating session"
                if epistemic == "C_primary" else None
            ),
            "observed_numerator": int(observed[nk][0]),
            "observed_denominator": int(observed[dk][0]),
            "observed_rate": orate,
            "observed_rate_pct": 100 * orate,
            "null_mean_rate": null,
            "null_mean_rate_pct": 100 * null,
            "excess_percentage_points": 100 * (orate - null),
            "effect_relative_to_null_mean_pct":
                100 * (orate - null) / null if null else None,
            "randomization_p_two_sided": p,
            "lower_tail_plus_one": lo,
            "upper_tail_plus_one": up,
            "null_p025": quantile(finite, 0.025),
            "null_p975": quantile(finite, 0.975),
            "randomizations": int(finite.size),
        })

    primary = next(x for x in rows if x["category"] == "later_session_7d")
    component_schema=list(rows[0].keys())
    if any(list(row.keys()) != component_schema for row in rows):
        raise RuntimeError("C9 component rows do not share one explicit ordered schema")

    # Secondary contrasts compare observed category difference to its conditional null.
    contrast_specs = [
        (
            "same_session_minus_later_session_excess_7d",
            "same_session_7d", "later_session_7d",
            "state_component_size",
        ),
        (
            "same_pool_minus_cross_pool_excess_24h",
            "same_pool_24h", "cross_pool_24h",
            "context_boundness",
        ),
    ]
    contrast_rows = []
    for name, a, b, meaning in contrast_specs:
        observed_diff = obs[a] - obs[b]
        sim_diff = sims[a] - sims[b]
        finite = sim_diff[np.isfinite(sim_diff)]
        null_mean = float(finite.mean())
        lo, up, p = randomization_tail_p(observed_diff, finite)
        contrast_rows.append({
            "contrast": name,
            "epistemic_label": "S",
            "mechanism_role": meaning,
            "observed_rate_difference": observed_diff,
            "observed_rate_difference_pp": 100 * observed_diff,
            "null_mean_rate_difference": null_mean,
            "null_mean_rate_difference_pp": 100 * null_mean,
            "excess_difference_pp": 100 * (observed_diff - null_mean),
            "randomization_p_two_sided": p,
            "lower_tail_plus_one": lo,
            "upper_tail_plus_one": up,
            "null_p025": quantile(finite, 0.025),
            "null_p975": quantile(finite, 0.975),
            "randomizations": int(finite.size),
        })

    summary = {
        "primary_raw_p_value": primary["randomization_p_two_sided"],
        "primary_excess_percentage_points": primary["excess_percentage_points"],
        "primary_observed_rate_pct": primary["observed_rate_pct"],
        "primary_null_mean_rate_pct": primary["null_mean_rate_pct"],
        "component_csv_schema": component_schema,
        "component_csv_schema_uniform": True,
    }
    return rows, contrast_rows, summary


def self_test() -> None:
    import numpy as np
    import tempfile
    times = np.array([0, 10, 40, 50], dtype=np.int64) * 60_000
    sessions = np.array([1, 1, 2, 2], dtype=np.int64)
    speeds = np.array(["blitz", "blitz", "rapid", "rapid"])
    choices = np.array([
        [True, False, True, False],
        [False, True, False, True],
    ], dtype=bool)
    got = c9_totals(times, sessions, speeds, choices)
    # Sim 0 first at position0: pos1 same session; pos2/3 later, and rapid cross pool.
    assert got["same7_den"][0] == 1
    assert got["later7_den"][0] == 2
    assert got["later7_num"][0] == 1
    assert got["crosspool24_den"][0] == 2
    # Sim1 first at pos1: both later positions are later session/cross pool.
    assert got["same7_den"][1] == 0
    assert got["later7_den"][1] == 2
    assert got["later7_num"][1] == 1

    # Exact regression test for the v1.0.0 publication failure: a field introduced by
    # a later row must be included without a partial-write exception.
    temp = Path(tempfile.mkdtemp(prefix="c9_csv_selftest_"))
    try:
        csv_path = temp / "heterogeneous.csv"
        write_csv(csv_path, [{"a": 1}, {"a": 2, "primary_only": "x"}])
        with csv_path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert list(rows[0].keys()) == ["a", "primary_only"]
        assert rows[0]["primary_only"] == ""
        assert rows[1]["primary_only"] == "x"
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    print("DYNAMICS_CAMPAIGN1_C9_SELF_TEST_OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, default=PROJECT)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--memory-limit", default="12GB")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--execution-pointer", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return

    project = args.project_root
    repo = project / "replication_package"

    core_private = project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    b1 = core_private / "b1_repeat_granter_private.parquet"
    prop = core_private / "b1_crossfit_propensity_private.parquet"

    stage07 = project / "derived/replication/analysis_panel_24m_sf100k"
    chron_manifest = (
        project
        / "output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z/"
          "chronology_input_manifest.tsv"
    )
    b2_public = project / "output/dynamic_second_wave_b2_v100/20260822T150914Z"
    b2_success = b2_public / "_SUCCESS.json"
    b2_summary = b2_public / "summary.json"

    base = repo / "docs/dynamics_paper2_campaign1_analysis_plan_v1_0_0.md"
    amd101 = repo / "docs/dynamics_paper2_campaign1_analysis_plan_v1_0_1_amendment.md"
    amd102 = repo / "docs/dynamics_paper2_campaign1_analysis_plan_v1_0_2_amendment.md"
    amd103 = repo / "docs/dynamics_paper2_campaign1_analysis_plan_v1_0_3_amendment.md"
    anchor_manifest = repo / "manifests/dynamics_campaign1_b2_anchoring_precondition_v1_0_0.json"

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_base = project / "output/dynamics_campaign1_c9_recovery_v101"
    existing_successes = (
        [p for p in output_base.glob("*/_SUCCESS.json") if p.is_file()]
        if output_base.exists() else []
    )
    if existing_successes:
        raise RuntimeError(
            "A C9 v1.0.1 recovery success already exists; refusing duplicate "
            f"publication: {existing_successes}"
        )
    staging = output_base / f".{run_id}.tmp.{os.getpid()}"
    final = output_base / run_id

    private_root = project / "derived/replication/dynamics_campaign1_c9_v100_PRIVATE"
    staging.mkdir(parents=True, exist_ok=False)
    tempdir = staging / "duckdb_tmp"
    started = time.time()

    try:
        print("C9_V101_SERIALIZATION_RECOVERY_PREFLIGHT_BEGIN", flush=True)

        packaged_recovery_evidence = authenticate_packaged_recovery_evidence()

        if not private_root.is_dir():
            raise RuntimeError(f"Existing C9 private root missing: {private_root}")
        if not (private_root / "randomizations").is_dir():
            raise RuntimeError("Existing C9 randomization checkpoint directory missing")

        run(["git", "fetch", "origin", "main", "--quiet"], cwd=repo)
        head = run(["git", "rev-parse", "HEAD"], cwd=repo)
        remote = run(["git", "rev-parse", "origin/main"], cwd=repo)
        if head != remote or head != EXPECTED_GIT:
            raise RuntimeError(f"Git authority mismatch local={head} remote={remote}")
        if run(["git", "status", "--porcelain"], cwd=repo):
            raise RuntimeError("Git worktree dirty")

        authorities = {
            "base_plan": (base, EXPECTED_BASE_SHA),
            "amendment_101": (amd101, EXPECTED_AMD101_SHA),
            "amendment_102": (amd102, EXPECTED_AMD102_SHA),
            "amendment_103": (amd103, EXPECTED_AMD103_SHA),
            "b2_anchoring_precondition": (anchor_manifest, B2_ANCHOR_MANIFEST_SHA),
            "b1_sample": (b1, EXPECTED_B1_SHA),
            "b1_propensity": (prop, EXPECTED_PROP_SHA),
            "b2_success": (b2_success, EXPECTED_B2_SUCCESS_SHA),
            "b2_summary": (b2_summary, EXPECTED_B2_SUMMARY_SHA),
        }
        for label, (p, expected) in authorities.items():
            if not p.is_file():
                raise RuntimeError(f"Authority missing: {label}: {p}")
            actual = sha256_file(p)
            if actual != expected:
                raise RuntimeError(
                    f"Authority SHA mismatch {label}: expected={expected} actual={actual}"
                )

        if parquet_rows(b1) != EXPECTED_B1_ROWS or parquet_rows(prop) != EXPECTED_B1_ROWS:
            raise RuntimeError("B1/propensity row count mismatch")

        # Historical B2 exact source loaded from the audited commit.
        hist_b2 = historical_b2_source(repo, staging)
        b2mod = import_module_from_path("historical_b2_main", hist_b2)
        if int(b2mod.RANDOMIZATIONS) != RANDOMIZATIONS:
            raise RuntimeError("Historical B2 randomization count changed")
        if int(b2mod.B2_SEED) != B2_SEED:
            raise RuntimeError("Historical B2 seed changed")

        # Load exact historical B2 inputs now only for cardinality certification. This
        # is the first read of the B1 outcome in this producer; all mapping/session
        # support below is kept outcome-blind until support is frozen.
        # We defer this call until after non-outcome mapping/session work.
        s7 = stage07_paths(stage07)
        if not s7 or total_rows(s7) != EXPECTED_STAGE07_ROWS:
            raise RuntimeError("Stage07 authority row count mismatch")

        cm = chronology_manifest_rows(chron_manifest)
        if len(cm) != EXPECTED_CHRON_FILES or sum(x["rows"] for x in cm) != EXPECTED_CHRON_ROWS:
            raise RuntimeError("Chronology manifest authority mismatch")

        con = setup_duckdb(tempdir, args.threads, args.memory_limit)

        mapping = b1_stage07_mapping(con, b1, s7, staging)

        # Session cache may be reused only if it authenticates to the same B1.
        session_cache = private_root / "b1_c9_session_private.parquet"
        session_receipt_path = private_root / "b1_c9_session_receipt.json"
        session_report = None
        if session_cache.is_file() and session_receipt_path.is_file():
            sr = json.loads(session_receipt_path.read_text())
            expected = {
                "status": "C9_ALL_GAME_SESSION_CACHE_OK",
                "b1_sha256": EXPECTED_B1_SHA,
                "rows": EXPECTED_B1_ROWS,
                "cache_sha256": sha256_file(session_cache),
            }
            if all(sr.get(k) == v for k, v in expected.items()):
                session_report = sr["report"]
                write_json(staging / "c9_session_mapping.json", session_report)
                print("C9_ALL_GAME_SESSION_CACHE_AUTHENTICATED_OK", flush=True)
            else:
                raise RuntimeError(
                    "Existing C9 session private cache does not authenticate; "
                    "refusing overwrite. Inspect/remove via a separate receipted recovery."
                )
        else:
            raise RuntimeError(
                "Serialization-only C9 recovery requires the existing authenticated "
                "session cache and receipt; no rebuild was attempted"
            )

        support = outcome_blind_support(b1, session_cache, staging)

        # NOW load historical B2 outcome+propensity arrays.
        print("C9_B2_INPUT_LOAD_BEGIN", flush=True)
        data, probability = b2mod.load_inputs(b1, prop)
        import numpy as np
        chooser = np.asarray(data["chooser_index"], dtype=np.int64)
        if chooser.size != EXPECTED_B1_ROWS:
            raise RuntimeError("Historical B2 load row count mismatch")
        if int(np.unique(chooser).size) != EXPECTED_B1_CHOOSERS:
            raise RuntimeError("Historical B2 chooser count mismatch")
        if int(np.count_nonzero(data["kind_draw"])) != EXPECTED_B1_KIND:
            raise RuntimeError("Historical B2 kind-draw count mismatch")

        sc, ssq, session_vec, speed_vec = load_session_vectors(session_cache)
        if not np.array_equal(sc, chooser):
            raise RuntimeError("C9 session vector order does not match historical B2 order")
        print("C9_B2_INPUT_LOAD_OK", flush=True)

        # Config binds all private randomization checkpoints.
        config = {
            "status": "DYNAMICS_CAMPAIGN1_C9_PRIVATE_CONFIG_V100",
            "git_head": head,
            "b1_sha256": EXPECTED_B1_SHA,
            "propensity_sha256": EXPECTED_PROP_SHA,
            "session_cache_sha256": sha256_file(session_cache),
            "historical_b2_commit": B2_PRODUCER_COMMIT,
            "historical_b2_blob": B2_PRODUCER_BLOB,
            "historical_b2_source_sha256": sha256_file(hist_b2),
            "randomizations": RANDOMIZATIONS,
            "batch": BATCH,
            "seed": B2_SEED,
            "session_gap_ms": SESSION_GAP_MS,
            "primary_horizon_ms": C9_7D_MS,
            "pool_horizon_ms": C9_24H_MS,
            "pseudo_first_recomputed_each_draw": True,
        }
        config_text = json.dumps(config, sort_keys=True, separators=(",", ":"))
        config_sha = hashlib.sha256(config_text.encode()).hexdigest()
        config["config_sha256"] = config_sha
        config_path = private_root / "CONFIG.json"
        if not config_path.is_file():
            raise RuntimeError(
                "Serialization-only C9 recovery requires the existing private CONFIG"
            )
        old = json.loads(config_path.read_text())
        if old != config:
            raise RuntimeError("C9 private CONFIG mismatch; refusing mixed checkpoints")

        print("C9_OBSERVED_STATISTIC_BEGIN", flush=True)
        observed = observed_totals(data, session_vec, speed_vec)
        print("C9_OBSERVED_STATISTIC_OK", flush=True)

        simulated, checkpoint_inventory = run_randomizations(
            b1, prop, session_cache, hist_b2,
            private_root, config_sha, args.workers,
        )
        if checkpoint_inventory["pending_batches"] != 0:
            raise RuntimeError("C9 recovery checkpoint inventory unexpectedly has pending batches")
        if checkpoint_inventory["new_randomizations_drawn"] != 0:
            raise RuntimeError("C9 serialization recovery drew new randomizations")
        write_json(staging / "c9_checkpoint_recovery_inventory.json", checkpoint_inventory)

        print("C9_EXACT_B2_REPRODUCTION_CHECK_BEGIN", flush=True)
        b2check = b2_validation(observed, simulated, b2_public)
        write_json(staging / "c9_exact_b2_reproduction.json", b2check)
        print("C9_EXACT_B2_REPRODUCTION_OK", flush=True)

        rows, contrasts, c9sum = summarize_c9(observed, simulated)
        if len({tuple(row.keys()) for row in rows}) != 1:
            raise RuntimeError("C9 component schema uniformity check failed before CSV write")
        write_csv(staging / "c9_partition_components.csv", rows)
        write_csv(staging / "c9_secondary_contrasts.csv", contrasts)

        primary = next(r for r in rows if r["category"] == "later_session_7d")
        write_json(staging / "c9_primary_later_session.json", primary)

        public_summary = {
            "status": "DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_OK",
            "created_utc": now(),
            "git_head": head,
            "producer_source": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
                "original_v100_runner_sha256": EXPECTED_ORIGINAL_C9_RUNNER_SHA,
            },
            "recovery_classification": "SERIALIZATION_ONLY",
            "packaged_recovery_evidence": packaged_recovery_evidence,
            "checkpoint_recovery_inventory": checkpoint_inventory,
            "new_randomizations_drawn": 0,
            "epistemic_label_primary": "C",
            "primary_estimand":
                "later-session post-pseudo-first-grant kindness excess within 7 days",
            "primary": primary,
            "secondary_contrasts": contrasts,
            "support": support,
            "b2_exact_reproduction": b2check,
            "session_mapping": session_report,
            "b1_stage07_mapping": mapping,
            "authorities": {
                k: {"path": str(p), "sha256": expected}
                for k, (p, expected) in authorities.items()
            },
            "historical_b2": {
                "commit": B2_PRODUCER_COMMIT,
                "blob": B2_PRODUCER_BLOB,
                "source_sha256": sha256_file(hist_b2),
                "randomizations": RANDOMIZATIONS,
                "seed": B2_SEED,
            },
            "holm_family_note":
                "C9 raw p-value is reported. Final Holm adjustment awaits the valid "
                "corrected C1 result plus C5 and C6; the prior invalid C1 lineages "
                "must never enter the family calculation.",
            "inherited_caveats": [
                "first observed grant in the locked panel, not necessarily first lifetime grant",
                "repeat-granter scope",
                "timing evidence, not a causal claim",
            ],
            "privacy": {
                "account_level_output": False,
                "private_checkpoints_root": str(private_root),
                "private_checkpoint_or_cache_mutation": False,
                "patron_profile_read": False,
                "api_requests": 0,
            },
            "runtime_seconds": time.time() - started,
            **c9sum,
        }
        write_json(staging / "summary.json", public_summary)

        report = []
        for p in sorted(staging.iterdir()):
            if p.is_file() and p.name not in {"_SUCCESS.json", "report_file_hashes.csv"}:
                report.append({
                    "sha256": sha256_file(p),
                    "bytes": p.stat().st_size,
                    "file": p.name,
                })
        write_csv(staging / "report_file_hashes.csv", report)

        success = {
            "status": "DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_OK",
            "created_utc": public_summary["created_utc"],
            "git_head": head,
            "summary_sha256": sha256_file(staging / "summary.json"),
            "report_file_hashes_sha256": sha256_file(staging / "report_file_hashes.csv"),
            "primary_raw_p_value": primary["randomization_p_two_sided"],
            "primary_excess_percentage_points": primary["excess_percentage_points"],
            "randomizations": RANDOMIZATIONS,
            "new_randomizations_drawn": 0,
            "serialization_only_recovery": True,
            "private_checkpoint_or_cache_mutation": False,
            "existing_checkpoint_batches_authenticated":
                checkpoint_inventory["existing_batches"],
            "exact_b2_reproduction": True,
            "account_level_output": False,
            "holm_family_adjustment_complete": False,
        }
        write_json(staging / "_SUCCESS.json", success)

        if tempdir.exists():
            shutil.rmtree(tempdir, ignore_errors=True)
        os.replace(staging, final)
        write_execution_pointer(args.execution_pointer, {
            "status": "DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_OK",
            "result_root": str(final),
            "success_sha256": sha256_file(final / "_SUCCESS.json"),
        })
        print(f"DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_OK: {final}", flush=True)
        print(f"runtime_seconds: {time.time()-started:.1f}", flush=True)

    except Exception as exc:
        diag = {
            "status": "DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_FAIL_CLOSED",
            "created_utc": now(),
            "error": f"{type(exc).__name__}: {exc}",
            "account_level_output": False,
        }
        try:
            write_json(staging / "FAILURE_DIAGNOSTIC.json", diag)
            if tempdir.exists():
                shutil.rmtree(tempdir, ignore_errors=True)
            fail = output_base / f"{run_id}_FAILED"
            if fail.exists():
                shutil.rmtree(fail)
            os.replace(staging, fail)
            write_execution_pointer(args.execution_pointer, {
                "status": "DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_FAIL_CLOSED",
                "result_root": str(fail),
                "failure_diagnostic_sha256": sha256_file(
                    fail / "FAILURE_DIAGNOSTIC.json"
                ),
            })
            print(f"Failure root: {fail}", file=sys.stderr, flush=True)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"DYNAMICS_CAMPAIGN1_C9_RECOVERY_V101_FAIL_CLOSED: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise
