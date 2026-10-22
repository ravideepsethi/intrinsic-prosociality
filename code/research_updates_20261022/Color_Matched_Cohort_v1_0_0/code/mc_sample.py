"""Freeze the common sample and export coverage/calibration before comparisons."""
from mc_io import *

FIELDS=('game_id','chooser','opponent','t','month','speed','color','y','cp','ply','rating','opp_rating','g','rd','opp_rd',
        'rg','rc','ki','kj','clock','opp_clock','prior_starts','history_days','inactivity_days','opp_prior_starts','state')

def assemble(catalog,post,rosters,work,report,memory):
    work=Path(work);report=Path(report);parts=[];gates=[];selection=[];calibration=[]
    inputs=[auth(p,work) for p in [*catalog['pre'],*post,*rosters]]
    for month in POST_MONTHS:
        inputs += [auth(work/'post_features'/f'{s}_{month}.parquet',work) for s in SPEEDS]
    key=digest(dict(version=VERSION,inputs=inputs,rd_rule='contemporaneous_both_45_110',regularity='fixed_at_implementation'))
    target=work/'matched_all_states.parquet'
    cached=cache(target,key,work)
    if cached:
        for r in cached['summary_outputs']:record_auth(work/r['relative_path'],r,work)
        for name in ('sample_selection','coverage_gates','calibration_cells','roster_counts'):
            table(pd.read_parquet(work/'summaries'/(name+'.parquet')),report/name)
        return str(target),pd.read_parquet(work/'summaries/coverage_gates.parquet').to_dict('records')
    c=connect(work/'tmp/sample',2,memory)
    try:
        c.execute('CREATE VIEW roster AS SELECT * FROM '+scan(rosters)+' WHERE fixed_regular_cohort')
        counts=c.execute('SELECT speed,count(*) eligible_accounts,min(prior_starts) min_prior_starts,min(history_days) min_history_days FROM roster GROUP BY speed').fetchdf()
        table(counts,work/'summaries/roster_counts');table(counts,report/'roster_counts')
        for path in [*catalog['pre'],*post]:
            month=Path(path).stem
            if month in POST_MONTHS:
                hs=[work/'post_features'/f'{s}_{month}.parquet' for s in SPEEDS]
                c.execute('CREATE OR REPLACE VIEW h AS SELECT * FROM '+scan(hs))
                c.execute(f'''CREATE OR REPLACE VIEW b AS SELECT d.*,h.prior_starts,h.history_days,h.inactivity_days,o.prior_starts opp_prior_starts
                    FROM {scan(path)} d JOIN h ON d.game_id=h.game_id AND h.role=1 JOIN h o ON d.game_id=o.game_id AND o.role=0''')
            else:
                c.execute(f'''CREATE OR REPLACE VIEW b AS SELECT d.*,'pool'::VARCHAR AS source,'recovered'::VARCHAR source_status,
                    'not_mutually_adjacent_observed'::VARCHAR previous_classification_status,TRUE pool_main,
                    NULL::DOUBLE actual_score,NULL::DOUBLE observed,NULL::DOUBLE pred_old,NULL::DOUBLE pred_new,
                    NULL::DOUBLE stored_pred FROM {scan(path)} d''')
            c.execute('''CREATE OR REPLACE VIEW r AS SELECT b.* FROM b JOIN roster k ON b.chooser=k.user_id AND b.speed=k.speed''')
            # Unknown source cannot be recoded non-pool. Boundary/ambiguous
            # adjacency is excluded under the original main-sample predicate.
            c.execute('''CREATE OR REPLACE VIEW a AS SELECT *,rd BETWEEN 45 AND 110 AND opp_rd BETWEEN 45 AND 110 rd_eligible,
                source_status='recovered' AND source IS NOT NULL source_known,
                previous_classification_status IN ('not_mutually_adjacent_observed','mutual_adjacency_candidate_timing_unresolved',
                  'left_boundary_unresolved','ambiguous_start_order') adjacency_classified,
                source='pool' AND previous_classification_status='not_mutually_adjacent_observed' main_member,
                isfinite(history_days) AND isfinite(inactivity_days) AND isfinite(prior_starts) AND isfinite(opp_prior_starts)
                  AND history_days>=0 AND inactivity_days>=0 AND prior_starts>=0 AND opp_prior_starts>=0 features_valid
                FROM r''')
            flow=c.execute('''SELECT month,state,color,count(*) fixed_cohort_opportunities,
                count(*) FILTER(WHERE rd_eligible) rd_eligible_n,
                count(*) FILTER(WHERE rd_eligible AND source_known) source_known_n,
                count(*) FILTER(WHERE rd_eligible AND source_known AND main_member) main_n,
                count(*) FILTER(WHERE rd_eligible AND source_known AND main_member AND features_valid) common_n,
                count(*) FILTER(WHERE rd_eligible AND source_known AND main_member AND NOT features_valid) history_feature_exclusions,
                count(*) FILTER(WHERE rd_eligible AND source_known AND main_member AND features_valid AND clock IS NULL) missing_chooser_clock,
                count(*) FILTER(WHERE rd_eligible AND source_known AND main_member AND features_valid AND opp_clock IS NULL) missing_opponent_clock,
                count(*) FILTER(WHERE rd_eligible AND source_known AND main_member AND features_valid AND opp_clock<5) below_five_seconds,
                count(DISTINCT chooser) chooser_accounts FROM a GROUP BY ALL''').fetchdf()
            selection.extend(flow.to_dict('records'))
            # Coverage checks are exported weekly to permit safe short windows
            # even if a later month still has unresolved source labels.
            g=c.execute('''SELECT epoch_ms(date_trunc('week',epoch_ms(t)))::BIGINT week_ms,state,
                count(*) FILTER(WHERE rd_eligible) eligible_before_membership,
                count(*) FILTER(WHERE rd_eligible AND NOT coalesce(source_known,FALSE)) unknown_source_n,
                count(*) FILTER(WHERE rd_eligible AND source='pool' AND NOT coalesce(adjacency_classified,FALSE)) unmapped_pool_adjacency_n,
                count(*) FILTER(WHERE rd_eligible AND main_member AND features_valid AND opp_clock<5) clock_rule_violation_n
                FROM a GROUP BY ALL''').fetchdf();gates.extend(g.to_dict('records'))
            out=work/'matched_months'/(month+'.parquet')
            copy(c,'SELECT '+','.join(FIELDS)+''' FROM a WHERE rd_eligible AND source_known AND main_member AND features_valid''',out)
            if month in POST_MONTHS:
                cal=c.execute(f'''SELECT month,state,color,speed,actual_score,
                    CASE WHEN t<{BRACKET} THEN 'pre' WHEN t<{IMPLEMENTED} THEN 'implementation_bracket'
                         WHEN t<{ANNOUNCED} THEN 'unannounced' ELSE 'announced' END period,
                    CASE WHEN g=0 THEN 'displayed_tie' WHEN (color='white' AND g>0 AND g<{ADVANTAGE})
                      OR (color='black' AND g<0 AND g>-{ADVANTAGE}) THEN 'strict_flip' ELSE 'other_gap' END gap_band,
                    count(*) n,count(observed) observed_n,avg(stored_pred-observed) signed_error,
                    avg(abs(stored_pred-observed)) mae,avg(abs(pred_old-observed)) old_mae,
                    avg(abs(pred_new-observed)) new_mae,
                    count(*) FILTER(WHERE stored_pred IS NULL) missing_prediction_n
                    FROM a WHERE rd_eligible AND source_known AND main_member AND features_valid GROUP BY ALL''').fetchdf()
                calibration.extend(cal.to_dict('records'))
            parts.append(out)
        copy(c,'SELECT * FROM '+scan(parts)+' ORDER BY chooser,t,game_id',target)
        n,nu,bad=c.execute(f'''SELECT count(*),count(DISTINCT game_id),count(*) FILTER(WHERE chooser=opponent
            OR y NOT IN(0,1) OR NOT isfinite(rg+rc+ki+kj) OR ki<=0 OR kj<=0) FROM {scan(target)}''').fetchone()
        if n!=nu or bad:raise RuntimeError('Final matched-sample identity/payoff audit failed')
        for name,rows in [('sample_selection',selection),('coverage_gates',gates),('calibration_cells',calibration)]:
            d=pd.DataFrame(rows)
            if name=='coverage_gates':d=d.groupby(['week_ms','state'],as_index=False).sum(numeric_only=True)
            table(d,work/'summaries'/name);table(d,report/name)
        summaries=[dict(relative_path=str(p.relative_to(work)),sha256=sha(p),bytes=p.stat().st_size) for p in (work/'summaries').glob('*.parquet')]
        unchanged(inputs);commit(target,key,input_snapshots=inputs,rows=n,actual_regular_roster=True,summary_outputs=summaries,
            source_predicate="source='pool' AND previous_classification_status='not_mutually_adjacent_observed'",
            regularity_uses_post_activity=False,rd_eligibility='contemporaneous_both_45_110',formal_censor_certified=False)
        return str(target),pd.read_parquet(work/'summaries/coverage_gates.parquet').to_dict('records')
    finally:c.close()
