from __future__ import annotations
import argparse
import concurrent.futures as cf
import fcntl
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time
import zipfile
import duckdb
import numpy as np
import pandas as pd
from .common import (PACKAGE_ROOT, atomic_json, atomic_text, canonical_json, load_json,
                     sha256_file, utc_now, authenticate_sample, compact_sample_lineage,
                     verify_package_manifest, verify_runtime_dependencies)

FIELDS = ['n', 'f', 'l', 'k', 'a', 'b']
VERSION = '1.0.0'
PUBLIC_FILES = ['chooser_opportunity_summary.csv','opportunities_per_chooser_distribution.csv',
                'singleton_invariance.csv','DESERT_SUPPORT.json','SAMPLE_LINEAGE.json','CONTRACT.json',
                'REFERENCE_REPRODUCTION.json','DESIGN_I_COUNT_PARAGRAPH.txt','DESIGN_I_REPLACEMENT.tex',
                'SUMMARY.md','RUN_STATUS.json','ENVIRONMENT.json']


def literal(value):
    return "'"+str(value).replace("'", "''")+"'"


def connection(memory='2GB', threads=1, spill=None):
    con=duckdb.connect()
    con.execute(f'SET threads={int(threads)}')
    con.execute(f'SET memory_limit={literal(memory)}')
    con.execute('SET preserve_insertion_order=false')
    if spill:
        Path(spill).mkdir(parents=True,exist_ok=True)
        con.execute(f'SET temp_directory={literal(spill)}')
    return con


def csv_write(path, frame):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.csv.tmp')
    frame.to_csv(temporary,index=False)
    os.replace(temporary,path)


def month_census(task):
    root=Path(task['cache'])
    root.mkdir(parents=True,exist_ok=True)
    month=task['month']
    output=root/(month+'.parquet')
    receipt=root/(month+'.json')
    if receipt.exists():
        saved=load_json(receipt)
        if saved['contract']!=task['contract'] or saved['source_sha256']!=task['expected_sha256']:
            raise RuntimeError('Monthly census authority mismatch: '+month)
        if not output.exists() or sha256_file(output)!=saved['cache_sha256']:
            raise RuntimeError('Monthly census checksum mismatch: '+month)
        return dict(month=month,resumed=True)
    con=connection(task.get('memory','2GB'),spill=root/'spill'/month)
    try:
        con.execute('''CREATE TEMP TABLE p AS SELECT month,chooser_user_id AS chooser,
            CAST(outcome_kind_draw AS INTEGER) AS y,CAST(kind_draw AS INTEGER) AS y_alias,
            engine_eval_cp_disconnected AS evaluation,
            fair_competitive AS fair_alias,clearly_worse AS worse_alias,api_status
            FROM read_parquet(?,hive_partitioning=false)''',[task['path']])
        qa=con.execute('''SELECT count(*) AS rows,
            count(*) FILTER (WHERE chooser IS NULL) AS missing_chooser,
            count(*) FILTER (WHERE y IS NULL OR y NOT IN (0,1)) AS invalid_outcome,
            count(*) FILTER (WHERE y IS DISTINCT FROM y_alias) AS outcome_mismatch,
            count(*) FILTER (WHERE evaluation IS NULL) AS missing_evaluation,
            count(*) FILTER (WHERE fair_alias IS DISTINCT FROM (evaluation>=-100)) AS fair_mismatch,
            count(*) FILTER (WHERE worse_alias IS DISTINCT FROM (evaluation<=-300)) AS worse_mismatch,
            count(*) FILTER (WHERE api_status IS DISTINCT FROM 'timeout') AS non_timeout
            FROM p''').df().iloc[0].to_dict()
        qa={k:int(v) for k,v in qa.items()}
        if qa['rows']!=task['rows'] or any(v for k,v in qa.items() if k!='rows'):
            raise RuntimeError('Source QA failed: '+month+' '+canonical_json(qa))
        if con.execute('SELECT DISTINCT month FROM p').fetchall()!=[(month,)]:
            raise RuntimeError('Month field differs from authenticated inventory: '+month)
        temporary=output.with_suffix('.parquet.tmp')
        con.execute(f'''COPY (SELECT chooser, count(*)::BIGINT AS n,
            count(*) FILTER (WHERE evaluation>=-100)::BIGINT AS f,
            count(*) FILTER (WHERE evaluation<=-300)::BIGINT AS l,
            sum(y)::BIGINT AS k,
            coalesce(sum(y) FILTER (WHERE evaluation>=-100),0)::BIGINT AS a,
            coalesce(sum(y) FILTER (WHERE evaluation<=-300),0)::BIGINT AS b
            FROM p GROUP BY chooser) TO {literal(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD)''')
        os.replace(temporary,output)
        atomic_json(receipt,dict(month=month,contract=task['contract'],source_sha256=task['expected_sha256'],
                                cache_sha256=sha256_file(output),qa=qa,completed_utc=utc_now()))
        return dict(month=month,resumed=False,rows=qa['rows'])
    finally:
        con.close()


def merge_census(private, contract, threads=8, memory='4GB'):
    output=private/'chooser_counts_private.parquet'
    receipt=private/'chooser_counts_receipt.json'
    if receipt.exists():
        saved=load_json(receipt)
        if saved['contract']!=contract or not output.exists() or sha256_file(output)!=saved['sha256']:
            raise RuntimeError('Merged chooser census authority/checksum mismatch')
        return output
    paths=sorted(str(p) for p in (private/'monthly').glob('????-??.parquet'))
    con=connection(memory,threads,private/'merge_spill')
    try:
        sums=','.join(f'sum({field})::BIGINT AS {field}' for field in FIELDS)
        temporary=output.with_suffix('.parquet.tmp')
        con.execute(f'''COPY (SELECT chooser,{sums} FROM read_parquet(?,hive_partitioning=false)
            GROUP BY chooser ORDER BY chooser) TO {literal(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD)''',[paths])
        os.replace(temporary,output)
        atomic_json(receipt,dict(contract=contract,sha256=sha256_file(output),completed_utc=utc_now()))
        return output
    finally:
        con.close()


def distribution(values, name):
    values=np.asarray(values,dtype=np.int64)
    values=values[values>0]
    if not len(values):
        raise ValueError('Empty support: '+name)
    quantiles=np.quantile(values,[.25,.5,.75,.9,.95,.99],method='linear')
    nobs=int(values.sum())
    summary=dict(sample=name,choosers=int(len(values)),opportunities=nobs,
                 mean=float(values.mean()),median=float(quantiles[1]),
                 choosers_one=int((values==1).sum()),choosers_more_than_one=int((values>1).sum()),
                 singleton_chooser_share=float((values==1).mean()),
                 singleton_opportunity_share=float((values==1).sum()/nobs),
                 p25=float(quantiles[0]),p75=float(quantiles[2]),p90=float(quantiles[3]),
                 p95=float(quantiles[4]),p99=float(quantiles[5]),maximum=int(values.max()))
    counts,frequencies=np.unique(values,return_counts=True)
    pmf=pd.DataFrame(dict(sample=name,opportunities_per_chooser=counts,choosers=frequencies,
                          opportunities=counts*frequencies))
    return summary,pmf


def calculate(frame):
    n=frame.n.to_numpy(dtype=np.int64)
    f=frame.f.to_numpy(dtype=np.int64)
    l=frame.l.to_numpy(dtype=np.int64)
    a=frame.a.to_numpy(dtype=float)
    b=frame.b.to_numpy(dtype=float)
    contrast_n=f+l
    eligible=contrast_n>0
    both=(f>0)&(l>0)
    weights=np.divide(f.astype(float)*l,contrast_n,out=np.zeros(len(n)),where=eligible)
    cross=np.divide(a*l-b*f,contrast_n,out=np.zeros(len(n)),where=eligible)
    denominator=float(weights.sum())
    if denominator<=0 or int(both.sum())<2:
        raise ValueError('Insufficient within-chooser state variation')
    rows=[]
    definitions=[('all_contrast_accounts',eligible),('drop_contrast_singletons',contrast_n>1),
                 ('state_varying_accounts',both)]
    for name,mask in definitions:
        N=int(contrast_n[mask].sum())
        G=int(mask.sum())
        beta=float(cross[mask].sum()/weights[mask].sum())
        score=cross[mask]-beta*weights[mask]
        variance=float(score@score/(weights[mask].sum()**2))
        if G<=1 or N-G-1<=0:
            raise ValueError('Insufficient regression degrees of freedom')
        corrections={'CR0':1.0,'nested_chooser_CR1':G/(G-1),
                     'C7R_reported_CR1':G/(G-1)*(N-1)/(N-G-1)}
        for convention,q in corrections.items():
            se=math.sqrt(variance*q)
            rows.append(dict(sample=name,covariance=convention,rows=N,chooser_clusters=G,
                             informative_choosers=int(both[mask].sum()),estimate_pp=100*beta,
                             se_pp=100*se,ci_low_pp=100*(beta-1.959963984540054*se),
                             ci_high_pp=100*(beta+1.959963984540054*se),
                             p_normal=math.erfc(abs(beta/se)/math.sqrt(2)) if se>0 else None,
                             finite_sample_correction=q))
    results=pd.DataFrame(rows)
    def row(sample,covariance):
        return results[(results['sample']==sample)&(results.covariance==covariance)].iloc[0]
    kept=row('all_contrast_accounts','C7R_reported_CR1')
    dropped=row('drop_contrast_singletons','C7R_reported_CR1')
    if abs(kept.estimate_pp-dropped.estimate_pp)>1e-9:
        raise RuntimeError('Unexpected singleton coefficient difference')
    minimal=float(cross.sum()/denominator)
    # Independent weighted-mean identity, restricted only by state variation.
    individual_gap=a[both]/f[both]-b[both]/l[both]
    identity=float(np.average(individual_gap,weights=weights[both]))
    if abs(minimal-identity)>1e-12:
        raise RuntimeError('Within-coefficient weighted-contrast identity failed')
    no_grant=(a+b)==0
    support=dict(contrast_rows=int(contrast_n.sum()),contrast_choosers=int(eligible.sum()),
                 choosers_seen_in_both_states=int(both.sum()),
                 opportunities_from_both_state_choosers=int(contrast_n[both].sum()),
                 fair_opportunities_from_both_state_choosers=int(f[both].sum()),
                 worse_opportunities_from_both_state_choosers=int(l[both].sum()),
                 contrast_singleton_choosers=int((contrast_n==1).sum()),
                 full_panel_accounts_absent_from_binary_contrast=int((contrast_n==0).sum()),
                 only_fair_choosers=int(((f>0)&(l==0)).sum()),
                 only_worse_choosers=int(((l>0)&(f==0)).sum()),
                 state_varying_choosers_with_no_grant_in_contrast=int((both&no_grant).sum()),
                 share_identifying_weight_no_grant_in_contrast=float(weights[no_grant].sum()/denominator),
                 identifying_weight_sum=denominator,
                 weight_effective_choosers=float(denominator**2/(weights@weights)),
                 weighted_difference_identity_error_pp=100*abs(identity-minimal),
                 coefficient_difference_after_singleton_drop_pp=float(dropped.estimate_pp-kept.estimate_pp),
                 coefficient_same_at_4_decimal_pp=format(kept.estimate_pp,'.4f')==format(dropped.estimate_pp,'.4f'),
                 reported_C7R_se_same_at_4_decimal_pp=format(kept.se_pp,'.4f')==format(dropped.se_pp,'.4f'),
                 reported_C7R_se_before_pp=float(kept.se_pp),reported_C7R_se_after_pp=float(dropped.se_pp),
                 note='No regression conditions on whether a chooser ever grants. Zero observed grants are not zero causal effects.')
    summaries,pmfs=[],[]
    for name,values in [('all_pool_opportunities',n),('competitive_or_clearly_worse',contrast_n),('competitive_only',f)]:
        summary,pmf=distribution(values,name)
        summaries.append(summary);pmfs.append(pmf)
    return pd.DataFrame(summaries),pd.concat(pmfs,ignore_index=True),support,results


def verify_reference(results,support,authority):
    reference=authority['current_minimal_desert_model']
    actual=results[(results['sample']=='all_contrast_accounts')&(results.covariance=='C7R_reported_CR1')].iloc[0]
    for name in ('rows','chooser_clusters'):
        if int(actual[name])!=int(reference[name]):
            raise RuntimeError('Returned C7R reference count mismatch: '+name)
    for name in ('estimate_pp','finite_sample_correction'):
        if abs(float(actual[name])-float(reference[name]))>1e-7:
            raise RuntimeError('Returned C7R reference mismatch: '+name)
    if abs(float(actual.se_pp)-float(reference['se_cr1_pp']))>1e-7:
        raise RuntimeError('C7R reference clustered SE did not reproduce')
    return dict(status='CURRENT_C7R_REFERENCE_REPRODUCED',reference_estimate_pp=float(reference['estimate_pp']),
                reproduced_estimate_pp=float(actual.estimate_pp),reproduced_se_pp=float(actual.se_pp))


def report(public,summaries,pmf,support,results,lineage,contract,elapsed,reference_check,*,synthetic=False):
    public.mkdir(parents=True,exist_ok=True)
    csv_write(public/'chooser_opportunity_summary.csv',summaries)
    csv_write(public/'opportunities_per_chooser_distribution.csv',pmf)
    csv_write(public/'singleton_invariance.csv',results)
    atomic_json(public/'DESERT_SUPPORT.json',support)
    atomic_json(public/'SAMPLE_LINEAGE.json',lineage)
    atomic_json(public/'CONTRACT.json',contract)
    atomic_json(public/'REFERENCE_REPRODUCTION.json',reference_check)
    allrow=summaries[summaries['sample']=='all_pool_opportunities'].iloc[0]
    contrast=summaries[summaries['sample']=='competitive_or_clearly_worse'].iloc[0]
    c7r=results[(results['sample']=='all_contrast_accounts')&(results.covariance=='C7R_reported_CR1')].iloc[0]
    stage08=results[(results['sample']=='state_varying_accounts')&(results.covariance=='nested_chooser_CR1')].iloc[0]
    text=(f'The pool sample with the existing rematch exclusion contains {int(allrow.opportunities):,} opportunities '
          f'from {int(allrow.choosers):,} choosers. Choosers face a mean of {allrow["mean"]:.2f} opportunities and '
          f'a median of {allrow["median"]:g}; {int(allrow.choosers_more_than_one):,} face more than one opportunity. '
          f'The competitive-versus-clearly-worse comparison contains {int(contrast.opportunities):,} observations '
          f'from {int(contrast.choosers):,} choosers, of whom {support["choosers_seen_in_both_states"]:,} are observed '
          'in both states. These choosers supply the direct within-person state variation in the minimal binary '
          f'contrast. The {support["contrast_singleton_choosers"]:,} singleton accounts in that estimating sample '
          'have zero demeaned regressors. Explicitly removing them leaves the minimal chooser-FE desert '
          f'coefficient unchanged at {c7r.estimate_pp:.4f} percentage points.\n')
    estimand=('The primary specifications are linear probability models with chooser fixed effects and '
              'standard errors clustered by chooser. They compare opportunities faced by the same account, '
              'with the remaining state variables held fixed. The coefficient is a within-chooser linear '
              'projection whose weighting reflects the available within-person covariate variation. '
              'Accounts are included regardless of whether they ever grant a draw. The state is not assigned, '
              'so the estimates are conditional associations.\n')
    atomic_text(public/'DESIGN_I_COUNT_PARAGRAPH.txt',text)
    def tex_numbers(value):
        import re
        return re.sub(r'\b\d{1,3}(?:,\d{3})+\b',lambda m:m.group().replace(',',r'{,}'),value)
    opening=(r'\paragraph{Design I: within-chooser structure.} Section~\ref{sec:structure} asks how the '
             r'probability of a kind draw varies with the state $(b,m,q)$ and with relative strength $x$. ')
    closing=('Raw rates are reported alongside; differences between raw and within-chooser estimates '
             'reflect differences in which choosers face which states as well as the weighting of '
             'within-chooser variation.\n')
    atomic_text(public/'DESIGN_I_REPLACEMENT.tex',opening+tex_numbers(estimand)+'\n'+tex_numbers(text)+'\n'+closing)
    se_note=('The as-reported C7R standard error also agrees to four decimal places in percentage points.'
             if support['reported_C7R_se_same_at_4_decimal_pp'] else
             f'The as-reported C7R standard error changes from {support["reported_C7R_se_before_pp"]:.4f} to '
             f'{support["reported_C7R_se_after_pp"]:.4f} pp because its finite-sample correction changes. '
             'Do not state that all reported digits, including inference, are identical.')
    note=(f'# Chooser support and singleton audit\n\n{text}\n'
          f'Minimal FE desert coefficient: {c7r.estimate_pp:.6f} pp. The current C7R reference is reproduced.\n\n'
          f'{se_note}\n\n'
          f'The Stage08-compatible identifying-row/nested-chooser correction yields SE {stage08.se_pp:.6f} pp. '
          'This separately labeled inference comparison does not overwrite the earlier reported result.\n\n'
          'For the binary FE-only comparison, chooser i has weight n_Fi*n_Li/(n_Fi+n_Li). '
          'The coefficient is the weighted mean of the chooser-specific observed fair-minus-worse grant-rate '
          'differences. Same-state choosers and singletons receive zero weight. Choosers observed in both '
          'states with zero grants contribute positive weight and an observed difference of zero. This '
          'does not establish a zero individual causal effect or a permanent never-granting type. With '
          'additional controls, interpretation uses the residualized state regressor; the simple weights '
          'above do not automatically carry over.\n\n'
          'The support counts and singleton re-estimation here concern the minimal binary desert contrast. '
          'They do not certify identical rounded standard errors for every other Design I specification. '
          'No ever-granter-only model is fitted.\n\n'
          f'Elapsed runtime including source authentication: {elapsed:.1f} seconds.\n')
    atomic_text(public/'SUMMARY.md',note)
    atomic_json(public/'RUN_STATUS.json',dict(status='SYNTHETIC_TEST_ONLY' if synthetic else 'CHOOSER_SUPPORT_AUDIT_COMPLETE',completed_utc=utc_now(),
                elapsed_seconds=elapsed,production_data_computed=not synthetic,sample_fingerprint=lineage['fingerprint'],
                contract_sha256=contract['sha256'],reference_reproduced=True,
                singleton_coefficient_invariance=True,ever_granter_only_model_fitted=False))


def export(public,transfer):
    transfer.mkdir(parents=True,exist_ok=True)
    stamp=utc_now().replace('-','').replace(':','')
    name='POOL_CHOOSER_SUPPORT_RESULTS_v100_'+stamp
    # Flat public inventory only; no private Parquets/account IDs.
    files=[public/name for name in sorted(PUBLIC_FILES)]
    if any(not p.is_file() for p in files):raise RuntimeError('Expected public report file is missing')
    atomic_text(public/'SHA256SUMS.txt',''.join(f'{sha256_file(p)}  {p.name}\n' for p in files))
    files.append(public/'SHA256SUMS.txt')
    output=transfer/(name+'.zip')
    if output.exists():raise RuntimeError('Refusing to replace an existing result ZIP')
    temporary=output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,name+'/'+p.name)
    os.replace(temporary,output)
    atomic_text(output.with_suffix('.zip.sha256'),f'{sha256_file(output)}  {output.name}\n')
    return output


def main(args):
    os.umask(0o077)
    started=time.monotonic()
    package=verify_package_manifest()
    environment=verify_runtime_dependencies()
    private=args.project_root/'derived/replication/pool_chooser_support_v100_PRIVATE'
    public=args.project_root/'output/pool_chooser_support_v100'
    if not args.project_root.is_dir():raise RuntimeError('Project drive/path not found')
    private.mkdir(parents=True,exist_ok=True)
    lock=(private/'run.lock').open('a+')
    try:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError('This chooser-support audit is already running') from exc
    try:
        if shutil.disk_usage(private).free<args.min_free_gb*1e9:
            raise RuntimeError(f'Require {args.min_free_gb:g} GB free for private census/spill files')
        sample=args.sample_root or args.project_root/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
        auth=authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
        stats={str(r['path']):(r['path'].stat().st_size,r['path'].stat().st_mtime_ns) for r in auth['month_records']}
        reference=load_json(PACKAGE_ROOT/'authority/REFERENCE.json')
        payload=dict(version=VERSION,sample_fingerprint=auth['fingerprint'],package_manifest_sha256=package['manifest_sha256'],
                     contrast='evaluation >= -100 versus evaluation <= -300; middle excluded',
                     model='y ~ competitive + chooser FE',outcome_selection='none')
        contract=dict(payload,sha256=hashlib.sha256(canonical_json(payload).encode()).hexdigest())
        path=private/'CONTRACT.json'
        if path.exists() and load_json(path)!=contract:raise RuntimeError('Private census contract changed')
        atomic_json(path,contract)
        tasks=[dict(month=r['month'],rows=r['rows'],path=str(r['path']),expected_sha256=r['expected_sha256'],
                    cache=str(private/'monthly'),memory=args.worker_memory,contract=contract['sha256']) for r in auth['month_records']]
        cached_months={p.stem for p in (private/'monthly').glob('????-??.parquet')}
        if not cached_months.issubset({t['month'] for t in tasks}):raise RuntimeError('Unrecognized month in private cache')
        with cf.ProcessPoolExecutor(max_workers=args.workers,mp_context=mp.get_context('spawn')) as pool:
            futures=[pool.submit(month_census,t) for t in tasks]
            for future in cf.as_completed(futures):print('MONTH_OK '+canonical_json(future.result()),flush=True)
        print('MERGING_CHOOSER_COUNTS',flush=True)
        census=merge_census(private,contract['sha256'],args.merge_threads,args.merge_memory)
        frame=pd.read_parquet(census,columns=FIELDS)
        a=auth['authority']
        totals=dict(rows=int(frame.n.sum()),choosers=len(frame),kind_draws=int(frame.k.sum()),
                    fair_rows=int(frame.f.sum()),fair_kind_draws=int(frame.a.sum()),
                    fair_choosers=int((frame.f>0).sum()),fair_kind_choosers=int((frame.a>0).sum()))
        if any(totals[k]!=a[k] for k in totals):raise RuntimeError('Chooser census fails source-authority conservation')
        print('CHOOSER_COUNTS_CONSERVED '+canonical_json(totals),flush=True)
        summaries,pmf,support,results=calculate(frame)
        check=verify_reference(results,support,reference)
        if sha256_file(auth['success_path'])!=auth['success_sha256']:raise RuntimeError('Source receipt changed during run')
        for name,previous in stats.items():
            p=Path(name)
            if (p.stat().st_size,p.stat().st_mtime_ns)!=previous:raise RuntimeError('Source panel changed during run')
        report(public,summaries,pmf,support,results,compact_sample_lineage(auth),contract,time.monotonic()-started,check)
        atomic_json(public/'ENVIRONMENT.json',environment)
        output=export(public,args.transfer_root)
        print('CHOOSER_SUPPORT_AUDIT_COMPLETE',flush=True)
        print((public/'DESIGN_I_COUNT_PARAGRAPH.txt').read_text(),flush=True)
        print('RESULTS_ZIP '+str(output),flush=True)
        print('RESULTS_SHA256 '+str(output.with_suffix('.zip.sha256')),flush=True)
    finally:
        lock.close()


def parser():
    p=argparse.ArgumentParser(description='Exact chooser-support census and singleton/FE estimand audit; offline.')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--sample-root',type=Path)
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,choices=range(1,5),default=2)
    p.add_argument('--hash-workers',type=int,choices=range(1,11),default=8)
    p.add_argument('--merge-threads',type=int,choices=range(1,11),default=8)
    p.add_argument('--worker-memory',default='2GB')
    p.add_argument('--merge-memory',default='4GB')
    p.add_argument('--min-free-gb',type=float,default=5)
    return p


if __name__=='__main__':
    main(parser().parse_args())
