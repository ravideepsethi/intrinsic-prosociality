"""Aggregate results, fixed units, joint contrasts and honest completion status."""
from score_a100_common import *

def placebo_precision(row):
    if not row.get('supported') or row.get('standard_error') is None:return {}
    # Original substantive margin was +/-0.015 pp per fixed score SD .0594.
    margin_native=.015/(100*.0594)
    b,se=row['coefficient'],row['standard_error']
    u.require(se>0 and np.isfinite([b,se]).all(),'Invalid placebo uncertainty')
    lo=b-1.6448536269514722*se;hi=b+1.6448536269514722*se
    tail=lambda z:.5*math.erfc(z/math.sqrt(2))
    return dict(original_margin_pp_per_fixed_0_0594=.015,
        equivalence_margin_pp_per_common_SD=100*COMMON_SD*margin_native,
        nominal_TOST_p=max(tail((b+margin_native)/se),tail((margin_native-b)/se)),
        nominal_90CI_inside_original_margin=lo>-margin_native and hi<margin_native,
        no_sequential_coverage_guarantee=True,causal_exclusion_proved=False)

def export(root,desktop,conf,status,extra,oldfits,plan=(),contrasts=()):
    folder=root/'report';folder.mkdir(exist_ok=True)
    tables={k:[] for k in ('ordinary','entry','balance','joint_balance','receipt_minus_ordinary','added_band_minus_75','certified_receipt','certified75')}
    complete=[]
    for job in plan:
        path=Path(job['output'])
        if not (path/'_DONE.json').exists():continue
        old.prior.check_stage(path,conf,['result.json'])
        result=u.load(path/'result.json');complete.append(path.name)
        for row in result['estimates']:
            v=scaled(row,COMMON_SD);v['new_100percent_run']=True
            if job['kind']=='ordinary' and v.get('outcome')=='y':v.update(placebo_precision(row))
            tables['ordinary' if job['kind']=='ordinary' else 'entry'].append(v)
        tables['balance']+=result['balance'];tables['joint_balance']+=result['joint_balance']
    for job in contrasts:
        path=Path(job['output'])
        if not (path/'_DONE.json').exists():continue
        old.prior.check_stage(path,conf,['result.json'])
        for row in u.load(path/'result.json'):
            tables['receipt_minus_ordinary' if job['label']=='S0_minus_ordinary100' else 'added_band_minus_75'].append(scaled(row,COMMON_SD))
    for (sample,level),path in oldfits.items():
        for row in u.load(path/'result.json')['estimates']:
            v=scaled(row,COMMON_SD) if row.get('estimator') in ('first_stage','reduced_form') else dict(row)
            v.update(reused_certified_result=True,source_configuration=CERTIFIED_CONF,reestimated=False)
            tables['certified_receipt' if sample=='S0' else 'certified75'].append(v)
    if status=='PHASE_100_SCORE_A_COMPLETE':
        u.require(len(complete)==len(plan)==8,'Eight comparison fits required for completion')
        for job in plan+list(contrasts):
            old.prior.check_stage(Path(job['output']),conf,['result.json'])
        u.require(len(contrasts)==6 and len(tables['receipt_minus_ordinary'])==4 and len(tables['added_band_minus_75'])==10,'Joint comparison results incomplete')
        for job in plan:
            rows=u.load(Path(job['output'])/'result.json')['estimates']
            u.require(all(v.get('supported') and v['n']==pq.ParquetFile(job['input']).metadata.num_rows for v in rows),'Unsupported fixed-row comparison; inspect partial report')
    # Two prespecified main diagnostics, corrected together within each cohort/control set.
    for level in LEVELS:
        for sample in ('100','75_100'):
            pair=[v for name,frame,outcome in [('ordinary','O','y'),('entry','F','analysis_entry_90')]
                  for v in tables[name] if v['sample']==frame+sample and v['control_level']==level and v.get('outcome')==outcome]
            if len(pair)==2:r.stats.stats.holm(pair,out='p_Holm_two_main_diagnostics')
    for name,rows in tables.items():r.write_rows(folder,name,rows)
    summary=dict(version='1.0.0',status=status,phase_percent=100,configuration_sha256=conf,
        certified_receipt_configuration=CERTIFIED_CONF,score_definition=DEFINITION,
        common_score_SD=COMMON_SD,primary_controls='X0_ENV_indicator',secondary_controls='X0',
        completed_new_models=len(complete),expected_new_models=8,
        final_fixed_hash_frame=True,new_receipt_IV_estimated=False,
        no_API_requests=True,no_Stockfish=True,generated_scores_treated_as_fixed=True,
        intervals='nominal shared-account OR date CR0; final fixed sample, not sequential confidence sequences',
        earlier_phases_used_to_stop_download=False,abstract_or_title_gate_automatically_cleared=False,
        **extra)
    io=r.io
    io.js(folder/'summary.json',summary)
    lines=['Full Run 2 comparison, current certified Score A',status,'',
        'Read ordinary.csv: O100, y, X0_ENV_indicator. Then receipt_minus_ordinary.csv and entry.csv.',
        'O75_100/F75_100 are the newly added last quarter; certified75.csv holds the previously completed 75% results.',
        'Receipt estimates are reused from the authenticated certified R9; they were not reestimated.',
        'All RF, entry and ordinary slopes use the same frozen Score A SD 0.04979005187533171.',
        'The original +/-0.015 pp margin at score SD 0.0594 is rescaled to identical native-score units, not loosened.',
        'Added-versus-earlier and receipt-versus-ordinary tests use stacked actual accounts and dates; no independent-sample SE assumption.',
        'Entry denotes selection into the research opportunity. A disconnect flag does not establish anger, an opening trap, or motive.',
        'This updates the current all-donor Score A diagnostic. It does not rerun competitive-only-score comparisons, November color mechanics, or main-IV subgroup work.',
        'A small placebo interval does not prove the exclusion restriction. Negative entry associations remain a selection concern.',
        'Final sample is fixed in advance; prior looks have no sequential-coverage guarantee. No automatic abstract/title decision.',
        'Only aggregate results are in this report. Private inputs and row-level influences stay on the Mac.','']
    for name in ('ordinary','entry','receipt_minus_ordinary'):
        for row in tables[name]:
            if row.get('control_level')!='X0_ENV_indicator' or row.get('outcome') not in ('y','analysis_entry_90'):continue
            if row.get('standard_error_pp') is not None:
                lines.append(f"{row.get('sample',row.get('contrast'))}: {row['coefficient_pp']:+.6f} pp/SD; SE {row['standard_error_pp']:.6f}; 95% [{row['ci_low_pp']:+.6f}, {row['ci_high_pp']:+.6f}]")
    (folder/'READ_RESULTS.txt').write_text('\n'.join(lines)+'\n')
    zip_report(folder,desktop,'RUN2_PHASE_100_SCORE_A_REPORT_'+conf[:12])
    return summary
