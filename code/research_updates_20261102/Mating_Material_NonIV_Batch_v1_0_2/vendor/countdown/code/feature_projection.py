"""One SQL projection per authenticated month; no engine or HTTP code."""
from common import *
import pyarrow as pa

REQUIRED = ['game_id','month','chooser_user_id','outcome_kind_draw',
 'engine_eval_cp_disconnected','engine_eval_cp_disconnected_raw','engine_eval_is_mate',
 'ply_count','api_speed','api_last_move_at_ms','disconnected_color','side_to_move_after_last',
 'chooser_clock_last_obs_s','disconnected_clock_last_obs_s','chooser_elo','disconnected_elo',
 'api_status','api_rated','api_variant','five_second_rule_passed','sf100k_nodes_requested',
 'sf100k_fen_turn_matches_disconnected_color','sf100k_disconnected_color_for_perspective',
 'chooser_username_norm','disconnected_username_norm']

def fields(path): return set(pq.ParquetFile(path).schema_arrow.names)

def material_sql(names):
    has_fen = 'fen_after_last_move' in names
    has_counts = all(f'{r}_{p}' in names for r in ('chooser','disconnected') for p,_,_ in PIECES)
    fen = 'fen_after_last_move' if has_fen else 'NULL::VARCHAR'
    # Count literal pieces, including promotions. Digits and kings carry no material value.
    board = f"split_part({fen},' ',1)"
    pc = lambda ch:f'(length({board})-length(replace({board},{q(ch)},\'\')))'
    v = lambda role,ch:f"CASE WHEN disconnected_color='white' THEN {pc(ch.upper() if role=='disconnected' else ch)} ELSE {pc(ch if role=='disconnected' else ch.upper())} END"
    fen_counts = {f'{r}_{p}':v(r,ch) for r in ('chooser','disconnected') for p,ch,_ in PIECES}
    expanded = board
    for i in range(1,9): expanded=f'replace({expanded},{q(i)},{q("x"*i)})'
    rank_lengths = f"list_transform(string_split({expanded},'/'), r -> length(r))"
    fen_ok = f'''coalesce({fen} IS NOT NULL AND len(string_split(trim({fen}),' '))=6
        AND regexp_full_match({board},'[prnbqkPRNBQK1-8]+(/[prnbqkPRNBQK1-8]+){{7}}')
        AND list_min({rank_lengths})=8 AND list_max({rank_lengths})=8
        AND {pc('K')}=1 AND {pc('k')}=1
        AND split_part({fen},' ',2)=CASE disconnected_color WHEN 'white' THEN 'w' ELSE 'b' END, false)'''
    if not has_fen: fen_ok = 'false'
    counts_ok = ' AND '.join(f'{ident(r+"_"+p)} IS NOT NULL AND {ident(r+"_"+p)} BETWEEN 0 AND 15 AND {ident(r+"_"+p)}=floor({ident(r+"_"+p)})'
                             for r in ('chooser','disconnected') for p,_,_ in PIECES) if has_counts else 'false'
    if has_counts:
        counts_ok += ' AND ' + ' AND '.join('('+ '+'.join(ident(r+'_'+p) for p,_,_ in PIECES)+')<=15' for r in ('chooser','disconnected'))
    values = {}
    for k, expression in fen_counts.items():
        values[k] = f'CASE WHEN _fen_ok THEN ({expression}) WHEN _counts_ok THEN {ident(k)} ELSE NULL END' if has_counts else f'CASE WHEN _fen_ok THEN ({expression}) ELSE NULL END'
    equal = ' AND '.join(f'{ident(k)} IS NOT DISTINCT FROM ({v})' for k,v in fen_counts.items()) if has_counts else 'true'
    return dict(has_fen=has_fen, has_counts=has_counts, fen_ok=fen_ok, counts_ok=counts_ok,
                fen_present=f'{fen} IS NOT NULL', equal=equal, values=values)

def project_month(task):
    start=time.monotonic(); r=task['record']; src=Path(r['path']); out=Path(task['out'])
    out.mkdir(parents=True, exist_ok=True)
    before=stamp(src)
    require(sha(src)==r['expected_sha256'], 'Source SHA256 differs: '+r['month'])
    require(pq.ParquetFile(src).metadata.num_rows==r['rows'], 'Source count differs: '+r['month'])
    key=digest([task['config'], r['month'], r['expected_sha256']])
    receipt=out/'DONE.json'
    if receipt.exists():
        saved=read(receipt); require(saved['key']==key, 'Monthly checkpoint definition differs')
        verify(saved['output']); require(stamp(src)==before,'Source changed during resume check')
        return {**saved, 'reused':True,'elapsed_seconds':time.monotonic()-start,'source_stamp':before}
    names=fields(src); require(set(REQUIRED)<=names, 'Missing required fields: '+','.join(sorted(set(REQUIRED)-names)))
    mat=material_sql(names)
    c=db(out/'spill',task['memory_gb'],1)
    try:
        c.execute('CREATE VIEW src AS SELECT * FROM '+scan(src))
        bad=c.execute(f'''SELECT count(*) FROM src WHERE
            month IS DISTINCT FROM {q(r['month'])} OR game_id IS NULL OR trim(game_id)=''
            OR chooser_user_id IS NULL OR outcome_kind_draw IS NULL OR outcome_kind_draw::INTEGER NOT IN (0,1)
            OR ply_count IS NULL OR ply_count<0
            OR NOT coalesce(api_status='timeout' AND api_rated AND api_variant='standard' AND five_second_rule_passed, false)
            OR NOT coalesce(sf100k_nodes_requested=100000 AND sf100k_fen_turn_matches_disconnected_color,false)
            OR disconnected_color NOT IN ('white','black') OR disconnected_color IS NULL
            OR disconnected_color IS DISTINCT FROM side_to_move_after_last
            OR disconnected_color IS DISTINCT FROM sf100k_disconnected_color_for_perspective
            OR coalesce(trim(chooser_username_norm),'')='' OR coalesce(trim(disconnected_username_norm),'')=''
            OR lower(trim(chooser_username_norm)) IN ({','.join(map(q,AUTHORS))})
            OR lower(trim(disconnected_username_norm)) IN ({','.join(map(q,AUTHORS))})
            OR api_last_move_at_ms IS NULL
            OR NOT isfinite(api_last_move_at_ms::DOUBLE)
            OR api_last_move_at_ms<946684800000 OR api_last_move_at_ms>4102444800000
            OR (NOT engine_eval_is_mate AND engine_eval_cp_disconnected_raw IS DISTINCT FROM engine_eval_cp_disconnected)
            OR (engine_eval_is_mate AND abs(engine_eval_cp_disconnected) IS DISTINCT FROM 10000)
            ''').fetchone()[0]
        require(bad==0, f'{r["month"]}: {bad} rows violate source/role/author/engine semantics')
        c.execute('CREATE VIEW checks AS SELECT *, '+mat['fen_ok']+' AS _fen_ok, coalesce(('+mat['counts_ok']+'),false) AS _counts_ok FROM src')
        mismatch=c.execute('SELECT count(*) FROM checks WHERE _fen_ok AND _counts_ok AND NOT ('+mat['equal']+')').fetchone()[0]
        require(mismatch==0, f'{r["month"]}: cached FEN and piece counts disagree on {mismatch} rows')
        malformed=c.execute('SELECT count(*) FROM checks WHERE '+mat['fen_present']+' AND NOT _fen_ok').fetchone()[0]
        require(malformed==0, f'{r["month"]}: {malformed} malformed FENs or FEN turn mismatches')
        computed=','.join('('+v+')::SMALLINT AS _'+k for k,v in mat['values'].items())
        c.execute('CREATE VIEW pieces AS SELECT *, '+computed+' FROM checks')
        material='+'.join(f'{w}*(_chooser_{p}-_disconnected_{p})' for p,_,w in PIECES)
        if 'disconnected_minus_chooser_material' in names:
            n=c.execute('SELECT count(*) FROM pieces WHERE (_fen_ok OR _counts_ok) AND disconnected_minus_chooser_material IS NOT NULL AND -disconnected_minus_chooser_material IS DISTINCT FROM ('+material+')').fetchone()[0]
            require(n==0, 'Stored material sign/value differs: '+r['month'])
        piece_signature="concat_ws(',',"+','.join('_'+role+'_'+p for role in ('chooser','disconnected') for p,_,_ in PIECES)+')'
        speed="CASE lower(api_speed) WHEN 'ultrabullet' THEN 'ultraBullet' WHEN 'bullet' THEN 'bullet' WHEN 'blitz' THEN 'blitz' WHEN 'rapid' THEN 'rapid' WHEN 'classical' THEN 'classical' ELSE 'excluded_other_speed' END"
        clock=lambda col:f'CASE WHEN isfinite({col}) AND {col}>=0 THEN {col}::DOUBLE ELSE NULL END'
        c.execute(f'''CREATE VIEW core AS SELECT game_id, {q(r['month'])} AS month,
            chooser_user_id::BIGINT chooser, outcome_kind_draw::TINYINT y,
            ({material})::SMALLINT deficit, {piece_signature} piece_signature,
            CASE WHEN _fen_ok THEN 'fen_verified' WHEN _counts_ok THEN 'cached_piece_counts' ELSE 'missing' END material_source,
            CASE WHEN NOT engine_eval_is_mate AND isfinite(engine_eval_cp_disconnected_raw)
                 THEN engine_eval_cp_disconnected_raw::DOUBLE ELSE NULL END cp,
            engine_eval_is_mate::BOOLEAN mate,engine_eval_cp_disconnected::DOUBLE board,
            {speed} speed,ply_count::INTEGER ply,
            CASE WHEN ply_count<=10 THEN 'ply_0_10' WHEN ply_count<=20 THEN 'ply_11_20'
                 WHEN ply_count<=40 THEN 'ply_21_40' WHEN ply_count<=80 THEN 'ply_41_80' ELSE 'ply_81_plus' END stage,
            {clock('chooser_clock_last_obs_s')} clock_c,{clock('disconnected_clock_last_obs_s')} clock_d,
            chooser_elo::DOUBLE rating, (disconnected_elo-chooser_elo)::DOUBLE rating_gap,
            to_timestamp(api_last_move_at_ms/1000.0)::DATE position_date,
            CASE WHEN api_last_move_at_ms<epoch_ms(TIMESTAMP '2025-07-19') THEN 'pre'
                 WHEN api_last_move_at_ms>=epoch_ms(TIMESTAMP '2025-08-11') THEN 'post'
                 ELSE 'buffer' END period
            FROM pieces''')
        query='''SELECT *, CASE WHEN mate THEN CASE WHEN board<0 THEN 'mate_losing' ELSE 'mate_winning' END
             WHEN cp IS NULL THEN 'missing_eval' WHEN cp < -100 THEN 'finite_lost' ELSE 'finite_competitive' END region,
             CASE WHEN cp IS NOT NULL THEN (10*floor(cp/10))::INTEGER END eval10,
             CASE speed WHEN 'ultraBullet' THEN 40 WHEN 'bullet' THEN 40 WHEN 'blitz' THEN 60
                        WHEN 'rapid' THEN 120 WHEN 'classical' THEN 300 ELSE NULL END long_clock_cut,
             CASE WHEN clock_d IS NULL THEN 'missing' WHEN clock_d<10 THEN '0_10' WHEN clock_d<20 THEN '10_20'
                  WHEN clock_d<40 THEN '20_40' WHEN clock_d<60 THEN '40_60' WHEN clock_d<120 THEN '60_120'
                  WHEN clock_d<300 THEN '120_300' ELSE '300_plus' END clock_d_bin,
             CASE WHEN clock_c IS NULL THEN 'missing' WHEN clock_c<10 THEN '0_10' WHEN clock_c<20 THEN '10_20'
                  WHEN clock_c<40 THEN '20_40' WHEN clock_c<60 THEN '40_60' WHEN clock_c<120 THEN '60_120'
                  WHEN clock_c<300 THEN '120_300' ELSE '300_plus' END clock_c_bin
             FROM core'''
        dest=out/'features.parquet'; n=copy(c,query,dest)
        require(n==r['rows'],'Projection lost rows')
        c.execute('CREATE VIEW p AS SELECT * FROM '+scan(dest))
        cols=['rows','grants','fen_verified','piece_counts_only','missing_material','finite_lost','finite_competitive','mate_rows','missing_eval','missing_clock','excluded_speed','unique_game_ids']
        row=c.execute('''SELECT count(*),coalesce(sum(y),0),count(*) FILTER(WHERE material_source='fen_verified'),
           count(*) FILTER(WHERE material_source='cached_piece_counts'),count(*) FILTER(WHERE material_source='missing'),
           count(*) FILTER(WHERE region='finite_lost'),count(*) FILTER(WHERE region='finite_competitive'),
           count(*) FILTER(WHERE mate),count(*) FILTER(WHERE region='missing_eval'),
           count(*) FILTER(WHERE clock_d IS NULL OR clock_c IS NULL),count(*) FILTER(WHERE speed='excluded_other_speed'),
           count(DISTINCT game_id) FROM p''').fetchone()
        counts=dict(zip(cols,map(int,row)))
        require(counts['rows']==counts['unique_game_ids'],'Duplicate games within month')
        require(stamp(src)==before,'Source changed during projection')
        result=dict(key=key,month=r['month'],counts=counts,output=record(dest),source_sha256=r['expected_sha256'],
                    source_stamp=before,elapsed_seconds=time.monotonic()-start,reused=False)
        write(receipt,result); return result
    finally: c.close()
