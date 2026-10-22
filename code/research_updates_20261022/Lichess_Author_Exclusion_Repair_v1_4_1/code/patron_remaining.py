"""Frozen-slot rematches and original Wave3B2 chooser/opportunity sensitivities."""
from remaining_common import *

def run_stage(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/patron_remaining'))
    from runner import families,opportunity
    from source import wave3b1_helpers as h,chooser_models_v101 as chooser
    prior=stage_output(args.parent,args.variant,'patron')
    design=prior/'PRIVATE/design/chooser_design_features_private.parquet'
    acquisition=prior/'PRIVATE/acquisition_users_private.parquet'
    receipt=read(prior/'PRIVATE/design/DESIGN_DONE.json');verify(receipt['cache'])
    snapshot=h.prior.authenticate_snapshot(args.project)
    key=digest([auth['fingerprint'],record(design),record(acquisition),record(snapshot),sha(__file__)])
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    try:
        bridge=out/'PRIVATE/bridge.parquet';bins=out/'PRIVATE/five_bins.parquet'
        copy(c,'SELECT a.*,coalesce(s.returned,false) returned,s.patron FROM '+scan(acquisition)+' a LEFT JOIN '+scan(snapshot)+' s USING(username_norm)',bridge)
        copy(c,'SELECT p.chooser_username_norm username_norm,p.engine_fairness_bin fairness_bin,count(*)::BIGINT opportunities,sum(p.kind_draw::INTEGER)::BIGINT kind_draws FROM '+scan([r['path'] for r in auth['month_records']])+' p SEMI JOIN '+scan(acquisition)+' a ON p.chooser_username_norm=a.username_norm GROUP BY 1,2',bins)
        frame=families.returned_frame(c,design,snapshot)
        data,groups,_=chooser.prepare_features(frame)
        main=data.loc[data.group_ever_kind_fair.astype(bool)&data.group_kind_returned.astype(bool)].copy()
        del frame,data
        # deterministic_rematch hashes the original focal and requested slot;
        # an unavailable selected slot drops its group, never replaces it.
        rematches=families.rematches(main,groups,out/'PRIVATE',key,out/'report',replicates=100)
        del main
        post=families.postcertification(c,design,snapshot,bins,out/'PRIVATE',key,out/'report')
        cache=out/'PRIVATE/opportunity_cells.parquet'
        qa=opportunity.build_cache(c,[r['path'] for r in auth['month_records']],bridge,cache)
        base=opportunity.fit_families(c,cache,bridge,out/'PRIVATE',key,out/'report',ply=False)
        ply=opportunity.fit_families(c,cache,bridge,out/'PRIVATE',key,out/'report',ply=True)
    finally:c.close()
    return dict(status='REMAINING_WAVE3B2_REFITTED',rematches=rematches,postcertification=post,opportunity=base,ply=ply,cache=qa,replacement_matches=0)

