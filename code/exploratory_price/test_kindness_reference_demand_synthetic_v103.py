#!/usr/bin/env python3
"""Synthetic compressed-Parquet regression test for reference-demand v1.0.3."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile

import kindness_price_elasticity_common_v102 as common
import run_kindness_price_elasticity_v102 as legacy
import run_kindness_reference_demand_v103 as module


def main() -> None:
    _, np, pa, pq = common.import_dependencies()
    rng = np.random.default_rng(20260826)
    chooser_count = 400
    per_chooser = 80
    rows = chooser_count * per_chooser
    chooser = np.repeat(np.arange(chooser_count, dtype=np.int64), per_chooser)
    sequence = np.tile(np.arange(per_chooser, dtype=np.int64), chooser_count)
    representatives = np.asarray(
        [-7.0, -5.0, -3.0, -1.5, -0.75, -0.35, -0.175, -0.05,
         0.05, 0.175, 0.35, 0.75, 1.5, 3.0, 5.0, 7.0],
        dtype=np.float64,
    )
    template = np.concatenate((representatives, np.linspace(-7.5, 7.5, per_chooser - 16)))
    draw = np.tile(template, chooser_count)
    draw += rng.normal(0.0, 0.005, size=rows)
    rd = 45.0 + (chooser % 25) + rng.normal(0.0, 2.0, size=rows)
    opponent_rd = 50.0 + (sequence % 20) + rng.normal(0.0, 2.0, size=rows)
    price = np.exp(1.45 + 0.010 * rd + 0.003 * opponent_rd + rng.normal(0, 0.18, rows))
    log_price = np.log(price)
    latent = (
        -3.65
        - 0.12 * np.log(np.maximum(-draw, 0.02)) * (draw < 0)
        + 0.30 * (draw >= 0)
        + 0.025 * np.maximum(draw, 0)
        + 0.08 * log_price
        + rng.normal(0, 0.45, rows)
    )
    probability = 1.0 / (1.0 + np.exp(-latent))
    kind = (rng.random(rows) < probability).astype(np.int8)
    # Guarantee informative chooser support without dictating the fitted sign.
    kind[::per_chooser] = 1
    kind[1::per_chooser] = 0
    kind[8::per_chooser] = 1
    price_edges = np.quantile(price, np.linspace(0, 1, 21))
    draw_edges20 = np.quantile(draw, np.linspace(0, 1, 21))
    draw_edges50 = np.quantile(draw, np.linspace(0, 1, 51))
    price_bin20 = np.digitize(price, price_edges[1:-1]).astype(np.int8)
    draw_bin20 = np.digitize(draw, draw_edges20[1:-1]).astype(np.int8)
    draw_bin50 = np.digitize(draw, draw_edges50[1:-1]).astype(np.int8)
    engine_eval = rng.normal(40, 160, rows)
    clock_a = np.log1p(rng.uniform(0, 180, rows))
    clock_b = np.log1p(rng.uniform(0, 180, rows))

    arrays = {
        "row_id": np.arange(rows, dtype=np.int64),
        "chooser_index": chooser,
        "kind": kind,
        "price": price,
        "log_price": log_price,
        "draw_payoff": draw,
        "engine_eval_cp": engine_eval,
        "chooser_elo": 1400 + (chooser % 1200),
        "opponent_elo": 1400 + (sequence * 17) % 1200,
        "chooser_rd": rd,
        "opponent_rd": opponent_rd,
        "log_chooser_clock": clock_a,
        "log_opponent_clock": clock_b,
        "tournament": (sequence % 7 == 0).astype(np.int8),
        "month_code": (sequence % 24).astype(np.int8),
        "speed_code": (sequence % 5).astype(np.int8),
        "rating_band": (chooser % 4).astype(np.int8),
        "eval_band": (sequence % 5).astype(np.int8),
        "hour_of_week": (sequence * 3 % 168).astype(np.int16),
        "both_rd_le_110": np.ones(rows, dtype=np.int8),
        "activity_quartile": (chooser % 4).astype(np.int8),
        "prior_kind_stratum": (sequence % 3).astype(np.int8),
        "price_bin20": price_bin20,
        "draw_bin20": draw_bin20,
        "draw_bin50": draw_bin50,
        "row_hash": np.arange(rows, dtype=np.int64),
    }
    with tempfile.TemporaryDirectory(prefix="reference_demand_v103_synthetic_") as temp:
        root = Path(temp)
        parquet = root / "synthetic.parquet"
        pq.write_table(pa.table(arrays), parquet, compression="zstd", row_group_size=1_000)
        loaded = legacy.load_arrays(parquet)
        if loaded["kind"].size != rows or not np.allclose(loaded["draw_payoff"], draw):
            raise RuntimeError("Synthetic Parquet round trip changed rows or draw payoff")

        all_rows = np.ones(rows, dtype=bool)
        piecewise = module.fit_reference_piecewise(
            data=loaded,
            mask=all_rows,
            model="synthetic_piecewise",
            role="synthetic_test",
            premium_mode="bin20_fe",
        )
        required_terms = {
            "positive_draw_payoff", "negative_draw_payoff", "draw_nonnegative"
        }
        if not required_terms.issubset(module.term_map(piecewise)):
            raise RuntimeError("Synthetic piecewise model lost required terms")

        loss = loaded["draw_payoff"] < 0
        loss_model = module.fit_side_model(
            data=loaded,
            mask=loss,
            model="synthetic_loss_log",
            side="loss",
            transform="log",
            premium_mode="bin20_fe",
        )
        elasticity = float(loss_model["elasticity"]["estimate"])
        if not math.isfinite(elasticity):
            raise RuntimeError("Synthetic loss elasticity is nonfinite")

        zero = module.fit_zero_contrast(
            data=loaded,
            mask=np.abs(loaded["draw_payoff"]) <= 1.0,
            model="synthetic_zero",
            role="synthetic_test",
            premium_mode="level",
        )
        if not math.isfinite(
            float(module.term_map(zero)["above_cutoff"]["coefficient_probability_units"])
        ):
            raise RuntimeError("Synthetic zero contrast is nonfinite")

        attempts: list[dict[str, object]] = []
        results: list[dict[str, object]] = []
        config_sha = "synthetic-config"
        state = root / "state"
        module.run_piecewise_family(
            data=loaded,
            state=state,
            config_sha256=config_sha,
            attempts=attempts,
            results=results,
        )
        matched, donuts = module.run_matched_windows(
            data=loaded,
            state=state,
            config_sha256=config_sha,
            attempts=attempts,
            results=results,
        )
        placebos = module.run_local_shape_and_placebos(
            data=loaded,
            state=state,
            config_sha256=config_sha,
            attempts=attempts,
            results=results,
        )
        side_data = module.side_masks_and_transforms(loaded)
        module.run_side_elasticities(
            data=loaded,
            side_data=side_data,
            state=state,
            config_sha256=config_sha,
            attempts=attempts,
            results=results,
        )
        schedule, arcs, adjacent = module.run_nonparametric_schedule(
            data=loaded,
            state=state,
            config_sha256=config_sha,
            attempts=attempts,
            results=results,
        )
        if len(schedule) != len(module.SIGNED_LABELS) or not arcs:
            raise RuntimeError("Synthetic nonparametric schedule is incomplete")
        if adjacent.get("elasticity_status") != "UNDEFINED_BECAUSE_REFERENCE_PRICE_EQUALS_ZERO":
            raise RuntimeError("Synthetic zero-price status changed")
        heterogeneity = module.run_heterogeneity(
            data=loaded,
            side_data=side_data,
            state=state,
            config_sha256=config_sha,
            attempts=attempts,
            results=results,
        )
        module.run_side_ppml(
            data=loaded,
            side_data=side_data,
            state=state,
            config_sha256=config_sha,
            attempts=attempts,
            results=results,
        )
        local = module.loss_local_elasticity_table(
            data=loaded, side_data=side_data, results=results
        )
        interpretation = module.interpretation(
            results=results,
            matched=matched,
            validation={"status": "SYNTHETIC_VALIDATION_BYPASS"},
            prior_v102={"elasticity_estimate": 0.1570280092407992},
        )
        if not matched or not donuts or not placebos or not heterogeneity or not local:
            raise RuntimeError("Synthetic retained output family is incomplete")
        if interpretation.get("global_signed_log_elasticity_status") != "NOT_MATHEMATICALLY_DEFINED":
            raise RuntimeError("Synthetic interpretation changed the signed-price boundary")
        primary_loss = module.find_result(results, module.PRIMARY_LOSS_MODEL)
        primary_reference = module.find_result(results, module.PRIMARY_REFERENCE_MODEL)
        if primary_loss is None or primary_reference is None:
            raise RuntimeError("Synthetic primary reference models were not retained")
        if not any(row.get("status") == "FAILED_RETAINED" for row in attempts):
            raise RuntimeError("Synthetic family did not exercise failed-result retention")
        if any(Path(temp).rglob("*.parquet")) is False:
            raise RuntimeError("Synthetic test did not exercise Parquet")

    print("KINDNESS_REFERENCE_DEMAND_SYNTHETIC_PARQUET_TEST_OK")


if __name__ == "__main__":
    main()
