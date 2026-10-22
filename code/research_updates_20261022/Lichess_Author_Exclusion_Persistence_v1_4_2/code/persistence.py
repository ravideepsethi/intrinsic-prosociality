"""Recovered original Test F v1.0.2 producer, on authenticated paired panels."""
from engine import *
sys.path.insert(0,str(ROOT/'vendor/original_f_v102/src'))
import run_f as producer

STATE_KEYS={
 'tabF0_original_competitive_reconciliation.csv':[],
 'tabF1_opportunities_by_year_state.csv':['period','region'],
 'tabF1_region_exposure_support.csv':['C1_exposed','L1_exposed','C2_exposed','L2_exposed'],
 'tabF2_retention.csv':['p1_grp'],
 'tabF2_transition_4x4.csv':['sample','p1_group','p2_group'],
 'tabF3_P2_rates_by_P1_group.csv':['sample','stage','P1_group','P2_region'],
 'tabF4_cross_year_correlations.csv':['sample','min_opportunities_each_year_and_state','period1_state','period2_state'],
 'tabF4_selectivity_persistence.csv':['threshold'],
 'tabF5_collinearity_audit.csv':['model','P2_outcome','dropped_covariate'],
 'tabF5_cross_prediction.csv':['model','P2_outcome','estimand'],
 'tabF6_threshold_sensitivity.csv':['threshold'],
 'tabF6_transition_thresholds.csv':['sample','p1_group','p2_group'],
 'tabF7_noncompetitive_P2_rates.csv':['P1_group','P2_region'],
 'tabF7_noncompetitive_and_stage_sensitivity.csv':['sample','p1_group','p2_group'],
 'tabF7_noncompetitive_correlations.csv':['sample','min_opportunities_each_year_and_state','period1_state','period2_state'],
 'tabF7_stage_correlations_after10.csv':['sample','min_opportunities_each_year_and_state','period1_state','period2_state'],
 'tabF7_stage_transition_after10.csv':['sample','p1_group','p2_group'],
}


def reproduction(actual,baseline):
    """Compare all seventeen original CSVs by their original dimensions."""
    checks=[]
    for name,keys in STATE_KEYS.items():
        a=pd.read_csv(baseline/name);b=pd.read_csv(actual/name)
        require(list(a.columns)==list(b.columns),'Original F columns changed: '+name)
        if keys:
            require(not a.duplicated(keys).any() and not b.duplicated(keys).any(),'Duplicate original F keys')
            a=a.set_index(keys).sort_index();b=b.set_index(keys).sort_index()
        require(a.index.equals(b.index),'Original F rows changed: '+name)
        for col in a.columns:
            x=a[col];y=b[col]
            if col=='weighted_relative_residual':
                ok=bool(np.isfinite(y).all() and (y>=0).all() and (y<1e-9).all())
            elif pd.api.types.is_bool_dtype(x.dtype) or pd.api.types.is_integer_dtype(x.dtype):
                ok=x.equals(y)
            elif pd.api.types.is_numeric_dtype(x.dtype):
                ok=bool(np.allclose(x,y,rtol=2e-7,atol=5e-8,equal_nan=True))
            else:ok=x.fillna('<missing>').equals(y.fillna('<missing>'))
            checks.append(dict(file=name,column=col,status='REPRODUCED' if ok else 'MISMATCH'))
    return checks


def run_stage(auth,variant,out,workers,memory):
    private=out/'PRIVATE';public=out/'report'
    private.mkdir(parents=True,exist_ok=True);public.mkdir(parents=True,exist_ok=True)
    counts=auth['census']
    # Only the sample-size assertions change between variants. All original
    # aggregation, estimation, uncertainty and cohort functions are unchanged.
    producer.PAPER=dict(rows=int(counts['opportunities']),grants=int(counts['grants']),
        comp_n=int(counts['competitive']),comp_y=int(counts['competitive_grants']),
        lost_n=int(counts['clearly_worse']),lost_y=int(counts['clearly_worse_grants']))
    paths=[r['path'] for r in auth['month_records']]
    c=db(private/'spill',max(2,memory-2),workers)
    try:
        source=scan(paths);pair=names_pair(paths[0])
        n,missing,hits=c.execute('SELECT count(*),count(*) FILTER(WHERE '+
            ' OR '.join('s.'+ident(x)+' IS NULL' for x in pair)+'),count(*) FILTER(WHERE '+author_sql(pair)+') FROM '+source+' s').fetchone()
        require(n==counts['opportunities'] and missing==0,'Persistence identity/count audit failed')
        require(hits==(42 if variant=='included' else 0),'Persistence author-game inventory changed')
        matched=producer.choose_columns(c,source)
        checks=producer.preflight(c)
        producer.build_account_panel(c,private)
        producer.year_state_summary(c,public)
        rec=producer.f0_published_reconciliation(c,public)
        producer.retention(c,public)
        primary=producer.sample_account_panel(c,4)
        require(len(primary)>0,'Empty original persistence cohort')
        producer.save_csv(public/'tabF2_transition_4x4.csv',pd.DataFrame(producer.transition_rows(primary,'primary_balanced_C_L_4')))
        producer.save_csv(public/'tabF3_P2_rates_by_P1_group.csv',pd.DataFrame(producer.p2_rates(primary,'primary_balanced_C_L_4')))
        producer.figure_transition(primary,public)
        producer.threshold_table(c,public)
        producer.cross_predict(primary,public)
        sensitivities=producer.sensitivities(c,public)
    finally:c.close()
    for p in public.glob('*.csv'):
        frame=pd.read_csv(p)
        require(not {'chooser','username','game_id','account_id','user_id'}.intersection(frame.columns),'Private identifier in original aggregate')
        frame.to_parquet(p.with_suffix('.parquet'),index=False,compression='zstd')
    gates=reproduction(public,ROOT/'evidence/original_f_report') if variant=='included' else []
    write(public/'REPRODUCTION.json',gates)
    result=dict(status='ORIGINAL_F_V102_REFIT',variant=variant,accounts=len(primary),preflight=checks,
        identity=dict(author_games=hits,missing_identity_rows=missing),input_columns=matched,sensitivities=sensitivities,
        original_source_sha256=sha(producer.__file__),standard_errors='Original account-robust joint covariance with n/(n-1) correction',
        original_functions_unmodified=True,original_PAPER_count_assertions=producer.PAPER)
    write(public/'METHOD.json',result)
    require(not any(x['status']=='MISMATCH' for x in gates),'Original F output reproduction mismatch; inspect REPRODUCTION.json')
    return result
