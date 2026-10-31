"""Chooser families; frozen functions plus resumable fit serialization."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from source import wave3b1_helpers as h
from source import chooser_models_v101 as chooser
from source import postcertification_v100 as add
from source import patron_stage10_common as common


def returned_frame(db, design, snapshot):
    frame = h.load_frames(db, design, snapshot)
    frame = frame.loc[frame.returned.astype(bool)].copy()
    if frame.patron.isna().any():
        raise RuntimeError('Returned profile with missing Patron outcome')
    return frame


def load_reference_models(path):
    """Read the list emitted by Wave3B1's save_collector.

    The shared authority loader intentionally accepts JSON objects only;
    model catalogues have a separate list-of-objects schema.
    """
    models = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(models, list) or not models or not all(isinstance(m, dict) for m in models):
        raise RuntimeError(f'Expected a nonempty JSON list of model objects: {path}')
    return models


def core_reproduction(frame, state, digest, reference, public):
    data, groups, _ = chooser.prepare_features(frame)
    main = data[data.group_ever_kind_fair.astype(bool) & data.group_kind_returned.astype(bool)].copy()
    collector = h.CheckpointCollector(state/'core_gate', digest)
    checks = []
    # Match the existing model names by the frozen specifications, not positions.
    refs = pd.read_csv(reference/'chooser_coefficients.csv')
    models = load_reference_models(reference/'chooser_models.json')
    for label, regressors, standardize in [
        ('fe', ['is_kind_role'], []),
        ('full', ['is_kind_role'] + groups['all'], groups['standardize'])]:
        name = ('main_fair_kind_1to3_01_match_cell_fe_only_HC1' if label=='fe'
                else 'main_fair_kind_1to3_08_all_controls_HC1')
        candidates = [m for m in models if m.get('model')==name and m.get('covariance')=='HC1'
                      and m.get('n')==len(main)
                      and m.get('requested_regressors', m.get('regressors'))==regressors]
        # Frozen public metadata records requested regressors under this key.
        if len(candidates)!=1:
            raise RuntimeError(f'Cannot uniquely identify frozen {label} reproduction: {len(candidates)}')
        source_name = candidates[0]['model']
        expected = refs[(refs.model==source_name)&(refs.variable=='is_kind_role')].iloc[0]
        fit = collector.run(main, name='reproduction_'+label, regressors=regressors,
                            standardize=standardize, estimand_class='reproduction_gate')
        got = fit.coefficients.set_index('variable').loc['is_kind_role']
        for field in ['coefficient_pp','se_pp']:
            if not np.isclose(float(got[field]),float(expected[field]),rtol=1e-7,atol=5e-9):
                raise RuntimeError(f'Wave3B1 {label} {field} did not reproduce')
        checks.append({'model':source_name,'n':len(main),'coefficient_pp':float(got.coefficient_pp),
                       'se_pp':float(got.se_pp),'status':'REPRODUCED'})
    h.save_json(public/'CORE_REPRODUCTION.json', checks)
    return data, main, groups


def rematches(frame, groups, state, digest, public, replicates=100):
    collector = h.CheckpointCollector(state/'rematch_fits', digest)
    rows=[]
    for rep in range(1,replicates+1):
        sample=chooser.deterministic_rematch(frame,rep)
        sizes=sample.groupby('matched_kind_chooser_id',observed=True).agg(
            rows=('is_kind_role','size'), kind=('is_kind_role','sum'))
        if not ((sizes.rows==2)&(sizes.kind==1)).all():
            raise RuntimeError('Alternative control draw is not exactly 1:1')
        raw=common.contrast_from_frame(sample,'is_kind_role')
        estimates={}
        for label, regressors, standardize in [
            ('fe',['is_kind_role'],[]),('full',['is_kind_role']+groups['all'],groups['standardize'])]:
            fit=collector.run(sample,name=f'rematch_{rep:03d}_{label}_HC1',regressors=regressors,
                standardize=standardize,covariance='HC1',estimand_class='rematch_sensitivity')
            c=fit.coefficients.set_index('variable').loc['is_kind_role']
            if c.status!='estimated': raise RuntimeError('Unsupported rematch treatment contrast')
            estimates.update({label+'_gap_pp':float(c.coefficient_pp),label+'_se_pp':float(c.se_pp),
                              label+'_p_two_sided':float(c.p_two_sided_approx)})
        rows.append({'replicate':rep,'root_seed':'20260826','users':len(sample),
            'kind_users':int(sample.is_kind_role.sum()),'controls':int((sample.is_kind_role==0).sum()),
            'unavailable_selected_slot_groups':int(frame.is_kind_role.sum()-sample.is_kind_role.sum()),
            'raw_gap_pp':raw.get('gap_pp'),'raw_p_two_sided':raw.get('pooled_p_two_sided'),**estimates})
        if rep==1 or rep%10==0: h.log(f'REMATCH_PROGRESS {rep}/{replicates}')
    values=pd.DataFrame(rows)
    common.write_csv(public/'rematch_replicates.csv',values)
    summaries=[]
    for label in ['raw','fe','full']:
        v=values[label+'_gap_pp'];p=values[label+'_p_two_sided']
        summaries.append({'estimand':label,'replicates':len(v),'mean_pp':v.mean(),'sd_pp':v.std(ddof=1),
            'minimum_pp':v.min(),'p10_pp':v.quantile(.1),'median_pp':v.median(),'p90_pp':v.quantile(.9),
            'maximum_pp':v.max(),'share_positive':float((v>0).mean()),
            'share_positive_p_below_0_05':float(((v>0)&(p<.05)).mean())})
    common.write_csv(public/'rematch_summary.csv',pd.DataFrame(summaries))
    h.save_collector(public,'rematch',collector)
    return {'replicates':replicates,'models':len(collector.models),'root_seed':20260826}


def postcertification(db, design, snapshot, bins, state, digest, public):
    frame=add.load_analysis_frame(db,snapshot,design,bins)
    frame=frame.loc[frame.returned.astype(bool)].copy()
    if frame.patron.isna().any(): raise RuntimeError('Unknown Patron outcome in observed cohort')
    data,groups,imputation=add.prepare_features(frame)
    h.save_json(public/'postcertification_imputation.json',imputation)
    # Inject only persistence; the model family and numerical estimator stay frozen.
    original=add.Collector
    try:
        add.Collector=lambda: h.CheckpointCollector(state/'postcertification_fits',digest)
        five,support,raw=add.fairness_models(data,groups)
        h.save_collector(public,'five_bin',five)
        common.write_csv(public/'five_bin_support.csv',support)
        common.write_csv(public/'five_bin_raw.csv',raw)
        price,support=add.price_count_rate_models(data,groups)
        h.save_collector(public,'price_count_rate',price)
        common.write_csv(public/'price_count_rate_support.csv',support)
    finally: add.Collector=original
    return {'five_bin_models':len(five.models),'price_count_rate_models':len(price.models),'accounts':len(data),
            'not_estimable_contrasts':sum(r.get('status')!='estimated' for r in five.contrasts+price.contrasts)}
