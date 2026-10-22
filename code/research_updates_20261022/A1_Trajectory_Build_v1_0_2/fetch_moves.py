"""Single-request Lichess exports with saved responses and bounded retries."""
from __future__ import annotations
import datetime as dt,email.utils,gzip,http.client,json,math,os,re,socket,ssl,time
import urllib.error,urllib.parse,urllib.request
from pathlib import Path
import local_io as io

PARAMS={'moves':'true','clocks':'true','evals':'false','opening':'false','literate':'false','pgnInJson':'false'}
URL='https://lichess.org/api/games/export/_ids?'+urllib.parse.urlencode(PARAMS)
MAX_BODY=32*1024**2

def parse_response(raw,requested):
    wanted=set(requested);found={}
    try:
        for line in raw.decode('utf-8').splitlines():
            if not line.strip():continue
            o=json.loads(line)
            if not isinstance(o,dict) or not isinstance(o.get('id'),str):raise ValueError('Not a game')
            key=o['id']
            if key not in wanted or key in found:raise ValueError('Unexpected or duplicate game')
            found[key]=o
    except (UnicodeError,ValueError):raise RuntimeError('Invalid export response: malformed, duplicate, or unexpected game ID') from None
    return found

def ssl_context():
    ctx=ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except ImportError:pass
    return ctx

def retry_delay(status,headers,attempt,now=None):
    delay=min(300,5*2**min(attempt,6))
    if status==429:delay=max(60,delay)
    val=headers.get('Retry-After') if headers else None
    if val:
        try:
            try:x=float(val)
            except ValueError:
                stamp=email.utils.parsedate_to_datetime(val)
                if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=dt.timezone.utc)
                x=stamp.timestamp()-(time.time() if now is None else now)
            if math.isfinite(x):delay=max(delay,x)
        except (TypeError,ValueError,OverflowError):pass
    return max(0,delay)

def cooldown(seconds,sleeper=time.sleep):
    left=seconds
    while left>0:
        step=min(left,45);sleeper(step);left-=step
        if left>0:io.log(f'Server/error cooldown: {left:.0f}s left')

class Client:
    def __init__(self,opener=None,sleeper=time.sleep):
        self.context=ssl_context();self.opener=opener or urllib.request.urlopen;self.sleeper=sleeper
        self.requests=0;self.wait_seconds=0;self.http_seconds=0
    def get(self,ids):
        if not 1<=len(ids)<=300 or len(set(ids))!=len(ids) or any(not re.fullmatch(r'[A-Za-z0-9]{8}',s) for s in ids):
            raise RuntimeError('Invalid 1–300 game-ID request')
        headers={'Accept':'application/x-ndjson','Content-Type':'text/plain',
                 'User-Agent':'A1-Trajectory-Research/1.0.0','Accept-Encoding':'identity'}
        # Token is optional and is never written to receipts or logs.
        token=os.environ.get('LICHESS_TOKEN')
        if token:headers['Authorization']='Bearer '+token.strip()
        req=urllib.request.Request(URL,data=','.join(ids).encode('ascii'),headers=headers,method='POST')
        for attempt in range(12):
            status=None;error_headers={};started=time.monotonic()
            try:
                self.requests+=1
                with self.opener(req,timeout=180,context=self.context) as response:
                    status=response.status
                    if status!=200:raise RuntimeError('Unexpected HTTP status '+str(status))
                    raw=response.read(MAX_BODY+1)
                    if len(raw)>MAX_BODY:raise RuntimeError('Export body exceeds expected batch size')
                parse_response(raw,ids)
                return raw
            except ssl.SSLCertVerificationError:
                raise RuntimeError('TLS certificate verification failed. Use a trusted Python CA bundle; verification remains enabled.') from None
            except urllib.error.HTTPError as e:
                status=e.code;error_headers=e.headers;e.close()
                if status not in (408,425,429,500,502,503,504):
                    raise RuntimeError('Lichess HTTP '+str(status)+'; saved earlier batches remain reusable') from None
            except urllib.error.URLError as e:
                if isinstance(e.reason,ssl.SSLCertVerificationError):
                    raise RuntimeError('TLS certificate verification failed. Use a trusted Python CA bundle; verification remains enabled.') from None
            except (TimeoutError,socket.timeout,ConnectionError,http.client.IncompleteRead,http.client.RemoteDisconnected):pass
            finally:self.http_seconds+=time.monotonic()-started
            delay=retry_delay(status,error_headers,attempt)
            self.wait_seconds+=delay
            io.log(f'Request retry {attempt+1}/12; HTTP {status}; cooldown {delay:.0f}s')
            cooldown(delay,self.sleeper)
        raise RuntimeError('Export retry limit reached; rerun the same command to resume')

def recover_unit(path,targets,conf,client):
    """Each complete request is committed before processing the next response."""
    ids=[t['exposure_game_id'] for t in targets];records={}
    for pass_index in range(3):
        missing=[s for s in ids if s not in records]
        if not missing:break
        attempt_conf=io.cfgsha([conf,missing,pass_index,URL])
        def fetch(out):
            raw=client.get(missing)
            with gzip.open(out/'response_PRIVATE.ndjson.gz','wb',compresslevel=1) as f:f.write(raw)
            count=len(parse_response(raw,missing))
            io.js(out/'request_PRIVATE.json',{'ids':missing,'url':URL,'returned':count,'pass_index':pass_index})
            return {'requested':len(missing),'returned':count}
        saved,_=io.stage(Path(path)/('pass_'+str(pass_index)),attempt_conf,fetch)
        with gzip.open(saved/'response_PRIVATE.ndjson.gz','rb') as f:raw=f.read()
        records.update(parse_response(raw,missing))
    return records
