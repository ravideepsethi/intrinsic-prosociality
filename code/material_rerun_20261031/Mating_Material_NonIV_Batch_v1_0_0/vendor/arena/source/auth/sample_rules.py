"""The agreed sample rule. No timing cutoff and no successor selection."""
CANDIDATE = 'mutual_adjacency_candidate_timing_unresolved'
NONADJACENT = 'not_mutually_adjacent_observed'
MISSING = 'left_boundary_unresolved'
AMBIGUOUS = 'ambiguous_start_order'
STATUSES = [CANDIDATE, NONADJACENT, MISSING, AMBIGUOUS]
SAMPLES = [
    ('original', 'TRUE'),
    ('pool', 'eligible_pool'),
    ('main_pool_nonadjacent', 'eligible_main'),
    ('pool_restore_missing_previous', 'eligible_pool_restore_missing_previous'),
]
COUNT_COLUMNS = ['rows', 'kind_draws', 'fair_rows', 'fair_kind_draws']
CONTINUOUS = {
    'chooser_rating': 'CAST(chooser_elo AS DOUBLE)',
    'disconnected_rating': 'CAST(disconnected_elo AS DOUBLE)',
    'opponent_minus_chooser_rating': 'CAST(disconnected_elo AS DOUBLE)-CAST(chooser_elo AS DOUBLE)',
    'draw_payoff': 'chooser_draw_payoff_v2',
    'game_plies': 'CAST(ply_count AS DOUBLE)',
    'disconnected_clock_seconds': 'disconnected_clock_last_obs_s',
}


def mask_query():
    return f'''SELECT game_id,month,source,source_provenance,
      p1 AS chooser_user_id,p2 AS disconnected_user_id,focal_start_ms AS observed_start_ms,
      previous_classification_status,previous_game_id,mutual_previous_observed,
      mutual_previous_same_pair,previous_start_order_ambiguous,
      source='pool' AS eligible_pool,
      source='pool' AND previous_classification_status='{NONADJACENT}' AS eligible_main,
      source='pool' AND previous_classification_status IN ('{NONADJACENT}','{MISSING}')
        AS eligible_pool_restore_missing_previous,
      CASE WHEN source<>'pool' THEN 'not_pool'
           WHEN previous_classification_status='{NONADJACENT}' THEN 'included_main'
           WHEN previous_classification_status='{CANDIDATE}' THEN 'pool_adjacent_candidate'
           WHEN previous_classification_status='{MISSING}' THEN 'pool_missing_previous'
           WHEN previous_classification_status='{AMBIGUOUS}' THEN 'pool_ambiguous_order'
           ELSE 'ERROR_UNKNOWN_STATUS' END AS main_exclusion_reason
      FROM j'''


def counts_sql():
    return '''count(*) AS rows,count(*) FILTER(WHERE outcome_kind_draw) AS kind_draws,
      count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100) AS fair_rows,
      count(*) FILTER(WHERE outcome_kind_draw AND engine_eval_cp_disconnected>=-100) AS fair_kind_draws'''


def summary_query(sample, condition):
    moments = []
    for name, expression in CONTINUOUS.items():
        moments.extend([f'count(*) FILTER(WHERE isfinite({expression})) AS {name}_n',
                        f'coalesce(sum({expression}) FILTER(WHERE isfinite({expression})),0) AS {name}_sum'])
    return f"SELECT '{sample}' AS sample,{counts_sql()},"+','.join(moments)+f' FROM b WHERE {condition}'


def board_case():
    return '''CASE WHEN engine_eval_cp_disconnected<=-300 THEN 'clearly_worse'
      WHEN engine_eval_cp_disconnected<-100 THEN 'modestly_worse'
      WHEN engine_eval_cp_disconnected<=100 THEN 'roughly_equal'
      WHEN engine_eval_cp_disconnected<300 THEN 'better' ELSE 'clearly_better' END'''


def ply_case():
    return '''CASE WHEN ply_count BETWEEN 0 AND 1 THEN 'plies_0_1'
      WHEN ply_count=2 THEN 'plies_2'
      WHEN ply_count BETWEEN 3 AND 10 THEN 'plies_3_10'
      WHEN ply_count>10 THEN 'plies_over_10' ELSE 'missing_or_invalid' END'''


def presence_query():
    """Four bits per sample: any opportunity, fair, kind, fair-kind.

    Per-chooser OR across months yields exact global distinct counts without
    treating monthly distinct accounts as mutually exclusive.
    """
    terms = []
    for i, (_, condition) in enumerate(SAMPLES):
        for offset, event in enumerate(['TRUE', 'engine_eval_cp_disconnected>=-100',
                                        'outcome_kind_draw', 'outcome_kind_draw AND engine_eval_cp_disconnected>=-100']):
            terms.append(f'(CASE WHEN ({condition}) AND ({event}) THEN {1 << (4*i+offset)} ELSE 0 END)')
    return 'SELECT chooser_user_id,bit_or(CAST(('+'+'.join(terms)+') AS BIGINT)) AS presence_bits FROM b GROUP BY 1'


def distinct_counts_query(view):
    parts = []
    for i, (sample, _) in enumerate(SAMPLES):
        expressions = [f"'{sample}' AS sample"]
        for offset, name in enumerate(['choosers', 'fair_choosers', 'kind_choosers', 'fair_kind_choosers']):
            expressions.append(f'count(*) FILTER(WHERE (presence_bits & {1 << (4*i+offset)})<>0) AS {name}')
        parts.append('SELECT '+','.join(expressions)+' FROM '+view)
    return ' UNION ALL '.join(parts)
