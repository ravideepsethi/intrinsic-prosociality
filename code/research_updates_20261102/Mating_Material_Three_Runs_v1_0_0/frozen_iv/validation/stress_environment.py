"""Synthetic validation only. Run each mode in a fresh process for peak RSS."""
import argparse,resource,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
from types import SimpleNamespace
import environment_partitions as ep
import rebuild_frames

p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','old','partitioned','verify','pipeline_prepare','pipeline','pipeline_verify'])
p.add_argument('--folder',type=Path,required=True);p.add_argument('--rows',type=int,default=4000000)
p.add_argument('--memory',type=float,default=.3);a=p.parse_args();a.folder.mkdir(parents=True,exist_ok=True)
started=time.monotonic();n=a.rows;paths=[a.folder/f'cache{k}.parquet' for k in range(3)]

def values(ids,priority):
    complete=ids%17!=0;supported=complete&(ids%23!=0)
    games=100+ids%1000;own=ids%7;chooser=ids%11
    data=dict(person=ids%600000,partner=ids//600000+1000000,month_code=ids%24,
              lo=ids%24*10000000000,hi=ids%24*10000000000+7776000000,
              complete=complete,games=games,own=own,chooser=chooser,
              environment_supported=supported)
    for k,raw in [('log_opponent_games90',np.log1p(games)),
                  ('opponent_observed_disconnect_rate',own/games),
                  ('opponent_observed_chooser_rate',chooser/games),
                  ('validation_priority',ids%101/101+np.asarray(priority)*2e-13)]:
        data[k]=pa.array(raw,mask=~supported)
    return pa.table(data)

status='PASS';output=None
if a.mode=='prepare':
    for k,path in enumerate(paths):
        start=k*(n//4);writer=None
        try:
            for lo in range(start,start+n,65536):
                ids=np.arange(lo,min(lo+65536,start+n),dtype=np.int64);table=values(ids,k)
                if writer is None:writer=pq.ParquetWriter(path,table.schema,compression='zstd',use_dictionary=False)
                writer.write_table(table,row_group_size=65536)
        finally:
            if writer:writer.close()
elif a.mode in ('old','partitioned'):
    run=a.folder/a.mode;b={'primary':dict(known_rates=[str(p) for p in paths])}
    try:
        fn=rebuild_frames.pool_rates if a.mode=='old' else ep.pool_rates
        output=fn(SimpleNamespace(memory_gb=2+a.memory,workers=1),run,'synthetic_memory',b)
    except Exception as e:
        if a.mode=='old' and ('Out of Memory' in str(e) or 'OutOfMemory' in type(e).__name__):status='EXPECTED_OOM'
        else:raise
elif a.mode in ('verify','pipeline_verify'):
    output=a.folder/'partitioned/PRIVATE/rate_pool/rates.parquet';count=0
    if a.mode=='pipeline_verify':output=a.folder/'pipeline/attached/model.parquet'
    seen=np.zeros(n+n//2,dtype=bool)
    for batch in pq.ParquetFile(output).iter_batches(batch_size=65536,use_threads=False):
        table=pa.Table.from_batches([batch])
        if a.mode=='pipeline_verify':
            ids=table['row_id'].to_numpy()
            require(np.array_equal(ids,np.arange(count,count+len(ids))),'Attached row order changed')
            require(np.array_equal(table['opponent_id'].to_numpy(),ids%600000),'Attached person changed')
            require(np.array_equal(table['recipient_id'].to_numpy(),ids//600000+1000000),'Attached partner changed')
            require(table['payload'].to_pylist()==['position-'+str(int(x%1009)) for x in ids],'Payload changed')
            fields=values(ids,0).column_names
            table=pa.Table.from_arrays([table['opponent_id'] if k=='person' else table['recipient_id'] if k=='partner' else table[k] for k in fields],names=fields)
        else:ids=table['person'].to_numpy()+600000*(table['partner'].to_numpy()-1000000)
        require(np.all((ids>=0)&(ids<len(seen))),'Invalid synthetic key')
        require(not seen[ids].any() and len(np.unique(ids))==len(ids),'Duplicate synthetic key')
        seen[ids]=True;priority=np.where(ids<n,0,np.where(ids<n+n//4,1,2))
        want=values(ids,priority)
        require(table.equals(want,check_metadata=False),'Partitioned result differs from exact generator')
        count+=len(ids)
    require(count==n+n//2 and seen.all(),'Incomplete synthetic key coverage')
    old=a.folder/'old/PRIVATE/rate_pool/rates.parquet'
    if old.exists() and a.mode=='verify':
        db=connect(a.folder/'verify_spill',1.)
        try:
            view(db,'new',output);view(db,'old',old)
            require(db.execute('SELECT count(*) FROM ((SELECT * FROM new EXCEPT ALL SELECT * FROM old) UNION ALL (SELECT * FROM old EXCEPT ALL SELECT * FROM new))').fetchone()[0]==0,'Original SQL differs')
        finally:db.close()
elif a.mode=='pipeline_prepare':
    target=a.folder/'queries.parquet';writer=None
    try:
        for lo in range(0,n+n//2,65536):
            ids=np.arange(lo,min(lo+65536,n+n//2),dtype=np.int64)
            table=pa.table(dict(row_id=ids,opponent_id=ids%600000,recipient_id=ids//600000+1000000,
                                month_code=ids%24,payload=['position-'+str(int(x%1009)) for x in ids]))
            if writer is None:writer=pq.ParquetWriter(target,table.schema,compression='zstd',use_dictionary=False)
            writer.write_table(table,row_group_size=65536)
    finally:
        if writer:writer.close()
    pq.write_table(pa.table({k:pa.array([],pa.int64()) for k in ['i','j','start_ms','end_ms']}),a.folder/'removed.parquet')
elif a.mode=='pipeline':
    source=a.folder/'queries.parquet';rates=a.folder/'partitioned/PRIVATE/rate_pool/rates.parquet'
    run=a.folder/'pipeline';cfg='synthetic_following_environment_steps'
    req,info=ep.missing_requests([source],rates,run/'requests',cfg,a.memory)
    require(info['missing_requests']==0,'Unexpected synthetic missing request')
    fixed,_=ep.correct_rates(SimpleNamespace(memory_gb=2+a.memory),run,cfg,rates,a.folder/'removed.parquet')
    result,_=ep.attach(source,fixed,run/'attached',cfg,a.memory);output=result/'model.parquet'

peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024 if sys.platform!='darwin' else 1024**2)
result=dict(mode=a.mode,status=status,rows_per_cache=n,input_rows=3*n,distinct_keys=n+n//2,
            partitions=128,memory_limit_gb=a.memory,seconds=time.monotonic()-started,
            peak_rss_mib=peak,output=str(output) if output else None)
if a.mode in ('verify','pipeline_verify'):result.update(all_values_and_keys_match_generator=True,original_SQL_checked=old.exists() and a.mode=='verify')
save(a.folder/(a.mode+'.json'),result);print(json.dumps(result))
