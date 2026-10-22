"""Arena next-wave I/O. Read-only inputs; isolated, hash-bound output stages."""
from __future__ import annotations
import contextlib, csv, hashlib, importlib.util, json, math, os, shutil, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.1'
REPO_COMMIT = 'bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129'
V102_RUN = '20260913T202346Z_96523'
V102_CONTRACT = '45c0403f0ece80e9d89b5f5627aca5b1e23a898e2e3f9fb7b26bcdf9c4dba905'
ARENA_TOTAL = [1892835, 20325, 730717, 12829]
NONADJ = 'not_mutually_adjacent_observed'

def require(ok, message):
    if not ok: raise RuntimeError(message)

def log(message):
    print(time.strftime('[%Y-%m-%dT%H:%M:%SZ]', time.gmtime()), message, flush=True)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8*1024**2), b''): h.update(b)
    return h.hexdigest()

def clean(x):
    if isinstance(x, dict): return {str(k): clean(v) for k,v in x.items()}
    if isinstance(x, (list, tuple)): return [clean(v) for v in x]
    if isinstance(x, Path): return str(x)
    if hasattr(x, 'columns') and hasattr(x, 'to_dict'): return clean(x.to_dict(orient='records'))
    if hasattr(x, 'tolist'): return clean(x.tolist())
    if isinstance(x, float) and not math.isfinite(x): return None
    return x

def js(path, x):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp.'+str(os.getpid()))
    tmp.write_text(json.dumps(clean(x), sort_keys=True, indent=2, allow_nan=False)+'\n')
    os.replace(tmp, path)

def read(path): return json.loads(Path(path).read_text())
def fingerprint(x): return hashlib.sha256(json.dumps(clean(x),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def q(x): return "'"+str(x).replace("'", "''")+"'"
def parq(paths):
    if isinstance(paths, (str,Path)): paths = [paths]
    require(bool(paths), 'Empty parquet input list')
    return 'read_parquet(['+','.join(q(x) for x in paths)+'],hive_partitioning=false,union_by_name=false)'

def db(temp, memory='4GB', threads=4, path=':memory:'):
    import duckdb
    Path(temp).mkdir(parents=True,exist_ok=True)
    c=duckdb.connect(str(path)); c.execute("SET TimeZone='UTC'")
    c.execute('SET threads='+str(int(threads))); c.execute('SET memory_limit='+q(memory))
    c.execute('SET temp_directory='+q(temp)); c.execute('SET preserve_insertion_order=false')
    return c

def records(c, sql):
    r=c.execute(sql); return [dict(zip([v[0] for v in r.description],v)) for v in r.fetchall()]

def csvout(path, rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    rows=[clean(r) for r in rows]; names=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names); w.writeheader()
        for r in rows: w.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in r.items()})

@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event()
    def beat():
        while not stop.wait(45): log(label+' — working')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try: yield
    finally: stop.set();t.join()

def load(path, name):
    path=Path(path)
    if str(path.parent) not in sys.path: sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod

def safe_child(root, name):
    p=(Path(root)/name).resolve()
    require(p.is_relative_to(Path(root).resolve()) and p!=Path(root).resolve(), 'Manifest path escapes its root')
    return p

def inventory(root):
    return [{'path':str(p.relative_to(root)), 'bytes':p.stat().st_size, 'sha256':sha(p)}
            for p in sorted(Path(root).rglob('*')) if p.is_file()
            and p not in {Path(root)/'_DONE.json',Path(root)/'MANIFEST.json'} and '__pycache__' not in p.parts]

def verify_files(root, entries):
    for r in entries:
        p=safe_child(root,r['path']);require(p.is_file(),'Missing input: '+str(p))
        sig=(p.stat().st_size,p.stat().st_mtime_ns)
        require(sig[0]==r['bytes'] and sha(p)==r['sha256'],'File checksum changed: '+str(p))
        require(sig==(p.stat().st_size,p.stat().st_mtime_ns),'File changed while hashing: '+str(p))

def verify_package():
    p=ROOT/'PACKAGE_MANIFEST.sha256';require(p.is_file(),'Missing package manifest')
    for line in p.read_text().splitlines():
        h,name=line.split('  ',1);require(sha(safe_child(ROOT,name))==h,'Package checksum failed: '+name)
    for r in read(ROOT/'authority/REPOSITORY_SOURCES.json')['files']:
        require(sha(safe_child(ROOT,r['package_path']))==r['sha256'],'Original repository source changed')
    return sha(p)

def stage_complete(root, contract):
    p=Path(root)/'_DONE.json'
    if not p.exists(): return None
    r=read(p);require(r['contract']==contract,'Stage configuration changed')
    verify_files(root,r['files']); return r

def finish_stage(root, contract, summary):
    js(Path(root)/'_DONE.json',{'contract':contract,'files':inventory(root),'summary':summary})

def authenticate_arena(arena, work, threads, memory):
    import pyarrow.parquet as pq
    arena=Path(arena).resolve()
    for name in ['RUN_STATUS.json','SAMPLE_COUNTS.json']:
        require(sha(arena/'public'/name)==sha(ROOT/'authority'/('V102_'+name)), 'Different v102 public authority: '+name)
    b=read(arena/'private/BUILD.json'); known=read(ROOT/'authority/V102_SAMPLE_COUNTS.json')
    require(b['status']=='ARENA_INPUTS_BUILT_AND_CHECKED' and b['contract']==V102_CONTRACT,'Wrong arena input contract')
    require(b['totals']==known['totals'] and b['monthly']==known['monthly'],'Arena build margins changed')
    require(b['totals']['arena_nonadjacent']==ARENA_TOTAL,'Wrong arena population')
    panels=[]; narrow=[]; signatures=[]; months=[]
    with heartbeat('Authenticating 24 completed arena months'):
        for m in known['monthly']:
            folder=arena/'private/months'/('month='+m['month']);done=read(folder/'_DONE.json')
            require(done['contract']==V102_CONTRACT and done['summary']==m,'Monthly arena receipt changed')
            verify_files(folder,done['files'])
            pp=folder/'analysis_panel.parquet';nn=folder/'opportunities.parquet'
            require(pq.ParquetFile(pp).metadata.num_rows==m['arena']['n'],'Monthly arena rows changed')
            require(len(pq.ParquetFile(pp).schema_arrow.names)==157,'Arena schema is not the original 157 columns')
            for p in [pp,nn]: signatures.append({'path':str(p),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns})
            panels.append(str(pp));narrow.append(str(nn));months.append({'month':m['month'],'path':str(pp),'rows':m['arena']['n']})
            log('Arena month authenticated: '+m['month'])
    c=db(Path(work)/'authentication_spill',memory,threads)
    try:
        qa=records(c,f'''SELECT count(*) AS rows,count(DISTINCT game_id) AS games,
          count(DISTINCT chooser_username_norm) AS choosers,
          sum(kind_draw::BIGINT) AS kind_draws,count(*) FILTER(WHERE fair_competitive) AS fair_rows,
          sum(kind_draw::BIGINT) FILTER(WHERE fair_competitive) AS fair_kind_draws,
          count(DISTINCT chooser_username_norm) FILTER(WHERE fair_competitive) AS fair_choosers,
          count(DISTINCT chooser_username_norm) FILTER(WHERE fair_competitive AND kind_draw) AS fair_kind_choosers,
          count(*) FILTER(WHERE disconnected_clock_last_obs_s IS NULL) AS missing_disconnected_clock,
          count(*) FILTER(WHERE tournament_like_event) AS tournament_flag_rows
          FROM {parq(panels)}''')[0]
        require([qa[k] for k in ['rows','kind_draws','fair_rows','fair_kind_draws']]==ARENA_TOTAL,'Arena row definitions changed')
        require(qa['games']==qa['rows'] and qa['choosers']==466535,'Arena identity count changed')
    finally: c.close();shutil.rmtree(Path(work)/'authentication_spill',ignore_errors=True)
    return {'arena_run':str(arena),'panels':panels,'narrow':narrow,'month_records':months,
            'authority':qa,'signatures':signatures,'v102_contract':V102_CONTRACT}

def unchanged(signatures):
    for s in signatures:
        p=Path(s['path']);require(p.stat().st_size==s['bytes'] and p.stat().st_mtime_ns==s['mtime_ns'], 'Input changed during analysis: '+str(p))

def export_tables(source, dest):
    """Only aggregate producer outputs; all account, game and chronology caches stay private."""
    import pyarrow.parquet as pq
    private={'chooser','chooser_id','chooser_user_id','chooser_username_norm','username','username_norm','game_id',
             'recipient_user_id','recipient_id','opponent_id','exposure_chooser_user_id','sample_row','pilot_row','query_index'}
    for p in sorted(Path(source).rglob('*')):
        if not p.is_file() or p.suffix not in {'.csv','.parquet','.png','.pdf'}: continue
        rel=p.relative_to(source)
        if any(x in rel.parts for x in {'_work','private_cache','receipts','spill'}): continue
        if p.suffix=='.csv':
            with p.open() as f: names=next(csv.reader(f),[])
        elif p.suffix=='.parquet': names=pq.ParquetFile(p).schema_arrow.names
        else: names=[]
        require(not(private & set(names)),'Account or game identifier in aggregate export: '+str(rel))
        target=Path(dest)/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
