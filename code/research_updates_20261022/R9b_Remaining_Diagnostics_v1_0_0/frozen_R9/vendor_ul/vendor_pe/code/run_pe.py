#!/usr/bin/env python3
"""Offline incremental updated-cutoff placebo and entry/disconnection tests."""
from pe_common import *
import pe_scores, pe_material, pe_models, pe_runtime, pe_report
import argparse, fcntl

def make_job(source, scores, output, conf, sample, kind, level, screen='all', material=None):
    n=pq.ParquetFile(source).metadata.num_rows
    # Conservative reservations; a fresh spawned worker releases peak allocations.
    weight=1.2+n*(900 if kind!='receipt_influence' else 650)/1024**3
    return dict(input=str(source),scores=str(scores),output=str(output),conf=conf,sample=sample,
        kind=kind,level=level,selection=screen,material=str(material) if material else None,memory_gb=weight)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--r7-root',type=Path);p.add_argument('--cutoff-root',type=Path)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args();u.require(1<=a.workers<=10 and 9.5<=a.memory_gb<=11,'Use 1–10 workers and 9.5–11 GiB')
    verify_package();r.threads_one();u.no_network()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    desktop.mkdir(parents=True,exist_ok=True)
    with heartbeat('Authenticate completed receipt and R7 inputs',5,70):
        paths,binding,parts,reference,cutoff,old=authenticate(project,a.r7_root,a.cutoff_root)
    conf=r.io.cfgsha(dict(version=VERSION,package=u.sha(ROOT/'PACKAGE_MANIFEST.sha256'),
        baseline=u.R7_CONF,receipt=CUTOFF_CONF,reference=u.sha(reference),
        definition='fixed_F50_O50_lag24h_frozen_nuisance_controls_shared_covariance_Parquet_material_audit'))
    root=project/'derived/replication/iv_placebo_entry_v100_PRIVATE'/conf[:12]
    root.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This configuration is already running')
    extra={};progress=0
    try:
        r.io.js(root/'config.json',dict(version=VERSION,conf=conf,workers=a.workers,memory_gb=a.memory_gb,
            receipt=CUTOFF_CONF,baseline=u.R7_CONF,reference_sha256=u.sha(reference)))
        r.io.js(desktop/'IV_PLACEBO_ENTRY_LATEST_PRIVATE.json',dict(root=str(root),configuration_sha256=conf))
        extra['archived_models']=[dict(sample=key.split('__')[0],level=key.split('__')[1],path=value) for key,value in old.items()]
        with heartbeat('Prepare cached F50 query shards',3,65):
            query=pe_scores.prepare_queries(paths['F50'],root/'queries',conf)
        jobs=[]
        for s in range(16):
            selected=[v for v in parts if v['shard']==s]
            nq=pq.ParquetFile(query/f'{s:02}.parquet').metadata.num_rows
            jobs.append(dict(shard=s,parts=selected,queries=str(query/f'{s:02}.parquet'),authors=binding['author_ids'],
                reference=str(reference),output=str(root/'scores'/f'{s:02}'),conf=conf,
                memory_gb=.7+(sum(v['rows'] for v in selected)*480+nq*700)/1024**3))
        extra['history_shards']=pe_runtime.mapped(pe_scores.score_job,jobs,a.workers,a.memory_gb,'F50 history replay and new scores',20,35)
        # Do not expose private checkpoint dependency hashes/path lists in aggregates.
        extra['history_shards']=[{k:v for k,v in x.items() if k not in ('files',)} for x in extra['history_shards']]
        with heartbeat('Combine histories and verify O50/F50 identity bridge',3,35):
            scores=pe_scores.combine([str(Path(j['output'])/'scores.parquet') for j in jobs],paths['F50'],root/'scores_combined',conf,a.memory_gb-2)
            oscores,extra['ordinary_subset']=pe_scores.subset_scores(paths['F50'],paths['O50'],scores,root/'ordinary_scores',conf,a.memory_gb-2)
        progress=25;pe_report.export(root,desktop,conf,progress,'HISTORIES_COMPLETE',extra)
        with heartbeat('Audit ordinary final-position Parquet coverage',5,30):
            candidates,inv=pe_material.inventory(paths,binding,project,a.r7_root or project/u.R7_REL)
            saved=root/'material_inventory_PRIVATE.json';snapshot=dict(candidates=candidates,audit=inv)
            if saved.exists():u.require(u.load(saved)==snapshot,'Material cache inventory changed since this run began')
            else:r.io.js(saved,snapshot)
            material,extra['material']=pe_material.audit(paths['O50'],candidates,inv,root/'material',conf,a.memory_gb-2)
        progress=50;pe_report.export(root,desktop,conf,progress,'INPUT_CHECKS_COMPLETE',extra)
        jobs=[];lookup={}
        for level in LEVELS:
            for sample,kind,score in [('F50','entry',scores),('O50','ordinary',oscores),('S0','receipt_influence',cutoff/'scores_combined/scores.parquet')]:
                name=f'{sample}__all__{level}';out=root/'fits'/name
                jobs.append(make_job(paths[sample],score,out,conf,sample,kind,level))
                lookup[(sample,'all',level)]=out
            if material:
                for screen in ('observed','neutral'):
                    for sample,kind,score,mat in [('O50','ordinary',oscores,material),
                        ('S0','receipt_influence',cutoff/'scores_combined/scores.parquet',cutoff/'material/material.parquet')]:
                        name=f'{sample}__{screen}__{level}';out=root/'fits'/name
                        jobs.append(make_job(paths[sample],score,out,conf,sample,kind,level,screen,mat))
                        lookup[(sample,screen,level)]=out
        r.io.js(root/'MODEL_PLAN_PRIVATE.json',jobs)
        pe_runtime.mapped(pe_models.fit_job,jobs,a.workers,a.memory_gb,'New diagnostic fits and receipt RF checks',25,5)
        progress=75;pe_report.export(root,desktop,conf,progress,'MODELS_COMPLETE_CONTRASTS_PENDING',extra)
        cjobs=[]
        for screen in ('all','observed','neutral') if material else ('all',):
            for level in LEVELS:
                left=lookup[('S0',screen,level)];right=lookup[('O50',screen,level)]
                if not (right/'influence_PRIVATE.parquet').exists():continue
                cjobs.append(dict(left=str(left),right=str(right),level=level,selection=screen,conf=conf,
                    output=str(root/'contrasts'/f'{screen}__{level}'),memory_gb=7.5))
        extra['contrast_jobs']=pe_runtime.mapped(pe_models.contrast_job,cjobs,a.workers,a.memory_gb,'Receipt minus placebo shared-covariance contrasts',5)
        extra['contrast_jobs']=[{k:v for k,v in x.items() if k!='files'} for x in extra['contrast_jobs']]
        progress=100
        status='COMPLETE' if material else 'CORE_COMPLETE_ORDINARY_MATERIAL_PENDING'
        pe_report.export(root,desktop,conf,progress,status,extra)
        u.log('FINISHED. Return the 100% report ZIP and its .sha256 sidecar from Lichess_Desktop. ETA: complete.')
    except BaseException as exc:
        extra['error_type']=type(exc).__name__
        pe_report.export(root,desktop,conf,progress,'STOPPED_RETURN_LOG',extra)
        raise
    finally:lock.close()

if __name__=='__main__':main()
