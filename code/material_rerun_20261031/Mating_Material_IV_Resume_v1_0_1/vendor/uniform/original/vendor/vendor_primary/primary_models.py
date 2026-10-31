"""Rebind R9/R9b estimators; every fitted table carries its actual row digest."""
from primary_common import *
from primary_balance import balance

LEVELS=('X0_ENV_indicator','X0')

def assert_reference(actual,expected,label):
    for name in ('exposures','recipients','first_stage','first_stage_se','reduced_form','reduced_form_se','iv','iv_se','first_stage_F'):
        require(np.isclose(actual[name],expected[name],atol=2e-7,rtol=1e-7),label+' reproduction failed: '+name)

def r9job(source,scores,run,conf,name,level,**kw):
    job=frozen.r9_models.make_job(source,scores,run/'PRIVATE/fits'/name,conf,'receipt_total5','iv',level,**kw)
    job.update(engine='r9',name=name,memory_gb=5.5)
    return job

def r9bjob(source,scores,run,conf,name,level,**kw):
    n=pq.ParquetFile(source).metadata.num_rows
    return dict(name=name,input=str(source),scores=str(scores),output=str(run/'PRIVATE/fits'/name),conf=conf,
                engine='r9b',level=level,candidate='all',memory_gb=min(9.,max(3.,1.5+n*900/1024**3)),**kw)

def dispatch(job):
    if job['engine']=='r9':return frozen.r9_models.fit_job(job)
    if job['engine']=='calibration':return frozen.r9_models.calibration_job(job)
    return models.fit_job(job)

def execute(a,run,conf,jobs,label,callback=None):
    if not jobs:return
    # Each model uses one BLAS thread. The existing scheduler admits jobs only
    # while the sum of declared reservations fits the total memory budget.
    frozen.runtime.mapped(dispatch,jobs,a.workers,a.memory_gb,label,45,60,callback)

def initial(a,run,conf,b):
    src=b['primary'];scores=b['primary_scores'];root=run/'PRIVATE/primary';root.mkdir(parents=True,exist_ok=True)
    controls=frozen.r.X0+frozen.r.ENV+['env_supported']
    ck=key([conf,sha(src),sha(scores),'reproduce_R12'])
    got=cached_json(root/'reproduction.json',ck,lambda:iv.iv_fit(src,scores,controls))
    assert_reference(got,b['baseline'],'Rebuilt R12 primary')
    save(run/'report/primary_reproduction.json',dict(passed=True,expected=b['baseline'],reestimated=got))
    old=b['bound'];oldsrc=old['s0'];oldscore=Path(old['parent'])/'scores_combined/S0.parquet'
    oldfit=cached_json(root/'legacy_reproduction.json',key([conf,sha(oldsrc),sha(oldscore)]),lambda:iv.iv_fit(oldsrc,oldscore,controls))
    iv.reproduce(oldfit,4)
    csv_out(run/'report/cohort_comparison.csv',[dict(sample='primary_total_decisions_five',**got),dict(sample='legacy_historical_support',**oldfit)])
    ladder=[]
    for j,names in enumerate([[],frozen.r.NH,frozen.r.X0,controls],1):
        fit=got if j==4 else cached_json(root/f'ladder_{j}.json',key([ck,'ladder',j]),lambda names=names:iv.iv_fit(src,scores,names))
        ladder.append(dict(column=j,controls=names,**fit));csv_out(run/'report/first_stage_ladder.csv',ladder)
    balance(src,scores,run,conf)
    jobs=[]
    for level in LEVELS:
        jobs += [r9job(src,scores,run,conf,'primary_r9__'+level,level,figure=level==LEVELS[0]),
                 r9bjob(src,scores,run,conf,'primary_ols__'+level,level,ols=True)]
    save(run/'PRIVATE/PRIMARY_PLAN.json',jobs)
    execute(a,run,conf,jobs,'Primary receipt, OLS, balance and first-stage bins')
    # A second implementation path must agree with the R12 FWL result.
    rows=load(run/'PRIVATE/fits'/('primary_ols__'+LEVELS[0])/'result.json')['estimates']
    for est,field,se in [('first_stage','first_stage','first_stage_se'),('reduced_form','reduced_form','reduced_form_se'),('2SLS','iv','iv_se')]:
        r=next(x for x in rows if x.get('estimator')==est and x.get('outcome')==('received' if est=='first_stage' else 'y'))
        require(np.isclose(r['coefficient_pp'],got[field],atol=2e-7,rtol=1e-7),'R9b/R12 coefficient bridge failed: '+est)
        require(np.isclose(r['standard_error_pp'],got[se],atol=2e-7,rtol=1e-7),'R9b/R12 SE bridge failed: '+est)
    save(run/'report/estimator_bridge.json',dict(R12_R9b_primary_match=True))
    return jobs

def subset(a,run,conf,source,scores,label,where,material=None,flags=None):
    root=run/'PRIVATE/subsets'/label
    deps=[source,scores]+([material] if material else [])+([flags] if flags else [])
    def build(tmp):
        c=db(tmp/'spill',a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]));c.execute('CREATE VIEW s AS SELECT * FROM '+parq([scores]))
            join='q JOIN s USING(row_id)'
            if material:c.execute('CREATE VIEW m AS SELECT * FROM '+parq([material]));join+=' JOIN m USING(row_id)'
            if flags:c.execute('CREATE VIEW f AS SELECT * FROM '+parq([flags]));join+=' JOIN f USING(row_id)'
            c.execute('CREATE VIEW selected AS SELECT q.row_id FROM '+join+' WHERE '+where);n=c.execute('SELECT count(*) FROM selected').fetchone()[0]
            copy_query(c,'SELECT q.* FROM q JOIN selected USING(row_id) ORDER BY row_id',tmp/'source.parquet')
            copy_query(c,'SELECT s.* FROM s JOIN selected USING(row_id) ORDER BY row_id',tmp/'scores.parquet')
            return dict(rows=n,selection=where)
        finally:c.close()
    folder,info=frozen.r.stable_stage(root,conf,build,deps)
    return folder/'source.parquet',folder/'scores.parquet'

def diagnostic_plan(a,run,conf,b,wider,scores,flags,act,material):
    src=b['primary'];wsrc,wscore=wider;jobs=[]
    # These subsets restrict the already selected primary cohort. They never
    # alter the score-A support screen or redo primary spacing.
    subsets={}
    for label,where in [('before_supported','s.n_B>=5 AND isfinite(s.adjusted_B)'),
                        ('timing_common','s.n_B>=5 AND s.n_C>=5 AND isfinite(s.adjusted_B) AND isfinite(s.adjusted_C)')]:
        subsets[label]=subset(a,run,conf,src,scores,label,where)
    for level in LEVELS:
        for hour in ('start','last_move'):
            jobs.append(r9bjob(src,scores,run,conf,'hour_'+hour+'__'+level,level,hour=hour,ols=True))
        for name,candidate,rich,repeat,fe in frozen.SPECIFICATIONS:
            if name=='primary90':continue
            job=r9bjob(wsrc,wscore,run,conf,name+'__'+level,level,rich=rich,repeat=repeat,fe=fe,
                      balance=name in ('primary90_without_recipient_history','repeated_recipient_FE'))
            job['candidate']=candidate;jobs.append(job)
        for kind,values in [('speed',range(4)),('rating',range(4)),('prior',range(3)),('month',range(24))]:
            for value in values:jobs.append(r9bjob(src,scores,run,conf,f'subgroup_{kind}_{value}__{level}',level,subgroup=[kind,value]))
        jobs.append(r9bjob(src,scores,run,conf,'compliers__'+level,level,kind='compliers'))
        for label,score,floor in [('competitive5','competitive',5),('competitive3','competitive',3),('noncompetitive5','noncompetitive',5)]:
            for instrument in (score,'A'):
                jobs.append(r9bjob(src,scores,run,conf,f'donor_{label}_{instrument}__{level}',level,instruments=[instrument],support=[[score,floor]]))
        for label,instruments,kind in [('two_scores',['competitive','noncompetitive'],'two_score'),('joint_rows_A',['A'],'regular')]:
            jobs.append(r9bjob(src,scores,run,conf,'donor_'+label+'__'+level,level,instruments=instruments,kind=kind,support=[['competitive',5],['noncompetitive',5]]))
        jobs.append(r9bjob(src,scores,run,conf,'act_result__'+level,level,kind='act',act=str(act)))
        jobs[-1]['memory_gb']=7.
        jobs.append(r9job(src,scores,run,conf,'neutral__'+level,level,cohort='neutral',material=material))
        for label,variants in [('before_supported',('A','B')),('timing_common',('A','B','C'))]:
            ss,sc=subsets[label]
            for variant in variants:jobs.append(r9job(ss,sc,run,conf,f'{label}_{variant}__{level}',level,variant=variant))
        for flag in ('full_chronology','flag_90d'):
            for value in (False,True):jobs.append(r9job(src,scores,run,conf,f'learning_{flag}_{int(value)}__{level}',level,flags=flags,split=[flag,value]))
        jobs.append(dict(engine='calibration',name='calibration__'+level,input=str(src),scores=str(scores),
                         output=str(run/'PRIVATE/fits'/('calibration__'+level)),conf=conf,level=level,memory_gb=9.))
    save(run/'PRIVATE/DIAGNOSTIC_PLAN.json',jobs)
    return jobs

def timing_contrasts(a,run,conf):
    jobs=[]
    for level in LEVELS:
        for label,left,right in [('before_supported','A','B'),('timing_common','A','B'),('timing_common','B','C')]:
            name=f'{label}_{left}_minus_{right}__{level}'
            jobs.append(dict(left=str(run/'PRIVATE/fits'/f'{label}_{left}__{level}'),right=str(run/'PRIVATE/fits'/f'{label}_{right}__{level}'),
                label=name,outcomes=['y','reached','iv_y'],level=level,conf=conf,output=str(run/'PRIVATE/contrasts'/name),memory_gb=8.))
        for flag in ('full_chronology','flag_90d'):
            name=f'learning_{flag}_experienced_minus_new__{level}'
            jobs.append(dict(left=str(run/'PRIVATE/fits'/f'learning_{flag}_1__{level}'),right=str(run/'PRIVATE/fits'/f'learning_{flag}_0__{level}'),
                 label=name,outcomes=['y','reached','iv_y'],level=level,conf=conf,output=str(run/'PRIVATE/contrasts'/name),memory_gb=8.))
    frozen.runtime.mapped(frozen.r9_models.contrast_job,jobs,a.workers,a.memory_gb,'Timing-score differences with joint account/date covariance',20,5)
    save(run/'PRIVATE/TIMING_CONTRAST_PLAN.json',jobs)
    return jobs

def comparison100(a,run,conf):
    """Update the receipt contrast against the separately certified O100 population."""
    expected=load(PACKAGE/'evidence/comparison100_summary.json');oldconf=expected['configuration_sha256']
    parent=a.comparison_root or a.project/'derived/replication/run2_phase100_score_a_v100_PRIVATE'/oldconf[:12]
    require(load(parent/'report/summary.json')==expected,'Completed Phase-100 Score A report changed')
    require(expected['status']=='PHASE_100_SCORE_A_COMPLETE','Phase-100 comparisons incomplete')
    for rec in load(PACKAGE/'evidence/comparison100_REPORT_MANIFEST.json'):
        frozen.r.io.checked(parent/'report'/rec['path'],rec['sha256'],rec['bytes'])
    jobs=[]
    for level in LEVELS:
        oldfit=parent/'fits'/('O100__A__'+level)
        for n in ('result.json','influence_PRIVATE.parquet'):frozen.r9_inputs.stage_file(oldfit/n,oldconf)
        rows=load(oldfit/'result.json')['estimates']
        require(all(x['n']==9528012 and x['score']=='A' and x['control_mode']=='matched' for x in rows),'Wrong ordinary-game comparator')
        name='receipt_total5_minus_ordinary100__'+level
        jobs.append(dict(left=str(run/'PRIVATE/fits'/('primary_r9__'+level)),right=str(oldfit),label=name,outcomes=['y','reached'],
             level=level,conf=conf,output=str(run/'PRIVATE/contrasts'/name),memory_gb=9.))
    frozen.runtime.mapped(frozen.r9_models.contrast_job,jobs,1,a.memory_gb,'Updated receipt-minus-ordinary contrasts on actual shared accounts/dates',20,5)
    save(run/'PRIVATE/COMPARISON_CONTRAST_PLAN.json',jobs)
    # The comparator was designed separately. Preserve, and explicitly identify,
    # its population instead of pretending it is rebuilt under receipt support.
    for name in ('ordinary','entry'):
        rows=load(PACKAGE/'evidence'/('comparison100_'+name+'.json'))
        csv_out(run/'report'/('legacy_comparison100_'+name+'.csv'),[dict(x,provenance='Unchanged certified Phase-100 comparison population; not rebuilt under receipt total-five eligibility') for x in rows])
    return jobs
