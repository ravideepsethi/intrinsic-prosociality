"""Offline, fixed-cohort first pass. No upstream orchestration is invoked."""
from iv_common import *
from iv_history import prepare_queries,score_job,combine
from iv_material import attach
import argparse, concurrent.futures as cf, multiprocessing as mp, time, json, zipfile, fcntl
from r7_reproduce import check_row

def reproduction(folder):
    got=r.io.load(Path(folder)/'result.json');checked=[]
    fields=['coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp','AR95_intervals_pp','first_stage_F']
    for table in ('B_estimates','B_joint_balance','B_balance'):
        target=[v for v in r.io.load(ROOT/'evidence'/f'{table}.json') if v['sample']=='S0' and v['control_level']=='X0' and v['instrument']=='pooled']
        for want in target:
            row=next(v for v in got[table] if all(v.get(k)==want.get(k) for k in ('outcome','estimator','trait','test_set')))
            check_row(row,want,table,fields+['coefficient','standard_error','wald_chi2','p_value_asymptotic'])
            checked.append(dict(table=table,outcome=want.get('outcome'),trait=want.get('trait'),passed=True))
    u.require(len(checked)==12,'Unexpected reproduction target count')
    return checked

def run_scores(jobs,workers,memory):
    # Event-time history arrays have a larger footprint than monthly cached counts.
    # Reserve 1.5 GiB for the parent; conservative 480 bytes per source row + 0.5 GiB per worker.
    weights=[max(1.,.5+sum(v['rows'] for v in j['parts'])*480/1024**3) for j in jobs]
    worst=max(weights);slots=min(workers,max(1,int((memory-1.5)//worst)))
    u.require(worst<=memory-1.5,'History shard exceeds the requested memory budget')
    u.log(f'Donor scores: up to {slots} workers under {memory:g} GiB budget (requested maximum {workers})')
    start=time.monotonic();done=0;results=[]
    options={'max_tasks_per_child':1} if sys.version_info>=(3,11) else {}
    with cf.ProcessPoolExecutor(max_workers=slots,mp_context=mp.get_context('spawn'),**options) as pool:
        pending={pool.submit(score_job,j) for j in jobs}
        while pending:
            finished,pending=cf.wait(pending,timeout=30,return_when=cf.FIRST_COMPLETED)
            for future in finished:results.append(future.result());done+=1
            eta=(time.monotonic()-start)/done*(len(jobs)-done) if done else None
            u.log(f'Donor score shards {done}/{len(jobs)}; estimated remaining '+(f'{eta/60:.1f} minutes' if eta is not None else 'pending first completed shard'))
    return sorted(results,key=lambda v:v['shard'])

def report(root,desktop,conf,status,progress,extra):
    folder=root/'report';folder.mkdir(exist_ok=True)
    tables={k:[] for k in ('B_estimates','B_balance','B_joint_balance','B_indicator')}
    for p in sorted((root/'fits').glob('*/result.json')):
        if not (p.parent/'_DONE.json').exists():continue
        for k in tables:tables[k]+=r.io.load(p).get(k,[])
    for k,rows in tables.items():r.write_rows(folder,k,rows)
    comparisons=[]
    for screen in ('all','observed','neutral'):
        for level in ('X0','X0_ENV_indicator'):
            pair=[]
            for variant in ('old_monthly','lag24h'):
                rows=[v for v in tables['B_estimates'] if v['history_cutoff']==variant and v['exposure_screen']==screen and v['control_level']==level]
                if rows:pair.append((variant,rows))
            if len(pair)==2:
                u.require(pair[0][1][0]['n']==pair[1][1][0]['n'] and
                    pair[0][1][0]['row_set_sha256']==pair[1][1][0]['row_set_sha256'],
                    'Old/new comparison changed the row set')
            for variant,rows in pair:
                row=dict(history_cutoff=variant,exposure_screen=screen,control_level=level,
                         n=rows[0]['n'],row_set_sha256=rows[0]['row_set_sha256'],same_row_pair_complete=len(pair)==2)
                for v in rows:
                    if v.get('estimator')=='first_stage':row.update(first_stage_pp=v.get('coefficient_pp'),first_stage_SE_pp=v.get('standard_error_pp'))
                    if v.get('estimator')=='reduced_form':row.update({v['outcome']+'_RF_pp':v.get('coefficient_pp'),v['outcome']+'_RF_SE_pp':v.get('standard_error_pp')})
                    if v.get('estimator')=='2SLS':row.update(IV_pp=v.get('iv_coefficient_pp'),IV_SE_pp=v.get('iv_standard_error_pp'),AR95_intervals_pp=v.get('AR95_intervals_pp'),first_stage_F=v.get('first_stage_F'))
                joint=next((v for v in tables['B_joint_balance'] if v['history_cutoff']==variant and v['exposure_screen']==screen and v['control_level']==level),{})
                row['balance_joint_p']=joint.get('p_value_asymptotic');comparisons.append(row)
    r.write_rows(folder,'comparison',comparisons)
    summary=dict(version=VERSION,configuration_sha256=conf,status=status,progress_percent=progress,
        completed_models=len(list((root/'fits').glob('*/_DONE.json'))),author_clean_frozen_rows=2682329,
        causal_identification_certified=False,production_results_available=any(tables.values()),**extra)
    r.io.js(folder/'summary.json',summary)
    (folder/'READ_RESULTS.txt').write_text(
        'IV cutoff / material robustness — fixed-cohort first pass\n'
        'Read summary.json first: COMPLETE_WITH_MATERIAL_UNAVAILABLE is not a completed material test.\n'
        'old_monthly = the archived exposure-month start minus 7 days.\n'
        'lag24h = all recorded eligible donor decisions with cached api_last_move_at_ms strictly below exposure archive_start_ms minus 24 hours.\n'
        'This is NOT a trailing 24-hour window. Ordinary games are not refusals.\n'
        'All earlier current-pair decisions and both author accounts are excluded. At least five decisions required.\n'
        'The old monthly cross-fitted state probabilities and X0/ENV controls remain fixed. Only the instrument history cutoff changes.\n'
        'No exposure reselection, spacing change, expanded cohort, entry-frame rebuild, new API request, or engine work.\n'
        'Outcome is the archived 90-day later-choice outcome; complete-window nonreachers remain zero.\n'
        'Material uses the final FEN, conventional 1/3/3/5/9 values, and STRICT abs(balance)<4.\n'
        'observed = valid material available; neutral = observed AND abs(balance)<4; all retains the original cohort.\n'
        'Every old/new comparison within a screen and control level has identical rows. Missing material is never coded neutral.\n'
        'The source-panel competitive-position rule cp>=-100 is verified again. Donor history is not material-filtered.\n'
        'Numerical rageSit neutrality does not remove sanctions, ratings, prior matchmaking, or post-assignment sample selection.\n'
        'Shared-account-or-date CR0; fixed original reference score SD; generated instruments treated as fixed; nominal inference.\n'
        'This first pass does not establish exclusion or address newly supported exposure opportunities.\n'
        'Source timestamps retain the archived last-move/event convention, not a newly observed claim-button timestamp.\n')
    manifest=[dict(path=p.name,sha256=u.sha(p),bytes=p.stat().st_size) for p in sorted(folder.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    r.io.js(folder/'REPORT_MANIFEST.json',manifest)
    desktop.mkdir(parents=True,exist_ok=True)
    name=f'IV_CUTOFF_MATERIAL_REPORT_{conf[:12]}_{progress:03d}.zip'
    target=desktop/name;temp=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.iterdir()):
            if p.is_file():z.write(p,p.name)
    os.replace(temp,target)
    target.with_suffix('.zip.sha256').write_text(u.sha(target)+'  '+target.name+'\n')
    u.log(f'{progress}% checkpoint: {target}')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',default='/Volumes/XT_Pro/lichess_kindness')
    p.add_argument('--desktop',default=str(Path.home()/'Desktop/Lichess_Desktop'))
    p.add_argument('--r7-root');p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    args=p.parse_args();u.require(1<=args.workers<=10 and 6<=args.memory_gb<=11,'Use 1–10 workers and 6–11 GiB')
    verify_package();u.no_network()
    project=Path(args.project_root).expanduser().resolve();desktop=Path(args.desktop).expanduser().resolve()
    with u.heartbeat('Authenticate completed R7 and cached monthly reference'):
        paths,binding,parts,reference=bind(project,args.r7_root)
    conf=r.io.cfgsha(dict(version=VERSION,package=u.sha(ROOT/'PACKAGE_MANIFEST.sha256'),
        R7=u.R7_CONF,reference=u.sha(reference),source=[{k:v[k] for k in ('month','shard','sha256','rows')} for v in parts],
        definition='fixed_S0_cumulative_t_minus_24h_frozen_nuisance_frozen_controls_strict_abs_material_lt4'))
    root=project/'derived/replication/iv_cutoff_material_v100_PRIVATE'/conf[:12];root.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This exact IV configuration is already running')
    extra={};progress=0
    try:
        r.io.js(root/'config.json',dict(version=VERSION,conf=conf,workers=args.workers,memory_gb=args.memory_gb,
            baseline=u.R7_CONF,reference_sha256=u.sha(reference),definition='fixed cohort, frozen nuisance and controls'))
        source=paths['S0'];base=root/'fits/old_monthly__all__X0'
        with u.heartbeat('Reproduce completed author-clean S0 baseline'):
            with cf.ProcessPoolExecutor(max_workers=1,mp_context=mp.get_context('spawn')) as pool:
                pool.submit(fit_job,dict(input_path=source,output=str(base),conf=conf,variant='old_monthly')).result()
            extra['reproduction']=reproduction(base)
        queries=prepare_queries(source,root/'queries',conf)
        jobs=[dict(shard=s,parts=[v for v in parts if v['shard']==s],queries=str(queries/f'{s:02}.parquet'),
            authors=binding['author_ids'],reference=str(reference),output=str(root/'scores'/f'{s:02}'),conf=conf) for s in range(16)]
        extra['history_shards']=run_scores(jobs,args.workers,args.memory_gb)
        scores=combine([str(Path(j['output'])/'scores.parquet') for j in jobs],source,root/'scores_combined',conf,args.memory_gb-2)
        a=r.arrays(r.io.read(scores,['n_7d','n_24h','counterparts_7d','counterparts_24h','adjusted_7d','adjusted_24h']))
        extra['score_comparison']=dict(rows=len(a['n_7d']),correlation=float(np.corrcoef(a['adjusted_7d'],a['adjusted_24h'])[0,1]),
            old_median_decisions=float(np.median(a['n_7d'])),new_median_decisions=float(np.median(a['n_24h'])),
            old_median_counterparts=float(np.median(a['counterparts_7d'])),new_median_counterparts=float(np.median(a['counterparts_24h'])),
            mean_added_decisions=float(np.mean(a['n_24h']-a['n_7d'])))
        del a
        progress=25;report(root,desktop,conf,'HISTORIES_COMPLETE',progress,extra)
        with u.heartbeat('Authenticate final-position material and attach to fixed exposures'):
            material,extra['material']=attach(source,project,root/'material',conf,args.memory_gb)
        progress=50;report(root,desktop,conf,'INPUT_CHECKS_COMPLETE',progress,extra)
        screens=['all']+(['observed','neutral'] if material else [])
        planned=[]
        for screen in screens:
            for level in ('X0','X0_ENV_indicator'):
                for variant in ('old_monthly','lag24h'):
                    if (screen,level,variant)==('all','X0','old_monthly'):continue
                    name=f'{variant}__{screen}__{level}'
                    planned.append(dict(input_path=source,output=str(root/'fits'/name),conf=conf,
                        variant=variant,selection=screen,level=level,scores=str(scores),
                        material=str(material) if screen!='all' else None))
        # One numerical fit at a time; each fresh process releases allocation high-water marks.
        started=time.monotonic()
        for k,job in enumerate(planned,1):
            with cf.ProcessPoolExecutor(max_workers=1,mp_context=mp.get_context('spawn')) as pool:
                f=pool.submit(fit_job,job)
                while True:
                    try:f.result(timeout=30);break
                    except cf.TimeoutError:u.log(f'Fit {k}/{len(planned)} working: {job["variant"]} {job["selection"]} {job["level"]}')
            eta=(time.monotonic()-started)/k*(len(planned)-k)
            u.log(f'Models {k}/{len(planned)}; estimated fit time remaining {eta/60:.1f} minutes')
            if k>=(len(planned)+1)//2 and progress<75:
                progress=75;report(root,desktop,conf,'MODELS_IN_PROGRESS',progress,extra)
        progress=100
        status='COMPLETE' if material else 'COMPLETE_WITH_MATERIAL_UNAVAILABLE'
        report(root,desktop,conf,status,progress,extra)
    except Exception as exc:
        extra['error_type']=type(exc).__name__
        report(root,desktop,conf,'STOPPED_RETURN_LOG',progress,extra)
        raise
    finally:lock.close()

if __name__=='__main__':main()
