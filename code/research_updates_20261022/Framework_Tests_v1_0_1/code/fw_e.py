"""Full observed prior history, frozen matched receipt design and joint receipt IV."""
from fw_common import *
DAY=86400000
LABELS=['PG','PC','NC']

def history_group(grant_ms,choice_ms,anchor):
    # PG takes priority: a prior grant in any state establishes observed granting.
    return np.where(np.asarray(grant_ms)<anchor,0,np.where(np.asarray(choice_ms)<anchor,1,2)).astype(np.int8)

def prior_history(a,run,key):
    work=run/'E/history';hk=digest([key,'full_history_earliest'])
    if completed(work,hk):return work/'earliest.parquet'
    work.mkdir(parents=True,exist_ok=True);records,manifest=u.full_source_panels(a.project_root)
    paths=[r['path'] for r in records];c=conn(work/'spill',max(1,a.memory_gb-2),min(a.workers,3))
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+parq(paths)+' WHERE '+u.author_predicate())
        require(c.execute('''SELECT count(*) FROM p WHERE chooser_user_id IS NULL OR disconnected_user_id IS NULL
          OR api_last_move_at_ms IS NULL OR api_last_move_at_ms<=0 OR engine_eval_cp_disconnected IS NULL''').fetchone()[0]==0,'Prior-history identity/time/evaluation missing')
        c.execute(f'''COPY (SELECT chooser_user_id::BIGINT chooser,
          min(api_last_move_at_ms) FILTER(WHERE kind_draw) first_grant,
          min(api_last_move_at_ms) FILTER(WHERE engine_eval_cp_disconnected>=-100 AND (kind_draw OR timeout_chooser_win)) first_choice
          FROM p GROUP BY chooser_user_id) TO {qs(work/'earliest.parquet')} (FORMAT PARQUET,COMPRESSION ZSTD)''')
    finally:c.close()
    save(work/'SOURCE_PRIVATE.json',records);certify(work,hk,paths+[manifest]);return work/'earliest.parquet'

def lookup_history(ids,anchor,history):
    h=frame(history).set_index('chooser');v=h.reindex(ids)
    return history_group(v.first_grant.to_numpy(float),v.first_choice.to_numpy(float),np.asarray(anchor))

def support_clean(d,keep):
    t=np.asarray(d['received_mercy'],bool);cell=np.asarray(d['exposure_cell_code'],int)
    valid=keep&np.asarray(d['first_ever_pair'],bool)&np.asarray(d['arm_eligible'],bool)&(cell>=0)
    nt=np.bincount(cell[valid&t],minlength=1152);nc=np.bincount(cell[valid&~t],minlength=1152)
    allowed=(nt>=5)&(nc>=20);eligible=valid&allowed[np.maximum(cell,0)]
    w=np.zeros(len(t));w[eligible&t]=1;z=eligible&~t;w[z]=nt[cell[z]]/nc[cell[z]]
    return dict(eligible=eligible,weights=w)

def clustered_meat(scores,cluster):
    _,code=np.unique(cluster,return_inverse=True);G=int(code.max())+1
    S=np.column_stack([np.bincount(code,weights=scores[:,j],minlength=G) for j in range(scores.shape[1])])
    return S.T@S,G

def receipt_fit(y,treat,group,controls,w,fe,cluster,solver_root,key):
    sf=module('framework_sparse_fe',ROOT/'vendor_kac/sparse_fe.py');sf.configure(solver_root,key)
    G=np.eye(3)[group];X=np.column_stack([treat[:,None]*G,G[:,:2],controls])
    with heartbeat('E weighted fixed effects'):
        v,it,err=sf.weighted_absorb(np.column_stack([100*y,X]),w,fe)
    Y=v[:,0];X=v[:,1:];fit=solve((X*w[:,None]).T@X,X.T@(w*Y));e=Y-X@fit['beta']
    M,ng=clustered_meat(X*(w*e)[:,None],cluster);require(ng>1,'Receipt needs multiple exposure opponents')
    V=fit['inverse']@M@fit['inverse']*ng/(ng-1)*(len(y)-1)/(len(y)-fit['rank'])
    rows=[]
    for g,label in enumerate(LABELS):
        q=np.eye(X.shape[1])[g];z=group==g
        rows.append(dict(group=label,rows=int(z.sum()),receipts=int(np.sum(treat[z])),
          **(infer(q@fit['beta'],q@V@q) if estimable(fit,q) else dict(status='NOT_ESTIMABLE'))))
    q=np.eye(X.shape[1])[0]-np.eye(X.shape[1])[2]
    rows.append(dict(group='PG_minus_NC',**(infer(q@fit['beta'],q@V@q) if estimable(fit,q) else dict(status='NOT_ESTIMABLE'))))
    return rows,dict(rows=len(y),clusters=ng,rank=fit['rank'],absorption_iterations=it,absorption_residual=err,
        covariance='Exposure-opponent cluster CR1, original N/rank and G correction',units='percentage points per receipt')

def future_clean(a,run,paths,source,key):
    work=run/'E/future';fk=digest([key,'future_clean']);target=work/'next.parquet'
    if completed(work,fk):return target
    work.mkdir(parents=True,exist_ok=True);c=conn(work/'spill',max(1,a.memory_gb-2),min(a.workers,3))
    try:
        c.execute('CREATE VIEW e AS SELECT cohort_row_id,recipient_user_id,exposure_anchor_utc_ms FROM '+parq([source]))
        # Original anchor, tie ordering, main-sample outcomes; authors removed first.
        q=f'''SELECT e.cohort_row_id,p.y,p.event_ms-e.exposure_anchor_utc_ms delta_ms
          FROM e JOIN {parq(paths)} p ON p.chooser=e.recipient_user_id AND p.board>=-100
          AND p.event_ms>e.exposure_anchor_utc_ms AND p.event_ms<=e.exposure_anchor_utc_ms+{90*DAY}
          QUALIFY row_number() OVER(PARTITION BY cohort_row_id ORDER BY p.event_ms,p.archive_ordinal,p.game_id)=1'''
        c.execute(f'COPY ({q}) TO {qs(target)} (FORMAT PARQUET,COMPRESSION ZSTD)')
    finally:c.close()
    certify(work,fk,list(paths)+[source]);return target

def interval_rows(group,treat,y,delta,w,eligible,cluster):
    rows=[]
    for label,lo,hi in [('up_to_6_hours',0,DAY/4),('30_to_90_days',30*DAY,90*DAY)]:
      for g,name in enumerate(LABELS):
        use=eligible&(group==g)&np.isfinite(delta)&(delta>lo)&(delta<=hi);ix=np.flatnonzero(use)
        z=treat[ix];yy=100*y[ix];ww=w[ix];arm=[]
        for t in (0,1):
            m=z==t;den=ww[m].sum();arm.append(float(ww[m]@yy[m]/den) if den else np.nan)
        r=dict(interval=label,group=name,rows=len(ix),receipts=int(z.sum()),claim_mean_pp=arm[0],receipt_mean_pp=arm[1],descriptive=True)
        if len(ix)>1 and np.isfinite(arm).all():
            inf=np.where(z==1,ww*(yy-arm[1])/ww[z==1].sum(),-ww*(yy-arm[0])/ww[z==0].sum())
            M,ng=clustered_meat(inf[:,None],cluster[ix]);r.update(infer(arm[1]-arm[0],M[0,0]*ng/(ng-1)) if ng>1 else dict(status='INSUFFICIENT_CLUSTERS'))
        else:r['status']='INSUFFICIENT_SUPPORT'
        rows.append(r)
    return rows

def run_receipt(a,run,paths,history,key):
    work=run/'E/matched';report=run/'E/report';report.mkdir(parents=True,exist_ok=True);ek=digest([key,'E_matched'])
    if completed(work/'final',ek):return load(work/'final/status.json')
    source=a.project_root/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1/project_view/derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet'
    reference=load(ROOT/'vendor_kac/authority/core_summary.json')
    require(sha(source)==reference['recipient_private_input_sha256'],'Matched receipt source hash differs from reviewed current pool design')
    core=module('framework_receipt_core',ROOT/'vendor_kac/vendor/core/receipt_core.py')
    d=core.load_recipient_arrays(source);old=core.common_support_weights(d)
    require(old['eligible'].sum()==2294012,'Original receipt support differs')
    extra=frame(source,['cohort_row_id','disconnected_username_norm','exposure_chooser_username_norm','exposure_anchor_utc_ms'])
    require(np.array_equal(extra.cohort_row_id,d['cohort_row_id']),'Receipt row order differs')
    keep=~extra.disconnected_username_norm.str.lower().str.strip().isin(AUTHORS)&~extra.exposure_chooser_username_norm.str.lower().str.strip().isin(AUTHORS)
    require(extra[['disconnected_username_norm','exposure_chooser_username_norm']].notna().all().all(),'Receipt author bridge missing')
    support=support_clean(d,keep.to_numpy());complete=np.asarray(d['a1_90d_followup_eligible'],bool)&support['eligible']
    require(int((np.asarray(d['a1_90d_followup_eligible'],bool)&old['eligible']).sum())==2110400,'Original receipt followup differs')
    group=lookup_history(d['recipient_user_id'],extra.exposure_anchor_utc_ms.to_numpy(),history)
    nextfile=future_clean(a,run,paths,source,key);f=frame(nextfile).set_index('cohort_row_id').reindex(d['cohort_row_id'])
    reached=f.y.notna().to_numpy();y=f.y.fillna(0).to_numpy(float);delta=f.delta_ms.to_numpy(float)
    table(report,'tabE0_matched_group_coverage',[dict(group=name,complete_exposures=int((complete&(group==g)).sum()),
        conditional_choices=int((complete&reached&(group==g)).sum()),prior_history='Observed all-source active decisions from 2023-11-01, strictly before exposure anchor') for g,name in enumerate(LABELS)])
    rows=[];infos=[]
    for outcome,mask in [('conditional_next_competitive',complete&reached),('zero_coded_90d',complete)]:
        out=work/outcome;mk=digest([ek,outcome])
        if completed(out,mk):rr=load(out/'rows.json');info=load(out/'info.json')
        else:
            ix=np.flatnonzero(mask);X,names=core.model_controls(d,ix,state_conditioned=False)
            rr,info=receipt_fit(y[ix],d['received_mercy'][ix].astype(float),group[ix],X,support['weights'][ix],
                [d['exposure_cell_code'][ix],d['exposure_month_code'][ix]],d['exposure_chooser_user_id'][ix],out/'solver',mk)
            info['controls']=names;save(out/'rows.json',rr);save(out/'info.json',info);certify(out,mk,[source,history,nextfile])
        rows += [dict(outcome=outcome,**r) for r in rr];infos.append(dict(outcome=outcome,**info))
    table(report,'tabE1_matched_receipt_by_history',rows)
    table(report,'tabE3_interval_profile',interval_rows(group,d['received_mercy'].astype(int),y,delta,support['weights'],complete,d['exposure_chooser_user_id']))
    status=dict(status='ESTIMATED',models=infos,author_exposures_removed=int((~keep).sum()),
        future_choices_changed=int(np.sum(reached!=np.asarray(d['reached_fair_chooser_within_90d'],bool))),
        support='Original cells, >=5 treated and >=20 controls, weights recomputed before outcomes after excluding both author accounts; frozen original exposure cohort, no replacement exposures.',
        history='All observed prior active choices, no 90-day restriction; panel-left-censored, not lifetime.',
        interpretation='Joint PG/PC/NC receipt interactions plus group main effects. PG has priority over PC/NC. Conditional outcomes select on reaching a future opportunity.')
    save(work/'final/status.json',status);certify(work/'final',ek,[source,history,nextfile],outputs=list(report.glob('tabE[013]*')));return status

def iv_system(y,D,Z,meat):
    zz=Z.T@Z;require(np.linalg.matrix_rank(zz)==Z.shape[1],'Excluded instruments lack rank')
    W=np.linalg.inv(zz);B=D.T@Z@W;A=B@Z.T@D;fit=solve(A,B@(Z.T@y))
    require(fit['rank']==D.shape[1],'Joint IV is unidentified')
    beta=fit['beta'];e=y-D@beta;bread=fit['inverse']@B;V=bread@meat(Z*e[:,None])@bread.T
    return beta,V

def run_iv(a,run,history,key):
    work=run/'E/iv';report=run/'E/report';ik=digest([key,'E_IV'])
    if completed(work/'final',ik):return load(work/'final/status.json')
    root,paths,binding=u.bind_r7(a.project_root)
    import r7_common as r
    import r7_math as rm
    d=r.load_fit_columns(paths['S0'],extra=['anchor_ms']);require('anchor_ms' in d,'IV anchor timestamp unavailable')
    # S0's producer certifies complete follow-up from timestamps; complete90 is
    # an F50 field and is deliberately absent from the frozen S0 schema.
    validate_iv_followup(d,r.env_common.core.PANEL_END)
    for role in ['recipient_id','opponent_id']:require(~np.isin(d[role],binding['author_ids']).any(),'Author appears in frozen IV cohort')
    group=lookup_history(d['recipient_id'],d['anchor_ms'],history);G=np.eye(3)[group]
    x,names,traits,fe=r.feature_design(d,'X0');del traits
    controls=np.column_stack([x,G[:,:2]]);D=d['received'][:,None]*G;Z=d['adjusted_7d'][:,None]*G
    with heartbeat('E joint group IV projection'):
        targets=np.column_stack([100*d['y'],D,Z])
        projected,_=rm.project([controls[:,j] for j in range(controls.shape[1])],
            [targets[:,j] for j in range(targets.shape[1])],fe)
    y=projected[:,0];D=projected[:,1:4];Z=projected[:,4:7]
    shared=rm.covariance(d)
    def opponent_meat(s):
        M,ng=clustered_meat(s,d['opponent_id']);return M*ng/(ng-1)
    rows=[];first=[]
    for cov,meat in [('shared_account_OR_date_CR0',shared),('exposure_opponent_CR1',opponent_meat)]:
        beta,V=iv_system(y,D,Z,meat)
        for g,label in enumerate(LABELS):
            rows.append(dict(covariance=cov,group=label,rows=int((group==g).sum()),**infer(beta[g],V[g,g])))
        q=np.array([1.,0,-1.]);rows.append(dict(covariance=cov,group='PG_minus_NC',**infer(q@beta,q@V@q)))
        inv=np.linalg.inv(Z.T@Z)
        for g,label in enumerate(LABELS):
            b=inv@(Z.T@D[:,g]);err=D[:,g]-Z@b;vv=inv@meat(Z*err[:,None])@inv
            first.append(dict(covariance=cov,receipt_group=label,test='joint_three_excluded_instruments',**rm.wald(b,vv)))
            for j,name in enumerate(LABELS):
                scale=100*r.SD['pooled'];first.append(dict(covariance=cov,receipt_group=label,score_group=name,
                    term='first_stage_pp_per_frozen_score_SD',**infer(b[j]*scale,vv[j,j]*scale**2)))
    # Separate within-group first stages aid weak-instrument assessment; not substituted for joint 2SLS.
    for g,label in enumerate(LABELS):
        sub=r.subset(d,group==g)
        if len(sub['row_id'])<30:continue
        xx,_,_,gg=r.feature_design(sub,'X0');v,_=rm.project(xx,[sub['received'],sub['adjusted_7d']],gg)
        fit,_=rm.scalar(v[:,0],v[:,1],rm.covariance(sub),100*r.SD['pooled'])
        fit['wald_F_one_df']=(fit['coefficient']/fit['standard_error'])**2 if fit.get('supported') and fit.get('standard_error',0)>0 else None
        first.append(dict(receipt_group=label,term='within_group_first_stage',**fit))
    table(report,'tabE2_joint_IV_by_history',rows);table(report,'tabE2_first_stages',first)
    status=dict(status='ESTIMATED',cohort='Authenticated author-clean R7 S0, original Table 4 frozen score/X0 controls and FE',
      score='Pooled adjusted_7d, scores treated as fixed',controls=names,units='percentage points per receipt',
      inference='Wald intervals; inspect within-group first stages. Weak subgroup instruments can make Wald inference unreliable; no automatic gate-versus-shift conclusion.',
      history='PG: prior grant any state; PC: prior competitive active choice and no prior grant; NC: neither, within observed history.',
      causal_identification_certified=False)
    save(work/'final/status.json',status);certify(work/'final',ik,[paths['S0'],history],outputs=list(report.glob('tabE2*')));return status

def validate_iv_followup(d,panel_end):
    anchor=np.asarray(d['anchor_ms']);start=np.asarray(d['archive_start_ms'])
    require(np.isfinite(anchor).all() and np.all(anchor>=start),'Invalid frozen IV anchor')
    complete=anchor+90*DAY<panel_end
    require(complete.all(),'IV main cohort is not complete at 90 days')
    if 'complete90' in d:require(np.array_equal(np.asarray(d['complete90'],bool),complete),'Stored IV follow-up flag disagrees with timestamps')
    for name in ('received','y','reached'):
        require(np.isin(d[name],[0,1]).all(),'Nonbinary frozen IV field: '+name)

def run(a,run,paths,key,mode):
    history=prior_history(a,run,key)
    return run_receipt(a,run,paths,history,key) if mode=='matched' else run_iv(a,run,history,key)
