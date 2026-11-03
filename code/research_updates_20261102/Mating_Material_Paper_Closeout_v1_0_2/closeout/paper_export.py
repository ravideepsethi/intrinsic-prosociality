"""Generate reviewable tables from results, never infer a preferred conclusion."""
from closeout_common import *
import csv,math

def csvrows(p):
    with Path(p).open(newline='') as f:return list(csv.DictReader(f))
def f(x,d=3):
    if x is None or x=='':return '--'
    return f'{float(x):.{d}f}'
def interval(r):return '$['+f(r['ci95_low'])+', '+f(r['ci95_high'])+']$'
def texescape(x):return str(x).replace('_',r'\_').replace('%',r'\%').replace('&',r'\&')
def table(title,headers,rows,notes):
    return '\n'.join([r'\begin{table}[htbp]\centering\small',r'\caption{'+title+'}',r'\begin{tabular}{l'+'r'*(len(headers)-1)+'}',r'\toprule', ' & '.join(headers)+r' \\ \midrule',*[' & '.join(map(str,row))+r' \\' for row in rows],r'\bottomrule\end{tabular}',r'\par\smallskip\begin{minipage}{.97\textwidth}\footnotesize '+notes+r'\end{minipage}',r'\end{table}'])

def render(run):
    out=run/'report/manuscript_tables';out.mkdir(parents=True,exist_ok=True)
    ordinary=csvrows(run/'report/ordinary_draw_vs_loss.csv')
    require(len(ordinary)==6 and all(r['inference_status']=='nominal_large_sample' for r in ordinary),'Ordinary comparison has unsupported inference; review rather than mark complete')
    model=csvrows(run/'report/model_estimates.csv');joint=csvrows(run/'report/balance_joint.csv')
    material=[r for r in model if r['sample']=='spaced_material_strict_lt4' and r['term']=='iv_y'];require(len(material)==1,'Material IV estimate missing/duplicated')
    require(material[0]['supported']=='True','Material covariance unsupported')
    require(len(joint)==3 and all(r['supported']=='True' for r in joint),'Recent balance joint covariance unsupported')
    labels={'overlap':'Overlap cells','exact_time_control':'Exact time control','within_recipient':'Within recipient'}
    t1=table('Ordinary draw versus ordinary loss: corrected comparison frame', ['Specification','Estimate','SE',r'95\% interval','N'],
      [[labels[r['specification']],f(r['estimate_pp']),f(r['standard_error_pp']),interval(r),f"{int(r['rows']):,}".replace(',',r'{,}')] for r in ordinary if r['outcome']=='y'],
      r'Percentage points of later granting. The first subsequent competitive choice within 90 days is used; complete windows without a choice are zero. Empirical-cell overlap weights; covariance allows a shared account in any of three roles, with the original HC1 adjustment. This is an observational comparison. The corrected frame uses all-time score support, no receipt cooldown, and 90-day immediate histories and activity; it is not the former 1,290,237-game sample.')
    t2=table('Strict final-material sensitivity',['Sample','Estimate','SE',r'95\% interval','N'],[[r'Spaced, $|M|<4$',f(material[0]['coefficient']),f(material[0]['standard_error']),interval(material[0]),f"{int(material[0]['n']):,}".replace(',',r'{,}')]],r'Instrumented receipt effect in percentage points. Final material is computed from a valid six-field FEN with matching ply count. Pawn, knight, bishop, rook, and queen weights are 1, 3, 3, 5, and 9. Endpoints $-4$ and $+4$ are excluded. The corrected donor score is unchanged; this post-assignment restriction is a sensitivity, not a separate identification design.')
    blabel={'spaced_recent_balance':'Spaced, environment controls','spaced_noenv_recent_balance':'Spaced, no environment controls','repeated_FE_recent_balance':'Repeated recipients, recipient FE'}
    t3=table('Recent-history balance in retained spaced specifications',['Specification',r'$\chi^2$','df',r'$p$'],[[blabel[r['sample']],f(r['chi2'],2),int(r['df']),(r'$<0.001$' if float(r['p_value'])<.001 else f(r['p_value'],3))] for r in joint],r'Seven recent traits measured from 37 to 7 days before index-game start; the spaced model\textquotesingle s 97-to-7-day histories and preceding-30-day activity remain controls. Joint test $p$-values are unadjusted; individual Holm adjustment uses seven tested traits. Shared-account-or-date covariance.')
    for name,body in [('ordinary.tex',t1),('material.tex',t2),('recent_balance.tex',t3)]: (out/name).write_text(body+'\n')
    manuscript=r'''\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{booktabs,textcomp}
\title{Material rerun: remaining results for manuscript integration}
\date{\today}
\begin{document}\maketitle
These tables are generated from the completed closeout results. They do not certify the full paper as complete. Claims about the act versus the result must be assessed against the estimates and intervals below, regardless of their signs or significance.
'''+t1+t2+t3+r'\end{document}'
    (out/'closeout_tables.tex').write_text(manuscript+'\n')
    save(out/'NUMERICAL_LINEAGE.json',dict(ordinary='ordinary_draw_vs_loss.csv',material='model_estimates.csv: sample=spaced_material_strict_lt4, term=iv_y',balance='balance_joint.csv',auto_claim_selection=False,figures_or_manuscript_modified=False))
    save(run/'report/INTEGRATION_CHECKS.json',dict(retained_result_count=len(ordinary)+len(model),ordinary_largest_smd={k:read(run/'report'/('ORDINARY_'+k+'.json'))['largest_absolute_matched_smd'] for k in labels},
      do_not_reuse_old_mechanism_N=1290237,do_not_call_null_without_reading_interval=True,
      noncompetitive_in_stage_gap_clock_models_includes_modestly_worse=True,
      entry_diagnostic_does_not_rule_out_selection=True,manuscript_not_yet_certified=True))
