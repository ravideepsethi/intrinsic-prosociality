"""Run each historical producer in its own process, on explicitly verified inputs.

Estimator functions are unchanged. Changed census expectations are bound to a
fresh independent census, never disabled. No producer's main() is invoked.
"""
from engine import *
from additional import activity
import argparse, concurrent.futures as cf, multiprocessing as mp

def mapped(fn,tasks,workers,label):
    start=time.monotonic();out=[]
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        fs=[pool.submit(fn,t) for t in tasks]
        for f in cf.as_completed(fs):
            out.append(f.result());elapsed=time.monotonic()-start
            log(f'{label}: {len(out)}/{len(fs)}; measured ETA {elapsed/len(out)*(len(fs)-len(out))/60:.1f} min')
    return out

def wave(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/wave1'))
    from runner import common
    common.authenticate_sample=lambda *a,**k: auth
    a=argparse.Namespace(sample_root=auth['sample_root'],output_root=out,
        threads=args.workers,memory_limit=f'{args.memory_gb}GB',hash_workers=min(4,args.workers))
    parent=out.parent
    if args.stage=='core':from runner import run_core as producer
    elif args.stage=='panel_robustness':
        from runner import run_panel_robustness as producer
        a.stage08_root=parent/'core'
    elif args.stage=='rating_gap':from runner import run_krd as producer
    elif args.stage=='nonparametric':
        from runner import run_nonparametric as producer
        a.krd_root=parent/'rating_gap';a.prep_threads=args.workers;a.prep_memory_limit=a.memory_limit
        a.model_workers=min(args.workers,3);a.worker_threads=1;a.worker_memory_limit=f'{max(.5,(args.memory_gb-1)/a.model_workers)}GB'
    elif args.stage=='controlled_reference':
        from runner import run_controlled_reference as producer
        a.model_output=out/'model';a.private_root=out/'PRIVATE';a.figure_output=out/'figures';a.scratch_root=out/'scratch'
        a.memory=a.memory_limit;a.batch_rows=32768
    else:raise RuntimeError('Unknown wave adapter')
    return producer.run(a)

def projections(args,auth,out,prepare,memory_name):
    jobs=[];paths=[];key=digest([auth['fingerprint'],args.stage,args.shards])
    for r in auth['month_records']:
        p=out/'PRIVATE/projected'/f'{r["month"]}.parquet';paths.append(p)
        jobs.append(dict(source=str(r['path']),expected_sha256=r['expected_sha256'],rows=r['rows'],month=r['month'],output=str(p),key=key,**{memory_name:min(1.5,(args.memory_gb-1)/4)}))
    counts=mapped(prepare.project_month,jobs,min(4,args.workers),'Project '+args.stage)
    require(sum(x['n'] for x in counts)==auth['census']['opportunities'],'Projection census mismatch')
    require(sum(x['grants'] for x in counts)==auth['census']['grants'],'Projection grant mismatch')
    table(out/'report/monthly_validation',counts)
    return paths,key

def merit(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/merit'))
    import prepare,run,design
    paths,key=projections(args,auth,out,prepare,'memory_gb')
    validation=prepare.raw_summaries(paths,out,args.workers,args.memory_gb)
    require(validation['choosers']==auth['census']['choosers'],'Merit chooser count mismatch')
    part=prepare.partition(paths,out,args.shards,args.workers,args.memory_gb,key)
    fits=run.analyse(out,paths,design.specifications(),part,args.workers,args.memory_gb,key,validation)
    return {'models':len(fits)}

def r11(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/r11'))
    import prepare,design,estimate,report
    paths,key=projections(args,auth,out,prepare,'memory')
    # Bind the historical fixed-census gates to independently counted NEW inputs.
    # Expected forty-cell support is computed directly from full-width inputs.
    c=db(out/'PRIVATE/spill_cells',args.memory_gb,args.workers)
    try:
        source=scan([r['path'] for r in auth['month_records']])
        cells=c.execute('''SELECT CASE WHEN engine_eval_cp_disconnected>=300 THEN 4 WHEN engine_eval_cp_disconnected>=101 THEN 3 WHEN engine_eval_cp_disconnected>=-100 THEN 2 WHEN engine_eval_cp_disconnected>=-299 THEN 1 ELSE 0 END position_code,
            CASE WHEN ply_count<=4 THEN 0 WHEN ply_count<=6 THEN 1 WHEN ply_count<=8 THEN 2 WHEN ply_count<=10 THEN 3 WHEN ply_count<=20 THEN 4 WHEN ply_count<=40 THEN 5 WHEN ply_count<=80 THEN 6 ELSE 7 END stage_code,
            count(*) opportunities,sum(outcome_kind_draw)::BIGINT grants FROM '''+source+' GROUP BY ALL ORDER BY ALL').fetchall()
    finally:c.close()
    expected=[dict(position=design.POSITIONS[p],stage=design.STAGES[s],opportunities=n,grants=g) for p,s,n,g in cells]
    import ast,inspect
    bindings={41534331:auth['census']['opportunities'],570091:auth['census']['grants'],3224173:auth['census']['choosers'],15207423:auth['census']['competitive'],419463:auth['census']['competitive_grants']}
    class CensusBindings(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is int and node.value in bindings:return ast.copy_location(ast.Constant(bindings[node.value]),node)
            return node
    for name in ('raw_summaries','partition'):
        tree=CensusBindings().visit(ast.parse(inspect.getsource(getattr(prepare,name))))
        ast.fix_missing_locations(tree);exec(compile(tree,str(ROOT/'vendor/r11/prepare.py'),'exec'),prepare.__dict__)
    original_load=prepare.load
    prepare.load=lambda p:expected if Path(p).name=='EXPECTED_BOARD_STAGE.json' else original_load(p)
    validation=prepare.raw_summaries(paths,out,args.workers,args.memory_gb)
    validation['author_accounts_retained']=args.variant=='included';write(out/'report/CENSUS.json',validation)
    write(out/'report/CENSUS_BINDINGS.json',{'source_counts':auth['census'],'forty_cells_verified_against_full_width_inputs':True,'bindings':bindings})
    part=prepare.partition(paths,out,args.shards,args.workers,args.memory_gb,key)
    by={}
    for f in part['files']:
        b=int(Path(f['relative']).parts[0].split('=')[1]);by.setdefault(b,[]).append(out/'PRIVATE/by_chooser'/f['relative'])
    _,names,indices=design.design(design.dummy());_,mnames=design.moments_design(design.dummy())
    largest=max(sum(pq.ParquetFile(p).metadata.num_rows for p in files) for files in by.values())
    per=(largest*8*(4*len(names)+4*len(mnames)+40)+200_000_000)/2**30
    require(per<args.memory_gb-.75,'R11 largest shard exceeds memory; increase --shards')
    nw=max(1,min(args.workers,int((args.memory_gb-.75)/max(.4,per))))
    fit=None
    for phase in (1,2):
        jobs=[];moment_paths=[]
        for b,files in sorted(by.items()):
            p=out/f'PRIVATE/moments/phase{phase}_{b:04d}.npz';moment_paths.append(p)
            job=dict(bucket=b,files=list(map(str,files)),out=str(p),key=digest([key,phase,b]),phase=phase)
            if phase==2:job['fit']=fit
            jobs.append(job)
        mapped(estimate.task,jobs,nw,'R11 pass '+str(phase))
        if phase==1:
            fit=estimate.fit_first(moment_paths,names,indices,mnames)
            require((fit['n'],fit['g'])==(auth['census']['opportunities'],auth['census']['choosers']),'R11 fitted census mismatch')
    report.write_report(out,fit,estimate.combine(moment_paths))
    return {'models':len(fit['fits']),'all_game_pgn_quantiles':'NOT_REQUESTED_OR_RUN'}

def session(args,auth,out):
    from session_reuse import run_session
    return run_session(args,auth,out)


def prepare_patron_roster(c,original,acquired):
    """The caller builds chooser_summary from the filtered full-width panels."""
    cols=[x[0] for x in c.execute('DESCRIBE chooser_summary').fetchall() if x[0]!='chooser_id']
    c.execute('CREATE VIEW old AS SELECT * FROM '+scan(original))
    oldcols=[x[0] for x in c.execute('DESCRIBE old').fetchall()]
    require(all(x in oldcols for x in cols),'Acquisition summary schema changed')
    select=','.join(('s.' if x in cols else 'a.')+ident(x) for x in oldcols if x not in ('selected_controls','nested_1to1_available','exact_1to3_group'))
    c.execute('CREATE TABLE eligible AS SELECT '+select+' FROM old a JOIN chooser_summary s ON s.chooser_id=a.username_norm JOIN chooser_summary k ON k.chooser_id=a.matched_kind_chooser_id WHERE k.ever_kind_any_state AND s.match_cell=k.match_cell AND ((a.acquisition_role=\'kind\' AND s.ever_kind_any_state) OR (a.acquisition_role=\'control\' AND NOT s.ever_kind_any_state))')
    c.execute('''CREATE TABLE counted AS SELECT *,count(*) FILTER(WHERE acquisition_role='control') OVER(PARTITION BY matched_kind_chooser_id)::BIGINT selected_controls,
        bool_or(acquisition_role='control' AND control_slot=1) OVER(PARTITION BY matched_kind_chooser_id) nested_1to1_available
        FROM eligible''')
    n=copy(c,'SELECT *,selected_controls=3 exact_1to3_group FROM counted WHERE selected_controls>0 ORDER BY query_index',acquired)
    return c.execute('SELECT count(*) FROM old').fetchone()[0],n

def patron(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/patron'))
    from runner import run as producer
    from source import acquisition_planner_v100 as planner
    previous,status=producer.authenticate_wave3a(args.project)
    snapshot=producer.prior.authenticate_snapshot(args.project)
    original=previous/'matching/acquisition_users_private.parquet'
    acquired=out/'PRIVATE/acquisition_users_private.parquet'
    c=db(out/'PRIVATE/spill_summary',args.memory_gb,args.workers)
    try:
        planner.create_panel_view(c,[r['path'] for r in auth['month_records']])
        planner.build_chooser_summary(c)
        # Rebuild exposure summaries, preserve group roster and slots. Remove a
        # focal with no remaining kindness and any control that is no longer an
        # eligible never-granter in its focal's rebuilt exact matching cell.
        before,n=prepare_patron_roster(c,original,acquired)
        if args.variant=='included':require(n==before,'Included Patron roster changed')
        if args.variant=='excluded':
            bad=c.execute('SELECT count(*) FROM '+scan(acquired)+' WHERE lower(trim(username_norm)) IN ('+','.join(map(q,AUTHORS))+') OR lower(trim(matched_kind_chooser_id)) IN ('+','.join(map(q,AUTHORS))+')').fetchone()[0]
            require(bad==0,'Author survived Patron selection')
        flow=c.execute('SELECT acquisition_role,count(*) accounts FROM '+scan(acquired)+' GROUP BY ALL').fetchdf()
        table(out/'report/retained_acquisition',flow)
        write(out/'report/ACQUISITION_POLICY.json',{'before':before,'after':n,'removed':before-n,'new_profiles_queried':0,'replacement_matches':0,'fresh_exposure_summaries':True,'rule':'retain frozen group/slot membership only where the focal remains any-kind, the control remains never-kind, and fresh exact cells agree; require >=1 retained control'})
    finally:c.close()
    design=out/'PRIVATE/design'
    if design.exists() and not (design/'DESIGN_DONE.json').exists():design.rename(design.with_name('design.interrupted.'+str(time.time_ns())))
    design.mkdir(parents=True,exist_ok=True)
    ns=argparse.Namespace(threads=args.workers,memory_limit=f'{args.memory_gb}GB')
    receipt=design/'DESIGN_DONE.json'
    key=digest([auth['fingerprint'],record(acquired),record(snapshot)])
    if receipt.exists():
        z=read(receipt);require(z['key']==key,'Patron design key changed');verify(z['cache'])
    else:
        producer.build_design(design,ns,auth,acquired,snapshot,n)
        write(receipt,{'key':key,'cache':record(design/'chooser_design_features_private.parquet')})
    c=producer.common.connect_database(None,args.workers,f'{args.memory_gb}GB')
    try:
        qa,_,_=producer.models.outcome_qa(c,snapshot,fixture=False)
        frame=producer.load_frames(c,design/'chooser_design_features_private.parquet',snapshot)
    finally:c.close()
    require(len(frame)==n and frame.username_norm.nunique()==n,'Patron joined sample identity differs')
    support=read(design/'preoutcome_support_receipt.json')
    summary=producer.main_models(frame,out/'PRIVATE/models',key,out/'report',support)
    dates=producer.corrected_date_models(frame,out/'PRIVATE/models',key,out/'report')
    bounds=producer.missing_outcome_bounds(frame)
    write(out/'report/missing_outcome_bounds.json',bounds)
    if args.variant=='included':
        require((summary['primary_accounts'],summary['primary_kind_accounts'],summary['primary_control_accounts'])==(851131,212829,638302),'Included Patron primary flow fails to reproduce the manuscript')
    write(out/'report/PRIMARY_FLOW.json',summary)
    return {'primary':summary,'corrected_dates':dates,'opportunity_level_and_rematch_sensitivities':'NOT_RUN'}

def receipt_sql(core,paths,original,exposure_columns):
    query=core.recipient_panel_sql(paths,original,int(pd.Timestamp('2025-11-01',tz='UTC').timestamp()*1000))
    left='), exposure_ranked AS (';right='), future_labeled AS ('
    require(query.count(left)==query.count(right)==1,'Receipt producer CTE structure changed')
    before=query.split(left)[0];after=query.split(right)[1]
    exposure='SELECT '+','.join('o.'+ident(x) for x in exposure_columns)+' FROM frozen_receipt o SEMI JOIN panel p ON p.game_id=o.exposure_game_id'
    query=before+'), exposure AS ('+exposure+right+after
    needle='FROM read_parquet('+core.sql_literal(original)+')'
    require(query.count(needle)==1,'Receipt factual-history binding changed')
    return query.replace(needle,'FROM a3_facts')

def receipt(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/companion'))
    import incidents,sparse_fe
    core=module('author_receipt_core',ROOT/'vendor/companion/vendor/core/receipt_core.py')
    old=incidents.locate_receipt(args.project)
    reference=read(ROOT/'vendor/companion/authority/core_summary.json')
    require(sha(old)==reference['recipient_private_input_sha256'],'Frozen receipt checkpoint checksum changed')
    original_names=pq.ParquetFile(old).schema_arrow.names
    require('a1_90d_followup_eligible' in original_names,'Frozen exposure schema missing')
    exposure_columns=original_names[:original_names.index('a1_90d_followup_eligible')+1]
    require('exposure_game_id' in exposure_columns and 'recipient_user_id' in exposure_columns,'Frozen exposure identity missing')
    fresh=out/'PRIVATE/recipient_with_chronology_private.parquet'
    done=out/'PRIVATE/RECIPIENT_INPUT.json'
    key=digest([auth['fingerprint'],reference['recipient_private_input_sha256'],sha(__file__)])
    c=db(out/'PRIVATE/spill_receipt',args.memory_gb,args.workers)
    try:
        c.execute('CREATE VIEW frozen_receipt AS SELECT * FROM '+scan(old))
        c.execute('CREATE VIEW a3_facts AS SELECT *,recipient_user_id AS disconnected_user_id FROM frozen_receipt')
        if done.exists():
            r=read(done);require(r['key']==key,'Receipt input key changed');verify(r['output'])
        else:
            query=receipt_sql(core,[r['path'] for r in auth['month_records']],old,exposure_columns)
            # Rebuild all analytical receipt events, future choice outcomes,
            # recipient histories and leave-pair-out donor propensities.
            query='SELECT r.*,o.pre_games_30d,o.first_pair_utc_ms,o.first_ever_pair FROM ('+query+') r JOIN frozen_receipt o USING(cohort_row_id) ORDER BY r.cohort_row_id'
            with heartbeat('Rebuild receipt histories and subsequent choices'):n=copy(c,query,fresh)
            expected=c.execute('SELECT count(*) FROM frozen_receipt o SEMI JOIN '+scan([r['path'] for r in auth['month_records']])+' p ON p.game_id=o.exposure_game_id').fetchone()[0]
            require(n==expected,'Frozen exposure subset changed')
            write(done,{'key':key,'output':record(fresh),'rows':n,'frozen_exposure_ids_preserved':True,'all_factual_chronology_preserved':True,'no_replacement_exposures':True})
        counts=c.execute('SELECT count(*),count(DISTINCT cohort_row_id),sum(received_mercy::INTEGER),sum(exposure_claimed_win::INTEGER),sum(arm_eligible::INTEGER),sum((NOT arm_eligible)::INTEGER) FROM '+scan(fresh)).fetchone()
        require(counts[0]==counts[1],'Duplicate exposure identity')
        if args.variant=='excluded':
            bad=c.execute('SELECT count(*) FROM '+scan(fresh)+' s WHERE '+author_sql(('disconnected_username_norm','exposure_chooser_username_norm'))).fetchone()[0]
            require(bad==0,'Author survived receipt cohort exclusion')
    finally:c.close()
    t=pq.ParquetFile(fresh).read(columns=list(core.RECIPIENT_NUMERIC_COLUMNS),use_threads=False)
    data={n:core.arrow_column_numpy(t,n,np,pa) for n in core.RECIPIENT_NUMERIC_COLUMNS};del t
    ids=data['cohort_row_id'];require(len(ids)==counts[0] and (np.diff(ids)>0).all(),'Recipient row IDs must remain unique, sorted, original IDs')
    for name,n in zip(('EXPECTED_RECIPIENT_MERCY','EXPECTED_RECIPIENT_CLAIMED','EXPECTED_RECIPIENT_ARM_ELIGIBLE','EXPECTED_RECIPIENT_NONARM'),counts[2:]):setattr(core,name,int(n))
    support=core.common_support_weights(data)
    write(out/'report/common_support.json',{k:v for k,v in support.items() if k not in ('eligible','weights','cell_rows')})
    table(out/'report/common_support_cells',support['cell_rows'])
    with heartbeat('Matched receipt and reentry models'):results=core.estimate_recipient_analyses(data,support)
    # Original source reports any-grant as its unconditional companion; also fit
    # the manuscript's first-choice-with-no-reach-coded-zero outcome explicitly.
    data['first_choice_zero_coded']=np.where(data['reached_fair_chooser_within_90d'],data['first_subsequent_kind_draw'],0).astype(float)
    complete=data['first_ever_pair'].astype(bool)&data['arm_eligible'].astype(bool)&data['a1_90d_followup_eligible'].astype(bool)
    results['a1_models'].append(core.fit_recipient_outcome(data=data,support=support,outcome_name='first_choice_zero_coded',sample=complete,estimand='first_choice_zero_coded_90d',state_conditioned=False,binary_outcome=True))
    if args.variant=='included':
        baseline=next(x for x in results['a1_models'] if x['estimand']=='primary_total_path_conditional_choice')
        require(baseline['rows']==993762 and abs(baseline['coefficient_percentage_points']-.8816583609166886)<1e-6 and abs(baseline['standard_error_percentage_points']-.12240319188770558)<1e-6,'Included receipt model fails to reproduce baseline')
    with heartbeat('Refit receipt overlap weights'):
        overlap,overlap_receipt=core.estimate_overlap_sensitivities({'resume_config_sha256':key},out/'PRIVATE',data)
    results['overlap']=overlap
    for family,rows in results.items():
        table(out/'report'/family,[{k:v for k,v in x.items() if not isinstance(v,(dict,list,np.ndarray))} for x in rows])
        write(out/'report'/(family+'.json'),rows)
    # Exact-hour sensitivity from the completed companion producer.
    stamps=pq.ParquetFile(fresh).read(columns=['cohort_row_id','exposure_game_utc_ms','exposure_anchor_utc_ms'],use_threads=False)
    require(np.array_equal(stamps['cohort_row_id'].to_numpy(),ids),'Receipt timestamp alignment differs')
    start=stamps['exposure_game_utc_ms'].to_numpy();anchor=stamps['exposure_anchor_utc_ms'].to_numpy()
    complete=complete&support['eligible'];reached=data['reached_fair_chooser_within_90d'].astype(bool);hours=[]
    for name,mask,y in [('conditional_first_choice',complete&reached,data['first_subsequent_kind_draw']),('reach_90d',complete,reached.astype(float)),('first_choice_zero_coded',complete,data['first_choice_zero_coded'])]:
        ix=np.flatnonzero(mask);X,names=core.model_controls(data,ix,state_conditioned=False)
        groups=[data['exposure_cell_code'][ix],data['exposure_month_code'][ix]]
        modes=[('baseline',[]),('exposure_start_hour',[start[ix]//3600000]),('exposure_last_move_hour',[anchor[ix]//3600000])]
        if name=='conditional_first_choice':modes.append(('both_last_move_hours_post_exposure_sensitivity',[anchor[ix]//3600000,(anchor[ix]+data['first_subsequent_delta_ms'][ix])//3600000]))
        for mode,extra in modes:
            target=out/'PRIVATE/hour_models'/f'{name}_{mode}.json'
            if target.exists():r=read(target)
            else:
                sparse_fe.configure(out/'PRIVATE/hour_solvers'/f'{name}_{mode}',key)
                with heartbeat(name+' / '+mode):r=incidents.fit(np.asarray(y[ix],float),data['received_mercy'][ix].astype(float),X,support['weights'][ix],groups+extra,data['exposure_chooser_user_id'][ix])
                r.update(outcome=name,specification=mode);write(target,r)
            hours.append({k:v for k,v in r.items() if not isinstance(v,(dict,list))})
    table(out/'report/receipt_hours',hours)
    return {'families':list(results),'hour_models':len(hours),'frozen_exposures':int(counts[0]),'all_behavioral_histories_rebuilt':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--project',type=Path,required=True)
    p.add_argument('--variant',choices=['included','excluded'],required=True);p.add_argument('--stage',required=True)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--shards',type=int,default=256)
    p.add_argument('--session-root',type=Path);args=p.parse_args()
    auth=load_auth(args.run,args.variant);out=args.run/'PRIVATE/results'/args.variant/args.stage
    if args.stage in ['core','panel_robustness','rating_gap','nonparametric','controlled_reference']:result=wave(args,auth,out)
    else:
        (out/'PRIVATE').mkdir(parents=True,exist_ok=True);(out/'report').mkdir(exist_ok=True)
        result=globals()[args.stage](args,auth,out)
    guard_auth(auth)
    write(args.run/'PRIVATE/stage_receipts'/args.variant/(args.stage+'.json'),{'stage':args.stage,'variant':args.variant,'sample_fingerprint':auth['fingerprint'],'result':result})

if __name__=='__main__':main()
