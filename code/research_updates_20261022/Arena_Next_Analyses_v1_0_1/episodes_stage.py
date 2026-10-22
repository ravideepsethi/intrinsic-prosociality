"""The repository's B1 conditional randomization, on arena repeat granters."""
from pathlib import Path
from next_common import *

def engine():
    import sys
    sys.path.insert(0,str(ROOT/'source/episodes'))
    import episode_engine
    if not getattr(episode_engine,'arena_utc_configured',False):
        original=episode_engine.configure_duckdb
        def utc(connection,payload,temp):
            original(connection,payload,temp);connection.execute("SET TimeZone='UTC'")
        episode_engine.configure_duckdb=utc;episode_engine.arena_utc_configured=True
    return episode_engine

def run(sample, root, args, contract):
    mod=engine();state=Path(root)/'private/episodes';public=Path(root)/'public/episodes'
    state.mkdir(parents=True,exist_ok=True);public.mkdir(parents=True,exist_ok=True)
    c=db(state/'support_spill',args.memory,args.threads)
    try:
        support=records(c,f'''WITH x AS (SELECT chooser_username_norm,count(*) AS n,sum(kind_draw::BIGINT) AS k
          FROM {parq(sample['panels'])} WHERE fair_competitive AND kind_draw IS NOT NULL
          AND chooser_username_norm IS NOT NULL AND trim(chooser_username_norm)<>'' GROUP BY 1)
          SELECT count(*) AS choosers,coalesce(sum(n),0)::BIGINT AS opportunities,
          coalesce(sum(k),0)::BIGINT AS kind_draws FROM x WHERE n>=4 AND k>=2 AND k<n''')[0]
    finally:c.close()
    bindings={'EXPECTED_B1_CHOOSERS':support['choosers'],'EXPECTED_B1_OPPORTUNITIES':support['opportunities'],
      'EXPECTED_B1_KIND_DRAWS':support['kind_draws'],'EXPECTED_STAGE07_FAIR_CHOOSERS':sample['authority']['fair_choosers'],
      'EXPECTED_STAGE07_FAIR_KIND_CHOOSERS':sample['authority']['fair_kind_choosers'],
      'EXPECTED_STAGE07_FAIR_ROWS':sample['authority']['fair_rows'],'EXPECTED_STAGE07_FAIR_KIND_DRAWS':sample['authority']['fair_kind_draws']}
    for k,v in bindings.items():setattr(mod,k,v)
    js(public/'INPUT_BINDINGS.json',{'support':support,'bindings':bindings,'producer_sha256':sha(mod.__file__),
       'criteria':'At least four competitive arena opportunities, at least two grants, at least one non-grant.',
       'kernels_hours':[6,24,168],'randomizations':4999,'chooser_crossfit_folds':5,
       'clock':'lastMoveAt with archive-start fallback, as in the original B1 producer',
       'claim':'Sequence dependence within arena opportunities; no causal episode interpretation.'})
    if support['choosers']<10:
        return {'status':'UNSUPPORTED','reason':'Fewer than ten eligible repeat granters for five-fold cross-fitting',**support}
    payload={'stage07':{'paths':sample['panels']},'threads':args.threads,'memory_limit':args.memory,
      'resume_config_sha256':contract,'b1_workers':min(args.workers,5)}
    # The original checkpoint builder checks dynamic arena totals against an independent census.
    path,receipt=mod.build_or_authenticate_b1_sample(payload,state)
    require(receipt['resume_config_sha256']==contract,'Episode sample checkpoint has another configuration')
    result=mod.run_b1_conditional_randomization(payload,state,path,receipt)
    for r in result['rows']:
        if r['null_standard_deviation']<=0:
            r.update(status='UNSUPPORTED_DEGENERATE_NULL',p_value_raw=None,p_value_holm_within_b1=None,standardized_difference=None)
        else:r['status']='ESTIMATED'
    csvout(public/'episode_randomization.csv',result['rows'])
    # Receipts contain private paths, but never account identifiers or account-level predictions.
    js(public/'RESULTS.json',result)
    return {'status':'COMPLETE','randomizations':4999,**support,
      'interpretation':'Tests excess temporal clustering conditional on chooser totals and cross-fitted current-state propensities.'}
