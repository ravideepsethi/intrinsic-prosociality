"""Frozen basis. No test outcomes or test-derived categories enter the design."""
from __future__ import annotations
import numpy as np
from scipy import sparse

NUMERIC={
 'gap':('gap',100.,0.,-5.,5.),
 'rating':('rating',400.,1600.,-3.,4.),
 'loss':('loss',5.,0.,0.,10.),
 'gain':('gain',5.,0.,0.,10.),
 'premium':('premium',10.,10.,-1.,10.),
 'crd':('crd',100.,60.,-.6,3.),
 'drd':('drd',100.,60.,-.6,3.),
 'cvol':('cvol',.05,.06,-1.2,4.),
 'dvol':('dvol',.05,.06,-1.2,4.)}


def design(df):
    cols=[];names=[];blocks={}
    def add(name,v,block):
        cols.append(np.asarray(v,float));names.append(name);blocks.setdefault(block,[]).append(len(names)-1)
    b=df.board.to_numpy();stage=df.stage.to_numpy();cell=b*4+stage
    add('competitive_centered',(b>=2).astype(float)-1,'board')
    for k in range(20):
        if k not in (2,10):add('board_stage_'+str(k),cell==k,'board_stage')
    for name,(source,scale,reference,lo,hi) in NUMERIC.items():
        v=df[source].to_numpy(float);missing=~np.isfinite(v)
        add(name,np.clip((np.where(missing,reference,v)-reference)/scale,lo,hi),'cost' if name in ('loss','gain','premium') else 'rating')
        add(name+'_missing',missing,'missing')
    for name in ('cclock','dclock'):
        v=df[name].to_numpy(float);missing=~np.isfinite(v)|(v<0)
        add(name,np.clip((np.log1p(np.where(missing,60,v))-np.log(61))/2,-3,4),'clocks')
        add(name+'_missing',missing,'missing')
    speeds=df.speed.fillna('__MISSING__').to_numpy()
    for speed in ['ultraBullet','bullet','rapid','classical','correspondence','__MISSING__']:
        add('speed_'+speed,speeds==speed,'speed')
    unknown=~np.isin(speeds,['blitz','ultraBullet','bullet','rapid','classical','correspondence','__MISSING__'])
    add('speed_other',unknown,'speed')
    for month in range(1,12):add('season_'+str(month),df.month.str[-2:].astype(int).to_numpy()==month,'season')
    add('white',df.color.to_numpy()==1,'color');add('color_missing',df.color.to_numpy()<0,'missing')
    X=sparse.csr_matrix(np.column_stack(cols))
    H=np.column_stack([np.ones(len(df)),df.received.to_numpy(float),
        np.log1p(np.minimum(df.gap_days.to_numpy(float),365))/3,
        np.log1p(df.receipt_risks.to_numpy(float))/2,
        (df.ambiguous_receipts.to_numpy()>0).astype(float)])
    accounts,counts=np.unique(df.chooser.to_numpy(),return_counts=True)
    ptr=np.r_[0,np.cumsum(counts)].astype(np.int64)
    if not np.all(df.chooser.to_numpy()==np.repeat(accounts,counts)):raise ValueError('Rows must be contiguous and ordered by account')
    return dict(X=X,H=H,y=df.y.to_numpy(np.float64),ptr=ptr,accounts=accounts,
                period=df.period.to_numpy(np.int64),ids=np.repeat(np.arange(len(accounts)),counts),
                F=(b>=2).astype(float)-1,names=names,cost_indices=blocks['cost'],blocks=blocks,
                transition_names=['constant','well_separated_receipt','log_elapsed_days','log_observed_receipt_risks','ambiguous_receipt_interval'])


def subset(d,mask):
    mask=np.asarray(mask,bool);oldids=d['ids'][mask]
    kept,counts=np.unique(oldids,return_counts=True)
    out=dict(d)
    for key in ['X','H','y','period','F']:out[key]=d[key][mask]
    out['accounts']=d['accounts'][kept];out['ids']=np.repeat(np.arange(len(kept)),counts)
    out['ptr']=np.r_[0,np.cumsum(counts)].astype(np.int64)
    if 'account_weights' in d:out['account_weights']=d['account_weights'][kept]
    return out


def replace_outcomes(d,y):
    out=dict(d);out['y']=np.asarray(y,float);return out
