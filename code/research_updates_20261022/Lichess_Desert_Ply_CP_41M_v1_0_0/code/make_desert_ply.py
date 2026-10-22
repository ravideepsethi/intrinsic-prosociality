#!/usr/bin/env python3
"""Render the percentage-only heatmap with board-state labels and centipawn boundaries."""
from pathlib import Path
import csv
import datetime as dt
import hashlib
import json
import math
import platform

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.container import ErrorbarContainer
import numpy as np
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
STEM='fig1_desert_ply_41M_cp'
STATES=['disconnected_clearly_better','disconnected_better','roughly_equal','modestly_worse_excluded','clearly_worse']
LABELS=['Clearly better','Better','Roughly equal','Modestly worse','Clearly worse']
# Frozen descriptive bins, from FIGURE_SPECIFICATION.md and manuscript sec:desert_measure.
CP_RANGES=['≥ +300','+101 to +299','−100 to +100','−299 to −101','≤ −300']
Y_BOUNDARIES=[.5,1.5,2.5,3.5]
Y_LABELS=['+300','+100','−100','−300']
BANDS=['0_4','5_6','7_8','9_10','11_20','21_40','41_80','81_plus']
BAND_LABELS=['0–4','5–6','7–8','9–10','11–20','21–40','41–80','81+']
CHECKS=[]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def check(name,condition):
    if not condition:raise AssertionError(name)
    CHECKS.append({'check':name,'status':'PASS'})


def read(name):
    with (ROOT/'source_data'/name).open(newline='') as f:
        rows=list(csv.DictReader(f))
    for r in rows:
        r['rows']=int(r['rows']);r['kind_draws']=int(r['kind_draws'])
        r['kind_rate_pct']=float(r['kind_rate_pct'])
    return rows


def write(name,rows,columns):
    p=ROOT/'plotdata'/name
    with p.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(rows)


def main():
    for d in ['figures','plotdata','verification']:(ROOT/d).mkdir(exist_ok=True)
    manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())
    for item in manifest['entries']:
        check('SHA-256: '+item['file'],sha(ROOT/item['file'])==item['sha256'])
    authority=json.loads((ROOT/'SAMPLE_AUTHORITY.json').read_text())
    check('Current certified pool sample',authority['rows']==41534331 and authority['kind_draws']==570091 and authority['fingerprint']=='a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30')
    board=read('fairness_bins.csv');cells=read('state_ply.csv')
    by_state={r['fairness_bin']:r for r in board}
    lookup={(r['fairness_bin'],r['ply_band']):r for r in cells}
    check('Exactly five board states',len(board)==5 and set(by_state)==set(STATES))
    check('Exactly forty distinct state-by-ply cells',len(cells)==40 and set(lookup)=={(s,b) for s in STATES for b in BANDS})
    check('Heatmap and marginal table conserve all opportunities',sum(r['rows'] for r in board)==sum(r['rows'] for r in cells)==41534331)
    check('Heatmap and marginal table conserve all kind draws',sum(r['kind_draws'] for r in board)==sum(r['kind_draws'] for r in cells)==570091)
    check('Stored rates agree with counts',all(math.isclose(r['kind_rate_pct'],100*r['kind_draws']/r['rows'],abs_tol=1e-11) for r in board+cells))
    for s in STATES:
        check('Ply cells aggregate to state: '+s,
              sum(lookup[(s,b)]['rows'] for b in BANDS)==by_state[s]['rows'] and
              sum(lookup[(s,b)]['kind_draws'] for b in BANDS)==by_state[s]['kind_draws'])
    matrix=np.array([[lookup[(s,b)]['kind_rate_pct'] for b in BANDS] for s in STATES])
    check('Color scale contains every cell',matrix.min()>=0 and matrix.max()<=5.6)

    write('board_merit_by_ply.csv',[{'board_state':label,'ply_band':blabel,'opportunities':lookup[(s,b)]['rows'],'kind_draws':lookup[(s,b)]['kind_draws'],'kind_rate_pct':lookup[(s,b)]['kind_rate_pct']} for s,label in zip(STATES,LABELS) for b,blabel in zip(BANDS,BAND_LABELS)],['board_state','ply_band','opportunities','kind_draws','kind_rate_pct'])
    write('heatmap_rates_wide.csv',[{'board_state':label,**{blabel:float(matrix[i,j]) for j,blabel in enumerate(BAND_LABELS)}} for i,label in enumerate(LABELS)],['board_state']+BAND_LABELS)

    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,'axes.labelsize':10.5,
        'xtick.labelsize':10.5,'ytick.labelsize':10.5,'axes.titlesize':12.5,
        'axes.titleweight':'bold','axes.linewidth':.7,'pdf.fonttype':42,'ps.fonttype':42,
        'svg.fonttype':'path','svg.hashsalt':'desert-ply-41m-heatmap-cp','figure.facecolor':'white',
        'savefig.facecolor':'white','axes.unicode_minus':True})
    fig=plt.figure(figsize=(8.4,4.25))
    def axis(x,y,w,h):return fig.add_axes([x/8.4,y/4.25,w/8.4,h/4.25])
    b=axis(1.60,.84,6.00,2.95)
    c=axis(7.72,.89,.12,2.85)

    mesh=b.pcolormesh(np.arange(9)-.5,np.arange(6)-.5,matrix,cmap='Blues',vmin=0,vmax=5.6,
                      shading='flat',rasterized=False,antialiased=False,linewidth=.25,edgecolors='face')
    b.set_xlim(-.5,7.5);b.set_ylim(4.5,-.5)
    b.set_yticks(Y_BOUNDARIES,Y_LABELS);b.set_xticks(np.arange(8),BAND_LABELS,rotation=35,ha='right')
    b.set_yticks(np.arange(5),LABELS,minor=True)
    b.tick_params(axis='y',which='minor',length=0,pad=7,labelsize=10.5,labelcolor='#20252A')
    b.tick_params(axis='y',which='major',pad=4,labelsize=9.5,labelcolor='#555555')
    b.set_xlabel('Final-position ply band',labelpad=8)
    b.set_ylabel("Disconnected player's evaluation (cp)",labelpad=8)
    b.set_title('Board merit × game stage',loc='left',pad=9)
    cell_labels=[]
    for i in range(5):
        for j in range(8):
            v=matrix[i,j]
            ink='white' if v>=3.2 else '#20252A'
            rate_label=b.text(j,i,f'{v:.1f}%',ha='center',va='center',fontsize=11.5,color=ink)
            cell_labels.append((rate_label,i,j))
    colorbar=fig.colorbar(mesh,cax=c,ticks=[0,1,2,3,4,5])
    colorbar.set_label('Kind-draw rate (%)',labelpad=4)
    colorbar.solids.set_rasterized(False)
    # Matching edges prevent hairline seams in vector PDF viewers.
    colorbar.solids.set_edgecolor('face')
    colorbar.solids.set_linewidth(.25)
    c.tick_params(labelsize=10.5,pad=2.5,length=2.5)

    check('No error bars in the raw-rate heatmap',not any(isinstance(x,ErrorbarContainer) for x in b.containers))
    check('Heatmap is vector geometry',not mesh.get_rasterized() and not colorbar.solids.get_rasterized())
    fig.canvas.draw();renderer=fig.canvas.get_renderer()
    bad=[]
    for text in fig.findobj(matplotlib.text.Text):
        if text.get_visible() and text.get_text():
            box=text.get_window_extent(renderer)
            if box.x0<0 or box.y0<0 or box.x1>fig.bbox.width or box.y1>fig.bbox.height:bad.append(text.get_text())
    check('Every label fits the canvas: '+str(bad),not bad)
    for label,i,j in cell_labels:
        box=label.get_window_extent(renderer)
        x0,y0=b.transData.transform((j-.5,i+.5))
        x1,y1=b.transData.transform((j+.5,i-.5))
        if not (x0+2<=box.x0<box.x1<=x1-2 and y0+2<=box.y0<box.y1<=y1-2):
            raise AssertionError(f'Cell label exceeds its cell: {label.get_text()}')
    check('All 40 percentage labels fit within their own cells',len(cell_labels)==40)
    outputs=[];stamp=dt.datetime(2026,9,15,tzinfo=dt.timezone.utc)
    for ext in ['pdf','png','svg']:
        p=ROOT/'figures'/f'{STEM}.{ext}';kwargs={}
        if ext=='pdf':kwargs['metadata']={'Title':'Board merit and game stage: kind-draw rates and centipawn boundaries','Author':'Ravideep Sethi','CreationDate':stamp,'ModDate':stamp}
        elif ext=='png':kwargs['dpi']=300
        else:kwargs['metadata']={'Date':'2026-09-15'}
        fig.savefig(p,**kwargs);outputs.append(p)
    plt.close(fig)
    pdf=PdfReader(outputs[0])
    check('One-page vector PDF with no raster images',len(pdf.pages)==1 and len(pdf.pages[0].images)==0)
    report={'status':'DESERT_PLY_41M_REPRODUCED_OK','checks':CHECKS,'count':len(CHECKS),
        'sample_rows':41534331,'kind_draws':570091,'source_fingerprint':authority['fingerprint'],
        'heatmap_rows':5,'heatmap_columns':8,'model_fits':0,'rate_policy':'Plot stored full-precision rates; count ratios are checked but never substituted.',
        'rounding':'One decimal for heatmap labels, matching the reference.',
        'annotations':'Percentages only; observation counts and bottom notes omitted as requested.',
        'centipawn_ranges':dict(zip(LABELS,CP_RANGES)),
        'y_axis_ticks':dict(zip(Y_LABELS,Y_BOUNDARIES)),
        'y_axis_row_labels':dict(zip(LABELS,range(5))),
        'software':{'python':platform.python_version(),'matplotlib':matplotlib.__version__,'numpy':np.__version__},
        'outputs':[{'file':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in outputs]}
    (ROOT/'verification/VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'DESERT_PLY_41M_REPRODUCED_OK: {len(CHECKS)} checks passed')


if __name__=='__main__':main()
