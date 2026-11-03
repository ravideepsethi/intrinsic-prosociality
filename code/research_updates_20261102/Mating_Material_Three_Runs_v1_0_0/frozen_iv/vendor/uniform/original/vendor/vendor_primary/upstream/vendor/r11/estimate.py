"""Two-pass exact chooser absorption; all columns share rows and group moments."""
from common import *
from design import design,moments_design,COLS

def grouped(ids):
    start=np.r_[0,np.flatnonzero(ids[1:]!=ids[:-1])+1]
    return start,np.diff(np.r_[start,len(ids)])

def read_bucket(paths):
    import pyarrow as pa
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    d=pd.concat([pq.ParquetFile(p).read(use_threads=False).to_pandas(use_threads=False) for p in paths],ignore_index=True)
    return d.sort_values('chooser',kind='stable').reset_index(drop=True)

def demean(X,y,start,count):
    # In-place subtraction in bounded blocks; avoids a full repeat-sized temporary.
    xm=np.add.reduceat(X,start,axis=0)/count[:,None]
    ym=np.add.reduceat(y,start)/count
    for a in range(0,len(start),2048):
        b=min(a+2048,len(start));lo=start[a];hi=start[b] if b<len(start) else len(y)
        X[lo:hi]-=np.repeat(xm[a:b],count[a:b],axis=0)
        y[lo:hi]-=np.repeat(ym[a:b],count[a:b])

def first(d):
    X,names,indices=design(d);M,mnames=moments_design(d)
    y=d.y.to_numpy(float)*100;start,count=grouped(d.chooser.to_numpy())
    ysum=y.sum();msum=M.sum(axis=0);del M
    # Defined exactly as requested: rows belonging to choosers with >=2 opportunities.
    within_rows=count[count>=2].sum();within_groups=(count>=2).sum()
    demean(X,y,start,count)
    var_pos=np.add.reduceat(np.sum(X[:,:4]**2,axis=1),start)>1e-16
    stages=d.stage.to_numpy();var_stage=np.maximum.reduceat(stages,start)!=np.minimum.reduceat(stages,start)
    return dict(xx=X.T@X,xy=X.T@y,n=np.array(len(d)),g=np.array(len(count)),sum_y=np.array(ysum),sum_m=msum,
      within_n=np.array(within_rows),within_g=np.array(within_groups),position_vary_n=np.array(count[var_pos].sum()),stage_vary_n=np.array(count[var_stage].sum())),names,indices,mnames

def solve(xx,xy):
    scales=np.sqrt(np.maximum(np.diag(xx),0));scales=np.where(scales>1e-12,scales,1.)
    A=xx/scales[:,None]/scales[None,:];vals,vec=np.linalg.eigh((A+A.T)/2)
    tol=max(1e-11,float(vals.max())*1e-10)
    require(vals.min()>=-tol*10,'Crossproducts have a materially negative eigenvalue')
    good=vals>tol;require(good.any(),'No within-chooser identifying variation')
    inv=((vec[:,good]/vals[good])@vec[:,good].T)/scales[:,None]/scales[None,:]
    beta=inv@xy
    residual=np.linalg.norm((xx@beta-xy)/scales)/max(1.,np.linalg.norm(xy/scales))
    require(residual<1e-7,'Normal equations failed the numerical residual gate')
    return dict(beta=beta,bread=inv,scale=scales,null=vec[:,~good],rank=int(good.sum()),normal_equation_error=float(residual),eigenvalue_min=float(vals.min()),eigenvalue_max=float(vals.max()))

def second(d,fit):
    X,names,indices=design(d);M,mnames=moments_design(d);y=d.y.to_numpy(float)*100
    start,count=grouped(d.chooser.to_numpy());ng=len(count)
    centered=(np.add.reduceat(M,start,axis=0)-count[:,None]*fit['mean_m'])/fit['n'];del M
    demean(X,y,start,count)
    result={}
    for col in COLS:
        ix=np.asarray(indices[col]);f=fit['fits'][col];W=X[:,ix]
        u=y-W@f['beta'];score=np.empty((ng,len(ix)))
        for a in range(0,ng,2048):
            b=min(a+2048,ng);lo=start[a];hi=start[b] if b<ng else len(y)
            score[a:b]=np.add.reduceat(W[lo:hi]*u[lo:hi,None],start[a:b]-lo,axis=0)
        psi=np.column_stack([score@f['bread'],centered])
        result[col]=psi.T@psi
        del W,u,score,psi
    return result

def task(t):
    out=Path(t['out']);t0=time.monotonic()
    if valid(out,t['key']):return dict(bucket=t['bucket'],seconds=0,reused=True)
    d=read_bucket(t['files'])
    if t['phase']==1:r=first(d)[0]
    else:r=second(d,t['fit'])
    npz(out,**r);certify(out,t['key'])
    return dict(bucket=t['bucket'],seconds=time.monotonic()-t0,reused=False)

def combine(paths):
    total={}
    for path in paths:
        with np.load(path,allow_pickle=False) as z:
            for k in z.files:total[k]=total.get(k,0)+z[k]
    return total

def fit_first(paths,names,indices,mnames):
    s=combine(paths);r={k:int(s[k]) for k in ['n','g','within_n','within_g','position_vary_n','stage_vary_n']}
    r.update(mean_y=float(s['sum_y']/r['n']),mean_m=s['sum_m']/r['n'],moment_names=mnames,fits={})
    for col in COLS:
        ix=indices[col];f=solve(s['xx'][np.ix_(ix,ix)],s['xy'][ix]);f['names']=[names[i] for i in ix];r['fits'][col]=f
    return r
