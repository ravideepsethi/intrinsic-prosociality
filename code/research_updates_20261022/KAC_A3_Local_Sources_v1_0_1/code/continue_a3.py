#!/usr/bin/env python3
"""Reuse the completed A3 audit; inspect local schemas and within-cell support."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import readiness_v100 as old

ROOT = Path(__file__).resolve().parents[1]
OLD_PACKAGE = '436705593c2454cb9bf8047e5a4feaabb472720cf0b34f8cdb9345ff0b3ce4a0'
OLD_BUILD = 'e50a02d4be50c9299360d6960fd83dd73d74a208416b455baebe2d6b053befab'
EXCLUDED_DIRS = {'.git','venv','node_modules','__pycache__','work','tmp','temp'}
PREFIX_BYTES = 256*1024
REVIEWED_ROWS = 1892834


def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,name=line.split('  ',1);p=(ROOT/name).resolve()
        old.require(p.is_relative_to(ROOT) and old.sha(p)==h,'Package checksum mismatch: '+name)
    return old.sha(ROOT/'PACKAGE_MANIFEST.sha256')


def find_cached_inputs(project):
    base=project/'derived/replication/kac_a3_readiness_v100_PRIVATE'
    matches=[]
    for f in sorted(base.glob('*/INPUTS.json')):
        data=json.loads(f.read_text())
        if data.get('arena_build_sha256')!=OLD_BUILD or data.get('arena_contract')!=old.EXPECTED_CONTRACT:
            continue
        records=data.get('records',[])
        expected=old.digest({'package':OLD_PACKAGE,'inputs':records,'policy':old.POLICY})
        if data.get('contract')!=expected or data.get('author_policy')!=old.POLICY:
            continue
        old.require(sorted(x['month'] for x in records)==old.MONTHS,'Cached month coverage differs')
        matches.append((f.parent,data))
    old.require(len(matches)==1,'Expected one authenticated completed A3 cache; do not rerun or delete old caches')
    return matches[0]


def verify_projection(task):
    folder,record,contract=task
    folder=Path(folder);r=json.loads((folder/'DONE.json').read_text())
    expected=old.digest({'record':record,'contract':contract})
    p=folder/'target_keys_PRIVATE.parquet'
    before=old.signature(p)
    old.require(r.get('key')==expected,'Projection input contract differs')
    old.require(r['summary']['input_sha256']==record['sha256'],'Projection source hash differs')
    old.require(old.sha(p)==r['projection_sha256'],'Completed projection changed: '+record['month'])
    old.require(old.signature(p)==before,'Projection changed during authentication')
    return p,r['summary'],{'path':str(p),'signature':before,'sha256':r['projection_sha256']}


def state_support(paths, report, private, threads):
    c=duckdb.connect(':memory:')
    c.execute(f'SET threads={threads}');c.execute("SET memory_limit='4GB'");c.execute("SET TimeZone='UTC'")
    try:
        c.execute('CREATE VIEW t AS SELECT * FROM '+old.scan(paths))
        n,u,missing=c.execute('SELECT count(*),count(DISTINCT game_id),count(*) FILTER(WHERE tournament_id IS NULL OR chooser IS NULL) FROM t').fetchone()
        old.require(n==u and missing==0,'Cached game or tournament keys failed validation')
        specifications=[('all','TRUE'),('competitive_all_stages','eval_cp>=-100'),
          ('competitive_after_ply10','eval_cp>=-100 AND ply>10'),('losing_all_stages','eval_cp<=-300'),
          ('losing_after_ply10','eval_cp<=-300 AND ply>10'),
          ('competitive_or_losing_after_ply10','(eval_cp>=-100 OR eval_cp<=-300) AND ply>10')]
        result=[]
        for name,where in specifications:
            r=old.rows(c,f'''WITH cells AS (SELECT chooser,tournament_id,count(*) AS n FROM t WHERE {where} GROUP BY 1,2)
              SELECT count(*) AS cells,coalesce(sum(n),0) AS opportunities,
              count(*) FILTER(WHERE n>=2) AS repeat_cells,
              coalesce(sum(n) FILTER(WHERE n>=2),0) AS opportunities_in_repeat_cells,
              coalesce(sum(n-1),0) AS within_cell_dimensions_before_controls,
              count(*) FILTER(WHERE n>=3) AS cells_with_at_least_three FROM cells''')[0]
            result.append({'sample':name,**r})
        table=pa.Table.from_pylist(result);c.register('support_table',table)
        old.export_table(c,'SELECT * FROM support_table',report/'support_by_state')
        c.execute(f'''COPY (WITH cells AS (SELECT chooser,tournament_id,count(*) AS n FROM t
          WHERE eval_cp>=-100 AND ply>10 GROUP BY 1,2)
          SELECT tournament_id,count(*) AS repeat_chooser_cells,sum(n) AS opportunities
          FROM cells WHERE n>=2 GROUP BY 1 ORDER BY 1)
          TO {old.q(private/'late_competitive_repeat_tournaments_PRIVATE.parquet')}
          (FORMAT PARQUET, COMPRESSION ZSTD)''')
        old.export_table(c,'''SELECT speed,count(*) AS opportunities,
          count(DISTINCT tournament_id) AS tournaments FROM t WHERE eval_cp>=-100 AND ply>10
          GROUP BY 1 ORDER BY 1''',report/'late_competitive_by_speed')
        return result
    finally:c.close()


def family_key(relative):
    s=str(relative)
    s=re.sub(r'20\d{6}T\d+(?:Z)?','<run_date>',s)
    s=re.sub(r'(?<![A-Za-z0-9])[0-9a-f]{16,}(?![A-Za-z0-9])','<hash>',s,flags=re.I)
    # Preserve YYYY-MM month partitions; collapse file shards and hashed buckets.
    s=re.sub(r'((?:bucket|part|unit|batch|shard|chunk|worker)[=_-]?)\d+',r'\1*',s,flags=re.I)
    return s


def asset_kind(path):
    n=path.name.lower()
    if n.endswith('.parquet'):return 'parquet'
    if any(n.endswith(x) for x in ('.pgn','.pgn.zst','.pgn.gz','.pgn.bz2')):return 'pgn'
    if any(n.endswith(x) for x in ('.ndjson','.jsonl','.ndjson.gz','.jsonl.gz','.ndjson.zst','.jsonl.zst')):return 'json_records'
    if any(n.endswith(x) for x in ('.json','.json.gz','.json.zst')) and re.search(r'api|game|arena|tournament|berserk|score.?sheet',str(path),re.I):return 'json'
    return None


def enumerate_assets(project, additional_roots=()):
    """Enumerate each requested subtree fully; no shared file limit or row scan."""
    # Compare canonical paths on both sides. On macOS a temporary project may
    # arrive as /var/... while resolving its scan roots produces /private/var/....
    project=Path(project).expanduser().resolve()
    bases=[project/'derived',project/'output',project/'raw',*additional_roots]
    # Remove nested or duplicate roots, preserving first occurrence.
    roots=[]
    for b in bases:
        b=Path(b).expanduser().resolve()
        if any(b==x or b.is_relative_to(x) for x in roots):continue
        roots=[x for x in roots if not x.is_relative_to(b)];roots.append(b)
    groups={};scopes=[];last_log=time.monotonic()
    for base in roots:
        scope={'root':str(base),'present':base.is_dir(),'directories':0,'candidate_files':0,'walk_errors':[]}
        def walk_error(e):scope['walk_errors'].append({'path':str(e.filename),'error':type(e).__name__})
        if base.is_dir():
            for here,dirs,files in os.walk(base,onerror=walk_error,followlinks=False):
                dirs[:]=sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith('.')
                    and not d.startswith('kac_a3_') and '.pending' not in d)
                scope['directories']+=1
                for name in sorted(files):
                    p=Path(here)/name
                    kind=asset_kind(p)
                    if not kind or p.is_symlink():continue
                    try:s=p.stat()
                    except OSError as e:walk_error(e);continue
                    rel=str(p.relative_to(project)) if p.is_relative_to(project) else str(p)
                    k=(family_key(rel),kind)
                    # Each family stores only three deterministic representatives.
                    rank=int.from_bytes(hashlib.sha256(str(p).encode()).digest()[:8],'big')
                    item=groups.setdefault(k,{'family':k[0],'kind':kind,'files':0,'bytes':0,'representatives':[]})
                    item['files']+=1;item['bytes']+=s.st_size
                    item['representatives'].append((rank,str(p),[s.st_size,s.st_mtime_ns,s.st_ino]))
                    item['representatives'].sort();item['representatives']=item['representatives'][:3]
                    scope['candidate_files']+=1
                if time.monotonic()-last_log>20:
                    old.log(f'Local inventory: {scope["directories"]:,} directories in {base.name}; no game rows scanned')
                    last_log=time.monotonic()
        scopes.append(scope)
        old.log(f'{base.name}: enumerated {scope["candidate_files"]:,} candidate files')
    return list(groups.values()),scopes


def selected_fields(names):
    out={}
    patterns={
        'tournament_id':r'tournament|arenaid|arena_id',
        'berserk':r'berserk',
        'title':r'title',
        'tournament_scoring':r'streak|scoresheet|score_sheet|tournament.*score|arena.*score|standing|(^|\.)(score|scores|rank|rankings|points)$',
        'end_or_deadline':r'finish|completion|ended|endsat|ends_at|deadline',
        'last_move_proxy':r'last.?move',
        'record_blob':r'(^|\.)(json|payload|response|raw_json|body|pgn)$',
        'event_header':r'(^|\.)(event|site)$'}
    for key,pat in patterns.items():out[key]=[n for n in names if re.search(pat,n,re.I)]
    return out


def field_paths(fields,prefix=''):
    result=[]
    for f in fields:
        name=prefix+f.name;result.append(name)
        if pa.types.is_struct(f.type):result.extend(field_paths(f.type,name+'.'))
        elif pa.types.is_list(f.type) or pa.types.is_large_list(f.type):
            if pa.types.is_struct(f.type.value_type):result.extend(field_paths(f.type.value_type,name+'[].'))
    return result


def json_paths(value,prefix='',depth=0):
    if depth>7:return []
    if isinstance(value,dict):
        result=[]
        known={'id','gameid','tournamentid','arenaid','tournament','arena','berserk','white','black',
          'players','player','user','users','title','score','scores','scoresheet','streak','standing',
          'standings','finishedat','finishat','endedat','endsat','endat','createdat','startsat',
          'lastmoveat','setting','settings','position','clock','rated','variant','status','winner',
          'moves','turns','createdby','data','games','game','results','result','pgn','rounds','end',
          'pairings','secondstofinish','seconds','duration','minutes','noberserk','nostreak',
          'rank','rankings','points','payload','response','rawjson','body','json'}
        for k,v in value.items():
            if re.sub('[^a-z0-9]','',str(k).lower()) not in known:continue
            key=prefix+str(k);result.append(key);result.extend(json_paths(v,key+'.',depth+1))
        return result
    if isinstance(value,list):
        return sorted({k for v in value[:3] for k in json_paths(v,prefix+'[].',depth+1)})
    return []


def prefix_bytes(p):
    if p.name.endswith('.gz'):
        with gzip.open(p,'rb') as f:return f.read(PREFIX_BYTES)
    if p.name.endswith('.zst'):
        with pa.OSFile(str(p),'rb') as raw:
            with pa.CompressedInputStream(raw,'zstd') as f:return f.read(PREFIX_BYTES)
    if p.name.endswith('.bz2'):
        import bz2
        with bz2.open(p,'rb') as f:return f.read(PREFIX_BYTES)
    with p.open('rb') as f:return f.read(PREFIX_BYTES)


def inspect_representative(task):
    family,kind,path,signature=task;p=Path(path)
    result={'family':family,'kind':kind,'path':path,'status':'OK','rows_in_footer':None,
            'schema_json':None,'matched_fields_json':None,'prefix_bytes_read':0,'error':None}
    try:
        old.require(old.signature(p)==signature,'File changed after enumeration')
        if kind=='parquet':
            pf=pq.ParquetFile(p);names=field_paths(pf.schema_arrow)
            result.update(rows_in_footer=pf.metadata.num_rows,schema_json=json.dumps(names))
            matches=selected_fields(names)
        else:
            data=prefix_bytes(p);result['prefix_bytes_read']=len(data)
            text=data.decode('utf-8',errors='replace')
            if kind=='pgn':
                tags=re.findall(r'^\[([A-Za-z0-9_]+)\s+"[^\n]*"\]\s*$',text,re.M)
                names=sorted(set(tags));matches=selected_fields(names)
                matches['prefix_tournament_url_present']=bool(re.search(old.TOUR_RE,text))
            else:
                objects=[]
                if kind=='json':
                    try:objects=[json.loads(text)]
                    except json.JSONDecodeError:pass
                else:
                    for line in text.splitlines()[:100]:
                        try:objects.append(json.loads(line))
                        except json.JSONDecodeError:pass
                names=sorted({k for o in objects for k in json_paths(o)})
                matches=selected_fields(names)
                if not objects:result['status']='PREFIX_NOT_PARSEABLE_COMPLETE_RECORD'
            result['schema_json']=json.dumps(names)
        result['matched_fields_json']=json.dumps(matches,sort_keys=True)
        old.require(old.signature(p)==signature,'File changed during inspection')
    except Exception as e:
        result.update(status='UNREAD_OR_CHANGED',error=str(e),schema_json=None,matched_fields_json=None)
    return result


def write_catalogue(groups,scopes,report,workers):
    tasks=[(g['family'],g['kind'],p,s) for g in groups for _,p,s in g['representatives']]
    results=[]
    old.log(f'Inspecting {len(tasks):,} representative footers/header prefixes using {workers} workers')
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i,r in enumerate(ex.map(inspect_representative,tasks),1):
            results.append(r)
            if i%1000==0:old.log(f'Inspected {i:,}/{len(tasks):,} representatives')
    schema=pa.schema([('family',pa.string()),('kind',pa.string()),('path',pa.string()),('status',pa.string()),
       ('rows_in_footer',pa.int64()),('schema_json',pa.string()),('matched_fields_json',pa.string()),
       ('prefix_bytes_read',pa.int64()),('error',pa.string())])
    pq.write_table(pa.Table.from_pylist(results,schema=schema),report/'representative_schemas.parquet',compression='zstd')
    fs=pa.schema([('family',pa.string()),('kind',pa.string()),('files',pa.int64()),('bytes',pa.int64())])
    pq.write_table(pa.Table.from_pylist([{k:g[k] for k in ('family','kind','files','bytes')} for g in groups],schema=fs),
        report/'asset_families.parquet',compression='zstd')
    relevant=[]
    for r in results:
        m=json.loads(r['matched_fields_json'] or '{}')
        if any(m.get(k) for k in ('tournament_id','berserk','title','tournament_scoring','end_or_deadline','record_blob','event_header','prefix_tournament_url_present')):
            relevant.append({k:v for k,v in r.items() if k!='schema_json'})
    old.write_json(report/'candidate_sources.json',{'scopes':scopes,'relevant_representatives':relevant,
       'schema_sampling':'At most three deterministic hash-selected files per filename family; not all file schemas are certified',
       'row_sampling':'No Parquet rows scanned; up to 256 KiB per sampled PGN/JSON file',
       'absence_is_not_certified':True})
    return {'families':len(groups),'representatives':len(results),'candidate_representatives':len(relevant),
            'unread_or_changed':sum(r['status']!='OK' for r in results),
            'enumeration_errors':sum(len(s['walk_errors']) for s in scopes)}


def run(args):
    started=time.monotonic();project=Path(args.project).expanduser().resolve()
    old.require(project.is_dir(),'Project volume is not mounted')
    work=project/'derived/replication/kac_a3_local_sources_v100_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=(work/'run.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report=project/'output/kac_a3_local_sources_v100'/('KAC_A3_LOCAL_SOURCES_RESULT_'+stamp);report.mkdir(parents=True)
    status={'status':'RUNNING','API_requests':0,'engine_evaluations':0,'behavioral_models_fit':0,
            'prior_audit_rebuilt':False,'old_private_files_changed':False,'price_measured':False}
    try:
        status['package_manifest_sha256']=verify_package()
        base,inputs=find_cached_inputs(project)
        workers=min(10,max(1,args.workers),os.cpu_count() or 1);status['workers']=workers
        tasks=[(str(base/('month='+r['month'])),r,inputs['contract']) for r in inputs['records']]
        with ThreadPoolExecutor(max_workers=workers) as ex:checked=list(ex.map(verify_projection,tasks))
        paths=[x[0] for x in checked]
        old.require(sum(x[1]['kept_rows'] for x in checked)==REVIEWED_ROWS,'Reviewed retained count differs')
        status['authenticated_cached_months']=len(paths)
        private=work/stamp;private.mkdir()
        status['support']=state_support(paths,report,private,workers)
        groups,scopes=enumerate_assets(project,[Path(x).expanduser() for x in args.extra_root])
        status['catalogue']=write_catalogue(groups,scopes,report,workers)
        for _,_,s in checked:old.require(old.signature(s['path'])==s['signature'],'Cached projection changed during run')
        status['status']='LOCAL_SOURCE_AND_SUPPORT_REVIEW_COMPLETE_PRICE_NOT_ESTIMATED'
        if status['catalogue']['unread_or_changed'] or status['catalogue']['enumeration_errors']:
            status['status']='LOCAL_REVIEW_COMPLETE_WITH_UNREAD_ASSETS_PRICE_NOT_ESTIMATED'
        old.write_json(private/'CACHE_LINEAGE.json',{'old_contract':inputs['contract'],'inputs_sha256':old.sha(base/'INPUTS.json'),
             'projections':[x[2] for x in checked]})
    except Exception as e:
        status.update(status='LOCAL_REVIEW_BLOCKED',error=str(e));(report/'ERROR.txt').write_text(traceback.format_exc())
        old.log('Stopped: '+str(e))
    finally:
        status['elapsed_seconds']=time.monotonic()-started;old.write_json(report/'SUMMARY.json',status)
        (report/'READ_ME_FIRST.txt').write_text('This is a local source and support review, not an estimated price effect.\n'
          'No grant outcomes were used. Repeat cells can support within-cell comparisons only if measured price varies.\n'
          'Source leads are based on sampled schemas/header prefixes, not certified complete tournament histories.\n'
          'Private tournament and account keys remain on the Mac. The portable report contains schemas, paths, and aggregates.\n'
          'An empty source category means no lead in the inspected sample, not that no file exists elsewhere.\n')
        old.make_report_zip(report,Path(args.report_dir).expanduser());fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    return 2 if status['status']=='LOCAL_REVIEW_BLOCKED' else 0


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',default='/Volumes/XT_Pro/lichess_kindness')
    p.add_argument('--workers',type=int,default=10)
    p.add_argument('--report-dir',default=str(Path.home()/'Desktop/Lichess_Desktop'))
    p.add_argument('--extra-root',action='append',default=[],help='Optional known legacy source folder; metadata/header inspection only')
    raise SystemExit(run(p.parse_args()))
