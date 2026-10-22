#!/usr/bin/env python3
"""Portable metadata downloader with per-request SQLite transactions and return packing."""
from __future__ import annotations
import argparse, contextlib, fcntl, gzip, hashlib, json, math, os, shlex, shutil, sqlite3, subprocess, time, zipfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import expansion_common as x
import metadata_http as http
import local_io as io

def binding(ids):return hashlib.sha256('\n'.join(ids).encode('ascii')).hexdigest()

def unpack_input(archive,desktop,checksum=None):
    archive=archive.resolve();digest=io.sha(archive)
    candidates=[Path(checksum)] if checksum else sorted(archive.parent.glob('CHOOSER_COMPARISON_EXPANSION_INPUT_*.sha256*'))
    if not any(p.is_file() and p.read_text().split() and p.read_text().split()[0]==digest for p in candidates):
        raise RuntimeError('No matching input ZIP checksum. Keep the ZIP and its .sha256 sidecar together.')
    allowed={'targets.parquet','DESIGN_FREEZE.json','TRANSFER.json','INPUT_MANIFEST.json'}
    with zipfile.ZipFile(archive) as z:
        if len(z.namelist())!=4 or set(z.namelist())!=allowed:raise RuntimeError('Unexpected private input archive contents')
        manifest=json.loads(z.read('INPUT_MANIFEST.json'));conf=manifest['config_sha256']
        if len(manifest.get('files',[]))!=3 or {r['path'] for r in manifest['files']}!=allowed-{'INPUT_MANIFEST.json'}:
            raise RuntimeError('Private input manifest must cover every input file exactly once')
        if not isinstance(conf,str) or len(conf)!=64 or any(v not in '0123456789abcdef' for v in conf):raise RuntimeError('Invalid input configuration hash')
        root=desktop/f'CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_{conf[:12]}_PRIVATE';root.mkdir(exist_ok=True)
        inp=root/'inputs'
        def extract(out):
            x.require_disk(out,1+sum(i.file_size for i in z.infolist())/1024**3)
            for name in sorted(allowed):
                with z.open(name) as source,(out/name).open('xb') as dest:shutil.copyfileobj(source,dest,8*1024**2)
            for rec in manifest['files']:io.checked(io.child(out,rec['path']),rec['sha256'],rec['bytes'])
            return {'archive_sha256':digest}
        _,saved=io.stage(inp,conf,extract)
        if saved['archive_sha256']!=digest:raise RuntimeError('A different private input archive claims the same configuration')
    transfer=io.load(inp/'TRANSFER.json')
    if transfer['config_sha256']!=conf or pq.ParquetFile(inp/'targets.parquet').metadata.num_rows!=transfer['target_rows']:
        raise RuntimeError('Transfer target count or configuration mismatch')
    if io.load(inp/'DESIGN_FREEZE.json')['config_sha256']!=conf:raise RuntimeError('Input freeze mismatch')
    return root,conf,transfer

@contextlib.contextmanager
def exclusive(path,message):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError(message)
        yield

def check_other_api_jobs(project):
    """Inspect active known workers, allowing A1 once its API recovery is complete."""
    result=subprocess.run(['ps','-axo','pid=,command='],text=True,capture_output=True,check=True)
    for line in result.stdout.splitlines():
        try:pid,command=line.strip().split(None,1);args=shlex.split(command)
        except ValueError:continue
        if int(pid)==os.getpid():continue
        scripts=[Path(a) for a in args if a.endswith('.py')]
        for script in scripts:
            name=script.name
            if name in ('enrich_home.py','fast_home.py'):
                raise RuntimeError('Another comparison API job is active. Finish its downloads first.')
            if name=='run_build.py' and 'A1_Trajectory_Build_' in str(script):
                candidates=[]
                if script.is_file():
                    expected={p.name:io.sha(p) for p in script.parent.glob('*.py')}
                    for confpath in (project/'derived/replication/a1_trajectory_build_v100_PRIVATE').glob('*/RUN_CONFIG.json'):
                        if io.load(confpath).get('code')==expected:candidates.append(confpath.parent)
                if len(candidates)!=1 or not (candidates[0]/'RECOVERY_COMPLETE.json').is_file():
                    raise RuntimeError('A1 trajectory recovery is still using, or may next use, the API. Start this download after RECOVERY_COMPLETE is printed/saved. Its Stockfish phase may run alongside this downloader.')

def connect(path,conf,target_sha):
    db=sqlite3.connect(path,timeout=60)
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
    db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS responses(batch INTEGER,pass INTEGER,request_sha TEXT NOT NULL,raw_sha TEXT NOT NULL,raw_gzip BLOB NOT NULL,PRIMARY KEY(batch,pass));
      CREATE TABLE IF NOT EXISTS batches(batch INTEGER PRIMARY KEY,request_sha TEXT NOT NULL,requested INTEGER NOT NULL,returned INTEGER NOT NULL,flagged INTEGER NOT NULL);''')
    wanted={'config_sha256':conf,'target_sha256':target_sha,'url':http.URL,'batch_size':'300','passes':'3'}
    try:
        with db:
            for k,v in wanted.items():
                old=db.execute('SELECT value FROM meta WHERE key=?',(k,)).fetchone()
                if old and old[0]!=v:raise RuntimeError('Download checkpoint configuration changed')
                db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',(k,v))
    except BaseException:
        db.close();raise
    return db

def batches(path):
    remainder=[]
    for batch in pq.ParquetFile(path).iter_batches(batch_size=30000,use_threads=False):
        rows=remainder+batch.to_pylist();last=(len(rows)//300)*300
        for pos in range(0,last,300):yield rows[pos:pos+300]
        remainder=rows[last:]
    if remainder:yield remainder

def response(db,k,pass_no,ids,client):
    saved=db.execute('SELECT request_sha,raw_sha,raw_gzip FROM responses WHERE batch=? AND pass=?',(k,pass_no)).fetchone()
    request_sha=binding(ids)
    if saved:
        if saved[0]!=request_sha:raise RuntimeError('Saved request differs from target batch')
        raw=gzip.decompress(saved[2])
        if hashlib.sha256(raw).hexdigest()!=saved[1]:raise RuntimeError('Saved API response checksum mismatch')
        return http.parse(raw,ids)
    if client is None:raise RuntimeError('Missing saved response in completed batch')
    raw=client.get(ids);found=http.parse(raw,ids)
    with db:db.execute('INSERT INTO responses VALUES (?,?,?,?,?)',(k,pass_no,request_sha,hashlib.sha256(raw).hexdigest(),gzip.compress(raw,compresslevel=1,mtime=0)))
    return found

def process_batch(db,k,rows,client):
    ids=[r['game_id'] for r in rows];request_sha=binding(ids)
    done=db.execute('SELECT request_sha,requested,returned,flagged FROM batches WHERE batch=?',(k,)).fetchone()
    if done and (done[0]!=request_sha or done[1]!=len(rows)):raise RuntimeError('Completed batch identity changed')
    found={}
    for pass_no in range(3):
        missing=[g for g in ids if g not in found]
        if not missing:break
        found.update(response(db,k,pass_no,missing,None if done else client))
    normalized=[];unreturned=[];flags=0
    for frame in rows:
        gid=frame['game_id']
        if gid not in found:unreturned.append(dict(game_id=gid));continue
        row=x.normalize(found[gid]);errors=x.metadata_errors(row,frame)
        row['record_errors']=';'.join(errors);normalized.append(row);flags+=bool(errors)
    if done:
        if done[2]!=len(found) or done[3]!=flags:raise RuntimeError('Completed batch accounting changed')
    else:
        with db:db.execute('INSERT INTO batches VALUES (?,?,?,?,?)',(k,request_sha,len(rows),len(found),flags))
    return normalized,unreturned,flags,done is not None

def export_saved(db,target,folder,conf):
    def build(out):
        meta=pq.ParquetWriter(out/'downloaded_metadata.parquet',x.metadata_schema(),compression='zstd')
        missing=pq.ParquetWriter(out/'not_returned.parquet',pa.schema([('game_id',pa.string())]),compression='zstd')
        rowsbuf=[];missbuf=[];requested=returned=flagged=0
        try:
            for k,rows in enumerate(batches(target)):
                nr,nm,nf,_=process_batch(db,k,rows,None)
                requested+=len(rows);returned+=len(nr);flagged+=nf;rowsbuf.extend(nr);missbuf.extend(nm)
                if len(rowsbuf)>=30000:
                    meta.write_table(pa.Table.from_pylist(rowsbuf,schema=x.metadata_schema()));rowsbuf=[]
                if len(missbuf)>=30000:
                    missing.write_table(pa.Table.from_pylist(missbuf,schema=pa.schema([('game_id',pa.string())])));missbuf=[]
                if (k+1)%1000==0:io.log(f'Verifying saved return batches: {k+1:,}')
            if rowsbuf:meta.write_table(pa.Table.from_pylist(rowsbuf,schema=x.metadata_schema()))
            if missbuf:missing.write_table(pa.Table.from_pylist(missbuf,schema=pa.schema([('game_id',pa.string())])))
        finally:meta.close();missing.close()
        if requested!=pq.ParquetFile(target).metadata.num_rows:raise RuntimeError('Return denominator differs')
        summary=dict(config_sha256=conf,requested=requested,returned=returned,not_returned=requested-returned,
            returned_with_metadata_flags=flagged,all_targets_accounted=True,
            status='EXPANSION_METADATA_RETURN_COMPLETE' if requested==returned and flagged==0 else 'EXPANSION_METADATA_RETURN_WITH_GAPS',
            global_account_identity_verified=False,cache_conflicts_reconciled_against_new_returns=False,
            estimates_run=False,stockfish_searches=0)
        io.js(out/'SUMMARY.json',summary);return {k:v for k,v in summary.items() if k!='config_sha256'}
    return io.stage(folder,conf,build)

def select_archive(desktop,explicit):
    if explicit:return explicit.expanduser().resolve()
    found=sorted(desktop.glob('CHOOSER_COMPARISON_EXPANSION_INPUT_*_PRIVATE*.zip'))
    if len(found)!=1:raise RuntimeError('Expected one expansion input ZIP; use --input with its exact path when several exist')
    return found[0]

def status(root):
    path=root/'checkpoint.sqlite3'
    if not path.exists():io.log('No download requests saved yet.');return
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        r=db.execute('SELECT count(*),coalesce(sum(requested),0),coalesce(sum(returned),0),coalesce(sum(flagged),0) FROM batches').fetchone()
    print(f'Completed batches: {r[0]:,}; accounted IDs: {r[1]:,}; returned: {r[2]:,}; metadata flags: {r[3]:,}')

def pack(root,conf,desktop):
    if not io.complete(root/'finished',conf):raise RuntimeError('Finish the download before packing its return')
    dest=desktop/f'CHOOSER_COMPARISON_EXPANSION_RETURN_{conf[:12]}_PRIVATE.zip'
    stage=root/'return_pack';stage.mkdir(exist_ok=True)
    names=[]
    for p in sorted((root/'finished').iterdir()):
        if p.is_file():names.append('finished/'+p.name)
    # The closed WAL is checkpointed; store the actual evidence DB, not an unsafe live copy.
    db=sqlite3.connect(root/'checkpoint.sqlite3')
    try:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('Return checkpoint integrity check failed')
        if db.execute('SELECT value FROM meta WHERE key=?',('config_sha256',)).fetchone()!=(conf,):
            raise RuntimeError('Return checkpoint belongs to a different input')
        if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]!=0:
            raise RuntimeError('Checkpoint is busy; finish its downloader before packing')
    finally:db.close()
    names+=['checkpoint.sqlite3','inputs/TRANSFER.json','inputs/DESIGN_FREEZE.json','inputs/INPUT_MANIFEST.json']
    records=[dict(path=n,bytes=(root/n).stat().st_size,sha256=io.sha(root/n)) for n in names]
    io.js(root/'RETURN_MANIFEST.json',dict(config_sha256=conf,files=records));names+=['RETURN_MANIFEST.json']
    x.require_disk(desktop,1+sum(r['bytes'] for r in records)/1024**3)
    with io.heartbeat('Packing private return'):x.zip_files(root,dest,names)
    print('PRIVATE RETURN (copy to work laptop, do not upload here): '+str(dest));print('PRIVATE RETURN SHA: '+str(dest)+'.sha256')

def execute(a):
    desktop=a.desktop.expanduser().resolve();archive=select_archive(desktop,a.input)
    with io.heartbeat('Verifying private input ZIP'):root,conf,transfer=unpack_input(archive,desktop,a.checksum)
    if a.mode=='status':status(root);return
    with exclusive(root/'RUN.lock','This download or its return pack is already running'):
        if a.mode=='pack':pack(root,conf,desktop);return
        global_lock=Path.home()/'.cache/lichess_research_api'
        with exclusive(global_lock/'one_request.lock','Another Lichess comparison API downloader is running'):
            check_other_api_jobs(a.project_root)
            target=root/'inputs/targets.parquet';db=connect(root/'checkpoint.sqlite3',conf,io.sha(target))
            try:
                quick=db.execute('PRAGMA quick_check').fetchone()[0]
                if quick!='ok':raise RuntimeError('SQLite checkpoint integrity check failed')
                accounted=db.execute('SELECT coalesce(sum(requested),0) FROM batches').fetchone()[0]
                # Space for remaining responses plus typed exports of the full target list.
                x.require_disk(root,2+(max(0,transfer['target_rows']-accounted)*450+transfer['target_rows']*150)/1024**3)
                client=http.Client(global_lock/'cooldown.json');start=time.monotonic();new=0
                total=transfer['target_rows'];number=math.ceil(total/300)
                io.log('Metadata only: 300 IDs/request, one request at a time, ZERO pause after success. No Stockfish.')
                io.log('Checkpoint database: '+str(root/'checkpoint.sqlite3'))
                for k,rows in enumerate(batches(target)):
                    out,missing,flags,reused=process_batch(db,k,rows,client)
                    if not reused:new+=len(out)
                    elapsed=time.monotonic()-start;rate=new/elapsed if elapsed else 0
                    if not reused or (k+1)%1000==0 or k+1==number:
                        eta=max(0,total-(k+1)*300)/rate/3600 if rate else None
                        io.log(f'Batch {k+1:,}/{number:,}; returned {len(out)}/{len(rows)}; flags {flags}; '+
                            (f'{rate:.2f} games/s; remaining ETA {eta:.1f} hours' if rate else 'verified saved batch'))
                    if flags>max(3,len(out)*.05):
                        raise RuntimeError('More than 5% of a batch has metadata flags. Saved evidence retained; inspect before continuing.')
                with io.heartbeat('Verifying and exporting complete metadata return'):
                    _,s=export_saved(db,target,root/'finished',conf)
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            finally:db.close()
    report=root/'report';report.mkdir(exist_ok=True)
    s=io.load(root/'finished/SUMMARY.json');s.update(network_requests_this_invocation=client.requests,
        elapsed_seconds_this_invocation=time.monotonic()-start,http_seconds_this_invocation=client.http_seconds)
    io.js(report/'summary.json',s)
    dest=desktop/f'CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_REPORT_{conf[:12]}.zip';x.report_zip(report,dest)
    io.log(s['status']);print('UPLOAD: '+str(dest));print('UPLOAD: '+str(dest)+'.sha256')
    print('Run PACK_RETURN.command to prepare the private return ZIP for the work laptop.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['download','pack','status'])
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--input',type=Path);p.add_argument('--checksum',type=Path);p.add_argument('--project-root',type=Path,default=x.BASE)
    a=p.parse_args();os.umask(0o077)
    try:execute(a)
    except KeyboardInterrupt:io.log('Interrupted. Completed requests remain saved; rerun the same command.');raise SystemExit(130)
    except Exception as e:io.log('STOPPED: '+str(e));raise SystemExit(2)

if __name__=='__main__':main()
