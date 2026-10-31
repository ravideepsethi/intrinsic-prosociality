"""Original K/RD and nonparametric specifications on the corrected frame."""
from bindings import *
from types import SimpleNamespace

def wave_auth(auth):
    counts=auth['census']
    return dict(auth,status='MATERIAL_INPUTS_VERIFIED',sample_root=Path(auth['sample_root']),panel_root=Path(auth['panel_root']),
        authority=dict(status='MATERIAL_INPUTS_VERIFIED',report_sha256=auth['manifest_sha256'],
          sample_name='material_restricted_pool_observed_nonadjacent',main_predicate='Reviewed main sample AND chooser has mating material; author excluded in both roles',
          rows=counts['opportunities'],kind_draws=counts['grants'],fair_rows=counts['competitive'],fair_kind_draws=counts['competitive_grants'],months=MONTHS))

def krd(a,auth,out):
    import_vendor('wave1');from runner import common,run_krd
    binding=wave_auth(auth);common.authenticate_sample=lambda *args,**kwargs:binding
    original_loader=common.load_source_module
    def loader(path,name):
        m=original_loader(path,name)
        if name=='pool_main_krd_source':
            original_duckdb=m.duckdb;spill=out/'PRIVATE/spill_krd';spill.mkdir(parents=True,exist_ok=True)
            def connect(*args,**kwargs):
                options=dict(kwargs.pop('config',{}));options['temp_directory']=str(spill)
                return original_duckdb.connect(*args,config=options,**kwargs)
            m.duckdb=SimpleNamespace(connect=connect,__version__=original_duckdb.__version__)
        return m
    common.load_source_module=loader
    ns=SimpleNamespace(sample_root=binding['sample_root'],output_root=out/'PRIVATE/model',threads=a.workers,
                       memory_limit=f'{a.memory_gb-2}GB',hash_workers=1)
    # Producer cannot restart an unfinished output directory. Preserve that
    # attempt, then reconstruct this comparatively cheap derived panel.
    model=ns.output_root
    if model.exists():model.rename(model.with_name('interrupted_'+str(time.time_ns())))
    result=run_krd.run(ns);public_copy(model,out/'report')
    require((model/'private_cache/rating_gap_krd_derived_private.parquet').is_file(),'K/RD cache missing')
    return dict(status='COMPLETE',producer_status=result['status'])

def nonparametric(a,auth,out):
    import_vendor('wave1');from runner import common,run_nonparametric
    binding=wave_auth(auth);common.authenticate_sample=lambda *args,**kwargs:binding
    prior=Path(a.batch_root)/'PRIVATE/stages/krd'
    receipt=read(prior/'DONE.json');require(receipt['input_fingerprint']==auth['fingerprint'],'K/RD parent differs')
    for r in receipt['files']:verify(r)
    model=prior/'PRIVATE/model';cache=model/'private_cache/rating_gap_krd_derived_private.parquet'
    probs=sorted({round(i/20,2) for i in range(1,20)}|{round(i/50,2) for i in range(1,50)})
    c=db(out/'PRIVATE/spill_quantiles',a.memory_gb-2,min(4,a.workers))
    try:values=c.execute('SELECT quantile_cont(k_scale,['+','.join(map(str,probs))+']) FROM '+scan(cache)).fetchone()[0]
    finally:c.close()
    values={f'{p:.2f}':float(v) for p,v in zip(probs,values)}
    original=common.load_source_module
    def loader(path,name):
        m=original(path,name)
        if name=='rating_gap_nonparametric_closure_parallel':
            m.get_quantiles=lambda connection,expr,ps:[values[f'{p:.2f}'] for p in ps]
        return m
    common.load_source_module=loader
    workers=min(3,a.workers);ns=SimpleNamespace(sample_root=binding['sample_root'],krd_root=model,output_root=out/'PRIVATE/model',
        prep_threads=min(4,a.workers),prep_memory_limit=f'{a.memory_gb-2}GB',model_workers=workers,
        worker_threads=1,worker_memory_limit=f'{(a.memory_gb-2)/workers}GB',hash_workers=1)
    result=run_nonparametric.run(ns)
    r=read(ns.output_root/'00_private_cache_receipt.json')
    require(r['k20_cutpoints']==[values[f'{i/20:.2f}'] for i in range(1,20)] and
            r['k50_cutpoints']==[values[f'{i/50:.2f}'] for i in range(1,50)] and r['k95']==values['0.95'],'K reference differs')
    public_copy(ns.output_root,out/'report')
    # Original consolidated statistics are Parquets. Export aggregate tables,
    # not the private opportunity cache, so the return is directly reviewable.
    for name in ['fe_nonparametric_coefficients','fe_nonparametric_curves','fe_nonparametric_receipts']:
        p=ns.output_root/(name+'.parquet')
        if p.is_file():table(out/'report'/name,pd.read_parquet(p))
    write(out/'report/EXACT_K_REFERENCE.json',dict(values=values,source='Corrected material main sample',method='exact quantile_cont; original cut probabilities'))
    return dict(status='COMPLETE',producer_status=result['status'])
