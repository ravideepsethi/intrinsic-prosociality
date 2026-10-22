"""Exact keyed timestamp reuse. Expected runtime 1-10 minutes over four months;
allow 5-20 minutes if fallback must scan all-rated-game Parquet timestamp columns.
No rating state, identity or engine evaluation is rebuilt in this module.
"""
from __future__ import annotations
import fcntl
from common import *

SOURCE_REGISTRY=PACKAGE/"vendor/historical_timestamp_sources.json"

def timestamp_expression(cols,alias="s",allow_api=True):
    if "utc_ms" in cols:
        return f"TRY_CAST({alias}.utc_ms AS BIGINT)"
    if {"utc_date","utc_time"}<=cols:
        return f"epoch_ms(try_strptime(replace(CAST({alias}.utc_date AS VARCHAR),'.','-') || ' ' || CAST({alias}.utc_time AS VARCHAR),'%Y-%m-%d %H:%M:%S'))"
    if allow_api and "api_created_at_ms" in cols:
        return f"TRY_CAST({alias}.api_created_at_ms AS BIGINT)"
    if "utc_ts" in cols:
        return f"epoch_ms(TRY_CAST({alias}.utc_ts AS TIMESTAMP))"
    return None

def resolve_timestamp_source(project,month,source_cols):
    project=Path(project); probes=[]
    if timestamp_expression(source_cols):
        return {"kind":"panel","files":[],"probes":probes}
    candidates=[project/"derived/replication_36m/timeout_opportunity_extension"/f"month={month}"/"timeout_opportunities.parquet",
                project/"derived/replication/pgn_timeforfeit_candidates"/f"month={month}"/"api_target_candidates_ge5s_or_missing.parquet"]
    for p in candidates:
        row={"path":str(p),"exists":p.is_file()}
        if p.is_file():
            cols=schema(p);row["timestamp_columns"]=sorted(cols&{"utc_ms","utc_ts","utc_date","utc_time","api_created_at_ms"})
            if "game_id" in cols and timestamp_expression(cols):
                probes.append(row)
                return {"kind":"modern_keyed_source","files":[{"path":str(p)}],"probes":probes}
        probes.append(row)
    registered=read_json(SOURCE_REGISTRY).get("months",{}).get(month,{})
    files=[]
    for item in registered.get("files",[]):
        p=project/item["relative_path"]
        row={"path":str(p),"exists":p.is_file(),"kind":"registered_historical_source"}
        if p.is_file():
            cols=schema(p);row["timestamp_columns"]=sorted(cols&{"utc_ms","utc_ts","utc_date","utc_time"})
            if "game_id" in cols and timestamp_expression(cols,allow_api=False):
                files.append({"path":str(p),"expected_sha256":item["sha256"],"expected_bytes":item["size_bytes"]})
        probes.append(row)
    if files and len(files)==len(registered.get("files",[])):
        return {"kind":"registered_historical_source","files":files,"probes":probes,
                "source_receipt_sha256":read_json(SOURCE_REGISTRY)["source_receipt_sha256"]}
    # The surviving replay substrate already carries exact PGN UTC milliseconds.
    # Project just IDs and timestamps, then semi-join to the requested games.
    root=project/"derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time"
    files=[]
    for speed in SPEEDS:
        p=root/f"speed={speed}"/f"month={month}"/"part-00000.parquet"
        row={"path":str(p),"exists":p.is_file(),"kind":"existing_replay_timestamps","speed":speed}
        if p.is_file() and {"game_id","utc_ms"}<=schema(p):files.append({"path":str(p)})
        probes.append(row)
    if len(files)==len(SPEEDS):
        return {"kind":"existing_replay_timestamps","files":files,"probes":probes}
    return {"kind":"unresolved","files":[],"probes":probes}

def authenticate_sources(spec,work):
    """Share hash receipts for November/December's identical upstream shards."""
    out=[]
    for item in spec["files"]:
        p=Path(item["path"]);fp=stamp(p)
        expected=item.get("expected_sha256")
        if expected is None:
            out.append({**fp,"authentication":"existing documented project source; metadata fingerprint"});continue
        if fp["size"]!=item["expected_bytes"]:raise RuntimeError(f"Historical timestamp-source size changed: {p}")
        root=Path(work)/"timestamp_source_auth";root.mkdir(parents=True,exist_ok=True)
        key=digest({"path":str(p.resolve())});receipt=root/(key+".json")
        with open(root/(key+".lock"),"a+") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                old=read_json(receipt) if receipt.exists() else {}
                if old.get("fingerprint")==fp and old.get("sha256")==expected:
                    out.append({**fp,"sha256":expected,"authentication":"registered SHA receipt reused"});continue
                actual=sha(p)
                if actual!=expected:raise RuntimeError(f"Historical timestamp-source SHA-256 mismatch: {p}")
                write_json(receipt,{"fingerprint":fp,"sha256":actual})
                out.append({**fp,"sha256":actual,"authentication":"registered SHA verified"})
            finally:fcntl.flock(lock,fcntl.LOCK_UN)
    return out

def make_timestamp_table(c,spec,source):
    terms=[]
    for item in spec["files"]:
        p=Path(item["path"]);cols=schema(p)
        expr=timestamp_expression(cols,allow_api=spec["kind"]=="modern_keyed_source")
        if expr is None:raise RuntimeError(f"No supported UTC timestamp fields: {p}")
        terms.append(f"SELECT CAST(s.game_id AS VARCHAR) AS game_id,{expr} AS resolved_utc_ms FROM {scan(p)} s")
    c.execute("CREATE TEMP VIEW timestamp_source_rows AS "+" UNION ALL ".join(terms))
    c.execute(f"CREATE TEMP TABLE aux AS SELECT t.* FROM timestamp_source_rows t SEMI JOIN (SELECT game_id FROM {source}) wanted USING(game_id)")
    n,unique,invalid=c.execute("SELECT count(*),count(DISTINCT game_id),count(*) FILTER(WHERE resolved_utc_ms IS NULL OR resolved_utc_ms<946684800000 OR resolved_utc_ms>4102444800000) FROM aux").fetchone()
    expected=c.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
    if n!=unique:raise RuntimeError(f"Duplicate timestamp-source IDs among target games: {n-unique}")
    if invalid:raise RuntimeError(f"Unparseable timestamp or wrong epoch units in {invalid} requested games")
    if n!=expected:raise RuntimeError(f"Timestamp source covers {n:,}/{expected:,} requested games")
    return {"matched_rows":int(n),"duplicate_rows":0,"invalid_timestamps":0}
