"""First observed pairs, previous adjacency and factual all-game activity.

Retain per-account moments within the required interval and the last older
moment in each file. Older games still enter first-pair minima. Author games
remain in all three factual chronology calculations.
"""
from cached_common import *

def prepare_chronology(queries,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries])+' WHERE NOT previous_frame')
            io.copy(c,'SELECT game_id,archive_start_ms,recipient_id,opponent_id FROM q',tmp/'focal.parquet')
            io.copy(c,'SELECT row_id AS sample_row,recipient_id AS user_id,opponent_id,game_id,archive_start_ms,0 AS role FROM q UNION ALL SELECT row_id,opponent_id,recipient_id,game_id,archive_start_ms,1 FROM q',tmp/'roles.parquet')
            io.copy(c,'SELECT user_id,min(archive_start_ms) AS minimum_start,max(archive_start_ms) AS maximum_start FROM '+io.parq([tmp/'roles.parquet'])+' GROUP BY 1',tmp/'people.parquet')
            io.copy(c,'SELECT DISTINCT least(recipient_id,opponent_id)::UBIGINT*4294967296+greatest(recipient_id,opponent_id)::UBIGINT AS pair_key FROM q',tmp/'pairs.parquet')
            n,latest=c.execute('SELECT count(*),max(archive_start_ms) FROM q').fetchone()
            return dict(rows=n,latest_start=latest)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[queries])

def chronology_job(job):
    threads_one()
    if io.sig(job['path'])!=job['signature']:raise RuntimeError('Chronology changed since authentication')
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW wanted AS SELECT * FROM '+io.parq([job['people']]))
            # One projected Parquet pass per file. Only relevant accounts survive;
            # subsequent pair, focal and moment calculations reuse the temp table.
            c.execute('CREATE TEMP TABLE e AS SELECT game_id,utc_ms,white_id,black_id FROM '+io.parq([job['path']])+f" WHERE utc_ms>0 AND utc_ms<={job['latest']} AND white_id>=0 AND black_id>=0 AND white_id<4294967296 AND black_id<4294967296 AND white_id<>black_id AND (white_id IN (SELECT user_id FROM wanted) OR black_id IN (SELECT user_id FROM wanted))")
            io.copy(c,'SELECT e.game_id,count(*)::BIGINT matches FROM e JOIN '+io.parq([job['focal']])+''' q
                ON e.game_id=q.game_id AND e.utc_ms=q.archive_start_ms
                AND least(e.white_id,e.black_id)=least(q.recipient_id,q.opponent_id)
                AND greatest(e.white_id,e.black_id)=greatest(q.recipient_id,q.opponent_id) GROUP BY 1''',tmp/'focal.parquet')
            pair='least(white_id,black_id)::UBIGINT*4294967296+greatest(white_id,black_id)::UBIGINT'
            io.copy(c,'SELECT '+pair+' AS pair_key,min(utc_ms)::BIGINT AS first_t FROM e SEMI JOIN '+io.parq([job['pairs']])+' p ON '+pair+'=p.pair_key GROUP BY 1',tmp/'pairs.parquet')
            c.execute('''CREATE TEMP TABLE moments AS WITH ep AS (
                SELECT e.game_id,e.utc_ms,e.white_id AS user_id,e.black_id AS opponent_id FROM e JOIN wanted w ON e.white_id=w.user_id AND e.utc_ms<=w.maximum_start
                UNION ALL
                SELECT e.game_id,e.utc_ms,e.black_id AS user_id,e.white_id AS opponent_id FROM e JOIN wanted w ON e.black_id=w.user_id AND e.utc_ms<=w.maximum_start
              ) SELECT user_id,utc_ms,count(*)::BIGINT multiplicity,min(game_id) gid,min(opponent_id)::BIGINT opponent_id FROM ep GROUP BY 1,2''')
            # At most one older timestamp per person per file. Keep its true multiplicity.
            query=f'''WITH older AS (
                SELECT m.user_id,max(m.utc_ms) old_t FROM moments m JOIN wanted w USING(user_id)
                WHERE m.utc_ms<w.minimum_start-{30*DAY} GROUP BY 1
              ) SELECT m.* FROM moments m JOIN wanted w USING(user_id) LEFT JOIN older o USING(user_id)
                WHERE m.utc_ms>=w.minimum_start-{30*DAY} OR m.utc_ms=o.old_t'''
            n=io.copy(c,query,tmp/'moments.parquet')
            return dict(input_rows=job['rows'],retained_person_moments=n,file_index=job['file_index'])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['path'],job['people'],job['pairs'],job['focal']])[1]

def merge_chronology(queries,prepared,parts,root,conf,memory,workers):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,workers)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries])+' WHERE NOT previous_frame')
            c.execute('CREATE VIEW roles AS SELECT * FROM '+io.parq([prepared/'roles.parquet']))
            c.execute('CREATE TEMP TABLE moments AS SELECT user_id,utc_ms,sum(multiplicity)::BIGINT multiplicity,min(gid) gid,min(opponent_id)::BIGINT opponent_id FROM '+io.parq([p/'moments.parquet' for p in parts])+' GROUP BY 1,2')
            c.execute('CREATE TEMP TABLE found_focal AS SELECT game_id,sum(matches)::BIGINT matches FROM '+io.parq([p/'focal.parquet' for p in parts])+' GROUP BY 1')
            c.execute('''CREATE VIEW candidates AS
                SELECT r.sample_row,r.role,r.user_id,r.opponent_id,r.game_id,r.archive_start_ms,
                  p.utc_ms prev_t,p.multiplicity prev_count,p.gid prev_gid,p.opponent_id prev_opponent,
                  coalesce(x.multiplicity,0)::BIGINT focal_time_count,
                  coalesce(f.matches,0)::BIGINT focal_matches
                FROM roles r ASOF LEFT JOIN moments p ON r.user_id=p.user_id AND r.archive_start_ms>p.utc_ms
                LEFT JOIN moments x ON r.user_id=x.user_id AND r.archive_start_ms=x.utc_ms
                LEFT JOIN found_focal f ON r.game_id=f.game_id''')
            c.execute('CREATE VIEW focal AS SELECT row_id sample_row,recipient_id,opponent_id FROM q')
            sql=rebuild.adjacency_final_sql('candidates','focal')
            c.execute('CREATE TEMP TABLE classifications AS '+sql)
            c.execute('CREATE TEMP TABLE pairs AS SELECT pair_key,min(first_t)::BIGINT first_t FROM '+io.parq([p/'pairs.parquet' for p in parts])+' GROUP BY 1')
            # Prefix totals at timestamps strictly below the two endpoints.
            c.execute('CREATE TEMP TABLE volume AS SELECT user_id,utc_ms,sum(multiplicity) OVER(PARTITION BY user_id ORDER BY utc_ms ROWS UNBOUNDED PRECEDING)::BIGINT cumulative FROM moments')
            pair='least(q.recipient_id,q.opponent_id)::UBIGINT*4294967296+greatest(q.recipient_id,q.opponent_id)::UBIGINT'
            query=f'''SELECT q.row_id,s.previous_classification_status,
                s.previous_classification_status={io.lit(rebuild.NONADJ)} AS eligible_main,
                (p.first_t=q.archive_start_ms) AS first_observed_pair,
                (coalesce(hi.cumulative,0)-coalesce(lo.cumulative,0))::BIGINT pre_games_30d
              FROM q JOIN classifications s ON q.row_id=s.sample_row LEFT JOIN pairs p ON {pair}=p.pair_key
              ASOF LEFT JOIN volume hi ON q.recipient_id=hi.user_id AND q.archive_start_ms>hi.utc_ms
              ASOF LEFT JOIN volume lo ON q.recipient_id=lo.user_id AND q.archive_start_ms-{30*DAY}>lo.utc_ms'''
            n=c.execute('SELECT count(*) FROM q').fetchone()[0];assert_rows(c,query,n,'Chronology')
            bad=c.execute('SELECT count(*) FROM ('+query+') WHERE first_observed_pair IS NULL OR pre_games_30d<0').fetchone()[0]
            if bad:raise RuntimeError('Focal game absent from canonical pair chronology or invalid volume')
            io.copy(c,query,tmp/'features.parquet')
            counts=[dict(classification=k,rows=n) for k,n in c.execute('SELECT previous_classification_status,count(*) FROM classifications GROUP BY 1').fetchall()]
            return dict(rows=n,classifications=counts,factual_author_games_preserved=True)
        finally:finish_connection(c,tmp/'spill')
    paths=[queries,prepared/'roles.parquet']+[p/name for p in parts for name in ('moments.parquet','pairs.parquet','focal.parquet')]
    return stable_stage(root,conf,build,paths)
