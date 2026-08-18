#!/usr/bin/env python3
"""Build and freeze the true 24-month timeout-opportunity panel.

Scientific contract
===================

The locked paper window is the 24 complete UTC months from 2023-11 through
2025-10.  Stage 04 has already classified and globally deduplicated every API
target in that window.  Its immutable timeout-only population contains exactly
47,587,020 games.  This program joins those frozen IDs to authenticated PGN
candidate records and constructs the behavioral opportunity layer used by all
later cost, fairness, and paper-analysis stages.

The locked definitions are:

* opportunity: API status is exactly ``timeout`` (never ``outoftime``);
* chooser: the last mover, i.e. the connected player who could claim the win;
* disconnected player: the side to move after the last observed move;
* clock rule: disconnected clock is at least five seconds, or is missing;
* kind draw: final draw while the chooser retained mating material.

The output is deliberately behavioral.  It contains identifiers, PGN roles and
clocks, API outcome evidence, final-board material, and the kind-draw outcome.
It does not attach Glicko-2 cost or Stockfish fairness; those remain separate
downstream stages with their own provenance.

Input lineages
==============

Three already-audited PGN/candidate lineages are required:

1. 2023-11--2024-09: the historical monthly outcome/material Parquets.  These
   contain the original PGN candidate fields and the historical chooser
   mating-material flag.  They do not retain the intermediate piece counts or
   material-point totals.  Stage 05 recomputes those fields from final FEN and
   requires exact agreement with the retained historical flag before it
   accepts any earlier month.
2. 2024-10--2025-07: canonical Stage 01
   ``api_target_candidates_ge5s_or_missing.parquet`` files.
3. 2025-08--2025-10: the three authenticated legacy candidate CSVs used by
   adapter 04b.  Their SHA-256 values are locked below.

API evidence is read from the same authenticated lineage that Stage 04 used:
the curated monthly lookup Parquets for the earlier block, native Stage 04
response units for the bridge block, and 04b-normalized response Parquets for
the late block.  Earlier PGN/material and API evidence intentionally remain
separate inputs and are joined by exact game ID.  The narrow Stage 04
reconciler remains the population authority.

The native bridge response units contain one known adapter defect that does
not affect Stage 04 population membership: their stored ``is_draw`` field was
derived from terminal-status labels, so a ``status=timeout`` row was marked
non-draw even when ``winner`` was absent.  For bridge rows Stage 05 therefore
derives outcome from the authoritative winner field: absent winner means draw,
while ``white`` or ``black`` means decisive.  The number of disagreements with
the stored bridge flag is counted in every preflight and manifest; source bytes
are never changed.

Player-role authority remains with the archived PGN candidate fields.  API
player names are retained as descriptive source metadata and their normalized
agreement with PGN names is counted in every monthly manifest.  Those counts
are diagnostics rather than fatal scientific gates: roles are never assigned
from API names, and API evidence is already bound to the PGN record by unique
game ID, exact Stage 04 set equality, status, and color-coded result.  The
authoritative PGN chooser/disconnected names must still agree exactly with the
PGN White/Black fields.

Mating-material rule
====================

Material is counted from the board portion of ``fen_after_last_move``.  The
locked historical mating-capacity rule counts any pawn, rook, or queen; two or
more bishops; a bishop plus a knight; or two or more knights.  Two knights
cannot force mate against a bare king, but a legal mating position is possible,
so they are not classified as insufficient material here.  The rule excludes
king only, king plus one bishop, and king plus one knight.  For every earlier
row the recomputed flag must exactly reproduce the retained flag in the locked
historical outcome/material layer.  Piece counts and point totals are newly and
deterministically derived from FEN because the historical monthly files did not
retain those intermediate fields.  This is a production equivalence gate, not
an assumption silently applied to new months.

Safety, restartability, and auditability
========================================

* Default invocation is a write-free plan.  ``--execute`` is mandatory.
* No HTTP or Lichess API request exists anywhere in this program.
* Source artifacts are opened read-only, SHA-256 fingerprinted, and never
  modified.
* Each month is built in an isolated partial directory, validated, and then
  atomically renamed into place.
* A completed month is reused only when its output and full input source-set
  hashes still match.  An untrusted existing month fails closed.
* Interrupted partial directories are moved to ``_stale``; they are not
  silently deleted.
* Every published month must be an exact one-to-one realization of that
  month's frozen Stage 04 timeout IDs.
* The global success marker is written only after all 24 months and the exact
  47,587,020-row total pass.

Fresh-Terminal example
======================

    ROOT="/Volumes/XT_Pro/lichess_kindness"
    LEGACY_ROOT="/Users/u6025368/projects/lichess_kindness"
    source "$ROOT/venv/bin/activate"
    export PYTHONDONTWRITEBYTECODE=1
    export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
    "$ROOT/venv/bin/python" -B \
      "$ROOT/replication_package/code/05_build_timeout_opportunity_panel.py" \
      --project-root "$ROOT" \
      --legacy-root "$LEGACY_ROOT" \
      --execute

Expected runtime is normally 30--90 minutes and can approach two hours on a
slow external filesystem.  Source hashing, CSV scans, exact keyed joins,
Parquet compression, and output hashing are included.  Allow roughly 20--50 GB
of temporary free space.  DuckDB memory is bounded by ``--memory-limit``
(default: 8GB).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shlex
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCRIPT_VERSION = "1.0.5"
LOCKED_SAMPLE_START = "2023-11-01"
LOCKED_SAMPLE_END = "2025-10-31"

LOCKED_MONTHS = (
    "2023-11",
    "2023-12",
    "2024-01",
    "2024-02",
    "2024-03",
    "2024-04",
    "2024-05",
    "2024-06",
    "2024-07",
    "2024-08",
    "2024-09",
    "2024-10",
    "2024-11",
    "2024-12",
    "2025-01",
    "2025-02",
    "2025-03",
    "2025-04",
    "2025-05",
    "2025-06",
    "2025-07",
    "2025-08",
    "2025-09",
    "2025-10",
)

EARLIER_MONTHS = LOCKED_MONTHS[:11]
BRIDGE_MONTHS = LOCKED_MONTHS[11:21]
LATE_MONTHS = LOCKED_MONTHS[21:]

EXPECTED_TOTAL_TIMEOUT = 47_587_020
EXPECTED_BLOCK_TIMEOUTS: Mapping[str, int] = {
    "earlier": 21_600_308,
    "bridge": 20_175_915,
    "late": 5_810_797,
}

# Earlier and late counts are independent locked historical anchors.  Bridge
# month counts are authenticated at runtime from the frozen Stage 04 summary;
# their ten-month total must equal the locked bridge total above.
LOCKED_TIMEOUT_BY_MONTH: Mapping[str, int] = {
    "2023-11": 2_015_809,
    "2023-12": 2_101_110,
    "2024-01": 2_049_292,
    "2024-02": 1_931_143,
    "2024-03": 2_021_798,
    "2024-04": 1_917_136,
    "2024-05": 2_011_399,
    "2024-06": 1_903_139,
    "2024-07": 1_893_461,
    "2024-08": 1_923_975,
    "2024-09": 1_832_046,
    "2025-08": 1_930_170,
    "2025-09": 1_881_564,
    "2025-10": 1_999_063,
}

LOCKED_TARGET_BY_MONTH: Mapping[str, int] = {
    "2023-11": 7_183_319,
    "2023-12": 7_448_160,
    "2024-01": 7_450_435,
    "2024-02": 7_012_824,
    "2024-03": 7_333_233,
    "2024-04": 7_015_289,
    "2024-05": 7_304_894,
    "2024-06": 6_913_168,
    "2024-07": 6_958_044,
    "2024-08": 7_096_917,
    "2024-09": 6_796_664,
    "2024-10": 7_280_463,
    "2024-11": 6_920_848,
    "2024-12": 7_327_917,
    "2025-01": 7_499_540,
    "2025-02": 6_780_461,
    "2025-03": 7_371_390,
    "2025-04": 7_007_508,
    "2025-05": 7_209_483,
    "2025-06": 6_937_046,
    "2025-07": 7_111_923,
    "2025-08": 6_961_261,
    "2025-09": 6_698_493,
    "2025-10": 7_029_411,
}

BRIDGE_UNIT_COUNTS: Mapping[str, int] = {
    "2024-10": 243,
    "2024-11": 231,
    "2024-12": 245,
    "2025-01": 250,
    "2025-02": 227,
    "2025-03": 246,
    "2025-04": 234,
    "2025-05": 241,
    "2025-06": 232,
    "2025-07": 238,
}

STAGE04_RECONCILER_RELATIVE_PATH = Path(
    "replication_package/code/04c_reconcile_stage04_24m.py"
)
STAGE04_RECONCILER_SHA256 = (
    "1631392dffa4dd13abd5a81a0769b20b294c9a2e75d17baec2a7e8082662e82a"
)

STAGE04_FROZEN_RELATIVE_ROOT = Path(
    "derived/replication/api_timeout_enrichment_24m_reconciled"
)
STAGE01_RELATIVE_ROOT = Path("derived/replication/pgn_timeforfeit_candidates")
NATIVE_STAGE04_RELATIVE_ROOT = Path("derived/replication/api_timeout_enrichment")
LATE_STAGE04_RELATIVE_ROOT = Path(
    "derived/replication/api_timeout_enrichment_legacy_normalized"
)
EARLIER_OUTCOME_RELATIVE_ROOT = Path(
    "output/main_2023-10_to_2024-09_outcome_material_20260601_165759/"
    "timeout_api_v2_outcome_by_month"
)
DEFAULT_OUTPUT_RELATIVE_ROOT = Path("derived/replication/timeout_opportunity_panel")

# These are the exact curated API lookup Parquets authenticated by canonical
# reconciler 04c.  Stage 05 independently hashes each file and also requires
# its path and hash to agree with the corresponding frozen Stage 04 month
# manifest.  Keeping this mapping explicit prevents an accidental filesystem
# search from selecting a duplicate or stale historical lookup.
EARLIER_API_RELATIVE_PATHS: Mapping[str, str] = {
    "2023-11": (
        "output/api_enrich_main_2023-11_to_2024-01_anon300_sleep1_20260516_110007/"
        "2023-11_lookup_targeted5s_anon300_sleep1_20260516_110007/"
        "game_status_lookup.parquet"
    ),
    "2023-12": (
        "output/api_enrich_main_2023-11_to_2024-01_anon300_sleep1_20260516_110007/"
        "2023-12_lookup_targeted5s_anon300_sleep1_20260519_134140/"
        "game_status_lookup.parquet"
    ),
    "2024-01": (
        "output/api_enrich_main_2023-11_to_2024-01_anon300_sleep1_20260516_110007/"
        "2024-01_lookup_targeted5s_anon300_sleep1_20260522_193316/"
        "game_status_lookup.parquet"
    ),
    "2024-02": (
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-02_20260524_212755/output/"
        "2024-02_lookup_targeted5s_anon300_sleep1_20260525_093128/"
        "game_status_lookup.parquet"
    ),
    "2024-03": (
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-03_to_2024-05_20260514_151655/output/"
        "2024-03_lookup_targeted5s_anon300_sleep1_20260522_025101/"
        "game_status_lookup.parquet"
    ),
    "2024-04": (
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-03_to_2024-05_20260514_151655/output/"
        "2024-04_lookup_targeted5s_anon300_sleep1_20260517_211236/"
        "game_status_lookup.parquet"
    ),
    "2024-05": (
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-03_to_2024-05_20260514_151655/output/"
        "2024-05_lookup_targeted5s_anon300_sleep1_20260514_154511/"
        "game_status_lookup.parquet"
    ),
    "2024-06": (
        "output/api_enrich_main_2024-06_anon300_sleep1_20260526_163105/"
        "2024-06_lookup_targeted5s_anon300_sleep1_20260526_163105/"
        "game_status_lookup.parquet"
    ),
    "2024-07": (
        "output/api_enrichment_imported_from_lexar_20260601_162203/work_desktop/"
        "lichess_api_kit_2024-06_to_2024-09_20260514_143228/output/"
        "2024-07_lookup_targeted5s_anon300_sleep1_20260527_132703/"
        "game_status_lookup.parquet"
    ),
    "2024-08": (
        "output/api_enrichment_imported_from_lexar_20260601_162203/work_desktop/"
        "lichess_api_kit_2024-06_to_2024-09_20260514_143228/output/"
        "2024-08_lookup_targeted5s_anon300_sleep1_20260521_133304/"
        "game_status_lookup.parquet"
    ),
    "2024-09": (
        "output/api_enrichment_imported_from_lexar_20260601_162203/work_desktop/"
        "lichess_api_kit_2024-06_to_2024-09_20260514_143228/output/"
        "2024-09_lookup_targeted5s_anon300_sleep1_20260514_151116/"
        "game_status_lookup.parquet"
    ),
}

LATE_CANDIDATE_RELATIVE_PATHS: Mapping[str, str] = {
    "2025-08": (
        "output/2025-08_candidates_split_5s_20260403_002014/"
        "targeted_ge5s_or_missing.csv"
    ),
    "2025-09": (
        "output/2025-09_candidates_split_5s_20260403_002014/"
        "targeted_ge5s_or_missing.csv"
    ),
    "2025-10": (
        "output/2025-10_candidates_split_5s_20260403_002014/"
        "targeted_ge5s_or_missing.csv"
    ),
}

LATE_CANDIDATE_SHA256: Mapping[str, str] = {
    "2025-08": "90a25df3bec29dcd750d56aeedfad1e83a5e522182cb0fda1e9c0b621fa18dfc",
    "2025-09": "fd226766f2569ac0ebf3be959f6e09c1120f5d619c9852a3a799dfd0b9a18469",
    "2025-10": "cfe4d84962edd078d5ca725963132b9fb0a0f43c6dd72d8803ef89d95d6b11d2",
}

LATE_API_SHA256: Mapping[str, str] = {
    "2025-08": "99e0f10463cacd0d4d7b9c035b2d1b7d4cbe7dcd1a9d9a00403f33abf2df8afe",
    "2025-09": "f6561095d3b874e9f81b1ce414892e6034f1a1cfad7a9eb48422c8f60370037d",
    "2025-10": "81c588140c550a2b2e89c613c9647ea3f9c8230c54bc34666bf100f36737fd23",
}

EXPECTED_CANDIDATE_COLUMNS = (
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
)

EARLIER_LOOKUP_COLUMNS = (
    "id",
    "status",
    "winner",
    "draw",
    "speed",
    "perf",
    "rated",
    "variant",
    "createdAt",
    "lastMoveAt",
    "white_name",
    "black_name",
    "white_rating",
    "black_rating",
)

EARLIER_MATERIAL_COLUMNS = ("chooser_has_mating_material",)

COMMON_API_COLUMNS = (
    "month",
    "game_id",
    "api_status",
    "winner",
    "is_draw",
    "speed",
    "perf",
    "rated",
    "variant",
    "created_at_ms",
    "last_move_at_ms",
    "white_username",
    "white_username_norm",
    "white_rating",
    "white_rating_diff",
    "black_username",
    "black_username_norm",
    "black_rating",
    "black_rating_diff",
)

OUTPUT_COLUMNS = (
    "month",
    "game_id",
    "api_status",
    "source_block",
    "provenance_class",
    "candidate_source_class",
    "site",
    "event",
    "utc_date",
    "utc_time",
    "white_username_pgn",
    "black_username_pgn",
    "white_elo_pgn",
    "black_elo_pgn",
    "white_rating_diff_pgn",
    "black_rating_diff_pgn",
    "pgn_result",
    "pgn_termination",
    "time_control",
    "tc_base_s",
    "tc_inc_s",
    "last_mover_color",
    "chooser_username",
    "chooser_username_norm",
    "chooser_color",
    "chooser_elo",
    "disconnected_username",
    "disconnected_username_norm",
    "disconnected_color",
    "disconnected_elo",
    "white_clock_last_obs_s",
    "black_clock_last_obs_s",
    "chooser_clock_last_obs_s",
    "disconnected_clock_last_obs_s",
    "clock_gap_chooser_minus_disconnected_s",
    "disconnected_clock_positive",
    "five_second_rule_passed",
    "pgn_chooser_raw_win",
    "pgn_raw_draw",
    "last_move_uci",
    "last_move_san",
    "ply_count",
    "side_to_move_after_last",
    "fen_after_last_move",
    "tournament_like_event",
    "api_winner",
    "api_is_draw",
    "api_speed",
    "api_perf",
    "api_rated",
    "api_variant",
    "api_created_at_ms",
    "api_last_move_at_ms",
    "api_white_username",
    "api_white_username_norm",
    "api_white_rating",
    "api_white_rating_diff",
    "api_black_username",
    "api_black_username_norm",
    "api_black_rating",
    "api_black_rating_diff",
    "pgn_api_result_consistent",
    "timeout_draw",
    "timeout_chooser_win",
    "timeout_chooser_loss",
    "chooser_has_mating_material",
    "timeout_draw_no_mating_material",
    "outcome_kind_draw",
    "chooser_material_pts",
    "disconnected_material_pts",
    "disconnected_minus_chooser_material",
    "chooser_pawns",
    "chooser_knights",
    "chooser_bishops",
    "chooser_rooks",
    "chooser_queens",
    "disconnected_pawns",
    "disconnected_knights",
    "disconnected_bishops",
    "disconnected_rooks",
    "disconnected_queens",
    "chooser_pieces",
    "disconnected_pieces",
    "total_pieces",
    "material_total",
    "material_advantage_chooser",
    "avg_rating",
    "rating_gap",
    "rating_gap_abs",
    "rating_gap_100",
    "chooser_higher_rated",
)


class ContractError(RuntimeError):
    """Raised when any fail-closed scientific or provenance gate fails."""


@dataclass(frozen=True)
class FileFingerprint:
    """Stable description of one source or output file."""

    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class MonthSources:
    """Resolved, authenticated source set for one month."""

    month: str
    block: str
    source_block: str
    provenance_class: str
    candidate_source_class: str
    expected_timeout_rows: int
    expected_target_rows: int | None
    frozen_timeout: FileFingerprint
    candidate: FileFingerprint
    api_files: tuple[FileFingerprint, ...]
    authority_files: tuple[FileFingerprint, ...]
    source_set_sha256: str
    candidate_kind: str


def utc_now() -> str:
    """Return a compact, timezone-explicit UTC timestamp."""

    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_stamp() -> str:
    """Return a sortable UTC run identifier."""

    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def require(condition: bool, message: str) -> None:
    """Raise a contract error with a precise message when condition is false."""

    if not condition:
        raise ContractError(message)


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Stream a file into SHA-256 without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path, expected_sha256: str | None = None) -> FileFingerprint:
    """Resolve, hash, and optionally authenticate one regular file."""

    require(path.is_file(), f"required file is missing: {path}")
    resolved = path.resolve()
    observed = sha256_file(resolved)
    if expected_sha256 is not None:
        require(
            observed == expected_sha256,
            f"SHA-256 mismatch for {resolved}: expected {expected_sha256}, got {observed}",
        )
    return FileFingerprint(
        path=str(resolved),
        size_bytes=resolved.stat().st_size,
        sha256=observed,
    )


def source_set_digest(
    month: str,
    block: str,
    files: Sequence[FileFingerprint],
) -> str:
    """Hash an ordered source manifest, independent of JSON whitespace."""

    payload = {
        "contract": "stage05_timeout_opportunity_sources_v6",
        "script_version": SCRIPT_VERSION,
        "month": month,
        "block": block,
        "files": [asdict(item) for item in files],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace a small text artifact in its destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically write pretty, deterministic JSON."""

    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any:
    """Read JSON with a path-aware failure."""

    require(path.is_file(), f"required JSON is missing: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        raise ContractError(f"could not parse JSON {path}: {exc}") from exc


def write_csv(
    path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> None:
    """Write a small manifest CSV atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def sql_string(value: str | Path) -> str:
    """Return a single-quoted DuckDB literal after rejecting NUL bytes."""

    text = str(value)
    require("\x00" not in text, "NUL byte is not allowed in a SQL path")
    return "'" + text.replace("'", "''") + "'"


def parquet_scan_sql(paths: Sequence[str | Path]) -> str:
    """Build an exact path-list Parquet scan with Hive inference disabled."""

    require(bool(paths), "Parquet scan received an empty path list")
    path_list = "[" + ", ".join(sql_string(item) for item in paths) + "]"
    return f"read_parquet({path_list}, hive_partitioning=false, union_by_name=false)"


def bool_sql(expression: str) -> str:
    """Normalize common Boolean/string encodings to nullable SQL BOOLEAN."""

    value = f"lower(trim(CAST({expression} AS VARCHAR)))"
    return (
        "CASE "
        f"WHEN {expression} IS NULL OR {value} IN ('', 'na', 'nan', 'none', 'null') THEN NULL "
        f"WHEN {value} IN ('true', 't', '1', 'yes', 'y') THEN TRUE "
        f"WHEN {value} IN ('false', 'f', '0', 'no', 'n') THEN FALSE "
        "ELSE NULL END"
    )


def color_sql(expression: str) -> str:
    """Normalize white/black and w/b color encodings."""

    value = f"lower(trim(CAST({expression} AS VARCHAR)))"
    return (
        "CASE "
        f"WHEN {value} IN ('white', 'w') THEN 'white' "
        f"WHEN {value} IN ('black', 'b') THEN 'black' "
        "ELSE NULL END"
    )


def name_norm_sql(expression: str) -> str:
    """Normalize a username for identity checks without changing display case."""

    return f"NULLIF(lower(trim(CAST({expression} AS VARCHAR))), '')"


def bridge_is_draw_sql(winner_expression: str = "winner") -> str:
    """Derive bridge draw status from the winner field.

    Native Stage 04 stored ``is_draw`` from terminal-status labels.  That is
    unsuitable for ``status=timeout``, which can be either a draw (no winner)
    or a decisive game (winner is White or Black).
    """

    winner = f"NULLIF(lower(trim(CAST({winner_expression} AS VARCHAR))), '')"
    return (
        "CASE "
        f"WHEN {winner} IS NULL THEN TRUE "
        f"WHEN {winner} IN ('white', 'black') THEN FALSE "
        "ELSE NULL::BOOLEAN END"
    )


def finite_double_sql(expression: str) -> str:
    """Parse a finite float, treating malformed, NaN, and infinity as missing."""

    parsed = f"TRY_CAST({expression} AS DOUBLE)"
    return f"CASE WHEN isfinite({parsed}) THEN {parsed} ELSE NULL::DOUBLE END"


def mating_material_sql(prefix: str = "chooser") -> str:
    """Return the locked historical mating-capacity expression."""

    return (
        f"({prefix}_pawns > 0 OR {prefix}_rooks > 0 OR {prefix}_queens > 0 "
        f"OR {prefix}_bishops >= 2 "
        f"OR ({prefix}_bishops >= 1 AND {prefix}_knights >= 1) "
        f"OR {prefix}_knights >= 2)"
    )


class EventLog:
    """Timestamped terminal and optional file logger."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def emit(self, message: str) -> None:
        line = f"[{utc_now()}] {message}"
        print(line, flush=True)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


def load_duckdb() -> Any:
    """Import DuckDB lazily so --help remains useful without the dependency."""

    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise ContractError(
            "DuckDB is unavailable. Activate the project virtual environment first."
        ) from exc
    return duckdb


def configure_connection(
    duckdb: Any,
    database: str,
    memory_limit: str,
    threads: int,
    temp_directory: Path,
) -> Any:
    """Open a bounded DuckDB connection with an explicit spill directory."""

    connection = duckdb.connect(database=database)
    connection.execute(f"SET memory_limit = {sql_string(memory_limit)}")
    connection.execute(f"SET threads = {int(threads)}")
    connection.execute(f"SET temp_directory = {sql_string(temp_directory)}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute("SET enable_progress_bar = true")
    return connection


def relation_columns(connection: Any, relation_sql: str) -> tuple[str, ...]:
    """Read relation field names without scanning row data."""

    rows = connection.execute(f"DESCRIBE SELECT * FROM {relation_sql}").fetchall()
    return tuple(str(row[0]) for row in rows)


def require_columns(
    observed: Sequence[str], required: Sequence[str], label: str
) -> None:
    """Require named columns while permitting explicitly unused extras."""

    observed_set = set(observed)
    missing = [column for column in required if column not in observed_set]
    require(not missing, f"{label} is missing required columns: {missing}")


def read_csv_header(path: Path) -> tuple[str, ...]:
    """Read exactly one RFC-compatible CSV header row."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return tuple(next(reader))
        except StopIteration as exc:
            raise ContractError(f"candidate CSV is empty: {path}") from exc


def software_versions(duckdb: Any) -> Mapping[str, Any]:
    """Capture the reproducibility-relevant execution environment."""

    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "duckdb": duckdb.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "script_version": SCRIPT_VERSION,
    }


def month_block(month: str) -> str:
    """Map a locked month to its authenticated source block."""

    if month in EARLIER_MONTHS:
        return "earlier"
    if month in BRIDGE_MONTHS:
        return "bridge"
    if month in LATE_MONTHS:
        return "late"
    raise ContractError(f"month is outside the locked sample: {month}")


def validate_stage04_summary(project_root: Path) -> Mapping[str, Mapping[str, Any]]:
    """Authenticate the frozen Stage 04 authority and return monthly records."""

    reconciler = project_root / STAGE04_RECONCILER_RELATIVE_PATH
    fingerprint(reconciler, STAGE04_RECONCILER_SHA256)

    summary_path = (
        project_root
        / STAGE04_FROZEN_RELATIVE_ROOT
        / "_manifests"
        / "latest_summary.json"
    )
    summary = read_json(summary_path)
    require(isinstance(summary, dict), "Stage 04 latest summary is not a JSON object")
    require(
        summary.get("final_ok") is True, "Stage 04 latest summary is not successful"
    )
    require(
        summary.get("analysis_authorization") == "PROCEED_TO_STAGE05_OPPORTUNITY_PANEL",
        "Stage 04 does not authorize Stage 05",
    )
    require(summary.get("months") == list(LOCKED_MONTHS), "Stage 04 month list changed")
    require(summary.get("month_count") == 24, "Stage 04 month count is not 24")
    require(
        summary.get("total_timeout_rows") == EXPECTED_TOTAL_TIMEOUT,
        "Stage 04 timeout total changed",
    )
    require(summary.get("duplicate_game_ids") == 0, "Stage 04 has duplicate game IDs")
    require(summary.get("unresolved_ids") == 0, "Stage 04 has unresolved IDs")

    rows = summary.get("monthly_funnel")
    require(
        isinstance(rows, list) and len(rows) == 24, "Stage 04 monthly funnel is invalid"
    )
    by_month: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), "Stage 04 monthly funnel row is not an object")
        month = row.get("month")
        require(month in LOCKED_MONTHS, f"unexpected Stage 04 month: {month!r}")
        require(month not in by_month, f"duplicate Stage 04 monthly record: {month}")
        require(row.get("final_ok") is True, f"Stage 04 month is not final: {month}")
        expected_path = (
            project_root
            / STAGE04_FROZEN_RELATIVE_ROOT
            / f"month={month}"
            / "timeout_ids.parquet"
        ).resolve()
        require(
            Path(str(row.get("timeout_ids_path"))).resolve() == expected_path,
            f"Stage 04 timeout path changed for {month}",
        )
        digest = row.get("timeout_ids_sha256")
        require(
            isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            f"Stage 04 timeout hash is invalid for {month}",
        )
        timeout_rows = row.get("timeout_rows")
        require(
            isinstance(timeout_rows, int) and timeout_rows > 0,
            f"bad timeout count: {month}",
        )
        if month in LOCKED_TIMEOUT_BY_MONTH:
            require(
                timeout_rows == LOCKED_TIMEOUT_BY_MONTH[month],
                f"Stage 04 timeout count changed for {month}",
            )
        by_month[month] = row

    require(tuple(by_month) == LOCKED_MONTHS, "Stage 04 monthly order changed")
    bridge_total = sum(int(by_month[month]["timeout_rows"]) for month in BRIDGE_MONTHS)
    require(
        bridge_total == EXPECTED_BLOCK_TIMEOUTS["bridge"],
        f"Stage 04 bridge timeout total changed: {bridge_total}",
    )
    return by_month


def resolve_earlier_api_authority(
    project_root: Path,
    month: str,
    stage04_row: Mapping[str, Any],
) -> tuple[FileFingerprint, FileFingerprint]:
    """Authenticate one curated earlier API lookup against Stage 04.

    Reconciler 04c deliberately published only a narrow status index.  Its
    per-month manifest nevertheless preserves the exact full lookup Parquet,
    its SHA-256, and its schema.  Stage 05 uses that record as the authority
    for optional API outcome/player fields while the frozen timeout Parquet
    remains the population authority.
    """

    relative = EARLIER_API_RELATIVE_PATHS[month]
    api_path = (project_root / relative).resolve()
    manifest_path = (
        project_root
        / STAGE04_FROZEN_RELATIVE_ROOT
        / f"month={month}"
        / "month_manifest.json"
    )
    manifest = read_json(manifest_path)
    require(isinstance(manifest, dict), f"{month}: Stage 04 month manifest is invalid")
    require(manifest.get("final_ok") is True, f"{month}: Stage 04 month is not final")
    require(manifest.get("month") == month, f"{month}: Stage 04 manifest month changed")
    require(manifest.get("block") == "earlier", f"{month}: Stage 04 block changed")

    contract = manifest.get("source_contract")
    require(isinstance(contract, dict), f"{month}: Stage 04 source contract is absent")
    require(
        contract.get("source_kind") == "earlier_single_parquet",
        f"{month}: Stage 04 earlier source kind changed",
    )
    require(
        contract.get("earlier_lookup_relative_path") == relative,
        f"{month}: curated earlier API path disagrees with Stage 04",
    )
    outputs = manifest.get("outputs")
    require(isinstance(outputs, dict), f"{month}: Stage 04 outputs record is absent")
    timeout_output = outputs.get("timeout_ids")
    require(
        isinstance(timeout_output, dict)
        and timeout_output.get("sha256") == stage04_row.get("timeout_ids_sha256"),
        f"{month}: Stage 04 manifest/summary timeout hash mismatch",
    )

    source_columns = manifest.get("source_columns")
    require(
        isinstance(source_columns, list),
        f"{month}: Stage 04 earlier source schema is absent",
    )
    require_columns(source_columns, EARLIER_LOOKUP_COLUMNS, f"{month} earlier lookup")
    source_files = manifest.get("source_files")
    require(
        isinstance(source_files, list), f"{month}: Stage 04 source files are absent"
    )
    matches = [
        record
        for record in source_files
        if isinstance(record, dict) and record.get("identity_path") == relative
    ]
    require(
        len(matches) == 1,
        f"{month}: expected exactly one curated API record in Stage 04 manifest",
    )
    record = matches[0]
    expected_sha = record.get("sha256")
    require(
        isinstance(expected_sha, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha) is not None,
        f"{month}: Stage 04 curated API hash is invalid",
    )
    require(
        Path(str(record.get("path"))).resolve() == api_path,
        f"{month}: Stage 04 curated API absolute path changed",
    )
    api = fingerprint(api_path, expected_sha)
    require(
        record.get("size_bytes") == api.size_bytes,
        f"{month}: Stage 04 curated API size changed",
    )
    return api, fingerprint(manifest_path)


def resolve_month_sources(
    month: str,
    project_root: Path,
    legacy_root: Path,
    stage04_row: Mapping[str, Any],
    logger: EventLog,
) -> MonthSources:
    """Resolve and authenticate every file needed to build one month."""

    block = month_block(month)
    expected_timeout = int(stage04_row["timeout_rows"])
    frozen_path = (
        project_root
        / STAGE04_FROZEN_RELATIVE_ROOT
        / f"month={month}"
        / "timeout_ids.parquet"
    )
    logger.emit(f"{month}: authenticating frozen Stage 04 timeout IDs")
    frozen = fingerprint(frozen_path, str(stage04_row["timeout_ids_sha256"]))

    expected_target: int | None = None
    authority_files: tuple[FileFingerprint, ...] = ()
    if block == "earlier":
        expected_target = LOCKED_TARGET_BY_MONTH[month]
        require(
            stage04_row.get("target_rows") == expected_target,
            f"{month}: Stage 04 earlier target count changed",
        )
        candidate_path = (
            project_root
            / EARLIER_OUTCOME_RELATIVE_ROOT
            / f"month={month}"
            / f"timeout_api_v2_outcome_{month}.parquet"
        )
        candidate = fingerprint(candidate_path)
        earlier_api, authority_manifest = resolve_earlier_api_authority(
            project_root, month, stage04_row
        )
        api_files = (earlier_api,)
        authority_files = (authority_manifest,)
        source_block = "earlier_legacy"
        provenance_class = "historical_outcome_material_plus_curated_stage04_lookup"
        candidate_source_class = "historical_monthly_outcome_material_parquet"
        candidate_kind = "parquet"
    elif block == "bridge":
        expected_target = LOCKED_TARGET_BY_MONTH[month]
        candidate_path = (
            project_root
            / STAGE01_RELATIVE_ROOT
            / f"month={month}"
            / "api_target_candidates_ge5s_or_missing.parquet"
        )
        candidate = fingerprint(candidate_path)
        response_dir = (
            project_root / NATIVE_STAGE04_RELATIVE_ROOT / f"month={month}" / "responses"
        )
        response_paths = sorted(response_dir.glob("unit-*.parquet"))
        require(
            len(response_paths) == BRIDGE_UNIT_COUNTS[month],
            f"{month}: expected {BRIDGE_UNIT_COUNTS[month]} native response units, "
            f"found {len(response_paths)}",
        )
        logger.emit(
            f"{month}: hashing {len(response_paths)} native Stage 04 response units"
        )
        api_files = tuple(fingerprint(path) for path in response_paths)
        source_block = "bridge_native_stage04"
        provenance_class = "canonical_stage01_plus_native_stage04"
        candidate_source_class = "canonical_stage01_target_parquet"
        candidate_kind = "parquet"
    else:
        expected_target = LOCKED_TARGET_BY_MONTH[month]
        candidate_path = legacy_root / LATE_CANDIDATE_RELATIVE_PATHS[month]
        candidate = fingerprint(candidate_path, LATE_CANDIDATE_SHA256[month])
        header = read_csv_header(candidate_path)
        require(
            header == EXPECTED_CANDIDATE_COLUMNS,
            f"{month}: legacy candidate header changed; expected "
            f"{EXPECTED_CANDIDATE_COLUMNS}, got {header}",
        )
        api_path = (
            project_root
            / LATE_STAGE04_RELATIVE_ROOT
            / f"month={month}"
            / "responses"
            / "legacy-normalized.parquet"
        )
        api_files = (fingerprint(api_path, LATE_API_SHA256[month]),)
        source_block = "late_legacy_normalized"
        provenance_class = "authenticated_legacy_candidate_plus_04b"
        candidate_source_class = "authenticated_legacy_target_csv"
        candidate_kind = "csv"

    ordered_files = (frozen, candidate, *api_files, *authority_files)
    digest = source_set_digest(month, block, ordered_files)
    return MonthSources(
        month=month,
        block=block,
        source_block=source_block,
        provenance_class=provenance_class,
        candidate_source_class=candidate_source_class,
        expected_timeout_rows=expected_timeout,
        expected_target_rows=expected_target,
        frozen_timeout=frozen,
        candidate=candidate,
        api_files=tuple(api_files),
        authority_files=authority_files,
        source_set_sha256=digest,
        candidate_kind=candidate_kind,
    )


def candidate_scan_sql(sources: MonthSources) -> str:
    """Return the source relation for one month's PGN candidate fields."""

    if sources.candidate_kind == "parquet":
        return parquet_scan_sql((sources.candidate.path,))
    # all_varchar makes the legacy CSV contract deterministic across DuckDB
    # versions.  Every analytical type is cast explicitly in candidate_norm.
    return (
        f"read_csv({sql_string(sources.candidate.path)}, header=true, "
        "all_varchar=true, strict_mode=true, parallel=true)"
    )


def install_source_views(connection: Any, sources: MonthSources) -> None:
    """Create common-schema temporary views for candidate, API, and frozen IDs."""

    candidate_relation = candidate_scan_sql(sources)
    candidate_columns = relation_columns(connection, candidate_relation)
    require_columns(
        candidate_columns, EXPECTED_CANDIDATE_COLUMNS, f"{sources.month} candidate"
    )
    if sources.block == "earlier":
        require_columns(
            candidate_columns,
            EARLIER_MATERIAL_COLUMNS,
            f"{sources.month} earlier material",
        )

    api_relation = parquet_scan_sql(tuple(item.path for item in sources.api_files))
    api_columns = relation_columns(connection, api_relation)
    if sources.block == "earlier":
        require_columns(
            api_columns, EARLIER_LOOKUP_COLUMNS, f"{sources.month} earlier API"
        )
    else:
        require_columns(
            api_columns, COMMON_API_COLUMNS, f"{sources.month} API evidence"
        )

    frozen_relation = parquet_scan_sql((sources.frozen_timeout.path,))
    frozen_columns = relation_columns(connection, frozen_relation)
    require_columns(
        frozen_columns,
        ("month", "game_id", "api_status", "source_block", "provenance_class"),
        f"{sources.month} frozen IDs",
    )

    connection.execute("DROP VIEW IF EXISTS frozen_ids")
    connection.execute("DROP VIEW IF EXISTS candidate_raw")
    connection.execute("DROP VIEW IF EXISTS candidate_norm")
    connection.execute("DROP VIEW IF EXISTS api_raw")
    connection.execute("DROP VIEW IF EXISTS api_norm")

    connection.execute(
        f"""
        CREATE TEMP VIEW frozen_ids AS
        SELECT
            CAST(month AS VARCHAR) AS month,
            CAST(game_id AS VARCHAR) AS game_id,
            lower(trim(CAST(api_status AS VARCHAR))) AS api_status
        FROM {frozen_relation}
        """
    )
    connection.execute(
        f"CREATE TEMP VIEW candidate_raw AS SELECT * FROM {candidate_relation}"
    )
    connection.execute(f"CREATE TEMP VIEW api_raw AS SELECT * FROM {api_relation}")

    if sources.block == "earlier":
        reference_material = """
            {ref_flag} AS reference_chooser_has_mating_material
        """.format(ref_flag=bool_sql("chooser_has_mating_material"))
    else:
        reference_material = """
            NULL::BOOLEAN AS reference_chooser_has_mating_material
        """

    connection.execute(
        f"""
        CREATE TEMP VIEW candidate_norm AS
        SELECT
            CAST(archive_month AS VARCHAR) AS archive_month,
            CAST(game_id AS VARCHAR) AS game_id,
            NULLIF(CAST(site AS VARCHAR), '') AS site,
            NULLIF(CAST(event AS VARCHAR), '') AS event,
            NULLIF(CAST(utc_date AS VARCHAR), '') AS utc_date,
            NULLIF(CAST(utc_time AS VARCHAR), '') AS utc_time,
            NULLIF(CAST(white AS VARCHAR), '') AS white_username_pgn,
            NULLIF(CAST(black AS VARCHAR), '') AS black_username_pgn,
            TRY_CAST(white_elo AS INTEGER) AS white_elo_pgn,
            TRY_CAST(black_elo AS INTEGER) AS black_elo_pgn,
            TRY_CAST(white_rating_diff AS INTEGER) AS white_rating_diff_pgn,
            TRY_CAST(black_rating_diff AS INTEGER) AS black_rating_diff_pgn,
            NULLIF(trim(CAST(result AS VARCHAR)), '') AS pgn_result,
            NULLIF(trim(CAST(termination AS VARCHAR)), '') AS pgn_termination,
            NULLIF(trim(CAST(time_control AS VARCHAR)), '') AS time_control,
            {finite_double_sql("tc_base_s")} AS tc_base_s,
            {finite_double_sql("tc_inc_s")} AS tc_inc_s,
            {color_sql("last_mover_color")} AS last_mover_color,
            NULLIF(CAST(candidate_chooser AS VARCHAR), '') AS chooser_username,
            {name_norm_sql("candidate_chooser")} AS chooser_username_norm,
            {color_sql("candidate_chooser_color")} AS chooser_color,
            TRY_CAST(candidate_chooser_elo AS INTEGER) AS chooser_elo,
            NULLIF(CAST(likely_disconnected_player AS VARCHAR), '')
                AS disconnected_username,
            {name_norm_sql("likely_disconnected_player")} AS disconnected_username_norm,
            {color_sql("likely_disconnected_color")} AS disconnected_color,
            TRY_CAST(likely_disconnected_elo AS INTEGER) AS disconnected_elo,
            {finite_double_sql("white_clock_last_obs_s")} AS white_clock_last_obs_s,
            {finite_double_sql("black_clock_last_obs_s")} AS black_clock_last_obs_s,
            {finite_double_sql("chooser_clock_last_obs_s")} AS chooser_clock_last_obs_s,
            {finite_double_sql("disconnected_clock_last_obs_s")}
                AS disconnected_clock_last_obs_s,
            {finite_double_sql("clock_gap_chooser_minus_disconnected_s")}
                AS clock_gap_chooser_minus_disconnected_s,
            {bool_sql("disconnected_clock_positive")} AS disconnected_clock_positive,
            {bool_sql("chooser_raw_win")} AS pgn_chooser_raw_win,
            {bool_sql("raw_draw")} AS pgn_raw_draw,
            NULLIF(CAST(last_move_uci AS VARCHAR), '') AS last_move_uci,
            NULLIF(CAST(last_move_san AS VARCHAR), '') AS last_move_san,
            TRY_CAST(ply_count AS INTEGER) AS ply_count,
            {color_sql("side_to_move_after_last")} AS side_to_move_after_last,
            NULLIF(trim(CAST(fen_after_last_move AS VARCHAR)), '') AS fen_after_last_move,
            {bool_sql("tournament_like_event")} AS tournament_like_event,
            {reference_material}
        FROM candidate_raw
        """
    )

    if sources.block == "earlier":
        connection.execute(
            f"""
            CREATE TEMP VIEW api_norm AS
            SELECT
                {sql_string(sources.month)}::VARCHAR AS month,
                CAST(id AS VARCHAR) AS game_id,
                lower(trim(CAST(status AS VARCHAR))) AS api_status,
                NULLIF(lower(trim(CAST(winner AS VARCHAR))), '') AS api_winner,
                {bool_sql("draw")} AS api_is_draw,
                NULLIF(lower(trim(CAST(speed AS VARCHAR))), '') AS api_speed,
                NULLIF(CAST(perf AS VARCHAR), '') AS api_perf,
                {bool_sql("rated")} AS api_rated,
                NULLIF(lower(trim(CAST(variant AS VARCHAR))), '') AS api_variant,
                TRY_CAST(createdAt AS BIGINT) AS api_created_at_ms,
                TRY_CAST(lastMoveAt AS BIGINT) AS api_last_move_at_ms,
                NULLIF(CAST(white_name AS VARCHAR), '') AS api_white_username,
                {name_norm_sql("white_name")} AS api_white_username_norm,
                TRY_CAST(white_rating AS INTEGER) AS api_white_rating,
                NULL::INTEGER AS api_white_rating_diff,
                NULLIF(CAST(black_name AS VARCHAR), '') AS api_black_username,
                {name_norm_sql("black_name")} AS api_black_username_norm,
                TRY_CAST(black_rating AS INTEGER) AS api_black_rating,
                NULL::INTEGER AS api_black_rating_diff
            FROM api_raw
            WHERE lower(trim(CAST(status AS VARCHAR))) = 'timeout'
            """
        )
    else:
        api_is_draw = (
            bridge_is_draw_sql("winner")
            if sources.block == "bridge"
            else bool_sql("is_draw")
        )
        connection.execute(
            f"""
            CREATE TEMP VIEW api_norm AS
            SELECT
                CAST(month AS VARCHAR) AS month,
                CAST(game_id AS VARCHAR) AS game_id,
                lower(trim(CAST(api_status AS VARCHAR))) AS api_status,
                NULLIF(lower(trim(CAST(winner AS VARCHAR))), '') AS api_winner,
                {api_is_draw} AS api_is_draw,
                NULLIF(lower(trim(CAST(speed AS VARCHAR))), '') AS api_speed,
                NULLIF(CAST(perf AS VARCHAR), '') AS api_perf,
                {bool_sql("rated")} AS api_rated,
                NULLIF(lower(trim(CAST(variant AS VARCHAR))), '') AS api_variant,
                TRY_CAST(created_at_ms AS BIGINT) AS api_created_at_ms,
                TRY_CAST(last_move_at_ms AS BIGINT) AS api_last_move_at_ms,
                NULLIF(CAST(white_username AS VARCHAR), '') AS api_white_username,
                {name_norm_sql("white_username")} AS api_white_username_norm,
                TRY_CAST(white_rating AS INTEGER) AS api_white_rating,
                TRY_CAST(white_rating_diff AS INTEGER) AS api_white_rating_diff,
                NULLIF(CAST(black_username AS VARCHAR), '') AS api_black_username,
                {name_norm_sql("black_username")} AS api_black_username_norm,
                TRY_CAST(black_rating AS INTEGER) AS api_black_rating,
                TRY_CAST(black_rating_diff AS INTEGER) AS api_black_rating_diff
            FROM api_raw
            """
        )


def relation_cardinality(
    connection: Any, relation: str, id_column: str
) -> Mapping[str, int]:
    """Return exact row, nonmissing-ID, and distinct-ID counts."""

    row = connection.execute(
        f"""
        SELECT
            COUNT(*)::BIGINT AS rows,
            COUNT({id_column})::BIGINT AS nonmissing_ids,
            COUNT(DISTINCT {id_column})::BIGINT AS distinct_ids
        FROM {relation}
        """
    ).fetchone()
    return {
        "rows": int(row[0]),
        "nonmissing_ids": int(row[1]),
        "distinct_ids": int(row[2]),
    }


def preflight_month(connection: Any, sources: MonthSources) -> Mapping[str, Any]:
    """Prove source cardinality and exact coverage before writing output."""

    frozen = relation_cardinality(connection, "frozen_ids", "game_id")
    require(
        frozen
        == {
            "rows": sources.expected_timeout_rows,
            "nonmissing_ids": sources.expected_timeout_rows,
            "distinct_ids": sources.expected_timeout_rows,
        },
        f"{sources.month}: frozen timeout cardinality failed: {frozen}",
    )
    frozen_bad = int(
        connection.execute(
            "SELECT COUNT(*) FROM frozen_ids WHERE month <> ? OR api_status <> 'timeout'",
            [sources.month],
        ).fetchone()[0]
    )
    require(frozen_bad == 0, f"{sources.month}: frozen timeout semantics failed")

    candidate = relation_cardinality(connection, "candidate_norm", "game_id")
    expected_candidate_rows = (
        sources.expected_timeout_rows
        if sources.block == "earlier"
        else int(sources.expected_target_rows or 0)
    )
    require(
        candidate
        == {
            "rows": expected_candidate_rows,
            "nonmissing_ids": expected_candidate_rows,
            "distinct_ids": expected_candidate_rows,
        },
        f"{sources.month}: candidate cardinality failed: {candidate}",
    )
    wrong_candidate_month = int(
        connection.execute(
            "SELECT COUNT(*) FROM candidate_norm WHERE archive_month <> ?",
            [sources.month],
        ).fetchone()[0]
    )
    require(wrong_candidate_month == 0, f"{sources.month}: candidate month mismatch")

    earlier_api_source: Mapping[str, int] | None = None
    if sources.block == "earlier":
        earlier_api_source = relation_cardinality(connection, "api_raw", "id")
        expected_target = int(sources.expected_target_rows or 0)
        require(
            earlier_api_source
            == {
                "rows": expected_target,
                "nonmissing_ids": expected_target,
                "distinct_ids": expected_target,
            },
            f"{sources.month}: curated API source cardinality failed: "
            f"{earlier_api_source}",
        )
        status_counts = connection.execute(
            """
            SELECT
                SUM((lower(trim(CAST(status AS VARCHAR))) = 'timeout')::INTEGER)::BIGINT,
                SUM((lower(trim(CAST(status AS VARCHAR))) = 'outoftime')::INTEGER)::BIGINT,
                SUM((lower(trim(CAST(status AS VARCHAR)))
                    NOT IN ('timeout', 'outoftime'))::INTEGER)::BIGINT
            FROM api_raw
            """
        ).fetchone()
        observed_timeout, observed_outoftime, invalid_status = (
            int(value or 0) for value in status_counts
        )
        require(
            observed_timeout == sources.expected_timeout_rows
            and observed_outoftime == expected_target - sources.expected_timeout_rows
            and invalid_status == 0,
            f"{sources.month}: curated API status partition failed: "
            f"timeout={observed_timeout}, outoftime={observed_outoftime}, "
            f"invalid={invalid_status}",
        )

    api = relation_cardinality(connection, "api_norm", "game_id")
    expected_api_rows = (
        sources.expected_timeout_rows
        if sources.block == "earlier"
        else int(sources.expected_target_rows or 0)
    )
    require(
        api
        == {
            "rows": expected_api_rows,
            "nonmissing_ids": expected_api_rows,
            "distinct_ids": expected_api_rows,
        },
        f"{sources.month}: API evidence cardinality failed: {api}",
    )

    coverage = connection.execute(
        """
        SELECT
            COUNT(*)::BIGINT AS frozen_rows,
            COUNT(c.game_id)::BIGINT AS candidate_matches,
            COUNT(a.game_id)::BIGINT AS api_matches
        FROM frozen_ids f
        LEFT JOIN candidate_norm c USING (game_id)
        LEFT JOIN api_norm a USING (game_id)
        """
    ).fetchone()
    require(
        tuple(int(value) for value in coverage)
        == (
            sources.expected_timeout_rows,
            sources.expected_timeout_rows,
            sources.expected_timeout_rows,
        ),
        f"{sources.month}: frozen-ID coverage failed: {coverage}",
    )
    api_status_mismatches = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM frozen_ids f
            INNER JOIN api_norm a USING (game_id)
            WHERE a.month <> f.month OR a.api_status <> f.api_status
            """
        ).fetchone()[0]
    )
    require(
        api_status_mismatches == 0,
        f"{sources.month}: API evidence disagrees with frozen Stage 04 status "
        f"for {api_status_mismatches} rows",
    )
    bridge_outcome_adapter: Mapping[str, int] | None = None
    if sources.block == "bridge":
        bridge_values = connection.execute(
            f"""
            SELECT
                SUM((lower(trim(CAST(api_status AS VARCHAR))) = 'timeout'
                     AND ({bool_sql("is_draw")}) IS DISTINCT FROM
                         ({bridge_is_draw_sql("winner")}))::INTEGER)::BIGINT,
                SUM((lower(trim(CAST(api_status AS VARCHAR))) = 'timeout'
                     AND ({bridge_is_draw_sql("winner")}) IS TRUE)::INTEGER)::BIGINT,
                SUM((lower(trim(CAST(api_status AS VARCHAR))) = 'timeout'
                     AND ({bridge_is_draw_sql("winner")}) IS NULL)::INTEGER)::BIGINT,
                SUM((lower(trim(CAST(api_status AS VARCHAR))) = 'timeout'
                     AND ({bool_sql("is_draw")}) IS TRUE)::INTEGER)::BIGINT
            FROM api_raw
            """
        ).fetchone()
        bridge_outcome_adapter = {
            "stored_is_draw_disagreements": int(bridge_values[0] or 0),
            "derived_timeout_draws": int(bridge_values[1] or 0),
            "invalid_timeout_winner_encodings": int(bridge_values[2] or 0),
            "stored_timeout_draw_true_rows": int(bridge_values[3] or 0),
        }
        require(
            bridge_outcome_adapter["invalid_timeout_winner_encodings"] == 0,
            f"{sources.month}: bridge timeout winner encoding is invalid: "
            f"{bridge_outcome_adapter}",
        )
        require(
            bridge_outcome_adapter["stored_timeout_draw_true_rows"] == 0
            and bridge_outcome_adapter["stored_is_draw_disagreements"]
            == bridge_outcome_adapter["derived_timeout_draws"],
            f"{sources.month}: bridge stored is_draw defect has an unexpected "
            f"shape: {bridge_outcome_adapter}",
        )

    result: dict[str, Any] = {
        "frozen": frozen,
        "candidate": candidate,
        "api": api,
        "api_status_mismatches": api_status_mismatches,
    }
    if earlier_api_source is not None:
        result["earlier_api_source"] = dict(earlier_api_source)
    if bridge_outcome_adapter is not None:
        result["bridge_outcome_adapter"] = dict(bridge_outcome_adapter)
    return result


def opportunity_select_sql(sources: MonthSources) -> str:
    """Return the deterministic common-schema Stage 05 transformation."""

    # Character counts in the FEN board field are exact piece counts.  Digits,
    # slashes, active color, castling, and move counters cannot masquerade as
    # piece letters because only the first space-delimited FEN field is used.
    has_mating = mating_material_sql("chooser")
    return f"""
    WITH joined AS (
        SELECT
            f.month,
            f.game_id,
            f.api_status,
            c.* EXCLUDE (archive_month, game_id),
            a.* EXCLUDE (month, game_id, api_status)
        FROM frozen_ids f
        INNER JOIN candidate_norm c USING (game_id)
        INNER JOIN api_norm a USING (game_id)
    ),
    board AS (
        SELECT *, split_part(fen_after_last_move, ' ', 1) AS fen_board
        FROM joined
    ),
    side_counts AS (
        SELECT *,
            length(fen_board) - length(replace(fen_board, 'P', '')) AS white_pawns,
            length(fen_board) - length(replace(fen_board, 'N', '')) AS white_knights,
            length(fen_board) - length(replace(fen_board, 'B', '')) AS white_bishops,
            length(fen_board) - length(replace(fen_board, 'R', '')) AS white_rooks,
            length(fen_board) - length(replace(fen_board, 'Q', '')) AS white_queens,
            length(fen_board) - length(replace(fen_board, 'p', '')) AS black_pawns,
            length(fen_board) - length(replace(fen_board, 'n', '')) AS black_knights,
            length(fen_board) - length(replace(fen_board, 'b', '')) AS black_bishops,
            length(fen_board) - length(replace(fen_board, 'r', '')) AS black_rooks,
            length(fen_board) - length(replace(fen_board, 'q', '')) AS black_queens
        FROM board
    ),
    role_counts AS (
        SELECT *,
            CASE WHEN chooser_color = 'white' THEN white_pawns ELSE black_pawns END
                ::INTEGER AS chooser_pawns,
            CASE WHEN chooser_color = 'white' THEN white_knights ELSE black_knights END
                ::INTEGER AS chooser_knights,
            CASE WHEN chooser_color = 'white' THEN white_bishops ELSE black_bishops END
                ::INTEGER AS chooser_bishops,
            CASE WHEN chooser_color = 'white' THEN white_rooks ELSE black_rooks END
                ::INTEGER AS chooser_rooks,
            CASE WHEN chooser_color = 'white' THEN white_queens ELSE black_queens END
                ::INTEGER AS chooser_queens,
            CASE WHEN disconnected_color = 'white' THEN white_pawns ELSE black_pawns END
                ::INTEGER AS disconnected_pawns,
            CASE WHEN disconnected_color = 'white' THEN white_knights ELSE black_knights END
                ::INTEGER AS disconnected_knights,
            CASE WHEN disconnected_color = 'white' THEN white_bishops ELSE black_bishops END
                ::INTEGER AS disconnected_bishops,
            CASE WHEN disconnected_color = 'white' THEN white_rooks ELSE black_rooks END
                ::INTEGER AS disconnected_rooks,
            CASE WHEN disconnected_color = 'white' THEN white_queens ELSE black_queens END
                ::INTEGER AS disconnected_queens
        FROM side_counts
    ),
    material AS (
        SELECT *,
            (chooser_pawns + 3 * chooser_knights + 3 * chooser_bishops
             + 5 * chooser_rooks + 9 * chooser_queens)::INTEGER AS chooser_material_pts,
            (disconnected_pawns + 3 * disconnected_knights + 3 * disconnected_bishops
             + 5 * disconnected_rooks + 9 * disconnected_queens)::INTEGER
                AS disconnected_material_pts,
            (chooser_pawns + chooser_knights + chooser_bishops
             + chooser_rooks + chooser_queens)::INTEGER AS chooser_pieces,
            (disconnected_pawns + disconnected_knights + disconnected_bishops
             + disconnected_rooks + disconnected_queens)::INTEGER AS disconnected_pieces,
            {has_mating} AS chooser_has_mating_material
        FROM role_counts
    ),
    outcomes AS (
        SELECT *,
            (disconnected_clock_last_obs_s IS NULL
             OR disconnected_clock_last_obs_s >= 5.0) AS five_second_rule_passed,
            CASE
                WHEN api_is_draw IS TRUE AND pgn_result = '1/2-1/2' THEN TRUE
                WHEN api_is_draw IS FALSE AND api_winner = 'white' AND pgn_result = '1-0'
                    THEN TRUE
                WHEN api_is_draw IS FALSE AND api_winner = 'black' AND pgn_result = '0-1'
                    THEN TRUE
                ELSE FALSE
            END AS pgn_api_result_consistent,
            api_is_draw IS TRUE AS timeout_draw,
            (api_is_draw IS FALSE AND api_winner = chooser_color) AS timeout_chooser_win,
            (api_is_draw IS FALSE AND api_winner = disconnected_color)
                AS timeout_chooser_loss,
            (api_is_draw IS TRUE AND NOT chooser_has_mating_material)
                AS timeout_draw_no_mating_material,
            (api_is_draw IS TRUE AND chooser_has_mating_material) AS outcome_kind_draw
        FROM material
    )
    SELECT
        month,
        game_id,
        api_status,
        {sql_string(sources.source_block)}::VARCHAR AS source_block,
        {sql_string(sources.provenance_class)}::VARCHAR AS provenance_class,
        {sql_string(sources.candidate_source_class)}::VARCHAR AS candidate_source_class,
        site,
        event,
        utc_date,
        utc_time,
        white_username_pgn,
        black_username_pgn,
        white_elo_pgn,
        black_elo_pgn,
        white_rating_diff_pgn,
        black_rating_diff_pgn,
        pgn_result,
        pgn_termination,
        time_control,
        tc_base_s,
        tc_inc_s,
        last_mover_color,
        chooser_username,
        chooser_username_norm,
        chooser_color,
        chooser_elo,
        disconnected_username,
        disconnected_username_norm,
        disconnected_color,
        disconnected_elo,
        white_clock_last_obs_s,
        black_clock_last_obs_s,
        chooser_clock_last_obs_s,
        disconnected_clock_last_obs_s,
        clock_gap_chooser_minus_disconnected_s,
        disconnected_clock_positive,
        five_second_rule_passed,
        pgn_chooser_raw_win,
        pgn_raw_draw,
        last_move_uci,
        last_move_san,
        ply_count,
        side_to_move_after_last,
        fen_after_last_move,
        tournament_like_event,
        api_winner,
        api_is_draw,
        api_speed,
        api_perf,
        api_rated,
        api_variant,
        api_created_at_ms,
        api_last_move_at_ms,
        api_white_username,
        api_white_username_norm,
        api_white_rating,
        api_white_rating_diff,
        api_black_username,
        api_black_username_norm,
        api_black_rating,
        api_black_rating_diff,
        pgn_api_result_consistent,
        timeout_draw,
        timeout_chooser_win,
        timeout_chooser_loss,
        chooser_has_mating_material,
        timeout_draw_no_mating_material,
        outcome_kind_draw,
        chooser_material_pts,
        disconnected_material_pts,
        (disconnected_material_pts - chooser_material_pts)::INTEGER
            AS disconnected_minus_chooser_material,
        chooser_pawns,
        chooser_knights,
        chooser_bishops,
        chooser_rooks,
        chooser_queens,
        disconnected_pawns,
        disconnected_knights,
        disconnected_bishops,
        disconnected_rooks,
        disconnected_queens,
        chooser_pieces,
        disconnected_pieces,
        (chooser_pieces + disconnected_pieces)::INTEGER AS total_pieces,
        (chooser_material_pts + disconnected_material_pts)::INTEGER AS material_total,
        (chooser_material_pts - disconnected_material_pts)::INTEGER
            AS material_advantage_chooser,
        ((chooser_elo + disconnected_elo) / 2.0)::DOUBLE AS avg_rating,
        (chooser_elo - disconnected_elo)::INTEGER AS rating_gap,
        abs(chooser_elo - disconnected_elo)::INTEGER AS rating_gap_abs,
        ((chooser_elo - disconnected_elo) / 100.0)::DOUBLE AS rating_gap_100,
        (chooser_elo > disconnected_elo) AS chooser_higher_rated
    FROM outcomes
    """


def opportunity_gates_sql() -> str:
    """Return one aggregate query covering all row-level scientific gates."""

    return """
    SELECT
        COUNT(*)::BIGINT AS rows,
        COUNT(game_id)::BIGINT AS nonmissing_ids,
        COUNT(DISTINCT game_id)::BIGINT AS distinct_ids,
        SUM((api_status <> 'timeout')::INTEGER)::BIGINT AS non_timeout_rows,
        SUM((month IS NULL OR game_id IS NULL)::INTEGER)::BIGINT AS missing_keys,
        SUM((NOT regexp_full_match(game_id, '[A-Za-z0-9]{8}'))::INTEGER)::BIGINT
            AS malformed_game_ids,
        SUM((lower(trim(pgn_termination)) <> 'time forfeit')::INTEGER)::BIGINT
            AS bad_terminations,
        SUM((last_mover_color IS NULL OR chooser_color IS NULL
             OR disconnected_color IS NULL OR side_to_move_after_last IS NULL)::INTEGER)
            ::BIGINT AS missing_roles,
        SUM((last_mover_color <> chooser_color)::INTEGER)::BIGINT
            AS chooser_not_last_mover,
        SUM((side_to_move_after_last <> disconnected_color)::INTEGER)::BIGINT
            AS disconnected_not_side_to_move,
        SUM((chooser_color = disconnected_color)::INTEGER)::BIGINT AS same_role_color,
        SUM((chooser_username_norm IS NULL OR disconnected_username_norm IS NULL)::INTEGER)
            ::BIGINT AS missing_role_usernames,
        SUM((chooser_username_norm <> CASE WHEN chooser_color = 'white'
                                          THEN lower(trim(white_username_pgn))
                                          ELSE lower(trim(black_username_pgn)) END)::INTEGER)
            ::BIGINT AS chooser_username_mismatches,
        SUM((disconnected_username_norm <> CASE WHEN disconnected_color = 'white'
                                               THEN lower(trim(white_username_pgn))
                                               ELSE lower(trim(black_username_pgn)) END)::INTEGER)
            ::BIGINT AS disconnected_username_mismatches,
        SUM((five_second_rule_passed IS DISTINCT FROM TRUE)::INTEGER)::BIGINT
            AS five_second_violations,
        SUM((fen_after_last_move IS NULL)::INTEGER)::BIGINT AS missing_final_fen,
        SUM((pgn_api_result_consistent IS DISTINCT FROM TRUE)::INTEGER)::BIGINT
            AS result_mismatches,
        SUM((pgn_raw_draw IS DISTINCT FROM timeout_draw)::INTEGER)::BIGINT
            AS raw_draw_mismatches,
        SUM((pgn_chooser_raw_win IS DISTINCT FROM timeout_chooser_win)::INTEGER)::BIGINT
            AS raw_chooser_win_mismatches,
        SUM((api_is_draw IS NULL)::INTEGER)::BIGINT AS missing_api_draw,
        SUM(((api_is_draw IS TRUE AND api_winner IS NOT NULL)
             OR (api_is_draw IS FALSE AND api_winner NOT IN ('white', 'black'))
             OR (api_is_draw IS FALSE AND api_winner IS NULL))::INTEGER)::BIGINT
            AS invalid_api_winner,
        SUM((api_variant IS DISTINCT FROM 'standard')::INTEGER)::BIGINT
            AS nonstandard_variant,
        SUM((api_rated IS DISTINCT FROM TRUE)::INTEGER)::BIGINT AS nonrated_rows,
        SUM((api_white_username_norm IS NOT NULL
             AND api_white_username_norm <> lower(trim(white_username_pgn)))::INTEGER)
            ::BIGINT AS api_white_username_mismatches,
        SUM((api_black_username_norm IS NOT NULL
             AND api_black_username_norm <> lower(trim(black_username_pgn)))::INTEGER)
            ::BIGINT AS api_black_username_mismatches,
        SUM(timeout_draw::INTEGER)::BIGINT AS timeout_draws,
        SUM(timeout_chooser_win::INTEGER)::BIGINT AS timeout_chooser_wins,
        SUM(timeout_chooser_loss::INTEGER)::BIGINT AS timeout_chooser_losses,
        SUM(chooser_has_mating_material::INTEGER)::BIGINT AS chooser_has_mating_material_rows,
        SUM(timeout_draw_no_mating_material::INTEGER)::BIGINT
            AS timeout_draws_no_mating_material,
        SUM(outcome_kind_draw::INTEGER)::BIGINT AS outcome_kind_draws,
        SUM((disconnected_clock_last_obs_s IS NULL)::INTEGER)::BIGINT
            AS missing_disconnected_clock_rows
    FROM output_relation
    """


GATE_FIELDS = (
    "rows",
    "nonmissing_ids",
    "distinct_ids",
    "non_timeout_rows",
    "missing_keys",
    "malformed_game_ids",
    "bad_terminations",
    "missing_roles",
    "chooser_not_last_mover",
    "disconnected_not_side_to_move",
    "same_role_color",
    "missing_role_usernames",
    "chooser_username_mismatches",
    "disconnected_username_mismatches",
    "five_second_violations",
    "missing_final_fen",
    "result_mismatches",
    "raw_draw_mismatches",
    "raw_chooser_win_mismatches",
    "missing_api_draw",
    "invalid_api_winner",
    "nonstandard_variant",
    "nonrated_rows",
    "api_white_username_mismatches",
    "api_black_username_mismatches",
    "timeout_draws",
    "timeout_chooser_wins",
    "timeout_chooser_losses",
    "chooser_has_mating_material_rows",
    "timeout_draws_no_mating_material",
    "outcome_kind_draws",
    "missing_disconnected_clock_rows",
)

ZERO_GATE_FIELDS = (
    "non_timeout_rows",
    "missing_keys",
    "malformed_game_ids",
    "bad_terminations",
    "missing_roles",
    "chooser_not_last_mover",
    "disconnected_not_side_to_move",
    "same_role_color",
    "missing_role_usernames",
    "chooser_username_mismatches",
    "disconnected_username_mismatches",
    "five_second_violations",
    "missing_final_fen",
    "result_mismatches",
    "raw_draw_mismatches",
    "raw_chooser_win_mismatches",
    "missing_api_draw",
    "invalid_api_winner",
    "nonstandard_variant",
    "nonrated_rows",
)

# These independent API-versus-PGN metadata comparisons are deliberately
# recorded but are not role, population, or outcome authorities.  Keeping them
# outside ZERO_GATE_FIELDS prevents harmless representation differences from
# discarding an otherwise exactly reconciled game, while preserving their
# counts for audit and later diagnosis.
DIAGNOSTIC_GATE_FIELDS = (
    "api_white_username_mismatches",
    "api_black_username_mismatches",
)


def validate_opportunity_relation(
    connection: Any,
    relation_sql: str,
    sources: MonthSources,
) -> Mapping[str, int]:
    """Validate schema, row semantics, material equivalence, and ID equality."""

    observed_columns = relation_columns(connection, relation_sql)
    require(
        observed_columns == OUTPUT_COLUMNS,
        f"{sources.month}: output schema mismatch; expected {OUTPUT_COLUMNS}, "
        f"got {observed_columns}",
    )
    connection.execute("DROP VIEW IF EXISTS output_relation")
    connection.execute(
        f"CREATE TEMP VIEW output_relation AS SELECT * FROM {relation_sql}"
    )
    values = connection.execute(opportunity_gates_sql()).fetchone()
    gates = {name: int(value or 0) for name, value in zip(GATE_FIELDS, values)}
    expected = sources.expected_timeout_rows
    require(
        gates["rows"] == expected,
        f"{sources.month}: output rows {gates['rows']} != {expected}",
    )
    require(gates["nonmissing_ids"] == expected, f"{sources.month}: missing output IDs")
    require(gates["distinct_ids"] == expected, f"{sources.month}: duplicate output IDs")
    failures = {name: gates[name] for name in ZERO_GATE_FIELDS if gates[name] != 0}
    require(not failures, f"{sources.month}: scientific gates failed: {failures}")
    require(
        all(0 <= gates[name] <= expected for name in DIAGNOSTIC_GATE_FIELDS),
        f"{sources.month}: API/PGN username diagnostics are outside row bounds",
    )
    require(
        gates["timeout_draws"]
        == gates["outcome_kind_draws"] + gates["timeout_draws_no_mating_material"],
        f"{sources.month}: draw/material outcome identity failed",
    )
    require(
        gates["rows"]
        == gates["timeout_draws"]
        + gates["timeout_chooser_wins"]
        + gates["timeout_chooser_losses"],
        f"{sources.month}: outcome partition identity failed",
    )

    set_differences = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM (
                SELECT game_id FROM frozen_ids
                EXCEPT
                SELECT game_id FROM output_relation
            ))::BIGINT AS frozen_missing,
            (SELECT COUNT(*) FROM (
                SELECT game_id FROM output_relation
                EXCEPT
                SELECT game_id FROM frozen_ids
            ))::BIGINT AS output_extra
        """
    ).fetchone()
    require(
        tuple(int(value) for value in set_differences) == (0, 0),
        f"{sources.month}: exact Stage 04 set equality failed: {set_differences}",
    )

    if sources.block == "earlier":
        # The historical monthly layer retains only the final mating-material
        # flag, not the intermediate piece counts or point totals.  Therefore
        # equivalence is deliberately enforced on the retained flag after all
        # new material fields have been independently derived from FEN.
        reference = int(
            connection.execute(
                """
            SELECT COUNT(*)::BIGINT
            FROM output_relation o
            INNER JOIN candidate_norm c USING (game_id)
            WHERE
                o.chooser_has_mating_material
                    IS DISTINCT FROM c.reference_chooser_has_mating_material
            """
            ).fetchone()[0]
        )
        if reference != 0:
            # A compact material-signature table makes any genuine rule drift
            # immediately diagnosable without another broad filesystem audit.
            signature_rows = connection.execute(
                """
                SELECT
                    o.chooser_pawns,
                    o.chooser_knights,
                    o.chooser_bishops,
                    o.chooser_rooks,
                    o.chooser_queens,
                    c.reference_chooser_has_mating_material AS historical_flag,
                    o.chooser_has_mating_material AS recomputed_flag,
                    COUNT(*)::BIGINT AS rows
                FROM output_relation o
                INNER JOIN candidate_norm c USING (game_id)
                WHERE o.chooser_has_mating_material
                    IS DISTINCT FROM c.reference_chooser_has_mating_material
                GROUP BY ALL
                ORDER BY rows DESC, chooser_pawns, chooser_knights,
                         chooser_bishops, chooser_rooks, chooser_queens
                LIMIT 12
                """
            ).fetchall()
            raise ContractError(
                f"{sources.month}: recomputed mating-material flag differs from "
                f"historical layer for {reference} rows; top material signatures="
                f"{signature_rows}"
            )
        gates = dict(gates)
        gates["historical_mating_flag_mismatches"] = 0
    return gates


def validate_published_file(
    connection: Any,
    path: Path,
    sources: MonthSources,
) -> Mapping[str, int]:
    """Run the full relation gates on a materialized Parquet file."""

    relation = parquet_scan_sql((path,))
    return validate_opportunity_relation(connection, relation, sources)


def quarantine_partial_directories(
    output_root: Path, month: str, logger: EventLog
) -> None:
    """Move interrupted partial directories into a recoverable stale area."""

    stale_root = output_root / "_stale"
    for partial in sorted(output_root.glob(f".month={month}.partial.*")):
        stale_root.mkdir(parents=True, exist_ok=True)
        destination = stale_root / f"{partial.name}.{run_stamp()}"
        counter = 1
        while destination.exists():
            destination = stale_root / f"{partial.name}.{run_stamp()}.{counter}"
            counter += 1
        logger.emit(f"{month}: moving interrupted partial directory to {destination}")
        os.replace(partial, destination)


def reuse_completed_month(
    connection: Any,
    final_dir: Path,
    sources: MonthSources,
) -> Mapping[str, Any] | None:
    """Authenticate a completed checkpoint; return it or fail closed."""

    if not final_dir.exists():
        return None
    require(final_dir.is_dir(), f"published month path is not a directory: {final_dir}")
    success_path = final_dir / "_SUCCESS.json"
    require(success_path.is_file(), f"existing month lacks _SUCCESS.json: {final_dir}")
    success = read_json(success_path)
    require(
        success.get("final_ok") is True, f"existing month is not final: {final_dir}"
    )
    require(
        success.get("month") == sources.month,
        f"existing month marker mismatch: {final_dir}",
    )
    require(
        success.get("script_version") == SCRIPT_VERSION,
        f"existing {sources.month} was built by a different Stage 05 version",
    )
    require(
        success.get("source_set_sha256") == sources.source_set_sha256,
        f"existing {sources.month} was built from a different source set",
    )
    output = final_dir / "timeout_opportunities.parquet"
    recorded = success.get("output", {})
    require(output.is_file(), f"existing month output is missing: {output}")
    observed_hash = sha256_file(output)
    require(
        observed_hash == recorded.get("sha256"),
        f"existing {sources.month} output hash mismatch",
    )
    gates = validate_published_file(connection, output, sources)
    require(
        gates == success.get("gates"), f"existing {sources.month} gate record changed"
    )
    return success


def build_month(
    connection: Any,
    sources: MonthSources,
    output_root: Path,
    logger: EventLog,
) -> Mapping[str, Any]:
    """Build, validate, and atomically publish one month or reuse its checkpoint."""

    final_dir = output_root / f"month={sources.month}"
    reused = reuse_completed_month(connection, final_dir, sources)
    if reused is not None:
        logger.emit(f"{sources.month}: authenticated completed checkpoint reused")
        return {"status": "reused", "success": reused}

    quarantine_partial_directories(output_root, sources.month, logger)
    partial = output_root / f".month={sources.month}.partial.{os.getpid()}"
    require(not partial.exists(), f"partial directory unexpectedly exists: {partial}")
    partial.mkdir(parents=False)
    output = partial / "timeout_opportunities.parquet"

    try:
        logger.emit(
            f"{sources.month}: enforcing source cardinality and exact timeout coverage"
        )
        preflight = preflight_month(connection, sources)
        if sources.block == "bridge":
            adapter = preflight["bridge_outcome_adapter"]
            logger.emit(
                f"{sources.month}: bridge outcome adapter authenticated; "
                f"stored is_draw disagreements="
                f"{adapter['stored_is_draw_disagreements']:,}; "
                f"winner-derived timeout draws={adapter['derived_timeout_draws']:,}"
            )
        select_sql = opportunity_select_sql(sources)

        # DESCRIBE validates the projected contract without materializing the
        # 47-million-row transform twice.  All row-level gates run against the
        # partial Parquet before it can be atomically published.
        projected_columns = relation_columns(connection, f"({select_sql})")
        require(
            projected_columns == OUTPUT_COLUMNS,
            f"{sources.month}: projected output schema changed: {projected_columns}",
        )
        logger.emit(
            f"{sources.month}: deriving roles, outcomes, material, and writing Parquet"
        )
        connection.execute(
            f"""
            COPY ({select_sql})
            TO {sql_string(output)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        require(output.is_file(), f"{sources.month}: DuckDB did not create output")
        gates = validate_published_file(connection, output, sources)
        logger.emit(
            f"{sources.month}: audited non-authoritative API/PGN username "
            f"differences: white={gates['api_white_username_mismatches']:,}, "
            f"black={gates['api_black_username_mismatches']:,}"
        )
        output_fingerprint = fingerprint(output)
        manifest = {
            "contract": "stage05_timeout_opportunity_month_v5",
            "script_version": SCRIPT_VERSION,
            "final_ok": True,
            "month": sources.month,
            "block": sources.block,
            "source_block": sources.source_block,
            "provenance_class": sources.provenance_class,
            "candidate_source_class": sources.candidate_source_class,
            "source_set_sha256": sources.source_set_sha256,
            "expected_timeout_rows": sources.expected_timeout_rows,
            "preflight": preflight,
            "gates": gates,
            "sources": {
                "frozen_timeout": asdict(sources.frozen_timeout),
                "candidate": asdict(sources.candidate),
                "api_files": [asdict(item) for item in sources.api_files],
                "authority_files": [asdict(item) for item in sources.authority_files],
            },
            "output": {
                **asdict(output_fingerprint),
                "relative_path": "timeout_opportunities.parquet",
                "columns": list(OUTPUT_COLUMNS),
            },
            "mating_material_rule": (
                "pawn>=1 OR rook>=1 OR queen>=1 OR bishops>=2 OR "
                "(bishops>=1 AND knights>=1) OR knights>=2"
            ),
            "historical_material_reference": (
                "Earlier monthly Parquets retain chooser_has_mating_material only; "
                "Stage 05 derives counts/points from FEN and requires exact flag "
                "equivalence."
            ),
            "player_identity_authority": {
                "role_authority": (
                    "PGN candidate chooser/disconnected fields, exactly checked "
                    "against PGN White/Black by color"
                ),
                "join_authority": (
                    "unique game_id with exact frozen Stage 04 set equality, API "
                    "status equality, and PGN/API color-result consistency"
                ),
                "api_username_role": (
                    "descriptive source metadata; normalized PGN differences are "
                    "preserved in gates as non-fatal diagnostics"
                ),
            },
            "bridge_outcome_adapter": (
                preflight.get("bridge_outcome_adapter")
                if sources.block == "bridge"
                else None
            ),
            "created_utc": utc_now(),
            "api_requests_performed": False,
        }
        atomic_write_json(partial / "month_manifest.json", manifest)
        atomic_write_json(partial / "_SUCCESS.json", manifest)
        require(
            not final_dir.exists(), f"final month appeared during build: {final_dir}"
        )
        os.replace(partial, final_dir)
        logger.emit(
            f"{sources.month}: published {gates['rows']:,} opportunities; "
            f"kind draws={gates['outcome_kind_draws']:,}"
        )
        return {"status": "built", "success": manifest}
    except Exception:
        # The partial is intentionally retained.  A future execute run moves it
        # into _stale, preserving evidence from the interrupted attempt.
        raise


def parse_months(value: str) -> tuple[str, ...]:
    """Parse ``all`` or a comma-separated locked-month subset."""

    if value.strip().lower() == "all":
        return LOCKED_MONTHS
    months = tuple(item.strip() for item in value.split(",") if item.strip())
    require(bool(months), "--months resolved to an empty list")
    require(len(months) == len(set(months)), "--months contains duplicates")
    invalid = [month for month in months if month not in LOCKED_MONTHS]
    require(not invalid, f"--months contains out-of-window months: {invalid}")
    # Canonical order prevents filesystem or user ordering from affecting output.
    requested = set(months)
    return tuple(month for month in LOCKED_MONTHS if month in requested)


def self_test(args: argparse.Namespace) -> int:
    """Exercise SQL normalization, material logic, schema, and outcome gates."""

    duckdb = load_duckdb()
    with tempfile.TemporaryDirectory(prefix="stage05_selftest_") as directory:
        root = Path(directory)
        connection = configure_connection(
            duckdb,
            database=":memory:",
            memory_limit="1GB",
            threads=1,
            temp_directory=root,
        )
        # Pure rule examples cover all scientifically important material cases.
        cases = [
            (0, 0, 0, 0, 0, False),
            (0, 1, 0, 0, 0, False),
            (0, 0, 1, 0, 0, False),
            # K+NN cannot force mate against K, but a legal mating position is
            # possible.  The locked historical layer therefore treats it as
            # mating material, and this exact case is production-gated.
            (0, 2, 0, 0, 0, True),
            (0, 3, 0, 0, 0, True),
            (0, 1, 1, 0, 0, True),
            (0, 0, 2, 0, 0, True),
            (1, 0, 0, 0, 0, True),
            (0, 0, 0, 1, 0, True),
            (0, 0, 0, 0, 1, True),
        ]
        connection.execute(
            "CREATE TABLE material_cases(chooser_pawns INTEGER, chooser_knights INTEGER, "
            "chooser_bishops INTEGER, chooser_rooks INTEGER, chooser_queens INTEGER, "
            "expected BOOLEAN)"
        )
        connection.executemany(
            "INSERT INTO material_cases VALUES (?, ?, ?, ?, ?, ?)", cases
        )
        mismatches = connection.execute(
            f"SELECT COUNT(*) FROM material_cases WHERE ({mating_material_sql()}) "
            "IS DISTINCT FROM expected"
        ).fetchone()[0]
        require(int(mismatches) == 0, "self-test mating-material cases failed")

        # Test the most error-prone normalization helpers independently.
        row = connection.execute(
            f"""
            SELECT
                {bool_sql("'TRUE'")},
                {bool_sql("'0'")},
                {color_sql("'W'")},
                {color_sql("'black'")},
                {name_norm_sql("'  Alice_1  '")},
                {finite_double_sql("'NaN'")},
                {finite_double_sql("'5.5'")}
            """
        ).fetchone()
        require(
            row == (True, False, "white", "black", "alice_1", None, 5.5),
            "self-test normalization failed",
        )
        connection.close()
    print("SELF-TEST PASS: material rule, normalization, and DuckDB contract helpers")
    return 0


def make_parser() -> argparse.ArgumentParser:
    """Construct the command-line interface."""

    parser = argparse.ArgumentParser(
        description="Build the frozen 24-month true timeout-opportunity panel."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--legacy-root",
        type=Path,
        default=Path("/Users/u6025368/projects/lichess_kindness"),
        help="Root containing the authenticated Aug-Oct 2025 candidate CSVs.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Override the canonical output root (mainly for isolated tests).",
    )
    parser.add_argument(
        "--months",
        default="all",
        help="all, or a comma-separated subset for checkpointed recovery.",
    )
    parser.add_argument("--memory-limit", default="8GB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--temp-directory", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def plan(args: argparse.Namespace) -> int:
    """Print a write-free execution plan and validate only cheap root contracts."""

    project_root = args.project_root.resolve()
    legacy_root = args.legacy_root.resolve()
    months = parse_months(args.months)
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else project_root / DEFAULT_OUTPUT_RELATIVE_ROOT
    )
    require(project_root.is_dir(), f"project root does not exist: {project_root}")
    require(legacy_root.is_dir(), f"legacy root does not exist: {legacy_root}")
    validate_stage04_summary(project_root)
    print("=" * 88)
    print("STAGE 05 PLAN — NO OUTPUT WRITES")
    print("=" * 88)
    print(f"Project root: {project_root}")
    print(f"Legacy root:  {legacy_root}")
    print(f"Output root:  {output_root}")
    print(f"Months:       {', '.join(months)}")
    print(f"Execute:      {args.execute}")
    print(f"Memory limit: {args.memory_limit}")
    print(f"DuckDB threads: {args.threads}")
    print()
    print("Population authority: frozen Stage 04 timeout IDs")
    print("Full expected rows: 47,587,020")
    print("API calls: impossible (no network code)")
    print("Estimated full runtime: normally 30–90 minutes; up to two hours")
    print("Estimated temporary free space: 20–50 GB")
    print()
    print("Rerun with --execute to build and publish monthly Parquets.")
    return 0


def execute(args: argparse.Namespace) -> int:
    """Run the authenticated, checkpointed Stage 05 production build."""

    started = time.monotonic()
    project_root = args.project_root.resolve()
    legacy_root = args.legacy_root.resolve()
    months = parse_months(args.months)
    require(project_root.is_dir(), f"project root does not exist: {project_root}")
    require(legacy_root.is_dir(), f"legacy root does not exist: {legacy_root}")
    require(args.threads >= 1, "--threads must be at least 1")
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else project_root / DEFAULT_OUTPUT_RELATIVE_ROOT
    )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_root = output_root / "_manifests"
    run_root = manifest_root / "runs" / f"{run_stamp()}_{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=False)
    logger = EventLog(run_root / "run.log")
    duckdb = load_duckdb()

    temp_directory = (
        args.temp_directory.resolve()
        if args.temp_directory is not None
        else output_root / "_duckdb_tmp"
    )
    temp_directory.mkdir(parents=True, exist_ok=True)
    database = str(run_root / "stage05.duckdb")
    connection = configure_connection(
        duckdb,
        database=database,
        memory_limit=args.memory_limit,
        threads=args.threads,
        temp_directory=temp_directory,
    )

    command = [sys.executable, *sys.argv]
    atomic_write_json(
        run_root / "run_config.json",
        {
            "started_utc": utc_now(),
            "command": shlex.join(command),
            "project_root": str(project_root),
            "legacy_root": str(legacy_root),
            "output_root": str(output_root),
            "months": list(months),
            "memory_limit": args.memory_limit,
            "threads": args.threads,
            "temp_directory": str(temp_directory),
            "execute": True,
            "api_requests_performed": False,
        },
    )
    atomic_write_json(run_root / "software_versions.json", software_versions(duckdb))

    try:
        logger.emit("STAGE 05 TIMEOUT-OPPORTUNITY BUILD STARTED")
        logger.emit("Safety: no API calls; Stage 01 and Stage 04 inputs are read-only")
        logger.emit("Authenticating frozen 24-month Stage 04 authority")
        stage04_rows = validate_stage04_summary(project_root)

        month_rows: list[Mapping[str, Any]] = []
        for ordinal, month in enumerate(months, start=1):
            logger.emit(f"Resolving month {ordinal}/{len(months)}: {month}")
            sources = resolve_month_sources(
                month,
                project_root=project_root,
                legacy_root=legacy_root,
                stage04_row=stage04_rows[month],
                logger=logger,
            )
            # Views must exist before a completed output can be fully
            # revalidated, so install them once before build/reuse dispatch.
            install_source_views(connection, sources)
            result = build_month(
                connection=connection,
                sources=sources,
                output_root=output_root,
                logger=logger,
            )
            success = result["success"]
            gates = success["gates"]
            bridge_adapter = success["preflight"].get("bridge_outcome_adapter") or {}
            month_rows.append(
                {
                    "month": month,
                    "block": sources.block,
                    "run_status": result["status"],
                    "final_ok": success["final_ok"],
                    "opportunity_rows": gates["rows"],
                    "timeout_draws": gates["timeout_draws"],
                    "timeout_chooser_wins": gates["timeout_chooser_wins"],
                    "timeout_chooser_losses": gates["timeout_chooser_losses"],
                    "outcome_kind_draws": gates["outcome_kind_draws"],
                    "timeout_draws_no_mating_material": gates[
                        "timeout_draws_no_mating_material"
                    ],
                    "missing_disconnected_clock_rows": gates[
                        "missing_disconnected_clock_rows"
                    ],
                    "api_white_username_mismatches": gates[
                        "api_white_username_mismatches"
                    ],
                    "api_black_username_mismatches": gates[
                        "api_black_username_mismatches"
                    ],
                    "bridge_stored_is_draw_disagreements": bridge_adapter.get(
                        "stored_is_draw_disagreements", 0
                    ),
                    "bridge_derived_timeout_draws": bridge_adapter.get(
                        "derived_timeout_draws", 0
                    ),
                    "source_set_sha256": sources.source_set_sha256,
                    "output_path": str(
                        output_root / f"month={month}" / "timeout_opportunities.parquet"
                    ),
                    "output_sha256": success["output"]["sha256"],
                }
            )

        fields = (
            "month",
            "block",
            "run_status",
            "final_ok",
            "opportunity_rows",
            "timeout_draws",
            "timeout_chooser_wins",
            "timeout_chooser_losses",
            "outcome_kind_draws",
            "timeout_draws_no_mating_material",
            "missing_disconnected_clock_rows",
            "api_white_username_mismatches",
            "api_black_username_mismatches",
            "bridge_stored_is_draw_disagreements",
            "bridge_derived_timeout_draws",
            "source_set_sha256",
            "output_path",
            "output_sha256",
        )
        write_csv(run_root / "month_status.csv", month_rows, fields)
        atomic_write_text(
            run_root / "timeout_opportunity_paths.txt",
            "".join(str(row["output_path"]) + "\n" for row in month_rows),
        )

        requested_total = sum(int(row["opportunity_rows"]) for row in month_rows)
        all_months = months == LOCKED_MONTHS
        if all_months:
            require(
                requested_total == EXPECTED_TOTAL_TIMEOUT,
                f"global opportunity total {requested_total} != {EXPECTED_TOTAL_TIMEOUT}",
            )
            observed_blocks = {
                block: sum(
                    int(row["opportunity_rows"])
                    for row in month_rows
                    if row["block"] == block
                )
                for block in ("earlier", "bridge", "late")
            }
            require(
                observed_blocks == dict(EXPECTED_BLOCK_TIMEOUTS),
                f"Stage 05 block totals failed: {observed_blocks}",
            )
        else:
            observed_blocks = {
                block: sum(
                    int(row["opportunity_rows"])
                    for row in month_rows
                    if row["block"] == block
                )
                for block in ("earlier", "bridge", "late")
            }

        summary = {
            "final_ok": all_months,
            "technical_status": "complete"
            if all_months
            else "requested_subset_complete",
            "decision": (
                "STAGE05_24M_TIMEOUT_OPPORTUNITY_PANEL_FROZEN"
                if all_months
                else "STAGE05_REQUESTED_MONTH_SUBSET_COMPLETE__GLOBAL_NOT_FROZEN"
            ),
            "analysis_authorization": (
                "PROCEED_TO_STAGE06_GLICKO2_COST_LAYER"
                if all_months
                else "NO_GLOBAL_AUTHORIZATION"
            ),
            "finished_utc": utc_now(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "locked_sample_start": LOCKED_SAMPLE_START,
            "locked_sample_end": LOCKED_SAMPLE_END,
            "months": list(months),
            "month_count": len(months),
            "full_month_count": 24,
            "total_timeout_opportunities": requested_total,
            "expected_full_timeout_opportunities": EXPECTED_TOTAL_TIMEOUT,
            "timeout_draws": sum(int(row["timeout_draws"]) for row in month_rows),
            "timeout_chooser_wins": sum(
                int(row["timeout_chooser_wins"]) for row in month_rows
            ),
            "timeout_chooser_losses": sum(
                int(row["timeout_chooser_losses"]) for row in month_rows
            ),
            "outcome_kind_draws": sum(
                int(row["outcome_kind_draws"]) for row in month_rows
            ),
            "timeout_draws_no_mating_material": sum(
                int(row["timeout_draws_no_mating_material"]) for row in month_rows
            ),
            "missing_disconnected_clock_rows": sum(
                int(row["missing_disconnected_clock_rows"]) for row in month_rows
            ),
            "api_white_username_mismatches": sum(
                int(row["api_white_username_mismatches"]) for row in month_rows
            ),
            "api_black_username_mismatches": sum(
                int(row["api_black_username_mismatches"]) for row in month_rows
            ),
            "bridge_stored_is_draw_disagreements": sum(
                int(row["bridge_stored_is_draw_disagreements"]) for row in month_rows
            ),
            "bridge_derived_timeout_draws": sum(
                int(row["bridge_derived_timeout_draws"]) for row in month_rows
            ),
            "block_totals": observed_blocks,
            "global_id_uniqueness": {
                "status": "inherited_by_exact_month_set_equality",
                "stage04_duplicate_game_ids": 0,
                "reason": (
                    "Every Stage 05 month is exactly set-equal to its frozen Stage 04 "
                    "timeout partition; Stage 04 proved global uniqueness."
                ),
            },
            "api_refetch_performed": False,
            "output_root": str(output_root),
            "monthly_funnel": month_rows,
            "next_step": (
                "Build the canonical 24-month v2 Glicko-2 chooser cost/payoff layer."
                if all_months
                else "Run or resume all 24 months before proceeding downstream."
            ),
        }
        atomic_write_json(run_root / "summary.json", summary)
        atomic_write_json(run_root / "_SUCCESS.json", summary)
        if all_months:
            write_csv(manifest_root / "month_status.csv", month_rows, fields)
            atomic_write_text(
                manifest_root / "timeout_opportunity_paths.txt",
                "".join(str(row["output_path"]) + "\n" for row in month_rows),
            )
            atomic_write_json(manifest_root / "latest_summary.json", summary)
            atomic_write_text(
                manifest_root / "latest_run_path.txt", str(run_root) + "\n"
            )
            atomic_write_json(output_root / "_SUCCESS.json", summary)
            logger.emit("STAGE 05: TECHNICALLY COMPLETE AND FROZEN")
            logger.emit(f"True timeout opportunities: {requested_total:,}")
            logger.emit(f"Kind draws: {summary['outcome_kind_draws']:,}")
            logger.emit("Decision: STAGE05_24M_TIMEOUT_OPPORTUNITY_PANEL_FROZEN")
        else:
            logger.emit(
                "STAGE 05 requested subset complete; global layer is not yet frozen"
            )
        logger.emit(f"Run manifest: {run_root}")
        connection.close()
        return 0
    except Exception as exc:
        failure = {
            "final_ok": False,
            "failed_utc": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "api_requests_performed": False,
            "output_root": str(output_root),
        }
        atomic_write_json(run_root / "failure.json", failure)
        logger.emit(f"FAILED CLOSED: {type(exc).__name__}: {exc}")
        try:
            connection.close()
        except Exception:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """Command entry point."""

    parser = make_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test(args)
    if args.execute:
        return execute(args)
    return plan(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
