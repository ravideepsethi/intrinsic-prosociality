#!/usr/bin/env python3
"""Refit the existing curves after separating small losses, exact zero and gains."""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import argparse, concurrent.futures, csv, fcntl, hashlib, json, multiprocessing, platform, shutil, time, zipfile
from pathlib import Path
import numpy as np
import scipy, duckdb, pyarrow as pa
from source import pool_wave1_common as common
from pooled_utils import log,qs,require,signature,write_csv,manifest,verify_manifest,checkpoint_ok,certify_checkpoint
from data_io import old_cache,stage_competitive,EXPECTED,SAMPLE_RELATIVE,validate_retained_counts
from stage_base import prepare_data
from fe_engine import AXES,iter_blocks,axis_definition
from pooled_engine import PooledMoments,fit_models,score_block,finish,retain_units,STATES

ROOT=Path(__file__).resolve().parent
VERSION='1.0.0'; STATUS='POOL_SPLIT_ZERO_CURVES_OK'
SUPPORT=dict(min_n=500,min_choosers=50,min_months=6)
AUDIT_KEYS=('retained_rows','negative_payoff','exact_zero_payoff','positive_payoff',
            'nonzero_abs_payoff_le_1e_minus12','equal_displayed_rating','zero_payoff_nonzero_gap',
            'zero_gap_nonzero_payoff','opposite_payoff_gap_sign','old_central_bin')

def count_record(m):
    return dict(sample='all',source_competitive_rows=m.all_N,source_competitive_grants=m.all_events,
      source_competitive_choosers=m.all_G,estimation_rows=m.N,estimation_grants=m.events,
      chooser_clusters=m.G,absorbed_chooser_state_units=m.H,singleton_unit_rows_dropped=m.all_N-m.N,
      state_source_rows=dict(zip(STATES,m.all_state_N.tolist())),
      state_source_grants=dict(zip(STATES,m.all_state_events.tolist())),
      state_estimation_rows=dict(zip(STATES,m.state_N.tolist())),
      state_estimation_grants=dict(zip(STATES,m.state_events.tolist())),
      state_absorbed_units=dict(zip(STATES,m.state_H.tolist())))

def verify_prior_counts(counts):
    # This evidence file is a JSON ARRAY, not an object. Do not use common.load_json.
    records=json.loads((ROOT/'evidence/PRIOR_STABLE_SAMPLE_COUNTS.json').read_text())
    require(isinstance(records,list),'Prior sample-count evidence must be a list')
    old=next(r for r in records if r['sample']=='all')
    for key,value in counts.items():
        require(value==old[key],f'Prior stable sample mismatch: {key}')
    validate_retained_counts(counts)
    return dict(status='EXACT_COUNTS_MATCH',prior_run='68050a8540511454',counts=counts)

def zero_audit(frame):
    f=retain_units(frame)
    d,g=f['payoff'],f['gap']
    return np.array([len(d),np.sum(d<0),np.sum(d==0),np.sum(d>0),
      np.sum((d!=0)&(np.abs(d)<=1e-12)),np.sum(g==0),np.sum((d==0)&(g!=0)),
      np.sum((g==0)&(d!=0)),np.sum(((g<0)&(d>0))|((g>0)&(d<0))),
      np.sum((d>=-.4)&(d<.4))],dtype=np.int64)

def moments_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=path.parent/(path.stem+'_split_zero');out.mkdir(exist_ok=True)
    target=out/'moments.npz';audit_path=out/'zero_audit.json'
    if checkpoint_ok(target,job['identity']) and checkpoint_ok(audit_path,job['identity']):
        log('REUSED_MOMENTS '+path.stem);return str(out)
    m=PooledMoments(job['edges']);audit=np.zeros(len(AUDIT_KEYS),dtype=np.int64);before=signature(path)
    for i,f in enumerate(iter_blocks(path,job['batch_rows'])):
        m.add(f);audit+=zero_audit(f)
        if i and i%50==0:log(f'MOMENTS {path.stem} blocks={i}')
    require(signature(path)==before,'Input shard changed during moment pass')
    tmp=out/'moments.partial.npz';m.save(tmp);os.replace(tmp,target)
    common.atomic_json(audit_path,dict(zip(AUDIT_KEYS,map(int,audit))))
    certify_checkpoint(target,job['identity']);certify_checkpoint(audit_path,job['identity'])
    log('MOMENTS_DONE '+path.stem);return str(out)

def scores_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    path=Path(job['path']);out=Path(job['moment_dir'])/'scores.npz'
    if checkpoint_ok(out,job['identity']):log('REUSED_SCORES '+path.stem);return str(out)
    models=job['models'];before=signature(path)
    for model in models.values():
        j=len(model['estimates']);model['meat']=np.zeros((j,j));model['score_sum']=np.zeros(j)
    for i,f in enumerate(iter_blocks(path,job['batch_rows'])):
        score_block(f,job['edges'],models)
        if i and i%50==0:log(f'SCORES {path.stem} blocks={i}')
    require(signature(path)==before,'Input shard changed during covariance pass')
    arrays={key+'__'+field:model[field] for key,model in models.items() for field in ('meat','score_sum')}
    tmp=out.with_name('scores.partial.npz');np.savez_compressed(tmp,**arrays);os.replace(tmp,out)
    certify_checkpoint(out,job['identity']);log('SCORES_DONE '+path.stem);return str(out)

def verify_gap_replication(rows,report):
    with (ROOT/'evidence/PRIOR_STABLE_CURVES.csv').open(newline='') as stream:
        prior={(r['specification'],int(r['bin'])):r for r in csv.DictReader(stream)
               if r['sample']=='all' and r['axis']=='gap' and r['context']=='pooled_competitive'}
    errors=[]
    for row in rows:
        if row['axis']!='gap':continue
        old=prior[(row['specification'],row['bin'])]
        for field in ('n','events','choosers','switching_choosers','direct_reference_choosers','months'):
            require(int(old[field])==row[field],'Gap count replication failed: '+field)
        require((old['estimable']=='True')==row['estimable'],'Gap estimability changed')
        for field in ('estimate_pp','cluster_se_pp'):
            if row[field] is not None:
                error=abs(row[field]-float(old[field]));errors.append(error)
                require(error<2e-5,'Unchanged gap estimate did not replicate: '+field)
    result=dict(status='GAP_REPLICATION_OK',maximum_absolute_difference_pp=max(errors),tolerance_pp=2e-5)
    common.atomic_json(report/'GAP_REPLICATION.json',result);return result

def estimate(paths,edges,identity,workers,batch_rows,report,production=True):
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        jobs=[dict(path=str(p),edges=edges,identity=identity,batch_rows=batch_rows) for p in paths]
        dirs=list(pool.map(moments_job,jobs));m=PooledMoments(edges)
        audit=dict.fromkeys(AUDIT_KEYS,0)
        for directory in dirs:
            d=Path(directory);m.merge(PooledMoments.load(d/'moments.npz'))
            a=common.load_json(d/'zero_audit.json')
            for key in audit:audit[key]+=a[key]
        counts=count_record(m)
        if production:
            common.atomic_json(report/'SAMPLE_REPLICATION.json',verify_prior_counts(counts))
        require(audit['retained_rows']==m.N,'Zero audit sample differs')
        require(audit['negative_payoff']+audit['exact_zero_payoff']+audit['positive_payoff']==m.N,'Sign audit lost rows')
        common.atomic_json(report/'ZERO_AUDIT.json',dict(**audit,definition='payoff == 0.0 in stored unrounded chooser_draw_payoff_v2; no tolerance or rounding'))
        if production:
            with (ROOT/'evidence/PRIOR_STABLE_CURVES.csv').open(newline='') as stream:
                old_reference=next(r for r in csv.DictReader(stream) if r['sample']=='all' and r['axis']=='payoff'
                    and r['specification']=='raw' and r['context']=='pooled_competitive' and r['reference']=='True')
            central_codes=[r['bin'] for r in axis_definition('payoff')[1]
                           if r['mid'] is not None and abs(r['mid'])<.3]
            split_n=int(m.counts['payoff']['n'][0,central_codes].sum())
            split_events=int(m.counts['payoff']['events'][0,central_codes].sum())
            require(split_n==int(old_reference['n'])==audit['old_central_bin'],'Split bins do not conserve old reference-bin observations')
            require(split_events==int(old_reference['events']),'Split bins do not conserve old reference-bin grants')
            common.atomic_json(report/'CENTRAL_BIN_PARTITION.json',dict(status='EXACT_PARTITION_MATCH',
                old_reference_n=split_n,old_reference_grants=split_events,new_bin_codes=central_codes))
        for axis,c in m.counts.items():
            require(int(c['n'][0].sum())==m.N,'Axes have different samples')
            require(int(c['events'][0].sum())==m.events,'Axes have different outcomes')
        require(audit['exact_zero_payoff']>0,'No exact-zero observations: see ZERO_AUDIT.json; do not substitute a tolerance')
        log(f'SAMPLE_OK N={m.N:,}; choosers={m.G:,}; exact zeros={audit["exact_zero_payoff"]:,}')
        models=fit_models(m,interaction=False)
        scorejobs=[dict(job,moment_dir=d,models=models) for job,d in zip(jobs,dirs)]
        for path in pool.map(scores_job,scorejobs):
            with np.load(path,allow_pickle=False) as z:
                for key,model in models.items():
                    model['meat']+=z[key+'__meat'];model['score_sum']+=z[key+'__score_sum']
    rows,shapes,tests,diag,arrays=finish(m,models,**SUPPORT)
    for row in rows:row['sample']='all'
    central=[r for r in rows if r['axis']=='payoff' and r['specification']=='chooser_state_controls_k20'
             and r['mid'] is not None and abs(r['mid'])<.3]
    require(len(central)==3,'Expected three central payoff bins')
    if production:
        require(all(r['display_supported'] for r in central),'Central split bins fail support/estimability; inspect private moments and zero audit')
        verify_gap_replication(rows,report)
    write_csv(report/'curves.csv',rows)
    write_csv(report/'bin_definitions.csv',[dict(axis=a,**r) for a in AXES for r in axis_definition(a)[1]])
    common.atomic_json(report/'SAMPLE_COUNTS.json',counts)
    common.atomic_json(report/'MODEL_DIAGNOSTICS.json',diag)
    np.savez_compressed(report/'curve_covariances.npz',**arrays)
    m.save(report/'curve_moments.npz')
    from split_report import build_report
    build_report(report,rows,arrays,counts)
    return counts

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
    require(auth['fingerprint']==common.load_json(ROOT/'evidence/PRIOR_STABLE_SAMPLE_LINEAGE.json')['fingerprint'],'Different source sample from prior stable run')
    versions=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__)
    settings=dict(sample='all_competitive',axes={a:axis_definition(a)[1] for a in AXES},support=SUPPORT,
      zero_definition='stored payoff == 0.0; no rounding or tolerance',workers=args.workers,batch_rows=args.batch_rows,
      memory_limit=args.memory_limit,fixed_effects='chooser_by_broad_competitive_board_state',cluster='chooser',shape_restrictions=None)
    identity=hashlib.sha256(common.canonical_json(dict(package=packagehash,sample=auth['fingerprint'],versions=versions,settings=settings)).encode()).hexdigest()
    root=(args.output_root or args.project_root/'output/pool_split_zero_curves_v100')/identity[:16]
    private=root/'PRIVATE';report=root/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
    lock=open(root/'run.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    signatures={str(r['path']):signature(r['path']) for r in auth['month_records']}
    cached=None if args.no_reuse_previous_cache else old_cache(args.project_root,auth)
    if cached is None:
        db=duckdb.connect();db.execute(f'SET threads={args.workers}');db.execute(f'SET memory_limit={qs(args.memory_limit)}')
        spill=private/'duckdb_spill';spill.mkdir(exist_ok=True);db.execute(f'SET temp_directory={qs(spill)}')
        prep=prepare_data(db,[r['path'] for r in auth['month_records']],private,identity,EXPECTED,[]);db.close()
        base=private/'sorted_base.parquet';cached=(base,prep,dict(kind='fresh_authenticated_source_build',sha256=common.sha256_file(base)))
    base,prep,receipt=cached;before=signature(base)
    paths=stage_competitive(base,private,identity,args.workers,EXPECTED['fair_rows'])
    common.atomic_json(report/'BASE_CACHE_PROVENANCE.json',receipt);common.atomic_json(report/'PREPARATION.json',prep)
    common.atomic_json(report/'RUN_IDENTITY.json',dict(identity=identity,settings=settings,versions=versions,package_manifest_sha256=packagehash))
    counts=estimate(paths,prep['K_cutpoints'],identity,args.workers,args.batch_rows,report)
    common.atomic_json(report/'SAMPLE_LINEAGE.json',common.compact_sample_lineage(auth))
    common.atomic_json(report/'INPUT_MANIFEST.json',[dict(month=r['month'],rows=r['rows'],size_bytes=r['size_bytes'],sha256=r['actual_sha256']) for r in auth['month_records']])
    require(signature(base)==before,'Sorted base changed')
    for path,sig in signatures.items():require(signature(path)==sig,'Source input changed')
    for name in ('METHODS.md','README.md'):shutil.copyfile(ROOT/name,report/name)
    executed=report/'executed_code'
    for rel in [line.split('  ',1)[1] for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines()]+['PACKAGE_MANIFEST.sha256']:
        target=executed/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,target)
    common.atomic_json(report/'_SUCCESS.json',dict(status=STATUS,version=VERSION,identity=identity,sample=counts,
      network_requests=0,source_inputs_unchanged=True,elapsed_seconds=time.monotonic()-start,no_usernames_or_game_ids_in_report=True))
    manifest(report);args.transfer_root.mkdir(parents=True,exist_ok=True)
    stem='POOL_SPLIT_ZERO_CURVES_RESULTS_v100_'+identity[:16];target=args.transfer_root/(stem+'.zip');tmp=target.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(report.rglob('*')):
            if f.is_file():z.write(f,stem+'/'+f.relative_to(report).as_posix())
    os.replace(tmp,target);digest=common.sha256_file(target)
    common.atomic_text(target.with_suffix('.zip.sha256'),f'{digest}  {target.name}\n')
    log(f'{STATUS}\nRESULTS_ZIP: {target}\nSHA256: {digest}\nFIGURES: {report/"figures"}')

if __name__=='__main__':main()
