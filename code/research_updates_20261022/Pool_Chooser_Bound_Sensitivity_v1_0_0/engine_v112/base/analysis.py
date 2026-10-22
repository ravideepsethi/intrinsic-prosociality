"""Chronological selection, safe resumability, refit bootstrap and recovery."""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor,as_completed
from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
from scipy.optimize import linear_sum_assignment
from io_utils import *
from prepare import subset,perception_subset
from model import Spec,Model,CORE,PERCEPTION,fit,predict,simulate,transfer,parameters
from diagnostics import paired,summaries,perception_decomposition,CORE_PAIRS,NOISE_PAIRS

_CACHE={}


def initialize(design_path):
    global _CACHE
    root=Path(design_path)
    _CACHE={name:dict(np.load(root/(name+'.npz'),allow_pickle=False)) for name in ['development','evaluation']}
    _CACHE['meta']=json_read(root/'DESIGN.json')


def data_for(stage):
    dev,ev,meta=_CACHE['development'],_CACHE['evaluation'],_CACHE['meta']
    if stage=='perception':
        # Boundary observations are excluded from the primary perception fit;
        # their coverage is explicitly reported, not assigned a noise-induced jump.
        dev=perception_subset(dev,meta['support'],drop_boundaries=True)
        ev=perception_subset(ev,meta['support'],drop_boundaries=True)
    return dev,ev,meta


def safe_result(path,signature,fn):
    path=Path(path)
    if path.exists():
        result=json_read(path)
        require(result.get('signature')==signature,'Cached fit belongs to a different configuration: '+str(path))
        return result['result']
    result=fn();json_write(path,dict(signature=signature,result=result))
    return result


def fit_one(task):
    stage,spec,J,seed,options,path,warm,bound=task
    dev,ev,meta=data_for(stage)
    training=subset(dev,dev['period']<(1 if options['phase']=='validation' else 2))
    sig=binding(dict(stage=stage,spec=spec,J=J,seed=seed,options=options,warm=warm,bound=bound))
    def compute():
        res=fit(training,Spec(**spec),J,meta,seed,options['maxiter'],options['ridge'],bound,warm)
        if options['phase']=='validation':
            past=subset(dev,dev['period']<2)
            _,ll=predict(res,past,meta);mask=past['period']==1
            require(mask.any(),'No chronological validation opportunities')
            res['validation_score']=float(ll[mask].mean())
            res['validation_opportunities']=int(mask.sum())
        return res
    return safe_result(path,sig,compute)


def execute(tasks,worker,design_path,workers,label):
    results=[]
    if workers==1:
        initialize(design_path)
        for j,task in enumerate(tasks):
            results.append(worker(task));log(f'{label}: {j+1}/{len(tasks)} tasks complete')
    else:
        with ProcessPoolExecutor(max_workers=workers,initializer=initialize,initargs=(str(design_path),)) as pool:
            futures={pool.submit(worker,t):j for j,t in enumerate(tasks)}
            ordered={}
            for f in as_completed(futures):
                ordered[futures[f]]=f.result();log(f'{label}: {len(ordered)}/{len(tasks)} tasks complete')
            results=[ordered[j] for j in range(len(tasks))]
    return results


def best(results):
    good=[r for r in results if r['success'] and np.isfinite(r['objective'])]
    require(bool(good),'No converged optimizer start; increase --maxiter/--starts. See PRIVATE fit attempts.')
    return min(good,key=lambda x:x['objective'])


def provisional_best(results):
    """Allow an unfinished fit as a warm start, never as a selected result."""
    good=[r for r in results if r['success'] and np.isfinite(r['objective'])]
    if good:return min(good,key=lambda r:r['objective'])
    finite=[r for r in results if np.isfinite(r['objective'])]
    require(bool(finite),'Every optimizer start is nonfinite')
    return min(finite,key=lambda r:r['objective'])


def write_attempts(report,prefix,attempts):
    csv_write(report/(prefix+'optimizer_attempts.csv'),[dict(model=r['spec']['name'],J=r['J'],seed=r['seed'],
      success=r['success'],optimizer_success=r['optimizer_success'],objective=r['objective'],
      projected_gradient=r['projected_gradient'],iterations=r['iterations'],seconds=r['elapsed_seconds'],
      solver_passes=r['solver_passes'],bound=r['bound'],
      boundary_parameters=';'.join(r['numerical_bounds']),message=r['message']) for r in attempts])


def specs_for(stage,meta,args):
    if stage=='perception':return PERCEPTION
    specs=[s for s in CORE if s.name in args.models]
    if 'board_factor' in meta:specs.append(Spec('calibrated',surface='calibrated'))
    return specs


def run_models(private,report,args,stage='core'):
    design=private/'design';initialize(design)
    dev,ev,meta=data_for(stage)
    prefix='' if stage=='core' else 'perception_'
    for period in [0,1]:require(np.any(dev['period']==period),
      'No retained development opportunities in period '+str(period)+' for '+stage)
    require(np.any(ev['period']==2),'No retained evaluation-year opportunities for '+stage)
    if stage=='perception':
        from prepare import C0,C1
        early=subset(dev,dev['period']==0)
        require(C0 in early['cell'] and C1 in early['cell'],
                'Perception sample lacks an early-training index anchor')
        require(set(early['group'])==set(range(4)) and set(early['tier'])==set(range(4)),
                'Every rating tier needs early-training support for the four-tier perception comparison')
    specs=specs_for(stage,meta,args);directory=private/stage
    directory.mkdir(exist_ok=True)
    attempts=[];candidates={}
    # Validation uses period 0 for fitting and period 1 for sequential scoring.
    jobs=[]
    for spec in specs:
        for J in args.support_grid:
            for ridge in args.ridge_grid:
                for s in range(args.starts):
                    seed=args.seed+1000*J+s
                    opts=dict(phase='validation',maxiter=args.maxiter,ridge=ridge)
                    p=directory/f'validation_{spec.name}_J{J}_r{ridge}_s{s}.json'
                    jobs.append((stage,asdict(spec),J,seed,opts,str(p),None,args.bound))
    with heartbeat(stage+' chronological selection'):
        values=execute(jobs,fit_one,design,args.workers,stage+' validation')
    attempts.extend(values)
    write_attempts(report,prefix,attempts)
    for spec in specs:
        for J in args.support_grid:
            for ridge in args.ridge_grid:
                subset_results=[r for r in values if r['spec']['name']==spec.name and r['J']==J and r['ridge']==ridge]
                candidates[(spec.name,J,ridge)]=provisional_best(subset_results)
    # Additional nested starts guard against declaring a relaxation useless because
    # its optimizer missed the restricted fit. They never use evaluation outcomes.
    nests={'desert':['level'],'cost':['level'],'both':['desert','cost','no_cost','premium_only'],
           'free_index':['both'],'type_cells':['free_index'],'separate_costs':['both'],
           'signed_costs':['separate_costs'],'noisy_tiers':['accurate_tiers'],
           'noisy_common':['accurate_common'],'accurate_tiers':['accurate_common']}
    for target,sources in nests.items():
        if target not in [s.name for s in specs]:continue
        jobs=[];keys=[]
        for J in args.support_grid:
            for ridge in args.ridge_grid:
                key=(target,J,ridge);current=candidates[key]
                for source in sources:
                    if (source,J,ridge) not in candidates:continue
                    base=candidates[(source,J,ridge)]
                    mdl=Model(current['spec'],J,meta,args.bound)
                    warm=transfer(base,mdl,meta,args.seed).tolist()
                    opts=dict(phase='validation',maxiter=args.maxiter,ridge=ridge)
                    p=directory/f'nested_{target}_from_{source}_J{J}_r{ridge}.json'
                    jobs.append((stage,current['spec'],J,args.seed,opts,str(p),warm,args.bound));keys.append(key)
        vals=execute(jobs,fit_one,design,args.workers,stage+' nested starts') if jobs else []
        attempts.extend(vals)
        write_attempts(report,prefix,attempts)
        for key,r in zip(keys,vals):candidates[key]=provisional_best([candidates[key],r])
    # Expand numerical bounds on the training/validation comparison, never on test score.
    jobs=[];keys=[]
    for key,r in candidates.items():
        if r['numerical_bounds']:
            opts=dict(phase='validation',maxiter=args.maxiter,ridge=r['ridge'])
            p=directory/f'wider_{key[0]}_J{key[1]}_r{key[2]}.json'
            jobs.append((stage,r['spec'],r['J'],r['seed'],opts,str(p),r['parameters'],args.bound*2));keys.append(key)
    vals=execute(jobs,fit_one,design,args.workers,stage+' bound checks') if jobs else []
    attempts.extend(vals)
    write_attempts(report,prefix,attempts)
    for key,r in zip(keys,vals):candidates[key]=provisional_best([candidates[key],r])
    selection=[];chosen={}
    for spec in specs:
        rows=[r for key,r in candidates.items() if key[0]==spec.name]
        require(all(r['success'] for r in rows),'Incomplete convergence in the complexity grid for '+spec.name+
                '; inspect optimizer_attempts.csv, then increase --maxiter/--starts.')
        winner=max(rows,key=lambda r:(r['validation_score'],-r['parameter_count']))
        chosen[spec.name]=winner
        for r in rows:selection.append(dict(model=spec.name,J=r['J'],ridge=r['ridge'],bound=r['bound'],
          validation_score=r['validation_score'],selected=r is winner,parameter_count=r['parameter_count']))
    csv_write(report/(prefix+'complexity_selection.csv'),selection)
    # Refits use all of year one, with the preselected structure and controls.
    jobs=[]
    for name,r in chosen.items():
        for s in range(args.starts):
            opts=dict(phase='full',maxiter=args.maxiter,ridge=r['ridge'])
            warm=np.array(r['parameters'])
            if s:warm+=np.random.default_rng(args.seed+s).normal(0,.03,len(warm))
            p=directory/f'full_{name}_s{s}.json'
            jobs.append((stage,r['spec'],r['J'],args.seed+70000+s,opts,str(p),warm.tolist(),r['bound']))
    vals=execute(jobs,fit_one,design,args.workers,stage+' year-one refits');attempts.extend(vals)
    write_attempts(report,prefix,attempts)
    fits={name:best([r for r in vals if r['spec']['name']==name]) for name in chosen}
    # A final full-year numerical-bound check does not alter complexity selection.
    jobs=[]
    for name,r in fits.items():
        if r['numerical_bounds']:
            opts=dict(phase='full',maxiter=args.maxiter,ridge=r['ridge'])
            jobs.append((stage,r['spec'],r['J'],args.seed+80000,opts,str(directory/f'full_wider_{name}.json'),
                         r['parameters'],r['bound']*2))
    vals=execute(jobs,fit_one,design,args.workers,stage+' final bound checks') if jobs else []
    attempts.extend(vals)
    for r in vals:fits[r['spec']['name']]=best([fits[r['spec']['name']],r])
    json_write(directory/'SELECTED_FITS.json',fits)
    write_attempts(report,prefix,attempts)
    scores,comparisons=summaries(fits,ev,meta,report,prefix)
    if stage=='perception':
        for name in ['noisy_tiers','noisy_common']:perception_decomposition(fits[name],ev,meta,report)
        coverage=[]
        for n,d in [('development',dev),('evaluation',ev)]:
            for period in range(3):coverage.append(dict(cohort=n,period=period,opportunities=int((d['period']==period).sum())))
        csv_write(report/'perception_sample_support.csv',coverage)
        json_write(report/'PERCEPTION_STATUS.json',dict(status='MODEL_COMPARISON_NOT_MECHANISM_IDENTIFICATION',
          scope='Numeric nonmate scores; exact bin boundaries excluded from all four matched fits',
          all_converged=all(r['success'] for r in fits.values()),
          numerical_bound_models=[n for n,r in fits.items() if r['numerical_bounds']],
          caveat='Perception separation requires recovery; tier gradients alone do not identify sigma.'))
    return fits


def multistart(d,template,meta,seed,starts,maxiter,warm_sources=()):
    attempts=[]
    for s in range(starts):
        model=Model(template['spec'],template['J'],meta,template['bound'])
        if s==0:warm=np.array(template['parameters'])
        elif s-1<len(warm_sources):warm=transfer(warm_sources[s-1],model,meta,seed+s)
        else:warm=model.start(seed+s)
        attempts.append(fit(d,Spec(**template['spec']),template['J'],meta,seed+s,maxiter,
                            template['ridge'],template['bound'],warm))
    return best(attempts)


def bootstrap_one(task):
    stage,rep,fits,options,path=task
    dev,ev,meta=data_for(stage);train=subset(dev,dev['period']<2)
    sig=binding(dict(stage=stage,rep=rep,fits=fits,options=options))
    def compute():
        rng=np.random.default_rng(options['seed']+99173*rep)
        train=dict(train_base)
        train['aw']=rng.multinomial(len(train['ptr'])-1,np.ones(len(train['ptr'])-1)/(len(train['ptr'])-1)).astype(float)
        ew=rng.multinomial(len(ev['ptr'])-1,np.ones(len(ev['ptr'])-1)/(len(ev['ptr'])-1)).astype(float)
        estimates={};failures={};score={};pg={}
        for j,(name,template) in enumerate(fits.items()):
            try:
                nested=[r for r in estimates.values() if r['J']==template['J']]
                est=multistart(train,template,meta,options['seed']+rep*1000+j*10,
                               options['starts'],options['maxiter'],nested[-1:])
                estimates[name]=est;pg[name]=est['projected_gradient']
                score[name]=predict(est,ev,meta)[1]
            except RuntimeError as exc:failures[name]=str(exc)
        pairs=NOISE_PAIRS if stage=='perception' else CORE_PAIRS
        if 'calibrated' in fits:pairs=pairs+[('both','calibrated')]
        rows=[]
        for a,b in pairs:
            if a not in fits or b not in fits:continue
            if a in score and b in score:
                stat=paired(ev,score[a],score[b],ev['period']==2,ew)
                rows.append(dict(rep=rep,candidate=a,baseline=b,gain=stat['gain'],equal_account_gain=stat['equal_account_gain']))
            else:rows.append(dict(rep=rep,candidate=a,baseline=b,gain=None,equal_account_gain=None))
        return dict(rows=rows,failures=failures,projected_gradients=pg,
          bound_models=[n for n,r in estimates.items() if r['numerical_bounds']])
    train_base=train
    return safe_result(path,sig,compute)


def run_bootstrap(private,report,args,stage='core'):
    fits=json_read(private/stage/'SELECTED_FITS.json')
    directory=private/stage/'bootstrap';directory.mkdir(exist_ok=True)
    options=dict(seed=args.seed+913,starts=args.refit_starts,maxiter=args.maxiter)
    jobs=[(stage,r,fits,options,str(directory/f'rep_{r:04d}.json')) for r in range(args.bootstrap_refits)]
    results=execute(jobs,bootstrap_one,private/'design',args.workers,stage+' refit bootstrap')
    rows=[r for value in results for r in value['rows']];summary=[]
    for a,b in sorted(set((r['candidate'],r['baseline']) for r in rows)):
        vv=[r['gain'] for r in rows if r['candidate']==a and r['baseline']==b and r['gain'] is not None]
        v=np.array(vv,float);count=len(v)
        eq=[r['equal_account_gain'] for r in rows if r['candidate']==a and r['baseline']==b and r['gain'] is not None]
        summary.append(dict(candidate=a,baseline=b,requested=args.bootstrap_refits,converged_pairs=count,
          failures=args.bootstrap_refits-count,bootstrap_se=float(v.std(ddof=1)) if count>1 else None,
          percentile_low=float(np.quantile(v,.025)) if count>=100 else None,
          percentile_high=float(np.quantile(v,.975)) if count>=100 else None,
          equal_account_low=float(np.quantile(eq,.025)) if count>=100 else None,
          equal_account_high=float(np.quantile(eq,.975)) if count>=100 else None,
          positive_draws=int((v>0).sum()),interval_status='AVAILABLE_CONDITIONAL_ON_SUCCESSFUL_REFITS' if count>=100 else 'WITHHELD_FEWER_THAN_100'))
    prefix='' if stage=='core' else 'perception_'
    csv_write(report/(prefix+'refit_bootstrap_draws.csv'),rows)
    csv_write(report/(prefix+'refit_bootstrap_summary.csv'),summary)
    json_write(report/(prefix+'BOOTSTRAP_STATUS.json'),dict(requested=args.bootstrap_refits,
      failed_replications=sum(bool(r['failures']) for r in results),
      numerical_bound_replications=sum(bool(r['bound_models']) for r in results),
      note='Independent development/evaluation account resampling; all fitted index and population parameters are refitted. Complexity, support, covariate transformations, and optional external calibration are frozen. Does not cover specification search or cross-account dependence.'))
    return summary


def recovery_one(task):
    stage,scenario,rep,generator,templates,options,path=task
    dev,ev,meta=data_for(stage);train=subset(dev,dev['period']<2)
    sig=binding(dict(stage=stage,scenario=scenario,rep=rep,generator=generator,templates=templates,options=options))
    def compute():
        rng=np.random.default_rng(options['seed']+rep*719+options['scenario_id']*100003)
        generated,types,p=simulate(generator,train,meta,rng)
        evaluation,etypes,ep=simulate(generator,ev,meta,rng)
        out=[]
        for j,(name,template) in enumerate(templates.items()):
            try:
                # Do not initialize recovery at the generating parameter vector.
                blank=dict(template);mdl=Model(template['spec'],template['J'],meta,template['bound'])
                blank['parameters']=mdl.start(options['seed']+rep*111+j).tolist()
                fitted=multistart(generated,blank,meta,options['seed']+rep*111+j,
                                  options['starts'],options['maxiter'])
                pred,ll=predict(fitted,evaluation,meta);test=evaluation['period']==2
                fm=Model(fitted['spec'],fitted['J'],meta,fitted['bound'])
                lp,_,_=fm.emissions(np.array(fitted['parameters']),evaluation)
                # Compare true type-conditional probabilities using optimal matching,
                # only when support sizes agree; label ordering is otherwise arbitrary.
                td=Model(generator['spec'],generator['J'],meta,generator['bound']).decode(np.array(generator['parameters']))
                fd=fm.decode(np.array(fitted['parameters']))
                cost_rmse=None;state_rmse=None;theta_rmse=None;sigma_rmse=None
                if generator['J']==fitted['J']:
                    distance=((td['effect'][:,None,meta['support']]-fd['effect'][None,:,meta['support']])**2).mean(axis=2)
                    distance+=(td['alpha'][:,None]-fd['alpha'][None,:])**2
                    a,b=linear_sum_assignment(distance)
                    cost_rmse=float(np.sqrt(np.mean((td['B'][a]-fd['B'][b])**2))/10)
                    state_rmse=float(np.sqrt(np.mean((td['effect'][a][:,meta['support']]-fd['effect'][b][:,meta['support']])**2)))
                    if td['theta'] is not None and fd['theta'] is not None:theta_rmse=float(np.sqrt(np.mean((td['theta'][a]-fd['theta'][b])**2)))
                if stage=='perception':sigma_rmse=float(np.sqrt(np.mean((td['sigma']-fd['sigma'])**2)))
                out.append(dict(scenario=scenario,rep=rep,model=name,success=True,
                  mean_log_score=float(ll[test].mean()),train_grants=int(generated['y'].sum()),
                  train_expected_grants=float(p.sum()),evaluation_grants=int(evaluation['y'][test].sum()),
                  development_accounts=len(train['ptr'])-1,evaluation_accounts=len(ev['ptr'])-1,
                  matched_cost_rmse=cost_rmse,matched_state_rmse=state_rmse,matched_theta_rmse=theta_rmse,
                  sigma_rmse_cp=sigma_rmse,numerical_bounds=';'.join(fitted['numerical_bounds'])))
            except RuntimeError as exc:out.append(dict(scenario=scenario,rep=rep,model=name,success=False,error=str(exc)))
        return out
    return safe_result(path,sig,compute)


def run_recovery(private,report,args,stage='core'):
    fits=json_read(private/stage/'SELECTED_FITS.json');meta=json_read(private/'design'/'DESIGN.json')
    if stage=='core':
        templates={k:fits[k] for k in ['level','desert','cost','both','free_index','type_cells'] if k in fits}
        generators={k:fits[k] for k in ['level','desert','cost','both','type_cells'] if k in fits}
        if 'both' in fits:
            base=json.loads(json.dumps(fits['both']));m=Model(base['spec'],base['J'],meta,base['bound'])
            v=np.array(base['parameters']);v[m.slices['amplitude']]=0.
            zero=dict(base,parameters=v.tolist());generators['zero_cost']=zero
            v=np.array(base['parameters'])
            for key in ['alpha','theta','amplitude']:
                a=v[m.slices[key]];v[m.slices[key]]=a.mean()+.03*(a-a.mean())
            generators['nearly_coincident_types']=dict(base,parameters=v.tolist())
    else:
        templates=fits;generators={k:fits[k] for k in ['accurate_tiers','noisy_tiers','noisy_common']}
        base=json.loads(json.dumps(fits['noisy_tiers']));m=Model(base['spec'],base['J'],meta,base['bound'])
        v=np.array(base['parameters']);v[m.slices['sigma']]=.2
        generators['weak_perception_20cp']=dict(base,parameters=v.tolist())
    directory=private/stage/'recovery';directory.mkdir(exist_ok=True)
    jobs=[]
    for s,(scenario,generator) in enumerate(generators.items()):
        options=dict(seed=args.seed+971,scenario_id=s,starts=args.refit_starts,maxiter=args.maxiter)
        for r in range(args.recovery_reps):jobs.append((stage,scenario,r,generator,templates,options,str(directory/f'{scenario}_{r:04d}.json')))
    results=execute(jobs,recovery_one,private/'design',args.workers,stage+' full-design recovery')
    rows=[r for batch in results for r in batch]
    winners=[]
    for scenario in generators:
        for r in range(args.recovery_reps):
            rr=[x for x in rows if x['scenario']==scenario and x['rep']==r]
            complete=all(x['success'] for x in rr) and len(rr)==len(templates)
            good=[x for x in rr if x['success']]
            winner=max(good,key=lambda x:x['mean_log_score'])['model'] if complete else None
            winners.append(dict(scenario=scenario,rep=r,complete=complete,best_predictive_model=winner))
    prefix='' if stage=='core' else 'perception_'
    csv_write(report/(prefix+'recovery_results.csv'),rows)
    csv_write(report/(prefix+'recovery_winners.csv'),winners)
    json_write(report/(prefix+'RECOVERY_STATUS.json'),dict(replications_per_scenario=args.recovery_reps,
      uses_full_observed_account_histories=True,simulated_choices_only=True,
      failed_fits=sum(not x['success'] for x in rows),
      note='Fitted-model generators plus zero/weak/near-collapsed scenarios; complexity frozen from real training validation. Not a causal validation or proof of unique identification. Inspect event counts and parameter recovery, not just winner frequencies.'))
    return winners
