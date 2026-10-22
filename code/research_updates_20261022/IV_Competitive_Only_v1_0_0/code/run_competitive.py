#!/usr/bin/env python3
from common import *
import inputs,reporting,iv_stats
import argparse,fcntl

def execute(a):
    no_network();threads_one();start=time.monotonic();codehash=verify_package()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if a.memory_gb<4:raise RuntimeError('At least 4 GiB analysis memory budget is required')
    sw=max(1,min(a.workers,10,os.cpu_count() or 1,int(max(1,(a.memory_gb-2)//1.5))))
    mw=max(1,min(a.workers,10,os.cpu_count() or 1,int(max(1,(a.memory_gb-2)//4.5))))
    io.log(f'Budget {a.memory_gb:g} GiB; score workers {sw}; simultaneous model workers {mw}; API requests zero')
    with io.heartbeat('Authenticating headline inputs'):source=inputs.authenticate(project,sw)
    config=dict(version=VERSION,package_sha256=codehash,source={k:v for k,v in source.items() if k not in ('index_root','parts','deltas')},
        history=[{k:r[k] for k in ('month','shard','sha256','rows')} for r in source['parts']],
        reference_deltas=[io.sha(p) for p in source['deltas']],author_included=True,reviewed_spec_sha=io.sha(ROOT/'SPECIFICATION.md'))
    conf=io.cfgsha(config);root=project/OUT_REL/conf[:12];root.mkdir(parents=True,exist_ok=True)
    performance=[];results=[];subgroups=[]
    with (root/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This competitive-only analysis is already running')
        io.js(root/'config.json',config);io.js(root/'INPUTS_PRIVATE.json',source)
        io.js(desktop/'IV_COMPETITIVE_ONLY_LATEST_PRIVATE.json',dict(root=str(root),config_sha256=conf))
        t=time.monotonic()
        with io.heartbeat('Reproducing original headline IV and original placebo'):
            prepared,_=inputs.prepare(source,root/'prepared',conf,io.load(ROOT/'evidence/expanded_estimates.json'))
        performance.append(dict(stage='Frozen numerical reproduction and query preparation',seconds=time.monotonic()-t,workers=1))
        reference,_=inputs.reference(source,root/'reference',conf)
        jobs=[dict(module='inputs',function='build_index',existing=str(Path(source['index_root'])/f'{s:02}'),
            index_conf=source['index_conf'],parts=[r['path'] for r in source['parts'] if r['shard']==s],
            memory=max(.5,(a.memory_gb-2)/sw),output=str(root/'score_indexes'/f'{s:02}')) for s in range(16)]
        indexes=mapped(jobs,sw,'Reusing or building score sufficient-statistic indexes',performance)
        jobs=[dict(module='inputs',function='score_job',query=str(prepared/f'query_{s:02}.parquet'),index=indexes[s]['path'],
            reference=str(reference/'original.npy'),conf=conf,output=str(root/'scores'/f'{s:02}')) for s in range(16)]
        mapped(jobs,sw,'Splitting historical scores and verifying pooled reconstruction',performance)
        paths=[str(root/'scores'/f'{s:02}'/'scores.parquet') for s in range(16)]
        with io.heartbeat('Assembling unchanged rows with split scores'):
            assembled,_=inputs.assemble(prepared,paths,root/'assembled',conf,a.memory_gb-2)
            inputs_before={p:io.sha(assembled/p) for p in ('iv.parquet','placebo.parquet')}
            reporting.descriptive(assembled,root/'descriptive',conf)
        reporting.export(root,desktop,conf,results,subgroups,performance,'SCORES_AND_SUPPORT_COMPLETE',start)
        def model(sample,family,refs=None,rich=True,balance_only=False):
            placebo=sample=='P1';where=reporting.FILTERS['S1' if placebo else sample]
            suffix=sample+'_'+family+('_without_recipient_history' if not rich else '')
            return dict(module='iv_stats',function='model_job',input=str(assembled/('placebo.parquet' if placebo else 'iv.parquet')),
                output=str(root/'models'/suffix),conf=conf,sample=sample,family=family,where=where,rich=rich,
                balance_only=balance_only,reference_sds=refs,memory=1)
        first=mapped([model('S1',f) for f in ('X0','XC')],mw,'Core A-B on S1 and common SD references',performance)
        results+=first;references={r['control_family']:r.get('native_sds',{}) for r in first}
        if any(not {'pooled','comp'}<=set(r) for r in references.values()):
            reporting.export(root,desktop,conf,results,subgroups,performance,'INSUFFICIENT_COMPETITIVE_SUPPORT',start);return
        second=mapped([model('S2',f,references[f]) for f in ('X0','XC')],mw,'Core A-D on common S2 rows',performance)
        results+=second
        reporting.export(root,desktop,conf,results,subgroups,performance,'CORE_A_D_COMPLETE_DIAGNOSTICS_CONTINUING',start)
        jobs=[model(s,f,references[f]) for s in ('S1_3','P1') for f in ('X0','XC')]
        jobs += [model(s,f,references[f],False,True) for s in ('S1','S2') for f in ('X0','XC')]
        # Bounded batches publish new aggregates after each completed batch.
        for begin in range(0,len(jobs),mw):
            results+=mapped(jobs[begin:begin+mw],mw,'Support, placebo and balance diagnostics',performance)
            reporting.export(root,desktop,conf,results,subgroups,performance,'DIAGNOSTICS_IN_PROGRESS',start)
        jobs=[dict(module='iv_stats',function='subgroup_job',input=str(assembled/'iv.parquet'),
            output=str(root/'subgroups'/(s['dimension']+'_'+s['label'])),conf=conf,spec=s,
            reference_sd=references['XC']['comp'],memory=1) for s in iv_stats.subgroup_specs()]
        grouped=mapped(jobs,mw,'Competitive score subgroup first stages',performance)
        subgroups=[r for rows in grouped for r in rows]
        # Verify the immutable model inputs are unchanged after all model workers finish.
        for p,h in inputs_before.items():io.checked(assembled/p,h)
        final=reporting.export(root,desktop,conf,results,subgroups,performance,'COMPETITIVE_ONLY_COMPLETE',start)
        io.js(root/'SUCCESS.json',dict(config_sha256=conf,report=str(final),report_sha256=io.sha(final)))
        io.log(f'COMPETITIVE_ONLY_COMPLETE in {(time.monotonic()-start)/60:.1f} minutes')

def main():
    p=argparse.ArgumentParser(description='Competitive-only IV on the frozen original headline cohort; no API calls.')
    p.add_argument('--project-root',type=Path,default=Path(os.environ.get('IV_PROJECT_ROOT','/Volumes/XT_Pro/lichess_kindness')))
    p.add_argument('--desktop',type=Path,default=Path(os.environ.get('IV_DESKTOP',str(Path.home()/'Desktop/Lichess_Desktop'))))
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=memory_default())
    a=p.parse_args()
    if a.workers<1:p.error('--workers must be positive')
    try:execute(a)
    except Exception as e:
        io.log('STOPPED: '+str(e));raise
if __name__=='__main__':main()
