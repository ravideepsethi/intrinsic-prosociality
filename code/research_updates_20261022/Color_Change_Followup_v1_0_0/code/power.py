"""Outcome-free dose support and pre-period weekly power screens.
Expected runtime: 5-30 min; memory-mapped arrays, then small seeded bootstraps.
These are diagnostic controls/statistics, not a released A3 or A4 estimate.
"""
from __future__ import annotations
from io_tools import *

PLACEBOS=('2024-02-05','2024-03-18','2024-05-06','2024-06-17','2024-08-05','2024-09-16',
          '2024-11-04','2024-12-16','2025-02-03','2025-03-17','2025-05-05','2025-07-07')

def absorb_inplace(x,groups,tol=1e-9,max_iter=100):
    """Alternating orthogonal projections, with a final BOTH-margin check."""
    counts=[np.bincount(g).astype(float) for g in groups]
    initial=np.sqrt(np.mean(np.asarray(x)**2,axis=0)) if len(x)<100000 else np.array([np.sqrt(np.dot(x[:,j],x[:,j])/len(x)) for j in range(x.shape[1])])
    scale=np.maximum(initial,1e-6)
    for iteration in range(max_iter):
        for g,n in zip(groups,counts):
            for j in range(x.shape[1]):
                means=np.bincount(g,weights=x[:,j],minlength=len(n))/np.maximum(n,1)
                x[:,j]-=means[g]
        max_mean=0.
        for g,n in zip(groups,counts):
            for j in range(x.shape[1]):
                m=np.bincount(g,weights=x[:,j],minlength=len(n))/np.maximum(n,1)
                max_mean=max(max_mean,float(np.max(np.abs(m)))/scale[j])
        if iteration%10==0:log(f'Dose-support absorption {iteration+1}: largest scaled group mean {max_mean:.3g}')
        if max_mean<tol:return dict(iterations=iteration+1,max_scaled_group_mean=max_mean,tolerance=tol)
    raise RuntimeError(f'Fixed-effect projection did not converge: residual group mean {max_mean}; support not certified')

def residual_support(x,groups):
    """Column 0 is Post*dG; remaining columns are diagnostic controls."""
    raw_ss=float(np.dot(x[:,0]-x[:,0].mean(),x[:,0]-x[:,0].mean()))
    conv=absorb_inplace(x,groups)
    p=x.shape[1];gram=np.empty((p,p))
    for i in range(p):
        for j in range(i+1):gram[i,j]=gram[j,i]=np.dot(x[:,i],x[:,j])
    zz=gram[1:,1:];zx=gram[1:,0]
    vals,vecs=np.linalg.eigh(zz)
    threshold=max(1e-12,float(vals.max())*1e-10);keep=vals>threshold
    coef=vecs[:,keep]@((vecs[:,keep].T@zx)/vals[keep]) if keep.any() else np.zeros(p-1)
    ss=0.;largest=0.
    for start in range(0,len(x),100000):
        a=np.asarray(x[start:start+100000]);e=a[:,0]-a[:,1:]@coef
        ss+=float(np.dot(e,e));largest=max(largest,float(np.max(np.abs(e))))
    return dict(n=len(x),raw_treatment_centered_ss=raw_ss,after_chooser_week_ss=float(gram[0,0]),
       residual_treatment_ss=ss,residual_treatment_sd=float(np.sqrt(ss/len(x))),
       fraction_ss_remaining=ss/raw_ss if raw_ss>0 else None,max_abs_residual=largest,
       controls_rank=int(keep.sum()),controls_columns=p-1,rank_tolerance=threshold,
       positive_control_eigenvalues=vals[keep].tolist(),projection=conv)

def support_scenario(work,scenario,end,threads,memory_mb):
    work=Path(work);paths=sorted((work/'narrow').glob('month=*/opportunities.parquet'))
    dest=work/'support'/scenario/'support.json';dest.parent.mkdir(parents=True,exist_ok=True)
    key=digest(dict(version=VERSION,scenario=scenario,end=end,inputs=[stamp(p) for p in paths]))
    if dest.is_file():
        r=read_json(dest)
        if r.get('key')!=key:raise RuntimeError('Existing support scenario changed')
        return r
    c=connection(work/'tmp'/scenario,threads,memory_mb)
    # Controls are fixed before this run, contain no outcome, and omit unavailable account age.
    features=[f'(utc_ms>={CUTOFF})::DOUBLE*d_G','d_G',"(color='white')::DOUBLE",'K_old/20.','E_old',
      'greatest(-6.,least(6.,cp/100.))','ln(1+greatest(0,coalesce(ply,0)))',
      'ln(1+greatest(0,coalesce(chooser_clock,0)))','ln(1+greatest(0,coalesce(opp_clock,0)))',
      '(chooser_clock IS NULL OR NOT isfinite(chooser_clock))::DOUBLE',
      '(opp_clock IS NULL OR NOT isfinite(opp_clock))::DOUBLE']
    features += [f'(speed={q(s)})::DOUBLE' for s in SPEEDS[1:]]
    fields=[f'{s} AS z{j}' for j,s in enumerate(features)]
    sql=f"SELECT chooser_id,(epoch_ms(week)//604800000)::BIGINT AS week_id,"+','.join(fields)+f" FROM {scan(paths)} WHERE established AND board_state='competitive' AND utc_ms<{end} AND period<>'transition'"
    try:
        n=c.execute('SELECT count(*) FROM ('+sql+')').fetchone()[0]
        if n<2:raise RuntimeError('Insufficient rows for support')
        scratch=dest.parent/'matrix.npy'
        x=np.lib.format.open_memmap(scratch,mode='w+',dtype=np.float64,shape=(n,len(features)),fortran_order=True)
        ids=np.empty(n,dtype=np.int64);weeks=np.empty(n,dtype=np.int64);pos=0
        reader=c.execute(sql).fetch_record_batch(100000)
        for b in reader:
            stop=pos+b.num_rows
            for k,arr in enumerate([ids,weeks]):
                col=b.column(k)
                if col.null_count:raise RuntimeError('Missing identifier in established support sample')
                arr[pos:stop]=col.to_numpy(zero_copy_only=False)
            for j in range(len(features)):x[pos:stop,j]=b.column(j+2).to_numpy(zero_copy_only=False)
            pos=stop
        if pos!=n:raise RuntimeError('Support row count changed')
        if any(not np.isfinite(x[:,j]).all() for j in range(x.shape[1])):raise RuntimeError('Nonfinite control in support matrix')
        c.close();c=None
        _,groups=np.unique(ids,return_inverse=True);_,wg=np.unique(weeks,return_inverse=True)
        del ids,weeks
        # Count pre/post support from exact timestamps, including zero-dose rows.
        c2=connection(work/'tmp'/(scenario+'_membership'),threads,memory_mb)
        both=c2.execute(f"SELECT count(*) FROM (SELECT chooser_id FROM {scan(paths)} WHERE established AND board_state='competitive' AND utc_ms<{end} AND period<>'transition' GROUP BY chooser_id HAVING count(*) FILTER(WHERE utc_ms<{BRACKET})>0 AND count(*) FILTER(WHERE utc_ms>={CUTOFF})>0)").fetchone()[0];c2.close()
        result=residual_support(x,[groups,wg]);result.update(key=key,scenario=scenario,end_exclusive_utc=str(pd.to_datetime(end,unit='ms',utc=True)),
          choosers=int(groups.max()+1),weeks=int(wg.max()+1),choosers_in_both_periods=int(both),
          sample='all-source competitive fixed established cohort; NOT manuscript pool extension',
          controls=features[1:],missing_from_final_A3=['account tenure','time-control details','full board/stage specification'],
          interpretation='Variance of Post*dG after chooser/week effects and these diagnostic controls only; no Y regression, SE, causal coefficient, or automatic GO decision.',
          censoring='Prespecified truncation scenario, not a certified grace deployment cutoff')
        write_json(dest,result);del x;scratch.unlink(missing_ok=True);return result
    finally:
        if c is not None:c.close()

def moving_block_noise(y,before,after,block,reps,seed):
    y=np.asarray(y,float)
    if len(y)<max(block,before+after):raise ValueError('Too few complete pre-period weeks')
    rng=np.random.default_rng(seed);length=before+after
    starts=rng.integers(0,len(y)-block+1,size=(reps,(length+block-1)//block))
    idx=(starts[:,:,None]+np.arange(block)).reshape(reps,-1)[:,:length]
    draws=y[idx]
    stats=draws[:,before:].mean(axis=1)-draws[:,:before].mean(axis=1)
    return stats-stats.mean()

def empirical_mde(noise,alpha=.05,power=.8):
    crit=float(np.quantile(abs(noise),1-alpha,method='higher'))
    def probability(effect):
        return min(float(np.mean(abs(noise+effect)>crit)),float(np.mean(abs(noise-effect)>crit)))
    low=0.;high=max(1e-8,2*crit)
    while probability(high)<power:high*=2
    for _ in range(60):
        mid=(low+high)/2
        if probability(mid)>=power:high=mid
        else:low=mid
    return crit,high,probability

def weekly_screen(report):
    report=Path(report);df=pd.read_parquet(report/'weekly_cells.parquet');outputs=[];boots=[];placebos=[];visibility=[]
    for sample in sorted(df['sample'].unique()):
        z=df[(df['sample']==sample)&(df.stratum=='fixed_established')&(df.board_state=='competitive')].copy()
        z['pct']=100*z.grants/z.opportunities
        # Sum counts rather than average rates if future output adds subcells.
        z=z.groupby(['week','color'])[['grants','opportunities']].sum();z['pct']=100*z.grants/z.opportunities
        pivot=z.pct.unstack();pivot.index=pd.DatetimeIndex(pivot.index).as_unit('ns')
        pivot['difference_pp']=pivot['white']-pivot['black']
        complete=pivot[(pivot.index>=pd.Timestamp('2023-11-06'))&(pivot.index<=pd.Timestamp('2025-11-10'))].dropna()
        # Pool authority ends Oct 31; its final week is incomplete and is excluded.
        if sample=='pool_observed_nonadjacent':complete=complete[complete.index<=pd.Timestamp('2025-10-20')]
        if len(complete)<40:continue
        expected=pd.date_range(complete.index.min(),complete.index.max(),freq='W-MON')
        if not complete.index.equals(expected):raise RuntimeError('Missing complete pre-period weeks: '+sample)
        y=complete.difference_pp.to_numpy()
        for after in (4,8):
            before=8
            for block in (4,8):
                seed=17291+after*101+block*997
                noise=moving_block_noise(y,before,after,block,10000,seed)
                crit,mde,pfun=empirical_mde(noise)
                boots.append(dict(sample=sample,pre_weeks=len(y),before_weeks=before,after_weeks=after,block_weeks=block,
                  repetitions=len(noise),seed=seed,critical_abs_pp=crit,mde_80pct_two_sided_pp=mde,
                  statistic='unweighted mean post weekly White-minus-Black rate minus mean of 8 preceding weeks',
                  scope='pre-period stationarity-based planning screen; NOT A3/A4 inference'))
                for slope in (.003,.004):
                    full_effect=2*ADVANTAGE*slope
                    for awareness in (.05,.1,.2,.5,1.):
                        visibility.append(dict(sample=sample,after_weeks=after,block_weeks=block,
                          slope_pp_per_rating_point=slope,awareness_scenario=awareness,
                          predicted_abs_color_contrast_pp=full_effect*awareness,
                          modeled_power=pfun(full_effect*awareness),mde_divided_by_predicted=mde/(full_effect*awareness),
                          note='Illustrative smooth-profile relocation prediction only; awareness is assumed, not measured'))
            for date in PLACEBOS:
                t=pd.Timestamp(date);a=complete.reindex(pd.date_range(t-pd.Timedelta(weeks=before),periods=before,freq='W-MON')).difference_pp
                b=complete.reindex(pd.date_range(t,periods=after,freq='W-MON')).difference_pp
                valid=bool(a.notna().all() and b.notna().all())
                placebos.append(dict(sample=sample,date=date,before_weeks=before,after_weeks=after,complete=valid,
                  contrast_pp=float(b.mean()-a.mean()) if valid else None))
        p=pivot.reset_index();p['sample']=sample;p['complete_pre_week']=p.week.isin(complete.index);outputs.append(p)
    for name,rows in [('weekly_power_screen',boots),('awareness_planning_scenarios',visibility),('frozen_pre_placebos',placebos)]:
        d=pd.DataFrame(rows);frame(d,report/(name+'.parquet'));d.to_csv(report/(name+'.csv'),index=False)
    if outputs:
        d=pd.concat(outputs,ignore_index=True);frame(d,report/'weekly_difference.parquet');d.to_csv(report/'weekly_difference.csv',index=False)
    write_json(report/'POWER_GATE.json',dict(status='FORMAL_GO_DECISION_NOT_YET_ELIGIBLE',
       calculated='Pre-period weekly-contrast MDE at 80% power and 5% two-sided size, under moving-block stationarity approximation; sensitivity to block lengths 4 and 8.',
       not_calculated='MDE of the final continuous DiD or symmetric threshold DDD; exact visibility; final sample-specific causal bound.',
       reasons=['Post-period pool/observed-adjacency membership not certified','Grace deployment/censor timestamp not certified',
         'Exact display visibility unidentified','A3 control/tenure support and A4 exact response statistic still require finalization'],
       no_new_post_outcome_selection=True,placebo_dates=list(PLACEBOS)))
