#!/usr/bin/env python3
"""Run 3: local, checkpointed subgroup first stages and complier descriptions."""
from __future__ import annotations
from common import *
import argparse, fcntl, time, traceback
import author_history as history
import leniency_stats as models

def method_status():
    return dict(status='NOT_RUN_DESIGN_ADAPTATION_REQUIRED',
        test='Frandsen–Lefgren–Leslie (2023), AER 113(1), 253–277',
        DOI='10.1257/aer.20201860',
        reason='Published test uses mutually exclusive assignment instruments and their treatment propensities. '
               'This instrument is a time-varying, state-adjusted, pair-leave-all-out historical score. '
               'Treating chooser IDs or score bins as those assignment instruments changes the design; '
               'a validated mapping and inference adaptation are not available in these source packages.',
        linear_overidentification_test_substituted=False,formal_p_value=None,
        source='https://sites.google.com/view/brighamfrandsen/software',
        subgroup_positive_first_stages_prove_monotonicity=False,
        run3_diagnostics_gate_submission=False)

def execute(a):
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if not project.is_dir():raise RuntimeError('Connect XT_Pro: project directory is unavailable')
    package_sha=verify_package();start=time.monotonic()
    specs=models.subgroup_specs()
    config=dict(version='1.0.0',package_manifest_sha256=package_sha,
        source_spaced90_sha256=SPACED_SHA,reference_score_SD=REFERENCE_SD,
        author_accounts=AUTHORS,exposure_spacing='preserve_frozen90_no_replacement',
        subgroup_specs=specs,rating_bin_cutpoints=[1200,1600,2000],
        inference='shared_account_OR_date_CR0_normal_historical_scores_fixed',
        prior_granting_window='[start-97d,start-7d)',minimum_rows=models.MIN_ROWS,
        minimum_receipts_or_nonreceipts=models.MIN_RECEIPTS,complier_weights='unclipped',
        outcome_y_not_read=True,old_headline_IV_not_reestimated=True,
        formal_FLL=method_status())
    conf=io.cfgsha(config);root=project/'derived/replication/iv_run3_leniency_v100_PRIVATE'/conf[:12]
    root.mkdir(parents=True,exist_ok=True)
    with (root/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This Run 3 job is already running')
        io.js(root/'DESIGN_FREEZE.json',config)
        io.log(f'RUN3: up to {a.workers} processes; {a.memory_gb} GiB working allowance; Parquet caches; no SciPy/API.')
        io.log('Expected first run: roughly 1–3 hours on a fast laptop/SSD; completed-stage reruns are shorter. This is an unbenchmarked estimate.')
        io.log('Output: '+str(root))
        tick=time.monotonic();inputs=history.authenticate(project,a.workers)
        io.js(root/'inputs_PRIVATE.json',inputs);timing={'authenticate_seconds':time.monotonic()-tick}
        tick=time.monotonic();sample,accounting=history.build_clean_sample(inputs,root,conf,a.workers)
        timing['clean_histories_and_sample_seconds']=time.monotonic()-tick
        sample_path=sample/'sample.parquet'
        # Largest full-cohort fit is completed alone to avoid ten overlapping copies.
        jobs=[dict(sample=str(sample_path),spec=s,output=str(root/'fits'/f'{k:02}_{s["dimension"]}_{s["label"]}'),conf=conf)
              for k,s in enumerate(specs)]
        tick=time.monotonic()
        rows=models.subgroup_job(jobs[0])
        rest=io.mapped(models.subgroup_job,jobs[1:],a.workers,'Subgroup first stages')
        for r in rest:rows.extend(r)
        timing['first_stage_seconds']=time.monotonic()-tick
        summary=models.finalize_first_stages(rows)
        def complier_build(tmp):
            d=arrays(io.read(sample_path,MODEL_COLS));results,details=models.complier_means(d)
            io.js(tmp/'results.json',results);return details
        tick=time.monotonic();complier,_=io.stage(root/'complier',conf,complier_build)
        timing['complier_seconds']=time.monotonic()-tick
        timing['total_seconds']=time.monotonic()-start
        def report_build(tmp):
            write_rows(tmp,'first_stages',rows)
            write_rows(tmp,'complier_means',io.load(complier/'results.json'))
            io.js(tmp/'sample_flow.json',{k:v for k,v in accounting.items() if k not in ('files','config_sha256')})
            io.js(tmp/'formal_leniency_test_status.json',method_status())
            io.js(tmp/'design.json',config);io.js(tmp/'runtime.json',timing)
            result=dict(status='SUBGROUP_AND_COMPLIER_DIAGNOSTICS_COMPLETE_FORMAL_FLL_PENDING',
                        rows=accounting['rows'],**summary,headline_IV_reestimated=False,
                        abstract_gate_changed=False,formal_FLL_status=method_status()['status'])
            io.js(tmp/'summary.json',result)
            text=['Run 3: leniency diagnostics','',
                f"Author-clean diagnostic sample: {accounting['rows']:,} frozen 90-day-spaced exposures.",
                f"Supported subgroups: {summary['supported_subgroups']} / {summary['subgroups']}.",
                f"Negative adjusted point estimates: {summary['negative_points']}; 95% intervals entirely below zero: {summary['negative_ci95']}.",
                f"Raw/adjusted sign reversals: {summary['raw_adjusted_reversals']}.",'',
                'first_stages.csv reports raw and adjusted first stages in percentage points per fixed historical score SD, with shared-account OR date CR0 intervals, F and partial R-squared.',
                'Models refit the same covariate and fixed-effect structure within each subgroup. Sparse/empty cells remain explicit; a missing estimate is not zero.',
                'Prior granting means the lagged 90-day history, not lifetime history. Author-involving behavior is removed from both own histories and the nuisance reference. Factual game activity is retained.',
                'Complier means describe the continuous instrument’s weighted treatment margin under the maintained conditional IV assumptions. Negative weights and estimates outside observed ranges are reported, not clipped. They do not describe a directly observed group of people.',
                'Scores are treated as fixed in inference, as in the existing analysis; wider network and score-estimation uncertainty are not fully propagated.',
                'The formal Frandsen–Lefgren–Leslie test has NOT been run. Its assignment-instrument mapping and inference require a separate validated adaptation. No linear overidentification or positive-first-stage check is labeled that test.',
                'This run does not reestimate the headline IV, validate exclusion, clear the abstract/Contagious gate, or replace the planned extended cohort. The recipient outcome is not loaded.',
                'Keep the IV in the main text with the v2 placebo limitation until Run 2 is actually estimated and reviewed.','']
            (tmp/'READ_RESULTS.txt').write_text('\n'.join(text))
            return result
        report,_=io.stage(root/'report',conf,report_build)
        out=pack_report(report,desktop,'IV_RUN3_LENIENCY_REPORT_'+conf[:12])
        io.log('Subgroup and complier diagnostics complete. Formal FLL remains explicitly unrun.')
        print('RETURN THIS AGGREGATE REPORT: '+out,flush=True)

def main():
    workers,memory=defaults();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=BASE)
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=int(os.environ.get('IV_WORKERS',workers)))
    p.add_argument('--memory-gb',type=int,default=int(os.environ.get('IV_MEMORY_GB',memory)))
    a=p.parse_args();os.umask(0o077)
    if a.memory_gb<4 or a.workers<1:p.error('Need at least 4 GiB and one worker')
    a.workers=max(1,min(a.workers,10,os.cpu_count() or 1,int((a.memory_gb-2)//1.25)))
    try:execute(a)
    except KeyboardInterrupt:io.log('Interrupted. Completed checkpoints remain reusable.');raise SystemExit(130)
    except Exception:
        traceback.print_exc();raise SystemExit(2)
if __name__=='__main__':main()
