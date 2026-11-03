"""Shared I/O. Expected runtime: individual metadata operations seconds."""
from __future__ import annotations
import hashlib, importlib.util, json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone
import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PACKAGE = Path(__file__).resolve().parents[1]
VERSION = "1.0.2"
# Adapter/authentication repairs preserve scientific settings and completed data.
DATA_CONTRACT_VERSION = "1.0.0"
STAGE06_SHA = "e1a72414b4c4a18dca5b583b704cbbf97e0bff7de2a837e6ad85e078ecf00cca"
REFERENCE_SHA = "19ad528abb0f9d68bb0d5dcf39d1be529471cad149b064c0f63108a8a330cc1f"
SCALE = 173.7178
ADVANTAGE = 11.782457
CUTOFF = "2025-11-18T07:22:00Z"
CUTOFF_MS = int(pd.Timestamp(CUTOFF).timestamp()*1000)
BRACKET_START_MS = int(pd.Timestamp("2025-11-18T07:15:00Z").timestamp()*1000)
ANNOUNCEMENT_MS = int(pd.Timestamp("2025-12-22T22:35:00Z").timestamp()*1000)
SPEEDS = ("ultrabullet", "bullet", "blitz", "rapid", "classical")
POST_MONTHS = ("2025-11", "2025-12", "2026-01")

def log(s):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] {s}", flush=True)

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
    return h.hexdigest()

def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,default=str).encode()).hexdigest()

def read_json(p): return json.loads(Path(p).read_text())

def write_json(p,obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str,allow_nan=False)+"\n")
    os.replace(tmp,p)

def stamp(path):
    p=Path(path); st=p.stat()
    return {"path":str(p.resolve()),"size":st.st_size,"mtime_ns":st.st_mtime_ns}

def schema(path): return set(pq.ParquetFile(path).schema_arrow.names)
def q(x): return "'"+str(x).replace("'","''")+"'"
def ident(x): return '"'+x.replace('"','""')+'"'
def scan(paths):
    if isinstance(paths,(str,Path)): paths=[paths]
    if not paths: raise ValueError("Empty Parquet source")
    return "read_parquet(["+",".join(q(x) for x in paths)+"],hive_partitioning=false,union_by_name=true)"

def connection(temp,threads=1,memory_mb=1024):
    Path(temp).mkdir(parents=True,exist_ok=True)
    c=duckdb.connect()
    c.execute(f"SET threads={int(threads)}")
    c.execute(f"SET memory_limit='{int(memory_mb)}MB'")
    c.execute(f"SET temp_directory={q(temp)}")
    c.execute("SET preserve_insertion_order=false")
    return c

def copy_query(c,sql,path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f".tmp-{os.getpid()}")
    temp.unlink(missing_ok=True)
    c.execute(f"COPY ({sql}) TO {q(temp)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)")
    os.replace(temp,path)

def write_frame(df,path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f".tmp-{os.getpid()}")
    pq.write_table(pa.Table.from_pandas(df,preserve_index=False),tmp,compression="zstd",row_group_size=100000)
    os.replace(tmp,path)

def parquet_receipt(path):
    return {**stamp(path),"sha256":sha(path),"rows":pq.ParquetFile(path).metadata.num_rows}

def months(start,end):
    return [x.strftime("%Y-%m") for x in pd.period_range(start,end,freq="M")]

def load_stage06(path,expected=STAGE06_SHA):
    path=Path(path)
    if sha(path)!=expected: raise RuntimeError(f"Stage06 source hash mismatch: {path}. No replay started.")
    name="audited_stage06"
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

def rd_bins(x): return np.searchsorted([45.01,60,100,200],x,side="right").astype(np.int8)
def gap_bins(x): return np.searchsorted([-200,-50,-30,-ADVANTAGE,0,ADVANTAGE,30,50,200],x,side="right").astype(np.int8)

def payoffs(r,opp,rd,opp_rd,color,advantage):
    """Vectorized certified novol/noreg payoff at fixed pregame hidden state.
    Does not infer fractional production ratings from displayed integers.
    """
    r,opp,rd,opp_rd,color=np.broadcast_arrays(*[np.asarray(x,dtype=float) for x in (r,opp,rd,opp_rd,color)])
    if np.any(~np.isfinite(r+opp+rd+opp_rd+color)) or np.any((rd<=0)|(opp_rd<=0)|(~np.isin(color,[-1,1]))):
        raise ValueError("Invalid rating state/color in payoff computation")
    attenuation=1/np.sqrt(1+3*(np.maximum(opp_rd,45)/SCALE)**2/np.pi**2)
    x=attenuation*(r-opp+color*advantage)/SCALE
    E=1/(1+np.exp(np.clip(-x,-700,700)))
    E=np.clip(E,1e-12,1-1e-12)
    K=SCALE*attenuation/(1/(np.maximum(rd,45)/SCALE)**2+attenuation**2*E*(1-E))
    return E,K,K*(.5-E),K*(1-E)

def phase(ts):
    return np.where(ts<BRACKET_START_MS,"pre",np.where(ts<CUTOFF_MS,"transition_bracket","post"))
