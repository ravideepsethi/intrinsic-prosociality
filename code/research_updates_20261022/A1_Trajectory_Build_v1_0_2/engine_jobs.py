"""Single-thread Stockfish workers with per-batch atomic checkpoints."""
from __future__ import annotations
import collections,os,re,shutil,time
from pathlib import Path
import chess,chess.engine
import pyarrow as pa
import local_io as io

ENGINE=None
ENGINE_COMMAND=None
SCORE_CACHE=collections.OrderedDict()
SCORE_SCHEMA=pa.schema([('cohort_row_id',pa.int64()),('exposure_game_id',pa.string()),
 ('recipient_color',pa.string()),('board_ply',pa.int64()),('fen',pa.string()),
 ('status',pa.string()),('cp_recipient',pa.int64()),('mate_recipient',pa.int64()),
 ('mate_favors_recipient',pa.bool_()),('nodes',pa.int64()),('depth',pa.int64()),('seconds',pa.float64()),
 ('score_bound',pa.bool_()),('search_executed',pa.bool_())])
FEATURE_FIELDS=[('trajectory_positions',pa.int64()),('trajectory_below_node_budget',pa.int64()),
 ('trajectory_mate_positions',pa.int64()),('trajectory_all_requested_nodes_reached',pa.bool_())]+[
 (f'recipient_move_{i}_{name}',typ) for i in (1,2) for name,typ in [
 ('cp_before',pa.int64()),('cp_after',pa.int64()),('cp_change',pa.int64()),('cp_loss',pa.int64()),
 ('has_mate_score',pa.bool_()),('score_full_nodes',pa.bool_())]]

def find_engine(project,explicit=None):
    if explicit:
        p=Path(explicit).expanduser().resolve()
        if not p.is_file() or not os.access(p,os.X_OK):raise RuntimeError('Requested engine is not executable')
        return p
    candidates=[shutil.which('stockfish'),'/opt/homebrew/bin/stockfish','/usr/local/bin/stockfish']
    for root in (Path(project)/'tools',Path(project)/'bin',Path(project)/'engines',Path(project)/'replication_package'):
        if root.is_dir():
            for base,dirs,files in os.walk(root,followlinks=False):
                dirs[:]=[d for d in sorted(dirs) if not d.startswith('.') and d not in ('node_modules','vendor')]
                if len(Path(base).relative_to(root).parts)>=3:dirs[:]=[]
                for name in sorted(files):
                    if name.lower().startswith('stockfish'):candidates.append(str(Path(base)/name))
    for candidate in candidates:
        if candidate:
            p=Path(candidate)
            if p.is_file() and os.access(p,os.X_OK):return p.resolve()
    raise RuntimeError('Stockfish not found; set A1_TRAJ_STOCKFISH to the binary used in the preparation run')

def probe(path,expected_sha):
    if io.sha(path)!=expected_sha:raise RuntimeError('Stockfish binary differs from the certified preparation engine')
    with chess.engine.SimpleEngine.popen_uci(str(path),timeout=60) as engine:
        if not re.search(r'\bStockfish\s+18(?:\b|\.)',engine.id.get('name','')):raise RuntimeError('Stockfish 18 required')
        engine.configure({'Threads':1,'Hash':64})
        return {'name':engine.id.get('name'),'sha256':expected_sha,'threads':1,'hash_mb':64,'nodes_requested':100000,
                'fresh_game_per_position':True,'board_input':'standalone normalized FEN; no move stack'}

def prepare_worker(path):
    """A pool initializer must not leave a UCI background thread running.

    Python 3.13 joins threads before multiprocessing finalizers. Each batch
    therefore owns and explicitly closes its engine before returning.
    The bounded score cache can still be reused across batches in this worker.
    """
    global ENGINE_COMMAND
    ENGINE_COMMAND=path
    SCORE_CACHE.clear()

def init_engine(path):
    global ENGINE
    if ENGINE is not None:raise RuntimeError('Engine already open in this worker')
    ENGINE=chess.engine.SimpleEngine.popen_uci(path,timeout=180)
    try:ENGINE.configure({'Threads':1,'Hash':64})
    except BaseException:
        close_engine()
        raise

def close_engine():
    global ENGINE
    engine=ENGINE;ENGINE=None
    if engine is not None:
        engine.timeout=5
        try:engine.quit()
        except Exception:pass
        finally:engine.close()
        # Ensure the subprocess is gone before this worker can accept another
        # batch. Closing the transport also releases the UCI background thread.
        engine.returncode.result(timeout=10)

def score_position(row,engine=None):
    engine=engine or ENGINE
    if engine is None:raise RuntimeError('Engine worker was not initialized')
    board=chess.Board(row['fen'])
    if not board.is_valid():raise RuntimeError('Invalid reconstructed board')
    out={**row,'cp_recipient':None,'mate_recipient':None,'mate_favors_recipient':None,
         'nodes':0,'depth':None,'seconds':0.0,'score_bound':False,'search_executed':False}
    if board.is_game_over(claim_draw=False):
        out['status']='TERMINAL_POSITION';return out
    started=time.monotonic()
    info=engine.analyse(board,chess.engine.Limit(nodes=100000),game=object())
    score=info.get('score')
    if score is None:raise RuntimeError('Engine omitted its score')
    bound=bool(info.get('lowerbound') or info.get('upperbound'))
    pov=score.pov(row['recipient_color']=='white');nodes=int(info.get('nodes',0))
    out.update(status='BOUNDED_SCORE' if bound else ('SCORED' if nodes>=100000 else 'SCORED_BELOW_REQUESTED_NODES'),nodes=nodes,
               cp_recipient=None if bound else pov.score(),mate_recipient=pov.mate(),score_bound=bound,search_executed=True,
               mate_favors_recipient=(pov>chess.engine.Cp(0)) if pov.is_mate() else None,
               depth=info.get('depth'),seconds=time.monotonic()-started)
    return out

def cached_score(row):
    key=(row['fen'],row['recipient_color'])
    if key in SCORE_CACHE:
        saved=SCORE_CACHE.pop(key);SCORE_CACHE[key]=saved
        return {**row,**saved,'seconds':0.0,'search_executed':False}
    if ENGINE is None:
        if ENGINE_COMMAND is None:raise RuntimeError('Engine worker was not initialized')
        init_engine(ENGINE_COMMAND)
    result=score_position(row)
    SCORE_CACHE[key]={k:v for k,v in result.items() if k not in row}
    if len(SCORE_CACHE)>4096:SCORE_CACHE.popitem(last=False)
    return result

def game_features(games,scores):
    by_game=collections.defaultdict(dict)
    for p in scores:
        key=(p['cohort_row_id'],p['board_ply'])
        if p['board_ply'] in by_game[p['cohort_row_id']]:raise RuntimeError('Duplicate trajectory board')
        by_game[p['cohort_row_id']][p['board_ply']]=p
    out=[]
    for g in games:
        p=by_game[g['cohort_row_id']];r=dict(g)
        r.update(trajectory_positions=len(p),trajectory_below_node_budget=sum(x['nodes']<100000 for x in p.values()),
            trajectory_mate_positions=sum(x['mate_recipient'] is not None for x in p.values()),
            trajectory_all_requested_nodes_reached=bool(p) and all(x['nodes']>=100000 for x in p.values()))
        for i,m in enumerate(g.get('recipient_move_plies') or [],1):
            a=p.get(m-1);b=p.get(m)
            if a is None or b is None:
                if g['status']=='VERIFIED':raise RuntimeError('Missing engine board in verified game')
                continue
            prefix=f'recipient_move_{i}_';before=a['cp_recipient'];after=b['cp_recipient']
            r.update({prefix+'cp_before':before,prefix+'cp_after':after,
                prefix+'cp_change':after-before if before is not None and after is not None else None,
                prefix+'cp_loss':before-after if before is not None and after is not None else None,
                prefix+'has_mate_score':a['mate_recipient'] is not None or b['mate_recipient'] is not None,
                prefix+'score_full_nodes':a['nodes']>=100000 and b['nodes']>=100000})
        out.append(r)
    return out

def evaluate_unit(job):
    replay_path,out_path,conf=job;replay_path=Path(replay_path)
    def produce(out):
        games=io.read(replay_path/'games_PRIVATE.parquet');positions=io.read(replay_path/'positions_PRIVATE.parquet')
        scores=[cached_score(r) for r in positions.to_pylist()]
        io.table(out/'scores_PRIVATE.parquet',pa.Table.from_pylist(scores,schema=SCORE_SCHEMA))
        features=game_features(games.to_pylist(),scores)
        schema=pa.schema(list(games.schema)+[pa.field(n,t) for n,t in FEATURE_FIELDS])
        io.table(out/'features_PRIVATE.parquet',pa.Table.from_pylist(features,schema=schema))
        counts={'games':games.num_rows,'positions':len(scores),
            'score_statuses':dict(collections.Counter(r['status'] for r in scores)),
            'mate_positions':sum(r['mate_recipient'] is not None for r in scores),
            'engine_searches_executed':sum(r['search_executed'] for r in scores)}
        io.js(out/'summary.json',counts);return counts
    try:
        out,receipt=io.stage(out_path,conf,produce)
        return str(out),io.load(out/'summary.json')
    finally:
        # Runs on success, exceptions, and interruption, before pool shutdown.
        close_engine()
