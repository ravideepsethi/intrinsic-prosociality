#!/usr/bin/env python3
"""Create a deterministic Stage-07-shaped fixture for end-to-end package QA."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ModuleNotFoundError:  # pragma: no cover - build-only kernel self-tests
    pa = None
    pq = None

import equality_fen_common as common


# Two months from each frozen temporal half so both split-sample model families
# are exercised by the end-to-end synthetic gate.
MONTHS = ("2024-01", "2024-06", "2025-01", "2025-06")
SPEEDS = ("bullet", "blitz", "rapid", "classical")
FENS = (
    "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
    "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
    "rnbqkbnr/ppp1pppp/8/3p4/8/3P4/PPP1PPPP/RNBQKBNR w KQkq d6 0 2",
    "rnbqkbnr/ppp1pppp/8/3p4/8/3P1N2/PPP1PPPP/RNBQKB1R b KQkq - 1 2",
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
)
CHOOSER_COUNT = 600
EVAL_GRID = np.array(
    [
        -420, -300, -250, -225, -200, -175, -125,
        -100, -75, -50, -25, -10, -5, 0, 5, 10, 25, 50, 75, 100,
        125, 150, 175, 200, 225, 250, 300, 320, 420,
    ],
    dtype=np.int32,
)
PLACEBO_KNOTS = (-200, -100, 0, 100, 200)


def fairness(eval_cp: int) -> str:
    if eval_cp >= 300:
        return "disconnected_clearly_better"
    if eval_cp > 100:
        return "disconnected_better"
    if eval_cp >= -100:
        return "roughly_equal"
    if eval_cp > -300:
        return "modestly_worse_excluded"
    return "clearly_worse"


def make_fixture_frame(rows: int = 24000) -> pd.DataFrame:
    """Build a balanced fixture with guaranteed within-chooser identification."""
    if rows < CHOOSER_COUNT * len(EVAL_GRID):
        raise ValueError(
            "Synthetic fixture must give every chooser support across the evaluation grid"
        )
    if rows % CHOOSER_COUNT != 0:
        raise ValueError("Synthetic fixture rows must be divisible by chooser count")
    rng = np.random.default_rng(20260827)
    row_index = np.arange(rows, dtype=np.int64)
    chooser = row_index % CHOOSER_COUNT
    observation = row_index // CHOOSER_COUNT

    # Every chooser cycles through all evaluation values and all month/speed cells.
    # This directly prevents the v1.0.0 fixture defect in which fairness was constant
    # within chooser because both modular periods divided 1,200.
    evaluation = EVAL_GRID[(observation + 7 * chooser) % len(EVAL_GRID)]
    month_index = (observation + chooser // 17) % len(MONTHS)
    speed_index = (observation // 2 + chooser // 23) % len(SPEEDS)

    forced_short = (observation % 3 == 0) | ((observation + chooser) % 11 == 0)
    short_ply = 2 + ((5 * observation + chooser) % 9)
    long_ply = 11 + ((7 * observation + 3 * chooser) % 35)
    ply = np.where(forced_short, short_ply, long_ply).astype(np.int32)

    draw_payoff = (
        ((7 * observation + 3 * chooser) % 41).astype(np.float64) - 20.0
    ) / 10.0
    win_premium = 5.0 + (
        (11 * observation + 7 * chooser) % 50
    ).astype(np.float64) / 5.0

    # Deliberately skewed position frequencies exercise continuous and tiered
    # commonness designs. The observation term also guarantees within-chooser
    # movement across position signatures among short games.
    fen_selector = (37 * observation + 17 * chooser) % 100
    fen_index = np.select(
        [
            fen_selector < 50,
            fen_selector < 75,
            fen_selector < 88,
            fen_selector < 95,
            fen_selector < 99,
        ],
        [0, 1, 2, 3, 4],
        default=5,
    )
    equality = ((evaluation >= -100) & (evaluation <= 100)).astype(np.float64)
    short = (ply <= 10).astype(np.float64)
    common_position = (fen_index <= 1).astype(np.float64)
    probability = (
        0.018
        + 0.002 * equality
        + 0.004 * equality * short
        + 0.0015 * equality * short * common_position
        + 0.001 * (draw_payoff >= 0)
        + 0.0006 * np.maximum(evaluation, 0) / 100.0
        - 0.0002 * np.maximum(-evaluation, 0) / 100.0
    )
    chooser_effect = ((chooser % 17) - 8) * 0.00025
    probability = np.clip(probability + chooser_effect, 0.001, 0.20)
    kind = rng.random(rows) < probability
    return pd.DataFrame(
        {
            "month": np.array(MONTHS, dtype=object)[month_index],
            "game_id": [f"SYN{i:08d}" for i in range(rows)],
            "archive_ordinal": row_index,
            "chooser_username_norm": [f"chooser_{value:05d}" for value in chooser],
            "kind_draw": kind,
            "engine_eval_cp_disconnected": evaluation,
            "engine_fairness_bin": [fairness(int(value)) for value in evaluation],
            "chooser_draw_payoff_v2": draw_payoff,
            "chooser_win_premium_v2": win_premium,
            "draw_nonnegative": draw_payoff >= 0,
            "api_speed": np.array(SPEEDS, dtype=object)[speed_index],
            "chooser_elo": 1200 + (chooser % 1600).astype(np.int32),
            "tournament_like_event": ((3 * observation + chooser) % 13) == 0,
            "chooser_clock_last_obs_s": 1.0 + ((17 * observation + 13 * chooser) % 300),
            "disconnected_clock_last_obs_s": 2.0 + ((29 * observation + 19 * chooser) % 500),
            "ply_count": ply,
            "fen_after_last_move": np.array(FENS, dtype=object)[fen_index],
        }
    )


def identification_diagnostics(frame: pd.DataFrame) -> dict[str, int]:
    """Fail closed unless the fixture identifies every required FE family."""
    eligible = frame.loc[
        frame.engine_fairness_bin.isin(["roughly_equal", "disconnected_better"])
    ].copy()
    eligible["is_equality"] = eligible.engine_fairness_bin.eq("roughly_equal").astype(float)
    chooser_switchers = int(
        eligible.groupby("chooser_username_norm")["is_equality"].nunique().ge(2).sum()
    )
    short_eligible = eligible.loc[eligible.ply_count <= 10].copy()
    short_switchers = int(
        short_eligible.groupby("chooser_username_norm")["is_equality"].nunique().ge(2).sum()
    )

    short_all = frame.loc[frame.ply_count <= 10].copy()
    short_all["fen4"] = short_all.fen_after_last_move.str.split().str[:4].str.join(" ")
    frequencies = short_all.fen4.value_counts()
    short_eligible["fen4"] = (
        short_eligible.fen_after_last_move.str.split().str[:4].str.join(" ")
    )
    short_eligible["fen4_log1p_loo"] = np.log1p(
        short_eligible.fen4.map(frequencies).astype(float) - 1.0
    )
    commonness_switchers = int(
        short_eligible.groupby("chooser_username_norm")["fen4_log1p_loo"]
        .nunique()
        .ge(2)
        .sum()
    )

    exact_knots = int(frame.engine_eval_cp_disconnected.isin(PLACEBO_KNOTS).sum())
    observed_knots = set(
        int(value)
        for value in frame.loc[
            frame.engine_eval_cp_disconnected.isin(PLACEBO_KNOTS),
            "engine_eval_cp_disconnected",
        ].unique()
    )
    if observed_knots != set(PLACEBO_KNOTS):
        raise RuntimeError(f"Synthetic placebo-knot support changed: {observed_knots}")
    if chooser_switchers != CHOOSER_COUNT:
        raise RuntimeError(
            f"Synthetic equality support is not universal within chooser: {chooser_switchers}"
        )
    if short_switchers < 500:
        raise RuntimeError(
            f"Synthetic short-game equality switcher support is inadequate: {short_switchers}"
        )
    if commonness_switchers < 500:
        raise RuntimeError(
            f"Synthetic FEN commonness support is inadequate: {commonness_switchers}"
        )

    chooser_codes = pd.factorize(eligible.chooser_username_norm, sort=False)[0]
    month_codes = pd.factorize(eligible.month, sort=False)[0]
    speed_codes = pd.factorize(eligible.api_speed, sort=False)[0]
    y = 100.0 * eligible.kind_draw.to_numpy(dtype=float)
    equality = eligible.is_equality.to_numpy(dtype=float)
    win = eligible.chooser_win_premium_v2.to_numpy(dtype=float)
    log_chooser = np.log1p(eligible.chooser_clock_last_obs_s.to_numpy(dtype=float))
    log_disconnected = np.log1p(
        eligible.disconnected_clock_last_obs_s.to_numpy(dtype=float)
    )
    e1 = common.fit_lpm_cluster(
        y,
        equality,
        ["roughly_equal"],
        chooser_codes,
        fixed_effect_codes=(chooser_codes,),
    )
    e2 = common.fit_lpm_cluster(
        y,
        np.column_stack([equality, win, log_chooser, log_disconnected]),
        [
            "roughly_equal",
            "win_premium",
            "log_chooser_clock",
            "log_disconnected_clock",
        ],
        chooser_codes,
        fixed_effect_codes=(chooser_codes, month_codes, speed_codes),
    )

    short_chooser = pd.factorize(short_eligible.chooser_username_norm, sort=False)[0]
    short_month = pd.factorize(short_eligible.month, sort=False)[0]
    short_speed = pd.factorize(short_eligible.api_speed, sort=False)[0]
    short_ply = pd.factorize(short_eligible.ply_count, sort=False)[0]
    short_y = 100.0 * short_eligible.kind_draw.to_numpy(dtype=float)
    short_equality = short_eligible.is_equality.to_numpy(dtype=float)
    short_fen = short_eligible.fen4_log1p_loo.to_numpy(dtype=float)
    c1 = common.fit_lpm_cluster(
        short_y,
        np.column_stack([short_equality, short_fen, short_equality * short_fen]),
        ["roughly_equal", "fen4_log1p_loo", "roughly_equal_x_fen4_log1p_loo"],
        short_chooser,
        fixed_effect_codes=(short_chooser, short_month, short_speed, short_ply),
    )
    minimum_identifying = min(
        int(e1["n_rows_identifying"]),
        int(e2["n_rows_identifying"]),
        int(c1["n_rows_identifying"]),
    )
    if minimum_identifying < 1000:
        raise RuntimeError(
            f"Synthetic FE identification rows are inadequate: {minimum_identifying}"
        )
    return {
        "chooser_switchers": chooser_switchers,
        "short_equality_switchers": short_switchers,
        "fen4_commonness_switchers": commonness_switchers,
        "exact_placebo_knot_rows": exact_knots,
        "minimum_fe_identifying_rows": minimum_identifying,
    }


def build_fixture(root: Path, rows: int = 24000) -> dict[str, int]:
    if pa is None or pq is None:
        raise RuntimeError("pyarrow is required for the end-to-end synthetic fixture")
    root.mkdir(parents=True, exist_ok=True)
    frame = make_fixture_frame(rows)
    diagnostics = identification_diagnostics(frame)
    for month in MONTHS:
        part = frame.loc[frame.month == month].copy()
        destination = root / f"month={month}" / "analysis_panel.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(part, preserve_index=False)
        pq.write_table(
            table,
            destination,
            compression="zstd",
            compression_level=6,
            row_group_size=5000,
        )
    receipt = {
        "status": "SYNTHETIC_STAGE07_OK",
        "created_at_utc": common.utc_now(),
        "months": len(MONTHS),
        "rows": int(rows),
        "kind_draws": int(frame.kind_draw.sum()),
        "short_rows": int((frame.ply_count <= 10).sum()),
        "short_ply_max": 10,
        "choosers": CHOOSER_COUNT,
        "identification_diagnostics": diagnostics,
    }
    common.atomic_write_json(root / "_SUCCESS.json", receipt)
    return {
        "rows": int(rows),
        "kind_draws": int(frame.kind_draw.sum()),
        "short_rows": int((frame.ply_count <= 10).sum()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=24000)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        if len(FENS) < 5 or len(MONTHS) != 4:
            raise RuntimeError("Synthetic fixture constants changed")
        if fairness(-100) != "roughly_equal" or fairness(101) != "disconnected_better":
            raise RuntimeError("Synthetic fairness boundary test failed")
        diagnostics = identification_diagnostics(make_fixture_frame())
        print(
            "synthetic_chooser_switchers: "
            f"{diagnostics['chooser_switchers']:,}"
        )
        print(
            "synthetic_short_equality_switchers: "
            f"{diagnostics['short_equality_switchers']:,}"
        )
        print(
            "synthetic_fen4_commonness_switchers: "
            f"{diagnostics['fen4_commonness_switchers']:,}"
        )
        print(
            "synthetic_minimum_fe_identifying_rows: "
            f"{diagnostics['minimum_fe_identifying_rows']:,}"
        )
        print("KINDNESS_EQUALITY_FEN_SYNTHETIC_FIXTURE_SELFTEST_OK")
        return 0
    result = build_fixture(args.root.resolve(), args.rows)
    print("KINDNESS_EQUALITY_FEN_SYNTHETIC_FIXTURE_OK")
    print(f"Rows: {result['rows']:,}")
    print(f"Kind draws: {result['kind_draws']:,}")
    print(f"Short rows: {result['short_rows']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
