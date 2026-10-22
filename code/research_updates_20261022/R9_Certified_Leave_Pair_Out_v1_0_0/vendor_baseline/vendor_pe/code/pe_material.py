"""Audit existing Parquet final positions before attempting an ordinary screen.

This is a cache coverage audit, not a new PGN-replay or API extraction. A file
must expose documented endpoint FEN/ply and the full frozen exposure identity.
Raw move-only caches are reported separately, never counted as missing games.
"""
from pe_common import *
from pe_scores import IDENTITY
from iv_material import material_from_fen, neutral

BRIDGE = ('game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms')
REQUIRED = set(BRIDGE) | {'fen_after_last_move','ply_count'}

def inventory(paths, binding, project, r7root):
    candidates = {str(Path(paths[k]).resolve()) for k in ('O50','F50')}
    f = u.relocate(binding['phase50']['root'], project)/'assembled/features.parquet'
    check_stage(f.parent, binding['phase50']['conf'], [f.name])
    candidates.add(str(f.resolve()))
    inv = Path(r7root)/'composition/move_inventory_PRIVATE.json'
    records = u.load(inv) if inv.exists() else []
    nonparquet = 0
    for rec in records:
        path = u.relocate(rec['path'], project)
        if path.suffix == '.parquet': candidates.add(str(path.resolve()))
        else: nonparquet += 1
    rows = []; usable = []; move_only = 0
    for value in sorted(candidates):
        p = Path(value)
        if not p.is_file():
            rows.append(dict(source=p.name, status='FILE_UNAVAILABLE')); continue
        pf = pq.ParquetFile(p); names = set(pf.schema_arrow.names)
        direct = REQUIRED <= names
        has_moves = bool(names & {'moves','pgn_moves','movetext','pgn','metadata_json','raw_json','response_json','api_json'})
        if has_moves and not direct: move_only += 1
        rows.append(dict(source=p.name, rows=pf.metadata.num_rows, usable_endpoint_contract=direct,
            has_documented_final_fen='fen_after_last_move' in names, has_recorded_moves_or_json=has_moves,
            missing_required_columns=sorted(REQUIRED-names)))
        if direct: usable.append(str(p))
    info = dict(sources=rows, candidate_parquets=len(rows), directly_usable_parquets=len(usable),
        move_or_json_parquets_requiring_separate_replay=move_only, nonparquet_move_cache_files_not_replayed=nonparquet,
        scope='Frozen O50/F50/Phase50 feature tables and Parquets in completed R7 move-cache inventory',
        not_a_complete_raw_move_coverage_audit=True, api_requests=0, stockfish_searches=0)
    return usable, info

def audit(ordinary, candidates, inventory_info, root, conf, memory):
    def build(tmp):
        info = dict(inventory_info, ordinary_rows=pq.ParquetFile(ordinary).metadata.num_rows,
            threshold='-4 < white-minus-black material < 4; endpoints excluded', imputed_rows=0,
            ordinary_competitive_cp_screen=False,
            interpretation='Material-only ordinary-ending sensitivity if available; ordinary endings have no certified disconnected-player cp counterpart')
        if not candidates:
            info.update(status='NO_USABLE_FINAL_POSITION_PARQUET', material_coverage_fraction=None,
                restricted_placebo_run=False,
                next_requirement='A separate cached-move replay/identity audit is needed; raw move availability has not been established or ruled out')
            r.io.js(tmp/'summary.json',info); return info
        c = u.conn(tmp/'spill', memory, 1)
        try:
            c.execute('CREATE VIEW o AS SELECT * FROM '+u.parq([ordinary]))
            pieces = []
            for k,path in enumerate(candidates):
                cols = ','.join(sorted(REQUIRED))
                c.execute('CREATE OR REPLACE VIEW p AS SELECT '+cols+' FROM '+u.parq([path]))
                terms = ' OR '.join('o.'+v+' IS DISTINCT FROM p.'+v for v in BRIDGE if v!='game_id')
                u.require(c.execute('SELECT count(*) FROM o JOIN p USING(game_id) WHERE '+terms).fetchone()[0]==0,
                    'Cached ordinary position disagrees with the frozen exposure identity')
                dest=tmp/f'part_{k:04}.parquet'
                r.io.copy(c,'SELECT p.game_id,p.fen_after_last_move,p.ply_count FROM p SEMI JOIN o USING(game_id)',dest)
                pieces.append(dest)
            c.execute('CREATE OR REPLACE VIEW p AS SELECT * FROM '+u.parq(pieces))
            c.execute('''CREATE TEMP TABLE positions AS SELECT game_id,
                count(DISTINCT struct_pack(fen:=fen_after_last_move,ply:=ply_count)) variants,
                min(fen_after_last_move) fen_after_last_move,min(ply_count) ply_count FROM p GROUP BY game_id''')
            q='''SELECT o.row_id,p.fen_after_last_move,p.ply_count,coalesce(p.variants,0) variants
                FROM o LEFT JOIN positions p USING(game_id) ORDER BY o.row_id'''
            bridge=tmp/'bridge.parquet';r.io.copy(c,q,bridge)
            schema=pa.schema([('row_id',pa.int64()),('material_valid',pa.bool_()),('material_neutral',pa.bool_()),
                ('material_white_minus_black',pa.int16()),('material_status',pa.string())])
            counts={};valid=0;balanced=0
            with pq.ParquetWriter(tmp/'material.parquet',schema,compression='zstd') as w:
                for batch in pq.ParquetFile(bridge).iter_batches(batch_size=32768,use_threads=False):
                    out=[]
                    for row in batch.to_pylist():
                        if row['variants']>1: value,status=None,'conflicting_cached_positions'
                        else: value,status=material_from_fen(row['fen_after_last_move'],row['ply_count'])
                        ok=status=='valid'; keep=ok and neutral(value)
                        valid+=ok;balanced+=keep;counts[status]=counts.get(status,0)+1
                        out.append(dict(row_id=row['row_id'],material_valid=ok,material_neutral=keep,
                            material_white_minus_black=value,material_status=status))
                    w.write_table(pa.Table.from_pylist(out,schema=schema))
            for path in pieces+[bridge]:path.unlink()
            info.update(status='FINAL_POSITION_PARQUET_AUDIT_COMPLETE', valid_rows=valid, neutral_rows=balanced,
                material_coverage_fraction=valid/info['ordinary_rows'] if info['ordinary_rows'] else 0,
                status_counts=counts, restricted_placebo_run=balanced>=2000,
                requested_screens=['observed','neutral'] if balanced>=2000 else [])
            r.io.js(tmp/'summary.json',info);return info
        finally:r.finish_connection(c,tmp/'spill')
    folder,info=r.stable_stage(root,conf,build,[ordinary]+candidates)
    return (folder/'material.parquet' if info.get('restricted_placebo_run') else None),info
