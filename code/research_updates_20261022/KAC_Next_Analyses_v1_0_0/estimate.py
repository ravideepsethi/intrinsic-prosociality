"""Two-pass chooser FE OLS, chooser-cluster scores, and cluster-influence levels."""
from common import *
from design import design,select,dummy

def grouped(chooser):
    starts=np.r_[0,np.flatnonzero(np.diff(chooser))+1]
    counts=np.diff(np.r_[starts,len(chooser)])
    return starts,counts

def within(X,y,chooser):
    starts,counts=grouped(chooser)
    xb=np.add.reduceat(X,starts,axis=0)/counts[:,None]
    yb=np.add.reduceat(y,starts)/counts
    return X-np.repeat(xb,counts,axis=0),y-np.repeat(yb,counts),starts,counts

def read_bucket(files):
    import pyarrow as pa
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    frames=[pq.ParquetFile(p).read(use_threads=False).to_pandas(use_threads=False) for p in files]
    d=pd.concat(frames,ignore_index=True)
    return d.sort_values('chooser',kind='stable').reset_index(drop=True)

def moments(d,s):
    a=select(d,s);X,names,p,group,ng=design(a,s);y=a.y.to_numpy(float)*100
    k=X.shape[1]
    if len(a)==0:
        return dict(xx=np.zeros((k,k)),xy=np.zeros(k),f_sum=np.zeros(p),group_sum=np.zeros(ng),
            n=np.array(0),g=np.array(0),y_sum=np.array(0.),singletons=np.array(0),never=np.array(0),vary_g=np.array(0),vary_n=np.array(0)),names,p,ng
    Fsum=X[:,:p].sum(axis=0);group_sum=np.bincount(group,minlength=ng)
    W,v,starts,counts=within(X,y,a.chooser.to_numpy());del X
    varies=np.add.reduceat(np.square(W[:,:p]).sum(axis=1),starts)>1e-16
    m=dict(xx=W.T@W,xy=W.T@v,f_sum=Fsum,group_sum=group_sum,n=np.array(len(a)),g=np.array(len(starts)),y_sum=np.array(y.sum()),
      singletons=np.array((counts==1).sum()),never=np.array((np.add.reduceat(y,starts)==0).sum()),
      vary_g=np.array(varies.sum()),vary_n=np.array(counts[varies].sum()))
    return m,names,p,ng

def solve(xx,xy):
    # Normalize columns before rank detection. Dropped directions are recorded, not hidden.
    scale=np.sqrt(np.maximum(np.diag(xx),0));scale=np.where(scale>1e-12,scale,1.)
    A=xx/scale[:,None]/scale[None,:];values,vectors=np.linalg.eigh((A+A.T)/2)
    good=values>max(1e-10,float(values.max())*1e-10)
    B=(vectors[:,good]/values[good])@vectors[:,good].T
    inverse=B/scale[:,None]/scale[None,:]
    return inverse@xy,inverse,scale,vectors[:,~good],int(good.sum())

def meat(d,s,fit):
    a=select(d,s);X,names,p,group,ng=design(a,s);y=a.y.to_numpy(float)*100
    k=X.shape[1];dimension=1+p+ng+k
    if len(a)==0:return np.zeros((dimension,dimension))
    starts,counts=grouped(a.chooser.to_numpy())
    y0=np.add.reduceat(y,starts)-counts*fit['mean_y']
    f0=np.add.reduceat(X[:,:p],starts,axis=0)-counts[:,None]*fit['mean_f']
    c0=np.column_stack([np.add.reduceat((group==g).astype(float),starts) for g in range(ng)])-counts[:,None]*fit['group_share']
    W,v,_,_=within(X,y,a.chooser.to_numpy());del X
    u=v-W@fit['beta']
    score=np.add.reduceat(W*u[:,None],starts,axis=0)
    z=np.column_stack([y0,f0,c0,score])
    return z.T@z

def run_bucket(task):
    t0=time.monotonic();out=Path(task['out']);key=task['key']
    if valid(out,key):return dict(bucket=task['bucket'],seconds=0,reused=True)
    d=read_bucket(task['files']);result={}
    for j,s in enumerate(task['specs']):
        if task['phase']==1:
            m,_,_,_=moments(d,s)
            for name,value in m.items():result[f'm{j}_{name}']=value
        else:result[f'm{j}_meat']=meat(d,s,task['fits'][j])
    npz(out,**result);certify(out,key,dict(seconds=time.monotonic()-t0))
    return dict(bucket=task['bucket'],seconds=time.monotonic()-t0,reused=False)

def aggregate_first(paths,specs):
    sums={}
    for p in paths:
        with np.load(p,allow_pickle=False) as z:
            for n in z.files:sums[n]=sums.get(n,0)+z[n]
    # Shapes and term names come from the same deterministic design on a dummy row.
    template=dummy()
    fits=[]
    for j,s in enumerate(specs):
        m={k.removeprefix(f'm{j}_'):v for k,v in sums.items() if k.startswith(f'm{j}_')}
        _,names,p,_,ng=design(template,s);require(int(m['n'])>0,'Empty specification '+s['name'])
        b,inv,scale,null,rank=solve(m['xx'],m['xy'])
        fits.append(dict(beta=b,inverse=inv,scale=scale,null=null,rank=rank,names=names,p=p,ng=ng,
             mean_y=float(m['y_sum']/m['n']),mean_f=m['f_sum']/m['n'],group_share=m['group_sum']/m['n'],
             n=int(m['n']),g=int(m['g']),singletons=int(m['singletons']),never=int(m['never']),
             vary_g=int(m['vary_g']),vary_n=int(m['vary_n'])))
    return fits

def aggregate_meat(paths,specs):
    sums=[None]*len(specs)
    for p in paths:
        with np.load(p,allow_pickle=False) as z:
            for j in range(len(specs)):
                v=z[f'm{j}_meat'];sums[j]=v.copy() if sums[j] is None else sums[j]+v
    return sums

def estimable(fit,delta):
    q=np.asarray(delta)/fit['scale']
    return fit['null'].shape[1]==0 or np.linalg.norm(q@fit['null'])<=1e-7*max(np.linalg.norm(q),1e-12)

def coefficient_cov(fit,M):
    k=len(fit['beta']);factor=fit['g']/(fit['g']-1)
    return factor*fit['inverse']@M[-k:,-k:]@fit['inverse']

def level(fit,M,counter):
    # The standardization population is resampled with whole chooser clusters.
    # This includes sampling variation in baseline, composition, and slope jointly.
    p=fit['p'];ng=fit['ng'];k=len(fit['beta']);N=fit['n']
    delta=np.zeros(k);delta[:p]=fit['group_share']@counter-fit['mean_f']
    if not estimable(fit,delta):return np.nan,np.nan,False
    estimate=fit['mean_y']+delta@fit['beta']
    gradient=np.r_[1./N,-fit['beta'][:p]/N,(counter@fit['beta'][:p])/N,fit['inverse']@delta]
    var=fit['g']/(fit['g']-1)*float(gradient@M@gradient)
    return float(estimate),float(np.sqrt(max(0,var))),True
