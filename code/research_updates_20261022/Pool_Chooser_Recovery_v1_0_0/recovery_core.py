"""Full-history simulation with independent starts and paired forecast recovery."""
from __future__ import annotations
import os
for _name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS']:
    os.environ[_name]='1'
import sys,time,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'reference_wide'))
import run_wide_bootstrap as wide
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.special import xlogy,xlog1py
from engine import Model,Spec,fit,predict,simulate,transfer
from diagnostics import paired
from followup_diagnostics import pairs_for
from io_utils import binding,json_read,json_write,require
from table_io import csv_write
import followup_analysis as analysis

MODELS=['level','desert','cost','both']
SCENARIOS=['level','desert','cost']


def clean_template(fitted):
    return {k:fitted[k] for k in ['spec','J','ridge','bound']}


def independent_start(model,seed,number):
    """Generic starts include the near-additive region; never inspect a generator."""
    v=model.start(seed);rng=np.random.default_rng(seed+117)
    if number%6>=3:
        offset=[.8,.95,.975][number%6-3];den=1-offset
        alpha=v[model.slices['alpha']].copy()
        anchored=v[model.slices['theta']].copy()
        raw=np.minimum(anchored/den,.90*model.bound)
        v[model.slices['theta']]=raw
        v[model.slices['f0']]=offset
        v[model.slices['alpha']]=alpha-np.broadcast_to(raw,(model.J,))*offset
        v[model.slices['fother']]=1+den*(np.array([-.6,.6,1.2])+rng.normal(0,.05,3))
        v[model.slices['g']]=1+den*(np.array([.6,.3,-.2])+rng.normal(0,.05,3))
        v[model.slices['h']]=1+den*(np.array([.3,.15,-.15,-.3])+rng.normal(0,.05,4))
    lo,hi=np.asarray(model.bounds).T
    require(np.all(np.isfinite(v)) and np.all(v>=lo) and np.all(v<=hi),'Independent start is outside bounds')
    return v


def fit_simulated(data,template,restrictions,meta,settings,seed,path,data_hash):
    require(set(template)=={'spec','J','ridge','bound'},'Estimation template must not carry fitted truth vectors')
    signature=binding(dict(template=template,restrictions=restrictions,settings=settings,seed=seed,data_hash=data_hash))
    def compute():
        model=Model(template['spec'],template['J'],meta,template['bound'])
        warm=[('independent_'+str(j),independent_start(model,seed+j,j)) for j in range(settings['starts'])]
        warm += [('restriction_'+name,transfer(value,model,meta,seed)) for name,value in restrictions]
        trials=[];witness=[]
        for j,(label,start) in enumerate(warm):
            lo,hi=np.asarray(model.bounds).T
            require(np.all(start>=lo-1e-10) and np.all(start<=hi+1e-10),'Infeasible transferred start')
            witness.append(dict(start=label,objective=float(model.objective(start,data,template['ridge'])[0])))
            result=fit(data,Spec(**template['spec']),template['J'],meta,seed+j,settings['maxiter'],template['ridge'],template['bound'],start)
            result['start_label']=label;trials.append(result)
        try:
            winner=analysis.best(trials)
            require(winner['objective']<=min(x['objective'] for x in witness)+1e-8,'Selected fit is worse than a feasible start')
            error=None
        except RuntimeError as exc:winner=None;error=str(exc)
        return dict(fit=winner,attempts=trials,feasible_starts=witness,error=error)
    return analysis.safe_result(path,signature,compute)


def fingerprint(*arrays):
    h=hashlib.sha256()
    for array in arrays:
        a=np.ascontiguousarray(array);h.update(str(a.shape).encode());h.update(a.dtype.str.encode());h.update(memoryview(a).cast('B'))
    return h.hexdigest()


def simulate_panel(generator,data,meta,seed,scenario,rep,stream):
    rng=np.random.default_rng(np.random.SeedSequence([seed,SCENARIOS.index(scenario),rep,stream]))
    return simulate(generator,data,meta,rng)


def simulation_job(task):
    scenario,rep,generator,templates,settings,observed,path=task
    signature=binding(dict(scenario=scenario,rep=rep,generator=generator,templates=templates,settings=settings,observed=observed))
    def compute():
        begin=time.monotonic();training=analysis.training_for('core');_,evaluation,meta=analysis.data_for('core')
        train,types,tp=simulate_panel(generator,training,meta,settings['seed'],scenario,rep,0)
        ev,etypes,ep=simulate_panel(generator,evaluation,meta,settings['seed'],scenario,rep,1)
        test=ev['period']==2;require(test.any(),'No year-two evaluation opportunities')
        identity=fingerprint(train['y'],ev['y'],types,etypes)
        folder=Path(path).with_suffix('');folder.mkdir(exist_ok=True)
        fits={};records={};failures={}
        # Fitting sees synthetic development outcomes, clean templates and fitted
        # restrictions only. Generating vectors and evaluation outcomes are not inputs.
        for j,name in enumerate(analysis.fit_order(templates)):
            aux=analysis.compatible_sources(name,templates[name],fits)
            record=fit_simulated(train,templates[name],aux,meta,settings,
                settings['seed']+SCENARIOS.index(scenario)*10000019+rep*1019+j*31,
                folder/(name+'.json'),fingerprint(train['y']))
            records[name]=record
            if record['fit'] is None:failures[name]=record['error']
            else:fits[name]=record['fit']
        # Oracle calculations take place only after estimation and never supply starts.
        oracle_p,oracle_ll=predict(generator,ev,meta)
        gm=Model(generator['spec'],generator['J'],meta,generator['bound'])
        gd=gm.decode(np.asarray(generator['parameters']))
        generator_objective=float(gm.objective(np.asarray(generator['parameters']),train,generator['ridge'])[0])
        worse_than_generator=None if scenario not in fits else fits[scenario]['objective']>generator_objective+1e-8
        oracle_score=float(oracle_ll[test].mean());scores={};fit_rows=[];parameter_rows=[];state_rows=[]
        ids=ev['ids'][test];counts=np.bincount(ids,minlength=len(ev['ptr'])-1);active=counts>0
        cell_counts=np.bincount(train['cell'],minlength=100);support=np.asarray(meta['support'])
        for name in MODELS:
            if name not in fits:
                fit_rows.append(dict(scenario=scenario,rep=rep,model=name,success=False,error=failures[name]));continue
            result=fits[name];prob,ll=predict(result,ev,meta);scores[name]=ll
            fm=Model(result['spec'],result['J'],meta,result['bound']);fd=fm.decode(np.asarray(result['parameters']))
            op=np.clip(oracle_p[test],1e-15,1-1e-15);pp=np.clip(prob[test],1e-15,1-1e-15)
            kl=xlogy(op,op/pp)+xlog1py(1-op,-op)-xlog1py(1-op,-pp)
            equal=float(np.mean(np.bincount(ids,weights=ll[test],minlength=len(counts))[active]/counts[active]))
            matched={}
            if name==scenario:
                # Match labels by state utilities and cost responses, using fixed
                # design weights. These parameter diagnostics do not affect selection.
                ts=gd['alpha'][:,None]+gd['effect'][:,support]
                fs=fd['alpha'][:,None]+fd['effect'][:,support]
                distance=np.average((ts[:,None,:]-fs[None,:,:])**2,axis=2,weights=cell_counts[support])
                scales=np.array([np.std(train['kappa']),np.std(train['loss'])])
                distance+=np.sum(((gd['B'][:,None,:]-fd['B'][None,:,:])*scales)**2,axis=2)
                aa,bb=linear_sum_assignment(distance)
                matched=dict(matched_theta_rmse=float(np.sqrt(np.mean((gd['theta'][aa]-fd['theta'][bb])**2))),
                    matched_alpha_rmse=float(np.sqrt(np.mean((gd['alpha'][aa]-fd['alpha'][bb])**2))),
                    matched_cost_rmse=float(np.sqrt(np.mean((gd['B'][aa]-fd['B'][bb])**2))/10),
                    index_rmse=float(np.sqrt(np.average((gd['A'][support]-fd['A'][support])**2,weights=cell_counts[support]))))
                for a,b in zip(aa,bb):
                    parameter_rows.append(dict(scenario=scenario,rep=rep,true_type=int(a),fitted_type=int(b),
                        true_alpha=float(gd['alpha'][a]),fitted_alpha=float(fd['alpha'][b]),
                        true_theta=float(gd['theta'][a]),fitted_theta=float(fd['theta'][b]),
                        true_share=float(np.exp(gd['lp'][:,a]).mean()),fitted_share=float(np.exp(fd['lp'][:,b]).mean()),
                        true_premium=float(gd['B'][a,0]/10),fitted_premium=float(fd['B'][b,0]/10),
                        true_loss=float(gd['B'][a,1]/10),fitted_loss=float(fd['B'][b,1]/10)))
            fit_rows.append(dict(scenario=scenario,rep=rep,model=name,success=True,error=None,
                mean_log_score=float(ll[test].mean()),equal_account_log_score=equal,
                oracle_log_score=oracle_score,oracle_score_gap=float((oracle_ll-ll)[test].mean()),
                oracle_probability_rmse=float(np.sqrt(np.mean((oracle_p[test]-prob[test])**2))),
                oracle_mean_kl=float(kl.mean()),predicted_grants=float(prob[test].sum()),
                capped=bool(result['numerical_bounds']),numerical_bounds=';'.join(result['numerical_bounds']),
                near_theta_cap=bool(np.max(fd['raw_theta'])>=.99*result['bound']),
                max_raw_theta=float(np.max(fd['raw_theta'])),index_offset=fd['index_offset'],
                projected_gradient=result['projected_gradient'],objective=result['objective'],**matched))
            for board in range(5):
                mask=test&(ev['board']==board)
                if mask.any():state_rows.append(dict(scenario=scenario,rep=rep,model=name,board=board,
                    opportunities=int(mask.sum()),grants=int(ev['y'][mask].sum()),predicted_grants=float(prob[mask].sum()),
                    mean_log_score=float(ll[mask].mean()),oracle_score_gap=float((oracle_ll-ll)[mask].mean())))
        comparison=[]
        for a,b in pairs_for(templates):
            row=dict(scenario=scenario,rep=rep,candidate=a,baseline=b,success=a in scores and b in scores)
            if row['success']:
                stat=paired(ev,scores[a],scores[b],test)
                threshold=observed[a+'|'+b]
                row.update(stat,observed_gain=threshold['gain'],observed_equal_gain=threshold['equal_account_gain'],
                    reaches_observed_gain=stat['gain']>=threshold['gain'],
                    reaches_observed_equal_gain=stat['equal_account_gain']>=threshold['equal_account_gain'])
            comparison.append(row)
        complete=len(fits)==len(MODELS);winner=tied=equal_winner=None
        if complete:
            best=max(r['mean_log_score'] for r in fit_rows)
            tied=';'.join(r['model'] for r in fit_rows if abs(r['mean_log_score']-best)<=1e-12)
            winner=tied if ';' not in tied else 'tie'
            equal_best=max(r['equal_account_log_score'] for r in fit_rows)
            names=[r['model'] for r in fit_rows if abs(r['equal_account_log_score']-equal_best)<=1e-12]
            equal_winner=names[0] if len(names)==1 else 'tie'
        pairs={(r['candidate'],r['baseline']):r for r in comparison}
        headline=[pairs[('desert','level')],pairs[('desert','cost')]]
        joint_available=all(r['success'] for r in headline)
        outcome=dict(scenario=scenario,rep=rep,complete=complete,best_predictive_model=winner,
            tied_models=tied,best_equal_account_model=equal_winner,generator_fit_worse_than_truth=worse_than_generator,
            headline_available=joint_available,
            desert_beats_both=None if not joint_available else all(r['gain']>0 for r in headline),
            desert_reaches_both_observed=None if not joint_available else all(r['reaches_observed_gain'] for r in headline),
            desert_reaches_both_observed_equal=None if not joint_available else all(r['reaches_observed_equal_gain'] for r in headline))
        events=dict(scenario=scenario,rep=rep,development_accounts=len(train['ptr'])-1,
            development_opportunities=len(train['y']),development_grants=int(train['y'].sum()),
            development_expected_grants=float(tp.sum()),evaluation_accounts=len(ev['ptr'])-1,
            year_two_accounts=int(active.sum()),year_two_opportunities=int(test.sum()),
            year_two_grants=int(ev['y'][test].sum()),year_two_expected_grants=float(ep[test].sum()))
        attempts=[];guards=[]
        for name,record in records.items():
            for r in record['attempts']:attempts.append(dict(scenario=scenario,rep=rep,model=name,start=r['start_label'],
                success=r['success'],objective=r['objective'],projected_gradient=r['projected_gradient'],
                seconds=r['elapsed_seconds'],iterations=r['iterations'],bound=r['bound'],numerical_bounds=';'.join(r['numerical_bounds'])))
            for w in record['feasible_starts']:
                delta=None if record['fit'] is None else record['fit']['objective']-w['objective']
                guards.append(dict(scenario=scenario,rep=rep,model=name,start=w['start'],after_minus_feasible=delta,
                    violation=None if delta is None else delta>1e-8))
        return dict(scenario=scenario,rep=rep,events=events,outcome=outcome,comparisons=comparison,fit_rows=fit_rows,
            parameter_rows=parameter_rows,state_rows=state_rows,attempts=attempts,guards=guards,failures=failures,
            simulation_sha256=identity,elapsed_seconds=time.monotonic()-begin,
            generator_objective=generator_objective)
    return analysis.safe_result(path,signature,compute)


def wilson(successes,total):
    if not total:return dict(count=int(successes),n=0,rate=None,mc_se=None,wilson_low=None,wilson_high=None)
    z=1.959963984540054;p=successes/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den;half=z*np.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return dict(count=int(successes),n=int(total),rate=p,mc_se=float(np.sqrt(p*(1-p)/total)),
        wilson_low=max(0.,center-half),wilson_high=min(1.,center+half))


def summarize(results,report):
    rows=[x for r in results for x in r['comparisons']];fits=[x for r in results for x in r['fit_rows']]
    outcomes=[r['outcome'] for r in results];events=[r['events'] for r in results];comparisons=[];selection=[];model_status=[]
    for scenario in SCENARIOS:
        out=[x for x in outcomes if x['scenario']==scenario];complete=[x for x in out if x['complete']]
        for name in MODELS+['tie']:
            selection.append(dict(scenario=scenario,criterion='highest_opportunity_score',selected_model=name,
                requested=len(out),**wilson(sum(x['best_predictive_model']==name for x in complete),len(complete))))
            selection.append(dict(scenario=scenario,criterion='highest_equal_account_score',selected_model=name,
                requested=len(out),**wilson(sum(x['best_equal_account_model']==name for x in complete),len(complete))))
        for criterion in ['desert_beats_both','desert_reaches_both_observed','desert_reaches_both_observed_equal']:
            valid=[x[criterion] for x in out if x[criterion] is not None]
            selection.append(dict(scenario=scenario,criterion=criterion,selected_model='desert',requested=len(out),**wilson(sum(valid),len(valid))))
        for a,b in pairs_for({n:{} for n in MODELS}):
            selected=[r for r in rows if r['scenario']==scenario and r['candidate']==a and r['baseline']==b]
            valid=[r for r in selected if r['success']];v=np.array([r['gain'] for r in valid]);eq=np.array([r['equal_account_gain'] for r in valid])
            for weight,values,threshold_key in [('opportunity',v,'reaches_observed_gain'),('account',eq,'reaches_observed_equal_gain')]:
                row=dict(scenario=scenario,candidate=a,baseline=b,weighting=weight,requested=len(selected),successful=len(valid),
                    mean_gain=float(values.mean()) if len(values) else None,
                    simulation_sd=float(values.std(ddof=1)) if len(values)>1 else None,
                    mean_gain_mc_se=float(values.std(ddof=1)/np.sqrt(len(values))) if len(values)>1 else None,
                    simulation_q025=float(np.quantile(values,.025)) if len(values)>=100 else None,
                    simulation_q975=float(np.quantile(values,.975)) if len(values)>=100 else None)
                row.update({'positive_'+k:v for k,v in wilson(int((values>0).sum()),len(values)).items()})
                row.update({'observed_margin_'+k:v for k,v in wilson(sum(r[threshold_key] for r in valid),len(valid)).items()})
                comparisons.append(row)
        for name in MODELS:
            rr=[r for r in fits if r['scenario']==scenario and r['model']==name];valid=[r for r in rr if r['success']]
            model_status.append(dict(scenario=scenario,model=name,requested=len(rr),successful=len(valid),failed=len(rr)-len(valid),
                capped=sum(r['capped'] for r in valid),near_theta_cap=sum(r['near_theta_cap'] for r in valid),
                mean_oracle_kl=float(np.mean([r['oracle_mean_kl'] for r in valid])) if valid else None,
                max_projected_gradient=max([r['projected_gradient'] for r in valid],default=None)))
    for name,data in [('recovery_events',events),('recovery_fits',fits),('recovery_comparisons',rows),
        ('recovery_outcomes',outcomes),('recovery_selection_summary',selection),('recovery_comparison_summary',comparisons),
        ('recovery_model_status',model_status),('recovery_parameter_draws',[x for r in results for x in r['parameter_rows']]),
        ('recovery_by_board',[x for r in results for x in r['state_rows']]),
        ('recovery_optimizer_attempts',[x for r in results for x in r['attempts']]),
        ('recovery_training_checks',[x for r in results for x in r['guards']]),
        ('recovery_failures',[dict(scenario=r['scenario'],rep=r['rep'],model=k,error=v) for r in results for k,v in r['failures'].items()])]:
        csv_write(report/(name+'.csv'),data)
    json_write(report/'RECOVERY_STATUS.json',dict(datasets=len(results),requested_per_scenario={s:sum(r['scenario']==s for r in results) for s in SCENARIOS},
        failed_model_fits=sum(len(r['failures']) for r in results),incomplete_datasets=sum(not r['outcome']['complete'] for r in results),
        generator_fits_worse_than_feasible_truth=sum(r['outcome']['generator_fit_worse_than_truth'] is True for r in results),
        full_observed_histories=True,simulated_outcomes_only=True,complexity_frozen=True,fixed_numerical_domains=True,
        truth_vectors_used_as_starts=False,capped_draws_retained=True,
        note='Conditional recovery under three fitted generators. Winner frequencies are not test rejection rates. Observed-margin frequencies use fixed empirical point gains. Monte Carlo intervals concern simulation frequencies, not uncertainty in the real-data effect. Inspect failures and truth-objective diagnostics before interpretation.'))
