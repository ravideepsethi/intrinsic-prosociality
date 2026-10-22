"""Matched descriptive changes and explicitly conditional model comparisons."""
from mc_io import *
from itertools import combinations
AWARENESS=(.05,.1,.2,.5,1.)

def windows():
    pre=complete_weeks(ms('2025-01-01T00:00:00Z'),BRACKET)[-8:]
    unannounced=complete_weeks(IMPLEMENTED,ANNOUNCED)
    out=[dict(name='unannounced',pre=pre,post=unannounced,role='primary_bounded_event_window',cutoff_status='announcement_ends_unannounced_period')]
    for label,end in [('jan7',ms('2026-01-07T00:00:00Z')),('jan30',ms('2026-01-30T00:00:00Z'))]:
        announced=complete_weeks(ANNOUNCED,end)
        out.extend([dict(name='announced_'+label,pre=pre,post=announced,role='truncation_sensitivity',cutoff_status='scenario_not_certified_mechanics_censor'),
                    dict(name='pooled_'+label,pre=pre,post=np.r_[unannounced,announced],role='secondary_truncation_sensitivity',cutoff_status='scenario_not_certified_mechanics_censor')])
    for w in out:
        w['pre_offsets']=(w['pre']-pre[0])//WEEK;w['post_offsets']=(w['post']-pre[0])//WEEK
    return out

def difference(d,column,weeks):
    if d.duplicated(['week_ms','color']).any():raise ValueError('Duplicate week/color cells')
    p=d.pivot(index='week_ms',columns='color',values=column).reindex(index=weeks,columns=['white','black'])
    if p.isna().any().any():raise ValueError('Missing complete week or color')
    return (p.white-p.black).to_numpy(float)

def block_noise(x,pre_offsets,post_offsets,block,reps=10000):
    x=np.asarray(x,float);a=np.asarray(pre_offsets,int);b=np.asarray(post_offsets,int)
    if len(x)<32 or not np.isfinite(x).all():raise ValueError('Need 32 complete pre weeks')
    if min(a.min(),b.min())<0 or len(set(a)&set(b)) or b.min()<=a.max() or np.any(np.diff(a)<=0) or np.any(np.diff(b)<=0):raise ValueError('Invalid event-calendar offsets')
    span=int(b.max()+1);rng=np.random.default_rng(2026092607+100*block+span+len(b))
    starts=rng.integers(0,len(x)-block+1,(reps,int(np.ceil(span/block))))
    samples=x[(starts[:,:,None]+np.arange(block)).reshape(reps,-1)[:,:span]]
    z=samples[:,b].mean(axis=1)-samples[:,a].mean(axis=1)
    z-=z.mean()
    if np.std(z)==0:raise ValueError('Degenerate pre-policy variance')
    return z

def mde(noise):
    critical=float(np.quantile(abs(noise),.95,method='higher'))
    def power(delta):return min(float(np.mean(abs(noise+delta)>critical)),float(np.mean(abs(noise-delta)>critical)))
    lo=0.;hi=max(1.,10*np.std(noise))
    for _ in range(60):
        mid=(lo+hi)/2
        if power(mid)<.8:lo=mid
        else:hi=mid
    return float(hi),critical

def coverage_ok(gates,state,weeks):
    d=pd.DataFrame(gates);d=d[d.state.eq(state)].set_index('week_ms').reindex(weeks)
    counts=['unknown_source_n','unmapped_pool_adjacency_n','clock_rule_violation_n']
    missing=int(d.eligible_before_membership.isna().sum())
    totals={k:int(d[k].fillna(0).sum()) for k in counts}
    return not missing and not any(totals.values()),dict(missing_coverage_weeks=missing,**totals)

def weekly_outcomes(target,work,end,allowed=None):
    c=connect(Path(work)/'tmp/weekly_outcomes',2,1024)
    extra=''
    if allowed is not None:
        if not allowed:raise ValueError('No admitted behavioral weeks')
        terms=[]
        for state,ws in allowed.items():
            terms.append('(state='+q(state)+" AND epoch_ms(date_trunc('week',epoch_ms(t))) IN ("+','.join(map(str,sorted(ws)))+'))')
        extra=' AND ('+' OR '.join(terms)+')'
    try:return c.execute(f'''SELECT state,epoch_ms(date_trunc('week',epoch_ms(t)))::BIGINT week_ms,color,
        count(*)::BIGINT n,sum(y)::BIGINT grants,100.*avg(y) rate_pp,count(DISTINCT chooser) chooser_accounts
        FROM {scan(target)} WHERE t<{int(end)}{extra} GROUP BY ALL ORDER BY state,week_ms,color''').fetchdf()
    finally:c.close()

def run_comparison(target,predictions,gates,work,report,reps=10000):
    work=Path(work);report=Path(report);spec=windows()
    survivors={r['state']:set(r['compatible_models']) for r in read(ROOT/'authority/PRE_MODEL_COMPARISON_STATUS.json')
        if r['comparison']=='rd110_train_rd110_test'}
    # Seal forecast identities before aggregating a single post-policy choice.
    write(report/'PREDICTIONS_SEALED.json',dict(prediction_files=[snapshot(p) for p in sorted(report.glob('*_weekly_predictions.parquet'))],
        conditional_on_fitted_parameters=True,post_outcomes_used_in_predictions=False,plan_sha256=sha(ROOT/'FROZEN_PLAN.json')))
    preweekly=weekly_outcomes(target,work,BRACKET);table(preweekly,report/'pre_weekly_rates')
    noise_weeks=complete_weeks(START,ms('2025-11-01T00:00:00Z'))
    forecast=[];power=[];thresholds=[];status=[];nulls={};diagnostics=[];placebos=[]
    anchors=['2024-03-04','2024-04-29','2024-06-24','2024-08-19','2024-10-14','2024-12-09','2025-02-10','2025-04-21','2025-06-30']
    for state,weeklypred in predictions.items():
        pre=preweekly[preweekly.state.eq(state)]
        try:noise_series=difference(pre,'rate_pp',noise_weeks)
        except ValueError as e:
            status.append(dict(state=state,window='all',status='PRE_SUPPORT_MISSING',reason=str(e)));continue
        diagnostics.append(dict(state=state,weeks=len(noise_series),mean_gap_pp=float(noise_series.mean()),
            slope_pp_per_year=float(np.polyfit(np.arange(len(noise_series)),noise_series,1)[0]*52),
            lag1=float(np.corrcoef(noise_series[:-1],noise_series[1:])[0,1]),
            note='Descriptive; fixed 2025 cohort selection can affect earlier composition and stationarity'))
        lookup=dict(zip(noise_weeks,noise_series))
        for w in spec:
            allweeks=np.r_[w['pre'],w['post']];ok,details=coverage_ok(gates,state,allweeks)
            status.append(dict(state=state,window=w['name'],status='MATCHED_COVERAGE_PASSED' if ok else 'SOURCE_OR_ADJACENCY_OR_CLOCK_GAP',**details,
                post_weeks=len(w['post']),role=w['role'],cutoff_status=w['cutoff_status']))
            if not ok:continue
            pw=[]
            try:
                for (model,baseline),d in weeklypred.groupby(['model','baseline'],sort=True):
                    mech=float(difference(d,'mechanical_delta_pp',w['post']).mean())
                    base=float(difference(d,'old_rate_pp',w['post']).mean()-difference(d,'old_rate_pp',w['pre']).mean())
                    row=dict(state=state,window=w['name'],model=model,baseline=baseline,mechanical_shift_pp=mech,
                        no_policy_composition_change_pp=base,total_prediction_full_awareness_pp=base+mech,
                        parameter_uncertainty_propagated=False,pre_policy_compatible=model in survivors[state],
                        post_weeks=len(w['post']),cutoff_status=w['cutoff_status'])
                    pw.append(row)
            except ValueError as e:
                status[-1].update(status='PREDICTION_WEEK_MISSING',reason=str(e));continue
            forecast.extend(pw)
            for b in (4,8):
                try:z=block_noise(noise_series,w['pre_offsets'],w['post_offsets'],b,reps);md,critical=mde(z)
                except ValueError as e:
                    status.append(dict(state=state,window=w['name'],status='NO_NOISE_ESTIMATE',reason=str(e)));continue
                nulls[(state,w['name'],b)]=z
                thresholds.append(dict(state=state,window=w['name'],block_weeks=b,mde_80_pp=md,critical_5_pp=critical,
                    post_weeks=len(w['post']),noise_pre_weeks=len(noise_series),event_pre_weeks=8,
                    post_offsets=','.join(map(str,w['post_offsets'])),formal_causal_interval=False))
                main=[r for r in pw if r['baseline']=='account20']
                for a1,a2 in combinations(main,2):
                    for awareness in AWARENESS:
                        mdiff=awareness*(a1['mechanical_shift_pp']-a2['mechanical_shift_pp'])
                        tdiff=a1['no_policy_composition_change_pp']-a2['no_policy_composition_change_pp']+mdiff
                        power.append(dict(state=state,window=w['name'],block_weeks=b,model_a=a1['model'],model_b=a2['model'],awareness=awareness,
                            mechanical_difference_pp=mdiff,total_prediction_difference_pp=tdiff,
                            both_pre_policy_compatible=a1['pre_policy_compatible'] and a2['pre_policy_compatible'],
                            conditional_mechanical_power=min(float(np.mean(abs(z+mdiff)>critical)),float(np.mean(abs(z-mdiff)>critical))),
                            conditional_total_forecast_power=min(float(np.mean(abs(z+tdiff)>critical)),float(np.mean(abs(z-tdiff)>critical))),
                            parameter_uncertainty_propagated=False))
            for date in anchors:
                origin=ms(date+'T00:00:00Z')-8*WEEK;before=origin+w['pre_offsets']*WEEK;after=origin+w['post_offsets']*WEEK
                if all(t in lookup for t in np.r_[before,after]):
                    placebos.append(dict(state=state,window=w['name'],anchor=date,change_pp=float(np.mean([lookup[t] for t in after])-np.mean([lookup[t] for t in before])),
                        independent_replication=False))
    for name,rows in [('window_status',status),('matched_predictions',forecast),('matched_pairwise_power',power),('matched_MDE',thresholds),
                      ('pre_temporal_diagnostics',diagnostics),('fixed_placebos',placebos)]:table(rows,report/name)
    # The same source-complete windows, rows, colors and equal-week weights are
    # used below. Closed windows never trigger a partial-sample substitution.
    admitted={(r['state'],r['window']) for r in status if r['status']=='MATCHED_COVERAGE_PASSED'}
    if not admitted:return dict(status='MATCHED_SAMPLE_BUILT_BEHAVIOR_WITHHELD_FOR_COVERAGE',windows=status)
    allowed={}
    for state,window in admitted:
        w=next(w for w in spec if w['name']==window)
        allowed.setdefault(state,set()).update(map(int,np.r_[w['pre'],w['post']]))
    actual=weekly_outcomes(target,work,ms('2026-01-30T00:00:00Z'),allowed);table(actual,report/'matched_weekly_rates')
    estimates=[];comparisons=[]
    for state,window in sorted(admitted):
        w=next(w for w in spec if w['name']==window);d=actual[actual.state.eq(state)]
        try:before=difference(d,'rate_pp',w['pre']);after=difference(d,'rate_pp',w['post'])
        except ValueError:continue
        observed=float(after.mean()-before.mean())
        for b in (4,8):
            if (state,window,b) not in nulls:continue
            z=nulls[(state,window,b)];lo=observed-np.quantile(z,.975);hi=observed-np.quantile(z,.025)
            estimates.append(dict(state=state,window=window,block_weeks=b,observed_change_pp=observed,
                lo_pp=lo,hi_pp=hi,pre_gap_pp=before.mean(),post_gap_pp=after.mean(),post_weeks=len(after),
                cutoff_status=w['cutoff_status'],interpretation='Descriptive matched contrast; conditional pre-period block interval'))
            for p in [r for r in forecast if r['state']==state and r['window']==window and r['baseline']=='account20']:
                for awareness in AWARENESS:
                    predicted=p['no_policy_composition_change_pp']+awareness*p['mechanical_shift_pp'];residual=observed-predicted
                    pv=(1+int(np.sum(abs(z)>=abs(residual))))/(len(z)+1)
                    comparisons.append(dict(state=state,window=window,block_weeks=b,model=p['model'],awareness=awareness,
                        pre_policy_compatible=p['pre_policy_compatible'],
                        observed_change_pp=observed,mechanical_prediction_pp=awareness*p['mechanical_shift_pp'],
                        no_policy_composition_change_pp=p['no_policy_composition_change_pp'],total_prediction_pp=predicted,
                        conditional_p=pv,parameter_uncertainty_propagated=False,unconditional_rejection=False,
                        note='Parallel color evolution, baseline transport and awareness assumptions; no motive shares'))
    table(estimates,report/'matched_behavioral_contrasts');table(comparisons,report/'conditional_point_fit_comparisons')
    return dict(status='MATCHED_DESCRIPTIVE_COMPARISON_COMPLETE' if estimates else 'MATCHED_COMPARISON_INSUFFICIENT_TIME_SUPPORT',
        behavior_windows_estimated=len({(r['state'],r['window']) for r in estimates}),windows=status,
        causal_adjudication=False,mechanics_censor_certified=False,parameter_uncertainty_propagated=False)
