"""Count dynamic and profile support without changing the receipt estimand."""
from __future__ import annotations

from pathlib import Path
from common import *
from analysis import open_data

SNAPSHOT_SHA='f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'

def next_fair_support(con):
    """Next *all-source* fair opportunity, never next arena after skipping pool.

    API lastMoveAt is only a last-move proxy. Requiring target start greater than
    exposure lastMoveAt gives a support upper bound, not certified post-resolution
    causal ordering. Duplicate event times are counted and excluded, not broken
    with game IDs. This module does not estimate receipt effects.
    """
    con.execute("""CREATE TEMP TABLE exposure_candidates AS SELECT game_id,opponent AS recipient,
      last_move_ms,kind AS received_kind,source FROM eligible
      WHERE source='arena' AND (kind=1 OR claimed) AND last_move_ms IS NOT NULL""")
    con.execute('''CREATE TEMP TABLE exposures AS SELECT * EXCLUDE(tied) FROM
      (SELECT *,count(*) OVER(PARTITION BY recipient,last_move_ms) AS tied FROM exposure_candidates)
      WHERE tied=1''')
    con.execute('''CREATE TEMP TABLE fair_target_candidates AS SELECT game_id,chooser AS recipient,
      start_ms,source AS target_source,previous_status AS target_previous_status,kind AS target_kind
      FROM all_opps WHERE eval>=-100 AND chooser IN (SELECT DISTINCT recipient FROM exposures)''')
    con.execute('''CREATE TEMP TABLE fair_targets AS SELECT * EXCLUDE(tied) FROM
      (SELECT *,count(*) OVER(PARTITION BY recipient,start_ms) AS tied FROM fair_target_candidates)
      WHERE tied=1''')
    # Ambiguous earliest target must remain unresolved rather than be skipped.
    con.execute('''CREATE TEMP TABLE first_target_times AS
      SELECT DISTINCT recipient,start_ms FROM fair_target_candidates''')
    con.execute('''CREATE TEMP TABLE next_targets AS
      SELECT e.*,t.start_ms AS next_start_ms,f.game_id AS target_id,
        f.target_source,f.target_previous_status,f.target_kind
      FROM exposures e ASOF LEFT JOIN first_target_times t
        ON e.recipient=t.recipient AND e.last_move_ms<t.start_ms
      LEFT JOIN fair_targets f ON f.recipient=e.recipient AND f.start_ms=t.start_ms''')
    return {
      'exposure_candidates':con.execute('SELECT count(*) FROM exposure_candidates').fetchone()[0],
      'exposures_after_tie_exclusion':con.execute('SELECT count(*) FROM exposures').fetchone()[0],
      'ambiguous_earliest_target':con.execute('SELECT count(*) FROM next_targets WHERE next_start_ms IS NOT NULL AND target_id IS NULL').fetchone()[0],
      'same_start_as_exposure_last_move':con.execute('''SELECT count(*) FROM exposures e
        WHERE EXISTS(SELECT 1 FROM fair_target_candidates f WHERE f.recipient=e.recipient AND f.start_ms=e.last_move_ms)''').fetchone()[0],
    }

def run_support(run,project,memory,threads):
    con,build=open_data(run,memory,threads)
    out=Path(run)/'public/support';out.mkdir(parents=True,exist_ok=True)
    log('Counting receipt transitions using all sources for intervening fair opportunities')
    timing=next_fair_support(con)
    write_table(con, f'''SELECT received_kind,
      CASE WHEN next_start_ms IS NULL THEN 'no_later_observed_fair_opportunity'
           WHEN target_id IS NULL THEN 'earliest_target_time_ambiguous'
           ELSE target_source END AS next_fair_source,
      target_previous_status,
      count(*) AS exposures,count(DISTINCT recipient) AS recipients,
      count(*) FILTER(WHERE target_id IS NOT NULL AND next_start_ms-last_move_ms<=7776000000::BIGINT) AS linked_within_90d,
      count(*) FILTER(WHERE target_id IS NOT NULL AND target_kind=1 AND next_start_ms-last_move_ms<=7776000000::BIGINT) AS later_grants_within_90d
      FROM next_targets GROUP BY 1,2,3''',out/'receipt_transition_support')
    json_write(out/'receipt_design_status.json',{
      'status':'SUPPORT_COUNTS_ONLY','input_contract':build['contract'],'timing_diagnostics':timing,
      'ordering':'Next observed fair opportunity across ALL sources; pool targets are never skipped to find an arena target.',
      'exposure':'Arena, observed nonadjacency; recorded kind grant or chooser win; all board states.',
      'time_limitation':'lastMoveAt is a proxy, not certified resolution time. These are candidate support counts, not an A1 sample or receipt estimates.',
      'intervening_histories':'All 47,587,020 active opportunities retained for target ordering. Ordinary games and passive endings are not in this support table.',
      'next_steps':['Rebuild the frozen A1 exposure cells, eligibility, overlap and censoring rules on the desired arena design.',
                    'Recover the authenticated instrument construction and evaluate arena assignment separately.'],
      'receipt_estimated':False,'iv_estimated':False,'causal_identification_certified':False})
    con.execute('''CREATE TEMP TABLE arena_choosers AS SELECT username,
      count(*) AS n,sum(kind) AS k,count(*) FILTER(WHERE eval>=-100) AS fair_n,
      count(*) FILTER(WHERE eval>=-100 AND kind=1) AS fair_k,
      count(*) FILTER(WHERE eval<=-300) AS losing_n,
      count(*) FILTER(WHERE eval<=-300 AND kind=1) AS losing_k
      FROM eligible WHERE source='arena' GROUP BY username''')
    snapshot=Path(project)/'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
    if not snapshot.is_file():
        json_write(out/'patron_status.json',{'status':'SNAPSHOT_NOT_AVAILABLE','profile_counts_unknown':True,
                   'expected_snapshot_sha256':SNAPSHOT_SHA,'patron_estimated':False})
    else:
        log('Authenticating fixed August Patron snapshot and counting arena coverage')
        require(sha(snapshot)==SNAPSHOT_SHA,'Patron snapshot differs from the certified August snapshot')
        con.execute('CREATE VIEW profiles AS SELECT username_norm,returned,patron FROM '+parquet(snapshot))
        n,unique,returned,patrons=con.execute('''SELECT count(*),count(DISTINCT username_norm),
          count(*) FILTER(WHERE returned),count(*) FILTER(WHERE returned AND patron) FROM profiles''').fetchone()
        require((n,unique,returned,patrons)==(1305872,1305872,1305683,4896),'Patron snapshot margins changed')
        write_table(con,'''SELECT CASE WHEN a.fair_k>0 THEN 'arena_competitive_granter'
          WHEN a.k>0 THEN 'arena_other_state_granter' ELSE 'no_arena_grants' END AS arena_group,
          CASE WHEN a.fair_n<4 THEN 'fewer_than_4_fair_opportunities' ELSE 'at_least_4_fair_opportunities' END AS support,
          count(*) AS accounts,count(*) FILTER(WHERE p.username_norm IS NOT NULL) AS in_snapshot,
          count(*) FILTER(WHERE p.returned) AS returned_profiles,
          count(*) FILTER(WHERE p.returned AND p.patron) AS patrons,
          count(*) FILTER(WHERE p.username_norm IS NULL) AS unqueried_in_august,
          count(*) FILTER(WHERE p.username_norm IS NOT NULL AND NOT p.returned) AS nonreturned_profiles
          FROM arena_choosers a LEFT JOIN profiles p ON p.username_norm=a.username GROUP BY 1,2''',out/'patron_coverage')
        json_write(out/'patron_status.json',{'status':'CERTIFIED_AUGUST_SNAPSHOT_SUPPORT_COUNTED',
          'snapshot_sha256':SNAPSHOT_SHA,'patron_estimated':False,
          'limitation':'Coverage is selected under the original all-source acquisition design. Rebuild arena matching before estimating; no unreturned or unqueried profile is coded as non-Patron.',
          'new_profile_requests':0})
    con.close()
