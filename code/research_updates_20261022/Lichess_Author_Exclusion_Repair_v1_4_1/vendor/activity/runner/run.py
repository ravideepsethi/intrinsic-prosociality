from __future__ import annotations
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import time
import zipfile
import pandas as pd
from .common import (PACKAGE_ROOT,atomic_json,atomic_text,canonical_json,load_json,sha256_file,
                     utc_now,verify_package_manifest,verify_runtime_dependencies,verify_report_package)
from .source import load_census,verify_baseline,verify_unchanged
from .rates import analyze

PUBLIC_FILES=('state_rates_and_ratios.csv','state_rate_covariance_pct2.csv','activity_ratio_comparisons.csv',
              'SUMMARY.md','ACTIVITY_STATE_RATES_TABLE.tex','RUN_STATUS.json','SOURCE_LINEAGE.json',
              'CONTRACT.json','ENVIRONMENT.json','REFERENCE_REPRODUCTION.json','METHODS.md','INTERPRETATION.md')


def write_csv(path,frame):
    temporary=path.with_suffix('.csv.tmp');frame.to_csv(temporary,index=False);os.replace(temporary,path)


def verify_previous(table):
    results=table.set_index(['scope','weighting'])
    checked=0
    for filename in ('UPSTREAM_estimates.csv','UPSTREAM_activity_tercile_estimates.csv'):
        previous=pd.read_csv(PACKAGE_ROOT/'evidence'/filename)
        for row in previous.itertuples():
            scope='all' if row.scope=='all_state_varying_choosers' else row.scope
            observed=results.loc[(scope,row.estimator)]
            if int(observed.choosers)!=int(row.choosers):raise RuntimeError('Activity-group support differs from the previous run')
            if abs(float(observed.gap_pp)-float(row.estimate_pp))>1e-8:
                raise RuntimeError('State-rate difference does not reproduce prior desert coefficient')
            if abs(float(observed.gap_se_pp)-float(row.se_pp))>1e-8:
                raise RuntimeError('State-rate joint covariance does not reproduce prior gap SE')
            checked+=1
    return dict(status='ALL_PREVIOUS_GAPS_AND_STANDARD_ERRORS_REPRODUCED',checks=checked)


def number(value,digits=3):
    return f'{value:.{digits}f}' if pd.notna(value) else 'undefined'


def report(public,table,cov,comparisons,lineage,contract,environment,baseline,previous,elapsed,*,synthetic=False):
    public.mkdir(parents=True,exist_ok=True)
    for filename,data in [('state_rates_and_ratios.csv',table),('state_rate_covariance_pct2.csv',cov),
                          ('activity_ratio_comparisons.csv',comparisons)]:write_csv(public/filename,data)
    for filename,data in [('SOURCE_LINEAGE.json',lineage),('CONTRACT.json',contract),('ENVIRONMENT.json',environment),
                          ('REFERENCE_REPRODUCTION.json',dict(baseline=baseline,activity_gaps=previous))]:atomic_json(public/filename,data)
    for name in ('METHODS.md','INTERPRETATION.md'):
        atomic_text(public/name,(PACKAGE_ROOT/'docs'/name).read_text())
    description={'original_FE':'Common chooser weights reproducing the original FE gap',
                 'inverse_count_FE':'Common chooser weights reproducing inverse-count FE',
                 'equal_chooser':'Each chooser receives equal weight',
                 'pooled_opportunities':'Raw opportunity-pooled state rates'}
    text='# Activity, state-specific rates and proportional contrasts\n\n'
    if synthetic:text+='SYNTHETIC TEST ONLY.\n\n'
    text+=('The same both-state chooser sample and fixed activity cutoffs (2–6, 7–16, 17+ binary opportunities) '
           'are used throughout. All observed nongranters remain included. RR is the competitive grant rate divided '
           'by the clearly-worse grant rate, calculated from group rates, not individual ratios.\n\n')
    for method in ('equal_chooser','original_FE','inverse_count_FE','pooled_opportunities'):
        text+='## '+description[method]+'\n\n'
        text+='| Group | Overall binary rate (%) | Competitive (%) | Clearly worse (%) | Gap (pp) | RR | RR 95% CI |\n'
        text+='|---|---:|---:|---:|---:|---:|---:|\n'
        for row in table[table.weighting==method].itertuples():
            text+=(f'| {row.scope} | {row.overall_binary_rate_pct:.4f} | {row.competitive_rate_pct:.4f} | '
                   f'{row.worse_rate_pct:.4f} | {row.gap_pp:.4f} | {number(row.risk_ratio)} | '
                   f'[{number(row.risk_ratio_ci_low)}, {number(row.risk_ratio_ci_high)}] |\n')
        selected=comparisons[(comparisons.weighting==method)&(comparisons.comparison=='heavy_versus_light')]
        if len(selected):
            row=selected.iloc[0]
            text+=(f'\nHeavy/light ratio of RRs: {number(row.ratio_of_risk_ratios)}, 95% CI '
                   f'[{number(row.ratio_ci_low)}, {number(row.ratio_ci_high)}]. A value below one indicates '
                   'a smaller proportional contrast in the heavy group under this weighting.\n\n')
    text+=('## Reading the table\n\nAt a fixed risk ratio R, the absolute gap is p_L(R−1), where p_L is the '
           'clearly-worse-state grant rate. A smaller pp gap can therefore coexist with the same or a larger '
           'relative contrast. The table can describe relative state dependence under its explicit weighting; '
           'it does not identify an individual preference parameter or the causal effect of activity.\n\n'
           'The CSV also reports a 50/50 state-standardized rate, (p_F+p_L)/2, so levels can be compared at a common '
           'state composition. Observed overall binary rates retain each chooser\'s actual state mix. Raw pooled '
           'state rates weight choosers differently in each state and should not be presented as the FE estimand.\n\n'
           'This add-on reproduces the previous minimal desert gaps and adds state levels and ratios. It does not '
           'reestimate or certify the paper\'s adjusted specifications. No individual ratio requires dropping a '
           'zero-grant chooser, and no smoothing constant is added. Undefined group ratios are flagged.\n\n'
           f'Elapsed analysis time before report writing: {elapsed:.2f} seconds.\n')
    atomic_text(public/'SUMMARY.md',text)
    tex=[r'\begin{table}[htbp]',r'\centering',r'\caption{Kindness by observed chooser activity.}',
         r'\begin{tabular}{lrrrrr}',r'\toprule',
         r'Activity & Overall (\%) & Competitive (\%) & Clearly worse (\%) & Gap (pp) & Rate ratio \\',r'\midrule']
    groups={'all':'All both-state choosers','light':'Light: 2--6','medium':'Medium: 7--16','heavy':'Heavy: 17+'}
    for row in table[table.weighting=='equal_chooser'].itertuples():
        tex.append(f'{groups[row.scope]} & {row.overall_binary_rate_pct:.3f} & {row.competitive_rate_pct:.3f} & '
                   f'{row.worse_rate_pct:.3f} & {row.gap_pp:.3f} & {number(row.risk_ratio)} '+r'\\')
    tex += [r'\bottomrule',r'\end{tabular}',r'\par\smallskip',
            r'\begin{minipage}{0.97\linewidth}\footnotesize',
            'Each chooser receives equal weight within the stated activity group. Activity counts competitive and '
            'clearly-worse opportunities. Both states must be observed; all zero-grant accounts are retained. '
            'The rate ratio divides the group competitive grant rate by its clearly-worse grant rate. '
            'Overall rates refer to the binary estimating sample and retain each chooser\'s observed state mix.',
            r'\end{minipage}',r'\end{table}']
    atomic_text(public/'ACTIVITY_STATE_RATES_TABLE.tex','\n'.join(tex)+'\n')
    allrow=table[(table.scope=='all')&(table.weighting=='equal_chooser')].iloc[0]
    atomic_json(public/'RUN_STATUS.json',dict(status='SYNTHETIC_TEST_ONLY' if synthetic else 'ACTIVITY_STATE_RATES_COMPLETE',
                completed_utc=utc_now(),analysis_seconds_before_report=elapsed,production_data_computed=not synthetic,
                sample_fingerprint=lineage['sample_fingerprint'],source_census_sha256=lineage['source_census_sha256'],
                contract_sha256=contract['sha256'],choosers=int(allrow.choosers),
                observed_nongranters_retained=int(allrow.observed_nongranters_retained),
                outcome_based_selection=False,individual_ratios_averaged=False,adjusted_paper_models_reestimated=False))


def export(public,transfer):
    transfer.mkdir(parents=True,exist_ok=True)
    stem='POOL_ACTIVITY_STATE_RATES_RESULTS_v100_'+public.name.removeprefix('run_')
    files=[public/name for name in sorted(PUBLIC_FILES)]
    if any(not p.is_file() for p in files):raise RuntimeError('Public report is incomplete')
    atomic_text(public/'SHA256SUMS.txt',''.join(f'{sha256_file(p)}  {p.name}\n' for p in files))
    files.append(public/'SHA256SUMS.txt')
    output=transfer/(stem+'.zip')
    if output.exists():raise RuntimeError('Result ZIP already exists')
    tmp=output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for path in files:z.write(path,stem+'/'+path.name)
    os.replace(tmp,output)
    atomic_text(output.with_suffix('.zip.sha256'),f'{sha256_file(output)}  {output.name}\n')
    return output


def main(args):
    os.umask(0o077);started=time.monotonic()
    package=verify_package_manifest();environment=verify_runtime_dependencies()
    authority,_=verify_report_package();reference=load_json(PACKAGE_ROOT/'authority/REFERENCE.json')
    if not args.project_root.is_dir():raise RuntimeError('Project path not found; connect XT_Pro')
    source=args.source_root or args.project_root/reference['upstream_private_relative_path']
    state=args.project_root/'derived/replication/pool_activity_state_rates_v100_PRIVATE'
    state.mkdir(parents=True,exist_ok=True);lock=(state/'run.lock').open('a+');source_lock=None
    try:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (source/'run.lock').is_file():
            source_lock=(source/'run.lock').open('r');fcntl.flock(source_lock.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
        print('AUTHENTICATING_EXISTING_CHOOSER_CENSUS',flush=True)
        frame,lineage,before=load_census(source,reference,args.threads)
        if lineage['source_census_sha256']!=reference['expected_census_sha256']:
            raise RuntimeError('Census bytes differ from the verified equal-chooser run')
        baseline=verify_baseline(frame,authority,reference)
        definition=reference['activity_definition']
        cuts=(definition['lower_cutoff_inclusive'],definition['middle_cutoff_inclusive'])
        if cuts!=(6,16):raise RuntimeError('Activity cutoffs differ from the previous analysis')
        table,cov,comparisons=analyze(frame,cuts)
        previous=verify_previous(table)
        verify_unchanged(before)
        payload=dict(version='1.0.0',package_manifest_sha256=package['manifest_sha256'],
                     sample_fingerprint=lineage['sample_fingerprint'],source_census_sha256=lineage['source_census_sha256'],
                     activity_cutoffs=list(cuts),ratio='ratio of group competitive and clearly-worse rates',
                     chooser_sample='F>0 and L>0, irrespective of grants',outcome_selection='none')
        contract=dict(payload,sha256=hashlib.sha256(canonical_json(payload).encode()).hexdigest())
        stamp=utc_now().replace('-','').replace(':','')
        public=args.project_root/'output/pool_activity_state_rates_v100'/('run_'+stamp)
        public.mkdir(parents=True,exist_ok=False)
        report(public,table,cov,comparisons,lineage,contract,environment,baseline,previous,time.monotonic()-started)
        output=export(public,args.transfer_root)
        print('ACTIVITY_STATE_RATES_COMPLETE',flush=True)
        print(table[table.weighting=='equal_chooser'][['scope','overall_binary_rate_pct','competitive_rate_pct','worse_rate_pct','gap_pp','risk_ratio']].to_string(index=False),flush=True)
        print('RESULTS_ZIP '+str(output),flush=True)
        print('RESULTS_SHA256 '+str(output.with_suffix('.zip.sha256')),flush=True)
    finally:
        if source_lock:source_lock.close()
        lock.close()


def parser():
    p=argparse.ArgumentParser(description='Activity-group state rates and proportional desert contrasts from the verified chooser census.')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--source-root',type=Path)
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--threads',type=int,choices=range(1,11),default=8)
    return p


if __name__=='__main__':main(parser().parse_args())
