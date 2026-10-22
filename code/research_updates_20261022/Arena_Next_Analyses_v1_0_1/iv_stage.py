"""Arena exposure adapter for the repository's chooser-history IV and A1 engines.

Historical chooser scores retain all original sources. Subsequent opportunities
are selected across all sources FIRST. Arena outcomes are joint events, with
reach reported separately; no intervening pool opportunity is silently skipped.
"""
from __future__ import annotations
import csv, gc, shutil
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from next_common import *

sys.path.insert(0,str(ROOT/'source/iv'))
import run_rebuild as upstream
import local_io as io
import rebuild_logic as logic
import iv_numerics as num
import iv_models as models
from preliminary_core import DAY, MONTHS, STARTS, PANEL_END, SPEEDS

def connection(temp, memory=2, threads=1):
    return db(temp,str(memory)+'GB',threads)
io.conn=connection

def authenticate_history(project, audit_path=None):
    audit={'status':'RUNNING','phase':'initialization','config_checks':{},
           'authority_digests_changed':False,'historical_config_values_exported':False}
    try:
        result=_authenticate_history(project,audit)
        audit.update(status='COMPLETE',phase='complete',projection_files=len(result['projection']),
                     reference_files=len(result['deltas']),chronology_files=len(result['chron']))
        return result
    except Exception as e:
        audit.update(status='FAILED',error_type=type(e).__name__,error=str(e))
        raise
    finally:
        if audit_path is not None:js(audit_path,audit)

def _authenticate_history(project,audit):
    """Reuse authenticated all-source projections, not the pool comparison cohort."""
    a=read(ROOT/'source/iv/evidence/prior_authority.json');snapshots=[]
    previous=project/'derived/replication/comparison_tests_v110_PRIVATE'/a['comparison_run']
    audit['phase']='comparison_completion_and_configuration'
    snapshots.append(io.checked(previous/'_SUCCESS.json'))
    done=read(previous/'_SUCCESS.json')
    require(done.get('status')=='CHOOSER_COMPARISON_TESTS_COMPLETE' and
      done.get('config_sha256')==a['comparison_config_sha256'] and done.get('report_sha256')==a['comparison_report_sha256'],
      'The verified all-source projection lineage is unavailable')
    from history_auth import config_hash_audit
    snapshots.append(io.checked(previous/'config.json'))
    check=config_hash_audit(read(previous/'config.json'),a['comparison_config_sha256'])
    audit['config_checks']['comparison']=check
    require(check['matched'],'Historical projection configuration differs from the fixed authority digest; neither upstream JSON serialization matches')
    log('Historical comparison configuration authenticated: '+', '.join(check['matched_serializations']))
    audit['phase']='comparison_projection_lineage'
    snapshots.append(io.checked(previous/'lineage_PRIVATE.json',a['comparison_lineage_sha256']))
    line=read(previous/'lineage_PRIVATE.json')
    audit['phase']='iv_completion_and_configuration'
    iv=project/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/a['iv_run']
    snapshots.append(io.checked(iv/'_SUCCESS.json'));ivdone=read(iv/'_SUCCESS.json')
    require(ivdone.get('config_sha256')==a['iv_config_sha256'] and ivdone.get('report_zip_sha256')==a['iv_report_sha256'],
      'Verified expanding-reference history is unavailable')
    snapshots.append(io.checked(iv/'config.json'))
    check=config_hash_audit(read(iv/'config.json'),a['iv_config_sha256'])
    audit['config_checks']['iv_pilot']=check
    require(check['matched'],'Historical IV configuration differs from the fixed authority digest; neither upstream JSON serialization matches')
    log('Historical IV configuration authenticated: '+', '.join(check['matched_serializations']))
    projection=[];deltas=[]
    with heartbeat('Authenticating full historical score inputs'):
        audit['phase']='projection_file_hashes'
        for shard,parts in enumerate(line['projections']):
            for r in parts:
                p=upstream.relocate(project,r['path']);snapshots.append(io.checked(p,r['sha256'],r['bytes']))
                snapshots.append(io.checked(p.parent/'_COMPLETE.json',r['receipt_sha256']))
                projection.append(dict(r,path=str(p),shard=shard))
        audit['phase']='reference_delta_file_hashes'
        for month in MONTHS:
            folder=iv/'projection'/('month='+month);r=read(folder/'_COMPLETE.json')
            snapshots.append(io.checked(folder/'_COMPLETE.json'))
            found=[x for x in r['files'] if x['path']=='reference_deltas.npz']
            require(len(found)==1 and r['config_sha256']==a['iv_config_sha256'],'Historical reference checkpoint changed')
            p=folder/'reference_deltas.npz';snapshots.append(io.checked(p,found[0]['sha256'],found[0]['bytes']));deltas.append(str(p))
    require({(x['month'],x['shard']) for x in projection}=={(m,s) for m in MONTHS for s in range(16)},'Incomplete score-history grid')
    require(sum(x['rows'] for x in projection)==47587020,'Full score history has a different population')
    audit['phase']='original_panel_and_chronology_manifest'
    snapshots.append(io.checked(project/'derived/replication/analysis_panel_24m_sf100k/_SUCCESS.json',a['stage07_success_sha256']))
    manifest=project/upstream.CHRON_MANIFEST;snapshots.append(io.checked(manifest,upstream.CHRON_SHA))
    with manifest.open() as f:chron=list(csv.DictReader(f,delimiter='\t'))
    require(len(chron)==852 and sum(int(x['rows']) for x in chron)==7763847245,'Canonical chronology coverage changed')
    with heartbeat('Checking canonical chronology metadata'):
        audit['phase']='chronology_file_metadata'
        for k,r in enumerate(chron):
            p=upstream.relocate(project,r['path']);pf=pq.ParquetFile(p)
            require(int(r['file_index'])==k and p.stat().st_size==int(r['bytes']) and pf.metadata.num_rows==int(r['rows'])
              and pf.metadata.num_row_groups==int(r['row_groups']),'Chronology metadata changed: '+str(p))
            require({'utc_ms','white_id','black_id','game_id'}<=set(pf.schema_arrow.names),'Canonical chronology schema changed')
            r.update(path=str(p),signature=io.sig(p))
    return {'projection':projection,'deltas':deltas,'chron':chron,'snapshots':snapshots,
      'chronology_integrity':'Authenticated original manifest, byte size, row count, row groups and pre/post stat signatures; no claim of full-content historical hashes.',
      'comparison_ordinary_pool_games_used_as_arena_controls':False}

def exposure_query(panels):
    original=logic.exposure_sql(parq(panels))
    require(original.count('AND NOT tournament_like_event')==1,'Original exposure selector changed')
    # Arena identity comes from the authenticated source/adjacency join. No event-name reclassification.
    first=original.replace('AND NOT tournament_like_event','')
    return f'''WITH first AS ({first}) SELECT f.*,
      p.timeout_chooser_win AS exposure_claimed_win,
      p.chooser_draw_payoff_v2 AS exposure_draw_payoff,
      p.chooser_win_premium_v2 AS exposure_win_premium,
      p.material_advantage_chooser AS exposure_material_advantage
      FROM first f JOIN {parq(panels)} p USING(game_id) ORDER BY target_row'''

def chronology_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    r=job['input'];path=Path(r['path']);require(io.sig(path)==r['signature'],'Chronology input changed before scan')
    def build(tmp):
        t=io.read(job['targets'],['target_row','recipient_id','chooser_id','archive_start_ms'])
        ids=io.arr(t,'recipient_id').astype(np.int64);st=io.arr(t,'archive_start_ms').astype(np.int64)
        require(np.all(np.diff(ids)>0),'First-exposure recipients are not uniquely sorted')
        keys,inv=np.unique(logic.pair_keys(ids,io.arr(t,'chooser_id')),return_inverse=True)
        pre=np.zeros(len(t),np.int64);mins=np.full(len(keys),np.iinfo(np.int64).max,np.int64);nr=0
        for batch in pq.ParquetFile(path).iter_batches(columns=['utc_ms','white_id','black_id'],batch_size=262144,use_threads=False):
            tab=pa.Table.from_batches([batch]);arr=[tab[col].fill_null(-1).to_numpy().astype(np.int64) for col in ['utc_ms','white_id','black_id']]
            logic.chronology_accumulate(*arr,ids,st,keys,pre,mins);nr+=len(tab)
        require(nr==int(r['rows']) and io.sig(path)==r['signature'],'Chronology scan lost rows or input changed')
        ix=np.flatnonzero(pre>0);io.table(tmp/'volume.parquet',pa.table({'target_row':ix,'pre_games_30d':pre[ix]}))
        values=mins[inv];ix=np.flatnonzero(values<np.iinfo(np.int64).max)
        io.table(tmp/'pairs.parquet',pa.table({'target_row':ix,'first_pair_start_ms':values[ix]}))
        return {'scanned_rows':nr,'input_signature':r['signature']}
    dest,receipt=io.stage(job['out'],job['conf'],build)
    require(receipt['input_signature']==r['signature'],'Chronology changed since its checkpoint')
    return str(dest)

def build_cohort(state, conf, dirs, memory):
    def build(tmp):
        c=connection(tmp/'spill',memory)
        try:
            p=parq([Path(d)/'pairs.parquet' for d in dirs]);v=parq([Path(d)/'volume.parquet' for d in dirs])
            query=f'''SELECT f.*,p.first_pair_start_ms,coalesce(v.pre_games_30d,0) AS pre_games_30d
              FROM {parq(state/'targets/first_exposures.parquet')} f
              LEFT JOIN (SELECT target_row,min(first_pair_start_ms) AS first_pair_start_ms FROM {p} GROUP BY 1) p USING(target_row)
              LEFT JOIN (SELECT target_row,sum(pre_games_30d)::BIGINT AS pre_games_30d FROM {v} GROUP BY 1) v USING(target_row)
              ORDER BY target_row'''
            io.copy(c,query,tmp/'first_exposures_with_history.parquet')
            t=io.read(tmp/'first_exposures_with_history.parquet');a={n:io.arr(t,n) for n in t.column_names};ft=a['first_pair_start_ms']
            require(np.isfinite(ft).all() and np.all(ft<=a['archive_start_ms']),'Canonical history did not recover every exposure pair')
            clock=np.isfinite(a['anchor_ms'])&(a['anchor_ms']>=a['archive_start_ms'])
            mask=logic.primary_cohort_mask(a,ft)&clock
            keep=t.filter(pa.array(mask));keep=keep.append_column('pilot_row',pa.array(np.arange(len(keep),dtype=np.int64)))
            keep=keep.append_column('speed_code',pa.array([SPEEDS[x] for x in keep['speed'].to_pylist()],type=pa.int8()))
            io.table(tmp/'cohort.parquet',keep)
            cut=np.ones(len(t),bool);flow=[]
            for label,m in [('first_competitive_screened_arena_exposure',cut.copy()),('grant_or_claim_arm',a['arm_eligible'].astype(bool)),
              ('real_time',np.isin(a['speed'],list(SPEEDS))&(a['tc_base_s']>0)),('first_observed_pair',ft==a['archive_start_ms']),
              ('valid_lastMoveAt_proxy',clock),('complete_90_days',a['anchor_ms']+90*DAY<PANEL_END)]:
                cut &= m;flow.append({'step':label,'rows':int(cut.sum()),'receipts':int(a['received'][cut].sum())})
            js(tmp/'cohort_flow.json',flow)
            return {'cohort_rows':len(keep),'receipts':int(io.arr(keep,'received').sum())}
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return io.stage(state/'cohort',conf,build)

def prepare_scores(sample, history, state, conf, memory):
    def build(tmp):
        t=io.read(state/'cohort/cohort.parquet')
        query=pa.table({'target_row':t['pilot_row'],'sample_row':t['pilot_row'],'game_id':t['game_id'],
          'recipient_id':t['recipient_id'],'opponent_id':t['chooser_id'],'archive_start_ms':t['archive_start_ms'],
          'anchor_ms':t['anchor_ms'],'month_code':t['month_code']})
        for role,col in [('scores','opponent_id'),('outcomes','recipient_id')]:
            shard=num.user_hash(io.arr(query,col))%np.uint64(16)
            for s in range(16):io.table(tmp/f'{role}_{s:02d}.parquet',query.filter(pa.array(shard==s)))
        rn=np.zeros((2,25,4,4,500),np.int64);rs=np.zeros_like(rn)
        for p in history['deltas']:
            with np.load(p,allow_pickle=False) as z:rn+=z['n'];rs+=z['s']
        np.save(tmp/'reference.npy',num.expanding_reference(rn[:,:24],rs[:,:24]),allow_pickle=False)
        c=connection(tmp/'spill',memory)
        try:io.copy(c,'SELECT game_id,chooser_user_id AS chooser FROM '+parq(sample['panels']),tmp/'arena_keys.parquet')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        return {'queries':len(t),'historical_reference_population':'All 47,587,020 original opportunities, all sources'}
    return io.stage(state/'score_inputs',conf,build)

def select_next(h, q, arena_ids):
    out=logic.fresh_outcomes(h,q,np.ones(len(h['j']),bool))
    arena=out['reached']&np.isin(out['outcome_gid'],arena_ids)
    out['next_arena_reached']=arena;out['next_arena_y']=arena&out['y']
    out['next_elsewhere_reached']=out['reached']&~arena
    return out

def score_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def build(tmp):
        ht=pa.concat_tables([io.read(p) for p in job['parts']]);h={n:io.arr(ht,n) for n in ht.column_names};del ht
        require(all(len(x)==8 for x in h['gid']),'Nonstandard history game identifier')
        h['gid']=h['gid'].astype('U8')
        c=connection(tmp/'spill',1)
        try:
            c.register('h',pa.table({'gid':h['gid'],'chooser':h['j']}))
            ids=c.execute('SELECT a.game_id FROM '+parq(job['keys'])+' a SEMI JOIN h ON a.game_id=h.gid AND a.chooser=h.chooser').fetchnumpy()['game_id']
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        qt=io.read(job['outcomes']);q={n:io.arr(qt,n) for n in qt.column_names}
        out=select_next(h,q,ids);out['target_row']=out.pop('sample_row');io.table(tmp/'outcomes.parquet',pa.table(out))
        qt=io.read(job['scores']);q={n:io.arr(qt,n) for n in qt.column_names};ref=np.load(job['reference'],allow_pickle=False)
        use=h['arm'];hj,hi,ht,hy,hc=(h[n][use] for n in ['j','i','t','y','cell']);result={'target_row':q['target_row']}
        for l,lag in enumerate([7,30]):
            a={n:np.full(len(qt),np.nan) for n in ['raw','adjusted','expected']}
            a.update({n:np.zeros(len(qt),np.int64) for n in ['n','counterparts','pair_removed']})
            for m in np.unique(q['month_code']):
                ix=np.flatnonzero(q['month_code']==m)
                score=num.score_month(hj,hi,ht,hy,hc,q['opponent_id'][ix],q['recipient_id'][ix],int(STARTS[int(m)]-lag*DAY),ref[l,int(m)],4)
                for n in a:a[n][ix]=score[n]
            for n,x in a.items():result[f'{n}_{lag}d']=x
            result[f'shrunken_adjusted_{lag}d']=a['adjusted']*a['n']/(a['n']+20.)
        io.table(tmp/'scores.parquet',pa.table(result))
        iv=io.read(job['cohort'],['pilot_row','recipient_id','archive_start_ms']);ids=io.arr(iv,'recipient_id');order=np.argsort(ids)
        pos=num.lookup(ids[order],h['i']);found=pos>=0;row=order[np.maximum(pos,0)];end=io.arr(iv,'archive_start_ms')[row]-7*DAY
        before=found&(h['t']<end)&(h['t']>=end-90*DAY)
        nr=np.bincount(row[before],minlength=len(iv));nk=np.bincount(row[before],weights=h['y'][before],minlength=len(iv)).astype(np.int64)
        ix=np.flatnonzero(nr);io.table(tmp/'prior_receipts.parquet',pa.table({'pilot_row':ix,'prior_disconnects':nr[ix],'prior_receipts':nk[ix]}))
        return {'history_rows':len(h['j']),'score_queries':len(qt),'outcome_queries':len(out['target_row'])}
    dest,_=io.stage(job['out'],job['conf'],build);return str(dest)

def assemble(state, conf, dirs):
    def build(tmp):
        t=io.read(state/'cohort/cohort.parquet');n=len(t)
        for family in ['scores','outcomes']:
            a=pa.concat_tables([io.read(Path(d)/(family+'.parquet')) for d in dirs]);a=a.take(pa.array(np.argsort(io.arr(a,'target_row'))))
            require(np.array_equal(io.arr(a,'target_row'),np.arange(n)),'Lost or duplicated score/outcome query')
            for name in a.column_names:
                if name in ['target_row','prior_disconnects','prior_receipts']:continue
                target={'y':'all_source_next_y','reached':'all_source_next_reached',
                  'next_arena_y':'other_started_after_y','next_arena_reached':'other_started_after_reached'}.get(name,name)
                t=t.append_column(target,a[name])
        pre=np.zeros((n,2),np.int64)
        for d in dirs:
            r=io.read(Path(d)/'prior_receipts.parquet');ix=io.arr(r,'pilot_row')
            for k,col in enumerate(['prior_disconnects','prior_receipts']):pre[ix,k]+=io.arr(r,col)
        for k,col in enumerate(['prior_disconnects','prior_receipts']):t=t.append_column(col,pa.array(pre[:,k]))
        require(io.arr(t,'complete90').all(),'Incomplete followup was coded as zero')
        io.table(tmp/'iv.parquet',t);return {'rows':n}
    return io.stage(state/'analysis',conf,build)

def receipt_models(state, public, args):
    """Use the original A1 weighting and clustered estimator on a documented arena adaptation."""
    from episodes_stage import engine
    mod=engine();t=io.read(state/'analysis/iv.parquet');a={n:io.arr(t,n) for n in t.column_names};n=len(t)
    # Same frozen evaluation/payoff/rating-gap/speed cells as A1. Outcomes choose the first all-source opportunity.
    c=connection(state/'receipt_spill',int(args.memory[:-2]),args.threads)
    try:
        cell_sql=f'''SELECT target_row, (({mod.eval_band_sql('exposure_eval_cp')})*3*8*6
          +({mod.payoff_class_sql('exposure_draw_payoff')})*8*6
          +({mod.gap_band_sql('exposure_chooser_elo-exposure_recipient_elo')})*6
          +({mod.speed_code_sql('speed')}))::INTEGER AS cell FROM {parq(state/'analysis/iv.parquet')} ORDER BY pilot_row'''
        cells=c.execute(cell_sql).fetchnumpy()['cell']
    finally:c.close()
    d={k:v for k,v in a.items() if k.startswith('exposure_')}
    d.update(cohort_row_id=a['pilot_row'],recipient_user_id=a['recipient_id'],exposure_chooser_user_id=a['chooser_id'],
      received_mercy=a['received'],exposure_claimed_win=~a['received'],arm_eligible=np.ones(n,bool),
      first_ever_pair=np.ones(n,bool),exposure_no_mating_draw=np.zeros(n,bool),exposure_chooser_loss=np.zeros(n,bool),
      exposure_cell_code=cells,exposure_month_code=a['month_code'],exposure_tc_base_s=a['tc_base_s'],exposure_tc_inc_s=a['tc_inc_s'],
      arena_joint_kind=a['other_started_after_y'],arena_next_reach=a['other_started_after_reached'],
      all_source_joint_kind=a['all_source_next_y'],all_source_next_reach=a['all_source_next_reached'])
    for key,val in {'EXPECTED_RECIPIENT_MERCY':int(a['received'].sum()),'EXPECTED_RECIPIENT_CLAIMED':int((~a['received']).sum()),
      'EXPECTED_RECIPIENT_ARM_ELIGIBLE':n,'EXPECTED_RECIPIENT_NONARM':0}.items():setattr(mod,key,val)
    # Report the retention gate even if it fails; do not silently relax it for arenas.
    valid=cells>=0;tc=np.bincount(cells[valid&a['received']],minlength=1152);cc=np.bincount(cells[valid&~a['received']],minlength=1152)
    ok=(tc>=5)&(cc>=20);retained=int(tc[ok].sum());den=int(a['received'][valid].sum());retention=retained/den if den else 0.
    gate={'treated_retention':retention,'required_retention':0.9,'retained_treated':retained,'first_pair_complete90_treated':den,
      'eligible_cells':int(ok.sum()),'count_rule':'at least 5 grants and 20 claims per frozen A1 exposure cell',
      'adaptation':'First competitive arena event ranked before cuts; complete 90-day realtime first-pair cohort. Different risk set from old all-source A1.'}
    js(public/'receipt_SUPPORT.json',gate)
    if retention<0.9:
        js(public/'receipt_RESULTS.json',{'status':'UNSUPPORTED_COMMON_SUPPORT_RETENTION','gate':gate})
        return {'status':'UNSUPPORTED_COMMON_SUPPORT_RETENTION','treated_retention':retention}
    support=mod.common_support_weights(d);out=[]
    for outcome,conditional in [('arena_joint_kind',False),('arena_next_reach',False),('arena_joint_kind',True),
                               ('all_source_joint_kind',False),('all_source_next_reach',False)]:
        mask=a['other_started_after_reached'] if conditional else np.ones(n,bool)
        label='conditional_arena_choice_SELECTION_CAVEAT' if conditional else outcome
        try:
            r=mod.fit_recipient_outcome(data=d,support=support,outcome_name=outcome,sample=mask,
              estimand=label,state_conditioned=False,binary_outcome=True)
            r['arena_adaptation']=True;out.append(r)
        except RuntimeError as e:
            if not any(x in str(e) for x in ['Insufficient support for recipient outcome:', 'Model matrix is rank deficient:']):raise
            out.append({'outcome':outcome,'status':'UNSUPPORTED','reason':str(e)})
    js(public/'receipt_RESULTS.json',out);csvout(public/'receipt_estimates.csv',out)
    return {'status':'COMPLETE','models':len(out),'treated_retention':retention}

def run(sample, root, args, contract):
    state=Path(root)/'private/receipt_iv';public=Path(root)/'public/receipt_iv'
    state.mkdir(parents=True,exist_ok=True);public.mkdir(parents=True,exist_ok=True)
    history=authenticate_history(args.project,public/'HISTORY_AUTHENTICATION.json')
    # Bind resumed chronology checkpoints to the actual currently observed signatures.
    signature=fingerprint({'parent':contract,'history':history})
    js(state/'HISTORY_INPUTS.json',history)
    js(public/'HISTORY_SCOPE.json',{'historical_opportunities':47587020,'chronology_rows':7763847245,
      'chronology_files':852,'history_signature':signature,'integrity':history['chronology_integrity']})
    memory=int(args.memory[:-2])
    def targets(tmp):
        c=connection(tmp/'spill',memory,args.threads)
        try:n=io.copy(c,exposure_query(sample['panels']),tmp/'first_exposures.parquet')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        return {'first_arena_exposure_recipients':n,'ranked_before_arm_and_followup_cuts':True}
    io.stage(state/'targets',signature,targets)
    jobs=[{'input':r,'targets':str(state/'targets/first_exposures.parquet'),'out':str(state/'chronology'/f'{k:04d}'),'conf':signature}
          for k,r in enumerate(history['chron'])]
    log('Receipt/IV: one scan of 7.76 billion chronology rows; each file has its own resume checkpoint.')
    dirs=io.mapped(chronology_job,jobs,min(args.workers,4),'Arena chronology')
    _,cohort=build_cohort(state,signature,dirs,memory)
    shutil.copy2(state/'cohort/cohort_flow.json',public/'cohort_flow.json')
    if cohort['cohort_rows']==0:return {'status':'UNSUPPORTED','reason':'No eligible first-pair arena receipt cohort'}
    prepare_scores(sample,history,state,signature,memory)
    jobs=[]
    for s in range(16):
        jobs.append({'parts':[r['path'] for r in history['projection'] if r['shard']==s],
          'keys':str(state/'score_inputs/arena_keys.parquet'),'outcomes':str(state/'score_inputs'/f'outcomes_{s:02d}.parquet'),
          'scores':str(state/'score_inputs'/f'scores_{s:02d}.parquet'),'reference':str(state/'score_inputs/reference.npy'),
          'cohort':str(state/'cohort/cohort.parquet'),'out':str(state/'scores'/f'{s:02d}'),'conf':signature})
    scored=io.mapped(score_job,jobs,min(args.workers,3),'Arena historical scores')
    assemble(state,signature,scored)
    receipt=receipt_models(state,public,args)
    result=upstream.estimate_iv(state,signature)
    for name,value in result.items():
        js(public/(name+'.json'),value)
        if isinstance(value,list) and value and isinstance(value[0],dict):csvout(public/(name+'.csv'),value)
    t=io.read(state/'analysis/iv.parquet');d={n:io.arr(t,n) for n in t.column_names}
    extra={'name':'arena_exposure_next_opportunity_any_source_SENSITIVITY','lag':7,'floor':5,'score':'adjusted',
      'outcome':'all_source_next_y','reach':'all_source_next_reached'}
    rows,_,_=models.estimate_spec(d,extra);csvout(public/'all_source_outcome_sensitivity.csv',rows)
    flow=[]
    for received in [False,True]:
        ix=d['received']==received
        flow.append({'received':received,'recipients':int(ix.sum()),'next_opportunity_any_source':int(d['all_source_next_reached'][ix].sum()),
          'next_opportunity_screened_arena':int(d['other_started_after_reached'][ix].sum()),'next_arena_kind_grant':int(d['other_started_after_y'][ix].sum()),
          'next_opportunity_elsewhere':int(d['next_elsewhere_reached'][ix].sum())})
    csvout(public/'next_opportunity_flow.csv',flow)
    js(public/'ESTIMANDS.json',{'primary_iv_outcome':'First subsequent competitive different-opponent opportunity starts after exposure lastMoveAt, within 90 days, and is both screened arena and a kind grant.',
      'unconditional_joint_event':True,'next_pool_opportunity_skipped':False,'reach_model_reported':True,
      'all_source_outcome_sensitivity':True,'conditional_arena_choice_has_post_exposure_selection':True,
      'lastMoveAt_is_proxy_not_certified_game_end':True,'causal_identification_certified':False,
      'ordinary_game_arena_comparison_available':False,'ordinary_pool_controls_substituted':False,
      'scope_limit':'Arena ordinary-game comparison and the full Stage10 A3/second-wave dynamics are not part of this runner.'})
    for s in history['snapshots']:require(io.sig(s['path'])==s['signature'],'Historical input changed during analyses')
    for r in history['chron']:require(io.sig(r['path'])==r['signature'],'Chronology changed during analyses')
    return {'status':'COMPLETE','cohort_rows':len(t),'receipt':receipt,'iv_specifications':11,'arena_ordinary_game_comparison':'NOT_AVAILABLE'}
