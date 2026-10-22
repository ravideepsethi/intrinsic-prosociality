#!/usr/bin/env python3
"""Stable pregame ratings: unrestricted curves, chooser FE and local diagnostics."""
from __future__ import annotations
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse, concurrent.futures, fcntl, hashlib, multiprocessing, platform, shutil, time, zipfile
from pathlib import Path
import numpy as np
import scipy, duckdb, pyarrow as pa
from source import pool_wave1_common as common
from pooled_utils import log,qs,require,signature,write_csv,manifest,verify_manifest,checkpoint_ok,certify_checkpoint
from data_io import old_cache,stage_competitive,EXPECTED,SAMPLE_RELATIVE,validate_retained_counts
from stage_base import prepare_data
from fe_engine import AXES,iter_blocks,bin_axis,axis_definition
from pooled_engine import PooledMoments,fit_models,score_block,finish,retain_units,holm,STATES
from stable_specs import SAMPLES,INTERACT_SAMPLES,LOCAL_SAMPLES,SUPPORT,PRIMARY_LOCAL,select,add_normalized,local_definitions
import zero_engine

ROOT=Path(__file__).resolve().parent
VERSION='1.0.0';STATUS='POOL_STABLE_RATING_CURVES_OK'

def count_record(m,sample):
    return dict(sample=sample,label=SAMPLES[sample]['label'],source_competitive_rows=m.all_N,
      source_competitive_grants=m.all_events,source_competitive_choosers=m.all_G,
      estimation_rows=m.N,estimation_grants=m.events,chooser_clusters=m.G,
      absorbed_chooser_state_units=m.H,singleton_unit_rows_dropped=m.all_N-m.N,
      state_source_rows=dict(zip(STATES,m.all_state_N.tolist())),state_source_grants=dict(zip(STATES,m.all_state_events.tolist())),
      state_estimation_rows=dict(zip(STATES,m.state_N.tolist())),state_estimation_grants=dict(zip(STATES,m.state_events.tolist())),
      state_absorbed_units=dict(zip(STATES,m.state_H.tolist())))

def moments_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=path.parent/(path.stem+'_'+job['sample']);out.mkdir(exist_ok=True)
    receipt=out/'moments_done.json'
    if checkpoint_ok(receipt,job['identity']):
        verify_manifest(out,'MOMENT_MANIFEST.sha256');log('REUSED_MOMENTS '+out.name);return str(out)
    m=PooledMoments(job['edges']);locals_={key:zero_engine.LocalMoments(job['edges'],axis,h)
      for key,axis,h in local_definitions()} if job['sample'] in LOCAL_SAMPLES else {}
    audit={a:np.zeros((len(axis_definition(a)[1]),8)) for a in AXES}
    before=signature(path)
    for i,original in enumerate(iter_blocks(path,job['batch_rows'])):
        f=select(add_normalized(original),job['sample'])
        if not len(f['y']):continue
        m.add(f)
        for lm in locals_.values():lm.add(f)
        retained=retain_units(f)
        if len(retained['y']):
            vals=np.column_stack([np.ones(len(retained['y'])),retained['y'],retained['K'],retained['crd'],retained['drd'],
              (retained['crd']<=75)&(retained['drd']<=75),retained['gap'],retained['payoff']])
            for a in AXES:np.add.at(audit[a],bin_axis(retained[a],a),vals)
        if i and i%40==0:log(f'MOMENTS {out.name} blocks={i}')
    require(signature(path)==before,'Input shard changed')
    m.save(out/'moments.npz')
    for key,lm in locals_.items():lm.save(out/(key+'.npz'))
    np.savez_compressed(out/'composition.npz',**audit)
    common.atomic_json(receipt,dict(sample=job['sample'],identity=job['identity']))
    certify_checkpoint(receipt,job['identity'])
    # Only moment files: later score files must not invalidate this checkpoint.
    files=[out/'moments.npz',out/'composition.npz',receipt,receipt.with_suffix('.json.json')]+[out/(k+'.npz') for k in locals_]
    common.atomic_text(out/'MOMENT_MANIFEST.sha256',''.join(f'{common.sha256_file(p)}  {p.name}\n' for p in files))
    log('MOMENTS_DONE '+out.name);return str(out)

def scores_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=Path(job['moment_dir'])/'scores.npz'
    if checkpoint_ok(out,job['identity']):log('REUSED_SCORES '+out.parent.name);return str(out)
    models=job['models'];locals_=job['locals'];before=signature(path)
    for model in [*models.values(),*locals_.values()]:
        J=len(model['estimates']);model['meat']=np.zeros((J,J));model['score_sum']=np.zeros(J)
    for i,original in enumerate(iter_blocks(path,job['batch_rows'])):
        f=select(add_normalized(original),job['sample'])
        if not len(f['y']):continue
        score_block(f,job['edges'],models)
        for model in locals_.values():zero_engine.score(f,job['edges'],model)
        if i and i%40==0:log(f'SCORES {out.parent.name} blocks={i}')
    require(signature(path)==before,'Input shard changed during scores')
    arrays={}
    for prefix,collection in [('curve',models),('local',locals_)]:
        for key,m in collection.items():
            arrays[prefix+'__'+key+'__meat']=m['meat'];arrays[prefix+'__'+key+'__score_sum']=m['score_sum']
    tmp=out.with_name('scores.partial.npz');np.savez_compressed(tmp,**arrays);os.replace(tmp,out)
    certify_checkpoint(out,job['identity']);log('SCORES_DONE '+out.parent.name);return str(out)

def estimate(paths,edges,identity,workers,batch_rows,report):
    all_rows=[];all_shapes=[];all_tests=[];all_diag=[];all_local=[];all_counts=[];composition=[]
    # Sequential sample families bound memory; independent account shards use up to 10 workers.
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for sample in SAMPLES:
            log('ESTIMATING '+sample)
            jobs=[dict(path=str(p),sample=sample,edges=edges,identity=identity,batch_rows=batch_rows) for p in paths]
            dirs=list(pool.map(moments_job,jobs));m=PooledMoments(edges)
            lm={key:zero_engine.LocalMoments(edges,a,h) for key,a,h in local_definitions()} if sample in LOCAL_SAMPLES else {}
            audit={a:np.zeros((len(axis_definition(a)[1]),8)) for a in AXES}
            for directory in dirs:
                d=Path(directory);m.merge(PooledMoments.load(d/'moments.npz'))
                for key in lm:lm[key].merge(zero_engine.LocalMoments.load(d/(key+'.npz')))
                with np.load(d/'composition.npz',allow_pickle=False) as z:
                    for a in AXES:audit[a]+=z[a]
            counts=count_record(m,sample);all_counts.append(counts)
            if sample=='all':
                validate_retained_counts(counts)
                require(m.all_N==EXPECTED['fair_rows'] and m.all_events==EXPECTED['fair_kind_draws'],'Competitive source count mismatch')
            if m.G<2 or m.N<=m.H:
                log('INSUFFICIENT_SAMPLE '+sample+'; emitting support/unidentified placeholders')
            for a,c in m.counts.items():
                require(int(c['n'][0].sum())==m.N,'Curve axes do not use the same observations')
                require(int(c['events'][0].sum())==m.events,'Curve axes do not use the same outcomes')
                require(int(audit[a][:,0].sum())==m.N,'Composition audit row mismatch')
            models=fit_models(m,interaction=sample in INTERACT_SAMPLES)
            localmodels={key:zero_engine.fit(obj) for key,obj in lm.items()}
            scorejobs=[dict(job,moment_dir=d,models=models,locals=localmodels) for job,d in zip(jobs,dirs)]
            scorepaths=list(pool.map(scores_job,scorejobs))
            for p in scorepaths:
                with np.load(p,allow_pickle=False) as z:
                    for prefix,collection in [('curve',models),('local',localmodels)]:
                        for key,model in collection.items():
                            model['meat']+=z[prefix+'__'+key+'__meat'];model['score_sum']+=z[prefix+'__'+key+'__score_sum']
            rows,shapes,tests,diag,arrays=finish(m,models,**SUPPORT)
            for group in (rows,shapes,tests,diag):
                for row in group:
                    row['sample']=sample
                    # Global multiplicity adjustment is applied after combining sample families.
                    for key in list(row):
                        if key.startswith('p_holm_'):del row[key]
            for key,obj in lm.items():
                local,V=zero_engine.finish(obj,localmodels[key],**SUPPORT)
                for row in local:
                    row['sample']=sample;row['primary_specification']=(sample,obj.axis,obj.bandwidth)==PRIMARY_LOCAL
                all_local+=local;arrays['local__'+key+'__covariance']=V
                arrays['local__'+key+'__estimates']=localmodels[key]['estimates']
                obj.save(report/(sample+'_local_'+key+'_moments.npz'))
            np.savez_compressed(report/(sample+'_curve_covariances.npz'),**arrays)
            m.save(report/(sample+'_curve_moments.npz'))
            for a,v in audit.items():
                for j,item in enumerate(axis_definition(a)[1]):
                    n=v[j,0];composition.append(dict(sample=sample,axis=a,**item,n=int(n),grants=int(v[j,1]),
                      rate_percent=100*v[j,1]/n if n else None,mean_K=v[j,2]/n if n else None,
                      mean_chooser_RD=v[j,3]/n if n else None,mean_opponent_RD=v[j,4]/n if n else None,
                      share_both_RD_le75=v[j,5]/n if n else None,mean_rating_gap=v[j,6]/n if n else None,mean_draw_payoff=v[j,7]/n if n else None))
            all_rows+=rows;all_shapes+=shapes;all_tests+=tests;all_diag+=diag
            log(f'ESTIMATED {sample}: N={m.N:,}, chooser clusters={m.G:,}')
    # Fixed full family sizes include unsupported tests (p treated as 1).
    holm(all_local,lambda r:True,'p_two_sided','p_holm_all_90_local_tests')
    holm(all_local,lambda r:r['primary_specification'],'p_two_sided','p_holm_primary_5_tests')
    holm(all_shapes,lambda r:r['specification']=='chooser_state_controls_k20','p_two_sided','p_holm_all_60_adjusted_shape_tests')
    holm(all_tests,lambda r:True,'p_cluster_F','p_holm_all_6_heterogeneity_tests')
    write_csv(report/'curves.csv',all_rows);write_csv(report/'tail_contrasts.csv',all_shapes)
    if all_tests:write_csv(report/'board_state_heterogeneity.csv',all_tests)
    if all_local:write_csv(report/'zero_diagnostics.csv',all_local)
    write_csv(report/'bin_composition.csv',composition)
    common.atomic_json(report/'SAMPLE_COUNTS.json',all_counts)
    write_csv(report/'sample_counts.csv',[{k:v for k,v in r.items() if not isinstance(v,dict)} for r in all_counts])
    common.atomic_json(report/'MODEL_DIAGNOSTICS.json',all_diag)
    from stable_report import build_report
    build_report(report,all_rows,all_shapes,all_local,all_counts)
    return all_counts

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--sample-root',type=Path);p.add_argument('--output-root',type=Path)
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--hash-workers',type=int,default=2)
    p.add_argument('--batch-rows',type=int,default=32768);p.add_argument('--memory-limit',default='6GB')
    p.add_argument('--no-reuse-previous-cache',action='store_true');args=p.parse_args()
    require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be 1..10')
    require(1024<=args.batch_rows<=131072,'Batch rows must be 1024..131072')
    start=time.monotonic();packagehash=verify_manifest(ROOT,'PACKAGE_MANIFEST.sha256')
    auth=common.authenticate_sample(args.sample_root or args.project_root/SAMPLE_RELATIVE,verify_hashes=True,hash_workers=args.hash_workers)
    for key,value in EXPECTED.items():require(auth['authority'][key]==value,'Authority mismatch: '+key)
    versions=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__)
    settings=dict(samples=SAMPLES,support=SUPPORT,local=local_definitions(),primary_local=PRIMARY_LOCAL,
      workers=args.workers,batch_rows=args.batch_rows,memory_limit=args.memory_limit,
      fixed_effects='chooser_by_broad_competitive_board_state',cluster='chooser',curve_shape_restrictions=None)
    identity=hashlib.sha256(common.canonical_json(dict(package=packagehash,sample=auth['fingerprint'],versions=versions,settings=settings)).encode()).hexdigest()
    root=(args.output_root or args.project_root/'output/pool_stable_rating_curves_v100')/identity[:16]
    private=root/'PRIVATE';report=root/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
    lock=open(root/'run.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    source_signatures={str(r['path']):signature(r['path']) for r in auth['month_records']}
    cached=None if args.no_reuse_previous_cache else old_cache(args.project_root,auth)
    if cached is None:
        db=duckdb.connect();db.execute(f'SET threads={args.workers}');db.execute(f'SET memory_limit={qs(args.memory_limit)}')
        temp=private/'duckdb_spill';temp.mkdir(exist_ok=True);db.execute(f'SET temp_directory={qs(temp)}')
        prep=prepare_data(db,[r['path'] for r in auth['month_records']],private,identity,EXPECTED,[]);db.close()
        base=private/'sorted_base.parquet';cached=(base,prep,dict(kind='fresh_authenticated_source_build',sha256=common.sha256_file(base)))
    base,prep,receipt=cached;before=signature(base)
    paths=stage_competitive(base,private,identity,args.workers,EXPECTED['fair_rows'])
    common.atomic_json(report/'BASE_CACHE_PROVENANCE.json',receipt)
    common.atomic_json(report/'PREPARATION.json',prep)
    common.atomic_json(report/'RUN_IDENTITY.json',dict(identity=identity,settings=settings,versions=versions,package_manifest_sha256=packagehash))
    counts=estimate(paths,prep['K_cutpoints'],identity,args.workers,args.batch_rows,report)
    baseline=next(r for r in counts if r['sample']=='all')
    require(baseline['source_competitive_choosers']==auth['authority']['fair_choosers'],'Competitive chooser count mismatch')
    require(baseline['chooser_clusters']==1421546,'Retained chooser cluster count differs from preceding pooled run')
    common.atomic_json(report/'SAMPLE_LINEAGE.json',common.compact_sample_lineage(auth))
    common.atomic_json(report/'INPUT_MANIFEST.json',[dict(month=r['month'],rows=r['rows'],size_bytes=r['size_bytes'],sha256=r['actual_sha256'],relative_path=f'panel/month={r["month"]}/analysis_panel.parquet') for r in auth['month_records']])
    require(signature(base)==before,'Sorted base changed')
    for path,sig in source_signatures.items():require(signature(path)==sig,'Source input changed')
    for name in ('METHODS.md','REFERENCE_MODEL.md'):shutil.copyfile(ROOT/name,report/name)
    executed=report/'executed_code'
    for rel in [line.split('  ',1)[1] for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines()]+['PACKAGE_MANIFEST.sha256']:
        target=executed/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,target)
    common.atomic_json(report/'_SUCCESS.json',dict(status=STATUS,version=VERSION,identity=identity,samples=counts,
      network_requests=0,source_inputs_unchanged=True,elapsed_seconds=time.monotonic()-start,no_usernames_or_game_ids_in_report=True))
    manifest(report);args.transfer_root.mkdir(parents=True,exist_ok=True)
    stem='POOL_STABLE_RATING_CURVES_RESULTS_v100_'+identity[:16];target=args.transfer_root/(stem+'.zip');tmp=target.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(report.rglob('*')):
            if f.is_file():z.write(f,stem+'/'+f.relative_to(report).as_posix())
    os.replace(tmp,target);digest=common.sha256_file(target)
    common.atomic_text(target.with_suffix('.zip.sha256'),f'{digest}  {target.name}\n')
    log(f'{STATUS}\nRESULTS_ZIP: {target}\nSHA256: {digest}\nFIGURES: {report/"figures"}\nPRIVATE_CACHE: {private}')

if __name__=='__main__':main()
