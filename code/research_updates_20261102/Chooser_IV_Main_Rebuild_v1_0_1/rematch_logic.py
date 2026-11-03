"""Portable SQL for start-chronology adjacency (not verified end-to-start rematches).

Used unchanged by DuckDB production and SQLite logic tests. Windows always see
ALL events for the selected users, across dates and speed categories, before
filtering to the focal game set.
"""
from __future__ import annotations


def side_query(events: str = 'ev', targets: str = 'targets') -> str:
    return f'''
    SELECT s.game_id, s.user_id, s.opponent_id, s.utc_ms, s.archive_ordinal,
           s.prev_game_id, s.prev_opponent_id, s.prev_start_ms, s.prev2_start_ms,
           s.next_game_id, s.next_opponent_id, s.next_start_ms, s.next2_start_ms
    FROM (
      SELECT e.*,
             LAG(game_id) OVER w AS prev_game_id,
             LAG(opponent_id) OVER w AS prev_opponent_id,
             LAG(utc_ms) OVER w AS prev_start_ms,
             LAG(utc_ms, 2) OVER w AS prev2_start_ms,
             LEAD(game_id) OVER w AS next_game_id,
             LEAD(opponent_id) OVER w AS next_opponent_id,
             LEAD(utc_ms) OVER w AS next_start_ms,
             LEAD(utc_ms, 2) OVER w AS next2_start_ms
      FROM {events} e
      WINDOW w AS (PARTITION BY user_id ORDER BY utc_ms, archive_ordinal, game_id)
    ) s
    INNER JOIN {targets} t ON t.game_id=s.game_id AND t.user_id=s.user_id
    '''


def census_query(focal: str = 'f', sides: str = 'sides') -> str:
    """LEFT joins ensure that even a focal game missing BOTH sides is retained.

    A positive flag requires two matched focal sides, two non-null neighbour
    IDs, agreement on the neighbour, reciprocal opponents and equal neighbour
    start times. Ambiguous chronology ordering and boundary cases are NULL.
    """
    return f'''
    WITH paired AS (
      SELECT f.game_id, f.p1, f.p2,
        a.utc_ms AS p1_focal_start_ms, b.utc_ms AS p2_focal_start_ms,
        a.prev_game_id AS p1_prev_game_id, b.prev_game_id AS p2_prev_game_id,
        a.prev_start_ms AS p1_prev_start_ms, b.prev_start_ms AS p2_prev_start_ms,
        a.next_game_id AS p1_next_game_id, b.next_game_id AS p2_next_game_id,
        a.next_start_ms AS p1_next_start_ms, b.next_start_ms AS p2_next_start_ms,
        CASE WHEN a.game_id IS NOT NULL AND b.game_id IS NOT NULL
                   AND a.opponent_id=f.p2 AND b.opponent_id=f.p1
                   AND a.utc_ms=b.utc_ms THEN TRUE ELSE FALSE END AS focal_mapping_ok,
        CASE WHEN a.prev_game_id IS NOT NULL AND b.prev_game_id IS NOT NULL
                   AND a.prev_game_id=b.prev_game_id
                   AND a.prev_opponent_id=f.p2 AND b.prev_opponent_id=f.p1
                   AND a.prev_start_ms=b.prev_start_ms THEN TRUE ELSE FALSE END AS raw_prev_match,
        CASE WHEN a.next_game_id IS NOT NULL AND b.next_game_id IS NOT NULL
                   AND a.next_game_id=b.next_game_id
                   AND a.next_opponent_id=f.p2 AND b.next_opponent_id=f.p1
                   AND a.next_start_ms=b.next_start_ms THEN TRUE ELSE FALSE END AS raw_next_match,
        CASE WHEN a.prev_start_ms=a.utc_ms OR a.next_start_ms=a.utc_ms
                   OR b.prev_start_ms=b.utc_ms OR b.next_start_ms=b.utc_ms
                   OR a.prev2_start_ms=a.prev_start_ms
                   OR b.prev2_start_ms=b.prev_start_ms
             THEN TRUE ELSE FALSE END AS previous_start_order_ambiguous,
        CASE WHEN a.prev_start_ms=a.utc_ms OR a.next_start_ms=a.utc_ms
                   OR b.prev_start_ms=b.utc_ms OR b.next_start_ms=b.utc_ms
                   OR a.next2_start_ms=a.next_start_ms
                   OR b.next2_start_ms=b.next_start_ms
             THEN TRUE ELSE FALSE END AS next_start_order_ambiguous
      FROM {focal} f
      LEFT JOIN {sides} a ON a.game_id=f.game_id AND a.user_id=f.p1
      LEFT JOIN {sides} b ON b.game_id=f.game_id AND b.user_id=f.p2
    ), flags AS (
      SELECT *,
        CASE WHEN focal_mapping_ok THEN p1_focal_start_ms END AS focal_start_ms,
        CASE WHEN focal_mapping_ok AND raw_prev_match THEN TRUE ELSE FALSE END AS mutual_previous_observed,
        CASE WHEN focal_mapping_ok AND raw_next_match THEN TRUE ELSE FALSE END AS mutual_next_observed,
        CASE WHEN NOT focal_mapping_ok OR previous_start_order_ambiguous
                    OR p1_prev_game_id IS NULL OR p2_prev_game_id IS NULL
             THEN NULL ELSE raw_prev_match END AS mutual_previous_same_pair,
        CASE WHEN NOT focal_mapping_ok OR next_start_order_ambiguous
                    OR p1_next_game_id IS NULL OR p2_next_game_id IS NULL
             THEN NULL ELSE raw_next_match END AS mutual_next_same_pair
      FROM paired
    )
    SELECT game_id, p1, p2, focal_start_ms, focal_mapping_ok,
      p1_prev_game_id, p2_prev_game_id, p1_prev_start_ms, p2_prev_start_ms,
      p1_next_game_id, p2_next_game_id, p1_next_start_ms, p2_next_start_ms,
      mutual_previous_observed, mutual_next_observed,
      previous_start_order_ambiguous, next_start_order_ambiguous,
      mutual_previous_same_pair, mutual_next_same_pair,
      CASE WHEN mutual_previous_observed THEN p1_prev_game_id END AS previous_game_id,
      CASE WHEN mutual_next_observed THEN p1_next_game_id END AS next_game_id,
      CASE WHEN mutual_previous_observed THEN focal_start_ms-p1_prev_start_ms END
          AS predecessor_start_to_focal_start_ms,
      CASE WHEN mutual_next_observed THEN p1_next_start_ms-focal_start_ms END
          AS focal_start_to_successor_start_ms,
      CASE WHEN NOT focal_mapping_ok THEN 'unmapped_or_inconsistent_focal'
           WHEN previous_start_order_ambiguous THEN 'ambiguous_start_order'
           WHEN p1_prev_game_id IS NULL OR p2_prev_game_id IS NULL THEN 'left_boundary_unresolved'
           WHEN raw_prev_match THEN 'mutual_adjacency_candidate_timing_unresolved'
           ELSE 'not_mutually_adjacent_observed' END AS previous_classification_status,
      CASE WHEN NOT focal_mapping_ok THEN 'unmapped_or_inconsistent_focal'
           WHEN next_start_order_ambiguous THEN 'ambiguous_start_order'
           WHEN p1_next_game_id IS NULL OR p2_next_game_id IS NULL THEN 'right_boundary_unresolved'
           WHEN raw_next_match THEN 'mutual_adjacency_candidate_timing_unresolved'
           ELSE 'not_mutually_adjacent_observed' END AS next_classification_status
    FROM flags
    '''
