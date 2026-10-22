"""All-source histories, known-main later decisions, and selection flags."""
import shutil
from common import *
from contracts import snap
import logic

def history_month_job(job):
    inputs=job['inputs'];key=digest(dict(code=job['code'],month=job['month'],inputs=inputs))
    def build(tmp):
        c=connection(tmp/'spill',job['threads'],job['memory_mb'])
        try:
            h=scan(job['paths'])
            query=f'''WITH e AS (
                SELECT j::BIGINT person,t::BIGINT t,fair::BIGINT fair,(fair AND y)::BIGINT kind,
                    0::BIGINT disconnect,0::BIGINT receipt,0::BIGINT claim FROM {h} WHERE fair
                UNION ALL SELECT i::BIGINT,t::BIGINT,0::BIGINT,0::BIGINT,1::BIGINT,y::BIGINT,(arm AND NOT y)::BIGINT FROM {h})
                SELECT person,t,sum(fair)::BIGINT fair,sum(kind)::BIGINT kind,sum(disconnect)::BIGINT disconnect,
                    sum(receipt)::BIGINT receipt,sum(claim)::BIGINT claim,(person%16)::INTEGER bucket FROM e GROUP BY person,t'''
            c.execute('COPY ('+query+') TO '+lit(tmp/'events')+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket))')
            return dict(month=job['month'],input_rows=sum(pq.ParquetFile(p).metadata.num_rows for p in job['paths']))
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    root,d=stage(Path(job['work'])/'history_events'/job['month']/key,key,inputs,build,job['auth'])
    return dict(root=str(root),result=d['result'])

def empty_events():return {k:np.empty(0,np.int64) for k in ('person','t',*logic.COUNTS)}

def bucket_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    key=digest(dict(code=job['code'],bucket=job['bucket'],inputs=job['inputs']))
    def build(tmp):
        c=connection(tmp/'spill',job['threads'],job['memory_mb'])
        try:
            querypaths=job['queries']
            if not querypaths:return dict(bucket=job['bucket'],rows=0)
            c.execute('CREATE VIEW q AS SELECT * FROM '+scan(querypaths))
            fields='row_id,game_id,recipient_id,opponent_id,archive_start_ms,anchor_ms,archive_ordinal,n_7d,n_30d,adjusted_7d,adjusted_30d,expected_7d,expected_30d'
            qt=c.execute('SELECT '+fields+' FROM q ORDER BY recipient_id,archive_start_ms,archive_ordinal,game_id').to_arrow_table();q=logic.arrays(qt);del qt
            if job['events']:
                ht=c.execute('SELECT person,t,'+','.join('sum('+x+')::BIGINT '+x for x in logic.COUNTS)+' FROM '+scan(job['events'])+
                    ' SEMI JOIN (SELECT DISTINCT recipient_id FROM q) z ON person=z.recipient_id GROUP BY person,t').to_arrow_table()
                h=logic.arrays(ht);del ht
            else:h=empty_events()
            counts=logic.window_counts(h,q['recipient_id'],q['archive_start_ms']);counts['row_id']=q['row_id'];del h
            pq.write_table(pa.table(counts),tmp/'counts_PRIVATE.parquet',compression='zstd');del counts
            if job['outcomes']:
                ht=c.execute('SELECT gid,j,i,t,start,ord,y,color,known FROM '+scan(job['outcomes'])+
                    ' SEMI JOIN (SELECT DISTINCT recipient_id FROM q) z ON j=z.recipient_id').to_arrow_table();h=logic.arrays(ht);del ht
            else:
                h={k:np.empty(0, 'U8' if k=='gid' else 'U5' if k=='color' else bool if k in ('known','y') else np.int64)
                    for k in ('gid','j','i','t','start','ord','y','color','known')}
            if len(h['t']) and (np.any(h['t']<h['start']) or not np.isin(h['color'],['white','black']).all()):
                raise RuntimeError('Invalid later-choice timing or color')
            o=logic.outcomes(h,q);del h
            pq.write_table(pa.table(o),tmp/'outcomes_PRIVATE.parquet',compression='zstd');del o
            flags=logic.selection(q);pq.write_table(pa.table(flags),tmp/'flags_PRIVATE.parquet',compression='zstd');del flags,q
            for name in ('counts','outcomes','flags'):
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+scan(tmp/(name+'_PRIVATE.parquet')))
            # Keep known nonreachers separately; absence under incomplete/ambiguous
            # observation never enters the primary response as zero.
            period=f'''CASE WHEN q.anchor_ms<{logic.POLICY_LO} THEN 'pre' WHEN q.anchor_ms>={logic.POLICY_HI} THEN 'post' ELSE 'implementation_bracket' END'''
            z=f'''SELECT q.*,c.* EXCLUDE(row_id),o.* EXCLUDE(row_id),f.* EXCLUDE(row_id),
                CASE WHEN o.complete90_data AND NOT o.outcome_membership_ambiguous THEN o.observed_y ELSE NULL END y_calendar,
                CASE WHEN q.pre_games_30d_complete THEN q.pre_games_30d_observed ELSE NULL END pre_games_30d,
                {period} index_policy_period,
                CASE WHEN o.later_choice_is_identified AND o.later_choice_policy_period IN ('pre','post') THEN
                    (o.outcome_color='white')::INTEGER*(o.later_choice_policy_period='post')::INTEGER ELSE NULL END later_white_x_post,
                NULL::BOOLEAN final_iv_eligible,NULL::BIGINT mechanics_censor_ms,
                c.history_window_complete AND o.complete90_data AND NOT o.outcome_membership_ambiguous
                    AND f.spaced90_7d_floor5 calendar_primary_7d_floor5,
                c.history_window_complete AND o.complete90_data AND NOT o.outcome_membership_ambiguous
                    AND f.common5_10_on_primary_stream calendar_common5_10,
                c.history_window_complete AND o.complete90_data AND NOT o.outcome_membership_ambiguous
                    AND f.spaced90_7d_floor10 calendar_independently_spaced_floor10
                FROM q JOIN counts c USING(row_id) JOIN outcomes o USING(row_id) JOIN flags f USING(row_id) ORDER BY q.row_id'''
            n=copy(c,z,tmp/'analysis_PRIVATE.parquet')
            if n!=c.execute('SELECT count(*) FROM q').fetchone()[0]:raise RuntimeError('Follow-up joins changed row count')
            c.execute('CREATE VIEW a AS SELECT * FROM '+scan(tmp/'analysis_PRIVATE.parquet'))
            for gap in (30,90):
                copy(c,f'SELECT row_id,game_id,recipient_id,opponent_id,archive_start_ms,anchor_ms FROM a WHERE spaced{gap}_7d_floor5 ORDER BY recipient_id,archive_start_ms,archive_ordinal,game_id',tmp/f'selected_stream_{gap}_PRIVATE.parquet')
            # Window selection precedes every administrative and prior-history cut.
            bad=c.execute(f'''SELECT count(*) FROM (SELECT recipient_id,archive_start_ms,
                lag(anchor_ms) OVER(PARTITION BY recipient_id ORDER BY archive_start_ms,archive_ordinal,game_id) prev
                FROM a WHERE spaced90_7d_floor5) WHERE archive_start_ms<=prev+{90*DAY}''').fetchone()[0]
            if bad:raise RuntimeError('Primary selected windows overlap')
            bad=c.execute('SELECT count(*) FROM (SELECT outcome_gid FROM a WHERE calendar_primary_7d_floor5 AND reached GROUP BY 1 HAVING count(*)>1)').fetchone()[0]
            if bad:raise RuntimeError('Primary selected cohort reuses an outcome decision')
            for name in ('counts','outcomes','flags'):(tmp/(name+'_PRIVATE.parquet')).unlink()
            return dict(bucket=job['bucket'],rows=n)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    root,d=stage(Path(job['work'])/'followup'/f"bucket-{job['bucket']:02d}"/key,key,job['inputs'],build,job['auth'])
    return dict(root=str(root),result=d['result'])
