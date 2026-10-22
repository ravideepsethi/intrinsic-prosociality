"""Secondary observational dose models in the separate frozen receipt cohort."""
from common import *
from models import DERIVED,uncertainty,coefficient_row

def absorb(x,s):
    n=np.bincount(s)
    out=np.asarray(x,dtype=float).copy()
    if x.ndim==1:return out-(np.bincount(s,weights=x)/n)[s]
    for j in range(x.shape[1]):out[:,j]-=(np.bincount(s,weights=x[:,j])/n)[s]
    return out

def linear_fit(c,x,y,strata,actors,names,targets,n1,n0):
    """Absorb month x speed FE, standardize numerically, reject bad rank."""
    xr=absorb(x,strata);yr=absorb(y,strata);rms=np.sqrt(np.mean(xr*xr,axis=0))
    use=rms>1e-12;dropped=[names[j] for j in np.flatnonzero(~use)]
    if any(v in targets for v in dropped):return dict(status='TARGET_HAS_NO_WITHIN_STRATUM_VARIATION',dropped=dropped),[]
    names=[v for v,u in zip(names,use) if u];rms=rms[use];xr=xr[:,use]/rms
    gram=xr.T@xr;values=np.linalg.eigvalsh(gram)
    condition=float(values[-1]/values[0]) if values[0]>0 else float('inf')
    info=dict(rows=len(y),regressors=len(names),fixed_effects=int(strata.max()+1),
              standardized_gram_condition=condition,dropped_constant_controls=dropped)
    if condition>1e10 or not np.isfinite(condition):return dict(info,status='COLLINEAR_NOT_ESTIMATED'),[]
    inverse=np.linalg.inv(gram);b=inverse@(xr.T@yr);res=yr-xr@b
    info.update(status='ESTIMATED',residual_score_max=float(np.max(np.abs(xr.T@res))),
                potential_stakes_treated_as_fixed=True)
    estimates=[]
    for name in targets:
        j=names.index(name);influence=res*(xr@inverse[:,j])/rms[j]
        unc=uncertainty(c,actors,influence,len(names)+info['fixed_effects'])
        row=coefficient_row(float(b[j]/rms[j]),unc,n1,n0)
        row={k:v for k,v in row.items() if not k.startswith('ci95_inside')}
        row.update(term=name,units='percentage points per 5 rating points' if name!='received' else 'percentage points at centered stakes',
                   variance_inflation_factor=float(inverse[j,j]*len(y)),causal_interpretation=False)
        estimates.append(row)
    return info,estimates

def build_design(d,grant_only=False):
    n=len(d['y']);a=np.asarray(d['received'],float)
    center_g=float(np.mean(d['giver_cost']));center_b=float(np.mean(d['recipient_benefit']))
    g=(d['giver_cost']-center_g)/5;b=(d['recipient_benefit']-center_b)/5
    x={}
    if not grant_only:x['received']=a
    x.update(giver_cost_5=g,recipient_benefit_5=b)
    if not grant_only:x.update(received_x_giver_cost_5=a*g,received_x_recipient_benefit_5=a*b)
    x.update(recipient_rating_100=d['recipient_rating']/100,opponent_rating_100=d['opponent_rating']/100,
       log_giver_rd=np.log(d['giver_rd']),log_recipient_rd=np.log(d['recipient_rd']),
       log_pregames=d['log_pre_games'],log_fair90=d['log_fair90'],prior_kind_rate=d['prior_kind_rate'],
       fair_history_present=d['fair_history_present'],log_disconnect90=d['log_disconnect90'],
       log_receipt90=d['log_receipt90'],log_claim90=d['log_claim90'],
       opponent_leniency=d['adjusted_7d'],opponent_expected=d['expected_7d'],
       board_cp_capped600=np.clip(d['board_cp'],-600,600)/100,log_ply=np.log1p(d['ply']),
       log_giver_clock=np.log1p(np.maximum(0,d['giver_clock'])),
       log_recipient_clock=np.log1p(np.maximum(0,d['recipient_clock'])),
       giver_white=(d['chooser_color']=='white').astype(float))
    target=['giver_cost_5','recipient_benefit_5'] if grant_only else ['received','received_x_giver_cost_5','received_x_recipient_benefit_5']
    xx=np.column_stack(list(x.values()))
    if not np.isfinite(xx).all():raise RuntimeError('Invalid dose regressor; no silent complete-case deletion')
    _,s=np.unique(np.column_stack([d['month_code'],d['speed_class']]),axis=0,return_inverse=True)
    actors=np.column_stack([d['recipient_id'],d['opponent_id'],np.where(d['reached']==1,d['outcome_opponent'],-1)])
    centers=dict(giver_cost_mean=center_g,recipient_benefit_mean=center_b,
                 stake_correlation=float(np.corrcoef(d['giver_cost'],d['recipient_benefit'])[0,1]),
                 giver_stake_rd_correlation=float(np.corrcoef(d['giver_cost'],d['giver_rd'])[0,1]),
                 recipient_stake_rd_correlation=float(np.corrcoef(d['recipient_benefit'],d['recipient_rd'])[0,1]))
    return xx,list(x),target,s,actors,centers

def dose_models(paths,work,key,threads,memory):
    blocked=[str(p) for p in paths if read(Path(p)/'secondary_status.json')['status']!='VERIFIED']
    if blocked:raise RuntimeError('Secondary dose cohort is not fully verified; partial-cohort fitting is prohibited')
    c=conn(Path(work)/'spill/dose',threads,max(1,memory*.4));outs=[]
    try:
        c.execute('CREATE VIEW raw AS SELECT * FROM '+scan([Path(p)/'dose.parquet' for p in paths]))
        cols=['recipient_id','opponent_id','outcome_opponent','reached','y','received','month_code',
            'recipient_rating','opponent_rating','adjusted_7d','expected_7d','chooser_color',
            'giver_cost','recipient_benefit','giver_rd','recipient_rd','board_cp','ply','giver_clock',
            'recipient_clock','log_pre_games','log_fair90','prior_kind_rate','fair_history_present',
            'log_disconnect90','log_receipt90','log_claim90','speed_class']
        c.execute('CREATE VIEW enriched AS SELECT *, '+DERIVED+' FROM raw')
        for scope in ('all_rd','both_rd_le_110'):
            for model in ('receipt_interactions','grants_only'):
                name=scope+'__'+model;out=Path(work)/'dose_models'/name;out.mkdir(parents=True,exist_ok=True);outs.append(out)
                if checkpoint_ok(out,key):continue
                where='TRUE' if scope=='all_rd' else 'giver_rd<=110 AND recipient_rd<=110'
                if model=='grants_only':where+=' AND received=1'
                with heartbeat('Secondary stake model: '+name):
                    d=arrays(c.execute('SELECT '+','.join(cols)+' FROM enriched WHERE '+where).to_arrow_table())
                    if len(d['y'])<100:
                        write(out/'summary.json',dict(status='INSUFFICIENT_ROWS',rows=len(d['y'])));finish(out,key);continue
                    x,names,targets,s,actors,centers=build_design(d,model=='grants_only')
                    a=d['received']==1;n1=np.unique(d['recipient_id'][a]).size
                    n0=np.unique(d['recipient_id'][~a]).size if model!='grants_only' else n1
                    summary=dict(scope=scope,model=model,centering=centers,rows=len(d['y']),grants=int(a.sum()),
                        causal_interpretation=False,selected_on_grant=model=='grants_only',
                        recipient_benefit_definition='Recipient-side win-minus-draw premium; draw-minus-loss under the frozen common-scale replay representation, not a newly simulated realized rating change',
                        gift_awareness_observed=False,generated_scores_and_potential_stakes_fixed=True)
                    es=[]
                    for outcome in ('y','reached'):
                        fit,est=linear_fit(c,x,np.asarray(d[outcome],float),s,actors,names,targets,n1,n0)
                        summary[outcome]=fit;es += [dict(r,outcome=outcome) for r in est]
                    write(out/'summary.json',summary);write(out/'estimates.json',es);csvwrite(out/'estimates.csv',es)
                    bins=[]
                    for stake in ('giver_cost','recipient_benefit'):
                        for arm in (0,1):
                            use=d['received']==arm
                            if not np.any(use):continue
                            values=d[stake][use];edges=np.unique(np.quantile(values,[.25,.5,.75]));j=np.searchsorted(edges,values,side='right')
                            for b in np.unique(j):
                                ix=np.flatnonzero(use)[j==b]
                                bins.append(dict(stake=stake,arm=arm,bin=int(b),rows=len(ix),stake_mean=float(d[stake][ix].mean()),
                                  stake_min=float(d[stake][ix].min()),stake_max=float(d[stake][ix].max()),
                                  kind_percent=float(d['y'][ix].mean()*100),reached_percent=float(d['reached'][ix].mean()*100),
                                  giver_rd_mean=float(d['giver_rd'][ix].mean()),recipient_rd_mean=float(d['recipient_rd'][ix].mean())))
                    csvwrite(out/'unadjusted_dose_bins.csv',bins);finish(out,key)
    finally:c.close()
    return outs
