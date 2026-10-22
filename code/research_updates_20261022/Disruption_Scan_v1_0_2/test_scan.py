#!/usr/bin/env python3
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
from support import *
from aggregate import api_month,traffic_month
from detector import baseline,before_traffic,find_seeds,select_episodes,validate,centered,grid
from reporting import diagnostics,plot_episodes,review_text

class TestScan(unittest.TestCase):
 def test_month_binding_ignores_batch_range(self):
  for m in ('2023-11','2023-12','2024-01'):
   p=Path('/project/output/api_enrich_main_2023-11_to_2024-01_20260516')/(m+'_lookup_targeted5s_20260519')/'game_status_lookup.parquet'
   self.assertEqual(legacy_month(p),m)
  self.assertEqual(legacy_month('/project/kit_2024-06_to_2024-09/output/2024-08_lookup_20260521/game_status_lookup.parquet'),'2024-08')
  with self.assertRaises(ValueError):legacy_month('/project/kit_2024-06_to_2024-09/game_status_lookup.parquet')
 def test_discovery_reports_missing_legacy_accounts(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);selector=root/'output/api_enrichment_canonical_inventory_20260601_163807/canonical_lookup_parquet_paths.txt';selector.parent.mkdir(parents=True)
   item,df=self.fixture(root,300);df=df.drop(columns=['white_username_norm','black_username_norm'])
   p=root/'output/api_enrich_main_2023-11_to_2024-01/2023-12_lookup_safe300/game_status_lookup.parquet';p.parent.mkdir(parents=True);df.to_parquet(p,index=False)
   excluded=root/'output/2023-10_lookup_safe300/game_status_lookup.parquet'
   selector.write_text(str(p.relative_to(root))+'\n'+str(excluded.relative_to(root))+'\n');details=[]
   items,issues=discover(root,details)
   self.assertEqual(items,[]);self.assertEqual(len(issues),1);self.assertEqual(issues[0]['month'],'2023-12')
   self.assertEqual(issues[0]['reason'],'Required raw API fields unavailable: white,black')
   snapshot=next(d for d in details if d['month']=='2023-12');self.assertEqual(snapshot['missing_required_fields'],['white','black'])
   self.assertEqual(snapshot['rows'],300);self.assertNotIn('g0000001',json.dumps(details))
   # A schema-compatible legacy leaf is admitted only at its authoritative count.
   df['white_username']='white';df['black_username']='black';df.to_parquet(p,index=False)
   with patch.dict('support.LEGACY_COUNTS',{'2023-12':300}):items,issues=discover(root)
   self.assertEqual(len(items),1);self.assertEqual(items[0]['month'],'2023-12');self.assertEqual(issues,[])
 def test_centered_alignment(self):
  np.testing.assert_allclose(centered(np.arange(9),5)[2:7],[10,15,20,25,30])
 def test_returned_legacy_schema_projects_identically(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);item,df=self.fixture(root)
   canonical=api_month(item,root/'canonical','test',2,'512MB')
   legacy=df.rename(columns={'game_id':'id','api_status':'status','created_at_ms':'createdAt','last_move_at_ms':'lastMoveAt','white_username_norm':'white_name','black_username_norm':'black_name','is_draw':'draw'})
   legacy.white_name=legacy.white_name.str.upper();legacy.black_name=' '+legacy.black_name+' '
   legacy['perf']='blitz';legacy['winner']='white';legacy['white_rating']=1500;legacy['black_rating']=1550;legacy['draw']=legacy['draw'].astype('int64')
   expected_schema=read(PKG/'evidence/legacy_schema_report.json')['schemas'][0]['fields']
   path=root/'legacy.parquet';legacy[[f['name'] for f in expected_schema]].to_parquet(path,index=False)
   self.assertEqual([dict(name=f.name,type=str(f.type)) for f in pq.ParquetFile(path).schema_arrow],expected_schema)
   newer=dict(item,paths=[str(path)],source='curated_legacy');summary=api_month(newer,root/'legacy','test',2,'512MB')
   self.assertEqual(summary['included'],canonical['included']);self.assertTrue(summary['coverage_usable'])
   pd.testing.assert_frame_equal(pd.read_parquet(root/'canonical/events.parquet'),pd.read_parquet(root/'legacy/events.parquet'))
   pd.testing.assert_frame_equal(pd.read_parquet(root/'canonical/minute_counts.parquet').sort_values(['minute','fold','speed','status']).reset_index(drop=True),pd.read_parquet(root/'legacy/minute_counts.parquet').sort_values(['minute','fold','speed','status']).reset_index(drop=True))
   # Admit the observed schema through the actual curated selector and month binder.
   target=root/'output/kit_2024-06_to_2024-09/output/2024-06_lookup_safe300/game_status_lookup.parquet';target.parent.mkdir(parents=True);target.write_bytes(path.read_bytes())
   selector=root/'output/api_enrichment_canonical_inventory_20260601_163807/canonical_lookup_parquet_paths.txt';selector.parent.mkdir(parents=True);selector.write_text(str(target.relative_to(root))+'\n')
   with patch.dict('support.LEGACY_COUNTS',{'2024-06':len(legacy)}):items,issues=discover(root)
   self.assertEqual(issues,[]);self.assertEqual(len(items),1);self.assertEqual(items[0]['expected_rows'],len(legacy))
 def test_legacy_account_alias_conflicts_are_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);item,df=self.fixture(root,300)
   df['white_name']=df.white_username_norm;df['black_name']=df.black_username_norm
   df.loc[0,'white_name']='different_account';df.to_parquet(item['paths'][0],index=False)
   with self.assertRaises(RuntimeError):api_month(item,root/'bad_white','test',2,'512MB')
   df['white_name']=df.white_username_norm;df.loc[0,'black_name']='different_account';df.to_parquet(item['paths'][0],index=False)
   with self.assertRaises(RuntimeError):api_month(item,root/'bad_black','test',2,'512MB')
 def test_traffic_is_predetermined(self):
  x=np.ones(200);a=before_traffic(x);x[100:110]=1000;b=before_traffic(x)
  self.assertEqual(a[100],50);self.assertEqual(a[100],b[100]);self.assertGreater(b[150],a[150])
 def test_peak_detected_and_replicates(self):
  n=85*1440;i=42*1440+733;x=np.full((2,n),10,dtype=np.int64);x[0,i]+=500;x[1,i]+=450
  counts={'all':x};valid=np.ones(n,bool);seeds=find_seeds(counts,valid);eps=select_episodes(seeds)
  self.assertEqual(len(eps),1);self.assertEqual(eps[0]['minute_index'],i)
  out=validate(eps,counts,valid);self.assertTrue(out[0]['replicates_in_disjoint_accounts'])
 def test_validation_cannot_create_or_rank_events(self):
  n=85*1440;i=42*1440+733;x=np.full((2,n),10,dtype=np.int64);x[1,i]+=500
  self.assertEqual(find_seeds({'all':x},np.ones(n,bool)),[])
  x[0,i]+=500;eps=select_episodes(find_seeds({'all':x},np.ones(n,bool)));x[1]=10
  self.assertFalse(validate(eps,{'all':x},np.ones(n,bool))[0]['replicates_in_disjoint_accounts'])
 def test_missing_coverage_and_reference_count(self):
  n=85*1440;i=42*1440;x=np.ones(n)*10;x[i]=1000;v=np.ones(n,bool);v[i]=False
  self.assertFalse(baseline(x,v,1)['eligible'][i])
  v[:]=False;v[i]=True;self.assertFalse(baseline(x,v,1)['eligible'][i])
  full=grid(['2024-03']);start=(ms('2024-03-01')-START)//MINUTE
  self.assertFalse(full[start+6*1440]);self.assertTrue(full[start+8*1440])
 def test_busy_traffic_adjustment(self):
  n=85*1440;i=42*1440+733;x=np.full(n,10.);x[i]=100;v=np.ones(n,bool);traffic=np.ones(n)*500
  traffic[i]=2000;x[i]=40
  a=baseline(x,v,1,traffic);self.assertAlmostEqual(a['expected'][i],40);self.assertAlmostEqual(a['score'][i],0)
 def test_account_disjoint_sql_matches_python(self):
  names=[f'player{i}' for i in range(100)]
  c=duckdb.connect();d=pd.DataFrame(dict(white=names,black=names[::-1]));c.register('x',d)
  actual=c.execute('SELECT '+fold_sql()+' AS fold FROM x').fetchnumpy()['fold'];c.close()
  expected=[player_bit(w) if player_bit(w)==player_bit(b) else 2 for w,b in zip(names,names[::-1])]
  np.testing.assert_array_equal(actual,expected)
 def fixture(self,root,n=9000):
  root=Path(root);m='2024-06';a,b=bounds(m);paths=[]
  # Uniform deterministic timing; mixed terminal status. Each game has unrelated names.
  df=pd.DataFrame(dict(game_id=[f'g{k:07d}' for k in range(n)],api_status=np.where(np.arange(n)%3==0,'timeout','outoftime'),
    created_at_ms=a+(np.arange(n)%10000)*1000,last_move_at_ms=a+10*DAY+(np.arange(n)%10000)*1000,
    white_username_norm=[f'w{k}' for k in range(n)],black_username_norm=[f'b{k}' for k in range(n)],
    speed='blitz',rated=True,variant='standard',is_draw=np.arange(n)%7==0))
  # All durations under the seven-day cap; input creation month remains June.
  df.created_at_ms=df.last_move_at_ms-300000
  p=root/'raw.parquet';df.to_parquet(p,index=False)
  return dict(month=m,source='synthetic',paths=[str(p)],expected_rows=n,receipts=[]),df
 def test_real_projection_and_aggregate_conservation(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);item,df=self.fixture(root);s=api_month(item,root/'api/2024-06','test',2,'512MB')
   self.assertEqual(s['included'],len(df));self.assertTrue(s['coverage_usable'])
   x=pd.read_parquet(root/'api/2024-06/events.parquet');bins=pd.read_parquet(root/'api/2024-06/minute_counts.parquet')
   self.assertEqual(bins.n.sum(),len(df));self.assertNotIn('is_draw',x.columns)
   self.assertTrue((x.t>=x.start_ms).all())
   # Draw labels are never projected; toggling them leaves all detection inputs unchanged.
   old=x.copy();df.is_draw=~df.is_draw;df.to_parquet(item['paths'][0],index=False)
   s2=api_month(item,root/'api/2024-06','test',2,'512MB');new=pd.read_parquet(root/'api/2024-06/events.parquet')
   pd.testing.assert_frame_equal(old,new);self.assertNotEqual(s['signature'],s2['signature'])
 def test_duplicate_ids_and_conflicting_timestamps_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);item,df=self.fixture(root,300)
   df.loc[1,'game_id']=df.loc[0,'game_id'];df.to_parquet(item['paths'][0],index=False)
   with self.assertRaises(RuntimeError):api_month(item,root/'bad','test',2,'512MB')
   item,df=self.fixture(root,300);df['lastMoveAt']=df.last_move_at_ms+1;df.to_parquet(item['paths'][0],index=False)
   with self.assertRaises(RuntimeError):api_month(item,root/'conflict','test',2,'512MB')
 def test_checkpoint_changed_bytes_invalidates(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);p=root/'x';p.write_text('old');done(root,'s',[p]);self.assertTrue(resumed(root,'s'))
   p.write_text('new');self.assertFalse(resumed(root,'s'))
 def test_diagnostics_and_privacy(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);item,df=self.fixture(root);summary=api_month(item,root/'api/2024-06','test',2,'512MB')
   idx=(int(df.last_move_at_ms.iloc[0])-START)//MINUTE
   e=dict(episode_id='E001',minute_index=idx,series='blitz',width_minutes=5,discovery_score=20,discovery_ratio=3,
    validation_score=18,validation_ratio=2.8,replicates_in_disjoint_accounts=True)
   out=diagnostics(root,[e],[summary],2,'512MB',root,with_main=False)
   self.assertEqual(len(out),1);self.assertIn('discovery_screen_accounts',out[0]);self.assertFalse(out[0]['externally_verified_outage'])
   review_text(root/'public',out,[summary],'test',[])
   text='\n'.join(p.read_text() for p in (root/'public').rglob('*') if p.is_file())
   self.assertNotIn('g0000001',text);self.assertNotIn('w1234',text)
 def test_traffic_aggregation_and_resume(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);rel=Path('chron/speed=blitz/month=2024-06/part-00000.parquet');p=root/rel;p.parent.mkdir(parents=True)
   a,b=bounds('2024-06');pd.DataFrame({'utc_ms':[a,a+1000,0]}).to_parquet(p,index=False)
   pf=pq.ParquetFile(p);entry=dict(path='/Volumes/XT_Pro/lichess_kindness/'+str(rel),bytes=p.stat().st_size,rows=3,row_groups=pf.metadata.num_row_groups)
   with patch('aggregate.read',return_value={'entries':[entry]}):
    result=traffic_month(root,'2024-06',root/'traffic','code',2,'512MB')
   self.assertTrue(result['available']);self.assertEqual(result['starts'],2)
   self.assertEqual(pd.read_parquet(root/'traffic/starts.parquet').n.sum(),2)
   self.assertTrue(resumed(root/'traffic',result['signature']))
 def test_main_overlay_does_not_require_kindness_column(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);item,df=self.fixture(root);s=api_month(item,root/'api/2024-06','test',2,'512MB')
   t=int(df.last_move_at_ms.iloc[0]);idx=(t-START)//MINUTE
   mp=root/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel/month=2024-06/analysis_panel.parquet';mp.parent.mkdir(parents=True)
   pd.DataFrame(dict(game_id=['z0000001'],api_last_move_at_ms=[t],fair_competitive=[True],clearly_worse=[False],chooser_clock_last_obs_s=[45.],disconnected_clock_last_obs_s=[30.])).to_parquet(mp,index=False)
   contract={'panel_outputs':[dict(relative_path='panel/month=2024-06/analysis_panel.parquet',rows=1,size_bytes=mp.stat().st_size,sha256=sha(mp))]}
   e=dict(episode_id='E001',minute_index=idx,series='blitz',width_minutes=5,discovery_score=20,discovery_ratio=3,validation_score=18,validation_ratio=2.8,replicates_in_disjoint_accounts=True)
   with patch('reporting.read',return_value=contract):out=diagnostics(root,[e],[s],2,'512MB',root,with_main=True)
   d=pd.read_csv(root/'public/main_sample_choice_availability.csv');self.assertEqual(d.main_sample_choices.iloc[0],1)
 def test_missing_fields_do_not_use_timeout_panel_as_fallback(self):
  with self.assertRaises(ValueError):mapping(['game_id','status','utc_ms','chooser_user_id','api_last_move_at_ms'])

if __name__=='__main__':unittest.main(verbosity=2)
