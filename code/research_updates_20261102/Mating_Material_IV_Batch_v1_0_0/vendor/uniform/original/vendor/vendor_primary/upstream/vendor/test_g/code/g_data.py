"""Streaming PGN inventory, held-out ending validation, and exact cascading quota reservoirs."""
from __future__ import annotations
import gzip, heapq, io, math, pickle, re, sqlite3, zlib
import urllib.request
from collections import Counter,defaultdict
from scipy.stats import beta
import zstandard as zstd
from g_common import *
from g_inputs import quota_counts

TAG=re.compile(r'^\[([A-Za-z0-9_]+) "(.*)"\]\s*$')
HEADER_BLOCK=re.compile(r'^\[(Event|Site|TimeControl|Result|White|Black|WhiteElo|BlackElo|Termination|Variant|SetUp|FEN) "(.*)"\]\s*$',re.MULTILINE)
GAME_BOUNDARY=re.compile(r'\n(?=\[Event ")')
TOKEN=re.compile(r'\{[^}]*\}|O-O-O[+#]?|O-O[+#]?|(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?)[+#]?')
CLOCK=re.compile(r'\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]')
GID=re.compile(r'(?:https?://lichess\.org/)?([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?/?$')
RULES=['normal','normal_or_zero','zero','normal_decisive']
ORDINARY={'mate','resign','stalemate','draw','outoftime','variantend'}
STREAM_RECEIPTS={}

class DigestReader(io.RawIOBase):
    def __init__(self,source):self.source=source;self.digest=hashlib.sha256();self.bytes=0
    def readable(self):return True
    def readinto(self,b):
        value=self.source.read(len(b));n=len(value);b[:n]=value;self.digest.update(value);self.bytes+=n;return n

@contextlib.contextmanager
def pgn_text(path):
    if str(path).startswith('https://'):
        url=str(path);match=re.fullmatch(r'https://database\.lichess\.org/standard/(lichess_db_standard_rated_(20\d\d-\d\d)\.pgn\.zst)',url)
        require(match is not None and match[2] in MONTHS,'Remote PGN URL is outside the frozen public-source allowlist')
        expected=load(ROOT/'PUBLISHED_PGN_SHA256.json')['sha256'][match[1]]
        # This branch is reachable only after the explicit CLI approval flag creates a URL source.
        with urllib.request.urlopen(url,timeout=60) as response:
            reader=DigestReader(response)
            with zstd.ZstdDecompressor().stream_reader(reader,read_across_frames=True,closefd=False) as stream,io.TextIOWrapper(stream,encoding='utf-8') as text:yield text
            actual=reader.digest.hexdigest();require(actual==expected,'Streamed PGN checksum failed for '+match[2],'PGN_INTEGRITY_FAILURE')
            STREAM_RECEIPTS[url]=dict(month=match[2],sha256=actual,bytes=reader.bytes,time=now(),stored_full_dump=False)
        return
    path=Path(path)
    if path.name.endswith('.zst'):
        with path.open('rb') as raw,zstd.ZstdDecompressor().stream_reader(raw,read_across_frames=True) as stream,io.TextIOWrapper(stream,encoding='utf-8') as text:yield text
    elif path.name.endswith('.gz'):
        with gzip.open(path,'rt',encoding='utf-8') as text:yield text
    else:
        with path.open(encoding='utf-8') as text:yield text

def pgn_records(path):
    """Lichess dump blocks, without building billions of boards. Sampled games are parsed fully later."""
    with pgn_text(path) as f:
        pending=''
        while True:
            chunk=f.read(8*1024*1024)
            if not chunk:
                pieces=[pending];pending=''
            else:
                pieces=GAME_BOUNDARY.split(pending+chunk);pending=pieces.pop()
            for block in pieces:
                block=block.lstrip('\ufeff\r\n');head,separator,moves=block.partition('\n\n')
                if not separator:head,separator,moves=block.partition('\r\n\r\n')
                if not block.strip():continue
                require(separator and moves.strip(),'Malformed or incomplete PGN game block','PGN_PARSE_ERROR')
                headers={m[1]:m[2] for m in HEADER_BLOCK.finditer(head)}
                require('Event' in headers and 'Site' in headers,'PGN block lacks identifying headers','PGN_PARSE_ERROR')
                yield headers,moves.strip()
            if not chunk:break

def pgn_summary(h,moves,parse_moves=True):
    site=GID.fullmatch(h.get('Site',''));tc=re.fullmatch(r'(\d+)\+(\d+)',h.get('TimeControl',''))
    if not site or not tc:return None
    base,inc=map(int,tc.groups());duration=base+40*inc
    speed=0 if duration<30 else 1 if duration<180 else 2 if duration<480 else 3 if duration<1500 else 4
    ply=0 if parse_moves else 11;clocks=[None,None]
    for m in TOKEN.finditer(moves) if parse_moves else ():
        token=m[0]
        if token.startswith('{'):
            clk=CLOCK.search(token)
            if clk and ply:clocks[(ply-1)%2]=3600*int(clk[1])+60*int(clk[2])+float(clk[3])
        else:ply+=1
    result=h.get('Result');event=h.get('Event','')
    try: wr=float(h.get('WhiteElo','?'));br=float(h.get('BlackElo','?'))
    except ValueError:wr=br=float('nan')
    zero=any(x is not None and x<=.001 for x in clocks)
    return dict(game_id=site[1],speed=speed,ply=ply,clock_white=clocks[0],clock_black=clocks[1],
      base=base,inc=inc,result=result,termination=h.get('Termination',''),zero=zero,
      white=h.get('White','').lower().strip(),black=h.get('Black','').lower().strip(),white_rating=wr,black_rating=br,
      rated=event.startswith('Rated '),standard=h.get('Variant','Standard')=='Standard' and h.get('SetUp','0')!='1',
      pool_tag=bool(re.fullmatch(r'Rated (?:UltraBullet|Ultrabullet|Bullet|Blitz|Rapid|Classical) game',event,re.I)),
      clocks_known=all(x is not None for x in clocks),annotated='[%eval' in moves)
def rule_match(r,name):
    normal=r['termination']=='Normal'
    return {'normal':normal,'normal_or_zero':normal or r['zero'],'zero':r['zero'],
            'normal_decisive':normal and r['result'] in ('1-0','0-1')}[name]
def precision_interval(good,total):
    if total==0:return np.nan,0.,1.
    return good/total,float(beta.ppf(.025,good,total-good+1)) if good else 0.,float(beta.ppf(.975,good+1,total-good)) if good<total else 1.
def status_connection(work,memory):
    work=Path(work);work.mkdir(exist_ok=True,parents=True);c=duckdb.connect(str(work/'statuses.duckdb'))
    c.execute(f"SET memory_limit='{max(1,memory-2)}GB'");c.execute('SET threads=1');c.execute('SET temp_directory='+qs(work/'spill'));return c

def make_lookup(c,work):
    """A sorted compact mmap index avoids rescanning the large cache for every PGN batch."""
    work=Path(work);status_names=[r[0] for r in c.execute('SELECT DISTINCT status FROM status WHERE status IS NOT NULL ORDER BY status').fetchall()]
    source_names=[r[0] for r in c.execute('SELECT DISTINCT source FROM status WHERE source IS NOT NULL ORDER BY source').fetchall()]
    sm={v:i+1 for i,v in enumerate(status_names)};om={v:i+1 for i,v in enumerate(source_names)}
    require(max(len(sm),len(om))<65535,'Unexpected status/source category cardinality')
    n=c.execute('SELECT count(*) FROM status').fetchone()[0]
    keys=np.lib.format.open_memmap(work/'ids.npy',mode='w+',dtype='S8',shape=(n,));values=np.lib.format.open_memmap(work/'values.npy',mode='w+',dtype='uint16',shape=(n,5));offset=0
    reader=c.execute('SELECT s.*,e.game_id IS NOT NULL excluded FROM status s LEFT JOIN excluded e USING(game_id) ORDER BY s.game_id').fetch_record_batch(131072)
    for b in reader:
        d=b.to_pandas();end=offset+len(d);keys[offset:end]=d.game_id.to_numpy(dtype='S8')
        values[offset:end]=np.column_stack([d.status.map(sm).fillna(0),d.source.map(om).fillna(0),d.conflict,d.timeout_seen,d.excluded]).astype('uint16');offset=end
    keys.flush();values.flush()
    f=c.execute('SELECT * FROM flags ORDER BY "name"').fetchdf();encoded=[str(x).encode('utf-8') for x in f['name']]
    require(all(len(x)<=64 for x in encoded),'Unexpected account-name length in flag snapshot')
    np.save(work/'flag_names.npy',np.array(encoded,dtype='S64'));np.save(work/'flag_values.npy',f[['known','flagged']].fillna(False).to_numpy(dtype=bool))
    save(work/'LOOKUP.json',dict(status=[None]+status_names,source=[None]+source_names,rows=n))

class StatusLookup:
    def __init__(self,work):
        p=Path(work);self.meta=load(p/'LOOKUP.json');self.keys=np.load(p/'ids.npy',mmap_mode='r');self.values=np.load(p/'values.npy',mmap_mode='r')
        self.names=np.load(p/'flag_names.npy',mmap_mode='r');self.flags=np.load(p/'flag_values.npy',mmap_mode='r')
    def flags_for(self,names):
        if len(self.names)==0:return np.zeros((len(names),2),bool)
        encoded=np.array([str(n).encode('utf-8') for n in names],dtype='S64');pos=np.searchsorted(self.names,encoded);safe=np.minimum(pos,len(self.names)-1);match=(pos<len(self.names))&(self.names[safe]==encoded)
        return self.flags[safe]*match[:,None]
    def annotate(self,records):
        if not records:return []
        gids=np.array([r['game_id'] for r in records],dtype='S8');pos=np.searchsorted(self.keys,gids);safe=np.minimum(pos,max(0,len(self.keys)-1))
        match=(pos<len(self.keys))&(self.keys[safe]==gids) if len(self.keys) else np.zeros(len(records),bool)
        values=self.values[safe].copy() if len(self.keys) else np.zeros((len(records),5),np.uint16);values[~match]=0
        wf=self.flags_for([r['white'] for r in records]);bf=self.flags_for([r['black'] for r in records]);out=[]
        for i,r in enumerate(records):
            s,o,conflict,timeout,excluded=map(int,values[i]);out.append(dict(r,status=self.meta['status'][s],source=self.meta['source'][o],conflict=bool(conflict),timeout_seen=bool(timeout),
              analysis_excluded=bool(excluded),white_known=bool(wf[i,0]),black_known=bool(bf[i,0]),flagged=bool(wf[i,1] or bf[i,1])))
        return out
    def close(self):pass

def normalize_cache_object(r):
    if not isinstance(r,dict):return None
    if isinstance(r.get('metadata_json'),str):
        obj=json.loads(r['metadata_json'])
        if not isinstance(obj,dict):return None
        require(not r.get('game_id') or obj.get('id',obj.get('game_id'))==r['game_id'],'Cache JSON identity conflict');r=obj
    gid=r.get('game_id',r.get('id'));status=[r[k] for k in ['status','api_status'] if isinstance(r.get(k),str)]
    source=[r[k] for k in ['source','api_source'] if isinstance(r.get(k),str)]
    if not isinstance(gid,str) or not re.fullmatch('[A-Za-z0-9]{8}',gid) or not status:return None
    bad=len(set(status))>1 or len(set(source))>1 or any(r.get(k) not in (None,False,0) for k in ['invalid','source_conflict','cached_conflict_or_prior_flag']) or bool(r.get('record_errors')) or ('metadata_valid' in r and r['metadata_valid'] not in (True,1))
    return dict(game_id=gid,status=status[0].lower(),source=source[0].lower() if source else None,bad=bad)

def cache_objects(path):
    path=Path(path);name=path.name.lower()
    if path.suffix.lower() in ('.db','.sqlite','.sqlite3'):
        c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for name in tables:
                quoted='"'+name.replace('"','""')+'"';columns=[r[1] for r in c.execute('PRAGMA table_info('+quoted+')')]
                if not set(columns)&{'game_id','id'} or not set(columns)&{'status','api_status','metadata_json'}:continue
                wanted=[v for v in columns if v in {'game_id','id','status','api_status','source','api_source','metadata_json','invalid','source_conflict','record_errors','metadata_valid'}]
                query='SELECT '+','.join('"'+v.replace('"','""')+'"' for v in wanted)+' FROM '+quoted
                cursor=c.execute(query)
                while True:
                    rows=cursor.fetchmany(8192)
                    if not rows:break
                    for r in rows:yield dict(zip(wanted,r))
        finally:c.close()
        return
    opener=pgn_text # Same safe text decompression; content is interpreted below as JSON only.
    with opener(path) as f:
        if any(x in name for x in ('.jsonl','.ndjson')):
            for line in f:
                if line.strip():yield json.loads(line)
        else:
            require(path.stat().st_size<=64*1024*1024,'Large non-streamable JSON cache needs a reviewed adapter','LARGE_JSON_CACHE_NOT_LOADED')
            text=f.read(64*1024*1024+1);require(len(text)<=64*1024*1024,'Large JSON cache needs a streaming adapter','LARGE_JSON_CACHE_NOT_LOADED');obj=json.loads(text)
            if isinstance(obj,list):yield from obj
            elif isinstance(obj,dict):
                if 'id' in obj or 'game_id' in obj:yield obj
                elif isinstance(obj.get('games'),list):yield from obj['games']
                else:
                    for gid,value in obj.items():
                        if isinstance(value,dict) and re.fullmatch('[A-Za-z0-9]{8}',gid):yield dict(value,id=gid)

def build_status_cache(a,run,key):
    work=run/'gdata/status';work.mkdir(parents=True,exist_ok=True);k=digest([key,'status-cache'])
    if done(work,k):return
    c=status_connection(work,a.memory_gb);accepted=[];other=[];fail=[]
    try:
        c.execute('DROP TABLE IF EXISTS evidence');c.execute('CREATE TABLE evidence(game_id VARCHAR,status VARCHAR,source VARCHAR,bad BOOLEAN)')
        candidates=[];other_caches=[]
        for root in [a.project_root/'derived',a.project_root/'raw']:
            for p in file_inventory(root,[run]):
                if 'test_g_' in str(p).lower():continue
                if p.suffix!='.parquet':
                    lower=p.name.lower()
                    if (lower.endswith(('.jsonl','.ndjson','.jsonl.gz','.ndjson.gz','.jsonl.zst','.ndjson.zst','.sqlite','.sqlite3','.db'))
                        or lower.endswith(('.json','.json.gz','.json.zst')) and any(v in str(p).lower() for v in ['cache','api','metadata','export','response','batch'])):other_caches.append(p)
                    continue
                try:names=set(pq.ParquetFile(p).schema_arrow.names)
                except Exception:continue
                if names&{'moves','pgn','san','move_list','uci_moves'}:
                    other.append(dict(path=str(p),rows=pq.ParquetFile(p).metadata.num_rows,move_columns=sorted(names&{'moves','pgn','san','move_list','uci_moves'}),
                        covered_months=sorted(set(re.findall(r'20\d\d-\d\d',str(p)))&set(MONTHS)),coverage_basis='Directory labels; stored privately for schema review'))
                if 'game_id' in names and ({'api_status','api_source'}<=names or {'status','source'}<=names or 'metadata_json' in names):candidates.append((p,names))
        for p,names in candidates:
            before=stamp(p)
            bads=[f'coalesce({n},false)' for n in ('invalid','cached_conflict_or_prior_flag','source_conflict') if n in names]
            if 'record_errors' in names:bads.append("coalesce(record_errors,'')<>''")
            bad=' OR '.join(bads) or 'false'
            if {'api_status','api_source'}<=names:status='api_status';source='api_source'
            elif {'status','source'}<=names:status='status';source='source'
            else:
                status="json_extract_string(metadata_json,'$.status')";source="json_extract_string(metadata_json,'$.source')"
            try:
                c.execute(f'''INSERT INTO evidence SELECT game_id,lower(cast({status} AS VARCHAR)),lower(cast({source} AS VARCHAR)),({bad})
                   FROM {parq([p])} WHERE regexp_full_match(game_id,'[A-Za-z0-9]{{8}}')''')
                require(stamp(p)==before,'Status cache changed while reading');accepted.append(dict(path=str(p),stamp=before,sha256=sha(p)))
            except duckdb.Error as e:fail.append(dict(path=str(p),reason=type(e).__name__))
        for p in other_caches:
            before=stamp(p);buffer=[];matched=0;c.execute('BEGIN TRANSACTION')
            try:
                for obj in cache_objects(p):
                    r=normalize_cache_object(obj)
                    if r:buffer.append(r)
                    if len(buffer)>=8192:
                        c.register('_cache_batch',pd.DataFrame(buffer));c.execute('INSERT INTO evidence SELECT * FROM _cache_batch');c.unregister('_cache_batch');matched+=len(buffer);buffer=[]
                if buffer:
                    c.register('_cache_batch',pd.DataFrame(buffer));c.execute('INSERT INTO evidence SELECT * FROM _cache_batch');c.unregister('_cache_batch');matched+=len(buffer)
                require(stamp(p)==before,'Cache changed during read');c.execute('COMMIT')
                if matched:accepted.append(dict(path=str(p),stamp=before,sha256=sha(p),records=matched))
                else:fail.append(dict(path=str(p),reason='NO_RECOGNIZED_API_GAME_RECORDS'))
            except (ValueError,OSError,GateError,sqlite3.Error,duckdb.Error) as e:
                c.execute('ROLLBACK');fail.append(dict(path=str(p),reason=e.code if isinstance(e,GateError) else type(e).__name__))
        # The authenticated analysis IDs guarantee exclusion even if no other cache survives.
        for p in sorted((run/'input').glob('*/analysis_ids.parquet')):c.execute('INSERT INTO evidence SELECT *,false FROM '+parq([p]))
        c.execute('''CREATE OR REPLACE TABLE status AS SELECT game_id,
           CASE WHEN count(DISTINCT status)=1 THEN min(status) END status,
           CASE WHEN count(DISTINCT source)=1 THEN min(source) END source,
           bool_or(bad) OR count(DISTINCT status)>1 OR count(DISTINCT source)>1 conflict,
           bool_or(status='timeout') timeout_seen FROM evidence GROUP BY game_id''')
        c.execute('CREATE OR REPLACE TABLE excluded AS SELECT DISTINCT game_id FROM '+parq(sorted((run/'input').glob('*/analysis_ids.parquet'))))
        snapshot=a.project_root/SNAPSHOT_REL
        if snapshot.exists():
            require(sha(snapshot)==SNAPSHOT_SHA,'Flag snapshot mismatch')
            c.execute('''CREATE OR REPLACE TABLE flags AS SELECT lower(trim(username_norm)) AS "name",returned known,
               coalesce(returned AND (coalesce(disabled,false) OR coalesce(tos_violation,false)),false) flagged FROM '''+parq([snapshot]))
        else:raise GateError('MISSING_FLAG_SNAPSHOT','Fixed Test A flag snapshot is required.')
        c.execute('DROP TABLE evidence');make_lookup(c,work);c.execute('CHECKPOINT')
        save(work/'SOURCES_PRIVATE.json',accepted);save(work/'OTHER_MOVE_STORES_PRIVATE.json',other);save(work/'UNSUPPORTED_PRIVATE.json',fail)
        counts=c.execute('SELECT count(*) games,count(*) FILTER(WHERE conflict) conflicts,count(*) FILTER(WHERE timeout_seen) timeout_endings FROM status').fetchdf()
        table(run/'report','tabG_cache_inventory',counts,dict(N=int(counts.games.iloc[0]),sample='Existing API-provenance records in Parquet, JSON/NDJSON and read-only SQLite',source_months=MONTHS,ending_status_coverage='Unrecognized or conflicting records never prove a non-disconnection ending'))
    finally:c.close()
    checkpoint(work,k,outputs=[work/'statuses.duckdb',work/'SOURCES_PRIVATE.json',work/'OTHER_MOVE_STORES_PRIVATE.json',work/'LOOKUP.json']+list(work.glob('*.npy')))

def annotate(c,records):
    if not records:return []
    if isinstance(c,StatusLookup):return c.annotate(records)
    d=pd.DataFrame(records);c.register('_batch',d[['game_id','white','black']])
    q='''SELECT b.game_id,s.status,s.source,coalesce(s.conflict,false) conflict,coalesce(s.timeout_seen,false) timeout_seen,
        e.game_id IS NOT NULL analysis_excluded,coalesce(w.known,false) white_known,coalesce(k.known,false) black_known,
        coalesce(w.flagged,false) OR coalesce(k.flagged,false) flagged FROM _batch b LEFT JOIN status s USING(game_id)
        LEFT JOIN excluded e USING(game_id) LEFT JOIN flags w ON b.white=w.name LEFT JOIN flags k ON b.black=k.name'''
    out=c.execute(q).fetchdf().to_dict('records');c.unregister('_batch');return [dict(r,**v) for r,v in zip(records,out)] if [r['game_id'] for r in records]==[v['game_id'] for v in out] else [dict(r,**{v['game_id']:v for v in out}[r['game_id']]) for r in records]

def discover_pgns(a):
    found=defaultdict(list)
    roots=[a.project_root/'raw']+[Path(x) for x in a.extra_pgn_root]
    for root in roots:
        for p in file_inventory(root):
            if p.name.endswith(('.pgn','.pgn.zst','.pgn.gz')):
                m=re.search(r'(20\d\d-\d\d)',p.name)
                if m and m[1] in MONTHS:found[m[1]].append(p)
    picked={}
    for month,ps in found.items():
        preferred=[p for p in ps if p.name in [f'lichess_db_standard_rated_{month}.pgn.zst',f'lichess_db_standard_rated_{month}.pgn']]
        require(len(preferred or ps)==1,'Ambiguous PGN copies for '+month+'; use --extra-pgn-root with a unique surviving source.','AMBIGUOUS_PGN_SOURCE')
        picked[month]=(preferred or ps)[0]
    return picked

def inventory(a,run,key):
    work=run/'gdata';work.mkdir(exist_ok=True);k=digest([key,'pgn-inventory'])
    if done(work,k):return load(work/'PGNS_PRIVATE.json'),load(work/'ENDING_RULES.json')
    build_status_cache(a,run,key);pg=discover_pgns(a);save(work/'PGNS_PRIVATE.json',pg)
    c=StatusLookup(work/'status');stats=Counter();rows=[];support=Counter();totals=Counter();eligible=Counter()
    def process(batch):
        for r in annotate(c,batch):
            sp=int(r['speed']);totals[(sp,'pgn_games')]+=1
            valid=r['status'] is not None and not pd.isna(r['status']) and not r['conflict']
            totals[(sp,'verified')]+=int(valid)
            if not valid:continue
            parsed=pgn_summary(r.pop('_headers'),r.pop('_moves'));r.update(parsed)
            split='development' if hash64(r['game_id'],'ending-validation')%2==0 else 'validation'
            good=r['status'] in ORDINARY
            totals[(sp,split+'_ordinary')]+=int(good)
            for name in RULES:
                if rule_match(r,name):
                    stats[(sp,split,name,'all')]+=1;stats[(sp,split,name,'good')]+=int(good)
                    sig=(r['termination'],r['zero'],r['clocks_known'],r['result'])
                    support[(sp,name,json.dumps(sig))]+=1
            if r['pool_tag'] and r['source'] is not None and not pd.isna(r['source']):
                stats[(sp,split,'pool_tag','all')]+=1;stats[(sp,split,'pool_tag','good')]+=int(r['source']=='pool')
    try:
        for month in MONTHS:
            if month not in pg:
                rows.append(dict(month=month,survives=False,checksum_status='absent',games=0,other_sources=0,used=False));continue
            path=Path(pg[month]);before=stamp(path);n=0;batch=[]
            with heartbeat('Inventory and ending validation '+month):
                actual=sha(path)
                published=load(ROOT/'PUBLISHED_PGN_SHA256.json')
                expected=published['sha256'].get(path.name);checksum_origin=published['source'] if expected else ''
                for side in [path.with_name(path.name+'.sha256'),path.parent/'sha256sums.txt',path.parent/'SHA256SUMS']:
                    if side.exists():
                        for line in side.read_text(errors='strict').splitlines():
                            if path.name in line and re.match('[a-fA-F0-9]{64}',line):
                                side_expected=line.split()[0].lower()
                                if expected:require(expected==side_expected,'Local and published PGN checksum differ','PGN_CHECKSUM_CONFLICT')
                                else:expected=side_expected;checksum_origin=side.name
                if expected:require(actual==expected,'PGN SHA256 mismatch for '+month,'PGN_INTEGRITY_FAILURE')
                for h,moves in pgn_records(path):
                    n+=1;r=pgn_summary(h,moves,parse_moves=False)
                    if r:r['_headers']=h;r['_moves']=moves;batch.append(r)
                    if len(batch)>=8192:process(batch);batch=[]
                if batch:process(batch)
                require(n>0 and stamp(path)==before,'Empty or changing PGN source','PGN_INTEGRITY_FAILURE')
            status='checksum sidecar matched; '+checksum_origin if expected else ('full zstd decompression completed; published checksum not locally available' if path.name.endswith('.zst') else 'full decompression completed; no published checksum locally available')
            rows.append(dict(month=month,survives=True,checksum_status=status,sha256=actual,games=n,other_sources=0,used=True))
            log(f'Inventory {month}: {n:,} games')
        chosen={};rule_rows=[]
        for sp in range(5):
            dev=[]
            for name in RULES:
                n=stats[(sp,'development',name,'all')];g=stats[(sp,'development',name,'good')];pi,lo,hi=precision_interval(g,n)
                if n>=500 and lo>=.99:dev.append((pi,lo,n,name))
            best=max(dev)[3] if dev else None
            allow=False
            for name in RULES+['pool_tag']:
                for split in ['development','validation']:
                    n=stats[(sp,split,name,'all')];g=stats[(sp,split,name,'good')];pi,lo,hi=precision_interval(g,n)
                    rule_rows.append(dict(speed=SPEEDS[sp],rule=name,split=split,selected=name==best,N=n,precision=pi,ci_low=lo,ci_high=hi,
                       recall=g/max(1,totals[(sp,split+'_ordinary')]) if name!='pool_tag' else np.nan,
                       cache_coverage=totals[(sp,'verified')]/max(1,totals[(sp,'pgn_games')]),pgn_games=totals[(sp,'pgn_games')]))
                    if name==best and split=='validation':allow=n>=500 and lo>=.99
            n=stats[(sp,'validation','pool_tag','all')];g=stats[(sp,'validation','pool_tag','good')]
            pool_ok=n>=500 and precision_interval(g,n)[1]>=.99
            chosen[str(sp)]=dict(rule=best,validated=allow,pool_proxy_validated=pool_ok,
              supported_signatures=[sig for (s,name,sig),n in support.items() if s==sp and name==best and n>=500])
        meta=dict(N=sum(r['games'] for r in rows),sample='Local surviving monthly rated-standard PGNs',source_months=sorted(pg),ending_status_coverage='Reported by speed; validation games held out from rule selection')
        table(run/'report','tabGdata_inventory',rows,meta);table(run/'report','tabGdata_ending_status',rule_rows,meta)
        save(work/'ENDING_RULES.json',chosen);save(work/'COUNTS.json',rows)
        other=load(work/'status/OTHER_MOVE_STORES_PRIVATE.json')
        table(run/'report','tabGdata_other_move_stores',[dict(store_number=i+1,rows=r['rows'],columns=';'.join(r['move_columns']),source_months=r['covered_months'],coverage_basis=r['coverage_basis'],used=False,status='Move-bearing derived store requires verified complete PGN metadata before sampling') for i,r in enumerate(other)] or [dict(status='None found')],meta)
        checkpoint(work,k,list(pg.values()),[work/'PGNS_PRIVATE.json',work/'ENDING_RULES.json',work/'COUNTS.json'])
    finally:c.close()
    return load(work/'PGNS_PRIVATE.json'),chosen

def eligible_reason(r,rules,verified_only=False,exclude_names=frozenset()):
    if r['white'] in AUTHORS or r['black'] in AUTHORS:return 'author'
    if r['white'] in exclude_names or r['black'] in exclude_names:return 'overlap_sensitivity'
    if r['analysis_excluded'] or r['timeout_seen'] or r['status']=='timeout':return 'disconnection_or_analysis_sample'
    if r['conflict']:return 'conflicting_cache'
    if r['flagged']:return 'flagged'
    if not (r['rated'] and r['standard'] and r['ply']>10 and r['result'] in ('1-0','0-1','1/2-1/2')):return 'ineligible_game'
    if not np.isfinite(r['white_rating']+r['black_rating']) or r['base']<=0:return 'missing_required_feature'
    rule=rules[str(r['speed'])]
    source=r['source'] if isinstance(r['source'],str) else None
    if source is not None and source!='pool':return 'non_pool'
    if source is None and not (r['pool_tag'] and rule['pool_proxy_validated']):return 'unresolved_pool_source'
    status=r['status'] if isinstance(r['status'],str) else None
    if status in ORDINARY:return 'verified'
    if status is not None:return 'nonordinary_status'
    sig=json.dumps((r['termination'],r['zero'],r['clocks_known'],r['result']))
    if not verified_only and rule['validated'] and rule['rule'] and rule_match(r,rule['rule']) and sig in rule['supported_signatures']:return 'validated_rule'
    return 'unresolved_ending'

class CascadeReservoir:
    """Exact greedy quotas in one pass: independent hash priorities at each bin.

    A replacement at a higher bin is offered to lower bins. Thresholds decrease
    monotonically, so rejected games never need revisiting. Retained payloads
    occupy disk, while heaps contain only identifiers and priorities.
    """
    def __init__(self,folder,quotas,seed=SEED):
        self.folder=Path(folder);self.folder.mkdir(exist_ok=True,parents=True);self.quotas=quotas;self.seed=seed
        self.heaps={k:[] for k in quotas};self.c=sqlite3.connect(self.folder/'reservoir.sqlite')
        self.c.execute('CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,payload BLOB)');self.seen=0
    def add(self,r,h,moves):
        payload=dict(row=r,headers=h,moves=moves);current=r['game_id'];start=min((r['ply']-11)//10,19);sp=r['speed'];stored=False
        for b in range(start,-1,-1):
            k=(sp,b);q=self.quotas.get(k,0)
            if not q:continue
            priority=hash64(current,f'{self.seed}:{sp}:{b}');heap=self.heaps[k]
            if len(heap)<q or priority < -heap[0][0]:
                if not stored:self.c.execute('INSERT INTO games VALUES(?,?)',(current,zlib.compress(pickle.dumps(payload,protocol=5),1)));stored=True
                if len(heap)<q:heapq.heappush(heap,(-priority,current));return
                _,old=heapq.heapreplace(heap,(-priority,current));current=old;payload=None;stored=True
        if stored:self.c.execute('DELETE FROM games WHERE id=?',(current,))
    def flush(self):self.c.commit()
    def records(self):
        self.flush()
        for (sp,b),heap in sorted(self.heaps.items()):
            for _,gid in sorted(heap):
                blob=self.c.execute('SELECT payload FROM games WHERE id=?',(gid,)).fetchone()[0]
                r=pickle.loads(zlib.decompress(blob));r['bin']=b;r['speed']=sp;yield r
    def close(self):self.c.close()

def sample_games(a,run,paths,pg,rules,key):
    work=run/'g1/sample';work.mkdir(parents=True,exist_ok=True);k=digest([key,'quota-sample',a.positions])
    if done(work,k):return work/'sampled_positions.parquet'
    counts=quota_counts(paths);tot=int(counts.n.sum());raw=counts.n.to_numpy()/tot*a.positions;q=np.floor(raw).astype(int)
    q[np.argsort(-(raw-q),kind='stable')[:a.positions-int(q.sum())]]+=1
    quotas={(int(r.speed),int(r.ply_bin)):int(n) for r,n in zip(counts.itertuples(),q)}
    resdir=work/'reservoir'
    if resdir.exists():shutil.rmtree(resdir)
    reservoir=CascadeReservoir(resdir,quotas);c=StatusLookup(run/'gdata/status');attrition=Counter();batch=[];payloads={};scanned=0
    def process():
        nonlocal batch,payloads
        for r in annotate(c,batch):
            rule=rules[str(r['speed'])]
            potential_pool=r['source']=='pool' or r['source'] is None and r['pool_tag'] and rule['pool_proxy_validated']
            potential_ending=r['status'] in ORDINARY or r['status'] is None and rule['validated']
            if potential_pool and potential_ending and not (r['analysis_excluded'] or r['timeout_seen'] or r['flagged'] or r['conflict']):
                h,moves=payloads[r['game_id']];r.update(pgn_summary(h,moves))
            reason=eligible_reason(r,rules);attrition[(r['speed'],reason)]+=1
            if reason in ('verified','validated_rule'):
                r['ending_basis']=reason;h,moves=payloads[r['game_id']];reservoir.add(r,h,moves)
        reservoir.flush();batch=[];payloads={}
    try:
        streamed_counts={}
        for month,path in sorted(pg.items()):
            with heartbeat('Quota reservoirs '+month):
                nmonth=0
                for h,moves in pgn_records(path):
                    nmonth+=1
                    r=pgn_summary(h,moves,parse_moves=False)
                    if r:
                        r['month_code']=MONTHS.index(month);batch.append(r);payloads[r['game_id']]=(h,moves)
                    if len(batch)>=8192:process()
                if batch:process()
                if str(path).startswith('https://'):streamed_counts[month]=dict(STREAM_RECEIPTS[str(path)],games=nmonth)
        if streamed_counts:
            save(work/'STREAM_RECEIPTS.json',streamed_counts)
            rows=load(run/'gdata/COUNTS.json')
            for r in rows:
                if r['month'] in streamed_counts:r.update(games=streamed_counts[r['month']]['games'],checksum_status='Published SHA256 verified during approved streaming; full dump not stored',used=True,sha256=streamed_counts[r['month']]['sha256'])
            table(run/'report','tabGdata_inventory',rows,dict(N=sum(r['games'] for r in rows),sample='Surviving PGNs plus explicitly approved missing-month streams',source_months=sorted(pg),ending_status_coverage='Validated existing-cache rules applied during quota sampling'))
        import chess.pgn
        rows=[];sample_path=work/'sampled_positions.parquet';writer=None;achieved=Counter()
        def write_rows():
            nonlocal rows,writer
            if not rows:return
            t=pa.Table.from_pylist(rows)
            if writer is None:writer=pq.ParquetWriter(sample_path,t.schema,compression='zstd')
            writer.write_table(t);rows=[]
        for p in reservoir.records():
            r=p['row'];b=p['bin'];first=11+10*b;last=r['ply'] if b==19 else min(first+9,r['ply'])
            target=first+hash64(r['game_id'],'sample-ply')%(last-first+1)
            text='\n'.join(f'[{k} "{v}"]' for k,v in p['headers'].items())+'\n\n'+p['moves']+'\n'
            game=chess.pgn.read_game(io.StringIO(text));require(game is not None and not game.errors,'Sampled PGN is not fully parseable','PGN_PARSE_ERROR')
            require(game.end().ply()==r['ply'],'Streaming ply count differs from full PGN parser','PGN_PLY_MISMATCH')
            node=game;clocks=[float(r['base']),float(r['base'])];missing=False
            for i in range(target):
                node=node.variation(0);clk=node.clock()
                if clk is None:missing=True
                else:clocks[i%2]=float(clk)
            if missing:attrition[(r['speed'],'missing_sample_clock')]+=1;continue
            d=dict(game_id=r['game_id'],white=r['white'],black=r['black'],fen=node.board().fen(),ply=target,ply_bin=b,speed=r['speed'],month_code=r['month_code'],
                mean_r=(r['white_rating']+r['black_rating'])/2,dr=r['black_rating']-r['white_rating'],clock_f=clocks[0],clock_g=clocks[1],base=float(r['base']),inc=float(r['inc']),
                stm=int(node.board().turn==chess.WHITE),outcome={'1-0':0,'1/2-1/2':1,'0-1':2}[r['result']],
                test=hash64(r['game_id'],'g1-holdout')%5==0,ending_basis=r['ending_basis'],flags_known=r['white_known'] and r['black_known'],
                annotated=r['annotated'],annotation_cp=np.nan,annotation_mate=np.nan)
            evaluation=node.eval()
            if evaluation is not None:
                score=evaluation.white();d['annotation_cp']=score.score();d['annotation_mate']=score.mate()
                if d['annotation_mate']==0:d['annotation_mate']=.5*np.sign(score.score(mate_score=10000))
            rows.append(d);achieved[(r['speed'],b)]+=1
            if len(rows)>=8192:write_rows()
        write_rows()
        if writer:writer.close()
        n=sum(achieved.values());meta=dict(N=n,sample='One position per eligible completed pool game; quota cascade, higher bins first',source_months=sorted(pg),ending_status_coverage='Verified API endings and independently validated PGN rule')
        table(run/'report','tabG1_ply_quotas',[dict(speed=SPEEDS[s],ply_bin=b,target=q,achieved=achieved[(s,b)],weight=q/achieved[(s,b)] if achieved[(s,b)] else np.nan) for (s,b),q in sorted(quotas.items())],meta)
        table(run/'report','tabGdata_retention',[dict(speed=SPEEDS[s],reason=reason,N=n) for (s,reason),n in sorted(attrition.items())],meta)
        require(n>=500000,f'Only {n:,} eligible sampled positions. The 500,000 minimum was not reached; no API requests were made.','NEEDS_DATA_OR_API_APPROVAL')
        require(all(achieved[k]>0 for k,q in quotas.items() if q>0),'A positive-target quota cell has no support','G1_QUOTA_NO_SUPPORT')
        d=pd.read_parquet(sample_path);d['weight']=[quotas[(s,b)]/achieved[(s,b)] for s,b in zip(d.speed,d.ply_bin)];atomic_parquet(d,sample_path)
        checkpoint(work,k,[Path(p) for p in pg.values() if not str(p).startswith('https://')],[sample_path]+([work/'STREAM_RECEIPTS.json'] if streamed_counts else []),dict(N=n,attrition=[dict(speed=s,reason=r,N=n) for (s,r),n in attrition.items()]))
    finally:reservoir.close();c.close()
    return work/'sampled_positions.parquet'
