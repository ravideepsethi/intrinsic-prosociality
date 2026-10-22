"""Optional synthetic full-size memory probe, never run by startup self-tests.

Usage: python tests/benchmark_memory.py --folder PATH --rows 7371688 --mode fit
Writes synthetic inputs/checkpoint + measurement.json. Unique accounts in both
roles stress the largest possible account/account-date covariance summaries.
This is a resource and execution check, not a production result.
"""
import argparse, resource, platform, time
from test_r7 import *

def generate(folder,n):
    path=folder/'synthetic.parquet'
    if path.exists():
        if pq.ParquetFile(path).metadata.num_rows!=n:raise RuntimeError('Existing probe has different row count')
        return path
    written=0;writer=None
    try:
        while written<n:
            size=min(131072,n-written);d=fixture(int(size*1.15)+100)
            d={k:v[:size] for k,v in d.items() if k in FIT_COLUMNS}
            if len(d['row_id'])!=size:raise RuntimeError('Synthetic batch too small')
            d['row_id']=np.arange(written,written+size,dtype=np.int64)
            d['recipient_id']=d['row_id']+1;d['opponent_id']=d['row_id']+n+1
            d['environment_supported'][::13]=False
            for key in ENV:d[key][::13]=np.nan
            # Include varied C classes without storing a mask for every class.
            row=d['row_id'];d['ply_count']=np.array([8,20,45,80])[row%4]
            d['engine_eval_cp_disconnected']=np.array([-350,-200,0,200,350,np.nan])[(row//4)%6]
            d['disconnected_clock_last_obs_s']=d['tc_base_s']*np.array([.05,.5,np.nan])[(row//24)%3]
            d['moves_available']=(row%11)!=0
            d['net_material_change_4ply']=np.where(d['moves_available'],np.array([-4,-1,0,2])[(row//72)%4],np.nan)
            table=pa.table(d)
            if writer is None:writer=pq.ParquetWriter(path,table.schema,compression='zstd')
            writer.write_table(table);written+=size
    finally:
        if writer:writer.close()
    return path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--rows',type=int,default=7371688);p.add_argument('--mode',choices=['generate','fit','composition','composition_probe'],default='fit')
    a=p.parse_args();a.folder.mkdir(parents=True,exist_ok=True);threads_one();started=time.monotonic()
    if a.mode=='generate':generate(a.folder,a.rows);return
    path=a.folder/'synthetic.parquet'
    if pq.ParquetFile(path).metadata.num_rows!=a.rows:raise RuntimeError('Wrong benchmark input size')
    if a.mode=='fit':
        j=dict(input=str(path),selection='',sample='F50',level='X0_ENV_indicator',instrument='pooled',kind='entry',
            part_a=True,calibration=True,influence=False,output=str(a.folder/'fit'),conf='memory_probe_v101')
        r7_models.model_job(j)
    elif a.mode=='composition_probe':
        # Full row count/classification/covariance keys and one 8-outcome batch.
        # Later batches have identical allocation shapes. No partial statistical
        # table is published or passed off as a completed composition run.
        d=load_fit_columns(path,['moves_available','net_material_change_4ply','ply_count',
            'engine_eval_cp_disconnected','disconnected_clock_last_obs_s'])
        cls,_,_=r7_composition.classes_and_prior(d,'F50')
        original_project=r7_composition.project;calls=0
        class ProbeComplete(Exception):pass
        def checked_project(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==3:raise ProbeComplete()
            return original_project(*args,**kwargs)
        r7_composition.project=checked_project
        try:r7_composition.entry_models(d,cls)
        except ProbeComplete:pass
        finally:r7_composition.project=original_project
        if calls!=3:raise RuntimeError('Composition probe did not reach the second batch')
    else:r7_composition.job(dict(input=str(path),sample='F50',output=str(a.folder/'composition'),conf='memory_probe_v101'))
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024)/1024**3
    result=dict(synthetic=True,rows=a.rows,mode=a.mode,peak_RSS_GiB=peak,elapsed_seconds=time.monotonic()-started,
        account_pattern='2*n unique accounts; maximum-sized account and account-date grouped sums',platform=platform.platform())
    io.js(a.folder/(a.mode+'_measurement.json'),result);print(json.dumps(result),flush=True)

if __name__=='__main__':main()
