"""Read-only public API requests; sequential, persistent and resumable."""
import datetime as dt, email.utils, gzip, json, os, re, time
import requests
from common import *

def post(url,ids,accept):
    headers={'Accept':accept,'Content-Type':'text/plain','User-Agent':'Lichess-Tenure-Responsibility-Research/1.0.0'}
    token=os.environ.get('LICHESS_TOKEN')
    if token:headers['Authorization']='Bearer '+token.strip()
    for attempt in range(10):
        delay=min(300,5*2**attempt)
        try:
            r=requests.post(url,data=','.join(ids).encode('utf-8'),headers=headers,timeout=(30,180))
            if r.status_code==200:return r.content
            require(r.status_code in [408,425,429,500,502,503,504],'Lichess HTTP '+str(r.status_code))
            if r.status_code==429:delay=max(60,delay)
            v=r.headers.get('Retry-After')
            if v:
                try:delay=max(delay,float(v))
                except ValueError:
                    try:delay=max(delay,email.utils.parsedate_to_datetime(v).timestamp()-time.time())
                    except (ValueError,TypeError):pass
        except requests.exceptions.SSLError:raise RuntimeError('TLS verification failed; no insecure fallback') from None
        except (requests.exceptions.ConnectionError,requests.exceptions.Timeout):pass
        log(f'API retry {attempt+1}/10; waiting {delay:.0f} seconds')
        while delay>0:
            step=min(delay,40);time.sleep(step);delay-=step
            if delay>0:log(f'API cooldown: {delay:.0f} seconds remain')
    raise RuntimeError('API retry limit reached; completed responses preserved')

def fetch_batch(folder,ids,kind,enabled,key):
    found={};stamp=None
    for attempt in range(3):
        missing=[x for x in ids if x not in found]
        if not missing:break
        k=signature([key,kind,missing,attempt]);p=folder/(k+'.json.gz')
        if checkpoint(p,k):
            with gzip.open(p,'rt') as f:env=json.load(f)
        else:
            if not enabled:break
            if kind=='profiles':
                require(len(missing)<=300 and all(re.fullmatch(r'[A-Za-z0-9_-]{1,40}',s) for s in missing),'Invalid profile request')
                raw=post('https://lichess.org/api/users',missing,'application/json');objects=json.loads(raw)
                require(isinstance(objects,list),'Profile API returned a non-list')
            else:
                require(len(missing)<=300 and all(re.fullmatch(r'[A-Za-z0-9]{8}',s) for s in missing),'Invalid game request')
                raw=post('https://lichess.org/api/games/export/_ids?moves=true&clocks=false&evals=false&opening=false&literate=false&pgnInJson=false',missing,'application/x-ndjson')
                objects=[json.loads(x) for x in raw.decode().splitlines() if x.strip()]
            seen=set()
            for o in objects:
                ident=o.get('id');ident=ident.lower() if kind=='profiles' and isinstance(ident,str) else ident
                require(ident in missing and ident not in seen,'Unexpected/duplicate API ID');seen.add(ident)
            env=dict(queried_at=dt.datetime.now(dt.timezone.utc).isoformat(),requested=missing,objects=objects)
            p.parent.mkdir(parents=True,exist_ok=True);t=Path(str(p)+'.partial')
            with gzip.open(t,'wt',compresslevel=1) as f:json.dump(env,f)
            os.replace(t,p);certify(p,k)
        require(env['requested']==missing,'Cached API request mismatch')
        stamp=env['queried_at']
        for o in env['objects']:
            ident=o['id'].lower() if kind=='profiles' else o['id'];require(ident in missing,'Cached API ID mismatch');found[ident]=o
    return found,stamp

def profiles(db,run,args,key):
    wanted=[r[0] for r in db.execute('''SELECT s.username FROM selected s LEFT JOIN profiles_cache p USING(username)
      WHERE p.created_ms IS NULL ORDER BY s.draw_rank''').fetchall()]
    rows=[]
    for start in range(0,len(wanted),300):
        ids=wanted[start:start+300];objects,stamp=fetch_batch(run/'PRIVATE/profile_responses',ids,'profiles',args.fetch_profiles,key)
        for name in ids:
            o=objects.get(name,{});v=o.get('createdAt');valid=isinstance(v,int) and not isinstance(v,bool) and 946684800000<=v<=int(time.time()*1000)
            rows.append(dict(username=name,created_ms=v if valid else None,returned=name in objects,queried_at=stamp))
        if start%3000==0:log(f'Profile creation dates: {min(start+300,len(wanted)):,}/{len(wanted):,} requested accounts processed')
    import pyarrow as pa
    tab=pa.Table.from_pylist(rows,schema=pa.schema([('username',pa.string()),('created_ms',pa.int64()),('returned',pa.bool_()),('queried_at',pa.string())]))
    p=run/'PRIVATE/fetched_profile_dates.parquet';pq.write_table(tab,p,compression='zstd');certify(p,key)
    db.execute(f'CREATE TEMP VIEW profiles_fetch AS SELECT * FROM read_parquet({qs(p)})')
    dump(run/'report/PROFILE_FETCH.json',dict(accounts_needing_dates=len(wanted),valid_dates=sum(x['created_ms'] is not None for x in rows),returned=sum(x['returned'] for x in rows),enabled=args.fetch_profiles))
