#!/usr/bin/env python3
from common5 import *
import fcntl,subprocess,platform,traceback

def main():
    a=parser().parse_args();a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve()
    manifest=verify_package();require(a.project.is_dir(),'Research project drive is unavailable')
    hardware=c.resources(a.workers,a.memory_gb);a.workers=hardware['workers'];a.memory_gb=hardware['memory_budget_gib']
    os.environ['UNIFORM90_WORKERS']=str(a.workers);os.environ['UNIFORM90_MEMORY_GIB']=str(a.memory_gb)
    parent=a.project/'derived/replication/receipt_iv_uniform90_v100_PRIVATE'/cert.CONF[:12]
    c.frozen.u.no_network()
    with cert.heartbeat('Authenticating completed Model 5 source and scores'):
        binding=cert.input_binding(ROOT/'NO_SUPPLEMENT_DESIGN',parent)
    plan=[j for j in load(parent/'PRIVATE/MODEL_PLAN90.json') if j['name']=='uniform_unspaced']
    baseline=Path(plan[0]['output'])/'result.json'
    config=dict(version='1.0.0',package_manifest=manifest,parent_configuration=cert.CONF,inputs=cert.INPUTS,
        project=str(a.project),primary_row_set=cert.ROW_HASH,badge_snapshot='August2026',headline='instrument_to_Patron_reduced_form',weights='original_acquisition_IPW',api_requests=0)
    a.conf=c.key(config);base=(a.work_dir or a.result_dir/'Patron_Model5_PRIVATE').expanduser().resolve();a.run=base/a.conf[:12]
    require(not base.is_relative_to(parent) and not parent.is_relative_to(base),'Private work directory overlaps the completed parent')
    (a.run/'PRIVATE').mkdir(parents=True,exist_ok=True);(a.run/'report').mkdir(exist_ok=True);a.result_dir.mkdir(parents=True,exist_ok=True)
    require(shutil.disk_usage(a.run).free>=40*2**30,'Need 40 GiB free for subset frames, projection and covariance spill')
    with (a.run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This Patron Model 5 run is already active')
        if (a.run/'config.json').exists():require(load(a.run/'config.json')==config,'Run configuration changed')
        else:save(a.run/'config.json',config)
        save(a.run/'PRIVATE/BINDING.json',dict(source=str(binding['source']),scores=str(binding['scores']),baseline=str(baseline),parent=str(parent)))
        save(a.run/'report/definition.json',dict(config,primary_exposures=cert.N,primary_recipients=cert.PEOPLE,score_SD=SD,
            primary_model='uniform_unspaced; all-time-five Score A; X0_ENV_indicator; log_volume_90',
            covariance='shared-account-OR-exposure-date CR0; repeated Patron outcomes retained; generated scores held fixed',
            sensitivity_models=['equal observed exposure weights','inverse original sampling probability divided by full-frame exposures per recipient','prior-chooser subset with universal positive support'],
            outcome='Current Patron badge in the original August 2026 profile snapshot; not adoption or self-funded payment',
            scientific_scope='Reduced-form instrument–badge association is primary. 2SLS is secondary and inherits the receipt-IV assumptions. Missing profiles stay missing; IPW cannot restore zero-support accounts.'))
        save(a.run/'report/runtime.json',dict(python=platform.python_version(),numpy=np.__version__,pyarrow=pa.__version__,hardware=hardware,api_requests=0,engine_evaluations=0,provisional_runtime='1–3 hours; not benchmarked on private production data',os_memory_cap=False))
        shutil.copyfile(ROOT/'METHODS.txt',a.run/'report/METHODS.txt')
        save(a.result_dir/'PATRON_MODEL5_LATEST_PRIVATE.json',dict(root=str(a.run),configuration_sha256=a.conf));log('RUN '+str(a.run))
        percent=0;started=time.monotonic()
        steps=[('fit_badge.py','baseline',25),('link_badge.py','link',50),('fit_badge.py','primary',75),('fit_badge.py','sensitivities',100)]
        forecasts=[25,15,55,85]
        try:
            for ix,(script,mode,mark) in enumerate(steps):
                log(f'{percent}% | {mode} | elapsed {(time.monotonic()-started)/60:.1f} min | provisional next checkpoint {forecasts[ix]} min; finish {sum(forecasts[ix:])} min')
                subprocess.run([sys.executable,'-u',str(ROOT/'code'/script),'--project',str(a.project),'--result-dir',str(a.result_dir),'--run',str(a.run),'--conf',a.conf,'--mode',mode,'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)],check=True)
                percent=mark;export(a.run,a.result_dir,percent,'COMPLETE' if mark==100 else 'IN_PROGRESS')
            log('COMPLETE: updated Patron reduced form, receipt IV, profile-selection diagnostics and sensitivities. Upload the aggregate _100 ZIP and checksum.')
        except BaseException:
            traceback.print_exc();export(a.run,a.result_dir,percent,'STOPPED');raise
if __name__=='__main__':main()
