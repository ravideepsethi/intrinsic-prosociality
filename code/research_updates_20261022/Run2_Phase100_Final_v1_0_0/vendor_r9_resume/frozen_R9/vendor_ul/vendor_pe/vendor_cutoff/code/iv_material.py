"""Final-position material, not engine merit or recent material change."""
from iv_common import *
import chess
from collections import Counter

def material_from_fen(fen,ply):
    if fen is None or not str(fen).strip():return None,'missing_fen'
    try:
        if len(str(fen).split())!=6:return None,'invalid_fen'
        board=chess.Board(str(fen))
        if not board.is_valid():return None,'invalid_board'
        if ply is None or not np.isfinite(ply) or int(ply)!=ply or board.ply()!=int(ply):
            return None,'ply_mismatch'
        weights={chess.PAWN:1,chess.KNIGHT:3,chess.BISHOP:3,chess.ROOK:5,chess.QUEEN:9}
        balance=sum(value*(len(board.pieces(piece,chess.WHITE))-len(board.pieces(piece,chess.BLACK)))
                    for piece,value in weights.items())
        return int(balance),'valid'
    except (ValueError,TypeError,OverflowError):return None,'invalid_fen'

def neutral(material):return material is not None and -4<material<4

def attach(source,project,root,conf,memory):
    # Sources resolved only from the authenticated main-panel input manifest.
    files,manifest=u.full_source_panels(project)
    paths=[v['path'] for v in files]
    def build(tmp):
        names=[set(pq.ParquetFile(p).schema_arrow.names) for p in paths]
        required={'fen_after_last_move','ply_count','game_id','chooser_user_id','disconnected_user_id',
                  'api_last_move_at_ms','engine_eval_cp_disconnected'}
        absent=sorted(set.union(*(required-n for n in names)))
        if absent:
            info=dict(status='MATERIAL_SOURCE_UNAVAILABLE',missing_columns=absent,
                source_files=len(paths),imputed_rows=0,
                reason='No guessed FEN alias, move-change proxy, or API fallback is allowed.')
            r.io.js(tmp/'summary.json',info);return info
        grant='kind_draw' if all('kind_draw' in n for n in names) else 'outcome_kind_draw'
        u.require(all(grant in n for n in names),'Active grant outcome column is unavailable')
        c=u.conn(tmp/'spill',max(1,memory-2),1)
        try:
            c.execute('CREATE VIEW q AS SELECT row_id,game_id,recipient_id,opponent_id,anchor_ms,received,y,reached FROM '+u.parq([source]))
            c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq(paths))
            bridge=c.execute(f'''SELECT count(*),count(DISTINCT q.row_id),count(*) FILTER(WHERE
              q.recipient_id IS DISTINCT FROM s.disconnected_user_id OR
              q.opponent_id IS DISTINCT FROM s.chooser_user_id OR
              q.anchor_ms IS DISTINCT FROM s.api_last_move_at_ms OR
              q.received IS DISTINCT FROM s.{grant}) FROM q JOIN s USING(game_id)''').fetchone()
            n=pq.ParquetFile(source).metadata.num_rows
            u.require(bridge==(n,n,0),'Material source identity/time/treatment bridge failed')
            bad=c.execute('''SELECT count(*) FROM q JOIN s USING(game_id)
              WHERE s.engine_eval_cp_disconnected IS NULL OR NOT isfinite(s.engine_eval_cp_disconnected)
              OR s.engine_eval_cp_disconnected < -100''').fetchone()[0]
            u.require(bad==0,'Frozen competitive exposure definition differs in material source')
            r.io.copy(c,'''SELECT q.row_id,s.fen_after_last_move,s.ply_count,q.received,q.y,q.reached
              FROM q JOIN s USING(game_id) ORDER BY q.row_id''',tmp/'fens_PRIVATE.parquet')
        finally:r.finish_connection(c,tmp/'spill')
        writer=None;counts=Counter();totals={};n_done=0
        try:
            for batch in pq.ParquetFile(tmp/'fens_PRIVATE.parquet').iter_batches(batch_size=32768,use_threads=False):
                a=batch.to_pydict();parsed=[material_from_fen(f,p) for f,p in zip(a['fen_after_last_move'],a['ply_count'])]
                values=[p[0] for p in parsed];statuses=[p[1] for p in parsed];counts.update(statuses)
                valid=[s=='valid' for s in statuses];keep=[neutral(v) for v in values]
                table=pa.table(dict(row_id=a['row_id'],material_white_minus_black=pa.array(values,type=pa.int16()),
                    material_valid=valid,material_neutral=keep,material_status=statuses))
                if writer is None:writer=pq.ParquetWriter(tmp/'material.parquet',table.schema,compression='zstd')
                writer.write_table(table);n_done+=len(batch)
                for label,mask in [('all',np.ones(len(batch),bool)),('observed',np.asarray(valid)),('neutral',np.asarray(keep))]:
                    t=totals.setdefault(label,dict(rows=0,received=0,y=0,reached=0))
                    t['rows']+=int(mask.sum())
                    for k in ('received','y','reached'):t[k]+=int(np.asarray(a[k])[mask].sum())
        finally:
            if writer:writer.close()
        info=dict(status='MATERIAL_SCREEN_COMPLETE',rows=n_done,status_counts=dict(counts),flow=totals,
            threshold='-4 < white-minus-black material < 4; endpoints excluded',
            competitive_exposure_cp_minimum=-100,donor_history_unchanged=True,imputed_rows=0,
            source='authenticated final-position fen_after_last_move; board validity and FEN ply checked',
            interpretation='Neutralizes the immediate numerical material-based rageSit increment only; does not neutralize disciplinary outcomes, rating effects, prior sorting, or post-assignment selection.')
        r.io.js(tmp/'summary.json',info);return info
    folder,info=r.stable_stage(root,conf,build,[source,manifest]+paths)
    return (folder/'material.parquet' if (folder/'material.parquet').exists() else None),r.io.load(folder/'summary.json')
