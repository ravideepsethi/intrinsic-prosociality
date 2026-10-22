"""Aggregate contrasts and unsmoothed figures for the split-zero refit."""
import csv
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from fe_engine import axis_definition
from pooled_engine import holm
from pooled_utils import write_csv

SPEC='chooser_state_controls_k20'

def near_zero_contrasts(rows,arrays,counts):
    result=[];labels=axis_definition('payoff')[1];J=len(labels)
    indices=[next(r['bin'] for r in labels if r['mid'] is not None and abs(r['mid']-x)<1e-9) for x in (-.2,0.,.2)]
    for spec in (SPEC,'raw'):
        rr={r['bin']:r for r in rows if r['axis']=='payoff' and r['specification']==spec}
        beta=arrays['payoff__'+spec+'__estimates'];V=arrays['payoff__'+spec+'__covariance']
        for name,first,second in [('small_gain_minus_small_loss',2,0),('exact_zero_minus_small_loss',1,0),('small_gain_minus_exact_zero',2,1)]:
            a,b=indices[first],indices[second];w=np.zeros(J);w[a]=1;w[b]=-1
            supported=rr[a]['display_supported'] and rr[b]['display_supported']
            row=dict(specification=spec,contrast=name,status='estimated' if supported else 'insufficient_support',
              estimate_pp=None,cluster_se_pp=None,ci95_low_pp=None,ci95_high_pp=None,p_two_sided=None,
              first_n=rr[a]['n'],second_n=rr[b]['n'],chooser_clusters=counts['chooser_clusters'],exploratory=True)
            if supported:
                estimate=100*float(w@beta);variance=float(w@V@w)
                if variance < -1e-10:raise RuntimeError('Negative contrast variance')
                se=100*np.sqrt(max(0,variance));df=counts['chooser_clusters']-1
                crit=student_t.ppf(.975,df)
                p=2*student_t.sf(abs(estimate/se),df) if se>0 else float(estimate==0)
                row.update(estimate_pp=estimate,cluster_se_pp=float(se),ci95_low_pp=float(estimate-crit*se),
                           ci95_high_pp=float(estimate+crit*se),p_two_sided=float(p))
            result.append(row)
    holm(result,lambda r:r['specification']==SPEC,'p_two_sided','p_holm_three_adjusted_contrasts')
    return result

def plot(report,rows,counts,wide=False,clean=False):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':16,'axes.spines.top':False,
      'axes.spines.right':False,'axes.edgecolor':'#ACB4BC','pdf.fonttype':42,'svg.fonttype':'none'})
    fig,axes=plt.subplots(1,2,figsize=(16,9),sharey=True)
    fig.subplots_adjust(left=.105,right=.975,top=.84 if clean else .76,bottom=.23 if clean else .29,wspace=.16)
    ymin=[];ymax=[];used=[]
    for ax,axis,title,xlabel in zip(axes,('gap','payoff'),('Relative strength','Draw payoff'),
        ('Opponent rating − chooser rating','Rating change from granting a draw')):
        rr=sorted([r for r in rows if r['axis']==axis and r['specification']==SPEC and r['mid'] is not None
          and r['display_supported'] and (wide or abs(r['mid'])<=(200.001 if axis=='gap' else 2.201))],key=lambda r:r['mid'])
        if not rr:raise RuntimeError('No supported bins for '+axis)
        used.extend(rr)
        for group in ([rr] if axis=='gap' else [[r for r in rr if r['mid']<0],[r for r in rr if r['mid']>0]]):
            if not group:continue
            chunks=np.split(np.arange(len(group)),np.where(np.diff([r['bin'] for r in group])>1)[0]+1)
            for chunk in chunks:
                x=np.array([group[j]['mid'] for j in chunk]);y=np.array([group[j]['estimate_pp'] for j in chunk])
                lo=np.array([group[j]['ci95_low_pp'] for j in chunk]);hi=np.array([group[j]['ci95_high_pp'] for j in chunk])
                ax.fill_between(x,lo,hi,color='#006DA4',alpha=.12,lw=0)
                ax.plot(x,y,color='#006DA4',lw=2.5,marker='o',ms=6,zorder=3)
        if axis=='payoff':
            atom=next((r for r in rr if r['reference']),None)
            if atom:ax.plot(0,0,'D',color='#006DA4',mfc='white',mew=2,ms=8,zorder=4)
        ymin.extend(r['ci95_low_pp'] for r in rr);ymax.extend(r['ci95_high_pp'] for r in rr)
        ax.axhline(0,color='#A3ABB3',lw=.9);ax.axvline(0,color='#A3ABB3',lw=.9)
        ax.grid(axis='y',color='#E7EBEF',lw=.8)
        ax.set_title(title,loc='left',fontsize=22,weight='bold',pad=15)
        ax.set_xlabel(xlabel,fontsize=17,labelpad=12)
        if axis=='gap':
            ax.set_xlim((-625,625) if wide else (-225,225));ax.set_xticks([-600,-300,0,300,600] if wide else [-200,-100,0,100,200])
        else:
            ax.set_xlim((-6.1,6.1) if wide else (-2.4,2.4));ax.set_xticks([-6,-3,0,3,6] if wide else [-2,-1,0,1,2])
        if not clean:
            coverage=sum(r['n'] for r in rr)/counts['estimation_rows']
            ax.text(.015,.965,f'Shown bins cover {coverage:.1%} of the sample',transform=ax.transAxes,va='top',fontsize=11,color='#536475')
    lo=min(ymin);hi=max(ymax);pad=max(.05,.14*(hi-lo));axes[0].set_ylim(lo-pad,hi+pad)
    axes[0].set_ylabel('Difference in kindness\n(percentage points)',fontsize=18,labelpad=12)
    axes[0].yaxis.set_major_locator(MaxNLocator(nbins=6))
    if not clean:
        fig.text(.105,.94,'Kindness, relative strength, and draw payoff',fontsize=29,weight='bold',color='#172A3A')
        fig.text(.105,.885,'All competitive positions. Chooser × board-state fixed effects and controls',fontsize=17,color='#536475')
        foot=['Controls: ply, both players’ RD and volatility, month, speed, fine board evaluation, and rating sensitivity K.',
          'Reference categories: gap [−25, 25); draw payoff exactly zero (hollow diamond).',
          'Payoff bins: [−0.4, 0), {0}, (0, 0.4). Lines join bins on each side separately; no smoothing.',
          f'N = {counts["estimation_rows"]:,}. Shading: pointwise 95% confidence intervals, clustered by chooser.']
        for i,line in enumerate(foot):fig.text(.105,.165-i*.031,line,fontsize=12,color='#536475')
    else:
        fig.text(.105,.12,'Chooser × board-state fixed effects and controls. Pointwise 95% intervals clustered by chooser.',fontsize=12,color='#536475')
        fig.text(.105,.08,'Reference: near-zero rating gap; exact-zero draw payoff (diamond). Payoff lines stop on either side of zero.',fontsize=12,color='#536475')
    name='split_zero_'+('expanded' if wide else 'central')+('_plot_only' if clean else '')
    for ext in ('png','pdf'):fig.savefig(report/'figures'/(name+'.'+ext),dpi=200,facecolor='white')
    plt.close(fig)
    return [dict(r,figure=name) for r in used]

def build_report(report,rows,arrays,counts):
    (report/'figures').mkdir(exist_ok=True)
    contrasts=near_zero_contrasts(rows,arrays,counts)
    write_csv(report/'near_zero_contrasts.csv',contrasts)
    central=[r for r in rows if r['axis']=='payoff' and r['mid'] is not None and abs(r['mid'])<.3]
    write_csv(report/'near_zero_bins.csv',central)
    plotted=[]
    for wide in (False,True):
        for clean in (False,True):plotted+=plot(report,rows,counts,wide,clean)
    write_csv(report/'plotted_data.csv',plotted)
    text=['# Split-zero curve refit','',f'Estimation rows: {counts["estimation_rows"]:,}; chooser clusters: {counts["chooser_clusters"]:,}.',
      '', 'This refit separates small losses, exact zero, and small gains. Both axes retain the same observations, chooser × board-state fixed effects, and controls.',
      '', '**Normalization changed only for the payoff curve:** zero now means the exact-zero category, not the old pooled [−0.4,+0.4) category. Compare shapes and contrasts; do not interpret vertical shifts from the older plot as new effects.',
      '', 'Exact zero uses equality to the stored unrounded payoff, with no epsilon. ZERO_AUDIT.json reports tiny nonzero payoffs and disagreements with displayed-rating ties.',
      '', '## Central adjusted bins','', '| Category | Dot x | N | Difference vs exact zero (pp) | SE (pp) |', '|---|---:|---:|---:|---:|']
    for r in central:
        if r['specification']!=SPEC:continue
        name='Exact zero (normalization)' if r['reference'] else 'Small loss' if r['mid']<0 else 'Small gain'
        fmt=lambda v:'unidentified' if v is None else f'{v:.5f}'
        text.append(f'| {name} | {r["mid"]:.1f} | {r["n"]:,} | {fmt(r["estimate_pp"])} | {fmt(r["cluster_se_pp"])} |')
    text+=['','near_zero_contrasts.csv uses the full covariance matrix and Holm adjustment across the three adjusted comparisons. These are finite-bin contrasts, not tests of a derivative discontinuity at zero.',
      '', 'Figures show only supported bins; see curves.csv for counts, estimability, and support. Overflow bins remain in estimation but have no finite plotting position. No monotonicity or smooth shape is imposed.']
    (report/'SUMMARY.md').write_text('\n'.join(text)+'\n')
