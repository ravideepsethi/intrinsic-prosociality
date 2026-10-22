"""Pooled and diagnostic FE IV, common rows, shared-account OR date CR0."""
from __future__ import annotations
from bounded_linear import stack_columns, partial_out_owned, residualize_columns
import math
import numpy as np
import iv_numerics as num
import comparison_core as cmp
import followup_logic as history_design
import followup_stats as stats
import expanded_logic as logic

REFERENCE_SD=0.059411690344000595
MIN_MODEL_ROWS=2000


def controls(d,rich):
    xs,names,ts,tnames,groups,missing=history_design.controls_and_traits(d,7,rich,False)
    for days in (90,30):
        v=np.log1p(d[f'claim_{days}']);v=(v-v.mean())/max(float(v.std()),1e-12)
        name=f'log_claim_{days}'
        ts.append(v);tnames.append(name)
        if rich and days==90:xs.append(v);names.append(name)
    return xs,names,ts,tnames,groups,missing


def iv_result(y,d,z,meat):
    r=stats.iv_fit(y,d,z,meat)
    # Invert a robust score/AR moment test under each null beta. Use the
    # null-restricted moments z*(y-beta*d), not unrestricted RF residuals.
    for key in list(r):
        if key.startswith('AR'):del r[key]
    V=meat(np.column_stack([z*y,z*d]))
    scale=max(float(np.abs(V).max()),1e-30)
    psd=bool(np.linalg.eigvalsh(V).min()>=-1e-10*scale)
    r['AR_null_moment_covariance_psd']=psd
    if psd:
        zy,zd=float(z@y),float(z@d);critical=stats.CRIT**2
        intervals=num.quadratic_set(zd*zd-critical*V[1,1],-2*zy*zd+2*critical*V[0,1],zy*zy-critical*V[0,0])
        r['AR95_intervals_pp']=[[('-inf' if math.isinf(a) else 100*a),('+inf' if math.isinf(b) else 100*b)] for a,b in intervals]
        r['AR95_unbounded']=any(math.isinf(a) or math.isinf(b) for a,b in intervals)
        r['AR_method']='null-restricted shared-account OR date CR0 score-moment inversion; chi2_1 asymptotic'
    else:r['AR95_reason']='NON_PSD_NULL_MOMENT_COVARIANCE_NOT_REPAIRED'
    return r


def describe(d):
    _,counts=np.unique(d['recipient_id'],return_counts=True)
    answer=dict(rows=len(d['recipient_id']),recipients=len(counts),repeat_recipients=int((counts>=2).sum()),
        recipient_max_rows=int(counts.max()) if len(counts) else 0,
        row_set_sha256=logic.row_digest(d['row_id']))
    for col in ('received','y','reached'):
        if col in d:
            known=np.ones(len(d[col]),bool)
            if col in ('y','reached') and 'complete90' in d:known &= np.asarray(d['complete90'],bool)
            value=np.asarray(d[col])[known]
            if any(v is None for v in value):raise ValueError('Missing outcome inside a complete window')
            answer[col+'_known_rows']=int(known.sum())
            answer[col+'_ones']=int(np.asarray(value,bool).sum())
    if 'outcome_gid' in d:
        reached=np.asarray(d['reached'],bool);positive=reached&np.asarray(d['y'],bool)
        answer.update(distinct_outcome_events=len(np.unique(d['outcome_gid'][reached])),
            distinct_kind_outcomes=len(np.unique(d['outcome_gid'][positive])))
        answer['outcome_copies_beyond_first']=int(reached.sum())-answer['distinct_outcome_events']
    return answer


def estimate(d,spec):
    n=len(d['recipient_id']);base=dict(specification=spec['name'],family=spec['family'],
        n=n,recipient_history_controls=spec['rich'],recipient_FE=spec['fe'],
        repeat_recipient_rows_only=spec['repeat'],clustering='shared_account_OR_date_CR0',
        historical_scores_treated_as_fixed=True,post_assignment_state_controls=False,
        reference_score_SD=REFERENCE_SD,causal_identification_certified=False,
        row_set_sha256=logic.row_digest(d['row_id']))
    if n<MIN_MODEL_ROWS:return dict(estimates=[dict(base,supported=False,reason='FEWER_THAN_2000_ROWS')],balance=[],joint_balance=[],design=base)
    xs,names,traits,tnames,groups,missing=controls(d,spec['rich'])
    if spec['fe']:groups=groups+[d['recipient_id']]
    if spec['family']=='iv':outs=['received','y','reached']
    elif spec['family']=='ordinary':outs=['y','reached']
    else:outs=['active_timeout','recipient_disconnect_main','recipient_fair_arm_main',
               f'selected_entry_{spec["gap"]}',f'analysis_entry_{spec["gap"]}']
    trait_indices=[k for k,name in enumerate(tnames) if name not in names]
    test_traits=[traits[k] for k in trait_indices] if spec['balance'] else []
    raw=stack_columns(xs+[d['adjusted_7d']]+[np.asarray(d[o],float) for o in outs]+test_traits)
    del xs,traits,test_traits
    with np.errstate(invalid='raise'):
        residual,info=partial_out_owned(raw,groups,len(names))
    del raw
    z=residual[:,0];native=float(np.sqrt(np.mean(z*z)))
    base.update(native_residual_score_SD=native,continuous_controls=names,missing_control_counts=missing,
        assignment_cells=len(np.unique(groups[0])),exposure_dates=len(np.unique(groups[1])),**info)
    if native<1e-10:return dict(estimates=[dict(base,supported=False,reason='NO_RESIDUAL_SCORE_VARIATION')],balance=[],joint_balance=[],design=base)
    ys={o:residual[:,k+1] for k,o in enumerate(outs)}
    codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1])
    meat=lambda s:stats.shared_meat(s,codes,True)
    estimates=[];balance=[];joints=[]
    if spec['family']=='iv':
        r=iv_result(ys['y'],ys['received'],z,meat)
        for label,fit in [('first_stage_per_reference_SD',r.get('first_stage',{})),
                          ('RF_kindness_per_reference_SD',r.get('reduced_form',{})),
                          ('RF_reach_per_reference_SD',stats.ols(ys['reached'],z,meat))]:
            estimates.append(dict(base,estimator=label,**stats.effect_row(fit,100*REFERENCE_SD)))
        r={k:v for k,v in r.items() if k not in ('first_stage','reduced_form')}
        for k in ('iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high'):
            if k in r:r[k+'_pp']=100*r[k]
        estimates.append(dict(base,estimator='2SLS',**r))
        estimates.append(dict(base,estimator='same_row_OLS',**stats.effect_row(stats.ols(ys['y'],ys['received'],meat),100)))
    else:
        for outcome in outs:
            events=int(np.asarray(d[outcome],bool).sum());mean=events/n
            fit=stats.ols(ys[outcome],z,meat) if min(events,n-events)>=10 else dict(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
            r=dict(base,estimator='score_association_per_reference_SD',outcome=outcome,events=events,
                outcome_mean_pp=100*mean,**stats.effect_row(fit,100*REFERENCE_SD))
            if fit.get('supported'):
                r['relative_percent_of_outcome_mean']=r['coefficient_pp']/mean if mean else None
                r['relative_ci_low_percent']=r['ci_low_pp']/mean if mean else None
                r['relative_ci_high_percent']=r['ci_high_pp']/mean if mean else None
                r['MDE80_pp']=(stats.CRIT+.8416212335729143)*r['standard_error_pp']
            estimates.append(r)
    if spec['balance']:
        values=residual[:,1+len(outs):]
        trait_columns={tnames[k]:j for j,k in enumerate(trait_indices)}
        for k,name in enumerate(tnames):
            meta=dict(base,trait=name,units='trait_SD_per_native_residual_score_SD')
            if name in names:balance.append(dict(meta,supported=False,reason='CONTROLLED_TRAIT_NOT_INDEPENDENT_BALANCE_EVIDENCE'))
            elif np.std(values[:,trait_columns[name]])<1e-10:balance.append(dict(meta,supported=False,reason='NO_RESIDUAL_TRAIT_VARIATION'))
            else:balance.append(dict(meta,**stats.ols(values[:,trait_columns[name]],z/native,meat)))
        for label,ix in [('all_available_history',[trait_columns[nm] for nm in tnames if nm not in names]),
                         ('recent_behavior',[trait_columns[nm] for nm in tnames if nm.endswith('_30') and nm!='log_volume_30' and nm not in names])]:
            fit=stats.joint(values[:,ix],z/native,meat) if ix else dict(supported=False,reason='NO_UNCONTROLLED_TRAITS')
            joints.append(dict(base,test_set=label,traits=[tnames[trait_indices[k]] for k in ix],**fit))
        stats.holm(balance,out='p_Holm_within_specification')
    return dict(estimates=estimates,balance=balance,joint_balance=joints,design=base)

