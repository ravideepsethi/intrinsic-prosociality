"""Log-domain two-state likelihood: no probability floors in estimation/scoring.

The v1.0.0 parameterisation is preserved. Persistent type is integrated once
per account. Bounds are explicit numerical sensitivities, not type restrictions.
"""
import time
import numpy as np
from numba import njit
from scipy.special import expit
from scipy.optimize import minimize
import hmm as old
from util import log


@njit(cache=True)
def lse(a,b):
    if a==-np.inf:return b
    if b==-np.inf:return a
    if a<b:a,b=b,a
    return a+np.log1p(np.exp(b-a))


@njit(cache=True)
def lsig(x):
    return -np.log1p(np.exp(-x)) if x>=0 else x-np.log1p(np.exp(x))


@njit(cache=True)
def sig(x):
    if x>=0:return 1./(1.+np.exp(-x))
    a=np.exp(x);return a/(1.+a)


@njit(cache=True)
def forward_backward(y,ptr,ee,tt,ii,lp,aw):
    n,J,_=ee.shape;N=len(ptr)-1
    ll=np.zeros(N);ge=np.zeros((n,2));gt=np.zeros((n,2))
    gl=np.zeros(J);gg=np.zeros(J);gi=np.zeros(J);mix=np.zeros(J)
    for i in range(N):
        lo,hi=ptr[i],ptr[i+1];T=hi-lo
        f=np.empty((T,J,2));scales=np.empty((T,J));comp=lp.copy()
        for j in range(J):
            for t in range(T):
                r=lo+t;sign=1. if y[r] else -1.
                if t==0:p0=lsig(-ii[j]);p1=lsig(ii[j])
                else:
                    p0=lse(f[t-1,j,0]+lsig(-tt[r,j,0]),f[t-1,j,1]+lsig(-tt[r,j,1]))
                    p1=lse(f[t-1,j,0]+lsig(tt[r,j,0]),f[t-1,j,1]+lsig(tt[r,j,1]))
                a=p0+lsig(sign*ee[r,j,0]);b=p1+lsig(sign*ee[r,j,1]);c=lse(a,b)
                f[t,j,0]=a-c;f[t,j,1]=b-c;scales[t,j]=c;comp[j]+=c
        total=-np.inf
        for j in range(J):total=lse(total,comp[j])
        ll[i]=total
        if aw[i]==0:continue
        for j in range(J):
            weight=aw[i]*np.exp(comp[j]-total);mix[j]+=weight;lb0=0.;lb1=0.
            for t in range(T-1,-1,-1):
                r=lo+t;a=f[t,j,0]+lb0;b=f[t,j,1]+lb1;c=lse(a,b)
                s0=np.exp(a-c);s1=np.exp(b-c)
                d0=weight*s0*(y[r]-sig(ee[r,j,0]));d1=weight*s1*(y[r]-sig(ee[r,j,1]))
                ge[r,0]+=d0;ge[r,1]+=d1;gl[j]+=d0+d1
                if t==0:gi[j]+=weight*(s1-sig(ii[j]))
                else:
                    sign=1. if y[r] else -1.
                    a=lsig(sign*ee[r,j,0])+lb0;b=lsig(sign*ee[r,j,1])+lb1
                    x00=f[t-1,j,0]+lsig(-tt[r,j,0])+a
                    x01=f[t-1,j,0]+lsig(tt[r,j,0])+b
                    x10=f[t-1,j,1]+lsig(-tt[r,j,1])+a
                    x11=f[t-1,j,1]+lsig(tt[r,j,1])+b
                    norm=lse(lse(x00,x01),lse(x10,x11))
                    p00=np.exp(x00-norm);p01=np.exp(x01-norm)
                    p10=np.exp(x10-norm);p11=np.exp(x11-norm)
                    d0=weight*(p01-sig(tt[r,j,0])*(p00+p01))
                    d1=weight*(p11-sig(tt[r,j,1])*(p10+p11))
                    gt[r,0]+=d0;gt[r,1]+=d1;gg[j]+=d0+d1
                    lb0=lse(lsig(-tt[r,j,0])+a,lsig(tt[r,j,0])+b)-scales[t,j]
                    lb1=lse(lsig(-tt[r,j,1])+a,lsig(tt[r,j,1])+b)-scales[t,j]
    return ll,ge,gt,gl,gg,gi,mix


class Layout(old.Layout):
    def logits(self,v,d):
        z=self.decode(v)
        ee=(np.asarray(d['X']@z['beta'].T)+z['alpha'])[:,None,:]+z['ell'][None,:,None]
        tt=(d['H']@z['transition'].T)[:,None,:]+z['gamma'][None,:,None]
        ii=z['initial'][0]+z['initial'][1]*z['ell']+z['gamma']
        return z,ee,tt,ii

    def objective(self,v,d,ridge=1e-6):
        z,ee,tt,ii=self.logits(v,d);aw=d.get('account_weights',np.ones(len(d['accounts'])));den=aw.sum()
        ll,ge,gt,gl,gg,gi,mix=forward_backward(d['y'],d['ptr'],ee,tt,ii,z['lp'],aw)
        grad=np.zeros_like(v)
        grad[self.s['a']]=[ge.sum(),expit(v[self.s['a']][1])*ge[:,1].sum()]
        grad[self.s['ell']]=(gl+z['initial'][1]*gi)[1:]
        grad[self.s['gamma']]=(gg+gi)[1:]
        grad[self.s['mix']]=(mix-den*np.exp(z['lp']))[1:]
        gb=np.asarray(d['X'].T@ge).T-ridge*den*z['beta']
        grad[self.s['b1']]=gb[1]+(gb[0] if self.family=='willingness' else 0)
        if self.family=='unrestricted':grad[self.s['b0']]=gb[0]
        if self.family=='gate_cost':grad[self.s['b0']]=gb[0,self.cost_indices]
        grad[self.s['transition']]=(d['H'].T@gt).T.ravel()
        grad[self.s['initial']]=[gi.sum(),gi@z['ell']]
        return float(-(aw@ll)/den+ridge*np.sum(z['beta']**2)/2),-grad/den

    def bounds(self,width=20.):
        b=[(-width,width)]*self.size
        b[self.s['a']]=[(-max(16.,2*width),1.),(-max(8.,width),width)]
        return b

    def dispersed(self,seed):
        rng=np.random.default_rng(seed);v=self.start(seed)
        v[self.s['a']]=[rng.uniform(-9,-4),rng.uniform(-2,9)]
        v[self.s['ell']]=rng.uniform(-2,4,self.J-1)
        v[self.s['gamma']]=rng.uniform(-8,3,self.J-1)
        v[self.s['mix']]=rng.uniform(-3,3,self.J-1)
        v[self.s['b1']]=rng.normal(0,.18,self.P)
        if 'b0' in self.s:v[self.s['b0']]=rng.normal(0,.15,self.s['b0'].stop-self.s['b0'].start)
        t=rng.normal(0,.35,(2,self.Q));t[:,0]=[rng.uniform(-5,1),rng.uniform(-1,5)]
        v[self.s['transition']]=t.ravel();v[self.s['initial']]=rng.normal(0,1,2)
        return v


def fit(d,family,J,seed,maxiter=1000,ridge=1e-6,warm=None,width=20.):
    m=Layout(d['X'].shape[1],d['H'].shape[1],J,family,d['cost_indices'])
    v=m.dispersed(seed) if warm is None else np.array(warm,float)
    bounds=m.bounds(width);lo=np.array([b[0] for b in bounds]);hi=np.array([b[1] for b in bounds]);v=np.clip(v,lo,hi)
    begin=time.monotonic();counter=[0]
    def callback(_):
        counter[0]+=1
        if counter[0]%200==0:log(f'{family} bound={width:g} seed={seed}: iteration {counter[0]}')
    opt=minimize(m.objective,v,args=(d,ridge),jac=True,method='L-BFGS-B',bounds=bounds,callback=callback,
      options=dict(maxiter=maxiter,maxls=40,ftol=2e-10,gtol=1e-5,maxcor=20))
    f,g=m.objective(opt.x,d,ridge);projected=opt.x-np.clip(opt.x-g,lo,hi)
    active=np.flatnonzero(np.minimum(abs(opt.x-lo),abs(opt.x-hi))<1e-4).tolist()
    z=m.decode(opt.x)
    return dict(family=family,J=J,seed=int(seed),width=float(width),parameters=opt.x.tolist(),objective=f,
      converged=bool(opt.success),message=str(opt.message),iterations=int(opt.nit),parameter_count=m.size,
      projected_gradient_max=float(abs(projected).max()),boundary_parameters=active,
      alpha=z['alpha'].tolist(),weights=np.exp(z['lp']).tolist(),ell=z['ell'].tolist(),gamma=z['gamma'].tolist(),
      elapsed_seconds=time.monotonic()-begin,likelihood='log_domain_no_probability_floor')


@njit(cache=True)
def filtered(y,ptr,period,ee,tt,ii,lp,received,tau):
    n,J,_=ee.shape;N=len(ptr)-1
    p=np.empty(n);score=np.empty(n);state=np.empty(n);end_train=np.empty((N,J,2))
    entry=np.full(n,np.nan);stay=np.full(n,np.nan)
    state_entry=np.full(n,np.nan);state_stay=np.full(n,np.nan)
    for i in range(N):
        post=np.empty((J,2))
        for j in range(J):post[j,0]=lp[j]+lsig(-ii[j]);post[j,1]=lp[j]+lsig(ii[j])
        end_train[i]=np.exp(post)
        for r in range(ptr[i],ptr[i+1]):
            if r>ptr[i]:
                ce=0.;cs=0.;se=0.;ss=0.
                for j in range(J):
                    d0=tt[r,j,0]-received[r]*tau[0];d1=tt[r,j,1]-received[r]*tau[1]
                    pe=np.exp(post[j,0])*(sig(d0+tau[0])-sig(d0))
                    ps=np.exp(post[j,1])*(sig(d1+tau[1])-sig(d1))
                    diff=sig(ee[r,j,1])-sig(ee[r,j,0]);ce+=pe*diff;cs+=ps*diff;se+=pe;ss+=ps
                    a=lse(post[j,0]+lsig(-tt[r,j,0]),post[j,1]+lsig(-tt[r,j,1]))
                    b=lse(post[j,0]+lsig(tt[r,j,0]),post[j,1]+lsig(tt[r,j,1]))
                    post[j,0]=a;post[j,1]=b
                entry[r]=ce;stay[r]=cs;state_entry[r]=se;state_stay[r]=ss
            l0=-np.inf;l1=-np.inf;norm=-np.inf;s1=-np.inf
            for j in range(J):
                s1=lse(s1,post[j,1])
                for e in range(2):
                    norm=lse(norm,post[j,e]);l0=lse(l0,post[j,e]+lsig(-ee[r,j,e]));l1=lse(l1,post[j,e]+lsig(ee[r,j,e]))
            p[r]=np.exp(l1-norm);state[r]=np.exp(s1-norm);score[r]=(l1 if y[r] else l0)-norm
            denom=l1 if y[r] else l0;sign=1. if y[r] else -1.
            for j in range(J):
                for e in range(2):post[j,e]+=lsig(sign*ee[r,j,e])-denom
            if period[r]==0:end_train[i]=np.exp(post)
    return p,score,state,end_train,entry,stay,state_entry,state_stay


def predict(result,d):
    m=Layout(d['X'].shape[1],d['H'].shape[1],result['J'],result['family'],d['cost_indices'])
    z,ee,tt,ii=m.logits(np.array(result['parameters']),d)
    values=filtered(d['y'],d['ptr'],d['period'],ee,tt,ii,z['lp'],d['H'][:,1],z['transition'][:,1])
    return dict(zip(['probability','log_score','pre_state','train_posterior','receipt_entry_contribution',
                    'receipt_stay_contribution','receipt_state_entry_change','receipt_state_stay_change'],values))


def expected_grants(result,d):
    m=Layout(d['X'].shape[1],d['H'].shape[1],result['J'],result['family'],d['cost_indices'])
    z,ee,tt,ii=m.logits(np.array(result['parameters']),d)
    return expected_kernel(d['ptr'],ee,tt,ii,np.exp(z['lp']))


@njit(cache=True)
def expected_kernel(ptr,ee,tt,ii,weights):
    total=0.;J=len(weights)
    for i in range(len(ptr)-1):
        state=np.empty(J)
        for j in range(J):state[j]=sig(ii[j])
        for r in range(ptr[i],ptr[i+1]):
            for j in range(J):
                if r>ptr[i]:state[j]=(1-state[j])*sig(tt[r,j,0])+state[j]*sig(tt[r,j,1])
                total+=weights[j]*((1-state[j])*sig(ee[r,j,0])+state[j]*sig(ee[r,j,1]))
    return total


def simulate(result,d,seed):
    m=Layout(d['X'].shape[1],d['H'].shape[1],result['J'],result['family'],d['cost_indices'])
    z,ee,tt,ii=m.logits(np.array(result['parameters']),d)
    return simulate_kernel(d['ptr'],ee,tt,ii,np.exp(z['lp']),seed)


@njit(cache=True)
def simulate_kernel(ptr,ee,tt,ii,weights,seed):
    np.random.seed(seed);y=np.zeros(len(ee));cum=np.cumsum(weights)
    for i in range(len(ptr)-1):
        j=min(np.searchsorted(cum,np.random.random()),len(weights)-1);e=int(np.random.random()<sig(ii[j]))
        for r in range(ptr[i],ptr[i+1]):
            if r>ptr[i]:e=int(np.random.random()<sig(tt[r,j,e]))
            y[r]=int(np.random.random()<sig(ee[r,j,e]))
    return y
