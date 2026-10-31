#!/usr/bin/env python3
"""Cached entry diagnostics; no metadata retrieval or chronology rebuilding."""
from entry_common import *
import entry_models as models
import entry_report as reporting
import argparse,fcntl,concurrent.futures as futures,multiprocessing as mp
from performance_runtime import invoke


def model_memory(rows):return .8+int(rows)*1800/1024**3


def model_map(jobs,runtime,workers,memory,label):
    """Memory-weighted spawned scheduling; large FE fits are never oversubscribed."""
    jobs=sorted(jobs,key=lambda j:j['memory_estimate_gb'],reverse=True)
    budget=memory-1.5
    if any(j['memory_estimate_gb']>budget for j in jobs):
        raise RuntimeError(f'Model needs an estimated {max(j["memory_estimate_gb"] for j in jobs)+1.5:.1f} GiB total budget. Rerun with --memory-gb at least that value; completed stages remain reusable.')
    began=time.monotonic();pending={};completed=0;metrics=[]
    with futures.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        while jobs or pending:
            used=sum(j['memory_estimate_gb'] for j in pending.values())
            while len(pending)<workers:
                k=next((k for k,j in enumerate(jobs) if used+j['memory_estimate_gb']<=budget),None)
                if k is None:break
                job=jobs.pop(k);pending[pool.submit(invoke,models.model_job,job)]=job;used+=job['memory_estimate_gb']
            done,_=futures.wait(pending,timeout=30,return_when=futures.FIRST_COMPLETED)
            for f in done:
                job=pending.pop(f);_,metric=f.result();metrics.append(metric);completed+=1
            io.log(f'{label}: {completed} complete; {len(pending)} fits active; {len(jobs)} queued; reserved model memory {sum(j["memory_estimate_gb"] for j in pending.values()):.1f} GiB')
    runtime.save(dict(stage=label,kind='memory_weighted_spawn',seconds=time.monotonic()-began,workers=workers,
        completed_jobs=completed,max_worker_lifetime_peak_rss_gib=max((r['worker_lifetime_peak_rss_gib'] for r in metrics),default=0),
        reused_checkpoints=sum(r['reused_checkpoint'] for r in metrics)))


def execute(a):
    started=time.monotonic();no_network();verify_package()
    a.project_root=a.project_root.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    if not a.project_root.is_dir():raise RuntimeError('Project drive unavailable: '+str(a.project_root))
    workers=max(1,min(a.workers,10,os.cpu_count() or 1,int(max(1,(a.memory_gb-2)//1.5))))
    worker_memory=max(.5,(a.memory_gb-2)/workers)
    io.log(f'Up to {workers} local workers; budget {a.memory_gb:g} GiB. Models use memory-weighted scheduling. Zero API calls.')
    with io.heartbeat('Authenticating completed 25% entry files and cached score definitions'):
        binding=authenticate(a.project_root,a.parent)
    config=dict(version=VERSION,package_sha256=io.sha(HERE/'PACKAGE_MANIFEST.sha256'),parent=binding,
        design='nested_entry_stages_common_rows_X0_XC_fixed_control_ladder_v1',minimum_competitive_decisions=5)
    conf=io.cfgsha(config);root=a.project_root/ENTRY_REL/conf[:12];root.mkdir(parents=True,exist_ok=True)
    a.desktop.mkdir(parents=True,exist_ok=True);runtime=Runtime(root)
    with (root/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This entry analysis is already running')
        io.js(root/'config.json',config)
        io.js(root/'execution.json',dict(workers=workers,memory_gb=a.memory_gb,model_memory_rule='0.8 GiB + 1800 bytes per pre-support row; 1.5 GiB coordinator reserve',estimated_runtime_minutes=[15,40],runtime_is_unbenchmarked=True))
        parent=Path(binding['parent']);split=parent/'split';shared=a.project_root/CACHE_REL
        # Reproduce all five earlier entry cohorts before changing scores or support.
        original_jobs=[]
        for cohort in COHORTS:
            path=split/('entry_'+cohort+'.parquet');n=pq.ParquetFile(path).metadata.num_rows
            original_jobs.append(dict(input=str(path),cohort=cohort,sample='all_entry',conf=conf,
                expected=str(HERE/'evidence/estimates.json'),memory_estimate_gb=model_memory(n),
                output=str(root/'models'/(cohort+'_all_entry'))))
        model_map(original_jobs,runtime,workers,a.memory_gb,'Reproducing the completed entry estimates')
        reporting.export(root,a.desktop,conf,'ORIGINAL_ENTRY_REPRODUCED_NEW_COMPARISON_PENDING',started,binding)
        with runtime.stage('Small entry score queries from completed Parquets'):
            queryroot,_=prepare_queries(split,root/'queries',conf,binding['author_ids'])
        index_jobs=[dict(shard=s,index=str(shared/'score_index'/binding['index_conf']/f'{s:02}'),index_conf=binding['index_conf'],output=str(root/'index_checks'/f'{s:02}')) for s in range(16)]
        runtime.mapped(index_auth_job,index_jobs,workers,'Verify existing sufficient-statistic indexes; no raw history scan')
        reference=shared/'reference'/binding['reference_conf']/'models';scorejobs=[]
        for s in range(16):
            job=dict(queries=str(queryroot/f'{s:02}.parquet'),index=index_jobs[s]['index'],index_conf=binding['index_conf'],
                reference=str(reference),authors=binding['author_ids'],memory=worker_memory,conf=conf,
                output=str(root/'scores'/f'{s:02}'))
            scorejobs.append(feature_cache.attach(job,shared,'competitive_scores',binding['competitive_definition'],s))
        runtime.mapped(score_job,scorejobs,workers,'Reuse competitive scores; compute only missing entry-game scores')
        with runtime.stage('Project model columns and audit competitive-history support'):
            prepared,_=assemble(split,[str(Path(j['output'])/'scores.parquet') for j in scorejobs],root/'prepared',conf,a.memory_gb-1,workers)
        reporting.export(root,a.desktop,conf,'SUPPORT_COMPLETE_MODELS_PENDING',started,binding)
        cutoff=io.load(HERE/'evidence/secondary_scale.json')['upper_5pct_raw_competitive_cutoff']
        jobs=[]
        for cohort in COHORTS:
            path=prepared/(cohort+'.parquet');n=pq.ParquetFile(path).metadata.num_rows
            jobs.append(dict(input=str(path),cohort=cohort,sample='competitive_supported',conf=conf,tail_cutoff=cutoff,
                expected=str(HERE/'evidence/estimates.json'),memory_estimate_gb=model_memory(n),
                output=str(root/'models'/(cohort+'_competitive_supported'))))
        model_map(jobs,runtime,workers,a.memory_gb,'Matched instrument comparisons and fixed control ladder')
        reporting.export(root,a.desktop,conf,'ENTRY_DIAGNOSTICS_COMPLETE',started,binding)
        io.log('Entry diagnostics complete. Return the aggregate report ZIP printed above.')
    return root


def main():
    workers,memory=defaults();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=BASE)
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--parent',type=Path,help='Exact completed 25% folder, only if moved')
    p.add_argument('--workers',type=int,default=workers);p.add_argument('--memory-gb',type=float,default=memory)
    a=p.parse_args()
    if a.workers<1 or a.memory_gb<4:p.error('Use at least one worker and 4 GiB memory')
    execute(a)

if __name__=='__main__':main()
