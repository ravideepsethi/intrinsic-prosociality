"""Exact-binary UCI alignment and resumable sampled-position evaluations."""
from __future__ import annotations
import concurrent.futures as cf
import logging
import chess
import chess.engine
from g_common import *
logging.getLogger('chess.engine').setLevel(logging.CRITICAL+1)

def find_engine(a,configs):
    hashes={e['sf100k_stockfish_sha256'] for e in configs}
    require(len(hashes)==1,'Multiple original engine binaries require a documented per-game configuration mapping','ENGINE_CONFIGURATION_AMBIGUOUS')
    expected=next(iter(hashes));candidates=[]
    if a.engine:candidates.append(Path(a.engine).expanduser())
    for command in ['stockfish','/opt/homebrew/bin/stockfish','/usr/local/bin/stockfish']:
        p=shutil.which(command)
        if p:candidates.append(Path(p))
    for root in [a.project_root/'engines',a.project_root/'stockfish',a.project_root/'bin',a.project_root/'code',a.project_root/'tools']:
        if root.exists():
            for p in file_inventory(root):
                if 'stockfish' in p.name.lower() and p.is_file() and os.access(p,os.X_OK) and p.suffix not in ('.py','.sh','.command'):candidates.append(p)
    for p in dict.fromkeys(candidates):
        if p.is_file() and sha(p)==expected:return p.resolve()
    raise GateError('EXACT_ENGINE_NOT_FOUND','No local Stockfish binary matches the saved SHA256. Supply --engine with the original binary. Expected SHA256: '+expected)

def engine_options(engine,config):
    wanted={'Threads':int(config['sf100k_threads']),'Hash':int(config['sf100k_hash_mb'])}
    require(int(config['sf100k_nodes_requested'])==100000 and config['sf100k_eval_method']=='uci_go_nodes','Unexpected original engine limits','ENGINE_CONFIGURATION_MISMATCH')
    engine.configure(wanted);return wanted

def describe_engine(path,config):
    with chess.engine.SimpleEngine.popen_uci(str(path),timeout=60) as eng:
        used=engine_options(eng,config);options={n:dict(default=o.default,type=o.type) for n,o in eng.options.items()}
        networks=[]
        for name,o in eng.options.items():
            if name.startswith('EvalFile'):
                value=str(o.default or '');candidates=[Path(value),path.parent/value]
                found=next((p for p in candidates if p.is_file()),None)
                networks.append(dict(option=name,file=value,storage='external file' if found else 'embedded in SHA256-matched binary',sha256=sha(found) if found else None))
        return dict(binary_sha256=sha(path),id=eng.id,options=options,overrides=used,network_files=networks,limit=dict(nodes=100000),position_policy='New game identifier for each FEN; original bare-FEN search, no reconstructed move history')

def evaluate_chunk(job):
    d=job['rows'];out=[];start=time.monotonic()
    with chess.engine.SimpleEngine.popen_uci(job['engine'],timeout=180) as engine:
        engine_options(engine,job['config'])
        for r in d:
            board=chess.Board(r['fen']);require(board.is_valid(),'Invalid sampled FEN','ENGINE_INVALID_FEN')
            result=engine.analyse(board,chess.engine.Limit(nodes=100000),game=object(),info=chess.engine.INFO_SCORE|chess.engine.INFO_BASIC)
            perspective=chess.WHITE if job['perspective']=='white' else board.turn
            score=result['score'].pov(perspective)
            # UCI mate distances / python-chess .mate() are moves, despite the old column's "ply" name.
            mate=score.mate();cp=score.score()
            if mate==0:require(board.is_checkmate(),'Mate(0) without checkmate','ENGINE_MATE_ZERO_INVALID');mate=-.5 if perspective==board.turn else .5
            out.append(dict(game_id=r['game_id'],vf=float(cp) if cp is not None else 0.,mate=float(mate) if mate is not None else 0.,nodes=int(result.get('nodes',0)),depth=int(result.get('depth',0))))
    return out,time.monotonic()-start

def evaluate(a,run,rows,engine,config,folder,perspective,key):
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True);jobs=[];paths=[]
    for i in range(0,len(rows),1000):
        index=i//1000;p=folder/f'chunk_{index:05d}.parquet';receipt=folder/f'receipt_{index:05d}';k=digest([key,index,digest(rows[i:i+1000])])
        paths.append(p)
        if done(receipt,k):continue
        jobs.append((dict(rows=rows[i:i+1000],engine=str(engine),config=config,perspective=perspective),p,receipt,k))
    # Submit bounded work; at most workers+1 chunks are resident per engine process.
    workers=max(1,min(a.workers//max(1,int(config['sf100k_threads'])),int(max(1,a.memory_gb-2)*1024/(int(config['sf100k_hash_mb'])+128))))
    with cf.ProcessPoolExecutor(max_workers=workers) as pool,heartbeat('Stockfish evaluations'):
        pending={};it=iter(jobs)
        for _ in range(min(workers,len(jobs))):
            job,p,rc,k=next(it);pending[pool.submit(evaluate_chunk,job)]=(p,rc,k)
        complete=0
        while pending:
            finished,_=cf.wait(pending,timeout=45,return_when=cf.FIRST_COMPLETED)
            for f in finished:
                p,rc,k=pending.pop(f);out,elapsed=f.result();atomic_parquet(pd.DataFrame(out),p);checkpoint(rc,k,outputs=[p],summary={'worker_seconds':elapsed,'positions':len(out)});complete+=1
                if complete%10==0:log(f'Engine chunks: {complete}/{len(jobs)} newly evaluated')
                try:job,p,rc,k=next(it);pending[pool.submit(evaluate_chunk,job)]=(p,rc,k)
                except StopIteration:pass
    return pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True)

def align(a,run,key):
    folder=run/'g0';folder.mkdir(exist_ok=True);configs=load(run/'input/ENGINE_CONFIGURATIONS.json')
    require(len(configs)==1,'Original rows used multiple thread/hash configurations; no arbitrary collapse.','ENGINE_CONFIGURATION_AMBIGUOUS')
    config=configs[0];engine=find_engine(a,configs);description=describe_engine(engine,config);save(folder/'ENGINE.json',description);save(run/'report/ENGINE.json',description)
    c=db(folder/'spill',2)
    try:
        d=c.execute('SELECT * FROM '+parq(sorted((run/'input').glob('*/alignment_pool.parquet')))+" ORDER BY md5(game_id || 'G0-20261012') LIMIT 10000").fetchdf()
    finally:c.close()
    require(len(d)==10000,'G0 requires exactly 10,000 positions')
    for r in d.itertuples():
        color='white' if chess.Board(r.fen_after_last_move).turn else 'black'
        require(color==r.disconnected_color,'Disconnect sign/side-to-move mismatch','ENGINE_PERSPECTIVE_MISMATCH')
    rows=d[['game_id','fen_after_last_move']].rename(columns={'fen_after_last_move':'fen'}).to_dict('records');start=time.monotonic()
    e=evaluate(a,run,rows,engine,config,folder/'evaluations','turn',digest([key,description]));elapsed=time.monotonic()-start
    d=d.merge(e,on='game_id',validate='one_to_one');mate_agreement=float((d.old_is_mate==(d.mate!=0)).mean());nm=(~d.old_is_mate)&(d.mate==0)
    delta=np.abs(d.loc[nm,'old_cp']-d.loc[nm,'vf']);median=float(delta.median());p95=float(delta.quantile(.95))
    passed=mate_agreement>=.99 and median<=10 and p95<=40
    row=dict(N=10000,nonmate_comparison_N=int(nm.sum()),mate_agreement=mate_agreement,median_abs_cp=median,p95_abs_cp=p95,passed=passed,elapsed_seconds=elapsed)
    table(run/'report','tabG0_engine_alignment',[row],dict(N=10000,sample='Uniform hash-priority final positions from the authenticated main sample',source_months=MONTHS,ending_status_coverage='Verified disconnects; alignment only'))
    require(passed,'G0 engine alignment failed; outcome estimation was not started.','G0_ALIGNMENT_FAILED')
    save(folder/'PASS.json',row);return engine,config

def evaluate_sample(a,run,sample,engine,config,key):
    out=run/'g1/positions.parquet';receipt=run/'g1/evaluated';k=digest([key,sha(sample),config])
    if done(receipt,k):return out
    d=pd.read_parquet(sample);rows=d[['game_id','fen']].to_dict('records')
    pilot_start=time.monotonic();pilot=evaluate(a,run,rows[:10000],engine,config,run/'g1/engine_pilot','white',k);secs=time.monotonic()-pilot_start
    save(run/'report/G1_ENGINE_THROUGHPUT.json',dict(positions=10000,elapsed_seconds=secs,target=len(rows),estimate_hours=secs*len(rows)/10000/3600,
        warning='Estimate is provisional; checkpoint reuse can reduce measured elapsed time. Engine worker timings are retained privately.'))
    rest=evaluate(a,run,rows[10000:],engine,config,run/'g1/engine_rest','white',k) if len(rows)>10000 else pilot.iloc[:0]
    d=d.merge(pd.concat([pilot,rest],ignore_index=True),on='game_id',validate='one_to_one');atomic_parquet(d,out)
    checkpoint(receipt,k,[sample],[out]);return out
