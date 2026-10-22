"""Common-test-set comparison, signed score diagnostics, and transparent fits."""
from common import *
from design import design,counterfactual,MODELS
from stats import groups,demean,conditional_kernel,fit_conditional
from model_utils import fit_one,FOLDS

def restore(f):
    f=dict(f)
    for n in ('beta','cov','identified','boundary','switcher_ids'):
        if n in f:f[n]=np.asarray(f[n],dtype=bool if n in ('identified','boundary') else float)
    return f

def source_fit(source,state,model,fold,reference,work):
    suffix='' if fold is None else f'_fold{fold}'
    path=Path(source)/'models'/('regular_'+state+'_'+model+suffix+'.json')
    auth(path,work);f=restore(read(path)['fit'])
    if f.get('status')!='ESTIMATED' or f.get('model')!=model:
        raise RuntimeError('Original model cache unavailable or not estimated: '+str(path))
    if fold is None:
        expected=reference['states'][state]['full_fits'][model]
        if expected['names']!=f['names'] or not np.allclose(expected['beta'],f['beta'],rtol=1e-10,atol=1e-10):
            raise RuntimeError('Original full coefficients differ from reviewed result')
        for k in ('n','grants','accounts'):
            if expected[k]!=f[k]:raise RuntimeError('Original estimation count differs: '+k)
    return f

def save_public_fit(f,path,**labels):
    write(path,{**{k:v for k,v in f.items() if k!='switcher_ids'},**labels})

def coefficient_rows(f,**labels):
    rows=[]
    for j,name in enumerate(f.get('names',[])):
        if 'beta' not in f:continue
        boundary=np.asarray(f.get('boundary',np.zeros(len(f['beta']),bool)),bool)
        cov=np.asarray(f.get('cov',np.full((len(boundary),len(boundary)),np.nan)),float)
        identified=np.asarray(f.get('identified',np.zeros(len(boundary),bool)),bool)
        se=np.sqrt(max(0,cov[j,j])) if f['status']=='ESTIMATED' and identified[j] and not boundary.any() and np.isfinite(cov[j,j]) else np.nan
        rows.append(dict(**labels,model=f.get('model'),term=name,beta=f['beta'][j],se=se,
            lo=f['beta'][j]-1.96*se,hi=f['beta'][j]+1.96*se,
            constrained_boundary=bool(boundary[j]),any_constrained_boundary=bool(boundary.any()),
            interval_status='INTERIOR_IDENTIFIED_WALD' if np.isfinite(se) else 'NO_ORDINARY_WALD_INTERVAL',
            note='A constrained zero is not evidence of a zero effect or an unrestricted negative coefficient',
            model_status=f['status'],n=f.get('n'),grants=f.get('grants'),accounts=f.get('accounts'),curvature=f.get('curvature')))
    return rows

def cached_fit(dpath,meta,model,path,key,inference=True,unrestricted=False,start=None):
    path=Path(path)
    if path.exists():
        r=read(path)
        if r['key']!=key:raise RuntimeError('Audit fit cache changed: '+str(path))
        return restore(r['fit'])
    d=pd.read_parquet(dpath)
    if unrestricted:
        X,names,_=design(d,model)
        f=fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),inference=True,start=start,maxiter=500)
        f.update(model=model,names=names,curvature=.5,cue=None)
    else:f=fit_one(d,model,inference=inference)
    f.update(full_n=int(meta['n']),full_accounts=int(meta['accounts']))
    write(path,dict(key=key,fit=f));return f

def evaluate(d,f,meta,**labels):
    """Same exact conditional score as v1.0.0, allocating only informative rows."""
    if f['status']!='ESTIMATED':
        return [dict(**labels,model=f['model'],month=m['month'],loglik=np.nan,
                     rows=m['rows'],grants=m['grants'],informative_rows=m['informative_rows'],
                     informative_groups=m['informative_groups'],training_status=f['status']) for m in meta],[]
    if len(d):
        X,names,_=design(d,f['model'],f['curvature']);assert names==f['names']
        ids=pd.MultiIndex.from_arrays([d.chooser,d.month]).factorize()[0]
        order,st,en=groups(ids);y=d.y.to_numpy(float)[order]
        ll,residual=conditional_kernel(X[order]@f['beta'],y,st,en)
        z=d.iloc[order];prob=y-residual
        if not np.isfinite(prob).all() or np.min(prob)<-1e-8 or np.max(prob)>1+1e-8:
            raise RuntimeError('Invalid conditional probabilities')
        if not np.allclose(np.add.reduceat(prob,st),np.add.reduceat(y,st),rtol=1e-8,atol=1e-7):
            raise RuntimeError('Conditional predictions do not conserve group grant counts')
        totals=pd.DataFrame(dict(month=z.month.to_numpy()[st],ll=ll,n=en-st)).groupby('month').agg(loglik=('ll','sum'),groups=('ll','size'),n=('n','sum'))
        bins=(np.floor((z.g.to_numpy()+25)/50)*50).astype(int)
        cal=pd.DataFrame(dict(month=z.month.to_numpy(),gap_bin=bins,y=y,p=prob)).groupby(['month','gap_bin']).agg(
            rows=('y','size'),observed_grants=('y','sum'),predicted_grants=('p','sum')).reset_index()
        for k,v in dict(**labels,model=f['model']).items():cal[k]=v
        cal['meaning']='Conditional allocation in identical outcome-varying held-out chooser-month groups; group grant totals are conditioned on'
        calibration=cal.to_dict('records')
    else:totals=pd.DataFrame();calibration=[]
    rows=[]
    for m in meta:
        a=totals.loc[m['month']] if len(totals) and m['month'] in totals.index else None
        if (int(a['groups']) if a is not None else 0)!=m['informative_groups']:
            raise RuntimeError('Validation informative-group count changed')
        rows.append(dict(**labels,model=f['model'],month=m['month'],loglik=float(a.loglik) if a is not None else 0.,
            rows=int(m['rows']),grants=int(m['grants']),informative_rows=int(m['informative_rows']),
            informative_groups=int(m['informative_groups']),training_status=f['status']))
    return rows,calibration

def rd_class(rd,opp):
    return np.where((rd<=110)&(opp<=110),'both_le110',
           np.where((rd>110)&(opp<=110),'own_only_gt110',np.where((rd<=110)&(opp>110),'opponent_only_gt110','both_gt110')))

def score_diagnostics(d,f,**labels):
    if f['status']!='ESTIMATED' or not len(d):return []
    X,names,_=design(d,f['model'],f['curvature']);order,st,en=groups(d.chooser.to_numpy())
    d=d.iloc[order];X=X[order];y=d.y.to_numpy(float)
    ll,r=conditional_kernel(X@f['beta'],y,st,en)
    if len(d)!=f['n'] or int(y.sum())!=f['grants'] or len(st)!=f['accounts']:
        raise RuntimeError('Conditional fit population differs from cached estimation counts')
    if not np.isclose(ll.sum(),f['loglik'],rtol=1e-9,atol=1e-5):
        raise RuntimeError('Full-history likelihood does not reproduce fit receipt')
    Z=demean(X,d.chooser.to_numpy());category=rd_class(d.rd.to_numpy(),d.opp_rd.to_numpy())
    terms=[j for j,n in enumerate(names) if n in ('own_cost','opponent_stake','draw_frame','extra_loss','utility_cost') or n.startswith('strength_')]
    out=[]
    for j in terms:
        scores=Z[:,j]*r;sq=Z[:,j]**2;absolute=np.abs(scores).sum();variation=sq.sum()
        if not np.isclose(scores.sum(),X[:,j]@r,rtol=1e-5,atol=1e-5):
            raise RuntimeError('Within-chooser score centering failed')
        for group in np.unique(category):
            m=category==group
            out.append(dict(**labels,model=f['model'],term=names[j],RD_class=group,n=int(m.sum()),
                grants=int(y[m].sum()),choosers=d.loc[m,'chooser'].nunique(),signed_score=float(scores[m].sum()),
                absolute_row_score=float(abs(scores[m]).sum()),absolute_row_score_share=float(abs(scores[m]).sum()/absolute) if absolute else None,
                centered_regressor_ss=float(sq[m].sum()),centered_regressor_ss_share=float(sq[m].sum()/variation) if variation else None,
                meaning='Exact full-history conditional score, centered within chooser. Variation shares are not Fisher information, causal shares, or a leverage decomposition.'))
    return out

def index_profiles(stand,f,**labels):
    if f['status']!='ESTIMATED' or not len(stand):return []
    zero=counterfactual(stand,g=0);Z,_,_=design(zero,f['model'],f['curvature']);eta0=Z@f['beta'];out=[]
    for gap in (-300,-200,-100,-50,0,50,100,200,300):
        W,_,_=design(counterfactual(stand,g=gap),f['model'],f['curvature'])
        out.append(dict(**labels,model=f['model'],gap=gap,index_difference=float(np.mean(W@f['beta']-eta0)),
            standardization_rows=len(stand),frame='Common outcome-independent RD<=110 rows for both fitted models',
            units='Conditional logit index; no additional probability/intercept calibration'))
    return out

def run_model(task):
    state,model,prepared,source,work,report,reference,run_key=task
    work,report=Path(work),Path(report)
    job=work/'jobs'/(state+'_'+model+'.json')
    key=digest(dict(run=run_key,state=state,model=model,prepared_key=prepared['key']))
    if job.exists():
        r=read(job)
        if r['key']!=key:raise RuntimeError('Model job identity differs')
        for p in r['outputs']:auth(p['path'],work,p['sha256'])
        log(state+'/'+model+': reusing completed audit');return r['status']
    log(state+'/'+model+': fitting capped sample and scoring common holdouts')
    own=report/'models'/state/model;own.mkdir(parents=True,exist_ok=True)
    coeff=[];scores=[];calibration=[];diagnostics=[];profiles=[];statuses=[]
    original=source_fit(source,state,model,None,reference,work)
    stand=pd.read_parquet(prepared['cohorts']['rd110']['standardization'])
    for cohort in ('original','rd110'):
        p=prepared['cohorts'][cohort]
        f=original if cohort=='original' else cached_fit(p['fit_full'],p['meta'],model,work/'fits'/(state+'_'+model+'_full.json'),key+'full')
        statuses.append(f['status']);coeff+=coefficient_rows(f,state=state,training=cohort,stage='full')
        save_public_fit(f,own/(cohort+'_full_fit.json'),state=state,training=cohort)
        profiles+=index_profiles(stand,f,state=state,training=cohort)
        if f['status']=='ESTIMATED':diagnostics+=score_diagnostics(pd.read_parquet(p['fit_full']),f,state=state,training=cohort)
    del stand
    for fold in range(2):
        original=source_fit(source,state,model,fold,reference,work)
        o=prepared['cohorts']['original']['folds'][fold];c=prepared['cohorts']['rd110']['folds'][fold]
        a,cal=evaluate(pd.read_parquet(o['test_path']),original,o['test_meta'],state=state,fold=fold,comparison='original_train_original_test')
        expected=[r for r in reference['states'][state]['heldout_scores'] if r['model']==model and r['fold']==fold]
        if len(a)!=len(expected):raise RuntimeError('Original validation month count changed')
        for r,e in zip(sorted(a,key=lambda x:x['month']),sorted(expected,key=lambda x:x['month'])):
            if r['month']!=e['month'] or r['rows']!=e['rows'] or r['informative_groups']!=e['informative_groups'] or not np.isclose(r['loglik'],e['loglik'],rtol=1e-9,atol=1e-5):
                raise RuntimeError('Original held-out score does not reproduce reviewed result: '+str((state,model,fold,r['month'])))
        scores+=a;calibration+=cal
        test=pd.read_parquet(c['test_path'])
        a,cal=evaluate(test,original,c['test_meta'],state=state,fold=fold,comparison='original_train_rd110_test')
        scores+=a;calibration+=cal
        coeff+=coefficient_rows(original,state=state,training='original',stage='fold'+str(fold))
        save_public_fit(original,own/('original_fold'+str(fold)+'_fit.json'),state=state,training='original')
        f=cached_fit(c['train_path'],c['train_meta'],model,work/'fits'/(state+'_'+model+f'_fold{fold}.json'),key+str(fold),inference=False)
        statuses.append(f['status']);a,cal=evaluate(test,f,c['test_meta'],state=state,fold=fold,comparison='rd110_train_rd110_test')
        scores+=a;calibration+=cal
        coeff+=coefficient_rows(f,state=state,training='rd110',stage='fold'+str(fold))
        save_public_fit(f,own/('rd110_fold'+str(fold)+'_fit.json'),state=state,training='rd110')
        del test
    for name,rows in [('coefficients',coeff),('heldout_scores',scores),('heldout_calibration',calibration),('conditional_score_diagnostics',diagnostics),('common_index_profiles',profiles)]:
        table(rows,own/(name+'.parquet'))
    status=dict(state=state,model=model,status='COMPLETE' if all(s=='ESTIMATED' for s in statuses) else 'COMPLETE_WITH_FIT_FAILURES')
    write(job,dict(key=key,status=status,outputs=[dict(path=str(p),sha256=sha(p)) for p in sorted(own.rglob('*')) if p.is_file()]))
    log(state+'/'+model+': '+status['status']);return status

def unrestricted_task(task):
    state,model,cohort,prepared,source,work,report,reference,run_key=task
    p=prepared['cohorts'][cohort];work,report=Path(work),Path(report)
    original=source_fit(source,state,model,None,reference,work)
    key=digest(dict(run=run_key,state=state,model=model,cohort=cohort,unrestricted=True))
    f=cached_fit(p['fit_full'],p['meta'],model,work/'unrestricted'/(state+'_'+cohort+'_'+model+'.json'),key,
                 unrestricted=True,start=original['beta'])
    own=report/'unrestricted';own.mkdir(exist_ok=True)
    prefix=state+'_'+cohort+'_'+model
    save_public_fit(f,own/(prefix+'_fit.json'),state=state,training=cohort,scope='Unrestricted-sign diagnostic; excluded from candidate selection')
    table(coefficient_rows(f,state=state,training=cohort,stage='full_unrestricted'),own/(prefix+'_coefficients.parquet'))
    profiles=index_profiles(pd.read_parquet(prepared['cohorts']['rd110']['standardization']),f,state=state,training=cohort)
    table(profiles,own/(prefix+'_index_profiles.parquet'))
    return dict(state=state,model=model,training=cohort,status=f['status'])
