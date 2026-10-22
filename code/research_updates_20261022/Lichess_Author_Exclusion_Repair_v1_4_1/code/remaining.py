"""Repair five remaining families; preserve verified v140 fits and audits."""
from remaining_common import *
from compare import compare_all,export_tables
import run as reporting
from repair import child
import argparse,fcntl,subprocess,traceback,uuid,concurrent.futures as cf

FIX=['first_repeat','state_persistence','tenure','patron_remaining','c6']
PARENT141=read(ROOT/'REPAIR_141_PARENT.json')

def remaining_parent(project):
    return project/'derived/replication/author_exclusion_remaining_v140_PRIVATE'/PARENT141['run_id']

NEW=['responsibility','first_repeat','state_persistence','tenure','patron_remaining','c6','temporal','arena']
# Sequential family processes; each family has a bounded internal worker budget.
RANGES={'responsibility':(5,25),'first_repeat':(5,25),'state_persistence':(3,12),'tenure':(10,40),'patron_remaining':(20,75),'c6':(10,40),'temporal':(5,30),'arena':(10,45)}

def authenticate(a,run):
    parent=parent_root(a.project);require(parent.is_dir(),'Successful v130 private cache is required')
    cfg=read(parent/'PRIVATE/CONFIG.json')
    require(cfg['code']==PARENT['code'],'Parent execution code differs from reviewed v1.3.0')
    require(sha(parent/'report/REPORT_HASHES.json')==PARENT['report_manifest_sha256'],'Parent report manifest changed')
    for r in read(ROOT/'evidence/returned_v130/REPORT_HASHES.json'):
        rel=Path(r['file']);require(not rel.is_absolute() and '..' not in rel.parts,'Unsafe parent manifest path')
        p=parent/'report'/rel;require(p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Reviewed parent report changed: '+str(rel))
    auths={v:read(parent/'PRIVATE/inputs'/(v+'_AUTH.json')) for v in ('included','excluded')}
    paths={r['path']:r for d in auths.values() for r in d['month_records']}
    def check(r):require(sha(r['path'])==r['expected_sha256'],'Parent Parquet changed');return r['path'],signature(r['path'])
    with cf.ThreadPoolExecutor(max_workers=min(4,a.workers)) as pool,heartbeat('Authenticate reusable Parquets'):stamps=dict(pool.map(check,paths.values()))
    for v,d in auths.items():
        require(d['author_policy']['accounts']==list(AUTHORS),'Author policy changed')
        for r in d['month_records']:r['verified_signature']=stamps[r['path']]
        d['verification_session']=os.environ['AUTHOR_EXCLUSION_SESSION'];write(run/'PRIVATE/inputs'/(v+'_AUTH.json'),d)
    old=read(parent/'PRIVATE/STAGES.json')
    for token,r in old.items():
        if r.get('status')!='COMPLETE':continue
        verify(r['receipt'])
        for item in r['aggregate_files']:verify(item)
        v,s=token.split('/');shutil.copytree(parent/'report/tables'/v/s,run/'report/tables'/v/s,dirs_exist_ok=True)
    for name in ('main_counts.csv','main_counts.parquet','removals_by_month.csv','removals_by_month.parquet','POLICY.json'):
        shutil.copy2(parent/'report'/name,run/'report'/name)
    shutil.copytree(parent/'report/current_audits',run/'report/current_audits',dirs_exist_ok=True)
    return old

def adopt_remaining(a,run,statuses):
    old=remaining_parent(a.project)
    cfg=read(old/'PRIVATE/CONFIG.json')
    require(digest(cfg)[:16]==PARENT141['run_id'] and cfg['code']==PARENT141['code'],'v140 configuration differs from reviewed source')
    require(sha(old/'report/REPORT_HASHES.json')==PARENT141['report_sha256'],'v140 report has changed since return')
    for r in read(ROOT/'evidence/returned_v140/REPORT_HASHES.json'):
        rel=Path(r['file']);require(not rel.is_absolute() and '..' not in rel.parts,'Unsafe v140 report path')
        f=old/'report'/rel
        require(f.is_file() and f.stat().st_size==r['bytes'] and sha(f)==r['sha256'],'Returned v140 report differs: '+str(rel))
    prior=read(old/'PRIVATE/STAGES.json');adopted=[]
    for family in PARENT141['completed_families']:
        for variant in ('included','excluded'):
            token=variant+'/'+family;r=prior[token]
            require(r['status']=='COMPLETE','Required completed v140 stage missing: '+token)
            receipt=verify(r['receipt']);d=read(receipt)
            auth=read(run/'PRIVATE/inputs'/(variant+'_AUTH.json'))
            require(d['sample_fingerprint']==auth['fingerprint'] and d['stage']==family and d['variant']==variant,'v140 sample/receipt mismatch')
            require(d==read(old/'report/stage_summaries'/variant/(family+'.json')),'v140 receipt differs from returned summary')
            for item in r['aggregate_files']:verify(item)
            shutil.copytree(old/'report/tables'/variant/family,run/'report/tables'/variant/family,dirs_exist_ok=True)
            dest=run/'report/stage_summaries'/variant/(family+'.json');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(receipt,dest)
            statuses[token]=r;adopted.append(token);log('Verified v140 fit retained: '+token)
    for folder in ('current_audits','audit_tables'):
        shutil.copytree(old/'report'/folder,run/'report'/folder,dirs_exist_ok=True)
    write(run/'report/REUSE_V140.json',dict(parent=old.name,completed_stages=adopted,current_audits_retained=True,temporal_draws_rerun=0,report_entries_verified=len(read(ROOT/'evidence/returned_v140/REPORT_HASHES.json'))))

def eta(run,jobs,statuses,completed=0,total=None):
    pending=[(i,v,s) for i,(v,s) in enumerate(jobs) if statuses.get(v+'/'+s,{}).get('status')!='COMPLETE']
    low=high=0;stage_ranges=[]
    for i,v,s in pending:
        lo,hi=RANGES[s]
        before=statuses.get('included/'+s,{})
        if v=='excluded' and before.get('seconds'):
            minutes=before['seconds']/60;lo=max(.5,.6*minutes);hi=max(5,1.8*minutes)
        low+=lo;high+=hi
        stage_ranges.append((i,lo,hi))
    result=dict(planning_estimate=True,remaining_minutes=[round(low+5),round(high+15)],audit_allowance_minutes=[5,15],next_stage=(pending[0][1]+'/'+pending[0][2]) if pending else 'existing-result audits',next_stage_minutes=list(RANGES[pending[0][2]]) if pending else [15,60],conditional_addition='None: completed temporal results and audits are retained.',pending=[v+'/'+s for _,v,s in pending])
    total=total or len(jobs);progress=completed*90/max(1,total)
    checkpoint=next((x for x in (25,50,75,100) if x>progress),100)
    until=max(0,math.ceil(checkpoint*total/90)-completed)
    selected=[(lo,hi) for i,lo,hi in stage_ranges if i<until]
    result['next_checkpoint_percent']=checkpoint
    result['next_checkpoint_minutes']=[round(sum(x[0] for x in selected)+(5 if checkpoint==100 else 0)),round(sum(x[1] for x in selected)+(15 if checkpoint==100 else 0))]
    write(run/'report/RUNTIME_ESTIMATE.json',result)
    log(f'Estimated remaining {(low+5)/60:.1f}–{(high+15)/60:.1f} hours; completed fits and temporal randomizations are retained.')
    log(f"Next report checkpoint {checkpoint}%: approximately {result['next_checkpoint_minutes'][0]}–{result['next_checkpoint_minutes'][1]} minutes.")

def coverage(run,statuses,audits,summary=None):
    rows=[]
    for family in NEW:
        rows.append(dict(family=family,included=statuses.get('included/'+family,{}).get('status','NOT_RUN'),excluded=statuses.get('excluded/'+family,{}).get('status','NOT_RUN')))
    rows.extend(dict(family=k,included='NO_NEW_INCLUDED_COUNTERFACTUAL',excluded=v.get('status','NOT_RUN')) for k,v in audits.items())
    table(run/'report/remaining_coverage',rows)
    complete=all(statuses.get(v+'/'+s,{}).get('status')=='COMPLETE' for s in NEW for v in ('included','excluded'))
    # All retained table/figure labels are listed, including tables with multiple producers.
    import re
    mapping=read(ROOT/'MANUSCRIPT_MAP.json');items=[]
    documents=[]
    for document in ('main','supplement'):
        text=(ROOT/'manuscript'/(document+'.tex')).read_text()
        documents.append((document,re.findall(r'\\label\{((?:tab|fig):[^}]+)\}',text)))
    documents.append(('prose',[k for k in mapping if k.startswith('prose:')]))
    for document,labels in documents:
        for label in labels:
            families=mapping.get(label,[])
            states=[]
            for f in families:
                if f.startswith('audit:'):states.append(audits.get(f[6:],{}).get('status','NOT_VERIFIED'))
                elif f=='illustration':states.append('NOT_AN_ANALYSIS')
                else:states.append(statuses.get('excluded/'+f,{}).get('status','NOT_RUN'))
            items.append(dict(document=document,label=label,families='|'.join(families),status=';'.join(states) if states else 'UNMAPPED_REQUIRES_REVIEW'))
    table(run/'report/manuscript_coverage',items)
    accepted={'COMPLETE','NOT_AN_ANALYSIS','EXISTING_AUTHOR_EXCLUDED_RESULT_VERIFIED','EXISTING_FRAMEWORK_PERSISTENCE_VERIFIED','ALL_CURRENT_RECEIPT_IV_MODELS_AUTHOR_CLEAN_VERIFIED','ENTRY_AND_ORDINARY_AUTHOR_CLEAN_RESULTS_VERIFIED'}
    covered=all(all(s in accepted for s in r['status'].split(';')) for r in items)
    write(run/'report/CLAIM_STATUS.json',dict(all_analyses_excluded=complete and covered,no_substantive_difference_established=False,all_requested_paired_stages_finished=complete,all_retained_manuscript_items_have_verified_excluded_outputs=covered,review_required=True,reason='Coverage refers to the bundled current manuscript and supplement. Review the paired estimates before claiming no substantive change; already-excluded results have no new included counterfactual.'))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop');p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    p.add_argument('--shards',type=int,default=256);p.add_argument('--estimate-only',action='store_true');p.add_argument('--stages',nargs='+',choices=NEW,default=FIX)
    a=p.parse_args()
    if a.estimate_only:
        print('Planning estimate: 2–7 hours on the 10-worker/11-GiB Mac configuration, provisional. All completed v140 fits and current audits are retained. Temporal inputs were exactly unchanged; no randomizations are scheduled. Authentication and reporting included. No engine searches, API acquisition, or all-game chronology rescan. Successful stages resume by verified receipts.');return 0
    a.project=a.project.expanduser().resolve();reporting.verify_package();versions=reporting.preflight(a)
    cfg=dict(version='1.4.1',parent=PARENT,repair_parent=PARENT141,code={p.name:sha(p) for p in sorted((ROOT/'code').glob('*.py'))},package=sha(ROOT/'PACKAGE_MANIFEST.sha256'),versions=versions)
    run=a.project/'derived/replication/author_exclusion_repair_v141_PRIVATE'/digest(cfg)[:16]
    for sub in ('PRIVATE','report'):(run/sub).mkdir(parents=True,exist_ok=True)
    parent=parent_root(a.project);require(parent.is_dir(),'Completed v1.3.0 parent cache missing')
    locks=[]
    for base in (parent,remaining_parent(a.project),run):
        lock=(base/'RUNNING.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
    os.environ['AUTHOR_EXCLUSION_SESSION']=uuid.uuid4().hex;write(run/'PRIVATE/CONFIG.json',cfg)
    state=run/'PRIVATE/STAGES.json';statuses=read(state) if state.exists() else {};audits={};start=time.monotonic();failures=[]
    try:
        statuses.update(authenticate(a,run));adopt_remaining(a,run,statuses);write(state,statuses)
        audits={p.stem:read(p) for p in (run/'report/current_audits').glob('*.json')}
        jobs=[(v,s) for s in a.stages for v in ('included','excluded')]
        eta(run,jobs,statuses);coverage(run,statuses,audits);reporting.package(run,a.result_dir,0)
        milestones=set()
        for i,(v,s) in enumerate(jobs):
            token=v+'/'+s;t=time.monotonic();old=statuses.get(token,{})
            if old.get('status')=='COMPLETE':
                verify(old['receipt'])
                for f in old['aggregate_files']:verify(f)
                log('Verified completed checkpoint: '+token)
            else:
                try:
                    cmd=[sys.executable,str(ROOT/'code/remaining_worker.py'),'--project',str(a.project),'--run',str(run),'--stage',s,'--variant',v,'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
                    log('Starting '+token+f'; expected {RANGES[s][0]}–{RANGES[s][1]} minutes, except conditional temporal rerandomization.')
                    require(child(cmd,run/'PRIVATE/logs'/(v+'_'+s+'.log'),token)==0,'Stage failed: '+token)
                    files=export_tables(run,v,s);require(files,'No aggregate tables produced: '+token)
                    receipt=run/'PRIVATE/stage_receipts'/v/(s+'.json')
                    write(run/'report/stage_summaries'/v/(s+'.json'),read(receipt))
                    for name in ('REPRODUCTION.json','RECONSTRUCTION_METHOD.json','interaction_covariance.json','RESOURCE_PLAN.json','models.json'):
                        diagnostic=run/'PRIVATE/results'/v/s/'report'/name
                        if diagnostic.is_file():
                            target=run/'report/stage_summaries'/v/s/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(diagnostic,target)
                    statuses[token]=dict(status='COMPLETE',seconds=time.monotonic()-t,receipt=record(receipt),aggregate_files=[record(f) for f in files])
                except Exception as e:
                    statuses[token]=dict(status='FAILED',error=str(e));failures.append(token)
                    # Diagnostics contain no raw rows. Preserve the failing worker's
                    # traceback so repairs do not require a second inventory run.
                    logp=run/'PRIVATE/logs'/(v+'_'+s+'.log')
                    write(run/'report/failures'/(v+'_'+s+'.json'),dict(stage=token,error=str(e),log_tail=logp.read_text(errors='replace')[-12000:] if logp.exists() else ''))
                    for name in ('REPRODUCTION.json','RECONSTRUCTION_METHOD.json','models.json','regressions.csv','normalized_contrasts.csv','equal_account_diagnostic.csv'):
                        diag=run/'PRIVATE/results'/v/s/'report'/name
                        if diag.is_file():shutil.copy2(diag,run/'report/failures'/(v+'_'+s+'_'+name))
                write(state,statuses)
            coverage(run,statuses,audits);eta(run,jobs[i+1:],statuses,completed=i+1,total=len(jobs))
            percent=int((i+1)*90/len(jobs))
            for checkpoint in (25,50,75):
                if percent>=checkpoint and checkpoint not in milestones:reporting.package(run,a.result_dir,checkpoint);milestones.add(checkpoint)
        # All current audits were authenticated and copied from the completed v140 report.
        paired=sorted({t.split('/')[1] for t in statuses if statuses.get('included/'+t.split('/')[1],{}).get('status')=='COMPLETE' and statuses.get('excluded/'+t.split('/')[1],{}).get('status')=='COMPLETE'})
        summary=compare_all(run,paired);coverage(run,statuses,audits,summary)
        write(run/'report/EXECUTION_STATUS.json',dict(status='COMPLETED_REVIEW_REQUIRED' if not failures else 'PARTIAL_REVIEW_FAILURES',failed_stages=failures,paired_families=paired,elapsed_minutes=(time.monotonic()-start)/60,comparison=summary))
        write(run/'report/RUNTIME_ESTIMATE.json',dict(finished=True,elapsed_minutes=(time.monotonic()-start)/60,remaining_minutes=[0,0]))
        reporting.package(run,a.result_dir,100)
        log('Return the _100.zip and .sha256 for review. Do not revise numerical results or assert invariance before review.')
        return 2 if failures else 0
    except BaseException as e:
        write(run/'report/EXECUTION_STATUS.json',dict(status='BLOCKED',error=str(e),traceback=traceback.format_exc()));reporting.package(run,a.result_dir,0);raise
    finally:
        for lock in locks:lock.close()

if __name__=='__main__':sys.exit(main())
