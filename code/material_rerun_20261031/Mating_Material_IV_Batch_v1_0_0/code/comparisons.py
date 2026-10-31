"""Full fixed denominator, fresh support and labels; metadata always offline."""
from bootstrap import *
import fast_comparisons as fc
import features

def prepare(a,run,conf,b):
    old=a.legacy_root/'comparisons';cr=run/'comparisons';(cr/'report').mkdir(parents=True,exist_ok=True)
    cb=fc.prepare90(a,cr,conf)
    cb['primary']=dict(b)
    # Pool all verified factual denominators before subtracting material removals.
    for rel in ('PRIVATE/wider/environment/combined/rates.parquet','PRIVATE/frames90/F.parquet'):
        p=old/rel
        c.check_stage(p,PARENT)
        if p.name=='rates.parquet':cb['primary']['known_rates']=list(b['known_rates'])+[str(p)]
    meta=old/'PRIVATE/metadata_complete/metadata.parquet';c.check_stage(meta,PARENT)
    cb['metadata'].append(str(meta))
    cb['legacy_candidate_run']=str(old)
    oldq=old/'PRIVATE/supported/queries.parquet';c.check_stage(oldq,PARENT)
    parts=[old/'PRIVATE/chronology_plan90/hits.parquet']
    remainder=old/'PRIVATE/chronology_merge90/features.parquet'
    if remainder.exists():parts.append(remainder)
    for p in parts:c.check_stage(p,PARENT)
    def combine(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'q',oldq);view(db,'f',parts);c.assert_coverage(db,'q','f')
            copy(db,'SELECT * FROM f ORDER BY row_id',tmp/'features.parquet');return dict(rows=rows(oldq))
        finally:db.close()
    cached=cr/'old_chron_cache';stage(cached/'PRIVATE/chronology',conf,combine,[oldq]+parts)
    cb['legacy_chronology_run']=str(cached)
    save(cr/'PRIVATE/BINDING90.json',cb);return cb

def make_frames(a,run,conf,cb,removed):
    cr=run/'comparisons'
    known=[a.legacy_root/'comparisons/PRIVATE/frames90/F.parquet']
    saved=(fc.features90.behavior,fc.features90.volume,fc.primary.environment)
    def env(aa,rr,cc,bb,source):return features.environment(aa,rr,cc,bb,source,removed)
    def vol(aa,rr,cc,bb,source):return features.volume(aa,rr,cc,bb,source,known,90)
    try:
        fc.features90.behavior=features.behavior;fc.features90.volume=vol;fc.primary.environment=env
        fc.frames90(a,cr,conf,cb,run)
    finally:fc.features90.behavior,fc.features90.volume,fc.primary.environment=saved

def metadata(a,run,conf,b):
    root=fc.metadata.plan(a,run,conf,b)
    n=rows(root/'targets.parquet')
    report=read(run/'report/metadata_plan.json')
    report.update(first_pair_and_cooldown_applied_before_requests=False,
                  first_pair_applied_before_requests=True,receipt_cooldown_applied=False,
                  production_network=False)
    save(run/'report/metadata_plan.json',report)
    if n:
        save(run/'report/OFFLINE_HOLD.json',dict(status='BLOCKED_MISSING_CACHED_METADATA',games=n,
            private_target_file=str(root/'targets.parquet'),receipt_results_preserved=True,
            action='Return this report. Supply authenticated cached metadata for the missing games before resuming the comparison stages.'))
        raise RuntimeError(f'OFFLINE_HOLD: {n:,} newly eligible comparison games lack cached metadata. Receipt results are preserved; return the consolidated report.')
    fc.metadata.retrieve(a,run,conf,b)
    save(run/'report/metadata_plan.json',report)

def models(a,run,conf):
    import model_kernel as m
    cr=run/'comparisons';frame=cr/'PRIVATE/frames90';plan=[]
    for tag,outs in [('F',['analysis_entry_uniform90','recipient_disconnect_main','active_timeout']),('O',['y','reached'])]:
        for balance in (False,True):
            job=m.job_for(cr,conf,'uniform_'+tag+('_balance' if balance else ''),frame/(tag+'.parquet'),frame/(tag+'_scores.parquet'),balance=balance)
            job.update(outcomes=outs,iv=False);plan.append(job)
    for job in plan:
        with heartbeat(job['name']):m.fit(job)
        m.export_models(cr)
    receipt=m.job_for(run,conf,'uniform_unspaced','','')
    result=m.contrast(cr,conf,receipt,plan[2],'receipt_minus_ordinary',['rf_y','rf_reached'])
    c.csv_out(cr/'report/receipt_minus_ordinary.csv',result)
