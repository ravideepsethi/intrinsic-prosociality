"""Original 1-in-50 unordered-pair models; factual pair chronology stays fixed."""
from remaining_common import *
import ast,inspect

def retain_covariance(common):
    """Expose two existing local variables in the result, without changing arithmetic."""
    original=common.fit_hdfe_cluster
    tree=ast.parse(inspect.getsource(original));fn=tree.body[0]
    ret=fn.body[-1];require(isinstance(ret,ast.Return) and isinstance(ret.value,ast.Dict),'Original estimator return structure changed')
    ret.value.keys += [ast.Constant('covariance_terms'),ast.Constant('covariance_probability_units')]
    ret.value.values += [ast.Name(id='retained_names',ctx=ast.Load()),ast.Call(func=ast.Attribute(value=ast.Name(id='covariance',ctx=ast.Load()),attr='tolist',ctx=ast.Load()),args=[],keywords=[])]
    exec(compile(ast.fix_missing_locations(tree),'<covariance-export-only>','exec'),common.__dict__)
    return original

def validate_model_statuses(models,baseline):
    baseline={x['model']:x for x in baseline}
    require(set(baseline)=={x['model'] for x in models},'First-repeat model inventory differs')
    for x in models:
        ref=baseline[x['model']]
        require(x['status']==ref['status'],'First-repeat identification status changed: '+x['model'])
        if x['status']!='ESTIMATED':
            require(x.get('error_type')==ref.get('error_type') and str(x.get('error_message','')).startswith('HDFE absorption did not converge:'),'Unexpected first-repeat model failure')

def run_stage(args,auth,out):
    vendor=ROOT/'vendor/wave2b2a/source/c7r';sys.path.insert(0,str(vendor))
    import run_campaign1_c7r_closure_v102 as producer
    retain_covariance(producer.common)
    base=args.project/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b2a'
    original=unique_path(base.glob('**/c7r_pair_model_private.parquet'),'Pool-main C7R model cache')
    receipt=read(original.with_name('c7r_pair_model_receipt.json'))
    require(receipt['output_sha256']==sha(original),'C7R model cache changed')
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    try:
        removed_games(args.auths,c);path=out/'PRIVATE/pair_model.parquet'
        flow=game_filter(c,original,path,args.variant)
        flags=unique_path((base.parent/'wave2b1').glob('**/stage07_prefocal_first_repeat_flags_private.parquet'),'Main-panel first/repeat chronology flags')
        fr=read(flags.with_name('stage07_prefocal_first_repeat_flags_receipt.json'))
        freeze=read(flags.with_name('PREOUTCOME_SUPPORT_FROZEN.json'))
        require(fr['sha256']==sha(flags)==freeze['flags_sha256'],'First/repeat frozen chronology changed')
        c.execute('CREATE VIEW main_panel AS SELECT * FROM '+scan([r['path'] for r in auth['month_records']]))
        n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM '+scan(flags)).fetchone()
        require(n==u,'Duplicate first/repeat flag identity')
        missing=c.execute('SELECT count(*) FROM main_panel p ANTI JOIN '+scan(flags)+' f USING(game_id)').fetchone()[0]
        require(missing==0,'First/repeat chronology does not cover current main panel')
        c.execute('CREATE VIEW census AS SELECT p.*,f.first_rated_meeting,f.repeat_rated_meeting FROM main_panel p JOIN '+scan(flags)+' f USING(game_id)')
        census=[]
        for state,where in [('all','TRUE'),('competitive','engine_eval_cp_disconnected>=-100'),('clearly_worse','engine_eval_cp_disconnected<=-300')]:
            rows=c.execute("SELECT CASE WHEN first_rated_meeting THEN 'first' ELSE 'repeat' END meeting,count(*) opportunities,sum(outcome_kind_draw)::BIGINT grants,100*avg(outcome_kind_draw::DOUBLE) rate_pct FROM census WHERE "+where+' GROUP BY 1').fetchdf()
            rows['state']=state;census.extend(rows.to_dict('records'))
        table(out/'report/census_rates',census)
        if args.variant=='included':
            expected={('all','first'):(38599845,540736),('all','repeat'):(2934486,29355),('competitive','first'):(14078271,396596),('competitive','repeat'):(1129152,22867),('clearly_worse','first'):(21119042,101967),('clearly_worse','repeat'):(1545776,4589)}
            require(all((r['opportunities'],r['grants'])==expected[(r['state'],r['meeting'])] for r in census),'Full-census first/repeat table did not reproduce')
        # Every pair cache row must agree with the authenticated current main panel.
        c.execute('CREATE VIEW p AS SELECT game_id,outcome_kind_draw FROM '+scan([r['path'] for r in auth['month_records']]))
        n,bad=c.execute('SELECT count(*),count(*) FILTER(WHERE p.game_id IS NULL OR p.outcome_kind_draw::DOUBLE IS DISTINCT FROM s.kind) FROM '+scan(path)+' s LEFT JOIN p USING(game_id)').fetchone()
        require(n==flow['after'] and bad==0,'C7R outcome/main-panel bridge failed')
    finally:c.close()
    with heartbeat('First/repeat pair models'):models=producer.estimate_first_meeting_models(path,args.workers)
    write(out/'report/models.json',models);table(out/'report/models',producer.flatten_models(models))
    validate_model_statuses(models,read(ROOT/'evidence/first_repeat_baseline.json'))
    # Three original repeat-only auxiliary fits did not converge. Retain their
    # status; the manuscript uses the successful pooled interaction model.
    table(out/'report/pair_rates',producer.pair_rates(path))
    # Retain joint covariance for the repeat-meeting gradient.
    interaction=next(x for x in models if x['model']=='X_C7R_fair_repeat_interaction_all_meetings')
    write(out/'report/interaction_covariance.json',interaction)
    names=interaction['covariance_terms'];V=np.asarray(interaction['covariance_probability_units']);b={r['term']:r['coefficient'] for r in interaction['results']}
    contrasts=[]
    for label,weights in [('first_gradient',{'fair':1}),('repeat_gradient',{'fair':1,'fair_x_repeat':1}),('repeat_minus_first_gradient',{'fair_x_repeat':1})]:
        w=np.array([weights.get(n,0) for n in names]);value=100*sum(b[k]*v for k,v in weights.items());se=100*np.sqrt(max(0,w@V@w))
        contrasts.append(dict(contrast=label,estimate_pp=value,se_pp=se,ci_low_pp=value-1.96*se,ci_high_pp=value+1.96*se))
    table(out/'report/gradient_contrasts',contrasts)
    if args.variant=='included':
        require(interaction['rows']==757646 and interaction['clusters']==533531,'First/repeat interaction sample differs')
        for r,(b,se) in zip(contrasts,[(1.594,.055),(1.279,.134),(-.315,.138)]):
            require(abs(r['estimate_pp']-b)<.0005001 and abs(r['se_pp']-se)<.0005001,'First/repeat gradient did not reproduce manuscript')
        within=next(x for x in models if x['model']=='X_C7R_repeat_association_within_fair')
        row=next(x for x in within['results'] if x['term']=='repeat_meeting')
        require(within['rows']==304729 and within['clusters']==256366,'Within-competitive first/repeat sample differs')
        require(abs(100*row['coefficient']-.128)<.0005001 and abs(100*row['standard_error']-.161)<.0005001,'Within-competitive first/repeat estimate differs')
    return dict(status='ORIGINAL_FIRST_REPEAT_MODELS_REFITTED',flow=flow,original_cache=record(original),pair_sample='Original 1-in-50 roster, no replacement; raw rated-game meetings unchanged')

