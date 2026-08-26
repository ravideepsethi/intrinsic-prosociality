#!/usr/bin/env python3
"""Synthetic-Parquet integration test for the elasticity production kernels."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

import kindness_price_elasticity_common_v102 as common
import run_kindness_price_elasticity_v102 as runner


def main() -> None:
    rows_per_month = 50
    rows = rows_per_month * len(common.MAIN_MONTHS)
    choosers = 120
    kind_draws = rows // 5
    first12_rows = rows_per_month * 12

    common.EXPECTED_FAIR_ROWS = rows
    common.EXPECTED_FAIR_KIND_DRAWS = kind_draws
    common.EXPECTED_FAIR_CHOOSERS = choosers
    common.EXPECTED_FIRST12_FAIR_ROWS = first12_rows
    common.EXPECTED_FIRST12_FAIR_CHOOSERS = choosers
    common.EXPECTED_NONPOSITIVE_PRICE_ROWS = 1

    with tempfile.TemporaryDirectory(prefix="kindness_elasticity_synthetic_") as temporary:
        root = Path(temporary)
        stage = root / "stage07"
        ordinal = 0
        for month_index, month in enumerate(common.MAIN_MONTHS):
            payload: dict[str, list[object]] = {
                "chooser_username_norm": [], "fair_competitive": [], "game_id": [],
                "api_last_move_at_ms": [], "utc_ms": [], "archive_ordinal": [],
                "kind_draw": [], "chooser_win_premium_v2": [],
                "chooser_draw_payoff_v2": [], "engine_eval_cp_disconnected": [],
                "chooser_elo": [], "disconnected_elo": [], "chooser_pre_rd_v2": [],
                "disconnected_pre_rd_v2": [], "chooser_clock_last_obs_s": [],
                "disconnected_clock_last_obs_s": [], "tournament_like_event": [],
                "month": [], "api_speed": [],
            }
            for local in range(rows_per_month):
                index = ordinal + local
                chooser = index % choosers
                # Production Stage07 has no nonpositive premium. Deliberately
                # inject one here to exercise the generic guard: retain it for
                # level models and omit only it from log(price) estimators.
                price = 0.0 if index == 7 else math.exp(
                    -0.4 + ((index * 17) % 100) / 36.0
                )
                draw = -4.0 + ((index * 29) % 800) / 100.0
                payload["chooser_username_norm"].append(f"chooser_{chooser:03d}")
                payload["fair_competitive"].append(True)
                payload["game_id"].append(f"g{index:08d}")
                payload["api_last_move_at_ms"].append(1_698_796_800_000 + index * 60_000)
                payload["utc_ms"].append(1_698_796_800_000 + index * 60_000)
                payload["archive_ordinal"].append(index)
                payload["kind_draw"].append(((index // choosers) + chooser) % 5 == 0)
                payload["chooser_win_premium_v2"].append(price)
                payload["chooser_draw_payoff_v2"].append(draw)
                payload["engine_eval_cp_disconnected"].append(-90 + (index * 13) % 900)
                payload["chooser_elo"].append(1300 + (chooser * 11) % 1500)
                payload["disconnected_elo"].append(1350 + (index * 7) % 1400)
                payload["chooser_pre_rd_v2"].append(55.0 + (index % 90))
                payload["disconnected_pre_rd_v2"].append(60.0 + (index % 85))
                payload["chooser_clock_last_obs_s"].append(None if index % 41 == 0 else 20.0 + index % 240)
                payload["disconnected_clock_last_obs_s"].append(None if index % 37 == 0 else 15.0 + index % 300)
                payload["tournament_like_event"].append(index % 7 == 0)
                payload["month"].append(month)
                payload["api_speed"].append(("bullet", "blitz", "rapid", "classical")[index % 4])
            month_root = stage / f"month={month}"
            month_root.mkdir(parents=True)
            pq.write_table(
                pa.table(payload), month_root / "analysis_panel.parquet",
                compression="zstd", row_group_size=50,
            )
            ordinal += rows_per_month

        paths = common.stage07_paths(stage)
        state = root / "state"
        state.mkdir()
        config = common.sha256_json({"test": "synthetic", "version": runner.SCRIPT_VERSION})
        base, base_receipt = runner.build_fair_base(
            paths=paths, state=state, threads=4, memory_limit="2GB",
            config_sha256=config,
        )
        cache, cache_receipt = runner.build_model_cache(
            base=base, state=state, threads=4, memory_limit="2GB",
            config_sha256=config,
        )
        base_resumed, _ = runner.build_fair_base(
            paths=paths, state=state, threads=4, memory_limit="2GB",
            config_sha256=config,
        )
        cache_resumed, _ = runner.build_model_cache(
            base=base_resumed, state=state, threads=4, memory_limit="2GB",
            config_sha256=config,
        )
        if base_resumed != base or cache_resumed != cache:
            raise RuntimeError("Synthetic checkpoint resume paths changed")
        data = runner.load_arrays(cache)
        if base_receipt["rows"] != rows or cache_receipt["kind_draws"] != kind_draws:
            raise RuntimeError("Synthetic Parquet receipts did not conserve rows/outcomes")
        if base_receipt["zero_price_rows"] != 1 or sum(~(data["log_price"] == data["log_price"])) != 1:
            raise RuntimeError("Synthetic zero-price support policy was not exercised exactly once")
        mask = data["row_id"] >= 0
        fitted = runner.fit_lpm_model(
            data=data, mask=mask,
            model="synthetic_primary", role="synthetic_validation",
            exposure="log_price", exposure_values=data["log_price"],
            reference="bins", adjusted=True, fixed_reference_bins=50,
        )
        if fitted["status"] != "ESTIMATED" or not math.isfinite(fitted["elasticity"]["estimate"]):
            raise RuntimeError("Synthetic adjusted LPM did not produce a finite elasticity")
        ppml = common.conditional_fe_poisson(
            outcome=data["kind"],
            regressors={
                "log_price": data["log_price"],
                "draw_payoff": data["draw_payoff"],
            },
            chooser_codes=data["chooser_index"], exposure_name="log_price",
            specification={"model": "synthetic_conditional_fe_poisson"},
        )
        if not math.isfinite(ppml["elasticity"]["estimate"]):
            raise RuntimeError("Synthetic conditional FE Poisson elasticity is nonfinite")
        attempts: list[dict[str, object]] = []
        results: list[dict[str, object]] = []
        runner.run_main_models(
            data=data, cache_receipt=cache_receipt, state=state,
            config_sha256=config, attempts=attempts, results=results,
        )
        if not any(row.get("model") == runner.PRIMARY_MODEL for row in results):
            raise RuntimeError("Synthetic full main-model family lost its primary model")
        runner.run_nonparametric_price_bins(
            data=data, state=state, config_sha256=config,
            attempts=attempts, results=results,
        )
        runner.run_conditional_ppml(
            data=data, state=state, config_sha256=config,
            attempts=attempts, results=results,
        )
        if not any(row.get("model", "").startswith("X_conditional_chooser_fe_poisson") for row in results):
            raise RuntimeError("Synthetic full conditional PPML model was not retained")
        runner.attempt_lpm(
            state=state, config_sha256=config, attempts=attempts, results=results,
            model="synthetic_retained_failure",
            fit=lambda: (_ for _ in ()).throw(RuntimeError("synthetic support failure")),
        )
        failure_attempt = next(row for row in attempts if row["model"] == "synthetic_retained_failure")
        if failure_attempt["status"] != "FAILED_RETAINED" or any(
            row.get("model") == "synthetic_retained_failure" for row in results
        ):
            raise RuntimeError("Synthetic model failure was not retained correctly")
        resumed_attempts: list[dict[str, object]] = []
        runner.attempt_lpm(
            state=state, config_sha256=config, attempts=resumed_attempts, results=[],
            model="synthetic_retained_failure",
            fit=lambda: (_ for _ in ()).throw(RuntimeError("must not rerun")),
        )
        if resumed_attempts[0]["error"] != failure_attempt["error"]:
            raise RuntimeError("Retained model-failure checkpoint did not resume identically")
    print("KINDNESS_PRICE_ELASTICITY_SYNTHETIC_PARQUET_TEST_OK", flush=True)


if __name__ == "__main__":
    main()
