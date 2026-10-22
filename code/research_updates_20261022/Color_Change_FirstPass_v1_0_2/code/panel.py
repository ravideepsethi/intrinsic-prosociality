"""Project-specific Parquet adapters. Expected runtime: 10-40 min / 32 months.
Ten independent monthly workers; one DuckDB thread each, bounded memory.
"""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback
from common import *
from timestamps import resolve_timestamp_source,timestamp_expression,authenticate_sources,make_timestamp_table

CORE_SUCCESS_SHA="8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"

def catalog(project):
    project=Path(project); result=[]
    core=project/"derived/replication/analysis_panel_24m_sf100k"
    if not (core/"_SUCCESS.json").exists() or sha(core/"_SUCCESS.json")!=CORE_SUCCESS_SHA:
        raise RuntimeError("Certified Stage07 root receipt does not match the pinned 24-month authority.")
    certified={x["month"]:x for x in read_json(core/"_SUCCESS.json")["monthly_outputs"]}
    prior_path=project/"output/c7_color_advantage_preanalysis_v104_launcher/20260826T165128Z/panel_authentication.json"
    prior={};prior_time=-1
    if prior_path.is_file():
        p=read_json(prior_path)
        if p.get("status")=="STAGE07_24M_PHYSICAL_AUTHENTICATION_OK" and p.get("receipt_sha256")==CORE_SUCCESS_SHA:
            prior={x["month"]:x for x in p.get("monthly_files",[])}
            prior_time=pd.Timestamp(p["created_utc"]).timestamp()
    for month in months("2023-09","2026-04"):
        if "2023-11"<=month<="2025-10":
            paths=[core/f"month={month}"/"analysis_panel.parquet"]
            kind="certified_stage07"
        else:
            kind="sf100k_extension"
            base=project/"derived/replication_36m"
            root=(base/"stockfish100k_historical_reuse" if month in ("2023-10","2025-11","2025-12","2026-02")
                  else base/"stockfish100k_extension_new_api_2026_04" if month=="2026-04"
                  else base/"stockfish100k_extension_new_api")
            paths=sorted((root/f"month={month}").glob("part_*.parquet"))
        available=bool(paths) and all(p.is_file() for p in paths)
        item={"month":month,"kind":kind,"paths":[str(p) for p in paths],"available":available}
        if kind=="certified_stage07":
            auth=certified[month];item["expected_sha256"]=auth["output_sha256"];item["expected_rows"]=int(auth["rows"])
            old=prior.get(month,{})
            if available and old.get("sha256")==auth["output_sha256"] and int(old.get("bytes",-1))==paths[0].stat().st_size and int(old.get("rows",-1))==pq.ParquetFile(paths[0]).metadata.num_rows and paths[0].stat().st_mtime<=prior_time+1:
                item["reused_physical_authentication"]=str(prior_path)
        result.append(item)
    return result

def choose(cols,names,required=False,alias="s"):
    for n in names:
        if n in cols: return f"{alias}.{ident(n)}"
    if required: raise RuntimeError(f"Missing required source column; expected one of {names}")
    return "NULL"

def normalize_month(task):
    project,work,item,memory_mb=task
    project=Path(project); work=Path(work); month=item["month"]
    files=[Path(p) for p in item["paths"]]
    dest=work/"base"/f"month={month}"/"opportunities.parquet"
    receipt=dest.with_suffix(".json")
    source_stamps=[stamp(p) for p in files]
    cols=schema(files[0])
    ts_source=resolve_timestamp_source(project,month,cols)
    write_json(work/"timestamp_resolution"/(month+".json"),ts_source)
    if ts_source["kind"]=="unresolved":raise RuntimeError(f"{month}: no complete keyed timestamp source; probes saved in timestamp_resolution/{month}.json")
    has_aux=ts_source["kind"]!="panel"
    source_stamps += [stamp(x["path"]) for x in ts_source["files"]]
    contract={"version":DATA_CONTRACT_VERSION,"month":month,"sources":source_stamps,"expected_sha256":item.get("expected_sha256")}
    if ts_source["kind"] in ("registered_historical_source","existing_replay_timestamps"):
        contract["timestamp_recipe"]={"kind":ts_source["kind"],"sha256":[x.get("expected_sha256") for x in ts_source["files"]]}
    key=digest(contract)
    if receipt.exists() and dest.exists():
        old=read_json(receipt)
        if old.get("key")==key and old["output"]["sha256"]==sha(dest):
            log(f"{month}: verified existing normalization reused")
            return old
        raise RuntimeError(f"Existing normalized month has changed inputs: {month}; retain it for review.")
    authentication=[]
    for p in files:
        reused=item.get("reused_physical_authentication")
        rec={**stamp(p),"sha256":item["expected_sha256"] if reused else sha(p),"physical_authentication":reused or "fresh_sha256"}
        if item["kind"]=="certified_stage07" and rec["sha256"]!=item["expected_sha256"]:
            raise RuntimeError(f"Certified monthly panel checksum differs: {p}")
        if item["kind"]=="sf100k_extension":
            done=p.with_suffix(".done.json")
            if not done.exists(): raise RuntimeError(f"Missing engine completion receipt: {done}")
            d=read_json(done)
            if int(d.get("error_rows",-1))!=0 or int(d.get("rows",-1))!=pq.ParquetFile(p).metadata.num_rows:
                raise RuntimeError(f"Engine part is incomplete: {p}")
            if d.get("part_sha256")!=rec["sha256"]: raise RuntimeError(f"Engine part checksum differs: {p}")
            rec["completion_receipt_sha256"]=sha(done)
        authentication.append(rec)
    timestamp_auth=authenticate_sources(ts_source,work) if has_aux else []
    c=connection(work/"tmp"/f"normalize_{month}",memory_mb=memory_mb)
    try:
        source=scan(files); join=""
        source_count=c.execute(f"SELECT count(*), count(DISTINCT game_id) FROM {source}").fetchone()
        if item.get("expected_rows") is not None and source_count[0]!=item["expected_rows"]:raise RuntimeError(f"Certified month row count differs: {month}")
        if source_count[0]!=source_count[1]: raise RuntimeError(f"Duplicate opportunity IDs: {month}")
        timestamp_join=None
        if has_aux:
            timestamp_join=make_timestamp_table(c,ts_source,source)
            join=" LEFT JOIN aux a USING(game_id)"
            ts="a.resolved_utc_ms"
        else:ts=timestamp_expression(cols)
        fields={
          "game_id":choose(cols,["game_id"],True),"utc_ms":ts,
          "chooser":f"lower(trim(CAST({choose(cols,['chooser_username_norm','chooser_username','candidate_chooser'],True)} AS VARCHAR)))",
          "opponent":f"lower(trim(CAST({choose(cols,['disconnected_username_norm','disconnected_username','likely_disconnected_player'],True)} AS VARCHAR)))",
          "color":choose(cols,["chooser_color","candidate_chooser_color_norm","candidate_chooser_color"],True),
          "speed":choose(cols,["api_speed"],True),
          "rating":choose(cols,["chooser_elo","candidate_chooser_elo"],True),
          "opp_rating":choose(cols,["disconnected_elo","likely_disconnected_elo"],True),
          "grant":choose(cols,["outcome_kind_draw"],True),
          "cp":choose(cols,["engine_eval_cp_disconnected","sf100k_eval_cp_disconnected"],True),
          "rd":choose(cols,["chooser_pre_rd_v2"]),"opp_rd":choose(cols,["disconnected_pre_rd_v2"]),
          "stored_draw":choose(cols,["chooser_draw_payoff_v2"]),
          "stored_premium":choose(cols,["chooser_win_premium_v2"]),
          "chooser_clock":choose(cols,["chooser_clock_last_obs_s"]),
          "opp_clock":choose(cols,["disconnected_clock_last_obs_s"]),
          "ply":choose(cols,["ply_count"]),"fen":choose(cols,["fen_after_last_move"]),
          "both_null":choose(cols,["both_ratingdiff_null"]),
          "prior_games": "NULL", "gap_days":"NULL",
          "chooser_user_id":choose(cols,["chooser_user_id"]),
        }
        strings={"game_id","chooser","opponent","color","speed","fen"}
        ints={"utc_ms","prior_games","ply","chooser_user_id"}
        expr=[]
        for name,value in fields.items():
            typ="VARCHAR" if name in strings else "BIGINT" if name in ints else "BOOLEAN" if name=="both_null" else "DOUBLE"
            expr.append(f"CAST({value} AS {typ}) AS {ident(name)}")
        expr += [f"{q(month)} AS month",f"{q(item['kind'])} AS source_kind"]
        copy_query(c,"SELECT "+",".join(expr)+f" FROM {source} s"+join,dest)
        counts=c.execute(f"SELECT count(*), count(DISTINCT game_id), count(*) FILTER(WHERE utc_ms IS NULL OR chooser IS NULL OR chooser='' OR opponent IS NULL OR speed NOT IN ('ultrabullet','bullet','blitz','rapid','classical') OR color NOT IN ('white','black') OR grant NOT IN (0,1) OR cp IS NULL OR rating IS NULL OR opp_rating IS NULL) FROM {scan(dest)}").fetchone()
        if counts[0]!=source_count[0] or counts[0]!=counts[1] or counts[2]: raise RuntimeError(f"{month}: normalized rows/uniqueness/required fields failed: {counts}")
        # No self-player records may enter a behavioral panel.
        self_n=c.execute(f"SELECT count(*) FROM {scan(dest)} WHERE chooser=opponent").fetchone()[0]
        rec={"key":key,"month":month,"source_kind":item["kind"],"authentication":authentication,
             "timestamp_source":ts_source,"timestamp_authentication":timestamp_auth,"timestamp_join":timestamp_join,
             "self_player_rows_excluded_downstream":self_n,
             "output":parquet_receipt(dest)}
        write_json(receipt,rec); log(f"Normalized {month}: {counts[0]:,} opportunities")
        return rec
    finally: c.close()

def normalize_all(project,work,workers,memory_mb):
    items=catalog(project)
    write_json(Path(work)/"source_catalog.json",items)
    absent=[x["month"] for x in items if not x["available"]]
    if absent: raise RuntimeError(f"Missing expected completed month(s): {absent}; source catalog saved")
    out=[];failures=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(normalize_month,(str(project),str(work),x,memory_mb)):x["month"] for x in items}
        for f in as_completed(futures):
            try:out.append(f.result())
            except Exception as exc:
                failures.append({"month":futures[f],"error":str(exc),"traceback":traceback.format_exc()})
                log(f"Normalization stopped for {futures[f]}: {exc}")
            write_json(Path(work)/"normalization_status.json",{"completed_months":[x["month"] for x in out],"failures":failures,"total_expected":len(items)})
    if failures:raise RuntimeError("Normalization needs repair in month(s): "+", ".join(x["month"] for x in failures)+"; all failures and completed partitions are recorded in normalization_status.json")
    return sorted(out,key=lambda x:x["month"])
