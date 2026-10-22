"""Frozen state definitions, spline basis and baseline controls."""
from fw_common import *
from scipy.interpolate import CubicSpline
from functools import lru_cache

@lru_cache(None)
def spline():return CubicSpline(np.array([-100,0,100,300,600])/100.,np.eye(5),bc_type='natural',extrapolate=False)
def eval_basis(d):
    x=d.cp.to_numpy(float);m=d.mate.to_numpy(bool);b=d.board.to_numpy(float)
    inside=(~m)&np.isfinite(x)&(x>=-100)&(x<600)
    z=spline()(np.clip(np.nan_to_num(x),-100,600)/100.)[:,1:]-spline()(0.)[None,1:]
    z[~inside]=0
    return np.column_stack([z,(~m)&(x>=600),m&(b>0)])

def baseline(d,all_stages=True):
    cols=[];names=[]
    def add(n,x):cols.append(np.asarray(x,float));names.append(n)
    for m in range(1,24):add('month_'+str(m),d.month_code==m)
    for s in range(1,5):add('speed_'+str(s),d.speed_code==s)
    for s in (range(1,6) if all_stages else range(3,6)):add('stage_'+str(s),d.stage==s)
    for n in ('premium','rd_c','rd_d'):
        v=d[n].to_numpy(float);ok=np.isfinite(v)&(v>0)
        # Baseline financial/RD missingness is separately recorded in every model.
        z=np.log1p(np.where(ok,v,0)) if n=='premium' else np.log(np.where(ok,v,1))
        add('log_'+n,z);add('log_'+n+'_sq',z*z);add('missing_'+n,~ok)
    for n in ('clock_c','clock_d'):
        v=d[n].to_numpy(float);ok=np.isfinite(v)&(v>=0)
        add('log1p_'+n,np.log1p(np.where(ok,v,0)));add('missing_'+n,~ok)
    return np.column_stack(cols),names

def nuisance(d):
    b=d.board.to_numpy(float);cp=d.cp.to_numpy(float);m=d.mate.to_numpy(bool)
    code=np.select([m&(b<0),m&(b>0),cp< -600,cp<=-300,cp< -100,cp<0,cp<100,cp<300,cp<600],range(9),default=9)
    gap=d.gap.to_numpy(float);require(np.isfinite(gap).all(),'Missing displayed gap in nuisance adjustment');g=np.select([gap< -200,gap< -50,gap<50,gap<200],range(4),default=4)
    base,names=baseline(d,True)
    cols=[np.ones(len(d)),base]+[(code==j).astype(float)[:,None] for j in range(1,10)]+[(g==j).astype(float)[:,None] for j in range(1,5)]
    return np.column_stack(cols),['intercept']+names+['eval_'+str(j) for j in range(1,10)]+['gap_'+str(j) for j in range(1,5)]

def groups_from_counts(nc,nl,yc,yl):
    # CO=0, BOTH=1, LO=2, NEI=3; unknown support=-1, never an outcome-based drop.
    g=np.select([(yc>0)&(yl==0),(yc>0)&(yl>0),(yc==0)&(yl>0)],[0,1,2],default=3).astype(np.int8)
    g[(nc<4)|(nl<4)]=-1;return g

GROUPS=['CO','BOTH','LO','NEI']
def b_design(d,spec):
    groups=d.group_code.to_numpy(int);ng=2 if spec.get('provisional') else 4
    if spec.get('provisional'):groups=(d.rd_c.to_numpy()>110).astype(int)
    base,names=baseline(d,False);F=eval_basis(d)
    if spec.get('stage_interactions'):
        keep=[i for i,n in enumerate(names) if not n.startswith('stage_')]
        base=base[:,keep];names=[names[i] for i in keep]
    reg=spec.get('reg','rG');x=d.rG.to_numpy(float)
    if reg=='gap':x=d.gap.to_numpy(float)
    if reg=='normalized':x=x/d.premium.to_numpy(float)
    cols=[];out=[]
    for g in range(ng):
        z=groups==g
        if spec.get('profile'):
            code=profile_bins(d,spec['profile']);ref=11 if spec['profile']=='gap' else 2
            for j in range(23 if spec['profile']=='gap' else 8):
                if j!=ref:cols.append((code==j)*z);out.append(f'g{g}:bin{j}')
            if spec['profile']=='evaluation':cols.append(x*z);out.append(f'g{g}:slope')
        else:cols.append(x*z);out.append(f'g{g}:slope')
        if not spec.get('equal') and not spec.get('profile'):
            for j in range(6):cols.append(F[:,j]*z);out.append(f'g{g}:eval{j}')
        if spec.get('stage_interactions'):
            for st in (3,4,5):cols.append((d.stage.to_numpy()==st)*z);out.append(f'g{g}:stage{st}')
    if spec.get('provisional'):
        cols.append(groups.astype(float));out.append('provisional_main')
    # Group histories are fixed per chooser; their levels are absorbed by chooser FE.
    return np.column_stack(cols+[base]),out+names,groups

EVAL_LABELS=['[-100,-50)','[-50,0)','[0,50)','[50,100]','(100,200]','(200,300)','[300,600)','>=600 or positive mate']
def profile_bins(d,kind):
    if kind=='gap':return np.clip(np.floor((d.gap.to_numpy()+25)/50).astype(int)+11,0,22)
    x=d.board.to_numpy(float)
    return np.select([x< -50,x<0,x<50,x<=100,x<=200,x<300,x<600],range(7),default=7).astype(int)
