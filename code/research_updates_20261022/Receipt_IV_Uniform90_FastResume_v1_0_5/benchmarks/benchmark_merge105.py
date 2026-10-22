#!/usr/bin/env python3
"""Synthetic, exact-output timing comparison. Never reads the research project.

Run manually with --rows 64000 --parts 16. Not part of launch-time self-tests.
Both runs begin with query partitions, scan partitions and first-pair features
already sealed; classification is unfinished. Temporary fixtures self-delete.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import fast_bootstrap as b
import fast_chronology_merge as new
import merge_v104_reference as old
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb


def data(root,n,parts):
    root.mkdir();index=np.arange(n,dtype=np.int64);row=index+2**45
    recipient=2*index+1;opponent=recipient+1
    q=root/'queries.parquet'
    pq.write_table(pa.table(dict(row_id=row,game_id=[f'q{i:09}' for i in index],recipient_id=recipient,
        opponent_id=opponent,archive_start_ms=np.full(n,100000,np.int64),previous_frame=np.zeros(n,bool))),q)
    sources=[]
    for k in range(parts):
        part=root/f'part{k:02}';part.mkdir();sources.append(part)
        role=np.tile(np.array([0,1],np.int32),n)
        prev_gid=[f'previous{i:08}_{r if not (k==0 and i%8==1) else 2}' for i in index for r in (0,1)]
        volume=np.where(role==0,k+1,0).astype(np.int64)
        pq.write_table(pa.table(dict(sample_row=np.repeat(row,2),role=role,
            prev_t=np.full(2*n,99990-k,np.int64),prev_count=np.ones(2*n,np.int64),prev_gid=prev_gid,
            prev_opponent=np.repeat(opponent+1000000,2),focal_time_count=np.full(2*n,int(k==0),np.int64),
            focal_matches=np.full(2*n,int(k==0),np.int64),pre_games_30d=volume)),part/'candidates.parquet',compression='zstd')
        pq.write_table(pa.table(dict(pair_key=recipient.astype(np.uint64)*np.uint64(4294967296)+opponent.astype(np.uint64),
            first_t=np.full(n,100000,np.int64))),part/'pairs.parquet',compression='zstd')
    return q,sources


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--rows',type=int,default=64000)
    ap.add_argument('--parts',type=int,default=16);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();os.environ['UNIFORM90_WORKERS']='12';os.environ['UNIFORM90_MEMORY_GIB']='13.5'
    original_hash=old.io.sha
    if hasattr(original_hash,'hash_file'):original_hash=original_hash.hash_file
    with tempfile.TemporaryDirectory(prefix='uniform90_merge105_benchmark_') as td:
        root=Path(td);q,parts=data(root/'data',a.rows,a.parts)
        settings=dict(memory=4.,buckets=8,max_queries=max(1,a.rows//64),max_candidates=max(1,a.rows*a.parts//32))
        def initialize(target):
            stage=old.stage
            def stop(path,*args,**kw):
                if Path(path).parent.name=='classified':raise RuntimeError('benchmark setup complete')
                return stage(path,*args,**kw)
            try:
                with patch.object(old,'stage',stop):old.bounded_merge(q,parts,target,'benchmark',**settings)
            except RuntimeError as error:
                if str(error)!='benchmark setup complete':raise
        with contextlib.redirect_stdout(io.StringIO()):
            initialize(root/'old');initialize(root/'new')
        timing={};outputs={};stats={}
        for name,module in [('v104',old),('v105',new)]:
            old.io.sha=original_hash
            began=time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()):
                outputs[name],stats[name]=module.bounded_merge(q,parts,root/('old' if name=='v104' else 'new'),'benchmark',**settings)
            timing[name]=time.monotonic()-began
        left=pq.read_table(outputs['v104']/'features.parquet').to_pydict()
        right=pq.read_table(outputs['v105']/'features.parquet').to_pydict()
        if left!=right:raise AssertionError('Synthetic benchmark results differ')
        if len(right['row_id'])!=a.rows:raise AssertionError('Row coverage changed')
        result=dict(purpose='Synthetic restart/classification benchmark; not a private-data ETA',
            query_rows=a.rows,candidate_summary_rows=2*a.rows*a.parts,source_parts=a.parts,
            seconds=timing,speedup=timing['v104']/timing['v105'],exact_all_fields_equal=True,
            old_leaf_groups=stats['v104']['leaf_groups'],new_leaf_groups=stats['v105']['leaf_groups'],
            resources=stats['v105']['parallel_execution'],
            runtime=dict(python=platform.python_version(),duckdb=duckdb.__version__,pyarrow=pa.__version__,numpy=np.__version__,platform=platform.system()),
            limitations='Synthetic data, Linux runtime and warm filesystem cache; real Mac/SSD/runtime speedup may differ. Timings include existing-partition verification.')
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))


if __name__=='__main__':main()
