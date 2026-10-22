#!/usr/bin/env python3
"""Read-only input audit and local API-source recovery for chooser-leniency IV.

No API requests; no estimates; no rating-state replay; no automatic inference of
historical rageSit categories. Large generated outputs are private Parquet/ZSTD.
The 24-month Stage 07 inputs and the A1 checkpoint are never modified.
"""
from __future__ import annotations
import argparse
import collections
import concurrent.futures as cf
import contextlib
import csv
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import traceback
import uuid
import zipfile

VERSION = '1.0.0'
DAY = 86_400_000
MONTHS = tuple(f'{i//12:04d}-{i%12+1:02d}' for i in range(2023*12+10, 2023*12+34))
SOURCES = ('pool','lobby','friend','ai','api','tournament','arena','swiss','simul',
           'position','import','importlive','hook')
SOURCE_BITS = {s: 1 << i for i, s in enumerate(SOURCES)}
UNKNOWN_BIT = 1 << len(SOURCES)
EXPECTED = {
 'stage07_success': '8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7',
 'stage07_producer': '0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e',
 'recipient': '41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d',
 'core_success': 'bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009',
 'core_summary': 'fa49fb15e095fb961a3f4cca5b937d903bc890467ed8404e37683858dd20a269',
 'core_manifest': 'e2724dab02a2b7b7c10f68b63ed40ddc67f2345947aa923d851912df946d16d8',
}
CONDUCT = re.compile(r'rage.?sit|rage.?quit.?counter|gone.?weight|rating.?range|provisional|blocking|queue.?entry|missed.?waves|^misses$|trust.?score|^trust$|^lame$|is.?lame', re.I)
RAW_SUFFIXES = ('.ndjson','.jsonl','.ndjson.gz','.jsonl.gz','.ndjson.zst',
                '.jsonl.zst','.ndjson.zstd','.jsonl.zstd','.json.gz','.json.zst')
KEY_ALIASES = ('game_id','id')
SOURCE_ALIASES = ('api_source','source')
CREATED_ALIASES = ('api_created_at_ms','created_at_ms','createdAt')
STATUS_ALIASES = ('api_status','status')
RECIPIENT_COLUMNS = (
 'cohort_row_id','exposure_game_id','recipient_user_id','exposure_chooser_user_id',
 'exposure_anchor_utc_ms','exposure_game_utc_ms','received_mercy','exposure_claimed_win',
 'arm_eligible','first_ever_pair','a1_90d_followup_eligible','exposure_cell_code',
 'exposure_no_mating_draw','exposure_chooser_loss','exposure_month_code',
 'exposure_tc_base_s','exposure_tc_inc_s','exposure_speed_code',
 'reached_fair_chooser_within_90d','first_subsequent_kind_draw',
)
HISTORY_COLUMNS = ('chooser_user_id','disconnected_user_id','api_last_move_at_ms',
                   'kind_draw','timeout_chooser_win','game_id')
_GLOBAL_IDS = None


def log(s):
    print(f'[{dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%SZ")}] {s}', flush=True)


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()


def signature(p):
    st=Path(p).stat()
    return {'bytes':st.st_size,'mtime_ns':st.st_mtime_ns}


def atomic_json(p, x):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.tmp.'+uuid.uuid4().hex)
    t.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
    os.replace(t,p)


def csv_write(p, rows, fields=None):
    rows=list(rows)
    fields=fields or sorted({k for r in rows for k in r})
    with open(p,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def load(p): return json.loads(Path(p).read_text())


def hashcheck(p, expected):
    if not Path(p).is_file(): raise RuntimeError(f'Missing authority: {p}')
    actual=digest(p)
    if actual != expected: raise RuntimeError(f'Authority SHA-256 mismatch: {p}')
    return actual


def deps():
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    import zstandard as zstd
    return np,pa,pq,zstd


def pa_write(path, table):
    _,_,pq,_=deps()
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.partial.'+uuid.uuid4().hex)
    pq.write_table(table,tmp,compression='zstd',row_group_size=131072)
    os.replace(tmp,path)


def array(table,name,dtype=None,allow_null=False):
    import numpy as np
    c=table[name]
    if c.null_count and not allow_null: raise RuntimeError('Unexpected nulls in '+name)
    a=c.to_numpy(zero_copy_only=False)
    return np.asarray(a,dtype=dtype) if dtype is not None else a


def authenticate(args, private):
    """Pin the exact certified authorities; do not discover a replacement."""
    _,_,pq,_=deps()
    root=args.project_root
    stage=root/'derived/replication/analysis_panel_24m_sf100k'
    rec=root/'derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet'
    rr=rec.with_name('recipient_with_chronology_receipt.json')
    core=root/'output/dynamic_prosociality_core_v102/20260822T022146Z'
    hashcheck(stage/'_SUCCESS.json',EXPECTED['stage07_success'])
    ss=load(stage/'_SUCCESS.json')
    if ss.get('status')!='STAGE07_24M_CERTIFIED_OK' or ss.get('script_sha256')!=EXPECTED['stage07_producer']:
        raise RuntimeError('Stage 07 semantic authority mismatch')
    if {k:int(ss.get('global_qa',{}).get(k,-1)) for k in ('rows','kind_draws','fair_rows')} != {
       'rows':47587020,'kind_draws':669503,'fair_rows':17328130}:
        raise RuntimeError('Stage 07 certified counts mismatch')
    for key,name in [('core_success','_SUCCESS.json'),('core_summary','summary.json'),('core_manifest','report_file_hashes.tsv')]:
        hashcheck(core/name,EXPECTED[key])
    if load(core/'_SUCCESS.json').get('status')!='DYNAMIC_PROSOCIALITY_CORE_V102_OK':
        raise RuntimeError('A1 core status mismatch')
    hashcheck(rec,EXPECTED['recipient'])
    receipt=load(rr)
    if receipt.get('output_sha256')!=EXPECTED['recipient'] or receipt.get('rows')!=2556782:
        raise RuntimeError('Recipient checkpoint receipt mismatch')
    if pq.ParquetFile(rec).metadata.num_rows!=2556782: raise RuntimeError('Recipient footer count mismatch')
    paths=[stage/f'month={m}/analysis_panel.parquet' for m in MONTHS]
    listed=[Path(x.strip()) for x in (stage/'_manifests/analysis_panel_paths.txt').read_text().splitlines() if x.strip()]
    if listed!=paths: raise RuntimeError('Stage 07 path list differs from frozen authority')
    with open(stage/'_manifests/month_status.csv',newline='') as f: status=list(csv.DictReader(f))
    if [x['month'] for x in status]!=list(MONTHS): raise RuntimeError('Stage 07 month ordering mismatch')
    items=[]
    for p,r in zip(paths,status):
        if not p.is_file() or p.stat().st_size!=int(r['output_size_bytes']): raise RuntimeError('Stage 07 file/size mismatch: '+str(p))
        pf=pq.ParquetFile(p)
        if not set(HISTORY_COLUMNS).issubset(pf.schema_arrow.names): raise RuntimeError('Stage 07 history fields unavailable')
        items.append({'path':str(p),'month':r['month'],'expected_sha256':r['output_sha256'],**signature(p),'rows':pf.metadata.num_rows})
    if sum(x['rows'] for x in items)!=47587020: raise RuntimeError('Stage 07 footer sum mismatch')
    hashdir=private/'input_hash_checkpoints'; hashdir.mkdir(exist_ok=True)
    def one(r):
        p=Path(r['path']); receiptpath=hashdir/(r['month']+'.json')
        if receiptpath.exists():
            old=load(receiptpath)
            if old.get('signature')==signature(p) and old.get('sha256')==r['expected_sha256']:
                return
        before=signature(p); actual=digest(p)
        if signature(p)!=before or actual!=r['expected_sha256']: raise RuntimeError('Stage 07 content changed: '+str(p))
        atomic_json(receiptpath,{'signature':before,'sha256':actual})
        log('STAGE07_SHA_OK '+r['month'])
    with cf.ThreadPoolExecutor(max_workers=min(args.workers,4)) as ex: list(ex.map(one,items))
    atomic_json(private/'input_authorities.json',{'stage07_files':items,'recipient_path':str(rec),'pinned_sha256':EXPECTED})
    log('A1_AND_STAGE07_AUTHENTICATED')
    return rec,paths


def cohort_masks(d, enforce=True):
    """Literal A1 support rule; membership only, never ATT weights for IV."""
    import numpy as np
    first=np.asarray(d['first_ever_pair'],bool); arm=np.asarray(d['arm_eligible'],bool)
    treated=np.asarray(d['received_mercy'],bool); cell=np.asarray(d['exposure_cell_code'],np.int64)
    if not np.array_equal(arm,treated | np.asarray(d['exposure_claimed_win'],bool)):
        raise RuntimeError('A1 arm partition is not grant versus claim')
    if not np.array_equal(~arm,np.asarray(d['exposure_no_mating_draw'],bool)|np.asarray(d['exposure_chooser_loss'],bool)):
        raise RuntimeError('A1 excluded-arm partition changed')
    valid=first & arm & (cell>=0)
    if np.any(cell[valid]>=1152): raise RuntimeError('Unexpected A1 cell code')
    nt=np.bincount(cell[valid&treated],minlength=1152)
    nc=np.bincount(cell[valid&~treated],minlength=1152)
    good=(nt>=5)&(nc>=20)
    support=np.zeros(len(cell),bool); support[valid]=good[cell[valid]]
    full=valid & np.asarray(d['a1_90d_followup_eligible'],bool)
    published=full & support
    if enforce:
        counts=(int(published.sum()),int((published&treated).sum()),int((published&~treated).sum()))
        if counts!=(2185073,65085,2119988): raise RuntimeError('Frozen complete-follow-up cohort mismatch: '+str(counts))
        if int((published & np.asarray(d['reached_fair_chooser_within_90d'],bool)).sum())!=1029558:
            raise RuntimeError('Frozen reached cohort mismatch')
    return full,published


def build_targets(rec,private):
    np,pa,pq,_=deps()
    table=pq.ParquetFile(rec).read(columns=list(RECIPIENT_COLUMNS),use_threads=False)
    names=[n for n in RECIPIENT_COLUMNS if n not in ('exposure_game_id','first_subsequent_kind_draw')]
    d={n:array(table,n) for n in names}
    if not np.array_equal(d['cohort_row_id'],np.arange(2556782)): raise RuntimeError('A1 row alignment changed')
    full,published=cohort_masks(d)
    table=table.filter(pa.array(full))
    ids=np.asarray(table['exposure_game_id'].to_pylist(),dtype='U8')
    # Validate before fixed-width conversion; never truncate malformed IDs.
    if any(not re.fullmatch(r'[A-Za-z0-9]{8}',s or '') for s in table['exposure_game_id'].to_pylist()):
        raise RuntimeError('Malformed or missing A1 game ID')
    if len(np.unique(ids))!=len(ids): raise RuntimeError('Exposure game IDs are not unique')
    cols={
       'target_index':pa.array(np.arange(len(table),dtype=np.int64)),
       'cohort_row_id':table['cohort_row_id'], 'game_id':table['exposure_game_id'],
       'chooser_id':table['exposure_chooser_user_id'], 'recipient_id':table['recipient_user_id'],
       'archive_start_ms':table['exposure_game_utc_ms'], 'anchor_ms':table['exposure_anchor_utc_ms'],
       'received':table['received_mercy'], 'frozen_a1_support':pa.array(published[full]),
       'month_code':table['exposure_month_code'], 'speed_code':table['exposure_speed_code'],
       'tc_base_s':table['exposure_tc_base_s'], 'tc_inc_s':table['exposure_tc_inc_s'],
    }
    out=pa.table(cols)
    if out['chooser_id'].null_count or out['recipient_id'].null_count: raise RuntimeError('Missing identities')
    if np.any(array(out,'chooser_id')==array(out,'recipient_id')): raise RuntimeError('Self-opponent exposure')
    pa_write(private/'targets_private.parquet',out)
    result={'all_first_pair_arm_complete_followup':len(out),'frozen_a1_complete_followup':int(published.sum()),
            'frozen_receipts':65085,'frozen_claims':2119988,
            'ATT_weights_reused':False,'outcomes_reestimated':False,
            'same_opponent_outcome_exclusion_reauthenticated':False,
            'note':'T0 carries cohort membership, not a new outcome definition or IV sample certification.'}
    log('TARGET_COHORT_OK total='+str(len(out))+' published=2185073')
    return result


def conduct_paths(obj, prefix='', depth=0):
    """Keys/values are evidence candidates, not historically timed fields."""
    if depth>7 or not isinstance(obj,dict): return {}
    found={}
    for k,v in obj.items():
        p=f'{prefix}.{k}' if prefix else k
        if CONDUCT.search(k):
            # Private evidence only; do not publish usernames/block lists.
            found[p]=v if isinstance(v,(str,int,float,bool,type(None))) else {'container_type':type(v).__name__}
        if isinstance(v,dict): found.update(conduct_paths(v,p,depth+1))
    return found


def normalize(obj,aliases=False):
    def get(keys):
        for k in keys:
            if k in obj and obj[k] is not None: return obj[k]
        return None
    gid=get(KEY_ALIASES)
    if not isinstance(gid,str) or re.fullmatch(r'[A-Za-z0-9]{8}',gid) is None: return None
    raw=get(SOURCE_ALIASES); raw=raw.strip().lower() if isinstance(raw,str) else (None if raw is None else '__invalid_type__')
    source=raw if raw in SOURCE_BITS else ('__UNRECOGNIZED__' if raw not in (None,'') else None)
    v=get(CREATED_ALIASES)
    try: ts=int(v) if v is not None and not isinstance(v,bool) else None
    except (ValueError,TypeError,OverflowError): ts=None
    if ts is not None and not 1262304000000<=ts<4102444800000: ts=None
    status=get(STATUS_ALIASES)
    status=(status.strip().lower() or None) if isinstance(status,str) else None
    c=conduct_paths(obj)
    return {'game_id':gid,'source':source,'created_at_ms':ts,'api_status':status,
            'conduct_candidate_json':json.dumps(c,sort_keys=True,default=str) if c else None}


class HashReader(io.RawIOBase):
    def __init__(self,f): self.f=f; self.h=hashlib.sha256()
    def readable(self): return True
    def readinto(self,b):
        n=self.f.readinto(b)
        if n: self.h.update(memoryview(b)[:n])
        return n


@contextlib.contextmanager
def json_lines(p):
    """Stream raw bytes; digest is the exact compressed input, not its text."""
    with open(p,'rb') as f:
        hr=HashReader(f)
        with io.BufferedReader(hr,buffer_size=1024*1024) as buffered:
            name=str(p).lower()
            if name.endswith('.gz'): binary=gzip.GzipFile(fileobj=buffered,mode='rb')
            elif name.endswith(('.zst','.zstd')):
                import zstandard as zstd
                binary=zstd.ZstdDecompressor().stream_reader(buffered,read_across_frames=True,closefd=False)
            else: binary=buffered
            # Detach to leave the outer stream open long enough to drain/hash it.
            text=io.TextIOWrapper(binary,encoding='utf-8',errors='strict')
            try: yield text,hr
            finally:
                text.detach()
                if binary is not buffered: binary.close()
                while buffered.read(1024*1024): pass


def schema_record(p,kind):
    _,_,pq,_=deps()
    pf=pq.ParquetFile(p)
    fields=[{'name':f.name,'type':str(f.type)} for f in pf.schema_arrow]
    names=pf.schema_arrow.names
    candidate=[f['name'] for f in fields if CONDUCT.search(f['name']) or CONDUCT.search(f['type'])]
    return {'file_id':hashlib.sha256(str(p).encode()).hexdigest()[:24], 'path':str(p),'kind':kind,
            **signature(p),'rows':pf.metadata.num_rows,'fields':fields,'conduct_field_candidates':candidate,
            'game_id_field':next((x for x in KEY_ALIASES if x in names),None),
            'source_field':next((x for x in SOURCE_ALIASES if x in names),None)}


def discover(args,stagepaths,private):
    """Metadata-only walk of explicit local roots; no ZIP unpacking/cloud pulls."""
    roots=[args.project_root/'derived/replication/api_timeout_enrichment',args.project_root/'output']
    roots += [r.expanduser().resolve() for r in args.extra_scan_root]
    # Additional established normalization roots are schema/data candidates only.
    derived=args.project_root/'derived/replication'
    if derived.is_dir():
        roots += [p for p in derived.iterdir() if p.is_dir() and p not in roots
                  and re.search(r'api.*enrich|enrich.*api|stage0?4',p.name,re.I)
                  and '36m' not in p.name.lower()]
    seen=set(); files=[]; ignored=[]; schemas=[]; errors=[]; visited=0
    excluded=('chooser_leniency_t0_', 'c7r_fullpanel', 'rating_shock', 'rating_redesign')
    relevance=re.compile(r'api|enrich|lookup|stage0?4|responses|export',re.I)
    for root in roots:
        if not root.is_dir(): continue
        for here,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if not d.startswith('.') and not any(x in d.lower() for x in excluded)
                     and 'quarantine' not in d.lower() and not d.lower().endswith('_private')]
            for name in sorted(names):
                visited+=1
                if visited>args.max_inventory_files: raise RuntimeError('Inventory cap reached; increase --max-inventory-files explicitly')
                p=Path(here)/name
                if p.is_symlink() or not p.is_file() or any(x in name.lower() for x in ('.partial','.tmp','.lock')): continue
                st=p.stat(); inode=(st.st_dev,st.st_ino)
                if inode in seen: continue
                seen.add(inode)
                if not relevance.search(str(p)): continue
                pm=re.search(r'month=(\d{4}-\d{2})(?:/|$)',str(p))
                if pm and pm.group(1) not in MONTHS: continue
                # Legacy exports often encode the GAME month before '_lookup'.
                lm=re.search(r'(20\d{2}-\d{2})_lookup',str(p))
                if lm and lm.group(1) not in MONTHS: continue
                lower=name.lower()
                israw=lower.endswith(RAW_SUFFIXES)
                ispq=lower.endswith('.parquet')
                if not (israw or ispq): continue
                if time.time()-st.st_mtime<120:
                    ignored.append({'file_id':hashlib.sha256(str(p).encode()).hexdigest()[:24],'reason':'recently_modified_may_be_in_progress'})
                    continue
                if israw:
                    files.append({'path':str(p),'kind':'ndjson','file_id':hashlib.sha256(str(p).encode()).hexdigest()[:24],**signature(p)})
                else:
                    try:
                        s=schema_record(p,'api_parquet'); schemas.append(s)
                        if s['game_id_field'] and (s['source_field'] or s['conduct_field_candidates']): files.append(s)
                    except Exception as e:
                        errors.append({'path':str(p),'exception':type(e).__name__})
    for p in stagepaths:
        s=schema_record(p,'stage07'); schemas.append(s)
        if s['source_field'] or s['conduct_field_candidates']: files.append(s)
    files=sorted(files,key=lambda r:r['path'])
    atomic_json(private/'source_inventory_private.json',{'roots':[str(r) for r in roots], 'files':files,
        'schemas':schemas,'ignored':ignored,'errors':errors,'visited_files':visited,
        'scope':'explicit local API/output roots, committed NDJSON and Parquet only; archives/cloud mirrors not opened'})
    return files,schemas,ignored,errors


def extract_schema():
    _,pa,_,_=deps()
    return pa.schema([('game_id',pa.string()),('source',pa.string()),('created_at_ms',pa.int64()),
                      ('api_status',pa.string()),('conduct_candidate_json',pa.string())])


def init_scan(targets):
    global _GLOBAL_IDS
    _,pa,pq,_=deps(); pa.set_cpu_count(1); pa.set_io_thread_count(1)
    ids=set()
    for b in pq.ParquetFile(targets).iter_batches(columns=['game_id'],batch_size=65536,use_threads=False):
        ids.update(b.column(0).to_pylist())
    _GLOBAL_IDS=ids


def scan_file(job):
    _,pa,pq,_=deps()
    p=Path(job['path']); out=Path(job['output']); rec=out.with_suffix('.receipt.json')
    before=signature(p)
    if before!={k:job[k] for k in ('bytes','mtime_ns')}: raise RuntimeError('Input changed since discovery: '+job['file_id'])
    if rec.exists() and out.exists():
        r=load(rec)
        if r.get('input_signature')==before and r.get('target_sha256')==job['target_sha256'] and r.get('version')==VERSION:
            if digest(out)==r.get('output_sha256'): return r
            raise RuntimeError('Checkpoint output hash mismatch: '+job['file_id'])
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_name(out.name+'.partial.'+uuid.uuid4().hex)
    stats={'file_id':job['file_id'],'kind':job['kind'],'rows_read':0,'matched_rows':0,'malformed_lines':0,
           'probe_rows':0,'probe_conduct_fields':set(),'matched_conduct_fields':collections.Counter()}
    buf=[]; compressed_sha=None
    writer=pq.ParquetWriter(tmp,extract_schema(),compression='zstd')
    def accept(obj):
        stats['rows_read']+=1
        if not isinstance(obj,dict): return
        if stats['probe_rows']<64:
            stats['probe_conduct_fields'].update(conduct_paths(obj)); stats['probe_rows']+=1
        gid=obj.get('game_id') or obj.get('id')
        if not isinstance(gid,str) or gid not in _GLOBAL_IDS: return
        r=normalize(obj)
        if r is None: return
        stats['matched_rows']+=1
        if r['conduct_candidate_json']:
            stats['matched_conduct_fields'].update(json.loads(r['conduct_candidate_json']).keys())
        buf.append(r)
        if len(buf)>=8192:
            writer.write_table(pa.Table.from_pylist(buf,schema=extract_schema())); buf.clear()
    try:
        if job['kind']=='ndjson':
            with json_lines(p) as (f,hr):
                for line in f:
                    if not line.strip(): continue
                    try: obj=json.loads(line)
                    except (ValueError,TypeError): stats['malformed_lines']+=1; continue
                    if isinstance(obj,list):
                        for row in obj: accept(row)
                    else: accept(obj)
            compressed_sha=hr.h.hexdigest()
        else:
            pf=pq.ParquetFile(p); names=pf.schema_arrow.names
            wanted=set(KEY_ALIASES+SOURCE_ALIASES+CREATED_ALIASES+STATUS_ALIASES)
            cols=[x for x in names if x in wanted or CONDUCT.search(x)]
            # Include nested structs only when their field schema contains candidates.
            cols += [f.name for f in pf.schema_arrow if pa.types.is_struct(f.type) and CONDUCT.search(str(f.type)) and f.name not in cols]
            for b in pf.iter_batches(columns=cols,batch_size=65536,use_threads=False):
                # Filter by ID in Python but avoid materializing other rows as dicts.
                key=next(k for k in KEY_ALIASES if k in b.schema.names)
                ids=b.column(b.schema.get_field_index(key)).to_pylist()
                keep=[i for i,g in enumerate(ids) if isinstance(g,str) and g in _GLOBAL_IDS]
                stats['rows_read']+=len(ids)-len(keep)
                if keep:
                    small=pa.Table.from_batches([b]).take(pa.array(keep,type=pa.int64()))
                    for row in small.to_pylist(): accept(row)
        if buf: writer.write_table(pa.Table.from_pylist(buf,schema=extract_schema()))
        writer.close()
        if signature(p)!=before: raise RuntimeError('Input changed while reading: '+job['file_id'])
        os.replace(tmp,out)
    except BaseException:
        writer.close()
        raise
    stats['probe_conduct_fields']=sorted(stats['probe_conduct_fields'])
    stats['matched_conduct_fields']=dict(stats['matched_conduct_fields'])
    stats.update({'version':VERSION,'input_signature':before,'input_sha256':compressed_sha,
                  'input_full_sha256_computed':compressed_sha is not None,
                  'target_sha256':job['target_sha256'],'output_sha256':digest(out),'output_rows':stats['matched_rows']})
    atomic_json(rec,stats)
    return stats


def run_scans(args,jobs,private):
    target=private/'targets_private.parquet'; tsha=digest(target)
    for j in jobs: j.update(output=str(private/'source_parts'/f"{j['file_id']}.parquet"),target_sha256=tsha)
    results=[]; errors=[]
    if not jobs: return results,errors
    n=deps()[2].ParquetFile(target).metadata.num_rows
    est=128*1024**2+n*125
    workers=max(1,min(args.workers,int(max(1,(args.memory_gb-1)*1024**3//est))))
    total=sum(j['bytes'] for j in jobs); donebytes=0; start=time.monotonic()
    log(f'SOURCE_RECOVERY_BEGIN files={len(jobs)} compressed_GiB={total/1024**3:.2f} workers={workers}')
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),initializer=init_scan,initargs=(str(target),)) as ex:
        pending={ex.submit(scan_file,j):j for j in jobs}
        remaining=set(pending)
        while remaining:
            done,remaining=cf.wait(remaining,timeout=30,return_when=cf.FIRST_COMPLETED)
            if not done:
                log(f'SOURCE_RECOVERY_HEARTBEAT completed={len(results)+len(errors)}/{len(jobs)} elapsed_min={(time.monotonic()-start)/60:.1f}')
            for f in done:
                j=pending[f]; donebytes+=j['bytes']
                try: results.append(f.result())
                except Exception as e:
                    errors.append({'file_id':j['file_id'],'path':j['path'],'exception':type(e).__name__,'message':str(e)})
                k=len(results)+len(errors)
                if k%20==0 or k==len(jobs):
                    elapsed=time.monotonic()-start; eta=elapsed*(total-donebytes)/max(donebytes,1)
                    log(f'SOURCE_RECOVERY_PROGRESS files={k}/{len(jobs)} matches={sum(r["matched_rows"] for r in results):,} ETA_min={eta/60:.1f} errors={len(errors)}')
    atomic_json(private/'source_scan_results_private.json',{'results':results,'errors':errors})
    return results,errors


def reduce_sources(target,jobs,results,private):
    np,pa,pq,_=deps()
    t=pq.ParquetFile(target).read(use_threads=False); n=len(t)
    ids=np.asarray(t['game_id'].to_pylist(),dtype='U8'); order=np.argsort(ids); sid=ids[order]
    bits=np.zeros(n,np.uint32); counts=np.zeros(n,np.int64); lo=np.full(n,np.iinfo(np.int64).max,np.int64)
    hi=np.zeros(n,np.int64); status=np.zeros(n,np.uint8); conduct=np.zeros(n,np.bool_)
    valid={r['file_id'] for r in results}
    for job in jobs:
        if job['file_id'] not in valid: continue
        for b in pq.ParquetFile(job['output']).iter_batches(batch_size=65536,use_threads=False):
            d=b.to_pydict(); gids=np.asarray(d['game_id'],dtype='U8'); pos=np.searchsorted(sid,gids)
            if np.any(pos>=len(sid)) or not np.array_equal(sid[pos],gids): raise RuntimeError('Non-target evidence in recovered sources')
            ix=order[pos]
            m=np.asarray([SOURCE_BITS.get(s,UNKNOWN_BIT if s else 0) for s in d['source']],np.uint32)
            np.bitwise_or.at(bits,ix,m); np.add.at(counts,ix,1)
            start=np.asarray([x or 0 for x in d['created_at_ms']],np.int64); ok=start>0
            np.minimum.at(lo,ix[ok],start[ok]); np.maximum.at(hi,ix[ok],start[ok])
            ss=np.asarray([0 if s is None else 1 if s=='timeout' else 2 for s in d['api_status']],np.uint8)
            np.bitwise_or.at(status,ix,ss)
            np.logical_or.at(conduct,ix,np.asarray([bool(c) for c in d['conduct_candidate_json']],bool))
    inverse={v:k for k,v in SOURCE_BITS.items()}
    labels=np.asarray([inverse.get(int(x),'MISSING' if x==0 else 'UNRECOGNIZED' if x==UNKNOWN_BIT else 'CONFLICT') for x in bits],dtype='U16')
    conflicting_time=(hi>0)&(lo!=hi)
    lo[hi==0]=0
    columns={'api_source_recovered':pa.array(labels), 'api_source_evidence_count':pa.array(counts),
             'api_created_at_ms':pa.array([int(x) if x else None for x in hi],type=pa.int64()),
             'api_created_at_conflict':pa.array(conflicting_time),'api_status_not_timeout_evidence':pa.array((status&2)>0),
             'conduct_field_candidate_present':pa.array(conduct)}
    for name,value in columns.items(): t=t.append_column(name,value)
    pa_write(private/'cohort_with_source_private.parquet',t)
    return t,{'matched_unique_exposures':int((counts>0).sum()),'known_source_exposures':int(np.isin(labels,SOURCES).sum()),
              'missing_source_exposures':int((labels=='MISSING').sum()),'conflicting_source_exposures':int((labels=='CONFLICT').sum()),
              'unrecognized_source_exposures':int((labels=='UNRECOGNIZED').sum()),'created_at_conflicts':int(conflicting_time.sum()),
              'non_timeout_status_evidence':int(((status&2)>0).sum()),'exposures_with_candidate_conduct_fields':int(conduct.sum())}


def count_before(hj,hi,ht,qj,qi,qt,pair=False):
    """Strict timestamp predecessor counts, including ties and empty histories.

Uses observed anchors, NOT authenticated terminal decision times. Pair=True
counts every prior chooser decision involving the same recipient for subtraction.
"""
    import numpy as np
    if len(hj)==0: return np.zeros(len(qj),np.int64)
    if pair:
        order=np.lexsort((ht,hi,hj)); dtype=[('j','<i8'),('i','<i8'),('t','<i8')]
    else:
        order=np.lexsort((ht,hj)); dtype=[('j','<i8'),('t','<i8')]
    keys=np.empty(len(hj),dtype=dtype); keys['j']=hj[order]; keys['t']=ht[order]
    queries=np.empty(len(qj),dtype=dtype); queries['j']=qj; queries['t']=qt
    if pair: keys['i']=hi[order]; queries['i']=qi
    change=np.empty(len(hj),bool); change[0]=True
    change[1:]=keys['j'][1:]!=keys['j'][:-1]
    if pair: change[1:] |= keys['i'][1:]!=keys['i'][:-1]
    groupstart=np.maximum.accumulate(np.where(change,np.arange(len(hj)),0))
    idx=np.searchsorted(keys,queries,side='left')-1
    safe=np.maximum(idx,0); ok=(idx>=0)&(keys['j'][safe]==qj)
    if pair: ok &= keys['i'][safe]==qi
    return np.where(ok,safe-groupstart[safe]+1,0).astype(np.int64)


def history_month(job):
    np,pa,pq,_=deps(); pa.set_cpu_count(1); pa.set_io_thread_count(1)
    p=Path(job['path']); root=Path(job['output']); root.mkdir(parents=True,exist_ok=True)
    receipt=root/'receipt.json'
    if receipt.exists():
        r=load(receipt)
        if r.get('input_signature')==signature(p) and r.get('shards')==job['shards'] and r.get('version')==VERSION:
            if all((root/x['name']).is_file() and digest(root/x['name'])==x['sha256'] for x in r['files']): return r
            raise RuntimeError('History checkpoint content mismatch')
    writers={}; temps={}; paths={}; counts=collections.Counter(); before=signature(p)
    schema=pa.schema([('j',pa.int64()),('i',pa.int64()),('anchor',pa.int64())])
    try:
        for b in pq.ParquetFile(p).iter_batches(columns=list(HISTORY_COLUMNS),batch_size=131072,use_threads=False):
            t=pa.Table.from_batches([b]); valid=array(t,'kind_draw',bool)|array(t,'timeout_chooser_win',bool)
            j=array(t,'chooser_user_id',np.int64)[valid]; i=array(t,'disconnected_user_id',np.int64)[valid]
            tm=array(t,'api_last_move_at_ms',np.int64)[valid]
            if np.any(j==i): raise RuntimeError('Self-player row in choice history')
            for shard in range(job['shards']):
                take=(j%job['shards'])==shard
                if not take.any(): continue
                if shard not in writers:
                    final=root/f'shard-{shard:02d}.parquet'; temp=final.with_name(final.name+'.partial.'+uuid.uuid4().hex)
                    paths[shard]=final; temps[shard]=temp; writers[shard]=pq.ParquetWriter(temp,schema,compression='zstd')
                writers[shard].write_table(pa.table({'j':j[take],'i':i[take],'anchor':tm[take]},schema=schema))
                counts[shard]+=int(take.sum())
        for w in writers.values(): w.close()
        if signature(p)!=before: raise RuntimeError('Stage 07 input changed during history scan')
        files=[]
        for s,tmp in temps.items():
            os.replace(tmp,paths[s]); files.append({'name':paths[s].name,'shard':s,'rows':counts[s],'sha256':digest(paths[s])})
        r={'version':VERSION,'input_signature':before,'shards':job['shards'],'files':files}
        atomic_json(receipt,r); return r
    except BaseException:
        for w in writers.values():
            with contextlib.suppress(Exception): w.close()
        raise


def history_shard(job):
    np,pa,pq,_=deps(); pa.set_cpu_count(1); pa.set_io_thread_count(1)
    parts=[pq.ParquetFile(p).read(use_threads=False) for p in job['parts']]
    if parts:
        h=pa.concat_tables(parts); del parts
        hj=array(h,'j',np.int64); hi=array(h,'i',np.int64); ht=array(h,'anchor',np.int64)
    else: hj=hi=ht=np.array([],np.int64)
    q=pq.ParquetFile(job['targets']).read(use_threads=False)
    j=array(q,'chooser_id',np.int64); keep=(j%job['shards'])==job['shard']; q=q.filter(pa.array(keep)); del j,keep
    qj=array(q,'chooser_id',np.int64); qi=array(q,'recipient_id',np.int64); qt=array(q,'archive_start_ms',np.int64)
    columns={'target_index':q['target_index']}
    for days in (0,7,30):
        before=qt-days*DAY
        n=count_before(hj,hi,ht,qj,qi,before)-count_before(hj,hi,ht,qj,qi,before,pair=True)
        if np.any(n<0): raise RuntimeError('Negative pair-excluded support')
        columns[f'anchor_prior_n_lag{days}d']=pa.array(n)
    pa_write(job['output'],pa.table(columns))
    return {'rows':len(q),'sha256':digest(job['output']),'output':job['output']}


def run_history(args,paths,private):
    np,pa,pq,_=deps(); root=private/'history_support'; root.mkdir(exist_ok=True)
    manifest=root/'_COMPLETE.json'
    target=private/'targets_private.parquet'; thash=digest(target)
    if manifest.exists():
        r=load(manifest)
        if r.get('target_sha256')==thash and r.get('version')==VERSION:
            if all(Path(f['output']).is_file() and digest(f['output'])==f['sha256'] for f in r['files']): return r
            raise RuntimeError('Final history support hash mismatch')
    jobs=[{'path':str(p),'output':str(root/p.parent.name),'shards':args.shards} for p in paths]
    log('ANCHOR_HISTORY_SUPPORT_BEGIN: no instrument; no terminal-time claim')
    with cf.ProcessPoolExecutor(max_workers=min(args.workers,4),mp_context=mp.get_context('spawn')) as ex:
        for idx,r in enumerate(ex.map(history_month,jobs),1): log(f'HISTORY_PROJECTION_MONTHS {idx}/{len(jobs)}')
    sjobs=[]
    for s in range(args.shards):
        parts=[str(Path(j['output'])/f'shard-{s:02d}.parquet') for j in jobs if (Path(j['output'])/f'shard-{s:02d}.parquet').is_file()]
        rows=sum(pq.ParquetFile(p).metadata.num_rows for p in parts)
        sjobs.append({'shard':s,'shards':args.shards,'parts':parts,'rows':rows,'targets':str(target),'output':str(root/f'support-{s:02d}.parquet')})
    # Conservative estimated peak; a planning cap, not an OS RSS limit.
    estimate=max(j['rows'] for j in sjobs)*220+384*1024**2
    workers=max(1,min(args.workers,args.shards,int(max(1,(args.memory_gb-1)*1024**3//estimate))))
    log(f'HISTORY_COUNT_WORKERS {workers} conservative_estimated_GiB_per_worker={estimate/1024**3:.2f}')
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex: files=list(ex.map(history_shard,sjobs))
    r={'version':VERSION,'target_sha256':thash,'files':files,
       'timestamp_basis':'api_last_move_at_ms history anchor strictly before focal archive game start minus lag',
       'terminal_decision_timing_verified':False,'pair_leaveout':'all observed earlier chooser-recipient interactions excluded',
       'history_window':'2023-11 through 2025-10 only; left truncation retained', 'scores_estimated':False}
    atomic_json(manifest,r); log('ANCHOR_HISTORY_SUPPORT_COMPLETE'); return r


def publish(args,private,public,table,cohort_summary,recovery,schemas,ignored,scanerrors,receipts,history):
    np,pa,pq,_=deps()
    n=len(table); source=np.asarray(table['api_source_recovered'].to_pylist(),dtype='U16')
    frozen=array(table,'frozen_a1_support',bool); treated=array(table,'received',bool)
    month=array(table,'month_code',np.int64); speed=array(table,'speed_code',np.int64)
    status_bad=array(table,'api_status_not_timeout_evidence',bool); time_bad=array(table,'api_created_at_conflict',bool)
    masks={'all_first_pair_arm_complete90':np.ones(n,bool),'frozen_A1_complete90':frozen,
           'frozen_A1_pool_unambiguous':frozen&(source=='pool')&~status_bad&~time_bad}
    rows=[]
    for population,mask in masks.items():
        keys=collections.Counter(zip(month[mask].tolist(),speed[mask].tolist(),treated[mask].tolist(),source[mask].tolist()))
        for (m,s,d,z),cnt in sorted(keys.items()):
            rows.append({'population':population,'month':MONTHS[m] if 0<=m<24 else 'INVALID','speed_code':s,
                         'receipt_arm':int(d),'source':z,'exposures':cnt})
    csv_write(public/'T0_source_coverage.csv',rows)
    histrows=[]
    if history:
        history_n={days:np.full(n,-1,np.int64) for days in (0,7,30)}
        seen=np.zeros(n,bool)
        for f in history['files']:
            t=pq.ParquetFile(f['output']).read(use_threads=False); idx=array(t,'target_index',np.int64)
            if np.any(seen[idx]) or len(np.unique(idx))!=len(idx): raise RuntimeError('Duplicate history output target')
            seen[idx]=True
            for days in history_n: history_n[days][idx]=array(t,f'anchor_prior_n_lag{days}d',np.int64)
        if not seen.all(): raise RuntimeError('History support missing targets')
        for pop,mask in masks.items():
            denom=int(mask.sum())
            for days,v in history_n.items():
                for floor in (1,5,10,25):
                    kept=mask&(v>=floor)
                    histrows.append({'population':pop,'washout_days':days,'minimum_anchor_history_count':floor,
                     'denominator':denom,'exposures_retained':int(kept.sum()),'retained_receipts':int((kept&treated).sum()),
                     'share_retained':float(kept.sum()/denom) if denom else None,'terminal_decision_timing_verified':False})
        csv_write(public/'T0_anchor_history_support.csv',histrows)
    csv_write(public/'T0_scan_summary.csv',[{k:r.get(k) for k in ('file_id','kind','rows_read','matched_rows','malformed_lines','input_sha256')} for r in receipts],['file_id','kind','rows_read','matched_rows','malformed_lines','input_sha256'])
    fields=collections.Counter()
    for s in schemas:
        for name in s['conduct_field_candidates']: fields[(s['kind'],name)]+=1
    for r in receipts:
        for name in r['probe_conduct_fields']: fields[('raw_or_matched_key_probe',name)]+=1
    csv_write(public/'T0_conduct_field_candidates.csv',[
       {'evidence_scope':k[0],'field_path':k[1],'files_with_field':v,'historical_timing_validated':False,'used_as_behavior_category':False}
       for k,v in sorted(fields.items())],['evidence_scope','field_path','files_with_field','historical_timing_validated','used_as_behavior_category'])
    families=collections.Counter((s['kind'],json.dumps(s['fields'],sort_keys=True)) for s in schemas)
    atomic_json(public/'schema_families.json',[{'kind':k[0],'files':v,'fields':json.loads(k[1])} for k,v in sorted(families.items())])
    missing=int(recovery['missing_source_exposures']); conflict=int(recovery['conflicting_source_exposures'])
    malformed=sum(r['malformed_lines'] for r in receipts)
    gaps=[]
    if missing: gaps.append('SOME_EXPOSURE_SOURCES_NOT_RECOVERED')
    if conflict or recovery['unrecognized_source_exposures']: gaps.append('SOURCE_CONFLICT_OR_UNRECOGNIZED_VALUES')
    if recovery['created_at_conflicts'] or recovery['non_timeout_status_evidence']: gaps.append('API_EVIDENCE_DISAGREEMENT')
    if scanerrors or malformed or ignored: gaps.append('DISCOVERY_OR_READ_COVERAGE_INCOMPLETE')
    gaps.extend(['HISTORICAL_MATCHMAKER_BEHAVIOR_CATEGORY_NOT_AUTHENTICATED',
                 'QUEUE_RISK_SETS_NOT_OBSERVED','TERMINAL_DECISION_TIMING_NOT_AUTHENTICATED',
                 'OTHER_OPPONENT_OUTCOME_RULE_REQUIRES_SEPARATE_AUTHENTICATION'])
    summary={'status':'CHOOSER_LENIENCY_T0_COMPLETE_WITH_GAPS','version':VERSION,'run_id':args.run_id,
       'cohort':cohort_summary,'source_recovery':recovery,'pool_frozen_A1_exposures':int(masks['frozen_A1_pool_unambiguous'].sum()),
       'pool_frozen_A1_receipts':int((masks['frozen_A1_pool_unambiguous']&treated).sum()),
       'source_files_scanned':len(receipts),'source_file_errors':len(scanerrors),'recent_files_skipped':len(ignored),
       'malformed_lines':malformed,'conduct_candidate_fields_found':len(fields),'gaps':gaps,
       'historical_conduct_category_inferred':False,'IV_or_first_stage_estimated':False,'causal_identification_certified':False,
       'raw_API_network_requests':0,'certified_inputs_modified':False,'anchor_history_support_run':history is not None,
       'source_scope':'explicit local API/output roots; no ZIP extraction or cloud mirrors; unmatched/unknown are never called pool',
       'pinned_input_sha256':EXPECTED,'runtime':{'python':sys.version.split()[0],'platform':platform.system(),
        'numpy':np.__version__,'pyarrow':pa.__version__,'zstandard':deps()[3].__version__,
        'max_workers':args.workers,'history_shards':args.shards,'planning_memory_GiB':args.memory_gb}}
    atomic_json(public/'summary.json',summary)
    report=f'''# Chooser-leniency T0: local feasibility and source recovery\n\nStatus: {summary['status']}\n\n## Cohort and coverage\n\nAuthenticated frozen A1 complete-follow-up cohort: 2,185,073 (65,085 receipts).\nA broader first-pair, arm-eligible, complete-follow-up population is retained separately; no ATT weights are applied.\n\nKnown sources in the broader population: {recovery['known_source_exposures']:,} / {n:,}.\nUnambiguous pool exposures in frozen A1: {summary['pool_frozen_A1_exposures']:,}; receipts: {summary['pool_frozen_A1_receipts']:,}.\nMissing sources: {missing:,}; source conflicts: {conflict:,}.\nFiles scanned: {len(receipts):,}; file errors: {len(scanerrors)}; malformed lines: {malformed}.\n\n## Interpretation\n\n`pool` is recorded game-source evidence, not a claim that both players clicked the same interface. Source filtering does not establish random assignment.\nHistorical rageSit/trust/queue fields are *candidates* until a producer, unit, role, and pregame timestamp are authenticated. A missing counter is not zero and is not an ordinary-conduct category. No behavioral category is inferred from grant rates or disconnection proxies.\n\nHistory support uses last-move/API anchors strictly before focal archive game start, subtracting every earlier observed decision involving the focal recipient. Counts at 0/7/30-day washouts are feasibility diagnostics, not confirmed completed-decision histories or a constructed IV. The history window is left-truncated at November 2023.\n\nT0 does not estimate OLS/IV, certify exclusion or monotonicity, recreate exact queue risk sets, or certify the different-opponent outcome definition. It does not rebuild or rerun the existing A1 estimate.\n\n## Files\n\n`T0_source_coverage.csv`: source by population, month, speed code, and receipt arm.\n`T0_conduct_field_candidates.csv`: field names only; historical meaning unvalidated.\n`T0_anchor_history_support.csv`: optional count-floor feasibility, explicitly anchor-based.\n`schema_families.json`: inspected field schemas without input paths or row-level data.\n\nOnly this report directory is packaged for upload. Row-level recoveries, candidate field values, absolute paths, logs, and intermediate histories remain private on XT_Pro.\n\n## Remaining gates\n\n'''+''.join(f'- {g}\n' for g in gaps)
    (public/'REPORT.md').write_text(report)
    return summary


def package_report(public,desktop,run_id):
    allow={'summary.json','REPORT.md','T0_source_coverage.csv','T0_conduct_field_candidates.csv',
           'T0_anchor_history_support.csv','schema_families.json','failure_summary.json','T0_scan_summary.csv'}
    files=[p for p in sorted(public.iterdir()) if p.is_file() and p.name in allow]
    rows=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in files]
    csv_write(public/'REPORT_MANIFEST.csv',rows,['file','bytes','sha256'])
    files.append(public/'REPORT_MANIFEST.csv')
    archive=desktop/f'CHOOSER_LENIENCY_T0_REPORT_{run_id}.zip'
    if archive.exists():
        # Never overwrite a previous transfer artifact, including on resume.
        archive=desktop/f'CHOOSER_LENIENCY_T0_REPORT_{run_id}_{uuid.uuid4().hex[:8]}.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,arcname='CHOOSER_LENIENCY_T0_REPORT/'+p.name)
    sha=digest(archive)
    archive.with_suffix('.zip.sha256').write_text(sha+'  '+archive.name+'\n')
    log('UPLOAD_REPORT_ZIP '+str(archive)); log('UPLOAD_REPORT_SHA256 '+sha)
    return archive


def execute(args):
    root=args.project_root.expanduser().resolve(); args.project_root=root
    if not root.is_dir(): raise RuntimeError('Project volume is not mounted: '+str(root))
    if args.workers<1 or args.workers>10 or args.shards<2 or args.memory_gb<2:
        raise RuntimeError('Use 1-10 workers, at least 2 shards and at least 2 GiB planning memory')
    args.desktop_root=args.desktop_root.expanduser().resolve(); args.desktop_root.mkdir(parents=True,exist_ok=True)
    private=root/'derived/replication/chooser_leniency_t0_v100_PRIVATE'/args.run_id
    public=root/'output/chooser_leniency_t0_v100'/args.run_id
    private.mkdir(parents=True,exist_ok=True); public.mkdir(parents=True,exist_ok=True)
    lock=open(private/'RUN.lock','a+')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This T0 run is already active')
    config={'version':VERSION,'script_sha256':digest(Path(__file__)),'shards':args.shards,
       'history':not args.skip_history,'extra_scan_root':[str(x.expanduser().resolve()) for x in args.extra_scan_root]}
    cp=private/'config.json'
    if cp.exists() and load(cp)!=config: raise RuntimeError('Resume configuration/script changed; use a new run ID')
    atomic_json(cp,config)
    stage='authentication'
    try:
        free=shutil.disk_usage(root).free
        log(f'PREFLIGHT disk_free_GiB={free/1024**3:.1f}; workers={args.workers}; planning_memory_GiB={args.memory_gb}')
        if free<12*1024**3: raise RuntimeError('At least 12 GiB free disk is required for this audit')
        rec,paths=authenticate(args,private)
        stage='cohort'; cs=build_targets(rec,private)
        stage='discovery'; jobs,schemas,ignored,discovery_errors=discover(args,paths,private)
        stage='source_recovery'; receipts,scan_errors=run_scans(args,jobs,private)
        stage='source_reduction'; table,recovery=reduce_sources(private/'targets_private.parquet',jobs,receipts,private)
        stage='history_support'; history=None if args.skip_history else run_history(args,paths,private)
        stage='report'; summary=publish(args,private,public,table,cs,recovery,schemas,ignored,discovery_errors+scan_errors,receipts,history)
        archive=package_report(public,args.desktop_root,args.run_id)
        atomic_json(private/'_AUDIT_COMPLETE.json',{'status':summary['status'],'report_zip':str(archive),
            'report_zip_sha256':digest(archive),'NOT_A_CAUSAL_CERTIFICATE':True})
        log(summary['status']); log('PRIVATE_OUTPUT '+str(private))
        log('Resume ID: '+args.run_id)
        return 0
    except BaseException as e:
        (private/'exception_PRIVATE.txt').write_text(traceback.format_exc())
        atomic_json(public/'failure_summary.json',{'status':'CHOOSER_LENIENCY_T0_BLOCKED','stage':stage,
           'exception_type':type(e).__name__,'details_saved_privately':True,'causal_identification_certified':False})
        # Drop stale successful-report files from the allowlist on failure by packaging
        # only a separate failure directory; do not remove any old artifacts.
        failure=public/('failure_'+uuid.uuid4().hex[:8]); failure.mkdir()
        shutil.copy2(public/'failure_summary.json',failure/'failure_summary.json')
        (failure/'REPORT.md').write_text('# T0 blocked\n\nStage: '+stage+'\n\n'+type(e).__name__+
              '. Detailed diagnostic is retained privately. No scientific result is certified.\n')
        package_report(failure,args.desktop_root,args.run_id)
        log('BLOCKED '+str(e)); log('PRIVATE_DIAGNOSTIC '+str(private/'exception_PRIVATE.txt'))
        return 2
    finally: lock.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10); p.add_argument('--shards',type=int,default=8)
    p.add_argument('--memory-gb',type=float,default=8)
    p.add_argument('--run-id',default=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(os.getpid()))
    p.add_argument('--extra-scan-root',type=Path,action='append',default=[])
    p.add_argument('--max-inventory-files',type=int,default=300000)
    p.add_argument('--skip-history',action='store_true')
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    if re.fullmatch(r'[A-Za-z0-9_-]+',args.run_id) is None: p.error('Unsafe run ID')
    if not args.execute: p.error('Pass --execute; no production work occurs without it')
    os.umask(0o077)
    return execute(args)

if __name__=='__main__': sys.exit(main())
