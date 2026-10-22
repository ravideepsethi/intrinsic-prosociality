#!/usr/bin/env python3
"""Authenticate, stage and estimate the within-chooser K comparison."""
from __future__ import annotations
import os
for _v in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_v]='1'
import argparse
import concurrent.futures
import csv
import fcntl
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import shutil
import sys
import time
import zipfile
import numpy as np
import scipy
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from source import pool_wave1_common as common
from fe_engine import (VERSION,CONTEXTS,MONTHS,SPEEDS,context_mask,iter_blocks,Moments,
                       fit_models,score_block,finalize_models)
from render_comparison import render

ROOT=Path(__file__).resolve().parent
EXPECTED=dict(rows=41534331,kind_draws=570091,fair_rows=15207423,fair_kind_draws=419463,choosers=3224173)
SAMPLE_RELATIVE='derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
STATUS='POOL_WITHIN_CHOOSER_K_COMPARISON_OK'


def log(s): print(f'[{common.utc_now()}] {s}',flush=True)
def qs(x):return "'"+str(x).replace("'","''")+"'"
def require(ok,s):
    if not ok:raise RuntimeError(s)
def signature(p):
    s=Path(p).stat();return [s.st_size,s.st_mtime_ns,s.st_ino]
def records(db,sql):
    cursor=db.execute(sql);names=[x[0] for x in cursor.description]
    return [dict(zip(names,r)) for r in cursor.fetchall()]
def write_csv(path,rows):
    require(bool(rows),'Refusing empty result CSV')
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def manifest(root,name='OUTPUT_MANIFEST.sha256'):
    lines=[f'{common.sha256_file(p)}  {p.relative_to(root).as_posix()}\n' for p in sorted(root.rglob('*'))
           if p.is_file() and p.name!=name and '__pycache__' not in p.parts]
    common.atomic_text(root/name,''.join(lines))
def verify_manifest(root,name):
    p=root/name;require(p.is_file(),f'Missing {name}')
    for line in p.read_text().splitlines():
        digest,rel=line.split('  ',1);q=root/rel
        require(q.resolve().is_relative_to(root.resolve()),'Unsafe manifest path')
        require(q.is_file() and common.sha256_file(q)==digest,f'Checksum mismatch: {rel}')
    return common.sha256_file(p)
def checkpoint_ok(path,identity):
    receipt=path.with_suffix(path.suffix+'.json')
    if not receipt.is_file():return False
    r=common.load_json(receipt)
    require(r['run_identity']==identity,f'Checkpoint identity mismatch: {path.name}')
    require(path.is_file() and common.sha256_file(path)==r['sha256'],f'Checkpoint corrupted: {path.name}')
    return True
def certify_checkpoint(path,identity,**extra):
    common.atomic_json(path.with_suffix(path.suffix+'.json'),dict(run_identity=identity,
        sha256=common.sha256_file(path),**extra))


def prepare_data(db,paths,private,identity,expected,context_keys):
    """One sorted slim copy; context Parquets retain complete account ordering."""
    private.mkdir(parents=True,exist_ok=True)
    base=private/'sorted_base.parquet';meta=private/'PREPARATION.json'
    if checkpoint_ok(base,identity):
        preparation=common.load_json(meta);log('REUSED authenticated sorted base')
    else:
        files='['+','.join(qs(p) for p in paths)+']'
        month_case='CASE month '+' '.join(f'WHEN {qs(m)} THEN {i}' for i,m in enumerate(MONTHS))+' ELSE -1 END'
        speed_case='CASE api_speed '+' '.join(f'WHEN {qs(m)} THEN {i}' for i,m in enumerate(SPEEDS))+' ELSE -1 END'
        db.execute(f'''CREATE OR REPLACE TEMP VIEW source AS SELECT
          chooser_user_id::BIGINT AS chooser, outcome_kind_draw::INTEGER AS y,
          (disconnected_elo::DOUBLE-chooser_elo::DOUBLE) AS gap,
          chooser_draw_payoff_v2::DOUBLE AS payoff, 2*chooser_win_premium_v2 AS K,
          chooser_win_payoff_v2-chooser_draw_payoff_v2-chooser_win_premium_v2 AS identity_error,
          engine_eval_cp_disconnected::DOUBLE AS board, ply_count::DOUBLE AS ply,
          chooser_pre_rd_v2 AS crd, disconnected_pre_rd_v2 AS drd,
          chooser_pre_sigma_v2 AS cvol, disconnected_pre_sigma_v2 AS dvol,
          ({month_case})::SMALLINT AS month, ({speed_case})::SMALLINT AS speed
          FROM read_parquet({files},hive_partitioning=false)''')
        numerics=['gap','payoff','K','board','ply','crd','drd','cvol','dvol','identity_error']
        invalid=' OR '.join([f'{x} IS NULL OR NOT isfinite({x})' for x in numerics]+
          ['chooser IS NULL','chooser<0','y IS NULL','y NOT IN(0,1)','month<0','speed<0',
           'K<=0','ply<0','crd<=0','drd<=0','cvol<=0','dvol<=0',
           'abs(identity_error)>1e-7*greatest(1.,K)',
           '(0.5-payoff/K)<-1e-7','(0.5-payoff/K)>1+1e-7'])
        counts=records(db,f'''SELECT count(*) AS "rows",sum(y)::BIGINT kind_draws,
          count(*) FILTER(WHERE board>=-100) fair_rows,
          sum(y) FILTER(WHERE board>=-100)::BIGINT fair_kind_draws,
          count(DISTINCT chooser) choosers, count(*) FILTER(WHERE {invalid}) invalid_rows,
          min(K) min_K,max(K) max_K,max(abs(identity_error)) max_identity_error FROM source''')[0]
        require(counts['invalid_rows']==0,f'Invalid required values; no silent row dropping: {counts}')
        for k,v in expected.items():require(counts[k]==v,f'Current-sample count mismatch: {k}: {counts[k]} vs {v}')
        quantiles={}
        for key,number in [('k20',20),('k50',50)]:
            probs='['+','.join(str(i/number) for i in range(1,number))+']'
            values=db.execute(f'SELECT quantile_cont(K,{probs}) FROM source').fetchone()[0]
            quantiles[key]=sorted(set(float(x) for x in values if x<counts['max_K']))
        log(f'SOURCE_OK rows={counts["rows"]:,}; sorting all rows by chooser (disk spill allowed)')
        temporary=base.with_suffix('.partial.parquet')
        temporary.unlink(missing_ok=True)
        db.execute('SET preserve_insertion_order=true')
        db.execute(f'''COPY (SELECT * EXCLUDE(identity_error) FROM source ORDER BY chooser,month,gap,payoff,y)
          TO {qs(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 65536)''')
        os.replace(temporary,base)
        preparation=dict(run_identity=identity,counts=counts,K_cutpoints=quantiles,
            quantile_scope='all frozen current-sample opportunities, before singleton exclusion',
            ties='duplicate cutpoints collapsed; equal K is never split by rank',
            K_definition='2 * chooser_win_premium_v2',
            gap_definition='disconnected_elo - chooser_elo; recomputed from displayed ratings',
            expected_score_check='0 <= 0.5 - chooser_draw_payoff_v2 / K <= 1')
        common.atomic_json(meta,preparation);certify_checkpoint(base,identity,rows=counts['rows'])
    todo=[key for key in context_keys if not checkpoint_ok(private/(key+'.parquet'),identity)]
    if todo:
        writers={};totals={key:0 for key in todo};blocks=0
        try:
            for batch in pq.ParquetFile(base).iter_batches(batch_size=131072,use_threads=False):
                table=pa.Table.from_batches([batch]);d=table['board'].to_numpy()
                for key in todo:
                    subset=table.filter(pa.array(context_mask(d,key)))
                    if key not in writers:
                        writers[key]=pq.ParquetWriter(private/(key+'.partial.parquet'),table.schema,compression='zstd')
                    if len(subset):writers[key].write_table(subset);totals[key]+=len(subset)
                blocks+=1
                if blocks%30==0:log(f'CONTEXT_STAGING rows_read≈{blocks*131072:,}')
        finally:
            for writer in writers.values():writer.close()
        for key in todo:
            p=private/(key+'.parquet');os.replace(private/(key+'.partial.parquet'),p)
            certify_checkpoint(p,identity,rows=totals[key]);log(f'CONTEXT_READY {key} rows={totals[key]:,}')
    # Support of the K approximation, including heaped floor and wide tail bins.
    bins=[]
    for key,edges in preparation['K_cutpoints'].items():
        expression='CASE '+' '.join(f'WHEN K<={repr(x)} THEN {i}' for i,x in enumerate(edges))+f' ELSE {len(edges)} END'
        rows=records(db,f'''SELECT {expression} AS bin,count(*) n,min(K) min_K,max(K) max_K,avg(K) mean_K
          FROM read_parquet({qs(base)}) GROUP BY bin ORDER BY bin''')
        bins.extend(dict(scheme=key,**r) for r in rows)
    preparation['K_bin_support']=bins
    return preparation


def estimate_context(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    private=Path(job['private']);context=job['context'];identity=job['identity']
    path=private/(context+'.parquet');out=Path(job['results'])/context
    out.mkdir(parents=True,exist_ok=True)
    success=out/'_SUCCESS.json'
    if success.is_file():
        require(common.load_json(success)['run_identity']==identity,'Result identity mismatch')
        verify_manifest(out,'OUTPUT_MANIFEST.sha256');log(f'REUSED_RESULT {context}');return str(out)
    before=signature(path);momentpath=private/(context+'_moments.npz')
    if checkpoint_ok(momentpath,identity):
        moments=Moments.load(momentpath);log(f'REUSED_MOMENTS {context} N={moments.N:,}')
    else:
        moments=Moments(job['edges']);blocks=0;start=time.monotonic()
        for frame in iter_blocks(path,job['batch_rows']):
            moments.add(frame);blocks+=1
            if blocks%40==0:log(f'MOMENTS {context} rows={moments.all_N:,} seconds={time.monotonic()-start:.0f}')
        temporary=momentpath.with_name(momentpath.stem+'.partial.npz')
        moments.save(temporary);os.replace(temporary,momentpath);certify_checkpoint(momentpath,identity)
    log(f'FIT {context}: all={moments.all_N:,}, usable={moments.N:,}, choosers={moments.G:,}')
    for counts in moments.counts.values():
        require(int(counts['all_n'].sum())==moments.all_N and
                int(counts['all_events'].sum())==moments.all_events and
                int(counts['n'].sum())==moments.N and
                int(counts['events'].sum())==moments.events and
                int(counts['month'].sum())==moments.N,'Context count conservation failed')
    models=fit_models(moments);blocks=0
    for frame in iter_blocks(path,job['batch_rows']):
        score_block(frame,job['edges'],models);blocks+=1
        if blocks%40==0:log(f'CLUSTER_SCORES {context} blocks={blocks}')
    require(before==signature(path),'Context input changed during estimation')
    rows,shapes,diagnostics,arrays=finalize_models(moments,models,context,**job['support'])
    write_csv(out/'curves.csv',rows);write_csv(out/'shape_contrasts.csv',shapes)
    common.atomic_json(out/'MODEL_DIAGNOSTICS.json',diagnostics)
    np.savez_compressed(out/'curve_covariances.npz',**arrays)
    # These contain only sums, cross-products and counts, never individual IDs.
    shutil.copyfile(momentpath,out/'within_chooser_moments.npz')
    common.atomic_json(success,dict(status='CONTEXT_ESTIMATED_OK',run_identity=identity,
                                   context=context,N=moments.N,G=moments.G,all_N=moments.all_N,
                                   all_events=moments.all_events,events=moments.events))
    manifest(out);log(f'CONTEXT_COMPLETE {context}');return str(out)


def read_csv(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f))


def add_holm(rows):
    selected=[r for r in rows if r['specification']=='chooser_controls_k20']
    # Missing/unestimable comparisons retain their place in the declared family.
    vals=np.array([float(r['p_two_sided']) if r.get('p_two_sided') not in (None,'') else 1. for r in selected])
    order=np.argsort(vals);adjusted=np.empty(len(vals));previous=0.
    for rank,index in enumerate(order):
        previous=max(previous,min(1.,(len(vals)-rank)*vals[index]));adjusted[index]=previous
    for i,r in enumerate(selected):
        r['holm_family_size']=len(vals)
        r['p_holm_exploratory_k20']=float(adjusted[i]) if r.get('p_two_sided') not in (None,'') else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--sample-root',type=Path)
    parser.add_argument('--output-root',type=Path)
    parser.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--workers',type=int,default=10)
    parser.add_argument('--hash-workers',type=int,default=2)
    parser.add_argument('--memory-limit',default='6GB')
    parser.add_argument('--batch-rows',type=int,default=32768)
    parser.add_argument('--min-n',type=int,default=500)
    parser.add_argument('--min-choosers',type=int,default=50)
    parser.add_argument('--min-months',type=int,default=6)
    args=parser.parse_args()
    require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be 1..10')
    require(1024<=args.batch_rows<=131072,'Use 1024..131072 batch rows')
    require(args.min_n>=1 and args.min_choosers>=2 and 1<=args.min_months<=24,'Invalid display support')
    start=time.monotonic();packagehash=verify_manifest(ROOT,'PACKAGE_MANIFEST.sha256')
    sample=args.sample_root or args.project_root/SAMPLE_RELATIVE
    auth=common.authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
    lineage=common.compact_sample_lineage(auth)
    for key,value in EXPECTED.items():require(auth['authority'][key]==value,f'Authority mismatch: {key}')
    versions=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
                  duckdb=duckdb.__version__,pyarrow=pa.__version__)
    settings=dict(batch_rows=args.batch_rows,support=dict(min_n=args.min_n,min_choosers=args.min_choosers,min_months=args.min_months),
                  contexts=[x[0] for x in CONTEXTS],workers=args.workers,memory_limit=args.memory_limit)
    identity=hashlib.sha256(common.canonical_json(dict(package=packagehash,sample=auth['fingerprint'],
                                                    versions=versions,settings=settings)).encode()).hexdigest()
    root=(args.output_root or args.project_root/'output/pool_within_chooser_k_comparison_v100')/identity[:16]
    private=root/'PRIVATE';report=root/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
    lock=open(root/'run.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    snapshots={str(r['path']):signature(r['path']) for r in auth['month_records']}
    db=duckdb.connect()
    db.execute(f'SET threads={args.workers}');db.execute(f'SET memory_limit={qs(args.memory_limit)}')
    temp=private/'duckdb_spill';temp.mkdir(exist_ok=True)
    db.execute(f'SET temp_directory={qs(temp)}');db.execute('SET preserve_insertion_order=true')
    prep=prepare_data(db,[r['path'] for r in auth['month_records']],private,identity,EXPECTED,settings['contexts'])
    db.close()
    common.atomic_json(report/'PREPARATION.json',prep);write_csv(report/'K_bin_support.csv',prep['K_bin_support'])
    jobs=[dict(private=str(private),context=c,identity=identity,results=str(report/'contexts'),
               edges=prep['K_cutpoints'],batch_rows=args.batch_rows,support=settings['support']) for c in settings['contexts']]
    log(f'ESTIMATING {len(jobs)} board contexts; up to {min(args.workers,len(jobs))} simultaneous workers')
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(args.workers,len(jobs)),
            mp_context=multiprocessing.get_context('spawn')) as pool:
        for result in pool.map(estimate_context,jobs):log(f'READY {Path(result).name}')
    partition=[common.load_json(report/'contexts'/c/'_SUCCESS.json') for c in settings['contexts'][:5]]
    require(sum(r['all_N'] for r in partition)==EXPECTED['rows'],'Five board contexts do not conserve source rows')
    require(sum(r['all_events'] for r in partition)==EXPECTED['kind_draws'],'Five board contexts do not conserve grants')
    curves=[];shapes=[];diagnostics=[]
    for c in settings['contexts']:
        out=report/'contexts'/c
        curves.extend(read_csv(out/'curves.csv'));shapes.extend(read_csv(out/'shape_contrasts.csv'))
        diagnostics.extend(json.loads((out/'MODEL_DIAGNOSTICS.json').read_text()))
    add_holm(shapes)
    write_csv(report/'curves.csv',curves);write_csv(report/'shape_contrasts.csv',shapes)
    common.atomic_json(report/'MODEL_DIAGNOSTICS.json',diagnostics)
    common.atomic_json(report/'SAMPLE_LINEAGE.json',lineage)
    common.atomic_json(report/'RUN_IDENTITY.json',dict(identity=identity,package_manifest_sha256=packagehash,
                       settings=settings,versions=versions))
    common.atomic_json(report/'INPUT_MANIFEST.json',[dict(month=r['month'],rows=r['rows'],
         size_bytes=r['size_bytes'],sha256=r['actual_sha256'],relative_path=f'panel/month={r["month"]}/analysis_panel.parquet')
         for r in auth['month_records']])
    shutil.copyfile(ROOT/'METHODS.md',report/'METHODS.md')
    render(report)
    for path,sig in snapshots.items():require(signature(path)==sig,'Production input changed during run')
    common.atomic_json(report/'_SUCCESS.json',dict(status=STATUS,identity=identity,version=VERSION,
        source_rows=EXPECTED['rows'],source_events=EXPECTED['kind_draws'],contexts=len(jobs),
        network_requests=0,source_inputs_unchanged=True,elapsed_seconds=time.monotonic()-start,
        no_usernames_or_game_ids_in_report=True))
    executed=report/'executed_code';executed.mkdir(exist_ok=True)
    rels=[line.split('  ',1)[1] for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines()]
    for rel in [*rels,'PACKAGE_MANIFEST.sha256']:
        destination=executed/rel;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/rel,destination)
    manifest(report)
    args.transfer_root.mkdir(parents=True,exist_ok=True)
    stem='POOL_WITHIN_CHOOSER_K_COMPARISON_RESULTS_v100_'+identity[:16]
    target=args.transfer_root/(stem+'.zip');temporary=target.with_suffix('.partial.zip')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,stem+'/'+p.relative_to(report).as_posix())
    os.replace(temporary,target);digest=common.sha256_file(target)
    common.atomic_text(target.with_suffix('.zip.sha256'),f'{digest}  {target.name}\n')
    log(f'{STATUS}\nRESULTS_ZIP: {target}\nSHA256: {digest}\nFIGURES: {report/"figures"}\nPRIVATE_CACHE: {private}')


if __name__=='__main__':main()
