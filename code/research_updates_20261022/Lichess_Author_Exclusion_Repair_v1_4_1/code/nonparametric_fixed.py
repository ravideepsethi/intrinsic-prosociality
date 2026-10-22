"""Paired nonparametric fits with one exact author-free K reference distribution."""
from engine import *

def cuts(args,parent):
    target=args.run/'PRIVATE/EXACT_K_CUTS.json'
    source=parent/'PRIVATE/results/excluded/rating_gap/private_cache/rating_gap_krd_derived_private.parquet'
    sr=record(source);key=digest([sr['sha256'],sha(__file__)])
    if target.exists():
        r=read(target);require(r['key']==key,'Exact K reference changed');return target
    probs=sorted({round(i/20,2) for i in range(1,20)}|{round(i/50,2) for i in range(1,50)})
    c=db(args.run/'PRIVATE/spill_quantiles',args.memory_gb-2,min(4,args.workers))
    try:
        with heartbeat('Exact K cutoffs from author-excluded data'):
            values=c.execute('SELECT quantile_cont(k_scale,['+','.join(map(str,probs))+']) FROM '+scan(source)).fetchone()[0]
    finally:c.close()
    require(signature(source)==sr['verified_signature'],'K reference changed during quantile calculation')
    r=dict(key=key,source=sr,values={f'{p:.2f}':float(v) for p,v in zip(probs,values)},method='exact quantile_cont on author-excluded K/RD full sample; same fixed controls and restriction in both paired fits')
    write(target,r);write(args.run/'report/EXACT_K_REFERENCE.json',{k:v for k,v in r.items() if k!='source'})
    return target

def run(args,auth,out,parent):
    cutfile=cuts(args,parent);values=read(cutfile)['values']
    sys.path.insert(0,str(ROOT/'vendor/wave1'))
    from runner import common,run_nonparametric
    common.authenticate_sample=lambda *a,**k:auth
    original_loader=common.load_source_module
    def loader(path,name):
        m=original_loader(path,name)
        if name=='rating_gap_nonparametric_closure_parallel':
            m.get_quantiles=lambda connection,expr,probs:[values[f'{p:.2f}'] for p in probs]
        return m
    common.load_source_module=loader
    from types import SimpleNamespace
    a=SimpleNamespace(sample_root=auth['sample_root'],krd_root=parent/'PRIVATE/results'/args.variant/'rating_gap',output_root=out,prep_threads=min(4,args.workers),prep_memory_limit=f'{args.memory_gb}GB',model_workers=min(3,args.workers),worker_threads=1,worker_memory_limit=f'{(args.memory_gb-2)/min(3,args.workers)}GB',hash_workers=1)
    result=run_nonparametric.run(a)
    receipt=read(out/'00_private_cache_receipt.json')
    require(receipt['k20_cutpoints']==[values[f'{i/20:.2f}'] for i in range(1,20)] and receipt['k50_cutpoints']==[values[f'{i/50:.2f}'] for i in range(1,50)] and receipt['k95']==values['0.95'],'Producer did not use common exact cutoffs')
    diagnostics=pd.read_parquet(out/'fe_nonparametric_receipts.parquet')
    deficient=diagnostics.loc[diagnostics['rank']<diagnostics['terms_kept']]
    coefficients=pd.read_parquet(out/'fe_nonparametric_coefficients.parquet')
    write(args.run/'report'/('NONPARAMETRIC_IDENTIFICATION_'+args.variant.upper()+'.json'),{
        'rank_deficient_models':deficient[['model_id','rank','terms_kept','condition_number']].to_dict('records'),
        'unidentified_coefficients':int((coefficients.identified==0).sum()),
        'interpretation':'Original rank/identification diagnostics retained. Fixed cutoffs do not resolve sparse or unidentified coefficients; review before substantive claims.'})
    write(out/'FIXED_REFERENCE_POLICY.json',{'cut_reference_sha256':sha(cutfile),'author_free_reference':True,'same_cutoffs_both_variants':True,'other_estimation_functions_unchanged':True,'previous_approximate_cutpoint_results':'retained separately; not the clean author-exclusion contrast'})
    return result
