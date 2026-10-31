"""Isolated adapters: unchanged estimators, material-aware analytical inputs."""
from bindings import *
import argparse,subprocess

def responsibility(a,auth,out):
    component=ROOT/'components/Mating_Material_Responsibility_v1_0_1'
    command=[sys.executable,str(component/'code/run_responsibility.py'),'--project-root',str(a.project),
             '--results-dir',str(out/'PRIVATE/native_return'),'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
    subprocess.run(command,check=True)
    latest=read(out/'PRIVATE/native_return/MATERIAL_RESPONSIBILITY_LATEST_PRIVATE.json')
    run=Path(latest['root']);success=read(run/'_SUCCESS.json')
    require(success['parent_run_id']==auth['parent_run_id'],'Responsibility parent differs')
    for r in success['files']:verify(dict(r,path=str(run/r['path'])))
    public_copy(run/'report',out/'report')
    return dict(status='COMPLETE',native_run_id=success['run_id'],models=53)

def tenure(a,auth,out):
    import tenure_remaining
    return tenure_remaining.run_stage(a,auth,out)

def arena(a,auth,out):
    import_vendor('arena');import common as ac,analysis as an
    success=unique_path([p for p in (a.project/'output/arena_replication_v102').glob('*/_SUCCESS.json')
                        if read(p).get('status')=='ARENA_REPLICATION_WAVE1_COMPLETE'],'Arena completion')
    old=success.parent;b=read(old/'private/BUILD.json');contract=b['contract']
    require(read(success)['input_contract']==contract,'Arena contract differs')
    require(len(b['panel_paths'])==len(b['narrow_paths'])==24,'Incomplete arena months')
    fresh={r['month']:r['path'] for r in auth['all_source_records']}
    c=db(out/'PRIVATE/spill',a.memory_gb-2,a.workers);paths=[];flows=[]
    try:
        for broad,small in zip(b['panel_paths'],b['narrow_paths']):
            broad,small=Path(broad),Path(small);month=broad.parent.name.removeprefix('month=')
            require(broad.parent==small.parent and ac.verify_complete(broad.parent,contract),'Unsealed arena cache')
            path=out/'PRIVATE/panels'/(month+'.parquet')
            flow=guarded_join(c,small,fresh[month],path,replacements={'kind':'n.outcome_kind_draw::DOUBLE','claimed':'n.timeout_chooser_win'},
                checks={'chooser':'n.chooser_user_id','opponent':'n.disconnected_user_id','start_ms':'n.utc_ms',
                        'eval':'n.engine_eval_cp_disconnected::DOUBLE','ply':'n.ply_count','premium':'n.chooser_win_premium_v2'})
            paths.append(str(path));flows.append(dict(month=month,**flow))
    finally:c.close()
    new=dict(b,narrow_paths=paths,contract=digest([contract,auth['fingerprint'],'material']))
    write(out/'private/BUILD.json',new)
    con,_=an.open_data(out,f'{a.memory_gb-2}GB',a.workers)
    try:
        frame=an.load_frame(con,'eval>=-100 OR eval<=-300');frame['arena_fair']=frame.arena*frame.fair
        result=an.model_save(out/'report','arena_by_board_merit',frame,['arena','arena_fair'],an.CONTROLS,an.FULL_FE,new['contract'],'Original arena interaction, corrected material frame')
        require(result['status']=='ESTIMATED','Arena model failed')
        contrasts=[dict(contrast=name,**an.linear_contrast(result,w)) for name,w in
                   [('competitive',{'arena':1,'arena_fair':1}),('clearly_worse',{'arena':1}),('difference',{'arena_fair':1})]]
        table(out/'report/contrasts',contrasts);table(out/'report/coefficients',result['coefficients'])
        table(out/'report/input_flow',flows)
        return dict(status='COMPLETE',models=1,rows=result['n'],dual_format_eligibility_rebuilt=True)
    finally:con.close()

def patron(a,auth,out):
    import_vendor('patron_remaining')
    from runner import families as f,opportunity
    from source import wave3b1_helpers as h,chooser_models_v101 as chooser
    prior=reviewed_stage(a.project,'patron')
    design=prior/'PRIVATE/design/retained_design_private.parquet'
    acquisition=prior/'PRIVATE/rosters/retained_acquisition_private.parquet'
    require(design.is_file() and acquisition.is_file(),'Reviewed Patron caches missing')
    snapshot=h.prior.authenticate_snapshot(a.project)
    key=digest([auth['fingerprint'],record(design),record(acquisition),record(snapshot)])
    c=db(out/'PRIVATE/spill',a.memory_gb-2,a.workers)
    try:
        bridge=out/'PRIVATE/bridge.parquet';bins=out/'PRIVATE/five_bins.parquet'
        copy(c,'SELECT a.*,coalesce(s.returned,false) returned,s.patron FROM '+scan(acquisition)+' a LEFT JOIN '+scan(snapshot)+' s USING(username_norm)',bridge)
        copy(c,'SELECT p.chooser_username_norm username_norm,p.engine_fairness_bin fairness_bin,count(*)::BIGINT opportunities,sum(p.kind_draw::INTEGER)::BIGINT kind_draws FROM '+
             scan([r['path'] for r in auth['records']])+' p SEMI JOIN '+scan(acquisition)+' a ON p.chooser_username_norm=a.username_norm GROUP BY 1,2',bins)
        frame=f.returned_frame(c,design,snapshot);data,groups,_=chooser.prepare_features(frame)
        main=data.loc[data.group_ever_kind_fair.astype(bool)&data.group_kind_returned.astype(bool)].copy();del frame,data
        rematches=f.rematches(main,groups,out/'PRIVATE',key,out/'report',replicates=100);del main
        post=f.postcertification(c,design,snapshot,bins,out/'PRIVATE',key,out/'report')
        cache=out/'PRIVATE/opportunity_cells.parquet'
        qa=opportunity.build_cache(c,[r['path'] for r in auth['records']],bridge,cache)
        base=opportunity.fit_families(c,cache,bridge,out/'PRIVATE',key,out/'report',ply=False)
        ply=opportunity.fit_families(c,cache,bridge,out/'PRIVATE',key,out/'report',ply=True)
        return dict(status='COMPLETE',rematches=rematches,postcertification=post,opportunity=base,ply=ply,cache=qa,replacement_matches=0)
    finally:c.close()

def split_half(a,auth,out):
    core=module('split_half_original',ROOT/'vendor/wave1/source/core/08_make_core_paper_results.py')
    c=db(out/'PRIVATE/spill',a.memory_gb-2,a.workers);correlations=[];transitions=[];grids=[]
    try:
        c.execute('CREATE VIEW p AS SELECT chooser_user_id chooser_fe_id,outcome_kind_draw y,'+
                  "CASE WHEN lower(right(md5(game_id),1)) IN ('1','3','5','7','9','b','d','f') THEN 1 ELSE 0 END hash_half,"+
                  "CASE WHEN month<'2024-11' THEN 0 ELSE 1 END temporal_half FROM "+scan([r['path'] for r in auth['records']])+' WHERE engine_eval_cp_disconnected>=-100')
        for label,col in [('hash_md5_game_id','hash_half'),('temporal_first12_second12','temporal_half')]:
            wide=c.execute(f'SELECT chooser_fe_id,count(*) FILTER(WHERE {col}=0)::BIGINT n0,count(*) FILTER(WHERE {col}=1)::BIGINT n1,'+
                           f'sum(CASE WHEN {col}=0 THEN y ELSE 0 END)::BIGINT k0,sum(CASE WHEN {col}=1 THEN y ELSE 0 END)::BIGINT k1 FROM p GROUP BY 1').fetchdf()
            corr,trans,grid=core.summarize_split(wide,label)
            correlations.append(corr);transitions.append(trans);grids.append(grid)
        table(out/'report/split_half_correlations',pd.concat(correlations));table(out/'report/split_half_transitions',pd.concat(transitions))
        table(out/'report/split_half_figure_data',pd.concat(grids))
        return dict(status='COMPLETE',method='Original MD5 split and total-opportunity cutoffs 2,4,5,10; original correlation and weighting functions')
    finally:c.close()

def first_repeat(a,auth,out):
    import_vendor('wave2b2a','source/c7r');import run_campaign1_c7r_closure_v102 as producer
    import ast,inspect
    tree=ast.parse(inspect.getsource(producer.common.fit_hdfe_cluster));ret=tree.body[0].body[-1]
    require(isinstance(ret,ast.Return) and isinstance(ret.value,ast.Dict),'Covariance export location differs')
    ret.value.keys += [ast.Constant('covariance_terms'),ast.Constant('covariance_probability_units')]
    ret.value.values += [ast.Name(id='retained_names',ctx=ast.Load()),ast.Call(func=ast.Attribute(value=ast.Name(id='covariance',ctx=ast.Load()),attr='tolist',ctx=ast.Load()),args=[],keywords=[])]
    exec(compile(ast.fix_missing_locations(tree),'<covariance-export-only>','exec'),producer.common.__dict__)
    base=a.project/'derived/replication/pool_main_reanalysis_v100_PRIVATE'
    original=unique_path((base/'wave2b2a').glob('**/c7r_pair_model_private.parquet'),'Frozen 1-in-50 pairs')
    require(read(original.with_name('c7r_pair_model_receipt.json'))['output_sha256']==sha(original),'Pair cache changed')
    flags=unique_path((base/'wave2b1').glob('**/stage07_prefocal_first_repeat_flags_private.parquet'),'Factual pair flags')
    require(read(flags.with_name('stage07_prefocal_first_repeat_flags_receipt.json'))['sha256']==sha(flags)==read(flags.with_name('PREOUTCOME_SUPPORT_FROZEN.json'))['flags_sha256'],'Pair chronology changed')
    c=db(out/'PRIVATE/spill',a.memory_gb-2,a.workers);path=out/'PRIVATE/pairs.parquet'
    try:
        paths=[r['path'] for r in auth['records']]
        flow=guarded_join(c,original,paths,path,replacements={'kind':'n.outcome_kind_draw::DOUBLE'},checks={
            'chooser_id':'n.chooser_user_id','opponent_id':'n.disconnected_user_id','ply_count':'n.ply_count',
            'win_premium':'n.chooser_win_premium_v2','draw_payoff':'n.chooser_draw_payoff_v2'})
        c.execute('CREATE VIEW p AS SELECT * FROM '+scan(paths));c.execute('CREATE VIEW f AS SELECT * FROM '+scan(flags))
        n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM f').fetchone();require(n==u,'Duplicate pair flags')
        require(c.execute('SELECT count(*) FROM p ANTI JOIN f USING(game_id)').fetchone()[0]==0,'Missing factual pair flags')
        rows=[]
        for state,where in [('all','TRUE'),('competitive','engine_eval_cp_disconnected>=-100'),('clearly_worse','engine_eval_cp_disconnected<=-300')]:
            d=c.execute("SELECT CASE WHEN first_rated_meeting THEN 'first' ELSE 'repeat' END meeting,count(*) opportunities,sum(outcome_kind_draw)::BIGINT grants,100*avg(outcome_kind_draw::DOUBLE) rate_pct FROM p JOIN f USING(game_id) WHERE "+where+' GROUP BY 1').fetchdf();d['state']=state;rows.append(d)
        table(out/'report/full_census',pd.concat(rows));write(out/'report/FLOW.json',flow)
    finally:c.close()
    models=producer.estimate_first_meeting_models(path,a.workers)
    write(out/'report/models.json',models);table(out/'report/models',producer.flatten_models(models));table(out/'report/pair_rates',producer.pair_rates(path))
    expected={r['model'] for r in read(ROOT/'authority/first_repeat_baseline.json')}
    require({r['model'] for r in models}==expected,'First/repeat model inventory changed')
    interaction=next(r for r in models if r['model']=='X_C7R_fair_repeat_interaction_all_meetings')
    require(interaction['status']=='ESTIMATED','Required pooled interaction failed')
    names=interaction['covariance_terms'];V=np.asarray(interaction['covariance_probability_units']);b={r['term']:r['coefficient'] for r in interaction['results']}
    contrasts=[]
    for label,w0 in [('first',{'fair':1}),('repeat',{'fair':1,'fair_x_repeat':1}),('difference',{'fair_x_repeat':1})]:
        w=np.array([w0.get(n,0) for n in names]);contrasts.append(dict(contrast=label,estimate_pp=100*sum(b[k]*v for k,v in w0.items()),se_pp=100*np.sqrt(max(0,w@V@w))))
    table(out/'report/contrasts',contrasts)
    unsupported=[r['model'] for r in models if r['status']!='ESTIMATED']
    return dict(status='COMPLETE_WITH_UNSUPPORTED_AUXILIARIES' if unsupported else 'COMPLETE',models=len(models),unsupported=unsupported,
                frozen_pair_sample='1-in-50; separate from the current 1-in-5 reputation design')
