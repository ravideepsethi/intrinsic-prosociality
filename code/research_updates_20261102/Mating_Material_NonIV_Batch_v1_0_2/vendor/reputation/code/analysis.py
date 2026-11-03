from core import *
import rep_stats as stats

def pair_counts(keys,times,qp,starts,anchors):
    """Exact vectorized windows; historical and future ties handled separately."""
    moments_e=moments(keys.view(np.int64),times)
    # Unsigned pair order must be recast consistently before structured search.
    order=np.argsort(moments_e,kind='stable');ee=moments_e[order];qp=qp.view(np.int64)
    before=np.searchsorted(ee,moments(qp,starts),'left');ans={}
    for h in (30,90):ans['prior'+str(h)]=before-np.searchsorted(ee,moments(qp,starts-h*DAY),'left')
    lo=np.searchsorted(ee,moments(qp,anchors),'right')
    for h in (30,90,180):ans['meet'+str(h)]=np.searchsorted(ee,moments(qp,anchors+h*DAY),'right')-lo
    # Timing sensitivity: no new game until an hour after lastMoveAt.
    lo1=np.searchsorted(ee,moments(qp,anchors+3600000),'right')
    ans['meet90_after1h']=np.searchsorted(ee,moments(qp,anchors+90*DAY),'right')-lo1
    ans['same_start_other_games']=(np.searchsorted(ee,moments(qp,starts),'right')-before-1)
    if any(np.any(v<0) for k,v in ans.items()):raise RuntimeError('Negative pair counts')
    return ans

def make_features(history,returns,folder,threads,memory,return_scope):
    folder=Path(folder);old=cached(folder)
    if old:return old
    folder.mkdir(parents=True,exist_ok=True);c=conn(folder/'spill',threads,memory)
    try:
        q=pq.ParquetFile(Path(history)/'features.parquet').read();e=pq.ParquetFile(Path(history)/'events.parquet').read(columns=['pair_key','t'])
        extra=pair_counts(array(e,'pair_key',np.uint64),array(e,'t',np.int64),array(q,'pair_key',np.uint64),array(q,'start',np.int64),array(q,'anchor',np.int64));del e
        for k,v in extra.items():q=q.append_column(k,pa.array(v))
        pq.write_table(q,folder/'pre_returns.parquet',compression='zstd');del q
        c.execute('CREATE VIEW q AS SELECT * FROM '+scan(folder/'pre_returns.parquet'))
        c.execute('CREATE VIEW r0 AS SELECT * FROM '+scan(returns))
        n,u=c.execute('SELECT count(*),count(DISTINCT gid) FROM r0').fetchone()
        if n!=u:raise RuntimeError('Duplicate repayment opportunity IDs')
        c.execute('CREATE VIEW r AS SELECT * FROM r0 WHERE start>='+str(START)+' AND anchor<'+str(END))
        expr=[]
        for h in (30,90,180):
            w=f'r.anchor<=q.anchor+{h*DAY}'
            expr.extend([f'count(r.gid) FILTER(WHERE {w}) AS repay_opportunities{h}',
              f'count(r.gid) FILTER(WHERE {w} AND r.y) AS repayments{h}',
              f'count(r.gid) FILTER(WHERE {w} AND (r.recipient_gain IS NULL OR NOT isfinite(r.recipient_gain) OR r.recipient_gain<0)) AS missing_value{h}',
              f'coalesce(sum(r.recipient_gain) FILTER(WHERE {w} AND isfinite(r.recipient_gain) AND r.recipient_gain>=0),0) potential_points{h}',
              f'coalesce(sum(r.recipient_gain) FILTER(WHERE {w} AND r.y AND isfinite(r.recipient_gain) AND r.recipient_gain>=0),0) received_points{h}'])
        sql='SELECT q.qid,'+','.join(expr)+''' FROM q LEFT JOIN r ON r.j=q.i AND r.i=q.j AND r.start>q.anchor
            AND r.start<=q.anchor+'''+str(180*DAY)+''' AND r.anchor<=q.anchor+'''+str(180*DAY)+' GROUP BY q.qid'
        copy(c,sql,folder/'returns.parquet')
        copy(c,'SELECT q.*,r.* EXCLUDE(qid) FROM q JOIN '+scan(folder/'returns.parquet')+' r USING(qid) ORDER BY qid',folder/'analysis.parquet')
        result=dict(rows=pq.ParquetFile(folder/'analysis.parquet').metadata.num_rows,return_scope=return_scope,
            rating_value='Original giver as later recipient: stored recipient-side win premium, equal to draw-minus-loss under maintained fixed-state formula',
            value_interpretation='Observed-path finite-horizon capacity only, not a causal or lifetime upper bound')
        finish(folder,result);return result
    finally:c.close()

def read_arrays(p):
    t=pq.ParquetFile(p).read();return {n:array(t,n) for n in t.column_names if n!='gid'}

def descriptions(d,return_scope):
    out=[]
    for h in (30,90,180):
        complete=d['anchor']+h*DAY<END
        for history,hm in [('all',np.ones(len(complete),bool)),('first_observed',~d['repeat']&(d['same_start_other_games']==0)),('repeat',d['repeat'])]:
            for arm,am in [('all',np.ones(len(complete),bool)),('grant',d['y']),('claim',~d['y'])]:
                ix=complete&hm&am;n=int(ix.sum())
                if not n:continue
                for region,rm in [('all',np.ones(len(complete),bool)),('competitive',d['fair']),('clearly_worse',d['lost'])]:
                    z=ix&rm;nn=int(z.sum())
                    if not nn:continue
                    meet=d[f'meet{h}'][z];opp=d[f'repay_opportunities{h}'][z];rep=d[f'repayments{h}'][z]
                    good=z&(d[f'missing_value{h}']==0)&np.isfinite(d['cost'])&(d['cost']>0)
                    out.append(dict(horizon_days=h,history=history,initial_action=arm,region=region,n=nn,
                        later_meeting_pct=100*np.mean(meet>0),mean_later_meetings=float(np.mean(meet)),
                        repayment_opportunity_pct=100*np.mean(opp>0),actual_repayment_pct=100*np.mean(rep>0),
                        later_opportunities=int(opp.sum()),later_grants=int(rep.sum()),return_scope=return_scope,
                        monetary_value_rows=int(good.sum()),potential_points_sum=float(d[f'potential_points{h}'][good].sum()),
                        initial_cost_sum=float(d['cost'][good].sum()),received_points_sum=float(d[f'received_points{h}'][good].sum()),
                        ratio_potential_to_initial_cost=float(d[f'potential_points{h}'][good].sum()/d['cost'][good].sum()) if good.any() else None,
                        share_potential_covers_initial_cost=float(np.mean(d[f'potential_points{h}'][good]>=d['cost'][good])) if good.any() else None))
    return out

def regression(d,mask,mode,name):
    ix=np.flatnonzero(mask);x={k:v[ix] for k,v in d.items() if k in ['y','fair','repeat','cp','j','i','start','month','speed','rating','opp_rating','rd','opp_rd','cost','draw_payoff','clock','opp_clock','ply']}
    finite=np.ones(len(ix),bool)
    for k in ['rating','opp_rating','rd','opp_rd','cost','draw_payoff','ply']:finite &= np.isfinite(x[k])
    lost=int((~finite).sum());x={k:v[finite] for k,v in x.items()};n=len(x['y'])
    if not n:return [dict(specification=name,supported=False,reason='No usable rows',excluded_nonfinite=lost)]
    controls=[];cn=[]
    for key in ['rating','opp_rating','rd','opp_rd','cost','draw_payoff']:
        v=x[key].astype(float);controls.append((v-v.mean())/max(float(v.std()),1e-12));cn.append(key)
    for key in ['clock','opp_clock']:
        missing=~np.isfinite(x[key]);v=np.log1p(np.maximum(np.where(missing,0,x[key]),0));controls.extend([v,missing.astype(float)]);cn.extend(['log_'+key,key+'_missing'])
    hour=((x['start']//3600000+72)%168).astype(np.int64);ply=np.searchsorted([4,10,20,40,60,100],x['ply'],side='left')
    groups=[x['j'],x['month'],x['speed'],hour,ply]
    if mode=='repeat_competitive':
        targets=[x['repeat'].astype(float)];names=['repeat_minus_first_competitive'];groups.append(np.searchsorted([-100,0,100,200,300,500,1000],x['cp']))
    elif mode=='interaction':
        f=x['fair'].astype(float);r=x['repeat'].astype(float);targets=[f,r,f*r];names=['competitive_gradient_first','repeat_difference_lost','repeat_minus_first_gradient']
    else:targets=[x['fair'].astype(float)];names=['competitive_minus_clearly_worse']
    meta,rows=stats.fit_fe(x['y'],targets,controls,groups,x['j'],x['i'],x['start']//DAY,names)
    if not rows:rows=[meta]
    return [dict(**r,specification=name,excluded_nonfinite=lost,design=meta,controls=cn,standard_errors_condition_on_prediction=True) for r in rows]

def prediction(d,folder):
    folder=Path(folder);old=cached(folder)
    if old:
        return np.load(folder/'predicted_probability.npy'),load(folder/'prediction.json'),load(folder/'calibration.json')
    folder.mkdir(parents=True,exist_ok=True)
    X,names=stats.prediction_raw(d);finite=np.isfinite(X).all(axis=1);complete=d['anchor']+90*DAY<END
    fold=(mix(d['pair_key']^np.uint64(0xD1B54A32D192ED03))%np.uint64(5)).astype(int)
    train=finite&complete&(d['start']<1714521600000)&(d['anchor']+90*DAY<1722470400000)&(fold<2) # labels mature before calibration
    calibrate=finite&complete&(d['start']>=1722470400000)&(d['start']<1730419200000)&(fold==2) # Aug-Oct 2024
    test=finite&complete&(d['start']>=1730419200000)&(fold>=3) # Nov 2024 onward
    yy=(d['meet90']>0).astype(float)
    if train.sum()<2000 or calibrate.sum()<1000 or test.sum()<1000 or min(yy[train].sum(),train.sum()-yy[train].sum())<30:
        raise RuntimeError('Insufficient support for the declared temporal/pair-disjoint prediction split')
    mean=X[train].mean(axis=0);sd=X[train].std(axis=0);mean[0]=0;sd[0]=1;sd=np.where(sd<1e-10,1,sd)
    X=(X-mean)/sd;b,it=stats.logistic_fit(X[train],yy[train]);prob=np.full(len(yy),np.nan);prob[finite]=1/(1+np.exp(-np.clip(X[finite]@b,-35,35)))
    # Threshold fixed on calibration predictions without inspecting grant outcomes.
    threshold=float(np.quantile(prob[calibrate],.2));rows=[]
    bounds=[0,.001,.005,.01,.025,.05,.10,.25,1.000001]
    for label,mask in [('calibration',calibrate),('evaluation',test)]:
        for lo,hi in zip(bounds[:-1],bounds[1:]):
            ix=mask&(prob>=lo)&(prob<hi)
            if ix.any():rows.append(dict(sample=label,prediction_low=lo,prediction_high=hi,n=int(ix.sum()),predicted_pct=100*float(prob[ix].mean()),observed_pct=100*float(yy[ix].mean())))
        ix=mask&(prob<=threshold);rows.append(dict(sample=label,group='calibration_bottom_quintile_threshold',threshold=threshold,n=int(ix.sum()),predicted_pct=100*float(prob[ix].mean()) if ix.any() else None,observed_pct=100*float(yy[ix].mean()) if ix.any() else None))
    meta=dict(features=names,coefficients=b,scaling_mean=mean,scaling_sd=sd,iterations=it,training_rows=int(train.sum()),calibration_rows=int(calibrate.sum()),evaluation_rows=int(test.sum()),low_threshold=threshold,
        rule='Train before May 2024, folds 0/1; calibration Aug-Oct 2024 fold 2; evaluate Nov 2024 onward folds 3/4; all 90-day complete. Pair folds never overlap.',
        label='Any same-pair recorded rated real-time meeting within 90 days after lastMoveAt',
        grant_outcome_used_in_prediction=False,limitation='Predicted observed encounters under existing behavior, not subjective beliefs or a causal return forecast')
    np.save(folder/'predicted_probability.npy',prob);np.save(folder/'evaluation_mask.npy',test);dump(folder/'prediction.json',meta);dump(folder/'calibration.json',rows)
    finish(folder,dict(status='PREDICTION_COMPLETE'));return prob,clean(meta),rows

def run_analyses(feature_file,folder,return_scope):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);d=read_arrays(feature_file)
    table_csv(descriptions(d,return_scope),folder/'reencounters_and_repayment.csv')
    complete=d['anchor']+90*DAY<END
    timing=[dict(n=int(complete.sum()),meeting90_pct=100*float(np.mean(d['meet90'][complete]>0)),meeting90_after_one_hour_pct=100*float(np.mean(d['meet90_after1h'][complete]>0)),
        same_start_tied_rows=int(np.sum(d['same_start_other_games']>0)),anchor='API lastMoveAt, not observed button-click time')]
    table_csv(timing,folder/'timestamp_sensitivity.csv')
    estimates=[];statuses=[]
    unambiguous=d['repeat']|(d['same_start_other_games']==0)
    for name,mask,mode in [('first_repeat_gradient',(d['fair']|d['lost'])&unambiguous,'interaction'),('repeat_premium_competitive',d['fair']&unambiguous,'repeat_competitive')]:
        rp=folder/(name+'.json')
        if rp.exists():rows=load(rp)
        else:
            with heartbeat(name):rows=regression(d,mask,mode,name)
            dump(rp,rows)
        estimates+=rows
    try:
        with heartbeat('Re-encounter prediction'):prob,meta,cal=prediction(d,folder/'prediction_private')
        dump(folder/'prediction_design.json',meta);table_csv(cal,folder/'prediction_calibration.csv')
        test=np.load(folder/'prediction_private/evaluation_mask.npy');low=test&(prob<=meta['low_threshold'])
        rates=[]
        for label,mask in [('evaluation_all',test),('evaluation_low_risk',low),('evaluation_low_risk_first',low&~d['repeat']&unambiguous),('evaluation_under_1pct_prediction',test&(prob<=.01))]:
            for region,rm in [('all',np.ones(len(test),bool)),('competitive',d['fair']),('clearly_worse',d['lost'])]:
                ix=mask&rm
                if ix.any():rates.append(dict(group=label,region=region,n=int(ix.sum()),grants=int(d['y'][ix].sum()),grant_pct=100*float(d['y'][ix].mean()),predicted_reencounter_pct=100*float(prob[ix].mean()),actual_reencounter_pct=100*float((d['meet90'][ix]>0).mean())))
        table_csv(rates,folder/'low_risk_grant_rates.csv')
        for name,mask in [('evaluation_gradient',test),('low_risk_gradient',low),('low_risk_first_gradient',low&~d['repeat']&unambiguous)]:
            rp=folder/(name+'.json')
            if rp.exists():rows=load(rp)
            else:
                with heartbeat(name):rows=regression(d,mask&(d['fair']|d['lost']),'gradient',name)
                dump(rp,rows)
            estimates+=rows
        statuses.append(dict(module='prediction_and_low_risk',status='COMPLETE'))
    except RuntimeError as e:
        statuses.append(dict(module='prediction_and_low_risk',status='UNSUPPORTED',reason=str(e)))
    # Holm adjustment for the three declared main chooser-clustered tests.
    primary=[r for r in estimates if r.get('supported') and r.get('covariance')=='chooser_CR1' and
        (r.get('contrast')=='competitive_gradient_first' or r.get('specification')=='repeat_premium_competitive' or r.get('specification')=='low_risk_gradient')]
    order=sorted(primary,key=lambda r:r['p']);prev=0
    for k,r in enumerate(order):prev=max(prev,min(1.,(3-k)*r['p']));r['p_Holm_three_planned_tests']=prev
    dump(folder/'estimates.json',estimates);table_csv(estimates,folder/'estimates.csv');dump(folder/'module_status.json',statuses)
    return dict(rows=len(d['qid']),return_scope=return_scope,module_status=statuses)
