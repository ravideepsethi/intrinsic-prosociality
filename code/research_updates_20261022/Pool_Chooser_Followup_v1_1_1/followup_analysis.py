"""Chronological selection, safe resumability, refit bootstrap and recovery."""
from __future__ import annotations
import bootstrap_path
from concurrent.futures import ProcessPoolExecutor,as_completed
from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
from scipy.optimize import linear_sum_assignment
from io_utils import *
from prepare import subset,perception_subset
from engine import Spec,Model,CHALLENGE,SWITCHING,fit,predict,simulate,transfer,parameters
from model import CORE,PERCEPTION
from diagnostics import paired,perception_decomposition,CORE_PAIRS,NOISE_PAIRS
from followup_diagnostics import summaries, pairs_for

_CACHE={}

# Order restrictions before their relaxations. Final-year fits and every
# resample need these starts too; validation-only nesting is insufficient.
NESTS={
  'cost':['level'],
  'premium_only':['no_cost'],
  'desert':['level','board_only','no_stage','no_expected','desert_no_cost','no_cost'],
  'both':['desert','cost','no_cost','premium_only'],
  'free_index':['both'], 'type_cells':['free_index'],
  'separate_costs':['both'], 'signed_costs':['separate_costs'],
  'accurate_tiers':['accurate_common'], 'noisy_common':['accurate_common'],
  'noisy_tiers':['accurate_tiers','noisy_common']}
for _kind in ['iid','hmm']:
    for _family in ['willingness','gate','gatecost','unrestricted']:
        NESTS[_kind+'_'+_family]=['desert']+(['iid_'+_family] if _kind=='hmm' else [])
    NESTS[_kind+'_gatecost'] += [_kind+'_gate']
    NESTS[_kind+'_unrestricted'] += [_kind+'_willingness',_kind+'_gate',_kind+'_gatecost']


def fit_order(fits):
    ordered=[];remaining=list(fits)
    while remaining:
        ready=[n for n in remaining if all(s not in remaining for s in NESTS.get(n,[]))]
        require(bool(ready),'Cycle in model nesting graph')
        for n in ready:ordered.append(n);remaining.remove(n)
    return ordered


def compatible_sources(name,template,fits):
    return [(s,fits[s]) for s in NESTS.get(name,[]) if s in fits and fits[s]['J']==template['J']]


def initialize(design_path):
    global _CACHE
    root=Path(design_path)
    _CACHE={name:dict(np.load(root/(name+'.npz'),allow_pickle=False)) for name in ['development','evaluation']}
    _CACHE['meta']=json_read(root/'DESIGN.json')
    _CACHE['suite']=json_read(root/'FOLLOWUP.json')['suite']


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
    available=SWITCHING if _CACHE['suite']=='switching' else CHALLENGE
    return [s for s in available if s.name in args.models]


def run_models(private,report,args,stage='core',inherited=None):
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
    nests['desert']+=['board_only','no_stage','no_expected','desert_no_cost']
    for family in ['willingness','gate','gatecost','unrestricted']:
        nests['iid_'+family]=['desert']
        nests['hmm_'+family]=['desert','iid_'+family]
    nests['iid_gatecost']+=['iid_gate']
    nests['hmm_gatecost']+=['hmm_gate']
    nests['iid_unrestricted']+=['iid_willingness','iid_gate','iid_gatecost']
    nests['hmm_unrestricted']+=['hmm_willingness','hmm_gate','hmm_gatecost','iid_unrestricted']
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
    json_write(report/(prefix+'SEARCH_DIAGNOSTICS.json'),dict(
      selected_at_max_support=[n for n,r in chosen.items() if r['J']==max(args.support_grid)],
      selected_at_min_ridge=[n for n,r in chosen.items() if r['ridge']==min(args.ridge_grid)],
      selected_at_max_ridge=[n for n,r in chosen.items() if r['ridge']==max(args.ridge_grid)],
      note='Search-edge selections are diagnostics, not numerical parameter-bound hits. Repeatedly expanding after seeing evaluation scores is specification search.'))
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
    if inherited:
        fits={**inherited,**fits}
        json_write(report/'INHERITED_MODEL_SELECTION.json',dict(
          models={n:dict(J=r['J'],ridge=r['ridge']) for n,r in inherited.items()},
          note='Complexity inherited from the expanded parent run; all full-year fits receive the same final nesting repair. No old complexity grid is recomputed.'))
    fits=run_repair(private,report,args,stage,fits=fits,score=False)
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


def run_repair(private,report,args,stage='core',fits=None,score=True):
    """Independent full-year starts and feasible cross-starts, with a guard.

    The selected J/ridge and chronology remain fixed. Never choose on year two.
    Cache signatures bind the original inputs, so restarting is deterministic.
    """
    initialize(private/'design');dev,ev,meta=data_for(stage)
    train=subset(dev,dev['period']<2);directory=private/stage
    directory.mkdir(exist_ok=True)
    if fits is None:fits=json_read(directory/'IMPORTED_FITS.json')
    repaired={};attempts=[];audit=[]
    for name in fit_order(fits):
        template=fits[name];sources=compatible_sources(name,template,repaired)
        bound=max([template['bound']]+[r['bound'] for _,r in sources])
        if template['numerical_bounds']:bound=max(bound,template['bound']*2)
        mdl=Model(template['spec'],template['J'],meta,bound)
        starts=[('self',np.asarray(template['parameters']))]
        starts += [('independent_'+str(s),mdl.start(args.seed+91000+s)) for s in range(1,args.starts)]
        starts += [('from_'+s,transfer(r,mdl,meta,args.seed)) for s,r in sources]
        opts=dict(phase='full',maxiter=args.maxiter,ridge=template['ridge'])
        jobs=[];witness=[]
        lo,hi=np.array(mdl.bounds).T
        for j,(label,warm) in enumerate(starts):
            warm=np.clip(warm,lo,hi)
            objective=mdl.objective(warm,train,template['ridge'])[0]
            witness.append((label,float(objective)))
            jobs.append((stage,template['spec'],template['J'],args.seed+91000+j,opts,
              str(directory/f'final_repair_{name}_{label}.json'),warm.tolist(),bound))
        values=execute(jobs,fit_one,private/'design',args.workers,'full-year repair '+name)
        attempts.extend(values)
        winner=best([template]+values)
        floor=min(x for _,x in witness)
        require(winner['objective']<=floor+1e-8,
          f'{name}: best converged full-year fit is worse than a feasible start; increase --maxiter/--starts. No repaired result released.')
        repaired[name]=winner
        audit += [dict(model=name,start=label,J=template['J'],ridge=template['ridge'],
          before=template['objective'],feasible_start_objective=value,
          after=winner['objective'],after_minus_feasible=winner['objective']-value,
          violation=bool(winner['objective']>value+1e-8)) for label,value in witness]
    prefix='' if stage=='core' else 'perception_'
    csv_write(report/(prefix+'final_nesting_audit.csv'),audit)
    write_attempts(report,prefix+'repair_',attempts)
    json_write(directory/'SELECTED_FITS.json',repaired)
    json_write(report/(prefix+'REPAIR_STATUS.json'),dict(status='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW',
      selected_complexity_unchanged=True,year_two_used_to_select_fits=False,
      numerical_bound_models=[n for n,r in repaired.items() if r['numerical_bounds']],
      note='Checks all supplied feasible starts at the target penalty. This is not proof of a global optimum.'))
    if score:summaries(repaired,ev,meta,report,prefix)
    return repaired


def multistart(d,template,meta,seed,starts,maxiter,warm_sources=()):
    attempts=[]
    bound=max([template['bound']]+[r['bound'] for r in warm_sources])
    if template['numerical_bounds']:bound=max(bound,template['bound']*2)
    model=Model(template['spec'],template['J'],meta,bound)
    warm_points=[np.asarray(template['parameters'])]+[model.start(seed+s) for s in range(1,starts)]
    warm_points += [transfer(r,model,meta,seed) for r in warm_sources]
    lo,hi=np.array(model.bounds).T;feasible=[]
    for s,warm in enumerate(warm_points):
        warm=np.clip(warm,lo,hi);feasible.append(model.objective(warm,d,template['ridge'])[0])
        attempts.append(fit(d,Spec(**template['spec']),template['J'],meta,seed+s,maxiter,
                            template['ridge'],bound,warm))
    result=best(attempts)
    require(result['objective']<=min(feasible)+1e-8,'Converged resample fit is worse than a feasible start')
    return result


def bootstrap_one(task):
    stage,rep,fits,options,path=task
    dev,ev,meta=data_for(stage);train=subset(dev,dev['period']<2)
    sig=binding(dict(stage=stage,rep=rep,fits=fits,options=options))
    def compute():
        rng=np.random.default_rng(options['seed']+99173*rep)
        train=dict(train_base)
        train['aw']=rng.multinomial(len(train['ptr'])-1,np.ones(len(train['ptr'])-1)/(len(train['ptr'])-1)).astype(float)
        ew=rng.multinomial(len(ev['ptr'])-1,np.ones(len(ev['ptr'])-1)/(len(ev['ptr'])-1)).astype(float)
        estimates={};failures={};score={};pg={};parameter_draws=[]
        for j,name in enumerate(fit_order(fits)):
            template=fits[name]
            try:
                nested=[r for _,r in compatible_sources(name,template,estimates)]
                est=multistart(train,template,meta,options['seed']+rep*1000+j*10,
                               options['starts'],options['maxiter'],nested)
                estimates[name]=est;pg[name]=est['projected_gradient']
                score[name]=predict(est,ev,meta)[1]
                tm=Model(template['spec'],template['J'],meta,template['bound'])
                td=tm.decode(np.asarray(template['parameters']))
                fm=Model(est['spec'],est['J'],meta,est['bound']);fd=fm.decode(np.asarray(est['parameters']))
                distance=((td['effect'][:,None,meta['support']]-fd['effect'][None,:,meta['support']])**2).mean(axis=2)
                distance+=(td['alpha'][:,None]-fd['alpha'][None,:])**2
                a,b=linear_sum_assignment(distance)
                for k,l in zip(a,b):
                    parameter_draws.append(dict(rep=rep,model=name,reference_type=int(k),
                      alpha=float(fd['alpha'][l]),theta=None if fd['theta'] is None else float(fd['theta'][l]),
                      share=float(np.exp(fd['lp'][:,l]).mean()),
                      premium=float(fd['B'][l,0]/10),loss=float(fd['B'][l,1]/10),
                      lower_theta=float(fd['lower_theta'][l]) if 'lower_theta' in fd else None,
                      entry=float(np.exp(fd['logT'][0,1])) if 'logT' in fd else None,
                      retention=float(np.exp(fd['logT'][1,1])) if 'logT' in fd else None))
            except RuntimeError as exc:failures[name]=str(exc)
        pairs=pairs_for(fits)
        if 'calibrated' in fits:pairs=pairs+[('both','calibrated')]
        rows=[]
        for a,b in pairs:
            if a not in fits or b not in fits:continue
            if a in score and b in score:
                stat=paired(ev,score[a],score[b],ev['period']==2,ew)
                rows.append(dict(rep=rep,candidate=a,baseline=b,gain=stat['gain'],equal_account_gain=stat['equal_account_gain']))
            else:rows.append(dict(rep=rep,candidate=a,baseline=b,gain=None,equal_account_gain=None))
        return dict(rows=rows,parameter_draws=parameter_draws,failures=failures,projected_gradients=pg,
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
    csv_write(report/(prefix+'refit_parameter_draws.csv'),[x for r in results for x in r['parameter_draws']])
    json_write(report/(prefix+'BOOTSTRAP_STATUS.json'),dict(requested=args.bootstrap_refits,
      failed_replications=sum(bool(r['failures']) for r in results),
      numerical_bound_replications=sum(bool(r['bound_models']) for r in results),
      note='Independent development/evaluation account resampling; all index/population/transition parameters are refitted. Complexity, support and covariate transformations are frozen. Does not cover model search, prior use of this evaluation cohort, or cross-account dependence. Intervals are conditional on successful fits; inspect failures and boundary counts.'))
    return summary


def recovery_one(task):
    stage,scenario,rep,generator,templates,options,path=task
    dev,ev,meta=data_for(stage);train=subset(dev,dev['period']<2)
    sig=binding(dict(stage=stage,scenario=scenario,rep=rep,generator=generator,templates=templates,options=options))
    def compute():
        rng=np.random.default_rng(options['seed']+rep*719+options['scenario_id']*100003)
        generated,types,p=simulate(generator,train,meta,rng)
        evaluation,etypes,ep=simulate(generator,ev,meta,rng)
        out=[];recovered={}
        for j,name in enumerate(fit_order(templates)):
            template=templates[name]
            try:
                # Do not initialize recovery at the generating parameter vector.
                blank=dict(template);mdl=Model(template['spec'],template['J'],meta,template['bound'])
                blank['parameters']=mdl.start(options['seed']+rep*111+j).tolist()
                fitted=multistart(generated,blank,meta,options['seed']+rep*111+j,
                                  options['starts'],options['maxiter'],
                                  [r for _,r in compatible_sources(name,template,recovered)])
                recovered[name]=fitted
                pred,ll=predict(fitted,evaluation,meta);test=evaluation['period']==2
                fm=Model(fitted['spec'],fitted['J'],meta,fitted['bound'])
                # Compare true type-conditional probabilities using optimal matching,
                # only when support sizes agree; label ordering is otherwise arbitrary.
                td=Model(generator['spec'],generator['J'],meta,generator['bound']).decode(np.array(generator['parameters']))
                fd=fm.decode(np.array(fitted['parameters']))
                cost_rmse=None;state_rmse=None;theta_rmse=None;sigma_rmse=None;lower_rmse=None;transition_rmse=None
                if generator['J']==fitted['J']:
                    distance=((td['effect'][:,None,meta['support']]-fd['effect'][None,:,meta['support']])**2).mean(axis=2)
                    distance+=(td['alpha'][:,None]-fd['alpha'][None,:])**2
                    a,b=linear_sum_assignment(distance)
                    cost_rmse=float(np.sqrt(np.mean((td['B'][a]-fd['B'][b])**2))/10)
                    state_rmse=float(np.sqrt(np.mean((td['effect'][a][:,meta['support']]-fd['effect'][b][:,meta['support']])**2)))
                    if td['theta'] is not None and fd['theta'] is not None:theta_rmse=float(np.sqrt(np.mean((td['theta'][a]-fd['theta'][b])**2)))
                    if 'lower_theta' in td and 'lower_theta' in fd:
                        lower_rmse=float(np.sqrt(np.mean((td['lower_theta'][a]-fd['lower_theta'][b])**2)))
                        transition_rmse=float(np.sqrt(np.mean((np.exp(td['logT'])-np.exp(fd['logT']))**2)))
                if stage=='perception':sigma_rmse=float(np.sqrt(np.mean((td['sigma']-fd['sigma'])**2)))
                out.append(dict(scenario=scenario,rep=rep,model=name,success=True,
                  mean_log_score=float(ll[test].mean()),train_grants=int(generated['y'].sum()),
                  train_expected_grants=float(p.sum()),evaluation_grants=int(evaluation['y'][test].sum()),
                  development_accounts=len(train['ptr'])-1,evaluation_accounts=len(ev['ptr'])-1,
                  matched_cost_rmse=cost_rmse,matched_state_rmse=state_rmse,matched_theta_rmse=theta_rmse,
                  matched_lower_theta_rmse=lower_rmse,transition_probability_rmse=transition_rmse,
                  sigma_rmse_cp=sigma_rmse,numerical_bounds=';'.join(fitted['numerical_bounds'])))
            except RuntimeError as exc:out.append(dict(scenario=scenario,rep=rep,model=name,success=False,error=str(exc)))
        return out
    return safe_result(path,sig,compute)


def run_recovery(private,report,args,stage='core'):
    fits=json_read(private/stage/'SELECTED_FITS.json');meta=json_read(private/'design'/'DESIGN.json')
    if stage=='core' and any(n.startswith('hmm_') for n in fits):
        templates=fits
        generators={k:fits[k] for k in ['desert','iid_unrestricted','hmm_willingness','hmm_gate','hmm_unrestricted'] if k in fits}
    elif stage=='core':
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
