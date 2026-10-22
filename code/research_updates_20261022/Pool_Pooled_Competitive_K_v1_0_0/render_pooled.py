#!/usr/bin/env python3
"""Render pooled and interacted curves from public aggregate results."""
import csv
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pooled_engine import STATES,INTERACTED

def truth(x):return str(x).lower()=='true'
def number(x):return float(x) if x not in ('',None) else np.nan

def render(report):
    report=Path(report);out=report/'figures';out.mkdir(exist_ok=True)
    with (report/'curves.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    counts=json.loads((report/'SAMPLE_COUNTS.json').read_text())
    def get(axis,spec,state='pooled_competitive'):
        return sorted([r for r in rows if r['axis']==axis and r['specification']==spec and r['context']==state and r['mid']!=''],key=lambda r:float(r['mid']))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':13,'pdf.fonttype':42,
      'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#A4AFBB',
      'text.color':'#24344A','axes.labelcolor':'#24344A'})
    metadata=[]
    versions=[('pooled_main',False,True),('pooled_full_range',False,False),
      ('pooled_specification_ladder',True,False),('board_state_interactions',False,True)]
    for stem,ladder,central in versions:
        interaction=stem=='board_state_interactions'
        if interaction:
            labels=['Roughly equal','Better','Clearly better']
            specs=[(INTERACTED,labels[i],color,'-',state) for i,(state,color) in enumerate(zip(STATES,['#1769AA','#C47624','#238B70']))]
        else:
            specs=[('raw','Raw, same estimation rows','#929AA3','--','pooled_competitive'),
              ('chooser_state_controls_k20','Chooser × board-state FE + controls + K20','#1769AA','-','pooled_competitive')]
            if ladder:
                specs.insert(1,('chooser_state_controls','Chooser × board-state FE + controls','#C47624','-','pooled_competitive'))
                specs.append(('chooser_state_controls_k50','Chooser × board-state FE + controls + K50','#238B70',':','pooled_competitive'))
        fig,axes=plt.subplots(1,2,figsize=(14.4,8.1),sharey=True)
        fig.subplots_adjust(left=.085,right=.98,bottom=.27,top=.67,wspace=.15)
        extremes=[];display_counts={}
        for ax,axis in zip(axes,['gap','payoff']):
            series=[get(axis,spec,state) for spec,_,_,_,state in specs]
            x=np.array([float(r['mid']) for r in series[0]])
            common=np.array([all(truth(v[i]['display_supported']) for v in series) for i in range(len(x))])
            if central and axis=='gap':common&=(x>=-200)&(x<=200)
            display_counts[axis]=int(sum(int(r['n']) for r,ok in zip(series[0],common) if ok))
            for (spec,label,color,style,state),data in zip(specs,series):
                y=np.array([number(r['estimate_pp']) for r in data]);lo=np.array([number(r['ci95_low_pp']) for r in data]);hi=np.array([number(r['ci95_high_pp']) for r in data])
                y=np.where(common,y,np.nan);lo=np.where(common,lo,np.nan);hi=np.where(common,hi,np.nan)
                ax.plot(x,y,label=label,color=color,ls=style,lw=2,marker='o',ms=3.5)
                if interaction or spec=='chooser_state_controls_k20':
                    ax.fill_between(x,lo,hi,color=color,alpha=.11 if interaction else .16,lw=0)
                    extremes.extend(lo[np.isfinite(lo)]);extremes.extend(hi[np.isfinite(hi)])
                extremes.extend(y[np.isfinite(y)])
            ax.axhline(0,color='#A7B1BC',lw=.8);ax.axvline(0,color='#D3DAE3',lw=.8)
            ax.grid(axis='y',color='#E8EDF2',lw=.8);ax.set_axisbelow(True)
            if axis=='gap':
                ax.set_title('Relative strength',fontsize=18,pad=14)
                ax.set_xlabel('Opponent minus chooser rating',labelpad=10)
                ax.set_xlim((-225,225) if central else (-625,625))
                ax.set_xticks([-200,-100,0,100,200] if central else [-600,-300,0,300,600])
            else:
                ax.set_title('Draw payoff',fontsize=18,pad=14)
                ax.set_xlabel('Chooser’s rating change from a draw',labelpad=10)
                ax.set_xlim(-6.1,6.1);ax.set_xticks([-6,-3,0,3,6])
            if not common.any():ax.text(.5,.6,'Insufficient common display support',transform=ax.transAxes,ha='center')
        if extremes:
            span=max(max(extremes)-min(extremes),.25)
            axes[0].set_ylim(min(min(extremes),0)-.08*span,max(max(extremes),0)+.08*span)
        axes[0].set_ylabel('Kindness relative to reference bin\n(percentage points)',labelpad=12)
        fig.text(.085,.94,'Does the relationship differ across board states?' if interaction else 'Pooled competitive positions',fontsize=24,weight='bold')
        fig.text(.085,.883,'Opponent evaluation ≥ −100 cp · chooser-by-board-state fixed effects · clustered by chooser',fontsize=13.5,color='#56667A')
        fig.text(.085,.837,f'{counts["estimation_rows"]:,} opportunities · {counts["chooser_clusters"]:,} chooser accounts',fontsize=13,color='#56667A')
        handles,labels=axes[0].get_legend_handles_labels()
        fig.legend(handles,labels,loc='upper left',bbox_to_anchor=(.077,.808),ncol=2 if not interaction else 3,frameon=False,fontsize=11.5)
        if central and not interaction:
            share=100*display_counts['gap']/counts['estimation_rows']
            note=f'Central rating-gap bins shown ({share:.2f}% of estimation rows); full-range version supplied. Plot limits do not restrict estimation.'
        elif interaction:note='Each state’s curve is relative to its own reference bin; common supported display bins only. Controls share slopes across states.'
        else:note='All supported plotted bins shown. Extreme observations remain in estimation; no smoothing or shape restriction.'
        fig.text(.085,.132,note,fontsize=10.5,color='#56667A')
        fig.text(.085,.09,'References: gap [−25,+25); payoff [−0.4,+0.4). Shading: pointwise 95% confidence intervals, clustered by chooser.',fontsize=10.5,color='#56667A')
        fig.text(.085,.048,'Controls: ply, both players’ RD and volatility, month, speed, 50-cp evaluation bins; K20/K50 indicators plus log K.',fontsize=10.5,color='#56667A')
        for ext in ('png','pdf'):fig.savefig(out/(stem+'.'+ext),dpi=180,facecolor='white')
        plt.close(fig)
        metadata.append(dict(figure=stem,central_rating_gap_display=central,no_smoothing=True,display_counts=display_counts))
    (report/'FIGURE_METADATA.json').write_text(json.dumps(metadata,indent=2)+'\n')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True)
    render(p.parse_args().report)
