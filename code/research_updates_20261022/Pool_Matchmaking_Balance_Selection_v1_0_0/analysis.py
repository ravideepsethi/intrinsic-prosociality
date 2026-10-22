"""Post-hoc diagnostic specifications; no random-assignment certification."""
from __future__ import annotations

import math
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'source'))
import iv_numerics as num
import comparison_core as inherited

DAY = 86_400_000
NONADJ = 'not_mutually_adjacent_observed'
BALANCE = ('has_prior_fair', 'log_prior_fair', 'prior_kind_ever')
SELECTION = ('active_timeout', 'passive_outoftime', 'any_candidate',
             'recipient_disconnect_main', 'recipient_chooser_main',
             'active_other_role_or_screen', 'recipient_fair_arm_main', 'actual_iv_exposure')
SPECS = (
    dict(name='coarse_context', frame='nonadj_history', fe='coarse', outcomes='both'),
    dict(name='local5_primary', frame='nonadj_history', fe='local5', outcomes='both'),
    dict(name='local1_sensitivity', frame='nonadj_history', fe='local1', outcomes='both'),
    dict(name='local15_sensitivity', frame='nonadj_history', fe='local15', outcomes='both'),
    dict(name='within_focal_sensitivity', frame='nonadj_history', fe='within', outcomes='both'),
    dict(name='history_adjusted_selection', frame='nonadj_history', fe='coarse', outcomes='selection', history=True),
    dict(name='nonlinear_gap_sensitivity', frame='nonadj_history', fe='coarse', outcomes='both', nonlinear=True),
    dict(name='all_dates_nonadj_selection', frame='nonadj', fe='coarse', outcomes='selection'),
    dict(name='active_given_candidate', frame='nonadj_history', fe='coarse', outcomes='candidate', candidate=True),
    dict(name='pool_parent_context', frame='parent_history', fe='coarse', outcomes='parent'),
    dict(name='prior_rate_floor1', frame='nonadj_history', fe='coarse', outcomes='prior_rate', floor=1),
    dict(name='prior_rate_floor5', frame='nonadj_history', fe='coarse', outcomes='prior_rate', floor=5),
)
CONTRACT = {
    'version': '1.0.0', 'analysis_status': 'POST_HOC_DIAGNOSTIC',
    'target_main_rows': 41_534_331,
    'target_main_fingerprint': 'a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30',
    'gap_definition': '(opponent_rating - recipient_rating) / 100; original random focal orientation',
    'history_window': '[archive_start_ms - 97 days, archive_start_ms - 7 days)',
    'history_population': 'original all-source Stage07 opportunity histories, not truncated to new main sample',
    'weights': 'one per sampled game; no ATT or opponent-score support weights',
    'primary_specification': 'local5_primary',
    'own_rating_bin_width': 50, 'fine_time_minutes': [1, 5, 15],
    'absorption_tolerance': 1e-10, 'absorption_max_iterations': 300,
    'minimum_rows_with_gap_variation': 500, 'minimum_identifying_dates': 30,
    'inference': 'shared-account OR game-start-date CR0; normal reference; no covariance repair',
    'nonlinear_basis': ['gap', 'abs_gap', 'gap_squared'],
    'baseline_standardization': 'unconditional SD of each baseline on that model sample',
    'descriptive_equivalence_margin_SD_per_100_rating_points': 0.05,
    'multiplicity': 'all individual p values exploratory and unadjusted; joint baseline test also reported',
    'specifications': list(SPECS),
    'unavailable_in_comparison': ['queue entry/wait', 'conduct score', 'blocking/rating preferences',
                                'pregame RD', 'prior all-game activity', 'current-game kind-grant flag'],
}


def derived(d):
    d = dict(d)
    d['gap'] = (d['opponent_rating'] - d['recipient_rating']) / 100.0
    d['has_prior_fair'] = (d['own_fair90'] > 0).astype(float)
    d['log_prior_fair'] = np.log1p(d['own_fair90'])
    d['prior_kind_ever'] = (d['own_kind90'] > 0).astype(float)
    d['prior_kind_rate'] = np.divide(d['own_kind90'], d['own_fair90'],
        out=np.full(len(d['gap']), np.nan), where=d['own_fair90'] > 0)
    d['any_candidate'] = d['active_timeout'].astype(float) + d['passive_outoftime'].astype(float)
    d['active_other_role_or_screen'] = (d['active_timeout'].astype(float)
        - d['recipient_disconnect_main'].astype(float) - d['recipient_chooser_main'].astype(float))
    return d


def frame_mask(d, spec):
    mask = np.ones(len(d['gap']), bool)
    if spec['frame'].startswith('nonadj'):
        mask &= d['eligible_main']
    if spec['frame'].endswith('history'):
        mask &= d['own_history_complete']
    if spec.get('floor'):
        mask &= d['own_fair90'] >= spec['floor']
    if spec.get('candidate'):
        mask &= d['any_candidate'] == 1
    return mask


def groups(d, mask, kind):
    t = d['archive_start_ms'][mask]
    own = d['recipient_rating'][mask]
    clock = (d['tc_base_s'][mask], d['tc_inc_s'][mask])
    ownbin = np.floor(own / 50).astype(np.int64)
    if kind.startswith('local'):
        minutes = int(kind[5:])
        _, cell = num.factor(t // (minutes * 60_000), *clock, ownbin)
        return [cell]
    _, cell = num.factor(d['month_code'][mask], *clock, ownbin)
    day = t // DAY
    # UTC hour of week; Unix's Thursday origin is a harmless fixed cyclic relabeling.
    hourweek = (t // 3_600_000) % 168
    result = [cell, day, hourweek]
    if kind == 'within':
        result.append(d['recipient_id'][mask])
    return result


def support_inventory(d):
    rows = []
    for frame in ('nonadj_history', 'nonadj', 'parent_history'):
        mask = frame_mask(d, {'frame': frame})
        for minutes in (1, 5, 15):
            for width in (25, 50, 100):
                _, code = num.factor(d['archive_start_ms'][mask] // (minutes * 60_000),
                    d['tc_base_s'][mask], d['tc_inc_s'][mask],
                    np.floor(d['recipient_rating'][mask] / width).astype(np.int64))
                counts = np.bincount(code)
                g = d['gap'][mask]
                lo = np.full(len(counts), np.inf); hi = np.full(len(counts), -np.inf)
                np.minimum.at(lo, code, g); np.maximum.at(hi, code, g)
                varying = hi - lo > 1e-12
                rows.append(dict(frame=frame, minutes=minutes, own_rating_bin_width=width,
                    rows=int(mask.sum()), cells=len(counts), singleton_cells=int((counts == 1).sum()),
                    rows_in_varying_gap_cells=int(counts[varying].sum()),
                    varying_gap_cells=int(varying.sum()),
                    note='outcome-blind support; no automatic model/grid selection'))
    return rows


def shared_meat(scores, codes):
    """Multivariate extension of inherited covariance_meat, with identical union rule."""
    scores = np.asarray(scores, float)
    if scores.ndim == 1:
        scores = scores[:, None]
    def gram(values, key):
        sums = np.column_stack([np.bincount(codes[key], weights=values[:, j])
                                for j in range(values.shape[1])])
        return sums.T @ sums
    both = np.concatenate((scores, scores), axis=0)
    return (gram(both, 'accounts') - gram(scores, 'pairs') + gram(scores, 'dates')
            - gram(both, 'account_dates') + gram(scores, 'pair_dates'))


def wald(beta, cov):
    cov = (cov + cov.T) / 2
    ev = np.linalg.eigvalsh(cov)
    if not np.isfinite(ev).all() or ev.min() <= max(abs(ev).max(), 1e-30) * 1e-10:
        return dict(supported=False, reason='NONPOSITIVE_OR_SINGULAR_COVARIANCE_NOT_REPAIRED')
    stat = float(beta @ np.linalg.solve(cov, beta))
    return dict(supported=True, statistic=stat, df=len(beta), p_value=num.chi2_sf(stat, len(beta)))


def interval(beta, variance):
    ans = dict(estimate=float(beta))
    if not np.isfinite(variance) or variance <= 0:
        return dict(ans, supported=False, reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED')
    se = math.sqrt(variance)
    return dict(ans, supported=True, standard_error=se,
                ci95_low=beta - 1.959963984540054 * se, ci95_high=beta + 1.959963984540054 * se,
                ci90_low=beta - 1.6448536269514722 * se, ci90_high=beta + 1.6448536269514722 * se,
                p_value=math.erfc(abs(beta / se) / math.sqrt(2)))


def linear_fit(x, y, codes):
    gram = x.T @ x
    ev = np.linalg.eigvalsh(gram)
    if ev.min() <= max(ev.max(), 1) * 1e-11:
        raise RuntimeError('GAP_BASIS_NOT_FULL_RANK')
    inv = np.linalg.inv(gram)
    beta = inv @ (x.T @ y)
    residual = y - x @ beta
    influence = (x @ inv) * residual[:, None]
    cov = shared_meat(influence, codes)
    return beta, cov, influence


def residualize(matrix, fe, control_count):
    matrix = np.asarray(matrix, float)
    means = matrix.mean(axis=0); sd = matrix.std(axis=0)
    scale = np.where(sd > 1e-12, sd, 1.0)
    a, iterations = num.absorb((matrix - means) / scale, fe,
        tol=CONTRACT['absorption_tolerance'], max_iter=CONTRACT['absorption_max_iterations'])
    if control_count:
        c, v = a[:, :control_count], a[:, control_count:]
        gram = c.T @ c
        ev, U = np.linalg.eigh(gram)
        keep = ev > max(float(ev.max()), 1.0) * 1e-11
        inv = (U[:, keep] / ev[keep]) @ U[:, keep].T
        v = v - c @ (inv @ (c.T @ v))
        rank = int(keep.sum())
    else:
        v = a; rank = 0
    return v * scale[control_count:], dict(absorb_iterations=iterations, continuous_control_rank=rank)


def fit_spec(d, spec):
    mask = frame_mask(d, spec); n = int(mask.sum())
    meta = dict(specification=spec, n=n, supported=False)
    if n < CONTRACT['minimum_rows_with_gap_variation']:
        return dict(meta, reason='TOO_FEW_ROWS')
    g = d['gap'][mask]
    kind = spec['outcomes']
    names = list(BALANCE + SELECTION if kind == 'both' else SELECTION)
    if kind == 'parent': names = list(BALANCE) + ['eligible_main', 'active_timeout', 'passive_outoftime', 'any_candidate']
    if kind == 'prior_rate': names = ['prior_kind_rate']
    if kind == 'candidate': names = ['active_timeout', 'passive_outoftime', 'recipient_disconnect_main', 'recipient_chooser_main', 'active_other_role_or_screen']
    own = (d['recipient_rating'][mask] - 1500) / 500
    controls = [own, own * own, own * own * own]
    control_names = ['own_rating', 'own_rating_squared', 'own_rating_cubed']
    if spec.get('history'):
        controls.extend(d[name][mask] for name in BALANCE)
        control_names.extend(BALANCE)
    x = np.column_stack([g, abs(g), g * g] if spec.get('nonlinear') else [g])
    xnames = ['gap', 'abs_gap', 'gap_squared'] if spec.get('nonlinear') else ['gap']
    raw_y = np.column_stack([d[name][mask].astype(float) for name in names])
    if not np.isfinite(raw_y).all(): raise RuntimeError('NONFINITE_OUTCOME_IN_FIXED_SAMPLE')
    fe = groups(d, mask, spec['fe'])
    res, info = residualize(np.column_stack(controls + [x, raw_y]), fe, len(controls))
    xr = res[:, :x.shape[1]]; yr = res[:, x.shape[1]:]
    identifying = np.max(abs(xr), axis=1) > 1e-9
    t = d['archive_start_ms'][mask] // DAY
    date_n = np.unique(t[identifying], return_counts=True)[1]
    meta.update(info, control_names=control_names,
        fixed_effect_levels=[len(np.unique(f)) for f in fe],
        rows_with_residual_gap_variation=int(identifying.sum()),
        identifying_dates=len(np.unique(t[identifying])),
        largest_identifying_date_row_share=float(date_n.max()/date_n.sum()) if len(date_n) else None,
        effective_identifying_dates_by_row_share=float(date_n.sum()**2/np.square(date_n.astype(float)).sum()) if len(date_n) else 0,
        focal_accounts=len(np.unique(d['recipient_id'][mask])),
        all_accounts=len(np.unique(np.r_[d['recipient_id'][mask], d['opponent_id'][mask]])),
        residual_gap_sd=float(xr[:, 0].std()))
    if (identifying.sum() < CONTRACT['minimum_rows_with_gap_variation']
            or meta['identifying_dates'] < CONTRACT['minimum_identifying_dates']):
        return dict(meta, reason='INSUFFICIENT_IDENTIFYING_ROWS_OR_DATES')
    codes = inherited.covariance_codes(d['recipient_id'][mask], d['opponent_id'][mask], t)
    estimates = []; baseline_influences = []; baseline_betas = []; betas = {}
    for k, name in enumerate(names):
        b, cov, influence = linear_fit(xr, yr[:, k], codes)
        betas[name] = b
        family = 'balance' if name in BALANCE or name == 'prior_kind_rate' else 'selection'
        out = dict(outcome=name, family=family, mean=float(raw_y[:, k].mean()),
            sd=float(raw_y[:, k].std()), n=n, terms=xnames,
            coefficients=b.tolist(), covariance=cov.tolist(),
            joint_gap_test=wald(b, cov), inference='shared-account OR date CR0')
        contrasts = {'per_100_rating_points': np.array([1.0])}
        if spec.get('nonlinear'):
            contrasts = {'plus100_vs_zero': np.array([1., 1., 1.]),
                'minus100_vs_zero': np.array([-1., 1., 1.]),
                'plus100_vs_minus100': np.array([2., 0., 0.])}
        out['contrasts'] = []
        for label, v in contrasts.items():
            stats = interval(float(v @ b), float(v @ cov @ v))
            out['contrasts'].append(dict(contrast=label, unit='outcome_units', **stats))
            scale = 1 / out['sd'] if family == 'balance' and out['sd'] > 0 else 100.0
            if family == 'balance' and out['sd'] <= 0:
                continue
            standardized = interval(float(v @ b) * scale, float(v @ cov @ v) * scale * scale)
            unit = 'outcome_SD' if family == 'balance' else 'percentage_points'
            if family == 'balance' and not spec.get('nonlinear') and standardized.get('supported'):
                margin = CONTRACT['descriptive_equivalence_margin_SD_per_100_rating_points']
                se = standardized['standard_error']; value = standardized['estimate']
                standardized['descriptive_equivalence_margin'] = margin
                standardized['TOST_p_value'] = max(.5 * math.erfc((value + margin) / se / math.sqrt(2)),
                    .5 * math.erfc((margin - value) / se / math.sqrt(2)))
                standardized['ci90_inside_margin'] = (standardized['ci90_low'] > -margin and standardized['ci90_high'] < margin)
            out['contrasts'].append(dict(contrast=label, unit=unit, **standardized))
        estimates.append(out)
        if name in BALANCE and x.shape[1] == 1:
            baseline_influences.append(influence[:, 0]); baseline_betas.append(b[0])
    meta.update(supported=True, estimates=estimates,
        unsupported_outcome_covariances=[out['outcome'] for out in estimates if not out['joint_gap_test']['supported']])
    if len(baseline_betas) == len(BALANCE):
        covariance = shared_meat(np.column_stack(baseline_influences), codes)
        meta['joint_baseline_test'] = dict(outcomes=list(BALANCE), coefficients=baseline_betas,
            covariance=covariance.tolist(), **wald(np.asarray(baseline_betas), covariance))
    identities = {}
    if all(k in betas for k in ('any_candidate', 'active_timeout', 'passive_outoftime')):
        identities['candidate_minus_active_minus_passive_max_abs'] = float(abs(betas['any_candidate'] - betas['active_timeout'] - betas['passive_outoftime']).max())
    if all(k in betas for k in ('active_timeout', 'recipient_disconnect_main', 'recipient_chooser_main', 'active_other_role_or_screen')):
        identities['active_minus_roles_and_residual_max_abs'] = float(abs(betas['active_timeout'] - betas['recipient_disconnect_main'] - betas['recipient_chooser_main'] - betas['active_other_role_or_screen']).max())
    if identities and max(identities.values()) > 1e-7:
        raise RuntimeError('SAME_SAMPLE_DECOMPOSITION_FAILED')
    meta['coefficient_identities'] = identities
    return meta


def raw_tables(d):
    rows = []
    boundaries = np.array([-2., -1., -.25, .25, 1., 2.])
    labels = ('gap_lt_minus200', 'minus200_to_minus100', 'minus100_to_minus25',
              'minus25_to_25', '25_to_100', '100_to_200', 'gap_ge_200')
    bins = np.searchsorted(boundaries, d['gap'], side='right')
    for frame in ('nonadj_history', 'nonadj', 'parent_history'):
        mask = frame_mask(d, {'frame': frame})
        for k, label in enumerate(labels):
            take = mask & (bins == k); n = int(take.sum())
            if not n: continue
            row = dict(frame=frame, gap_bin=label, n=n, mean_gap_rating_points=float(d['gap'][take].mean() * 100))
            for name in SELECTION:
                row[name + '_count'] = int(d[name][take].sum())
                row[name + '_pct'] = float(d[name][take].mean() * 100)
            known = take & d['own_history_complete']
            has = known & (d['own_fair90'] > 0)
            row.update(history_complete_n=int(known.sum()), prior_rate_defined_n=int(has.sum()),
                prior_kind_ever_pct=float(d['prior_kind_ever'][known].mean() * 100) if known.any() else None,
                mean_prior_kind_rate_pct=float(d['prior_kind_rate'][has].mean() * 100) if has.any() else None)
            rows.append(row)
    return rows
