from util import *
from checkpoints import stage
from panel import build_exposures,build_outcomes
from history import seed_pairs,reconstruct_pairs,join_pairs,guard_catalog
from estimation import execute_models
import pyarrow.parquet as pq

def execute(auth,old,run,key,workers,memory,project):
    state=run/'PRIVATE';timing={};started=time.monotonic()
    with heartbeat('Selecting each recipient’s first eligible material-restricted exposure'):
        exposures,exposure_summary=stage(state,'exposures',key,lambda d:build_exposures(d,auth,workers,memory))
    timing['exposure_selection']=time.monotonic()-started;started=time.monotonic()
    with heartbeat('Rebuilding later competitive choices and censoring events'):
        outcomes,outcome_summary=stage(state,'outcomes',key,lambda d:build_outcomes(d,auth,exposures/'exposures_private.parquet',workers,memory))
    require(outcome_summary['candidates']==exposure_summary['candidates'],'Exposure and outcome counts differ')
    timing['outcomes']=time.monotonic()-started;started=time.monotonic()
    seeds,seed_summary=stage(state,'pair_seeds',key,lambda d:seed_pairs(d,exposures/'exposures_private.parquet',old,workers,memory))
    def history_build(folder):
        pairs,summary,catalog=reconstruct_pairs(state,seeds/'pairs_private.parquet',project,key,workers)
        pairs.to_parquet(folder/'pairs_private.parquet',index=False)
        save(folder/'catalog_private.json',catalog);save(folder/'history_summary.json',summary)
        return {k:v for k,v in summary.items() if k!='files'}
    histories,history_summary=stage(state,'pair_history',key,history_build)
    guard_catalog(read(histories/'catalog_private.json'))
    history_full=read(histories/'history_summary.json')
    save(run/'report/HISTORY_RECONSTRUCTION.json',history_full)
    timing['first_pair_history']=time.monotonic()-started;started=time.monotonic()
    pairs=pq.read_table(histories/'pairs_private.parquet').to_pandas()
    recipient,recipient_summary=stage(state,'recipient',key,lambda d:join_pairs(d,outcomes/'outcomes_private.parquet',pairs,workers,memory))
    del pairs
    require(recipient_summary['rows']==exposure_summary['candidates'],'Recipient join lost exposures')
    timing['history_join']=time.monotonic()-started;started=time.monotonic()
    rows,flow=execute_models(recipient/'recipient_private.parquet',run,key)
    timing['models']=time.monotonic()-started
    return dict(models=len(rows),exposures=exposure_summary,outcomes=outcome_summary,pair_seed=seed_summary,history=history_summary,sample=flow),timing,rows

def guard_history(run):
    path=Path(run)/'PRIVATE/pair_history/catalog_private.json'
    if path.is_file():guard_catalog(read(path))
