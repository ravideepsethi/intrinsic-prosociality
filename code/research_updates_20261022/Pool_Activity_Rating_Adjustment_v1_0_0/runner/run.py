from __future__ import annotations
import argparse
import fcntl
import hashlib
from pathlib import Path
import time
import pandas as pd
from .common import (PACKAGE_ROOT,atomic_json,canonical_json,load_json,sha256_file,utc_now,
    verify_package_manifest,verify_runtime_dependencies,verify_report_package,authenticate_sample,compact_sample_lineage)
from .source import load_census,verify_baseline,verify_unchanged
from .features import build_features,join_features
from .rates import analyze as baseline_rates
from .adjustment import analyze_adjustment,RATING_BREAKS,MIN_CELL_CHOOSERS
from .report import write_report,export


def verify_previous(rates):
    previous=pd.read_csv(PACKAGE_ROOT/'evidence/STATE_RATES_state_rates_and_ratios.csv')
    actual=rates.set_index(['scope','weighting'])
    expected=previous.set_index(['scope','weighting'])
    if set(actual.index)!=set(expected.index):raise RuntimeError('Previous state-rate support differs')
    columns=['choosers','competitive_opportunities','worse_opportunities','observed_nongranters_retained',
        'competitive_rate_pct','worse_rate_pct','overall_binary_rate_pct','gap_pp','gap_se_pp',
        'risk_ratio','log_rr_se','risk_ratio_ci_low','risk_ratio_ci_high']
    for key,row in expected.iterrows():
        for col in columns:
            if abs(float(actual.loc[key,col])-float(row[col]))>1e-8:
                raise RuntimeError('Prior result failed to reproduce: '+str(key)+' '+col)
    return dict(status='ALL_16_PREVIOUS_STATE_RATE_ROWS_REPRODUCED',rows=len(previous),checked_columns=columns)


def main(args):
    started=time.monotonic()
    package=verify_package_manifest()
    environment=verify_runtime_dependencies()
    authority,_=verify_report_package()
    reference=load_json(PACKAGE_ROOT/'authority/REFERENCE.json')
    for name,digest in reference['source_evidence_sha256'].items():
        if sha256_file(PACKAGE_ROOT/'evidence'/name)!=digest:raise RuntimeError('Evidence checksum mismatch: '+name)
    if not args.project_root.is_dir():raise RuntimeError('Project not found; connect XT_Pro')
    source=args.source_root or args.project_root/reference['upstream_private_relative_path']
    sample=args.sample_root or args.project_root/authority['default_sample_root_relative']
    private=args.project_root/'derived/replication/pool_activity_rating_adjustment_v100_PRIVATE'
    private.mkdir(parents=True,exist_ok=True)
    lock=(private/'run.lock').open('a+');source_lock=None
    try:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (source/'run.lock').is_file():
            source_lock=(source/'run.lock').open('r')
            fcntl.flock(source_lock.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
        print('VERIFYING_PREVIOUS_CHOOSER_AND_STATE_RATE_RESULTS',flush=True)
        census,census_lineage,before=load_census(source,reference,args.threads)
        if census_lineage['source_census_sha256']!=reference['expected_census_sha256']:
            raise RuntimeError('Census is not the previously verified census')
        baseline=verify_baseline(census,authority,reference)
        base_rates,base_cov,base_comparisons=baseline_rates(census,(6,16))
        reproduction=verify_previous(base_rates)
        print('ALL_PREVIOUS_STATE_RATES_REPRODUCED',flush=True)
        auth=authenticate_sample(sample,verify_hashes=True,hash_workers=args.workers)
        needed={'chooser_user_id','chooser_elo','api_speed','time_control','engine_eval_cp_disconnected',
            'outcome_kind_draw','kind_draw','fair_competitive','clearly_worse','api_status','month'}
        if not needed.issubset(auth['schema']):raise RuntimeError('Required rating source columns are absent')
        panel_before={str(row['path']):(row['path'].stat().st_size,row['path'].stat().st_mtime_ns)
                      for row in auth['month_records']}
        payload=dict(version='1.0.0',package_manifest_sha256=package['manifest_sha256'],
            sample_fingerprint=auth['fingerprint'],source_census_sha256=census_lineage['source_census_sha256'],
            rating='mean chooser_elo across binary opportunities in modal (api_speed,time_control)',
            modal_definition='maximum binary opportunities; ties ascending speed then time_control',
            activity_cutoffs=[6,16],rating_breaks=list(RATING_BREAKS),
            minimum_choosers_per_activity_in_joint_cell=MIN_CELL_CHOOSERS,
            common_support='same joint cells and same choosers for raw/rating/rating-plus-time-control rows',
            target='pooled equal-chooser covariate distribution over retained common support',
            inference='chooser-cluster; conditional on observed joint cell counts and target mix',
            missing_rating='explicit category; no outcome selection',outcome_selection='none')
        contract=dict(payload,sha256=hashlib.sha256(canonical_json(payload).encode()).hexdigest())
        contract_path=private/'CONTRACT.json'
        if contract_path.exists() and load_json(contract_path)!=contract:
            raise RuntimeError('Existing rating-adjustment cache belongs to another contract')
        if not contract_path.exists():atomic_json(contract_path,contract)
        feature_path,feature_receipt,monthly=build_features(auth,private,contract['sha256'],args.workers,
            args.threads,args.worker_memory,args.merge_memory)
        joined,join_receipt=join_features(census,feature_path)
        del census
        print('STANDARDIZING_SAME_CHOOSER_SAMPLE',flush=True)
        tables=analyze_adjustment(joined)
        del joined
        tables.update({'baseline_state_rates.csv':base_rates,'baseline_rate_covariance_pct2.csv':base_cov,
                       'baseline_activity_comparisons.csv':base_comparisons})
        verify_unchanged(before);verify_unchanged(panel_before)
        if sha256_file(feature_path)!=feature_receipt['sha256']:
            raise RuntimeError('Rating features changed during analysis')
        stamp=utc_now().replace('-','').replace(':','')
        public=args.project_root/'output/pool_activity_rating_adjustment_v100'/('run_'+stamp)
        public.mkdir(parents=True,exist_ok=False)
        flow=tables['common_support_flow.csv'].set_index('scope').loc['all']
        metadata={
            'CONTRACT.json':contract,'ENVIRONMENT.json':environment,
            'SOURCE_LINEAGE.json':dict(chooser_census=census_lineage,panel=compact_sample_lineage(auth),
                rating_features=dict(machine_path=str(feature_path),**feature_receipt),
                raw_panel_hashes_recomputed=True,source_inputs_unchanged=True,network_requests=0),
            'REFERENCE_REPRODUCTION.json':dict(minimal_FE=baseline,state_rates=reproduction,feature_join=join_receipt),
            'MONTHLY_FEATURE_SCAN.json':dict(months=monthly),
            'RUN_STATUS.json':dict(status='ACTIVITY_RATING_ADJUSTMENT_COMPLETE',completed_utc=utc_now(),
                production_data_computed=True,elapsed_seconds_before_report=time.monotonic()-started,
                sample_fingerprint=auth['fingerprint'],contract_sha256=contract['sha256'],
                full_both_state_choosers=int(flow.full_choosers),common_support_choosers=int(flow.common_support_choosers),
                common_observed_nongranters=int(flow.common_observed_nongranters),outcome_based_selection=False,
                paper_adjusted_specifications_reestimated=False,individual_ratios_averaged=False),
        }
        write_report(public,tables,metadata)
        output=export(public,args.transfer_root,stamp)
        print('ACTIVITY_RATING_ADJUSTMENT_COMPLETE',flush=True)
        print(tables['rating_activity_summary.csv'][['scope','choosers','rating_mean','rating_median']].to_string(index=False),flush=True)
        pairs=tables['standardized_activity_comparisons.csv']
        print(pairs.loc[pairs.comparison=='heavy_versus_light',
            ['method','ratio_of_risk_ratios','ratio_ci_low','ratio_ci_high']].to_string(index=False),flush=True)
        print('RESULTS_ZIP '+str(output),flush=True)
        print('RESULTS_SHA256 '+str(output.with_suffix('.zip.sha256')),flush=True)
    finally:
        if source_lock:source_lock.close()
        lock.close()


def parser():
    p=argparse.ArgumentParser(description='Activity/rating composition and standardized desert contrasts.')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--source-root',type=Path)
    p.add_argument('--sample-root',type=Path)
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,choices=range(1,11),default=4)
    p.add_argument('--threads',type=int,choices=range(1,11),default=8)
    p.add_argument('--worker-memory',default='1GB')
    p.add_argument('--merge-memory',default='4GB')
    return p


if __name__=='__main__':main(parser().parse_args())
