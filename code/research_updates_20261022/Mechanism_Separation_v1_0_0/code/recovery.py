"""Parametric recovery on the actual complete-account design, including refits."""
from scipy.special import expit
from common import *
from design import MODELS,design
from stats import account_intercepts
from models import compare,decision,compatible_models

def generate_probabilities(d,fit,half_frame=False):
    beta=np.asarray(fit['beta'],float).copy()
    if half_frame:
        if 'draw_frame' not in fit['names']:raise ValueError('Half framing requires framing generator')
        beta[fit['names'].index('draw_frame')]*=.5
    X,_,_=design(d,fit['model'],fit['curvature']);eta=X@beta
    ids,a,base=account_intercepts(eta,d.y.to_numpy(float),d.chooser.to_numpy())
    return expit(eta+a[np.searchsorted(ids,d.chooser.to_numpy())])

def recovery_task(task):
    data_path,prob_path,generator,rep,work,seed=task;work=Path(work)
    out=work/'recovery'/f'{generator}_{rep:03d}.json';key=digest(dict(data=stamp(data_path),prob=stamp(prob_path),generator=generator,rep=rep,seed=seed,version=VERSION))
    if out.exists():
        old=read(out)
        if old['key']!=key:raise RuntimeError('Recovery checkpoint changed')
        return old['result']
    d=pd.read_parquet(data_path);p=np.load(prob_path,mmap_mode='r')
    rng=np.random.default_rng(np.random.SeedSequence([seed,rep,int(digest(generator)[:8],16)]))
    d['y']=(rng.random(len(p))<p).astype(np.int8)
    # Full model pipeline on both forward folds, reapplying switcher selection.
    _,scores=compare(d,work/'simulation_transient',work/'simulation_transient',generator,False,save=False,fit_full=False)
    retained=compatible_models(scores)
    result=dict(generator=generator,rep=rep,selected=decision(scores),compatible_models=';'.join(retained),
                generator_retained=generator.removesuffix('_half_effect') in retained,
                simulated_grants=int(d.y.sum()),n=len(d))
    write(out,dict(key=key,result=result,scores=scores));log(f'Recovery {generator} {rep+1}: {result["selected"]}')
    return result

def prepare_recovery(d,fits,work):
    work=Path(work);out=work/'simulation_design.parquet';key=digest(dict(version=VERSION,n=len(d),
        data_hash=hashlib.sha256(pd.util.hash_pandas_object(d,index=False).values.tobytes()).hexdigest()))
    if not reuse(out,key):frame(d,out);done(out,key)
    inputs=[]
    for model in MODELS:
        f=fits[model]
        if f['status']!='ESTIMATED':continue
        for half in ([False,True] if model=='framing' else [False]):
            name=model+('_half_effect' if half else '');p=work/'recovery_probabilities'/(name+'.npy');p.parent.mkdir(exist_ok=True)
            pk=digest(dict(data_key=key,beta=f['beta'],curvature=f['curvature'],half=half))
            if not reuse(p,pk):
                prob=generate_probabilities(d,f,half);tmp=p.with_name(p.name+'.partial')
                with open(tmp,'wb') as h:np.save(h,prob)
                os.replace(tmp,p);done(p,pk)
            inputs.append((name,str(p)))
    return str(out),inputs

def summarize_recovery(rows,report,reps):
    df=pd.DataFrame(rows)
    if df.empty:
        write(Path(report)/'RECOVERY_STATUS.json',dict(status='NO_VALID_GENERATORS',shares_released=False));return
    tab=df.groupby(['generator','selected']).size().rename('count').reset_index()
    tab['share']=tab['count']/tab.groupby('generator')['count'].transform('sum')
    table(tab,Path(report)/'recovery_confusion.parquet');table(df,Path(report)/'recovery_runs.parquet')
    write(Path(report)/'RECOVERY_STATUS.json',dict(status='SPECIFIED_MODEL_RECOVERY_COMPLETE',
        repetitions_per_generator=reps,monte_carlo_resolution=1/reps,shares_released=False,
        limitations='Fitted-generator and half-framing simulation. Does not establish exogeneity, robustness to arbitrary omitted variables, or correctness of preferences. Indistinguishable and failed fits are retained.'))
