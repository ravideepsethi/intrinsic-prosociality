#!/usr/bin/env python3
"""Expected runtime: under 30 seconds; aggregate Parquets, up to six parallel jobs."""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[key]='1'
import argparse,itertools,time
from concurrent.futures import ProcessPoolExecutor,as_completed
from multiprocessing import get_context
from datetime import datetime
from io_utils import *
from inference import windows,complete_weeks,block_null,mde,pre_diagnostics,AWARENESS,SEED

def milliseconds(s):
    d=datetime.fromisoformat(str(s).replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('Expected an explicit UTC offset')
    return int(d.timestamp()*1000)

def bootstrap_job(task):
    pre,w,block=task
    null=block_null(pre,w['pre_offsets'],w['post_offsets'],block,10000,SEED)
    neg,critical=mde(null,-1);pos,_=mde(null,1)
    return w['period'],block,null,neg,pos,critical

def validate_inputs():
    lineage=read(ROOT/'SOURCE_LINEAGE.json')
    for name,h in lineage['input_files'].items():
        if sha(ROOT/name)!=h:raise RuntimeError('Source checksum differs: '+name)
    for name,h in lineage['copied_calendar_code'].items():
        if sha(ROOT/'code'/name)!=h:raise RuntimeError('Calendar implementation differs: '+name)
    source=ROOT/'source';summary=read(source/'SUMMARY.json')
    if summary['status']!='PRE_POLICY_TRANSPORT_COMPLETE_POST_POLICY_TEST_OPEN':
        raise RuntimeError('Parent prediction run is not complete')
    n=summary['support'];counts=pd.read_parquet(source/'failed_branch_monthly_counts.parquet')
    if (n['n'],n['grants'],n['accounts'])!=(3236219,58298,778048):raise RuntimeError('Unexpected source population')
    if (int(counts.rows.sum()),int(counts.grants.sum()))!=(n['n'],n['grants']):raise RuntimeError('Branches use different monthly totals')
    weekly=pd.read_parquet(source/'pre_policy_weekly.parquet').sort_values('week')
    weekly['week_ms']=weekly.week.map(milliseconds).astype('int64')
    lo=milliseconds(n['source_coverage_start_exclusive_utc']) if 'source_coverage_start_exclusive_utc' in n else milliseconds(n['source_coverage_start_utc'])
    hi=milliseconds(n['source_coverage_end_exclusive_utc'])
    expected=complete_weeks(lo,hi)
    if len(weekly)!=103 or not np.array_equal(weekly.week_ms,expected):raise RuntimeError('Incomplete/duplicate calendar coverage')
    for color in ('white','black'):
        if (weekly[color+'_n']<=0).any():raise RuntimeError('Missing color support')
        grants=weekly[color+'_grants'];nn=weekly[color+'_n']
        if not grants.between(0,nn).all():raise RuntimeError('Invalid weekly counts')
        np.testing.assert_allclose(100*grants/nn,weekly[color+'_rate_pp'],atol=1e-12,rtol=0)
    np.testing.assert_allclose(weekly.white_rate_pp-weekly.black_rate_pp,weekly.white_minus_black_pp,atol=1e-12,rtol=0)
    p=pd.read_parquet(source/'prediction_by_week.parquet')
    p=p[(p.cohort=='rd110')&(p.stage=='full')&(p.baseline=='account20')].copy()
    p['week_ms']=p.week.map(milliseconds).astype('int64')
    if set(p.model)!=set(MODELS):raise RuntimeError('Primary models missing')
    readout=pd.read_parquet(source/'PRIMARY_READOUT.parquet')
    for model in MODELS:
        d=p[p.model==model].sort_values('week_ms')
        if not np.array_equal(d.week_ms,expected):raise RuntimeError('Incomplete prediction calendar: '+model)
        np.testing.assert_array_equal(d.white_n,weekly.white_n)
        np.testing.assert_array_equal(d.black_n,weekly.black_n)
        np.testing.assert_allclose(d.statistic_prediction_pp,d.white_shift_pp-d.black_shift_pp,atol=1e-12,rtol=0)
        for color in ('white','black'):
            np.testing.assert_allclose(d['new_'+color+'_rate_pp']-d['old_'+color+'_rate_pp'],d[color+'_shift_pp'],atol=1e-12,rtol=0)
        for scope,z in [('all_complete_pre',d),('last8_complete_pre',d.tail(8))]:
            r=readout[(readout.model==model)&(readout.target_scope==scope)]
            if len(r)!=1:raise RuntimeError('Ambiguous readout')
            np.testing.assert_allclose(z.statistic_prediction_pp.mean(),r.statistic_prediction_pp.iloc[0],atol=1e-12,rtol=0)
    return weekly,readout,lo,hi,lineage

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workers',type=int,default=6)
    ap.add_argument('--output',type=Path,default=ROOT/'reproduced_results')
    a=ap.parse_args()
    if not 1<=a.workers<=10:ap.error('Use 1–10 workers')
    start=time.monotonic();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    w,pred,lo,hi,lineage=validate_inputs();spec=windows()
    compatible=set(next(x['compatible_models'] for x in read(ROOT/'source/REPAIRED_MODEL_COMPATIBILITY.json')
        if x['comparison']=='rd110_train_rd110_test' and x['state']=='equal'))
    pre=w.white_minus_black_pp.to_numpy(float)
    jobs=[(pre,s,b) for s in spec for b in (4,8)]
    results=[]
    with ProcessPoolExecutor(max_workers=min(a.workers,6),mp_context=get_context('spawn')) as pool:
        futures=[pool.submit(bootstrap_job,j) for j in jobs]
        for future in as_completed(futures):results.append(future.result())
    power=[];single=[];noise=[];byperiod={s['period']:s for s in spec}
    for period,block,null,neg,pos,critical in sorted(results,key=lambda x:(x[0],x[1])):
        s=byperiod[period]
        table(pd.DataFrame({'null_pp':null}),out/f'null_{period}_block{block}.parquet')
        noise.append(dict(period=period,block_weeks=block,pre_weeks=103,post_weeks=len(s['post']),
            mde_negative_pp=neg,mde_positive_pp=pos,critical_abs_pp=critical,null_mean_pp=float(null.mean()),
            null_sd_pp=float(null.std(ddof=1)),pre_offsets=','.join(map(str,s['pre_offsets'])),
            post_offsets=','.join(map(str,s['post_offsets'])),planning_censor_certified=False))
        for scope in ('all_complete_pre','last8_complete_pre'):
            z=pred[pred.target_scope==scope];full=dict(zip(z.model,z.statistic_prediction_pp))
            for ma,mb in itertools.combinations(sorted(full),2):
                for qv in AWARENESS:
                    delta=qv*(full[ma]-full[mb]);pwr=float(np.mean(abs(null+delta)>critical))
                    power.append(dict(period=period,block_weeks=block,target_scope=scope,model_a=ma,model_b=mb,
                        effective_updating=qv,predicted_difference_pp=delta,conditional_power=pwr,
                        reaches_80pct_at_point_fit=pwr>=.8,both_models_pre_policy_compatible=ma in compatible and mb in compatible,
                        parameter_uncertainty_propagated=False,actual_frozen_cohort=False,automatic_go=False))
            for model,value in full.items():
                for qv in AWARENESS:
                    shift=qv*value
                    single.append(dict(period=period,block_weeks=block,target_scope=scope,model=model,
                        effective_updating=qv,prediction_pp=shift,conditional_power=float(np.mean(abs(null+shift)>critical))))
    table(power,out/'calendar_pairwise_power.parquet');table(single,out/'calendar_single_model_power.parquet')
    table(noise,out/'calendar_MDE.parquet');table(pred,out/'reused_primary_predictions.parquet')
    long=pd.concat([pd.DataFrame(dict(week_ms=w.week_ms,color=c,n=w[c+'_n'],grants=w[c+'_grants'],rate_pp=w[c+'_rate_pp'])) for c in ('white','black')],ignore_index=True)
    pre_diagnostics(long,spec,lo,hi,out/'pre_diagnostics')
    table(w,out/'observed_pre_weekly.parquet')
    windows_rows=[]
    for s in spec:
        for side in ('pre','post'):
            for t in s[side]:windows_rows.append(dict(period=s['period'],side=side,week_start_utc=pd.to_datetime(int(t),unit='ms',utc=True).isoformat(),week_ms=int(t)))
    table(windows_rows,out/'calendar_windows.parquet')
    write(out/'SUMMARY.json',dict(status='CALENDAR_PLANNING_RECOVERED_FROM_COMPLETED_SEPARATE_RUN',
        source=lineage['successful_prediction_archive'],source_sha256=lineage['successful_prediction_sha256'],
        failed_branch_completed=False,baseline=lineage['baseline'],new_private_data_run=False,
        post_policy_outcomes_used=False,parameter_uncertainty_propagated=False,automatic_go=False,
        planning_end='2026-01-30T00:00:00Z; illustrative, not certified',
        workers=min(a.workers,6),python=__import__('sys').version,pandas=pd.__version__,numpy=np.__version__,
        calendar_rule='Eight pre weeks; exclude event-crossing weeks; preserve calendar gaps in bootstrap',
        transport_scopes=['103 complete source weeks','last eight complete source weeks'],
        note='This extends the completed account20-plus-global-rate-match analysis. It does not fill in the failed branch with a different baseline unnoticed.',
        elapsed_seconds=time.monotonic()-start))
    print('OK — recovered calendar-aware planning in %.2f seconds; no private data read.'%(time.monotonic()-start))

if __name__=='__main__':main()
