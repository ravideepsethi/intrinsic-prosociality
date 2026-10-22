#!/usr/bin/env python3
"""Synthetic-only tests. No Lichess request and no private project access."""
import os
for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS']:os.environ[k]='1'
import contextlib, io, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
import pyarrow as pa
from common import *
import estimate, prepare, tenure, trajectory, network

class Tests(unittest.TestCase):
    def test_full_preparation_and_resume(self):
        # Exercise the actual SQL and Parquet preparation path that v1.0.0 skipped.
        # Only authentication's input file list/counts are substituted; production
        # authenticity checks remain unchanged and are separately tested below.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';(run/'report').mkdir(parents=True)
            months=[f'{2023+(10+i)//12}-{(10+i)%12+1:02d}' for i in range(24)]
            monthly=[];total_grants=0
            for mi,month in enumerate(months):
                rows=[]
                for chooser in range(3):
                    for j in range(2):
                        y=int(chooser==0 and j==1);total_grants+=y
                        row=dict(game_id=f'{mi:04d}{chooser:02d}{j:02d}',chooser_user_id=chooser,
                          disconnected_user_id=100+j,chooser_username_norm='u'+str(chooser),
                          disconnected_username_norm='r'+str(j),outcome_kind_draw=y,
                          engine_eval_cp_disconnected=0 if j else -400,ply_count=8+2*j,
                          month=month,api_speed='blitz',time_control='180+0',chooser_elo=1500,
                          disconnected_elo=1400,chooser_draw_payoff_v2=-2.0,chooser_win_premium_v2=5.0,
                          chooser_pre_rd_v2=40.0,disconnected_pre_rd_v2=50.0,
                          chooser_clock_last_obs_s=30.0,disconnected_clock_last_obs_s=20.0,
                          api_created_at_ms=1698796800000+mi*30*DAY+j*60000,
                          api_last_move_at_ms=1698796800000+mi*30*DAY+j*60000+30000,
                          fen_after_last_move=trajectory.chess.STARTING_FEN,
                          disconnected_color='white',chooser_color='black',api_winner=None if y else 'black',
                          api_variant='standard',api_status='timeout',api_rated=True,
                          sf100k_stockfish_sha256=trajectory.ENGINE_SHA,engine_eval_is_mate=False)
                        rows.append(row)
                path=root/f'{month}.parquet';pq.write_table(pa.Table.from_pylist(rows),path)
                monthly.append(dict(month=month,path=path))
            auth=dict(month_records=monthly,authority=dict(choosers=3,rows=144,kind_draws=total_grants))
            args=SimpleNamespace(sample_root=None,threads=1,seed=2026092301,tenure_accounts=2,
              responsibility_accounts=1,fetch_profiles=False,fetch_games=False)
            created_times=None
            for attempt in range(2):
                db=connect(run,1,'1GB')
                try:
                    with patch.object(prepare.authority,'authenticate_sample',return_value=auth), \
                         patch.object(prepare.authority,'compact_sample_lineage',return_value={'synthetic':True}), \
                         contextlib.redirect_stdout(io.StringIO()):
                        prepare.prepare(db,root,run,args,'synthetic-preparation')
                    self.assertEqual(db.execute('SELECT count(*),sum(n),max(username_count) FROM accounts').fetchone(),(3,144,1))
                    self.assertEqual(db.execute('SELECT count(*),count(DISTINCT chooser) FROM panel').fetchone(),(96,2))
                    targets=pq.read_table(run/'PRIVATE/trajectory_targets.parquet')
                    self.assertEqual(targets.num_rows,48)
                    files=list((run/'PRIVATE').rglob('*.parquet'))
                    times={str(p.relative_to(run)):p.stat().st_mtime_ns for p in files}
                    if attempt==0:created_times=times
                    else:self.assertEqual(created_times,times)
                finally:db.close()

    def test_cluster_estimator_matches_explicit_dummies(self):
        rng=np.random.default_rng(341);g=np.repeat(np.arange(30),12);n=len(g)
        z=rng.integers(0,3,n);x=rng.normal(size=n);t=rng.integers(0,2,n);y=rng.binomial(1,.15+.16*t)
        d=dict(y=y,chooser=g,t=t,z=z,x=x)
        r=estimate.fit(d,['t'],['z'],['x'],'chooser','chooser')
        X=np.column_stack([t,x,z==1,z==2,np.eye(30)[g]])
        beta=np.linalg.lstsq(X,y,rcond=None)[0];u=y-X@beta;B=np.linalg.inv(X.T@X)
        s=np.array([X[g==i].T@u[g==i] for i in range(30)])
        V=B@(s.T@s)@B*30/29*(n-1)/(n-np.linalg.matrix_rank(X))
        self.assertAlmostEqual(r['estimates']['t']['coefficient_pp'],100*beta[0],places=8)
        self.assertAlmostEqual(r['estimates']['t']['se_pp'],100*np.sqrt(V[0,0]),places=8)
        # A target constant within chooser must remain unsupported, not return a pseudoinverse estimate.
        d['t']=g%2;r=estimate.fit(d,['t'],[],[],'chooser','chooser')
        self.assertTrue(r['status']=='NO_WITHIN_VARIATION' or r['estimates']['t']['status']=='NOT_IDENTIFIED')

    def test_chess_orientation_and_score_missingness(self):
        sans='e4 e5 Nf3 Nc6 Bb5 a6';b=trajectory.chess.Board()
        for s in sans.split():b.push_san(s)
        t=dict(game_id='abc12345',game_ms=1700000000000,last_ms=1700000001000,api_winner='black',ply_count=6,disconnected_color='white',fen_after_last_move=b.fen())
        o=dict(id=t['game_id'],source='pool',rated=True,status='timeout',variant='standard',createdAt=t['game_ms'],lastMoveAt=t['last_ms'],winner='black',moves=sans)
        g=trajectory.validate(o,t);self.assertEqual([p['ply'] for p in g['positions']],[2,3,4,5,6])
        scores=[dict(ply=p,cp=c,mate=None,status='SCORED') for p,c in zip(range(2,7),[200,100,100,-50,-200])]
        f=trajectory.features(g,scores)
        self.assertEqual((f['loss2'],f['loss4'],f['own_last_loss'],f['own_previous_loss']),(300,400,150,100))
        scores[2]['mate']=3;scores[2]['cp']=None;f=trajectory.features(g,scores)
        self.assertIsNone(f['loss2']);self.assertIsNone(f['own_last_loss']);self.assertEqual(f['loss4'],400)
        with self.assertRaises(RuntimeError):trajectory.validate(dict(o,winner='white'),t)

    def test_checkpoint_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_text('abc');certify(p,'a');self.assertTrue(checkpoint(p,'a'))
            p.write_text('abcd')
            with self.assertRaises(RuntimeError):checkpoint(p,'a')

    def test_network_cache_and_no_network_default(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with patch.object(network,'post',return_value=b'[{"id":"alpha","createdAt":1600000000000}]') as client:
                found,_=network.fetch_batch(p,['alpha'],'profiles',True,'k');self.assertEqual(client.call_count,1)
                same,_=network.fetch_batch(p,['alpha'],'profiles',False,'k');self.assertEqual(found,same)
                none,_=network.fetch_batch(p,['beta'],'profiles',False,'k');self.assertEqual(none,{})

    def test_profile_date_and_patron_semantics(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'report').mkdir();path=root/'snapshot.parquet'
            data=[dict(username_norm='Alice',returned=True,raw_user_json='{"id":"alice","createdAt":1600000000000,"patron":true}',match_cell='a',created_at_ms=1600000000000),
              dict(username_norm='Bob',returned=True,raw_user_json='{"id":"bob","disabled":true}',match_cell='a',created_at_ms=None),
              dict(username_norm='Carl',returned=False,raw_user_json=None,match_cell='b',created_at_ms=None)]
            pq.write_table(pa.Table.from_pylist(data),path);db=connect(root,1,'1GB')
            try:
                with patch.object(prepare,'SNAPSHOT','snapshot.parquet'),patch.object(prepare,'SNAPSHOT_SHA',sha(path)):
                    prepare.cached_profiles(db,root,root)
                self.assertEqual(db.execute('SELECT username,created_ms,patron FROM profiles_cache ORDER BY username').fetchall(),[('alice',1600000000000,1),('bob',None,None),('carl',None,None)])
            finally:db.close()

    def test_sql_analysis_smoke(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);(run/'report').mkdir();(run/'PRIVATE').mkdir();db=connect(run,2,'1GB')
            try:
                fixture(db)
                prepare.attach_age(db)
                with contextlib.redirect_stdout(io.StringIO()):
                    tenure.run_tenure(db,run)
                    trajectory.analyze(db,run,None)
                self.assertTrue((run/'report/TENURE_COMPLETE.json').exists())
                self.assertTrue((run/'report/RESPONSIBILITY_COMPLETE.json').exists())
                # Census novice-share bounds must contain observed young counts and remain ordered.
                r=db.execute(f"SELECT min(lower_share_pct),max(upper_share_pct),min(upper_share_pct-lower_share_pct) FROM read_csv_auto({qs(run/'report/NOVICE_GRANT_SHARE_CENSUS_BOUNDS.csv')})").fetchone()
                self.assertTrue(r[0]>=0 and r[1]<=100 and r[2]>=-1e-10)
            finally:db.close()

    def test_bundled_sample_authority(self):
        a,r=prepare.authority.verify_report_package()
        self.assertEqual(a['rows'],41534331)
        self.assertEqual(a['sample_fingerprint'],'a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30')
        names={x['name'] for x in r['panel_outputs'][0]['schema']}
        self.assertTrue({'api_created_at_ms','chooser_username_norm','api_winner','fen_after_last_move','sf100k_stockfish_sha256'}<=names)

def fixture(db):
    rng=np.random.default_rng(1601);start=1698796800000;rows=[];profiles=[]
    for i in range(180):
        name='u'+str(i);base=[1,15,45,180,800][i%5]
        created=start-base*DAY;profiles.append(dict(username=name,created_ms=None if i%17==0 else created,
          returned=True,disabled=False,patron=int(i%11==0),match_cell='m'+str(i%6),profile_source='august'))
        for j in range(36):
            year=j%2+1;day=(j//2)*2 if year==1 else 366+(j//2)*2
            ms=start+day*DAY;board=float(rng.choice([-400,-200,0,200,500]));ply=int(rng.choice([4,6,8,10,20,40,80,100]));stage=['0_0_4','1_5_6','2_7_8','3_9_10','4_11_20','5_21_40','6_41_80','7_81plus'][[4,6,8,10,20,40,80,100].index(ply)]
            y=int(rng.random()<(.13 if board>=-100 else .04));gap=float(rng.integers(-5,6))
            row=dict(game_id=f'{i:04d}{j:04d}',chooser=i,recipient=1000+j,username=name,y=y,board=board,competitive=int(board>=-100),board_bin=['0_clearly_worse','1_modestly_worse','2_equal','3_better','4_clearly_better'][[-400,-200,0,200,500].index(board)],stage=stage,
              stage_mid=int(10<ply<=40),stage_late=int(ply>40),month='2023-11' if year==1 else '2024-11',speed='blitz' if j%3 else 'rapid',time_control='180+0',ply_count=ply,rating=1500+i,gap100=gap,rating_tier='0_under1600' if i<100 else '1_1600_1999',gap_bin=int(np.floor(gap/2)),
              game_ms=ms,last_ms=ms+10000,yr=year,draw_rank=i+1,engine_eval_is_mate=False)
            for col in tenure.NUMS:row[col]=float(rng.uniform(0,2)) if col not in ['cc_missing','dc_missing'] else 0
            rows.append(row)
    db.register('row_input',pa.Table.from_pylist(rows));db.execute('CREATE TABLE panel AS SELECT * FROM row_input')
    db.register('profile_input',pa.Table.from_pylist(profiles));db.execute('CREATE TABLE profiles_cache AS SELECT * FROM profile_input')
    db.execute('CREATE TABLE profiles_fetch(username VARCHAR,created_ms BIGINT,returned BOOLEAN,queried_at VARCHAR)')
    db.execute('CREATE TABLE accounts AS SELECT chooser,any_value(username) username,count(*) n,sum(y) grants,min(game_ms) first_ms FROM panel GROUP BY chooser')
    db.execute('''CREATE VIEW src AS SELECT chooser chooser_user_id,y outcome_kind_draw,board engine_eval_cp_disconnected,rating chooser_elo,game_ms api_created_at_ms FROM panel''')
    fs=[]
    for row in rows:
        a,b,c=rng.normal(50,160,3)
        fs.append(dict(game_id=row['game_id'],status='VERIFIED',positions=5,full_cp_positions=5,mate_positions=0,
          final_cp=row['board']+3,loss2=float(a),loss4=float(b),own_last_loss=float(c),own_previous_loss=float(b-c),own_two_sum=float(b),own_max_loss=float(max(c,b-c))))
    db.register('feature_input',pa.Table.from_pylist(fs,schema=trajectory.FEATURES));db.execute('CREATE TABLE trajectory AS SELECT * FROM feature_input')

if __name__=='__main__':unittest.main(verbosity=2)
