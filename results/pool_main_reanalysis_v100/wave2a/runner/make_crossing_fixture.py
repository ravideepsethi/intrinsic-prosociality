#!/usr/bin/env python3
"""Create an outcome-bearing synthetic fixture for the crossing audit."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


MONTHS = tuple(
    f"{year}-{month:02d}"
    for year, values in ((2023, range(11, 13)), (2024, range(1, 13)), (2025, range(1, 11)))
    for month in values
)
SPEEDS = ("ultrabullet", "bullet", "blitz", "rapid", "classical")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=48_000)
    return parser.parse_args()


def run(root: Path, rows: int) -> Path:
    if rows < 30_000:
        raise ValueError("Synthetic crossing fixture requires at least 30,000 rows")
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(2026091001)
    chooser_count = 400
    chooser = np.arange(rows, dtype=np.int64) % chooser_count
    sequence = np.arange(rows, dtype=np.int64) // chooser_count
    displayed_gap = ((sequence * 7 + chooser * 3) % 25 - 12).astype(np.int64)
    month_code = ((sequence * 5 + chooser) % 24).astype(np.int64)
    speed_code = ((sequence + chooser) % len(SPEEDS)).astype(np.int64)
    zero_sequence = np.maximum(sequence, 0)
    zero_class = (zero_sequence + chooser) % 4
    base_rating = (1400 + 100 * ((chooser + sequence) % 7)).astype(float)
    zero = displayed_gap == 0
    both_1500 = zero & np.isin(zero_class, [0, 1, 2])
    chooser_rating = base_rating.copy()
    chooser_rating[both_1500] = 1500.0
    chooser_rating[zero & ~both_1500] = 1600.0 + 100.0 * ((chooser[zero & ~both_1500] + sequence[zero & ~both_1500]) % 5)
    opponent_rating = chooser_rating + displayed_gap.astype(float)

    chooser_rd = 45.0 + ((chooser * 11 + sequence * 7) % 60).astype(float)
    opponent_rd = 45.0 + ((chooser * 13 + sequence * 9) % 60).astype(float)
    chooser_rd[zero & (zero_class == 0)] = 350.0
    opponent_rd[zero & (zero_class == 0)] = 350.0
    chooser_rd[zero & (zero_class == 1)] = 350.0
    opponent_rd[zero & (zero_class == 1)] = 70.0
    chooser_rd[zero & (zero_class == 2)] = 70.0
    opponent_rd[zero & (zero_class == 2)] = 70.0
    chooser_rd[zero & (zero_class == 3)] = 65.0
    opponent_rd[zero & (zero_class == 3)] = 75.0

    kappa = 5.8 + 0.015 * chooser_rd + 0.006 * opponent_rd
    draw_payoff = kappa * np.tanh(displayed_gap.astype(float) / 400.0)
    draw_payoff[zero] = 0.0
    engine = np.clip(rng.normal(80.0, 130.0, rows), -100.0, 600.0)
    ply = 1 + ((sequence * 3 + chooser * 5) % 120)
    chooser_clock = np.maximum(0.0, rng.lognormal(mean=3.2, sigma=0.7, size=rows) - 1.0)
    opponent_clock = np.maximum(0.0, rng.lognormal(mean=3.0, sigma=0.8, size=rows) - 1.0)
    opponent_clock[(sequence + chooser) % 113 == 0] = np.nan
    latent = (
        -3.75
        + 0.10 * (displayed_gap > 0)
        + 0.12 * (draw_payoff < 0) * draw_payoff
        + 0.03 * (draw_payoff > 0) * draw_payoff
        + 0.22 * (zero & both_1500 & ((chooser_rd > 110) | (opponent_rd > 110)))
        + 0.08 * (zero & ~both_1500)
        + 0.002 * np.clip(engine, -100, 300) / 100
        + 0.08 * np.sin(chooser / 17.0)
    )
    probability = 1.0 / (1.0 + np.exp(-latent))
    kind = rng.random(rows) < probability
    frame = pd.DataFrame(
        {
            "game_id": [f"synthetic{index:010d}" for index in range(rows)],
            "chooser_user_id": chooser + 10_000,
            "chooser_username_norm": [f"chooser_{value:04d}" for value in chooser],
            "month": np.asarray(MONTHS, dtype=object)[month_code],
            "api_speed": np.asarray(SPEEDS, dtype=object)[speed_code],
            "outcome_kind_draw": kind,
            "kind_draw": kind,
            "chooser_draw_payoff_v2": draw_payoff,
            "chooser_win_premium_v2": kappa,
            "chooser_win_payoff_v2": draw_payoff + kappa,
            "engine_eval_cp_disconnected": engine,
            "chooser_pre_rd_v2": chooser_rd,
            "disconnected_pre_rd_v2": opponent_rd,
            "chooser_elo": chooser_rating,
            "disconnected_elo": opponent_rating,
            "ply_count": ply,
            "tournament_like_event": (chooser + sequence) % 19 == 0,
            "chooser_clock_last_obs_s": chooser_clock,
            "disconnected_clock_last_obs_s": opponent_clock,
        }
    )
    output = root / "synthetic_crossing_panel.parquet"
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        output,
        compression="zstd",
        row_group_size=8192,
    )
    print(f"POOL_MAIN_CROSSING_SYNTHETIC_FIXTURE_OK rows={rows} path={output}")
    return output


def main() -> int:
    args = parse_args()
    run(args.root.resolve(), args.rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
