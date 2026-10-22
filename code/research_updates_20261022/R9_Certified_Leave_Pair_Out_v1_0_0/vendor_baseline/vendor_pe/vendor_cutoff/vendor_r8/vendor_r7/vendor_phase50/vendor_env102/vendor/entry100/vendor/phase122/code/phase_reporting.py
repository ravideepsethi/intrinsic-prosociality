"""Interim inference and small aggregate reports; estimates never stop the download."""
from phase_features import *
import math,time

VERSION='1.1.0'
DIRECT_EFFECT_PP=.02038591312056039
MARGIN_PP=.015
COHORTS=('new_phase10','old_author_clean','pooled')

def precision_fields(row):
    if not row.get('supported'):return {}
    b=float(row['coefficient_pp']); se=float(row['standard_error_pp'])
    if not np.isfinite([b,se]).all() or se<=0:raise RuntimeError('Invalid estimated uncertainty')
    lo=b-1.6448536269514722*se;hi=b+1.6448536269514722*se
    p1=.5*math.erfc((b+MARGIN_PP)/se/math.sqrt(2))
    p2=.5*math.erfc((MARGIN_PP-b)/se/math.sqrt(2))
    return dict(ci90_low_pp=lo,ci90_high_pp=hi,equivalence_margin_pp=MARGIN_PP,
        nominal_TOST_p=max(p1,p2),nominal_equivalence_90CI_inside_margin=(lo>-MARGIN_PP and hi<MARGIN_PP),
        direct_effect_benchmark_pp=DIRECT_EFFECT_PP,
        ci95_includes_direct_effect_benchmark=row['ci_low_pp']<=DIRECT_EFFECT_PP<=row['ci_high_pp'],
        ci95_includes_negative_benchmark=row['ci_low_pp']<=-DIRECT_EFFECT_PP<=row['ci_high_pp'],
        interim_only=True,sequential_coverage_guarantee=False,abstract_gate_cleared=False)

def model_job(job):
    threads_one()
    def build(tmp):
        d=arrays(io.read(job['sample']));spec=SPECS[job['family']]
        r=stats.estimate(d,spec);r['cohort']=job['cohort'];r['sample_accounting']=stats.describe(d)
        for row in r['estimates']:
            row.update(cohort=job['cohort'],phase_percent=10,interim_only=True,abstract_gate_cleared=False)
            if job['family']=='ordinary' and row.get('outcome')=='y':row.update(precision_fields(row))
        io.js(tmp/'result.json',r);return dict(rows=len(d['row_id']))
    return stable_stage(Path(job['output']),job['conf'],build,[job['sample']])[1]

def export(root,desktop,conf,coverage,status,started,details=None):
    report=root/'report';report.mkdir(exist_ok=True)
    quarantine_path=root/'quarantine/summary.json'
    quarantine_info=io.load(quarantine_path) if quarantine_path.is_file() else None
    if sum(r['unresolved_rows'] for r in coverage) and quarantine_info is None:
        raise RuntimeError('Unresolved records must have a completed explicit quarantine audit before export')
    summary=dict(version=VERSION,status=status,phase_percent=10,config_sha256=conf,
        network_requests=0,stockfish_searches=0,
        fixed_additional_frame_rows=sum(r['selected_frame_rows'] for r in coverage),
        pool_games_before_chronology=sum(r['pool_rows'] for r in coverage),
        ordinary_games_before_chronology=sum(r['ordinary_rows'] for r in coverage),
        unresolved_selected_rows=sum(r['unresolved_rows'] for r in coverage),
        abstract_gate_cleared=False,title_gate_cleared=False,full_expansion_equivalence_gate_cleared=False,
        sample_selected_by_fixed_hash=True,cache_selected_sample=False,
        nominal_interim_intervals=True,download_schedule_changed=False,
        generated_scores_treated_as_fixed=True,elapsed_seconds=time.monotonic()-started,**(details or {}))
    summary.update(available_case_interim=quarantine_info is not None,
        metadata_quarantine=quarantine_info,full_phase_metadata_resolved=not bool(summary['unresolved_selected_rows']))
    if quarantine_info is not None:io.js(report/'metadata_quarantine.json',quarantine_info)
    for name,path in [('legacy_schema',root/'prepared/legacy_schema.json'),
                      ('baseline_feature_check',root/'baseline_feature_check/summary.json'),
                      ('early_eligibility',root/'early/summary.json'),
                      ('score_support',root/'support/summary.json'),
                      ('chronology_eligibility',root/'work/summary.json'),
                      ('performance',root/'performance.json')]:
        if path.is_file():
            info=io.load(path);summary[name]=info;io.js(report/(name+'.json'),info)
    if (root/'early/summary.json').exists():
        summary['sample_flow_note']='Model flow begins at the feature-work subset; early eligibility and chronology dispositions account for excluded candidates without fabricated features.'
    endings=[r for month in coverage for r in month['ending_counts']]
    dispositions=[dict(month=m['month'],disposition=k,rows=v) for m in coverage for k,v in m['dispositions'].items()]
    write_rows(report,'coverage_by_ending',endings);write_rows(report,'frame_dispositions',dispositions)
    rows=[];balance=[];joint=[]
    for family in SPECS:
        for cohort in COHORTS:
            path=root/'models'/(family+'_'+cohort)/'result.json'
            if path.exists():
                r=io.load(path);rows+=r['estimates']
                balance += [dict(v,cohort=cohort) for v in r['balance']]
                joint += [dict(v,cohort=cohort) for v in r['joint_balance']]
    original=[dict(r,cohort='historical_original') for r in io.load(VENDOR/'comparison_original/evidence/expanded_estimates.json')
              if r.get('specification') in ('ordinary90_placebo','entry90_pooled')]
    old=next(r for r in original if r.get('outcome')=='y')
    for cohort in COHORTS:
        primary=[]
        for family,outcome in [('ordinary','y'),('entry','analysis_entry_90')]:
            found=next((r for r in rows if r['cohort']==cohort and r['family']==family and r.get('outcome')==outcome),None)
            primary.append(found if found is not None else dict(supported=False))
        stats.stats.holm(primary,out='p_Holm_two_primary_within_phase')
    for row in rows:
        row['metadata_scope']='earlier_author_clean_sample' if row['cohort']=='old_author_clean' else ('available_case_interim' if quarantine_info else 'complete_metadata_interim')
        row['quarantined_focal_records']=0 if row['cohort']=='old_author_clean' else (quarantine_info or {}).get('quarantined_rows',0)
        if row.get('outcome')=='y' and row.get('supported'):
            projected=old['standard_error_pp']*math.sqrt(old['n']/row['n'])
            row.update(historical_SE_pp=old['standard_error_pp'],iid_scaling_projection_SE_pp=projected,
                measured_to_projected_SE_ratio=row['standard_error_pp']/projected,
                sample_size_relative_to_original=row['n']/old['n'],
                achieved_SE_relative_to_original=row['standard_error_pp']/old['standard_error_pp'])
    summary['estimates']=rows;summary['historical_original_estimates']=original
    io.js(report/'summary.json',summary)
    write_rows(report,'estimates',original+rows)
    if balance:write_rows(report,'entry_balance',balance)
    if joint:write_rows(report,'entry_joint_balance',joint)
    if (root/'assembled/flow.json').is_file():write_rows(report,'sample_flow',io.load(root/'assembled/flow.json'))
    if (root/'prepared/baseline_reproduction.json').is_file():
        io.js(report/'original_numerical_reproduction.json',io.load(root/'prepared/baseline_reproduction.json'))
    text=['Run 2: fixed 10% sample, available-case interim analysis','',status,'',
          ('One April 2024 focal record remains quarantined for a cache conflict or prior error flag. It remains in the fixed-frame accounting, contributes to no regression, and is not replaced. The metadata flag has not been repaired.' if quarantine_info else 'No unresolved metadata records.'),
          ('Read metadata_quarantine.json for aggregate field diagnostics. Private record values remain on the Mac. The small row count is not a bound on coefficient bias.' if quarantine_info else ''),
          'First read estimates.csv: ordinary90_placebo, outcome y, cohort new_phase10.',
          'Then read entry90_pooled: all five entry outcomes and the two-primary Holm correction.',
          'new_phase10 uses the verified, available records from the fixed additional-game sample. old_author_clean is the earlier sample recomputed with author exclusions. pooled is supplemental; it is not an independent replication.',
          'The runner reproduces both earlier original regressions before constructing the new samples, then verifies original row-level scores, histories, later choices and entry labels.',
          'Same frozen controls, fixed score SD and shared-account OR exposure-date CR0 covariance. Historical/generated scores are treated as fixed.',
          'The two designated primary diagnostics are ordinary kindness and analysis_entry_90. Their Holm correction is within this phase and cohort; it does not correct repeated looks across phases.',
          'Ordinary endings are mate, resignation and stalemate. Entry retains all ending types and uses calendar support from game start. Ordinary later kindness additionally requires complete 90-day follow-up from lastMoveAt.',
          'Author accounts are excluded from focal games, behavior histories, score reference fitting and later choices. Full factual chronology and the original pre-censoring exposure spacing stream remain intact.',
          'The +0.020385913 pp/SD benchmark is the original reduced-form/direct-effect sensitivity number. Report both whether its value lies in the interval and the full interval; a null p-value is insufficient.',
          'Equivalence at +/-0.015 pp is a nominal TOST/90% interval diagnostic only. The completed 100% analysis remains required for the planned abstract/title decision. These checks cannot prove the IV exclusion assumption.',
          'This runner concerns Run 2. It does not rerun the main receipt IV, Run 3 subgroup first stages, or the November color-change analysis.',
          'Zero API requests. No downloader files or request lists are modified.','']
    for r in rows:
        if r.get('outcome') not in ('y','analysis_entry_90') and r.get('supported'):continue
        text.append(f"{r['cohort']} {r['specification']} {r.get('outcome','unsupported')}: "+
            (f"N={r['n']:,}; estimate {r['coefficient_pp']:+.6f} pp/SD; 95% CI [{r['ci_low_pp']:+.6f}, {r['ci_high_pp']:+.6f}]." if r.get('supported') else f"Not estimated: {r.get('reason')}; N={r.get('n',0):,}."))
    (report/'READ_RESULTS.txt').write_text('\n'.join(text)+'\n')
    report_zip(report,desktop,'RUN2_PHASE_010_ANALYSIS_REPORT_'+conf[:12])
    return summary
