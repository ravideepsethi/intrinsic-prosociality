#!/usr/bin/env python3
"""Render only the exact tables and labels in FIGURE_SPECIFICATION.md.

Decimal arithmetic is used solely for the explicitly requested +/- 1.96 SE
intervals. Stored intervals are copied. No fitting, interpolation, rate
recalculation, source substitution or extra numerical precision is used.
"""
from __future__ import annotations
import csv
import datetime as dt
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.container import ErrorbarContainer
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.legend_handler import HandlerTuple
from matplotlib.ticker import FormatStrFormatter
import numpy as np
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
NAMES = {2:'fig2_merit_stage_equality',3:'fig3_relative_strength',4:'fig4_time_profile'}
INK,BLUE,GRAY,PALE = '#222629','#345E70','#7C858B','#E4E7E9'
AMBER,PALE_AMBER = '#98621C','#EED9B9'
CHECKS,LEDGER,OUTPUTS = [],{},[]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(name, okay, detail=None):
    if not bool(okay):
        raise AssertionError(f'{name}: {detail}')
    CHECKS.append({'check':name,'status':'PASS','detail':detail})


def decimal(text):
    return Decimal(text.replace('−','-').replace(',','').strip())


def val(text):
    return float(decimal(text))


def ci(est,se):
    e,s=decimal(est),decimal(se)
    return str(e-Decimal('1.96')*s),str(e+Decimal('1.96')*s)


def interval(text):
    low,high=text.strip('[]').split(',')
    return str(decimal(low)),str(decimal(high))


def table_rows(text):
    tables=[]
    current=[]
    for line in text.splitlines()+['']:
        if line.startswith('|'):
            current.append([s.strip() for s in line.strip('|').split('|')])
        elif current:
            tables.append((current[0],current[2:]))
            current=[]
    return tables


def exported(key,rows,columns):
    p=ROOT/'plotdata'/f'{key}.csv'
    with p.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns)
        writer.writeheader();writer.writerows(rows)
    LEDGER[key]={'file':str(p.relative_to(ROOT)),'rows':len(rows),'sha256':sha(p)}
    return rows


def inputs():
    manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())
    for item in manifest['entries']:
        check('Source SHA-256: '+item['file'],sha(ROOT/item['file'])==item['sha256'])
    spec=(ROOT/'FIGURE_SPECIFICATION.md').read_text()
    tables=table_rows(spec)
    def get(first,count):
        found=[rows for headers,rows in tables if headers[0]==first]
        check('Unique specification table: '+first,len(found)==1)
        rows=found[0]
        check('Specification row count: '+first,len(rows)==count)
        return rows
    d={}
    pooled=re.search(r'pooled competitive rate ([0-9.]+)',spec).group(1).rstrip('.')
    check('Competitive reference exactly as specified',pooled=='2.758278')
    d['pooled']=val(pooled)
    d['2a']=exported('fig2_A_board_merit',[
        {'state':s,'rate_pct':v,'competitive_reference_pct':pooled} for s,v in get('Board state (centipawns)',5)
    ],['state','rate_pct','competitive_reference_pct'])
    d['2b']=exported('fig2_B_stage',[
        {'stage':s,'rate_pct':v,'competitive_reference_pct':pooled} for s,v in get('Stage',3)
    ],['stage','rate_pct','competitive_reference_pct'])
    d['2c']=exported('fig2_C_equality_ladder',[
        {'label':s,'estimate_pp':str(decimal(e)),'se':se,'ci_low':ci(e,se)[0],'ci_high':ci(e,se)[1]}
        for s,e,se in get('Row label',4)
    ],['label','estimate_pp','se','ci_low','ci_high'])
    rows=[]
    for gap,e,se,limits in get('Gap centre',23):
        reference=e=='0 (reference)'
        low,high=('','') if reference else interval(limits)
        rows.append({'gap_centre':str(decimal(gap)),'estimate_pp':'0' if reference else str(decimal(e)),
            'se':'' if reference else se,'ci_low':low,'ci_high':high,'reference':reference})
    d['3a']=exported('fig3_A_full_rating_gap_series',rows,['gap_centre','estimate_pp','se','ci_low','ci_high','reference'])
    check('All 22 estimates plus zero reference',[int(r['gap_centre']) for r in rows]==list(range(-550,551,50)))
    check('Reference has no interval',sum(r['reference'] for r in rows)==1 and rows[11]['ci_low']==rows[11]['ci_high']=='')
    d['3b']=exported('fig3_B_same_chooser',[
        {'band':band,'comparison':name,'estimate_pp':str(decimal(e)),'se':se,'accounts':accounts.replace(',',''),
         'ci_low':ci(e,se)[0],'ci_high':ci(e,se)[1]}
        for band,name,e,se,accounts in get('Band (centipawns)',6)
    ],['band','comparison','estimate_pp','se','accounts','ci_low','ci_high'])
    high=d['3b'][4]
    check('Positive imprecise highest-band weaker comparison',val(high['estimate_pp'])>0 and val(high['ci_low'])<0<val(high['ci_high']))
    d['3c1']=exported('fig3_C1_adjacent_levels',[
        {'label':label,'estimate_pp':str(decimal(e)),'se':se,'ci_low':ci(e,se)[0],'ci_high':ci(e,se)[1]}
        for label,e,se in get('Contrast',2)
    ],['label','estimate_pp','se','ci_low','ci_high'])
    d['3c2']=exported('fig3_C2_local_slopes',[
        {'label':label,'estimate':str(decimal(e)),'ci_low':interval(limits)[0],'ci_high':interval(limits)[1]}
        for label,e,limits in get('Quantity',3)
    ],['label','estimate','ci_low','ci_high'])
    d['4a']=exported('fig4_A_receipt_intervals',[
        {'interval':label,'estimate_pp':str(decimal(e)),'se':se,'ci_low':ci(e,se)[0],'ci_high':ci(e,se)[1]}
        for label,e,se in get('Interval',5)
    ],['interval','estimate_pp','se','ci_low','ci_high'])
    for key,head,n in [('4b','Horizon',3),('4c','Partition',2)]:
        d[key]=exported('fig4_B_post_anchor_horizons' if key=='4b' else 'fig4_C_session_partition',[
            {'label':label,'observed_pct':observed,'benchmark_pct':benchmark,
             'percentile_low':interval(limits)[0],'percentile_high':interval(limits)[1]}
            for label,observed,benchmark,limits in get(head,n)
        ],['label','observed_pct','benchmark_pct','percentile_low','percentile_high'])
    check('No numerical table inputs omitted',len(LEDGER)==10)
    return d


def style():
    for path in (ROOT/'fonts').glob('*.ttf'):
        font_manager.fontManager.addfont(str(path))
    plt.rcParams.update({'font.family':'serif','font.serif':['P052 Figures'],
        'font.size':8.6,'axes.labelsize':8.6,'xtick.labelsize':8.4,'ytick.labelsize':8.4,
        'legend.fontsize':8.4,'axes.spines.top':False,'axes.spines.right':False,
        'axes.linewidth':.65,'axes.axisbelow':True,'axes.unicode_minus':True,
        'grid.color':'#E1E4E6','grid.linewidth':.4,'pdf.fonttype':42,'ps.fonttype':42,
        'svg.fonttype':'path','svg.hashsalt':'lichess-234-v101',
        'figure.facecolor':'white','savefig.facecolor':'white',
        'text.color':INK,'axes.labelcolor':INK,'lines.solid_capstyle':'butt'})
    check('Palatino-compatible font found',Path(font_manager.findfont('P052 Figures')).name=='P052Figures-Regular.ttf')


def axes(fig,x,y,w,h):
    fw,fh=fig.get_size_inches()
    return fig.add_axes([x/fw,y/fh,w/fw,h/fh])


def letter(fig,x,y,value):
    fw,fh=fig.get_size_inches()
    fig.text(x/fw,y/fh,value,fontsize=10,fontweight='bold',ha='left',va='top')


def label(fig,x,y,value,**kwargs):
    fw,fh=fig.get_size_inches()
    return fig.text(x/fw,y/fh,value,fontsize=8.6,ha='left',va='top',**kwargs)


def clean(ax,grid=None,forest=False):
    ax.tick_params(length=2.3,width=.6,pad=3)
    if grid:
        ax.grid(axis=grid)
    if forest:
        ax.spines['left'].set_visible(False)
        ax.tick_params(axis='y',length=0)


def pp(axis):
    axis.set_major_formatter(FormatStrFormatter('%.2f'))


def column(rows,key):
    return np.array([val(r[key]) for r in rows])


def hci(ax,rows,y,est='estimate_pp',color=BLUE,marker='o',fill=None,ms=3.3):
    e,lo,hi=[column(rows,key) for key in [est,'ci_low','ci_high']]
    return ax.errorbar(e,y,xerr=[e-lo,hi-e],fmt=marker,ls='none',color=color,
        mfc=color if fill is None else fill,mec=color,ms=ms,elinewidth=.8,capsize=2,capthick=.65)


def visible(ax,rows,lo='ci_low',hi='ci_high',direction='x'):
    limits=ax.get_xlim() if direction=='x' else ax.get_ylim()
    return column(rows,lo).min()>=min(limits) and column(rows,hi).max()<=max(limits)


def save(fig,number):
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    excluded=set()
    for ax in fig.axes:
        for axis in [ax.xaxis,ax.yaxis]:
            low,high=sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks()+axis.get_minor_ticks():
                if not low-1e-10<=tick.get_loc()<=high+1e-10:
                    excluded.update([id(tick.label1),id(tick.label2)])
    outside=[];sizes=[]
    for text in fig.findobj(matplotlib.text.Text):
        if not text.get_visible() or not text.get_text() or id(text) in excluded:
            continue
        box=text.get_window_extent(renderer)
        sizes.append(text.get_fontsize())
        if box.x0<-.5 or box.y0<-.5 or box.x1>fig.bbox.width+.5 or box.y1>fig.bbox.height+.5:
            outside.append(text.get_text())
    check(f'Figure {number}: labels fit the exact six-inch canvas',not outside,outside)
    check(f'Figure {number}: all text >= 8 pt at 5.9-inch manuscript width',min(sizes)*5.9/6>=8,min(sizes)*5.9/6)
    check(f'Figure {number}: no axis titles',all(not ax.get_title() for ax in fig.axes))
    check(f'Figure {number}: no vertical gridlines',all(not any(l.get_visible() for l in ax.get_xgridlines()) for ax in fig.axes))
    stamp=dt.datetime(2026,9,13,tzinfo=dt.timezone.utc)
    for ext in ['pdf','svg','png']:
        path=ROOT/'figures'/f'{NAMES[number]}.{ext}'
        kw={}
        if ext=='pdf':
            kw['metadata']={'Title':NAMES[number],'Author':'Ravideep Sethi','Creator':'make_figures.py v1.0.1','CreationDate':stamp,'ModDate':stamp}
        elif ext=='svg':
            kw['metadata']={'Title':NAMES[number],'Date':'2026-09-13'}
        else:
            kw['dpi']=300
        fig.savefig(path,**kw)
        OUTPUTS.append(path)
    plt.close(fig)


def figure2(d):
    fig=plt.figure(figsize=(6,3.8))
    a=axes(fig,.54,2.04,3.37,1.46)
    b=axes(fig,4.22,2.04,1.71,1.46)
    b.sharey(a)
    c=axes(fig,3.84,.56,1.90,1.02)
    letter(fig,.08,3.71,'A');letter(fig,4.04,3.71,'B');letter(fig,.08,1.68,'C')
    y=column(d['2a'],'rate_pct')
    a.bar(np.arange(5),y,width=.67,color=[BLUE]*3+['#CFD4D7',INK],zorder=3)
    a.set_xticks(np.arange(5),['Clearly\nbetter\n≥ +300','Better\n+101–+299','Roughly\nequal\n−100–+100','Modestly\nworse\n−299–−101','Clearly\nworse\n≤ −300'])
    a.set_ylabel('Kind-draw rate (%)');a.set_ylim(0,5);a.set_xlim(-.6,4.6)
    a.set_yticks([0,1,2,3,4,5]);pp(a.yaxis)
    for x,v in enumerate(y):
        a.text(x,v+.09,f'{v:.2f}',ha='center',va='bottom',fontsize=8.6)
    a.plot([-.28,-.28,2.28,2.28],[4.04,4.24,4.24,4.04],color=INK,lw=.75)
    a.text(1,4.32,'Competitive, 2.76%',ha='center',va='bottom',fontsize=8.6)
    clean(a,'y')
    y=column(d['2b'],'rate_pct')
    b.bar(np.arange(3),y,width=.6,color=BLUE,zorder=3)
    ref=b.axhline(d['pooled'],color=GRAY,lw=.85,ls=(0,(4,3)),zorder=4)
    b.set_xticks(np.arange(3),['Ply 2','Plies\n3–10','After\nply 10']);b.set_xlim(-.6,2.6)
    b.tick_params(labelleft=False)
    for x,v in enumerate(y):
        b.text(x,v+.08,f'{v:.2f}',ha='center',va='bottom',fontsize=8.6,
            bbox={'fc':'white','ec':'none','pad':.15},zorder=5)
    fig.legend([ref],['All competitive positions'],loc='upper right',bbox_to_anchor=(.997,.992),
        frameon=False,handlelength=1.1,handletextpad=.4,borderpad=0)
    clean(b,'y')
    check('Figure 2A/B share exact 0-to-5 rate scale',a.get_ylim()==b.get_ylim()==(0,5))
    check('Figure 2A/B no confidence intervals',not any(isinstance(h,ErrorbarContainer) for ax in [a,b] for h in ax.containers))
    q=d['2c'];positions=np.array([0,.95,2.05,3.35])
    hci(c,q,positions,ms=2.4)
    c.axvline(0,color=GRAY,lw=.7)
    labels=[r['label'] for r in q]
    wrapped=[labels[0],labels[1],labels[2].replace('; ',';\n'),labels[3].replace('and game-stage','and\ngame-stage')]
    c.set_yticks(positions,wrapped);c.set_ylim(3.85,-.45);c.set_xlim(-.5,.3)
    c.set_xticks([-.4,-.2,0,.2]);pp(c.xaxis)
    c.tick_params(axis='y',pad=7)
    c.set_xlabel('Roughly-equal minus better-position\nkindness rate (percentage points)',labelpad=3)
    for yi,row in zip(positions,q):
        c.text(1.115,yi,f"{val(row['estimate_pp']):+.2f}",transform=c.get_yaxis_transform(),ha='right',va='center',fontsize=8.4)
    clean(c,forest=True)
    check('Figure 2C labels verbatim except line wraps',[s.replace('\n',' ') for s in wrapped]==labels)
    check('Figure 2C all intervals visible',visible(c,q))
    save(fig,2)


def figure3(d):
    fig=plt.figure(figsize=(6,3.8))
    a=axes(fig,.66,2.66,5.22,.89)
    b=axes(fig,.99,1.14,1.45,.98)
    c1=axes(fig,4.44,1.80,1.39,.31)
    c2=axes(fig,4.44,.53,1.39,.47)
    letter(fig,.69,3.51,'A');letter(fig,.08,2.32,'B');letter(fig,2.79,2.32,'C')
    q=d['3a'];r=[row for row in q if not row['reference']]
    a.axhline(0,color=GRAY,lw=.7)
    a.plot(column(q,'gap_centre'),column(q,'estimate_pp'),lw=.7,color=BLUE,zorder=2)
    e,lo,hi=[column(r,key) for key in ['estimate_pp','ci_low','ci_high']]
    a.errorbar(column(r,'gap_centre'),e,yerr=[e-lo,hi-e],fmt='o',ls='none',ms=2.8,
        color=BLUE,elinewidth=.7,capsize=1.8,capthick=.65,zorder=3)
    a.scatter([0],[0],marker='D',s=22,facecolors='white',edgecolors=INK,linewidths=.9,zorder=5)
    a.set_xlim(-575,575);a.set_ylim(-2.55,3.55)
    a.set_xticks([-550,-400,-200,0,200,400,550]);a.set_yticks([-2,0,2]);pp(a.yaxis)
    a.set_xlabel('Displayed rating gap: opponent minus chooser (rating points)',labelpad=3)
    a.set_ylabel('Kind-draw rate difference\n(percentage points)',labelpad=3)
    a.yaxis.label.set_y(.42)
    a.legend([Line2D([],[],marker='D',mfc='white',mec=INK,lw=0,ms=4)],['Reference (no interval)'],
        loc='upper left',bbox_to_anchor=(.04,1),frameon=False,borderpad=0,handlelength=1,handletextpad=.4)
    clean(a,'y')
    check('Figure 3A all stored tail intervals visible',visible(a,r,direction='y'))
    q=d['3b']
    for side,color,marker,offset,fill in [('Weaker opponent',BLUE,'o',-.13,BLUE),('Stronger opponent',AMBER,'s',.13,'white')]:
        rows=[r for r in q if r['comparison']==side]
        hci(b,rows,np.arange(3)+offset,color=color,marker=marker,fill=fill)
    bands=list(dict.fromkeys(r['band'] for r in q))
    b.axvline(0,color=GRAY,lw=.7)
    b.set_yticks([0,1,2],bands);b.set_ylim(2.5,-.5);b.set_xlim(-.82,.95)
    b.set_xticks([-.5,0,.5]);pp(b.xaxis)
    b.set_xlabel('Within-account difference\nfrom near-equal opponents\n(percentage points)',labelpad=3)
    b.set_ylabel('Evaluation (centipawns)',labelpad=3)
    clean(b,forest=True)
    fig.legend([Line2D([],[],marker='o',mfc=BLUE,mec=BLUE,lw=0,ms=4),Line2D([],[],marker='s',mfc='white',mec=AMBER,lw=0,ms=4)],
        ['Weaker opponent','Stronger opponent'],loc='lower left',bbox_to_anchor=(.105,.014),
        ncol=1,frameon=False,handlelength=1,handletextpad=.4,labelspacing=.25,borderpad=0)
    check('Figure 3B exact band labels',bands==['[−100, 100)','[100, 300)','[300, 600]'])
    check('Figure 3B all six intervals visible',visible(b,q))
    label(fig,3.08,2.26,'Adjacent displayed-rating levels')
    q=d['3c1'];hci(c1,q,[0,1])
    c1.axvline(0,color=GRAY,lw=.7);c1.set_ylim(1.6,-.6);c1.set_xlim(-.21,.21)
    c1.set_yticks([0,1],[r['label'] for r in q]);c1.set_xticks([-.2,0,.2]);pp(c1.xaxis)
    c1.set_xlabel('Kind-draw rate difference\n(percentage points)',labelpad=3)
    clean(c1,forest=True)
    label(fig,3.08,1.20,'Local draw-payoff slopes')
    q=d['3c2'];hci(c2,q,[0,1,2],est='estimate')
    c2.axvline(0,color=GRAY,lw=.7);c2.set_ylim(2.65,-.65);c2.set_xlim(-.46,.74)
    c2.set_yticks([0,1,2],[r['label'] for r in q]);c2.set_xticks([-.4,0,.4]);pp(c2.xaxis)
    c2.set_xlabel('Percentage points per rating\npoint of signed draw payoff',labelpad=3)
    clean(c2,forest=True)
    check('Figure 3C separate axes and explicit unit titles',not c1.get_shared_x_axes().joined(c1,c2) and c1.get_xlabel()!=c2.get_xlabel())
    check('Figure 3C1 all intervals visible',visible(c1,d['3c1']))
    check('Figure 3C2 stored covariance interval preserved',visible(c2,q) and q[2]['ci_low']=='0.342328' and q[2]['ci_high']=='0.641478')
    save(fig,3)


def benchmark(ax,rows,labels):
    x=np.arange(len(rows))
    for xi,row in zip(x,rows):
        low,high=val(row['percentile_low']),val(row['percentile_high'])
        ax.add_patch(Rectangle((xi+.12-.08,low),.16,high-low,facecolor=PALE_AMBER,edgecolor=AMBER,lw=.65,zorder=2))
    ax.scatter(x+.12,column(rows,'benchmark_pct'),marker='D',s=20,facecolors='white',edgecolors=AMBER,linewidths=.8,zorder=4)
    ax.scatter(x-.12,column(rows,'observed_pct'),marker='o',s=18,color=INK,zorder=4)
    ax.set_xticks(x,labels);ax.set_xlim(-.5,len(rows)-.5);ax.set_ylim(30,55)
    ax.set_yticks([30,40,50,55]);pp(ax.yaxis);clean(ax,'y')
    check('Benchmark range attached only to open marker',not any(isinstance(h,ErrorbarContainer) for h in ax.containers) and len(ax.patches)==len(rows))
    check('Observed and benchmark rates visible',min(column(rows,'percentile_low'))>=30 and max(column(rows,'observed_pct'))<=55)


def figure4(d):
    fig=plt.figure(figsize=(6,2.2))
    a=axes(fig,.65,.82,2.08,1.18)
    b=axes(fig,3.46,.82,1.36,1.18)
    c=axes(fig,4.89,.82,1.04,1.18)
    c.sharey(b)
    letter(fig,.08,2.17,'A');letter(fig,3.00,2.17,'B');letter(fig,4.88,2.17,'C')
    q=d['4a'];e,lo,hi=[column(q,key) for key in ['estimate_pp','ci_low','ci_high']]
    handle=a.errorbar(np.arange(5),e,yerr=[e-lo,hi-e],fmt='o',ls='none',color=BLUE,
        ms=3.5,elinewidth=.8,capsize=2.2,capthick=.7)
    a.axhline(0,color=GRAY,lw=.7)
    a.set_xticks(np.arange(5),['Up to\n6 h','6 h to\n1 d','1 to\n7 d','7 to\n30 d','30 to\n90 d'])
    a.set_xlim(-.5,4.5);a.set_ylim(-.08,3);a.set_yticks([0,1,2,3]);pp(a.yaxis)
    a.set_ylabel('Association\n(percentage points)',labelpad=3);a.set_xlabel('Interval since exposure',labelpad=4)
    clean(a,'y')
    check('Figure 4A vertical categorical estimates with no joined line',handle.lines[0].get_linestyle()=='None' and a.get_xticks().tolist()==[0,1,2,3,4])
    check('Figure 4A all confidence intervals visible',visible(a,q,direction='y'))
    benchmark(b,d['4b'],['Within\n6 h','Within\n24 h','Within\n7 d'])
    benchmark(c,d['4c'],['Same\nsession','Other\nsessions'])
    b.set_ylabel('Grant rate (%)',labelpad=3);c.tick_params(labelleft=False)
    check('Figure 4B/C share the exact 30-to-55 percent axis',b.get_ylim()==c.get_ylim()==(30,55))
    fig.legend([handle],['Estimate and 95% CI'],loc='lower left',bbox_to_anchor=(.055,.025),
        frameon=False,handlelength=1.2,handletextpad=.5,borderpad=0,borderaxespad=0)
    mark=(Rectangle((0,0),1,1,facecolor=PALE_AMBER,edgecolor=AMBER,lw=.65),Line2D([],[],marker='D',mfc='white',mec=AMBER,lw=0,ms=4))
    fig.legend([Line2D([],[],marker='o',color=INK,lw=0,ms=4),mark],
        ['Observed','Conditional benchmark\n(central 95% of reallocations)'],handler_map={tuple:HandlerTuple(ndivide=1)},
        loc='lower left',bbox_to_anchor=(.52,.01),ncol=1,frameon=False,
        handlelength=1.4,handletextpad=.5,labelspacing=.15,borderpad=0,borderaxespad=0)
    save(fig,4)


def main():
    for folder in ['figures','plotdata','verification']:
        (ROOT/folder).mkdir(exist_ok=True)
    style();d=inputs()
    for number,func in [(2,figure2),(3,figure3),(4,figure4)]:
        print(f'Rendering Figure {number}',flush=True);func(d)
    writer=PdfWriter()
    for n,stem in NAMES.items():
        p=ROOT/'figures'/f'{stem}.pdf';reader=PdfReader(p)
        check(f'Figure {n}: one vector PDF page at exactly 6 inches',len(reader.pages)==1 and float(reader.pages[0].mediabox.width)==432 and len(reader.pages[0].images)==0)
        writer.add_page(reader.pages[0])
    writer.add_metadata({'/Title':'Lichess Figures 2, 3, and 4 — specification revision','/Author':'Ravideep Sethi'})
    preview=ROOT/'Figures_2_3_4_Preview.pdf'
    with preview.open('wb') as f:writer.write(f)
    OUTPUTS.append(preview)
    (ROOT/'FIGURE_PROVENANCE.json').write_text(json.dumps({'version':'1.0.1','authority':'FIGURE_SPECIFICATION.md',
        'specification_sha256':sha(ROOT/'FIGURE_SPECIFICATION.md'),'code_sha256':sha(Path(__file__)),
        'panels':LEDGER,'outputs':[{'file':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in OUTPUTS]},indent=2)+'\n')
    (ROOT/'verification/VALIDATION.json').write_text(json.dumps({'status':'FIGURES_234_SPECIFICATION_OK',
        'checks':CHECKS,'count':len(CHECKS),'model_fits':0,'randomizations':0,'rate_recalculations':0,
        'software':{'python':platform.python_version(),'matplotlib':matplotlib.__version__,'numpy':np.__version__}},indent=2)+'\n')
    print(f'FIGURES_2_3_4_REPRODUCED_OK: {len(CHECKS)} checks passed; outputs in {ROOT}/figures')


if __name__=='__main__':main()
