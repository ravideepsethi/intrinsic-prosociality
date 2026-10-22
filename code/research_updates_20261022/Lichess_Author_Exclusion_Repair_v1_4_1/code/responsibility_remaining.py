"""Refit all 53 repaired A2 specifications on the frozen 20,000-account sample."""
from remaining_common import *

def run_stage(args,auth,out):
    vendor=ROOT/'vendor/a2_repaired';sys.path.insert(0,str(vendor))
    import features,analysis_runner as ar,report as rp,history
    old=args.project/'output/tenure_responsibility_v100/c539ba215e708b22'
    repaired=args.project/'output/kac_a2_score_repair_v101/14eda066d25b14f4'
    verify_report(ROOT/'evidence/a2_repaired',repaired/'report')
    target=old/'PRIVATE/trajectory_targets.parquet';checked_sidecar(target)
    lineage=read(repaired/'report/LINEAGE.json')
    require(sha(target)==lineage['target_sha256'],'A2 frozen target changed')
    projected=sorted((repaired/'PRIVATE/projected').glob('*.parquet'))
    require(len(projected)>0,'Repaired A2 feature cache missing')
    for p in projected:checked_sidecar(p)
    d=features.prepare_targets(target);f=pd.concat([pq.ParquetFile(p).read().to_pandas() for p in projected],ignore_index=True)
    require(len(d)==260863 and d.game_id.nunique()==len(d) and len(f)==len(d),'A2 frozen roster changed')
    d=d.merge(f,on='game_id',validate='one_to_one',sort=False)
    c=db(out/'PRIVATE/spill',1,1)
    try:
        removed_games(args.auths,c);bad=set(c.execute('SELECT game_id FROM author_games').fetchnumpy()['game_id'])
    finally:c.close()
    n=len(d);hits=int(d.game_id.isin(bad).sum())
    if args.variant=='excluded':d=d.loc[~d.game_id.isin(bad)].copy()
    require(not (args.variant=='excluded' and d.game_id.isin(bad).any()),'Author game survived A2')
    d,h=history.attach(d,None);ar.coverage(d,out/'report')
    key=digest([auth['fingerprint'],lineage,sha(__file__),[record(p) for p in projected]])
    specs,fits,meats=ar.run_models(d,out,key,min(args.workers,max(1,int(args.memory_gb//1.25))),False)
    rp.render(out/'report',specs,fits,meats,h)
    require(len(specs)==53,'Repaired A2 model inventory changed')
    if args.variant=='included':
        a=pd.read_csv(out/'report/coefficients.csv');b=pd.read_csv(repaired/'report/coefficients.csv')
        keys=[x for x in ['model','term','variable'] if x in a and x in b]
        require(keys and not a.duplicated(keys).any() and not b.duplicated(keys).any(),'A2 coefficient identity ambiguous')
        z=a.merge(b,on=keys,suffixes=('_a','_b'),validate='one_to_one')
        require(len(z)==len(a)==len(b),'A2 baseline coefficient inventory differs')
        for name in a.select_dtypes('number').columns:
            if name in keys or name not in b:continue
            require(np.allclose(z[name+'_a'],z[name+'_b'],rtol=2e-7,atol=2e-8,equal_nan=True),'A2 original estimate did not reproduce: '+name)
    return dict(status='ALL_53_REPAIRED_MODELS_REFITTED',before=n,after=len(d),author_game_hits=hits,new_engine_searches=0,replacement_accounts=0,history_models='Not in current manuscript; no unobserved history coded zero')
