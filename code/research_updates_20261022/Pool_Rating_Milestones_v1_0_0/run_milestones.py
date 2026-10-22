#!/usr/bin/env python3
"""Run the frozen exploratory milestone study on the certified 41.5M sample."""
from __future__ import annotations
import os
for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
import argparse
import concurrent.futures
import fcntl
import hashlib
import multiprocessing
import platform
from pathlib import Path
import shutil
import time
import zipfile
import numpy as np
import scipy
import duckdb
import pyarrow as pa
from source import pool_wave1_common as common
from pooled_utils import log,qs,require,signature,write_csv,manifest,verify_manifest,checkpoint_ok,certify_checkpoint
from fe_core import iter_blocks
from milestone_model import VERSION,specifications,common_design
from prepare import EXPECTED,empty_frame,stage_base,stage_shards,write_raw_tables
from estimator import init_moments,prepare_block,save_moments,load_moments,fit,score,finish

ROOT=Path(__file__).resolve().parent
SAMPLE_RELATIVE='derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
STATUS='POOL_RATING_MILESTONES_EXPLORATORY_OK'


def moments_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=path.with_name(path.stem+'_moments.npz');identity=job['identity']
    if checkpoint_ok(out,identity):log('REUSED_MOMENTS '+path.stem);return str(out)
    before=signature(path);moments=init_moments(empty_frame());total=0
    for i,frame in enumerate(iter_blocks(path,job['batch_rows'])):
        shared=common_design(frame)
        for spec in specifications():
            original,small,part=prepare_block(frame,spec,shared)
            moments[spec['key']].add(original,small,part)
        total+=len(frame['y'])
        if i and i%50==0:log(f'MOMENTS {path.stem}: read {total:,} rows')
    require(signature(path)==before,'Shard changed during moments pass')
    temporary=out.with_name(out.stem+'.partial.npz');save_moments(temporary,moments);os.replace(temporary,out)
    certify_checkpoint(out,identity,source_rows=total)
    log(f'MOMENTS_DONE {path.stem}: {total:,} rows');return str(out)


def scores_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=path.with_name(path.stem+'_scores.npz');identity=job['identity']
    if checkpoint_ok(out,identity):log('REUSED_SCORES '+path.stem);return str(out)
    before=signature(path);models=job['models']
    for model in models.values():
        q=len(model['estimates']);model['meat']=np.zeros((q,q));model['score_sum']=np.zeros(q)
    total=0
    for i,frame in enumerate(iter_blocks(path,job['batch_rows'])):
        score(frame,models);total+=len(frame['y'])
        if i and i%75==0:log(f'COVARIANCE {path.stem}: read {total:,} rows')
    require(signature(path)==before,'Shard changed during covariance pass')
    arrays={}
    for key,model in models.items():
        arrays[key+'__meat']=model['meat'];arrays[key+'__score_sum']=model['score_sum']
    temporary=out.with_name(out.stem+'.partial.npz');np.savez_compressed(temporary,**arrays);os.replace(temporary,out)
    certify_checkpoint(out,identity,source_rows=total)
    log('COVARIANCE_DONE '+path.stem);return str(out)


def dispatch(pool,function,jobs,label):
    pending={pool.submit(function,j):i for i,j in enumerate(jobs)};outputs={};start=time.monotonic()
    while pending:
        done,_=concurrent.futures.wait(pending,timeout=30,return_when=concurrent.futures.FIRST_COMPLETED)
        if not done:
            log(f'{label}: {len(outputs)}/{len(jobs)} shards complete; elapsed {(time.monotonic()-start)/60:.1f} min')
        for future in done:outputs[pending.pop(future)]=future.result()
    return [outputs[i] for i in range(len(jobs))]


def estimate(paths,identity,workers,batch_rows,report):
    jobs=[dict(path=str(p),identity=identity,batch_rows=batch_rows) for p in paths]
    combined=init_moments(empty_frame())
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        paths1=dispatch(pool,moments_job,jobs,'WITHIN_CHOOSER_MOMENTS')
        for path in paths1:
            part=load_moments(path,empty_frame())
            for key,m in part.items():combined[key].merge(m)
        models=fit(combined)
        jobs2=[dict(j,models=models) for j in jobs]
        paths2=dispatch(pool,scores_job,jobs2,'CHOOSER_CLUSTER_COVARIANCE')
    for path in paths2:
        with np.load(path,allow_pickle=False) as z:
            for key,model in models.items():
                model['meat']+=z[key+'__meat'];model['score_sum']+=z[key+'__score_sum']
    rows,diagnostics,covariances=finish(combined,models)
    write_csv(report/'all_model_attempts.csv',rows)
    write_csv(report/'primary_models.csv',[r for r in rows if r['specification']=='hundreds_primary'])
    write_csv(report/'sensitivity_and_placebo_models.csv',[r for r in rows if r['specification'] not in
        ('hundreds_primary','hundreds_by_threshold','hundreds_distance_profile')])
    write_csv(report/'individual_milestones.csv',[r for r in rows if r['specification']=='hundreds_by_threshold'])
    write_csv(report/'adjusted_distance_profile.csv',[r for r in rows if r['specification']=='hundreds_distance_profile'])
    common.atomic_json(report/'MODEL_DIAGNOSTICS.json',diagnostics)
    np.savez_compressed(report/'contrast_covariances.npz',**covariances)
    return rows,diagnostics


def package_results(report,transfer,identity):
    verify_manifest(report)
    transfer.mkdir(parents=True,exist_ok=True)
    stem='POOL_RATING_MILESTONES_RESULTS_v100_'+identity[:16]
    target=transfer/(stem+'.zip');sidecar=target.with_suffix('.zip.sha256')
    if target.is_file() and sidecar.is_file():
        expected=sidecar.read_text().split()[0]
        require(common.sha256_file(target)==expected,'Existing result ZIP checksum differs')
        log('REUSED completed result ZIP: '+str(target));return target
    temporary=target.with_suffix('.partial.zip')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:z.write(p,stem+'/'+p.relative_to(report).as_posix())
    with zipfile.ZipFile(temporary) as z:require(z.testzip() is None,'Result ZIP CRC failure')
    os.replace(temporary,target)
    common.atomic_text(sidecar,f'{common.sha256_file(target)}  {target.name}\n')
    return target


def write_summary(report,audit,rows,elapsed):
    def fmt(x):return '—' if x is None else f'{x:.5g}'
    lines=['# Round-rating milestones: exploratory results','',
        f'Authenticated source: {audit["counts"]["rows"]:,} pool, observed non-adjacent decisions.',
        f'Competitive source: {audit["counts"]["fair_rows"]:,} opportunities; {audit["counts"]["fair_kind_draws"]:,} kind draws.','',
        'The primary model uses competitive opportunities within 25 points of a multiple of 100 from 500 to 3000.',
        'It absorbs chooser fixed effects and conditions on board, game stage, rating gap, draw payoff, K, both RDs and volatilities, clocks, time-control variables, color, month, threshold and separate distance polynomials on each side.',
        'Loss crossing: already at/above the target; a draw falls below it while a claim stays at/above it.',
        'Gain crossing: below the target; a claim reaches it while a draw stays below it.','',
        '| Test | Estimate (pp) | Cluster SE | 95% CI (pp) | Holm p (2 tests) | N | Status |',
        '|---|---:|---:|---|---:|---:|---|']
    for r in rows:
        if r['specification']=='hundreds_primary':
            lines.append(f'| {r["term"]} | {fmt(r["estimate_pp"])} | {fmt(r["cluster_se_pp"])} | [{fmt(r["ci95_low_pp"])}, {fmt(r["ci95_high_pp"])}] | {fmt(r["p_holm_primary"])} | {r["estimation_rows"]:,} | {r["status"]} |')
    lines += ['', 'Negative coefficients indicate lower conditional kindness when the actions straddle the milestone.',
        'Read the two primary estimates together with the established-account, no-1500, bandwidth, game-stage, rounding and offset checks. Fifty-ending ratings are a weaker-salience comparison, not assumed to be an inert placebo.',
        'The individually estimated 100-point milestones, sensitivities and placebo tests form one separately reported Holm family. All attempted thresholds remain in that family; unsupported attempts enter its arithmetic as p=1.',
        'A non-rejection does not establish equivalence. These are observational conditional associations, not a regression-discontinuity design or a causal loss-aversion estimate.',
        'Counterfactual post-game ratings are reconstructed from the displayed pre-game rating plus v2 payoff. The rounding checks are approximations, not recovered historical display flags.',
        'Personal-best tests are not run: maxima over selected disconnect opportunities would not be valid prior rating peaks. Those require the all-game rating chronology within each speed pool.',
        '',f'Elapsed: {elapsed/60:.1f} minutes. See METHODS.md and all_model_attempts.csv.']
    common.atomic_text(report/'RESULTS.md','\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--sample-root',type=Path)
    parser.add_argument('--output-root',type=Path)
    parser.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--workers',type=int,default=10)
    parser.add_argument('--hash-workers',type=int,default=2)
    parser.add_argument('--memory-limit',default='6GB')
    parser.add_argument('--batch-rows',type=int,default=8192)
    args=parser.parse_args()
    require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be 1..10')
    require(1024<=args.batch_rows<=32768,'Batch rows must be 1024..32768')
    start=time.monotonic();packagehash=verify_manifest(ROOT,'PACKAGE_MANIFEST.sha256')
    sample=args.sample_root or args.project_root/SAMPLE_RELATIVE
    auth=common.authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
    for key,value in EXPECTED.items():require(auth['authority'][key]==value,'Wrong sample authority: '+key)
    versions=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__)
    settings=dict(specifications=specifications(),workers=args.workers,batch_rows=args.batch_rows,
        memory_limit=args.memory_limit,support=dict(min_rows=1000,min_switchers=100,min_months=6),
        fixed_effects='chooser',cluster='chooser',primary_tests=2,exploratory=True)
    identity=hashlib.sha256(common.canonical_json(dict(package=packagehash,sample=auth['fingerprint'],versions=versions,settings=settings)).encode()).hexdigest()
    root=(args.output_root or args.project_root/'output/pool_rating_milestones_v100')/identity[:16]
    private=root/'PRIVATE';report=root/'report'
    private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
    lock=open(root/'run.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    log(f'RUN_ROOT: {root}\nIDENTITY: {identity}\nWorkers: {args.workers}; DuckDB memory: {args.memory_limit}')
    if (report/'_SUCCESS.json').is_file():
        saved=common.load_json(report/'_SUCCESS.json')
        require(saved['identity']==identity and saved['status']==STATUS,'Unexpected completion receipt')
        target=package_results(report,args.transfer_root,identity)
        log(f'{STATUS}\nRESULTS_ZIP: {target}');return
    source_signatures={str(r['path']):signature(r['path']) for r in auth['month_records']}
    try:
        common.atomic_json(report/'RUN_IDENTITY.json',dict(identity=identity,versions=versions,settings=settings,package_manifest_sha256=packagehash))
        common.atomic_json(report/'SAMPLE_LINEAGE.json',common.compact_sample_lineage(auth))
        common.atomic_json(report/'INPUT_MANIFEST.json',[dict(month=r['month'],rows=r['rows'],size_bytes=r['size_bytes'],sha256=r['actual_sha256']) for r in auth['month_records']])
        db=duckdb.connect();db.execute(f'SET threads={args.workers}');db.execute(f'SET memory_limit={qs(args.memory_limit)}')
        spill=private/'duckdb_spill';spill.mkdir(exist_ok=True);db.execute(f'SET temp_directory={qs(spill)}')
        base,audit=stage_base(db,[r['path'] for r in auth['month_records']],private,identity)
        common.atomic_json(report/'SOURCE_AUDIT.json',audit)
        write_raw_tables(db,base,report);db.close()
        basesig=signature(base)
        paths=stage_shards(base,private,identity,args.workers,EXPECTED['fair_rows'])
        total=sum(common.load_json(p.with_suffix('.parquet.json'))['rows'] for p in paths)
        require(total==EXPECTED['fair_rows'],'Competitive shard total differs')
        rows,diagnostics=estimate(paths,identity,args.workers,args.batch_rows,report)
        from render import render
        render(report)
        elapsed=time.monotonic()-start
        write_summary(report,audit,rows,elapsed)
        shutil.copyfile(ROOT/'METHODS.md',report/'METHODS.md')
        require(signature(base)==basesig,'Base cache changed during estimation')
        for p,sig in source_signatures.items():require(signature(p)==sig,'Production input changed during run')
        executed=report/'executed_code'
        for rel in [line.split('  ',1)[1] for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines()]+['PACKAGE_MANIFEST.sha256']:
            target=executed/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,target)
        common.atomic_json(report/'_SUCCESS.json',dict(status=STATUS,identity=identity,version=VERSION,
            exploratory=True,source_rows=EXPECTED['rows'],competitive_source_rows=EXPECTED['fair_rows'],
            model_attempts=len(rows),estimated=sum(r['status']=='estimated' for r in rows),
            elapsed_seconds=elapsed,network_requests=0,source_inputs_unchanged=True,
            personal_best_test='not_run_requires_all_game_rating_history'))
        manifest(report)
        target=package_results(report,args.transfer_root,identity)
        log(f'{STATUS}\nRESULTS_ZIP: {target}\nSHA256_FILE: {target.with_suffix(".zip.sha256")}\nREPORT: {report/"RESULTS.md"}')
        print((report/'RESULTS.md').read_text(),flush=True)
    except BaseException as exc:
        common.atomic_json(root/'FAILED.json',dict(identity=identity,error_type=type(exc).__name__,error=str(exc),time_utc=common.utc_now()))
        raise


if __name__=='__main__':main()
