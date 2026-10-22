from __future__ import annotations
import argparse
import fcntl
import hashlib
import math
import os
from pathlib import Path
import time
import zipfile
import numpy as np
import pandas as pd
from .common import (PACKAGE_ROOT,atomic_json,atomic_text,canonical_json,load_json,sha256_file,
                     utc_now,verify_package_manifest,verify_runtime_dependencies,verify_report_package)
from .source import load_census,verify_baseline,verify_unchanged
from .statistics import (LABELS,inputs,estimate,activity_distribution,activity_terciles,granting_rates)

VERSION='1.0.0'
PUBLIC_FILES=('estimates.csv','paired_differences.csv','estimator_covariance_pp2.csv',
              'activity_decile_weight_shares.csv','activity_top_shares.csv','activity_tercile_estimates.csv',
              'activity_tercile_differences.csv','activity_tercile_support.csv','ACTIVITY_TERCILE_DEFINITION.json',
              'granting_rates.csv','SUMMARY.md','MANUSCRIPT_SNIPPET.tex','RUN_STATUS.json','ENVIRONMENT.json',
              'CONTRACT.json','SOURCE_LINEAGE.json','BASELINE_REPRODUCTION.json','METHODS.md')


def write_csv(path,frame):
    temporary=path.with_suffix('.csv.tmp')
    frame.to_csv(temporary,index=False)
    os.replace(temporary,path)


def analyze(frame):
    n,both,w,balanced,d=inputs(frame)
    weights=np.column_stack((w[both],balanced[both],np.ones(int(both.sum()))))
    models,pairs,covariance=estimate(d,weights)
    if abs(models.loc[models.estimator=='equal_chooser','estimate_pp'].iloc[0]/100-d.mean())>1e-12:
        raise RuntimeError('Equal-chooser coefficient is not the simple mean of within-chooser gaps')
    expected_equal_se=float(d.std(ddof=1)/math.sqrt(len(d))*100)
    if abs(models.loc[models.estimator=='equal_chooser','se_pp'].iloc[0]-expected_equal_se)>1e-10:
        raise RuntimeError('Equal-chooser SE does not match the sample-mean SE')
    # Direct sufficient-statistic WLS normal equations, separate from normalized averages.
    cross=(frame.a.to_numpy(dtype=float)*frame.l.to_numpy()-frame.b.to_numpy(dtype=float)*frame.f.to_numpy())
    cross=np.divide(cross,n,out=np.zeros(len(n)),where=n>0)[both]
    row_weights=(np.ones(len(d)),1/n[both],1/w[both])
    for j,analytic_weight in enumerate(row_weights):
        direct=float((analytic_weight@cross)/(analytic_weight@w[both]))
        if abs(direct-float(models.iloc[j].estimate_pp)/100)>1e-12:
            raise RuntimeError('Weighted chooser-FE normal-equation identity failed: '+LABELS[j])
    all_weights=np.column_stack((w,balanced,both.astype(float)))
    deciles=[];top=[]
    populations=[('all_pool_choosers',np.ones(len(n),dtype=bool),frame.n.to_numpy()),
                 ('all_binary_comparison_choosers',n>0,n),
                 ('state_varying_choosers',both,n)]
    for name,mask,counts in populations:
        decile,tail=activity_distribution(counts[mask],all_weights[mask],name)
        deciles.append(decile);top.append(tail)
    tercile,tercile_pairs,tercile_support,tercile_definition=activity_terciles(n[both],d,weights)
    rates=granting_rates(frame)
    no_grants=(frame.a.to_numpy()[both]+frame.b.to_numpy()[both])==0
    support=dict(choosers=int(both.sum()),observed_nongranters_retained=int(no_grants.sum()),
                 original_FE_nongranter_weight_share=float(weights[no_grants,0].sum()/weights[:,0].sum()),
                 inverse_count_FE_nongranter_weight_share=float(weights[no_grants,1].sum()/weights[:,1].sum()),
                 equal_chooser_nongranter_weight_share=float(no_grants.mean()),
                 exact_equal_chooser_WLS_row_weight='(F_i+L_i)/(F_i*L_i)',
                 inverse_count_WLS_row_weight='1/(F_i+L_i)',
                 outcome_based_regression_selection=False)
    return dict(models=models,pairs=pairs,covariance=covariance,
                deciles=pd.concat(deciles,ignore_index=True),top=pd.concat(top,ignore_index=True),
                tercile=tercile,tercile_pairs=tercile_pairs,tercile_support=tercile_support,
                tercile_definition=tercile_definition,rates=rates,support=support)


def report(public,results,baseline,lineage,contract,environment,elapsed,*,synthetic=False):
    public.mkdir(parents=True,exist_ok=True)
    mapping={'estimates.csv':'models','paired_differences.csv':'pairs',
             'activity_decile_weight_shares.csv':'deciles','activity_top_shares.csv':'top',
             'activity_tercile_estimates.csv':'tercile','activity_tercile_differences.csv':'tercile_pairs',
             'activity_tercile_support.csv':'tercile_support','granting_rates.csv':'rates'}
    for filename,key in mapping.items():write_csv(public/filename,results[key])
    covariance=pd.DataFrame(results['covariance']*10000,columns=LABELS)
    covariance.insert(0,'estimator',LABELS)
    write_csv(public/'estimator_covariance_pp2.csv',covariance)
    atomic_json(public/'ACTIVITY_TERCILE_DEFINITION.json',results['tercile_definition'])
    for filename,value in [('BASELINE_REPRODUCTION.json',baseline),('SOURCE_LINEAGE.json',lineage),
                           ('CONTRACT.json',contract),('ENVIRONMENT.json',environment)]:
        atomic_json(public/filename,value)
    atomic_text(public/'METHODS.md',(PACKAGE_ROOT/'docs/METHODS.md').read_text())
    models=results['models'].set_index('estimator');pairs=results['pairs'].set_index('comparison')
    equal=models.loc['equal_chooser'];inverse=models.loc['inverse_count_FE'];original=models.loc['original_FE']
    diff=pairs.loc['equal_chooser_minus_original_FE']
    inv_diff=pairs.loc['inverse_count_FE_minus_original_FE']
    note=('# Equal chooser and activity-weighting comparison\n\n'
          +('SYNTHETIC TEST ONLY.\n\n' if synthetic else '')
          +f'The comparison retains the same {results["support"]["choosers"]:,} choosers observed in both states, '
          f'including all {results["support"]["observed_nongranters_retained"]:,} with zero grants in the binary comparison.\n\n'
          '| Estimator | Desert gap (pp) | Chooser-cluster SE (pp) | 95% CI (pp) |\n'
          '|---|---:|---:|---:|\n')
    for label,row in models.iterrows():
        note+=f'| {label} | {row.estimate_pp:.6f} | {row.se_pp:.6f} | [{row.ci_low_pp:.6f}, {row.ci_high_pp:.6f}] |\n'
    note+=(f'\nEqual chooser minus original FE: **{diff.estimate_pp:+.6f} pp**, paired SE {diff.se_pp:.6f}, '
           f'95% CI [{diff.ci_low_pp:.6f}, {diff.ci_high_pp:.6f}].\n\n'
           f'Inverse-count FE minus original FE: **{inv_diff.estimate_pp:+.6f} pp**, paired SE {inv_diff.se_pp:.6f}, '
           f'95% CI [{inv_diff.ci_low_pp:.6f}, {inv_diff.ci_high_pp:.6f}].\n\n'
           f'The source-reported original FE SE is {baseline["as_reported_se_pp"]:.9f} pp and is reproduced separately. '
           'The comparison above uses one common chooser-level sandwich correction G/(G-1) over the state-varying '
           'accounts. This differs from the source C7R finite-sample convention; it does not change the original slope. '
           'Difference intervals account for covariance between estimates on the same accounts.\n\n'
           'Equal chooser weights average each observed competitive-minus-clearly-worse grant-rate difference equally. '
           'The 1/n weighted FE regression instead weights chooser differences by p(1-p), removing the activity factor '
           'while retaining state-balance weighting. Here n is the number of binary-comparison opportunities.\n\n'
           'The decile and top-share files report exact identifying-weight shares as well as opportunity shares. '
           'They distinguish full-panel, binary-sample and state-varying-chooser rankings. Count ties at rank '
           'boundaries are allocated fractionally and equally. Activity-tercile slopes use state-varying choosers '
           'and retain whole count ties, so group sizes can differ.\n\n')
    rate=results['rates'].iloc[0]
    note+=(f'Talk denominators: **{rate.opportunity_grant_rate_pct:.4f}% of pool opportunities** are granted; '
           f'**{rate.ever_grant_chooser_pct:.4f}% of choosers** grant at least once '
           f'({int(rate.ever_grant_choosers):,}/{int(rate.choosers):,}). The equal-chooser mean observed grant rate '
           f'is **{rate.equal_chooser_mean_grant_rate_pct:.4f}%**. These are different descriptive summaries.\n\n'
           'This is a robustness analysis of the minimal binary conditional association. It neither reweights '
           'every adjusted specification in the paper nor establishes causal effects or permanent chooser types. '
           'Judge the size and confidence interval of changes; a nonsignificant difference is not proof of equivalence.\n\n'
           f'Elapsed time: {elapsed:.1f} seconds.\n')
    atomic_text(public/'SUMMARY.md',note)
    G=f'{results["support"]["choosers"]:,}'.replace(',',r'{,}')
    snippet=(f'As a sensitivity check on chooser activity, I compare three weightings over the same {G} choosers '
             'observed in both competitive and clearly-worse positions, retaining accounts with no grants. '
             f'The original chooser-FE desert gap is {original.estimate_pp:.4f} percentage points. Weighting each '
             r'observation by $1/n_i$, where $n_i=F_i+L_i$, gives '
             f'{inverse.estimate_pp:.4f} points (chooser-cluster SE {inverse.se_pp:.4f}); weighting each chooser\'s '
             f'observed within-person difference equally gives {equal.estimate_pp:.4f} points '
             f'(SE {equal.se_pp:.4f}). The equal-chooser estimate differs from the original by {diff.estimate_pp:+.4f} '
             f'points, with a paired 95\\% confidence interval [{diff.ci_low_pp:.4f}, {diff.ci_high_pp:.4f}]. '
             'The inverse-count specification removes the activity factor but retains state-balance weights; '
             'the equal-chooser specification gives each contributing account the same weight.\n')
    atomic_text(public/'MANUSCRIPT_SNIPPET.tex',snippet)
    atomic_json(public/'RUN_STATUS.json',dict(status='SYNTHETIC_TEST_ONLY' if synthetic else 'EQUAL_CHOOSER_DESERT_COMPLETE',
                completed_utc=utc_now(),elapsed_seconds=elapsed,production_data_computed=not synthetic,
                source_sample_fingerprint=lineage['sample_fingerprint'],contract_sha256=contract['sha256'],
                source_reference_reproduced=not synthetic,**results['support']))


def export(public,transfer):
    transfer.mkdir(parents=True,exist_ok=True)
    stem='POOL_EQUAL_CHOOSER_DESERT_RESULTS_v100_'+public.name.removeprefix('run_')
    files=[public/name for name in sorted(PUBLIC_FILES)]
    if any(not p.is_file() for p in files):raise RuntimeError('Public report is incomplete')
    atomic_text(public/'SHA256SUMS.txt',''.join(f'{sha256_file(p)}  {p.name}\n' for p in files))
    files.append(public/'SHA256SUMS.txt')
    output=transfer/(stem+'.zip')
    if output.exists():raise RuntimeError('Results ZIP already exists: '+str(output))
    temporary=output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,stem+'/'+p.name)
    os.replace(temporary,output)
    atomic_text(output.with_suffix('.zip.sha256'),f'{sha256_file(output)}  {output.name}\n')
    return output


def main(args):
    os.umask(0o077)
    started=time.monotonic()
    package=verify_package_manifest();environment=verify_runtime_dependencies()
    authority,_=verify_report_package()
    reference=load_json(PACKAGE_ROOT/'authority/REFERENCE.json')
    if not args.project_root.is_dir():raise RuntimeError('Project path not found; connect XT_Pro')
    source=args.source_root or args.project_root/reference['upstream_private_relative_path']
    state=args.project_root/'derived/replication/pool_equal_chooser_desert_v100_PRIVATE'
    state.mkdir(parents=True,exist_ok=True)
    lock=(state/'run.lock').open('a+')
    source_lock=None
    try:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (source/'run.lock').is_file():
            source_lock=(source/'run.lock').open('r')
            fcntl.flock(source_lock.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
        print('AUTHENTICATING_EXISTING_CHOOSER_CENSUS',flush=True)
        frame,lineage,before=load_census(source,reference,args.threads)
        baseline=verify_baseline(frame,authority,reference)
        print('BASELINE_REPRODUCED '+canonical_json(baseline),flush=True)
        payload=dict(version=VERSION,package_manifest_sha256=package['manifest_sha256'],
                     source_census_sha256=lineage['source_census_sha256'],
                     upstream_contract_sha256=lineage['source_contract_sha256'],
                     sample_fingerprint=lineage['sample_fingerprint'],
                     regression_support='F>0 and L>0, irrespective of grants',
                     estimators=['original FE: F*L/(F+L)','inverse-count FE: F*L/(F+L)^2','equal chooser: 1'],
                     inference='joint chooser sandwich with G/(G-1); paired covariance retained',
                     activity_terciles='quantiles among both-state accounts, ties kept together')
        contract=dict(payload,sha256=hashlib.sha256(canonical_json(payload).encode()).hexdigest())
        results=analyze(frame)
        verify_unchanged(before)
        stamp=utc_now().replace('-','').replace(':','')
        public=args.project_root/'output/pool_equal_chooser_desert_v100'/('run_'+stamp)
        public.mkdir(parents=True,exist_ok=False)
        report(public,results,baseline,lineage,contract,environment,time.monotonic()-started)
        output=export(public,args.transfer_root)
        print('EQUAL_CHOOSER_DESERT_COMPLETE',flush=True)
        print(results['models'][['estimator','estimate_pp','se_pp','ci_low_pp','ci_high_pp']].to_string(index=False),flush=True)
        print(results['pairs'][['comparison','estimate_pp','se_pp','ci_low_pp','ci_high_pp']].to_string(index=False),flush=True)
        print('RESULTS_ZIP '+str(output),flush=True)
        print('RESULTS_SHA256 '+str(output.with_suffix('.zip.sha256')),flush=True)
    finally:
        if source_lock:source_lock.close()
        lock.close()


def parser():
    p=argparse.ArgumentParser(description='Equal-chooser and inverse-count FE sensitivity using the verified private census.')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--source-root',type=Path)
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--threads',type=int,choices=range(1,11),default=8)
    return p


if __name__=='__main__':
    main(parser().parse_args())
