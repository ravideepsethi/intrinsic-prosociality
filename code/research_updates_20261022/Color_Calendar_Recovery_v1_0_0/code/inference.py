"""Calendar-matched pre-only block noise, conditional model comparisons."""
from io_utils import *

AWARENESS=(.05,.1,.2,.5,1.)
SEED=2026092607
PLACEBO_ANCHORS=('2024-03-04','2024-04-29','2024-06-24','2024-08-19','2024-10-14','2024-12-09',
                 '2025-01-06','2025-02-10','2025-03-17','2025-04-21','2025-05-26','2025-06-30')

def weekly_outcomes(path,work,hi):
    c=connect(Path(work)/'tmp/weekly',2,1024)
    try:
        # In planning mode this query cannot aggregate a post-policy outcome.
        return c.execute(f'''SELECT epoch_ms(date_trunc('week',epoch_ms(t)))::BIGINT week_ms,color,
           count(*)::BIGINT n,sum(y)::BIGINT grants,100.*avg(y) rate_pp
           FROM {scan(path)} WHERE t<{int(hi)} GROUP BY ALL ORDER BY week_ms,color''').fetchdf()
    finally:c.close()

def weekly_difference(d,value,required_weeks):
    if d.duplicated(['week_ms','color']).any():raise ValueError('Duplicate weekly/color cells')
    p=d.pivot(index='week_ms',columns='color',values=value).reindex(index=required_weeks,columns=['white','black'])
    if p.isna().any().any():raise ValueError('Missing complete week or color; not filled with zero')
    return (p.white-p.black).to_numpy(float)

def windows(censor=None):
    pre=complete_weeks(int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000),IMPLEMENTED)[-8:]
    if len(pre)!=8:raise RuntimeError('Eight complete pre weeks required')
    end=int(pd.Timestamp('2026-01-30',tz='UTC').timestamp()*1000) if censor is None else int(censor)
    u=complete_weeks(IMPLEMENTED,min(ANNOUNCED,end));a=complete_weeks(ANNOUNCED,end)
    result=[]
    for label,post in [('unannounced',u),('announced',a),('pooled_secondary',np.r_[u,a])]:
        if len(post):result.append(dict(period=label,pre=pre,post=post,
            pre_offsets=((pre-pre[0])//(7*DAY)).astype(int),post_offsets=((post-pre[0])//(7*DAY)).astype(int),
            timing='Illustrative through-Jan29 calendar only; not a certified censor' if censor is None else 'Actual certified censor'))
    return result

def block_null(pre,pre_offsets,post_offsets,block,reps=10000,seed=SEED):
    x=np.asarray(pre,float)
    if len(x)<max(32,2*block) or not np.isfinite(x).all():raise ValueError('At least 32 finite complete pre weeks required')
    x=x-x.mean();po=np.asarray(post_offsets,int);bo=np.asarray(pre_offsets,int)
    if po.ndim!=1 or bo.ndim!=1 or not len(po) or not len(bo):
        raise ValueError('Calendar offsets must be nonempty one-dimensional arrays')
    if np.any(po<0) or np.any(bo<0) or np.any(np.diff(po)<=0) or np.any(np.diff(bo)<=0) or po[0]<=bo[-1]:
        raise ValueError('Invalid calendar offsets: post weeks must follow pre weeks, with nonnegative increasing indices')
    n=int(max(po.max(),bo.max())+1);rng=np.random.default_rng(seed+block+n+len(po))
    starts=rng.integers(0,len(x)-block+1,(reps,int(np.ceil(n/block))))
    idx=(starts[:,:,None]+np.arange(block)).reshape(reps,-1)[:,:n]
    samples=x[idx]
    return samples[:,po].mean(axis=1)-samples[:,bo].mean(axis=1)

def pre_diagnostics(pre_weekly,spec,coverage_start,coverage_end,report):
    """Fixed overlapping placebo dates and descriptive temporal diagnostics."""
    ws=complete_weeks(coverage_start,min(coverage_end,IMPLEMENTED))
    x=weekly_difference(pre_weekly,'rate_pp',ws);lookup=dict(zip(ws,x))
    if len(x)<32:raise ValueError('Insufficient pre-period support')
    result=dict(complete_pre_weeks=len(x),mean_color_gap_pp=float(x.mean()),
        descriptive_linear_slope_pp_per_52_weeks=float(np.polyfit(np.arange(len(x)),x,1)[0]*52),
        first_26_week_mean_pp=float(x[:26].mean()),last_26_week_mean_pp=float(x[-26:].mean()),
        note='Descriptive stationarity checks; slope has no iid standard error and is not a pre-trend certification')
    result['autocorrelations']={str(k):float(np.corrcoef(x[:-k],x[k:])[0,1]) if np.std(x[:-k])*np.std(x[k:])>0 else None for k in (1,2,4,8,12)}
    write(Path(report)/'pre_temporal_diagnostics.json',result)
    rows=[]
    for anchor in PLACEBO_ANCHORS:
        monday=int(pd.Timestamp(anchor,tz='UTC').timestamp()*1000)
        for w in spec:
            # Implementation's mixed week is offset 8 from the baseline origin.
            origin=monday-8*7*DAY;before=origin+w['pre_offsets']*7*DAY;after=origin+w['post_offsets']*7*DAY
            available=all(t in lookup for t in np.r_[before,after])
            rows.append(dict(placebo_implementation_week=anchor,period=w['period'],available=available,
                change_pp=float(np.mean([lookup[t] for t in after])-np.mean([lookup[t] for t in before])) if available else None,
                interpretation='Overlapping descriptive placebo windows; not independent replications'))
    table(rows,Path(report)/'pre_placebo_statistics.parquet')

def mde(null,direction):
    if direction not in (-1,1):raise ValueError('MDE direction must be +/-1')
    null=np.asarray(null,float);critical=float(np.quantile(abs(null),.95))
    lo=0.;hi=max(1e-6,10*float(np.std(null)))
    while np.mean(abs(null+direction*hi)>critical)<.8:hi*=2
    for _ in range(55):
        mid=(lo+hi)/2
        if np.mean(abs(null+direction*mid)>critical)<.8:lo=mid
        else:hi=mid
    return hi,critical

def summaries(prediction_paths,coverage_start,coverage_end,actual):
    result=[];allweeks=complete_weeks(coverage_start,min(coverage_end,IMPLEMENTED))
    spec=windows(coverage_end if actual else None)
    compatible=next(r['compatible_models'] for r in read(ROOT/'authority/MODEL_COMPARISON_STATUS.json')
        if r['state']=='equal' and r['comparison']=='rd110_train_rd110_test')
    for path in prediction_paths:
        d=pd.read_parquet(path);model=d.model.iloc[0];stage=d.fit_stage.iloc[0]
        for w in spec:
            use=w['post'] if actual else allweeks
            effect=float(weekly_difference(d,'mean_delta_pp',use).mean())
            p=d[d.week_ms.isin(use)]
            values=p.groupby('color',observed=True)[['mean_delta_pp','mean_old','mean_new']].mean()
            result.append(dict(target='actual_frozen_cohort' if actual else 'capped_pre_policy_transport',
                period=w['period'],model=model,fit_stage=stage,prediction_pp=effect,
                white_shift_pp=values.loc['white','mean_delta_pp'],black_shift_pp=values.loc['black','mean_delta_pp'],
                white_old_probability=values.loc['white','mean_old'],black_old_probability=values.loc['black','mean_old'],
                prediction_weeks=len(use),planned_post_weeks=len(w['post']),
                pre_policy_compatible=model in compatible,
                actual_frozen_cohort=actual,units='percentage points after logistic probability conversion',
                uncertainty='Fixed-fit prediction; forward-fit range is descriptive sensitivity only'))
    return pd.DataFrame(result),spec

def analyze_power(pre_weekly,predictions,spec,coverage_start,coverage_end,report,reps=10000):
    end=min(coverage_end,IMPLEMENTED);ws=complete_weeks(coverage_start,end)
    pre=weekly_difference(pre_weekly,'rate_pp',ws)
    if len(pre)<32:raise ValueError('Insufficient complete pre weeks')
    rows=[];nulls={};criticals={}
    for w in spec:
        pw=predictions[(predictions.period==w['period'])&(predictions.fit_stage=='full')]
        full=dict(zip(pw.model,pw.prediction_pp))
        compatible=set(pw.loc[pw.pre_policy_compatible,'model'])
        for block in (4,8):
            null=block_null(pre,w['pre_offsets'],w['post_offsets'],block,reps)
            neg,critical=mde(null,-1);pos,_=mde(null,1)
            nulls[(w['period'],block)]=null;criticals[(w['period'],block)]=critical
            table(pd.DataFrame({'null_pp':null}),Path(report)/f"null_{w['period']}_block{block}.parquet")
            for i,ma in enumerate(sorted(full)):
                for mb in sorted(full)[i+1:]:
                    for qv in AWARENESS:
                        delta=qv*(full[ma]-full[mb]);threshold=neg if delta<0 else pos
                        rows.append(dict(period=w['period'],model_a=ma,model_b=mb,effective_updating=qv,
                            both_models_pre_policy_compatible=ma in compatible and mb in compatible,
                            predicted_difference_pp=delta,post_weeks=len(w['post']),block_weeks=block,
                            pre_weeks=len(pre),pre_offsets=','.join(map(str,w['pre_offsets'])),
                            post_offsets=','.join(map(str,w['post_offsets'])),mde_negative_pp=neg,mde_positive_pp=pos,
                            critical_abs_pp=critical,conditional_power=float(np.mean(abs(null+delta)>critical)),
                            reaches_80_percent_conditional_power=bool(np.mean(abs(null+delta)>critical)>=.8),
                            actual_frozen_cohort=bool(pw.actual_frozen_cohort.iloc[0]),
                            parameter_uncertainty_propagated=False,automatic_go=False))
    return pd.DataFrame(rows),nulls,criticals

def observed_comparison(target,work,spec,predictions,nulls,report):
    # Called only after authenticated input checks and after prediction/power files are sealed.
    hi=max(int(w['post'][-1]+7*DAY) for w in spec)
    weekly=weekly_outcomes(target,work,hi);rows=[];stats=[]
    for w in spec:
        before=weekly_difference(weekly,'rate_pp',w['pre']);after=weekly_difference(weekly,'rate_pp',w['post'])
        observed=float(after.mean()-before.mean())
        for block in (4,8):
            null=nulls[(w['period'],block)];lo=observed-float(np.quantile(null,.975));hi_ci=observed-float(np.quantile(null,.025))
            stats.append(dict(period=w['period'],block_weeks=block,observed_change_pp=observed,lo_pp=lo,hi_pp=hi_ci,
                pre_mean_pp=float(before.mean()),post_mean_pp=float(after.mean()),post_weeks=len(after),
                interpretation='Descriptive color change with pre-period block inference; parallel-color and composition assumptions required'))
            for r in predictions[(predictions.period==w['period'])&(predictions.fit_stage=='full')].to_dict('records'):
                for qv in AWARENESS:
                    prediction=qv*r['prediction_pp'];residual=observed-prediction
                    pvalue=(1+int(np.sum(abs(null)>=abs(residual))))/(len(null)+1)
                    rows.append(dict(period=w['period'],block_weeks=block,model=r['model'],effective_updating=qv,
                       prediction_pp=prediction,observed_change_pp=observed,conditional_p=pvalue,
                       compatible_at_point_fit=pvalue>=.05,parameter_uncertainty_propagated=False,
                       claim='Point-fit sensitivity only; no unconditional model rejection or mechanism share'))
    table(weekly,Path(report)/'actual_weekly_rates.parquet');table(stats,Path(report)/'actual_color_statistic.parquet')
    table(rows,Path(report)/'actual_point_fit_compatibility.parquet');return stats
