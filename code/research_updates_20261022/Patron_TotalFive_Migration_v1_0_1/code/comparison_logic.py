"""Pure SQL fragments used by the full-denominator comparison audit."""
def total_count_query(frame,people='people',pairs='pairs'):
    return ('SELECT f.*,(coalesce(j.n,0)-coalesce(p.n,0))::BIGINT total_pair_excluded_decisions FROM '+frame+
            ' f LEFT JOIN '+people+' j ON f.opponent_id=j.j LEFT JOIN '+pairs+' p ON f.opponent_id=p.j AND f.recipient_id=p.i')

def metadata_query():
    return """SELECT game_id,CASE
        WHEN bool_or(metadata_status='PREVIOUS_FRAME_REUSE') THEN 'PREVIOUS_FRAME_REUSE_REQUIRES_PREELIGIBILITY_SOURCE'
        WHEN bool_or(metadata_status IN ('CACHE_CONFLICT_OR_PRIOR_FLAG','CACHE_METADATA_INCOMPLETE_OR_INVALID')) THEN 'REVIEW_CACHE_FLAGS_OR_INVALID'
        WHEN (bool_or(metadata_status='CACHED_NONPOOL') AND bool_or(metadata_status='CACHED_POOL_METADATA'))
          OR count(DISTINCT fingerprint) FILTER(WHERE metadata_status='CACHED_POOL_METADATA')>1 THEN 'CROSS_CACHE_CONFLICT'
        WHEN bool_or(metadata_status='CACHED_POOL_METADATA') THEN 'CACHED_POOL_METADATA'
        WHEN bool_or(metadata_status='CACHED_NONPOOL') THEN 'CACHED_NONPOOL'
        ELSE 'MISSING_OR_UNRESOLVED_METADATA' END status
        FROM statuses GROUP BY game_id"""
