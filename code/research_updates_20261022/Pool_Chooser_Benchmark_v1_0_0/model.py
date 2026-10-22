"""Panel mixtures with analytic gradients and exact bin-integrated perception.

Costs are parameterized by a unit-length common direction and nonnegative
type amplitudes. Reporting maps these to E_G[beta]=1 without a redundant scale.
All likelihood calculations mix once per account, not once per opportunity.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import time
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp, ndtr
from numba import njit
from prepare import C0, C1, B_EDGES


@dataclass(frozen=True)
class Spec:
    name: str
    heterogeneity: str = 'both'
    surface: str = 'separable'
    cost: str = 'full'
    perception: bool = False
    tier_priors: bool = False
    pure_perception: bool = False


CORE = [Spec('level','level'),Spec('desert','desert'),Spec('cost','cost'),Spec('both'),
        Spec('free_index',surface='free'),Spec('type_cells',surface='type_cells'),
        Spec('no_cost',cost='none'),Spec('premium_only',cost='premium'),
        Spec('separate_costs',cost='separate'),Spec('signed_costs',cost='signed')]
PERCEPTION = [Spec('accurate_tiers',tier_priors=True),
              Spec('noisy_tiers',perception=True,tier_priors=True),
              Spec('accurate_common',pure_perception=True),
              Spec('noisy_common',perception=True,pure_perception=True)]


def normal_weights(b, sigma):
    """Stable normal-CDF differences and derivatives wrt sigma in cp units."""
    b=np.asarray(b,float);sigma=np.asarray(sigma,float)
    safe=np.maximum(sigma,1e-8)
    z=(np.asarray(B_EDGES)[None,:]-b[:,None])/safe[:,None]
    left,right=z[:,:-1],z[:,1:]
    w=np.where(left>=0,ndtr(-left)-ndtr(-right),ndtr(right)-ndtr(left))
    def zphi(x):
        finite=np.isfinite(x)
        a=np.where(finite,x,0.)
        return np.where(finite,a*np.exp(-.5*a*a)/np.sqrt(2*np.pi),0.)
    dw=(zphi(left)-zphi(right))/safe[:,None]
    zero=sigma<=0
    if np.any(zero):
        w[zero]=0.;w[np.where(zero)[0],np.searchsorted(B_EDGES[1:-1],b[zero],side='right')]=1.
        dw[zero]=0.
    return np.maximum(w,0.),dw


@njit(cache=True)
def forward_filter(logp,logq,y,ptr,group,lp):
    n=len(y);J=logp.shape[1];pred=np.empty(n);scores=np.empty(n)
    for i in range(len(ptr)-1):
        post=lp[group[i]].copy()
        for r in range(ptr[i],ptr[i+1]):
            top=-np.inf
            for k in range(J): top=max(top,post[k]+logp[r,k])
            total=0.
            for k in range(J): total+=np.exp(post[k]+logp[r,k]-top)
            lpred=top+np.log(total)
            pred[r]=np.exp(lpred)
            for k in range(J): post[k]+=logp[r,k] if y[r] else logq[r,k]
            top=np.max(post);total=np.exp(post-top).sum();norm=top+np.log(total)
            scores[r]=norm
            post-=norm
    return pred,scores


class Model:
    def __init__(self,spec,J,meta,bound=12.):
        self.spec=spec if isinstance(spec,Spec) else Spec(**spec)
        self.J=J;self.meta=meta;self.bound=float(bound)
        self.support=np.array(meta['support'],int)
        self.free_cells=self.support[~np.isin(self.support,[C0,C1])]
        self.nonref=self.support[self.support!=C0]
        self.cols=np.array([i for i,n in enumerate(meta['z_names'])
                           if not(self.spec.pure_perception and n in ['rating','rating_missing'])],int)
        self.slices={};self.bounds=[];self.names=[]
        def add(name,n,lo,hi):
            a=len(self.bounds);self.slices[name]=slice(a,a+n)
            self.bounds.extend([(lo,hi)]*n);self.names.extend([name+':'+str(i) for i in range(n)])
        add('alpha',J,-2*bound,2*bound/3)
        self.common_theta=self.spec.heterogeneity in ['level','cost']
        if self.spec.surface!='type_cells':
            add('theta',1 if self.common_theta else J,0.,bound)
            if self.spec.surface=='free': add('A',len(self.free_cells),-bound,bound)
            else:
                if self.spec.surface=='separable':
                    add('f0',1,0.,1.-.6/bound)
                    add('fother',3,0.,bound)
                add('g',3,0.,bound);add('h',4,0.,bound)
        else: add('cell_effect',J*len(self.nonref),-bound,bound)
        self.common_cost=self.spec.heterogeneity in ['level','desert']
        if self.spec.cost in ['separate','signed']:
            add('cost_pair',2*J,-bound if self.spec.cost=='signed' else 0.,bound)
        elif self.spec.cost!='none':
            add('amplitude',1 if self.common_cost else J,0.,bound)
            if self.spec.cost=='full':add('angle',1,0.,np.pi/2)
        add('eta',len(self.cols),-bound,bound)
        self.groups=4 if self.spec.tier_priors else 1
        add('prior',self.groups*(J-1),-4*bound/3,4*bound/3)
        if self.spec.perception:add('sigma',4,0.,5*bound/3)
        self.size=len(self.bounds)
        self.cells=np.arange(100);self.bcell=self.cells//20
        self.pcell=(self.cells//5)%4;self.qcell=self.cells%5

    def get(self,v,key): return v[self.slices[key]]

    def start(self,seed):
        rng=np.random.default_rng(seed);v=np.zeros(self.size)
        v[self.slices['alpha']]=np.linspace(-6.7,-2.3,self.J)+rng.normal(0,.25,self.J)
        if 'theta' in self.slices:v[self.slices['theta']]=rng.uniform(.3,1.5,self.slices['theta'].stop-self.slices['theta'].start)
        if 'f0' in self.slices:v[self.slices['f0']]=.1
        if 'fother' in self.slices:v[self.slices['fother']]=[.45,1.3,1.6]
        if 'g' in self.slices:v[self.slices['g']]=[1.3,1.15,.9]
        if 'h' in self.slices:v[self.slices['h']]=[1.15,1.1,.9,.8]
        if 'A' in self.slices:v[self.slices['A']]=self.bcell[self.free_cells]/2
        if 'cell_effect' in self.slices:
            v[self.slices['cell_effect']]=(np.linspace(.3,1.5,self.J)[:,None]*self.bcell[self.nonref][None,:]/2).ravel()
        if 'amplitude' in self.slices:v[self.slices['amplitude']]=rng.uniform(.01,.15,self.slices['amplitude'].stop-self.slices['amplitude'].start)
        if 'angle' in self.slices:v[self.slices['angle']]=.2
        if 'cost_pair' in self.slices:v[self.slices['cost_pair']]=.03
        if self.J>1:v[self.slices['prior']]=np.tile(-np.arange(1,self.J)*1.2,self.groups)
        if 'sigma' in self.slices:v[self.slices['sigma']]=rng.uniform(.3,2.,4)
        return v

    def decode(self,v):
        J=self.J
        raw=np.c_[np.zeros(self.groups),self.get(v,'prior').reshape(self.groups,J-1)]
        lp=raw-logsumexp(raw,axis=1)[:,None]
        a=self.get(v,'alpha').copy();eta=self.get(v,'eta');raw_theta=None;index_offset=None
        if self.spec.surface=='type_cells':
            effect=np.zeros((J,100));effect[:,self.nonref]=self.get(v,'cell_effect').reshape(J,-1)
            A=None;theta=None;ijac={}
        else:
            theta=self.get(v,'theta');theta=np.repeat(theta,J) if self.common_theta else theta
            if self.spec.surface=='free':
                A=np.zeros(100);A[C1]=1.;A[self.free_cells]=self.get(v,'A');ijac={}
            else:
                if self.spec.surface=='calibrated':
                    f=np.asarray(self.meta['board_factor'],float);f=f/f[2]
                else:
                    f=np.ones(5);f[0]=self.get(v,'f0')[0];f[[1,3,4]]=self.get(v,'fother')
                g=np.ones(4);g[[0,1,3]]=self.get(v,'g')
                h=np.ones(5);h[[0,1,3,4]]=self.get(v,'h')
                fb,gp,hq=f[self.bcell],g[self.pcell],h[self.qcell]
                den=1-f[0];A=(fb*gp*hq-f[0])/den
                # Optimize in raw-product utility units. This avoids a poorly
                # conditioned 1/(1-f0) in the likelihood; report anchored units.
                raw_theta=theta.copy();index_offset=float(f[0])
                a=a+raw_theta*f[0]
                theta=raw_theta*den
                ijac=dict(g=np.column_stack([(self.pcell==p)*fb*hq/den for p in [0,1,3]]),
                          h=np.column_stack([(self.qcell==q)*fb*gp/den for q in [0,1,3,4]]))
                if self.spec.surface=='separable':
                    ijac['f0']=((self.bcell==0)*gp*hq-1+A)[:,None]/den
                    ijac['fother']=np.column_stack([(self.bcell==b)*gp*hq/den for b in [1,3,4]])
            effect=theta[:,None]*A[None,:]
        if self.spec.cost=='none':B=np.zeros((J,2));amp=None;angle=0.
        elif self.spec.cost in ['separate','signed']:
            B=self.get(v,'cost_pair').reshape(J,2);amp=None;angle=0.
        else:
            amp=self.get(v,'amplitude');amp=np.repeat(amp,J) if self.common_cost else amp
            angle=self.get(v,'angle')[0] if self.spec.cost=='full' else 0.
            B=amp[:,None]*np.array([np.cos(angle),np.sin(angle)])[None,:]
        sigma=self.get(v,'sigma')*100 if self.spec.perception else np.zeros(4)
        return dict(alpha=a,theta=theta,raw_theta=raw_theta,index_offset=index_offset,
          A=A,ijac=ijac,effect=effect,B=B,amplitude=amp,angle=angle,eta=eta,lp=lp,sigma=sigma)

    def emissions(self,v,d,gradients=False):
        dec=self.decode(v)
        m=dec['alpha'][None,:]+(d['Z'][:,self.cols]@dec['eta'])[:,None]-d['kappa'][:,None]*dec['B'][None,:,0]-d['loss'][:,None]*dec['B'][None,:,1]
        if not self.spec.perception:
            U=m+dec['effect'][:,d['cell']].T
            logp=-np.logaddexp(0.,-U);logq=-np.logaddexp(0.,U)
            return logp,logq,dict(dec=dec,U=U)
        w,dw=normal_weights(d['b'],dec['sigma'][d['tier']])
        candidate=(np.arange(5)[None,:]*4+d['stage'][:,None])*5+d['q'][:,None]
        U=m[:,:,None]+np.transpose(dec['effect'][:,candidate],(1,0,2))
        logw=np.full_like(w,-np.inf);np.log(w,out=logw,where=w>0)
        lpj=-np.logaddexp(0.,-U);lqj=-np.logaddexp(0.,U)
        logp=logsumexp(logw[:,None,:]+lpj,axis=2)
        logq=logsumexp(logw[:,None,:]+lqj,axis=2)
        return logp,logq,dict(dec=dec,U=U,w=w,dw=dw,candidate=candidate,logw=logw,lpj=lpj,lqj=lqj)

    def objective(self,v,d,ridge=1e-6):
        logp,logq,cache=self.emissions(v,d,True);dec=cache['dec']
        y=d['y'];obs=np.where(y[:,None]>0,logp,logq)
        group=d['group'] if self.spec.tier_priors else np.zeros(len(d['ptr'])-1,int)
        ell=np.add.reduceat(obs,d['ptr'][:-1],axis=0)+dec['lp'][group]
        lli=logsumexp(ell,axis=1);post=np.exp(ell-lli[:,None])
        aw=d.get('aw',np.ones(len(lli)));den=aw.sum()
        if den<=0: raise ValueError('No positively weighted accounts')
        mass=post[d['ids']]*aw[d['ids'],None]
        gc=np.zeros((self.J,100));g=np.zeros(self.size)
        if not self.spec.perception:
            R=(y[:,None]-expit(cache['U']))*mass
            for k in range(self.J):gc[k]=np.bincount(d['cell'],weights=R[:,k],minlength=100)
        else:
            # Conditional responsibility for a perceived board bin, given y and type.
            obin=np.where(y[:,None,None]>0,cache['lpj'],cache['lqj'])
            rbin=np.exp(cache['logw'][:,None,:]+obin-obs[:,:,None])
            Rbin=rbin*(y[:,None,None]-expit(cache['U']))*mass[:,:,None]
            R=Rbin.sum(axis=2)
            for k in range(self.J):gc[k]=np.bincount(cache['candidate'].ravel(),weights=Rbin[:,k,:].ravel(),minlength=100)
            dlogw=np.divide(cache['dw'],cache['w'],out=np.zeros_like(cache['w']),where=cache['w']>1e-300)
            gs=(rbin*dlogw[:,None,:]*mass[:,:,None]).sum(axis=(1,2))*100
            g[self.slices['sigma']]=np.bincount(d['tier'],weights=gs,minlength=4)
        g[self.slices['alpha']]=R.sum(axis=0)
        g[self.slices['eta']]=d['Z'][:,self.cols].T@R.sum(axis=1)
        if self.spec.surface=='type_cells':g[self.slices['cell_effect']]=gc[:,self.nonref].ravel()
        else:
            gt=gc@dec['A']
            gt_raw=gt if dec['raw_theta'] is None else gt*(1-dec['index_offset'])+R.sum(axis=0)*dec['index_offset']
            g[self.slices['theta']]=gt_raw.sum() if self.common_theta else gt_raw
            ga=dec['theta']@gc
            if self.spec.surface=='free':g[self.slices['A']]=ga[self.free_cells]
            else:
                for key,jac in dec['ijac'].items():g[self.slices[key]]=ga@jac
                if 'f0' in self.slices:g[self.slices['f0']]+=np.sum((R.sum(axis=0)-gt)*dec['raw_theta'])
        gb=-np.column_stack([R.T@d['kappa'],R.T@d['loss']])
        if self.spec.cost in ['separate','signed']:g[self.slices['cost_pair']]=gb.ravel()
        elif self.spec.cost!='none':
            angle=dec['angle'];direction=np.array([np.cos(angle),np.sin(angle)])
            gt=gb@direction;g[self.slices['amplitude']]=gt.sum() if self.common_cost else gt
            if self.spec.cost=='full':g[self.slices['angle']]=np.sum(gb*dec['amplitude'][:,None]*np.array([-np.sin(angle),np.cos(angle)]))
        gp=np.zeros((self.groups,self.J))
        for h in range(self.groups):
            mask=group==h;gp[h]=(post[mask]*aw[mask,None]).sum(axis=0)-aw[mask].sum()*np.exp(dec['lp'][h])
        g[self.slices['prior']]=gp[:,1:].ravel()
        # Scale-invariant surface regularization: penalize identified cell effects,
        # actual cost coefficients and controls, not arbitrary factor scales.
        effects=dec['effect'][:,self.support]
        penalty=.5*ridge*(np.mean(effects**2)+np.mean(dec['B']**2)+np.sum(dec['eta']**2))
        pg=np.zeros_like(g);pec=np.zeros_like(gc)
        pec[:,self.support]=ridge*effects/effects.size
        if self.spec.surface=='type_cells':pg[self.slices['cell_effect']]=pec[:,self.nonref].ravel()
        else:
            pt=pec@dec['A']
            pt_raw=pt if dec['raw_theta'] is None else pt*(1-dec['index_offset'])
            pg[self.slices['theta']]=pt_raw.sum() if self.common_theta else pt_raw
            pa=dec['theta']@pec
            if self.spec.surface=='free':pg[self.slices['A']]=pa[self.free_cells]
            else:
                for key,jac in dec['ijac'].items():pg[self.slices[key]]=pa@jac
                if 'f0' in self.slices:pg[self.slices['f0']]-=np.sum(pt*dec['raw_theta'])
        pb=ridge*dec['B']/dec['B'].size
        if self.spec.cost in ['separate','signed']:pg[self.slices['cost_pair']]=pb.ravel()
        elif self.spec.cost!='none':
            pt=pb@np.array([np.cos(dec['angle']),np.sin(dec['angle'])])
            pg[self.slices['amplitude']]=pt.sum() if self.common_cost else pt
            if self.spec.cost=='full':pg[self.slices['angle']]=np.sum(pb*dec['amplitude'][:,None]*np.array([-np.sin(dec['angle']),np.cos(dec['angle'])]))
        pg[self.slices['eta']]=ridge*dec['eta']
        return float(-aw@lli/den+penalty),-g/den+pg


def fit(d,spec,J,meta,seed,maxiter=600,ridge=1e-6,bound=12.,warm=None):
    m=Model(spec,J,meta,bound);v=m.start(seed) if warm is None else np.asarray(warm,float).copy()
    v=np.clip(v,np.array(m.bounds)[:,0],np.array(m.bounds)[:,1])
    begin=time.monotonic()
    lo=np.array(m.bounds)[:,0];hi=np.array(m.bounds)[:,1]
    total_iterations=0
    # A function-tolerance stop is not by itself convergence. Reset the limited
    # memory and polish, at most twice, then require a projected-gradient check.
    for attempt in range(3):
        opt=minimize(m.objective,v,args=(d,ridge),jac=True,method='L-BFGS-B',bounds=m.bounds,
                     options=dict(maxiter=maxiter,ftol=1e-12 if attempt==0 else 0.,
                                  gtol=2e-5,maxls=50,maxcor=20))
        total_iterations+=opt.nit
        grad=opt.jac.copy()
        grad[(opt.x<=lo+1e-7)&(grad>0)]=0
        grad[(opt.x>=hi-1e-7)&(grad<0)]=0
        pg=float(np.max(abs(grad)))
        if not np.isfinite(opt.fun) or pg<=2.5e-5:break
        v=opt.x.copy()
    structural={'theta','amplitude','angle','f0','fother','g','h','sigma','cost_pair'}
    if m.spec.cost=='signed':structural.remove('cost_pair')
    lower=[m.names[i] for i in range(m.size) if abs(opt.x[i]-lo[i])<1e-5 and m.names[i].split(':')[0] not in structural]
    upper=[m.names[i] for i in range(m.size) if abs(opt.x[i]-hi[i])<1e-5 and m.names[i].split(':')[0]!='angle']
    return dict(spec=asdict(m.spec),J=J,seed=seed,parameters=opt.x.tolist(),objective=float(opt.fun),
      success=bool(np.isfinite(opt.fun) and pg<=2.5e-5),optimizer_success=bool(opt.success),
      message=str(opt.message),projected_gradient=pg,iterations=int(total_iterations),
      solver_passes=attempt+1,parameter_count=m.size,
      elapsed_seconds=time.monotonic()-begin,ridge=ridge,bound=bound,numerical_bounds=lower+upper)


def predict(result,d,meta):
    m=Model(result['spec'],result['J'],meta,result['bound'])
    logp,logq,cache=m.emissions(np.asarray(result['parameters']),d)
    group=d['group'] if m.spec.tier_priors else np.zeros(len(d['ptr'])-1,np.int64)
    p,ll=forward_filter(logp,logq,d['y'],d['ptr'],group,cache['dec']['lp'])
    return p,ll


def simulate(result,d,meta,rng):
    m=Model(result['spec'],result['J'],meta,result['bound'])
    logp,_,cache=m.emissions(np.asarray(result['parameters']),d)
    group=d['group'] if m.spec.tier_priors else np.zeros(len(d['ptr'])-1,int)
    weights=np.exp(cache['dec']['lp'][group])
    latent=(rng.random(len(group))[:,None]>np.cumsum(weights,axis=1)).sum(axis=1)
    probabilities=np.exp(logp[np.arange(len(d['y'])),latent[d['ids']]])
    out=dict(d);out['y']=(rng.random(len(probabilities))<probabilities).astype(float)
    return out,latent,probabilities


def parameters(result,meta,reference_group_weights=None):
    m=Model(result['spec'],result['J'],meta,result['bound']);dec=m.decode(np.asarray(result['parameters']))
    weights=np.exp(dec['lp'])
    nu=np.ones(m.groups)/m.groups if reference_group_weights is None else np.asarray(reference_group_weights)
    if m.groups==1:nu=np.ones(1)
    w=nu@weights
    amp=dec['amplitude'];mean=float(w@amp) if amp is not None else None
    rows=[]
    for k in range(m.J):
        rows.append(dict(model=m.spec.name,type=k,share=float(w[k]),alpha=float(dec['alpha'][k]),
          theta=float(dec['theta'][k]) if dec['theta'] is not None else None,
          premium_coefficient=float(dec['B'][k,0]/10),loss_coefficient=float(dec['B'][k,1]/10),
          normalized_cost_multiplier=float(amp[k]/mean) if mean is not None and mean>1e-8 else None,
          state_effect_range=float(np.ptp(dec['effect'][k,m.support])),
          cost_identified=bool(np.linalg.norm(dec['B'])>1e-8)))
    return rows,dec


def transfer(result,target,meta,seed=0):
    """Nested starts where possible; an approximation otherwise, never a fit claim."""
    src=Model(result['spec'],result['J'],meta,result['bound'])
    dec=src.decode(np.asarray(result['parameters']))
    dst=target;v=dst.start(seed)
    v[dst.slices['alpha']]=dec['alpha']
    if 'theta' in dst.slices and dec['theta'] is not None:
        v[dst.slices['theta']]=dec['theta'].mean() if dst.common_theta else dec['theta']
    if dst.spec.surface=='type_cells':v[dst.slices['cell_effect']]=dec['effect'][:,dst.nonref].ravel()
    elif dst.spec.surface=='free' and dec['A'] is not None:v[dst.slices['A']]=dec['A'][dst.free_cells]
    elif dst.spec.surface==src.spec.surface:
        for key in ['f0','fother','g','h']:
            if key in dst.slices:v[dst.slices[key]]=src.get(np.asarray(result['parameters']),key)
    if 'cost_pair' in dst.slices:v[dst.slices['cost_pair']]=dec['B'].ravel()
    elif 'amplitude' in dst.slices:
        mean=dec['B'].mean(axis=0)
        angle=np.arctan2(max(mean[1],0),max(mean[0],1e-10)) if dst.spec.cost=='full' else 0.
        amp=dec['B']@np.array([np.cos(angle),np.sin(angle)])
        v[dst.slices['amplitude']]=amp.mean() if dst.common_cost else amp
        if 'angle' in dst.slices:v[dst.slices['angle']]=angle
    emap={c:dec['eta'][j] for j,c in enumerate(src.cols)}
    v[dst.slices['eta']]=[emap.get(c,0.) for c in dst.cols]
    weights=np.exp(dec['lp'])
    weights=np.tile(weights.mean(axis=0),(dst.groups,1)) if dst.groups!=src.groups else weights
    v[dst.slices['prior']]=(np.log(weights[:,1:])-np.log(weights[:,:1])).ravel()
    if 'sigma' in dst.slices and src.spec.perception:v[dst.slices['sigma']]=dec['sigma']/100
    if dst.spec.surface in ['separable','calibrated'] and dec['theta'] is not None:
        f0=dst.get(v,'f0')[0] if dst.spec.surface=='separable' else meta['board_factor'][0]/meta['board_factor'][2]
        anchored_theta=v[dst.slices['theta']].copy()
        raw_theta=anchored_theta/(1-f0)
        v[dst.slices['theta']]=raw_theta
        v[dst.slices['alpha']]=dec['alpha']-raw_theta*f0
    return np.clip(v,np.array(dst.bounds)[:,0],np.array(dst.bounds)[:,1])
