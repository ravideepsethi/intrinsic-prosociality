#!/usr/bin/env python3
"""Offline remaining Patron analyses on the authenticated new main sample."""
from __future__ import annotations
import argparse, contextlib, csv, fcntl, hashlib, io, json, os, platform, shutil, sys
import tempfile, threading, time, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
import duckdb, numpy as np, pandas as pd, pyarrow
from source import wave3b1_helpers as h
from source import postcertification_v100 as add
from runner import families, opportunity, dyad

VERSION='3B2-1.0.1'
PRIOR_CONFIG='9a64f1f9b8f87d62f10a5584937c44909a7a262601c2d6c7ec1751c7b67205bb'
PRIOR_REPORT_SHA='34b71da5e684ee07cf1abfbb9d9406dbc3601db20ff099e2737574790f0a5616'
q=h.q


def verify_prior_report(destination):
    path=ROOT/'evidence/WAVE3B1_RESULTS.zip'
    h.eq(h.auth.sha256_file(path),PRIOR_REPORT_SHA,'Wave3B1 archive SHA')
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as z:
        h.eq(z.testzip(),None,'Wave3B1 CRC')
        manifest=next(n for n in z.namelist() if n.endswith('/REPORT_FILE_HASHES.tsv'))
        prefix=manifest.rsplit('/',1)[0]+'/'
        listed=list(csv.DictReader(io.StringIO(z.read(manifest).decode()),delimiter='\t'))
        for row in listed:
            rel=row['relative_path']; target=destination/rel
            if Path(rel).is_absolute() or '..' in Path(rel).parts: raise RuntimeError('Unsafe report path')
            data=z.read(prefix+rel)
            h.eq(len(data),int(row['bytes']),'Wave3B1 report bytes')
            h.eq(hashlib.sha256(data).hexdigest(),row['sha256'],'Wave3B1 report member SHA')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    config=h.auth.load_json(destination/'CONFIGURATION.json')
    h.eq(hashlib.sha256(h.auth.canonical_json(config).encode()).hexdigest(),PRIOR_CONFIG,'Wave3B1 config SHA')
    status=h.auth.load_json(destination/'WAVE3B1_RUN_STATUS.json')
    h.eq(status['status'],'PATRON_WAVE3B1_CORE_ESTIMATES_COMPLETE','Wave3B1 completion')
    return config,status


@contextlib.contextmanager
def exclusive_run(base,project):
    base.mkdir(parents=True,exist_ok=True)
    with (base/'RUN.lock').open('a+') as own:
        try: fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e: raise RuntimeError('Patron Wave3B2 is already running') from e
        c9=project/'derived/replication/pool_main_reanalysis_v100_PRIVATE/c9_fresh_v100/runner.lock'
        c9.parent.mkdir(parents=True,exist_ok=True)
        with c9.open('a+') as other:
            while True:
                try: fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    h.log('WAITING_FOR_C9: Patron has not started computing. Checking again in 30 seconds.')
                    time.sleep(30)
            yield


def authenticate(args,base):
    package=h.auth.verify_package_manifest(ROOT)
    prior_config,prior_status=verify_prior_report(base/'prior_public_reference')
    sample=h.auth.authenticate_sample(args.project_root/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE',
        hash_workers=args.hash_workers)
    snapshot=h.prior.authenticate_snapshot(args.project_root)
    wave3a,wave3a_status=h.authenticate_wave3a(args.project_root)
    old=args.project_root/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3b1_patron'/PRIOR_CONFIG[:12]
    h.eq(h.auth.load_json(old/'CONFIGURATION.json'),prior_config,'local Wave3B1 configuration')
    receipt=h.prior.read_checkpoint(old/'design',PRIOR_CONFIG)
    h.eq(receipt['status'],'CHECKPOINT_COMPLETE','Wave3B1 design checkpoint')
    h.eq(h.auth.load_json(old/'design/preoutcome_support_receipt.json'),
         h.auth.load_json(base/'prior_public_reference/preoutcome_support_receipt.json'),'Wave3B1 design support')
    h.eq(sample['fingerprint'],prior_status['sample']['fingerprint'],'prior/new sample fingerprint')
    return {'package':package,'sample':sample,'snapshot':snapshot,'wave3a':wave3a,
            'wave3a_status':wave3a_status,'design':old/'design/chooser_design_features_private.parquet',
            'design_receipt':receipt,'reference':base/'prior_public_reference'}


def build_inputs(directory,args,inputs):
    db=h.prior.connect(directory/'work.duckdb',args,directory/'spill')
    try:
        acquisition=inputs['wave3a']/'matching/acquisition_users_private.parquet'
        design=inputs['design'];snapshot=inputs['snapshot']
        columns=['query_index','acquisition_role','matched_kind_chooser_id','control_slot','match_cell',
                 'total_opps','total_kind_count','fair_opps','fair_kind_count','clearly_worse_opps','clearly_worse_kind_count']
        condition=' OR '.join(f'a.{c} IS DISTINCT FROM d.{c}' for c in columns)
        qa=h.records(db,f"""SELECT count(*) AS rows,
          count(*) FILTER(WHERE a.username_norm IS NULL OR d.username_norm IS NULL OR {condition}) AS mismatches
          FROM read_parquet({q(acquisition)}) a FULL JOIN read_parquet({q(design)}) d USING(username_norm)""")[0]
        target_rows=inputs['wave3a_status']['checkpoint_receipts']['matching']['summary']['target_users']
        h.eq(qa,{'rows':target_rows,'mismatches':0},'design versus authenticated new matches')
        h.verify_new_cache(db,design,target_rows)
        h.models.outcome_qa(db,snapshot,fixture=False)
        bridge=directory/'new_target_august_outcomes_private.parquet'
        db.execute(f"""COPY (SELECT a.*,coalesce(s.returned,false) AS returned,s.patron,
          s.queried_at_utc,(s.username_norm IS NOT NULL) AS august_planned
          FROM read_parquet({q(acquisition)}) a LEFT JOIN read_parquet({q(snapshot)}) s USING(username_norm)
          ORDER BY a.query_index) TO {q(bridge)} (FORMAT PARQUET,COMPRESSION ZSTD)""")
        coverage=h.records(db,f"""SELECT count(*) targets,count(*) FILTER(WHERE returned) returned,
          count(*) FILTER(WHERE NOT august_planned) never_queried,
          count(*) FILTER(WHERE august_planned AND NOT returned) nonreturned,
          count(*) FILTER(WHERE (returned AND patron IS NULL) OR (NOT returned AND patron IS NOT NULL)) bad_outcomes,
          count(*) FILTER(WHERE returned AND patron) patrons FROM read_parquet({q(bridge)})""")[0]
        h.eq(coverage['targets'],1_105_919,'new target count')
        h.eq(coverage['returned'],1_105_634,'August returned new targets')
        h.eq(coverage['never_queried'],122,'never queried in August')
        h.eq(coverage['nonreturned'],163,'August nonreturns')
        h.eq(coverage['bad_outcomes'],0,'missing outcome semantics')
        paths='['+','.join(q(m['path']) for m in inputs['sample']['month_records'])+']'
        bins=directory/'five_bin_counts_private.parquet'
        db.execute(f"""COPY (SELECT p.chooser_username_norm AS username_norm,
           p.engine_fairness_bin AS fairness_bin,count(*)::BIGINT AS opportunities,
           sum(p.kind_draw::INTEGER)::BIGINT AS kind_draws
           FROM read_parquet({paths},union_by_name=true,hive_partitioning=false) p
           SEMI JOIN read_parquet({q(acquisition)}) a ON p.chooser_username_norm=a.username_norm
           GROUP BY 1,2 ORDER BY 1,2) TO {q(bins)} (FORMAT PARQUET,COMPRESSION ZSTD)""")
        mismatch=db.execute(f"""WITH b AS (SELECT username_norm,sum(opportunities) n,sum(kind_draws) k
          FROM read_parquet({q(bins)}) GROUP BY 1)
          SELECT count(*) FROM b FULL JOIN read_parquet({q(acquisition)}) a USING(username_norm)
          WHERE n IS DISTINCT FROM total_opps OR k IS DISTINCT FROM total_kind_count""").fetchone()[0]
        h.eq(mismatch,0,'five-bin counts reproduce all new target histories')
        h.save_json(directory/'INPUT_QA.json',{'design':qa,'coverage':coverage,'bin_partition_mismatch':mismatch})
    finally: db.close()
    (directory/'work.duckdb').unlink(missing_ok=True);shutil.rmtree(directory/'spill',ignore_errors=True)
    return {'target_users':target_rows,'returned':coverage['returned'],'missing':285}


def with_database(directory,args,function):
    db=h.prior.connect(directory/'work.duckdb',args,directory/'spill')
    try: return function(db)
    finally:
        db.close();(directory/'work.duckdb').unlink(missing_ok=True)
        shutil.rmtree(directory/'spill',ignore_errors=True)


def collect(args,state,digest,config,completed,error=None):
    output=args.project_root/'output/pool_main_reanalysis_v100/wave3b2_patron'/digest[:12]
    output.mkdir(parents=True,exist_ok=True)
    not_estimable=sum(v.get('summary',{}).get('not_estimable_contrasts',0) for v in completed.values())
    label=('PATRON_WAVE3B2_COMPLETE_WITH_ESTIMABILITY_WARNINGS' if not_estimable else 'PATRON_WAVE3B2_REMAINING_COMPLETE')
    status={'status':label if error is None else 'PATRON_WAVE3B2_INCOMPLETE',
            'version':VERSION,'config_sha256':digest,'created_utc':h.auth.utc_now(),
            'completed':completed,'error':error,'snapshot_cohort':'August only',
            'paper_assembly_remaining':True,'timing_churn_not_estimated':True,
            'not_estimable_contrasts':not_estimable}
    h.save_json(output/'WAVE3B2_RUN_STATUS.json',status)
    h.save_json(output/'CONFIGURATION.json',config)
    shutil.copy2(ROOT/'ANALYSIS_SCOPE.md',output/'ANALYSIS_SCOPE.md')
    shutil.copy2(ROOT/'authority/SOURCE_BINDINGS.json',output/'SOURCE_BINDINGS.json')
    for name in completed:
        directory=state/name
        target=output/name;target.mkdir(parents=True,exist_ok=True)
        # Public outputs are written to top-level CSV/JSON only. No private tables.
        for p in sorted(directory.iterdir()):
            if p.is_file() and p.suffix in {'.csv','.json'} and p.name!='CHECKPOINT.json':
                shutil.copy2(p,target/p.name)
    manifest=output/'REPORT_FILE_HASHES.tsv'
    with manifest.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['relative_path','bytes','sha256'],delimiter='\t');writer.writeheader()
        for p in sorted(output.rglob('*')):
            if p.is_file() and p!=manifest:
                writer.writerow({'relative_path':p.relative_to(output).as_posix(),'bytes':p.stat().st_size,'sha256':h.auth.sha256_file(p)})
    args.transfer_dir.mkdir(parents=True,exist_ok=True)
    suffix='RESULTS' if error is None else 'PARTIAL'
    filename=f'POOL_MAIN_PATRON_WAVE3B2_{suffix}_{time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())}_{digest[:12]}.zip'
    path=args.transfer_dir/filename;temporary=path.with_suffix('.zip.partial')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(output.rglob('*')):
            if p.is_file(): z.write(p,filename[:-4]+'/'+p.relative_to(output).as_posix())
    with zipfile.ZipFile(temporary) as z: h.eq(z.testzip(),None,'result CRC')
    os.replace(temporary,path)
    path.with_name(path.name+'.sha256').write_text(h.auth.sha256_file(path)+'  '+path.name+'\n')
    h.log('UPLOAD '+str(path));h.log('UPLOAD '+str(path)+'.sha256')
    return path


def run(args):
    os.umask(0o077)
    args.project_root=args.project_root.expanduser().resolve();args.transfer_dir=args.transfer_dir.expanduser().resolve()
    if not args.project_root.is_dir(): raise RuntimeError('Connect the project volume: '+str(args.project_root))
    if not 1<=args.threads<=10 or not 1<=args.hash_workers<=10: raise RuntimeError('Use 1-10 threads/hash workers')
    base=args.project_root/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3b2_patron'
    with exclusive_run(base,args.project_root):
        if shutil.disk_usage(args.project_root).free<80*(1024**3):
            raise RuntimeError('Allow at least 80 GiB free on the project volume for the private cache and spill files')
        inputs=authenticate(args,base)
        config={'version':VERSION,'package_manifest_sha256':inputs['package']['manifest_sha256'],
          'sample_fingerprint':inputs['sample']['fingerprint'],'prior_config_sha256':PRIOR_CONFIG,
          'prior_report_sha256':PRIOR_REPORT_SHA,'design_sha256':h.auth.sha256_file(inputs['design']),
          'snapshot_sha256':h.prior.SNAPSHOT_SHA,'threads':args.threads,'memory_limit':args.memory_limit,
          'scope_sha256':h.auth.sha256_file(ROOT/'ANALYSIS_SCOPE.md'),
          'runtime':{'python':platform.python_version(),'duckdb':duckdb.__version__,'numpy':np.__version__,
                     'pandas':pd.__version__,'pyarrow':pyarrow.__version__}}
        digest=hashlib.sha256(h.auth.canonical_json(config).encode()).hexdigest()
        state=base/digest[:12];state.mkdir(parents=True,exist_ok=True)
        h.save_json(state/'CONFIGURATION.json',config)
        completed={};progress={'stage':'inputs','started':time.monotonic()};stop=threading.Event()
        def heartbeat():
            while not stop.wait(60):
                h.log(f"STILL_RUNNING stage={progress['stage']} elapsed_minutes={(time.monotonic()-progress['started'])/60:.1f}")
        worker=threading.Thread(target=heartbeat,daemon=True);worker.start()
        def stage(name,function):
            progress.update(stage=name,started=time.monotonic())
            directory,receipt=h.prior.checkpoint(state,name,digest,function)
            completed[name]={'elapsed_seconds':receipt['elapsed_seconds'],'summary':receipt['summary'],
                             'receipt_sha256':h.auth.sha256_file(directory/'CHECKPOINT.json')}
            h.save_json(state/'PROGRESS.json',{'current_stage':name,'completed':completed,'status':'RUNNING'})
            return directory
        try:
            cached=stage('inputs',lambda d:build_inputs(d,args,inputs))
            bridge=cached/'new_target_august_outcomes_private.parquet'
            def rematch_stage(directory):
                def estimate(db):
                    frame=families.returned_frame(db,inputs['design'],inputs['snapshot'])
                    data,main,groups=families.core_reproduction(frame,state,digest,inputs['reference'],directory)
                    del data,frame
                    return families.rematches(main,groups,state,digest,directory)
                return with_database(directory,args,estimate)
            stage('rematches',rematch_stage)
            stage('postcertification',lambda d:with_database(d,args,lambda db:families.postcertification(
              db,inputs['design'],inputs['snapshot'],cached/'five_bin_counts_private.parquet',state,digest,d)))
            def cache_stage(directory):
                qa=with_database(directory,args,lambda db:opportunity.build_cache(db,
                   [m['path'] for m in inputs['sample']['month_records']],bridge,directory/'opportunity_cells_private.parquet'))
                h.save_json(directory/'OPPORTUNITY_CACHE_QA.json',qa);return qa
            cells=stage('opportunity_cache',cache_stage)/'opportunity_cells_private.parquet'
            stage('opportunity',lambda d:with_database(d,args,lambda db:opportunity.fit_families(
                db,cells,bridge,state,digest,d,ply=False)))
            stage('ply',lambda d:with_database(d,args,lambda db:opportunity.fit_families(
                db,cells,bridge,state,digest,d,ply=True)))
            stage('dyad',lambda d:dyad.run(args,inputs['sample'],bridge,state,digest,d))
            h.eq(h.auth.sha256_file(inputs['snapshot']),h.prior.SNAPSHOT_SHA,'August snapshot unchanged')
            result=collect(args,state,digest,config,completed)
            h.save_json(state/'PROGRESS.json',{'status':'COMPLETE','completed':completed,'result':str(result)})
        except BaseException as exc:
            if completed:
                try: collect(args,state,digest,config,completed,error=f'{type(exc).__name__}: {exc}')
                except Exception as report_exc: h.log('Partial report collection also failed: '+str(report_exc))
            raise
        finally: stop.set();worker.join(timeout=2)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,required=True)
    p.add_argument('--transfer-dir',type=Path,required=True)
    p.add_argument('--threads',type=int,default=8)
    p.add_argument('--hash-workers',type=int,default=10)
    p.add_argument('--memory-limit',default='12GB')
    run(p.parse_args())

if __name__=='__main__': main()
