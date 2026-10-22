#!/usr/bin/env python3
from __future__ import annotations
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
import argparse, concurrent.futures, csv, fcntl, shutil, traceback
from pathlib import Path
import duckdb, numpy, pyarrow, scipy
from common import *
from estimator import fit, CATS, NUMS

def authenticate(first, threads):
    frozen = ROOT / 'first_pass_report'
    frozen_hashes = read(frozen / 'REPORT_HASHES.json')
    for name, digest in frozen_hashes.items():
        require(sha(first / 'report' / name) == digest, 'First-pass report changed or incomplete: ' + name)
    core = read(first / 'report/CORE_SUCCESS.json')
    activity = read(first / 'report/ACTIVITY_SUCCESS.json')
    run = read(first / 'RUN_IDENTITY.json')
    require(core['status'] == 'COUNTRY_PROFILE_CORE_OK' and activity['status'] == 'COUNTRY_PROFILE_ACTIVITY_OK', 'First pass not complete')
    require(run['identity'] == signature(run['inputs']) == core['identity'] == activity['identity'], 'First-pass identity disagreement')
    require(run['identity'] == read(frozen / 'CORE_SUCCESS.json')['identity'], 'Not the reviewed first-pass run')
    require(run['inputs']['package_hash'] == signature(read(ROOT / 'authority/first_pass_package_hashes.json')), 'First-pass package identity changed')
    months = [f'{y}-{m:02}' for y in [2023, 2024, 2025] for m in range(1, 13) if '2023-11' <= f'{y}-{m:02}' <= '2025-10']
    panels = [first / 'PRIVATE/panel' / (month + '.parquet') for month in months]
    require(set(panels) == set((first / 'PRIVATE/panel').glob('*.parquet')), 'Expected exactly the certified 24 monthly checkpoints')
    profiles = first / 'PRIVATE/profiles.parquet'
    def check(path):
        require(valid(path, run['identity']), 'Missing certified checkpoint: ' + str(path))
        return dict(name=str(path.relative_to(first)), sha256=read(str(path)+'.json')['sha256'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(threads, 4)) as pool:
        checks = list(pool.map(check, [profiles] + panels))
    return panels, profiles, dict(first_pass_identity=run['identity'], verified_files=checks)

def prepare_pairs(db, panels, profiles, out, identity):
    db.execute(f'''CREATE TEMP TABLE profiles AS SELECT username, returned, disabled, flag_conflict,
       flag_code,flag_class,iso_code,parent_code,tos_mark,profile_source
       FROM read_parquet({qs(profiles)})''')
    n, unique = db.execute('SELECT count(*),count(DISTINCT username) FROM profiles').fetchone()
    require(n == unique, 'Duplicate profile keys')
    paths = []
    for panel in panels:
        part = out / 'PRIVATE/pairs' / panel.name
        paths.append(part)
        if valid(part, identity):
            log('REUSE_PAIR_MONTH ' + panel.stem)
            continue
        sql = f'''SELECT p.* EXCLUDE(chooser_name,recipient_name),c.iso_code chooser_country,r.iso_code recipient_country,
          c.flag_code chooser_flag,r.flag_code recipient_flag,
          c.parent_code raw_chooser_parent,r.parent_code raw_recipient_parent,
          CASE WHEN c.flag_class IN ('iso_country_or_territory','subnational_or_regional') THEN c.parent_code END chooser_parent,
          CASE WHEN r.flag_class IN ('iso_country_or_territory','subnational_or_regional') THEN r.parent_code END recipient_parent,
          r.tos_mark recipient_mark,c.profile_source chooser_profile_source,r.profile_source recipient_profile_source
          FROM read_parquet({qs(panel)},hive_partitioning=false) p
          JOIN profiles c ON p.chooser_name=c.username JOIN profiles r ON p.recipient_name=r.username
          WHERE c.returned AND r.returned AND NOT c.disabled AND NOT r.disabled
          AND NOT c.flag_conflict AND NOT r.flag_conflict AND c.flag_code IS NOT NULL AND r.flag_code IS NOT NULL'''
        parquet(db, part, sql)
        certify(part, identity)
        log('PAIR_MONTH_READY ' + panel.stem)
    db.execute('CREATE TEMP VIEW pairs AS SELECT * FROM read_parquet([' + ','.join(qs(p) for p in paths) + '])')
    # Match the reviewed public support totals before estimating anything new.
    comparisons = [
        ('04_iso_pair_support_rates.csv','iso_pair','same_iso','different_iso','chooser_country','recipient_country'),
        ('04_exact_pair_support_rates.csv','exact_pair','same_exact_flag','different_exact_flag','chooser_flag','recipient_flag'),
        ('04_parent_pair_support_rates.csv','parent_pair','same_parent_mapping','different_parent_mapping','raw_chooser_parent','raw_recipient_parent')]
    receipt = []
    for filename, group, same, different, c, r in comparisons:
        expected = list(csv.DictReader((ROOT / 'first_pass_report' / filename).open()))
        got = records(db, f'''SELECT CASE WHEN {c}={r} THEN {qs(same)} ELSE {qs(different)} END category,
          state,count(*) opportunities,sum(y)::BIGINT grants,count(DISTINCT chooser) choosers FROM pairs
          WHERE {c} IS NOT NULL AND {r} IS NOT NULL GROUP BY ALL''')
        lookup = {(x['category'],x['state']): x for x in got}
        for row in expected:
            if row[group] not in (same, different):
                continue
            observed = lookup.get((row[group],row['state']), {})
            for field in ('opportunities','grants','choosers'):
                require(observed.get(field) == int(row[field]), f'Support reconciliation failed: {filename}/{row[group]}/{row["state"]}/{field}')
        receipt.append(dict(file=filename,status='MATCHED',cells=len(got)))
    dump(out / 'report/PAIR_SUPPORT_RECONCILIATION.json', receipt)
    db.execute('DROP TABLE profiles')

def specifications():
    def item(name, state='competitive', definition='iso', controls=True, recipient_effect=True, extra='true', switchers=False):
        cols = dict(iso=('chooser_country','recipient_country'), parent=('chooser_parent','recipient_parent'), exact=('chooser_flag','recipient_flag'))
        chooser, recipient = cols[definition]
        return dict(model=name, state=state, definition=definition,
                    where=f'state={qs(state)} AND {chooser} IS NOT NULL AND {recipient} IS NOT NULL AND ({extra})',
                    chooser_code=chooser, recipient_code=recipient,
                    cats=(['recipient_group'] if recipient_effect else []) + (CATS if controls else []),
                    nums=NUMS if controls else [], switchers_only=switchers)
    return [item('iso_chooser_only',controls=False,recipient_effect=False),
            item('iso_chooser_recipient_country',controls=False),
            item('iso_primary'),
            item('iso_switchers_only',switchers=True),
            item('iso_excluding_russia',extra="chooser_country<>'RU' AND recipient_country<>'RU'"),
            item('parent_country_sensitivity',definition='parent'),
            item('exact_flag_sensitivity',definition='exact'),
            item('iso_excluding_marked_recipients',extra='recipient_mark IS NOT TRUE'),
            item('iso_clearly_losing',state='clearly_worse')]

def estimate(db, out, spec, identity):
    checkpoint = out / 'PRIVATE/models' / (spec['model'] + '.json')
    model_identity = signature([identity,spec])
    if valid(checkpoint, model_identity):
        log('REUSE_MODEL ' + spec['model'])
        return read(checkpoint)
    columns = ','.join(dict.fromkeys(['chooser','recipient','y'] + [x for x in spec['cats'] if x != 'recipient_group'] + spec['nums']))
    sql = f'''SELECT {columns},({spec['chooser_code']}={spec['recipient_code']})::INTEGER same,
              {spec['recipient_code']} recipient_group FROM pairs WHERE {spec['where']}'''
    with Heartbeat(spec['model']):
        data = db.execute(sql).to_arrow_table().to_pydict()
        result = fit(data, spec['cats'], spec['nums'], spec['switchers_only'])
    result['model'] = spec['model']
    result['specification'] = spec
    dump(checkpoint, result)
    certify(checkpoint, model_identity)
    log('MODEL_READY ' + spec['model'] + ': ' + result['status'])
    return result

def summarize(out, results):
    order = sorted([r for r in results if r.get('chooser_cluster',{}).get('p_value') is not None], key=lambda r:r['chooser_cluster']['p_value'])
    running = 0
    for i,r in enumerate(order):
        running = max(running, min(1, r['chooser_cluster']['p_value']*(9-i)))
        r['holm_p_nine_model_family'] = running
    dump(out / 'report/MODEL_SUMMARY.json', results)
    rows = []
    text = ['# Same-country follow-up results', '',
            'Unweighted associations among acquired flag setters. All estimates absorb chooser fixed effects. Primary inference clusters on chooser. CR1 counts absorbed chooser effects in the full model rank.', '',
            '| Model | Estimate (pp) | Chooser SE (pp) | 95% CI (pp) | p | N | Choosers | Same-country switchers |',
            '|---|---:|---:|---|---:|---:|---:|---:|']
    for r in results:
        dump(out / 'report' / ('model_' + r['model'] + '.json'), r)
        c = r.get('chooser_cluster',{})
        t = r.get('two_way_cluster',{})
        row = dict(model=r['model'], status=r['status'], coefficient_pp=r.get('coefficient_pp'),
                   chooser_se_pp=c.get('standard_error_pp'), ci_low_pp=c.get('ci_low_pp'), ci_high_pp=c.get('ci_high_pp'),
                   p_value=c.get('p_value'), holm_p=r.get('holm_p_nine_model_family'),
                   two_way_se_pp=t.get('standard_error_pp'), two_way_p=t.get('p_value'),
                   eligible_n=r.get('eligible_n'), estimation_n=r.get('estimation_n'), choosers=r.get('choosers'),
                   same_country_switchers=r.get('same_country_switchers'), switchers_with_outcome_variation=r.get('switchers_with_outcome_variation'),
                   dropped_singleton_rows=r.get('dropped_singleton_rows'))
        rows.append(row)
        if c.get('status') == 'ESTIMATED':
            text.append(f"| {r['model']} | {r['coefficient_pp']:+.4f} | {c['standard_error_pp']:.4f} | [{c['ci_low_pp']:+.4f}, {c['ci_high_pp']:+.4f}] | {c['p_value']:.3g} | {r['estimation_n']:,} | {r['choosers']:,} | {r['same_country_switchers']:,} |")
        else:
            text.append(f"| {r['model']} | {r['status']} | | | | {r.get('estimation_n',0):,} | | |")
    text += ['', 'The CSV and per-model JSON files include recipient and two-way clustering sensitivities, identification support and the nine-model Holm adjustment. A nonpositive two-way covariance is reported as unsupported, without truncation to zero.', '',
             'The parent-country sensitivity retains the primary geographic exclusions. Exact-flag matching includes symbolic affiliations and is not solely a country comparison. Flag reporting and outcome-based acquisition remain selection limitations.', '']
    write_csv(out / 'report/SAME_COUNTRY_MODELS.csv', rows)
    (out / 'report/SAME_COUNTRY_RESULTS.md').write_text('\n'.join(text))

def main():
    p = argparse.ArgumentParser(description='Within-chooser same-country models from the completed country first pass')
    p.add_argument('--project', type=Path, default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--first-pass-root', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--memory', default='4GB')
    args = p.parse_args()
    require(1 <= args.threads <= 10, 'Use 1–10 threads')
    project = args.project.expanduser().resolve()
    first = (args.first_pass_root or project/'output/country_profile_first_pass_v100/run').expanduser().resolve()
    out = (args.output or project/'output/country_profile_followup_v100/run').expanduser().resolve()
    require(project.is_dir() and first.is_dir(), 'Project or completed first-pass directory is not mounted')
    require(out != first and not out.is_relative_to(first) and not first.is_relative_to(out), 'Use a separate follow-up output directory')
    package = read(ROOT / 'PACKAGE_HASHES.json')
    for name,digest in package.items():
        require(sha(ROOT/name) == digest, 'Package file changed: ' + name)
    out.mkdir(parents=True, exist_ok=True)
    (out/'report').mkdir(exist_ok=True)
    lock = open(out/'RUN.lock','a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    source_lock = open(first/'RUN.lock','rb')
    fcntl.flock(source_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    db = None
    try:
        with Heartbeat('Verify saved first-pass checkpoints'):
            panels,profiles,receipt = authenticate(first,args.threads)
        identity = signature([package,receipt])
        identity_file = out/'RUN_IDENTITY.json'
        if identity_file.exists():
            require(read(identity_file)['identity'] == identity, 'Output belongs to different code or inputs; choose a new --output directory')
        else:
            dump(identity_file, dict(identity=identity))
        dump(out/'report/INPUT_VERIFICATION.json', receipt)
        dump(out/'report/RUN_SCOPE.json', dict(version=VERSION,identity=identity,network_requests=0,
             threads=args.threads,memory=args.memory,primary_model='iso_primary', population_weighting=False,
             software=dict(duckdb=duckdb.__version__,numpy=numpy.__version__,scipy=scipy.__version__,pyarrow=pyarrow.__version__)))
        shutil.copytree(ROOT/'ready_results',out/'report/first_pass_tables',dirs_exist_ok=True)
        shutil.copyfile(ROOT/'METHODS.md',out/'report/METHODS.md')
        db = connection(args.memory,args.threads,out/'PRIVATE/spill')
        with Heartbeat('Build cached both-player analysis sample'):
            prepare_pairs(db,panels,profiles,out,identity)
        results = []
        for spec in specifications():
            results.append(estimate(db,out,spec,identity))
            summarize(out,results)
        # The final family contains all nine specifications, including unsupported ones.
        summarize(out,results)
        dump(out/'report/FOLLOWUP_SUCCESS.json',dict(status='COUNTRY_PROFILE_FOLLOWUP_OK',identity=identity,
             models=len(results),estimated=sum(r['status']=='ESTIMATED' for r in results)))
        report_zip(out)
        (out/'ERROR.json').unlink(missing_ok=True)
        log('COUNTRY_PROFILE_FOLLOWUP_OK')
    except Exception as exc:
        dump(out/'ERROR.json',dict(error=str(exc),traceback=traceback.format_exc()))
        log('STOPPED: ' + str(exc) + '; completed follow-up checkpoints retained')
        raise
    finally:
        if db is not None:
            db.close()
        source_lock.close()
        lock.close()

if __name__ == '__main__':
    main()
