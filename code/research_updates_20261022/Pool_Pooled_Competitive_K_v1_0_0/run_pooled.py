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

def moments_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=path.with_name(path.stem+'_moments.npz');identity=job['identity']
    if checkpoint_ok(out,identity):log('REUSED_MOMENTS '+path.stem);return str(out)
    before=signature(path);m=PooledMoments(job['edges'])
    for i,frame in enumerate(iter_blocks(path,job['batch_rows'])):
        m.add(frame)
        if i and i%50==0:log(f'MOMENTS {path.stem} source_rows={m.all_N:,}')
    require(signature(path)==before,'Shard changed during moments pass')
    temporary=out.with_name(out.stem+'.partial.npz');m.save(temporary);os.replace(temporary,out)
    certify_checkpoint(out,identity)
    log(f'MOMENTS_DONE {path.stem}: N={m.N:,}, choosers={m.G:,}, absorbed_units={m.H:,}')
    return str(out)

def scores_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=path.with_name(path.stem+'_scores.npz');identity=job['identity']
    if checkpoint_ok(out,identity):log('REUSED_SCORES '+path.stem);return str(out)
    before=signature(path);models=job['models']
    # Do not inherit accumulated parent scores if tasks are serialized lazily.
    for model in models.values():
        J=len(model['estimates']);model['meat']=np.zeros((J,J));model['score_sum']=np.zeros(J)
    for i,frame in enumerate(iter_blocks(path,job['batch_rows'])):
        score_block(frame,job['edges'],models)
        if i and i%50==0:log(f'SCORES {path.stem} blocks={i}')
    require(signature(path)==before,'Shard changed during covariance pass')
    arrays={}
    for key,m in models.items():arrays[key+'__meat']=m['meat'];arrays[key+'__score_sum']=m['score_sum']
    temporary=out.with_name(out.stem+'.partial.npz');np.savez_compressed(temporary,**arrays);os.replace(temporary,out)
    certify_checkpoint(out,identity);log('SCORES_DONE '+path.stem);return str(out)

def estimate(paths,edges,identity,workers,batch_rows,report,support):
    jobs=[dict(path=str(p),edges=edges,identity=identity,batch_rows=batch_rows) for p in paths]
    m=PooledMoments(edges)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for p in pool.map(moments_job,jobs):m.merge(PooledMoments.load(p))
        for axis,c in m.counts.items():
            require(int(c['n'][0].sum())==m.N and int(c['events'][0].sum())==m.events,'Pooled count conservation failed')
            require(np.array_equal(c['n'][1:].sum(axis=0),c['n'][0]),'State counts do not sum to pooled counts')
        models=fit_models(m)
        score_jobs=[dict(j,models=models) for j in jobs]
        # Keep parent model objects unchanged while worker jobs are dispatched.
        scorepaths=list(pool.map(scores_job,score_jobs))
    for p in scorepaths:
        with np.load(p,allow_pickle=False) as z:
            for key,model in models.items():
                model['meat']+=z[key+'__meat'];model['score_sum']+=z[key+'__score_sum']
    rows,shapes,tests,diagnostics,arrays=finish(m,models,**support)
    write_csv(report/'curves.csv',rows);write_csv(report/'shape_contrasts.csv',shapes)
    write_csv(report/'heterogeneity_tests.csv',tests)
    common.atomic_json(report/'HETEROGENEITY_TESTS.json',tests)
    common.atomic_json(report/'MODEL_DIAGNOSTICS.json',diagnostics)
    np.savez_compressed(report/'curve_covariances.npz',**arrays)
    m.save(report/'within_chooser_state_moments.npz')
    counts=dict(source_competitive_rows=m.all_N,source_competitive_grants=m.all_events,
      source_competitive_choosers=m.all_G,estimation_rows=m.N,estimation_grants=m.events,
      chooser_clusters=m.G,absorbed_chooser_state_units=m.H,singleton_unit_rows_dropped=m.all_N-m.N,
      state_source_rows=dict(zip(STATES,m.all_state_N.tolist())),state_source_grants=dict(zip(STATES,m.all_state_events.tolist())),
      state_estimation_rows=dict(zip(STATES,m.state_N.tolist())),state_estimation_grants=dict(zip(STATES,m.state_events.tolist())),
      state_absorbed_units=dict(zip(STATES,m.state_H.tolist())))
    common.atomic_json(report/'SAMPLE_COUNTS.json',counts)
    return counts,shapes,tests

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
    parser.add_argument('--no-reuse-previous-cache',action='store_true')
    args=parser.parse_args()
    require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be 1..10')
    require(1024<=args.batch_rows<=131072,'Use 1024..131072 batch rows')
    start=time.monotonic();packagehash=verify_manifest(ROOT,'PACKAGE_MANIFEST.sha256')
    sample=args.sample_root or args.project_root/SAMPLE_RELATIVE
    auth=common.authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
    for key,value in EXPECTED.items():require(auth['authority'][key]==value,'Authority mismatch: '+key)
    versions=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
      duckdb=duckdb.__version__,pyarrow=pa.__version__)
    settings=dict(workers=args.workers,batch_rows=args.batch_rows,memory_limit=args.memory_limit,
      fixed_effects='chooser_by_three_competitive_board_states',cluster='chooser',
      support=dict(min_n=500,min_choosers=50,min_months=6),K_cutpoint_population='all 41,534,331 source rows')
    identity=hashlib.sha256(common.canonical_json(dict(package=packagehash,sample=auth['fingerprint'],
      versions=versions,settings=settings)).encode()).hexdigest()
    root=(args.output_root or args.project_root/'output/pool_pooled_competitive_k_v100')/identity[:16]
    private=root/'PRIVATE';report=root/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
    lock=open(root/'run.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    source_signatures={str(r['path']):signature(r['path']) for r in auth['month_records']}
    cached=None if args.no_reuse_previous_cache else old_cache(args.project_root,auth)
    if cached is None:
        db=duckdb.connect();db.execute(f'SET threads={args.workers}');db.execute(f'SET memory_limit={qs(args.memory_limit)}')
        temp=private/'duckdb_spill';temp.mkdir(exist_ok=True);db.execute(f'SET temp_directory={qs(temp)}')
        prep=prepare_data(db,[r['path'] for r in auth['month_records']],private,identity,EXPECTED,[]);db.close()
        base=private/'sorted_base.parquet'
        cached=(base,prep,dict(kind='fresh_authenticated_source_build',path=str(base),sha256=common.sha256_file(base)))
    base,prep,cache_receipt=cached;base_signature=signature(base)
    paths=stage_competitive(base,private,identity,args.workers,EXPECTED['fair_rows'])
    common.atomic_json(report/'BASE_CACHE_PROVENANCE.json',cache_receipt)
    common.atomic_json(report/'PREPARATION.json',prep)
    write_csv(report/'K_bin_support.csv',prep['K_bin_support'])
    counts,shapes,tests=estimate(paths,prep['K_cutpoints'],identity,args.workers,args.batch_rows,report,settings['support'])
    require(counts['source_competitive_rows']==EXPECTED['fair_rows'],'Competitive source rows differ')
    require(counts['source_competitive_grants']==EXPECTED['fair_kind_draws'],'Competitive source grants differ')
    require(counts['source_competitive_choosers']==auth['authority']['fair_choosers'],'Competitive chooser count differs')
    validate_retained_counts(counts)
    common.atomic_json(report/'SAMPLE_LINEAGE.json',common.compact_sample_lineage(auth))
    common.atomic_json(report/'RUN_IDENTITY.json',dict(identity=identity,settings=settings,versions=versions,package_manifest_sha256=packagehash))
    common.atomic_json(report/'INPUT_MANIFEST.json',[dict(month=r['month'],rows=r['rows'],size_bytes=r['size_bytes'],
      sha256=r['actual_sha256'],relative_path=f'panel/month={r["month"]}/analysis_panel.parquet') for r in auth['month_records']])
    from render_pooled import render
    render(report)
    lines=['# Pooled competitive-position analysis','',
      f'Competitive source: {counts["source_competitive_rows"]:,} opportunities; {counts["source_competitive_grants"]:,} kind draws.',
      f'Common estimation sample: {counts["estimation_rows"]:,} opportunities; {counts["chooser_clusters"]:,} chooser clusters; {counts["absorbed_chooser_state_units"]:,} chooser-by-state intercepts.','',
      'Fixed effects: chooser × roughly equal/better/clearly better. Covariance is clustered by chooser across states.','',
      '## Pooled K20 shape contrasts','', '| Axis | Contrast | Estimate (pp) | Cluster SE | Holm p (8 tests) | Status |',
      '|---|---|---:|---:|---:|---|']
    def fmt(x):return '—' if x is None else f'{x:.4g}'
    for r in shapes:
        if r['specification']=='chooser_state_controls_k20':
            lines.append(f'| {r["axis"]} | {r["contrast"]} | {fmt(r["estimate_pp"])} | {fmt(r["cluster_se_pp"])} | {fmt(r["p_holm_primary_shape"])} | {r["status"]} |')
    lines+=['','## Board-state heterogeneity','']
    for r in tests:lines.append(f'- {r["axis"]}: {r["status"]}; joint F p={fmt(r["p_cluster_F"])}; Holm p over two axes={fmt(r["p_holm_two_axes"])}.')
    lines+=['','All curves and tests are exploratory conditional associations. The pooled curve imposes a common axis response across states. A non-rejection is not evidence of equivalence. See METHODS.md for support, inference and weighting.']
    common.atomic_text(report/'RESULTS.md','\n'.join(lines)+'\n');shutil.copyfile(ROOT/'METHODS.md',report/'METHODS.md')
    require(signature(base)==base_signature,'Sorted base changed during analysis')
    for p,sig in source_signatures.items():require(signature(p)==sig,'Production input changed during analysis')
    executed=report/'executed_code'
    for rel in [line.split('  ',1)[1] for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines()]+['PACKAGE_MANIFEST.sha256']:
        target=executed/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,target)
    common.atomic_json(report/'_SUCCESS.json',dict(status=STATUS,version=VERSION,identity=identity,
      network_requests=0,source_inputs_unchanged=True,source_rows=EXPECTED['rows'],**counts,
      elapsed_seconds=time.monotonic()-start,no_usernames_or_game_ids_in_report=True))
    manifest(report)
    args.transfer_root.mkdir(parents=True,exist_ok=True);stem='POOL_POOLED_COMPETITIVE_K_RESULTS_v100_'+identity[:16]
    target=args.transfer_root/(stem+'.zip');temporary=target.with_suffix('.partial.zip')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,stem+'/'+p.relative_to(report).as_posix())
    os.replace(temporary,target);digest=common.sha256_file(target)
    common.atomic_text(target.with_suffix('.zip.sha256'),f'{digest}  {target.name}\n')
    log(f'{STATUS}\nRESULTS_ZIP: {target}\nSHA256: {digest}\nFIGURES: {report/"figures"}\nPRIVATE_CACHE: {private}')

if __name__=='__main__':main()
