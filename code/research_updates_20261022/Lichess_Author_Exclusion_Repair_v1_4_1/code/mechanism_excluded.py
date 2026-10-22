"""Rebuild analytical mechanism cohorts and refit the frozen candidate models."""
from engine import *
import concurrent.futures as cf,multiprocessing as mp,subprocess

def imports():
    sys.path.insert(0,str(ROOT/'vendor/mechanism/code'))
    import common,inputs,analysis,model_utils,design,stats,reporting
    return common,inputs,analysis,model_utils,design,stats,reporting

def prepare_frozen(paths,state,work,report,key,threads,memory_mb,frozen):
    _,inputs,*_=imports()
    text=(ROOT/'vendor/mechanism/code/inputs.py').read_text()
    needle="'SELECT * FROM d ORDER BY hash(game_id),game_id LIMIT 100000'"
    require(text.count(needle)==1,'Standardization selector changed')
    text=text.replace(needle,"'SELECT * FROM d WHERE game_id IN (SELECT game_id FROM '+scan(FROZEN_STANDARDIZATION)+') ORDER BY hash(game_id),game_id'")
    namespace=dict(inputs.__dict__,FROZEN_STANDARDIZATION=frozen);exec(compile(text,'prepared_author_exclusion','exec'),namespace)
    return namespace['prepare_state'](paths,state,work,report,key,threads,memory_mb)

def robust_fit(path,meta,model,out,key,inference=True,unrestricted=False):
    common,_,analysis,mu,design,stats,_=imports();out=Path(out)
    if out.exists():
        r=read(out);require(r['key']==key,'Mechanism fit checkpoint changed');return analysis.restore(r['fit'])
    d=pd.read_parquet(path)
    if unrestricted:
        X,names,_=design.design(d,model);bounds=None
        f=stats.fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),bounds=bounds,inference=inference)
        f.update(model=model,names=names,curvature=.5,cue=None)
    else:f=mu.fit_one(d,model,inference=inference)
    attempts=[]
    if f['status']!='ESTIMATED' and 'beta' in f:
        # Same likelihood, constraints and projected-gradient gate as the
        # reviewed one-fit repair; only optimizer stopping is tightened.
        X,names,bounds=design.design(d,model,f.get('curvature',.5))
        if unrestricted:bounds=None
        start=f['beta'];best=f
        for ftol in (1e-12,1e-14,1e-15):
            r=stats.fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),bounds=bounds,start=start,inference=inference,maxiter=1000,ftol=ftol)
            r.update(model=model,names=names,curvature=f.get('curvature',.5),cue=None)
            attempts.append({k:r.get(k) for k in ('status','gradient_max','loglik','iterations')})
            best=r
            if r['status']=='ESTIMATED':break
            if 'beta' in r:start=r['beta']
        f=best
    f.update(full_n=int(meta['n']),full_accounts=int(meta['accounts']))
    # An unsuccessful curvature search must not be silently converted into a
    # successful selection at just one curvature. Curved failures remain open.
    if model=='curved' and attempts:f['status']='CURVATURE_SEARCH_REVIEW_REQUIRED'
    write(out,{'key':key,'fit':f,'retry_attempts':attempts});return f

def model_job(task):
    state,model,prepared,work,report,key=task
    common,_,a,mu,design,stats,_=imports();work=Path(work);report=Path(report);own=report/'models'/state/model
    receipt=work/'jobs'/(state+'_'+model+'.json')
    if receipt.exists():
        r=read(receipt);require(r['key']==key,'Mechanism job changed')
        for f in r['files']:verify(f)
        return r['status']
    rows={n:[] for n in ('coefficients','heldout_scores','heldout_calibration','conditional_score_diagnostics','common_index_profiles')};statuses=[]
    stand=pd.read_parquet(prepared['cohorts']['rd110']['standardization'])
    for cohort in ('original','rd110'):
        p=prepared['cohorts'][cohort]
        f=robust_fit(p['fit_full'],p['meta'],model,work/'fits'/f'{state}_{cohort}_{model}_full.json',key+cohort+'full')
        statuses.append(f['status']);rows['coefficients']+=a.coefficient_rows(f,state=state,training=cohort,stage='full')
        a.save_public_fit(f,own/(cohort+'_full_fit.json'),state=state,training=cohort)
        rows['common_index_profiles']+=a.index_profiles(stand,f,state=state,training=cohort)
        if f['status']=='ESTIMATED':rows['conditional_score_diagnostics']+=a.score_diagnostics(pd.read_parquet(p['fit_full']),f,state=state,training=cohort)
        for fold,item in enumerate(p['folds']):
            f=robust_fit(item['train_path'],item['train_meta'],model,work/'fits'/f'{state}_{cohort}_{model}_fold{fold}.json',key+cohort+str(fold),inference=False)
            statuses.append(f['status']);rows['coefficients']+=a.coefficient_rows(f,state=state,training=cohort,stage='fold'+str(fold))
            a.save_public_fit(f,own/(cohort+f'_fold{fold}_fit.json'),state=state,training=cohort)
            tests=[('original',f'original_train_original_test'),('rd110','original_train_rd110_test')] if cohort=='original' else [('rd110','rd110_train_rd110_test')]
            for test_cohort,label in tests:
                t=prepared['cohorts'][test_cohort]['folds'][fold]
                scores,cal=a.evaluate(pd.read_parquet(t['test_path']),f,t['test_meta'],state=state,fold=fold,comparison=label)
                rows['heldout_scores']+=scores;rows['heldout_calibration']+=cal
    for name,rs in rows.items():common.table(rs,own/(name+'.parquet'))
    status=dict(state=state,model=model,status='COMPLETE' if all(s=='ESTIMATED' for s in statuses) else 'FIT_FAILURE',fit_statuses=statuses)
    write(receipt,{'key':key,'status':status,'files':[record(p) for p in sorted(own.rglob('*')) if p.is_file()]});return status

def unrestricted_job(task):
    state,model,cohort,prepared,work,report,key=task
    common,_,a,_,_,_,_=imports();p=prepared['cohorts'][cohort];own=Path(report)/'unrestricted';prefix=state+'_'+cohort+'_'+model
    f=robust_fit(p['fit_full'],p['meta'],model,Path(work)/'unrestricted'/(prefix+'.json'),key+prefix,unrestricted=True)
    a.save_public_fit(f,own/(prefix+'_fit.json'),state=state,training=cohort,scope='Unrestricted-sign diagnostic')
    common.table(a.coefficient_rows(f,state=state,training=cohort,stage='full_unrestricted'),own/(prefix+'_coefficients.parquet'))
    common.table(a.index_profiles(pd.read_parquet(prepared['cohorts']['rd110']['standardization']),f,state=state,training=cohort),own/(prefix+'_index_profiles.parquet'))
    return dict(state=state,model=model,cohort=cohort,status=f['status'])

def run(args,out,parent):
    # Resolve the exact same global identity namespace used by the successful
    # prior audit in a separate interpreter, avoiding legacy module collisions.
    identity=out/'PRIVATE/AUTHOR_IDS.json';identity.parent.mkdir(parents=True,exist_ok=True)
    code="import sys;from pathlib import Path;from types import SimpleNamespace;from audit_current import author_ids;from engine import write;write(Path(sys.argv[2]),author_ids(SimpleNamespace(project=Path(sys.argv[1])),Path(sys.argv[3])))"
    env=dict(os.environ,PYTHONPATH=str(ROOT/'code'))
    subprocess.run([sys.executable,'-c',code,str(args.project),str(identity),str(out)],check=True,env=env)
    ids=read(identity);require(set(ids)==set(AUTHORS),'Mechanism author identity differs')
    common,inputs,a,mu,design,stats,reporting=imports()
    source=args.project/'derived/replication/mechanism_separation_v100_PRIVATE'
    reference=read(ROOT/'vendor/mechanism/authority/reference.json');paths,ledger=inputs.authenticate_source(source,out/'PRIVATE',reference)
    names=','.join(str(int(i)) for i in ids.values());filtered=[];removals=[]
    c=db(out/'PRIVATE/spill_filter',args.memory_gb-2,min(args.workers,4))
    try:
        for month,path in zip(MONTHS,paths):
            dest=out/'PRIVATE/analysis'/(month+'.parquet');done=dest.with_suffix('.receipt.json');key=digest([record(path)['sha256'],ids,sha(__file__)])
            if done.exists():
                r=read(done);require(r['key']==key,'Mechanism filter identity differs');verify(r['output'])
            else:
                hit='chooser IN ('+names+') OR opponent IN ('+names+')'
                n,bad,eligible=c.execute('SELECT count(*),count(*) FILTER(WHERE '+hit+'),count(*) FILTER(WHERE ('+hit+") AND regular IS TRUE AND state IN ('equal','losing')) FROM "+scan(path)).fetchone()
                require(c.execute('SELECT count(*) FROM '+scan(path)+' WHERE chooser IS NULL OR opponent IS NULL').fetchone()[0]==0,'Missing mechanism participant identity')
                kept=copy(c,'SELECT * FROM '+scan(path)+' WHERE NOT ('+hit+')',dest)
                require(kept==n-bad,'Mechanism exclusion count failed')
                r=dict(key=key,output=record(dest),month=month,before=n,removed=bad,eligible_removed=eligible);write(done,r)
            filtered.append(dest);removals.append({k:r[k] for k in ('month','before','removed','eligible_removed')})
    finally:c.close()
    require(sum(r['eligible_removed'] for r in removals)==25,'Mechanism author hits differ from reviewed audit')
    table(args.run/'report/mechanism_removals',removals);prepared={};key=digest([ledger,ids,sha(__file__)])
    # Preserve the original deterministic standardization roster; no replacements.
    for state in ('equal','losing'):
        prior=args.project/'derived/replication/mechanism_rd_audit_v100_PRIVATE/prepared'/state/'PREPARED.json';old=read(prior)
        frozen=Path(old['cohorts']['rd110']['standardization']);entry=[r for r in old['files'] if r['path']==str(frozen)]
        require(len(entry)==1,'Frozen standardization roster not manifested');verify(entry[0])
        prepared[state]=prepare_frozen(filtered,state,out/'PRIVATE',out/'report',key+state,min(4,args.workers),int((args.memory_gb-2)*1024),frozen)
    tasks=[(state,m,prepared[state],str(out/'PRIVATE'),str(out/'report'),key+state+m) for state in ('equal','losing') for m in design.MODELS]
    workers=max(1,min(2,args.workers,int(args.memory_gb/4)))
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool,heartbeat('Author-excluded mechanism fits'):
        statuses=[]
        for i,r in enumerate(pool.map(model_job,tasks),1):statuses.append(r);log(f'Mechanism candidate jobs {i}/{len(tasks)}: '+r['status'])
    diagnostics=[(s,m,c,prepared[s],str(out/'PRIVATE'),str(out/'report'),key) for s in ('equal','losing') for m in (('cost','framing','strength') if s=='equal' else ('strength',)) for c in ('original','rd110')]
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool,heartbeat('Unrestricted mechanism diagnostics'):diag=list(pool.map(unrestricted_job,diagnostics))
    # Aggregate only new excluded outputs. Never import legacy included figures.
    for name in ('coefficients','heldout_scores','heldout_calibration','conditional_score_diagnostics','common_index_profiles'):
        frames=[pd.read_parquet(p) for p in sorted((out/'report/models').glob('*/*/'+name+'.parquet'))]
        common.table(pd.concat(frames,ignore_index=True),out/'report'/(name+'.parquet'))
    scores=pd.read_parquet(out/'report/heldout_scores.parquet');comparisons,selected=reporting.score_comparisons(scores)
    common.table(comparisons,out/'report/model_comparisons.parquet');write(out/'report/MODEL_COMPARISON_STATUS.json',selected)
    months,summary=reporting.training_comparisons(scores);common.table(months,out/'report/same_test_refitting_by_month.parquet');common.table(summary,out/'report/same_test_refitting_summary.parquet')
    calibration=pd.read_parquet(out/'report/heldout_calibration.parquet')
    if 'rows' in calibration:
        x=calibration.groupby(['state','comparison','model','gap_bin'],as_index=False)[['rows','observed_grants','predicted_grants']].sum()
        x['observed_rate_pp']=100*x.observed_grants/x.rows;x['predicted_rate_pp']=100*x.predicted_grants/x.rows
        x['residual_pp']=x.observed_rate_pp-x.predicted_rate_pp
        x['scope']='Identical informative held-out chooser-month groups; totals conditioned on, no marginal probability forecast'
        common.table(x,out/'report/heldout_gap_calibration.parquet')
    failures=[x for x in statuses if x['status']!='COMPLETE']+[x for x in diag if x['status']!='ESTIMATED']
    result=dict(status='AUTHOR_EXCLUDED_MECHANISM_FITS_COMPLETE' if not failures else 'FIT_FAILURES_REQUIRE_REVIEW',candidate_jobs=statuses,diagnostics=diag,fit_failures=failures,removed_eligible=25,full_and_rd110=True,factual_regularity_preserved=True,standardization_no_replacements=True,scope='Regular equal/losing candidate models, two temporal folds, RD110 sensitivity and unrestricted diagnostics; earlier tier2/sampled mechanism families remain outside this adapter')
    write(out/'report/AUTHOR_EXCLUSION_STATUS.json',result)
    require(not failures,'Mechanism fit convergence failures; all computed outputs preserved')
    return result
