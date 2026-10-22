"""Frozen main panel and exact author exclusion; no source modifications."""
from common import *
from exclusion import AUTHORS, POLICY, username_pair, names_keep_sql, normalized, is_name_type

def sources(project):
    authority=read(ROOT/'authority/pool_main.json')
    base=Path(project)/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    live=read(base/'_SUCCESS.json')
    for k in ('status','main_predicate','contract_sha256','code_sha256','observed_screen_certified','literal_immediate_rematches_certified'):
        if live.get(k)!=authority[k]:raise RuntimeError('Main-sample authority differs: '+k)
    if live.get('report_zip_sha256')!=authority['report_sha256']:raise RuntimeError('Main report differs')
    by={r['month']:r for r in live['panel_outputs']}
    if len(by)!=len(live['panel_outputs']) or sorted(by)!=list(MONTHS):raise RuntimeError('Main month inventory differs')
    result=[]
    for r in authority['panel_outputs']:
        for k in ('rows','relative_path','size_bytes','sha256'):
            if by[r['month']][k]!=r[k]:raise RuntimeError('Monthly main authority differs')
        result.append(dict(**r,path=str(base/r['relative_path'])))
    return result

def author_ids(project,work):
    observations={n:set() for n in AUTHORS};evidence=[]
    existing=Path(project)/'derived/replication/author_exclusion_v100_PRIVATE/AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json'
    if existing.exists():
        d=read(existing)
        if d.get('policy')==POLICY and d.get('contract')=='AUTHOR_EXCLUDED_MAIN_24M_V1':
            for name,uid in d.get('author_id_resolution',{}).get('author_ids',{}).items():
                if name in observations:observations[name].add(int(uid))
            evidence.append(record(existing))
    # Resolve missing accounts from the explicit typed global dictionary.
    if any(not x for x in observations.values()):
        c=connect(Path(work)/'tmp/dictionary')
        try:
            root=Path(project)/'derived/glicko2_replay/user_dictionary_v1'
            for p in sorted(root.rglob('*.parquet')):
                types={f.name:f.type for f in pq.ParquetFile(p).schema_arrow}
                if 'user_id' not in types or not pa.types.is_integer(types['user_id']):continue
                name=next((x for x in ('username_norm','username','user_name','lichess_id','name') if x in types and is_name_type(types[x])),None)
                if not name:continue
                norm=normalized(name)
                rows=c.execute(f'SELECT {norm},s.user_id FROM {scan(p)} s WHERE {norm} IN ({",".join(q(n) for n in AUTHORS)})').fetchall()
                if rows:
                    evidence.append(authenticate(p,work,None))
                    for n,uid in rows:observations[n].add(int(uid))
        finally:c.close()
    if any(len(x)!=1 for x in observations.values()):
        raise RuntimeError('Both author IDs must resolve uniquely in the existing global dictionary. Found: '+str(observations))
    result={n:next(iter(x)) for n,x in observations.items()}
    if len(set(result.values()))!=2 or min(result.values())<0:raise RuntimeError('Conflicting author IDs')
    write(Path(work)/'author_ids_PRIVATE.json',dict(author_ids=result,evidence=evidence));return result

def prepare_month(job):
    rec,work,ids,memory=job;work=Path(work);source=Path(rec['path']);month=rec['month']
    evidence=authenticate(source,work,rec['sha256'],rec['rows'],rec['size_bytes'])
    out=work/'targets'/f'{month}.parquet';key=digest(dict(input=evidence,ids=ids,version=VERSION))
    if reusable(out,key):return str(out)
    pair=username_pair(source);c=connect(work/'tmp'/('prepare_'+month),1,memory)
    try:
        c.execute('CREATE VIEW s AS SELECT * FROM '+scan(source))
        n1,n2=(normalized(x) for x in pair);keep=names_keep_sql(pair)
        if c.execute(f"SELECT count(*) FROM s WHERE {n1} IS NULL OR {n1}='' OR {n2} IS NULL OR {n2}=''").fetchone()[0]:
            raise RuntimeError('Missing player names prevent exact exclusion')
        if pair[0].startswith(('white','api_white')):
            left="CASE chooser_color WHEN 'white' THEN chooser_user_id ELSE disconnected_user_id END"
            right="CASE chooser_color WHEN 'black' THEN chooser_user_id ELSE disconnected_user_id END"
        else:left,right='chooser_user_id','disconnected_user_id'
        for name,uid in ids.items():
            for norm,num in ((n1,left),(n2,right)):
                bad=c.execute(f'SELECT count(*) FROM s WHERE ({norm}={q(name)}) IS DISTINCT FROM ({num}={uid})').fetchone()[0]
                if bad:raise RuntimeError('Name/numeric namespace mismatch for author exclusion')
        eligible='engine_eval_cp_disconnected>=-100 AND lower(api_speed) IN ('+','.join(q(s) for s in SPEEDS)+')'
        counts=c.execute(f'''SELECT count(*) input_rows,count(*) FILTER(WHERE NOT ({keep})) author_removed,
            count(*) FILTER(WHERE {keep}) author_free_rows,
            count(*) FILTER(WHERE {keep} AND engine_eval_cp_disconnected>=-100) competitive_all_speeds,
            count(*) FILTER(WHERE {keep} AND {eligible}) competitive_supported,
            count(*) FILTER(WHERE {keep} AND engine_eval_cp_disconnected IS NULL) missing_engine_eval FROM s''').df().iloc[0].to_dict()
        sql=f'''SELECT game_id,chooser_user_id::BIGINT user_id,disconnected_user_id::BIGINT opponent_id,
            api_created_at_ms::BIGINT t,lower(api_speed) speed,chooser_color color,
            chooser_elo::DOUBLE rating,disconnected_elo::DOUBLE opponent_rating,
            chooser_pre_rd_v2::DOUBLE rd,outcome_kind_draw::TINYINT y,
            chooser_draw_payoff_v2::DOUBLE rg,chooser_win_payoff_v2::DOUBLE rc,
            chooser_win_premium_v2::DOUBLE ki,{q(month)} AS month
            FROM s WHERE {keep} AND {eligible}'''
        copy(c,sql,out)
        n,u,bad,err=c.execute(f'''SELECT count(*),count(DISTINCT game_id),count(*) FILTER(WHERE
            game_id IS NULL OR user_id IS NULL OR opponent_id IS NULL OR user_id=opponent_id OR user_id<0 OR opponent_id<0
            OR t IS NULL OR t<=0 OR color IS NULL OR color NOT IN ('white','black') OR y IS NULL OR y NOT IN (0,1)
            OR rating IS NULL OR opponent_rating IS NULL OR rd IS NULL OR rg IS NULL OR rc IS NULL OR ki IS NULL
            OR NOT isfinite(rating+opponent_rating+rd+rg+rc+ki) OR rating<=0 OR opponent_rating<=0 OR rd<=0 OR ki<=0),max(abs(ki-(rc-rg))) FROM {scan(out)}''').fetchone()
        if n!=u or bad or (err or 0)>1e-6:raise RuntimeError('Invalid opportunity identities/payoffs: '+month)
        finished(out,key,month=month,counts=counts,rows=n,maximum_payoff_identity_error=err,source=evidence)
        log(f'{month}: {n:,} competitive opportunities prepared')
    finally:c.close()
    return str(out)

def needed(work,files,threads,memory):
    out=Path(work)/'needed_users.parquet';key=digest([record(p) for p in files])
    if reusable(out,key):return out
    c=connect(Path(work)/'tmp/needed',threads,memory)
    try:copy(c,f'SELECT DISTINCT speed,user_id FROM {scan(files)}',out)
    finally:c.close()
    finished(out,key);return out
