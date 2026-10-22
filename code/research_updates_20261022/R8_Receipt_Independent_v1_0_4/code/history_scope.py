"""Keep grant/claim history and frozen fair-opportunity history distinct.

The historical producer counts `fair`, without its separate `arm` condition.
Reconstruct those counts from its authenticated projections before estimation.
Only aggregate diagnostics are copied to the report; attachments stay private.
"""
from pathlib import Path
import gc
import receipt_resume as base

PRIOR_REL = ('vendor_r7/vendor_phase50/vendor_env102/vendor/entry100/vendor/'
             'phase122/vendor/local_first/evidence/prior_authority.json')


def history_sources(project):
    u = base.u
    authority = u.load(u.ROOT / PRIOR_REL)
    manifest = (Path(project) / 'derived/replication/comparison_tests_v110_PRIVATE'
                / authority['comparison_run'] / 'lineage_PRIVATE.json')
    u.require(u.sha(manifest) == authority['comparison_lineage_sha256'],
              'Historical projection lineage differs from the frozen producer')
    records = []
    for shard, entries in enumerate(u.load(manifest)['projections']):
        for entry in entries:
            records.append(dict(entry, shard=shard,
                                path=str(u.relocate(entry['path'], project))))
    months = ['%04d-%02d' % (2023 + (10 + k) // 12, (10 + k) % 12 + 1)
              for k in range(24)]
    u.require(len(records) == 384 and
              {(r['month'], r['shard']) for r in records} ==
              {(m, s) for m in months for s in range(16)} and
              sum(r['rows'] for r in records) == 47587020,
              'Historical projection coverage differs')
    for month in months:
        with u.heartbeat('Authenticate frozen history projections ' + month):
            for record in records:
                if record['month'] != month:
                    continue
                path = Path(record['path'])
                pf = u.pq.ParquetFile(path)
                u.require(pf.metadata.num_rows == record['rows'] and
                          {'j', 'i', 't', 'fair', 'y', 'arm'} <=
                          set(pf.schema_arrow.names) and
                          u.sha(path) == record['sha256'],
                          'Historical projection bytes/schema changed: ' + str(path))
        u.log('HISTORY_PROJECTION_SHA256_OK ' + month)
    return records, manifest


def window_counts(events, people, starts):
    """Independent prefix-sum calculation on [start-97d, start-7d)."""
    np = base.np
    day = base.m.r.DAY
    dtype = [('person', '<i8'), ('time', '<i8')]
    order = np.lexsort((events['t'], events['person']))
    keys = np.empty(len(order), dtype=dtype)
    keys['person'] = np.asarray(events['person'], np.int64)[order]
    keys['time'] = np.asarray(events['t'], np.int64)[order]
    query = np.empty(len(people), dtype=dtype)
    query['person'] = people
    query['time'] = np.asarray(starts, np.int64) - 7 * day
    hi = np.searchsorted(keys, query, side='left')
    query['time'] -= 90 * day
    lo = np.searchsorted(keys, query, side='left')
    result = {}
    for name in ('fair', 'kind', 'strict'):
        prefix = np.r_[np.int64(0),
                       np.cumsum(np.asarray(events[name], np.int64)[order], dtype=np.int64)]
        result[name] = prefix[hi] - prefix[lo]
    return result


def construct(c, out, report, author_ids, expected_rows=None, expected_counts=None):
    """q/src/pv are the frozen exposures, Stage07 panel and old projections."""
    u = base.u
    np = base.np
    out = Path(out)
    report = Path(report)
    out.mkdir(parents=True, exist_ok=True)
    report.mkdir(parents=True, exist_ok=True)
    src_columns = {r[0] for r in c.execute('DESCRIBE src').fetchall()}
    yn = 'kind_draw' if 'kind_draw' in src_columns else 'outcome_kind_draw'
    needed = {'chooser_user_id', 'disconnected_user_id', 'api_last_move_at_ms',
              'game_id', 'engine_eval_cp_disconnected', 'chooser_username_norm',
              'disconnected_username_norm', 'timeout_chooser_win', yn}
    u.require(needed <= src_columns, 'All-source active-decision schema is incomplete')
    ids = ','.join(str(int(v)) for v in author_ids)
    u.require(len(set(author_ids)) == 2, 'Both author identities must be bound')
    clean_projection = f'j NOT IN ({ids}) AND i NOT IN ({ids})'
    comp = 'engine_eval_cp_disconnected>=-100'
    arm = f'({yn} OR timeout_chooser_win)'
    c.execute('CREATE TEMP TABLE requirements AS SELECT DISTINCT recipient_id FROM q')
    qn, qu = c.execute('SELECT count(*),count(DISTINCT row_id) FROM q').fetchone()
    u.require(qn == qu and (expected_rows is None or qn == expected_rows),
              'Frozen exposure row count/uniqueness changed')
    bridge = c.execute('''SELECT count(*),count(DISTINCT q.row_id),count(*) FILTER(WHERE
      q.recipient_id IS DISTINCT FROM s.disconnected_user_id OR
      q.opponent_id IS DISTINCT FROM s.chooser_user_id OR
      q.anchor_ms IS DISTINCT FROM s.api_last_move_at_ms)
      FROM q JOIN src s USING(game_id)''').fetchone()
    u.require(bridge == (qn, qn, 0), 'All-source/S0 identity or event-time bridge failed')
    invalid = c.execute(f'''SELECT count(*) FROM src WHERE
      chooser_username_norm IS NULL OR disconnected_username_norm IS NULL OR
      chooser_user_id IS NULL OR disconnected_user_id IS NULL OR
      api_last_move_at_ms IS NULL OR {yn} IS NULL OR timeout_chooser_win IS NULL OR
      engine_eval_cp_disconnected IS NULL''').fetchone()[0]
    u.require(invalid == 0, 'All-source active-decision fields contain missing values')
    invalid_projection = c.execute('''SELECT count(*) FROM pv WHERE j IS NULL OR
      i IS NULL OR t IS NULL OR fair IS NULL OR y IS NULL OR arm IS NULL''').fetchone()[0]
    u.require(invalid_projection == 0, 'Historical projection semantics contain missing values')
    # The original primary event rule is unchanged, including strict event timing.
    c.execute(f'''CREATE TEMP TABLE earliest_source AS SELECT
      chooser_user_id recipient_id,
      min(api_last_move_at_ms) FILTER(WHERE {arm})::BIGINT first_decision_ms,
      min(api_last_move_at_ms)::BIGINT first_opportunity_ms
      FROM src WHERE {u.author_predicate()} AND {comp} GROUP BY chooser_user_id''')
    c.execute(f'''CREATE TEMP TABLE earliest_projection AS SELECT j recipient_id,
      min(t) FILTER(WHERE arm)::BIGINT projection_first_decision_ms,
      min(t)::BIGINT projection_first_opportunity_ms
      FROM pv WHERE {clean_projection} AND fair GROUP BY j''')
    c.execute('''CREATE TEMP TABLE attached AS SELECT q.*,s.first_decision_ms,
      s.first_opportunity_ms,p.projection_first_decision_ms,p.projection_first_opportunity_ms,
      coalesce(s.first_decision_ms<q.anchor_ms,false) faced_recorded,
      coalesce(s.first_decision_ms<q.archive_start_ms,false) faced_before_game_start,
      coalesce(s.first_opportunity_ms<q.anchor_ms,false) faced_any_competitive,
      coalesce(q.fair_90>0,false) faced90,
      CASE WHEN q.fair_90=0 THEN 0 WHEN q.kind_90=0 THEN 1 ELSE 2 END::TINYINT group90
      FROM q LEFT JOIN earliest_source s USING(recipient_id)
      LEFT JOIN earliest_projection p USING(recipient_id)''')
    query = c.execute('''SELECT row_id,recipient_id,archive_start_ms,fair_90,kind_90
      FROM q ORDER BY row_id''').to_arrow_table()
    d = base.m.r.arrays(query)
    del query
    day = base.m.r.DAY
    low, high = int(d['archive_start_ms'].min()) - 97*day, int(d['archive_start_ms'].max()) - 7*day
    events = c.execute(f'''SELECT j person,t,sum(fair::BIGINT)::BIGINT fair,
      sum((fair AND y)::BIGINT)::BIGINT kind,sum((fair AND arm)::BIGINT)::BIGINT "strict"
      FROM pv SEMI JOIN requirements ON pv.j=requirements.recipient_id
      WHERE {clean_projection} AND fair AND t>={low} AND t<{high}
      GROUP BY j,t ORDER BY j,t''').to_arrow_table()
    ev = base.m.r.arrays(events)
    del events
    counts = window_counts(ev, d['recipient_id'], d['archive_start_ms'])
    del ev
    frame = u.pd.DataFrame(dict(row_id=d['row_id'],reconstructed_fair90=counts['fair'],
                               reconstructed_kind90=counts['kind'],strict_choice90=counts['strict']))
    c.register('reconstructed', frame)
    c.execute('CREATE TEMP TABLE final_attachment AS SELECT a.*,r.* EXCLUDE(row_id) FROM attached a JOIN reconstructed r USING(row_id)')
    c.unregister('reconstructed')
    del frame, counts, d
    gc.collect()
    secondary = c.execute('SELECT group90,count(*) FROM final_attachment GROUP BY 1 ORDER BY 1').fetchall()
    counts_ok = expected_counts is None or secondary == expected_counts
    # Record every relevant discrepancy before applying any gate.
    metrics = c.execute('''SELECT count(*),
      count(*) FILTER(WHERE fair_90<>reconstructed_fair90),
      count(*) FILTER(WHERE kind_90<>reconstructed_kind90),
      count(*) FILTER(WHERE first_decision_ms IS DISTINCT FROM projection_first_decision_ms),
      count(*) FILTER(WHERE first_opportunity_ms IS DISTINCT FROM projection_first_opportunity_ms),
      count(*) FILTER(WHERE faced90 AND NOT faced_recorded),
      count(*) FILTER(WHERE faced90 AND NOT faced_any_competitive),
      count(*) FILTER(WHERE strict_choice90>0 AND NOT faced_recorded),
      count(*) FILTER(WHERE faced90 AND NOT faced_recorded AND faced_any_competitive
                      AND reconstructed_fair90=fair_90 AND reconstructed_kind90=kind_90 AND strict_choice90=0),
      count(*) FILTER(WHERE faced_recorded<>faced_before_game_start)
      FROM final_attachment''').fetchone()
    names = ['rows','fair90_count_mismatch_rows','kind90_count_mismatch_rows',
             'strict_earliest_time_mismatch_rows','competitive_earliest_time_mismatch_rows',
             'recent_opportunity_without_prior_grant_or_claim_rows',
             'recent_opportunity_without_prior_competitive_opportunity_rows',
             'recent_grant_or_claim_without_prior_grant_or_claim_rows',
             'scope_difference_explained_rows','game_start_sensitivity_rows']
    diag = dict(zip(names, map(int, metrics)))
    diag.update(frozen_secondary_counts=dict(secondary),frozen_secondary_counts_reproduced=counts_ok,
                primary_rule='competitive AND (kind draw OR timeout chooser win); completed before exposure anchor_ms',
                secondary_rule='frozen fair_90: all competitive opportunities, including nonarm resolutions',
                secondary_window='[archive_start_ms-97 days, archive_start_ms-7 days)',
                primary_changed=False,secondary_changed=False,score_changed=False,
                definitions_forced_to_agree=False,private_rows_exported=False)
    problems = {k:diag[k] for k in names[1:5]+names[6:8] if diag[k] != 0}
    if not counts_ok:problems['frozen_secondary_counts_changed'] = True
    if diag[names[5]] != diag['scope_difference_explained_rows']:
        problems['unexplained_discordant_rows'] = diag[names[5]] - diag['scope_difference_explained_rows']
    diag['status'] = ('CERTIFIED_DIFFERENT_EVENT_SCOPES' if not problems
                      else 'BLOCKED_HISTORY_SOURCE_DISCREPANCY')
    diag['unresolved_checks'] = problems
    u.save(report/'history_scope_diagnostics.json',diag)
    u.table(report,'history_scope_crosswalk',c.execute('''SELECT faced_recorded,
      faced_any_competitive,group90,strict_choice90>0 faced_strict90,count(*) exposures
      FROM final_attachment GROUP BY ALL ORDER BY ALL''').fetchdf())
    census = c.execute(f'''SELECT {comp} competitive,{arm} grant_or_claim,count(*) events
      FROM src WHERE {u.author_predicate()} GROUP BY ALL ORDER BY ALL''').fetchdf()
    u.table(report,'history_scope_source_census',census)
    p = out/'split.parquet'
    c.execute('COPY (SELECT * FROM final_attachment ORDER BY row_id) TO '+u.qs(p)+' (FORMAT PARQUET,COMPRESSION ZSTD)')
    if problems:
        u.save(out/'FAILED_DIAGNOSTIC.json',diag)
        u.log('HISTORY_SCOPE_BLOCKED ' + str(problems))
    u.require(not problems,'History source validation failed; aggregate diagnostics: '+str(problems))
    u.log('HISTORY_SCOPE_VALIDATED recent opportunities without prior grant/claim: '+str(diag[names[5]])+
          '; all explained by the different event scopes')
    return p, diag


def prior_frame(paths, binding, project, work, key, memory, report):
    u = base.u
    out = Path(work)/'prior_experience'
    if u.verify_cached(out,key):
        for f in (out/'report').iterdir():
            if f.is_file():
                import shutil
                shutil.copy2(f,Path(report)/f.name)
        u.log('History scope checkpoint verified; attachment reused')
        return out/'split.parquet',u.load(out/'summary.json')
    sources, source_manifest = u.full_source_panels(project)
    projections, projection_manifest = history_sources(project)
    c = u.conn(out/'spill',max(2,memory-2),1)
    ar = out/'report'
    try:
        c.execute('CREATE VIEW q AS SELECT row_id,game_id,recipient_id,opponent_id,archive_start_ms,anchor_ms,fair_90,kind_90 FROM '+u.parq([paths['S0']]))
        c.execute('CREATE VIEW src AS SELECT * FROM '+u.parq([r['path'] for r in sources]))
        c.execute('CREATE VIEW pv AS SELECT j,i,t,fair,y,arm FROM '+u.parq([r['path'] for r in projections]))
        with u.heartbeat('Validate full grant/claim history and reconstruct frozen 90-day opportunity counts'):
            p,diag = construct(c,out,ar,list(binding['author_ids'].values()),2682329,
                               [(0,1319101),(1,1291893),(2,71335)])
        summary = dict(diag,all_source_rows=47587020,all_source_files=24,history_projection_files=384,
            source_window='November 2023–October 2025; all sources and adjacent pairs',
            left_censoring='No prior grant/claim in this recorded chronology; no lifetime assertion',
            author_policy='Both author accounts excluded on both sides; chronology remains factual')
        u.save(out/'summary.json',summary)
    finally:
        c.close()
        if ar.exists():
            import shutil
            for f in ar.iterdir():
                if f.is_file():shutil.copy2(f,Path(report)/f.name)
    u.certify(out,key,[paths['S0'],source_manifest,projection_manifest]+
              [r['path'] for r in sources]+[r['path'] for r in projections],summary)
    return p,summary
