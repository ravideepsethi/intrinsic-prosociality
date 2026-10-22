"""Recover pre-eligibility metadata and screen factual chronology before requests."""
from pathlib import Path
import recovery_util as u
from phase_bridge import *
import cached_inputs, cached_chronology, local_cache, phase100_recovery
from bounded_assembly import RiskIndex

def chronology_attempt(job):
    try:
        cached_chronology.chronology_job(job);return True
    except Exception as error:
        if type(error).__name__!='OutOfMemoryException':raise
        return False

def merge_sql(sources):
    fields=['game_id']+[f'CASE WHEN count(DISTINCT "{k}")=1 THEN min("{k}") END AS "{k}"' for k in ex.META_FIELDS]
    conflict=' OR '.join([f'count(DISTINCT "{k}")>1' for k in ex.META_FIELDS]+['bool_or(coalesce(cached_conflict_or_prior_flag,FALSE))'])
    return 'SELECT '+','.join(fields)+',('+conflict+') AS cached_conflict_or_prior_flag FROM ('+' UNION ALL '.join(sources)+') GROUP BY game_id'

def readiness():
    # Legacy membership is NOT permission to bypass the metadata checks.
    return original_plan.readiness_sql().replace("WHEN f.previous_frame THEN 'PREVIOUS_FRAME_REUSE'",'WHEN FALSE THEN \'PREVIOUS_FRAME_REUSE\'')

def legacy_master(a,root):
    prior=io.load(VENDOR/'comparison_original/evidence/prior_authority.json')
    line=a.project/'derived/replication/comparison_tests_v110_PRIVATE'/prior['comparison_run']/'lineage_PRIVATE.json'
    io.checked(line,prior['comparison_lineage_sha256'])
    source=a.project/'derived/replication/comparison_reconciled_v100_PRIVATE/20260907T013118Z_71e0e5c6_eb4091b7a862/master/comparison_frame.parquet'
    io.checked(source,io.load(line)['reconciled_master_sha256'])
    u.require(pq.ParquetFile(source).metadata.num_rows==1912023,'Legacy master count differs')
    def build(tmp):
        pf=pq.ParquetFile(source);mode=local_cache.adapter(pf.schema_arrow.names)
        # An unknown producer schema remains missing; never invent fields.
        cols=local_cache.parquet_columns(pf.schema_arrow.names,mode) if mode else []
        n=0
        with pq.ParquetWriter(tmp/'records.parquet',ex.metadata_schema(),compression='zstd') as w:
            if mode:
                for batch in pf.iter_batches(columns=cols,batch_size=32768,use_threads=False):
                    records=[local_cache.normalize_row(r,mode) for r in batch.to_pylist()];records=[r for r in records if r]
                    if records:w.write_table(pa.Table.from_pylist(records,schema=ex.metadata_schema()));n+=len(records)
        return dict(source_rows=1912023,normalized_rows=n,adapter=mode,source_sha256=io.sha(source))
    folder,info=stable_stage(root,a.conf,build,[source,line])
    u.save(a.run/'report/legacy_recovery.json',{k:info[k] for k in ('source_rows','normalized_rows','adapter','source_sha256')})
    return folder/'records.parquet'

def risk_screen(source,stream,out,conf):
    def build(tmp):
        risk=RiskIndex(arrays(io.read(stream,['recipient_id','archive_start_ms','anchor_ms'])))
        writer=None;n=0;finite=at_risk=calendar=0
        try:
            for batch in pq.ParquetFile(source).iter_batches(batch_size=131072,use_threads=False):
                t=pa.Table.from_batches([batch]);d=arrays(t);d['archive_start_ms']=d['utc_ms'];values=risk.query(d)
                supported=d['finite_A'].astype(bool);cal=d['utc_ms']+90*DAY<core.PANEL_END
                for name,v in [('at_risk_90',values['at_risk']),('anchor_tie',values['anchor_tie']),('earlier_started_not_yet_anchored',values['earlier_started_not_yet_anchored']),('calendar_support',cal)]:t=t.append_column(name,pa.array(v))
                if writer is None:writer=pq.ParquetWriter(tmp/'candidates.parquet',t.schema,compression='zstd')
                writer.write_table(t);n+=len(t);finite+=int(supported.sum());at_risk+=int((supported&values['at_risk']).sum());calendar+=int((supported&values['at_risk']&cal).sum())
        finally:
            if writer:writer.close()
        return dict(count_supported=n,finite_A=finite,after_rebuilt_cooldown=at_risk,after_start_calendar=calendar)
    return stable_stage(out,conf,build,[source,stream])

def cache_month(a,month,source,legacy,caches,quarantine,out):
    metadata=[(label,cached_inputs.metadata_for_month(path,month)) for label,path in caches]
    def build(tmp):
        c=io.conn(tmp/'spill',a.memory_gb-2,1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([source])+' WHERE month='+io.lit(month)+' AND finite_A AND at_risk_90 AND calendar_support')
            fields=','.join('m."'+k+'"' for k in ex.META_FIELDS)
            sources=[]
            for label,paths in metadata:
                c.execute('CREATE OR REPLACE VIEW m AS SELECT * FROM '+io.parq(paths))
                u.require(c.execute('SELECT count(*)-count(DISTINCT game_id) FROM m').fetchone()[0]==0,'Duplicate cached game in '+label)
                p=tmp/(label+'.parquet')
                io.copy(c,'SELECT m.game_id,'+fields+',m.cached_conflict_or_prior_flag FROM m SEMI JOIN f USING(game_id)',p)
                sources.append('SELECT * FROM '+io.parq([p]))
            sources.append('SELECT m.game_id,'+fields+",coalesce(m.record_errors,'')<>'' cached_conflict_or_prior_flag FROM "+io.parq([legacy])+' m SEMI JOIN f USING(game_id)')
            io.copy(c,merge_sql(sources),tmp/'metadata.parquet')
            c.execute('CREATE OR REPLACE VIEW m AS SELECT * FROM '+io.parq([tmp/'metadata.parquet']))
            c.execute('CREATE VIEW quarantine AS SELECT * FROM '+io.parq([quarantine]))
            sql='SELECT f.*,'+readiness()+' metadata_status,(f.game_id IN (SELECT game_id FROM quarantine)) certified_quarantine FROM f LEFT JOIN m USING(game_id)'
            io.copy(c,sql,tmp/'dispositions.parquet')
            counts=[dict(month=month,status=s,rows=n,legacy_rows=old) for s,n,old in c.execute('SELECT metadata_status,count(*),sum(previous_frame::BIGINT) FROM ('+sql+') GROUP BY 1 ORDER BY 1').fetchall()]
            u.save(tmp/'counts.json',counts);return dict(rows=sum(r['rows'] for r in counts))
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(out,a.conf,build,[source,legacy,quarantine]+[p for _,ps in metadata for p in ps])

def run(a):
    no_network();a.project_root=a.project;a.plan=None
    audited=u.load(u.parent(a)/'PRIVATE/COMPARISON_AUDIT_INPUTS.json')
    local=authenticate(a)
    import phase100_inputs
    phase=phase100_inputs.authenticate_checkpoint(a,local)
    u.require(local==audited['local'] and phase==audited['phase'],'Completed cache authority changed')
    oldq=phase100_recovery.bind_previous(a,local,phase)
    quarantine=Path(oldq['root'])/'quarantine/quarantined_records_PRIVATE.parquet'
    u.require(pq.ParquetFile(quarantine).metadata.num_rows==3,'Certified three-record quarantine changed')
    root=a.run/'PRIVATE/metadata';root.mkdir(exist_ok=True)
    legacy=legacy_master(a,root/'legacy')
    p=u.load(a.run/'PRIVATE/SCORE_PATHS.json')
    risk,info=risk_screen(p['candidates'],p['stream'],root/'risk',a.conf)
    u.save(a.run/'report/eligibility_before_metadata.json',{k:info[k] for k in ('count_supported','finite_A','after_rebuilt_cooldown','after_start_calendar')})
    caches=[('original',local['manifest']['original_cached_metadata']),('local_first',local['metadata']),('phase100',phase['metadata'])]
    folders=[];counts=[]
    for month in ex.MONTHS:
        folder,_=cache_month(a,month,risk/'candidates.parquet',legacy,caches,quarantine,root/'months'/month)
        folders.append(folder);counts+=u.load(folder/'counts.json');u.log('Cache reconciliation '+month)
    u.save(a.run/'report/cache_disposition.json',counts)
    def prep(tmp):
        c=io.conn(tmp/'spill',a.memory_gb-2,1)
        try:
            io.copy(c,"SELECT row_id,game_id,utc_ms archive_start_ms,recipient_id,opponent_id,FALSE previous_frame FROM "+io.parq([f/'dispositions.parquet' for f in folders])+" WHERE metadata_status<>'CACHED_NONPOOL' AND NOT certified_quarantine ORDER BY row_id",tmp/'queries.parquet')
            return dict(rows=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows)
        finally:finish_connection(c,tmp/'spill')
    qp,qi=stable_stage(root/'chronology_queries',a.conf,prep,[f/'dispositions.parquet' for f in folders])
    u.save(a.run/'PRIVATE/METADATA_PATHS.json',dict(months=[str(f) for f in folders],queries=str(qp/'queries.parquet'),quarantine=str(quarantine),chronology_rows=qi['rows']))

def chronology(a):
    no_network();root=a.run/'PRIVATE/chronology';root.mkdir(exist_ok=True)
    p=u.load(a.run/'PRIVATE/METADATA_PATHS.json');q=Path(p['queries'])
    if p['chronology_rows']:
        h=cached_inputs.research_inputs(a.project,min(a.workers,2))
        inventory=root/'SOURCE_INVENTORY_PRIVATE.json'
        if inventory.exists():u.require(u.load(inventory)==h['chron'],'Canonical chronology signatures changed since first run')
        else:u.save(inventory,h['chron'])
        prepared,info=cached_chronology.prepare_chronology(q,root/'prepared',a.conf,a.memory_gb-2)
        jobs=[]
        for rec in h['chron']:
            if rec['minimum'] is not None and rec['minimum']>info['latest_start']:continue
            jobs.append(dict(rec,people=str(prepared/'people.parquet'),pairs=str(prepared/'pairs.parquet'),focal=str(prepared/'focal.parquet'),latest=info['latest_start'],output=str(root/'parts'/f'{rec["file_index"]:04}'),conf=a.conf,memory=3.5))
        u.log(f'Chronology: {len(jobs)} source files; {sum(j["rows"] for j in jobs):,} source rows. Throughput ETA will follow completed files.')
        # Frozen scan retains factual author games. Two workers fit the 11 GiB plan.
        import concurrent.futures as cf,multiprocessing as mp,time
        started=time.monotonic();done_rows=0
        retry=[]
        with cf.ProcessPoolExecutor(max_workers=min(a.workers,2),mp_context=mp.get_context('spawn')) as pool:
            pending={pool.submit(chronology_attempt,j):j for j in jobs}
            for future in cf.as_completed(pending):
                if not future.result():retry.append(pending[future]);continue
                done_rows+=pending[future]['rows'];elapsed=time.monotonic()-started
                remaining=sum(j['rows'] for j in jobs)-done_rows
                u.log(f'Chronology {done_rows:,}/{sum(j["rows"] for j in jobs):,} rows; rough remaining ETA {elapsed*remaining/max(1,done_rows)/3600:.1f} h (file mix and resumed stages affect rate)')
        for job in retry:
            u.log('Retrying one chronology file serially with 8 GiB DuckDB memory')
            cached_chronology.chronology_job(dict(job,memory=8.))
        parts=[Path(j['output']) for j in jobs]
        folder,ci=cached_chronology.merge_chronology(q,prepared,parts,root/'combined',a.conf,a.memory_gb-2,1)
    else:
        def empty(tmp):
            pq.write_table(pa.table({'row_id':pa.array([],type=pa.int64()),'eligible_main':pa.array([],type=pa.bool_()),'first_observed_pair':pa.array([],type=pa.bool_()),'pre_games_30d':pa.array([],type=pa.int64())}),tmp/'features.parquet');return dict(rows=0,classifications=[])
        folder,ci=stable_stage(root/'combined',a.conf,empty,[q])
    u.save(a.run/'report/chronology.json',{k:ci[k] for k in ('rows','classifications')})
    def plan(tmp):
        c=io.conn(tmp/'spill',a.memory_gb-2,1)
        try:
            c.execute('CREATE VIEW d AS SELECT * FROM '+io.parq([Path(f)/'dispositions.parquet' for f in p['months']]))
            c.execute('CREATE VIEW x AS SELECT * FROM '+io.parq([folder/'features.parquet']))
            u.require(c.execute('SELECT count(*) FROM d JOIN x USING(row_id)').fetchone()[0]==p['chronology_rows'],'Chronology join changed screened denominator')
            io.copy(c,'SELECT d.*,x.* EXCLUDE(row_id) FROM d LEFT JOIN x USING(row_id)',tmp/'screened_candidates.parquet')
            pred="eligible_main AND first_observed_pair AND NOT certified_quarantine"
            c.execute('CREATE VIEW retained AS SELECT * FROM '+io.parq([tmp/'screened_candidates.parquet'])+' WHERE '+pred)
            io.copy(c,'SELECT * FROM retained',tmp/'eligible_candidates.parquet')
            n=io.copy(c,"SELECT game_id,utc_ms,speed_partition FROM retained WHERE metadata_status NOT IN ('CACHED_POOL_METADATA','CACHED_NONPOOL') ORDER BY retrieval_rank,game_id",tmp/'targets.parquet')
            u.require(c.execute('SELECT count(*)-count(DISTINCT game_id) FROM '+io.parq([tmp/'targets.parquet'])).fetchone()[0]==0,'Duplicate API target')
            kept=c.execute('SELECT count(*) FROM retained').fetchone()[0]
            return dict(chronology_input_rows=p['chronology_rows'],chronology_supported_candidates=kept,API_targets=n,cached_pool_survivors=kept-n,quarantined_rows=c.execute('SELECT count(*) FROM d WHERE certified_quarantine').fetchone()[0],final_analytic_sample_size=None,scope='90-day comparison entry and ordinary-ending placebo metadata',selection_uses_Patron_or_followup_outcomes=False)
        finally:finish_connection(c,tmp/'spill')
    pf,pi=stable_stage(a.run/'PRIVATE/requests',a.conf,plan,[folder/'features.parquet']+[Path(f)/'dispositions.parquet' for f in p['months']])
    u.save(a.run/'report/request_plan.json',{k:v for k,v in pi.items() if k not in ('files','config_sha256')})
    u.save(a.run/'PRIVATE/REQUEST_PLAN.json',dict(targets=str(pf/'targets.parquet'),target_sha256=io.sha(pf/'targets.parquet'),target_rows=pi['API_targets'],eligible_candidates=str(pf/'eligible_candidates.parquet'),chronology=str(folder/'features.parquet')))

if __name__=='__main__':
    a=u.parser().parse_args()
    with u.pulse('Offline '+a.mode):
        if a.mode=='metadata':run(a)
        elif a.mode=='chronology':chronology(a)
        else:raise ValueError(a.mode)
