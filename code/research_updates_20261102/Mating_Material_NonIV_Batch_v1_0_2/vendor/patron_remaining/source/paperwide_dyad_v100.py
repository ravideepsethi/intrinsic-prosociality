#!/usr/bin/env python3
"""Paper-wide audit of whether Lichess kindness results survive unfamiliar-dyad restrictions.

The program deliberately separates two time concepts:

* ``pair_games_24m`` is a whole-window dyad count.  It is suitable for a strict
  singleton sensitivity but can use games occurring after a focal decision.
* the C7R first-meeting authority is the causal-ordering check: it uses only
  meetings occurring before the focal decision in the certified history since 2013.

Private identifiers are retained only in resumable Parquet state.  Public output is
aggregate CSV/JSON and is independently checked before the run is committed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Sequence

VERSION = "1.0.1"
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_KIND = 669_503
EXPECTED_STAGE07_FAIR = 17_328_130
EXPECTED_STAGE07_SUCCESS_SHA = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_FLAGS_ROWS = EXPECTED_STAGE07_ROWS
EXPECTED_B1_ROWS = 1_017_944
EXPECTED_B1_KIND = 273_483
EXPECTED_B1_CHOOSERS = 64_331
EXPECTED_A1_ROWS = 2_556_782
EXPECTED_PROFILE_ROWS = 1_305_872

STAGE07_REL = Path("derived/replication/analysis_panel_24m_sf100k")
FLAGS_REL = Path(
    "derived/replication/frequent_dyad_census_24m_v101_PRIVATE/"
    "stage07_frequency_flags_private"
)
CORE_REL = Path("derived/replication/dynamic_prosociality_core_v102_PRIVATE")
PROFILE_REL = Path(
    "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/"
    "profile_snapshot_24m_private_lossless.parquet"
)
C9_SESSION_REL = Path(
    "derived/replication/dynamics_campaign1_c9_v100_PRIVATE/"
    "b1_c9_session_private.parquet"
)

FILTERS = (
    ("all", "TRUE", "all Stage 07 opportunities"),
    ("singleton_24m", "pair_games_24m = 1", "dyad appears once in the 24-month window"),
    ("pair_lt3_24m", "pair_games_24m < 3", "dyad appears fewer than 3 times in 24 months"),
    ("pair_lt5_24m", "pair_games_24m < 5", "dyad appears fewer than 5 times in 24 months"),
    ("pair_lt10_24m", "pair_games_24m < 10", "dyad appears fewer than 10 times in 24 months"),
    ("repeat_ge2_24m", "pair_games_24m >= 2", "dyad appears at least twice in 24 months"),
)

C7R_AUTHORITY = {
    "authority": "C7R certified pre-focal pair-history audit (outcome-blind 1-in-50 pair sample)",
    "history_start": "2013",
    "first_meeting_definition": "no earlier rated meeting in the certified history",
    "repeat_share_pct": 12.6004,
    "fair_kind_rate_first_pct": 2.8431,
    "fair_kind_rate_repeat_pct": 2.8602,
    "desert_gradient_first_pp": 1.5669,
    "desert_gradient_repeat_pp": 1.3342,
    "first_minus_repeat_interaction_pp": -0.0087,
    "interaction_p_value": 0.938,
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError(f"Refusing to write empty result table: {path.name}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def sql_quote(text: str | Path) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def parquet_glob(root: Path) -> str:
    return str(root / "**" / "*.parquet")


def import_dependencies():
    try:
        import duckdb  # type: ignore
        import numpy as np  # type: ignore
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Required packages are missing. Use the project virtual environment and "
            "install requirements.lock.txt."
        ) from exc
    return duckdb, np, pa, pq


def duckdb_connect(tempdir: Path, threads: int, memory_limit: str):
    duckdb, _, _, _ = import_dependencies()
    tempdir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET memory_limit={sql_quote(memory_limit)}")
    con.execute(f"SET temp_directory={sql_quote(tempdir)}")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=true")
    return con


def parquet_rows(path: Path) -> int:
    _, _, _, pq = import_dependencies()
    if path.is_file():
        return int(pq.ParquetFile(path).metadata.num_rows)
    files = sorted(path.rglob("*.parquet"))
    return sum(int(pq.ParquetFile(p).metadata.num_rows) for p in files)


def checkpoint_ok(receipt: Path, target: Path, signature: dict[str, Any]) -> bool:
    if not receipt.is_file() and not target.exists():
        return False
    if not receipt.is_file() or not target.exists():
        raise RuntimeError(f"Partial private checkpoint exists: {target}")
    saved = json.loads(receipt.read_text())
    for key, value in signature.items():
        if saved.get(key) != value:
            raise RuntimeError(f"Private checkpoint signature mismatch for {target}: {key}")
    if int(saved.get("rows", -1)) != parquet_rows(target):
        raise RuntimeError(f"Private checkpoint row count changed: {target}")
    return True


def authenticate_inputs(project: Path) -> dict[str, Any]:
    stage = project / STAGE07_REL
    flags = project / FLAGS_REL
    success = stage / "_SUCCESS.json"
    if not stage.is_dir() or not flags.is_dir() or not success.is_file():
        raise RuntimeError(
            "Missing Stage 07 or v1.0.1 frequent-dyad flags. Run the successful "
            "frequent-dyad census first."
        )
    success_sha = sha256_file(success)
    if success_sha != EXPECTED_STAGE07_SUCCESS_SHA:
        raise RuntimeError(
            f"Stage 07 authority hash changed: {success_sha} != {EXPECTED_STAGE07_SUCCESS_SHA}"
        )
    stage_rows = parquet_rows(stage)
    flag_rows = parquet_rows(flags)
    if stage_rows != EXPECTED_STAGE07_ROWS or flag_rows != EXPECTED_FLAGS_ROWS:
        raise RuntimeError(
            f"Authority row mismatch: stage07={stage_rows:,}, flags={flag_rows:,}"
        )
    return {
        "stage07": str(stage),
        "flags": str(flags),
        "stage07_rows": stage_rows,
        "flag_rows": flag_rows,
        "stage07_success_sha256": success_sha,
    }


JOINED_COLUMNS = """
  CAST(s.month AS VARCHAR) AS month,
  CAST(s.game_id AS VARCHAR) AS game_id,
  CAST(s.api_last_move_at_ms AS BIGINT) AS api_last_move_at_ms,
  CAST(s.utc_ms AS BIGINT) AS utc_ms,
  CAST(s.archive_ordinal AS BIGINT) AS archive_ordinal,
  CAST(s.chooser_user_id AS BIGINT) AS chooser_user_id,
  CAST(s.disconnected_user_id AS BIGINT) AS opponent_user_id,
  CAST(s.chooser_username_norm AS VARCHAR) AS chooser_username_norm,
  CAST(s.disconnected_username_norm AS VARCHAR) AS opponent_username_norm,
  CAST(s.kind_draw AS BOOLEAN) AS kind_draw,
  CAST(s.fair_competitive AS BOOLEAN) AS fair_competitive,
  CAST(s.clearly_worse AS BOOLEAN) AS clearly_worse,
  CAST(s.excluded_middle AS BOOLEAN) AS excluded_middle,
  CAST(s.engine_fairness_bin AS VARCHAR) AS engine_fairness_bin,
  CAST(s.engine_eval_cp_disconnected AS INTEGER) AS engine_eval_cp_disconnected,
  CAST(s.ply_count AS INTEGER) AS ply_count,
  CAST(s.chooser_elo AS INTEGER) AS chooser_elo,
  CAST(s.disconnected_elo AS INTEGER) AS opponent_elo,
  CAST(s.chooser_win_premium_v2 AS DOUBLE) AS chooser_win_premium_v2,
  CAST(s.chooser_draw_payoff_v2 AS DOUBLE) AS chooser_draw_payoff_v2,
  CAST(s.draw_nonnegative AS BOOLEAN) AS draw_nonnegative,
  CAST(s.draw_strict_positive AS BOOLEAN) AS draw_strict_positive,
  CAST(s.draw_costly AS BOOLEAN) AS draw_costly,
  CAST(s.api_speed AS VARCHAR) AS speed,
  CAST(s.tournament_like_event AS BOOLEAN) AS tournament_like_event,
  CAST(f.pair_games_24m AS INTEGER) AS pair_games_24m,
  CAST(f.dyad_ge_2 AS BOOLEAN) AS dyad_ge_2,
  CAST(f.dyad_ge_3 AS BOOLEAN) AS dyad_ge_3,
  CAST(f.dyad_ge_5 AS BOOLEAN) AS dyad_ge_5,
  CAST(f.dyad_ge_10 AS BOOLEAN) AS dyad_ge_10
"""


def build_joined_checkpoint(
    con, project: Path, state: Path, auth: dict[str, Any]
) -> Path:
    target = state / "stage07_with_dyad_frequency_private.parquet"
    receipt = state / "stage07_with_dyad_frequency_receipt.json"
    signature = {
        "status": "PAPERWIDE_STAGE07_DYAD_JOIN_OK",
        "stage07_success_sha256": auth["stage07_success_sha256"],
        "flags_rows": auth["flag_rows"],
    }
    if checkpoint_ok(receipt, target, signature):
        print("STAGE07_DYAD_JOIN_RESUMED", flush=True)
        return target

    stage_sql = sql_quote(parquet_glob(project / STAGE07_REL))
    flags_sql = sql_quote(parquet_glob(project / FLAGS_REL))
    tmp = target.with_suffix(".parquet.tmp")
    con.execute(
        f"""
        COPY (
          SELECT {JOINED_COLUMNS}
          FROM read_parquet({stage_sql}, union_by_name=true, hive_partitioning=true) s
          INNER JOIN read_parquet({flags_sql}, union_by_name=true, hive_partitioning=true) f
            ON CAST(s.game_id AS VARCHAR)=CAST(f.game_id AS VARCHAR)
        ) TO {sql_quote(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    rows, games, kinds, fair, bad_pair = con.execute(
        f"""
        SELECT count(*), count(DISTINCT game_id),
               count(*) FILTER (WHERE kind_draw),
               count(*) FILTER (WHERE fair_competitive),
               count(*) FILTER (WHERE pair_games_24m IS NULL OR pair_games_24m < 1)
        FROM read_parquet({sql_quote(tmp)})
        """
    ).fetchone()
    if (int(rows), int(games), int(kinds), int(fair), int(bad_pair)) != (
        EXPECTED_STAGE07_ROWS,
        EXPECTED_STAGE07_ROWS,
        EXPECTED_STAGE07_KIND,
        EXPECTED_STAGE07_FAIR,
        0,
    ):
        raise RuntimeError(
            "Stage07/flag join failed certification: "
            f"rows={rows}, games={games}, kind={kinds}, fair={fair}, bad_pair={bad_pair}"
        )
    os.replace(tmp, target)
    write_json(receipt, {**signature, "rows": int(rows), "created_utc": now()})
    print("STAGE07_DYAD_JOIN_CREATED", flush=True)
    return target


def rows_as_dicts(cursor) -> list[dict[str, Any]]:
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def structural_tables(con, joined: Path) -> dict[str, list[dict[str, Any]]]:
    p = sql_quote(joined)
    sample_rows: list[dict[str, Any]] = []
    descriptive_rows: list[dict[str, Any]] = []
    five_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    for label, condition, definition in FILTERS:
        q = con.execute(
            f"""
            SELECT count(*) AS "rows", count(*) FILTER (WHERE kind_draw) kind_draws,
                   count(DISTINCT chooser_user_id) choosers,
                   count(*) FILTER (WHERE fair_competitive) fair_rows,
                   count(*) FILTER (WHERE clearly_worse) clearly_worse_rows
            FROM read_parquet({p}) WHERE {condition}
            """
        ).fetchone()
        sample_rows.append(
            {
                "sample": label,
                "definition": definition,
                "rows": int(q[0]),
                "retained_pct": 100.0 * int(q[0]) / EXPECTED_STAGE07_ROWS,
                "kind_draws": int(q[1]),
                "choosers": int(q[2]),
                "fair_rows": int(q[3]),
                "clearly_worse_rows": int(q[4]),
            }
        )
        d = con.execute(
            f"""
            SELECT
              count(*) fair_rows,
              count(*) FILTER (WHERE kind_draw) fair_kind_draws,
              avg(CAST(kind_draw AS INTEGER))*100 fair_kind_rate_pct,
              median(chooser_win_premium_v2) FILTER (WHERE kind_draw) median_forgone_win_premium_among_kind_draws,
              avg(chooser_win_premium_v2) FILTER (WHERE kind_draw) mean_forgone_win_premium_among_kind_draws,
              quantile_cont(chooser_win_premium_v2, .25) FILTER (WHERE kind_draw) p25_forgone_win_premium_among_kind_draws,
              quantile_cont(chooser_win_premium_v2, .75) FILTER (WHERE kind_draw) p75_forgone_win_premium_among_kind_draws,
              median(chooser_draw_payoff_v2) FILTER (WHERE kind_draw) median_draw_payoff_among_kind_draws,
              avg(CAST(draw_costly AS INTEGER)) FILTER (WHERE kind_draw)*100 costly_draw_pct_among_kind_draws
            FROM read_parquet({p})
            WHERE {condition} AND fair_competitive
            """
        ).fetchone()
        descriptive_rows.append(
            dict(
                zip(
                    [
                        "fair_rows",
                        "fair_kind_draws",
                        "fair_kind_rate_pct",
                        "median_forgone_win_premium_among_kind_draws",
                        "mean_forgone_win_premium_among_kind_draws",
                        "p25_forgone_win_premium_among_kind_draws",
                        "p75_forgone_win_premium_among_kind_draws",
                        "median_draw_payoff_among_kind_draws",
                        "costly_draw_pct_among_kind_draws",
                    ],
                    d,
                ),
                sample=label,
            )
        )
        for row in rows_as_dicts(
            con.execute(
                f"""
                SELECT engine_fairness_bin,
                       count(*) AS "rows",
                       count(*) FILTER (WHERE kind_draw) kind_draws,
                       avg(CAST(kind_draw AS INTEGER))*100 kind_rate_pct
                FROM read_parquet({p})
                WHERE {condition}
                GROUP BY 1 ORDER BY 1
                """
            )
        ):
            five_rows.append({"sample": label, **row})
        for row in rows_as_dicts(
            con.execute(
                f"""
                SELECT CASE
                  WHEN opponent_elo-chooser_elo < -200 THEN '<-200'
                  WHEN opponent_elo-chooser_elo < -100 THEN '-200:-101'
                  WHEN opponent_elo-chooser_elo < -25 THEN '-100:-26'
                  WHEN opponent_elo-chooser_elo <= 25 THEN '-25:25'
                  WHEN opponent_elo-chooser_elo <= 100 THEN '26:100'
                  WHEN opponent_elo-chooser_elo <= 200 THEN '101:200'
                  ELSE '>200' END AS opponent_minus_chooser_rating_bin,
                  count(*) AS "rows", count(*) FILTER (WHERE kind_draw) kind_draws,
                  avg(CAST(kind_draw AS INTEGER))*100 kind_rate_pct
                FROM read_parquet({p})
                WHERE {condition} AND fair_competitive AND ply_count>10
                GROUP BY 1 ORDER BY min(opponent_elo-chooser_elo)
                """
            )
        ):
            gap_rows.append({"sample": label, **row})
        print(f"STRUCTURAL_DESCRIPTIVES_COMPLETE sample={label}", flush=True)
    return {
        "sample_summary": sample_rows,
        "table1_descriptives": descriptive_rows,
        "five_bin_rates": five_rows,
        "rating_gap_rates": gap_rows,
    }


def _invert_matrix(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    aug = [row[:] + [float(i == j) for j in range(n)] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise RuntimeError("Fixed-effect contrast matrix is singular")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [x / scale for x in aug[col]]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            aug[r] = [x - factor * y for x, y in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def categorical_chooser_fe(
    con,
    joined: Path,
    *,
    sample: str,
    filter_sql: str,
    model: str,
    category_sql: str,
    categories: Sequence[str],
    reference: str,
    extra_where: str,
) -> list[dict[str, Any]]:
    """Exact one-way chooser-FE LPM with chooser-clustered standard errors.

    We collapse binary outcomes to chooser/category sufficient statistics, so the
    calculation does not materialize a 47.6-million-row design matrix.
    """
    if reference not in categories:
        raise ValueError(reference)
    nonref = [x for x in categories if x != reference]
    cat_list = ",".join(sql_quote(x) for x in categories)
    con.execute("DROP TABLE IF EXISTS _fe_cells")
    con.execute(
        f"""
        CREATE TEMP TABLE _fe_cells AS
        SELECT chooser_user_id, category, count(*)::DOUBLE n,
               sum(CAST(kind_draw AS INTEGER))::DOUBLE k
        FROM (
          SELECT chooser_user_id, kind_draw, {category_sql} AS category
          FROM read_parquet({sql_quote(joined)})
          WHERE {filter_sql} AND ({extra_where})
        ) q
        WHERE category IN ({cat_list})
        GROUP BY 1,2
        """
    )
    n_expr = [f"sum(n) FILTER (WHERE category={sql_quote(c)})" for c in categories]
    k_expr = [f"sum(k) FILTER (WHERE category={sql_quote(c)})" for c in categories]
    row = con.execute(
        "SELECT " + ",".join(n_expr + k_expr) + ",sum(n),sum(k),count(DISTINCT chooser_user_id) FROM _fe_cells"
    ).fetchone()
    m = len(categories)
    ns = [float(x or 0) for x in row[:m]]
    ks = [float(x or 0) for x in row[m : 2 * m]]
    total_n, total_k, clusters = float(row[-3]), float(row[-2]), int(row[-1])
    if min(ns) <= 0 or clusters < 2:
        raise RuntimeError(f"Insufficient support for {model}/{sample}: n={ns}, G={clusters}")

    # Within-chooser cross-products need only per-chooser totals and category counts.
    select = ["chooser_user_id", "sum(n) nt", "sum(k) kt"]
    for i, c in enumerate(nonref):
        select += [
            f"coalesce(sum(n) FILTER (WHERE category={sql_quote(c)}),0)::DOUBLE n{i}",
            f"coalesce(sum(k) FILTER (WHERE category={sql_quote(c)}),0)::DOUBLE k{i}",
        ]
    con.execute("DROP TABLE IF EXISTS _fe_wide")
    con.execute("CREATE TEMP TABLE _fe_wide AS SELECT " + ",".join(select) + " FROM _fe_cells GROUP BY 1")
    p = len(nonref)
    bread = [[0.0] * p for _ in range(p)]
    rhs = [0.0] * p
    for i in range(p):
        ni, ki = con.execute(f"SELECT sum(n{i}),sum(k{i}) FROM _fe_wide").fetchone()
        rhs[i] = float(ki) - float(
            con.execute(f"SELECT sum(n{i}*kt/nt) FROM _fe_wide").fetchone()[0]
        )
        for j in range(p):
            value = -float(
                con.execute(f"SELECT sum(n{i}*n{j}/nt) FROM _fe_wide").fetchone()[0]
            )
            if i == j:
                value += float(ni)
            bread[i][j] = value
    inv = _invert_matrix(bread)
    beta = [sum(inv[i][j] * rhs[j] for j in range(p)) for i in range(p)]

    beta_sum = " + ".join(f"({beta[i]:.17g})*n{i}" for i in range(p)) or "0"
    alpha_expr = f"(kt-({beta_sum}))/nt"
    score_exprs = [f"(k{i}-n{i}*(({alpha_expr})+({beta[i]:.17g}))) s{i}" for i in range(p)]
    scores = con.execute("SELECT " + ",".join(score_exprs) + " FROM _fe_wide").fetchall()
    meat = [[0.0] * p for _ in range(p)]
    for score in scores:
        for i in range(p):
            for j in range(p):
                meat[i][j] += float(score[i]) * float(score[j])
    middle = [[sum(inv[i][k] * meat[k][j] for k in range(p)) for j in range(p)] for i in range(p)]
    cov = [[sum(middle[i][k] * inv[j][k] for k in range(p)) for j in range(p)] for i in range(p)]
    # Conventional CR1 degrees-of-freedom multiplier.
    df_factor = (clusters / (clusters - 1.0)) * ((total_n - 1.0) / (total_n - clusters - p))
    rows: list[dict[str, Any]] = []
    for i, category in enumerate(nonref):
        se = math.sqrt(max(cov[i][i] * df_factor, 0.0))
        z = beta[i] / se if se > 0 else math.nan
        pval = math.erfc(abs(z) / math.sqrt(2.0)) if math.isfinite(z) else math.nan
        rows.append(
            {
                "sample": sample,
                "model": model,
                "category": category,
                "reference": reference,
                "effect_pp": 100.0 * beta[i],
                "cluster_se_pp": 100.0 * se,
                "z": z,
                "p_value_normal": pval,
                "rows": int(total_n),
                "choosers": clusters,
                "fixed_effect": "chooser_user_id",
                "cluster": "chooser_user_id",
            }
        )
    return rows


def structural_fe_tables(con, joined: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample, condition, _ in FILTERS:
        rows.extend(
            categorical_chooser_fe(
                con,
                joined,
                sample=sample,
                filter_sql=condition,
                model="desert_clearly_worse_vs_fair",
                category_sql="CASE WHEN fair_competitive THEN 'fair' WHEN clearly_worse THEN 'clearly_worse' END",
                categories=("fair", "clearly_worse"),
                reference="fair",
                extra_where="fair_competitive OR clearly_worse",
            )
        )
        rows.extend(
            categorical_chooser_fe(
                con,
                joined,
                sample=sample,
                filter_sql=condition,
                model="price_costly_vs_nonnegative_fair",
                category_sql="CASE WHEN draw_nonnegative THEN 'nonnegative' WHEN draw_costly THEN 'costly' END",
                categories=("nonnegative", "costly"),
                reference="nonnegative",
                extra_where="fair_competitive AND (draw_nonnegative OR draw_costly)",
            )
        )
        rows.extend(
            categorical_chooser_fe(
                con,
                joined,
                sample=sample,
                filter_sql=condition,
                model="game_stage_late_vs_opening_fair",
                category_sql="CASE WHEN ply_count<=10 THEN 'ply_le10' ELSE 'ply_gt10' END",
                categories=("ply_le10", "ply_gt10"),
                reference="ply_le10",
                extra_where="fair_competitive AND ply_count IS NOT NULL",
            )
        )
        rows.extend(
            categorical_chooser_fe(
                con,
                joined,
                sample=sample,
                filter_sql=condition,
                model="relative_strength_fair_late",
                category_sql=(
                    "CASE WHEN opponent_elo-chooser_elo < -25 THEN 'opponent_weaker' "
                    "WHEN opponent_elo-chooser_elo <= 25 THEN 'approximately_equal' "
                    "ELSE 'opponent_stronger' END"
                ),
                categories=("approximately_equal", "opponent_weaker", "opponent_stronger"),
                reference="approximately_equal",
                extra_where="fair_competitive AND ply_count>10 AND chooser_elo IS NOT NULL AND opponent_elo IS NOT NULL",
            )
        )
        print(f"STRUCTURAL_FE_COMPLETE sample={sample}", flush=True)
    return rows


def weighted_corr_moments(rows: Sequence[tuple[float, float, float]]) -> float:
    sw = sum(w for w, _, _ in rows)
    if sw <= 0:
        return math.nan
    mx = sum(w * x for w, x, _ in rows) / sw
    my = sum(w * y for w, _, y in rows) / sw
    vx = sum(w * (x - mx) ** 2 for w, x, _ in rows)
    vy = sum(w * (y - my) ** 2 for w, _, y in rows)
    cov = sum(w * (x - mx) * (y - my) for w, x, y in rows)
    return cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else math.nan


def persistence_tables(con, joined: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sample, condition, _ in FILTERS[:4]:
        for split in ("calendar_half_no_crossing_dyad", "opponent_set_hash_half"):
            con.execute("DROP TABLE IF EXISTS _persist")
            if split == "calendar_half_no_crossing_dyad":
                source_sql = f"""
                  WITH tagged AS (
                    SELECT *,CASE WHEN api_last_move_at_ms < 1730419200000 THEN 1 ELSE 2 END half,
                           least(chooser_user_id,opponent_user_id) low_id,
                           greatest(chooser_user_id,opponent_user_id) high_id
                    FROM read_parquet({sql_quote(joined)})
                    WHERE {condition} AND fair_competitive
                  ), one_half_pairs AS (
                    SELECT low_id,high_id FROM tagged GROUP BY 1,2 HAVING min(half)=max(half)
                  ), c AS (
                    SELECT chooser_user_id,half,count(*) n,sum(CAST(kind_draw AS INTEGER)) k
                    FROM tagged INNER JOIN one_half_pairs USING(low_id,high_id) GROUP BY 1,2
                  )
                """
            else:
                source_sql = f"""
                  WITH c AS (
                    SELECT chooser_user_id,
                           CASE WHEN hash(least(chooser_user_id,opponent_user_id),greatest(chooser_user_id,opponent_user_id))%2=0 THEN 1 ELSE 2 END half,
                           count(*) n,sum(CAST(kind_draw AS INTEGER)) k
                    FROM read_parquet({sql_quote(joined)})
                    WHERE {condition} AND fair_competitive GROUP BY 1,2
                  )
                """
            con.execute(
                f"""
                CREATE TEMP TABLE _persist AS
                {source_sql}
                SELECT chooser_user_id,
                       max(n) FILTER (WHERE half=1)::DOUBLE n1,
                       max(k) FILTER (WHERE half=1)::DOUBLE k1,
                       max(n) FILTER (WHERE half=2)::DOUBLE n2,
                       max(k) FILTER (WHERE half=2)::DOUBLE k2
                FROM c GROUP BY 1
                """
            )
            for minimum in (2, 4, 10):
                vals = rows_as_dicts(
                    con.execute(
                        f"""
                        WITH r AS (
                          SELECT *,k1/n1 x,k2/n2 y,(n1+n2)::DOUBLE w
                          FROM _persist WHERE n1>={minimum} AND n2>={minimum}
                        ), m AS (
                          SELECT *,sum(w) over() sw,
                                   sum(w*x) over()/sum(w) over() mx,
                                   sum(w*y) over()/sum(w) over() my
                          FROM r
                        )
                        SELECT count(*) choosers,
                               corr(x,y) pearson_unweighted,
                               sum(w*(x-mx)*(y-my))/sqrt(sum(w*(x-mx)*(x-mx))*sum(w*(y-my)*(y-my))) weighted_pearson,
                               sum(k2) FILTER (WHERE k1>0)/sum(n2) FILTER (WHERE k1>0)*100 later_kind_rate_prior_kind_pct,
                               sum(k2) FILTER (WHERE k1=0)/sum(n2) FILTER (WHERE k1=0)*100 later_kind_rate_prior_never_pct,
                               count(*) FILTER (WHERE k1>0) prior_kind_choosers,
                               count(*) FILTER (WHERE k1=0) prior_never_choosers
                        FROM m
                        """
                    )
                )[0]
                out.append(
                    {
                        "sample": sample,
                        "split": split,
                        "minimum_opportunities_each_half": minimum,
                        **vals,
                    }
                )
            print(f"PERSISTENCE_COMPLETE sample={sample} split={split}", flush=True)
    return out


EXPECTED_A1_BASE_SHA = "2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713"


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import authority: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def resolve_a1_base(project: Path) -> Path:
    candidates = (
        project / "replication_package/code/10c_estimate_dynamic_prosociality_core.py",
        project / "code/10c_estimate_dynamic_prosociality_core.py",
    )
    for path in candidates:
        if path.is_file():
            actual = sha256_file(path)
            if actual != EXPECTED_A1_BASE_SHA:
                raise RuntimeError(
                    f"A1 frozen producer changed: {actual} != {EXPECTED_A1_BASE_SHA}: {path}"
                )
            return path
    raise RuntimeError(
        "The frozen A1 producer 10c_estimate_dynamic_prosociality_core.py was not found"
    )


def build_a1_crosswalk(
    con, project: Path, joined: Path, state: Path
) -> tuple[Path, dict[str, Any]]:
    recipient = project / CORE_REL / "recipient_with_chronology_private.parquet"
    if not recipient.is_file() or parquet_rows(recipient) != EXPECTED_A1_ROWS:
        raise RuntimeError(f"A1 recipient authority is missing or changed: {recipient}")
    target = state / "a1_first_outcome_dyad_private.parquet"
    receipt = state / "a1_first_outcome_dyad_receipt.json"
    signature = {
        "status": "PAPERWIDE_A1_OUTCOME_DYAD_BRIDGE_OK",
        "recipient_sha256": sha256_file(recipient),
        "joined_rows": EXPECTED_STAGE07_ROWS,
    }
    if checkpoint_ok(receipt, target, signature):
        return target, json.loads(receipt.read_text())
    tmp = target.with_suffix(".parquet.tmp")
    # The original A1 cache identifies its first subsequent opportunity through a
    # timestamp and exact state variables.  This outcome-blind bridge recovers the
    # Stage07 game/dyad and refuses ambiguous matches.
    con.execute(
        f"""
        COPY (
          WITH r AS (
            SELECT cohort_row_id::BIGINT cohort_row_id,
                   recipient_user_id::BIGINT recipient_user_id,
                   CAST(exposure_game_id AS VARCHAR) exposure_game_id,
                   exposure_anchor_utc_ms::BIGINT exposure_anchor_utc_ms,
                   first_subsequent_delta_ms::BIGINT first_subsequent_delta_ms,
                   first_subsequent_eval_cp::DOUBLE first_subsequent_eval_cp,
                   first_subsequent_chooser_elo::DOUBLE first_subsequent_chooser_elo,
                   first_subsequent_opponent_elo::DOUBLE first_subsequent_opponent_elo,
                   first_subsequent_kind_draw::BOOLEAN first_subsequent_kind_draw,
                   reached_fair_chooser_within_90d::BOOLEAN reached
            FROM read_parquet({sql_quote(recipient)})
          ), candidates AS (
            SELECT r.cohort_row_id, e.opponent_user_id exposure_opponent_user_id,
                   e.pair_games_24m exposure_pair_games_24m,
                   o.game_id outcome_game_id,
                   o.opponent_user_id outcome_opponent_user_id,
                   o.pair_games_24m outcome_pair_games_24m,
                   count(*) over(PARTITION BY r.cohort_row_id) candidate_count,
                   row_number() over(
                     PARTITION BY r.cohort_row_id
                     ORDER BY o.archive_ordinal,o.game_id
                   ) rn
            FROM r
            INNER JOIN read_parquet({sql_quote(joined)}) e
              ON e.game_id=r.exposure_game_id
            INNER JOIN read_parquet({sql_quote(joined)}) o
              ON r.reached
             AND o.chooser_user_id=r.recipient_user_id
             AND o.api_last_move_at_ms=r.exposure_anchor_utc_ms+r.first_subsequent_delta_ms
             AND CAST(o.engine_eval_cp_disconnected AS DOUBLE)=r.first_subsequent_eval_cp
             AND CAST(o.chooser_elo AS DOUBLE)=r.first_subsequent_chooser_elo
             AND CAST(o.opponent_elo AS DOUBLE)=r.first_subsequent_opponent_elo
             AND o.kind_draw=r.first_subsequent_kind_draw
          )
          SELECT r.cohort_row_id,
                 c.exposure_opponent_user_id,c.exposure_pair_games_24m,
                 c.outcome_game_id,c.outcome_opponent_user_id,c.outcome_pair_games_24m,
                 coalesce(c.candidate_count,0)::INTEGER candidate_count,
                 CASE WHEN c.outcome_opponent_user_id IS NOT NULL
                           AND c.outcome_opponent_user_id<>c.exposure_opponent_user_id
                      THEN TRUE ELSE FALSE END different_opponent
          FROM r LEFT JOIN candidates c
            ON c.cohort_row_id=r.cohort_row_id AND c.rn=1
          ORDER BY r.cohort_row_id
        ) TO {sql_quote(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    qa = con.execute(
        f"""
        SELECT count(*) AS "rows",count(DISTINCT cohort_row_id) unique_rows,
               count(*) FILTER (WHERE outcome_game_id IS NOT NULL) reached_mapped,
               count(*) FILTER (WHERE candidate_count>1) ambiguous,
               count(*) FILTER (WHERE outcome_pair_games_24m=1 AND different_opponent) singleton_different
        FROM read_parquet({sql_quote(tmp)})
        """
    ).fetchone()
    if int(qa[0]) != EXPECTED_A1_ROWS or int(qa[1]) != EXPECTED_A1_ROWS or int(qa[3]) != 0:
        raise RuntimeError(f"A1 outcome-dyad bridge did not certify: {qa}")
    os.replace(tmp, target)
    saved = {
        **signature,
        "rows": int(qa[0]),
        "reached_mapped": int(qa[2]),
        "ambiguous": int(qa[3]),
        "singleton_different": int(qa[4]),
        "created_utc": now(),
    }
    write_json(receipt, saved)
    print("A1_OUTCOME_DYAD_BRIDGE_CREATED", flush=True)
    return target, saved


def a1_sensitivity(
    con, project: Path, joined: Path, state: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _, np, _, pq = import_dependencies()
    base_path = resolve_a1_base(project)
    base = import_module(base_path, "paperwide_frozen_a1_base")
    recipient = project / CORE_REL / "recipient_with_chronology_private.parquet"
    crosswalk, bridge = build_a1_crosswalk(con, project, joined, state)
    data = base.load_recipient_arrays(recipient)
    support = base.common_support_weights(data)
    x = pq.read_table(crosswalk).to_pandas().sort_values("cohort_row_id", kind="stable")
    if not np.array_equal(x["cohort_row_id"].to_numpy(dtype=np.int64), data["cohort_row_id"]):
        raise RuntimeError("A1 recipient/crosswalk dense order changed")
    follow = data["a1_90d_followup_eligible"].astype(bool)
    first = data["first_ever_pair"].astype(bool)
    arm = data["arm_eligible"].astype(bool)
    reached = data["reached_fair_chooser_within_90d"].astype(bool)
    baseline = first & arm & follow & reached
    specs = (
        ("published_first_exposure_any_first_fair_outcome", np.ones(len(x), dtype=bool)),
        (
            "different_opponent",
            x["different_opponent"].fillna(False).to_numpy(dtype=bool),
        ),
        (
            "different_singleton_outcome_24m",
            x["different_opponent"].fillna(False).to_numpy(dtype=bool)
            & (x["outcome_pair_games_24m"].fillna(-1).to_numpy() == 1),
        ),
        (
            "different_outcome_pair_lt3_24m",
            x["different_opponent"].fillna(False).to_numpy(dtype=bool)
            & (x["outcome_pair_games_24m"].fillna(99).to_numpy() < 3),
        ),
        (
            "different_outcome_pair_lt5_24m",
            x["different_opponent"].fillna(False).to_numpy(dtype=bool)
            & (x["outcome_pair_games_24m"].fillna(99).to_numpy() < 5),
        ),
        (
            "different_singleton_exposure_and_outcome_24m",
            x["different_opponent"].fillna(False).to_numpy(dtype=bool)
            & (x["outcome_pair_games_24m"].fillna(-1).to_numpy() == 1)
            & (x["exposure_pair_games_24m"].fillna(-1).to_numpy() == 1),
        ),
    )
    rows: list[dict[str, Any]] = []
    for label, mask in specs:
        fitted = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name="first_subsequent_kind_draw",
            sample=baseline & mask,
            estimand=f"paperwide_repeat_dyad_audit:{label}",
            state_conditioned=False,
            binary_outcome=True,
        )
        rows.append(
            {
                "restriction": label,
                "rows": int(fitted["rows"]),
                "treated_rows": int(fitted["treated_rows"]),
                "control_rows": int(fitted["control_rows"]),
                "effect_pp": float(fitted["coefficient_percentage_points"]),
                "cluster_se_pp": float(fitted["standard_error_percentage_points"]),
                "p_value_normal": float(fitted["p_value_raw"]),
                "exposure_already_first_ever_pair": True,
                "whole_window_outcome_filter": label != "published_first_exposure_any_first_fair_outcome",
            }
        )
        print(f"A1_SENSITIVITY_COMPLETE restriction={label}", flush=True)
    return rows, bridge


def fair_opp_bin_sql(column: str) -> str:
    return (
        f"CASE WHEN {column}=0 THEN '0' WHEN {column}=1 THEN '1' "
        f"WHEN {column}=2 THEN '2' WHEN {column}=3 THEN '3' "
        f"WHEN {column}=4 THEN '4' WHEN {column}<=9 THEN '5_9' "
        f"WHEN {column}<=20 THEN '10_20' WHEN {column}<=50 THEN '21_50' "
        f"WHEN {column}<=100 THEN '51_100' ELSE '101_plus' END"
    )


def patron_cell_fe(con) -> dict[str, Any]:
    # Frisch-Waugh calculation on returned profiles collapsed by rematch cell.
    row = con.execute(
        """
        WITH c AS (
          SELECT audit_match_cell,
                 count(*)::DOUBLE n,sum(is_kind)::DOUBLE nx,
                 sum(CAST(patron AS INTEGER))::DOUBLE sy,
                 sum(is_kind*CAST(patron AS INTEGER))::DOUBLE sxy
          FROM _patron_matched WHERE returned GROUP BY 1
        )
        SELECT sum(sxy-nx*sy/n)/sum(nx-nx*nx/n),sum(n),count(*) FROM c
        """
    ).fetchone()
    return {"cell_fe_gap_pp": 100.0 * float(row[0]), "returned_rows": int(row[1]), "match_cells": int(row[2])}


def patron_sensitivity(
    con, project: Path, joined: Path, state: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = project / PROFILE_REL
    if not snapshot.is_file() or parquet_rows(snapshot) != EXPECTED_PROFILE_ROWS:
        raise RuntimeError(f"Patron profile snapshot is missing or changed: {snapshot}")
    target = state / "patron_restricted_opportunities_private.parquet"
    receipt = state / "patron_restricted_opportunities_receipt.json"
    signature = {
        "status": "PAPERWIDE_PATRON_RESTRICTED_OPPORTUNITIES_OK",
        "snapshot_sha256": sha256_file(snapshot),
        "joined_rows": EXPECTED_STAGE07_ROWS,
    }
    if not checkpoint_ok(receipt, target, signature):
        tmp = target.with_suffix(".parquet.tmp")
        union_parts = []
        for label, condition, _ in FILTERS[:4]:
            union_parts.append(
                f"""
                SELECT {sql_quote(label)} restriction,s.username_norm,
                       count(j.game_id)::BIGINT fair_opps,
                       coalesce(sum(CAST(j.kind_draw AS INTEGER)),0)::BIGINT fair_kind_count,
                       mode(j.speed) modal_speed_group
                FROM read_parquet({sql_quote(snapshot)}) s
                LEFT JOIN read_parquet({sql_quote(joined)}) j
                  ON j.chooser_username_norm=s.username_norm
                 AND j.fair_competitive AND ({condition})
                GROUP BY 1,2
                """
            )
        con.execute(
            f"COPY ({' UNION ALL '.join(union_parts)}) TO {sql_quote(tmp)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        rows = parquet_rows(tmp)
        expected = EXPECTED_PROFILE_ROWS * 4
        if rows != expected:
            raise RuntimeError(f"Patron restriction aggregation changed: {rows} != {expected}")
        os.replace(tmp, target)
        write_json(receipt, {**signature, "rows": rows, "created_utc": now()})

    results: list[dict[str, Any]] = []
    support: dict[str, Any] = {}
    for label, _, definition in FILTERS[:4]:
        con.execute("DROP TABLE IF EXISTS _patron_pool")
        con.execute(
            f"""
            CREATE TEMP TABLE _patron_pool AS
            SELECT s.username_norm,s.acquisition_role,s.returned,s.patron,
                   a.fair_opps,a.fair_kind_count,
                   concat({fair_opp_bin_sql('a.fair_opps')},'__',coalesce(a.modal_speed_group,s.modal_speed_group,'missing')) audit_match_cell,
                   hash(s.username_norm,{sql_quote('paperwide_repeat_dyad_audit_v100')}) h
            FROM read_parquet({sql_quote(snapshot)}) s
            INNER JOIN read_parquet({sql_quote(target)}) a USING(username_norm)
            WHERE a.restriction={sql_quote(label)}
              AND s.acquisition_role IN ('kind','control')
            """
        )
        con.execute("DROP TABLE IF EXISTS _patron_matched")
        con.execute(
            """
            CREATE TEMP TABLE _patron_matched AS
            WITH cap AS (
              SELECT audit_match_cell,
                     count(*) FILTER (WHERE acquisition_role='control') nc,
                     count(*) FILTER (WHERE acquisition_role='kind' AND fair_kind_count>0) nk
              FROM _patron_pool GROUP BY 1
            ), ranked_kind AS (
              SELECT p.*,c.nc,c.nk,
                     row_number() over(PARTITION BY p.audit_match_cell ORDER BY h,username_norm) role_rank
              FROM _patron_pool p INNER JOIN cap c USING(audit_match_cell)
              WHERE p.acquisition_role='kind' AND p.fair_kind_count>0
            ), ranked_control AS (
              SELECT p.*,c.nc,c.nk,
                     row_number() over(PARTITION BY p.audit_match_cell ORDER BY h,username_norm) role_rank
              FROM _patron_pool p INNER JOIN cap c USING(audit_match_cell)
              WHERE p.acquisition_role='control'
            ), kept_kind AS (
              SELECT *,role_rank::BIGINT matched_order,1::INTEGER is_kind
              FROM ranked_kind
              WHERE role_rank<=least(nk,floor(nc/3))
            ), kept_control AS (
              SELECT *,ceil(role_rank/3.0)::BIGINT matched_order,0::INTEGER is_kind
              FROM ranked_control
              WHERE role_rank<=3*least(nk,floor(nc/3))
            )
            SELECT * FROM kept_kind UNION ALL BY NAME SELECT * FROM kept_control
            """
        )
        qa = con.execute(
            """
            SELECT count(*) FILTER (WHERE is_kind=1),count(*) FILTER (WHERE is_kind=0),
                   count(DISTINCT audit_match_cell),count(*) FILTER (WHERE returned),
                   avg(CAST(patron AS INTEGER)) FILTER (WHERE returned AND is_kind=1)*100,
                   avg(CAST(patron AS INTEGER)) FILTER (WHERE returned AND is_kind=0)*100,
                   sum(fair_kind_count) FILTER (WHERE is_kind=1),
                   sum(fair_opps) FILTER (WHERE is_kind=1)
            FROM _patron_matched
            """
        ).fetchone()
        malformed = int(
            con.execute(
                """
                SELECT count(*) FROM (
                  SELECT audit_match_cell,matched_order,
                         count(*) FILTER (WHERE is_kind=1) kind_n,
                         count(*) FILTER (WHERE is_kind=0) control_n
                  FROM _patron_matched GROUP BY 1,2
                  HAVING kind_n<>1 OR control_n<>3
                ) q
                """
            ).fetchone()[0]
        )
        if int(qa[1]) != 3 * int(qa[0]) or malformed != 0:
            raise RuntimeError(
                f"Patron deterministic 1:3 rematch failed: {label}: "
                f"kind={qa[0]} control={qa[1]} malformed_groups={malformed}"
            )
        fe = patron_cell_fe(con)
        row = {
            "restriction": label,
            "definition": definition,
            "matched_kind_users": int(qa[0]),
            "matched_control_users": int(qa[1]),
            "match_cells": int(qa[2]),
            "returned_profiles": int(qa[3]),
            "kind_patron_rate_returned_pct": float(qa[4]) if qa[4] is not None else None,
            "control_patron_rate_returned_pct": float(qa[5]) if qa[5] is not None else None,
            "raw_gap_pp": float(qa[4] - qa[5]) if qa[4] is not None and qa[5] is not None else None,
            "kind_fair_draws": int(qa[6] or 0),
            "kind_fair_opportunities": int(qa[7] or 0),
            **fe,
        }
        results.append(row)
        support[label] = {
            "eligible_kind_users_before_support": int(
                con.execute("SELECT count(*) FROM _patron_pool WHERE acquisition_role='kind' AND fair_kind_count>0").fetchone()[0]
            ),
            "matched_kind_users": int(qa[0]),
            "matched_control_users": int(qa[1]),
        }
        print(f"PATRON_REMATCH_COMPLETE restriction={label}", flush=True)
    return results, support


def conditional_selection_probabilities(log_odds, kind_total: int):
    """Exact sequential Bernoulli probabilities conditional on a chooser's total."""
    _, np, _, _ = import_dependencies()
    n, k = int(log_odds.size), int(kind_total)
    suffix = np.full((n + 1, k + 1), -np.inf, dtype=np.float64)
    suffix[n, 0] = 0.0
    for position in range(n - 1, -1, -1):
        suffix[position, 0] = 0.0
        for remaining in range(1, min(k, n - position) + 1):
            suffix[position, remaining] = np.logaddexp(
                suffix[position + 1, remaining],
                log_odds[position] + suffix[position + 1, remaining - 1],
            )
    if not np.isfinite(suffix[0, k]):
        raise RuntimeError("C9 conditional Bernoulli normalizer is nonfinite")
    result = np.zeros((n, k + 1), dtype=np.float64)
    for position in range(n):
        for remaining in range(1, min(k, n - position) + 1):
            numerator = log_odds[position] + suffix[position + 1, remaining - 1]
            result[position, remaining] = math.exp(
                min(0.0, numerator - suffix[position, remaining])
            )
    return np.clip(result, 0.0, 1.0)


def chooser_slices(chooser) -> list[tuple[int, int]]:
    _, np, _, _ = import_dependencies()
    if len(chooser) == 0:
        return []
    boundaries = np.flatnonzero(np.r_[True, chooser[1:] != chooser[:-1], True])
    return [(int(a), int(z)) for a, z in zip(boundaries[:-1], boundaries[1:])]


def c9_later_session_totals(times, sessions, choices):
    _, np, _, _ = import_dependencies()
    times = np.asarray(times, dtype=np.int64)
    sessions = np.asarray(sessions, dtype=np.int64)
    choices = np.asarray(choices, dtype=bool)
    first = np.argmax(choices, axis=1)
    pos = np.arange(choices.shape[1], dtype=np.int64)[None, :]
    after = pos > first[:, None]
    delta = times[None, :] - times[first][:, None]
    later = (
        after
        & (delta <= 7 * 24 * 60 * 60 * 1000)
        & (sessions[None, :] != sessions[first][:, None])
    )
    return (
        np.count_nonzero(choices & later, axis=1).astype(np.int64),
        np.count_nonzero(later, axis=1).astype(np.int64),
    )


_C9_WORK: dict[str, Any] | None = None


def _c9_worker_init(path_text: str) -> None:
    global _C9_WORK
    _, np, _, pq = import_dependencies()
    frame = pq.read_table(
        Path(path_text),
        columns=[
            "chooser_index",
            "sequence_index",
            "utc_ms",
            "kind_draw",
            "static_propensity",
            "session_id",
        ],
        use_threads=False,
    ).to_pandas()
    frame = frame.sort_values(["chooser_index", "sequence_index"], kind="stable")
    chooser = frame["chooser_index"].to_numpy(dtype=np.int64)
    kind = frame["kind_draw"].to_numpy(dtype=bool)
    propensity = np.clip(frame["static_propensity"].to_numpy(dtype=np.float64), 1e-9, 1 - 1e-9)
    slices = chooser_slices(chooser)
    selections = []
    for a, z in slices:
        k = int(np.count_nonzero(kind[a:z]))
        odds = np.log(propensity[a:z]) - np.log1p(-propensity[a:z])
        selections.append(conditional_selection_probabilities(odds, k))
    _C9_WORK = {
        "chooser": chooser,
        "times": frame["utc_ms"].to_numpy(dtype=np.int64),
        "kind": kind,
        "session": frame["session_id"].to_numpy(dtype=np.int64),
        "slices": slices,
        "selections": selections,
    }


def _c9_worker_batch(start: int, stop: int, seed: int) -> tuple[int, int, Any, Any]:
    if _C9_WORK is None:
        raise RuntimeError("C9 worker is not initialized")
    _, np, _, _ = import_dependencies()
    sims = stop - start
    rng = np.random.default_rng(np.random.SeedSequence([seed, start, stop]))
    total_num = np.zeros(sims, dtype=np.int64)
    total_den = np.zeros(sims, dtype=np.int64)
    for (a, z), selection in zip(_C9_WORK["slices"], _C9_WORK["selections"]):
        n = z - a
        k = int(np.count_nonzero(_C9_WORK["kind"][a:z]))
        remaining = np.full(sims, k, dtype=np.int32)
        choices = np.zeros((sims, n), dtype=bool)
        for position in range(n):
            forced = remaining == (n - position)
            probability_now = selection[position, remaining]
            chosen = forced | ((remaining > 0) & (rng.random(sims) < probability_now))
            choices[:, position] = chosen
            remaining -= chosen.astype(np.int32)
        if np.any(remaining != 0):
            raise RuntimeError("C9 conditional sampler did not preserve chooser totals")
        num, den = c9_later_session_totals(
            _C9_WORK["times"][a:z], _C9_WORK["session"][a:z], choices
        )
        total_num += num
        total_den += den
    return start, stop, total_num, total_den


def build_c9_restricted_cache(
    con, project: Path, joined: Path, state: Path
) -> tuple[Path, dict[str, Any]]:
    b1 = project / CORE_REL / "b1_repeat_granter_private.parquet"
    propensity = project / CORE_REL / "b1_crossfit_propensity_private.parquet"
    sessions = project / C9_SESSION_REL
    for path in (b1, propensity, sessions):
        if not path.is_file() or parquet_rows(path) != EXPECTED_B1_ROWS:
            raise RuntimeError(f"C9 authority is missing or changed: {path}")
    target = state / "c9_singleton_b1_private.parquet"
    receipt = state / "c9_singleton_b1_receipt.json"
    signature = {
        "status": "PAPERWIDE_C9_SINGLETON_B1_OK",
        "b1_sha256": sha256_file(b1),
        "propensity_sha256": sha256_file(propensity),
        "session_sha256": sha256_file(sessions),
        "joined_rows": EXPECTED_STAGE07_ROWS,
    }
    if checkpoint_ok(receipt, target, signature):
        return target, json.loads(receipt.read_text())

    con.execute(
        f"""
        CREATE TEMP VIEW _b1 AS
        SELECT b1_row_id::BIGINT b1_row_id,chooser_index::BIGINT chooser_index,
               sequence_index::BIGINT sequence_index,utc_ms::BIGINT b_utc_ms,
               current_eval_cp::DOUBLE eval_cp,current_chooser_elo::DOUBLE chooser_elo,
               current_opponent_elo::DOUBLE opponent_elo,current_ply_count::DOUBLE ply_count,
               kind_draw::BOOLEAN kind_draw
        FROM read_parquet({sql_quote(b1)})
        """
    )
    attempts: list[dict[str, Any]] = []
    for tf in ("api_last_move_at_ms", "utc_ms"):
        con.execute(f"DROP TABLE IF EXISTS _c9_map_{tf}")
        con.execute(
            f"""
            CREATE TEMP TABLE _c9_map_{tf} AS
            SELECT DISTINCT b.b1_row_id,b.chooser_index,j.game_id,j.chooser_user_id,
                            j.pair_games_24m
            FROM _b1 b INNER JOIN read_parquet({sql_quote(joined)}) j
              ON b.b_utc_ms=j.{tf}
             AND b.eval_cp=CAST(j.engine_eval_cp_disconnected AS DOUBLE)
             AND b.chooser_elo=CAST(j.chooser_elo AS DOUBLE)
             AND b.opponent_elo=CAST(j.opponent_elo AS DOUBLE)
             AND b.ply_count=CAST(j.ply_count AS DOUBLE)
            """
        )
        stats = con.execute(
            f"""
            WITH r AS (SELECT b1_row_id,count(*) n FROM _c9_map_{tf} GROUP BY 1),
                 c AS (SELECT chooser_index,count(DISTINCT chooser_user_id) n FROM _c9_map_{tf} GROUP BY 1)
            SELECT count(*) FILTER (WHERE r.n=1),
                   (SELECT count(*) FROM c WHERE n=1),count(*) FROM r
            """
        ).fetchone()
        attempts.append({"time_field": tf, "unique_rows": int(stats[0]), "unique_choosers": int(stats[1]), "rows_with_candidate": int(stats[2])})
    best = sorted(attempts, key=lambda x: (x["unique_choosers"], x["unique_rows"]), reverse=True)[0]
    tf = best["time_field"]
    con.execute("DROP TABLE IF EXISTS _c9_chooser_map")
    con.execute(
        f"""
        CREATE TEMP TABLE _c9_chooser_map AS
        SELECT chooser_index,min(chooser_user_id) chooser_user_id
        FROM _c9_map_{tf} GROUP BY 1 HAVING count(DISTINCT chooser_user_id)=1
        """
    )
    if int(con.execute("SELECT count(*) FROM _c9_chooser_map").fetchone()[0]) != EXPECTED_B1_CHOOSERS:
        raise RuntimeError(f"C9 chooser bridge incomplete: {attempts}")
    con.execute("DROP TABLE IF EXISTS _c9_game_map")
    con.execute(
        f"""
        CREATE TEMP TABLE _c9_game_map AS
        SELECT DISTINCT b.b1_row_id,j.game_id,j.pair_games_24m
        FROM _b1 b INNER JOIN _c9_chooser_map c USING(chooser_index)
        INNER JOIN read_parquet({sql_quote(joined)}) j
          ON j.chooser_user_id=c.chooser_user_id
         AND b.b_utc_ms=j.{tf}
         AND b.eval_cp=CAST(j.engine_eval_cp_disconnected AS DOUBLE)
         AND b.chooser_elo=CAST(j.chooser_elo AS DOUBLE)
         AND b.opponent_elo=CAST(j.opponent_elo AS DOUBLE)
         AND b.ply_count=CAST(j.ply_count AS DOUBLE)
        """
    )
    map_qa = con.execute(
        "WITH q AS (SELECT b1_row_id,count(*) n FROM _c9_game_map GROUP BY 1) SELECT count(*) FILTER (WHERE n=1),count(*) FILTER (WHERE n>1) FROM q"
    ).fetchone()
    if (int(map_qa[0]), int(map_qa[1])) != (EXPECTED_B1_ROWS, 0):
        raise RuntimeError(f"C9 game bridge incomplete/ambiguous: {map_qa}; attempts={attempts}")

    tmp = target.with_suffix(".parquet.tmp")
    con.execute(
        f"""
        COPY (
          WITH e AS (
            SELECT b.b1_row_id,b.chooser_index,b.sequence_index,b.b_utc_ms utc_ms,
                   b.kind_draw,p.static_propensity::DOUBLE static_propensity,
                   s.session_id::BIGINT session_id,m.pair_games_24m
            FROM _b1 b INNER JOIN _c9_game_map m USING(b1_row_id)
            INNER JOIN read_parquet({sql_quote(propensity)}) p USING(b1_row_id)
            INNER JOIN read_parquet({sql_quote(sessions)}) s USING(b1_row_id)
            WHERE m.pair_games_24m=1 AND s.session_id IS NOT NULL
          ), eligible AS (
            SELECT chooser_index FROM e GROUP BY 1
            HAVING count(*)>=2 AND sum(CAST(kind_draw AS INTEGER)) BETWEEN 1 AND count(*)-1
          )
          SELECT e.* FROM e INNER JOIN eligible USING(chooser_index)
          ORDER BY chooser_index,sequence_index
        ) TO {sql_quote(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    qa = con.execute(
        f"SELECT count(*),count(DISTINCT chooser_index),sum(CAST(kind_draw AS INTEGER)),count(*) FILTER (WHERE static_propensity<=0 OR static_propensity>=1) FROM read_parquet({sql_quote(tmp)})"
    ).fetchone()
    if int(qa[0]) < 100 or int(qa[1]) < 10 or int(qa[3]) != 0:
        raise RuntimeError(f"C9 singleton support is invalid: {qa}")
    os.replace(tmp, target)
    saved = {
        **signature,
        "rows": int(qa[0]),
        "choosers": int(qa[1]),
        "kind_draws": int(qa[2]),
        "mapping_time_field": tf,
        "mapping_attempts": attempts,
        "created_utc": now(),
    }
    write_json(receipt, saved)
    return target, saved


def observed_c9(path: Path) -> tuple[int, int]:
    _, np, _, pq = import_dependencies()
    f = pq.read_table(path).to_pandas().sort_values(["chooser_index", "sequence_index"], kind="stable")
    chooser = f["chooser_index"].to_numpy(dtype=np.int64)
    kind = f["kind_draw"].to_numpy(dtype=bool)
    times = f["utc_ms"].to_numpy(dtype=np.int64)
    sessions = f["session_id"].to_numpy(dtype=np.int64)
    num = den = 0
    for a, z in chooser_slices(chooser):
        n, d = c9_later_session_totals(times[a:z], sessions[a:z], kind[a:z][None, :])
        num += int(n[0])
        den += int(d[0])
    return num, den


def randomization_p(observed: float, simulated) -> tuple[float, float, float]:
    _, np, _, _ = import_dependencies()
    finite = np.asarray(simulated, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    lo = (1 + int(np.count_nonzero(finite <= observed))) / (finite.size + 1.0)
    hi = (1 + int(np.count_nonzero(finite >= observed))) / (finite.size + 1.0)
    return lo, hi, min(1.0, 2.0 * min(lo, hi))


def c9_singleton_randomization(
    con,
    project: Path,
    joined: Path,
    state: Path,
    *,
    workers: int,
    randomizations: int,
    batch: int,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _, np, _, _ = import_dependencies()
    cache, support = build_c9_restricted_cache(con, project, joined, state)
    checkpoint_root = state / "c9_singleton_randomizations"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    config = {
        "cache_sha256": sha256_file(cache),
        "randomizations": randomizations,
        "batch": batch,
        "seed": seed,
        "estimand": "later-session kindness within 7d after pseudo-first grant; 24m singleton dyads",
    }
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    specs = [(a, min(a + batch, randomizations)) for a in range(0, randomizations, batch)]
    pending: list[tuple[int, int]] = []
    for a, z in specs:
        path = checkpoint_root / f"batch_{a:05d}_{z:05d}.npz"
        receipt = path.with_suffix(".json")
        if path.is_file() and receipt.is_file():
            saved = json.loads(receipt.read_text())
            if saved.get("config_sha256") != config_sha or saved.get("output_sha256") != sha256_file(path):
                raise RuntimeError(f"C9 checkpoint authentication failed: {path}")
        elif path.exists() or receipt.exists():
            raise RuntimeError(f"Partial C9 checkpoint exists: {path}")
        else:
            pending.append((a, z))
    if pending:
        import multiprocessing as mp
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(workers, len(pending)),
            mp_context=context,
            initializer=_c9_worker_init,
            initargs=(str(cache),),
        ) as pool:
            futures = {pool.submit(_c9_worker_batch, a, z, seed): (a, z) for a, z in pending}
            for future in as_completed(futures):
                a, z, num, den = future.result()
                path = checkpoint_root / f"batch_{a:05d}_{z:05d}.npz"
                tmp = path.with_suffix(".npz.tmp")
                with tmp.open("wb") as f:
                    np.savez_compressed(f, numerator=num, denominator=den)
                os.replace(tmp, path)
                write_json(
                    path.with_suffix(".json"),
                    {
                        "status": "PAPERWIDE_C9_SINGLETON_BATCH_OK",
                        "config_sha256": config_sha,
                        "start": a,
                        "stop_exclusive": z,
                        "output_sha256": sha256_file(path),
                        "created_utc": now(),
                    },
                )
                print(f"C9_SINGLETON_RANDOMIZATION_BATCH_COMPLETE start={a} stop={z}", flush=True)
    nums, dens = [], []
    for a, z in specs:
        data = np.load(checkpoint_root / f"batch_{a:05d}_{z:05d}.npz")
        nums.append(data["numerator"])
        dens.append(data["denominator"])
    num_sim, den_sim = np.concatenate(nums), np.concatenate(dens)
    rates = np.divide(num_sim, den_sim, out=np.full(num_sim.shape, np.nan), where=den_sim > 0)
    obs_num, obs_den = observed_c9(cache)
    obs_rate = obs_num / obs_den
    null = float(np.nanmean(rates))
    lo, hi, p = randomization_p(obs_rate, rates)
    row = {
        "restriction": "singleton_24m",
        "category": "later_session_within_7d",
        "observed_numerator": obs_num,
        "observed_denominator": obs_den,
        "observed_rate_pct": 100.0 * obs_rate,
        "null_mean_rate_pct": 100.0 * null,
        "excess_pp": 100.0 * (obs_rate - null),
        "randomization_p_two_sided": p,
        "lower_tail_plus_one": lo,
        "upper_tail_plus_one": hi,
        "null_p025_pct": 100.0 * float(np.nanquantile(rates, 0.025)),
        "null_p975_pct": 100.0 * float(np.nanquantile(rates, 0.975)),
        "randomizations": randomizations,
        "interpretation": "relationship-specific repeat-granter mechanism; not generalized stranger kindness",
    }
    return [row], {**support, "config_sha256": config_sha}


def c7x_mechanism_summary(project: Path) -> dict[str, Any]:
    candidates = sorted(
        (project / "output/frequent_dyad_census_24m_v101").glob("*/c7x_attrition.csv")
    )
    attrition: list[dict[str, Any]] = []
    authority = None
    if candidates:
        authority = candidates[-1]
        with authority.open(newline="") as f:
            for row in csv.DictReader(f):
                if row["exclusion_rule"] == "dyad":
                    attrition.append(
                        {
                            **row,
                            "threshold_games_per_unordered_pair": int(row["threshold_games_per_unordered_pair"]),
                            "total_rows_before": int(row["total_rows_before"]),
                            "rows_excluded": int(row["rows_excluded"]),
                            "rows_retained": int(row["rows_retained"]),
                            "share_excluded_pct": float(row["share_excluded_pct"]),
                            "share_retained_pct": float(row["share_retained_pct"]),
                        }
                    )
    return {
        "status": "C7X_RELATIONSHIP_MECHANISM_CLASSIFIED",
        "estimand": "kindness toward a previous benefactor versus a previous claimer",
        "paperwide_classification": "relationship-specific reciprocity/reputation",
        "not_supported_label": "generalized intrinsic kindness toward strangers",
        "reason": "A prior relationship is constitutive of C7X, so a first-meeting-only C7X estimand cannot exist.",
        "dyad_attrition_authority": str(authority) if authority else None,
        "dyad_attrition": attrition,
        "headline": {
            "benefactor_rows_from_dyads_ge10_pct": 87.68115942028986,
            "claimer_rows_from_dyads_ge10_pct": 43.12128722609072,
        },
    }


def c6_scope_summary() -> dict[str, Any]:
    return {
        "status": "C6_SCOPE_AUDITED_NO_NEW_DYAD_KINDNESS_ESTIMATE",
        "exposure_dyad": "already restricted to first-ever rated meeting in the certified history since 2013",
        "outcome": "subsequent clearly-losing timeout disconnections per 1,000 rated games",
        "why_not_filtered_like_stage07": (
            "C6's outcome is behavior across later rated games, not a kindness decision toward the original opponent. "
            "Dropping players who ever have a frequent dyad would conflate player activity with the focal relationship."
        ),
        "paperwide_interpretation": (
            "C6 is protected against a repeat exposure dyad by construction; its later-game outcome should not be "
            "described as stranger-directed kindness."
        ),
    }


PUBLIC_FILES = (
    "sample_summary.csv",
    "table1_descriptives.csv",
    "five_bin_rates.csv",
    "rating_gap_rates.csv",
    "structural_chooser_fe.csv",
    "persistence.csv",
    "a1_unfamiliar_opponent_sensitivity.csv",
    "patron_singleton_rematch.csv",
    "c9_singleton_randomization.csv",
    "c7r_prefocal_authority.json",
    "c7x_relationship_mechanism.json",
    "c6_scope.json",
    "module_status.csv",
    "summary.json",
    "README_results.md",
)


def verify_public_directory(root: Path, *, require_success: bool) -> dict[str, Any]:
    forbidden_headers = {
        "game_id",
        "chooser_user_id",
        "opponent_user_id",
        "username_norm",
        "chooser_username_norm",
        "recipient_user_id",
    }
    for name in PUBLIC_FILES:
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Required public result is missing/empty: {path}")
        if path.suffix == ".csv":
            with path.open(newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                if forbidden_headers.intersection(header):
                    raise RuntimeError(f"Private identifier leaked into {name}")
                if next(reader, None) is None:
                    raise RuntimeError(f"Public CSV has no result rows: {name}")
    summary = json.loads((root / "summary.json").read_text())
    if summary.get("status") != "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_OK":
        raise RuntimeError("Public summary status changed")
    if require_success:
        success = json.loads((root / "_SUCCESS.json").read_text())
        if success.get("status") != "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_INDEPENDENT_VERIFICATION_OK":
            raise RuntimeError("Success receipt status changed")
        for row in success["files"]:
            path = root / row["path"]
            if sha256_file(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
                raise RuntimeError(f"Public result hash mismatch: {path}")
    return {"files_checked": len(PUBLIC_FILES), "run_id": summary["run_id"]}


def result_readme(run_id: str) -> str:
    return f"""# Paper-wide repeat-dyad audit ({run_id})

This run tests whether the paper's estimable kindness results survive focal-dyad
restrictions.  It never applies the overbroad rule “drop every game by a player who
ever has a frequent opponent.”

## Read these results in this order

1. `c7r_prefocal_authority.json` is the ordering-valid structural check: prior
   meetings are counted strictly before the focal decision in certified history
   beginning in 2013.
2. `structural_chooser_fe.csv`, `table1_descriptives.csv`, and `persistence.csv`
   compare the complete Stage 07 panel to 24-month singleton, <3, and <5 focal-dyad
   samples.  Whole-window counts are strict sensitivities, not pre-treatment facts.
3. `a1_unfamiliar_opponent_sensitivity.csv` requires the recipient's later choice
   to concern a different opponent, then tightens that outcome dyad to singleton,
   <3, and <5.
4. `patron_singleton_rematch.csv` reconstructs kindness dose under each restriction
   and performs a fresh deterministic 1:3 rematch within restricted opportunity
   count and modal-speed cells.
5. `c9_singleton_randomization.csv` re-runs conditional randomization after retaining
   only 24-month-singleton focal opportunities.  C7X is separately classified as a
   relationship-specific estimand in `c7x_relationship_mechanism.json`.

The private Parquet checkpoints contain account/game keys and remain under the
project's `derived/replication/..._PRIVATE` directory.  This public result directory
contains aggregate output only.
"""


def execute(args: argparse.Namespace) -> Path:
    started = time.time()
    project = args.project_root.resolve()
    auth = authenticate_inputs(project)
    state = args.state_root.resolve()
    state.mkdir(parents=True, exist_ok=True)
    output_root = args.output_root.resolve()
    final = output_root / args.run_id
    staging = output_root / f".{args.run_id}.tmp.{os.getpid()}"
    if final.exists() or staging.exists():
        raise RuntimeError(f"Refusing to overwrite output: {final} or {staging}")
    staging.mkdir(parents=True, exist_ok=False)
    tempdir = state / "duckdb_tmp"
    con = duckdb_connect(tempdir, args.threads, args.memory_limit)
    modules: list[dict[str, Any]] = []
    try:
        joined = build_joined_checkpoint(con, project, state, auth)
        structural = structural_tables(con, joined)
        for name, rows in structural.items():
            write_csv(staging / f"{name}.csv", rows)
        fe = structural_fe_tables(con, joined)
        write_csv(staging / "structural_chooser_fe.csv", fe)
        persistence = persistence_tables(con, joined)
        write_csv(staging / "persistence.csv", persistence)
        modules.append({"module": "structural_and_persistence", "status": "complete", "result_rows": sum(len(x) for x in structural.values()) + len(fe) + len(persistence)})

        a1_rows, a1_bridge = a1_sensitivity(con, project, joined, state)
        write_csv(staging / "a1_unfamiliar_opponent_sensitivity.csv", a1_rows)
        modules.append({"module": "A1_receipt_to_different_unfamiliar_opponent", "status": "complete", "result_rows": len(a1_rows)})

        patron_rows, patron_support = patron_sensitivity(con, project, joined, state)
        write_csv(staging / "patron_singleton_rematch.csv", patron_rows)
        modules.append({"module": "Patron_reconstructed_kindness_and_rematch", "status": "complete", "result_rows": len(patron_rows)})

        c9_rows, c9_support = c9_singleton_randomization(
            con,
            project,
            joined,
            state,
            workers=args.workers,
            randomizations=args.c9_randomizations,
            batch=args.c9_batch,
            seed=args.c9_seed,
        )
        write_csv(staging / "c9_singleton_randomization.csv", c9_rows)
        modules.append({"module": "C9_singleton_conditional_randomization", "status": "complete", "result_rows": len(c9_rows)})

        write_json(staging / "c7r_prefocal_authority.json", C7R_AUTHORITY)
        write_json(staging / "c7x_relationship_mechanism.json", c7x_mechanism_summary(project))
        write_json(staging / "c6_scope.json", c6_scope_summary())
        modules.extend(
            [
                {"module": "C7R_prefocal_history_authority", "status": "incorporated", "result_rows": 1},
                {"module": "C7X_relationship_specific_classification", "status": "complete", "result_rows": 1},
                {"module": "C6_first_exposure_scope", "status": "audited_no_new_estimate", "result_rows": 1},
            ]
        )
        write_csv(staging / "module_status.csv", modules)
        summary = {
            "status": "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_OK",
            "version": VERSION,
            "run_id": args.run_id,
            "created_utc": now(),
            "runtime_seconds": time.time() - started,
            "threads": args.threads,
            "c9_workers": args.workers,
            "c9_randomizations": args.c9_randomizations,
            "input_authentication": auth,
            "stage07_joined_checkpoint": str(joined),
            "causal_ordering_rule": "C7R pre-focal history is primary; whole-window pair counts are sensitivities",
            "targeted_exclusion_rule": "drop the focal dyad only; never drop all games by either player",
            "a1_bridge": a1_bridge,
            "patron_support": patron_support,
            "c9_support": c9_support,
            "modules": modules,
        }
        write_json(staging / "summary.json", summary)
        (staging / "README_results.md").write_text(result_readme(args.run_id))
        verify_public_directory(staging, require_success=False)
        files = []
        for name in PUBLIC_FILES:
            path = staging / name
            files.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        with (staging / "report_file_hashes.tsv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=("path", "bytes", "sha256"), delimiter="\t")
            writer.writeheader()
            writer.writerows(files)
        write_json(
            staging / "_SUCCESS.json",
            {
                "status": "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_INDEPENDENT_VERIFICATION_OK",
                "run_id": args.run_id,
                "created_utc": now(),
                "files": files,
            },
        )
        staging.rename(final)
        verify_public_directory(final, require_success=True)
        if args.execution_pointer:
            write_json(
                args.execution_pointer,
                {"status": "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_OK", "run_id": args.run_id, "result_root": str(final)},
            )
        print(f"PAPERWIDE_REPEAT_DYAD_AUDIT_V100_OK: {final}", flush=True)
        return final
    except Exception:
        if staging.exists():
            (staging / "FAILED.txt").write_text(f"failed_utc={now()}\n")
        raise
    finally:
        con.close()


def self_test() -> None:
    global EXPECTED_PROFILE_ROWS
    import tempfile

    _, np, pa, pq = import_dependencies()
    odds = np.log(np.array([0.2, 0.4, 0.7])) - np.log1p(-np.array([0.2, 0.4, 0.7]))
    selection = conditional_selection_probabilities(odds, 1)
    assert selection.shape == (3, 2)
    assert 0 < selection[0, 1] < 1
    choices = np.array([[True, False, True, False], [False, True, False, True]])
    num, den = c9_later_session_totals(
        np.array([0, 10, 40, 50]) * 60_000,
        np.array([1, 1, 2, 2]),
        choices,
    )
    assert (num.tolist(), den.tolist()) == ([1, 1], [2, 2])
    assert math.isclose(weighted_corr_moments([(1, 1, 1), (1, 2, 2)]), 1.0)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "tiny.parquet"
        table = pa.table(
            {
                "chooser_user_id": [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3],
                "kind_draw": [0, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1],
                "fair_competitive": [True, True, False, False] * 3,
                "clearly_worse": [False, False, True, True] * 3,
                "pair_games_24m": [1] * 12,
            }
        )
        pq.write_table(table, path)
        con = duckdb_connect(Path(d) / "tmp", 2, "1GB")
        rows = categorical_chooser_fe(
            con,
            path,
            sample="tiny",
            filter_sql="TRUE",
            model="tiny_desert",
            category_sql="CASE WHEN fair_competitive THEN 'fair' ELSE 'worse' END",
            categories=("fair", "worse"),
            reference="fair",
            extra_where="TRUE",
        )
        con.close()
        assert len(rows) == 1 and math.isfinite(rows[0]["effect_pp"])

    # Regression test for v1.0.1: ineligible original-kind accounts must not
    # consume ranks ahead of accounts that remain kind under the restriction.
    with tempfile.TemporaryDirectory() as d:
        project = Path(d)
        state = project / "state"
        state.mkdir()
        snapshot = project / PROFILE_REL
        snapshot.parent.mkdir(parents=True)
        users: list[dict[str, Any]] = []
        for i in range(3):
            users.append(
                {
                    "username_norm": f"eligible_kind_{i}",
                    "acquisition_role": "kind",
                    "returned": True,
                    "patron": i == 0,
                    "modal_speed_group": "blitz",
                }
            )
        for i in range(100):
            users.append(
                {
                    "username_norm": f"ineligible_kind_{i}",
                    "acquisition_role": "kind",
                    "returned": True,
                    "patron": False,
                    "modal_speed_group": "blitz",
                }
            )
        for i in range(9):
            users.append(
                {
                    "username_norm": f"control_{i}",
                    "acquisition_role": "control",
                    "returned": True,
                    "patron": False,
                    "modal_speed_group": "blitz",
                }
            )
        pq.write_table(pa.Table.from_pylist(users), snapshot)
        opportunities = []
        for i, user in enumerate(users):
            opportunities.append(
                {
                    "game_id": f"test_{i}",
                    "chooser_username_norm": user["username_norm"],
                    "fair_competitive": True,
                    "kind_draw": user["username_norm"].startswith("eligible_kind_"),
                    "speed": "blitz",
                    "pair_games_24m": 1,
                }
            )
        joined = project / "joined.parquet"
        pq.write_table(pa.Table.from_pylist(opportunities), joined)
        original_expected = EXPECTED_PROFILE_ROWS
        EXPECTED_PROFILE_ROWS = len(users)
        try:
            con = duckdb_connect(project / "duckdb", 2, "1GB")
            patron_rows, _ = patron_sensitivity(con, project, joined, state)
            con.close()
        finally:
            EXPECTED_PROFILE_ROWS = original_expected
        assert all(
            row["matched_kind_users"] == 3
            and row["matched_control_users"] == 9
            for row in patron_rows
        )
    print("PAPERWIDE_REPEAT_DYAD_AUDIT_V100_SYNTHETIC_OK")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path("/Volumes/XT_Pro/lichess_kindness"))
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execution-pointer", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--memory-limit", default="11980MB")
    parser.add_argument("--c9-randomizations", type=int, default=4_999)
    parser.add_argument("--c9-batch", type=int, default=250)
    parser.add_argument("--c9-seed", type=int, default=20_250_825)
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    if not args.execute:
        parser.error("Use --execute for a production run or --self-test")
    args.run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.state_root = args.state_root or args.project_root / "derived/replication/paperwide_repeat_dyad_audit_v100_PRIVATE"
    args.output_root = args.output_root or args.project_root / "output/paperwide_repeat_dyad_audit_v100"
    if not 1 <= args.threads <= 10 or not 1 <= args.workers <= 10:
        parser.error("--threads and --workers must be between 1 and 10")
    if args.c9_randomizations < 99 or args.c9_batch < 1:
        parser.error("C9 requires at least 99 randomizations and a positive batch size")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
    else:
        execute(args)


if __name__ == "__main__":
    main()
