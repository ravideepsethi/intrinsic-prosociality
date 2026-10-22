"""Outcome levels, explicitly weighted histories, and score-band first stages."""
from __future__ import annotations
from common import *
import math
import expanded_stats as design
import iv_numerics as num
import comparison_core as cmp
import followup_stats as stats

def outcome_levels(d):
    D, Y, R = [np.asarray(d[k], bool) for k in ('received', 'y', 'reached')]
    if np.any(Y & ~R):
        raise RuntimeError('Y must be zero outside R=1')
    rows = []
    for label, mask in [('all', np.ones(len(D), bool)), ('claim_D0', ~D), ('grant_D1', D)]:
        n, y, r = int(mask.sum()), int(Y[mask].sum()), int(R[mask].sum())
        rows.append(dict(group=label, N=n, Y_ones=y, R_ones=r,
                         mean_Y=y/n if n else None, mean_R=r/n if n else None,
                         mean_Y_given_R=y/r if r else None,
                         mean_Y_percent=100*y/n if n else None,
                         mean_R_percent=100*r/n if n else None,
                         mean_Y_given_R_percent=100*y/r if r else None))
    return rows

def historical_grants(d):
    """Recover integer S from n * (Z + expected), with strict integer checks."""
    n = np.asarray(d['n_7d'], float)
    z, expected = np.asarray(d['adjusted_7d'], float), np.asarray(d['expected_7d'], float)
    if not np.isfinite(n).all() or np.any(n < 5) or np.any(n != np.rint(n)):
        raise RuntimeError('Historical denominators must be supported integers')
    if not np.isfinite(expected).all() or np.any((expected < -1e-10) | (expected > 1+1e-10)):
        raise RuntimeError('Invalid expected grant rate')
    raw = z + expected
    count = n * raw
    rounded = np.rint(count)
    if not np.isfinite(count).all() or np.max(abs(count-rounded), initial=0) > 1e-6:
        raise RuntimeError('Cannot recover integer historical grants from Z + expected')
    if np.any((rounded < 0) | (rounded > n)):
        raise RuntimeError('Recovered grant count outside [0,n]')
    return rounded.astype(np.int64), rounded/n

def weighted_quantiles(x, w, probs=(.1, .5, .9)):
    """Inverse weighted empirical CDF; no interpolation, ties stay together."""
    x, w = np.asarray(x, float), np.asarray(w, float)
    if len(x) == 0 or np.any(w < 0) or not np.isfinite(x).all() or not np.isfinite(w).all() or w.sum() <= 0:
        raise ValueError('Invalid weighted distribution')
    order = np.argsort(x, kind='stable')
    mass = np.cumsum(w[order])
    ix = np.searchsorted(mass, np.asarray(probs) * mass[-1], side='left')
    return x[order[np.minimum(ix, len(x)-1)]]

def score_distribution(d):
    grants, raw = historical_grants(d)
    z = np.asarray(d['adjusted_7d'], float)
    opponents, inverse, counts = np.unique(d['opponent_id'], return_inverse=True, return_counts=True)
    order = np.lexsort((d['row_id'], d['archive_start_ms'], d['opponent_id']))
    first = order[np.r_[True, np.diff(d['opponent_id'][order]) != 0]]
    rules = [
        ('exposure_weighted', np.arange(len(z)), np.ones(len(z)),
         'One observation per frozen IV exposure; relevant history varies by month and excluded recipient.'),
        ('equal_opponent_weight_across_exposures', np.arange(len(z)), 1.0/counts[inverse],
         'Each observed opponent has total weight one, divided equally across their eligible exposure rows.'),
        ('one_snapshot_per_opponent', first, np.ones(len(first)),
         'Each observed opponent once, at their earliest eligible exposure; ties break by frozen row_id.')]
    rows, hist = [], []
    for population, ix, w, rule in rules:
        for name, x in [('adjusted_score_Z', z[ix]), ('raw_historical_grant_rate', raw[ix])]:
            q = weighted_quantiles(x, w)
            mean = float(np.average(x, weights=w))
            rows.append(dict(population=population, variable=name, observations=len(ix),
                             distinct_opponents=len(opponents), weight_sum=float(w.sum()),
                             zero_grant_history_share=float(np.average(grants[ix] == 0, weights=w)),
                             p10=float(q[0]), p50=float(q[1]), p90=float(q[2]), mean=mean,
                             SD=float(np.sqrt(np.average((x-mean)**2, weights=w))),
                             minimum=float(x.min()), maximum=float(x.max()), rule=rule,
                             quantiles='inverse_weighted_empirical_CDF'))
            # Common full-support bins, so no tails are dropped from charts.
            lo, hi = (float(z.min()), float(z.max())) if name == 'adjusted_score_Z' else (0., 1.)
            if hi <= lo:
                lo, hi = lo-.0005, hi+.0005
            edges = np.linspace(lo, hi, 61)
            values, _ = np.histogram(x, bins=edges, weights=w)
            for k, mass in enumerate(values):
                hist.append(dict(population=population, variable=name, bin=k+1,
                                 left=float(edges[k]), right=float(edges[k+1]),
                                 weight=float(mass), share=float(mass/w.sum())))
    return rows, hist, dict(distinct_opponents=len(opponents), exposure_rows=len(z),
                            maximum_integer_recovery_error=float(np.max(abs(d['n_7d']*(z+d['expected_7d'])-grants))),
                            universe='Supported opponents appearing in this frozen cohort; not the platform-wide universe.',
                            never_granted_lifetime_inferred=False)

def quantile_bands(z, requested):
    if not 2 <= requested <= 20:
        raise ValueError('Choose 2 to 20 score bands')
    cuts = np.unique(np.quantile(z, np.arange(1, requested)/requested))
    provisional = np.searchsorted(cuts, z, side='left')
    _, code = np.unique(provisional, return_inverse=True)
    return code, dict(requested_bands=requested, actual_bands=int(code.max()+1),
                      cutpoints=cuts.tolist(), ties='Identical score values are never split; empty bands are dropped.')

def fit_matrix(y, x, codes):
    gram = x.T @ x
    eig = np.linalg.eigvalsh(gram)
    if eig[0] <= max(float(eig[-1]), 1.)*1e-11:
        raise RuntimeError('Band model is rank deficient after the original controls/FEs')
    inv = np.linalg.inv(gram)
    beta = inv @ (x.T @ y)
    residual = y - x @ beta
    meat = stats.shared_meat(x * residual[:, None], codes, True)
    covariance = inv @ meat @ inv
    return beta, residual, covariance, inv

def joint_zero(beta, covariance):
    ev, U = np.linalg.eigh(covariance)
    cutoff = max(float(np.max(abs(ev))), 1e-30)*1e-9
    if ev.min() < -cutoff:
        return dict(supported=False, reason='NON_PSD_COVARIANCE_NOT_REPAIRED')
    use = ev > cutoff
    if int(use.sum()) != len(beta):
        return dict(supported=False, reason='SINGULAR_CONTRAST_COVARIANCE', rank=int(use.sum()))
    statistic = float(np.sum((U.T @ beta)**2 / ev))
    return dict(supported=True, wald_chi2=statistic, df=len(beta),
                p_value_asymptotic=num.chi2_sf(statistic, len(beta)))

def first_stage_bands(d, requested=10, expected=None):
    z = np.asarray(d['adjusted_7d'], float)
    D = np.asarray(d['received'], float)
    band, meta = quantile_bands(z, requested)
    K = meta['actual_bands']
    if K < 2:
        raise RuntimeError('Fewer than two distinct score bands')
    # The upstream function supplies the exact 15 controls and the three FEs.
    xs, names, _, _, groups, missing = design.controls(d, True)
    B = np.column_stack([(band == k).astype(float) for k in range(1, K)])
    raw = np.column_stack(xs + [z, D] + [B[:, k] for k in range(K-1)])
    del xs
    residual, absorb_info = num.partial_out(raw, groups, len(names))
    del raw
    rz, rd, rB = residual[:, 0], residual[:, 1], residual[:, 2:]
    codes = cmp.covariance_codes(d['recipient_id'], d['opponent_id'], groups[1])
    linear = stats.ols(rd, rz, lambda s: stats.shared_meat(s, codes, True))
    linear['native_residual_score_SD'] = float(np.sqrt(np.mean(rz**2)))
    if expected is not None:
        for key in ('coefficient', 'standard_error', 'native_residual_score_SD'):
            if key not in linear or abs(linear[key]-expected[key]) > 2e-8:
                raise RuntimeError(f'Frozen first-stage reproduction failed for {key}: {linear.get(key)} vs {expected[key]}')
    beta, err, covariance, inv = fit_matrix(rd, rB, codes)
    shares = B.mean(axis=0)
    C = np.vstack([np.zeros(K-1), np.eye(K-1)]) - shares[None, :]
    adjusted = D.mean() + C @ beta
    # Centered-design intercept is D.mean(). Cluster its influence jointly
    # with the band coefficients, using the saturated-band model residual.
    scores = np.column_stack([err/len(D), rB * err[:, None]])
    transform = np.column_stack([np.ones(K), C @ inv])
    band_cov = transform @ stats.shared_meat(scores, codes, True) @ transform.T
    del scores
    band_eig = np.linalg.eigvalsh(band_cov)
    band_psd = bool(band_eig.min() >= -1e-9*max(float(np.max(abs(band_eig))), 1e-30))
    rows = []
    for k in range(K):
        m = band == k
        variance = float(band_cov[k, k])
        se = math.sqrt(variance) if band_psd and variance > 0 else None
        rows.append(dict(band=k+1, N=int(m.sum()), receipts=int(D[m].sum()),
                         Z_min=float(z[m].min()), Z_max=float(z[m].max()), Z_mean=float(z[m].mean()),
                         Z_mean_reference_SD=float(z[m].mean()/REFERENCE_SD),
                         raw_receipt_percent=float(100*D[m].mean()),
                         adjusted_receipt_percent=float(100*adjusted[k]),
                         adjusted_SE_pp=None if se is None else 100*se,
                         adjusted_CI95_low_percent=None if se is None else 100*(adjusted[k]-stats.CRIT*se),
                         adjusted_CI95_high_percent=None if se is None else 100*(adjusted[k]+stats.CRIT*se),
                         linear_prediction_percent=float(100*(D.mean()+linear['coefficient']*(z[m].mean()-z.mean())))))
    # Nested diagnostic: add all K-1 band dummies to the continuous linear
    # first stage. The robust joint test asks whether those steps are zero.
    aug_x = np.column_stack([rz/REFERENCE_SD, rB])
    aug_beta, _, aug_cov, _ = fit_matrix(rd, aug_x, codes)
    nonlinear = joint_zero(aug_beta[1:], aug_cov[1:, 1:])
    nonlinear.update(test='H0: all score-band steps are zero after continuous Z and the original X/FEs',
                     diagnostic_only=True, formal_monotonicity_test=False,
                     maximum_absolute_adjusted_minus_linear_pp=max(abs(r['adjusted_receipt_percent']-r['linear_prediction_percent']) for r in rows))
    return rows, dict(**meta, linear_first_stage=stats.effect_row(linear, 100*REFERENCE_SD),
                      nonlinearity=nonlinear, continuous_controls=names,
                      missing_control_counts=missing, assignment_cells=len(np.unique(groups[0])),
                      exposure_dates=len(np.unique(groups[1])), **absorb_info,
                      band_covariance_psd=band_psd,
                      band_model='D ~ score-band indicators + original controls + original additive fixed effects',
                      adjusted_means='Dbar + (band dummy vector - full-sample dummy means) times band coefficients; common empirical covariate/FE distribution',
                      linear_predictions='Dbar + original linear slope * (band mean Z - full-sample mean Z)',
                      clustering='shared_account_OR_date_CR0; pointwise 95% normal intervals; scores and cutpoints treated as fixed',
                      reference_SD=REFERENCE_SD,
                      negative_probabilities_clipped=False,
                      proves_individual_monotonicity=False)

def make_plots(directory, cohort):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return dict(status='CSV_READY_PLOTS_NOT_CREATED', reason='Matplotlib unavailable in selected Python')
    directory = Path(directory)
    title = {'headline_original': 'Original headline IV sample',
             'run3_author_clean': 'Author-excluded Run 3 sample'}.get(cohort, cohort)
    rows = io.load(directory/'score_distribution.json')
    hist = io.load(directory/'score_histogram.json')
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    pops = [('exposure_weighted', 'Each exposure'), ('one_snapshot_per_opponent', 'Each opponent: first eligible snapshot')]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    for ax, (population, label) in zip(axes, pops):
        h = [v for v in hist if v['population'] == population and v['variable'] == 'adjusted_score_Z']
        ax.bar([100*v['left'] for v in h], [100*v['share'] for v in h],
               width=[100*(v['right']-v['left']) for v in h], align='edge', color='#176b87')
        s = next(v for v in rows if v['population'] == population and v['variable'] == 'adjusted_score_Z')
        ax.set(title=label, xlabel='State-adjusted historical score (×100)', ylabel='Share (%)')
        ax.text(.98, .96, f"Zero grants in relevant history: {100*s['zero_grant_history_share']:.2f}%",
                transform=ax.transAxes, ha='right', va='top', fontsize=9)
    fig.suptitle(title + ' · score distribution', fontsize=12)
    for ext in ('png', 'svg'):
        fig.savefig(directory/f'score_histogram.{ext}', dpi=180)
    plt.close(fig)
    bands = io.load(directory/'first_stage_bands.json')
    fig, ax = plt.subplots(figsize=(8.5, 5.3), constrained_layout=True)
    x = [r['Z_mean_reference_SD'] for r in bands]
    ax.plot(x, [r['raw_receipt_percent'] for r in bands], 'o--', color='#91979b', label='Raw band mean')
    ax.plot(x, [r['linear_prediction_percent'] for r in bands], '-', color='#be6c27', label='Original linear first stage')
    y = np.array([r['adjusted_receipt_percent'] for r in bands])
    ax.plot(x, y, 'o-', color='#176b87', label='Adjusted band mean')
    intervals_available = all(r['adjusted_SE_pp'] is not None for r in bands)
    if intervals_available:
        ax.errorbar(x, y, yerr=[stats.CRIT*r['adjusted_SE_pp'] for r in bands],
                    fmt='none', color='#176b87', capsize=3)
    ax.set(xlabel='Mean historical score in band / fixed reference SD',
           ylabel='Receipt probability (%)', title=title + ' · first stage by score band')
    ax.legend(frameon=False)
    uncertainty = ('Pointwise 95% clustered intervals.' if intervals_available else
                   'Clustered intervals unavailable: covariance check failed.')
    fig.text(.5, -.02, 'Same controls and fixed effects as the cohort first stage. '+uncertainty,
             ha='center', fontsize=8)
    for ext in ('png', 'svg'):
        fig.savefig(directory/f'first_stage_bands.{ext}', dpi=180, bbox_inches='tight')
    plt.close(fig)
    return dict(status='PNG_AND_SVG_CREATED')
