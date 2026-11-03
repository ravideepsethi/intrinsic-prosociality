from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from engine import (AUTHORS, HARDCODED, REFACTOR, SKIP_FIX, NOVEMBER_START, NOVEMBER_END,
                    require, raw_changes, extra_period_changes, factors_for,
                    platform_transform, conditional_display_interval)
from support import read_json, write_json, sha, stamp, record
from material import MATERIAL_COLUMNS, classify_material

BASE_COLUMNS = ["month", "game_id", "chooser_username_norm", "disconnected_username_norm",
    "chooser_user_id", "disconnected_user_id", "chooser_color", "disconnected_color",
    "chooser_elo", "disconnected_elo", "chooser_pre_rd_v2", "disconnected_pre_rd_v2",
    "chooser_pre_sigma_v2", "disconnected_pre_sigma_v2", "chooser_draw_payoff_v2",
    "chooser_win_payoff_v2", "chooser_win_premium_v2", "api_status", "api_speed", "api_variant",
    "api_rated", "api_last_move_at_ms", "api_created_at_ms", "utc_ms", "pgn_result",
    "white_rating_diff_pgn", "black_rating_diff_pgn", "white_realized_pred_ratingdiff_v2",
    "black_realized_pred_ratingdiff_v2", "pgn_api_result_consistent", "outcome_kind_draw",
    "chooser_has_mating_material", "engine_eval_cp_disconnected", "ply_count", "both_ratingdiff_null",
    "hidden_state_update_applied", "color_adv_applied", "white_rating_source_match",
    "black_rating_source_match", "white_ratingdiff_source_match", "black_ratingdiff_source_match",
    "speed_source_match", "month_source_match", "timeout_draw", "timeout_chooser_win",
    "timeout_chooser_loss"] + MATERIAL_COLUMNS
CONSISTENCY = ["api_rated", "pgn_api_result_consistent", "white_rating_source_match",
    "black_rating_source_match", "white_ratingdiff_source_match", "black_ratingdiff_source_match",
    "speed_source_match", "month_source_match"]
_BOT_CACHE = {}


def array(batch, name, dtype=None, allow_null=False):
    a = batch.column(batch.schema.get_field_index(name))
    require(allow_null or a.null_count == 0, f"Missing required column values: {name}")
    x = a.to_numpy(zero_copy_only=False)
    return np.asarray(x, dtype=dtype) if dtype else np.asarray(x)


def load_bots(path):
    if path is None:
        return None
    if path not in _BOT_CACHE:
        pf = pq.ParquetFile(path)
        require(set(("username_norm", "is_bot")) <= set(pf.schema_arrow.names), "Bot Parquet schema mismatch")
        m = {}
        for b in pf.iter_batches(columns=["username_norm", "is_bot"], batch_size=65536):
            require(b.column(0).null_count == b.column(1).null_count == 0, "Missing bot status")
            require(pa.types.is_boolean(b.schema.field("is_bot").type), "Bot status must be Boolean")
            for name, val in zip(b.column(0).to_pylist(), b.column(1).to_pylist()):
                k = name.strip().lower()
                require(k != "", "Empty bot username")
                require(k not in m or m[k] == val, "Conflicting bot status entries")
                m[k] = val
        _BOT_CACHE[path] = m
    return _BOT_CACHE[path]


class Metrics:
    """Mergeable descriptive moments; no iid standard errors are reported."""
    def __init__(self):
        self.n = self.observed = 0
        self.sum_y = self.sum_y2 = self.sum_x = self.sum_x2 = self.sum_xy = 0.0
        self.sum_err = self.sum_abs = self.sum_sq = self.max_abs = 0.0
        self.within05 = self.within1 = self.within2 = self.within5 = self.opposite = 0
        self.display_bracket = 0
        self.paired_abs_improvement = 0.0
        self.gain_n = 0
        self.gain_xx = self.gain_xy = 0.0

    def add(self, observed, prediction, old_prediction):
        self.n += len(prediction)
        ok = np.isfinite(observed)
        y, x, old = observed[ok], prediction[ok], old_prediction[ok]
        if not len(y):
            return
        err = x-y
        ab = np.abs(err)
        self.observed += len(y)
        self.sum_y += float(y.sum()); self.sum_y2 += float(np.dot(y, y))
        self.sum_x += float(x.sum()); self.sum_x2 += float(np.dot(x, x)); self.sum_xy += float(np.dot(x, y))
        self.sum_err += float(err.sum()); self.sum_abs += float(ab.sum()); self.sum_sq += float(np.dot(err, err))
        self.max_abs = max(self.max_abs, float(ab.max()))
        self.within05 += int((ab <= .5).sum()); self.within1 += int((ab <= 1).sum())
        self.within2 += int((ab <= 2).sum()); self.within5 += int((ab <= 5).sum())
        self.opposite += int(((x*y) < 0).sum())
        low, high = conditional_display_interval(x)
        self.display_bracket += int(((y >= low) & (y <= high)).sum())
        self.paired_abs_improvement += float((np.abs(old-y)-ab).sum())
        # Diagnostic only. This coefficient is NEVER used to alter predictions.
        pos = (x > 1) & (x < 50)
        self.gain_n += int(pos.sum())
        self.gain_xx += float(np.dot(x[pos], x[pos])); self.gain_xy += float(np.dot(x[pos], y[pos]))

    def merge(self, d):
        for k, v in d.items():
            setattr(self, k, max(getattr(self, k), v) if k == "max_abs" else getattr(self, k) + v)

    def report(self):
        n = self.observed
        if not n:
            return {"rows": self.n, "observed": 0, "missing": self.n}
        xx, yy = self.sum_x2-self.sum_x**2/n, self.sum_y2-self.sum_y**2/n
        corr = ((self.sum_xy-self.sum_x*self.sum_y/n)/(xx*yy)**.5) if xx > 0 and yy > 0 else None
        return {"rows": self.n, "observed": n, "missing": self.n-n,
            "coverage_percent": 100*n/self.n,
            "mean_observed": self.sum_y/n, "mean_predicted": self.sum_x/n,
            "bias": self.sum_err/n, "MAE": self.sum_abs/n, "RMSE": (self.sum_sq/n)**.5,
            "correlation": corr, "max_abs_error": self.max_abs,
            "fraction_within_0_5": self.within05/n, "fraction_within_1": self.within1/n,
            "fraction_within_2": self.within2/n, "fraction_above_5": 1-self.within5/n,
            "opposite_nonzero_sign_fraction": self.opposite/n,
            "conditional_display_bracket_coverage": self.display_bracket/n,
            "MAE_improvement_over_old_on_same_rows": self.paired_abs_improvement/n,
            "diagnostic_positive_prediction_n": self.gain_n,
            "diagnostic_observed_on_prediction_slope": self.gain_xy/self.gain_xx if self.gain_xx else None}


def group_metrics(store, label, group, actual, old, new, sensitivity, mask):
    if not mask.any():
        return
    for name, pred in (("old_unregulated", old), ("regulated_candidate", new),
                       ("nov2024_source_window_sensitivity", sensitivity)):
        key = "|".join((label, group, name))
        obj = store.setdefault(key, Metrics())
        obj.add(actual[mask], pred[mask], old[mask])


def compute_batch(batch, month, config, metrics, counts):
    n0 = batch.num_rows
    cn = np.asarray([x.strip().lower() for x in array(batch, "chooser_username_norm")], dtype=object)
    dn = np.asarray([x.strip().lower() for x in array(batch, "disconnected_username_norm")], dtype=object)
    require((cn != "").all() and (dn != "").all(), "Blank player identities")
    exclude = np.isin(cn, AUTHORS) | np.isin(dn, AUTHORS)
    counts["input_rows"] += n0
    counts["author_games_removed"] += int(exclude.sum())
    if config["already_author_excluded"]:
        require(not exclude.any(), "Author account remains in the authenticated excluded sample")
    if exclude.any():
        batch = batch.filter(pa.array(~exclude))
        cn, dn = cn[~exclude], dn[~exclude]
    n = batch.num_rows
    if not n:
        return None
    def a(name, dtype=None, nullable=False):
        return array(batch, name, dtype, allow_null=nullable)
    require((a("month") == month).all(), "Month partition/value disagreement")
    require((a("api_status") == "timeout").all(), "Non-timeout input")
    require((a("api_variant") == "standard").all(), "Non-standard input")
    for col in CONSISTENCY:
        require(a(col, bool).all(), "Source consistency failure: " + col)
    require(not a("color_adv_applied", bool).any(), "Unsupported post-November-2025 color adjustment")
    white = a("chooser_color") == "white"
    require(np.isin(a("chooser_color"), ["white", "black"]).all(), "Unknown chooser color")
    require((a("disconnected_color") == np.where(white, "black", "white")).all(), "Role mismatch")
    result = a("pgn_result")
    require(np.isin(result, ["1-0", "0-1", "1/2-1/2"]).all(), "Unknown result")
    draw = result == "1/2-1/2"
    win = ((result == "1-0") & white) | ((result == "0-1") & ~white)
    loss = ~(draw | win)
    for flag, derived in (("timeout_draw", draw), ("timeout_chooser_win", win), ("timeout_chooser_loss", loss)):
        require(np.array_equal(a(flag, bool), derived), "Outcome classification mismatch: " + flag)
    cached_material = a("chooser_has_mating_material", bool)
    kind = a("outcome_kind_draw", bool)
    require(np.array_equal(kind, draw & cached_material), "Kind-draw/material inconsistency")
    historical, meaningful, fen_checks = classify_material(batch, white)
    require(np.array_equal(cached_material, historical), "Cached historical material screen/count mismatch")
    # The historical screen is not the platform rule. Never require it for wins.
    material_disagreement = cached_material != meaningful
    material_conflict = win & ~meaningful
    action_known = ~material_conflict
    platform_kind = draw & meaningful
    r, ro = a("chooser_elo", float), a("disconnected_elo", float)
    rd, rdo = a("chooser_pre_rd_v2", float), a("disconnected_pre_rd_v2", float)
    sig, sigo = a("chooser_pre_sigma_v2", float), a("disconnected_pre_sigma_v2", float)
    for x in (sig, sigo):
        require(np.isfinite(x).all() and ((x > 0) & (x <= .100001)).all(), "Invalid recovered volatility")
    for x in (r, ro):
        require(np.isfinite(x).all() and ((x >= 400) & (x < 4000)).all(), "Invalid anchored rating")
    raw, other = raw_changes(r, rd, ro, rdo), raw_changes(ro, rdo, r, rd)
    rg, rc, cost = a("chooser_draw_payoff_v2", float), a("chooser_win_payoff_v2", float), a("chooser_win_premium_v2", float)
    for name, new, old in (("draw", raw["draw"], rg), ("win", raw["win"], rc),
                           ("premium", raw["K"]*.5, cost)):
        error = float(np.abs(new-old).max())
        counts["maximum_core_reproduction_error"] = max(counts["maximum_core_reproduction_error"], error)
        require(error <= 1e-7 and np.isfinite(old).all(), f"Stored {name} does not match reconstructed core")
    require(np.allclose(rc-rg, cost, atol=1e-8, rtol=1e-12), "Old premium identity mismatch")
    t = a("api_last_move_at_ms", np.int64)
    require((t >= a("api_created_at_ms", np.int64)).all(), "Completion before creation")
    speed = np.char.lower(a("api_speed").astype(str))
    factor, factor_evidence = factors_for(speed, t, config.get("calendar"))
    bot_map = load_bots(config.get("bot_status"))
    if bot_map is None:
        known = np.zeros(n, bool); cb = np.zeros(n, bool); db = np.zeros(n, bool)
    else:
        known = np.array([x in bot_map and y in bot_map for x, y in zip(cn, dn)])
        cb = np.array([bot_map.get(x, False) for x in cn], bool)
        db = np.array([bot_map.get(x, False) for x in dn], bool)
    halfc, halfd = (~cb & db), (~db & cb)
    updated = {}; flags = {}
    for side, rr, changes, half in (("c", r, raw, halfc), ("d", ro, other, halfd)):
        for outcome in ("draw", "win", "loss"):
            value, flag = platform_transform(rr, changes[outcome], factor, t, half)
            updated[side+"_"+outcome] = value
            flags[side+"_"+outcome] = flag
    c_draw, c_win = updated["c_draw"], updated["c_win"]
    c_claim = np.where(meaningful, c_win, c_draw)
    new_cost = c_claim-c_draw
    opp_gain = np.where(meaningful, updated["d_draw"]-updated["d_loss"], 0.)
    reset = np.logical_or.reduce([flags[k]["sanity_reset"] for k in ("c_draw","c_win","d_draw","d_loss")])
    require(((new_cost >= -1e-9) | reset).all(), "Nonmonotone candidate outside platform sanity-reset cases")
    sensible = meaningful & ~reset & action_known
    window = (t >= REFACTOR) & (t < SKIP_FIX)
    nov = (t >= NOVEMBER_START) & (t < NOVEMBER_END)
    alt_draw, alt_win, alt_opp = c_draw.copy(), c_win.copy(), opp_gain.copy()
    alt_actual_d = np.select([draw, win], [updated["d_draw"], updated["d_loss"]], default=updated["d_win"])
    if window.any():
        ex = extra_period_changes(r[window], rd[window], sig[window], ro[window], rdo[window])
        exd = extra_period_changes(ro[window], rdo[window], sigo[window], r[window], rd[window])
        xd = {k: platform_transform(r[window], ex[k], factor[window], t[window], halfc[window])[0]
              for k in ("draw", "win", "loss")}
        od = {k: platform_transform(ro[window], exd[k], factor[window], t[window], halfd[window])[0]
              for k in ("draw", "win", "loss")}
        alt_draw[window], alt_win[window] = xd["draw"], xd["win"]
        alt_opp[window] = np.where(meaningful[window], od["draw"]-od["loss"], 0.)
        alt_actual_d[window] = np.select([draw[window], win[window]], [od["draw"], od["loss"]], default=od["win"])
    alt_cost = np.where(meaningful, alt_win-alt_draw, 0.)
    obs_w, obs_b = a("white_rating_diff_pgn", float, True), a("black_rating_diff_pgn", float, True)
    for o in (obs_w, obs_b):
        require(not np.isinf(o).any(), "Infinite observed rating change")
        finite = o[np.isfinite(o)]
        require((finite == np.trunc(finite)).all(), "Recorded changes must be integers")
    missing_both = np.isnan(obs_w) & np.isnan(obs_b)
    require(np.array_equal(missing_both, a("both_ratingdiff_null", bool)), "Missingness flag mismatch")
    require(np.array_equal(~missing_both, a("hidden_state_update_applied", bool)), "State-update flag mismatch")
    obs_c, obs_d = np.where(white, obs_w, obs_b), np.where(white, obs_b, obs_w)
    old_actual = np.select([draw, win], [raw["draw"], raw["win"]], default=raw["loss"])
    old_other = np.select([draw, win], [other["draw"], other["loss"]], default=other["win"])
    stored_w, stored_b = a("white_realized_pred_ratingdiff_v2", float), a("black_realized_pred_ratingdiff_v2", float)
    require(np.allclose(old_actual, np.where(white, stored_w, stored_b), atol=1e-7, rtol=1e-12),
            "Chooser realized prediction is not the reconstructed core")
    require(np.allclose(old_other, np.where(white, stored_b, stored_w), atol=1e-7, rtol=1e-12),
            "Opponent realized prediction is not the reconstructed core")
    new_actual = np.select([draw, win], [c_draw, c_win], default=updated["c_loss"])
    alt_actual = np.select([draw, win], [alt_draw, alt_win], default=updated["c_loss"])
    # A chooser loss is a supplemental data diagnostic, not a claim/grant choice.
    if window.any() and loss[window].any():
        alt_actual[window] = np.select([draw[window], win[window]], [xd["draw"], xd["win"]], default=xd["loss"])
    new_other = np.select([draw, win], [updated["d_draw"], updated["d_loss"]], default=updated["d_win"])
    cp = a("engine_eval_cp_disconnected", float)
    competitive = cp >= -100
    groups = {"all": np.ones(n, bool), "competitive": competitive,
        "clearly_lost": cp <= -300, "both_RD_le110": (rd <= 110) & (rdo <= 110),
        "own_RD_gt110": rd > 110, "costly_draw": rg < 0, "favorable_draw": rg >= 0,
        "runtime_setting_era": t < HARDCODED, "hardcoded_source_era": t >= HARDCODED,
        "exclude_November_2024": ~nov, "Nov2024_refactor_source_window": window,
        "bot_status_verified": known, "bot_status_assumed": ~known,
        "cached_material_screen_fails": ~cached_material,
        "material_rules_disagree": material_disagreement,
        "material_result_conflict": material_conflict}
    for sp in np.unique(speed):
        groups["speed="+sp] = speed == sp
    # Primary masks exactly preserve the earlier Pool_Rating_Validation definition.
    for label, mask in (("chooser_kind_draw", kind), ("chooser_claimed_win", win),
                        ("chooser_all_draws", draw), ("chooser_draw_failing_material", draw & ~cached_material),
                        ("chooser_draw_platform_material", platform_kind),
                        ("chooser_draw_without_platform_material", draw & ~meaningful), ("chooser_loss", loss)):
        for gn, gm in groups.items():
            group_metrics(metrics, label, gn, obs_c, old_actual, new_actual, alt_actual, mask & gm)
    for label, mask in (("opponent_draw", draw), ("opponent_loss", win), ("opponent_win", loss)):
        for gn in ("all", "competitive", "both_RD_le110"):
            group_metrics(metrics, label, gn, obs_d, old_other, new_other, alt_actual_d, mask & groups[gn])
    values = {"rows": n, "kind_draws": int(kind.sum()), "competitive_rows": int(competitive.sum()),
        "competitive_grants": int((competitive & kind).sum()), "meaningful_choices": int(meaningful.sum()),
        "no_material": int((~meaningful).sum()), "chooser_losses": int(loss.sum()),
        "actual_draws": int(draw.sum()), "chooser_claimed_wins": int(win.sum()),
        "historical_no_material": int((~cached_material).sum()),
        "wins_failing_historical_material_screen": int((win & ~cached_material).sum()),
        "material_rule_disagreements": int(material_disagreement.sum()),
        "historical_false_platform_true": int((~cached_material & meaningful).sum()),
        "historical_true_platform_false": int((cached_material & ~meaningful).sum()),
        "material_result_conflicts": int(material_conflict.sum()), "bishop_color_fen_checks": fen_checks,
        "platform_rule_kind_draws": int(platform_kind.sum()),
        "draws_added_by_platform_material_rule": int((platform_kind & ~kind).sum()),
        "draws_removed_by_platform_material_rule": int((kind & ~platform_kind).sum()),
        "competitive_draws_added_by_platform_material_rule": int((competitive & platform_kind & ~kind).sum()),
        "competitive_draws_removed_by_platform_material_rule": int((competitive & kind & ~platform_kind).sum()),
        "source_refactor_window_rows": int(window.sum()), "November_2024_rows": int(nov.sum()),
        "runtime_factor_assumption_rows": int((t < HARDCODED).sum()), "unknown_bot_status_rows": int((~known).sum()),
        "human_vs_bot_rows": int((halfc | halfd).sum()), "sanity_reset_rows": int(reset.sum()),
        "rating_floor_rows": int(np.logical_or.reduce([f["rating_floor"] for f in flags.values()]).sum()),
        "delta_cap_rows": int(np.logical_or.reduce([f["delta_cap"] for f in flags.values()]).sum()),
        "both_observed_changes_missing": int(missing_both.sum())}
    for k, value in values.items():
        counts[k] = counts.get(k, 0) + value
    gids = a("game_id")
    require(all(isinstance(x, str) and x and "\n" not in x for x in gids), "Invalid game IDs")
    # Compact sidecar: identifiers remain private. No full panel is duplicated.
    return pa.table({
        "game_id": gids, "month": np.repeat(month, n), "api_speed": speed,
        "chooser_user_id": a("chooser_user_id", np.int64), "disconnected_user_id": a("disconnected_user_id", np.int64),
        "completion_ms": t, "kind_draw": kind, "competitive": competitive,
        "observed_chooser_result": np.select([draw, win], ["draw", "win"], default="loss"),
        "historical_material_screen": cached_material, "kind_draw_platform_rule": platform_kind,
        "material_rule_disagreement": material_disagreement, "material_result_conflict": material_conflict,
        "action_cost_known": action_known,
        "meaningful_choice": meaningful, "sanity_reset": reset, "analysis_eligible_cost": sensible,
        "bot_status_verified": known, "factor_from_runtime_era": t < HARDCODED,
        "gain_factor": factor, "nov2024_source_window": window, "November_2024": nov,
        "old_draw_payoff": rg, "old_win_payoff": rc, "old_win_premium": cost,
        "chooser_draw_payoff_candidate": c_draw, "chooser_win_payoff_candidate": c_win,
        "chooser_win_minus_draw_candidate": c_win-c_draw,
        "chooser_claim_action_payoff_candidate": pa.array(c_claim, mask=~action_known),
        "chooser_cost_candidate": pa.array(new_cost, mask=~action_known),
        "opponent_draw_payoff_candidate": updated["d_draw"], "opponent_loss_payoff_candidate": updated["d_loss"],
        "opponent_benefit_candidate": pa.array(opp_gain, mask=~action_known),
        "chooser_cost_refactor_sensitivity": pa.array(alt_cost, mask=~action_known),
        "opponent_benefit_refactor_sensitivity": pa.array(alt_opp, mask=~action_known),
        "cost_difference": pa.array(new_cost-cost, mask=~action_known),
        "cost_relative_difference": pa.array((new_cost-cost)/cost, mask=~action_known),
        "candidate_factor_assumption": np.asarray(factor_evidence, str)})


def process_month(item, config):
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    folder = Path(config["run_root"]) / "months" / item["month"]
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "_SUCCESS.json"
    out = folder / "costs_PRIVATE.parquet"
    if done.is_file():
        receipt = read_json(done)
        require(receipt["fingerprint"] == config["fingerprint"] and receipt["input_sha256"] == item["sha256"],
                "Month checkpoint belongs to a different computation")
        for name, expected in receipt["files"].items():
            p = folder/name
            require(p.is_file() and sha(p) == expected, "Corrupt month checkpoint: " + item["month"])
        require(stamp(item["path"]) == item["stamp"], "Input changed after authentication")
        return read_json(folder / "statistics.json")
    require(stamp(item["path"]) == item["stamp"], "Input changed before month computation")
    start = time.monotonic()
    pf = pq.ParquetFile(item["path"])
    missing = set(BASE_COLUMNS)-set(pf.schema_arrow.names)
    require(not missing, "Required cached state fields missing: " + ", ".join(sorted(missing)))
    counts = {"input_rows": 0, "author_games_removed": 0, "maximum_core_reproduction_error": 0.}
    metrics = {}; writer = None; ordered = hashlib.sha256()
    temp = out.with_suffix(".parquet.partial")
    try:
        for b in pf.iter_batches(columns=BASE_COLUMNS, batch_size=config["batch_rows"], use_threads=False):
            result = compute_batch(b, item["month"], config, metrics, counts)
            if result is not None:
                if writer is None:
                    writer = pq.ParquetWriter(temp, result.schema, compression="zstd", compression_level=3,
                        use_dictionary=["month", "api_speed", "candidate_factor_assumption"])
                writer.write_table(result, row_group_size=config["batch_rows"])
                for gid in result["game_id"].to_pylist():
                    ordered.update(gid.encode()+b"\n")
            write_json(folder / "progress.json", {"input_rows_done": counts["input_rows"],
                        "input_rows_total": item["rows"], "elapsed_seconds": time.monotonic()-start})
        require(writer is not None, "Empty monthly analytical file")
        writer.close(); writer = None
        require(counts["input_rows"] == item["rows"], "Month row count changed")
        require(stamp(item["path"]) == item["stamp"], "Input changed while being processed")
        os.replace(temp, out)
        stats = {"month": item["month"], "counts": counts,
                 "metrics": {k: vars(v) for k,v in metrics.items()},
                 "ordered_game_id_sha256": ordered.hexdigest(),
                 "elapsed_seconds": time.monotonic()-start,
                 "output": record(out, rows=counts["rows"])}
        write_json(folder / "statistics.json", stats)
        write_json(done, {"fingerprint": config["fingerprint"], "input_sha256": item["sha256"],
            "files": {"costs_PRIVATE.parquet": stats["output"]["sha256"],
                      "statistics.json": sha(folder / "statistics.json")}})
        return stats
    finally:
        if writer is not None:
            writer.close()
