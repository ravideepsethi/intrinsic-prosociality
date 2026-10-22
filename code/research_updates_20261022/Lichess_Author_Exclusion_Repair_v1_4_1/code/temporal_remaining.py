"""B2/C9 benchmarks with original randomness, factual sessions and repaired eligibility."""
from remaining_common import *
import ast

def set_cardinality(source,target,values):
    tree=ast.parse(Path(source).read_text());seen=set()
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in values:
            name=node.targets[0].id;node.value=ast.Constant(int(values[name]));seen.add(name)
    require(seen==set(values),'B2 cardinality binding no longer matches source')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(ast.unparse(ast.fix_missing_locations(tree))+'\n')
    # Confirm every function body remains identical.
    functions=lambda t:{n.name:ast.dump(n,include_attributes=False) for n in t.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    require(functions(ast.parse(Path(source).read_text()))==functions(ast.parse(target.read_text())),'B2 estimator or RNG changed')

def run_stage(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/c9ply'))
    from runner import run_c9 as prior,run_ply,ply_engine
    a=argparse.Namespace(project_root=args.project,workers=min(args.workers,4),memory_gb=args.memory_gb)
    paths,session,c9,b2,reference,preflight,references=run_ply.authenticate(a)
    core=module('author_b1_core',ROOT/'vendor/companion/vendor/core/receipt_core.py')
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    extended=out/'PRIVATE/frozen_b1_with_game_identity.parquet'
    try:
        inc=[Path(r['path']) for r in args.auths['included']['month_records']]
        sql=core.b1_sample_sql(inc);needle='m.chooser_index,'
        require(sql.count(needle)==1,'B1 source projection changed')
        sql=sql.replace(needle,needle+' p.game_id AS author_game_key,')
        copy(c,sql,extended)
        original_cols=pq.ParquetFile(paths['b1']).schema_arrow.names
        selected=','.join(map(ident,original_cols))
        bad=c.execute('SELECT count(*) FROM ((SELECT '+selected+' FROM '+scan(extended)+' EXCEPT ALL SELECT * FROM '+scan(paths['b1'])+') UNION ALL (SELECT * FROM '+scan(paths['b1'])+' EXCEPT ALL SELECT '+selected+' FROM '+scan(extended)+'))').fetchone()[0]
        require(bad==0,'Rebuilt full B1 input does not reproduce authenticated frozen input')
        removed_games(args.auths,c)
        hits=c.execute('SELECT count(*) FROM '+scan(extended)+' e JOIN author_games a ON a.game_id=e.author_game_key').fetchone()[0]
        if args.variant=='excluded' and hits:
            # Retain the original chooser index (and therefore cross-fit fold),
            # but recreate sequential row/sequence positions after removing games.
            c.execute('CREATE TABLE retained AS SELECT e.* FROM '+scan(extended)+' e ANTI JOIN author_games a ON a.game_id=e.author_game_key')
            c.execute('CREATE TABLE eligible AS SELECT chooser_index FROM retained GROUP BY 1 HAVING count(*)>=4 AND sum(kind_draw::INTEGER)>=2 AND sum(kind_draw::INTEGER)<count(*)')
            c.execute('CREATE TABLE mapped AS SELECT r.*,row_number() OVER(ORDER BY r.chooser_index,r.sequence_index)-1 new_id,row_number() OVER(PARTITION BY r.chooser_index ORDER BY r.sequence_index)-1 new_seq FROM retained r SEMI JOIN eligible USING(chooser_index)')
            sample=out/'PRIVATE/b1.parquet'
            projection=','.join('new_id::BIGINT b1_row_id' if k=='b1_row_id' else 'new_seq::INTEGER sequence_index' if k=='sequence_index' else ident(k) for k in original_cols)
            copy(c,'SELECT '+projection+' FROM mapped ORDER BY new_id',sample)
            new_session=out/'PRIVATE/sessions.parquet'
            copy(c,'SELECT m.new_id::BIGINT b1_row_id,m.chooser_index,m.new_seq::INTEGER sequence_index,s.session_id,s.speed FROM mapped m JOIN '+scan(session)+' s USING(b1_row_id) ORDER BY m.new_id',new_session)
            n,g,k=c.execute('SELECT count(*),count(DISTINCT chooser_index),sum(kind_draw::INTEGER) FROM '+scan(sample)).fetchone()
            require(pq.ParquetFile(new_session).metadata.num_rows==n,'Filtered factual session mapping lost rows')
        else:sample=paths['b1'];new_session=session
    finally:c.close()
    # All donor/training rows for the B1 nuisance model are exactly this B1
    # sample. Exact equality therefore validates probabilities and every draw.
    if args.variant=='included' or hits==0:
        source=paths['public_base']/run_ply.SPEC['original_c9_config_sha256'][:12]
        prior.verify_public(source);csv_reports(source,out/'report/c9')
        csv_reports(paths['b2_public'],out/'report/b2')
        pbase=args.project/'output/pool_main_reanalysis_v100/c9_ply_v100'
        success=unique_path([p for p in pbase.glob('*/_SUCCESS.json') if read(p).get('status') in ('C9_PLY_SENSITIVITIES_COMPLETE','C9_PLY_COMPLETE_WITH_SUPPORT_WARNINGS')],'Completed current-pool C9 ply result')
        prior.verify_public(success.parent)
        cfg=read(success.parent/'CONFIGURATION.json')
        require(cfg['config']['specification']==run_ply.SPEC,'C9 ply report specification differs')
        csv_reports(success.parent,out/'report/c9_ply')
        return dict(status='EXACT_ANALYTICAL_AND_TRAINING_INPUTS_UNCHANGED',author_games_in_repeat_granter_sample=hits,randomizations_reused=4999,all_game_sessions_preserved=True,input_reproduction=True)
    key=digest([auth['fingerprint'],record(sample),record(new_session),sha(__file__)])
    core.EXPECTED_B1_OPPORTUNITIES=int(n);core.EXPECTED_B1_KIND_DRAWS=int(k);core.EXPECTED_B1_CHOOSERS=int(g)
    core.build_or_authenticate_b1_propensities({'resume_config_sha256':key},out/'PRIVATE',sample)
    prop=out/'PRIVATE/b1_crossfit_propensity_private.parquet'
    script=out/'PRIVATE/generated/author_b2_bound.py'
    set_cardinality(paths['b2_script'],script,dict(EXPECTED_ROWS=n,EXPECTED_CHOOSERS=g,EXPECTED_KIND_DRAWS=k))
    sys.path.insert(0,str(script.parent));b2=module('author_b2_bound',script)
    newpaths=dict(paths,b1=sample,prop=prop,b2_script=script)
    _,data,probability,sessions,speed,ply,bands=ply_engine.load_vectors(sample,prop,new_session,script)
    budget=run_ply.worker_budget(data,ply,b2,args.workers,args.memory_gb)
    write(out/'report/RESOURCE_PLAN.json',budget)
    observed_b2=b2.observed_totals(data);observed_c9=c9.observed_totals(data,sessions,speed)
    observed_ply=ply_engine.observed(data,sessions,speed,ply,c9)
    del data,probability,sessions,speed,ply,bands
    b2state=out/'PRIVATE/b2';(b2state/'randomizations').mkdir(parents=True,exist_ok=True)
    sim=b2.run_randomizations(dict(sample=sample,propensity=prop,state=b2state,config_sha256=key,workers=budget['effective_workers']))
    result=b2.summarize(observed_b2,sim);write(out/'report/b2_summary.json',result)
    for name,label in [('horizons','b2_first_grant_horizons'),('payoff_groups','b3_first_grant_payoff_groups')]:table(out/'report/b2'/label,result[name])
    c9state=out/'PRIVATE/c9';(c9state/'randomizations').mkdir(parents=True,exist_ok=True)
    sim=c9.run_randomizations(sample,prop,new_session,script,c9state,key,budget['effective_workers'])
    rows,contrasts,summary=c9.summarize_c9(observed_c9,sim)
    table(out/'report/c9/c9_partition_components',rows);table(out/'report/c9/c9_secondary_contrasts',contrasts)
    plystate=out/'PRIVATE/ply'
    sim,receipts,preserved=run_ply.run_batches(newpaths,new_session,plystate,key,dict(c9_state=str(c9state),b2_state=str(b2state)),budget['effective_workers'])
    rows,contrasts=run_ply.summarize(observed_ply,sim,c9)
    table(out/'report/c9_ply/c9_ply_components',rows);table(out/'report/c9_ply/c9_ply_session_contrasts',contrasts)
    return dict(status='NUISANCE_MODEL_AND_4999_DRAWS_REFITTED',author_games_removed=hits,rows=n,accounts=g,grants=k,replacement_accounts=0,fold_rule='Original chooser-index fold retained',resource_plan=budget)
