"""Statistical functions adapted from the verified IV pilot; no old cohort loader."""
import numpy as np
import math
import iv_numerics as num
DAY=86400000

def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    if isinstance(v,np.ndarray): return clean(v.tolist())
    if isinstance(v,np.generic): return clean(v.item())
    if isinstance(v,float) and not math.isfinite(v): return None
    return v

def imputed_scaled(a):
    a=np.asarray(a,float).copy(); missing=~np.isfinite(a)
    finite=a[~missing]
    med=float(np.median(finite)) if len(finite) else 0.0
    a[missing]=med
    scale=float(np.std(a))
    return (a-med)/(scale if scale>1e-12 else 1.0), missing.astype(float)

def model_inputs(data,mask,spec):
    d={k:v[mask] for k,v in data.items()}
    lag=spec['lag']; controls=[]; control_names=[]; missing_counts={}
    def control(name,values):
        v,m=imputed_scaled(values)
        controls.append(v); control_names.append(name)
        missing_counts[name]=int(m.sum())
        if m.any() and not m.all(): controls.append(m); control_names.append(name+'_missing')
    er=d['exposure_recipient_elo']; ej=d['exposure_chooser_elo']; gap=(ej-er)/100.0
    for name,v in [('recipient_rating',er),('rating_gap',gap),('rating_gap_square',gap**2),
                   ('rating_gap_absolute',np.abs(gap)),('recipient_RD',d['exposure_recipient_rd']),
                   ('chooser_RD',d['exposure_chooser_rd']),
                   ('log_chooser_prior_count',np.log1p(d[f'n_{lag}d'])),
                   ('log_chooser_prior_counterparts',np.log1p(d[f'counterparts_{lag}d'])),
                   ('chooser_history_expected_rate',d[f'expected_{lag}d'])]: control(name,v)
    if spec.get('state_controls'):
        for name,v in [('exposure_eval',np.sign(d['exposure_eval_cp'])*np.log1p(np.abs(d['exposure_eval_cp']))),
                       ('log_exposure_ply',np.log1p(d['exposure_ply_count'])),
                       ('log_chooser_clock',np.log1p(np.maximum(d['exposure_chooser_clock_s'],0))),
                       ('log_recipient_clock',np.log1p(np.maximum(d['exposure_recipient_clock_s'],0)))]: control(name,v)
    if spec.get('recipient_history_controls'):
        for name,v in [('log_prior_disconnects',np.log1p(d['prior_disconnects'])),
                       ('log_prior_receipts',np.log1p(d['prior_receipts'])),
                       ('log_pre_games30',np.log1p(d['pre_games_30d'])),
                       ('log_prior_fair',np.log1p(d['own_fair_n'])),
                       ('prior_kind_ever',(d['own_kind_n']>0).astype(float))]: control(name,v)
    if not np.isfinite(er).all() or not np.isfinite(ej).all():
        mean=np.nan_to_num((er+ej)/2,nan=-10000.0)
    else: mean=(er+ej)/2
    base=d['tc_base_s']; inc=d['tc_inc_s']
    if not np.isfinite(base).all() or not np.isfinite(inc).all(): raise RuntimeError('Missing exact time-control assignment fields')
    _,cell=num.factor(d['month_code'],base.astype(int),inc.astype(int),np.floor(mean/100).astype(int))
    day=d['archive_start_ms']//DAY
    hour=(d['archive_start_ms']//3_600_000)%168
    groups=[cell,hour,day]
    has=(d['own_fair_n']>0)
    priorrate=np.divide(d['own_kind_n'],d['own_fair_n'],out=np.zeros(len(has),float),where=has)
    traits={
      'prior_fair_history_present':has.astype(float),
      'log_prior_fair_opportunities':np.log1p(d['own_fair_n']),
      'prior_kind_indicator':(d['own_kind_n']>0).astype(float),
      'prior_kind_rate_zero_without_history':priorrate,
      'log_prior_disconnections':np.log1p(d['prior_disconnects']),
      'log_prior_receipts':np.log1p(d['prior_receipts']),
      'log_pre_game_volume30':np.log1p(d['pre_games_30d'])}
    z=d[f'{spec["score"]}_{lag}d']
    y=d[spec.get('outcome','other_started_after_y')].astype(float)
    reach=d[spec.get('reach','other_started_after_reached')].astype(float)
    treatment=d['received'].astype(float)
    columns=controls+[z,treatment,y,reach]
    tnames=[]; tsds={}
    for name,v in traits.items():
        v,m=imputed_scaled(v)
        columns.append(v); tnames.append(name); tsds[name]=float(np.std(traits[name]))
    a=np.column_stack(columns)
    res,absinfo=num.partial_out(a,groups,len(controls))
    rz,rd,ry,rr=res[:,0],res[:,1],res[:,2],res[:,3]
    zsd=float(np.sqrt(np.mean(rz**2)))
    if zsd<=1e-12: return None
    rz/=zsd
    rd_sd=float(np.sqrt(np.mean(rd**2)))
    diag={'n':len(y),'receipts':int(treatment.sum()),'outcome_mean':float(y.mean()),
      'control_outcome_mean':float(y[treatment==0].mean()) if np.any(treatment==0) else None,
      'treated_outcome_mean':float(y[treatment==1].mean()) if np.any(treatment==1) else None,
      'reached_n':int(reach.sum()),'raw_instrument_sd':float(np.std(z)),
      'residual_instrument_sd':zsd,'assignment_cells':int(cell.max()+1),
      'exposure_dates':int(len(np.unique(day))),'choosers':int(len(np.unique(d['chooser_id']))),
      'continuous_controls':control_names,'missing_control_counts':missing_counts,**absinfo}
    return {'z':rz,'d':rd,'y':ry,'reach':rr,'traits':res[:,4:],'trait_names':tnames,
            'trait_sd':tsds,'diag':diag,'j':d['chooser_id'],'date':day,'d_sd':rd_sd}

def specification_mask(data,spec):
    z=data[f'{spec["score"]}_{spec["lag"]}d']
    mask=np.isfinite(z)&(data[f'n_{spec["lag"]}d']>=spec['floor'])
    if spec.get('frozen'): mask &= data['frozen_a1_support'].astype(bool)
    if spec.get('breadth'): mask &= data[f'counterparts_{spec["lag"]}d']>=spec['breadth']
    if spec.get('own_history'): mask &= data['own_fair_n']>0
    if spec.get('conditional'): mask &= data[spec.get('reach','other_started_after_reached')].astype(bool)
    return mask

def flatten_ols(label,r,extra):
    row={**extra,'estimator':label,'supported':r.get('supported',False)}
    for k,v in r.items():
        row[k]=v
        if k in ('coefficient','standard_error','ci_low','ci_high'):
            row[k+'_pp']=None if v is None else 100*v
    return row

def estimate_spec(data,spec,extra_mask=None,balance=False):
    mask=specification_mask(data,spec)
    if extra_mask is not None: mask &= extra_mask
    n=int(mask.sum())
    if n<2000 or int(data['received'][mask].sum())<20:
        return [{'specification':spec['name'],'supported':False,'reason':'INSUFFICIENT_SUPPORT','n':n}],[],[]
    r=model_inputs(data,mask,spec)
    if r is None: return [{'specification':spec['name'],'supported':False,'reason':'NO_RESIDUAL_Z_VARIATION','n':n}],[],[]
    rows=[]; balance_rows=[]; joint=[]
    for name,groups in [('chooser_CR0',num.cluster_codes(r['j'])),
                        ('chooser_and_exposure_date_CR0',num.cluster_codes(r['j'],r['date']))]:
        result=num.iv_fit(r['y'],r['d'],r['z'],groups)
        common={'specification':spec['name'],'clustering':name,'n':n,'receipts':r['diag']['receipts'],
          'outcome':spec.get('outcome','other_started_after_y'),'lag_days':spec['lag'],'minimum_history':spec['floor'],
          'post_assignment_state_controls':bool(spec.get('state_controls')),
          'conditional_on_reaching_opportunity':bool(spec.get('conditional')),
          'residual_instrument_sd':r['diag']['residual_instrument_sd'],'choosers':r['diag']['choosers'],
          'exposure_dates':r['diag']['exposure_dates'],'assignment_cells':r['diag']['assignment_cells'],
          'causal_identification_certified':False,'inference_small_cluster_warning':bool(r['diag']['choosers']<50 or (len(groups)==3 and r['diag']['exposure_dates']<50))}
        for label,out in [('first_stage_receipt_per_SD_Z',result['first_stage']),
                          ('reduced_form_kindness_per_SD_Z',result['reduced_form']),
                          ('same_sample_OLS',num.scalar_ols(r['y'],r['d'],groups)),
                          ('reduced_form_reach_per_SD_Z',num.scalar_ols(r['reach'],r['z'],groups))]:
            rows.append(flatten_ols(label,out,common))
        iv={**common,'estimator':'candidate_2SLS','supported':result['supported'],
            'partial_first_stage_R2':result.get('partial_first_stage_R2'),
            'control_outcome_mean_pp':100*r['diag']['control_outcome_mean'] if r['diag']['control_outcome_mean'] is not None else None,
            'reached_n':r['diag']['reached_n']}
        for k in ['iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high']:
            iv[k]=result.get(k)
            iv[k+'_pp']=100*result[k] if k in result else None
        for k in ['AR95_intervals','AR95_unbounded','AR95_reason','AR_covariance_psd']:
            iv[k]=result.get(k)
        fs=result['first_stage']; rf=result['reduced_form']
        if fs.get('supported') and rf.get('supported') and abs(fs['coefficient'])>1e-12:
            iv['approx_MDE80_IV_pp']=100*(1.959963984540054+0.8416212335729143)*rf['standard_error']/abs(fs['coefficient'])
            iv['MDE_caveat']='conditional large-sample approximation; does not include first-stage estimation uncertainty'
        rows.append(iv)
        if balance:
            for predictor,pred in [('Z_per_residual_SD',r['z']),('receipt_D_per_residual_SD',r['d']/r['d_sd'])]:
                for k,trait in enumerate(r['trait_names']):
                    out=num.scalar_ols(r['traits'][:,k],pred,groups)
                    balance_rows.append({**common,'trait':trait,'predictor':predictor,
                       'units':'trait SD per predictor residual SD','no_history_is_not_declining':True,**out})
                joint.append({**common,'predictor':predictor,**num.joint_balance(r['traits'],pred,groups)})
    return rows,balance_rows,joint