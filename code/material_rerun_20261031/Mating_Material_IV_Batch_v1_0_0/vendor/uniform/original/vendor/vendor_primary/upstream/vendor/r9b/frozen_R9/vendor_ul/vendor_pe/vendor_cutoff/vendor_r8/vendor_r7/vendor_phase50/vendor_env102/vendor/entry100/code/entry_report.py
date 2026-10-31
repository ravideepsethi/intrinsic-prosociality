"""Small aggregate deliverable; no game IDs, usernames or private paths."""
from entry_common import *


def write_rows(root,name,rows):
    io.js(root/(name+'.json'),rows);csvout(root/(name+'.csv'),rows)
    if not rows:return
    flat=[{k:json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in io.clean(rows)]
    keys=sorted(set().union(*(r.keys() for r in flat)))
    io.table(root/(name+'.parquet'),pa.Table.from_pylist([{k:r.get(k) for k in keys} for r in flat]))


def export(root,desktop,conf,status,started,binding):
    report=root/'report';report.mkdir(exist_ok=True);Path(desktop).mkdir(parents=True,exist_ok=True)
    results=[];bridges=[];contrasts=[];support=[];transitions=[]
    for p in sorted((root/'models').glob('*/result.json')):
        d=io.load(p);results+=d['estimates'];bridges+=d['bridge'];contrasts+=d['contrasts'];support+=d['support'];transitions+=d['transitions']
    # Declared multiplicity family: five entry stages x two score definitions,
    # separately for each common-row control specification and cohort.
    for cohort in COHORTS:
        for level in ('X0','XC'):
            selected=[r for r in results if r.get('cohort')==cohort and r.get('sample')=='competitive_supported' and r.get('control_level')==level and r.get('outcome') in ENTRY_COLUMNS]
            if selected:stats.stats.holm(selected,out='p_Holm_10_stage_instrument_tests')
    comparison=[]
    for cohort in COHORTS:
        for outcome in ENTRY_COLUMNS:
            rows=[r for r in results if r.get('cohort')==cohort and r.get('outcome')==outcome]
            def get(sample,level,instrument):return next((r for r in rows if r.get('sample')==sample and r.get('control_level')==level and r.get('instrument')==instrument),{})
            specs=[('pooled_all_X0','all_entry','X0','pooled'),('pooled_common_X0','competitive_supported','X0','pooled'),
                   ('competitive_common_X0','competitive_supported','X0','competitive'),('pooled_common_XC','competitive_supported','XC','pooled'),
                   ('competitive_common_XC','competitive_supported','XC','competitive')]
            for label,sample,level,instrument in specs:
                r=get(sample,level,instrument)
                if r:comparison.append(dict(r,comparison_step=label))
    coverage=io.load(root/'prepared/support.json') if (root/'prepared/support.json').is_file() else []
    summary=dict(version=VERSION,status=status,config_sha256=conf,parent_config_sha256=binding['parent_config_sha256'],
        elapsed_seconds=time.monotonic()-started,network_requests=0,stockfish_searches=0,chronology_scans=0,
        estimates=len(results),reproduced_original_entry_estimates=len(bridges),
        main_reading='new_phase25, competitive_supported, XC, competitive, analysis_entry_90',
        secondary_post_result_analysis=True,nominal_interim_intervals=True,sequential_coverage_guarantee=False,
        causal_identification_certified=False,receipt_IV_reestimated=False,abstract_gate_cleared=False,
        quarantine=binding['quarantine'],score_units=dict(pooled_reference_SD=stats.REFERENCE_SD,competitive_reference_SD=secondary.COMP_REFERENCE_SD,
        competitive_reference_source='Oct 3 S1 XC author-included unit, used for scaling only; all score histories in this analysis are author-clean'),
        support=coverage)
    io.js(report/'summary.json',summary)
    for name,rows in [('entry_comparison',comparison),('all_estimates',results),('same_row_slope_contrasts',contrasts),
       ('residual_support',support),('stage_accounting',transitions),('sample_support',coverage),('original_entry_reproduction',bridges)]:
        write_rows(report,name,rows)
    for name in ('performance.json','execution.json'):
        if (root/name).is_file():shutil.copyfile(root/name,report/name)
    lines=['Run 2: entry association diagnostics on the completed 25% sample','',status,'',
      'Start with entry_comparison.csv. The five rows per outcome separate sample support, score definition and controls.',
      'Pooled/all/X0 must reproduce the completed 25% report before new comparisons run.',
      'Pooled/common/X0 versus pooled/all/X0 diagnoses how restricting to >=5 competitive history decisions changes the population. It is not a causal selection effect.',
      'Pooled/common versus competitive/common uses identical rows and controls. X0 is the original rich control set. XC adds competitive expected rate, decision count and counterpart breadth.',
      'The principal new diagnostic is the competitive score, common rows, XC, analysis_entry_90, new_phase25.',
      'The first10 and added10–25 bands contain different games but share accounts; they are not independent replications. old_author_clean and pooled are supplemental.',
      'All stage regressions retain the same pre-entry denominator. active_timeout is the platform timeout ending; recipient_disconnect_main requires the certified main panel and focal role. recipient_fair_arm_main requires the certified competitive arm. These are observed labels, not a census of every physical disconnection.',
      'selected_entry_90 and analysis_entry_90 describe whether this focal game enters the original spaced receipt sample. They are not later kindness outcomes.',
      'The four stage-loss outcomes partition the difference between adjacent nested labels. Their coefficients add algebraically; this is accounting, not causal mediation. Conditional pass percentages in stage_accounting are descriptive only.',
      'all_estimates.csv also gives a fixed control ladder on common rows: assignment/time FEs, then ratings, then opponent history, then recipient history (X0), then competitive history (XC). Ladder results are exploratory, not specification selection.',
      'Every coefficient_pp uses its instrument-specific fixed reference SD. Do not compare these magnitudes as though the units were identical. coefficient_pp_per_raw_0_10 uses a common raw-score increment.',
      'same_row_slope_contrasts.csv tests differences between separate slopes per identical raw 0.10 increment, with their covariance. It does not subtract independent standard errors or estimate jointly instrumented receipt effects.',
      'residual_support reports precision support and the residual-variance share above the already frozen ordinary-game 95th-percentile cutoff. No outcome-dependent trimming or replacement rows occur.',
      'Intervals use the original shared-account OR exposure-date CR0 covariance; historical scores are treated as fixed. Nonpositive covariance is flagged, not repaired.',
      'p_Holm_10_stage_instrument_tests adjusts five nested stages x two scores within a cohort and X0/XC family. It does not correct prior looks, other cohorts, or the exploratory control ladder.',
      'A negative competitive-score entry association would retain the selection concern. A near-zero estimate only helps if its interval is informative. Neither result proves or disproves IV exclusion; no receipt IV is reestimated here.',
      'The original +0.0204 ordinary-outcome sensitivity benchmark is not an entry-equivalence margin and is not transferred to this test.',
      'The two previously reviewed focal-record quarantines remain unchanged. No API, Stockfish, all-history chronology scan, new metadata exclusion, or downloader modification.','']
    for r in comparison:
        if r.get('cohort')=='new_phase25' and r.get('outcome') in ('recipient_disconnect_main','recipient_fair_arm_main','analysis_entry_90'):
            lines.append(r['outcome']+' / '+r['comparison_step']+': '+(f"N={r['n']:,}; {r['coefficient_pp']:+.6f} pp/fixed SD; 95% CI [{r['ci_low_pp']:+.6f}, {r['ci_high_pp']:+.6f}]" if r.get('supported') else 'Unsupported: '+r.get('reason','unknown')))
    (report/'READ_RESULTS.txt').write_text('\n'.join(lines)+'\n')
    report_zip(report,desktop,'RUN2_ENTRY_DIAGNOSTICS_REPORT_'+conf[:12])
    return summary
