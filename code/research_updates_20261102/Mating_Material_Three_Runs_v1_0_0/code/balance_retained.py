"""The retained fifteen-trait ladder and generated-index uncertainty."""
from common_retained import *
RECENT=['recent_present','recent_log_fair','recent_ever','recent_rate','recent_log_disconnect','recent_log_receipt','recent_log_claim']
PRIOR=['fair_history_present_90','log_fair_90','kind_ever_90','kind_rate_90','log_disconnect_90','log_receipt_90','log_claim_90','log_volume_30']
def standard(v):
    v=np.asarray(v,float);require(np.isfinite(v).all(),'Nonfinite balance trait');return (v-v.mean())/max(float(v.std()),1e-12)
def traits(src,include_prior=True):
    f=col(src,'recent_fair_90');k=col(src,'recent_kind_90')
    out=dict(recent_present=f>0,recent_log_fair=np.log1p(f),recent_ever=k>0,recent_rate=np.divide(k,f,out=np.zeros(len(f)),where=f>0))
    out.update({'recent_log_'+k:np.log1p(col(src,'recent_'+k+'_90')) for k in ('disconnect','receipt','claim')})
    if include_prior:
        f=col(src,'fair_90');k=col(src,'kind_90')
        out.update(fair_history_present_90=f>0,log_fair_90=np.log1p(f),kind_ever_90=k>0,kind_rate_90=np.divide(k,f,out=np.zeros(len(f)),where=f>0),log_volume_30=np.log1p(col(src,'pre_games_30d')))
        out.update({'log_'+k+'_90':np.log1p(col(src,k+'_90')) for k in ('disconnect','receipt','claim')})
    return {k:standard(v) for k,v in out.items()}
def fit_balance(run,conf,src,scores,label,nohistory=False,environment=True):
    job=kernel.job_for(run,conf,label,src,scores,legacy=True,balance=nohistory);job.update(outcomes=[],iv=False,level='X0_ENV_indicator' if environment else 'X0')
    def build(tmp):
        raw=traits(src,include_prior=False);extra={k:raw[k] for k in RECENT}
        v,g,actors,targets,meta,_=extended_buffer(job,tmp,extra);del raw,extra
        res,rank,diag=kernel.project(v,g,len(targets),tmp);del v,g;gc.collect()
        keys=RECENT+PRIOR if nohistory else RECENT;z=res[:,0];zz=float(z@z);sd=math.sqrt(zz/len(z));require(sd>0,'No residual score')
        meta.update(native_residual_score_sd=sd,units='trait SD per native residual-score SD')
        points=np.array([float(z@res[:,targets.index(k)])/zz for k in keys]);infl=kernel.disk.disk_matrix(tmp/'influence.dat',len(z),len(keys))
        for j,k in enumerate(keys):infl[:,j]=z*(res[:,targets.index(k)]-points[j]*z)/zz
        V=meat_factory(actors,tmp)(infl);stat=frozen_systems();ests=[];joint=[]
        for j,k in enumerate(keys):ests.append(dict(meta,**fit_meta(actors),term='balance_'+k,**kernel.inference90(points[j],V[j,j],sd)))
        for label_set,subset in [('recent_7',RECENT)]+([('all_15',keys)] if nohistory else []):
            ix=[keys.index(k) for k in subset];result=stat.m7.wald(points[ix]*sd,V[np.ix_(ix,ix)]*sd**2)
            joint.append(dict(meta,**fit_meta(actors),test_set=label_set,traits=subset,**result))
        save(tmp/'result.json',dict(estimates=ests,joint_tests=joint));save(tmp/'numerical_diagnostics.json',diag)
        del res,infl;clear_design(tmp);(tmp/'influence.dat').unlink(missing_ok=True);return dict(rows=rows(src))
    out,_=stage(run/'PRIVATE/balance'/label,conf,build,[src,scores]);return read(out/'result.json')

def calibration(run,conf,src,scores):
    def build(tmp):
        raw=traits(src);keys=RECENT+PRIOR;extra={'trait_'+k:raw[k] for k in keys}
        outer=kernel.job_for(run,conf,'calibration_outer',src,scores,legacy=True)
        od=tmp/'outer';od.mkdir();v,g,actors,t,meta,_=extended_buffer(outer,od,extra)
        r,_,diag=kernel.project(v,g,len(t),od);del v,g;gc.collect()
        z=np.array(r[:,0]);zz=float(z@z);require(zz>0,'No residual score')
        # Store residualized trait columns; eight controlled traits should be
        # zero to numerical tolerance, never mistaken for independent balance.
        reference={k:float(z@r[:,t.index(k)])/zz for k in ('y','received')}
        residual_t=np.column_stack([r[:,t.index('trait_'+k)] for k in keys]);del r
        td=tmp/'training';td.mkdir();train=dict(outer,balance=True,level='X0_ENV_indicator')
        v,g,_,t,_,_=extended_buffer(train,td,extra);tr,_,tdiag=kernel.project(v,g,len(t),td);del v,g,extra;gc.collect()
        T=np.column_stack([tr[:,t.index('trait_'+k)] for k in keys]);G=T.T@T
        require(np.linalg.matrix_rank(G,tol=max(float(np.linalg.norm(G,2)),1)*1e-12)==len(keys),'Calibration training traits rank deficient')
        bread=np.linalg.inv(G);derivative=np.array([float(z@raw[k])/zz for k in keys]);del raw
        rows_out=[];meat=meat_factory(actors,tmp)
        for outcome in ('y','received'):
            Y=tr[:,t.index(outcome)];beta=bread@(T.T@Y);e=Y-T@beta
            pred=residual_t@beta;bval=float(z@pred)/zz;fixed=z*(pred-bval*z)/zz
            full=fixed+e*(T@(bread@derivative));V=meat(np.column_stack([full,fixed]))
            rows_out.append(dict(meta,**fit_meta(actors),outcome=outcome,units='percentage points per 0.04979005187533171 of score',prediction_rule_uncertainty_included=True,
              training_controls='headline nonhistory controls including ENV and its support indicator',traits=keys,interpretation='observed-trait calibration, not a bound on selection bias',
              primary_reference_coefficient_pp=reference[outcome]*100*c.SD,
              share_of_primary_reference_percent=100*bval/reference[outcome] if reference[outcome] else None,
              fixed_rule_se_pp=math.sqrt(V[1,1])*100*c.SD if V[1,1]>0 else None,**kernel.inference90(bval,V[0,0],100*c.SD)))
        save(tmp/'result.json',dict(estimates=rows_out));save(tmp/'diagnostics.json',dict(outer=diag,training=tdiag))
        del tr,T,residual_t;clear_design(td);clear_design(od);return dict(rows=rows(src),traits=15)
    out,_=stage(run/'PRIVATE/calibration',conf,build,[src,scores]);write_csv(run/'report/table_D2_implied_bias.csv',read(out/'result.json')['estimates'])

def run_ladder(a,run,conf,auth):
    results=[];src=Path(auth['paths']['spaced']);scores=Path(auth['paths']['spaced_scores'])
    for env in (True,False):
        label='spaced_nohistory_15traits'+('' if env else '_noenv');result=fit_balance(run,conf,src,scores,label,True,env)
        results.append(result)
    save(run/'report/BALANCE_NEW.json',results);calibration(run,conf,src,scores)

def combine(a,run,conf):
    """One wide six-column table, including Panel B and the joint-test rows."""
    close=a.closeout/'report'
    specs=['spaced_recent_balance','spaced_noenv_recent_balance','entry_spaced_recent_balance','ordinary_spaced_recent_balance','spaced_nohistory_15traits','repeated_FE_recent_balance']
    raw_rows=[r for r in csv_rows(close/'model_estimates.csv') if r['term'].startswith('balance_') and r['sample'] in specs]
    joints=[r for r in csv_rows(close/'balance_joint.csv') if r['sample'] in specs]
    counts=read(run/'report/DESIGN_COUNTS.json')
    for r in raw_rows+joints:
        label='repeated' if r['sample']=='repeated_FE_recent_balance' else 'spaced'
        require(int(r['n'])==counts[label]['n'],'Reused balance count differs')
        r.update(counts[label])
    for label in ('spaced_nohistory_15traits','spaced_nohistory_15traits_noenv','entry_spaced_recent_balance','ordinary_spaced_recent_balance'):
        path=run/'PRIVATE/balance'/label/'result.json';stage_record(path,conf)
        result=read(path);raw_rows+=result['estimates'];joints+=result['joint_tests']
    write_csv(run/'report/BALANCE_TRAITS.csv',raw_rows)
    normalized=[]
    for r in joints:
        normalized.append(dict(r,chi2=r.get('chi2',r.get('wald_chi2','')),df=r.get('df',r.get('rank','')),
            p_value=r.get('p_value',r.get('p_value_asymptotic','')),test_set=r.get('test_set','recent_7')))
    write_csv(run/'report/BALANCE_JOINT.csv',normalized)
    lookup={(r['sample'],r['term'].replace('balance_','')):(i+2,r) for i,r in enumerate(raw_rows)}
    joint_lookup={(r['sample'],r['test_set']):(i+2,r) for i,r in enumerate(normalized)}
    out=[]
    def put(row,column,spec,source,fields,filename):
        source_row,r=source
        row[f'column_{column}_specification']=spec;row[f'column_{column}_status']='COMPLETE'
        row[f'column_{column}_source_file']='raw/'+filename;row[f'column_{column}_source_row']=source_row
        for field in fields:row[f'column_{column}_{field}']=r.get(field,'')
    fields=('coefficient','standard_error','n','recipients','opponents','account_clusters','date_clusters','p_value')
    for trait in RECENT+PRIOR:
        row=dict(panel='A' if trait in RECENT else 'B',trait=trait)
        for j,spec in enumerate(specs,1):
            if trait in PRIOR and j!=5:continue
            require((spec,trait) in lookup,'Missing F6 cell: '+spec+'/'+trait)
            put(row,j,spec,lookup[spec,trait],fields,'BALANCE_TRAITS.csv')
        out.append(row)
    row=dict(panel='joint',trait='joint_main_test')
    jfields=('chi2','df','p_value','n','recipients','opponents','account_clusters','date_clusters')
    for j,spec in enumerate(specs,1):
        key=(spec,'all_15' if j==5 else 'recent_7')
        require(key in joint_lookup,'Missing F6 joint test: '+str(key))
        put(row,j,spec,joint_lookup[key],jfields,'BALANCE_JOINT.csv')
    out.append(row)
    for spec,test in [('spaced_nohistory_15traits','recent_7'),('spaced_nohistory_15traits_noenv','all_15')]:
        row=dict(panel='joint',trait=spec+'_'+test)
        require((spec,test) in joint_lookup,'Missing additional fifteen-trait joint test')
        put(row,5,spec,joint_lookup[spec,test],jfields,'BALANCE_JOINT.csv');out.append(row)
    write_csv(run/'report/table_F6.csv',out)
