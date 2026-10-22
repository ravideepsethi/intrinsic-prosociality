"""Render only the 20 certified aggregate bins; no individual data needed."""
from pathlib import Path
import json, csv
def draw(source,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    records=json.loads(Path(source).read_text());bins=[r for r in records if 'bin' in r]
    line=next(r for r in records if r.get('record_type')=='linear_first_stage')
    assert len(bins)==20 and sum(r['rows'] for r in bins)==2682329
    sd=line['native_residual_score_SD'];slope=line['slope_receipt_pp_per_unit_residual_score']*sd
    assert abs(sd-0.04979005187533171)<1e-14
    x=np.array([r['mean_residual_score']/sd for r in bins]);y=np.array([r['mean_residual_receipt_pp'] for r in bins])
    lo=np.array([r['ci95_low_pp'] for r in bins]);hi=np.array([r['ci95_high_pp'] for r in bins])
    assert np.all(lo<=y) and np.all(y<=hi)
    plt.rcParams.update({'font.family':'DejaVu Serif','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
        'pdf.fonttype':42,'ps.fonttype':42,'savefig.facecolor':'white'})
    fig,ax=plt.subplots(figsize=(6.5,4.35),layout='constrained')
    grid=np.linspace(min(x)-.09,max(x)+.09,200)
    ax.plot(grid,slope*grid,color='#6c6c6c',lw=1.25,label=f'Linear first stage: {slope:.2f} pp per SD')
    ax.errorbar(x,y,yerr=np.vstack([y-lo,hi-y]),fmt='o',markersize=4,color='#153e62',ecolor='#153e62',
        elinewidth=1.05,capsize=2.3,label='20 equal-count bins; 95% intervals',zorder=3)
    ax.axhline(0,color='#b7b7b7',lw=.65,zorder=0)
    ax.set_xlabel('Residualized opponent score (Score A SDs)')
    ax.set_ylabel('Residual receipt (percentage points)')
    ax.set_xlim(min(grid),max(grid));ax.set_ylim(min(lo)-1.2,max(hi)+1.7)
    ax.legend(loc='upper left',frameon=False,fontsize=9)
    ax.tick_params(direction='out');out=Path(output);out.mkdir(parents=True,exist_ok=True)
    for suffix in ['pdf','png']:fig.savefig(out/('Figure5_Score_A.'+suffix),dpi=300)
    plt.close(fig)
    rows=[dict(bin=r['bin'],rows=r['rows'],mean_residual_score=r['mean_residual_score'],mean_score_in_SD=r['mean_residual_score']/sd,
        mean_residual_receipt_pp=r['mean_residual_receipt_pp'],ci95_low_pp=r['ci95_low_pp'],ci95_high_pp=r['ci95_high_pp']) for r in bins]
    with (out/'Figure5_bins.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,rows[0].keys());writer.writeheader();writer.writerows(rows)
    (out/'Figure5_caption.txt').write_text(
        'Figure 5. Opponent grant score and receipt of a draw.\n\n'
        'Twenty equal-count bins of Score A residualized under the primary X0_ENV_indicator model, '
        'using all 2,682,329 S0 exposures. The horizontal axis is in units of the common residual-score '
        f'SD, {sd:.17g}; the vertical axis is residual receipt in percentage points. '
        'Bars show 95% shared-account-OR-date CR0 intervals, conditional on the fitted residuals and bins. '
        f'The fitted linear first stage is {slope:.8f} percentage points per SD. '
        'Residual means can be negative and are not receipt probabilities.\n\n'
        'Source: H_figure5 from certified run 4028bf3e1857; the drawing uses saved aggregates only. '
        'No model was re-estimated and no observations were added or removed.\n')
    return dict(bins=20,rows=2682329,common_SD=sd,linear_first_stage_pp_per_SD=slope,
        weighted_mean_x=float(np.average(x,weights=[r['rows'] for r in bins])),weighted_mean_y=float(np.average(y,weights=[r['rows'] for r in bins])))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]/'evidence/H_figure5.json')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(draw(a.source,a.output),indent=2))
