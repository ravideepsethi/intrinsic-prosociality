"""Rebuild cutoff eligibility from the authenticated pre-five exposure universe.

The old cohort also used a lag-seven support screen before spacing. Applying
an all-time Score A cutoff to the earlier universe can therefore change even
the cutoff-five cohort. Both that rebuilt cohort and the certified R9 reference
are reported; this distinction is never hidden behind a reused cutoff-five row.
"""
import concurrent.futures as cf, multiprocessing as mp, sys, gc
import pyarrow as pa
import pyarrow.parquet as pq
from local_common import *
from iv_followups import bind, iv_fit, reproduce, inputs, frozen

def audit_source(a):
    import phase_inputs
    p=Path(phase_inputs.__file__).resolve().parents[1]/'evidence/entry_authority.json'
    authority=load(p)['audit'];conf=authority['config_sha256']
    root=a.project/'derived/replication/chooser_iv_repeated_audit_v100_PRIVATE'/conf[:12]
    frozen.r.io.checked(root/'report/_DONE.json',authority['report_receipt_sha256'])
    require(frozen.r.io.cfgsha(load(root/'config.json'))==conf,'Pre-five universe config changed')
    path=frozen.r9_inputs.stage_file(root/'analysis/analysis.parquet',conf)
    require(pq.ParquetFile(path).metadata.num_rows==14058373,'Pre-five universe row count changed')
    return path

def donor_job(job):
    out=Path(job['out']);ck=job['key']
    if cached(out,ck):return str(out)
    chunks=[]
    for rec in job['parts']:
        frozen.r.io.checked(rec['path'],rec['sha256'],rec.get('bytes'))
        h=frozen.r.arrays(frozen.r.io.read(rec['path'],['j','i','t','y','arm','cell']))
        use=h['arm'].astype(bool)&~np.isin(h['j'],job['authors'])&~np.isin(h['i'],job['authors'])
        chunks.append({x:h[x][use] for x in ['j','i','t','y','cell']})
    h={x:np.concatenate([v[x] for v in chunks]) for x in chunks[0]};del chunks
    q=frozen.r.arrays(frozen.r.io.read(job['query']));ref=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
    score,fallback=inputs.alltime(h,q,ref)
    # Independent direct pair-exclusion oracle, including newly admitted low-support queries.
    error=0.
    for ix in np.unique(np.linspace(0,len(q['row_id'])-1,min(16,len(q['row_id'])),dtype=int)):
        mask=(h['j']==q['opponent_id'][ix])&(h['i']!=q['recipient_id'][ix]);hh={x:v[mask] for x,v in h.items()}
        require(score['n'][ix]==mask.sum() and score['counterparts'][ix]==len(np.unique(hh['i'])),'Cutoff donor count oracle failed')
        if mask.any():
            mapping,_=frozen.r9_scores.reference_map(ref,frozen.r9_scores.event_month(hh['t']))
            fold=int(frozen.r.num.user_hash(np.array([q['recipient_id'][ix]]))[0]%np.uint64(4))
            prediction,_=frozen.r9_scores.donor_weights(hh,ref,fold,mapping)
            error=max(error,abs(float(score['adjusted'][ix])-float(np.mean(hh['y']-prediction))))
    require(error<2e-10,'Cutoff score oracle failed')
    out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_name(out.name+'.tmp')
    pq.write_table(pa.table(dict(row_id=q['row_id'],**{x+'_A':v for x,v in score.items()})),tmp,compression='zstd');os.replace(tmp,out)
    save(str(out)+'.audit.json',dict(queries=len(q['row_id']),donors=len(h['j']),oracle_max_error=error));seal(out,ck);return str(out)

def spacing(person,start,anchor,eligible):
    """Greedy 90-day spacing, before administrative/history cuts; sorted inputs."""
    require(np.all(person[1:]>=person[:-1]) and np.all((person[1:]!=person[:-1])|(start[1:]>=start[:-1])),'Spacing order changed')
    require(np.all(anchor>=start),'Anchor before start')
    out=np.zeros(len(person),bool);prev=None;next_start=-1
    for i in np.flatnonzero(eligible):
        if person[i]!=prev:prev=person[i];next_start=-1
        if start[i]>next_start:out[i]=True;next_start=int(anchor[i])+90*DAY
    return out

def volume_job(job):
    import followup_logic as vol
    p=Path(job['input']['path']);out=Path(job['out']);ck=job['key']
    # cached_inputs.research_inputs already checks the chronology manifest's
    # bytes, rows and row groups. Its bound records carry io.sig(path), not a
    # top-level bytes field; use the same signature gate as env_rates.
    info=job['input'];signature=info.get('signature')
    require(isinstance(signature,list) and len(signature)==2,'Chronology record lacks [size, mtime_ns] signature')
    before=frozen.r.io.sig(p)
    require(before==signature,'Chronology signature changed before volume scan')
    if cached(out,ck):return str(out)
    pf=pq.ParquetFile(p)
    require(pf.metadata.num_rows==int(info['rows']),'Chronology row count changed before volume scan')
    require({'utc_ms','white_id','black_id'}<=set(pf.schema_arrow.names),'Chronology schema changed before volume scan')
    q=job['query'];keys=np.load(q+'/keys.npy',mmap_mode='r');order=np.load(q+'/order.npy',mmap_mode='r');people=np.load(q+'/people.npy',mmap_mode='r')
    meta=load(q+'/meta.json');delta=np.zeros(len(order)+1,np.int64);idx=pf.schema_arrow.get_field_index('utc_ms')
    for g in range(pf.metadata.num_row_groups):
        stat=pf.metadata.row_group(g).column(idx).statistics
        if stat is not None and stat.has_min_max and (stat.max<meta['minimum']-30*DAY or stat.min>=meta['maximum']):continue
        for batch in pf.iter_batches(row_groups=[g],columns=['utc_ms','white_id','black_id'],batch_size=131072,use_threads=False):
            t,w,b=[batch.column(j).fill_null(-1).to_numpy(zero_copy_only=False).astype(np.int64,copy=False) for j in range(3)]
            use=(t>=meta['minimum']-30*DAY)&(t<meta['maximum'])
            if use.any():vol.accumulate_volume(t[use],w[use],b[use],keys,people,delta)
    value=vol.finish_volume(delta,order);require(frozen.r.io.sig(p)==before,'Chronology changed during volume scan')
    npz(out,value=value);seal(out,ck);return str(out)

def add_volume(a,b,source,root,k):
    import followup_logic as vol
    out=root/'with_volume.parquet';ck=key([k,'volume',sha(source),sha(b['original'])])
    if cached(out,ck):return out
    c=db(root/'spill_volume',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]));c.execute('CREATE VIEW old AS SELECT row_id,pre_games_30d FROM '+parq([b['original']]))
        missing=c.execute('SELECT row_id,recipient_id,archive_start_ms FROM q ANTI JOIN old USING(row_id) ORDER BY row_id').fetchdf()
        if len(missing):
            query=root/'volume_query';query.mkdir(parents=True,exist_ok=True)
            keys,order,people=vol.volume_plan(missing.recipient_id.to_numpy(),missing.archive_start_ms.to_numpy())
            for name,value in [('keys',keys),('order',order),('people',people)]:np.save(query/(name+'.npy'),value,allow_pickle=False)
            save(query/'meta.json',dict(minimum=int(missing.archive_start_ms.min()),maximum=int(missing.archive_start_ms.max())))
            jobs=[dict(input=r,query=str(query),out=str(root/'volume_parts'/f'{j:04d}.npz'),key=key([ck,r])) for j,r in enumerate(b['binding']['source']['chron'])]
            nworkers=min(a.workers,2);total=np.zeros(len(missing),np.int64)
            log(f'30-day volume: {len(missing):,} new exposures, {len(jobs)} chronology files, {nworkers} workers; verified file checkpoints are reused')
            started=time.monotonic()
            with heartbeat('New cutoff rows: 30-day game volume'),cf.ProcessPoolExecutor(max_workers=nworkers,mp_context=mp.get_context('spawn')) as pool:
                pending=[pool.submit(volume_job,job) for job in jobs]
                for done,future in enumerate(cf.as_completed(pending),1):
                    p=future.result()
                    with np.load(p,allow_pickle=False) as z:total+=z['value']
                    if done%16==0 or done==len(jobs):
                        log(f'30-day volume files {done}/{len(jobs)} complete; elapsed {(time.monotonic()-started)/60:.1f} min')
            fresh=pa.table(dict(row_id=missing.row_id.to_numpy(),pre_games_30d=total));c.register('fresh',fresh)
        else:c.execute('CREATE TEMP TABLE fresh(row_id BIGINT,pre_games_30d BIGINT)')
        names=pq.ParquetFile(source).schema_arrow.names
        fields='q.* EXCLUDE(pre_games_30d)' if 'pre_games_30d' in names else 'q.*'
        copy_query(c,'SELECT '+fields+',coalesce(old.pre_games_30d,fresh.pre_games_30d)::BIGINT pre_games_30d FROM q LEFT JOIN old USING(row_id) LEFT JOIN fresh USING(row_id) ORDER BY row_id',out)
        require(c.execute('SELECT count(*) FROM '+parq([out])+' WHERE pre_games_30d IS NULL OR pre_games_30d<0').fetchone()[0]==0,'Missing new-row playing volume')
        seal(out,ck);return out
    finally:c.close()

def clean_features(a,b,base,root,sk):
    # The merged file has its own input-key and SHA256 receipt. Return before
    # rewriting query files: upstream completed shards bind their input mtime.
    merged=root/'clean_features.parquet'
    if cached(merged,sk):
        log('Reusing verified cutoff histories and later outcomes')
        return merged
    prep=root/'outcome_queries';prep.mkdir(exist_ok=True)
    c=db(root/'spill_outcomes',a.memory_gb-2)
    try:
        for s in range(16):copy_query(c,'SELECT * FROM '+parq([base])+f' WHERE recipient_id%16={s} ORDER BY row_id',prep/f'outcome_{s:02}.parquet')
    finally:c.close()
    jobs=inputs.outcome_jobs(b,prep,root,sk)
    with heartbeat('Author-clean cutoff histories and later outcomes'):
        frozen.runtime.mapped(frozen.fast.outcome_job,jobs,min(2,a.workers),a.memory_gb,'Cutoff histories',45,60)
    c=db(root/'spill_merge',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW q AS SELECT * FROM '+parq([base]));c.execute('CREATE VIEW o AS SELECT * FROM '+parq([Path(j['output'])/'outcomes.parquet' for j in jobs]))
        replace=[f'{x}_{days}' for days in [30,90] for x in ['fair','kind','disconnect','receipt','claim']]+['y','reached']
        copy_query(c,'SELECT q.* EXCLUDE('+','.join(replace)+'),'+','.join('o.'+x for x in replace)+' FROM q JOIN o USING(row_id) ORDER BY row_id',merged)
        require(pq.ParquetFile(merged).metadata.num_rows==pq.ParquetFile(base).metadata.num_rows,'Cutoff feature join lost rows');seal(merged,sk)
    finally:c.close()
    return merged

def run(a,run,k):
    b=bind(a,run);raw=audit_source(a);root=run/'PRIVATE/cutoffs';root.mkdir(parents=True,exist_ok=True)
    authors=b['binding']['author_ids'];ids=','.join(map(str,authors));ck=key([k,sha(raw),sha(b['reference'])])
    querybase=root/'queries.parquet'
    if not cached(querybase,ck):
        c=db(root/'spill_queries',a.memory_gb-2)
        try:
            copy_query(c,'SELECT row_id,recipient_id,opponent_id,month_code FROM '+parq([raw])+f' WHERE recipient_id NOT IN ({ids}) AND opponent_id NOT IN ({ids}) ORDER BY row_id',querybase)
            seal(querybase,ck)
        finally:c.close()
    qdir=inputs.query_shards(querybase,root/'query_shards',ck)
    jobs=[dict(query=str(qdir/f'{s:02}.parquet'),reference=b['reference'],authors=authors,
               parts=[p for p in b['parts'] if p['shard']==s],out=str(root/'scores'/f'{s:02}.parquet'),key=key([ck,s])) for s in range(16)]
    with heartbeat('Rebuild all-time pair-excluded scores before minimum support'),cf.ProcessPoolExecutor(max_workers=min(2,a.workers),mp_context=mp.get_context('spawn')) as pool:
        scores=list(pool.map(donor_job,jobs))
    selected=root/'selection.parquet';sk=key([ck,[sha(p) for p in scores]])
    c=db(root/'spill_select',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW raw AS SELECT * FROM '+parq([raw]));c.execute('CREATE VIEW scores AS SELECT * FROM '+parq(scores))
        c.execute('CREATE VIEW s0 AS SELECT * FROM '+parq([b['s0']]))
        oldscore=Path(b['parent'])/'scores_combined/S0.parquet';c.execute('CREATE VIEW oldscore AS SELECT * FROM '+parq([oldscore]))
        require(c.execute('SELECT count(*) FROM scores JOIN oldscore USING(row_id)').fetchone()[0]==2682329,'Pre-five source does not contain all certified S0 rows')
        for field in ['n_A','counterparts_A','expected_A','adjusted_A']:
            error=c.execute(f'SELECT max(abs(scores.{field}-oldscore.{field})) FROM scores JOIN oldscore USING(row_id)').fetchone()[0]
            require(error is not None and error<2e-10,'Rebuilt donor controls/score differ on S0: '+field)
        if not cached(selected,sk):
            cols=['row_id','recipient_id','archive_start_ms','anchor_ms','complete90','history_window_complete','n_A','adjusted_A']
            d=c.execute('SELECT '+','.join('raw.'+x if x not in ['n_A','adjusted_A'] else 'scores.'+x for x in cols)+' FROM raw JOIN scores USING(row_id) ORDER BY recipient_id,archive_start_ms,row_id').fetchdf()
            result={'row_id':d.row_id.to_numpy()};audit=[]
            for cutoff in [3,5,10,20]:
                support=(d.n_A.to_numpy()>=cutoff)&np.isfinite(d.adjusted_A.to_numpy())
                spaced=spacing(d.recipient_id.to_numpy(),d.archive_start_ms.to_numpy(),d.anchor_ms.to_numpy(),support)
                kept=spaced&d.complete90.to_numpy(bool)&d.history_window_complete.to_numpy(bool)
                result['cutoff_'+str(cutoff)]=kept;audit.append(dict(cutoff=cutoff,supported=int(support.sum()),spaced_before_calendar_cuts=int(spaced.sum()),analysis_rows=int(kept.sum())))
            t=pa.table(result);pq.write_table(t,selected,compression='zstd');seal(selected,sk);csv_out(run/'report/cutoff_selection_counts.csv',audit);del d,t,result;gc.collect()
        c.execute('CREATE VIEW selected AS SELECT * FROM '+parq([selected]))
        base=root/'source.parquet';union=' OR '.join('cutoff_'+str(x) for x in [3,5,10,20])
        if not cached(base,sk):
            copy_query(c,'SELECT raw.*,FALSE previous_frame FROM raw JOIN selected USING(row_id) WHERE '+union+' ORDER BY row_id',base);seal(base,sk)
        overlap=c.execute('SELECT count(*) FILTER(WHERE cutoff_5),count(*) FILTER(WHERE cutoff_5 AND s0.row_id IS NOT NULL),count(*) FILTER(WHERE s0.row_id IS NOT NULL) FROM selected FULL JOIN s0 USING(row_id)').fetchone()
    finally:c.close()
    save(run/'report/cutoff_cohort_bridge.json',dict(rebuilt_cutoff5=int(overlap[0]),overlap_with_certified_R9=int(overlap[1]),certified_R9=int(overlap[2]),
         same_cohort=overlap[0]==overlap[1]==overlap[2],
         reason='Certified S0 used historical lag-seven minimum-five support BEFORE spacing. New rows use the requested all-time Score A cutoff before spacing. Rebuilt cutoff five is therefore not silently labelled the certified S0 cohort.',
         order='pre-support first-pair exposure universe; remove author exposures; rebuild Score A excluding both author roles and every focal pair decision; apply cutoff; greedy 90-day spacing in recipient/start/row_id order; complete 90-day follow-up and 97-day history coverage; clean histories and outcomes',
         donor_set='All-time Score A donor set is unchanged by an exposure eligibility threshold; the score and all three history controls are recomputed from that same set.'))
    # Frozen fast feature workers also handle new rows; they never copy old outcomes into a new exposure.
    merged=clean_features(a,b,base,root,sk)
    with_volume=add_volume(a,b,merged,root,sk)
    with heartbeat('Attach opponent environment controls to cutoff rows'):
        source,envinfo=inputs.environment(b,with_volume,root/'environment',sk,a.memory_gb,a.workers)
    c=db(root/'spill_frames',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]));c.execute('CREATE VIEW chosen AS SELECT * FROM '+parq([selected]));c.execute('CREATE VIEW s AS SELECT * FROM '+parq(scores))
        for cutoff in [3,5,10,20]:
            p=root/f'frame_{cutoff}.parquet';sp=root/f'score_{cutoff}.parquet'
            copy_query(c,f'SELECT q.* FROM q JOIN chosen USING(row_id) WHERE cutoff_{cutoff} ORDER BY row_id',p)
            copy_query(c,f'SELECT s.* FROM s JOIN chosen USING(row_id) WHERE cutoff_{cutoff} ORDER BY row_id',sp)
    finally:c.close()
    rows=[];controls=frozen.r.X0+frozen.r.ENV+['env_supported']
    for cutoff in [3,5,10,20]:
        dest=root/f'fit_{cutoff}.json';fk=key([sk,cutoff,sha(root/f'frame_{cutoff}.parquet'),sha(root/f'score_{cutoff}.parquet')])
        if cached(dest,fk):fit=load(dest)
        else:fit=iv_fit(root/f'frame_{cutoff}.parquet',root/f'score_{cutoff}.parquet',controls);save(dest,fit);seal(dest,fk)
        rows.append(dict(cutoff=cutoff,sample='rebuilt_preminimum_frame',**fit));csv_out(run/'report/cutoff_robustness.csv',rows)
    refpath=run/'PRIVATE/iv/ladder_4.json'
    reference=load(refpath) if refpath.exists() else iv_fit(b['s0'],Path(b['parent'])/'scores_combined/S0.parquet',controls)
    reproduce(reference,4);rows.append(dict(cutoff=5,sample='certified_frozen_R9_reference',**reference))
    csv_out(run/'report/cutoff_robustness.csv',rows)
