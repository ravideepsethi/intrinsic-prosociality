#!/usr/bin/env python3
"""Read-only source diagnosis. Never normalizes keys or imputes timestamps."""
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
import argparse, collections, contextlib, datetime as dt, fcntl, hashlib, json
import re, shutil, subprocess, sys, threading, time, traceback, uuid, zipfile
from pathlib import Path
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
pa.set_cpu_count(1)
pa.set_io_thread_count(1)
ROOT=Path(__file__).resolve().parent

def require(condition,code):
    if not condition: raise RuntimeError(code)
def load(p): return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def snap(p):
    s=Path(p).stat();return dict(bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def js(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.partial');temp.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n');os.replace(temp,p)
def q(x):return "'"+str(x).replace("'","''")+"'"
def scan(p):
    values=p if isinstance(p,list) else [p]
    return 'read_parquet(['+','.join(q(x) for x in values)+'],hive_partitioning=false)'
def save_table(p,table):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.partial');pq.write_table(table,temp,compression='zstd');os.replace(temp,p)
def log(message):print(dt.datetime.now().strftime('[%Y-%m-%d %H:%M:%S] ')+message,flush=True)
def available_threads(want):
    while True:
        lines=subprocess.check_output(['ps','-axo','pid=,command='],text=True)
        used=0
        for line in lines.splitlines():
            match=re.match(r'\s*(\d+)\s+(.*)',line)
            if not match:continue
            pid,cmd=int(match[1]),match[2]
            if pid==os.getpid() or str(ROOT) in cmd:continue
            exe=cmd.split(' ',1)[0]
            if not re.search(r'(?:^|/)python(?:[0-9.]*)?$',exe):continue
            if not re.search(r'lichess|kac_|code/run\.py',cmd,re.I):continue
            amount=re.search(r'--(?:workers|threads|worker-budget)(?:=|\s+)(\d+)',cmd)
            used+=int(amount[1]) if amount else 1
        if used<10:return min(want,10-used)
        log('Waiting for capacity within the ten-worker total budget; existing jobs continue.')
        time.sleep(30)
@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event()
    def pulse():
        while not stop.wait(30):log(label+' — working')
    t=threading.Thread(target=pulse,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()

def key_summary(value):
    """Return shape only, not literal key, URL, account, or reversible hash."""
    if value is None:return {'kind':'null'}
    if not isinstance(value,str):return {'kind':'non_string','python_type':type(value).__name__}
    stripped=value.strip()
    ascii_alnum=lambda s: bool(re.fullmatch(r'[A-Za-z0-9]+',s))
    url=bool(re.fullmatch(r'https?://(?:www\.)?lichess\.org/[A-Za-z0-9]{8}(?:/(?:white|black))?/?',stripped))
    return dict(kind='string',length=len(value),empty=not value,ascii=value.isascii(),
        standard_eight=bool(re.fullmatch(r'[A-Za-z0-9]{8}',value)),
        standard_eight_after_strip=bool(re.fullmatch(r'[A-Za-z0-9]{8}',stripped)),
        surrounding_whitespace=value!=stripped,alphanumeric=ascii_alnum(value),
        url_shaped=url,contains_control=any(ord(c)<32 or ord(c)==127 for c in value),
        letters=sum(c.isascii() and c.isalpha() for c in value),
        digits=sum(c in '0123456789' for c in value),
        other_characters=sum(not(c.isascii() and c.isalnum()) for c in value))
def grouped(values,fn):
    counts=collections.Counter(json.dumps(fn(x),sort_keys=True) for x in values)
    return [dict(shape=json.loads(k),count=v) for k,v in sorted(counts.items())]
def time_kind(x):
    return 'null' if x is None else 'zero' if x==0 else 'negative' if x<0 else 'positive'

def inspect_source(c,source,cache,affected,private):
    before=snap(source)
    c.execute('CREATE TEMP VIEW raw AS SELECT * FROM '+scan(source))
    c.execute('CREATE TEMP VIEW affected AS SELECT chooser FROM '+scan(affected))
    c.execute('CREATE TEMP TABLE bad AS SELECT * FROM raw WHERE utc_ms IS NULL OR utc_ms<=0')
    # Compare the full cached bad-row multiset, not only its row count.
    cols='game_id,utc_ms,white_id,black_id'
    mismatch=c.execute(f'SELECT count(*) FROM ((SELECT {cols} FROM bad EXCEPT ALL SELECT {cols} FROM {scan(cache)}) UNION ALL '
        f'(SELECT {cols} FROM {scan(cache)} EXCEPT ALL SELECT {cols} FROM bad))').fetchone()[0]
    require(mismatch==0,'CACHED_BAD_ROWS_DIFFER_FROM_SOURCE')
    c.execute('CREATE TEMP TABLE target AS SELECT * FROM bad WHERE white_id IN(SELECT chooser FROM affected) '
        'OR black_id IN(SELECT chooser FROM affected)')
    targets=c.execute('SELECT * FROM target').to_arrow_table();rows=targets.to_pylist()
    require(len(rows)==1,'TARGET_COUNT_CHANGED')
    c.execute('CREATE TEMP TABLE needed_matches AS SELECT * FROM target')
    save_table(private/'target.parquet',targets)
    save_table(private/'all_invalid_rows.parquet',c.execute('SELECT * FROM bad').to_arrow_table())
    invalid=c.execute('SELECT game_id,utc_ms FROM bad').fetchall()
    target=rows[0]
    summary=dict(invalid_rows=len(invalid),invalid_time_counts=dict(collections.Counter(time_kind(x[1]) for x in invalid)),
        invalid_key_shapes=grouped([x[0] for x in invalid],key_summary),
        target_key=key_summary(target['game_id']),target_time_kind=time_kind(target['utc_ms']),
        target_null_fields=[k for k,v in target.items() if v is None],
        target_result_in_declared_codes=target.get('result_code') in (0,1,2),
        target_ratings_positive=all(isinstance(target.get(k),int) and target[k]>0 for k in ('white_elo','black_elo')),
        target_distinct_players=target['white_id']!=target['black_id'],cached_bad_rows_match_source=True)
    # Samples adjacent in archive order diagnose a parser boundary, but stay private.
    if target.get('archive_ordinal') is not None:
        ordinal=target['archive_ordinal']
        neighbors=c.execute('SELECT * FROM raw WHERE archive_ordinal BETWEEN ? AND ? ORDER BY archive_ordinal',
            [ordinal-3,ordinal+3]).to_arrow_table()
        save_table(private/'archive_neighbors.parquet',neighbors)
        ns=neighbors.to_pylist()
        summary['neighbor_rows']=len(ns)
        summary['neighbor_valid_key_rows']=sum(key_summary(x['game_id']).get('standard_eight',False) for x in ns)
        summary['neighbor_positive_time_rows']=sum(x['utc_ms'] is not None and x['utc_ms']>0 for x in ns)
    require(snap(source)==before,'SOURCE_CHANGED_DURING_READ')
    summary['source_sha256']=sha(source)
    require(snap(source)==before,'SOURCE_CHANGED_DURING_HASH')
    return summary,target,before

def footer_summary(source,authority):
    f=pq.ParquetFile(source);m=f.metadata;ix=f.schema_arrow.names.index('utc_ms')
    mins=[];maxs=[];missing=0;nulls=0
    for i in range(m.num_row_groups):
        s=m.row_group(i).column(ix).statistics
        if s is None or not s.has_min_max:missing+=1
        else:mins.append(s.min);maxs.append(s.max)
        if s is not None and s.null_count is not None:nulls+=s.null_count
    signature=dict(path=authority['path'],bytes=source.stat().st_size,rows=m.num_rows,
        row_groups=m.num_row_groups,selected_row_groups=[int(x) for x in authority['selected_row_groups'].split(',') if x],
        utc_ms_min=min(mins) if mins else None,utc_ms_max=max(maxs) if maxs else None,
        row_groups_without_utc_stats=missing,schema=f.schema_arrow.to_string())
    digest=hashlib.sha256(json.dumps(signature,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(rows=m.num_rows,bytes=source.stat().st_size,row_groups=m.num_row_groups,
        created_by=m.created_by,schema=f.schema_arrow.to_string(),null_utc_rows=nulls,
        manifest_counts_match=(m.num_rows==int(authority['rows']) and source.stat().st_size==int(authority['bytes'])
            and m.num_row_groups==int(authority['row_groups'])),
        computed_footer_signature_sha256=digest,expected_footer_signature_sha256=authority['footer_signature_sha256'],
        footer_signature_matches=digest==authority['footer_signature_sha256'],
        historical_manifest_already_had_zero_minimum=int(authority['utc_ms_min'])==0)

def numeric_comparison(c,files,private):
    before={str(p):snap(p) for p in files}
    c.execute('CREATE TEMP VIEW numeric_input AS SELECT * FROM '+scan(files))
    names={r[0] for r in c.execute('DESCRIBE numeric_input').fetchall()}
    wanted={'archive_ordinal','white_id','black_id','game_id','utc_ts','white_elo','black_elo','result'}
    if not wanted<=names:return dict(status='SCHEMA_NOT_COMPARABLE',missing_columns=sorted(wanted-names))
    # Check the same archive ordinal, then report identity agreement; do not silently select by a guessed key.
    table=c.execute('SELECT n.* FROM numeric_input n JOIN target t ON n.archive_ordinal=t.archive_ordinal LIMIT 1001').to_arrow_table()
    require(table.num_rows<=1000,'UPSTREAM_ARCHIVE_ORDINAL_NOT_SELECTIVE')
    save_table(private/'numeric_same_ordinal.parquet',table)
    target=c.execute('SELECT * FROM target').to_arrow_table().to_pylist()[0]
    matches=[]
    for row in table.to_pylist():
        raw=row['utc_ts'];parsed=None
        if isinstance(raw,str):
            try:parsed=dt.datetime.strptime(raw,'%Y-%m-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc)
            except ValueError:pass
        matches.append(dict(same_players=all(row[k]==target[k] for k in ('white_id','black_id')),
            same_game_key=row['game_id']==target['game_id'],same_ratings=all(row[k]==target[k] for k in ('white_elo','black_elo')),
            result_agrees={'1-0':2,'1/2-1/2':1,'0-1':0}.get(row['result'])==target['result_code'],
            game_key_shape=key_summary(row['game_id']),utc_text_present=isinstance(raw,str) and bool(raw),
            utc_text_length=len(raw) if isinstance(raw,str) else None,utc_parses_with_producer_format=parsed is not None,
            utc_in_June_2023=parsed is not None and parsed.year==2023 and parsed.month==6))
    require(all(snap(p)==before[str(p)] for p in files),'UPSTREAM_SOURCE_CHANGED')
    return dict(status='COMPARED_NO_REPAIR_APPLIED',files=len(files),same_ordinal_rows=len(matches),comparisons=matches)

def lineage(c,project,source,private):
    sorted_root=source.parents[3]
    reports={};numeric=None
    # These are producer-defined locations, not a recursive search through raw/API trees.
    for label,p in [('command',sorted_root/'command.json'),('success',source.parent/'_SUCCESS.json'),
                    ('summary',sorted_root/'summary.json'),('sort_log',sorted_root/'logs/sort_time_bullet_2023-06.log')]:
        item=dict(exists=p.is_file())
        if p.is_file():
            item.update(bytes=p.stat().st_size,sha256=sha(p))
            if p.stat().st_size<=2*1024**2:
                shutil.copyfile(p,private/(label+p.suffix))
                if p.suffix=='.json':
                    try:
                        obj=load(p)
                        if isinstance(obj,dict):
                            item['keys']=sorted(obj)
                            if label=='command':numeric=obj.get('numeric_root')
                    except (ValueError,TypeError):item['parse_status']='INVALID_JSON'
                else:
                    content=p.read_text(errors='replace')
                    item['sql_contains_ts_not_null']=bool(re.search(r'WHERE\s+ts\s+IS\s+NOT\s+NULL',content,re.I))
        reports[label]=item
    outcome=dict(producer_artifacts=reports,upstream=dict(status='NO_PRODUCER_NUMERIC_ROOT'))
    if isinstance(numeric,str):
        nr=Path(numeric)
        if not nr.is_absolute():nr=project/nr
        nr=nr.resolve()
        try:nr.relative_to(project.resolve())
        except ValueError:
            outcome['upstream']['status']='NUMERIC_ROOT_OUTSIDE_PROJECT_NOT_SCANNED';return outcome
        folder=nr/'events_numeric/month=2023-06/speed=bullet'
        files=sorted(folder.glob('*.parquet'))
        outcome['upstream']=dict(status='NUMERIC_PARTITION_MISSING' if not files else 'AVAILABLE',files=len(files))
        if files:
            require(len(files)<=256,'UPSTREAM_PARTITION_TOO_MANY_FILES')
            log('Comparing the affected archive ordinal with the producer’s June bullet inputs')
            outcome['upstream']=numeric_comparison(c,files,private)
    return outcome

def export(run,desktop):
    report=run/'report';manifest=[]
    for p in sorted(report.rglob('*')):
        if p.is_file() and p.name!='MANIFEST.json':manifest.append(dict(path=str(p.relative_to(report)),sha256=sha(p),bytes=p.stat().st_size))
    js(report/'MANIFEST.json',dict(files=manifest))
    dest=desktop/('KAC_TIMESTAMP_DIAGNOSTIC_RESULT_'+run.name+'.zip')
    temp=dest.with_suffix('.partial.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(temp,dest);dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_RESULT '+str(dest))

def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop');p.add_argument('--threads',type=int,default=3)
    args=p.parse_args();require(1<=args.threads<=3,'USE_ONE_TO_THREE_THREADS')
    manifest=load(ROOT/'PACKAGE_MANIFEST.json')
    for entry in manifest['files']:require(sha(ROOT/entry['path'])==entry['sha256'],'PACKAGE_DAMAGED')
    auth=load(ROOT/'AUTHORITY.json');project=args.project_root.resolve();desktop=args.desktop
    require(str(project)==auth['parent_config']['project'],'PROJECT_DIFFERS_FROM_REVIEWED_RUN')
    parent=project/'output/kac_companion_recovery_v102'/auth['parent_run']
    conf=load(parent/'report/CONFIG.json')
    require(all(conf.get(k)==v for k,v in auth['parent_config'].items()),'PARENT_CONFIG_CHANGED')
    parent_locks=[]
    for existing in [parent,project/'output/kac_companion_analyses_v100/9560b33ec926b6ca']:
        lock=(existing/'RUN.lock').open('a')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('COMPANION_STILL_RUNNING_NO_DIAGNOSTIC_STARTED') from None
        parent_locks.append(lock)
    source=Path(auth['chronology']['path'])
    require(source.is_file(),'SOURCE_NOT_MOUNTED')
    cache=parent/'PRIVATE/timestamp_audit/bullet_2023-06'
    require((cache/'bad_rows.parquet').is_file() and (cache/'affected_choosers.parquet').is_file(),'CACHED_DIAGNOSTIC_MISSING')
    run=project/'output/kac_timestamp_diagnostic_v100'/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6])
    private=run/'PRIVATE';private.mkdir(parents=True);(run/'report').mkdir();desktop.mkdir(parents=True,exist_ok=True)
    threads=available_threads(args.threads)
    c=duckdb.connect(config={'threads':str(threads),'memory_limit':'2GB','temp_directory':str(private/'spill')})
    status=dict(status='DIAGNOSTIC_IN_PROGRESS',source_files_modified=False,models_rerun=0,account_exclusions=0,api_requests=0)
    try:
        js(run/'report/CONFIG.json',dict(version='1.0.0',threads=threads,worker_budget=10,package_manifest_sha256=sha(ROOT/'PACKAGE_MANIFEST.json'),
            reviewed_result_sha256=auth['parent_result_sha256'],python=sys.version.split()[0],duckdb=duckdb.__version__,pyarrow=pa.__version__))
        footer=footer_summary(source,auth['chronology']);js(run/'report/FOOTER.json',footer)
        require(footer['manifest_counts_match'],'SOURCE_COUNTS_CHANGED')
        log('Checking the cached bad rows against the June bullet Parquet')
        with heartbeat('Targeted chronology diagnostic'):
            summary,target,before=inspect_source(c,source,cache/'bad_rows.parquet',cache/'affected_choosers.parquet',private)
            js(run/'report/KEY_AND_TIME.json',summary)
            js(run/'report/LINEAGE.json',lineage(c,project,source,private))
        require(snap(source)==before,'SOURCE_CHANGED_DURING_DIAGNOSTIC')
        status['status']='DIAGNOSTIC_COMPLETE_REPAIR_NOT_APPLIED'
    except Exception as e:
        (private/'ERROR.txt').write_text(traceback.format_exc())
        code=str(e) if isinstance(e,RuntimeError) and re.fullmatch('[A-Z0-9_]+',str(e)) else type(e).__name__
        status.update(status='DIAGNOSTIC_BLOCKED',reason=code)
    finally:
        c.close();shutil.rmtree(private/'spill',ignore_errors=True)
        js(run/'report/STATUS.json',status);export(run,desktop)
    log(status['status']+'; completed analyses were not rerun.')
    if status['status']=='DIAGNOSTIC_BLOCKED':raise SystemExit(1)

if __name__=='__main__':main()
