"""Validate complete SAN moves against fixed A1 targets; construct earlier boards."""
from __future__ import annotations
import math
import chess
import pyarrow as pa

class RecordProblem(ValueError):
    pass

def require(condition,reason):
    if not condition:raise RecordProblem(reason)

def required_positions(ply,color):
    require(color in ('white','black') and isinstance(ply,int) and ply>=0,'BAD_TARGET')
    last=ply if ply%2==(color=='white') else ply-1
    own=[m for m in (last,last-2) if m>0]
    return own,sorted({x for m in own for x in (m-1,m)})

def game_metadata(o,t):
    require(o.get('id')==t['exposure_game_id'],'GAME_ID_MISMATCH')
    require(o.get('variant')=='standard','NONSTANDARD_VARIANT')
    require(o.get('source')=='pool' and o.get('rated') is True,'POOL_OR_RATED_MISMATCH')
    require(o.get('status')=='timeout','STATUS_MISMATCH')
    for key,target in [('createdAt','api_created_at_ms'),('lastMoveAt','api_last_move_at_ms')]:
        require(o.get(key) is not None and t.get(target) is not None and o[key]==t[target],key.upper()+'_MISMATCH')
    own=t['disconnected_color'];other='black' if own=='white' else 'white'
    require(o.get('winner')==(None if t['received_mercy'] else other),'RESULT_MISMATCH')
    require(set(o.get('players',{}))=={'white','black'},'PLAYER_COLORS_MISSING')
    # Account IDs in the frozen target are dictionary integers, not API names.
    # We retain those original integers; no joins or remapping use API names.
    return own

def validated_game(o,t):
    color=game_metadata(o,t);ply=int(t['ply_count']);own,wanted=required_positions(ply,color)
    require(own==t['recipient_move_plies'] and wanted==t['board_plies'],'TARGET_BOARD_PLAN_CHANGED')
    initial=o.get('initialFen')
    require(initial in (None,'startpos',chess.STARTING_FEN),'NONSTANDARD_START')
    require(isinstance(o.get('moves'),str),'MISSING_MOVES')
    sans=o['moves'].split();require(len(sans)==ply,'PLY_COUNT_MISMATCH')
    board=chess.Board();positions=[];captures=[];last_captures={};is_capture={}
    if 0 in wanted:positions.append({'board_ply':0,'fen':board.fen()})
    for p,san in enumerate(sans,1):
        try:move=board.parse_san(san)
        except ValueError:raise RecordProblem('ILLEGAL_MOVE') from None
        require(board.is_legal(move),'ILLEGAL_MOVE')
        is_capture[p]=board.is_capture(move)
        if is_capture[p]:captures.append(p)
        board.push(move);last_captures[p]=captures[-1] if captures else None
        if p in wanted:positions.append({'board_ply':p,'fen':board.fen()})
    try:expected=chess.Board(t['fen_after_last_move'])
    except ValueError:raise RecordProblem('BAD_TARGET_FEN') from None
    require(board.is_valid() and board.fen()==expected.fen(),'FINAL_FEN_MISMATCH')
    require(board.turn==(color=='white'),'DISCONNECTED_COLOR_MISMATCH')
    clocks=o.get('clocks');clock_ok=isinstance(clocks,list) and len(clocks)==ply and all(
        isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=0 for x in clocks)
    clock_status='COMPLETE' if clock_ok else ('MISSING' if clocks in (None,[]) else 'LENGTH_OR_VALUE_MISMATCH')
    base={'cohort_row_id':t['cohort_row_id'],'exposure_game_id':t['exposure_game_id'],'month':t['month'],
          'received_mercy':bool(t['received_mercy']),'a1_att_weight':t['a1_att_weight'],
          'primary_conditional_choice':bool(t['primary_conditional_choice']),'recipient_color':color,
          'recipient_user_id':t['recipient_user_id'],'exposure_chooser_user_id':t['exposure_chooser_user_id'],
          'status':'VERIFIED','clock_status':clock_status,'recipient_move_plies':own,
          'plies_since_last_capture':ply-captures[-1] if captures else None,'no_capture_observed':not captures,
          'recipient_last_move_capture':is_capture.get(own[0]) if own else None,
          'recipient_last_clock_api_units':clocks[own[0]-1] if clock_ok and own else None,
          'chooser_last_clock_api_units':clocks[-1] if clock_ok and ply else None,
          'clock_initial_seconds':(o.get('clock') or {}).get('initial'),
          'clock_increment_seconds':(o.get('clock') or {}).get('increment')}
    # Preserve raw clocks and pre/post own-move readings. Do not call their
    # difference think time: increment/first-move/lag rules need their own audit.
    for i,p in enumerate(own,1):
        base[f'recipient_move_{i}_clock_after_api_units']=clocks[p-1] if clock_ok else None
        base[f'recipient_move_{i}_clock_previous_api_units']=clocks[p-3] if clock_ok and p>=3 else None
    return base,[{'cohort_row_id':t['cohort_row_id'],'exposure_game_id':t['exposure_game_id'],
                  'recipient_color':color,**p} for p in positions]

# Explicit schemas keep all-missing batches compatible with later Parquet joins.
GAME_FIELDS=[('cohort_row_id',pa.int64()),('exposure_game_id',pa.string()),('month',pa.string()),
('received_mercy',pa.bool_()),('a1_att_weight',pa.float64()),('primary_conditional_choice',pa.bool_()),
('recipient_color',pa.string()),('recipient_user_id',pa.int64()),('exposure_chooser_user_id',pa.int64()),
('status',pa.string()),('clock_status',pa.string()),('recipient_move_plies',pa.list_(pa.int64())),
('plies_since_last_capture',pa.int64()),('no_capture_observed',pa.bool_()),('recipient_last_move_capture',pa.bool_()),
('recipient_last_clock_api_units',pa.float64()),('chooser_last_clock_api_units',pa.float64()),
('clock_initial_seconds',pa.float64()),('clock_increment_seconds',pa.float64())]+[
(f'recipient_move_{i}_clock_{side}_api_units',pa.float64()) for i in (1,2) for side in ('after','previous')]
GAME_SCHEMA=pa.schema(GAME_FIELDS)
POSITION_SCHEMA=pa.schema([('cohort_row_id',pa.int64()),('exposure_game_id',pa.string()),
                         ('recipient_color',pa.string()),('board_ply',pa.int64()),('fen',pa.string())])

def replay_records(targets,records):
    games=[];positions=[]
    for t in targets:
        try:
            if t['exposure_game_id'] not in records:raise RecordProblem('NONRETURN')
            g,p=validated_game(records[t['exposure_game_id']],t)
        except RecordProblem as e:
            g={k:t.get(k) for k in ('cohort_row_id','exposure_game_id','month','received_mercy','a1_att_weight',
                'primary_conditional_choice','recipient_user_id','exposure_chooser_user_id')}
            g.update(status=str(e),recipient_color=t['disconnected_color'],recipient_move_plies=t['recipient_move_plies'],
                     received_mercy=bool(t['received_mercy']),primary_conditional_choice=bool(t['primary_conditional_choice']));p=[]
        games.append(g);positions.extend(p)
    return pa.Table.from_pylist(games,schema=GAME_SCHEMA),pa.Table.from_pylist(positions,schema=POSITION_SCHEMA)
