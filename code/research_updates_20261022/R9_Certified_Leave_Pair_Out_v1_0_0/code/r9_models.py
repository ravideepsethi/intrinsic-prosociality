"""Frozen FE/CR0 equations, new history controls, shared-covariance contrasts."""
from r9_common import *
import gc

def load_data(job,work):
    work.mkdir(parents=True,exist_ok=True)
    source=job['input'];n=pq.ParquetFile(source).metadata.num_rows
    scores=job['scores'];a=r.arrays(r.io.read(scores,['row_id']+[k+'_'+v for v in ('A','B','C') for k in ('n','counterparts','expected','adjusted')]))
    ids=r.io.arr(r.io.read(source,['row_id']),'row_id');u.require(np.array_equal(ids,a['row_id']),'Model scores not in source row order')
    keep=np.ones(n,bool);variant=job['variant'];cohort=job.get('cohort','full')
    if cohort=='common':keep &= (a['n_B']>=5)&(a['n_C']>=5)
    if job.get('material'):
        mat=r.arrays(r.io.read(job['material'],['row_id','material_valid','material_neutral']))
        u.require(np.array_equal(ids,mat['row_id']),'Material identities differ')
        keep &= mat['material_valid'].astype(bool)&mat['material_neutral'].astype(bool)
    if job.get('learning'):
        flags=r.arrays(r.io.read(job['learning'],['row_id','experienced_'+job['learning_definition']]))
        u.require(np.array_equal(ids,flags['row_id']),'Learning flag identities differ')
        keep &= flags['experienced_'+job['learning_definition']].astype(bool)==job['experienced']
    u.require(np.all(a['n_'+variant][keep]>=5),'Fewer than five '+variant+' donors on required rows; no rows dropped')
    d={};names=set(pq.ParquetFile(source).schema_arrow.names)
    wanted=['row_id','recipient_id','opponent_id','archive_start_ms','month_code','tc_base_s','tc_inc_s',
        'recipient_rating','opponent_rating','n_7d','counterparts_7d','expected_7d','pre_games_30d']
    wanted += [f'{name}_{days}' for days in (30,90) for name in ('fair','kind','disconnect','receipt','claim')]
    wanted += models.model_outcomes({},job.get('kind','iv'))
    if job.get('level','X0_ENV_indicator')=='X0_ENV_indicator':wanted+=r.ENV+['environment_supported']
    u.require(set(wanted)<=names,'Required frozen model fields are missing: '+str(sorted(set(wanted)-names)))
    for k in dict.fromkeys(wanted):
        value=r.io.arr(r.io.read(source,[k]),k)
        d[k]=memmap_column(work,k,value if keep.all() else value[keep]);del value
    if job.get('score_recipe')=='old':
        b=r.arrays(r.io.read(job['old_scores'],['row_id','adjusted_all_time']))
        u.require(np.array_equal(ids,b['row_id']),'Old score identities differ')
        d['adjusted_7d']=memmap_column(work,'z',b['adjusted_all_time'][keep])
    else:d['adjusted_7d']=memmap_column(work,'z',a['adjusted_'+variant][keep])
    if job.get('history','rebuilt')!='old':
        history_variant=job.get('history_score','A' if variant=='C' else variant)
        for sourcekey,dest in [('n','n_7d'),('counterparts','counterparts_7d'),('expected','expected_7d')]:
            d[dest]=memmap_column(work,'new_'+dest,a[sourcekey+'_'+history_variant][keep])
    u.require(np.isfinite(d['adjusted_7d']).all(),'Missing score on required rows')
    return d

def design(d,level,work,log_kind='log1p'):
    """Columnwise disk-backed transforms; identical frozen FEs/trait standardization."""
    n=len(d['row_id']);names=r.X0.copy()
    if level=='X0_ENV_indicator':names+=r.ENV+['env_supported']
    u.require(level in LEVELS,'Undeclared controls')
    x=np.lib.format.open_memmap(work/'design.npy',mode='w+',dtype=float,shape=(n,len(names)),fortran_order=True)
    t=np.lib.format.open_memmap(work/'traits.npy',mode='w+',dtype=float,shape=(n,15),fortran_order=True)
    def standard(v):
        v=np.asarray(v,float);u.require(np.isfinite(v).all(),'Missing frozen control or trait')
        return (v-v.mean())/max(float(v.std()),1e-12)
    for days in (90,30):
        fair=np.asarray(d[f'fair_{days}']);kind=np.asarray(d[f'kind_{days}'])
        traits={f'fair_history_present_{days}':(fair>0).astype(float),f'log_fair_{days}':np.log1p(fair),
            f'kind_ever_{days}':(kind>0).astype(float),f'kind_rate_{days}':np.divide(kind,fair,out=np.zeros(n),where=fair>0)}
        for key in ('disconnect','receipt','claim'):traits[f'log_{key}_{days}']=np.log1p(d[f'{key}_{days}'])
        for name,value in traits.items():
            if name in r.T15:t[:,r.T15.index(name)]=standard(value)
        del traits
    t[:,r.T15.index('log_volume_30')]=standard(np.log1p(d['pre_games_30d']))
    ir=d['recipient_rating'];jr=d['opponent_rating'];gap=(jr-ir)/100.
    logarithm=np.log if log_kind=='log' else np.log1p
    raw=[ir,gap,gap**2,abs(gap),logarithm(d['n_7d']),logarithm(d['counterparts_7d']),d['expected_7d']]
    for j,value in enumerate(raw):x[:,j]=standard(value)
    del raw,gap
    for name in r.X0[7:]:x[:,names.index(name)]=t[:,r.T15.index(name)]
    if 'ENV' in level:
        supported=d['environment_supported'].astype(bool)
        for name in r.ENV:
            value=np.asarray(d[name],float).copy();u.require(np.isfinite(value[supported]).all(),'Supported ENV is missing')
            value[~supported]=0;x[:,names.index(name)]=standard(value)
        x[:,names.index('env_supported')]=supported.astype(float)
    _,cell=r.num.factor(d['month_code'],d['tc_base_s'],d['tc_inc_s'],np.floor((ir+jr)/200).astype(np.int64))
    groups=[cell,d['archive_start_ms']//DAY,(d['archive_start_ms']//3600000)%168]
    return x,names,t,groups

def bin_data(z,receipt,meat,sd,slope):
    order=np.argsort(z,kind='stable');out=[];n=len(z)
    for k,ix in enumerate(np.array_split(order,20),1):
        mean=float(receipt[ix].mean());influence=np.zeros(n);influence[ix]=(receipt[ix]-mean)/len(ix)
        fit=rm.inference(mean,float(meat(influence)[0,0]),100)
        out.append(dict(bin=k,n=len(ix),mean_residual_score=float(z[ix].mean()),
            mean_score_in_primary_SD=float(z[ix].mean()/sd),minimum_residual_score=float(z[ix].min()),maximum_residual_score=float(z[ix].max()),
            mean_residual_receipt_pp=100*mean,ci95_low_pp=fit.get('ci_low_pp'),ci95_high_pp=fit.get('ci_high_pp'),
            supported=fit['supported'],linear_first_stage_pp_per_primary_SD=slope*100*sd,
            interval_method='shared-account-OR-date CR0 bin-mean intervals conditional on fitted residualization and bin membership'))
    return out

def fit_job(job):
    r.threads_one();u.no_network()
    deps=[job['input'],job['scores']]+[job[k] for k in ('material','learning','old_scores') if job.get(k)]
    def build(tmp):
        work=tmp/'work_PRIVATE';d=load_data(job,work);n=len(d['row_id'])
        if job.get('expected_n') is not None:u.require(n==job['expected_n'],'Required cohort row count changed')
        if job.get('expected_row_hash'):u.require(r.design.row_digest(d['row_id'])==job['expected_row_hash'],'Required cohort membership changed')
        log_kind=job.get('log_kind','log1p')
        x,names,t,groups=design(d,job['level'],work,log_kind)
        kind=job['kind'];outs=models.model_outcomes(d,kind);balance=job.get('balance',False)
        columns=[d['adjusted_7d']]+[d[k] for k in outs]+([t[:,k] for k in range(7)] if balance else [])
        u.require(all(np.isin(d[k],[0,1]).all() for k in outs),'Missing/nonbinary frozen outcome')
        u.log('R9 fit '+job['label']+f': {n:,} rows, frozen FEs and shared-account/date CR0')
        rr,rank=rm.project(x,columns,groups);del columns
        z=rr[:,0];zz=float(z@z);native=math.sqrt(zz/n)
        u.require(native>1e-10,'No residual score variation')
        sd=float(job.get('primary_sd') or native)
        meta=dict(label=job['label'],sample=job['sample'],score=job['variant'],cohort=job.get('cohort','full'),
            control_level=job['level'],n=n,row_set_sha256=r.design.row_digest(d['row_id']),controls=names,
            continuous_control_rank=rank,native_residual_score_SD=native,primary_score_SD=sd,
            clustering='shared_account_OR_date_CR0',generated_scores_treated_as_fixed=True,
            units='score effects in pp per common primary SD and per fixed 0.0594',
            history_controls=job.get('history','rebuilt'),count_transform=log_kind,
            history_control_donor_set='old_cutoff' if job.get('history')=='old' else job.get('history_score','A' if job['variant']=='C' else job['variant']),
            causal_identification_certified=False)
        meat=rm.covariance(d);out=dict(estimates=[],balance=[],joint_balance=[],figure5=[],implied_bias=[])
        payload=dict(row_id=d['row_id'],recipient_id=d['recipient_id'],opponent_id=d['opponent_id'],date=d['archive_start_ms']//DAY)
        for j,name in enumerate(outs,1):
            fit,inf=rm.scalar(rr[:,j],z,meat);events=int(d[name].sum());base=float(d[name].mean()*100)
            row=dict(meta,outcome=name,estimator='first_stage' if name=='received' else 'reduced_form',events=events,base_rate_pp=base,**scaled(fit,sd))
            if min(events,n-events)<10:row.update(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
            for suffix in ('primary_SD','fixed_0_0594'):
                row['share_of_base_percent_per_'+suffix]=100*row.get('coefficient_pp_per_'+suffix,0)/base if base else None
            out['estimates'].append(row);payload[name]=inf
        if kind=='iv':
            iv=r.stats.iv_result(rr[:,2],rr[:,1],z,meat)
            fields={k:v for k,v in iv.items() if k not in ('first_stage','reduced_form')}
            for key in ('iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high'):
                if key in fields:fields[key+'_pp']=100*fields[key]
            fields['first_stage_F']=iv.get('first_stage',{}).get('wald_F_one_df')
            out['estimates'].append(dict(meta,outcome='y',estimator='2SLS',units='percentage points per receipt',**fields))
            zd=float(z@rr[:,1]);u.require(abs(zd)>1e-15,'Zero first stage covariance')
            payload['iv_y']=z*(rr[:,2]-iv['iv_coefficient']*rr[:,1])/zd
        if balance:
            ts=rr[:,1+len(outs):]
            for k,name in enumerate(r.T30):
                out['balance'].append(dict(meta,trait=name,units='trait SD per native residual-score SD',**r.stats.stats.ols(ts[:,k],z/native,meat)))
            r.stats.stats.holm(out['balance'],out='p_Holm_7_traits')
            out['joint_balance'].append(dict(meta,test_set='T30',traits=r.T30,**r.stats.stats.joint(ts,z/native,meat)))
        if job.get('figure'):
            slope=out['estimates'][0]['coefficient'];out['figure5']=bin_data(z,rr[:,1],meat,sd,slope)
        if job.get('implied_bias'):
            # X0-NH is exactly the seven non-recipient-history controls. ENV belongs to the outer primary equation.
            for name in ('y','received'):
                fit=rm.generated_index(t,np.asarray(d[name],float),x[:,:7],x,np.asarray(d['adjusted_7d']),groups,meat,mode='in_sample')
                actual=next(v for v in out['estimates'] if v['outcome']==name and v['estimator']!='2SLS')
                out['implied_bias'].append(dict(meta,predicted_outcome='Y_hat' if name=='y' else 'D_hat',
                    training_controls=r.NH,training_traits=r.T15,observed_equation_coefficient_pp_per_primary_SD=actual['coefficient_pp_per_primary_SD'],
                    **scaled(fit,sd)))
        r.io.js(tmp/'result.json',out)
        if job.get('influence',True):r.io.table(tmp/'influence_PRIVATE.parquet',pa.table(payload))
        info=dict(n=n,label=job['label'],primary_score_SD=sd,native_residual_score_SD=native)
        # Only private aggregate outputs and influences survive a completed fit; working arrays are reproducible.
        del payload,d,x,t,groups,rr,meat;gc.collect()
        for p in work.iterdir():p.unlink()
        work.rmdir();return info
    return r.stable_stage(Path(job['output']),job['conf'],build,deps)[1]

def covariance_sql(left,right,leftfield,rightfield,tmp,memory):
    """Two stacked equations. Exact five-term account/pair/date inclusion-exclusion."""
    u.require(leftfield in ('y','reached','iv_y','received') and rightfield in ('y','reached','iv_y','received'),'Invalid contrast field')
    c=u.conn(tmp/'spill',memory,1)
    try:
        c.execute('CREATE VIEW s AS SELECT recipient_id i,opponent_id j,date,'+leftfield+' s0,0.0 s1 FROM '+u.parq([left])+
            ' UNION ALL SELECT recipient_id,opponent_id,date,0.0,'+rightfield+' FROM '+u.parq([right]))
        c.execute('CREATE VIEW p AS SELECT *,least(i,j) a,greatest(i,j) b FROM s')
        V=np.zeros((2,2))
        terms=[('SELECT i AS account,s0,s1 FROM p UNION ALL SELECT j,s0,s1 FROM p','account',1),
            ('SELECT a,b,s0,s1 FROM p','a,b',-1),('SELECT date,s0,s1 FROM p','date',1),
            ('SELECT i AS account,date,s0,s1 FROM p UNION ALL SELECT j,date,s0,s1 FROM p','account,date',-1),
            ('SELECT a,b,date,s0,s1 FROM p','a,b,date',1)]
        for sql,keys,sign in terms:
            v=c.execute('SELECT coalesce(sum(x*x),0),coalesce(sum(x*y),0),coalesce(sum(y*y),0) FROM (SELECT sum(s0) x,sum(s1) y FROM ('+sql+') GROUP BY '+keys+')').fetchone()
            V+=sign*np.array([[v[0],v[1]],[v[1],v[2]]])
        return V
    finally:r.finish_connection(c,tmp/'spill')

def contrast_job(job):
    r.threads_one();u.no_network()
    deps=[str(Path(folder)/name) for folder in (job['left'],job['right']) for name in ('result.json','influence_PRIVATE.parquet')]
    def build(tmp):
        l=u.load(Path(job['left'])/'result.json')['estimates'];rr=u.load(Path(job['right'])/'result.json')['estimates'];out=[]
        for field in job['fields']:
            estimator='2SLS' if field=='iv_y' else 'reduced_form';name='y' if field=='iv_y' else field
            a=next(v for v in l if v['estimator']==estimator and v['outcome']==name)
            b=next(v for v in rr if v['estimator']==estimator and v['outcome']==name)
            V=covariance_sql(Path(job['left'])/'influence_PRIVATE.parquet',Path(job['right'])/'influence_PRIVATE.parquet',field,field,tmp,job['sql_memory'])
            k='iv_coefficient' if field=='iv_y' else 'coefficient';s='iv_standard_error' if field=='iv_y' else 'standard_error'
            for ix,row in enumerate((a,b)):
                if s in row:u.require(np.isclose(V[ix,ix],row[s]**2,rtol=2e-6,atol=2e-16),'Stacked covariance marginal differs from model')
            fit=rm.inference(a[k]-b[k],float(V[0,0]+V[1,1]-2*V[0,1]),100 if field=='iv_y' else 1)
            out.append(dict(label=job['label'],control_level=job['level'],outcome=name,estimator=estimator,
                units='percentage points per receipt' if field=='iv_y' else 'percentage points per common primary SD and per fixed 0.0594',
                left_n=a['n'],right_n=b['n'],left_coefficient=a[k],right_coefficient=b[k],
                left_variance=float(V[0,0]),right_variance=float(V[1,1]),cross_equation_covariance=float(V[0,1]),
                equations_stacked=True,clustering='shared_account_OR_date_CR0',
                **(fit if field=='iv_y' else scaled(fit,job['primary_sd']))))
        r.io.js(tmp/'result.json',out);return dict(contrasts=len(out))
    return r.stable_stage(Path(job['output']),job['conf'],build,deps)[1]

def make_job(source,scores,root,conf,label,sample,level,variant='A',kind='iv',**kw):
    n=pq.ParquetFile(source).metadata.num_rows
    # Large comparison fits run alone; core numerical arrays use disk-backed inputs.
    memory=min(9.4,1.6+n*570/1024**3)
    return dict(input=str(source),scores=str(scores),output=str(root/label),conf=conf,label=label,sample=sample,
        level=level,variant=variant,kind=kind,memory_gb=memory,**kw)
