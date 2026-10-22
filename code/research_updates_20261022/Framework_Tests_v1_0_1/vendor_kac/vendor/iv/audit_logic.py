"""Exposure, spacing and outcome rules; no treatment-effect estimation."""
from __future__ import annotations
import numpy as np
import iv_numerics as num
from preliminary_core import DAY, STARTS, PANEL_END, SPEEDS

COUNTS=('fair','kind','disconnect','receipt','claim')

def pairs(a,b):
    a=np.asarray(a,np.int64);b=np.asarray(b,np.int64)
    if np.any((a<0)|(b<0)|(a>=2**32)|(b>=2**32)|(a==b)):
        raise ValueError('Invalid numeric account pair')
    return (np.minimum(a,b).astype(np.uint64)<<np.uint64(32))|np.maximum(a,b).astype(np.uint64)

def exposure_sql(panel):
    return f'''WITH e AS (
      SELECT game_id,disconnected_user_id::BIGINT AS recipient_id,chooser_user_id::BIGINT AS opponent_id,
        utc_ms::BIGINT AS archive_start_ms,api_last_move_at_ms::BIGINT AS anchor_ms,
        archive_ordinal,kind_draw AS received,(kind_draw OR timeout_chooser_win) AS arm_eligible,
        api_speed AS speed,tc_base_s,tc_inc_s,disconnected_elo::DOUBLE AS recipient_rating,
        chooser_elo::DOUBLE AS opponent_rating,disconnected_pre_rd_v2 AS recipient_rd,
        chooser_pre_rd_v2 AS opponent_rd,
        date_diff('month',DATE '2023-11-01',strptime(month||'-01','%Y-%m-%d'))::BIGINT AS month_code
      FROM {panel} WHERE fair_competitive AND NOT tournament_like_event
    ), r AS (
      SELECT *,row_number() OVER(PARTITION BY recipient_id ORDER BY archive_start_ms,archive_ordinal,game_id)=1 AS first_recipient,
        row_number() OVER(ORDER BY recipient_id,archive_start_ms,archive_ordinal,game_id)-1 AS row_id FROM e
    ) SELECT *,anchor_ms+{90*DAY}<{PANEL_END} AS complete90,
      least(recipient_id,opponent_id)::UBIGINT*4294967296+greatest(recipient_id,opponent_id)::UBIGINT AS pair_key
      FROM r ORDER BY row_id'''

def realtime_sql():
    return 'speed IN ('+','.join("'"+s+"'" for s in SPEEDS)+') AND tc_base_s>0'

def accumulate_pairs(t,w,b,keys,earliest):
    valid=(t>0)&(w>=0)&(b>=0)&(w<2**32)&(b<2**32)&(w!=b)
    t,w,b=t[valid],w[valid],b[valid]
    pos=num.lookup(keys,pairs(w,b));ok=pos>=0
    np.minimum.at(earliest,pos[ok],t[ok])

def moments(person,t):
    a=np.empty(len(person),dtype=[('person','<i8'),('time','<i8')])
    a['person']=person;a['time']=t;return a

def window_counts(events,person,start):
    order=np.lexsort((events['t'],events['person']))
    keys=moments(events['person'][order],events['t'][order]);end=np.asarray(start,np.int64)-7*DAY
    hi=np.searchsorted(keys,moments(person,end),'left');out={}
    for days in (90,30):
        lo=np.searchsorted(keys,moments(person,end-days*DAY),'left')
        for name in COUNTS:
            v=np.asarray(events[name],np.int64)[order]
            if np.any(v<0):raise ValueError('Negative historical count')
            total=np.r_[np.int64(0),np.cumsum(v,dtype=np.int64)]
            out[f'{name}_{days}']=total[hi]-total[lo]
    out['history_window_complete']=np.asarray(start)-97*DAY>=int(STARTS[0])
    return out

def history_sql(parts,queries):
    return f'''WITH events AS (
      SELECT j AS person,t,fair::BIGINT AS fair,(fair AND y)::BIGINT AS kind,
        0::BIGINT AS disconnect,0::BIGINT AS receipt,0::BIGINT AS claim FROM {parts} WHERE fair
      UNION ALL
      SELECT i AS person,t,0::BIGINT,0::BIGINT,1::BIGINT,y::BIGINT,(arm AND NOT y)::BIGINT FROM {parts}
    ) SELECT person,t,sum(fair)::BIGINT AS fair,sum(kind)::BIGINT AS kind,
       sum(disconnect)::BIGINT AS disconnect,sum(receipt)::BIGINT AS receipt,sum(claim)::BIGINT AS claim,
       (person%16)::INTEGER AS bucket
       FROM events SEMI JOIN (SELECT DISTINCT recipient_id FROM {queries}) q ON person=q.recipient_id
       GROUP BY person,t'''

def later_outcomes(h,q):
    """h contains ONLY certified-main fair choices, already filtered by the caller.

    Vectorized first eligible choice; ties retain the original t/ordinal/gid order.
    Observed flags remain separate from completeness. Unknown Y is not made zero.
    """
    n=len(q['row_id']);order=np.lexsort((h['gid'],h['ord'],h['t'],h['j']))
    hh={k:np.asarray(v)[order] for k,v in h.items()}
    keys=moments(hh['j'],hh['t'])
    at=np.searchsorted(keys,moments(q['recipient_id'],q['anchor_ms']),'right')
    end=np.searchsorted(keys,moments(q['recipient_id'],q['anchor_ms']+90*DAY),'right')
    out=dict(row_id=q['row_id'],observed_y=np.zeros(n,bool),reached=np.zeros(n,bool),
             outcome_gid=np.full(n,'',dtype='U8'),outcome_t=np.full(n,-1,np.int64),
             outcome_start=np.full(n,-1,np.int64),outcome_opponent=np.full(n,-1,np.int64))
    active=np.flatnonzero(at<end)
    while len(active):
        ix=at[active]
        valid=(hh['start'][ix]>q['anchor_ms'][active])&(hh['i'][ix]!=q['opponent_id'][active])&(hh['gid'][ix]!=q['game_id'][active])
        hit=active[valid];hi=ix[valid]
        out['reached'][hit]=True;out['observed_y'][hit]=hh['y'][hi]
        for name,key in [('outcome_gid','gid'),('outcome_t','t'),('outcome_start','start'),('outcome_opponent','i')]:out[name][hit]=hh[key][hi]
        active=active[~valid];at[active]+=1;active=active[at[active]<end[active]]
    return out

def spaced(person,start,anchor,eligible,gap_days):
    """Greedy date/past-only selection, BEFORE the administrative follow-up cut.

    Queries must be in deterministic person/start/ordinal/game order. The next
    chosen exposure must START strictly after the earlier chosen anchor+gap.
    Unsupported cases never start a window; future outcomes never enter this rule.
    """
    n=len(person);out=np.zeros(n,bool)
    if n==0:return out
    if np.any(np.diff(person)<0) or np.any((np.diff(person)==0)&(np.diff(start)<0)):
        raise ValueError('Spacing queries must be sorted by recipient and start')
    if np.any(anchor<start):raise ValueError('Anchor precedes game start')
    if gap_days==0:return np.asarray(eligible,bool).copy()
    if gap_days<0:raise ValueError('Negative spacing')
    prev=None;next_start=-1
    for k in np.flatnonzero(eligible):
        if person[k]!=prev:prev=person[k];next_start=-1
        if start[k]>next_start:
            out[k]=True;next_start=int(anchor[k])+gap_days*DAY
    return out

def support_sql(lag,floor):
    return f'n_{lag}d>={floor} AND isfinite(adjusted_{lag}d) AND isfinite(expected_{lag}d)'

def candidates():
    return [('all_7d_floor5','complete90 AND support7'),
            ('spaced30_7d_floor5','complete90 AND spaced30'),
            ('spaced90_7d_floor5','complete90 AND spaced90'),
            ('first_reference_7d_floor5','complete90 AND support7 AND first_recipient')]
