from pathlib import Path
import sys,tempfile
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import comparison_audit as a
import pyarrow as pa,pyarrow.parquet as pq

def put(p,rows):p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.Table.from_pylist(rows),p)
with tempfile.TemporaryDirectory() as t:
 r=Path(t);run=r/'run';(run/'PRIVATE').mkdir(parents=True);(run/'report').mkdir()
 h=r/'donors.parquet';donors=[dict(j=10,i=2,arm=True)]*5+[dict(j=10,i=1,arm=True)]*8
 put(h,donors)
 a.mu.save(run/'PRIVATE/BOUND.json',dict(bound=dict(parts=[dict(path=str(h),sha256=a.mu.sha(h),rows=len(donors),bytes=h.stat().st_size)],binding=dict(author_ids=[101,102]))))
 f=r/'ledger.parquet';start=1711929600000
 put(f,[dict(game_id='abcdefgh',opponent_id=10,recipient_id=1,n7_author_clean=0,author_game=False,prior_97d_complete=True,previous_frame=False,utc_ms=start,speed_partition='blitz')])
 m=r/'cache'/'metadata.parquet'
 put(m,[dict(game_id='abcdefgh',source='pool',status='resign',api_start_ms=start,anchor_ms=start+1000,rated=True,variant='standard',speed='blitz',tc_base_s=300.,tc_inc_s=0.,white_username='a',black_username='b',white_rating=1500.,black_rating=1501.,winner='white',cached_conflict_or_prior_flag=False)])
 local=dict(ledgers=[str(f)],metadata=str(m),manifest=dict(original_cached_metadata=str(m)))
 args=SimpleNamespace(project=r,desktop=r,workers=1,memory_gb=11.,run=run,conf='synthetic')
 with mock.patch.object(a,'authenticate',return_value=local),mock.patch.object(a.checkpoint,'authenticate_checkpoint',return_value=dict(metadata=str(m))),mock.patch.object(a.ex,'MONTHS',['2024-04']),mock.patch.object(a.io,'complete',return_value={}):
  a.run(args)
 result=a.mu.load(run/'report/comparison_next_step.json')
 assert result['newly_count_supported_candidates']==1,result
 assert result['metadata_missing_conflicted_or_needing_legacy_source']==0,result
 print('Whole comparison audit synthetic integration passed')
