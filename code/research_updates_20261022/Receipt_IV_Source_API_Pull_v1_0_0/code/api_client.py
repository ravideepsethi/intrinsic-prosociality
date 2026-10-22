"""Sequential public API client; records raw responses and respects backoff."""
from __future__ import annotations
import email.utils, gzip, http.client, socket, time, urllib.error, urllib.parse, urllib.request
from common import *

class PullStopped(RuntimeError):pass

def retry_seconds(status,header,failures,now=None):
    seconds=0.0
    if header:
        try:seconds=float(header)
        except ValueError:
            try:
                t=email.utils.parsedate_to_datetime(header).timestamp()
                seconds=t-(time.time() if now is None else now)
            except (ValueError,TypeError,OverflowError):pass
    floor=60.0 if status==429 else min(300.0,5.0*2**min(failures,6))
    return max(floor,seconds)

def wait_with_progress(seconds):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        remaining=until-time.monotonic()
        if remaining>=10:log(f'API backoff: {remaining:.0f} seconds remaining')
        time.sleep(min(30,remaining))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise urllib.error.HTTPError(req.full_url,code,'API redirect refused',headers,fp)

class Client:
    def __init__(self,interval=0.0,timeout=90,opener=None,sleeper=wait_with_progress,cooldown_path=None):
        self.interval=interval;self.timeout=timeout;self.sleeper=sleeper
        self.opener=opener or urllib.request.build_opener(NoRedirect())
        self.last_finished=0.0;self.requests=0;self.throttles=0
        self.token=os.environ.get('LICHESS_API_TOKEN','').strip()
        self.cooldown_path=Path(cooldown_path) if cooldown_path else None

    def defer(self,seconds):
        if self.cooldown_path:
            write_json(self.cooldown_path,dict(next_request_after_unix=time.time()+seconds))

    def pause(self,seconds):
        self.defer(seconds)
        self.sleeper(seconds)

    def fetch(self,ids,directory,binding):
        if not 1<=len(ids)<=BATCH_SIZE or len(ids)!=len(set(ids)):
            raise ValueError('Each request needs 1–300 unique IDs')
        if self.cooldown_path and self.cooldown_path.is_file():
            remaining=load(self.cooldown_path)['next_request_after_unix']-time.time()
            if remaining>0:self.sleeper(remaining)
        delay=self.interval-(time.monotonic()-self.last_finished)
        if delay>0:self.sleeper(delay)
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        name=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+uuid.uuid4().hex[:8]
        body_path=directory/(name+'.ndjson.gz');tmp=body_path.with_suffix('.gz.partial')
        headers={'Accept':'application/x-ndjson','Content-Type':'text/plain',
                 'User-Agent':'LichessReceiptIVMetadata/1.0 (sequential research export)'}
        if self.token:headers['Authorization']='Bearer '+self.token
        req=urllib.request.Request(ENDPOINT+'?'+urllib.parse.urlencode(PARAMS),
                                  data=','.join(ids).encode('ascii'),headers=headers,method='POST')
        start=time.monotonic();objects=[];status=None;retry_after=None;problem=None;bytes_read=0
        self.requests+=1
        try:
            with gzip.open(tmp,'wb',compresslevel=3) as raw:
                try:
                    with self.opener.open(req,timeout=self.timeout) as response:
                        status=response.status
                        content_type=response.headers.get('Content-Type','').split(';')[0].strip().lower()
                        if status!=200:raise PullStopped('Unexpected non-200 API response')
                        if content_type not in ('application/x-ndjson','application/ndjson','application/json'):
                            raise PullStopped('API did not return NDJSON/JSON')
                        while True:
                            line=response.readline(2*1024**2+1)
                            if not line:break
                            raw.write(line);bytes_read+=len(line)
                            if len(line)>2*1024**2 or bytes_read>64*1024**2:
                                raise PullStopped('API response exceeded the bounded metadata limit')
                            if not line.strip():continue
                            try:obj=json.loads(line)
                            except (ValueError,UnicodeError):raise PullStopped('Malformed API NDJSON') from None
                            if not isinstance(obj,dict):raise PullStopped('API record is not a JSON object')
                            objects.append(obj)
                except urllib.error.HTTPError as e:
                    status=e.code;retry_after=e.headers.get('Retry-After') if e.headers else None
                    problem='HTTP_'+str(status)
                    if status==429:self.throttles+=1
                    # Error-body text is not useful game evidence and can contain
                    # private diagnostics. Keep only status and Retry-After.
                    e.close()
                except (urllib.error.URLError,TimeoutError,socket.timeout,ConnectionError,
                        http.client.HTTPException,OSError) as e:
                    problem='transport_'+type(e).__name__
        except PullStopped as e:
            problem='protocol_'+str(e)
        finally:
            self.last_finished=time.monotonic()
        if status==429:self.defer(retry_seconds(status,retry_after,0))
        # Native bytes are preserved even for a partial response. Only complete
        # JSON objects parsed before a transport failure can be used below.
        if tmp.exists():os.replace(tmp,body_path)
        else:
            with gzip.open(body_path,'wb'):pass
        with body_path.open('rb') as f:os.fsync(f.fileno())
        result=dict(binding=binding,request_ids=ids,status=status,retry_after=retry_after,
                    problem=problem,objects=objects,elapsed_seconds=time.monotonic()-start,
                    raw=receipt(body_path,directory),authenticated=bool(self.token))
        saved={k:v for k,v in result.items() if k!='objects'}
        saved['parsed_objects']=len(objects)
        write_json(directory/(name+'.receipt.json'),saved)
        return result
