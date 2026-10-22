"""Fixed-complexity numerical sensitivity, refit uncertainty, and recovery."""
from pathlib import Path
from collections import OrderedDict
import hashlib,json,math
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm
from scipy.special import expit
import hmm,stable_hmm as sh,model_analysis as old
from features import design,subset,replace_outcomes
from util import *

FAMILIES=('gate','willingness','unrestricted','gate_cost')
PAIRS=old.PAIRS[:4]
_DATA=OrderedDict()


def cached_data(path):
    if path not in _DATA:
        _DATA[path]=old.load_data(path)
        while len(_DATA)>2:_DATA.popitem(last=False)
    return _DATA[path]


def job(task):
    path,out,identity,family,J,seed,width,maxiter,ridge,warm,weights,yfile,label=task
    out=Path(out)
    if ready(out,identity):return json.loads(out.read_text())
    d=dict(cached_data(path))
    if weights is not None:d['account_weights']=np.array(weights,float)
    if yfile is not None:d['y']=np.load(yfile,allow_pickle=False)
    log('FIT '+label)
    result=sh.fit(d,family,J,seed,maxiter,ridge,warm,width)
    require(np.isfinite(result['objective']) and np.isfinite(result['parameters']).all(),'Nonfinite fit: '+label)
    result['start_label']=label;atomic_json(out,result);certify(out,identity)
    log(f'DONE {label}: converged={result["converged"]}; boundaries={len(result["boundary_parameters"])}')
    return result


def run_tasks(tasks,pool):return list(pool.map(job,tasks)) if pool is not None else [job(t) for t in tasks]


def fit_set(data_path,private,identity,family,J,width,prefix,args,pool,warms=(),weights=None,yfile=None,starts=None,seed=None):
    starts=starts or args.starts;seed=args.seed if seed is None else seed
    tasks=[]
    # Half the starts are dispersed independently; extra warm candidates do not displace those starts.
    supplied=list(warms);n_random=max(2,starts//2);n_total=max(starts,len(supplied)+n_random)
    for k in range(n_total):
        warm=supplied[k] if k<len(supplied) else None
        label=f'{prefix}_{family}_w{width:g}_s{k}'
        tasks.append((str(data_path),str(private/'fits'/(label+'.json')),identity,family,J,seed+101*k,width,
          args.maxiter,args.ridge,warm,weights,str(yfile) if yfile else None,label))
    results=run_tasks(tasks,pool);chosen=old.choose(results)
    finite=min(results,key=lambda f:f['objective'])
    chosen=dict(chosen,lower_nonconverged_objective_gap=max(0.,chosen['objective']-finite['objective']),
      attempted_starts=len(results),converged_starts=sum(f['converged'] for f in results),
      start_objective_range=float(max(f['objective'] for f in results)-min(f['objective'] for f in results)))
    return chosen,results


def pair_stats(candidate,baseline,d,mask,weights=None):
    delta=candidate-baseline;ids=d['ids'];N=len(d['accounts'])
    count=np.bincount(ids[mask],minlength=N);total=np.bincount(ids[mask],weights=delta[mask],minlength=N)
    w=np.ones(N) if weights is None else weights;active=count>0;M=int(active.sum());den=w@count
    if den<=0:return dict(gain=None,conditional_SE=None,p_value=None,accounts=M,opportunities=int(count.sum()),equal_account_gain=None)
    gain=float(w@total/den);se=None
    if weights is None and M>1:se=float(np.sqrt(M/(M-1)*np.sum((total[active]-gain*count[active])**2))/den)
    equal=float(np.average(total[active]/count[active],weights=w[active]))
    return dict(gain=gain,conditional_SE=se,p_value=float(2*norm.sf(abs(gain/se))) if se and se>0 else None,
      accounts=M,opportunities=int(count.sum()),equal_account_gain=equal)


def structure(result,d):
    m=sh.Layout(d['X'].shape[1],d['H'].shape[1],result['J'],result['family'],d['cost_indices'])
    z=m.decode(np.array(result['parameters']));w=np.exp(z['lp'])
    def avg(e,r):return float(w@expit(z['transition'][e,0]+z['gamma']+r*z['transition'][e,1]))
    return dict(reference_gap=float(z['alpha'][1]-z['alpha'][0]),tau_entry=float(z['transition'][0,1]),
      tau_stay=float(z['transition'][1,1]),tau_stay_minus_entry=float(z['transition'][1,1]-z['transition'][0,1]),
      reference_entry_probability_change=avg(0,1)-avg(0,0),reference_stay_probability_change=avg(1,1)-avg(1,0))


def moments(pred,d,mask,weights=None):
    w=np.ones(len(d['accounts'])) if weights is None else weights
    row_weights=w[d['ids'][mask]];den=row_weights.sum()
    return {name:float(np.dot(pred[name][mask],row_weights)/den) if den else None for name in
      ['receipt_entry_contribution','receipt_stay_contribution','receipt_state_entry_change','receipt_state_stay_change']}


def numerical_grid(train,eval_data,frame,prior,private,report,identity,args,pool):
    path=private/'train_arrays.npz';old.save_data(path,train,identity)
    selected={};attempt_rows=[];coefs=[];bounds_rows=[];scores=[];gains=[];previous={}
    test=eval_data['period']==1
    risk=test&(frame.separated_risks.to_numpy()>0)&(frame.ambiguous_receipts.to_numpy()==0)
    risk[eval_data['ptr'][:-1]]=False
    for width in args.bound_grid:
        at_width={};pred={}
        for family in FAMILIES:
            base=prior[family];J=base['J'];warms=[base['parameters']]
            if family in previous:warms.append(previous[family]['parameters'])
            if family in ('unrestricted','gate_cost'):warms.append(hmm.embed(at_width['gate'],family,train).tolist())
            if family=='unrestricted':warms.append(hmm.embed(at_width['willingness'],family,train).tolist())
            fit,attempts=fit_set(path,private,identity,family,J,width,'primary',args,pool,warms)
            at_width[family]=fit;pred[family]=sh.predict(fit,eval_data)
            for attempt in attempts:attempt_rows.append({k:attempt[k] for k in ['family','J','seed','width','start_label','objective','converged','iterations','projected_gradient_max','boundary_parameters']})
            coefs.append(dict(model=family,width=width,**structure(fit,train),**moments(pred[family],eval_data,risk),
              converged=fit['converged'],boundary_parameters=fit['boundary_parameters']))
            previous_score=None
            if family in previous:previous_score=float(np.max(abs(pred[family]['probability'][test]-sh.predict(previous[family],eval_data)['probability'][test])))
            bounds_rows.append(dict(model=family,width=width,objective=fit['objective'],converged=fit['converged'],
              boundary_count=len(fit['boundary_parameters']),lower_nonconverged_objective_gap=fit['lower_nonconverged_objective_gap'],
              objective_improvement_from_previous=previous[family]['objective']-fit['objective'] if family in previous else None,
              largest_evaluation_prediction_change=previous_score,attempted_starts=fit['attempted_starts']))
            scores.append(dict(model=family,width=width,opportunities=int(test.sum()),
              log_loss=float(-pred[family]['log_score'][test].mean()),brier=float(np.mean((eval_data['y'][test]-pred[family]['probability'][test])**2))))
        for a,b in PAIRS:gains.append(dict(candidate=a,baseline=b,width=width,**pair_stats(pred[a]['log_score'],pred[b]['log_score'],eval_data,test)))
        selected[str(width)]=at_width;previous=at_width
        for name,rows in [('bound_sensitivity.csv',bounds_rows),('optimizer_attempts.csv',attempt_rows),('receipt_transition_sensitivity.csv',coefs),('bound_scores.csv',scores),('bound_comparisons.csv',gains)]:csv_write(report/name,rows)
    widest=selected[str(args.bound_grid[-1])]
    atomic_json(report/'SELECTED_FITS.json',widest);atomic_json(report/'BOUND_FITS.json',selected)
    primary=[r for r in gains if r['width']==args.bound_grid[-1]];old.holm(primary,out='p_Holm_four_conditional')
    csv_write(report/'primary_comparisons.csv',primary)
    readiness=dict(primary_width=args.bound_grid[-1],fixed_J={k:v['J'] for k,v in widest.items()},
      all_converged=all(f['converged'] for f in widest.values()),
      any_boundary=any(f['boundary_parameters'] for f in widest.values()),
      any_better_nonconverged_start=any(f['lower_nonconverged_objective_gap']>1e-7 for f in widest.values()),
      status='NUMERICAL_SENSITIVITY_REPORTED',interpretation='Convergence is not global optimality, parameter recovery, or mechanism identification')
    atomic_json(report/'NUMERICAL_STATUS.json',readiness)
    return widest,selected,path,risk


def verify_legacy(train,eval_data,prior,prior_report,report,args):
    rows=[]
    for family in FAMILIES:
        result=prior[family];m=sh.Layout(train['X'].shape[1],train['H'].shape[1],result['J'],family,train['cost_indices'])
        objective,_=m.objective(np.array(result['parameters']),train,args.ridge)
        predicted=sh.predict(result,eval_data);test=eval_data['period']==1
        original=prior_report['heldout_scores.csv'];r=original[(original.model==family)&(original.group=='all')&(original.region=='all')].iloc[0]
        diff=float(-predicted['log_score'][test].mean()-r.log_loss)
        rows.append(dict(model=family,objective_difference=objective-result['objective'],heldout_log_loss_difference=diff))
        require(abs(objective-result['objective'])<1e-7 and abs(diff)<1e-7,'New likelihood does not reproduce the original fit: '+family)
    csv_write(report/'legacy_numeric_bridge.csv',rows)


def old_replication_six(base,base_identity,train,eval_data,report,prior_draws):
    rng=np.random.default_rng(20260921+70000+6)
    aw=rng.multinomial(len(train['accounts']),np.ones(len(train['accounts']))/len(train['accounts'])).astype(float)
    ew=rng.multinomial(len(eval_data['accounts']),np.ones(len(eval_data['accounts']))/len(eval_data['accounts'])).astype(float)
    original={};rows=[]
    for family in FAMILIES:
        attempts=[]
        for start in range(2):
            p=base/'PRIVATE'/f'boot_6_{family}_{start}.json'
            require(ready(p,base_identity),'Missing original bootstrap-six fit: '+str(p));attempts.append(json.loads(p.read_text()))
        original[family]=old.choose(attempts)
        for f in attempts:rows.append(dict(family=family,seed=f['seed'],objective=f['objective'],converged=f['converged'],boundaries=f['boundary_parameters']))
    csv_write(report/'original_bootstrap_6_attempts.csv',rows)
    pred={k:old.predict(f,eval_data)[0] for k,f in original.items()};bridge=[]
    for a,b in PAIRS:
        value=old.gain_stats(pred[a],pred[b],eval_data['y'],eval_data['ids'],eval_data['period']==1,ew)['gain']
        saved=float(prior_draws[(prior_draws.replication==6)&(prior_draws.candidate==a)&(prior_draws.baseline==b)].gain.iloc[0])
        require(abs(value-saved)<1e-9,'Original bootstrap-six resampling does not reproduce returned result')
        bridge.append(dict(candidate=a,baseline=b,returned_gain=saved,reproduced_gain=value))
    csv_write(report/'original_bootstrap_6_bridge.csv',bridge)
    return original,aw,ew


def bootstrap(train,path,eval_data,risk,fits,grid,private,report,identity,args,pool,legacy_six=None):
    rows=[];parameters=[];six=[];test=eval_data['period']==1;width=args.bound_grid[-1]
    # The random resampling stream deliberately matches v1.0.0, including replication 6.
    for b in range(args.bootstrap_refits):
        rng=np.random.default_rng(args.seed+70000+b)
        aw=rng.multinomial(len(train['accounts']),np.ones(len(train['accounts']))/len(train['accounts'])).astype(float)
        ew=rng.multinomial(len(eval_data['accounts']),np.ones(len(eval_data['accounts']))/len(eval_data['accounts'])).astype(float)
        chosen={};pred={}
        for family in FAMILIES:
            warms=[fits[family]['parameters']]
            if b==6 and legacy_six:warms.append(legacy_six[family]['parameters'])
            if family in ('unrestricted','gate_cost'):warms.append(hmm.embed(chosen['gate'],family,train).tolist())
            if family=='unrestricted':warms.append(hmm.embed(chosen['willingness'],family,train).tolist())
            f,_=fit_set(path,private,identity,family,fits[family]['J'],width,f'boot_{b:04d}',args,pool,
              warms,aw.tolist(),starts=args.refit_starts,seed=args.seed+90000+b*1000)
            chosen[family]=f;pred[family]=sh.predict(f,eval_data)
            parameters.append(dict(replication=b,model=family,converged=f['converged'],boundary_count=len(f['boundary_parameters']),
              objective=f['objective'],lower_nonconverged_objective_gap=f['lower_nonconverged_objective_gap'],
              **structure(f,train),**moments(pred[family],eval_data,risk,ew)))
        for a,c in PAIRS:rows.append(dict(replication=b,candidate=a,baseline=c,
          gain=pair_stats(pred[a]['log_score'],pred[c]['log_score'],eval_data,test,ew)['gain'],
          both_converged=chosen[a]['converged'] and chosen[c]['converged'],
          any_boundary=bool(chosen[a]['boundary_parameters'] or chosen[c]['boundary_parameters'])))
        if b==6:
            for cap in args.bound_grid[:-1]:
                narrow={};narrowpred={}
                for family in FAMILIES:
                    warms=[grid[str(cap)][family]['parameters']]
                    if legacy_six:warms.append(legacy_six[family]['parameters'])
                    if family in ('unrestricted','gate_cost'):warms.append(hmm.embed(narrow['gate'],family,train).tolist())
                    if family=='unrestricted':warms.append(hmm.embed(narrow['willingness'],family,train).tolist())
                    f,_=fit_set(path,private,identity,family,fits[family]['J'],cap,'boot_0006',args,pool,warms,aw.tolist(),starts=args.refit_starts)
                    narrow[family]=f;narrowpred[family]=sh.predict(f,eval_data)
                for a,c in PAIRS:six.append(dict(width=cap,candidate=a,baseline=c,
                  **pair_stats(narrowpred[a]['log_score'],narrowpred[c]['log_score'],eval_data,test,ew)))
            for r in rows[-4:]:six.append(dict(width=width,**r))
            csv_write(report/'bootstrap_6_reoptimization.csv',six)
        csv_write(report/'refit_bootstrap_draws.csv',rows);csv_write(report/'refit_transition_draws.csv',parameters)
        log(f'Bootstrap {b+1}/{args.bootstrap_refits} recorded')
    summary=[]
    for a,b in PAIRS:
        subset_rows=[r for r in rows if r['candidate']==a and r['baseline']==b]
        good=[r for r in subset_rows if r['both_converged']];values=np.array([r['gain'] for r in good],float)
        out=dict(candidate=a,baseline=b,requested=args.bootstrap_refits,converged=len(values),boundary_draws=sum(r['any_boundary'] for r in good),
          SE=float(values.std(ddof=1)) if len(values)>1 else None,positive_draws=int((values>0).sum()),
          interval_status='INSUFFICIENT_CONVERGED_REFITS')
        if len(values)>=100:out.update(percentile95_low=float(np.quantile(values,.025)),percentile95_high=float(np.quantile(values,.975)),interval_status='FROZEN_COMPLEXITY_REFIT_PERCENTILES')
        summary.append(out)
    csv_write(report/'refit_bootstrap_summary.csv',summary)
    params=[]
    keys=list(structure(fits['gate'],train))+list(moments(sh.predict(fits['gate'],eval_data),eval_data,risk))
    for family in FAMILIES:
        observed=dict(structure(fits[family],train),**moments(sh.predict(fits[family],eval_data),eval_data,risk))
        for key in keys:
            v=np.array([r[key] for r in parameters if r['model']==family and r['converged'] and r[key] is not None],float)
            out=dict(model=family,term=key,point_estimate=observed[key],converged=len(v),SE=float(v.std(ddof=1)) if len(v)>1 else None,
              interpretation='Predictive latent transition; not an IV effect or an observed moral state')
            if len(v)>=100:out.update(percentile95_low=float(np.quantile(v,.025)),percentile95_high=float(np.quantile(v,.975)))
            params.append(out)
    csv_write(report/'refit_transition_summary.csv',params)
    return summary


def calibrated_truth(fit,train,target,collapsed=False):
    result=dict(fit);v=np.array(fit['parameters']).copy()
    m=sh.Layout(train['X'].shape[1],train['H'].shape[1],fit['J'],fit['family'],train['cost_indices'])
    if collapsed:v[m.s['a']][1]=np.log(np.expm1(.03))
    reference=v[m.s['a']][0]
    def fun(shift):
        candidate=v.copy();candidate[m.s['a']][0]=reference+shift
        return sh.expected_grants(dict(result,parameters=candidate.tolist()),train)-target
    shift=brentq(fun,-30,30,xtol=1e-9);v[m.s['a']][0]=reference+shift
    z=m.decode(v)
    return dict(result,parameters=v.tolist(),alpha=z['alpha'].tolist(),weights=np.exp(z['lp']).tolist(),
      ell=z['ell'].tolist(),gamma=z['gamma'].tolist(),calibration_shift=shift,
      expected_training_grants=sh.expected_grants(dict(result,parameters=v.tolist()),train),
      generating_parameters_are_calibrated_not_reestimated=True)


def wilson(k,n):
    if n==0:return None,None
    z=1.95996398454;p=k/n;den=1+z*z/n;mid=(p+z*z/(2*n))/den
    half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return float(mid-half),float(mid+half)


def recovery(train,path,eval_data,fits,private,report,identity,args,pool):
    dgps={k:calibrated_truth(fits[k],train,float(train['y'].sum())) for k in ('gate','willingness','unrestricted')}
    dgps['nearly_collapsed']=calibrated_truth(fits['willingness'],train,float(train['y'].sum()),True)
    atomic_json(report/'RECOVERY_DGPS.json',dgps);rows=[];test=eval_data['period']==1
    for scenario,truth in dgps.items():
        code=int(hashlib.sha256(scenario.encode()).hexdigest()[:6],16)
        target=structure(truth,train)
        for rep in range(args.recovery_reps):
            seed=(args.seed+code+rep*1009)%(2**31-1)
            ytrain=sh.simulate(truth,train,seed);yeval=sh.simulate(truth,eval_data,seed+1)
            ys=private/'simulation_outcomes'/f'{scenario}_{rep:04d}.npy';ys.parent.mkdir(exist_ok=True)
            if ready(ys,identity):np.testing.assert_array_equal(np.load(ys),ytrain)
            else:np.save(ys,ytrain);certify(ys,identity)
            sim_eval=replace_outcomes(eval_data,yeval);selected={}
            for family in ('gate','willingness','unrestricted'):
                # Empirical fits are fixed generic warm starts. The generating truth is never supplied.
                warms=[fits[family]['parameters']]
                if family=='unrestricted':warms += [hmm.embed(selected[k],family,train).tolist() for k in ('gate','willingness')]
                f,_=fit_set(path,private,identity,family,fits[family]['J'],args.bound_grid[-1],f'recovery_{scenario}_{rep:04d}',args,pool,
                  warms,yfile=ys,starts=args.recovery_starts,seed=seed+17)
                selected[family]=f;pred=sh.predict(f,sim_eval);est=structure(f,train)
                rows.append(dict(scenario=scenario,replication=rep,fitted_family=family,converged=f['converged'],
                  boundaries=len(f['boundary_parameters']),training_accounts=len(train['accounts']),training_grants=int(ytrain.sum()),
                  evaluation_accounts=len(eval_data['accounts']),evaluation_year_grants=int(yeval[test].sum()),
                  heldout_log_loss=float(-pred['log_score'][test].mean()),
                  **{'true_'+k:v for k,v in target.items()},**{'estimated_'+k:v for k,v in est.items()}))
            csv_write(report/'recovery_draws.csv',rows);log(f'Recovery {scenario}: {rep+1}/{args.recovery_reps}')
    selection=[];errors=[]
    for scenario in dgps:
        s=pd.DataFrame([r for r in rows if r['scenario']==scenario])
        converged=s.groupby('replication').converged.all();eligible=converged[converged].index
        losses=s[s.replication.isin(eligible)].pivot(index='replication',columns='fitted_family',values='heldout_log_loss')
        for a,b in [('gate','willingness'),('unrestricted','gate'),('unrestricted','willingness')]:
            n=len(losses);wins=int((losses[a]<losses[b]).sum()) if n else 0;lo,hi=wilson(wins,n)
            selection.append(dict(scenario=scenario,candidate=a,baseline=b,requested=args.recovery_reps,all_models_converged=n,
              wins=wins,win_fraction=wins/n if n else None,MC_Wilson95_low=lo,MC_Wilson95_high=hi,
              mean_log_score_gain=float((losses[b]-losses[a]).mean()) if n else None))
        for family,part in s[s.converged].groupby('fitted_family'):
            for name in target:
                delta=part['estimated_'+name]-part['true_'+name]
                errors.append(dict(scenario=scenario,model=family,term=name,replications=len(part),bias=float(delta.mean()),RMSE=float(np.sqrt(np.mean(delta**2)))))
    csv_write(report/'recovery_selection.csv',selection);csv_write(report/'recovery_parameter_errors.csv',errors)
    atomic_json(report/'RECOVERY_STATUS.json',dict(status='FULL_TRAINING_DESIGN_RECOVERY_REPORTED',
      training_accounts=len(train['accounts']),training_observations=len(train['y']),target_training_grants=int(train['y'].sum()),
      evaluation_accounts=len(eval_data['accounts']),replications_per_scenario=args.recovery_reps,
      design='Fixed actual covariate and receipt histories; independently simulated development/evaluation accounts; actual year-one/year-two filtering',
      limitation='Conditional design recovery does not model endogenous opportunities, receipt feedback, or prove psychological identification'))
    return rows
