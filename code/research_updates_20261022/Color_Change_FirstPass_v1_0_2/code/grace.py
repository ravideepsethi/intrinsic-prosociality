"""January-mechanics diagnostics, not an automatic deployment-date estimate.
Expected runtime: 5-20 min for January-February, two workers.
"""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor,as_completed
from common import *
from panel import choose

def material_sql(fen):
    board=f"split_part({fen},' ',1)"
    expr=[]
    for piece,value in (("p",1),("n",3),("b",3),("r",5),("q",9)):
        wc=f"(length({board})-length(replace({board},{q(piece.upper())},'')))"
        bc=f"(length({board})-length(replace({board},{q(piece)},'')))"
        expr.append(f"{value}*({wc}-{bc})")
    return "("+"+".join(expr)+")"

def grace_month(task):
    project,work,month=task;project,work=Path(project),Path(work)
    candidate=project/"derived/replication/pgn_timeforfeit_candidates"/f"month={month}"/"api_target_candidates_ge5s_or_missing.parquet"
    roots=[project/"derived/replication_36m/api_timeout_enrichment_extension",project/"derived/replication/api_timeout_enrichment"]
    matches=[]
    for root in roots:
        files=sorted((root/f"month={month}"/"responses").glob("unit-*.parquet"))
        marker=root/f"month={month}"/"_SUCCESS.json"
        if files and marker.exists() and read_json(marker).get("final_ok") is True:matches.append((files,marker))
    if not candidate.exists() or not matches:
        return {"month":month,"status":"MISSING_COMPLETE_CANDIDATE_API_PAIR","candidate_path":str(candidate),"api_roots":[str(x) for x in roots]}
    if len(matches)>1:
        return {"month":month,"status":"AMBIGUOUS_API_PAIR_REQUIRES_EXISTING_LINEAGE_BINDING"}
    files,marker=matches[0];cols=schema(candidate);ac=schema(files[0])
    needed={"game_id","utc_date","utc_time","candidate_chooser_color","fen_after_last_move","result","disconnected_clock_last_obs_s"}
    if not needed<=cols:raise RuntimeError(f"January-mechanics candidate schema changed: {needed-cols}")
    status=choose(ac,["api_status","status"],True,"a")
    speed=choose(ac,["api_speed","speed"],True,"a")
    rated=choose(ac,["api_rated","rated"],False,"a")
    dest=work/"grace"/f"month={month}";dest.mkdir(parents=True,exist_ok=True)
    c=connection(dest/"tmp",threads=2,memory_mb=1024)
    try:
        c.execute(f"CREATE TEMP VIEW cand AS SELECT * FROM {scan(candidate)}")
        c.execute(f"CREATE TEMP VIEW api AS SELECT * FROM {scan(files)}")
        cn,cu=c.execute("SELECT count(*),count(DISTINCT game_id) FROM cand").fetchone()
        an,au=c.execute("SELECT count(*),count(DISTINCT game_id) FROM api").fetchone()
        missing=c.execute("SELECT count(*) FROM cand LEFT JOIN api USING(game_id) WHERE api.game_id IS NULL").fetchone()[0]
        if cn!=cu or an!=au or cn!=an or missing:raise RuntimeError(f"{month}: candidate/API key coverage failed {(cn,cu,an,au,missing)}")
        time_sql="epoch_ms(try_strptime(replace(CAST(s.utc_date AS VARCHAR),'.','-')||' '||CAST(s.utc_time AS VARCHAR),'%Y-%m-%d %H:%M:%S'))"
        mat=material_sql("s.fen_after_last_move")
        c.execute(f"""CREATE TEMP VIEW joined AS SELECT {time_sql} AS utc_ms,{speed}::VARCHAR AS speed,
          s.candidate_chooser_color AS color,{status}::VARCHAR AS status,{rated}::BOOLEAN AS rated,
          s.disconnected_clock_last_obs_s AS disconnected_clock,
          CASE WHEN s.candidate_chooser_color='white' THEN {mat} ELSE -{mat} END AS own_material_adv,
          s.result='1/2-1/2' AS draw,
          CASE WHEN s.candidate_chooser_color='white' THEN s.result='1-0' ELSE s.result='0-1' END AS chooser_win,
          s.fen_after_last_move IS NOT NULL AS material_known
          FROM cand s JOIN api a USING(game_id)""")
        if c.execute("SELECT count(*) FROM joined WHERE utc_ms IS NULL OR status IS NULL OR color NOT IN ('white','black')").fetchone()[0]:raise RuntimeError("Unclassified rows in grace diagnostic inputs")
        strata="""CASE WHEN NOT material_known THEN 'unknown' WHEN own_material_adv<=-3 THEN 'chooser_down_3plus' WHEN own_material_adv>=3 THEN 'chooser_up_3plus' ELSE 'within_2' END"""
        sql=f"""SELECT date_trunc('day',epoch_ms(utc_ms)) AS day,speed,color,{strata} AS material_group,
          count(*) AS targeted_timeforfeit_games,
          count(*) FILTER(WHERE status='timeout') AS active_resolutions,
          count(*) FILTER(WHERE status='outoftime') AS clock_expirations,
          count(*) FILTER(WHERE status='timeout' AND draw) AS active_draws,
          count(*) FILTER(WHERE status='timeout' AND chooser_win) AS active_chooser_wins,
          avg((status='timeout')::INTEGER) AS active_share_targeted,
          count(*) FILTER(WHERE rated IS NULL) AS rated_field_missing
          FROM joined WHERE disconnected_clock>=5 AND (rated OR rated IS NULL) GROUP BY ALL"""
        copy_query(c,sql,dest/"daily_cells.parquet")
        copy_query(c,"""SELECT (utc_ms//3600000)*3600000 AS hour_ms,speed,
          count(*) AS targeted_timeforfeit_games,count(*) FILTER(WHERE status='timeout') AS targeted_timeouts
          FROM joined WHERE disconnected_clock>=5 AND (rated OR rated IS NULL) GROUP BY ALL""",dest/"hourly_targeted.parquet")
        rec={"month":month,"status":"TARGETED_FRAME_DIAGNOSTICS_COMPLETE","rows_before_clock_restriction":cn,
          "denominator":"API-enriched time-forfeit candidates with last observed disconnected clock >=5 seconds; NOT all disconnections or all platform games",
          "api_success_sha256":sha(marker),"candidate":stamp(candidate),"api_files":[stamp(p) for p in files],
          "outputs":{"daily":parquet_receipt(dest/"daily_cells.parquet"),"hourly":parquet_receipt(dest/"hourly_targeted.parquet")}}
        write_json(dest/"_SUCCESS.json",rec);return rec
    finally:c.close()

def grace_all(project,work,report,workers):
    out=[]
    with ProcessPoolExecutor(max_workers=min(workers,2)) as pool:
        fs=[pool.submit(grace_month,(str(project),str(work),m)) for m in ("2026-01","2026-02")]
        for f in as_completed(fs):out.append(f.result())
    paths=[x["outputs"]["daily"]["path"] for x in out if "outputs" in x]
    if paths:
        c=connection(Path(work)/"tmp/grace_summary",threads=workers,memory_mb=2048)
        copy_query(c,f"SELECT * FROM {scan(paths)}",Path(report)/"grace_daily_targeted.parquet")
        c.execute(f"COPY (SELECT * FROM {scan(paths)}) TO {q(Path(report)/'grace_daily_targeted.csv')} (HEADER)")
        # Supply seven-day differences for source-informed review, without
        # selecting a censoring date or consulting grant outcomes.
        copy_query(c,f"""WITH x AS (SELECT day,speed,material_group,
          sum(targeted_timeforfeit_games) AS n,sum(active_resolutions) AS active FROM {scan(paths)} GROUP BY ALL),
          w AS (SELECT *,sum(active) OVER(PARTITION BY speed,material_group ORDER BY day RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING)::DOUBLE/
           nullif(sum(n) OVER(PARTITION BY speed,material_group ORDER BY day RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING),0) AS before_share,
           sum(active) OVER(PARTITION BY speed,material_group ORDER BY day RANGE BETWEEN CURRENT ROW AND INTERVAL 6 DAY FOLLOWING)::DOUBLE/
           nullif(sum(n) OVER(PARTITION BY speed,material_group ORDER BY day RANGE BETWEEN CURRENT ROW AND INTERVAL 6 DAY FOLLOWING),0) AS after_share
           FROM x)
          SELECT *,after_share-before_share AS change FROM w WHERE day BETWEEN DATE '2026-01-20' AND DATE '2026-02-15'""",Path(report)/"grace_candidate_date_diagnostics.parquet")
        c.close()
    receipt={"input_results":out,"censoring_cutoff_utc":None,"status":"SOURCE_AND_GROUP_REVIEW_REQUIRED",
      "jan30":"Issue-open date, not a certified production-change date.",
      "platform_timeout_share":"Not identified by >=5-second candidate-only API data; targeted ratios must not replace the platform-wide control in B2.",
      "iv_followup":"No IV exposure cohort is certified until the outcome censoring timestamp is fixed. Eligibility is exposure_time + 90 days <= censor_time; color x post refers to recipient's later choice.",
      "source_to_pin":"https://github.com/lichess-org/lila/issues/19256 plus implementing source and deployment evidence"}
    write_json(Path(report)/"grace_and_iv_dependencies.json",receipt)
    return receipt
