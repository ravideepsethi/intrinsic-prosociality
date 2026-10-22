"""Conditional comparisons, overlap/balance audits, and shared-account inference.

These are observational contrasts. They neither refit nor decompose the IV.
"""
from common import *
import math

PAIRS=[
 ('grant_vs_stalemate',['granted_draw'],['ordinary_stalemate']),
 ('grant_vs_all_ordinary_draws',['granted_draw'],['ordinary_stalemate','ordinary_draw_unspecified']),
 ('claim_vs_ordinary_loss',['claimed_loss'],['ordinary_loss']),
 ('stalemate_vs_ordinary_loss',['ordinary_stalemate'],['ordinary_loss']),
 ('ordinary_draw_vs_ordinary_loss',['ordinary_stalemate','ordinary_draw_unspecified'],['ordinary_loss']),
 ('grant_vs_no_material_draw',['granted_draw'],['no_material_draw']),
 ('grant_vs_unspecified_draw',['granted_draw'],['ordinary_draw_unspecified']),
 ('grant_vs_claim_benchmark',['granted_draw'],['claimed_loss']),
]
BALANCE=['recipient_rating','opponent_rating','rating_gap','log_pre_games','log_fair90',
         'prior_kind_rate','fair_history_present','log_disconnect90','log_receipt90',
         'log_claim90','adjusted_7d','expected_7d','log_n7']
POSITION_BALANCE=['board_cp','ply','giver_clock','recipient_clock']
DERIVED='''recipient_rating-opponent_rating rating_gap,
  ln(1+pre_games_30d) log_pre_games,ln(1+fair_90) log_fair90,
  CASE WHEN fair_90>0 THEN kind_90::DOUBLE/fair_90 ELSE 0 END prior_kind_rate,
  (fair_90>0)::INT fair_history_present,ln(1+disconnect_90) log_disconnect90,
  ln(1+receipt_90) log_receipt90,ln(1+claim_90) log_claim90,ln(1+n_7d) log_n7,
  CASE WHEN tc_base_s+40*tc_inc_s<180 THEN 0 WHEN tc_base_s+40*tc_inc_s<480 THEN 1
       WHEN tc_base_s+40*tc_inc_s<1500 THEN 2 ELSE 3 END speed_class,
  floor(recipient_rating/200)::INT rating_band,
  CASE WHEN recipient_rating-opponent_rating< -200 THEN -1 WHEN recipient_rating-opponent_rating>200 THEN 1 ELSE 0 END gap_band,
  CASE WHEN fair_90=0 THEN 0 WHEN fair_90<5 THEN 1 WHEN fair_90<20 THEN 2 ELSE 3 END fair_band,
  (kind_90>0)::INT prior_kind,
  CASE WHEN pre_games_30d<10 THEN 0 WHEN pre_games_30d<50 THEN 1 WHEN pre_games_30d<200 THEN 2 ELSE 3 END volume_band'''
CELL=['month_code','speed_class','rating_band','gap_band','fair_band','prior_kind','volume_band']

def uncertainty(c,actors,influence,nparameters=1):
    """CR1 recipient SE and dyadic/overlapping-account HC1 SE.

    Inclusion-exclusion counts each pair of observations sharing any account
    exactly once, even when two or three accounts coincide or swap roles.
    """
    n=len(influence);ids=np.asarray(actors,np.int64)
    if ids.shape!=(n,3):raise ValueError('Three account slots required')
    ids=np.sort(ids,axis=1)
    # Repeated identities in a row should not produce repeated memberships.
    for j in (2,1):ids[ids[:,j]==ids[:,j-1],j]=-1
    ids=np.sort(ids,axis=1)
    t=pa.table(dict(a=ids[:,0],b=ids[:,1],c=ids[:,2],u=np.asarray(influence,float),r=actors[:,0]))
    c.register('influence_rows',t)
    try:
        g,vr=c.execute('SELECT count(*),sum(s*s) FROM (SELECT r,sum(u) s FROM influence_rows GROUP BY r)').fetchone()
        v1=c.execute('''SELECT coalesce(sum(s*s),0) FROM (SELECT id,sum(u) s FROM
          (SELECT a id,u FROM influence_rows WHERE a>=0 UNION ALL SELECT b,u FROM influence_rows WHERE b>=0
           UNION ALL SELECT c,u FROM influence_rows WHERE c>=0) GROUP BY id)''').fetchone()[0]
        v2=c.execute('''SELECT coalesce(sum(s*s),0) FROM (SELECT a,b,sum(u) s FROM
          (SELECT a,b,u FROM influence_rows WHERE a>=0 AND b>=0 UNION ALL
           SELECT a,c,u FROM influence_rows WHERE a>=0 AND c>=0 UNION ALL
           SELECT b,c,u FROM influence_rows WHERE b>=0 AND c>=0) GROUP BY a,b)''').fetchone()[0]
        v3=c.execute('''SELECT coalesce(sum(s*s),0) FROM
          (SELECT a,b,c,sum(u) s FROM influence_rows WHERE a>=0 GROUP BY a,b,c)''').fetchone()[0]
    finally:c.unregister('influence_rows')
    adj=(n-1)/(n-nparameters) if n>nparameters else float('nan')
    vd=(v1-v2+v3)*adj
    return dict(recipient_clusters=g,recipient_se=math.sqrt(max(0,vr)*adj*g/(g-1)) if g>1 else None,
                shared_account_variance=vd,shared_account_se=math.sqrt(vd) if vd>=0 else None,
                shared_account_variance_negative=bool(vd<0))

def coefficient_row(beta,unc,n1,n0,scale=100):
    out={k:v for k,v in unc.items() if k not in ('recipient_se','shared_account_se','shared_account_variance')}
    se=unc['shared_account_se'];out.update(estimate=beta*scale,recipient_se=unc['recipient_se']*scale if unc['recipient_se'] is not None else None,
       shared_account_se=se*scale if se is not None else None)
    enough=unc['recipient_clusters']>=30 and min(n1,n0)>=30
    out['inference_status']='nominal_large_sample' if enough and se is not None and se>0 else 'insufficient_clusters_or_invalid_variance'
    if out['inference_status']=='nominal_large_sample':
        lo,hi=(beta-1.959963984540054*se)*scale,(beta+1.959963984540054*se)*scale
        out.update(ci95_low=lo,ci95_high=hi,p_normal=math.erfc(abs(beta/se)/math.sqrt(2)))
        if scale==100:
            for margin in (.1,.25):out[f'ci95_inside_plusminus_{margin:g}_pp']=bool(lo> -margin and hi<margin)
    return out

def cem_fit(d,outcome,c):
    a=np.asarray(d['arm'],float);y=np.asarray(d[outcome],float);w=np.asarray(d['weight'],float)
    s=np.asarray(d['stratum'],np.int64);sw=np.bincount(s,w)
    sy=np.bincount(s,w*y);mean=sy/sw
    beta=np.sum(w*a*y)/np.sum(w*a)-np.sum(w*(1-a)*y)/np.sum(w*(1-a))
    residual=y-mean[s]-beta*(a-.5)
    bread=np.sum(w)/4;influence=w*(a-.5)*residual/bread
    actors=np.column_stack([d['recipient_id'],d['opponent_id'],np.where(d['reached']==1,d['outcome_opponent'],-1)])
    u=uncertainty(c,actors,influence,nparameters=len(sw)+1)
    out=coefficient_row(beta,u,np.unique(d['recipient_id'][a==1]).size,np.unique(d['recipient_id'][a==0]).size)
    out.update(outcome=outcome,units='percentage points',treated_mean_percent=100*np.average(y[a==1],weights=w[a==1]),
               comparison_mean_percent=100*np.average(y[a==0],weights=w[a==0]))
    return out

def balance_rows(d,raw,variables=BALANCE):
    ans=[];a=d['arm'];w=d['weight'];by={(r['arm'],r['variable']):r for r in raw}
    for v in variables:
        x=np.asarray(d[v],float);r1=by[(1,v)];r0=by[(0,v)]
        sd=math.sqrt(max(0,((r1['variance'] or 0)+(r0['variance'] or 0))/2))
        ok1=(a==1)&np.isfinite(x);ok0=(a==0)&np.isfinite(x)
        m1=np.average(x[ok1],weights=w[ok1]) if ok1.any() else None
        m0=np.average(x[ok0],weights=w[ok0]) if ok0.any() else None
        ans.append(dict(variable=v,raw_treated_mean=r1['mean'],raw_comparison_mean=r0['mean'],
            matched_treated_mean=m1,matched_comparison_mean=m0,
            matched_treated_observed_rows=int(ok1.sum()),matched_comparison_observed_rows=int(ok0.sum()),
            raw_smd=(r1['mean']-r0['mean'])/sd if sd>0 and r1['mean'] is not None and r0['mean'] is not None else None,
            matched_smd=((m1-m0)/sd if sd>0 else (0 if m1==m0 else None)) if m1 is not None and m0 is not None else None))
    return ans

def one_pair(c,work,key,name,treated,control,spec='overlap'):
    out=Path(work)/'comparisons'/(name+'__'+spec);out.mkdir(parents=True,exist_ok=True)
    if checkpoint_ok(out,key):return out
    groups=treated+control;ingroup=','.join(q(x) for x in groups);inarm=','.join(q(x) for x in treated)
    c.execute(f'CREATE OR REPLACE TEMP TABLE p AS SELECT *, (exposure_group IN ({inarm}))::INT arm FROM base WHERE exposure_group IN ({ingroup})')
    missing_position=0
    if spec=='position_overlap':
        invalid=' OR '.join(f'NOT coalesce(isfinite({v}),false)' for v in POSITION_BALANCE)
        missing_position=c.execute('SELECT count(*) FROM p WHERE '+invalid).fetchone()[0]
        c.execute('DELETE FROM p WHERE '+invalid)
    counts=records(c,'SELECT arm,count(*) AS "rows",count(DISTINCT recipient_id) recipients,sum(y) kind_events,sum(reached) reached_events FROM p GROUP BY arm ORDER BY arm')
    summary=dict(name=name,specification=spec,treated=treated,comparison=control,unmatched=counts,
       estimand='Overlap-weighted observational difference in this pair-specific common-support population',
       causal_identification=False,ordinary_position_balance_available=False,position_missing_rows=missing_position)
    if len(counts)<2:
        summary['status']='NO_OBSERVATIONS_IN_ONE_ARM';write(out/'summary.json',summary);finish(out,key);return out
    variables=BALANCE+(POSITION_BALANCE if name in ('grant_vs_no_material_draw','grant_vs_claim_benchmark') else [])
    raw=[]
    for v in variables:
        raw+=records(c,f'SELECT arm,{q(v)} AS "variable",avg({v}) FILTER(WHERE isfinite({v})) mean,var_pop({v}) FILTER(WHERE isfinite({v})) variance FROM p GROUP BY arm')
    cells=(['recipient_id','speed_class'] if spec=='within_recipient' else
           [x for x in CELL if x!='speed_class']+['tc_base_s','tc_inc_s'] if spec=='exact_time_control' else CELL)
    if spec=='position_overlap':
        cells=cells+['floor(greatest(-600,least(600,board_cp))/100)',
                     'floor(ply/20)','floor(ln(1+greatest(0,giver_clock)))','floor(ln(1+greatest(0,recipient_clock)))']
    ck="concat_ws('|',"+','.join(cells)+')'
    select=','.join(['recipient_id','opponent_id','outcome_opponent','reached','y','game_id','outcome_gid','arm']+variables)
    query=f'''WITH k AS (SELECT *,{ck} cell FROM p),
      n AS (SELECT *,count(*) FILTER(WHERE arm=1) OVER(PARTITION BY cell) n1,
        count(*) FILTER(WHERE arm=0) OVER(PARTITION BY cell) n0 FROM k)
      SELECT {select},dense_rank() OVER(ORDER BY cell)-1 AS stratum,
        CASE WHEN arm=1 THEN n0::DOUBLE/(n1+n0) ELSE n1::DOUBLE/(n1+n0) END weight
      FROM n WHERE n1>=1 AND n0>=1 ORDER BY stratum,arm,recipient_id,game_id'''
    n=copy(c,query,out/'selected_PRIVATE.parquet')
    if not n:
        summary['status']='NO_COMMON_SUPPORT';write(out/'summary.json',summary);finish(out,key);return out
    d=arrays(pq.ParquetFile(out/'selected_PRIVATE.parquet').read())
    support=[]
    for a in (0,1):
        use=d['arm']==a;w=d['weight'][use];old=next(r for r in counts if r['arm']==a)
        support.append(dict(arm=a,rows=int(use.sum()),recipients=np.unique(d['recipient_id'][use]).size,
            retained_share=use.sum()/old['rows'],effective_n=w.sum()**2/np.sum(w*w),
            weight_mass=w.sum(),events=int(d['y'][use].sum()),reached=int(d['reached'][use].sum()),
            conditional_kindness_percent=100*np.sum(w*d['y'][use])/np.sum(w*d['reached'][use]) if np.sum(w*d['reached'][use])>0 else None))
    balance=balance_rows(d,raw,variables);est=[cem_fit(d,y,c) for y in ('y','reached')]
    # Measured prior generosity remains a diagnostic; it is NOT a future outcome.
    summary.update(status='ESTIMATED',support=support,strata=int(np.max(d['stratum'])+1),
        maximum_absolute_matched_smd=max(abs(r['matched_smd']) for r in balance if r['matched_smd'] is not None),
        repeated_future_outcome_rows=int(np.sum(d['reached']))-len(set(d['outcome_gid'][d['reached']==1])),
        inference='Shared-account overlap sandwich includes focal recipient, current opponent, and later opponent; scores and matching cells treated as fixed',
        within_recipient_caveat='This uses only players observed in both arms within time-control class, across the full period; time-varying confounding remains' if spec=='within_recipient' else None)
    write(out/'summary.json',summary);write(out/'estimates.json',est);csvwrite(out/'estimates.csv',est)
    csvwrite(out/'balance.csv',balance);csvwrite(out/'support.csv',support);finish(out,key);return out

def comparisons(paths,work,key,threads,memory):
    c=conn(Path(work)/'spill/models',threads,max(1,memory*.4))
    try:
        c.execute('CREATE VIEW source AS SELECT * FROM '+scan([Path(p)/'comparisons.parquet' for p in paths]))
        # All covariates must be observed before the focal exposure. No current
        # result, realized rating change, or future-opportunity control enters.
        c.execute('CREATE TEMP TABLE base AS SELECT *, '+DERIVED+' FROM source WHERE entry_eligible AND complete90')
        bad=c.execute('SELECT count(*) FROM base WHERE '+' OR '.join(f'NOT coalesce(isfinite({v}),false)' for v in BALANCE)).fetchone()[0]
        if bad:raise RuntimeError('Nonfinite predetermined comparison covariates')
        bad=c.execute('''SELECT count(*) FROM base WHERE fair_90<0 OR kind_90<0 OR kind_90>fair_90
           OR pre_games_30d<0 OR disconnect_90<0 OR receipt_90<0 OR claim_90<0''').fetchone()[0]
        if bad:raise RuntimeError('Invalid prehistory counts')
        results=[]
        for name,a,b in PAIRS:
            specs=['overlap','exact_time_control','within_recipient']
            if name in ('grant_vs_no_material_draw','grant_vs_claim_benchmark'):specs.append('position_overlap')
            for spec in specs:
                with heartbeat(f'Estimating {name}: {spec}'):
                    results.append(one_pair(c,work,key,name,a,b,spec))
        return results
    finally:c.close()
