"""Ordinary draw versus loss on the corrected 90-day comparison frame.

The estimator is the original coarsened-cell overlap estimator. The frame and
history window deliberately follow the corrected primary IV, not the older
97-day eligibility/cooldown frame. This is an observational mechanism check.
"""
from closeout_common import *
import itertools,math
BALANCE=['recipient_rating','opponent_rating','rating_gap','log_pre_games','log_fair90','prior_kind_rate','fair_history_present','log_disconnect90','log_receipt90','log_claim90','adjusted_A','expected_A','log_nA']
CELL=['month_code','speed_class','rating_band','gap_band','fair_band','prior_kind','volume_band']
DERIVED='''recipient_rating-opponent_rating rating_gap,
 ln(1+pre_games_90d) log_pre_games,ln(1+fair_90) log_fair90,
 CASE WHEN fair_90>0 THEN kind_90::DOUBLE/fair_90 ELSE 0 END prior_kind_rate,
 (fair_90>0)::INT fair_history_present,ln(1+disconnect_90) log_disconnect90,
 ln(1+receipt_90) log_receipt90,ln(1+claim_90) log_claim90,ln(1+n_A) log_nA,
 CASE WHEN tc_base_s+40*tc_inc_s<180 THEN 0 WHEN tc_base_s+40*tc_inc_s<480 THEN 1 WHEN tc_base_s+40*tc_inc_s<1500 THEN 2 ELSE 3 END speed_class,
 floor(recipient_rating/200)::INT rating_band,
 CASE WHEN recipient_rating-opponent_rating< -200 THEN -1 WHEN recipient_rating-opponent_rating>200 THEN 1 ELSE 0 END gap_band,
 CASE WHEN fair_90=0 THEN 0 WHEN fair_90<5 THEN 1 WHEN fair_90<20 THEN 2 ELSE 3 END fair_band,
 (kind_90>0)::INT prior_kind,
 CASE WHEN pre_games_90d<10 THEN 0 WHEN pre_games_90d<50 THEN 1 WHEN pre_games_90d<200 THEN 2 ELSE 3 END volume_band'''

def prepare(a,run,conf,auth):
    paths=auth['paths'];root=run/'PRIVATE/ordinary_frame'
    def build(tmp):
        db=connect(tmp,4.)
        try:
            view(db,'f',paths['frame']);view(db,'m',paths['metadata']);view(db,'s',paths['frame_scores'])
            assert_zero(db,'SELECT count(*) FROM (SELECT game_id FROM m GROUP BY 1 HAVING count(*)<>1)','Metadata repeats a game')
            db.execute("CREATE VIEW q AS SELECT * FROM f WHERE complete90 AND status IN ('draw','stalemate','mate','resign')")
            assert_zero(db,"SELECT count(*) FROM q WHERE recipient_color NOT IN ('white','black') OR recipient_color IS NULL",'Unknown focal color')
            assert_zero(db,'''SELECT count(*) FROM q LEFT JOIN m USING(game_id) WHERE m.game_id IS NULL OR q.status IS DISTINCT FROM m.status
              OR q.anchor_ms IS DISTINCT FROM m.anchor_ms OR q.tc_base_s IS DISTINCT FROM m.tc_base_s OR q.tc_inc_s IS DISTINCT FROM m.tc_inc_s
              OR lower(q.recipient_username) IS DISTINCT FROM lower(CASE WHEN q.recipient_color='white' THEN m.white_username ELSE m.black_username END)
              OR lower(q.opponent_username) IS DISTINCT FROM lower(CASE WHEN q.recipient_color='white' THEN m.black_username ELSE m.white_username END)''','Metadata identity/status/timing conflict')
            assert_zero(db,"SELECT count(*) FROM q JOIN m USING(game_id) WHERE (q.status IN ('draw','stalemate') AND m.winner IS NOT NULL) OR (q.status IN ('mate','resign') AND (m.winner IS NULL OR m.winner NOT IN ('white','black')))",'Invalid ordinary result; no available-case exclusion')
            ids=','.join(map(str,auth['authors']))
            assert_zero(db,f'SELECT count(*) FROM q WHERE recipient_id IN ({ids}) OR opponent_id IN ({ids}) OR (reached AND outcome_opponent IN ({ids}))','Author in ordinary frame or later decision')
            assert_zero(db,"SELECT count(*) FROM q WHERE NOT eligible_main OR NOT first_observed_pair OR NOT history_window_complete OR NOT complete90 OR recipient_id=opponent_id OR recipient_id<0 OR opponent_id<0",'Ordinary eligibility/identity failure')
            assert_zero(db,f'''SELECT count(*) FROM q WHERE y IS NULL OR reached IS NULL OR y NOT IN (0,1) OR reached NOT IN (0,1) OR (NOT reached AND y<>0)
              OR (reached AND (outcome_opponent IS NULL OR outcome_opponent<0 OR outcome_opponent=recipient_id OR outcome_opponent=opponent_id OR outcome_gid=game_id OR outcome_start<=anchor_ms OR outcome_t<=anchor_ms OR outcome_t>anchor_ms+{90*DAY}))''','Invalid future choice')
            numeric=['recipient_rating','opponent_rating','pre_games_90d','fair_90','kind_90','disconnect_90','receipt_90','claim_90','tc_base_s','tc_inc_s','month_code']
            assert_zero(db,'SELECT count(*) FROM q WHERE '+' OR '.join('NOT coalesce(isfinite('+x+'),FALSE)' for x in numeric)+' OR kind_90>fair_90 OR least(pre_games_90d,fair_90,kind_90,disconnect_90,receipt_90,claim_90)<0','Missing/invalid pregame covariate')
            assert_zero(db,'SELECT count(*) FROM q LEFT JOIN s USING(row_id) WHERE s.row_id IS NULL OR n_A<5 OR NOT coalesce(isfinite(adjusted_A),FALSE) OR NOT coalesce(isfinite(expected_A),FALSE)','Unsupported ordinary score')
            wanted=['row_id','game_id','recipient_id','opponent_id','outcome_opponent','outcome_gid','y','reached']+numeric
            raw='SELECT '+','.join(('q.'+x+'::INT AS '+x) if x in ('y','reached') else 'q.'+x for x in wanted)+",(q.status IN ('draw','stalemate'))::INT arm,s.n_A,s.adjusted_A,s.expected_A FROM q JOIN m USING(game_id) JOIN s USING(row_id) WHERE q.status IN ('draw','stalemate') OR m.winner<>q.recipient_color"
            db.execute('CREATE VIEW base AS '+raw)
            copy(db,'SELECT *, '+DERIVED+' FROM base ORDER BY row_id',tmp/'source.parquet')
            n=rows(tmp/'source.parquet');require(n>0,'No ordinary comparisons')
            counts=db.execute('SELECT arm,count(*),count(DISTINCT recipient_id),sum(y),sum(reached) FROM base GROUP BY arm ORDER BY arm').fetchall()
            result=dict(status='READY',rows=n,arms=[dict(arm=int(x[0]),rows=x[1],recipients=x[2],later_grants=x[3],later_choices=x[4]) for x in counts],
              definition='Corrected F frame; first observed pairs; all-time leave-pair-out score support >=5; complete pregame/follow-up 90 days; no receipt spacing. Ordinary draws: draw/stalemate with no winner. Ordinary losses: mate/resign with opposite-color winner.',
              history='90 days immediately before index start; volume uses the same 90 days',same_as_old_1290237_sample=False,estimator='Empirical-cell overlap weights; coarsened exact support',causal_identification=False)
            save(tmp/'summary.json',result);return dict(rows=n)
        finally:db.close()
    out,_=stage(root,conf,build,[paths[x] for x in ('frame','metadata','frame_scores')]);save(run/'report/ORDINARY_FRAME.json',read(out/'summary.json'));return out/'source.parquet'

def memberships(actors,influence):
    """Yield each distinct within-row account subset once, plus recipient sums."""
    ids=np.sort(np.asarray(actors,np.int64),axis=1)
    require(ids.ndim==2 and ids.shape[1]==3,'Three account roles required')
    for j in (2,1):ids[ids[:,j]==ids[:,j-1],j]=-1
    ids.sort(axis=1);u=np.asarray(influence,float)
    yield 0,np.column_stack((actors[:,0],np.full(len(ids),-1),np.full(len(ids),-1))),u
    for order in (1,2,3):
        for slots in itertools.combinations(range(3),order):
            valid=np.all(ids[:,slots]>=0,axis=1)
            if not valid.any():continue
            key=np.full((int(valid.sum()),3),-1,np.int64);key[:,:order]=ids[valid][:,slots]
            yield order,key,u[valid]

def covariance(influence_path,root,buckets=64):
    """Bounded inclusion-exclusion for rows sharing ANY of three accounts.

    Role changes and repeated identities are counted once. No full-sample
    influence or account dictionary is loaded. Two outcomes share the pass.
    """
    root=Path(root);root.mkdir(parents=True,exist_ok=True);writers={}
    try:
        for batch in pq.ParquetFile(influence_path).iter_batches(batch_size=32768,use_threads=False):
            d=batch.to_pydict();actors=np.column_stack([d[x] for x in ('recipient_id','opponent_id','future_id')])
            u=np.column_stack([d['if_y'],d['if_reached']])
            blocks=list(memberships(actors,u))
            order=np.concatenate([np.full(len(key),kind,np.int8) for kind,key,value in blocks])
            keys=np.vstack([key for kind,key,value in blocks]);values=np.vstack([value for kind,key,value in blocks])
            with np.errstate(over='ignore'):
                h=(keys[:,0].astype(np.uint64)*np.uint64(11400714819323198485))^(keys[:,1].astype(np.uint64)*np.uint64(14029467366897019727))^(keys[:,2].astype(np.uint64)*np.uint64(1609587929392839161))
            bucket=(h%np.uint64(buckets)).astype(np.int32)
            # One write per bucket/batch, not one per role-subset, avoiding
            # hundreds of thousands of tiny Parquet row groups on the Mac.
            for k in np.unique(bucket):
                take=bucket==k;t=pa.table(dict(order=order[take],a=keys[take,0],b=keys[take,1],c=keys[take,2],u=values[take,0],v=values[take,1]))
                k=int(k)
                if k not in writers:writers[k]=pq.ParquetWriter(root/f'{k:03}.parquet',t.schema,compression='zstd',use_dictionary=False)
                writers[k].write_table(t)
    finally:
        for w in writers.values():w.close()
    total=np.zeros((2,2));recipient=np.zeros((2,2));clusters=0
    db=connect(root/'spill',1.)
    try:
        for k in sorted(writers):
            p=root/f'{k:03}.parquet';view(db,'membership',p)
            answer=db.execute('SELECT "order",count(*),sum(u*u),sum(u*v),sum(v*v) FROM (SELECT "order",a,b,c,sum(u) u,sum(v) v FROM membership GROUP BY ALL) GROUP BY "order"').fetchall()
            for order,n,uu,uv,vv in answer:
                block=np.array([[uu,uv],[uv,vv]])
                if order==0:recipient+=block;clusters+=n
                else:total+=(1 if order%2 else -1)*block
            db.execute('DROP VIEW membership');p.unlink()
    finally:db.close()
    return total,recipient,clusters

def infer(beta,var,groups,n):
    ans=dict(estimate_pp=100*beta,standard_error_pp=None,ci95_low=None,ci95_high=None,p_value=None,
             inference_status='UNSUPPORTED_VARIANCE_OR_CLUSTER_COUNT')
    if np.isfinite(var) and var>0 and min(groups)>=30 and n>0:
        se=math.sqrt(var);ans.update(standard_error_pp=100*se,ci95_low=100*(beta-1.959963984540054*se),ci95_high=100*(beta+1.959963984540054*se),p_value=math.erfc(abs(beta/se)/math.sqrt(2)),inference_status='nominal_large_sample')
    return ans

def fit(a,run,conf,source,spec):
    root=run/'PRIVATE/ordinary_models'/spec
    cells=['recipient_id','speed_class'] if spec=='within_recipient' else [x for x in CELL if x!='speed_class']+['tc_base_s','tc_inc_s'] if spec=='exact_time_control' else CELL
    def build(tmp):
        db=connect(tmp,4.)
        try:
            view(db,'p',source);key="concat_ws('|',"+','.join(cells)+')'
            db.execute('CREATE VIEW k AS SELECT *,'+key+' cell FROM p')
            # Narrow grouped totals replace a wide window/sort of all frame rows.
            copy(db,'''SELECT cell,count(*) FILTER(WHERE arm=1) n1,count(*) FILTER(WHERE arm=0) n0,
              avg(y) FILTER(WHERE arm=1) y1,avg(y) FILTER(WHERE arm=0) y0,
              avg(reached::INT) FILTER(WHERE arm=1) r1,avg(reached::INT) FILTER(WHERE arm=0) r0
              FROM k GROUP BY cell HAVING n1>0 AND n0>0''',tmp/'cells.parquet')
            view(db,'s',tmp/'cells.parquet');ncells=rows(tmp/'cells.parquet');require(ncells>0,'No ordinary common support: '+spec)
            fields=['row_id','game_id','recipient_id','opponent_id','outcome_opponent','reached','y','arm']+BALANCE
            copy(db,'SELECT '+','.join('k.'+x for x in fields)+''',CASE WHEN arm=1 THEN n0::DOUBLE/(n1+n0) ELSE n1::DOUBLE/(n1+n0) END weight,
             (y1+y0)/2 my,(r1+r0)/2 mr FROM k JOIN s USING(cell)''',tmp/'selected.parquet')
            view(db,'d',tmp/'selected.parquet');n=rows(tmp/'selected.parquet');require(n>ncells+1,'No residual degrees of freedom')
            groups=db.execute('SELECT arm,count(*),count(DISTINCT recipient_id),sum(y),sum(reached::INT),sum(weight),sum(weight*weight),sum(weight*y)/sum(weight),sum(weight*reached::INT)/sum(weight) FROM d GROUP BY arm ORDER BY arm').fetchall()
            require(len(groups)==2 and np.isclose(groups[0][5],groups[1][5],rtol=1e-11),'Overlap weights are not balanced across arms')
            beta=np.array([groups[1][7]-groups[0][7],groups[1][8]-groups[0][8]])
            bread=(groups[0][5]+groups[1][5])/4
            copy(db,f'''SELECT recipient_id,opponent_id,CASE WHEN reached THEN outcome_opponent ELSE -1 END future_id,
              weight*(arm-.5)*(y-my-({beta[0]:.17g})*(arm-.5))/{bread:.17g} if_y,
              weight*(arm-.5)*(reached::INT-mr-({beta[1]:.17g})*(arm-.5))/{bread:.17g} if_reached FROM d''',tmp/'influence_PRIVATE.parquet')
            balance=[]
            # Small aggregate queries; Arrow never owns the selected population.
            for variable in BALANCE:
                raw=db.execute(f'SELECT arm,avg({variable}),var_pop({variable}) FROM p GROUP BY arm ORDER BY arm').fetchall()
                weighted=db.execute(f'SELECT arm,sum(weight*{variable})/sum(weight) FROM d GROUP BY arm ORDER BY arm').fetchall()
                sd=math.sqrt(max(0.,(raw[0][2]+raw[1][2])/2))
                balance.append(dict(variable=variable,raw_smd=(raw[1][1]-raw[0][1])/sd if sd else None,matched_smd=(weighted[1][1]-weighted[0][1])/sd if sd else None))
            support=[dict(arm=g[0],rows=g[1],recipients=g[2],grants=g[3],reached=g[4],weight_sum=g[5],effective_rows=g[5]**2/g[6],grant_rate_pp=g[7]*100,reach_rate_pp=g[8]*100) for g in groups]
        finally:db.close()
        V,Vr,clusters=covariance(tmp/'influence_PRIVATE.parquet',tmp/'covariance')
        adjustment=(n-1)/(n-ncells-1);V*=adjustment;Vr*=adjustment
        estimates=[]
        for k,outcome in enumerate(('y','reached')):
            ans=infer(beta[k],V[k,k],[groups[0][2],groups[1][2],clusters],n)
            ans.update(specification=spec,outcome=outcome,rows=n,strata=ncells,recipient_clusters=clusters,HC1_factor=adjustment,
              treated_mean_pp=groups[1][7+k]*100,loss_mean_pp=groups[0][7+k]*100,
              recipient_cluster_se_pp=100*math.sqrt(Vr[k,k]*clusters/(clusters-1)) if clusters>1 and Vr[k,k]>=0 else None)
            estimates.append(ans)
        result=dict(status='COMPLETE',estimates=estimates,support=support,balance=balance,cells=cells,
          covariance='Any shared account among recipient, index opponent and later-choice opponent; inclusion-exclusion HC1; no date clustering; fixed weights/cells',
          causal_identification=False,definition_change='Corrected all-time-supported F frame, no cooldown, 90-day immediate histories and volume',
          largest_absolute_matched_smd=max(abs(x['matched_smd']) for x in balance if x['matched_smd'] is not None))
        save(tmp/'result.json',result)
        # Keep keyed input/covariance evidence private; selected inputs reusable.
        return dict(rows=n,strata=ncells)
    out,_=stage(root,conf,build,[source]);return read(out/'result.json')

def run_all(a,run,conf,auth):
    source=prepare(a,run,conf,auth);est=[];support=[];balance=[]
    for spec in ('overlap','exact_time_control','within_recipient'):
        with heartbeat('Ordinary draw versus loss: '+spec):result=fit(a,run,conf,source,spec)
        save(run/'report'/('ORDINARY_'+spec+'.json'),result)
        est+=result['estimates'];support += [dict(specification=spec,**r) for r in result['support']];balance += [dict(specification=spec,**r) for r in result['balance']]
        public_csv(run/'report/ordinary_draw_vs_loss.csv',est);public_csv(run/'report/ordinary_support.csv',support);public_csv(run/'report/ordinary_balance.csv',balance)
