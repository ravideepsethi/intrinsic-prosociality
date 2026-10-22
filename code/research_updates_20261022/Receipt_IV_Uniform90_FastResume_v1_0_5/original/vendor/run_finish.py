#!/usr/bin/env python3
"""Finish the reviewed v1.0.3 report using its eight completed comparison fits."""
from rebuild_common import *
import argparse,contextlib,fcntl,subprocess,traceback,platform,csv
import run_rebuild as exporter
import rebuild_models as previous
import finish_covariance as bounded

VERSION='1.0.5'
PARENT_CONF='5eca56c416c537930e86893b4a061420ec3cbc5f232dce83fa218ac70f4ad8c5'
PARENT_PACKAGE='c056b76b9a2fe30ff7009ef1b20380c8263475362cde752cad560d8e0efc2f9d'
PARENT_REPORT='4519e52db15e0715ffc61e95d433ef4ce2858bbab8f8ea0ae1d255d24e5c04bb'
EXPECTED_ROWS={'legacy_F':14742651,'legacy_O':9528012,'totalfive_F':17745415,'totalfive_O':11410477}
exporter.VERSION=VERSION


class Authentication:
    """Hash each unique file once per invocation; never trust a filename alone."""
    def __init__(self):self.files={};self.stages=[]
    def file(self,path,digest,size=None):
        path=Path(path).resolve();before=frozen.r.io.sig(path)
        if path not in self.files:
            actual=sha(path);require(frozen.r.io.sig(path)==before,'File changed during verification: '+str(path))
            self.files[path]=(before,actual)
        signature,actual=self.files[path]
        require(signature==before and actual==digest,'Saved file changed: '+str(path))
        require(size is None or path.stat().st_size==size,'Saved file size changed: '+str(path))
    def stage(self,folder,conf,needed=(),expected_dependencies=None):
        folder=Path(folder);receipt_path=folder/'_DONE.json'
        require(receipt_path.is_file(),'Completed checkpoint missing; no rebuild fallback: '+str(folder))
        receipt=load(receipt_path);require(receipt['config_sha256']==conf,'Checkpoint configuration differs: '+str(folder))
        names=set()
        for item in receipt['files']:
            path=(folder/item['path']).resolve()
            require(path.is_relative_to(folder.resolve()),'Unsafe checkpoint member')
            require(item['path'] not in names,'Duplicate checkpoint member')
            names.add(item['path']);self.file(path,item['sha256'],item['bytes'])
        require(set(needed).issubset(names) and 'dependencies_PRIVATE.json' in names,'Uncertified checkpoint outputs')
        deps=load(folder/'dependencies_PRIVATE.json')
        if expected_dependencies is not None:
            require([str(Path(x['path']).resolve()) for x in deps]==[str(Path(x).resolve()) for x in expected_dependencies],
                    'Model dependencies differ from the reviewed binding: '+str(folder))
        for item in deps:self.file(item['path'],item['sha256'])
        self.stages.append(dict(path=str(folder),configuration=conf,receipt_sha256=sha(receipt_path)))
        return receipt


def verify_parent_header(parent,project):
    cfg=load(parent/'config.json')
    require(key(cfg)==PARENT_CONF,'Parent is not the reviewed 5eca56c416c5 run')
    require(cfg['version']=='1.0.3' and cfg['package_manifest_sha256']==PARENT_PACKAGE,'Parent producer differs')
    require(cfg['project']==str(project),'Parent project differs')
    require(cfg['rule']==RULE,'Scientific rules differ from the completed rebuild')
    require(sha(parent/'report/REPORT_MANIFEST.json')==PARENT_REPORT,
            'Parent report changed since the uploaded 75% checkpoint; stop and return the new report')
    status=load(parent/'report/STATUS.json')
    require(status['configuration_sha256']==PARENT_CONF and status['progress_percent']==75,'Unexpected parent progress')
    for name in ('authenticate','candidates','chronology','metadata_audit','metadata','frames'):
        require(status['stages'][name]['status']=='COMPLETE','Earlier stage is incomplete: '+name)
    return cfg


def authenticate(a,run,conf):
    parent=a.reuse_completed;verify_parent_header(parent,a.project);auth=Authentication()
    manifest=load(ROOT/'evidence/v103_075_REPORT_MANIFEST.json')
    require(sha(ROOT/'evidence/v103_075_REPORT_MANIFEST.json')==PARENT_REPORT,'Reviewed report evidence changed')
    for rec in manifest:auth.file(parent/'report'/rec['path'],rec['sha256'],rec['bytes'])
    validation=load(parent/'report/model_validation.json')
    require(validation['comparison_models_complete']==8 and validation['comparison_models_planned']==8 and
            validation['corrected_primary_reproduced'] and validation['contrasts_complete']==1,'Parent completion gates differ')
    b=bind(parent);plan=load(parent/'PRIVATE/MODEL_PLAN.json');expected=[]
    auth.stage(parent/'PRIVATE/frames',PARENT_CONF,('F.parquet','O.parquet','F_scores.parquet','O_scores.parquet','overlap.json'))
    log('Verified completed frames and their input hashes. Checking the eight completed model checkpoints.')
    for level in r9.LEVELS:
        for sample,kind in [('F','entry'),('O','ordinary')]:
            for legacy in (True,False):
                source=b['old_paths'][sample] if legacy else parent/'PRIVATE/frames'/(sample+'.parquet')
                scores=b['old_scores'][sample] if legacy else parent/'PRIVATE/frames'/(sample+'_scores.parquet')
                label=('legacy_' if legacy else 'totalfive_')+sample
                out=parent/'PRIVATE/models'/(label+'__'+level)
                job=fits.make_job(source,scores,out,PARENT_CONF,label,kind,level)
                job.update(memory=4.,memory_gb=9.);expected.append(job)
                auth.stage(out,PARENT_CONF,('result.json','influence_PRIVATE.parquet'),[source,scores])
                result=load(out/'result.json')
                require(all(x['n']==EXPECTED_ROWS[label] and x['control_level']==level and x['sample']==label
                            for x in result['estimates']),'Completed model population differs')
                require(pq.ParquetFile(out/'influence_PRIVATE.parquet').metadata.num_rows==EXPECTED_ROWS[label],
                        'Influence row coverage differs')
                if legacy:
                    old=Path(b['comparison_root'])/'fits'/(sample+'100__A__'+level)
                    auth.stage(old,b['comparison_conf'],('result.json','influence_PRIVATE.parquet'))
                    previous.replay_check(result,load(old/'result.json'))
                log(f'Authenticated completed comparison fit {len(expected)}/8: {label} {level}')
    require(plan==expected,'Completed model plan changed')
    primary=b['primary'];receipt=parent/'PRIVATE/models/receipt__X0_ENV_indicator'
    auth.stage(receipt,PARENT_CONF,('result.json','influence_PRIVATE.parquet'),[primary['primary'],primary['primary_scores']])
    iv=next(x for x in load(receipt/'result.json')['estimates'] if x['estimator']=='2SLS')
    require(abs(iv['iv_coefficient_pp']-.36280640903671635)<2e-9 and
            abs(iv['iv_standard_error_pp']-.096407515226692)<2e-9,'Accepted main IV does not reproduce')
    first=parent/'PRIVATE/contrasts/new_receipt_minus_new_ordinary__X0_ENV_indicator'
    auth.stage(first,PARENT_CONF,('result.json',),
               [p/n for p in (receipt,parent/'PRIVATE/models/totalfive_O__X0_ENV_indicator')
                for n in ('result.json','influence_PRIVATE.parquet')])
    # Keep report provenance and model paths explicit. No large frame/fit is copied
    # into the new run, and the old directories are never written.
    for rec in manifest:
        if rec['path'] in ('STATUS.json','REPORT_MANIFEST.json','README.txt','runtime.json','model_validation.json'):continue
        shutil.copyfile(parent/'report'/rec['path'],run/'report'/rec['path'])
    save(run/'PRIVATE/MODEL_PLAN.json',plan);save(run/'PRIVATE/BINDING.json',b)
    save(run/'report/model_validation.json',dict(validation,parent_configuration=PARENT_CONF,
       comparison_models_recomputed=0,completed_comparison_models_reused=8,patron_placebo_calculated=False))
    def import_first(tmp):
        shutil.copyfile(first/'result.json',tmp/'result.json')
        return dict(imported_from_configuration=PARENT_CONF,recomputed=False,source_receipt_sha256=sha(first/'_DONE.json'))
    stage(run/'PRIVATE/contrasts'/first.name,conf,import_first,[first/'result.json',first/'_DONE.json'])
    provenance=dict(parent_configuration=PARENT_CONF,parent_report_manifest_sha256=PARENT_REPORT,
        parent_package_manifest_sha256=PARENT_PACKAGE,authenticated_stages=auth.stages,
        unique_files_hashed=len(auth.files),old_files_modified=False,comparison_models_recomputed=0,
        metadata_requests=0,frame_rebuilds=0,raw_game_scans=0,covariance_algorithm=bounded.ALGORITHM,
        scientific_formula_changed=False,patron_placebo_included=False)
    save(run/'report/finish_reuse.json',provenance)
    return b


def finish(run,conf,parent,b):
    validation=load(run/'report/model_validation.json');checks=[]
    for level in r9.LEVELS:
        if level=='X0_ENV_indicator':receipt=parent/'PRIVATE/models'/('receipt__'+level)
        else:
            receipt=run/'PRIVATE/models'/('receipt__'+level)
            job=fits.make_job(b['primary']['primary'],b['primary']['primary_scores'],receipt,conf,'receipt_total5','iv',level)
            log('Completing the remaining 3.1-million-row receipt X0 fit; all eight comparison fits are reused.')
            with heartbeat('Receipt X0 fit'):fits.fit_job(job)
        comparisons=[dict(left=str(receipt),right=str(parent/'PRIVATE/models'/('totalfive_O__'+level)),
                          label='new_receipt_minus_new_ordinary',outcomes=['y','reached'])]
        for sample,outs in [('F',['analysis_entry_90','recipient_disconnect_main','active_timeout']),('O',['y','reached'])]:
            comparisons.append(dict(left=str(parent/'PRIVATE/models'/('totalfive_'+sample+'__'+level)),
                right=str(parent/'PRIVATE/models'/('legacy_'+sample+'__'+level)),label=sample+'_new_minus_old',outcomes=outs))
        for job in comparisons:
            name=job['label']+'__'+level
            job.update(level=level,conf=conf,output=str(run/'PRIVATE/contrasts'/name),work=str(run/'PRIVATE/covariance'/name))
            if name=='new_receipt_minus_new_ordinary__X0_ENV_indicator':
                require(frozen.r.io.complete(job['output'],conf) is not None,'Imported contrast missing')
            else:
                log('Starting remaining contrast: '+name)
                with heartbeat('Contrast '+name):bounded.contrast_job(job)
            checks.append(job);validation['contrasts_complete']=len(checks)
            save(run/'report/model_validation.json',validation)
            log(f'Final contrasts {len(checks)}/6 complete')
    require(len(checks)==6 and validation['comparison_models_complete']==8 and validation['corrected_primary_reproduced'],
            'Final validation gates incomplete')
    save(run/'PRIVATE/CONTRAST_PLAN.json',checks)


class Tee:
    def __init__(self,*streams):self.streams=streams
    def write(self,text):
        for stream in self.streams:stream.write(text);stream.flush()
        return len(text)
    def flush(self):
        for stream in self.streams:stream.flush()


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--reuse-completed',type=Path,help='The reviewed v1.0.3 5eca56c416c5 run; read-only')
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--self-test',action='store_true')
    return p


def main():
    a=parser().parse_args()
    if a.self_test:return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)
    package=exporter.verify();a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve()
    a.reuse_completed=(a.reuse_completed or a.project/'derived/replication/alltime_entry_placebo_v103_PRIVATE'/PARENT_CONF[:12]).expanduser().resolve()
    a.audit_only=False;require(a.project.is_dir(),'Project drive is not mounted')
    frozen.u.no_network();frozen.r.threads_one()
    config=dict(version=VERSION,package_manifest_sha256=package,rule=RULE,project=str(a.project),
                parent=str(a.reuse_completed),parent_configuration=PARENT_CONF,parent_report_manifest=PARENT_REPORT,
                covariance_algorithm=bounded.ALGORITHM)
    conf=key(config);run=a.project/'derived/replication/alltime_entry_placebo_v105_PRIVATE'/conf[:12]
    for folder in (run,run/'PRIVATE',run/'report',a.result_dir):folder.mkdir(parents=True,exist_ok=True)
    with exporter.prior_runs_stopped(a.project,run),(run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This finish repair is already running')
        if (run/'config.json').exists():require(load(run/'config.json')==config,'Finish definition changed')
        else:save(run/'config.json',config)
        with (run/'run.log').open('a',buffering=1) as output,contextlib.redirect_stdout(Tee(sys.stdout,output)),contextlib.redirect_stderr(Tee(sys.stderr,output)):
            state={};progress=0
            try:
                require(shutil.disk_usage(run).free>=40*2**30,'At least 40 GiB free is needed for bounded covariance checkpoints')
                save(a.result_dir/'ALLTIME_ENTRY_PLACEBO_LATEST_PRIVATE.json',dict(root=str(run),configuration_sha256=conf))
                log('v1.0.5 finish repair: no API requests, no frame rebuild, no comparison refits. Verifying saved inputs first.')
                with heartbeat('Authenticating completed v1.0.3 fits'):b=authenticate(a,run,conf)
                state=load(a.reuse_completed/'report/STATUS.json')['stages'];state['models']=dict(status='RUNNING',execution='v105_finish_from_v103')
                progress=75
                save(run/'report/runtime.json',dict(version=VERSION,python=platform.python_version(),duckdb=bounded.duckdb.__version__,
                    platform=platform.platform(),workers=1,covariance_duckdb_decimal_gb=4.,covariance_buckets=128,
                    covariance_arrow_buffer_mib=64,additional_API_requests=0,comparison_fits_reused=8))
                exporter.export(a,run,conf,state,progress)
                # The inherited complete fits must regenerate exactly the reviewed
                # aggregate tables before any remaining calculation is attempted.
                for item in load(ROOT/'evidence/v103_075_REPORT_MANIFEST.json'):
                    if item['path'].endswith('.csv') and item['path'] not in ('new_receipt_minus_new_ordinary.csv','F_new_minus_old.csv','O_new_minus_old.csv'):
                        require(sha(run/'report'/item['path'])==item['sha256'],'Reviewed aggregate table changed: '+item['path'])
                finish(run,conf,a.reuse_completed,b)
                state['models']=dict(status='COMPLETE',execution='v105_finish_from_v103',comparison_fits_reused=8,contrasts_complete=6)
                progress=100;save(run/'PRIVATE/STATE.json',state);exporter.export(a,run,conf,state,progress)
                log('COMPLETE: return ALLTIME_ENTRY_PLACEBO_'+conf[:12]+'_100.zip and its .sha256.')
                return 0
            except (Exception,KeyboardInterrupt) as exc:
                error=type(exc).__name__+': '+str(exc);log(error);traceback.print_exc()
                state['models' if progress else 'finish_authentication']=dict(status='FAILED')
                save(run/'PRIVATE/STATE.json',state);exporter.export(a,run,conf,state,progress,error)
                return 130 if isinstance(exc,KeyboardInterrupt) else 1


if __name__=='__main__':sys.exit(main())
