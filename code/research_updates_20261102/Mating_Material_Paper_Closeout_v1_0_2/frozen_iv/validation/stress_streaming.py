"""Standalone scale test; omitted from startup to avoid a multi-minute detour.

Generate a wide synthetic frame. Reproduce the original join's OOM under a
small DuckDB budget, then compare the streaming result with uncapped SQL.
Run each fit in a separate process for meaningful peak-RSS measurements.
"""
from pathlib import Path
import argparse, json, os, resource, subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
import stream_frames as sf


def main():
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path)
    p.add_argument('--mode',choices=['prepare','old_small','old_oracle','stream','compare','formula'],required=True)
    p.add_argument('--rows',type=int,default=500000);a=p.parse_args()
    a.folder.mkdir(parents=True,exist_ok=True);n=a.rows
    source=a.folder/'q.parquet';parts=[a.folder/f'h{k:02}.parquet' for k in range(16)]
    start=time.monotonic();result=dict(mode=a.mode,rows=n)
    if a.mode=='prepare':
        writers=[]
        try:
            qw=None
            for lo in range(0,n,16384):
                ids=np.arange(lo,min(n,lo+16384),dtype=np.int64)
                data=dict(row_id=ids,name=['account_'+str(i)+'x'*60 for i in ids])
                data.update({'q'+str(k):ids.astype(float)*(k+1)/17 for k in range(30)})
                q=pa.table(data)
                if qw is None:qw=pq.ParquetWriter(source,q.schema,compression='zstd')
                qw.write_table(q)
                for s in range(16):
                    ii=ids[ids%16==s]
                    h=pa.table(dict(row_id=ii,**{'h'+str(k):ii.astype(float)*(k+1)/19 for k in range(24)}))
                    if len(writers)<16:writers.append(pq.ParquetWriter(parts[s],h.schema,compression='zstd'))
                    writers[s].write_table(h)
        finally:
            if qw:qw.close()
            for w in writers:w.close()
        # Match the saved workers' large Parquet row groups, not tiny test groups.
        for part in parts:
            table=pq.read_table(part)
            temporary=part.with_suffix('.compact')
            pq.write_table(table,temporary,compression='zstd',row_group_size=1048576)
            os.replace(temporary,part)
    elif a.mode.startswith('old_'):
        db=connect(a.folder/('spill_'+a.mode),.096 if a.mode=='old_small' else 1.)
        try:
            view(db,'q',source);view(db,'h',parts)
            copy(db,'SELECT q.*,h.* EXCLUDE(row_id) FROM q JOIN h USING(row_id) ORDER BY row_id',a.folder/(a.mode+'.parquet'))
            result['status']='PASS'
        except Exception as error:
            import duckdb
            if a.mode!='old_small' or not isinstance(error,duckdb.OutOfMemoryException):raise
            result.update(status='EXPECTED_OOM',exception=type(error).__name__,message=str(error).split('\n')[0])
        finally:db.close()
        if a.mode=='old_small':require(result['status']=='EXPECTED_OOM','Fixture did not reproduce the memory problem')
    elif a.mode=='stream':
        result.update(sf.attach(source,parts,a.folder/'stream.parquet'))
        result['arrow_peak_bytes']=pa.default_memory_pool().max_memory()
    elif a.mode=='compare':
        original=pq.ParquetFile(a.folder/'old_oracle.parquet');fixed=pq.ParquetFile(a.folder/'stream.parquet')
        require(original.metadata.num_rows==fixed.metadata.num_rows==n,'Row count differs')
        count=0
        for left,right in zip(original.iter_batches(batch_size=65536,use_threads=False),fixed.iter_batches(batch_size=65536,use_threads=False)):
            require(left.schema.equals(right.schema,check_metadata=False),'Schema differs')
            require(left.equals(right,check_metadata=False),'Logical values or row order differ')
            count+=left.num_rows
        require(count==n,'Comparison omitted rows');result['exact_SQL_equivalence']=True
    else:
        count=0
        for batch in pq.ParquetFile(a.folder/'stream.parquet').iter_batches(batch_size=65536,use_threads=False):
            ids=batch.column('row_id').to_numpy()
            require(np.array_equal(ids,np.arange(count,count+len(ids))),'Row IDs changed')
            require(batch.column('name').to_pylist()==['account_'+str(i)+'x'*60 for i in ids],'String values changed')
            for prefix,width,den in [('q',30,17),('h',24,19)]:
                for k in range(width):
                    require(np.array_equal(batch.column(prefix+str(k)).to_numpy(),ids.astype(float)*(k+1)/den),'Numeric values changed')
            count+=len(ids)
        require(count==n,'Row count differs');result['all_values_match_generator']=True
    result.update(seconds=time.monotonic()-start,peak_RSS_MiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024 if sys.platform!='darwin' else 1024**2))
    (a.folder/(a.mode+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
