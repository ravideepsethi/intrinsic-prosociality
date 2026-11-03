"""Six retained matched-receipt companions, using the completed corrected panel."""
import argparse,sys,shutil,gc,traceback
from pathlib import Path
from result_common import *
sys.path.insert(0,str(ROOT/'vendor_receipt/code'))
import util,history
from source import core,common
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from receipt_numerics import fit,conditional_censor_mask
from engagement import build_activity

SUPPORT_N=2296216
COMPLETE90_N=2112426
CONDITIONAL_N=994454

def load_receipt(path):
    cols=list(dict.fromkeys(['cohort_row_id','recipient_user_id','exposure_chooser_user_id','received_mercy',
        'exposure_claimed_win','arm_eligible','exposure_no_mating_draw','exposure_chooser_loss','first_ever_pair',
        'a1_90d_followup_eligible','exposure_cell_code','exposure_month_code',
        'reached_fair_chooser_within_90d','first_subsequent_kind_draw','first_subsequent_delta_ms',
        'recipient_next_disconnection_utc_ms','exposure_anchor_utc_ms']+list(core.EXPOSURE_CONTROLS)))
    t=pq.ParquetFile(path).read(columns=cols,use_threads=False)
    d={x:core.arrow_column_numpy(t,x,np,pa) for x in cols}
    require(np.array_equal(d['cohort_row_id'],np.arange(len(t))),'Corrected receipt IDs/order differ')
    require(np.array_equal(d['arm_eligible'],d['received_mercy']|d['exposure_claimed_win']),'Receipt-arm partition differs')
    require(not (d['received_mercy']&d['exposure_claimed_win']).any(),'Receipt arms overlap')
    for name,count in [('EXPECTED_RECIPIENT_MERCY',d['received_mercy'].sum()),('EXPECTED_RECIPIENT_CLAIMED',d['exposure_claimed_win'].sum()),
                       ('EXPECTED_RECIPIENT_ARM_ELIGIBLE',d['arm_eligible'].sum()),('EXPECTED_RECIPIENT_NONARM',(~d['arm_eligible']).sum())]:setattr(core,name,int(count))
    support=core.common_support_weights(d)
    return d,support

def run(a):
    parents=load(ROOT/'authority/PARENTS.json');rid=parents['receipt_run_id']
    parent=a.project/'derived/replication/mating_material_receipt_v100_PRIVATE'/rid[:16]
    require(load(parent/'_SUCCESS.json')['status']=='RECEIPT_COMPLETE_MORE_FAMILIES_PENDING','Completed corrected receipt source missing')
    require(sha(parent/'report/RESULTS.json')==parents['receipt_result_sha256'],'Corrected receipt summary changed')
    with heartbeat('Authenticating corrected matched-receipt inputs'):
        sources=[bind_success_file(parent,'PRIVATE/recipient/recipient_private.parquet',rid),
                 bind_success_file(parent,'report/models/conditional.json',rid)]
    path=Path(sources[0]['path']);expected=load(ROOT/'authority/receipt_RESULTS.json')['summary']['sample']
    require(pq.ParquetFile(path).metadata.num_rows==expected['all_fresh_exposures'],'Corrected receipt row count differs')
    fingerprint=key(dict(package=sha(ROOT/'SOURCE_SHA256SUMS.txt'),source=sources[0]['sha256']))
    state=a.project/'derived/replication/remaining_results_v100_PRIVATE'/fingerprint[:16]/'receipt'
    state.mkdir(parents=True,exist_ok=True);a.report.mkdir(parents=True,exist_ok=True)
    d,support=load_receipt(path)
    complete=support['eligible']&d['a1_90d_followup_eligible'].astype(bool)
    conditional=complete&d['reached_fair_chooser_within_90d'].astype(bool)
    require(int(support['eligible'].sum())==expected['common_support']==SUPPORT_N,'Support-cohort count differs')
    require(int(complete.sum())==expected['common_support_complete90']==COMPLETE90_N,'Complete-followup cohort differs')
    require(int(conditional.sum())==expected['complete90_reached']==CONDITIONAL_N,'Conditional receipt cohort differs')
    table_rows=[]
    def estimate(name,mask,y,binary=True,both_hours=False):
        ix=np.flatnonzero(mask);require(np.isfinite(y[ix]).all(),'Missing outcome in '+name)
        def build(folder):
            X,names=core.model_controls(d,ix,state_conditioned=False)
            groups=[d['exposure_cell_code'][ix],d['exposure_month_code'][ix]];hour=None
            if both_hours:
                anchor=d['exposure_anchor_utc_ms'][ix].astype(np.int64)
                delta=d['first_subsequent_delta_ms'][ix]
                require(np.isfinite(delta).all() and (delta>0).all(),'Invalid first-choice timestamp')
                hour=anchor//3600000;later=(anchor+delta.astype(np.int64))//3600000
                groups.extend([hour,later])
            with heartbeat('Matched companion '+name):
                r=fit(y[ix],d['received_mercy'][ix],X,names,support['weights'][ix],groups,
                      d['exposure_chooser_user_id'][ix],d['cohort_row_id'][ix],common,core,binary,hour)
            r['specification']=name
            r['fixed_effects']=['exposure cell','exposure month']+(['exposure last-move UTC hour','later-choice last-move UTC hour'] if both_hours else [])
            save(folder/'MODEL.json',r);return r
        loc,r=checkpoint(state/'models',name,key(dict(job=fingerprint,model=name)),build)
        shutil.copyfile(loc/'MODEL.json',a.report/(name+'.json'))
        log(f"{name}: {r['estimate']:.6f} ({r['se']:.6f}), N={r['rows']:,}")
        return r
    # Verify the new scalar influence calculation against a completed, same-row model.
    ref=estimate('reference_conditional_validation',conditional,d['first_subsequent_kind_draw'].astype(float))
    saved=load(sources[1]['path'])
    require(ref['sample_sha256']==saved['sample_sha256'],'Reference row hash differs')
    require(abs(ref['estimate']-saved['estimate'])<1e-6 and abs(ref['se']-saved['se'])<1e-6,'Reference fit does not reproduce the completed corrected model')
    save(a.report/'REFERENCE_CHECK.json',dict(status='PASSED',reference=sources[1],estimate_difference=ref['estimate']-saved['estimate'],se_difference=ref['se']-saved['se']))
    table_rows.append(estimate('conditional_exposure_and_later_choice_hours',conditional,d['first_subsequent_kind_draw'].astype(float),both_hours=True))
    censored=conditional_censor_mask(d['reached_fair_chooser_within_90d'],d['exposure_anchor_utc_ms'],
           d['first_subsequent_delta_ms'],d['recipient_next_disconnection_utc_ms'],complete)
    table_rows.append(estimate('conditional_censored_at_next_competitive_disconnection',censored,d['first_subsequent_kind_draw'].astype(float)))
    save(a.report/'CONDITIONAL_COUNTS.json',dict(complete90=int(complete.sum()),conditional=int(conditional.sum()),
        censored=int(censored.sum()),censoring_rule='Retain a reached first choice if no competitive disconnection is within 90 days, or if choice <= next disconnection; timestamp ties retained.',
        zero_coded_censored_primary='Existing 0.315 row is a separate outcome and is not replaced by this conditional estimate.'))
    with heartbeat('Preparing exact-exposure engagement outcomes'):
        loc,summary=checkpoint(state,'activity',key(dict(job=fingerprint,activity='exact_exposure_reuse_plus_missing_windows_v1')),
            lambda folder:build_activity(folder,state,path,d,support,a.project,a.workers,a.memory_gb,fingerprint,history,util))
    t=pq.ParquetFile(loc/'activity_PRIVATE.parquet').read();ids=t['cohort_row_id'].to_numpy().astype(np.int64)
    require(np.array_equal(ids,np.flatnonzero(support['eligible'])),'Engagement outcome IDs differ from support cohort')
    counts=t['games_within_30d'].to_numpy();first=t['first_next_game_utc_ms'].to_numpy();anchor=t['exposure_anchor_utc_ms'].to_numpy()
    require(np.array_equal(counts>0,first<np.iinfo(np.int64).max),'Engagement outcomes invalid')
    mask=support['eligible'];y=np.full(len(mask),np.nan);y[ids]=np.log1p(counts)
    table_rows.append(estimate('engagement_log1p_games_30d',mask,y,binary=False))
    for minutes in (10,30,60):
        y=np.full(len(mask),np.nan);y[ids]=(counts>0)&(first>anchor)&(first-anchor<=minutes*60000)
        table_rows.append(estimate(f'engagement_any_game_{minutes}m',mask,y))
    guard(sources)
    export=[]
    for r in table_rows:
        export.append({k:v for k,v in r.items() if not isinstance(v,(list,dict))})
    csv_save(a.report/'RECEIPT_COMPANIONS.csv',export)
    save(a.report/'ENGAGEMENT_CONSTRUCTION.json',summary)
    save(a.report/'INPUT_LINEAGE.json',dict(sources=sources,parent_run_id=rid,support_rows=SUPPORT_N,completed90_rows=COMPLETE90_N))
    save(a.report/'STATUS.json',dict(status='COMPLETE',models_reported=6,reference_models_verified=1,
        manuscript_modified=False,pdfs_modified=False,private_rows_exported=False,adjusted_p_values=False))

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--workers',type=int,default=8);p.add_argument('--memory-gb',type=float,default=8);a=p.parse_args()
    require(1<=a.workers<=10 and 2<=a.memory_gb<=32,'Invalid resource limits')
    block_network()
    try:run(a);return 0
    except Exception as e:
        save(a.report/'STATUS.json',dict(status='FAILED',error=type(e).__name__+': '+str(e)))
        (a.report/'ERROR.txt').write_text(traceback.format_exc());traceback.print_exc();return 1
if __name__=='__main__':raise SystemExit(main())
