"""R13(b): uniform hash-priority completed-game draw and restartable Stockfish.

No account/game identifiers or FENs enter public output. Network access is only
the optional, sequential public game-export request, never a message/action.
"""
from __future__ import annotations
import concurrent.futures as cf, multiprocessing as mp, io, re, time, urllib.request, urllib.error
from collections import Counter
from types import SimpleNamespace
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import chess, chess.pgn, chess.engine
from local_common import *
sys.path.insert(0,str(ROOT/'vendor/test_g/code'))
import g_data, g_engine

def random_bits(gid,seed,tag):
    return int.from_bytes(hashlib.blake2b(f'{seed}|{tag}|{gid}'.encode(),digest_size=16).digest(),'big')

def candidate_month(job):
    out=Path(job['out']);ck=job['key']
    if cached(out,ck):return str(out)
    out.parent.mkdir(parents=True,exist_ok=True);temp=out.with_name(out.name+'.tmp');rows=[];total=kept=0;last=time.monotonic()
    schema=pa.schema([('game_id',pa.string()),('priority',pa.string()),('month_code',pa.int8()),('speed_code',pa.int8()),('pgn',pa.string())])
    before=snapshot(job['path'])
    with pq.ParquetWriter(temp,schema,compression='zstd') as writer:
        for h,moves in g_data.pgn_records(job['path']):
            total+=1;r=g_data.pgn_summary(h,moves,False)
            if r and r['rated'] and r['standard'] and r['speed'] in job['speeds'] and r['result'] in ['1-0','0-1','1/2-1/2']:
                priority=random_bits(r['game_id'],job['seed'],'game')
                if priority<job['limit']:
                    text='\n'.join('['+x+' "'+v.replace('\\','\\\\').replace('"','\\"')+'"]' for x,v in h.items())+'\n\n'+moves
                    rows.append(dict(game_id=r['game_id'],priority=f'{priority:032x}',month_code=MONTHS.index(job['month']),speed_code=r['speed'],pgn=text));kept+=1
            if len(rows)>=4096:writer.write_table(pa.Table.from_pylist(rows,schema=schema));rows=[]
            if time.monotonic()-last>45:log(f'R13 draw {job["month"]}: {total:,} scanned, {kept:,} candidates');last=time.monotonic()
        if rows:writer.write_table(pa.Table.from_pylist(rows,schema=schema))
    require(snapshot(job['path'])==before,'Archive changed during random draw');os.replace(temp,out);seal(out,ck)
    save(str(out)+'.audit.json',dict(games_scanned=total,candidates=kept,month=job['month']));return str(out)

def metadata_files(a,run):
    if a.metadata_source:return list(dict.fromkeys(Path(p).resolve() for p in a.metadata_source))
    result=[]
    # Only schema-bearing Parquet caches. Individual JSON trees are not walked/read automatically.
    for folder in [a.project/'derived/replication',a.project/'raw']:
        if not folder.is_dir():continue
        for parent,dirs,files in os.walk(folder):
            dirs[:]=[d for d in dirs if not d.startswith(('.', 'spill','r12_r13_')) and d not in ['node_modules','by_chooser','buckets','rate_panels']]
            for name in files:
                if name.endswith('.parquet') and any(s in name.lower() for s in ['metadata','api_cache','game_export']):result.append(Path(parent)/name)
    return sorted(set(result))

def metadata_index(a,run,candidates):
    root=a.completed_root;path=root/'metadata.parquet';sources=metadata_files(a,run)
    ck=key([a.seed,[snapshot(p) for p in sources],[sha(p) for p in candidates]])
    if cached(path,ck):return path
    c=db(root/'spill_metadata',a.memory_gb-2)
    try:
        c.execute('CREATE TEMP TABLE ids AS SELECT DISTINCT game_id FROM '+parq(candidates))
        c.execute('CREATE TEMP TABLE evidence(game_id VARCHAR,status VARCHAR,source VARCHAR,bad BOOLEAN,both_connected BOOLEAN)')
        accepted=[]
        for p in sources:
            before=snapshot(p)
            if p.suffix=='.parquet':
                names=set(pq.ParquetFile(p).schema_arrow.names)
                if 'game_id' not in names:continue
                status='api_status' if 'api_status' in names else 'status' if 'status' in names else None
                source='api_source' if 'api_source' in names else 'source' if 'source' in names else None
                if not status or not source:
                    if 'metadata_json' not in names:continue
                    for batch in pq.ParquetFile(p).iter_batches(columns=['game_id','metadata_json'],batch_size=4096):
                        insert_metadata(c,[json.loads(x['metadata_json']) for x in batch.to_pylist() if x['metadata_json']])
                else:
                    bad=' OR '.join('coalesce('+x+',false)' for x in ['invalid','source_conflict','cached_conflict_or_prior_flag'] if x in names) or 'false'
                    if 'record_errors' in names:bad+=' OR coalesce(record_errors,\'\')<>\'\''
                    connected='both_connected' if 'both_connected' in names else 'players_both_connected' if 'players_both_connected' in names else 'NULL::BOOLEAN'
                    c.execute('INSERT INTO evidence SELECT s.game_id,lower('+status+'),lower('+source+'),'+bad+','+connected+' FROM '+parq([p])+' s SEMI JOIN ids USING(game_id)')
            else:
                records=[]
                for r in g_data.cache_objects(p):
                    records.append(r)
                    if len(records)>=4096:insert_metadata(c,records);records=[]
                if records:insert_metadata(c,records)
            require(snapshot(p)==before,'Metadata source changed during read')
            accepted.append(dict(name=p.name,sha256=sha(p),bytes=before['bytes']))
        query='''SELECT game_id,min(status) AS status,min(source) AS "source",
           bool_or(bad) OR count(DISTINCT status)>1 OR count(DISTINCT source)>1 OR count(DISTINCT both_connected)>1 AS conflict,
           min(both_connected) AS both_connected FROM evidence GROUP BY game_id'''
        copy_query(c,query,path);seal(path,ck);save(run/'report/completed_metadata_sources.json',accepted);return path
    finally:c.close()

def insert_metadata(c,records):
    rows=[]
    for r in records:
        normalized=g_data.normalize_cache_object(r)
        if normalized:
            rows.append(dict(game_id=normalized['game_id'],status=normalized['status'],source=normalized['source'],bad=normalized['bad'],
                             both_connected=r.get('both_connected',r.get('players_both_connected'))))
    if rows:
        schema=pa.schema([('game_id',pa.string()),('status',pa.string()),('source',pa.string()),('bad',pa.bool_()),('both_connected',pa.bool_())])
        c.register('incoming',pa.Table.from_pylist(rows,schema=schema));c.execute('INSERT INTO evidence SELECT incoming.* FROM incoming SEMI JOIN ids USING(game_id)');c.unregister('incoming')

def fetch_batch(ids,path,allow):
    ck=key(ids)
    if cached(path,ck):return load(path)
    require(allow,'Unresolved candidate metadata. Re-run part-b with --fetch-metadata, or provide --metadata-source with explicit status/source records.')
    # Batches are sequential; 429 is respected with >=60 seconds backoff.
    url='https://lichess.org/api/games/export/_ids?moves=false&tags=true&clocks=false&evals=false&opening=false'
    req=urllib.request.Request(url,data=','.join(ids).encode(),method='POST',headers={'Accept':'application/x-ndjson','Content-Type':'text/plain','User-Agent':'R12-R13-academic-replication/1.0 (sequential game exports)'})
    for attempt in range(7):
        try:
            with urllib.request.urlopen(req,timeout=180) as response:
                rows=[json.loads(line) for line in response if line.strip()]
            require(len(rows)==len({r.get('id') for r in rows}) and all(r.get('id') in ids for r in rows),'Game export returned duplicate/unrequested IDs')
            require(set(r.get('id') for r in rows)==set(ids),'Game export omitted requested IDs; no nonreturn deletion is allowed')
            save(path,rows);seal(path,ck);return rows
        except urllib.error.HTTPError as e:
            if e.code not in [429,500,502,503,504]:raise
            seconds=max(60 if e.code==429 else 5,2**attempt*5)
            log(f'Game export HTTP {e.code}; retry in {seconds}s')
            for _ in range(0,seconds,30):time.sleep(min(30,seconds-_))
        except (TimeoutError,urllib.error.URLError):
            if attempt==6:raise
            time.sleep(min(30,2**attempt))
    raise RuntimeError('Game export retry limit reached; completed batches are reusable')

def eligibility(status,source,conflict,connected,flag_policy):
    if conflict:raise RuntimeError('Conflicting historical status/source evidence in the candidate priority prefix')
    if not source or not status:raise RuntimeError('A completed-game candidate lacks explicit API source/status; no PGN pool proxy is used')
    if source!='pool':return False
    if status=='outoftime':
        if flag_policy=='strict-connected':
            require(connected is not None,'Flagged game lacks historical both-connected evidence; provide it or explicitly select --flag-policy api-status-proxy')
            return bool(connected)
        return connected is not False
    return status in ['mate','resign','stalemate','draw']

def choose_games(a,run,k,candidates,metadata):
    root=a.completed_root;out=root/'selected_games.parquet';ck=key([k,a.games,a.seed,a.flag_policy,[sha(p) for p in candidates],sha(metadata)])
    if cached(out,ck):return out
    c=db(root/'spill_priority',a.memory_gb-2);schema=pq.ParquetFile(candidates[0]).schema_arrow
    schema=pa.schema(list(schema)+[pa.field('status',pa.string()),pa.field('source',pa.string()),pa.field('both_connected',pa.bool_())])
    n=0;network=0;dispositions=Counter();batch_index=0;temp=out.with_name(out.name+'.tmp')
    try:
        require(c.execute('SELECT count(*)-count(DISTINCT game_id) FROM '+parq(candidates)).fetchone()[0]==0,'Duplicate game IDs across archive candidate months')
        c.execute('CREATE VIEW candidates AS SELECT * FROM '+parq(candidates));c.execute('CREATE VIEW meta AS SELECT * FROM '+parq([metadata]))
        reader=c.execute('SELECT q.*,m.status,m.source,m.conflict,m.both_connected FROM candidates q LEFT JOIN meta m USING(game_id) ORDER BY priority,game_id').fetch_record_batch(300)
        with pq.ParquetWriter(temp,schema,compression='zstd') as writer:
            for batch in reader:
                rows=batch.to_pylist();missing=[r['game_id'] for r in rows if not r['source'] or not r['status']]
                if missing:
                    network+=len(missing)
                    require(network<=a.max_metadata_games,'Metadata-game budget exhausted; raise --max-metadata-games to continue. Existing requests remain cached.')
                    p=root/'api_batches'/(key(missing)+'.json');answers=fetch_batch(missing,p,a.fetch_metadata)
                    lookup={r['id']:g_data.normalize_cache_object(r) for r in answers}
                    connections={r['id']:r.get('both_connected',r.get('players_both_connected')) for r in answers}
                    for r in rows:
                        if r['game_id'] in lookup:
                            q=lookup[r['game_id']];require(q is not None,'API metadata could not be normalized')
                            for name in ['status','source']:
                                if r[name] and q[name]:require(r[name]==q[name],'Cached/API status-source conflict')
                                r[name]=r[name] or q[name]
                            connected=connections[r['game_id']]
                            if r['both_connected'] is not None and connected is not None:require(r['both_connected']==connected,'Cached/API connectedness conflict')
                            if r['both_connected'] is None:r['both_connected']=connected
                            r['conflict']=bool(r['conflict']) or q['bad']
                selected=[]
                for r in rows:
                    ok=eligibility(r['status'],r['source'],r['conflict'],r['both_connected'],a.flag_policy)
                    dispositions[(r['source'],r['status'])]+=1
                    if ok:
                        selected.append({x:r[x] for x in schema.names});n+=1
                        if n==a.games:break
                if selected:writer.write_table(pa.Table.from_pylist(selected,schema=schema))
                batch_index+=1
                if batch_index%100==0:log(f'Completed-game selection: {n:,}/{a.games:,}; metadata candidates checked {sum(dispositions.values()):,}')
                if n==a.games:break
        require(n==a.games,'Candidate hash threshold contained too few eligible pool games. Increase --candidate-multiplier (or use --games 500000 --speeds blitz rapid); already scanned source archives remain untouched.')
        os.replace(temp,out);seal(out,ck)
        csv_out(run/'report/completed_game_selection_counts.csv',[dict(source=s,status=t,candidates_in_examined_prefix=v) for (s,t),v in sorted(dispositions.items())])
        return out
    finally:c.close()

def sample_position(record,seed,plies,cumulative):
    gid=record['game_id'];u=random_bits(gid,seed,'ply')/(1<<128);index=np.searchsorted(cumulative,u,side='right');ply=int(plies[min(index,len(plies)-1)])
    side=bool(random_bits(gid,seed,'role')&1);game=chess.pgn.read_game(io.StringIO(record['pgn']))
    require(game is not None and not game.errors,'Sampled PGN parse failed')
    tc=game.headers.get('TimeControl','');base=int(tc.split('+')[0]);clocks=[float(base),float(base)]
    node=game;board=game.board();played=0
    while played<ply and node.variations:
        mover=board.turn;node=node.variations[0];board.push(node.move);played+=1
        value=node.clock();clocks[0 if mover else 1]=float(value) if value is not None else np.nan
    common=dict(game_id=gid,month_code=record['month_code'],speed_code=record['speed_code'],ply=ply,side_white=side)
    if played<ply:return dict(common,available=False,reason='GAME_ENDED_BEFORE_DRAWN_PLY')
    # Even a terminal position is recorded; the model/filter and mate audit remain explicit.
    try:wr=float(game.headers['WhiteElo']);br=float(game.headers['BlackElo'])
    except (ValueError,KeyError):wr=br=np.nan
    result=game.headers.get('Result');require(result in ['1-0','0-1','1/2-1/2'],'Unknown sampled final outcome')
    avoided=result=='1/2-1/2' or result==('1-0' if side else '0-1')
    return dict(common,available=True,reason='',fen=board.fen(),gap=(wr-br) if side else (br-wr),
                clock_d=clocks[0 if side else 1],clock_c=clocks[1 if side else 0],y=int(avoided))

def engine_chunk(job):
    path=Path(job['out']);ck=job['key']
    if cached(path,ck):return str(path)
    rows=[];start=time.monotonic()
    with chess.engine.SimpleEngine.popen_uci(job['engine'],timeout=180) as engine:
        g_engine.engine_options(engine,job['config'])
        for r in job['rows']:
            p=sample_position(r,job['seed'],job['plies'],job['cumulative'])
            if p['available']:
                board=chess.Board(p['fen']);require(board.is_valid(),'Invalid sampled position')
                info=engine.analyse(board,chess.engine.Limit(nodes=100000),game=object(),info=chess.engine.INFO_SCORE|chess.engine.INFO_BASIC)
                score=info['score'].pov(chess.WHITE if p['side_white'] else chess.BLACK);mate=score.mate();cp=score.score()
                if mate==0:
                    require(board.is_checkmate(),'Mate zero on a non-checkmated board');mate=-.5 if board.turn==p['side_white'] else .5
                p.update(board=float(cp) if cp is not None else (100000. if mate>0 else -100000.),is_mate=mate is not None,
                         mate_distance=float(mate) if mate is not None else None,nodes=int(info.get('nodes',0)))
            rows.append(p)
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.tmp')
    # Pandas unions optional fields even when an unavailable game is the first record.
    pd.DataFrame(rows).to_parquet(temp,index=False,compression='zstd');os.replace(temp,path);seal(path,ck)
    save(str(path)+'.timing.json',dict(seconds=time.monotonic()-start,games=len(rows),positions=sum(r['available'] for r in rows)));return str(path)

def estimate_positions(a,run,paths):
    # Month clusters: accumulated across every batch, never batch-wise independent SEs.
    xx=xy=None;counts=Counter();n=0;mate=0;sample_rows=[];draws=Counter()
    for path in paths:
        d=pd.read_parquet(path)
        for row in d.itertuples():
            counts[(row.month_code,row.speed_code,'games_drawn')]+=1;draws[row.ply]+=1
            if row.available:counts[(row.month_code,row.speed_code,'positions_evaluated')]+=1
        available=d.available.astype(bool)
        if 'is_mate' in d:mate+=int(d.loc[available,'is_mate'].fillna(False).sum())
        if 'board' not in d:continue
        d=d.loc[available&(d.board>=-100)&(d.ply>10)].copy()
        if not len(d):continue
        d['stage']=stage_code(d.ply);X,names=competitive_design(d,False);y=d.y.to_numpy(float)*100
        xx=X.T@X if xx is None else xx+X.T@X;xy=X.T@y if xy is None else xy+X.T@y;n+=len(d)
        for (m,s),number in d.groupby(['month_code','speed_code']).size().items():counts[(m,s,'model_positions')]+=int(number)
    require(xx is not None and n>len(names),'No supported completed-game model sample')
    f=solve(xx,xy);W=exchange_contrasts(names);require(estimable(W,f).all(),'Completed-game exchange contrast is not identified')
    scores=np.zeros((24,len(names)));observed=np.zeros(24,bool)
    for path in paths:
        d=pd.read_parquet(path)
        if 'board' not in d:continue
        d=d.loc[d.available.astype(bool)&(d.board>=-100)&(d.ply>10)].copy()
        if not len(d):continue
        d['stage']=stage_code(d.ply);X,_=competitive_design(d,False);u=d.y.to_numpy(float)*100-X@f['beta']
        for m in np.unique(d.month_code):
            mask=d.month_code.to_numpy()==m;scores[int(m)]+=X[mask].T@u[mask];observed[int(m)]=True
    G=int(observed.sum());require(G>1,'At least two observed game-month clusters required')
    V=f['bread']@(scores.T@scores)@f['bread']*G/(G-1);theta=W@f['beta'];cv=W@V@W.T
    rows=[]
    for step,j in [('small',0),('large',2)]:
        r=ratio_stats(theta[j],theta[j+1],cv[j:j+2,j:j+2]);rows.append(dict(step=step,positions=n,clusters=G,cluster='game_month',**r))
    csv_out(run/'report/exchange_rate_part_b.csv',
            [{('pi_'+name if name in ['E','E_se','R','R_se'] else name):value for name,value in r.items()} for r in rows])
    for m in range(24):
        for s in [1,2,3,4]:
            sample_rows.append(dict(month=MONTHS[m],speed=SPEEDS[s],**{v:counts[(m,s,v)] for v in ['games_drawn','positions_evaluated','model_positions']}))
    csv_out(run/'report/completed_game_sample.csv',sample_rows)
    csv_out(run/'report/completed_game_drawn_plies.csv',[dict(ply=p,games=n) for p,n in sorted(draws.items())])
    evaluated=sum(v for (m,s,t),v in counts.items() if t=='positions_evaluated')
    save(run/'report/completed_game_sample_notes.json',dict(games_drawn=a.games,positions_evaluated=evaluated,unavailable_drawn_ply=a.games-evaluated,
         mate_scores=mate,mate_share=mate/evaluated if evaluated else None,model_positions=n,cluster='game month; G/(G-1) correction; normal Wald intervals',
         position_rule='Exactly one independent empirical-ply draw per sampled game. Draws beyond game length are unavailable, not capped or redrawn. Attrition is reported.',
         flag_policy=a.flag_policy,flag_limitation='API outoftime excludes abandonment timeout but does not certify historical socket presence of both players.' if a.flag_policy=='api-status-proxy' else 'Flagged games require explicit historical both-connected evidence.',
         population='Rated standard pool games with an allowed normal ending; author accounts retained. The play model describes completed games, conditional on a recorded position at the drawn ply.',
         sample_uniformity='Smallest independent 128-bit game priorities across all available target-month archives. All candidates up through the Nth eligible game are classified; no cache-availability selection.'))
    pooled=load(run/'PRIVATE/opportunity/POOLED.json');comparison=[]
    for r in rows:
        p=next(x for x in pooled if x['step']==r['step'])
        good=p.get('ratio') is not None and r['ratio'] is not None and p.get('se') is not None and r.get('se') is not None
        comparison.append(dict(step=r['step'],grant_ratio=p.get('ratio'),grant_se=p.get('se'),play_ratio=r['ratio'],play_se=r['se'],
             **(inference(p['ratio']-r['ratio'],p['se']**2+r['se']**2) if good else dict(estimate=None,se=None,p=None,status='UNAVAILABLE_RATIO')),
             weak_denominator=p.get('weak_denominator',True) or r.get('weak_denominator',True),covariance_assumption='two samples treated as independent as requested'))
    csv_out(run/'report/exchange_rate_comparison.csv',comparison)

def require_full_archive_coverage(status):
    require(status.get('status')=='COMPLETE_24_MONTHS' and sorted(status.get('months_used',[]))==sorted(MONTHS),
        'R13(b) requires the requested 24-month archive census. Run archive-probe and resolve missing/failed months; partial R12 quantiles do not authorize a reduced R13 population.')

def run(a,run,k):
    status=load(run/'report/ALL_GAMES_STATUS.json');require_full_archive_coverage(status)
    coverage=[(x['month'],x['source_sha256']) for x in sorted(status['monthly_sources'],key=lambda x:x['month'])]
    variant=key([a.games,a.seed,a.speeds,a.candidate_multiplier,a.flag_policy,[str(p) for p in a.metadata_source or []],coverage])[:12]
    root=run/'PRIVATE/completed'/variant;root.mkdir(parents=True,exist_ok=True);a.completed_root=root
    save(root/'CONFIG.json',dict(games=a.games,seed=a.seed,speeds=a.speeds,candidate_multiplier=a.candidate_multiplier,flag_policy=a.flag_policy))
    status=load(run/'report/ALL_GAMES_STATUS.json');months=status['months_used']
    require(months,'Run the ply stage first to authenticate available archives')
    require((run/'PRIVATE/opportunity/POOLED.json').exists(),'Run opportunity models before part-b')
    configs=load(run/'PRIVATE/opportunity/ENGINE_CONFIGURATIONS.json')
    require(len(configs)==1,'Original engine configuration is not unique')
    aa=SimpleNamespace(engine=a.engine,project_root=a.project)
    engine=g_engine.find_engine(aa,configs);description=g_engine.describe_engine(engine,configs[0]);save(run/'report/R13_ENGINE.json',description)
    codes=[SPEEDS.index(x) for x in a.speeds]
    total=pd.read_csv(run/'report/all_games_ply_histogram.csv');N=int(total.loc[total.speed_code.isin(codes),'games'].sum())
    limit=min(1<<128,int((1<<128)*min(1.,a.candidate_multiplier*a.games/max(1,N))))
    # Bind the selected monthly archives to the checksums already recorded by the complete census.
    # Avoid common.py namespace collisions by using the paths saved with the monthly census receipts.
    jobs=[]
    for month in months:
        rc=load(str(run/'PRIVATE/ply'/f'{month}.json')+'.ok.json')
        # R11's census result has the source hash; discover exact-name alternatives and match it.
        expected=next(r['source_sha256'] for r in status['monthly_sources'] if r['month']==month)
        choices=[]
        for folder in (a.archive_root or [a.project/'raw',a.project/'archives',a.project/'data',a.project.parent]):
            if Path(folder).is_dir():choices.extend(Path(folder).rglob(f'lichess_db_standard_rated_{month}.pgn*'))
        paths=[p for p in choices if re.fullmatch(r'.*\.pgn(?:\.zst|\.gz|\.bz2)?',p.name) and p.is_file()]
        path=next((p for p in dict.fromkeys(paths) if sha(p)==expected),None)
        require(path is not None,'Cannot rebind authenticated archive '+month)
        require(not path.name.endswith('.bz2'),'R13 candidate reader supports zst/gz/plain PGN; decompress the bz2 archive and repeat the ply scan')
        jobs.append(dict(path=str(path),month=month,seed=a.seed,speeds=codes,limit=limit,out=str(root/'candidates'/f'{month}.parquet'),key=key([k,month,expected,limit,codes,a.seed])))
    with heartbeat('Uniform completed-game candidates'),cf.ProcessPoolExecutor(max_workers=min(a.workers,2),mp_context=mp.get_context('spawn')) as pool:
        candidates=list(pool.map(candidate_month,jobs))
    metadata=metadata_index(a,run,candidates);selected=choose_games(a,run,k,candidates,metadata)
    hist=pd.read_csv(run/'report/competitive_ply_histogram.csv');plies=hist.ply.to_numpy(int);cumulative=np.cumsum(hist.opportunities.to_numpy(float));cumulative/=cumulative[-1]
    threads=int(configs[0]['sf100k_threads']);hashmb=int(configs[0]['sf100k_hash_mb'])
    require(threads<=a.workers and hashmb+200<=(a.memory_gb-2)*1024,'Exact original engine settings exceed the requested total resource budget')
    workers=max(1,min(a.workers//max(1,threads),int((a.memory_gb-2)*1024/(hashmb+200))))
    ck=key([k,sha(selected),sha(run/'report/competitive_ply_histogram.csv'),description,a.seed]);paths=[];pending={};start=time.monotonic();done=0;evaluated=0
    with heartbeat('R13 Stockfish positions'),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        for j,batch in enumerate(pq.ParquetFile(selected).iter_batches(batch_size=1000,use_threads=False)):
            path=root/'evaluations'/f'{j:05d}.parquet';paths.append(path)
            job=dict(rows=batch.to_pylist(),engine=str(engine),config=configs[0],seed=a.seed,plies=plies,cumulative=cumulative,out=str(path),key=key([ck,j]))
            if cached(path,job['key']):continue
            pending[pool.submit(engine_chunk,job)]=path
            if len(pending)>=workers:
                ready,_=cf.wait(pending,return_when=cf.FIRST_COMPLETED)
                for f in ready:
                    p=f.result();pending.pop(f);meta=load(p+'.timing.json');done+=meta['games'];evaluated+=meta['positions']
                    elapsed=time.monotonic()-start;log(f'Engine: {done:,} new games, {evaluated:,} evaluated positions; elapsed {elapsed/3600:.2f} h')
        for f in cf.as_completed(pending):f.result()
    estimate_positions(a,run,paths)
