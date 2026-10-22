"""Frozen transformations. No transformations are selected using held-out y."""
import numpy as np
from common import MONTHS,SPEEDS,payoff

MODELS=('cost','loss','curved','framing','strength','strength_loss','strength_framing')
CURVATURE=(.25,.5,.75)
def gap_basis(g):
    g=np.asarray(g,float);knots=(-575,-300,-100,0,100,300,575)
    return np.column_stack([(np.clip(g-a,0,b-a)-np.clip(-a,0,b-a))/100 for a,b in zip(knots[:-1],knots[1:])])
def controls(d):
    columns=[];names=[]
    def add(name,x):names.append(name);columns.append(np.asarray(x,float))
    # Future month levels have zero coefficient under this fixed design. Held-out
    # likelihood conditions on chooser x month, eliminating that nuisance intercept.
    for m in MONTHS[1:]:add('month_'+m,d.month.eq(m))
    for s in SPEEDS[1:]:add('speed_'+s,d.speed.eq(s))
    for lo,hi in ((21,40),(41,80),(81,100000)):add('stage_'+str(lo),d.ply.between(lo,hi))
    cp=np.clip(d.cp.to_numpy(float),-600,600)/100
    for power in (1,2,3):add('eval_'+str(power),cp**power)
    for field in ('clock','opp_clock'):
        x=d[field].to_numpy(float);missing=~np.isfinite(x)|(x<0)
        add(field+'_missing',missing);add('log_'+field,np.log1p(np.where(missing,0,x)))
    for field in ('history_days','prior_starts','inactivity_days','opp_prior_starts'):
        x=d[field].to_numpy(float)
        if not np.isfinite(x).all() or (x<0).any():raise ValueError('Missing required history: '+field)
        add('log_'+field,np.log1p(x))
    add('own_rating',(d.rating.to_numpy(float)-1500)/400)
    return np.column_stack(columns),names

def value(r,p):
    r=np.asarray(r,float);pos=np.maximum(r,0)
    gain=np.log1p(pos) if p==0 else np.expm1(p*np.log1p(pos))/p
    return np.where(r>=0,gain,r)

def design(d,model,p=.5,cue=None,control_matrix=None):
    z,zn=controls(d) if control_matrix is None else control_matrix
    feats=[];names=[]
    def add(n,x):names.append(n);feats.append(np.asarray(x,float))
    if model=='curved':add('utility_cost',-(value(d.rc,p)-value(d.rg,p)))
    else:add('own_cost',-d.ki)
    add('opponent_stake',d.kj)
    if model in ('loss','strength_loss'):add('extra_loss',-np.maximum(-d.rg,0))
    if model in ('framing','strength_framing'):add('draw_frame',d.rg)
    gb=gap_basis(d.g)
    if model.startswith('strength'):
        for j in range(gb.shape[1]):add('strength_'+str(j),gb[:,j])
    constrained=len(names)
    if cue:
        x=d[cue].to_numpy(float)
        if not np.isin(x,[0,1]).all():raise ValueError('Cue unknown values must not be coded false')
        add(cue,x)
        for j in range(gb.shape[1]):add(cue+'_gap_'+str(j),x*gb[:,j])
    X=np.column_stack(feats+[z])
    bounds=[(0,None)]*constrained+[(None,None)]*(len(names)-constrained+len(zn))
    return X,names+zn,bounds

def counterfactual(d,g=None,advantage=0.):
    x=d.copy()
    if g is not None:x['g']=g;x['opp_rating']=x.rating+g
    c=np.where(x.color.eq('white'),1.,-1.)
    _,k,rg,rc=payoff(x.rating,x.opp_rating,x.rd,x.opp_rd,c,advantage)
    _,ko,_,_=payoff(x.opp_rating,x.rating,x.opp_rd,x.rd,-c,advantage)
    x['ki']=k/2;x['kj']=ko/2;x['rg']=rg;x['rc']=rc
    return x

def descriptive_design(d,kcuts):
    z,zn=controls(d);centers=(np.floor((d.g.to_numpy()+25)/50)*50).astype(int)
    k=2*d.ki.to_numpy();kg=np.where(d.rd.to_numpy()<45.01,0,1+np.searchsorted(kcuts,k,side='right'))
    feats=[];names=[]
    for group in range(5):
        if group:feats.append((kg==group).astype(float));names.append('kgroup_'+str(group))
        for b in range(-550,551,50):
            if b==0:continue
            feats.append(((kg==group)&(centers==b)).astype(float));names.append(f'gap_{b}_k{group}')
    return np.column_stack(feats+[z]),names+zn,kg
