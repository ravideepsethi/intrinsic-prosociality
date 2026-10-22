#!/usr/bin/env python3
"""Offline A–F runner. Each model family runs in a fresh process."""
from fw_common import *
import argparse,fcntl,subprocess,traceback,zipfile,shutil,platform

STAGES=['A','F_raw','A3','B','C','E_matched','E_iv','D','F_adjusted','B_profiles','B_logit']
def verify_package():
    manifest=ROOT/'PACKAGE_MANIFEST.json';require(manifest.is_file(),'Package manifest missing')
    for x in load(manifest)['files']:
        p=ROOT/x['path'];require(p.is_file() and sha(p)==x['sha256'],'Package file changed: '+x['path'])
    return sha(manifest)

def state_readout(run):
    lines=['# Persistence across years','',
      'Fixed years: November 2023–October 2024 and November 2024–October 2025. Common sample, at least four opportunities per state/year, all stages. Returning observed accounts only.','']
    for mode in ['raw','adjusted']:
        p=run/'F/report'/('tabF2_persistence_matrix_'+mode+'.json')
        if not p.exists():continue
        rows=[r for r in load(p) if r.get('sample')=='common' and r.get('minimum')==4 and not r.get('late')]
        for state in ['N','L']:
            subset=[r for r in rows if r.get('comparison')=='C/'+state]
            targets=['pearson:C_to_C','pearson:C_to_'+state,'pearson:'+state+'_to_C','pearson:'+state+'_to_'+state,'pearson:within_state_difference']
            selected={r['statistic']:r for r in subset if r.get('statistic') in targets}
            lines += [f'## {mode.capitalize()}: C versus {state}','', '| Correlation or difference | Estimate | 95% CI | Accounts |','|---|---:|---:|---:|']
            for name in targets:
                r=selected.get(name,{})
                if r.get('status')=='ESTIMATED':lines.append(f"| {name.replace('pearson:','').replace('N',state)} | {r['estimate']:.4f} | [{r['ci_low']:.4f}, {r['ci_high']:.4f}] | {r['accounts']:,} |")
                else:lines.append('| '+name+' | Not estimable | — | — |')
            c=selected.get(targets[0],{});n=selected.get(targets[3],{})
            positive=lambda x:x.get('status')=='ESTIMATED' and x.get('ci_low',-1)>0
            if positive(c) and positive(n):message='Both states show positive year-to-year persistence.'
            elif positive(c):message='Competitive persistence is supported. Positive persistence in the comparison state is unresolved.'
            elif positive(n):message='Positive persistence in the comparison state is supported. Competitive persistence is unresolved.'
            else:message='These intervals do not establish positive persistence in both states; this is not evidence that persistence is absent.'
            lines += ['',message,'']
    lines += ['N includes every noncompetitive position (v < −100); L includes clearly lost positions (v ≤ −300). Adjusted intervals hold the cross-fitted nuisance models fixed. Correlations do not identify psychological motives.','']
    (run/'report/PERSISTENCE_READOUT.md').write_text('\n'.join(lines))

def export(run,a,tag,status):
    public=run/'report';public.mkdir(parents=True,exist_ok=True)
    save(public/'STATUS.json',status);state_readout(run)
    manifest=[];items=[]
    # Only explicit aggregate report directories are eligible for result export.
    folders=[public]+[run/n/'report' for n in ('A','A3','B','C','D','E','F')]+[run/'C/exposure/report',run/'F/adjustment/report']
    for folder in folders:
        if folder.is_dir():
            for p in sorted(folder.glob('*')):
                if p.is_file() and p.suffix.lower() in ('.json','.csv','.parquet','.pdf','.md','.txt'):
                    arc='results/'+str(p.relative_to(run));items.append((p,arc));manifest.append(dict(path=arc,bytes=p.stat().st_size,sha256=sha(p)))
    a.desktop.mkdir(parents=True,exist_ok=True);dest=a.desktop/f'FRAMEWORK_TESTS_{tag}_{run.name}.zip';tmp=dest.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p,arc in items:z.write(p,arc)
        for name in ['README.md','HANDOFF_SPEC.md','IMPLEMENTATION_NOTES.md','REPAIR_NOTES.md','VALIDATION.md','PACKAGE_MANIFEST.json']:z.write(ROOT/name,name)
        z.writestr('RESULT_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    os.replace(tmp,dest);dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_RESULT '+str(dest));return dest

def run_stage(a,run,key,stage):
    no_network();paths=load(run/'PATHS_PRIVATE.json');panels=paths['panels'];parts=paths['parts'];accounts=Path(paths['accounts'])
    reused=(run/'REUSE_PRIVATE.json').exists()
    if reused and stage in ('B','B_profiles','B_logit','D'):
        import fw_repair
        parts=fw_repair.complete_parts(a,run,key)
    if stage=='A':
        import fw_a;result=fw_a.run(a,run,key)
    elif stage=='A3':
        import fw_a3;result=fw_a3.run(a,run,key)
    elif stage=='F_raw':
        import fw_f;result=fw_f.run(a,run,accounts,None,key)
    elif stage=='F_adjusted':
        import fw_f,fw_adjust
        if reused:
            import fw_repair
            adjusted=fw_repair.adjusted(a,run,key)
        else:adjusted=fw_adjust.adjust(parts,run/'F/adjustment',digest([key,'nuisance']),a)
        result=fw_f.run(a,run,accounts,adjusted,key)
    elif stage=='B':
        import fw_b;result=fw_b.run(a,run,parts,accounts,key)
    elif stage=='B_profiles':
        import fw_b_profiles;result=fw_b_profiles.run(a,run,parts,key)
    elif stage=='B_logit':
        import fw_b_extra;result=fw_b_extra.run_logit(a,run,parts,key)
    elif stage=='C':
        import fw_c;result=fw_c.run(a,run,panels,key)
    elif stage=='D':
        import fw_d;result=fw_d.run(a,run,parts,key)
    elif stage in ('E_matched','E_iv'):
        import fw_e
        if reused and stage=='E_iv':
            import fw_repair
            result=fw_e.run_iv(a,run,fw_repair.history(a,run,key),key)
        else:result=fw_e.run(a,run,panels,key,'matched' if stage=='E_matched' else 'iv')
    else:raise RuntimeError('Unknown stage')
    save(run/'stages'/(stage+'.json'),result)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10);ap.add_argument('--memory-gb',type=float,default=11.)
    ap.add_argument('--bootstrap',type=int,default=999,help='Production requires exactly 999 as frozen in F')
    ap.add_argument('--reuse-framework-root',type=Path,help='Certified v1.0.0 run; retain unaffected results and repair B/E/F')
    ap.add_argument('--stage',choices=['all','F']+STAGES,default='all')
    ap.add_argument('--preflight-only',action='store_true');ap.add_argument('--status',action='store_true')
    ap.add_argument('--child-stage',choices=STAGES,help=argparse.SUPPRESS);ap.add_argument('--run-root',type=Path,help=argparse.SUPPRESS)
    ap.add_argument('--key',help=argparse.SUPPRESS);a=ap.parse_args()
    require(1<=a.workers<=10 and 4<=a.memory_gb<=11,'Use 1–10 workers and 4–11 GiB RAM');require(a.bootstrap==999,'Production F uses the frozen 999 bootstrap replicates')
    if a.child_stage:
        run_stage(a,a.run_root,a.key,a.child_stage);return 0
    package=verify_package();require(a.project_root.is_dir(),'Project volume is not mounted')
    conf=dict(version=VERSION,package_sha256=package,project=str(a.project_root.resolve()),bootstrap=a.bootstrap,
        handoff_sha256=sha(ROOT/'HANDOFF_SPEC.md'),amendment_sha256=sha(ROOT/'IMPLEMENTATION_NOTES.md'))
    if a.reuse_framework_root:conf['reuse_framework_root']=str(a.reuse_framework_root.resolve())
    key=digest(conf);run=a.project_root/'derived/replication/framework_tests_v101_PRIVATE'/key[:12]
    if a.status:
        print(json.dumps(load(run/'report/STATUS.json') if (run/'report/STATUS.json').exists() else dict(status='NOT_STARTED',run=str(run)),indent=2));return 0
    run.mkdir(parents=True,exist_ok=True);lock=(run/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This framework run is already active')
    (run/'report').mkdir(exist_ok=True);save(run/'CONFIGURATION.json',conf)
    if not (run/'DESIGN_FREEZE.json').exists():save(run/'DESIGN_FREEZE.json',dict(created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),configuration=conf,earlier_A_to_E_execution='Not inferred; historical runs remain separately dated.'))
    import scipy,matplotlib
    save(run/'report/ENVIRONMENT.json',dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,pyarrow=pa.__version__,duckdb=duckdb.__version__,scipy=scipy.__version__,matplotlib=matplotlib.__version__,workers=a.workers,memory_budget_gb=a.memory_gb))
    no_network();status=dict(status='RUNNING',stages={},milestone_percent=0,run_id=run.name,empirical_results='Produced locally only; no estimate is prefilled from the manuscript.')
    try:
        from fw_inputs import prepare,aggregate_accounts,partitions
        log('Authenticate fixed 24-month sources; no API, PGN downloads or Stockfish.')
        if not (run/'PATHS_PRIVATE.json').exists():require(shutil.disk_usage(run).free>=60*1024**3,'Need at least 60 GiB free for projections and model caches')
        if a.reuse_framework_root:
            import fw_repair
            require(a.reuse_framework_root.resolve()!=run.resolve(),'Cannot reuse the new run itself')
            parent_lock=(a.reuse_framework_root/'RUN.lock').open('r')
            try:fcntl.flock(parent_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('The parent framework run is still active')
            status['stages']=fw_repair.prepare(a,run,key)
            stages=fw_repair.REPAIR_STAGES if a.stage=='all' else ['F_adjusted'] if a.stage=='F' else [a.stage]
            require(all(s in fw_repair.REPAIR_STAGES for s in stages),'Reuse mode repairs F, E_iv and B/D; other stages are retained')
        else:
            panels=prepare(a,run,key)
            accounts=aggregate_accounts(panels,run/'accounts',digest([key,'accounts']),a.memory_gb)
            parts=partitions(panels,run/'partitions',digest([key,'parts']),a.memory_gb)
            save(run/'PATHS_PRIVATE.json',dict(panels=panels,accounts=str(accounts),parts=[str(p) for p in parts]))
            table(run/'report','source_counts',[{k:v for k,v in r.items() if k not in ('path','source_sha256')} for r in load(run/'INPUTS_PRIVATE.json')])
            stages=STAGES if a.stage=='all' else ['F_raw','F_adjusted'] if a.stage=='F' else [a.stage]
        if a.preflight_only:
            status['status']='PREFLIGHT_PASSED';export(run,a,'PREFLIGHT',status);return 0
        start=time.monotonic();milestones=set()
        log('Whole-run duration is unbenchmarked on this Mac. Worker stages print measured ETAs; 25/50/75/100% are stage milestones, not elapsed-time forecasts.')
        for i,stage in enumerate(stages):
            log('START '+stage);t=time.monotonic()
            cmd=[sys.executable,'-u',str(Path(__file__).resolve()),'--child-stage',stage,'--run-root',str(run),'--key',key,
                '--project-root',str(a.project_root),'--desktop',str(a.desktop),'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
            with heartbeat(stage):proc=subprocess.run(cmd)
            if proc.returncode==0:
                result=load(run/'stages'/(stage+'.json'));result['execution']='FINISHED'
            else:result=dict(status='FAILED_OR_BLOCKED',execution='FAILED',returncode=proc.returncode,action='Return the terminal log and latest result ZIP. Successful checkpoints remain reusable.')
            result['elapsed_seconds']=time.monotonic()-t;status['stages'][stage]=result
            percent=int(100*(i+1)/len(stages));status['milestone_percent']=percent;status['elapsed_seconds']=time.monotonic()-start
            save(run/'report/STATUS.json',status)
            for mark in [25,50,75]:
                if percent>=mark and mark not in milestones:
                    export(run,a,f'CHECKPOINT_{mark:03d}',status);milestones.add(mark)
        failed=any(r.get('execution')=='FAILED' for r in status['stages'].values())
        if a.stage=='all' and status['stages'].get('B',{}).get('execution')=='FINISHED':
            b=status['stages']['B'];b['supplements']={n:status['stages'][n] for n in ['B_profiles','B_logit']}
            b['remaining']=[n for n in ['B_profiles','B_logit'] if status['stages'][n].get('execution')!='FINISHED']
            if not (run/'A/flagged_chooser_names_PRIVATE.json').exists():b['remaining'].append('Flag exclusion source unavailable')
            b['status']='ESTIMATED' if not b['remaining'] else 'PARTIAL'
            save(run/'B/report/STATUS.json',b)
        status['status']='FINISHED_WITH_FAILED_STAGES' if failed else 'FINISHED_AVAILABLE_TESTS'
        status['scope']=a.stage;status['D_casual_history']='Unavailable from standard rated PGN dumps; explicitly reported if D is triggered.'
        export(run,a,'CHECKPOINT_100',status);export(run,a,'FINAL',status);return 2 if failed else 0
    except BaseException as e:
        status.update(status='STOPPED',error_type=type(e).__name__,error=str(e));(run/'report/ERROR.txt').write_text(traceback.format_exc())
        export(run,a,'PARTIAL',status);raise
    finally:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=='__main__':sys.exit(main())
