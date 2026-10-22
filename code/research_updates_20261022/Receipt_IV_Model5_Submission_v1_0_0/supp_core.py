"""Model 5 submission supplements; all writes belong to this runner's workspace."""
from pathlib import Path
import sys, os, json, gc, math, hashlib, time, re, subprocess, mmap
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'vendor'))
import fast_bootstrap as c
import fast_models as old
import rebuild_models as disk
import finish_covariance as bounded
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

VERSION = '1.0.0'
EXPECTED_CONF = 'af114813b1add1405ce5f4a40d6968648f6dbc79ffa49199b185085371411ab3'
EXPECTED_ROWS = 'fdb12d9955b1005f3df61738499d279aa4da07d1bb126d0db040b9f53a9b487f'
EXPECTED_N = 9736182
EXPECTED_PEOPLE = 1877395
BLOCK = 65536
SPEC = dict(version=VERSION, parent_configuration=EXPECTED_CONF,
    row_set_sha256=EXPECTED_ROWS, supplements=['S1','S4','S5','S7'],
    S1='Each recipient has total weight one; w_it=1/n_i on the fixed Model 5 frame; weights in FE, FWL, moments and influence functions',
    S4='Unweighted OLS of y on received with the exact Model 5 controls and fixed effects',
    S5='Unweighted transformed-outcome IV diagnostics on the primary frame: YD and Y(1-D); mu0 has a negative sign; probability units; interpretation requires additional assumptions',
    S7='Exact recipient exposure-count histogram, quantiles, and row/recipient shares above fixed thresholds',
    score_scale=c.SD, covariance='shared-account-OR-exposure-date CR0; scores treated as fixed',
    primary_unchanged=True, inference='Wald; covariance of differences retains shared rows and all cross-account/date terms',
    no_new_outcomes=True, no_network=True, no_recipient_caps=True)

def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n');os.replace(tmp,p)

def load(p): return json.loads(Path(p).read_text())
def require(ok,message):
    if not ok: raise RuntimeError(message)
def log(s): print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+' '+s,flush=True)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def signature(p):
    s=Path(p).stat();return [s.st_size,s.st_mtime_ns]
def release(a):
    if isinstance(a,np.memmap):
        if a.flags.writeable:a.flush()
        if hasattr(a._mmap,'madvise') and hasattr(mmap,'MADV_DONTNEED'):
            a._mmap.madvise(mmap.MADV_DONTNEED)

def pressure_gate(label):
    """Yield at allocation boundaries when macOS has little reclaimable RAM.

    No signals, locks, or settings of the active parent run are changed.
    Inactive pages are reclaimable, so this is a conservative scheduling hint,
    not an RSS cap or a guarantee about other processes.
    """
    if sys.platform!='darwin' or os.environ.get('SUPP_PRESSURE_GUARD')=='0':return
    while True:
        try:
            out=subprocess.check_output(['/usr/bin/vm_stat'],text=True,timeout=5)
            size=int(re.search(r'page size of (\d+) bytes',out).group(1))
            values={k:int(v) for k,v in re.findall(r'^([^:\n]+):\s+(\d+)\.',out,re.M)}
            available=sum(values.get(k,0) for k in ['Pages free','Pages inactive','Pages speculative'])*size/2**30
        except (OSError,ValueError,AttributeError,subprocess.SubprocessError):return
        if available>=1.5:return
        gc.collect();log(f'Memory pressure: yielding before {label}; reclaimable estimate {available:.2f} GiB. Parent continues.')
        time.sleep(15)

def recipient_weights(person):
    ids,inverse,counts=np.unique(person,return_inverse=True,return_counts=True)
    weights=1.0/counts[inverse]
    require(np.isclose(weights.sum(),len(ids),rtol=2e-13),'Recipient weights do not sum to recipient count')
    require(np.allclose(np.bincount(inverse,weights=weights),1.,rtol=2e-13,atol=2e-13),'Recipient weights do not sum to one within account')
    return weights,counts

def counts_report(counts):
    counts=np.asarray(counts,np.int64);people=len(counts);rows=int(counts.sum())
    levels,frequencies=np.unique(counts,return_counts=True)
    histogram=[dict(exposures_per_recipient=int(k),recipients=int(f),rows=int(k*f),
                    recipient_share=float(f/people),row_share=float(k*f/rows)) for k,f in zip(levels,frequencies)]
    quantiles=[dict(quantile=q,exposures=float(np.quantile(counts,q,method='linear'))) for q in [0,.25,.5,.75,.9,.95,.99,.999,1]]
    summary=dict(rows=rows,recipients=people,mean_exposures=rows/people,max_exposures=int(counts.max()),
        one_exposure_recipients=int((counts==1).sum()),one_exposure_recipient_share=float((counts==1).mean()),
        repeat_recipient_row_share=float(counts[counts>1].sum()/rows),quantile_method='linear interpolation across recipients')
    thresholds=[dict(more_than=k,recipients=int((counts>k).sum()),recipient_share=float((counts>k).mean()),
                     rows=int(counts[counts>k].sum()),row_share=float(counts[counts>k].sum()/rows)) for k in [1,10,20,50,100]]
    return summary,histogram,quantiles,thresholds

def prepare_design(source,scores,root,validate_real=True):
    """Use unchanged producer transforms, but force its buffer onto local disk."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    old.allocate_design=disk.disk_matrix
    job=dict(input=str(source),scores=str(scores),level='X0_ENV_indicator',name='model5_submission',
             outcomes=['received','y','reached'],iv=True)
    pressure_gate('design construction')
    v,groups,actors,targets,meta,events=old.build_buffer(job,root)
    require(targets==['z','received','y','reached'],'Unexpected parent target layout')
    n,p=v.shape
    if validate_real:
        require(n==EXPECTED_N and meta['recipients']==EXPECTED_PEOPLE,'Model 5 sample size changed')
        require(meta['row_set_sha256']==EXPECTED_ROWS,'Model 5 row set changed')
    # Both products are constructed before absorption. P(YD) != P(Y)*P(D).
    base=disk.disk_matrix(root/'base.dat',n,p+2)
    for lo in range(0,n,BLOCK):
        hi=min(n,lo+BLOCK);base[lo:hi,:4]=v[lo:hi,:4]
        base[lo:hi,4]=v[lo:hi,1]*v[lo:hi,2]
        base[lo:hi,5]=(1-v[lo:hi,1])*v[lo:hi,2]
        base[lo:hi,6:]=v[lo:hi,4:];release(v);release(base)
    del v;(root/'design.dat').unlink()
    w,counts=recipient_weights(actors['recipient_id'])
    np.save(root/'weights.npy',w);del w
    summary,hist,quantiles,thresholds=counts_report(counts);del counts
    save(root/'counts.json',dict(summary=summary,histogram=hist,quantiles=quantiles,thresholds=thresholds))
    for key,value in actors.items():np.save(root/(key+'.npy'),value)
    for k,g in enumerate(groups):np.save(root/f'group{k}.npy',g)
    save(root/'design.json',dict(n=n,p=p+2,width=6,meta=meta,events=events,
        targets=['z','received','y','reached','y_times_d','y_times_one_minus_d']))
    del actors,groups,base;gc.collect()
    return summary

def absorb_column(y,groups,weights,tolerance,checkpoint=None):
    """Alternating weighted orthogonal projections in the original metric."""
    n=len(y);den=[np.bincount(g,weights=weights) if weights is not None else np.bincount(g) for g in groups]
    initial=float(y@y) if weights is None else float(y@(weights*y));previous=initial
    for it in range(1,1001):
        biggest=0.
        for g,d in zip(groups,den):
            sums=np.bincount(g,weights=y if weights is None else weights*y,minlength=len(d))
            means=np.divide(sums,d,out=np.zeros_like(sums),where=d>0)
            biggest=max(biggest,float(np.max(np.abs(means))))
            y-=means[g]
        energy=float(y@y) if weights is None else float(y@(weights*y))
        require(np.isfinite(energy) and energy<=previous+1e-10*max(initial,1e-30),'Weighted FE projection increased norm')
        previous=energy
        if biggest<=tolerance:
            orth=0.
            for g,d in zip(groups,den):
                sums=np.bincount(g,weights=y if weights is None else weights*y,minlength=len(d))
                orth=max(orth,float(np.max(np.abs(np.divide(sums,d,out=np.zeros_like(sums),where=d>0)))))
            if orth<=tolerance:return y,dict(iterations=it,orthogonality=orth)
        if checkpoint is not None and it%25==0:checkpoint(it)
    raise RuntimeError('Weighted FE projection failed to converge')

def project_design(design,root,weighted=False):
    design=Path(design);root=Path(root);root.mkdir(parents=True,exist_ok=True)
    info=load(design/'design.json');n,p,width=info['n'],info['p'],info['width']
    base=np.memmap(design/'base.dat',dtype='float64',mode='r',shape=(n,p),order='F')
    groups=[np.load(design/f'group{k}.npy',mmap_mode='r') for k in range(3)]
    w=np.load(design/'weights.npy',mmap_mode='r') if weighted else None
    v=disk.disk_matrix(root/'absorbed.dat',n,p)
    maximum=1.
    for k in range(p):maximum=max(maximum,float(np.max(np.abs(base[:,k]))));release(base)
    tolerance=1e-10*maximum;diag=[];started=time.monotonic()
    for k in range(p):
        pressure_gate('FE column '+str(k+1))
        y=np.array(base[:,k]);release(base)
        y,d=absorb_column(y,groups,w,tolerance,lambda it:log(f'FE column {k+1}/{p}: {it} sweeps'))
        v[:,k]=y;del y;release(v);diag.append(d)
        for a in groups+([w] if w is not None else []):release(a)
        elapsed=time.monotonic()-started
        log(f'{"Recipient-weighted" if weighted else "Exposure-weighted"} FE {k+1}/{p}; {d["iterations"]} sweeps; remaining columns ETA {elapsed/(k+1)*(p-k-1)/60:.1f} min')
    del base,groups;gc.collect()
    gram=np.zeros((p-width,p-width));cross=np.zeros((p-width,width))
    for lo in range(0,n,BLOCK):
        hi=min(n,lo+BLOCK);x=np.array(v[lo:hi,width:],order='C');y=np.array(v[lo:hi,:width],order='C')
        if w is None:gram+=x.T@x;cross+=x.T@y
        else:
            wx=w[lo:hi,None]*x;gram+=x.T@wx;cross+=wx.T@y
        release(v)
    beta=np.linalg.pinv(gram,rcond=1e-12)@cross
    rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1.)*1e-12))
    res=disk.disk_matrix(root/'residual.dat',n,width)
    for lo in range(0,n,BLOCK):
        hi=min(n,lo+BLOCK);res[lo:hi]=v[lo:hi,:width]-v[lo:hi,width:]@beta;release(v);release(res)
    del v;(root/'absorbed.dat').unlink()
    save(root/'projection.json',dict(weighted=weighted,rank=rank,tolerance=tolerance,columns=diag,seconds=time.monotonic()-started,
        method='weighted group demeaning and weighted FWL; one column at a time; no iid covariance'))
    return res

def compute_terms(res,weights=None,include_s5=True,include_ols=True):
    n=len(res);width=res.shape[1];G=np.zeros((width,width))
    for lo in range(0,n,BLOCK):
        a=np.array(res[lo:lo+BLOCK]);wa=a if weights is None else weights[lo:lo+BLOCK,None]*a
        G+=a.T@wa;release(res)
    require(G[0,0]>1e-14 and abs(G[0,1])>1e-12,'No IV variation/first stage')
    terms=[]
    for idx,name in [(1,'first_stage'),(2,'rf_y'),(3,'rf_reached')]:
        terms.append(dict(term=name,outcome=['z','received','y','reached'][idx],beta=float(G[0,idx]/G[0,0]),
            den=float(G[0,0]),instrument=0,error_y=idx,error_x=0,sign=1.,scale=100*c.SD,
            units='percentage points per fixed reference Score A SD'))
    terms.append(dict(term='iv_y',outcome='y',beta=float(G[0,2]/G[0,1]),den=float(G[0,1]),instrument=0,
                      error_y=2,error_x=1,sign=1.,scale=100.,units='percentage points per receipt'))
    if include_ols:
        require(G[1,1]>1e-14,'No residual treatment variation for OLS')
        terms.append(dict(term='ols_y',outcome='y',beta=float(G[1,2]/G[1,1]),den=float(G[1,1]),instrument=1,
                          error_y=2,error_x=1,sign=1.,scale=100.,units='percentage points per receipt'))
    if include_s5:
        for idx,name,sign in [(4,'s5_mu1',1.),(5,'s5_mu0',-1.)]:
            terms.append(dict(term=name,outcome='y_times_d' if idx==4 else 'y_times_one_minus_d',
                beta=float(G[0,idx]/G[0,1]),den=float(G[0,1]),instrument=0,error_y=idx,error_x=1,
                sign=sign,scale=1.,units='probability; transformed-outcome IV diagnostic'))
        require(np.isclose(terms[-2]['beta']+terms[-1]['beta'],G[0,2]/G[0,1],atol=2e-10,rtol=2e-8),'S5 outcome-linearity identity failed')
    return terms

def influences(res,terms,weights=None):
    """Small-array helper also used by the independent dense tests."""
    columns=[]
    for t in terms:
        value=t['sign']*res[:,t['instrument']]*(res[:,t['error_y']]-t['beta']*res[:,t['error_x']])/t['den']
        if weights is not None:value=value*weights
        columns.append(value)
    return np.column_stack(columns)

def write_influences(design,res,terms,path,weighted=False,prefix='u_'):
    design=Path(design);actors={k:np.load(design/(k+'.npy'),mmap_mode='r') for k in ('row_id','recipient_id','opponent_id','date')}
    w=np.load(design/'weights.npy',mmap_mode='r') if weighted else None
    writer=None
    try:
        for lo in range(0,len(res),BLOCK):
            hi=min(len(res),lo+BLOCK);v=influences(np.array(res[lo:hi]),terms,None if w is None else w[lo:hi])
            data={k:a[lo:hi] for k,a in actors.items()};data.update({prefix+t['term']:v[:,j] for j,t in enumerate(terms)})
            table=pa.table(data)
            if writer is None:writer=pq.ParquetWriter(path,table.schema,compression='zstd')
            writer.write_table(table);release(res)
            for a in actors.values():release(a)
            if w is not None:release(w)
    finally:
        if writer is not None:writer.close()

def fit(design,root,weighted=False):
    root=Path(root);res=project_design(design,root,weighted)
    weights=np.load(Path(design)/'weights.npy',mmap_mode='r') if weighted else None
    terms=compute_terms(res,weights,include_s5=not weighted,include_ols=not weighted)
    write_influences(design,res,terms,root/'influence.parquet',weighted,'w_' if weighted else 'u_')
    del res,weights;gc.collect();(root/'residual.dat').unlink()
    save(root/'terms.json',terms)
    return terms

def covariance(path,cols,root,buckets=32):
    # One DuckDB thread, 1 decimal GB SQL limit; 64 MiB Arrow partition buffer.
    # Yield before each database connection if macOS reports memory pressure.
    original=bounded.connection
    def connection(folder,memory=1.):
        pressure_gate('covariance partition');return original(folder,1.)
    bounded.connection=connection
    try:return bounded.covariance(path,cols,root,1.,buckets=buckets)
    finally:bounded.connection=original

def merge_influences(left,right,out):
    a=pq.ParquetFile(left);b=pq.ParquetFile(right)
    require(a.metadata.num_rows==b.metadata.num_rows,'Joint influence row count mismatch')
    writer=None
    from itertools import zip_longest
    try:
        for aa,bb in zip_longest(a.iter_batches(batch_size=BLOCK,use_threads=False),b.iter_batches(batch_size=BLOCK,use_threads=False)):
            require(aa is not None and bb is not None,'Joint influence batches differ')
            x={k:aa.column(k) for k in aa.schema.names};y={k:bb.column(k) for k in bb.schema.names}
            for k in ('row_id','recipient_id','opponent_id','date'):
                require(x[k].equals(y[k]),'Joint influences do not align: '+k);y.pop(k)
            x.update(y);table=pa.table(x)
            if writer is None:writer=pq.ParquetWriter(out,table.schema,compression='zstd')
            writer.write_table(table)
    finally:
        if writer is not None:writer.close()

def result_rows(terms,V,meta,sample,weighted):
    rows=[]
    for k,t in enumerate(terms):
        r=dict(meta,sample=sample,weighting='1/n_i' if weighted else 'one per exposure',term=t['term'],outcome=t['outcome'],units=t['units'],
            generated_scores_treated_as_fixed=True,**old.inference90(t['sign']*t['beta'],float(V[k,k]),t['scale']))
        if t['term']=='first_stage':r['wald_F']=t['beta']**2/V[k,k] if V[k,k]>0 else None
        rows.append(r)
    return rows

def baseline_gate(rows,reference):
    ref={r['term']:r for r in reference['estimates']};actual={r['term']:r for r in rows}
    for term in ('first_stage','rf_y','rf_reached','iv_y'):
        for field in ('coefficient','standard_error'):
            require(actual[term]['supported'] and np.isclose(actual[term][field],ref[term][field],rtol=2e-7,atol=2e-7),
                    'Model 5 baseline replay failed: '+term+'/'+field)
    return dict(passed=True,terms_checked=['first_stage','rf_y','rf_reached','iv_y'],coefficient_and_SE=True,atol=2e-7,rtol=2e-7)
