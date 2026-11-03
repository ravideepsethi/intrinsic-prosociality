from util import *
import pandas as pd
import numpy as np

def compare_previous(run):
    rows=[]
    specs=[('chooser_coefficients.csv',['model','variable'],['coefficient_pp','se_pp','n']),
      ('chooser_contrasts.csv',['model','contrast'],['difference_pp','se_pp','n']),
      ('corrected_dates_coefficients.csv',['model','variable'],['coefficient_pp','se_pp','n']),
      ('corrected_dates_contrasts.csv',['model','contrast'],['difference_pp','se_pp','n']),
      ('diagnostic_kindness_raw_groups.csv',['minimum_opportunities_each_state','diagnostic_group'],['users','patrons','patron_rate_pct']),
      ('raw_matched_patron_comparisons.csv',['sample'],['treated_n','control_n','treated_successes','control_successes','treated_rate_pct','control_rate_pct','gap_pp'])]
    for name,keys,metrics in specs:
        old=pd.read_csv(ROOT/'evidence/old_patron'/name);new=pd.read_csv(run/'report'/name)
        joined=old.merge(new,on=keys,how='outer',suffixes=('_old','_new'),indicator=True,validate='one_to_one')
        for r in joined.to_dict('records'):
            for metric in metrics:
                a=r[metric+'_old'];b=r[metric+'_new']
                rows.append(dict(source=name,key=json.dumps({k:r[k] for k in keys},sort_keys=True),metric=metric,before=a,after=b,change=b-a,comparison_status=r['_merge']))
    table(run/'report/PATRON_BEFORE_AFTER.csv',rows)

def paper_table(run):
    report=run/'report';coef=pd.read_csv(report/'chooser_coefficients.csv');contrast=pd.read_csv(report/'chooser_contrasts.csv')
    raw=pd.read_csv(report/'raw_matched_patron_comparisons.csv')
    main=raw.loc[raw['sample']=='primary_available_outcomes_with_returned_kind_focal'].iloc[0]
    def term(model,variable):
        d=coef.loc[(coef.model==model)&(coef.variable==variable)&(coef.status=='estimated')]
        require(len(d)==1,'Paper-table term absent: '+model+'/'+variable)
        return d.iloc[0]
    rows=[]
    def add(panel,statistic,estimate,units,se=None,cell_se=None,accounts=None):
        rows.append(dict(panel=panel,statistic=statistic,estimate=estimate,units=units,HC1_SE=se,cell_cluster_SE=cell_se,accounts=accounts))
    for s in ('treated','control'):
        add('A',s+'_accounts',int(main[s+'_n']),'accounts')
        add('A',s+'_patrons',int(main[s+'_successes']),'accounts')
        add('A',s+'_patron_rate',main[s+'_rate_pct'],'percent',accounts=int(main[s+'_n']))
    add('A','raw_rate_difference',main.gap_pp,'percentage_points')
    full=term('main_fair_kind_1to3_08_all_controls_HC1','is_kind_role');cr=term('main_fair_kind_all_controls_CR1','is_kind_role')
    add('A','adjusted_association',full.coefficient_pp,'percentage_points',full.se_pp,cr.se_pp,int(full.n))
    for variable in ('ever_kind_fair_state','ever_kind_clearly_worse_state'):
        a=term('diagnostic_horse_race_min4_full_match_cell_fe_HC1',variable);b=term('diagnostic_horse_race_min4_full_match_cell_fe_CR1',variable)
        add('B',variable,a.coefficient_pp,'percentage_points',a.se_pp,b.se_pp,int(a.n))
    a=contrast.loc[contrast.model=='diagnostic_horse_race_min4_full_match_cell_fe_HC1'].iloc[0]
    b=contrast.loc[contrast.model=='diagnostic_horse_race_min4_full_match_cell_fe_CR1'].iloc[0]
    add('B','fair_minus_clearly_worse',a.difference_pp,'percentage_points',a.se_pp,b.se_pp,int(a.n))
    groups=pd.read_csv(report/'diagnostic_kindness_raw_groups.csv')
    groups=groups.loc[groups.minimum_opportunities_each_state==4].set_index('diagnostic_group')
    for name in ('fair_only','both','neither','losing_only'):
        r=groups.loc[name];add('C',name+'_patron_rate',r.patron_rate_pct,'percent',accounts=int(r.users));add('C',name+'_patrons',int(r.patrons),'accounts')
    table(report/'tab_patron.csv',rows)
    lines=[r'\begin{tabular}{llrrr}',r'\toprule',r'Panel & Statistic & Estimate & HC1 SE & Cell SE \\',r'\midrule']
    for r in rows:
        fmt=lambda x: '---' if x is None else f'{x:,.3f}'
        name=r['statistic'].replace('_',r'\_')
        value=f"{r['estimate']:,.0f}" if r['units']=='accounts' else fmt(r['estimate'])
        lines.append(f"{r['panel']} & {name} & {value} & {fmt(r['HC1_SE'])} & {fmt(r['cell_cluster_SE'])} "+r'\\')
    lines.extend([r'\bottomrule',r'\end{tabular}', '% Fixed August profiles; original matching roles/slots; eligibility refreshed under v1.4.1. Broad-acquired check is separate.'])
    (report/'tab_patron.tex').write_text('\n'.join(lines)+'\n')
    save(report/'PATRON_METHOD.json',dict(
      headline='Exact original v1.4.1 roster eligibility and Wave3B1 34-model estimator family, with four corrected-date sensitivity fits.',
      extra='Two clearly labelled min-four state fits on all originally acquired surviving non-author accounts; no new matching.',
      outcomes='Existing August 2026 profile snapshot only; unknown outcomes remain unknown.',
      controls='Fresh behavior, unchanged profile covariates and imputation. Original HC1/CR1 finite-sample conventions retained.',
      optimization='Only needed source files authenticated. One broad account-feature aggregation; retained cache is an exact subset with refreshed group counts. Per-stage and per-model checksummed checkpoints. Sequential numerical fits avoid concurrent large matrices.',
      pending=['tenure-restricted Patron association','recipient badge association','100 fixed-slot rematch sensitivities','opportunity-level Patron models','receipt effect on badge'],
      api_requests=0,engine_evaluations=0,rating_replay_records=0,whole_paper_rerun_complete=False))
