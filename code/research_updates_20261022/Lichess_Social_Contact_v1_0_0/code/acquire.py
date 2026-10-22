"""Sequential, read-only public opponent-filtered exports with per-pair receipts."""
from core import *
import gzip, urllib.request, urllib.parse, urllib.error, socket, http.client

class PairUnavailable(RuntimeError):pass

def request_spec(t):
    # Omit rated/perfType/max to include casual, correspondence, and variants without a count cap.
    params=dict(vs=t['recipient_name'],since=int(t['start']-91*DAY),until=int(t['anchor']+181*DAY),
      moves='false',clocks='false',evals='false',opening='false',pgnInJson='false',finished='true',ongoing='false',sort='dateAsc')
    url='https://lichess.org/api/games/user/'+urllib.parse.quote(t['giver_name'],safe='')+'?'+urllib.parse.urlencode(params)
    return dict(url=url,parameters=params,giver=t['giver_name'],recipient=t['recipient_name'])

def normalize(raw,t,expected):
    records={};duplicates=0;outside=0
    for x in raw:
        if not isinstance(x,dict) or 'error' in x:raise PairUnavailable('Export returned an error object')
        gid=x.get('id');created=x.get('createdAt');rated=x.get('rated')
        if not isinstance(gid,str) or not isinstance(created,int) or not isinstance(rated,bool) or not isinstance(x.get('status'),str):
            raise PairUnavailable('Export is missing game ID, time, or rated status')
        players=x.get('players',{});names=[]
        for color in ('white','black'):
            u=players.get(color,{}).get('user',{})
            names.append(str(u.get('id',u.get('name',''))).strip().lower())
        if set(names)!={t['giver_name'],t['recipient_name']}:
            raise PairUnavailable('Opponent filter or player identity could not be verified')
        lo=t['start']-90*DAY;hi=t['anchor']+180*DAY
        # Parent PGN starts have second precision; include a one-second validation buffer.
        if created<lo-1000 or created>hi+1000:outside+=1;continue
        source=x.get('source');source=source if isinstance(source,str) and source else None
        z=dict(gid=gid,created=created,last_move=x.get('lastMoveAt'),rated=rated,source=source,
          status=x.get('status'),variant=x.get('variant'),speed=x.get('speed'))
        if gid in records:
            if records[gid]!=z:raise PairUnavailable('Conflicting duplicate games in export')
            duplicates+=1
        records[gid]=z
    missing=[]
    for gid,time0 in expected.items():
        x=records.get(gid)
        if x is None or not x['rated'] or x['created']//1000!=int(time0)//1000:missing.append(gid)
    focal=records.get(t['gid'])
    if focal is None or focal['created']//1000!=int(t['start'])//1000:
        raise PairUnavailable('Focal game absent or time inconsistent; absence is not zero contact')
    if focal['last_move']!=t['anchor']:raise PairUnavailable('Focal lastMoveAt differs from authenticated parent')
    if missing:raise PairUnavailable(f'Export failed to reproduce {len(missing)} known rated games')
    return list(records.values()),dict(duplicate_rows=duplicates,rows_outside_window=outside,
      known_rated_validated=len(expected),missing_source_rows=sum(x['source'] is None for x in records.values()),
      limitation='Successful export reproduces known rated games; completeness of unobserved casual histories is not independently certified')

class Client:
    def __init__(self, pause=1.0, opener=urllib.request.urlopen, sleeper=time.sleep):
        self.pause=max(1.0,pause);self.open=opener;self.sleep=sleeper;self.requests=0;self.last_request=0
    def get(self,url):
        for attempt in range(6):
            self.sleep(max(0.,self.pause-(time.monotonic()-self.last_request)))
            req=urllib.request.Request(url,headers={'Accept':'application/x-ndjson','User-Agent':'LichessSocialContactResearch/1.0 (sequential public export)'})
            self.requests+=1;self.last_request=time.monotonic()
            try:
                with self.open(req,timeout=90) as response:
                    if response.status!=200:raise PairUnavailable('Unexpected HTTP response')
                    mime=response.headers.get('Content-Type','').lower()
                    if 'ndjson' not in mime and 'json' not in mime:raise PairUnavailable('Expected NDJSON, received another content type')
                    chunks=[];size=0
                    for line in response:
                        size+=len(line)
                        if size>64*1024*1024:raise PairUnavailable('Pair export exceeds 64 MiB safeguard; not truncated to zero')
                        if line.strip():chunks.append(json.loads(line))
                    return chunks
            except urllib.error.HTTPError as e:
                if e.code in (401,403,404,410):raise PairUnavailable('Public pair history unavailable: HTTP '+str(e.code)) from None
                if e.code==429:
                    delay=max(60, min(3600,int(e.headers.get('Retry-After','60'))) if str(e.headers.get('Retry-After','60')).isdigit() else 60)
                    log(f'API rate limit: waiting {delay}s, then resuming');self.sleep(delay)
                elif e.code>=500:self.sleep(min(60,2**attempt*2))
                else:raise PairUnavailable('HTTP '+str(e.code)) from None
            except (urllib.error.URLError,socket.timeout,TimeoutError,ConnectionError,http.client.HTTPException,json.JSONDecodeError):
                if attempt<5:self.sleep(min(60,2**attempt*2))
        raise RuntimeError('Repeated API transport/rate-limit failure; rerun to resume completed pairs')

def acquire_one(t, expected, cache, client, retry_unavailable=False):
    spec=request_spec(t);folder=Path(cache)/digest(spec)[:24]
    old=cached(folder)
    if old and (old['status']=='COMPLETE' or not retry_unavailable):
        return (load(folder/'games.json') if old['status']=='COMPLETE' else None),dict(**old,reused=True)
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'_DONE.json').exists():(folder/'_DONE.json').unlink()
    dump(folder/'request.json',spec)
    try:
        raw=client.get(spec['url'])
        with gzip.open(folder/'response.ndjson.gz','wt') as f:
            for x in raw:f.write(json.dumps(x,separators=(',',':'))+'\n')
        games,qa=normalize(raw,t,expected);dump(folder/'games.json',games)
        result=dict(status='COMPLETE',fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),**qa)
        finish(folder,result);return games,dict(**result,reused=False)
    except PairUnavailable as e:
        result=dict(status='UNAVAILABLE',reason=str(e),fetched_at=dt.datetime.now(dt.timezone.utc).isoformat())
        finish(folder,result);return None,dict(**result,reused=False)
