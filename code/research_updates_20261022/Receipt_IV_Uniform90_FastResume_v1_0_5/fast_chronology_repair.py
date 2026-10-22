"""Validate scan keys, repair affected scans, and partition physical Arrow keys.

No NULL key is filled, discarded or assigned to an arbitrary bucket. Original
scans remain unchanged. Repairs use a strict-time window sweep, without ASOF,
and verify every added or changed candidate against independent raw-game counts.
Old identified keys must remain covered; original pair summaries must agree.
"""
from fast_bootstrap import *
import repair_chronology as merge
import pyarrow.compute as pc
io=frozen.r.io
REQUIRED_CANDIDATES=['sample_row','role','focal_time_count','focal_matches','pre_games_30d']
CANDIDATE_FIELDS=['sample_row','role','prev_t','prev_count','prev_gid','prev_opponent',
                  'focal_time_count','focal_matches','pre_games_30d']

def null_audit(path,fields):
    """Use complete Parquet null statistics, reading a field if stats are absent."""
    f=pq.ParquetFile(path);schema=f.schema_arrow;answer={}
    for name in fields:
        index=schema.get_field_index(name);require(index>=0,'Missing chronology field '+name+' in '+str(path))
        counts=[]
        for g in range(f.metadata.num_row_groups):
            stats=f.metadata.row_group(g).column(index).statistics
            if stats is None or stats.null_count is None:counts=None;break
            counts.append(stats.null_count)
        if counts is None:
            answer[name]=sum(b.column(0).null_count for b in f.iter_batches(columns=[name],batch_size=65536,use_threads=False))
        else:answer[name]=sum(counts)
    return dict(rows=f.metadata.num_rows,nulls=answer,invalid=any(answer.values()))

def partition_files(paths,key,path,**kwargs):
    """Keep the frozen bounded writer; calculate buckets from physical integers.

    This also handles a SQL/Arrow expression-path problem when source keys are
    actually intact. Missing physical keys stop here rather than being dropped.
    """
    paths=list(map(Path,paths));require(bool(paths),'No input files for chronology partition')
    buckets=kwargs.get('buckets',merge.BUCKETS);schema=pq.ParquetFile(paths[0]).schema_arrow
    require(schema.get_field_index(key)>=0,'Missing chronology partition key '+key)
    require(schema.get_field_index('bucket')<0,'Unexpected bucket field in source scan')
    extended=schema.append(pa.field('bucket',pa.int64()))
    def batches(batch_size):
        for p in paths:
            f=pq.ParquetFile(p);require(f.schema_arrow.equals(schema,check_metadata=False),'Chronology scan schema changed: '+str(p))
            for b in f.iter_batches(batch_size=batch_size,use_threads=False):
                values=b.column(b.schema.get_field_index(key))
                require(values.null_count==0,'Missing physical chronology key '+key+' in '+str(p))
                ids=values.to_numpy(zero_copy_only=False)
                require(np.issubdtype(ids.dtype,np.integer) and (not len(ids) or ids.min()>=0),'Invalid chronology key in '+str(p))
                yield pa.RecordBatch.from_arrays(list(b.columns)+[pa.array((ids%buckets).astype(np.int64))],schema=extended)
    class Source:
        def execute(self,sql):return self
        def fetch_record_batch(self,rows_per_batch):return pa.RecordBatchReader.from_batches(extended,batches(rows_per_batch))
    return merge.partition(Source(),'physical Arrow chronology reader',path,**kwargs)

def window_lookups(c):
    """Strict predecessors at upper and lower endpoints, including exact ties.

    Query endpoints (event=0) precede moments (event=1) at the same millisecond.
    Thus the carried timestamp is strictly less than the endpoint. Query ties
    do not alter the state and every sample/role is retained independently.
    """
    c.execute('''CREATE TEMP TABLE bounds AS
      SELECT sample_row,role,user_id,archive_start_ms t,1 bound FROM role_rows
      UNION ALL
      SELECT sample_row,role,user_id,archive_start_ms-'''+str(30*DAY)+''' t,0 bound FROM role_rows WHERE role=0''')
    c.execute('''CREATE TEMP TABLE lookups AS WITH timeline AS (
      SELECT user_id,utc_ms AS t,1 AS event_rank,utc_ms AS moment_t,NULL::BIGINT AS sample_row,NULL::INTEGER AS role,NULL::INTEGER AS bound FROM moments
      UNION ALL SELECT user_id,t,0,NULL::BIGINT,sample_row,role,bound FROM bounds
      ), carried AS (
        SELECT *,max(moment_t) OVER(PARTITION BY user_id ORDER BY t,event_rank ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) previous_t FROM timeline
      ) SELECT sample_row,role,max(previous_t) FILTER(WHERE bound=1) hi_t,
          max(previous_t) FILTER(WHERE bound=0) lo_t
        FROM carried WHERE event_rank=0 GROUP BY sample_row,role''')
    ensure(c,'SELECT count(*) FROM ((SELECT sample_row,role FROM role_rows EXCEPT ALL SELECT sample_row,role FROM lookups) UNION ALL (SELECT sample_row,role FROM lookups EXCEPT ALL SELECT sample_row,role FROM role_rows))','Window sweep changed query-role coverage')

def candidate_sql():
    return '''SELECT r.sample_row,r.role,p.utc_ms prev_t,p.multiplicity prev_count,p.gid prev_gid,p.opponent_id prev_opponent,
      coalesce(x.multiplicity,0)::BIGINT focal_time_count,coalesce(f.matches,0)::BIGINT focal_matches,
      CASE WHEN r.role=0 THEN coalesce(p.cumulative,0)-coalesce(lo.cumulative,0) ELSE 0 END::BIGINT pre_games_30d
      FROM role_rows r JOIN lookups l ON r.sample_row=l.sample_row AND r.role=l.role
      LEFT JOIN moments p ON r.user_id=p.user_id AND l.hi_t=p.utc_ms
      LEFT JOIN moments lo ON r.user_id=lo.user_id AND l.lo_t=lo.utc_ms
      LEFT JOIN moments x ON r.user_id=x.user_id AND r.archive_start_ms=x.utc_ms
      LEFT JOIN found_focal f ON r.game_id=f.game_id'''

def repair_scan(job,target,parent_conf):
    original=Path(job['output']);require(io.complete(original,job['conf']) is not None,'Original scan is not authenticated')
    require(io.sig(job['path'])==job['signature'],'Raw chronology signature changed')
    identity=key([parent_conf,'strict_time_window_scan_repair_with_raw_verification_v104',sha(original/'_DONE.json')])
    dependencies=[original/'candidates.parquet',original/'pairs.parquet']+[Path(job[k]) for k in ('path','people','pairs','focal','roles')]
    def build(tmp):
        c=io.conn(tmp/'spill',4.,1)
        try:
            roles=parq([job['roles']]);source=parq([job['path']])
            ensure(c,'SELECT count(*) FROM '+roles+' WHERE sample_row IS NULL OR role IS NULL OR user_id IS NULL OR archive_start_ms IS NULL','Prepared query roles contain missing keys')
            c.execute('CREATE VIEW wanted AS SELECT * FROM '+parq([job['people']]))
            c.execute('CREATE TEMP TABLE e AS SELECT game_id,utc_ms,white_id,black_id FROM '+source+f" WHERE utc_ms>0 AND utc_ms<={job['latest']} AND white_id>=0 AND black_id>=0 AND white_id<4294967296 AND black_id<4294967296 AND white_id<>black_id AND (white_id IN (SELECT user_id FROM wanted) OR black_id IN (SELECT user_id FROM wanted))")
            c.execute('CREATE TEMP TABLE found_focal AS SELECT e.game_id,count(*)::BIGINT matches FROM e JOIN '+parq([job['focal']])+''' q ON e.game_id=q.game_id AND e.utc_ms=q.archive_start_ms
              AND least(e.white_id,e.black_id)=least(q.recipient_id,q.opponent_id)
              AND greatest(e.white_id,e.black_id)=greatest(q.recipient_id,q.opponent_id) GROUP BY 1''')
            pair='least(white_id,black_id)::UBIGINT*4294967296+greatest(white_id,black_id)::UBIGINT'
            copy_query(c,'SELECT '+pair+' pair_key,min(utc_ms)::BIGINT first_t FROM e SEMI JOIN '+parq([job['pairs']])+' p ON '+pair+'=p.pair_key GROUP BY 1',tmp/'pairs.parquet')
            c.execute('''CREATE TEMP TABLE ep AS
              SELECT e.game_id,e.utc_ms,e.white_id user_id,e.black_id opponent_id,w.minimum_start FROM e JOIN wanted w ON e.white_id=w.user_id AND e.utc_ms<=w.maximum_start
              UNION ALL SELECT e.game_id,e.utc_ms,e.black_id,e.white_id,w.minimum_start FROM e JOIN wanted w ON e.black_id=w.user_id AND e.utc_ms<=w.maximum_start''')
            c.execute(f'CREATE TEMP TABLE older AS SELECT user_id,max(utc_ms) old_t FROM ep WHERE utc_ms<minimum_start-{30*DAY} GROUP BY 1')
            c.execute(f'''CREATE TEMP TABLE moments AS WITH counts AS (
              SELECT ep.user_id,utc_ms,count(*)::BIGINT multiplicity,min(game_id) gid,min(opponent_id)::BIGINT opponent_id
              FROM ep LEFT JOIN older USING(user_id) WHERE utc_ms>=minimum_start-{30*DAY} OR utc_ms=old_t GROUP BY ep.user_id,utc_ms
              ) SELECT *,sum(multiplicity) OVER(PARTITION BY user_id ORDER BY utc_ms ROWS UNBOUNDED PRECEDING)::BIGINT cumulative FROM counts''')
            c.execute('CREATE TEMP TABLE present AS SELECT user_id,min(utc_ms) minimum_t FROM moments GROUP BY 1')
            c.execute('CREATE TEMP TABLE role_rows AS SELECT r.* FROM '+roles+' r JOIN present p ON r.user_id=p.user_id AND r.archive_start_ms>=p.minimum_t')
            ensure(c,'SELECT count(*) FROM (SELECT sample_row,role FROM role_rows GROUP BY 1,2 HAVING count(*)<>1)','Duplicate prepared query-role key')
            expected=c.execute('SELECT count(*) FROM role_rows').fetchone()[0]
            c.execute('DROP TABLE ep');c.execute('DROP TABLE e')
            window_lookups(c);copy_query(c,candidate_sql(),tmp/'candidates.parquet')
            audit=null_audit(tmp/'candidates.parquet',REQUIRED_CANDIDATES)
            require(not audit['invalid'] and audit['rows']==expected,'Repaired scan failed key/row checks')
            ensure(c,'SELECT count(*) FROM '+parq([tmp/'candidates.parquet'])+' WHERE pre_games_30d<0 OR role NOT IN (0,1)','Invalid repaired chronology value')
            ensure(c,'SELECT count(*) FROM (SELECT sample_row,role FROM '+parq([tmp/'candidates.parquet'])+' GROUP BY 1,2 HAVING count(*)<>1)','Repaired chronology duplicates a role')
            for table in ('lookups','bounds','moments','present','role_rows','found_focal','older'):
                c.execute('DROP TABLE '+table)
            from fast_chronology_oracle import audit_candidates
            candidate_audit=audit_candidates(c,job,original,tmp)
            # Pair minima are not the failing calculation. Keep the strict guard.
            left='SELECT pair_key,first_t FROM '+parq([original/'pairs.parquet'])
            right='SELECT pair_key,first_t FROM '+parq([tmp/'pairs.parquet'])
            ensure(c,'SELECT count(*) FROM ('+left+' EXCEPT ALL '+right+')','Repair changed an original pairs row')
            ensure(c,'SELECT count(*) FROM ('+right+' EXCEPT ALL '+left+')','Repair altered an intact original pairs table')
            preserved=dict(candidates=candidate_audit,pairs=dict(all_original_rows_preserved=True))
            require(io.sig(job['path'])==job['signature'],'Chronology source changed during repair')
            save(tmp/'repair_audit.json',dict(algorithm='strict_time_window_scan_repair_with_raw_verification_v104',original_receipt_sha256=sha(original/'_DONE.json'),
                source_file_index=job['file_index'],expected_query_roles=expected,tables=preserved,
                missing_keys_filled=False,analytical_query_roles_dropped=False,distinct_raw_sources_reread=1,
                raw_passes=2 if candidate_audit['raw_verification'] is not None else 1,original_files_modified=False))
            return dict(rows=expected,file_index=job['file_index'],safe_window_lookup=True)
        finally:chron.finish_connection(c,tmp/'spill')
    out,_=stage(target,identity,build,dependencies)
    return out

def validated_parts(jobs,root,conf,report):
    """Inspect all scans before merging; repair only scans with invalid keys."""
    root=Path(root);report=Path(report);outputs=[];audit=[];repaired=0;began=time.monotonic()
    for index,job in enumerate(jobs):
        original=Path(job['output'])
        checks={name:null_audit(original/(name+'.parquet'),fields) for name,fields in
          [('candidates',REQUIRED_CANDIDATES),('pairs',['pair_key','first_t'])]}
        bad=any(x['invalid'] for x in checks.values());out=original
        if bad:
            log('Repairing chronology scan '+str(job['file_index'])+' with missing keys; preserving the original scan. '+str({k:v['nulls'] for k,v in checks.items()}))
            with heartbeat('Repairing chronology scan '+str(job['file_index'])):
                try:out=repair_scan(job,root/original.name,conf)
                except Exception as error:
                    save(report/'chronology_repair104_failure.json',dict(file_index=job['file_index'],checks=checks,
                        error=str(error).split('; audit at ')[0],original_files_modified=False,repair_accepted=False))
                    raise
            repaired+=1
        outputs.append(out);audit.append(dict(file_index=job['file_index'],checks=checks,repaired=bad,
            repair_receipt_sha256=sha(out/'_DONE.json') if bad else None,
            repair_details=load(out/'repair_audit.json') if bad else None))
        if (index+1)%100==0 or index+1==len(jobs):log(f'Chronology key validation {index+1}/{len(jobs)}; repaired {repaired}; {(time.monotonic()-began)/60:.1f} min')
    save(report/'chronology_key_repair104.json',dict(scans=len(jobs),repaired_scans=repaired,intact_scans_reused=len(jobs)-repaired,
        original_files_modified=False,null_keys_filled=False,candidate_rows_discarded=False,partition_keys_computed_from_physical_integers=True,
        cause='The log proves a null computed bucket. This audit distinguishes missing source fields from an expression-reader problem; no unverified engine-specific root cause is asserted.',checks=audit))
    (report/'chronology_repair104_failure.json').unlink(missing_ok=True)
    return outputs
