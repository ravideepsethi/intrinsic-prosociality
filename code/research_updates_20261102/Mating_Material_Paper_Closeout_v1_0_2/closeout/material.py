"""Original strict material screen on the corrected spaced exposure rows."""
from closeout_common import *
import chess
from collections import Counter

def material_from_fen(fen,ply):
    if fen is None or not str(fen).strip():return None,'missing_fen'
    try:
        if len(str(fen).split())!=6:return None,'invalid_fen'
        board=chess.Board(str(fen))
        if not board.is_valid():return None,'invalid_board'
        if ply is None or not np.isfinite(ply) or int(ply)!=ply or board.ply()!=int(ply):return None,'ply_mismatch'
        weights={chess.PAWN:1,chess.KNIGHT:3,chess.BISHOP:3,chess.ROOK:5,chess.QUEEN:9}
        return int(sum(v*(len(board.pieces(p,chess.WHITE))-len(board.pieces(p,chess.BLACK))) for p,v in weights.items())),'valid'
    except (ValueError,TypeError,OverflowError):return None,'invalid_fen'

def neutral(material):return material is not None and -4<material<4

def month_job(job):
    def build(tmp):
        db=connect(tmp,3.)
        try:
            view(db,'q',job['source']);view(db,'s',job['panel'])
            db.execute('CREATE VIEW month AS SELECT row_id,game_id,recipient_id,opponent_id,anchor_ms,received,y,reached FROM q WHERE month_code='+str(job['month_code']))
            n=db.execute('SELECT count(*) FROM month').fetchone()[0]
            check=db.execute('''SELECT count(*),count(DISTINCT q.row_id),count(*) FILTER(WHERE q.recipient_id IS DISTINCT FROM s.disconnected_user_id OR q.opponent_id IS DISTINCT FROM s.chooser_user_id OR q.anchor_ms IS DISTINCT FROM s.api_last_move_at_ms OR q.received IS DISTINCT FROM s.kind_draw OR NOT coalesce(isfinite(s.engine_eval_cp_disconnected),FALSE) OR s.engine_eval_cp_disconnected< -100) FROM month q JOIN s USING(game_id)''').fetchone()
            require(check==(n,n,0),'Material identity/label/board bridge failed: '+job['month'])
            copy(db,'SELECT q.row_id,s.fen_after_last_move,s.ply_count,q.received,q.y,q.reached FROM month q JOIN s USING(game_id) ORDER BY row_id',tmp/'fens_PRIVATE.parquet')
        finally:db.close()
        counts=Counter();totals={};seen=0;schema=pa.schema([('row_id',pa.int64()),('material_white_minus_black',pa.int16()),('material_valid',pa.bool_()),('material_neutral',pa.bool_()),('material_status',pa.string())])
        with pq.ParquetWriter(tmp/'material.parquet',schema,compression='zstd') as writer:
            for batch in pq.ParquetFile(tmp/'fens_PRIVATE.parquet').iter_batches(batch_size=16384,use_threads=False):
                d=batch.to_pydict();parsed=[material_from_fen(f,p) for f,p in zip(d['fen_after_last_move'],d['ply_count'])]
                values=[x[0] for x in parsed];statuses=[x[1] for x in parsed];counts.update(statuses)
                valid=np.array([s=='valid' for s in statuses]);keep=np.array([neutral(v) for v in values])
                writer.write_table(pa.Table.from_pydict(dict(row_id=d['row_id'],material_white_minus_black=values,material_valid=valid,material_neutral=keep,material_status=statuses),schema=schema))
                seen+=batch.num_rows
                for label,mask in [('all',np.ones(batch.num_rows,bool)),('valid',valid),('strict_lt4',keep)]:
                    rec=totals.setdefault(label,dict(rows=0,received=0,y=0,reached=0));rec['rows']+=int(mask.sum())
                    for k in ('received','y','reached'):rec[k]+=int(np.asarray(d[k])[mask].sum())
        require(seen==n,'Material parser lost rows');save(tmp/'summary.json',dict(month=job['month'],rows=n,status_counts=dict(counts),flow=totals))
        return dict(rows=n)
    return stage(Path(job['output']),job['conf'],build,[job['source'],job['panel']])[1]

def run_all(a,run,conf,auth):
    src=auth['paths']['spaced'];scores=auth['paths']['spaced_scores'];jobs=[]
    for k,rec in enumerate(sorted(auth['panels'],key=lambda r:r['month'])):
        jobs.append(dict(source=src,panel=rec['path'],month=rec['month'],month_code=k,output=str(run/'PRIVATE/material_months'/rec['month']),conf=conf))
    c.mapped(month_job,jobs,min(2,a.workers),'Final-position material')
    summaries=[read(Path(j['output'])/'summary.json') for j in jobs]
    require(sum(x['rows'] for x in summaries)==rows(src),'Material months do not exhaust spaced exposures')
    paths=[Path(j['output'])/'material.parquet' for j in jobs]
    def select(tmp):
        db=connect(tmp,4.)
        try:
            view(db,'m',paths)
            assert_zero(db,'SELECT count(*) FROM (SELECT row_id FROM m GROUP BY 1 HAVING count(*)<>1)','Duplicate material identity')
            # Sort one integer key, then stream both wide payloads exactly.
            copy(db,'SELECT row_id FROM m WHERE material_valid AND material_neutral ORDER BY row_id',tmp/'selected_ids.parquet')
        finally:db.close()
        import stream_frames
        stream_frames.select(src,tmp/'source.parquet',ids=tmp/'selected_ids.parquet')
        stream_frames.select(scores,tmp/'scores.parquet',ids=tmp/'selected_ids.parquet')
        require(rows(tmp/'source.parquet')==rows(tmp/'scores.parquet')==rows(tmp/'selected_ids.parquet'),'Material subset coverage differs')
        return dict(rows=rows(tmp/'source.parquet'))
    folder,_=stage(run/'PRIVATE/material_subset',conf,select,[src,scores]+paths)
    import model_kernel as m
    job=m.job_for(run,conf,'spaced_material_strict_lt4',folder/'source.parquet',folder/'scores.parquet',legacy=True)
    with heartbeat('Strict material sensitivity'):m.fit(job)
    m.export_models(run)
    base=m.job_for(run,PARENT_CONF,'legacy_spaced','','',legacy=True);base['output']=str(a.parent/'PRIVATE/models/legacy_spaced')
    contrast=m.contrast(run,conf,job,base,'strict_material_minus_spaced',['iv_y'])
    public_csv(run/'report/material_contrast.csv',contrast)
    save(run/'report/MATERIAL_SCREEN.json',dict(status='COMPLETE',monthly=summaries,
        rows_before=rows(src),rows_after=rows(folder/'source.parquet'),rule='-4 < white-minus-black material < 4; P1/N3/B3/R5/Q9; exact six-field FEN, valid board and FEN ply match',
        donor_history_changed=False,post_assignment_sensitivity=True,
        limitation='Does not eliminate play bans, rating effects, prior sorting, or selection into active resolution.'))
