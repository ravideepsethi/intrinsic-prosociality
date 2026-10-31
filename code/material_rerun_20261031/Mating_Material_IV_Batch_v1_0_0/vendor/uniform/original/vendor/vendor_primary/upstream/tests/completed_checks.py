import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from types import SimpleNamespace
import completed_games as b
from local_common import *

PGN='''[Event "Rated Blitz game"]
[Site "https://lichess.org/AbCd1234"]
[White "fixture-white"]
[Black "fixture-black"]
[WhiteElo "1500"]
[BlackElo "1700"]
[TimeControl "180+0"]
[Result "0-1"]

1. f3 { [%clk 0:02:59] } e5 { [%clk 0:02:58] } 2. g4 { [%clk 0:02:57] } Qh4# { [%clk 0:02:56] } 0-1
'''
b.require_full_archive_coverage(dict(status='COMPLETE_24_MONTHS',months_used=MONTHS))
try:b.require_full_archive_coverage(dict(status='PARTIAL_AVAILABLE_MONTHS',months_used=['2023-11']))
except RuntimeError:pass
else:raise AssertionError('A one-month R13 population was accepted')

r=dict(game_id='AbCd1234',month_code=0,speed_code=2,pgn=PGN)
p=b.sample_position(r,42,np.array([2]),np.array([1.]))
assert p['available'] and p['ply']==2
assert p['gap']==(-200 if p['side_white'] else 200)
assert p['y']==int(not p['side_white'])
assert p['clock_d']==(179 if p['side_white'] else 178)
assert not b.sample_position(r,42,np.array([8]),np.array([1.]))['available']
assert b.sample_position(r,42,np.array([0]),np.array([1.]))['clock_c']==180
assert not b.eligibility('timeout','pool',False,None,'api-status-proxy')
assert not b.eligibility('mate','friend',False,None,'api-status-proxy')
assert b.eligibility('mate','pool',False,None,'strict-connected')
assert b.eligibility('outoftime','pool',False,None,'api-status-proxy')
try:b.eligibility('outoftime','pool',False,None,'strict-connected')
except RuntimeError:pass
else:raise AssertionError('Missing connectedness was accepted as observed')
try:b.eligibility('mate',None,False,None,'api-status-proxy')
except RuntimeError:pass
else:raise AssertionError('Missing pool source was accepted')
assert b.random_bits('AbCd1234',42,'game')==b.random_bits('AbCd1234',42,'game')
assert len({b.random_bits('AbCd1234',42,t) for t in ['game','ply','role']})==3
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'response.json';save(p,[{'id':'AbCd1234','source':'pool','status':'mate'}]);seal(p,key(['AbCd1234']))
    assert b.fetch_batch(['AbCd1234'],p,False)[0]['id']=='AbCd1234'
    td=Path(td);root=td/'PRIVATE/completed/fixture';root.mkdir(parents=True);(td/'report').mkdir()
    pg=td/'archive.pgn';pg.write_text(PGN)
    candidate=root/'candidates.parquet'
    b.candidate_month(dict(path=str(pg),out=str(candidate),key='candidate-test',month='2023-11',seed=42,limit=1<<128,speeds=[2]))
    metadata=td/'metadata.parquet';pd.DataFrame([dict(game_id='AbCd1234',source='pool',status='mate',both_connected=True)]).to_parquet(metadata,index=False)
    a=SimpleNamespace(metadata_source=[metadata],seed=42,completed_root=root,memory_gb=4,project=td,games=1,flag_policy='strict-connected',fetch_metadata=False,max_metadata_games=0)
    index=b.metadata_index(a,td,[candidate]);chosen=b.choose_games(a,td,'selection-test',[candidate],index)
    assert len(pd.read_parquet(chosen))==1
print('Completed-game selection gates, independent draws, clock orientation, censor attrition, and offline cache checks passed')
