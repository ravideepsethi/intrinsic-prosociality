"""Sparse additive-control LPM; exact chooser-cluster score aggregation.
Only the target coefficient is reported; no fixed account effect is included
because the snapshot flag is constant within account.
"""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[k]='1'
import math
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import sparse, stats
from utils import *

CATS=['match_cell','month','speed','rating_tier','board_bin','ply_bin','gap_bin']
NUMS=['payoff10','premium10','crd100','drd100','log_cc','log_dc','cc_missing','dc_missing','log_volume']

def matrix(d,spec):
    n=len(d['y']); rows=[np.arange(n),np.arange(n)]; cols=[np.zeros(n,dtype=int),np.ones(n,dtype=int)]
    vals=[np.asarray(d[spec['target']],float),np.ones(n)]; j=2
    for col in spec['cats']:
        levels=spec['levels'][col]; lookup={v:i for i,v in enumerate(levels)}
        code=np.array([lookup[str(v)] for v in d[col]],dtype=int)
        take=code>0; rows.append(np.flatnonzero(take)); cols.append(j+code[take]-1); vals.append(np.ones(take.sum()))
        j+=len(levels)-1
    for col in spec['nums']:
        v=np.asarray(d[col],float); require(np.isfinite(v).all(),'Nonfinite model covariate: '+col)
        rows.append(np.arange(n)); cols.append(np.full(n,j)); vals.append(v); j+=1
    return sparse.csr_matrix((np.concatenate(vals),(np.concatenate(rows),np.concatenate(cols))),shape=(n,j))

def solve(A,b):
    scale=np.sqrt(np.maximum(np.diag(A),1e-30)); Z=A/np.outer(scale,scale)
    values,V=np.linalg.eigh(Z); keep=values>max(1e-11,float(values.max())*1e-10)
    rank=int(keep.sum()); null=float(np.sum(V[0,~keep]**2))
    if null>1e-8: return None,None,rank
    inv=(V[:,keep]/values[keep])@V[:,keep].T/np.outer(scale,scale)
    return inv@b,inv[0,:],rank

def fit(db, run, name, target, where, cats=CATS, nums=NUMS, outcome='y', account=False):
    private=run/'PRIVATE'/'models'/name; private.mkdir(parents=True,exist_ok=True)
    source='accounts_model' if account else 'model_data'
    where='('+where+') AND profile_source=\'august\' AND returned AND NOT disabled AND match_cell IS NOT NULL'
    levels={c:[str(r[0]) for r in db.execute(f'SELECT DISTINCT {qi(c)} FROM {source} WHERE {where} ORDER BY 1').fetchall()] for c in cats}
    n,g=db.execute(f'SELECT count(*),count(DISTINCT chooser) FROM {source} WHERE {where}').fetchone()
    if n==0:
        result=dict(model=name,status='NO_ELIGIBLE_ROWS',n=0); dump(run/'report'/f'model_{name}.json',result); return result
    spec=dict(target=target,cats=cats,nums=nums,levels=levels,outcome=outcome,where=where,source=source)
    ident=signature([read(run/'RUN_IDENTITY.json')['identity'],name,spec]); dump(private/'spec.json',spec)
    p=2+sum(max(0,len(v)-1) for v in levels.values())+len(nums)
    A=np.zeros((p,p)); b=np.zeros(p); N=0
    # Month partitions allow bounded memory and restart of both passes.
    parts=['all'] if account else [r[0] for r in db.execute(f'SELECT DISTINCT month FROM {source} ORDER BY 1').fetchall()]
    def batches(part):
        sel=list(dict.fromkeys(['chooser',target]+cats+nums))
        extra='' if account else f' AND month={qs(part)}'
        sql=f'SELECT '+','.join(qi(c) for c in sel)+f', {qi(outcome)}::DOUBLE AS y FROM {source} WHERE {where}{extra}'
        for batch in db.execute(sql).fetch_record_batch(65536): yield batch.to_pydict()
    for part in parts:
        path=private/(part+'_moments.npz')
        if valid(path,ident):
            with np.load(path) as z: A+=z['A']; b+=z['b']; N+=int(z['N'])
            continue
        a=np.zeros_like(A); bb=np.zeros_like(b); nn=0
        with Heartbeat(name+' moments '+part):
            for d in batches(part):
                X=matrix(d,spec); y=np.asarray(d['y'],float); a+=(X.T@X).toarray(); bb+=np.asarray(X.T@y); nn+=len(y)
        np.savez(path,A=a,b=bb,N=nn); certify(path,ident); A+=a; b+=bb; N+=nn; log(name+' moments '+part)
    require(N==n,'Model sample count changed')
    beta,bread,rank=solve(A,b)
    if beta is None or n<=rank or g<2:
        result=dict(model=name,status='TARGET_NOT_IDENTIFIED_OR_INSUFFICIENT_CLUSTERS',n=n,clusters=g,rank=rank)
        dump(run/'report'/f'model_{name}.json',result); return result
    scores=[]; score_identity=signature([ident,beta.tolist()])
    for part in parts:
        path=private/(part+'_scores.parquet'); scores.append(path)
        if valid(path,score_identity): continue
        # Aggregate the influence score by chooser inside each batch, then
        # across batches/months in DuckDB. This retains cross-month covariance.
        temp=path.with_suffix('.partial.parquet'); writer=None
        try:
            with Heartbeat(name+' clustered scores '+part):
                for d in batches(part):
                    X=matrix(d,spec); y=np.asarray(d['y'],float)
                    score=np.asarray(X@bread)*(y-np.asarray(X@beta))
                    ids,inv=np.unique(np.asarray(d['chooser'],np.int64),return_inverse=True)
                    sums=np.bincount(inv,weights=score)
                    t=pa.table({'chooser':ids,'score':sums})
                    if writer is None: writer=pq.ParquetWriter(temp,t.schema,compression='zstd')
                    writer.write_table(t)
                if writer is None: pq.write_table(pa.table({'chooser':pa.array([],type=pa.int64()),'score':pa.array([],type=pa.float64())}),temp)
        finally:
            if writer: writer.close()
        os.replace(temp,path); certify(path,score_identity); log(name+' scores '+part)
    paths='['+','.join(qs(p) for p in scores)+']'
    observed_g,meat=db.execute(f'SELECT count(*),sum(s*s) FROM (SELECT chooser,sum(score) s FROM read_parquet({paths}) GROUP BY chooser)').fetchone()
    require(observed_g==g,'Cluster score count mismatch')
    se=math.sqrt(max(0,meat)*g/(g-1)*(n-1)/(n-rank)); t=float(beta[0])/se if se else None
    crit=float(stats.t.ppf(.975,g-1)); pv=float(2*stats.t.sf(abs(t),g-1)) if t is not None else None
    result=dict(model=name,status='ESTIMATED',n=n,clusters=g,rank=rank,coefficient_pp=float(beta[0])*100,
      standard_error_pp=se*100,ci_low_pp=(float(beta[0])-crit*se)*100,ci_high_pp=(float(beta[0])+crit*se)*100,p_value=pv,
      se_method='chooser clustered CR1; summed scores across all months',specification=spec,
      scope='August acquired, returned, non-disabled accounts in current pool panel; unweighted selected-sample association',
      historical_replication=False,warning='Not a population estimate, causal effect, or exact replication of the historical +0.907 pp specification.')
    dump(run/'report'/f'model_{name}.json',result); return result

def all_models(db,run):
    results=[]
    for name,target,where in [('flag_competitive','flag_present','board>=-100'),('flag_clearly_worse','flag_present','board<=-300'),
                              ('tv_competitive','tv_positive','board>=-100 AND tv_seconds IS NOT NULL')]:
        results.append(fit(db,run,name,target,where))
    results.append(fit(db,run,'flag_ever_competitive','flag_present','fair_n>0',cats=['match_cell'],nums=[],outcome='ever_fair',account=True))
    valid_results=[r for r in results if r.get('p_value') is not None]; order=sorted(valid_results,key=lambda r:r['p_value']); running=0
    for i,r in enumerate(order):
        running=max(running,min(1,r['p_value']*(len(results)-i))); r['holm_p_four_model_family']=running
    dump(run/'report'/'MODEL_SUMMARY.json',results)
