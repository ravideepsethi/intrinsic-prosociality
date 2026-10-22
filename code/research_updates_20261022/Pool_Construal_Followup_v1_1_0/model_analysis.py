"""Chronological selection, matched sequential scoring, and account refits."""
from __future__ import annotations
import concurrent.futures as cf
import multiprocessing as mp
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.special import expit
from scipy.stats import norm
import hmm,static_models
from features import design,subset,replace_outcomes
from util import *

SWITCH=('gate','willingness','unrestricted','gate_cost')
FAMILIES=SWITCH+('static_level','static_selectivity','normal_selectivity')
PAIRS=[('gate','willingness'),('unrestricted','gate'),('gate_cost','gate'),
       ('unrestricted','willingness'),('gate','static_level'),
       ('willingness','static_level'),('unrestricted','static_selectivity'),
       ('static_selectivity','normal_selectivity')]


def save_data(path,d,identity):
    path=Path(path)
    if ready(path,identity):return
    X=d['X'].tocsr()
    with path.open('wb') as f:
        np.savez_compressed(f,x_data=X.data,x_indices=X.indices,x_indptr=X.indptr,x_shape=X.shape,
          **{k:d[k] for k in ['H','y','ptr','period','ids','F','accounts','cost_indices']})
    certify(path,identity)


def load_data(path):
    with np.load(path,allow_pickle=False) as z:
        d={k:z[k] for k in ['H','y','ptr','period','ids','F','accounts','cost_indices']}
        d['X']=sparse.csr_matrix((z['x_data'],z['x_indices'],z['x_indptr']),shape=tuple(z['x_shape']))
    return d


def job(task):
    path,out,identity,family,J,seed,maxiter,ridge,warm,aw=task
    out=Path(out)
    if ready(out,identity):return json.loads(out.read_text())
    d=load_data(path)
    if aw is not None:d['account_weights']=np.asarray(aw,float)
    mod=hmm if family in SWITCH else static_models
    log(f'FIT {out.stem}')
    result=mod.fit(d,family,J,seed,maxiter,ridge,warm)
    require(np.isfinite(result['objective']) and np.isfinite(result['parameters']).all(),'Nonfinite fit')
    atomic_json(out,result);certify(out,identity)
    log(f'FINISHED {out.stem}: converged={result["converged"]}; iterations={result["iterations"]}')
    return result


def run_jobs(tasks,workers):
    if workers==1:return [job(t) for t in tasks]
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        return list(ex.map(job,tasks))


def choose(fits):
    converged=[f for f in fits if f['converged']]
    return min(converged or fits,key=lambda f:f['objective'])


def predict(fit,d):
    return (hmm if fit['family'] in SWITCH else static_models).predict(fit,d)


def losses(y,p):return -(y*np.log(p)+(1-y)*np.log1p(-p))


def gain_stats(candidate,base,y,ids,mask,account_weights=None):
    diff=losses(y,base)-losses(y,candidate)
    N=int(ids.max()+1) if len(ids) else 0
    n=np.bincount(ids[mask],minlength=N);g=np.bincount(ids[mask],weights=diff[mask],minlength=N)
    aw=np.ones(N) if account_weights is None else account_weights
    active=n>0;M=int(active.sum());total=float(aw@n)
    if total==0:return dict(gain=None,equal_account_gain=None,accounts=0,opportunities=0,conditional_SE=None,p_value=None)
    gain=float(aw@g/total)
    se=float(np.sqrt(M/(M-1)*np.sum((g[active]-gain*n[active])**2))/n.sum()) if M>1 and account_weights is None else None
    equal=float(np.average(g[active]/n[active],weights=aw[active])) if aw[active].sum()>0 else None
    return dict(gain=gain,equal_account_gain=equal,accounts=M,opportunities=int(n.sum()),
                conditional_SE=se,p_value=float(2*norm.sf(abs(gain/se))) if se and se>0 else None)


def holm(rows,field='p_value',out='p_Holm'):
    valid=[(float(r[field]),j) for j,r in enumerate(rows) if r.get(field) is not None and np.isfinite(r[field])]
    order=sorted(valid);last=0.;m=len(rows)
    for k,(p,j) in enumerate(order):
        last=max(last,min(1.,(m-k)*p));rows[j][out]=last
    for r in rows:r.setdefault(out,None)


def select_fit(df,private,report,identity,args):
    development=df[df.cohort=='development'].copy()
    d=design(development)
    year1=development.period.to_numpy()==0
    # Calendar boundaries use recorded anchors, so October-start / November-end
    # games cannot leak later actions into the earlier training window.
    split_ms=1722470400000  # 2024-08-01
    early=year1&(development.t.to_numpy()<split_ms)
    val=year1&~early
    require(early.any() and val.any(),'No chronological validation support')
    train=subset(d,early);full=subset(d,year1)
    path_cv=private/'cv_arrays.npz';path_full=private/'train_arrays.npz'
    save_data(path_cv,train,identity);save_data(path_full,full,identity)
    first=design(development[year1])
    validation_mask=development.loc[year1,'t'].to_numpy()>=split_ms
    atomic_json(report/'MODEL_DESIGN.json',dict(emission_features=d['names'],feature_blocks=d['blocks'],
       transitions=d['transition_names'],families=list(FAMILIES),support_grid=args.support_grid,
       normal_quadrature_grid=args.normal_grid,random_effects='Joint freely located finite support for persistent granting level and transition heterogeneity; anchor normalisation internally',
       initial_state='logit(zeta0 + zeta_ell*ell_j + gamma_j)',
       latent_label='higher grant intercept at the fixed competitive reference configuration',
       selection='development accounts, November 2023--July 2024 fitting; August--October 2024 sequential validation',
       reporting='No classification of observed accounts as moral or non-moral',ridge=args.ridge))
    selected={};attempts=[];selection=[];cvbest={}
    for family in FAMILIES:
        grid=args.normal_grid if family=='normal_selectivity' else args.support_grid
        if family in ('static_level','static_selectivity'):grid=sorted(set(grid+[5]))
        candidates=[]
        for J in grid:
            tasks=[]
            for start in range(args.starts):
                warm=None
                if family in ('unrestricted','gate_cost') and start==0 and ('gate',J) in cvbest:
                    warm=hmm.embed(cvbest['gate',J],family,train).tolist()
                if family=='unrestricted' and start==1 and ('willingness',J) in cvbest:
                    warm=hmm.embed(cvbest['willingness',J],family,train).tolist()
                tasks.append((str(path_cv),str(private/f'cv_{family}_{J}_{start}.json'),identity,
                    family,J,args.seed+start*101,args.maxiter,args.ridge,warm,None))
            fits=run_jobs(tasks,args.workers);best=choose(fits);cvbest[family,J]=best
            for f in fits:attempts.append(dict(phase='validation_fit',**{k:f[k] for k in ('family','J','seed','converged','objective','iterations','parameter_count')},bounds=len(f['boundary_parameters'])))
            p,_=predict(best,first);score=float(losses(first['y'][validation_mask],p[validation_mask]).mean())
            selection.append(dict(family=family,J=J,validation_log_loss=score,training_converged=best['converged']))
            candidates.append((score,best))
        converged=[v for v in candidates if v[1]['converged']]
        winner=min(converged or candidates,key=lambda x:x[0])[1]
        J=winner['J'];tasks=[]
        for start in range(args.starts):
            warm=np.array(winner['parameters'])
            if start: warm+=np.random.default_rng(args.seed+start).normal(0,.03,len(warm))
            tasks.append((str(path_full),str(private/f'full_{family}_{J}_{start}.json'),identity,
                family,J,args.seed+start*101,args.maxiter,args.ridge,warm.tolist(),None))
        fits=run_jobs(tasks,args.workers);selected[family]=choose(fits)
        for f in fits:attempts.append(dict(phase='full_first_year',**{k:f[k] for k in ('family','J','seed','converged','objective','iterations','parameter_count')},bounds=len(f['boundary_parameters'])))
        csv_write(report/'optimizer_attempts.csv',attempts);csv_write(report/'first_year_selection.csv',selection)
    atomic_json(report/'SELECTED_FITS.json',selected)
    emissions=[];transitions=[];support=[];initial=[]
    for family in SWITCH:
        f=selected[family];m=hmm.Layout(d['X'].shape[1],d['H'].shape[1],f['J'],family,d['cost_indices'])
        z=m.decode(np.array(f['parameters']))
        for e in (0,1):
            for name,value in zip(['reference_intercept']+d['names'],np.r_[z['alpha'][e],z['beta'][e]]):
                emissions.append(dict(model=family,state=e,term=name,coefficient=float(value),units='conditional_log_odds'))
            for name,value in zip(d['transition_names'],z['transition'][e]):
                transitions.append(dict(model=family,previous_state=e,term=name,coefficient=float(value),units='log_odds_of_state_1'))
        for j in range(f['J']):support.append(dict(model=family,component=j,weight=float(np.exp(z['lp'][j])),ell=float(z['ell'][j]),gamma=float(z['gamma'][j])))
        initial.append(dict(model=family,constant=float(z['initial'][0]),ell_coefficient=float(z['initial'][1]),gamma_coefficient=1.))
    csv_write(report/'emission_coefficients.csv',emissions);csv_write(report/'transition_coefficients.csv',transitions)
    csv_write(report/'persistent_support.csv',support);csv_write(report/'initial_state_coefficients.csv',initial)
    return selected,full,path_full


def score(df,fits,private,report,identity):
    ev=df[df.cohort=='evaluation'].copy();d=design(ev);test=d['period']==1
    require(test.any(),'No evaluation-year opportunities after timing exclusions')
    predictions={};details={};scores=[];cal=[]
    groups={'all':np.ones(len(ev),bool),'first_year_no_grant':ev.g_train.to_numpy()==0,
      'first_year_prior_granter':ev.g_train.to_numpy()>0,
      'first_year_lost_only_grants':(ev.lg_train.to_numpy()>0)&(ev.g_train.to_numpy()==ev.lg_train.to_numpy()),
      'rich_both_states':(ev.f_train.to_numpy()>=8)&(ev.l_train.to_numpy()>=8)}
    regions={'all':np.ones(len(ev),bool),'competitive':ev.board.to_numpy()>=2,
             'clearly_worse':ev.board.to_numpy()==0,'middle':ev.board.to_numpy()==1}
    for name,fit in fits.items():
        p,extra=predict(fit,d);predictions[name]=p;details[name]=extra
        for group,gm in groups.items():
            for region,rm in regions.items():
                m=test&gm&rm
                if not m.any():continue
                scores.append(dict(model=name,group=group,region=region,opportunities=int(m.sum()),accounts=int(np.unique(d['ids'][m]).size),
                   actual_rate=float(d['y'][m].mean()),predicted_rate=float(p[m].mean()),
                   log_loss=float(losses(d['y'][m],p[m]).mean()),brier=float(np.mean((d['y'][m]-p[m])**2))))
        cuts={'board':ev.board.to_numpy(),'stage':ev.stage.to_numpy(),
          'loss':np.digitize(ev.loss.fillna(-1).to_numpy(),[0.00001,5,10,20]),
          'dclock':np.digitize(ev.dclock.fillna(-1).to_numpy(),[0,10,30,60,180,600]),
          'gap':np.digitize(ev.gap.fillna(-9999).to_numpy(),[-200,-50,0,1,51,201])}
        for dimension,values in cuts.items():
            for v in np.unique(values[test]):
                for group,gm in [('all',groups['all']),('first_year_no_grant',groups['first_year_no_grant'])]:
                    m=test&gm&(values==v)
                    if m.any():cal.append(dict(model=name,dimension=dimension,bin=int(v),group=group,n=int(m.sum()),grants=int(d['y'][m].sum()),observed=float(d['y'][m].mean()),predicted=float(p[m].mean())))
    gains=[]
    for candidate,baseline in PAIRS:
        for group,gm in groups.items():
            for region,rm in regions.items():
                res=gain_stats(predictions[candidate],predictions[baseline],d['y'],d['ids'],test&gm&rm)
                gains.append(dict(candidate=candidate,baseline=baseline,group=group,region=region,**res))
    primary=[g for g in gains if g['group']=='all' and g['region']=='all' and (g['candidate'],g['baseline']) in PAIRS[:4]]
    holm(primary,out='p_Holm_four_conditional_comparisons')
    csv_write(report/'heldout_scores.csv',scores);csv_write(report/'heldout_calibration.csv',cal)
    csv_write(report/'heldout_gains.csv',gains);csv_write(report/'primary_comparisons.csv',primary)
    for name,p in predictions.items():
        dest=private/f'predictions_{name}.npz'
        with dest.open('wb') as f:np.savez_compressed(f,probability=p,**details[name])
        certify(dest,identity)
    surfaces=[]
    for family in SWITCH:
        a=details[family]['receipt_input_0'];b=details[family]['receipt_input_1']
        supported=test&np.isfinite(a)&np.isfinite(b)&(ev.separated_risks.to_numpy()>0)&(ev.ambiguous_receipts.to_numpy()==0)
        for board in range(5):
            for group,gm in groups.items():
                m=supported&(ev.board.to_numpy()==board)&gm
                if m.any():surfaces.append(dict(model=family,board=board,group=group,n=int(m.sum()),
                  forecast_input0=float(a[m].mean()),forecast_input1=float(b[m].mean()),
                  probability_contrast_pp=float(100*(b[m]-a[m]).mean()),
                  interpretation='Model-input contrast holding pre-interval beliefs and other covariates fixed; not a causal receipt effect'))
    csv_write(report/'receipt_model_forecast_surface.csv',surfaces)
    post=pd.DataFrame({'chooser':d['accounts']})
    for family in SWITCH:
        fit=fits[family];layout=hmm.Layout(d['X'].shape[1],d['H'].shape[1],fit['J'],family,d['cost_indices'])
        z=layout.decode(np.array(fit['parameters']));q=details[family]['train_posterior'];typeq=q.sum(axis=2)
        post[family+'_ell']=typeq@z['ell'];post[family+'_gamma']=typeq@z['gamma'];post[family+'_state1']=q[:,:,1].sum(axis=1)
    post.to_parquet(private/'first_year_posterior_features.parquet',index=False)
    return ev,d,predictions,details,primary


def bootstrap_refits(full,path_full,ev,d,fits,predictions,private,report,identity,args):
    rows=[];test=d['period']==1
    # Population fit and evaluation histories are both resampled by account.
    for b in range(args.bootstrap_refits):
        rng=np.random.default_rng(args.seed+70000+b)
        aw=rng.multinomial(len(full['accounts']),np.ones(len(full['accounts']))/len(full['accounts'])).astype(float)
        ew=rng.multinomial(len(d['accounts']),np.ones(len(d['accounts']))/len(d['accounts'])).astype(float)
        bootpred={};converged={}
        for family in SWITCH:
            fit=fits[family];tasks=[]
            for start in range(2):
                warm=np.array(fit['parameters'])
                if start:warm+=rng.normal(0,.03,len(warm))
                tasks.append((str(path_full),str(private/f'boot_{b}_{family}_{start}.json'),identity,
                    family,fit['J'],args.seed+90000+b*10+start,args.maxiter,args.ridge,warm.tolist(),aw.tolist()))
            chosen=choose(run_jobs(tasks,args.workers));converged[family]=chosen['converged']
            bootpred[family]=predict(chosen,d)[0]
        for candidate,baseline in PAIRS[:4]:
            g=gain_stats(bootpred[candidate],bootpred[baseline],d['y'],d['ids'],test,ew)
            rows.append(dict(replication=b,candidate=candidate,baseline=baseline,gain=g['gain'],
                 both_converged=converged[candidate] and converged[baseline]))
        csv_write(report/'refit_bootstrap_draws.csv',rows)
    summary=[]
    for candidate,baseline in PAIRS[:4]:
        vals=np.array([r['gain'] for r in rows if r['candidate']==candidate and r['baseline']==baseline and r['both_converged']],float)
        out=dict(candidate=candidate,baseline=baseline,requested=args.bootstrap_refits,converged=len(vals),
          refit_bootstrap_SE=float(vals.std(ddof=1)) if len(vals)>1 else None,
          interval_status='NOT_REPORTED_FEWER_THAN_100_CONVERGED_REFITS')
        if len(vals)>=100:
            out.update(percentile_95_low=float(np.quantile(vals,.025)),percentile_95_high=float(np.quantile(vals,.975)),interval_status='PERCENTILE_INTERVAL_AT_FROZEN_COMPLEXITY')
        summary.append(out)
    csv_write(report/'refit_bootstrap_summary.csv',summary)
    return summary


def recovery(df,private,report,identity,args):
    dev=df[(df.cohort=='development')&(df.period==0)]
    ids=np.sort(dev.chooser.unique())[:args.recovery_accounts]
    dev=dev[dev.chooser.isin(ids)];d=design(dev);rows=[]
    if not len(dev):return rows
    rng=np.random.default_rng(args.seed+414)
    for scenario in ['gate','willingness','nearly_collapsed']:
        truth_family='willingness' if scenario=='willingness' else 'gate'
        m=hmm.Layout(d['X'].shape[1],d['H'].shape[1],2,truth_family,d['cost_indices'])
        truth=m.start(args.seed+91);truth[m.s['a']]=[-6.,2.5 if scenario!='nearly_collapsed' else -5.]
        truth[m.s['b1']]=0.;truth[m.s['b1']][0]=1.5 if scenario!='nearly_collapsed' else .02
        z,pe,pt,initial=m.probabilities(truth,d)
        for rep in range(args.recovery_reps):
            y=np.zeros(len(dev));latent=rng.choice(2,len(ids),p=np.exp(z['lp']))
            for i in range(len(d['ptr'])-1):
                j=latent[i];e=int(rng.random()<initial[j])
                for r in range(d['ptr'][i],d['ptr'][i+1]):
                    if r>d['ptr'][i]:e=int(rng.random()<pt[r,j,e])
                    y[r]=rng.random()<pe[r,j,e]
            sim=replace_outcomes(d,y)
            # Account-disjoint simulated evaluation prevents comparing training fit alone.
            split=max(1,len(d['accounts'])*2//3);train=subset(sim,sim['ids']<split);test=subset(sim,sim['ids']>=split)
            for family in ['gate','willingness','unrestricted']:
                out=private/f'recovery_{scenario}_{rep}_{family}.json'
                if ready(out,identity):fit=json.loads(out.read_text())
                else:
                    fit=choose([hmm.fit(train,family,2,args.seed+rep*10+k,min(args.maxiter,250),args.ridge) for k in range(2)])
                    atomic_json(out,fit);certify(out,identity)
                p,_=hmm.predict(fit,test)
                layout=hmm.Layout(d['X'].shape[1],d['H'].shape[1],2,family,d['cost_indices'])
                zhat=layout.decode(np.array(fit['parameters']))
                # Reference intercept separation is label invariant under the imposed order.
                rows.append(dict(scenario=scenario,replication=rep,fitted_family=family,
                    converged=fit['converged'],simulated_grants=int(y.sum()),accounts=len(d['accounts']),
                    heldout_log_loss=float(losses(test['y'],p).mean()),
                    true_reference_gap=float(z['alpha'][1]-z['alpha'][0]),
                    fitted_reference_gap=float(zhat['alpha'][1]-zhat['alpha'][0]),
                    true_receipt_entry=float(z['transition'][0,1]),estimated_receipt_entry=float(zhat['transition'][0,1])))
            csv_write(report/'recovery_simulations.csv',rows)
            log(f'Recovery {scenario} {rep+1}/{args.recovery_reps}')
    return rows
