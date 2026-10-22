"""Exact conditional likelihood, not a dummy-variable logit approximation."""
from fw_common import *
from fw_b import sample
from fw_design import b_design
from scipy.optimize import minimize

def conditional_group(X,y,beta,hessian=False):
    X=np.asarray(X,float);y=np.asarray(y,float);m=int(y.sum());n=len(y);p=X.shape[1]
    require(0<m<n,'Conditional likelihood requires within-account outcome variation')
    if m>n//2:X=-X;y=1-y;m=n-m
    if m==1:
        from scipy.special import logsumexp
        eta=X@beta;z=logsumexp(eta);w=np.exp(eta-z);mu=w@X;W=X-mu
        return float(z-eta@y),mu-X.T@y,(W*w[:,None]).T@W if hessian else None
    eta=X@beta;A=np.full(m+1,-np.inf);A[0]=0.;G=np.zeros((m+1,p));H=np.zeros((m+1,p,p)) if hessian else None
    for i,(e,x) in enumerate(zip(eta,X)):
      for j in range(min(i+1,m),0,-1):
        a=A[j];b=A[j-1]+e;z=np.logaddexp(a,b)
        wa=0. if not np.isfinite(a) else np.exp(a-z);wb=0. if not np.isfinite(b) else np.exp(b-z)
        ga=G[j].copy();gb=G[j-1]+x;g=wa*ga+wb*gb
        if hessian:H[j]=wa*(H[j]+np.outer(ga-g,ga-g))+wb*(H[j-1]+np.outer(gb-g,gb-g))
        G[j]=g;A[j]=z
    return float(A[m]-eta@y),G[m]-X.T@y,H[m] if hessian else None

def conditional_fit(groups,names,checkpoint=None,key=None):
    k=len(names);gram=sum(X.T@X for X,y in groups);base=solve(gram,np.zeros(k));
    scale=base['scale'];v,Q=np.linalg.eigh(gram/scale[:,None]/scale[None,:]);good=v>max(1e-10,v.max()*1e-10)
    T=(Q[:,good]/np.sqrt(v[good]))/scale[:,None];reduced=[(X@T,y) for X,y in groups]
    def objective(b):
        loss=0.;g=np.zeros(len(b))
        for X,y in reduced:
            ll,gg,_=conditional_group(X,y,b);loss+=ll;g+=gg
        return loss,g
    initial=np.zeros(T.shape[1]);iterations=[0]
    if checkpoint and Path(checkpoint).is_file():
        warm=load(checkpoint);require(warm['key']==key and warm['names']==names,'Conditional logit warm-start identity differs')
        initial=np.array(warm['beta']);require(initial.shape==(T.shape[1],) and np.isfinite(initial).all(),'Invalid conditional logit warm start')
    def callback(b):
        iterations[0]+=1
        if checkpoint and iterations[0]%5==0:
            save(checkpoint,dict(key=key,names=names,beta=b));log('B conditional logit: saved optimizer iterate '+str(iterations[0]))
    with heartbeat('B exact conditional logit optimization'):
        fit=minimize(objective,initial,jac=True,callback=callback,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-14,'gtol':1e-8,'maxls':60})
    # A small relative change in likelihood does not establish stationarity.
    # Exact Hessian/Newton refinement keeps the original likelihood and sample.
    current=fit.x.copy();stationary=False;prediction_step=np.inf
    with heartbeat('B conditional logit exact Newton refinement'):
      for polish in range(13):
        H=np.zeros((len(current),len(current)));M=H.copy();gradient=np.zeros(len(current));loss=0.
        for X,y in reduced:
            ll,g,h=conditional_group(X,y,current,True);loss+=ll;gradient+=g;H+=h;M+=np.outer(g,g)
        require(np.linalg.matrix_rank(H)==len(current),'Conditional logit information is singular; possible separation')
        step=np.linalg.solve(H,gradient)
        prediction_step=max(float(np.max(np.abs(X@step),initial=0)) for X,y in reduced)
        if checkpoint:save(checkpoint,dict(key=key,names=names,beta=current))
        log(f'B conditional logit Newton {polish}: largest log-odds correction {prediction_step:.6g}')
        if prediction_step<1e-5:stationary=True;break
        if polish==12:break
        rate=1.;descent=float(gradient@step)
        while rate>=2**-20:
            candidate=current-rate*step;next_loss,_=objective(candidate)
            if np.isfinite(next_loss) and next_loss<=loss-1e-4*rate*descent+1e-10:
                current=candidate;break
            rate*=.5
        else:break
    require(stationary,'Conditional logit not stationary after exact refinement; warm-start retained')
    inv=np.linalg.inv(H);G=len(groups);V=T@inv@M@inv@T.T*G/(G-1);beta=T@current
    return beta,V,base,dict(conditional_accounts=G,conditional_rows=sum(len(y) for _,y in groups),converged=True,iterations=int(fit.nit),
      score_max=float(np.max(np.abs(gradient))),newton_steps=polish,max_log_odds_newton_correction=prediction_step,
      rank=int(T.shape[1]),covariance='chooser score sandwich, G/(G-1)',units='log odds per draw-payoff rating point')

def run_logit(a,run,parts,key):
    work=run/'B/logit';lk=digest([key,'conditional_logit']);report=run/'B/report'
    if completed(work/'final',lk):return load(work/'final/status.json')
    groups=[];selected_accounts=0;constant=0;names=None
    for path in parts:
        d,_=sample(frame(path),dict(name='primary'))
        d=d.loc[fold_ids(d.chooser.to_numpy())==0].reset_index(drop=True)
        X,names,_=b_design(d,dict(name='primary'));X=demean(X,d.chooser.to_numpy()) if len(d) else X
        y=d.y.to_numpy(float);s,n=starts_counts(d.chooser.to_numpy());selected_accounts+=len(s)
        for start,length in zip(s,n):
            yy=y[start:start+length]
            if 0<yy.sum()<length:groups.append((X[start:start+length].copy(),yy.copy()))
            else:constant+=1
    require(len(groups)>2,'Insufficient varying accounts for conditional logit')
    beta,V,base,info=conditional_fit(groups,names,work/'optimizer_PRIVATE.json',lk);rows=[]
    for g in range(4):
        q=np.array([float(n==f'g{g}:slope') for n in names]);ok=estimable(base,q)
        rows.append(dict(group=g,term='slope',**(infer(q@beta,q@V@q) if ok else dict(status='NOT_ESTIMABLE'))))
    q=np.array([float(n=='g1:slope')-float(n=='g0:slope') for n in names])
    rows.append(dict(group='BOTH_minus_CO',term='slope',**(infer(q@beta,q@V@q) if estimable(base,q) else dict(status='NOT_ESTIMABLE'))))
    table(report,'tabB3_conditional_logit',rows);info.update(selected_accounts=selected_accounts,constant_outcome_accounts_dropped=constant,sampling='Fixed account hash modulo 5 equals zero; 20% before outcome-variation restriction')
    save(work/'final/status.json',info);certify(work/'final',lk,list(parts),outputs=list(report.glob('tabB3_conditional_logit.*')));return info
