"""C6 receipt/timeout models: fresh analytical events, unchanged all-game denominators."""
from remaining_common import *

def align_cache(path,ids,fields):
    t=pq.ParquetFile(path).read(columns=['cohort_row_id']+list(fields)).to_pandas()
    require(t.cohort_row_id.is_unique,'Duplicate C6 cache identity')
    ix=pd.Index(ids).get_indexer(t.cohort_row_id)
    require((ix>=0).all(),'C6 cache contains rows outside retained frozen cohort')
    out={'present':np.zeros(len(ids),bool)};out['present'][ix]=True
    for k in fields:
        out[k]=np.zeros(len(ids),np.int64);out[k][ix]=t[k].to_numpy(np.int64)
    return out

def run_stage(args,auth,out):
    source=ROOT/'vendor/wave2b2b1/source'
    sys.path[:0]=[str(source/'campaign'),str(source/'engines')]
    import campaign1_c6_c10_v100 as c6
    ply=module('author_c6_ply',ROOT/'vendor/wave2b2b1/runner/c6_ply_retrofit.py')
    core=module('author_receipt_core',ROOT/'vendor/companion/vendor/core/receipt_core.py')
    previous=stage_output(args.parent,args.variant,'receipt')
    fresh=previous/'PRIVATE/recipient_with_chronology_private.parquet'
    verified=read(previous/'PRIVATE/RECIPIENT_INPUT.json');verify(verified['output'])
    cols={'cohort_row_id','recipient_user_id','exposure_chooser_user_id','received_mercy','exposure_claimed_win','arm_eligible','exposure_no_mating_draw','exposure_chooser_loss','first_ever_pair','a1_90d_followup_eligible','exposure_cell_code','exposure_month_code','exposure_anchor_utc_ms','encouragement_prior_pair_excluded_n','encouragement_pair_excluded_propensity',*core.EXPOSURE_CONTROLS}
    t=pq.ParquetFile(fresh).read(columns=sorted(cols),use_threads=False)
    data={n:c6.common.arrow_numpy(t,n,nullable_float=n in {'encouragement_pair_excluded_propensity',*core.EXPOSURE_CONTROLS}) for n in cols};del t
    ids=data['cohort_row_id'];require((np.diff(ids)>0).all(),'Frozen recipient identity order differs')
    for name,key in [('EXPECTED_RECIPIENT_MERCY','received_mercy'),('EXPECTED_RECIPIENT_CLAIMED','exposure_claimed_win'),('EXPECTED_RECIPIENT_ARM_ELIGIBLE','arm_eligible')]:setattr(core,name,int(data[key].sum()))
    core.EXPECTED_RECIPIENT_NONARM=int((~data['arm_eligible'].astype(bool)).sum())
    # Original implementation indexed dense row IDs. Preserve original IDs and
    # align by identity after exclusion instead of renumbering/replacing rows.
    c6._load_recipient_minimal=lambda recipient,core: data.copy()
    c6._expand_cache=lambda path,total_rows,fields:align_cache(path,ids,fields)
    key=digest([auth['fingerprint'],record(fresh),sha(__file__)])
    state=out/'PRIVATE/c6';state.mkdir(parents=True,exist_ok=True)
    cohort,cr=c6.build_c6_preoutcome_index(recipient=fresh,core=core,state=state,config_sha256=key)
    oldbase=args.project/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b2b1'
    old=unique_path(oldbase.glob('**/c6_rated_games_90d_private.parquet'),'C6 factual denominator cache')
    rr=read(old.with_name('c6_rated_games_90d_receipt.json'))
    require(rr['output_sha256']==sha(old),'C6 factual denominator changed')
    denominator=state/'c6_rated_games_90d_private.parquet'
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    try:
        missing=c.execute('SELECT count(*) FROM '+scan(cohort)+' a ANTI JOIN '+scan(old)+' b USING(cohort_row_id)').fetchone()[0]
        require(missing==0,'A newly eligible C6 cohort row lacks a factual denominator; cannot code missing as zero')
        copy(c,'SELECT b.* FROM '+scan(old)+' b SEMI JOIN '+scan(cohort)+' a USING(cohort_row_id) ORDER BY cohort_row_id',denominator)
    finally:c.close()
    paths=[Path(r['path']) for r in auth['month_records']]
    events,er=c6.build_c6_event_cache(cohort_index=cohort,stage07_paths=paths,state=state,threads=args.workers,memory_limit=f'{args.memory_gb-2}GB',config_sha256=key)
    gate=c6.freeze_c6_gate(cohort_receipt=cr,event_receipt=er,state=state,config_sha256=key)
    require(gate['gate_pass'],'C6 frozen support gate no longer passes')
    result=c6.estimate_c6(recipient=fresh,core=core,denominator_cache=denominator,event_cache=events,gate=gate)
    write(out/'report/c6_models.json',result)
    table(out/'report/c6_models',[{k:v for k,v in row.items() if not isinstance(v,(dict,list))} for row in result['models']])
    late=ply.execute(recipient=fresh,stage_paths=paths,c6_state=state,state=out/'PRIVATE/ply',public_stage=out/'report/ply',core=core,c6=c6,campaign_common=c6.common,config_sha256=key,threads=args.workers,memory_limit=f'{args.memory_gb-2}GB')
    if args.variant=='included':
        x=result['primary'];require(abs(x['coefficient']-(-1.593))<.000501,'C6 primary does not reproduce printed baseline')
    return dict(status='C6_AND_PLY_REFITTED',rows=len(ids),new_chronology_scans=0,behavioral_events_rebuilt=True,ply=late)
