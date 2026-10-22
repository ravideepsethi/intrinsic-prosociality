"""Regression tests for the actual UCI failure, targeted repair and resume."""
from common import *
import argparse, asyncio, gzip, tempfile, sys, shlex
import chess, chess.engine
from score_stream import ScoreStream, collect
from repair import inventory_unit, score_jobs, evaluate_batch, shard_overlays, project_unit
from lineage import digest
from features import one_game


def test_messages():
    def message(cp=None,mate=None,nodes=100001,**kw):
        return dict(score=chess.engine.PovScore(chess.engine.Cp(cp) if mate is None else chess.engine.Mate(mate),chess.WHITE),nodes=nodes,depth=10,**kw)
    s=ScoreStream();s.post(message(25,nodes=50000,lowerbound=True));s.post(message(12))
    r=s.finish();assert r['cp_white']==12 and r['stale_bound'] and r['status']=='SCORED'
    s=ScoreStream();s.post(message(12,nodes=75000));s.post(message(25,lowerbound=True))
    r=s.finish();assert r['cp_white']==12 and r['used_prior_exact'] and r['score_nodes']==75000 and r['nodes']==100001
    s=ScoreStream();s.post(message(25,lowerbound=True));assert s.finish()['status']=='NO_EXACT_SCORE'
    s=ScoreStream();s.post(message(mate=-3,nodes=50000));s.post({'nodes':100010})
    r=s.finish();assert r['mate_white']==-3 and r['score_nodes']==50000 and r['nodes']==100010
    # A later unbounded score supersedes prior exact AND bound messages.
    s.post(message(-90,nodes=100010));assert s.finish()['cp_white']==-90 and s.finish()['mate_white'] is None


def fake_engine(path):
    # Exercise python-chess's real process/protocol path with deterministic UCI.
    script=path.with_suffix('.py')
    script.write_text('''
import sys,chess
b=chess.Board()
for line in sys.stdin:
 line=line.strip()
 if line=='uci':
  print('id name Stockfish 18 TEST FIXTURE');print('option name Threads type spin default 1 min 1 max 10');print('option name Hash type spin default 64 min 1 max 1024');print('uciok',flush=True)
 elif line=='isready':print('readyok',flush=True)
 elif line.startswith('position fen '):b=chess.Board(line[len('position fen '):])
 elif line.startswith('position startpos'):b=chess.Board()
 elif line.startswith('go '):
  move=next(iter(b.legal_moves)).uci()
  print('info depth 9 score cp 10 nodes 40000 pv '+move)
  if b.fullmove_number%2:
   print('info depth 10 score cp 30 lowerbound nodes 60000 pv '+move)
   print('info depth 11 score cp 12 nodes 100050 pv '+move)
  else:
   print('info depth 10 score cp 12 nodes 75000 pv '+move)
   print('info depth 11 score cp 30 upperbound nodes 100050 pv '+move)
  print('bestmove '+move,flush=True)
 elif line=='quit':break
''')
    path.write_text('#!/bin/bash\nexec '+shlex.quote(sys.executable)+' -u '+shlex.quote(str(script))+'\n')
    path.chmod(0o755)


def test_pipeline(real_engine=None):
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);engine=Path(real_engine).resolve() if real_engine else root/'fake_stockfish'
        if not real_engine:fake_engine(engine)
        board=chess.Board();positions=[dict(ply=0,fen=board.fen())]
        for i,san in enumerate(['e4','e5','Nf3','Nc6'],1):
            board.push_san(san);positions.append(dict(ply=i,fen=board.fen()))
        game=dict(game_id='SYNTHETIC_GAME',n=4,color='white',status='VERIFIED',positions=positions)
        raw=[dict(game_id=game['game_id'],color='white',**pos,cp=None,mate=None,nodes=100050,depth=11,status='BOUNDED') for pos in positions]
        # One usable record must be carried through without searching its FEN.
        raw[0].update(cp=42,status='SCORED')
        replay=root/'replay.json';dump(replay,[game]);scores=root/'original.json.gz'
        with gzip.open(scores,'wt') as f:json.dump(raw,f)
        for p in [replay,scores]:dump(str(p)+'.receipt.json',dict(key='test-key',sha256=digest(p)))
        original_hash=digest(scores)
        unit=dict(name='000000',replay=str(replay),scores=str(scores),key='test-key')
        inv,meta=inventory_unit((unit,str(root/'inventory'),'inv'))
        invstamp=Path(inv).stat().st_mtime_ns
        inventory_unit((unit,str(root/'inventory'),'inv'));assert invstamp==Path(inv).stat().st_mtime_ns
        fens=pd.read_parquet(inv).fen.tolist();assert len(fens)==4 and positions[0]['fen'] not in fens
        jobs=score_jobs(fens+fens,root/'repaired',engine,sha(engine),sha(ROOT/'score_stream.py'))
        assert sum(len(j['fens']) for j in jobs)==4
        outputs=[evaluate_batch(j) for j in jobs]
        stamps={r['path']:Path(r['path']).stat().st_mtime_ns for r in outputs}
        assert all(evaluate_batch(j)['cached'] for j in jobs)
        assert all(Path(p).stat().st_mtime_ns==t for p,t in stamps.items())
        repaired=pd.concat([pd.read_parquet(r['path']) for r in outputs],ignore_index=True)
        assert (repaired.status=='SCORED').all()
        if not real_engine:
            assert repaired.stale_bound.any() and repaired.used_prior_exact.any()
        shards=shard_overlays([inv],repaired,root/'shards','test')
        dest=root/'features.parquet';project_unit((unit,str(dest),'project',shards['000000']))
        result=pd.read_parquet(dest).iloc[0]
        assert result.trajectory_ok and not one_game(game,raw)['trajectory_ok']
        assert result.material_swing4==0 and result.replay_status=='VERIFIED'
        before=dest.stat().st_mtime_ns;project_unit((unit,str(dest),'project',shards['000000']))
        assert dest.stat().st_mtime_ns==before and digest(scores)==original_hash
        # Cross-color orientation uses one white-oriented result per FEN.
        from repair import legacy_patch
        selected=repaired.iloc[0].to_dict();w=legacy_patch(dict(color='white'),selected);b=legacy_patch(dict(color='black'),selected)
        assert w['cp']==-b['cp']
        # Damaged authenticated input cannot silently become a new source.
        with gzip.open(scores,'wt') as f:json.dump([],f)
        try:inventory_unit((unit,str(root/'bad'),'new-key'))
        except RuntimeError:pass
        else:raise AssertionError('Accepted damaged original scores')


def main():
    p=argparse.ArgumentParser();p.add_argument('--engine');args=p.parse_args()
    test_messages();test_pipeline(args.engine)
    print('REPAIR_TEST_OK: atomic flags; genuine final-bound fallback; complete search vs score nodes; UCI process; selective FEN repair; cache resume; unchanged inputs; color; damaged-input rejection.')


if __name__=='__main__':main()
