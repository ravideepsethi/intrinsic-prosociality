#!/usr/bin/env python3
"""Synthetic integration tests for the dynamic second-wave production package."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


history = load("history_producer", "10g_build_dynamic_second_wave_histories.py")
estimate = load("result_producer", "10h_estimate_dynamic_second_wave.py")


def matching_user(connection: duckdb.DuckDBPyConnection) -> int:
    for value in range(1, 20_000):
        if (
            connection.execute(
                f"SELECT hash({value}::BIGINT, {history.USER_SEED}) "
                f"% {history.SAMPLE_DENOMINATOR}"
            ).fetchone()[0]
            == 0
        ):
            return value
    raise AssertionError("No sampled user found")


def matching_pair(connection: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    for low in range(20_001, 20_500):
        high = low + 10_000
        if (
            connection.execute(
                f"SELECT hash({low}::BIGINT, {high}::BIGINT, {history.PAIR_SEED}) "
                f"% {history.SAMPLE_DENOMINATOR}"
            ).fetchone()[0]
            == 0
        ):
            return low, high
    raise AssertionError("No sampled pair found")


def write(path: Path, mapping: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(mapping), path, compression="zstd")


def test_history_sql(root: Path) -> None:
    connection = duckdb.connect()
    sampled_user = matching_user(connection)
    pair_low, pair_high = matching_pair(connection)
    connection.close()
    other = 999_001
    times = [1_640_995_200_000, 1_672_531_200_000, 1_704_067_200_000, 1_735_689_600_000]
    source = root / "source.parquet"
    write(
        source,
        {
            "utc_ms": times + times[:3],
            "archive_ordinal": list(range(7)),
            "game_id": [f"u{i}" for i in range(4)] + [f"p{i}" for i in range(3)],
            "white_id": [sampled_user] * 4 + [pair_low] * 3,
            "black_id": [other + i for i in range(4)] + [pair_high] * 3,
            "white_elo": [1490, 1495, 1500, 1505, 1600, 1602, 1604],
            "black_elo": [1510, 1512, 1514, 1516, 1600, 1601, 1602],
            "white_rating_diff": [5, 5, 5, 5, 2, 2, 2],
            "black_rating_diff": [-5, -5, -5, -5, -2, -2, -2],
        },
    )
    state = root / "state"
    for relative in ("selected_games", "selected_game_receipts", "duckdb_temp/source"):
        (state / relative).mkdir(parents=True, exist_ok=True)
    row = {
        "file_index": 0,
        "path": str(source),
        "rows": 7,
        "footer_signature_sha256": "synthetic-footer",
        "speed": "blitz",
        "month": "synthetic",
    }
    saved = history.source_worker(row, str(state), "config", "1GB")
    assert saved["output_rows"] == 7
    payload = {"state": state, "config_sha256": "config"}
    user_root, pair_root = history.materialize_event_layers(
        payload, [state / "selected_games/source_0000.parquet"]
    )
    target = state / "targets.parquet"
    write(
        target,
        {
            "game_id": ["u3", "p2"],
            "user_sample": [True, False],
            "chooser_user_id": [sampled_user, pair_low],
            "pair_sample": [False, True],
            "low_id": [min(sampled_user, other + 3), pair_low],
            "high_id": [max(sampled_user, other + 3), pair_high],
        },
    )
    user_bucket = int(
        duckdb.connect().execute(
            f"SELECT hash({sampled_user}::BIGINT, {history.USER_SEED}) "
            f"% {history.IDENTIFIER_BUCKETS}"
        ).fetchone()[0]
    )
    pair_bucket = int(
        duckdb.connect().execute(
            f"SELECT hash({pair_low}::BIGINT, {pair_high}::BIGINT, {history.PAIR_SEED}) "
            f"% {history.IDENTIFIER_BUCKETS}"
        ).fetchone()[0]
    )
    (state / "user_bucket_receipts").mkdir(exist_ok=True)
    (state / "pair_bucket_receipts").mkdir(exist_ok=True)
    user_saved = history.user_bucket_worker(
        user_bucket, str(user_root), str(target), str(state), "config", "1GB"
    )
    pair_saved = history.pair_bucket_worker(
        pair_bucket, str(pair_root), str(target), str(state), "config", "1GB"
    )
    assert user_saved["output_rows"] >= 1
    assert pair_saved["output_rows"] >= 1
    user_table = pq.read_table(user_saved["output_path"])
    target_rows = user_table.filter(pc.equal(user_table["game_id"], "u3"))
    assert target_rows.num_rows == 1
    assert target_rows["prior_pool_peak"][0].as_py() == 1505
    pair_table = pq.read_table(pair_saved["output_path"])
    pair_target = pair_table.filter(pc.equal(pair_table["game_id"], "p2"))
    assert pair_target.num_rows == 1
    assert pair_target["pair_sequence"][0].as_py() == 3


def test_e1_scoring(root: Path) -> None:
    state = root / "e1_state"
    (state / "e1_month_scores").mkdir(parents=True)
    (state / "e1_month_receipts").mkdir(parents=True)
    (state / "duckdb_temp").mkdir(parents=True)
    training_time = 1_680_310_800_000  # 2023-04-01 01:00 UTC
    focal_time = 1_699_164_000_000  # 2023-11-05 01:00 UTC
    lows = list(range(100, 125)) + [900]
    highs = list(range(1_100, 1_125)) + [901]
    pair_path = root / "pair_processed.parquet"
    write(
        pair_path,
        {
            "low_id": lows,
            "high_id": highs,
            "game_id": [f"train{i}" for i in range(25)] + ["target"],
            "pair_sequence": [1] * 26,
            "is_stage07_target": [False] * 25 + [True],
            "utc_ms": [training_time] * 25 + [focal_time],
            "repeat_within_30d": [i % 2 == 0 for i in range(25)] + [False],
            "speed": ["blitz"] * 26,
            "rating_band_100": [1500] * 26,
            "rating_band_200": [1400] * 26,
            "utc_block_6h": [0] * 26,
            "weekend": [True] * 26,
        },
    )
    target = root / "e1_target.parquet"
    write(
        target,
        {
            "game_id": ["target"],
            "pair_sample": [True],
            "month": ["2023-11"],
            "low_id": [900],
            "high_id": [901],
            "chooser_user_id": [900],
            "chooser_elo": [1500.0],
            "opponent_elo": [1500.0],
            "utc_ms": [focal_time],
            "speed": ["blitz"],
        },
    )
    saved = estimate.e1_month_worker(
        "2023-11", [str(pair_path)], str(target), str(state), "config", "1GB"
    )
    assert saved["output_rows"] == 1
    result = pq.read_table(saved["output_path"]).to_pylist()[0]
    assert result["level"] == 1
    assert result["first_ever_pair"] is True
    assert 0 < result["re_pair_risk"] < 1
    assert result["leave_pair_out_n"] == 25


def test_salience_query(root: Path) -> None:
    rows = 12_000
    rng = np.random.default_rng(20260822)
    running = rng.integers(-70, 71, size=rows)
    post = 1500 + running
    path = root / "user_processed.parquet"
    write(
        path,
        {
            "is_stage07_target": [False] * rows,
            "rating_diff": [5] * rows,
            "post_rating": post,
            "pre_rating": post - 5,
            "prior_same_pool_games": [60] * rows,
            "first_prior_pool_utc_ms": [1_600_000_000_000] * rows,
            "utc_ms": [1_700_000_000_000 + int(i) for i in range(rows)],
            "prior_pool_peak": [1500.0] * rows,
            "user_id": rng.integers(1, 201, size=rows),
            "game_id": [f"g{i}" for i in range(rows)],
            "speed": ["blitz"] * rows,
            "next_any_utc_ms": [1_700_000_000_000 + i + 3_600_000 for i in range(rows)],
            "next_same_speed_utc_ms": [1_700_000_000_000 + i + 3_600_000 for i in range(rows)],
        },
    )
    payload = {"user_paths": [path], "state": root / "salience_state"}
    round_frame = estimate.salience_frame(payload, "round")
    personal_frame = estimate.salience_frame(payload, "personal")
    assert set(round_frame["grid"]) == {"true", "placebo_50", "placebo_37"}
    assert set(personal_frame["grid"]) == {"true", "placebo_37", "placebo_50"}
    diagnostics = estimate.salience_diagnostics(round_frame, "round")
    assert diagnostics["integer_support"]
    assert diagnostics["density_and_balance"]
    assert diagnostics["threshold_models"]
    secondary = estimate.fit_salience_grid(
        round_frame,
        branch="round",
        grid="true",
        bandwidth=10,
        prior_games=50,
        stop_minutes=30,
        next_game_field="next_same_speed_utc_ms",
        stopping_scope="same_speed_rated_standard_secondary",
    )
    assert secondary["stopping_scope"] == "same_speed_rated_standard_secondary"


def sampled_users_and_partners(count: int) -> list[tuple[int, int]]:
    connection = duckdb.connect()
    rows = []
    candidate = 1
    while len(rows) < count:
        user_mod = connection.execute(
            f"SELECT hash({candidate}::BIGINT, {history.USER_SEED}) "
            f"% {history.SAMPLE_DENOMINATOR}"
        ).fetchone()[0]
        if user_mod == 0:
            for partner in range(2_000_000, 2_005_000):
                pair_mod = connection.execute(
                    f"SELECT hash(LEAST({candidate}::BIGINT, {partner}::BIGINT), "
                    f"GREATEST({candidate}::BIGINT, {partner}::BIGINT), "
                    f"{history.PAIR_SEED}) % {history.SAMPLE_DENOMINATOR}"
                ).fetchone()[0]
                if pair_mod == 0:
                    rows.append((candidate, partner))
                    break
        candidate += 1
    connection.close()
    return rows


def test_stage07_model_path(root: Path) -> None:
    import pandas as pd

    rng = np.random.default_rng(220826)
    pairs = sampled_users_and_partners(40)
    rows = 4_800
    chooser = np.array([pairs[index % len(pairs)][0] for index in range(rows)])
    opponent = np.array([pairs[index % len(pairs)][1] for index in range(rows)])
    rating = rng.integers(1400, 1800, size=rows).astype(float)
    draw = rng.uniform(-8, 4, size=rows)
    premium = rng.uniform(3, 18, size=rows)
    month = np.array([f"2024-{index % 12 + 1:02d}" for index in range(rows)])
    game = np.array([f"stage{index}" for index in range(rows)])
    panel = root / "stage07.parquet"
    write(
        panel,
        {
            "game_id": game,
            "archive_ordinal": np.arange(rows),
            "month": month,
            "utc_ms": 1_704_067_200_000 + np.arange(rows) * 60_000,
            "chooser_user_id": chooser,
            "disconnected_user_id": opponent,
            "kind_draw": rng.random(rows) < 0.04,
            "chooser_elo": rating,
            "disconnected_elo": rating + rng.normal(0, 60, size=rows),
            "chooser_pre_rd_v2": rng.uniform(40, 100, size=rows),
            "disconnected_pre_rd_v2": rng.uniform(40, 100, size=rows),
            "engine_eval_cp_disconnected": rng.normal(0, 100, size=rows),
            "chooser_draw_payoff_v2": draw,
            "chooser_win_premium_v2": premium,
            "chooser_clock_last_obs_s": rng.uniform(1, 600, size=rows),
            "disconnected_clock_last_obs_s": rng.uniform(1, 600, size=rows),
            "ply_count": rng.integers(20, 120, size=rows),
            "material_advantage_chooser": rng.normal(0, 3, size=rows),
            "tc_base_s": rng.choice([60.0, 180.0, 600.0], size=rows),
            "tc_inc_s": rng.choice([0.0, 1.0, 2.0], size=rows),
            "api_speed": rng.choice(["bullet", "blitz", "rapid"], size=rows),
            "tournament_like_event": rng.random(rows) < 0.1,
            "fair_competitive": [True] * rows,
        },
    )
    user_state = root / "user_state.parquet"
    peak = rating + rng.integers(-10, 11, size=rows)
    write(
        user_state,
        {
            "user_id": chooser,
            "game_id": game,
            "prior_pool_peak": peak,
            "is_stage07_target": [True] * rows,
        },
    )
    payload = {
        "stage07_paths": [panel],
        "user_paths": [user_state],
        "state": root / "model_state",
    }
    frame = estimate.stage07_frame(payload, "F2-R", [])
    assert len(frame) == rows
    assert frame[["round_true", "round_50", "round_37"]].to_numpy().sum() > 0
    configured_stage08 = os.environ.get("DYNAMIC_SECOND_WAVE_STAGE08_CODE")
    candidates = []
    if configured_stage08:
        candidates.append(Path(configured_stage08))
    candidates.extend((
        ROOT / "08_make_core_paper_results.py",
        Path(
            "/Volumes/XT_Pro/lichess_kindness/replication_package/code/"
            "08_make_core_paper_results.py"
        ),
        ROOT.parent.parent / "deliverables/08_make_core_paper_results.py",
    ))
    stage08_path = next((path for path in candidates if path.is_file()), candidates[0])
    stage08 = estimate.load_stage08(stage08_path)
    result = estimate.fit_panel_branch(stage08, frame, "F2-R", 110)
    assert result["rows_raw"] > 1_000
    assert result["chooser_clusters"] == 40
    assert np.isfinite(result["coefficient"])
    e1_frame = frame.copy()
    e1_frame["re_pair_risk"] = rng.uniform(0.001, 0.2, size=len(frame))
    e1_frame["first_ever_pair"] = True
    e1_result = estimate.fit_panel_branch(stage08, e1_frame, "E1")
    assert e1_result["risk_p90"] > e1_result["risk_p10"]
    assert np.isfinite(e1_result["coefficient"])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dynamic_second_wave_synthetic_") as directory:
        root = Path(directory)
        test_history_sql(root / "history")
        test_e1_scoring(root / "e1")
        test_salience_query(root / "salience")
        test_stage07_model_path(root / "model")
    history.self_test()
    estimate.self_test()
    print("DYNAMIC_SECOND_WAVE_PRODUCTION_SYNTHETIC_TEST_OK")


if __name__ == "__main__":
    main()
