"""Exact-hour common-shock sensitivity on the frozen receipt and IV rows."""
from util import *
from scipy.stats import norm

def model_load(p,key):
    receipt=Path(str(p)+'.ok.json')
    if not p.is_file() or not receipt.is_file():return None
    r=load(receipt)
    require(r['key']==key and sha(p)==r['sha256'],'Per-model checkpoint damaged: '+str(p))
    return load(p)

def model_save(p,key,result):
    js(p,result);js(str(p)+'.ok.json',dict(key=key,sha256=sha(p)))

def paths(project):
    p=Path(project)
    base=p/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1/project_view'
    r=base/'derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet'
    iv=p/'derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet'
    return r,iv

def locate_receipt(project):
    r,_=paths(project)
    options=[r,Path(project)/'derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet']
    # Exact known relative producer locations; no broad scan of billions of files.
    for p in options:
        if p.is_file():return p
    raise FileNotFoundError('Frozen receipt panel missing: '+str(r))

def score_meat(X,err,w,groups):
    _,codes=np.unique(np.asarray(groups),return_inverse=True);G=int(codes.max())+1
    S=np.column_stack([np.bincount(codes,weights=w*err*X[:,j],minlength=G) for j in range(X.shape[1])])
    return S.T@S,G

def fit(y,treatment,controls,w,groups,clusters):
    core=module('receipt_core_numeric',ROOT/'vendor/core/receipt_core.py')
    a=np.column_stack([y,treatment,controls]);z,it,last=core.weighted_absorb(a,w,groups)
    y=z[:,0];X=z[:,1:];del a,z
    from repetition import solve
    fit=solve((X*w[:,None]).T@X,X.T@(w*y))
    test=np.zeros(X.shape[1]);test[0]=1
    require(np.linalg.norm((test/fit['scale'])@fit['null'])<1e-7,'Receipt contrast not identified after hour absorption')
    b=fit['beta'];err=y-X@b;bread=fit['bread'];M,G=score_meat(X,err,w,clusters)
    correction=G/(G-1)*(len(y)-1)/(len(y)-fit['rank'])
    V=bread@M@bread*correction;se=np.sqrt(max(0,V[0,0]));point=float(b[0])
    result=dict(coefficient_percentage_points=100*point,standard_error_percentage_points=100*se,
        ci_low=100*(point-1.96*se),ci_high=100*(point+1.96*se),p=float(2*norm.sf(abs(point/se))) if se else None,
        rows=len(y),clusters=G,rank=fit['rank'],absorption_iterations=it,absorption_residual=last,
        inference='chooser-clustered, same correction as original matched model')
    if len(groups)>2:
        h=groups[2];Mh,H=score_meat(X,err,w,h)
        _,pair=np.unique(np.column_stack([clusters,h]),axis=0,return_inverse=True)
        Mp,P=score_meat(X,err,w,pair)
        # Additional CR0 two-way dependence sensitivity, not substituted into baseline parity.
        V2=bread@(M+Mh-Mp)@bread;v=float(V2[0,0])
        result.update(se_chooser_or_exposure_hour_CR0_pp=100*np.sqrt(v) if v>=0 else None,
            two_way_variance_nonnegative=v>=0,exposure_hour_clusters=H)
    return result

def receipt(project,run,key):
    out=Path(run)/'report/receipt_hour';conf=digest([key,'receipt_exact_hours_v1'])
    if cached(out,conf):return dict(status='ESTIMATED',reused=True)
    p=locate_receipt(project);reference=load(ROOT/'authority/core_summary.json')
    auth=checked(p,reference['recipient_private_input_sha256'])
    core=module('receipt_core',ROOT/'vendor/core/receipt_core.py')
    d=core.load_recipient_arrays(p);support=core.common_support_weights(d)
    require(int(support['eligible'].sum())==2294012,'Receipt common support changed')
    t=pq.ParquetFile(p).read(columns=['cohort_row_id','exposure_game_utc_ms','exposure_anchor_utc_ms'],use_threads=False)
    require(np.array_equal(t['cohort_row_id'].to_numpy(),d['cohort_row_id']),'Timestamp row identity differs')
    start=t['exposure_game_utc_ms'].to_numpy();anchor=t['exposure_anchor_utc_ms'].to_numpy()
    complete=np.asarray(d['a1_90d_followup_eligible'],bool)&support['eligible']
    reached=np.asarray(d['reached_fair_chooser_within_90d'],bool)
    require(int(complete.sum())==2110400 and int((complete&reached).sum())==993762,'Receipt sample counts changed')
    results=[]
    outcomes=[('conditional_first_choice',complete&reached,np.asarray(d['first_subsequent_kind_draw'],float)),
        ('reach_90d',complete,reached.astype(float)),
        ('first_choice_zero_coded',complete,np.where(reached,d['first_subsequent_kind_draw'],0).astype(float))]
    for label,mask,yall in outcomes:
        ix=np.flatnonzero(mask);X,names=core.model_controls(d,ix,state_conditioned=False)
        w=support['weights'][ix];y=yall[ix];treat=np.asarray(d['received_mercy'][ix],float)
        base=[d['exposure_cell_code'][ix],d['exposure_month_code'][ix]];cluster=d['exposure_chooser_user_id'][ix]
        require(np.isfinite(start[ix]).all() and np.isfinite(anchor[ix]).all() and (anchor[ix]>=start[ix]).all(),'Invalid exposure times')
        modes=[('baseline',[]),('exposure_start_hour',[start[ix]//HOUR]),('exposure_last_move_hour',[anchor[ix]//HOUR])]
        if label=='conditional_first_choice':
            future=anchor[ix]+d['first_subsequent_delta_ms'][ix]
            require(np.isfinite(future).all() and (future>anchor[ix]).all(),'Invalid subsequent choice times')
            modes += [('both_last_move_hours_post_exposure_sensitivity',[anchor[ix]//HOUR,future//HOUR])]
        for mode,extra in modes:
            cache=out/(label+'__'+mode+'.json')
            r=model_load(cache,conf)
            if r is None:
                with heartbeat('Receipt '+label+' / '+mode):r=fit(y,treat,X,w,base+extra,cluster)
                r.update(outcome=label,specification=mode,weighted_control_mean_percent=100*float(np.average(y[treat==0],weights=w[treat==0])),
                    row_set_sha256=hashlib.sha256(np.asarray(d['cohort_row_id'][ix],dtype='<i8').tobytes()).hexdigest(),
                    post_exposure_adjustment=('both_' in mode),clock_definition='UTC hours; last move is a decision-time proxy, not a claim-click time',
                    input_sha256=auth['sha256'],controls=names)
                model_save(cache,conf,r)
            if label=='conditional_first_choice' and mode=='baseline':
                require(abs(r['coefficient_percentage_points']-0.8816583609166886)<1e-6 and
                    abs(r['standard_error_percentage_points']-0.12240319188770558)<1e-6,'Matched baseline did not reproduce; hour estimates stopped')
            results.append(r)
    unchanged([auth]);tab(out/'results',[{k:v for k,v in r.items() if k!='controls'} for r in results]);commit(out,conf,source=auth)
    return dict(status='ESTIMATED',models=len(results))

def iv(project,run,key):
    out=Path(run)/'report/iv_hour';conf=digest([key,'iv_exact_hours_v1'])
    if cached(out,conf):return dict(status='ESTIMATED',reused=True)
    _,p=paths(project);ref=load(ROOT/'authority/iv_summary.json')
    f=next(x for x in ref['analysis_validation']['files'] if x['path']=='spaced90.parquet')
    auth=checked(p,f['sha256']);require(auth['stat']['bytes']==f['bytes'],'IV source bytes changed')
    sys.path.insert(0,str(ROOT/'vendor/iv'))
    import local_io as io,expanded_stats as stats,expanded_logic as logic
    table=io.read(p);d={n:io.arr(table,n) for n in table.column_names};del table
    require(len(d['row_id'])==2682330 and logic.row_digest(d['row_id'])==ref['analysis_validation']['candidates']['spaced90']['row_set_sha256'],'IV frozen rows changed')
    original=stats.controls;results=[]
    for mode in ('baseline','exposure_start_hour','exposure_last_move_hour'):
        cache=out/(mode+'.json')
        r=model_load(cache,conf)
        if r is None:
            def with_hour(a,rich):
                xs,names,traits,tnames,groups,missing=original(a,rich)
                if mode!='baseline':
                    times=np.asarray(a['archive_start_ms' if mode=='exposure_start_hour' else 'anchor_ms'])
                    require(np.isfinite(times).all() and (times>0).all(),'Invalid IV hour timestamps')
                    groups=groups+[times//HOUR]
                return xs,names,traits,tnames,groups,missing
            stats.controls=with_hour
            try:
                spec=dict(name='main90_'+mode,family='iv',rich=True,fe=False,repeat=False,balance=False)
                with heartbeat('Receipt IV / '+mode):r=stats.estimate(d,spec)
            finally:stats.controls=original
            r.update(exact_hour_adjustment=mode,post_exposure_outcome_hour_control=False,input_sha256=auth['sha256'])
            model_save(cache,conf,r)
        if mode=='baseline':
            point=next(x for x in r['estimates'] if x['estimator']=='2SLS')
            expected=next(x for x in load(ROOT/'authority/iv_estimates.json') if x['specification']=='main90_pooled' and x['estimator']=='2SLS')
            for term in ('iv_coefficient_pp','iv_standard_error_pp'):
                require(abs(point[term]-expected[term])<1e-6,'IV baseline did not reproduce: '+term)
        results.extend(r['estimates'])
    unchanged([auth]);js(out/'results.json',results)
    tab(out/'results',[{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in results]);commit(out,conf,source=auth)
    return dict(status='ESTIMATED',specifications=3)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['receipt','iv']);ap.add_argument('--project',required=True)
    ap.add_argument('--run',required=True);ap.add_argument('--key',required=True);a=ap.parse_args()
    print(json.dumps(globals()[a.stage](a.project,a.run,a.key)))
