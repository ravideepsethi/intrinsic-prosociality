from env_common import *

def export(root,desktop,conf,status,started):
    report=root/'report';report.mkdir(exist_ok=True)
    allrows={key:[] for key in ('estimates','balance','bins','support','bridge','joint_balance','accounting','numerics')}
    for path in sorted((root/'models').glob('*/result.json')):
        if not (path.parent/'_DONE.json').is_file():continue
        io.complete(path.parent,conf)
        d=io.load(path)
        for key in allrows:allrows[key]+=d.get(key,[])
    # Each outcome family, sample and control set is declared separately; no cross-look guarantee.
    e=allrows['estimates']
    for cohort in {r.get('cohort') for r in e}:
        for sample in {r.get('sample') for r in e}:
            for level in {r.get('control_level') for r in e}:
                family=[r for r in e if r.get('kind')=='entry' and r.get('cohort')==cohort and r.get('sample')==sample and r.get('control_level')==level and r.get('outcome') in ENTRY_COLUMNS]
                if family:stats.stats.holm(family,out='p_Holm_10_entry_tests')
    for key,value in allrows.items():oldreport.write_rows(report,key,value)
    # Diagnostics contain names and numeric aggregates only, never player/game IDs.
    numerical_progress=[io.load(p) for p in sorted((root/'numerical_progress').glob('*.json'))]
    io.js(report/'numerical_progress.json',numerical_progress)
    if (root/'failure_summary.json').is_file():shutil.copyfile(root/'failure_summary.json',report/'failure_summary.json')
    elif (report/'failure_summary.json').exists():(report/'failure_summary.json').unlink()
    for src,name in [(root/'prepared_entry/bins.json','score_bin_definition.json'),(root/'rates/coverage.json','rate_coverage.json'),
                     (root/'scan_plan.json','scan_plan.json'),(root/'performance.json','performance.json'),
                     (root/'iv_assembled/reproduction.json','receipt_reconstruction.json'),
                     (root/'status_audit/status_coverage.json','status_coverage.json'),
                     (root/'status_audit/status_coverage.csv','status_coverage.csv'),
                     (root/'recovery.json','checkpoint_recovery.json')]:
        if src.exists():shutil.copyfile(src,report/name)
    summary=dict(version=VERSION,status=status,config_sha256=conf,elapsed_seconds=time.monotonic()-started,
        network_requests=0,stockfish_searches=0,chronology_global_sort=False,entries_reproduced=len(allrows['bridge']),
        completed_model_checkpoints=len(list((root/'models').glob('*/_DONE.json'))),
        checked_numerical_fits=len(allrows['numerics']),
        receipt_IV_reestimated=any(r.get('estimator')=='2SLS' for r in e),ordinary_placebo_reestimated=any(r.get('kind')=='ordinary' for r in e),
        environment_controls_completed=any(r.get('control_level')=='XC_both_rates' and r.get('kind')=='iv' for r in e),
        historical_numerators='certified active-resolution disconnections; not every physical connection drop',
        exposure_cohort='original frozen 2,682,330-row receipt cohort, reconstructed then author-cleaned; no newly extended receipt cohort substituted',
        country_status='NOT_ESTIMATED: no authenticated historical profile source is bound to this package; no profile API calls',
        causal_identification_certified=False,abstract_gate_cleared=False,nominal_interim_intervals=True,
        rate_control_caveat='Observed histories are imperfect proxies for connection environment; stable 2SLS and improved balance cannot establish exclusion')
    io.js(report/'summary.json',summary)
    lines=['Run 2: disconnection environment, score bins and linked IV diagnostics','',status,'',
        'Read status_coverage.json first if the run stops before estimation. Missing legacy status may arrive as None or numeric NaN after Parquet conversion; neither is an observed ending. Every known status is checked against active_timeout even in a mixed cohort. Entry labels and rows are preserved.',
        'Read estimates.csv and bins.csv for completed models. bridge.csv must reproduce the completed entry XC results.',
        'Version 1.0.2 uses contiguous columns and sorted group means for the same fixed-effect projection. Every fit checks finite residuals, non-increasing sums of squares and final group-mean orthogonality. See numerics.json and numerical_progress.json. Models are refitted; prepared Parquets and upstream features are reused. A failed fit supplies no estimates. Completed fits are exported immediately, including when a later fit fails.',
        'The quick report labels verified recipient-disconnect, verified opponent-disconnect and timeout-role-unclassified separately. They add up to timeout. Unclassified timeouts are never attributed to the opponent.',
        'Bins are fixed from the completed ordinary-game competitive score distribution, including its previously frozen 95th-percentile cutoff. Raw event rates, adjusted outcome means, row shares, residual score variance and exact contributions to the full-sample adjusted slope are separate columns. Slope contributions are an algebraic description, not causal attribution; adjusted means condition on fitted controls and have no probability interpretation.',
        'New environment histories: games starting in the 90 days ending seven days before the exposure month begins. A certified active resolution counts only if it also finished strictly before that cutoff. Both players must be author-clean. The current recipient-opponent pair is subtracted from both numerators and denominator. Unknown/incomplete windows and zero other-opponent games are explicitly unsupported, never filled with zero.',
        'The denominator is games in the authenticated rated-game chronology. The two numerators are observed certified active resolutions, in either role, across board states. They are not a census of internet failures or all raw disconnection events. An independent reconciliation checks that every relevant numerator event is found in the canonical game universe.',
        'XC is the previous rich control set plus competitive-history controls. XC_volume adds opponent game count; XC_volume_own and XC_volume_chooser add each rate separately; XC_both_rates adds both. Every row in this ladder uses the SAME supported sample. Compare its XC baseline with the full competitive-supported baseline to see the effect of support selection.',
        'Both instruments are fitted separately on identical rows. Their fixed SD units differ; raw coefficients remain available. A stable IV ratio can hide changes in its numerator or denominator: inspect reduced form, first stage and first-stage F next to 2SLS and AR intervals.',
        'Balance checks use seven pre-existing recipient 30-day traits. Included opponent rate controls are not presented as independent balance tests. Holm adjustment is within the seven traits; the joint test retains the original covariance rules.',
        'The original receipt cohort is reconstructed with the same spacing, lag, current-pair exclusion, cross-fit reference and future-choice rules; both authors are removed from focal games, histories, reference and later choices. The original included-author features must reproduce before the clean sample is used. This does not extend the receipt cohort.',
        'The ordinary comparison is the completed 25% competitive-supported sample. The outoftime comparison uses recorded ending status only, and is unavailable for cohorts with missing legacy status. It is an ending comparison, not a test that timeout necessarily means an internet problem.',
        'Shared-account OR exposure-date CR0 inference is unchanged; generated scores are fixed. These are exploratory nominal intervals after prior results, not sequentially valid stopping rules. A disappearing entry/balance association with stable receipt estimates supports this particular explanation; it does not prove IV exclusion.',
        'Country is not estimated because no authenticated historical profile source is bound to this package. No API, Stockfish, downloader changes or new metadata exclusions. The existing two focal-record quarantines remain unchanged.',
        'A completed quick report remains useful if a later stage encounters a missing input. Return this aggregate ZIP and the terminal log if execution stops.','']
    (report/'READ_RESULTS.txt').write_text('\n'.join(lines))
    report_zip(report,desktop,'RUN2_ENVIRONMENT_DIAGNOSTICS_REPORT_'+conf[:12])
    return summary
