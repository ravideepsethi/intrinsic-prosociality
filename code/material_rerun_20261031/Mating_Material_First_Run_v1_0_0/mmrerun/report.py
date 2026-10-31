from __future__ import annotations
from collections import Counter
from pathlib import Path
import os
import zipfile
from .io import database, scan, require, csv_file, save, load, record, sha, atomic_text, copy_query, digest, verify
from .inputs import BASELINE
from .material import CASE_NAMES, RULE

STATES = ["clearly_worse", "modestly_worse", "roughly_equal", "better", "clearly_better"]
OUTCOMES = ["draw", "chooser_win", "chooser_loss"]
STAGE_LABELS = ["0-4", "5-6", "7-8", "9-10", "11-20", "21-40", "41-80", "81+"]
STAGE_SQL = "CASE WHEN ply<=4 THEN 0 WHEN ply<=6 THEN 1 WHEN ply<=8 THEN 2 WHEN ply<=10 THEN 3 WHEN ply<=20 THEN 4 WHEN ply<=40 THEN 5 WHEN ply<=80 THEN 6 ELSE 7 END"

PENDING = [
    ("tab_main", "Position, region-specific stage and gap; same chooser FE and covariance", "R11 region-gap producer"),
    ("tab_app_main_spec", "Clocks, alternative controls, common-gap comparison", "R11 + Wave1 core"),
    ("tab_app_equalweights", "Three weighting rules", "Wave1 panel robustness"),
    ("tab_app_merit_continuous", "Spline and covariance", "Continuous Merit + R11 continuous"),
    ("tab_app_stage_speed", "Stage by speed", "R11 + v143 prose checks"),
    ("tab_app_responsibility", "Deliberate-departure proxies", "v141 responsibility remaining"),
    ("fig_countdown", "Countdown threshold profiles", "Countdown_Estimation_v1_0_0"),
    ("tab_app_countdown", "Countdown threshold fits", "Countdown_Estimation_v1_0_0"),
    ("tab_app_tenure_arena_repeat", "Tenure, arena and repeat sensitivities", "v141 remaining workers"),
    ("tab_app_repeat", "Pair histories and re-encounter", "First Repeat + Reputation"),
    ("tab_app_rating", "Rating-gap profile and adjacent levels", "Wave1 KRD + C9"),
    ("tab_app_stakes", "Percentile and personal scales", "Stakes producer"),
    ("tab_persistence", "Persistence and account bootstrap, 1999 resamples", "v142 corrected persistence + Submission_Checks_20261025"),
    ("tab_supp_state_regressions", "Weighted state regressions", "v142 original_f_v102"),
    ("tab_patron", "Fixed acquisition design and snapshot; rebuilt behavior", "v141 Patron adapters"),
    ("tab_dynamics", "Matched receipt and interval outcomes", "R8 Independent + companion receipt core"),
    ("tab_iv_main", "Uniform90 primary and both placebos", "Uniform90 v105, rebuild from candidate universe"),
    ("fig_iv_bins", "Residualized first-stage bins", "Model5_FirstStageBins_v1_0_0"),
    ("tab_app_iv_companions", "Spaced variants, balance, entry, exclusion, compliers, mechanisms", "R9/R12 + Model5 Submission"),
    ("tab_app_receipt_kind", "Merited and unmerited frames", "Receipt_IV_Position_v1_0_0"),
    ("tab_app_receipt_patron", "Fixed profile acquisition and IPW", "Patron_Model5_v1_0_0"),
    ("tab_supp_iv_specs", "Subgroups, exposure variants, alternate scores", "R9/R12 + Model5 supplements"),
]


def rows(c, sql):
    result = c.execute(sql)
    names = [d[0] for d in result.description]
    return [dict(zip(names, r)) for r in result.fetchall()]


def aggregate_audits(audits, report):
    report = Path(report)
    totals = {}
    cross, dropped = Counter(), Counter()
    monthly = []
    for a in sorted(audits, key=lambda r: (r["family"], r["month"])):
        totals.setdefault(a["family"], Counter()).update(a["counts"])
        monthly.append(dict(family=a["family"], month=a["month"], **a["counts"]))
        for r in a["crosstab"]:
            cross[(a["family"], r["outcome"], r["old_pass"], r["new_pass"])] += r["rows"]
        for r in a["dropped_cases"]:
            dropped[(a["family"], r["case"], r["outcome"], r["state"])] += r["rows"]
    csv_file(report / "sample_flow_by_month.csv", monthly)
    csv_file(report / "old_new_rule_crosstab.csv", [dict(family=f, outcome=OUTCOMES[o], old_pass=bool(old), new_pass=bool(new), rows=n)
              for (f, o, old, new), n in sorted(cross.items())])
    csv_file(report / "dropped_by_case_outcome_state.csv", [dict(family=f, case=k, case_name=CASE_NAMES[k],
              outcome=OUTCOMES[o], state=STATES[s], rows=n) for (f, k, o, s), n in sorted(dropped.items())],
              fields=["family", "case", "case_name", "outcome", "state", "rows"])
    return {k: dict(v) for k, v in totals.items()}


def census(c, files, family, private):
    selected = [r for r in files if r["family"] == family]
    cache_path = Path(private)/"census"/(family+".json")
    cache_key = digest(["census_v1",[(r["month"],r["files"][0]["sha256"]) for r in selected]])
    if cache_path.exists():
        cached = load(cache_path)
        require(cached["key"]==cache_key,"Census cache identity differs")
        verify(cached["account"])
        return cached["counts"],Path(cached["account"]["path"])
    paths = [r["files"][0]["path"] for r in files if r["family"] == family]
    c.execute("CREATE OR REPLACE VIEW d AS SELECT * FROM " + scan(paths) + " WHERE author_clean")
    counts = rows(c, """SELECT count(*) opportunities, count(DISTINCT game_id) unique_games,
        sum(old_grant)::BIGINT grants,
        count(*) FILTER(WHERE state>=2) competitive,
        sum(old_grant) FILTER(WHERE state>=2)::BIGINT competitive_grants,
        count(*) FILTER(WHERE state=0) clearly_worse,
        sum(old_grant) FILTER(WHERE state=0)::BIGINT clearly_worse_grants,
        count(*) FILTER(WHERE keep) new_opportunities,
        sum(grant)::BIGINT new_grants,
        count(*) FILTER(WHERE keep AND state>=2) new_competitive,
        sum(grant) FILTER(WHERE state>=2)::BIGINT new_competitive_grants,
        count(*) FILTER(WHERE keep AND state=0) new_clearly_worse,
        sum(grant) FILTER(WHERE state=0)::BIGINT new_clearly_worse_grants
        FROM d""")[0]
    counts = {k: 0 if v is None else int(v) for k, v in counts.items()}
    require(counts["opportunities"] == counts["unique_games"], "Duplicate game IDs in " + family)
    account = Path(private) / (family + "_account_counts_PRIVATE.parquet")
    copy_query(c, """SELECT chooser, count(*)::BIGINT old_n, sum(old_grant)::BIGINT old_g,
        count(*) FILTER(WHERE keep)::BIGINT new_n, sum(grant)::BIGINT new_g,
        count(*) FILTER(WHERE state>=2)::BIGINT old_n_c,
        sum(old_grant) FILTER(WHERE state>=2)::BIGINT old_g_c,
        count(*) FILTER(WHERE state>=2 AND keep)::BIGINT new_n_c,
        sum(grant) FILTER(WHERE state>=2)::BIGINT new_g_c,
        count(*) FILTER(WHERE state=0)::BIGINT old_n_l,
        sum(old_grant) FILTER(WHERE state=0)::BIGINT old_g_l,
        count(*) FILTER(WHERE state=0 AND keep)::BIGINT new_n_l,
        sum(grant) FILTER(WHERE state=0)::BIGINT new_g_l
        FROM d GROUP BY chooser""", account)
    c.execute("CREATE OR REPLACE VIEW a AS SELECT * FROM " + scan([account]))
    counts.update(rows(c, """SELECT count(*) choosers, count(*) FILTER(WHERE old_g>0) granters,
       count(*) FILTER(WHERE new_n>0) new_choosers, count(*) FILTER(WHERE new_g>0) new_granters,
       count(*) FILTER(WHERE new_n=0) accounts_losing_all_opportunities,
       count(*) FILTER(WHERE old_g=0 AND new_g>0) accounts_newly_granting,
       count(*) FILTER(WHERE old_g>0 AND new_g=0) accounts_losing_all_grants,
       count(*) FILTER(WHERE new_g_c>0) new_competitive_granters
       FROM a""")[0])
    save(cache_path,dict(key=cache_key,counts=counts,account=record(account)))
    return counts, account


def reconcile(config, audits, enforce_baseline=True):
    run = Path(config["run"])
    report = run / "report"
    report.mkdir(parents=True, exist_ok=True)
    totals = aggregate_audits(audits, report)
    checks = []
    with database(run / "PRIVATE/spill/reconcile", max(1, config["memory_gb"]-3), min(4, config["workers"])) as c:
        censuses = {}
        for family in ("main", "all_source"):
            if family not in totals:
                continue
            counts, account = census(c, audits, family, run / "PRIVATE")
            censuses[family] = counts
            t = totals[family]
            if family == "main" and enforce_baseline:
                for key, value in BASELINE.items():
                    checks.append(dict(family=family, check="baseline_" + key, actual=counts[key], expected=value,
                                       passed=counts[key] == value))
            identity = [
                ("zero_win_conflicts", t["zero_win_conflicts"], 0),
                ("chooser_loss_conflicts", t["chooser_loss_conflicts"], 0),
                ("opportunity_identity", counts["new_opportunities"], counts["opportunities"]-t["dropped"]),
                ("grant_identity", counts["new_grants"], counts["grants"]+t["reclassified_draws"]-t["removed_old_grants"]),
                ("chooser_identity", counts["new_choosers"], counts["choosers"]-counts["accounts_losing_all_opportunities"]),
                ("granter_identity", counts["new_granters"], counts["granters"]+counts["accounts_newly_granting"]-counts["accounts_losing_all_grants"]),
            ]
            for name, actual, expected in identity:
                checks.append(dict(family=family, check=name, actual=actual, expected=expected, passed=actual==expected))
            # Engine evaluations are a measurement. Exceptions are reported, not coerced into a bin.
            checks.append(dict(family=family, check="dropped_outside_competitive", actual=t["dropped_outside_competitive"],
                               expected=0, passed=t["dropped_outside_competitive"]==0, informational=True))
            for key in ("clearly_worse", "clearly_worse_grants"):
                checks.append(dict(family=family, check=key+"_unchanged", actual=counts["new_"+key], expected=counts[key],
                    passed=counts["new_"+key]==counts[key], informational=True))
        if set(censuses) == {"main", "all_source"}:
            main = [r["files"][0]["path"] for r in audits if r["family"]=="main"]
            other = [r["files"][0]["path"] for r in audits if r["family"]=="all_source"]
            # Join only the identity/material fields; DuckDB can spill the hash table.
            c.execute('CREATE VIEW main_check AS SELECT game_id,chooser,opponent,"case",keep,grant,old_grant,recorded_draw,recorded_chooser_win FROM ' + scan(main))
            c.execute('CREATE VIEW all_check AS SELECT game_id,chooser,opponent,"case",keep,grant,old_grant,recorded_draw,recorded_chooser_win FROM ' + scan(other))
            bad = c.execute("""SELECT count(*) FROM main_check m LEFT JOIN all_check a USING(game_id)
                WHERE a.game_id IS NULL OR m.chooser IS DISTINCT FROM a.chooser OR m.opponent IS DISTINCT FROM a.opponent
                OR m.case IS DISTINCT FROM a.case OR m.keep IS DISTINCT FROM a.keep OR m.grant IS DISTINCT FROM a.grant
                OR m.old_grant IS DISTINCT FROM a.old_grant OR m.recorded_draw IS DISTINCT FROM a.recorded_draw
                OR m.recorded_chooser_win IS DISTINCT FROM a.recorded_chooser_win""").fetchone()[0]
            checks.append(dict(family="both", check="main_is_identical_subset_of_all_source", actual=bad, expected=0, passed=bad==0))
    # Include all six handoff checks in one rectangular CSV, as well as their dedicated tables.
    extended = [dict(r, category="check") for r in checks]
    for name, category in [("old_new_rule_crosstab.csv", "old_new_crosstab"),
                           ("dropped_by_case_outcome_state.csv", "dropped_by_case")]:
        import csv
        with (report/name).open() as f:
            extended.extend(dict(r, category=category) for r in csv.DictReader(f))
    for family, t in totals.items():
        extended.append(dict(category="reclassified_grants", family=family, added=t["reclassified_draws"], removed=t["removed_old_grants"]))
    csv_file(report / "RECONCILIATION.csv", extended)
    gate = all(r["passed"] for r in checks if not r.get("informational"))
    result = dict(status="AUDIT_PASSED" if gate else "AUDIT_FAILED", run_id=config["id"], rule=RULE,
                  totals=totals, censuses=censuses, checks=checks, inference_rerun_complete=False,
                  input_panels_built=False, scope="material audit and certified replacement input panels")
    save(report / "RESULTS.json", result)
    return result


def descriptives(config, audits):
    run = Path(config["run"])
    report = run / "report"
    result = load(report / "RESULTS.json")
    paths = [r["files"][0]["path"] for r in audits if r["family"] == "main"]
    with database(run/"PRIVATE/spill/descriptives", max(1,config["memory_gb"]-3), min(4,config["workers"])) as c:
        c.execute("CREATE VIEW d AS SELECT * FROM " + scan(paths) + " WHERE keep")
        sample = rows(c, """SELECT 'all' region, count(*) opportunities, sum(grant)::BIGINT grants,
            100.0*avg(grant::DOUBLE) grant_rate_percent, count(DISTINCT chooser) choosers,
            count(DISTINCT chooser) FILTER(WHERE grant) granters FROM d
            UNION ALL SELECT 'competitive',count(*),sum(grant)::BIGINT,100.0*avg(grant::DOUBLE),count(DISTINCT chooser),count(DISTINCT chooser) FILTER(WHERE grant) FROM d WHERE state>=2
            UNION ALL SELECT 'clearly_worse',count(*),sum(grant)::BIGINT,100.0*avg(grant::DOUBLE),count(DISTINCT chooser),count(DISTINCT chooser) FILTER(WHERE grant) FROM d WHERE state=0""")
        csv_file(report / "tab_sample.csv", sample)
        cells = rows(c, f"""SELECT state,{STAGE_SQL} stage,count(*) opportunities,sum(grant)::BIGINT grants,
                     100.0*avg(grant::DOUBLE) grant_rate_percent FROM d GROUP BY state,stage ORDER BY state,stage""")
        for r in cells:
            r["state_label"] = STATES[r["state"]]
            r["ply_band"] = STAGE_LABELS[r["stage"]]
        csv_file(report / "tab_app_state_ply_cells.csv", cells)
        csv_file(report / "fig_desert_ply.csv", cells)
        stages = []
        for label, where in [("ply_2", "ply=2"), ("plies_3_10", "ply BETWEEN 3 AND 10"), ("after_ply_10", "ply>10")]:
            for region, condition in [("all", "TRUE"), ("competitive", "state>=2"), ("clearly_worse", "state=0")]:
                r = rows(c, "SELECT count(*) opportunities,sum(grant)::BIGINT grants,100.0*avg(grant::DOUBLE) grant_rate_percent FROM d WHERE " + where + " AND " + condition)[0]
                stages.append(dict(region=region, stage=label, **r))
        csv_file(report / "tab_app_stage_raw.csv", stages)
        comp = []
        for label, expression in [("speed", "speed"), ("month","month"), ("period","CASE WHEN month<'2024-11' THEN 'year_1' ELSE 'year_2' END"), ("rating", "CASE WHEN rating<1200 THEN '<1200' WHEN rating<1600 THEN '1200-1599' WHEN rating<2000 THEN '1600-1999' ELSE '2000+' END"), ("state", "CAST(state AS VARCHAR)")]:
            comp.extend(dict(dimension=label, **r) for r in rows(c, "SELECT " + expression + " category,count(*) opportunities,sum(grant)::BIGINT grants,100.0*avg(grant::DOUBLE) grant_rate_percent FROM d GROUP BY category ORDER BY category"))
        csv_file(report / "tab_app_composition.csv", comp)
        stakes = []
        for region, condition in [("all", "TRUE"), ("competitive", "state>=2"), ("clearly_worse", "state=0")]:
            r = rows(c, "SELECT count(*) grants,count(DISTINCT chooser) granters,sum(kappa) total_forgone_rating_points,avg(kappa) mean_premium,median(kappa) median_premium FROM d WHERE grant AND " + condition)[0]
            stakes.append(dict(region=region, price_source="original chooser_win_premium_v2; no cost upgrade", **r))
        csv_file(report / "tab_intro_rating_totals.csv", stakes)
        by_region={r["region"]:r for r in sample}
        c_rate=by_region["competitive"]["grant_rate_percent"]
        l_rate=by_region["clearly_worse"]["grant_rate_percent"]
        sample.append(dict(region="competitive_vs_clearly_worse",difference_pp=None if c_rate is None or l_rate is None else c_rate-l_rate,
                           rate_ratio=c_rate/l_rate if c_rate is not None and l_rate else None))
        premium=next(r for r in stakes if r["region"]=="competitive")
        by_region["competitive"].update(mean_forgone_premium=premium["mean_premium"],median_forgone_premium=premium["median_premium"])
        csv_file(report/"tab_sample.csv",sample)
    csv_file(report / "DOWNSTREAM_RERUN_REQUIRED.csv", [dict(output=name, description=description, producer=producer,
             status="NOT_RUN_IN_THIS_FIRST_STAGE") for name,description,producer in PENDING])
    save(report / "CACHE_POLICY.json", dict(
        safe_to_reuse=["Engine evaluations for unchanged positions", "original pregame rating states and kappa",
          "all-game factual chronology and numeric-ID dictionary", "profile snapshot and fixed Patron acquisition plan",
          "cached factual API metadata, predecessor and first-pair facts"],
        must_rebuild=["all grant/claim donor histories and cross-fitted state references", "scores, history controls and minimum-support flags",
          "exposure selection and spacing from the full eligible candidate universe", "first subsequent choices and reach",
          "recipient and opponent behavioral histories", "ordinary-ending later outcomes and entry labels",
          "persistence cohorts and bootstrap", "Patron behavior measures and comparisons", "all regression fits/covariances and figures"],
        prohibited_shortcut="Do not just filter old regression frames or reuse a cached first-later-choice. Removing its first event changes the next event; new grants also change scores.",
        not_rerun=["five-second status audit", "September audience analysis", "engine jobs", "profile acquisition"] ))
    result["descriptives_complete"] = True
    result["completed_outputs"] = ["tab_sample.csv", "tab_app_state_ply_cells.csv", "fig_desert_ply.csv", "tab_app_stage_raw.csv", "tab_app_composition.csv", "tab_intro_rating_totals.csv"]
    save(report / "RESULTS.json", result)
    return result


def bundle(config, package_root, label):
    """Aggregate-only allowlist. Private masks, identities, and tracebacks stay local."""
    run, root = Path(config["run"]), Path(package_root)
    report = run / "report"
    files = [("report/" + p.name, p) for p in sorted(report.iterdir()) if p.is_file() and p.suffix in (".csv", ".json", ".txt")]
    files += [("code/" + str(p.relative_to(root)), p) for folder in ("mmrerun", "tests")
              for p in sorted((root/folder).glob("*.py"))]
    files += [(p.name, p) for p in [root/"BUILD_INFO.json", root/"README.txt"] if p.exists()]
    if (run/"run.log").exists():
        files.append(("run.log",run/"run.log"))
    target = Path(config["results_dir"])/f'MATERIAL_FIRST_RUN_{config["id"][:16]}_{label}.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".partial")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name,p in files:
            require("PRIVATE" not in name and "exceptions" not in name, "A private path entered the report allowlist")
            z.write(p,name)
        z.writestr("REPORT_MANIFEST.json", __import__("json").dumps([dict(path=n,sha256=sha(p),bytes=p.stat().st_size) for n,p in files],indent=2))
    os.replace(tmp,target)
    atomic_text(str(target)+".sha256",sha(target)+"  "+target.name+"\n")
    return target
