"""Single resumable closeout command; production never contacts the network."""
from closeout_common import *
import argparse,subprocess,fcntl,zipfile,traceback,datetime
from zoneinfo import ZoneInfo
STAGES=['preflight','ordinary','material','balance','export']
BASE_PACKAGE_SHA='f523e9fbeab12e955a95d35721ee0165a9362226241eacd82f0048469f6f7fac'
BASE_CONF='2854da0567adc38694949710ea608055f4d3157aaa92ebc5a9aa0ceb41d52aeb'

def arguments():
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--parent',type=Path)
    p.add_argument('--workers',type=int,default=10)
    p.add_argument('--memory-gb',type=float,default=11.)
    p.add_argument('--preflight-only',action='store_true')
    p.add_argument('--_stage',choices=STAGES,help=argparse.SUPPRESS)
    return p.parse_args()

def setup(a):
    a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve()
    a.parent=(a.parent or a.project/'derived/replication/mating_material_iv_batch_v100_PRIVATE'/PARENT_CONF[:16]).resolve()
    require(a.project.is_dir(),'Project drive not mounted: '+str(a.project))
    hw=c.resources(a.workers,a.memory_gb);a.workers=min(10,hw['workers']);a.memory_gb=hw['memory_budget_gib']
    os.environ['UNIFORM90_MEMORY_GIB']=str(a.memory_gb);os.environ['UNIFORM90_WORKERS']=str(a.workers)
    os.environ['CLOSEOUT_SQL_GB']='1.5'
    from fast_digest_cache import install
    install(c.frozen.r.io)
    require(sha(ROOT/'authority/failed_v100/EXECUTED_PACKAGE.sha256')==BASE_PACKAGE_SHA,'Baseline execution manifest differs')
    # This is an execution repair of the reviewed scientific configuration.
    # Its own bytes are separately recorded below; numerical definitions stay fixed.
    config=dict(version='1.0.0',package_sha256=BASE_PACKAGE_SHA,parent=str(a.parent),parent_configuration=PARENT_CONF,production_network=False)
    conf=c.key(config);run=a.project/'derived/replication/mating_material_paper_closeout_v100_PRIVATE'/conf[:16]
    require(conf==BASE_CONF and (run/'config.json').is_file(),'Reviewed closeout checkpoint not found; this repair must resume 2854da0567adc386')
    for p in (run/'PRIVATE',run/'report',a.result_dir):p.mkdir(parents=True,exist_ok=True)
    if (run/'config.json').exists():require(read(run/'config.json')==config,'Closeout configuration differs')
    return run,conf

def export(a,run,conf):
    from paper_export import render
    render(run)
    required=['ORDINARY_FRAME.json','ordinary_draw_vs_loss.csv','ordinary_support.csv','ordinary_balance.csv','MATERIAL_SCREEN.json','material_contrast.csv','model_estimates.csv','balance_joint.csv','RECENT_BALANCE_DEFINITION.json']
    require(all((run/'report'/x).is_file() for x in required),'Missing retained result family')
    save(run/'report/COVERAGE.json',dict(status='RETAINED_ANALYSES_COMPLETE',
      already_completed=['core position-stage-gap','continuous evaluation','persistence','Patron','matched receipt','primary IV and instruments','entry and ordinary-ending exclusion checks','primary balance','non-IV supplements'],
      completed_here=['ordinary draw-versus-loss, three matching specifications','strict final material <4 spaced sensitivity','recent balance for three retained specifications'],
      omitted_extensions=['two-instrument Hansen test','spaced complier demographics','clearly-worse receipt IV','receipt-position/stakes heterogeneity','extra balance ladder and implied-bias projection','adjacent-payoff check'],
      manuscript_rule='Omitted extensions and their numerical claims must be removed; original draft is archived, not silently overwritten.',
      whole_paper_complete=False,remaining='Integrate these private-data results into the manuscript, verify every retained number/reference, compile and visually inspect final PDF.'))

def execute(a,run,conf):
    if a._stage=='preflight':preflight(a,run,conf);return
    auth=read(run/'PRIVATE/AUTHENTICATED.json');guard(auth)
    if a._stage=='ordinary':
        import mechanism;mechanism.run_all(a,run,conf,auth)
    elif a._stage=='material':
        import material;material.run_all(a,run,conf,auth)
    elif a._stage=='balance':
        import balance;balance.run_all(a,run,conf,auth)
    elif a._stage=='export':export(a,run,conf)
    guard(auth)

def archive(a,run,conf,state):
    save(run/'report/STATUS.json',state)
    manifest=[record(p,run/'report') for p in sorted((run/'report').rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    save(run/'report/REPORT_MANIFEST.json',manifest)
    destination=a.result_dir/('MATERIAL_PAPER_CLOSEOUT_'+conf[:16]+'_RETURN.zip');temp=destination.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((run/'report').rglob('*')):
            if p.is_file():z.write(p,Path('report')/p.relative_to(run/'report'))
        z.write(run/'run.log','run.log')
        z.write(ROOT/'README.txt','README.txt')
        z.write(ROOT/'PACKAGE_MANIFEST.sha256','EXECUTED_PACKAGE.sha256')
    os.replace(temp,destination)
    destination.with_name(destination.name+'.sha256').write_text(sha(destination)+'  '+destination.name+'\n')
    save(a.result_dir/'MATERIAL_PAPER_CLOSEOUT_LATEST_PRIVATE.json',dict(run=str(run),configuration=conf,return_zip=str(destination),status=state['status']))
    return destination

def main():
    a=arguments();verify_package();b.no_network();run,conf=setup(a)
    if a._stage:execute(a,run,conf);return 0
    lock=open(run/'RUN.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This closeout is already running; no second worker was launched.')
    repair=dict(execution_version='1.0.2',scientific_configuration=conf,
        baseline_package_manifest_sha256=BASE_PACKAGE_SHA,
        repaired_package_manifest_sha256=sha(ROOT/'PACKAGE_MANIFEST.sha256'),
        analytical_sample_changed=False,estimator_changed=False,production_network=False,
        query_and_metadata_partitions=128,matching_partitions=128,covariance_partitions=128,
        ordinary_sql_limit_gb=1.5,ordinary_sql_threads=1,
        global_wide_sort_removed=True,material_selection_streamed=True,
        compensated_overlap_moments=True,independent_cell_formula_check=True,
        weight_tolerances_unchanged=True,weights_rescaled=False)
    require(sha(ROOT/'authority/failed_v101/EXECUTED_PACKAGE.sha256')=='39eb87379995171a1a1326734e4ef37c81909aec38a138a9c78d3f2ded582e69','Prior execution manifest differs')
    prior=run/'report/REPAIR_V101.json'
    require(prior.is_file() and read(prior)==read(ROOT/'authority/failed_v101/report/REPAIR_V101.json'),'The reviewed v1.0.1 checkpoint is required')
    rp=run/'report/REPAIR_V102.json'
    if rp.exists():require(read(rp)==repair,'Different repair bytes already used this configuration')
    else:save(rp,repair)
    Toronto=ZoneInfo('America/Toronto');utc=datetime.datetime.now(datetime.timezone.utc);now=utc.astimezone(Toronto)
    print('Expected remaining runtime: 90–150 minutes provisionally; drive I/O can extend this. Startup tests take about 1–2 minutes.',flush=True)
    print('Toronto start: '+now.strftime('%Y-%m-%d %I:%M %p %Z')+'; provisional finish '+(utc+datetime.timedelta(minutes=90)).astimezone(Toronto).strftime('%Y-%m-%d %I:%M %p %Z')+'–'+(utc+datetime.timedelta(minutes=150)).astimezone(Toronto).strftime('%Y-%m-%d %I:%M %p %Z'),flush=True)
    print('Private work: '+str(run),flush=True)
    state=dict(status='RUNNING',configuration=conf,completed=[],failed=[],whole_paper_complete=False,private_rows_exported=False,stages={})
    code=0;logpath=run/'run.log'
    with logpath.open('a',buffering=1) as logfile:
        for name in STAGES:
            if a.preflight_only and name!='preflight':break
            began=time.monotonic();log('Closeout stage '+name)
            cmd=[sys.executable,'-u',str(ROOT/'run.py'),'--project',str(a.project),'--parent',str(a.parent),'--result-dir',str(a.result_dir),'--workers',str(a.workers),'--memory-gb',str(a.memory_gb),'--_stage',name]
            process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            try:
                for line in process.stdout:print(line,end='',flush=True);logfile.write(line)
                rc=process.wait()
            except KeyboardInterrupt:
                process.terminate();process.wait();rc=130
            state['stages'][name]=dict(exit_code=rc,seconds=time.monotonic()-began)
            if rc:
                state['failed'].append(name);state['status']='STOPPED_WITH_CHECKPOINT';code=rc;break
            state['completed'].append(name)
            archive(a,run,conf,state)
    if not code:state['status']='PREFLIGHT_COMPLETE' if a.preflight_only else 'RETAINED_ANALYSES_COMPLETE'
    destination=archive(a,run,conf,state)
    print('Return this single file: '+str(destination),flush=True)
    print('Finished/paused Toronto: '+datetime.datetime.now(Toronto).strftime('%Y-%m-%d %I:%M %p %Z'),flush=True)
    if code:print('Completed checkpoints are retained. The same command resumes; do not delete the work directory.',flush=True)
    else:print('No original analyses or manuscript files were overwritten. The manuscript still needs integration and final review.',flush=True)
    return code
