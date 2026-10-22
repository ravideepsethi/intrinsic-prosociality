from __future__ import annotations
import contextlib, datetime as dt, hashlib, json, os, threading, time, zipfile
from pathlib import Path
import duckdb
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parent
DAY=86400000
VERSION='1.0.0'
def log(s): print(dt.datetime.now(dt.timezone.utc).strftime('[%Y-%m-%d %H:%M:%SZ] ')+str(s),flush=True)
def require(c,s):
    if not c: raise RuntimeError(s)
def qs(x): return "'"+str(x).replace("'","''")+"'"
def qi(x): return '"'+str(x).replace('"','""')+'"'
def read(p): return json.loads(Path(p).read_text())
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+'.partial');t.write_text(json.dumps(x,indent=2,default=str,allow_nan=False)+'\n');os.replace(t,p)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def signature(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
def records(db,sql):
    c=db.execute(sql);names=[x[0] for x in c.description];return [dict(zip(names,r)) for r in c.fetchall()]
def parq(paths):return 'read_parquet(['+','.join(qs(x) for x in paths)+'],hive_partitioning=false)'
def export(db,path,sql):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db.execute(f'COPY ({sql}) TO {qs(path)} (HEADER,FORMAT CSV)')
def checkpoint(path,key):
    p=Path(path);r=Path(str(p)+'.receipt.json')
    if not p.exists() or not r.exists():return False
    d=read(r);require(d['key']==key,'Checkpoint identity mismatch: '+str(p))
    require(d['sha256']==sha(p),'Checkpoint checksum mismatch: '+str(p));return True
def certify(path,key):dump(str(path)+'.receipt.json',dict(key=key,sha256=sha(path)))
def copy(db,path,sql,key):
    if checkpoint(path,key):return
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    t=Path(str(path)+'.partial');t.unlink(missing_ok=True)
    db.execute(f'COPY ({sql}) TO {qs(t)} (FORMAT PARQUET,COMPRESSION ZSTD)');os.replace(t,path);certify(path,key)
def table(path,rows,key):
    import pyarrow as pa
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);t=Path(str(p)+'.partial')
    pq.write_table(pa.Table.from_pylist(rows),t,compression='zstd');os.replace(t,p);certify(p,key)
def connect(run,threads=8,memory='6GB'):
    db=duckdb.connect();db.execute(f'SET threads={int(threads)}');db.execute(f'SET memory_limit={qs(memory)}')
    spill=Path(run)/'PRIVATE/spill';spill.mkdir(parents=True,exist_ok=True)
    db.execute(f'SET temp_directory={qs(spill)}');db.execute('SET preserve_insertion_order=false');return db
@contextlib.contextmanager
def heartbeat(message):
    stop=threading.Event()
    def beat():
        while not stop.wait(40):log(message+' — working')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()
def package_report(run,label):
    report=Path(run)/'report'
    overview(report)
    hashes={str(p.relative_to(report)):sha(p) for p in sorted(report.rglob('*')) if p.is_file() and p.name!='HASHES.json'}
    dump(report/'HASHES.json',hashes)
    dest=Path(run)/f'TENURE_RESPONSIBILITY_{label}_REPORT_v100.zip'
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'TENURE_RESPONSIBILITY_REPORT/'+str(p.relative_to(report)))
    Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n');log('REPORT_READY '+str(dest));return dest
def overview(report):
    lines=['# Tenure / responsibility results overview','',
      'Read coverage and support before interpreting estimates. Units: percentage points; bracketed values are 95% confidence intervals. These are descriptive screening estimates.','',
      '| Comparison | Estimate [95% CI] | Rows | Chooser / cluster count |','|---|---:|---:|---:|']
    queries=[]
    for age in ['all_sample','age_ge_30','age_ge_90','age_ge_365']:
        queries.append((f'TENURE_MODEL_{age}_gradient_full.json','competitive','Tenure gradient: '+age))
    for age in ['all','age_ge_90','age_ge_365']:
        for step in ['baseline','own_moves','all_proxies']:
            queries.append((f'RESP_MODEL_{age}_gradient_{step}.json','competitive','Responsibility gradient: '+age+', '+step))
    for fname,target,label in queries:
        p=report/fname
        if not p.exists():continue
        r=read(p);e=r.get('estimates',{}).get(target,{})
        value=f"{e['coefficient_pp']:.3f} [{e['ci_low_pp']:.3f}, {e['ci_high_pp']:.3f}]" if e.get('status')=='ESTIMATED' else r.get('status','Unsupported')
        lines.append(f"| {label} | {value} | {r.get('n','')} | {r.get('clusters','')} |")
    lines +=['','Population: probability sample of full chooser histories in the certified 41.5M main panel. Responsibility comparisons within each restriction use identical finite-score rows.','',
      'Next inspect NOVICE_GRANT_SHARE_CENSUS_BOUNDS.csv, TENURE_COVERAGE.csv, PERSISTENCE.csv, PERSISTENCE_RETENTION.csv, the PATRON_MODEL files, RESPONSIBILITY_COVERAGE.csv and RESPONSIBILITY_BOARD_BY_BLUNDER.csv.','',
      'Patron comparisons use the historical acquired August profile frame and are conditional on that selection. Review METHODS.md for all definitions and interpretation limits.']
    (report/'RESULTS_OVERVIEW.md').write_text('\n'.join(lines)+'\n')
def age_bin(expr):
    return f"CASE WHEN {expr} IS NULL THEN '9_unknown' WHEN {expr}<0 THEN '8_invalid' WHEN {expr}<7 THEN '0_0_6d' WHEN {expr}<30 THEN '1_7_29d' WHEN {expr}<90 THEN '2_30_89d' WHEN {expr}<365 THEN '3_90_364d' ELSE '4_365plus' END"
def loss_bin(expr):
    return f"CASE WHEN {expr} IS NULL THEN '9_missing' WHEN {expr}<0 THEN '0_improvement' WHEN {expr}<50 THEN '1_0_49' WHEN {expr}<100 THEN '2_50_99' WHEN {expr}<200 THEN '3_100_199' ELSE '4_200plus' END"
