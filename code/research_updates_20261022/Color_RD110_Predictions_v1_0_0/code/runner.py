"""Authenticated preparation and finite reporting from existing analysis files."""
import shutil
from common import *
from predictions import START, STOP, SURVIVORS, period_groups, weekly_values, predict_job, mechanical_summary
from power import calculate_power, placebo_table

FIELDS = ('game_id', 'chooser', 't', 'month', 'color', 'speed', 'ply', 'cp',
          'clock', 'opp_clock', 'history_days', 'prior_starts', 'inactivity_days',
          'opp_prior_starts', 'rating', 'opp_rating', 'rd', 'opp_rd', 'g', 'ki', 'kj', 'rg', 'rc', 'y')


def prepare(source, work, reference, threads=4, memory_mb=3072):
    source, work = Path(source), Path(work)
    identity = read(source / 'RUN_IDENTITY.json')
    if identity.get('package_sha256') != reference['mechanism_package_sha256']:
        raise RuntimeError('Mechanism cache package identity differs from the reviewed run')
    paths, ledger = [], []
    for r in reference['inputs']:
        p = source / 'analysis' / (r['month'] + '.parquet')
        verified = auth(p, work, r['sha256'], size=r['size'])
        paths.append(p)
        ledger.append(dict(path=str(p), sha256=verified['sha256'], bytes=p.stat().st_size,
                           role='Reviewed pre-policy analysis cache'))
    if [r['month'] for r in reference['inputs']] != list(MONTHS):
        raise RuntimeError('Expected exactly November 2023 through October 2025')
    key = digest(dict(inputs=ledger, fields=FIELDS, selection='regular/equal/both_RD_le110'))
    path = work / 'prepared' / 'regular_equal_rd110.parquet'
    receipt = path.with_suffix('.json')
    if path.exists() and receipt.exists():
        r = read(receipt)
        if r['key'] != key:
            raise RuntimeError('Prepared transport sample identity changed')
        auth(path, work, r['sha256'], rows=r['rows'])
        log('Reusing authenticated RD-capped transport rows')
    else:
        c = connect(work / 'tmp', threads=threads, memory_mb=memory_mb)
        try:
            fields = ','.join('"' + f + '"' for f in FIELDS)
            copy(c, f"SELECT {fields} FROM {scan(paths)} WHERE regular IS TRUE AND state='equal' "
                    "AND rd<=110 AND opp_rd<=110 ORDER BY chooser,t,game_id", path)
        finally:
            c.close()
        write(receipt, dict(key=key, sha256=sha(path), rows=pq.ParquetFile(path).metadata.num_rows))
    d = pd.read_parquet(path)
    if d.game_id.duplicated().any() or d.chooser.isna().any():
        raise RuntimeError('Duplicate game keys or missing chooser IDs')
    numeric = ['t', 'ply', 'cp', 'rating', 'opp_rating', 'rd', 'opp_rd', 'g', 'ki', 'kj', 'rg', 'rc', 'y']
    if not np.isfinite(d[numeric].to_numpy(float)).all():
        raise RuntimeError('Missing required numeric state')
    actual = dict(n=len(d), grants=int(d.y.sum()), accounts=d.chooser.nunique())
    if actual != reference['expected']:
        raise RuntimeError('Transport population differs from the reviewed capped sample: ' + str(actual))
    if not (d.t.ge(START) & d.t.lt(STOP) & d.ply.gt(10) & d.cp.ge(-100) & d.cp.lt(100) &
            d.g.ge(-575) & d.g.lt(575) & d.rd.between(45, 110) & d.opp_rd.between(45, 110) &
            d.ki.gt(0) & d.kj.gt(0) & d.y.isin([0, 1])).all():
        raise RuntimeError('Stored rows violate frozen time, state, gap, RD, or outcome restrictions')
    if not np.allclose(d.g, d.opp_rating - d.rating, atol=1e-9, rtol=0):
        raise RuntimeError('Displayed rating gap mismatch')
    calculated_month = pd.to_datetime(d.t, unit='ms', utc=True).dt.strftime('%Y-%m')
    if not np.array_equal(calculated_month.to_numpy(), d.month.to_numpy()):
        raise RuntimeError('Row month differs from UTC timestamp')
    max_error = check_payoffs(d)
    for col in ('month', 'color', 'speed'):
        d[col] = d[col].astype('category')
    log(f"Prepared {len(d):,} capped opportunities; {int(d.y.sum()):,} grants; payoff parity checked")
    return d, ledger, dict(**actual, payoff_max_absolute_error=max_error,
                          source_coverage_start_utc='2023-11-01T00:00:00Z',
                          source_coverage_end_exclusive_utc='2025-11-01T00:00:00Z')


def pre_tables(d, grouping, public):
    grant_rates = weekly_values(grouping, 100 * d.y.to_numpy(float))
    grants = np.bincount(grouping['groups'], weights=d.y.to_numpy(float),
                        minlength=grouping['counts'].size).reshape(-1, 2)
    rows = []
    for i in np.flatnonzero(grouping['complete']):
        rows.append(dict(week=pd.to_datetime(grouping['weeks'][i], unit='ms', utc=True).isoformat(),
            white_n=int(grouping['counts'][i, 0]), black_n=int(grouping['counts'][i, 1]),
            white_grants=int(grants[i, 0]), black_grants=int(grants[i, 1]),
            white_rate_pp=grant_rates[i, 0], black_rate_pp=grant_rates[i, 1],
            white_minus_black_pp=grant_rates[i, 0] - grant_rates[i, 1]))
    weekly = pd.DataFrame(rows)
    table(weekly, public / 'pre_policy_weekly.parquet')
    monthly = d.groupby('month', observed=True).agg(n=('y', 'size'), grants=('y', 'sum'),
                                                   choosers=('chooser', 'nunique')).reset_index()
    monthly['grants'] = monthly.grants.astype(int)
    monthly['base_rate_pp'] = 100 * monthly.grants / monthly.n
    table(monthly, public / 'monthly_support.parquet')
    return weekly


def figures(predictions, thresholds, public):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels = dict(curved='Curved utility', framing='Draw framing', strength='Displayed gap')
    p = predictions[(predictions.cohort == 'rd110') & (predictions.stage == 'full') &
                    (predictions.baseline == 'account20') & (predictions.model.isin(SURVIVORS))]
    fig, ax = plt.subplots(figsize=(9, 4.6), layout='constrained')
    x = np.arange(3)
    for shift, scope, label, marker in [(-.06, 'all_complete_pre', 'All complete pre-policy weeks', 'o'),
                                      (.06, 'last8_complete_pre', 'Last eight complete pre-policy weeks', 's')]:
        vals = p[p.target_scope == scope].set_index('model').loc[list(SURVIVORS)].statistic_prediction_pp
        ax.scatter(vals, x + shift, s=52, label=label, marker=marker, zorder=3)
    limits = [r['mde_80pct_pp'] for r in thresholds]
    if limits:
        for sign in (-1, 1):
            a, b = sorted([sign * min(limits), sign * max(limits)])
            ax.axvspan(a, b, color='#b7bdc7', alpha=.25)
            ax.axvline(sign * min(limits), color='#7d8591', ls=':', lw=1)
        ax.plot([], [], color='#7d8591', lw=7, alpha=.35, label='Planning MDE range across horizons/blocks')
    ax.axvline(0, color='black', lw=.8)
    ax.set_yticks(x, [labels[s] for s in SURVIVORS])
    ax.invert_yaxis()
    ax.set_xlabel('Predicted change in weekly White-minus-Black grant rate (percentage points)')
    ax.set_title('RD≤110 fits: full-awareness pre-policy transport\nFixed fitted parameters; no post-policy estimate or confidence intervals')
    ax.grid(axis='x', alpha=.2)
    ax.legend(loc='best', fontsize=8)
    for ext in ('png', 'pdf'):
        fig.savefig(public / ('Figure_color_predictions.' + ext), dpi=180)
    plt.close(fig)


def execute(source, work, public, reference, package_identity, threads=4, memory_mb=3072, reps=10000):
    work, public = Path(work), Path(public)
    public.mkdir(parents=True, exist_ok=True)
    d, ledger, support = prepare(source, work, reference, threads, memory_mb)
    identity = dict(package_sha256=package_identity, reference=reference,
                    source_inputs=ledger, power_repetitions=reps)
    p = work / 'RUN_IDENTITY.json'
    if p.exists() and read(p) != identity:
        raise RuntimeError('This output cache belongs to different inputs or code')
    write(p, identity)
    run_key = digest(identity)
    grouping = period_groups(d)
    groups, _ = pd.factorize(d.chooser, sort=False)
    weekly = pre_tables(d, grouping, public)
    table(mechanical_summary(d), public / 'mechanical_dose_summary.parquet')
    results, coefficient_rows = [], []
    for spec in reference['fits']:
        path = ROOT / spec['file']
        if sha(path) != spec['sha256']:
            raise RuntimeError('Frozen reviewed fit checksum mismatch')
        f = read(path)
        if f['status'] != 'ESTIMATED' or f['model'] != spec['model']:
            raise RuntimeError('Invalid frozen candidate fit')
        key = digest(dict(run=run_key, fit=spec))
        result = predict_job(d, grouping, groups, spec, f, key, work)
        results.append(result)
        ledger.append(dict(path=spec['file'], sha256=spec['sha256'], bytes=path.stat().st_size,
                           role='Reviewed fixed coefficient snapshot'))
        for term, beta, boundary in zip(f['names'], f['beta'], f['boundary']):
            coefficient_rows.append(dict(cohort=spec['cohort'], model=spec['model'], stage=spec['stage'],
                term=term, beta=beta, constrained_boundary=bool(boundary), curvature=f['curvature'],
                interval_status='BOUNDARIES_MARKED; NO_ORDINARY_WALD_INTERVALS_USED'))
    for key, filename in [('summaries', 'model_predictions'), ('weeks', 'prediction_by_week'),
                          ('calibrations', 'baseline_calibration'), ('components', 'index_shift_components')]:
        table([row for result in results for row in result[key]], public / (filename + '.parquet'))
    predictions = pd.DataFrame([row for r in results for row in r['summaries']])
    thresholds, single, pairwise = calculate_power(predictions, weekly, reps=reps)
    table(thresholds, public / 'planning_MDE.parquet')
    table(single, public / 'single_model_power.parquet')
    table(pairwise, public / 'pairwise_power.parquet')
    table(placebo_table(weekly), public / 'fixed_date_placebos.parquet')
    table(coefficient_rows, public / 'coefficients_used.parquet')
    table(ledger, public / 'input_checksums.parquet')
    main = predictions[(predictions.cohort == 'rd110') & (predictions.stage == 'full') &
                       (predictions.baseline == 'account20')]
    table(main, public / 'PRIMARY_READOUT.parquet')
    old = predictions[(predictions.cohort == 'original') & (predictions.stage == 'full')].copy()
    joined = old.merge(main, on=['model', 'baseline', 'target_scope'], suffixes=('_old_fit', '_capped_fit'))
    if len(joined):
        joined['change_in_prediction_pp'] = joined.statistic_prediction_pp_capped_fit - joined.statistic_prediction_pp_old_fit
    table(joined, public / 'same_sample_old_vs_corrected.parquet')
    figures(predictions, thresholds, public)
    support.update(pre_complete_weeks=len(weekly), week_start=str(weekly.week.min()), week_end=str(weekly.week.max()))
    write(public / 'SUPPORT.json', support)
    relevant = [r for r in pairwise if r['awareness'] == 1 and r['target_scope'] == 'all_complete_pre'
                and r['model_a'] in SURVIVORS and r['model_b'] in SURVIVORS]
    return dict(status='PRE_POLICY_TRANSPORT_COMPLETE_POST_POLICY_TEST_OPEN', support=support,
        new_candidate_fits=0, fixed_fit_snapshots=len(reference['fits']), calibration_predictions=len(predictions),
        conditional_full_awareness_pairwise_screen=[{k: r[k] for k in (
            'model_a', 'model_b', 'post_weeks', 'block_weeks', 'predicted_difference_pp',
            'mde_80pct_pp', 'conditional_planning_power', 'passes_80pct_mde_screen')} for r in relevant],
        formal_behavioral_go_decision='NOT_MADE', post_policy_outcomes_read=False,
        parameter_uncertainty='NOT_PROPAGATED; fold and baseline sensitivities are not confidence intervals',
        awareness='ASSUMED_RESPONDER_MIXTURE; NOT_MEASURED', mechanism_shares_released=False,
        upstream_history_or_rating_replay=False, visibility='UNIDENTIFIED')
