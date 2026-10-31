"""Unrestricted donor histories on authenticated, frozen receipt/comparison rows."""
from pathlib import Path
import sys, os, time, json
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor_pe/code'))
import pe_common as prior
from pe_common import u, r, np, pa, pq, models, DAY, LEVELS, heartbeat
import pe_runtime as runtime
VERSION = '1.0.0'
PE_CONF = '15a254020647aa905513363104491c30daba5c013d1fa4439579e89b271d254d'
FRAME = {'S0': 0, 'F50': 1}
DEFINITION = 'all_recorded_donor_times_pair_excluded_frozen_monthly_nuisance_controls_fixed_S0_F50_O50'

def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = (ROOT/name).resolve()
        u.require(path.is_relative_to(ROOT), 'Unsafe package member')
        r.io.checked(path, digest)

def authenticate(project, r7root=None, cutoffroot=None, peroot=None):
    paths, binding, parts, reference, cutoff, old = prior.authenticate(project, r7root, cutoffroot)
    pe = Path(peroot) if peroot else project/'derived/replication/iv_placebo_entry_v100_PRIVATE'/PE_CONF[:12]
    expected = u.load(ROOT/'evidence/placebo/summary.json')
    u.require(u.load(pe/'report/summary.json') == expected, 'Completed placebo report differs from reviewed run')
    u.require(expected['configuration_sha256'] == PE_CONF and expected['progress_percent'] == 100,
              'Wrong or unfinished placebo configuration')
    for rec in u.load(ROOT/'evidence/placebo/REPORT_MANIFEST.json'):
        r.io.checked(pe/'report'/rec['path'], rec['sha256'], rec['bytes'])
    for folder in ('scores_combined', 'ordinary_scores'):
        prior.check_stage(pe/folder, PE_CONF, ['scores.parquet'])
    prior.check_stage(pe/'material', PE_CONF, ['summary.json'])
    for sample, n in [('S0', 2682329), ('F50', 7371688), ('O50', 4764089)]:
        u.require(pq.ParquetFile(paths[sample]).metadata.num_rows == n, 'Frozen '+sample+' rows changed')
    return paths, binding, parts, reference, cutoff, pe

def annotations(variant='all_time', screen='all', cohort='frozen'):
    return dict(history_cutoff=variant, exposure_screen=screen, cohort=cohort,
        donor_pair_exclusion='all recorded decisions of j against i, at every time',
        nuisance_reference='frozen_author_clean_monthly_lag7', controls_timing='frozen_R7',
        expanded_exposure_cohort=False, material_screen_changes_donor_history=False,
        estimator_implementation='existing_R7_single_score_2SLS_not_UJIVE',
        generated_scores_treated_as_fixed=True, nuisance_reestimated=False,
        own_pair_direct_leakage_removed=True, full_UJIVE_bias_correction=False,
        residualization_own_observation_bias_ruled_out=False,
        causal_identification_certified=False)

def public_stage(info):
    return {k:v for k,v in info.items() if k not in ('files',)}
