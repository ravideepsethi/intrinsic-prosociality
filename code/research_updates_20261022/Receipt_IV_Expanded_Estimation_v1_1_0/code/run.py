#!/usr/bin/env python3
"""Fit the expanded calendar-cohort receipt IV from completed local private cohorts."""
import os
for _k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[_k]='1'
import argparse,csv,fcntl,gc,platform,shutil,time,traceback,zipfile
from common import *
import contracts,design,prepare,model

def signature():
    paths=[*sorted((PACKAGE/'code').glob('*.py')),*sorted((PACKAGE/'vendor').glob('*.py')),
           *sorted((PACKAGE/'authority').glob('*')),PACKAGE/'DESIGN_FREEZE.json']
    return digest({str(p.relative_to(PACKAGE)):sha(p) for p in paths if p.is_file()})

def flat_csv(path,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for r in clean(rows):w.writerow({k:json.dumps(v,separators=(',',':')) if isinstance(v,(list,dict)) else v for k,v in r.items()})

def fit_one(path,spec,root,code,inputs,threads,memory_mb,auth):
    key=digest(dict(code=code,spec=spec,inputs=inputs,freeze=design.freeze()))
    def producer(tmp):
        began=time.monotonic()
        c=connection(tmp/'spill',threads,memory_mb);c.execute('SET enable_progress_bar=false')
        try:d=prepare.load_model(c,path,spec)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        log(spec['name']+f': {len(d["row_id"]):,} rows; fitting')
        try:
            result=model.estimate(d,spec)
        except RuntimeError as e:
            # A slow/nonconvergent FE diagnostic must not invalidate completed
            # pooled results. Structural and other numerical errors still stop.
            if spec['fe'] and str(e).startswith('FE absorption did not converge'):
                result=dict(estimates=[dict(specification=spec['name'],supported=False,reason=str(e))],
                    balance=[],joint_balance=[],design=spec,sample_accounting=model.original.describe(d),
                    exclusion_sensitivity=dict(supported=False,reason='FE_DID_NOT_CONVERGE',fixed=[],bounds=[]))
            else:raise
        result['elapsed_seconds']=time.monotonic()-began
        write_json(tmp/'result.json',result)
        return dict(specification=spec['name'],rows=len(d['row_id']),elapsed_seconds=result['elapsed_seconds'])
    return stage(root/'models'/spec['name']/key,key,inputs,producer,auth)

def assemble_outputs(results,public):
    estimates=[];balance=[];joint=[];fixed=[];bounds=[];tipping=[];accounts={};designs={};timings=[]
    for spec,result in results:
        name=spec['name'];estimates+=result['estimates'];balance+=result['balance'];joint+=result['joint_balance']
        accounts[name]=result['sample_accounting'];designs[name]=result['design']
        timings.append(dict(specification=name,elapsed_seconds=result['elapsed_seconds']))
        s=result['exclusion_sensitivity']
        fixed += [dict(specification=name,**r) for r in s.get('fixed',[])]
        bounds += [dict(specification=name,**r) for r in s.get('bounds',[])]
        tipping.append(dict(specification=name,**{k:v for k,v in s.items() if k not in ('fixed','bounds')}))
    for a,b in [('calendar90_primary','calendar90_without_recipient_history'),
                ('calendar90_primary','calendar90_legacy_controls'),
                ('calendar90_repeat_pooled','calendar90_repeat_FE_diagnostic'),
                ('calendar90_lag_common_7d','calendar90_lag_common_30d')]:
        if a in accounts and b in accounts and accounts[a]['row_set_sha256']!=accounts[b]['row_set_sha256']:
            raise RuntimeError('Declared common-row fits do not have identical rows')
    for name,rows in [('ESTIMATES',estimates),('BALANCE',balance),('JOINT_BALANCE',joint),
                      ('EXCLUSION_FIXED_GAMMA',fixed),('EXCLUSION_BOUNDED_GAMMA',bounds),('TIPPING_POINTS',tipping),('MODEL_TIMINGS',timings)]:
        write_json(public/(name+'.json'),rows);flat_csv(public/(name+'.csv'),rows)
    write_json(public/'MODEL_ACCOUNTING.json',accounts);write_json(public/'MODEL_DESIGNS.json',designs)
    common=accounts.get('calendar90_common10')
    if common:
        write_json(public/'COMMON_FLOOR_COMPARISON.json',dict(status='IDENTICAL_SCORE_AND_COMMON_ROWS',
            common_row_set_sha256=common['row_set_sha256'],rows=common['rows'],
            floor5_common_fit='calendar90_common10',floor10_common_fit='calendar90_common10',
            score_difference=0,coefficient_difference=0,
            interpretation='The thresholds change eligibility, not the score. Both labels reference one fit; this is an algebraic identity, not an independent robustness finding.'))
    return estimates

PUBLIC_NAMES={'RUN_CONFIGURATION.json','DESIGN_FREEZE.json','ACCOUNT_POLICY.json','SUMMARY.json','ERRORS.json',
    'READ_ME_FIRST.txt','HISTORICAL_REPRODUCTION.json','HISTORICAL_MEMBERSHIP_BRIDGE.json',
    'SAMPLE_ACCOUNTING.json','COMMON_HISTORY_CONTRACT.json','COMMON_FLOOR_COMPARISON.json',
    'MODEL_ACCOUNTING.json','MODEL_DESIGNS.json','GATES.json'}
for _n in ('ESTIMATES','BALANCE','JOINT_BALANCE','EXCLUSION_FIXED_GAMMA','EXCLUSION_BOUNDED_GAMMA','TIPPING_POINTS','MODEL_TIMINGS'):
    PUBLIC_NAMES.update({_n+'.json',_n+'.csv'})
for _n in ('PRIMARY_COUNTS_BY_MONTH','HISTORICAL_MEMBERSHIP_BY_MONTH','CALENDAR_REGIME_COUNTS','LATER_CHOICE_POLICY_DESCRIPTIVE'):
    PUBLIC_NAMES.update({_n+'.csv',_n+'.parquet'})

def export_report(report,desktop):
    files=[p for p in sorted(report.iterdir()) if p.is_file()]
    if any(p.name not in PUBLIC_NAMES for p in files):raise RuntimeError('Unexpected public output; not exported')
    write_json(report/'RESULT_MANIFEST.json',dict(files=[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in files]))
    dest=desktop/(report.name+'.zip')
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files+[report/'RESULT_MANIFEST.json']:z.write(p,report.name+'/'+p.name)
    dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    return dest

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=ORIGINAL_PROJECT)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10)
    ap.add_argument('--memory-gb',type=int,default=8,help='DuckDB/working-memory planning budget; NumPy fits run sequentially')
    a=ap.parse_args(argv)
    if not 1<=a.workers<=10:ap.error('workers must be 1–10')
    if not 4<=a.memory_gb<=64:ap.error('memory-gb must be 4–64')
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if not project.is_dir() or not desktop.is_dir():ap.error('Project drive and Lichess_Desktop must exist')
    contracts.verify_package();pa.set_cpu_count(1);pa.set_io_thread_count(1)
    work=project/'derived/replication_36m/receipt_iv_expanded_estimation_v110_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=(work/'run.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This estimator is already running')
    began=time.monotonic();code=signature();auth=work/'authentication'
    runid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    public=project/'output/receipt_iv_expanded_estimation_v110'/('RECEIPT_IV_EXPANDED_ESTIMATION_'+runid);public.mkdir(parents=True)
    # Freeze precedes all data access and model estimation.
    write_json(public/'DESIGN_FREEZE.json',design.freeze())
    write_json(public/'ACCOUNT_POLICY.json',contracts.ACCOUNT_POLICY)
    write_json(public/'RUN_CONFIGURATION.json',dict(version=VERSION,code_signature=code,workers_limit=a.workers,
        memory_planning_gb=a.memory_gb,python=platform.python_version(),duckdb=duckdb.__version__,pyarrow=pa.__version__,numpy=np.__version__,
        exclusion_applied=False,endpoint=design.ENDPOINT_UTC,lichess_requests=0,Stockfish_calls=0))
    phase='authenticate';errors=[];results=[];historical_pass=False;prepared=None;root=None;estimates=[]
    try:
        with heartbeat('Authenticating completed cohorts'):
            inputs=contracts.authenticate(project,work)
        binding=digest(dict(code=code,inputs=inputs['snapshots']));root=work/'runs'/binding;root.mkdir(parents=True,exist_ok=True)
        write_json(root/'DESIGN_FREEZE.json',design.freeze())
        write_json(root/'INPUT_CONTRACT_PRIVATE.json',inputs)
        memory_mb=min(a.memory_gb*1024-2048,4096)
        if shutil.disk_usage(work).free<8*1024**3:raise RuntimeError('At least 8 GiB free working space is required')
        phase='select_and_bridge'
        with heartbeat('Freezing calendar-complete rows and comparing the historical cohort'):
            prepared,pdone=prepare.build(inputs,root,code,a.workers,memory_mb,auth)
        for p in prepared.iterdir():
            if p.is_file() and p.name in PUBLIC_NAMES:shutil.copy2(p,public/p.name)
        source=prepared/'primary_PRIVATE.parquet'
        model_inputs=[contracts.snap(source),contracts.snap(prepared/'_DONE.json')]
        historical_input=[r for r in inputs['snapshots'] if r['path']==str(Path(inputs['historical_path']).resolve())]
        specs=design.specifications()
        for i,spec in enumerate(specs,1):
            phase=spec['name'];hist=spec['sample']=='historical'
            path=Path(inputs['historical_path']) if hist else source
            log(f'Model {i}/{len(specs)}: '+spec['name'])
            with heartbeat('Estimating '+spec['name']):
                folder,done=fit_one(path,spec,root,code,historical_input if hist else model_inputs,
                    a.workers,memory_mb,auth)
            result=load(folder/'result.json');results.append((spec,result));del done;gc.collect()
            if hist:
                check=model.check_historical(result);write_json(public/'HISTORICAL_REPRODUCTION.json',check)
                historical_pass=check['passed']
                if not historical_pass:raise RuntimeError('Historical reproduction failed; no new cohort coefficients were fitted')
            log(spec['name']+f' complete ({result["elapsed_seconds"]:.1f} s; cached time if reused)')
        phase='finish';unchanged(inputs['snapshots']);unchanged(model_inputs)
    except Exception as e:
        brief=str(e) if isinstance(e,RuntimeError) else (str(e).splitlines()[0] if isinstance(e,duckdb.Error) and str(e) else 'See private error details')
        errors.append(dict(stage=phase,exception=type(e).__name__,message=brief))
        write_json(work/'errors'/runid/'error_PRIVATE.json',dict(stage=phase,error=str(e),traceback=traceback.format_exc()))
        log('Stopped at '+phase+': '+brief)
    if results:estimates=assemble_outputs(results,public)
    status='PARTIAL_EXPANDED_ESTIMATION' if errors else 'EXPANDED_RECEIPT_IV_ESTIMATION_COMPLETE'
    summary=dict(status=status,elapsed_seconds=time.monotonic()-began,models_completed=len(results),
        primary='calendar90_primary',primary_rows=design.EXPECTED['primary'] if prepared else None,
        endpoint=design.ENDPOINT_UTC,historical_reproduction_passed=historical_pass,
        author_accounts_retained=True,author_exclusion_applied=False,mechanics_deployment_timestamp=None,
        primary_covers_multiple_policy_regimes=True,color_based_primary_censor=False,
        rating_replays=0,source_requests=0,Stockfish_calls=0,new_broader_incident_denominator=False,
        new_prospective_entry_estimate=False,new_ordinary_game_placebo=False,
        design_frozen_before_new_coefficients=True,causal_identification_certified=False,
        unsupported_estimate_rows=sum(not r.get('supported',False) for r in estimates),errors=errors)
    write_json(public/'SUMMARY.json',summary);write_json(public/'ERRORS.json',errors)
    write_json(public/'GATES.json',dict(primary_policy_windows='FULL_CALENDAR_COHORT',
        full_32_month_policy_spanning_IV='POOLED_ESTIMATE_NOT_STABLE_REGIME_CERTIFICATION',
        mechanics_deployment='UNPINNED_JANUARY_GUARD_REPORTED_SEPARATELY',
        color_reform='NOT_A_PRIMARY_CENSOR',expanded_prospective_entry_and_ordinary_placebo='NOT_PRODUCED',
        original_IV_assignment_and_exclusion='ASSUMPTIONS_NOT_CERTIFIED',returning_payoff_calibration='SEPARATE_STUDY_NOT_A_RECEIPT_IV_GATE',
        author_exclusion='DEFERRED_BY_USER'))
    (public/'READ_ME_FIRST.txt').write_text('Primary: calendar90_primary, estimator 2SLS. Read first stage, reduced form, AR set and exclusion sensitivity together.\n'
        'Primary windows end strictly before the data endpoint 2026-05-01 00:00 UTC. Color reform imposes no primary censor.\n'
        'Pre-color and January 30 guard fits are sensitivities; January 30 is not a proven deployment boundary.\n'
        'Month x assigned index color is added to the original controls; legacy_controls uses the same full rows without that addition.\n'
        'Calendar-regime fits use the index anchor and fixed horizon. Realized later-choice color/timing do not enter controls or selection.\n'
        'Both author accounts and complete-window nonreachers remain included. Original spacing is preserved.\n'
        'Five/ten are support floors for the same all-history score; both common-sample labels reference one fit.\n'
        'Lag 7/30 fits use identical rows and corresponding opponent-history controls; recipient-history windows stay fixed.\n'
        'Effect fields ending _pp use percentage points. Instrument effects and gamma use the fixed reference score SD.\n'
        'Read exposure-date counts and support for each fit. Cross-regime differences are not causal effects of the policy or independent replication tests.\n'
        'JSON is authoritative for interval unions, including unbounded/disconnected sets. No covariance repair.\n'
        'MDE80 is a descriptive normal approximation from fitted covariance, not a prospective power decision.\n'
        'Expanded entry/placebo estimates are not in this package. The old evidence is not newly precise.\n'
        'Only aggregate results are exported. Private game/account rows remain on XT_Pro.\n'
        'Restart the same command to verify and reuse completed stages. No API, replay, history scan or Stockfish.\n')
    zp=export_report(public,desktop)
    if not errors:
        write_json(work/'COMPLETED_ESTIMATION_PRIVATE.json',dict(status=status,
            code_signature=code,run_root=str(root),report_root=str(public),endpoint=design.ENDPOINT_UTC,
            primary_rows=design.EXPECTED['primary'],author_exclusion_applied=False,causal_identification_certified=False,
            result_zip_receipt=receipt(zp)))
    log(status)
    print('UPLOAD: '+str(zp),flush=True);print('UPLOAD: '+str(zp)+'.sha256',flush=True)
    lock.close();return 1 if errors else 0

if __name__=='__main__':raise SystemExit(main())
