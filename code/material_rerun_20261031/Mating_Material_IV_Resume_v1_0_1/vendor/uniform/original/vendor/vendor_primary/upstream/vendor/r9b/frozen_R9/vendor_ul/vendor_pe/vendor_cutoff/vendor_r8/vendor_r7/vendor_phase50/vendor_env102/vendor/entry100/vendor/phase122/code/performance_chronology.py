"""Exact first-pair scan with a bounded chronology sort and reusable game features."""
from cached_common import *
import phase_chronology as previous
from performance_cache import feature_stage,CHRON_KEYS
from performance_runtime import Runtime
import performance_migration as migration

def chronology_job(job):
    threads_one()
    if io.sig(job['path'])!=job['signature']:raise RuntimeError('Chronology changed since authentication')
    if job.get('legacy_part'):
        reused=migration.reuse_chron_part(job)
        if reused is not None:return reused
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW wanted AS SELECT * FROM '+io.parq([job['people']]))
            c.execute('CREATE TEMP TABLE e AS SELECT game_id,utc_ms,white_id,black_id FROM '+io.parq([job['path']])+f" WHERE utc_ms>0 AND utc_ms<={job['latest']} AND white_id>=0 AND black_id>=0 AND white_id<4294967296 AND black_id<4294967296 AND white_id<>black_id AND (white_id IN (SELECT user_id FROM wanted) OR black_id IN (SELECT user_id FROM wanted))")
            c.execute('CREATE TEMP TABLE found_focal AS SELECT e.game_id,count(*)::BIGINT matches FROM e JOIN '+io.parq([job['focal']])+''' q ON e.game_id=q.game_id AND e.utc_ms=q.archive_start_ms
                AND least(e.white_id,e.black_id)=least(q.recipient_id,q.opponent_id) AND greatest(e.white_id,e.black_id)=greatest(q.recipient_id,q.opponent_id) GROUP BY 1''')
            pair='least(white_id,black_id)::UBIGINT*4294967296+greatest(white_id,black_id)::UBIGINT'
            io.copy(c,'SELECT '+pair+' pair_key,min(utc_ms)::BIGINT first_t FROM e SEMI JOIN '+io.parq([job['pairs']])+' p ON '+pair+'=p.pair_key GROUP BY 1',tmp/'pairs.parquet')
            # First-pair minima above use ALL prior games. Sorting below needs
            # recent moments and one true latest older moment per file/person.
            c.execute('''CREATE TEMP TABLE ep AS
                SELECT e.game_id,e.utc_ms,e.white_id user_id,e.black_id opponent_id,w.minimum_start FROM e JOIN wanted w ON e.white_id=w.user_id AND e.utc_ms<=w.maximum_start
                UNION ALL SELECT e.game_id,e.utc_ms,e.black_id,e.white_id,w.minimum_start FROM e JOIN wanted w ON e.black_id=w.user_id AND e.utc_ms<=w.maximum_start''')
            c.execute(f'CREATE TEMP TABLE older AS SELECT user_id,max(utc_ms) old_t FROM ep WHERE utc_ms<minimum_start-{30*DAY} GROUP BY 1')
            c.execute(f'''CREATE TEMP TABLE moments AS WITH counts AS (
                SELECT ep.user_id,utc_ms,count(*)::BIGINT multiplicity,min(game_id) gid,min(opponent_id)::BIGINT opponent_id
                FROM ep LEFT JOIN older USING(user_id) WHERE utc_ms>=minimum_start-{30*DAY} OR utc_ms=old_t GROUP BY ep.user_id,utc_ms
              ) SELECT *,sum(multiplicity) OVER(PARTITION BY user_id ORDER BY utc_ms ROWS UNBOUNDED PRECEDING)::BIGINT cumulative FROM counts''')
            c.execute('CREATE TEMP TABLE present AS SELECT user_id,min(utc_ms) minimum_t FROM moments GROUP BY 1')
            c.execute('CREATE VIEW roles AS SELECT r.* FROM '+io.parq([job['roles']])+' r JOIN present p ON r.user_id=p.user_id AND r.archive_start_ms>=p.minimum_t')
            query=f'''SELECT r.sample_row,r.role,p.utc_ms prev_t,p.multiplicity prev_count,p.gid prev_gid,p.opponent_id prev_opponent,
                coalesce(x.multiplicity,0)::BIGINT focal_time_count,coalesce(f.matches,0)::BIGINT focal_matches,
                CASE WHEN r.role=0 THEN coalesce(p.cumulative,0)-coalesce(lo.cumulative,0) ELSE 0 END::BIGINT pre_games_30d
                FROM roles r ASOF LEFT JOIN moments p ON r.user_id=p.user_id AND r.archive_start_ms>p.utc_ms
                ASOF LEFT JOIN moments lo ON r.user_id=lo.user_id AND r.archive_start_ms-{30*DAY}>lo.utc_ms
                LEFT JOIN moments x ON r.user_id=x.user_id AND r.archive_start_ms=x.utc_ms LEFT JOIN found_focal f ON r.game_id=f.game_id'''
            n=io.copy(c,query,tmp/'candidates.parquet')
            return dict(input_rows=job['rows'],retained_query_roles=n,file_index=job['file_index'],
                retained_person_moments=c.execute('SELECT count(*) FROM moments').fetchone()[0],
                unsorted_person_events=c.execute('SELECT count(*) FROM ep').fetchone()[0])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(job['output'],job['conf'],build,[job[k] for k in ('path','people','pairs','focal','roles')])[1]

def run(job,source,workers,runtime):
    def produce(queries,tmp):
        n=pq.ParquetFile(queries).metadata.num_rows
        if not n:
            path=tmp/'features.parquet';io.table(path,pa.table(dict(row_id=pa.array([],pa.int64()),previous_classification_status=pa.array([],pa.string()),eligible_main=pa.array([],pa.bool_()),first_observed_pair=pa.array([],pa.bool_()),pre_games_30d=pa.array([],pa.int64()))));return path
        prep,info=previous.prepare_chronology(queries,tmp/'plan',job['conf'],job['memory'])
        parts=Path(job['parts_root']);parts.mkdir(parents=True,exist_ok=True)
        # Stable query content identity lets interrupted optimized scans resume.
        partconf=io.cfgsha([job['cache_conf'],io.sha(queries)])
        jobs=[dict(r,latest=info['latest_start'],people=str(prep/'people.parquet'),pairs=str(prep/'pairs.parquet'),focal=str(prep/'focal.parquet'),roles=str(prep/'roles.parquet'),memory=job['worker_memory'],conf=partconf,output=str(parts/partconf[:16]/f"{r['file_index']:04}")) for r in source if r['minimum'] is None or r['minimum']<=info['latest_start']]
        if job.get('legacy'):
            legacy=job['legacy'];old=Path(legacy['root'])
            for row in jobs:row.update(legacy_part=str(old/'chron_parts'/f"{row['file_index']:04}"),legacy_conf=legacy['conf'],legacy_queries=str(old/'prepared/queries.parquet'))
        jobs.sort(key=lambda r:r['rows'],reverse=True)
        runtime.mapped(chronology_job,jobs,workers,'Bounded-sort chronology scan')
        out,_=previous.merge_chronology(queries,prep,[Path(r['output']) for r in jobs],tmp/'merged',job['conf'],job['memory'],workers)
        return out/'features.parquet'
    return feature_stage(job,'features.parquet',CHRON_KEYS,produce)
