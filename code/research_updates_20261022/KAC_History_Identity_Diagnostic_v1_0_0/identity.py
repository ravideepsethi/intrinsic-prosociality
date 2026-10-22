"""Narrow-column identity checks. This module never repairs or estimates anything."""
from util import *
import collections


def key_shape(value):
    if value is None:
        return 'null'
    if value == '':
        return 'empty'
    if re.fullmatch(r'[A-Za-z0-9]{8}', value):
        return 'eight_ascii_alphanumeric'
    if re.fullmatch(r'[A-Za-z0-9]{8}', value.strip()):
        return 'eight_after_whitespace_trim'
    if re.fullmatch(r'https?://(?:www\.)?lichess\.org/[A-Za-z0-9]{8}(?:/.*)?', value):
        return 'url_shaped'
    return 'other'


def shapes(c, relation, column='game_id'):
    # Aggregate shapes only. Literal identifiers never enter the public report.
    return dict(collections.Counter(key_shape(r[0]) for r in c.execute(
        'SELECT '+column+' FROM '+relation).fetchall()))


def raw_sql(record):
    return f'''SELECT game_id::VARCHAR game_id, utc_ms::BIGINT t,
        archive_ordinal::BIGINT ordinal, white_id::BIGINT white_id,
        black_id::BIGINT black_id, {int(record['speed_code'])}::TINYINT speed_code
        FROM {scan(record['path'])}'''


def aggregate(c, sql):
    cur = c.execute(sql)
    return {d[0]: int(v or 0) for d, v in zip(cur.description, cur.fetchone())}


def compare_month(c, focal_path, records, out):
    """Reproduce the exact chooser/game join without building any sessions."""
    out = Path(out)
    c.execute('CREATE TEMP TABLE focal AS SELECT game_id,chooser,t,ordinal,speed_code FROM '+scan(focal_path))
    n, distinct = c.execute('SELECT count(*),count(DISTINCT game_id) FROM focal').fetchone()
    require(n == distinct, 'FOCAL_GAME_KEYS_NOT_UNIQUE')
    # All five speeds are searched. This retains wrong-player and wrong-speed
    # candidates instead of filtering them out with the needed-chooser set.
    parts = [f'''SELECT h.* FROM ({raw_sql(r)}) h
        SEMI JOIN focal f ON h.game_id=f.game_id''' for r in records]
    c.execute('CREATE TEMP TABLE matches AS '+' UNION ALL '.join(parts))
    c.execute('''CREATE TEMP TABLE counts AS SELECT f.game_id,
        count(h.game_id)::BIGINT game_rows,
        count(*) FILTER (WHERE f.chooser IN (h.white_id,h.black_id))::BIGINT pair_rows,
        count(*) FILTER (WHERE f.chooser IN (h.white_id,h.black_id)
          AND f.t=h.t AND f.speed_code=h.speed_code)::BIGINT exact_rows,
        count(*) FILTER (WHERE f.chooser IN (h.white_id,h.black_id)
          AND (f.t IS DISTINCT FROM h.t OR f.speed_code IS DISTINCT FROM h.speed_code))::BIGINT time_speed_mismatch_rows,
        count(*) FILTER (WHERE f.chooser IN (h.white_id,h.black_id)
          AND f.ordinal IS DISTINCT FROM h.ordinal)::BIGINT ordinal_mismatch_rows
        FROM focal f LEFT JOIN matches h USING(game_id) GROUP BY f.game_id''')
    summary = aggregate(c, '''SELECT count(*) focal_rows,
        count(*) FILTER(WHERE game_rows=0) missing_game_keys,
        count(*) FILTER(WHERE game_rows>0 AND pair_rows=0) game_present_wrong_chooser,
        count(*) FILTER(WHERE pair_rows=0) missing_chooser_game_pairs,
        count(*) FILTER(WHERE pair_rows>1) duplicated_chooser_game_pairs,
        count(*) FILTER(WHERE pair_rows>0 AND time_speed_mismatch_rows>0) time_or_speed_mismatches,
        count(*) FILTER(WHERE pair_rows=1 AND exact_rows=1) passing_focal_rows,
        count(*) FILTER(WHERE ordinal_mismatch_rows>0) ordinal_mismatches_auxiliary_only,
        sum(greatest(pair_rows,1)) parent_join_rows,
        sum(time_speed_mismatch_rows)+count(*) FILTER(WHERE pair_rows=0) parent_time_speed_check
        FROM counts''')
    c.execute('''CREATE TEMP TABLE bad AS SELECT f.*,n.* EXCLUDE(game_id)
        FROM focal f JOIN counts n USING(game_id)
        WHERE pair_rows<>1 OR exact_rows<>1''')
    summary['failing_focal_rows'] = copy(c, 'SELECT * FROM bad', out/'bad_focal.parquet')
    copy(c, 'SELECT h.* FROM matches h SEMI JOIN bad b USING(game_id)', out/'same_key_candidates.parquet')
    summary['bad_key_shapes'] = shapes(c, 'bad')
    summary['identity_pass'] = summary['failing_focal_rows'] == 0
    summary['replicated_parent_check'] = [summary['parent_join_rows'],
        summary['missing_chooser_game_pairs'], summary['parent_time_speed_check']]
    return summary


def certified_targets(c, source_path, bad_path, out):
    c.execute('CREATE TEMP TABLE bad AS SELECT * FROM '+scan(bad_path))
    c.execute('CREATE TEMP TABLE targets AS SELECT s.* FROM '+scan(source_path)+
        ' s SEMI JOIN bad b USING(game_id)')
    n = copy(c, 'SELECT * FROM targets', Path(out)/'certified_targets.parquet')
    require(n == c.execute('SELECT count(*) FROM bad').fetchone()[0], 'CERTIFIED_TARGET_COUNT_CHANGED')
    names = {r[0] for r in c.execute('DESCRIBE targets').fetchall()}
    required = {'game_id','utc_ms','archive_ordinal','chooser_user_id','disconnected_user_id',
                'disconnected_color','api_speed','chooser_elo','disconnected_elo'}
    require(required <= names, 'CERTIFIED_TARGET_SCHEMA_MISSING')
    mismatch = c.execute('''SELECT count(*) FROM targets s JOIN bad b USING(game_id)
        WHERE s.chooser_user_id IS DISTINCT FROM b.chooser
        OR s.utc_ms IS DISTINCT FROM b.t OR s.archive_ordinal IS DISTINCT FROM b.ordinal
        OR (CASE s.api_speed WHEN 'ultraBullet' THEN 0 WHEN 'ultrabullet' THEN 0
            WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2 WHEN 'rapid' THEN 3
            WHEN 'classical' THEN 4 END) IS DISTINCT FROM b.speed_code''').fetchone()[0]
    require(mismatch == 0, 'CACHED_FOCAL_DIFFERS_FROM_CERTIFIED_SOURCE')
    require(c.execute("SELECT count(*) FROM targets WHERE disconnected_color NOT IN ('white','black') OR disconnected_color IS NULL").fetchone()[0] == 0,
        'INVALID_CERTIFIED_COLOR')
    c.execute('''CREATE TEMP TABLE canonical AS SELECT s.game_id,b.chooser,b.t,b.ordinal,b.speed_code,
        CASE WHEN s.disconnected_color='white' THEN s.disconnected_user_id ELSE s.chooser_user_id END::BIGINT white_id,
        CASE WHEN s.disconnected_color='black' THEN s.disconnected_user_id ELSE s.chooser_user_id END::BIGINT black_id
        FROM targets s JOIN bad b USING(game_id)''')
    copy(c, 'SELECT * FROM canonical', Path(out)/'canonical_targets.parquet')
    flags = aggregate(c, '''SELECT count(*) target_rows,
        count(*) FILTER(WHERE t IS NULL OR t<=0) invalid_timestamps,
        count(*) FILTER(WHERE ordinal IS NULL) missing_archive_ordinals,
        count(*) FILTER(WHERE white_id IS NULL OR black_id IS NULL OR white_id=black_id) invalid_players
        FROM canonical''')
    flags['cached_projection_matches_certified_source'] = True
    flags['key_shapes'] = shapes(c, 'canonical')
    flags['schema_columns'] = len(names)
    return flags


def probe(c, target_path, records, month, out):
    """Candidate lookup, never an alternative join or a repair authorization."""
    c.execute('CREATE TEMP TABLE target AS SELECT * FROM '+scan(target_path))
    candidates = []
    for r in records:
        same_month = r['month'] == month
        clauses = ['h.game_id IN (SELECT game_id FROM target)']
        if same_month:
            clauses += ['h.ordinal IN (SELECT ordinal FROM target)',
                '''(h.t IN (SELECT t FROM target)
                    AND (h.white_id IN (SELECT white_id FROM target)
                    OR h.black_id IN (SELECT black_id FROM target)))''']
        candidates.append(f'''SELECT h.*,{q(r['month'])} source_month FROM ({raw_sql(r)}) h
            WHERE '''+' OR '.join('('+x+')' for x in clauses))
    c.execute('CREATE TEMP TABLE candidates AS '+' UNION ALL '.join(candidates))
    copy(c, 'SELECT * FROM candidates', Path(out)/'history_candidates.parquet')
    c.execute(f'''CREATE TEMP TABLE comparisons AS SELECT t.game_id target_key,
        h.game_id history_key,h.source_month,h.t history_t,h.ordinal history_ordinal,
        h.game_id IS NOT DISTINCT FROM t.game_id same_key,
        h.t IS NOT DISTINCT FROM t.t same_time,
        h.ordinal IS NOT DISTINCT FROM t.ordinal same_ordinal,
        h.speed_code IS NOT DISTINCT FROM t.speed_code same_speed,
        h.white_id IS NOT DISTINCT FROM t.white_id AND h.black_id IS NOT DISTINCT FROM t.black_id same_ordered_players,
        h.white_id IS NOT DISTINCT FROM t.black_id AND h.black_id IS NOT DISTINCT FROM t.white_id reversed_players,
        t.chooser IN (h.white_id,h.black_id) chooser_present,
        (h.t-t.t)::BIGINT time_delta_ms
        FROM target t JOIN candidates h ON h.game_id=t.game_id
        OR (h.source_month={q(month)} AND (h.ordinal=t.ordinal
            OR (h.t=t.t AND (h.white_id=t.white_id OR h.black_id=t.black_id))))''')
    copy(c, 'SELECT * FROM comparisons', Path(out)/'candidate_comparisons.parquet')
    summary = aggregate(c, '''SELECT count(*) candidate_comparisons,
        count(DISTINCT target_key) targets_with_any_candidate,
        count(*) FILTER(WHERE same_key) same_key_rows,
        count(*) FILTER(WHERE same_key AND chooser_present AND same_time AND same_speed) exact_identity_rows,
        count(*) FILTER(WHERE same_ordinal AND same_time AND same_speed AND same_ordered_players AND NOT same_key) coherent_except_key_rows,
        count(*) FILTER(WHERE same_key AND NOT chooser_present) same_key_wrong_players_rows,
        count(*) FILTER(WHERE same_time AND same_speed AND same_ordered_players AND NOT same_key) same_players_time_speed_different_key_rows,
        count(*) FILTER(WHERE same_key AND NOT same_time) same_key_wrong_time_rows,
        count(*) FILTER(WHERE same_key AND NOT same_speed) same_key_wrong_speed_rows
        FROM comparisons''')
    summary['history_candidate_key_shapes'] = shapes(c, 'candidates')
    # An ordinal collision or a matching player/time tuple is only a clue.
    summary['candidate_interpretation'] = 'DIAGNOSTIC_ONLY_NO_KEYS_NORMALIZED_OR_REPLACED'
    summary['searched_months'] = sorted({r['month'] for r in records})
    return summary


def upstream(c, target_path, records, project, month, out):
    """Only producer-declared Parquet locations; no raw PGN or broad disk crawl."""
    c.execute('CREATE TEMP TABLE target AS SELECT * FROM '+scan(target_path))
    result = []
    for r in records:
        source = Path(r['path']); base = source.parents[3]
        command = base/'command.json'
        item = dict(speed=r['speed'],command_present=command.is_file())
        if not command.is_file():
            item['status']='NO_PRODUCER_COMMAND';result.append(item);continue
        item['command_sha256']=sha(command)
        numeric = load(command).get('numeric_root')
        if not isinstance(numeric,str):
            item['status']='NO_NUMERIC_ROOT';result.append(item);continue
        nr=Path(numeric)
        if not nr.is_absolute():nr=Path(project)/nr
        nr=nr.resolve()
        try:nr.relative_to(Path(project).resolve())
        except ValueError:
            item['status']='DECLARED_ROOT_OUTSIDE_PROJECT';result.append(item);continue
        files=sorted((nr/f'events_numeric/month={month}/speed={r["speed"]}').glob('*.parquet'))
        item['files']=len(files)
        if not files:
            item['status']='NO_PARQUETS_AT_DECLARED_PARTITION';result.append(item);continue
        require(len(files)<=256,'UPSTREAM_PARTITION_TOO_LARGE')
        stamps={str(p):snapshot(p) for p in files}
        view='up_'+str(r['speed_code'])
        c.execute('CREATE TEMP VIEW '+view+' AS SELECT * FROM '+scan(files))
        names={x[0] for x in c.execute('DESCRIBE '+view).fetchall()}
        if not {'game_id','archive_ordinal'}<=names:
            item['status']='UPSTREAM_IDENTITY_COLUMNS_MISSING';result.append(item);continue
        sql='SELECT * FROM '+view+' WHERE game_id IN (SELECT game_id FROM target) OR archive_ordinal IN (SELECT ordinal FROM target)'
        c.execute('CREATE TEMP TABLE hit_'+view+' AS '+sql)
        item['candidate_rows']=copy(c,'SELECT * FROM hit_'+view,Path(out)/(view+'.parquet'))
        item.update(aggregate(c, 'SELECT count(*) FILTER(WHERE game_id IN (SELECT game_id FROM target)) exact_key_rows FROM hit_'+view))
        item['key_shapes']=shapes(c,'hit_'+view)
        item['status']='CANDIDATES_STORED_PRIVATELY_NO_REPAIR'
        for p in files:require(snapshot(p)==stamps[str(p)],'UPSTREAM_CHANGED_DURING_PROBE')
        result.append(item)
    return result
