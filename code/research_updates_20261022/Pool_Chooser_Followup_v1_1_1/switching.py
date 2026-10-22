"""Matched static, iid-state, and Markov-state choice probabilities.

Persistent account types coexist with a two-state process. All families use
the v3 anchored separable index, common controls, and common upper-state
costs. States are not observed construal. Transitions are per retained
opportunity; there is no receipt variable in the imported design.
"""
import bootstrap_path
import numpy as np
from scipy.special import expit, logsumexp
from numba import njit
from model import Model as StaticModel, Spec


@njit(cache=True)
def ladd(a,b):
    return np.logaddexp(a,b)


@njit(cache=True)
def forward_backward(U,y,ptr,lp,logT,loginit,aw):
    """Log-domain E step. Every derivative is for the log likelihood."""
    N,J,_=U.shape; M=len(ptr)-1
    logp=-np.logaddexp(0.,-U); logq=-np.logaddexp(0.,U)
    E=np.empty_like(U)
    for r in range(N): E[r]=logp[r] if y[r] else logq[r]
    f=np.empty_like(U); scales=np.empty((N,J)); ell=np.zeros((M,J))
    for i in range(M):
        for k in range(J):
            prev=loginit.copy()
            for r in range(ptr[i],ptr[i+1]):
                pred=prev.copy()
                if r>ptr[i]:
                    for h in range(2):pred[h]=ladd(prev[0]+logT[0,h],prev[1]+logT[1,h])
                val=pred+E[r,k]; norm=ladd(val[0],val[1])
                f[r,k]=val-norm;scales[r,k]=norm;ell[i,k]+=norm;prev=f[r,k].copy()
    lli=np.empty(M);post=np.empty((M,J))
    for i in range(M):
        val=lp+ell[i];top=np.max(val);lli[i]=top+np.log(np.exp(val-top).sum())
        post[i]=np.exp(val-lli[i])
    R=np.zeros_like(U); gt=np.zeros(2);gi=0.
    for i in range(M):
        for k in range(J):
            wt=post[i,k]*aw[i];back=np.zeros(2)
            for r in range(ptr[i+1]-1,ptr[i]-1,-1):
                g=f[r,k]+back;norm=ladd(g[0],g[1]);g=np.exp(g-norm)
                for h in range(2):R[r,k,h]=wt*g[h]*(y[r]-np.exp(logp[r,k,h]))
                if r==ptr[i]:gi+=wt*(g[1]-np.exp(loginit[1]))
                else:
                    xi=np.empty((2,2))
                    for a in range(2):
                        for h in range(2):xi[a,h]=np.exp(f[r-1,k,a]+logT[a,h]+E[r,k,h]+back[h]-scales[r,k])
                    xi/=xi.sum()
                    for a in range(2):gt[a]+=wt*(xi[a,1]-np.exp(logT[a,1])*xi[a].sum())
                    nxt=np.empty(2)
                    for a in range(2):nxt[a]=ladd(logT[a,0]+E[r,k,0]+back[0],logT[a,1]+E[r,k,1]+back[1])-scales[r,k]
                    back=nxt
    gp=(post*aw[:,None]).sum(axis=0)-aw.sum()*np.exp(lp)
    return np.dot(aw,lli),R,gt,gi,gp


@njit(cache=True)
def sequential(U,y,ptr,lp,logT,loginit):
    N,J,_=U.shape;pred=np.empty(N);scores=np.empty(N);state=np.empty(N)
    logp=-np.logaddexp(0.,-U);logq=-np.logaddexp(0.,U)
    for i in range(len(ptr)-1):
        joint=np.empty((J,2))
        for k in range(J):joint[k]=lp[k]+loginit
        for r in range(ptr[i],ptr[i+1]):
            if r>ptr[i]:
                new=joint.copy()
                for k in range(J):
                    for h in range(2):new[k,h]=ladd(joint[k,0]+logT[0,h],joint[k,1]+logT[1,h])
                joint=new
            val=joint+logp[r];top=np.max(val)
            pred[r]=np.exp(top)*np.exp(val-top).sum()
            state[r]=np.exp(joint[:,1]).sum()
            val=joint+(logp[r] if y[r] else logq[r]);top=np.max(val)
            norm=top+np.log(np.exp(val-top).sum());scores[r]=norm;joint=val-norm
    return pred,scores,state


class SwitchingModel:
    def __init__(self,spec,J,meta,bound=12.):
        self.spec=spec if isinstance(spec,Spec) else Spec(**spec)
        self.kind,self.family=self.spec.name.split('_',1)
        assert self.kind in ['hmm','iid'] and self.family in ['willingness','gate','gatecost','unrestricted']
        self.base=StaticModel(Spec('desert','desert'),J,meta,bound)
        self.J=J;self.meta=meta;self.bound=bound
        self.slices=dict(self.base.slices);self.bounds=list(self.base.bounds);self.names=list(self.base.names)
        self.support=self.base.support;self.cols=self.base.cols;self.groups=1
        def add(name,n,lo,hi):
            a=len(self.bounds);self.slices[name]=slice(a,a+n)
            self.bounds.extend([(lo,hi)]*n);self.names.extend(name+':'+str(j) for j in range(n))
        add('level_gap',1,0.,2*bound)
        if self.family=='unrestricted':add('lower_theta',J,0.,bound)
        if self.family in ['gatecost','unrestricted']:add('lower_cost',2,0.,bound)
        add('initial_logit',1,-bound,bound)
        if self.kind=='hmm':add('transition_logits',2,-bound,bound)
        self.size=len(self.bounds)

    def get(self,v,key):return v[self.slices[key]]

    def start(self,seed):
        rng=np.random.default_rng(seed);v=np.zeros(self.size);v[:self.base.size]=self.base.start(seed)
        v[self.slices['level_gap']]=rng.uniform(.2,1.5)
        if 'lower_theta' in self.slices:v[self.slices['lower_theta']]=rng.uniform(.1,1.,self.J)
        if 'lower_cost' in self.slices:v[self.slices['lower_cost']]=.03
        v[self.slices['initial_logit']]=rng.normal(0,.3)
        if self.kind=='hmm':v[self.slices['transition_logits']]=[-1.5,1.5]+rng.normal(0,.2,2)
        return v

    def decode(self,v):
        d=self.base.decode(v[:self.base.size])
        if self.family=='willingness':t=d['theta'];B=d['B']
        else:
            t=self.get(v,'lower_theta') if self.family=='unrestricted' else np.zeros(self.J)
            B=np.tile(self.get(v,'lower_cost'),(self.J,1)) if 'lower_cost' in self.slices else np.zeros((self.J,2))
        q=self.get(v,'initial_logit')[0]
        tr=self.get(v,'transition_logits') if self.kind=='hmm' else np.repeat(q,2)
        d.update(lower_theta=t,lower_B=B,level_gap=self.get(v,'level_gap')[0],
          loginit=-np.logaddexp(0.,np.array([q,-q])),
          logT=-np.logaddexp(0.,np.column_stack([tr,-tr])))
        return d

    def utilities(self,v,data):
        d=self.decode(v);A=d['A'][data['cell']]
        c=np.column_stack([data['kappa'],data['loss']])
        m=d['alpha'][None,:]+(data['Z'][:,self.cols]@d['eta'])[:,None]
        high=m+d['theta'][None,:]*A[:,None]-c@d['B'].T
        low=m-d['level_gap']+d['lower_theta'][None,:]*A[:,None]-c@d['lower_B'].T
        return np.stack([low,high],axis=2),d

    def chain(self,d,ga,gh,gl,bh,bl):
        """Map derivatives in anchored coordinates to the raw parameters."""
        g=np.zeros(self.size);base=self.base
        if self.family=='willingness':gh=gh+gl;bh=bh+bl
        gt=gh@d['A'];g[self.slices['alpha']]=ga
        g[self.slices['theta']]=gt*(1-d['index_offset'])+ga*d['index_offset']
        gA=d['theta']@gh
        if self.family=='unrestricted':
            g[self.slices['lower_theta']]=gl@d['A'];gA+=d['lower_theta']@gl
        for key,jac in d['ijac'].items():g[self.slices[key]]=gA@jac
        g[self.slices['f0']]+=np.sum((ga-gt)*d['raw_theta'])
        direction=np.array([np.cos(d['angle']),np.sin(d['angle'])])
        g[self.slices['amplitude']]=(bh@direction).sum()
        g[self.slices['angle']]=np.sum(bh*d['amplitude'][:,None]*np.array([-np.sin(d['angle']),np.cos(d['angle'])]))
        if 'lower_cost' in self.slices:g[self.slices['lower_cost']]=bl.sum(axis=0)
        return g

    def objective(self,v,data,ridge=1e-6):
        U,d=self.utilities(v,data);aw=np.asarray(data.get('aw',np.ones(len(data['ptr'])-1)),float);den=aw.sum()
        if den<=0:raise ValueError('No positively weighted accounts')
        ll,R,gt,gi,gp=forward_backward(U,data['y'],data['ptr'],d['lp'][0],d['logT'],d['loginit'],aw)
        gh=np.zeros((self.J,100));gl=np.zeros_like(gh)
        for k in range(self.J):
            gh[k]=np.bincount(data['cell'],weights=R[:,k,1],minlength=100)
            gl[k]=np.bincount(data['cell'],weights=R[:,k,0],minlength=100)
        cost=np.column_stack([data['kappa'],data['loss']])
        ga=R.sum(axis=(0,2));g=self.chain(d,ga,gh,gl,-R[:,:,1].T@cost,-R[:,:,0].T@cost)
        g[self.slices['eta']]=data['Z'][:,self.cols].T@R.sum(axis=(1,2))
        g[self.slices['prior']]=gp[1:];g[self.slices['level_gap']]=-R[:,:,0].sum()
        g[self.slices['initial_logit']]=gi if self.kind=='hmm' else gi+gt.sum()
        if self.kind=='hmm':g[self.slices['transition_logits']]=gt
        # Same energy penalty over two emission profiles in every switching fit.
        high=d['effect'][:,self.support];low=d['lower_theta'][:,None]*d['A'][None,self.support]
        pen=.5*ridge*(.5*(np.mean(high**2)+np.mean(low**2))+
                         .5*(np.mean(d['B']**2)+np.mean(d['lower_B']**2))+np.sum(d['eta']**2))
        ph=np.zeros_like(gh);pl=np.zeros_like(gl)
        ph[:,self.support]=.5*ridge*high/high.size;pl[:,self.support]=.5*ridge*low/low.size
        pg=self.chain(d,np.zeros(self.J),ph,pl,.5*ridge*d['B']/d['B'].size,
                      .5*ridge*d['lower_B']/d['lower_B'].size)
        pg[self.slices['eta']]=ridge*d['eta']
        return float(-ll/den+pen),-g/den+pg

    def predict(self,v,data):
        U,d=self.utilities(v,data)
        return sequential(U,data['y'],data['ptr'],d['lp'][0],d['logT'],d['loginit'])

    def simulate(self,v,data,rng):
        U,d=self.utilities(v,data);M=len(data['ptr'])-1
        types=rng.choice(self.J,M,p=np.exp(d['lp'][0]));p=np.empty(len(data['y']))
        for i in range(M):
            h=int(rng.random()<np.exp(d['loginit'][1]));k=types[i]
            for r in range(data['ptr'][i],data['ptr'][i+1]):
                if r>data['ptr'][i]:h=int(rng.random()<np.exp(d['logT'][h,1]))
                p[r]=expit(U[r,k,h])
        out=dict(data);out['y']=(rng.random(len(p))<p).astype(float)
        return out,types,p
