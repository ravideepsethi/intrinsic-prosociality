#!/usr/bin/env python3
"""Retry only the failed capped equal-state gap-plus-framing fold."""
import os
for _k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[_k]='1'
import argparse,fcntl,platform,shutil,threading,traceback,zipfile
from datetime import datetime,timezone
from common import *
from design import design
from stats import fit_conditional,conditional_value
from analysis import restore,evaluate,coefficient_rows,save_public_fit
from reporting import assemble

def verify_package():
    p=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        h,name=line.split('  ',1)
        if sha(ROOT/name)!=h:raise RuntimeError('Package checksum differs: '+name)
    return sha(p)

def embed_nested(nested,names):
    if nested['status']!='ESTIMATED':raise RuntimeError('Nested starting fit is not estimated')
    old=dict(zip(nested['names'],nested['beta']))
    if set(names)-set(old)!={'draw_frame'} or set(old)-set(names):
        raise RuntimeError('Unexpected model nesting')
    return np.array([old.get(n,0.) for n in names],float)

def refit(d,nested,failed):
    X,names,bounds=design(d,'strength_framing');warm=embed_nested(nested,names)
    for old in (nested,failed):
        if len(d)!=old['n'] or int(d.y.sum())!=old['grants'] or d.chooser.nunique()!=old['accounts']:
            raise RuntimeError('Training population differs from cached fit')
    ll=conditional_value(X,d.y.to_numpy(float),d.chooser.to_numpy(),warm)
    if not np.isclose(ll,nested['loglik'],rtol=1e-9,atol=1e-5):raise RuntimeError('Nested likelihood does not reproduce')
    attempts=[];start=warm;result=None
    # Stricter objective stopping if necessary; the original projected-gradient
    # acceptance threshold remains 2e-5. No scientific specification is changed.
    for ftol in (1e-12,1e-14,1e-15):
        f=fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),bounds=bounds,
            start=start,inference=False,maxiter=1000,ftol=ftol)
        f.update(model='strength_framing',names=names,curvature=.5,cue=None,
                 full_n=failed['full_n'],full_accounts=failed['full_accounts'])
        attempts.append({k:f.get(k) for k in ('status','iterations','gradient_max','loglik','message')})
        attempts[-1]['ftol']=ftol
        if f['status']=='ESTIMATED' and f['loglik']>=ll-1e-5:return f,attempts,ll
        if 'beta' in f:start=f['beta']
        result=f
    raise RuntimeError('Targeted retry did not satisfy unchanged convergence gate: '+json.dumps(clean(attempts)))

def replace_fold(report,f,scores,calibration):
    own=Path(report)/'models/equal/strength_framing'
    save_public_fit(f,own/'rd110_fold0_fit.json',state='equal',training='rd110')
    for name,new,field,value in [
        ('heldout_scores',scores,'comparison','rd110_train_rd110_test'),
        ('heldout_calibration',calibration,'comparison','rd110_train_rd110_test')]:
        d=pd.read_parquet(own/(name+'.parquet'))
        keep=~(d[field].eq(value)&d.fold.eq(0))
        table(pd.concat([d[keep],pd.DataFrame(new)],ignore_index=True),own/(name+'.parquet'))
    d=pd.read_parquet(own/'coefficients.parquet')
    keep=~(d.training.eq('rd110')&d.stage.eq('fold0'))
    new=coefficient_rows(f,state='equal',training='rd110',stage='fold0')
    table(pd.concat([d[keep],pd.DataFrame(new)],ignore_index=True),own/'coefficients.parquet')
    jobs=read(Path(report)/'MODEL_JOB_STATUS.json')
    for row in jobs:
        if row['state']=='equal' and row['model']=='strength_framing':row['status']='COMPLETE'
    write(Path(report)/'MODEL_JOB_STATUS.json',jobs)

def archive(report,desktop):
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    out=desktop/(report.name+'.zip');partial=out.with_suffix('.partial.zip')
    with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,report.name+'/'+p.relative_to(report).as_posix())
    os.replace(partial,out);text(Path(str(out)+'.sha256'),sha(out)+'  '+out.name+'\n')
    log('RESULT_TO_UPLOAD '+str(out))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    a=ap.parse_args();project=a.project_root.expanduser().resolve()
    if not project.is_dir():ap.error('XT_Pro project directory missing')
    code=verify_package();reference=read(ROOT/'authority/repair_reference.json')
    source=project/'derived/replication/mechanism_rd_audit_v100_PRIVATE'
    work=project/'derived/replication/mechanism_rd_audit_resume_v101_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=open(work/'run.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    parent_lock=None
    if (source/'run.lock').exists():
        parent_lock=open(source/'run.lock','r');fcntl.flock(parent_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
    start=time.monotonic();stop=threading.Event();error=None
    public=work/'public_results';public.mkdir(exist_ok=True)
    status=dict(status='REPAIR_PENDING',version='1.0.1',only_requested_refit='equal/rd110/strength_framing/fold0',
        upstream_stages_rebuilt=False,new_simulations_run=False,mechanism_shares_released=False,post_policy_outcomes_used=False)
    def heartbeat():
        while not stop.wait(45):log('One-fit numerical repair working; completed fits remain unchanged')
    threading.Thread(target=heartbeat,daemon=True).start()
    try:
        identity=read(source/'RUN_IDENTITY.json')
        if identity['package_sha256']!=reference['parent_package_sha256']:raise RuntimeError('Parent audit package differs')
        ledger=[]
        for rel,h in reference['expected_public_hashes'].items():
            p=source/'public_results'/rel;r=auth(p,work,h);ledger.append(dict(path=str(p),sha256=r['sha256']))
        prepared=read(source/'prepared/equal/PREPARED.json');fold=prepared['cohorts']['rd110']['folds'][0]
        required={fold['train_path'],fold['test_path']}
        for r in prepared['files']:
            if r['path'] in required:
                auth(r['path'],work,r['sha256'],size=r['bytes']);ledger.append(dict(path=r['path'],sha256=r['sha256']))
                required.remove(r['path'])
        if required:raise RuntimeError('Missing prepared input receipts')
        nested=restore(read(source/'fits/equal_strength_fold0.json')['fit'])
        failed=restore(read(source/'fits/equal_strength_framing_fold0.json')['fit'])
        for model,fit in [('strength',nested),('strength_framing',failed)]:
            p=source/'public_results/models/equal'/model/'rd110_fold0_fit.json';pub=read(p)
            if fit['names']!=pub['names'] or not np.allclose(fit['beta'],pub['beta'],rtol=1e-12,atol=1e-12):
                raise RuntimeError('Private fit differs from reviewed public fit')
        if failed['status']!='OPTIMIZER_NOT_CONVERGED':raise RuntimeError('Target no longer matches the reviewed numerical failure')
        key=digest(dict(code=code,parent_identity=identity,ledger=ledger,nested=nested,failed=failed))
        cache=work/'REPAIRED_FIT.json'
        if cache.exists():
            r=read(cache)
            if r['key']!=key:raise RuntimeError('Repair cache input identity changed')
            f=restore(r['fit']);attempts=r['attempts'];nested_ll=r['nested_loglik'];log('Reusing completed one-fit repair')
        else:
            log('Retrying one training fit from the converged nested gap model')
            f,attempts,nested_ll=refit(pd.read_parquet(fold['train_path']),nested,failed)
            write(cache,dict(key=key,fit=f,attempts=attempts,nested_loglik=nested_ll))
        shutil.copytree(source/'public_results',public,dirs_exist_ok=True)
        shutil.copy2(public/'SUMMARY.json',public/'PARENT_SUMMARY.json')
        shutil.copy2(public/'ENVIRONMENT.json',public/'PARENT_ENVIRONMENT.json')
        scores,cal=evaluate(pd.read_parquet(fold['test_path']),f,fold['test_meta'],state='equal',fold=0,comparison='rd110_train_rd110_test')
        replace_fold(public,f,scores,cal);assemble(public)
        comparisons=read(public/'MODEL_COMPARISON_STATUS.json')
        failures=[r for r in comparisons if r['status']!='COMPARED']
        status.update(status='RD_AUDIT_COMPLETE_AFTER_TARGETED_REPAIR' if not failures else 'COMPARISON_REVIEW_REQUIRED',
            comparison_failures=failures,fit_failures=[],newly_fitted_models=1,attempts=attempts,
            nested_training_loglik=nested_ll,repaired_training_loglik=f['loglik'],
            parent_result=reference['parent_result'],parent_result_sha256=reference['parent_result_sha256'])
        table(ledger,public/'repair_input_checksums.parquet')
    except Exception as exc:
        error=exc;status.update(status='TARGETED_REPAIR_FAILED',error=str(exc),traceback=traceback.format_exc());log(str(exc))
    finally:
        stop.set();status['elapsed_seconds']=time.monotonic()-start;write(public/'SUMMARY.json',status)
        write(public/'ENVIRONMENT.json',dict(python=platform.python_version(),platform=platform.platform(),
            numpy=np.__version__,pandas=pd.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__,package_sha256=code))
        shutil.copy2(ROOT/'README.md',public/'NUMERICAL_REPAIR.md')
        text(public/'READ_ME_FIRST.md','# Targeted numerical repair\n\nStatus: **'+status['status']+'**.\n\nOnly the capped equal-state gap-plus-framing first training fold was eligible for refitting. See SUMMARY.json and NUMERICAL_REPAIR.md. All other fitted models were copied unchanged from the completed audit. Read PARENT_METHODS.md and the inherited METHODS.md for scientific interpretation.\n')
        shutil.copy2(ROOT/'PARENT_METHODS.md',public/'PARENT_METHODS.md')
        run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        report=project/'output/mechanism_rd_audit_resume_v101'/('MECHANISM_RD_AUDIT_REPAIRED_RESULT_'+run_id)
        shutil.copytree(public,report);archive(report,a.desktop);lock.close()
        if parent_lock is not None:parent_lock.close()
    if error:raise SystemExit(1)

if __name__=='__main__':main()
