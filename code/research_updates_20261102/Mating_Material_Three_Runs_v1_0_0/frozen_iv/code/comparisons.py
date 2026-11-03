"""Full fixed denominator, fresh support and labels; metadata always offline."""
from bootstrap import *
import fast_comparisons as fc
import features

def chronology_parts(old):
    # bounded_merge returns root/'complete'. The old launcher incorrectly
    # looked for its file in root itself and therefore included only hits.
    report=read(old/'report/chronology90.json')
    hits=old/'PRIVATE/chronology_plan90/hits.parquet'
    c.check_stage(hits,PARENT)
    require(rows(hits)==report['reused'],'Chronology hit count differs from authenticated report')
    parts=[hits]
    if report['missing']:
        remainder=old/'PRIVATE/chronology_merge90/complete/features.parquet'
        c.check_stage(remainder,PARENT)
        require(rows(remainder)==report['missing'],'Chronology remainder count differs from authenticated report')
        parts.append(remainder)
    require(sum(rows(p) for p in parts)==report['rows'],'Chronology part counts do not cover the old query frame')
    return parts

def combine_chronology(oldq,parts,target,memory):
    db=connect(target.parent,memory)
    try:
        view(db,'q',oldq);view(db,'f',parts)
        c.ensure_unique(db,'q');c.ensure_unique(db,'f')
        c.assert_coverage(db,'q','f')
        copy(db,'SELECT * FROM f ORDER BY row_id',target)
        return dict(rows=rows(oldq))
    finally:db.close()

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
    parts=chronology_parts(old)
    def combine(tmp):
        return combine_chronology(oldq,parts,tmp/'features.parquet',a.memory_gb-2)
    cached=cr/'old_chron_cache';stage(cached/'PRIVATE/chronology',conf,combine,[oldq]+parts)
    cb['legacy_chronology_run']=str(cached)
    save(cr/'PRIVATE/BINDING90.json',cb);return cb

def make_frames(a,run,conf,cb,removed):
    from bounded_frames import frames90
    frames90(a,run/'comparisons',conf,cb,run)

def metadata(a,run,conf,b):
    from metadata_cache import complete_offline
    return complete_offline(a,run,conf,b)

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
