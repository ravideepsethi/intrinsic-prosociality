from bounded_linear import stack_columns, partial_out_owned, residualize_columns
"""Common-row entry comparisons. All outcomes use the pre-entry denominator."""
from entry_common import *
OUTCOMES=list(ENTRY_COLUMNS)
DROPS=['timeout_without_recipient_main_disconnect','recipient_disconnect_outside_competitive_arm',
       'competitive_arm_not_selected','selected_not_analysis']
LEVELS=('FE_only','ratings','opponent_history','X0','XC')
SD={'pooled':stats.REFERENCE_SD,'competitive':secondary.COMP_REFERENCE_SD}


def outcomes(d):
    y=np.column_stack([np.asarray(d[k],float) for k in OUTCOMES])
    if not np.isfinite(y).all() or not np.isin(y,[0,1]).all():raise RuntimeError('Nonbinary or missing entry outcome')
    losses=y[:,:-1]-y[:,1:]
    violations=[int((losses[:,k]<0).sum()) for k in range(4)]
    if any(violations):raise RuntimeError('Entry labels not nested: '+str(dict(zip(DROPS,violations))))
    return np.column_stack([y,losses]),OUTCOMES+DROPS


def support_mask(d):
    return (d['comp_n_7d']>=5)&np.isfinite(d['comp_adjusted_7d'])&np.isfinite(d['comp_expected_7d'])


def contrast(z1,z2,y,codes,scale=.1):
    """Competitive minus pooled slopes, per same raw 0.10-score increment."""
    z1z=float(z1@z1);z2z=float(z2@z2)
    if min(z1z,z2z)<1e-20:return dict(supported=False,reason='NO_RESIDUAL_SCORE_VARIATION')
    b1=float(z1@y)/z1z;b2=float(z2@y)/z2z
    influence=z2*(y-b2*z2)/z2z-z1*(y-b1*z1)/z1z
    variance=float(stats.stats.shared_meat(influence,codes,True)[0,0]);b=b2-b1
    if variance<=0 or not np.isfinite(variance):return dict(supported=False,reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED',coefficient_pp=100*scale*b)
    se=math.sqrt(variance)
    return dict(supported=True,coefficient_pp=100*scale*b,standard_error_pp=100*scale*se,
        ci_low_pp=100*scale*(b-stats.stats.CRIT*se),ci_high_pp=100*scale*(b+stats.stats.CRIT*se),
        p_value_asymptotic=math.erfc(abs(b/se)/math.sqrt(2)),common_raw_score_increment=scale,
        contrast='competitive_minus_pooled_separate_regressions_same_rows_and_controls',causal=False)



def estimate(d,cohort,sample,tail_cutoff=None):
    """Absorb FEs once; reuse for the fixed nested control ladder."""
    n=len(d['row_id']);base=dict(cohort=cohort,sample=sample,n=n,row_set_sha256=design.row_digest(d['row_id']),
        diagnostic_after_reviewed_results=True,clustering='shared_account_OR_date_CR0',
        generated_scores_treated_as_fixed=True,post_assignment_controls=False,causal_identification_certified=False,
        nominal_interim_intervals=True)
    if n<2000:return dict(estimates=[dict(base,supported=False,reason='FEWER_THAN_2000_ROWS')],contrasts=[],support=[],transitions=[],bridge=[])
    y,ynames=outcomes(d);nz=2 if sample=='competitive_supported' else 1
    if nz==2 and not support_mask(d).all():raise RuntimeError('Matched score comparison includes unsupported rows')
    xs,names,_,_,groups,missing=stats.controls(d,True)
    if any(missing.values()):raise RuntimeError('Missing model controls')
    if nz==2:
        for name,v in [('competitive_expected_rate',d['comp_expected_7d']),('log_competitive_decisions',np.log1p(d['comp_n_7d'])),('log_competitive_counterparts',np.log1p(d['comp_counterparts_7d']))]:
            if not np.isfinite(v).all():raise RuntimeError('Missing competitive control')
            xs.append((v-v.mean())/max(float(v.std()),1e-12));names.append(name)
    k=len(names);zs=[d['adjusted_7d']]+([d['comp_adjusted_7d']] if nz==2 else [])
    matrix=stack_columns(xs+zs+[y[:,j] for j in range(y.shape[1])]);del xs,zs
    if not np.isfinite(matrix).all():raise RuntimeError('Nonfinite model data')
    with np.errstate(invalid='raise'):absorbed,iterations=num.absorb(matrix,groups)
    del matrix
    codes=stats.cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1])
    meat=lambda v:stats.stats.shared_meat(v,codes,True)
    estimates=[];contrasts=[];support=[]
    families=LEVELS if nz==2 else ('X0',)
    for level in families:
        if level=='FE_only':ix=[]
        elif level=='ratings':ix=list(range(4))
        elif level=='opponent_history':ix=list(range(7))
        elif level=='X0':ix=list(range(k-3 if nz==2 else k))
        else:ix=list(range(k))
        residual,rank=residualize_columns(absorbed,k,ix)
        core=level in ('X0','XC');oi=range(len(ynames)) if core else [2,4]
        scores=residual[:,:nz];outs=residual[:,nz:]
        for j,tag in enumerate(('pooled','competitive')[:nz]):
            z=scores[:,j];native=float(np.sqrt(np.mean(z*z)));zz=float(z@z)
            concentration=None
            if nz==2 and tail_cutoff is not None and zz:
                mask=d['comp_adjusted_7d']>tail_cutoff
                concentration=float(z[mask]@z[mask])/zz
            support.append(dict(base,control_level=level,instrument=tag,native_residual_score_SD=native,
                fixed_reference_SD=SD[tag],residual_variance_share_above_frozen_ordinary_q95=concentration,
                score_correlation_residual=float(np.corrcoef(scores.T)[0,1]) if nz==2 and np.std(scores[:,0])>0 and np.std(scores[:,1])>0 else None))
            for o in oi:
                events=int(y[:,o].sum());mean=events/n
                fit=stats.stats.ols(outs[:,o],z,meat)
                if min(events,n-events)<10:
                    fit={k:v for k,v in fit.items() if k in ('coefficient',)}
                    fit.update(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
                r=dict(base,control_level=level,instrument=tag,outcome=ynames[o],events=events,
                    outcome_mean_pp=100*mean,controls=[names[t] for t in ix],continuous_control_rank=rank,
                    absorb_iterations=iterations,native_residual_score_SD=native,reference_score_SD=SD[tag],
                    **stats.stats.effect_row(fit,100*SD[tag]))
                if 'coefficient' in r:r['coefficient_pp_per_raw_0_10']=10*r['coefficient']
                if r.get('supported'):
                    r['standard_error_pp_per_raw_0_10']=10*r['standard_error']
                    r['MDE80_pp']=2.801585218112968*r['standard_error_pp']
                    r['relative_percent_of_outcome_mean']=r['coefficient_pp']/mean if mean else None
                estimates.append(r)
        if nz==2 and core:
            for o in range(5):
                r=contrast(scores[:,0],scores[:,1],outs[:,o],codes)
                if min(int(y[:,o].sum()),n-int(y[:,o].sum()))<10:r=dict(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
                contrasts.append(dict(base,control_level=level,outcome=ynames[o],**r))
        if core:
            for tag in ('pooled','competitive')[:nz]:
                fits={r['outcome']:r for r in estimates if r['instrument']==tag and r['control_level']==level}
                for a,b,gap in zip(OUTCOMES[:-1],OUTCOMES[1:],DROPS):
                    if all('coefficient' in fits[v] for v in (a,b,gap)) and not np.isclose(fits[a]['coefficient']-fits[b]['coefficient'],fits[gap]['coefficient'],atol=1e-10,rtol=1e-8):raise RuntimeError('Nested outcome decomposition failed')
        del residual,scores,outs
    transitions=[]
    for a,b,gap in zip(OUTCOMES[:-1],OUTCOMES[1:],DROPS):
        total=int(d[a].sum());success=int(d[b].sum())
        transitions.append(dict(base,from_stage=a,to_stage=b,from_events=total,to_events=success,removed_events=total-success,
            conditional_pass_percent=100*success/total if total else None,description='Unadjusted descriptive accounting; no conditional causal regression'))
    return dict(estimates=estimates,contrasts=contrasts,support=support,transitions=transitions,bridge=[])


