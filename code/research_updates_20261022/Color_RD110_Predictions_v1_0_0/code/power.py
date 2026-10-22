"""Pre-policy moving-block planning distributions, not a post-policy test."""
from common import *
from predictions import WEEK, SURVIVORS

AWARENESS = (0.05, 0.1, 0.2, 0.5, 1.0)
PLACEBOS = ('2024-02-05', '2024-03-18', '2024-05-06', '2024-06-17',
            '2024-08-05', '2024-09-16', '2024-11-04', '2024-12-16',
            '2025-02-03', '2025-03-17', '2025-05-05', '2025-07-07')


def block_noise(series, before=8, after=4, block=4, reps=10000, seed=2026092607):
    x = np.asarray(series, float)
    if len(x) < max(32, 2 * block) or not np.isfinite(x).all():
        raise ValueError('Insufficient contiguous finite pre-policy weeks')
    rng = np.random.default_rng(seed + 100 * block + after)
    need = before + after
    starts = rng.integers(0, len(x) - block + 1, size=(reps, int(np.ceil(need / block))))
    draws = x[(starts[:, :, None] + np.arange(block)).reshape(reps, -1)[:, :need]]
    stat = draws[:, before:].mean(axis=1) - draws[:, :before].mean(axis=1)
    return stat - stat.mean()


def empirical_mde(noise):
    noise = np.asarray(noise, float)
    critical = float(np.quantile(abs(noise), .95, method='higher'))
    if critical == 0 or np.std(noise) == 0:
        raise ValueError('Degenerate planning noise distribution')
    def power(effect):
        return min(np.mean(abs(noise + effect) > critical), np.mean(abs(noise - effect) > critical))
    lo, hi = 0., max(1., 10 * np.std(noise))
    while power(hi) < .8:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if power(mid) < .8:
            lo = mid
        else:
            hi = mid
    return float(hi), critical


def calculate_power(predictions, weekly, reps=10000):
    primary = predictions[(predictions.cohort == 'rd110') & (predictions.stage == 'full') &
                          (predictions.baseline == 'account20')]
    weekly = weekly.sort_values('week')
    if len(weekly) < 32 or np.any(np.diff(pd.to_datetime(weekly.week, utc=True).astype('int64')) != WEEK * 1000000):
        raise ValueError('Power series must contain contiguous complete weeks')
    values = weekly.white_minus_black_pp.to_numpy(float)
    thresholds, single, pairwise = [], [], []
    for after in (4, 8):
        for block in (4, 8):
            noise = block_noise(values, after=after, block=block, reps=reps)
            mde, critical = empirical_mde(noise)
            shared = dict(pre_weeks=8, post_weeks=after, block_weeks=block,
                          bootstrap_repetitions=reps, mde_80pct_pp=mde, critical_5pct_pp=critical,
                          planning_noise_sd_pp=float(np.std(noise, ddof=1)),
                          fitted_parameters_treated_as_fixed=True, actual_frozen_post_cohort=False)
            thresholds.append(dict(**shared, noise_complete_weeks=len(weekly),
                null_rejection_frequency=float(np.mean(abs(noise) > critical)),
                scope='Pre-policy rolling-regular cohort; not the matched policy-event MDE'))
            # Single-model departures from zero; awareness is a probability mixture.
            for _, row in predictions[(predictions.cohort == 'rd110') & (predictions.stage == 'full')].iterrows():
                for awareness in AWARENESS:
                    effect = awareness * row.statistic_prediction_pp
                    single.append(dict(**shared, model=row.model, baseline=row.baseline,
                        target_scope=row.target_scope, awareness=awareness,
                        predicted_shift_pp=effect, effect_over_mde=abs(effect) / mde,
                        conditional_planning_power=float(np.mean(abs(noise + effect) > critical)),
                        passes_80pct_mde_screen=bool(abs(effect) >= mde)))
            # Pairwise contrasts are essential: a shift from zero is not model separation.
            for scope, part in primary.groupby('target_scope', sort=True):
                part = part.sort_values('model').reset_index(drop=True)
                for i in range(len(part)):
                    for j in range(i + 1, len(part)):
                        a, b = part.iloc[i], part.iloc[j]
                        for awareness in AWARENESS:
                            effect = awareness * (a.statistic_prediction_pp - b.statistic_prediction_pp)
                            pairwise.append(dict(**shared, target_scope=scope, model_a=a.model, model_b=b.model,
                                baseline='account20', awareness=awareness, predicted_difference_pp=effect,
                                effect_over_mde=abs(effect) / mde,
                                conditional_planning_power=float(np.mean(abs(noise + effect) > critical)),
                                passes_80pct_mde_screen=bool(abs(effect) >= mde),
                                awareness_assumption='Same exogenous responder fraction for both candidates'))
    return thresholds, single, pairwise


def placebo_table(weekly):
    indexed = weekly.copy()
    indexed.index = pd.to_datetime(indexed.week, utc=True)
    rows = []
    for date in PLACEBOS:
        start = pd.Timestamp(date, tz='UTC')
        for after in (4, 8):
            pre_dates = pd.date_range(start - pd.Timedelta(weeks=8), periods=8, freq='7D')
            post_dates = pd.date_range(start, periods=after, freq='7D')
            required = pre_dates.union(post_dates)
            complete = required.isin(indexed.index).all()
            row = dict(placebo_monday=date, pre_weeks=8, post_weeks=after, complete=bool(complete),
                       status='DESCRIPTIVE_FIXED_DATE_PLACEBO' if complete else 'INCOMPLETE_WINDOW',
                       meaning='Pre-policy rolling cohort; neither a post-event result nor an independent randomization test')
            if complete:
                row['shift_pp'] = float(indexed.loc[post_dates].white_minus_black_pp.mean() -
                                        indexed.loc[pre_dates].white_minus_black_pp.mean())
                row['pre_opportunities'] = int(indexed.loc[pre_dates, ['white_n', 'black_n']].sum().sum())
                row['post_opportunities'] = int(indexed.loc[post_dates, ['white_n', 'black_n']].sum().sum())
            rows.append(row)
    return rows
