"""Explicit, authenticated adoption from the failed v1.0.0 run."""
from util import *
import fcntl

PARENT_MANIFEST='340344997fbcc83617751d9d03410f2d68d29d4a9e554c04768518886f0618e2'
PARENT_ZIP='130e5eed2521ea679bdde90d4c1979aa944b668d7df9a6229b03fcf936a23d44'

def parent_config():
    d=load(ROOT/'authority/parent/CONFIG.json')
    return {k:d[k] for k in ('version','package_sha','project','design_sha')}

def parent_key():return digest(parent_config())

def parent_root(run):
    return Path(run).parents[1]/'kac_companion_analyses_v100'/parent_key()[:16]

def lock_parent(project):
    expected=parent_config()
    require(expected['package_sha']==PARENT_MANIFEST,'Parent package authority changed')
    require(str(Path(project).resolve())==expected['project'],'This resume is bound to the original project root')
    root=Path(project)/'output/kac_companion_analyses_v100'/parent_key()[:16]
    require(root.is_dir(),'Original companion output missing: '+str(root))
    actual=load(root/'report/CONFIG.json')
    require(all(actual[k]==v for k,v in expected.items()),'Original run configuration differs')
    handle=(root/'RUN.lock').open('a')
    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Original companion is still running. No duplicate started.')
    return handle

def adopt_checkpoint(old,out,old_key,new_key,source_path):
    if not (Path(old)/'_DONE.json').is_file():return False
    require(cached(old,old_key),'Parent checkpoint unavailable')
    rec=load(Path(old)/'_DONE.json')
    source=rec['source']
    require(str(source_path)==source['path'] and snapshot(source_path)==source['stat'],
        'Source differs from completed parent checkpoint: '+str(source_path))
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    for row in rec['files']:
        name=row['path'];require(not Path(name).is_absolute() and '..' not in Path(name).parts,'Unsafe cache member')
        p=out/name;p.parent.mkdir(parents=True,exist_ok=True)
        tmp=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
        try:os.link(Path(old)/name,tmp)
        except OSError:shutil.copyfile(Path(old)/name,tmp)
        os.replace(tmp,p)
    commit(out,new_key,source=source,rows=rec.get('rows'),
        adopted_from=dict(directory=str(old),key=old_key,receipt_sha256=sha(Path(old)/'_DONE.json'),
            reason='Unchanged projection or validated all-positive pre-buffer count'))
    return True

def adopt_models(run,key):
    from incidents import model_load,model_save
    copied=[]
    for folder,kind in [('receipt_hour','receipt'),('iv_hour','iv')]:
        oldconf=digest([parent_key(),kind+'_exact_hours_v1'])
        newconf=digest([key,kind+'_exact_hours_v3'])
        for p in sorted((ROOT/'authority/parent'/folder).glob('*.json')):
            if p.name.endswith('.ok.json'):continue
            record=model_load(p,oldconf)
            dest=Path(run)/'report'/folder/p.name
            if model_load(dest,newconf) is None:model_save(dest,newconf,record)
            copied.append(dict(model=str(dest.relative_to(run)),sha256=sha(p),parent_model_key=oldconf))
    js(Path(run)/'report/ADOPTED_MODELS.json',dict(parent_result_zip_sha256=PARENT_ZIP,
        parent_run=parent_key()[:16],models=copied,
        note='Completed baseline/start-hour values preserved verbatim. Input SHA256 gates are rerun before further estimation.'))

def timestamp_audit(cat,run):
    """Footer scan first; query suspicious files only, before any history estimate."""
    bound=int(pd.Timestamp('2023-10-01',tz='UTC').timestamp()*1000)
    rows=[];affected=[]
    for r in cat['chronology']:
        require(snapshot(r['path'])==r['stat'],'History source changed before timestamp audit: '+r['path'])
        pf=pq.ParquetFile(r['path']);ix=pf.schema_arrow.names.index('utc_ms')
        stats=[pf.metadata.row_group(i).column(ix).statistics for i in range(pf.metadata.num_row_groups)]
        known=all(s is not None and s.has_min_max and s.null_count is not None for s in stats)
        lo=min(s.min for s in stats) if known else None
        hi=max(s.max for s in stats) if known else None
        nulls=sum(s.null_count for s in stats) if known else None
        low=int(pd.Timestamp(r['month']+'-01',tz='UTC').timestamp()*1000)
        high=int((pd.Timestamp(r['month']+'-01',tz='UTC')+pd.offsets.MonthBegin()).timestamp()*1000)
        suspicious=not known or nulls!=0 or lo<=0 or (hi>=bound if r['month']<'2023-10' else lo<low or hi>=high)
        row=dict(speed=r['speed'],month=r['month'],rows=r['rows'],minimum_ms=lo,maximum_ms=hi,
            null_count=nulls,footer_statistics_complete=known,suspicious=suspicious)
        if suspicious:
            folder=Path(run)/'PRIVATE/timestamp_audit'/(r['speed']+'_'+r['month'])
            c=db(folder/'spill',1,1)
            try:
                c.execute('CREATE VIEW raw AS SELECT * FROM '+scan(r['path']))
                c.execute('CREATE VIEW needed AS SELECT * FROM '+scan(Path(run)/'PRIVATE/needed.parquet'))
                invalid=f'utc_ms IS NULL OR utc_ms<=0 OR utc_ms>={bound}' if r['month']<'2023-10' else f'utc_ms IS NULL OR utc_ms<{low} OR utc_ms>={high}'
                c.execute('CREATE TEMP TABLE bad AS SELECT * FROM raw WHERE '+invalid)
                row['invalid_rows']=c.execute('SELECT count(*) FROM bad').fetchone()[0]
                row['invalid_needed_chooser_rows']=c.execute('''SELECT count(*) FROM bad WHERE
                    white_id IN(SELECT chooser FROM needed) OR black_id IN(SELECT chooser FROM needed)''').fetchone()[0]
                row['affected_choosers']=copy(c,'''SELECT DISTINCT chooser FROM
                    (SELECT white_id chooser FROM bad UNION ALL SELECT black_id chooser FROM bad) JOIN needed USING(chooser)''',folder/'affected_choosers.parquet')
                row['invalid_time_kinds']=c.execute('''SELECT count(*) FILTER(WHERE utc_ms IS NULL),
                    count(*) FILTER(WHERE utc_ms=0),count(*) FILTER(WHERE utc_ms<0),count(*) FILTER(WHERE utc_ms>0) FROM bad''').fetchone()
                if row['affected_choosers']:affected.append(row)
                # Raw identifiers stay private; exported diagnostic contains only counts.
                copy(c,'SELECT game_id,utc_ms,white_id,black_id FROM bad',folder/'bad_rows.parquet')
            finally:c.close();shutil.rmtree(folder/'spill',ignore_errors=True)
        rows.append(row)
        require(snapshot(r['path'])==r['stat'],'History source changed during timestamp audit: '+r['path'])
    result=dict(status='BLOCKED_AFFECTED_CHOOSER_TIMESTAMP' if affected else 'PASS_NO_ANALYSIS_CHOOSER_AFFECTED',
        files=len(rows),suspicious_files=[r for r in rows if r['suspicious']],
        affected_chooser_file_counts=sum(r['affected_choosers'] for r in affected),
        rule='No timestamp imputation. No analysis account exclusion. Invalid unrelated rows cannot enter chooser histories.',
        inventory=rows)
    js(Path(run)/'report/TIMESTAMP_AUDIT.json',result)
    log('Timestamp audit: '+result['status'])
    return result

def cache_summary(run):
    answer={}
    for kind in ('focal','prefix'):
        records=[load(p) for p in (Path(run)/'PRIVATE'/kind).glob('*/_DONE.json')]
        answer[kind]=dict(completed=len(records),adopted=sum('adopted_from' in r for r in records))
    records=[load(p) for p in (Path(run)/'PRIVATE/history').glob('*/_DONE.json') if p.parent.name!='initial']
    answer['history']=dict(completed=len(records),adopted=sum('adopted_from' in r for r in records))
    answer['prefix_note']='v1.0.1 reuses the authenticated initial carry; individual prefix outputs need not be copied.'
    js(Path(run)/'report/CACHE_REUSE.json',answer)
    return answer
