"""Sequentially updated static finite mixtures and continuous normal sensitivity.

The bivariate normal comparator uses Gaussian quadrature, with covariance between
intercept and competitive slope. A finite-mixture win does not prove bimodality.
"""
import time
import numpy as np
from scipy.special import expit,logsumexp
from scipy.optimize import minimize
from numpy.polynomial.hermite import hermgauss
from numba import njit


@njit(cache=True)
def static_ll(y,ptr,z,lp):
    N=len(ptr)-1;J=z.shape[1];ell=np.empty((N,J))
    for i in range(N):
        for j in range(J):
            val=lp[j]
            for r in range(ptr[i],ptr[i+1]):
                a=z[r,j];val+=y[r]*a-(max(a,0)+np.log1p(np.exp(-abs(a))))
            ell[i,j]=val
    return ell


@njit(cache=True)
def static_filter(y,ptr,period,z,lp):
    pred=np.empty(len(y));train=np.empty((len(ptr)-1,len(lp)))
    for i in range(len(ptr)-1):
        post=np.exp(lp);train[i]=post
        for r in range(ptr[i],ptr[i+1]):
            p=0.;norm=0.
            for j in range(len(lp)):
                eta=z[r,j]
                e=1/(1+np.exp(-eta)) if eta>=0 else np.exp(eta)/(1+np.exp(eta))
                p+=post[j]*e
                post[j]*=e if y[r] else 1-e
                norm+=post[j]
            pred[r]=min(max(p,1e-12),1-1e-12);post/=max(norm,1e-300)
            if period[r]==0:train[i]=post
    return pred,train


class Static:
    def __init__(self,P,J,family):
        self.P=P;self.J=J;self.family=family
        if family=='normal_selectivity':
            nodes,weights=hermgauss(J)
            g1,g2=np.meshgrid(nodes*np.sqrt(2),nodes*np.sqrt(2),indexing='ij')
            self.g1=g1.ravel();self.g2=g2.ravel()
            self.lp=np.log((weights[:,None]*weights[None,:]/np.pi).ravel())
            self.size=1+P+3
        else:self.size=J+(J if family=='static_selectivity' else 1)+(P-1)+(J-1)

    def decode(self,v,d):
        if self.family=='normal_selectivity':
            beta=v[1:1+self.P];s=v[-3:]
            intercept=v[0]+np.exp(s[0])*self.g1
            theta=s[1]*self.g1+np.exp(s[2])*self.g2
            z=np.asarray(d['X']@beta)[:,None]+intercept[None,:]+d['F'][:,None]*theta
            return z,self.lp,(intercept,theta,beta,s)
        width=self.J if self.family=='static_selectivity' else 1
        a=v[:self.J];theta=v[self.J:self.J+width]
        if width==1:theta=np.repeat(theta,self.J)
        b=v[self.J+width:self.J+width+self.P-1]
        logits=np.r_[0.,v[-self.J+1:]] if self.J>1 else np.array([0.])
        lp=logits-logsumexp(logits)
        z=np.asarray(d['X'][:,1:]@b)[:,None]+a[None,:]+d['F'][:,None]*theta
        return z,lp,(a,theta,b)

    def objective(self,v,d,ridge=1e-6):
        z,lp,info=self.decode(v,d);ell=static_ll(d['y'],d['ptr'],z,lp)
        ll=logsumexp(ell,axis=1);post=np.exp(ell-ll[:,None])
        aw=d.get('account_weights',np.ones(len(d['ptr'])-1));den=aw.sum()
        residual=(d['y'][:,None]-expit(z))*post[d['ids']]*aw[d['ids'],None]
        total=residual.sum(axis=1)
        if self.family=='normal_selectivity':
            _,_,beta,s=info
            grad=np.r_[total.sum(),np.asarray(d['X'].T@total).ravel()-ridge*den*beta,
                np.exp(s[0])*np.sum(residual*self.g1),
                np.sum(residual*d['F'][:,None]*self.g1),
                np.exp(s[2])*np.sum(residual*d['F'][:,None]*self.g2)]
            penalty=.5*ridge*(beta@beta)
        else:
            a,t,b=info;gs=(residual*d['F'][:,None]).sum(axis=0)
            if self.family=='static_level':gs=np.array([gs.sum()])
            grad=np.r_[residual.sum(axis=0),gs,np.asarray(d['X'][:,1:].T@total).ravel()-ridge*den*b,
                       ((post*aw[:,None]).sum(axis=0)-den*np.exp(lp))[1:]]
            penalty=.5*ridge*(b@b)
        return float(-aw@ll/den+penalty),-grad/den

    def start(self,seed):
        rng=np.random.default_rng(seed)
        if self.family=='normal_selectivity':return np.r_[-5.,np.zeros(self.P),np.log(1.5),.1,np.log(.6)]+rng.normal(0,.03,self.size)
        width=self.J if self.family=='static_selectivity' else 1
        return np.r_[np.linspace(-7,-2,self.J)+rng.normal(0,.2,self.J),np.ones(width),np.zeros(self.P-1),-np.arange(1,self.J)*.6]

    def bounds(self):
        if self.family=='normal_selectivity':return [(-16.,2.)]+[(-7.,7.)]*self.P+[(-4.,1.5),(-4.,4.),(-4.,1.5)]
        return [(-16.,3.)]*self.J+[(-7.,7.)]*(self.size-self.J)


def fit(d,family,J,seed,maxiter=400,ridge=1e-6,warm=None):
    m=Static(d['X'].shape[1],J,family);v=m.start(seed) if warm is None else np.array(warm)
    begin=time.monotonic()
    opt=minimize(m.objective,v,args=(d,ridge),jac=True,method='L-BFGS-B',bounds=m.bounds(),
                 options=dict(maxiter=maxiter,ftol=1e-9,gtol=2e-5,maxls=30))
    return dict(family=family,J=J,seed=seed,parameters=opt.x.tolist(),objective=float(opt.fun),
        converged=bool(opt.success),message=str(opt.message),iterations=int(opt.nit),
        parameter_count=len(opt.x),elapsed_seconds=time.monotonic()-begin,
        boundary_parameters=[k for k,(lo,hi) in enumerate(m.bounds()) if min(abs(opt.x[k]-lo),abs(opt.x[k]-hi))<1e-4])


def predict(result,d):
    m=Static(d['X'].shape[1],result['J'],result['family']);z,lp,_=m.decode(np.array(result['parameters']),d)
    p,q=static_filter(d['y'],d['ptr'],d['period'],z,lp)
    return p,dict(train_posterior=q)
