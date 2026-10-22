"""Read-only bindings to the completed run and its research sources."""
from cached_common import *
import csv
import concurrent.futures as cf

def metadata_for_month(path,month):
    parent=Path(path).parent
    if (parent/'empty_metadata.parquet').is_file():
        files=sorted((parent/'by_month'/('month='+month)).glob('*.parquet'))
        return list(map(str,files)) or [str(parent/'empty_metadata.parquet')]
    return [str(path)]

def coverage_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([job['ledger']]))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq(job['metadata']))
            # Upstream completeness and conflict checks must still agree at this join.
            ready="f.retrieval_disposition='LOCAL_POOL_METADATA_READY' AND NOT f.previous_frame"
            bad=c.execute('SELECT count(*) FROM f LEFT JOIN m USING(game_id) WHERE '+ready+
                " AND (m.game_id IS NULL OR ("+original_plan.readiness_sql()+") IS DISTINCT FROM 'CACHED_POOL_METADATA')").fetchone()[0]
            if bad:raise RuntimeError('Authenticated metadata readiness does not reproduce')
            c.execute('CREATE VIEW cached AS SELECT f.*,m.* EXCLUDE(game_id) FROM f JOIN m USING(game_id) WHERE '+ready)
            counts=c.execute('SELECT status,speed_partition,count(*) n FROM cached GROUP BY 1,2 ORDER BY 1,2').fetchall()
            n=c.execute('SELECT count(*),count(DISTINCT game_id) FROM cached').fetchone()
            if n[0]!=n[1]:raise RuntimeError('Duplicate cached metadata game')
            narrow='status IN ('+','.join(map(io.lit,sorted(core.NARROW)))+')'
            fields='''game_id,utc_ms AS archive_start_ms,anchor_ms,recipient_id,opponent_id,
              CASE WHEN recipient_color='white' THEN white_rating ELSE black_rating END AS recipient_rating,
              CASE WHEN recipient_color='white' THEN black_rating ELSE white_rating END AS opponent_rating,
              CASE WHEN recipient_color='white' THEN white_username ELSE black_username END AS recipient_username,
              CASE WHEN recipient_color='white' THEN black_username ELSE white_username END AS opponent_username,
              tc_base_s,tc_inc_s,status,n7_author_clean AS expected_n7'''
            nr=io.copy(c,'SELECT '+fields+','+str(core.MONTHS.index(job['month']))+'::BIGINT month_code FROM cached WHERE '+narrow+' ORDER BY game_id',tmp/'ordinary.parquet')
            info=dict(month=job['month'],cached_pool_rows=n[0],ordinary_rows=nr,
                      ending_counts=[dict(month=job['month'],status=s,speed=sp,rows=k) for s,sp,k in counts])
            io.js(tmp/'coverage.json',info);return info
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['ledger']]+job['metadata'])[1]

def research_inputs(project,workers):
    h=authors.authenticate(project,workers)
    expanded=project/EXPANDED_REL
    expanded_authority=io.load(VENDOR/'comparison_original/evidence/authority.json')
    io.checked(expanded/'report/_DONE.json',expanded_authority['expanded_receipt_sha256'])
    # Verify completed, configuration-bound inputs; numerical baseline reproduction is separate.
    for rel in ('prepared','comparison'):
        if io.complete(expanded/rel,EXPANDED_CONF) is None:raise RuntimeError('Missing expanded '+rel)
    comparison=expanded/'comparison/comparison.parquet'
    if pq.ParquetFile(comparison).metadata.num_rows!=1661563:raise RuntimeError('Original comparison size changed')
    stream=expanded/'prepared/selected_stream_90.parquet'
    if not stream.is_file():raise RuntimeError('Full pre-censoring exposure stream is missing')
    authority=io.load(PACKAGE/'evidence/chronology_authority.json')
    manifest=project/authority['chronology_manifest_relative']
    io.checked(manifest,authority['chronology_manifest_sha256'])
    with manifest.open() as f:records=list(csv.DictReader(f,delimiter='\t'))
    if len(records)!=852 or sum(int(r['rows']) for r in records)!=7763847245:
        raise RuntimeError('Canonical all-game coverage differs')
    chron=[]
    for r in records:
        path=relocate(project,r['path']);pf=pq.ParquetFile(path)
        if path.stat().st_size!=int(r['bytes']) or pf.metadata.num_rows!=int(r['rows']) or pf.metadata.num_row_groups!=int(r['row_groups']):
            raise RuntimeError('Chronology metadata differs: '+str(path))
        if not {'game_id','utc_ms','white_id','black_id'}<=set(pf.schema_arrow.names):raise RuntimeError('Chronology schema changed')
        times=[];ix=pf.schema_arrow.names.index('utc_ms')
        for rg in range(pf.metadata.num_row_groups):
            st=pf.metadata.row_group(rg).column(ix).statistics
            if st and st.has_min_max:times.append((st.min,st.max))
        minimum=min((v[0] for v in times),default=None) if len(times)==pf.metadata.num_row_groups else None
        chron.append(dict(path=str(path),file_index=int(r['file_index']),rows=int(r['rows']),signature=io.sig(path),minimum=minimum))
    main=io.load(PACKAGE/'evidence/main_panels.json');mainroot=relocate(project,main['private_output_root'])
    panels=[dict(path=str(io.child(mainroot,r['relative_path'])),sha256=r['sha256'],bytes=r['size_bytes'],rows=r['rows']) for r in main['panel_outputs']]
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(authors.checked_record,panels))
    if len(panels)!=24 or sum(r['rows'] for r in panels)!=41534331:raise RuntimeError('Wrong main-panel coverage')
    prior=io.load(VENDOR/'evidence/prior_authority.json')
    identity=project/'derived/replication/comparison_tests_v110_PRIVATE'/prior['comparison_run']/'identity'
    check=identity/'report/dictionary_check.json'
    io.checked(check,next(r['sha256'] for r in prior['comparison_public_files'] if r['file']=='dictionary_check.json'))
    r=io.load(identity/'_COMPLETE.json')
    if r['config_sha256']!=prior['comparison_config_sha256']:raise RuntimeError('Wrong dictionary receipt')
    rec=next(r for r in r['files'] if r['path']=='dictionary_binding_PRIVATE.json')
    binding=identity/rec['path'];io.checked(binding,rec['sha256'],rec['bytes'])
    directory=(project/'derived/glicko2_replay/user_dictionary_v1/user_dictionary_buckets').resolve()
    dictionary=[]
    for r in io.load(binding)['files']:
        path=relocate(project,r['path'])
        if directory in path.resolve().parents and path.suffix=='.parquet':dictionary.append(dict(r,path=str(path)))
    if not dictionary:raise RuntimeError('No bound global dictionary')
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(authors.checked_record,dictionary))
    h.update(comparison=str(comparison),stream=str(stream),chron=chron,panels=panels,
        dictionary=dictionary,dictionary_column=io.load(check)['selected_explicit_ID_column'],
        dictionary_total=io.load(check)['total_global_users'],
        expanded_receipts={r:io.sha(expanded/r/'_DONE.json') for r in ('prepared','comparison')},
        dictionary_binding_sha=io.sha(binding))
    return h

def identity_check(queries,inputs,root,conf,memory,workers):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,workers)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries]))
            c.execute('CREATE VIEW dictionary AS SELECT '+qident(inputs['dictionary_column'])+'::BIGINT account_id,username_norm historical_username FROM '+io.parq([r['path'] for r in inputs['dictionary']]))
            n,ids,names,lo,hi=c.execute('SELECT count(*),count(DISTINCT account_id),count(DISTINCT historical_username),min(account_id),max(account_id) FROM dictionary').fetchone()
            if n!=inputs['dictionary_total'] or ids!=n or names!=n or lo!=0 or hi!=n-1:raise RuntimeError('Global dictionary is not a complete bijection')
            c.execute('CREATE VIEW requirements AS SELECT recipient_id account_id,recipient_username username,previous_frame FROM q UNION SELECT opponent_id,opponent_username,previous_frame FROM q')
            bad=c.execute("SELECT count(*) FROM requirements r LEFT JOIN dictionary d USING(account_id) WHERE d.account_id IS NULL OR (r.username IS NULL AND NOT r.previous_frame) OR (r.username<>'ghost' AND lower(trim(r.username))<>d.historical_username)").fetchone()[0]
            if bad:raise RuntimeError(f'{bad} unresolved account mappings; models blocked, no rows silently deleted')
            n=io.copy(c,'SELECT * FROM dictionary SEMI JOIN (SELECT DISTINCT account_id FROM requirements) USING(account_id)',tmp/'lookup.parquet')
            ghosts=c.execute("SELECT count(*) FROM requirements WHERE username='ghost'").fetchone()[0]
            legacy=c.execute('SELECT count(*) FROM requirements WHERE previous_frame AND username IS NULL').fetchone()[0]
            return dict(required_IDs_resolved=n,API_ghost_labels=ghosts,global_dictionary_rows=ids,identity_conflicts=0,
                frozen_original_role_IDs_without_export_label=legacy,legacy_identity_authority='verified original row set and unchanged global dictionary; missing API labels not invented')
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[queries]+[r['path'] for r in inputs['dictionary']])
