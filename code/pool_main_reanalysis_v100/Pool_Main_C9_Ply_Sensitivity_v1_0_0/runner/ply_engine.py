"""C9 ply diagnostics with exact original and ply-band-conditional draws."""
from __future__ import annotations
import os
import time
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from runner import common, run_c9 as prior

RULES = ('all', 'outcome_gt4', 'outcome_gt10', 'outcome_gt20', 'anchor_and_outcome_gt10')
LAWS = ('original', 'ply_band_conditioned')
BAND_LABELS = ('00_04','05_10','11_20','21_40','41_80','81_plus','missing')
STRATIFIED_SEED_TAG = (20260911, 1)
FIELDS = ('same7_num','same7_den','later7_num','later7_den','total7_num','total7_den',
          'eligible_anchor_users','same7_users','later7_users')
_WORK = None


def ply_bands(ply):
    ply = np.asarray(ply, dtype=np.float64)
    finite = np.isfinite(ply)
    if np.any(np.isinf(ply)) or np.any(finite & ((ply < 0) | (ply != np.floor(ply)))):
        raise RuntimeError('Ply must be a nonnegative integer or missing')
    bands = np.searchsorted(np.array([4,10,20,40,80]), np.where(finite,ply,0), side='left').astype(np.int8)
    bands[~finite] = 6
    return bands


def draw_choices(selection, k, sims, rng):
    """The original B2/C9 position loop, including all RNG calls."""
    n = selection.shape[0]
    remaining = np.full(sims, k, dtype=np.int32)
    choices = np.zeros((sims, n), dtype=bool)
    for position in range(n):
        left = n - position
        forced = remaining == left
        probability_now = selection[position, remaining]
        chosen = forced | (
            (remaining > 0) & (rng.random(sims) < probability_now)
        )
        choices[:, position] = chosen
        remaining -= chosen.astype(np.int32)
    if np.any(remaining != 0) or np.any(np.count_nonzero(choices, axis=1) != k):
        raise RuntimeError('Conditional sampler did not preserve the fixed total')
    return choices


def masked_totals(times, sessions, ply, choices):
    """Keep the first grant in the complete sequence; restrict anchor/outcome masks.

    Each simulated sequence supplies its own first grant, session and clock.
    In the both-long rule, a short first grant excludes that chooser for that
    draw; it is never replaced by a later long-game grant.
    """
    choices = np.asarray(choices, dtype=bool)
    if not choices.ndim == 2 or np.any(~choices.any(axis=1)):
        raise RuntimeError('Each sequence requires a grant')
    first = choices.argmax(axis=1)
    positions = np.arange(len(times))[None,:]
    within = (positions > first[:,None]) & ((times[None,:]-times[first,None]) <= 604800000)
    same = sessions[None,:] == sessions[first,None]
    valid = np.isfinite(ply)
    outcomes = [np.ones(len(ply),dtype=bool)] + [valid & (ply > k) for k in (4,10,20)] + [valid & (ply > 10)]
    result = {}
    for rule, allowed_outcome in zip(RULES,outcomes):
        anchor = (valid[first] & (ply[first] > 10)) if rule == 'anchor_and_outcome_gt10' else np.ones(len(first),dtype=bool)
        mask = within & allowed_outcome[None,:] & anchor[:,None]
        for label, partition in [('total7',mask),('same7',mask & same),('later7',mask & ~same)]:
            result[rule+'__'+label+'_den'] = partition.sum(axis=1,dtype=np.int64)
            result[rule+'__'+label+'_num'] = (choices & partition).sum(axis=1,dtype=np.int64)
            if label != 'total7':
                result[rule+'__'+label+'_users'] = partition.any(axis=1).astype(np.int64)
        result[rule+'__eligible_anchor_users'] = anchor.astype(np.int64)
    return result


def load_vectors(b1_path, propensity_path, session_path, b2_path):
    b2 = common.load_source_module(Path(b2_path), 'c9_ply_b2_'+str(os.getpid()))
    data, probability = b2.load_inputs(Path(b1_path),Path(propensity_path))
    extra = pq.read_table(b1_path, columns=['b1_row_id','chooser_index','sequence_index','current_ply_count']).to_pandas()
    session = pq.read_table(session_path,columns=['b1_row_id','chooser_index','sequence_index','session_id','speed']).to_pandas()
    session = session.sort_values(['chooser_index','sequence_index'],kind='stable').reset_index(drop=True)
    for name in ('b1_row_id','chooser_index','sequence_index'):
        expected = np.asarray(data[name],dtype=np.int64)
        if not np.array_equal(extra[name].to_numpy(dtype=np.int64),expected):
            raise RuntimeError('B1 ply row alignment mismatch: '+name)
        if not np.array_equal(session[name].to_numpy(dtype=np.int64),expected):
            raise RuntimeError('Session row alignment mismatch: '+name)
    order = np.lexsort((data['sequence_index'],data['chooser_index']))
    if not np.array_equal(order,np.arange(len(order))):
        raise RuntimeError('B1 chooser/sequence order changed')
    if session.session_id.isna().any() or session.speed.isna().any():
        raise RuntimeError('Unresolved session or speed')
    same_user = data['chooser_index'][1:] == data['chooser_index'][:-1]
    if np.any(same_user & (np.diff(data['utc_ms']) < 0)):
        raise RuntimeError('Nonchronological opportunity order')
    ply = extra.current_ply_count.to_numpy(dtype=np.float64,na_value=np.nan)
    return b2,data,probability,session.session_id.to_numpy(dtype=np.int64),session.speed.astype(str).to_numpy(),ply,ply_bands(ply)


def initialize_worker(b1_path, propensity_path, session_path, b2_path):
    global _WORK
    b2,data,probability,sessions,speed,ply,bands = load_vectors(b1_path,propensity_path,session_path,b2_path)
    slices = b2.chooser_slices(data['chooser_index'])
    prepared = []
    for a,z in slices:
        y = data['kind_draw'][a:z]
        k = int(y.sum())
        if k < 2:
            raise RuntimeError('C9 source must remain the fixed repeat-granter cohort')
        odds = np.log(probability[a:z])-np.log1p(-probability[a:z])
        selection = b2.conditional_selection_probabilities(odds,k)
        strata = []
        for band in np.unique(bands[a:z]):
            ix = np.flatnonzero(bands[a:z] == band)
            total = int(y[ix].sum())
            table = b2.conditional_selection_probabilities(odds[ix],total)
            strata.append((ix,total,table))
        prepared.append((a,z,k,selection,strata))
    _WORK = (data,sessions,speed,ply,prepared,prior.load_c9())


def blank_totals(sims):
    output = {}
    for label in ('same7','later7','samepool24','crosspool24'):
        for suffix in ('num','den'):
            output['baseline__'+label+'_'+suffix] = np.zeros(sims,dtype=np.int64)
    for suffix in ('num','den'):
        output['baseline__b2_'+suffix] = np.zeros((sims,3),dtype=np.int64)
    for law in LAWS:
        for rule in RULES:
            for name in FIELDS:
                output[law+'__'+rule+'__'+name] = np.zeros(sims,dtype=np.int64)
    return output


def simulate(start,stop):
    if _WORK is None:
        raise RuntimeError('Worker was not initialized')
    data,sessions,speed,ply,prepared,c9 = _WORK
    sims = stop-start
    rng = np.random.default_rng(np.random.SeedSequence([c9.B2_SEED,start,stop]))
    rng_bands = np.random.default_rng(np.random.SeedSequence([c9.B2_SEED,*STRATIFIED_SEED_TAG,start,stop]))
    output = blank_totals(sims)
    for user,(a,z,k,selection,strata) in enumerate(prepared):
        original = draw_choices(selection,k,sims,rng)
        baseline = c9.c9_totals(data['utc_ms'][a:z],sessions[a:z],speed[a:z],original)
        for name,array in baseline.items():
            output['baseline__'+name] += array
        stratified = np.zeros_like(original)
        for ix,total,table in strata:
            stratified[:,ix] = draw_choices(table,total,sims,rng_bands)
        for law,choices in zip(LAWS,(original,stratified)):
            values = masked_totals(data['utc_ms'][a:z],sessions[a:z],ply[a:z],choices)
            for name,array in values.items():
                output[law+'__'+name] += array
        if (user+1) % 10000 == 0:
            print(f'C9_PLY_PROGRESS batch={start}:{stop} choosers={user+1}/{len(prepared)}',flush=True)
    return output


def observed(data,sessions,speed,ply,c9):
    output = blank_totals(1)
    for a,z in c9._chooser_slices(data['chooser_index']):
        choices = data['kind_draw'][a:z][None,:]
        for name,array in c9.c9_totals(data['utc_ms'][a:z],sessions[a:z],speed[a:z],choices).items():
            output['baseline__'+name] += array
        values = masked_totals(data['utc_ms'][a:z],sessions[a:z],ply[a:z],choices)
        for law in LAWS:
            for name,array in values.items():
                output[law+'__'+name] += array
    return output


def support(data,ply,bands,b2):
    by_band = []
    randomizable_users = set()
    band_user_counts = {i:0 for i in range(len(BAND_LABELS))}
    for user,(a,z) in enumerate(b2.chooser_slices(data['chooser_index'])):
        for band in np.unique(bands[a:z]):
            y = data['kind_draw'][a:z][bands[a:z] == band]
            if 0 < int(y.sum()) < len(y):
                randomizable_users.add(user)
                band_user_counts[int(band)] += 1
    for i,label in enumerate(BAND_LABELS):
        mask = bands == i
        by_band.append({'band':label,'opportunities':int(mask.sum()),'grants':int(data['kind_draw'][mask].sum()),
                        'randomizable_chooser_band_strata':band_user_counts[i]})
    return {'rows':len(ply),'choosers':int(np.unique(data['chooser_index']).size),
            'grants':int(data['kind_draw'].sum()),'missing_ply':int(np.isnan(ply).sum()),
            'choosers_with_any_randomizable_band':len(randomizable_users),'bands':by_band,
            'conditioned_on_observed_chooser_band_grant_counts':True,
            'support_selected_after_viewing_sensitivity_results':False}
