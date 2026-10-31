from util import *
import pandas as pd
import numpy as np

def report_rows(run,rows):
    frame=pd.DataFrame(rows)
    table(run/'report/matched_models.csv',frame)
    order=['primary','censored','reach','conditional'];main=frame.set_index('name').loc[order].reset_index()
    table(run/'report/tab_dynamics.csv',main)
    table(run/'report/tab_app_intervals.csv',frame[frame.name.str.startswith('decay_')])
    hours=frame[frame.hour.notna()].copy()
    hours['paper_se']=np.where(hours.name.str.startswith('primary_'),hours.se_chooser_or_hour_CR0,hours.se)
    hours['paper_covariance']=np.where(hours.name.str.startswith('primary_'),'chooser OR hour CR0 (Uniform90 matched source)','chooser CR1 (original companion source)')
    table(run/'report/tab_app_receipt_hours.csv',hours)
    table(run/'report/tab_app_receipt_sensitivities.csv',frame[frame.name.isin(['conditional_later_controls','any_later_grant','later_receipt_count'])])
    old=pd.read_csv(ROOT/'evidence/previous_receipt/a1_models.csv')
    old_intervals=pd.read_csv(ROOT/'evidence/previous_receipt/a1_decay.csv')
    old_hours=pd.read_csv(ROOT/'evidence/previous_receipt/receipt_hours.csv')
    mapping={'primary':'first_choice_zero_coded_90d','reach':'mandatory_reach_companion','conditional':'primary_total_path_conditional_choice',
      'conditional_later_controls':'mandatory_state_conditioned_conditional_choice','any_later_grant':'mandatory_unconditional_kind_companion',
      'later_receipt_count':'natural_path_crossover_count'}
    comparison=[]
    for r in rows:
        prior=None
        if r['name'] in mapping:
            found=old[old.estimand==mapping[r['name']]]
            if len(found)==1:prior=found.iloc[0]
        elif r['name'].startswith('decay_'):
            found=old_intervals[old_intervals.outcome==r['name']]
            if len(found)==1:prior=found.iloc[0]
        elif r['hour']:
            outcome={'primary':'first_choice_zero_coded','reach':'reach_90d','conditional':'conditional_first_choice'}[r['name'].split('_')[0]]
            spec='exposure_start_hour' if r['hour']=='start' else 'exposure_last_move_hour'
            found=old_hours[(old_hours.outcome==outcome)&(old_hours.specification==spec)]
            if len(found)==1:prior=found.iloc[0]
        if prior is not None:
            b=float(prior['coefficient_percentage_points'] if r['binary'] else prior['coefficient'])
            se=float(prior['standard_error_percentage_points'] if r['binary'] else prior['standard_error'])
            comparison.append(dict(model=r['name'],old_rows=int(prior['rows']),new_rows=r['rows'],old_estimate=b,new_estimate=r['estimate'],change=r['estimate']-b,old_se=se,new_se=r['se'],units=r['units']))
    table(run/'report/RECEIPT_BEFORE_AFTER.csv',comparison)
    labels={'primary':'Grant at first later choice; no choice coded zero','censored':'Same, before next competitive disconnection',
      'reach':'Reach a competitive choice within 90 days','conditional':'Grant at first later choice, conditional on reaching one'}
    lines=['% Generated from checked model outputs; units: percentage points.',r'\begin{tabular}{lrrr}',r'\toprule',r'Outcome & Estimate & SE & Exposures \\',r'\midrule']
    for r in main.to_dict('records'):lines.append(f"{labels[r['name']]} & {r['estimate']:.3f} & {r['se']:.3f} & {r['rows']:,} \\\\")
    lines += [r'\bottomrule',r'\end{tabular}'];(run/'report/tab_dynamics.tex').write_text('\n'.join(lines)+'\n')
    save(run/'report/METHOD.json',dict(scope='Matched receipt main table, five interval rows, original A1 companions and six exact-hour sensitivities',
      exposure_selection='Rebuilt from material-restricted main panel; earliest competitive non-tournament event by start/archive/game within recipient name. Rank before excluding historical non-arm outcomes.',
      first_pair='Equality of exposure start and earliest positive timestamp of unordered pair in the original all-game chronology. Only these factual pair dates are reused from the old certified recipient file.',
      weights='Recomputed over the fresh full candidate cohort before the complete-follow-up restriction, first pair and grant-or-claim only; >=5 grants and >=20 claims per original cell; treated weight 1, control weight cell grants/claims.',
      outcomes='Original matched last-move anchor, strict later timestamp, <=90 days, original tie ordering; complete follow-up uses MAX(last-move timestamp) from the source panel as in the original core; no new different-opponent or game-start restriction.',
      censor='Keep every baseline exposure; count a grant only if first later competitive choice strictly precedes next competitive disconnection.',
      intervals='First choice within each interval, allowing one exposure in several intervals; no choice in interval is excluded, not zero-coded.',
      controls='Original 13 exposure-game variables, squared standardized terms and supported missingness indicators, cell and month FE. Later controls only in the marked sensitivity.',
      covariance='Original exposure-chooser cluster correction. All hour models additionally report chooser-or-hour CR0. The zero-coded hour rows use that CR0 as paper_se, following the Uniform90 matched source; conditional/reach hour rows use the original companion chooser correction. Both are retained explicitly.',
      optimization='Prune unused A3/encouragement SQL branches; reuse authenticated factual pair dates; project only three chronology columns for new pairs; checkpoint each file/model; bounded numerical crossproducts; exact Schur hour projection.',
      pending=['All IV score/reference/support/exposure reconstructions and placebos','A3 engagement, preliminary encouragement and overlap diagnostics','Conditional both-exposure-and-later-hour sensitivity','Other paper families in DOWNSTREAM_STATUS.csv']))
