"""Compare aggregate tables by explicit keys; never silently align by row order."""
from engine import *

KEYS=('model','specification','estimand','analysis','column','term','variable','contrast','outcome','sample','family','test','label','population','group','position','stage','speed','month','month_code','speed_code','eval_bin','bin','payoff_class','fairness_bin','fairness','threshold','cutoff','bandwidth','min_total_fair_opportunities','split','split_type','half','control_slot','category','gap_category','category_kind','region','exposure_cell_code','account_grant_percent','session_position','acquisition_role')
EXTRA_KEYS=('bin_width','bin_number','clock_bin','split_design','first_half_rate_pct_bin','second_half_rate_pct_bin','prior_kind_type','chooser_rating_tier','first_half_any_kind','window','window_half_width','win_premium_control','sample_marker','dimension','subgroup','fair_threshold_cp','clearly_worse_threshold_cp','cell','benchmark','payoff_sign','row_bin_code','column_bin_code','payoff_bin_code','r_G','side','source_month','board_bin','tier','eval50','material','diagnostic_group','minimum_opportunities_each_state','dose_bin','minimum_opportunities_each_price_side','adjustment','field')
KEYS=KEYS+EXTRA_KEYS+('state','training','cohort','comparison','fold','RD_class','gap','model_a','model_b','own_rd_bin','opponent_rd_bin','model_id','eval_band','year_half','gap_bin50','gap_bin','score_bin','gap_bucket','axis','term1','term2')
KEYS=KEYS+('replicate','first_group','second_group','law','rule','partition','meeting','under_days','tenure','age_source','competitive','ever_competitive_kind_year1','minimum_each_year','minimum_each_state','opportunity_min_age')
KEYS=KEYS+('point','cp','after_ply10','trajectory_ok','ever_fair','ever_losing')
MEASURES=('estimate','coefficient','coefficient_pp','coefficient_percentage_points','estimate_pp','iv_coefficient_pp','beta','effect','difference','correlation','gap_pp','competitive_rate_pct','worse_rate_pct','overall_binary_rate_pct','balanced_50_50_rate_pct','risk_ratio','absolute_gap_difference_pp','ratio_of_risk_ratios')
SE=('se','se_pp','standard_error','standard_error_pp','standard_error_percentage_points','iv_standard_error_pp','std_error')
PAIRS={'beta_plus_pp_per_rating_point':'se_beta_plus','beta_minus_pp_per_rating_point':'se_beta_minus',
 'slope_asymmetry_beta_plus_plus_beta_minus':'se_slope_asymmetry','threshold_jump_pp':'se_threshold_jump_pp',
 'coefficient_favorable_pp':'se_favorable_pp','coefficient_win_premium':'se_win_premium','coef_pp':'se_pp','rate_pct':'se_pct','chooser_equal_diff_pp':'se_pp',
 'far_weaker_minus_equal_pp':'far_weaker_minus_equal_se_pp','far_stronger_minus_equal_pp':'far_stronger_minus_equal_se_pp',
 'far_stronger_minus_far_weaker_pp':'far_stronger_minus_far_weaker_se_pp',
 'kind_rate_raw_pct':'raw_binomial_se_pp','kind_rate_residualized_pct':'residualized_se_mean_pp',
 'adjusted_rate_pct':'clustered_se_pp','fitted_rate_pct':'clustered_se_pp','kind_rate_pct':'binomial_se_pp'}
MEASURES=MEASURES+tuple(PAIRS)+('rate_percent','patron_rate_pct','pearson_unweighted','spearman_unweighted','pearson_weighted_total_opportunities','pearson_weighted_harmonic_half_opportunities')
MEASURES=MEASURES+('harmonic_correlation','raw_gap_pp','fe_gap_pp','full_gap_pp','excess_pp','excess_percentage_points','difference_in_excess_pp')
PAIRS.update({'fe_gap_pp':'fe_se_pp','full_gap_pp':'full_se_pp'})
PAIRS.update({'coefficient_percentage_points':'standard_error_percentage_points',
              'iv_coefficient_pp':'iv_standard_error_pp'})
MEASURES=MEASURES+('grant_rate_pp','P2_pooled_rate_pp','P2_equal_account_mean_rate_pp',
 'P2_rate_pp','P2_equal_account_rate_pp','p2_share_percent','correlation_equal_account',
 'correlation_harmonic_opportunities','pearson_equal_account','pearson_total_comp_opportunities_weighted',
 'corr_C1_C2','corr_L1_L2','corr_C1_L2','corr_L1_C2','corr_selectivity_rate_difference',
 'corr_selectivity_harmonic','corr_overall_two_state_rate','corr_overall_two_state_rate_harmonic')

FORBIDDEN={'username','username_norm','chooser_username_norm','disconnected_username_norm','chooser_user_id','disconnected_user_id','recipient_user_id','game_id','exposure_game_id','cohort_row_id','matched_kind_chooser_id','query_index','chooser','recipient','opponent','user_id','account_id'}

def compare_frames(a,b,family,file):
    if family=='first_repeat' and file=='report/pair_rates.csv':
        # The original UNION ALL exports clearly_worse twice: once as a
        # named scope and once as the same fairness bin. Compare one canonical
        # aggregate per scope/meeting, retaining and comparing multiplicity.
        normalized=[]
        for frame in (a,b):
            counts=frame.groupby(['scope','meeting'],dropna=False).size()
            canonical=frame.drop_duplicates().copy()
            require(not canonical.duplicated(['scope','meeting']).any(),
                    'Conflicting first/repeat duplicate aggregates')
            canonical['_producer_row_multiplicity']=[int(counts.loc[(r.scope,r.meeting)]) for r in canonical.itertuples()]
            normalized.append(canonical)
        a,b=normalized
    # Activity uses scope as an actual sampling dimension, whereas mechanism
    # producers sometimes use it only for explanatory prose.
    keys=[x for x in KEYS if x in a.columns and x in b.columns]
    if family=='state_persistence':
        from persistence import STATE_KEYS
        require(Path(file).name in STATE_KEYS,'Unknown original persistence output: '+file)
        keys=list(STATE_KEYS[Path(file).name])
    if family=='merit' and file.endswith('monthly_validation.csv'):
        keys=['month']  # competitive is a count here, not a sample label.
    if family=='temporal' and 'horizon_hours' in a.columns and 'horizon_hours' in b.columns:keys.append('horizon_hours')
    if family in ('activity','first_repeat') and 'scope' in a.columns and 'scope' in b.columns:keys.append('scope')
    if family=='arena' and 'source' in a.columns and 'source' in b.columns:keys.append('source')
    if family=='patron_remaining' and file in ('report/five_bin_raw.csv','report/five_bin_support.csv'):
        keys.append('minimum_opportunities_in_each_of_five_bins')
    if family=='tenure' and file=='report/PROFILE_CACHE_COVERAGE.csv':
        keys += ['returned','disabled']
    # The mechanism quantile vector is a measured output, never a row identity.
    if family=='mechanism' and 'ki_quantiles' in a.columns and 'ki_quantiles' in b.columns:
        probabilities=(.01,.1,.25,.5,.75,.9,.95,.99,.999)
        frames=[]
        for frame in (a,b):
            frame=frame.copy();values=[]
            for x in frame.pop('ki_quantiles'):
                value=str(x).strip();require(value.startswith('[') and value.endswith(']'),'Unexpected mechanism quantile representation')
                parsed=np.fromstring(value[1:-1],sep=' ')
                require(len(parsed)==len(probabilities) and np.isfinite(parsed).all(),'Incomplete mechanism quantile vector')
                values.append(parsed)
            for j,p in enumerate(probabilities):frame['ki_quantile_'+str(p)]=[v[j] for v in values]
            frames.append(frame)
        a,b=frames
    # Additional string-valued dimensions are useful only if they are not
    # mutable diagnostics or numerical values encoded as strings.
    for x in a.columns.intersection(b.columns):
        if 'sha256' in x or 'fingerprint' in x or x.endswith(('_path','_file')):continue
        if x in keys or x.lower() in ('status','interpretation','note','notes','source','units','meaning','frame','scope','interval_status','drop_reason','absorption_method','normalization','horizontal_axis','description') or x.endswith('_status'):continue
        if pd.api.types.is_string_dtype(a[x].dtype) and pd.api.types.is_string_dtype(b[x].dtype):
            if pd.to_numeric(a[x],errors='coerce').notna().any() or pd.to_numeric(b[x],errors='coerce').notna().any():continue
            keys.append(x)
    if not keys:
        if len(a)==len(b)==1:a=a.assign(_singleton='one');b=b.assign(_singleton='one');keys=['_singleton']
        else:return [],{'family':family,'file':file,'status':'NO_UNIQUE_COMPARISON_KEY','included_rows':len(a),'excluded_rows':len(b)}
    a=a.copy();b=b.copy()
    # A coefficient label is a dimension only in this weight-definition table.
    if family=='r11' and file.endswith('gap_contrast_weights.csv') and 'coefficient' not in keys:keys.append('coefficient')
    for k in keys:a[k]=a[k].astype('string').fillna('<missing>');b[k]=b[k].astype('string').fillna('<missing>')
    if a.duplicated(keys).any() or b.duplicated(keys).any():
        return [],{'family':family,'file':file,'status':'DUPLICATE_COMPARISON_KEYS','included_rows':len(a),'excluded_rows':len(b),'keys':'|'.join(keys)}
    m=a.merge(b,on=keys,how='outer',suffixes=('_included','_excluded'),indicator=True,validate='one_to_one')
    rows=[];cols=[x for x in a.columns.intersection(b.columns) if x not in keys]
    for _,r in m.iterrows():
        key=json.dumps({k:str(r[k]) for k in keys},sort_keys=True)
        if r['_merge']!='both':
            rows.append(dict(family=family,file=file,key=key,metric='ROW_MEMBERSHIP',status=str(r['_merge'])));continue
        for col in cols:
            x=pd.to_numeric(r[col+'_included'],errors='coerce');y=pd.to_numeric(r[col+'_excluded'],errors='coerce')
            if (col in ('status','estimable','identified','both_estimable') or col.endswith('_status')) and str(r[col+'_included'])!=str(r[col+'_excluded']):
                rows.append(dict(family=family,file=file,key=key,metric=col,status='IDENTIFICATION_OR_STATUS_CHANGED',included_text=str(r[col+'_included']),excluded_text=str(r[col+'_excluded'])))
            if not (np.isscalar(x) and np.isscalar(y)) or not(np.isfinite(x) and np.isfinite(y)):continue
            row=dict(family=family,file=file,key=key,metric=col,status='MATCHED',included=float(x),excluded=float(y),change=float(y-x))
            if col in MEASURES:
                candidates=[col.replace('_pct','_se_pct'),col.replace('_pp','_se_pp')] if col.endswith(('_pct','_pp')) else []
                if col=='absolute_gap_difference_pp':candidates=['absolute_difference_se_pp']
                if col in PAIRS:candidates=[PAIRS[col]]
                if family=='patron_remaining' and file=='report/five_bin_raw.csv' and col=='gap_pp':
                    candidates=['unpooled_se_pp']
                se=next((s for s in candidates if s!=col and s in cols),None)
                if se is None and col not in PAIRS and col not in ('risk_ratio','ratio_of_risk_ratios'):se=next((s for s in SE if s in cols),None)
                if se:
                    sx=pd.to_numeric(r[se+'_included'],errors='coerce');sy=pd.to_numeric(r[se+'_excluded'],errors='coerce')
                    row.update(included_se=clean(sx),excluded_se=clean(sy))
                    if np.isfinite(sx) and sx>0:row['absolute_change_in_included_se_units']=abs(y-x)/sx
                    if np.isfinite(sx) and np.isfinite(sy):row['crosses_approx_95pct_zero_boundary']=(abs(x)>1.96*sx)!=(abs(y)>1.96*sy)
                row['sign_changed']=(x*y<0)
            rows.append(row)
    return rows,{'family':family,'file':file,'status':'COMPARED','included_rows':len(a),'excluded_rows':len(b),'matched_rows':int((m['_merge']=='both').sum()),'included_only':int((m['_merge']=='left_only').sum()),'excluded_only':int((m['_merge']=='right_only').sum()),'keys':'|'.join(keys)}

def export_tables(run,variant,stage):
    source=run/'PRIVATE/results'/variant/stage;target=run/'report/tables'/variant/stage
    allowed=[]
    # Reviewed aggregate products emitted at the root by these two original producers.
    root_csv={
      'rating_gap':{'mechanical_validation.csv','rating_gap_broad_rates.csv','rating_gap_u_metrics.csv','rating_gap_curves.csv','expected_score_curves.csv','krd_descriptives.csv','fe_model_coefficients.csv','fe_model_receipts.csv','fe_model_band_contrasts.csv'},
      'nonparametric':set(),
    }
    if stage=='nonparametric':
        names=('00_descriptive_rating_gap_curves','common_support_chooser_equal_differences','model_plan','fe_nonparametric_coefficients','fe_nonparametric_curves','fe_nonparametric_receipts')
        for name in names:
            p=source/(name+'.parquet')
            require(p.is_file(),'Missing nonparametric public aggregate: '+name)
            frame=pd.read_parquet(p)
            require(not FORBIDDEN.intersection(frame.columns),'Private identifiers in aggregate export: '+name)
            # Execution paths and per-process diagnostic strings are not analysis data.
            frame=frame.drop(columns=[c for c in frame.columns if c.endswith(('_path','_file','_parquet')) or c in ('worker_pid','worker_threads','worker_memory_limit')],errors='ignore')
            table(target/name,frame);allowed.append(target/(name+'.csv'))
    for p in source.rglob('*.csv'):
        rel=p.relative_to(source)
        if not set(rel.parts)&{'report','tables','figure_data'} and not (len(rel.parts)==1 and rel.name in root_csv.get(stage,set())):continue
        if any('private' in x.lower() or x in ('scratch','spill') for x in rel.parts):continue
        try:frame=pd.read_csv(p)
        except pd.errors.EmptyDataError:continue
        require(not FORBIDDEN.intersection(frame.columns),'Private identifiers in aggregate export: '+str(rel))
        dst=target/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst);allowed.append(dst)
    return allowed

def compare_all(run,stages):
    rows=[];inventory=[]
    for stage in stages:
        aa=run/'report/tables/included'/stage;bb=run/'report/tables/excluded'/stage
        files=sorted(set(str(p.relative_to(aa)) for p in aa.rglob('*.csv'))|set(str(p.relative_to(bb)) for p in bb.rglob('*.csv')))
        for f in files:
            if not (aa/f).exists() or not (bb/f).exists():
                inventory.append(dict(family=stage,file=f,status='MISSING_PAIRED_TABLE'));continue
            out,audit=compare_frames(pd.read_csv(aa/f),pd.read_csv(bb/f),stage,f);rows.extend(out);inventory.append(audit)
    if rows:pd.DataFrame(rows).to_parquet(run/'report/before_after.parquet',index=False,compression='zstd')
    if inventory:table(run/'report/comparison_coverage',inventory)
    points=[r for r in rows if r['metric'] in MEASURES and r['status']=='MATCHED']
    summary={'paired_metrics':len(rows),'point_estimates_compared':len(points),'tables_requiring_alignment_review':sum(r['status']!='COMPARED' for r in inventory),'tables_with_membership_changes':sum(bool(r.get('included_only',0) or r.get('excluded_only',0)) for r in inventory),'status_changes':sum(r['status']=='IDENTIFICATION_OR_STATUS_CHANGED' for r in rows),
        'sign_changes':sum(bool(r.get('sign_changed')) for r in points),'approx_95pct_boundary_changes':sum(bool(r.get('crosses_approx_95pct_zero_boundary')) for r in points),
        'maximum_absolute_change_in_included_se_units':max((r['absolute_change_in_included_se_units'] for r in points if 'absolute_change_in_included_se_units' in r),default=None),
        'substantive_equivalence':'NOT_AUTOMATICALLY_DETERMINED','inference':'These are paired estimates, not a test treating the overlapping samples as independent. No nonsignificance/equivalence shortcut.'}
    write(run/'report/COMPARISON_SUMMARY.json',summary);return summary
