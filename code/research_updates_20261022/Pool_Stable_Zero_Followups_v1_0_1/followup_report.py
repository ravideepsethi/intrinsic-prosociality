"""Figures and an evidence-first report from the returned aggregate estimates."""
from pathlib import Path
import csv
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from followup_specs import SAMPLES, BANDWIDTHS, MAIN_H, PRIMARY_SAMPLE, PRIMARY

LABELS = {'rd75': 'Both players’ RD ≤ 75', 'rd75_k11_12': 'Both RD ≤ 75; K from 11 to 12'}
AXES = ('normalized', 'payoff', 'gap')
AXIS_LABELS = {'normalized': 'Normalized draw payoff D/K', 'payoff': 'Draw payoff (rating points)', 'gap': 'Opponent − chooser rating'}
SCALE = {'normalized': .01, 'payoff': 1., 'gap': 10.}
UNITS = {'normalized': 'pp per 0.01 D/K', 'payoff': 'pp per rating point', 'gap': 'pp per 10 rating points'}
STATE_LABELS = {'roughly_equal': 'Roughly equal', 'better': 'Opponent better', 'clearly_better': 'Opponent clearly better'}
COLORS = ('#176EAD', '#CE7525', '#268075')


def number(x, decimals=4):
    if x is None or not math.isfinite(float(x)): return '—'
    return f'{float(x):.{decimals}g}'


def save(fig, directory, name, production=True):
    if not production:
        fig.text(.99, .012, 'SYNTHETIC VALIDATION ONLY', ha='right', fontsize=9,
                 fontweight='bold', color='#A32020')
    for extension in ('png', 'pdf'): fig.savefig(directory/(name+'.'+extension), dpi=180, facecolor='white')
    plt.close(fig)


def forest(ax, rows, xvalues, color, marker, label, scale=1.):
    rr = [r for r in rows if r['status'] == 'estimated']
    if not rr: return
    x = np.array([xvalues(r) for r in rr]); y = np.array([r['estimate_pp']*scale for r in rr])
    lo = np.array([r['ci95_low_pp']*scale for r in rr]); hi = np.array([r['ci95_high_pp']*scale for r in rr])
    ax.errorbar(x, y, yerr=np.vstack([y-lo, hi-y]), color=color, fmt=marker,
                markersize=5, capsize=3, linewidth=1.3, label=label)


def build_report(report, rows, tests, placebo, profiles, production=True):
    figures = Path(report)/'figures'; figures.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10.5, 'pdf.fonttype': 42,
                         'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': '#9AA6B2'})
    primary = [r for r in rows if r['primary_followup']]
    subtitle = 'Chooser × board-state FE and controls · pointwise 95% intervals, clustered by chooser'
    # Polynomial/window robustness: point estimates, never a shape constraint.
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.2))
    fig.subplots_adjust(left=.08, right=.98, bottom=.18, top=.79, hspace=.6, wspace=.35)
    for i, sample in enumerate(SAMPLES):
        for j, axis in enumerate(AXES):
            ax = axes[i, j]; hs = list(BANDWIDTHS[axis])
            for deg, color, marker, offset in [(1, '#83919E', 'o', -.12), (2, COLORS[0], 's', 0)]:
                rr = [r for r in rows if r['sample'] == sample and r['axis'] == axis and r['center'] == 0
                      and r['scope'] == 'pooled' and not r['omit_ties'] and r['degree'] == deg and r['term'] == 'right_minus_left_slope']
                forest(ax, rr, lambda r: hs.index(r['h'])+offset, color, marker, f'Degree {deg}', SCALE[axis])
            rr = [r for r in rows if r['sample'] == sample and r['axis'] == axis and r['omit_ties'] and r['term'] == 'right_minus_left_slope']
            forest(ax, rr, lambda r: hs.index(r['h'])+.12, COLORS[1], '^', 'Quadratic, omit rating ties', SCALE[axis])
            ax.axhline(0, color='#87929C', linewidth=.8); ax.grid(axis='y', alpha=.18)
            ax.set_xticks(range(3), [f'±{h:g}' for h in hs]); ax.set_xlabel('Window around zero')
            ax.set_ylabel('Right − left slope\n('+UNITS[axis]+')')
            ax.set_title(AXIS_LABELS[axis]+'\n'+LABELS[sample], fontsize=10.5)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(.07, .91), ncol=3, frameon=False)
    fig.suptitle('Does the slope change survive allowance for curvature?', x=.08, ha='left', y=.985, fontsize=19, fontweight='bold')
    fig.text(.08, .932, subtitle, fontsize=10.5)
    fig.text(.08, .055, 'Negative values mean the rise is steeper below zero. Missing points fail identification or support checks.\nPolynomial approximation and window choice remain assumptions; these are conditional shape tests, not a causal kink design.', fontsize=9, color='#536475')
    save(fig, figures, '01_zero_slope_robustness', production)
    # Unrestricted quadratic profiles for the primary sample, with separate sides.
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.2))
    fig.subplots_adjust(left=.08, right=.98, bottom=.20, top=.80, hspace=.50, wspace=.30)
    for i, scope in enumerate(('pooled', 'by_state')):
        for j, axis in enumerate(AXES):
            ax = axes[i, j]
            contexts = ['pooled_competitive'] if scope == 'pooled' else list(STATE_LABELS)
            for g, context in enumerate(contexts):
                rr = [r for r in profiles if r['sample'] == PRIMARY_SAMPLE and r['axis'] == axis
                      and r['scope'] == scope and r['context'] == context]
                for side in ('left', 'right', 'atom'):
                    use = [r for r in rr if r['side'] == side and r['status'] == 'estimated']
                    if not use: continue
                    x = np.array([r['x'] for r in use]); y = np.array([r['estimate_pp'] for r in use])
                    lo = np.array([r['ci95_low_pp'] for r in use]); hi = np.array([r['ci95_high_pp'] for r in use])
                    label = STATE_LABELS.get(context, 'Pooled competitive') if side == 'left' else None
                    if side == 'atom':
                        ax.errorbar(x, y, yerr=np.vstack([y-lo, hi-y]), fmt='D', color=COLORS[g], markersize=4, capsize=2)
                    else:
                        ax.plot(x, y, color=COLORS[g], label=label); ax.fill_between(x, lo, hi, color=COLORS[g], alpha=.09)
            ax.axhline(0, color='#AFB7BD', linewidth=.8); ax.axvline(0, color='#AFB7BD', linewidth=.8)
            ax.set_xlabel(AXIS_LABELS[axis]); ax.set_ylabel('Difference in kindness (pp)')
            ax.set_title('Pooled local quadratic' if i == 0 else 'Separate board-state polynomials')
            ax.grid(axis='y', alpha=.15)
    handles, labels = axes[1, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(.07, .90), ncol=3, frameon=False)
    fig.suptitle('Local profiles allowing curvature, a jump, and an exact-tie effect', x=.08, ha='left', y=.985, fontsize=18, fontweight='bold')
    fig.text(.08, .935, LABELS[PRIMARY_SAMPLE]+' · '+subtitle, fontsize=10)
    fig.text(.08, .07, 'Each curve is normalized to its extrapolated left limit at zero. A diamond denotes the estimated exact-cutoff mass point.\nLines on opposite sides are fitted separately; continuity is not imposed. These are model-based local profiles, not raw rates.', fontsize=9, color='#536475')
    save(fig, figures, '02_local_quadratic_profiles', production)
    # Board-state derivatives over all declared normalized bandwidths.
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 5.8))
    fig.subplots_adjust(left=.09, right=.98, bottom=.23, top=.72, wspace=.3)
    for ax, sample in zip(axes, SAMPLES):
        for j, context in enumerate(STATE_LABELS):
            rr = [r for r in rows if r['sample'] == sample and r['axis'] == 'normalized' and r['scope'] == 'by_state'
                  and r['context'] == context and r['term'] == 'right_minus_left_slope']
            forest(ax, rr, lambda r: list(BANDWIDTHS['normalized']).index(r['h'])+(j-1)*.14,
                   COLORS[j], ('o', 's', '^')[j], STATE_LABELS[context], .01)
        ax.axhline(0, color='#87929C', linewidth=.8); ax.grid(axis='y', alpha=.18)
        ax.set_xticks(range(3), ['±0.025', '±0.05', '±0.10']); ax.set_xlabel('Normalized-payoff window')
        ax.set_ylabel('Right − left slope (pp per 0.01 D/K)'); ax.set_title(LABELS[sample])
    fig.suptitle('Does the local asymmetry differ across board states?', x=.09, ha='left', y=.97, fontsize=17, fontweight='bold')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(.08, .88), ncol=3, frameon=False, fontsize=10)
    fig.text(.09, .08, 'Local quadratic fits. All polynomial, jump, and mass-point terms interact with board state; nuisance slopes remain common.\nIntervals cluster by chooser across states. Joint and pairwise tests use the full cross-state covariance.', fontsize=9, color='#536475')
    save(fig, figures, '03_board_state_slope_changes', production)
    # Placebo cutoff-specific slopes. Joint comparisons are in the companion table.
    fig, ax = plt.subplots(figsize=(9.4, 5.7)); fig.subplots_adjust(left=.12, right=.97, bottom=.25, top=.74)
    for j, sample in enumerate(SAMPLES):
        rr = [r for r in rows if r['sample'] == sample and r['axis'] == 'normalized' and r['h'] == .05
              and r['degree'] == 2 and r['scope'] == 'pooled' and not r['omit_ties'] and r['term'] == 'right_minus_left_slope']
        forest(ax, rr, lambda r: r['center']+(j-.5)*.004, COLORS[j], ('s', 'o')[j], LABELS[sample], .01)
    ax.axhline(0, color='#87929C', linewidth=.8); ax.axvline(0, color='#B5BEC4', linewidth=.8)
    ax.set_xticks([-.1, 0, .1]); ax.set_xlabel('Cutoff in normalized draw payoff D/K')
    ax.set_ylabel('Right − left slope (pp per 0.01 D/K)'); ax.grid(axis='y', alpha=.18)
    ax.legend(frameon=False, loc='upper left', bbox_to_anchor=(-.01, 1.25), ncol=2, fontsize=10)
    fig.suptitle('Zero and two declared placebo cutoffs', x=.12, ha='left', y=.97, fontsize=18, fontweight='bold')
    fig.text(.12, .08, 'Each fit uses a ±0.05 window and separate quadratic polynomials on either side.\nZero-minus-placebo contrasts account for choosers shared across windows. The populations can still differ.\nCompare the joint contrasts, not whether individual confidence intervals cross zero.', fontsize=9, color='#536475')
    save(fig, figures, '04_placebo_cutoffs', production)
    # Displayed-rating support of the declared primary window.
    support_path = Path(report)/'displayed_gap_support.csv'
    if support_path.is_file():
        support = list(csv.DictReader(support_path.open()))
        fig, axes = plt.subplots(1, 2, figsize=(11.8, 5.5)); fig.subplots_adjust(left=.09, right=.98, top=.78, bottom=.20, wspace=.23)
        for ax, sample in zip(axes, SAMPLES):
            counts = {}
            for r in support:
                if r['sample'] == sample and r['spec_id'] == PRIMARY.key:
                    k = int(r['displayed_gap']); counts[k] = counts.get(k, 0)+int(r['n'])
            if counts:
                x = sorted(counts); ax.bar(x, [counts[k] for k in x], color=COLORS[0], width=.9)
            ax.set_yscale('log'); ax.set_xlabel('Displayed opponent − chooser rating'); ax.set_ylabel('Retained observations (log scale)')
            ax.set_title(LABELS[sample]); ax.grid(axis='y', alpha=.15)
        fig.suptitle('Discrete rating support inside the primary local window', x=.09, ha='left', y=.96, fontsize=17, fontweight='bold')
        fig.text(.09, .065, 'Window: |D/K| ≤ 0.05. Counts are after chooser × board-state singleton removal.\nExact rating ties are retained here and excluded in the declared tie sensitivity.', fontsize=9, color='#536475')
        save(fig, figures, '05_discrete_rating_support', production)
    lines = ['# Stable-rating zero follow-ups', '', 'Actual data results.' if production else '**SYNTHETIC VALIDATION ONLY — not research results.**', '',
             'Exploratory follow-up: bandwidths, polynomial degrees, sample restrictions and placebo cutoffs were fixed in code before this run, after inspecting the earlier curves.', '',
             '## Primary follow-up', '', 'Both pregame RD ≤ 75; 11 ≤ K ≤ 12; |D/K| ≤ 0.05; separate quadratic polynomials; exact ties retained with a separate indicator.', '',
             '| Term | Estimate | Cluster SE | Raw p | Holm, primary five | Status |', '|---|---:|---:|---:|---:|---|']
    for r in primary: lines.append('| '+r['term']+' | '+ ' | '.join(number(r.get(k)) for k in ['estimate_pp', 'cluster_se_pp', 'p_two_sided', 'p_holm_primary_5'])+' | '+r['status']+' |')
    if primary: lines += ['', f'Local N={primary[0]["n"]:,}; chooser clusters={primary[0]["chooser_clusters"]:,}; absorbed chooser-state units={primary[0]["absorbed_units"]:,}.']
    lines += ['', 'Slopes above are percentage points per full unit D/K. Divide by 100 for a 0.01 change. Jump and atom terms are percentage points. The figures use their stated rescaled units.', '',
              '## Normalized-payoff bandwidth and tie sensitivity', '',
              '| Sample | Degree | Bandwidth | Omit rating ties | Right−left slope | SE | Holm pooled-zero kink family |', '|---|---:|---:|---|---:|---:|---:|']
    for r in rows:
        if r['axis'] == 'normalized' and r['scope'] == 'pooled' and r['center'] == 0 and r['term'] == 'right_minus_left_slope':
            lines.append(f'| {r["sample"]} | {r["degree"]} | {r["h"]} | {r["omit_ties"]} | {number(r["estimate_pp"])} | {number(r["cluster_se_pp"])} | {number(r.get("p_holm_pooled_zero_kinks"))} |')
    lines += ['', '## State-specific slope changes at the primary window', '',
              '| Sample | State | Right−left slope | SE | Holm state-kink family |', '|---|---|---:|---:|---:|']
    for r in rows:
        if r['axis'] == 'normalized' and r['scope'] == 'by_state' and r['h'] == .05 and r['term'] == 'right_minus_left_slope':
            lines.append(f'| {r["sample"]} | {r["context"]} | {number(r["estimate_pp"])} | {number(r["cluster_se_pp"])} | {number(r.get("p_holm_state_kinks"))} |')
    lines += ['', 'The table of joint tests is `board_state_tests.csv` / `.parquet`. It tests equality across states directly using cross-state covariance; significance in one state and not another is not itself evidence of a difference.', '',
              '## Zero versus placebos', '', '| Sample | Contrast/test | Estimate | SE | Adjusted p |', '|---|---|---:|---:|---:|']
    for r in placebo: lines.append(f'| {r["sample"]} | {r["test"]} | {number(r.get("estimate_pp"))} | {number(r.get("cluster_se_pp"))} | {number(r.get("p_holm_placebo_8"))} |')
    lines += ['', '## Interpretation and limits', '',
              '- Inspect the primary quadratic estimate alongside the linear benchmark, bandwidths, tie exclusion, and support; do not pick the smallest p-value. Rows marked insufficient support are diagnostic values, not supported scientific estimates; they receive no p-value and are omitted from figures.',
              '- A finite-bandwidth polynomial coefficient is an approximation to a local derivative. Clustered standard errors do not remove approximation bias. No automatic robust bias correction or causal regression-kink claim is made.',
              '- A nonzero derivative change at zero can be compatible with a rating-loss reference, but zero also marks equal ratings. These data do not separately identify rating reference dependence and a norm concerning equal-strength opponents.',
              '- Local profiles normalize each curve to its extrapolated left limit at the cutoff. They are conditional changes, not absolute grant rates.',
              '- The 90 prior local-linear coefficient/SE checks and current-sample count checks must pass before the success marker is written.',
              '- Unsupported tests remain in their declared multiplicity families as p=1. See METHODS.md for the distinct families and support thresholds.', '',
              'All table data are available in both CSV and compressed Parquet. Numerical moment matrices, coefficient vectors, and covariance matrices support independent review. The report contains no chooser or game identifiers.', '']
    (Path(report)/'RESULTS.md').write_text('\n'.join(lines))
