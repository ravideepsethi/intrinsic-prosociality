"""Authenticate completed R12; rebuild every exposure variant before spacing."""
from primary_common import *
import cutoffs
import concurrent.futures as cf
import multiprocessing as mp

HISTORY = [f'{x}_{d}' for d in (30,90) for x in ('fair','kind','disconnect','receipt','claim')]+['y','reached']
IDENTITY = ['game_id','recipient_id','opponent_id','received','archive_start_ms','anchor_ms']

def bind(a, run, conf):
    r12=a.r12_root; root=r12/'PRIVATE/cutoffs'
    cfg=load(r12/'PRIVATE/RUN_CONFIG.json')
    require(key(cfg).startswith(R12_PREFIX),'R12 cache configuration differs')
    require(load(r12/'PRIVATE/STATE.json')['cutoffs']['status']=='COMPLETE','R12 cutoff stage is incomplete')
    for filename in ('cutoff_robustness.csv','cutoff_cohort_bridge.json','cutoff_selection_counts.csv'):
        require(sha(r12/'report'/filename)==sha(PACKAGE/'evidence'/filename),'Accepted R12 report changed: '+filename)
    sk=verified_receipt(root/'selection.parquet')['key']
    verified_receipt(root/'source.parquet',sk)
    verified_receipt(root/'clean_features.parquet',sk)
    verified_receipt(root/'with_volume.parquet')
    frame=root/'frame_5.parquet';scores=root/'score_5.parquet'
    fkey=key([sk,5,sha(frame),sha(scores)])
    verified_receipt(root/'fit_5.json',fkey)
    expected=next(x for x in __import__('csv').DictReader((PACKAGE/'evidence/cutoff_robustness.csv').open())
                  if x['cutoff']=='5' and x['sample']=='rebuilt_preminimum_frame')
    fit=load(root/'fit_5.json')
    for name in ('exposures','recipients','first_stage','first_stage_se','reduced_form','reduced_form_se','iv','iv_se','first_stage_F'):
        require(np.isclose(float(expected[name]),fit[name],atol=2e-10,rtol=1e-10),'Accepted R12 fit differs: '+name)
    require(pq.ParquetFile(frame).metadata.num_rows==EXPECTED_N,'Primary cohort count differs')
    b=iv.bind(a,run)
    raw=cutoffs.audit_source(a)
    allscores=[]
    for s in range(16):
        p=root/'scores'/f'{s:02}.parquet';verified_receipt(p);allscores.append(str(p))
    expected_selection_key=key([key([key(cfg),sha(raw),sha(b['reference'])]),[sha(p) for p in allscores]])
    require(sk==expected_selection_key,'R12 selection is not bound to these pre-minimum rows, donor scores, and state reference')
    env=root/'environment/combined/rates.parquet';frozen.r9_inputs.stage_file(env,sk)
    known=[str(root/'with_volume.parquet')];rates=[str(env)]
    r9bmeta=load(PACKAGE/'evidence/r9b_summary.json');r9bc=r9bmeta['configuration_sha256']
    r9broot=a.project/'derived/replication/r9b_remaining_diagnostics_v100_PRIVATE'/r9bc[:12]
    if r9broot.is_dir():
        require(frozen.r.io.cfgsha(load(r9broot/'config.json'))==r9bc,'R9b configuration changed')
        require(load(r9broot/'report/summary.json')==r9bmeta,'R9b completed report changed')
        pp=frozen.r9_inputs.stage_file(r9broot/'clean_source/all.parquet',r9bc)
        ep=frozen.r9_inputs.stage_file(r9broot/'environment/combined/rates.parquet',r9bc)
        known.append(str(pp));rates.append(str(ep))
    info=dict(primary=str(frame),primary_scores=str(scores),raw=str(raw),all_scores=allscores,
              known_features=known,known_rates=rates,r12_root=str(r12),r12_selection_key=sk,baseline=fit,bound=b)
    c=db(run/'PRIVATE/spill_bind',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+parq([frame]));c.execute('CREATE VIEW s AS SELECT * FROM '+parq([scores]))
        ensure_unique(c,'p',EXPECTED_N);ensure_unique(c,'s',EXPECTED_N)
        require(c.execute('SELECT count(*),count(DISTINCT recipient_id) FROM p JOIN s USING(row_id)').fetchone()==(EXPECTED_N,EXPECTED_RECIPIENTS),'Primary identity/count failed')
        require(c.execute('SELECT count(*) FROM s WHERE n_A<5 OR NOT isfinite(adjusted_A) OR NOT isfinite(expected_A)').fetchone()[0]==0,'Primary support failed')
        ids=','.join(map(str,b['binding']['author_ids']))
        require(c.execute(f'SELECT count(*) FROM p WHERE recipient_id IN ({ids}) OR opponent_id IN ({ids})').fetchone()[0]==0,'Author exposure remains')
    finally:c.close()
    save(run/'PRIVATE/BOUND.json',info)
    save(run/'report/cohort_rule.json',DEFINITION)
    save(run/'report/cohort_bridge.json',load(r12/'report/cutoff_cohort_bridge.json'))
    save(run/'report/cache_authentication.json',dict(r12_report_sha256=load(PACKAGE/'evidence/r12_report_authority.json')['zip_sha256'],
         primary_frame_sha256=sha(frame),primary_score_sha256=sha(scores),primary_rows=EXPECTED_N,
         primary_recipients=EXPECTED_RECIPIENTS,primary_row_set_sha256=frozen.r.design.row_digest(frozen.col(frame,'row_id')),
         verified_R12_fit=fit,upstream_files_read_only=True))
    return info

def spacing_flags(person,start,anchor,support):
    """The original strict start > previous anchor+gap rule, with new support."""
    from audit_logic import spaced
    return {f'spaced{days}':spaced(person,start,anchor,support,days) for days in (30,90)}

def build_selection(a,run,conf,b):
    root=run/'PRIVATE/wider';root.mkdir(parents=True,exist_ok=True)
    out=root/'selection.parquet';ck=key([conf,'selection',sha(b['raw']),[sha(p) for p in b['all_scores']]])
    if cached(out,ck):return out
    c=db(root/'spill_selection',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW raw AS SELECT * FROM '+parq([b['raw']]))
        c.execute('CREATE VIEW s AS SELECT * FROM '+parq(b['all_scores']))
        ensure_unique(c,'raw',14058373);ensure_unique(c,'s')
        cols=['row_id','recipient_id','archive_start_ms','anchor_ms','complete90','history_window_complete','first_recipient']
        d=c.execute('SELECT '+','.join('raw.'+x for x in cols)+',s.n_A,s.adjusted_A,s.expected_A FROM raw JOIN s USING(row_id) ORDER BY recipient_id,archive_start_ms,row_id').fetchdf()
        support=(d.n_A.to_numpy()>=5)&np.isfinite(d.adjusted_A.to_numpy())&np.isfinite(d.expected_A.to_numpy())
        flags=spacing_flags(d.recipient_id.to_numpy(),d.archive_start_ms.to_numpy(),d.anchor_ms.to_numpy(),support)
        obs=d.complete90.to_numpy(bool)&d.history_window_complete.to_numpy(bool)
        keep=support&obs
        t=pa.table(dict(row_id=d.row_id.to_numpy(),supported=support,observation_complete=obs,keep=keep,
                        first_recipient=d.first_recipient.to_numpy(bool),**flags))
        temp=out.with_suffix('.partial.parquet');pq.write_table(t,temp,compression='zstd');os.replace(temp,out);seal(out,ck)
        csv_out(run/'report/exposure_selection_counts.csv',[
            dict(step='all_time_five_supported_before_windows',exposures=int(support.sum())),
            dict(step='all_supported_complete_windows',exposures=int(keep.sum())),
            dict(step='spaced30_before_windows',exposures=int(flags['spaced30'].sum())),
            dict(step='spaced90_before_windows',exposures=int(flags['spaced90'].sum())),
            dict(step='spaced30_complete_windows',exposures=int((flags['spaced30']&obs).sum())),
            dict(step='spaced90_complete_windows',exposures=int((flags['spaced90']&obs).sum())),
            dict(step='first_observed_supported_complete_windows',exposures=int((d.first_recipient.to_numpy(bool)&keep).sum()))])
        require(int((flags['spaced90']&obs).sum())==EXPECTED_N,'Rebuilt 90-day selection does not reproduce R12')
    finally:c.close()
    return out

def known_feature_union(a,run,conf,b):
    root=run/'PRIVATE/wider';out=root/'known_features.parquet'
    cols=['row_id']+IDENTITY+HISTORY+['pre_games_30d'];ck=key([conf,'known_features',[sha(p) for p in b['known_features']]])
    if cached(out,ck):return out
    c=db(root/'spill_known',a.memory_gb-2)
    try:
        views=[]
        for j,p in enumerate(b['known_features']):
            view='k'+str(j);views.append(view)
            c.execute('CREATE VIEW '+view+' AS SELECT '+','.join(cols)+' FROM '+parq([p]));ensure_unique(c,view)
            if j:bridge(c,'k0',view,IDENTITY+HISTORY+['pre_games_30d'],'R12/R9b reusable feature bridge')
        query=' UNION ALL '.join('SELECT * FROM '+v+(' WHERE row_id NOT IN (SELECT row_id FROM k0)' if j else '') for j,v in enumerate(views))
        copy_query(c,query+' ORDER BY row_id',out);seal(out,ck)
    finally:c.close()
    return out

def rebuild_wider_features(a,run,conf,b,selected):
    root=run/'PRIVATE/wider';known=known_feature_union(a,run,conf,b)
    sk=key([conf,'wider_features',sha(selected),sha(known)])
    source=root/'source.parquet';fresh=root/'missing_features.parquet';merged=root/'clean_features.parquet'
    c=db(root/'spill_features',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW raw AS SELECT * FROM '+parq([b['raw']]));c.execute('CREATE VIEW chosen AS SELECT * FROM '+parq([selected]))
        c.execute('CREATE VIEW known AS SELECT * FROM '+parq([known]))
        if not cached(source,sk):
            copy_query(c,'SELECT raw.* EXCLUDE(spaced30,spaced90,first_recipient),chosen.spaced30,chosen.spaced90,chosen.first_recipient,FALSE previous_frame FROM raw JOIN chosen USING(row_id) WHERE chosen.keep ORDER BY row_id',source);seal(source,sk)
        c.execute('CREATE VIEW source AS SELECT * FROM '+parq([source]));ensure_unique(c,'source')
        if not cached(fresh,sk):
            copy_query(c,'SELECT source.* FROM source ANTI JOIN known USING(row_id) ORDER BY row_id',fresh);seal(fresh,sk)
        missing=pq.ParquetFile(fresh).metadata.num_rows
        save(run/'report/wider_cache_reuse.json',dict(total_rows=pq.ParquetFile(source).metadata.num_rows,missing_history_outcome_rows=missing,
              known_feature_rows=pq.ParquetFile(known).metadata.num_rows,source='Verified R12 and, when available, R9b caches'))
    finally:c.close()
    if cached(merged,sk):return merged,known
    newfeatures=None
    if missing:
        freshroot=root/'fresh';freshroot.mkdir(exist_ok=True)
        newfeatures=cutoffs.clean_features(a,b['bound'],fresh,freshroot,sk)
    c=db(root/'spill_feature_merge',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]));c.execute('CREATE VIEW known AS SELECT * FROM '+parq([known]))
        if newfeatures:
            c.execute('CREATE VIEW fresh AS SELECT * FROM '+parq([newfeatures]))
            hist='SELECT row_id,'+','.join(HISTORY)+' FROM known UNION ALL SELECT row_id,'+','.join(HISTORY)+' FROM fresh'
        else:hist='SELECT row_id,'+','.join(HISTORY)+' FROM known'
        c.execute('CREATE VIEW h AS '+hist);ensure_unique(c,'h')
        copy_query(c,'SELECT q.* EXCLUDE('+','.join(HISTORY)+'),'+','.join('h.'+x for x in HISTORY)+' FROM q JOIN h USING(row_id) ORDER BY row_id',merged)
        require(pq.ParquetFile(merged).metadata.num_rows==pq.ParquetFile(source).metadata.num_rows,'History merge changed wider rows');seal(merged,sk)
    finally:c.close()
    return merged,known

def environment(a,run,conf,b,source):
    import r7_inputs
    root=run/'PRIVATE/wider/environment';root.mkdir(parents=True,exist_ok=True)
    old=root/'known_rates.parquet';ck=key([conf,'known_rates',[sha(p) for p in b['known_rates']]])
    if not cached(old,ck):
        c=db(root/'spill_known',a.memory_gb-2)
        try:
            for j,p in enumerate(b['known_rates']):c.execute(f'CREATE VIEW r{j} AS SELECT * FROM '+parq([p]))
            keys=['person','partner','month_code'];cols=pq.ParquetFile(b['known_rates'][0]).schema_arrow.names
            if len(b['known_rates'])>1:
                terms=['a."'+x+'" IS DISTINCT FROM b."'+x+'"' for x in cols if x not in keys]
                require(c.execute('SELECT count(*) FROM r0 a JOIN r1 b USING(person,partner,month_code) WHERE '+' OR '.join(terms)).fetchone()[0]==0,'R12/R9b ENV cache disagreement')
            query='SELECT * FROM r0'+(' UNION ALL SELECT r1.* FROM r1 ANTI JOIN r0 USING(person,partner,month_code)' if len(b['known_rates'])>1 else '')
            copy_query(c,query,old);seal(old,ck)
        finally:c.close()
    req,info=r7_inputs.missing_requests([source],old,root/'requests',conf,a.memory_gb-2);rates=[old]
    if info['missing_requests']:
        binding=b['bound']['binding'];e=Path(binding['environment']['root']);ec=binding['environment']['conf'];panels=[]
        for folder in sorted((e/'rate_panels').iterdir()):
            if not (folder/'_DONE.json').exists():continue
            p=frozen.r9_inputs.stage_file(folder/'events.parquet',ec);m=load(folder/'_DONE.json')
            panels.append(dict(path=str(p),minimum=m['minimum'],maximum=m['maximum']))
        jobs,scan=frozen.r.env_rates.chronology_jobs(binding['source']['chron'],info['windows'],panels,req,root/'parts',conf,3.)
        for job in jobs:job.update(authors=binding['author_ids'],memory=3.,memory_gb=4.5)
        result=frozen.runtime.mapped(inputs.env_attempt,jobs,min(a.workers,2),a.memory_gb,'Only missing wider-cohort ENV histories',50,90)
        retry=[dict(j,memory=8.,memory_gb=9.) for j,v in zip(jobs,result) if not v['ok']]
        if retry:
            result=frozen.runtime.mapped(inputs.env_attempt,retry,1,a.memory_gb,'Serial ENV memory retries',20,90)
            require(all(v['ok'] for v in result),'ENV serial memory retry failed')
        fresh,_=frozen.r.env_rates.combine(req,[j['output'] for j in jobs],[p['path'] for p in panels],root/'fresh',conf,a.memory_gb-2,1)
        rates.append(fresh/'rates.parquet');info['scan']=scan
    def union(tmp):
        c=db(tmp/'spill',a.memory_gb-2)
        try:
            copy_query(c,' UNION ALL '.join('SELECT * FROM '+parq([p]) for p in rates),tmp/'rates.parquet')
            return dict(rows=pq.ParquetFile(tmp/'rates.parquet').metadata.num_rows)
        finally:c.close()
    out,_=frozen.r.stable_stage(root/'combined',conf,union,rates)
    attached,_=frozen.r.env_rates.attach(source,out/'rates.parquet',root/'attached',conf,a.memory_gb-2)
    save(run/'report/wider_environment.json',frozen.public(info));return attached/'model.parquet'

def wider(a,run,conf,b):
    selected=build_selection(a,run,conf,b)
    clean,known=rebuild_wider_features(a,run,conf,b,selected)
    # Known playing volume is factual chronology; missing rows use the same R12 worker.
    bound=dict(b['bound'],original=str(known))
    root=run/'PRIVATE/wider'
    volume=cutoffs.add_volume(a,bound,clean,root,conf)
    source=environment(a,run,conf,b,volume)
    scores=root/'scores.parquet';ck=key([conf,sha(source),[sha(p) for p in b['all_scores']]])
    c=db(root/'spill_final',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]));c.execute('CREATE VIEW s AS SELECT * FROM '+parq(b['all_scores']))
        c.execute('CREATE VIEW primary AS SELECT * FROM '+parq([b['primary']]))
        c.execute('CREATE VIEW rebuilt90 AS SELECT * FROM q WHERE spaced90')
        ensure_unique(c,'rebuilt90',EXPECTED_N)
        bridge(c,'rebuilt90','primary',IDENTITY+HISTORY+['pre_games_30d','environment_supported']+frozen.r.ENV,'Rebuilt primary identity and complete feature bridge',EXPECTED_N)
        if not cached(scores,ck):
            copy_query(c,'SELECT s.* FROM s JOIN q USING(row_id) ORDER BY row_id',scores);seal(scores,ck)
        require(pq.ParquetFile(scores).metadata.num_rows==pq.ParquetFile(source).metadata.num_rows,'Wider score/source rows differ')
        counts=c.execute('SELECT count(*),count(DISTINCT recipient_id),sum(spaced90)::BIGINT,sum(spaced30)::BIGINT,sum(first_recipient)::BIGINT FROM q').fetchone()
        save(run/'report/wider_sample_counts.json',dict(all_exposures=counts[0],all_recipients=counts[1],primary90=counts[2],spacing30=counts[3],first_observed=counts[4],primary_features_reproduced=True))
    finally:c.close()
    save(run/'PRIVATE/WIDER.json',dict(source=str(source),scores=str(scores)))
    return source,scores
