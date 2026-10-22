#!/usr/bin/env python3
"""Run the fixed C9 ply-sensitivity specification using authenticated inputs."""
from __future__ import annotations
import argparse
import contextlib
import csv
import fcntl
import hashlib
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import numpy as np
from runner import common, run_c9 as prior, ply_engine as engine, checkpoints

PACKAGE = Path(__file__).resolve().parents[1]
SPEC = common.load_json(PACKAGE/'authority/C9_PLY_SPEC.json')
VERSION = 'C9-PLY-1.0.0'


def reference_report():
    archive = PACKAGE/'evidence/C9_COMPLETED_RESULTS.zip'
    prior.require_hash(archive,SPEC['original_c9_report_sha256'],'completed C9 result archive')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('Completed C9 CRC failure')
        names = [n for n in z.namelist() if not n.endswith('/')]
        manifests = [n for n in names if n.endswith('/REPORT_FILE_HASHES.tsv')]
        if len(manifests) != 1 or len(names) != len(set(names)):
            raise RuntimeError('Completed C9 manifest inventory is ambiguous')
        manifest = manifests[0];prefix = manifest.rsplit('/',1)[0]+'/'
        rows = list(csv.DictReader(io.StringIO(z.read(manifest).decode()),delimiter='\t'))
        if set(names) != {prefix+r['relative_path'] for r in rows}|{manifest}:
            raise RuntimeError('Completed C9 unlisted members')
        files = {}
        for r in rows:
            contents = z.read(prefix+r['relative_path'])
            if hashlib.sha256(contents).hexdigest() != r['sha256'] or len(contents) != int(r['bytes']):
                raise RuntimeError('Completed C9 report hash mismatch: '+r['relative_path'])
            files[r['relative_path']] = contents
    envelope = json.loads(files['CONFIGURATION.json'])
    digest = hashlib.sha256(common.canonical_json(envelope['config']).encode()).hexdigest()
    success = json.loads(files['_SUCCESS.json'])
    if digest != envelope['config_sha256'] or digest != SPEC['original_c9_config_sha256']:
        raise RuntimeError('Completed C9 configuration mismatch')
    if success['config_sha256'] != digest or success['summary_sha256'] != hashlib.sha256(files['summary.json']).hexdigest():
        raise RuntimeError('Completed C9 success/summary binding mismatch')
    if success['status'] != 'POOL_MAIN_C9_FRESH_RANDOMIZATION_OK' or not success['exact_new_sample_b2_reproduction']:
        raise RuntimeError('Completed C9 reference was not successful')
    session = json.loads(files['c9_session_mapping.json'])
    if session['persisted_private_cache_sha256'] != SPEC['session_cache_sha256']:
        raise RuntimeError('Session cache authority mismatch')
    return files


@contextlib.contextmanager
def exclusive(project):
    private = project/'derived/replication/pool_main_reanalysis_v100_PRIVATE'
    base = private/'c9_ply_v100'
    base.mkdir(parents=True,exist_ok=True)
    shared = private/'c9_fresh_v100/runner.lock'
    shared.parent.mkdir(parents=True,exist_ok=True)
    with (base/'runner.lock').open('a+') as own:
        try:
            fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError('A C9 ply run is already active') from e
        with shared.open('a+') as original:
            while True:
                try:
                    fcntl.flock(original,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    prior.log('Waiting for the existing C9/Patron job; checking again in 30 seconds.')
                    time.sleep(30)
            yield base


def authenticate(args):
    package = common.verify_package_manifest()
    reference = reference_report()
    paths = prior.paths_for(args.project_root)
    c9_state = paths['private_base']/SPEC['original_c9_config_sha256'][:12]
    c9_public = paths['public_base']/SPEC['original_c9_config_sha256'][:12]
    session = c9_state/'sessions/b1_c9_session_private.parquet'
    checks = [(paths['wave_status'],prior.SPEC['wave2b1_status_sha256'],'Wave2B1 status'),
              (paths['b1'],prior.SPEC['b1_sample_sha256'],'B1 repeat granters'),
              (paths['prop'],prior.SPEC['b1_propensity_sha256'],'B1 cross-fitted propensities'),
              (paths['b2_script'],prior.SPEC['b2_script_sha256'],'executed B2 producer'),
              (paths['b2_public']/'_SUCCESS.json',prior.SPEC['b2_success_sha256'],'B2 success'),
              (paths['b2_public']/'summary.json',prior.SPEC['b2_summary_sha256'],'B2 summary'),
              (paths['b2_public']/'b2_first_grant_horizons.csv',prior.SPEC['b2_horizons_sha256'],'B2 horizons'),
              (session,SPEC['session_cache_sha256'],'completed all-game session cache'),
              (c9_state/'CONFIGURATION.json',hashlib.sha256(reference['CONFIGURATION.json']).hexdigest(),'private C9 configuration'),
              (c9_public/'_SUCCESS.json',hashlib.sha256(reference['_SUCCESS.json']).hexdigest(),'completed C9 success')]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda row: prior.require_hash(*row),checks))
    sample = common.authenticate_sample(paths['sample'],verify_hashes=True,hash_workers=args.workers)
    if sample['fingerprint'] != prior.SPEC['sample_fingerprint']:
        raise RuntimeError('Certified sample fingerprint changed')
    c9 = prior.load_c9()
    b2 = common.load_source_module(paths['b2_script'],'authenticated_c9_ply_b2')
    for key,wanted in [('EXPECTED_ROWS',832948),('EXPECTED_CHOOSERS',55359),('EXPECTED_KIND_DRAWS',234993),
                       ('B2_SEED',2026082201),('RANDOMIZATIONS',4999),('RANDOMIZATION_BATCH',250)]:
        if getattr(b2,key) != wanted:
            raise RuntimeError('Executed B2 authority changed: '+key)
    inventory = json.loads(reference['CHECKPOINT_INVENTORY.json'])['batches']
    if [(r['start'],r['stop_exclusive']) for r in inventory] != [(i,min(i+250,4999)) for i in range(0,4999,250)]:
        raise RuntimeError('Completed C9 batch coverage changed')
    for row in inventory:
        start,stop = row['start'],row['stop_exclusive']
        path,receipt = c9.batch_checkpoint_paths(c9_state,start,stop)
        saved = c9.authenticate_checkpoint(path,receipt,start,stop,SPEC['original_c9_config_sha256'])
        if saved != row:
            raise RuntimeError('Local C9 batch differs from uploaded reference')
        path = paths['b2_state']/'randomizations'/f'b2_{start:04d}_{stop-1:04d}.npz'
        if b2.authenticate_checkpoint(path,path.with_suffix('.json'),start,stop,prior.SPEC['b2_config_sha256']) is None:
            raise RuntimeError('Missing completed B2 reference batch')
    receipt = {'status':'C9_PLY_PREFLIGHT_READY','package':package,'input_hashes':records,
               'sample':common.compact_sample_lineage(sample),'session_cache_reused':True,
               'all_game_chronology_rows_read':0,'reference_C9_batches':20,'reference_B2_batches':20,
               'runtime':common.environment_record(),'network_requests':0}
    return paths,session,c9,b2,reference,receipt,{'c9_state':str(c9_state),'b2_state':str(paths['b2_state'])}


def worker_budget(data,ply,b2,requested,memory_gb):
    bands = engine.ply_bands(ply)
    cells = strata = 0
    for a,z in b2.chooser_slices(data['chooser_index']):
        y = data['kind_draw'][a:z]
        cells += (z-a)*(int(y.sum())+1)
        for band in np.unique(bands[a:z]):
            sy = y[bands[a:z] == band]
            cells += len(sy)*(int(sy.sum())+1)
            strata += 1
    # Conservative planning bound: cached tables plus transient DP workspace,
    # arrays/string copies, Python object overhead and a fixed process allowance.
    per_worker = int(2*cells*8 + len(ply)*400 + strata*512 + 512*1024**2)
    usable = int(memory_gb*1024**3*.85 - len(ply)*400)
    count = min(requested,20,usable//per_worker)
    if count < 1:
        raise RuntimeError('Memory budget too small for one conditional-sampling worker')
    return {'requested_workers':requested,'effective_workers':count,'memory_budget_gb':memory_gb,
            'estimated_bytes_per_worker':per_worker,'conditional_table_cells':int(cells),
            'estimate_is_not_an_OS_memory_limit':True}


def run_batches(paths,session,state,digest,references,workers,draws=4999,batch=250):
    (state/'randomizations').mkdir(parents=True,exist_ok=True)
    preserved = checkpoints.preserve_incomplete(state,draws,batch)
    specs = [(a,min(a+batch,draws)) for a in range(0,draws,batch)]
    pending = [(a,z) for a,z in specs if checkpoints.authenticate(state,a,z,digest) is None]
    prior.log(f'C9_PLY_BATCHES complete={len(specs)-len(pending)} pending={len(pending)} workers={workers}')
    if pending:
        with ProcessPoolExecutor(max_workers=min(workers,len(pending)),mp_context=mp.get_context('spawn'),
             initializer=engine.initialize_worker,
             initargs=(str(paths['b1']),str(paths['prop']),str(session),str(paths['b2_script']))) as pool:
            futures = [pool.submit(checkpoints.worker,a,z,str(state),digest,references) for a,z in pending]
            for future in as_completed(futures):
                r = future.result()
                prior.log(f"C9_PLY_BATCH_COMPLETE {r['start']}:{r['stop_exclusive']} seconds={r['elapsed_seconds']:.1f}")
    receipts = []
    pieces = {k:[] for k in engine.blank_totals(1)}
    for a,z in specs:
        receipts.append(checkpoints.authenticate(state,a,z,digest))
        with np.load(checkpoints.paths(state,a,z)[0],allow_pickle=False) as saved:
            values = dict(saved)
        checkpoints.compare_reference(values,a,z,references)
        for key in pieces:
            pieces[key].append(values[key])
    return {key:np.concatenate(value) for key,value in pieces.items()},receipts,preserved


def summarize(observed,simulated,c9):
    rows = [];contrasts = []
    draws = len(simulated['original__all__later7_num'])
    for law in engine.LAWS:
        for rule in engine.RULES:
            prefix = law+'__'+rule+'__'
            rates = {};obs_rates = {}
            for category in ('same7','later7'):
                num = int(observed[prefix+category+'_num'][0]);den = int(observed[prefix+category+'_den'][0])
                null = c9.rate(simulated[prefix+category+'_num'],simulated[prefix+category+'_den'])
                finite = int(np.isfinite(null).sum())
                row = {'law':law,'rule':rule,'partition':category,'observed_numerator':num,'observed_denominator':den,
                       'observed_contributing_choosers':int(observed[prefix+category+'_users'][0]),
                       'observed_eligible_anchor_choosers':int(observed[prefix+'eligible_anchor_users'][0]),
                       'null_mean_denominator':float(simulated[prefix+category+'_den'].mean()),
                       'null_mean_contributing_choosers':float(simulated[prefix+category+'_users'].mean()),
                       'draws_requested':draws,'finite_null_rates':finite,
                       'classification':'original_reproduction' if law=='original' and rule=='all' else 'new_sensitivity'}
                if den <= 0 or finite != draws:
                    row.update(status='NOT_ESTIMABLE',reason='Requires positive observed denominator and finite rates in every null draw')
                else:
                    obs_rate = num/den;lo,up,p = c9.randomization_tail_p(obs_rate,null)
                    row.update(status='ESTIMATED',observed_rate_pct=100*obs_rate,null_mean_rate_pct=100*float(null.mean()),
                               excess_pp=100*(obs_rate-float(null.mean())),raw_randomization_p_two_sided=p,
                               lower_tail_plus_one=lo,upper_tail_plus_one=up,
                               null_distribution_p025_pct=100*float(np.quantile(null,.025)),
                               null_distribution_p975_pct=100*float(np.quantile(null,.975)),
                               null_quantiles_are_effect_confidence_intervals=False)
                    rates[category]=null;obs_rates[category]=obs_rate
                rows.append(row)
            contrast = {'law':law,'rule':rule,'contrast':'same_minus_later_excess_7d','classification':'new_sensitivity'}
            if len(rates) == 2:
                null = rates['same7']-rates['later7'];obs = obs_rates['same7']-obs_rates['later7']
                contrast.update(status='ESTIMATED',difference_in_excess_pp=100*(obs-float(null.mean())),
                                raw_randomization_p_two_sided=c9.randomization_tail_p(obs,null)[2],draws=draws)
            else:
                contrast.update(status='NOT_ESTIMABLE',reason='At least one component lacks full null support')
            contrasts.append(contrast)
    return rows,contrasts


def reproduce_baseline(observed,simulated,c9,reference,b2_public):
    obs = {k.removeprefix('baseline__'):v for k,v in observed.items() if k.startswith('baseline__')}
    sim = {k.removeprefix('baseline__'):v for k,v in simulated.items() if k.startswith('baseline__')}
    prior.validate_partitions(obs);prior.validate_partitions(sim)
    b2_gate = c9.b2_validation(obs,sim,b2_public)
    rows,_,_ = c9.summarize_c9(obs,sim)
    expected = {r['category']:r for r in csv.DictReader(io.StringIO(reference['c9_partition_components.csv'].decode()))}
    checked = []
    for row in rows:
        target = expected[row['category']]
        for key in ('observed_numerator','observed_denominator','observed_rate','null_mean_rate','randomization_p_two_sided'):
            if abs(float(row[key])-float(target[key])) > 1e-12:
                raise RuntimeError('Original C9 aggregate reproduction failed: '+row['category']+' '+key)
        checked.append({'category':row['category'],'status':'REPRODUCED',
                        'observed_numerator':row['observed_numerator'],'observed_denominator':row['observed_denominator'],
                        'excess_percentage_points':row['excess_percentage_points']})
    return {'status':'ORIGINAL_C9_AND_B2_REPRODUCED','draws':4999,'all_draw_arrays_equal':True,
            'C9_components':checked,'B2_summary':b2_gate}


def publish(parent,digest,config,preflight,support,rows,contrasts,reproduction,receipts,budget,elapsed):
    public = parent/digest[:12]
    parent.mkdir(parents=True,exist_ok=True)
    if public.exists():
        raise RuntimeError('Public destination already exists')
    staging = Path(tempfile.mkdtemp(prefix='report.partial_',dir=parent))
    prior.write_csv(staging/'c9_ply_components.csv',rows)
    prior.write_csv(staging/'c9_ply_session_contrasts.csv',contrasts)
    unsupported = sum(r['status']!='ESTIMATED' for r in rows+contrasts)
    summary = {'status':'C9_PLY_SENSITIVITIES_COMPLETE' if unsupported==0 else 'C9_PLY_COMPLETE_WITH_SUPPORT_WARNINGS',
               'version':VERSION,'config_sha256':digest,'sample_fingerprint':prior.SPEC['sample_fingerprint'],
               'created_utc':common.utc_now(),'unsupported_rows':unsupported,
               'laws':list(engine.LAWS),'outcome_rules':list(engine.RULES),'draws_per_law':4999,
               'original_confirmatory_estimate_changed':False,'new_sensitivities_added_to_Holm_family':False,
               'exact_original_C9_and_B2_reproduction':True,'runtime_seconds_this_invocation':elapsed,
               'session_cache_reused':True,'new_chronology_or_API_requests':False,'row_level_outputs_transferred':False,
               'remaining':['C13 if retained','global Holm reconciliation','C9 alternative session cutoffs and singleton appendix if retained','integrated manuscript updates'],
               'inference_limit':'New post-outcome sensitivity; fixed ply-band grant totals are descriptive conditioning, not a causal design.'}
    outputs = {'CONFIGURATION.json':config,'PREFLIGHT.json':preflight,'PLY_SUPPORT.json':support,
               'BASELINE_REPRODUCTION.json':reproduction,'CHECKPOINT_INVENTORY.json':{'batches':receipts},
               'RESOURCE_PLAN.json':budget,'summary.json':summary}
    for name,value in outputs.items():
        common.atomic_json(staging/name,value)
    shutil.copy2(PACKAGE/'ANALYSIS_SCOPE.md',staging/'ANALYSIS_SCOPE.md')
    shutil.copy2(PACKAGE/'authority/C9_PLY_SPEC.json',staging/'C9_PLY_SPEC.json')
    common.atomic_json(staging/'_SUCCESS.json',{'status':summary['status'],'config_sha256':digest,
                      'summary_sha256':common.sha256_file(staging/'summary.json')})
    common.write_manifest_tsv(staging);prior.verify_public(staging)
    os.replace(staging,public)
    return public


def collect(public,desktop,digest,label='RESULTS'):
    prior.verify_public(public)
    stamp = time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    archive = desktop/f'POOL_MAIN_C9_PLY_{label}_{stamp}_{digest[:12]}.zip'
    common.zip_tree(public,archive)
    sidecar = Path(str(archive)+'.sha256')
    common.atomic_text(sidecar,common.sha256_file(archive)+'  '+archive.name+'\n')
    prior.log('UPLOAD '+str(archive));prior.log('UPLOAD '+str(sidecar))


def run(args):
    started = time.monotonic()
    args.project_root = args.project_root.resolve()
    args.desktop.mkdir(parents=True,exist_ok=True)
    with exclusive(args.project_root) as base:
        with prior.heartbeat('Authenticating the sample, completed C9 cache and reference batches'):
            paths,session,c9,b2,reference,preflight,references = authenticate(args)
        config = {'version':VERSION,'specification':SPEC,'original_inputs':prior.SPEC,
                  'package_manifest_sha256':preflight['package']['manifest_sha256'],
                  'runtime':preflight['runtime'],'sample_fingerprint':prior.SPEC['sample_fingerprint']}
        digest = hashlib.sha256(common.canonical_json(config).encode()).hexdigest()
        state = base/digest[:12];state.mkdir(parents=True,exist_ok=True)
        envelope = {'config_sha256':digest,'config':config}
        path = state/'CONFIGURATION.json'
        if path.exists() and common.load_json(path) != envelope:
            raise RuntimeError('Restart configuration differs')
        common.atomic_json(path,envelope)
        parent = args.project_root/'output/pool_main_reanalysis_v100/c9_ply_v100'
        public = parent/digest[:12]
        if public.exists():
            prior.verify_public(public)
            if common.load_json(public/'_SUCCESS.json')['config_sha256'] != digest:
                raise RuntimeError('Completed public configuration differs')
            collect(public,args.desktop,digest)
            return
        try:
            with prior.heartbeat('Preparing ply support and observed counts'):
                _,data,probability,sessions,speed,ply,bands = engine.load_vectors(paths['b1'],paths['prop'],session,paths['b2_script'])
                support = engine.support(data,ply,bands,b2)
                observed = engine.observed(data,sessions,speed,ply,c9)
                checkpoints.validate_arrays(observed,1)
                budget = worker_budget(data,ply,b2,args.workers,args.memory_gb)
            common.atomic_json(state/'PLY_SUPPORT.json',support)
            common.atomic_json(state/'RESOURCE_PLAN.json',budget)
            del data,probability,sessions,speed,ply,bands
            prior.log('Resource plan: '+common.canonical_json(budget))
            with prior.heartbeat('Replaying original draws and drawing the ply-conditioned benchmark'):
                simulated,receipts,preserved = run_batches(paths,session,state,digest,references,budget['effective_workers'])
            reproduction = reproduce_baseline(observed,simulated,c9,reference,paths['b2_public'])
            reproduction['preserved_interrupted_checkpoint_pairs'] = preserved
            rows,contrasts = summarize(observed,simulated,c9)
            public = publish(parent,digest,envelope,preflight,support,rows,contrasts,reproduction,receipts,budget,time.monotonic()-started)
            collect(public,args.desktop,digest)
        except Exception as exc:
            failure = {'status':'C9_PLY_FAILED','created_utc':common.utc_now(),'config_sha256':digest,
                       'error':f'{type(exc).__name__}: {exc}','checkpoints_preserved':True}
            common.atomic_json(state/'LAST_FAILURE.json',failure)
            partial_parent = parent/'partial';partial_parent.mkdir(parents=True,exist_ok=True)
            partial = Path(tempfile.mkdtemp(prefix=digest[:12]+'_',dir=partial_parent))
            common.atomic_json(partial/'FAILURE.json',failure)
            common.atomic_json(partial/'CONFIGURATION.json',envelope)
            common.atomic_json(partial/'PREFLIGHT.json',preflight)
            common.write_manifest_tsv(partial)
            collect(partial,args.desktop,digest,'PARTIAL')
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10)
    p.add_argument('--memory-gb',type=float,default=12)
    args = p.parse_args()
    if not 1 <= args.workers <= 10 or not np.isfinite(args.memory_gb) or args.memory_gb < 1:
        p.error('workers must be 1–10 and memory-gb must be finite and at least 1')
    run(args)


if __name__ == '__main__':
    main()
