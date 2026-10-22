"""Bounded-memory I/O and explicit input contracts for the disruption screen."""
from __future__ import annotations
import contextlib,datetime as dt,hashlib,json,math,os,re,threading,time
from pathlib import Path
import duckdb,numpy as np,pyarrow.parquet as pq
PKG=Path(__file__).resolve().parent
MINUTE=60000;DAY=86400000
MONTHS=[f'{v//12:04d}-{v%12+1:02d}' for v in range(2023*12+10,2025*12+10)]
def ms(s):return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
START=ms('2023-11-01');END=ms('2025-11-01')
SPEEDS=['ultrabullet','bullet','blitz','rapid','classical']
def bounds(m):
 y,n=map(int,m.split('-'));return ms(m+'-01'),ms(f'{y+(n==12):04d}-{n%12+1:02d}-01')
def utc(t):return dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).isoformat()
def log(s):print(f'[{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%SZ}] {s}',flush=True)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,Path):return str(x)
 if isinstance(x,float) and not math.isfinite(x):return None
 return x
def js(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name(p.name+'.tmp')
 q.write_text(json.dumps(clean(x),indent=2,sort_keys=True,allow_nan=False)+'\n');q.replace(p)
def read(p):return json.loads(Path(p).read_text())
def sig(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def lit(x):return "'"+str(x).replace("'","''")+"'"
def ident(x):return '"'+str(x).replace('"','""')+'"'
def parq(ps):return 'read_parquet(['+','.join(lit(p) for p in ps)+'],hive_partitioning=false,union_by_name=true)'
def relocate(project,p):
 p=Path(p)
 if p.is_absolute():p=p.relative_to('/Volumes/XT_Pro/lichess_kindness')
 r=(Path(project)/p).resolve()
 if not r.is_relative_to(Path(project).resolve()):raise ValueError('Input outside project')
 return r
@contextlib.contextmanager
def heartbeat(label):
 e=threading.Event()
 def beat():
  while not e.wait(40):log(label+' — working')
 t=threading.Thread(target=beat,daemon=True);t.start()
 try:yield
 finally:e.set();t.join()
def connect(root,workers=4,memory='6GB'):
 root=Path(root);root.mkdir(parents=True,exist_ok=True);c=duckdb.connect(str(root/'work.duckdb'))
 c.execute(f'SET threads={int(workers)}');c.execute('SET memory_limit='+lit(memory));c.execute('SET temp_directory='+lit(root/'spill'));c.execute('SET preserve_insertion_order=false');return c
def copy(c,sql,p):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
 c.execute(f'COPY ({sql}) TO {lit(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)');tmp.replace(p)
def csv(c,sql,p):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);c.execute(f'COPY ({sql}) TO {lit(p)} (HEADER, DELIMITER ",")')
def records(ps):
 out=[]
 for p in ps:
  p=Path(p);s=p.stat();pf=pq.ParquetFile(p)
  out.append(dict(path=str(p),bytes=s.st_size,mtime_ns=s.st_mtime_ns,sha256=sha(p),rows=pf.metadata.num_rows,columns=pf.schema_arrow.names))
 return out
def resumed(root,signature):
 p=Path(root)/'_DONE.json'
 if not p.exists():return False
 d=read(p)
 if d['signature']!=signature:return False
 for r in d['files']:
  f=Path(root)/r['path']
  if not f.is_file() or f.stat().st_size!=r['bytes'] or sha(f)!=r['sha256']:return False
 return True
def done(root,signature,paths,extra=None):
 root=Path(root);js(root/'_DONE.json',dict(signature=signature,files=[dict(path=str(Path(p).relative_to(root)),bytes=Path(p).stat().st_size,sha256=sha(p)) for p in paths],extra=extra or {}))
# Legacy white_name/black_name are observed in the returned curated lookup schema.
# See evidence/legacy_schema_report.json. No choice-panel aliases are inferred.
ALIASES={'game_id':['game_id','id'],'status':['api_status','status'],
 'start_ms':['created_at_ms','api_created_at_ms','createdAt'],
 't':['last_move_at_ms','api_last_move_at_ms','lastMoveAt'],
 'white':['white_username_norm','white_username','white_name'],'black':['black_username_norm','black_username','black_name'],
 'speed':['speed','api_speed'],'rated':['rated','api_rated'],'variant':['variant','api_variant']}
def mapping(cols):
 out={k:[v for v in names if v in cols] for k,names in ALIASES.items()}
 missing=[k for k,v in out.items() if not v]
 if missing:raise ValueError('Required raw API fields unavailable: '+','.join(missing))
 return out

def norm_expr(k,col):
 a=ident(col)
 if k in ('start_ms','t'):return f'try_cast({a} AS BIGINT)'
 if k=='rated':return f'try_cast({a} AS BOOLEAN)'
 if k=='game_id':return f'cast({a} AS VARCHAR)'
 return f"nullif(lower(trim(cast({a} AS VARCHAR))),'')"
def normal_sql(ps):
 cols=set().union(*(set(pq.ParquetFile(p).schema_arrow.names) for p in ps));m=mapping(cols)
 fields=[];conflicts=[]
 for k,names in m.items():
  expr=[norm_expr(k,n) for n in names];fields.append((expr[0] if len(expr)==1 else 'coalesce('+','.join(expr)+')')+' AS '+ident(k))
  for a in range(len(expr)):
   for b in range(a):conflicts.append(f'({expr[a]} IS NOT NULL AND {expr[b]} IS NOT NULL AND {expr[a]}<>{expr[b]})')
 return 'SELECT '+','.join(fields)+',('+(' OR '.join(conflicts) or 'FALSE')+') AS alias_conflict FROM '+parq(ps)
def fold_sql():
 def bit(k):return f"(strpos('0123456789abcdef',substr(md5('disruption-v100| '||{k}),1,1))%2)"
 return f'CASE WHEN white IS NULL OR black IS NULL THEN 3 WHEN {bit("white")}={bit("black")} THEN {bit("white")} ELSE 2 END'
def player_bit(s):return (int(hashlib.md5(('disruption-v100| '+s.lower().strip()).encode()).hexdigest()[0],16)+1)%2

# Frozen upstream counts. They establish coverage, not a new certified outage population.
LEGACY_COUNTS=dict(zip(MONTHS[:11],[7183319,7448160,7450435,7012824,7333233,7015289,7304894,6913168,6958044,7096917,6796664]))
BRIDGE_COUNTS=dict(zip(MONTHS[11:21],[7280463,6920848,7327917,7499540,6780461,7371390,7007508,7209483,6937046,7111923]))

def legacy_month(path):
 """Bind the monthly lookup leaf, never dates in ancestor batch names."""
 for part in reversed(Path(path).parts[:-1]):
  match=re.fullmatch(r'(20\d{2}-(?:0[1-9]|1[0-2]))_lookup(?:_.*)?',part)
  if match:return match.group(1)
 raise ValueError('No explicit YYYY-MM_lookup directory in curated path')

def legacy_schema(path,month):
 """Footer-only diagnostics; never expose player names or game records."""
 p=Path(path);pf=pq.ParquetFile(p);names=pf.schema_arrow.names
 return dict(month=month,path=str(p),rows=pf.metadata.num_rows,bytes=p.stat().st_size,
   fields=[dict(name=f.name,type=str(f.type)) for f in pf.schema_arrow],
   missing_required_fields=[k for k,v in ALIASES.items() if not any(n in names for n in v)])

def discover(project,diagnostics=None):
 """Only canonical Stage04 responses or the historical curated selector; no recursive pile mixing."""
 project=Path(project);root=project/'derived/replication/api_timeout_enrichment';out=[];issues=[]
 for m in MONTHS:
  d=root/('month='+m);ps=sorted(d.glob('responses/unit-*.parquet'))
  if not ps:continue
  markers=[]
  for p in sorted(d.glob('*.json')):
   try:
    r=read(p)
    if isinstance(r,dict) and r.get('final_ok') is True and r.get('month',m)==m:markers.append((p,r))
   except (ValueError,OSError):continue
  try:
   if not markers:raise ValueError('No completed month final_ok receipt')
   expected={int(r.get('returned_unique_ids',r.get('selected_rows',-1))) for _,r in markers}
   if len(expected)!=1 or next(iter(expected))<=0:raise ValueError('Ambiguous completion counts')
   n=next(iter(expected));meta=sum(pq.ParquetFile(p).metadata.num_rows for p in ps)
   if meta!=n:raise ValueError(f'Response rows {meta} != completion rows {n}')
   if m in BRIDGE_COUNTS and n!=BRIDGE_COUNTS[m]:raise ValueError('Frozen bridge count differs')
   if any(int(r.get('missing_ids',0))!=0 for _,r in markers):raise ValueError('Incomplete responses')
   for p in ps:mapping(pq.ParquetFile(p).schema_arrow.names)
   out.append(dict(month=m,source='canonical_stage04',paths=list(map(str,ps)),expected_rows=n,receipts=[dict(path=str(p),sha256=sha(p)) for p,_ in markers]))
  except Exception as e:issues.append(dict(month=m,source='canonical_stage04',reason=str(e)))
 selected={r['month'] for r in out}
 selector=project/'output/api_enrichment_canonical_inventory_20260601_163807/canonical_lookup_parquet_paths.txt'
 if selector.is_file():
  grouped={m:[] for m in MONTHS[:11]}
  for line in selector.read_text().splitlines():
   if not line.strip():continue
   try:
    p=relocate(project,line.strip());m=legacy_month(p)
   except ValueError as e:
    issues.append(dict(source='curated_legacy',reason=str(e),path=line.strip()));continue
   if m in grouped:grouped[m].append(p)
   elif diagnostics is not None:diagnostics.append(dict(path=str(p),month=m,status='OUTSIDE_LEGACY_WINDOW'))
  for m,ps in grouped.items():
   if m in selected or not ps:continue
   try:
    if len(set(ps))!=len(ps):raise ValueError('Duplicate curated paths')
    snapshots=[legacy_schema(p,m) for p in ps]
    if diagnostics is not None:diagnostics.extend(snapshots)
    for s in snapshots:mapping([f['name'] for f in s['fields']])
    n=sum(pq.ParquetFile(p).metadata.num_rows for p in ps)
    if n!=LEGACY_COUNTS[m]:raise ValueError('Curated monthly count differs from historical authority')
    out.append(dict(month=m,source='curated_legacy',paths=list(map(str,ps)),expected_rows=n,receipts=[dict(path=str(selector),sha256=sha(selector))]))
   except Exception as e:issues.append(dict(month=m,source='curated_legacy',reason=str(e)))
 return sorted(out,key=lambda x:x['month']),issues
