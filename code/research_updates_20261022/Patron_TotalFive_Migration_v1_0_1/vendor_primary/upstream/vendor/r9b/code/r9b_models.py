"""Owned FWL buffers; one decoded source column at a time; fixed CR0 covariance."""
from r9b_common import *
from r7_memory import AbsorptionError

def project(v,groups,width):
    """Frozen MAP, with a certified sparse least-squares fallback for nearly nested hours."""
    try:v,diag=absorb_owned(v,groups)
    except AbsorptionError as error:
        diag=error.diagnostics
        if diag.get('reason')!='ITERATION_LIMIT_WITHOUT_CERTIFIED_CONVERGENCE':raise
        # MAP subtracts only vectors in the FE column space. Its unfinished
        # residual can therefore be projected again without changing the fit.
        np.ldexp(v,diag['power_of_two_exponent'],out=v)
        from scipy.sparse import coo_matrix
        from scipy.sparse.linalg import lsmr
        n=len(v);codes=[];counts=[];offset=0
        for g in groups:
            _,ix,ct=np.unique(g,return_inverse=True,return_counts=True)
            codes.append(ix+offset);counts.append(ct);offset+=len(ct)
        counts=np.concatenate(counts);columns=np.concatenate(codes)
        A=coo_matrix((1/np.sqrt(counts[columns]),(np.tile(np.arange(n),len(groups)),columns)),shape=(n,offset)).tocsr()
        del columns,codes
        threshold=diag['absolute_tolerance_original_units'];largest=0.;iterations=[]
        for k in range(v.shape[1]):
            fit=lsmr(A,v[:,k],atol=1e-14,btol=1e-14,conlim=1e14,maxiter=10000)
            v[:,k]-=A@fit[0];iterations.append(int(fit[2]))
            # A' residual / sqrt(count) is each FE group's residual mean.
            residual_means=(A.T@v[:,k])/np.sqrt(counts)
            largest=max(largest,float(np.max(abs(residual_means))))
            u.require(np.isfinite(v[:,k]).all() and np.max(abs(residual_means))<=threshold,'Sparse FE fallback failed orthogonality certificate')
        diag.update(status='CONVERGED',solver='MAP_then_sparse_normalized_LSMR',iterations=1000+max(iterations),
            fallback_iterations_by_column=iterations,maximum_group_mean=largest)
    x=v[:,width:];gram=x.T@x;inv=np.linalg.pinv(gram,rcond=1e-12)
    rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))
    beta=inv@(x.T@v[:,:width]);del x
    for lo in range(0,len(v),32768):v[lo:lo+32768,:width]-=v[lo:lo+32768,width:]@beta
    v.resize((len(v),width),refcheck=False)
    return v,rank,diag

COMPLIER_TRAITS=['recipient_rating','pre_games_30d','fair_90','kind_ever_90','no_fair_90',
    'disconnect_90','receipt_90','bullet_share','blitz_share','rapid_share','classical_share']
ACT_TERMS=[f'received_band_{i}' for i in range(4)]+['received_x_giver_cost_5','received_x_recipient_benefit_5']

def speed(base,inc):return np.searchsorted([180,480,1500],base+40*inc,side='right')

def select(job):
    path=job['input'];scores=job['scores'];ids=col(path,'row_id');sid=col(scores,'row_id')
    u.require(np.array_equal(ids,sid),'Source and score rows/order differ');del sid
    mask=np.ones(len(ids),bool)
    candidate=job.get('candidate','spaced90')
    if candidate!='all':mask &= col(path,'first_recipient' if candidate=='first' else candidate).astype(bool)
    if job.get('repeat'):
        people=col(path,'recipient_id');_,inv,cnt=np.unique(people[mask],return_inverse=True,return_counts=True)
        ix=np.flatnonzero(mask);mask[ix]=cnt[inv]>=2
    subgroup=job.get('subgroup')
    if subgroup:
        kind,value=subgroup
        if kind=='speed':s=speed(col(path,'tc_base_s'),col(path,'tc_inc_s'))
        elif kind=='rating':s=np.searchsorted([1200,1600,2000],col(path,'recipient_rating'),side='right')
        elif kind=='prior':s=np.where(col(path,'kind_90')>0,2,np.where(col(path,'fair_90')>0,1,0))
        elif kind=='month':s=col(path,'month_code')
        else:raise ValueError(kind)
        mask &= s==value
    for name,floor in job.get('support',[]):mask &= (col(scores,'n_'+name)>=floor)&np.isfinite(col(scores,'adjusted_'+name))
    return ids,mask

def buffer(job):
    ids,use=select(job);n=int(use.sum());allrows=bool(use.all())
    read=lambda k,path=None:col(path or job['input'],k) if allrows else col(path or job['input'],k)[use]
    names=list(r.X0 if job.get('rich',True) else r.NH)+(r.ENV+['env_supported'] if job['level']=='X0_ENV_indicator' else [])
    kind=job.get('kind','regular');instruments=job.get('instruments',['A'])
    balance=job.get('balance',False);traits=list(r.T15) if balance else []
    targets=['z_'+k for k in instruments]+['received','y','reached']+traits
    if kind=='compliers':targets+=['product_'+k for k in COMPLIER_TRAITS]
    if kind=='act':
        targets=['z_'+k for k in ACT_TERMS]+ACT_TERMS+['y','reached']
        names+=['giver_cost_5','recipient_benefit_5','log_giver_rd','log_recipient_rd','board_cp_capped600',
            'log_ply','log_giver_clock','log_recipient_clock','giver_white','band_1','band_2','band_3']
    meta=dict(model=job['name'],n=n,control_level=job['level'],controls=names,candidate=job.get('candidate','spaced90'),
        recipient_FE=bool(job.get('fe')),hour_effects=job.get('hour'),recipient_history_controls=job.get('rich',True),
        row_set_sha256=r.design.row_digest(ids[use]),common_score_SD=COMMON_SD,
        covariance='shared_account_OR_date_CR0',score=instruments[0] if len(instruments)==1 else 'joint',instruments=instruments,
        minimum_donor_support=job.get('support',[['A',5]]),score_history_controls='pooled A donor set',
        intervals='Wald 95% normal',generated_instruments_treated_as_fixed=True,subgroup=job.get('subgroup'))
    if n<2000:return None,None,None,meta,None,None
    v=np.empty((n,len(targets)+len(names)),float,order='F')
    places={k:[] for k in targets+names}
    for j,k in enumerate(targets+names):places[k].append(j)
    def fill(k,a,standard=False):
        a=np.asarray(a,float);u.require(np.isfinite(a).all(),'Missing/nonfinite '+k+'; no automatic row deletion')
        if standard:a=(a-a.mean())/max(float(a.std()),1e-12)
        for j in places.get(k,[]):v[:,j]=a
    D=read('received').astype(float);ystats={}
    for key in ['received','y','reached']:
        a=D if key=='received' else read(key)
        u.require(np.isin(a,[0,1]).all(),'Nonbinary outcome '+key);fill(key,a)
        ystats[key]=dict(events=int(a.sum()),outcome_mean_pp=float(a.mean()*100))
    ir=read('recipient_rating');jr=read('opponent_rating');gap=(jr-ir)/100
    for key,a in [('recipient_rating',ir),('rating_gap',gap),('rating_gap_square',gap*gap),('abs_rating_gap',abs(gap))]:fill(key,a,True)
    _,cells=r.num.factor(read('month_code'),read('tc_base_s'),read('tc_inc_s'),np.floor((ir+jr)/200).astype(np.int64))
    dates=read('archive_start_ms');groups=[cells,dates//DAY,(dates//3600000)%168]
    actors=dict(row_id=ids[use],recipient_id=read('recipient_id'),opponent_id=read('opponent_id'),date=dates//DAY)
    if job.get('fe'):groups.append(actors['recipient_id'])
    if job.get('hour')=='start':groups=[cells,dates//3600000]+([actors['recipient_id']] if job.get('fe') else [])
    elif job.get('hour'):groups.append(read('anchor_ms')//3600000)
    meta['fixed_effects']=['month_exact_time_control_mean_rating_100bin','exposure_date','hour_of_week']+(['recipient'] if job.get('fe') else [])+([job['hour']+'_absolute_UTC_hour'] if job.get('hour') else [])
    meta['recipients']=len(np.unique(actors['recipient_id']));del ids,ir,jr,gap,dates
    for key,src,log in [('log_opponent_prior_decisions','n_A',True),('log_opponent_prior_counterparts','counterparts_A',True),('opponent_history_expected_rate','expected_A',False)]:
        a=read(src,job['scores']);fill(key,np.log1p(a) if log else a,True)
    for days in (30,90):
        fair=read(f'fair_{days}');grant=read(f'kind_{days}')
        for key,a in [(f'fair_history_present_{days}',fair>0),(f'log_fair_{days}',np.log1p(fair)),
            (f'kind_ever_{days}',grant>0),(f'kind_rate_{days}',np.divide(grant,fair,out=np.zeros(n),where=fair>0))]:fill(key,a,True)
        for key in ['disconnect','receipt','claim']:fill(f'log_{key}_{days}',np.log1p(read(f'{key}_{days}')),True)
    fill('log_volume_30',np.log1p(read('pre_games_30d')),True)
    if job['level']=='X0_ENV_indicator':
        support=read('environment_supported').astype(bool);meta['ENV_unsupported_share']=float((~support).mean())
        for key in r.ENV:
            a=np.array(read(key),dtype=float,copy=True);u.require(np.isfinite(a[support]).all(),'ENV missing on supported rows');a[~support]=0;fill(key,a,True)
        fill('env_supported',support)
    if kind!='act':
        for key in instruments:fill('z_'+key,read('adjusted_'+key,job['scores']))
    extra={}
    if kind=='compliers':
        extra['descriptive']={}
        for key in COMPLIER_TRAITS:
            if key=='kind_ever_90':a=read('kind_90')>0
            elif key=='no_fair_90':a=read('fair_90')==0
            elif key.endswith('_share'):a=speed(read('tc_base_s'),read('tc_inc_s'))==['bullet_share','blitz_share','rapid_share','classical_share'].index(key)
            else:a=read(key)
            fill('product_'+key,D*a);extra['descriptive'][key]=dict(all_exposures=float(np.mean(a)),draw_recipients=float(np.mean(a[D==1])))
    if kind=='act':
        aid=col(job['act'],'row_id');u.require(np.array_equal(aid,actors['row_id']),'Act features do not match S0 exactly')
        aread=lambda k:col(job['act'],k)
        board=aread('board_cp');u.require(np.all(board>=-100),'Noncompetitive exposure in act frame')
        band=np.searchsorted([0,100,300],board,side='right');g=aread('giver_cost');b=aread('recipient_benefit')
        extra['band_counts']=[int((band==k).sum()) for k in range(4)]
        extra['band_support']=[]
        for k in range(4):
            useb=band==k
            extra['band_support'].append(dict(grants=int(D[useb].sum()),grant_recipients=len(np.unique(actors['recipient_id'][useb&(D==1)])),claim_recipients=len(np.unique(actors['recipient_id'][useb&(D==0)]))))
        extra['premium_q25'],extra['premium_q75']=map(float,np.quantile(g,[.25,.75]));extra['giver_cost_iqr']=extra['premium_q75']-extra['premium_q25']
        g=(g-g.mean())/5.;b=(b-b.mean())/5.;z=read('adjusted_A',job['scores'])
        for k,name in enumerate(ACT_TERMS):
            mod=(band==k).astype(float) if k<4 else (g if k==4 else b)
            fill(name,D*mod);fill('z_'+name,z*mod)
        fill('giver_cost_5',g,True);fill('recipient_benefit_5',b,True)
        for nm,source in [('log_giver_rd','giver_rd'),('log_recipient_rd','recipient_rd')]:
            a=aread(source);u.require((a>0).all(),'Nonpositive RD');fill(nm,np.log(a),True)
        fill('board_cp_capped600',np.clip(board,-600,600)/100,True);fill('log_ply',np.log1p(aread('ply')),True)
        for role in ('giver','recipient'):fill('log_'+role+'_clock',np.log1p(np.maximum(0,aread(role+'_clock'))),True)
        colors=aread('chooser_color');u.require(np.isin(colors,['white','black']).all(),'Unknown giver color');fill('giver_white',colors=='white',True)
        for k in [1,2,3]:fill('band_'+str(k),band==k,True)
    extra['raw_received']=D
    if job.get('subgroup'):
        extra['raw_score']=read('adjusted_A',job['scores'])
    return v,groups,actors,meta,targets,dict(ystats=ystats,**extra)

def estimate(job):
    v,groups,ids,meta,names,extras=buffer(job)
    tables=dict(estimates=[],balance=[],joint_balance=[],compliers=[],first_stages=[],act_contrasts=[],system=[])
    if v is None:
        tables['estimates']=[dict(meta,supported=False,reason='FEWER_THAN_2000_ROWS')];return tables
    if job.get('subgroup') and min(extras['ystats']['received']['events'],meta['n']-extras['ystats']['received']['events'])<20:
        tables['estimates']=[dict(meta,supported=False,reason='FEWER_THAN_20_RECEIPTS_OR_NONRECEIPTS')];return tables
    res,rank,diag=project(v,groups,len(names));del groups,v
    meta.update(continuous_control_rank=rank,absorb_iterations=diag['iterations'],FE_solver=diag.get('solver'),
        nested_date_and_hour_of_week_absorbed_by_absolute_start_hour=job.get('hour')=='start')
    code=r.stats.cmp.covariance_codes(ids['recipient_id'],ids['opponent_id'],ids['date']);meat=lambda s:shared_meat(s,code,True)
    fields={k:res[:,j] for j,k in enumerate(names)};kind=job.get('kind','regular')
    if kind=='act':
        z=res[:,:6];d=res[:,6:12];fs=first_stage_system(d,z,meat)
        for j,row in enumerate(fs):tables['first_stages'].append(dict(meta,term=ACT_TERMS[j],**row))
        minimum=min(x['conditional_F'] for x in fs) if all(x.get('conditional_F') is not None for x in fs) else None
        for outcome in ['y','reached']:
            b,V,info=multi_iv(fields[outcome],d,z,meat);tables['system'].append(dict(meta,outcome=outcome,**info,minimum_conditional_F=minimum,
                coefficient_terms=ACT_TERMS,coefficients=b.tolist(),covariance_matrix=V.tolist(),**{k:v for k,v in extras.items() if k not in ('raw_received','ystats')}))
            n=extras['band_counts'];w=np.zeros(6);w[:2]=-np.array(n[:2])/sum(n[:2]);w[3]=1
            tests={**{name:np.eye(6)[j] for j,name in enumerate(ACT_TERMS)},'well_ahead_minus_near_equal':w,
                'premium_IQR':np.eye(6)[4]*extras['giver_cost_iqr']/5}
            supported=[x['grants']>=20 and min(x['grant_recipients'],x['claim_recipients'])>=30 for x in extras['band_support']]
            for term,w in tests.items():
                fit=clean_inference(float(w@b),float(w@V@w),100)
                required=[int(term[-1])] if term.startswith('received_band_') else ([0,1,3] if term=='well_ahead_minus_near_equal' else list(range(4)))
                if not all(supported[j] for j in required):fit.update(supported=False,reason='FROZEN_BAND_RECEIPT_SUPPORT_RULE_FAILED')
                tables['act_contrasts'].append(dict(meta,outcome=outcome,term=term,units='pp per 5 rating points' if term.endswith('_5') else 'percentage points',
                    minimum_conditional_F=minimum,premium_IQR=extras['giver_cost_iqr'],**fit))
        return tables
    z=np.column_stack([fields['z_'+k] for k in job.get('instruments',['A'])]);d=fields['received'];y=fields['y']
    native=math.sqrt(float(z[:,0]@z[:,0])/len(d));meta['native_residual_score_SD']=native
    if kind=='two_score':
        fs=first_stage_system(d,z,meat)
        tables['first_stages']=[dict(meta,**x) for x in fs]
        for k,key in enumerate(job['instruments']):
            others=z[:,[j for j in range(z.shape[1]) if j!=k]]
            zz=z[:,k]-others@np.linalg.solve(others.T@others,others.T@z[:,k])
            dd=d-others@np.linalg.solve(others.T@others,others.T@d)
            tables['first_stages'].append(dict(meta,instrument=key,conditional_on_other_instrument=True,
                **scalar(dd,zz,meat,100*COMMON_SD)))
        b,V,info=multi_iv(y,d,z,meat);tables['system'].append(dict(meta,**info))
        tables['estimates'].append(dict(meta,estimator='2SLS',outcome='y',units='percentage points per receipt',**clean_inference(b[0],V[0,0],100)))
        for outcome in ['y','reached']:
            rb,rv,_,_=m7.multi(fields[outcome],z,meat)
            for k,key in enumerate(job['instruments']):
                tables['estimates'].append(dict(meta,estimator='reduced_form',outcome=outcome,instrument=key,
                    units='pp per common Score A SD, conditional on the other score',**clean_inference(rb[k],rv[k,k],100*COMMON_SD)))
        return tables
    zz=z[:,0]
    if job.get('subgroup'):
        raw=extras['raw_score'];raw=raw-raw.mean();dd=extras['raw_received']-extras['raw_received'].mean()
        tables['estimates'].append(dict(meta,estimator='raw_first_stage',outcome='received',units='pp per common Score A SD',**scalar(dd,raw,meat,100*COMMON_SD)))
    for key in (['received'] if job.get('subgroup') else ['received','y','reached']):
        tables['estimates'].append(dict(meta,outcome=key,estimator='first_stage' if key=='received' else 'reduced_form',
            units='pp per common Score A SD',**extras['ystats'][key],**scalar(fields[key],zz,meat,100*COMMON_SD)))
    if not job.get('subgroup'):
        b,V,info=multi_iv(y,d,zz,meat)
        first=next(x for x in tables['estimates'] if x.get('estimator')=='first_stage')
        tables['estimates'].append(dict(meta,estimator='2SLS',outcome='y',units='percentage points per receipt',
            first_stage_F=first.get('wald_F'),partial_first_stage_R2=first.get('partial_R2'),**clean_inference(b[0],V[0,0],100)))
        if job.get('ols'):tables['estimates'].append(dict(meta,estimator='OLS',outcome='y',units='percentage points per receipt',**scalar(y,d,meat,100)))
    if job.get('balance'):
        tested=[]
        for trait in r.T15:
            if trait in meta['controls']:fit=dict(supported=False,reason='CONTROLLED_TRAIT_NOT_INDEPENDENT_BALANCE_EVIDENCE',p_value=1.)
            elif np.std(fields[trait])<1e-10:fit=dict(supported=False,reason='NO_RESIDUAL_TRAIT_VARIATION',p_value=1.)
            else:
                fit=r.stats.stats.ols(fields[trait],zz/native,meat);tested.append(trait)
            tables['balance'].append(dict(meta,trait=trait,units='trait SD per native residual-score SD',**fit))
        r.stats.stats.holm(tables['balance'],out='p_Holm_15_traits')
        for label,keys in [('all_available',tested),('recent_T30',[k for k in r.T30 if k in tested])]:
            fit=r.stats.stats.joint(np.column_stack([fields[k] for k in keys]),zz/native,meat) if keys else dict(supported=False,reason='NO_UNCONTROLLED_TRAITS')
            tables['joint_balance'].append(dict(meta,test_set=label,traits=keys,**fit))
    if kind=='compliers':
        den=float(zz@d);w=zz*extras['raw_received'];negative=float(-w[w<0].sum()/w.sum())
        for key in COMPLIER_TRAITS:
            prod=fields['product_'+key];b=float(zz@prod)/den;influence=zz*(prod-b*d)/den
            tables['compliers'].append(dict(meta,trait=key,units='natural trait units',negative_weight_absolute_mass_over_signed_total=negative,
                treatment_margin='sum residualized_score*D*trait / sum residualized_score*D; negative weights retained',
                **extras['descriptive'][key],**clean_inference(b,float(meat(influence)[0,0]))))
    return tables

def fit_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        u.log('R9b '+job['name']+' '+job['level']+': projected FWL and CR0')
        result=estimate(job);r.io.js(tmp/'result.json',result)
        return dict(model=job['name'],level=job['level'],tables={k:len(v) for k,v in result.items()})
    return r.stable_stage(Path(job['output']),job['conf'],build,[job['input'],job['scores']]+([job['act']] if job.get('act') else []))[1]
