"""Fixed-fit, pre-policy transport. No post-policy input or outcome is accepted."""
from scipy.special import expit, logit
from common import *
from design import design, counterfactual, controls, value

ADVANTAGE = 11.782457
WEEK = 7 * DAY
START = int(pd.Timestamp('2023-11-01T00:00:00Z').timestamp() * 1000)
STOP = int(pd.Timestamp('2025-11-01T00:00:00Z').timestamp() * 1000)
SURVIVORS = ('curved', 'framing', 'strength')


def account_calibration(offset, y, groups, pseudo_count=20.):
    """A separate baseline model, not an estimate delivered by conditional logit.

    First match each account's shrunken pre-policy grant fraction. Then apply
    one common intercept shift to match the aggregate pre-policy grant rate.
    Brackets adapt to the offsets; large sparse-support gap coefficients must
    not silently hit an arbitrary +/-60 intercept limit.
    """
    offset, y = np.asarray(offset, float), np.asarray(y, float)
    groups = np.asarray(groups, int)
    if not len(y) or not np.isin(y, [0, 1]).all() or not np.isfinite(offset).all():
        raise ValueError('Invalid calibration rows')
    base = float(y.mean())
    if not 0 < base < 1:
        raise ValueError('Calibration requires both outcomes')
    if pseudo_count is None:
        relative = offset.copy()
        max_error = None
    else:
        if pseudo_count <= 0:
            raise ValueError('Use a positive shrinkage count')
        n = np.bincount(groups)
        s = np.bincount(groups, weights=y)
        if (n == 0).any():
            raise ValueError('Account codes must be contiguous')
        target = (s + pseudo_count * base) / (n + pseudo_count)
        smallest = np.full(len(n), np.inf)
        largest = np.full(len(n), -np.inf)
        np.minimum.at(smallest, groups, offset)
        np.maximum.at(largest, groups, offset)
        lo = logit(target) - largest - 1.
        hi = logit(target) - smallest + 1.
        for _ in range(48):
            mid = (lo + hi) / 2
            actual = np.bincount(groups, weights=expit(mid[groups] + offset)) / n
            below = actual < target
            lo = np.where(below, mid, lo)
            hi = np.where(below, hi, mid)
        relative = offset + ((lo + hi) / 2)[groups]
        actual = np.bincount(groups, weights=expit(relative)) / n
        max_error = float(np.max(abs(actual - target)))
        if max_error > 1e-8:
            raise RuntimeError('Account baseline calibration did not converge')
    before_global = float(expit(relative).mean())
    lo = float(logit(base) - relative.max() - 1.)
    hi = float(logit(base) - relative.min() + 1.)
    for _ in range(52):
        mid = (lo + hi) / 2
        if expit(relative + mid).mean() < base:
            lo = mid
        else:
            hi = mid
    intercept = (lo + hi) / 2
    result = relative + intercept
    if abs(expit(result).mean() - base) > 1e-9:
        raise RuntimeError('Aggregate baseline calibration did not converge')
    return result, dict(observed_rate_pp=100 * base,
                       predicted_rate_before_global_shift_pp=100 * before_global,
                       predicted_rate_pp=100 * float(expit(result).mean()),
                       global_intercept_shift=intercept,
                       account_target_max_error_before_global_shift=max_error,
                       pseudo_count=pseudo_count,
                       calibration='PRE_POLICY_ACCOUNT_SHRINKAGE_THEN_GLOBAL_RATE_MATCH'
                       if pseudo_count else 'PRE_POLICY_POOLED_INTERCEPT_SENSITIVITY')


def period_groups(d):
    origin = 4 * DAY  # 1970-01-05, Monday, UTC
    wm = ((d.t.to_numpy(np.int64) - origin) // WEEK) * WEEK + origin
    weeks, wi = np.unique(wm, return_inverse=True)
    color = d.color.to_numpy()
    if not np.isin(color, ['white', 'black']).all():
        raise ValueError('Unexpected chooser color')
    group = 2 * wi + (color == 'black').astype(int)
    counts = np.bincount(group, minlength=2 * len(weeks)).reshape(-1, 2)
    complete = (weeks >= START) & (weeks + WEEK <= STOP)
    if (counts[complete] == 0).any():
        raise RuntimeError('A complete calendar week lacks a color; no imputation allowed')
    eligible = weeks[complete]
    if len(eligible) < 32 or np.any(np.diff(eligible) != WEEK):
        raise RuntimeError('Need at least 32 contiguous complete pre-policy weeks')
    # Check absent calendar weeks too, including at the coverage edges.
    first = ((START - origin + WEEK - 1) // WEEK) * WEEK + origin
    last_exclusive = ((STOP - origin) // WEEK) * WEEK + origin
    if not np.array_equal(eligible, np.arange(first, last_exclusive, WEEK)):
        raise RuntimeError('Missing weeks inside certified calendar coverage')
    return dict(weeks=weeks, groups=group, counts=counts, complete=complete)


def weekly_values(grouping, x):
    totals = np.bincount(grouping['groups'], weights=np.asarray(x, float),
                         minlength=grouping['counts'].size).reshape(-1, 2)
    return np.divide(totals, grouping['counts'],
                     out=np.full(totals.shape, np.nan), where=grouping['counts'] > 0)


def offsets(d, f, block_size=75000):
    """Exact index change, updating both actions and both players' premiums."""
    eta = np.empty(len(d))
    delta = np.empty(len(d))
    coefficients = dict(zip(f['names'], f['beta']))
    component_sums = {}
    color_n = {'white': int(d.color.eq('white').sum()), 'black': int(d.color.eq('black').sum())}
    for lo in range(0, len(d), block_size):
        hi = min(len(d), lo + block_size)
        old = d.iloc[lo:hi]
        new = counterfactual(old, advantage=ADVANTAGE)
        X, names, _ = design(old, f['model'], f['curvature'])
        if names != f['names']:
            raise RuntimeError('Frozen model design names changed')
        eta[lo:hi] = X @ np.asarray(f['beta'])
        terms = {}
        if f['model'] == 'curved':
            p = f['curvature']
            terms['utility_cost'] = -((value(new.rc, p) - value(new.rg, p)) -
                                      (value(old.rc, p) - value(old.rg, p)))
        else:
            terms['own_cost'] = -(new.ki.to_numpy() - old.ki.to_numpy())
        terms['opponent_stake'] = new.kj.to_numpy() - old.kj.to_numpy()
        if 'extra_loss' in coefficients:
            terms['extra_loss'] = -np.maximum(-new.rg, 0) + np.maximum(-old.rg, 0)
        if 'draw_frame' in coefficients:
            terms['draw_frame'] = new.rg.to_numpy() - old.rg.to_numpy()
        shift = np.zeros(len(old))
        for term, change in terms.items():
            contribution = coefficients[term] * np.asarray(change)
            shift += contribution
            for color in color_n:
                key = (term, color)
                component_sums[key] = component_sums.get(key, 0.) + contribution[old.color.eq(color)].sum()
        # Displayed g and all controls stay fixed, including time and colors.
        delta[lo:hi] = shift
    if not np.isfinite(eta).all() or not np.isfinite(delta).all():
        raise RuntimeError('Nonfinite fixed-fit prediction')
    components = [dict(term=t, color=c, mean_delta_index=float(v / color_n[c]),
                       rows=color_n[c], meaning='Index change; not a probability-point contribution or mechanism share')
                  for (t, c), v in component_sums.items()]
    return eta, delta, components


def predict_job(d, grouping, groups, fit_spec, fit, key, work):
    label = f"{fit_spec['cohort']}_{fit_spec['model']}_{fit_spec['stage']}"
    out = Path(work) / 'jobs' / (label + '.json')
    if out.exists():
        cached = read(out)
        if cached['key'] != key:
            raise RuntimeError('Cached prediction identity changed: ' + label)
        checksum = cached.pop('payload_sha256')
        if digest(cached) != checksum:
            raise RuntimeError('Cached prediction payload changed: ' + label)
        log('Reusing predictions: ' + label)
        return cached
    log('Predicting: ' + label)
    eta, shift, components = offsets(d, fit)
    variants = [('account20', 20.)]
    if fit_spec['cohort'] == 'rd110' and fit_spec['stage'] == 'full' and fit_spec['model'] in SURVIVORS:
        variants += [('account5', 5.), ('account100', 100.), ('pooled', None)]
    summaries, weeks, calibrations = [], [], []
    common = {k: fit_spec[k] for k in ('cohort', 'stage', 'model')}
    mask = grouping['complete']
    for baseline, pseudo in variants:
        z, calibration = account_calibration(eta, d.y.to_numpy(float), groups, pseudo)
        old = expit(z)
        new = expit(z + shift)
        v = weekly_values(grouping, 100 * (new - old))
        old_w = weekly_values(grouping, 100 * old)
        new_w = weekly_values(grouping, 100 * new)
        calibration.update(**common, baseline=baseline, rows=len(d), accounts=int(groups.max()) + 1,
                           index_shift_max=float(np.max(shift)), index_shift_min=float(np.min(shift)))
        calibrations.append(calibration)
        for i in np.flatnonzero(mask):
            weeks.append(dict(**common, baseline=baseline,
                week=pd.to_datetime(grouping['weeks'][i], unit='ms', utc=True).isoformat(),
                white_shift_pp=v[i, 0], black_shift_pp=v[i, 1], statistic_prediction_pp=v[i, 0] - v[i, 1],
                old_white_rate_pp=old_w[i, 0], old_black_rate_pp=old_w[i, 1],
                new_white_rate_pp=new_w[i, 0], new_black_rate_pp=new_w[i, 1],
                white_n=int(grouping['counts'][i, 0]), black_n=int(grouping['counts'][i, 1])))
        for scope, indexes in [('all_complete_pre', np.flatnonzero(mask)),
                               ('last8_complete_pre', np.flatnonzero(mask)[-8:])]:
            summaries.append(dict(**common, baseline=baseline, target_scope=scope,
                complete_weeks=len(indexes), target_rows=int(grouping['counts'][indexes].sum()),
                white_shift_pp=float(v[indexes, 0].mean()), black_shift_pp=float(v[indexes, 1].mean()),
                statistic_prediction_pp=float((v[indexes, 0] - v[indexes, 1]).mean()),
                old_white_rate_pp=float(old_w[indexes, 0].mean()), old_black_rate_pp=float(old_w[indexes, 1].mean()),
                new_white_rate_pp=float(new_w[indexes, 0].mean()), new_black_rate_pp=float(new_w[indexes, 1].mean()),
                awareness=1., actual_frozen_post_cohort=False,
                interval_status='NO_PARAMETER_CONFIDENCE_INTERVAL; calibration/fold alternatives are sensitivities',
                meaning='Equal-weight weekly White-minus-Black mechanical change, transported from pre-policy states'))
    result = dict(key=key, summaries=summaries, weeks=weeks, calibrations=calibrations,
                  components=[dict(**common, **x) for x in components])
    write(out, dict(**result, payload_sha256=digest(result)))
    return result


def mechanical_summary(d):
    new = counterfactual(d, advantage=ADVANTAGE)
    ownbin = np.where(d.rd < 45.01, 'floor', np.where(d.rd < 60, '45.01_to_60', '60_to_110'))
    segment = np.where(d.g.eq(0), 'displayed_tie',
                       np.where(d.rg.to_numpy() * new.rg.to_numpy() < 0, 'draw_payoff_sign_flip', 'other_gap'))
    rows = []
    for color in ('white', 'black'):
        for rdgroup in ('floor', '45.01_to_60', '60_to_110'):
            for band in ('all', 'displayed_tie', 'draw_payoff_sign_flip', 'other_gap'):
                m = d.color.eq(color).to_numpy() & (ownbin == rdgroup)
                if band != 'all':
                    m &= segment == band
                if not m.any():
                    continue
                dg = (new.rg - d.rg).to_numpy()[m]
                dc = (new.rc - d.rc).to_numpy()[m]
                dk = (new.ki - d.ki).to_numpy()[m]
                dj = (new.kj - d.kj).to_numpy()[m]
                rows.append(dict(color=color, own_rd_bin=rdgroup, band=band, n=int(m.sum()),
                    mean_draw_shift=float(dg.mean()), mean_abs_draw_shift=float(abs(dg).mean()),
                    mean_claim_shift=float(dc.mean()), mean_own_premium_shift=float(dk.mean()),
                    mean_abs_own_premium_shift=float(abs(dk).mean()), mean_opponent_premium_shift=float(dj.mean()),
                    mean_abs_opponent_premium_shift=float(abs(dj).mean()),
                    mean_abs_own_premium_over_mean_abs_draw=float(abs(dk).mean() / abs(dg).mean()),
                    meaning='Rating points at fixed stored pregame state; no claim about displayed integer changes or awareness'))
    return rows
