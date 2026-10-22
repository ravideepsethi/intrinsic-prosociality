"""Reuse existing candidate/API files; expected runtime 5-20 min, up to 3 workers.
Missing historical denominator files remain explicitly unidentified. No network.
"""
from __future__ import annotations
from io_tools import *

def material_sql(fen):
    board=f"split_part({fen},' ',1)";terms=[]
    for piece,value in [('p',1),('n',3),('b',3),('r',5),('q',9)]:
        terms.append(f"{value}*((length({board})-length(replace({board},{q(piece.upper())},'')))-(length({board})-length(replace({board},{q(piece)},''))))")
    return '('+'+'.join(terms)+')'

def resolve_modern(project,month):
    project=Path(project);candidate=project/'derived/replication/pgn_timeforfeit_candidates'/f'month={month}'/'api_target_candidates_ge5s_or_missing.parquet'
    found=[]
    for root in ['derived/replication_36m/api_timeout_enrichment_extension','derived/replication/api_timeout_enrichment']:
        p=project/root/f'month={month}';success=p/'_SUCCESS.json';files=sorted((p/'responses').glob('unit-*.parquet'))
        if files and success.is_file() and read_json(success).get('final_ok') is True:found.append((p,files))
    if not candidate.is_file() or len(found)!=1:
        return None,dict(month=month,status='UNRESOLVED_COMPLETE_CANDIDATE_API_PAIR',candidate_path=str(candidate),
             candidate_exists=candidate.is_file(),complete_api_roots=[str(x[0]) for x in found])
    root,files=found[0];return (candidate,root,files),None

def authenticate_api(candidate,root,files,work,month):
    success=read_json(root/'_SUCCESS.json');source=read_json(candidate.parent/'_SUCCESS.json')
    if source.get('final_ok') is not True:raise RuntimeError('Incomplete Stage01 '+month)
    if success.get('month')!=month or not success.get('production'):raise RuntimeError('Wrong API month/production flag')
    n=int(success['source_rows'])
    for k in ('selected_rows','requested_ids','returned_unique_ids'):
        if int(success.get(k,-1))!=n:raise RuntimeError('Incomplete API field '+k)
    if int(success.get('missing_ids',-1)) or len(files)!=int(success['unit_count']):raise RuntimeError('Incomplete API ID/file coverage')
    cps={int(x['unit_index']):x['sha256'] for x in success.get('unit_checkpoint_sha256',[])}
    if len(cps)!=len(files):raise RuntimeError('API unit receipt inventory incomplete')
    for i,p in enumerate(files):
        checkpoint=root/'_checkpoints'/f'unit-{i:05d}.success.json'
        if sha(checkpoint)!=cps[i]:raise RuntimeError('API checkpoint hash differs')
        ck=read_json(checkpoint)
        if ck.get('final_ok') is not True or ck.get('unit_index')!=i or ck.get('missing_ids')!=0:raise RuntimeError('API checkpoint not complete')
        compact=ck['artifacts']['compact'];verify_record(p,compact,work)
    return dict(month=month,n=n,api_success_sha256=sha(root/'_SUCCESS.json'),
       candidate_fingerprint=stamp(candidate),candidate_sha256=sha(candidate),
       source_receipt_sha256=sha(candidate.parent/'_SUCCESS.json'),api_files=[stamp(p) for p in files],
       expected_status_counts=success.get('status_counts',{}))

def grace_month(task):
    project,first,work,month,memory_mb=task;project,first,work=map(Path,(project,first,work))
    resolved,missing=resolve_modern(project,month)
    if missing:return missing
    candidate,root,files=resolved;dest=work/'grace'/f'month={month}'/'daily.parquet'
    # Include authoritative metadata before allowing restart reuse.
    ins=[stamp(candidate),stamp(candidate.parent/'_SUCCESS.json'),stamp(root/'_SUCCESS.json')]+[stamp(p) for p in files]
    base=first/'base'/f'month={month}'/'opportunities.parquet';br=read_json(base.with_suffix('.json'))
    verify_record(base,br['output'],work);ins.append(stamp(base))
    key=digest(dict(version=VERSION,inputs=ins))
    old=cached(dest,key)
    if old and (dest.parent/'reconciliation.json').is_file():
        verify_record(dest.parent/'hourly.parquet',old['hourly'],work)
        if sha(dest.parent/'reconciliation.json')!=old['reconciliation_sha256']:raise RuntimeError('Grace reconciliation cache changed')
        return old
    evidence=authenticate_api(candidate,root,files,work,month)
    c=connection(work/'tmp'/('grace_'+month),2,memory_mb)
    try:
        c.execute(f'CREATE VIEW cand AS SELECT * FROM {scan(candidate)}')
        c.execute(f'CREATE VIEW api AS SELECT * FROM {scan(files)}')
        for relation in ('cand','api'):
            n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM '+relation).fetchone()
            if (n,u)!=(evidence['n'],evidence['n']):raise RuntimeError('Candidate/API cardinality differs')
        if c.execute('SELECT count(*) FROM cand ANTI JOIN api USING(game_id)').fetchone()[0]:raise RuntimeError('Candidate/API keysets differ')
        status_counts=dict(c.execute('SELECT api_status,count(*) FROM api GROUP BY 1').fetchall())
        if status_counts!=evidence['expected_status_counts']:raise RuntimeError('API status counts differ from receipt')
        if set(status_counts)-{'timeout','outoftime'}:raise RuntimeError('Unexpected status in selected frame')
        sc=schema(candidate);ac=schema(files[0]);ts=time_expr(sc)
        if ts is None:raise RuntimeError('Candidate timestamp contract absent')
        status=choose(ac,['api_status','status'],'a');speed=choose(ac,['api_speed','speed'],'a')
        rated=choose(ac,['api_rated','rated'],'a');variant=choose(ac,['api_variant','variant'],'a')
        winner=choose(ac,['api_winner','winner'],'a');draw=choose(ac,['api_is_draw','is_draw'],'a')
        result=choose(sc,['result','pgn_result']);color=choose(sc,['candidate_chooser_color','chooser_color']);fen=choose(sc,['fen_after_last_move'])
        clock=finite_sql(choose(sc,['disconnected_clock_last_obs_s']));mat=material_sql(fen)
        c.execute(f"""CREATE TEMP TABLE joined AS SELECT cast(s.game_id AS VARCHAR) game_id,{ts} utc_ms,
          lower(trim(cast({speed} AS VARCHAR))) speed,lower(trim(cast({color} AS VARCHAR))) color,
          {status}::VARCHAR status,{rated}::BOOLEAN rated,{variant}::VARCHAR variant,{clock} disconnected_clock,
          {result}::VARCHAR result, {draw}::BOOLEAN api_draw,{winner}::VARCHAR api_winner,
          CASE WHEN {color}='white' THEN {mat} ELSE -{mat} END own_material_adv,
          {fen} IS NOT NULL AS material_known FROM cand s JOIN api a USING(game_id)""")
        bad=c.execute(f"SELECT count(*) FROM joined WHERE utc_ms IS NULL OR strftime(epoch_ms(utc_ms),'%Y-%m')<>{q(month)} OR color NOT IN ('white','black') OR speed NOT IN ({','.join(q(s) for s in SPEEDS)}) OR NOT coalesce((api_draw AND result='1/2-1/2') OR (NOT api_draw AND ((api_winner='white' AND result='1-0') OR (api_winner='black' AND result='0-1'))),false)").fetchone()[0]
        if bad:raise RuntimeError(f'{month}: {bad} timestamp/color/speed/result conflicts')
        c.execute(f"CREATE VIEW opportunities AS SELECT game_id,grant FROM {scan(base)}")
        c.execute("""CREATE VIEW eligible AS SELECT *,
          CASE WHEN NOT material_known THEN 'unknown' WHEN own_material_adv<=-3 THEN 'chooser_down_3plus' WHEN own_material_adv>=3 THEN 'chooser_up_3plus' ELSE 'within_2' END material_group
          FROM joined WHERE rated IS TRUE AND variant='standard' AND (disconnected_clock>=5 OR disconnected_clock IS NULL)""")
        c.execute("""CREATE VIEW marked AS SELECT e.*,b.game_id IS NOT NULL AS in_opportunity_panel,b.grant AS kind_draw
          FROM eligible e LEFT JOIN opportunities b USING(game_id)""")
        reconciliation=dict(c.execute("SELECT count(*) AS panel_rows FROM opportunities").fetchdf().iloc[0])
        for name,sql in {
          'active_resolutions':"SELECT count(*) FROM eligible WHERE status='timeout'",
          'active_missing_clock':"SELECT count(*) FROM eligible WHERE status='timeout' AND disconnected_clock IS NULL",
          'active_missing_clock_wins':"SELECT count(*) FROM eligible WHERE status='timeout' AND disconnected_clock IS NULL AND NOT api_draw",
          'missing_in_panel':"SELECT count(*) FROM marked WHERE status='timeout' AND NOT in_opportunity_panel",
          'panel_not_in_frame':"SELECT count(*) FROM opportunities ANTI JOIN (SELECT game_id FROM eligible WHERE status='timeout') e USING(game_id)",
          'rated_unknown':"SELECT count(*) FROM joined WHERE rated IS NULL",
          'excluded_casual':"SELECT count(*) FROM joined WHERE rated IS FALSE",
          'excluded_variant':"SELECT count(*) FROM joined WHERE variant IS DISTINCT FROM 'standard'",
          'timeout_draws':"SELECT count(*) FROM eligible WHERE status='timeout' AND api_draw",
          'kindness_draws':"SELECT coalesce(sum(kind_draw),0) FROM marked WHERE status='timeout'",
          'non_kind_timeout_draws':"SELECT count(*) FROM marked WHERE status='timeout' AND api_draw AND kind_draw=0"
        }.items():reconciliation[name]=int(c.execute(sql).fetchone()[0])
        reconciliation={k:int(v) for k,v in reconciliation.items()};write_json(dest.parent/'reconciliation.json',reconciliation)
        if reconciliation['missing_in_panel'] or reconciliation['panel_not_in_frame']:raise RuntimeError('Active resolution/panel ID sets differ; see reconciliation.json')
        c.execute("""CREATE VIEW frames AS SELECT *,'ge5_or_missing' AS clock_frame FROM marked
          UNION ALL SELECT *,'ge5_observed' FROM marked WHERE disconnected_clock>=5
          UNION ALL SELECT *,'missing_clock_only' FROM marked WHERE disconnected_clock IS NULL""")
        copy(c,"""SELECT date_trunc('day',epoch_ms(utc_ms)) AS day,speed,color,material_group,clock_frame,
          count(*) targeted_candidates,count(*) FILTER(WHERE status='timeout') active_resolutions,
          count(*) FILTER(WHERE status='outoftime') clock_expirations,
          count(*) FILTER(WHERE status='timeout' AND api_draw) timeout_draws,
          count(*) FILTER(WHERE status='timeout' AND NOT api_draw AND api_winner=color) chooser_wins,
          coalesce(sum(kind_draw) FILTER(WHERE status='timeout'),0) kindness_draws,
          count(*) FILTER(WHERE status='timeout' AND api_draw AND kind_draw=0) non_kind_timeout_draws
          FROM frames GROUP BY ALL""",dest)
        copy(c,"""SELECT (utc_ms//3600000)*3600000 hour_ms,speed,clock_frame,count(*) targeted_candidates,
          count(*) FILTER(WHERE status='timeout') targeted_timeouts FROM frames GROUP BY ALL""",dest.parent/'hourly.parquet')
        return commit(dest,key,month=month,status='TARGETED_FRAME_COMPLETE',evidence=evidence,reconciliation=reconciliation,
          hourly=receipt(dest.parent/'hourly.parquet'),reconciliation_sha256=sha(dest.parent/'reconciliation.json'),
          denominator='Rated standard PGN time-forfeit API candidates, separate clock frames; NOT platform-wide disconnections/timeouts')
    finally:c.close()

def complete_window_differences(df):
    """Do not turn a missing day into zero or a 2-day window into seven days."""
    records=[]
    if df.empty:return pd.DataFrame()
    keys=['speed','material_group','clock_frame']
    z=df.groupby(keys+['day'])[['targeted_candidates','active_resolutions']].sum().reset_index()
    for group,x in z.groupby(keys):
        x=x.set_index('day').sort_index()
        for t in pd.date_range('2026-01-20','2026-02-15',freq='D'):
            a=x.reindex(pd.date_range(t-pd.Timedelta(days=7),periods=7,freq='D'))
            b=x.reindex(pd.date_range(t,periods=7,freq='D'))
            na=int(a.targeted_candidates.notna().sum());nb=int(b.targeted_candidates.notna().sum())
            valid=na==7 and nb==7 and a.targeted_candidates.sum()>0 and b.targeted_candidates.sum()>0
            records.append(dict(zip(keys,group),day=t,before_days=na,after_days=nb,complete=valid,
              before_share=float(a.active_resolutions.sum()/a.targeted_candidates.sum()) if valid else None,
              after_share=float(b.active_resolutions.sum()/b.targeted_candidates.sum()) if valid else None,
              change_pp=float(100*(b.active_resolutions.sum()/b.targeted_candidates.sum()-a.active_resolutions.sum()/a.targeted_candidates.sum())) if valid else None))
    return pd.DataFrame(records)

def historical_inventory(project,report):
    """Trace existing February recut metadata only; no silent promotion to a denominator."""
    project,report=map(Path,(project,report));registered=read_json(PACKAGE/'authority/historical_sources.json')['months']['2026-02']
    sources=[];references=[];seen=set();documents=[]
    for spec in registered['files']:
        p=project/spec['relative_path'];sources.append(dict(path=str(p),exists=p.is_file(),expected_sha256=spec['sha256'],role='authenticated historical timeout-only recut'))
        if p.is_file():
            sources[-1].update(rows=pq.ParquetFile(p).metadata.num_rows,columns=sorted(schema(p)))
        root=p.parents[2]
        if root.is_dir():documents.extend(list(root.glob('*.json'))+list(root.glob('*/*.json'))+list(root.glob('*/*/*.json')))
    # Existing metadata inventories often name the older raw-response/candidate cache.
    output=project/'output'
    if output.is_dir():
        for directory in output.iterdir():
            if directory.is_dir() and any(k in directory.name.lower() for k in ('feb2026','feb_2026','2026-02','february','standardized_fair_ge100')):
                documents.extend(list(directory.glob('*.json'))+list(directory.glob('*/*.json')))
    def walk(x,origin):
        if isinstance(x,dict):
            for v in x.values():walk(v,origin)
        elif isinstance(x,list):
            for v in x:walk(v,origin)
        elif isinstance(x,str) and (x.endswith(('.parquet','.csv','.csv.gz','.ndjson','.ndjson.zst'))):
            p=Path(x)
            if not p.is_absolute():return
            if x in seen:return
            seen.add(x);row=dict(path=x,mentioned_by=str(origin),exists=p.is_file(),status='LINEAGE_CANDIDATE_NOT_A_CERTIFIED_DENOMINATOR')
            if p.is_file() and p.suffix=='.parquet':
                try:row.update(rows=pq.ParquetFile(p).metadata.num_rows,columns=sorted(schema(p)))
                except Exception as exc:row['metadata_error']=str(exc)
            references.append(row)
    for p in sorted(set(documents))[:300]:
        if p.stat().st_size>4*1024**2:continue
        try:walk(read_json(p),p)
        except (ValueError,OSError):continue
    result=dict(known_sources=sources,metadata_files_considered=len(set(documents)),referenced_candidates=references,
        status='HISTORICAL_LINEAGE_INVENTORY',interpretation='Timeout-only recut can support active-outcome descriptions, never the active-resolution denominator. Candidate references need producer/frame authentication before use.')
    write_json(report/'FEBRUARY_LINEAGE.json',result);return result

def finalize_grace(first,work,report,results,threads,memory_mb):
    first,work,report=map(Path,(first,work,report));paths=[Path(r['output']['path']) for r in results if r.get('status')=='TARGETED_FRAME_COMPLETE']
    c=connection(work/'tmp/grace_final',threads,memory_mb)
    try:
        if paths:
            export(c,f'SELECT * FROM {scan(paths)}',report/'grace_daily.parquet')
            data=pd.read_parquet(report/'grace_daily.parquet');d=complete_window_differences(data)
            frame(d,report/'grace_complete_window_diagnostics.parquet');d.to_csv(report/'grace_complete_window_diagnostics.csv',index=False)
            hours=[p.parent/'hourly.parquet' for p in paths]
            export(c,f'SELECT * FROM {scan(hours)}',report/'targeted_hourly.parquet')
        # February active-only outcomes are useful even when its full candidate frame is unavailable.
        bp=first/'base/month=2026-02/opportunities.parquet'
        if bp.is_file():
            verify_record(bp,read_json(bp.with_suffix('.json'))['output'],work)
            export(c,f"""SELECT date_trunc('day',epoch_ms(utc_ms)) AS day,speed,color,
              CASE WHEN cp>=-100 THEN 'competitive' WHEN cp<=-300 THEN 'clearly_losing' ELSE 'middle' END board_state,
              count(*) active_opportunities,sum(grant) kindness_draws,avg(grant)*100 kind_percent,
              count(*) FILTER(WHERE opp_clock IS NULL) missing_clock_n
              FROM {scan(bp)} GROUP BY ALL""",report/'february_active_only.parquet')
    finally:c.close()
    write_json(report/'GRACE_AND_IV_STATUS.json',dict(months=results,censoring_cutoff_utc=None,
       status='CENSORING_REQUIRES_SOURCE_AND_COMPLETE_GROUP_REVIEW',
       platform_wide_timeout_share='NOT_IDENTIFIED_BY_TARGETED_FRAME',
       exact_visibility='NOT_IDENTIFIED_NO_FRACTIONAL_RATING_STATE',
       iv='Not run: 90-day eligibility and incident control require the shared censor/denominator decisions.',
       january30='Issue-open date; support truncation scenarios do not certify a deployment date.',
       source='https://github.com/lichess-org/lila/issues/19256'))
