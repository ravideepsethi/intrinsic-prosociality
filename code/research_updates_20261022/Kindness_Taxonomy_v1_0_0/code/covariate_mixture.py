"""B2: same account mixture with state/cost type slopes and common covariates.

Analytic gradient of the exact marginal account likelihood; no dense N x P
design or stochastic approximation. B1 uses EM; B2 uses bounded L-BFGS-B.
"""
from common import *
from scipy.special import expit,logsumexp
from scipy.optimize import minimize
from mixture import alignment

def pack_data(d,ids,scale=None):
    a=np.searchsorted(ids,d['chooser'])
    if not np.array_equal(ids[a],d['chooser']):raise RuntimeError('B2 identity join failure')
    scale=scale or dict(mean=float(np.mean(d['cost'])),sd=float(np.std(d['cost'])))
    if scale['sd']<=0:raise Unavailable('No cost variation for B2')
    cost=(d['cost']-scale['mean'])/scale['sd'];cols=[];names=[]
    for name in ('stage','speed','month'):
        levels=np.unique(d[name]);codes=np.searchsorted(levels,d[name])
        # Reference categories use -1; the other categories index the common vector.
        offset=len(names);cols.append(np.where(codes>0,codes-1+offset,-1).astype(np.int16))
        names.extend(name+'='+str(x) for x in levels[1:])
    return dict(account=a.astype(np.int32),state=d['state'].astype(np.int8),cost=cost,y=d['y'].astype(np.int8),
      cats=cols,common_names=names,n_accounts=len(ids),scale=scale)

def unpack(theta,K,J):
    off=K-1;pi=np.exp(np.r_[theta[:off],0]-logsumexp(np.r_[theta[:off],0]))
    alpha=theta[off:off+5*K].reshape(K,5);beta=theta[off+5*K:off+6*K];gamma=theta[off+6*K:]
    return pi,alpha,beta,gamma

def common_term(d,gamma,sl):
    out=np.zeros(len(d['y'][sl]))
    for col in d['cats']:
        cc=col[sl];valid=cc>=0;out[valid]+=gamma[cc[valid]]
    return out

def objective(theta,d,K,weight=None):
    A=d['n_accounts'];weight=np.ones(A) if weight is None else weight;J=len(d['common_names'])
    pi,alpha,beta,gamma=unpack(theta,K,J);ll=np.zeros((A,K));batch=250000
    for lo in range(0,len(d['y']),batch):
        sl=slice(lo,lo+batch);a=d['account'][sl];s=d['state'][sl];cost=d['cost'][sl];y=d['y'][sl];base=common_term(d,gamma,sl)
        for k in range(K):
            eta=alpha[k,s]+beta[k]*cost+base
            ll[:,k]+=np.bincount(a,weights=y*eta-np.logaddexp(0,eta),minlength=A)
    joint=ll+np.log(pi);z=logsumexp(joint,axis=1);tau=np.exp(joint-z[:,None]);loss=-float(weight@z)
    ga=np.zeros((K,5));gb=np.zeros(K);gc=np.zeros(J)
    for lo in range(0,len(d['y']),batch):
        sl=slice(lo,lo+batch);a=d['account'][sl];s=d['state'][sl];cost=d['cost'][sl];y=d['y'][sl];base=common_term(d,gamma,sl);total=np.zeros(len(a))
        for k in range(K):
            eta=alpha[k,s]+beta[k]*cost+base;r=(expit(eta)-y)*tau[a,k]*weight[a]
            ga[k]+=np.bincount(s,weights=r,minlength=5);gb[k]+=r@cost;total+=r
        for col in d['cats']:
            cc=col[sl];good=cc>=0;gc+=np.bincount(cc[good],weights=total[good],minlength=J)
    mix=(weight.sum()*pi-(weight[:,None]*tau).sum(axis=0))[:-1]
    return loss/weight.sum(),np.r_[mix,ga.ravel(),gb,gc]/weight.sum()

def surface(theta,d,K):
    pi,a,b,gamma=unpack(theta,K,len(d['common_names']))
    # A common, outcome-free sample of Y1 nuisance covariates, at mean cost.
    rng=np.random.default_rng(816321);ix=rng.choice(len(d['y']),min(100000,len(d['y'])),replace=False)
    base=common_term(d,gamma,ix);p=np.array([[expit(a[k,s]+base).mean() for s in range(5)] for k in range(K)])
    return pi,p,b

def fit_model(d,K,initial,cfg,seed,weight=None):
    bound=cfg['logit_coefficient_bound']
    r=minimize(lambda x:objective(x,d,K,weight),initial,jac=True,method='L-BFGS-B',bounds=[(-bound,bound)]*len(initial),
      options=dict(maxiter=cfg['max_covariate_optimizer_iterations'],ftol=1e-11,gtol=2e-6,maxls=30))
    pi,p,b=surface(r.x,d,K);order=np.lexsort((p[:,0],p[:,-1],p.mean(axis=1)))
    return dict(status='ESTIMATED' if r.success else 'NOT_CONVERGED',converged=bool(r.success),message=str(r.message),
      seed=seed,K=K,theta=r.x,pi=pi,p=p,cost_slopes=b,canonical_order=order,
      log_likelihood=-float(r.fun)*(len(pi)*0+(d['n_accounts'] if weight is None else weight.sum())),
      gradient_max=float(np.abs(r.jac).max()),bound_hits=int((abs(r.x)>bound-1e-5).sum()),minimum_share=float(pi.min()),
      iterations=int(r.nit),function_evaluations=int(r.nfev))

def starts(d,initial_fit,cfg,folder,key,count=None,weight=None,warm=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);K=initial_fit['K'];J=len(d['common_names']);fits=[]
    pi=np.asarray(initial_fit['pi']);p=np.asarray(initial_fit['p']);p=np.clip(p,1e-9,1-1e-9)
    initial=np.r_[np.log(pi[:-1]/pi[-1]),np.log(p/(1-p)).ravel(),np.zeros(K+J)]
    for j in range(count or cfg['random_starts']):
        dest=folder/f'start_{j:02}.json'
        if dest.exists():r=read(dest)
        else:
            seed=cfg['seed']+j;rg=np.random.default_rng(seed)
            x=np.asarray(warm['theta']) if warm is not None else initial
            x=x.copy()
            if j:x+=rg.normal(0,.15 if warm is not None else .7,len(x))
            r=fit_model(d,K,x,cfg,seed,weight);write(dest,r)
        fits.append(r)
        if (j+1)%5==0:log(f'B2 K={K}: starts {j+1}/{count or cfg["random_starts"]}')
    good=[r for r in fits if r['status']=='ESTIMATED' and r['minimum_share']>=cfg['component_min_share']]
    if not good:return dict(status='NO_SUPPORTED_CONVERGED_START',K=K,attempts=len(fits))
    r=max(good,key=lambda r:r['log_likelihood']).copy();r.update(starts=len(fits),converged_starts=len(good));return r

def load(c,work,M):
    c.execute(f'''CREATE OR REPLACE TEMP TABLE b2_roster AS SELECT chooser FROM panel WHERE year=1 GROUP BY chooser HAVING count(*)>={M}''')
    ids=c.execute('SELECT chooser FROM b2_roster ORDER BY chooser').fetchnumpy()['chooser']
    d=arrays(c.execute('''SELECT p.chooser,p.state,p.cost,p.y,p.stage,
       CASE p.speed WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2 WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 ELSE 5 END::TINYINT speed,
       cast(substr(p.month,6,2) AS TINYINT) AS "month"
       FROM panel p SEMI JOIN b2_roster b USING(chooser) WHERE year=1 ORDER BY chooser,game_id''').to_arrow_table())
    return ids,pack_data(d,ids)

def run(c,work,folder,key,cfg,b1folder):
    summaries=[];profiles=[];boots=[]
    for M in cfg['minimum_opportunities']:
        p=Path(b1folder)/f'M{M}_year1/selected.json'
        if not p.exists():summaries.append(dict(M=M,status='NO_B1_SELECTED_FIT'));continue
        ids,d=load(c,work,M);initial=read(p);dest=folder/f'M{M}';dest.mkdir(parents=True,exist_ok=True)
        fp=dest/'selected.json';r=read(fp) if fp.exists() else starts(d,initial,cfg,dest,key)
        if not fp.exists():write(fp,r)
        summaries.append(dict(M=M,scale=d['scale'],common_names=d['common_names'],**{k:v for k,v in r.items() if k not in ('theta','pi','p','cost_slopes')}))
        if r['status']!='ESTIMATED':continue
        order=alignment(initial['p'],r['p'])
        for k,j in enumerate(order):
            for s in range(5):profiles.append(dict(M=M,type=k,state=s,p=r['p'][j][s],share=r['pi'][j],cost_logodds_slope_per_Y1_SD=r['cost_slopes'][j],cost_sd=d['scale']['sd']))
        if M!=cfg['minimum_opportunities'][0]:continue
        for b in range(cfg['bootstrap_reps']):
            bp=dest/'bootstrap'/f'rep_{b:03}'/'selected.json'
            if bp.exists():br=read(bp)
            else:
                rng=np.random.default_rng(cfg['seed']+b+300000);w=np.bincount(rng.integers(0,len(ids),len(ids)),minlength=len(ids))
                bc=dict(cfg,seed=cfg['seed']+b*1000);br=starts(d,initial,bc,bp.parent,key,cfg['bootstrap_starts'],weight=w,warm=r);write(bp,br)
            if br['status']=='ESTIMATED':
                align=alignment(np.asarray(r['p'])[order],br['p'])
                for k,j in enumerate(align):
                    boots.append(dict(rep=b,type=k,share=br['pi'][j],cost_slope=br['cost_slopes'][j],**{f'p{s}':br['p'][j][s] for s in range(5)}))
            if (b+1)%max(1,cfg['bootstrap_reps']//4)==0:log(f'B2 bootstrap {b+1}/{cfg["bootstrap_reps"]}; continuing')
        del d
    write(folder/'B2_fit_summary.json',summaries);csvwrite(folder/'B2_profiles.csv',profiles);csvwrite(folder/'B2_bootstrap_draws.csv',boots)
    intervals=[]
    for k in sorted({b['type'] for b in boots}):
        for name in ['share','cost_slope']+[f'p{s}' for s in range(5)]:
            a=np.array([b[name] for b in boots if b['type']==k]);intervals.append(dict(type=k,parameter=name,valid_reps=len(a),requested_reps=cfg['bootstrap_reps'],
              bootstrap_se=float(a.std(ddof=1)) if len(a)>1 else None,low=float(np.quantile(a,.025)),high=float(np.quantile(a,.975)),
              status='AVAILABLE' if len(a)>=.9*cfg['bootstrap_reps'] else 'TOO_MANY_FAILED_REFITS',conditional_on_selected_K=True))
    csvwrite(folder/'B2_bootstrap_intervals.csv',intervals)
    write(folder/'method.json',dict(estimator='Exact marginal account likelihood; analytic-gradient L-BFGS-B with 20 dispersed starts',
      likelihood='Type-specific state intercepts and standardized cost slope; common stage, speed and year1 month coefficients',
      profiles='Common year1 nuisance distribution at mean year1 cost; fixed deterministic 100k-row outcome-free standardization sample',
      bootstrap='200 account resamples for main M20, three warm/perturbed starts per refit, selected K fixed',
      caveat='Cost is not randomized. Numerical bounds and component collapse are reported. Year2 outcomes never enter B2 estimation.'))
