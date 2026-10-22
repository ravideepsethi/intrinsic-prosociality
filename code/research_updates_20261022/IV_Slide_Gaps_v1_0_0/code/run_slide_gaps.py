#!/usr/bin/env python3
"""Complete the numerical gaps using existing verified local cohorts only."""
from __future__ import annotations
from common import *
import argparse, datetime as dt, fcntl, gc, shutil, time, traceback, zipfile
import diagnostics as diag
import cache_audit

def analyze_cohort(path, output, conf, cohort, bands, outcomes, expected):
    def calculate(tmp):
        started = time.monotonic()
        io.log(cohort + ': reading verified cohort')
        d = read_cohort(path, outcomes)
        if outcomes:
            rates = diag.outcome_levels(d)
            all_rows = rates[0]
            if len(d['row_id']) == HEADLINE_N:
                observed = (all_rows['N'], all_rows['Y_ones'], all_rows['R_ones'], rates[1]['N'])
                if observed != (2682330, 43600, 1537636, 2617641):
                    raise RuntimeError('Headline outcome counts do not reproduce the verified report')
            io.js(tmp/'outcome_levels.json', rates)
            write_csv(tmp/'outcome_levels.csv', rates)
            io.log(cohort + ': claim-only rates recovered')
        distribution, histogram, details = diag.score_distribution(d)
        for name, rows in [('score_distribution', distribution), ('score_histogram', histogram)]:
            io.js(tmp/(name+'.json'), rows)
            write_csv(tmp/(name+'.csv'), rows)
        io.js(tmp/'score_population_definition.json', details)
        io.log(cohort + ': score distributions complete; fitting score bands')
        with io.heartbeat(cohort + ' score-band models'):
            band_rows, model = diag.first_stage_bands(d, bands, expected)
        del d
        gc.collect()
        io.js(tmp/'first_stage_bands.json', band_rows)
        write_csv(tmp/'first_stage_bands.csv', band_rows)
        io.js(tmp/'first_stage_model.json', model)
        plot_status = diag.make_plots(tmp, cohort)
        io.js(tmp/'plot_status.json', plot_status)
        return dict(cohort=cohort, seconds=time.monotonic()-started, status='DIAGNOSTICS_COMPLETE',
                    plot_status=plot_status['status'], headline_IV_reestimated=False)
    return io.stage(output, conf, calculate)

def read_results(report):
    levels = io.load(report/'headline_original/outcome_levels.json')
    lines = ['IV SLIDE GAPS — LOCAL RESULTS', '',
             'Headline-original rates: the exact 2,682,330-row cohort behind the existing IV.',
             'These are exposure-weighted descriptive rates. No matched weighting is used.', '']
    for row in levels:
        conditional = 'undefined' if row['mean_Y_given_R_percent'] is None else f"{row['mean_Y_given_R_percent']:.8f}%"
        lines.append(f"{row['group']}: N={row['N']:,}; Y={row['mean_Y_percent']:.8f}%; R={row['mean_R_percent']:.8f}%; Y|R=1={conditional}.")
    for label in ('headline_original', 'run3_author_clean'):
        directory = report/label
        if not directory.is_dir():
            continue
        distribution = io.load(directory/'score_distribution.json')
        lines += ['', label.upper()]
        for population in ('exposure_weighted', 'one_snapshot_per_opponent'):
            s = next(r for r in distribution if r['population'] == population and r['variable'] == 'adjusted_score_Z')
            lines.append(f"{population}: zero grants in relevant history={100*s['zero_grant_history_share']:.4f}%; Z p10/p50/p90={s['p10']:.8f}, {s['p50']:.8f}, {s['p90']:.8f}.")
        fit = io.load(directory/'first_stage_model.json')
        lines.append(f"Adjusted linear first stage={fit['linear_first_stage']['coefficient_pp']:.8f} pp/reference SD; {fit['actual_bands']} score bands.")
        test = fit['nonlinearity']
        lines.append('Linearity diagnostic: '+json.dumps(test, sort_keys=True))
        lines.append('Use both the shape and departure size; a p-value alone does not say whether the approximation is useful.')
        lines.append('Plots: '+io.load(directory/'plot_status.json')['status'])
    profile = io.load(report/'profile_audit_summary.json')
    lines += ['', 'PROFILE CACHE: '+profile['status'], profile['interpretation'], '',
              'DEFINITIONS AND LIMITS',
              'Zero-grant history means zero grants in the exact pair-excluded historical scoring set, not lifetime never-granted.',
              'The opponent population is supported opponents actually encountered in this cohort, not all Lichess opponents.',
              'Raw Z is in grant-probability residual units. The fixed reference SD is 0.059411690344000595.',
              'Adjusted band means average over the same empirical controls/FE distribution. They are model-standardized probabilities, with no clipping.',
              'Band intervals are pointwise shared-account OR date CR0 normal intervals. Scores and cutpoints are treated as fixed.',
              'The nested band-step test is a functional-form diagnostic, not an exclusion or individual-monotonicity test.',
              'The optional Run 3 companion uses only its already-completed author-clean score/control cache. It has no Y and does not revise the headline IV.',
              'Run 2 status records local receipts and recognized processes. A process may exist without making progress; full-frame completion is not certified automatically.',
              'The exports do not identify seconds waited after disconnection or claim-button availability. No proxy is labeled that measurement.',
              'Meeting duration and whether Decio has read the draft require a human answer.', '',
              'RETURN THIS REPORT ZIP. Raw cohort records, account IDs, profile values and private input paths are excluded.', '']
    (report/'READ_RESULTS.txt').write_text('\n'.join(lines), encoding='utf-8')

def package_report(report, desktop, stem):
    desktop.mkdir(parents=True, exist_ok=True)
    destination = desktop/(stem+'.zip')
    if destination.exists():
        raise RuntimeError('Refusing to overwrite an existing report archive')
    temporary = destination.with_suffix('.zip.partial')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(report.rglob('*')):
            if p.is_file():
                if 'PRIVATE' in p.name:
                    raise RuntimeError('Private file unexpectedly present in report')
                archive.write(p, p.relative_to(report))
    os.replace(temporary, destination)
    Path(str(destination)+'.sha256').write_text(io.sha(destination)+'  '+destination.name+'\n')
    return destination

def execute(args):
    started = time.monotonic()
    project, desktop = args.project_root.expanduser().resolve(), args.desktop.expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError('Connect XT_Pro or set IV_PROJECT_ROOT: project folder unavailable')
    release_sha = verify_release()
    io.log('Verifying the frozen headline file (about 295 MB)')
    headline, source = authenticate_headline(project)
    try:
        run3_path, run3_source = (None, dict(status='SKIPPED_BY_OPTION')) if args.headline_only else authenticate_run3(project)
    except (RuntimeError, OSError, KeyError, ValueError) as error:
        io.log('Optional Run 3 cache not accepted: '+str(error))
        run3_path, run3_source = None, dict(status='VERIFICATION_FAILED_COMPANION_NOT_RUN', error_type=type(error).__name__)
    config = dict(version=VERSION, release_manifest_sha256=release_sha, headline_sha256=HEADLINE_SHA,
                  run3_sha256=run3_source.get('sha256'), score_bands=args.bands,
                  weighting='exposure; equal opponent over exposures; first observed eligible opponent snapshot',
                  no_network=True, reference_SD=REFERENCE_SD)
    conf = io.cfgsha(config)
    root = project/'derived/replication/iv_slide_gaps_v100_PRIVATE'/conf[:12]
    root.mkdir(parents=True, exist_ok=True)
    with (root/'RUN.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This slide-gap audit is already running')
        io.js(root/'inputs_PRIVATE.json', dict(headline=source, run3=run3_source))
        io.js(root/'DESIGN_FREEZE.json', config)
        io.log('Read-only audit; one full-cohort fit at a time. No downloads or history rebuilds.')
        io.log('Planning estimate: about 5–20 minutes with both cached cohorts; not benchmarked on this Mac.')
        primary, _ = analyze_cohort(headline, root/'headline_original', conf, 'headline_original', args.bands, True, HEADLINE_FIT)
        companion = None
        if run3_path:
            expected = io.load(ROOT/'evidence/run3_overall_first_stage.json')
            companion, _ = analyze_cohort(run3_path, root/'run3_author_clean', conf, 'run3_author_clean', args.bands, False, expected)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(os.getpid())
        audit_root = root/('cache_audit_'+stamp)
        audit_root.mkdir()
        io.log('Checking profile-cache schemas and local Run 2 receipts')
        profile_rows, profile_summary = cache_audit.audit_profiles(project, audit_root, args.profile_path)
        run2 = cache_audit.audit_run2_status(project, desktop, audit_root)
        def assemble(tmp):
            shutil.copytree(primary, tmp/'headline_original')
            if companion:
                shutil.copytree(companion, tmp/'run3_author_clean')
            io.js(tmp/'design.json', config)
            io.js(tmp/'companion_status.json', {k:v for k,v in run3_source.items() if k not in ('path', 'signature')})
            io.js(tmp/'profile_audit.json', profile_rows)
            write_csv(tmp/'profile_audit.csv', profile_rows)
            io.js(tmp/'profile_audit_summary.json', profile_summary)
            io.js(tmp/'run2_status_snapshot.json', run2)
            io.js(tmp/'runtime.json', dict(seconds=time.monotonic()-started, created_UTC=stamp))
            shutil.copy2(ROOT/'METHODS.txt', tmp/'METHODS.txt')
            read_results(tmp)
            return dict(status='SLIDE_GAP_DIAGNOSTICS_COMPLETE',
                        profile_status=profile_summary['status'], run3_included=companion is not None,
                        headline_IV_reestimated=False)
        report, _ = io.stage(root/('report_'+stamp), conf, assemble)
        destination = package_report(report, desktop, 'IV_SLIDE_GAPS_REPORT_'+stamp)
        io.log('Complete. Read READ_RESULTS.txt inside the report.')
        print('RETURN THIS AGGREGATE REPORT: '+str(destination), flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=BASE)
    parser.add_argument('--desktop', type=Path, default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--bands', type=int, choices=range(2, 21), default=10)
    parser.add_argument('--headline-only', action='store_true', help='Skip the cached author-clean Run 3 companion')
    parser.add_argument('--profile-path', action='append', default=[], help='Additional profile file/folder to inspect; repeatable')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        execute(args)
    except KeyboardInterrupt:
        io.log('Interrupted. Completed cohort diagnostics remain reusable.')
        raise SystemExit(130)
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)

if __name__ == '__main__':
    main()
