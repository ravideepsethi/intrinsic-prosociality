"""Part C: local recorded-move replay, no engine and no network calls."""
from r7_common import *
import chess, chess.pgn, io as streams, re
import cache_scan
from r7_schedule import fit_map

MOVE_FIELDS=('moves','pgn_moves','movetext','pgn')
JSON_FIELDS=('metadata_json','raw_json','response_json','api_json')
SCHEMA=pa.schema([('game_id',pa.string()),('valid',pa.bool_()),('reason',pa.string()),
    ('net_material_change_4ply',pa.int16()),('move_sequence_sha256',pa.string()),('window_plies',pa.int8()),
    ('opening_tag',pa.string())])

def replay(text,expected_ply,initial_fen=None):
    """Net own-minus-opponent material, from side to move in the final position."""
    if not isinstance(text,str) or not text.strip():raise ValueError('NO_RECORDED_MOVES')
    if '[' in text or '{' in text or re.search(r'\d+\.',text):
        game=chess.pgn.read_game(streams.StringIO(text))
        if game is None or game.errors:raise ValueError('INVALID_PGN')
        board=game.board();moves=list(game.mainline_moves())
        if initial_fen and board.fen()!=chess.Board(initial_fen).fen():raise ValueError('INITIAL_FEN_CONFLICT')
    else:
        board=chess.Board(initial_fen) if initial_fen else chess.Board();moves=[]
        for token in text.split():
            if token in ('1-0','0-1','1/2-1/2','*'):continue
            try:move=board.parse_san(token)
            except ValueError:
                try:move=chess.Move.from_uci(token)
                except ValueError:raise ValueError('INVALID_RECORDED_MOVE')
                if move not in board.legal_moves:raise ValueError('ILLEGAL_RECORDED_MOVE')
            moves.append(move);board.push(move)
        board=chess.Board(initial_fen) if initial_fen else chess.Board()
    if len(moves)!=int(expected_ply):raise ValueError('FINAL_PLY_MISMATCH')
    if len(moves)==0:raise ValueError('NO_RECORDED_MOVES')
    startfen=board.fen();cut=max(0,len(moves)-4)
    values={chess.PAWN:1,chess.KNIGHT:3,chess.BISHOP:3,chess.ROOK:5,chess.QUEEN:9}
    def balance(b):return sum(v*(len(b.pieces(p,chess.WHITE))-len(b.pieces(p,chess.BLACK))) for p,v in values.items())
    before=balance(board) if cut==0 else None
    for i,move in enumerate(moves):
        if move not in board.legal_moves:raise ValueError('ILLEGAL_RECORDED_MOVE')
        board.push(move)
        if i+1==cut:before=balance(board)
    # In a certified disconnect opportunity, the disconnected recipient is the
    # side to move after the final recorded move. This is never inferred for
    # ordinary endings, and the target table was checked against panel i/j.
    sign=1 if board.turn==chess.WHITE else -1
    digest=hashlib.sha256((startfen+'|'+' '.join(m.uci() for m in moves)).encode()).hexdigest()
    return dict(net_material_change_4ply=int(sign*(balance(board)-before)),window_plies=min(4,len(moves)),move_sequence_sha256=digest)

def target_table(paths,binding,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE TEMP TABLE target AS SELECT game_id,recipient_id,opponent_id FROM '+io.parq([paths['S0']])+
                ' UNION SELECT game_id,recipient_id,opponent_id FROM '+io.parq([paths['F50']])+' WHERE recipient_disconnect_main')
            if c.execute('SELECT count(*)-count(DISTINCT game_id) FROM target').fetchone()[0]:raise RuntimeError('Two disconnection roles for one game')
            needed=['game_id','disconnected_user_id','chooser_user_id','ply_count','engine_eval_cp_disconnected','disconnected_clock_last_obs_s','fair_competitive']
            partpaths=[]
            for i,record in enumerate(binding['source']['panels']):
                path=Path(record['path']);io.checked(path,record['sha256'],record['bytes'])
                env_common.checked_columns(path,needed)
                c.execute('CREATE OR REPLACE VIEW p AS SELECT '+','.join(needed)+' FROM '+io.parq([path]))
                if c.execute('SELECT count(*) FROM target t JOIN p USING(game_id) WHERE t.recipient_id<>p.disconnected_user_id OR t.opponent_id<>p.chooser_user_id').fetchone()[0]:
                    raise RuntimeError('Part C recipient role differs from certified panel')
                dest=tmp/f'panel_{i:02}.parquet'
                io.copy(c,'SELECT p.* FROM p SEMI JOIN target USING(game_id)',dest);partpaths.append(dest)
            c.execute('CREATE VIEW allp AS SELECT * FROM '+io.parq(partpaths))
            n=c.execute('SELECT count(*) FROM target').fetchone()[0]
            if c.execute('SELECT count(*),count(DISTINCT game_id) FROM allp').fetchone()!=(n,n):raise RuntimeError('Missing or duplicate certified Part C endpoints')
            io.copy(c,'SELECT * FROM allp ORDER BY game_id',tmp/'targets.parquet')
            for p in partpaths:p.unlink()
            return dict(rows=n)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[paths['S0'],paths['F50']]+[r['path'] for r in binding['source']['panels']])[0]/'targets.parquet'

def inventory(project,extra_roots=()):
    roots=cache_scan.discover(project)+[project/'derived/replication/pgn_timeforfeit_candidates']+[Path(p).expanduser().resolve() for p in extra_roots]
    seen=set();records=[]
    for root in roots:
        if not root.is_dir():continue
        for p in sorted(root.rglob('*')):
            if not p.is_file() or any(v.startswith('.') or '.partial' in v or 'quarantine' in v.lower() for v in p.relative_to(root).parts):continue
            p=p.resolve()
            if p in seen:continue
            seen.add(p);kind=cache_scan.kind(p)
            if p.suffix=='.parquet':
                names=set(pq.ParquetFile(p).schema_arrow.names)
                if ('game_id' in names or 'id' in names) and names.intersection(MOVE_FIELDS+JSON_FIELDS):kind='parquet'
                else:continue
            if kind:records.append(dict(path=str(p),kind=kind,signature=io.sig(p)))
    return records

def move_job(job):
    threads_one();no_network()
    def build(tmp):
        targets=arrays(io.read(job['targets'],['game_id','ply_count']))
        lookup=dict(zip(targets['game_id'].tolist(),targets['ply_count'].tolist()));rows=[];read=0;hits=0;failures=[]
        writer=pq.ParquetWriter(tmp/'moves.parquet',SCHEMA,compression='zstd')
        def add(obj,fallback_id=None):
            nonlocal read,hits,rows
            read+=1
            if not isinstance(obj,dict):return
            gid=str(obj.get('id',obj.get('game_id',fallback_id)) or '')
            if gid not in lookup:return
            candidates=[obj[k] for k in MOVE_FIELDS if isinstance(obj.get(k),str) and obj[k].strip()]
            if not candidates:return
            # Parse every recorded candidate; conflicting legal complete replays
            # are caught by digest reconciliation instead of file-order priority.
            for value in candidates:
                row=dict(game_id=gid,valid=False,reason=None,net_material_change_4ply=None,move_sequence_sha256=None,window_plies=None,opening_tag=None)
                try:
                    row.update(replay(value,lookup[gid],obj.get('initialFen') or obj.get('initial_fen')))
                    row['valid']=True
                    opening=obj.get('opening');row['opening_tag']=opening.get('eco') if isinstance(opening,dict) else obj.get('eco')
                except (ValueError,TypeError,IndexError) as error:row['reason']=str(error)[:120]
                rows.append(row);hits+=1
                if len(rows)>=8192:writer.write_table(pa.Table.from_pylist(rows,schema=SCHEMA));rows=[]
        try:
            for rec in job['inputs']:
                p=Path(rec['path'])
                if io.sig(p)!=rec['signature']:raise RuntimeError('Move source changed before read: '+str(p))
                try:
                    if rec['kind']=='parquet':
                        names=pq.ParquetFile(p).schema_arrow.names;key='game_id' if 'game_id' in names else 'id'
                        cols=[key]+[k for k in MOVE_FIELDS+JSON_FIELDS+('initial_fen','initialFen','eco') if k in names]
                        for batch in pq.ParquetFile(p).iter_batches(columns=cols,batch_size=8192,use_threads=False):
                            for row in batch.to_pylist():
                                gid=str(row.get(key) or '')
                                if gid not in lookup:continue
                                add(row,gid)
                                for field in JSON_FIELDS:
                                    if row.get(field):
                                        try:obj=json.loads(row[field]) if isinstance(row[field],str) else row[field]
                                        except (ValueError,TypeError):failures.append(dict(source=p.name,reason='INVALID_JSON_CELL'));continue
                                        if isinstance(obj,dict) and any(k in obj for k in MOVE_FIELDS):add(obj,gid)
                                        else:
                                            for obj1 in cache_scan.games(obj):add(obj1,gid)
                    else:
                        for obj in cache_scan.objects(p):add(obj)
                except (ValueError,UnicodeError,EOFError,OSError) as error:
                    failures.append(dict(source=p.name,reason=type(error).__name__))
                if io.sig(p)!=rec['signature']:raise RuntimeError('Move source changed during read: '+str(p))
            if rows:writer.write_table(pa.Table.from_pylist(rows,schema=SCHEMA))
        finally:writer.close()
        io.js(tmp/'parse_gaps.json',failures)
        return dict(source_files=len(job['inputs']),records_read=read,target_records=hits,parse_gaps=len(failures))
    return stable_stage(Path(job['output']),job['conf'],build,[job['targets']]+[r['path'] for r in job['inputs']])[1]

def prepare(paths,binding,project,root,conf,memory,workers,runtime,extra_roots=()):
    targets=target_table(paths,binding,root/'targets',conf,memory-1)
    invpath=root/'move_inventory_PRIVATE.json'
    if invpath.exists():records=io.load(invpath)
    else:records=inventory(project,extra_roots);io.js(invpath,records)
    for rec in records:
        if io.sig(rec['path'])!=rec['signature']:raise RuntimeError('Frozen move inventory changed; do not mix snapshots')
    jobs=[]
    for i,group in enumerate(cache_scan.group_jobs(records)):
        jobs.append(dict(inputs=group,targets=str(targets),output=str(root/'move_parts'/f'{i:05}'),conf=conf,
            memory_estimate_gb=.6+pq.ParquetFile(targets).metadata.num_rows*450/1024**3))
    if jobs:fit_map(move_job,jobs,runtime,workers,memory,'Recorded move replay (local caches only)',lambda:None)
    parts=[Path(j['output'])/'moves.parquet' for j in jobs]
    def build(tmp):
        c=io.conn(tmp/'spill',memory-1,1)
        try:
            if parts:c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq(parts))
            else:
                io.table(tmp/'empty.parquet',pa.Table.from_pylist([],schema=SCHEMA));c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq([tmp/'empty.parquet']))
            c.execute('CREATE VIEW t AS SELECT * FROM '+io.parq([targets]))
            c.execute('''CREATE TEMP TABLE v AS SELECT game_id,count(DISTINCT move_sequence_sha256) nd,
                min(net_material_change_4ply) delta,min(window_plies) window_plies,min(opening_tag) opening_tag FROM m WHERE valid GROUP BY game_id''')
            c.execute('CREATE VIEW bad AS SELECT game_id,string_agg(DISTINCT reason,\'; \') reasons FROM m WHERE NOT valid GROUP BY game_id')
            q="""SELECT t.*, coalesce(v.nd=1,false) moves_available,
                CASE WHEN v.nd=1 THEN delta ELSE NULL END net_material_change_4ply,
                CASE WHEN v.nd=1 THEN window_plies ELSE NULL END window_plies,
                CASE WHEN v.nd=1 THEN opening_tag ELSE NULL END opening_tag,
                CASE WHEN v.nd>1 THEN 'CONFLICTING_COMPLETE_REPLAYS' WHEN v.nd=1 THEN NULL
                     ELSE coalesce(bad.reasons,'NO_LOCAL_MOVE_HISTORY') END move_missing_reason
                FROM t LEFT JOIN v USING(game_id) LEFT JOIN bad USING(game_id) ORDER BY game_id"""
            io.copy(c,q,tmp/'features.parquet')
            return dict(targets=pq.ParquetFile(targets).metadata.num_rows,
                moves_available=c.execute('SELECT count(*) FROM v WHERE nd=1').fetchone()[0],source_files=len(records),network_requests=0,stockfish_searches=0)
        finally:finish_connection(c,tmp/'spill')
    features,info=stable_stage(root/'features',conf,build,[targets]+parts)
    attached={}
    for sample in ('S0','F50'):
        def attach(tmp,sample=sample):
            c=io.conn(tmp/'spill',memory-1,1)
            try:
                c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([paths[sample]]));c.execute('CREATE VIEW b AS SELECT * FROM '+io.parq([features/'features.parquet']))
                names=pq.ParquetFile(paths[sample]).schema_arrow.names
                common=(set(names)&set(pq.ParquetFile(features/'features.parquet').schema_arrow.names))-{'game_id'}
                for key in sorted(common):
                    if c.execute('SELECT count(*) FROM a JOIN b USING(game_id) WHERE a.'+key+' IS DISTINCT FROM b.'+key).fetchone()[0]:
                        raise RuntimeError('Part C endpoint feature conflict: '+key)
                fields='a.*,'+','.join('b.'+k for k in pq.ParquetFile(features/'features.parquet').schema_arrow.names if k!='game_id' and k not in names)
                n=io.copy(c,'SELECT '+fields+' FROM a LEFT JOIN b USING(game_id) ORDER BY a.row_id',tmp/'model.parquet')
                if n!=pq.ParquetFile(paths[sample]).metadata.num_rows:raise RuntimeError('Part C join multiplied rows')
                return dict(rows=n)
            finally:finish_connection(c,tmp/'spill')
        p,_=stable_stage(root/('attached_'+sample),conf,attach,[paths[sample],features/'features.parquet']);attached[sample]=p/'model.parquet'
    return attached,info
