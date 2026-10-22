"""Original core producers, with explicit rank/estimability checks around their fits."""
from __future__ import annotations
import gc, inspect, shutil
from pathlib import Path
import numpy as np
from scipy.linalg import qr
from next_common import *

def guarded_fit(module, style, audits):
    original=module.fit_lpm_cluster; signature=inspect.signature(original)
    def fit(*args, **kwargs):
        a=signature.bind(*args,**kwargs);a.apply_defaults();a=a.arguments
        y=np.asarray(a['y'],float);x=np.asarray(a['x'],float)
        if x.ndim==1:x=x[:,None]
        names=list(a['x_names' if style==8 else 'names'])
        clusters=np.asarray(a['cluster_codes' if style==8 else 'cluster'])
        fes=list(a['fixed_effect_codes']) if style==8 else ([] if a['fixed_effect'] is None else [np.asarray(a['fixed_effect'])])
        finite=np.isfinite(y)&np.isfinite(x).all(axis=1)
        import pandas as pd
        finite &= pd.notna(clusters)
        for f in fes:finite &= pd.notna(f)
        y,x,clusters=y[finite],x[finite],clusters[finite];fes=[np.asarray(f)[finite] for f in fes]
        if style==8:
            good=clusters>=0
            for f in fes:good &= f>=0
            y,x,clusters=y[good],x[good],clusters[good];fes=[f[good] for f in fes]
        if not fes and a['add_intercept']:x=np.column_stack([np.ones(len(y)),x]);names=['intercept']+names
        k=len(names);n=len(y);g=len(np.unique(clusters));kept=[];estimable=np.zeros(k,bool)
        empty={'n_rows_raw':n,'n_rows_identifying':0,'n_clusters':g,'k':0,'rank':0,
          'x_names':names,'beta':np.full(k,np.nan),'covariance':np.full((k,k),np.nan),
          'standard_errors_array':np.full(k,np.nan),'t_statistics_array':np.full(k,np.nan),
          'coefficients':dict.fromkeys(names,float('nan')),'standard_errors':dict.fromkeys(names,float('nan')),
          't_statistics':dict.fromkeys(names,float('nan')),'absorption_method':'unsupported',
          'absorption_iterations':0,'absorption_last_adjustment':0.,'absorption_max_scaled_group_mean':0.}
        reason=None
        if n<=k or g<2:reason='INSUFFICIENT_ROWS_OR_CLUSTERS'
        else:
            z=x.copy()
            if fes:
                if style==8:
                    z,_,_,_=module.absorb_matrix(z,[(f,int(f.max())+1) for f in fes])
                else:
                    f,levels=module.dense_codes(fes[0]);z=module.demean_once(z,f,levels)
            scale=np.sqrt(np.mean(z*z,axis=0));nonzero=scale>1e-10
            safe=np.where(nonzero,scale,1.);z/=safe
            gram=z.T@z/max(1,n);del z
            ev,vec=np.linalg.eigh((gram+gram.T)/2)
            positive=ev>max(1e-10,float(ev[-1])*1e-10);rank=int(positive.sum())
            estimable=(np.sum(vec[:,~positive]**2,axis=1)<1e-8)&nonzero
            if rank==0:reason='NO_WITHIN_DESIGN_VARIATION'
            else:
                _,_,piv=qr(gram,pivoting=True);kept=sorted(map(int,piv[:rank]))
                callx=x[:,kept]/safe[kept];callnames=[names[i] for i in kept]
                if style==8:r=original(y,callx,callnames,clusters,fixed_effect_codes=fes,add_intercept=False)
                else:r=original(y,callx,callnames,clusters,fixed_effect=fes[0] if fes else None,add_intercept=False)
                require(r['rank']==rank,'Reduced, scaled core design is still numerically singular')
                if r.get('absorption_iterations',0)>=1000 and r.get('absorption_last_adjustment',0)>1e-9:
                    raise RuntimeError('Core FE absorption did not converge')
                beta=np.full(k,np.nan);se=beta.copy();ts=beta.copy();cov=np.full((k,k),np.nan)
                for ix in kept:
                    if estimable[ix]:
                        name=names[ix];beta[ix]=r['coefficients'][name]/safe[ix]
                        se[ix]=r['standard_errors'][name]/safe[ix];ts[ix]=r['t_statistics'][name]
                if style==8:
                    for j,ix in enumerate(kept):
                        for l,iy in enumerate(kept):
                            if estimable[ix] and estimable[iy]:cov[ix,iy]=r['covariance'][j,l]/safe[ix]/safe[iy]
                empty.update(r)
                empty.update(x_names=names,beta=beta,covariance=cov,standard_errors_array=se,t_statistics_array=ts,
                    coefficients=dict(zip(names,beta)),standard_errors=dict(zip(names,se)),t_statistics=dict(zip(names,ts)))
        audits.append({'fit':len(audits)+1,'n':n,'clusters':g,'declared_columns':k,'effective_rank':len(kept),
          'column_names':names,'nonestimable_terms':[s for s,e in zip(names,estimable) if not e],
          'status':reason or ('ESTIMATED_WITH_NONESTIMABLE_TERMS' if not estimable.all() else 'ESTIMATED'),
          'scaled_gram_rank_tolerance':1e-10,'producer_fit_sha256':sha(module.__file__)})
        return empty
    return fit

def guard_contrasts(module):
    original=module.linear_combination
    def contrast(result,weights):
        keep=[i for i,n in enumerate(result['x_names']) if weights.get(n,0)!=0]
        if any(n not in result['x_names'] for n,w in weights.items() if w!=0):
            return {'estimate':np.nan,'se':np.nan,'t':np.nan}
        beta=result['beta'][keep];cov=result['covariance'][np.ix_(keep,keep)]
        if not np.isfinite(beta).all() or not np.isfinite(cov).all():
            return {'estimate':np.nan,'se':np.nan,'t':np.nan}
        return original({'x_names':[result['x_names'][i] for i in keep],'beta':beta,'covariance':cov},weights)
    module.linear_combination=contrast

def run(family, sample, root, args):
    number=8 if family=='core' else 9
    filename='08_make_core_paper_results.py' if number==8 else '09_build_panel_robustness.py'
    mod=load(ROOT/'source/core'/filename,'arena_core_'+str(number))
    mod.EXPECTED_STAGE07_ROWS=sample['authority']['rows'];mod.EXPECTED_STAGE07_KIND_DRAWS=sample['authority']['kind_draws']
    audit=[];mod.fit_lpm_cluster=guarded_fit(mod,number,audit)
    if number==8:guard_contrasts(mod)
    work=Path(root)/'private'/family;public=Path(root)/'public'/family
    if work.exists():work.rename(work.with_name(work.name+'.incomplete.'+str(time.time_ns())))
    for p in ['tables','figure_data','receipts','_work/duckdb_tmp']:(work/p).mkdir(parents=True,exist_ok=True)
    c=None; summaries={}
    try:
        if number==8:
            c,qa=mod.create_core_database(work/'_work/core.duckdb',sample['panels'],threads=args.threads,
              memory_limit=args.memory,temporary_directory=work/'_work/duckdb_tmp')
            c.execute("SET TimeZone='UTC'")
            require(qa['core']['rows']==sample['authority']['rows'],'Core cache lost arena rows')
            summaries['descriptive']=mod.descriptive_outputs(c,work)
            panel=mod.load_fair_panel(c)
            require(len(panel)==sample['authority']['fair_rows'],'Core competitive panel lost rows')
            for label,fn in [('table02',mod.table02_and_figure02),('piecewise',mod.piecewise_outputs),('table07',mod.table07_outputs)]:
                log('Arena core: '+label);summaries[label]=fn(panel,work)
            summaries['original_split_halves']=mod.type_and_split_outputs(c,panel,work)
        else:
            c=mod.configure_database(work/'_work/robustness.duckdb',sample['panels'],args.threads,args.memory,work/'_work/duckdb_tmp')
            c.execute("SET TimeZone='UTC'");qa=mod.source_qa(c,sample['authority']['rows'])
            for label,fn in [('density',mod.density_outputs),('subgroups',mod.subgroup_rates),('cutoffs',mod.cutoff_rate_outputs),('economic',mod.economic_outputs)]:
                log('Arena robustness: '+label);summaries[label]=fn(c,work)
            panel=mod.load_model_panel(c)
            summaries['regressions']=mod.regression_outputs(panel,work)
            summaries['exact_zero']=mod.exact_zero_sensitivity_outputs(panel,work)
        del panel;gc.collect()
    finally:
        if c is not None:c.close()
        js(public/'NUMERICAL_AUDIT.json',audit)
    shutil.rmtree(work/'_work');export_tables(work,public)
    js(public/'PRODUCER_SUMMARIES.json',summaries);js(public/'SOURCE_QA.json',qa)
    return {'status':'COMPLETE','producer':filename,'fits':len(audit),
      'fits_with_nonestimable_terms':sum(bool(x['nonestimable_terms']) for x in audit),
      'adaptation':'Authenticated arena input; original production functions; scaled independent design basis with nonestimable individual terms suppressed.',
      'old_all_source_certification_claimed':False}
