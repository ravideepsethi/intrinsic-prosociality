#!/usr/bin/env python3
from common import *
import argparse,fcntl,traceback,gc,platform
import data,diagnostics,mixture,covariate_mixture,hazard,receipt,extensions,report

def execute(project,desktop,workers,memory,diagnostics_only=False):
    cfg=read(ROOT/'config.json');definition=dict(specification=cfg,package_sha256=sha(ROOT/'PACKAGE_MANIFEST.sha256'))
    optional=Path(project)/'derived/replication/taxonomy_extended_inputs/EXTENDED_INPUTS.json'
    definition['extended_input_manifest_sha256']=sha(optional) if optional.exists() else None
    key=digest(definition);work=Path(project)/'derived/replication/kindness_taxonomy_v100_PRIVATE'/key[:12];work.mkdir(parents=True,exist_ok=True)
    Path(desktop).mkdir(parents=True,exist_ok=True);stages={};c=None;start=time.monotonic()
    with (work/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This exact run is already running')
        write(work/'config.json',definition);write(Path(desktop)/'KINDNESS_TAXONOMY_LATEST_PRIVATE.json',dict(root=str(work),run_key=key))
        write(work/'runtime_PRIVATE.json',dict(python=sys.version,numpy=np.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__,platform=platform.platform(),workers=workers,memory_gb=memory))
        def run(name,fn):
            stages[name]=stage(work,name,key,fn);report.assemble(work,desktop,key,'RUNNING',stages)
        try:
            binding=data.bind(project,work,workers);c=conn(work/'spill',workers,min(4,memory*.35))
            paths=data.build(c,binding,work,key,cfg);profile=data.profiles(c,project,work,key)
            run('00_inventory',lambda f:data.optional_inventory(project,f))
            run('00_markers',lambda f:data.markers(c,work,f,profile))
            run('E',lambda f:diagnostics.early(c,f,cfg));run('G',lambda f:diagnostics.rule_change(c,f,cfg))
            if diagnostics_only:
                report.assemble(work,desktop,key,'DIAGNOSTICS_COMPLETE_CORE_NOT_RUN',stages,plots=True);return
            data.histories(c,work,key,cfg)
            run('C1',lambda f:hazard.run(c,work,f,cfg))
            try:d,meta=receipt.prepare(c,project,work,workers)
            except Unavailable as e:
                for name in ('C23','H_deciles','H_dynamic'):stages[name]=dict(status='BLOCKED_INPUT',reason=str(e))
            else:
                write(work/'RECEIPT_BINDING_PRIVATE.json',meta)
                run('C23',lambda f:receipt.conversion(c,d,f));run('H_deciles',lambda f:receipt.deciles(c,d,f));run('H_dynamic',lambda f:receipt.dynamics(c,d,f));del d;gc.collect()
            run('B1',lambda f:mixture.run_b1(c,work,f,key,cfg))
            run('B3',lambda f:mixture.validate(c,work,f,cfg,work/'B1'))
            run('B2',lambda f:covariate_mixture.run(c,work,f,key,cfg,work/'B1'));gc.collect()
            extras,extra_meta=extensions.load(project,work)
            run('F',lambda f:extensions.waiting(c,f,extras,cfg));run('D1',lambda f:extensions.desert(c,f,extras,cfg))
            run('D2',lambda f:extensions.accuracy(c,f,extras,cfg))
            report.assemble(work,desktop,key,'COMPLETE_LOCAL',stages,plots=True)
            log(f'KINDNESS_TAXONOMY_COMPLETE_LOCAL in {(time.monotonic()-start)/3600:.2f} hours')
        except Exception as e:
            write(work/'FAILURE_PRIVATE.json',dict(error=str(e),traceback=traceback.format_exc()))
            report.assemble(work,desktop,key,'FAILED',stages,str(e));raise
        finally:
            if c:c.close()

def main():
    p=argparse.ArgumentParser(description='Frozen exploratory taxonomy, first-grant and receipt diagnostics; offline, checkpointed')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=10)
    p.add_argument('--stop-after-diagnostics',action='store_true')
    a=p.parse_args()
    if not 1<=a.workers<=10 or a.memory_gb<8:p.error('Use 1–10 workers and at least 8 GB')
    manifest_check();offline();execute(a.project_root.expanduser().resolve(),a.desktop.expanduser().resolve(),a.workers,a.memory_gb,a.stop_after_diagnostics)

if __name__=='__main__':main()
