"""Rebuild the two main statistical figures from authenticated aggregates."""
from pathlib import Path
import json,hashlib
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent

def verify(p):
    rel=p.relative_to(ROOT).as_posix();matches=[x for x in json.loads((ROOT/'SOURCE_REPORTS_MANIFEST.json').read_text()) if x['path']==rel]
    if len(matches)!=1 or hashlib.sha256(p.read_bytes()).hexdigest()!=matches[0]['sha256']:raise RuntimeError('Figure input checksum differs: '+rel)

def main():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    out=ROOT/'figures';out.mkdir(exist_ok=True);lineage={}
    path=ROOT/'source_reports/structure/board_stage.csv';verify(path);d=pd.read_csv(path)
    values=d.pivot(index='position_code',columns='stage_code',values='grant_rate_pct').reindex(index=[4,3,2,1,0],columns=range(8))
    counts=d.pivot(index='position_code',columns='stage_code',values='opportunities').reindex(index=[4,3,2,1,0],columns=range(8))
    if d.opportunities.sum()!=41513719 or d.grants.sum()!=570422:raise RuntimeError('Figure census differs')
    fig,ax=plt.subplots(figsize=(11.4,5.6));image=ax.imshow(values,aspect='auto',cmap='YlGnBu',vmin=0,vmax=max(5,float(values.max().max())))
    ax.set_xticks(range(8),['0–4','5–6','7–8','9–10','11–20','21–40','41–80','81+']);ax.set_yticks(range(5),['Clearly better','Better','Roughly equal','Modestly worse','Clearly worse'])
    ax.set_xlabel('Recorded plies');ax.set_ylabel('Disconnected player’s position')
    for i in range(5):
        for j in range(8):
            x=values.iloc[i,j];n=counts.iloc[i,j]
            if pd.notna(x):ax.text(j,i,f'{x:.2f}%\n{int(n):,}',ha='center',va='center',fontsize=8.4,color='white' if x>3.5 else '#132231',linespacing=1.8)
    ax.axhline(2.5,color='white',linewidth=2.5);bar=fig.colorbar(image,ax=ax,pad=.025);bar.set_label('Granted draws (%)')
    fig.tight_layout();fig.savefig(out/'fig2_position_stage.pdf');fig.savefig(out/'fig2_position_stage.png',dpi=180);plt.close(fig)
    lineage['fig2_position_stage.pdf']=dict(source=path.relative_to(ROOT).as_posix(),rows=41513719,grants=570422,confidence_intervals=False)
    path=ROOT/'source_reports/iv_receipt/FIRST_STAGE_BINS.csv';verify(path);d=pd.read_csv(path).sort_values('bin')
    if len(d)!=20 or d.exposures.sum()!=9736412:raise RuntimeError('First-stage bins do not exhaust primary exposures')
    fig,axes=plt.subplots(1,2,figsize=(10.8,4.6))
    for ax,sub,title in [(axes[0],d,'A. All twenty bins'),(axes[1],d.iloc[:-1],'B. Top bin omitted')]:
        x=sub.mean_score_reference_sd.to_numpy();y=sub.mean_residual_receipt_pp.to_numpy();errors=np.vstack([y-sub.ci_low_pp.to_numpy(),sub.ci_high_pp.to_numpy()-y])
        ax.errorbar(x,y,yerr=errors,fmt='o',markersize=4,color='#145a74',ecolor='#145a74',capsize=2,zorder=3)
        line=np.array([min(x),max(x)]);ax.plot(line,7.253784217066368*line,color='#b65e31',linewidth=1.3,label='Linear first stage')
        ax.axhline(0,color='#b4b9bd',linewidth=.7);ax.set_xlabel('Residual score / 0.0497901');ax.set_title(title,loc='left',fontsize=11);ax.grid(axis='y',alpha=.15)
    axes[0].set_ylabel('Residual draw receipt (percentage points)');axes[0].legend(frameon=False,fontsize=9)
    fig.tight_layout();fig.savefig(out/'fig5_iv_bins.pdf');fig.savefig(out/'fig5_iv_bins.png',dpi=180);plt.close(fig)
    lineage['fig5_iv_bins.pdf']=dict(source=path.relative_to(ROOT).as_posix(),exposures=9736412,score_unit=.04979005187533171,linear_first_stage=7.253784217066368,intervals='Reported 95% bin intervals')
    (out/'FIGURE_LINEAGE.json').write_text(json.dumps(lineage,indent=2)+'\n')

if __name__=='__main__':main()
