"""Outcome-blind eligibility checks plus mechanical rating calibration.

No receipt first stage, reduced form, IV coefficient, or behavioral grant-rate
contrast is calculated. Mechanical calibration conditions on recorded results.
"""
import shutil
from common import *
from contracts import snap

def ms(s):return int(dt.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
POLICY_LO=ms('2025-11-18T07:15:00Z');POLICY_HI=ms('2025-11-18T07:22:00Z')
PANEL_END=ms('2026-05-01T00:00:00Z')
ADVANTAGE=11.782457
EXPECTED_COUNTS=(18754435,18754435,3917764,3253387,468029,0,1683874)

def endpoints():
    out=[dict(endpoint='pre_color_guard',utc='2025-11-18T07:15:00Z',meaning='Sensitivity: all follow-up precedes the implementation bracket'),
         dict(endpoint='source_day_guard',utc='2026-01-30T00:00:00Z',meaning='Conservative source-date sensitivity; not a proven deployment cutoff'),
         dict(endpoint='source_authored',utc='2026-01-30T10:04:23Z',meaning='Commit author/committer timestamp; not deployment'),
         dict(endpoint='source_merged',utc='2026-02-01T10:31:02Z',meaning='PR merge timestamp; not deployment'),
         dict(endpoint='calendar_only',utc='2026-05-01T00:00:00Z',meaning='Available-data endpoint; not an adopted causal censor')]
    start=dt.datetime(2026,1,20,tzinfo=dt.timezone.utc)
    for i in range(27):
        t=start+dt.timedelta(days=i)
        out.append(dict(endpoint='daily_'+t.strftime('%Y_%m_%d'),utc=t.isoformat().replace('+00:00','Z'),
                        meaning='Outcome-blind cutoff grid; no date selected by fit'))
    return [dict(r,endpoint_ms=ms(r['utc']),latest_anchor_exclusive_ms=ms(r['utc'])-90*DAY) for r in out]

def complete_window(anchor,endpoint):
    return np.asarray(anchor,dtype=np.int64)+90*DAY < int(endpoint)

def later_interaction(reached,identified,color,t):
    """None is structural missingness; zero is reserved for identified choices."""
    if not reached or not identified or POLICY_LO<=t<POLICY_HI:return None
    if color not in ('white','black'):raise ValueError('Unknown later color')
    return int(color=='white' and t>=POLICY_HI)

def phase_sql(col):
    return f"CASE WHEN {col}<{POLICY_LO} THEN 'pre' WHEN {col}>={POLICY_HI} THEN 'post' ELSE 'implementation_bracket' END"

def rd_bin(col):
    return f"CASE WHEN {col}<45.01 THEN 'floor' WHEN {col}<60 THEN '45.01_60' WHEN {col}<100 THEN '60_100' WHEN {col}<200 THEN '100_200' ELSE '200_plus' END"

def gap_bin(col):
    vals=[(-200,'below_minus200'),(-50,'minus200_minus50'),(-30,'minus50_minus30'),
          (-ADVANTAGE,'minus30_minusA'),(0,'minusA_zero'),(ADVANTAGE,'zero_A'),(30,'A_30'),(50,'30_50'),(200,'50_200')]
    # Ties are a separate cell and are excluded from both sign-flip bands.
    return "CASE WHEN "+col+"=0 THEN 'displayed_tie' "+' '.join(f'WHEN {col}<{v} THEN {lit(label)}' for v,label in vals)+" ELSE '200_plus' END"

def export(c,query,path):
    copy(c,query,Path(path).with_suffix('.parquet'))
    c.execute('COPY (SELECT * FROM '+scan(Path(path).with_suffix('.parquet'))+') TO '+lit(Path(path).with_suffix('.csv'))+' (HEADER)')

def cutoff_tables(c,out):
    ep=pa.Table.from_pylist(endpoints());c.register('endpoints',ep)
    # Original greedy spacing and history membership remain fixed. Never rerun
    # selection after censoring or apply the ten-decision floor before spacing.
    sql=f'''SELECT e.endpoint,e.utc,e.meaning,e.endpoint_ms,e.latest_anchor_exclusive_ms,a.month,
        count(*) FILTER(WHERE calendar_primary_7d_floor5) primary_rows,
        count(*) FILTER(WHERE calendar_common5_10) common5_10_rows,
        count(*) FILTER(WHERE calendar_independently_spaced_floor10) independently_spaced_floor10_rows,
        count(*) FILTER(WHERE calendar_primary_7d_floor5 AND support_30d_floor5 AND isfinite(adjusted_30d)) lag30_floor5_on_primary_rows,
        count(*) FILTER(WHERE calendar_common5_10 AND support_30d_floor10 AND isfinite(adjusted_30d)) lag30_floor10_on_common_rows,
        count(*) FILTER(WHERE calendar_primary_7d_floor5 AND reached) primary_reached_rows,
        count(*) FILTER(WHERE calendar_primary_7d_floor5 AND NOT reached) primary_nonreached_rows,
        count(*) FILTER(WHERE calendar_primary_7d_floor5 AND (recipient_rd IS NULL OR opponent_rd IS NULL)) missing_rd_rows,
        count(*) FILTER(WHERE calendar_primary_7d_floor5 AND anchor_ms>={POLICY_HI}) index_post_color_rows,
        count(*) FILTER(WHERE calendar_primary_7d_floor5 AND later_choice_is_identified AND later_choice_policy_period='post') later_post_color_rows,
        count(*) FILTER(WHERE calendar_primary_7d_floor5 AND later_choice_policy_period='implementation_bracket') later_bracket_rows,
        NULL::BOOLEAN mechanics_cutoff_validated,NULL::BIGINT final_iv_n
        FROM a CROSS JOIN endpoints e WHERE a.anchor_ms+{90*DAY}<e.endpoint_ms AND e.endpoint_ms<={PANEL_END}
        GROUP BY ALL ORDER BY e.endpoint_ms,a.month'''
    export(c,sql,out/'CUTOFF_SAMPLE_COUNTS')
    # Preserve structural nonreachers rather than encoding all of them as Black.
    bad=c.execute(f'''SELECT count(*) FROM a WHERE
        later_white_x_post IS DISTINCT FROM CASE WHEN reached AND later_choice_is_identified
          AND (outcome_t<{POLICY_LO} OR outcome_t>={POLICY_HI}) THEN
          (outcome_color='white')::INTEGER*(outcome_t>={POLICY_HI})::INTEGER ELSE NULL END
        OR (later_choice_is_identified AND outcome_color NOT IN ('white','black'))''').fetchone()[0]
    if bad:raise RuntimeError('Inherited later-choice color/period/missingness is inconsistent')
    export(c,'''SELECT month,index_policy_period,later_choice_policy_period,
        CASE WHEN NOT reached THEN 'nonreacher' WHEN NOT later_choice_is_identified THEN 'ambiguous' ELSE outcome_color END later_color_status,
        later_white_x_post,count(*) AS row_count,count(*) FILTER(WHERE calendar_common5_10) common5_10_rows
        FROM a WHERE calendar_primary_7d_floor5 GROUP BY ALL ORDER BY ALL''',out/'LATER_CHOICE_AVAILABILITY')

def player_query():
    parts=[]
    for role,other,col in [('opponent','recipient','index_chooser_color'),('recipient','opponent',"CASE WHEN index_chooser_color='white' THEN 'black' ELSE 'white' END")]:
        parts.append(f'''SELECT game_id,month,speed,archive_start_ms,{lit(role)} player_role,{col} color,
          {role}_rating rating,{other}_rating opp_rating,{role}_rd rd,{other}_rd opp_rd,
          {role}_observed_change observed_change,{role}_predicted_change stored_prediction,
          {role}_prior_games prior_games,{role}_inactivity_days inactivity_days,
          {role}_established_oct2023 fixed_established,result_code
          FROM a WHERE calendar_primary_7d_floor5 AND replay_state_attached''')
    return ' UNION ALL '.join(parts)

def calibration_tables(c,out):
    c.execute('CREATE VIEW players AS '+player_query())
    c.execute(f'''CREATE VIEW p0 AS SELECT *,{phase_sql('archive_start_ms')} phase,
        opp_rating-rating rating_gap,CASE WHEN color='white' THEN result_code/2.0 ELSE 1-result_code/2.0 END score,
        CASE WHEN color='white' THEN 1.0 ELSE -1.0 END color_sign,
        {rd_bin('rd')} rd_bin,1/sqrt(1+3*pow(greatest(opp_rd,45)/173.7178,2)/pow(pi(),2)) attenuation
        FROM players''')
    c.execute('''CREATE VIEW p1 AS SELECT *,
        greatest(1e-12,least(1-1e-12,1/(1+exp(greatest(-700,least(700,-attenuation*(rating-opp_rating)/173.7178)))))) e_old,
        greatest(1e-12,least(1-1e-12,1/(1+exp(greatest(-700,least(700,-attenuation*(rating-opp_rating+color_sign*11.782457)/173.7178)))))) e_new
        FROM p0''')
    c.execute('''CREATE VIEW p2 AS SELECT *,
        173.7178*attenuation/(1/pow(greatest(rd,45)/173.7178,2)+pow(attenuation,2)*e_old*(1-e_old)) k_old,
        173.7178*attenuation/(1/pow(greatest(rd,45)/173.7178,2)+pow(attenuation,2)*e_new*(1-e_new)) k_new FROM p1''')
    c.execute(f'''CREATE TEMP TABLE mechanical AS SELECT *,
        k_old*(score-e_old) old_prediction,k_new*(score-e_new) new_prediction,
        k_new*(.5-e_new)-k_old*(.5-e_old) dG,
        k_new*(1-e_new)-k_old*(1-e_old) dC,
        {gap_bin('rating_gap')} gap_bin,
        (color='white' AND rating_gap>0 AND rating_gap<11.782457)
          OR (color='black' AND rating_gap<0 AND rating_gap> -11.782457) sign_flip_band,
        fixed_established AND rd>=200 AND inactivity_days>=90 returning_strict,
        observed_change IS NOT NULL AND isfinite(observed_change) has_observation
        FROM p2''')
    # This is a convention-consistency test, not production calibration.
    err=c.execute(f'''SELECT max(abs(stored_prediction-CASE WHEN archive_start_ms>={POLICY_HI}
        THEN new_prediction ELSE old_prediction END)) FROM mechanical''').fetchone()[0]
    if err is not None and err>1e-8:raise RuntimeError('Stored prediction does not match the certified fixed-state formula')
    c.execute('''CREATE VIEW strata AS SELECT *, 'all_primary' stratum FROM mechanical
        UNION ALL SELECT *, 'fixed_established' stratum FROM mechanical WHERE fixed_established
        UNION ALL SELECT *, 'returning_strict' stratum FROM mechanical WHERE returning_strict''')
    export(c,'''SELECT month,phase,player_role,color,speed,stratum,rd_bin,gap_bin,score,count(*) AS row_count,
        count(*) FILTER(WHERE has_observation) observed_updates,
        avg(abs(stored_prediction-observed_change)) FILTER(WHERE has_observation) mae,
        avg(stored_prediction-observed_change) FILTER(WHERE has_observation) signed_error,
        sum(abs(stored_prediction-observed_change)) FILTER(WHERE has_observation) sum_abs_error,
        avg(abs(old_prediction-observed_change)) FILTER(WHERE has_observation) old_formula_mae,
        avg(abs(new_prediction-observed_change)) FILTER(WHERE has_observation) new_formula_mae
        FROM strata GROUP BY ALL ORDER BY ALL''',out/'CALIBRATION_CELLS')
    src=scan(out/'CALIBRATION_CELLS.parquet')
    export(c,f'''WITH b AS (SELECT * FROM {src} WHERE phase='pre' AND observed_updates>0)
        SELECT p.*,b.observed_updates baseline_observed_updates,b.mae baseline_mae,b.signed_error baseline_signed_error,
        b.observed_updates IS NOT NULL baseline_matched
        FROM {src} p LEFT JOIN b USING(player_role,color,speed,stratum,rd_bin,gap_bin,score)
        WHERE p.phase='post' ''',out/'CALIBRATION_MATCHED_CELLS')
    export(c,f'''SELECT month,player_role,color,speed,stratum,sum(observed_updates) post_observed_updates,
        sum(observed_updates) FILTER(WHERE baseline_matched) matched_post_updates,
        sum(observed_updates) FILTER(WHERE NOT baseline_matched) unmatched_post_updates,
        sum(baseline_mae*observed_updates) FILTER(WHERE baseline_matched)/nullif(sum(observed_updates) FILTER(WHERE baseline_matched),0) weighted_pre_mae,
        sum(mae*observed_updates) FILTER(WHERE baseline_matched)/nullif(sum(observed_updates) FILTER(WHERE baseline_matched),0) matched_post_mae,
        sum(signed_error*observed_updates) FILTER(WHERE baseline_matched)/nullif(sum(observed_updates) FILTER(WHERE baseline_matched),0) matched_post_signed_error
        FROM {scan(out/'CALIBRATION_MATCHED_CELLS.parquet')} GROUP BY ALL ORDER BY ALL''',out/'CALIBRATION_MATCHED_SUMMARY')
    export(c,'''SELECT month,phase,player_role,color,speed,stratum,rd_bin,gap_bin,sign_flip_band,
        observed_change,count(*) observed_updates,avg(stored_prediction) mean_prediction,
        avg(stored_prediction-observed_change) mean_signed_error
        FROM strata WHERE score=.5 AND abs(rating_gap)<=12 AND has_observation GROUP BY ALL ORDER BY ALL''',out/'NEAR_ZERO_DRAW_DISTRIBUTIONS')
    export(c,'''SELECT month,phase,player_role,color,speed,stratum,rd_bin,sign_flip_band,
        count(*) opportunities,avg(abs(dG)) mean_abs_draw_shift,avg(abs(dC-dG)) mean_abs_premium_shift,
        100*sum(abs(dC-dG))/nullif(sum(abs(dG)),0) premium_ratio_of_means_percent,
        min(prior_games) minimum_prior_games,avg(inactivity_days) mean_inactivity_days
        FROM strata GROUP BY ALL ORDER BY ALL''',out/'IV_SAMPLE_MECHANICAL_DOSE')
    return dict(max_fixed_state_formula_difference=err,
        calibration_scope='Calendar-primary first-pair competitive IV exposures in November–January; both player roles. Strata overlap.',
        returning_definition='Side-specific RD>=200, >=100 same-speed rated updates by October 2023, last same-speed rated update >=90 days earlier.',
        old_returning_history_availability='Not newly recovered for earlier IV exposures. No complete returning-stratum DiD is claimed.',
        near_zero_definition='Observed integer changes, both gap sides, displayed ties separate; no rounding rule fitted.',
        matched_weighting='Post observed-update weights within speed/color/role/stratum/RD/gap/outcome cells. Unmatched cells are explicitly retained.')

def build(products,root,code,threads,memory,auth):
    inputs=[snap(Path(p['root'])/'_DONE.json') for p in products]
    key=digest(dict(code=code,inputs=inputs))
    def produce(tmp):
        c=connection(tmp/'spill',threads,memory)
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+scan([p['path'] for p in products]))
            n,u,primary,common,missing_before,missing_after,nonreached=c.execute('''SELECT count(*),count(DISTINCT game_id),
                count(*) FILTER(WHERE calendar_primary_7d_floor5),count(*) FILTER(WHERE calendar_common5_10),
                count(*) FILTER(WHERE calendar_primary_7d_floor5 AND original_recipient_rd IS NULL),
                count(*) FILTER(WHERE calendar_primary_7d_floor5 AND (recipient_rd IS NULL OR opponent_rd IS NULL)),
                count(*) FILTER(WHERE calendar_primary_7d_floor5 AND NOT reached) FROM a''').fetchone()
            if (n,u,primary,common,missing_before,missing_after,nonreached)!=EXPECTED_COUNTS:
                raise RuntimeError('Reviewed cohort or expected primary RD attachment did not reconcile')
            export(c,'''SELECT month,count(*) AS row_count,count(*) FILTER(WHERE calendar_primary_7d_floor5) primary_rows,
                count(*) FILTER(WHERE calendar_primary_7d_floor5 AND original_recipient_rd IS NULL) missing_rd_before,
                count(*) FILTER(WHERE calendar_primary_7d_floor5 AND (recipient_rd IS NULL OR opponent_rd IS NULL)) missing_rd_after,
                count(*) FILTER(WHERE replay_state_attached) replay_attached_rows FROM a GROUP BY month ORDER BY month''',tmp/'RD_ATTACHMENT_COUNTS')
            cutoff_tables(c,tmp);calibration=calibration_tables(c,tmp)
            write_json(tmp/'CALIBRATION_DEFINITIONS.json',calibration)
            return dict(status='STATES_ATTACHED_AND_CUTOFF_DIAGNOSTICS_COMPLETE',first_pair_rows=n,calendar_primary_rows=primary,
                calendar_common5_10_rows=common,primary_RD_rows_restored=missing_before,primary_missing_RD_rows=missing_after,
                primary_nonreachers_retained=nonreached,author_exclusion_applied=False,mechanics_censor=None,final_iv_eligible_n=None,
                new_IV_estimate=None,behavioral_estimation=False,source_requests=0,rating_replays=0,Stockfish_calls=0,
                calibration=calibration)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(root/'diagnostics'/key,key,inputs,produce,auth)
