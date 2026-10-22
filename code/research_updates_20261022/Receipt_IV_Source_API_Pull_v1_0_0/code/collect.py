"""Commit one 300-ID batch at a time; resume using authenticated responses."""
import gzip
from collections import Counter
from common import *
from api_client import PullStopped,retry_seconds
from records import SCHEMA,normalize,not_returned

OMISSION_ATTEMPTS=3
MAX_TRANSIENT_FAILURES=8

def restore_attempt(path,binding,auth):
    r=load(path)
    if r['binding']!=binding:raise RuntimeError('Attempt belongs to a different frozen request')
    raw=Path(path).parent/r['raw']['path'];checked(raw,r['raw'],auth)
    objects=[]
    if not (r.get('problem') or '').startswith('protocol_'):
        with gzip.open(raw,'rt',encoding='utf-8') as f:
            for line in f:
                if not line.strip():continue
                if len(objects)>=r['parsed_objects']:break
                objects.append(json.loads(line))
        if len(objects)!=r['parsed_objects']:raise RuntimeError('Raw attempt count differs from receipt')
    return dict(r,objects=objects)

def accept_attempt(r,target_map,seen,omissions,attempt_path):
    requested=r['request_ids']
    if len(requested)!=len(set(requested)) or not set(requested)<=set(target_map):
        raise PullStopped('Saved request ID set is invalid')
    if (r.get('problem') or '').startswith('protocol_'):return
    ids=[o.get('id') if isinstance(o,dict) else None for o in r['objects']]
    if len(ids)!=len(set(ids)) or not set(ids)<=set(requested):
        raise PullStopped('API returned unexpected or duplicate IDs; native response preserved')
    normalized=[normalize(obj,target_map[obj['id']],attempt_path) for obj in r['objects']]
    for row in normalized:
        key=row['game_id']
        if key in seen:
            # The normal collector requests pending IDs only. A duplicate
            # across committed attempts indicates a checkpoint conflict.
            raise PullStopped('An API ID occurs in multiple committed attempts')
        seen[key]=row
    if r['status']==200 and not r.get('problem'):
        omissions.update(set(requested)-set(ids))

def collect_batch(root,targets,plan_binding,client,auth):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    binding=digest(dict(plan=plan_binding,targets=targets))
    done_path=root/'_DONE.json'
    if done_path.is_file():
        done=load(done_path)
        if done['binding']!=binding:raise RuntimeError('Completed batch target binding changed')
        for r in done['files']:checked(root/r['path'],r,auth)
        return done,False
    attempts=root/'attempts';attempts.mkdir(exist_ok=True)
    target_map={r['game_id']:r for r in targets}
    if len(target_map)!=len(targets):raise RuntimeError('Duplicate target within API batch')
    seen={};omissions=Counter();receipts=[]
    for p in sorted(attempts.glob('*.receipt.json')):
        r=restore_attempt(p,binding,auth)
        accept_attempt(r,target_map,seen,omissions,str(p))
        receipts.append(p)
    failures=0
    while True:
        pending=[k for k in target_map if k not in seen and omissions[k]<OMISSION_ATTEMPTS]
        if not pending:break
        r=client.fetch(pending,attempts,binding)
        p=attempts/(Path(r['raw']['path']).name.removesuffix('.ndjson.gz')+'.receipt.json')
        receipts.append(p)
        if (r.get('problem') or '').startswith('protocol_'):
            raise PullStopped('Unexpected API response format; native response preserved')
        accept_attempt(r,target_map,seen,omissions,str(p))
        if r['status'] in (401,403):
            raise PullStopped('API access denied. Check any LICHESS_API_TOKEN and resume; no token is required by this endpoint')
        if r['status'] is not None and r['status']!=200 and r['status']!=429 and r['status']<500:
            raise PullStopped('Non-retryable API HTTP status '+str(r['status']))
        if r.get('problem'):
            failures+=1
            delay=retry_seconds(r['status'],r.get('retry_after'),failures-1)
            log(f"API {r['problem']}; completed batches remain saved")
            if failures>=MAX_TRANSIENT_FAILURES:
                # Persist the cooldown for the next invocation, then stop now.
                # There is no reason to keep a stopped job sleeping.
                client.defer(delay)
                raise PullStopped('Repeated API/network failures; rerun the same command to resume')
            client.pause(delay)
        else:
            failures=0
    rows=[seen.get(t['game_id']) or not_returned(t) for t in targets]
    output=root/'metadata_PRIVATE.parquet';write_parquet(output,rows,SCHEMA)
    files=[receipt(output,root)]
    # Bind native bytes and receipt text. Resume checks cached file fingerprints
    # before reusing an earlier successful SHA-256 check.
    for p in receipts:
        r=load(p);files.append(receipt(p,root))
        raw=attempts/r['raw']['path'];files.append(dict(r['raw'],path=str(raw.relative_to(root))))
    done=dict(binding=binding,rows=len(rows),files=files,
        status_counts=dict(Counter(r['record_status'] for r in rows)),request_count=len(receipts),
        source_counts=dict(Counter(r['source'] for r in rows if r['record_status']=='validated_source')),
        api_omission_retries=OMISSION_ATTEMPTS)
    write_json(done_path,done)
    return done,True
