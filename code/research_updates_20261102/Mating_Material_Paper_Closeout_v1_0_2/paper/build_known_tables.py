"""Auditable main-table fragments; the archived manuscript stays untouched."""
from pathlib import Path
import csv,json,math,hashlib
ROOT=Path(__file__).resolve().parent;SRC=ROOT/'source_reports';OUT=ROOT/'updated_tables'
MAN={r['path']:r for r in json.loads((ROOT/'SOURCE_REPORTS_MANIFEST.json').read_text())};used=set()
def path(rel):
 p=SRC/rel;key=p.relative_to(ROOT).as_posix()
 assert hashlib.sha256(p.read_bytes()).hexdigest()==MAN[key]['sha256'],key
 used.add(rel);return p
def rows(rel):
 with path(rel).open() as handle:return list(csv.DictReader(handle))
def num(v,d=3):return f'{float(v):.{d}f}'
def count(v):return f'{int(float(v)):,}'.replace(',',r'{,}')
def es(r,e='estimate',se='se',d=3):return num(r[e],d)+' ('+num(r[se],d)+')'
def tab(file,title,headers,data,notes):
 n=len(headers);body='\n'.join([r'\begin{table}[htbp]\centering\small',r'\caption{'+title+'}',r'\begin{tabular}{p{0.48\textwidth}'+'r'*(n-1)+'}',r'\toprule',' & '.join(headers)+r' \\ \midrule',*[' & '.join(map(str,row))+r' \\' for row in data],r'\bottomrule\end{tabular}',r'\par\smallskip\begin{minipage}{.97\textwidth}\footnotesize '+notes+r'\end{minipage}',r'\end{table}'])
 (OUT/(file+'.tex')).write_text(body+'\n');return body

def main():
 OUT.mkdir(exist_ok=True);tables=[]
 census={r['region']:r for r in rows('first_run/tab_sample.csv')}
 tables.append(tab('sample','Corrected material-restricted sample',['Position','Opportunities','Grants','Rate (\\%)'],[[label,count(census[k]['opportunities']),count(census[k]['grants']),num(census[k]['grant_rate_percent'])] for k,label in [('all','All'),('competitive','Competitive'),('clearly_worse','Clearly worse')]],r'Competitive positions have recipient evaluation at least $-100$ cp; clearly worse positions at most $-300$ cp. There are '+count(census['all']['choosers'])+' chooser accounts and '+count(census['all']['granters'])+r' accounts with a grant. The original treatment of 65 recorded chooser-loss/role anomalies is preserved as non-grants; these are not claimed wins.'))
 mainrows=rows('models/tab_main.csv')
 def get(panel,group,contrast):
  matches=[r for r in mainrows if (r['panel'],r['group'],r['contrast'])==(panel,group,contrast)];assert len(matches)==1;return matches[0]
 labels=[('clearly_worse','Clearly worse'),('modestly_worse','Modestly worse'),('roughly_equal','Roughly equal'),('better','Better'),('clearly_better','Clearly better')]
 data=[]
 for i,(key,label) in enumerate(labels):
  step='--' if not i else es(get('A_adjusted_difference','position',key+' minus '+labels[i-1][0]))
  data.append([label,es(get('A_adjusted_rate','position',key)),step])
 data.append(['Clearly better minus clearly worse',es(get('A_adjusted_difference','position','clearly_better minus clearly_worse')),''])
 tables.append(tab('position','Position within chooser',['Position','Adjusted rate (\\%)','Step (pp)'],data,r'Corrected main specification, 41,513,719 opportunities; chooser-clustered standard errors in parentheses. Adjusted rates reset the position and its region interactions.'))
 data=[]
 for b,label in [('5_6','5--6'),('7_8','7--8'),('9_10','9--10'),('11_20','11--20'),('21_40','21--40'),('41_80','41--80'),('81_plus','81 or more')]:
  data.append(['Plies '+label,es(get('B_region','competitive',b+' minus 0_4')),es(get('B_region','noncompetitive',b+' minus 0_4'))])
 data.append(['81 or more minus 41--80',es(get('B_rebound','competitive','81_plus minus 41_80')),es(get('B_rebound','noncompetitive','81_plus minus 41_80'))])
 tables.append(tab('stage','Stage within chooser',['Relative to plies 0--4','Competitive','Noncompetitive'],data,r'Percentage points; chooser-clustered SEs. Noncompetitive means evaluation below $-100$ cp and includes the modestly worse region. The difference between the two late upturns is '+es(get('B_rebound','','competitive minus noncompetitive: 81_plus minus 41_80'))+'.'))
 data=[]
 for contrast,label in [('h(+100) minus h(-100)','$+100$ versus $-100$'),('h(+0) minus h(-100)','Equal versus $-100$'),('h(+100) minus h(+0)','$+100$ versus equal'),('h(+300) minus h(+0)','$+300$ versus equal'),('h(-300) minus h(+0)','$-300$ versus equal')]:
  data.append([label,es(get('C_gap','competitive',contrast)),es(get('C_gap','noncompetitive',contrast))])
 tables.append(tab('gap','Displayed rating gap within chooser',['Opponent minus chooser','Competitive','Noncompetitive'],data,r'Percentage-point differences in the region-specific piecewise linear function; chooser-clustered SEs. Noncompetitive includes modestly worse positions.'))
 p={r['statistic']:r for r in rows('persistence/tab_persistence.csv')}
 order=[('correlation_equal_accounts','Annual competitive-rate correlation'),('correlation_total_opportunity_weighted','Opportunity-weighted correlation'),('second_year_rate_no_prior_grant_pp','Year-two rate, no year-one grant (\\%)'),('second_year_rate_prior_grant_pp','Year-two rate, prior grant (\\%)'),('rate_ratio_prior_vs_none','Rate ratio'),('correlation_C1_C2','Balanced cohort: competitive own-state'),('correlation_L1_L2','Balanced cohort: clearly-worse own-state'),('correlation_C1_L2','Competitive year one to lost year two'),('correlation_L1_C2','Lost year one to competitive year two')]
 tables.append(tab('persistence','Persistence across years',['Statistic','Estimate (SE)','Accounts'],[[label,es(p[k],se='bootstrap_se'),count(p[k]['accounts'])] for k,label in order],r'Account bootstrap, 1,999 resamples. The competitive cohort requires positive opportunities in both years and at least four in total; the balanced-state cohort requires four in each state and year.'))
 patron=rows('patron/tab_patron.csv');pt={r['statistic']:r for r in patron}
 broad=rows('patron/broad_acquired_coefficients.csv');coef={r['variable']:r for r in broad if r['model']=='broad_acquired_min4_full_HC1'}
 data=[['Matched granting accounts',count(pt['treated_accounts']['estimate']),''],['Matched controls',count(pt['control_accounts']['estimate']),''],['Matched adjusted badge association (pp)',es(pt['adjusted_association'],se='HC1_SE'),''],['Broad cohort: competitive granting (pp)',es(coef['ever_kind_fair_state'],e='coefficient_pp',se='se_pp'),''],['Broad cohort: clearly-worse granting (pp)',es(coef['ever_kind_clearly_worse_state'],e='coefficient_pp',se='se_pp'),'']]
 fit=json.loads(path('patron/model_fits/broad_acquired_models/broad_acquired_min4_full_HC1/fit.json').read_text());names=fit['kept_names'];i=names.index('ever_kind_fair_state');j=names.index('ever_kind_clearly_worse_state');V=fit['covariance'];gap=float(coef[names[i]]['coefficient_pp'])-float(coef[names[j]]['coefficient_pp']);se=math.sqrt(V[i][i]+V[j][j]-2*V[i][j]);data.append(['Broad cohort coefficient difference (pp)',num(gap)+' ('+num(se)+')',''])
 raw={r['granting_history']:r for r in rows('patron/broad_acquired_state_raw.csv')}
 for key,label in [('fair_only','Competitive only'),('both','Both states'),('neither','Neither state'),('losing_only','Clearly worse only')]:
  r=raw[key];data.append([label,count(r['patrons'])+' / '+count(r['accounts']),num(r['rate_percent'])+r'\%'])
 tables.append(tab('patron','Granting and the later Patron badge',['Comparison','Estimate (SE) or count','Raw rate'],data,r'Matched Panel A uses 847,680 accounts. The state comparison follows the broader acquired cohort described in the draft: 598,787 accounts, not the narrower 596,569-account retained roster. HC1 SEs. The coefficient-difference SE uses this broad model\textquotesingle s joint covariance. Badge possession is descriptive and can reflect purchased or gifted support.'))
 dr=rows('receipt/tab_dynamics.csv');labels={'primary':'First competitive choice; no choice = zero','censored':'Censor at next competitive disconnection','reach':'Reach a competitive choice','conditional':'Grant conditional on reaching a choice'}
 tables.append(tab('matched_receipt','Matched behavior after receipt',['Outcome','Estimate (SE)','Exposures'],[[labels[r['name']],es(r),count(r['rows'])] for r in dr],r'Percentage points. Original exposure-cell weights and controls rebuilt on corrected histories; SEs clustered by exposure chooser. The primary reweighted control mean is 1.567 percent.'))
 iv=rows('iv_receipt/model_estimates.csv');prim={r['term']:r for r in iv if r['sample']=='uniform_unspaced'}
 labels={'first_stage':'First stage (pp per score unit)','rf_y':'Reduced form (pp per score unit)','iv_y':'IV effect (pp per receipt)','rf_reached':'Later-choice reach (pp per score unit)'}
 tables.append(tab('iv_primary','Primary receipt IV',['Quantity','Estimate (SE)','N'],[[labels[k],es(prim[k],e='coefficient',se='standard_error'),count(prim[k]['n'])] for k in labels],r'9,736,412 exposures from 1,877,413 recipients. Shared-account-or-date CR0 covariance; fixed historical scores. The common score unit is 0.0497900518753, not the current residual SD. The IV 95\% interval is [0.211, 0.432] percentage points. Assignment, exclusion and monotonicity remain maintained assumptions.'))
 document=r'''\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{booktabs,textcomp,placeins}
\title{Corrected main results: manuscript integration tables}
\date{November 1, 2026}
\begin{document}\maketitle
These fragments are generated from the completed, material-corrected result files. The ordinary draw/loss comparison, strict-material sensitivity and recent balance checks are supplied by the closeout run. This is a table integration document, not a completed manuscript.
'''+ '\n\\FloatBarrier\n'.join(tables)+r'\end{document}'
 (OUT/'known_results.tex').write_text(document+'\n')
 (OUT/'TABLE_LINEAGE.json').write_text(json.dumps(dict(sources=sorted(used),patron_broad_contrast=dict(estimate_pp=gap,se_pp=se,accounts=598787)),indent=2)+'\n')
 print('Generated',len(tables),'table fragments from',len(used),'authenticated sources')

if __name__=='__main__':main()
