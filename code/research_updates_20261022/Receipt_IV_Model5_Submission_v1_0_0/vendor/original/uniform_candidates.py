"""Derived fixed-frame candidate producer: 90-day coverage, no cooldown.
All-time scoring is the unchanged donor_job.
"""
from uniform_common import *

def candidates(a,run,conf,b):
    parts=b['local']['ledgers'];authors=b['primary']['bound']['binding']['author_ids']
    def build(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+parq(parts))
            n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM f').fetchone()
            require(n==u==cache_auth.FRAME_ROWS,'Full fixed candidate frame differs')
            # New namespace IDs do not depend on subsequent eligibility or metadata availability.
            copy_query(c,'SELECT *,4398046511104+row_number() OVER(ORDER BY game_id)::BIGINT AS row_id FROM f ORDER BY game_id',tmp/'full_frame.parquet')
            c.execute('CREATE VIEW allq AS SELECT * FROM '+parq([tmp/'full_frame.parquet']))
            ids=','.join(map(str,authors));start=int(phase_inputs.core.STARTS[0]);end=int(phase_inputs.core.PANEL_END)
            sql=f'''SELECT f.*,
                (f.recipient_id NOT IN ({ids}) AND f.opponent_id NOT IN ({ids})) AS author_clean,
                f.utc_ms-{90*DAY}>={start} AS history_complete,
                f.utc_ms+{90*DAY}<{end} AS start_calendar_complete,
                TRUE AS at_risk_90
                FROM allq f'''
            copy_query(c,sql,tmp/'dispositions.parquet')
            c.execute('CREATE VIEW d AS SELECT * FROM '+parq([tmp/'dispositions.parquet']))
            counts=[];where='TRUE'
            for label,cut in [('fixed_hash_frame','TRUE'),('phase100_additional_games','NOT previous_frame'),('author_clean','author_clean'),('history90','history_complete'),
                              ('start_calendar90','start_calendar_complete'),('no_receipt_cooldown','at_risk_90')]:
                where+=' AND '+cut;counts.append(dict(step=label,rows=c.execute('SELECT count(*) FROM d WHERE '+where).fetchone()[0]))
            # No old support field participates. Complete scores determine the remaining support.
            months='CASE '+' '.join('WHEN month='+quote(m)+f' THEN {j}' for j,m in enumerate(phase_inputs.core.MONTHS))+' END'
            copy_query(c,'SELECT row_id,game_id,recipient_id,opponent_id,utc_ms,utc_ms archive_start_ms,'+months+'''::BIGINT month_code,
                recipient_color,speed_partition,previous_frame legacy_hash_member,FALSE previous_frame,at_risk_90,
                n7_author_clean legacy_prior_count FROM d WHERE '''+where+' ORDER BY row_id',tmp/'queries.parquet')
            save(tmp/'flow.json',counts);return dict(rows=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows,full_frame_rows=n)
        finally:c.close()
    path,_=stage(run/'PRIVATE/candidates',conf,build,parts)
    save(run/'report/candidate_flow.json',load(path/'flow.json'))
    query=path/'queries.parquet';qdir=inputs.query_shards(query,run/'PRIVATE/candidate_score_queries',conf)
    base=b['primary']['bound'];jobs=[]
    for s in range(16):
        jobs.append(dict(query=str(qdir/f'{s:02}.parquet'),reference=base['reference'],authors=authors,
          parts=[p for p in base['parts'] if p['shard']==s],out=str(run/'PRIVATE/candidate_scores'/f'{s:02}.parquet'),
          key=key([conf,'alltime_before_metadata',s,sha(qdir/f'{s:02}.parquet'),sha(base['reference'])])))
    mapped(cutoffs.donor_job,jobs,min(2,a.workers),'All-time-five scores before metadata')
    scores=[j['out'] for j in jobs]
    def choose(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([query]));c.execute('CREATE VIEW s AS SELECT * FROM '+parq(scores))
            ensure_unique(c,'q');ensure_unique(c,'s')
            ensure(c,'SELECT count(*) FROM q FULL JOIN s USING(row_id) WHERE q.row_id IS NULL OR s.row_id IS NULL','Candidate scores do not cover every query')
            keep='s.n_A>=5 AND isfinite(s.adjusted_A) AND isfinite(s.expected_A)'
            copy_query(c,'SELECT q.*,'+keep+' total_five_supported FROM q JOIN s USING(row_id) ORDER BY row_id',tmp/'support_dispositions.parquet')
            copy_query(c,'SELECT q.* FROM q JOIN s USING(row_id) WHERE '+keep+' ORDER BY row_id',tmp/'queries.parquet')
            copy_query(c,'SELECT s.* FROM s JOIN q USING(row_id) WHERE '+keep+' ORDER BY row_id',tmp/'scores.parquet')
            n,added=c.execute('SELECT count(*),count(*) FILTER(WHERE legacy_prior_count<5) FROM '+parq([tmp/'queries.parquet'])).fetchone()
            return dict(supported_queries=n,previously_failed_prior_count=added,old_prior_count_used_for_selection=False)
        finally:c.close()
    dest,info=stage(run/'PRIVATE/supported',conf,choose,[query]+scores)
    save(run/'report/alltime_support.json',{k:v for k,v in info.items() if k not in ('files','dependencies')})
