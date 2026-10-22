"""Certified outcome preparation and creation-date linkage, entirely offline."""
import json
from pathlib import Path
import pyarrow.parquet as pq
from common import *

def profiles(con, sources):
    parts=[]
    for s in sources:
        cols=set(pq.ParquetFile(s['path']).schema_arrow.names)
        required={'username_norm','returned','raw_user_json'}
        if not required<=cols: raise RuntimeError('Profile source lacks '+str(required-cols))
        role="coalesce(CAST(acquisition_role AS VARCHAR),'unknown')" if 'acquisition_role' in cols else sqlstr(s['role_fallback'])
        parts.append(f"SELECT lower(trim(username_norm)) username, returned, {role} profile_role, "
                     "try_cast(json_extract_string(raw_user_json,'$.createdAt') AS BIGINT) raw_created_ms, "
                     "lower(json_extract_string(raw_user_json,'$.id')) raw_id "
                     f"FROM {parquet(s['path'])}")
    con.execute('CREATE TEMP TABLE profile_raw AS '+' UNION ALL '.join(parts))
    con.execute('ALTER TABLE profile_raw ADD COLUMN created_ms BIGINT')
    con.execute('UPDATE profile_raw SET created_ms=CASE WHEN raw_created_ms>0 THEN raw_created_ms END')
    bad=con.execute("SELECT count(*) FROM profile_raw WHERE returned AND raw_id IS NOT NULL AND raw_id<>username").fetchone()[0]
    if bad: raise RuntimeError(f'{bad} returned profile IDs disagree with normalized linkage key')
    bad=con.execute("SELECT count(*) FROM (SELECT username FROM profile_raw WHERE returned GROUP BY 1 HAVING count(DISTINCT created_ms)>1)").fetchone()[0]
    if bad: raise RuntimeError('Conflicting creation dates across authenticated profile sources')
    # Same creation date can occur in both certified sources; collapse once before joining.
    con.execute("""CREATE TEMP TABLE profiles AS SELECT username, max(created_ms) FILTER(WHERE returned) created_ms,
        string_agg(DISTINCT profile_role,'+' ORDER BY profile_role) acquisition_role FROM profile_raw GROUP BY username""")

def projection(month):
    midx=(int(month[:4])-2023)*12+int(month[5:])-11
    speedcase='CASE api_speed '+' '.join(f'WHEN {sqlstr(s)} THEN {i}' for i,s in enumerate(SPEEDS))+' ELSE NULL END'
    return f"""SELECT p.game_id, p.chooser_user_id::BIGINT chooser, p.disconnected_user_id::BIGINT recipient,
      p.chooser_username_norm username, p.api_created_at_ms::BIGINT start_ms,
      {midx}::SMALLINT month_idx, {speedcase}::SMALLINT speed,
      p.outcome_kind_draw::SMALLINT y, p.engine_eval_cp_disconnected::DOUBLE board,
      CASE WHEN p.engine_eval_cp_disconnected>=-100 THEN 1 WHEN p.engine_eval_cp_disconnected<=-300 THEN 0 ELSE -1 END::SMALLINT state,
      p.chooser_elo::DOUBLE rating, p.disconnected_elo::DOUBLE opp_rating,
      p.chooser_draw_payoff_v2::DOUBLE rg, p.chooser_win_payoff_v2::DOUBLE rc,
      p.chooser_win_premium_v2::DOUBLE premium,
      CASE p.disconnected_color WHEN 'white' THEN p.white_win_premium_v2 WHEN 'black' THEN p.black_win_premium_v2 END::DOUBLE opp_stake,
      CASE p.disconnected_color WHEN 'white' THEN p.white_draw_ratingdiff_v2 WHEN 'black' THEN p.black_draw_ratingdiff_v2 END::DOUBLE opp_rg,
      CASE p.disconnected_color WHEN 'white' THEN p.white_win_ratingdiff_v2 WHEN 'black' THEN p.black_win_ratingdiff_v2 END::DOUBLE opp_rc,
      p.chooser_pre_rd_v2::DOUBLE rd, p.disconnected_pre_rd_v2::DOUBLE opp_rd,
      p.ply_count::INTEGER ply, p.chooser_clock_last_obs_s::DOUBLE clock,
      p.disconnected_clock_last_obs_s::DOUBLE opp_clock,
      (p.api_created_at_ms-q.created_ms)::DOUBLE/{DAY} age_days,
      q.created_ms, coalesce(q.acquisition_role,'unacquired') acquisition_role,
      p.api_created_at_ms-p.utc_ms start_discrepancy_ms,
      p.chooser_elo_v2_source::DOUBLE replay_rating,p.disconnected_elo_v2_source::DOUBLE replay_opp_rating,
      CASE p.chooser_color WHEN 'white' THEN p.white_draw_ratingdiff_v2 WHEN 'black' THEN p.black_draw_ratingdiff_v2 END::DOUBLE side_rg,
      CASE p.chooser_color WHEN 'white' THEN p.white_win_premium_v2 WHEN 'black' THEN p.black_win_premium_v2 END::DOUBLE side_premium
    FROM main p LEFT JOIN profiles q ON lower(trim(p.chooser_username_norm))=q.username"""

def prepare(con, auth, sources, work, report, identity, buckets=16):
    work,report=Path(work),Path(report); receipt=work/'prepare_receipt.json'
    out=[work/'base'/f'bucket_{b:03d}.parquet' for b in range(buckets)]
    if checkpoint_ok(receipt,identity): log('Reusing authenticated prepared panel');return out
    profiles(con,sources)
    write_csv(report/'profile_inventory.csv', records(con,"""SELECT profile_role,count(*) records,
        count(*) FILTER(WHERE returned) returned,count(created_ms) FILTER(WHERE returned) creation_known,
        count(*) FILTER(WHERE returned AND raw_created_ms<=0) invalid_nonpositive_creation
        FROM profile_raw GROUP BY profile_role ORDER BY profile_role"""))
    month_paths=[]; cover=[]; audit=[]; total=dict(rows=0,grants=0,competitive=0,competitive_grants=0)
    for r in auth['month_records']:
        m=r['month']; path=work/'monthly'/f'{m}.parquet'; month_paths.append(path)
        mr=work/'monthly'/f'{m}.json'
        if checkpoint_ok(mr,identity):
            saved=json.loads(mr.read_text())['extra']; cover+=saved['coverage'];audit.append(saved['audit'])
            for k in total: total[k]+=saved['counts'][k]
            continue
        log('Projecting and auditing '+m)
        con.execute(f'CREATE OR REPLACE TEMP VIEW main AS SELECT * FROM {parquet(r["path"])}')
        counts=records(con,"""SELECT count(*) AS rows,sum(outcome_kind_draw::INT) grants,
            count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100) competitive,
            sum(outcome_kind_draw::INT) FILTER(WHERE engine_eval_cp_disconnected>=-100) competitive_grants FROM main""")[0]
        for k in total: total[k]+=counts[k]
        con.execute('CREATE OR REPLACE TEMP TABLE projected AS '+projection(m))
        cov=records(con,f"""SELECT {sqlstr(m)} AS month,acquisition_role,state,count(*) opportunities,
            count(DISTINCT chooser) choosers,sum(y) grants,count(created_ms) creation_known,
            count(*) FILTER(WHERE age_days>=365) age_eligible,
            count(*) FILTER(WHERE age_days<0) invalid_future_creation,
            count(*) FILTER(WHERE age_days>=0 AND age_days<365) known_younger_than_365
            FROM projected GROUP BY 1,2,3 ORDER BY 1,2,3""");cover+=cov
        a=records(con,f"""SELECT {sqlstr(m)} AS month,count(*) age_state_rows,
            count(*) FILTER(WHERE chooser IS NULL OR recipient IS NULL OR chooser<0 OR recipient<0 OR chooser=recipient OR speed IS NULL OR ply IS NULL OR ply<0 OR NOT coalesce(isfinite(rating) AND rating>0,false) OR NOT coalesce(isfinite(opp_rating) AND opp_rating>0,false) OR start_ms IS NULL OR start_ms<=0 OR y IS NULL OR y NOT IN(0,1)) bad_base,
            count(*) FILTER(WHERE NOT coalesce(isfinite(rg) AND isfinite(rc) AND isfinite(premium) AND premium>0 AND abs(rc-rg-premium)<=1e-9 AND abs(rg-side_rg)<=1e-9 AND abs(premium-side_premium)<=1e-9,false)) bad_payoff,
            count(*) FILTER(WHERE NOT coalesce(isfinite(opp_stake) AND opp_stake>0 AND isfinite(opp_rg) AND isfinite(opp_rc) AND abs(opp_rc-opp_rg-opp_stake)<=1e-9,false)) missing_or_invalid_recipient_payoff,
            count(*) FILTER(WHERE isfinite(opp_stake) AND isfinite(opp_rg) AND isfinite(opp_rc) AND abs(opp_rc-opp_rg-opp_stake)>1e-9) inconsistent_recipient_payoff,
            count(*) FILTER(WHERE NOT coalesce(isfinite(rd) AND rd>0 AND isfinite(opp_rd) AND opp_rd>0,false)) missing_or_invalid_rd,
            count(*) FILTER(WHERE rating<>replay_rating OR opp_rating<>replay_opp_rating) displayed_replay_rating_disagreements,
            max(abs(start_discrepancy_ms)) max_api_pgn_start_difference_ms
            FROM projected WHERE age_days>=365 AND state>=0""")[0]
        if a['bad_base'] or a['bad_payoff'] or a['inconsistent_recipient_payoff']:
            save_json(report/'preparation_failure.json',a)
            raise RuntimeError('Eligible certified panel has invalid base/payoff fields; see preparation_failure.json')
        # This is the effective E under the audited common-scale payoff representation.
        con.execute("""CREATE OR REPLACE TEMP TABLE eligible AS SELECT * EXCLUDE(opp_stake),
            CASE WHEN isfinite(opp_stake) AND opp_stake>0 AND isfinite(opp_rg) AND isfinite(opp_rc) THEN opp_stake END opp_stake,2*premium k,
            .5-rg/(2*premium) e FROM projected WHERE age_days>=365 AND state>=0""")
        extra=records(con,"""SELECT count(*) FILTER(WHERE e<=0 OR e>=1 OR NOT isfinite(e)) bad_e,
            count(*) FILTER(WHERE NOT coalesce(isfinite(replay_rating) AND isfinite(replay_opp_rating) AND isfinite(opp_rd) AND opp_rd>0,false)) invalid_e_validation_rows,
            count(*) FILTER(WHERE abs(rg)<=1e-9 AND rating=opp_rating) exact_zero_rows,
            max(abs(rc-k*(1-e))) max_common_scale_error,
            max(abs(e-(1/(1+exp(-(replay_rating-replay_opp_rating)/173.7178/sqrt(1+3*pow(opp_rd/173.7178,2)/pow(pi(),2))))))) max_e_glicko_check_difference
            FROM eligible""")[0];a.update(extra);audit.append(a)
        if extra['bad_e']: raise RuntimeError('Effective E outside (0,1)')
        # A discrepant expected-score check blocks precise T5 interpretation, rather than discarding rows.
        copy_parquet(con,'SELECT * FROM eligible',path)
        finish_checkpoint(mr,identity,[path],dict(coverage=cov,audit=a,counts=counts))
    expected=dict(rows=41534331,grants=570091,competitive=15207423,competitive_grants=419463)
    if total!=expected: raise RuntimeError('Certified counts failed reproduction: '+str(total))
    write_csv(report/'creation_date_coverage.csv',cover);write_csv(report/'payoff_audit.csv',audit)
    save_json(report/'preparation_summary.json',dict(certified_counts=total,
        threshold_expected_score_validated=all(a['invalid_e_validation_rows']==0 and
            (a['age_state_rows']==0 or (a['max_e_glicko_check_difference'] is not None and np.isfinite(a['max_e_glicko_check_difference']) and a['max_e_glicko_check_difference']<=1e-6)) for a in audit),
        age_sample_selection='Known creation date in outcome-selected profile acquisition; no population weighting',
        recipient_stake_representation='Recipient-side win-minus-draw premium, equal to draw-minus-loss under the same common-scale replay representation',
        completion_time_warning='api_last_move_at_ms is not used as game completion time'))
    allmonths=parquet(month_paths)
    for b,p in enumerate(out):
        br=work/'base'/f'bucket_{b:03d}.json'
        if not checkpoint_ok(br,identity):
            log(f'Writing complete-chooser shard {b+1}/{buckets}')
            copy_parquet(con,f'SELECT * FROM {allmonths} WHERE chooser%{buckets}={b} ORDER BY chooser,start_ms,game_id',p)
            finish_checkpoint(br,identity,[p])
    finish_checkpoint(receipt,identity,out+[report/'creation_date_coverage.csv',report/'payoff_audit.csv',report/'preparation_summary.json'])
    return out
