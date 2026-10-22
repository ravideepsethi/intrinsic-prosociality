"""Same-row control ladder, entry shape and linked reduced-form/IV diagnostics."""
from env_common import *
import env_status
import env_numerics

SD=oldmodels.SD
ROLE_OUTS=['opponent_disconnect_main','timeout_role_unclassified']

def outcome_matrix(d,kind):
    if kind=='entry':
        oldmodels.outcomes(d)
        if np.any(d['active_timeout']!=(d['recipient_disconnect_main']|d['opponent_disconnect_main']|d['timeout_role_unclassified'])):raise RuntimeError('Timeout role categories do not partition recorded timeout')
        if np.any(d['recipient_disconnect_main']&d['opponent_disconnect_main']):raise RuntimeError('Both focal players classified as disconnected')
        names=list(ENTRY_COLUMNS)+ROLE_OUTS
        known,_=env_status.validate(d)
        if known.all():
            for status in ('outoftime','resign','mate'):
                d['ending_'+status]=d['status']==status;names.append('ending_'+status)
        # Entry outcomes retain all rows when legacy ending metadata is absent.
        # Optional ending regressions require recorded status for the whole cohort.
        y=np.column_stack([d[k] for k in names]).astype(float)
    else:
        names=(['received'] if kind=='iv' else [])+['y','reached']
        y=np.column_stack([d[k] for k in names]).astype(float)
    if not np.isfinite(y).all() or not np.isin(y,[0,1]).all():raise RuntimeError('Invalid model outcome')
    return y,names

def bin_diagnostics(d,z,y,ynames,edges,meta,codes):
    b=np.searchsorted(np.asarray(edges),d['comp_adjusted_7d'],side='left')
    zz=float(z@z);rows=[]
    if zz<=1e-20:return [dict(meta,supported=False,reason='NO_RESIDUAL_SCORE_VARIATION_FOR_BIN_DECOMPOSITION')]
    selected_names=[k for k in ('recipient_disconnect_main','opponent_disconnect_main','analysis_entry_90') if k in ynames]
    for k in range(len(edges)+1):
        use=b==k;n=int(use.sum())
        base=dict(meta,bin=k+1,lower_exclusive=edges[k-1] if k else None,upper_inclusive=edges[k] if k<len(edges) else None,
            bin_rows=n,share_of_rows=n/len(b),above_frozen_q95=k>=5,
            residual_score_variance_share=float(z[use]@z[use])/zz if zz else None,
            opponents=int(len(np.unique(d['opponent_id'][use]))),median_prior_competitive_decisions=float(np.median(d['comp_n_7d'][use])) if n else None)
        for name in selected_names:
            j=ynames.index(name);out=y[:,j]
            # Exact algebraic contribution to the full-sample adjusted OLS slope.
            contribution=float(z[use]@out[use])/zz if zz else None
            rows.append(dict(base,outcome=name,adjusted_slope_contribution_pp_per_fixed_SD=100*SD['competitive']*contribution if contribution is not None else None,
                raw_events=int(np.asarray(d[name])[use].sum()),raw_rate_pp=float(np.asarray(d[name])[use].mean())*100 if n else None,
                adjusted_mean_pp=float(out[use].mean())*100 if n else None,
                adjusted_mean_interpretation='mean control-residualized outcome, not a fitted probability; descriptive conditional on fitted controls',
                causal_decomposition=False))
    for name in selected_names:
        total=sum(r['adjusted_slope_contribution_pp_per_fixed_SD'] for r in rows if r['outcome']==name)
        want=100*SD['competitive']*float(z@y[:,ynames.index(name)])/zz
        if not np.isclose(total,want,atol=1e-10,rtol=1e-8):raise RuntimeError('Bin slope contribution identity failed')
    return rows

def compute(d,kind,cohort,environment=False,edges=None,reproduce=False,numerical_callback=None):
    n=len(d['row_id']);base=dict(kind=kind,cohort=cohort,n=n,row_set_sha256=design.row_digest(d['row_id']),
        sample='competitive_and_environment_supported' if environment else 'competitive_supported',
        clustering='shared_account_OR_date_CR0',generated_scores_treated_as_fixed=True,exploratory_after_previous_results=True,
        nominal_interim_intervals=True,causal_identification_certified=False)
    empty=dict(estimates=[],balance=[],bins=[],support=[],bridge=[],joint_balance=[],accounting=[],numerics=[])
    if n<2000:
        empty['estimates']=[dict(base,supported=False,reason='FEWER_THAN_2000_ROWS')];return empty
    if not oldmodels.support_mask(d).all():raise RuntimeError('Unsupported competitive rows in common-sample model')
    y,ynames=outcome_matrix(d,kind)
    xs,names,traits,tnames,groups,missing=stats.controls(d,True)
    if any(missing.values()):raise RuntimeError('Missing frozen control')
    for name,v in [('competitive_expected_rate',d['comp_expected_7d']),('log_competitive_decisions',np.log1p(d['comp_n_7d'])),('log_competitive_counterparts',np.log1p(d['comp_counterparts_7d']))]:
        xs.append((v-v.mean())/max(float(v.std()),1e-12));names.append(name)
    baseline_k=len(names)
    if environment:
        if not d['environment_supported'].all():raise RuntimeError('Environment support differs within a fit')
        for name in ENV_NAMES:
            v=np.asarray(d[name],float)
            if not np.isfinite(v).all():raise RuntimeError('Missing environment control')
            xs.append((v-v.mean())/max(float(v.std()),1e-12));names.append(name)
    # These seven recipient traits are NOT the new included opponent controls.
    if not set(RECENT)<=set(tnames):raise RuntimeError('Frozen balance trait names changed')
    chosen=[tnames.index(k) for k in RECENT]
    ts=[traits[k] for k in chosen];del traits
    k=len(names)
    matrix=np.column_stack(xs+[d['adjusted_7d'],d['comp_adjusted_7d']]+[y[:,j] for j in range(y.shape[1])]+ts)
    if not np.isfinite(matrix).all():raise RuntimeError('Nonfinite model data')
    absorbed,numerical=env_numerics.absorb(matrix,groups,
        column_names=names+['pooled_score','competitive_score']+ynames+RECENT,publish=numerical_callback)
    iterations=numerical['iterations'];del matrix,xs,ts
    codes=stats.cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]);meat=lambda x:stats.stats.shared_meat(x,codes,True)
    levels=[('XC',list(range(baseline_k)))]
    if environment:
        levels += [('XC_volume',list(range(baseline_k+1))),('XC_volume_own',list(range(baseline_k+2))),
            ('XC_volume_chooser',list(range(baseline_k+1))+[baseline_k+2]),('XC_both_rates',list(range(k)))]
    rows=[];balances=[];binrows=[];support=[];joints=[]
    for level,indices in levels:
        residual,rank=oldmodels.residualize(absorbed,k,indices)
        zs=residual[:,:2];ys=residual[:,2:2+len(ynames)];bs=residual[:,2+len(ynames):]
        if not np.isfinite(residual).all():raise RuntimeError('Nonfinite residual after continuous-control projection')
        meta=dict(base,control_level=level,controls=[names[j] for j in indices],continuous_control_rank=rank,absorb_iterations=iterations,
            absorption_solver=env_numerics.SOLVER,absorption_orthogonality_verified=True)
        for zcol,tag in enumerate(('pooled','competitive')):
            z=zs[:,zcol];sd=SD[tag];native=float(np.sqrt(np.mean(z*z)))
            support.append(dict(meta,instrument=tag,native_residual_score_SD=native,fixed_reference_SD=sd,
                raw_score_SD=float(np.std(d['adjusted_7d' if tag=='pooled' else 'comp_adjusted_7d'])),
                residual_variance_share_above_frozen_ordinary_q95=float(z[d['comp_adjusted_7d']>edges[4]]@z[d['comp_adjusted_7d']>edges[4]])/float(z@z) if edges is not None and z@z else None))
            for j,name in enumerate(ynames):
                events=int(y[:,j].sum());fit=stats.stats.ols(ys[:,j],z,meat)
                if min(events,n-events)<10:fit=dict({k:v for k,v in fit.items() if k=='coefficient'},supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
                rows.append(dict(meta,instrument=tag,outcome=name,estimator='first_stage' if name=='received' else 'reduced_form',
                    events=events,outcome_mean_pp=100*events/n,reference_score_SD=sd,native_residual_score_SD=native,**stats.stats.effect_row(fit,100*sd)))
            if kind=='iv':
                iv=stats.iv_result(ys[:,ynames.index('y')],ys[:,ynames.index('received')],z,meat)
                out={key:val for key,val in iv.items() if key not in ('first_stage','reduced_form')}
                for key in ('iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high'):
                    if key in iv:out[key+'_pp']=100*iv[key]
                out['first_stage_F']=iv.get('first_stage',{}).get('wald_F_one_df')
                rows.append(dict(meta,instrument=tag,outcome='y',estimator='2SLS',**out))
            if level in ('XC','XC_both_rates'):
                local=[]
                for j,name in enumerate(RECENT):
                    fit=stats.stats.ols(bs[:,j],z,meat)
                    # A trait is standardized BEFORE projection. Fixed instrument SD makes before/after comparable.
                    row=dict(meta,instrument=tag,trait=name,units='trait SD per fixed reference score SD',reference_score_SD=sd,**fit)
                    for key in ('coefficient','standard_error','ci_low','ci_high'):
                        if key in fit:row[key+'_traitSD']=sd*fit[key]
                    local.append(row)
                stats.stats.holm(local,out='p_Holm_7_traits');balances+=local
                joints.append(dict(meta,instrument=tag,**stats.stats.joint(bs,z/sd,meat)))
        if kind=='entry' and level in ('XC','XC_both_rates') and edges is not None:
            binrows+=bin_diagnostics(d,zs[:,1],ys,ynames,edges,meta,codes)
        # Algebraic role partition must hold after every projection too.
        if kind=='entry':
            for tag in ('pooled','competitive'):
                fit={r['outcome']:r for r in rows if r['instrument']==tag and r['control_level']==level}
                if any(fit[v].get('coefficient') is None for v in ['active_timeout','recipient_disconnect_main']+ROLE_OUTS):continue
                want=sum(fit[v]['coefficient'] for v in ['recipient_disconnect_main']+ROLE_OUTS)
                if not np.isclose(want,fit['active_timeout']['coefficient'],atol=1e-10,rtol=1e-8):raise RuntimeError('Adjusted role partition identity failed')
    bridges=[]
    if reproduce:
        targets=io.load(PACKAGE/'evidence/entry_estimates.json')
        for target in targets:
            if target.get('cohort')!=cohort or target.get('sample')!='competitive_supported' or target.get('control_level')!='XC' or target.get('outcome') not in ENTRY_COLUMNS:continue
            got=next(r for r in rows if r['instrument']==target['instrument'] and r['control_level']=='XC' and r['outcome']==target['outcome'])
            for key in ('n','events','row_set_sha256','supported'):
                if got.get(key)!=target.get(key):raise RuntimeError('Completed competitive entry bridge differs: '+key)
            for key in ('coefficient_pp','standard_error_pp'):
                if target.get(key) is not None and not np.isclose(got.get(key,np.nan),target[key],rtol=2e-7,atol=2e-9):raise RuntimeError('Completed entry numerical bridge differs: '+key)
            bridges.append(dict(cohort=cohort,instrument=target['instrument'],outcome=target['outcome'],reproduced=True))
        if len(bridges)!=10:raise RuntimeError('Expected ten completed XC entry bridges')
    return dict(estimates=rows,balance=balances,bins=binrows,support=support,bridge=bridges,joint_balance=joints,accounting=[],numerics=[dict(base,**numerical)])

def model_job(job):
    threads_one()
    def build(tmp):
        names=MODEL_COLUMNS+COMP_COLUMNS
        if job['kind']=='entry':names+=['status','previous_frame','opponent_disconnect_main','timeout_role_unclassified']
        else:names=[v for v in names if v not in ENTRY_COLUMNS]+['y','reached']+(['received'] if job['kind']=='iv' else [])
        if job['environment']:names+=ENV_NAMES+['environment_supported','games','own','chooser']
        d=arrays(io.read(job['input'],list(dict.fromkeys(names))))
        use=oldmodels.support_mask(d);score_n=int(use.sum())
        if job['environment']:use &= d['environment_supported'].astype(bool)
        total=len(use);d=selected(d,use)
        def numerical_callback(audit):
            audit=dict(audit,kind=job['kind'],cohort=job['cohort'],environment=job['environment'])
            if job.get('numerical_audit'):io.js(Path(job['numerical_audit']),audit)
        result=compute(d,job['kind'],job['cohort'],job['environment'],job.get('edges'),job.get('reproduce',False),numerical_callback)
        status_info=env_status.inspect(d,job['cohort'])[1] if job['kind']=='entry' else None
        if status_info is not None:io.js(tmp/'model_status_coverage.json',status_info)
        result['accounting']=[dict(status_coverage=status_info,kind=job['kind'],cohort=job['cohort'],environment=job['environment'],input_rows=total,competitive_supported=score_n,
            common_model_rows=int(use.sum()),excluded_for_environment=score_n-int(use.sum()),no_replacement_rows=True)]
        io.js(tmp/'result.json',result);return dict(rows=len(d['row_id']))
    return stage(job,build,[job['input']])
