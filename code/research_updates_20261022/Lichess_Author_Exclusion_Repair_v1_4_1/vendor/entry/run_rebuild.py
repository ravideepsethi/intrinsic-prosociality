#!/usr/bin/env python3
"""One resumable command for the all-time-five entry and placebo migration."""
from rebuild_common import *
import argparse,fcntl,subprocess,signal,traceback,zipfile,platform,contextlib
STAGES=('authenticate','candidates','chronology','metadata_audit','metadata','frames','models')
PROGRESS=dict(authenticate=5,candidates=25,chronology=35,metadata_audit=40,metadata=50,frames=75,models=100)

@contextlib.contextmanager
def prior_runs_stopped(project,current):
    """Hold read locks so a prior runner cannot compete for the same RAM/drive."""
    with contextlib.ExitStack() as stack:
        base=Path(project)/'derived/replication'
        for lockpath in sorted(base.glob('alltime_entry_placebo_v10*_PRIVATE/*/RUN.lock')):
            if lockpath.parent.resolve()==Path(current).resolve():continue
            lock=stack.enter_context(lockpath.open('r'))
            try:fcntl.flock(lock.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('An earlier entry/placebo run is still active: '+str(lockpath.parent)+
                    '. Press Ctrl+C in that terminal and wait for its prompt, then rerun this command. Completed files are retained.')
        yield

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11.)
    p.add_argument('--r12-root',type=Path);p.add_argument('--r9-root',type=Path);p.add_argument('--local-plan',type=Path)
    p.add_argument('--reuse-run',type=Path,help='Completed v1.0.0 candidates and chronology scan checkpoints; defaults to the reviewed 56739829cf4a run.')
    p.add_argument('--reuse-chronology',type=Path,help='Completed v1.0.2 chronology; defaults to the reviewed 25d22fd1d9e9 run. Missing or changed checkpoints stop; no rebuild fallback.')
    p.add_argument('--audit-only',action='store_true',help='Complete local candidate and chronology work, report metadata needs, then stop before new requests.')
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--_stage',choices=STAGES,help=argparse.SUPPRESS)
    return p

def verify():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);p=(ROOT/name).resolve()
        require(p.is_relative_to(ROOT),'Unsafe package manifest member');require(sha(p)==digest,'Package changed: '+name)
    return sha(ROOT/'PACKAGE_MANIFEST.sha256')

def export(a,run,conf,state,progress,error=None):
    report=run/'report';report.mkdir(exist_ok=True)
    status='COMPLETE' if progress==100 and not error else ('STOPPED' if error else 'IN_PROGRESS')
    if a.audit_only and state.get('metadata',{}).get('status')=='AUDIT_COMPLETE':status='METADATA_AUDIT_COMPLETE_REBUILD_PENDING'
    save(report/'STATUS.json',dict(status=status,version=VERSION,configuration_sha256=conf,progress_percent=progress,
        stages=state,error=error,entry_and_ordinary_populations_rebuilt=(status=='COMPLETE'),
        receipt_primary_changed=False,rule=RULE))
    plan=load(run/'PRIVATE/MODEL_PLAN.json') if (run/'PRIVATE/MODEL_PLAN.json').exists() else []
    for tag in ('F','O'):
        for legacy in (False,True):
            label=('legacy_' if legacy else 'totalfive_')+tag;rows=[];balance=[];joint=[]
            for job in plan:
                p=Path(job['output'])/'result.json'
                if job['sample']!=label or not p.exists():continue
                result=load(p);rows += [r9.scaled(x,SD) for x in result['estimates']];balance+=result['balance'];joint+=result['joint_balance']
            if rows:
                family='entry' if tag=='F' else 'ordinary_placebo';prefix='legacy_' if legacy else ''
                csv_out(report/(prefix+family+'.csv'),rows)
                csv_out(report/(prefix+family+'_balance.csv'),balance);csv_out(report/(prefix+family+'_joint_balance.csv'),joint)
    paths=run/'PRIVATE/contrasts'
    for label in ('new_receipt_minus_new_ordinary','F_new_minus_old','O_new_minus_old'):
        rows=[]
        for p in sorted(paths.glob(label+'__*/result.json')):rows += [r9.scaled(x,SD) for x in load(p)]
        if rows:csv_out(report/(label+'.csv'),rows)
    # Original equivalence margin expressed on the common reference SD.
    p=report/'ordinary_placebo.csv'
    if p.exists():
        import csv
        rows=[];margin=.015*SD/.0594
        for row in csv.DictReader(p.open()):
            if row.get('outcome')!='y' or not row.get('standard_error_pp'):continue
            beta=float(row['coefficient_pp']);se=float(row['standard_error_pp']);lo=beta-1.6448536269514722*se;hi=beta+1.6448536269514722*se
            rows.append(dict(control_level=row['control_level'],n=row['n'],coefficient_pp=beta,standard_error_pp=se,
              ci90_low_pp=lo,ci90_high_pp=hi,equivalence_margin_pp=margin,reference_score_SD=SD,
              equivalent_within_original_margin=(lo>-margin and hi<margin),prespecified_original_margin_pp=.015,prespecified_original_score_SD=.0594))
        csv_out(report/'ordinary_equivalence.csv',rows)
    shutil.copyfile(ROOT/'README.txt',report/'README.txt')
    records=[dict(path=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(report.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    save(report/'REPORT_MANIFEST.json',records)
    dest=a.result_dir/('ALLTIME_ENTRY_PLACEBO_'+conf[:12]+f'_{progress:03}.zip');tmp=dest.with_suffix('.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,'report/'+p.name)
        if (run/'run.log').exists():z.write(run/'run.log','run.log')
    os.replace(tmp,dest);Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('CHECKPOINT_SAVED '+str(dest))

def stage_execute(a,run,conf):
    if a._stage=='authenticate':prepare(a,run,conf);return
    b=bind(run)
    if a._stage=='candidates':
        from rebuild_candidates import candidates
        candidates(a,run,conf,b)
    elif a._stage=='chronology':
        from rebuild_candidates import chronology
        chronology(a,run,conf,b)
    elif a._stage=='metadata_audit':
        from rebuild_metadata import plan
        plan(a,run,conf,b)
    elif a._stage=='metadata':
        from rebuild_metadata import retrieve
        retrieve(a,run,conf,b)
    elif a._stage=='frames':
        from rebuild_frames import assemble
        assemble(a,run,conf,b)
    elif a._stage=='models':
        from rebuild_models import execute
        execute(a,run,conf,b)

def main():
    a=parser().parse_args()
    if a.self_test:return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)
    package=verify();a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve()
    a.r12_root=(a.r12_root or a.project/'derived/replication/r12_r13_followups_v100_PRIVATE'/R12_PREFIX).expanduser().resolve()
    a.reuse_run=(a.reuse_run or a.project/'derived/replication/alltime_entry_placebo_v100_PRIVATE/56739829cf4a').expanduser().resolve()
    a.reuse_chronology=(a.reuse_chronology or a.project/'derived/replication/alltime_entry_placebo_v102_PRIVATE/25d22fd1d9e9').expanduser().resolve()
    require(a.project.is_dir(),'Project drive is not mounted');require(1<=a.workers<=10 and 10.5<=a.memory_gb<=11,'Use 1–10 workers and 10.5–11 GiB')
    config=dict(version=VERSION,package_manifest_sha256=package,rule=RULE,project=str(a.project),r12_root=str(a.r12_root),
        r9_root=str(a.r9_root) if a.r9_root else None,local_plan=str(a.local_plan) if a.local_plan else None,reuse_run=str(a.reuse_run),reuse_chronology=str(a.reuse_chronology))
    conf=key(config);run=a.project/'derived/replication/alltime_entry_placebo_v103_PRIVATE'/conf[:12]
    run.mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True);(run/'report').mkdir(exist_ok=True);a.result_dir.mkdir(parents=True,exist_ok=True)
    if a._stage:
        if a._stage!='metadata':frozen.u.no_network()
        with heartbeat('Stage '+a._stage):stage_execute(a,run,conf)
        return 0
    require(shutil.disk_usage(run).free>=60*2**30,'At least 60 GiB free is needed for the rebuild, disk-backed models and spill files')
    if (run/'config.json').exists():require(load(run/'config.json')==config,'Run definition changed')
    else:save(run/'config.json',config)
    statepath=run/'PRIVATE/STATE.json';state=load(statepath) if statepath.exists() else {};progress=0
    save(run/'report/runtime.json',dict(python=platform.python_version(),platform=platform.platform(),workers_cap=a.workers,
      memory_budget_gib=a.memory_gb,metadata_requests_serial=True,local_large_jobs_at_most_two=True,models_serial_disk_backed=True,
      chronology_merge_workers=0,chronology_merge_duckdb_decimal_gb=None,raw_game_chronology_rescan=False,
      chronology_partition_writer='bounded_arrow_single_file_per_bucket_v102',
      chronology_partition_file_cap_per_batch=256,chronology_partition_buffer_mib=128,
      completed_v102_chronology_reused=True,metadata_workers=1,metadata_duckdb_decimal_gb=4.,
      metadata_partition_count=128,metadata_max_input_rows_per_leaf=250000,metadata_arrow_buffer_mib=64))
    with prior_runs_stopped(a.project,run),(run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This rebuild is already running')
        save(a.result_dir/'ALLTIME_ENTRY_PLACEBO_LATEST_PRIVATE.json',dict(root=str(run),configuration_sha256=conf))
        log('v1.0.3 reuses v1.0.0 selection/scores and completed v1.0.2 chronology. Metadata audit and reconciliation use bounded, resumable game-ID partitions. New requests contain only unresolved eligible IDs. Progress percentages are stage markers, not time estimates.')
        for stage_name in STAGES:
            if stage_name=='metadata' and a.audit_only:
                state['metadata']=dict(status='AUDIT_COMPLETE');save(statepath,state);export(a,run,conf,state,40)
                log('AUDIT_COMPLETE: rerun the same command without --audit-only to fetch missing metadata and finish.');return 0
            state[stage_name]=dict(status='RUNNING');save(statepath,state);log('Starting '+stage_name)
            with (run/'run.log').open('a',buffering=1) as output:
                output.write(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+' STAGE '+stage_name+'\n')
                child=subprocess.Popen([sys.executable,str(ROOT/'run_rebuild.py'),*sys.argv[1:],'--_stage',stage_name],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
                try:
                    for line in child.stdout:print(line,end='',flush=True);output.write(line)
                    code=child.wait()
                except KeyboardInterrupt:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=20)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    state[stage_name]=dict(status='INTERRUPTED');save(statepath,state);export(a,run,conf,state,progress,'Interrupted; completed checkpoints retained');raise
            state[stage_name]=dict(status='COMPLETE' if code==0 else 'FAILED',exit_code=code);save(statepath,state)
            if code:
                export(a,run,conf,state,progress,'Stage '+stage_name+' failed; return report and log');return code
            progress=PROGRESS[stage_name];export(a,run,conf,state,progress)
        log('COMPLETE: return ALLTIME_ENTRY_PLACEBO_'+conf[:12]+'_100.zip and its .sha256. Update Table 6 and Appendix D only after the completed report is checked.')
    return 0

if __name__=='__main__':
    raise SystemExit('This v1.0.5 package finishes completed v1.0.3 fits. Use RUN_ALLTIME_ENTRY_PLACEBO.command or run_finish.py.')
