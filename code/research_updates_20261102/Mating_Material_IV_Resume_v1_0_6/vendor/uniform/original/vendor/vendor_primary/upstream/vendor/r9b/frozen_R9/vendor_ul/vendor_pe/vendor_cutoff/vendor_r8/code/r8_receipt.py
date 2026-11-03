"""R8-2 fit information and R8-4 prior-choice splits; fixed R7 inputs/scores."""
from r8_util import *
import sys, gc
sys.path.insert(0,str(ROOT/'vendor_r7/code'))
import r7_common as r
import r7_math as rm

def r_squared(d,sample,archived,report):
    x,names,traits,groups=r.feature_design(d,'X0')
    nh=x[:,:7]
    t=np.column_stack([traits[k] for k in r.T15])
    outcomes=['y','received'] if sample=='S0' else ['y','analysis_entry_90','recipient_disconnect_main']
    y=np.column_stack([np.asarray(d[k],float) for k in outcomes])
    require(np.isfinite(y).all(),'Incomplete follow-up cannot be imputed for R8-2')
    log(f'R8-2 {sample}: fit statistics on {len(y):,} frozen rows')
    with heartbeat('R8-2 '+sample+' trait prediction'):
        a,_=rm.project(nh,[t[:,j] for j in range(15)]+[y[:,j] for j in range(len(outcomes))],groups)
        tt=a[:,:15];yy=a[:,15:]
        G=tt.T@tt
        require(np.linalg.matrix_rank(G)==15,'T15 prediction design rank deficient')
        b=np.linalg.solve(G,tt.T@yy);e=yy-tt@b
        rows=[]
        for j,k in enumerate(outcomes):
            for i,name in enumerate(r.T15):
                want=next(v for v in archived if v.get('sample')==sample and v.get('control_level')=='X0'
                    and v.get('analysis')=='A1' and v.get('dependent')==k and v.get('trait')==name)
                require(np.isclose(b[i,j],want['coefficient'],rtol=3e-6,atol=2e-9),'R7 trait prediction coefficient did not reproduce: '+name)
            rss=float(e[:,j]@e[:,j]);nhss=float(yy[:,j]@yy[:,j]);center=y[:,j]-y[:,j].mean();total=float(center@center)
            rows.append(dict(sample=sample,n=len(y),outcome=k,trait_incremental_partial_R2=1-rss/nhss,
                FE_plus_NH_plus_traits_R2=1-rss/total,trait_count=15,all_trait_coefficients_reproduced=True,
                row_set_sha256=r.design.row_digest(d['row_id']),prediction='in_sample',
                note='Full R2 includes fixed effects and NH; partial R2 measures the additional trait fit. Neither is an out-of-sample calibration statistic.'))
    return rows

def attach_prior(c,p,yn):
    """Views q/src carry the frozen exposures and complete recorded chronology."""
    c.execute(f'''CREATE TABLE earliest AS SELECT chooser_user_id recipient_id,min(api_last_move_at_ms)::BIGINT first_decision_ms
      FROM src WHERE {author_predicate()} AND engine_eval_cp_disconnected>=-100
      AND ({yn} OR timeout_chooser_win) GROUP BY chooser_user_id''')
    c.execute(f'''COPY (SELECT q.*,coalesce(e.first_decision_ms<q.anchor_ms,false) AS faced_recorded,
        coalesce(e.first_decision_ms<q.archive_start_ms,false) AS faced_before_game_start,
        CASE WHEN q.fair_90=0 THEN 0 WHEN q.kind_90=0 THEN 1 ELSE 2 END::TINYINT group90,
        coalesce(q.fair_90>0,false) AS faced90
      FROM q LEFT JOIN earliest e USING(recipient_id) ORDER BY q.row_id)
      TO {qs(p)} (FORMAT PARQUET,COMPRESSION ZSTD)''')

def prior_frame(paths,binding,project,work,key,memory):
    out=work/'prior_experience';p=out/'split.parquet'
    if verify_cached(out,key):return p,load(out/'summary.json')
    sources,manifest=full_source_panels(project)
    sourcepaths=[x['path'] for x in sources]
    cols=set(pq.ParquetFile(sourcepaths[0]).schema_arrow.names)
    needed={'chooser_user_id','disconnected_user_id','api_last_move_at_ms','game_id','engine_eval_cp_disconnected',
            'chooser_username_norm','disconnected_username_norm','timeout_chooser_win'}
    require(needed<=cols,'All-source decision contract missing: '+str(sorted(needed-cols)))
    yn='kind_draw' if 'kind_draw' in cols else 'outcome_kind_draw'
    require(yn in cols,'All-source active grant outcome is unavailable')
    out.mkdir(parents=True,exist_ok=True)
    c=conn(out/'spill',max(2,memory-2),1)
    try:
        c.execute('CREATE VIEW q AS SELECT row_id,game_id,recipient_id,opponent_id,archive_start_ms,anchor_ms,fair_90,kind_90 FROM '+parq([paths['S0']]))
        c.execute('CREATE VIEW src AS SELECT * FROM '+parq(sourcepaths))
        # Bind identities in the focal games rather than assuming numeric namespaces agree.
        matched=c.execute('''SELECT count(*),count(DISTINCT q.row_id),count(*) FILTER(WHERE
          q.recipient_id IS DISTINCT FROM s.disconnected_user_id OR q.opponent_id IS DISTINCT FROM s.chooser_user_id)
          FROM q JOIN src s USING(game_id)''').fetchone()
        require(matched==(2682329,2682329,0),'All-source / S0 role and identity bridge failed')
        invalid=c.execute(f'''SELECT count(*) FROM src WHERE chooser_username_norm IS NULL OR disconnected_username_norm IS NULL
          OR chooser_user_id IS NULL OR disconnected_user_id IS NULL OR api_last_move_at_ms IS NULL OR {yn} IS NULL OR timeout_chooser_win IS NULL
          OR engine_eval_cp_disconnected IS NULL''').fetchone()[0]
        require(invalid==0,'All-source chronology contains missing identity, event time or active-choice semantics')
        with heartbeat('First recorded competitive chooser decision on the all-source chronology'):
            # Exposure choice time is anchor_ms, the same chronology event convention used for repayment.
            attach_prior(c,p,yn)
        flows=c.execute('SELECT faced_recorded,group90,count(*) n FROM '+parq([p])+' GROUP BY ALL ORDER BY ALL').fetchdf()
        secondary=c.execute('SELECT group90,count(*) FROM '+parq([p])+' GROUP BY group90 ORDER BY group90').fetchall()
        require(secondary==[(0,1319101),(1,1291893),(2,71335)],'Frozen 90-day subgroup counts changed')
        discrepancy=c.execute('SELECT count(*) FROM '+parq([p])+' WHERE faced90 AND NOT faced_recorded').fetchone()[0]
        require(discrepancy==0,'Recent-choice history is not nested in all-source prior-choice history')
        summary=dict(rows=2682329,all_source_rows=47587020,all_source_files=24,secondary_counts=dict(secondary),
            primary_time='prior completed active decision strictly before exposure anchor_ms',
            game_start_sensitivity_rows=int(c.execute('SELECT count(*) FROM '+parq([p])+' WHERE faced_recorded!=faced_before_game_start').fetchone()[0]),
            source_window='November 2023–October 2025; all sources and adjacent pairs, not just the main pool/nonadjacent sample',
            left_censoring='Never faced means no prior qualifying choice in this recorded chronology; it does not mean never in the account lifetime.',
            author_policy='Both author accounts excluded from both sides of all prior-choice events; factual time and ordering preserved')
        table(out,'crosswalk_counts',flows);save(out/'summary.json',summary)
    finally:c.close()
    certify(out,key,[paths['S0'],manifest]+sourcepaths,summary)
    return p,summary

def group_iv(d,label):
    xs,names,traits,groups=r.feature_design(d,'X0')
    raw=[d['adjusted_7d'],d['received'],d['y']]
    with heartbeat('R8-4 '+label+' fixed effects'):
        a,_=rm.project(xs,raw,groups)
    z,D,Y=a.T;meat=rm.covariance(d)
    iv=r.stats.iv_result(Y,D,z,meat)
    fs,_=rm.scalar(D,z,meat,100*r.SD['pooled']);rf,_=rm.scalar(Y,z,meat,100*r.SD['pooled'])
    out=dict(group=label,n=len(D),recipients=len(np.unique(d['recipient_id'])),receipts=int(np.sum(d['received'])),
        receipt_rate_pp=100*float(np.mean(d['received'])),row_set_sha256=r.design.row_digest(d['row_id']),
        first_stage_pp=fs.get('coefficient_pp'),first_stage_SE_pp=fs.get('standard_error_pp'),
        reduced_form_pp=rf.get('coefficient_pp'),reduced_form_SE_pp=rf.get('standard_error_pp'),
        first_stage_F=(fs['coefficient']/fs['standard_error'])**2 if fs.get('supported') else None,
        iv_pp=100*iv['iv_coefficient'] if 'iv_coefficient' in iv else None,
        iv_SE_pp=100*iv['iv_standard_error'] if 'iv_standard_error' in iv else None,
        Wald95_pp=[100*iv['iv_ci_low'],100*iv['iv_ci_high']] if 'iv_ci_low' in iv else None,
        AR95_intervals_pp=iv.get('AR95_intervals_pp'),AR95_unbounded=iv.get('AR95_unbounded'),
        AR95_reason=iv.get('AR95_reason'),iv_covariance_supported=iv.get('supported'),
        first_stage_supported=fs.get('supported'),reduced_form_supported=rf.get('supported'),
        controls='Panel A X0 and fixed effects, reestimated within this subgroup',
        inference='shared-account OR exposure-date CR0; generated score fixed; nominal asymptotic intervals')
    require(np.isfinite(float(z@D)) and abs(float(z@D))>1e-14,'Zero first stage in subgroup '+label)
    beta=float(z@Y)/float(z@D);influence=100*z*(Y-beta*D)/float(z@D)
    # Bonferroni: two marginal 97.5% AR sets give a conservative >=95% set for their difference.
    V=meat(np.column_stack([z*Y,z*D]));scale=max(float(abs(V).max()),1e-30)
    ar975=None
    if np.linalg.eigvalsh(V).min()>=-1e-10*scale:
        zy,zd=float(z@Y),float(z@D);q=5.023886187314888
        ar975=[[100*x,100*y] for x,y in r.num.quadratic_set(zd*zd-q*V[1,1],-2*zy*zd+2*q*V[0,1],zy*zy-q*V[0,0])]
    return out,influence,ar975

def split_fits(d,groups,split,folder,key):
    code=np.asarray(groups,bool);result=[];influences=[];ars=[]
    for value,label in [(False,'never_faced'),(True,'faced')]:
        m=code==value;sub=r.subset(d,m)
        checkpoint=folder/(split+'_'+label);onekey=digest([key,split,label])
        if verify_cached(checkpoint,onekey):
            row=load(checkpoint/'result.json');inf=np.load(checkpoint/'influence.npy',allow_pickle=False)
            ar=load(checkpoint/'ar975.json')
            if ar is not None:ar=[[float(x),float(y)] for x,y in ar]
        else:
            checkpoint.mkdir(parents=True,exist_ok=True)
            row,inf,ar=group_iv(sub,label)
            save(checkpoint/'result.json',row);np.save(checkpoint/'influence.npy',inf,allow_pickle=False)
            save(checkpoint/'ar975.json',None if ar is None else [[str(x) if math.isinf(x) else x,str(y) if math.isinf(y) else y] for x,y in ar])
            certify(checkpoint,onekey)
        row.update(split=split);result.append(row)
        full=np.zeros(len(code));full[m]=inf;influences.append(full);ars.append(ar)
        del sub;gc.collect();log(f'R8-4 {split}: {label} complete ({int(m.sum()):,} rows)')
    difference=influences[0]-influences[1];V=float(rm.covariance(d)(difference)[0,0])
    point=result[0]['iv_pp']-result[1]['iv_pp'];se=math.sqrt(V) if V>0 else None
    contrast=dict(split=split,model='separately_fitted_groups',contrast='never_faced minus faced',coefficient_pp=point,
        standard_error_pp=se,Wald95_pp=[point-1.959963984540054*se,point+1.959963984540054*se] if se else None,
        covariance_includes_shared_accounts_and_dates_across_groups=True,
        AR_type95_intervals_pp=interval_difference(ars[0],ars[1]) if all(x is not None for x in ars) else None,
        AR_type='Conservative Bonferroni projection of two 97.5% null-restricted AR sets for the separately fitted group effects; not the shared-nuisance pooled estimand.')
    return result,contrast

def pooled_interaction(d,code,split):
    code=np.asarray(code,bool);xs,names,traits,groups=r.feature_design(d,'X0')
    xs=np.column_stack([xs,code.astype(float)])
    D=np.column_stack([d['received']*(~code),d['received']*code]).astype(float)
    Z=np.column_stack([d['adjusted_7d']*(~code),d['adjusted_7d']*code]).astype(float)
    with heartbeat('R8-4 '+split+' pooled interacted IV'):
        a,_=rm.project(xs,[d['y'],D[:,0],D[:,1],Z[:,0],Z[:,1]],groups)
    y=a[:,0];D=a[:,1:3];Z=a[:,3:5];A=Z.T@D
    require(np.linalg.matrix_rank(A)==2,'Pooled interacted IV has rank deficient first stage')
    bread=np.linalg.inv(A);beta=bread@(Z.T@y);e=y-D@beta
    scores=(Z*e[:,None])@bread.T;V=rm.covariance(d)(scores)
    delta=np.array([1.,-1.]);var=float(delta@V@delta)
    out=dict(split=split,model='pooled_common_X0_and_FE',n=len(y),contrast='never_faced minus faced',
        never_faced_iv_pp=100*beta[0],faced_iv_pp=100*beta[1],coefficient_pp=100*float(delta@beta),
        standard_error_pp=100*math.sqrt(var) if var>0 else None,
        instruments='score times each group; receipt times each group; group indicator and common X0/FE',
        inference='joint shared-account OR date CR0',
        AR_note='Conservative AR set reported for separately fitted effects in experience_contrasts; no weak-IV claim is made for this pooled Wald difference.')
    se=out['standard_error_pp'];point=out['coefficient_pp']
    out['Wald95_pp']=[point-1.959963984540054*se,point+1.959963984540054*se] if se else None
    return out

def run(a,work,key):
    no_network();root,paths,binding=bind_r7(a.project_root,a.r7_root)
    report=work/'report';report.mkdir(parents=True,exist_ok=True)
    p=[v for v in load(root/'report/A_predicted_outcome.json') if v.get('sample') in ('S0','F50') and v.get('control_level')=='X0']
    table(report,'predicted_outcome_reused',p)
    archived=load(root/'report/A_joint_balance.json')
    r2=[]
    for name in ('S0','F50'):
        checkpoint=work/('R2_'+name);k=digest([key,'R2',name])
        if verify_cached(checkpoint,k):rr=load(checkpoint/'r2.json')
        else:
            checkpoint.mkdir(parents=True,exist_ok=True)
            d=r.load_fit_columns(paths[name]);rr=r_squared(d,name,archived,report)
            save(checkpoint/'r2.json',rr);certify(checkpoint,k,[paths[name]])
            del d;gc.collect()
        r2+=rr
    table(report,'predicted_outcome_R2',r2)
    splitpath,coverage=prior_frame(paths,binding,a.project_root,work,key,a.memory_gb)
    save(report/'prior_experience_coverage.json',coverage)
    d=r.load_fit_columns(paths['S0']);s=r.arrays(r.io.read(splitpath))
    require(np.array_equal(d['row_id'],s['row_id']),'Experience attachment changed the frozen row order')
    rows=[];contrasts=[];pooled=[]
    for label,col in [('full_recorded_history','faced_recorded'),('past90_days','faced90')]:
        row,contrast=split_fits(d,s[col],label,work/'fits',key);rows+=row;contrasts.append(contrast)
        checkpoint=work/('pooled_'+label);k=digest([key,'pooled',label])
        if verify_cached(checkpoint,k):result=load(checkpoint/'result.json')
        else:
            checkpoint.mkdir(parents=True,exist_ok=True);result=pooled_interaction(d,s[col],label)
            save(checkpoint/'result.json',result);certify(checkpoint,k,[paths['S0'],splitpath])
        pooled.append(result)
    for val,label in [(0,'no_choice90'),(1,'choices90_never_granted'),(2,'granted90')]:
        checkpoint=work/('secondary90_'+str(val));k=digest([key,'secondary90',val])
        if verify_cached(checkpoint,k):row=load(checkpoint/'result.json')
        else:
            checkpoint.mkdir(parents=True,exist_ok=True)
            row,_,_=group_iv(r.subset(d,s['group90']==val),label)
            save(checkpoint/'result.json',row);certify(checkpoint,k,[paths['S0'],splitpath])
        rows.append(dict(row,split='past90_days_three_groups'))
    table(report,'experience_IV',rows);table(report,'experience_contrasts',contrasts)
    table(report,'pooled_interaction_IV',pooled)
    save(report/'COMPLETION.json',dict(status='R8_RECEIPT_CURRENT_DATA_COMPLETE',author_clean=True,
        score_reestimated=False,prior_history_scope=coverage['source_window'],primary_history_replaced_by90d=False,
        causal_identification_certified=False,network_requests=0,stockfish_searches=0))
    certify(work,key,[root/'report/summary.json',paths['S0'],paths['F50'],splitpath])

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,required=True);p.add_argument('--r7-root',type=Path)
    p.add_argument('--work',type=Path,required=True);p.add_argument('--key',required=True);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args();run(a,a.work,a.key)
