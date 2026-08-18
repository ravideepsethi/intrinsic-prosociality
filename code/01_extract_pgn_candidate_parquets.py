#!/usr/bin/env python3
"""
01_extract_pgn_candidate_parquets.py

Replication Stage 01 for the Lichess Kindness project.

Purpose
-------
Convert raw public monthly Lichess `.pgn.zst` archives into narrow, structured,
monthly Parquet files containing PGN-level "Time forfeit" candidates.

This is the first data-reduction step after raw acquisition.

It does NOT:
  - call the Lichess API,
  - decide API status timeout vs outoftime,
  - reconstruct Glicko-2 payoffs,
  - run Stockfish,
  - build paper tables.

It DOES:
  - stream each raw monthly PGN archive,
  - keep games whose PGN header says `[Termination "Time forfeit"]`,
  - parse those matched games with python-chess,
  - recover the connected chooser / likely disconnected player from last mover,
  - recover final observed board state and last observed clocks,
  - write Parquet outputs,
  - split the candidate pool into API-targeted and deferred-by-clock pools,
  - write stable month-level checkpoints.

Why this exists
---------------
The raw Lichess monthly PGNs are very large. We do not want downstream scripts to
keep rescanning raw `.pgn.zst` files. This script creates a much narrower Parquet
candidate layer that later stages can consume efficiently.

Relationship to existing development scripts
--------------------------------------------
This script consolidates the useful parts of:
  - scripts_clean_v2/310_extract_timeforfeit_candidates_parallel.py
  - scripts/01_extract_timeforfeit_candidates_parallel.py
  - scripts/split_candidate_by_clock_threshold.py

The older scripts wrote CSV first and used separate split scripts. This replication
version writes Parquet directly and checkpoints by month.

Default target months
---------------------
The same expansion months acquired by Stage 00:
  - 2024-10 through 2025-07
  - 2026-01
  - 2026-03 through 2026-06

Checkpointing
-------------
For each month, this script writes:
  derived/replication/pgn_timeforfeit_candidates/month=YYYY-MM/_SUCCESS.json

A month is skipped on rerun if:
  - _SUCCESS.json exists,
  - the main monthly candidate Parquet exists,
  - --force is not passed.

Atomicity
---------
Each month is first written to:
  month=YYYY-MM.tmp_<pid>_<timestamp>/

Only after all Parquets and summaries are complete does the script rename it to:
  month=YYYY-MM/

This avoids treating a half-written monthly folder as complete.

Outputs per month
-----------------
derived/replication/pgn_timeforfeit_candidates/month=YYYY-MM/
  timeforfeit_candidates.parquet
      Full PGN Time-forfeit candidate rows.

  api_target_candidates_ge5s_or_missing.parquet
      Candidate rows that satisfy the live-choice clock rule for API enrichment:
      disconnected clock >= --min-disconnected-clock-seconds OR missing clock
      unless --drop-missing-clock is used.

  api_deferred_candidates_lt5s.parquet
      Candidate rows with finite disconnected clock below threshold.

  api_target_game_ids.parquet
      Minimal API-enrichment input: game_id + archive_month for targeted rows.

  timeforfeit_summary.json
      Month-level QA summary.

  progress.jsonl
      Append-only progress events.

  parse_errors.parquet
      Parse errors for matched games, if any.

  _SUCCESS.json
      Stable completion checkpoint.

Top-level outputs
-----------------
derived/replication/pgn_timeforfeit_candidates/_manifests/
  month_status.csv
  month_status.parquet
  timeforfeit_candidate_paths.txt
  api_target_game_id_paths.txt
  summary.json
"""

from __future__ import annotations

# ----------------------------- Standard library -----------------------------
import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ----------------------------- Third-party deps -----------------------------
# These are required for this stage.
#   chess       : robust PGN mainline parsing and final FEN construction
#   zstandard   : streaming .zst decompression from Python
#   pyarrow     : direct Parquet writing without giant in-memory DataFrames
try:
    import chess
    import chess.pgn
    import pyarrow as pa
    import pyarrow.parquet as pq
    import zstandard
except Exception as e:
    raise SystemExit(
        "Missing required dependency for Stage 01. Required: chess, zstandard, pyarrow.\n"
        "Try using the project venv or installing dependencies.\n"
        f"Import error was: {repr(e)}"
    )


# ------------------------------- Configuration ------------------------------
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
RAW_DIR = PROJECT_ROOT / "raw" / "lichess_pgn_standard"
DEFAULT_OUT_ROOT = PROJECT_ROOT / "derived" / "replication" / "pgn_timeforfeit_candidates"
RUN_LOG_ROOT = PROJECT_ROOT / "output" / "replication_extract_pgn_candidates"

# Target months mirror Stage 00.
DEFAULT_MONTHS = [
    "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07",
    "2026-01",
    "2026-03", "2026-04", "2026-05", "2026-06",
]

BASE_URL = "https://database.lichess.org/standard"

# PGN scanning constants. The old extractor used the same strategy:
# stream line-by-line, detect game boundaries at [Event ...], and keep blocks
# whose header contains exactly [Termination "Time forfeit"].
EVENT_START = "[Event "
TERM_LINE = '[Termination "Time forfeit"]'

# Lichess game IDs are eight alphanumeric characters in the public URL.
SITE_ID_RE = re.compile(r"lichess\.org/([A-Za-z0-9]{8})")

# Clock comments in Lichess PGNs are usually like:
#   { [%clk 0:02:14] }
CLK_RE = re.compile(r"\[%clk\s+([0-9]+):([0-9]{2}):([0-9]{2})\]")

MONTH_RE = re.compile(r"(\d{4}-\d{2})")


# ----------------------------- Output schemas -------------------------------
# Keep the main candidate schema close to the existing main-window Parquets.
# That makes downstream code easier to adapt and audit.
CANDIDATE_FIELDS = [
    "archive_month",
    "game_id",
    "site",
    "event",
    "utc_date",
    "utc_time",
    "white",
    "black",
    "white_elo",
    "black_elo",
    "white_rating_diff",
    "black_rating_diff",
    "result",
    "termination",
    "time_control",
    "tc_base_s",
    "tc_inc_s",
    "last_mover_color",
    "candidate_chooser",
    "candidate_chooser_color",
    "candidate_chooser_elo",
    "likely_disconnected_player",
    "likely_disconnected_color",
    "likely_disconnected_elo",
    "white_clock_last_obs_s",
    "black_clock_last_obs_s",
    "chooser_clock_last_obs_s",
    "disconnected_clock_last_obs_s",
    "clock_gap_chooser_minus_disconnected_s",
    "disconnected_clock_positive",
    "chooser_raw_win",
    "raw_draw",
    "last_move_uci",
    "last_move_san",
    "ply_count",
    "side_to_move_after_last",
    "fen_after_last_move",
    "tournament_like_event",
]

# Explicit schema prevents PyArrow from inferring a different type in a month
# where one column is all missing.
CANDIDATE_SCHEMA = pa.schema([
    ("archive_month", pa.large_string()),
    ("game_id", pa.large_string()),
    ("site", pa.large_string()),
    ("event", pa.large_string()),
    ("utc_date", pa.large_string()),
    ("utc_time", pa.large_string()),
    ("white", pa.large_string()),
    ("black", pa.large_string()),
    ("white_elo", pa.int64()),
    ("black_elo", pa.int64()),
    ("white_rating_diff", pa.float64()),
    ("black_rating_diff", pa.float64()),
    ("result", pa.large_string()),
    ("termination", pa.large_string()),
    ("time_control", pa.large_string()),
    ("tc_base_s", pa.float64()),
    ("tc_inc_s", pa.float64()),
    ("last_mover_color", pa.large_string()),
    ("candidate_chooser", pa.large_string()),
    ("candidate_chooser_color", pa.large_string()),
    ("candidate_chooser_elo", pa.int64()),
    ("likely_disconnected_player", pa.large_string()),
    ("likely_disconnected_color", pa.large_string()),
    ("likely_disconnected_elo", pa.int64()),
    ("white_clock_last_obs_s", pa.float64()),
    ("black_clock_last_obs_s", pa.float64()),
    ("chooser_clock_last_obs_s", pa.float64()),
    ("disconnected_clock_last_obs_s", pa.float64()),
    ("clock_gap_chooser_minus_disconnected_s", pa.float64()),
    ("disconnected_clock_positive", pa.int64()),
    ("chooser_raw_win", pa.int64()),
    ("raw_draw", pa.int64()),
    ("last_move_uci", pa.large_string()),
    ("last_move_san", pa.large_string()),
    ("ply_count", pa.int64()),
    ("side_to_move_after_last", pa.large_string()),
    ("fen_after_last_move", pa.large_string()),
    ("tournament_like_event", pa.int64()),
])

API_IDS_SCHEMA = pa.schema([
    ("game_id", pa.large_string()),
    ("archive_month", pa.large_string()),
])

ERROR_SCHEMA = pa.schema([
    ("archive_month", pa.large_string()),
    ("matched_idx", pa.int64()),
    ("error", pa.large_string()),
])


# ----------------------------- Dataclasses ----------------------------------
@dataclass
class MonthJob:
    """A resolved month input job."""
    month: str
    pgn_zst: str
    remote_size: Optional[int]
    local_size: Optional[int]
    ready: bool
    ready_reason: str


@dataclass
class MonthStatus:
    """Final per-month status row for manifests."""
    month: str
    pgn_zst: str
    output_dir: str
    final_ok: bool
    skipped: bool
    skip_reason: str
    scanned_games: int
    matched_timeforfeit_games_seen: int
    matched_timeforfeit_games_written: int
    api_target_rows: int
    api_deferred_rows: int
    parse_failures_on_matched_games: int
    no_move_parse_failures: int
    missing_game_id_rows: int
    started_utc: str
    finished_utc: str
    elapsed_seconds: float
    error: str


# ----------------------------- Small utilities ------------------------------
def now_utc() -> str:
    """Return an ISO-like UTC timestamp for logs and summaries."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def filename_for_month(month: str) -> str:
    """Map YYYY-MM to the public Lichess standard-rated archive filename."""
    return f"lichess_db_standard_rated_{month}.pgn.zst"


def local_pgn_for_month(pgn_dir: Path, month: str) -> Path:
    """Return the expected local raw archive path for a month."""
    return pgn_dir / filename_for_month(month)


def remote_url_for_month(month: str) -> str:
    """Return the public Lichess URL for a month."""
    return f"{BASE_URL}/{filename_for_month(month)}"


def head_remote_size(url: str) -> Tuple[Optional[int], str]:
    """
    Read remote size from HTTP HEAD.

    We use this to avoid processing a month that is still being downloaded.
    If the remote check fails, the script can still proceed if --allow-size-unknown
    is passed, but the default is conservative.
    """
    req = Request(url, method="HEAD", headers={"User-Agent": "lichess-kindness-replication/1.0"})
    try:
        with urlopen(req, timeout=60) as r:
            s = r.headers.get("Content-Length")
            return (int(s) if s and s.isdigit() else None, "")
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        return None, repr(e)


def human_bytes(n: Optional[int]) -> str:
    """Human-readable bytes."""
    if n is None:
        return "NA"
    x = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if x < 1024 or unit == "TB":
            return f"{x:.2f} {unit}"
        x /= 1024
    return str(n)


def write_json_atomic(path: Path, obj: dict) -> None:
    """Atomically write JSON to avoid half-written checkpoint files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, obj: dict) -> None:
    """Append a structured event to a JSONL log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def write_csv(path: Path, rows: List[dict]) -> None:
    """Write a small manifest/status CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_parquet_status(path: Path, rows: List[dict]) -> str:
    """Write small status/manifest Parquet if possible."""
    if not rows:
        return "skipped_empty"
    try:
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, path, compression="zstd")
        return "ok"
    except Exception as e:
        return f"failed: {repr(e)}"


def safe_int(x: object) -> Optional[int]:
    """Parse PGN integer-like headers such as ratings."""
    if x is None:
        return None
    s = str(x).strip().replace("+", "")
    if s == "" or s == "?":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def safe_float(x: object) -> Optional[float]:
    """Parse ratingDiff headers into floats, preserving missing values."""
    if x is None:
        return None
    s = str(x).strip().replace("+", "")
    if s == "" or s == "?":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_time_control(tc: object) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse a Lichess TimeControl string like "180+2".

    Returns:
      base seconds, increment seconds
    """
    if tc is None:
        return None, None
    s = str(tc).strip()
    if s == "" or s == "-":
        return None, None
    if "+" not in s:
        val = safe_float(s)
        return val, None
    base, inc = s.split("+", 1)
    return safe_float(base), safe_float(inc)


def extract_game_id(site: object) -> str:
    """
    Extract the 8-character Lichess game ID from the Site header.

    The fallback handles unusual site strings by taking the last URL component.
    """
    s = "" if site is None else str(site)
    m = SITE_ID_RE.search(s)
    if m:
        return m.group(1)
    s = s.strip().rstrip("/")
    return s.rsplit("/", 1)[-1] if s else ""


def clk_to_seconds(comment: str) -> Optional[float]:
    """Extract a clock comment like [%clk 0:01:23] into seconds."""
    m = CLK_RE.search(comment or "")
    if not m:
        return None
    h, mm, ss = map(int, m.groups())
    return float(3600 * h + 60 * mm + ss)


def infer_archive_month_from_path(pgn_path: Path) -> str:
    """Infer YYYY-MM from a raw PGN filename."""
    m = MONTH_RE.search(pgn_path.name)
    return m.group(1) if m else ""


def reached_limit(value: int, limit: Optional[int]) -> bool:
    """True if an optional cap has been reached."""
    return limit is not None and value >= limit


def is_existing_success(month_dir: Path) -> bool:
    """Check whether a prior completed month output is reusable."""
    success = month_dir / "_SUCCESS.json"
    parquet = month_dir / "timeforfeit_candidates.parquet"
    api_ids = month_dir / "api_target_game_ids.parquet"
    if not success.exists() or not parquet.exists() or not api_ids.exists():
        return False
    try:
        obj = json.loads(success.read_text())
        return obj.get("final_ok") is True
    except Exception:
        return False


# ----------------------------- Parquet writer -------------------------------
class LazyParquetWriter:
    """
    Lazily open a ParquetWriter on the first non-empty batch.

    This avoids creating a writer before we know whether a month has any rows.
    If a month has zero rows, close_empty() writes an empty Parquet file with the
    correct schema.
    """

    def __init__(self, path: Path, schema: pa.Schema):
        self.path = path
        self.schema = schema
        self.writer: Optional[pq.ParquetWriter] = None
        self.rows_written = 0

    def write_pylist(self, rows: List[dict]) -> None:
        """Write a list of dictionaries as one Parquet row group."""
        if not rows:
            return
        table = pa.Table.from_pylist(rows, schema=self.schema)
        if self.writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.writer = pq.ParquetWriter(self.path, self.schema, compression="zstd")
        self.writer.write_table(table)
        self.rows_written += len(rows)

    def close(self) -> None:
        """Close writer, or create an empty Parquet file if no rows were written."""
        if self.writer is not None:
            self.writer.close()
        elif not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            empty = pa.Table.from_pylist([], schema=self.schema)
            pq.write_table(empty, self.path, compression="zstd")


# ------------------------- PGN parsing worker logic --------------------------
def analyze_game_text(game_text: str, archive_month: str) -> dict:
    """
    Parse one matched PGN block and return a structured candidate row.

    The behavioral interpretation follows the project convention:
      - last mover is the connected chooser;
      - side to move after the final observed move is the likely disconnected player.
    """
    game = chess.pgn.read_game(io.StringIO(game_text))
    if game is None:
        raise ValueError("python-chess could not parse matched PGN block")

    headers = game.headers
    board = game.board()
    node = game

    white_clock_s: Optional[float] = None
    black_clock_s: Optional[float] = None
    last_mover_color: Optional[str] = None
    last_move_uci = ""
    last_move_san = ""
    ply_count = 0

    # Walk the mainline. Lichess PGNs put clock comments on moves, so we update
    # the last observed clock for the side that just moved.
    while node.variations:
        child = node.variation(0)

        mover_color = "white" if board.turn == chess.WHITE else "black"

        try:
            move_san = board.san(child.move)
        except Exception:
            move_san = ""

        board.push(child.move)

        clk = clk_to_seconds(child.comment or "")
        if clk is not None:
            if mover_color == "white":
                white_clock_s = clk
            else:
                black_clock_s = clk

        last_mover_color = mover_color
        last_move_uci = child.move.uci()
        last_move_san = move_san
        ply_count += 1
        node = child

    if last_mover_color is None:
        raise ValueError("Matched game has no moves")

    chooser_color = last_mover_color
    disconnected_color = "black" if chooser_color == "white" else "white"

    white_name = headers.get("White", "")
    black_name = headers.get("Black", "")

    white_elo = safe_int(headers.get("WhiteElo", ""))
    black_elo = safe_int(headers.get("BlackElo", ""))

    chooser_name = white_name if chooser_color == "white" else black_name
    disconnected_name = black_name if chooser_color == "white" else white_name

    chooser_elo = white_elo if chooser_color == "white" else black_elo
    disconnected_elo = black_elo if chooser_color == "white" else white_elo

    chooser_clock_s = white_clock_s if chooser_color == "white" else black_clock_s
    disconnected_clock_s = black_clock_s if chooser_color == "white" else white_clock_s

    result = headers.get("Result", "")

    chooser_raw_win = int(
        (chooser_color == "white" and result == "1-0")
        or (chooser_color == "black" and result == "0-1")
    )
    raw_draw = int(result == "1/2-1/2")

    event = headers.get("Event", "")
    time_control = headers.get("TimeControl", "")
    tc_base_s, tc_inc_s = parse_time_control(time_control)

    return {
        "archive_month": archive_month,
        "game_id": extract_game_id(headers.get("Site", "")),
        "site": headers.get("Site", ""),
        "event": event,
        "utc_date": headers.get("UTCDate", ""),
        "utc_time": headers.get("UTCTime", ""),
        "white": white_name,
        "black": black_name,
        "white_elo": white_elo,
        "black_elo": black_elo,
        "white_rating_diff": safe_float(headers.get("WhiteRatingDiff", "")),
        "black_rating_diff": safe_float(headers.get("BlackRatingDiff", "")),
        "result": result,
        "termination": headers.get("Termination", ""),
        "time_control": time_control,
        "tc_base_s": tc_base_s,
        "tc_inc_s": tc_inc_s,
        "last_mover_color": last_mover_color,
        "candidate_chooser": chooser_name,
        "candidate_chooser_color": chooser_color,
        "candidate_chooser_elo": chooser_elo,
        "likely_disconnected_player": disconnected_name,
        "likely_disconnected_color": disconnected_color,
        "likely_disconnected_elo": disconnected_elo,
        "white_clock_last_obs_s": white_clock_s,
        "black_clock_last_obs_s": black_clock_s,
        "chooser_clock_last_obs_s": chooser_clock_s,
        "disconnected_clock_last_obs_s": disconnected_clock_s,
        "clock_gap_chooser_minus_disconnected_s": (
            chooser_clock_s - disconnected_clock_s
            if chooser_clock_s is not None and disconnected_clock_s is not None
            else None
        ),
        "disconnected_clock_positive": int(
            disconnected_clock_s is not None and disconnected_clock_s > 0
        ),
        "chooser_raw_win": chooser_raw_win,
        "raw_draw": raw_draw,
        "last_move_uci": last_move_uci,
        "last_move_san": last_move_san,
        "ply_count": ply_count,
        "side_to_move_after_last": "white" if board.turn == chess.WHITE else "black",
        "fen_after_last_move": board.fen(),
        "tournament_like_event": int("tournament" in event.lower()),
    }


def process_batch(batch: List[Tuple[int, str]], archive_month: str) -> dict:
    """
    Worker function for a batch of matched PGN blocks.

    Returning rows in batches avoids sending one task per game, which would be
    far too much process-pool overhead.
    """
    rows: List[dict] = []
    errors: List[dict] = []
    result_counts: Dict[str, int] = {}
    tc_counts: Dict[str, int] = {}
    parse_failures = 0
    no_move_parse_failures = 0

    for matched_idx, game_text in batch:
        try:
            row = analyze_game_text(game_text, archive_month)
            rows.append(row)
            result_counts[row["result"]] = result_counts.get(row["result"], 0) + 1
            tc_counts[row["time_control"]] = tc_counts.get(row["time_control"], 0) + 1
        except Exception as e:
            parse_failures += 1
            if "no moves" in str(e).lower():
                no_move_parse_failures += 1
            errors.append({
                "archive_month": archive_month,
                "matched_idx": matched_idx,
                "error": str(e),
            })

    return {
        "rows": rows,
        "errors": errors,
        "result_counts": result_counts,
        "tc_counts": tc_counts,
        "parse_failures": parse_failures,
        "no_move_parse_failures": no_move_parse_failures,
    }


# ----------------------------- Clock splitting ------------------------------
def is_api_target_row(row: dict, min_seconds: float, drop_missing_clock: bool) -> bool:
    """
    Decide whether a PGN candidate should go to API enrichment.

    Paper rule:
      - keep finite disconnected clock >= 5 seconds;
      - also keep missing/malformed clock rows by default;
      - finite disconnected clock < 5 seconds is deferred.
    """
    raw = row.get("disconnected_clock_last_obs_s")
    if raw is None:
        return not drop_missing_clock
    try:
        val = float(raw)
    except Exception:
        return not drop_missing_clock
    return val >= min_seconds


def api_id_row(row: dict) -> Optional[dict]:
    """Minimal row for API enrichment."""
    gid = (row.get("game_id") or "").strip()
    if not gid:
        return None
    return {"game_id": gid, "archive_month": row.get("archive_month")}


# ---------------------------- Month extraction ------------------------------
def extract_one_month(
    job: MonthJob,
    out_root: Path,
    run_root: Path,
    parse_workers: int,
    batch_size: int,
    max_inflight_batches: Optional[int],
    progress_every_games: int,
    min_disconnected_clock_seconds: float,
    drop_missing_clock: bool,
    max_games: Optional[int],
    max_matches: Optional[int],
    force: bool,
) -> MonthStatus:
    """
    Extract one month from raw PGN to Parquet.

    This function is the checkpoint unit. If it completes, it writes _SUCCESS.json.
    """
    started = now_utc()
    t0 = time.time()

    final_month_dir = out_root / f"month={job.month}"
    tmp_month_dir = out_root / f"month={job.month}.tmp_{os.getpid()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Skip if prior output is complete and force is not requested.
    if is_existing_success(final_month_dir) and not force:
        success = json.loads((final_month_dir / "_SUCCESS.json").read_text())
        return MonthStatus(
            month=job.month,
            pgn_zst=job.pgn_zst,
            output_dir=str(final_month_dir),
            final_ok=True,
            skipped=True,
            skip_reason="existing_success_checkpoint",
            scanned_games=int(success.get("scanned_games", 0)),
            matched_timeforfeit_games_seen=int(success.get("matched_timeforfeit_games_seen", 0)),
            matched_timeforfeit_games_written=int(success.get("matched_timeforfeit_games_written", 0)),
            api_target_rows=int(success.get("api_target_rows", 0)),
            api_deferred_rows=int(success.get("api_deferred_rows", 0)),
            parse_failures_on_matched_games=int(success.get("parse_failures_on_matched_games", 0)),
            no_move_parse_failures=int(success.get("no_move_parse_failures", 0)),
            missing_game_id_rows=int(success.get("missing_game_id_rows", 0)),
            started_utc=started,
            finished_utc=now_utc(),
            elapsed_seconds=round(time.time() - t0, 3),
            error="",
        )

    # If force is requested, move the existing final folder aside rather than
    # deleting it immediately. This is safer for large outputs.
    if final_month_dir.exists() and force:
        backup = out_root / f"month={job.month}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        final_month_dir.rename(backup)

    tmp_month_dir.mkdir(parents=True, exist_ok=False)
    progress_path = tmp_month_dir / "progress.jsonl"

    append_jsonl(progress_path, {
        "event": "month_start",
        "month": job.month,
        "utc": now_utc(),
        "pgn_zst": job.pgn_zst,
        "parse_workers": parse_workers,
        "batch_size": batch_size,
    })

    # Parquet outputs.
    all_path = tmp_month_dir / "timeforfeit_candidates.parquet"
    target_path = tmp_month_dir / "api_target_candidates_ge5s_or_missing.parquet"
    deferred_path = tmp_month_dir / "api_deferred_candidates_lt5s.parquet"
    api_ids_path = tmp_month_dir / "api_target_game_ids.parquet"
    errors_path = tmp_month_dir / "parse_errors.parquet"

    all_writer = LazyParquetWriter(all_path, CANDIDATE_SCHEMA)
    target_writer = LazyParquetWriter(target_path, CANDIDATE_SCHEMA)
    deferred_writer = LazyParquetWriter(deferred_path, CANDIDATE_SCHEMA)
    api_ids_writer = LazyParquetWriter(api_ids_path, API_IDS_SCHEMA)
    errors_writer = LazyParquetWriter(errors_path, ERROR_SCHEMA)

    scanned_games = 0
    matched_seen = 0
    matched_written = 0
    api_target_rows = 0
    api_deferred_rows = 0
    missing_game_id_rows = 0
    parse_failures = 0
    no_move_parse_failures = 0
    result_counts: Dict[str, int] = {}
    tc_counts: Dict[str, int] = {}
    stop_reason = "eof"

    parse_workers = max(1, parse_workers)
    batch_size = max(1, batch_size)
    max_inflight = max_inflight_batches or max(4, 4 * parse_workers)

    pending_batch: List[Tuple[int, str]] = []
    inflight = deque()

    def merge_counts(dst: Dict[str, int], src: Dict[str, int]) -> None:
        for k, v in src.items():
            dst[k] = dst.get(k, 0) + int(v)

    def write_result_batch(res: dict) -> None:
        """
        Write one completed worker-batch result to all relevant Parquet outputs.
        """
        nonlocal matched_written, parse_failures, no_move_parse_failures
        nonlocal api_target_rows, api_deferred_rows, missing_game_id_rows

        rows = res["rows"]
        errors = res["errors"]

        if rows:
            all_writer.write_pylist(rows)
            matched_written += len(rows)

            target_rows = []
            deferred_rows = []
            api_id_rows = []

            for row in rows:
                gid = (row.get("game_id") or "").strip()
                if not gid:
                    missing_game_id_rows += 1

                if is_api_target_row(row, min_disconnected_clock_seconds, drop_missing_clock):
                    target_rows.append(row)
                    minimal = api_id_row(row)
                    if minimal is not None:
                        api_id_rows.append(minimal)
                else:
                    deferred_rows.append(row)

            if target_rows:
                target_writer.write_pylist(target_rows)
                api_target_rows += len(target_rows)

            if deferred_rows:
                deferred_writer.write_pylist(deferred_rows)
                api_deferred_rows += len(deferred_rows)

            if api_id_rows:
                api_ids_writer.write_pylist(api_id_rows)

        if errors:
            errors_writer.write_pylist(errors)

        parse_failures += int(res["parse_failures"])
        no_move_parse_failures += int(res["no_move_parse_failures"])
        merge_counts(result_counts, res["result_counts"])
        merge_counts(tc_counts, res["tc_counts"])

    def submit_batch(executor: ProcessPoolExecutor) -> None:
        """
        Submit pending matched games to the worker pool.
        """
        nonlocal pending_batch
        if not pending_batch:
            return
        fut = executor.submit(process_batch, pending_batch, job.month)
        inflight.append(fut)
        pending_batch = []

    def drain_some(force: bool = False) -> None:
        """
        Drain completed worker futures.

        If force=False, drain only when the queue is too large.
        If force=True, drain everything.
        """
        while inflight and (force or len(inflight) >= max_inflight):
            done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
            for fut in list(done):
                inflight.remove(fut)
                write_result_batch(fut.result())
            if not force:
                break

    try:
        dctx = zstandard.ZstdDecompressor()

        with ProcessPoolExecutor(max_workers=parse_workers) as executor:
            with Path(job.pgn_zst).open("rb") as fh:
                reader = dctx.stream_reader(fh)
                text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")

                buffer: List[str] = []
                is_timeforfeit = False
                stop = False

                def flush_buffer() -> None:
                    """
                    Finish one PGN game block.

                    We count every game, and if the block was marked Time forfeit,
                    we queue it for worker parsing.
                    """
                    nonlocal buffer, is_timeforfeit, scanned_games, matched_seen, stop, stop_reason
                    if not buffer:
                        return

                    scanned_games += 1

                    if progress_every_games and scanned_games % progress_every_games == 0:
                        event = {
                            "event": "progress",
                            "month": job.month,
                            "utc": now_utc(),
                            "scanned_games": scanned_games,
                            "matched_seen": matched_seen,
                            "matched_written": matched_written,
                            "api_target_rows": api_target_rows,
                            "api_deferred_rows": api_deferred_rows,
                            "parse_failures": parse_failures,
                            "inflight_batches": len(inflight),
                        }
                        append_jsonl(progress_path, event)
                        print(json.dumps(event), flush=True)

                    if is_timeforfeit:
                        matched_seen += 1
                        pending_batch.append((matched_seen, "".join(buffer)))

                        if len(pending_batch) >= batch_size:
                            submit_batch(executor)
                            drain_some(force=False)

                    if reached_limit(scanned_games, max_games):
                        stop = True
                        stop_reason = "max_games"

                    if reached_limit(matched_seen, max_matches):
                        stop = True
                        stop_reason = "max_matches"

                    buffer = []
                    is_timeforfeit = False

                # Stream the PGN file. A new game starts at [Event ...].
                for line in text:
                    if line.startswith(EVENT_START):
                        flush_buffer()
                        if stop:
                            break
                        buffer = [line]
                        is_timeforfeit = False
                    else:
                        if buffer:
                            buffer.append(line)
                            if line.startswith(TERM_LINE):
                                is_timeforfeit = True

                if not stop:
                    flush_buffer()

            # Submit and drain any remaining matched games.
            if pending_batch:
                submit_batch(executor)

            drain_some(force=True)
            while inflight:
                done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
                for fut in list(done):
                    inflight.remove(fut)
                    write_result_batch(fut.result())

        # Close or create all Parquet outputs.
        all_writer.close()
        target_writer.close()
        deferred_writer.close()
        api_ids_writer.close()
        errors_writer.close()

        elapsed = round(time.time() - t0, 3)

        summary = {
            "final_ok": True,
            "month": job.month,
            "pgn_zst": job.pgn_zst,
            "remote_size": job.remote_size,
            "local_size": job.local_size,
            "parse_workers": parse_workers,
            "batch_size": batch_size,
            "max_inflight_batches": max_inflight,
            "max_games": max_games,
            "max_matches": max_matches,
            "stop_reason": stop_reason,
            "scanned_games": scanned_games,
            "matched_timeforfeit_games_seen": matched_seen,
            "matched_timeforfeit_games_written": matched_written,
            "api_target_rows": api_target_rows,
            "api_deferred_rows": api_deferred_rows,
            "parse_failures_on_matched_games": parse_failures,
            "no_move_parse_failures": no_move_parse_failures,
            "missing_game_id_rows": missing_game_id_rows,
            "result_counts_within_matched_games": result_counts,
            "time_control_counts_within_matched_games": tc_counts,
            "min_disconnected_clock_seconds": min_disconnected_clock_seconds,
            "drop_missing_clock": drop_missing_clock,
            "timeforfeit_candidates_parquet": str(all_path),
            "api_target_candidates_parquet": str(target_path),
            "api_deferred_candidates_parquet": str(deferred_path),
            "api_target_game_ids_parquet": str(api_ids_path),
            "parse_errors_parquet": str(errors_path),
            "started_utc": started,
            "finished_utc": now_utc(),
            "elapsed_seconds": elapsed,
        }

        write_json_atomic(tmp_month_dir / "timeforfeit_summary.json", summary)
        write_json_atomic(tmp_month_dir / "_SUCCESS.json", summary)

        # Rename temp folder into final month folder atomically-ish.
        tmp_month_dir.rename(final_month_dir)

        return MonthStatus(
            month=job.month,
            pgn_zst=job.pgn_zst,
            output_dir=str(final_month_dir),
            final_ok=True,
            skipped=False,
            skip_reason="",
            scanned_games=scanned_games,
            matched_timeforfeit_games_seen=matched_seen,
            matched_timeforfeit_games_written=matched_written,
            api_target_rows=api_target_rows,
            api_deferred_rows=api_deferred_rows,
            parse_failures_on_matched_games=parse_failures,
            no_move_parse_failures=no_move_parse_failures,
            missing_game_id_rows=missing_game_id_rows,
            started_utc=started,
            finished_utc=summary["finished_utc"],
            elapsed_seconds=elapsed,
            error="",
        )

    except Exception as e:
        # Preserve partial temp output for debugging rather than deleting it.
        elapsed = round(time.time() - t0, 3)
        err = repr(e)
        append_jsonl(progress_path, {
            "event": "month_failed",
            "month": job.month,
            "utc": now_utc(),
            "error": err,
        })

        return MonthStatus(
            month=job.month,
            pgn_zst=job.pgn_zst,
            output_dir=str(tmp_month_dir),
            final_ok=False,
            skipped=False,
            skip_reason="",
            scanned_games=scanned_games,
            matched_timeforfeit_games_seen=matched_seen,
            matched_timeforfeit_games_written=matched_written,
            api_target_rows=api_target_rows,
            api_deferred_rows=api_deferred_rows,
            parse_failures_on_matched_games=parse_failures,
            no_move_parse_failures=no_move_parse_failures,
            missing_game_id_rows=missing_game_id_rows,
            started_utc=started,
            finished_utc=now_utc(),
            elapsed_seconds=elapsed,
            error=err,
        )


# ------------------------------- Job planning -------------------------------
def resolve_month_jobs(
    months: List[str],
    pgn_dir: Path,
    require_complete_size: bool,
    allow_size_unknown: bool,
) -> List[MonthJob]:
    """
    Resolve monthly raw files and determine whether each is ready to process.

    By default, a month is ready only if:
      - the local .pgn.zst exists;
      - remote size is known;
      - local size equals remote size.

    This protects against accidentally extracting from an in-progress download.
    """
    jobs: List[MonthJob] = []

    for month in months:
        pgn = local_pgn_for_month(pgn_dir, month)
        local_size = pgn.stat().st_size if pgn.exists() else None
        remote_size, head_error = head_remote_size(remote_url_for_month(month))

        if not pgn.exists():
            ready = False
            reason = "missing_local_pgn"
        elif require_complete_size:
            if remote_size is None and not allow_size_unknown:
                ready = False
                reason = f"remote_size_unknown:{head_error}"
            elif remote_size is not None and local_size != remote_size:
                ready = False
                reason = f"local_size_mismatch_local={local_size}_remote={remote_size}"
            else:
                ready = True
                reason = "local_file_ready"
        else:
            ready = True
            reason = "local_file_exists_size_check_disabled"

        jobs.append(MonthJob(
            month=month,
            pgn_zst=str(pgn),
            remote_size=remote_size,
            local_size=local_size,
            ready=ready,
            ready_reason=reason,
        ))

    return jobs


# ------------------------------ CLI / main ----------------------------------
def parse_args() -> argparse.Namespace:
    """Command-line interface."""
    p = argparse.ArgumentParser()

    p.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    p.add_argument("--pgn-dir", type=Path, default=RAW_DIR)
    p.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    p.add_argument("--run-log-root", type=Path, default=RUN_LOG_ROOT)

    p.add_argument(
        "--months",
        default="",
        help="Comma-separated YYYY-MM list. Default: expansion target months.",
    )

    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually run extraction. Without this, the script only does a dry run.",
    )

    p.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if a month has an existing _SUCCESS.json checkpoint.",
    )

    p.add_argument(
        "--require-complete-size",
        action="store_true",
        default=True,
        help="Require local raw file size to equal remote size before processing.",
    )

    p.add_argument(
        "--allow-size-unknown",
        action="store_true",
        help="Allow processing if remote size cannot be checked.",
    )

    p.add_argument(
        "--month-workers",
        type=int,
        default=1,
        help="Number of months to process concurrently. Default 1.",
    )

    p.add_argument(
        "--parse-workers",
        type=int,
        default=6,
        help="Worker processes inside each month for matched PGN parsing.",
    )

    p.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Matched Time-forfeit PGN blocks per worker task.",
    )

    p.add_argument(
        "--max-inflight-batches",
        type=int,
        default=None,
        help="Max queued worker batches per month. Default 4 * parse-workers.",
    )

    p.add_argument(
        "--progress-every-games",
        type=int,
        default=1_000_000,
        help="Write/print progress every N scanned games.",
    )

    p.add_argument(
        "--min-disconnected-clock-seconds",
        type=float,
        default=5.0,
        help="Clock threshold for API-targeted candidate pool.",
    )

    p.add_argument(
        "--drop-missing-clock",
        action="store_true",
        help="Drop missing clock rows from API-targeted pool instead of keeping them.",
    )

    p.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="Pilot cap on total games scanned per month.",
    )

    p.add_argument(
        "--max-matches",
        type=int,
        default=None,
        help="Pilot cap on matched Time-forfeit games per month.",
    )

    return p.parse_args()


def main() -> int:
    """Top-level orchestration for Stage 01."""
    args = parse_args()

    months = [m.strip() for m in args.months.split(",") if m.strip()] if args.months.strip() else DEFAULT_MONTHS

    args.out_root.mkdir(parents=True, exist_ok=True)
    args.run_log_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = args.run_log_root / f"extract_pgn_candidates_{stamp}"
    run_root.mkdir(parents=True, exist_ok=False)

    manifests_dir = args.out_root / "_manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    command = " ".join(sys.argv)
    (run_root / "command.txt").write_text(command + "\n", encoding="utf-8")

    # Plan jobs and write the job manifest before doing anything heavy.
    jobs = resolve_month_jobs(
        months=months,
        pgn_dir=args.pgn_dir,
        require_complete_size=args.require_complete_size,
        allow_size_unknown=args.allow_size_unknown,
    )

    job_rows = [asdict(j) for j in jobs]
    write_csv(run_root / "job_manifest.csv", job_rows)
    write_parquet_status(run_root / "job_manifest.parquet", job_rows)

    ready_jobs = [j for j in jobs if j.ready]
    not_ready_jobs = [j for j in jobs if not j.ready]

    pre_summary = {
        "started_utc": now_utc(),
        "execute": bool(args.execute),
        "months_requested": months,
        "n_months_requested": len(months),
        "n_ready": len(ready_jobs),
        "n_not_ready": len(not_ready_jobs),
        "ready_months": [j.month for j in ready_jobs],
        "not_ready": {j.month: j.ready_reason for j in not_ready_jobs},
        "out_root": str(args.out_root),
        "run_root": str(run_root),
        "pgn_dir": str(args.pgn_dir),
        "month_workers": args.month_workers,
        "parse_workers": args.parse_workers,
        "batch_size": args.batch_size,
        "max_games": args.max_games,
        "max_matches": args.max_matches,
    }
    write_json_atomic(run_root / "summary_pre.json", pre_summary)
    print(json.dumps(pre_summary, indent=2, sort_keys=True))

    if not args.execute:
        write_json_atomic(run_root / "summary.json", {**pre_summary, "status": "dry_run_ok"})
        print(f"\nDRY_RUN_ONLY. Add --execute to run extraction.")
        print(f"RUN_ROOT={run_root}")
        return 0

    if not ready_jobs:
        write_json_atomic(run_root / "summary.json", {**pre_summary, "status": "no_ready_months"})
        print("\nNo ready months to process.")
        return 0

    # Guard against accidental oversubscription.
    total_worker_budget = max(1, args.month_workers) * max(1, args.parse_workers)
    if total_worker_budget > max(1, (os.cpu_count() or 1)):
        print(
            f"WARNING: month_workers * parse_workers = {total_worker_budget}, "
            f"but os.cpu_count() = {os.cpu_count()}. This may oversubscribe the machine.",
            flush=True,
        )

    statuses: List[MonthStatus] = []

    # Month-level parallelism. Default is 1 month at a time. If using multiple
    # month workers, reduce parse-workers accordingly.
    with ProcessPoolExecutor(max_workers=max(1, args.month_workers)) as executor:
        futures = {
            executor.submit(
                extract_one_month,
                job,
                args.out_root,
                run_root,
                args.parse_workers,
                args.batch_size,
                args.max_inflight_batches,
                args.progress_every_games,
                args.min_disconnected_clock_seconds,
                args.drop_missing_clock,
                args.max_games,
                args.max_matches,
                args.force,
            ): job.month
            for job in ready_jobs
        }

        for fut in futures:
            month = futures[fut]
            try:
                status = fut.result()
            except Exception as e:
                status = MonthStatus(
                    month=month,
                    pgn_zst="",
                    output_dir="",
                    final_ok=False,
                    skipped=False,
                    skip_reason="",
                    scanned_games=0,
                    matched_timeforfeit_games_seen=0,
                    matched_timeforfeit_games_written=0,
                    api_target_rows=0,
                    api_deferred_rows=0,
                    parse_failures_on_matched_games=0,
                    no_move_parse_failures=0,
                    missing_game_id_rows=0,
                    started_utc="",
                    finished_utc=now_utc(),
                    elapsed_seconds=0.0,
                    error=repr(e),
                )

            statuses.append(status)
            status_rows = [asdict(s) for s in sorted(statuses, key=lambda x: x.month)]
            write_csv(run_root / "month_status.csv", status_rows)
            write_parquet_status(run_root / "month_status.parquet", status_rows)

            print(
                f"MONTH STATUS {status.month}: final_ok={status.final_ok}, "
                f"skipped={status.skipped}, scanned={status.scanned_games:,}, "
                f"matched={status.matched_timeforfeit_games_written:,}, "
                f"api_target={status.api_target_rows:,}, error={status.error or 'none'}",
                flush=True,
            )

    # Build downstream path lists from successful month outputs.
    successful = [s for s in statuses if s.final_ok]
    candidate_paths = [
        str(Path(s.output_dir) / "timeforfeit_candidates.parquet")
        for s in sorted(successful, key=lambda x: x.month)
    ]
    api_id_paths = [
        str(Path(s.output_dir) / "api_target_game_ids.parquet")
        for s in sorted(successful, key=lambda x: x.month)
    ]

    (manifests_dir / "timeforfeit_candidate_paths.txt").write_text(
        "\n".join(candidate_paths) + ("\n" if candidate_paths else ""),
        encoding="utf-8",
    )
    (manifests_dir / "api_target_game_id_paths.txt").write_text(
        "\n".join(api_id_paths) + ("\n" if api_id_paths else ""),
        encoding="utf-8",
    )

    # Also copy current run status to stable manifest location.
    status_rows = [asdict(s) for s in sorted(statuses, key=lambda x: x.month)]
    write_csv(manifests_dir / "month_status.csv", status_rows)
    write_parquet_status(manifests_dir / "month_status.parquet", status_rows)

    failed = [s.month for s in statuses if not s.final_ok]
    summary = {
        **pre_summary,
        "finished_utc": now_utc(),
        "status": "ok" if not failed else "partial_or_failed",
        "n_processed_or_skipped": len(statuses),
        "n_successful": len(successful),
        "n_failed": len(failed),
        "failed_months": failed,
        "candidate_paths_file": str(manifests_dir / "timeforfeit_candidate_paths.txt"),
        "api_target_game_id_paths_file": str(manifests_dir / "api_target_game_id_paths.txt"),
        "stable_month_status_csv": str(manifests_dir / "month_status.csv"),
    }
    write_json_atomic(run_root / "summary.json", summary)
    write_json_atomic(manifests_dir / "summary.json", summary)

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
