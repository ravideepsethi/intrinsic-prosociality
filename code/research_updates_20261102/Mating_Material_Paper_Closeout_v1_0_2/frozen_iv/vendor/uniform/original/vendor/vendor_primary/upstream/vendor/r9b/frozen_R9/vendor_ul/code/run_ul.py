#!/usr/bin/env python3
"""Offline full-time leave-pair-out IV, placebo, entry, and timing diagnostics."""
from ul_common import *
import ul_scores,ul_models,ul_report
import argparse,fcntl

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--r7-root',type=Path);p.add_argument('--cutoff-root',type=Path);p.add_argument('--placebo-root',type=Path)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args();u.require(1<=a.workers<=10 and 9.5<=a.memory_gb<=11,'Use 1–10 workers and 9.5–11 GiB')
    verify_package();r.threads_one();u.no_network()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve();desktop.mkdir(parents=True,exist_ok=True)
    with heartbeat('Authenticate and reuse completed R7 / receipt / placebo runs',5,65):
        paths,binding,parts,reference,cutoff,pe=authenticate(project,a.r7_root,a.cutoff_root,a.placebo_root)
    conf=r.io.cfgsha(dict(version=VERSION,package=u.sha(ROOT/'PACKAGE_MANIFEST.sha256'),baseline=u.R7_CONF,
        receipt=prior.CUTOFF_CONF,placebo=PE_CONF,reference=u.sha(reference),definition=DEFINITION))
    root=project/'derived/replication/iv_leave_pair_out_v100_PRIVATE'/conf[:12];root.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This leave-pair-out configuration is already running')
    progress=0;extra={}
    try:
        r.io.js(root/'config.json',dict(version=VERSION,conf=conf,workers=a.workers,memory_gb=a.memory_gb,
            definition=DEFINITION,reference_sha256=u.sha(reference),inference=annotations()))
        r.io.js(desktop/'IV_LEAVE_PAIR_OUT_LATEST_PRIVATE.json',dict(root=str(root),configuration_sha256=conf))
        r.io.js(root/'INPUTS_PRIVATE.json',dict(paths=paths,cutoff=str(cutoff),placebo=str(pe),reference=str(reference)))
        with heartbeat('Prepare projected S0 and F50 query shards',3,60):
            queries=ul_scores.prepare_queries(paths,root/'queries',conf)
        jobs=[]
        for shard in range(16):
            selected=[v for v in parts if v['shard']==shard]
            nq=pq.ParquetFile(queries/f'{shard:02}.parquet').metadata.num_rows
            jobs.append(dict(shard=shard,parts=selected,queries=str(queries/f'{shard:02}.parquet'),authors=binding['author_ids'],
                reference=str(reference),output=str(root/'scores'/f'{shard:02}'),conf=conf,
                memory_gb=.8+(sum(v['rows'] for v in selected)*520+nq*800)/1024**3))
        info=runtime.mapped(ul_scores.score_job,jobs,a.workers,a.memory_gb,'Unrestricted pair-excluded scores',20,40)
        extra['history_shards']=[public_stage(v) for v in info]
        old_scores={'S0':cutoff/'scores_combined/scores.parquet','F50':pe/'scores_combined/scores.parquet'}
        with heartbeat('Combine and compare against saved 24-hour scores',4,40):
            scores,extra['score_comparison']=ul_scores.combine([str(Path(j['output'])/'scores.parquet') for j in jobs],
                paths,old_scores,root/'scores_combined',conf,a.memory_gb-2)
        progress=25;ul_report.export(root,desktop,conf,progress,'SCORES_COMPLETE',extra)
        with heartbeat('Verify ordinary subset and reuse final-material flags',3,36):
            scores['O50'],ordinary=ul_scores.ordinary_scores(paths,scores['F50'],root/'ordinary_scores',conf,a.memory_gb-2)
            extra['ordinary_subset']=public_stage(ordinary)
            material=cutoff/'material/material.parquet'
            prior.check_stage(material.parent,prior.CUTOFF_CONF,[material.name])
            oldmat=u.load(ROOT/'evidence/placebo/summary.json')['material']
            extra['ordinary_material']={k:v for k,v in oldmat.items() if not isinstance(v,(dict,list))}
            extra['ordinary_material']['audit_reused_not_repeated']=True
            extra['estimator_audit']=dict(donor_pair_exclusion='verified by independent direct masks',
                state_reference='unchanged held-out-both-player-fold model; authenticated hash',
                time_controls='retained; no timing restriction on primary donor eligibility',
                estimation='same R7 residualization and conditional-score CR0 as benchmarks',
                is_UJIVE=False,own_observation_bias_from_residualization_ruled_out=False,
                feedback_and_network_independence_assumed_not_verified=True)
        progress=50;ul_report.export(root,desktop,conf,progress,'INPUT_CHECKS_COMPLETE',extra)
        core=[];timing=[];lookup={}
        for level in LEVELS:
            for sample,kind in [('S0','iv'),('F50','entry'),('O50','ordinary')]:
                screens=('all','neutral') if sample=='S0' else ('all',)
                for screen in screens:
                    output=root/'fits'/f'{sample}__{screen}__all_time__{level}'
                    core.append(ul_models.make_job(paths[sample],scores[sample],output,conf,sample,kind,level,
                        screen,material if screen=='neutral' else None))
                    lookup[(sample,screen,level)]=output
            for variant in ('all_time','before','after'):
                output=root/'fits'/f'S0__timing_common__{variant}__{level}'
                timing.append(ul_models.make_job(paths['S0'],scores['S0'],output,conf,'S0','iv',level,
                    variant=variant,cohort='timing_common'))
        r.io.js(root/'MODEL_PLAN_PRIVATE.json',core+timing)
        runtime.mapped(ul_models.fit_job,core,a.workers,a.memory_gb,'Core receipt, placebo and entry fits',22,15)
        progress=75;ul_report.export(root,desktop,conf,progress,'CORE_MODELS_COMPLETE_TIMING_CONTRASTS_PENDING',extra)
        runtime.mapped(ul_models.fit_job,timing,a.workers,a.memory_gb,'Common-row before/after/full-history sensitivity',12,5)
        cjobs=[dict(left=str(lookup[('S0','all',level)]),right=str(lookup[('O50','all',level)]),level=level,
            conf=conf,output=str(root/'contrasts'/level),memory_gb=7.5) for level in LEVELS]
        extra['contrast_jobs']=[public_stage(v) for v in runtime.mapped(ul_models.contrast_job,cjobs,a.workers,a.memory_gb,
            'Receipt minus ordinary reduced-form contrasts',5)]
        progress=100;ul_report.export(root,desktop,conf,progress,'CORE_COMPLETE_ORDINARY_MATERIAL_PENDING',extra)
        u.log('FINISHED: return the 100% report ZIP and .sha256 sidecar. ETA: complete.')
    except BaseException as exc:
        extra['error_type']=type(exc).__name__
        try:ul_report.export(root,desktop,conf,progress,'STOPPED_RETURN_LOG',extra)
        except Exception as report_error:u.log('Could not export stopped report: '+str(report_error))
        raise
    finally:lock.close()

if __name__=='__main__':main()
