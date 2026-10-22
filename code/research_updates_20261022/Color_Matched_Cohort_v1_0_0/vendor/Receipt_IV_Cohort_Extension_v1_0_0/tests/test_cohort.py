from pathlib import Path
import datetime as dt,gzip,json,os,random,sys,tempfile,unittest
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
PKG=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PKG/'code'),str(PKG/'vendor')]
from common import *
import cohort_logic as logic
import source_stage,adjacency_stage,score_stage,membership_stage,inputs
import iv_numerics as num

def write(p,rows):p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.Table.from_pylist(rows),p);return p
def snap(p):return dict(**receipt(p),fingerprint=stamp(p))
def millis(s):return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()*1000)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"a root's path";self.root.mkdir()
        self.auth=self.root/'auth'
    def tearDown(self):self.tmp.cleanup()
    def conn(self):return connection(self.root/'spill',2,512)

    def test_three_valued_membership_does_not_infer_pool(self):
        c=self.conn()
        try:
            s=pa.table({'game_id':list(range(6)),'source':['pool',None,'lobby','pool','pool','pool'],
                'source_status':['recovered','missing','recovered','recovered','recovered','conflict']})
            a=pa.table({'game_id':list(range(6)),'previous_classification_status':[
                'not_mutually_adjacent_observed','not_mutually_adjacent_observed','left_boundary_unresolved',
                'ambiguous_start_order','mutual_adjacency_candidate_timing_unresolved','not_mutually_adjacent_observed']})
            c.register('s',s);c.register('a',a)
            got=[r[0] for r in c.execute('SELECT '+logic.membership_sql()+' FROM s JOIN a USING(game_id) ORDER BY game_id').fetchall()]
            self.assertEqual(got,[True,None,False,None,False,None])
        finally:c.close()

    def test_source_structure_conflicts_and_precision(self):
        t=millis('2026-01-02');rows=[];targets=[]
        spec=[('pool','timeout',t+600,None,True),('pool','timeout',t+601,'white',True),
              ('pool','timeout',t+1000,None,True),('pool',None,None,None,False),
              ('pool','timeout',t,None,True),('pool','timeout',t,None,True)]
        for k,(src,status,created,winner,present) in enumerate(spec):
            gid=f'g{k:07d}';targets.append(dict(game_id=gid,month='2026-01',utc_ms=t,
                api_created_at_ms=t+600 if k==1 else None,expected_winner=None))
            rows.append(dict(game_id=gid,source=src,status=status,created_at_ms=created,winner=winner,winner_present=present,
                invalid=False,provenance='test',record_number=k))
        rows.append(dict(rows[4],source='lobby'))
        rows[5]['invalid']=True
        c=self.conn()
        try:
            c.register('evidence',pa.Table.from_pylist(rows,schema=source_stage.original.SCHEMA))
            c.register('targets',pa.Table.from_pylist(targets))
            c.execute('CREATE VIEW recovered AS '+logic.source_reduce_sql())
            got=c.execute(logic.source_classify_sql(source_stage.original.SOURCES)+' ORDER BY game_id').fetchall()
            self.assertEqual([r[4] for r in got],['recovered','inconsistent_metadata','inconsistent_metadata',
                'unverified_record_structure','conflict','invalid_record'])
            self.assertEqual([r[2] for r in got],['pool',None,None,None,None,None])
        finally:c.close()

    def test_full_game_missing_winner_is_draw_not_unknown(self):
        obj=dict(id='abcdefgh',status='timeout',source='pool',createdAt=millis('2026-01-01'),players={})
        r=source_stage.normalize_record(obj);self.assertTrue(r['winner_present']);self.assertIsNone(r['winner'])
        r=source_stage.normalize_record(dict(game_id='abcdefgh',api_source='pool'))
        self.assertFalse(r['winner_present'])
        self.assertIsNone(source_stage.normalize_record(dict(source_block='pool')))

    def test_compressed_stream_matches_full_adjacency_random_ties(self):
        rng=random.Random(8547);games=[]
        months=['2023-09','2023-10','2023-11','2023-12','2024-01','2024-02']
        for k in range(2200):
            month=months[k//400] if k//400<len(months) else months[-1]
            p1,p2=rng.sample(range(1,90),2);start=millis(month+'-01')+rng.randrange(30)*1000
            games.append(dict(game_id=f'g{k:07d}',p1=p1,p2=p2,utc_ms=start,archive_ordinal=k,month=month,file=rng.randrange(5)))
        focal=[g for k,g in enumerate(games) if k%39==0]
        targetmonths={(g['p1'],g['month']) for g in focal}|{(g['p2'],g['month']) for g in focal}
        users={u for u,m in targetmonths};events=[]
        for g in games:
            for u,v in [(g['p1'],g['p2']),(g['p2'],g['p1'])]:
                if u in users:events.append(dict(game_id=g['game_id'],user_id=u,opponent_id=v,utc_ms=g['utc_ms'],
                    archive_ordinal=g['archive_ordinal'],month=g['month'],file=g['file'],has_target_month=(u,g['month']) in targetmonths))
        targets=[dict(game_id=g['game_id'],user_id=u) for g in focal for u in (g['p1'],g['p2'])]
        c=self.conn()
        try:
            c.register('all_events',pa.Table.from_pylist(events));c.register('targets',pa.Table.from_pylist(targets))
            full=c.execute(logic.rematch_logic.side_query('all_events')).to_arrow_table()
            pieces=[]
            for month in months:
                for file in range(5):
                    c.execute(f'CREATE OR REPLACE VIEW selected AS SELECT * FROM all_events WHERE month={lit(month)} AND file={file}')
                    pieces.append(c.execute(logic.compress_sql()).to_arrow_table())
            compressed=pa.concat_tables(pieces)
            self.assertLess(len(compressed),len(events))
            c.register('compressed',compressed)
            actual=c.execute(logic.rematch_logic.side_query('compressed')).to_arrow_table()
            c.register('a',actual);c.register('b',full)
            different=c.execute('SELECT count(*) FROM ((SELECT * FROM a EXCEPT ALL SELECT * FROM b) UNION ALL (SELECT * FROM b EXCEPT ALL SELECT * FROM a))').fetchone()[0]
            self.assertEqual(different,0)
        finally:c.close()

    def test_real_file_projection_sides_resume_and_changed_input_rejection(self):
        t=millis('2026-01-01');root=self.root;targets=root/'targets';targets.mkdir()
        write(targets/'targets_PRIVATE.parquet',[dict(game_id='focal001',p1=1,p2=2,month='2026-01')])
        write(targets/'target_user_months_PRIVATE.parquet',[dict(user_id=u,month='2026-01') for u in (1,2)])
        write(targets/'target_users_PRIVATE.parquet',[dict(user_id=u) for u in (1,2)])
        p=write(root/'chron.parquet',[
            dict(game_id='prior001',white_id=1,black_id=3,utc_ms=t+1000,archive_ordinal=1),
            dict(game_id='prior002',white_id=2,black_id=4,utc_ms=t+2000,archive_ordinal=2),
            dict(game_id='focal001',white_id=1,black_id=2,utc_ms=t+3000,archive_ordinal=3)])
        job=dict(record=dict(path=str(p),month='2026-01',speed='blitz',rows=3,fingerprint=stamp(p)),
            auth=str(self.auth),work=str(root/'work'),code='fixture',threads=2,memory_mb=512,targets=str(targets),
            target_inputs=[snap(p) for p in targets.glob('*.parquet')])
        result=adjacency_stage.file_job(job);second=adjacency_stage.file_job(job)
        self.assertEqual(result['root'],second['root']);self.assertEqual(result['result']['selected_player_events'],4)
        sides=[]
        for b in (1,2):
            paths=list((Path(result['root'])/'events'/f'ub={b}').glob('*.parquet'))
            r=adjacency_stage.side_job(dict(bucket=b,paths=paths,targets=str(targets),inputs=[snap(Path(result['root'])/'_DONE.json')],
                work=str(root/'work'),auth=str(self.auth),code='fixture',memory_mb=512))
            sides.append(pq.read_table(Path(r['root'])/'new_sides_PRIVATE.parquet'))
        c=self.conn()
        try:
            c.register('sides',pa.concat_tables(sides));c.register('f',pa.table({'game_id':['focal001'],'p1':[1],'p2':[2]}))
            rec=c.execute(logic.rematch_logic.census_query()).to_arrow_table().to_pylist()[0]
            self.assertEqual(rec['previous_classification_status'],'not_mutually_adjacent_observed')
        finally:c.close()
        os.utime(p,None)
        with self.assertRaisesRegex(RuntimeError,'changed before'):adjacency_stage.file_job(job)

    def test_target_winner_from_authenticated_loss_arm(self):
        t=millis('2026-02-01')
        opp=write(self.root/'opp.parquet',[dict(game_id='abcd1234',month='2026-02',utc_ms=t,archive_ordinal=1,
            chooser_user_id=1,disconnected_user_id=2,color='white',timeout_chooser_win=False,grant=0)])
        feature=write(self.root/'feature.parquet',[dict(game_id='abcd1234',timeout_chooser_win=False,timeout_chooser_loss=True)])
        root,r=source_stage.prepare_targets({'2026-02':str(opp)},{'2026-02':[str(feature)]},self.root/'work',self.auth,'fixture',2,512,[snap(opp),snap(feature)])
        a=pq.read_table(root/'targets_PRIVATE.parquet').to_pylist()[0]
        self.assertEqual(a['expected_winner'],'black');self.assertIsNone(a['api_created_at_ms'])

    def test_checkpoint_rejects_modified_output(self):
        p=write(self.root/'input.parquet',[dict(x=1)])
        def build(tmp):write(tmp/'output.parquet',[dict(x=2)]);return dict(rows=1)
        root,r=stage(self.root/'stage','key',[snap(p)],build,self.auth)
        stage(root,'key',[snap(p)],lambda t:self.fail('rebuild on resume'),self.auth)
        write(root/'output.parquet',[dict(x=3)])
        with self.assertRaisesRegex(RuntimeError,'checksum|size'):stage(root,'key',[snap(p)],build,self.auth)

    def test_receipt_pins_are_enforced(self):
        root=self.root/'old';root.mkdir();p=write(root/'x.parquet',[dict(x=1)])
        e=receipt(p);e['relative_path']=p.name;del e['path'];e['size_bytes']=e.pop('bytes')
        write_json(root/'_DONE.json',dict(files=[e]));h=sha(root/'_DONE.json')
        r,s=inputs.authenticated_stage(root,self.auth,h);self.assertEqual(len(s),2)
        write_json(root/'_DONE.json',dict(files=[]))
        with self.assertRaisesRegex(RuntimeError,'Pinned'):inputs.authenticated_stage(root,self.auth,h)

    def test_pair_exclusion_strict_cutoff_and_common_support(self):
        # The only kindness is with the focal recipient and must be removed.
        hj=np.repeat(1,13);hi=np.array([2]+list(range(3,15)))
        ht=np.array([10]*11+[100,101]);hy=np.array([1]+[0]*12);hc=np.zeros(13,int)
        r=num.score_month(hj,hi,ht,hy,hc,np.array([1]),np.array([2]),100,np.full((4,4,500),.02))
        self.assertEqual(r['n'][0],10);self.assertEqual(r['pair_removed'][0],1)
        self.assertEqual(r['raw'][0],0);self.assertAlmostEqual(r['adjusted'][0],-.02)

    def test_score_stage_32month_outputs_use_original_function(self):
        t0=millis('2023-09-03');rows=[]
        for k in range(12):rows.append(dict(j=1,i=3+k,t=t0+k,start=t0+k,ord=k,gid=f'h{k:07d}',y=False,arm=True,fair=False,rt=True,cell=0))
        tx=millis('2023-11-04');rows.append(dict(j=1,i=2,t=tx+1000,start=tx,ord=99,gid='query001',y=True,arm=True,fair=True,rt=True,cell=0))
        p=write(self.root/'h.parquet',rows);ref=self.root/'ref.npy';np.save(ref,np.full((2,32,4,4,500),.03))
        result=score_stage.score_job(dict(shard=0,paths=[str(p)],reference=str(ref),inputs=[snap(p),snap(ref)],
            work=str(self.root/'work'),auth=str(self.auth),code='fixture',memory_mb=512))
        path=Path(result['root'])/'month=2023-11/scores_PRIVATE.parquet';r=pq.ParquetFile(path).read().to_pylist()[0]
        self.assertEqual(r['n_7d'],12);self.assertTrue(r['common5_10_7d']);self.assertAlmostEqual(r['adjusted_7d'],-.03)
        self.assertEqual(len(list(Path(result['root']).glob('month=*/scores_PRIVATE.parquet'))),32)
        self.assertEqual(r['n_30d'],12)

    def test_actual_offline_recovery_then_resume(self):
        root=self.root;tr=root/'targets';tr.mkdir();api=root/'api_archive';api.mkdir()
        t=millis('2026-01-04')
        target=write(tr/'targets_PRIVATE.parquet',[dict(game_id='good0001',month='2026-01',utc_ms=t,
            api_created_at_ms=t+233,expected_winner='white'),dict(game_id='miss0002',month='2026-01',utc_ms=t,
            api_created_at_ms=t+233,expected_winner='white')])
        np.save(tr/'target_ids.npy',np.array(['good0001','miss0002'],dtype='S8'))
        raw=api/'records.ndjson.gz'
        with gzip.open(raw,'wt') as f:
            f.write(json.dumps(dict(id='good0001',source='pool',status='timeout',winner='white',createdAt=t+233,players={}))+'\n')
        os.utime(raw,(1000000000,1000000000))
        original_roots=source_stage.roots
        source_stage.roots=lambda *args:[api]
        try:
            dest,r=source_stage.recover(root,root,[],tr,root/'work',self.auth,'fixture',2,2,512)
            result=pq.read_table(dest/'source_by_game_PRIVATE.parquet').to_pylist()
            self.assertEqual({x['game_id']:x['source_status'] for x in result},{'good0001':'recovered','miss0002':'missing'})
            self.assertEqual(r['result']['scan_issues'],0)
            again,r2=source_stage.recover(root,root,[],tr,root/'work',self.auth,'fixture',2,2,512)
            self.assertEqual(again,dest)
        finally:source_stage.roots=original_roots

    def test_membership_and_support_end_to_end_keep_unknown_out(self):
        root=self.root;sr=root/'source';ar=root/'adj';sr.mkdir();ar.mkdir()
        write(sr/'source_by_game_PRIVATE.parquet',[
            dict(game_id=g,month='2026-02',source=s,source_status=st,source_provenance='fixture')
            for g,s,st in [('pool0001','pool','recovered'),('miss0002',None,'missing'),('pair0003','pool','recovered')]])
        write(ar/'new_adjacency_PRIVATE.parquet',[dict(game_id=g,previous_classification_status=st,mutual_previous_same_pair=mp)
            for g,st,mp in [('pool0001','not_mutually_adjacent_observed',False),('miss0002','not_mutually_adjacent_observed',False),
                ('pair0003','mutual_adjacency_candidate_timing_unresolved',True)]])
        write(ar/'old_bridge_membership_PRIVATE.parquet',[dict(game_id='old00001',source='pool',previous_classification_status='not_mutually_adjacent_observed')])
        t=millis('2026-02-02');old_t=millis('2023-11-02')
        opp=write(root/'opps.parquet',[dict(game_id=g,month='2026-02',chooser_user_id=1,disconnected_user_id=2,
            utc_ms=t,anchor_ms=t+1000,archive_ordinal=k,color='white',speed='blitz',rating=1600,opp_rating=1600,
            grant=0,timeout_chooser_win=True,cp=0,ply=32,tournament_like_event=False,tc_base_s=180,tc_inc_s=0)
            for k,g in enumerate(['pool0001','miss0002','pair0003'])])
        oldp=write(root/'old.parquet',[dict(game_id='old00001',month='2023-11',chooser_user_id=1,disconnected_user_id=2,
            utc_ms=old_t,api_last_move_at_ms=old_t+1000,archive_ordinal=1,chooser_color='black',api_speed='blitz',chooser_elo=1600,
            disconnected_elo=1600,engine_eval_cp_disconnected=0,ply_count=32,kind_draw=False,timeout_chooser_win=True,fair_competitive=True,tournament_like_event=False,
            tc_base_s=180,tc_inc_s=0,chooser_pre_rd_v2=45.,disconnected_pre_rd_v2=45.)])
        old=dict(panels=[dict(month='2023-11',path=str(oldp),rows=1)])
        mr,md=membership_stage.build(sr,dict(scan_issues=0),ar,{'2026-02':str(opp)},old,root/'work',self.auth,'fixture',2,512,[snap(opp),snap(oldp)])
        flow=next(x for x in md['result']['flow'] if x['month']=='2026-02')
        self.assertEqual((flow['known_main_rows'],flow['excluded_rows'],flow['unresolved_membership_rows']),(1,1,1))
        hist=[]
        for k in range(12):hist.append(dict(j=1,i=3+k,t=millis('2023-09-02'),start=millis('2023-09-02'),ord=k,gid=f'h{k:07d}',
            y=False,arm=True,fair=False,rt=True,cell=0))
        for k,(g,tt) in enumerate([('old00001',old_t),('pool0001',t),('miss0002',t),('pair0003',t)]):
            hist.append(dict(j=1,i=2,t=tt+1000,start=tt,ord=20+k,gid=g,y=False,arm=True,fair=True,rt=True,cell=0))
        hp=write(root/'hist.parquet',hist);ref=root/'ref.npy';np.save(ref,np.full((2,32,4,4,500),.03))
        sp=score_stage.score_job(dict(shard=0,paths=[str(hp)],reference=str(ref),inputs=[snap(hp),snap(ref)],work=str(root/'work'),
            auth=str(self.auth),code='fixture',memory_mb=512))
        ir,rr=score_stage.summarize([sp],mr,root/'work',self.auth,'fixture',2,512,[snap(mr/'_DONE.json'),snap(Path(sp['root'])/'_DONE.json')])
        out=pq.read_table(ir/'known_main_candidate_scores_PRIVATE.parquet').to_pylist()
        self.assertEqual({r['game_id'] for r in out},{'old00001','pool0001'})
        self.assertTrue(all(r['common5_10_7d'] for r in out))

    def test_census_bridge_passes_exactly_and_rejects_changed_status(self):
        root=self.root;targets=root/'targets';targets.mkdir();sroot=root/'sides';sroot.mkdir()
        focal=[dict(game_id='bridge01',p1=1,p2=2,month='2023-11'),dict(game_id='added001',p1=1,p2=2,month='2026-01')]
        write(targets/'targets_PRIVATE.parquet',focal)
        for label,gid,month in [('bridge','bridge01','2023-11'),('new','added001','2026-01')]:
            t=millis(month+'-02');rows=[]
            for u,v in [(1,2),(2,1)]:
                rows.append(dict(game_id=gid,user_id=u,opponent_id=v,utc_ms=t,archive_ordinal=3,
                    prev_game_id=f'prior00{u}',prev_opponent_id=3+u,prev_start_ms=t-1000,prev2_start_ms=t-2000,
                    next_game_id=f'after00{u}',next_opponent_id=5+u,next_start_ms=t+1000,next2_start_ms=t+2000))
            write(sroot/(label+'_sides_PRIVATE.parquet'),rows)
        write_json(sroot/'_DONE.json',dict(files=[]));side=[dict(root=str(sroot),receipt=receipt(sroot/'_DONE.json'))]
        oldp=write(root/'old_elig.parquet',[dict(game_id='bridge01',source='pool',previous_classification_status='not_mutually_adjacent_observed')])
        old=dict(eligibility=[str(oldp)],snapshots=[snap(oldp)])
        ar,ad=adjacency_stage.census(side,targets,old,root/'work',self.auth,'fixture',2,512,expected_bridge_rows=1)
        self.assertEqual(ad['result']['bridge']['different_rows'],0)
        self.assertEqual(ad['result']['new_rows'],1)
        write(oldp,[dict(game_id='bridge01',source='pool',previous_classification_status='left_boundary_unresolved')])
        old['snapshots']=[snap(oldp)]
        with self.assertRaisesRegex(RuntimeError,'bridge differs'):
            adjacency_stage.census(side,targets,old,root/'work',self.auth,'fixture',2,512,expected_bridge_rows=1)

if __name__=='__main__':unittest.main(verbosity=2)
