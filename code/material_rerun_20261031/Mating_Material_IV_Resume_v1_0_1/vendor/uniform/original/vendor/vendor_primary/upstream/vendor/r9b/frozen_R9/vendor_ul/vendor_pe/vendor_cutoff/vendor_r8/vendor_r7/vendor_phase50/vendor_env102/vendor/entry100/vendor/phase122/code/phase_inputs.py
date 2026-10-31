"""Immutable 10% metadata and exact entry-label provenance; no live SQLite reads."""
from cached_common import *
import cached_inputs as prior
import legacy_schema

PHASE_RUN='aadab02f3e73'
PHASE_PACKAGE_SHA='4d59b0269dbf02963f6494485bd54e842bc245db4c54255aafa04f4a62de772f'

def authenticate_phase(a,up):
    root=a.project_root/PHASE_REL/PHASE_RUN
    definition=io.load(root/'config.json'); conf=io.cfgsha(definition)
    if conf[:12]!=PHASE_RUN or definition['package_sha256']!=PHASE_PACKAGE_SHA:
        raise RuntimeError('Expected the completed, reviewed 10% phase producer')
    if definition['upstream_plan']!=UPSTREAM_PLAN or definition['input_receipts']!=up['input_receipts']:
        raise RuntimeError('Phase input lineage does not match the authenticated local-first plan')
    plan=root/'plan'; result=root/'phase_results/10'; merged=result/'merged'
    for folder,cfg in ((plan,conf),(merged,io.cfgsha([conf,10])),
                      (root/'download/10/finished',io.cfgsha([conf,10,io.sha(plan/'targets_10.parquet')]))):
        if io.complete(folder,cfg) is None:raise RuntimeError('10% checkpoint is incomplete: '+str(folder))
    summary=io.load(result/'report/summary.json')
    if summary!=io.load(PACKAGE/'evidence/phase10_summary.json'):
        raise RuntimeError('10% report differs from the supplied, verified completed report')
    manifest=io.load(result/'ANALYSIS_INPUTS_PRIVATE.json')
    checks=dict(through_percent=10,fixed_denominator=up['ledgers'],
        additional_frame_selection_sql=selection_sql(10),upstream_manifest=up['manifest'],
        merged_candidate_metadata=str(merged/'metadata.parquet'),
        original_cached_metadata=up['manifest']['original_cached_metadata'],
        full_historical_and_prospective_anchor_stream_required=True,all_frame_rows_preserved=True,
        final_sample_and_rules_unchanged=True)
    for k,v in checks.items():
        if manifest.get(k)!=v:raise RuntimeError('10% analysis manifest mismatch: '+k)
    if summary['not_returned'] or summary['metadata_flags'] or summary['prior_nonreturn_gaps']:
        raise RuntimeError('This runner requires the reviewed, gap-free completed 10% sample')
    return dict(root=str(root),config_sha256=conf,summary=summary,
        metadata=str(merged/'metadata.parquet'),manifest_sha256=io.sha(result/'ANALYSIS_INPUTS_PRIVATE.json'),
        receipts={str(f.relative_to(root)):io.sha(f) for f in
            (plan/'_DONE.json',merged/'_DONE.json',root/'download/10/finished/_DONE.json')})

def coverage_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([job['ledger']])+' f WHERE '+selection_sql(10))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq(job['metadata']))
            readiness=original_plan.readiness_sql()
            c.execute("CREATE TEMP TABLE disposition AS SELECT f.game_id,CASE WHEN f.local_eligibility<>'POTENTIALLY_ELIGIBLE' THEN 'LOCAL_RULE_EXCLUSION' ELSE ("+readiness+") END AS disposition FROM f LEFT JOIN m USING(game_id)")
            counts=dict(c.execute('SELECT disposition,count(*) FROM disposition GROUP BY 1').fetchall())
            if sum(counts.values())!=c.execute('SELECT count(*) FROM f').fetchone()[0]:
                raise RuntimeError('Metadata join changed the selected frame denominator')
            unknown=sum(n for d,n in counts.items() if d not in ('LOCAL_RULE_EXCLUSION','CACHED_NONPOOL','CACHED_POOL_METADATA'))
            fields='''f.game_id,f.utc_ms AS archive_start_ms,m.anchor_ms,f.recipient_id,f.opponent_id,
              CASE WHEN f.recipient_color='white' THEN m.white_rating ELSE m.black_rating END AS recipient_rating,
              CASE WHEN f.recipient_color='white' THEN m.black_rating ELSE m.white_rating END AS opponent_rating,
              CASE WHEN f.recipient_color='white' THEN m.white_username ELSE m.black_username END AS recipient_username,
              CASE WHEN f.recipient_color='white' THEN m.black_username ELSE m.white_username END AS opponent_username,
              m.tc_base_s,m.tc_inc_s,m.status,f.n7_author_clean AS expected_n7'''
            c.execute('CREATE VIEW pool AS SELECT '+fields+',f.speed_partition,'+str(core.MONTHS.index(job['month']))+
                      "::BIGINT month_code FROM f JOIN m USING(game_id) JOIN disposition d ON f.game_id=d.game_id WHERE d.disposition='CACHED_POOL_METADATA'")
            n=io.copy(c,'SELECT * EXCLUDE(speed_partition) FROM pool ORDER BY game_id',tmp/'pool.parquet')
            if c.execute('SELECT count(DISTINCT game_id) FROM pool').fetchone()[0]!=n:raise RuntimeError('Duplicate game in 10% pool')
            endings=[dict(month=job['month'],status=s,speed=sp,rows=n) for s,sp,n in c.execute('SELECT status,speed_partition,count(*) FROM pool GROUP BY 1,2 ORDER BY 1,2').fetchall()]
            nr=sum(r['rows'] for r in endings if r['status'] in core.NARROW)
            info=dict(month=job['month'],selected_frame_rows=sum(counts.values()),pool_rows=n,ordinary_rows=nr,
                      unresolved_rows=unknown,dispositions=counts,ending_counts=endings)
            io.js(tmp/'coverage.json',info);return info
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['ledger']]+job['metadata'])[1]

def research_inputs(project,workers):
    source=prior.research_inputs(project,workers)
    source['legacy_outcome_parent']=legacy_schema.authenticate_parent(project)
    authority=io.load(PACKAGE/'evidence/entry_authority.json')['audit']
    conf=authority['config_sha256']
    root=project/'derived/replication/chooser_iv_repeated_audit_v100_PRIVATE'/conf[:12]
    io.checked(root/'report/_DONE.json',authority['report_receipt_sha256'])
    if io.cfgsha(io.load(root/'config.json'))!=conf:raise RuntimeError('Wrong audited entry universe')
    if io.complete(root/'analysis',conf) is None:raise RuntimeError('Audited entry labels are not complete')
    path=root/'analysis/analysis.parquet'
    if pq.ParquetFile(path).metadata.num_rows!=14058373:raise RuntimeError('Audited entry universe changed')
    source.update(entry_universe=str(path),entry_receipt_sha256=io.sha(root/'analysis/_DONE.json'))
    return source

def future_and_roles_job(job):
    """One panel input supplies later-choice events and contemporaneous entry keys."""
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([job['queries']]))
            c.execute('CREATE VIEW main AS SELECT * FROM '+io.parq([job['panel']]))
            fields='game_id gid,chooser_user_id::BIGINT j,disconnected_user_id::BIGINT i,api_last_move_at_ms::BIGINT t,utc_ms::BIGINT AS "start",archive_ordinal::BIGINT ord,kind_draw::BOOLEAN y'
            c.execute('CREATE TEMP TABLE events AS SELECT '+fields+' FROM main SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON chooser_user_id=q.recipient_id WHERE fair_competitive AND NOT tournament_like_event')
            bad=c.execute('SELECT count(*) FROM main JOIN q USING(game_id) WHERE q.ordinary_narrow').fetchone()[0]
            if bad:raise RuntimeError('Ordinary focal game occurs in active-opportunity main panel')
            for s in range(16):io.copy(c,'SELECT * FROM events WHERE j%16='+str(s),tmp/f'{s:02}.parquet')
            # This matches run_rebuild.py lines defining main_keys: all certified main rows.
            n=io.copy(c,'''SELECT q.row_id,q.game_id,q.recipient_id,q.opponent_id,
                 m.disconnected_user_id::BIGINT i,m.chooser_user_id::BIGINT j,
                 m.fair_competitive,m.kind_draw,m.timeout_chooser_win
                 FROM main m JOIN q USING(game_id)''',tmp/'roles.parquet')
            return dict(future_events=c.execute('SELECT count(*) FROM events').fetchone()[0],matched_roles=n)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['queries'],job['panel']])[1]

def entry_labels(queries,rolepaths,audit_path,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries]))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq(rolepaths))
            c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([audit_path]))
            bad=c.execute('''SELECT count(*) FROM q JOIN m USING(row_id) WHERE
                (q.status IS NOT NULL AND q.status<>'timeout') OR
                NOT ((q.recipient_id=m.i AND q.opponent_id=m.j) OR (q.recipient_id=m.j AND q.opponent_id=m.i))''').fetchone()[0]
            if bad:raise RuntimeError('Certified main role/ending conflicts with focal metadata')
            query='''SELECT q.row_id,(m.row_id IS NOT NULL) matched_main,
              coalesce(q.recipient_id=m.i,FALSE) recipient_disconnect_main,
              coalesce(q.recipient_id=m.i AND m.fair_competitive AND (m.kind_draw OR m.timeout_chooser_win),FALSE) recipient_fair_arm_main,
              coalesce(a.spaced90,FALSE) selected_entry_90,
              coalesce(a.spaced90 AND a.history_window_complete AND a.complete90,FALSE) analysis_entry_90
              FROM q LEFT JOIN m USING(row_id)
              LEFT JOIN a ON q.game_id=a.game_id AND q.recipient_id=a.recipient_id'''
            n=pq.ParquetFile(queries).metadata.num_rows;assert_rows(c,query,n,'Entry labels')
            io.copy(c,query+' ORDER BY q.row_id',tmp/'entry.parquet')
            return dict(rows=n,definition='original certified main roles and audited full-stream spaced90 labels')
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[queries,audit_path]+rolepaths)
