"""Position profile first, with jointly adjusted stakes and full covariance."""
from .common import *
from .cache import row_hash
from .numerics import codes,fit_ols,contrast

BANDS=['[-100,0)','[0,100)','[100,300)','[300,infinity)']
def size(d,use):
    a=np.asarray(d['received'],bool);r=d['recipient_id'];idx=np.flatnonzero(use)
    ids=r[idx];unique,inv=np.unique(ids,return_inverse=True)
    ng=np.bincount(inv,weights=a[idx],minlength=len(unique));n=np.bincount(inv,minlength=len(unique))
    return dict(rows=len(idx),recipients=len(unique),grants=int(a[idx].sum()),claims=int((~a[idx]).sum()),
      grant_recipients=len(np.unique(ids[a[idx]])),claim_recipients=len(np.unique(ids[~a[idx]])),
      treatment_switchers=int(((ng>0)&(ng<n)).sum()),kind_events=int(d['y'][idx].sum()),reach_events=int(d['reached'][idx].sum()),
      receipt_percent=100*float(a[idx].mean()) if len(idx) else None,
      kindness_percent=100*float(d['y'][idx].mean()) if len(idx) else None,
      reach_percent=100*float(d['reached'][idx].mean()) if len(idx) else None,
      month_speed_cells=len(np.unique(d['month_code'][idx]*4+d['speed_class'][idx])))

def sample_info(d,scope):
    n=len(d['y'])
    def corr(a,b):return float(np.corrcoef(a,b)[0,1]) if len(a)>1 and np.std(a)>0 and np.std(b)>0 else None
    return dict(scope=scope,sample_sha256=row_hash(d),**size(d,np.ones(n,bool)),
      correlations=dict(giver_cost_recipient_benefit=corr(d['giver_cost'],d['recipient_benefit']),
        giver_cost_giver_rd=corr(d['giver_cost'],d['giver_rd']),recipient_benefit_recipient_rd=corr(d['recipient_benefit'],d['recipient_rd'])),
      band_counts=[int(np.sum(d['band']==k)) for k in range(4)],
      both_arms_per_band=[size(d,d['band']==k) for k in range(4)],position_orientation='recipient; positive means ahead',
      generator='Receipt_Mechanisms_v1_0_1 dose.parquet',selected_on_outcome=False)

def audit(d,scope):
    n=len(d['y']);sample_hash=row_hash(d);sample=[];balance=[]
    for band in [-1,0,1,2,3]:
        base=np.ones(n,bool) if band==-1 else d['band']==band
        for arm in [-1,0,1]:
            use=base if arm==-1 else base&(d['received']==arm)
            tag=dict(scope=scope,band='all' if band==-1 else BANDS[band],arm='all' if arm==-1 else arm,sample_sha256=sample_hash)
            s=size(d,use);s.update(tag)
            s['receipt_count_supported']=s['grants']>=20 if arm==-1 else None
            s['independent_arms_supported']=min(s['grant_recipients'],s['claim_recipients'])>=30 if arm==-1 else None
            sample.append(s)
            for col in ('giver_cost','recipient_benefit','giver_rd','recipient_rd','recipient_rating','opponent_rating','board_cp','ply','giver_clock','recipient_clock'):
                x=np.asarray(d[col][use],float);row=dict(tag,variable=col,rows=len(x))
                if len(x):
                    v=np.quantile(x,[0,.25,.5,.75,1]);row.update(mean=float(x.mean()),sd=float(x.std()),minimum=v[0],q25=v[1],median=v[2],q75=v[3],maximum=v[4])
                balance.append(row)
    return sample,balance,sample_info(d,scope)

def control_dict(d):
    return dict(recipient_rating_100=d['recipient_rating']/100,opponent_rating_100=d['opponent_rating']/100,
      log_giver_rd=np.log(d['giver_rd']),log_recipient_rd=np.log(d['recipient_rd']),
      log_pregames=d['log_pre_games'],log_fair90=d['log_fair90'],prior_kind_rate=d['prior_kind_rate'],
      fair_history_present=d['fair_history_present'],log_disconnect90=d['log_disconnect90'],
      log_receipt90=d['log_receipt90'],log_claim90=d['log_claim90'],
      opponent_leniency=d['adjusted_7d'],opponent_expected=d['expected_7d'],
      board_cp_capped600=np.clip(d['board_cp'],-600,600)/100,log_ply=np.log1p(d['ply']),
      log_giver_clock=np.log1p(np.maximum(0,d['giver_clock'])),
      log_recipient_clock=np.log1p(np.maximum(0,d['recipient_clock'])),
      giver_white=(d['chooser_color']=='white').astype(float))

def design(d,mode='joint',within=False):
    a=np.asarray(d['received'],float);band=d['band'];gc=float(d['giver_cost'].mean());bc=float(d['recipient_benefit'].mean())
    g=(d['giver_cost']-gc)/5;b=(d['recipient_benefit']-bc)/5
    x={f'received_band_{k}':a*(band==k) for k in range(4)};targets=list(x)
    x.update(giver_cost_5=g,recipient_benefit_5=b)
    cuts=None;tercile=None
    if mode=='terciles':
        cuts=np.quantile(d['giver_cost'],[1/3,2/3]);tercile=np.searchsorted(cuts,d['giver_cost'],side='right')
        if cuts[0]>=cuts[1] or len(np.unique(tercile))!=3:raise ValueError('TERCILES_UNSUPPORTED_TIES')
        for k in (1,2):
            x[f'received_tercile_{k}']=a*(tercile==k);targets.append(f'received_tercile_{k}')
            x[f'tercile_{k}']=(tercile==k).astype(float)
    elif mode!='drop_cost':x['received_x_giver_cost_5']=a*g;targets.append('received_x_giver_cost_5')
    if mode!='drop_benefit':x['received_x_recipient_benefit_5']=a*b;targets.append('received_x_recipient_benefit_5')
    for k in (1,2,3):x[f'band_{k}']=(band==k).astype(float)
    x.update(control_dict(d))
    groups=[codes(d['month_code']*4+d['speed_class'])]
    if within:groups.append(codes(d['recipient_id']))
    actors=np.column_stack([d['recipient_id'],d['opponent_id'],np.where(d['reached']==1,d['outcome_opponent'],-1)])
    meta=dict(giver_cost_mean=gc,recipient_benefit_mean=bc,giver_cost_iqr=float(np.diff(np.quantile(d['giver_cost'],[.25,.75]))[0]),
      tercile_cut_points=cuts,stake_scale_rating_points=5,position_band_labels=BANDS,
      fixed_effects=['month_x_speed']+(['recipient'] if within else []))
    return np.column_stack(list(x.values())),list(x),targets,groups,actors,meta,tercile

def infer_weights(targets,kind,info,meta,tercile=None):
    w=np.zeros(len(targets));stats=info['both_arms_per_band']
    good=[s['grants']>=20 and min(s['grant_recipients'],s['claim_recipients'])>=30 for s in stats]
    eligible=all(good)
    if kind in targets:
        w[targets.index(kind)]=1
        if kind.startswith('received_band_'):eligible=good[int(kind.rsplit('_',1)[1])]
    elif kind in ('equal','ahead_minus_equal'):
        n=info['band_counts'];total=n[0]+n[1]
        if total==0:return w,False
        w[targets.index('received_band_0')]=n[0]/total;w[targets.index('received_band_1')]=n[1]/total
        eligible=good[0] and good[1]
        if kind=='ahead_minus_equal':w=-w;w[targets.index('received_band_3')]=1;eligible &= good[3]
    elif kind=='giver_cost_iqr':w[targets.index('received_x_giver_cost_5')]=meta['giver_cost_iqr']/5
    elif kind.startswith('standardized_tercile_'):
        for k,n in enumerate(info['band_counts']):w[targets.index(f'received_band_{k}')]=n/info['rows']
        k=int(kind.rsplit('_',1)[1])
        if k:w[targets.index(f'received_tercile_{k}')]=1
    else:raise ValueError(kind)
    return w,eligible

def run_model(c,d,folder,name,key,mode='joint',within=False):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    if checkpoint_ok(folder,key):log('Reusing '+name);return
    with heartbeat('Model '+name):
        sample=sample_info(d,'within' if within else 'both_rd_le_110' if name=='rd110' else 'all_rd')
        if len(d['y'])<100:
            write(folder/'summary.json',dict(name=name,status='INSUFFICIENT_ROWS',sample=sample));csvwrite(folder/'estimates.csv',[dict(model=name,status='INSUFFICIENT_ROWS')]);finish(folder,key);return
        try:x,names,targets,groups,actors,meta,tercile=design(d,mode,within)
        except ValueError as e:
            write(folder/'summary.json',dict(name=name,status=str(e),sample=sample));csvwrite(folder/'estimates.csv',[dict(model=name,status=str(e))]);finish(folder,key);return
        write(folder/'design.json',dict(meta,regressors=names,targets=targets))
        info,fit=fit_ols(c,x,np.column_stack([d['y'],d['reached']]),groups,actors,names,targets)
        summary=dict(name=name,sample=sample,design=meta,fit=info,status=info['status'],causal_mechanism_identified=False)
        estimates=[];covrows=[];support=[]
        if fit is not None:
            terms=targets+['equal','ahead_minus_equal']
            if 'received_x_giver_cost_5' in targets:terms+=['giver_cost_iqr']
            if mode=='terciles':terms += [f'standardized_tercile_{k}' for k in range(3)]
            for o,outcome in enumerate(('y','reached')):
                for term in terms:
                    w,ok=infer_weights(targets,term,sample,meta)
                    r=contrast(fit['coefficients'][:,o],fit['covariances'][o],w,ok)
                    if term.startswith('standardized_tercile_'):
                        t=int(term.rsplit('_',1)[1]);cells=[size(d,(d['band']==k)&(tercile==t)) for k in range(4)]
                        r['thin_joint_support']=any(z['grants']<20 or min(z['grant_recipients'],z['claim_recipients'])<30 for z in cells)
                        r['giver_cost_tercile_mean']=float(d['giver_cost'][tercile==t].mean())
                    r.update(model=name,outcome=outcome,term=term,sample_sha256=sample['sample_sha256'],
                      units='percentage points per 5 rating points' if '_5' in term else 'percentage points',
                      variance_inflation_factor=info['variance_inflation_factors'].get(term),
                      equal_weight_negative=sample['band_counts'][0]/max(1,sum(sample['band_counts'][:2])),
                      equal_weight_nonnegative=sample['band_counts'][1]/max(1,sum(sample['band_counts'][:2])),
                      causal_interpretation=False,prior_related_results_seen=True)
                    estimates.append(r)
                for i,a in enumerate(targets):
                    for j,b in enumerate(targets):covrows.append(dict(model=name,outcome=outcome,term_i=a,term_j=b,covariance_pp_squared=10000*fit['covariances'][o][i,j]))
            if mode=='terciles':
                for t in range(3):
                    for k in range(4):support.append(dict(tercile=t,band=BANDS[k],**size(d,(tercile==t)&(d['band']==k))))
        else:estimates=[dict(model=name,status=info['status'],sample_sha256=sample['sample_sha256'])]
        write(folder/'summary.json',summary);csvwrite(folder/'estimates.csv',estimates);csvwrite(folder/'covariance.csv',covrows)
        if support:csvwrite(folder/'tercile_support.csv',support)
        finish(folder,key)
