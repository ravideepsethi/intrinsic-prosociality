"""Optional parameter-recovery probe for a two-type receipt/decay model.

This is deliberately a restricted Stage-0 probe, not estimation of the proposed
full structural model and not a causal design for real receipts.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import expit,logsumexp
from scipy.optimize import minimize
from common import *

def mixture_objective(p,y,person,offset,lag_row,lag_days,npeople):
    a0,gap,logit_share,phi,logrho=p;a1=a0+np.exp(gap);rho=np.exp(logrho)
    e=np.exp(-rho*lag_days)
    stock=np.bincount(lag_row,weights=e,minlength=len(y))
    ds=np.bincount(lag_row,weights=-rho*lag_days*e,minlength=len(y))
    v=np.column_stack([a0+offset+phi*stock,a1+offset+phi*stock])
    pr=expit(v);ll=y[:,None]*v-np.logaddexp(0,v)
    llperson=np.column_stack([np.bincount(person,weights=ll[:,k],minlength=npeople) for k in (0,1)])
    w=expit(logit_share);llperson+=np.log([1-w,w])
    denom=logsumexp(llperson,axis=1);post=np.exp(llperson-denom[:,None])
    score=(y[:,None]-pr)*post[person]
    total=score.sum(axis=1)
    grad=np.array([total.sum(),np.exp(gap)*score[:,1].sum(),(post[:,1]-w).sum(),total@stock,phi*(total@ds)])
    return -float(denom.sum()),-grad

def unpack(p):
    return dict(alpha_low=p[0],alpha_high=p[0]+np.exp(p[1]),high_type_share=float(expit(p[2])),receipt_loading=p[3],half_life_days=float(np.log(2)/np.exp(p[4])))

def recovery(inputs,root,workers,memory,simulations=10,accounts=3000):
    root=Path(root);pub=root/'public';pub.mkdir(parents=True,exist_ok=True)
    c=connection(root,workers,memory);view_panel(c,inputs)
    c.execute(f'''CREATE OR REPLACE TABLE chosen AS SELECT chooser_user_id FROM panel GROUP BY chooser_user_id
        ORDER BY hash(chooser_user_id,20260920) LIMIT {int(accounts)}''')
    copy(c,'''SELECT chooser_user_id AS person,api_last_move_at_ms AS t,kind_draw AS observed_y,
       .6*fair_competitive::DOUBLE-.02*chooser_win_premium_v2 AS offset
       FROM panel SEMI JOIN chosen USING(chooser_user_id)
       WHERE isfinite(chooser_win_premium_v2)
       ORDER BY person,t,archive_ordinal,game_id''',root/'choices.parquet')
    source=parq(inputs.get('history',inputs['panels']))
    copy(c,'''SELECT disconnected_user_id AS person,api_last_move_at_ms AS t FROM '''+source+'''
       SEMI JOIN chosen ON disconnected_user_id=chosen.chooser_user_id WHERE kind_draw ORDER BY person,t''',root/'receipts.parquet')
    d=pq.read_table(root/'choices.parquet').to_pandas();r=pq.read_table(root/'receipts.parquet').to_pandas()
    ids,person=np.unique(d.person.to_numpy(),return_inverse=True);npeople=len(ids)
    offsets=d.offset.to_numpy(float);lag_rows=[];lags=[]
    receipt_groups={k:v.t.to_numpy(np.int64) for k,v in r.groupby('person',sort=False)}
    for idx,row in enumerate(d.itertuples(index=False)):
        times=receipt_groups.get(row.person)
        if times is None:continue
        before=times[:np.searchsorted(times,row.t,side='left')]
        if len(before):lag_rows.extend([idx]*len(before));lags.extend((row.t-before)/DAY)
    lag_rows=np.asarray(lag_rows,np.int64);lags=np.asarray(lags,float)
    counts=np.bincount(person);exposed=len(np.unique(lag_rows))
    design=dict(accounts=npeople,choices=len(d),choices_with_prior_receipt=exposed,receipt_choice_pairs=len(lags),
        account_choices_quantiles=np.quantile(counts,[0,.25,.5,.75,.9,.99,1]),
        initial_stock='zero at observed history boundary, known in this synthetic DGP',
        model='two latent intercept types, common receipt loading and continuous-time exponential decay; static offset fixed',
        omitted_from_probe=['own-grant feedback','correlated temporary shocks','estimated warrant','type-dependent receipt responses','endogenous receipt process'])
    js(pub/'recovery_design.json',design)
    if exposed<100 or npeople<100:
        c.close();return dict(status='INSUFFICIENT_DESIGN_SUPPORT',**design)
    truth=np.array([-6.,np.log(2.5),math.log(.15/.85),.8,math.log(math.log(2)/7)])
    true_values=unpack(truth);rho=np.exp(truth[4]);stock=np.bincount(lag_rows,weights=np.exp(-rho*lags),minlength=len(d))
    rng=np.random.default_rng(20260920);rows=[]
    for rep in range(simulations):
        typ=rng.random(npeople)<.15;alpha=np.where(typ,-3.5,-6.)
        probability=expit(alpha[person]+offsets+.8*stock);y=rng.binomial(1,probability).astype(float)
        fits=[]
        for start in [np.array([-5.5,np.log(2),-1.5,.4,math.log(math.log(2)/3)]),np.array([-6.5,np.log(3),-2.,1.,math.log(math.log(2)/20)])]:
            fit=minimize(mixture_objective,start,args=(y,person,offsets,lag_rows,lags,npeople),jac=True,method='L-BFGS-B',
                bounds=[(-12,-1),(-3,2.3),(-6,3),(-3,5),(math.log(math.log(2)/180),math.log(math.log(2)/.05))],
                options=dict(maxiter=400,ftol=1e-10,gtol=1e-5))
            fits.append(fit)
        fit=min(fits,key=lambda x:x.fun)
        row=dict(replication=rep+1,converged=bool(fit.success),objective=float(fit.fun),simulated_grants=int(y.sum()),**unpack(fit.x))
        for k,v in true_values.items():row['true_'+k]=v
        rows.append(row);pd.DataFrame(rows).to_csv(pub/'recovery_replications.csv',index=False)
        log(f'Recovery simulation {rep+1}/{simulations}: converged={fit.success}')
    summaries=[]
    for k,v in true_values.items():
        values=np.array([r[k] for r in rows if r['converged']]);summaries.append(dict(parameter=k,true_value=v,converged_runs=len(values),
            mean_estimate=float(values.mean()) if len(values) else None,bias=float((values-v).mean()) if len(values) else None,
            rmse=float(np.sqrt(np.mean((values-v)**2))) if len(values) else None))
    pd.DataFrame(summaries).to_csv(pub/'recovery_summary.csv',index=False)
    (pub/'INTERPRETATION.md').write_text('Synthetic outcomes on sampled actual opportunity and receipt timing. Two intercept types and the response magnitude and half-life are estimated. The static offset is fixed and initial stocks are known by construction. Success here is only a necessary computational check for this restricted model, not identification of the full model. Observed receipt timing is held fixed: no causal inference or network multiplier follows. Account sampling uses a fixed hash independent of observed giving. Increase to 50 replications for a more stable Monte Carlo assessment. No real structural parameters are estimated.\n')
    c.close();return dict(status='RESTRICTED_RECOVERY_PROBE_COMPLETE',replications=simulations,converged=sum(r['converged'] for r in rows),**design)

def blackout_feasibility(inputs,root,workers,memory):
    root=Path(root);pub=root/'public';pub.mkdir(parents=True,exist_ok=True)
    schema=pq.ParquetFile(inputs['panels'][0]).schema_arrow.names
    geo=[x for x in schema if any(s in x.lower() for s in ('country','location','latitude','longitude','ip_address','geo'))]
    result=dict(status='FEASIBILITY_ONLY_NOT_AN_INSTRUMENT',main_panel_geography_fields=geo,
      game_start_available='utc_ms' in schema,last_move_proxy_available='api_last_move_at_ms' in schema,
      independently_verified_outage_exposures_available=False,
      requirements=['external dated and localized outage records','validated player location at the event, not merely a current profile flag',
      'adequate unaffected comparison games','a stated estimand: cause of disconnection versus receipt of kindness',
      'assessment of direct effects on return, future activity and follow-up observation'])
    js(pub/'blackout_feasibility.json',result);return result
