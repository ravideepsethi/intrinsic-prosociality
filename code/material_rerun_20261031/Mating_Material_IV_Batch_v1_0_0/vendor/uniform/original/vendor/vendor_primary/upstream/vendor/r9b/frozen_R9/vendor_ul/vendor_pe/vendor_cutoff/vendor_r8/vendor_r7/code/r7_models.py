"""Part A and B fits with row-identical control comparisons."""
from r7_common import *
from r7_math import *

def model_outcomes(d,kind):
    return ['received','y','reached'] if kind=='iv' else (['y','reached'] if kind=='ordinary' else
           ['analysis_entry_90','recipient_disconnect_main','active_timeout'])

def estimate(d,kind,sample,level='X0',instrument='pooled',recipient_fe=False,part_a=True,calibration=True,release_inputs=False):
    """No selection occurs here: the scheduler binds every row set explicitly."""
    n=len(d['row_id']);out={k:[] for k in TABLES}
    meta=metadata(d,sample,level,instrument,recipient_FE=recipient_fe)
    if n<2000:
        out['B_estimates']=[dict(meta,supported=False,reason='FEWER_THAN_2000_ROWS')];return out,None
    unavailable_y=0
    if part_a and kind=='entry':
        if 'y' not in d:raise RuntimeError('F50 A4 requires the authenticated later-outcome attachment before fitting')
        y=np.asarray(d['y'],float);known=np.isfinite(y)
        if not np.isin(y[known],[0.,1.]).all():raise RuntimeError('Nonbinary F50 later outcome')
        if not known.all():
            if 'complete90' not in d or not np.array_equal(known,np.asarray(d['complete90'],bool)):
                raise RuntimeError('Missing F50 Y is not explained by archived incomplete follow-up')
            unavailable_y=int((~known).sum())
        del y,known
    xs,names,traits,groups=feature_design(d,level,recipient_fe)
    outcomes=model_outcomes(d,kind);yraw=np.column_stack([d[k] for k in outcomes]).astype(float)
    if not np.isin(yraw,[0.,1.]).all():raise RuntimeError('Nonbinary/missing frozen outcome')
    zraw=np.asarray(d['adjusted_7d' if instrument=='pooled' else 'comp_adjusted_7d'],float)
    if not np.isfinite(zraw).all():raise RuntimeError('Missing score in selected model')
    t30=np.column_stack([traits[k] for k in T30])
    traits={k:traits[k] for k in T15 if k not in T30} if part_a else {}
    if release_inputs:
        keep={'row_id','recipient_id','opponent_id','archive_start_ms','environment_supported',
              'received','y','reached','analysis_entry_90','recipient_disconnect_main','active_timeout'}
        for key in list(d):
            if key not in keep:del d[key]
        pa.default_memory_pool().release_unused()
    io.log(f'Fit {sample} {level}: residualizing B outcomes and balance ({n:,} rows)')
    r,rank=project(xs,[zraw]+[yraw[:,j] for j in range(yraw.shape[1])]+[t30[:,j] for j in range(7)],groups)
    z=r[:,0];ys=r[:,1:1+len(outcomes)];ts=r[:,1+len(outcomes):]
    native=float(np.sqrt(np.mean(z*z)));meta.update(native_residual_score_SD=native,
        controls=names,continuous_control_rank=rank,recipients=len(np.unique(d['recipient_id'])))
    if native<1e-10:raise RuntimeError('No score variation')
    io.log(f'Fit {sample} {level}: building shared-account/date covariance keys')
    meat=covariance(d);influences={}
    for j,k in enumerate(outcomes):
        fit,inf=scalar(ys[:,j],z,meat,100*SD[instrument])
        row=dict(meta,outcome=k,estimator='first_stage' if k=='received' else 'reduced_form',
                 events=int(yraw[:,j].sum()),outcome_mean_pp=float(yraw[:,j].mean()*100),**fit)
        if min(row['events'],n-row['events'])<10:row.update(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
        if row.get('supported'):
            row['relative_percent_of_outcome_mean']=100*row['coefficient_pp']/row['outcome_mean_pp'] if row['outcome_mean_pp'] else None
        out['B_estimates'].append(row)
        influences[k]=inf
    if kind=='iv':
        iv=stats.iv_result(ys[:,1],ys[:,0],z,meat)
        fields={k:v for k,v in iv.items() if k not in ('first_stage','reduced_form')}
        for key in ('iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high'):
            if key in iv:fields[key+'_pp']=100*iv[key]
        out['B_estimates'].append(dict(meta,outcome='y',estimator='2SLS',units='percentage points per receipt',
            first_stage_F=iv.get('first_stage',{}).get('wald_F_one_df'),**fields))
    for k,name in enumerate(T30):
        fit=stats.stats.ols(ts[:,k],z/native,meat)
        out['B_balance'].append(dict(meta,trait=name,units='trait SD per native residual score SD',
            raw_score_coefficient=fit.get('coefficient',float('nan'))/native,**fit))
    stats.stats.holm(out['B_balance'],out='p_Holm_7_traits')
    out['B_joint_balance'].append(dict(meta,test_set='T30_stacked_trait_on_score',traits=T30,**stats.stats.joint(ts,z/native,meat)))
    if 'indicator' in level:
        idx=names.index('env_supported');others=[k for k in range(xs.shape[1]) if k!=idx]
        io.log(f'Fit {sample} {level}: availability-indicator coefficients')
        reg=project([xs[:,k] for k in others]+[zraw],[xs[:,idx]]+[yraw[:,j] for j in range(yraw.shape[1])],groups)[0]
        for j,k in enumerate(outcomes):
            fit,_=scalar(reg[:,j+1],reg[:,0],meat,100)
            out['B_indicator'].append(dict(meta,outcome=k,estimator='reduced_form_control_coefficient',
                units='percentage points, supported minus unsupported',unsupported_share=float((~d['environment_supported'].astype(bool)).mean()),**fit))
        del reg,others
    if part_a:
        b,V,_,_=multi(z/native,ts,meat)
        a2=dict(meta,analysis='A2',dependent='score',units='native residual score SD per trait SD')
        for k,trait in enumerate(T30):
            out['A_joint_balance'].append(dict(a2,trait=trait,raw_score_coefficient=float(b[k])*native,**inference(b[k],V[k,k])))
        out['A_joint_tests'].append(dict(a2,test_set='T30_joint_score_on_traits',**wald(b,V)))
        out['A_joint_tests'].append(dict(a2,test_set='T30_stacked_trait_on_score',**stats.stats.joint(ts,z/native,meat)))
        # A1 excludes the eight recipient histories, retains the model's other controls.
        inh=[k for k,name in enumerate(names) if name not in X0[7:]]
        xnh=xs[:,inh];nhnames=[names[k] for k in inh]
        t15=np.column_stack([t30]+[traits[k] for k in T15 if k not in T30])
        del t30,traits,r,z,ys,ts,yraw
        cols=['received','y'] if kind=='iv' else (['analysis_entry_90','recipient_disconnect_main','y'] if kind=='entry' else ['y'])
        if unavailable_y:cols.remove('y')
        yy=np.column_stack([np.asarray(d[k],float) for k in cols])
        io.log(f'Fit {sample} {level}: A1 joint traits')
        rr,_=project(xnh,[t15[:,j] for j in range(15)]+[yy[:,j] for j in range(yy.shape[1])]+[zraw],groups)
        T=rr[:,:15];native_nh=float(np.sqrt(np.mean(rr[:,-1]**2)))
        for j,name in enumerate(cols+['score']):
            v=rr[:,15+j] if name!='score' else rr[:,-1]/native_nh
            b,V,_,_=multi(v,T,meat)
            base=dict(meta,analysis='A1',dependent=name,controls=nhnames,native_residual_score_SD=native_nh,
                      units='native residual score SD per trait SD' if name=='score' else 'percentage points per trait SD')
            scale=1 if name=='score' else 100
            for k,trait in enumerate(T15):
                out['A_joint_balance'].append(dict(base,trait=trait,raw_score_coefficient=float(b[k])*native_nh if name=='score' else None,**inference(b[k],V[k,k],scale)))
            for label,ix in [('T15',list(range(15))),('T30',list(range(7)))]:
                out['A_joint_tests'].append(dict(base,test_set=label,**wald(b[ix],V[np.ix_(ix,ix)])))
        del rr,T,yy,v
        if unavailable_y:
            # The handoff prohibits new row exclusions and outcome imputation.
            # Retain the full frame for every estimable column and make the
            # unavailable full-frame Y column explicit instead of dropping rows.
            unavailable=dict(meta,analysis='A1',dependent='y',controls=nhnames,
                native_residual_score_SD=native_nh,units='percentage points per trait SD',
                supported=False,reason='INCOMPLETE_FOLLOWUP_ON_FROZEN_ROWS',
                missing_outcome_rows=unavailable_y,rows_removed=0,outcomes_imputed=0)
            out['A_joint_balance'] += [dict(unavailable,trait=trait) for trait in T15]
            out['A_joint_tests'] += [dict(unavailable,test_set=label) for label in ('T15','T30')]
            if calibration:
                out['A_predicted_outcome'] += [dict(meta,analysis='A3',predicted_outcome='y',
                    calibration_controls=outer,method=method,supported=False,
                    reason='INCOMPLETE_FOLLOWUP_ON_FROZEN_ROWS',missing_outcome_rows=unavailable_y,
                    rows_removed=0,outcomes_imputed=0)
                    for outer in ('NH','full_model') for method in ('in_sample','crossfit')]
        if calibration:
            io.log(f'Fit {sample} {level}: A3 calibration')
            yy=np.column_stack([np.asarray(d[name],float) for name in cols])
            fits=generated_indices(t15,yy,xnh,{'NH':xnh,'full_model':xs},zraw,
                groups,meat,d['recipient_id'],d['opponent_id'])
            for j,outer,onative,fit in fits:
                for key in ('coefficient','standard_error','ci_low','ci_high'):
                    if key in fit:fit[key+'_pp']=100*SD[instrument]*fit[key]
                for key in ('ci90_low_pp','ci90_high_pp'):
                    if key in fit:fit[key]*=100*SD[instrument]
                fit['conditional_fixed_rule_SE_pp']=100*SD[instrument]*fit['conditional_fixed_rule_SE']
                out['A_predicted_outcome'].append(dict(meta,analysis='A3',predicted_outcome=cols[j],
                    calibration_controls=outer,native_residual_score_SD=onative,
                    training_controls=nhnames,**fit))
    for table in ('A_joint_balance','A_joint_tests'):out[table].sort(key=lambda r:r['analysis'])
    payload=dict(recipient_id=d['recipient_id'],opponent_id=d['opponent_id'],
                 date=d['archive_start_ms']//DAY,**{k:100*SD[instrument]*v for k,v in influences.items() if v is not None})
    return out,payload

def select_sample(d,selection):
    use=np.ones(len(d['row_id']),bool)
    # Repeated-recipient membership is fixed on the full author-clean S0 BEFORE ENV restriction.
    if 'repeat' in selection:
        _,ix,count=np.unique(d['recipient_id'],return_inverse=True,return_counts=True);use &= count[ix]>=2
    if 'env' in selection:use &= d['environment_supported'].astype(bool)
    if 'comp' in selection:use &= comp_mask(d)
    return subset(d,use)

def model_job(job):
    threads_one();no_network()
    def build(tmp):
        d=select_sample(load_fit_columns(job['input']),job['selection'])
        rows,inf=estimate(d,job['kind'],job['sample'],job['level'],job['instrument'],
                         job.get('recipient_fe',False),job.get('part_a',True),job.get('calibration',True),release_inputs=True)
        io.js(tmp/'result.json',rows)
        if job.get('influence') and inf is not None:io.table(tmp/'influence_PRIVATE.parquet',pa.table(inf))
        return dict(rows=len(d['row_id']),sample=job['sample'],control_level=job['level'],instrument=job['instrument'])
    return stable_stage(Path(job['output']),job['conf'],build,[job['input']])[1]

def contrast(left,right,meta):
    """Stack the two score influence functions under common actual accounts/dates."""
    l=arrays(io.read(Path(left)/'influence_PRIVATE.parquet'));r=arrays(io.read(Path(right)/'influence_PRIVATE.parquet'))
    codes=stats.cmp.covariance_codes(np.r_[l['recipient_id'],r['recipient_id']],
        np.r_[l['opponent_id'],r['opponent_id']],np.r_[l['date'],r['date']])
    a=io.load(Path(left)/'result.json')['B_estimates'];b=io.load(Path(right)/'result.json')['B_estimates']
    rows=[]
    for name in ('y','reached'):
        aa=next(v for v in a if v['estimator']=='reduced_form' and v['outcome']==name)
        bb=next(v for v in b if v['estimator']=='reduced_form' and v['outcome']==name)
        s=np.r_[l[name],-r[name]]
        var=float(shared_meat(s,codes,True)[0,0])
        rows.append(dict(meta,outcome=name,receipt_reduced_form_pp=aa['coefficient_pp'],
            ordinary_reduced_form_pp=bb['coefficient_pp'],receipt_n=aa['n'],ordinary_n=bb['n'],
            receipt_row_set_sha256=aa['row_set_sha256'],ordinary_row_set_sha256=bb['row_set_sha256'],
            covariance_accounts_dates_shared_across_samples=True,
            **inference(aa['coefficient_pp']-bb['coefficient_pp'],var)))
    return rows
