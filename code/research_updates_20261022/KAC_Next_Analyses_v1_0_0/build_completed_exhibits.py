"""Rebuild completed exhibits from included, checksum-bound aggregate archives only."""
import io,json,hashlib,zipfile,textwrap
from pathlib import Path
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'completed'
LABELS={
'primary_competitive_late':'Primary, after ply 10','competitive_all_stages':'All stages',
'competitive_plies11_80':'Plies 11–80','alternative_knots':'Alternative knots',
'competitive_late_clocks':'Plus clocks','competitive_late_rating':'Plus clocks and ratings',
'early_late_interaction':'Early/late interaction, average','full_range_late':'Full evaluation range',
'eight_bins_late':'Eight bins, after ply 10','eight_bins_all':'Eight bins, all stages',
'linear_summary_late':'Linear summary',
'material_competitive_late_base':'Material, competitive: base','material_competitive_late_clocks':'Material, competitive: clocks',
'material_competitive_late_rating':'Material, competitive: ratings','material_full_late_base':'Material, full range: base',
'material_full_late_clocks':'Material, full range: clocks','material_full_late_rating':'Material, full range: ratings',
'evaluation_by_rating_tier':'Evaluation × rating tier, average',
'material_by_rating_tier_competitive':'Material × tier, competitive: average',
'material_by_rating_tier_full':'Material × tier, full range: average',
'joint_eval_material_base':'Evaluation + material: base','joint_eval_material_clocks':'Evaluation + material: clocks',
'joint_eval_material_rating':'Evaluation + material: ratings'}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def archive(name):
    p=ROOT/'evidence'/name
    expected=json.loads((ROOT/'evidence/RESULT_HASHES.json').read_text())[name]
    assert digest(p)==expected,(name,'checksum mismatch')
    z=zipfile.ZipFile(p);assert z.testzip() is None;return z
def csv(z,name):
    names=[n for n in z.namelist() if n.endswith('/'+name)];assert len(names)==1
    return pd.read_csv(io.BytesIO(z.read(names[0])))
def js(z,name):
    names=[n for n in z.namelist() if n.endswith('/'+name)];assert len(names)==1
    return json.loads(z.read(names[0]))
def saveframe(d,name):d.to_csv(OUT/(name+'.csv'),index=False);d.to_parquet(OUT/(name+'.parquet'),index=False)
def effect(r):return f"{r.estimate_pp:.3f} ({r.se:.3f})"
def p_display(p):return '<1e-300' if p==0 else f'{p:.3g}'
def markdown_table(data,headers):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,r))+' |' for r in data])
def escape_latex(s):
    s=str(s).replace('>=','≥').replace('<=','≤')
    for a,b in [('&',r'\&'),('%',r'\%'),('_',r'\_'),('#',r'\#')]:s=s.replace(a,b)
    for a,b in [('<',r'$<$'),('>',r'$>$'),('≥',r'$\geq$'),('≤',r'$\leq$'),('Δ',r'$\Delta$'),('×',r'$\times$'),('−','-')]:s=s.replace(a,b)
    return s
def latex_table(data,headers,columns=None):
    columns=columns or 'l'+'r'*(len(headers)-1)
    return '\n'.join([r'\begin{tabular}{'+columns+'}',r'\toprule',' & '.join(map(escape_latex,headers))+r' \\',r'\midrule']+
                     [' & '.join(map(escape_latex,r))+r' \\' for r in data]+[r'\bottomrule',r'\end{tabular}'])
def fig_merit(p):
    plt.rcParams.update({'font.size':11,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    fig=plt.figure(figsize=(9.4,4.1),layout='constrained');gs=fig.add_gridspec(1,3,width_ratios=[3.8,1.25,3.8])
    ax=fig.add_subplot(gs[0]);tail=fig.add_subplot(gs[1],sharey=ax);mat=fig.add_subplot(gs[2],sharey=ax)
    q=p[(p.model=='primary_competitive_late')&p.cp.between(-100,599)].sort_values('cp')
    ax.plot(q.cp,q.adjusted_percent,color='#173f55',lw=1.8);ax.fill_between(q.cp,q.lo,q.hi,color='#173f55',alpha=.16)
    ax.set(title='A. Engine evaluation',xlabel="Rival's advantage (centipawns)",ylabel='Adjusted grant rate (%)',xlim=(-100,600),ylim=(0,5.4))
    ax.set_xticks([-100,0,100,300,500]);ax.grid(axis='y',alpha=.15)
    q=p[(p.model=='primary_competitive_late')&p.cp.ge(600)]
    tail.errorbar([0,1],q.adjusted_percent,yerr=1.96*q.se,fmt='o',color='#173f55',capsize=3)
    tail.set(title='Tail states',xlim=(-.5,1.5));tail.set_xticks([0,1],['Finite\n≥600','Mate']);tail.tick_params(labelleft=False)
    q=p[p.model=='material_competitive_late_base']
    mat.errorbar(range(8),q.adjusted_percent,yerr=1.96*q.se,fmt='o-',color='#9a572e',capsize=3,lw=1.5)
    mat.set(title='B. Material balance',xlabel="Rival's material advantage (pawn units)",xlim=(-.4,7.4))
    mat.set_xticks(range(8),['≤−2','−1','0','1','2','3','4','≥5']);mat.tick_params(labelleft=False);mat.grid(axis='y',alpha=.15)
    fig.savefig(OUT/'fig_continuous_and_material.pdf');fig.savefig(OUT/'fig_continuous_and_material.png',dpi=180);plt.close(fig)
def make_tables(z,p):
    samples=csv(z,'model_samples.csv');contrasts=csv(z,'planned_contrasts.csv');assert len(samples)==23
    definitions=js(z,'model_definitions.json');kinds={s['name']:s['kind'] for s in definitions}
    rows=[]
    for r in samples.itertuples():
        kind=kinds[r.model];c=contrasts[(contrasts.model==r.model)&(contrasts.group=='population_average')]
        labels=['100 minus 0','300 minus 100','500 minus 300'] if kind not in ['material','bins'] else (
               ['0 minus -1','1 minus 0','>=5 minus 4'] if kind=='material' else c.contrast.tolist()[:3])
        row=dict(model=r.model,label=LABELS[r.model],panel='Material' if kind=='material' else 'Eight bins' if kind=='bins' else 'Evaluation',N=r.N,choosers=r.choosers)
        for i,lab in enumerate(labels,1):
            q=c[c.contrast==lab].iloc[0]
            row.update({f'contrast_{i}':lab,f'estimate_{i}':q.estimate_pp,f'se_{i}':q.se,f'holm_p_{i}':q.holm_p,f'display_{i}':effect(q)})
        rows.append(row)
    frame=pd.DataFrame(rows);saveframe(frame,'A1_23_model_table');saveframe(contrasts,'A1_all_planned_contrasts')
    hetero=contrasts[contrasts.group!='population_average'].copy();saveframe(hetero,'A1_heterogeneity_all_contrasts')
    saveframe(csv(z,'interaction_tests.csv'),'A1_joint_interaction_tests')
    pages=[];tex=[];md=['# A1: all 23 specifications','',
       'Entries are percentage-point contrasts with chooser-clustered standard errors in parentheses. N counts retained opportunities, including singletons and never-granting accounts. 95% intervals and Holm p-values are in the accompanying complete contrast tables. Knots were specified after earlier binned results, before this run.','']
    for panel in ['Evaluation','Eight bins','Material']:
        a=frame[frame.panel==panel];headers=['Specification','N','Δ1 (SE)','Δ2 (SE)','Δ3 (SE)']
        data=[[r.label,f'{r.N:,}',r.display_1,r.display_2,r.display_3] for r in a.itertuples()]
        notes={'Evaluation':'Δ1: +100 minus 0 cp; Δ2: +300 minus +100; Δ3: +500 minus +300.',
               'Eight bins':'First three adjacent-bin differences, starting at [−100, −50). All seven steps are supplied in A1_all_planned_contrasts.',
               'Material':'Δ1: 0 minus −1 pawn; Δ2: +1 minus 0; Δ3: ≥+5 minus +4. All seven steps are supplied in A1_all_planned_contrasts.'}[panel]
        md+=['## '+panel,'',notes,'',markdown_table(data,headers),'']
        pages.append(('A1 — '+panel,headers,data,notes))
        latexdata=pd.DataFrame(data,columns=headers)
        tex+=['\\begin{table}[!htbp]','\\centering\\scriptsize',f'\\caption{{A1: {panel.lower()} specifications}}',
              latex_table(data,headers,'p{0.34\\textwidth}rrrr'),
              '\\par\\smallskip\\begin{minipage}{\\textwidth}\\footnotesize\\raggedright '+escape_latex(notes)+' Standard errors are in parentheses; complete planned contrasts and their Holm adjustments are supplied separately.\\end{minipage}','\\end{table}']
    for model in ['early_late_interaction','evaluation_by_rating_tier','material_by_rating_tier_competitive','material_by_rating_tier_full']:
        a=hetero[hetero.model==model];data=[]
        groupnames=['Ply ≤10','Ply >10'] if model=='early_late_interaction' else ['<1600','1600–1999','2000–2399','≥2400']
        for g in sorted(a.group.unique(),key=int):
            for r in a[a.group==g].itertuples():data.append([groupnames[int(g)],r.contrast,effect(r),p_display(r.holm_p)])
        headers=['Group','Planned contrast','Estimate (SE)','Holm p']
        title=LABELS[model].replace(', average','').replace(': average','')
        md+=['## '+title,'',markdown_table(data,headers),'']
        pages.append((title,headers,data,'Interactions from one model. Holm adjustments are those of the executed A1 design.'))
        tex+=['\\begin{table}[!htbp]','\\centering\\scriptsize',f'\\caption{{{title.replace("×","by")}}}',
              latex_table(data,headers), '\\end{table}']
    (OUT/'A1_appendix_tables.md').write_text('\n'.join(md)+'\n');(OUT/'A1_appendix_tables.tex').write_text('\n'.join(tex)+'\n')
    return pages
def recovered_tables(z):
    b=csv(z,'TENURE_BOARD_RATES.csv');rows=[]
    for i in range(5):
        band=next(x for x in b.tenure.unique() if str(x).startswith(str(i)+'_'))
        x=b[b.tenure==band];lost=x[x.board_bin=='0_clearly_worse'];comp=x[x.board_bin.isin(['2_equal','3_better','4_clearly_better'])]
        m=js(z,f'TENURE_MODEL_tenure_{i}_gradient_full.json');e=m['estimates']['competitive']
        rows.append(dict(tenure=band,competitive_N=int(comp.opportunities.sum()),competitive_grants=int(comp.grants.sum()),competitive_pct=100*comp.grants.sum()/comp.opportunities.sum(),
                 losing_N=int(lost.opportunities.sum()),losing_grants=int(lost.grants.sum()),losing_pct=100*lost.grants.sum()/lost.opportunities.sum(),
                 adjusted_gap_pp=e['coefficient_pp'],cluster_se=e['se_pp'],low=e['ci_low_pp'],high=e['ci_high_pp'],model_N=m['n'],eligible_N=m['eligible_n'],clusters=m['clusters'],
                 inference=m['se'],scope='Existing all-stage 100,000-account screen; model drops chooser singletons.'))
    t=pd.DataFrame(rows);saveframe(t,'B6_recovered_tenure_table')
    patron=[]
    for age in [0,30,90,365]:
        m=js(z,f'PATRON_MODEL_age{age}_min4_pooled.json')
        for name,e in m['estimates'].items():
            patron.append(dict(minimum_opportunity_age_days=age,term=name,N=m['n'],clusters=m['clusters'],**e,inference=m['se'],specification=m['specification']))
    p=pd.DataFrame(patron);saveframe(p,'B7_recovered_patron_tenure_sensitivity')
    notes='''# Recovered tenure and supporter tables

These tables transcribe existing results; they are not new A2 estimates.

The tenure table uses all stages in the original 100,000-account screen, drops chooser singletons, and reports the original full-rank CR1 correction. It therefore does not use the new A1/A2 G/(G−1)-only convention. The raw rates and adjusted model Ns have different denominators. The pooled tenure-interaction test and census rating-cell counts still require work.

The five adjusted gaps in the retrieved source are 1.931, 1.760, 1.879, 1.833 and 2.013 percentage points. The draft's claim that every tenure-band estimate lies between 1.93 and 2.01 is inconsistent with this source. Replace it with the actual range, about 1.76–2.01, and report intervals. Overlapping intervals do not establish identical selectivity across ages.

The supporter age restriction applies to **opportunities used to construct the granting histories**: the account must be at least the stated age at each included opportunity, then have at least four opportunities in each board region. It is not age at the later profile query, and not simply a restriction that the account was already a year old at panel entry.

These supporter fits absorb matching cells and adjust for mean rating, log competitive/losing opportunity counts, and log age at the first panel opportunity. They do **not** use the main paper's full control set. Standard errors are clustered by matching cell (24 cells for the year-plus row), with t-based intervals in the source output; they are not HC1 estimates. The year-plus associations are +0.604 (SE 0.044) and −0.272 (SE 0.046), on 462,754 accounts. Preserve these qualifications if inserting them into the manuscript. A returned-profile failure alone does not identify a moderation closure.
'''
    (OUT/'B6_B7_table_notes.md').write_text(notes)
    data=[[r.tenure,f'{r.competitive_pct:.3f}',f'{r.losing_pct:.3f}',f'{r.adjusted_gap_pp:.3f} ({r.cluster_se:.3f})',f'{r.model_N:,}'] for r in t.itertuples()]
    return [('Recovered tenure screen',['Age band','Competitive %','Losing %','Adjusted gap (SE)','Model N'],data,'Existing all-stage sample. Original full-rank CR1; singletons dropped. Counts/intervals are in the CSV/Parquet.')]
def pdf_tables(pages):
    with PdfPages(OUT/'completed_appendix_tables.pdf') as pdf:
        for title,headers,data,note in pages:
            for start in range(0,len(data),24):
                rows=data[start:start+24];fig,ax=plt.subplots(figsize=(11.7,8.3));ax.axis('off')
                ax.set_title(title+(' (continued)' if start else ''),loc='left',fontsize=15,pad=18)
                tab=ax.table(cellText=rows,colLabels=headers,loc='upper center',cellLoc='left',colLoc='left')
                tab.auto_set_font_size(False);tab.set_fontsize(9);tab.scale(1,1.45)
                tab.auto_set_column_width(list(range(len(headers))))
                for (r,c),cell in tab.get_celld().items():
                    cell.set_linewidth(.2);cell.set_edgecolor('#b6c0c4')
                    if r==0:cell.set_facecolor('#e9eff2');cell.set_text_props(weight='bold')
                fig.text(.07,.055,textwrap.fill(note,135),fontsize=9,va='bottom')
                fig.subplots_adjust(left=.07,right=.95,top=.9,bottom=.15);pdf.savefig(fig);plt.close(fig)
def color(z):
    p=csv(z,'PRIMARY_READOUT.csv');m=csv(z,'planning_MDE.csv');saveframe(p,'B4_completed_color_predictions');saveframe(m,'B4_planning_power')
    (OUT/'B4_status.md').write_text('''# B4 status correction

The corrected prediction run is already complete. The matched post-policy behavioral test remains open.

On the transported all-complete-pre-period target, the refitted curved-utility and framing models predict −0.183 and −0.190 percentage points for the weekly White-minus-Black change; the displayed-gap model predicts zero. Fitted parameters are treated as fixed, with additional probability-calibration assumptions.

The 0.269-point 80% planning MDE applies specifically to eight pre weeks, four hypothetical post weeks and four-week bootstrap blocks. Alternative planning scenarios range from 0.178 to 0.269 points; do not call 0.27 a universal detection limit. The eight-post-week/eight-week-block scenario just exceeds 80% power for some full-awareness predictions. None is a matched event-study estimate, and none identifies player awareness or a share of motives.

Suggested manuscript sentence: “Under the primary pre-policy planning scenario, the corrected payoff models predict changes smaller than the estimated detection threshold; a matched behavioral test of the rating-formula change remains unfinished.”
''')
def main():
    OUT.mkdir(exist_ok=True);z=archive('A1_RESULT.zip');p=csv(z,'adjusted_profiles.csv')
    assert js(z,'COMPLETION.json')['models']==23
    fig_merit(p);pages=make_tables(z,p);pages+=recovered_tables(archive('TENURE_RESULT.zip'));pdf_tables(pages);color(archive('COLOR_PREDICTIONS_RESULT.zip'))
    raw=csv(z,'raw_board_stage_rating.csv');late=raw[raw.stage>=6].groupby('board_bin',as_index=False)[['n','grants']].sum();late['rate_percent']=100*late.grants/late.n;saveframe(late,'A1_raw_late_board_rates')
    print('COMPLETED_EXHIBITS_READY '+str(OUT))
if __name__=='__main__':main()
