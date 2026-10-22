"""Secondary fully interacted IV, authenticated headline controls and CR0 rule.

Conditional first stages use the adjusted residual u_j - U_-j delta, rather
than the erroneous unadjusted residual from the fitted-regressor regression.
Exactly identified systems only. Normal intervals are not weak-IV robust.
"""
from common import *
from numerics import codes,absorb,contrast
from analysis import infer_weights,sample_info,BANDS

REFERENCE_SD=0.059411690344000595
def date_covariance(c,actors,dates,influence):
    h=np.asarray(influence,float)
    if h.ndim==1:h=h[:,None]
    n,k=h.shape;ids=np.sort(np.asarray(actors,np.int64),axis=1)
    if ids.shape!=(n,2) or np.any(ids[:,0]==ids[:,1]):raise ValueError('Distinct exposure accounts required')
    table=dict(a=ids[:,0],b=ids[:,1],day=dates);table.update({f'u{j}':h[:,j] for j in range(k)})
    c.register('iv_scores',pa.table(table));values=','.join(f'u{j}' for j in range(k))
    sums=','.join(f'sum(u{j}) s{j}' for j in range(k));products=','.join(f'coalesce(sum(s{i}*s{j}),0)' for i in range(k) for j in range(i,k))
    queries=[(1,'id',f'SELECT a id,{values} FROM iv_scores UNION ALL SELECT b id,{values} FROM iv_scores'),
       (-1,'a,b',f'SELECT a,b,{values} FROM iv_scores'),
       (1,'day',f'SELECT day,{values} FROM iv_scores'),
       (-1,'id,day',f'SELECT a id,day,{values} FROM iv_scores UNION ALL SELECT b id,day,{values} FROM iv_scores'),
       (1,'a,b,day',f'SELECT a,b,day,{values} FROM iv_scores')]
    ans=np.zeros((k,k))
    try:
        for sign,group,query in queries:
            row=c.execute(f'SELECT {products} FROM (SELECT {group},{sums} FROM ({query}) GROUP BY {group})').fetchone();p=0
            for i in range(k):
                for j in range(i,k):ans[i,j]+=sign*row[p];ans[j,i]=ans[i,j];p+=1
    finally:c.unregister('iv_scores')
    return ans

def augment(c,binding,project,work,d):
    parent=read(Path(binding['parent_root'])/'binding_PRIVATE.json')
    path=relocate(project,parent['receipt'])
    if not path.is_file():raise RuntimeError('AUTHENTICATED_RECEIPT_INPUT_NOT_AVAILABLE_FOR_IV')
    authenticate(path,work,parent['receipt_sha256'])
    need=['row_id','game_id','recipient_id','opponent_id','received','y','reached','adjusted_7d','expected_7d','counterparts_7d']
    require_columns(path,need)
    c.execute('CREATE OR REPLACE VIEW original_iv AS SELECT * FROM '+scan(path))
    n=c.execute('SELECT count(*),count(DISTINCT row_id) FROM original_iv').fetchone()
    if n!=(len(d['y']),len(d['y'])):raise RuntimeError('Original-IV source has a different row set')
    checks=['game_id','recipient_id','opponent_id','received','y','reached','adjusted_7d','expected_7d']
    bad=c.execute('SELECT count(*) FROM raw r FULL OUTER JOIN original_iv o USING(row_id) WHERE r.row_id IS NULL OR o.row_id IS NULL OR '+
      ' OR '.join('r.'+s+' IS DISTINCT FROM o.'+s for s in checks)).fetchone()[0]
    if bad:raise RuntimeError('Original-IV source identity/treatment/outcome/score mismatch')
    add=arrays(c.execute('SELECT r.row_id,r.n_7d,o.counterparts_7d,r.tc_base_s,r.tc_inc_s,r.archive_start_ms FROM raw r JOIN original_iv o USING(row_id) ORDER BY r.row_id').to_arrow_table())
    if not np.array_equal(d['row_id'],add.pop('row_id')):raise RuntimeError('IV augmentation reordered rows')
    return dict(d,**add),dict(source_sha256=parent['receipt_sha256'],rows_added=0,rows_removed=0,field='counterparts_7d')

def iv_design(d):
    a=np.asarray(d['received'],float);band=d['band'];g=(d['giver_cost']-d['giver_cost'].mean())/5;b=(d['recipient_benefit']-d['recipient_benefit'].mean())/5
    modifiers=np.column_stack([(band==k).astype(float) for k in range(4)]+[g,b]);endo=modifiers*a[:,None]
    z=modifiers*(d['adjusted_7d']/REFERENCE_SD)[:,None];gap=(d['opponent_rating']-d['recipient_rating'])/100
    x=dict(recipient_rating=d['recipient_rating']/100,rating_gap=gap,rating_gap_square=gap**2,abs_rating_gap=np.abs(gap),
      log_opponent_prior_decisions=np.log1p(d['n_7d']),log_opponent_prior_counterparts=np.log1p(d['counterparts_7d']),
      opponent_history_expected_rate=d['expected_7d'],fair_history_present_90=d['fair_history_present'],log_fair_90=d['log_fair90'],
      kind_ever_90=(d['prior_kind_rate']>0).astype(float),kind_rate_90=d['prior_kind_rate'],log_disconnect_90=d['log_disconnect90'],
      log_receipt_90=d['log_receipt90'],log_volume_30=d['log_pre_games'],log_claim_90=d['log_claim90'],
      giver_cost_5=g,recipient_benefit_5=b,log_giver_rd=np.log(d['giver_rd']),log_recipient_rd=np.log(d['recipient_rd']),
      board_cp_capped600=np.clip(d['board_cp'],-600,600)/100,log_ply=np.log1p(d['ply']),
      log_giver_clock=np.log1p(np.maximum(0,d['giver_clock'])),log_recipient_clock=np.log1p(np.maximum(0,d['recipient_clock'])),
      giver_white=(d['chooser_color']=='white').astype(float))
    for k in (1,2,3):x[f'band_{k}']=(band==k).astype(float)
    cell=np.unique(np.column_stack([d['month_code'],d['tc_base_s'],d['tc_inc_s'],np.floor((d['recipient_rating']+d['opponent_rating'])/200)]),axis=0,return_inverse=True)[1]
    date=d['archive_start_ms']//DAY;hour=(d['archive_start_ms']//3_600_000)%168
    names=[f'received_band_{k}' for k in range(4)]+['received_x_giver_cost_5','received_x_recipient_benefit_5']
    return np.column_stack(list(x.values())),list(x),endo,z,names,[cell,codes(date),codes(hour)],date

def conditional_scores(d,z):
    """Just-identified SW conditional scalar directions, residualized controls."""
    n,p=d.shape
    if z.shape!=(n,p):raise ValueError('Exactly identified system required')
    gram=z.T@z;pi=np.linalg.solve(gram,z.T@d);hat=z@pi;u=d-hat;slopes=[];influences=[]
    for j in range(p):
        others=[k for k in range(p) if k!=j]
        if others:
            h=hat[:,others];delta=np.linalg.solve(h.T@h,h.T@d[:,j])
            _,_,vh=np.linalg.svd(h.T@z,full_matrices=True);v=vh[-1]
            err=u[:,j]-u[:,others]@delta
        else:v=np.ones(1);err=u[:,j]
        zz=z@v;zz/=np.sqrt(np.mean(zz*zz));den=float(zz@zz)
        slopes.append(float(zz@d[:,j])/den);influences.append(zz*err/den)
    return np.array(slopes),np.column_stack(influences),pi

def fit_iv(c,x,endo,z,y,groups,actors,dates,names):
    matrix=np.column_stack([x,endo,z,y])
    if not np.isfinite(matrix).all():raise RuntimeError('Missing IV controls; no row deletion or imputation')
    a,it,_=absorb(matrix,groups,compute_rank=False);del matrix
    k=x.shape[1];p=endo.shape[1];xr=a[:,:k];v=a[:,k:];rms=np.sqrt(np.mean(xr*xr,axis=0));use=rms>1e-12
    xr=np.ascontiguousarray(xr[:,use]);xr/=rms[use];gram=xr.T@xr
    cond=float(np.linalg.cond(gram));info=dict(absorb_iterations=it,controls=[s for s,u in zip(names,use) if u],
      dropped_constant_controls=[s for s,u in zip(names,use) if not u],control_gram_condition=cond,
      covariance='shared_exposure_account_OR_exposure_date_CR0',reference_score_sd=REFERENCE_SD,
      fixed_effects=['month_exact_time_control_mean_rating_100bin','exposure_UTC_date','UTC_hour_mod_168'],
      conditional_exclusion_certified=False,weak_IV_robust_intervals=False)
    if not np.isfinite(cond) or cond>1e10:return dict(info,status='IV_CONTROL_COLLINEARITY'),None
    v=v-xr@np.linalg.solve(gram,xr.T@v);d=v[:,:p].copy();z=v[:,p:2*p].copy();y=v[:,2*p:]
    ds=np.sqrt(np.mean(d*d,axis=0));zs=np.sqrt(np.mean(z*z,axis=0))
    if min(ds.min(),zs.min())<1e-10:return dict(info,status='IV_NO_RESIDUAL_VARIATION'),None
    d/=ds;z/=zs;q=z.T@z;cross=z.T@d
    if np.linalg.cond(q)>1e10:return dict(info,status='IV_INSTRUMENT_COLLINEARITY'),None
    cross_condition=float(np.linalg.cond(cross));rf=np.linalg.solve(q,z.T@y);rfderiv=z@np.linalg.inv(q)
    beta=None;derivative=None
    if cross_condition<=1e8:
        inverse=np.linalg.inv(cross);beta=inverse@(z.T@y);derivative=z@inverse.T
    fs=[];pi=np.linalg.solve(q,cross)
    try:
        slopes,influence,pi=conditional_scores(d,z);cv=date_covariance(c,actors,dates,influence)
        for j in range(p):
            variance=float(cv[j,j]);fs.append(dict(endogenous_column=j,conditional_F=float(slopes[j]**2/variance) if variance>0 else None,
              conditional_rank_df=1,conditional_residual_adjusted=True,variance_negative=variance<0))
    except np.linalg.LinAlgError:
        fs=[dict(endogenous_column=j,conditional_F=None,reason='CONDITIONAL_PREDICTED_REGRESSORS_RANK_DEFICIENT') for j in range(p)]
    ivcov=[];rfcov=[]
    for o in range(y.shape[1]):
        if beta is not None:ivcov.append(date_covariance(c,actors,dates,derivative*(y[:,o]-d@beta[:,o])[:,None])/np.outer(ds,ds))
        rfcov.append(date_covariance(c,actors,dates,rfderiv*(y[:,o]-z@rf[:,o])[:,None])/np.outer(zs,zs))
    info.update(status='ESTIMATED' if beta is not None else 'REDUCED_FORM_ONLY_RANK_DEFICIENCY',instrument_gram_condition=float(np.linalg.cond(q)),cross_moment_condition=cross_condition,
      conditional_first_stages=fs,minimum_conditional_F=min((r['conditional_F'] or 0) for r in fs),
      first_stage_coefficient_matrix=(pi*ds[None,:]/zs[:,None]).tolist(),
      first_stage_matrix_orientation='rows = excluded instruments; columns = endogenous regressors')
    return info,dict(coefficients=beta/ds[:,None] if beta is not None else None,covariances=ivcov,reduced_form=rf/zs[:,None],reduced_covariances=rfcov)

def run_iv(c,d,binding,project,work,folder,key):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    if checkpoint_ok(folder,key):log('Reusing secondary IV');return
    with heartbeat('Secondary interacted IV'):
        try:d,source=augment(c,binding,project,work,d)
        except (RuntimeError,FileNotFoundError,KeyError) as e:
            write(folder/'summary.json',dict(status='WITHHELD',reason=str(e),original_IV_modified=False));csvwrite(folder/'estimates.csv',[dict(status='WITHHELD',reason=str(e))]);finish(folder,key);return
        x,names,endo,z,targets,groups,dates=iv_design(d)
        try:
            info,fit=fit_iv(c,x,endo,z,np.column_stack([d['y'],d['reached']]),groups,
              np.column_stack([d['recipient_id'],d['opponent_id']]),dates,names)
        except (np.linalg.LinAlgError,RuntimeError) as e:
            write(folder/'summary.json',dict(status='WITHHELD_NUMERICS',reason=str(e),original_IV_modified=False));csvwrite(folder/'estimates.csv',[dict(status='WITHHELD_NUMERICS',reason=str(e))]);finish(folder,key);return
        sample=sample_info(d,'all_rd');meta=dict(giver_cost_iqr=float(np.diff(np.quantile(d['giver_cost'],[.25,.75]))[0]))
        out=[];rf=[];cov=[]
        if fit is not None:
            if fit['coefficients'] is None:out=[dict(status=info['status'],model='secondary_iv',reason='2SLS cross-moment system rank/condition failed; reduced forms retained')]
            for o,outcome in enumerate(('y','reached')):
                for term in targets+['equal','ahead_minus_equal','giver_cost_iqr'] if fit['coefficients'] is not None else []:
                    w,ok=infer_weights(targets,term,sample,meta)
                    out.append(dict(model='secondary_iv',outcome=outcome,term=term,**contrast(fit['coefficients'][:,o],fit['covariances'][o],w,ok),
                      sample_sha256=sample['sample_sha256'],minimum_conditional_F=info['minimum_conditional_F'],
                      weak_IV_robust=False,conditional_exclusion_certified=False,
                      units='percentage points per 5 rating points' if '_5' in term else 'percentage points'))
                for j,t in enumerate(targets):
                    w=np.eye(len(targets))[j];rf.append(dict(outcome=outcome,instrument=t.replace('received','Z'),
                      **contrast(fit['reduced_form'][:,o],fit['reduced_covariances'][o],w),units='pp per fixed reference SD, or its modifier product'))
                if fit['coefficients'] is not None:
                    for i,a in enumerate(targets):
                        for j,b in enumerate(targets):cov.append(dict(outcome=outcome,term_i=a,term_j=b,covariance_pp_squared=10000*fit['covariances'][o][i,j]))
            for j,r in enumerate(info['conditional_first_stages']):r['term']=targets[j]
        else:out=[dict(status=info['status'],model='secondary_iv')]
        write(folder/'summary.json',dict(status=info['status'],fit=info,sample=sample,source=source,
          original_IV_modified=False,targets=targets,description='New secondary IV, rich authenticated headline controls plus predecision position/stake controls'))
        csvwrite(folder/'estimates.csv',out);csvwrite(folder/'reduced_forms.csv',rf);csvwrite(folder/'covariance.csv',cov)
        csvwrite(folder/'first_stages.csv',info.get('conditional_first_stages',[]));finish(folder,key)
