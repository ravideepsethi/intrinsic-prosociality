from __future__ import annotations
import os
from pathlib import Path
import zipfile
import pandas as pd
from .common import PACKAGE_ROOT,atomic_json,atomic_text,sha256_file,utc_now


def write_csv(path,frame):
    temporary=path.with_suffix('.csv.tmp')
    frame.to_csv(temporary,index=False)
    os.replace(temporary,path)


def number(value,digits=3):
    return f'{value:.{digits}f}' if pd.notna(value) else 'undefined'


def write_report(public,tables,metadata,*,synthetic=False):
    public.mkdir(parents=True,exist_ok=True)
    for name,table in tables.items():write_csv(public/name,table)
    for name,data in metadata.items():atomic_json(public/name,data)
    for name in ('METHODS.md','INTERPRETATION.md'):
        atomic_text(public/name,(PACKAGE_ROOT/'docs'/name).read_text())
    flow=tables['common_support_flow.csv'].set_index('scope')
    descr=tables['rating_activity_summary.csv'].set_index('scope')
    rates=tables['standardized_state_rates.csv']
    pairs=tables['standardized_activity_comparisons.csv']
    baseline=tables['baseline_activity_comparisons.csv']
    base=baseline[(baseline.weighting=='equal_chooser')&(baseline.comparison=='heavy_versus_light')].iloc[0]
    lines=['# Activity, rating composition and state-specific granting','']
    if synthetic:lines+=['**SYNTHETIC TEST ONLY — not empirical results.**','']
    lines+=[f'The original full both-state sample contains {int(flow.loc["all","full_choosers"]):,} choosers. '
        f'The joint common-support comparison retains {int(flow.loc["all","common_support_choosers"]):,} '
        f'({flow.loc["all","retained_chooser_pct"]:.3f}%), including '
        f'{int(flow.loc["all","common_observed_nongranters"]):,} choosers with no grants in the binary comparison. '
        'Support is selected using covariates and chooser counts only, never grant outcomes.','',
        '## Does observed activity increase with rating?','',
        '| Activity | Choosers | Mean rating | Median rating | Missing ratings | Mean share in modal time control |',
        '|---|---:|---:|---:|---:|---:|']
    for g in ('light','medium','heavy'):
        r=descr.loc[g]
        lines.append(f'| {g} | {int(r.choosers):,} | {number(r.rating_mean,1)} | {number(r.rating_median,1)} | '
                     f'{int(r.choosers_missing_rating):,} | {r.mean_modal_time_control_share:.3f} |')
    d=descr.loc['all']
    lines+=['',f'Across all both-state choosers, Pearson correlation of rating with the binary opportunity count: '
        f'{number(d.pearson_rating_binary_count)}; Spearman correlation: {number(d.spearman_rating_binary_count)}. '
        'Rating is the mean pre-game chooser rating in the chooser\'s modal observed time control, defined jointly '
        'with speed. It is a chooser-level summary over this panel, not a baseline or randomized variable.','',
        '## Same-sample comparison','',
        '| Adjustment | Activity | Competitive (%) | Clearly worse (%) | Gap (pp) | RR |',
        '|---|---|---:|---:|---:|---:|']
    labels={'unadjusted_common_support':'Unadjusted, common support','rating_standardized':'Rating',
            'rating_time_control_standardized':'Rating + time control'}
    for method in labels:
        for r in rates[rates.method==method].itertuples():
            lines.append(f'| {labels[method]} | {r.scope} | {r.competitive_rate_pct:.3f} | '
                f'{r.worse_rate_pct:.3f} | {r.gap_pp:.3f} | {number(r.risk_ratio)} |')
    lines+=['','| Adjustment | Heavy/light ratio of RRs | 95% CI |', '|---|---:|---:|',
        f'| Full-sample unadjusted reference | {number(base.ratio_of_risk_ratios)} | '
        f'[{number(base.ratio_ci_low)}, {number(base.ratio_ci_high)}] |']
    for method in labels:
        r=pairs[(pairs.method==method)&(pairs.comparison=='heavy_versus_light')].iloc[0]
        lines.append(f'| {labels[method]} | {number(r.ratio_of_risk_ratios)} | '
                     f'[{number(r.ratio_ci_low)}, {number(r.ratio_ci_high)}] |')
    lines+=['','The full-sample reference and common-support unadjusted row separate any sample change from '
        'the subsequent rating adjustment. Rating-only and rating-plus-time-control rows use exactly the same '
        'retained choosers. The adjusted estimates give all activity groups the same pooled chooser distribution '
        'of rating bands, and then of rating-band/time-control cells. Within each cell, each chooser has equal weight '
        'in each state. No individual risk ratios are averaged.','',
        'The target is a finite-sample common covariate mix. Intervals for the common-support rows condition on '
        'the observed joint cell counts and target mix, retain the covariance between each chooser\'s state rates, '
        'and use the delta method on log ratios. `paired_adjustment_changes.csv` uses the covariance between '
        'adjusted and unadjusted estimates, rather than treating them as independent.','',
        '## Interpretation','',
        'A smaller heavy/light ratio of RRs after adjustment is consistent with rating composition accounting for '
        'part of the raw proportional contrast. A ratio that remains above one describes residual activity '
        'heterogeneity under this adjustment. Neither result identifies the causal effect of playing more games. '
        'A confidence interval containing one is not an equivalence test. Assess magnitudes and intervals.','',
        'The control is typical chooser rating and preferred observed time control. It does not hold each focal '
        'game\'s changing rating, clock, opponent strength, or exact position fixed. The 200-point rating bands '
        'also leave variation within bands. Zero-grant choosers remain in every supported cell. Missing ratings '
        'form an explicit category; missingness and exclusions are reported.','',
        'No adjusted specification from the paper is reestimated or replaced. All files in this return are '
        'aggregates; chooser identifiers and chooser-level features remain in the private cache.','']
    atomic_text(public/'SUMMARY.md','\n'.join(lines))
    tex=[r'% Requires booktabs. Descriptive common-support standardization; see METHODS.md.',
        r'\begin{table}[htbp]',r'\centering',r'\small',
        r'\caption{Activity contrasts after adjustment for chooser rating and preferred time control.}',
        r'\label{tab:activity-rating-adjustment}',r'\begin{tabular}{llrrrr}',r'\toprule',
        r'Adjustment & Activity & Competitive (\%) & Worse (\%) & Gap (pp) & Ratio \\',r'\midrule']
    short={'unadjusted_common_support':'None','rating_standardized':'Rating',
           'rating_time_control_standardized':'Rating + time control'}
    for method in short:
        for r in rates[rates.method==method].itertuples():
            tex.append(f'{short[method]} & {r.scope.title()} & {r.competitive_rate_pct:.3f} & '
                f'{r.worse_rate_pct:.3f} & {r.gap_pp:.3f} & {number(r.risk_ratio)} '+r'\\')
        if method!='rating_time_control_standardized':tex.append(r'\addlinespace')
    tex += [r'\bottomrule',r'\end{tabular}',r'\par\smallskip',r'\begin{minipage}{0.98\linewidth}\footnotesize',
        'All rows use the same '+f'{int(flow.loc["all","common_support_choosers"]):,}'.replace(',','{,}')+
        ' choosers on common support. Activity counts competitive and clearly-worse opportunities: '
        'light 2--6, medium 7--16, heavy 17+. Rating is mean pre-game chooser rating in the modal '
        'observed time control, defined jointly with speed. Adjustment standardizes 200-point rating bands '
        '(with open tails) and then rating-band/time-control cells to the same pooled chooser distribution. '
        'Each chooser receives equal weight within each cell and state; accounts with zero grants are retained. '
        'These are descriptive comparisons of chooser-level summaries; focal-game covariates are not held fixed.',
        r'\end{minipage}',r'\end{table}','']
    atomic_text(public/'ACTIVITY_RATING_ADJUSTMENT_TABLE.tex','\n'.join(tex))


def export(public,transfer,stamp,*,synthetic=False):
    files=sorted(p for p in public.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt')
    atomic_text(public/'SHA256SUMS.txt',''.join(sha256_file(p)+'  '+p.name+'\n' for p in files))
    files.append(public/'SHA256SUMS.txt')
    prefix='SYNTHETIC_ACTIVITY_RATING_TEST_' if synthetic else 'POOL_ACTIVITY_RATING_ADJUSTMENT_RESULTS_v100_'
    name=prefix+stamp
    transfer.mkdir(parents=True,exist_ok=True)
    output=transfer/(name+'.zip');temporary=output.with_suffix('.zip.tmp')
    if output.exists():raise RuntimeError('Refusing to replace an existing result archive')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,name+'/'+p.name)
    os.replace(temporary,output)
    atomic_text(output.with_suffix('.zip.sha256'),sha256_file(output)+'  '+output.name+'\n')
    return output
