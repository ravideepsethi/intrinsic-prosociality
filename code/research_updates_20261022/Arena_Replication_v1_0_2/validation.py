"""UTC diagnostics around the unchanged original source-mask validator."""
from pathlib import Path

from common import json_write, log, q, require, rows


def validate_opportunity_rows(con,month,output):
    """Preserve the certified Stage 05 ge5s-or-missing clock contract.

    Every other v1.0.1 monthly predicate remains a fatal check. Counts are
    written before failure so a production error identifies its condition.
    This function validates the authenticated sample; it never filters rows.
    """
    checks={
      'non_timeout_rows':"api_status IS DISTINCT FROM 'timeout'",
      'non_rated_rows':'api_rated IS DISTINCT FROM TRUE',
      'clock_rule_failure_rows':'(disconnected_clock_last_obs_s IS NULL OR disconnected_clock_last_obs_s >= 5.0) IS DISTINCT FROM TRUE',
      'requested_nodes_mismatch_rows':'sf100k_nodes_requested IS DISTINCT FROM 100000',
      'missing_kind_outcome_rows':'outcome_kind_draw IS NULL',
      'missing_engine_evaluation_rows':'engine_eval_cp_disconnected IS NULL',
      'kind_alias_mismatch_rows':'kind_draw IS DISTINCT FROM outcome_kind_draw',
      'kind_without_mating_material_rows':'outcome_kind_draw AND chooser_has_mating_material IS DISTINCT FROM TRUE',
    }
    terms=['count(*) AS rows',
      'count(*) FILTER(WHERE disconnected_clock_last_obs_s IS NULL) AS missing_disconnected_clock_rows',
      'count(*) FILTER(WHERE disconnected_clock_last_obs_s IS NULL AND outcome_kind_draw) AS kind_draws_with_missing_clock',
      'count(*) FILTER(WHERE disconnected_clock_last_obs_s IS NULL AND engine_eval_cp_disconnected>=-100) AS competitive_rows_with_missing_clock',
      'count(*) FILTER(WHERE disconnected_clock_last_obs_s IS NOT NULL AND disconnected_clock_last_obs_s<5) AS recorded_clock_below_5_rows',
      'count(*) FILTER(WHERE disconnected_clock_last_obs_s IS NOT NULL AND NOT isfinite(disconnected_clock_last_obs_s)) AS nonfinite_recorded_clock_rows']
    terms += [f'count(*) FILTER(WHERE ({predicate})) AS {name}' for name,predicate in checks.items()]
    terms.append('count(*) FILTER(WHERE '+' OR '.join('('+v+')' for v in checks.values())+') AS invalid_any')
    values=rows(con,'SELECT '+','.join(terms)+' FROM p')[0]
    failures={name:values[name] for name in checks if values[name]}
    report={'month':month,'status':'FAILED' if failures else 'PASSED',
      'clock_rule':'disconnected clock >= 5 seconds OR missing; certified Stage 05 rule',
      'missing_clock_rows_retained':True,'rows_filtered':0,
      'individual_failure_counts_can_overlap':True,'checks':values,'failed_conditions':failures}
    path=Path(output)/('opportunities_'+month+'.json')
    json_write(path,report)
    if failures:
        detail=', '.join(f'{key}={value:,}' for key,value in failures.items())
        raise RuntimeError(f'Opportunity validation failed for {month}: {detail}; diagnostics={path}')
    log(f"Opportunity check {month}: {values['rows']:,} rows; "
        f"missing clocks retained={values['missing_disconnected_clock_rows']:,}; invalid=0")
    return report


def month_timezone_audit(con, timezone_info):
    require(con.execute("SELECT current_setting('TimeZone')").fetchone()[0]=='UTC',
            'Source-mask validation requires explicit UTC')
    inherited=timezone_info['inherited_timezone']
    table=rows(con,f'''WITH a AS (
      SELECT month,
        strftime(to_timestamp(focal_start_ms/1000.0),'%Y-%m') AS utc_month,
        strftime(timezone({q(inherited)},to_timestamp(focal_start_ms/1000.0)),
                 '%Y-%m') AS inherited_month
      FROM j)
      SELECT month,count(*) AS rows,
        count(*) FILTER(WHERE month IS DISTINCT FROM utc_month) AS utc_month_mismatches,
        count(*) FILTER(WHERE month IS DISTINCT FROM inherited_month) AS inherited_month_mismatches
      FROM a GROUP BY month ORDER BY month''')
    return {**timezone_info,'by_month':table,
      'utc_month_mismatches':sum(r['utc_month_mismatches'] for r in table),
      'inherited_month_mismatches':sum(r['inherited_month_mismatches'] for r in table),
      'purpose':'Audit the local-timezone failure without altering rows or source labels.'}


def flag_failure_counts(con,auth):
    # These mirror the disjuncts of the hash-verified original mask_validation.
    # They only explain failure; the original function remains the authority.
    tests={
      'mapping_not_ok':'focal_mapping_ok IS DISTINCT FROM TRUE',
      'missing_first_player':'p1 IS NULL',
      'missing_second_player':'p2 IS NULL',
      'same_player':'p1=p2',
      'missing_start':'focal_start_ms IS NULL',
      'missing_source':'source IS NULL',
      'missing_month':'month IS NULL',
      'missing_source_provenance':"source_provenance IS NULL OR trim(source_provenance)=''",
      'missing_or_unknown_status':f"previous_classification_status IS NULL OR previous_classification_status NOT IN ({','.join(q(x) for x in auth.STATUSES)})",
      'missing_mutual_observation':'mutual_previous_observed IS NULL',
      'missing_ambiguity_flag':'previous_start_order_ambiguous IS NULL',
      'nonadjacent_flag_inconsistent':f'(previous_classification_status={q(auth.NONADJACENT)}) IS DISTINCT FROM (mutual_previous_same_pair IS FALSE)',
      'candidate_flag_inconsistent':f'(previous_classification_status={q(auth.CANDIDATE)}) IS DISTINCT FROM (mutual_previous_same_pair IS TRUE)',
      'unresolved_flag_inconsistent':f'(previous_classification_status IN ({q(auth.MISSING)},{q(auth.AMBIGUOUS)})) IS DISTINCT FROM (mutual_previous_same_pair IS NULL)',
      'ambiguity_flag_inconsistent':f'(previous_classification_status={q(auth.AMBIGUOUS)}) IS DISTINCT FROM previous_start_order_ambiguous',
      'same_pair_without_observation':'mutual_previous_same_pair IS TRUE AND mutual_previous_observed IS DISTINCT FROM TRUE',
      'different_pair_with_observation':'mutual_previous_same_pair IS FALSE AND mutual_previous_observed IS DISTINCT FROM FALSE',
      'invalid_previous_game':'mutual_previous_observed AND (previous_game_id IS NULL OR previous_game_id=game_id)',
      'unexpected_previous_game':'NOT mutual_previous_observed AND previous_game_id IS NOT NULL',
      'utc_month_mismatch':"month IS DISTINCT FROM strftime(to_timestamp(focal_start_ms/1000.0),'%Y-%m')",
    }
    terms=[f'count(*) FILTER(WHERE ({sql})) AS {name}' for name,sql in tests.items()]
    terms.append('count(*) FILTER(WHERE '+ ' OR '.join('('+sql+')' for sql in tests.values())+') AS invalid_any')
    return rows(con,'SELECT '+','.join(terms)+' FROM j')[0]


def validate_source_masks(con,plan,auth,output,timezone_info):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    audit=month_timezone_audit(con,timezone_info)
    json_write(output/'source_month_timezone.json',audit)
    log(f"Source month check: inherited timezone={audit['inherited_timezone']}; "
        f"inherited mismatches={audit['inherited_month_mismatches']:,}; "
        f"UTC mismatches={audit['utc_month_mismatches']:,}")
    try:
        qa=auth.mask_validation(con,plan)
    except Exception as error:
        report={'status':'FAILED','validator':'unchanged original mask_validation',
                'error':type(error).__name__+': '+str(error),'timezone':timezone_info}
        try:
            report['flag_failure_counts']=flag_failure_counts(con,auth)
            report['individual_counts_can_overlap']=True
        except Exception as diagnostic_error:
            report['diagnostic_error']=type(diagnostic_error).__name__+': '+str(diagnostic_error)
        json_write(output/'source_validation.json',report)
        raise
    json_write(output/'source_validation.json',{
      'status':'PASSED','validator':'unchanged original mask_validation',
      'timezone':timezone_info,'qa':qa})
    return qa
