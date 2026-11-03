from pathlib import Path
import csv, hashlib, json, os, shutil, time
import duckdb, pyarrow.parquet as pq

PACKAGE=Path(__file__).resolve().parents[1]
DAY=86400000
SD=.04979005187533171
X0=['recipient_rating','rating_gap','rating_gap_square','abs_rating_gap',
    'log_opponent_prior_decisions','log_opponent_prior_counterparts','opponent_history_expected_rate',
    'fair_history_present_90','log_fair_90','kind_ever_90','kind_rate_90','log_disconnect_90',
    'log_receipt_90','log_volume_30','log_claim_90']
ENV=['log_opponent_games90','opponent_observed_disconnect_rate','opponent_observed_chooser_rate']
RAW=['row_id','recipient_id','opponent_id','archive_start_ms','month_code','tc_base_s','tc_inc_s',
     'recipient_rating','opponent_rating','received','y','reached','fair_90','kind_90','disconnect_90',
     'receipt_90','claim_90','pre_games_30d','environment_supported']+ENV

def require(ok,message):
    if not ok:raise RuntimeError(message)
def log(message):print(time.strftime('[%Y-%m-%d %H:%M:%S UTC] ',time.gmtime())+message,flush=True)
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def cfgsha(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n');os.replace(tmp,p)
def lit(x):return "'"+str(x).replace("'","''")+"'"
def qi(x):return '"'+x.replace('"','""')+'"'
def parq(p):return 'read_parquet('+lit(p)+')'
def checked(p,digest,size=None):
    p=Path(p);require(p.is_file(),'Required input absent: '+str(p))
    require(size is None or p.stat().st_size==int(size),'File size changed: '+str(p))
    require(sha(p)==digest,'SHA256 changed: '+str(p));return p
def relocate(p,project):
    p=Path(p).expanduser()
    if not p.is_absolute():return project/p
    if p.is_relative_to(project):return p
    require('lichess_kindness' in p.parts,'Cannot relocate source path: '+str(p))
    return project.joinpath(*p.parts[p.parts.index('lichess_kindness')+1:])
def connect(folder,threads,memory):
    c=duckdb.connect();c.execute('SET threads='+str(threads));c.execute('SET memory_limit='+lit(str(memory)+'GiB'))
    c.execute('SET temp_directory='+lit(Path(folder)/'spill'));c.execute('SET preserve_insertion_order=false');return c
def records(c,sql):
    cur=c.execute(sql);keys=[x[0] for x in cur.description];return [dict(zip(keys,r)) for r in cur.fetchall()]
def copy(c,sql,p):c.execute('COPY ('+sql+') TO '+lit(p)+' (FORMAT PARQUET,COMPRESSION ZSTD)')
def table(p,data):
    data=list(data);save(Path(p).with_suffix('.json'),data)
    keys=sorted(set().union(*(x.keys() for x in data))) if data else ['status']
    with Path(p).with_suffix('.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,keys);w.writeheader()
        for x in data:w.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in x.items()})
def row_digest(ids):
    import numpy as np
    return hashlib.sha256(np.sort(np.asarray(ids,dtype='<i8')).tobytes()).hexdigest()
def verify_stage(folder,conf):
    folder=Path(folder);r=load(folder/'_DONE.json');require(r['config_sha256']==conf,'Stage configuration mismatch: '+folder.name)
    for x in r['files']:checked(folder/x['path'],x['sha256'],x['bytes'])
    return r
def stage(root,name,conf,build):
    folder=Path(root)/name
    if folder.exists():verify_stage(folder,conf);log('Reuse verified stage '+name);return folder
    tmp=folder.with_name(folder.name+'.partial')
    if tmp.exists():shutil.rmtree(tmp)
    tmp.mkdir(parents=True);result=build(tmp)
    if (tmp/'spill').exists():shutil.rmtree(tmp/'spill')
    files=[dict(path=str(p.relative_to(tmp)),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(tmp.rglob('*')) if p.is_file()]
    save(tmp/'_DONE.json',dict(config_sha256=conf,result=result,files=files));os.replace(tmp,folder);return folder
