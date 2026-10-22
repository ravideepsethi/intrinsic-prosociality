#!/usr/bin/env python3
"""Concurrent, read-only consumer of completed Uniform90 Model 5 inputs."""
from supp_core import *
import argparse, csv, shutil, fcntl, zipfile, platform, contextlib
import run_fast as parent_runner
import finalize_submission as finalizer

def verify_package():
    manifest=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        digest,name=line.split('  ',1);p=(ROOT/name).resolve()
        require(p.is_relative_to(ROOT) and sha(p)==digest,'Package verification failed: '+name)
    parent_runner.verify()
    return sha(manifest)

def authenticate(parent):
    parent=Path(parent).expanduser().resolve()
    config=load(parent/'config.json');conf=c.key(config)
    require(conf==EXPECTED_CONF and parent.name==conf[:12],'Unexpected parent configuration/run directory')
    require(config.get('version')=='1.0.0' and config.get('rule')==c.RULE90,'Parent scientific definition changed')
    require(config.get('manifest_sha256')==sha(ROOT/'vendor/original/PACKAGE_MANIFEST.sha256'),'Original producer manifest changed')
    state=load(parent/'PRIVATE/STATE.json')
    require(state.get('receipt_models',{}).get('status')=='COMPLETE','Receipt stage must be complete (075); comparison stage may remain active')
    plan=load(parent/'PRIVATE/MODEL_PLAN90.json')
    jobs=[j for j in plan if j['name']=='uniform_unspaced'];require(len(jobs)==1,'Model 5 job missing/duplicated')
    job=jobs[0]
    require(job['conf']==conf and job['level']=='X0_ENV_indicator' and job['outcomes']==['received','y','reached'] and job['iv'],'Unexpected Model 5 specification')
    paths=dict(source=Path(job['input']).resolve(),scores=Path(job['scores']).resolve(),baseline=Path(job['output']).resolve()/'result.json')
    # The model stage binds its input bytes. Some upstream feature files use
    # sealed-cache receipts rather than their own directory-level _DONE file.
    deps_path=paths['baseline'].parent/'dependencies_PRIVATE.json'
    c.check_stage(paths['baseline'],conf);c.check_stage(deps_path,conf)
    deps={str(Path(d['path']).resolve()):d for d in load(deps_path)}
    records={}
    for label,p in paths.items():
        require(p.is_relative_to(parent) and '.partial' not in str(p),'Input is outside the completed parent run')
        before=signature(p)
        digest=sha(p);require(signature(p)==before,'Input changed during authentication: '+label)
        if label!='baseline':
            dep=deps.get(str(p));require(dep is not None and digest==dep['sha256'],'Input differs from completed Model 5 dependency: '+label)
            require(c.frozen.r.io.sig(p)==dep['signature'],'Input signature differs from completed Model 5 dependency: '+label)
        records[label]=dict(path=str(p),sha256=digest,signature=before)
    ref=load(paths['baseline']);rows={r['term']:r for r in ref['estimates']}
    r=rows['iv_y']
    require(r['n']==EXPECTED_N and r['recipients']==EXPECTED_PEOPLE and r['row_set_sha256']==EXPECTED_ROWS,'Model 5 identity differs')
    require(np.isclose(r['coefficient'],.3246734093460897,atol=2e-10,rtol=2e-10) and
            np.isclose(r['standard_error'],.05641077060922318,atol=2e-10,rtol=2e-10),'Parent Model 5 result differs from verified 075 report')
    require(load(parent/'report/legacy_reproduction.json')['passed'],'Parent legacy replay missing')
    return dict(parent_root=str(parent),project=config['project'],configuration_sha256=conf,inputs=records,
                receipt_models_complete=True,comparison_status=state.get('comparison_models',{}).get('status','NOT_YET_COMPLETE'))

def copy_verified(rec,destination):
    source=Path(rec['path']);destination=Path(destination)
    require(signature(source)==rec['signature'],'Parent input changed before snapshot')
    h=hashlib.sha256()
    with source.open('rb') as src,destination.open('wb') as dst:
        for b in iter(lambda:src.read(8*1024*1024),b''):dst.write(b);h.update(b)
    require(signature(source)==rec['signature'] and h.hexdigest()==rec['sha256'],'Parent input changed while snapshotting')

def completed(root,conf):
    root=Path(root);p=root/'_SUPP_DONE.json'
    if not p.exists():return False
    data=load(p);require(data['conf']==conf,'Supplement checkpoint configuration mismatch')
    for r in data['files']:
        f=root/r['path'];require(f.is_file() and f.stat().st_size==r['bytes'] and sha(f)==r['sha256'],'Supplement checkpoint damaged: '+str(f))
    return True

def stage(root,conf,producer):
    root=Path(root)
    if completed(root,conf):log('REUSE '+root.name);return root
    partial=root.with_name(root.name+'.partial')
    if partial.exists():shutil.rmtree(partial)
    partial.mkdir(parents=True)
    started=time.monotonic();producer(partial)
    records=[dict(path=str(p.relative_to(partial)),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(partial.rglob('*')) if p.is_file()]
    save(partial/'_SUPP_DONE.json',dict(conf=conf,seconds=time.monotonic()-started,files=records))
    require(not root.exists(),'Uncommitted stage folder exists: '+str(root))
    partial.rename(root);return root

def csv_write(path,rows):
    rows=list(rows);names=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names);w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})

def checkpoint(run,result_dir,percent,status='IN_PROGRESS',error=None):
    report=run/'report';report.mkdir(exist_ok=True)
    combined=(report/'COMPLETION.json').exists() and load(report/'COMPLETION.json').get('all_agreed_analyses_complete') is True
    require(status!='COMPLETE' or (percent==100 and combined),'Cannot mark 100 complete before entry/placebo and supplements are combined')
    save(report/'STATUS.json',dict(status=status,milestone_percent=percent,supplement_configuration=run.name,
        parent_configuration=EXPECTED_CONF,supplements=['S1','S4','S5','S7'],error=error,
        all_agreed_analyses_complete=combined,entry_and_placebo_included=combined))
    manifest=[dict(path=str(p.relative_to(report)),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    save(report/'REPORT_MANIFEST.json',manifest)
    dest=Path(result_dir)/f'MODEL5_SUBMISSION_{run.name}_{percent:03}.zip'
    temp=dest.with_suffix('.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
        if (run/'run.log').exists():z.write(run/'run.log','run.log')
    os.replace(temp,dest);dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('CHECKPOINT_SAVED '+str(dest))

def execute(a):
    package=verify_package();log('PACKAGE_SHA256_OK')
    # Cap Arrow/BLAS independently of the active parent process.
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    try:os.nice(10)
    except OSError:pass
    binding=authenticate(a.parent_root);log('PARENT_MODEL5_AUTHENTICATED; completed receipt inputs only')
    work=Path(a.work_dir).expanduser().resolve();project=Path(binding['project']).resolve();parent=Path(binding['parent_root'])
    require(not work.is_relative_to(project) and not project.is_relative_to(work),'Supplement workspace must be outside the parent project tree')
    require(not work.is_relative_to(parent),'Supplement workspace overlaps parent run')
    config=dict(specification=SPEC,package_manifest_sha256=package,
        inputs={k:dict(sha256=v['sha256'],bytes=v['signature'][0]) for k,v in binding['inputs'].items()},
        software=dict(python=platform.python_version(),numpy=np.__version__,pyarrow=pa.__version__,duckdb=bounded.duckdb.__version__))
    conf=c.key(config);run=work/conf[:12];run.mkdir(parents=True,exist_ok=True)
    a.result_dir=Path(a.result_dir).expanduser().resolve();a.result_dir.mkdir(parents=True,exist_ok=True)
    require(not a.result_dir.is_relative_to(project),'Reports must be written outside the parent project')
    with (run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This supplement run is already active; its own lock is retained')
        with (run/'run.log').open('a',buffering=1) as logfile,contextlib.redirect_stdout(Tee(sys.stdout,logfile)):
            if (run/'config.json').exists():require(load(run/'config.json')==config,'Supplement configuration changed')
            else:save(run/'config.json',config)
            report=run/'report';report.mkdir(exist_ok=True);private=run/'PRIVATE';private.mkdir(exist_ok=True)
            save(report/'supplement_definition.json',SPEC);save(report/'provenance.json',dict(configuration_sha256=conf,**config,
                parent_read_only=True,local_snapshot=True,one_fit_at_a_time=True,sql_memory_decimal_gb=1,blas_threads=1,
                pressure_guard='yield between allocations on macOS if free+inactive+speculative memory is below 1.5 GiB',
                runtime='Not benchmarked on the full private frame; concurrent elapsed time depends on parent workload'))
            percent=0
            try:
                if completed(private/'final',conf):
                    export_final(private,report);percent=75
                    finish(run,a,parent,private,report);return 0
                need=max(20*2**30,sum(v['signature'][0] for v in binding['inputs'].values())+18*2**30)
                require(shutil.disk_usage(work).free>=need,f'Need approximately {need/2**30:.1f} GiB free in the supplement workspace')
                def snapshot(tmp):
                    for key,rec in binding['inputs'].items():
                        log('Snapshot '+key);copy_verified(rec,tmp/('baseline.json' if key=='baseline' else key+'.parquet'))
                    save(tmp/'binding_PRIVATE.json',binding)
                inputs=stage(private/'inputs',conf,snapshot)
                design=stage(private/'design',conf,lambda tmp:prepare_design(inputs/'source.parquet',inputs/'scores.parquet',tmp))
                cnt=load(design/'counts.json');save(report/'recipient_summary.json',cnt['summary'])
                for key,name in [('histogram','rows_per_recipient.csv'),('quantiles','recipient_quantiles.csv'),('thresholds','recipient_thresholds.csv')]:csv_write(report/name,cnt[key])
                save(report/'input_authentication.json',dict(parent_configuration=EXPECTED_CONF,row_set_sha256=EXPECTED_ROWS,
                    n=EXPECTED_N,recipients=EXPECTED_PEOPLE,input_sha256=config['inputs'],verified_completed_parent_files=True))
                percent=25;checkpoint(run,a.result_dir,percent)
                if a.preflight_only:return 0
                info=load(design/'design.json');meta=info['meta']
                def unweighted(tmp):
                    terms=fit(design,tmp,False)
                    V=covariance(tmp/'influence.parquet',['u_'+t['term'] for t in terms],private/'covariance_unweighted')
                    rows=result_rows(terms,V,meta,'model5_unweighted',False)
                    gate=baseline_gate(rows,load(inputs/'baseline.json'))
                    save(tmp/'result.json',dict(rows=rows,covariance=V.tolist(),gate=gate))
                u=stage(private/'unweighted',conf,unweighted)
                save(report/'baseline_reproduction.json',load(u/'result.json')['gate'])
                csv_write(report/'supplements.csv',load(u/'result.json')['rows'])
                percent=50;checkpoint(run,a.result_dir,percent);log('MODEL5_REPLAY_OK; OLS and S5 available')
                w=stage(private/'weighted',conf,lambda tmp:fit(design,tmp,True))
                percent=75;checkpoint(run,a.result_dir,percent)
                def combine(tmp):
                    merge_influences(u/'influence.parquet',w/'influence.parquet',tmp/'joint.parquet')
                    ut,wt=load(u/'terms.json'),load(w/'terms.json');cols=['u_'+t['term'] for t in ut]+['w_'+t['term'] for t in wt]
                    V=covariance(tmp/'joint.parquet',cols,private/'covariance_joint')
                    prior=np.array(load(u/'result.json')['covariance']);require(np.allclose(V[:len(ut),:len(ut)],prior,rtol=2e-7,atol=2e-12),'Joint covariance fails unweighted replay')
                    rows=result_rows(ut,V[:len(ut),:len(ut)],meta,'model5_unweighted',False)+result_rows(wt,V[len(ut):,len(ut):],meta,'S1_recipient_weighted',True)
                    baseline_gate(rows[:len(ut)],load(inputs/'baseline.json'))
                    contrasts=[]
                    for term in ('first_stage','rf_y','iv_y'):
                        i=next(i for i,t in enumerate(ut) if t['term']==term);j=len(ut)+next(i for i,t in enumerate(wt) if t['term']==term)
                        scale=ut[i]['scale'];b=wt[j-len(ut)]['beta']-ut[i]['beta']
                        contrasts.append(dict(contrast='recipient_weighted_minus_Model5',term=term,units=ut[i]['units'],
                            **old.inference90(b,float(V[i,i]+V[j,j]-2*V[i,j]),scale)))
                    i=next(i for i,t in enumerate(ut) if t['term']=='ols_y');j=next(i for i,t in enumerate(ut) if t['term']=='iv_y')
                    contrasts.append(dict(contrast='OLS_minus_IV_same_rows',term='y',units='percentage points per receipt',
                        **old.inference90(ut[i]['beta']-ut[j]['beta'],float(V[i,i]+V[j,j]-2*V[i,j]),100.)))
                    r={x['term']:x for x in rows[:len(ut)]};diagnostics=dict(
                        identity_probability=r['s5_mu1']['coefficient']-r['s5_mu0']['coefficient'],
                        iv_probability=r['iv_y']['coefficient']/100,
                        identity_error=r['s5_mu1']['coefficient']-r['s5_mu0']['coefficient']-r['iv_y']['coefficient']/100,
                        mu1=r['s5_mu1'],mu0=r['s5_mu0'],
                        interpretation='Transformed-outcome IV diagnostics, not a certification of monotonicity. Complier-mean interpretation requires additional exogeneity, exclusion, monotonicity and specification/weighting assumptions. Probability units; no clipping.')
                    save(tmp/'results.json',dict(rows=rows,contrasts=contrasts,S5=diagnostics,covariance_columns=cols,covariance=V.tolist()))
                    (tmp/'joint.parquet').unlink()
                stage(private/'final',conf,combine);export_final(private,report)
                finish(run,a,parent,private,report);return 0
            except KeyboardInterrupt:
                checkpoint(run,a.result_dir,percent,'INTERRUPTED','Rerun the same supplement command; completed phases are retained');return 130
            except Exception as e:
                checkpoint(run,a.result_dir,percent,'FAILED',str(e));raise

def export_final(private,report):
    data=load(private/'final/results.json');csv_write(report/'supplements.csv',data['rows']);csv_write(report/'contrasts.csv',data['contrasts'])
    save(report/'S5_diagnostics.json',data['S5']);save(report/'joint_covariance.json',dict(columns=data['covariance_columns'],matrix=data['covariance']))

def finish(run,a,parent,private,report):
    path=a.parent_report or a.result_dir/('UNIFORM90_IV_'+EXPECTED_CONF[:12]+'_100.zip')
    def waiting(message):
        save(report/'WAITING_PARENT.json',dict(message=message,expected_report=str(path),supplement_fits_complete=True))
        checkpoint(run,a.result_dir,75,'WAITING_PARENT')
    public,provenance=finalizer.wait_parent(path,parent,waiting)
    finalizer.assemble(report,public,provenance,load(private/'final/results.json'))
    (report/'WAITING_PARENT.json').unlink(missing_ok=True)
    checkpoint(run,a.result_dir,100,'COMPLETE')
    log('ALL_AGREED_PRE_SUBMISSION_COMPUTATIONS_COMPLETE; read report/READ_RESULTS_FIRST.txt in the 100 ZIP')

class Tee:
    def __init__(self,*streams):self.streams=streams
    def write(self,text):
        for stream in self.streams:stream.write(text);stream.flush()
        return len(text)
    def flush(self):
        for stream in self.streams:stream.flush()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness/derived/replication/receipt_iv_uniform90_v100_PRIVATE/af114813b1ad'))
    p.add_argument('--work-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop/Model5_Submission_PRIVATE')
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--parent-report',type=Path,help='Parent Uniform90 100 ZIP; default is the standard filename in --result-dir')
    p.add_argument('--preflight-only',action='store_true')
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)
    return execute(a)

if __name__=='__main__':raise SystemExit(main())
