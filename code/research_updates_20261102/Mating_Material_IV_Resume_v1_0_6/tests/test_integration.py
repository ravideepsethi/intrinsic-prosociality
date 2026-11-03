import sys,unittest,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
from types import SimpleNamespace
import exposures,features
from unittest.mock import patch

class IntegrationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=SimpleNamespace(workers=1,memory_gb=4.)
    def tearDown(self):self.tmp.cleanup()
    def file(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.table(data),p);return p
    def test_fresh_exposure_first_pairs_and_pre_arm_ranking(self):
        start=int(c.phase_inputs.core.STARTS[5]);ids=['oldgood1','oldbad01','newgood1','newbad01','firstbad']
        main=dict(game_id=ids,chooser_user_id=[10]*5,disconnected_user_id=[20,21,22,23,20],utc_ms=[start,start,start,start,start-1],api_last_move_at_ms=[start+1]*5,
          archive_ordinal=[0,1,2,3,4],kind_draw=[False,False,True,True,False],timeout_chooser_win=[True,True,False,False,False],api_speed=['blitz']*5,tc_base_s=[300]*5,tc_inc_s=[0]*5,disconnected_elo=[1500.]*5,chooser_elo=[1500.]*5,disconnected_pre_rd_v2=[50.]*5,chooser_pre_rd_v2=[50.]*5,fair_competitive=[True]*5,tournament_like_event=[False]*5)
        mp=self.file('main.parquet',main);hp=self.file('oldh.parquet',dict(gid=ids,y=[False]*5))
        raw=self.file('oldraw.parquet',dict(row_id=[10],game_id=['oldgood1'],recipient_id=[20],opponent_id=[10],archive_start_ms=[start],anchor_ms=[start+1]))
        chron=self.file('chron.parquet',dict(utc_ms=[start,start-100,start],white_id=[22,23,23],black_id=[10,10,10]))
        rec=dict(path=str(chron),signature=c.frozen.r.io.sig(chron),rows=3,minimum=start-100)
        bound=dict(binding=dict(source=dict(chron=[rec])))
        b=dict(bound=bound)
        auth=dict(material=dict(records=[dict(path=str(mp),month='2024-04')]),legacy=dict(raw=str(raw),bound=dict(parts=[dict(path=str(hp))])))
        out=exposures.build(self.a,self.root/'run','exposure_test',auth,b)
        t=pq.read_table(out).to_pydict()
        self.assertEqual(set(t['game_id']),{'oldgood1','newgood1'})
        first=dict(zip(t['game_id'],t['first_recipient']));self.assertFalse(first['oldgood1']);self.assertTrue(first['newgood1'])
    def test_environment_pair_exclusion_and_incomplete_windows(self):
        # Window [100,200), resolution strictly before 200. Focal pair 1/2
        # contributes nothing to the correction. Denominators are unchanged.
        source=self.file('source.parquet',dict(row_id=[0,1,2],recipient_id=[2,7,9],opponent_id=[1,1,1],month_code=[0,0,1]))
        rates=self.file('rates.parquet',dict(person=[1,1,1],partner=[2,7,9],month_code=[0,0,1],complete=[True,True,False],lo=[100]*3,hi=[200]*3,games=[10,10,0],own=[3,3,0],chooser=[4,4,0],environment_supported=[True,True,False],opponent_observed_disconnect_rate=[.3,.3,None],opponent_observed_chooser_rate=[.4,.4,None],log_opponent_games90=[float(np.log(11)),float(np.log(11)),None]))
        removed=self.file('removed.parquet',dict(game_id=['a','b','c','d','e'],start_ms=[100,150,150,200,150],end_ms=[101,151,200,201,151],i=[1,3,1,1,1],j=[2,1,8,8,4]))
        def frozen(a,run,conf,b,source):
            import shutil
            p=Path(run)/'PRIVATE/wider/environment/combined/rates.parquet';p.parent.mkdir(parents=True);shutil.copy2(rates,p);return source
        with patch.object(features,'FROZEN_ENVIRONMENT',frozen):out=features.environment(self.a,self.root/'env','env',{},source,removed)
        t=pq.read_table(out).to_pydict();self.assertEqual(t['games'],[10,10,0]);self.assertEqual(t['own'],[2,1,0]);self.assertEqual(t['chooser'],[3,3,0]);self.assertEqual(t['environment_supported'],[True,True,False])
    def test_volume_reuses_identity_even_after_row_ids_change(self):
        src=self.file('new.parquet',dict(row_id=[100,101],game_id=['a','b'],recipient_id=[1,2],archive_start_ms=[1000,2000]))
        old=self.file('old.parquet',dict(row_id=[0,1],game_id=['b','a'],recipient_id=[2,1],archive_start_ms=[2000,1000],pre_games_90d=[8,9]))
        out=features.volume(self.a,self.root/'vol','vol',{},src,[old],90)
        t=pq.read_table(out).to_pydict();self.assertEqual(t['row_id'],[100,101]);self.assertEqual(t['pre_games_90d'],[9,8])
    def test_volume_rejects_conflicting_cached_facts(self):
        src=self.file('new.parquet',dict(row_id=[100],game_id=['a'],recipient_id=[1],archive_start_ms=[1000]))
        a=self.file('a.parquet',dict(game_id=['a'],recipient_id=[1],archive_start_ms=[1000],pre_games_90d=[8]))
        b=self.file('b.parquet',dict(game_id=['a'],recipient_id=[1],archive_start_ms=[1000],pre_games_90d=[9]))
        with self.assertRaises(RuntimeError):features.volume(self.a,self.root/'vol','vol',{},src,[a,b],90)

    def test_missing_volume_worker_gets_only_ids_and_preserves_wide_source(self):
        src=self.file('wide.parquet',dict(row_id=[100,101],game_id=['a','b'],recipient_id=[1,2],archive_start_ms=[1000,2000],payload=['x'*10000,None]))
        old=self.file('one_known.parquet',dict(game_id=['a'],recipient_id=[1],archive_start_ms=[1000],pre_games_90d=[9]))
        before=sha(src)
        for tag,known,expected_ids in [('part',[old],[101]),('none',[],[100,101])]:
            def fake_worker(a,run,conf,bound,source):
                table=pq.read_table(source)
                self.assertEqual(table.schema.names,['row_id','recipient_id','archive_start_ms'])
                self.assertEqual(table['row_id'].to_pylist(),expected_ids)
                table=table.append_column('pre_games_90d',pa.array([9 if x==100 else 8 for x in expected_ids],pa.int64()))
                target=Path(run)/'computed.parquet';target.parent.mkdir(parents=True,exist_ok=True)
                pq.write_table(table,target);return target
            with self.subTest(tag=tag),patch.object(features,'FROZEN_VOLUME90',side_effect=fake_worker):
                out=features.volume(self.a,self.root/tag,tag,{},src,known,90)
                t=pq.read_table(out)
                self.assertEqual(t['pre_games_90d'].to_pylist(),[9,8])
                self.assertEqual(t.drop(['pre_games_90d']).to_pydict(),pq.read_table(src).to_pydict())
                self.assertEqual(sha(src),before)

if __name__=='__main__':unittest.main()
