from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from mmrerun.material import fen_state, ROLES
from mmrerun.io import record, signature

FIXTURES = [
    ("bare_king", "6k1/8/8/8/8/8/8/4K3 b - - 0 1", True),
    ("knight_vs_king", "6k1/8/8/8/8/8/8/4K1N1 b - - 0 1", True),
    ("knight_vs_queen", "q5k1/8/8/8/8/8/8/4K1N1 b - - 0 1", True),
    ("knight_vs_rook", "r5k1/8/8/8/8/8/8/4K1N1 b - - 0 1", False),
    ("two_knights", "6k1/8/8/8/8/8/8/4KNN1 b - - 0 1", False),
    ("bishop_vs_king", "6k1/8/8/8/8/8/8/4KB2 b - - 0 1", True),
    ("bishops_same_color", "2b3k1/8/8/8/8/8/8/4KB2 b - - 0 1", True),
    ("bishops_opposite_color", "3b2k1/8/8/8/8/8/8/4KB2 b - - 0 1", False),
    ("bishop_vs_pawn", "6k1/p7/8/8/8/8/8/4KB2 b - - 0 1", False),
    ("two_same_color_bishops", "6k1/8/8/8/8/8/8/3BKB2 b - - 0 1", True),
    ("two_opposite_color_bishops", "6k1/8/8/8/8/8/8/2B1KB2 b - - 0 1", False),
    ("rook", "6k1/8/8/8/8/8/8/R3K3 b - - 0 1", False),
]


def row(name, fen, drop, index=0, color="white", chooser=None, result="1/2-1/2", month="2023-11"):
    own,other,_=fen_state(fen,color=="white")
    p,n,b,r,q=own
    old=bool(p>0 or r>0 or q>0 or b>=2 or (b>0 and n>0) or n>=2)
    draw=result=="1/2-1/2"
    win=(result=="1-0" and color=="white") or (result=="0-1" and color=="black")
    winner=None if draw else ("white" if result=="1-0" else "black")
    rec=dict(game_id=f"game{index:06}",month=month,chooser_username_norm=chooser or f"chooser{index%4}",
        disconnected_username_norm=f"opponent{index%5}",chooser_color=color,
        disconnected_color="black" if color=="white" else "white",fen_after_last_move=fen,pgn_result=result,
        api_status="timeout",chooser_has_mating_material=old,outcome_kind_draw=draw and old,kind_draw=draw and old,
        engine_eval_cp_disconnected=0 if drop else [-300,-101,0,101,300][index%5],ply_count=index*4,
        api_speed="blitz",chooser_elo=1500,chooser_win_premium_v2=5.5+index/10,
        timeout_draw=draw,timeout_chooser_win=win,timeout_chooser_loss=not (draw or win),
        timeout_draw_no_mating_material=draw and not old,api_winner=winner,
        api_is_draw=draw,api_rated=True,api_variant="standard",pgn_api_result_consistent=True,
        never_touch_me=f"sentinel {name}",chooser_draw_payoff_v2=-1.25,utc_ms=1700000000000+index)
    for side,counts in [("chooser",own),("disconnected",other)]:
        for role,value in zip(ROLES,counts):rec[side+"_"+role]=int(value)
    return rec


def make_rows():
    return [row(name,fen,drop,i) for i,(name,fen,drop) in enumerate(FIXTURES)]


def write_input(root, family, data, row_group_size=3):
    path=Path(root)/(family+".parquet")
    table=pa.Table.from_pylist(data)
    # Entirely-null api_winner can otherwise be inferred as null rather than string.
    table=table.set_column(table.schema.get_field_index("api_winner"),"api_winner",pa.array([r["api_winner"] for r in data],type=pa.string()))
    pq.write_table(table,path,row_group_size=row_group_size,compression="zstd")
    return dict(record(path),family=family,month="2023-11",rows=len(data),signature=signature(path),
        columns=table.column_names,already_author_excluded=family=="main")


def config(root):
    return dict(run=str(Path(root)/"run"),id="synthetic_1234",results_dir=str(Path(root)/"results"),
        workers=2,memory_gb=4,batch_rows=5,verify_all_fens=False,code_sha256="synthetic",
        input_identity="synthetic",environment={},source_commit="synthetic",pipeline_commit="synthetic")
