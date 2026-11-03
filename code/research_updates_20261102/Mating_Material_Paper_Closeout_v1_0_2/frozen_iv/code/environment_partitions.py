"""Bounded execution of the frozen environment-cache definitions.

All records for a person go to one of 128 partitions. Therefore every
person/partner/month key, including copies in different caches, is checked
together. Partitioning changes neither eligibility nor the cache priority.
"""
from bootstrap import *
import pyarrow.compute as pc
import stream_frames

PARTITIONS=128
BATCH=65536
KEYS=['person','partner','month_code']
PRIORITY='_cache_priority'


def quoted(name):return '"'+name.replace('"','""')+'"'


def concatenate(paths,target,order=None,memory=3.):
    """Only narrow key products need a global order; payloads are streamed."""
    if order:
        db=connect(target.parent/'sort_spill',memory)
        try:copy(db,'SELECT * FROM '+c.parq(paths)+' ORDER BY '+','.join(map(quoted,order)),target)
        finally:db.close()
        return
    schema=pq.ParquetFile(paths[0]).schema_arrow
    with pq.ParquetWriter(target,schema,compression='zstd',use_dictionary=False) as writer:
        for p in paths:
            with pq.ParquetFile(p) as file:
                require(file.schema_arrow.equals(schema,check_metadata=False),'Partition output schemas differ')
                for batch in file.iter_batches(batch_size=BATCH,use_threads=False):
                    writer.write_batch(batch,row_group_size=BATCH)


def partition(paths,root,conf,columns=None,rename=None,priority=False,nparts=PARTITIONS):
    """One input pass, no hash aggregation; at most 128 open output writers."""
    paths=[Path(p) for p in paths];rename=rename or {}
    require(paths and 1<=nparts<=128,'Invalid environment partition request')
    def build(tmp):
        schemas=[]
        for p in paths:
            schema=pq.ParquetFile(p).schema_arrow
            selected=schema.names if columns is None else columns
            schemas.append(pa.schema([schema.field(k).with_name(rename.get(k,k)) for k in selected]))
        require(all(s.names==schemas[0].names for s in schemas),'Environment cache columns differ')
        schema=pa.unify_schemas(schemas,promote_options='permissive')
        require('person' in schema.names and pa.types.is_integer(schema.field('person').type),
                'Environment person key must be integer')
        require(PRIORITY not in schema.names,'Reserved cache-priority column exists')
        output_schema=schema.append(pa.field(PRIORITY,pa.int64())) if priority else schema
        writers=[pq.ParquetWriter(tmp/f'{k:03}.parquet',output_schema,compression='zstd',
                                  use_dictionary=False) for k in range(nparts)]
        counts=[0]*nparts;source_counts=[];last=time.monotonic()
        try:
            for source_index,p in enumerate(paths):
                count=0
                with pq.ParquetFile(p) as file:
                    for batch in file.iter_batches(batch_size=BATCH,columns=columns,use_threads=False):
                        table=pa.Table.from_batches([batch])
                        table=table.rename_columns([rename.get(k,k) for k in table.column_names]).cast(schema,safe=True)
                        # Null keys, if present, remain grouped together exactly as SQL GROUP BY.
                        person=pc.fill_null(table['person'],0).to_numpy()
                        bucket=np.remainder(person,nparts).astype(np.int16)
                        if priority:table=table.append_column(PRIORITY,pa.array(np.full(len(person),source_index,np.int64)))
                        order=np.argsort(bucket,kind='stable');table=table.take(pa.array(order));bucket=bucket[order]
                        cuts=np.r_[0,np.flatnonzero(bucket[1:]!=bucket[:-1])+1,len(bucket)]
                        for lo,hi in zip(cuts[:-1],cuts[1:]):
                            if hi==lo:continue
                            k=int(bucket[lo]);writers[k].write_table(table.slice(int(lo),int(hi-lo)),row_group_size=BATCH)
                            counts[k]+=int(hi-lo)
                        count+=len(person)
                        if time.monotonic()-last>=30:
                            log(f'Environment partitioning: input {source_index+1}/{len(paths)}, {count:,} rows')
                            last=time.monotonic()
                require(count==rows(p),'Environment partitioning changed source count')
                source_counts.append(count)
        finally:
            for writer in writers:writer.close()
        return dict(rows=sum(counts),bucket_rows=counts,source_rows=source_counts,partitions=nparts)
    return stage(root,conf,build,paths)


def reuse_stage(root,conf,deps,filename):
    if not (root/'_DONE.json').exists():return None
    def forbidden(tmp):raise RuntimeError('Completed environment stage unexpectedly requested a rebuild')
    return stage(root,conf,forbidden,deps)[0]/filename


def disagreement_tests(schema):
    tests=[]
    for field in schema:
        if field.name in KEYS or field.name==PRIORITY:continue
        x=quoted(field.name)
        if pa.types.is_floating(field.type):tests.append(f'(max({x})-min({x})>2e-12)')
        else:
            # Equivalent to count(DISTINCT x)>1 for the ordered scalar cache fields,
            # but does not allocate a distinct-value hash table per column.
            tests.append(f'(min({x}) IS DISTINCT FROM max({x}))')
        tests.append(f'(count({x})>0 AND count({x})<count(*))')
    return tests


def pool_rates(a,run,conf,b,nparts=PARTITIONS):
    paths=[Path(p) for p in b['primary']['known_rates']];root=run/'PRIVATE/rate_pool'
    cached=reuse_stage(root,conf,paths,'rates.parquet')
    if cached:return cached
    prepared,info=partition(paths,run/'PRIVATE/rate_pool_v106_inputs',conf,priority=True,nparts=nparts)
    outputs=[]
    for k in range(nparts):
        source=prepared/f'{k:03}.parquet'
        def build(tmp,source=source):
            db=connect(tmp,min(a.memory_gb-2,3.))
            try:
                view(db,'r',source);schema=pq.ParquetFile(source).schema_arrow
                tests=disagreement_tests(schema)
                query='SELECT count(*) FROM (SELECT '+','.join(KEYS)+' FROM r GROUP BY '+','.join(KEYS)
                if tests:query+=' HAVING '+' OR '.join(tests)
                else:query+=' HAVING FALSE'
                c.ensure(db,query+')','Existing ENV caches disagree')
                copy(db,'SELECT * EXCLUDE('+PRIORITY+') FROM r QUALIFY row_number() OVER(PARTITION BY '+','.join(KEYS)+' ORDER BY '+PRIORITY+')=1 ORDER BY '+','.join(KEYS),tmp/'rates.parquet')
                return dict(rows=rows(tmp/'rates.parquet'))
            finally:db.close()
        part,_=stage(run/'PRIVATE/rate_pool_v106_checked'/f'{k:03}',conf,build,[source])
        outputs.append(part/'rates.parquet')
        if (k+1)%16==0:log(f'Environment cache agreement: {k+1}/{nparts} partitions verified')
    def finish(tmp):
        concatenate(outputs,tmp/'rates.parquet')
        return dict(rows=sum(rows(p) for p in outputs))
    result,_=stage(root,conf,finish,paths)
    save(run/'report/RATE_POOL_V106.json',dict(input_rows=info['rows'],unique_keys=rows(result/'rates.parquet'),
        partitions=nparts,largest_input_partition=max(info['bucket_rows']),
        tolerance=2e-12,null_checks_preserved=True,cache_priority_preserved=True))
    return result/'rates.parquet'


def missing_requests(inputs,oldrates,root,conf,memory,nparts=PARTITIONS):
    """Same complete request universe, null rules and missing-key anti join."""
    root=Path(root)
    q,_=partition(inputs,root/'query_parts_v106',conf,
        columns=['opponent_id','recipient_id','month_code'],
        rename={'opponent_id':'person','recipient_id':'partner'},nparts=nparts)
    old,_=partition([oldrates],root/'known_key_parts_v106',conf,columns=KEYS,nparts=nparts)
    outputs=[];total=0;missing=0;months=set()
    for k in range(nparts):
        qp=q/f'{k:03}.parquet';op=old/f'{k:03}.parquet'
        def build(tmp,qp=qp,op=op):
            db=connect(tmp,min(memory,3.))
            try:
                view(db,'q',qp);view(db,'b',op)
                c.ensure(db,'SELECT count(*) FROM (SELECT person,partner,month_code,count(*) n FROM b GROUP BY ALL HAVING n<>1)','Duplicate archived ENV keys')
                copy(db,'SELECT DISTINCT * FROM q ORDER BY person,partner,month_code',tmp/'all.parquet')
                view(db,'a',tmp/'all.parquet')
                copy(db,'SELECT a.* FROM a ANTI JOIN b USING(person,partner,month_code) ORDER BY person,partner,month_code',tmp/'missing.parquet')
                view(db,'m',tmp/'missing.parquet')
                for label,v in [('all','a'),('missing','m')]:
                    copy(db,'SELECT DISTINCT person FROM '+v+' ORDER BY person',tmp/(label+'_people.parquet'))
                    copy(db,'SELECT DISTINCT person,partner FROM '+v+' ORDER BY person,partner',tmp/(label+'_pairs.parquet'))
                return dict(all_requests=rows(tmp/'all.parquet'),missing_requests=rows(tmp/'missing.parquet'),
                            months=[r[0] for r in db.execute('SELECT DISTINCT month_code FROM a').fetchall()])
            finally:db.close()
        out,info=stage(root/'checked_parts_v106'/f'{k:03}',conf,build,[qp,op]);outputs.append(out)
        total+=info['all_requests'];missing+=info['missing_requests'];months.update(info['months'])
    er=c.frozen.r.env_rates
    require(all(m is not None and 0<=m<len(er.STARTS) for m in months),'Unknown month code')
    windows=[dict(month_code=m,lo=int(er.STARTS[m])-97*DAY,hi=int(er.STARTS[m])-7*DAY,
                  complete=int(er.STARTS[m])-97*DAY>=int(er.STARTS[0]) and int(er.STARTS[m])-7*DAY<=er.core.PANEL_END) for m in sorted(months)]
    window_schema=pa.schema([('month_code',pa.int64()),('lo',pa.int64()),('hi',pa.int64()),('complete',pa.bool_())])
    def combine(tmp,label):
        for name,suffix,order in [('requests','',KEYS),('people','_people',['person']),('pairs','_pairs',['person','partner'])]:
            concatenate([p/(label+suffix+'.parquet') for p in outputs],tmp/(name+'.parquet'),order,min(memory,3.))
        pq.write_table(pa.Table.from_pylist(windows,schema=window_schema),tmp/'windows.parquet')
    def all_build(tmp):
        combine(tmp,'all');return dict(windows=windows,request_rows=total)
    all_root,_=stage(root/'all',conf,all_build,inputs)
    def missing_build(tmp):
        combine(tmp,'missing');return dict(missing_requests=missing,all_requests=total,windows=windows)
    result,info=stage(root/'missing',conf,missing_build,[all_root/'requests.parquet',oldrates])
    log(f'Environment requests: {total:,} unique; {missing:,} need factual histories')
    return result,info


def environment_rates(a,run,conf,b,source):
    """Frozen factual rate producer, with bounded request checks and no unused wide attachment."""
    p=c.primary;root=run/'PRIVATE/wider/environment';root.mkdir(parents=True,exist_ok=True)
    require(len(b['known_rates'])==1,'Environment inputs must first pass the complete pooled-cache check')
    old=root/'known_rates.parquet';ck=p.key([conf,'known_rates',[p.sha(x) for x in b['known_rates']]])
    if not p.cached(old,ck):
        db=connect(root/'spill_known',3.)
        try:copy(db,'SELECT * FROM '+c.parq(b['known_rates']),old);p.seal(old,ck)
        finally:db.close()
    req,info=missing_requests([source],old,root/'requests',conf,a.memory_gb-2);rates=[old]
    if info['missing_requests']:
        binding=b['bound']['binding'];e=Path(binding['environment']['root']);ec=binding['environment']['conf'];panels=[]
        for folder in sorted((e/'rate_panels').iterdir()):
            if not (folder/'_DONE.json').exists():continue
            path=p.frozen.r9_inputs.stage_file(folder/'events.parquet',ec);meta=read(folder/'_DONE.json')
            panels.append(dict(path=str(path),minimum=meta['minimum'],maximum=meta['maximum']))
        jobs,scan=p.frozen.r.env_rates.chronology_jobs(binding['source']['chron'],info['windows'],panels,req,root/'parts',conf,3.)
        for job in jobs:job.update(authors=binding['author_ids'],memory=3.,memory_gb=4.5)
        result=p.frozen.runtime.mapped(p.inputs.env_attempt,jobs,min(a.workers,2),a.memory_gb,'Only missing wider-cohort ENV histories',50,90)
        retry=[dict(j,memory=8.,memory_gb=9.) for j,v in zip(jobs,result) if not v['ok']]
        if retry:
            result=p.frozen.runtime.mapped(p.inputs.env_attempt,retry,1,a.memory_gb,'Serial ENV memory retries',20,90)
            require(all(v['ok'] for v in result),'ENV serial memory retry failed')
        fresh,_=p.frozen.r.env_rates.combine(req,[j['output'] for j in jobs],[x['path'] for x in panels],root/'fresh',conf,a.memory_gb-2,1)
        rates.append(fresh/'rates.parquet');info['scan']=scan
    def union(tmp):
        concatenate(rates,tmp/'rates.parquet');return dict(rows=rows(tmp/'rates.parquet'))
    out,_=stage(root/'combined',conf,union,rates)
    save(run/'report/wider_environment.json',p.frozen.public(info))
    return out/'rates.parquet'


def correct_rates(a,run,conf,rates,removed,nparts=PARTITIONS):
    root=run/'PRIVATE/material_environment'
    cached=reuse_stage(root,conf,[rates,removed],'rates.parquet')
    if cached:return cached,read(root/'_DONE.json')
    prepared,_=partition([rates],run/'PRIVATE/material_environment_v106_inputs',conf,nparts=nparts)
    outputs=[]
    for k in range(nparts):
        source=prepared/f'{k:03}.parquet'
        def build(tmp,source=source):
            db=connect(tmp,min(a.memory_gb-2,3.))
            try:
                view(db,'r',source);view(db,'d',removed)
                db.execute('''CREATE VIEW e AS SELECT i person,j counterpart,start_ms,end_ms,1::BIGINT own,0::BIGINT chooser FROM d
                    UNION ALL SELECT j,i,start_ms,end_ms,0,1 FROM d''')
                copy(db,'''WITH v AS (
                    SELECT r.person,r.partner,r.month_code,coalesce(sum(e.own),0)::BIGINT drop_own,
                    coalesce(sum(e.chooser),0)::BIGINT drop_chooser FROM r LEFT JOIN e
                    ON r.complete AND r.person=e.person AND r.partner<>e.counterpart AND e.start_ms>=r.lo AND e.start_ms<r.hi AND e.end_ms<r.hi GROUP BY r.person,r.partner,r.month_code
                    ), fixed AS (
                    SELECT r.* EXCLUDE(own,chooser,opponent_observed_disconnect_rate,opponent_observed_chooser_rate),
                    r.own-v.drop_own AS own,r.chooser-v.drop_chooser AS chooser FROM r JOIN v USING(person,partner,month_code)
                    ) SELECT *,CASE WHEN environment_supported THEN own::DOUBLE/games ELSE NULL END opponent_observed_disconnect_rate,
                    CASE WHEN environment_supported THEN chooser::DOUBLE/games ELSE NULL END opponent_observed_chooser_rate FROM fixed''',tmp/'rates.parquet')
                view(db,'f',tmp/'rates.parquet');c.ensure(db,'SELECT count(*) FROM f WHERE games<0 OR own<0 OR chooser<0 OR own+chooser>games','Invalid corrected environment counts')
                require(rows(source)==rows(tmp/'rates.parquet'),'Environment correction changed key count')
                return dict(rows=rows(source))
            finally:db.close()
        out,_=stage(run/'PRIVATE/material_environment_v106_corrected'/f'{k:03}',conf,build,[source,removed]);outputs.append(out/'rates.parquet')
    def finish(tmp):
        concatenate(outputs,tmp/'rates.parquet')
        return dict(keys=rows(rates),factual_game_denominators_preserved=True,removed_decisions=rows(removed))
    out,info=stage(root,conf,finish,[rates,removed]);return out/'rates.parquet',info


def attach(input_path,rates,root,conf,memory,nparts=PARTITIONS):
    root=Path(root);cached=reuse_stage(root,conf,[input_path,rates],'model.parquet')
    if cached:return root,read(root/'_DONE.json')
    incoming=[k for k in c.columns(rates) if k not in KEYS]
    require(not set(incoming)&set(c.columns(input_path)),'Unexpected existing environment columns')
    helpers=root.with_name(root.name+'_v106_parts')
    q,_=partition([input_path],helpers/'queries',conf,columns=['row_id','opponent_id','recipient_id','month_code'],
                  rename={'opponent_id':'person','recipient_id':'partner'},nparts=nparts)
    r,_=partition([rates],helpers/'rates',conf,nparts=nparts)
    lookups=[];supported=0
    for k in range(nparts):
        qp=q/f'{k:03}.parquet';rp=r/f'{k:03}.parquet'
        def build(tmp,qp=qp,rp=rp):
            db=connect(tmp,min(memory,3.))
            try:
                view(db,'q',qp);view(db,'r',rp);join=' FROM q JOIN r USING(person,partner,month_code)'
                n=rows(qp)
                require(db.execute('SELECT count(*),count(DISTINCT q.row_id)'+join).fetchone()==(n,n),'Environment join changed rows')
                copy(db,'SELECT q.row_id,'+','.join('r.'+quoted(k) for k in incoming)+join+' ORDER BY q.row_id',tmp/'by_row.parquet')
                return dict(rows=n,environment_supported=db.execute('SELECT count(*)'+join+' WHERE r.environment_supported').fetchone()[0])
            finally:db.close()
        out,info=stage(helpers/'joined'/f'{k:03}',conf,build,[qp,rp]);lookups.append(out/'by_row.parquet');supported+=info['environment_supported']
    def finish(tmp):
        stream_frames.attach(input_path,lookups,tmp/'model.parquet',replace=False,label='Attaching checked opponent environment')
        return dict(rows=rows(input_path),environment_supported=supported)
    return stage(root,conf,finish,[input_path,rates])
