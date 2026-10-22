"""Dispatch matched models without modifying the archived benchmark."""
import bootstrap_path
import time
from dataclasses import asdict
import numpy as np
from scipy.optimize import minimize
import model as original
from model import Spec
from switching import SwitchingModel
from fast_static import FastStaticModel

CHALLENGE=original.CORE+[
    Spec('board_only','desert'),Spec('no_stage','desert'),
    Spec('no_expected','desert'),Spec('desert_no_cost','desert',cost='none')]
SWITCHING=[Spec('desert','desert')]+[
    Spec(kind+'_'+family,'desert') for kind in ['iid','hmm']
    for family in ['willingness','gate','gatecost','unrestricted']]


class RestrictedModel(FastStaticModel):
    def __init__(self,spec,J,meta,bound=12.):
        super().__init__(spec,J,meta,bound)
        keys=[]
        if self.spec.name in ['board_only','no_stage']:keys.append('g')
        if self.spec.name in ['board_only','no_expected']:keys.append('h')
        for key in keys:
            for j in range(self.slices[key].start,self.slices[key].stop):self.bounds[j]=(1.,1.)


def Model(spec,J,meta,bound=12.):
    name=spec.name if isinstance(spec,Spec) else spec['name']
    return SwitchingModel(spec,J,meta,bound) if name.startswith(('hmm_','iid_')) else RestrictedModel(spec,J,meta,bound)


def fit(data,spec,J,meta,seed,maxiter=800,ridge=1e-6,bound=12.,warm=None):
    m=Model(spec,J,meta,bound)
    v=m.start(seed) if warm is None else np.asarray(warm,float).copy()
    lo,hi=np.array(m.bounds).T;v=np.clip(v,lo,hi);start=time.monotonic();nit=0
    for attempt in range(3):
        opt=minimize(m.objective,v,args=(data,ridge),jac=True,method='L-BFGS-B',bounds=m.bounds,
          options=dict(maxiter=maxiter,ftol=1e-12 if attempt==0 else 0.,gtol=2e-5,maxls=50,maxcor=20))
        nit+=opt.nit;grad=opt.jac.copy()
        grad[(opt.x<=lo+1e-7)&(grad>0)]=0.;grad[(opt.x>=hi-1e-7)&(grad<0)]=0.;grad[lo==hi]=0.
        pg=float(np.max(abs(grad)))
        if not np.isfinite(opt.fun) or pg<=2.5e-5:break
        v=opt.x.copy()
    structural={'theta','amplitude','angle','f0','fother','g','h','sigma','cost_pair','lower_theta','lower_cost','level_gap'}
    if m.spec.cost=='signed':structural.remove('cost_pair')
    hits=[]
    for j,name in enumerate(m.names):
        if lo[j]==hi[j]:continue
        key=name.split(':')[0]
        if abs(opt.x[j]-lo[j])<1e-5 and key not in structural:hits.append(name)
        if abs(opt.x[j]-hi[j])<1e-5 and key!='angle':hits.append(name)
    return dict(spec=asdict(m.spec),J=J,seed=seed,parameters=opt.x.tolist(),objective=float(opt.fun),
      success=bool(np.isfinite(opt.fun) and pg<=2.5e-5),optimizer_success=bool(opt.success),
      message=str(opt.message),projected_gradient=pg,iterations=int(nit),solver_passes=attempt+1,
      parameter_count=int((lo!=hi).sum()),elapsed_seconds=time.monotonic()-start,
      ridge=ridge,bound=bound,numerical_bounds=hits)


def predict(result,data,meta):
    m=Model(result['spec'],result['J'],meta,result['bound'])
    if isinstance(m,SwitchingModel):return m.predict(np.asarray(result['parameters']),data)[:2]
    return original.predict(result,data,meta)


def simulate(result,data,meta,rng):
    m=Model(result['spec'],result['J'],meta,result['bound'])
    if isinstance(m,SwitchingModel):return m.simulate(np.asarray(result['parameters']),data,rng)
    return original.simulate(result,data,meta,rng)


def transfer(result,target,meta,seed=0):
    src=Model(result['spec'],result['J'],meta,result['bound']);v0=np.asarray(result['parameters'])
    base_result=dict(result)
    if isinstance(src,SwitchingModel):
        base_result['spec']=asdict(src.base.spec);base_result['parameters']=v0[:src.base.size].tolist()
    if not isinstance(target,SwitchingModel):return original.transfer(base_result,target,meta,seed)
    v=target.start(seed);v[:target.base.size]=original.transfer(base_result,target.base,meta,seed)
    dec=src.decode(v0)
    if isinstance(src,SwitchingModel):
        v[target.slices['level_gap']]=dec['level_gap']
        if 'lower_theta' in target.slices:v[target.slices['lower_theta']]=dec['lower_theta']
        if 'lower_cost' in target.slices:v[target.slices['lower_cost']]=dec['lower_B'].mean(axis=0)
        v[target.slices['initial_logit']]=src.get(v0,'initial_logit')
        if target.kind=='hmm':
            v[target.slices['transition_logits']]=src.get(v0,'transition_logits') if src.kind=='hmm' else src.get(v0,'initial_logit')[0]
    else:
        # Exact static embedding for willingness/unrestricted. A gate start
        # concentrates on the upper state; it is not an exact finite embedding.
        v[target.slices['level_gap']]=0.
        if 'lower_theta' in target.slices:v[target.slices['lower_theta']]=dec['theta']
        if 'lower_cost' in target.slices:v[target.slices['lower_cost']]=dec['B'].mean(axis=0)
        if target.family in ['gate','gatecost']:
            v[target.slices['initial_logit']]=4.
            if target.kind=='hmm':v[target.slices['transition_logits']]=4.
    lo,hi=np.array(target.bounds).T
    return np.clip(v,lo,hi)


def parameters(result,meta,reference_group_weights=None):
    m=Model(result['spec'],result['J'],meta,result['bound'])
    if not isinstance(m,SwitchingModel):return original.parameters(result,meta,reference_group_weights)
    v=np.asarray(result['parameters']);dec=m.decode(v)
    base_result=dict(result,spec=asdict(m.base.spec),parameters=v[:m.base.size].tolist())
    rows,_=original.parameters(base_result,meta)
    for k,r in enumerate(rows):
        r.update(model=m.spec.name,lower_alpha=float(dec['alpha'][k]-dec['level_gap']),
          lower_theta=float(dec['lower_theta'][k]),lower_premium=float(dec['lower_B'][k,0]/10),
          lower_loss=float(dec['lower_B'][k,1]/10),initial_upper=float(np.exp(dec['loginit'][1])),
          entry=float(np.exp(dec['logT'][0,1])),retention=float(np.exp(dec['logT'][1,1])))
    return rows,dec
