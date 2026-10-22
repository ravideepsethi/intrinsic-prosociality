"""Two-state mixed logit. Persistent type is integrated once per account.

Forward/backward scores are analytic; Numba accelerates only numeric loops.
No latent-state assignment is used as an observed outcome in a test.
"""
from __future__ import annotations
import time
import numpy as np
from numba import njit
from scipy.optimize import minimize
from scipy.special import expit, logsumexp
from util import log


@njit(cache=True)
def fb(y, ptr, pe, pt, initial, logweights, account_weights):
    n, J, _ = pe.shape
    N = len(ptr)-1
    ll = np.zeros(N)
    ge = np.zeros((n, 2)); gt = np.zeros((n, 2))
    gl = np.zeros(J); gg = np.zeros(J); gi = np.zeros(J)
    mix = np.zeros(J); posterior = np.zeros((N, J))
    for i in range(N):
        lo, hi = ptr[i], ptr[i+1]; T = hi-lo
        if T == 0:
            for j in range(J): posterior[i,j] = np.exp(logweights[j])
            continue
        f = np.empty((T,J,2)); scales = np.empty((T,J))
        comp = logweights.copy()
        for j in range(J):
            for t in range(T):
                r = lo+t
                if t == 0:
                    pre1 = initial[j]
                else:
                    pre1 = f[t-1,j,0]*pt[r,j,0]+f[t-1,j,1]*pt[r,j,1]
                e0 = pe[r,j,0] if y[r] else 1-pe[r,j,0]
                e1 = pe[r,j,1] if y[r] else 1-pe[r,j,1]
                z0 = (1-pre1)*e0; z1 = pre1*e1
                c = max(z0+z1, 1e-300)
                f[t,j,0] = z0/c; f[t,j,1] = z1/c
                scales[t,j] = c; comp[j] += np.log(c)
        largest = np.max(comp); denom = np.sum(np.exp(comp-largest))
        ll[i] = largest+np.log(denom)
        for j in range(J):
            post = np.exp(comp[j]-ll[i]); posterior[i,j] = post
            weight = account_weights[i]*post
            mix[j] += weight
            b0 = 1.; b1 = 1.
            for t in range(T-1,-1,-1):
                r = lo+t
                s0 = f[t,j,0]*b0; s1 = f[t,j,1]*b1
                norm = max(s0+s1,1e-300); s0 /= norm; s1 /= norm
                d0 = weight*s0*(y[r]-pe[r,j,0])
                d1 = weight*s1*(y[r]-pe[r,j,1])
                ge[r,0] += d0; ge[r,1] += d1; gl[j] += d0+d1
                if t == 0:
                    gi[j] += weight*(s1-initial[j])
                else:
                    e0 = pe[r,j,0] if y[r] else 1-pe[r,j,0]
                    e1 = pe[r,j,1] if y[r] else 1-pe[r,j,1]
                    a = e0*b0/scales[t,j]; b = e1*b1/scales[t,j]
                    x00=f[t-1,j,0]*(1-pt[r,j,0])*a
                    x01=f[t-1,j,0]*pt[r,j,0]*b
                    x10=f[t-1,j,1]*(1-pt[r,j,1])*a
                    x11=f[t-1,j,1]*pt[r,j,1]*b
                    d0=weight*(x01-pt[r,j,0]*(x00+x01))
                    d1=weight*(x11-pt[r,j,1]*(x10+x11))
                    gt[r,0]+=d0; gt[r,1]+=d1; gg[j]+=d0+d1
                    b0=(1-pt[r,j,0])*a+pt[r,j,0]*b
                    b1=(1-pt[r,j,1])*a+pt[r,j,1]*b
    return ll,ge,gt,gl,gg,gi,mix,posterior


@njit(cache=True)
def filter_forecasts(y, ptr, period, pe, pt, initial, weights):
    n,J,_=pe.shape; N=len(ptr)-1
    prob=np.empty(n); pre_state=np.empty(n)
    end_train=np.empty((N,J,2)); ll=np.zeros(N)
    for i in range(N):
        post=np.empty((J,2))
        for j in range(J):
            post[j,0]=weights[j]*(1-initial[j]);post[j,1]=weights[j]*initial[j]
        end_train[i]=post
        for r in range(ptr[i],ptr[i+1]):
            if r>ptr[i]:
                for j in range(J):
                    mass=post[j,0]+post[j,1]
                    one=post[j,0]*pt[r,j,0]+post[j,1]*pt[r,j,1]
                    post[j,0]=mass-one;post[j,1]=one
            p=0.;one=0.
            for j in range(J):
                p+=post[j,0]*pe[r,j,0]+post[j,1]*pe[r,j,1]
                one+=post[j,1]
            prob[r]=min(max(p,1e-12),1-1e-12);pre_state[r]=one
            c=0.
            for j in range(J):
                for e in range(2):
                    post[j,e]*=pe[r,j,e] if y[r] else 1-pe[r,j,e]
                    c+=post[j,e]
            c=max(c,1e-300);post/=c;ll[i]+=np.log(c)
            if period[r]==0:end_train[i]=post
    return prob,pre_state,end_train,ll


class Layout:
    def __init__(self,P,Q,J,family,cost_indices=()):
        self.P,self.Q,self.J,self.family=P,Q,J,family
        self.cost_indices=np.asarray(cost_indices,dtype=int)
        self.s={}; self.size=0
        def add(name,n):
            self.s[name]=slice(self.size,self.size+n);self.size+=n
        add('a',2);add('ell',J-1);add('gamma',J-1);add('mix',J-1)
        add('b1',P)
        if family=='unrestricted':add('b0',P)
        elif family=='gate_cost':add('b0',len(self.cost_indices))
        elif family not in ('gate','willingness'):raise ValueError(family)
        add('transition',2*Q);add('initial',2)

    def decode(self,v):
        a=v[self.s['a']];ell=np.r_[0.,v[self.s['ell']]]
        gamma=np.r_[0.,v[self.s['gamma']]]
        logits=np.r_[0.,v[self.s['mix']]];lp=logits-logsumexp(logits)
        beta=np.zeros((2,self.P));beta[1]=v[self.s['b1']]
        if self.family=='willingness':beta[0]=beta[1]
        elif self.family=='unrestricted':beta[0]=v[self.s['b0']]
        elif self.family=='gate_cost':beta[0,self.cost_indices]=v[self.s['b0']]
        return dict(alpha=np.array([a[0],a[0]+np.logaddexp(0,a[1])]),ell=ell,
                    gamma=gamma,lp=lp,beta=beta,
                    transition=v[self.s['transition']].reshape(2,self.Q),
                    initial=v[self.s['initial']])

    def probabilities(self,v,d):
        z=self.decode(v)
        base=np.asarray(d['X']@z['beta'].T)+z['alpha']
        pe=expit(base[:,None,:]+z['ell'][None,:,None])
        trans=d['H']@z['transition'].T
        pt=expit(trans[:,None,:]+z['gamma'][None,:,None])
        initial=expit(z['initial'][0]+z['initial'][1]*z['ell']+z['gamma'])
        return z,pe,pt,initial

    def objective(self,v,d,ridge=1e-6):
        z,pe,pt,initial=self.probabilities(v,d)
        aw=d.get('account_weights',np.ones(len(d['ptr'])-1));den=aw.sum()
        ll,ge,gt,gl,gg,gi,mix,_=fb(d['y'],d['ptr'],pe,pt,initial,z['lp'],aw)
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
        loss=-(aw@ll)/den+ridge*np.sum(z['beta']**2)/2
        return float(loss),-grad/den

    def start(self,seed):
        rng=np.random.default_rng(seed);v=np.zeros(self.size)
        v[self.s['a']]=[-6.5,2.]
        v[self.s['ell']]=np.linspace(.5,2.,self.J-1)+rng.normal(0,.2,self.J-1)
        v[self.s['gamma']]=rng.normal(0,.5,self.J-1)
        v[self.s['mix']]=-np.arange(1,self.J)*1.2
        v[self.s['b1']]=rng.normal(0,.04,self.P)
        if 'b0' in self.s:v[self.s['b0']]=rng.normal(0,.04,self.s['b0'].stop-self.s['b0'].start)
        trans=np.zeros((2,self.Q));trans[:,0]=[-3.,1.5]
        if self.Q>1:trans[:,1]=.25
        v[self.s['transition']]=trans.ravel();v[self.s['initial']]=[-2.,.3]
        v+=rng.normal(0,.03,self.size)
        return v

    def bounds(self):
        b=[(-7.,7.)]*self.size
        b[self.s['a']]=[(-16.,1.),(-8.,7.)]
        return b


def fit(d,family,J,seed,maxiter=400,ridge=1e-6,warm=None):
    layout=Layout(d['X'].shape[1],d['H'].shape[1],J,family,d.get('cost_indices',()))
    v=layout.start(seed) if warm is None else np.asarray(warm,float).copy()
    begin=time.monotonic();iteration=[0]
    def callback(_):
        iteration[0]+=1
        if iteration[0]%50==0:log(f'{family} J={J} start={seed}: iteration {iteration[0]}, {(time.monotonic()-begin)/60:.1f} min')
    opt=minimize(layout.objective,v,args=(d,ridge),jac=True,method='L-BFGS-B',bounds=layout.bounds(),
                 callback=callback,options={'maxiter':maxiter,'maxls':30,'ftol':1e-9,'gtol':2e-5,'maxcor':15})
    z=layout.decode(opt.x);boundary=[k for k,(lo,hi) in enumerate(layout.bounds()) if min(abs(opt.x[k]-lo),abs(opt.x[k]-hi))<1e-4]
    return dict(family=family,J=J,seed=seed,parameters=opt.x.tolist(),objective=float(opt.fun),
                converged=bool(opt.success),message=str(opt.message),iterations=int(opt.nit),
                boundary_parameters=boundary,weights=np.exp(z['lp']).tolist(),
                alpha=z['alpha'].tolist(),ell=z['ell'].tolist(),gamma=z['gamma'].tolist(),
                elapsed_seconds=time.monotonic()-begin,parameter_count=len(opt.x))


def predict(fit_result,d):
    layout=Layout(d['X'].shape[1],d['H'].shape[1],fit_result['J'],fit_result['family'],d.get('cost_indices',()))
    z,pe,pt,initial=layout.probabilities(np.array(fit_result['parameters']),d)
    p,e,q,ll=filter_forecasts(d['y'],d['ptr'],d['period'],pe,pt,initial,np.exp(z['lp']))
    base=d['H']@z['transition'].T-d['H'][:,1,None]*z['transition'][None,:,1]
    pt0=expit(base[:,None,:]+z['gamma'][None,:,None])
    pt1=expit(base[:,None,:]+z['gamma'][None,:,None]+z['transition'][None,None,:,1])
    r0,r1=receipt_contrasts(d['y'],d['ptr'],pe,pt,pt0,pt1,initial,np.exp(z['lp']))
    return p,dict(pre_state=e,train_posterior=q,log_likelihood=ll,receipt_input_0=r0,receipt_input_1=r1)


@njit(cache=True)
def receipt_contrasts(y,ptr,pe,pt,pt0,pt1,initial,weights):
    n,J,_=pe.shape;p0=np.empty(n);p1=np.empty(n)
    for i in range(len(ptr)-1):
        post=np.empty((J,2))
        for j in range(J):post[j,0]=weights[j]*(1-initial[j]);post[j,1]=weights[j]*initial[j]
        for r in range(ptr[i],ptr[i+1]):
            a=0.;b=0.
            if r>ptr[i]:
                for j in range(J):
                    mass=post[j,0]+post[j,1]
                    one0=post[j,0]*pt0[r,j,0]+post[j,1]*pt0[r,j,1]
                    one1=post[j,0]*pt1[r,j,0]+post[j,1]*pt1[r,j,1]
                    a+=(mass-one0)*pe[r,j,0]+one0*pe[r,j,1]
                    b+=(mass-one1)*pe[r,j,0]+one1*pe[r,j,1]
                    one=post[j,0]*pt[r,j,0]+post[j,1]*pt[r,j,1]
                    post[j,0]=mass-one;post[j,1]=one
                p0[r]=a;p1[r]=b
            else:p0[r]=np.nan;p1[r]=np.nan
            c=0.
            for j in range(J):
                for e in range(2):post[j,e]*=pe[r,j,e] if y[r] else 1-pe[r,j,e];c+=post[j,e]
            post/=max(c,1e-300)
    return p0,p1


def embed(result,target,d):
    src=Layout(d['X'].shape[1],d['H'].shape[1],result['J'],result['family'],d.get('cost_indices',()))
    dst=Layout(src.P,src.Q,src.J,target,src.cost_indices);a=np.array(result['parameters']);b=dst.start(result['seed'])
    for k in ('a','ell','gamma','mix','b1','transition','initial'):b[dst.s[k]]=a[src.s[k]]
    z=src.decode(a)
    if target=='unrestricted':b[dst.s['b0']]=z['beta'][0]
    if target=='gate_cost':b[dst.s['b0']]=z['beta'][0,src.cost_indices]
    return b
