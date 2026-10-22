"""Authenticate existing checkpoint DATA hashes and replay prerequisites.
Expected runtime: 10-120 seconds on an SSD; up to ten parallel I/O workers.
No history or account identities are reconstructed by this preflight.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
import traceback
from common import *

AUTHORITY_PATH=PACKAGE/"vendor/checkpoint_authority.json"
POLICY={"formula_version":"anchored_timeaware_glicko2_novol_noreg_defaultRD500_skip_both_null_v1",
    "both_null_policy":"skip","default_rd":500.,"default_sigma":.09,"min_rd":45.,"max_rd":500.,
    "max_sigma":.1,"tau":.75,"periods_per_day":.21436,"color_adv_start_utc":CUTOFF,"standard_color_adv":ADVANTAGE}
STATE_COLUMNS={"user_id","rd","sigma","games_seen","last_seen_ms"}

def checkpoint_path(project,speed,month):
    return Path(project)/"derived/replication/glicko2_cost_layer/checkpoints"/f"speed={speed}"/f"state_after_{month}.parquet"

def authenticate_checkpoint(project,work,speed,month):
    """The foundation inventory copied metadata['sha256'], the Parquet digest.
    Metadata is checked for policy/identity, then data is checked against both
    the independently recorded authority and the metadata's declared digest.
    """
    cp=checkpoint_path(project,speed,month);meta=cp.with_suffix(".json")
    receipt=Path(work)/"checkpoint_authentication"/f"{speed}_{month}.json"
    old=read_json(receipt) if receipt.is_file() else {}
    rec={"speed":speed,"month":month,"data_path":str(cp),"metadata_path":str(meta),"status":"CHECKING"}
    try:
        authority=read_json(AUTHORITY_PATH)["checkpoints"][month][speed]
        expected=authority["checkpoint_parquet_sha256"]
        rec["expected_data_sha256"]=expected
        rec["authority_file_sha256"]=sha(AUTHORITY_PATH)
        if not cp.is_file() or not meta.is_file():raise RuntimeError("Checkpoint data or metadata is missing")
        m=read_json(meta);rec["metadata"]=m
        rec["metadata_file_sha256"]=sha(meta)
        rec["data_fingerprint"]=stamp(cp)
        mismatches={key:{"expected":value,"observed":m.get(key)} for key,value in
            {**POLICY,"speed":speed,"month":month}.items() if m.get(key)!=value}
        if mismatches:
            rec["policy_mismatches"]=mismatches
            raise RuntimeError("Checkpoint policy or identity mismatch: "+", ".join(mismatches))
        if m.get("sha256")!=expected:
            raise RuntimeError("Metadata's checkpoint data hash differs from the recorded authority")
        pf=pq.ParquetFile(cp)
        rec["rows"]=pf.metadata.num_rows;rec["columns"]=pf.schema_arrow.names
        if not STATE_COLUMNS<=set(rec["columns"]):raise RuntimeError("Missing checkpoint state columns")
        if m.get("rows")!=rec["rows"] or m.get("size_bytes")!=cp.stat().st_size:
            raise RuntimeError("Checkpoint row count or byte size differs from its metadata")
        # Preflight and the later speed worker share this receipt, avoiding a
        # second full-file read when the physical source is unchanged.
        reusable=(old.get("status")=="CHECKPOINT_AUTHENTICATED" and
            old.get("data_fingerprint")==rec["data_fingerprint"] and
            old.get("metadata_file_sha256")==rec["metadata_file_sha256"] and
            old.get("data_sha256")==expected)
        actual=old["data_sha256"] if reusable else sha(cp)
        rec["data_sha256"]=actual;rec["verification"]="verified receipt reused" if reusable else "fresh data SHA-256"
        if actual!=expected:raise RuntimeError("Checkpoint Parquet data checksum differs from the recorded authority")
        rec["status"]="CHECKPOINT_AUTHENTICATED"
        return rec
    except Exception as exc:
        rec["status"]="CHECKPOINT_AUTHENTICATION_FAILED";rec["error"]=str(exc)
        raise RuntimeError(f"{speed}/{month}: {exc}") from exc
    finally:write_json(receipt,rec)

def inspect_event(project,speed,month,required_columns):
    p=Path(project)/"derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time"/f"speed={speed}"/f"month={month}"/"part-00000.parquet"
    if not p.is_file():raise RuntimeError(f"Missing replay substrate: {p}")
    pf=pq.ParquetFile(p);missing=set(required_columns)-set(pf.schema_arrow.names)
    if missing:raise RuntimeError(f"{p}: missing replay columns {sorted(missing)}")
    if not pf.metadata.num_rows:raise RuntimeError(f"Empty replay substrate: {p}")
    return {"speed":speed,"month":month,**stamp(p),"rows":pf.metadata.num_rows,"check":"metadata and schema; data SHA recorded by replay worker"}

def preflight_all(project,work,workers,required_columns):
    out={"status":"CHECKING","checkpoints":[],"events":[],"failures":[]}
    try:
        dictionary=Path(project)/"derived/glicko2_replay/user_dictionary_v1/summary.json"
        d=read_json(dictionary)
        if int(d["total_global_users"])<=0:raise RuntimeError("Dictionary has no global users")
        out["dictionary"]={**stamp(dictionary),"sha256":sha(dictionary),"total_global_users":d["total_global_users"]}
    except Exception as exc:
        out["failures"].append({"input":"dictionary summary","error":str(exc)})
    with ThreadPoolExecutor(max_workers=min(10,max(1,workers))) as pool:
        tasks={pool.submit(authenticate_checkpoint,project,work,speed,month):("checkpoints",speed,month)
            for month in ("2023-10","2025-10") for speed in SPEEDS}
        tasks.update({pool.submit(inspect_event,project,speed,month,required_columns):("events",speed,month)
            for month in POST_MONTHS for speed in SPEEDS})
        for future in as_completed(tasks):
            kind,speed,month=tasks[future]
            try:out[kind].append(future.result())
            except Exception as exc:
                out["failures"].append({"input":kind,"speed":speed,"month":month,"error":str(exc),"traceback":traceback.format_exc()})
    for key in ("checkpoints","events"):out[key].sort(key=lambda x:(x["speed"],x["month"]))
    out["status"]="REPLAY_PREFLIGHT_FAILED" if out["failures"] else "REPLAY_PREFLIGHT_OK"
    write_json(Path(work)/"replay_preflight.json",out)
    if out["failures"]:raise RuntimeError(f"Replay preflight found {len(out['failures'])} problem(s); details saved in replay_preflight.json")
    log("REPLAY_PREFLIGHT_OK: ten checkpoint data hashes verified; fifteen event schemas checked.")
    return out
