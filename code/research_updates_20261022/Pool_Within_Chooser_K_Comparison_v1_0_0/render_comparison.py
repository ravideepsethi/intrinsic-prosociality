#!/usr/bin/env python3
"""Render aggregate curve estimates without access to private observations."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fe_engine import CONTEXTS


def render(report):
    report=Path(report);out=report/'figures';out.mkdir(parents=True,exist_ok=True)
    with (report/'curves.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    titles={x[0]:x[1] for x in CONTEXTS}
    def extract(context,axis,spec):
        r=[x for x in rows if x['context']==context and x['axis']==axis and x['specification']==spec
           and x['mid'] not in ('',None)]
        return sorted(r,key=lambda x:float(x['mid']))
    def truth(s):return str(s).lower()=='true'
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':12,'pdf.fonttype':42,
        'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#ADB7C2',
        'text.color':'#203040','axes.labelcolor':'#203040'})
    present=list(dict.fromkeys(x['context'] for x in rows))
    for context in present:
        for ladder in [False,True]:
            fig,axes=plt.subplots(1,2,figsize=(14,7.8),sharey=True)
            fig.subplots_adjust(left=.08,right=.98,bottom=.29,top=.74,wspace=.13)
            specs=[('raw','Raw, same accounts','#888E96','--'),
                   ('chooser_controls_k20','Chooser FE + controls + K20','#1268A8','-')]
            if ladder:
                specs=[specs[0],('chooser_controls','Chooser FE + controls','#C47A20','-'),
                       specs[1],('chooser_controls_k50','Chooser FE + controls + K50','#168E86',':')]
            extrema=[]
            for ax,axis in zip(axes,['gap','payoff']):
                series={s:extract(context,axis,s) for s,_,_,_ in specs}
                # Same displayed bins for every line; no selecting by outcome or p-value.
                common=np.array([all(truth(series[s][i]['display_supported']) for s,_,_,_ in specs)
                                  for i in range(len(series[specs[0][0]]))])
                for spec,label,color,style in specs:
                    data=series[spec];x=np.array([float(r['mid']) for r in data])
                    def values(key):
                        return np.array([float(r[key]) if r[key] not in ('',None) else np.nan for r in data])
                    y=np.where(common,values('estimate_pp'),np.nan)
                    low=np.where(common,values('ci95_low_pp'),np.nan)
                    high=np.where(common,values('ci95_high_pp'),np.nan)
                    ax.plot(x,y,color=color,linestyle=style,label=label,marker='o',markersize=3,linewidth=1.8)
                    if spec=='chooser_controls_k20':
                        ax.fill_between(x,low,high,color=color,alpha=.17,linewidth=0)
                        extrema.extend(low[np.isfinite(low)]);extrema.extend(high[np.isfinite(high)])
                    extrema.extend(y[np.isfinite(y)])
                ax.axhline(0,color='#AAB5BF',linewidth=.8);ax.axvline(0,color='#CBD2D9',linewidth=.8)
                ax.grid(axis='y',color='#E7EBEF',linewidth=.7)
                if axis=='gap':
                    ax.set_xlabel('Opponent minus chooser rating');ax.set_xlim(-625,625)
                    ax.set_xticks([-600,-300,0,300,600]);ax.set_title('Relative strength',pad=14)
                else:
                    ax.set_xlabel('Chooser’s signed draw payoff');ax.set_xlim(-6.1,6.1)
                    ax.set_xticks([-6,-3,0,3,6]);ax.set_title('Draw payoff (rating points)',pad=14)
                if not common.any():ax.text(.5,.55,'Insufficient common display support',ha='center',transform=ax.transAxes)
            if extrema:
                span=max(max(extrema)-min(extrema),.25)
                axes[0].set_ylim(min(min(extrema),0)-.08*span,max(max(extrema),0)+.08*span)
            axes[0].set_ylabel('Change in kindness (percentage points)')
            fig.suptitle(titles[context],x=.08,ha='left',fontsize=21,y=.95)
            example=extract(context,'gap','raw')[0]
            fig.text(.08,.891,f'{int(example["sample_n"]):,} opportunities · {int(example["chooser_clusters"]):,} repeated-choice accounts',
                     fontsize=12,color='#526577')
            handles,labels=axes[0].get_legend_handles_labels()
            fig.legend(handles,labels,loc='upper left',bbox_to_anchor=(.075,.864),frameon=False,
                       ncol=2 if ladder else 2,fontsize=11,columnspacing=1.6)
            fig.text(.08,.19,'References: rating gap [−25, +25); draw payoff [−0.4, +0.4). Lines join existing bin estimates; no smoothing.',fontsize=10)
            fig.text(.08,.155,'Shading: pointwise 95% confidence intervals, clustered by chooser, for the K20 model. Raw curves use the same estimation rows.',fontsize=10)
            fig.text(.08,.12,'Controls: ply, both players’ RD and volatility, month, speed, and 50-cp board bins. K20/K50 use pooled quantile cutpoints plus log K; ties collapse.',fontsize=9.6)
            fig.text(.08,.085,'Only supported, estimable bins are shown. Effects are normalized within each panel; these are associations, not causal price effects.',fontsize=10)
            stem=('ladder_' if ladder else 'comparison_')+context
            for suffix in ['pdf','png']:
                fig.savefig(out/(stem+'.'+suffix),dpi=160,facecolor='white')
            plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True)
    render(p.parse_args().report)
