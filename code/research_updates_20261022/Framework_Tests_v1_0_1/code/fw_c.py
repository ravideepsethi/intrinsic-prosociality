"""Gamma-Poisson and zero-inflated fits with literal and mean-calibrated mixtures."""
from fw_common import *
from scipy.special import gammaln,digamma
from scipy.optimize import minimize,minimize_scalar,brentq
from scipy.stats import chi2

BINS=np.array([.25,.5,1,2,4,8,16,32,np.inf])
def lognb(y,E,k,scale=1.):
    mu=E*scale
    return gammaln(y+k)-gammaln(k)-gammaln(y+1)+k*(np.log(k)-np.log(k+mu))+y*(np.log(mu)-np.log(k+mu))

def likelihood(logk,gamma,y,E,calibrated=False):
    if not (0<gamma<=1):return np.inf
    k=np.exp(logk);lp=lognb(y,E,k,1/gamma if calibrated else 1.)
    if gamma==1:return -float(lp.sum())
    out=np.log(gamma)+lp;zero=y==0
    out[zero]=np.logaddexp(np.log1p(-gamma),out[zero]);return -float(out.sum())

def objective_gradient(z,y,E,calibrated=False):
    lk,g=z;k=np.exp(lk);mu=E/g if calibrated else E;lp=lognb(y,E,k,1/g if calibrated else 1.)
    dk=k*(digamma(y+k)-digamma(k)+np.log(k)-np.log(k+mu)+1-(k+y)/(k+mu))
    dg=-k*(y-mu)/(k+mu)/g if calibrated else np.zeros_like(y)
    zero=y==0;logp=np.log(g)+lp
    if g<1:logp[zero]=np.logaddexp(np.log1p(-g),logp[zero])
    post=np.exp(np.log(g)+lp[zero]-logp[zero]);dk[zero]*=post
    dg+=1/g;dg[zero]=post*dg[zero]-np.exp(np.minimum(700,-logp[zero]))
    return -float(logp.mean()),-np.array([dk.mean(),dg.mean()])

def fit(y,E,mixture=False,calibrated=False,profile=True):
    y=np.asarray(y,float);E=np.asarray(E,float);require(len(y)>5 and np.all(E>0),'Insufficient positive-exposure accounts')
    null=minimize_scalar(lambda z:likelihood(z,1,y,E),bounds=(-10,12),method='bounded',options={'xatol':1e-7})
    require(null.success,'Gamma-Poisson fit failed')
    for endpoint in (-10.,12.):
        value=likelihood(endpoint,1,y,E)
        if value<null.fun:null.x=endpoint;null.fun=value
    if not mixture:return dict(k=float(np.exp(null.x)),gamma=1.,nll=float(null.fun),converged=True,k_at_search_boundary=bool(null.x>11.95 or null.x< -9.95))
    choices=[]
    for g in (.15,.6,.95,1.):
        r=minimize(lambda z:objective_gradient(z,y,E,calibrated),[null.x,g],jac=True,method='L-BFGS-B',bounds=[(-10,12),(1e-6,1.)],
                   options={'ftol':1e-12,'gtol':1e-9,'maxiter':600})
        r.fun*=len(y)
        if r.success and np.isfinite(r.fun):choices.append(r)
    require(choices,'Zero-inflated likelihood failed to converge')
    best=min(choices,key=lambda x:x.fun)
    if best.fun>null.fun or best.x[1]>=1-1e-10:lk,g,loss=null.x,1.,null.fun
    else:lk,g,loss=best.x[0],best.x[1],best.fun
    lr=max(0.,2*(null.fun-loss));p=.5*chi2.sf(lr,1) if lr>0 else 1.
    out=dict(k=float(np.exp(lk)),gamma=float(g),nll=float(loss),converged=True,LR=float(lr),boundary_mixture_p=float(p),
             mean_calibrated=calibrated,k_at_search_boundary=bool(lk>11.95 or lk< -9.95))
    if profile:
        def dev(g0):
            opt=minimize_scalar(lambda z:likelihood(z,g0,y,E,calibrated),bounds=(-10,12),method='bounded')
            require(opt.success,'Gamma profile optimization failed');return 2*(opt.fun-loss)-chi2.ppf(.95,1)
        lo=1e-6 if dev(1e-6)<=0 else brentq(dev,1e-6,g,xtol=1e-6)
        hi=1. if dev(1.)<=0 else brentq(dev,g,1.,xtol=1e-6)
        out.update(gamma_ci_low=float(lo),gamma_ci_high=float(hi),interval='95% profile likelihood, chi-square(1) cutoff')
    return out

def zero_probability(E,f):
    k=f['k'];g=f['gamma'];scale=1/g if f.get('mean_calibrated') else 1.
    return 1-g+g*np.exp(-k*np.log1p(E*scale/k))

def posterior_mean_zero(E,f):
    k=f['k'];g=f['gamma'];rate=k*g if f.get('mean_calibrated') else k
    if g==1:return k/(rate+E)
    logactive=np.log(g)-k*np.log1p(E/rate)
    prob=np.exp(logactive-np.logaddexp(np.log1p(-g),logactive))
    return prob*k/(rate+E)

def exposure(paths,work,key,memory):
    if completed(work,key):return work/'counts.parquet'
    work.mkdir(parents=True,exist_ok=True);c=conn(work/'spill',max(1,memory-2),2)
    try:
        # Exact 500-cell encoding from the current IV producer, including endpoints.
        c.execute('''CREATE VIEW p AS SELECT *,
          (((CASE WHEN board<=-300 THEN 0 WHEN board< -100 THEN 1 WHEN board<=100 THEN 2 WHEN board<300 THEN 3 ELSE 4 END)*4+
             CASE WHEN ply<=10 THEN 0 WHEN ply<=30 THEN 1 WHEN ply<=60 THEN 2 ELSE 3 END)*5+speed_code)*5+
             CASE WHEN gap<=-200 THEN 0 WHEN gap<=-100 THEN 1 WHEN gap<=100 THEN 2 WHEN gap<=200 THEN 3 ELSE 4 END AS cell
          FROM '''+parq(paths))
        c.execute('CREATE TABLE cells AS SELECT cell,avg(y) p_all,avg(y) FILTER(WHERE year=1) p_P1,count(*) n FROM p GROUP BY cell')
        c.execute('''CREATE TABLE by_account AS SELECT chooser,year,count(*) n,sum(y) y,sum(p_all) E_full,
             sum(p_P1) E_frozen_P1,count(*) FILTER(WHERE p_P1 IS NULL) unsupported_P1
             FROM p JOIN cells USING(cell) WHERE board>=-100 GROUP BY chooser,year''')
        c.execute(f'COPY by_account TO {qs(work/"counts.parquet")} (FORMAT PARQUET,COMPRESSION ZSTD)')
        table(work/'report','cell_reference_rates',c.execute('SELECT * FROM cells ORDER BY cell').fetchdf())
    finally:c.close()
    certify(work,key,paths);return work/'counts.parquet'

def run(a,run,paths,key):
    work=run/'C';report=work/'report';report.mkdir(parents=True,exist_ok=True);ck=digest([key,'C'])
    if completed(work/'final',ck):return load(work/'final/status.json')
    p=exposure(paths,work/'exposure',digest([ck,'exposure']),a.memory_gb);d=frame(p)
    allv=d.groupby('chooser',sort=True).agg(n=('n','sum'),y=('y','sum'),E=('E_full','sum')).reset_index()
    p1=d.loc[d.year==1].rename(columns={'E_frozen_P1':'E'})
    results=[];curves=[];fits={}
    for label,x in [('full',allv),('P1',p1)]:
        x=x.loc[x.E>=.25];y=x.y.to_numpy(float);E=x.E.to_numpy(float)
        for model,mix,cal in [('gamma_poisson',False,False),('zero_inflated_literal',True,False),('zero_inflated_mean_calibrated',True,True)]:
            checkpoint=work/'fits'/(label+'_'+model);fk=digest([ck,label,model])
            if completed(checkpoint,fk):f=load(checkpoint/'fit.json')
            else:
                with heartbeat('C '+label+' '+model):f=fit(y,E,mix,cal)
                save(checkpoint/'fit.json',f);certify(checkpoint,fk,[p])
            fits[label,model]=f;results.append(dict(period=label,model=model,accounts=len(y),**f))
            for lo,hi in zip(BINS[:-1],BINS[1:]):
                use=(E>=lo)&(E<hi)
                curves.append(dict(period=label,model=model,bin_low=lo,bin_high=hi,accounts=int(use.sum()),
                  observed_zero_share=float(np.mean(y[use]==0)) if use.any() else None,
                  predicted_zero_share=float(zero_probability(E[use],f).mean()) if use.any() else None))
    joined=p1[['chooser','n','y','E']].merge(d.loc[d.year==2,['chooser','n','y','E_frozen_P1','unsupported_P1']],on='chooser',suffixes=('_P1','_P2'))
    cohort=joined.loc[(joined.y_P1==0)&(joined.E>=8)&(joined.unsupported_P1==0)]
    forward=[]
    for model in ('gamma_poisson','zero_inflated_literal','zero_inflated_mean_calibrated'):
        f=fits['P1',model];pred=posterior_mean_zero(cohort.E.to_numpy(float),f)*cohort.E_frozen_P1.to_numpy(float)
        forward.append(dict(model=model,accounts=len(cohort),P2_opportunities=int(cohort.n_P2.sum()),
          observed_grants=int(cohort.y_P2.sum()),predicted_grants=float(pred.sum()),
          observed_rate_pp=float(100*cohort.y_P2.sum()/cohort.n_P2.sum()) if len(cohort) else None,
          predicted_rate_pp=float(100*pred.sum()/cohort.n_P2.sum()) if len(cohort) else None,
          frozen_population_rates='P1 only; unsupported P2 cells excluded from forward cohort'))
    table(report,'tabC1_zero_inflation',results);table(report,'tabC1_zero_predictions',curves);table(report,'tabC2_forward_zero_granters',forward)
    import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7,4));full=[r for r in curves if r['period']=='full']
    for model in ('gamma_poisson','zero_inflated_literal','zero_inflated_mean_calibrated'):
        rr=[r for r in full if r['model']==model];ax.plot(range(8),[r['predicted_zero_share'] for r in rr],label=model.replace('_',' '))
    rr=[r for r in full if r['model']=='gamma_poisson'];ax.plot(range(8),[r['observed_zero_share'] for r in rr],'ko-',label='Observed')
    ax.set_xticks(range(8),['.25–.5','.5–1','1–2','2–4','4–8','8–16','16–32','32+']);ax.set(xlabel='Expected competitive grants',ylabel='Share with zero grants',ylim=(0,1));ax.legend(fontsize=8);fig.tight_layout();fig.savefig(report/'figC1_zero_share.pdf');plt.close(fig)
    status=dict(status='ESTIMATED',caution='Mixture fits compare distributional models; a fitted zero mass does not uniquely establish a psychological gate.',
      implementation_amendment='The literal mixture fixes active mean at one, so its unconditional mean is gamma*E. A separate mean-calibrated mixture fixes total mean at E. Both are reported; no automatic mechanism verdict.')
    save(work/'final/status.json',status);certify(work/'final',ck,[p],outputs=list(report.glob('*')));return status
