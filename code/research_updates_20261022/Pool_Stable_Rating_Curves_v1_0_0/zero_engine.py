"""Unrestricted two-sided local linear diagnostics; no continuity restriction.

These are descriptive FE regressions, not causal regression discontinuities.
Separate left/right slopes, right-limit jump, and an exact-zero mass-point
indicator. Every window is selected and singleton-filtered independently.
"""
import json
import numpy as np
from scipy import sparse
from scipy.stats import t as student_t
from fe_engine import make_design, make_layout, solve
from pooled_engine import absorption, retain_units, within_crossproducts

TERMS=('left_slope','right_slope','right_minus_left_slope','jump_right_minus_left','zero_atom_minus_left_limit')

def local_frame(original, axis, bandwidth):
    keep=np.abs(original[axis])<=bandwidth
    f={k:v[keep] for k,v in original.items()}
    return retain_units(f) if len(f['y']) else f

def local_design(f, edges, axis, bandwidth):
    x=f[axis];zero=np.abs(x)<=1e-12*max(1.,bandwidth)
    left=(x<0)&~zero;right=(x>0)&~zero
    core=np.column_stack([np.where(left,x/bandwidth,0),np.where(right,x/bandwidth,0),right,zero])
    names,sections=make_layout(edges)
    ix=np.concatenate([sections[k] for k in ('continuous','month','speed','board','k20','logk')])
    X=sparse.hstack([sparse.csr_matrix(core),make_design(f,edges)[:,ix]],format='csr')
    return X,np.where(zero,1,np.where(left,0,2))

class LocalMoments:
    def __init__(self, edges, axis, bandwidth):
        self.edges=edges;self.axis=axis;self.bandwidth=bandwidth
        _,s=make_layout(edges);p=4+sum(len(s[k]) for k in ('continuous','month','speed','board','k20','logk'))
        self.S=np.zeros((p,p));self.b=np.zeros(p)
        self.N=self.G=self.H=self.events=self.source_N=self.cross=self.zero_cross=0
        self.n=np.zeros(3,dtype=np.int64);self.ev=np.zeros(3,dtype=np.int64)
        self.month=np.zeros((3,24),dtype=np.int64)

    def add(self, original):
        self.source_N+=int((np.abs(original[self.axis])<=self.bandwidth).sum())
        f=local_frame(original,self.axis,self.bandwidth)
        if not len(f['y']):return
        a=absorption(f);X,side=local_design(f,self.edges,self.axis,self.bandwidth);y=f['y'].astype(float)
        S,b=within_crossproducts(X,y,a)
        self.S+=S;self.b+=b
        self.N+=len(y);self.G+=a['G'];self.H+=a['H'];self.events+=int(y.sum())
        self.n+=np.bincount(side,minlength=3);self.ev+=np.bincount(side,weights=y,minlength=3).astype(np.int64)
        np.add.at(self.month,(side,f['month'].astype(int)),1)
        present=np.asarray(a['A']@np.eye(3)[side])>0
        cross=present[:,0]&present[:,2]
        self.cross+=int(((a['chooser_unit']@cross.astype(int))>0).sum())
        zcross=present[:,1]&(present[:,0]|present[:,2])
        self.zero_cross+=int(((a['chooser_unit']@zcross.astype(int))>0).sum())

    def merge(self, other):
        if (self.edges,self.axis,self.bandwidth)!=(other.edges,other.axis,other.bandwidth):raise ValueError('Local specification mismatch')
        for k in ('S','b','N','G','H','events','source_N','cross','zero_cross','n','ev','month'):
            setattr(self,k,getattr(self,k)+getattr(other,k))

    def save(self,path):
        scalars={k:int(getattr(self,k)) for k in ('N','G','H','events','source_N','cross','zero_cross')}
        meta=dict(edges=self.edges,axis=self.axis,bandwidth=self.bandwidth,**scalars)
        np.savez_compressed(path,metadata=np.array(json.dumps(meta)),**{k:getattr(self,k) for k in ('S','b','n','ev','month')})

    @classmethod
    def load(cls,path):
        with np.load(path,allow_pickle=False) as z:
            m=json.loads(str(z['metadata']));obj=cls(m.pop('edges'),m.pop('axis'),m.pop('bandwidth'))
            for k,v in m.items():setattr(obj,k,v)
            for k in ('S','b','n','ev','month'):setattr(obj,k,z[k].copy())
        return obj

def fit(m):
    C=np.zeros((5,len(m.b)));h=m.bandwidth
    C[0,0]=1/h;C[1,1]=1/h;C[2,:2]=[-1/h,1/h];C[3,2]=1;C[4,3]=1
    model=solve(m.S,m.b,C)
    model.update(C=C,estimates=C@model['beta'],projection=model['bread']@C.T,
                 meat=np.zeros((5,5)),score_sum=np.zeros(5),axis=m.axis,bandwidth=h)
    return model

def score(original,edges,model):
    f=local_frame(original,model['axis'],model['bandwidth'])
    if not len(f['y']):return
    a=absorption(f);X,_=local_design(f,edges,model['axis'],model['bandwidth'])
    e=f['y']-X@model['beta'];e-=np.asarray(a['A']@e).ravel()[a['u']]/a['n'][a['u']]
    scores=np.asarray((a['B']@X.multiply(e[:,None]))@model['projection'])
    model['meat']+=scores.T@scores;model['score_sum']+=scores.sum(axis=0)

def finish(m,model,min_n=500,min_choosers=50,min_months=6):
    denom=m.N-m.H-model['rank'];factor=m.G/(m.G-1)*(m.N-1)/denom if m.G>1 and denom>0 else None
    V=model['meat']*factor if factor is not None else np.full((5,5),np.nan)
    critical=student_t.ppf(.975,m.G-1) if m.G>1 else np.nan
    common=bool(m.n[0]>=min_n and m.n[2]>=min_n and m.cross>=min_choosers and
                (np.count_nonzero(m.month[[0,2]],axis=1)>=min_months).all())
    rows=[]
    for j,name in enumerate(TERMS):
        supported=common and (j!=4 or (m.n[1]>=min_n and m.zero_cross>=min_choosers and np.count_nonzero(m.month[1])>=min_months))
        estimable=bool(model['identified'][j] and factor is not None)
        ok=estimable and supported
        value=float(model['estimates'][j]);se=float(np.sqrt(max(0,V[j,j]))) if estimable else None
        p=float(2*student_t.sf(abs(value/se),m.G-1)) if ok and se else (1. if ok and value==0 else 0. if ok else None)
        rows.append(dict(axis=m.axis,bandwidth=m.bandwidth,term=name,status='estimated' if ok else 'insufficient_support' if estimable else 'unidentified',
          estimate_pp=100*value if estimable else None,cluster_se_pp=100*se if estimable else None,
          ci95_low_pp=100*(value-critical*se) if estimable else None,ci95_high_pp=100*(value+critical*se) if estimable else None,
          p_two_sided=p,units='pp per axis unit' if j<3 else 'pp',source_window_n=m.source_N,
          n=m.N,events=m.events,chooser_clusters=m.G,absorbed_units=m.H,
          left_n=int(m.n[0]),zero_n=int(m.n[1]),right_n=int(m.n[2]),
          left_grants=int(m.ev[0]),zero_grants=int(m.ev[1]),right_grants=int(m.ev[2]),
          cross_zero_choosers=m.cross,zero_switching_choosers=m.zero_cross,
          left_months=int(np.count_nonzero(m.month[0])),right_months=int(np.count_nonzero(m.month[2])),
          rank=int(model['rank']),CR1_factor=factor,condition_number=model['condition_number'],
          projection_error=float(model['projection_error'][j]),exploratory=True))
    return rows,V
