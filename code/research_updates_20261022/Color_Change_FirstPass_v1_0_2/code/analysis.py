"""Payoff audit and descriptive weekly series; expected runtime 15-45 min.
No continuous-DiD, threshold-relocation, or IV causal estimate is released.
"""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor,as_completed
from common import *
from checkpoints import authenticate_checkpoint

def build_established_cohort(project,work):
    """Fixed, strictly pre-period same-speed history; avoids inferred account age."""
    dest=Path(work)/"established_2023_10.parquet"
    cps=[Path(project)/"derived/replication/glicko2_cost_layer/checkpoints"/f"speed={s}"/"state_after_2023-10.parquet" for s in SPEEDS]
    key=digest([stamp(p) for p in cps]); receipt=dest.with_suffix(".json")
    if dest.exists() and receipt.exists() and read_json(receipt).get("key")==key and read_json(receipt)["sha256"]==sha(dest):return dest
    c=connection(Path(work)/"tmp/cohort",threads=5,memory_mb=2048)
    parts=[]
    for s,p in zip(SPEEDS,cps):
        authenticate_checkpoint(project,work,s,"2023-10")
        parts.append(f"SELECT user_id,{q(s)} AS speed,games_seen FROM {scan(p)} WHERE games_seen>=100")
    copy_query(c," UNION ALL ".join(parts),dest);c.close()
    write_json(receipt,{"key":key,"sha256":sha(dest),"definition":"at least 100 rated updates in the same speed through October 2023; a conservative fixed established cohort"})
    return dest

def state_query(work,month):
    work=Path(work); base=work/"base"/f"month={month}"/"opportunities.parquet"
    if month not in POST_MONTHS:
        return f"SELECT * FROM {scan(base)} WHERE chooser<>opponent"
    raw=[work/"replay"/f"speed={s}"/f"month={month}"/"targets.parquet" for s in SPEEDS]
    # Same game ID join; choose both pre-game states before either player's update.
    w="b.color='white'"
    q0=f"""SELECT b.* EXCLUDE(rd,opp_rd,prior_games,gap_days,chooser_user_id,both_null),
      CASE WHEN {w} THEN r.white_pre_rd ELSE r.black_pre_rd END AS rd,
      CASE WHEN {w} THEN r.black_pre_rd ELSE r.white_pre_rd END AS opp_rd,
      CASE WHEN {w} THEN r.white_prior_games ELSE r.black_prior_games END::BIGINT AS prior_games,
      CASE WHEN (CASE WHEN {w} THEN r.white_last_ms ELSE r.black_last_ms END)>=0 THEN
       (b.utc_ms-(CASE WHEN {w} THEN r.white_last_ms ELSE r.black_last_ms END))/86400000.0 END AS gap_days,
      CASE WHEN {w} THEN r.white_id ELSE r.black_id END::BIGINT AS chooser_user_id,
      (r.white_rating_diff IS NULL AND r.black_rating_diff IS NULL) AS both_null
      FROM {scan(base)} b LEFT JOIN {scan(raw)} r USING(game_id) WHERE b.chooser<>b.opponent"""
    return q0

def dose_month(task):
    project,work,month,memory_mb=task;work=Path(work)
    dest=work/"dose"/f"month={month}"/"opportunities.parquet";receipt=dest.with_suffix(".json")
    inputs=[work/"base"/f"month={month}"/"opportunities.parquet",work/"established_2023_10.parquet"]
    if month in POST_MONTHS: inputs += [work/"replay"/f"speed={s}"/f"month={month}"/"targets.parquet" for s in SPEEDS]
    key=digest({"version":DATA_CONTRACT_VERSION,"inputs":[stamp(p) for p in inputs]})
    if dest.exists() and receipt.exists():
        r=read_json(receipt)
        if r["key"]==key and r["output"]["sha256"]==sha(dest):return r
        raise RuntimeError(f"Dose cache inputs changed: {month}")
    c=connection(work/"tmp"/f"dose_{month}",memory_mb=memory_mb)
    if month in POST_MONTHS:
        bp=work/"base"/f"month={month}"/"opportunities.parquet"
        rp=[work/"replay"/f"speed={s}"/f"month={month}"/"targets.parquet" for s in SPEEDS]
        audit=c.execute(f"""SELECT count(*),count(DISTINCT b.game_id),count(*) FILTER(WHERE
          r.game_id IS NULL OR r.utc_ms<>b.utc_ms OR
          b.rating<>CASE WHEN b.color='white' THEN r.white_elo ELSE r.black_elo END OR
          b.opp_rating<>CASE WHEN b.color='white' THEN r.black_elo ELSE r.white_elo END)
          FROM {scan(bp)} b LEFT JOIN {scan(rp)} r USING(game_id) WHERE b.chooser<>b.opponent""").fetchone()
        if audit[0]!=audit[1] or audit[2]:raise RuntimeError(f"{month}: replay/panel key, time, or displayed-rating mismatch {audit}")
    joined=dest.with_name("state.parquet")
    copy_query(c,f"SELECT b.*, coalesce(e.games_seen>=100,false) AS established_at_2023_10 FROM ({state_query(work,month)}) b LEFT JOIN {scan(work/'established_2023_10.parquet')} e ON b.chooser_user_id=e.user_id AND b.speed=e.speed",joined)
    c.close();dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix(".tmp.parquet");tmp.unlink(missing_ok=True)
    writer=None;n=0;valid_n=0;old_err=0.;min_replay_time=0
    for batch in pq.ParquetFile(joined).iter_batches(batch_size=100000,use_threads=False):
        df=batch.to_pandas();color=np.where(df.color.eq("white"),1.,-1.)
        valid=df.rd.notna().to_numpy()&df.opp_rd.notna().to_numpy()
        g=df.opp_rating.to_numpy()-df.rating.to_numpy()
        columns={x:np.full(len(df),np.nan) for x in ("E_old","K_old","draw_old","win_old","E_new","K_new","draw_new","win_new")}
        if valid.any():
            values=[df.rating.to_numpy()[valid],df.opp_rating.to_numpy()[valid],df.rd.to_numpy()[valid],df.opp_rd.to_numpy()[valid],color[valid]]
            for suffix,a in (("old",0.),("new",ADVANTAGE)):
                for name,v in zip(("E","K","draw","win"),payoffs(*values,a)):
                    columns[f"{name}_{suffix}"][valid]=v
        for k,v in columns.items():df[k]=v
        df["g"]=g;df["c"]=color;df["d_G"]=df.draw_new-df.draw_old;df["d_C"]=df.win_new-df.win_old
        df["delta_kappa"]=df.d_C-df.d_G
        df["premium_ratio_signed"]=np.divide(df.delta_kappa,df.d_G.abs(),out=np.full(len(df),np.nan),where=df.d_G.abs()>1e-9)
        df["premium_ratio_abs"]=df.premium_ratio_signed.abs()
        df["near_zero_dose"]=valid&(df.d_G.abs().to_numpy()<=1e-9)
        df["rd_bin"]=np.where(valid,rd_bins(df.rd.to_numpy()),-1).astype(np.int8)
        df["gap_bin"]=gap_bins(g)
        df["phase"]=phase(df.utc_ms.to_numpy(np.int64))
        df["valid_state"]=valid
        df["old_sign_flip_band"]=((color==1)&(g>0)&(g<ADVANTAGE))|((color==-1)&(g>-ADVANTAGE)&(g<0))
        df["high_rd_returning_strict"]=valid&(df.rd>=200)&df.established_at_2023_10&(df.gap_days>=90)
        # This is game experience, not an account-age or novice classification.
        df["prior_games_bin"]=np.where(df.prior_games.isna(),"unknown",np.where(df.prior_games<30,"0-29",np.where(df.prior_games<100,"30-99","100+")))
        check=valid&df.stored_draw.notna().to_numpy()&(df.source_kind=="certified_stage07").to_numpy()
        if check.any(): old_err=max(old_err,float(np.max(np.abs(df.draw_old.to_numpy()[check]-df.stored_draw.to_numpy()[check]))))
        # All extension historical payoff columns are ignored unless RD comes
        # from this replay. No old color patch is treated as certified state.
        if month not in POST_MONTHS and month not in months("2023-11","2025-10"):
            if valid.any(): raise RuntimeError("Uncertified extension rating states reached dose calculation")
        if month in POST_MONTHS and not valid.all():raise RuntimeError(f"{month}: incomplete target state join")
        table=pa.Table.from_pandas(df,preserve_index=False)
        if writer is None:writer=pq.ParquetWriter(tmp,table.schema,compression="zstd")
        writer.write_table(table);n+=len(df);valid_n+=int(valid.sum())
    if writer is None:raise RuntimeError(f"Empty month: {month}")
    writer.close();os.replace(tmp,dest);joined.unlink()
    rec={"key":key,"month":month,"rows":n,"valid_state_rows":valid_n,"stored_old_draw_max_abs_difference":old_err,"output":parquet_receipt(dest)}
    write_json(receipt,rec);log(f"Dose {month}: {valid_n:,}/{n:,} rows have authenticated rating states")
    return rec

def dose_all(project,work,workers,memory_mb):
    build_established_cohort(project,work)
    out=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        fs=[pool.submit(dose_month,(str(project),str(work),m,memory_mb)) for m in months("2023-09","2026-04")]
        for f in as_completed(fs):out.append(f.result())
    return sorted(out,key=lambda x:x["month"])

def summarize(work,report,workers):
    work,report=Path(work),Path(report);report.mkdir(parents=True,exist_ok=True)
    files=sorted((work/"dose").glob("month=*/opportunities.parquet"))
    c=connection(work/"tmp/summary",threads=workers,memory_mb=4096)
    c.execute(f"CREATE VIEW dose AS SELECT *, date_trunc('week',epoch_ms(utc_ms)) AS week FROM {scan(files)}")
    queries={
      "dose_distribution": """SELECT month,color,speed,rd_bin,gap_bin,prior_games_bin,established_at_2023_10,
        count(*) AS n,avg(abs(d_G)) AS mean_abs_dG,quantile_cont(abs(d_G),[.1,.5,.9,.99])::VARCHAR AS dG_quantiles,
        avg(d_C) AS mean_dC,avg(delta_kappa) AS mean_delta_kappa,
        avg(premium_ratio_abs) AS mean_abs_premium_ratio,quantile_cont(premium_ratio_abs,.99) AS p99_abs_premium_ratio,
        sum(near_zero_dose::INTEGER) AS near_zero_dose_n,
        avg((abs(g)<=50)::INTEGER) AS within_50_share
        FROM dose WHERE valid_state GROUP BY ALL""",
      "premium_near_equality":"""SELECT color,rd_bin,abs(g)<=50 AS within_50,old_sign_flip_band,
        count(*) AS n,avg(abs(d_G)) AS mean_abs_dG,avg(abs(delta_kappa)) AS mean_abs_delta_kappa,
        quantile_cont(premium_ratio_abs,[.5,.9,.99])::VARCHAR AS ratio_quantiles,
        sum(near_zero_dose::INTEGER) AS zero_denominator_n FROM dose WHERE valid_state GROUP BY ALL""",
      "weekly_color_grant_descriptive":"""SELECT week,color,speed,established_at_2023_10,
        CASE WHEN cp>=-100 THEN 'competitive' WHEN cp<=-300 THEN 'clearly_losing' ELSE 'middle' END AS board_state,
        count(*) AS opportunities,sum(grant) AS grants,100*avg(grant) AS grant_percent,
        sum(valid_state::INTEGER) AS authenticated_state_n FROM dose GROUP BY ALL""",
      "state_coverage":"SELECT month,source_kind,count(*) AS n,sum(valid_state::INTEGER) AS valid_state_n,sum(established_at_2023_10::INTEGER) AS fixed_established_n FROM dose GROUP BY ALL",
      "returning_stratum_support":"SELECT month,color,count(*) AS n,avg(abs(d_G)) AS mean_abs_dG,avg(prior_games) AS mean_prior_games,avg(gap_days) AS mean_gap_days FROM dose WHERE high_rd_returning_strict GROUP BY ALL",
    }
    for name,sql in queries.items():
        dest=report/(name+".parquet");copy_query(c,sql,dest)
        c.execute(f"COPY (SELECT * FROM {scan(dest)}) TO {q(report/(name+'.csv'))} (HEADER,DELIMITER ',')")
    diags=sorted((work/"replay").glob("speed=*/month=*/diagnostics.parquet"))
    copy_query(c,f"SELECT *,sum_error/n AS signed_error,sum_abs_error/n AS mae,sqrt(sum_squared_error/n) AS rmse,abs_gt_1::DOUBLE/n AS abs_gt_1_share,abs_gt_2::DOUBLE/n AS abs_gt_2_share,sum_old_abs_error/n AS old_formula_mae FROM {scan(diags)}",report/"reconstruction_cells.parquet")
    c.execute(f"COPY (SELECT * FROM {scan(report/'reconstruction_cells.parquet')}) TO {q(report/'reconstruction_cells.csv')} (HEADER)")
    # Match November 1-18 baseline separately within outcome/speed/color/RD/gap.
    copy_query(c,f"""WITH b AS (SELECT * FROM {scan(report/'reconstruction_cells.parquet')} WHERE phase='pre')
      SELECT p.month,p.speed,p.color,p.outcome,p.rd_bin,p.gap_bin,p.n AS post_n,b.n AS baseline_n,
        p.mae AS post_mae,b.mae AS pre_mae,p.mae-b.mae AS mae_difference,
        p.signed_error AS post_signed_error,b.signed_error AS pre_signed_error,
        p.old_formula_mae, p.mae-p.old_formula_mae AS new_minus_old_mae
      FROM {scan(report/'reconstruction_cells.parquet')} p LEFT JOIN b USING(speed,color,outcome,rd_bin,gap_bin)
      WHERE p.phase='post'""",report/"matched_reconstruction.parquet")
    c.execute(f"COPY (SELECT * FROM {scan(report/'matched_reconstruction.parquet')}) TO {q(report/'matched_reconstruction.csv')} (HEADER)")
    hourly=sorted((work/"replay").glob("speed=*/month=*/hourly_games.parquet"))
    copy_query(c,f"SELECT * FROM {scan(hourly)}",report/"hourly_rated_games.parquet")
    c.close()

def visibility_status():
    return {"status":"NOT_IDENTIFIED_FROM_CURRENT_REPLAY",
      "reason":"Certified Stage06 anchors to integer PGN ratings and stores RD, sigma, game counts, and last-update time; no fractional pregame rating is retained.",
      "integer_match_diagnostics":"floor(predicted_delta) and floor(predicted_delta+0.5) are diagnostics only, not source-pinned production display rules.",
      "exact_visibility_share":None,"chooser_cumulative_visible_games":None,
      "needed":"Source-pinned display conversion plus validated fractional pregame ratings for all realized same-speed rated games, or justified latent-phase bounds.",
      "awareness":"Even exact display differences establish possible feedback, not observed awareness."}
