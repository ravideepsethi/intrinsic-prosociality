"""Restore fields omitted by the authenticated historical normalize() producer.

The normalized comparison retained y/reached but dropped all four later-game
identifiers. Recover those from its hash-pinned parent, never from invented
sentinels or from the new reconstruction that they will independently check.
"""
from cached_common import *

DETAILS=['outcome_gid','outcome_t','outcome_start','outcome_opponent']
SHARED=['game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms',
        'month_code','recipient_rating','opponent_rating','tc_base_s','tc_inc_s',
        'complete90','y','reached','n_7d','counterparts_7d','expected_7d','adjusted_7d']

def require_columns(path,required,label):
    schema=pq.ParquetFile(path).schema_arrow
    missing=sorted(set(required)-set(schema.names))
    if missing:raise RuntimeError(label+' missing required columns: '+', '.join(missing))
    return schema

def authenticate_parent(project):
    authority=io.load(PACKAGE/'evidence/legacy_outcome_authority.json')
    root=io.child(project,authority['root_relative'])
    if io.cfgsha(io.load(root/'config.json'))!=authority['config_sha256']:
        raise RuntimeError('Original outcome parent has a different configuration')
    path=io.child(root,authority['relative_path'])
    io.checked(path,authority['sha256'],authority['bytes'])
    if pq.ParquetFile(path).metadata.num_rows!=authority['rows']:
        raise RuntimeError('Original outcome parent row count changed')
    require_columns(path,SHARED+DETAILS,'Original outcome parent')
    return dict(path=str(path),sha256=authority['sha256'],bytes=authority['bytes'],
                config_sha256=authority['config_sha256'])

def preflight(source,parent,required):
    schema=require_columns(source,set(required)-set(DETAILS),'Normalized original comparison')
    missing=[k for k in DETAILS if k not in schema.names]
    if missing:
        if not parent:raise RuntimeError('Original later-game fields require the authenticated parent: '+', '.join(missing))
        require_columns(parent,SHARED+DETAILS,'Original outcome parent')
    return dict(source_columns=schema.names,missing_later_game_fields=missing,
                recovery='authenticated_parent_join' if missing else 'already_present')

def restore(baseline,parent,tmp,memory):
    missing=[k for k in DETAILS if k not in baseline]
    if not missing:return baseline,dict(restored_columns=[],verified_rows=0)
    if not parent:raise RuntimeError('Missing authenticated original outcome parent')
    c=io.conn(tmp/'legacy_spill',memory,1)
    try:
        c.register('baseline',pa.table({k:baseline[k] for k in ['row_id']+SHARED}))
        c.execute('CREATE VIEW parent AS SELECT * FROM '+io.parq([parent]))
        joined='FROM baseline b LEFT JOIN parent p USING(game_id,recipient_id)'
        # Materialize one projected join; validation must not rescan the parent
        # separately for every shared field on an external SSD.
        checks=['(b.'+k+' IS DISTINCT FROM p.'+k+') AS mismatch_'+k for k in SHARED]
        c.execute('CREATE TEMP TABLE parent_matches AS SELECT b.row_id,p.game_id AS parent_game_id,'+
                  ','.join(['p.'+k for k in DETAILS]+checks)+' '+joined)
        query='SELECT row_id,'+','.join(DETAILS)+' FROM parent_matches'
        assert_rows(c,query,len(baseline['row_id']),'Original outcome parent join')
        bad=c.execute('SELECT count(*) FROM parent_matches WHERE parent_game_id IS NULL').fetchone()[0]
        if bad:raise RuntimeError('Original outcome parent is missing '+str(bad)+' focal rows')
        # Compare shared source values before accepting ANY recovered detail.
        counts=c.execute('SELECT '+','.join('count(*) FILTER(WHERE mismatch_'+k+')' for k in SHARED)+' FROM parent_matches').fetchone()
        disagreed=[k for k,n in zip(SHARED,counts) if n]
        if disagreed:raise RuntimeError('Original outcome parent disagrees on '+', '.join(disagreed))
        restored=arrays(c.execute(query+' ORDER BY row_id').to_arrow_table())
        if not np.array_equal(restored['row_id'],baseline['row_id']):raise RuntimeError('Original outcome recovery changed row order')
        all_known(restored,DETAILS)
        for name in DETAILS:
            if name in baseline and not np.array_equal(baseline[name],restored[name]):
                raise RuntimeError('Existing original outcome detail disagrees with parent: '+name)
        result=dict(baseline)
        for name in missing:result[name]=restored[name]
        return result,dict(restored_columns=missing,verified_rows=len(baseline['row_id']),
            matched_by=['game_id','recipient_id'],shared_columns_verified=SHARED,
            fabricated_values=0,independent_parent_details_preserved=True)
    finally:finish_connection(c,tmp/'legacy_spill')
