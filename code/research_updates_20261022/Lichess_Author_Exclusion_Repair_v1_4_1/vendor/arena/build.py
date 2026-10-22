"""Authenticate the original panel and build source-labelled replication inputs."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import os
from pathlib import Path
import shutil

from common import *
from validation import validate_source_masks, validate_opportunity_rows

def counts(con, table):
    return rows(con, f'''SELECT count(*) AS n, sum(outcome_kind_draw::BIGINT) AS grants,
      count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100) AS fair_n,
      count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100 AND outcome_kind_draw) AS fair_grants
      FROM {table}''')[0]

def narrow_query():
    return f'''SELECT p.game_id, p.month, p.chooser_user_id AS chooser,
      p.disconnected_user_id AS opponent, p.chooser_username_norm AS username,
      p.utc_ms AS start_ms, p.api_last_move_at_ms AS last_move_ms,
      p.outcome_kind_draw::DOUBLE AS kind, p.timeout_chooser_win AS claimed,
      p.engine_eval_cp_disconnected::DOUBLE AS eval, p.engine_eval_is_mate AS mate,
      p.ply_count AS ply, p.api_speed AS speed, p.time_control,
      p.tc_base_s, p.tc_inc_s, p.chooser_elo::DOUBLE AS rating,
      (p.disconnected_elo-p.chooser_elo)::DOUBLE AS gap,
      p.chooser_pre_rd_v2 AS rd, p.disconnected_pre_rd_v2 AS opp_rd,
      p.chooser_draw_payoff_v2 AS payoff, p.chooser_win_premium_v2 AS premium,
      p.chooser_win_payoff_v2 AS win_payoff,
      p.chooser_clock_last_obs_s AS clock_self,
      p.disconnected_clock_last_obs_s AS clock_opp,
      e.source, e.previous_classification_status AS previous_status,
      {board_case('p.engine_eval_cp_disconnected')}::TINYINT AS board,
      {ply_case('p.ply_count')}::TINYINT AS stage
      FROM p JOIN e USING(game_id)'''

def build_month(task):
    m, join_root, root, contract, memory, threads = task
    dest = Path(root) / 'private/months' / ('month='+m['month'])
    old = verify_complete(dest, contract)
    if old:
        return old['summary']
    require(not dest.exists(), 'Incomplete committed month folder; preserve it and use a fresh run')
    tmp = dest.with_name(dest.name + f'.pending.{os.getpid()}')
    tmp.mkdir(parents=True, exist_ok=False)
    work = Path(root) / 'private/work' / m['month']
    con = database(':memory:', threads, memory, work)
    masks = sorted((Path(join_root) / ('join_month=' + m['month'])).glob('*.parquet'))
    require(masks, 'Missing monthly source/adjacency partition')
    con.execute('CREATE VIEW p AS SELECT * FROM ' + parquet(m['panel_path']))
    con.execute('CREATE VIEW e AS SELECT * FROM ' + parquet(masks))
    for v in ('p', 'e'):
        n, unique, bad = con.execute(f'''SELECT count(*),count(DISTINCT game_id),
          count(*) FILTER(WHERE game_id IS NULL OR month IS DISTINCT FROM {q(m['month'])}) FROM {v}''').fetchone()
        require((n, unique, bad) == (m['expected_counts']['original'], m['expected_counts']['original'], 0),
                'Monthly coverage/identity mismatch: ' + m['month'])
    mismatch = con.execute('''SELECT count(*) FROM p FULL OUTER JOIN e USING(game_id)
      WHERE p.game_id IS NULL OR e.game_id IS NULL OR p.month IS DISTINCT FROM e.month
      OR p.chooser_user_id IS DISTINCT FROM e.p1 OR p.disconnected_user_id IS DISTINCT FROM e.p2
      OR p.utc_ms IS DISTINCT FROM e.focal_start_ms''').fetchone()[0]
    require(mismatch == 0, 'Source join changed identity/orientation/start time')
    opportunity_qa=validate_opportunity_rows(con,m['month'],Path(root)/'public/validation')
    con.execute('CREATE VIEW narrow AS ' + narrow_query())
    actual = rows(con, '''SELECT source,previous_status,count(*) AS n,
      sum(kind)::BIGINT AS grants,count(*) FILTER(WHERE eval>=-100) AS fair_n,
      count(*) FILTER(WHERE eval>=-100 AND kind=1) AS fair_grants
      FROM narrow GROUP BY 1,2 ORDER BY 1,2''')
    actual_source = {r['source']: r['n'] for r in rows(con, 'SELECT source,count(*) AS n FROM narrow GROUP BY 1')}
    require(actual_source == {r['source']: r['rows'] for r in m['source_counts']}, 'Monthly source count mismatch')
    expected_status = {(r['source'], r['classification_status']): r['rows'] for r in m['statuses']}
    require({(r['source'],r['previous_status']):r['n'] for r in actual} == expected_status,
            'Monthly source-by-adjacency mismatch')
    con.execute(f'COPY narrow TO {q(tmp / "opportunities.parquet")} (FORMAT PARQUET, COMPRESSION ZSTD)')
    arena_filter = f"e.source='arena' AND e.previous_classification_status={q(NONADJACENT)}"
    con.execute(f'''COPY (SELECT p.* FROM p JOIN e USING(game_id) WHERE {arena_filter})
      TO {q(tmp / 'analysis_panel.parquet')} (FORMAT PARQUET, COMPRESSION ZSTD)''')
    summary = {'month': m['month'], 'counts': actual,'opportunity_validation':opportunity_qa,
               'arena': counts(con, f'(SELECT p.* FROM p JOIN e USING(game_id) WHERE {arena_filter})')}
    con.close()
    complete(tmp, contract, {'summary': summary})
    os.replace(tmp, dest)
    log('Built ' + m['month'] + ': arena rows=' + str(summary['arena']['n']))
    return summary

def build(project, root, workers, threads, memory):
    root = Path(root)
    auth = load_source('source/auth/build_main_sample.py', 'arena_original_input_auth')
    log('Checking original Stage 07, completed source union, and all 128 adjacency receipts')
    plan = auth.production_plan(ROOT / 'source/auth', Path(project))
    panel_bytes=sum(e['size_bytes'] for e in plan['entries'] if e['kind']=='panel')
    join_bytes=sum(e['size_bytes'] for e in plan['entries'] if e['kind']=='join')
    disk_allowance=max(20*1024**3,int(.75*panel_bytes+2*join_bytes+8*1024**3))
    free=shutil.disk_usage(root).free
    log(f'Initial disk planning allowance: {disk_allowance/1024**3:.1f} GiB; free: {free/1024**3:.1f} GiB')
    if not (root/'private/INPUT_PLAN.json').exists():
        require(free>=disk_allowance,'Insufficient free space for the initial build planning allowance')
    json_write(root/'public/RESOURCE_PLAN.json',{'free_bytes_at_start':free,
      'initial_disk_planning_allowance_bytes':disk_allowance,'measured_peak_available':False,
      'formula':'max(20 GiB, 0.75 * original panel bytes + 2 * join bytes + 8 GiB)',
      'ram_gb':ram_gb(),'max_workers':workers,'max_duckdb_threads':threads,
      'duckdb_main_memory_limit':memory,'python_arrays_included_in_duckdb_cap':False})
    inputs = auth.authenticate_inputs(plan, workers=min(workers,10))
    contract = fingerprint({'package': verify_package(), 'inputs': inputs,
                            'predicate': "source='arena' AND previous_status='not_mutually_adjacent_observed'"})
    json_write(root / 'private/INPUT_PLAN.json', plan)
    json_write(root / 'private/INPUT_SIGNATURES.json', inputs)
    if (root / 'private/BUILD.json').is_file():
        saved = read_json(root / 'private/BUILD.json')
        require(saved['contract'] == contract, 'Existing build belongs to different inputs or code')
    join_root = root / 'private/source_months'
    if not verify_complete(join_root, contract):
        require(not join_root.exists(), 'Incomplete committed source partition; use a fresh run')
        tmp = join_root.with_name('source_months.pending.' + str(os.getpid()))
        tmp.mkdir(parents=True)
        con,timezone_info = database(':memory:', threads, memory, root / 'private/work/source',
                                     with_timezone_info=True)
        con.execute('CREATE VIEW j AS SELECT * FROM ' + parquet(plan['join_paths']))
        con.execute('CREATE VIEW s AS SELECT * FROM ' + parquet(plan['source_path']))
        validate_source_masks(con,plan,auth,root/'public/validation',timezone_info)
        con.execute(f'''COPY (SELECT game_id,month,p1,p2,focal_start_ms,source,
          previous_classification_status, month AS join_month FROM j)
          TO {q(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY(join_month))''')
        con.close()
        complete(tmp, contract)
        os.replace(tmp, join_root)
    monthly = []
    # Full-width source rows make these tasks memory-heavy. Ten is a ceiling.
    month_workers = min(workers, max(1, int((ram_gb()-6)//4)), 4)
    per_memory = str(max(1, min(3, int((ram_gb()-6)/max(1,month_workers)/1.5)))) + 'GB'
    log(f'Month build: {month_workers} processes, {per_memory} DuckDB buffer each')
    tasks = [(m, str(join_root), str(root), contract, per_memory, max(1,min(2,threads//month_workers))) for m in plan['months']]
    with ProcessPoolExecutor(max_workers=month_workers) as ex:
        for f in as_completed([ex.submit(build_month,t) for t in tasks]):
            monthly.append(f.result())
    monthly.sort(key=lambda r:r['month'])
    flat = [r for m in monthly for r in m['counts']]
    def total(pred):
        return tuple(sum(r[k] for r in flat if pred(r)) for k in ('n','grants','fair_n','fair_grants'))
    actual = {
        'all': total(lambda r:True),
        'arena_all':total(lambda r:r['source']=='arena'),
        'pool_all':total(lambda r:r['source']=='pool'),
        'pool_nonadjacent':total(lambda r:r['source']=='pool' and r['previous_status']==NONADJACENT),
        'arena_nonadjacent':total(lambda r:r['source']=='arena' and r['previous_status']==NONADJACENT),
    }
    for k in ('all','arena_all','pool_all','pool_nonadjacent'):
        require(actual[k] == EXPECTED[k], f'Certified total failed: {k}: {actual[k]}')
    require(actual['arena_nonadjacent'][0] == EXPECTED['arena_nonadjacent_rows'], 'Arena retained count changed')
    sample = {'status':'ARENA_INPUTS_BUILT_AND_CHECKED','contract':contract,
      'totals':actual,'monthly':monthly,'months':[m['month'] for m in monthly],
      'panel_paths':[str(root/'private/months'/('month='+m['month'])/'analysis_panel.parquet') for m in monthly],
      'narrow_paths':[str(root/'private/months'/('month='+m['month'])/'opportunities.parquet') for m in monthly],
      'source_files_unchanged':True,'literal_immediate_rematch_timing_certified':False,
      'network_requests':0,'stockfish_evaluations':0}
    auth.unchanged(inputs)
    json_write(root / 'private/BUILD.json', sample)
    json_write(root / 'public/SAMPLE_COUNTS.json', {'scope':'Nov 2023–Oct 2025; source-specific observed-adjacency screen',
               'columns':['opportunities','kind_draws','competitive_opportunities','competitive_kind_draws'],
               'totals':actual,'monthly':monthly,'input_contract':contract})
    return sample
