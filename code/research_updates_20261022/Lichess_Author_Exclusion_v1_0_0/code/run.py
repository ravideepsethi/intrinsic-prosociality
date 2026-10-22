#!/usr/bin/env python3
"""Build a new author-excluded main sample and reusable exclusion authority."""
from __future__ import annotations
import argparse,concurrent.futures as cf,multiprocessing as mp,os,platform,shutil,sys,time,traceback,zipfile
from io_tools import *
from exclusion import *

CORE='derived/replication/analysis_panel_24m_sf100k'
MAIN='derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
WORK='derived/replication/author_exclusion_v100_PRIVATE'
CORE_RECEIPT='8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7'

def verify_package():
    p=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        expected,rel=line.split('  ',1);f=PACKAGE/rel
        if not f.resolve().is_relative_to(PACKAGE.resolve()) or sha(f)!=expected:raise RuntimeError('Package checksum mismatch: '+rel)
    return sha(p)

def inventory(project):
    project=Path(project);items=[];missing=[]
    p=project/CORE/'_SUCCESS.json'
    if sha(p)!=CORE_RECEIPT:raise RuntimeError('Stage07 receipt differs from the reviewed authority')
    core=read(p)
    for r in core['monthly_outputs']:
        path=project/CORE/f'month={r["month"]}'/'analysis_panel.parquet'
        items.append(dict(family='core_24m',month=r['month'],path=str(path),sha256=r['output_sha256'],rows=r['rows']))
    ref=read(PACKAGE/'authority/pool_main.json');live=read(project/MAIN/'_SUCCESS.json')
    for k in ('status','main_predicate','contract_sha256','code_sha256','observed_screen_certified','literal_immediate_rematches_certified'):
        if live.get(k)!=ref[k]:raise RuntimeError('Main-sample authority differs: '+k)
    if live.get('report_zip_sha256')!=ref['report_sha256']:raise RuntimeError('Main-sample report differs')
    live_months={r['month']:r for r in live['panel_outputs']}
    if len(live_months)!=len(live['panel_outputs']):raise RuntimeError('Duplicate main authority month')
    for r in ref['panel_outputs']:
        for k in ('rows','relative_path','size_bytes','sha256'):
            if live_months.get(r['month'],{}).get(k)!=r[k]:raise RuntimeError('Monthly main-sample authority differs')
        path=project/MAIN/r['relative_path']
        items.append(dict(family='main_24m',month=r['month'],path=str(path),sha256=r['sha256'],rows=r['rows']))
    for family in ('core_24m','main_24m'):
        months=[r['month'] for r in items if r['family']==family]
        if sorted(months)!=[str(m) for m in pd.period_range('2023-11','2025-10',freq='M')]:raise RuntimeError('Missing/duplicate certified month')
    # These are the exact completed SF100k extension roots used by the color
    # producer, not a recursive scan of arbitrary derived data.
    for month in ('2023-09','2023-10','2025-11','2025-12','2026-01','2026-02','2026-03','2026-04'):
        label=('stockfish100k_historical_reuse' if month in ('2023-10','2025-11','2025-12','2026-02') else
               'stockfish100k_extension_new_api_2026_04' if month=='2026-04' else 'stockfish100k_extension_new_api')
        paths=sorted((project/'derived/replication_36m'/label/f'month={month}').glob('part_*.parquet'))
        if not paths:missing.append(dict(month=month,status='EXTENSION_NOT_FOUND'));continue
        for path in paths:
            rp=path.with_suffix('.done.json')
            if not rp.is_file():raise RuntimeError('Extension part lacks completed SF receipt: '+month+'/'+path.name)
            r=read(rp)
            if r.get('error_rows')!=0:raise RuntimeError('Extension engine part has errors')
            items.append(dict(family='extension',month=month,path=str(path),sha256=r['part_sha256'],rows=r['rows']))
    return items,missing

def id_columns(path,pair):
    schema=pq.ParquetFile(path).schema_arrow;types={f.name:f.type for f in schema}
    options=(('white_id','black_id'),('white_user_id','black_user_id')) if pair[0].startswith(('white','api_white')) else (
        ('chooser_user_id','disconnected_user_id'),('chooser','recipient'),('chooser_user_id','opponent_user_id'))
    for a,b in options:
        if all(n in types and pa.types.is_integer(types[n]) for n in (a,b)):return (a,b)
    return (None,None)

def audit_file(job):
    item,work,code=job;work=Path(work);path=Path(item['path'])
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    evidence=authenticate(path,item['sha256'],work,item['rows'])
    key=digest(dict(code=code,policy=policy_sha(),input=evidence,family=item['family'],month=item['month']))
    folder=work/'files'/key;done=folder/'_DONE.json'
    if done.exists():
        result=read(done)
        for record in result['files']:verify_record(record)
        log(item['family']+'/'+item['month']+'/'+path.name+': reused')
        return result
    folder.mkdir(parents=True,exist_ok=True);pair=username_pair(path);ids=id_columns(path,pair)
    c=connect(folder/'spill')
    try:
        c.execute('CREATE VIEW s AS SELECT * FROM '+scan(path))
        names=[normalized(n) for n in pair];hits=name_hits(pair);excluded='('+hits[0]+' OR '+hits[1]+')'
        fields=set(pq.ParquetFile(path).schema_arrow.names)
        outcome=next((x for x in ('outcome_kind_draw','kind_draw','grant','y') if x in fields),None)
        if not outcome:raise RuntimeError('Missing grant outcome in input opportunity panel')
        y='CAST(s.'+ident(outcome)+' AS BIGINT)'
        if c.execute(f'SELECT count(*) FROM s WHERE game_id IS NULL OR {y} IS NULL OR {y} NOT IN (0,1)').fetchone()[0]:
            raise RuntimeError('Invalid game identity or grant outcome')
        bad=c.execute('SELECT count(*) FROM s WHERE '+ ' OR '.join(f'{n} IS NULL OR {n}=\'\'' for n in names)).fetchone()[0]
        if bad:raise RuntimeError('Player identity is missing; exclusion cannot be verified: '+item['family']+'/'+item['month'])
        n,grants,left,right,both,removed,removed_grants=c.execute(f'''SELECT count(*),coalesce(sum({y}),0),
            count(*) FILTER(WHERE {hits[0]}),count(*) FILTER(WHERE {hits[1]}),
            count(*) FILTER(WHERE {hits[0]} AND {hits[1]}),count(*) FILTER(WHERE {excluded}),
            coalesce(sum({y}) FILTER(WHERE {excluded}),0) FROM s''').fetchone()
        if n!=item['rows'] or removed!=left+right-both:raise RuntimeError('Exclusion count conservation failed')
        part=folder/'excluded_games_PRIVATE.parquet'
        copy(c,f'SELECT game_id,{lit(item["month"])} AS month FROM s WHERE {excluded}',part)
        if c.execute(f'SELECT count(*)-count(DISTINCT game_id) FROM {scan(part)}').fetchone()[0]:raise RuntimeError('Duplicate excluded game identity')
        id_observations=[];by_account=[]
        roles=('white','black') if pair[0].startswith(('white','api_white')) else ('chooser','opponent')
        for side in range(2):
            idexpr='CAST(s.'+ident(ids[side])+' AS BIGINT)' if ids[side] else 'NULL::BIGINT'
            rows=c.execute(f'''SELECT {names[side]} AS username,{idexpr} AS user_id,count(*) AS rows,
                sum({y}) AS grants FROM s WHERE {hits[side]} GROUP BY ALL ORDER BY 1,2''').fetchall()
            for username,user_id,count,yg in rows:
                if user_id is not None:id_observations.append(dict(username=username,user_id=int(user_id)))
                by_account.append(dict(username=username,role=roles[side],rows=int(count),grants=int(yg)))
        main_record=None
        if item['family']=='main_24m':
            if removed:
                out=folder/'author_free_main.parquet'
                if shutil.disk_usage(folder).free<max(2*path.stat().st_size,2*1024**3):raise RuntimeError('Insufficient space for the filtered main-sample part')
                kept=copy(c,'SELECT * FROM s WHERE '+names_keep_sql(pair),out)
                if kept!=n-removed:raise RuntimeError('Filtered output count differs')
                c.execute('CREATE VIEW filtered AS SELECT * FROM '+scan(out))
                bad=c.execute('SELECT count(*) FROM filtered s WHERE '+excluded).fetchone()[0]
                if bad:raise RuntimeError('Author survived output exclusion')
                if pq.ParquetFile(out).schema_arrow.names!=pq.ParquetFile(path).schema_arrow.names:raise RuntimeError('Filtered columns changed')
                main_record=file_record(out)
            else:
                # The dataset manifest reuses this immutable author-free source
                # file directly. No pointless full-width rewrite is needed.
                main_record=dict(path=str(path.resolve()),sha256=evidence['sha256'],bytes=path.stat().st_size,rows=n)
        if stamp(path)!=evidence['fingerprint']:raise RuntimeError('Source changed while filtering')
        counterparts=c.execute(f'''SELECT count(*) FROM (
            SELECT {names[1]} username FROM s WHERE {hits[0]} AND NOT {hits[1]}
            UNION SELECT {names[0]} username FROM s WHERE {hits[1]} AND NOT {hits[0]})''').fetchone()[0]
        summary=dict(family=item['family'],month=item['month'],input_rows=int(n),input_grants=int(grants),
            author_left_rows=int(left),author_right_rows=int(right),author_both_rows=int(both),
            removed_rows=int(removed),removed_grants=int(removed_grants),kept_rows=int(n-removed),kept_grants=int(grants-removed_grants),
            distinct_other_accounts_in_file=int(counterparts),
            left_role=roles[0],right_role=roles[1])
        files=[file_record(part)]+([main_record] if main_record else [])
        result=dict(key=key,input=evidence,summary=summary,by_account=by_account,username_pair=list(pair),
            id_observations=id_observations,excluded_games=str(part),main_output=main_record,files=files)
        write(done,result);log(f'{item["family"]}/{item["month"]}/{path.name}: {removed:,} excluded; {n-removed:,} retained')
        return result
    finally:c.close();shutil.rmtree(folder/'spill',ignore_errors=True)

def resolve_ids(project,results,work):
    observations={name:set() for name in AUTHORS};evidence=[]
    for r in results:
        if r['summary']['family'] in ('core_24m','main_24m'):
            for x in r['id_observations']:observations[x['username']].add(x['user_id'])
    root=Path(project)/'derived/glicko2_replay/user_dictionary_v1'
    # Explicitly typed dictionary files only. Never guess an ID from row order,
    # a username hash, an API numeric-looking string, or a different namespace.
    c=connect(Path(work)/'dictionary_spill')
    try:
        for p in sorted(root.rglob('*.parquet')) if root.exists() else []:
            schema=pq.ParquetFile(p).schema_arrow;types={f.name:f.type for f in schema}
            if 'user_id' not in types or not pa.types.is_integer(types['user_id']):continue
            name=next((n for n in ('username_norm','username','user_name','lichess_id','name') if n in types and is_name_type(types[n])),None)
            if name is None:continue
            before=stamp(p)
            rows=c.execute('SELECT '+normalized(name)+' AS username,s.user_id FROM '+scan(p)+' s WHERE '+normalized(name)+' IN ('+','.join(lit(n) for n in AUTHORS)+')').fetchall()
            if stamp(p)!=before:raise RuntimeError('User dictionary changed during lookup')
            if rows:
                e=authenticate(p,None,work);evidence.append(e)
                for username,uid in rows:observations[username].add(int(uid))
    finally:c.close()
    for name,values in observations.items():
        if len(values)>1:raise RuntimeError('Author username maps to multiple numeric IDs: '+name)
    resolved={n:next(iter(v)) for n,v in observations.items() if v}
    if len(set(resolved.values()))!=len(resolved) or any(v<0 for v in resolved.values()):raise RuntimeError('Conflicting author numeric IDs')
    return dict(author_ids=resolved,unresolved_usernames=[n for n in AUTHORS if n not in resolved],dictionary_evidence=evidence,
        namespace='existing glicko2_replay global user_id; observed names cross-checked against available dictionary')

def create_views(results,game_index,work):
    dest=Path(work)/'author_free_views.duckdb';tmp=dest.with_name(dest.name+'.partial_'+uuid.uuid4().hex)
    c=duckdb.connect(str(tmp))
    try:
        for family in sorted({r['summary']['family'] for r in results}):
            parts=[]
            for r in results:
                if r['summary']['family']!=family:continue
                p=r['main_output']['path'] if family=='main_24m' else r['input']['path']
                parts.append('SELECT * FROM '+scan(p)+' s WHERE '+names_keep_sql(r['username_pair']))
            c.execute('CREATE VIEW '+ident(family)+' AS '+' UNION ALL BY NAME '.join(parts))
        c.execute('CREATE VIEW excluded_games AS SELECT * FROM '+scan(game_index))
        c.execute('CHECKPOINT')
    finally:c.close()
    os.replace(tmp,dest);return dest

def impact_audit(project,game_index,work):
    """Read only specific existing compact targets; never modify running jobs."""
    project=Path(project);paths=[]
    color=project/'derived/replication_36m/color_matched_cohort_v100_PRIVATE'
    if (color/'matched_all_states.parquet').is_file():paths.append(('color_matched',color/'matched_all_states.parquet'))
    mech=project/'derived/replication/mechanism_separation_v100_PRIVATE/analysis'
    paths += [('mechanism_pre',p) for p in sorted(mech.glob('*.parquet'))]
    run=project/'output/tenure_responsibility_v100/c539ba215e708b22/PRIVATE'
    if (run/'trajectory_targets.parquet').is_file():paths.append(('A2_frozen_targets',run/'trajectory_targets.parquet'))
    c=connect(Path(work)/'impact_spill');rows=[]
    try:
        c.execute('CREATE VIEW excluded AS SELECT game_id FROM '+scan(game_index))
        for label,p in paths:
            before=stamp(p)
            n,k=c.execute('SELECT count(*),count(*) FILTER(WHERE e.game_id IS NOT NULL) FROM '+scan(p)+' s LEFT JOIN excluded e USING(game_id)').fetchone()
            if stamp(p)!=before:raise RuntimeError('Compact analysis target changed during impact audit')
            rows.append(dict(analysis=label,file=p.name,input_rows=n,direct_author_games=k,action='REFRESH_AFTER_FILTER' if k else 'NO_DIRECT_GAME_HITS; CHECK_DERIVED_HISTORIES'))
        return rows
    finally:c.close()

def bundle(report,desktop):
    write(report/'RESULT_MANIFEST.json',dict(files=[dict(name=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in sorted(report.iterdir()) if p.is_file()]))
    dest=Path(desktop)/(report.name+'.zip')
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,report.name+'/'+p.name)
    dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_RESULT '+str(dest));log('UPLOAD_RESULT '+str(dest)+'.sha256')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10)
    a=p.parse_args(argv)
    if not 1<=a.workers<=10:p.error('Use 1–10 workers')
    if not a.project.is_dir() or not a.desktop.is_dir():p.error('Project and Desktop result directories must exist')
    code=verify_package();start=time.monotonic();project=a.project.resolve();work=project/WORK
    report=project/'output/author_exclusion_v100'/('AUTHOR_EXCLUSION_RESULT_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    report.mkdir(parents=True);status=dict(status='STARTED',code_manifest_sha256=code,policy_sha256=policy_sha())
    workers=min(a.workers,4)
    write(report/'ENVIRONMENT.json',dict(python=sys.version,platform=platform.platform(),
        pandas=pd.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__,workers=workers,
        duckdb_threads_per_worker=1,duckdb_memory_limit_per_worker='768MB'))
    try:
        with lock(work/'run.lock'):
            write(work/'AUTHOR_EXCLUSION.json',POLICY)
            items,missing=inventory(project);write(work/'INPUT_INVENTORY_PRIVATE.json',dict(files=items,missing_extension=missing))
            table(missing,report/'missing_extension_months');status['phase']='audit_and_main_filter'
            results=[]
            pa.set_cpu_count(1);pa.set_io_thread_count(1)
            with heartbeat('Checking existing panels and excluding author games'),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
                futures=[pool.submit(audit_file,(item,str(work),code)) for item in items]
                for f in cf.as_completed(futures):
                    results.append(f.result());log(f'Files completed or reused: {len(results)}/{len(items)}')
            results.sort(key=lambda r:(r['summary']['family'],r['summary']['month'],r['input']['path']))
            status['phase']='identity_and_index'
            ids=resolve_ids(project,results,work);write(work/'AUTHOR_IDS_PRIVATE.json',ids)
            c=connect(work/'index_spill')
            try:
                index=work/'excluded_game_ids_PRIVATE.parquet'
                copy(c,'SELECT DISTINCT game_id,month FROM '+scan([r['excluded_games'] for r in results]),index)
                if c.execute('SELECT count(*)-count(DISTINCT game_id) FROM '+scan(index)).fetchone()[0]:raise RuntimeError('Excluded game has inconsistent months')
            finally:c.close()
            views=create_views(results,index,work)
            main=[dict(month=r['summary']['month'],**r['main_output']) for r in results if r['summary']['family']=='main_24m']
            manifest=dict(contract='AUTHOR_EXCLUDED_MAIN_24M_V1',policy=POLICY,policy_sha256=policy_sha(),
                package_manifest_sha256=code,
                input_main_report_sha256=read(PACKAGE/'authority/pool_main.json')['report_sha256'],
                datasets=dict(main_24m=main),excluded_games=file_record(index),author_id_resolution=ids,
                audited_inputs=[dict(family=r['summary']['family'],month=r['summary']['month'],**r['input']) for r in results],
                views=file_record(views),missing_extension_months=missing,
                analytical_results_reestimated=False,raw_history_preserved=True,
                raw_game_chronology_exclusion=False,rating_replays=0,stockfish_searches=0,API_requests=0)
            table([r['summary'] for r in results],report/'file_counts')
            counts=pd.DataFrame([r['summary'] for r in results]).drop(columns=['distinct_other_accounts_in_file']).groupby(['family','month'],as_index=False).sum(numeric_only=True)
            table(counts.to_dict('records'),report/'monthly_counts')
            table([dict(family=r['summary']['family'],month=r['summary']['month'],**v) for r in results for v in r['by_account']],report/'author_role_counts')
            status['phase']='impact_audit'
            with heartbeat('Checking compact analysis targets'):impact=impact_audit(project,index,work)
            table(impact,report/'analysis_impact')
            # Publish the ready manifest only after the audit has completed.
            write(work/'AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json',manifest)
            status.update(status='AUTHOR_EXCLUDED_MAIN_READY_ESTIMATES_PENDING',phase='finished',
                main_input_rows=int(counts[counts.family.eq('main_24m')].input_rows.sum()),
                main_removed_rows=int(counts[counts.family.eq('main_24m')].removed_rows.sum()),
                main_removed_grants=int(counts[counts.family.eq('main_24m')].removed_grants.sum()),
                main_kept_rows=int(counts[counts.family.eq('main_24m')].kept_rows.sum()),
                numeric_mapping_complete=not ids['unresolved_usernames'],unresolved_usernames=ids['unresolved_usernames'],
                missing_extension_months=missing,raw_history_preserved=True,API_requests=0,rating_replays=0,stockfish_searches=0,
                analytical_results_reestimated=False,ready_manifest=str(work/'AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json'))
    except Exception as e:
        write(work/'errors'/(report.name+'_PRIVATE.json'),dict(error=str(e),traceback=traceback.format_exc()))
        status.update(status='INCOMPLETE_REVIEW_REQUIRED',error_type=type(e).__name__,error=str(e));log(str(e))
    status['elapsed_seconds']=time.monotonic()-start;write(report/'SUMMARY.json',status)
    shutil.copy2(PACKAGE/'AUTHOR_EXCLUSION.json',report/'AUTHOR_EXCLUSION.json')
    shutil.copy2(PACKAGE/'DOWNSTREAM_REQUIREMENTS.md',report/'DOWNSTREAM_REQUIREMENTS.md')
    bundle(report,a.desktop)
    return 0 if status['status']=='AUTHOR_EXCLUDED_MAIN_READY_ESTIMATES_PENDING' else 1

if __name__=='__main__':raise SystemExit(main())
