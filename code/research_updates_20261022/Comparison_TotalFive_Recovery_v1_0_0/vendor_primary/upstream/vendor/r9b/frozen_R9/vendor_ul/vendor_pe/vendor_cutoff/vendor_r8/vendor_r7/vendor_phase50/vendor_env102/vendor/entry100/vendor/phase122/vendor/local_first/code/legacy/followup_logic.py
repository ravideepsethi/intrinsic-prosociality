"""Predetermined histories and eligibility; no outcomes enter these calculations."""
from __future__ import annotations
import numpy as np
import pyarrow as pa
import iv_numerics as num
from preliminary_core import DAY, PANEL_END, STARTS
from rebuild_logic import pair_keys

MOMENT = np.dtype([('person', '<i8'), ('time', '<i8')])
COUNTS = ('fair', 'kind', 'disconnect', 'receipt')


def moments(person, time):
    out = np.empty(len(person), dtype=MOMENT)
    out['person'] = person
    out['time'] = time
    return out


def volume_plan(person, start):
    keys = moments(person, start)
    order = np.argsort(keys, kind='stable')
    return keys[order], order, np.unique(person)


def accumulate_volume(t, w, b, keys, people, delta):
    """Each past game increments every applicable query, including repeated users.

    t belongs to [query_start-30d, query_start), so the affected query starts
    satisfy t < query_start <= t+30d. Difference arrays avoid a many-to-many join.
    """
    valid = (t > 0) & (w >= 0) & (b >= 0) & (w != b)
    t, w, b = t[valid], w[valid], b[valid]
    if not len(keys):
        return
    for ids in (w, b):
        keep = (num.lookup(people, ids) >= 0)
        ids1, tt = ids[keep], t[keep]
        if not len(tt):
            continue
        lo = np.searchsorted(keys, moments(ids1, tt), side='right')
        hi = np.searchsorted(keys, moments(ids1, tt + 30*DAY), side='right')
        ok = lo < hi
        np.add.at(delta, lo[ok], 1)
        np.add.at(delta, hi[ok], -1)


def finish_volume(delta, order):
    result = np.empty(len(order), np.int64)
    result[order] = np.cumsum(delta[:-1])
    if np.any(result < 0) or delta.sum() != 0:
        raise RuntimeError('Invalid volume difference array')
    return result


def accumulate_pairs(t, w, b, keys, earliest):
    valid = (t > 0) & (w >= 0) & (b >= 0) & (w != b)
    t, w, b = t[valid], w[valid], b[valid]
    if not len(keys):
        return
    loc = num.lookup(keys, pair_keys(w, b))
    keep = loc >= 0
    np.minimum.at(earliest, loc[keep], t[keep])


def window_counts(events, person, start):
    """Exact all-source Stage07 counts on [start-97d,start-7d) and last 30d.

    Events may arrive in any file/order and may share timestamps. Search bounds
    and prefix sums count all such rows, without borrowing another user's history.
    """
    order = np.lexsort((events['t'], events['person']))
    keys = moments(events['person'][order], events['t'][order])
    end = np.asarray(start, np.int64) - 7*DAY
    hi = np.searchsorted(keys, moments(person, end), side='left')
    result = {}
    for days in (90, 30):
        lo = np.searchsorted(keys, moments(person, end-days*DAY), side='left')
        for name in COUNTS:
            values = np.asarray(events[name], np.int64)[order]
            if np.any(values < 0):
                raise RuntimeError('Negative historical count')
            total = np.r_[np.int64(0), np.cumsum(values, dtype=np.int64)]
            result[f'{name}_{days}'] = total[hi] - total[lo]
    result['history_complete'] = np.asarray(start) - 97*DAY >= int(STARTS[0])
    return result


def first_event_sql(panel):
    # Identical first-event ranking to the authenticated rebuild, before arm cuts.
    return f'''WITH ranked AS (
      SELECT disconnected_user_id AS recipient_id, game_id, utc_ms AS first_start,
        row_number() OVER (PARTITION BY disconnected_user_id
          ORDER BY utc_ms, archive_ordinal, game_id) AS rn
      FROM {panel} WHERE fair_competitive AND NOT tournament_like_event
    ) SELECT recipient_id, game_id AS first_game_id, first_start
      FROM ranked WHERE rn=1'''


def history_events_sql(parts, targets):
    return f'''WITH raw_events AS (
      SELECT j AS person,t,CAST(fair AS BIGINT) AS fair,
        CAST(fair AND y AS BIGINT) AS kind,0::BIGINT AS disconnect,0::BIGINT AS receipt
        FROM {parts} WHERE fair
      UNION ALL
      SELECT i AS person,t,0::BIGINT,0::BIGINT,1::BIGINT,CAST(y AS BIGINT)
        FROM {parts}
    ) SELECT person,t,sum(fair)::BIGINT AS fair,sum(kind)::BIGINT AS kind,
      sum(disconnect)::BIGINT AS disconnect,sum(receipt)::BIGINT AS receipt,
      (person%16)::INTEGER AS bucket
      FROM raw_events SEMI JOIN (SELECT DISTINCT recipient_id FROM {targets}) q
        ON person=q.recipient_id
      GROUP BY person,t'''


def risk_status(start, game, first_start, first_game, first_pair):
    start = np.asarray(start, np.int64)
    first_start = np.asarray(first_start, np.int64)
    same = np.asarray(game) == np.asarray(first_game)
    missing = first_start < 0
    inconsistent = same & ~missing & (start != first_start)
    if np.any(inconsistent):
        raise RuntimeError('First-event time disagrees with the focal game')
    earlier = ~missing & (first_start < start)
    tie = ~missing & (first_start == start) & ~same
    risk = missing | (start < first_start) | same
    if np.any(risk & (earlier | tie)):
        raise RuntimeError('Inconsistent first-exposure risk set')
    return dict(at_risk_first=risk,earlier_first_event=earlier,
        first_event_tie=tie,first_observed_pair=np.asarray(first_pair)==start)


def controls_and_traits(d, lag, rich=False, rd=False):
    """Identical named controls, transformations and FEs for both populations."""
    controls = []; names = []; missing = {}
    def add(name, v):
        v = np.asarray(v, float).copy()
        bad = ~np.isfinite(v)
        missing[name] = int(bad.sum())
        v[bad] = np.median(v[~bad]) if (~bad).any() else 0.
        sd = float(v.std())
        controls.append((v-v.mean())/(sd if sd > 1e-12 else 1.))
        names.append(name)
        if bad.any() and (~bad).any():
            controls.append(bad.astype(float)); names.append(name+'_missing')
    ir, jr = d['recipient_rating'], d['opponent_rating']
    if not np.isfinite(ir).all() or not np.isfinite(jr).all():
        raise RuntimeError('Pregame displayed ratings missing; retain and investigate')
    gap = (jr-ir)/100.
    for name, value in [('recipient_rating',ir),('rating_gap',gap),
        ('rating_gap_square',gap**2),('abs_rating_gap',abs(gap)),
        ('log_opponent_prior_decisions',np.log1p(d[f'n_{lag}d'])),
        ('log_opponent_prior_counterparts',np.log1p(d[f'counterparts_{lag}d'])),
        ('opponent_history_expected_rate',d[f'expected_{lag}d'])]:
        add(name,value)
    traits = {}
    for days in (90,30):
        fair,kind = d[f'fair_{days}'],d[f'kind_{days}']
        traits[f'fair_history_present_{days}'] = (fair>0).astype(float)
        traits[f'log_fair_{days}'] = np.log1p(fair)
        traits[f'kind_ever_{days}'] = (kind>0).astype(float)
        traits[f'kind_rate_{days}'] = np.divide(kind,fair,out=np.zeros(len(fair),float),where=fair>0)
        traits[f'log_disconnect_{days}'] = np.log1p(d[f'disconnect_{days}'])
        traits[f'log_receipt_{days}'] = np.log1p(d[f'receipt_{days}'])
    traits['log_volume_30'] = np.log1p(d['pre_games_30d'])
    if rich:
        for name in [n for n in traits if n.endswith('_90')] + ['log_volume_30']:
            add(name,traits[name])
    if rd:
        for name in ['recipient_rd','opponent_rd']:
            if not np.isfinite(d[name]).any():
                raise RuntimeError('IV-only RD control unavailable')
            add(name,d[name])
    scaled = []; trait_names = list(traits)
    for name in trait_names:
        v = np.asarray(traits[name],float); sd=float(v.std())
        scaled.append((v-v.mean())/(sd if sd>1e-12 else 1.))
    _, cell = num.factor(d['month_code'],d['tc_base_s'],d['tc_inc_s'],np.floor((ir+jr)/200).astype(np.int64))
    day = d['archive_start_ms']//DAY
    hour = (d['archive_start_ms']//3_600_000)%168
    return controls,names,scaled,trait_names,[cell,day,hour],missing


def analysis_mask(d, family, lag):
    steps=[];mask=np.ones(len(d['recipient_id']),bool)
    def cut(name, test):
        nonlocal mask
        mask &= test
        steps.append(dict(step=name,n=int(mask.sum())))
    cut('new_main_eligibility',d['eligible_main'].astype(bool))
    cut('finite_history_at_least_five',(d[f'n_{lag}d']>=5)&np.isfinite(d[f'adjusted_{lag}d'])&np.isfinite(d[f'expected_{lag}d']))
    cut('complete_97_day_prehistory',d['history_complete'].astype(bool))
    if family == 'iv':
        cut('complete_followup',d['complete90'].astype(bool))
    elif family == 'selection_at_risk':
        cut('not_past_first_fair_main_exposure',d['at_risk_first'].astype(bool))
        cut('first_observed_pair',d['first_observed_pair'].astype(bool))
        cut('real_time',d['tc_base_s']>0)
        cut('complete_followup',d['complete90'].astype(bool))
    elif family.startswith('ordinary'):
        cut('ordinary_end',d['ordinary_broad' if family=='ordinary_broad' else 'ordinary_narrow'].astype(bool))
        cut('complete_followup',d['complete90'].astype(bool))
    elif family != 'selection_all':
        raise ValueError(family)
    return mask,steps
