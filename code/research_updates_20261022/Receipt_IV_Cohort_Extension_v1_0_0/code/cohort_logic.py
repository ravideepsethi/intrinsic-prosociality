"""Exact observed-adjacency compression and explicit three-valued membership."""
from common import *
import sys
sys.path.insert(0,str(PACKAGE/'vendor'))
import rematch_logic

EVENTS='game_id,user_id,opponent_id,utc_ms,archive_ordinal'

def compress_sql(events='selected'):
    # Full event sequences are kept for every user-month containing a target.
    # In other source-file/month segments, the first/last TWO events preserve
    # both adjacent IDs and the second-neighbour time needed for tie ambiguity.
    return f'''SELECT {EVENTS} FROM {events} WHERE has_target_month
      UNION ALL SELECT {EVENTS} FROM (
        SELECT *,row_number() OVER(PARTITION BY user_id ORDER BY utc_ms,archive_ordinal,game_id) lo,
          row_number() OVER(PARTITION BY user_id ORDER BY utc_ms DESC,archive_ordinal DESC,game_id DESC) hi
        FROM {events} WHERE NOT has_target_month) WHERE lo<=2 OR hi<=2'''

def membership_sql(source='s',adjacency='a'):
    return f'''CASE WHEN {source}.source_status<>'recovered' OR {source}.source IS NULL THEN NULL
        WHEN {source}.source<>'pool' THEN FALSE
        WHEN {adjacency}.previous_classification_status='not_mutually_adjacent_observed' THEN TRUE
        WHEN {adjacency}.previous_classification_status='mutual_adjacency_candidate_timing_unresolved' THEN FALSE
        ELSE NULL END'''

def source_reduce_sql():
    return '''SELECT game_id,count(*) evidence_rows,count(DISTINCT source) distinct_sources,
        min(source) candidate_source,bool_or(invalid) invalid,
        bool_or(status IS NOT NULL AND status<>'timeout') status_bad,
        bool_or(source IS NOT NULL AND status='timeout' AND created_at_ms IS NOT NULL) structured_label,
        count(DISTINCT winner) FILTER(WHERE winner_present)
          + max(CASE WHEN winner_present AND winner IS NULL THEN 1 ELSE 0 END) winner_values,
        bool_or(winner_present) winner_observed,min(winner) raw_winner,
        count(DISTINCT created_at_ms) time_values,min(created_at_ms) created_at_ms,
        min(provenance) FILTER(WHERE source IS NOT NULL) source_provenance
      FROM evidence GROUP BY game_id'''

def source_classify_sql(allowed):
    codes=','.join(lit(x) for x in allowed)
    return f'''WITH joined AS (
      SELECT t.game_id,t.month,r.candidate_source,r.source_provenance,
        coalesce(r.evidence_rows,0) evidence_rows,coalesce(r.distinct_sources,0) distinct_sources,
        CASE WHEN r.distinct_sources>1 THEN 'conflict'
          WHEN coalesce(r.invalid,false) THEN 'invalid_record'
          WHEN coalesce(r.distinct_sources,0)=0 THEN 'missing'
          WHEN r.candidate_source NOT IN ({codes}) THEN 'unrecognized'
          WHEN r.structured_label IS NOT TRUE THEN 'unverified_record_structure'
          WHEN r.status_bad OR r.winner_values>1 OR r.time_values>1
            OR (r.winner_observed AND r.raw_winner IS DISTINCT FROM t.expected_winner)
            OR (t.api_created_at_ms IS NOT NULL AND r.created_at_ms<>t.api_created_at_ms)
            OR (t.api_created_at_ms IS NULL AND floor(r.created_at_ms/1000)<>floor(t.utc_ms/1000))
            THEN 'inconsistent_metadata' ELSE 'recovered' END source_status
      FROM targets t LEFT JOIN recovered r USING(game_id))
      SELECT game_id,month,CASE WHEN source_status='recovered' THEN candidate_source END AS source,
        CASE WHEN source_status='recovered' THEN source_provenance END source_provenance,
        source_status,evidence_rows,distinct_sources FROM joined'''
