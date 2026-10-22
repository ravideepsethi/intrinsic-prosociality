"""Certified pre-policy panel; no API, rating replay, or Stockfish calls."""
from common import *

def sources(project):
    a=read(ROOT/'authority/pool_main.json')
    base=Path(project)/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    s=read(base/'_SUCCESS.json')
    for k in ('status','main_predicate','contract_sha256','code_sha256','observed_screen_certified','literal_immediate_rematches_certified'):
        if a[k]!=s.get(k):raise RuntimeError('Pool authority mismatch: '+k)
    if s.get('report_zip_sha256')!=a['report_sha256']:raise RuntimeError('Pool report identity differs')
    by={r['month']:r for r in s['panel_outputs']};result=[]
    for r in a['panel_outputs']:
        for k in ('rows','relative_path','size_bytes','sha256'):
            if by[r['month']].get(k)!=r[k]:raise RuntimeError('Monthly pool authority mismatch')
        result.append((base/r['relative_path'],r))
    return result

def narrow_month(task):
    source,record,work=task;source=Path(source);work=Path(work);month=record['month']
    identity=auth(source,work,record['sha256'],record['rows'],record['size_bytes'])
    out=work/'narrow'/f'{month}.parquet';key=digest(dict(version=VERSION,input=identity))
    if reuse(out,key):return str(out)
    c=connect(work/'tmp'/('narrow_'+month))
    try:
        sql=f"""SELECT game_id,chooser_user_id::BIGINT chooser,disconnected_user_id::BIGINT opponent,
          api_created_at_ms::BIGINT t,lower(api_speed) speed,chooser_color color,
          outcome_kind_draw::TINYINT y,engine_eval_cp_disconnected::DOUBLE cp,ply_count::INTEGER ply,
          chooser_elo::DOUBLE rating,disconnected_elo::DOUBLE opp_rating,
          disconnected_elo-chooser_elo AS g,chooser_pre_rd_v2::DOUBLE rd,disconnected_pre_rd_v2::DOUBLE opp_rd,
          chooser_draw_payoff_v2::DOUBLE rg,chooser_win_payoff_v2::DOUBLE rc,chooser_win_premium_v2::DOUBLE ki,
          CASE disconnected_color WHEN 'white' THEN white_win_premium_v2 WHEN 'black' THEN black_win_premium_v2 END::DOUBLE kj,
          chooser_clock_last_obs_s::DOUBLE clock,disconnected_clock_last_obs_s::DOUBLE opp_clock,
          {q(month)}::VARCHAR AS month,
          CASE WHEN engine_eval_cp_disconnected>=-100 THEN 'equal' ELSE 'losing' END AS state
          FROM {scan(source)} WHERE ply_count>10
          AND (engine_eval_cp_disconnected>=-100 AND engine_eval_cp_disconnected<100 OR engine_eval_cp_disconnected<=-300)
          AND disconnected_elo-chooser_elo>=-575 AND disconnected_elo-chooser_elo<575"""
        copy(c,sql,out)
        n,u,bad=c.execute(f"SELECT count(*),count(DISTINCT game_id),count(*) FILTER(WHERE t IS NULL OR chooser IS NULL OR opponent IS NULL OR chooser=opponent OR y NOT IN(0,1) OR ki<=0 OR kj<=0 OR NOT isfinite(rg+rc+ki+kj+rd+opp_rd)) FROM {scan(out)}").fetchone()
        if n!=u or bad:raise RuntimeError('Invalid narrow panel: '+month)
        err=0.
        for b in pq.ParquetFile(out).iter_batches(batch_size=100000):err=max(err,check_payoffs(b.to_pandas()))
        done(out,key,rows=n,month=month,maximum_payoff_error=err)
        log(f'{month}: {n:,} eligible board/stage/gap rows; payoff identities verified')
        return str(out)
    finally:c.close()

def needed_users(work,files,threads=8,memory_mb=4096):
    work=Path(work);out=work/'needed_users.parquet';key=digest([stamp(p) for p in files])
    if reuse(out,key):return out
    c=connect(work/'tmp/needed',threads,memory_mb)
    try:
        copy(c,f'SELECT DISTINCT speed,chooser AS user_id FROM {scan(files)} UNION SELECT DISTINCT speed,opponent AS user_id FROM {scan(files)}',out)
        done(out,key);return out
    finally:c.close()

def join_history(work,month):
    work=Path(work);base=work/'narrow'/f'{month}.parquet'
    hs=[work/'history_features'/f'{s}_{month}.parquet' for s in SPEEDS]
    out=work/'analysis'/f'{month}.parquet'
    key=digest(dict(version=VERSION,inputs=[stamp(p) for p in [base]+hs]))
    if reuse(out,key):return str(out)
    c=connect(work/'tmp'/('join_'+month),2,1536)
    try:
        c.execute(f'CREATE VIEW h AS SELECT * FROM {scan(hs)}')
        n,u=c.execute('SELECT count(*),count(DISTINCT (game_id,player_role)) FROM h').fetchone()
        expected=pq.ParquetFile(base).metadata.num_rows*2
        if n!=expected or n!=u:raise RuntimeError('History targets do not conserve: '+month)
        sql=f"""SELECT b.*,h.prior_starts,h.history_days,h.inactivity_days,h.week1,h.week2,h.week3,h.week4,
          o.prior_starts opp_prior_starts,
          h.prior_starts>=100 AND h.history_days>=365 AND h.week1 AND h.week2 AND h.week3 AND h.week4 AS regular,
          h.prior_starts>=100 AND h.history_days>=365 AND b.rd<=110 AND h.inactivity_days<90 AS tier2
          FROM {scan(base)} b JOIN h ON b.game_id=h.game_id AND h.player_role=1
          JOIN h o ON b.game_id=o.game_id AND o.player_role=0"""
        copy(c,sql,out);done(out,key);return str(out)
    finally:c.close()
