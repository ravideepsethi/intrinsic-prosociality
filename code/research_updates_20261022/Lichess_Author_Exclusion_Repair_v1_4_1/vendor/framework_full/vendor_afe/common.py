"""I/O, authenticated input contracts, and bounded-memory regression helpers."""
from __future__ import annotations
import contextlib, datetime as dt, hashlib, json, math, os, platform, threading, time
from pathlib import Path
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

PKG = Path(__file__).resolve().parent
DAY = 86_400_000
PANEL_START = int(dt.datetime(2023,11,1,tzinfo=dt.timezone.utc).timestamp()*1000)
PANEL_END = int(dt.datetime(2025,11,1,tzinfo=dt.timezone.utc).timestamp()*1000)
REFERENCE_SD = 0.059411690344000595
IV_CONFIG = 'f14a1105a9f7'
SNAPSHOT_SHA = 'f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'

def log(s): print(f'[{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%SZ}] {s}',flush=True)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def read(p): return json.loads(Path(p).read_text())
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,np.ndarray):return clean(x.tolist())
    if isinstance(x,np.generic):return clean(x.item())
    if isinstance(x,Path):return str(x)
    if isinstance(x,float) and not math.isfinite(x):return None
    return x
def js(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(clean(x),indent=2,sort_keys=True,allow_nan=False)+'\n');tmp.replace(p)
def lit(x):return "'"+str(x).replace("'","''")+"'"
def ident(x):return '"'+str(x).replace('"','""')+'"'
def parq(ps):return 'read_parquet(['+','.join(lit(p) for p in ps)+'],hive_partitioning=false)'
def columns(c,table):return {r[0] for r in c.execute('DESCRIBE '+table).fetchall()}
def require(c,table,names):
    missing=set(names)-columns(c,table)
    if missing:raise RuntimeError(f'{table}: missing required columns {sorted(missing)}')
def copy(c,sql,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.tmp');c.execute(f'COPY ({sql}) TO {lit(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD)');tmp.replace(p)
def csv(c,sql,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    c.execute(f'COPY ({sql}) TO {lit(p)} (HEADER,DELIMITER ",")')
def connection(root,workers,memory):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    c=duckdb.connect(str(root/'work.duckdb'))
    c.execute(f'SET threads={int(workers)}');c.execute('SET memory_limit='+lit(memory))
    c.execute('SET temp_directory='+lit(root/'spill'));c.execute('SET preserve_insertion_order=false')
    return c
@contextlib.contextmanager
def heartbeat(label):
    event=threading.Event();start=time.monotonic()
    def beat():
        while not event.wait(45):log(f'{label}: working, {(time.monotonic()-start)/60:.1f} minutes')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try:yield
    finally:event.set();t.join()
def environment():
    return dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__)
def check_file(p,expected=None,size=None):
    p=Path(p)
    if not p.is_file():raise FileNotFoundError(str(p))
    if size is not None and p.stat().st_size!=size:raise RuntimeError('Input size changed: '+str(p))
    actual=sha(p)
    if expected and actual!=expected:raise RuntimeError('Input SHA-256 differs: '+str(p))
    return dict(path=str(p),bytes=p.stat().st_size,sha256=actual)
def resolve_inputs(project):
    """Exact contracts; never silently substitute the old 47.6M main sample."""
    project=Path(project).resolve();a=read(PKG/'evidence/main_sample_report.json')
    base=project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    files=[];records=[]
    with heartbeat('Authenticating the 24 main-panel files'):
        for e in a['panel_outputs']:
            p=base/e['relative_path'];records.append(check_file(p,e['sha256'],e['size_bytes']))
            if pq.ParquetFile(p).metadata.num_rows!=e['rows']:raise RuntimeError('Panel row count changed')
            files.append(str(p))
    if len(files)!=24 or sum(pq.ParquetFile(p).metadata.num_rows for p in files)!=41534331:raise RuntimeError('Wrong main sample')
    ivroot=project/'derived/replication/chooser_iv_expanded_v100_PRIVATE'/IV_CONFIG
    ivpath=ivroot/'analysis/spaced90.parquet';ivs=read(PKG/'evidence/expanded_summary.json')
    ivrec=next(e for e in ivs['analysis_validation']['files'] if e['path']=='spaced90.parquet')
    optional={};status={}
    if ivpath.is_file():
        records.append(check_file(ivpath,ivrec['sha256'],ivrec['bytes']));optional['iv']=str(ivpath)
        if pq.ParquetFile(ivpath).metadata.num_rows!=2682330:raise RuntimeError('Wrong IV cohort')
    else:status['iv']='MISSING_REVIEWED_IV_COHORT: '+str(ivpath)
    snapshot=project/'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
    if snapshot.is_file():records.append(check_file(snapshot,SNAPSHOT_SHA));optional['snapshot']=str(snapshot)
    else:status['snapshot']='MISSING_CERTIFIED_PROFILE_SNAPSHOT: '+str(snapshot)
    # Original all-source panel is used ONLY for pretreatment history, never as the main outcome population.
    broad=sorted((project/'derived/replication/analysis_panel_24m_sf100k').glob('month=*/analysis_panel.parquet'))
    if len(broad)==24 and sum(pq.ParquetFile(p).metadata.num_rows for p in broad)==47587020:
        optional['history']=[str(p) for p in broad]
        optional['history_metadata']=[dict(path=str(p),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns,rows=pq.ParquetFile(p).metadata.num_rows) for p in broad]
        status['history']='24_FILES_47587020_ROWS_METADATA_CHECKED; content hashes recorded when history is used'
    else:status['history']='UNAVAILABLE_ALL_SOURCE_HISTORY; recent reviewed IV histories remain usable'
    return dict(project=str(project),panels=files,records=records,status=status,**optional)
def view_panel(c,inputs):
    c.execute('CREATE OR REPLACE VIEW panel AS SELECT * FROM '+parq(inputs['panels']))
    require(c,'panel',['game_id','chooser_user_id','disconnected_user_id','kind_draw','fair_competitive','clearly_worse','utc_ms','api_last_move_at_ms','archive_ordinal'])
def verify_resume(root,signature):
    p=Path(root)/'_DONE.json'
    if not p.exists():return False
    d=read(p)
    if d['signature']!=signature:raise RuntimeError('Checkpoint signature mismatch')
    for e in d['files']:check_file(Path(root)/e['path'],e['sha256'],e['bytes'])
    return True
def done(root,signature,status='COMPLETE',extra=None):
    root=Path(root);files=[]
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.name not in ('_DONE.json','work.duckdb','work.duckdb.wal') and 'spill' not in p.parts:
            files.append(dict(path=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=sha(p)))
    js(root/'_DONE.json',dict(signature=signature,status=status,files=files,**(extra or {})))
def covariance_scalar_sql(c,table,score):
    """Shared-account OR date CR0, matching the existing IV dependence convention."""
    def ss(q):return float(c.execute('SELECT coalesce(sum(v*v),0) FROM ('+q+')').fetchone()[0])
    c.execute(f'CREATE OR REPLACE TEMP VIEW scores AS SELECT j,i,day,{score} AS s FROM {table}')
    account='SELECT j AS id,day,s FROM scores UNION ALL SELECT i,day,s FROM scores'
    va=ss('SELECT sum(s) v FROM ('+account+') GROUP BY id')
    vp=ss('SELECT sum(s) v FROM scores GROUP BY least(j,i),greatest(j,i)')
    vd=ss('SELECT sum(s) v FROM scores GROUP BY day')
    vad=ss('SELECT sum(s) v FROM ('+account+') GROUP BY id,day')
    vpd=ss('SELECT sum(s) v FROM scores GROUP BY least(j,i),greatest(j,i),day')
    return va-vp+vd-vad+vpd
def streaming_lpm(c,feature_sql,features,targets,root,chooser_fe=False):
    """Exact full-row OLS/FWL; regressors and sufficient statistics stay on disk."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    f=root/'features.parquet';copy(c,feature_sql,f)
    c.execute('CREATE OR REPLACE VIEW f AS SELECT * FROM '+parq([f]))
    n=int(c.execute('SELECT count(*) FROM f').fetchone()[0])
    if n<1000:return [dict(target=t,supported=False,reason='FEWER_THAN_1000_ROWS',rows=n) for t in targets]
    cols=['y']+features
    if chooser_fe:
        means=', '.join(f'avg({ident(x)}) AS {ident("m_"+x)}' for x in cols)
        c.execute('CREATE OR REPLACE TABLE means AS SELECT j,'+means+' FROM f GROUP BY j')
        q='SELECT f.j,f.i,f.day,'+','.join(f'f.{ident(x)}-m.{ident("m_"+x)} AS {ident(x)}' for x in cols)+' FROM f JOIN means m USING(j)'
        copy(c,q,root/'demeaned.parquet');c.execute('CREATE OR REPLACE VIEW r AS SELECT * FROM '+parq([root/'demeaned.parquet']))
    else:c.execute('CREATE OR REPLACE VIEW r AS SELECT * FROM f')
    p=len(features);gram=np.zeros((p,p));cross=np.zeros(p)
    reader=c.execute('SELECT '+','.join(map(ident,cols))+' FROM r').to_arrow_reader(131072)
    for b in reader:
        a=np.column_stack([b.column(k).to_numpy(zero_copy_only=False) for k in range(len(cols))]).astype(float)
        if not np.isfinite(a).all():raise RuntimeError('Nonfinite regression design')
        y,x=a[:,0],a[:,1:];gram+=x.T@x;cross+=x.T@y
    sd=np.sqrt(np.maximum(np.diag(gram),1e-30));g=gram/sd[:,None]/sd[None,:]
    ev,U=np.linalg.eigh(g);keep=ev>max(ev.max(),1)*1e-10
    inv=((U[:,keep]/ev[keep])@U[:,keep].T)/sd[:,None]/sd[None,:]
    beta=inv@cross;null=U[:,~keep];rank=int(keep.sum())
    fitted='+'.join(f'({beta[k]:.17g})*{ident(x)}' for k,x in enumerate(features))
    result=[]
    for name in targets:
        k=features.index(name)
        if null.shape[1] and np.linalg.norm(null[k,:])>1e-7:
            result.append(dict(target=name,supported=False,reason='TARGET_NOT_SEPARATELY_IDENTIFIED',rows=n,rank=rank));continue
        influence='+'.join(f'({inv[k,j]:.17g})*{ident(x)}' for j,x in enumerate(features))
        var=covariance_scalar_sql(c,'r',f'({influence})*(y-({fitted}))')
        out=dict(target=name,coefficient=beta[k],coefficient_pp=100*beta[k],rows=n,rank=rank,chooser_FE=chooser_fe,
                 clustering='shared_account_OR_date_CR0',supported=bool(var>0 and math.isfinite(var)))
        if out['supported']:
            se=math.sqrt(var);out.update(standard_error_pp=100*se,ci_low_pp=100*(beta[k]-1.959964*se),ci_high_pp=100*(beta[k]+1.959964*se),p_value=math.erfc(abs(beta[k]/se)/math.sqrt(2)))
        else:out['reason']='NONPOSITIVE_COVARIANCE_NOT_REPAIRED'
        result.append(out)
    js(root/'fit.json',dict(estimates=result,features=features,rank=rank,rows=n))
    return result
