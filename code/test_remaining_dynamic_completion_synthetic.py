#!/usr/bin/env python3
"""Synthetic integration tests for the remaining-dynamics completion producer."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "12_complete_remaining_dynamic_analyses.py"


def load_producer():
    specification = importlib.util.spec_from_file_location("remaining_dynamic", SCRIPT)
    if specification is None or specification.loader is None:
        raise RuntimeError("Cannot import completion producer")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def write_parquet(path: Path, mapping: dict[str, list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(mapping), path, compression="zstd")


def test_a2_cache(producer, root: Path) -> None:
    day = producer.DAY_MS
    start = 1_000_000_000_000
    end = start + 500 * day
    anchor_a = start + 150 * day
    anchor_b = start + 250 * day
    recipient = root / "recipient.parquet"
    choices = root / "stage07.parquet"
    output = root / "a2_windows.parquet"
    write_parquet(
        recipient,
        {
            "cohort_row_id": [0, 1],
            "recipient_user_id": [10, 20],
            "exposure_anchor_utc_ms": [anchor_a, anchor_b],
        },
    )
    write_parquet(
        choices,
        {
            "chooser_user_id": [10, 10, 10, 10, 10, 20, 20, 20, 20, 99],
            "api_last_move_at_ms": [
                anchor_a - 80 * day,
                anchor_a - 20 * day,
                anchor_a + 10 * day,
                anchor_a + 50 * day,
                anchor_a + 95 * day,  # outside the 90-day window
                anchor_b - 70 * day,
                anchor_b - 10 * day,
                anchor_b + 15 * day,
                anchor_b + 70 * day,
                anchor_a + 1 * day,
            ],
            "fair_competitive": [True, True, True, True, True, True, False, True, True, True],
            "kind_draw": [False, True, True, False, True, True, True, False, True, True],
        },
    )
    producer.build_a2_account_windows(
        recipient=recipient,
        stage07_paths=[choices],
        output=output,
        threads=2,
        memory="1GB",
        temp=root / "duckdb_temp",
        start_ms=start,
        end_exclusive_ms=end,
    )
    table = pq.read_table(output).to_pydict()
    assert table["cohort_row_id"] == [0, 1]
    # User 10: one pre choice in 30d, two pre in 90d; one post in 30d,
    # two post in 90d. User 20's -10d choice is unfair and excluded.
    assert table["pre_30_n"] == [1, 0]
    assert table["pre_90_n"] == [2, 1]
    assert table["post_30_n"] == [1, 1]
    assert table["post_90_n"] == [2, 2]
    assert table["pre_90_k"] == [1, 1]
    assert table["post_90_k"] == [1, 1]


def test_helpers(producer) -> None:
    producer.self_test()


def load_core_authority(producer):
    raw = os.environ.get("REMAINING_DYNAMIC_BASE_CODE")
    if not raw:
        raw = (
            "/Volumes/XT_Pro/lichess_kindness/replication_package/"
            "code/10c_estimate_dynamic_prosociality_core.py"
        )
    path = Path(raw)
    if not path.is_file():
        raise RuntimeError(f"Synthetic model authority is missing: {path}")
    if producer.sha256_file(path) != producer.EXPECTED_BASE_CODE_SHA256:
        raise RuntimeError("Synthetic model authority SHA-256 mismatch")
    return producer.load_module(path)


def test_exact_model_integration(producer) -> None:
    """Exercise every new fit through the certified core numerical routines."""
    base = load_core_authority(producer)
    rng = np.random.default_rng(20260823)
    rows = 400
    index = np.arange(rows, dtype=np.int64)
    treatment = index % 5 == 0
    data: dict[str, np.ndarray] = {
        "cohort_row_id": index,
        "exposure_chooser_user_id": index // 4,
        "received_mercy": treatment,
        "exposure_claimed_win": ~treatment,
        "arm_eligible": np.ones(rows, dtype=bool),
        "exposure_no_mating_draw": np.zeros(rows, dtype=bool),
        "exposure_chooser_loss": np.zeros(rows, dtype=bool),
        "first_ever_pair": np.ones(rows, dtype=bool),
        "a1_90d_followup_eligible": np.ones(rows, dtype=bool),
        "exposure_cell_code": (index // 50) % 8,
        "exposure_month_code": (index // 25) % 2,
        "reached_fair_chooser_within_90d": np.ones(rows, dtype=bool),
        "first_subsequent_kind_draw": rng.binomial(
            1, 0.04 + 0.03 * treatment
        ).astype(float),
        "first_subsequent_speed_code": index % 4,
        "first_subsequent_tournament_like": index % 7 == 0,
        "first_subsequent_month_code": (index // 20) % 4,
        "recipient_future_disconnections_90d": rng.poisson(
            0.5 + 0.1 * treatment
        ),
        "recipient_future_mercy_receipts_90d": rng.binomial(
            2, 0.1 + 0.02 * treatment
        ),
        "exposure_anchor_utc_ms": 1_710_000_000_000 + index * 10_000,
        "first_subsequent_delta_ms": rng.integers(
            10_000, 10 * producer.DAY_MS, size=rows, dtype=np.int64
        ),
        "recipient_next_disconnection_utc_ms": np.full(rows, -1, dtype=np.int64),
    }
    # Censor a deterministic minority after their next exposure.
    censored = index % 11 == 0
    data["recipient_next_disconnection_utc_ms"][censored] = (
        data["exposure_anchor_utc_ms"][censored]
        + data["first_subsequent_delta_ms"][censored]
        - 1
    )
    for field in base.EXPOSURE_CONTROLS:
        data[field] = rng.normal(size=rows)
    for field in base.SUBSEQUENT_CONTROLS:
        if field == "first_subsequent_delta_ms":
            continue
        data[field] = rng.normal(size=rows)

    support = {
        "eligible": np.ones(rows, dtype=bool),
        "weights": np.ones(rows, dtype=float),
    }
    windows: dict[str, np.ndarray] = {
        "full_symmetric_window": np.ones(rows, dtype=bool)
    }
    for horizon, opportunities in ((30, 10), (60, 20), (90, 30)):
        pre_k = rng.binomial(opportunities, 0.04, size=rows)
        post_k = rng.binomial(
            opportunities, 0.04 + 0.02 * treatment, size=rows
        )
        windows[f"pre_{horizon}_n"] = np.full(rows, opportunities, dtype=np.int64)
        windows[f"post_{horizon}_n"] = np.full(rows, opportunities, dtype=np.int64)
        windows[f"pre_{horizon}_k"] = pre_k.astype(np.int64)
        windows[f"post_{horizon}_k"] = post_k.astype(np.int64)

    did, arms = producer.estimate_a2(base, data, support, windows)
    censor, paths, diagnostic = producer.estimate_a1_completion(base, data, support)
    assert len(did) == 6
    assert len(arms) == 24
    assert len(censor) == 2
    assert len(paths) == 4
    assert diagnostic["rows_removed_by_next_exposure_censoring"] == int(
        np.count_nonzero(censored)
    )
    assert all(np.isfinite(row["coefficient"]) for row in did)
    assert all(row["primary_family_reopened"] is False for row in censor)


def main() -> None:
    producer = load_producer()
    test_helpers(producer)
    with tempfile.TemporaryDirectory(prefix="remaining_dynamic_synthetic_") as text:
        test_a2_cache(producer, Path(text))
    test_exact_model_integration(producer)
    print("REMAINING_DYNAMIC_COMPLETION_SYNTHETIC_INTEGRATION_OK")


if __name__ == "__main__":
    main()
