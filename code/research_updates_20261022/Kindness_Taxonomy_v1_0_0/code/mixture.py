"""Account-level binomial mixture, unconstrained profiles, multistart EM."""
from common import *
from scipy.special import logsumexp,expit
from scipy.optimize import linear_sum_assignment

def posterior(n,g,pi,p):
    l=g@np.log(p).T+(n-g)@np.log1p(-p).T+np.log(pi)
    z=logsumexp(l,axis=1);return np.exp(l-z[:,None]),z

def fit(n,g,k,seed,cfg,weight=None,initial=None):
    n=np.asarray(n,float);g=np.asarray(g,float);w=np.ones(len(n)) if weight is None else np.asarray(weight,float)
    rng=np.random.default_rng(seed);eps=cfg['probability_floor'];N=w.sum()
    pooled=(w@g+.5)/(w@n+1)
    if initial is None:
        p=expit(np.log(pooled/(1-pooled))[None,:]+rng.normal(0,2,(k,5)))
        if k>1:p[0]=np.minimum(pooled*.01,eps*100)
        pi=rng.dirichlet(np.ones(k))
    else:pi=np.asarray(initial['pi'],float).copy();p=np.asarray(initial['p'],float).copy()
    prev=-np.inf;converged=False
    for iteration in range(1,cfg['max_em_iterations']+1):
        tau,z=posterior(n,g,pi,p);ll=float(w@z)
        if np.isfinite(prev) and ll<prev-1e-7*max(1,abs(prev)):raise RuntimeError('EM likelihood decreased')
        if np.isfinite(prev) and ll-prev<=cfg['em_relative_tolerance']*max(1,abs(prev)):
            converged=True;break
        a=tau*w[:,None];pi=np.maximum(a.sum(axis=0)/N,eps);pi/=pi.sum()
        denom=a.T@n
        if (denom<=0).any():return dict(status='UNIDENTIFIED_STATE_COMPONENT',seed=seed,K=k)
        p=np.clip((a.T@g)/denom,eps,1-eps);prev=ll
    tau,z=posterior(n,g,pi,p);ll=float(w@z)
    order=np.lexsort((p[:,0],p[:,-1],p.mean(axis=1)));pi=pi[order];p=p[order];tau=tau[:,order]
    entropy=-float(np.sum(w[:,None]*tau*np.log(np.maximum(tau,1e-300))))
    pars=6*k-1;bic=-2*ll+pars*np.log(N)
    return dict(status='ESTIMATED' if converged else 'MAX_ITERATIONS',K=k,seed=seed,iterations=iteration,converged=converged,
      pi=pi,p=p,log_likelihood=ll,BIC=bic,ICL=bic+2*entropy,parameters=pars,accounts=int(N),
      normalized_entropy=entropy/(N*np.log(k)) if k>1 else 0.,
      confident_share=float(w@(tau.max(axis=1)>.9)/N),minimum_share=float(pi.min()),
      boundary_probability_count=int(((p<=eps*1.01)|(p>=1-eps*1.01)).sum()))

def multistart(n,g,k,cfg,folder,key,weight=None,starts=None,initial=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);fits=[]
    count=starts or cfg['random_starts']
    for j in range(count):
        path=folder/f'start_{j:02}.json'
        if path.exists():
            r=read(path)
            if r.pop('checkpoint_key',None)!=key:raise RuntimeError('Mixture start key mismatch')
        else:
            r=fit(n,g,k,cfg['seed']+k*10000+j,cfg,weight,initial if j==0 else None)
            write(path,dict(r,checkpoint_key=key))
        fits.append(r)
        if count>=20 and (j+1)%5==0:log(f'Mixture K={k}: starts {j+1}/{count}')
    usable=[r for r in fits if r['status']=='ESTIMATED']
    if not usable:return dict(status='NO_CONVERGED_START',K=k,starts=count,converged_starts=0)
    best=max(usable,key=lambda r:r['log_likelihood']).copy()
    best.update(starts=count,converged_starts=len(usable),near_best_starts=sum(abs(r['log_likelihood']-best['log_likelihood'])<=1e-5*max(1,abs(best['log_likelihood'])) for r in usable))
    return best

def grouped(c,work,minimum,year=1):
    source=Path(work)/'00_aggregates/account_state_year.parquet'
    d=arrays(c.execute(f'''SELECT a.* FROM {scan(source)} a SEMI JOIN
      (SELECT chooser FROM {scan(source)} WHERE year={year} GROUP BY chooser HAVING sum(n)>={minimum}) b USING(chooser)
      WHERE year={year} ORDER BY chooser,state''').to_arrow_table())
    ids,ix=np.unique(d['chooser'],return_inverse=True);n=np.zeros((len(ids),5));g=n.copy()
    n[ix,d['state']]=d['n'];g[ix,d['state']]=d['g'];return ids,n,g

def alignment(reference,candidate):
    a=np.asarray(reference);b=np.asarray(candidate);row,col=linear_sum_assignment(((a[:,None,:]-b[None,:,:])**2).sum(axis=2))
    return col[np.argsort(row)]

def bootstrap(n,g,best,cfg,folder,key):
    results=[];K=best['K']
    for b in range(cfg['bootstrap_reps']):
        dest=Path(folder)/f'rep_{b:03}';dest.mkdir(parents=True,exist_ok=True);p=dest/'fit.json'
        if p.exists():r=read(p)
        else:
            rng=np.random.default_rng(cfg['seed']+100000+b);w=np.bincount(rng.integers(0,len(n),len(n)),minlength=len(n))
            subcfg=dict(cfg,seed=cfg['seed']+b*1000)
            r=multistart(n,g,K,subcfg,dest,key,weight=w,starts=cfg['bootstrap_starts'],initial=best);write(p,r)
        if r['status']=='ESTIMATED' and r['minimum_share']>=cfg['component_min_share']:
            order=alignment(best['p'],r['p']);results.append(dict(rep=b,pi=np.asarray(r['pi'])[order],p=np.asarray(r['p'])[order]))
        if (b+1)%max(1,cfg['bootstrap_reps']//4)==0:log(f'B1 bootstrap {b+1}/{cfg["bootstrap_reps"]}; continuing')
    return results

def run_b1(c,work,folder,key,cfg):
    fitpath=[];selection=[];profiles=[]
    for M in cfg['minimum_opportunities']:
        for year in (1,2):
            ids,n,g=grouped(c,work,M,year)
            if len(ids)<20 or np.any(n.sum(axis=0)==0):
                selection.append(dict(M=M,year=year,status='INSUFFICIENT_SUPPORT'));continue
            fits=[]
            for K in cfg['K']:
                dest=folder/f'M{M}_year{year}'/f'K{K}';p=dest/'best.json'
                best=read(p) if p.exists() else multistart(n,g,K,cfg,dest,key)
                if not p.exists():write(p,best)
                fits.append(best);fitpath.append(dict(M=M,year=year,**{k:v for k,v in best.items() if k not in ('pi','p')}))
            viable=[r for r in fits if r['status']=='ESTIMATED' and r['minimum_share']>=cfg['component_min_share']]
            if not viable:selection.append(dict(M=M,year=year,status='NO_SUPPORTED_FIT'));continue
            best=min(viable,key=lambda r:(r['BIC'],r['K']));selection.append(dict(M=M,year=year,K=best['K'],status='ESTIMATED',accounts=len(ids)))
            dest=folder/f'M{M}_year{year}';write(dest/'selected.json',best)
            post,z=posterior(n,g,np.asarray(best['pi']),np.asarray(best['p']));t=dict(chooser=ids,modal_type=post.argmax(axis=1),max_posterior=post.max(axis=1),opportunities=n.sum(axis=1))
            t.update({f'posterior_{k}':post[:,k] for k in range(best['K'])});pq.write_table(pa.table(t),dest/'posteriors_PRIVATE.parquet',compression='zstd')
            for k in range(best['K']):
                for s in range(5):profiles.append(dict(M=M,year=year,type=k,share=best['pi'][k],state=s,p=best['p'][k][s],state_opportunities=n[:,s].sum()))
    csvwrite(folder/'B1_fit_path.csv',fitpath);csvwrite(folder/'B1_selected_models.csv',selection);csvwrite(folder/'B1_profiles.csv',profiles)
    # Main M=20/Y1 selected-K bootstrap; selection uncertainty is not silently included.
    M=cfg['minimum_opportunities'][0];p=folder/f'M{M}_year1/selected.json';se=[]
    if p.exists():
        best=read(p);ids,n,g=grouped(c,work,M,1);draws=bootstrap(n,g,best,cfg,folder/'bootstrap_main',key)
        for k in range(best['K']):
            for s in range(-1,5):
                v=np.array([a['pi'][k] if s<0 else a['p'][k,s] for a in draws]);est=best['pi'][k] if s<0 else best['p'][k][s]
                se.append(dict(M=M,type=k,state=s,parameter='share' if s<0 else 'probability',estimate=est,bootstrap_se=float(v.std(ddof=1)) if len(v)>1 else None,
                  ci_low=float(np.quantile(v,.025)) if len(v)>1 else None,ci_high=float(np.quantile(v,.975)) if len(v)>1 else None,
                  valid_reps=len(v),requested_reps=cfg['bootstrap_reps'],inference_status='AVAILABLE' if len(v)>=.9*cfg['bootstrap_reps'] else 'TOO_MANY_FAILED_REFITS',conditional_on_selected_K=True))
    csvwrite(folder/'B1_bootstrap.csv',se)
    write(folder/'method.json',dict(likelihood='Binomial account likelihood conditional on state opportunities; binomial combinatorial constants omitted uniformly across K',
      BIC_sample_size='Accounts, not choices',selection='BIC minimum among converged nonempty components; all K fit diagnostics retained',
      labels='Neutral numeric labels. Finite mixtures approximate heterogeneity; BIC does not prove psychological categories.',
      bootstrap='200 account cluster resamples, selected K fixed, three starts including fitted initialization; type alignment by profile distance; M20 year1 main',
      zero_type='Near-zero fitted probabilities are not proof of structural never-granters',prior_related_results_seen=True))
    return dict(selection=selection)

def validate(c,work,folder,cfg,b1folder):
    retention=[];shares=[]
    for M in cfg['minimum_opportunities']:
        src=Path(b1folder)/f'M{M}_year1/posteriors_PRIVATE.parquet'
        if not src.exists():continue
        c.execute('CREATE OR REPLACE TEMP VIEW types AS SELECT * FROM '+scan(src))
        c.execute('CREATE OR REPLACE TEMP VIEW validation AS SELECT p.*,t.modal_type,t.max_posterior FROM panel p JOIN types t USING(chooser)')
        from diagnostics import rate_table
        rate_table(c,folder/f'B3_M{M}_year2_profiles.csv','modal_type,state','year=2','validation')
        retention+=records(c,f'''SELECT {M} M,t.modal_type,count(*) year1_accounts,
          count(a.chooser) returned_year2,avg(t.max_posterior) mean_max_posterior
          FROM types t LEFT JOIN (SELECT DISTINCT chooser FROM panel WHERE year=2) a USING(chooser) GROUP BY t.modal_type''')
        c.execute('''CREATE OR REPLACE TEMP TABLE preferred_speed AS SELECT chooser,speed FROM
          (SELECT chooser,speed,count(*) n FROM panel WHERE year=1 GROUP BY ALL)
          QUALIFY row_number() OVER(PARTITION BY chooser ORDER BY n DESC,speed)=1''')
        shares+=records(c,f'''SELECT {M} M,s.speed,t.modal_type,count(*) accounts FROM types t JOIN preferred_speed s USING(chooser) GROUP BY ALL''')
        markers=Path(work)/'00_markers/account_markers_PRIVATE.parquet'
        if markers.exists():
            copy(c,f'''SELECT t.*,m.* EXCLUDE(chooser) FROM types t
              LEFT JOIN {scan(markers)} m ON t.chooser=m.chooser AND m.year=1''',folder/f'account_types_markers_M{M}_PRIVATE.parquet')
            fields=['rating_level_main_opportunities','rating_sd_main_opportunities','rating_level_primary_speed_opportunities','rating_sd_primary_speed_opportunities','tenure_days','patron']
            out=[]
            for f in fields:
                out+=records(c,f'''SELECT {M} M,t.modal_type,{q(f)} marker,count(*) type_accounts,count(m.{f}) observed,
                  avg(m.{f}) mean,stddev_samp(m.{f})/sqrt(count(m.{f})) se
                  FROM types t LEFT JOIN {scan(markers)} m ON t.chooser=m.chooser AND m.year=1 GROUP BY t.modal_type''')
            csvwrite(folder/f'B3_M{M}_marker_means.csv',out)
        # Y2 types re-estimated independently; use optimal profile alignment only for comparison, never Y1 assignment.
        a=Path(b1folder)/f'M{M}_year1/selected.json';b=Path(b1folder)/f'M{M}_year2/selected.json'
        if b.exists():
            f1,f2=read(a),read(b);meta=dict(M=M,K_year1=f1['K'],K_year2=f2['K'],year1_shares=f1['pi'],year2_shares=f2['pi'])
            if f1['K']==f2['K']:meta['year2_alignment_to_year1']=alignment(f1['p'],f2['p']).tolist()
            write(folder/f'B3_M{M}_independent_year_comparison.json',meta)
    csvwrite(folder/'B3_retention.csv',retention);csvwrite(folder/'B3_speed_type_counts.csv',shares)
    write(folder/'interpretation.json',dict(assignments='Year1 only; main validation uses year1 modal types without reclassification',
      uncertainty='Rate SEs cluster by account conditional on fitted assignments. Profile/share estimation uncertainty is separately bootstrapped.',
      patron='Selected later snapshot; report coverage and avoid population ordering claims without sampling correction.'))
