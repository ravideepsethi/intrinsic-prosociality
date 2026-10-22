"""Inherited controls and inference, with an explicit instrument lag adapter."""
import sys,math
from common import *
sys.path.insert(0,str(PACKAGE/'vendor'))
import expanded_stats as original
import expanded_logic as old_logic
import followup_stats as stats
import comparison_core as cmp
import iv_numerics as num
import design,sensitivity

def validate(d):
    n=len(d['row_id'])
    if len(np.unique(d['row_id']))!=n:raise RuntimeError('Repeated model row identifiers')
    for k in design.MODEL_COLUMNS:
        if len(d[k])!=n:raise RuntimeError('Unequal model columns')
    for k in ('received','y','reached','complete90'):
        if any(v is None for v in d[k]) or not np.isin(d[k],[False,True]).all():
            raise RuntimeError('Incomplete binary response inside final cohort')
    if not np.asarray(d['complete90'],bool).all():raise RuntimeError('Incomplete follow-up in model')
    if np.any(np.asarray(d['y'],bool)&~np.asarray(d['reached'],bool)):
        raise RuntimeError('A nonreacher has a positive response')
    for lag in (7,30):
        # Optional unsupported lag-30 scores can be missing outside its common sample.
        if lag==7 or np.all(d[f'n_{lag}d']>=5):
            for name in ('n','counterparts','expected','adjusted'):
                if not np.isfinite(d[f'{name}_{lag}d']).all():raise RuntimeError('Required instrument history missing')
    for days in (90,30):
        for k in ('fair','kind','disconnect','receipt','claim'):
            a=d[f'{k}_{days}']
            if not np.isfinite(a).all() or np.any(a<0):raise RuntimeError('Invalid history counts')
    if not np.isfinite(d['pre_games_30d']).all() or np.any(d['pre_games_30d']<0):
        raise RuntimeError('Pregame volume is missing')

def estimate(d,spec):
    validate(d);n=len(d['row_id'])
    account=original.describe(d)
    base=dict(specification=spec['name'],family='iv',n=n,lag=spec['lag'],
        recipient_history_controls=spec['rich'],recipient_FE=spec['fe'],repeat_recipient_rows_only=spec['repeat'],
        index_color_month_FE=spec.get('color_month_fe',False),
        clustering='shared_account_OR_date_CR0',historical_scores_treated_as_fixed=True,
        post_assignment_state_controls=False,reference_score_SD=design.REFERENCE_SD,
        causal_identification_certified=False,row_set_sha256=account['row_set_sha256'])
    out=dict(estimates=[],balance=[],joint_balance=[],design=base,sample_accounting=account,
        exclusion_sensitivity=dict(supported=False,reason='MODEL_NOT_SUPPORTED',fixed=[],bounds=[]))
    if n<2000:
        out['estimates']=[dict(base,supported=False,reason='FEWER_THAN_2000_ROWS')];return out
    for key in ('received','y','reached'):
        events=int(np.asarray(d[key],bool).sum())
        if min(events,n-events)<10:
            out['estimates']=[dict(base,supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS',outcome=key)];return out
    view=dict(d)
    if spec['lag']==30:
        for name in ('n','adjusted','expected','counterparts'):view[name+'_7d']=d[name+'_30d']
    xs,names,traits,tnames,groups,missing=original.controls(view,spec['rich'])
    if spec.get('color_month_fe',False):
        if 'index_color_white' not in d or not np.isin(d['index_color_white'],[0,1]).all():
            raise RuntimeError('Assigned index color missing; do not fill from later-choice color')
        _,color_month=num.factor(d['month_code'],d['index_color_white'])
        groups=groups+[color_month]
        base['index_color_month_cells']=len(np.unique(color_month))
    if spec['fe']:groups=groups+[d['recipient_id']]
    outs=['received','y','reached']
    raw=np.column_stack(xs+[view['adjusted_7d']]+[np.asarray(d[k],float) for k in outs]+(traits if spec['balance'] else []))
    del xs,traits
    with np.errstate(invalid='raise'):residual,info=num.partial_out(raw,groups,len(names))
    del raw
    z=residual[:,0];native=float(np.sqrt(np.mean(z*z)))
    dates=len(np.unique(groups[1]))
    base.update(native_residual_score_SD=native,continuous_controls=names,missing_control_counts=missing,
        assignment_cells=len(np.unique(groups[0])),exposure_dates=dates,
        fewer_than_30_exposure_dates=dates<30,**info)
    if native<1e-10:
        out['estimates']=[dict(base,supported=False,reason='NO_RESIDUAL_SCORE_VARIATION')];return out
    ys={k:residual[:,j+1] for j,k in enumerate(outs)}
    codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1])
    meat=lambda s:stats.shared_meat(s,codes,True)
    r=original.iv_result(ys['y'],ys['received'],z,meat)
    for label,fit in [('first_stage_per_reference_SD',r.get('first_stage',{})),
                      ('RF_kindness_per_reference_SD',r.get('reduced_form',{})),
                      ('RF_reach_per_reference_SD',stats.ols(ys['reached'],z,meat))]:
        row=dict(base,estimator=label,**stats.effect_row(fit,100*design.REFERENCE_SD))
        if fit.get('supported'):
            row['descriptive_MDE80_pp']=(stats.CRIT+.8416212335729143)*row['standard_error_pp']
        out['estimates'].append(row)
    iv={k:v for k,v in r.items() if k not in ('first_stage','reduced_form')}
    for k in ('iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high'):
        if k in iv:iv[k+'_pp']=100*iv[k]
    if 'iv_standard_error_pp' in iv:iv['descriptive_MDE80_pp']=(stats.CRIT+.8416212335729143)*iv['iv_standard_error_pp']
    out['estimates'].append(dict(base,estimator='2SLS',**iv))
    out['estimates'].append(dict(base,estimator='same_row_OLS',**stats.effect_row(stats.ols(ys['y'],ys['received'],meat),100)))
    if spec['balance']:
        values=residual[:,1+len(outs):]
        for k,name in enumerate(tnames):
            meta=dict(base,trait=name,units='trait_SD_per_native_residual_score_SD')
            if name in names:fit=dict(supported=False,reason='CONTROLLED_TRAIT_NOT_INDEPENDENT_BALANCE_EVIDENCE')
            elif np.std(values[:,k])<1e-10:fit=dict(supported=False,reason='NO_RESIDUAL_TRAIT_VARIATION')
            else:fit=stats.ols(values[:,k],z/native,meat)
            out['balance'].append(dict(meta,**fit))
        for label,ix in [('all_available_history',[k for k,nm in enumerate(tnames) if nm not in names]),
                        ('recent_behavior',[k for k,nm in enumerate(tnames) if nm.endswith('_30') and nm!='log_volume_30' and nm not in names])]:
            fit=stats.joint(values[:,ix],z/native,meat) if ix else dict(supported=False,reason='NO_UNCONTROLLED_TRAITS')
            out['joint_balance'].append(dict(base,test_set=label,traits=[tnames[k] for k in ix],**fit))
        stats.holm(out['balance'],out='p_Holm_within_specification')
    out['exclusion_sensitivity']=sensitivity.compute(ys['y'],ys['received'],z,meat)
    return out

def check_historical(r):
    if r['sample_accounting']['rows']!=design.EXPECTED['historical']:
        raise RuntimeError('Historical fit row count differs')
    e={x.get('estimator'):x for x in r['estimates']}
    required=[('2SLS','iv_coefficient_pp',.294953),('2SLS','iv_standard_error_pp',.127399),
              ('RF_kindness_per_reference_SD','coefficient_pp',.020386),
              ('first_stage_per_reference_SD','coefficient_pp',6.911589)]
    checks=[]
    for estimator,field,rounded in required:
        value=e.get(estimator,{}).get(field)
        passed=value is not None and abs(value-rounded)<=.000002
        checks.append(dict(estimator=estimator,field=field,reviewed_rounded=rounded,actual=value,tolerance=.000002,passed=passed))
    return dict(passed=all(x['passed'] for x in checks),checks=checks,
        interpretation='Reproduction against reviewed rounded historical estimates on the exact SHA-pinned author-inclusive cohort.')
