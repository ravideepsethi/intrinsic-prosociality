"""Inherited selection rules plus explicit unknown-membership and policy fields."""
import sys
from common import *
sys.path.insert(0,str(PACKAGE/'vendor'))
import audit_logic as inherited
import iv_numerics as num

PANEL_START=int(STARTS[0])
PANEL_END=int(dt.datetime(2026,5,1,tzinfo=dt.timezone.utc).timestamp()*1000)
POLICY_LO=int(dt.datetime(2025,11,18,7,15,tzinfo=dt.timezone.utc).timestamp()*1000)
POLICY_HI=int(dt.datetime(2025,11,18,7,22,tzinfo=dt.timezone.utc).timestamp()*1000)
COUNTS=inherited.COUNTS
pairs=inherited.pairs
moments=inherited.moments
spaced=inherited.spaced

def arrays(t):return {k:arr(t,k) for k in t.column_names}

def window_counts(events,person,start):
    out=inherited.window_counts(events,person,start)
    out['history_window_complete']=np.asarray(start)-97*DAY>=PANEL_START
    return out

def volume_plan(person,start):
    keys=moments(person,start);order=np.argsort(keys,kind='stable')
    return keys[order],order,np.unique(person)

def accumulate_volume(t,w,b,keys,people,delta):
    valid=(t>0)&(w>=0)&(b>=0)&(w!=b)
    t,w,b=t[valid],w[valid],b[valid]
    if not len(keys):return
    for ids in (w,b):
        keep=num.lookup(people,ids)>=0;ids,tt=ids[keep],t[keep]
        lo=np.searchsorted(keys,moments(ids,tt),'right')
        hi=np.searchsorted(keys,moments(ids,tt+30*DAY),'right')
        ok=lo<hi;np.add.at(delta,lo[ok],1);np.add.at(delta,hi[ok],-1)

def finish_volume(delta,order):
    out=np.empty(len(order),np.int64);out[order]=np.cumsum(delta[:-1])
    if delta.sum()!=0 or np.any(out<0):raise RuntimeError('Invalid volume difference array')
    return out

def first_choice(h,q):
    """Original t/ordinal/gid ordering; strict future start, different counterpart."""
    n=len(q['row_id']);order=np.lexsort((h['gid'],h['ord'],h['t'],h['j']))
    h={k:np.asarray(v)[order] for k,v in h.items()};keys=moments(h['j'],h['t'])
    at=np.searchsorted(keys,moments(q['recipient_id'],q['anchor_ms']),'right')
    end=np.searchsorted(keys,moments(q['recipient_id'],q['anchor_ms']+90*DAY),'right')
    out=dict(reached=np.zeros(n,bool),observed_y=np.zeros(n,bool),outcome_gid=np.full(n,'',dtype='U8'),
        outcome_t=np.full(n,-1,np.int64),outcome_start=np.full(n,-1,np.int64),
        outcome_ordinal=np.full(n,-1,np.int64),outcome_opponent=np.full(n,-1,np.int64),
        outcome_color=np.full(n,'',dtype='U5'))
    active=np.flatnonzero(at<end)
    while len(active):
        ix=at[active]
        valid=(h['start'][ix]>q['anchor_ms'][active])&(h['i'][ix]!=q['opponent_id'][active])&(h['gid'][ix]!=q['game_id'][active])
        hit=active[valid];hi=ix[valid];out['reached'][hit]=True;out['observed_y'][hit]=h['y'][hi]
        for name,key in [('outcome_gid','gid'),('outcome_t','t'),('outcome_start','start'),('outcome_ordinal','ord'),('outcome_opponent','i'),('outcome_color','color')]:
            out[name][hit]=h[key][hi]
        active=active[~valid];at[active]+=1;active=active[at[active]<end[active]]
    return out

def outcomes(h,q):
    known=np.asarray(h['known'],bool)
    a=first_choice({k:v[known] for k,v in h.items() if k!='known'},q)
    u=first_choice({k:v[~known] for k,v in h.items() if k!='known'},q)
    # Unknown membership can displace a known first outcome, including tied times.
    before=(u['outcome_t']<a['outcome_t'])|((u['outcome_t']==a['outcome_t'])&
        ((u['outcome_ordinal']<a['outcome_ordinal'])|((u['outcome_ordinal']==a['outcome_ordinal'])&(u['outcome_gid']<a['outcome_gid']))))
    ambiguous=u['reached']&(~a['reached']|before)
    complete=q['anchor_ms']+90*DAY<PANEL_END
    status=np.full(len(complete),'no_observed_later_choice',dtype='U32')
    status[a['reached']&(a['outcome_t']<POLICY_LO)]='pre'
    status[a['reached']&(a['outcome_t']>=POLICY_HI)]='post'
    status[a['reached']&(a['outcome_t']>=POLICY_LO)&(a['outcome_t']<POLICY_HI)]='implementation_bracket'
    # These fields describe the first KNOWN-main later choice. Their qualification
    # flag must be respected when an unresolved choice could precede it.
    return dict(row_id=q['row_id'],**a,complete90_data=complete,outcome_membership_ambiguous=ambiguous,
        first_unknown_choice_gid=u['outcome_gid'],first_unknown_choice_t=u['outcome_t'],
        later_choice_policy_period=status,later_choice_is_identified=a['reached']&~ambiguous)

def selection(q):
    order=np.lexsort((q['game_id'],q['archive_ordinal'],q['archive_start_ms'],q['recipient_id']))
    if not np.array_equal(order,np.arange(len(order))):raise RuntimeError('Unsorted selection queries')
    out={'row_id':q['row_id']}
    for lag in (7,30):
        for floor in (5,10):
            ok=(q[f'n_{lag}d']>=floor)&np.isfinite(q[f'adjusted_{lag}d'])&np.isfinite(q[f'expected_{lag}d'])
            out[f'support_{lag}d_floor{floor}']=ok
            for gap in (30,90):out[f'spaced{gap}_{lag}d_floor{floor}']=spaced(q['recipient_id'],q['archive_start_ms'],q['anchor_ms'],ok,gap)
    out['common5_10_on_primary_stream']=out['spaced90_7d_floor5']&out['support_7d_floor10']
    return out
