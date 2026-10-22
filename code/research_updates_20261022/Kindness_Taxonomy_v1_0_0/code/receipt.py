"""C2/C3: joint subgroup IV with covariance of the difference; H presentation."""
from common import *
from vendor.rct.cache import bind_cache,open_data,load_scope
from vendor.rct.iv import augment,fit_iv,date_covariance,REFERENCE_SD
from vendor.rct.numerics import codes,absorb,contrast

def prepare(c,project,work,workers):
    try:
        binding=bind_cache(project,Path(work)/'receipt_binding',workers)
        counts=open_data(c,binding);d=load_scope(c,'all_rd');d,source=augment(c,binding,project,work,d)
    except FileNotFoundError as e:raise Unavailable('Authenticated receipt cache not available: '+str(e))
    bridge=records(c,'''SELECT count(*) AS rows_checked,
      count(*) FILTER(WHERE p.game_id IS NULL OR r.recipient_id IS DISTINCT FROM p.recipient
        OR r.opponent_id IS DISTINCT FROM p.chooser OR r.received IS DISTINCT FROM p.y
        OR r.board_cp IS DISTINCT FROM p.cp OR r.anchor_ms IS DISTINCT FROM p.end_ms) invalid
      FROM raw r LEFT JOIN panel p USING(game_id)''')[0]
    if bridge['rows_checked']!=len(d['y']) or bridge['invalid']:
        raise RuntimeError('Receipt and main-panel ID/treatment/position/time bridge failed: '+str(bridge))
    # One-to-one linkage: no new cohort, no respacing, no alteration of the score.
    sql='''SELECT r.row_id,coalesce(h.grants_before,0)::BIGINT grants_before,
      coalesce(h.screens_before,0)::BIGINT screens_before,coalesce(h.receipts_before,0)::BIGINT receipts_before,
      h.last_screen_ms FROM raw r ASOF LEFT JOIN histories h
      ON r.recipient_id=h.account AND r.archive_start_ms>h.available_ms ORDER BY r.row_id'''
    a=arrays(c.execute(sql).to_arrow_table())
    if not np.array_equal(a.pop('row_id'),d['row_id']):raise RuntimeError('Receipt history alignment failed')
    d.update(a)
    return d,dict(binding=binding,counts=counts,source=source,main_panel_bridge=bridge)

def controls(d):
    gap=(d['opponent_rating']-d['recipient_rating'])/100.
    x=dict(recipient_rating=d['recipient_rating']/100,rating_gap=gap,rating_gap_square=gap**2,abs_rating_gap=abs(gap),
      log_opponent_prior_decisions=np.log1p(d['n_7d']),log_opponent_prior_counterparts=np.log1p(d['counterparts_7d']),
      opponent_history_expected_rate=d['expected_7d'],fair_history_present_90=d['fair_history_present'],log_fair_90=d['log_fair90'],
      kind_ever_90=(d['prior_kind_rate']>0).astype(float),kind_rate_90=d['prior_kind_rate'],log_disconnect_90=d['log_disconnect90'],
      log_receipt_90=d['log_receipt90'],log_volume_30=d['log_pre_games'],log_claim_90=d['log_claim90'])
    cell=np.unique(np.column_stack([d['month_code'],d['tc_base_s'],d['tc_inc_s'],np.floor((d['recipient_rating']+d['opponent_rating'])/200)]),axis=0,return_inverse=True)[1]
    dates=d['archive_start_ms']//DAY;hour=(d['archive_start_ms']//3600000)%168
    return np.column_stack(list(x.values())),list(x),[cell,codes(dates),codes(hour)],dates

def subgroup_fit(c,d,subgroup,labels,outcomes=None):
    x,names,groups,dates=controls(d);m=np.column_stack([subgroup==j for j in range(len(labels))]).astype(float)
    # Separate control slopes and FEs within strata reproduce separate subgroup designs
    # while the single covariance accounts for shared accounts/dates across strata.
    if len(labels)>1:
        x=np.column_stack([x*m[:,j,None] for j in range(len(labels))]);names=[f'{s}[{label}]' for label in labels for s in names]
        groups=[codes(g*len(labels)+subgroup) for g in groups]
    endo=m*d['received'][:,None];z=m*(d['adjusted_7d']/REFERENCE_SD)[:,None]
    outcomes=outcomes if outcomes is not None else np.column_stack([d['y'],d['reached']])
    info,fit=fit_iv(c,x,endo,z,outcomes,groups,np.column_stack([d['recipient_id'],d['opponent_id']]),dates,names)
    return info,fit

def split_run(c,d,folder,name,subgroup,labels):
    support=[]
    for j,label in enumerate(labels):
        m=subgroup==j;support.append(dict(group=label,n=int(m.sum()),receipts=int(d['received'][m].sum()),kind_events=int(d['y'][m].sum()),
          recipients=len(np.unique(d['recipient_id'][m])),reached=int(d['reached'][m].sum())))
    csvwrite(folder/f'{name}_support.csv',support)
    if any(r['n']<2000 or r['receipts']<10 or r['kind_events']<10 for r in support):
        write(folder/f'{name}_fit.json',dict(status='INSUFFICIENT_SUBGROUP_SUPPORT'));return
    info,fit=subgroup_fit(c,d,subgroup,labels);write(folder/f'{name}_fit.json',info);rows=[];cov=[]
    if fit is not None and fit['coefficients'] is not None:
        for o,outcome in enumerate(['y','reached']):
            weights=[(label,np.eye(len(labels))[j]) for j,label in enumerate(labels)]
            if len(labels)==2:weights.append(('group1_minus_group0',np.array([-1.,1.])))
            for label,w in weights:
                r=contrast(fit['coefficients'][:,o],fit['covariances'][o],w)
                rows.append(dict(group=label,outcome=outcome,**r,events_per_1000_receipts=r['estimate_pp']*10,
                   per_1000_low=(r.get('ci95_low_pp') or 0)*10 if r.get('ci95_low_pp') is not None else None,
                   per_1000_high=r.get('ci95_high_pp',0)*10 if r.get('ci95_high_pp') is not None else None))
            for j,a in enumerate(labels):
                for k,b in enumerate(labels):cov.append(dict(outcome=outcome,group_i=a,group_j=b,covariance_pp2=10000*fit['covariances'][o][j,k]))
    csvwrite(folder/f'{name}_estimates.csv',rows);csvwrite(folder/f'{name}_covariance.csv',cov)

def conversion(c,d,folder):
    split_run(c,d,folder,'C2_prior_grants',(d['grants_before']>0).astype(int),['no_prior_observed_grant','prior_observed_grant'])
    split_run(c,d,folder,'C3_prior_screens',(d['screens_before']>0).astype(int),['no_prior_observed_opportunity','prior_observed_opportunity'])
    split_run(c,d,folder,'G1_receipt_year',(d['archive_start_ms']>=SPLIT).astype(int),['year1','year2'])
    write(folder/'C23_method.json',dict(history='Strictly prior observed pool/nonadjacent main-panel grants and opportunities; five-minute availability guard',
      estimand='Next different-opponent competitive-choice kind act within 90 days; nonreachers zero, reached reported separately',
      controls='Authenticated rich headline controls and fixed effects, all interacted with subgroup',
      instrument='Original pooled adjusted_7d score at fixed reference SD; no score as included control',
      covariance='Shared exposure account OR exposure date CR0; joint cross-group difference',
      caveat='No prior observed grants is not never having granted, and no observed screen is not ignorance of the option. Conditional IV assumptions still apply.'))

def deciles(c,d,folder):
    z=d['adjusted_7d'];edges=np.unique(np.quantile(z,np.arange(.1,1,.1)));g=np.searchsorted(edges,z,side='right');K=len(edges)+1
    raw=[]
    for j in range(K):
        a=g==j;raw.append(dict(decile=j,n=int(a.sum()),score_mean=float(z[a].mean()) if a.any() else None,receipt_pct=100*float(d['received'][a].mean()) if a.any() else None,kind_pct=100*float(d['y'][a].mean()) if a.any() else None))
    csvwrite(folder/'H_raw_score_deciles.csv',raw)
    x,names,groups,dates=controls(d);bins=np.column_stack([(g==j).astype(float) for j in range(1,K)]);ys=np.column_stack([d['received'],d['y']])
    a,iterations,_=absorb(np.column_stack([x,bins,ys]),groups,compute_rank=False);P=x.shape[1];xr=a[:,:P];rest=a[:,P:]
    rms=np.sqrt(np.mean(xr*xr,axis=0));use=rms>1e-12;xr=xr[:,use]/rms[use]
    qx=xr.T@xr
    if np.linalg.cond(qx)>1e10:raise Unavailable('Decile control design lacks rank')
    rest=rest-xr@np.linalg.solve(qx,xr.T@rest);b=rest[:,:K-1];y=rest[:,K-1:];gram=b.T@b
    if np.linalg.cond(gram)>1e10:raise Unavailable('Score ties leave unsupported decile contrasts')
    inv=np.linalg.inv(gram);coef=inv@(b.T@y);deriv=b@inv;rows=[]
    for o,outcome in enumerate(['first_stage','reduced_form']):
        V=date_covariance(c,np.column_stack([d['recipient_id'],d['opponent_id']]),dates,deriv*(y[:,o]-b@coef[:,o])[:,None])
        rows.append(dict(outcome=outcome,decile=0,estimate_pp=0,reference=True))
        for j in range(1,K):rows.append(dict(outcome=outcome,decile=j,reference=False,**contrast(coef[:,o],V,np.eye(K-1)[j-1])))
    csvwrite(folder/'H_adjusted_score_deciles.csv',rows);write(folder/'H_decile_definition.json',dict(cutpoints=edges,ties='Preserved, so bins may have unequal sizes or collapse',
      adjusted_plot='Differences from lowest score bin with rich headline controls/FE; bins are descriptive, not a linear IV estimate'))

def dynamics(c,d,folder):
    # Exposure windows are frozen; all competitive subsequent opportunities count.
    query=f'''SELECT r.row_id,
       count(p.game_id) FILTER(WHERE p.end_ms<=r.anchor_ms+{7*DAY}) opp_0_7,
       coalesce(sum(p.y) FILTER(WHERE p.end_ms<=r.anchor_ms+{7*DAY}),0)::BIGINT kind_0_7,
       count(p.game_id) FILTER(WHERE p.end_ms>r.anchor_ms+{7*DAY} AND p.end_ms<=r.anchor_ms+{30*DAY}) opp_7_30,
       coalesce(sum(p.y) FILTER(WHERE p.end_ms>r.anchor_ms+{7*DAY} AND p.end_ms<=r.anchor_ms+{30*DAY}),0)::BIGINT kind_7_30,
       count(p.game_id) FILTER(WHERE p.end_ms>r.anchor_ms+{30*DAY}) opp_30_90,
       coalesce(sum(p.y) FILTER(WHERE p.end_ms>r.anchor_ms+{30*DAY}),0)::BIGINT kind_30_90
       FROM raw r LEFT JOIN panel p ON r.recipient_id=p.chooser AND p.recipient<>r.opponent_id
        AND p.state>=2 AND p.start_ms>r.anchor_ms AND p.end_ms<=r.anchor_ms+{90*DAY}
       GROUP BY r.row_id ORDER BY r.row_id'''
    vals=arrays(c.execute(query).to_arrow_table())
    if not np.array_equal(vals.pop('row_id'),d['row_id']):raise RuntimeError('Dynamic window alignment failed')
    names=list(vals);y=np.column_stack([vals[n] for n in names]);info,fit=subgroup_fit(c,d,np.zeros(len(y),int),['pooled'],y)
    write(folder/'H_dynamic_fit.json',info);rows=[]
    if fit is not None and fit['coefficients'] is not None:
        for j,name in enumerate(names):
            est=fit['coefficients'][0,j];se=np.sqrt(fit['covariances'][j][0,0]) if fit['covariances'][j][0,0]>0 else np.nan
            days=7 if name.endswith('0_7') else 23 if name.endswith('7_30') else 60
            rows.append(dict(outcome=name,units='events per 1000 receipts',days=days,**interval(1000*est,1000*se),
              effect_per_1000_per_day=1000*est/days))
    csvwrite(folder/'H_dynamic_counts.csv',rows)
    write(folder/'H_dynamic_method.json',dict(windows='(0,7], (7,30], (30,90] elapsed days from receipt anchor; game start after anchor',
      events='All observed subsequent competitive main-panel choices against a different opponent; kind act and opportunity counts',
      comparison='Unequal-length windows; per-day values supplied. No test across windows is inferred from separate intervals.',
      interpretation='Counts per exposure; not a conditional generosity probability or permanent conversion estimate'))
