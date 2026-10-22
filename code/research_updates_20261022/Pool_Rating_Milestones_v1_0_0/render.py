"""Aggregate-only figures; every plotted value is in the result CSV files."""
from pathlib import Path
import csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    with open(path,newline='') as f:return list(csv.DictReader(f))


def render(report):
    report=Path(report);out=report/'figures';out.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'pdf.fonttype':42,'savefig.dpi':200})
    rows=read(report/'all_model_attempts.csv')
    selected=[('hundreds_primary','Hundreds: primary'),('hundreds_established','Both RD ≤ 100'),
              ('hundreds_established_no1500','Both RD ≤ 100; omit 1500'),
              ('hundreds_past_ply10','Past ply 10'),('hundreds_rounding_safe','Rounding-safe subset'),
              ('fifties_comparison','Ratings ending in 50'),('offset37_placebo','Offset +37'),
              ('offset73_placebo','Offset +73')]
    fig,axes=plt.subplots(1,2,figsize=(11,5.3),sharey=True)
    for ax,term,title,color in zip(axes,['loss_crossing','gain_crossing'],
                                 ['Protecting a milestone','Reaching a milestone'],['#126782','#b05b32']):
        for i,(key,label) in enumerate(selected):
            r=next(x for x in rows if x['specification']==key and x['term']==term)
            if r['status']=='estimated':
                y=len(selected)-i-1;v=float(r['estimate_pp'])
                ax.errorbar(v,y,xerr=[[v-float(r['ci95_low_pp'])],[float(r['ci95_high_pp'])-v]],
                            fmt='o',color=color,capsize=3,ms=5)
            else:ax.text(.02,len(selected)-i-1,'Insufficient support',transform=ax.get_yaxis_transform(),fontsize=8,color='#777')
        ax.axvline(0,color='#aaa',lw=.8);ax.set_title(title);ax.set_xlabel('Conditional difference in kindness (percentage points)')
        ax.set_yticks(range(len(selected)));ax.set_yticklabels([x[1] for x in reversed(selected)])
        ax.grid(axis='x',alpha=.15)
    fig.suptitle('Rating milestones and kindness',fontsize=15,y=.99)
    fig.text(.5,.02,'95% chooser-clustered intervals • Competitive positions • Exploratory conditional associations',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.055,1,.96))
    for ext in ('pdf','png'):fig.savefig(out/f'milestone_crossings.{ext}',bbox_inches='tight')
    plt.close(fig)
    raw=read(report/'raw_pooled_distance.csv')
    profile=read(report/'adjusted_distance_profile.csv')
    fig,axes=plt.subplots(1,2,figsize=(10.5,4.3))
    axes[0].plot([float(r['distance']) for r in raw],[float(r['kind_rate_percent']) for r in raw],color='#126782',marker='.',lw=1)
    axes[0].set_ylabel('Kind draws (%)');axes[0].set_title('Raw proximity profile')
    for j,r in enumerate(profile):
        if r['status'] not in ('estimated','reference'):continue
        v=float(r['estimate_pp']);x=-22.5+5*j
        axes[1].errorbar(x,v,yerr=[[v-float(r['ci95_low_pp'])],[float(r['ci95_high_pp'])-v]],fmt='o',color='#126782',capsize=3)
    axes[1].set_ylabel('Difference from +10 to +14 (pp)');axes[1].set_title('Within-chooser adjusted profile')
    axes[1].axhline(0,lw=.7,color='#aaa')
    for ax in axes:
        ax.axvline(0,lw=.8,ls='--',color='#888');ax.set_xlabel('Pre-game rating minus nearest hundred');ax.grid(axis='y',alpha=.15)
    fig.text(.5,.015,'Hundreds from 500 to 3000 • ±25-point window • Proximity is distinct from an action crossing the milestone',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.06,1,1))
    for ext in ('pdf','png'):fig.savefig(out/f'milestone_proximity.{ext}',bbox_inches='tight')
    plt.close(fig)
