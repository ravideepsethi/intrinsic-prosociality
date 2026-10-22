"""Rebuild presentation tables and scientific figures from the frozen public report.

Used before packaging; the Mac analysis does not need Matplotlib to run.
"""
from pathlib import Path
import csv, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import write_csv, require

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'first_pass_report'
OUT=ROOT/'ready_results'

def rows(name):
    with (SOURCE/name).open() as f:
        return list(csv.DictReader(f))

def phase(label):
    return None if label=='unclassified' else (20-int(label.replace('proxy_UTC','')))%24

def main():
    OUT.mkdir(exist_ok=True)
    models=json.loads((SOURCE/'MODEL_SUMMARY.json').read_text())
    labels={'flag_competitive':'Flag presence: competitive granting',
            'flag_clearly_worse':'Flag presence: clearly losing granting',
            'flag_ever_competitive':'Flag presence: ever competitive granter',
            'tv_competitive':'Positive TV time: competitive granting'}
    results=[]
    for m in models:
        results.append(dict(model=m['model'],label=labels[m['model']],estimate_pp=m['coefficient_pp'],
          chooser_cluster_se_pp=m['standard_error_pp'],ci_low_pp=m['ci_low_pp'],ci_high_pp=m['ci_high_pp'],
          p_value=m['p_value'],holm_p=m['holm_p_four_model_family'],observations=m['n'],choosers=m['clusters']))
    write_csv(OUT/'selection_and_tv_models.csv',results)
    coverage=[]
    for r in rows('01_flag_coverage_by_source_role.csv'):
        coverage.append(dict(source=r['profile_source'],role=r['acquisition_role'],accounts=int(r['accounts']),
          flag_setters=int(r['with_flag']),flag_coverage_pct=100*int(r['with_flag'])/int(r['accounts']),
          usable_country_territory=int(r['usable_iso_flags'])))
    write_csv(OUT/'flag_coverage.csv',coverage)
    md=['# Flag selection and TV visibility', '',
      'Completed first-pass results. Estimates are percentage points with chooser-clustered CR1 standard errors. These are unweighted associations in the acquired August profile sample.', '',
      '| Comparison | Estimate (pp) | SE (pp) | 95% CI (pp) | p | Opportunities / accounts | Choosers |',
      '|---|---:|---:|---|---:|---:|---:|']
    tex=[r'\begin{minipage}{\linewidth}',r'\small',r'\setlength{\tabcolsep}{4pt}',
         r'\begin{tabular}{@{}p{0.34\linewidth}rrrrr@{}}',r'\hline',r'Comparison & Estimate (pp) & SE (pp) & $p$ & $N$ & Choosers \\',r'\hline']
    for r in results:
        md.append(f"| {r['label']} | {r['estimate_pp']:+.3f} | {r['chooser_cluster_se_pp']:.3f} | [{r['ci_low_pp']:+.3f}, {r['ci_high_pp']:+.3f}] | {r['p_value']:.3g} | {r['observations']:,} | {r['choosers']:,} |")
        ptext=r'$<0.001$' if r['p_value']<.001 else f"{r['p_value']:.3f}"
        tex.append(f"{r['label']} & {r['estimate_pp']:+.3f} & {r['chooser_cluster_se_pp']:.3f} & {ptext} & {r['observations']:,} & {r['choosers']:,} "+r'\\')
    tex.extend([r'\hline',r'\end{tabular}',r'\par\smallskip\footnotesize',
      'Notes: Chooser-clustered CR1 standard errors. August returned active acquired sample; unweighted.',
      'Opportunity models include acquisition match cell, month, speed, rating tier, board/game-length/rating-gap bins,',
      'draw payoff, win premium, both RDs, clocks, clock missingness and log opportunity volume.',
      'The ever-granter account model includes acquisition match-cell effects only.',
      'TV time is accumulated featured-game exposure, not measured audience at the decision.',r'\end{minipage}'])
    md.extend(['', 'Opportunity models control for acquisition match cell, month, speed, rating tier, board bin, game-length bin, rating-gap bin, draw payoff, win premium, both RDs, clocks, clock-missingness indicators and log opportunity volume. The ever-granter account model includes acquisition match-cell effects only.', '',
      'TV time is accumulated featured-game exposure, measured after the game panel. It does not establish an audience for a particular decision. The adjusted TV result has p = 0.093 and its interval includes zero.', '',
      'Flag reporting is optional and acquisition was based on granting history. The results neither estimate a population country effect nor replicate the historical +0.907 pp specification exactly.', '',
      'The activity figures use UTC centers of the circular-mean activity bands. They show raw competitive-minus-clearly-losing rate differences, with 95% normal-approximation intervals from the reported chooser-cluster standard errors. They do not infer location or time zone.', '',
      'Classified accounts only are plotted. The full-window unclassified gradients are 3.955 pp for flag setters and 4.433 pp for known active non-setters. All relabeled CSVs retain the unclassified rows and all acquisition statuses.', '',
      'The full-panel pooled CSV sums the reported opportunity and grant counts across all acquisition statuses, including accounts not acquired. It contains point estimates only; no pooled standard errors are inferred from the aggregate tables.'])
    (OUT/'selection_and_tv_tables.md').write_text('\n'.join(md)+'\n')
    (OUT/'selection_and_tv_table.tex').write_text('\n'.join(tex)+'\n')
    all_rows=[]
    choices=[('full_window','06_activity_band_board_gradient.csv'),('stable_years','06_stable_band_board_gradient.csv'),('year1_timing_year2_outcomes','06_year1_proxy_year2_gradient.csv')]
    mapping={}
    pooled=[]
    for sample,name in choices:
        d=rows(name);key=next(iter(d[0]));relabel=[]
        for r in d:
            hour=phase(r[key])
            row=dict(sample=sample,utc_activity_phase_center_hour=hour,
              utc_activity_phase_label='unclassified' if hour is None else f'{hour:02}:00 UTC',original_proxy_label=r[key],
              **{k:v for k,v in r.items() if k!=key})
            relabel.append(row)
        relabel.sort(key=lambda r:(r['utc_activity_phase_center_hour'] is None,r['utc_activity_phase_center_hour'] or 0,r['flag_status']))
        write_csv(OUT/(sample+'_activity_phase_gradients.csv'),relabel)
        mapping[sample]=relabel
        for band in sorted(set(r[key] for r in d)):
            vals=[r for r in d if r[key]==band]
            nf=sum(float(r['competitive_opportunities']) for r in vals);kf=sum(float(r['competitive_grants']) for r in vals)
            nl=sum(float(r['losing_opportunities']) for r in vals);kl=sum(float(r['losing_grants']) for r in vals)
            pooled.append(dict(sample=sample,utc_activity_phase_center_hour=phase(band),
              competitive_opportunities=int(nf),competitive_grants=int(kf),clearly_losing_opportunities=int(nl),clearly_losing_grants=int(kl),
              competitive_rate_pct=100*kf/nf,clearly_losing_rate_pct=100*kl/nl,gradient_pp=100*(kf/nf-kl/nl)))
    write_csv(OUT/'all_chooser_activity_phase_point_estimates.csv',pooled)
    full=[r for r in pooled if r['sample']=='full_window']
    require(sum(r['competitive_opportunities'] for r in full)==15207423,'Full-panel activity denominator mismatch')
    require(sum(r['competitive_grants'] for r in full)==419463,'Full-panel activity grant total mismatch')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig,axs=plt.subplots(1,2,figsize=(10.8,4.9),sharey=True)
    for ax,sample,title in zip(axs,['full_window','year1_timing_year2_outcomes'],['Full-window activity and outcomes','Year-1 activity; year-2 outcomes']):
        for status,label,color,marker in [('flag_present','Flag set','#2364AA','o'),('active_no_flag','Known active profile; no flag','#BF6B25','s')]:
            data=[r for r in mapping[sample] if r['flag_status']==status and r['utc_activity_phase_center_hour'] is not None]
            x=[r['utc_activity_phase_center_hour'] for r in data];y=[float(r['gradient_pp']) for r in data];se=[float(r['chooser_cluster_se_pp']) for r in data]
            ax.errorbar(x,y,yerr=1.96*np.array(se),color=color,marker=marker,lw=1.5,ms=4,capsize=2,label=label)
        ax.set_title(title,fontsize=11,pad=12)
        ax.set_xticks([2,5,8,11,14,17,20,23],[f'{h:02}:00' for h in [2,5,8,11,14,17,20,23]],rotation=45)
        ax.set_xlabel('UTC activity-phase center')
        ax.grid(axis='y',color='#e5e5e5',lw=.6)
    axs[0].set_ylabel('Competitive minus clearly losing grant rate (pp)')
    handles,labels=axs[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,.12),ncol=2,frameon=False)
    fig.suptitle('The board-state gradient persists across activity schedules',fontsize=13,y=.98)
    fig.text(.5,.025,'Acquired accounts with observed active profiles; classified histories only. Bars: 95% chooser-cluster intervals.\nActivity phase measures timing of play, not country or time zone. Unclassified results are retained in the tables.',ha='center',fontsize=8,color='#444444')
    fig.subplots_adjust(left=.08,right=.985,top=.86,bottom=.31,wspace=.12)
    fig.savefig(OUT/'activity_phase_robustness.pdf')
    fig.savefig(OUT/'activity_phase_robustness.png',dpi=180)
    plt.close(fig)
    print('READY_RESULTS_OK',len(results),'models;',len(pooled),'full-panel phase cells')

if __name__=='__main__':main()
