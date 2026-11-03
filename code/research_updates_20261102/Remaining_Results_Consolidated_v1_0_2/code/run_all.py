"""Run all remaining retained-result jobs and return one aggregate-only ZIP."""
import argparse,fcntl,os,sys,subprocess,time,zipfile,traceback,platform,shutil
import importlib,importlib.metadata,re,shlex
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from result_common import *

DEPENDENCIES=('numpy','scipy','pandas','pyarrow','duckdb')

def dependency_report():
    """Check every required distribution and import before reporting problems."""
    versions={};checks={};problems=[]
    for name in DEPENDENCIES:
        entry={}
        try:
            versions[name]=importlib.metadata.version(name)
            entry['version']=versions[name]
        except Exception as exc:
            entry['metadata_error']=type(exc).__name__+': '+str(exc)
        try:
            importlib.import_module(name)
            entry['import_ok']=True
        except Exception as exc:
            entry['import_ok']=False
            entry['import_error']=type(exc).__name__+': '+str(exc)
        if 'metadata_error' in entry or not entry['import_ok']:problems.append(name)
        checks[name]=entry
    return dict(versions=versions,checks=checks,problems=problems)

def run_self_tests(env,report=None):
    log('Checking the package on synthetic data; these are not study estimates.')
    with heartbeat('Synthetic package checks'):
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-q'],
                              env=env,capture_output=True,text=True)
    transcript=result.stdout+'\n'+result.stderr
    if report is not None:(Path(report)/'SELF_TEST.log').write_text(transcript)
    match=re.search(r'Ran (\d+) tests',result.stderr)
    count=match.group(1) if match else 'unknown count'
    if result.returncode==0:
        log('Synthetic checks PASSED: '+count+' tests. Study jobs can now start.')
    else:
        log('Synthetic checks FAILED; no private-data job was launched.')
        print(result.stderr,flush=True)
    return result.returncode

def verify_package():
    for line in (ROOT/'SOURCE_SHA256SUMS.txt').read_text().splitlines():
        h,name=line.split('  ',1);p=(ROOT/name).resolve()
        require(p.is_relative_to(ROOT) and p.is_file() and sha(p)==h,'Package checksum differs: '+name)

def child(command,log_path):
    with Path(log_path).open('w',buffering=1) as f:
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        try:
            for line in proc.stdout:print(line,end='',flush=True);f.write(line)
            return proc.wait()
        except BaseException:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            raise

def collect_rating(job):
    zips=sorted((job/'returns').glob('RATING_VALIDATION_*RETURN.zip'))
    require(len(zips)==1,'Expected one rating-validation return ZIP')
    with zipfile.ZipFile(zips[0]) as z:
        for n in z.namelist():
            p=Path(n);require(not p.is_absolute() and '..' not in p.parts,'Unsafe rating return path')
            if p.suffix not in ('.csv','.json','.txt'):continue
            target=job/'aggregate'/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(n))

def pack(report,output):
    records=[];output=Path(output);temp=output.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if not p.is_file() or p.suffix not in ('.csv','.json','.txt','.log'):continue
            rel=p.relative_to(report)
            require('PRIVATE' not in rel.parts and p.suffix!='.parquet','Private rows cannot enter the return ZIP')
            z.write(p,str(rel));records.append(record(p,report))
        z.writestr('RETURN_MANIFEST.json',__import__('json').dumps(records,indent=2)+'\n')
    os.replace(temp,output);output.with_suffix('.zip.sha256').write_text(sha(output)+'  '+output.name+'\n')
    log('Return this single file: '+str(output))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--results-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=8);p.add_argument('--memory-gb',type=float,default=8)
    p.add_argument('--self-test',action='store_true');a=p.parse_args()
    os.umask(0o077);verify_package()
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'code')
    if a.self_test:return run_self_tests(env)
    require(1<=a.workers<=10 and 2<=a.memory_gb<=32,'Use 1–10 workers and 2–32 GB for chronology joins')
    a.project_root=a.project_root.expanduser().resolve();a.results_dir=a.results_dir.expanduser().resolve()
    a.results_dir.mkdir(parents=True,exist_ok=True)
    require(not a.results_dir.is_relative_to(a.project_root),'Return folder must be outside the source project')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report=a.results_dir/'Remaining_Results_Reports'/stamp;report.mkdir(parents=True,exist_ok=False)
    target=a.results_dir/f'REMAINING_RESULTS_{stamp}_RETURN.zip'
    lock=(a.results_dir/'Remaining_Results_Reports/RUNNING.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('A consolidated results run is already active')
    status=[];started=time.monotonic();exit_code=1
    try:
        now=datetime.now(ZoneInfo('America/Toronto'))
        log('Provisional total runtime: 20–60 minutes; allow longer for external-drive I/O or difficult hour projections.')
        log('Provisional finish window: '+(now+timedelta(minutes=20)).strftime('%I:%M %p %Z')+' to '+(now+timedelta(minutes=60)).strftime('%I:%M %p %Z'))
        require(a.project_root.is_dir(),'Mount XT_Pro; project root is missing: '+str(a.project_root))
        require(shutil.disk_usage(a.project_root).free>=10*2**30,'At least 10 GiB free is needed for checkpoints, quantiles and spill')
        dependencies=dependency_report()
        save(report/'ENVIRONMENT.json',dict(python=platform.python_version(),versions=dependencies['versions'],
            dependency_checks=dependencies['checks'],dependency_problems=dependencies['problems'],
            executable=sys.executable,platform=platform.platform(),
            workers=a.workers,duckdb_memory_gb=a.memory_gb,blas_threads=1,package_manifest_sha256=sha(ROOT/'SOURCE_SHA256SUMS.txt')))
        if dependencies['problems']:
            command=shlex.join([sys.executable,'-m','pip','install','--only-binary=:all:','-r',str(ROOT/'requirements.txt')])
            require(False,'Dependency problems: '+', '.join(dependencies['problems'])+'. Complete setup command: '+command)
        test=run_self_tests(env,report)
        require(test==0,'Synthetic tests failed; no private-data job was launched')
        jobs=[
            ('counts',[sys.executable,str(ROOT/'code/run_counts.py'),'--project',str(a.project_root),'--report',str(report/'counts')]),
            ('receipt_companions',[sys.executable,str(ROOT/'code/receipt_companions.py'),'--project',str(a.project_root),'--report',str(report/'receipt_companions'),
                '--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]),
            ('rating_validation',[sys.executable,str(ROOT/'code/validate_ratings.py'),'--project',str(a.project_root),'--results',str(report/'rating_validation/returns')])]
        for name,cmd in jobs:
            job=report/name;job.mkdir(parents=True,exist_ok=True);t=time.monotonic();log('Starting '+name)
            try:
                rc=child(cmd,job/'run.log')
                if name=='rating_validation':collect_rating(job)
                status.append(dict(job=name,status='COMPLETE' if rc==0 else 'FAILED_OR_PARTIAL',return_code=rc,seconds=time.monotonic()-t))
            except Exception as e:
                (job/'ORCHESTRATOR_ERROR.txt').write_text(traceback.format_exc())
                status.append(dict(job=name,status='FAILED',error=str(e),seconds=time.monotonic()-t))
            save(report/'JOB_STATUS.json',status)
        exit_code=0 if len(status)==3 and all(s['status']=='COMPLETE' for s in status) else 1
    except BaseException as e:
        (report/'ERROR.txt').write_text(traceback.format_exc());log(type(e).__name__+': '+str(e))
        if isinstance(e,KeyboardInterrupt):exit_code=130
    finally:
        save(report/'STATUS.json',dict(status='ALL_REQUESTED_RESULT_JOBS_COMPLETE' if exit_code==0 else 'INCOMPLETE',
              jobs=status,elapsed_seconds=time.monotonic()-started,manuscript_or_pdf_modified=False,
              completion_scope='Rating validation, six retained matched-receipt companions, donor/environment/reputation/tenure counts',
              whole_paper_completion_certified=False))
        shutil.copyfile(ROOT/'RESULTS_SCOPE.csv',report/'RESULTS_SCOPE.csv')
        pack(report,target);fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    return exit_code
if __name__=='__main__':raise SystemExit(main())
