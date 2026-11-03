#!/usr/bin/env python3
"""Offline, resumable R7 analysis runner for the authenticated Run 2/Phase-050 caches."""
from r7_common import *
import r7_inputs, r7_reproduce, r7_models, r7_moves, r7_composition, r7_report
from performance_runtime import Runtime
from r7_schedule import fit_map
import r7_resume, r7_outcomes, r7_preflight
import argparse,fcntl

def plan(paths,root,conf):
    jobs=[]
    def add(source,selection,sample,level='X0',instrument='pooled',fe=False,A=True,influence=False):
        key='_'.join([sample,level,instrument,'recipientFE' if fe else 'pooled'])
        n=pq.ParquetFile(paths[source]).metadata.num_rows
        jobs.append(dict(input=str(paths[source]),selection=selection,sample=sample,level=level,instrument=instrument,
            kind={'S0':'iv','F50':'entry','O50':'ordinary'}[source],recipient_fe=fe,part_a=A,calibration=A,
            influence=influence,output=str(root/'models'/key),conf=conf,
            memory_estimate_gb=1.0+n*(1200 if A else 850)/1024**3))
    add('S0','','S0',influence=True)
    add('S0','','S0','X0_ENV_indicator',influence=True)
    for level in ('X0','X0_volume','X0_volume_own','X0_volume_chooser','X0_ENV'):
        add('S0','env','S0_env',level,A=level in ('X0','X0_ENV'),influence=level in ('X0','X0_ENV'))
    for level in ('X0','X0_ENV','XC','XC_ENV'):add('S0','comp_env','S0_CSE',level)
    add('S0','comp','S0_CS','X0','competitive')
    for source in ('F50','O50'):
        for selection,suffix,level in [('', '', 'X0'),('', '', 'X0_ENV_indicator'),('env','_env','X0'),('env','_env','X0_ENV')]:
            add(source,selection,source+suffix,level,A=source=='F50',influence=source=='O50')
    for selection,sample in [('comp','F50_CS'),('comp_env','F50_CSE')]:
        for level in ('X0','X0_ENV_indicator' if selection=='comp' else 'X0_ENV'):
            add('F50',selection,sample,level,'competitive',A=False)
    for selection,sample,levels in [('repeat','S0_repeat',('X0','X0_ENV_indicator')),('repeat_env','S0_repeat_env',('X0','X0_ENV'))]:
        for level in levels:
            for fe in (False,True):add('S0',selection,sample,level,fe=fe,A=False)
    return jobs

def execute(a):
    threads_one();no_network();verify_package();started=time.monotonic()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if not project.is_dir():raise RuntimeError('Project drive unavailable: '+str(project))
    workers=max(1,min(a.workers,10,os.cpu_count() or 1,int(max(1,(a.memory_gb-2)//1.5))))
    with io.heartbeat('Authenticating completed environment and Phase-050 files'):
        binding=r7_inputs.authenticate(project,a.environment_root,a.phase50_root)
    reused_paths=None;reuse=None;gate_reuse=None
    if a.reuse_r7_root is not None:
        with io.heartbeat('Verifying completed R7 ENV tables for read-only reuse'):
            reused_paths,reuse=r7_resume.bind(a.reuse_r7_root,binding)
        io.log('R7 ENV_REUSE_VERIFIED: 120 chronology tasks will not be repeated')
    if a.reuse_reproduction_root is not None:
        with io.heartbeat('Verifying the completed v1.0.2 numerical reproduction gate'):
            gate_reuse=r7_resume.bind_reproduction(a.reuse_reproduction_root,binding)
        io.log('R7 REPRODUCTION_REUSE_VERIFIED: all nine passed production checks are preserved')
    config=dict(version=VERSION,package_sha256=io.sha(ROOT/'PACKAGE_MANIFEST.sha256'),
        environment_conf=binding['environment']['conf'],phase50_conf=binding['phase50']['conf'],
        original_n=2682330,diagnostic_n=2682329,folds=4,author_ids=binding['author_ids'],
        move_roots=[str(p.expanduser().resolve()) for p in a.move_root],spec_sha256=io.sha(ROOT/'R7_SPEC.md'),reused_r7=
        {k:reuse[k] for k in ('root','config_sha256')} if reuse else None,
        reused_reproduction={k:gate_reuse[k] for k in ('root','config_sha256')} if gate_reuse else None)
    conf=io.cfgsha(config);root=project/'derived/replication/r7_analysis_v103_PRIVATE'/conf[:12];root.mkdir(parents=True,exist_ok=True)
    runtime=Runtime(root);jobs=[]
    with (root/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This R7 configuration is already running')
        io.js(root/'config.json',config);io.js(root/'INPUTS_PRIVATE.json',binding)
        if reuse:io.js(root/'REUSED_R7_PRIVATE.json',reuse)
        if gate_reuse:io.js(root/'REUSED_REPRODUCTION_PRIVATE.json',gate_reuse)
        io.js(desktop/'R7_ANALYSIS_LATEST_PRIVATE.json',dict(root=str(root),config_sha256=conf))
        try:
            with runtime.stage('Reuse verified reproduction gate' if gate_reuse else 'Full-precision reproduction gate'):
                if gate_reuse:r7_resume.reuse_reproduction(gate_reuse,binding,root/'reproduction',conf)
                else:r7_reproduce.run(binding,root/'reproduction',conf)
            r7_report.export(root,desktop,conf,'REPRODUCTION_PASSED',started)
            if a.reproduce_only:return root
            with runtime.stage('Reuse ENV and extend only missing pair/month histories'):
                paths=reused_paths if reused_paths is not None else r7_inputs.prepare_environment(binding,root/'prepared',conf,a.memory_gb,workers,runtime)
            with runtime.stage('Attach authenticated cached F50 later outcomes'):
                paths,outcome_info=r7_outcomes.prepare(paths,binding,root/'entry_outcomes',conf,a.memory_gb)
                io.log(f"F50 outcomes attached: {outcome_info['rows']:,} unchanged rows; {outcome_info['incomplete90_rows']:,} incomplete windows retained as missing")
            io.js(root/'PREPARED_INPUTS_PRIVATE.json',{k:str(v) for k,v in paths.items()})
            io.js(root/'support.json',r7_inputs.support_report(paths))
            jobs=plan(paths,root,conf);io.js(root/'MODEL_PLAN_PRIVATE.json',jobs)
            with runtime.stage('Input schema preflight for every A/B model and C endpoint'):
                io.js(root/'input_preflight.json',r7_preflight.check(jobs,paths,binding,include_c=a.parts=='ABC'))
            io.log(f'R7 INPUT_PREFLIGHT_OK: all {len(jobs)} A/B model schemas verified')
            io.log(f'R7 A/B: {len(jobs)} resumable fits; up to {workers} workers, RAM-limited. Original scores are unchanged.')
            fit_map(r7_models.model_job,jobs,runtime,workers,a.memory_gb,'R7 A/B',
                lambda:r7_report.export(root,desktop,conf,'AB_MODELS_IN_PROGRESS',started,len(jobs)+2))
            def contrasts(tmp):
                result=[]
                for suffix,level in [('', 'X0'),('', 'X0_ENV_indicator'),('_env','X0'),('_env','X0_ENV')]:
                    left=next(j for j in jobs if j['sample']=='S0'+suffix and j['level']==level and j['instrument']=='pooled' and not j['recipient_fe'])
                    right=next(j for j in jobs if j['sample']=='O50'+suffix and j['level']==level)
                    meta=dict(control_level=level,instrument='pooled',sample='S0'+suffix+'_minus_O50'+suffix,
                        units='percentage points per reference score SD',reference_score_SD=SD['pooled'],
                        clustering='shared_account_OR_date_CR0',nominal_interim_intervals=True,
                        diagnostic_after_reviewed_results=True,causal_identification_certified=False)
                    result+=r7_models.contrast(left['output'],right['output'],meta)
                io.js(tmp/'result.json',result);return dict(contrasts=len(result))
            stable_stage(root/'contrasts',conf,contrasts,[Path(j['output'])/'result.json' for j in jobs if j['influence']])
            r7_report.export(root,desktop,conf,'AB_COMPLETE_C_PENDING',started,len(jobs)+2)
            if a.parts=='AB':return root
            with runtime.stage('Recorded exit features from existing move caches'):
                cpaths,coverage=r7_moves.prepare(paths,binding,project,root/'composition',conf,a.memory_gb,workers,runtime,a.move_root)
            cjobs=[]
            for sample,path in cpaths.items():
                n=pq.ParquetFile(path).metadata.num_rows
                cjobs.append(dict(input=str(path),sample=sample,output=str(root/'models'/('C_'+sample)),conf=conf,memory_estimate_gb=1.0+n*1150/1024**3))
            fit_map(r7_composition.job,cjobs,runtime,workers,a.memory_gb,'R7 C',
                lambda:r7_report.export(root,desktop,conf,'C_IN_PROGRESS',started,len(jobs)+2))
            summary=r7_report.export(root,desktop,conf,'R7_ANALYSIS_COMPLETE',started,len(jobs)+2)
            io.js(root/'SUCCESS.json',summary)
        except BaseException as exc:
            r7_report.export(root,desktop,conf,'STOPPED_WITH_PARTIAL_RESULTS',started,len(jobs)+2,type(exc).__name__+': '+str(exc))
            raise
    return root

def main():
    workers,memory=upstream.defaults()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--environment-root',type=Path);p.add_argument('--phase50-root',type=Path)
    p.add_argument('--workers',type=int,default=workers);p.add_argument('--memory-gb',type=float,default=memory)
    p.add_argument('--move-root',type=Path,action='append',default=[],help='Additional existing move-cache folder; never downloaded')
    p.add_argument('--reuse-r7-root',type=Path,help='Read-only reuse of the completed ENV extension in reviewed R7 v1.0.0 run dae86f8a1785')
    p.add_argument('--reuse-reproduction-root',type=Path,help='Reuse the verified production reproduction gate in R7 v1.0.2 run 30547781f2c4')
    p.add_argument('--parts',choices=['AB','ABC'],default='ABC');p.add_argument('--reproduce-only',action='store_true')
    a=p.parse_args()
    if a.workers<1 or a.memory_gb<4:p.error('At least one worker and 4 GiB required')
    execute(a)

if __name__=='__main__':main()
