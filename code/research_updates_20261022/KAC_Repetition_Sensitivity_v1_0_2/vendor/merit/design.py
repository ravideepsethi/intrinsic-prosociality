"""Frozen unconstrained designs. No outcome-dependent knot or model selection."""
from common import *
from scipy.interpolate import CubicSpline
from functools import lru_cache

MONTHS=[f'{2023+(10+i)//12:04d}-{(10+i)%12+1:02d}' for i in range(24)]
SPEEDS=['ultraBullet','bullet','blitz','rapid','classical']
STAGES=['0_1','2','3_4','5_6','7_8','9_10','11_20','21_40','41_80','81plus']
MATERIAL_LABELS=['<=-2','-1','0','1','2','3','4','>=5']
BIN_LABELS=['[-100,-50)','[-50,0)','[0,50)','[50,100]','(100,200]','(200,300)','[300,600)','>=600 or positive mate']

def specifications():
    out=[]
    def add(name,kind='spline',sample='competitive_late',controls='base',**kw):
        out.append(dict(name=name,kind=kind,sample=sample,controls=controls,**kw))
    add('primary_competitive_late')
    add('competitive_all_stages',sample='competitive_all')
    add('competitive_plies11_80',sample='competitive_11_80')
    add('alternative_knots',alternative=True)
    add('competitive_late_clocks',controls='clocks')
    add('competitive_late_rating',controls='rating')
    add('early_late_interaction',sample='competitive_all',interaction='late')
    add('full_range_late',sample='full_late')
    add('eight_bins_late',kind='bins')
    add('eight_bins_all',kind='bins',sample='competitive_all')
    add('linear_summary_late',kind='linear')
    for sample in ['competitive_late','full_late']:
        for control in ['base','clocks','rating']:
            add('material_'+sample+'_'+control,kind='material',sample=sample,controls=control)
    add('evaluation_by_rating_tier',interaction='tier')
    add('material_by_rating_tier_competitive',kind='material',interaction='tier')
    add('material_by_rating_tier_full',kind='material',sample='full_late',interaction='tier')
    for c in ['base','clocks','rating']:add('joint_eval_material_'+c,kind='joint',controls=c)
    return out

def select(d,s):
    m=np.ones(len(d),bool)
    if s['sample'].startswith('competitive'):m &= d.board.to_numpy()>=-100
    if s['sample'].endswith('late'):m &= d.ply.to_numpy()>10
    if s['sample']=='competitive_11_80':m &= (d.ply.to_numpy()>10)&(d.ply.to_numpy()<=80)
    return d.loc[m].reset_index(drop=True)

@lru_cache(None)
def interpolator(knots):return CubicSpline(np.asarray(knots)/100.,np.eye(len(knots)),bc_type='natural',extrapolate=False)

def natural_basis(cp,knots):
    # Cardinal natural-cubic basis, omitting a constant direction and centering at 0.
    cs=interpolator(tuple(knots));return cs(np.asarray(cp)/100.)[:,1:]-cs(0.)[None,1:]

def eval_base(d,s):
    e=d.cp.to_numpy(float);mate=d.mate.to_numpy(bool);board=d.board.to_numpy(float)
    full=s['sample'].startswith('full');lo=-600 if full else -100
    knots=[-600,-300,-100,0,100,300,600] if full else [-100,0,100,300,600]
    if s.get('alternative'):knots=[-100,-50,100,250,450,600]
    inside=(~mate)&(e>=lo)&(e<600)
    if s['kind']=='linear':b=(np.where(inside,e,0)/100.)[:,None];names=['cp_per100']
    else:
        b=natural_basis(np.clip(np.nan_to_num(e,nan=0),lo,600),knots);b[~inside,:]=0
        names=[f'ns_{j+1}' for j in range(b.shape[1])]
    tails=[('finite_ge600',(~mate)&(e>=600)),('mate_positive',mate&(board>0))]
    if full:tails += [('finite_lt_minus600',(~mate)&(e<lo)),('mate_negative',mate&(board<0))]
    return np.column_stack([b]+[x.astype(float) for _,x in tails]),names+[n for n,_ in tails]

def material_code(x):return np.clip(np.asarray(x),-2,5).astype(int)+2
def bins_code(d):
    x=d.board.to_numpy()
    return np.select([x< -50,x<0,x<50,x<=100,x<=200,x<300,x<600],list(range(7)),default=7).astype(int)

def focal(d,s):
    if s['kind']=='material':
        code=material_code(d.material);base=np.column_stack([(code==j).astype(float) for j in [0,1,3,4,5,6,7]])
        names=['material_'+MATERIAL_LABELS[j] for j in [0,1,3,4,5,6,7]]
    elif s['kind']=='bins':
        code=bins_code(d);base=np.column_stack([(code==j).astype(float) for j in range(1,8)])
        names=['bin_'+str(j) for j in range(1,8)]
    else:base,names=eval_base(d,s)
    inter=s.get('interaction')
    ng=4 if inter=='tier' else 2 if inter=='late' else 1
    group=d.tier.to_numpy(int) if inter=='tier' else (d.ply.to_numpy()>10).astype(int) if inter=='late' else np.zeros(len(d),int)
    if ng>1:
        base=np.column_stack([base*(group==g)[:,None] for g in range(ng)])
        names=[n+f':{inter}{g}' for g in range(ng) for n in names]
    return base,names,group,ng

def design(d,s):
    f,names,groups,ng=focal(d,s);p=f.shape[1];cols=[f]
    def add(n,x):names.append(n);cols.append(np.asarray(x,float)[:,None])
    for j in range(1,24):add('month_'+MONTHS[j],d.month_code.to_numpy()==j)
    for j in range(1,5):add('speed_'+SPEEDS[j],d.speed_code.to_numpy()==j)
    stages=range(1,10) if s['sample'].endswith('all') else range(7,10)
    for j in stages:add('stage_'+STAGES[j],d.stage.to_numpy()==j)
    if s.get('interaction')=='tier':
        for j in range(1,4):add('rating_tier_'+str(j),d.tier.to_numpy()==j)
    if s['kind']=='joint':
        c=material_code(d.material)
        for j in [0,1,3,4,5,6,7]:add('material_'+MATERIAL_LABELS[j],c==j)
    if s['controls'] in ['clocks','rating']:
        for n in ['clock_c','clock_d']:
            v=d[n].to_numpy(float);ok=np.isfinite(v)&(v>=0);z=np.log1p(np.where(ok,v,0))
            add('log_'+n,z);add('missing_'+n,~ok)
    if s['controls']=='rating':
        gap=d.gap.to_numpy(float);ok=np.isfinite(gap);z=np.clip(np.where(ok,gap,0),-600,600)/100.
        add('gap100',z)
        for knot in [-3,-1,0,1,3]:add('gap_hinge_'+str(knot),np.maximum(z-knot,0))
        add('gap_low_tail',ok&(gap< -600));add('gap_high_tail',ok&(gap>600));add('gap_missing',~ok)
        for n in ['premium','rd_c','rd_d']:
            v=d[n].to_numpy(float);ok=np.isfinite(v)&(v>0);z=np.log(np.where(ok,v,1))
            add('log_'+n,z);add('log_'+n+'_sq',z*z);add(n+'_missing',~ok)
    return np.column_stack(cols),names,p,groups,ng

def points(s):
    if s['kind']=='material':return [dict(label=x,material=j-2) for j,x in enumerate(MATERIAL_LABELS)]
    if s['kind']=='bins':return [dict(label=x,cp=e) for x,e in zip(BIN_LABELS,[-75,-25,25,75,150,250,450,700])]
    lo=-600 if s['sample'].startswith('full') else -100
    out=[dict(label=str(e),cp=e) for e in sorted(set(list(range(lo,600,10))+[599]))]
    out += [dict(label='finite >=600',cp=700),dict(label='positive mate',cp=10000,mate=True)]
    if lo==-600:out += [dict(label='finite <-600',cp=-700),dict(label='negative mate',cp=-10000,mate=True)]
    return out

def counterfocal(s,point,ng):
    d=pd.DataFrame(dict(cp=[point.get('cp',0)]*ng,board=[point.get('cp',0)]*ng,mate=[point.get('mate',False)]*ng,
        material=[point.get('material',0)]*ng,tier=np.arange(ng),ply=[5 if g==0 else 20 for g in range(ng)]))
    return focal(d,s)[0]
