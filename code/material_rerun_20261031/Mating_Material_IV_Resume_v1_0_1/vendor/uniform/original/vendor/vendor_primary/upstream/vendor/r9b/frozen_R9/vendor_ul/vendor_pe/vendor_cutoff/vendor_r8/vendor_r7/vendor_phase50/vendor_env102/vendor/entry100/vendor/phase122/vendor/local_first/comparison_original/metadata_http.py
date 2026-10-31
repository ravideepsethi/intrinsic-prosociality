"""One metadata request at a time; verified TLS; server cooldowns only."""
import datetime as dt, email.utils, http.client, json, math, os, socket, ssl, time
import urllib.error, urllib.request
import local_io as io
from preliminary_core import GID

URL='https://lichess.org/api/games/export/_ids?moves=false&clocks=false&evals=false&opening=false&literate=false&pgnInJson=false&tags=true'

def parse(raw,ids):
    wanted=set(ids);found={}
    for line in raw.decode('utf-8').splitlines():
        if not line.strip():continue
        obj=json.loads(line)
        if not isinstance(obj,dict) or obj.get('id') not in wanted or obj['id'] in found:
            raise RuntimeError('Malformed, duplicate or unrequested response ID; request not committed')
        found[obj['id']]=obj
    return found

def delay(status,headers,attempt,now):
    value=min(300,5*2**min(attempt,6))
    if status==429:value=max(60,value)
    s=headers.get('Retry-After') if headers else None
    if s:
        try:
            try:t=float(s)
            except ValueError:t=email.utils.parsedate_to_datetime(s).timestamp()-now
            if math.isfinite(t):value=max(value,t)
        except (ValueError,TypeError,OverflowError):pass
    return max(value,0)

class Client:
    def __init__(self,cooldown_path,opener=None,sleeper=time.sleep,clock=time.time):
        self.path=cooldown_path;self.opener=opener or urllib.request.urlopen;self.sleeper=sleeper;self.clock=clock
        self.requests=0;self.http_seconds=0;self.wait_seconds=0
        self.context=ssl.create_default_context()
        try:
            import certifi
            self.context.load_verify_locations(cafile=certifi.where())
        except ImportError:pass
    def wait(self):
        until=io.load(self.path).get('until',0) if self.path.exists() else 0
        while until>self.clock():
            seconds=min(45,until-self.clock());self.sleeper(seconds);self.wait_seconds+=seconds
            if until>self.clock():io.log(f'Server/error cooldown: {until-self.clock():.0f}s remaining')
    def get(self,ids):
        if not 1<=len(ids)<=300 or len(set(ids))!=len(ids) or any(not GID.fullmatch(g) for g in ids):
            raise RuntimeError('Invalid 1–300-ID request')
        headers={'Accept':'application/x-ndjson','Content-Type':'text/plain','Accept-Encoding':'identity',
                 'User-Agent':'LichessKindnessComparisonExpansion/1.0.0'}
        token=os.environ.get('LICHESS_API_TOKEN') or os.environ.get('LICHESS_TOKEN')
        if token:headers['Authorization']='Bearer '+token.strip()
        request=urllib.request.Request(URL,data=','.join(ids).encode('ascii'),headers=headers,method='POST')
        for attempt in range(12):
            self.wait();status=None;error_headers={};t0=time.monotonic()
            try:
                self.requests+=1
                with self.opener(request,timeout=180,context=self.context) as response:
                    if response.status!=200:raise RuntimeError('Unexpected HTTP status')
                    if 'ndjson' not in response.headers.get('Content-Type','').lower():raise RuntimeError('Expected NDJSON response')
                    raw=response.read(32*1024**2+1)
                if len(raw)>32*1024**2:raise RuntimeError('Metadata response exceeds 32 MiB limit')
                parse(raw,ids);return raw
            except ssl.SSLCertVerificationError:
                raise RuntimeError('TLS verification failed; install a trusted CA bundle. Verification remains enabled.') from None
            except urllib.error.HTTPError as e:
                status=e.code;error_headers=e.headers;e.close()
                if status not in (408,425,429,500,502,503,504):raise RuntimeError('HTTP '+str(status)+'; completed requests remain saved') from None
            except urllib.error.URLError as e:
                if isinstance(e.reason,ssl.SSLCertVerificationError):raise RuntimeError('TLS verification failed; verification remains enabled') from None
            except (TimeoutError,socket.timeout,ConnectionError,http.client.IncompleteRead,http.client.RemoteDisconnected):pass
            finally:self.http_seconds+=time.monotonic()-t0
            pause=delay(status,error_headers,attempt,self.clock());io.js(self.path,dict(until=self.clock()+pause))
            io.log(f'Request retry {attempt+1}/12; HTTP {status}; server/error cooldown {pause:.0f}s')
        raise RuntimeError('Retry limit reached; rerun the same command to resume')
