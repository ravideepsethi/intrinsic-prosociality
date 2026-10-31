from util import *
import numpy as np,pandas as pd

def covariance_comparison(actual,expected,names,rtol=2e-7,atol=2e-8):
    """Compare covariance entries on their SE-product scale, including zeros.

    Covariances depend on both coefficient units. Relative error in an entry
    itself is ill-conditioned when that covariance is near zero, even if the
    marginal variances are large. Use the archived SE_i * SE_j as the relative
    scale. Diagonals, reported SEs and every planned contrast retain their
    existing checks; a changed correlation must still fail this full-matrix gate.
    """
    a=np.asarray(actual,dtype=float);b=np.asarray(expected,dtype=float)
    require(a.shape==b.shape and a.ndim==2 and a.shape[0]==a.shape[1]==len(names),
            'Reference covariance dimensions differ')
    require(np.isfinite(a).all() and np.isfinite(b).all(),'Nonfinite reference covariance')
    require((np.diag(a)>=-atol).all() and (np.diag(b)>=-atol).all(),'Negative reference variance')
    se=np.sqrt(np.maximum(np.diag(b),0.))
    tolerance=atol+rtol*np.outer(se,se)
    require((np.abs(a-a.T)<=tolerance).all() and (np.abs(b-b.T)<=tolerance).all(),
            'Asymmetric reference covariance')
    delta=np.abs(a-b);ratio=delta/tolerance
    i,j=np.unravel_index(int(np.argmax(ratio)),ratio.shape)
    return dict(max_absolute_difference=float(np.max(delta)),
        passed=bool((ratio<=1.).all()),
        elementwise_relative_check_passed=bool(np.allclose(a,b,rtol=rtol,atol=atol)),
        comparison='abs(delta_ij) <= 2e-8 + 2e-7 * archived_SE_i * archived_SE_j',
        max_tolerance_ratio=float(ratio[i,j]),worst_row_term=names[i],worst_column_term=names[j],
        worst_entry_difference=float(delta[i,j]),worst_entry_tolerance=float(tolerance[i,j]))

def compare_reference(actual,expected,output):
    """Fail closed if the cached source and unchanged mathematics do not reproduce."""
    checks=[]
    for filename,keys,values in [
        ('coefficients.csv',['model','term'],['estimate','se']),
        ('planned_contrasts.csv',['model','contrast'],['estimate','se','holm_p']),
        ('adjusted_profiles.csv',['model','point'],['estimate','se']),
        ('model_samples.csv',['model'],['N','choosers','grant_or_blunder_rate','singletons_retained','never_outcome_accounts','rank','columns']),
        ('model_row_support.csv',['model'],[]),
    ]:
        a=pd.read_csv(Path(actual)/filename);b=pd.read_csv(Path(expected)/filename)
        require(not a.duplicated(keys).any() and not b.duplicated(keys).any(),'Ambiguous reference table keys')
        z=a.merge(b,on=keys,suffixes=('_new','_old'),how='outer',indicator=True,validate='one_to_one')
        require((z._merge=='both').all() and len(a)==len(b),'Reference row inventory differs: '+filename)
        if 'status_new' in z:require((z.status_new==z.status_old).all(),'Reference estimability differs: '+filename)
        if 'row_set_sha256_new' in z:require((z.row_set_sha256_new==z.row_set_sha256_old).all(),'Frozen reference sample differs')
        for name in values:
            x=z[name+'_new'].to_numpy(float);y=z[name+'_old'].to_numpy(float)
            ok=np.isclose(x,y,rtol=2e-7,atol=2e-8,equal_nan=True)
            finite=np.isfinite(x)&np.isfinite(y)
            checks.append(dict(table=filename,metric=name,rows=len(z),max_absolute_difference=float(np.max(np.abs(x[finite]-y[finite]))) if finite.any() else 0.,passed=bool(ok.all())))
    with np.load(Path(actual)/'model_covariances.npz',allow_pickle=False) as a,np.load(Path(expected)/'model_covariances.npz',allow_pickle=False) as b:
        require(set(a.files)==set(b.files),'Reference covariance inventory differs')
        order=read(Path(expected)/'coefficient_order.json')
        require(read(Path(actual)/'coefficient_order.json')==order,'Reference covariance column order differs')
        from design_support import exact_zero_indices,canonical_covariance_comparison
        support_path=Path(actual)/'within_design_support.json'
        supports={r['model']:r for r in read(support_path)} if support_path.is_file() else {}
        rows=pd.read_csv(Path(actual)/'model_row_support.csv').set_index('model')
        new_coefficients=pd.read_csv(Path(actual)/'coefficients.csv')
        old_coefficients=pd.read_csv(Path(expected)/'coefficients.csv')
        for name in a.files:
            result=covariance_comparison(a[name],b[name],order[name])
            if name in supports:
                new_status=new_coefficients[new_coefficients.model==name].set_index('term').status.to_dict()
                old_status=old_coefficients[old_coefficients.model==name].set_index('term').status.to_dict()
                zeros=exact_zero_indices(supports[name],order[name],rows.loc[name,'row_set_sha256'],new_status,old_status)
                result=canonical_covariance_comparison(a[name],b[name],order[name],zeros,covariance_comparison)
            checks.append(dict(table='model_covariances.npz',metric=name,rows=a[name].shape[0],
                **result))
    table(output,checks)
    require(all(x['passed'] for x in checks),'Archived responsibility estimates did not reproduce; inspect REFERENCE_REPRODUCTION.csv')
    return dict(passed=True,models=53,metrics=len(checks),max_absolute_difference=max(x['max_absolute_difference'] for x in checks))

def manuscript_tables(report,reference):
    contrasts=pd.read_csv(report/'planned_contrasts.csv');samples=pd.read_csv(report/'model_samples.csv')
    models=set(samples.model);require(len(models)==53,'Incomplete responsibility report')
    # Compact extraction; the full original coefficient/contrast inventory is also returned.
    wanted=[
        ('curve_late_common_baseline','300_to_500_cp','A_profile','Same trajectory-supported rows, baseline'),
        ('curve_late_common_proxies','300_to_500_cp','A_profile','Same rows, trajectory/clock/material proxies'),
        ('curve_late_common_proxies_rating','300_to_500_cp','A_profile','Same rows, proxies and rating-state controls'),
        ('blunder200_competitive','blunder','B_own_last_move','Own-move loss at least 200 cp, competitive'),
        ('blunder200_losing','blunder','B_own_last_move','Own-move loss at least 200 cp, clearly worse'),
        ('proxy_late_competitive_own','own_loss100','B_own_last_move','Continuous own-move loss, competitive'),
        ('proxy_late_losing_own','own_loss100','B_own_last_move','Continuous own-move loss, clearly worse'),
        ('cross_region_baseline','competitive','C_region','Competitive minus clearly worse, common baseline'),
        ('cross_region_proxies','competitive','C_region','Competitive minus clearly worse, common proxies'),
    ]
    rows=[]
    for model,contrast,panel,label in wanted:
        x=contrasts[(contrasts.model==model)&(contrasts.contrast==contrast)]
        require(len(x)==1,'Missing paper-facing responsibility contrast')
        rows.append(dict(panel=panel,label=label,**x.iloc[0].to_dict()))
    result=pd.DataFrame(rows).merge(samples[['model','N','choosers']],on='model',validate='many_to_one')
    table(report/'tab_app_responsibility.csv',result)
    old=pd.read_csv(reference/'planned_contrasts.csv')
    compare=result.merge(old[['model','contrast','estimate','se']],on=['model','contrast'],suffixes=('_material','_previous'),validate='one_to_one')
    compare['estimate_change']=compare.estimate_material-compare.estimate_previous
    compare['comparison']='Descriptive change across different frames; no paired difference SE estimated'
    table(report/'RESPONSIBILITY_BEFORE_AFTER.csv',compare)
    selected=contrasts[contrasts.model.isin(['asymmetry_late','asymmetry_all'])].copy()
    table(report/'responsibility_region_interactions.csv',selected)
    save(report/'SPECIFICATION.json',dict(models=53,
        frozen_sample='Original 20,000 chooser accounts, complete original opportunity histories, intersected with corrected material main frame; no replacements.',
        engine_features='Existing A2_SCORE_REPAIR_V101 projected features; no engine evaluations or API calls.',
        outcome='100 times new grant, except explicitly named gap_predicts_blunder threshold outcomes.',
        comparisons='Every specification, cutoff, knot, control, fixed effect, missingness indicator and covariance rule comes from the frozen A2 source.',
        standardization='Original joint chooser-cluster influence formula includes sampling variation in composition and baseline.',
        inference='Original chooser-cluster G/(G-1) covariance; full covariances and model state supplied; unchanged planned Holm families.',
        excluded_history_models='Prior 90-day disconnection rate, prepanel rate, no-prior-disconnection subset were not in the archived 53 models and are not added.',
        historical_chooser_losses='Retained as non-grants, following reviewed material input policy.',
        whole_paper_rerun_complete=False))
    return dict(models=53,paper_table_rows=len(result),interaction_rows=len(selected))
