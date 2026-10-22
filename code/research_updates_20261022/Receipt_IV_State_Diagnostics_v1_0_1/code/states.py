"""Attach authenticated pregame states without changing exposure selection."""
import shutil
from common import *
from contracts import snap, POST_MONTHS

FIELDS=('archive_ordinal','utc_ms','game_id','white_id','black_id','white_elo','black_elo',
        'white_rating_diff','black_rating_diff','result_code','white_pre_rd','black_pre_rd',
        'white_prior_games','black_prior_games','white_last_ms','black_last_ms','white_pred','black_pred')

def prepare(inp,root,code,threads,memory,auth):
    key=digest(dict(code=code,inputs=inp['snapshots']))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory)
        try:
            parts=[]
            for r in inp['targets']:
                if not set(FIELDS)<=columns(r['path']):raise RuntimeError('Retained target-state schema differs')
                parts.append('SELECT '+','.join(map(ident,FIELDS))+','+lit(r['month'])+' AS "month",'+lit(r['speed'])+' AS "speed" FROM '+scan(r['path']))
            c.execute('CREATE VIEW t AS '+' UNION ALL '.join(parts))
            n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM t').fetchone()
            if n!=u:raise RuntimeError('Duplicate replay target IDs')
            bad=c.execute('''SELECT count(*) FROM t WHERE game_id IS NULL OR white_id IS NULL OR black_id IS NULL
                OR white_id=black_id OR utc_ms IS NULL OR archive_ordinal IS NULL
                OR white_pre_rd IS NULL OR black_pre_rd IS NULL OR NOT isfinite(white_pre_rd) OR NOT isfinite(black_pre_rd)
                OR white_pre_rd<45 OR white_pre_rd>500 OR black_pre_rd<45 OR black_pre_rd>500
                OR result_code IS NULL OR result_code NOT IN (0,1,2)''').fetchone()[0]
            if bad:raise RuntimeError('Invalid replay target state')
            copy(c,'SELECT * FROM t',tmp/'targets_PRIVATE.parquet')
            parts=[f"SELECT user_id::BIGINT user_id,{lit(r['speed'])} speed,games_seen::BIGINT games_seen FROM {scan(r['path'])} WHERE games_seen>=100" for r in inp['checkpoints']]
            c.execute('CREATE VIEW e AS '+' UNION ALL '.join(parts))
            if c.execute('SELECT count(*) FROM (SELECT user_id,speed,count(*) n FROM e GROUP BY ALL HAVING n>1)').fetchone()[0]:
                raise RuntimeError('Duplicate fixed-history identity')
            ne=copy(c,'SELECT * FROM e',tmp/'established_PRIVATE.parquet')
            return dict(target_rows=n,established_speed_accounts=ne)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(root/'state_inputs'/key,key,inp['snapshots'],build,auth)[0]

def oriented_query(analysis,targets,established):
    # Both sides' hidden states were recorded before either player's update.
    w="a.index_chooser_color='white'"
    def side(wcol,bcol):return f'CASE WHEN {w} THEN t.{wcol} ELSE t.{bcol} END'
    selected=[
        ('state_opponent_id',side('white_id','black_id')),('state_recipient_id',side('black_id','white_id')),
        ('state_opponent_rating',side('white_elo','black_elo')),('state_recipient_rating',side('black_elo','white_elo')),
        ('state_opponent_rd',side('white_pre_rd','black_pre_rd')),('state_recipient_rd',side('black_pre_rd','white_pre_rd')),
        ('opponent_observed_change',side('white_rating_diff','black_rating_diff')),('recipient_observed_change',side('black_rating_diff','white_rating_diff')),
        ('opponent_predicted_change',side('white_pred','black_pred')),('recipient_predicted_change',side('black_pred','white_pred')),
        ('opponent_prior_games',side('white_prior_games','black_prior_games')),('recipient_prior_games',side('black_prior_games','white_prior_games')),
        ('opponent_last_update_ms',side('white_last_ms','black_last_ms')),('recipient_last_update_ms',side('black_last_ms','white_last_ms'))]
    return f'''SELECT a.*,t.game_id IS NOT NULL replay_state_attached,t.utc_ms state_start_ms,
        t.archive_ordinal state_ordinal,t.month state_month,t.speed state_speed,t.result_code,
        {','.join(v+' AS '+ident(k) for k,v in selected)},
        coalesce(er.games_seen>=100,FALSE) recipient_established_oct2023,
        coalesce(eo.games_seen>=100,FALSE) opponent_established_oct2023
        FROM {scan(analysis)} a LEFT JOIN {scan(targets)} t USING(game_id)
        LEFT JOIN {scan(established)} er ON a.recipient_id=er.user_id AND a.speed=er.speed
        LEFT JOIN {scan(established)} eo ON a.opponent_id=eo.user_id AND a.speed=eo.speed'''

def validate_join(c,expected_n):
    n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM j').fetchone()
    if n!=expected_n or u!=n:raise RuntimeError('State join changed row count or uniqueness')
    bad=c.execute('''SELECT count(*) FROM j WHERE replay_state_attached AND
        (state_start_ms IS DISTINCT FROM archive_start_ms OR state_ordinal IS DISTINCT FROM archive_ordinal
        OR state_month IS DISTINCT FROM month OR state_speed IS DISTINCT FROM speed
        OR state_opponent_id IS DISTINCT FROM opponent_id OR state_recipient_id IS DISTINCT FROM recipient_id
        OR state_opponent_rating IS DISTINCT FROM opponent_rating OR state_recipient_rating IS DISTINCT FROM recipient_rating
        OR index_chooser_color NOT IN ('white','black')
        OR (recipient_rd IS NOT NULL AND abs(recipient_rd-state_recipient_rd)>1e-9)
        OR (opponent_rd IS NOT NULL AND abs(opponent_rd-state_opponent_rd)>1e-9))''').fetchone()[0]
    if bad:raise RuntimeError('State identity, speed, time, rating anchor or existing RD disagrees')
    missed=c.execute("SELECT count(*) FROM j WHERE month IN ('2025-11','2025-12','2026-01') AND NOT replay_state_attached").fetchone()[0]
    if missed:raise RuntimeError('November–January exposure lacks its authenticated replay state')

def enrich_job(job):
    key=digest(dict(code=job['code'],inputs=job['inputs'],index=job['index']))
    def build(tmp):
        c=connection(tmp/'spill',job['threads'],job['memory_mb'])
        try:
            p=Path(job['prepared']);q=oriented_query(job['path'],p/'targets_PRIVATE.parquet',p/'established_PRIVATE.parquet')
            c.execute('CREATE VIEW j AS '+q)
            validate_join(c,pq.ParquetFile(job['path']).metadata.num_rows)
            # Keep every original column except the three explicitly enriched fields.
            fields=','.join('j.'+ident(k) for k in pq.ParquetFile(job['path']).schema_arrow.names
                            if k not in ('recipient_rd','opponent_rd','authenticated_rating_states_attached'))
            extras=['replay_state_attached','result_code','recipient_established_oct2023','opponent_established_oct2023']
            extras += [role+'_'+name for role in ('recipient','opponent') for name in
                       ('observed_change','predicted_change','prior_games','last_update_ms')]
            sql=f'''SELECT {fields},coalesce(recipient_rd,state_recipient_rd) recipient_rd,
                coalesce(opponent_rd,state_opponent_rd) opponent_rd,
                (authenticated_rating_states_attached OR replay_state_attached) authenticated_rating_states_attached,
                recipient_rd original_recipient_rd,opponent_rd original_opponent_rd,
                {','.join(extras)},
                CASE WHEN recipient_last_update_ms>=0 THEN (archive_start_ms-recipient_last_update_ms)/86400000.0 END recipient_inactivity_days,
                CASE WHEN opponent_last_update_ms>=0 THEN (archive_start_ms-opponent_last_update_ms)/86400000.0 END opponent_inactivity_days
                FROM j'''
            n=copy(c,sql,tmp/'analysis_enriched_PRIVATE.parquet')
            rows=c.execute('''SELECT month,count(*) AS row_count,count(*) FILTER(WHERE calendar_primary_7d_floor5) primary_rows,
                count(*) FILTER(WHERE calendar_primary_7d_floor5 AND original_recipient_rd IS NULL) primary_missing_rd_before,
                count(*) FILTER(WHERE calendar_primary_7d_floor5 AND (recipient_rd IS NULL OR opponent_rd IS NULL)) primary_missing_rd_after,
                count(*) FILTER(WHERE replay_state_attached) replay_attached_rows
                FROM '''+scan(tmp/'analysis_enriched_PRIVATE.parquet')+' GROUP BY month ORDER BY month').to_arrow_table().to_pylist()
            write_json(tmp/'attachment_counts.json',rows)
            return dict(rows=n,counts=rows)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    root,done=stage(Path(job['work'])/'enriched'/key,key,job['inputs'],build,job['auth'])
    return dict(root=str(root),path=str(root/'analysis_enriched_PRIVATE.parquet'),result=done['result'])
