"""Aggregate outputs and prospectively declared contrast families."""
import bootstrap_path
import numpy as np
from diagnostics import paired,holm,CORE_PAIRS,NOISE_PAIRS
from io_utils import csv_write,json_write
from engine import predict,parameters,Model
from switching import SwitchingModel


def pairs_for(fits):
    if 'noisy_tiers' in fits:
        pairs=NOISE_PAIRS
    elif any(n.startswith('hmm_') for n in fits):
        pairs=[('hmm_'+f,'desert') for f in ['willingness','gate','gatecost','unrestricted']]
        pairs += [('hmm_'+f,'iid_'+f) for f in ['willingness','gate','gatecost','unrestricted']]
        pairs += [('hmm_gate','hmm_willingness'),('hmm_unrestricted','hmm_gate'),
                  ('hmm_gatecost','hmm_gate'),('hmm_unrestricted','hmm_willingness'),
                  ('iid_unrestricted','desert')]
    else:
        pairs=CORE_PAIRS+ [('desert','board_only'),('desert','no_stage'),
                         ('desert','no_expected'),('desert','desert_no_cost')]
    return [(a,b) for a,b in pairs if a in fits and b in fits]


def summaries(fits,data,meta,report,prefix=''):
    scores={};totals=[];rows=[];surface=[];cal=[];comparisons=[];subgroups=[]
    mask=data['period']==2
    groups=[('all',np.ones(len(mask),bool))]+[('board_'+str(j),data['board']==j) for j in range(5)]
    groups += [('loss_positive',data['loss']>0),('loss_zero',data['loss']==0)]
    state_rows=[]
    for name,res in fits.items():
        p,ll=predict(res,data,meta);scores[name]=ll
        types,dec=parameters(res,meta,meta.get('reference_group_weights'));rows+=types
        for c in meta['support']:
            for k in range(res['J']):
                surface.append(dict(model=name,type=k,cell=c,board=c//20,stage=(c//5)%4,
                  expected_score_bin=c%5,index=None if dec['A'] is None else float(dec['A'][c]),
                  effect=float(dec['effect'][k,c]),
                  lower_effect=float(dec['lower_theta'][k]*dec['A'][c]) if 'lower_theta' in dec else None))
        model=Model(res['spec'],res['J'],meta,res['bound'])
        if isinstance(model,SwitchingModel):
            state=model.predict(np.asarray(res['parameters']),data)[2]
            state_rows.append(dict(model=name,mean_forecast_upper_state=float(state[mask].mean()),
              initial_upper=float(np.exp(dec['loginit'][1])),entry=float(np.exp(dec['logT'][0,1])),
              retention=float(np.exp(dec['logT'][1,1])),
              persistence=float(np.exp(dec['logT'][1,1])-np.exp(dec['logT'][0,1]))))
        for label,g in groups:
            use=mask&g
            if not use.any():continue
            count=np.bincount(data['ids'][use],minlength=len(data['ptr'])-1)
            sl=np.bincount(data['ids'][use],weights=ll[use],minlength=len(count));active=count>0
            totals.append(dict(model=name,group=label,opportunities=int(use.sum()),accounts=int(active.sum()),
              grants=int(data['y'][use].sum()),mean_log_score=float(ll[use].mean()),
              equal_account_log_score=float(np.mean(sl[active]/count[active])),
              observed_rate=float(data['y'][use].mean()),predicted_rate=float(p[use].mean()),
              brier=float(np.mean((data['y'][use]-p[use])**2))))
        edges=[0,.001,.0025,.005,.01,.025,.05,.1,.25,.5,1.00001]
        bucket=np.searchsorted(edges[1:-1],p,side='right')
        for j in range(len(edges)-1):
            use=mask&(bucket==j)
            if use.any():cal.append(dict(model=name,bin=j,opportunities=int(use.sum()),
              observed_grants=float(data['y'][use].sum()),predicted_grants=float(p[use].sum())))
    for a,b in pairs_for(fits):
        comparisons.append(dict(candidate=a,baseline=b,**paired(data,scores[a],scores[b],mask)))
        for label,g in groups[1:]:subgroups.append(dict(candidate=a,baseline=b,group=label,**paired(data,scores[a],scores[b],mask&g)))
    for name,value in [('comparisons',holm(comparisons)),('comparisons_by_state',subgroups),('scores',totals),
                        ('types',rows),('state_surfaces',surface),('calibration',cal)]:
        csv_write(report/(prefix+name+'.csv'),value)
    if state_rows:csv_write(report/'state_dynamics.csv',state_rows)
    json_write(report/'INTERPRETATION.json',dict(
      conditional_tests='Population fits held fixed; account-clustered. Holm covers this table only.',
      predictive_scope='Differences in predictive risk for these fitted classes, not rejection of a population restriction.',
      evaluation_status='Same evaluation cohort already inspected; additional restrictions are follow-up sensitivity analyses, not an untouched confirmation.',
      dynamics='Opportunity-indexed transitions conditional on persistent type and observed covariates; no receipt effect or causal state interpretation.'))
    return scores,comparisons
