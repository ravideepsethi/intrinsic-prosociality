"""One narrow projection per month and one chooser-complete partition pass."""
from util import *
from checkpoints import stage,copy_query
from sources import producers
import concurrent.futures as cf,multiprocessing as mp

def project(task):
    record_=task['record'];_,_,_,prepare,_=producers()
    require(signature(record_['path'])==record_['signature'],'Source changed before projection')
    def build(out):
        # The launcher has already hashed this exact file. Guard it rather than
        # reading the same full-width bytes again inside the legacy projector.
        previous=prepare.sha
        def checked(path):
            if Path(path).resolve()==Path(record_['path']).resolve():
                require(signature(path)==record_['signature'],'Authenticated input changed')
                return record_['sha256']
            return previous(path)
        prepare.sha=checked
        try:
            result=prepare.project_month(dict(source=record_['path'],output=str(out/'panel.parquet'),month=record_['month'],
                   rows=record_['rows'],expected_sha256=record_['sha256'],key=task['key'],memory=task['memory']))
        finally:prepare.sha=previous
        require(result['n']==record_['rows'] and result['grants']==record_['grants'],'Projection census changed')
        require(signature(record_['path'])==record_['signature'],'Source changed during projection')
        return {k:result[k] for k in ('n','grants')}
    started=time.monotonic();path,summary=stage(task['parent'],record_['month'],task['key'],build)
    return dict(path=str(path/'panel.parquet'),month=record_['month'],seconds=time.monotonic()-started,**summary)

def mapped(fn,tasks,workers,label):
    start=time.monotonic();results=[]
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        futures=[pool.submit(fn,t) for t in tasks]
        try:
            for f in cf.as_completed(futures):
                results.append(f.result());n=len(results)
                if len(tasks)<=24 or n%16==0 or n==len(tasks):
                    eta=(time.monotonic()-start)/n*(len(tasks)-n)/60
                    log(f'{label}: {n}/{len(tasks)} complete; stage ETA {eta:.1f} min')
        except BaseException:
            for f in futures:f.cancel()
            raise
    return results

def projections(auth,run,key,workers,memory):
    tasks=[dict(record=r,parent=str(run/'PRIVATE/months'),key=digest([key,r['month'],r['sha256']]),memory=min(1.5,(memory-1)/4)) for r in auth['records']]
    results=mapped(project,tasks,min(4,workers),'Narrow monthly panels')
    results=sorted(results,key=lambda r:r['month'])
    require(sum(r['n'] for r in results)==auth['expected_census']['new_opportunities'],'Narrow panels lost rows')
    table(run/'report/MONTHLY_PROJECTION.csv',[{k:v for k,v in r.items() if k!='path'} for r in results])
    return [Path(r['path']) for r in results]

def partition(paths,run,key,shards,workers,memory,expected):
    import pyarrow.parquet as pq
    def build(out):
        c=db(out/'spill',memory,min(workers,4))
        try:
            c.execute(f'COPY (SELECT *,((chooser%{shards}+{shards})%{shards})::INTEGER bucket FROM '+parquet(paths)+') TO '+sqlstr(out/'data')+
               ' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY(bucket),ROW_GROUP_SIZE 122880)')
        finally:c.close()
        files=sorted((out/'data').glob('bucket=*/*.parquet'))
        rows=sum(pq.ParquetFile(p).metadata.num_rows for p in files)
        require(rows==expected,'Chooser partitions lost rows')
        return dict(rows=rows,shards=shards,files=len(files))
    out,summary=stage(run/'PRIVATE','chooser_partitions',digest([key,'partition',shards]),build)
    by={}
    for p in sorted((out/'data').glob('bucket=*/*.parquet')):
        b=int(p.parent.name.split('=')[1]);require(0<=b<shards,'Unexpected chooser partition')
        by.setdefault(b,[]).append(p)
    require(sum(pq.ParquetFile(p).metadata.num_rows for files in by.values() for p in files)==expected,'Partition footer count changed')
    return by

def descriptions(paths,out,workers,memory,expected):
    """Every raw-stage row is rebuilt; no pre-author-exclusion rows are copied."""
    import pandas as pd
    r11,_,_,_,_=producers();c=db(out/'spill',memory,min(workers,4));public=out/'report'
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+parquet(paths))
        total=c.execute('SELECT count(*),sum(y)::BIGINT,count(DISTINCT chooser) FROM p').fetchone()
        require(tuple(total)==tuple(expected[k] for k in ('opportunities','grants','choosers')),'Description census differs')
        queries={
          'chooser_counts':'''SELECT chooser,count(*)::BIGINT n,sum(y)::BIGINT k,
            count(*) FILTER(WHERE "position">=2)::BIGINT f,count(*) FILTER(WHERE "position"=0)::BIGINT l,
            coalesce(sum(y) FILTER(WHERE "position">=2),0)::BIGINT a,coalesce(sum(y) FILTER(WHERE "position"=0),0)::BIGINT b
            FROM p GROUP BY chooser ORDER BY chooser''',
          'board_stage':'''SELECT "position" position_code,stage stage_code,count(*) opportunities,sum(y)::BIGINT grants,
            100.*avg(y) grant_rate_pct FROM p GROUP BY ALL ORDER BY ALL''',
          'speed_stage':'''SELECT speed_code,stage stage_code,count(*) opportunities,sum(y)::BIGINT grants,
            100.*avg(y) grant_rate_pct FROM p GROUP BY ALL ORDER BY ALL''',
          'speed_composition':'''SELECT speed_code,count(*) opportunities,sum(y)::BIGINT grants,
            count(*) FILTER(WHERE stage=0) baseline_opportunities,sum(y) FILTER(WHERE stage=0)::BIGINT baseline_grants,
            100.*avg(y) FILTER(WHERE stage=0) baseline_grant_rate_pct,100.*avg((stage=7)::INT) share_81plus_pct
            FROM p GROUP BY ALL ORDER BY ALL'''}
        copy_query(c,queries.pop('chooser_counts'),out/'chooser_counts_PRIVATE.parquet')
        for name,q in queries.items():
            d=c.execute(q).fetchdf()
            if 'stage_code' in d:d['stage']=d.stage_code.map(dict(enumerate(r11.STAGES)))
            if 'speed_code' in d:d['speed']=d.speed_code.map(dict(enumerate(r11.SPEEDS)))
            if 'position_code' in d:d['position']=d.position_code.map(dict(enumerate(r11.POSITIONS)))
            table(public/(name+'.csv'),d)
        rows=[]
        for label,condition in [('ply_2','ply=2'),('plies_3_10','ply BETWEEN 3 AND 10'),('by_ply_10','ply<=10'),('after_ply_10','ply>10'),('by_ply_4','ply<=4')]:
            n,g=c.execute('SELECT count(*),coalesce(sum(y),0)::BIGINT FROM p WHERE "position">=2 AND '+condition).fetchone()
            rows.append(dict(panel='A_competitive',stage=label,opportunities=n,grants=g,grant_rate_pct=100*g/n if n else None))
        require(rows[0]['opportunities']+rows[1]['opportunities']==rows[2]['opportunities'],'Ply 2 and 3–10 do not partition early decisions')
        require(rows[2]['opportunities']+rows[3]['opportunities']==expected['competitive'],'Early and late counts do not partition competitive decisions')
        d=c.execute('SELECT stage,count(*) opportunities,sum(y)::BIGINT grants,100.*avg(y) grant_rate_pct FROM p WHERE "position"=2 GROUP BY stage ORDER BY stage').fetchdf()
        for row in d.to_dict('records'):
            row['stage']=r11.STAGES[row['stage']];row['panel']='B_roughly_equal';rows.append(row)
        table(public/'tab_app_state_ply.csv',rows)
        valid=c.execute('''SELECT count(*) FILTER(WHERE clock_c IS NULL OR NOT isfinite(clock_c) OR clock_c<0) clock_c_invalid,
          count(*) FILTER(WHERE clock_d IS NULL OR NOT isfinite(clock_d) OR clock_d<0) clock_d_invalid,
          count(*) FILTER(WHERE premium IS NULL OR NOT isfinite(premium) OR premium<=0) premium_invalid,
          count(*) FILTER(WHERE rd_c IS NULL OR NOT isfinite(rd_c) OR rd_c<=0) rd_c_invalid,
          count(*) FILTER(WHERE rd_d IS NULL OR NOT isfinite(rd_d) OR rd_d<=0) rd_d_invalid,
          count(*) FILTER(WHERE gap IS NULL OR NOT isfinite(gap)) gap_invalid FROM p''').fetchdf()
        table(public/'missingness.csv',valid)
        # Reviewed material panel has no invalid clocks: pooled vs interacted
        # missing-indicator conventions therefore cannot change this fit.
        require(int(valid.clock_c_invalid.iloc[0])+int(valid.clock_d_invalid.iloc[0])==0,'Clock missingness differs from reviewed source; stop for specification review')
        return dict(opportunities=total[0],grants=total[1],choosers=total[2])
    finally:c.close()
