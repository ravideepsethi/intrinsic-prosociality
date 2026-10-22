"""One projected all-game pass; reduce each file to query-level sufficient statistics.

Avoid writing and globally sorting billions of individual player-game moments.
The original adjudication of ties, missing predecessors and mutual adjacency is
unchanged. Per-file volumes add, earliest pair times take minima, and predecessor
candidates combine with the original adjacency_final_sql implementation.
"""
from cached_common import *
from cached_chronology import prepare_chronology

def chronology_job(job):
    threads_one()
    if io.sig(job['path'])!=job['signature']:raise RuntimeError('Chronology changed since authentication')
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW wanted AS SELECT * FROM '+io.parq([job['people']]))
            c.execute('CREATE TEMP TABLE e AS SELECT game_id,utc_ms,white_id,black_id FROM '+io.parq([job['path']])+f" WHERE utc_ms>0 AND utc_ms<={job['latest']} AND white_id>=0 AND black_id>=0 AND white_id<4294967296 AND black_id<4294967296 AND white_id<>black_id AND (white_id IN (SELECT user_id FROM wanted) OR black_id IN (SELECT user_id FROM wanted))")
            c.execute('CREATE TEMP TABLE found_focal AS SELECT e.game_id,count(*)::BIGINT matches FROM e JOIN '+io.parq([job['focal']])+''' q
                ON e.game_id=q.game_id AND e.utc_ms=q.archive_start_ms
                AND least(e.white_id,e.black_id)=least(q.recipient_id,q.opponent_id)
                AND greatest(e.white_id,e.black_id)=greatest(q.recipient_id,q.opponent_id) GROUP BY 1''')
            pair='least(white_id,black_id)::UBIGINT*4294967296+greatest(white_id,black_id)::UBIGINT'
            io.copy(c,'SELECT '+pair+' AS pair_key,min(utc_ms)::BIGINT AS first_t FROM e SEMI JOIN '+io.parq([job['pairs']])+' p ON '+pair+'=p.pair_key GROUP BY 1',tmp/'pairs.parquet')
            c.execute('''CREATE TEMP TABLE moments AS WITH ep AS (
                SELECT e.game_id,e.utc_ms,e.white_id AS user_id,e.black_id AS opponent_id FROM e JOIN wanted w ON e.white_id=w.user_id AND e.utc_ms<=w.maximum_start
                UNION ALL
                SELECT e.game_id,e.utc_ms,e.black_id AS user_id,e.white_id AS opponent_id FROM e JOIN wanted w ON e.black_id=w.user_id AND e.utc_ms<=w.maximum_start
              ), counts AS (SELECT user_id,utc_ms,count(*)::BIGINT multiplicity,min(game_id) gid,min(opponent_id)::BIGINT opponent_id FROM ep GROUP BY 1,2)
              SELECT *,sum(multiplicity) OVER(PARTITION BY user_id ORDER BY utc_ms ROWS UNBOUNDED PRECEDING)::BIGINT cumulative FROM counts''')
            c.execute('CREATE TEMP TABLE present AS SELECT user_id,min(utc_ms) minimum_t FROM moments GROUP BY 1')
            c.execute('CREATE VIEW roles AS SELECT r.* FROM '+io.parq([job['roles']])+' r JOIN present p ON r.user_id=p.user_id AND r.archive_start_ms>=p.minimum_t')
            query=f'''SELECT r.sample_row,r.role,p.utc_ms prev_t,p.multiplicity prev_count,p.gid prev_gid,p.opponent_id prev_opponent,
                coalesce(x.multiplicity,0)::BIGINT focal_time_count,coalesce(f.matches,0)::BIGINT focal_matches,
                CASE WHEN r.role=0 THEN coalesce(p.cumulative,0)-coalesce(lo.cumulative,0) ELSE 0 END::BIGINT pre_games_30d
              FROM roles r ASOF LEFT JOIN moments p ON r.user_id=p.user_id AND r.archive_start_ms>p.utc_ms
              ASOF LEFT JOIN moments lo ON r.user_id=lo.user_id AND r.archive_start_ms-{30*DAY}>lo.utc_ms
              LEFT JOIN moments x ON r.user_id=x.user_id AND r.archive_start_ms=x.utc_ms
              LEFT JOIN found_focal f ON r.game_id=f.game_id'''
            n=io.copy(c,query,tmp/'candidates.parquet')
            return dict(input_rows=job['rows'],retained_query_roles=n,file_index=job['file_index'])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job[k] for k in ('path','people','pairs','focal','roles')])[1]

def merge_chronology(queries,prepared,parts,root,conf,memory,workers):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,workers)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries])+' WHERE NOT previous_frame')
            c.execute('CREATE VIEW candidates AS SELECT * FROM '+io.parq([p/'candidates.parquet' for p in parts]))
            c.execute('CREATE VIEW focal AS SELECT row_id sample_row,recipient_id,opponent_id FROM q')
            c.execute('CREATE TEMP TABLE classifications AS '+rebuild.adjacency_final_sql('candidates','focal'))
            c.execute('CREATE TEMP TABLE pairs AS SELECT pair_key,min(first_t)::BIGINT first_t FROM '+io.parq([p/'pairs.parquet' for p in parts])+' GROUP BY 1')
            c.execute('CREATE TEMP TABLE volume AS SELECT sample_row,sum(pre_games_30d)::BIGINT pre_games_30d FROM candidates WHERE role=0 GROUP BY 1')
            pair='least(q.recipient_id,q.opponent_id)::UBIGINT*4294967296+greatest(q.recipient_id,q.opponent_id)::UBIGINT'
            query=f'''SELECT q.row_id,s.previous_classification_status,
                s.previous_classification_status={io.lit(rebuild.NONADJ)} AS eligible_main,
                (p.first_t=q.archive_start_ms) AS first_observed_pair,coalesce(v.pre_games_30d,0)::BIGINT pre_games_30d
              FROM q JOIN classifications s ON q.row_id=s.sample_row LEFT JOIN pairs p ON {pair}=p.pair_key
              LEFT JOIN volume v ON q.row_id=v.sample_row'''
            n=c.execute('SELECT count(*) FROM q').fetchone()[0];assert_rows(c,query,n,'Chronology')
            bad=c.execute('SELECT count(*) FROM ('+query+') WHERE first_observed_pair IS NULL OR pre_games_30d<0').fetchone()[0]
            if bad:raise RuntimeError('Focal game absent from canonical pair chronology or invalid volume')
            io.copy(c,query,tmp/'features.parquet')
            counts=[dict(classification=k,rows=n) for k,n in c.execute('SELECT previous_classification_status,count(*) FROM classifications GROUP BY 1').fetchall()]
            return dict(rows=n,classifications=counts,factual_author_games_preserved=True,per_file_query_reduction=True)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[queries,prepared/'roles.parquet']+[p/name for p in parts for name in ('candidates.parquet','pairs.parquet')])
