"""Aggregate reports and a paper-ready exclusion robustness figure."""
from common import write_csv

STAGE_LABELS={'00_no_exclusion':'Full main sample',
 '01_elite_title_streamer':'Exclude elite / titled / known streamers',
 '02_add_profile_links':'Also exclude profile channel links',
 '03_add_recorded_tv':'Also exclude recorded TV exposure'}

def write_report(out,payload):
    rows=[r for r in payload['summary'] if r['threshold']==2400 and
          r['metadata_scope']=='all_available_metadata' and
          r['group'] in ('all_opportunities_in_scope','not_flagged_by_available_sources')]
    def fmt(x): return 'NA' if x is None else f'{x:.3f}'
    lines=['# Expanded audience exclusions','',
      'This is an exclusion robustness analysis using observed account characteristics. '
      'It does not measure spectators at the decision or identify a causal audience effect.','',
      f"Main sample: {payload['sample_qa']['opportunities']:,} opportunities; "
      f"{payload['sample_qa']['kind_draws']:,} kind draws.",'',
      '## Primary: either player; rating threshold 2400','',
      '| Exclusion | Remaining opportunities | Accounts | Competitive rate (%) | Clearly-worse rate (%) | Raw gap (pp) | Chooser FE gap (SE), pp |',
      '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {STAGE_LABELS[r['stage']]} | {r['opportunities']:,} | {r['chooser_accounts']:,} | "
          f"{fmt(r['competitive_rate_pct'])} | {fmt(r['clearly_worse_rate_pct'])} | "
          f"{fmt(r['raw_gradient_pp'])} | {fmt(r['chooser_fe_gradient_pp'])} ({fmt(r['chooser_fe_se_pp'])}) |")
    lines += ['','## Specifications and interpretation','',
      '- Exclusions apply if either player is flagged. Ratings are measured at the game; cached titles, links and TV time are post-panel account attributes.',
      '- The full sample includes all frozen opportunities. Subsequent rows separately classify any invalid ratings or known bots; see group_summary.csv.',
      '- The remainder has no positive flag in available sources. Missing profiles, missing TV fields, and actual audiences remain unknown.',
      '- Raw rates use all observations in each stated category. Chooser FE compares competitive with clearly-worse decisions by the same chooser within that subset; the middle evaluation region does not enter the contrast.',
      '- FE controls: chooser intercepts only. No added month, speed, rating, clocks, ply, RD, volatility, payoff or Patron controls. These are desert-gradient robustness estimates, not the separate payoff-curve specification.',
      '- Standard errors cluster by chooser. Accounts with observations in only one of the two desert categories do not identify the FE slope. Accounts that never grant remain eligible.',
      '- Excluding records can change the set of identifying choosers. The FE row counts and cluster counts report this directly.',
      '- Both-profile and both-profile-plus-numeric-TV restrictions are coverage diagnostics. The underlying profile acquisition selected partly on granting, so these are not representative subsamples.',
      '- A recorded zero is not proof of never appearing on TV; a missing TV measurement is kept separate from zero.',
      '- Positive TV time is accumulated credited playing time associated with TV selection. It does not establish a viewer, a viewer count, or exposure of the focal panel game.',
      '- Channel links are candidates, not verified channel ownership. The original 260-account directory is deliberately reused unchanged and remains incomplete.',
      '- Similar point estimates or a failure to reject a difference do not establish equivalence. No causal or equivalence conclusion is automated.',
      '- Account counts across exclusion rows and overlap cells are not additive. Opportunity counts in disjoint overlap cells are additive.','',
      '## Outputs','',
      '- `audience_exclusion_robustness.pdf` and `.png`: raw versus chooser-FE desert gradients with chooser-clustered 95% intervals.',
      '- `group_summary.csv`: all rates, ratios, samples, account counts and FE estimates.',
      '- `estimates.csv`: clustered SEs, 95% intervals, effective observations and chooser clusters for each metric.',
      '- `between_flag_groups.csv`: positive-flag minus remaining-group contrasts, accounting for shared choosers.',
      '- `exclusion_metadata_partition.csv`: unknown versus observed metadata within each exclusion group.',
      '- `metadata_coverage_by_opportunity.csv` and `metadata_coverage_by_chooser.csv`: selection/coverage diagnostics by current choice and ever-granting status.',
      '- `flag_overlap.csv`: disjoint combinations of the five flags at the opportunity level.',
      '- `individual_flag_coverage.csv`: each flag separately, for chooser, opponent and either player.',
      '- `recorded_tv_duration.csv`: missing, recorded zero, and positive TV-duration categories.',
      '- `RESULTS.json`: all aggregate outputs, input hashes, specification and provenance.','',
      'Private account IDs and profile/link evidence remain on the external drive.']
    (out/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    write_csv(out/'primary_exclusion_summary.csv',rows)

def plot(out,payload):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    rows=[r for r in payload['summary'] if r['threshold']==2400 and
          r['metadata_scope']=='all_available_metadata' and
          r['group'] in ('all_opportunities_in_scope','not_flagged_by_available_sources')]
    if not rows: return
    fig,axes=plt.subplots(1,2,figsize=(12.8,5.1),sharey=True,sharex=True)
    for ax,metric,title,color in zip(axes,('raw_gradient','chooser_fe_gradient'),
        ('Raw competitive–clearly-worse gap','Within-chooser gap'),('#597b95','#1b526b')):
        for j,r in enumerate(rows):
            e=next(x for x in payload['estimates'] if x['threshold']==2400 and
              x['metadata_scope']=='all_available_metadata' and x['stage']==r['stage'] and
              x['group']==r['group'] and x['metric']==metric)
            if e['estimate'] is None or e['ci95_low'] is None: continue
            ax.errorbar(e['estimate'],j,xerr=[[max(0,e['estimate']-e['ci95_low'])],
              [max(0,e['ci95_high']-e['estimate'])]],fmt='o',capsize=3,color=color,markersize=6)
        ax.set_title(title,fontsize=11,pad=12)
        ax.set_xlabel('Kindness difference (percentage points)',fontsize=10)
        ax.grid(axis='x',color='#e8e8e8')
        ax.set_axisbelow(True)
        ax.spines[['top','right','left']].set_visible(False)
        ax.tick_params(axis='y',length=0)
    axes[0].set_yticks(np.arange(len(rows)),[STAGE_LABELS[r['stage']]+f"\nN (all states) = {r['opportunities']:,}" for r in rows],fontsize=9)
    axes[0].invert_yaxis()
    for ax in axes: ax.margins(y=.20)
    fig.suptitle('Desert gradient after broader audience-proxy exclusions',fontsize=14,y=.97)
    fig.text(.03,.035,'Either player flagged; elite threshold 2400. Bars: chooser-clustered 95% CIs.\n'
       'Remaining games are not certified unwatched. Profiles are selected and observed after the panel.',fontsize=9,color='#444444')
    fig.subplots_adjust(left=.31,right=.98,top=.84,bottom=.20,wspace=.24)
    fig.savefig(out/'audience_exclusion_robustness.pdf')
    fig.savefig(out/'audience_exclusion_robustness.png',dpi=200)
    plt.close(fig)
