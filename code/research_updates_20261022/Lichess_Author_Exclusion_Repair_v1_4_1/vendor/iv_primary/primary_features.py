"""Reattach existing position/payoff features to every rebuilt primary row."""
from primary_common import *

def prepare(a,run,conf,b):
    root=run/'PRIVATE/position_features';source=b['primary']
    files,manifest=frozen.u.full_source_panels(a.project);paths=[x['path'] for x in files]
    require(len(paths)==24,'Position feature source requires all 24 authenticated months')
    def build(tmp):
        c=db(tmp/'spill',a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]))
            c.execute('CREATE VIEW p AS SELECT * FROM '+parq(paths))
            names=set(pq.ParquetFile(paths[0]).schema_arrow.names)
            grant='kind_draw' if 'kind_draw' in names else 'outcome_kind_draw'
            check=c.execute(f'''SELECT count(*),count(DISTINCT q.row_id),count(*) FILTER(WHERE
              q.recipient_id IS DISTINCT FROM p.disconnected_user_id OR q.opponent_id IS DISTINCT FROM p.chooser_user_id
              OR q.archive_start_ms IS DISTINCT FROM p.utc_ms OR q.anchor_ms IS DISTINCT FROM p.api_last_move_at_ms
              OR q.received IS DISTINCT FROM p.{grant}) FROM q JOIN p USING(game_id)''').fetchone()
            require(check==(EXPECTED_N,EXPECTED_N,0),'New position features identity/time/treatment bridge failed')
            query='''SELECT q.row_id,p.chooser_color,p.disconnected_color,
              p.chooser_win_premium_v2 giver_cost,p.chooser_draw_payoff_v2 giver_draw,p.chooser_win_payoff_v2 giver_win,
              p.chooser_pre_rd_v2 giver_rd,p.disconnected_pre_rd_v2 recipient_rd,
              CASE p.disconnected_color WHEN 'white' THEN p.white_win_premium_v2 WHEN 'black' THEN p.black_win_premium_v2 END recipient_benefit,
              CASE p.disconnected_color WHEN 'white' THEN p.white_draw_ratingdiff_v2 WHEN 'black' THEN p.black_draw_ratingdiff_v2 END recipient_draw,
              CASE p.disconnected_color WHEN 'white' THEN p.white_win_ratingdiff_v2 WHEN 'black' THEN p.black_win_ratingdiff_v2 END recipient_win,
              p.engine_eval_cp_disconnected board_cp,p.ply_count ply,p.chooser_clock_last_obs_s giver_clock,
              p.disconnected_clock_last_obs_s recipient_clock,p.fen_after_last_move
              FROM q JOIN p USING(game_id) ORDER BY q.row_id'''
            copy_query(c,query,tmp/'dose_PRIVATE.parquet')
            c.execute('CREATE VIEW d AS SELECT * FROM '+parq([tmp/'dose_PRIVATE.parquet']))
            bad=c.execute('''SELECT count(*) FROM d WHERE NOT coalesce(
              isfinite(giver_cost) AND giver_cost>0 AND isfinite(recipient_benefit) AND recipient_benefit>0
              AND abs(giver_win-giver_draw-giver_cost)<1e-7 AND abs(recipient_win-recipient_draw-recipient_benefit)<1e-7
              AND isfinite(giver_rd) AND giver_rd>0 AND isfinite(recipient_rd) AND recipient_rd>0
              AND isfinite(board_cp) AND board_cp>=-100 AND isfinite(ply) AND ply>=0
              AND isfinite(giver_clock) AND isfinite(recipient_clock)
              AND chooser_color IN ('white','black') AND disconnected_color IN ('white','black'),false)''').fetchone()[0]
            require(bad==0,'Missing or invalid dose feature: no deletion or imputation is allowed')
            copy_query(c,'SELECT * EXCLUDE(fen_after_last_move) FROM d ORDER BY row_id',tmp/'act.parquet')
        finally:c.close()
        import iv_material
        writer=None;count={};valid_n=neutral_n=0
        try:
            for batch in pq.ParquetFile(tmp/'dose_PRIVATE.parquet').iter_batches(columns=['row_id','fen_after_last_move','ply'],batch_size=32768,use_threads=False):
                d=batch.to_pydict();parsed=[iv_material.material_from_fen(f,p) for f,p in zip(d['fen_after_last_move'],d['ply'])]
                values=[x[0] for x in parsed];status=[x[1] for x in parsed]
                valid=[s=='valid' for s in status];neutral=[iv_material.neutral(x) for x in values]
                for s in status:count[s]=count.get(s,0)+1
                valid_n+=sum(valid);neutral_n+=sum(neutral)
                t=pa.table(dict(row_id=d['row_id'],material_valid=valid,material_neutral=neutral,
                                material_white_minus_black=pa.array(values,type=pa.int16())))
                if writer is None:writer=pq.ParquetWriter(tmp/'material.parquet',t.schema,compression='zstd')
                writer.write_table(t)
        finally:
            if writer:writer.close()
        info=dict(rows=EXPECTED_N,payoff_and_identity_checks_passed=True,new_engine_evaluations=0,new_API_calls=0,
                  material_valid_rows=valid_n,neutral_rows=neutral_n,material_status_counts=count,
                  neutral_rule='strict -4 < white-minus-black material < 4; invalid material excluded only from neutral sensitivity',
                  recipient_benefit='Existing recipient-side win-minus-draw premium; same common-scale replay interpretation as R9b')
        save(tmp/'summary.json',info);return info
    folder,meta=frozen.r.stable_stage(root,conf,build,[source,manifest]+paths)
    save(run/'report/position_feature_checks.json',load(folder/'summary.json'))
    save(run/'PRIVATE/POSITION_FEATURES.json',dict(act=str(folder/'act.parquet'),material=str(folder/'material.parquet')))
    return folder/'act.parquet',folder/'material.parquet'
