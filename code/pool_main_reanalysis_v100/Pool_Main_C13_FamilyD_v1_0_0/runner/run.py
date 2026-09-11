"""C13 full rebuild plus honest five-slot Campaign family-D reconciliation."""
from __future__ import annotations
import argparse
import contextlib
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from runner import bind,common,family_d,pipeline

ROOT=Path(__file__).resolve().parents[1]
VERSION='C13-FAMILY-D-1.0.0'


def log(message): print('['+common.utc_now()+'] '+message,flush=True)


@contextlib.contextmanager
def heartbeat(label):
    start=time.monotonic();stop=threading.Event()
    def report():
        while not stop.wait(30): log(f'{label}: still running, elapsed {(time.monotonic()-start)/60:.1f} min')
    worker=threading.Thread(target=report,daemon=True);worker.start()
    try: yield
    finally: stop.set();worker.join()


@contextlib.contextmanager
def exclusive(project):
    private=project/'derived/replication/pool_main_reanalysis_v100_PRIVATE'
    base=private/'c13_family_d_v100';base.mkdir(parents=True,exist_ok=True)
    shared=private/'c9_fresh_v100/runner.lock';shared.parent.mkdir(parents=True,exist_ok=True)
    with (base/'runner.lock').open('a+') as own:
        try: fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e: raise RuntimeError('A C13 job is already running') from e
        with shared.open('a+') as queue:
            while True:
                try:
                    fcntl.flock(queue,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    log('Waiting for the active C9, C9-ply or Patron job; checking in 30 seconds.')
                    time.sleep(30)
            yield base


def write_csv(path,rows):
    fields=list(dict.fromkeys(key for row in rows for key in row))
    buffer=io.StringIO(newline='')
    writer=csv.DictWriter(buffer,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    common.atomic_text(path,buffer.getvalue())


def verify_public(root):
    path=root/'REPORT_FILE_HASHES.tsv'
    rows=list(csv.DictReader(io.StringIO(path.read_text()),delimiter='\t'))
    expected={r['relative_path'] for r in rows}
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p!=path}
    if expected!=actual or len(expected)!=len(rows): raise RuntimeError('Public result inventory mismatch')
    for row in rows:
        p=(root/row['relative_path']).resolve()
        p.relative_to(root.resolve())
        if common.sha256_file(p)!=row['sha256'] or p.stat().st_size!=int(row['bytes']):
            raise RuntimeError('Public result hash mismatch: '+row['relative_path'])
        if p.suffix.lower() in ('.parquet','.npz','.npy','.duckdb','.pgn'):
            raise RuntimeError('Private data extension in public result')


def collect(public,desktop,digest,label='RESULTS'):
    verify_public(public)
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    archive=desktop/f'POOL_MAIN_C13_FAMILYD_{label}_{stamp}_{digest[:12]}.zip'
    common.zip_tree(public,archive)
    common.atomic_text(Path(str(archive)+'.sha256'),common.sha256_file(archive)+'  '+archive.name+'\n')
    log('UPLOAD '+str(archive));log('UPLOAD '+str(archive)+'.sha256')


def seal(public,summary,digest):
    common.atomic_json(public/'summary.json',summary)
    common.atomic_json(public/'_SUCCESS.json',{'status':summary['status'],'config_sha256':digest,
                                           'summary_sha256':common.sha256_file(public/'summary.json')})
    common.write_manifest_tsv(public);verify_public(public)


def family_files(public,table,receipt):
    public.mkdir(parents=True,exist_ok=True)
    write_csv(public/'family_D_reconciliation.csv',table)
    common.atomic_json(public/'FAMILY_D_RECONCILIATION.json',receipt)


def run(args):
    started=time.monotonic()
    args.project_root=args.project_root.resolve();args.desktop.mkdir(parents=True,exist_ok=True)
    package=common.verify_package_manifest()
    table,family=family_d.reconcile()
    log('Family D: C6 and C9 authenticated; C1/C2/C5 missing. Five slots retained.')
    public_base=args.project_root/'output/pool_main_reanalysis_v100/c13_family_d_v100'
    if args.holm_only:
        digest=hashlib.sha256(common.canonical_json({'family':family,'package':package['manifest_sha256']}).encode()).hexdigest()
        public=public_base/'holm'/digest[:12]
        if not public.exists():
            public.parent.mkdir(parents=True,exist_ok=True)
            staging=Path(tempfile.mkdtemp(prefix='holm.partial_',dir=public.parent))
            family_files(staging,table,family)
            shutil.copy2(ROOT/'ANALYSIS_SCOPE.md',staging/'ANALYSIS_SCOPE.md')
            seal(staging,{'status':family['status'],'C13_run':False,'family_size':5,
                         'guaranteed_rejections':family['guaranteed_rejections'],'missing_current_authorities':['C1','C2','C5']},digest)
            os.replace(staging,public)
        collect(public,args.desktop,digest,'HOLM')
        return
    with exclusive(args.project_root) as base:
        with heartbeat('Authenticating the certified pool-main panel'):
            sample=common.authenticate_sample(args.project_root/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE',
                                               verify_hashes=True,hash_workers=args.threads)
        if sample['fingerprint']!=family_d.FINGERPRINT: raise RuntimeError('Unexpected main sample')
        rendered,binding=bind.render()
        config={'version':VERSION,'sample_fingerprint':sample['fingerprint'],'package_manifest_sha256':package['manifest_sha256'],
                'runtime':common.environment_record(),'rendered_source_sha256':binding['rendered_sha256'],
                'family_evidence':family['source_reports'],'C13_model_attempts':19,'C13_role':'X',
                'support_threshold_other_fair_opportunities':5000,'original_Holm_family':list(family_d.MEMBERS)}
        digest=hashlib.sha256(common.canonical_json(config).encode()).hexdigest()
        state=base/digest[:12];state.mkdir(parents=True,exist_ok=True)
        public=public_base/digest[:12]
        envelope={'config_sha256':digest,'config':config}
        saved=state/'CONFIGURATION.json'
        if saved.exists() and common.load_json(saved)!=envelope: raise RuntimeError('Restart configuration differs')
        common.atomic_json(saved,envelope)
        if public.exists():
            verify_public(public)
            if common.load_json(public/'_SUCCESS.json')['config_sha256']!=digest: raise RuntimeError('Public configuration differs')
            collect(public,args.desktop,digest);return
        staging=state/'public_work';staging.mkdir(parents=True,exist_ok=True)
        family_files(staging,table,family)
        common.atomic_json(staging/'CONFIGURATION.json',envelope)
        common.atomic_json(staging/'SOURCE_BINDING.json',binding)
        common.atomic_json(staging/'PREFLIGHT.json',{'status':'C13_PREFLIGHT_READY','sample':common.compact_sample_lineage(sample),
                         'panel_file_hashes_recomputed':True,'threads':args.threads,'duckdb_memory_limit':args.memory_limit,
                         'simultaneous_models':1,'numpy_memory_has_no_hard_limit':True,'network_requests':0})
        shutil.copy2(ROOT/'ANALYSIS_SCOPE.md',staging/'ANALYSIS_SCOPE.md')
        c13,shared=bind.load_rendered(state/'execution_source',rendered)
        try:
            with heartbeat('C13 rebuild and checkpointed estimation'):
                result=pipeline.execute(c13,[r['path'] for r in sample['month_records']],state/'C13',staging/'C13',
                                        digest,args.threads,args.memory_limit)
            summary={'status':'C13_COMPLETE_FAMILY_D_RECONCILED_WITH_MISSING_AUTHORITIES',
                     'C13':result,'family_D_status':family['status'],'family_D_final_exact_complete':False,
                     'family_D_guaranteed_rejections':family['guaranteed_rejections'],
                     'family_D_missing_current_authorities':['C1','C2','C5'],
                     'sample_fingerprint':sample['fingerprint'],'runtime_seconds_this_invocation':time.monotonic()-started,
                     'private_row_level_outputs_transferred':False,'network_requests':0,'new_profile_reads':0,
                     'C13_causal_claim':False,'C13_in_confirmatory_family':False}
            seal(staging,summary,digest)
            public_base.mkdir(parents=True,exist_ok=True)
            os.replace(staging,public)
            collect(public,args.desktop,digest)
        except Exception as exc:
            failure={'status':'C13_RUN_FAILED_WITH_CHECKPOINTS_PRESERVED','config_sha256':digest,
                     'created_utc':common.utc_now(),'error':f'{type(exc).__name__}: {exc}',
                     'family_D_status':family['status'],'private_state_preserved':True}
            common.atomic_json(state/'LAST_FAILURE.json',failure)
            partial_parent=public_base/'partial';partial_parent.mkdir(parents=True,exist_ok=True)
            partial=Path(tempfile.mkdtemp(prefix=digest[:12]+'_',dir=partial_parent))
            shutil.copytree(staging,partial,dirs_exist_ok=True)
            completed=[]
            for path in sorted((state/'C13/model_checkpoints').glob('*.json')):
                record=common.load_json(path)
                completed.append({'model':record['request']['label'],'rows':record['rows'],'attempt':record['attempt']})
            common.atomic_json(partial/'COMPLETED_MODEL_ATTEMPTS.json',{'attempts':completed,'C13_complete':False})
            common.atomic_json(partial/'FAILURE.json',failure)
            common.write_manifest_tsv(partial)
            collect(partial,args.desktop,digest,'PARTIAL')
            raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--threads',type=int,default=10)
    p.add_argument('--memory-limit',default='8GB')
    p.add_argument('--holm-only',action='store_true',help='Reconcile aggregate reports only; do not run C13 or read private data')
    args=p.parse_args()
    if not args.project_root.is_dir(): p.error('Connect the project volume first')
    if not 1<=args.threads<=10: p.error('threads must be 1 to 10')
    if not re.fullmatch(r'[1-9][0-9]*(?:\.[0-9]+)?(?:GB|MB)',args.memory_limit): p.error('memory-limit must be a positive GB or MB quantity')
    run(args)


if __name__=='__main__': main()
