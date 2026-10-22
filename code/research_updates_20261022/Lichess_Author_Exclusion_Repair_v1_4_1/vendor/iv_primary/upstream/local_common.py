"""Shared local I/O and statistical primitives; no network or source mutations."""
from __future__ import annotations
import contextlib, csv, hashlib, json, math, os, sys, threading, time
from pathlib import Path
import numpy as np
from scipy.stats import norm, chi2

ROOT = Path(__file__).resolve().parent
MONTHS = [f'{2023+(10+i)//12:04d}-{(10+i)%12+1:02d}' for i in range(24)]
STAGES = ['0_4','5_6','7_8','9_10','11_20','21_40','41_80','81_plus']
SPEEDS = ['ultrabullet','bullet','blitz','rapid','classical']
EVALS = ['m100_m50','m50_0','0_50','50_100','100_200','200_300','300_600','600_plus_or_mate']
SD = 0.04979005187533171
DAY = 86400000

def require(condition, message):
    if not condition: raise RuntimeError(message)

def log(message):
    print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+' '+str(message),flush=True)

@contextlib.contextmanager
def heartbeat(message):
    stop=threading.Event(); start=time.monotonic()
    def pulse():
        while not stop.wait(45): log(f'{message}; elapsed {(time.monotonic()-start)/60:.1f} min')
    t=threading.Thread(target=pulse,daemon=True);t.start()
    try: yield
    finally: stop.set();t.join()

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def serial(value):
    if isinstance(value,Path): return str(value)
    if isinstance(value,np.ndarray): return value.tolist()
    if isinstance(value,np.generic): return value.item()
    raise TypeError(type(value).__name__)

def key(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=serial,allow_nan=False).encode()).hexdigest()

def load(path):
    with open(path) as f: return json.load(f)

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(value,indent=2,default=serial,allow_nan=False)+'\n');os.replace(temp,path)

def csv_out(path,rows,fields=None):
    rows=list(rows);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fields=fields or list(dict.fromkeys(k for r in rows for k in r))
    require(bool(fields),'Cannot write an untyped empty CSV: '+str(path))
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='raise');w.writeheader()
        for r in rows:
            w.writerow({k:json.dumps(v,default=serial) if isinstance(v,(dict,list,tuple)) else v for k,v in r.items()})
    os.replace(temp,path)

def quote(value): return "'"+str(value).replace("'","''")+"'"
def parq(paths):
    return 'read_parquet(['+','.join(quote(p) for p in paths)+'],hive_partitioning=false,union_by_name=true)'

def db(folder,memory=7,threads=1):
    import duckdb
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    c=duckdb.connect();c.execute(f"SET memory_limit='{memory}GB'")
    c.execute(f'SET threads={int(threads)}');c.execute('SET temp_directory='+quote(folder));c.execute('SET preserve_insertion_order=false')
    return c

def copy_query(c,query,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp')
    c.execute('COPY ('+query+') TO '+quote(tmp)+' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)');os.replace(tmp,path)

def snapshot(path):
    p=Path(path);s=p.stat();return dict(path=str(p.resolve()),bytes=s.st_size,mtime_ns=s.st_mtime_ns)

def cached(path,k):
    path=Path(path);receipt=Path(str(path)+'.ok.json')
    if not path.exists() or not receipt.exists(): return False
    r=load(receipt);require(r['key']==k,'Checkpoint belongs to different inputs/options: '+str(path))
    require(sha(path)==r['sha256'],'Checkpoint checksum changed: '+str(path));return True

def seal(path,k): save(str(path)+'.ok.json',dict(key=k,sha256=sha(path)))

def npz(path,**arrays):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    with tmp.open('wb') as f:np.savez_compressed(f,**arrays)
    os.replace(tmp,p)

def solve(xx,xy):
    """R11 scaled eigensolve, including its null-space estimability certificate."""
    scales=np.sqrt(np.maximum(np.diag(xx),0));scales=np.where(scales>1e-12,scales,1.)
    a=xx/scales[:,None]/scales[None,:];vals,vec=np.linalg.eigh((a+a.T)/2)
    tol=max(1e-11,float(vals.max())*1e-10);require(vals.min()>=-10*tol,'Indefinite crossproduct')
    good=vals>tol;require(good.any(),'No identifying variation')
    bread=((vec[:,good]/vals[good])@vec[:,good].T)/scales[:,None]/scales[None,:]
    beta=bread@xy;error=np.linalg.norm((xx@beta-xy)/scales)/max(1.,np.linalg.norm(xy/scales))
    require(error<1e-7,'Normal equations failed')
    return dict(beta=beta,bread=bread,scale=scales,null=vec[:,~good],rank=int(good.sum()))

def estimable(w,fit):
    w=np.atleast_2d(w)
    return np.linalg.norm((w/fit['scale'])@fit['null'],axis=1)<1e-7

def inference(b,var):
    b=float(b);var=float(var)
    if not np.isfinite(var) or var<0:
        return dict(estimate=b,se=None,p=None,ci_low=None,ci_high=None,status='INVALID_VARIANCE')
    se=math.sqrt(var);p=float(2*norm.sf(abs(b/se))) if se else (1. if b==0 else 0.)
    return dict(estimate=b,se=se,p=p,ci_low=b-1.959963984540054*se,ci_high=b+1.959963984540054*se,status='ESTIMATED')

def ratio_stats(E,R,V):
    """V is in [E,R] order. Never stabilize a ratio by changing its denominator."""
    ef=inference(E,V[0,0]);rf=inference(R,V[1,1])
    out=dict(E=float(E),E_se=ef['se'],R=float(R),R_se=rf['se'],cov_E_R=float(V[0,1]))
    if not np.isfinite(E) or abs(E)<1e-14:
        return dict(out,ratio=None,se=None,ci_low=None,ci_high=None,weak_denominator=True,status='ZERO_DENOMINATOR')
    grad=np.array([-R/E**2,1/E]);fit=inference(R/E,grad@V@grad)
    weak=ef['ci_low'] is None or ef['ci_low']<=0<=ef['ci_high']
    return dict(out,ratio=fit['estimate'],se=fit['se'],ci_low=fit['ci_low'],ci_high=fit['ci_high'],weak_denominator=weak,status=fit['status'])

def wald(b,V,df=None):
    b=np.asarray(b,float);V=(np.asarray(V,float)+np.asarray(V,float).T)/2
    ev=np.linalg.eigvalsh(V);df=len(b) if df is None else df
    if len(b)!=df or not np.isfinite(ev).all() or ev.min()<=max(1e-30,float(abs(ev).max()))*1e-10:
        return dict(wald_chi2=None,df=df,p=None,status='SINGULAR_OR_NONPOSITIVE_COVARIANCE')
    q=float(b@np.linalg.solve(V,b));return dict(wald_chi2=q,df=df,p=float(chi2.sf(q,df)),status='ESTIMATED')

def cluster_sums(x,groups):
    x=np.asarray(x);x=x[:,None] if x.ndim==1 else x
    _,ix=np.unique(groups,return_inverse=True);G=int(ix.max())+1
    s=np.column_stack([np.bincount(ix,weights=x[:,j],minlength=G) for j in range(x.shape[1])])
    return s,G

def stage_code(p):return np.searchsorted([4,6,8,10,20,40,80],p,side='left')

def eval_code(cp):
    cp=np.asarray(cp,float);require(np.isfinite(cp).all() and (cp>=-100).all(),'Evaluation outside competitive model')
    # 100 belongs to [50,100]; 200 to (100,200]; 300 to [300,600).
    return np.select([cp< -50,cp<0,cp<50,cp<=100,cp<=200,cp<300,cp<600],range(7),default=7).astype(np.int8)

def gap_basis(raw):
    x=np.asarray(raw,float);ok=np.isfinite(x);g=np.clip(np.where(ok,x,0),-600,600)/100
    return np.column_stack([g]+[np.maximum(g-k,0) for k in [-3,-1,0,1,3]]+[ok&(x< -600),ok&(x>600),~ok])

def add_logs(d,arrays,names,full=True):
    for role in ['clock_c','clock_d']:
        x=d[role].to_numpy(float);ok=np.isfinite(x)&(x>=0)
        arrays.extend([np.log1p(np.where(ok,x,0)),~ok]);names.extend(['log1p_'+role,'missing_'+role])
    if full:
        for role in ['premium','rd_c','rd_d']:
            x=d[role].to_numpy(float);ok=np.isfinite(x)&(x>0);z=np.log(np.where(ok,x,1))
            arrays.extend([z,z*z,~ok]);names.extend(['log_'+role,'log_'+role+'_sq','missing_'+role])

def competitive_design(d,account_fe=True):
    arrays=[];names=[]
    if not account_fe: arrays.append(np.ones(len(d)));names.append('intercept')
    codes=eval_code(d.board)
    for k in range(8):
        if k!=2: arrays.append(codes==k);names.append('eval_'+EVALS[k])
    for k in range(1,8): arrays.append(d.stage.to_numpy()==k);names.append('stage_'+STAGES[k])
    for k in range(1,24):arrays.append(d.month_code.to_numpy()==k);names.append('month_'+MONTHS[k])
    for k in [0,2,3,4]:arrays.append(d.speed_code.to_numpy()==k);names.append('speed_'+SPEEDS[k])
    H=gap_basis(d.gap)
    for j in range(9):arrays.append(H[:,j]);names.append('gap_'+str(j))
    add_logs(d,arrays,names,full=account_fe)
    return np.column_stack(arrays).astype(float),names

def exchange_contrasts(names):
    W=np.zeros((4,len(names)))
    W[0,names.index('eval_50_100')]=1;W[0,names.index('eval_m50_0')]=-1
    W[2,names.index('eval_300_600')]=1
    for row,hi,lo in [(1,100,-100),(3,300,0)]:
        a=gap_basis([hi])[0]-gap_basis([lo])[0]
        for j,v in enumerate(a):W[row,names.index('gap_'+str(j))]=v
    return W
