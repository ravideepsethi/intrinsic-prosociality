"""Original weighted projections and covariance, with bounded crossproducts."""
from util import *
from source import core,common,absorption,matched
from checkpoints import stage
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

EXTRA=('exposure_game_utc_ms','exposure_anchor_utc_ms','recipient_next_disconnection_utc_ms')
OMIT={'pre_games_30d','encouragement_prior_pair_excluded_n','encouragement_pair_excluded_propensity',
 'recipient_prior_fair_opportunities_90d','recipient_prior_kind_draws_90d','recipient_prior_kind_rate_90d',
 'recipient_prior_rating_change_90d','recipient_prior_disconnections_main_sample','recipient_prior_mercy_receipts_main_sample',
 'any_game_within_10m','any_game_within_30m','any_game_within_60m','any_game_within_7d','any_game_within_30d',
 'games_within_7d','games_within_30d','log1p_games_within_30d'}

def load_data(path):
    columns=[x for x in core.RECIPIENT_NUMERIC_COLUMNS if x not in OMIT]+list(EXTRA)
    t=pq.ParquetFile(path).read(columns=columns,use_threads=False)
    d={x:core.arrow_column_numpy(t,x,np,pa) for x in columns}
    require(np.array_equal(d['cohort_row_id'],np.arange(len(t))),'Recipient row order is not dense')
    require(np.array_equal(d['arm_eligible'],d['received_mercy']|d['exposure_claimed_win']),'Receipt arms differ')
    require(not (d['received_mercy']&d['exposure_claimed_win']).any(),'Overlapping receipt arms')
    for name,count in [('EXPECTED_RECIPIENT_MERCY',d['received_mercy'].sum()),('EXPECTED_RECIPIENT_CLAIMED',d['exposure_claimed_win'].sum()),
                       ('EXPECTED_RECIPIENT_ARM_ELIGIBLE',d['arm_eligible'].sum()),('EXPECTED_RECIPIENT_NONARM',(~d['arm_eligible']).sum())]:
        setattr(core,name,int(count))
    support=core.common_support_weights(d)
    reached=d['reached_fair_chooser_within_90d']
    require(np.isfinite(d['first_subsequent_kind_draw'][reached]).all(),'A reached decision has a missing outcome')
    d['first_choice_zero_coded']=np.where(reached,d['first_subsequent_kind_draw'],0.)
    d['censored_next_competitive_disconnection']=matched.censored_outcome(reached,d['first_subsequent_kind_draw'],
      d['exposure_anchor_utc_ms'],d['first_subsequent_delta_ms'],d['recipient_next_disconnection_utc_ms'])
    return d,support

def fit(y,treatment,controls,names,weights,groups,cluster,row_ids,binary=True,allow_rank_deficient=False):
    y=np.asarray(y,float);D=np.asarray(treatment,float);w=np.asarray(weights,float)
    require(len(y)>=100 and len(np.unique(D))==2 and np.isfinite(y).all() and (w>0).all(),'Insufficient or invalid model support')
    matrix=np.column_stack([y,D,controls])
    if len(groups)==3:z,it,last=absorption.absorb(matrix,w,groups)
    else:z,it,last=core.weighted_absorb(matrix,w,groups)
    del matrix
    yy=z[:,0];X=z[:,1:];k=X.shape[1];xx=np.zeros((k,k));xy=np.zeros(k)
    # Bound temporary allocations, rather than duplicating the whole 2-million-row design.
    for first in range(0,len(y),131072):
        sl=slice(first,first+131072);wx=X[sl]*w[sl,None]
        xx+=X[sl].T@wx;xy+=wx.T@yy[sl]
    f=common.solve(xx,xy)
    require(common.estimable(np.eye(k)[0],f)[0],'Receipt contrast is not identified')
    require(allow_rank_deficient or f['rank']==k,'Historical full-rank requirement failed')
    u=yy-X@f['beta'];_,codes=np.unique(cluster,return_inverse=True);G=int(codes.max())+1
    require(G>1 and len(y)>f['rank'],'Insufficient clusters/degrees of freedom')
    scores=np.column_stack([np.bincount(codes,weights=w*u*X[:,j],minlength=G) for j in range(k)])
    meat=scores.T@scores;del scores
    correction=G/(G-1)*(len(y)-1)/(len(y)-f['rank'])
    V=f['bread']@meat@f['bread']*correction;V=(V+V.T)/2
    require(np.isfinite(V).all() and V[0,0]>=0,'Invalid receipt covariance')
    scale=100 if binary else 1;inference=common.inference(f['beta'][0]*scale,V[0,0]*scale**2)
    treated=D>0.5;mean0=float(np.average(y[~treated],weights=w[~treated]));mean1=float(np.average(y[treated],weights=w[treated]))
    result=dict(inference,rows=len(y),clusters=G,treated_rows=int(treated.sum()),control_rows=int((~treated).sum()),
      weighted_control_mean=mean0*scale,weighted_treated_mean=mean1*scale,
      relative_to_control_mean=float(f['beta'][0]/mean0) if mean0 else None,
      units='percentage points' if binary else 'count per exposure',rank=f['rank'],control_count=len(names),
      control_names=list(names),coefficient_names=['received_mercy']+list(names),
      coefficients=(f['beta']*scale).tolist(),covariance=(V*scale**2).tolist(),
      cluster_correction=correction,absorption_iterations=int(it),absorption_residual=float(last),
      sample_sha256=hashlib.sha256(np.asarray(row_ids,dtype='<i8').tobytes()).hexdigest(),
      covariance_description='Exposure chooser clusters; G/(G-1)*(N-1)/(N-rank), same as original matched design')
    if len(groups)==3:
        # Report the established common-hour sensitivity alongside the principal chooser SE.
        _,hc=np.unique(groups[-1],return_inverse=True);H=int(hc.max())+1
        _,both=np.unique(np.column_stack([codes,hc]),axis=0,return_inverse=True);B=int(both.max())+1
        sh=np.column_stack([np.bincount(hc,weights=w*u*X[:,j],minlength=H) for j in range(k)])
        mh=sh.T@sh;del sh
        sp=np.column_stack([np.bincount(both,weights=w*u*X[:,j],minlength=B) for j in range(k)])
        mh-=sp.T@sp;del sp
        VV=f['bread']@(meat+mh)@f['bread'];vv=float(VV[0,0])*scale**2
        result.update(hour_clusters=H,se_chooser_or_hour_CR0=math.sqrt(vv) if vv>=0 else None,
                      chooser_or_hour_variance=vv,chooser_or_hour_status='ESTIMATED' if vv>=0 else 'INVALID_VARIANCE')
        hour_inference=common.inference(f['beta'][0]*scale,vv)
        for name in ('p','ci_low','ci_high'):result[name+'_chooser_or_hour_CR0']=hour_inference[name]
    return result

import math

def specs():
    rows=[('primary','first_choice_zero_coded',False,True),
      ('censored','censored_next_competitive_disconnection',False,True),
      ('reach','reached_fair_chooser_within_90d',False,True),
      ('conditional','first_subsequent_kind_draw',False,True),
      ('conditional_later_controls','first_subsequent_kind_draw',True,True),
      ('any_later_grant','any_fair_kind_grant_within_90d',False,True),
      ('later_receipt_count','recipient_future_mercy_receipts_90d',False,False)]
    rows += [(name,name,False,True) for name in ('decay_6h_kind','decay_1d_kind','decay_7d_kind','decay_30d_kind','decay_90d_kind')]
    result=[dict(name=n,outcome=o,later=l,binary=b,hour=None) for n,o,l,b in rows]
    for n,o in [('primary','first_choice_zero_coded'),('reach','reached_fair_chooser_within_90d'),('conditional','first_subsequent_kind_draw')]:
        for hour in ('start','last_move'):result.append(dict(name=n+'_'+hour+'_hour',outcome=o,later=False,binary=True,hour=hour))
    return result

def execute_models(path,run,key):
    d,support=load_data(path)
    table(run/'report/common_support_cells.csv',support['cell_rows'])
    support_summary={k:v for k,v in support.items() if k not in ('weights','eligible','cell_rows')}
    save(run/'report/COMMON_SUPPORT.json',support_summary)
    rows=[]
    complete=d['a1_90d_followup_eligible'].astype(bool)&support['eligible']
    flow=dict(all_fresh_exposures=len(d['cohort_row_id']),first_observed_pair=int(d['first_ever_pair'].sum()),
      common_support=int(support['eligible'].sum()),common_support_complete90=int(complete.sum()),
      complete90_receipts=int((complete&d['received_mercy']).sum()),complete90_claims=int((complete&d['exposure_claimed_win']).sum()),
      complete90_reached=int((complete&d['reached_fair_chooser_within_90d']).sum()))
    table(run/'report/MATCHED_SAMPLE_FLOW.csv',[flow])
    for j,spec in enumerate(specs(),1):
        model_key=digest(dict(key=key,specification=spec))
        def build(folder):
            y=np.asarray(d[spec['outcome']],float);ix=np.flatnonzero(complete&np.isfinite(y))
            X,names=core.model_controls(d,ix,state_conditioned=spec['later'])
            groups=[d['exposure_cell_code'][ix],d['exposure_month_code'][ix]]
            if spec['hour']:
                column='exposure_game_utc_ms' if spec['hour']=='start' else 'exposure_anchor_utc_ms'
                groups.append(d[column][ix]//3600000)
            with heartbeat(f"Receipt model {j}/18: {spec['name']}"):
                r=fit(y[ix],d['received_mercy'][ix],X,names,support['weights'][ix],groups,
                    d['exposure_chooser_user_id'][ix],d['cohort_row_id'][ix],spec['binary'],bool(spec['hour']))
            r.update(spec);save(folder/'model.json',r)
            return {k:v for k,v in r.items() if k not in ('covariance','coefficients','coefficient_names','control_names')}
        folder,result=stage(run/'PRIVATE/models',spec['name'],model_key,build)
        import shutil
        target=run/'report/models'/(spec['name']+'.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(folder/'model.json',target)
        table(run/'report/rows'/(spec['name']+'.csv'),[result]);rows.append(result)
        log(f"Receipt {j}/18 {spec['name']}: {result['estimate']:.6f} ({result['se']:.6f}), N={result['rows']:,}")
    return rows,flow
