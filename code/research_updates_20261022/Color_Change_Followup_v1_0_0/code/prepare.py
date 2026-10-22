"""Reuse dose and target-state Parquets. Expected runtime: 10-30 min, 10 workers."""
from __future__ import annotations
from io_tools import *

def pool_specs(project):
    authority=read_json(PACKAGE/'authority/pool_main.json')
    root=Path(project)/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    sp=root/'_SUCCESS.json'
    if not sp.is_file():return {},dict(status='MISSING_EXISTING_POOL_SAMPLE',path=str(root))
    s=read_json(sp)
    for k in ('status','main_predicate','contract_sha256','code_sha256','observed_screen_certified','literal_immediate_rematches_certified'):
        if s.get(k)!=authority[k]:raise RuntimeError('Pool authority differs: '+k)
    if s.get('report_zip_sha256')!=authority['report_sha256']:raise RuntimeError('Pool report identity differs')
    local={r['month']:r for r in s.get('panel_outputs',[])};result={}
    for row in authority['panel_outputs']:
        if row['month'] not in local:raise RuntimeError('Missing pool month in receipt')
        for k in ('rows','relative_path','size_bytes','sha256'):
            if local[row['month']].get(k)!=row[k]:raise RuntimeError('Pool monthly receipt differs')
        result[row['month']]=dict(path=str(root/row['relative_path']),record=row)
    return result,dict(status='EXISTING_24_MONTH_POOL_AUTHORITY_FOUND',root=str(root),post_change_membership='UNAVAILABLE',literal_immediate_rematches_certified=False)

def prepare_month(task):
    project,first,work,month,pool_spec,memory_mb=task
    project,first,work=map(Path,(project,first,work));p=first/'dose'/f'month={month}'/'opportunities.parquet'
    r=read_json(p.with_suffix('.json'));verify_record(p,r['output'],work)
    required={'game_id','utc_ms','chooser','color','speed','rating','opp_rating','grant','cp','rd','opp_rd','prior_games','gap_days','established_at_2023_10','d_G','d_C','delta_kappa','K_old','E_old','K_new','E_new','g','rd_bin','gap_bin','old_sign_flip_band','valid_state','chooser_clock','opp_clock','ply','high_rd_returning_strict'}
    if not required<=schema(p):raise RuntimeError(f'{month}: incompatible first-pass dose schema: {required-schema(p)}')
    inputs=[stamp(p)];pool=None
    if pool_spec:
        pool=Path(pool_spec['path']);verify_record(pool,pool_spec['record'],work);inputs.append(stamp(pool))
    base_rec=read_json(first/'base'/f'month={month}'/'opportunities.json')
    if month<'2025-11':
        sr=base_rec['authentication'][0];source=Path(sr['path']);verify_record(source,sr,work);inputs.append(stamp(source))
        cols=schema(source)
        needed={'game_id','pgn_result','white_rating_diff_pgn','black_rating_diff_pgn','white_realized_pred_ratingdiff_v2','black_realized_pred_ratingdiff_v2'}
        if not needed<=cols:raise RuntimeError('Certified calibration fields absent: '+str(needed-cols))
        aux=f"SELECT game_id,CASE pgn_result WHEN '1-0' THEN 1. WHEN '0-1' THEN 0. WHEN '1/2-1/2' THEN .5 END AS white_score,white_rating_diff_pgn AS white_obs,black_rating_diff_pgn AS black_obs,white_realized_pred_ratingdiff_v2 AS white_pred,black_realized_pred_ratingdiff_v2 AS black_pred FROM {scan(source)}"
    else:
        paths=[]
        for speed in SPEEDS:
            dest=first/'replay'/f'speed={speed}'/f'month={month}'
            rr=read_json(dest/'_SUCCESS.json');out=rr['outputs']['targets'];rp=dest/'targets.parquet'
            verify_record(rp,out,work);paths.append(rp);inputs.append(stamp(rp))
        aux=f'SELECT game_id,result_code/2.0 AS white_score,white_rating_diff AS white_obs,black_rating_diff AS black_obs,white_pred,black_pred FROM {scan(paths)}'
    out=work/'narrow'/f'month={month}'/'opportunities.parquet'
    key=digest(dict(version=VERSION,inputs=inputs,pool_known=pool is not None))
    old=cached(out,key)
    if old:log(f'{month}: reuse verified narrow cache');return old
    c=connection(work/'tmp'/month,memory_mb=memory_mb)
    try:
        c.execute(f'CREATE TEMP VIEW dose AS SELECT * FROM {scan(p)}')
        c.execute('CREATE TEMP VIEW aux AS '+aux)
        n,nu,bad=c.execute(f"SELECT count(*),count(DISTINCT game_id),count(*) FILTER(WHERE NOT valid_state OR chooser IS NULL OR utc_ms IS NULL OR NOT isfinite(d_G) OR abs((d_C-d_G)-delta_kappa)>1e-9) FROM dose").fetchone()
        if n!=nu or bad:raise RuntimeError(f'{month}: dose key/state failure {(n,nu,bad)}')
        counts=c.execute('SELECT count(*),count(DISTINCT d.game_id),count(*) FILTER(WHERE a.game_id IS NULL OR a.white_score IS NULL) FROM dose d LEFT JOIN aux a USING(game_id)').fetchone()
        if counts!=(n,n,0):raise RuntimeError(f'{month}: calibration key/result coverage failure {counts}')
        pjoin='';membership='NULL::BOOLEAN'
        if pool:
            c.execute(f'CREATE TEMP VIEW pool AS SELECT game_id FROM {scan(pool)}')
            pn,pu,missing=c.execute('SELECT count(*),count(DISTINCT p.game_id),count(*) FILTER(WHERE d.game_id IS NULL) FROM pool p LEFT JOIN dose d USING(game_id)').fetchone()
            if pn!=pu or missing or pn!=pool_spec['record']['rows']:raise RuntimeError('Pool membership join does not conserve certified IDs')
            pjoin=' LEFT JOIN pool p USING(game_id)';membership='p.game_id IS NOT NULL'
        sql=f"""WITH j AS (SELECT d.*,{membership} AS pool_main,
            CASE WHEN color='white' THEN a.white_score ELSE 1-a.white_score END AS actual_score,
            CASE WHEN color='white' THEN a.white_obs ELSE a.black_obs END::DOUBLE AS observed,
            CASE WHEN color='white' THEN a.white_pred ELSE a.black_pred END AS stored_pred
            FROM dose d LEFT JOIN aux a USING(game_id){pjoin}),
          k AS (SELECT *,K_old*(actual_score-E_old) AS pred_old,K_new*(actual_score-E_new) AS pred_new,
            CASE WHEN cp>=-100 THEN 'competitive' WHEN cp<=-300 THEN 'clearly_losing' ELSE 'middle' END AS board_state,
            {period_sql()} AS period,date_trunc('week',epoch_ms(utc_ms)) AS week,
            CASE WHEN g=0 THEN 'displayed_tie' WHEN old_sign_flip_band THEN 'sign_flip' WHEN abs(g)<{ADVANTAGE} THEN 'opposite_band' WHEN abs(g)<=30 THEN 'outer_30' ELSE 'outside_30' END AS local_band
            FROM j)
          SELECT game_id,utc_ms,week,period,chooser,chooser_user_id::BIGINT AS chooser_id,color,speed,grant,board_state,cp,ply,
            rating,opp_rating,g,rd,opp_rd,rd_bin,gap_bin,chooser_clock,opp_clock,prior_games,gap_days,
            established_at_2023_10 AS established,high_rd_returning_strict AS returner,
            pool_main,d_G,d_C,delta_kappa,K_old,E_old,local_band,old_sign_flip_band,
            actual_score,observed,pred_old,pred_new,
            CASE WHEN utc_ms>={CUTOFF} THEN pred_new ELSE pred_old END AS predicted,
            stored_pred FROM k"""
        copy(c,sql,out)
        mismatch=c.execute(f'SELECT count(*) FROM {scan(out)} WHERE stored_pred IS NULL OR NOT isfinite(stored_pred) OR abs(predicted-stored_pred)>1e-7').fetchone()[0]
        if mismatch:raise RuntimeError(f'{month}: {mismatch} predictions disagree with authenticated replay')
        result=commit(out,key,month=month,pool_membership_known=pool is not None,rows=n,
            inputs=inputs,calibration_join=counts,realized_prediction_disagreements=mismatch)
        log(f'{month}: prepared {n:,} opportunities from cached states');return result
    finally:c.close()

def summarize(work,report,workers,memory_mb):
    work,report=map(Path,(work,report));paths=sorted((work/'narrow').glob('month=*/opportunities.parquet'))
    c=connection(work/'tmp/summary',workers,memory_mb)
    try:
        c.execute(f'CREATE VIEW base AS SELECT * FROM {scan(paths)}')
        c.execute("CREATE VIEW samples AS SELECT b.*,s.sample FROM base b CROSS JOIN (VALUES ('all_source'),('pool_observed_nonadjacent')) s(sample) WHERE s.sample='all_source' OR b.pool_main")
        # Overlapping strata are explicitly named; never add their denominators.
        c.execute("CREATE VIEW strata AS SELECT b.*,s.stratum FROM samples b CROSS JOIN (VALUES ('all_accounts'),('fixed_established'),('established_returning_rd200')) s(stratum) WHERE s.stratum='all_accounts' OR (s.stratum='fixed_established' AND b.established) OR (s.stratum='established_returning_rd200' AND b.returner)")
        queries={
          'dose_by_period':"""SELECT sample,stratum,period,board_state,color,rd_bin,count(*) n,count(DISTINCT chooser) choosers,
            avg(abs(d_G)) mean_abs_dG,avg(d_G) mean_dG,stddev_pop(d_G) sd_dG,
            quantile_cont(abs(d_G),[.1,.5,.9,.99])::VARCHAR abs_dG_quantiles,
            avg(d_C) mean_dC,avg(delta_kappa) mean_delta_kappa,avg(abs(delta_kappa)) mean_abs_delta_kappa,
            avg(abs(delta_kappa))/nullif(avg(abs(d_G)),0) ratio_of_mean_magnitudes,
            count(*) FILTER(WHERE abs(d_G)<=1e-9) zero_dose_n,
            count(*) FILTER(WHERE prior_games IS NULL) missing_experience_n,
            count(*) FILTER(WHERE gap_days IS NULL) missing_gap_days_n
            FROM strata WHERE period<>'transition' GROUP BY ALL""",
          'premium_by_band':"""SELECT sample,stratum,period,board_state,color,rd_bin,local_band,abs(g)<=50 AS within_50,
            count(*) n,avg(abs(d_G)) mean_abs_dG,avg(abs(delta_kappa)) mean_abs_delta_kappa,
            avg(CASE WHEN abs(d_G)>1e-9 THEN abs(delta_kappa)/abs(d_G) END) mean_individual_ratio,
            quantile_cont(CASE WHEN abs(d_G)>1e-9 THEN abs(delta_kappa)/abs(d_G) END,[.5,.9,.99])::VARCHAR ratio_quantiles,
            count(*) FILTER(WHERE abs(d_G)<=1e-9) near_zero_denominator_n
            FROM strata WHERE period<>'transition' GROUP BY ALL""",
          'weekly_cells':"""SELECT sample,stratum,week,board_state,color,count(*) opportunities,sum(grant) grants,
            count(DISTINCT chooser) choosers,avg(d_G) mean_dG,avg(abs(d_G)) mean_abs_dG
            FROM strata GROUP BY ALL""",
          'calibration_cells':"""SELECT sample,stratum,strftime(epoch_ms(utc_ms),'%Y-%m') AS month,period,speed,color,board_state,
            rd_bin,gap_bin,local_band,actual_score,count(*) n,count(observed) observed_n,
            avg(predicted-observed) signed_error,avg(abs(predicted-observed)) mae,
            avg(abs(pred_old-observed)) old_mae,avg((abs(predicted-observed)>2)::INTEGER) abs_gt2_share,
            avg(observed) mean_observed,avg(predicted) mean_predicted
            FROM strata GROUP BY ALL""",
          'draw_integer_distribution':"""SELECT sample,stratum,period,speed,color,board_state,rd_bin,g::INTEGER displayed_gap,
            CASE WHEN observed IS NULL THEN 'missing' WHEN observed < -5 THEN 'below_-5' WHEN observed>5 THEN 'above_5' ELSE cast(observed AS VARCHAR) END AS observed_delta,
            count(*) n,avg(predicted) mean_predicted,avg(predicted-observed) signed_error
            FROM strata WHERE actual_score=.5 AND abs(g)<=30 GROUP BY ALL""",
          'returning_support':"""SELECT period,board_state,color,speed,count(*) n,count(DISTINCT chooser) choosers,
            avg(abs(d_G)) mean_abs_dG,avg(prior_games) mean_prior_games,avg(gap_days) mean_gap_days,
            count(observed) observed_n,avg(abs(predicted-observed)) mae,avg(predicted-observed) signed_error
            FROM base WHERE returner GROUP BY ALL""",
          'coverage':"""SELECT strftime(epoch_ms(utc_ms),'%Y-%m') AS month,count(*) n,count(*) FILTER(WHERE established) established_n,
            count(*) FILTER(WHERE pool_main IS NOT NULL) membership_known_n,count(*) FILTER(WHERE pool_main) pool_n,
            count(*) FILTER(WHERE prior_games IS NOT NULL) experience_known_n,count(*) FILTER(WHERE gap_days IS NOT NULL) gap_known_n
            FROM base GROUP BY ALL"""
        }
        for name,sql in queries.items():export(c,sql,report/(name+'.parquet'));log('Wrote '+name)
        cells=scan(report/'calibration_cells.parquet')
        export(c,f"""WITH b AS (SELECT * FROM {cells} WHERE month='2025-11' AND period='pre')
          SELECT p.*,b.observed_n baseline_observed_n,b.mae pre_mae,b.signed_error pre_signed_error,p.mae-b.mae mae_difference
          FROM {cells} p LEFT JOIN b USING(sample,stratum,speed,color,board_state,rd_bin,gap_bin,local_band,actual_score)
          WHERE p.period NOT IN ('pre','transition')""",report/'matched_opportunity_calibration.parquet')
    finally:c.close()
