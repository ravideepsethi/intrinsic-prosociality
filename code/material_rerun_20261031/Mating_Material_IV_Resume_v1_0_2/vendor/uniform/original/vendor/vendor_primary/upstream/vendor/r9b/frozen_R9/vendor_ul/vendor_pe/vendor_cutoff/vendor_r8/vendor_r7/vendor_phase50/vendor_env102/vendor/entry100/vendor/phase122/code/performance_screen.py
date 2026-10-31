"""Outcome-independent eligibility before costly chronological/behavior features.

All original rows remain for the independent reconstruction check. Every new
query is retained in the disposition Parquets even when its features are not
computed. The full selected-exposure stream defines cooldown, unchanged.
"""
from cached_common import *

def shards(query,tmp,prefix,column,old_only=False):
    q=io.read(query)
    if old_only:q=q.filter(q['previous_frame'])
    values=io.arr(q,column)
    bucket=num.user_hash(values)%np.uint64(16) if prefix=='score' else values%16
    for s in range(16):io.table(tmp/f'{prefix}_{s:02}.parquet',q.filter(pa.array(bucket==s)))

def cheap(queries,stream,ids,root,conf,memory):
    def build(tmp):
        q=arrays(io.read(queries,['row_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','tc_base_s','expected_n7','previous_frame']))
        risk=design.prospective_risk(arrays(io.read(stream)),q,90)
        old=q['previous_frame'].astype(bool)
        reasons=np.full(len(old),'KEEP',dtype='U40')
        for label,ok in [('prior_history_97d',q['archive_start_ms']-97*DAY>=int(STARTS[0])),
                         ('real_time',q['tc_base_s']>0),('prior_count_floor5',q['expected_n7']>=5),
                         ('full_stream_cooldown_90d',risk['at_risk']),
                         ('author_focal_game',~authors.author_mask(q['recipient_id'],q['opponent_id'],ids))]:
            reasons[(reasons=='KEEP')&~ok&~old]=label
        reasons[old]='LEGACY_VERIFICATION';keep=(reasons=='KEEP')|old
        io.table(tmp/'dispositions.parquet',pa.table(dict(row_id=q['row_id'],keep=keep,reason=reasons,at_risk_90=risk['at_risk'])))
        c=io.conn(tmp/'spill',memory,1)
        try:
            io.copy(c,'SELECT q.* FROM '+io.parq([queries])+' q JOIN '+io.parq([tmp/'dispositions.parquet'])+' d USING(row_id) WHERE d.keep ORDER BY row_id',tmp/'queries.parquet')
        finally:finish_connection(c,tmp/'spill')
        shards(tmp/'queries.parquet',tmp,'score','opponent_id')
        shards(tmp/'queries.parquet',tmp,'old_outcome','recipient_id',True)
        labels,counts=np.unique(reasons,return_counts=True)
        info=dict(total_queries=len(old),legacy_rows=int(old.sum()),new_rows_kept=int((keep&~old).sum()),new_rows_skipped=int((~keep).sum()),
            dispositions=dict(zip(labels.tolist(),counts.tolist())),no_outcome_used=True,full_exposure_stream_preserved=True)
        io.js(tmp/'summary.json',info);return info
    return stable_stage(root,conf,build,[queries,stream])

def supported(queries,scorepaths,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries]))
            c.execute('CREATE VIEW s AS SELECT * FROM '+io.parq(scorepaths))
            query='SELECT q.row_id,q.previous_frame OR (s.n_7d>=5 AND isfinite(s.adjusted_7d) AND isfinite(s.expected_7d)) AS keep FROM q JOIN s USING(row_id)'
            assert_rows(c,query,pq.ParquetFile(queries).metadata.num_rows,'Early score support')
            io.copy(c,query,tmp/'dispositions.parquet')
            io.copy(c,'SELECT q.* FROM q JOIN '+io.parq([tmp/'dispositions.parquet'])+' d USING(row_id) WHERE d.keep ORDER BY row_id',tmp/'queries.parquet')
            n=io.copy(c,'SELECT * FROM '+io.parq([tmp/'queries.parquet'])+' WHERE NOT previous_frame',tmp/'chron_queries.parquet')
            skipped=c.execute('SELECT count(*) FROM '+io.parq([tmp/'dispositions.parquet'])+' WHERE NOT keep').fetchone()[0]
            info=dict(new_chronology_queries=n,new_rows_without_score_support=skipped,no_outcome_used=True)
            io.js(tmp/'summary.json',info);return info
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[queries]+scorepaths)

def after_chronology(queries,chron,root,conf,memory,entrypath=None):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries]))
            c.execute('CREATE VIEW x AS SELECT * FROM '+io.parq([chron]))
            if entrypath:
                bad=c.execute('SELECT count(*) FROM q JOIN x USING(row_id) JOIN '+io.parq([entrypath])+' e USING(row_id) WHERE NOT q.previous_frame AND e.matched_main AND NOT x.eligible_main').fetchone()[0]
                if bad:raise RuntimeError('Main panel and recomputed adjacency disagree before eligibility filtering')
            query='SELECT q.row_id,q.previous_frame OR (x.eligible_main AND x.first_observed_pair) AS keep,x.previous_classification_status,x.first_observed_pair FROM q LEFT JOIN x USING(row_id)'
            assert_rows(c,query,pq.ParquetFile(queries).metadata.num_rows,'Chronology eligibility')
            if c.execute('SELECT count(*) FROM ('+query+') WHERE keep IS NULL').fetchone()[0]:raise RuntimeError('Missing chronological eligibility')
            io.copy(c,query,tmp/'dispositions.parquet')
            io.copy(c,'SELECT q.* FROM q JOIN '+io.parq([tmp/'dispositions.parquet'])+' d USING(row_id) WHERE d.keep ORDER BY row_id',tmp/'queries.parquet')
            rows=c.execute('SELECT count(*) FROM '+io.parq([tmp/'queries.parquet'])).fetchone()[0]
            skipped=c.execute('SELECT count(*) FROM '+io.parq([tmp/'dispositions.parquet'])+' WHERE NOT keep').fetchone()[0]
            info=dict(feature_queries=rows,new_rows_skipped_by_chronology=skipped,no_outcome_used=True)
        finally:finish_connection(c,tmp/'spill')
        shards(tmp/'queries.parquet',tmp,'outcome','recipient_id')
        io.js(tmp/'summary.json',info);return info
    return stable_stage(root,conf,build,[queries,chron]+([entrypath] if entrypath else []))
