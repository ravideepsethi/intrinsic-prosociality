#!/usr/bin/env python3
"""Stable-rating local curvature, exact-tie, placebo and board-state follow-ups."""
from __future__ import annotations
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_key] = '1'
import argparse
import concurrent.futures
import csv
import fcntl
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import shutil
import time
import zipfile
import numpy as np
import scipy
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from source import pool_wave1_common as common
from pooled_utils import (log, qs, require, signature, write_csv, manifest, verify_manifest,
                          checkpoint_ok, certify_checkpoint)
from data_io import old_cache, stage_competitive, EXPECTED, SAMPLE_RELATIVE
from stage_base import prepare_data
from fe_engine import iter_blocks
from pooled_engine import absorption, states, retain_units, holm, STATES
from stable_specs import select, add_normalized
from followup_specs import (VERSION, SAMPLES, definitions, PRIMARY, PRIMARY_SAMPLE, PLACEBO_SPECS,
                            SUPPORT, is_primary, Spec)
import followup_engine as eng

ROOT = Path(__file__).resolve().parent
STATUS = 'POOL_STABLE_ZERO_FOLLOWUPS_OK'


def count_summary(f):
    source_n = len(f['y'])
    out = dict(source_competitive_rows=source_n, source_competitive_grants=int(f['y'].sum()),
               source_competitive_choosers=len(np.unique(f['chooser'])))
    ss = states(f['board'])
    for state in range(3):
        out[f'state_source_rows__{state}'] = int((ss == state).sum())
        out[f'state_source_grants__{state}'] = int(f['y'][ss == state].sum())
    ff = retain_units(f) if source_n else f
    a = absorption(ff) if len(ff['y']) else None
    out.update(estimation_rows=len(ff['y']), estimation_grants=int(ff['y'].sum()),
               chooser_clusters=a['G'] if a else 0, absorbed_chooser_state_units=a['H'] if a else 0)
    out['singleton_unit_rows_dropped'] = source_n-len(ff['y'])
    for state in range(3):
        out[f'state_estimation_rows__{state}'] = int((a['state'] == state).sum()) if a else 0
        out[f'state_estimation_grants__{state}'] = int(ff['y'][a['state'] == state].sum()) if a else 0
        out[f'state_absorbed_units__{state}'] = int((a['unit_state'] == state).sum()) if a else 0
    return out


def moments_job(job):
    pa.set_cpu_count(1); pa.set_io_thread_count(1)
    path = Path(job['path']); out = Path(job['work'])/path.stem/job['sample']; out.mkdir(parents=True, exist_ok=True)
    done = out/'MOMENTS_COMPLETE.json'
    if checkpoint_ok(done, job['identity']):
        verify_manifest(out, 'MOMENT_MANIFEST.sha256'); log('REUSED_MOMENTS '+str(out.name)); return str(out)
    objects = {s.key: eng.Moments(job['edges'], s) for s in job['specs']}
    counts = {}; before = signature(path)
    for i, original in enumerate(iter_blocks(path, job['batch_rows'])):
        f = select(add_normalized(original), job['sample'])
        for k, value in count_summary(f).items(): counts[k] = counts.get(k, 0)+value
        if not len(f['y']): continue
        Z = eng.nuisance_design(f, job['edges'])
        for obj in objects.values(): obj.add(f, Z)
        if i and i % 30 == 0: log(f'MOMENTS {path.stem} {job["sample"]} blocks={i}')
    require(signature(path) == before, 'Input Parquet shard changed during moments')
    for key, obj in objects.items(): obj.save(out/(key+'.npz'))
    common.atomic_json(out/'counts.json', counts)
    common.atomic_json(done, dict(identity=job['identity'], sample=job['sample'], specifications=[s.dictionary() for s in job['specs']]))
    certify_checkpoint(done, job['identity'])
    files = [out/(k+'.npz') for k in objects]+[out/'counts.json', done, done.with_suffix('.json.json')]
    common.atomic_text(out/'MOMENT_MANIFEST.sha256', ''.join(f'{common.sha256_file(p)}  {p.name}\n' for p in files))
    log(f'MOMENTS_DONE {path.stem} {job["sample"]}'); return str(out)


def scores_job(job):
    pa.set_cpu_count(1); pa.set_io_thread_count(1)
    path = Path(job['path']); out = Path(job['moment_dir'])/'scores.npz'
    if checkpoint_ok(out, job['identity']): log('REUSED_SCORES '+str(out.parent)); return str(out)
    models = job['models']; before = signature(path)
    for model in models.values():
        p = model['core_size']; model['meat'] = np.zeros((p, p)); model['score_sum'] = np.zeros(p)
    cutkeys = [s.key for s in PLACEBO_SPECS if s.key in models]
    # Joint covariance for cutoff-specific derivative changes. Every chooser is
    # aligned across windows before taking the outer product, including zeros
    # when that chooser contributes to one window but not another.
    joint = np.zeros((len(cutkeys), len(cutkeys))); joint_sum = np.zeros(len(cutkeys)); joint_G = 0
    for i, original in enumerate(iter_blocks(path, job['batch_rows'])):
        f = select(add_normalized(original), job['sample'])
        if not len(f['y']): continue
        Z = eng.nuisance_design(f, job['edges']); users = np.unique(f['chooser'])
        stacked = np.zeros((len(users), len(cutkeys))); present = np.zeros(len(users), dtype=bool)
        for key, model in models.items():
            ids, score = eng.scores(f, job['edges'], model, Z)
            if key in cutkeys and len(ids):
                column = cutkeys.index(key); where = np.searchsorted(users, ids)
                stacked[where, column] = (score[:, 1]-score[:, 0])/model['spec'].h
                present[where] = True
        joint += stacked.T@stacked; joint_sum += stacked.sum(axis=0); joint_G += int(present.sum())
        if i and i % 30 == 0: log(f'SCORES {path.stem} {job["sample"]} blocks={i}')
    require(signature(path) == before, 'Input Parquet shard changed during scores')
    arrays = {key+'__'+name: model[name] for key, model in models.items() for name in ('meat', 'score_sum')}
    arrays.update(placebo_joint_meat=joint, placebo_joint_score_sum=joint_sum,
                  placebo_union_chooser_clusters=np.array(joint_G), placebo_keys=np.array(cutkeys))
    tmp = out.with_name('scores.partial.npz'); np.savez_compressed(tmp, **arrays); os.replace(tmp, out)
    certify_checkpoint(out, job['identity']); log(f'SCORES_DONE {path.stem} {job["sample"]}'); return str(out)


def load_prior_sample_counts(path=None):
    """Read the prior report's JSON array; keep object-only readers strict elsewhere."""
    path = ROOT/'evidence/PRIOR_STABLE_SAMPLE_COUNTS.json' if path is None else Path(path)
    with path.open(encoding='utf-8') as stream:
        records = json.load(stream)
    require(isinstance(records, list) and bool(records), f'Expected a nonempty JSON list: {path}')
    scalar_fields = ('source_competitive_rows', 'source_competitive_grants',
                     'source_competitive_choosers', 'estimation_rows', 'estimation_grants',
                     'chooser_clusters', 'absorbed_chooser_state_units', 'singleton_unit_rows_dropped')
    state_fields = ('state_source_rows', 'state_source_grants', 'state_estimation_rows',
                    'state_estimation_grants', 'state_absorbed_units')
    result = {}
    for record in records:
        require(isinstance(record, dict), f'Expected count record objects: {path}')
        sample = record.get('sample')
        require(isinstance(sample, str) and bool(sample), f'Missing sample identifier: {path}')
        require(sample not in result, f'Duplicate sample count evidence: {sample}')
        flat = {}
        for field in scalar_fields:
            value = record.get(field)
            require(type(value) is int and value >= 0, f'Invalid count evidence: {sample}/{field}')
            flat[field] = value
        for field in state_fields:
            values = record.get(field)
            require(isinstance(values, dict) and set(values) == set(STATES),
                    f'Invalid state count evidence: {sample}/{field}')
            for index, state in enumerate(STATES):
                value = values[state]
                require(type(value) is int and value >= 0, f'Invalid state count: {sample}/{field}/{state}')
                flat[f'{field}__{index}'] = value
        result[sample] = flat
    require(set(SAMPLES).issubset(result), f'Missing required samples in count evidence: {path}')
    return result


def verify_sample_counts(sample, counts, report):
    expected = load_prior_sample_counts()[sample]
    require(set(counts) == set(expected), 'Stable sample count fields differ: '+sample)
    checks = []
    for key, value in counts.items():
        want = expected[key]
        checks.append(dict(sample=sample, field=key, actual=int(value), expected=int(want), matched=value == want))
    common.atomic_json(report/(sample+'_SAMPLE_REPLICATION.json'), checks)
    require(all(r['matched'] for r in checks), 'Stable sample count replication failed: '+sample)


def placebo_tests(sample, specs, moments, models, joint, union_G, result_rows):
    keys = [s.key for s in specs]
    values = np.array([(models[k]['estimates'][1]-models[k]['estimates'][0])/moments[k].spec.h for k in keys])
    factors = [eng.factor(moments[k], models[k]) for k in keys]
    scaled = np.sqrt(np.array([v if v is not None else np.nan for v in factors]))
    V = joint*scaled[:, None]*scaled[None, :]
    relevant = {r['spec_id']: r for r in result_rows if r['term'] == 'right_minus_left_slope' and r['context'] == 'pooled_competitive'}
    valid = np.array([relevant[k]['status'] == 'estimated' for k in keys])
    G = min(moments[k].G for k in keys)  # conservative df across the three windows
    contrasts = [('zero_minus_left_placebo', [1, -1, 0]), ('zero_minus_right_placebo', [1, 0, -1]),
                 ('zero_minus_average_placebo', [1, -.5, -.5])]
    rows = []
    for name, vector in contrasts:
        c = np.array(vector, float); ok = bool(valid[c != 0].all() and G > 1)
        rows.append(dict(sample=sample, test=name, axis='normalized', h=.05,
                         cutoffs=[s.center for s in specs], status='estimated' if ok else 'insufficient_support_or_unidentified',
                         estimate_pp=100*float(c@values) if ok else None,
                         **eng.inference(c@values, c@V@c, G-1, ok),
                         units='pp per unit D/K', denominator_df=G-1, union_chooser_clusters=union_G,
                         covariance='Joint chooser influence scores, with geometric CR1 scaling across fits', exploratory=True))
    H = np.array([[1, -1, 0], [1, 0, -1]], float)
    test = dict(sample=sample, test='zero_equals_both_placebo_kinks', axis='normalized', h=.05,
                **eng.wald(H@values, H@V@H.T, G-1, bool(valid.all())), union_chooser_clusters=union_G,
                null='The derivative change at zero equals the changes at both placebo cutoffs.', exploratory=True)
    return rows, test, V, values


def prior_replication(rows):
    with (ROOT/'evidence/PRIOR_ZERO_DIAGNOSTICS.csv').open(encoding='utf-8', newline='') as stream:
        previous = list(csv.DictReader(stream))
    index = {(r['sample'], r['axis'], float(r['bandwidth']), r['term']): r for r in previous}
    checks = []
    for r in rows:
        if r['degree'] != 1 or r['center'] != 0 or r['scope'] != 'pooled' or r['omit_ties']: continue
        term = 'zero_atom_minus_left_limit' if r['term'] == 'center_atom_minus_left_limit' else r['term']
        old = index[(r['sample'], r['axis'], r['h'], term)]
        ok = True; errors = {}
        for key in ('n', 'events', 'chooser_clusters', 'absorbed_units', 'left_n', 'right_n'):
            ok &= int(old[key]) == r[key]
        for key in ('estimate_pp', 'cluster_se_pp'):
            expected = float(old[key]) if old[key] else None
            actual = r[key]
            if expected is None or actual is None:
                matched = expected is None and actual is None; error = None
            else:
                error = abs(actual-expected); matched = bool(np.isclose(actual, expected, atol=1e-4, rtol=1e-5))
            ok &= matched; errors[key+'_absolute_difference'] = error
        checks.append(dict(sample=r['sample'], axis=r['axis'], bandwidth=r['h'], term=term,
                           matched=bool(ok), **errors))
    return checks


def export_table(report, name, rows):
    if not rows: return
    write_csv(report/(name+'.csv'), rows)
    # Result Parquets are aggregates only; no account IDs or game IDs.
    clean = []
    for row in rows:
        clean.append({k: common.canonical_json(v) if isinstance(v, (dict, list, tuple)) else v for k, v in row.items()})
    # Build one schema using the union of keys, including fields unique to later rows.
    keys = list(dict.fromkeys(k for r in clean for k in r))
    table = pa.Table.from_pylist([{k: r.get(k) for k in keys} for r in clean])
    pq.write_table(table, report/(name+'.parquet'), compression='zstd')


def estimate(paths, edges, identity, workers, batch_rows, private, report, specs=None, production=True):
    specs = definitions() if specs is None else specs
    results = []; tests = []; placebo = []; placebo_joint = []; profiles = []; diagnostics = []; support_rows = []; counts_rows = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for sample in SAMPLES:
            log(f'ESTIMATING {sample}: {len(specs)} local polynomial fits')
            jobs = [dict(path=str(p), work=str(private/'estimation'), sample=sample, edges=edges,
                         identity=identity, batch_rows=batch_rows, specs=specs) for p in paths]
            dirs = list(pool.map(moments_job, jobs))
            moments = {s.key: eng.Moments(edges, s) for s in specs}; counts = {}
            for d in map(Path, dirs):
                for key in moments: moments[key].merge(eng.Moments.load(d/(key+'.npz')))
                for key, value in common.load_json(d/'counts.json').items(): counts[key] = counts.get(key, 0)+value
            if production: verify_sample_counts(sample, counts, report)
            counts_rows.append(dict(sample=sample, **counts))
            models = {k: eng.fit(m) for k, m in moments.items()}
            for key, model in models.items():
                require(model['normal_equation_relative_error'] < 1e-5, 'Normal-equation failure: '+sample+' '+key)
            score_jobs = [dict(job, moment_dir=d, models=models) for job, d in zip(jobs, dirs)]
            scorepaths = list(pool.map(scores_job, score_jobs))
            cut_specs = [s for s in PLACEBO_SPECS if s.key in models]
            joint = np.zeros((len(cut_specs), len(cut_specs))); joint_G = 0
            for p in scorepaths:
                with np.load(p, allow_pickle=False) as z:
                    for key, model in models.items():
                        model['meat'] += z[key+'__meat']; model['score_sum'] += z[key+'__score_sum']
                    require(z['placebo_keys'].tolist() == [s.key for s in cut_specs], 'Placebo ordering mismatch')
                    joint += z['placebo_joint_meat']; joint_G += int(z['placebo_union_chooser_clusters'])
            sample_rows = []; arrays = {}
            for key, m in moments.items():
                m.save(report/(sample+'__'+key+'__moments.npz'))
                row, test, V = eng.finish(m, models[key], **(SUPPORT if production else dict(min_n=1, min_choosers=1, min_months=1, min_gap_levels=1)))
                for rr in row:
                    rr.update(sample=sample, primary_followup=is_primary(sample, m.spec))
                for rr in test: rr['sample'] = sample
                sample_rows += row; tests += test
                arrays[key+'__covariance'] = V; arrays[key+'__core_estimates'] = models[key]['estimates']
                arrays[key+'__full_coefficients'] = models[key]['beta']; arrays[key+'__names'] = np.array(m.names)
                diagnostics.append(dict(sample=sample, spec_id=key, n=m.N, chooser_clusters=m.G,
                                        rank=models[key]['rank'], condition_number=models[key]['condition_number'],
                                        normal_equation_relative_error=models[key]['normal_equation_relative_error'],
                                        max_absolute_cluster_score_sum=float(np.max(np.abs(models[key]['score_sum']), initial=0)),
                                        noninteger_displayed_gap_rows=m.noninteger_gap))
                if m.spec.degree == 2 and m.spec.center == 0 and not m.spec.omit_ties and m.spec.h == {'normalized': .05, 'payoff': .5, 'gap': 25.}[m.spec.axis]:
                    pp = eng.polynomial_profile(m, models[key], V, **(SUPPORT if production else dict(min_n=1, min_choosers=1, min_months=1, min_gap_levels=1)))
                    for rr in pp: rr['sample'] = sample
                    profiles += pp
                for g, context in enumerate(eng.contexts(m.spec)):
                    for side in range(3):
                        for code in np.flatnonzero(m.gap_hist[g, side]):
                            support_rows.append(dict(sample=sample, spec_id=key, axis=m.spec.axis, h=m.spec.h,
                                                     center=m.spec.center, degree=m.spec.degree, scope=m.spec.scope,
                                                     omit_ties=m.spec.omit_ties, context=context,
                                                     side=('left', 'at_cutoff', 'right')[side], displayed_gap=int(code)-501,
                                                     overflow=bool(code in (0, 1002)), n=int(m.gap_hist[g, side, code])))
            if len(cut_specs) == 3:
                pr, pj, Vj, vj = placebo_tests(sample, cut_specs, moments, models, joint, joint_G, sample_rows)
                placebo += pr; placebo_joint.append(pj)
                arrays['placebo_joint_covariance'] = Vj; arrays['placebo_kink_estimates'] = vj
            np.savez_compressed(report/(sample+'__coefficients_and_covariances.npz'), **arrays)
            results += sample_rows
            log(f'ESTIMATED {sample}; global stable FE sample N={counts["estimation_rows"]:,}')
    # Separate declared families; unsupported tests remain in each family as p=1.
    holm(results, lambda r: r['primary_followup'], 'p_two_sided', 'p_holm_primary_5')
    for term, short in [('right_minus_left_slope', 'kinks'), ('jump_right_minus_left', 'jumps')]:
        holm(results, lambda r, t=term: r['scope'] == 'pooled' and r['center'] == 0 and r['term'] == t,
             'p_two_sided', 'p_holm_pooled_zero_'+short)
    holm(results, lambda r: r['scope'] == 'by_state' and r['term'] == 'right_minus_left_slope', 'p_two_sided', 'p_holm_state_kinks')
    holm(tests, lambda r: r['test'] == 'equal_kinks_across_board_states', 'p_cluster_F', 'p_holm_state_joint_tests')
    holm(tests, lambda r: r['test'] != 'equal_kinks_across_board_states', 'p_two_sided', 'p_holm_state_pairwise')
    for r in placebo: r['p_for_family'] = r['p_two_sided']
    for r in placebo_joint: r['p_for_family'] = r['p_cluster_F']
    combined = placebo+placebo_joint
    holm(combined, lambda r: True, 'p_for_family', 'p_holm_placebo_8')
    checks = prior_replication(results) if production else []
    if production:
        export_table(report, 'prior_linear_replication', checks)
        require(len(checks) == 90 and all(r['matched'] for r in checks), 'Prior local-linear replication failed; inspect prior_linear_replication.csv. No success marker written.')
    for name, rows in [('local_estimates', results), ('board_state_tests', tests), ('placebo_contrasts', combined),
                       ('local_profiles', profiles), ('displayed_gap_support', support_rows), ('sample_counts', counts_rows)]:
        export_table(report, name, rows)
    common.atomic_json(report/'MODEL_DIAGNOSTICS.json', diagnostics)
    from followup_report import build_report
    build_report(report, results, tests, combined, profiles, production)
    return counts_rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root', type=Path, default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--sample-root', type=Path); p.add_argument('--output-root', type=Path)
    p.add_argument('--transfer-root', type=Path, default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers', type=int, default=10); p.add_argument('--hash-workers', type=int, default=2)
    p.add_argument('--batch-rows', type=int, default=32768); p.add_argument('--memory-limit', default='6GB')
    p.add_argument('--no-reuse-previous-cache', action='store_true'); args = p.parse_args()
    require(1 <= args.workers <= 10 and 1 <= args.hash_workers <= 10, 'Workers must be 1..10')
    require(1024 <= args.batch_rows <= 131072, 'Batch rows must be 1024..131072')
    start = time.monotonic(); packagehash = verify_manifest(ROOT, 'PACKAGE_MANIFEST.sha256')
    load_prior_sample_counts()  # Fail on malformed evidence before authentication or estimation.
    auth = common.authenticate_sample(args.sample_root or args.project_root/SAMPLE_RELATIVE,
                                      verify_hashes=True, hash_workers=args.hash_workers)
    for key, value in EXPECTED.items(): require(auth['authority'][key] == value, 'Authority mismatch: '+key)
    require(auth['fingerprint'] == common.load_json(ROOT/'evidence/PRIOR_STABLE_SAMPLE_LINEAGE.json')['fingerprint'],
            'Sample fingerprint differs from the preceding stable-rating run')
    versions = dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                    duckdb=duckdb.__version__, pyarrow=pa.__version__)
    settings = dict(samples=SAMPLES, specs=[s.dictionary() for s in definitions()], support=SUPPORT,
                    primary_sample=PRIMARY_SAMPLE, primary_spec=PRIMARY.dictionary(),
                    workers=args.workers, batch_rows=args.batch_rows, memory_limit=args.memory_limit,
                    fixed_effects='chooser_by_broad_competitive_board_state', cluster='chooser',
                    kernel='uniform', shape_restrictions=None, inference='CR1; no automatic bias correction',
                    design_status='exploratory_followup_fixed_before_this_run')
    identity = hashlib.sha256(common.canonical_json(dict(package=packagehash, sample=auth['fingerprint'], versions=versions, settings=settings)).encode()).hexdigest()
    root = (args.output_root or args.project_root/'output/pool_stable_zero_followups_v101')/identity[:16]
    private = root/'PRIVATE'; report = root/'report'; private.mkdir(parents=True, exist_ok=True); report.mkdir(exist_ok=True)
    lock = open(root/'run.lock', 'a')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This exact follow-up run is already active.') from None
    source_signatures = {str(r['path']): signature(r['path']) for r in auth['month_records']}
    cached = None if args.no_reuse_previous_cache else old_cache(args.project_root, auth)
    if cached is None:
        db = duckdb.connect(); db.execute(f'SET threads={args.workers}'); db.execute(f'SET memory_limit={qs(args.memory_limit)}')
        spill = private/'duckdb_spill'; spill.mkdir(exist_ok=True); db.execute(f'SET temp_directory={qs(spill)}')
        prep = prepare_data(db, [r['path'] for r in auth['month_records']], private, identity, EXPECTED, []); db.close()
        base = private/'sorted_base.parquet'
        cached = base, prep, dict(kind='fresh_authenticated_source_build', sha256=common.sha256_file(base))
    base, prep, receipt = cached; before = signature(base)
    paths = stage_competitive(base, private, identity, args.workers, EXPECTED['fair_rows'])
    common.atomic_json(report/'BASE_CACHE_PROVENANCE.json', receipt)
    common.atomic_json(report/'PREPARATION.json', prep)
    common.atomic_json(report/'RUN_IDENTITY.json', dict(identity=identity, settings=settings, versions=versions, package_manifest_sha256=packagehash))
    counts = estimate(paths, prep['K_cutpoints'], identity, args.workers, args.batch_rows, private, report)
    common.atomic_json(report/'SAMPLE_LINEAGE.json', common.compact_sample_lineage(auth))
    common.atomic_json(report/'INPUT_MANIFEST.json', [dict(month=r['month'], rows=r['rows'], size_bytes=r['size_bytes'], sha256=r['actual_sha256'], relative_path=f'panel/month={r["month"]}/analysis_panel.parquet') for r in auth['month_records']])
    require(signature(base) == before, 'Sorted cache changed')
    for path, sig in source_signatures.items(): require(signature(path) == sig, 'Source input changed')
    for name in ('METHODS.md', 'README.md'): shutil.copyfile(ROOT/name, report/name)
    executed = report/'executed_code'
    for rel in [line.split('  ', 1)[1] for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines()]+['PACKAGE_MANIFEST.sha256']:
        target = executed/rel; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/rel, target)
    common.atomic_json(report/'_SUCCESS.json', dict(status=STATUS, version=VERSION, identity=identity,
        samples=counts, number_of_local_fits=2*len(definitions()), prior_linear_checks=90,
        network_requests=0, source_inputs_unchanged=True, elapsed_seconds=time.monotonic()-start,
        no_usernames_or_game_ids_in_report=True))
    manifest(report); args.transfer_root.mkdir(parents=True, exist_ok=True)
    stem = 'POOL_STABLE_ZERO_FOLLOWUPS_RESULTS_v101_'+identity[:16]
    target = args.transfer_root/(stem+'.zip'); temp = target.with_suffix('.partial.zip')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(report.rglob('*')):
            if f.is_file() and '__pycache__' not in f.parts: z.write(f, stem+'/'+f.relative_to(report).as_posix())
    os.replace(temp, target); digest = common.sha256_file(target)
    common.atomic_text(target.with_suffix('.zip.sha256'), f'{digest}  {target.name}\n')
    log(f'{STATUS}\nRESULTS_ZIP: {target}\nSHA256: {digest}\nFIGURES: {report/"figures"}\nPRIVATE_CACHE: {private}')


if __name__ == '__main__': main()
