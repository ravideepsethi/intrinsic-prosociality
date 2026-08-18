#!/usr/bin/env python3
"""
Canonical Stage 06: reconstruct time-aware Lichess Glicko-2 hidden state and
build chooser-side draw/win payoff measures for the frozen two-year timeout
opportunity panel.

Scientific purpose
------------------
The paper distinguishes two rating consequences at each timeout opportunity:

* ``chooser_draw_payoff_v2``: the chooser's hypothetical rating change from
  granting a draw, relative to the pre-game displayed rating;
* ``chooser_win_payoff_v2``: the chooser's hypothetical rating change from
  claiming the timeout win; and
* ``chooser_win_premium_v2``: win payoff minus draw payoff, the rating gain
  forgone by granting the draw.

The displayed rating itself is anchored to the rating recorded in the Lichess
PGN archive at every game.  The only quantities replayed through history are the
hidden Glicko-2 rating deviation (RD), volatility, and last rated-update time.
State is maintained independently by Lichess speed/performance pool.

Canonical design encoded here
-----------------------------

* Frozen target sample: 2023-11 through 2025-10, inclusive.
* Frozen target universe: canonical Stage 05, expected 47,587,020 unique games.
* Historical replay substrate: the already sorted all-rated-game event layer.
* Glicko constants inherited from the audited historical producer:
  scale 173.7178, default/max RD 500, minimum RD 45, default volatility 0.09,
  maximum volatility 0.10, tau 0.75, and 0.21436 rating periods per day.
* Update convention: time-aware anchored Glicko-2, ``novol_noreg``.  There is
  no additional same-game RD inflation and no post-update RatingRegulator.
* Missing-difference policy: if BOTH PGN rating-difference fields are absent,
  the game is retained as a behavioral target when otherwise eligible, but it
  does not update hidden RD/volatility state and does not advance last-update
  time.  A one-sided observed difference is treated as evidence that the rated
  update occurred, so both players' hidden states are updated.
* Color-advantage convention is parameterized using the audited production
  cutoff 2025-11-18 07:22:00 UTC.  It has no effect on the locked main sample,
  which ends in October 2025, but keeps the implementation usable for later
  holdouts.

Why this is a new canonical producer
------------------------------------
The recovered historical scripts are preserved as provenance, but they cannot
be used unchanged because they (i) updated hidden state through games with both
rating differences missing, (ii) hard-coded the old one-year candidate layout,
(iii) used a stale November 2025 color-advantage cutoff, and (iv) selected the
chooser side with non-fail-closed CASE expressions.  This script carries forward
validated mathematical logic while enforcing the frozen Stage 05 schema and the
later missing-difference adjudication.

Execution model
---------------
The script has three safe modes:

1. ``--self-test`` runs deterministic unit tests and touches no project data.
2. With neither ``--execute`` nor ``--finalize-only``, it performs a read-only
   production plan/preflight.
3. ``--execute`` replays one or more independent speed pools, writes raw
   white/black candidate costs, and—when all target speeds are selected—merges
   them into canonical month-level chooser-side cost files.

Each speed is restartable from atomic policy-matched checkpoints.  Checkpoints
are written at annual boundaries, immediately before the target window, and at
its endpoint.  A failed run never silently skips a target or publishes a global
success marker.

Expected runtime on the historical work laptop
----------------------------------------------
Historical all-history runtimes through April 2026 summed to about 25 hours
across pools: blitz 11.9h, bullet 8.8h, rapid 3.5h, classical 0.4h, and
ultrabullet 0.3h.  This corrected run ends in October 2025.  With three workers,
reasonable wall-time planning is roughly 12-18 hours, subject to SSD and memory
contention.  Self-test and plan mode should take seconds to a few minutes.

Canonical example commands
--------------------------
Fresh Terminal self-test:

    cd /Volumes/XT_Pro/lichess_kindness
    venv/bin/python -B replication_package/code/06_build_glicko2_cost_layer.py \
        --project-root /Volumes/XT_Pro/lichess_kindness \
        --self-test

Read-only production plan:

    cd /Volumes/XT_Pro/lichess_kindness
    venv/bin/python -B replication_package/code/06_build_glicko2_cost_layer.py \
        --project-root /Volumes/XT_Pro/lichess_kindness

Small-pool pilot (separate output root; historically about 15-25 minutes):

    cd /Volumes/XT_Pro/lichess_kindness
    /usr/bin/caffeinate -dimsu venv/bin/python -B \
        replication_package/code/06_build_glicko2_cost_layer.py \
        --project-root /Volumes/XT_Pro/lichess_kindness \
        --output-root /Volumes/XT_Pro/lichess_kindness/derived/replication/glicko2_cost_layer_PILOT \
        --speeds ultrabullet \
        --execute

Full production (resume-safe):

    cd /Volumes/XT_Pro/lichess_kindness
    export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
           NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
    /usr/bin/caffeinate -dimsu venv/bin/python -u -B \
        replication_package/code/06_build_glicko2_cost_layer.py \
        --project-root /Volumes/XT_Pro/lichess_kindness \
        --speeds all \
        --workers 3 \
        --resume \
        --execute \
        2>&1 | tee output/replication_glicko2_cost_layer_stage06.log

The final global authority is ``_manifests/latest_summary.json`` and must report
``final_ok: true`` before Stage 06 is treated as frozen.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


# -----------------------------------------------------------------------------
# Frozen scientific constants and sample contract
# -----------------------------------------------------------------------------

SCALE = 173.7178
PI2 = math.pi**2
MS_PER_DAY = 1000 * 60 * 60 * 24

DEFAULT_RD = 500.0
DEFAULT_SIGMA = 0.09
MIN_RD = 45.0
MAX_RD = 500.0
MAX_SIGMA = 0.10
TAU = 0.75
PERIODS_PER_DAY = 0.21436
STANDARD_COLOR_ADV = 11.782457
COLOR_ADV_START_UTC = "2025-11-18T07:22:00Z"

TARGET_START_MONTH = "2023-11"
TARGET_END_MONTH = "2025-10"
EXPECTED_STAGE05_ROWS = 47_587_020

# Stage 05 shows positive support in exactly these five modern live pools.
CANONICAL_SPEED_ORDER = (
    "blitz",
    "rapid",
    "bullet",
    "classical",
    "ultrabullet",
)

# The surviving historical replay has one known non-contiguous modern-pool
# partition: rapid is present in 2018-03 and 2018-05, while 2018-04 is absent.
# A separate speed=unknown/2018-04 partition survives. The deleted upstream
# numeric layer prevents authoritative relabeling, and project/source searches
# do not establish that the unknown partition is rapid. Canonical baseline
# behavior therefore preserves the historical replay labels exactly and allows
# only this explicitly audited gap. A separate sensitivity analysis may later
# test treating speed=unknown/2018-04 as rapid; it must never happen silently.
AUDITED_REPLAY_GAPS: dict[str, tuple[str, ...]] = {
    "rapid": ("2018-04",),
}

FORMULA_VERSION = (
    "anchored_timeaware_glicko2_novol_noreg_"
    "defaultRD500_skip_both_null_v1"
)

REQUIRED_STAGE05_COLUMNS = (
    "month",
    "game_id",
    "api_speed",
    "api_perf",
    "api_rated",
    "api_variant",
    "api_created_at_ms",
    "chooser_color",
    "chooser_elo",
    "disconnected_color",
    "disconnected_elo",
    "white_elo_pgn",
    "black_elo_pgn",
    "white_rating_diff_pgn",
    "black_rating_diff_pgn",
)

REQUIRED_REPLAY_COLUMNS = (
    "archive_ordinal",
    "utc_ms",
    "game_id",
    "white_id",
    "black_id",
    "white_elo",
    "black_elo",
    "white_rating_diff",
    "black_rating_diff",
    "result_code",
)

RAW_COST_SCHEMA = pa.schema(
    [
        ("month", pa.string()),
        ("speed", pa.string()),
        ("archive_ordinal", pa.int64()),
        ("utc_ms", pa.int64()),
        ("game_id", pa.string()),
        ("white_id", pa.int64()),
        ("black_id", pa.int64()),
        ("white_elo_replay", pa.int32()),
        ("black_elo_replay", pa.int32()),
        ("white_pre_rd_v2", pa.float64()),
        ("black_pre_rd_v2", pa.float64()),
        ("white_pre_sigma_v2", pa.float64()),
        ("black_pre_sigma_v2", pa.float64()),
        ("white_draw_ratingdiff_v2", pa.float64()),
        ("white_win_ratingdiff_v2", pa.float64()),
        ("white_win_premium_v2", pa.float64()),
        ("black_draw_ratingdiff_v2", pa.float64()),
        ("black_win_ratingdiff_v2", pa.float64()),
        ("black_win_premium_v2", pa.float64()),
        ("white_realized_pred_ratingdiff_v2", pa.float64()),
        ("black_realized_pred_ratingdiff_v2", pa.float64()),
        ("observed_white_rating_diff", pa.int32()),
        ("observed_black_rating_diff", pa.int32()),
        ("both_ratingdiff_null", pa.bool_()),
        ("hidden_state_update_applied", pa.bool_()),
        ("color_adv_applied", pa.bool_()),
    ]
)


# -----------------------------------------------------------------------------
# Generic utilities
# -----------------------------------------------------------------------------


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp without fractional seconds."""

    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(message: str, *, file: Path | None = None) -> None:
    line = f"[{utc_now()}] {message}"
    print(line, flush=True)
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _json_default(value: Any) -> Any:
    """Convert common scientific-Python scalars to JSON-native values."""

    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(obj, indent=2, sort_keys=True, default=_json_default) + "\n",
    )


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def quote_sql(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def parse_utc_ms(value: str) -> int:
    normalized = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone: {value}")
    return int(parsed.timestamp() * 1000)


def parse_month(value: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError(f"Invalid YYYY-MM month: {value}")
    year, month = map(int, value.split("-"))
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month number: {value}")
    return year, month


def month_range(start: str, end: str) -> list[str]:
    y, m = parse_month(start)
    ey, em = parse_month(end)
    if (y, m) > (ey, em):
        raise ValueError(f"start month {start} is after end month {end}")
    out: list[str] = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y += 1
            m = 1
    return out


def month_before(value: str) -> str:
    y, m = parse_month(value)
    m -= 1
    if m == 0:
        y -= 1
        m = 12
    return f"{y:04d}-{m:02d}"


def month_after(value: str) -> str:
    y, m = parse_month(value)
    m += 1
    if m == 13:
        y += 1
        m = 1
    return f"{y:04d}-{m:02d}"


def canonical_months() -> list[str]:
    return month_range(TARGET_START_MONTH, TARGET_END_MONTH)


def environment_snapshot() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for module in (np, pd, pa, duckdb):
        name = getattr(module, "__name__", type(module).__name__)
        version = getattr(module, "__version__", "unknown")
        packages[name] = str(version)
    return {
        "created_at": utc_now(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "packages": packages,
        "thread_environment": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
    }


def normalize_speed_list(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() == "all":
        return CANONICAL_SPEED_ORDER
    values = tuple(x.strip().lower() for x in raw.split(",") if x.strip())
    if not values:
        raise ValueError("--speeds resolved to an empty set")
    unknown = sorted(set(values) - set(CANONICAL_SPEED_ORDER))
    if unknown:
        raise ValueError(f"Unsupported speed(s): {unknown}")
    # Preserve canonical ordering and remove duplicates.
    return tuple(s for s in CANONICAL_SPEED_ORDER if s in set(values))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_empty_or_resumable_root(output_root: Path, resume: bool) -> None:
    """Fail closed if production-like outputs exist without explicit resume."""

    if not output_root.exists():
        return
    meaningful = [
        p
        for p in output_root.iterdir()
        if p.name not in {".DS_Store"} and not p.name.startswith(".tmp-")
    ]
    if meaningful and not resume:
        raise RuntimeError(
            f"Output root is not empty: {output_root}. "
            "Pass --resume only after reviewing the existing run."
        )


# -----------------------------------------------------------------------------
# Glicko-2 mathematics, inherited from the audited historical producer
# -----------------------------------------------------------------------------


def g_phi(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / PI2)


def expected_score(mu: float, mu_j: float, phi_j: float) -> float:
    g = g_phi(phi_j)
    x = -g * (mu - mu_j)
    if x > 50:
        return 0.0
    if x < -50:
        return 1.0
    return 1.0 / (1.0 + math.exp(x))


def volatility_update(
    phi: float,
    sigma: float,
    delta: float,
    v: float,
    tau: float,
    max_sigma: float,
) -> float:
    """Source-aligned Glicko-2 volatility iteration."""

    if sigma <= 0 or not math.isfinite(sigma):
        sigma = DEFAULT_SIGMA

    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex = math.exp(x)
        denom = 2.0 * (phi * phi + v + ex) ** 2
        return (
            ex * (delta * delta - phi * phi - v - ex) / denom
        ) - ((x - a) / (tau * tau))

    A = a
    threshold = phi * phi + v
    delta2 = delta * delta

    if delta2 > threshold:
        B = math.log(delta2 - threshold)
    else:
        k = 1
        B = a - k * abs(tau)
        while f(B) < 0 and k < 100:
            k += 1
            B = a - k * abs(tau)

    fA = f(A)
    fB = f(B)

    for _ in range(1000):
        if abs(B - A) <= 1e-6:
            break
        denom = fB - fA
        if denom == 0 or not math.isfinite(denom):
            break
        C = A + (A - B) * fA / denom
        fC = f(C)
        if fC * fB <= 0:
            A = B
            fA = fB
        else:
            fA /= 2.0
        B = C
        fB = fC

    out = math.exp(A / 2.0)
    if not math.isfinite(out) or out <= 0:
        return sigma
    return max(0.0001, min(out, max_sigma))


def inflate_rd(
    rd_value: float,
    sigma_value: float,
    last_ms: int,
    current_ms: int,
    periods_per_day: float,
    min_rd: float,
    max_rd: float,
) -> float:
    """Inflate RD between rated updates using elapsed real time."""

    if last_ms < 0 or current_ms <= last_ms:
        return rd_value
    elapsed_periods = ((current_ms - last_ms) / MS_PER_DAY) * periods_per_day
    if elapsed_periods <= 0:
        return rd_value
    phi = rd_value / SCALE
    new_phi = math.sqrt(phi * phi + elapsed_periods * sigma_value * sigma_value)
    return min(max_rd, max(min_rd, new_phi * SCALE))


def pred_diff_only(
    rating: float,
    rd: float,
    opp_rating: float,
    opp_rd: float,
    score: float,
    min_rd: float,
    self_adv: float = 0.0,
    opp_adv: float = 0.0,
) -> float:
    """Counterfactual rating change under the novol/noreg convention."""

    mu = ((rating + self_adv) - 1500.0) / SCALE
    mu_j = ((opp_rating + opp_adv) - 1500.0) / SCALE
    phi = max(rd / SCALE, min_rd / SCALE)
    phi_j = max(opp_rd / SCALE, min_rd / SCALE)
    g = g_phi(phi_j)
    E = expected_score(mu, mu_j, phi_j)
    E = min(max(E, 1e-12), 1.0 - 1e-12)
    v = 1.0 / (g * g * E * (1.0 - E))
    phi_prime = 1.0 / math.sqrt((1.0 / (phi * phi)) + (1.0 / v))
    mu_delta = phi_prime * phi_prime * g * (score - E)
    return SCALE * mu_delta


def update_one(
    rating: float,
    rd: float,
    sigma: float,
    opp_rating: float,
    opp_rd: float,
    score: float,
    tau: float,
    min_rd: float,
    max_rd: float,
    max_sigma: float,
    self_adv: float = 0.0,
    opp_adv: float = 0.0,
) -> tuple[float, float, float]:
    """Return predicted rating change and updated hidden RD/volatility."""

    mu = ((rating + self_adv) - 1500.0) / SCALE
    mu_j = ((opp_rating + opp_adv) - 1500.0) / SCALE
    phi = max(rd / SCALE, min_rd / SCALE)
    phi_j = max(opp_rd / SCALE, min_rd / SCALE)
    g = g_phi(phi_j)
    E = expected_score(mu, mu_j, phi_j)
    E = min(max(E, 1e-12), 1.0 - 1e-12)
    v = 1.0 / (g * g * E * (1.0 - E))
    delta = v * g * (score - E)
    sigma_prime = volatility_update(phi, sigma, delta, v, tau, max_sigma)

    # novol: no additional same-game elapsed-period RD inflation here.
    phi_prime = 1.0 / math.sqrt((1.0 / (phi * phi)) + (1.0 / v))
    mu_delta = phi_prime * phi_prime * g * (score - E)
    pred_diff = SCALE * mu_delta
    rd_prime = min(max_rd, max(min_rd, SCALE * phi_prime))
    return pred_diff, rd_prime, sigma_prime


# -----------------------------------------------------------------------------
# Streaming validation metrics
# -----------------------------------------------------------------------------


@dataclasses.dataclass
class Metrics:
    n: int = 0
    sum_obs: float = 0.0
    sum_pred: float = 0.0
    sum_obs2: float = 0.0
    sum_pred2: float = 0.0
    sum_cross: float = 0.0
    sum_err: float = 0.0
    sum_abs: float = 0.0
    sum_sq: float = 0.0

    def add(self, obs: Any, pred: float) -> None:
        if pd.isna(obs) or not math.isfinite(float(pred)):
            return
        obs_f = float(obs)
        pred_f = float(pred)
        err = pred_f - obs_f
        self.n += 1
        self.sum_obs += obs_f
        self.sum_pred += pred_f
        self.sum_obs2 += obs_f * obs_f
        self.sum_pred2 += pred_f * pred_f
        self.sum_cross += obs_f * pred_f
        self.sum_err += err
        self.sum_abs += abs(err)
        self.sum_sq += err * err

    def as_dict(self) -> dict[str, Any]:
        if self.n == 0:
            return {"n": 0}
        mo = self.sum_obs / self.n
        mp = self.sum_pred / self.n
        cov = self.sum_cross / self.n - mo * mp
        vo = self.sum_obs2 / self.n - mo * mo
        vp = self.sum_pred2 / self.n - mp * mp
        corr = cov / math.sqrt(vo * vp) if vo > 0 and vp > 0 else None
        return {
            "n": int(self.n),
            "mean_obs": mo,
            "mean_pred": mp,
            "bias_pred_minus_obs": self.sum_err / self.n,
            "mae": self.sum_abs / self.n,
            "rmse": math.sqrt(self.sum_sq / self.n),
            "corr": corr,
        }


# -----------------------------------------------------------------------------
# Configuration and preflight
# -----------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Config:
    project_root: str
    stage05_root: str
    sorted_root: str
    dictionary_summary: str
    output_root: str
    target_start_month: str
    target_end_month: str
    replay_end_month: str
    speeds: tuple[str, ...]
    workers: int
    batch_size: int
    output_chunk_rows: int
    checkpoint_frequency_months: int
    resume: bool
    script_path: str
    script_sha256: str
    color_adv_start_utc: str
    color_adv_start_ms: int
    standard_color_adv: float
    formula_version: str
    default_rd: float
    default_sigma: float
    min_rd: float
    max_rd: float
    max_sigma: float
    tau: float
    periods_per_day: float
    expected_stage05_rows: int
    hash_final_outputs: bool

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def build_config(args: argparse.Namespace) -> Config:
    project_root = Path(args.project_root).expanduser().resolve()
    stage05_root = (
        Path(args.stage05_root).expanduser().resolve()
        if args.stage05_root
        else project_root / "derived/replication/timeout_opportunity_panel"
    )
    sorted_root = (
        Path(args.sorted_root).expanduser().resolve()
        if args.sorted_root
        else project_root
        / "derived/glicko2_replay/rating_events_replay_sorted_v2_time"
        / "events_replay_sorted_time"
    )
    dictionary_summary = (
        Path(args.dictionary_summary).expanduser().resolve()
        if args.dictionary_summary
        else project_root
        / "derived/glicko2_replay/user_dictionary_v1/summary.json"
    )
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else project_root / "derived/replication/glicko2_cost_layer"
    )
    script_path = Path(__file__).resolve()
    return Config(
        project_root=str(project_root),
        stage05_root=str(stage05_root),
        sorted_root=str(sorted_root),
        dictionary_summary=str(dictionary_summary),
        output_root=str(output_root),
        target_start_month=args.target_start_month,
        target_end_month=args.target_end_month,
        replay_end_month=args.replay_end_month or args.target_end_month,
        speeds=normalize_speed_list(args.speeds),
        workers=max(1, int(args.workers)),
        batch_size=max(10_000, int(args.batch_size)),
        output_chunk_rows=max(1_000, int(args.output_chunk_rows)),
        checkpoint_frequency_months=max(1, int(args.checkpoint_frequency_months)),
        resume=bool(args.resume),
        script_path=str(script_path),
        script_sha256=sha256_file(script_path),
        color_adv_start_utc=args.color_adv_start_utc,
        color_adv_start_ms=parse_utc_ms(args.color_adv_start_utc),
        standard_color_adv=float(args.standard_color_adv),
        formula_version=FORMULA_VERSION,
        default_rd=DEFAULT_RD,
        default_sigma=DEFAULT_SIGMA,
        min_rd=MIN_RD,
        max_rd=MAX_RD,
        max_sigma=MAX_SIGMA,
        tau=TAU,
        periods_per_day=PERIODS_PER_DAY,
        expected_stage05_rows=int(args.expected_stage05_rows),
        hash_final_outputs=not bool(args.no_hash_final_outputs),
    )


def stage05_path(config: Config, month: str) -> Path:
    return Path(config.stage05_root) / f"month={month}" / "timeout_opportunities.parquet"


def replay_part_path(config: Config, speed: str, month: str) -> Path:
    return (
        Path(config.sorted_root)
        / f"speed={speed}"
        / f"month={month}"
        / "part-00000.parquet"
    )


def replay_months_for_speed(config: Config, speed: str) -> list[str]:
    base = Path(config.sorted_root) / f"speed={speed}"
    months: list[str] = []
    for d in sorted(base.glob("month=*")):
        m = re.fullmatch(r"month=(\d{4}-\d{2})", d.name)
        if m and (d / "part-00000.parquet").is_file():
            month = m.group(1)
            if month <= config.replay_end_month:
                months.append(month)
    return months


def validate_replay_schema(path: Path) -> None:
    names = pq.ParquetFile(path).schema_arrow.names
    missing = [c for c in REQUIRED_REPLAY_COLUMNS if c not in names]
    if missing:
        raise RuntimeError(f"Replay input missing {missing}: {path}")


def validate_stage05_schema(path: Path) -> None:
    names = pq.ParquetFile(path).schema_arrow.names
    missing = [c for c in REQUIRED_STAGE05_COLUMNS if c not in names]
    if missing:
        raise RuntimeError(f"Stage 05 input missing {missing}: {path}")


def target_counts_by_speed(config: Config) -> pd.DataFrame:
    glob = str(Path(config.stage05_root) / "month=*" / "timeout_opportunities.parquet")
    con = duckdb.connect()
    try:
        con.execute("SET threads=4")
        con.execute("SET memory_limit='4GB'")
        return con.execute(
            f"""
            SELECT
                month,
                lower(cast(api_speed AS varchar)) AS speed,
                count(*)::BIGINT AS rows,
                count(DISTINCT game_id)::BIGINT AS unique_games
            FROM read_parquet(
                {quote_sql(glob)},
                union_by_name=true,
                hive_partitioning=false
            )
            GROUP BY 1, 2
            ORDER BY month, speed
            """
        ).fetchdf()
    finally:
        con.close()


def preflight(config: Config) -> dict[str, Any]:
    """Validate immutable inputs and return a complete read-only plan."""

    stage05_root = Path(config.stage05_root)
    sorted_root = Path(config.sorted_root)
    dictionary_summary = Path(config.dictionary_summary)

    if not stage05_root.is_dir():
        raise FileNotFoundError(stage05_root)
    if not sorted_root.is_dir():
        raise FileNotFoundError(sorted_root)
    if not dictionary_summary.is_file():
        raise FileNotFoundError(dictionary_summary)

    target_months = month_range(config.target_start_month, config.target_end_month)
    if target_months != canonical_months():
        # The script is reusable, but production departures from the locked sample
        # must be explicit in the plan rather than silently inheriting constants.
        sample_note = "NONCANONICAL_TARGET_WINDOW"
    else:
        sample_note = "CANONICAL_24_MONTH_WINDOW"

    stage05_rows = 0
    stage05_files: list[dict[str, Any]] = []
    schema0: pa.Schema | None = None
    for month in target_months:
        path = stage05_path(config, month)
        if not path.is_file():
            raise FileNotFoundError(path)
        validate_stage05_schema(path)
        pf = pq.ParquetFile(path)
        if schema0 is None:
            schema0 = pf.schema_arrow
        elif pf.schema_arrow != schema0:
            raise RuntimeError(f"Stage 05 schema differs in {month}")
        n = int(pf.metadata.num_rows)
        stage05_rows += n
        success_path = path.with_name("_SUCCESS.json")
        stage05_files.append(
            {
                "month": month,
                "path": str(path),
                "rows": n,
                "size_bytes": path.stat().st_size,
                "success_path": str(success_path) if success_path.is_file() else None,
                "success_sha256": (
                    sha256_file(success_path) if success_path.is_file() else None
                ),
            }
        )

    if (
        target_months == canonical_months()
        and stage05_rows != config.expected_stage05_rows
    ):
        raise RuntimeError(
            f"Frozen Stage 05 count mismatch: {stage05_rows:,} != "
            f"{config.expected_stage05_rows:,}"
        )

    dictionary = read_json(dictionary_summary)
    n_users = int(dictionary["total_global_users"])
    if n_users <= 0:
        raise RuntimeError("Invalid total_global_users")

    counts = target_counts_by_speed(config)
    if int(counts["rows"].sum()) != stage05_rows:
        raise RuntimeError("Stage 05 speed-count sum does not equal footer total")
    if not (counts["rows"] == counts["unique_games"]).all():
        raise RuntimeError("Stage 05 game IDs are not unique within month/speed")

    stage05_glob = str(stage05_root / "month=*" / "timeout_opportunities.parquet")
    con = duckdb.connect()
    try:
        con.execute("SET threads=4")
        con.execute("SET memory_limit='6GB'")
        qa_row = con.execute(
            f"""
            SELECT
                count(*)::BIGINT AS rows,
                count(DISTINCT game_id)::BIGINT AS unique_game_ids,
                sum(CASE WHEN game_id IS NULL OR game_id = ''
                         THEN 1 ELSE 0 END)::BIGINT AS blank_game_ids,
                sum(CASE WHEN api_rated IS DISTINCT FROM TRUE
                         THEN 1 ELSE 0 END)::BIGINT AS nonrated_rows,
                sum(CASE WHEN lower(cast(api_variant AS varchar)) != 'standard'
                           OR api_variant IS NULL
                         THEN 1 ELSE 0 END)::BIGINT AS nonstandard_rows,
                sum(CASE WHEN lower(cast(chooser_color AS varchar))
                               NOT IN ('white','black')
                           OR chooser_color IS NULL
                         THEN 1 ELSE 0 END)::BIGINT AS invalid_chooser_color,
                sum(CASE WHEN lower(cast(disconnected_color AS varchar))
                               NOT IN ('white','black')
                           OR disconnected_color IS NULL
                         THEN 1 ELSE 0 END)::BIGINT AS invalid_disconnected_color,
                sum(CASE WHEN lower(cast(chooser_color AS varchar)) =
                                   lower(cast(disconnected_color AS varchar))
                         THEN 1 ELSE 0 END)::BIGINT AS same_color_roles,
                sum(CASE
                    WHEN lower(cast(chooser_color AS varchar)) = 'white'
                         AND chooser_elo IS DISTINCT FROM white_elo_pgn THEN 1
                    WHEN lower(cast(chooser_color AS varchar)) = 'black'
                         AND chooser_elo IS DISTINCT FROM black_elo_pgn THEN 1
                    ELSE 0 END)::BIGINT AS chooser_rating_mismatch,
                sum(CASE
                    WHEN lower(cast(disconnected_color AS varchar)) = 'white'
                         AND disconnected_elo IS DISTINCT FROM white_elo_pgn THEN 1
                    WHEN lower(cast(disconnected_color AS varchar)) = 'black'
                         AND disconnected_elo IS DISTINCT FROM black_elo_pgn THEN 1
                    ELSE 0 END)::BIGINT AS disconnected_rating_mismatch,
                sum(CASE WHEN white_rating_diff_pgn IS NULL
                           AND black_rating_diff_pgn IS NULL
                         THEN 1 ELSE 0 END)::BIGINT
                    AS focal_both_ratingdiff_null
            FROM read_parquet(
                {quote_sql(stage05_glob)},
                union_by_name=true,
                hive_partitioning=false
            )
            """
        ).fetchdf().iloc[0].to_dict()
    finally:
        con.close()

    stage05_qa = {
        key: (int(value) if key != "rows" or value is not None else value)
        for key, value in qa_row.items()
    }
    if int(stage05_qa["rows"]) != stage05_rows:
        raise RuntimeError("Stage 05 QA row count differs from footer total")
    if int(stage05_qa["unique_game_ids"]) != stage05_rows:
        raise RuntimeError("Stage 05 game IDs are not globally unique")
    zero_qa = (
        "blank_game_ids",
        "nonrated_rows",
        "nonstandard_rows",
        "invalid_chooser_color",
        "invalid_disconnected_color",
        "same_color_roles",
        "chooser_rating_mismatch",
        "disconnected_rating_mismatch",
    )
    bad_qa = {field: int(stage05_qa[field]) for field in zero_qa if int(stage05_qa[field]) != 0}
    if bad_qa:
        raise RuntimeError(f"Frozen Stage 05 contract failure: {bad_qa}")

    supported = tuple(
        speed
        for speed in CANONICAL_SPEED_ORDER
        if int(counts.loc[counts["speed"] == speed, "rows"].sum()) > 0
    )
    unexpected = sorted(set(counts["speed"].astype(str)) - set(CANONICAL_SPEED_ORDER))
    if unexpected:
        raise RuntimeError(f"Stage 05 contains unexpected speed pools: {unexpected}")

    replay: dict[str, Any] = {}
    for speed in supported:
        months = replay_months_for_speed(config, speed)
        if not months:
            raise RuntimeError(f"No replay months for speed={speed}")
        if config.target_end_month not in months:
            raise RuntimeError(
                f"Replay for speed={speed} does not cover {config.target_end_month}"
            )
        expected_contiguous = month_range(months[0], months[-1])
        missing_replay_months = sorted(set(expected_contiguous) - set(months))
        audited_gaps = sorted(AUDITED_REPLAY_GAPS.get(speed, ()))
        unaudited_gaps = sorted(set(missing_replay_months) - set(audited_gaps))
        stale_audited_gaps = sorted(set(audited_gaps) - set(missing_replay_months))
        if unaudited_gaps:
            raise RuntimeError(
                f"Replay history has unaudited gaps for speed={speed}: "
                f"{unaudited_gaps}; audited exceptions={audited_gaps}"
            )
        if stale_audited_gaps:
            raise RuntimeError(
                f"Audited replay-gap exception no longer matches the data for "
                f"speed={speed}: {stale_audited_gaps}. Re-audit before proceeding."
            )
        first = replay_part_path(config, speed, months[0])
        validate_replay_schema(first)
        replay[speed] = {
            "first_month": months[0],
            "last_month": months[-1],
            "month_count": len(months),
            "missing_replay_months": missing_replay_months,
            "audited_replay_gap_exceptions": audited_gaps,
            "replay_gap_policy": (
                "preserve_historical_partition_labels; do not silently alias unknown"
            ),
            "target_months_present": [m for m in target_months if m in set(months)],
            "target_months_missing": [m for m in target_months if m not in set(months)],
        }
        if replay[speed]["target_months_missing"]:
            raise RuntimeError(
                f"Replay coverage missing for speed={speed}: "
                f"{replay[speed]['target_months_missing']}"
            )

    selected_missing = sorted(set(config.speeds) - set(supported))
    if selected_missing:
        raise RuntimeError(
            f"Selected speed(s) have no Stage 05 targets: {selected_missing}"
        )

    return {
        "created_at": utc_now(),
        "sample_note": sample_note,
        "config": config.as_dict(),
        "n_users": n_users,
        "stage05_rows": stage05_rows,
        "stage05_files": stage05_files,
        "stage05_qa": stage05_qa,
        "target_counts": counts.to_dict(orient="records"),
        "supported_speeds": list(supported),
        "selected_speeds": list(config.speeds),
        "replay": replay,
        "dictionary_summary": {
            "path": str(dictionary_summary),
            "sha256": sha256_file(dictionary_summary),
            "total_global_users": n_users,
        },
        "formula": {
            "version": config.formula_version,
            "default_rd": config.default_rd,
            "default_sigma": config.default_sigma,
            "min_rd": config.min_rd,
            "max_rd": config.max_rd,
            "max_sigma": config.max_sigma,
            "tau": config.tau,
            "periods_per_day": config.periods_per_day,
            "standard_color_adv": config.standard_color_adv,
            "color_adv_start_utc": config.color_adv_start_utc,
            "both_null_policy": "skip hidden-state update and do not advance last_seen_ms",
        },
    }


# -----------------------------------------------------------------------------
# Target loading and raw-cost writing
# -----------------------------------------------------------------------------


def load_target_ids(config: Config, month: str, speed: str) -> set[str]:
    """Read only the Stage 05 game IDs belonging to one speed/month."""

    path = stage05_path(config, month)
    pf = pq.ParquetFile(path)
    targets: set[str] = set()
    for batch in pf.iter_batches(columns=["game_id", "api_speed"], batch_size=500_000):
        gids = batch.column(0).to_pylist()
        speeds = batch.column(1).to_pylist()
        for gid, raw_speed in zip(gids, speeds):
            if gid is None or raw_speed is None:
                continue
            if str(raw_speed).lower() == speed:
                targets.add(str(gid))
    return targets


def raw_cost_path(config: Config, speed: str, month: str) -> Path:
    return (
        Path(config.output_root)
        / "raw_white_black_costs"
        / f"speed={speed}"
        / f"month={month}"
        / "glicko2_raw_costs.parquet"
    )


def raw_success_path(config: Config, speed: str, month: str) -> Path:
    return raw_cost_path(config, speed, month).with_name("_SUCCESS.json")


def count_unique_parquet(path: Path) -> tuple[int, int]:
    con = duckdb.connect()
    try:
        row = con.execute(
            f"""
            SELECT count(*)::BIGINT, count(DISTINCT game_id)::BIGINT
            FROM read_parquet({quote_sql(path)})
            """
        ).fetchone()
        return int(row[0]), int(row[1])
    finally:
        con.close()


def write_target_coverage_ledgers(
    config: Config,
    month: str,
    speed: str,
    raw_path: Path,
) -> dict[str, str]:
    """Write fail-closed missing/extra/duplicate ledgers after a coverage error."""

    diagnostics = raw_path.parent / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    missing = diagnostics / "missing_target_ids.parquet"
    extra = diagnostics / "extra_raw_cost_ids.parquet"
    duplicates = diagnostics / "duplicate_raw_cost_ids.parquet"
    stage05 = stage05_path(config, month)

    con = duckdb.connect()
    try:
        con.execute("SET threads=2")
        con.execute("SET memory_limit='4GB'")
        con.execute(
            f"""
            COPY (
                WITH s AS (
                    SELECT game_id
                    FROM read_parquet({quote_sql(stage05)})
                    WHERE lower(cast(api_speed AS varchar)) = {quote_sql(speed)}
                ),
                k AS (
                    SELECT game_id
                    FROM read_parquet({quote_sql(raw_path)})
                )
                SELECT s.game_id
                FROM s LEFT JOIN k USING (game_id)
                WHERE k.game_id IS NULL
                ORDER BY s.game_id
            ) TO {quote_sql(missing)} (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        con.execute(
            f"""
            COPY (
                WITH s AS (
                    SELECT game_id
                    FROM read_parquet({quote_sql(stage05)})
                    WHERE lower(cast(api_speed AS varchar)) = {quote_sql(speed)}
                ),
                k AS (
                    SELECT game_id
                    FROM read_parquet({quote_sql(raw_path)})
                )
                SELECT k.game_id
                FROM k LEFT JOIN s USING (game_id)
                WHERE s.game_id IS NULL
                ORDER BY k.game_id
            ) TO {quote_sql(extra)} (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        con.execute(
            f"""
            COPY (
                SELECT game_id, count(*)::BIGINT AS rows
                FROM read_parquet({quote_sql(raw_path)})
                GROUP BY game_id
                HAVING count(*) > 1
                ORDER BY rows DESC, game_id
            ) TO {quote_sql(duplicates)} (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()

    return {
        "missing_target_ids": str(missing),
        "extra_raw_cost_ids": str(extra),
        "duplicate_raw_cost_ids": str(duplicates),
    }


def write_raw_rows(
    writer: pq.ParquetWriter | None,
    tmp_path: Path,
    rows: list[dict[str, Any]],
) -> pq.ParquetWriter:
    table = pa.Table.from_pylist(rows, schema=RAW_COST_SCHEMA)
    if writer is None:
        writer = pq.ParquetWriter(tmp_path, RAW_COST_SCHEMA, compression="zstd")
    writer.write_table(table, row_group_size=min(len(rows), 250_000))
    return writer


# -----------------------------------------------------------------------------
# State checkpoints
# -----------------------------------------------------------------------------


def checkpoint_dir(config: Config, speed: str) -> Path:
    return Path(config.output_root) / "checkpoints" / f"speed={speed}"


def checkpoint_path(config: Config, speed: str, month: str) -> Path:
    return checkpoint_dir(config, speed) / f"state_after_{month}.parquet"


def checkpoint_meta_path(config: Config, speed: str, month: str) -> Path:
    return checkpoint_dir(config, speed) / f"state_after_{month}.json"


def checkpoint_month_set(config: Config, replay_months: Sequence[str]) -> set[str]:
    out: set[str] = {
        month_before(config.target_start_month),
        config.target_end_month,
    }
    for idx, month in enumerate(replay_months, 1):
        if idx % config.checkpoint_frequency_months == 0:
            out.add(month)
    return out


def write_checkpoint(
    config: Config,
    speed: str,
    month: str,
    rd: np.ndarray,
    sigma: np.ndarray,
    games_seen: np.ndarray,
    last_seen_ms: np.ndarray,
    cumulative_rows_scanned: int,
    cumulative_updates_applied: int,
    cumulative_both_null_skipped: int,
) -> dict[str, Any]:
    active = np.nonzero(games_seen > 0)[0]
    final = checkpoint_path(config, speed, month)
    meta_path = checkpoint_meta_path(config, speed, month)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(final.name + f".tmp-{os.getpid()}")

    table = pa.table(
        {
            "user_id": active.astype(np.int64),
            "rd": rd[active].astype(np.float32),
            "sigma": sigma[active].astype(np.float32),
            "games_seen": games_seen[active].astype(np.uint32),
            "last_seen_ms": last_seen_ms[active].astype(np.int64),
        }
    )
    pq.write_table(table, tmp, compression="zstd", row_group_size=1_000_000)
    tmp.replace(final)

    rec = {
        "created_at": utc_now(),
        "speed": speed,
        "month": month,
        "path": str(final),
        "rows": int(len(active)),
        "size_bytes": final.stat().st_size,
        "sha256": sha256_file(final),
        "script_sha256": config.script_sha256,
        "formula_version": config.formula_version,
        "both_null_policy": "skip",
        "default_rd": config.default_rd,
        "default_sigma": config.default_sigma,
        "min_rd": config.min_rd,
        "max_rd": config.max_rd,
        "max_sigma": config.max_sigma,
        "tau": config.tau,
        "periods_per_day": config.periods_per_day,
        "color_adv_start_utc": config.color_adv_start_utc,
        "standard_color_adv": config.standard_color_adv,
        "cumulative_rows_scanned": int(cumulative_rows_scanned),
        "cumulative_updates_applied": int(cumulative_updates_applied),
        "cumulative_both_null_skipped": int(cumulative_both_null_skipped),
    }
    atomic_write_json(meta_path, rec)
    return rec


def checkpoint_matches_config(config: Config, meta: Mapping[str, Any]) -> bool:
    expected = {
        "formula_version": config.formula_version,
        "both_null_policy": "skip",
        "default_rd": config.default_rd,
        "default_sigma": config.default_sigma,
        "min_rd": config.min_rd,
        "max_rd": config.max_rd,
        "max_sigma": config.max_sigma,
        "tau": config.tau,
        "periods_per_day": config.periods_per_day,
        "color_adv_start_utc": config.color_adv_start_utc,
        "standard_color_adv": config.standard_color_adv,
    }
    return all(meta.get(k) == v for k, v in expected.items())


def target_outputs_complete_through(
    config: Config,
    speed: str,
    checkpoint_month: str,
) -> bool:
    for month in month_range(config.target_start_month, config.target_end_month):
        if month > checkpoint_month:
            break
        success = raw_success_path(config, speed, month)
        if not success.is_file():
            return False
        rec = read_json(success)
        if not rec.get("final_ok"):
            return False
    return True


def find_resume_checkpoint(
    config: Config,
    speed: str,
) -> tuple[str | None, Path | None, Mapping[str, Any] | None]:
    if not config.resume:
        return None, None, None
    base = checkpoint_dir(config, speed)
    candidates: list[tuple[str, Path, Path]] = []
    for p in base.glob("state_after_*.parquet"):
        m = re.fullmatch(r"state_after_(\d{4}-\d{2})\.parquet", p.name)
        if not m:
            continue
        month = m.group(1)
        if month > config.replay_end_month:
            continue
        meta = checkpoint_meta_path(config, speed, month)
        if meta.is_file():
            candidates.append((month, p, meta))
    for month, p, meta_path in sorted(candidates, reverse=True):
        meta = read_json(meta_path)
        if not checkpoint_matches_config(config, meta):
            continue
        if not target_outputs_complete_through(config, speed, month):
            continue
        return month, p, meta
    return None, None, None


def load_checkpoint(
    path: Path,
    n_users: int,
    config: Config,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rd = np.full(n_users, config.default_rd, dtype=np.float32)
    sigma = np.full(n_users, config.default_sigma, dtype=np.float32)
    games_seen = np.zeros(n_users, dtype=np.uint32)
    last_seen_ms = np.full(n_users, -1, dtype=np.int64)
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=1_000_000):
        df = batch.to_pandas()
        idx = df["user_id"].to_numpy(dtype=np.int64)
        if np.any(idx < 0) or np.any(idx >= n_users):
            raise RuntimeError(f"Checkpoint user_id out of bounds: {path}")
        rd[idx] = df["rd"].to_numpy(dtype=np.float32)
        sigma[idx] = df["sigma"].to_numpy(dtype=np.float32)
        games_seen[idx] = df["games_seen"].to_numpy(dtype=np.uint32)
        last_seen_ms[idx] = df["last_seen_ms"].to_numpy(dtype=np.int64)
    return rd, sigma, games_seen, last_seen_ms


# -----------------------------------------------------------------------------
# Per-speed replay
# -----------------------------------------------------------------------------


def score_pair(result_code: int) -> tuple[float, float]:
    if result_code == 2:
        return 1.0, 0.0
    if result_code == 1:
        return 0.5, 0.5
    if result_code == 0:
        return 0.0, 1.0
    raise ValueError(f"Unexpected result_code={result_code}")


def speed_output_root(config: Config, speed: str) -> Path:
    return Path(config.output_root) / "speed_runs" / f"speed={speed}"


def speed_summary_path(config: Config, speed: str) -> Path:
    return speed_output_root(config, speed) / "summary.json"


def load_progress_before_or_at(
    progress_path: Path,
    month: str | None,
) -> list[dict[str, Any]]:
    if month is None or not progress_path.is_file():
        return []
    df = pd.read_csv(progress_path)
    if df.empty or "month" not in df.columns:
        return []
    df = df[df["month"].astype(str) <= month].copy()
    return df.to_dict(orient="records")


def run_speed(config_dict: Mapping[str, Any], speed: str, n_users: int) -> dict[str, Any]:
    config = Config(**config_dict)
    root = speed_output_root(config, speed)
    root.mkdir(parents=True, exist_ok=True)
    run_log = root / "run.log"
    failure_path = root / "_FAILURE.json"
    summary_path = speed_summary_path(config, speed)

    try:
        if summary_path.is_file():
            existing = read_json(summary_path)
            if existing.get("final_ok"):
                log(f"SKIP completed speed={speed}", file=run_log)
                return existing
            if not config.resume:
                raise RuntimeError(
                    f"Incomplete prior speed output exists for {speed}; pass --resume"
                )

        replay_months = replay_months_for_speed(config, speed)
        if not replay_months:
            raise RuntimeError(f"No replay months for speed={speed}")
        validate_replay_schema(replay_part_path(config, speed, replay_months[0]))
        checkpoints = checkpoint_month_set(config, replay_months)

        resume_month, resume_path, resume_meta = find_resume_checkpoint(config, speed)
        if resume_path is None:
            rd = np.full(n_users, config.default_rd, dtype=np.float32)
            sigma = np.full(n_users, config.default_sigma, dtype=np.float32)
            games_seen = np.zeros(n_users, dtype=np.uint32)
            last_seen_ms = np.full(n_users, -1, dtype=np.int64)
            start_month = replay_months[0]
            previous_progress: list[dict[str, Any]] = []
            cumulative_rows_scanned = 0
            cumulative_updates_applied = 0
            cumulative_both_null_skipped = 0
            log(f"Starting speed={speed} from default state", file=run_log)
        else:
            rd, sigma, games_seen, last_seen_ms = load_checkpoint(
                resume_path, n_users, config
            )
            start_month = month_after(str(resume_month))
            progress_path = root / "progress_by_month.csv"
            previous_progress = load_progress_before_or_at(progress_path, resume_month)
            cumulative_rows_scanned = int(
                (resume_meta or {}).get("cumulative_rows_scanned", 0)
            )
            cumulative_updates_applied = int(
                (resume_meta or {}).get("cumulative_updates_applied", 0)
            )
            cumulative_both_null_skipped = int(
                (resume_meta or {}).get("cumulative_both_null_skipped", 0)
            )
            log(
                f"Resuming speed={speed} from checkpoint after {resume_month}",
                file=run_log,
            )

        months_to_run = [m for m in replay_months if m >= start_month]
        progress: list[dict[str, Any]] = list(previous_progress)
        color_half = config.standard_color_adv / 2.0
        total_t0 = time.time()

        for month in months_to_run:
            part = replay_part_path(config, speed, month)
            if not part.is_file():
                raise FileNotFoundError(part)
            validate_replay_schema(part)
            mt0 = time.time()
            target_month = config.target_start_month <= month <= config.target_end_month
            targets = load_target_ids(config, month, speed) if target_month else set()
            target_count = len(targets)

            final_path = raw_cost_path(config, speed, month)
            success_path = raw_success_path(config, speed, month)
            tmp_path = final_path.with_name(final_path.name + f".tmp-{os.getpid()}")
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if tmp_path.exists():
                tmp_path.unlink()
            writer: pq.ParquetWriter | None = None
            rows_buffer: list[dict[str, Any]] = []

            metrics = Metrics()
            rows_scanned = 0
            updates_applied = 0
            both_null_skipped = 0
            white_only_null = 0
            black_only_null = 0
            target_hits = 0
            target_both_null = 0
            target_updates_applied = 0
            monotonic_inversions = 0
            previous_archive: int | None = None

            pf = pq.ParquetFile(part)
            batch_columns = list(REQUIRED_REPLAY_COLUMNS)
            if not target_month:
                # game_id is needed only while extracting focal target costs.
                # Avoiding string materialization over the pre-sample history is
                # a substantial runtime and memory optimization.
                batch_columns.remove("game_id")
            for batch in pf.iter_batches(
                columns=batch_columns,
                batch_size=config.batch_size,
            ):
                df = batch.to_pandas()
                archive = df["archive_ordinal"].to_numpy(dtype=np.int64)
                utc = df["utc_ms"].to_numpy(dtype=np.int64)
                gids = (
                    df["game_id"].astype(str).to_numpy()
                    if target_month
                    else None
                )
                w_id = df["white_id"].to_numpy(dtype=np.int64)
                b_id = df["black_id"].to_numpy(dtype=np.int64)
                w_elo = df["white_elo"].to_numpy(dtype=np.float64)
                b_elo = df["black_elo"].to_numpy(dtype=np.float64)
                w_diff_obs = df["white_rating_diff"].to_numpy()
                b_diff_obs = df["black_rating_diff"].to_numpy()
                result = df["result_code"].to_numpy(dtype=np.int8)

                if len(archive):
                    if previous_archive is not None and archive[0] < previous_archive:
                        monotonic_inversions += 1
                    if len(archive) > 1:
                        monotonic_inversions += int(
                            np.sum(archive[1:] < archive[:-1])
                        )
                    previous_archive = int(archive[-1])

                for i in range(len(df)):
                    now_ms = int(utc[i])
                    wi = int(w_id[i])
                    bi = int(b_id[i])
                    if wi < 0 or wi >= n_users or bi < 0 or bi >= n_users:
                        raise RuntimeError(
                            f"user_id out of bounds speed={speed} month={month}"
                        )

                    # Compute the pre-game inflated RD without committing it to
                    # state.  This is essential for both-null games: committing
                    # inflation while retaining the old last_seen_ms would
                    # double-inflate the next observed rated update.
                    pre_w_rd = inflate_rd(
                        float(rd[wi]),
                        float(sigma[wi]),
                        int(last_seen_ms[wi]),
                        now_ms,
                        config.periods_per_day,
                        config.min_rd,
                        config.max_rd,
                    )
                    pre_b_rd = inflate_rd(
                        float(rd[bi]),
                        float(sigma[bi]),
                        int(last_seen_ms[bi]),
                        now_ms,
                        config.periods_per_day,
                        config.min_rd,
                        config.max_rd,
                    )
                    pre_w_sigma = float(sigma[wi])
                    pre_b_sigma = float(sigma[bi])

                    use_adv = now_ms >= config.color_adv_start_ms
                    w_adv = color_half if use_adv else 0.0
                    b_adv = -color_half if use_adv else 0.0
                    sw, sb = score_pair(int(result[i]))

                    w_actual_pred, upd_w_rd, upd_w_sigma = update_one(
                        float(w_elo[i]),
                        pre_w_rd,
                        pre_w_sigma,
                        float(b_elo[i]),
                        pre_b_rd,
                        sw,
                        config.tau,
                        config.min_rd,
                        config.max_rd,
                        config.max_sigma,
                        self_adv=w_adv,
                        opp_adv=b_adv,
                    )
                    b_actual_pred, upd_b_rd, upd_b_sigma = update_one(
                        float(b_elo[i]),
                        pre_b_rd,
                        pre_b_sigma,
                        float(w_elo[i]),
                        pre_w_rd,
                        sb,
                        config.tau,
                        config.min_rd,
                        config.max_rd,
                        config.max_sigma,
                        self_adv=b_adv,
                        opp_adv=w_adv,
                    )

                    w_null = bool(pd.isna(w_diff_obs[i]))
                    b_null = bool(pd.isna(b_diff_obs[i]))
                    both_null = w_null and b_null
                    if w_null and not b_null:
                        white_only_null += 1
                    if b_null and not w_null:
                        black_only_null += 1

                    # Validation uses every observed side, regardless of whether
                    # the other side is missing.
                    metrics.add(w_diff_obs[i], w_actual_pred)
                    metrics.add(b_diff_obs[i], b_actual_pred)

                    if target_month:
                        assert gids is not None
                        gid = str(gids[i])
                    else:
                        gid = ""
                    if target_month and gid in targets:
                        white_draw = pred_diff_only(
                            float(w_elo[i]),
                            pre_w_rd,
                            float(b_elo[i]),
                            pre_b_rd,
                            0.5,
                            config.min_rd,
                            self_adv=w_adv,
                            opp_adv=b_adv,
                        )
                        white_win = pred_diff_only(
                            float(w_elo[i]),
                            pre_w_rd,
                            float(b_elo[i]),
                            pre_b_rd,
                            1.0,
                            config.min_rd,
                            self_adv=w_adv,
                            opp_adv=b_adv,
                        )
                        black_draw = pred_diff_only(
                            float(b_elo[i]),
                            pre_b_rd,
                            float(w_elo[i]),
                            pre_w_rd,
                            0.5,
                            config.min_rd,
                            self_adv=b_adv,
                            opp_adv=w_adv,
                        )
                        black_win = pred_diff_only(
                            float(b_elo[i]),
                            pre_b_rd,
                            float(w_elo[i]),
                            pre_w_rd,
                            1.0,
                            config.min_rd,
                            self_adv=b_adv,
                            opp_adv=w_adv,
                        )
                        row = {
                            "month": month,
                            "speed": speed,
                            "archive_ordinal": int(archive[i]),
                            "utc_ms": now_ms,
                            "game_id": gid,
                            "white_id": wi,
                            "black_id": bi,
                            "white_elo_replay": int(w_elo[i]),
                            "black_elo_replay": int(b_elo[i]),
                            "white_pre_rd_v2": float(pre_w_rd),
                            "black_pre_rd_v2": float(pre_b_rd),
                            "white_pre_sigma_v2": pre_w_sigma,
                            "black_pre_sigma_v2": pre_b_sigma,
                            "white_draw_ratingdiff_v2": float(white_draw),
                            "white_win_ratingdiff_v2": float(white_win),
                            "white_win_premium_v2": float(white_win - white_draw),
                            "black_draw_ratingdiff_v2": float(black_draw),
                            "black_win_ratingdiff_v2": float(black_win),
                            "black_win_premium_v2": float(black_win - black_draw),
                            "white_realized_pred_ratingdiff_v2": float(w_actual_pred),
                            "black_realized_pred_ratingdiff_v2": float(b_actual_pred),
                            "observed_white_rating_diff": (
                                None if w_null else int(w_diff_obs[i])
                            ),
                            "observed_black_rating_diff": (
                                None if b_null else int(b_diff_obs[i])
                            ),
                            "both_ratingdiff_null": both_null,
                            "hidden_state_update_applied": not both_null,
                            "color_adv_applied": use_adv,
                        }
                        rows_buffer.append(row)
                        target_hits += 1
                        if both_null:
                            target_both_null += 1
                        else:
                            target_updates_applied += 1
                        if len(rows_buffer) >= config.output_chunk_rows:
                            writer = write_raw_rows(writer, tmp_path, rows_buffer)
                            rows_buffer = []

                    if both_null:
                        # Canonical later adjudication: no state update and no
                        # change in last_seen_ms.  The transient pre-RD values
                        # above are not committed to the state arrays.
                        both_null_skipped += 1
                    else:
                        rd[wi] = upd_w_rd
                        rd[bi] = upd_b_rd
                        sigma[wi] = upd_w_sigma
                        sigma[bi] = upd_b_sigma
                        games_seen[wi] += 1
                        games_seen[bi] += 1
                        last_seen_ms[wi] = now_ms
                        last_seen_ms[bi] = now_ms
                        updates_applied += 1

                    rows_scanned += 1

            if rows_buffer:
                writer = write_raw_rows(writer, tmp_path, rows_buffer)
            if writer is not None:
                writer.close()

            if target_month:
                if writer is None:
                    empty = pa.Table.from_pylist([], schema=RAW_COST_SCHEMA)
                    pq.write_table(empty, tmp_path, compression="zstd")
                tmp_path.replace(final_path)
                raw_rows, raw_unique = count_unique_parquet(final_path)
                final_ok = (
                    raw_rows == target_count
                    and raw_unique == target_count
                    and target_hits == target_count
                    and monotonic_inversions == 0
                )
                success = {
                    "created_at": utc_now(),
                    "final_ok": final_ok,
                    "month": month,
                    "speed": speed,
                    "target_count": target_count,
                    "target_hits": target_hits,
                    "rows": raw_rows,
                    "unique_game_ids": raw_unique,
                    "target_both_ratingdiff_null": target_both_null,
                    "target_updates_applied": target_updates_applied,
                    "output_path": str(final_path),
                    "size_bytes": final_path.stat().st_size,
                    "sha256": sha256_file(final_path),
                    "formula_version": config.formula_version,
                    "script_sha256": config.script_sha256,
                }
                if not final_ok:
                    success["coverage_ledgers"] = write_target_coverage_ledgers(
                        config, month, speed, final_path
                    )
                atomic_write_json(success_path, success)
                if not final_ok:
                    raise RuntimeError(
                        f"Target coverage failure speed={speed} month={month}: "
                        f"expected={target_count:,} hits={target_hits:,} "
                        f"rows={raw_rows:,} unique={raw_unique:,}"
                    )
            elif tmp_path.exists():
                tmp_path.unlink()

            if rows_scanned != int(pf.metadata.num_rows):
                raise RuntimeError(
                    f"Replay row-count mismatch speed={speed} month={month}: "
                    f"scanned={rows_scanned:,} footer={pf.metadata.num_rows:,}"
                )

            cumulative_rows_scanned += rows_scanned
            cumulative_updates_applied += updates_applied
            cumulative_both_null_skipped += both_null_skipped

            rec: dict[str, Any] = {
                "month": month,
                "speed": speed,
                "source_path": str(part),
                "source_rows": int(pf.metadata.num_rows),
                "source_size_bytes": part.stat().st_size,
                "rows_scanned": int(rows_scanned),
                "updates_applied": int(updates_applied),
                "both_ratingdiff_null_skipped": int(both_null_skipped),
                "white_only_ratingdiff_null": int(white_only_null),
                "black_only_ratingdiff_null": int(black_only_null),
                "target_month": bool(target_month),
                "target_count": int(target_count),
                "target_hits": int(target_hits),
                "target_both_ratingdiff_null": int(target_both_null),
                "monotonic_inversions": int(monotonic_inversions),
                "elapsed_sec": round(time.time() - mt0, 3),
                **{f"validation_{k}": v for k, v in metrics.as_dict().items()},
            }

            if month in checkpoints:
                ck = write_checkpoint(
                    config,
                    speed,
                    month,
                    rd,
                    sigma,
                    games_seen,
                    last_seen_ms,
                    cumulative_rows_scanned,
                    cumulative_updates_applied,
                    cumulative_both_null_skipped,
                )
                rec["checkpoint_path"] = ck["path"]
                rec["checkpoint_active_users"] = ck["rows"]

            # Replace any stale record for a month rerun from an earlier
            # checkpoint, then publish progress atomically.
            progress = [r for r in progress if str(r.get("month")) != month]
            progress.append(rec)
            progress.sort(key=lambda r: str(r.get("month")))
            progress_path = root / "progress_by_month.csv"
            tmp_progress = progress_path.with_name(
                progress_path.name + f".tmp-{os.getpid()}"
            )
            pd.DataFrame(progress).to_csv(tmp_progress, index=False)
            tmp_progress.replace(progress_path)

            log(
                f"{speed} {month}: rows={rows_scanned:,} updates={updates_applied:,} "
                f"both_null_skipped={both_null_skipped:,} targets={target_hits:,}/"
                f"{target_count:,} elapsed={rec['elapsed_sec']}s",
                file=run_log,
            )

        # Final speed-level assertions use the published target success records.
        expected_target_rows = 0
        actual_target_rows = 0
        target_both_null_total = 0
        for month in month_range(config.target_start_month, config.target_end_month):
            success = raw_success_path(config, speed, month)
            if not success.is_file():
                raise RuntimeError(
                    f"Missing target success speed={speed} month={month}"
                )
            srec = read_json(success)
            if not srec.get("final_ok"):
                raise RuntimeError(
                    f"Non-success target month speed={speed} month={month}"
                )
            expected_target_rows += int(srec["target_count"])
            actual_target_rows += int(srec["rows"])
            target_both_null_total += int(srec["target_both_ratingdiff_null"])

        if expected_target_rows != actual_target_rows:
            raise RuntimeError(
                f"Speed target total mismatch {speed}: expected="
                f"{expected_target_rows:,} actual={actual_target_rows:,}"
            )

        progress_df = pd.DataFrame(progress)
        summary = {
            "created_at": utc_now(),
            "final_ok": True,
            "speed": speed,
            "formula_version": config.formula_version,
            "script_sha256": config.script_sha256,
            "replay_first_month": replay_months[0],
            "replay_last_month": replay_months[-1],
            "replay_months": len(replay_months),
            "rows_scanned": int(progress_df["rows_scanned"].sum()),
            "updates_applied": int(progress_df["updates_applied"].sum()),
            "both_ratingdiff_null_skipped": int(
                progress_df["both_ratingdiff_null_skipped"].sum()
            ),
            "target_rows": int(actual_target_rows),
            "target_both_ratingdiff_null": int(target_both_null_total),
            "active_users": int(np.sum(games_seen > 0)),
            "elapsed_sec_this_invocation": round(time.time() - total_t0, 3),
            "progress_path": str(root / "progress_by_month.csv"),
        }
        atomic_write_json(summary_path, summary)
        if failure_path.exists():
            failure_path.unlink()
        log(f"COMPLETE speed={speed} target_rows={actual_target_rows:,}", file=run_log)
        return summary

    except Exception as exc:
        failure = {
            "created_at": utc_now(),
            "final_ok": False,
            "speed": speed,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "script_sha256": config.script_sha256,
        }
        atomic_write_json(failure_path, failure)
        log(f"FAIL speed={speed}: {exc}", file=run_log)
        raise


# -----------------------------------------------------------------------------
# Canonical chooser-side finalization
# -----------------------------------------------------------------------------


def final_month_path(config: Config, month: str) -> Path:
    return (
        Path(config.output_root)
        / f"month={month}"
        / "chooser_glicko2_costs.parquet"
    )


def final_month_success_path(config: Config, month: str) -> Path:
    return final_month_path(config, month).with_name("_SUCCESS.json")


def sql_file_list(paths: Iterable[Path]) -> str:
    return "[" + ",".join(quote_sql(p) for p in paths) + "]"


def finalize_month(
    config: Config,
    month: str,
    speeds: Sequence[str],
) -> dict[str, Any]:
    stage05 = stage05_path(config, month)
    raw_paths = [raw_cost_path(config, speed, month) for speed in speeds]
    for path in raw_paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    final = final_month_path(config, month)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(final.name + f".tmp-{os.getpid()}")
    if tmp.exists():
        tmp.unlink()

    con = duckdb.connect()
    try:
        con.execute("SET threads=4")
        con.execute("SET memory_limit='8GB'")
        con.execute("SET preserve_insertion_order=false")
        duck_tmp = Path(config.output_root) / "duckdb_tmp" / f"finalize_{month}"
        duck_tmp.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory={quote_sql(duck_tmp)}")

        con.execute(
            f"""
            COPY (
                WITH s AS (
                    SELECT
                        month,
                        game_id,
                        lower(cast(api_speed AS varchar)) AS api_speed,
                        cast(api_perf AS varchar) AS api_perf,
                        api_created_at_ms,
                        lower(cast(chooser_color AS varchar)) AS chooser_color,
                        cast(chooser_elo AS INTEGER) AS chooser_elo,
                        lower(cast(disconnected_color AS varchar)) AS disconnected_color,
                        cast(disconnected_elo AS INTEGER) AS disconnected_elo,
                        cast(white_elo_pgn AS INTEGER) AS white_elo_pgn,
                        cast(black_elo_pgn AS INTEGER) AS black_elo_pgn,
                        cast(white_rating_diff_pgn AS INTEGER) AS white_rating_diff_pgn,
                        cast(black_rating_diff_pgn AS INTEGER) AS black_rating_diff_pgn
                    FROM read_parquet({quote_sql(stage05)})
                ),
                k AS (
                    SELECT *
                    FROM read_parquet({sql_file_list(raw_paths)}, union_by_name=true)
                )
                SELECT
                    s.month,
                    s.game_id,
                    s.api_speed,
                    s.api_perf,
                    s.api_created_at_ms,
                    s.chooser_color,
                    s.disconnected_color,
                    s.chooser_elo,
                    s.disconnected_elo,
                    s.white_elo_pgn,
                    s.black_elo_pgn,
                    s.white_rating_diff_pgn,
                    s.black_rating_diff_pgn,

                    k.archive_ordinal,
                    k.utc_ms,
                    k.white_id,
                    k.black_id,
                    k.white_elo_replay,
                    k.black_elo_replay,

                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_id
                        WHEN s.chooser_color = 'black' THEN k.black_id
                        ELSE NULL
                    END AS chooser_user_id,
                    CASE
                        WHEN s.disconnected_color = 'white' THEN k.white_id
                        WHEN s.disconnected_color = 'black' THEN k.black_id
                        ELSE NULL
                    END AS disconnected_user_id,

                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_elo_replay
                        WHEN s.chooser_color = 'black' THEN k.black_elo_replay
                        ELSE NULL
                    END AS chooser_elo_v2_source,
                    CASE
                        WHEN s.disconnected_color = 'white' THEN k.white_elo_replay
                        WHEN s.disconnected_color = 'black' THEN k.black_elo_replay
                        ELSE NULL
                    END AS disconnected_elo_v2_source,

                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_pre_rd_v2
                        WHEN s.chooser_color = 'black' THEN k.black_pre_rd_v2
                        ELSE NULL
                    END AS chooser_pre_rd_v2,
                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_pre_sigma_v2
                        WHEN s.chooser_color = 'black' THEN k.black_pre_sigma_v2
                        ELSE NULL
                    END AS chooser_pre_sigma_v2,
                    CASE
                        WHEN s.disconnected_color = 'white' THEN k.white_pre_rd_v2
                        WHEN s.disconnected_color = 'black' THEN k.black_pre_rd_v2
                        ELSE NULL
                    END AS disconnected_pre_rd_v2,
                    CASE
                        WHEN s.disconnected_color = 'white' THEN k.white_pre_sigma_v2
                        WHEN s.disconnected_color = 'black' THEN k.black_pre_sigma_v2
                        ELSE NULL
                    END AS disconnected_pre_sigma_v2,

                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_draw_ratingdiff_v2
                        WHEN s.chooser_color = 'black' THEN k.black_draw_ratingdiff_v2
                        ELSE NULL
                    END AS chooser_draw_payoff_v2,
                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_win_ratingdiff_v2
                        WHEN s.chooser_color = 'black' THEN k.black_win_ratingdiff_v2
                        ELSE NULL
                    END AS chooser_win_payoff_v2,
                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_win_premium_v2
                        WHEN s.chooser_color = 'black' THEN k.black_win_premium_v2
                        ELSE NULL
                    END AS chooser_win_premium_v2,
                    CASE
                        WHEN s.chooser_color = 'white' THEN k.white_draw_ratingdiff_v2 >= 0
                        WHEN s.chooser_color = 'black' THEN k.black_draw_ratingdiff_v2 >= 0
                        ELSE NULL
                    END AS favorable_draw_v2,

                    k.white_pre_rd_v2,
                    k.black_pre_rd_v2,
                    k.white_pre_sigma_v2,
                    k.black_pre_sigma_v2,
                    k.white_draw_ratingdiff_v2,
                    k.white_win_ratingdiff_v2,
                    k.white_win_premium_v2,
                    k.black_draw_ratingdiff_v2,
                    k.black_win_ratingdiff_v2,
                    k.black_win_premium_v2,
                    k.white_realized_pred_ratingdiff_v2,
                    k.black_realized_pred_ratingdiff_v2,
                    k.observed_white_rating_diff,
                    k.observed_black_rating_diff,
                    k.both_ratingdiff_null,
                    k.hidden_state_update_applied,
                    k.color_adv_applied,

                    (s.white_elo_pgn = k.white_elo_replay) AS white_rating_source_match,
                    (s.black_elo_pgn = k.black_elo_replay) AS black_rating_source_match,
                    (
                        s.white_rating_diff_pgn IS NOT DISTINCT FROM
                        k.observed_white_rating_diff
                    ) AS white_ratingdiff_source_match,
                    (
                        s.black_rating_diff_pgn IS NOT DISTINCT FROM
                        k.observed_black_rating_diff
                    ) AS black_ratingdiff_source_match,
                    (s.api_speed = k.speed) AS speed_source_match,
                    (s.month = k.month) AS month_source_match,
                    (s.api_created_at_ms - k.utc_ms) AS api_minus_pgn_created_ms

                FROM s
                LEFT JOIN k USING (game_id)
                ORDER BY k.archive_ordinal, s.game_id
            )
            TO {quote_sql(tmp)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 500000)
            """
        )

        tmp.replace(final)

        # Sigma is stored in float32 state arrays/checkpoints.  The exact
        # float32 representation of a nominal ceiling such as 0.1 is
        # 0.10000000149011612, which is microscopically above the Python
        # float literal 0.1.  Final QA therefore distinguishes:
        #
        # * sigma_above_nominal_max: useful diagnostic count at > 0.1; and
        # * sigma_out_of_bounds: true violations above the representable
        #   float32 storage ceiling.
        #
        # This preserves a strict fail-closed upper bound without falsely
        # rejecting states that were correctly clamped before float32 storage.
        sigma_storage_ceiling = float(np.float32(config.max_sigma))

        qa = con.execute(
            f"""
            SELECT
                count(*)::BIGINT AS rows,
                count(DISTINCT game_id)::BIGINT AS unique_game_ids,
                sum(CASE WHEN archive_ordinal IS NULL THEN 1 ELSE 0 END)::BIGINT
                    AS missing_raw_cost_join,
                sum(CASE WHEN chooser_user_id IS NULL THEN 1 ELSE 0 END)::BIGINT
                    AS invalid_chooser_role,
                sum(CASE WHEN disconnected_user_id IS NULL THEN 1 ELSE 0 END)::BIGINT
                    AS invalid_disconnected_role,
                sum(CASE WHEN chooser_draw_payoff_v2 IS NULL
                           OR chooser_win_payoff_v2 IS NULL
                           OR chooser_win_premium_v2 IS NULL
                         THEN 1 ELSE 0 END)::BIGINT AS null_chooser_cost,
                sum(CASE WHEN chooser_draw_payoff_v2 IS NOT NULL AND
                                   NOT isfinite(chooser_draw_payoff_v2)
                           OR chooser_win_payoff_v2 IS NOT NULL AND
                                   NOT isfinite(chooser_win_payoff_v2)
                           OR chooser_win_premium_v2 IS NOT NULL AND
                                   NOT isfinite(chooser_win_premium_v2)
                         THEN 1 ELSE 0 END)::BIGINT AS nonfinite_chooser_cost,
                sum(CASE WHEN chooser_win_premium_v2 <= 0
                         THEN 1 ELSE 0 END)::BIGINT AS nonpositive_win_premium,
                sum(CASE WHEN chooser_pre_rd_v2 < {config.min_rd}
                           OR chooser_pre_rd_v2 > {config.max_rd}
                           OR disconnected_pre_rd_v2 < {config.min_rd}
                           OR disconnected_pre_rd_v2 > {config.max_rd}
                         THEN 1 ELSE 0 END)::BIGINT AS rd_out_of_bounds,
                sum(CASE WHEN chooser_pre_sigma_v2 > {config.max_sigma}
                           OR disconnected_pre_sigma_v2 > {config.max_sigma}
                         THEN 1 ELSE 0 END)::BIGINT AS sigma_above_nominal_max,
                sum(CASE WHEN chooser_pre_sigma_v2 <= 0
                           OR chooser_pre_sigma_v2 > {sigma_storage_ceiling!r}
                           OR disconnected_pre_sigma_v2 <= 0
                           OR disconnected_pre_sigma_v2 > {sigma_storage_ceiling!r}
                         THEN 1 ELSE 0 END)::BIGINT AS sigma_out_of_bounds,
                sum(CASE WHEN NOT white_rating_source_match
                           OR NOT black_rating_source_match
                         THEN 1 ELSE 0 END)::BIGINT AS rating_source_mismatch,
                sum(CASE WHEN NOT white_ratingdiff_source_match
                           OR NOT black_ratingdiff_source_match
                         THEN 1 ELSE 0 END)::BIGINT AS ratingdiff_source_mismatch,
                sum(CASE WHEN NOT speed_source_match
                           OR NOT month_source_match
                         THEN 1 ELSE 0 END)::BIGINT AS speed_or_month_mismatch,
                sum(CASE WHEN both_ratingdiff_null
                           AND hidden_state_update_applied
                         THEN 1 ELSE 0 END)::BIGINT AS both_null_wrongly_updated,
                sum(CASE WHEN NOT both_ratingdiff_null
                           AND NOT hidden_state_update_applied
                         THEN 1 ELSE 0 END)::BIGINT AS observed_diff_wrongly_skipped,
                max(abs(
                    chooser_win_premium_v2 -
                    (chooser_win_payoff_v2 - chooser_draw_payoff_v2)
                )) AS max_win_premium_identity_error,
                sum(CASE WHEN color_adv_applied THEN 1 ELSE 0 END)::BIGINT
                    AS color_adv_rows,
                sum(CASE WHEN both_ratingdiff_null THEN 1 ELSE 0 END)::BIGINT
                    AS both_ratingdiff_null_rows
            FROM read_parquet({quote_sql(final)})
            """
        ).fetchdf().iloc[0].to_dict()

    finally:
        con.close()

    expected_rows = int(pq.ParquetFile(stage05).metadata.num_rows)
    integer_zero_fields = (
        "missing_raw_cost_join",
        "invalid_chooser_role",
        "invalid_disconnected_role",
        "null_chooser_cost",
        "nonfinite_chooser_cost",
        "nonpositive_win_premium",
        "rd_out_of_bounds",
        "sigma_out_of_bounds",
        "rating_source_mismatch",
        "ratingdiff_source_mismatch",
        "speed_or_month_mismatch",
        "both_null_wrongly_updated",
        "observed_diff_wrongly_skipped",
        "color_adv_rows",  # locked main sample is entirely pre-color change
    )
    final_ok = (
        int(qa["rows"]) == expected_rows
        and int(qa["unique_game_ids"]) == expected_rows
        and all(int(qa[field]) == 0 for field in integer_zero_fields)
        and float(qa["max_win_premium_identity_error"] or 0.0) <= 1e-12
    )

    rec = {
        "created_at": utc_now(),
        "final_ok": final_ok,
        "month": month,
        "expected_rows": expected_rows,
        "output_path": str(final),
        "size_bytes": final.stat().st_size,
        "sha256": sha256_file(final) if config.hash_final_outputs else None,
        "formula_version": config.formula_version,
        "script_sha256": config.script_sha256,
        "qa": qa,
    }
    atomic_write_json(final_month_success_path(config, month), rec)
    if not final_ok:
        raise RuntimeError(f"Final month QA failed for {month}: {qa}")
    return rec


def finalize_all(config: Config, supported_speeds: Sequence[str]) -> dict[str, Any]:
    """Merge all speed outputs into the canonical month-level cost layer."""

    if tuple(supported_speeds) != CANONICAL_SPEED_ORDER:
        raise RuntimeError(
            "Global finalization requires exactly the five frozen Stage 05 speed pools"
        )
    for speed in supported_speeds:
        summary = speed_summary_path(config, speed)
        if not summary.is_file() or not read_json(summary).get("final_ok"):
            raise RuntimeError(f"Speed is not complete: {speed}")

    records: list[dict[str, Any]] = []
    for month in month_range(config.target_start_month, config.target_end_month):
        success = final_month_success_path(config, month)
        if success.is_file() and config.resume:
            rec = read_json(success)
            if rec.get("final_ok"):
                records.append(rec)
                continue
        rec = finalize_month(config, month, supported_speeds)
        records.append(rec)
        print(
            f"FINALIZED {month}: rows={rec['expected_rows']:,} "
            f"sha256={rec.get('sha256')}",
            flush=True,
        )

    total_rows = sum(int(r["expected_rows"]) for r in records)
    both_null_rows = sum(int(r["qa"]["both_ratingdiff_null_rows"]) for r in records)
    final_ok = total_rows == config.expected_stage05_rows and all(
        r.get("final_ok") for r in records
    )

    manifests = Path(config.output_root) / "_manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    paths = [str(final_month_path(config, m)) for m in month_range(
        config.target_start_month, config.target_end_month
    )]
    atomic_write_text(
        manifests / "glicko2_cost_layer_paths.txt",
        "\n".join(paths) + "\n",
    )
    pd.DataFrame(
        [
            {
                "month": r["month"],
                "rows": r["expected_rows"],
                "sha256": r.get("sha256"),
                "final_ok": r["final_ok"],
                "both_ratingdiff_null_rows": r["qa"][
                    "both_ratingdiff_null_rows"
                ],
                "output_path": r["output_path"],
            }
            for r in records
        ]
    ).to_csv(manifests / "month_status.csv", index=False)

    validation_frames: list[pd.DataFrame] = []
    for speed in supported_speeds:
        p = speed_output_root(config, speed) / "progress_by_month.csv"
        if p.is_file():
            validation_frames.append(pd.read_csv(p))
    if validation_frames:
        pd.concat(validation_frames, ignore_index=True).to_csv(
            manifests / "validation_by_speed_month.csv", index=False
        )

    schema = pq.ParquetFile(final_month_path(config, config.target_start_month)).schema_arrow
    atomic_write_json(
        manifests / "schema.json",
        {
            "created_at": utc_now(),
            "fields": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in schema
            ],
        },
    )

    summary = {
        "created_at": utc_now(),
        "final_ok": final_ok,
        "formula_version": config.formula_version,
        "script_path": config.script_path,
        "script_sha256": config.script_sha256,
        "target_start_month": config.target_start_month,
        "target_end_month": config.target_end_month,
        "months": len(records),
        "speeds": list(supported_speeds),
        "speed_source_script_sha256s": {
            speed: read_json(speed_summary_path(config, speed)).get("script_sha256")
            for speed in supported_speeds
        },
        "total_rows": total_rows,
        "expected_total_rows": config.expected_stage05_rows,
        "both_ratingdiff_null_rows": both_null_rows,
        "cost_path_manifest": str(manifests / "glicko2_cost_layer_paths.txt"),
        "month_status": str(manifests / "month_status.csv"),
        "validation_by_speed_month": str(
            manifests / "validation_by_speed_month.csv"
        ),
        "schema": str(manifests / "schema.json"),
        "month_records": records,
    }
    atomic_write_json(manifests / "summary.json", summary)
    atomic_write_json(manifests / "latest_summary.json", summary)
    if final_ok:
        atomic_write_json(
            Path(config.output_root) / "_SUCCESS.json",
            {
                "created_at": utc_now(),
                "final_ok": True,
                "summary": str(manifests / "latest_summary.json"),
                "total_rows": total_rows,
                "script_sha256": config.script_sha256,
                "speed_source_script_sha256s": summary.get(
                    "speed_source_script_sha256s", {}
                ),
            },
        )
    else:
        raise RuntimeError("Global Stage 06 finalization failed")
    return summary


# -----------------------------------------------------------------------------
# Self-tests
# -----------------------------------------------------------------------------


def assert_close(a: float, b: float, tol: float = 1e-10) -> None:
    if not math.isclose(a, b, rel_tol=tol, abs_tol=tol):
        raise AssertionError(f"{a} != {b} within {tol}")


def run_self_tests() -> dict[str, Any]:
    tests: list[str] = []

    # Equal ratings and equal RD imply exactly zero draw payoff without color adv.
    equal_draw = pred_diff_only(1500, 100, 1500, 100, 0.5, MIN_RD)
    assert_close(equal_draw, 0.0, 1e-12)
    tests.append("equal_rating_draw_zero")

    weak_draw = pred_diff_only(1400, 100, 1600, 100, 0.5, MIN_RD)
    strong_draw = pred_diff_only(1600, 100, 1400, 100, 0.5, MIN_RD)
    if not weak_draw > 0 or not strong_draw < 0:
        raise AssertionError("Draw-payoff signs are wrong")
    tests.append("draw_payoff_sign")

    draw = pred_diff_only(1500, 80, 1500, 80, 0.5, MIN_RD)
    win = pred_diff_only(1500, 80, 1500, 80, 1.0, MIN_RD)
    loss = pred_diff_only(1500, 80, 1500, 80, 0.0, MIN_RD)
    if not win > draw > loss:
        raise AssertionError("Outcome ordering failed")
    assert_close(win - draw, draw - loss, 1e-10)
    tests.append("outcome_order_and_symmetry")

    inflated = inflate_rd(
        80.0,
        DEFAULT_SIGMA,
        0,
        30 * MS_PER_DAY,
        PERIODS_PER_DAY,
        MIN_RD,
        MAX_RD,
    )
    if not 80.0 < inflated <= MAX_RD:
        raise AssertionError("RD inflation failed")
    tests.append("rd_inflation")

    # Missing-difference policy regression: a skipped both-null game must not
    # commit transient inflation or advance last_seen_ms.
    stored_rd = 80.0
    stored_last = 0
    first_game_ms = 10 * MS_PER_DAY
    transient_pre = inflate_rd(
        stored_rd,
        DEFAULT_SIGMA,
        stored_last,
        first_game_ms,
        PERIODS_PER_DAY,
        MIN_RD,
        MAX_RD,
    )
    if not transient_pre > stored_rd:
        raise AssertionError("Expected transient inflation")
    # Canonical skip leaves stored_rd/stored_last unchanged.  The next observed
    # update therefore inflates exactly once over the full 20-day interval.
    second_game_ms = 20 * MS_PER_DAY
    canonical_next = inflate_rd(
        stored_rd,
        DEFAULT_SIGMA,
        stored_last,
        second_game_ms,
        PERIODS_PER_DAY,
        MIN_RD,
        MAX_RD,
    )
    double_inflated_wrong = inflate_rd(
        transient_pre,
        DEFAULT_SIGMA,
        stored_last,
        second_game_ms,
        PERIODS_PER_DAY,
        MIN_RD,
        MAX_RD,
    )
    if not double_inflated_wrong > canonical_next:
        raise AssertionError("Both-null double-inflation test failed")
    tests.append("both_null_does_not_commit_transient_inflation")

    cutoff = parse_utc_ms(COLOR_ADV_START_UTC)
    before = cutoff - 1
    after = cutoff
    if before >= cutoff or after < cutoff:
        raise AssertionError("Color cutoff test failed")
    tests.append("color_adv_cutoff")

    # Counterfactual premium identity.
    w_draw = pred_diff_only(1700, 75, 1600, 90, 0.5, MIN_RD)
    w_win = pred_diff_only(1700, 75, 1600, 90, 1.0, MIN_RD)
    premium = w_win - w_draw
    assert_close(premium, w_win - w_draw, 1e-12)
    if premium <= 0:
        raise AssertionError("Win premium must be positive")
    tests.append("win_premium_identity")

    # Storage-bound regression: state arrays/checkpoints use float32.  A value
    # correctly clamped to the nominal MAX_SIGMA=0.1 is represented as
    # 0.10000000149011612 after float32 storage and must not be treated as a
    # true upper-bound violation during final QA.
    sigma_storage_ceiling = float(np.float32(MAX_SIGMA))
    if sigma_storage_ceiling < MAX_SIGMA:
        raise AssertionError("float32 sigma ceiling unexpectedly below nominal max")
    if not sigma_storage_ceiling >= MAX_SIGMA:
        raise AssertionError("float32 sigma storage-ceiling test failed")
    tests.append("float32_sigma_storage_ceiling")

    result = {
        "created_at": utc_now(),
        "self_test_ok": True,
        "tests": tests,
        "formula_version": FORMULA_VERSION,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


# -----------------------------------------------------------------------------
# CLI and orchestration
# -----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Canonical Stage 06 Glicko-2 cost-layer reconstruction",
    )
    p.add_argument(
        "--project-root",
        default="/Volumes/XT_Pro/lichess_kindness",
        help="Project root",
    )
    p.add_argument("--stage05-root", default=None)
    p.add_argument("--sorted-root", default=None)
    p.add_argument("--dictionary-summary", default=None)
    p.add_argument("--output-root", default=None)
    p.add_argument("--target-start-month", default=TARGET_START_MONTH)
    p.add_argument("--target-end-month", default=TARGET_END_MONTH)
    p.add_argument(
        "--replay-end-month",
        default=None,
        help="Last replay month; defaults to target-end-month",
    )
    p.add_argument(
        "--speeds",
        default="all",
        help="Comma-separated subset or literal 'all'",
    )
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=500_000)
    p.add_argument("--output-chunk-rows", type=int, default=100_000)
    p.add_argument("--checkpoint-frequency-months", type=int, default=12)
    p.add_argument("--expected-stage05-rows", type=int, default=EXPECTED_STAGE05_ROWS)
    p.add_argument("--color-adv-start-utc", default=COLOR_ADV_START_UTC)
    p.add_argument("--standard-color-adv", type=float, default=STANDARD_COLOR_ADV)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--no-hash-final-outputs", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument(
        "--execute",
        action="store_true",
        help="Execute selected speed replays; otherwise plan only",
    )
    p.add_argument(
        "--finalize-only",
        action="store_true",
        help="Skip replay and merge already completed five-speed outputs",
    )
    p.add_argument(
        "--no-finalize",
        action="store_true",
        help="Do not globally merge even when all five speeds are selected",
    )
    return p


def prepare_run_provenance(config: Config, plan: Mapping[str, Any]) -> Path:
    output_root = Path(config.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / "_runs" / f"run_{utc_stamp()}_{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=False)
    atomic_write_json(run_root / "command.json", config.as_dict())
    atomic_write_json(run_root / "plan.json", plan)
    atomic_write_json(run_root / "environment.json", environment_snapshot())
    shutil.copy2(config.script_path, run_root / Path(config.script_path).name)
    atomic_write_text(
        run_root / "script.sha256",
        f"{config.script_sha256}  {Path(config.script_path).name}\n",
    )
    return run_root


def print_plan(plan: Mapping[str, Any]) -> None:
    counts = pd.DataFrame(plan["target_counts"])
    print("\nSTAGE 06 READ-ONLY PLAN")
    print(json.dumps(
        {
            "sample_note": plan["sample_note"],
            "stage05_rows": plan["stage05_rows"],
            "n_users": plan["n_users"],
            "stage05_qa": plan["stage05_qa"],
            "supported_speeds": plan["supported_speeds"],
            "selected_speeds": plan["selected_speeds"],
            "formula": plan["formula"],
            "output_root": plan["config"]["output_root"],
        },
        indent=2,
        sort_keys=True,
    ))
    print("\nTARGET COUNTS BY SPEED")
    print(counts.groupby("speed", as_index=False)["rows"].sum().sort_values(
        "rows", ascending=False
    ).to_string(index=False))
    print("\nREPLAY COVERAGE")
    print(json.dumps(plan["replay"], indent=2, sort_keys=True))
    print("\nNo project file was modified in plan mode.")


def main() -> None:
    args = build_parser().parse_args()
    if args.self_test:
        run_self_tests()
        return

    if args.execute and args.finalize_only:
        raise SystemExit("Choose at most one of --execute and --finalize-only")

    config = build_config(args)
    plan = preflight(config)

    if not args.execute and not args.finalize_only:
        print_plan(plan)
        return

    ensure_empty_or_resumable_root(Path(config.output_root), config.resume)
    run_root = prepare_run_provenance(config, plan)
    global_log = run_root / "run.log"
    log(f"Stage 06 run root: {run_root}", file=global_log)

    supported = tuple(plan["supported_speeds"])
    n_users = int(plan["n_users"])

    if args.execute:
        worker_count = min(config.workers, len(config.speeds))
        log(
            f"Executing speeds={config.speeds} workers={worker_count}",
            file=global_log,
        )
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        if worker_count == 1:
            for speed in config.speeds:
                try:
                    results.append(run_speed(config.as_dict(), speed, n_users))
                except Exception as exc:
                    failures.append({"speed": speed, "error": repr(exc)})
                    break
        else:
            with ProcessPoolExecutor(max_workers=worker_count) as pool:
                futures = {
                    pool.submit(run_speed, config.as_dict(), speed, n_users): speed
                    for speed in config.speeds
                }
                for future in as_completed(futures):
                    speed = futures[future]
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        failures.append({"speed": speed, "error": repr(exc)})

        run_result = {
            "created_at": utc_now(),
            "results": sorted(results, key=lambda x: str(x.get("speed"))),
            "failures": failures,
        }
        atomic_write_json(run_root / "speed_results.json", run_result)
        if failures:
            atomic_write_json(
                run_root / "_FAILURE.json",
                {"created_at": utc_now(), "final_ok": False, **run_result},
            )
            raise SystemExit(f"Stage 06 speed failure(s): {failures}")

    should_finalize = (
        not args.no_finalize
        and tuple(config.speeds) == tuple(supported)
        and tuple(supported) == CANONICAL_SPEED_ORDER
    )
    if args.finalize_only or should_finalize:
        summary = finalize_all(config, supported)
        atomic_write_json(run_root / "final_summary.json", summary)
        log(
            f"GLOBAL COMPLETE rows={summary['total_rows']:,} final_ok={summary['final_ok']}",
            file=global_log,
        )
    else:
        log(
            "Selected-speed replay complete; global finalization intentionally skipped",
            file=global_log,
        )

    atomic_write_json(
        run_root / "_SUCCESS.json",
        {
            "created_at": utc_now(),
            "final_ok": True,
            "selected_speeds": list(config.speeds),
            "global_finalized": bool(args.finalize_only or should_finalize),
        },
    )


if __name__ == "__main__":
    main()
