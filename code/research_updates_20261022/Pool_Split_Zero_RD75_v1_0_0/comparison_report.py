"""Overlay independently estimated full and RD<=75 split-zero curves."""
from pathlib import Path
import csv,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from pooled_utils import write_csv,require
from fe_engine import axis_definition

SPEC='chooser_state_controls_k20'
SAMPLES=[('all','All competitive positions','#006DA4','o','-'),
         ('rd75','Both players’ RD ≤ 75','#CB6800','^','--')]
BOOLS=('display','reference','estimable','display_supported')
INTS=('bin','n','events','all_n','all_events','choosers','switching_choosers','direct_reference_choosers','months','sample_n','chooser_clusters','absorbed_units')
FLOATS=('low','high','mid','estimate_pp','cluster_se_pp','ci95_low_pp','ci95_high_pp')

def read_curves(path):
    with Path(path).open(newline='') as f:rows=list(csv.DictReader(f))
    for r in rows:
        for key in BOOLS:
            if key in r:r[key]=r[key]=='True'
        for key in INTS:
            if key in r:r[key]=int(r[key]) if r[key] else None
        for key in FLOATS:
            if key in r:r[key]=float(r[key]) if r[key] else None
    return rows

def validate_rows(rows,counts):
    for sample,_,_,_,_ in SAMPLES:
        for axis in ('gap','payoff'):
            rr=[r for r in rows if r['sample']==sample and r['axis']==axis and r['specification']==SPEC]
            expected=axis_definition(axis)[1]
            require(len(rr)==len(expected),'Missing or duplicated bins: '+sample+'/'+axis)
            bybin={r['bin']:r for r in rr}
            for e in expected:
                r=bybin[e['bin']]
                for key in ('low','high','mid','reference'):
                    require(r[key]==e[key],f'Different bin definition: {sample}/{axis}/{e["bin"]}/{key}')
            require(sum(r['n'] for r in rr)==counts[sample]['estimation_rows'],'Sample counts differ')
            require(sum(r['events'] for r in rr)==counts[sample]['estimation_grants'],'Outcome counts differ')
            refs=[r for r in rr if r['reference']]
            require(len(refs)==1 and refs[0]['estimate_pp']==0,'Wrong reference normalization')
            if axis=='payoff':
                require(refs[0]['low']==refs[0]['high']==0,'Payoff reference must be exact zero')

def plot(report,rows,counts,wide=False,clean=False):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':16,'axes.spines.top':False,
      'axes.spines.right':False,'axes.edgecolor':'#ACB4BC','pdf.fonttype':42,'svg.fonttype':'none'})
    fig,axes=plt.subplots(1,2,figsize=(16,9),sharey=True)
    fig.subplots_adjust(left=.105,right=.975,top=.82 if clean else .69,bottom=.23 if clean else .29,wspace=.16)
    used=[];cover=[];lows=[];highs=[]
    for ax,axis,title,xlabel in zip(axes,('gap','payoff'),('Relative strength','Draw payoff'),
        ('Opponent rating − chooser rating','Rating change from granting a draw')):
        for sample,label,color,marker,style in SAMPLES:
            rr=sorted([r for r in rows if r['sample']==sample and r['axis']==axis and r['specification']==SPEC
                and r['mid'] is not None and r['display_supported']
                and (wide or abs(r['mid']) <= (200.001 if axis=='gap' else 2.201))],key=lambda r:r['mid'])
            require(bool(rr),'No supported bins: '+sample+'/'+axis)
            used.extend(rr);lows.extend(r['ci95_low_pp'] for r in rr);highs.extend(r['ci95_high_pp'] for r in rr)
            for group in ([rr] if axis=='gap' else [[r for r in rr if r['mid']<0],[r for r in rr if r['mid']>0]]):
                if not group:continue
                for ix in np.split(np.arange(len(group)),np.where(np.diff([r['bin'] for r in group])>1)[0]+1):
                    x=[group[i]['mid'] for i in ix];y=[group[i]['estimate_pp'] for i in ix]
                    lo=[group[i]['ci95_low_pp'] for i in ix];hi=[group[i]['ci95_high_pp'] for i in ix]
                    ax.fill_between(x,lo,hi,color=color,alpha=.10,lw=0)
                    ax.plot(x,y,color=color,lw=2.5,marker=marker,ms=6,linestyle=style,zorder=3)
            if axis=='payoff':
                atom=next((r for r in rr if r['reference']),None)
                if atom:ax.plot(0,0,'D',color=color,mfc='white',mew=1.8,ms=10 if sample=='all' else 5,zorder=4 if sample=='all' else 5)
            cover.append(dict(axis=axis,sample=sample,displayed_rows=sum(r['n'] for r in rr),
                estimation_rows=counts[sample]['estimation_rows'],coverage=sum(r['n'] for r in rr)/counts[sample]['estimation_rows']))
        ax.axhline(0,color='#A3ABB3',lw=.9,zorder=0);ax.axvline(0,color='#A3ABB3',lw=.9,zorder=0)
        ax.grid(axis='y',color='#E7EBEF',lw=.8)
        ax.set_title(title,loc='left',fontsize=22,weight='bold',pad=15)
        ax.set_xlabel(xlabel,fontsize=17,labelpad=12)
        if axis=='gap':
            ax.set_xlim((-625,625) if wide else (-225,225));ax.set_xticks([-600,-300,0,300,600] if wide else [-200,-100,0,100,200])
        else:
            ax.set_xlim((-6.1,6.1) if wide else (-2.4,2.4));ax.set_xticks([-6,-3,0,3,6] if wide else [-2,-1,0,1,2])
        if not clean:
            c=min(r['coverage'] for r in cover if r['axis']==axis)
            ax.text(.015,.97,f'Shown bins cover ≥{np.floor(c*1000)/10:.1f}% of either sample',transform=ax.transAxes,va='top',fontsize=11,color='#536475')
    lo=min(lows);hi=max(highs);pad=max(.05,.14*(hi-lo));axes[0].set_ylim(lo-pad,hi+pad)
    axes[0].set_ylabel('Difference in kindness\n(percentage points)',fontsize=18,labelpad=12)
    axes[0].yaxis.set_major_locator(MaxNLocator(nbins=6))
    handles=[Line2D([],[],color=color,lw=2.5,marker=marker,ls=style,label=label) for _,label,color,marker,style in SAMPLES]
    fig.legend(handles=handles,loc='upper left',bbox_to_anchor=(.10,.965 if clean else .82),ncol=2,frameon=False,fontsize=18,handlelength=3,columnspacing=2.5)
    if not clean:
        fig.text(.105,.94,'Kindness, relative strength, and draw payoff',fontsize=29,weight='bold',color='#172A3A')
        fig.text(.105,.885,'Chooser × board-state fixed effects and controls',fontsize=17,color='#536475')
        foot=['Controls: ply, both players’ RD and volatility, month, speed, fine board evaluation, and rating sensitivity K.',
          'Each curve has its own reference: gap [−25, 25); draw payoff exactly zero (hollow diamonds).',
          'Payoff bins near zero: [−0.4, 0), {0}, (0, 0.4). Lines join each side separately; no smoothing.',
          f'N = {counts["all"]["estimation_rows"]:,} (all); {counts["rd75"]["estimation_rows"]:,} (both RD ≤ 75). Pointwise 95% intervals clustered by chooser.']
        for i,line in enumerate(foot):fig.text(.105,.165-i*.031,line,fontsize=12,color='#536475')
    else:
        fig.text(.105,.12,'Chooser × board-state fixed effects and controls. Pointwise 95% intervals clustered by chooser.',fontsize=12,color='#536475')
        fig.text(.105,.08,'Each curve is relative to its own near-zero gap bin or exact-zero draw payoff. Diamonds are reference markers.',fontsize=12,color='#536475')
    name='split_zero_rd75_'+('expanded' if wide else 'central')+('_plot_only' if clean else '')
    for ext in ('png','pdf'):fig.savefig(report/'figures'/(name+'.'+ext),dpi=200,facecolor='white')
    plt.close(fig)
    return [dict(r,figure=name) for r in used],[dict(r,figure=name) for r in cover]

def build_comparison(report,all_dir,rd_dir):
    report=Path(report);counts={};rows=[];contrasts=[]
    for sample,path in [('all',all_dir),('rd75',rd_dir)]:
        path=Path(path);counts[sample]=json.loads((path/'SAMPLE_COUNTS.json').read_text())
        require(counts[sample]['sample']==sample,'Wrong sample count label')
        new=read_curves(path/'curves.csv')
        require(all(r['sample']==sample for r in new),'Wrong curve sample label')
        rows.extend(new)
        with (path/'near_zero_contrasts.csv').open(newline='') as f:
            contrasts.extend(dict(r,sample=sample) for r in csv.DictReader(f))
    validate_rows(rows,counts)
    (report/'figures').mkdir(exist_ok=True)
    plotted=[];coverage=[]
    for wide in (False,True):
        for clean in (False,True):
            a,b=plot(report,rows,counts,wide,clean);plotted+=a;coverage+=b
    write_csv(report/'curves.csv',rows)
    write_csv(report/'near_zero_contrasts.csv',contrasts)
    write_csv(report/'plotted_data.csv',plotted)
    write_csv(report/'display_coverage.csv',coverage)
    (report/'SAMPLE_COUNTS.json').write_text(json.dumps(counts,indent=2)+'\n')
    text=['# Split-zero curves with both RD <= 75 overlay','',
      'The all-competitive curve is reused unchanged from authenticated run 2994ab11f07eaf09. The RD<=75 curve is newly estimated using exactly the same split-zero bins, controls, and chooser-by-board-state fixed effects.',
      '', '## Adjusted comparisons within each sample','',
      '| Sample | Contrast | Estimate (pp) | Cluster SE (pp) | Holm p (three within-sample contrasts) |',
      '|---|---|---:|---:|---:|']
    for r in contrasts:
        if r['specification']!=SPEC:continue
        fmt=lambda k:format(float(r[k]),'.6g') if r[k] else 'unsupported'
        text.append(f'| {r["sample"]} | {r["contrast"]} | {fmt("estimate_pp")} | {fmt("cluster_se_pp")} | {fmt("p_holm_three_adjusted_contrasts")} |')
    text+=['','Each curve is normalized to its own reference category. The overlay compares shapes and within-sample contrasts, not absolute kindness levels. No test of the difference between the nested samples is claimed; their estimates are correlated.',
      '', 'The exact-zero point is a reference marker. Finite-bin contrasts do not establish a causal threshold effect or a derivative kink. RD<=75 is imposed before recomputing chooser-by-state singleton removal; all-zero outcome accounts remain.',
      '', 'No K=11–12 restriction is imposed. K controls remain. Full and expanded PNG/PDF figures, with and without the slide title, are in figures/.']
    (report/'SUMMARY.md').write_text('\n'.join(text)+'\n')
