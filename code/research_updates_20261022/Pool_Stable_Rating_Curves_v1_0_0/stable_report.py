"""Aggregate-only tables and publication-exportable unrestricted curve figures."""
import csv,json
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from stable_specs import SAMPLES
from fe_engine import AXES,axis_definition
from pooled_engine import STATES,INTERACTED
from pooled_utils import write_csv

ADJ='chooser_state_controls_k20'
COLORS={'all':'#88929f','rd75':'#1769aa','rd60':'#22856a','rd100':'#bf771e','rd75_k11_12':'#c27630'}
SHORT={'all':'All competitive','rd75':'Both RD ≤ 75','rd60':'Both RD ≤ 60','rd100':'Both RD ≤ 100','rd75_k11_12':'RD ≤ 75; K 11–12'}
XLABELS={'gap':'Opponent minus chooser rating','payoff':'Draw payoff D (rating points)','normalized':'Normalized payoff D/K = 0.5 − E'}
XLIMS={'gap':(-625,625),'payoff':(-6.1,6.1),'normalized':(-.505,.505)}

def truth(x):return str(x).lower()=='true'
def num(x):return float(x) if x not in (None,'') else np.nan

def common_weight_tail(report,rows):
    """Same weights/bins within each baseline-versus-restricted comparison.

    No test of the difference: cross-sample covariance is not estimated.
    Reports retained support rather than treating removed tails as a null.
    """
    results=[]
    for sample in ('rd75','rd60','rd100','rd75_k11_12'):
        axis='payoff';data={s:sorted([r for r in rows if r['sample']==s and r['axis']==axis and r['specification']==ADJ and r['context']=='pooled_competitive'],key=lambda r:r['bin']) for s in ('all',sample)}
        if not data[sample]:continue
        mids=np.array([num(r['mid']) for r in data['all']]);n=np.array([r['n'] for r in data['all']],dtype=float)
        supported=np.logical_and(*[np.array([r['display_supported'] for r in data[s]]) for s in ('all',sample)])
        masks={'left':(mids>=-6)&(mids<=-3),'shoulder':(mids>=-2.4)&(mids<=-1.2)}
        weights={};receipts={}
        for name,mask in masks.items():
            w=mask*supported*n;weights[name]=w/w.sum() if w.sum() else None
            receipts[name+'_bins']=[float(v) for v in mids[mask&supported]]
            receipts[name+'_baseline_rows_in_common_bins']=int(w.sum())
            receipts[name+'_baseline_rows_in_original_range']=int(n[mask].sum())
        for s in ('all',sample):
            row=dict(comparison='all_vs_'+sample,sample=s,axis=axis,status='insufficient_common_support',**receipts,
                     estimate_pp=None,cluster_se_pp=None,ci95_low_pp=None,ci95_high_pp=None,
                     between_sample_difference_tested=False)
            if weights['left'] is not None and weights['shoulder'] is not None:
                w=weights['left']-weights['shoulder'];key=axis+'__'+ADJ
                with np.load(report/(s+'_curve_covariances.npz'),allow_pickle=False) as z:
                    b=z[key+'__estimates'];V=z[key+'__covariance'];value=float(w@b);se=float(np.sqrt(max(0,w@V@w)))
                G=data[s][0]['chooser_clusters'];t=float(student_t.ppf(.975,G-1))
                row.update(status='estimated_on_reported_common_bins',estimate_pp=100*value,cluster_se_pp=100*se,
                           ci95_low_pp=100*(value-t*se),ci95_high_pp=100*(value+t*se))
            results.append(row)
    if results:write_csv(report/'common_weight_payoff_tail.csv',results)

def render(report,rows=None):
    report=Path(report);out=report/'figures';out.mkdir(exist_ok=True)
    if rows is None:
        with (report/'curves.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    def get(sample,axis,spec,state='pooled_competitive'):
        return sorted([r for r in rows if r['sample']==sample and r['axis']==axis and r['specification']==spec and r['context']==state and r['mid'] not in ('',None)],key=lambda r:num(r['mid']))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#a6adb7'})
    metadata=[]
    def decorate(ax,axis):
        ax.axhline(0,color='#b6bbc3',lw=.6);ax.axvline(0,color='#b6bbc3',lw=.6)
        ax.grid(axis='y',color='#edf0f3');ax.set_axisbelow(True);ax.set_xlim(XLIMS[axis]);ax.set_xlabel(XLABELS[axis])
    def save(fig,name,note):
        fig.text(.07,.045,note,fontsize=9,color='#536274',va='bottom')
        for ext in ('png','pdf'):fig.savefig(out/(name+'.'+ext),dpi=170,facecolor='white')
        plt.close(fig)
    main_samples=('all','rd75','rd75_k11_12')
    for common in (False,True):
        fig,axes=plt.subplots(2,3,figsize=(16,9),sharey='row');fig.subplots_adjust(left=.07,right=.985,top=.80,bottom=.20,hspace=.4,wspace=.15)
        for r,spec in enumerate(('raw',ADJ)):
            for c,axis in enumerate(AXES):
                ax=axes[r,c];data={s:get(s,axis,spec) for s in main_samples};present=[s for s in main_samples if data[s]]
                if not present:continue
                x=np.array([num(t['mid']) for t in data[present[0]]])
                shared=np.logical_and.reduce([np.array([truth(t['display_supported']) for t in data[s]]) for s in present])
                for s in present:
                    d=data[s];keep=shared if common else np.array([truth(t['display_supported']) for t in d])
                    y=np.array([num(t['estimate_pp']) for t in d]);lo=np.array([num(t['ci95_low_pp']) for t in d]);hi=np.array([num(t['ci95_high_pp']) for t in d])
                    ax.plot(x,np.where(keep,y,np.nan),color=COLORS[s],lw=1.6,marker='o',ms=3,label=SHORT[s])
                    ax.fill_between(x,np.where(keep,lo,np.nan),np.where(keep,hi,np.nan),color=COLORS[s],alpha=.10,lw=0)
                    metadata.append(dict(figure='common_support' if common else 'raw_and_adjusted',axis=axis,sample=s,specification=spec,displayed_n=sum(int(t['n']) for t,k in zip(d,keep) if k),estimation_n=int(d[0]['sample_n'])))
                decorate(ax,axis)
                if c==0:ax.set_ylabel(('Raw' if r==0 else 'Chooser × state FE + controls')+'\nDifference from reference (pp)')
        fig.suptitle('Stable-rating curves: '+('common supported bins' if common else 'all supported bins'),x=.07,ha='left',y=.97,fontsize=22,weight='bold')
        fig.text(.07,.914,'Competitive positions · same estimation rows across the three axes within each sample · no shape restriction',fontsize=12)
        handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='upper left',bbox_to_anchor=(.063,.887),ncol=3,frameon=False)
        note=('Common display support across the three samples; omitted bins remain in estimation.' if common else 'Each curve uses its own supported bins; gaps indicate insufficient support, not zero effects.')+'\nReference bins: gap [−25,25); D [−0.4,0.4); D/K [−0.025,0.025). Pointwise 95% intervals, clustered by chooser.\nBoth-player RD cutoffs are research definitions. All curves are conditional associations; different axis bins aggregate different observations.'
        save(fig,'02_common_support' if common else '01_raw_and_adjusted',note)
    fig,axes=plt.subplots(1,3,figsize=(16,6),sharey=True);fig.subplots_adjust(left=.07,right=.985,top=.73,bottom=.26,wspace=.15)
    for ax,axis in zip(axes,AXES):
        for s in ('rd60','rd75','rd100'):
            d=get(s,axis,ADJ)
            if not d:continue
            x=np.array([num(t['mid']) for t in d]);keep=np.array([truth(t['display_supported']) for t in d])
            ax.plot(x,np.where(keep,[num(t['estimate_pp']) for t in d],np.nan),color=COLORS[s],lw=1.7,label=SHORT[s])
            ax.fill_between(x,np.where(keep,[num(t['ci95_low_pp']) for t in d],np.nan),np.where(keep,[num(t['ci95_high_pp']) for t in d],np.nan),color=COLORS[s],alpha=.1)
        decorate(ax,axis)
    axes[0].set_ylabel('Adjusted difference from reference (pp)');fig.suptitle('Sensitivity to both-player RD cutoff',x=.07,ha='left',y=.97,fontsize=22,weight='bold')
    h,l=axes[0].get_legend_handles_labels();fig.legend(h,l,loc='upper left',bbox_to_anchor=(.06,.88),ncol=3,frameon=False)
    save(fig,'03_RD_sensitivity','Chooser × board-state fixed effects; same controls across cutoffs. Pointwise 95% chooser-clustered intervals.\nSeparate samples at each cutoff; plotted curves are normalized within their own reference bins.')
    fig,axes=plt.subplots(2,3,figsize=(16,9),sharey='row');fig.subplots_adjust(left=.07,right=.985,top=.80,bottom=.19,hspace=.4,wspace=.15)
    for r,sample in enumerate(('rd75','rd75_k11_12')):
        for c,axis in enumerate(AXES):
            ax=axes[r,c]
            for state,color in zip(STATES,('#1769aa','#c27630','#22856a')):
                d=get(sample,axis,INTERACTED,state)
                if not d:continue
                x=np.array([num(t['mid']) for t in d]);keep=np.array([truth(t['display_supported']) for t in d])
                ax.plot(x,np.where(keep,[num(t['estimate_pp']) for t in d],np.nan),color=color,label=state.replace('_',' ').title())
                ax.fill_between(x,np.where(keep,[num(t['ci95_low_pp']) for t in d],np.nan),np.where(keep,[num(t['ci95_high_pp']) for t in d],np.nan),color=color,alpha=.1)
            decorate(ax,axis)
            if c==0:ax.set_ylabel(SHORT[sample]+'\nAdjusted difference (pp)')
    fig.suptitle('Allow the curves to differ by board state',x=.07,ha='left',y=.97,fontsize=22,weight='bold')
    h,l=axes[0,0].get_legend_handles_labels();fig.legend(h,l,loc='upper left',bbox_to_anchor=(.06,.91),ncol=3,frameon=False)
    save(fig,'04_board_state_curves','State-specific axis effects and chooser × state fixed effects; nuisance slopes remain common.\nEach state is normalized to its own reference bin. Pointwise 95% chooser-clustered intervals; unsupported bins are blank.')
    with (report/'bin_composition.csv').open(newline='') as f:comp=list(csv.DictReader(f))
    fig,axes=plt.subplots(2,3,figsize=(16,8),sharey='row');fig.subplots_adjust(left=.07,right=.985,top=.81,bottom=.18,hspace=.35,wspace=.15)
    for c,axis in enumerate(AXES):
        for s in main_samples:
            d=sorted([t for t in comp if t['sample']==s and t['axis']==axis and t['mid']!=''],key=lambda t:num(t['mid']))
            x=np.array([num(t['mid']) for t in d]);n=np.array([num(t['n']) for t in d]);k=np.array([num(t['mean_K']) for t in d])
            axes[0,c].plot(x,np.where(n>0,n,np.nan),color=COLORS[s],label=SHORT[s])
            axes[1,c].plot(x,np.where(n>0,k,np.nan),color=COLORS[s])
        for r in range(2):axes[r,c].set_xlabel(XLABELS[axis]);axes[r,c].set_xlim(XLIMS[axis])
        axes[0,c].set_yscale('log')
    axes[0,0].set_ylabel('Observations per bin (log scale)');axes[1,0].set_ylabel('Mean K within bin')
    fig.suptitle('What observations support each curve?',x=.07,ha='left',y=.97,fontsize=22,weight='bold')
    h,l=axes[0,0].get_legend_handles_labels();fig.legend(h,l,loc='upper left',bbox_to_anchor=(.06,.92),ncol=3,frameon=False)
    save(fig,'05_support_and_K','Includes sparse finite bins hidden in the effect plots. Overflow bins remain in estimation and are listed in the CSVs.\nA disappearing tail can reflect lost support; consult common_weight_payoff_tail.csv before interpreting changes.')
    (report/'FIGURE_METADATA.json').write_text(json.dumps(metadata,indent=2)+'\n')

def build_report(report,rows,shapes,local,counts):
    common_weight_tail(report,rows);render(report,rows)
    def fmt(x):return '—' if x is None else f'{x:.5g}'
    lines=['# Stable-rating curves: results','',
      'Exploratory conditional associations. Cutoffs, bin edges, controls and local bandwidths were fixed in the runner before this run. No monotonicity, sigmoid or S-shape was imposed.','',
      '| Sample | Opportunities before singleton removal | Estimation opportunities | Chooser clusters |',
      '|---|---:|---:|---:|']
    for r in counts:lines.append(f'| {r["label"]} | {r["source_competitive_rows"]:,} | {r["estimation_rows"]:,} | {r["chooser_clusters"]:,} |')
    lines+=['','## Primary near-zero diagnostic','',
      'Both pregame RD ≤75 and K ∈[11,12]; normalized payoff |D/K|≤0.05. Separate left/right slopes, a right-limit jump, and an exact-zero indicator. Slopes are percentage points per unit D/K. These are local linear approximations, not structural loss-aversion parameters.','',
      '| Term | Estimate | Cluster SE | Holm p (5 tests) | Status |','|---|---:|---:|---:|---|']
    for r in local:
        if r['primary_specification']:lines.append(f'| {r["term"]} | {fmt(r["estimate_pp"])} | {fmt(r["cluster_se_pp"])} | {fmt(r.get("p_holm_primary_5_tests"))} | {r["status"]} |')
    lines+=['','## Read these files','',
      '- `figures/01_raw_and_adjusted.png`: unrestricted raw and adjusted curves with support gaps visible.',
      '- `figures/02_common_support.png`: the same curves restricted to common displayed bins.',
      '- `figures/03_RD_sensitivity.png`: RD 60, 75 and 100.',
      '- `figures/04_board_state_curves.png`: allows different responses in the three competitive board states.',
      '- `figures/05_support_and_K.png`, `bin_composition.csv`: support, K and both-player RD composition.',
      '- `common_weight_payoff_tail.csv`: baseline and restricted tails using identical bins and baseline weights within each pair. No cross-sample difference test is reported.',
      '- `zero_diagnostics.csv`: all bandwidths, coefficients, clustered uncertainty, sample sizes and support flags.',
      '- `REFERENCE_MODEL.md`: the stated model and what the diagnostics can and cannot establish.','',
      'A nonsignificant rebound is not evidence that the rebound is absent. Check confidence intervals and tail coverage. An S-shaped grant curve does not by itself distinguish reference dependence from relative strength.']
    (report/'RESULTS.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);render(p.parse_args().report)
