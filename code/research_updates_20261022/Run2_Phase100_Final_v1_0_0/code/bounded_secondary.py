from bounded_linear import stack_columns, partial_out_owned, residualize_columns
from checkpoint_secondary import *
def estimate(d,family,cohort,tail):
    n=len(d['row_id']);base=dict(n=n,cohort=cohort,control_family=family,tail_policy=tail,secondary=True,
        scores_author_clean=True,clustering='shared_account_OR_date_CR0',historical_scores_treated_as_fixed=True,
        row_set_sha256=design.row_digest(d['row_id']),abstract_gate_cleared=False)
    if n<2000:return [dict(base,supported=False,reason='FEWER_THAN_2000_ROWS')]
    xs,names,_,_,groups,missing=stats.controls(d,True)
    if any(missing.values()):raise RuntimeError('Missing controls in competitive comparison')
    if family=='XC':
        for name,v in [('competitive_expected_rate',d['comp_expected_7d']),('log_competitive_decisions',np.log1p(d['comp_n_7d'])),('log_competitive_counterparts',np.log1p(d['comp_counterparts_7d']))]:
            if not np.isfinite(v).all():raise RuntimeError('Missing competitive control')
            xs.append((v-v.mean())/max(float(v.std()),1e-12));names.append(name)
    raw=stack_columns(xs+[d['adjusted_7d'],d['comp_adjusted_7d'],d['y'],d['reached']])
    del xs
    res,info=partial_out_owned(raw,groups,len(names));del raw
    codes=stats.cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]);meat=lambda v:stats.stats.shared_meat(v,codes,True)
    rows=[]
    for j,(tag,sd) in enumerate([('pooled',stats.REFERENCE_SD),('competitive',COMP_REFERENCE_SD)]):
        z=res[:,j];native=float(np.sqrt(np.mean(z*z)))
        for k,outcome in enumerate(['y','reached']):
            events=int(np.asarray(d[outcome],bool).sum())
            if native<1e-10:fit=dict(supported=False,reason='NO_RESIDUAL_SCORE_VARIATION')
            elif min(events,n-events)<10:fit=dict(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
            else:fit=stats.stats.ols(res[:,2+k],z,meat)
            rows.append(dict(base,instrument=tag,outcome=outcome,events=events,reference_score_SD=sd,native_residual_score_SD=native,
                controls=names,**info,**stats.stats.effect_row(fit,100*sd)))
    return rows

