"""Local-only, frozen-cohort competitive instrument analysis."""
from __future__ import annotations
import os
for _k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_k]='1'
import sys,math,json,csv,time,hashlib,zipfile,contextlib,concurrent.futures as cf,multiprocessing as mp
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/legacy'))
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import local_io as io
import iv_numerics as num
import expanded_stats as oldstats
import expanded_logic as logic
import followup_stats as fs
import comparison_core as cmp
from preliminary_core import DAY,MONTHS,STARTS,SPEEDS

VERSION='1.0.0'
EXPANDED_REL='derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7'
EXPANDED_CONF='f14a1105a9f70782dffad6ecd98b651f5e6d57f1ce4d39ee0f0248e9e1d3bc0f'
SPACED_SHA='3bc55d83f113cd7c5942348b16ae9ff5e940ae8aad13f9db3d99a6a526ef250c'
OUT_REL='derived/replication/iv_competitive_only_v100_PRIVATE'
SCORE_COLS=['n_7d','adjusted_7d','expected_7d','counterparts_7d']
COUNTS=[f'{c}_{d}' for d in (90,30) for c in ('fair','kind','disconnect','receipt','claim')]
MODEL_COLS=['row_id','recipient_id','opponent_id','archive_start_ms','month_code','tc_base_s','tc_inc_s',
            'recipient_rating','opponent_rating','pre_games_30d','y','reached']+SCORE_COLS+COUNTS
SPLIT_COLS=[f'{tag}_{c}' for tag in ('comp','non') for c in ('n','grants','expected','counterparts','z')]+['non_clearly_worse_n']
ZCOLS={'pooled':'adjusted_7d','comp':'comp_z','non':'non_z'}
RECENT=['fair_history_present_30','log_fair_30','kind_ever_30','kind_rate_30','log_disconnect_30','log_receipt_30','log_claim_30']

def arrays(t):return {k:io.arr(t,k) for k in t.column_names}
def subset(d,m):return {k:v[m] for k,v in d.items()}
def threads_one():pa.set_cpu_count(1);pa.set_io_thread_count(1)
def no_network():
    import socket
    def blocked(*a,**k):raise RuntimeError('Network access disabled in this analysis')
    socket.create_connection=blocked;socket.socket.connect=blocked
def relocate(project,path):
    p=Path(path)
    if p.is_absolute():p=p.relative_to('/Volumes/XT_Pro/lichess_kindness')
    return io.child(project,p)
def memory_default():
    try:g=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/1024**3
    except (ValueError,OSError):
        import subprocess
        g=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True))/1024**3
    return max(4,min(48,int(g*.65)))
def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,n=line.split('  ',1);io.checked(io.child(ROOT,n),h)
    return io.sha(ROOT/'PACKAGE_MANIFEST.sha256')
def csvout(path,rows):
    rows=io.clean(rows);names=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names);w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in r.items()})
def tables(root,name,rows):
    io.js(root/(name+'.json'),rows);csvout(root/(name+'.csv'),rows)
    flat=[{k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in io.clean(rows)]
    if flat:
        # Arrow otherwise infers field names from the first row only.
        names=list(dict.fromkeys(k for r in flat for k in r))
        io.table(root/(name+'.parquet'),pa.Table.from_pylist([{k:r.get(k) for k in names} for r in flat]))
def stable(root,conf,producer,inputs=()):
    before=[io.sig(p) for p in inputs];result=io.stage(root,conf,producer)
    if before!=[io.sig(p) for p in inputs]:raise RuntimeError('Immutable input changed during stage')
    return result
def measured(job):
    # Importable entry point for spawn; each worker has a single numerical thread.
    import importlib,resource
    threads_one();no_network();t=time.monotonic()
    result=getattr(importlib.import_module(job['module']),job['function'])(job)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**3 if sys.platform=='darwin' else 1024**2)
    return dict(result=result,seconds=time.monotonic()-t,peak_rss_gib=rss)
def mapped(jobs,workers,label,performance):
    if not jobs:return []
    t=time.monotonic();out=[]
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool,io.heartbeat(label):
        pending={pool.submit(measured,j):i for i,j in enumerate(jobs)}
        for f in cf.as_completed(pending):
            out.append((pending[f],f.result()));done=len(out);elapsed=time.monotonic()-t
            io.log(f'{label}: {done}/{len(jobs)}; stage ETA {elapsed/done*(len(jobs)-done)/60:.1f} min')
    out=[v for _,v in sorted(out)]
    performance.append(dict(stage=label,workers=workers,seconds=time.monotonic()-t,jobs=len(jobs),
        max_worker_peak_rss_gib=max(v['peak_rss_gib'] for v in out)))
    return [v['result'] for v in out]
