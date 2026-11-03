from __future__ import annotations

from pathlib import Path
import shutil

import duckdb

from support import ROOT, write_json, write_table, atomic_text, digest, sha, record, now
from worker import Metrics
from engine import require


def merge_statistics(stats):
    totals, metric_groups = {}, {}
    monthly = []
    for s in sorted(stats, key=lambda x: x["month"]):
        for k, v in s["counts"].items():
            totals[k] = max(totals.get(k, 0), v) if k.startswith("maximum_") else totals.get(k, 0)+v
        for key, values in s["metrics"].items():
            obj = metric_groups.setdefault(key, Metrics())
            obj.merge(values)
            m = Metrics(); m.merge(values)
            arm, group, variant = key.split("|")
            monthly.append({"month": s["month"], "arm": arm, "group": group, "variant": variant, **m.report()})
    pooled = []
    for key, obj in sorted(metric_groups.items()):
        arm, group, variant = key.split("|")
        pooled.append({"arm": arm, "group": group, "variant": variant, **obj.report()})
    return totals, monthly, pooled


def sql_string(s):
    return "'"+str(s).replace("'", "''")+"'"


def exact_summaries(stats, config):
    files = [x["output"]["path"] for x in sorted(stats, key=lambda x: x["month"])]
    run = Path(config["run_root"])
    con = duckdb.connect()
    con.execute("SET threads = "+str(config["workers"]))
    con.execute("SET memory_limit = "+sql_string(str(max(1, config["memory_gb"]-2))+"GB"))
    con.execute("SET temp_directory = "+sql_string(run / "summary_spill_PRIVATE"))
    con.execute("SET preserve_insertion_order=false")
    literal = "["+",".join(sql_string(x) for x in files)+"]"
    con.execute("CREATE VIEW costs AS SELECT * FROM read_parquet("+literal+", hive_partitioning=false)")
    def rows(sql):
        result = con.execute(sql)
        names = [x[0] for x in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()]
    try:
        n, nd = con.execute("SELECT count(*), count(DISTINCT game_id) FROM costs").fetchone()
        require(n == nd, "Duplicate game IDs in final cost sidecar")
        require(n == sum(x["counts"]["rows"] for x in stats), "Final sidecar count differs from worker counts")
        distributions = []
        for group, where in (
            ("meaningful_all", "analysis_eligible_cost"),
            ("meaningful_competitive", "analysis_eligible_cost AND competitive"),
            ("granted_draws", "analysis_eligible_cost AND kind_draw"),
            ("competitive_granted_draws", "analysis_eligible_cost AND competitive AND kind_draw"),
            ("platform_rule_granted_draws", "analysis_eligible_cost AND kind_draw_platform_rule"),
            ("platform_rule_competitive_granted_draws", "analysis_eligible_cost AND competitive AND kind_draw_platform_rule"),
            ("meaningful_excluding_Nov2024", "analysis_eligible_cost AND NOT November_2024")):
            q = rows(f"""SELECT count(*) AS rows,
                avg(old_win_premium) AS old_mean, median(old_win_premium) AS old_median,
                quantile_cont(old_win_premium, .9) AS old_p90, quantile_cont(old_win_premium, .99) AS old_p99,
                sum(old_win_premium) AS old_total,
                avg(chooser_cost_candidate) AS new_mean, median(chooser_cost_candidate) AS new_median,
                quantile_cont(chooser_cost_candidate, .9) AS new_p90,
                quantile_cont(chooser_cost_candidate, .99) AS new_p99, sum(chooser_cost_candidate) AS new_total,
                avg(cost_difference) AS mean_change, median(cost_difference) AS median_change,
                quantile_cont(abs(cost_difference), .99) AS p99_abs_change,
                max(abs(cost_difference)) AS max_abs_change,
                avg(cost_relative_difference) AS mean_relative_change,
                quantile_cont(abs(cost_relative_difference), .99) AS p99_abs_relative_change,
                avg((abs(cost_difference)>.1)::DOUBLE) AS fraction_change_above_point1,
                avg((abs(cost_difference)>.5)::DOUBLE) AS fraction_change_above_point5,
                avg((abs(cost_difference)>1)::DOUBLE) AS fraction_change_above_1,
                corr(old_win_premium, chooser_cost_candidate) AS old_new_correlation,
                sum(chooser_cost_refactor_sensitivity) AS refactor_sensitivity_total,
                max(abs(chooser_cost_refactor_sensitivity-chooser_cost_candidate)) AS refactor_max_abs_difference,
                avg(opponent_benefit_candidate) AS mean_opponent_benefit,
                sum((NOT bot_status_verified)::BIGINT) AS bot_status_assumed_rows,
                sum(factor_from_runtime_era::BIGINT) AS runtime_factor_era_rows
                FROM costs WHERE {where}""")[0]
            distributions.append({"group": group, **q})
        calendar = rows("""SELECT month, api_speed, count(*) AS rows,
            sum(kind_draw::BIGINT) AS grants, avg(old_win_premium) AS old_mean,
            avg(chooser_cost_candidate) AS new_mean,
            avg(cost_difference) AS mean_difference,
            max(abs(cost_difference)) AS max_absolute_difference,
            sum(CASE WHEN kind_draw THEN old_win_premium ELSE 0 END) AS grant_old_total,
            sum(CASE WHEN kind_draw THEN chooser_cost_candidate ELSE 0 END) AS grant_new_total,
            sum(CASE WHEN competitive AND kind_draw THEN chooser_cost_candidate ELSE 0 END) AS competitive_grant_new_total
            FROM costs WHERE analysis_eligible_cost GROUP BY month, api_speed ORDER BY month, api_speed""")
        material = rows("""SELECT month, api_speed, observed_chooser_result,
            historical_material_screen, meaningful_choice AS platform_material_rule,
            material_result_conflict, competitive, count(*) AS rows,
            sum(kind_draw::BIGINT) AS historical_kind_draws,
            sum(kind_draw_platform_rule::BIGINT) AS platform_rule_kind_draws,
            count(chooser_cost_candidate) AS known_action_cost_rows
            FROM costs GROUP BY ALL
            ORDER BY month, api_speed, observed_chooser_result,
                historical_material_screen, platform_material_rule, material_result_conflict, competitive""")
        return {"rows": n, "distinct_games": nd}, distributions, calendar, material
    finally:
        con.close()


def make_report(stats, config, percent, final=False):
    run = Path(config["run_root"])
    report = run / "reports" / f"checkpoint_{percent:03d}"
    report.mkdir(parents=True, exist_ok=True)
    totals, monthly, pooled = merge_statistics(stats)
    write_json(report / "COUNTS.json", totals)
    write_table(report / "monthly_counts", [{"month": s["month"], **s["counts"]} for s in sorted(stats, key=lambda x:x["month"])])
    write_table(report / "validation_monthly", monthly)
    write_table(report / "validation_pooled", pooled)
    method = {
        "status": "COUNTERFACTUAL_COST_AUDIT_COMPLETE" if final else "PARTIAL_MONTH_CHECKPOINT",
        "package_version": config["version"], "run_fingerprint": config["fingerprint"],
        "completed_months": sorted(s["month"] for s in stats), "completed_month_count": len(stats),
        "API_requests": 0, "rating_history_replays": 0, "Stockfish_jobs": 0,
        "worker_count": config["workers"], "memory_budget_gb": config["memory_gb"],
        "batch_rows": config["batch_rows"], "original_fields_overwritten": False,
        "author_exclusion_applied_in_both_roles": True,
        "counterfactuals_condition_on_reconstructed_pre_game_state": True,
        "predictions_use_observed_outcome_to_fit_costs": False,
        "main_core": "skipDeviationIncrease=True; reproduce stored costs first, tolerance 1e-7 points",
        "factor_schedule": config.get("calendar") or {
            "bullet":1.015, "blitz":1.005, "rapid":1.015, "classical":1.015,
            "ultrabullet":1.013, "correspondence":1.0,
            "source":"hardcoded Lichess factors at c06b59cde5b2b763368267e203225c6954e5ba2f",
            "pre_2025_04_17":"assumption, runtime configuration was not archived in Git",
            "old_ultrabullet":"old updater omitted regulation; factor 1 before refactor"},
        "platform_operations": "historical ordering of gain scaling, bot adjustment, +/-700 change cap, sanity reset, 400 floor",
        "bot_status": "optional supplied mapping; unknown accounts assume human for candidate and are counted",
        "regime_times": "source commit timestamps, not authenticated deployment timestamps",
        "november_sensitivity": "2024-11-20 10:24:14Z through 2024-11-22 09:08:03Z: independently solve each outcome volatility and add one period",
        "rounding":"continuous costs; displayed integer changes compared using floor/ceil bracket conditional on predicted change, not exact realized-state bounds",
        "material_rule":"scalachess side-specific rule from cached piece counts and bishop-square colors; historical screen retained separately",
        "primary_validation_masks":"same as earlier Pool_Rating_Validation: stored kind draws and ALL confirmed chooser wins, no material restriction on wins",
        "no_mating_material":"platform predicate determines feasibility; consistent cases have zero action cost; contradictory observed wins have NULL action costs, separate diagnostics",
        "outcome_labels":"stored kind_draw is unchanged; kind_draw_platform_rule is a separate candidate, not an adopted paper outcome",
        "sanity_reset":"actual reset-to-1500 branch reproduced; flagged and excluded from regular cost summaries",
        "inference":"validation describes observed outcomes only; no direct validation of unchosen outcomes, no iid standard errors",
        "publication":"candidate cost layer for review; no automatic replacement of paper estimates",
        "regressions_reestimated":False,
        "parent_manifest_sha256":config["input_identity"], "code_manifest_sha256":config["code_identity"],
        "environment":config["environment"], "generated_at":now()}
    write_json(report / "METHOD.json", method)
    # Copy methodological source provenance, never game/account-level data.
    shutil.copy2(ROOT / "METHODS.md", report / "METHODS.md")
    shutil.copy2(ROOT / "sources/PROVENANCE.json", report / "SOURCE_PROVENANCE.json")
    distributions = []
    if final:
        check, distributions, calendar, material = exact_summaries(stats, config)
        write_json(report / "OUTPUT_CHECKS.json", check)
        write_table(report / "cost_distribution", distributions)
        write_table(report / "cost_changes_by_month_speed", calendar)
        write_table(report / "material_audit", material)
    lines = ["# Counterfactual cost audit", "", method["status"], "",
             f"Completed months: {len(stats)}/24. Retained opportunities: {totals.get('rows',0):,}.",
             "", "The new costs apply the documented gain factors and platform bounds to the recovered pre-update states.",
             "They are conditional candidates: early runtime factors and unobserved bot status are explicitly labelled.",
             "Existing costs are reproduced before any change. No factual history is replayed or altered.", "",
             f"Observed chooser wins failing the historical material screen: {totals.get('wins_failing_historical_material_screen', 0):,}.",
             f"Historical/platform material-rule disagreements: {totals.get('material_rule_disagreements', 0):,}.",
             f"Observed wins inconsistent with the platform material predicate: {totals.get('material_result_conflicts', 0):,}; action costs remain NULL for these rows.",
             f"Draw labels under the platform predicate: {totals.get('draws_added_by_platform_material_rule', 0):,} added, {totals.get('draws_removed_by_platform_material_rule', 0):,} removed relative to the stored outcome. The stored outcome is unchanged.", "",
             "| Outcome | Version | Observed rows | MAE | Bias | MAE improvement |",
             "|---|---|---:|---:|---:|---:|"]
    for r in pooled:
        if r["group"] == "all" and r["arm"] in ("chooser_kind_draw", "chooser_claimed_win"):
            def fmt(k):
                return "NA" if r.get(k) is None else f"{r[k]:.6f}"
            lines.append(f"| {r['arm']} | {r['variant']} | {r['observed']:,} | {fmt('MAE')} | {fmt('bias')} | {fmt('MAE_improvement_over_old_on_same_rows')} |")
    if final:
        lines += ["", "| Cost sample | Old mean | New mean | Mean change | Old total | New total |",
                  "|---|---:|---:|---:|---:|---:|"]
        for r in distributions:
            if r["rows"]:
                lines.append(f"| {r['group']} | {r['old_mean']:.6f} | {r['new_mean']:.6f} | {r['mean_change']:.6f} | {r['old_total']:.3f} | {r['new_total']:.3f} |")
    lines += ["", "Review the month-by-speed validation, early runtime-factor era, whole-November exclusion, and separate transient-refactor sensitivity before adopting the costs.",
              "The diagnostic observed-on-prediction slope is descriptive only and is never fed into an individual prediction.",
              "Continuous changes are not rounded to pretend to recover unknown internal rating fractions.",
              "Cost regressions and manuscript tables have not been automatically replaced.", ""]
    atomic_text(report / "SUMMARY.md", "\n".join(lines))
    return report, totals


def dataset_manifest(stats, config, totals):
    ordered = sorted(stats, key=lambda x:x["month"])
    return {"contract":"COUNTERFACTUAL_COST_CANDIDATE_V1_1", "status":"COUNTERFACTUAL_COST_AUDIT_COMPLETE",
        "package_version":config["version"],
        "run_fingerprint":config["fingerprint"], "code_manifest_sha256":config["code_identity"],
        "parent_manifest_sha256":config["input_identity"], "counts":totals,
        "files":[s["output"] for s in ordered],
        "month_ordered_game_ids_sha256":{s["month"]:s["ordered_game_id_sha256"] for s in ordered},
        "dataset_game_sequence_digest":digest([[s["month"],s["ordered_game_id_sha256"]] for s in ordered]),
        "join_key":["month","game_id"], "ready_for_join":True,
        "ready_to_replace_primary_costs_without_review":False,
        "cost_regressions_reestimated":False,
        "material_rule":"source-based platform predicate, separate historical screen and draw label",
        "action_cost_null_policy":"material_result_conflict=True implies NULL action costs, never an imputed zero",
        "required_analysis_filter":"analysis_eligible_cost=True for meaningful positive-cost summaries",
        "qualifications":["reconstructed state", "factor history before April 2025",
                          "unknown bot status", "commit times are not deployment times"]}
