"""Observed pair contact, explicit unknown-source bounds, and matched comparisons."""
from core import *
import math

CATEGORIES=['all','rated','casual','nonpool','rated_nonpool','casual_nonpool','friend_source','pool_source','organized','lobby']
PERIODS=['pre90','post7','post30','post90','post180','late7to90','after1h90']
BINARY=[f'{p}_{c}' for p in PERIODS for c in CATEGORIES]+[f'post{h}_{m}' for h in (90,180) for m in ('two_days','span7days','nonpool_two_days','nonpool_span7days')]
CONTINUOUS=[f'post{h}_{m}' for h in (7,30,90,180) for m in ('games','days')]
PRIMARY=['post90_nonpool','post90_casual','post90_nonpool_two_days']

def category_bounds(g,cat):
    source=g['source'];rated=g['rated']
    if cat=='all':return True,True
    if cat=='rated':return rated,rated
    if cat=='casual':return not rated,not rated
    if cat=='rated_nonpool' and not rated:return False,False
    if cat=='casual_nonpool' and rated:return False,False
    if source is None:return False,True
    if cat in ('nonpool','rated_nonpool','casual_nonpool'):yes=source!='pool'
    elif cat=='friend_source':yes=source=='friend'
    elif cat=='pool_source':yes=source=='pool'
    elif cat=='organized':yes=source in ('tournament','swiss','simul')
    elif cat=='lobby':yes=source=='lobby'
    else:raise ValueError(cat)
    return yes,yes

def in_period(g,t,p):
    at=g['created']
    if p=='pre90':return t['start']-90*DAY<=at<t['start']
    if p=='late7to90':return t['anchor']+7*DAY<at<=t['anchor']+90*DAY
    if p=='after1h90':return t['anchor']+3600000<at<=t['anchor']+90*DAY
    return t['anchor']<at<=t['anchor']+int(p[4:])*DAY

def outcomes(t,games):
    out={}
    if games is None:
        for k in BINARY:out[k+'_lo']=0;out[k+'_hi']=1
        for k in CONTINUOUS:out[k]=None
        return dict(**out,history_available=False,unknown_source_games=None)
    games=[g for g in games if g['gid']!=t['gid'] and g['status'] not in ('created','aborted','noStart') and g['source'] not in ('import','importlive','relay')]
    for p in PERIODS:
        gg=[g for g in games if in_period(g,t,p)]
        for cat in CATEGORIES:
            bb=[category_bounds(g,cat) for g in gg]
            out[p+'_'+cat+'_lo']=int(any(v[0] for v in bb));out[p+'_'+cat+'_hi']=int(any(v[1] for v in bb))
    for h in (7,30,90,180):
        gg=[g for g in games if in_period(g,t,'post'+str(h))];times=[g['created'] for g in gg]
        days=len({x//DAY for x in times});out[f'post{h}_games']=len(gg);out[f'post{h}_days']=days
        if h in (90,180):
            for m,v in [('two_days',days>=2),('span7days',len(times)>1 and max(times)-min(times)>=7*DAY)]:
                out[f'post{h}_{m}_lo']=out[f'post{h}_{m}_hi']=int(v)
            for suffix,bound in [('lo',0),('hi',1)]:
                tt=[g['created'] for g in gg if category_bounds(g,'nonpool')[bound]]
                out[f'post{h}_nonpool_two_days_'+suffix]=int(len({x//DAY for x in tt})>=2)
                out[f'post{h}_nonpool_span7days_'+suffix]=int(len(tt)>1 and max(tt)-min(tt)>=7*DAY)
    return dict(**out,history_available=True,unknown_source_games=sum(g['source'] is None for g in games))

def covariates(t):
    vals=[np.clip(t['cp'],-2000,2000)/1000,t['rating']/1000,t['opp_rating']/1000,t['rd']/100,t['opp_rd']/100,t['cost']/10,t['draw_payoff']/10,
      t['start']/DAY/90,t['ply']/50,np.log1p(t['jvolume']),np.log1p(t['ivolume']),np.log1p(t['base']),np.log1p(t['inc'])]
    for name in ('clock','opp_clock'):
        z=t[name];good=z is not None and np.isfinite(z);vals += [np.log1p(max(0,z)) if good else 0,float(not good)]
    return np.array(vals,float)

def paired_fit(delta,givers,dx=None):
    """Intercept in a matched difference regression; chooser-clustered covariance."""
    y=np.asarray(delta,float);givers=np.asarray(givers);n=len(y)
    base=dict(matched_sets=n,chooser_clusters=len(np.unique(givers)),causal=False)
    if n<30:return dict(**base,supported=False,reason='Fewer than 30 usable matched sets')
    x=np.ones((n,1))
    if dx is not None:
        z=np.asarray(dx,float);sd=z.std(axis=0);z=z[:,sd>1e-10]/sd[sd>1e-10]
        x=np.column_stack([x,z])
    rank=np.linalg.matrix_rank(x)
    if rank<x.shape[1]:
        # Reduce linearly redundant controls without changing their column space.
        keep=[0]
        for k in range(1,x.shape[1]):
            if np.linalg.matrix_rank(x[:,keep+[k]])>len(keep):keep.append(k)
        x=x[:,keep]
    b=np.linalg.lstsq(x,y,rcond=None)[0];u=y-x@b;bread=np.linalg.inv(x.T@x)
    codes=np.unique(givers,return_inverse=True)[1];G=int(codes.max()+1)
    score=x*u[:,None];sums=np.column_stack([np.bincount(codes,weights=score[:,k]) for k in range(x.shape[1])])
    var=(bread@sums.T@sums@bread)[0,0]*(G/(G-1) if G>1 else np.nan)
    if not np.isfinite(var) or var<=1e-20:return dict(**base,supported=False,estimate=float(b[0]),reason='No supported sampling variance; not interpreted as precise zero')
    se=math.sqrt(var)
    return dict(**base,supported=True,estimate=float(b[0]),se=se,ci95_low=float(b[0]-1.959964*se),ci95_high=float(b[0]+1.959964*se),
      p=math.erfc(abs(b[0]/se)/math.sqrt(2)),covariance='Chooser clustered, G/(G-1) correction',controls=x.shape[1]-1)

def analyze(rows,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    sets={}
    for r in rows:sets.setdefault(r['match_id'],{})[bool(r['y'])]=r
    full=[v for v in sets.values() if len(v)==2]
    coverage=[]
    for arm in (True,False):
        rr=[r for r in rows if r['y']==arm]
        coverage.append(dict(initial_action='grant' if arm else 'claim',selected_events=len(rr),
          available_histories=sum(r['history_available'] for r in rr),unavailable_histories=sum(not r['history_available'] for r in rr),
          histories_with_unknown_source=sum(r['unknown_source_games'] is not None and r['unknown_source_games']>0 for r in rr)))
    table_csv(coverage,folder/'COVERAGE.csv')
    # Bounds use every selected set, including failed requests. Complete-case fits stay explicit.
    outcomes_table=[];estimates=[];balance=[]
    for cohort in ('all_matched','no_observed_pre90_contact'):
        pairs0=full if cohort=='all_matched' else [v for v in full if all(r['history_available'] and r['pre90_all_hi']==0 for r in v.values())]
        if not pairs0:continue
        a=[v[True] for v in pairs0];b=[v[False] for v in pairs0];N=len(a)
        for key in BINARY:
            lo0=np.array([r[key+'_lo'] for r in a]);hi0=np.array([r[key+'_hi'] for r in a]);lo1=np.array([r[key+'_lo'] for r in b]);hi1=np.array([r[key+'_hi'] for r in b])
            known=(lo0==hi0)&(lo1==hi1)&np.array([u['history_available'] and v['history_available'] for u,v in zip(a,b)])
            outcomes_table.append(dict(cohort=cohort,outcome=key,selected_matched_sets=N,known_matched_sets=int(known.sum()),
              contact_after_grant_lower_pct=100*float(lo0.mean()),contact_after_grant_upper_pct=100*float(hi0.mean()),
              contact_after_claim_lower_pct=100*float(lo1.mean()),contact_after_claim_upper_pct=100*float(hi1.mean()),
              difference_lower_pp=100*float((lo0-hi1).mean()),difference_upper_pp=100*float((hi0-lo1).mean())))
            # Short windows and source categories are descriptive; fit the declared main measures and timing checks.
            if key not in PRIMARY+['post90_friend_source','post90_rated_nonpool','post90_casual_nonpool','late7to90_nonpool','post180_nonpool','post180_casual','post180_span7days','pre90_casual','pre90_nonpool']:continue
            aa=[r for r,z in zip(a,known) if z];bb=[r for r,z in zip(b,known) if z]
            delta=(lo0-lo1)[known].astype(float);giver=[r['j'] for r in aa]
            for adjusted in (False,True):
                if adjusted and aa:
                    dx=np.array([covariates(u)-covariates(v) for u,v in zip(aa,bb)])
                    # Only predetermined prior contact is added, never future behavior.
                    if not key.startswith('pre'):
                        prior=np.array([[u['pre90_all_lo']-v['pre90_all_lo'],u['pre90_casual_lo']-v['pre90_casual_lo']] for u,v in zip(aa,bb)])
                        dx=np.column_stack([dx,prior])
                    ok=np.isfinite(dx).all(axis=1)
                else:dx=None;ok=np.ones(len(delta),bool)
                ans=paired_fit(delta[ok],np.array(giver)[ok],dx[ok] if dx is not None else None)
                estimates.append(dict(cohort=cohort,outcome=key,adjusted=adjusted,**{k:(100*v if k in ('estimate','se','ci95_low','ci95_high') else v) for k,v in ans.items()},units='percentage points'))
        for k in ('rating','opp_rating','rd','opp_rd','cp','cost','jvolume','ivolume','ply'):
            z0=np.array([r[k] for r in a],float);z1=np.array([r[k] for r in b],float);den=np.sqrt((np.nanvar(z0)+np.nanvar(z1))/2)
            balance.append(dict(cohort=cohort,covariate=k,grant_mean=float(np.nanmean(z0)),claim_mean=float(np.nanmean(z1)),standardized_difference=float((np.nanmean(z0)-np.nanmean(z1))/den) if den else None))
    main=sorted([r for r in estimates if r['cohort']=='all_matched' and r['adjusted'] and r['outcome'] in PRIMARY and r['supported']],key=lambda r:r['p'])
    prev=0
    for k,r in enumerate(main):prev=max(prev,min(1.,(3-k)*r['p']));r['p_Holm_three_primary']=prev
    table_csv(outcomes_table,folder/'contact_rates_and_missing_bounds.csv');table_csv(estimates,folder/'matched_estimates.csv');dump(folder/'matched_estimates.json',estimates);table_csv(balance,folder/'balance.csv')
    counts=[]
    for key in CONTINUOUS:
        ok=[v for v in full if v[True][key] is not None and v[False][key] is not None]
        if ok:counts.append(dict(outcome=key,complete_matched_sets=len(ok),after_grant_mean=float(np.mean([v[True][key] for v in ok])),after_claim_mean=float(np.mean([v[False][key] for v in ok]))))
    table_csv(counts,folder/'contact_counts.csv')
    return dict(selected_events=len(rows),matched_sets=len(full),successful_histories=sum(r['history_available'] for r in rows),
      failed_histories=sum(not r['history_available'] for r in rows),friendship_edges='NOT_OBSERVED; game source friend is not a follow relationship',
      interpretation='Matched descriptive comparison within chooser. Granting is not randomly assigned; relationship formation does not establish anticipated motives.')
