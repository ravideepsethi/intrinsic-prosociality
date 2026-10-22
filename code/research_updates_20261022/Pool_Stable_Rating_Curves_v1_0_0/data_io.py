#!/usr/bin/env python3
"""Pool competitive positions with chooser-by-board-state fixed effects."""
from __future__ import annotations
import os
for v in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[v]='1'
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import shutil
import time
import zipfile
import numpy as np
import scipy
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from source import pool_wave1_common as common
from fe_engine import iter_blocks
from pooled_engine import VERSION,STATES,PooledMoments,fit_models,score_block,finish
from pooled_utils import (log,qs,require,signature,records,write_csv,manifest,
                          verify_manifest,checkpoint_ok,certify_checkpoint)
from stage_base import prepare_data

ROOT=Path(__file__).resolve().parent
EXPECTED=dict(rows=41534331,kind_draws=570091,fair_rows=15207423,fair_kind_draws=419463,choosers=3224173)
SAMPLE_RELATIVE='derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
STATUS='POOL_POOLED_COMPETITIVE_K_OK'

def validate_retained_counts(counts):
    previous=common.load_json(ROOT/'evidence/PREVIOUS_COMPETITIVE_COUNTS.json')
    for key,value in previous['expected_totals'].items():
        require(counts[key]==value,'Retained sample differs from prior state counts: '+key)
    for state,r in previous['state_receipts'].items():
        for key,oldkey in [('state_source_rows','all_N'),('state_source_grants','all_events'),
          ('state_estimation_rows','N'),('state_estimation_grants','events'),('state_absorbed_units','G')]:
            require(counts[key][state]==r[oldkey],'State count mismatch: '+state+': '+key)

def old_cache(project,auth):
    root=project/'output/pool_within_chooser_k_comparison_v100'
    if not root.is_dir():return None
    for run in sorted(root.iterdir()):
        report=run/'report';base=run/'PRIVATE/sorted_base.parquet'
        required=[report/'_SUCCESS.json',report/'SAMPLE_LINEAGE.json',report/'RUN_IDENTITY.json',
          report/'PREPARATION.json',base,base.with_suffix('.parquet.json')]
        if not all(p.is_file() for p in required):continue
        lineage=common.load_json(report/'SAMPLE_LINEAGE.json')
        if lineage.get('fingerprint')!=auth['fingerprint']:continue
        verify_manifest(report)
        success=common.load_json(report/'_SUCCESS.json');identity=success.get('identity')
        require(success.get('status')=='POOL_WITHIN_CHOOSER_K_COMPARISON_OK','Unexpected cache source status')
        require(common.load_json(report/'RUN_IDENTITY.json')['identity']==identity,'Old cache identity mismatch')
        require(checkpoint_ok(base,identity),'Old base checkpoint missing')
        prep=common.load_json(report/'PREPARATION.json')
        require(prep['run_identity']==identity,'Old preparation identity mismatch')
        for key,value in EXPECTED.items():require(prep['counts'][key]==value,'Old cache count mismatch: '+key)
        require(prep['counts']['invalid_rows']==0,'Invalid source rows in old cache')
        log('REUSING authenticated sorted cache from '+run.name)
        receipt=common.load_json(base.with_suffix('.parquet.json'))
        return base,prep,dict(kind='prior_within_chooser_K_sorted_base',
          prior_identity=identity,sha256=receipt['sha256'],path=str(base),source_fingerprint=auth['fingerprint'])
    return None

def stage_competitive(base,private,identity,workers,expected_fair_rows):
    paths=[private/f'competitive_shard_{i:02d}.parquet' for i in range(workers)]
    done=[checkpoint_ok(p,identity) for p in paths]
    if all(done):
        count=sum(common.load_json(p.with_suffix('.parquet.json'))['rows'] for p in paths)
        require(count==expected_fair_rows,'Staged competitive count differs')
        return paths
    writers={};n=[0]*workers;blocks=0
    try:
        for batch in pq.ParquetFile(base).iter_batches(batch_size=131072,use_threads=False):
            table=pa.Table.from_batches([batch]);board=table['board'].to_numpy()
            comp=table.filter(pa.array(board>=-100));ids=comp['chooser'].to_numpy()
            for j,p in enumerate(paths):
                if done[j]:continue
                if j not in writers:writers[j]=pq.ParquetWriter(p.with_suffix('.partial.parquet'),table.schema,compression='zstd')
                sub=comp.filter(pa.array(ids%workers==j))
                if len(sub):writers[j].write_table(sub);n[j]+=len(sub)
            blocks+=1
            if blocks%60==0:log(f'COMPETITIVE_STAGING source_rows_read≈{blocks*131072:,}')
    finally:
        for w in writers.values():w.close()
    for j,p in enumerate(paths):
        if done[j]:n[j]=common.load_json(p.with_suffix('.parquet.json'))['rows']
        else:
            os.replace(p.with_suffix('.partial.parquet'),p)
            certify_checkpoint(p,identity,rows=n[j],partition_rule=f'chooser_id modulo {workers} = {j}')
    require(sum(n)==expected_fair_rows,'Competitive staging does not conserve source rows')
    return paths
