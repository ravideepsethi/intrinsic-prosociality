#!/usr/bin/env python3
from common import *
from bind import bind
from prepare import prepare
from models import comparisons
from dose import dose_models
from report import assemble_report
from restart import seed_hash_cache,reuse_focal
import argparse,fcntl,traceback

def main():
    p=argparse.ArgumentParser(description='Offline receipt mechanisms diagnostics using reviewed Run 2 caches')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=6)
    p.add_argument('--memory-gb',type=float,default=10)
    a=p.parse_args()
    if a.workers<1 or a.memory_gb<4:p.error('At least one worker and 4 GB memory are required')
    threads=min(10,a.workers);no_network();verify_package();a.project_root=a.project_root.expanduser().resolve()
    definition=dict(version=VERSION,package_sha256=sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),
        parents=read(PACKAGE/'authority/parents.json'),authors=list(AUTHORS),
        primary_frame='new_phase25',followup_days=90,nominal_ci=.95,illustrative_margins_pp=[.1,.25])
    key=digest(definition);work=a.project_root/'derived/replication/receipt_mechanisms_v100_PRIVATE'/key[:12]
    work.mkdir(parents=True,exist_ok=True)
    with (work/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This package is already running')
        write(work/'config.json',definition);write(a.desktop/'RECEIPT_MECHANISMS_LATEST_PRIVATE.json',dict(root=str(work),run_key=key))
        log(f'Workers up to {threads}; DuckDB memory budget {a.memory_gb:g} GB; no network or engine work')
        started=time.monotonic()
        try:
            seed_hash_cache(a.project_root,work)
            with heartbeat('Verifying the reviewed source lineage'):binding=bind(a.project_root,work)
            reuse_focal(a.project_root,work,binding,key)
            paths=prepare(binding,work,key,threads,a.memory_gb)
            assemble_report(work,a.desktop,key,'COVERAGE_COMPLETE_MODELS_PENDING')
            comparisons(paths,work,key,threads,a.memory_gb)
            assemble_report(work,a.desktop,key,'COMPARISONS_COMPLETE_DOSE_PENDING')
            blocked=[read(Path(p)/'secondary_status.json') for p in paths if read(Path(p)/'secondary_status.json')['status']!='VERIFIED']
            if blocked:
                write(work/'secondary_blocked.json',dict(status='BLOCKED',months=blocked,
                    rows_removed=0,partial_cohort_dose_fit_run=False))
                assemble_report(work,a.desktop,key,'PRIMARY_COMPLETE_SECONDARY_BLOCKED')
                log('PRIMARY COMPARISONS COMPLETE. Secondary dose models withheld; upload the report for the exact mismatch audit.')
            else:
                dose_models(paths,work,key,threads,a.memory_gb)
                assemble_report(work,a.desktop,key,'COMPLETE')
            log(f'Finished in {(time.monotonic()-started)/60:.1f} minutes. Upload the REPORT zip for interpretation.')
        except Exception as e:
            write(work/'FAILURE_PRIVATE.json',dict(error=str(e),traceback=traceback.format_exc()))
            assemble_report(work,a.desktop,key,'BLOCKED',failure=str(e));raise

if __name__=='__main__':main()
