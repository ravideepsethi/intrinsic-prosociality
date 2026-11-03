#!/usr/bin/env python3
"""Offline certified R9; a new immutable configuration with resumable stages."""
from r9_common import *
import argparse, fcntl
import r9_inputs as inputs
import r9_scores as scores_code
import r9_models as fits
import r9_report as report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--baseline-root',type=Path);p.add_argument('--comparison-root',type=Path)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    p.add_argument('--skip-learning',action='store_true',help='Skip the explicitly optional learning split')
    a=p.parse_args();u.require(1<=a.workers<=10 and 10.5<=a.memory_gb<=11,'Use 1–10 workers, 10.5–11 GiB')
    verify_package();r.threads_one();u.no_network()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve();desktop.mkdir(parents=True,exist_ok=True)
    with heartbeat('Authenticate frozen baseline and completed comparison frames',8,165):
        paths,binding,parts,reference,cutoff,baseline=inputs.bind_baseline(project,a.baseline_root)
        comparison,phase,phase_root=inputs.bind_phase(project,desktop,a.comparison_root);paths.update(comparison)
        source_check=inputs.verify_phase_source(phase_root,binding,parts)
    config=dict(version=VERSION,package_sha256=u.sha(ROOT/'PACKAGE_MANIFEST.sha256'),baseline=BASE_CONF,
        comparison_phase=phase,reference_sha256=u.sha(reference),definition=DEFINITION,learning=not a.skip_learning)
    conf=r.io.cfgsha(config);root=project/'derived/replication/r9_certified_leave_pair_out_v100_PRIVATE'/conf[:12]
    u.require(root.resolve()!=baseline.resolve() and not root.resolve().is_relative_to(baseline.resolve()),'R9 cannot write inside the baseline run')
    root.mkdir(parents=True,exist_ok=True);lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This R9 configuration is already running')
    progress=0;extra=dict(comparison_frame=phase,source_lineage_check=source_check,learning_requested=not a.skip_learning,resource_plan=dict(workers=a.workers,total_memory_gib=a.memory_gb,
        blas_threads_per_worker=1,memory_reserved_scheduler=True,projected_parquet=True,ordinary_and_F50_donor_queries_reused=True))
    plan=[]
    try:
        if (root/'config.json').exists():u.require(u.load(root/'config.json')==config,'R9 configuration changed')
        else:r.io.js(root/'config.json',config)
        r.io.js(desktop/'R9_CERTIFIED_LATEST_PRIVATE.json',dict(root=str(root),configuration_sha256=conf,phase_percent=phase['phase_percent']))
        r.io.js(root/'INPUTS_PRIVATE.json',dict(paths={k:str(v) for k,v in paths.items()},baseline=str(baseline),reference=str(reference),comparison_root=str(phase_root)))
        material=stage_file(cutoff/'material/material.parquet',old.prior.CUTOFF_CONF)
        extra['baseline_models']=inputs.replay_baseline(paths,baseline,material,root/'baseline',conf,a.workers,a.memory_gb)
        with heartbeat('Verify Phase 50 overlap and prepare shared donor queries',5,125):
            extra['frame_feature_bridges']=[public(inputs.verify_frame_bridge(paths[k],paths[prior],root/'frame_bridges'/k,conf,a.memory_gb-2))
                for k,prior in [('F','F50'),('O','O50')]]
            # Independent final author check, including newly available comparison games.
            for sample in ('S0','F','O'):
                for role in ('recipient_id','opponent_id'):
                    u.require(not np.isin(col(paths[sample],role),binding['author_ids']).any(),'Author account in '+sample)
            queries=scores_code.prepare_queries(paths,root/'queries',conf)
        jobs=[]
        for shard in range(16):
            chosen=[v for v in parts if v['shard']==shard];nq=pq.ParquetFile(queries/f'{shard:02}.parquet').metadata.num_rows
            jobs.append(dict(shard=shard,parts=chosen,queries=str(queries/f'{shard:02}.parquet'),authors=binding['author_ids'],reference=str(reference),
                output=str(root/'scores'/f'{shard:02}'),conf=conf,memory_gb=.9+(sum(v['rows'] for v in chosen)*530+nq*850)/1024**3))
        info=runtime.mapped(scores_code.score_job,jobs,a.workers,a.memory_gb,'Step 0 score replay + single donor pass for A/B/C',32,95)
        extra['history_shards']=[public(v) for v in info]
        u.require(sum(v['source_rows'] for v in info)==47587020,'Donor source total changed')
        with heartbeat('Gate score replay and combine immutable model scores',5,90):
            scores,scoreinfo=scores_code.combine(jobs,paths,baseline,root/'scores_combined',conf,a.memory_gb-2)
            extra['score_diagnostics']=scoreinfo['diagnostics'];extra['baseline_scores_reproduced']=scoreinfo['baseline_scores_reproduced']
            scores['O'],extra['ordinary_subset']=scores_code.ordinary(paths,scores['F'],root/'ordinary_scores',conf,a.memory_gb-2)
            flags,extra['learning_flags']=scores_code.learning_flags(paths,jobs,root/'learning_flags',conf,a.memory_gb-2)
        progress=25;report.export(root,desktop,conf,progress,'BASELINE_AND_DONOR_SCORES_CERTIFIED',extra)
        with heartbeat('Reuse frozen ENV rates and extend only missing pair/month requests',50,90):
            paths,extra['environment_extension']=inputs.prepare_environment(paths,binding,root/'environment',conf,a.workers,a.memory_gb)
        r.io.js(root/'PREPARED_INPUTS_PRIVATE.json',{k:str(v) for k,v in paths.items()})
        primary=fits.make_job(paths['S0'],scores['S0'],root/'fits/S0__full__A__X0_ENV_indicator',conf,'S0','iv','X0_ENV_indicator',figure=True)
        runtime.mapped(fits.fit_job,[primary],a.workers,a.memory_gb,'Primary A model and Figure 5',8,40)
        rows=u.load(Path(primary['output'])/'result.json')['estimates']
        fs=next(v for v in rows if v.get('estimator')=='first_stage')
        r.io.js(root/'common_scale.json',dict(common_score_SD=fs['native_residual_score_SD'],legacy_score_SD=BRIDGE_SD,fixed_bridge_score_SD=FIXED_SD,
            defining_model='Score A, S0 full, X0_ENV_indicator',n=fs['n'],row_set_sha256=fs['row_set_sha256']))
        lookup={};plan=[]
        for level in LEVELS:
            for variant,cohort in [('A','full'),('A','neutral'),('B','full'),('A','timing_common'),('B','timing_common'),('C','timing_common')]:
                name=f'S0__{cohort}__{variant}__{level}'
                job=primary if name==Path(primary['output']).name else fits.make_job(paths['S0'],scores['S0'],root/'fits'/name,conf,
                    'S0','iv',level,variant,cohort,material if cohort=='neutral' else None)
                plan.append(job);lookup[('S0',cohort,variant,level)]=job['output']
            for sample,kind in [('F','entry'),('O','ordinary')]:
                label=sample+str(phase['phase_percent']);job=fits.make_job(paths[sample],scores[sample],root/'fits'/f'{label}__A__{level}',conf,label,kind,level)
                plan.append(job);lookup[(sample,'full','A',level)]=job['output']
        r.io.js(root/'MODEL_PLAN_PRIVATE.json',plan)
        progress=50;report.export(root,desktop,conf,progress,'PRIMARY_SCALE_FIXED_CORE_PENDING',extra)
        runtime.mapped(fits.fit_job,[j for j in plan if j is not primary],a.workers,a.memory_gb,'Receipt, placebo, entry, balance and timing models',35,12)
        cjobs=[]
        for level in LEVELS:
            for label,left,right,outcomes in [
                ('after_minus_before',lookup[('S0','timing_common','C',level)],lookup[('S0','timing_common','B',level)],['y','reached','iv_y']),
                ('S0_minus_ordinary',lookup[('S0','full','A',level)],lookup[('O','full','A',level)],['y','reached'])]:
                cjobs.append(dict(left=left,right=right,label=label,outcomes=outcomes,level=level,conf=conf,output=str(root/'contrasts'/(label+'__'+level)),memory_gb=7.5))
        runtime.mapped(fits.contrast_job,cjobs,a.workers,a.memory_gb,'Stacked timing and placebo covariance',6,10)
        gjobs=[dict(input=str(paths['S0']),scores=str(scores['S0']),level=level,conf=conf,
            output=str(root/'calibration'/level),memory_gb=6.5) for level in LEVELS]
        runtime.mapped(fits.calibration_job,gjobs,a.workers,a.memory_gb,'Y-hat and D-hat implied-bias calibration',6,8)
        progress=75;report.export(root,desktop,conf,progress,'CORE_MODELS_AND_PAIRED_TESTS_COMPLETE',extra)
        gate=report.adoption(root)
        if gate.get('triggered'):
            djobs=[]
            for level in LEVELS:
                for label,sm,cm in [('new_score_old_controls','new','old'),('old_score_new_controls','old','matched')]:
                    djobs.append(fits.make_job(paths['S0'],scores['S0'],root/'fits'/('decomp_'+label+'__'+level),conf,'S0','iv',level,
                        score_mode=sm,control_mode=cm))
            runtime.mapped(fits.fit_job,djobs,a.workers,a.memory_gb,'Adoption threshold triggered: same-row decomposition',8,5);plan+=djobs
        if not a.skip_learning:
            ljobs=[];lcontrasts=[]
            for definition in ('full_chronology','flag_90d'):
                for level in LEVELS:
                    pair=[]
                    for value in (False,True):
                        out=root/'fits'/f'learning__{definition}__{int(value)}__{level}';pair.append(str(out))
                        ljobs.append(fits.make_job(paths['S0'],scores['S0'],out,conf,'S0','iv',level,flags=flags,split=[definition,value]))
                    lcontrasts.append(dict(left=pair[1],right=pair[0],label=definition+'_experienced_minus_unexperienced',outcomes=['y','reached','iv_y'],
                        level=level,conf=conf,output=str(root/'contrasts'/('learning__'+definition+'__'+level)),memory_gb=5.))
            runtime.mapped(fits.fit_job,ljobs,a.workers,a.memory_gb,'Optional learning splits on observed prior chooser decisions',10,3)
            # A tiny/unsupported split is reported, not sent to a nonexistent influence file.
            ready=[];missing=[]
            for j in lcontrasts:
                if all((Path(j[k])/'influence_PRIVATE.parquet').exists() for k in ('left','right')):ready.append(j)
                else:missing.append(dict(contrast=j['label'],level=j['level'],reason='unsupported stratum; no paired estimate'))
            extra['learning_contrasts_unavailable']=missing
            runtime.mapped(fits.contrast_job,ready,a.workers,a.memory_gb,'Learning-split shared covariance',3);plan+=ljobs
        r.io.js(root/'MODEL_PLAN_PRIVATE.json',plan)
        gate=report.adoption(root)
        progress=100;status='R9_COMPLETE_REVIEW_SHIFT_BEFORE_ADOPTION' if gate.get('triggered') else 'R9_COMPLETE'
        report.export(root,desktop,conf,progress,status,extra,plan)
        u.log('FINISHED. Return R9_CERTIFIED_REPORT_*_100.zip, its .sha256 sidecar, and the R9 run log. ETA: complete.')
    except BaseException as exc:
        extra['error_type']=type(exc).__name__;extra['error_message']=str(exc)
        try:report.export(root,desktop,conf,progress,'STOPPED_RETURN_LOG',extra)
        except Exception as failure:u.log('Stopped report export failed: '+str(failure))
        raise
    finally:lock.close()

if __name__=='__main__':main()
