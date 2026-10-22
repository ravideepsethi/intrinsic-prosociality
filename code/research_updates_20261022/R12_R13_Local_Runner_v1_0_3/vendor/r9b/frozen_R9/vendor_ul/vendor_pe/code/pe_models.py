"""New diagnostic fits, receipt influence reconstruction, common-cluster contrasts."""
from pe_common import *

def receipt_influence(d, sample, level, screen='all'):
    meta = metadata(d, sample, level, screen)
    xs, names, traits, groups = r.feature_design(d, level)
    del traits
    raw = [np.asarray(d[k],float) for k in ('adjusted_7d','y','reached')]
    u.require(all(np.isfinite(x).all() for x in raw), 'Missing receipt score/outcome')
    u.require(all(np.isin(x,[0.,1.]).all() for x in raw[1:]), 'Receipt outcomes are not binary')
    # Only reduced forms are reconstructed; the published receipt IV stays fixed.
    rr, rank = math7.project(xs, raw, groups)
    meta.update(controls=names, continuous_control_rank=rank,
                native_residual_score_SD=float(np.sqrt(np.mean(rr[:,0]**2))))
    meat = math7.covariance(d)
    payload = dict(row_id=d['row_id'], recipient_id=d['recipient_id'], opponent_id=d['opponent_id'], date=d['archive_start_ms']//DAY)
    rows = []
    for col, name in enumerate(('y','reached'),1):
        fit, inf = math7.scalar(rr[:,col], rr[:,0], meat, 100*r.SD['pooled'])
        u.require(inf is not None, 'Receipt has no residual instrument variation')
        rows.append(dict(meta, outcome=name, estimator='reduced_form', **fit))
        payload[name] = 100*r.SD['pooled']*inf
    return {'B_estimates':rows}, payload

def verify_receipt(result, reference, level, screen):
    checks = []
    for got in result['B_estimates']:
        target = [v for v in reference if v['history_cutoff']=='lag24h' and v['exposure_screen']==screen
                  and v['control_level']==level and v['outcome']==got['outcome'] and v['estimator']=='reduced_form']
        u.require(len(target)==1, 'Receipt reference is missing/ambiguous')
        target = target[0]
        for key in ('n','row_set_sha256'): u.require(got[key]==target[key], 'Receipt reconstruction rows changed')
        differences = {}
        for key in ('coefficient_pp','standard_error_pp'):
            u.require(key in got and key in target, 'Receipt reconstruction inference unsupported')
            delta = abs(got[key]-target[key]); differences[key] = delta
            u.require(delta <= 2e-8 + 2e-7*abs(target[key]), 'Receipt RF reconstruction failed: '+key)
        checks.append(dict(control_level=level, exposure_screen=screen, outcome=got['outcome'], passed=True,
                           absolute_differences=differences))
    return checks

def fit_job(job):
    r.threads_one(); u.no_network()
    deps = [job['input'],job['scores']] + ([job['material']] if job.get('material') else [])
    if job['kind']=='receipt_influence': deps += [str(ROOT/'evidence/cutoff/B_estimates.json')]
    def build(tmp):
        d = load_scored(job['input'], job['scores'], job.get('material'), job.get('selection','all'))
        ids = d['row_id'].copy(); n = len(ids)
        if job['kind']=='receipt_influence':
            rows, inf = receipt_influence(d, 'S0', job['level'], job['selection'])
            checks = verify_receipt(rows, u.load(ROOT/'evidence/cutoff/B_estimates.json'), job['level'], job['selection'])
            r.io.js(tmp/'reproduction.json', checks)
        else:
            rows, inf = models.estimate(d, job['kind'], job['sample'], job['level'],
                                       part_a=False, calibration=False, release_inputs=True)
            for table in rows.values():
                for row in table: row.update(history_cutoff='lag24h', exposure_screen=job['selection'],
                    nuisance_reference='frozen_author_clean_monthly_lag7', controls_timing='frozen_R7',
                    expanded_exposure_cohort=False, material_screen_changes_donor_history=False)
            if inf is not None: inf['row_id'] = ids
        r.io.js(tmp/'result.json', rows)
        if inf is not None and job['kind']!='entry': r.io.table(tmp/'influence_PRIVATE.parquet', pa.table(inf))
        return dict(rows=n, sample=job['sample'], kind=job['kind'], control_level=job['level'], exposure_screen=job['selection'])
    return r.stable_stage(Path(job['output']), job['conf'], build, deps)[1]

def contrast_job(job):
    r.threads_one(); u.no_network()
    deps = [str(Path(p)/name) for p in (job['left'],job['right']) for name in ('result.json','influence_PRIVATE.parquet')]
    def build(tmp):
        meta = dict(control_level=job['level'], instrument='pooled', history_cutoff='lag24h',
            exposure_screen=job['selection'], sample='S0_minus_O50', units='percentage points per reference score SD',
            reference_score_SD=r.SD['pooled'], clustering='shared_account_OR_date_CR0', nominal_interim_intervals=True,
            generated_scores_treated_as_fixed=True, diagnostic_after_reviewed_results=True, causal_identification_certified=False,
            comparison_interpretation='Reduced-form difference; not a new IV estimate or an exclusion test that proves validity')
        rows = models.contrast(job['left'], job['right'], meta)
        r.io.js(tmp/'result.json', rows)
        return dict(contrasts=len(rows))
    return r.stable_stage(Path(job['output']), job['conf'], build, deps)[1]
