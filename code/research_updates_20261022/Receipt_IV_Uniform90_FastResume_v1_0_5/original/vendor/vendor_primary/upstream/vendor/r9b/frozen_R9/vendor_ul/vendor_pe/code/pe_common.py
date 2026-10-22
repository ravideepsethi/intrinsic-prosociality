"""Incremental diagnostics bound to the reviewed R7 and cutoff/material runs."""
from pathlib import Path
import sys, os, time, json, contextlib, threading
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor_cutoff/code'))
import iv_common as previous
from iv_common import u, r, np, pa, pq, models, DAY
import r7_math as math7
VERSION = '1.0.0'
CUTOFF_CONF = 'ef68f2376383a5a4b88682e568f8345ae527cc618aba7fee8eddef3d189faa8d'
LEVELS = ('X0', 'X0_ENV_indicator')

def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = (ROOT/name).resolve()
        u.require(path.is_relative_to(ROOT), 'Unsafe package path')
        r.io.checked(path, digest)

def check_stage(path, conf, files):
    r.env_common.checked_stage_files(Path(path), conf, files)

def authenticate(project, r7root=None, cutoffroot=None):
    paths, binding, parts, reference = previous.bind(project, r7root)
    r7root = Path(r7root) if r7root else project/u.R7_REL
    cutoff = Path(cutoffroot) if cutoffroot else project/'derived/replication/iv_cutoff_material_v100_PRIVATE'/CUTOFF_CONF[:12]
    expected = u.load(ROOT/'evidence/cutoff/summary.json')
    u.require(u.load(cutoff/'report/summary.json') == expected, 'Completed receipt run differs from reviewed results')
    u.require(expected['status'] == 'COMPLETE' and expected['completed_models'] == 12, 'Receipt run incomplete')
    for rec in u.load(ROOT/'evidence/cutoff/REPORT_MANIFEST.json'):
        r.io.checked(cutoff/'report'/rec['path'], rec['sha256'], rec['bytes'])
    config = u.load(r7root/'config.json')
    allowed = {u.R7_CONF}
    if config.get('reused_r7'): allowed.add(config['reused_r7']['config_sha256'])
    ordinary = Path(paths['O50'])
    oconf = u.load(ordinary.parent/'_DONE.json')['config_sha256']
    u.require(oconf in allowed, 'O50 checkpoint is outside the reviewed R7 lineage')
    check_stage(ordinary.parent, oconf, [ordinary.name])
    # The score recipe must equal the completed receipt recipe exactly.
    recipe = dict(version=previous.VERSION, package=u.sha(previous.ROOT/'PACKAGE_MANIFEST.sha256'),
        R7=u.R7_CONF, reference=u.sha(reference),
        source=[{k:v[k] for k in ('month','shard','sha256','rows')} for v in parts],
        definition='fixed_S0_cumulative_t_minus_24h_frozen_nuisance_frozen_controls_strict_abs_material_lt4')
    u.require(r.io.cfgsha(recipe) == CUTOFF_CONF, 'Receipt/new-diagnostic instrument definitions differ')
    for folder, file in [('scores_combined','scores.parquet'), ('material','material.parquet')]:
        check_stage(cutoff/folder, CUTOFF_CONF, [file])
    # Authenticate the archived baseline model outputs and their exact inputs.
    old = {}
    for sample in ('F50','O50'):
        for level in LEVELS:
            folder = r7root/'models'/f'{sample}_{level}_pooled_pooled'
            check_stage(folder, u.R7_CONF, ['result.json','dependencies_PRIVATE.json'])
            deps = u.load(folder/'dependencies_PRIVATE.json')
            u.require(len(deps) == 1, 'Unexpected archived model dependencies')
            r.io.checked(paths[sample], deps[0]['sha256'])
            old[sample+'__'+level] = str(folder/'result.json')
    return paths, binding, parts, reference, cutoff, old

@contextlib.contextmanager
def heartbeat(label, next_minutes, remaining_minutes):
    started = time.monotonic(); done = threading.Event()
    def emit():
        elapsed = (time.monotonic()-started)/60
        u.log(f'{label}; next checkpoint ETA ~{max(1,next_minutes-elapsed):.0f} min; finish ETA ~{max(2,remaining_minutes-elapsed):.0f} min (planning estimate)')
    def loop():
        while not done.wait(30): emit()
    emit(); thread = threading.Thread(target=loop, daemon=True); thread.start()
    try: yield
    finally: done.set(); thread.join()

def metadata(rows, sample, level, screen='all'):
    return r.metadata(rows, sample, level, 'pooled', history_cutoff='lag24h', exposure_screen=screen,
        nuisance_reference='frozen_author_clean_monthly_lag7', controls_timing='frozen_R7',
        expanded_exposure_cohort=False, material_screen_changes_donor_history=False)

def load_scored(source, scores, material=None, selection='all'):
    d = r.load_fit_columns(source)
    a = r.arrays(r.io.read(scores, ['row_id','n_24h','adjusted_24h']))
    u.require(np.array_equal(d['row_id'], a['row_id']), 'Score row identities/order differ')
    u.require(np.all(a['n_24h'] >= 5) and np.isfinite(a['adjusted_24h']).all(), 'Unsupported new score')
    d['adjusted_7d'] = a['adjusted_24h']
    if material:
        m = r.arrays(r.io.read(material, ['row_id','material_valid','material_neutral']))
        u.require(np.array_equal(d['row_id'], m['row_id']), 'Material row identities/order differ')
        use = m['material_valid'].astype(bool)
        if selection == 'neutral': use &= m['material_neutral'].astype(bool)
        d = r.subset(d, use)
    elif selection != 'all': raise RuntimeError('Material screen requested without observed material')
    return d
