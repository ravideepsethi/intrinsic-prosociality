from __future__ import annotations
import concurrent.futures as cf, gzip, json, multiprocessing as mp, os, time
from pathlib import Path
import chess, chess.engine
import pyarrow as pa
from common import *
from network import fetch_batch
from tenure import rates,NUMS,COMPLETE,CATS
from estimate import sqlfit

ENGINE_SHA='ae4c93fa9676ca7750d0714342fd8a5b1d018000fc6e0f6cedf112067b5ef374'
FEATURES=pa.schema([('game_id',pa.string()),('status',pa.string()),('positions',pa.int64()),('full_cp_positions',pa.int64()),
  ('mate_positions',pa.int64())]+[(x,pa.float64()) for x in ['final_cp','loss2','loss4','own_last_loss','own_previous_loss','own_two_sum','own_max_loss']])

def validate(o,t):
    require(o.get('id')==t['game_id'],'GAME_ID_MISMATCH')
    require(o.get('source')=='pool' and o.get('rated') is True and o.get('status')=='timeout' and o.get('variant')=='standard','GAME_CLASS_MISMATCH')
    require(o.get('createdAt')==t['game_ms'] and o.get('lastMoveAt')==t['last_ms'],'TIME_MISMATCH')
    require(o.get('winner')==t['api_winner'],'RESULT_MISMATCH')
    require(o.get('initialFen') in (None,'startpos',chess.STARTING_FEN),'NONSTANDARD_START')
    require(isinstance(o.get('moves'),str),'MISSING_MOVES')
    sans=o['moves'].split();n=int(t['ply_count']);require(len(sans)==n,'PLY_COUNT_MISMATCH')
    own=t['disconnected_color'];require(own in ['white','black'],'BAD_COLOR')
    wanted=set(range(max(0,n-4),n+1));b=chess.Board();positions=[]
    if 0 in wanted:positions.append(dict(ply=0,fen=b.fen()))
    for i,san in enumerate(sans,1):
        m=b.parse_san(san);require(b.is_legal(m),'ILLEGAL_MOVE');b.push(m)
        if i in wanted:positions.append(dict(ply=i,fen=b.fen()))
    require(b.fen()==chess.Board(t['fen_after_last_move']).fen(),'FINAL_FEN_MISMATCH')
    require(b.turn==(own=='white') and b.is_valid(),'MOVER_OR_BOARD_MISMATCH')
    # Last mover is chooser, so recipient's own most recent moves are n-1 and n-3.
    return dict(game_id=t['game_id'],n=n,color=own,status='VERIFIED',positions=positions)

def features(g,scores):
    r={k:None for k in FEATURES.names};r.update(game_id=g['game_id'],status=g['status'],positions=len(scores),full_cp_positions=0,mate_positions=0)
    if g['status']!='VERIFIED':return r
    by={s['ply']:s for s in scores};n=g['n']
    require(len(by)==len(scores),'Duplicate engine position')
    r['full_cp_positions']=sum(s['status']=='SCORED' and s['cp'] is not None for s in scores)
    r['mate_positions']=sum(s['mate'] is not None for s in scores)
    def cp(p):
        s=by.get(p);return s['cp'] if s and s['status']=='SCORED' and s['mate'] is None else None
    def drop(a,b):
        x,y=cp(a),cp(b);return None if x is None or y is None else float(x-y)
    r.update(final_cp=cp(n),loss2=drop(n-2,n),loss4=drop(n-4,n),own_last_loss=drop(n-2,n-1),own_previous_loss=drop(n-4,n-3))
    if r['own_last_loss'] is not None and r['own_previous_loss'] is not None:
        r['own_two_sum']=r['own_last_loss']+r['own_previous_loss'];r['own_max_loss']=max(r['own_last_loss'],r['own_previous_loss'])
    return r

def find_engine(project,explicit):
    if explicit:
        p=Path(explicit).expanduser();require(p.is_file() and os.access(p,os.X_OK),'Engine missing/not executable')
        require(sha(p)==ENGINE_SHA,'Engine differs from pinned SF18 binary');return p
    for root in [project/'tools',project/'bin',project/'engines',project/'replication_package']:
        if root.exists():
            for p in root.rglob('*stockfish*'):
                if p.is_file() and os.access(p,os.X_OK) and p.stat().st_size<200*1024**2 and sha(p)==ENGINE_SHA:return p
    raise RuntimeError('Pinned Stockfish 18 not found; rerun with --stockfish /absolute/path/to/the/existing/SF18/binary')

def evaluate(job):
    input_path,output,key,engine_path=job
    if checkpoint(output,key) and checkpoint(Path(output).with_suffix('.scores.json.gz'),key):return str(output)
    games=read(input_path);rows=[];scores_all=[];cache={};engine=None
    try:
        if any(g['positions'] for g in games):
            engine=chess.engine.SimpleEngine.popen_uci(engine_path,timeout=180)
            require('Stockfish 18' in engine.id.get('name',''),'Wrong engine name')
            engine.configure({'Threads':1,'Hash':64})
        for g in games:
            scores=[]
            for pos in g['positions']:
                k=(pos['fen'],g['color'])
                if k in cache:s=dict(cache[k])
                else:
                    b=chess.Board(pos['fen']);s=dict(cp=None,mate=None,nodes=0,depth=None,status='TERMINAL')
                    if not b.is_game_over():
                        info=engine.analyse(b,chess.engine.Limit(nodes=100000),game=object())
                        v=info.get('score');bound=bool(info.get('lowerbound') or info.get('upperbound'));nodes=int(info.get('nodes',0))
                        pov=v.pov(g['color']=='white') if v is not None else None
                        s.update(cp=pov.score() if pov is not None and not bound else None,mate=pov.mate() if pov is not None else None,nodes=nodes,depth=info.get('depth'),
                          status='BOUNDED' if bound else ('NO_SCORE' if v is None else ('SHORT' if nodes<100000 else 'SCORED')))
                    if len(cache)>=4096:cache.clear()
                    cache[k]=s.copy()
                s.update(ply=pos['ply'],fen=pos['fen']);scores.append(s)
                scores_all.append(dict(game_id=g['game_id'],color=g['color'],**s))
            rows.append(features(g,scores))
    finally:
        if engine:
            try:engine.quit()
            finally:engine.close()
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    # Retain every raw score (including mate/bound/short) for audit, never map mate to a made-up CP.
    scorefile=output.with_suffix('.scores.json.gz');tmp=Path(str(scorefile)+'.partial')
    with gzip.open(tmp,'wt',compresslevel=1) as f:json.dump(scores_all,f)
    os.replace(tmp,scorefile);certify(scorefile,key)
    tmp=Path(str(output)+'.partial');pq.write_table(pa.Table.from_pylist(rows,schema=FEATURES),tmp,compression='zstd')
    os.replace(tmp,output);certify(output,key);return str(output)

def reuse_moves(project,run,targets,key,enabled):
    p=run/'PRIVATE/a1_reused_moves.json.gz'
    if checkpoint(p,key):
        with gzip.open(p,'rt') as f:return json.load(f)
    found={};wanted={x['game_id'] for x in targets}
    root=project/'derived/replication/a1_trajectory_build_v100_PRIVATE/api_payloads'
    paths=sorted(root.rglob('response_PRIVATE.ndjson.gz')) if enabled and root.exists() else []
    with heartbeat('Checking existing A1 move responses'):
        for i,path in enumerate(paths):
            with gzip.open(path,'rt') as f:
                for line in f:
                    if not line.strip():continue
                    o=json.loads(line)
                    if o.get('id') in wanted:
                        # Source-validation against current main targets is performed by validate().
                        old=found.get(o['id'])
                        require(old is None or old.get('moves')==o.get('moves'),'Conflicting cached move histories')
                        found[o['id']]=o
            if (i+1)%1000==0:log(f'A1 cache: {i+1:,}/{len(paths):,} responses; {len(found):,} target games found')
    with gzip.open(p,'wt',compresslevel=1) as f:json.dump(found,f)
    certify(p,key);dump(run/'report/A1_REUSE.json',dict(response_files_scanned=len(paths),games_reused=len(found),engine_scores_reused=0,
      reason='Reuse legal move histories; fresh SF18 searches give all five adjacent positions identical settings and provenance'))
    return found

def build(db,project,run,args,key):
    targets=pq.read_table(run/'PRIVATE/trajectory_targets.parquet').to_pylist()
    require(targets,'Empty trajectory sample')
    engine=find_engine(project,args.stockfish)
    # Check cached engine lineage even though fresh scores will be used.
    dump(run/'report/TRAJECTORY_ENGINE.json',dict(binary_sha256=sha(engine),nodes=100000,threads_each=1,hash_mb_each=64,workers=args.workers,
      convention='Standalone FEN/new game each search; recipient perspective; five adjacent positions; raw mate/bounds retained'))
    reused=reuse_moves(project,run,targets,key,args.reuse_a1)
    jobs=[];statuses={};planned_positions=0;missing=0
    for start in range(0,len(targets),300):
        chunk=targets[start:start+300];name=f'{start//300:06d}';replay=run/'PRIVATE/replay'/f'{name}.json'
        unitkey=signature([key,[t['game_id'] for t in chunk],ENGINE_SHA])
        if checkpoint(replay,unitkey):games=read(replay)
        else:
            ids=[t['game_id'] for t in chunk if t['game_id'] not in reused]
            obtained,_=fetch_batch(run/'PRIVATE/game_responses',ids,'games',args.fetch_games,key) if ids else ({},None)
            games=[];invalid=0
            for t in chunk:
                o=reused.get(t['game_id'],obtained.get(t['game_id']))
                if o is None:g=dict(game_id=t['game_id'],status='NONRETURN',positions=[])
                else:
                    try:g=validate(o,t)
                    except (ValueError,RuntimeError) as e:
                        # Do not expose raw IDs in public reports; private input retains diagnostic detail.
                        g=dict(game_id=t['game_id'],status='REPLAY_INVALID',reason=str(e),positions=[]);invalid+=1
                games.append(g)
            require(invalid<=max(1,int(.05*len(chunk))),'More than 5% of a returned batch failed source validation; inspect private cached responses')
            # A cache-only probe must not freeze missing games as a completed recovery unit.
            if args.fetch_games or all(g['status']!='NONRETURN' for g in games):dump(replay,games);certify(replay,unitkey)
            else:dump(replay,games)
        for g in games:
            statuses[g['status']]=statuses.get(g['status'],0)+1;planned_positions+=len(g['positions'])
            missing+=g['status']=='NONRETURN'
        jobs.append((str(replay),str(run/'PRIVATE/engine'/f'{name}.parquet'),unitkey,str(engine)))
        if start%3000==0:log(f'Trajectory recovery: {min(start+300,len(targets)):,}/{len(targets):,}')
    dump(run/'report/TRAJECTORY_RECOVERY.json',dict(targets=len(targets),statuses=statuses,positions=planned_positions))
    if missing and not args.fetch_games:raise RuntimeError('Trajectory moves missing in cache; use --fetch-games to complete the frozen target sample')
    done=[];pending_jobs=[]
    for job in jobs:
        if checkpoint(job[1],job[2]) and checkpoint(Path(job[1]).with_suffix('.scores.json.gz'),job[2]):done.append(job[1])
        else:pending_jobs.append(job)
    started=time.monotonic();completed=0
    log(f'Engine: {len(done)} completed batches reused; {len(pending_jobs)} batches pending; {args.workers} workers')
    with heartbeat('Stockfish final-ply evaluation'):
        with cf.ProcessPoolExecutor(max_workers=args.workers,mp_context=mp.get_context('spawn')) as executor:
            todo=iter(pending_jobs);running={}
            def fill():
                while len(running)<2*args.workers:
                    job=next(todo,None)
                    if job is None:break
                    running[executor.submit(evaluate,job)]=job
            fill()
            while running:
                finished,_=cf.wait(running,return_when=cf.FIRST_COMPLETED)
                for future in finished:
                    running.pop(future);done.append(future.result());completed+=1
                    elapsed=time.monotonic()-started;eta=(len(pending_jobs)-completed)*elapsed/completed/3600
                    log(f'Engine {completed}/{len(pending_jobs)} new batches complete; ETA {eta:.1f} hours')
                fill()
    p=run/'PRIVATE/trajectory_features.parquet'
    copy(db,p,'SELECT * FROM '+parq(done),key)
    db.execute(f'CREATE OR REPLACE TEMP VIEW trajectory AS SELECT * FROM read_parquet({qs(p)})')
    require(db.execute('SELECT count(*),count(DISTINCT game_id) FROM trajectory').fetchone()==(len(targets),len(targets)),'Trajectory feature rows lost/duplicated')

def analyze(db,run,args):
    db.execute(f'''CREATE TEMP VIEW resp0 AS SELECT a.*,t.* EXCLUDE(game_id),
      CASE WHEN a.engine_eval_is_mate THEN 'mate' ELSE cast(floor(greatest(-1200,least(1200,a.board))/50) AS VARCHAR) END final50,
      {loss_bin('t.loss2')} loss2_bin,{loss_bin('t.loss4')} loss4_bin,{loss_bin('t.own_last_loss')} own_last_bin,{loss_bin('t.own_max_loss')} own_max_bin,
      (a.gap100<0)::INTEGER weaker_recipient,
      (t.own_max_loss>=100)::INTEGER blunder100,(t.own_max_loss>=200)::INTEGER blunder200
      FROM aged a JOIN trajectory t USING(game_id)''')
    export(db,run/'report/RESPONSIBILITY_COVERAGE.csv','''SELECT status,board_bin,tenure,count(*) opportunities,sum(y) grants,
      count(loss2) finite_loss2,count(loss4) finite_loss4,count(own_max_loss) finite_own_two,
      count(*) FILTER(WHERE loss2 IS NOT NULL AND loss4 IS NOT NULL AND own_max_loss IS NOT NULL) common_rows,
      sum(mate_positions) mate_positions FROM resp0 GROUP BY ALL ORDER BY ALL''')
    export(db,run/'report/RESPONSIBILITY_ENGINE_COMPARISON.csv','''SELECT board_bin,count(*) n,count(final_cp) finite_recomputed,
      avg(abs(final_cp-board)) mean_absolute_difference_cp,
      count(*) FILTER(WHERE final_cp IS NOT NULL AND (final_cp>=-100)<>(board>=-100)) competitive_reclassifications
      FROM resp0 GROUP BY board_bin ORDER BY board_bin''')
    # All comparisons in the ladder use the same finite-score rows, including baseline.
    db.execute(f'''CREATE TEMP VIEW resp AS SELECT * FROM resp0 WHERE status='VERIFIED' AND NOT engine_eval_is_mate
      AND loss2 IS NOT NULL AND loss4 IS NOT NULL AND own_max_loss IS NOT NULL AND ({COMPLETE})''')
    rates(db,run/'report/RESPONSIBILITY_BOARD_BY_BLUNDER.csv','board_bin,own_max_bin',source='resp')
    rates(db,run/'report/RESPONSIBILITY_NET_CHANGE_RATES.csv','board_bin,loss2_bin,loss4_bin',source='resp')
    results=[]
    for label,where in [('all','true'),('age_ge_90','age_days>=90'),('age_ge_365','age_days>=365')]:
        for model,targets,sub,cats in [
          ('gradient',['competitive'],'(board>=-100 OR board<=-300)',CATS+['gap_bin']),
          ('gap',['gap100'],'board>=-100',CATS+['final50'])]:
            for step,extra in [('baseline',[]),('net_two',['loss2_bin']),('net_four',['loss4_bin']),('own_moves',['own_last_bin','own_max_bin']),('all_proxies',['loss2_bin','loss4_bin','own_last_bin','own_max_bin'])]:
                log(f'Responsibility {label} {model} {step}')
                q=f'SELECT * FROM resp WHERE ({where}) AND ({sub})'
                with heartbeat('Fitting responsibility sensitivity'):r=sqlfit(db,q,targets,cats+extra,NUMS)
                r.update(scope=label,model=model,step=step,same_rows=True,
                  interpretation='Descriptive conditioning on trajectory, not identified responsibility or rage-quitting; board contrast cannot also absorb a full final-evaluation FE')
                name=f'RESP_MODEL_{label}_{model}_{step}.json';dump(run/'report'/name,r);results.append(dict(file=name,status=r['status'],estimates=r.get('estimates',{})))
        for threshold in [100,200]:
            q=f'SELECT * FROM resp WHERE ({where}) AND own_max_loss<{threshold} AND (board>=-100 OR board<=-300)'
            r=sqlfit(db,q,['competitive'],CATS+['gap_bin'],NUMS);r.update(scope=label,own_move_max_below_cp=threshold)
            name=f'RESP_MODEL_{label}_no_blunder_{threshold}.json';dump(run/'report'/name,r);results.append(dict(file=name,status=r['status']))
    # Directly check the proposed rating-gap interpretation at comparable final state.
    for threshold in [100,200]:
        q=f'SELECT * EXCLUDE(y),blunder{threshold} y FROM resp WHERE board>=-100'
        r=sqlfit(db,q,['gap100'],CATS+['final50'],NUMS)
        r.update(outcome=f'Disconnected account own-move maximum CP loss >= {threshold}',interpretation='Association of rating gap with recent own-move blunder; not observed beliefs or quitting intent')
        dump(run/f'report/RESP_BLUNDER_VS_GAP_{threshold}.json',r)
    dump(run/'report/RESPONSIBILITY_MODEL_INDEX.json',results)
    dump(run/'report/RESPONSIBILITY_COMPLETE.json',dict(status='RESPONSIBILITY_COMPUTATION_COMPLETE',sample='Uniform chooser subsample with full histories',engine='SF18,100k nodes',
      limits='Final-4-ply complete-case models exclude games shorter than 4 plies and mate/bound/short/missing scores. Coverage table must accompany all results. No causal mechanism identification.'))
