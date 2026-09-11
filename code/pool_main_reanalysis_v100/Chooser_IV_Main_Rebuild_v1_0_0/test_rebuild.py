"""Offline tests exercise sample changes, chronology edges, scoring, and inference."""
import tempfile, unittest
from pathlib import Path
import numpy as np
import pyarrow as pa
import duckdb
import local_io as io
import rebuild_logic as logic
import rematch_logic
import iv_numerics as num
import iv_models as models
import run_rebuild as run
from preliminary_core import DAY,PANEL_END

class RebuildTests(unittest.TestCase):
    def test_first_exposure_rank_before_arm(self):
        c=duckdb.connect()
        rows=[]
        for gid,t,arm,fair in [('first001',10,False,True),('second01',20,True,True),('notfair1',5,True,False)]:
            rows.append(dict(game_id=gid,utc_ms=t,archive_ordinal=t,month='2024-01',chooser_user_id=9,
              disconnected_user_id=1,api_last_move_at_ms=t+1,kind_draw=False,timeout_chooser_win=arm,
              api_speed='blitz',tc_base_s=180,tc_inc_s=2,chooser_elo=1500,disconnected_elo=1500,
              chooser_pre_rd_v2=50.,disconnected_pre_rd_v2=50.,engine_eval_cp_disconnected=0,
              ply_count=20,chooser_clock_last_obs_s=10.,disconnected_clock_last_obs_s=10.,fair_competitive=fair,tournament_like_event=False))
        c.register('panel',pa.Table.from_pylist(rows));r=c.execute(logic.exposure_sql('panel')).fetch_arrow_table();c.close()
        self.assertEqual(r['game_id'].to_pylist(),['first001']);self.assertFalse(r['arm_eligible'][0].as_py())

    def test_new_main_can_choose_later_exposure(self):
        # A removed old first exposure must not survive merely because it was in the old cohort.
        source=Path(run.PKG/'run_rebuild.py').read_text()
        self.assertNotIn('recipient_with_chronology_private.parquet',source)
        c=duckdb.connect();c.execute('CREATE TABLE x(i INT,t INT,eligible BOOLEAN)');c.execute('INSERT INTO x VALUES (1,1,false),(1,2,true),(1,3,true)')
        self.assertEqual(c.execute('SELECT min(t) FROM x WHERE eligible GROUP BY i').fetchone()[0],2);c.close()

    def test_full_history_volume_pair_and_ties(self):
        start=100*DAY;ids=np.array([1]);keys=logic.pair_keys(np.array([1]),np.array([2]))
        pre=np.zeros(1,np.int64);mins=np.full(1,2**63-1,np.int64)
        times=np.array([start-30*DAY,start-30*DAY-1,start-1,start,start+1])
        logic.chronology_accumulate(times,np.ones(5,dtype=np.int64),np.array([3,2,4,2,2]),ids,np.array([start]),keys,pre,mins)
        self.assertEqual(pre[0],2);self.assertEqual(mins[0],start-30*DAY-1)

    def check_adjacency(self,events,queries,split):
        c=duckdb.connect()
        schema=pa.schema([('game_id',pa.string()),('utc_ms',pa.int64()),('white_id',pa.int64()),('black_id',pa.int64()),('archive_ordinal',pa.int64())])
        ev=pa.Table.from_pylist(events,schema=schema);q=pa.Table.from_pylist(queries)
        c.register('allgames',ev);c.register('q',q)
        c.execute('CREATE VIEW sides_q AS SELECT sample_row,0 AS role,recipient_id AS user_id,opponent_id,game_id,archive_start_ms FROM q UNION ALL SELECT sample_row,1,opponent_id,recipient_id,game_id,archive_start_ms FROM q')
        c.execute('CREATE VIEW all_ev AS SELECT game_id,utc_ms,archive_ordinal,white_id AS user_id,black_id AS opponent_id FROM allgames UNION ALL SELECT game_id,utc_ms,archive_ordinal,black_id,white_id FROM allgames')
        c.execute('CREATE VIEW original_targets AS SELECT game_id,user_id FROM sides_q')
        c.execute('CREATE VIEW original_sides AS '+rematch_logic.side_query('all_ev','original_targets'))
        c.execute('CREATE VIEW f AS SELECT game_id,recipient_id AS p1,opponent_id AS p2 FROM q')
        expected={r[0]:r[-2] for r in c.execute(rematch_logic.census_query('f','original_sides')).fetchall()}
        tables=[]
        for idx in split:
            c.register('chunk',ev.take(pa.array(idx,type=pa.int64())))
            tables.append(c.execute(logic.adjacency_candidates_sql('chunk','sides_q')).fetch_arrow_table())
        c.register('parts',pa.concat_tables(tables));actual=c.execute(logic.adjacency_final_sql('parts','q')).fetchall()
        byrow=dict(actual)
        for r in queries:self.assertEqual(byrow[r['sample_row']],expected[r['game_id']])
        c.close();return byrow

    def test_adjacency_matches_original_logic_across_files(self):
        events=[]
        def e(g,t,w,b,o=0):events.append(dict(game_id=g,utc_ms=t,white_id=w,black_id=b,archive_ordinal=o))
        e('prior001',1,1,2);e('focal001',5,1,2) # candidate
        e('prior002',1,3,4);e('prior003',2,5,6);e('focal002',5,3,5) # nonadjacent
        e('focal003',5,7,8) # boundary
        e('prior004',1,9,10);e('tied0001',1,9,11);e('focal004',5,9,10) # tied previous across files
        e('prior005',1,12,13);e('focal005',5,12,13);e('tied0002',5,12,14) # tied focal across files
        queries=[dict(sample_row=k,game_id=f'focal00{k+1}',recipient_id=a,opponent_id=b,archive_start_ms=5)
                 for k,(a,b) in enumerate([(1,2),(3,5),(7,8),(9,10),(12,13)])]
        r=self.check_adjacency(events,queries,[list(range(0,len(events),2)),list(range(1,len(events),2))])
        self.assertEqual(r[0],'mutual_adjacency_candidate_timing_unresolved');self.assertEqual(r[1],logic.NONADJ)
        self.assertEqual(r[2],'left_boundary_unresolved');self.assertEqual(r[3],'ambiguous_start_order');self.assertEqual(r[4],'ambiguous_start_order')

    def test_random_partition_adjacency_matches_original(self):
        rng=np.random.default_rng(37);events=[]
        for k in range(250):
            w,b=rng.choice(25,2,replace=False);events.append(dict(game_id=f'{k:08d}',utc_ms=int(rng.integers(1,80)),white_id=int(w),black_id=int(b),archive_ordinal=k))
        queries=[dict(sample_row=k,game_id=e['game_id'],recipient_id=e['white_id'],opponent_id=e['black_id'],archive_start_ms=e['utc_ms']) for k,e in enumerate(events[::3])]
        order=rng.permutation(len(events));self.check_adjacency(events,queries,[p.tolist() for p in np.array_split(order,7)])

    def test_outcome_skips_removed_same_opponent_and_prestarted(self):
        anchor=1704067200000
        h=dict(j=np.array([1]*5),i=np.array([2,3,4,5,6]),t=anchor+np.array([1,2,3,4,5]),start=anchor+np.array([1,1,-1,2,3]),
          gid=np.array(['00000001','00000002','00000003','00000004','00000005']),ord=np.arange(5),fair=np.ones(5,bool),y=np.array([1,1,1,0,1],bool))
        q=dict(sample_row=np.array([0]),recipient_id=np.array([1]),opponent_id=np.array([2]),anchor_ms=np.array([anchor]),archive_start_ms=np.array([anchor-10]),game_id=np.array(['focal001']))
        out=logic.fresh_outcomes(h,q,np.array([1,0,1,1,1],bool))
        self.assertEqual(out['outcome_gid'][0],'00000004');self.assertTrue(out['reached'][0]);self.assertFalse(out['y'][0])

    def test_outcome_deadline_and_incomplete_followup(self):
        q=dict(sample_row=np.array([0,1]),recipient_id=np.array([1,2]),opponent_id=np.array([3,4]),anchor_ms=np.array([PANEL_END-90*DAY-1,PANEL_END-90*DAY]),archive_start_ms=np.array([PANEL_END-90*DAY-100]*2),game_id=np.array(['focal001','focal002']))
        h={k:np.array([],dtype='U8' if k=='gid' else np.int64) for k in ['j','i','t','start','ord','gid','y','fair']};h['fair']=np.array([],bool)
        out=logic.fresh_outcomes(h,q,np.array([],bool));self.assertEqual(out['complete90'].tolist(),[True,False])

    def test_pair_exclusion_and_exact_cutoff(self):
        model=np.full((4,4,500),.2)
        r=num.score_month(np.array([1,1,1,1]),np.array([2,3,4,5]),np.array([1,2,3,4]),np.array([1,0,1,1]),np.zeros(4,int),np.array([1]),np.array([2]),3,model)
        self.assertEqual(r['n'][0],1);self.assertEqual(r['pair_removed'][0],1);self.assertEqual(r['raw'][0],0)

    def test_crossfit_excludes_both_participant_folds(self):
        n=np.ones((1,2,4,4,1),np.int64);s=np.zeros_like(n);baseline=num.expanding_reference(n,s)
        s[:,:,0,:,:]=1;s[:,:,:,1,:]=1
        altered=num.expanding_reference(n,s);np.testing.assert_allclose(baseline[:,:,0,1],altered[:,:,0,1])

    def test_checkpoint_resume_and_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'stage';calls=[]
            def producer(p):calls.append(1);io.js(p/'x.json',{'x':1})
            io.stage(root,'abc',producer);io.stage(root,'abc',producer);self.assertEqual(len(calls),1)
            (root/'x.json').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'changed'):io.stage(root,'abc',producer)

    def test_changed_config_not_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'stage';io.stage(root,'a',lambda p:io.js(p/'x.json',{}))
            with self.assertRaisesRegex(RuntimeError,'configuration'):io.stage(root,'b',lambda p:None)

    def test_iv_matches_direct_just_identified_ratio(self):
        rng=np.random.default_rng(91);n=10000;z=rng.normal(size=n);d=.7*z+rng.normal(size=n);y=.3*d+rng.normal(size=n)
        for x in [z,d,y]:x-=x.mean()
        r=num.iv_fit(y,d,z,num.cluster_codes(np.arange(n)//10))
        self.assertAlmostEqual(r['iv_coefficient'],float(z@y/(z@d)),places=12);self.assertFalse(r['AR95_unbounded'])

    def test_zero_stage_weak_iv_interval_unbounded(self):
        rng=np.random.default_rng(8);z=rng.normal(size=1000);d=rng.normal(size=1000);d-=z*(z@d)/(z@z);y=rng.normal(size=1000)
        r=num.iv_fit(y,d,z,num.cluster_codes(np.arange(1000)))
        self.assertTrue(r['AR95_unbounded'])

    def test_model_controls_and_raw_adjusted_equivalence(self):
        rng=np.random.default_rng(98);n=8000;z=rng.normal(0,.05,n);ex=rng.uniform(.02,.1,n)
        received=rng.random(n)<np.clip(.15+2*z,.01,.9);y=rng.random(n)<(.04+.03*received)
        d=dict(received=received,chooser_id=rng.integers(1,301,n),recipient_id=np.arange(n)+10000,
          archive_start_ms=1704067200000+rng.integers(0,120,n)*DAY,
          exposure_recipient_elo=rng.normal(1500,150,n),exposure_chooser_elo=rng.normal(1500,150,n),
          exposure_recipient_rd=rng.uniform(30,80,n),exposure_chooser_rd=rng.uniform(30,80,n),month_code=rng.integers(2,6,n),
          tc_base_s=np.full(n,180),tc_inc_s=np.full(n,2),own_fair_n=rng.integers(0,10,n),own_kind_n=rng.integers(0,2,n),
          prior_disconnects=rng.integers(0,10,n),prior_receipts=rng.integers(0,2,n),pre_games_30d=rng.integers(0,100,n),
          n_7d=np.full(n,50),counterparts_7d=np.full(n,30),adjusted_7d=z,raw_7d=z+ex,expected_7d=ex,
          other_started_after_y=y,other_started_after_reached=rng.random(n)<.4)
        s=dict(name='synthetic',score='adjusted',lag=7,floor=5)
        a,b,j=models.estimate_spec(d,s,balance=True);raw,_,_=models.estimate_spec(d,dict(s,score='raw'))
        self.assertEqual((len(a),len(b),len(j)),(10,28,4))
        for left,right in zip(a,raw):
            if 'coefficient' in left:self.assertAlmostEqual(left['coefficient'],right['coefficient'],places=10)

    def test_chunk_scan_and_adjacency_integration(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);st=1704153600000
            exposure=pa.table({'target_row':[0],'recipient_id':[1],'chooser_id':[2],'archive_start_ms':[st]});io.table(d/'exposure.parquet',exposure)
            sides=pa.table({'sample_row':[5,5],'role':[0,1],'user_id':[1,2],'opponent_id':[2,1],'game_id':['focal001']*2,'archive_start_ms':[st]*2});io.table(d/'sides.parquet',sides)
            events=pa.table({'game_id':['prior001','focal001'],'utc_ms':[st-DAY,st],'white_id':[1,1],'black_id':[3,2]});io.table(d/'events.parquet',events)
            r=dict(path=str(d/'events.parquet'),signature=io.sig(d/'events.parquet'),rows=2,month='2024-01',footer_signature_sha256='synthetic')
            job=dict(input=r,targets=str(d/'exposure.parquet'),sides=str(d/'sides.parquet'),out=str(d/'result'),conf='test',memory=1)
            out=Path(run.chronology_job(job));self.assertEqual(io.read(out/'volume.parquet')['pre_games_30d'].to_pylist(),[1])
            self.assertEqual(io.read(out/'pairs.parquet')['first_pair_start_ms'].to_pylist(),[st]);self.assertEqual(len(io.read(out/'adjacency.parquet')),2)
            self.assertEqual(run.chronology_job(job),str(out))

    def test_fresh_pipeline_parquet_joins_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);st=1705276800000;rows=[]
            for k,(j,i,off,kind) in enumerate([(2,1,0,True),(1,3,20*DAY,False)]):
                rows.append(dict(game_id=f'main000{k}',utc_ms=st+off,archive_ordinal=k,month='2024-01' if k==0 else '2024-02',
                  chooser_user_id=j,disconnected_user_id=i,api_last_move_at_ms=st+off+100,
                  kind_draw=kind,timeout_chooser_win=not kind,api_speed='blitz',tc_base_s=180.,tc_inc_s=2.,chooser_elo=1500.,
                  disconnected_elo=1500.,chooser_pre_rd_v2=50.,disconnected_pre_rd_v2=50.,engine_eval_cp_disconnected=0.,ply_count=20.,
                  chooser_clock_last_obs_s=10.,disconnected_clock_last_obs_s=10.,fair_competitive=True,tournament_like_event=False))
            io.table(d/'main.parquet',pa.Table.from_pylist(rows))
            q=dict(sample_row=[3],game_id=['compare1'],month=['2024-01'],month_code=[2],recipient_id=[1],opponent_id=[9],archive_start_ms=[st-DAY],anchor_ms=[st-DAY+10],
              status=['mate'],active_timeout=[False],passive_outoftime=[False],ordinary_narrow=[True],ordinary_broad=[True],recipient_rating=[1500.],opponent_rating=[1500.],tc_base_s=[180.],tc_inc_s=[2.])
            for lag in [7,30]:
                for name in ['n','counterparts','pair_removed']:q[f'{name}_{lag}d']=[0]
                for name in ['raw','expected','adjusted']:q[f'{name}_{lag}d']=[float('nan')]
            io.table(d/'q.parquet',pa.table(q))
            ev=[dict(game_id='history1',utc_ms=st-2*DAY,white_id=1,black_id=4),dict(game_id='history2',utc_ms=st-2*DAY,white_id=9,black_id=5),
                dict(game_id='compare1',utc_ms=st-DAY,white_id=1,black_id=9)]
            ev += [dict(game_id=r['game_id'],utc_ms=r['utc_ms'],white_id=r['chooser_user_id'],black_id=r['disconnected_user_id']) for r in rows]
            io.table(d/'events.parquet',pa.Table.from_pylist(ev));inp=dict(panels=[str(d/'main.parquet')],qpath=str(d/'q.parquet'))
            root=d/'run';root.mkdir();run.targets(inp,root,'test',1)
            job=dict(input=dict(path=str(d/'events.parquet'),signature=io.sig(d/'events.parquet'),rows=len(ev),month='2024-01',footer_signature_sha256='synthetic'),
              targets=str(root/'targets/first_exposures.parquet'),sides=str(root/'targets/comparison_sides.parquet'),out=str(root/'chron'),conf='test',memory=1)
            ch=run.chronology_job(job);run.cohort_and_adjacency(inp,root,'test',1,[ch])
            self.assertEqual(len(io.read(root/'cohort/cohort.parquet')),2)
            np.savez(d/'delta.npz',n=np.ones((2,25,4,4,500),np.int64),s=np.zeros((2,25,4,4,500),np.int64));inp['deltas']=[str(d/'delta.npz')]
            run.prepare_scores(inp,root,'test',1);h=[]
            for r in rows:h.append(dict(gid=r['game_id'],j=r['chooser_user_id'],i=r['disconnected_user_id'],t=r['api_last_move_at_ms'],start=r['utc_ms'],ord=r['archive_ordinal'],y=r['kind_draw'],arm=True,fair=True,rt=True,cell=0))
            # A removed opportunity used to be the first later choice. It must remain
            # in historical behavior but must not remain the new primary outcome.
            h.append(dict(gid='removed1',j=1,i=8,t=st+DAY+100,start=st+DAY,ord=8,y=True,arm=True,fair=True,rt=True,cell=0))
            ht=pa.Table.from_pylist(h);hs=num.user_hash(io.arr(ht,'j'))%np.uint64(16);dirs=[]
            for s in range(16):
                p=d/f'h{s}.parquet';io.table(p,ht.filter(pa.array(hs==s)))
                job=dict(parts=[str(p)],out=str(root/f'score{s}'),conf='test',outcomes=str(root/'score_inputs'/f'outcomes_{s:02d}.parquet'),
                  scores=str(root/'score_inputs'/f'scores_{s:02d}.parquet'),keys=str(root/'score_inputs/main_keys.parquet'),reference=str(root/'score_inputs/reference.npy'),cohort=str(root/'cohort/cohort.parquet'),memory=1)
                dirs.append(run.score_job(job))
            run.assembled(inp,root,'test',1,dirs)
            iv=io.read(root/'analysis/iv.parquet');self.assertEqual(iv['outcome_gid'][0].as_py(),'main0001');self.assertFalse(iv['other_started_after_y'][0].as_py())
            comp=io.read(root/'analysis/comparison.parquet');self.assertTrue(comp['eligible_main'][0].as_py());self.assertEqual(comp['outcome_gid'][0].as_py(),'main0001')
            self.assertEqual(len(comp),1);run.assembled(inp,root,'test',1,dirs)

if __name__=='__main__':unittest.main(verbosity=2)
