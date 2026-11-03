"""Frozen feature maps; all counterfactuals rebuild their dependent features."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
from scipy.special import expit,logit
from g_common import require,hash64

EVAL_KNOTS=np.array([-1500,-1000,-600,-300,-100,0,100,300,600,1000,1500],float)/100
RATING_KNOTS=np.array([0,1000,1400,1800,2200,4000],float)/1000
PROB_CLIP=1e-6

def natural(x,knots,center=0):
    """Natural cubic basis, with genuinely linear (not cubic) exterior tails."""
    knots=np.asarray(knots,float);require(np.all(np.diff(knots)>0),'Spline knots are not distinct','INSUFFICIENT_INDEX_SUPPORT')
    sp=CubicSpline(knots,np.eye(len(knots)),bc_type='natural')
    x=np.asarray(x,float);z=sp(np.clip(x,knots[0],knots[-1]))
    z+=np.minimum(x-knots[0],0)[:,None]*sp(knots[0],1)
    z+=np.maximum(x-knots[-1],0)[:,None]*sp(knots[-1],1)
    return z[:,1:]-sp(np.clip(center,knots[0],knots[-1]))[None,1:]
def ply_band(p): return np.select([p<=20,p<=40,p<=80,p<=120],[0,1,2,3],default=4).astype(np.int8)
def ply_bin(p): return np.minimum((np.asarray(p,dtype=int)-11)//10,19)
def rating_band(r): return np.searchsorted([1200,1600,2000],r,side='right')
def context(d,merge_ultra=False):
    speed=d.speed.to_numpy(int).copy()
    if merge_ultra: speed[speed==0]=1
    return speed*20+rating_band(d.mean_r.to_numpy())*5+ply_band(d.ply.to_numpy())
def index_knots(p):
    q=np.quantile(logit(np.clip(np.asarray(p),PROB_CLIP,1-PROB_CLIP)),[.10,.25,.50,.75,.90])
    return np.r_[logit(PROB_CLIP),q,logit(1-PROB_CLIP)]
def index_basis(p,knots): return natural(logit(np.clip(p,PROB_CLIP,1-PROB_CLIP)),knots)

def raw_features(d,intercept=False):
    n=len(d);cols=[];names=[];blocks={}
    def add(name,x,block):
        z=np.asarray(x,float).reshape(n,-1)
        start=len(names);cols.append(z);names.extend([name] if z.shape[1]==1 else [name+str(k) for k in range(z.shape[1])]);blocks.setdefault(block,[]).extend(range(start,len(names)))
    if intercept:add('intercept',np.ones(n),'constant')
    v=np.clip(d.vf.to_numpy(float),-1500,1500)/100
    mate=d.mate.to_numpy(float);v=np.where(mate!=0,0,v)
    E=natural(v,EVAL_KNOTS);E[mate!=0]=0
    gap=np.clip(d.dr.to_numpy(float),-600,600)/100
    mean=d.mean_r.to_numpy(float)/1000
    cf=d.clock_f.to_numpy(float);cg=d.clock_g.to_numpy(float);base=d.base.to_numpy(float)
    require(np.isfinite(np.r_[v,gap,mean,cf,cg,base]).all() and (cf>=0).all() and (cg>=0).all() and (base>0).all(),'Missing or invalid G1 clock/rating input','MISSING_REQUIRED_FEATURES')
    lc=np.log1p(cf);lg=np.log1p(cg);stm=d.stm.to_numpy(float)
    sp=[(d.speed.to_numpy()==k).astype(float) for k in range(1,5)]
    pb=[(ply_band(d.ply.to_numpy())==k).astype(float) for k in (0,1,3,4)]
    add('eval_',E,'evaluation')
    for sign,label in [(1,'mate_for'),(-1,'mate_against')]:
        for near in [True,False]: add(label+('_near' if near else '_far'),(mate*sign>0)&((np.abs(mate)<=5)==near),'evaluation')
    add('gap',gap,'gap');add('gap_sq',gap**2,'gap')
    add('mean_rating_',natural(mean,RATING_KNOTS,1.6),'rating')
    for k,z in enumerate(sp,1):add('speed_'+str(k),z,'context')
    add('increment',d.inc.to_numpy()>0,'context')
    for k,z in zip((0,1,3,4),pb):add('stage_'+str(k),z,'context')
    add('log_clock_f',lc,'clocks');add('log_clock_g',lg,'clocks');add('clock_share',cf/base,'clocks');add('f_to_move',stm,'side_to_move')
    modifiers=[('speed'+str(k),z,'context') for k,z in enumerate(sp,1)]+[('stage'+str(k),z,'context') for k,z in zip((0,1,3,4),pb)]
    modifiers += [('mean_rating',mean,'rating'),('log_clock_f',lc,'clocks'),('log_clock_g',lg,'clocks'),('f_to_move',stm,'side_to_move')]
    for name,z,block in modifiers:
        add('eval_x_'+name+'_',E*z[:,None],'evaluation' if block=='context' else block)
        add('gap_x_'+name,gap*z,'gap' if block=='context' else block)
    add('eval_x_gap_',E*gap[:,None],'gap')
    X=np.column_stack(cols);require(np.isfinite(X).all(),'Nonfinite raw design')
    blocks={'evaluation':[i for i,n in enumerate(names) if n.startswith(('eval','mate_'))],
            'gap':[i for i,n in enumerate(names) if 'gap' in n],
            'clocks':[i for i,n in enumerate(names) if 'clock' in n],
            'side_to_move':[i for i,n in enumerate(names) if 'f_to_move' in n],
            'rating':[i for i,n in enumerate(names) if 'mean_rating' in n],
            'context':[i for i,n in enumerate(names) if n.startswith(('speed','stage','increment'))]}
    return X,names,blocks

def baseline(d):
    cols=[];names=[]
    def add(n,x):cols.append(np.asarray(x,float));names.append(n)
    for j in range(1,24):add('month_'+str(j),d.month_code==j)
    for j in range(1,5):add('speed_'+str(j),d.speed==j)
    for j in (0,1,3,4):add('stage_'+str(j),ply_band(d.ply.to_numpy())==j)
    for n in ('premium','rd_c','rd_d'):
        v=d[n].to_numpy(float);ok=np.isfinite(v)&(v>0)
        z=np.log1p(np.where(ok,v,0)) if n=='premium' else np.log(np.where(ok,v,1))
        add('log_'+n,z);add('log_'+n+'_sq',z*z);add('missing_'+n,~ok)
    return np.column_stack(cols),names
def g2_design(d,model,omega=None,score=None,knots=None,score_knots=None,group_specific=False):
    base,names=baseline(d);cols=[base];blocks={}
    if model in ('MU','MRU','MRUprime'):
        raw,rn,rb=raw_features(d)
        keep=[j for j,n in enumerate(rn) if n not in names and n!='f_to_move' and 'f_to_move' not in n]
        start=len(names);cols.append(raw[:,keep]);names+= [rn[j] for j in keep]
        blocks={b:[start+keep.index(j) for j in js if j in keep] for b,js in rb.items()}
    if model in ('MR','MRU','MRprime','MRUprime'):
        z=index_basis(score if 'prime' in model else omega,score_knots if 'prime' in model else knots)
        if group_specific:
            z=np.column_stack([z*(d.group.to_numpy()==g)[:,None] for g in range(4)])
        cols.append(z);names+=['index_'+str(j) for j in range(z.shape[1])]
    return np.column_stack(cols),names,blocks
def opposite(d):
    z=d.copy();z['vf']=-d.vf;z['mate']=-d.mate;z['dr']=-d.dr
    z['clock_f']=d.clock_g;z['clock_g']=d.clock_f;z['stm']=1-d.stm
    if 'outcome' in d:z['outcome']=2-d.outcome # W=0,D=1,L=2
    return z
def counterfactual(d,kind):
    z=d.copy()
    if kind=='gap100':
        # Hold chooser rating fixed; raise opponent rating by 100.
        z['dr']=d.dr+100;z['mean_r']=d.mean_r+50
    elif kind=='double_clock':z['clock_f']=2*d.clock_f
    elif kind=='eval100':
        z['vf']=d.vf+100 # chooser advantage; no invented finite mate transformation
    else:raise ValueError(kind)
    return z
def assign_split(d,random=False):
    require(not d.chooser.duplicated().any() or d.chooser.is_monotonic_increasing,'Accounts must be contiguous')
    n=d.groupby('chooser',sort=False).chooser.transform('size').to_numpy()
    if random:
        key=np.array([hash64(g,'holdout') for g in d.game_id],dtype=np.uint64)
        temp=pd.DataFrame({'chooser':d.chooser.to_numpy(),'key':key});rank=temp.groupby('chooser').key.rank(method='first').to_numpy()-1
    else:rank=d.groupby('chooser',sort=False).cumcount().to_numpy()
    return (n<10)|(rank<np.floor(.8*n))
