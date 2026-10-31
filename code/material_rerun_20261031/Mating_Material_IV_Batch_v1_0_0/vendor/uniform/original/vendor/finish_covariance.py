"""Bounded, resumable evaluation of the unchanged shared-account OR date CR0.

Partition complete grouping keys, never observations within a cluster. Account
partitions serve both account and account/date terms; canonical-pair partitions
serve both pair terms. Dates are a small full-sample reduction. A failed leaf is
split on a hash of its COMPLETE group key, preserving cross-sample covariance.
"""
from rebuild_common import *
from repair_chronology import partition
import duckdb, math, re

ALGORITHM = 'shared_account_OR_date_CR0_partitioned_v104'
BUCKETS = 128


def grouped_outer(c, source, keys, columns):
    sums = ','.join('sum("'+x+'") AS "'+x+'"' for x in columns)
    terms = [(i,j) for i in range(len(columns)) for j in range(i,len(columns))]
    outer = ','.join('coalesce(sum("'+columns[i]+'"*"'+columns[j]+'"),0.0)' for i,j in terms)
    row = c.execute('SELECT '+outer+' FROM (SELECT '+','.join(keys)+','+sums+
                    ' FROM ('+source+') GROUP BY '+','.join(keys)+')').fetchone()
    require(all(x is not None and np.isfinite(x) for x in row),'Nonfinite covariance term')
    return list(map(float,row))


def covariance(path, columns, root, memory=4., buckets=BUCKETS):
    path=Path(path);root=Path(root)
    require(columns and len(set(columns))==len(columns) and
            all(re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',x) for x in columns),'Invalid covariance columns')
    require(1<=buckets<=256,'Invalid covariance partition count')
    identity=dict(algorithm=ALGORITHM,input_sha256=sha(path),columns=columns,
                  buckets=buckets,duckdb_version=duckdb.__version__)
    conf=key(identity);root=root/conf[:16];root.mkdir(parents=True,exist_ok=True)
    if (root/'identity.json').exists():require(load(root/'identity.json')==identity,'Covariance identity changed')
    else:save(root/'identity.json',identity)
    # Input bytes, rather than a disposable stack filename, bind the checkpoints.
    # The same stack can be regenerated in a new partial stage after interruption.
    n=pq.ParquetFile(path).metadata.num_rows;require(n>0,'Empty covariance input')
    names=','.join('"'+x+'"' for x in columns);source=parq([path])
    c=connection(root/'validation',memory)
    try:
        bad='recipient_id IS NULL OR opponent_id IS NULL OR date IS NULL OR recipient_id=opponent_id'
        bad+=' OR '+' OR '.join('"'+x+'" IS NULL OR NOT isfinite("'+x+'")' for x in columns)
        ensure(c,'SELECT count(*) FROM '+source+' WHERE '+bad,'Invalid covariance IDs or influences')
    finally:c.close()
    families={
        'accounts': ('SELECT recipient_id person,date,'+names+' FROM '+source+
                     ' UNION ALL SELECT opponent_id person,date,'+names+' FROM '+source,['person'],2*n),
        'pairs': ('SELECT least(recipient_id,opponent_id) lo,greatest(recipient_id,opponent_id) hi,date,'+
                  names+' FROM '+source,['lo','hi'],n)}
    parts={}
    for family,(sql,keys,rows) in families.items():
        def build(tmp,sql=sql,keys=keys,rows=rows,family=family):
            c=connection(tmp,memory)
            try:
                query='SELECT *,CAST(hash('+','.join(keys)+f')%{buckets} AS INTEGER) bucket FROM ('+sql+')'
                return partition(c,query,tmp/'parts',buckets=buckets,label='Covariance '+family,
                                 expected_rows=rows,buffer_bytes=64*1024*1024)
            finally:c.close()
        parts[family],_=stage(root/('partition_'+family),conf,build)
    definitions=[('accounts',1,'accounts',['person']),('pairs',-1,'pairs',['lo','hi']),
                 ('dates',1,None,['date']),('account_dates',-1,'accounts',['person','date']),
                 ('pair_dates',1,'pairs',['lo','hi','date'])]
    totals=[];summary=[]
    for name,sign,family,keys in definitions:
        values=[];started=time.monotonic();fresh=0;fresh_seconds=0.
        paths=sorted((parts[family]/'parts').glob('bucket=*/data.parquet')) if family else [path]
        for index,p in enumerate(paths):
            base_sql='SELECT * FROM '+parq([p])
            def leaf(modulus=1,residue=0):
                target=root/'terms'/name/f'{index:03}_{modulus:05}_{residue:05}'
                query=base_sql
                if modulus>1:query+=' WHERE hash('+','.join(keys)+f')%{modulus}={residue}'
                def build(tmp):
                    c=connection(tmp,memory)
                    try:result=grouped_outer(c,query,keys,columns)
                    finally:c.close()
                    save(tmp/'outer.json',result);return dict(group_keys=keys,modulus=modulus,residue=residue)
                try:
                    # conf identifies the SHA-checked, immutable partition producer.
                    out,_=stage(target,conf,build)
                except duckdb.OutOfMemoryException:
                    require(modulus<65536,'Covariance leaf still exceeds memory; completed leaves retained')
                    log(f'Covariance {name} leaf {index+1}: splitting complete cluster keys after memory limit')
                    leaf(modulus*2,residue);leaf(modulus*2,residue+modulus);return
                values.append(load(out/'outer.json'))
            before=time.monotonic();was_done=(root/'terms'/name/f'{index:03}_00001_00000'/'_DONE.json').exists()
            leaf()
            if not was_done:fresh+=1;fresh_seconds+=time.monotonic()-before
            if (index+1)%16==0 or index+1==len(paths):
                remaining=(fresh_seconds/fresh*(len(paths)-index-1)/60) if fresh else 0.
                log(f'Covariance {name}: {index+1}/{len(paths)} partitions; remaining term ETA ~{remaining:.1f} min')
        total=[math.fsum(x[j] for x in values) for j in range(len(values[0]))]
        totals.append((sign,total));summary.append(dict(term=name,leaf_count=len(values),seconds=time.monotonic()-started))
    terms=[(i,j) for i in range(len(columns)) for j in range(i,len(columns))];V=np.zeros((len(columns),len(columns)))
    for k,(i,j) in enumerate(terms):V[i,j]=V[j,i]=math.fsum(sign*row[k] for sign,row in totals)
    require(np.isfinite(V).all(),'Nonfinite assembled covariance')
    save(root/'summary.json',dict(identity=identity,terms=summary,matrix=V.tolist(),memory_decimal_gb=memory,
                                 workers=1,arrow_buffer_mib=64,cross_sample_groups_preserved=True))
    return V


def contrast_job(job):
    from rebuild_models import m7
    left,right=Path(job['left']),Path(job['right'])
    deps=[p/n for p in (left,right) for n in ('result.json','influence_PRIVATE.parquet')]
    def build(tmp):
        a=load(left/'result.json')['estimates'];b=load(right/'result.json')['estimates'];cols=[]
        for name in job['outcomes']:cols+=['left_'+name,'right_'+name]
        c=connection(tmp,4.)
        try:
            queries=[]
            for side,folder in [('left',left),('right',right)]:
                fields=['recipient_id','opponent_id','date']
                for name in job['outcomes']:
                    fields += [(name if side=='left' else '0.0')+' AS left_'+name,
                               (name if side=='right' else '0.0')+' AS right_'+name]
                queries.append('SELECT '+','.join(fields)+' FROM '+parq([folder/'influence_PRIVATE.parquet']))
            copy_query(c,' UNION ALL '.join(queries),tmp/'stack.parquet')
        finally:c.close()
        V=covariance(tmp/'stack.parquet',cols,Path(job['work']),4.);rows=[]
        for k,name in enumerate(job['outcomes']):
            aa=next(x for x in a if x.get('outcome')==name and x.get('estimator')=='reduced_form')
            bb=next(x for x in b if x.get('outcome')==name and x.get('estimator')=='reduced_form')
            sub=V[2*k:2*k+2,2*k:2*k+2];var=float(sub[0,0]+sub[1,1]-2*sub[0,1])
            rows.append(dict(contrast=job['label'],control_level=job['level'],outcome=name,estimator='reduced_form',
              left_n=aa['n'],right_n=bb['n'],left_coefficient=aa['coefficient'],right_coefficient=bb['coefficient'],
              covariance_matrix=sub.tolist(),stacked_actual_accounts_and_dates=True,
              **m7.inference(aa['coefficient']-bb['coefficient'],var)))
        save(tmp/'result.json',rows);(tmp/'stack.parquet').unlink()
        return dict(contrasts=len(rows),covariance_algorithm=ALGORITHM,scientific_formula_changed=False)
    return stage(job['output'],job['conf'],build,deps)[1]
