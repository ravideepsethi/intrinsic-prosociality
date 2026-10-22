"""Frozen first-stage diagnostics and instrument-weighted complier descriptions."""
from __future__ import annotations
from common import *
import math
import iv_numerics as num
import expanded_stats as design
import followup_stats as stats
import comparison_core as cmp

MIN_ROWS=2000
MIN_RECEIPTS=20
RATING_BINS=[('under_1200',None,1200),('1200_1599',1200,1600),('1600_1999',1600,2000),('2000_plus',2000,None)]

def subgroup_specs():
    out=[dict(dimension='overall',label='all')]
    out += [dict(dimension='speed',label=s) for s in SPEEDS]
    out += [dict(dimension='rating',label=n,lower=lo,upper=hi) for n,lo,hi in RATING_BINS]
    out += [dict(dimension='month',label=m,month_code=k) for k,m in enumerate(MONTHS)]
    out += [dict(dimension='prior_granting',label=n) for n in ('no_fair_decision','fair_but_never_granted','ever_granted')]
    return out

def subgroup_mask(d,spec):
    n=len(d['recipient_id']);dim=spec['dimension'];label=spec['label']
    if dim=='overall':return np.ones(n,bool)
    if dim=='speed':return d['speed']==label
    if dim=='month':return d['month_code']==spec['month_code']
    if dim=='rating':
        r=d['recipient_rating'];lo=spec['lower'];hi=spec['upper']
        return (np.ones(n,bool) if lo is None else r>=lo)&(np.ones(n,bool) if hi is None else r<hi)
    fair=d['fair_90'];kind=d['kind_90']
    if dim=='prior_granting':
        return {'no_fair_decision':fair==0,'fair_but_never_granted':(fair>0)&(kind==0),'ever_granted':kind>0}[label]
    raise ValueError(dim)

def model_covariance(d,day):
    codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],day)
    return lambda s:stats.shared_meat(s,codes,True)

def first_stage(d, spec):
    n=len(d['recipient_id']);receipts=int(np.asarray(d['received'],bool).sum())
    base=dict(**spec,n=n,receipts=receipts,recipients=len(np.unique(d['recipient_id'])),
              choosers=len(np.unique(d['opponent_id'])),reference_score_SD=REFERENCE_SD,
              clustering='shared_account_OR_date_CR0',historical_scores_treated_as_fixed=True,
              author_excluded=True,prior_granting_window='[start-97d,start-7d)',
              rating_role='recipient',same_controls_refit_within_subgroup=True)
    if n<MIN_ROWS or min(receipts,n-receipts)<MIN_RECEIPTS:
        return [dict(base,adjustment=a,supported=False,reason='TOO_FEW_ROWS_OR_RECEIPTS') for a in ('raw','adjusted')]
    meat=model_covariance(d,d['archive_start_ms']//DAY)
    z0=np.asarray(d['adjusted_7d'],float);y0=np.asarray(d['received'],float)
    z0=z0-z0.mean();y0=y0-y0.mean()
    raw=dict(base,adjustment='raw',**stats.effect_row(stats.ols(y0,z0,meat),100*REFERENCE_SD))
    xs,names,_,_,groups,missing=design.controls(d,True)
    residual,info=num.partial_out(np.column_stack(xs+[d['adjusted_7d'],y0]),groups,len(xs))
    z,y=residual.T;zz=float(z@z);yy=float(y@y);zy=float(z@y)
    adjusted=dict(base,adjustment='adjusted',continuous_controls=names,missing_control_counts=missing,
                  native_residual_score_SD=math.sqrt(zz/n),assignment_cells=len(np.unique(groups[0])),
                  exposure_dates=len(np.unique(groups[1])),partial_R2=zy*zy/(zz*yy) if zz*yy>0 else None,
                  **info,**stats.effect_row(stats.ols(y,z,meat),100*REFERENCE_SD))
    for row in (raw,adjusted):
        if 'coefficient' in row:row['negative_point_estimate']=row['coefficient']<0
        if row.get('supported'):
            row['ci95_entirely_negative']=row['ci_high']<0
            row['one_sided_p_negative']=.5*math.erfc(-row['coefficient']/row['standard_error']/math.sqrt(2))
    adjusted['raw_adjusted_sign_reversal']=raw.get('coefficient',0)*adjusted.get('coefficient',0)<0
    return [raw,adjusted]

def subgroup_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def produce(tmp):
        # Column projection and predicate pushdown avoid reading the full cohort for every small subgroup.
        spec=job['spec'];dim=spec['dimension'];label=spec['label'];where='TRUE'
        if dim=='speed':where='speed='+io.lit(label)
        elif dim=='month':where='month_code='+str(spec['month_code'])
        elif dim=='rating':
            terms=[]
            if spec['lower'] is not None:terms.append('recipient_rating>='+str(spec['lower']))
            if spec['upper'] is not None:terms.append('recipient_rating<'+str(spec['upper']))
            where=' AND '.join(terms)
        elif dim=='prior_granting':
            where={'no_fair_decision':'fair_90=0','fair_but_never_granted':'fair_90>0 AND kind_90=0','ever_granted':'kind_90>0'}[label]
        c=io.conn(tmp/'spill',1,1)
        try:t=c.execute('SELECT '+','.join(MODEL_COLS)+' FROM '+io.parq([job['sample']])+' WHERE '+where).to_arrow_table()
        finally:c.close()
        rows=first_stage(arrays(t),spec);io.js(tmp/'results.json',rows)
        return dict(rows=len(t))
    directory,_=io.stage(Path(job['output']),job['conf'],produce)
    return io.load(directory/'results.json')

def complier_ratio(z,d,dx,meat):
    den=float(z@d)
    if abs(den)<=1e-15:return dict(supported=False,reason='ZERO_FIRST_STAGE_COVARIANCE')
    mu=float(z@dx)/den
    v=float(meat(z*(dx-mu*d))[0,0])/den**2
    if not np.isfinite(v) or v<=0:return dict(mean=mu,supported=False,reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED')
    se=math.sqrt(v)
    return dict(supported=True,mean=mu,standard_error=se,ci_low=mu-stats.CRIT*se,ci_high=mu+stats.CRIT*se)

def trait_values(d):
    out=[('recipient_rating','rating_points',d['recipient_rating']),
         ('prior_30d_rated_games','games',d['pre_games_30d']),
         ('prior_90d_fair_choices','choices',d['fair_90']),
         ('prior_90d_ever_granted','share',d['kind_90']>0),
         ('prior_90d_no_fair_choices','share',d['fair_90']==0),
         ('prior_90d_disconnections','games',d['disconnect_90']),
         ('prior_90d_receipts','grants_received',d['receipt_90'])]
    out += [('speed_'+speed,'share',d['speed']==speed) for speed in SPEEDS]
    return out

def complier_means(d):
    # These describe the continuous instrument's weighted treatment margin under
    # maintained IV assumptions. They do not identify a discrete complier class.
    xs,names,_,_,groups,missing=design.controls(d,True)
    D=np.asarray(d['received'],float);traits=trait_values(d)
    raw=np.column_stack(xs+[d['adjusted_7d'],D]+[D*np.asarray(v,float) for _,_,v in traits])
    residual,info=num.partial_out(raw,groups,len(xs));del raw,xs
    z,rd=residual[:,0],residual[:,1];meat=model_covariance(d,groups[1]);rows=[]
    weights=z*D;den=float(weights.sum());negative=float(np.abs(weights[weights<0]).sum())
    for k,(name,units,value) in enumerate(traits):
        value=np.asarray(value,float)
        result=complier_ratio(z,rd,residual[:,k+2],meat)
        lo,hi=float(value.min()),float(value.max())
        rows.append(dict(trait=name,units=units,n=len(D),population_mean=float(value.mean()),
            receipt_group_mean=float(value[D==1].mean()),observed_min=lo,observed_max=hi,
            interpretation='instrument_weighted_treatment_margin_under_maintained_conditional_IV_assumptions',
            out_of_observed_range=bool(result.get('mean',lo)<lo or result.get('mean',hi)>hi),
            negative_weight_mass_over_signed_total=negative/abs(den) if den else None,
            clustering='shared_account_OR_date_CR0',historical_scores_treated_as_fixed=True,
            **result))
    return rows,dict(**info,controls=names,missing_controls=missing,weights_clipped=False,
                     negative_weights_allowed=True,denominator=den)

def finalize_first_stages(rows):
    adjusted=[r for r in rows if r['adjustment']=='adjusted' and r['dimension']!='overall']
    stats.holm(adjusted,field='one_sided_p_negative',out='one_sided_p_negative_Holm_all_subgroups')
    return dict(subgroups=len(adjusted),supported_subgroups=sum(bool(r.get('supported')) for r in adjusted),
        negative_points=sum(bool(r.get('negative_point_estimate')) for r in adjusted),
        negative_ci95=sum(bool(r.get('ci95_entirely_negative')) for r in adjusted),
        raw_adjusted_reversals=sum(bool(r.get('raw_adjusted_sign_reversal')) for r in adjusted),
        individual_monotonicity_proved=False)
