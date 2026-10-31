from common import *
from design import *
from numerics import *
import gc

def read_model(path,spec,memory,spill):
    period,where,labels=selection(spec);c=db(spill,min(1.,max(.25,memory*.2)),1)
    try:
        c.execute('SET preserve_insertion_order=true')
        query=f'''SELECT chooser,y,deficit,eval10,stage_code,clock_c,clock_d,rating,rating_gap,
            date_code,(year(position_date)*12+month(position_date))::INTEGER month_code,{period} period
            FROM {scan(path)} WHERE {where}'''
        t=c.execute(query).fetch_arrow_table()
        require(all(t[x].null_count==0 for x in t.column_names),'Missing model value')
        d={x:t[x].combine_chunks().to_numpy(zero_copy_only=False) for x in t.column_names}
        return d,labels
    finally:c.close()

def setup(d,labels):
    require(np.isfinite(d['clock_c']).all() and np.isfinite(d['clock_d']).all(),'Nonfinite clocks')
    require((d['date_code']>=0).all() and (d['date_code']<1024).all(),'Date outside clustering namespace')
    require((d['chooser']>=0).all() and (d['chooser']<2**52).all(),'Invalid chooser ID')
    require((d['stage_code']>=0).all() and (d['stage_code']<=4).all(),'Invalid stage')
    g=encode([d['chooser'],d['eval10'].astype(np.int64)*10+d['stage_code']*2+d['period'],d['month_code']])
    mask,it=peel(g);before=len(mask)
    if not mask.all():d={k:v[mask] for k,v in d.items()};g=encode([x[mask] for x in g])
    return d,g,dict(input_rows=before,retained_rows=int(mask.sum()),singleton_rows_removed=int((~mask).sum()),singleton_rounds=it)

def column(d,j,G):
    nf=8*G
    if j<nf:
        p=j//8;deficit=[0,1,2,4,5,6,7,8][j%8]
        return ((d['period']==p)&(d['deficit']==deficit)).astype(float)
    p=(j-nf)//4;kind=(j-nf)%4
    z=(np.log1p(d['clock_c']) if kind==0 else np.log1p(d['clock_d']) if kind==1
       else d['rating_gap']/100. if kind==2 else d['rating']/100.)
    return np.asarray(z*(d['period']==p),float)

def names(labels):
    return [f'{p}:deficit{j}' for p in labels for j in (0,1,2,4,5,6,7,8)]+[
        f'{p}:{n}' for p in labels for n in ('log_clock_c','log_clock_d','gap100','rating100')]

def profile_maps(d,labels,k,beta):
    J=np.zeros((9*len(labels),k));mu=[];stats=[];anchors=[];valid=[]
    for g,label in enumerate(labels):
        m=d['period']==g;n=int(m.sum());shares=np.bincount(d['deficit'][m],minlength=9)/max(n,1)
        mean=100*float(d['y'][m].mean()) if n else 0.
        b=np.zeros(9);b[[0,1,2,4,5,6,7,8]]=beta[g*8:g*8+8]
        for deficit in range(9):
            row=g*9+deficit;J[row,g*8:g*8+8]=-shares[[0,1,2,4,5,6,7,8]]
            if deficit!=3:J[row,g*8+[0,1,2,4,5,6,7,8].index(deficit)]+=1
            mu.append(mean+J[row]@beta)
            mask=m&(d['deficit']==deficit)
            stats.append(dict(period=label,deficit=deficit,n=int(mask.sum()),grants=int(d['y'][mask].sum()),
                              raw_grant_percent=100*float(d['y'][mask].mean()) if mask.any() else None))
        anchors.append(np.where(m,(100*d['y']-mean-(b[d['deficit']]-shares@b))/max(n,1),0.))
    return np.asarray(mu),J,anchors,stats

def influence(ids,W,e,inverse,J,anchors):
    levels,g=np.unique(ids,return_inverse=True);g=g.astype(np.int32);k=W.shape[1]
    score=np.empty((len(levels),k))
    for j in range(k):score[:,j]=np.bincount(g,weights=np.asarray(W[:,j])*e,minlength=len(levels))
    result=score@(inverse@J.T);del score
    for p,v in enumerate(anchors):result[:,p*9:p*9+9]+=np.bincount(g,weights=v,minlength=len(levels))[:,None]
    return levels,result

def contrast_influence(ids,W,e,inverse,L):
    levels,g=np.unique(ids,return_inverse=True);g=g.astype(np.int32)
    # L contains coefficient contrasts; levels cancel the sample anchors.
    out=np.zeros((len(levels),len(L)));Q=inverse@L.T
    for lo in range(0,len(e),100000):
        scores=(np.asarray(W[lo:lo+100000])@Q)*e[lo:lo+100000,None]
        for j in range(len(L)):out[:,j]+=np.bincount(g[lo:lo+100000],weights=scores[:,j],minlength=len(levels))
    return levels,out

def fit_task(task):
    start=time.monotonic();out=Path(task['out']);out.mkdir(parents=True,exist_ok=True)
    source_stamp=stamp(task['source'])
    if task.get('source_stamp'):require(source_stamp==task['source_stamp'],'Prepared model input changed')
    key=task['key'];done=out/'DONE.json'
    if done.exists():
        r=read(done);require(r['key']==key,'Model key changed')
        for f in r['files']:verify(f)
        return {**r,'reused':True}
    d,labels=read_model(task['source'],task['spec'],task['memory'],out/'spill')
    if not len(d['y']):
        result=dict(key=key,id=task['id'],speed=task['speed'],spec=task['spec'],status='NO_ROWS',files=[],seconds=time.monotonic()-start)
        write(done,result);return result
    d,groups,counts=setup(d,labels);n=len(d['y']);G=len(labels);k=12*G
    if n<max(30,k*2):
        result=dict(key=key,id=task['id'],speed=task['speed'],spec=task['spec'],status='INSUFFICIENT_RETAINED_ROWS',counts=counts,files=[],seconds=time.monotonic()-start)
        write(done,result);return result
    cols=names(labels)+['outcome_pp'];folder=out/'columns';folder.mkdir(exist_ok=True)
    residual_files=[];diagnostics=[]
    array_hashes={name:hashlib.sha256(memoryview(np.ascontiguousarray(v)).cast('B')).hexdigest() for name,v in d.items()}
    layout=digest([key,n,counts,array_hashes])
    for j,name in enumerate(cols):
        dest=folder/f'{j:02}.npy';receipt=folder/f'{j:02}.json'
        if receipt.exists():
            rr=read(receipt);require(rr['layout']==layout,'Column layout changed');verify(rr['file']);diag=rr['diagnostic']
        else:
            raw=100*d['y'].astype(float) if j==k else column(d,j,G)
            log(task['id']+f': FE column {j+1}/{k+1} {name}')
            with heartbeat(task['id']+f': FE {j+1}/{k+1}'):
                residual,diag=absorb_column(raw,groups,progress=lambda it,sec:log(task['id']+f': column {j+1}, CG iteration {it}, elapsed {sec/60:.1f} min'))
            temp=dest.with_suffix('.partial.npy');np.save(temp,residual);os.replace(temp,dest)
            write(receipt,dict(layout=layout,file=record(dest),diagnostic=diag));del raw,residual
        residual_files.append(dest);diagnostics.append(diag)
    # Fortran layout keeps each already residualized column contiguous.
    matrix=out/'working.npy';W=np.lib.format.open_memmap(matrix,mode='w+',dtype='float64',shape=(n,k),fortran_order=True)
    for j,p in enumerate(residual_files[:-1]):W[:,j]=np.load(p,mmap_mode='r',allow_pickle=False)
    W.flush();y=np.load(residual_files[-1],mmap_mode='r',allow_pickle=False)
    fit=solve(W,y);beta=fit['beta'];e=np.array(y,copy=True)
    for lo in range(0,n,100000):e[lo:lo+100000]-=np.asarray(W[lo:lo+100000])@beta
    mu,J,anchors,stats=profile_maps(d,labels,k,beta)
    period_observed=[bool(np.any(d['period']==g)) for g in range(G)]
    ok=np.array([period_observed[i//9] and estimable(fit,j) for i,j in enumerate(J)]);profile_dim=len(mu)
    ids,inf=influence(d['chooser'],W,e,fit['inverse'],J,anchors);V=inf.T@inf
    npz(out/'chooser_profiles.npz',ids=ids,influence=inf);del ids,inf,anchors
    K=np.zeros((G*2,profile_dim))
    for g in range(G):
        for j,name in enumerate(KEY_CONTRASTS):K[g*2+j,g*9:g*9+9]=WEIGHTS[name]
    key_est=K@mu;key_ok=np.array([period_observed[i//2] and estimable(fit,j) for i,j in enumerate(K@J)]);key_cov=K@V@K.T
    files=[record(out/'chooser_profiles.npz')]
    if not task['spec'].get('month'):
        for kind,cluster in [('date',d['date_code']),('chooser_date',d['chooser'].astype(np.int64)*1024+d['date_code'])]:
            ids,inf=contrast_influence(cluster,W,e,fit['inverse'],K@J)
            npz(out/(kind+'.npz'),ids=ids,influence=inf);files.append(record(out/(kind+'.npz')))
    else:
        with np.load(out/'chooser_profiles.npz') as z:npz(out/'monthly_keys.npz',ids=z['ids'],influence=z['influence']@K.T)
        files.append(record(out/'monthly_keys.npz'))
    contrasts=[]
    for g,label in enumerate(labels):
        for name,w in WEIGHTS.items():
            l=np.zeros(profile_dim);l[g*9:g*9+9]=w;identified=period_observed[g] and estimable(fit,l@J)
            variance=float(l@V@l)
            contrasts.append(dict(period=label,contrast=name,estimate_pp=float(l@mu) if identified else None,
                se_pp=math.sqrt(max(0,variance)) if identified else None,estimable=identified))
    for i,row in enumerate(stats):
        row.update(adjusted_grant_percent=float(mu[i]) if ok[i] else None,
                   se_pp=float(np.sqrt(max(0,V[i,i]))) if ok[i] else None,estimable=bool(ok[i]))
    coefficients=[]
    for j,name in enumerate(cols[:-1]):
        v=np.zeros(k);v[j]=1.
        coefficients.append(dict(term=name,beta_pp=float(beta[j]),residual_sd=float(fit['residual_sd'][j]),estimable=estimable(fit,v)))
    summary=dict(key=key,id=task['id'],speed=task['speed'],spec=task['spec'],status='COMPLETE',labels=labels,counts=counts,
        retained_grants=int(d['y'].sum()),chooser_clusters=int(len(np.unique(d['chooser']))),
        date_clusters=int(len(np.unique(d['date_code']))),rank=fit['rank'],columns=k,
        profile=stats,contrasts=contrasts,coefficients=coefficients,fe_diagnostics=diagnostics,
        profile_values=mu,profile_estimable=ok,key_values=key_est,key_estimable=key_ok,
        specification_note='Speed-specific chooser FE; period-specific eval10-by-stage FE and control slopes',
        seconds=time.monotonic()-start)
    npz(out/'covariance.npz',profile=V,key=key_cov,beta=beta,inverse=fit['inverse'],null=fit['null'],scale=fit['scale'],profile_J=J)
    write(out/'MODEL.json',summary);files.extend([record(out/'MODEL.json'),record(out/'covariance.npz')])
    result=dict(key=key,id=task['id'],speed=task['speed'],spec=task['spec'],status='COMPLETE',counts=counts,
                out=str(out),files=files,seconds=time.monotonic()-start)
    require(stamp(task['source'])==source_stamp,'Prepared input changed during model fit')
    write(done,result)
    del W,y,e,d,groups;gc.collect();matrix.unlink(missing_ok=True)
    # Final fitted receipts replace intermediate column caches; interrupted fits keep them.
    shutil.rmtree(folder)
    return result
