"""Shared control design; transparent clustered IV and diagnostic inference."""
from __future__ import annotations
import math
import numpy as np
import iv_numerics as num
import comparison_core as cmp
import followup_logic as logic

CRIT=1.959963984540054


def shared_meat(score,codes,with_date=True):
    score=np.asarray(score,float)
    if score.ndim==1:score=score[:,None]
    both=np.concatenate([score,score],axis=0)
    def outer(values,key):
        s=np.column_stack([np.bincount(codes[key],weights=values[:,k]) for k in range(values.shape[1])])
        return s.T@s
    v=outer(both,'accounts')-outer(score,'pairs')
    if with_date:v+=outer(score,'dates')-outer(both,'account_dates')+outer(score,'pair_dates')
    return v


def ols(y,z,meat):
    zz=float(z@z)
    if zz<=1e-20:return dict(supported=False,reason='NO_RESIDUAL_Z_VARIATION')
    beta=float(z@y)/zz;v=float(meat(z*(y-beta*z))[0,0])/zz**2
    r=dict(coefficient=beta)
    if not np.isfinite(v) or v<=0:return dict(r,supported=False,reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED')
    se=math.sqrt(v)
    return dict(r,supported=True,standard_error=se,ci_low=beta-CRIT*se,ci_high=beta+CRIT*se,
        p_value_asymptotic=math.erfc(abs(beta/se)/math.sqrt(2)),wald_F_one_df=(beta/se)**2)


def iv_fit(y,d,z,meat):
    zz,zd,zy=float(z@z),float(z@d),float(z@y)
    if zz<=1e-20:return dict(supported=False,reason='NO_RESIDUAL_Z_VARIATION')
    pi,rho=zd/zz,zy/zz
    V=meat(np.column_stack([z*(y-rho*z),z*(d-pi*z)]))
    psd=np.linalg.eigvalsh(V).min()>=-1e-10*max(float(abs(V).max()),1e-30)
    r=dict(first_stage=ols(d,z,meat),reduced_form=ols(y,z,meat),AR_covariance_psd=bool(psd),
        partial_first_stage_R2=zd**2/(zz*float(d@d)) if float(d@d)>0 else None)
    if abs(zd)<=1e-15:r.update(supported=False,reason='ZERO_FIRST_STAGE_COVARIANCE')
    else:
        beta=zy/zd;v=float(meat(z*(y-beta*d))[0,0])/zd**2
        r.update(iv_coefficient=beta,supported=bool(np.isfinite(v) and v>0))
        if r['supported']:
            se=math.sqrt(v);r.update(iv_standard_error=se,iv_ci_low=beta-CRIT*se,iv_ci_high=beta+CRIT*se,
                iv_p_value_asymptotic=math.erfc(abs(beta/se)/math.sqrt(2)))
        else:r['reason']='NONPOSITIVE_COVARIANCE_NOT_REPAIRED'
    if psd:
        q=num.quadratic_set(zd*zd-CRIT**2*V[1,1],-2*zy*zd+2*CRIT**2*V[0,1],zy*zy-CRIT**2*V[0,0])
        r['AR95_intervals']=[[('-inf' if math.isinf(a) else a),('+inf' if math.isinf(b) else b)] for a,b in q]
        r['AR95_unbounded']=any(math.isinf(a) or math.isinf(b) for a,b in q)
    else:r['AR95_reason']='NON_PSD_COVARIANCE_NOT_REPAIRED'
    return r


def joint(values,z,meat):
    zz=float(z@z)
    if zz<=1e-20:return dict(supported=False,reason='NO_RESIDUAL_Z_VARIATION')
    beta=z@values/zz
    V=meat(z[:,None]*(values-z[:,None]*beta))/zz**2
    ev,u=np.linalg.eigh(V);cut=max(float(abs(ev).max()),1e-30)*1e-9
    if ev.min() < -cut:return dict(supported=False,reason='NON_PSD_COVARIANCE_NOT_REPAIRED')
    use=ev>cut
    if not use.any():return dict(supported=False,reason='ZERO_RANK')
    stat=float(np.sum((u[:,use].T@beta)**2/ev[use]));rank=int(use.sum())
    return dict(supported=True,wald_chi2=stat,rank=rank,p_value_asymptotic=num.chi2_sf(stat,rank))


def effect_row(out,scale):
    r=dict(out)
    for k in ('coefficient','standard_error','ci_low','ci_high'):
        if k in out:r[k+'_pp']=scale*out[k]
    return r


def estimate(data,spec,reference_sd):
    family,lag,rich=spec['family'],spec['lag'],spec['rich']
    mask,flow=logic.analysis_mask(data,family,lag)
    n=int(mask.sum());base=dict(specification=spec['name'],family=family,lag=lag,minimum_history=5,
        recipient_history_controls=rich,IV_only_RD_controls=spec.get('rd',False),n=n,
        analysis_status='FOLLOWUP_AFTER_REVIEWED_RESULTS',causal_identification_certified=False,
        historical_scores_treated_as_fixed=True,reference_IV_score_sd=reference_sd)
    if n<2000:return dict(estimates=[dict(base,supported=False,reason='FEWER_THAN_2000_ROWS')],balance=[],joint_balance=[],sample_flow=flow)
    d={k:np.asarray(v)[mask] for k,v in data.items()}
    controls,names,traits,tnames,groups,missing=logic.controls_and_traits(d,lag,rich,spec.get('rd',False))
    if family=='iv':outs=['received','y','reached']
    elif family.startswith('ordinary'):outs=['y','reached']
    else:outs=['active_timeout','passive_outoftime','recipient_disconnect_main','recipient_chooser_main','recipient_fair_arm_main','actual_iv_exposure']
    raw=np.column_stack(controls+[d[f'adjusted_{lag}d']]+[d[o].astype(float) for o in outs]+traits)
    residual,info=num.partial_out(raw,groups,len(controls));del raw
    z=residual[:,0];native=float(np.sqrt(np.mean(z*z)))
    base.update(continuous_controls=names,missing_control_counts=missing,native_residual_score_sd=native,
        assignment_cells=len(np.unique(groups[0])),exposure_dates=len(np.unique(groups[1])),
        prehistory_rule='[start-97d,start-7d); recent checks [start-37d,start-7d)',
        unavailable_common_controls=['pregame_RD','internal_conduct_category'],**info)
    if native<=1e-10:return dict(estimates=[dict(base,supported=False,reason='NO_RESIDUAL_Z_VARIATION')],balance=[],joint_balance=[],sample_flow=flow)
    yout={o:residual[:,k+1] for k,o in enumerate(outs)}
    traitres=residual[:,1+len(outs):]
    codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1])
    covariance=[('shared_account_OR_date_CR0',lambda s:shared_meat(s,codes))]
    if family=='iv':
        inherited=num.cluster_codes(d['opponent_id'],groups[1])
        covariance.insert(0,('chooser_and_exposure_date_CR0',lambda s:num.cluster_meat(s,inherited)))
    estimates=[];balance=[];joints=[]
    for cluster,meat in covariance:
        common=dict(base,clustering=cluster)
        if family=='iv':
            events=int(d['received'].sum())
            if min(events,n-events)<20:
                estimates.append(dict(common,supported=False,reason='FEWER_THAN_20_TREATMENT_OR_CONTROL_ROWS'));continue
            r=iv_fit(yout['y'],yout['received'],z,meat)
            common.update(receipts=events,control_outcome_mean_pp=100*float(d['y'][~d['received'].astype(bool)].mean()))
            for label,out in [('first_stage_per_reference_SD',r.get('first_stage',{})),
                ('RF_kindness_per_reference_SD',r.get('reduced_form',{})),
                ('RF_reach_per_reference_SD',ols(yout['reached'],z,meat))]:
                estimates.append(dict(common,estimator=label,outcome='reached' if 'reach_per' in label else ('received' if label.startswith('first') else 'y'),**effect_row(out,100*reference_sd)))
            candidate={k:v for k,v in r.items() if k not in ('first_stage','reduced_form')}
            for k in ('iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high'):
                if k in r:candidate[k+'_pp']=100*r[k]
            estimates.append(dict(common,estimator='candidate_2SLS',outcome='y',**candidate))
            estimates.append(dict(common,estimator='same_sample_OLS',outcome='y',**effect_row(ols(yout['y'],yout['received'],meat),100)))
        else:
            for outcome in outs:
                events=int(d[outcome].sum());mean=float(d[outcome].mean())
                out=ols(yout[outcome],z,meat) if min(events,n-events)>=10 else dict(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
                r=dict(common,estimator='score_association_per_reference_SD',outcome=outcome,events=events,outcome_mean_pp=100*mean,**effect_row(out,100*reference_sd))
                if out.get('supported'):
                    r['MDE80_pp']=(CRIT+.8416212335729143)*r['standard_error_pp']
                    r['MDE80_percent_of_outcome_mean']=r['MDE80_pp']/mean if mean>0 else None
                    if family.startswith('ordinary') and outcome=='y':
                        for margin in (.015,.0075):
                            b,se=r['coefficient_pp'],r['standard_error_pp']
                            r[f'descriptive_equivalence_p_margin_{margin}']=max(.5*math.erfc((b+margin)/se/math.sqrt(2)),.5*math.erfc((margin-b)/se/math.sqrt(2)))
                            r[f'ci90_inside_margin_{margin}']=(b-1.6448536269514722*se>-margin and b+1.6448536269514722*se<margin)
                estimates.append(r)
        for k,name in enumerate(tnames):
            meta=dict(common,trait=name,units='trait SD per native residual score SD',directly_controlled=name in names)
            if name in names:
                balance.append(dict(meta,supported=False,reason='CONTROLLED_TRAIT_NOT_AN_INDEPENDENT_BALANCE_CHECK'))
            elif np.std(traitres[:,k])<1e-10:
                balance.append(dict(meta,supported=False,reason='NO_RESIDUAL_TRAIT_VARIATION'))
            else:balance.append(dict(meta,**ols(traitres[:,k],z/native,meat)))
        for setname,ix in [('recent_behavior_not_used_as_controls',[k for k,nm in enumerate(tnames) if nm.endswith('_30') and nm!='log_volume_30']),
            ('original_aggregate_history',[k for k,nm in enumerate(tnames) if nm.endswith('_90') or nm=='log_volume_30'])]:
            if setname=='original_aggregate_history' and rich:
                joints.append(dict(common,test_set=setname,supported=False,reason='CONTROLLED_TRAITS_NOT_AN_INDEPENDENT_BALANCE_CHECK'));continue
            joints.append(dict(common,test_set=setname,**joint(traitres[:,ix],z/native,meat)))
    return dict(estimates=estimates,balance=balance,joint_balance=joints,sample_flow=flow)


def holm(rows,field='p_value_asymptotic',out='p_Holm'):
    p=[r.get(field,1.) if r.get('supported') else 1. for r in rows]
    order=np.argsort(p);running=0.
    for rank,k in enumerate(order):
        running=max(running,(len(rows)-rank)*p[k])
        rows[k][out]=min(1.,running) if rows[k].get('supported') else None
        rows[k]['multiplicity_family_size']=len(rows)
