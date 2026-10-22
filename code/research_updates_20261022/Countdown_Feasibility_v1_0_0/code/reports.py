"""Aggregate-only feasibility outputs. No causal estimates or significance tests."""
from common import *

SUMMARY_JOBS = [
 ('overall_coverage', '''SELECT count(*) AS "rows", sum(y)::BIGINT grants,count(DISTINCT chooser) choosers,
        count(*) FILTER(WHERE material_source='fen_verified') fen_verified,
        count(*) FILTER(WHERE material_source='cached_piece_counts') piece_counts_only,
        count(*) FILTER(WHERE deficit IS NULL) missing_material,
        count(*) FILTER(WHERE region='missing_eval') missing_eval,
        count(*) FILTER(WHERE clock_c IS NULL OR clock_d IS NULL) missing_clock,
        count(*) FILTER(WHERE NOT isfinite(rating) OR rating IS NULL OR NOT isfinite(rating_gap) OR rating_gap IS NULL) missing_rating,
        count(*) FILTER(WHERE speed='excluded_other_speed') excluded_speed
        FROM p'''),
 ('profile_by_month', '''SELECT month,speed,region,deficit,count(*) n,sum(y)::BIGINT grants,
        count(DISTINCT chooser) choosers,100.*avg(y) grant_percent,
        avg(cp) mean_cp,avg(clock_d) mean_clock_d,avg(clock_c) mean_clock_c
        FROM p GROUP BY ALL ORDER BY ALL'''),
 ('competitive_threshold', '''SELECT speed,period,region,count(*) n,sum(y)::BIGINT grants,
        count(*) FILTER(WHERE deficit>=4) deficit_ge4_n,
        sum(y) FILTER(WHERE deficit>=4)::BIGINT deficit_ge4_grants,
        100.*count(*) FILTER(WHERE deficit>=4)/nullif(count(*) FILTER(WHERE deficit IS NOT NULL),0) percent_ge4_among_material_observed,
        count(*) FILTER(WHERE deficit IS NULL) missing_material
        FROM p WHERE region IN ('finite_competitive','mate_winning') GROUP BY ALL ORDER BY ALL'''),
 ('profile_by_period_clock', '''SELECT speed,period,region,clock_sample,deficit,count(*) n,
        sum(y)::BIGINT grants,count(DISTINCT chooser) choosers,100.*avg(y) grant_percent,
        avg(cp) mean_cp,avg(clock_d) mean_clock_d,avg(clock_c) mean_clock_c,
        approx_quantile(clock_d,0.1) approx_clock_d_p10,approx_quantile(clock_d,0.5) approx_clock_d_median,
        approx_quantile(clock_d,0.9) approx_clock_d_p90
        FROM samples WHERE deficit BETWEEN 0 AND 8 GROUP BY ALL ORDER BY ALL'''),
 ('eval_clock_distributions', '''SELECT speed,period,region,deficit,stage,
        CASE WHEN mate THEN region WHEN cp< -1000 THEN 'finite_below_-1000'
             ELSE cast(100*floor(cp/100) AS VARCHAR) END eval100,
        clock_d_bin,clock_c_bin,count(*) n,sum(y)::BIGINT grants
        FROM p WHERE deficit BETWEEN 2 AND 5 GROUP BY ALL ORDER BY ALL'''),
 ('clock_lower_tail_by_week', '''SELECT date_trunc('week',position_date)::DATE AS "week",speed,
        CASE WHEN deficit>=4 THEN 'short_material_regime' WHEN deficit<4 THEN 'long_material_regime' ELSE 'missing' END material_regime,
        count(*) n, count(clock_d) clock_observed_n,min(clock_d) minimum_last_observed_clock,
        approx_quantile(clock_d,0.01) approx_p01,approx_quantile(clock_d,0.05) approx_p05,
        approx_quantile(clock_d,0.1) approx_p10
        FROM p GROUP BY ALL ORDER BY ALL'''),
 ('composition_top30', '''WITH a AS (SELECT speed,period,deficit,piece_signature,count(*) n,sum(y)::BIGINT grants
        FROM p WHERE deficit BETWEEN 2 AND 5 AND region='finite_lost' GROUP BY ALL),
        b AS (SELECT *,row_number() OVER(PARTITION BY speed,period,deficit ORDER BY n DESC,piece_signature) r,
        sum(n) OVER(PARTITION BY speed,period,deficit) group_n FROM a)
        SELECT speed,period,deficit,piece_signature,n,grants,100.*n/group_n percent_of_group
        FROM b WHERE r<=30 ORDER BY speed,period,deficit,r'''),
 ('chooser_overlap', '''WITH a AS (SELECT speed,period,clock_sample,chooser,
        count(*) FILTER(WHERE deficit=3) n3,count(*) FILTER(WHERE deficit=4) n4,
        sum(y) FILTER(WHERE deficit=3) g3,sum(y) FILTER(WHERE deficit=4) g4
        FROM samples WHERE region='finite_lost' AND deficit IN (3,4) GROUP BY ALL)
        SELECT speed,period,clock_sample,count(*) choosers,
        count(*) FILTER(WHERE n3>0 AND n4>0) choosers_both_3_4,
        sum(n3+n4) FILTER(WHERE n3>0 AND n4>0)::BIGINT rows_from_choosers_both,
        sum(g3+g4) FILTER(WHERE n3>0 AND n4>0)::BIGINT grants_from_choosers_both
        FROM a GROUP BY ALL ORDER BY ALL'''),
]

def support(c, run):
    path=Path(run)/'PRIVATE/support_cells.parquet'
    # Exclude missing clocks from overlap comparisons explicitly, without removing them from profiles.
    copy(c, '''SELECT speed,period,clock_sample,stage,eval10,clock_d_bin,clock_c_bin,
       count(*) FILTER(WHERE deficit=2) n2,count(*) FILTER(WHERE deficit=3) n3,
       count(*) FILTER(WHERE deficit=4) n4,count(*) FILTER(WHERE deficit=5) n5,
       coalesce(sum(y) FILTER(WHERE deficit=2),0)::BIGINT g2,
       coalesce(sum(y) FILTER(WHERE deficit=3),0)::BIGINT g3,
       coalesce(sum(y) FILTER(WHERE deficit=4),0)::BIGINT g4,
       coalesce(sum(y) FILTER(WHERE deficit=5),0)::BIGINT g5
       FROM samples WHERE region='finite_lost' AND deficit BETWEEN 2 AND 5
       AND clock_d IS NOT NULL AND clock_c IS NOT NULL GROUP BY ALL''',path)
    c.execute('CREATE VIEW cells AS SELECT * FROM '+scan(path))
    csv_query(c, '''SELECT speed,period,clock_sample,count(*) cells,
       sum(n2+n3+n4+n5)::BIGINT total_rows_2_5,sum(g2+g3+g4+g5)::BIGINT total_grants_2_5,
       count(*) FILTER(WHERE n3>0 AND n4>0) cells_both_3_4,
       coalesce(sum(n3+n4) FILTER(WHERE n3>0 AND n4>0),0)::BIGINT rows_in_shared_3_4_cells,
       coalesce(sum(g3+g4) FILTER(WHERE n3>0 AND n4>0),0)::BIGINT grants_in_shared_3_4_cells,
       count(*) FILTER(WHERE least(n2,n3,n4,n5)>0) cells_all_2_5,
       coalesce(sum(n2+n3+n4+n5) FILTER(WHERE least(n2,n3,n4,n5)>0),0)::BIGINT rows_in_shared_2_5_cells,
       count(*) FILTER(WHERE least(n2,n3,n4,n5)>=20) cells_min20_each_2_5,
       coalesce(sum(n2+n3+n4+n5) FILTER(WHERE least(n2,n3,n4,n5)>=20),0)::BIGINT rows_in_min20_each_cells
       FROM cells GROUP BY ALL ORDER BY ALL''',Path(run)/'report/overlap_summary.csv')

def summarize(run, records, memory, workers, announce):
    run=Path(run); c=db(run/'PRIVATE/spill_summary',memory,min(workers,4))
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+scan([r['output']['path'] for r in records]))
        with heartbeat('Checking global game uniqueness'):
            n,uniq=c.execute('SELECT count(*),count(DISTINCT game_id) FROM p').fetchone()
            require(n==uniq,'Duplicate games across monthly sources')
        c.execute('''CREATE VIEW samples AS SELECT p.*, x.clock_sample FROM p
            CROSS JOIN (VALUES ('unrestricted'),('above_long_proxy'),('above_twice_long_proxy')) x(clock_sample)
            WHERE speed<>'excluded_other_speed' AND
            (x.clock_sample='unrestricted' OR (x.clock_sample='above_long_proxy' AND clock_d>long_clock_cut)
             OR (x.clock_sample='above_twice_long_proxy' AND clock_d>2*long_clock_cut))''')
        timings=[]
        for i,(name,sql) in enumerate(SUMMARY_JOBS):
            start=time.monotonic()
            with heartbeat('Aggregate '+name): csv_query(c,sql,run/'report'/(name+'.csv'))
            timings.append(time.monotonic()-start)
            remaining=(sum(timings)/len(timings))*(len(SUMMARY_JOBS)-i)
            announce(i+1,len(SUMMARY_JOBS)+1,remaining)
        with heartbeat('Evaluation / clock / stage overlap cells'): support(c,run)
        announce(len(SUMMARY_JOBS)+1,len(SUMMARY_JOBS)+1,0)
        return dict(rows=n,unique_game_ids=uniq,summary_seconds=sum(timings),overlap_cells=record(run/'PRIVATE/support_cells.parquet'))
    finally:c.close()
