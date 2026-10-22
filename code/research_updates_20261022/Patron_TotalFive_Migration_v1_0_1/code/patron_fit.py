"""Old-sample numerical gates, new Patron fits, and explicit timing sensitivities."""
from patron_common import *
import patron_models as models
import migration_util as mu
import concurrent.futures as cf, multiprocessing as mp
LEVELS=('X0_ENV_indicator','X0')

def make(a,path,sample,family,level,variant='A',weighted=False,prior=False,before=False,label=None):
    name=label or '__'.join([family,sample,variant,'IPW' if weighted else 'unweighted','prior' if prior else 'all', 'before5' if before else 'alltime',level])
    job=dict(name=name,input=str(path),sample=sample,family=family,level=level,variant=variant,weighted=weighted,preeligible=prior,before_support=before,conf=a.conf,output=str(a.run/'PRIVATE/fits'/name))
    if family=='selection':job['outcomes']=['in_original_chooser_universe','positive_support','profile_returned']
    return job

def run_jobs(a,jobs):
    # A single large fit at a time avoids simultaneous duplicated FE/covariance
    # allocations; donor and authentication jobs use their own small pools.
    with cf.ProcessPoolExecutor(max_workers=1,mp_context=mp.get_context('spawn')) as pool:
        for ix,j in enumerate(jobs,1):
            log(f'Fit {ix}/{len(jobs)}: '+j['name'])
            r=pool.submit(models.fit_job,j).result();log(f"Finished in {r['seconds']/60:.1f} min")
    return [r for j in jobs for r in load(Path(j['output'])/'result.json')['rows']]

def verify_old(a,prepared):
    reference=load(PACKAGE/'evidence/old_patron_estimates.json');jobs=[]
    for level in LEVELS:
        for family,var,weight,prior in [('baseline','A',False,False),('patron','A',True,False),('patron','A',False,False),('patron','A',True,True),('patron','B',True,False)]:
            oldname='__'.join([family,'S0',var,'IPW' if weight else 'unweighted','prior' if prior else 'all',level])
            j=make(a,prepared/'old.parquet','old_S0',family,level,var,weight,prior,label='verify__'+oldname);j['reference_model']=oldname;jobs.append(j)
    run_jobs(a,jobs);checks=[]
    for j in jobs:
        actual=load(Path(j['output'])/'result.json')['rows'];expected=[r for r in reference if r['model']==j['reference_model']]
        require(len(actual)==len(expected)>0,'Legacy model result set differs')
        for old in expected:
            new=next(r for r in actual if (r['outcome'],r['estimator'])==(old['outcome'],old['estimator']))
            require(old['supported'] and new['supported'],'Legacy reproduction unsupported')
            for k in ('n','recipients','events','row_set_sha256'):require(new[k]==old[k],'Legacy sample differs: '+k)
            for k in ('coefficient','standard_error','native_residual_score_SD','outcome_mean_pp'):
                delta=abs(new[k]-old[k]);tol=2e-10+1e-8*abs(old[k]);checks.append(dict(model=j['reference_model'],outcome=old['outcome'],estimator=old['estimator'],field=k,delta=delta,tolerance=tol,passed=delta<=tol))
    table(a.run/'report/old_sample_reproduction',checks)
    require(checks and all(r['passed'] for r in checks),'Legacy numerical reproduction failed; no new results released')

def verify_r12(a,rows):
    expected=load(a.run/'PRIVATE/BOUND.json')['baseline'];checks=[]
    for estimator,outcome,b,se in [('first_stage','received','first_stage','first_stage_se'),('reduced_form','y','reduced_form','reduced_form_se'),('2SLS','y','iv','iv_se')]:
        r=next(r for r in rows if r['estimator']==estimator and r['outcome']==outcome and r['control_level']=='X0_ENV_indicator')
        require(r['n']==expected['exposures'] and r['recipients']==expected['recipients'],'R12 model sample changed')
        for actual,field in [('coefficient_pp',b),('standard_error_pp',se)]:
            d=abs(r[actual]-expected[field]);tol=2e-7+1e-7*abs(expected[field]);checks.append(dict(field=field,delta=d,tolerance=tol,passed=d<=tol))
    require(all(r['passed'] for r in checks),'R12 granting result did not reproduce with the weighted estimator at unit weights')
    table(a.run/'report/R12_reproduction',checks)

def main(a):
    if a.mode=='primary':
        prepared=a.run/'PRIVATE/prepared_primary';verify_stage(prepared,a.conf);verify_old(a,prepared)
        baseline=[make(a,prepared/'primary.parquet','total5_primary','baseline',l) for l in LEVELS]
        rows=run_jobs(a,baseline);verify_r12(a,rows);table(a.run/'report/new_receipt_reproduction_estimates',rows)
        jobs=[];gates=load(prepared/'eligibility_gate.json')
        for l in LEVELS:
            for w,prior in [(True,False),(False,False),(True,True)]:
                j=make(a,prepared/'primary.parquet','total5_primary','patron',l,weighted=w,prior=prior)
                if prior and not gates['primary']['allowed']:j['blocked_reason']='PRIOR_CHOOSER_TARGET_LACKS_UNIVERSAL_POSITIVE_SUPPORT_OR_ROWS'
                jobs.append(j)
            jobs.append(make(a,prepared/'primary.parquet','total5_primary','selection',l))
        rows=run_jobs(a,jobs);table(a.run/'report/Patron_primary_estimates',rows)
    else:
        prepared=a.run/'PRIVATE/prepared_extended';verify_stage(prepared,a.conf)
        require(all(r['passed'] for r in load(a.run/'report/old_sample_reproduction.json')),'Missing legacy gate')
        require(all(r['passed'] for r in load(a.run/'report/R12_reproduction.json')),'Missing R12 gate')
        jobs=[]
        for l in LEVELS:
            jobs.append(make(a,prepared/'first_reference.parquet','total5_first_observed','patron',l,weighted=True))
            for v in ('A','B'):
                jobs.append(make(a,prepared/'primary.parquet','total5_primary','patron',l,v,weighted=True,before=True))
            jobs.append(make(a,prepared/'primary.parquet','total5_primary','selection',l,'B',before=True))
        rows=run_jobs(a,jobs);table(a.run/'report/Patron_sensitivity_estimates',rows)
    table(a.run/'report'/('model_plan_'+a.mode),[{k:v for k,v in j.items() if k not in ('input','output','conf')} for j in jobs])

if __name__=='__main__':
    a=mu.parser().parse_args()
    with mu.pulse('Patron '+a.mode+' regressions'):main(a)
