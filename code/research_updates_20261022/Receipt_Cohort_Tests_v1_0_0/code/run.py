#!/usr/bin/env python3
from common import *
from cache import bind_cache,open_data,load_scope
from analysis import audit,run_model
from iv import run_iv
from report import assemble
import argparse,fcntl,traceback,gc

def save_audit(d,root,scope,key):
    out=Path(root)/'audits'/scope;out.mkdir(parents=True,exist_ok=True)
    if checkpoint_ok(out,key):return
    with heartbeat('Sample and stake audit: '+scope):
        sample,balance,info=audit(d,scope);csvwrite(out/'sample.csv',sample);csvwrite(out/'balance.csv',balance);write(out/'summary.json',info);finish(out,key)

def execute(project,desktop,workers,memory,skip_iv=False,authority=None):
    definition=dict(version=VERSION,package_sha256=sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),
      parent=authority or read(PACKAGE/'authority/parent.json'),skip_iv=skip_iv)
    key=digest(definition);work=Path(project)/'derived/replication/receipt_cohort_tests_v100_PRIVATE'/key[:12];work.mkdir(parents=True,exist_ok=True)
    with (work/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This exact run is already active')
        write(work/'config.json',definition);write(Path(desktop)/'RECEIPT_COHORT_TESTS_LATEST_PRIVATE.json',dict(root=str(work),run_key=key))
        start=time.monotonic();c=None
        try:
            log(f'Up to {workers} DuckDB workers, {memory:g} GB requested budget; dense models run one at a time')
            binding=bind_cache(project,work,workers,authority);c=conn(work/'spill',workers,min(4,max(1,memory*.30)))
            counts=open_data(c,binding);log(f'Verified {counts["rows"]:,} exposures and {counts["grants"]:,} grants')
            with heartbeat('Load frozen receipt cohort'):d=load_scope(c,'all_rd')
            save_audit(d,work,'all_rd',key);assemble(work,desktop,key,'AUDIT_COMPLETE_MODELS_PENDING')
            jobs=[('joint','joint'),('terciles','terciles'),('drop_benefit','drop_benefit'),('drop_cost','drop_cost')]
            for i,(name,mode) in enumerate(jobs,1):
                run_model(c,d,work/'models'/name,name,key,mode)
                elapsed=time.monotonic()-start;log(f'OLS models {i}/6; elapsed {elapsed/60:.1f} min; model ETA approx {elapsed/max(i,1)*(6-i)/60:.1f} min, IV follows')
                assemble(work,desktop,key,'MODELS_IN_PROGRESS')
            del d;gc.collect()
            for i,scope in enumerate(('both_rd_le_110','within'),5):
                d=load_scope(c,scope);save_audit(d,work,scope,key);name='rd110' if i==5 else 'within'
                run_model(c,d,work/'models'/name,name,key,within=(scope=='within'));del d;gc.collect()
                log(f'OLS models {i}/6 complete; continuing automatically');assemble(work,desktop,key,'OLS_COMPLETE_IV_PENDING' if i==6 else 'MODELS_IN_PROGRESS')
            if skip_iv:
                p=work/'secondary_iv';p.mkdir(exist_ok=True);write(p/'summary.json',dict(status='SKIPPED_BY_OPTION'));csvwrite(p/'estimates.csv',[dict(status='SKIPPED_BY_OPTION')]);finish(p,key)
            else:
                d=load_scope(c,'all_rd');run_iv(c,d,binding,project,work,work/'secondary_iv',key);del d;gc.collect()
            result=assemble(work,desktop,key,'COMPLETE');log(f'RECEIPT_COHORT_TESTS_COMPLETE in {(time.monotonic()-start)/60:.1f} minutes');return work,result
        except Exception as e:
            write(work/'FAILURE_PRIVATE.json',dict(error=str(e),traceback=traceback.format_exc()));assemble(work,desktop,key,'BLOCKED',str(e));raise
        finally:
            if c:c.close()

def main():
    p=argparse.ArgumentParser(description='Cached receipt-cohort position and stake heterogeneity tests')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=10);p.add_argument('--skip-iv',action='store_true')
    a=p.parse_args()
    if not 1<=a.workers<=10 or a.memory_gb<8:p.error('Use 1–10 workers and at least 8 GB for the dense model workspace')
    a.project_root=a.project_root.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve();a.desktop.mkdir(parents=True,exist_ok=True)
    verify_package();no_network();execute(a.project_root,a.desktop,a.workers,a.memory_gb,a.skip_iv)

if __name__=='__main__':main()
