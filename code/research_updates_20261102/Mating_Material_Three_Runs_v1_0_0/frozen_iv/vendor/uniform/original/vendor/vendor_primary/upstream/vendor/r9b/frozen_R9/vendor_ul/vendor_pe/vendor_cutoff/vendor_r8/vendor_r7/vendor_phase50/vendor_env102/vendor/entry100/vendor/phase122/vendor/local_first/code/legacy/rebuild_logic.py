"""New exposure selection, chronology summaries, and outcomes for the revised main sample."""
from __future__ import annotations
import numpy as np
import pyarrow as pa
import iv_numerics as num
from local_io import arr
from preliminary_core import DAY,PANEL_END,STARTS,MONTHS,SPEEDS

NONADJ='not_mutually_adjacent_observed'

def exposure_sql(panel):
    # Rank before the treatment-arm, first-pair, realtime and follow-up cuts.
    # Someone whose first qualifying event fails a later cut is not moved forward.
    return f'''WITH ranked AS (
      SELECT *,row_number() OVER(PARTITION BY disconnected_user_id
        ORDER BY utc_ms,archive_ordinal,game_id) AS rn
      FROM {panel} WHERE fair_competitive AND NOT tournament_like_event
    ) SELECT row_number() OVER(ORDER BY disconnected_user_id)-1 AS target_row,
      game_id,disconnected_user_id AS recipient_id,chooser_user_id AS chooser_id,
      utc_ms AS archive_start_ms,api_last_move_at_ms AS anchor_ms,archive_ordinal,
      date_diff('month',DATE '2023-11-01',strptime(month||'-01','%Y-%m-%d')) AS month_code,
      kind_draw AS received,(kind_draw OR timeout_chooser_win) AS arm_eligible,
      api_speed AS speed,tc_base_s,tc_inc_s,
      chooser_elo AS exposure_chooser_elo,disconnected_elo AS exposure_recipient_elo,
      chooser_pre_rd_v2 AS exposure_chooser_rd,disconnected_pre_rd_v2 AS exposure_recipient_rd,
      engine_eval_cp_disconnected AS exposure_eval_cp,ply_count AS exposure_ply_count,
      chooser_clock_last_obs_s AS exposure_chooser_clock_s,
      disconnected_clock_last_obs_s AS exposure_recipient_clock_s
      FROM ranked WHERE rn=1 ORDER BY target_row'''

def pair_keys(a,b):
    a=np.asarray(a,np.int64);b=np.asarray(b,np.int64)
    if np.any((a<0)|(b<0)|(a>=2**32)|(b>=2**32)|(a==b)):raise RuntimeError('Invalid numeric account pair')
    return (np.minimum(a,b).astype(np.uint64)<<np.uint64(32))|np.maximum(a,b).astype(np.uint64)

def chronology_accumulate(t,w,b,qids,qstart,keys,pre,mins):
    valid=(t>0)&(w>=0)&(b>=0)&(w!=b)
    t,w,b=t[valid],w[valid],b[valid]
    for ids in (w,b):
        pos=num.lookup(qids,ids);ok=pos>=0;p=pos[ok];delta=qstart[p]-t[ok]
        keep=(delta>0)&(delta<=30*DAY)
        np.add.at(pre,p[keep],1)
    if len(keys):
        k=pair_keys(w,b);pos=num.lookup(keys,k);ok=pos>=0
        np.minimum.at(mins,pos[ok],t[ok])

def adjacency_candidates_sql(events,queries):
    # Only strict start predecessors matter when order is unambiguous. A tie at
    # the focal or predecessor start is explicitly ambiguous, as in rematch_logic.
    return f'''WITH users AS (SELECT DISTINCT user_id FROM {queries}),
      endpoints AS (
        SELECT game_id,utc_ms,white_id AS user_id,black_id AS opponent_id FROM {events}
        WHERE white_id IN (SELECT user_id FROM users)
        UNION ALL
        SELECT game_id,utc_ms,black_id AS user_id,white_id AS opponent_id FROM {events}
        WHERE black_id IN (SELECT user_id FROM users)
      ), moments AS (
        SELECT user_id,utc_ms,count(*) AS multiplicity,min(game_id) AS gid,
          min(opponent_id) AS opponent_id FROM endpoints GROUP BY 1,2
      ), prior AS (
        SELECT q.sample_row,q.role,q.user_id,q.opponent_id,q.game_id,q.archive_start_ms,
          m.utc_ms AS prev_t,m.multiplicity AS prev_count,m.gid AS prev_gid,
          m.opponent_id AS prev_opponent
        FROM {queries} q ASOF LEFT JOIN moments m
          ON q.user_id=m.user_id AND q.archive_start_ms>m.utc_ms
      ), exact AS (
        SELECT q.sample_row,q.role,count(e.game_id) AS focal_time_count,
          count(e.game_id) FILTER(WHERE e.game_id=q.game_id AND e.opponent_id=q.opponent_id) AS focal_matches
        FROM {queries} q LEFT JOIN endpoints e
          ON q.user_id=e.user_id AND q.archive_start_ms=e.utc_ms GROUP BY 1,2
      ) SELECT p.*,x.focal_time_count,x.focal_matches
        FROM prior p JOIN exact x USING(sample_row,role)
        WHERE p.prev_t IS NOT NULL OR x.focal_time_count>0'''

def adjacency_final_sql(parts,q):
    return f'''WITH mx AS (SELECT sample_row,role,max(prev_t) AS max_t FROM {parts} GROUP BY 1,2),
      r AS (SELECT c.sample_row,c.role,max(m.max_t) AS prev_t,
          sum(c.prev_count) FILTER(WHERE c.prev_t=m.max_t) AS prev_count,
          min(c.prev_gid) FILTER(WHERE c.prev_t=m.max_t) AS prev_gid,
          min(c.prev_opponent) FILTER(WHERE c.prev_t=m.max_t) AS prev_opponent,
          sum(c.focal_time_count) AS focal_time_count,sum(c.focal_matches) AS focal_matches
        FROM {parts} c JOIN mx m USING(sample_row,role) GROUP BY 1,2)
      SELECT q.sample_row,CASE
        WHEN coalesce(a.focal_matches,0)<>1 OR coalesce(b.focal_matches,0)<>1 THEN 'unmapped_or_inconsistent_focal'
        WHEN a.focal_time_count>1 OR b.focal_time_count>1 OR a.prev_count>1 OR b.prev_count>1 THEN 'ambiguous_start_order'
        WHEN a.prev_t IS NULL OR b.prev_t IS NULL THEN 'left_boundary_unresolved'
        WHEN a.prev_gid=b.prev_gid AND a.prev_t=b.prev_t AND a.prev_opponent=q.opponent_id
          AND b.prev_opponent=q.recipient_id THEN 'mutual_adjacency_candidate_timing_unresolved'
        ELSE '{NONADJ}' END AS previous_classification_status
      FROM {q} q LEFT JOIN r a ON q.sample_row=a.sample_row AND a.role=0
        LEFT JOIN r b ON q.sample_row=b.sample_row AND b.role=1'''

def fresh_outcomes(h,q,eligible):
    """Earliest fair different-opponent eligible decision; first game started after anchor.
    Histories remain broad. Y is unknown without complete follow-up; stored observed
    flags are accompanied by complete90 and never used as zero for incomplete rows.
    """
    n=len(q['sample_row']);out=dict(sample_row=q['sample_row'],
      complete90=q['anchor_ms']+90*DAY<PANEL_END,
      reached=np.zeros(n,bool),y=np.zeros(n,bool),outcome_t=np.full(n,-1,np.int64),
      outcome_start=np.full(n,-1,np.int64),outcome_opponent=np.full(n,-1,np.int64),
      outcome_gid=np.full(n,'',dtype='U8'),own_fair_n=np.zeros(n,np.int64),own_kind_n=np.zeros(n,np.int64),
      prior_disconnects=np.zeros(n,np.int64),prior_receipts=np.zeros(n,np.int64))
    ix=np.flatnonzero(h['fair'])
    ix=ix[np.lexsort((h['gid'][ix],h['ord'][ix],h['t'][ix],h['j'][ix]))]
    ids=h['j'][ix];lo=np.searchsorted(ids,q['recipient_id'],'left');hi=np.searchsorted(ids,q['recipient_id'],'right')
    for k in range(n):
        rows=ix[lo[k]:hi[k]];tt=h['t'][rows];end=q['archive_start_ms'][k]-7*DAY
        prior=rows[np.searchsorted(tt,end-90*DAY,'left'):np.searchsorted(tt,end,'left')]
        out['own_fair_n'][k]=len(prior);out['own_kind_n'][k]=int(h['y'][prior].sum())
        anchor=q['anchor_ms'][k]
        a=np.searchsorted(tt,anchor,'right');b=np.searchsorted(tt,anchor+90*DAY,'right')
        for e in rows[a:b]:
            if not eligible[e] or h['i'][e]==q['opponent_id'][k] or h['start'][e]<=anchor or h['gid'][e]==q['game_id'][k]:continue
            out['reached'][k]=True;out['y'][k]=h['y'][e]
            for x,z in [('outcome_t','t'),('outcome_start','start'),('outcome_opponent','i'),('outcome_gid','gid')]:out[x][k]=h[z][e]
            break
    return out

def primary_cohort_mask(q,first_t):
    return (q['arm_eligible'].astype(bool)&np.isin(q['speed'],list(SPEEDS))&(q['tc_base_s']>0)
      &(first_t==q['archive_start_ms'])&(q['anchor_ms']+90*DAY<PANEL_END))
