"""Frozen row sets and prospective entry risk. No coefficient-dependent choices."""
from __future__ import annotations
import hashlib
import numpy as np
import audit_logic as audit
from preliminary_core import DAY, PANEL_END, STARTS

EXPECTED_ROWS = {'all':7432712, 'spaced30':3838184, 'spaced90':2682330, 'first':967594}
FLAGS = {'all':'support7', 'spaced30':'spaced30', 'spaced90':'spaced90', 'first':'first_recipient'}


def sample_condition(candidate):
    if candidate not in FLAGS: raise ValueError('Unknown candidate')
    return f'complete90 AND support7 AND history_window_complete AND {FLAGS[candidate]}'


def row_digest(ids):
    a=np.asarray(ids,dtype='<i8')
    if len(np.unique(a))!=len(a): raise ValueError('Duplicate row identifiers')
    return hashlib.sha256(np.sort(a).tobytes()).hexdigest()


def repeat_mask(person):
    _, inv, counts=np.unique(person,return_inverse=True,return_counts=True)
    return counts[inv]>=2


def prospective_risk(events, query, gap):
    """Only already anchored selected exposures can close the current risk window.

    This uses the inherited lastMoveAt proxy, not a certified resolution time.
    Selected events include early-history and administratively incomplete rows.
    Eventual exposure status of the queried person is never a restriction.
    Strict anchor < query start; equal-anchor and overlapping-start cases are
    reported. Events starting earlier but anchoring in the future do not enter
    the risk calculation. The target is entry into the audited algorithm's
    sample; that algorithm itself uses recorded start order.
    """
    if gap not in (0,30,90): raise ValueError('Invalid spacing')
    i=np.asarray(query['recipient_id'],np.int64);start=np.asarray(query['archive_start_ms'],np.int64)
    n=len(i)
    if gap==0:
        return dict(at_risk=np.ones(n,bool),previous_selected_anchor=np.full(n,-1,np.int64),
            anchor_tie=np.zeros(n,bool),earlier_started_not_yet_anchored=np.zeros(n,bool))
    ei=np.asarray(events['recipient_id'],np.int64)
    et=np.asarray(events['anchor_ms'],np.int64)
    es=np.asarray(events['archive_start_ms'],np.int64)
    if np.any(et<es): raise ValueError('Selected anchor precedes start')
    order=np.lexsort((et,ei));ei,et,es=ei[order],et[order],es[order]
    keys=audit.moments(ei,et);qkeys=audit.moments(i,start)
    at=np.searchsorted(keys,qkeys,side='left');ix=at-1
    previous=np.full(n,-1,np.int64)
    if len(keys):
        good=(ix>=0)&(ei[np.clip(ix,0,len(ei)-1)]==i)
        previous[good]=et[ix[good]]
        tie=(at<len(keys))&(keys[np.minimum(at,len(keys)-1)]==qkeys)
    else:tie=np.zeros(n,bool)
    # A diagnostic only: do not condition eligibility on a not-yet-anchored event.
    order=np.lexsort((es,ei));si,ss,st=ei[order],es[order],et[order]
    ix=np.searchsorted(audit.moments(si,ss),qkeys,side='left')-1
    pending=np.zeros(n,bool)
    if len(si):
        safe=np.clip(ix,0,len(si)-1)
        pending=(ix>=0)&(si[safe]==i)&(st[safe]>=start)
    risk=(previous<0)|(start>previous+gap*DAY)
    return dict(at_risk=risk,previous_selected_anchor=previous,anchor_tie=tie,
        earlier_started_not_yet_anchored=pending)


def entry_mask(d,gap,calendar=True):
    steps=[];mask=np.ones(len(d['recipient_id']),bool)
    def cut(name,values):
        nonlocal mask
        values=np.asarray(values,bool);mask &= values
        steps.append(dict(step=name,rows=int(mask.sum())))
    cut('observed_previous_nonadjacent_pool',d['eligible_main'])
    cut('score_lag7_floor5',(d['n_7d']>=5)&np.isfinite(d['adjusted_7d'])&np.isfinite(d['expected_7d']))
    cut('complete_97_day_prior_history',d['history_complete'])
    cut('first_observed_pair',d['first_observed_pair'])
    cut('real_time',d['tc_base_s']>0)
    cut(f'past_anchored_exposure_cooldown_{gap}d',d[f'at_risk_{gap}'])
    if calendar:
        cut('90_day_calendar_support_from_start',d['archive_start_ms']+90*DAY<PANEL_END)
    return mask,steps


def specifications():
    # Order and all outputs are frozen before the first coefficient is read.
    out=[]
    for name,candidate,rich,repeat,fe in [
        ('main90_pooled','spaced90',True,False,False),
        ('main90_repeat_pooled','spaced90',True,True,False),
        ('main90_repeat_FE_diagnostic','spaced90',True,True,True),
        ('sensitivity30_pooled','spaced30',True,False,False),
        ('sensitivity_all_pooled','all',True,False,False),
        ('first97_common_controls','first',True,False,False),
        ('main90_without_recipient_history','spaced90',False,False,False),
        ('first97_without_recipient_history','first',False,False,False)]:
        out.append(dict(name=name,family='iv',candidate=candidate,rich=rich,repeat=repeat,fe=fe,
            balance=name in ('main90_pooled','main90_without_recipient_history','main90_repeat_FE_diagnostic')))
    for gap in (90,30,0):
        out.append(dict(name=f'entry{gap}_pooled',family='entry',gap=gap,rich=True,repeat=False,fe=False,balance=gap==90))
    for suffix,rich,repeat,fe in [('without_recipient_history',False,False,False),
                                 ('repeat_pooled',True,True,False),('repeat_FE_diagnostic',True,True,True)]:
        out.append(dict(name='entry90_'+suffix,family='entry',gap=90,rich=rich,repeat=repeat,fe=fe,balance=False))
    out.append(dict(name='ordinary90_placebo',family='ordinary',gap=90,rich=True,repeat=False,fe=False,balance=False))
    return out


def validate_history(d,comparison=False):
    flag='history_complete' if comparison else 'history_window_complete'
    correct=np.asarray(d['archive_start_ms'])-97*DAY>=int(STARTS[0])
    if not np.array_equal(correct,d[flag]):raise ValueError('History coverage flag changed')
    for days in (30,90):
        for name in audit.COUNTS:
            a=np.asarray(d[f'{name}_{days}'])
            if not np.isfinite(a).all() or np.any(a<0) or np.any(a!=np.floor(a)):
                raise ValueError('Invalid historical count: '+name)
        if np.any(d[f'kind_{days}']>d[f'fair_{days}']):raise ValueError('Kindness exceeds opportunities')
        if np.any(d[f'receipt_{days}']+d[f'claim_{days}']>d[f'disconnect_{days}']):
            raise ValueError('Receipt and claim counts exceed disconnections')


def validate_disjoint(d):
    ids=np.asarray(d['outcome_gid'])[np.asarray(d['reached'],bool)]
    if len(np.unique(ids))!=len(ids):raise ValueError('90-day sample reuses outcomes')
    order=np.lexsort((d['archive_start_ms'],d['recipient_id']))
    i=np.asarray(d['recipient_id'])[order];s=np.asarray(d['archive_start_ms'])[order];a=np.asarray(d['anchor_ms'])[order]
    if np.any((i[1:]==i[:-1])&(s[1:]<=a[:-1]+90*DAY)):
        raise ValueError('Selected 90-day exposure windows overlap')
