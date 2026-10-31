"""Exact all-game ply histograms from local monthly PGNs; no API or chess engine."""
from common import *
from design import MONTHS,SPEEDS
import io,re,gzip,bz2
from collections import Counter

TAG=re.compile(r'^\[([A-Za-z0-9_]+) "(.*)"\]\s*$')
COMMENTS=re.compile(r'\{[^{}]*\}',re.S)
MOVENUM=re.compile(r'\b\d+\.(?:\.\.)?')
NAG=re.compile(r'\$\d+')
RESULTS={'1-0','0-1','1/2-1/2','*'}

def speed_from_tc(tc):
    # Lichess FAQ, https://lichess.org/faq#time-controls, checked 2026-10-13.
    if not re.fullmatch(r'\d+\+\d+',tc):return None
    base,inc=map(int,tc.split('+'));seconds=base+40*inc
    return 0 if seconds<30 else 1 if seconds<180 else 2 if seconds<480 else 3 if seconds<1500 else 4

def ply_count(body,result):
    text=COMMENTS.sub(' ',body)
    require(not any(x in text for x in '{}();'),'Unexpected PGN comment/variation syntax; no guessed ply count')
    tokens=NAG.sub(' ',MOVENUM.sub(' ',text)).split()
    tokens=[t for t in tokens if t not in ['!','?','!!','??','!?','?!']]
    require(bool(tokens) and tokens[-1]==result,'Missing/truncated/mismatched PGN final result')
    moves=tokens[:-1]
    require(not any(t in RESULTS for t in moves),'Embedded result inside PGN movetext')
    # Lichess standard SAN (including checks/promotions/castling); avoid board reconstruction.
    require(all(re.fullmatch(r'(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[O0]-[O0](?:-[O0])?)[+#]?[!?]*',t) for t in moves),'Unrecognized SAN token; median scan stopped instead of silently skipping a game')
    return len(moves)

def game_record(tags,body,month):
    event=tags.get('Event','')
    if event.startswith('Casual '):return None,'casual'
    require(event.startswith('Rated '),'Unknown ratedness in monthly PGN')
    if tags.get('Variant','Standard').lower()!='standard' or tags.get('SetUp')=='1' or 'FEN' in tags:return None,'variant_or_setup'
    tc=tags.get('TimeControl','');speed=speed_from_tc(tc)
    if speed is None:
        require(tc=='-' or re.fullmatch(r'\d+/\d+',tc) is not None,'Missing or unknown PGN TimeControl')
        return None,'untimed_or_correspondence'
    date=tags.get('UTCDate',tags.get('Date',''))
    require(date.startswith(month.replace('-','.')),'PGN date lies outside the named month')
    result=tags.get('Result','')
    require(result in RESULTS,'Unknown PGN result')
    # Stars are retained when present: they are still observed games with a recorded ply count.
    return (speed,ply_count(body,result)),'included'

def iter_games(stream):
    tags={};body=[];moves_started=False
    for line in stream:
        if line.startswith('[Event '):
            if tags:
                require(moves_started,'Game has no movetext')
                yield tags,''.join(body)
            tags={};body=[];moves_started=False
        if not tags and not line.startswith('[Event '):
            require(not line.strip(),'Text before first PGN Event header');continue
        if not moves_started and line.startswith('['):
            m=TAG.match(line.rstrip('\r\n'));require(m is not None,'Malformed PGN tag line')
            require(m[1] not in tags,'Duplicate PGN tag');tags[m[1]]=m[2]
        elif line.strip():moves_started=True;body.append(line)
    if tags:
        require(moves_started,'Truncated PGN final game');yield tags,''.join(body)

class HashReader(io.RawIOBase):
    def __init__(self,path):self.raw=open(path,'rb');self.digest=hashlib.sha256();self.bytes=0
    def readable(self):return True
    def readinto(self,b):
        n=self.raw.readinto(b)
        if n:self.digest.update(memoryview(b)[:n]);self.bytes+=n
        return n
    def close(self):self.raw.close();super().close()

def pgn_month(t):
    path=Path(t['path']);out=Path(t['out']);start=time.monotonic();key=fingerprint([t['key'],str(path.resolve()),stamp(path)])
    if valid(out,key):return dict(seconds=0,reused=True,**load(out))
    before=stamp(path);raw=HashReader(path);buffered=io.BufferedReader(raw,buffer_size=4*1024*1024)
    if path.name.endswith('.zst'):
        import zstandard
        stream=zstandard.ZstdDecompressor().stream_reader(buffered,read_across_frames=True,closefd=False)
    elif path.name.endswith('.gz'):stream=gzip.GzipFile(fileobj=buffered)
    elif path.name.endswith('.bz2'):stream=bz2.BZ2File(buffered)
    else:stream=buffered
    hist=Counter();dispositions=Counter();total=0;next_log=time.monotonic()+45
    try:
        text_stream=io.TextIOWrapper(stream,encoding='utf-8',errors='strict',newline=None)
        for tags,body in iter_games(text_stream):
            record,status=game_record(tags,body,t['month']);dispositions[status]+=1;total+=1
            if record is not None:hist[record]+=1
            if time.monotonic()>=next_log:
                elapsed=time.monotonic()-start;fraction=min(raw.bytes/path.stat().st_size,.9999)
                eta=elapsed*(1-fraction)/max(fraction,1e-8)
                log(f'All games {t["month"]}: {total:,} games; {100*fraction:.1f}% compressed bytes; month ETA {eta/60:.1f} min')
                next_log=time.monotonic()+45
        # At EOF all compressed/plain bytes must have been consumed.
        require(raw.bytes==before['bytes'],'PGN source was not consumed to EOF')
        digest=raw.digest.hexdigest()
        require(stamp(path)==before,'PGN source changed during the scan')
        sidecar=Path(str(path)+'.sha256')
        if sidecar.exists():require(sidecar.read_text().split()[0]==digest,'PGN sidecar checksum mismatch')
        require(total>0 and sum(hist.values())>0,'Empty monthly all-game census')
        rows=[dict(speed_code=s,ply=p,games=n) for (s,p),n in sorted(hist.items())]
        r=dict(month=t['month'],games_read=total,included_games=sum(hist.values()),dispositions=dict(dispositions),source_sha256=digest,source_bytes=before['bytes'],histogram=rows)
        dump(out,r);certify(out,key);return dict(seconds=time.monotonic()-start,reused=False,**r)
    finally:buffered.close()

def population():return 'rated standard live games; all match sources and endings; author accounts retained; 2023-11 through 2025-10 requested'

def discover(roots):
    """Find available target-month archives; absence never blocks other months."""
    candidates={m:[] for m in MONTHS};seen=set();inventory=[]
    pattern=re.compile(r'^lichess_db_standard_rated_(\d{4}-\d{2})\.pgn(?:\.zst|\.gz|\.bz2)?$')
    for root in roots:
        root=Path(root).expanduser();inventory.append(dict(path=str(root),exists=root.is_dir()))
        if not root.is_dir():continue
        for path in sorted(root.rglob('lichess_db_standard_rated_*.pgn*')):
            match=pattern.fullmatch(path.name)
            if not match or match[1] not in candidates or not path.is_file():continue
            canonical=str(path.resolve())
            if canonical in seen:continue
            seen.add(canonical);candidates[match[1]].append(canonical)
    # Roots are ordered by preference; alternatives are tried if the first source fails.
    return [dict(month=m,candidates=candidates[m]) for m in MONTHS],inventory

def safe_month(t):
    start=time.monotonic();errors=[]
    for path in t['candidates']:
        try:
            result=pgn_month(dict(t,path=path))
            return dict(status='INCLUDED',source_name=Path(path).name,alternative_sources=len(t['candidates'])-1,attempt_errors=errors,**result)
        except Exception as e:
            log(f'All games {t["month"]}: source rejected: {e}')
            errors.append(dict(source_name=Path(path).name,error=str(e)))
    return dict(month=t['month'],status='SOURCE_FAILED',included_games=0,seconds=time.monotonic()-start,reused=False,attempt_errors=errors)

def histogram_quantile(plies,counts,p):
    n=int(np.sum(counts));require(n>0,'Quantile of empty histogram')
    index=(n-1)*p;left=int(np.floor(index));right=int(np.ceil(index));cum=np.cumsum(counts,dtype=np.int64)
    a=int(plies[np.searchsorted(cum,left+1)]);b=int(plies[np.searchsorted(cum,right+1)])
    return float(a+(index-left)*(b-a))

def finish(results,run,discovery,inventory):
    sources=[r for r in results if r['status']=='INCLUDED'];months=sorted(r['month'] for r in sources)
    require(len(months)==len(set(months)) and set(months)<=set(MONTHS),'Duplicate or out-of-window monthly census')
    coverage=[];by={r['month']:r for r in results}
    for d in discovery:
        r=by.get(d['month']);coverage.append(dict(month=d['month'],status=r['status'] if r else 'MISSING',candidate_files=len(d['candidates']),
          games_read=int(r.get('games_read',0)) if r else 0,included_games=int(r.get('included_games',0)) if r else 0,
          source_name=r.get('source_name','') if r else '',source_sha256=r.get('source_sha256','') if r else '',
          reason=json.dumps(r.get('attempt_errors',[])) if r and r['status']!='INCLUDED' else ('' if r else 'No monthly PGN found in searched roots')))
    table(run/'report/all_games_month_coverage',coverage)
    records=[x for r in sources for x in r['histogram']]
    d=pd.DataFrame(records,columns=['speed_code','ply','games'])
    if len(d):d=d.groupby(['speed_code','ply'],as_index=False).games.sum().sort_values(['speed_code','ply'])
    require(int(d.games.sum())==sum(r['included_games'] for r in sources),'Histogram does not conserve monthly counts')
    table(run/'report/all_games_ply_histogram',d)
    med=[]
    for k,speed in enumerate(SPEEDS):
        a=d[d.speed_code==k];n=int(a.games.sum());record=dict(speed=speed,games=n,months_used=','.join(months),n_months=len(months),status='ESTIMATED' if n else 'NO_GAMES_AVAILABLE')
        for label,p in [('p25_plies',.25),('median_plies',.5),('p75_plies',.75)]:record[label]=histogram_quantile(a.ply.to_numpy(),a.games.to_numpy(dtype=np.int64),p) if n else None
        med.append(record)
    table(run/'report/all_games_plies_by_speed',med)
    status='COMPLETE_24_MONTHS' if len(months)==24 else ('PARTIAL_AVAILABLE_MONTHS' if months else 'NO_MONTHS_AVAILABLE')
    public_sources=[{k:r[k] for k in ['month','games_read','included_games','dispositions','source_name','source_sha256','source_bytes']} for r in sources]
    result=dict(status=status,population=population(),months_requested=MONTHS,months_used=months,months_missing_or_failed=[m for m in MONTHS if m not in months],
      games=int(d.games.sum()),monthly_sources=public_sources,method='Exact pooled histogram; quantile index (N-1)*p with linear interpolation, type 7; fully parsed through EOF; source SHA-256 recorded; no API or engine',
      archive_coverage='Files are local monthly standard-rated archives. EOF and available sidecar checks pass; no claim of coverage for an absent or failed month.',
      speed_definition='initial seconds + 40*increment; cutoffs 30,180,480,1500, inherited from checked R10 definition',
      searched_roots=len(inventory),regressions_complete=True)
    dump(run/'report/ALL_GAMES_STATUS.json',result);return result

