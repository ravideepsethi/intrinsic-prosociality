import sys,tempfile,unittest,json
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from cached_common import *
import cached_inputs as ci
import cached_chronology as ch
import cached_histories as hh
import run_cached as run

CONF='synthetic-offline-v1'
T=int(STARTS[6])+10*DAY

def queries(n=1):
    return dict(row_id=np.arange(n,dtype=np.int64)+NEW_ID_BASE,
        game_id=np.array([f'Q{k:07d}' for k in range(n)]),
        month_code=np.full(n,6,np.int64),archive_start_ms=np.full(n,T,np.int64),anchor_ms=np.full(n,T+1000,np.int64),
        recipient_id=np.arange(n,dtype=np.int64)*2+10,opponent_id=np.arange(n,dtype=np.int64)*2+11,
        recipient_rating=np.full(n,1500.),opponent_rating=np.full(n,1520.),tc_base_s=np.full(n,180,np.int64),tc_inc_s=np.zeros(n,np.int64),
        status=np.full(n,'resign'),ordinary_narrow=np.ones(n,bool),recipient_username=np.array([f'user{k*2+10}' for k in range(n)]),
        opponent_username=np.array([f'user{k*2+11}' for k in range(n)]),previous_frame=np.zeros(n,bool),
        pre_games_30d=np.zeros(n,np.int64),eligible_main=np.zeros(n,bool),first_observed_pair=np.zeros(n,bool),expected_n7=np.full(n,6,np.int64))

def put(root,name,table):
    path=root/name;io.table(path,pa.table(table) if isinstance(table,dict) else table);return str(path)

def fake_model(n=5000):
    rng=np.random.default_rng(4022);q=queries(n)
    q['row_id']=np.arange(n,dtype=np.int64)
    q['recipient_id']=rng.integers(1,900,n);q['opponent_id']=rng.integers(1000,1600,n)
    q['recipient_rating']=1400+rng.normal(0,80,n);q['opponent_rating']=q['recipient_rating']+rng.normal(0,100,n)
    q['archive_start_ms']=T+rng.integers(0,35*DAY,n);q['month_code']=np.full(n,6)
    q.update(n_7d=rng.integers(5,50,n),counterparts_7d=rng.integers(3,30,n),expected_7d=rng.uniform(.01,.06,n),adjusted_7d=rng.normal(0,.06,n),
        pre_games_30d=rng.integers(5,400,n),history_complete=np.ones(n,bool),eligible_main=np.ones(n,bool),first_observed_pair=np.ones(n,bool),
        at_risk_90=np.ones(n,bool),ordinary_narrow=np.ones(n,bool),complete90=np.ones(n,bool))
    q['y']=rng.random(n)<.03;q['reached']=q['y']|(rng.random(n)<.7)
    for d in (90,30):
        q[f'fair_{d}']=rng.integers(10,50,n);q[f'kind_{d}']=rng.integers(0,3,n)
        q[f'disconnect_{d}']=rng.integers(5,30,n);q[f'receipt_{d}']=rng.integers(0,3,n);q[f'claim_{d}']=rng.integers(0,3,n)
    return q

class CachedTests(unittest.TestCase):
    def test_five_rows_stop_before_authentication_or_models(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);project=root/'project';project.mkdir();desktop=root/'desktop'
            a=SimpleNamespace(project_root=project,desktop=desktop,workers=2,memory_gb=6,plan=None)
            local=dict(input_receipts=[],metadata='unused',ledgers=[],summary=dict(disposition_counts=dict(LOCAL_POOL_METADATA_READY=2556507)))
            coverage=[dict(cached_pool_rows=2556507,ordinary_rows=5,ending_counts=[dict(month='2024-10',speed='blitz',status='resign',rows=4),dict(month='2024-10',speed='blitz',status='mate',rows=1)])]
            with mock.patch('run_cached.no_network'),mock.patch('run_cached.verify_release'),mock.patch('run_cached.authenticate',return_value=local),mock.patch('run_cached.io.mapped',return_value=coverage),mock.patch('run_cached.inputs_code.research_inputs',side_effect=AssertionError('Research scan must not start')),mock.patch('run_cached.verify_baseline',side_effect=AssertionError('Regression must not start')):
                run.execute(a)
            r=io.load(next(project.rglob('report/summary.json')))
            self.assertEqual(r['status'],'INSUFFICIENT_CACHED_ORDINARY_GAMES')
            self.assertEqual(r['new_eligible_rows_upper_bound'],5);self.assertEqual(r['estimates'],[])
            self.assertEqual(run.coverage_status(0),'NO_NEW_CACHED_ORDINARY_GAMES')
            self.assertEqual(run.coverage_status(1999),'INSUFFICIENT_CACHED_ORDINARY_GAMES')
            self.assertEqual(run.coverage_status(2000),'COVERAGE_COMPLETE_ANALYSIS_PENDING')

    def test_legacy_baseline_without_status_or_api_names(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=fake_model(3)
            for name in ('status','recipient_username','opponent_username'):del base[name]
            base.update(outcome_gid=np.full(3,''),outcome_t=np.full(3,-1,np.int64),outcome_start=np.full(3,-1,np.int64),outcome_opponent=np.full(3,-1,np.int64))
            source=put(root,'source.parquet',base);new=queries(1);new['game_id']=np.array(['N0000000'])
            cols=['game_id','archive_start_ms','anchor_ms','recipient_id','opponent_id','recipient_rating','opponent_rating','recipient_username','opponent_username','tc_base_s','tc_inc_s','status','expected_n7','month_code']
            npth=put(root,'new.parquet',{k:new[k] for k in cols})
            with mock.patch('run_cached.verify_baseline',return_value=(base,dict(estimates=[]))):
                out,r=run.prepare_queries([npth],source,root/'prepared',CONF,.4)
            old=io.read(out/'baseline_queries.parquet')
            for name in ('status','recipient_username','opponent_username'):self.assertEqual(old[name].null_count,3)
            self.assertTrue(all(old['ordinary_narrow'].to_pylist()))
            self.assertNotIn('status',io.read(out/'baseline_original.parquet').column_names)

    def test_missing_api_names_allowed_only_on_frozen_original_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=queries(1);q['previous_frame'][:]=True
            q['recipient_username']=pa.nulls(1,type=pa.string());q['opponent_username']=pa.nulls(1,type=pa.string())
            qp=put(root,'old.parquet',q)
            dp=put(root,'dictionary.parquet',dict(global_id=np.arange(12),username_norm=[f'user{k}' for k in range(12)]))
            ins=dict(dictionary_column='global_id',dictionary_total=12,dictionary=[dict(path=dp)])
            _,r=ci.identity_check(qp,ins,root/'old_ok',CONF,.4,1)
            self.assertEqual(r['frozen_original_role_IDs_without_export_label'],2)
            q['previous_frame'][:]=False;npth=put(root,'new.parquet',q)
            with self.assertRaisesRegex(RuntimeError,'unresolved'):ci.identity_check(npth,ins,root/'new_bad',CONF,.4,1)

    def test_covariance_matches_explicit_shared_account_or_date_pairs(self):
        import comparison_core as cmp
        import followup_stats as frozen
        i=np.array([1,1,2,3,4,8,9]);j=np.array([2,3,1,7,8,9,7]);day=np.array([1,2,1,4,3,2,1])
        score=np.array([[1.,2],[2,1],[-1,3],[.5,-1],[3,2],[-2,4],[1,-3]])
        expected=np.zeros((2,2))
        for a in range(len(i)):
            for b in range(len(i)):
                if day[a]==day[b] or {i[a],j[a]} & {i[b],j[b]}:expected+=np.outer(score[a],score[b])
        np.testing.assert_allclose(frozen.shared_meat(score,cmp.covariance_codes(i,j,day),True),expected)

    def test_absorbed_coefficient_matches_explicit_dummy_ols(self):
        rng=np.random.default_rng(17);n=300
        g1=rng.integers(0,6,n);g2=rng.integers(0,8,n)
        x=rng.normal(size=n);z=.3*x+rng.normal(size=n);y=2*z+x+.1*g1-.2*g2+rng.normal(size=n)
        residual,_=num.partial_out(np.column_stack([x,z,y]),[g1,g2],1)
        actual=residual[:,0]@residual[:,1]/(residual[:,0]@residual[:,0])
        expected=np.linalg.lstsq(np.column_stack([z,x,np.eye(6)[g1],np.eye(8)[g2]]),y,rcond=1e-11)[0][0]
        self.assertAlmostEqual(actual,expected,places=9)

    def test_coverage_counts_endings_and_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);n=4;q=queries(n)
            f=dict(game_id=q['game_id'],utc_ms=q['archive_start_ms'],recipient_id=q['recipient_id'],opponent_id=q['opponent_id'],
                recipient_color=['white']*n,speed_partition=['blitz']*n,previous_frame=[False]*n,
                retrieval_disposition=['LOCAL_POOL_METADATA_READY']*n,n7_author_clean=[6]*n)
            records=[]
            for k,s in enumerate(('timeout','resign','mate','outoftime')):
                records.append(dict(game_id=q['game_id'][k],source='pool',status=s,api_start_ms=T,anchor_ms=T+1000,rated=True,variant='standard',speed='blitz',winner='white',
                    tc_base_s=180,tc_inc_s=0,white_username=f'user{k*2+10}',black_username=f'user{k*2+11}',white_rating=1500.,black_rating=1520.,cached_conflict_or_prior_flag=False))
            fp=put(root,'frame.parquet',f);mp=put(root,'meta.parquet',pa.Table.from_pylist(records))
            job=dict(ledger=fp,metadata=[mp],memory=.3,month=MONTHS[6],output=str(root/'out'),conf=CONF)
            r=ci.coverage_job(job);self.assertEqual(r['ordinary_rows'],2);self.assertEqual(r['cached_pool_rows'],4)
            self.assertEqual(io.read(root/'out/ordinary.parquet')['status'].to_pylist(),['resign','mate'])
            records[1]['cached_conflict_or_prior_flag']=True;put(root,'bad.parquet',pa.Table.from_pylist(records))
            with self.assertRaisesRegex(RuntimeError,'readiness'):ci.coverage_job(dict(job,metadata=[str(root/'bad.parquet')],output=str(root/'badout')))

    def test_chronology_across_files_ties_and_author_activity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=queries(5);qp=put(root,'q.parquet',q)
            cp,info=ch.prepare_chronology(qp,root/'plan',CONF,.3)
            rows=[]
            def add(g,t,w,b):rows.append(dict(game_id=g,utc_ms=t,white_id=w,black_id=b))
            # Every account has a separate older predecessor: nonadjacent, first pair.
            for k in range(5):
                a,b=10+k*2,11+k*2
                add(f'A{k:07d}',T-31*DAY,a,700+k)
                add(f'B{k:07d}',T-2*DAY,b,800+k)
                add(f'Q{k:07d}',T,a,b)
            add('Recent00',T-30*DAY,10,99)  # author 99 must count in factual activity
            add('AtStart0',T,10,500)       # focal-time tie: ambiguous, both focal rows still mapped
            add('Earlier1',T-500*DAY,12,13) # first pair fails, despite no mutual predecessor
            add('Mutual02',T-DAY,14,15)    # mutual previous event
            add('TiePrev1',T-DAY,16,900)
            add('TiePrev2',T-DAY,16,901)   # predecessor tie across two physical files
            paths=[put(root,f'chron{k}.parquet',pa.Table.from_pylist(rows[k::3])) for k in range(3)]
            jobs=[]
            for k,p in enumerate(paths):
                jobs.append(dict(path=p,signature=io.sig(p),people=str(cp/'people.parquet'),pairs=str(cp/'pairs.parquet'),focal=str(cp/'focal.parquet'),
                    latest=T,rows=pq.ParquetFile(p).metadata.num_rows,file_index=k,memory=.3,output=str(root/f'part{k}'),conf=CONF))
            for j in jobs:ch.chronology_job(j)
            out,r=ch.merge_chronology(qp,cp,[Path(j['output']) for j in jobs],root/'features',CONF,.5,2)
            d=arrays(io.read(out/'features.parquet'));idx=np.argsort(d['row_id']);d={k:v[idx] for k,v in d.items()}
            self.assertEqual(d['previous_classification_status'].tolist(),['ambiguous_start_order',rebuild.NONADJ,'mutual_adjacency_candidate_timing_unresolved','ambiguous_start_order',rebuild.NONADJ])
            np.testing.assert_array_equal(d['first_observed_pair'],[True,False,False,True,True])
            np.testing.assert_array_equal(d['pre_games_30d'],[1,0,1,2,0])
            # Identical inputs resume and output tampering is detected.
            again=ch.chronology_job(jobs[0]);self.assertEqual(again['file_index'],0)
            (Path(jobs[0]['output'])/'pairs.parquet').write_bytes(b'bad')
            with self.assertRaisesRegex(RuntimeError,'size|checksum'):ch.chronology_job(jobs[0])

    def test_scores_strict_lag_pair_removal_author_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=queries();qp=put(root,'q.parquet',q);cut=int(STARTS[6])-7*DAY
            # 6 independent clean decisions, one focal-pair history, one author,
            # one at the strict cutoff: clean n=6; old n=7.
            hp=put(root,'h.parquet',dict(j=[11]*9,i=[20,21,22,23,24,25,10,99,26],t=[cut-1]*8+[cut],
                y=[True,True,False,False,False,False,True,True,True],arm=[True]*9,fair=[True]*9,cell=[0]*9))
            ref=root/'ref';ref.mkdir();np.save(ref/'original.npy',np.full((2,24,4,4,500),.25));np.save(ref/'clean.npy',np.full((2,24,4,4,500),.2))
            shard=int(num.user_hash(np.array([11]))[0]%np.uint64(16))
            job=dict(queries=qp,parts=[hp],shard=shard,reference=str(ref),authors=[99,100],conf=CONF,output=str(root/'scores'))
            hh.score_job(job);d=arrays(io.read(root/'scores/scores.parquet'))
            self.assertEqual(d['n_7d'][0],6);self.assertEqual(d['original_n_7d'][0],7)
            self.assertAlmostEqual(d['adjusted_7d'][0],2/6-.2);self.assertAlmostEqual(d['original_adjusted_7d'][0],3/7-.25)

    def test_future_and_history_full_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=queries(2);qp=put(root,'q.parquet',q)
            hp=put(root,'h.parquet',dict(j=[10,10,99,12],i=[20,99,10,40],t=[T-8*DAY]*4,
                y=[True,True,True,False],arm=[True]*4,fair=[True]*4,cell=[0]*4))
            hj=dict(queries=qp,parts=[hp],month=MONTHS[6],authors=[99,100],memory=.3,output=str(root/'hist'),conf=CONF)
            hh.history_month_job(hj)
            rows=[]
            # same opponent, overlapping start, and author choice must be skipped;
            # lastMoveAt exactly 90 days IS included.
            for k,(who,opp,start,tt,y) in enumerate([(10,11,T+2000,T+3000,True),(10,20,T,T+4000,True),(10,99,T+2000,T+5000,True),
                (10,21,T+2000,T+6000,False),(12,22,T+2000,T+1000+90*DAY,True)]):
                rows.append(dict(game_id=f'F{k:07d}',chooser_user_id=who,disconnected_user_id=opp,api_last_move_at_ms=tt,utc_ms=start,archive_ordinal=k,kind_draw=y,fair_competitive=True,tournament_like_event=False))
            fp=put(root,'main.parquet',pa.Table.from_pylist(rows))
            hh.future_month_job(dict(queries=qp,panel=fp,memory=.3,output=str(root/'future'),conf=CONF))
            for s in (10,12):
                oqp=put(root,f'q{s}.parquet',pa.table(q).filter(pa.array(q['recipient_id']%16==s)))
                hh.outcomes_job(dict(queries=oqp,shard=s,authors=[99,100],original_histories=[str(root/'hist'/f'original_{s:02}.parquet')],
                    clean_histories=[str(root/'hist'/f'clean_{s:02}.parquet')],futures=[str(root/'future'/f'{s:02}.parquet')],output=str(root/f'out{s}'),conf=CONF))
            a=arrays(io.read(root/'out10/outcomes.parquet'));b=arrays(io.read(root/'out12/outcomes.parquet'))
            self.assertEqual(a['fair_90'][0],1);self.assertEqual(a['original_fair_90'][0],2)
            self.assertEqual(a['receipt_90'][0],0);self.assertEqual(a['original_receipt_90'][0],1)
            self.assertFalse(a['y'][0]);self.assertTrue(a['original_y'][0]);self.assertEqual(a['outcome_gid'][0],'F0000003')
            self.assertTrue(b['y'][0]);self.assertTrue(b['reached'][0])

    def test_dictionary_ghost_and_missing_id(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=queries();q['recipient_username']=np.array(['ghost']);qp=put(root,'q.parquet',q)
            dp=put(root,'dict.parquet',dict(global_id=np.arange(12),username_norm=[f'user{k}' for k in range(12)]))
            ins=dict(dictionary_column='global_id',dictionary_total=12,dictionary=[dict(path=dp)])
            _,r=ci.identity_check(qp,ins,root/'ok',CONF,.4,1);self.assertEqual(r['API_ghost_labels'],1)
            q['opponent_id']=np.array([20]);bp=put(root,'bad.parquet',q)
            with self.assertRaisesRegex(RuntimeError,'unresolved'):ci.identity_check(bp,ins,root/'bad',CONF,.4,1)

    def test_supported_estimator_and_unsupported_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=fake_model();p=put(root,'fit.parquet',d)
            r=run.model_job(dict(sample=p,label='new_cached',conf=CONF,output=str(root/'model')))
            self.assertEqual(r['rows'],5000)
            fit=io.load(root/'model/result.json');self.assertEqual(len(fit['estimates']),2)
            self.assertTrue(all(r['supported'] for r in fit['estimates']))
            self.assertTrue(all(r['reference_score_SD']==REFERENCE_SD for r in fit['estimates']))
            empty=stats.estimate({k:v[:0] for k,v in d.items()},SPEC)
            self.assertEqual(empty['estimates'][0]['reason'],'FEWER_THAN_2000_ROWS')

    def test_original_model_bridge_blocks_changed_expected_result(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=fake_model();p=put(root,'baseline.parquet',d)
            expected=stats.estimate(d,SPEC)['estimates']
            with mock.patch('cached_common.io.load',return_value=expected):
                out,fit=verify_baseline(p);self.assertEqual(len(out['row_id']),5000)
            bad=[dict(r,coefficient_pp=r['coefficient_pp']+1) for r in expected]
            with mock.patch('cached_common.io.load',return_value=bad),self.assertRaisesRegex(RuntimeError,'numerical bridge'):
                verify_baseline(p)

    def test_assembly_uses_full_cooldown_and_unknown_is_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=queries(4)
            q['previous_frame'][2:]=True;q['row_id'][2:]=[0,1]
            q['eligible_main'][2:]=True;q['first_observed_pair'][2:]=True;q['pre_games_30d'][2:]=3
            # Incomplete follow-up is present deliberately and must remain out.
            q['anchor_ms'][1]=core.PANEL_END-89*DAY
            order=np.argsort(q['row_id']);q={k:v[order] for k,v in q.items()};qp=put(root,'queries.parquet',q)
            n=4;sc={'row_id':q['row_id']};oc={'row_id':q['row_id']}
            for prefix in ('','original_'):
                sc.update({prefix+'n_7d':np.full(n,6),prefix+'counterparts_7d':np.full(n,6),prefix+'expected_7d':np.full(n,.2),prefix+'adjusted_7d':np.full(n,.1)})
                for col in COUNT_COLUMNS:oc[prefix+col]=np.zeros(n,np.int64)
                oc.update({prefix+'history_window_complete':np.ones(n,bool),prefix+'y':np.zeros(n,bool),prefix+'reached':np.zeros(n,bool),
                    prefix+'outcome_gid':np.full(n,''),prefix+'outcome_t':np.full(n,-1,np.int64),prefix+'outcome_start':np.full(n,-1,np.int64),prefix+'outcome_opponent':np.full(n,-1,np.int64)})
            saved={k:v[:2] for k,v in dict(q,**{k:v for k,v in sc.items() if k!='row_id'},**{k:v for k,v in oc.items() if k!='row_id'}).items()}
            saved['at_risk_90']=np.ones(2,bool)
            bp=put(root,'baseline.parquet',saved);sp=put(root,'scores.parquet',sc);op=put(root,'outcomes.parquet',oc)
            xp=put(root,'chron.parquet',dict(row_id=q['row_id'][2:],eligible_main=[True,True],first_observed_pair=[True,True],pre_games_30d=[4,5]))
            # A prior incomplete/early-history selected exposure STILL closes risk.
            stream=put(root,'stream.parquet',dict(recipient_id=[10],archive_start_ms=[T-12*DAY],anchor_ms=[T-10*DAY]))
            out,r=run.combine(qp,bp,[sp],[op],xp,stream,[99,100],root/'assembled',CONF,.4)
            self.assertEqual(r['sample_accounting']['new_cached']['rows'],0)
            self.assertEqual(r['sample_accounting']['old_author_clean']['rows'],2)
            features=arrays(io.read(out/'features.parquet'))
            self.assertFalse(features['analysis_eligible'][features['recipient_id']==12][0])
            self.assertFalse(features['complete90'][features['recipient_id']==12][0])
            self.assertFalse(features['at_risk_90'][features['recipient_id']==10][0])

    def test_prepared_query_shards_and_aggregate_export(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=fake_model(3)
            base.update(outcome_gid=np.full(3,''),outcome_t=np.full(3,-1,np.int64),outcome_start=np.full(3,-1,np.int64),outcome_opponent=np.full(3,-1,np.int64))
            source=put(root,'source.parquet',base)
            new=queries(2);new['game_id']=np.array(['N0000000','N0000001']);new['anchor_ms'][1]=core.PANEL_END-90*DAY # exact end excluded
            cols=['game_id','archive_start_ms','anchor_ms','recipient_id','opponent_id','recipient_rating','opponent_rating','recipient_username','opponent_username','tc_base_s','tc_inc_s','status','expected_n7','month_code']
            npth=put(root,'new.parquet',{k:new[k] for k in cols})
            with mock.patch('run_cached.verify_baseline',return_value=(base,dict(estimates=[]))):
                out,r=run.prepare_queries([npth],source,root/'prepared',CONF,.4)
            self.assertEqual(r['new_complete90_queries'],1);self.assertEqual(r['new_incomplete90_excluded'],1)
            self.assertEqual(sum(pq.ParquetFile(out/f'score_{s:02}.parquet').metadata.num_rows for s in range(16)),4)
            self.assertEqual(sum(pq.ParquetFile(out/f'outcome_{s:02}.parquet').metadata.num_rows for s in range(16)),4)
            desktop=root/'desktop';desktop.mkdir()
            r=run.export(root,desktop,CONF,[dict(cached_pool_rows=3,ordinary_rows=2,ending_counts=[dict(month='2024-05',status='resign',speed='blitz',rows=2)])],'TEST_ONLY',run.time.monotonic())
            self.assertFalse(r['abstract_gate_cleared']);self.assertEqual(r['network_requests'],0)
            import zipfile
            z=next(desktop.glob('*.zip'))
            with zipfile.ZipFile(z) as f:
                names=f.namelist();self.assertIn('summary.json',names);self.assertIn('REPORT_MANIFEST.json',names)
                text=f.read('READ_RESULTS.txt').decode();self.assertNotIn('user10',text)

    def test_full_pipeline_with_spawned_workers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=queries(4);old={k:v[2:].copy() for k,v in q.items()};old['row_id']=np.arange(2)
            old.update(eligible_main=np.ones(2,bool),first_observed_pair=np.ones(2,bool),history_complete=np.ones(2,bool),
                at_risk_90=np.ones(2,bool),ordinary_narrow=np.ones(2,bool),complete90=np.ones(2,bool),pre_games_30d=np.ones(2,np.int64),
                n_7d=np.full(2,7),counterparts_7d=np.full(2,7),expected_7d=np.full(2,.25),adjusted_7d=np.full(2,3/7-.25),
                y=np.ones(2,bool),reached=np.ones(2,bool),outcome_gid=np.array(['FAuth000','F0000003']),
                outcome_t=np.array([T+DAY+1,T+2*DAY+2]),outcome_start=np.array([T+DAY,T+2*DAY]),outcome_opponent=np.array([99,501]))
            for col in COUNT_COLUMNS:old[col]=np.zeros(2,np.int64)
            baseline=put(root,'baseline.parquet',old)
            cols=['game_id','archive_start_ms','anchor_ms','recipient_id','opponent_id','recipient_rating','opponent_rating','recipient_username','opponent_username','tc_base_s','tc_inc_s','status','expected_n7','month_code']
            newpath=put(root,'new.parquet',{k:q[k][:2] for k in cols})
            with mock.patch('run_cached.verify_baseline',return_value=(old,stats.estimate(old,SPEC))):
                prepared,_=run.prepare_queries([newpath],baseline,root/'prepared',CONF,.4)
            qp=str(prepared/'queries.parquet');cut=int(STARTS[6])-7*DAY
            records=[]
            for opp in q['opponent_id']:
                for k in range(7):records.append(dict(j=int(opp),i=200+k if k<6 else 99,t=cut-1,y=k in (0,1,6),arm=True,fair=True,cell=0))
            ht=pa.Table.from_pylist(records);hp=put(root,'history.parquet',ht)
            ref=root/'ref';ref.mkdir();np.save(ref/'original.npy',np.full((2,24,4,4,500),.25));np.save(ref/'clean.npy',np.full((2,24,4,4,500),.2))
            sjobs=[]
            hsh=num.user_hash(io.arr(ht,'j'))%np.uint64(16)
            for s in range(16):
                part=put(root,f'history{s}.parquet',ht.filter(pa.array(hsh==s)))
                sjobs.append(dict(queries=str(prepared/f'score_{s:02}.parquet'),parts=[part],shard=s,reference=str(ref),authors=[99,100],conf=CONF,output=str(root/'scores'/str(s))))
            io.mapped(hh.score_job,sjobs,2,'Synthetic score workers')
            hh.history_month_job(dict(queries=qp,parts=[hp],month=MONTHS[6],authors=[99,100],memory=.3,conf=CONF,output=str(root/'hist')))
            futures=[dict(game_id=f'F{k:07d}',chooser_user_id=int(p),disconnected_user_id=501,utc_ms=T+2*DAY,api_last_move_at_ms=T+2*DAY+2,archive_ordinal=k,kind_draw=k in (0,3),fair_competitive=True,tournament_like_event=False) for k,p in enumerate(q['recipient_id'])]
            futures.append(dict(game_id='FAuth000',chooser_user_id=14,disconnected_user_id=99,utc_ms=T+DAY,api_last_move_at_ms=T+DAY+1,archive_ordinal=9,kind_draw=True,fair_competitive=True,tournament_like_event=False))
            fp=put(root,'main.parquet',pa.Table.from_pylist(futures))
            hh.future_month_job(dict(queries=qp,panel=fp,memory=.3,conf=CONF,output=str(root/'future')))
            ojobs=[]
            for s in range(16):ojobs.append(dict(queries=str(prepared/f'outcome_{s:02}.parquet'),shard=s,authors=[99,100],
                original_histories=[str(root/'hist'/f'original_{s:02}.parquet')],clean_histories=[str(root/'hist'/f'clean_{s:02}.parquet')],
                futures=[str(root/'future'/f'{s:02}.parquet')],output=str(root/'outcomes'/str(s)),conf=CONF))
            io.mapped(hh.outcomes_job,ojobs,2,'Synthetic outcome workers')
            cp,info=ch.prepare_chronology(qp,root/'chronplan',CONF,.3)
            erows=[]
            for k in range(2):
                a,b=int(q['recipient_id'][k]),int(q['opponent_id'][k])
                erows.extend([dict(game_id=f'A{k:07d}',utc_ms=T-DAY,white_id=a,black_id=99),dict(game_id=f'B{k:07d}',utc_ms=T-2*DAY,white_id=b,black_id=800),dict(game_id=q['game_id'][k],utc_ms=T,white_id=a,black_id=b)])
            ep=put(root,'chron.parquet',pa.Table.from_pylist(erows));cj=dict(path=ep,signature=io.sig(ep),people=str(cp/'people.parquet'),pairs=str(cp/'pairs.parquet'),focal=str(cp/'focal.parquet'),latest=T,rows=len(erows),file_index=0,memory=.3,output=str(root/'chronpart'),conf=CONF)
            ch.chronology_job(cj);co,_=ch.merge_chronology(qp,cp,[root/'chronpart'],root/'chronology',CONF,.4,2)
            stream=put(root,'stream.parquet',dict(recipient_id=np.array([],np.int64),archive_start_ms=np.array([],np.int64),anchor_ms=np.array([],np.int64)))
            assembled,r=run.combine(qp,prepared/'baseline_original.parquet',[str(Path(j['output'])/'scores.parquet') for j in sjobs],
                [str(Path(j['output'])/'outcomes.parquet') for j in ojobs],co/'features.parquet',stream,[99,100],root/'assembled',CONF,.5)
            self.assertEqual(r['original_features_reproduced'],2)
            self.assertEqual(r['sample_accounting']['new_cached']['rows'],2)
            clean=arrays(io.read(assembled/'old_author_clean.parquet'))
            self.assertEqual(clean['y'].tolist(),[False,True]);self.assertEqual(clean['n_7d'].tolist(),[6,6])
            for label in ('new_cached','old_author_clean','combined_cached'):
                run.model_job(dict(sample=str(assembled/(label+'.parquet')),label=label,conf=CONF,output=str(root/'models'/label)))
            self.assertEqual(io.load(root/'models/combined_cached/result.json')['estimates'][0]['reason'],'FEWER_THAN_2000_ROWS')

    def test_network_disabled_and_parallel_workers(self):
        # Spawned subprocess verifies denial without monkeypatching this test process.
        import subprocess
        code="import sys;sys.path.insert(0,'code');from cached_common import no_network;no_network();import socket\ntry:socket.create_connection(('example.com',443))\nexcept RuntimeError:print('BLOCKED')\nelse:raise AssertionError('network allowed')"
        r=subprocess.run([sys.executable,'-c',code],cwd=PACKAGE,capture_output=True,text=True,check=True)
        self.assertIn('BLOCKED',r.stdout)
        with tempfile.TemporaryDirectory() as td:
            script=Path(td)/'spawn_check.py'
            script.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path.cwd()/'code'))\nfrom cached_common import *\nif __name__=='__main__':\n    no_network()\n    result=io.mapped(io.checked,[str(PACKAGE/'README.txt'),str(PACKAGE/'README.txt')],2,'Guarded spawn')\n    assert len(result)==2\n    print('SPAWN_OK')\n")
            r=subprocess.run([sys.executable,str(script)],cwd=PACKAGE,capture_output=True,text=True,check=True)
            self.assertIn('SPAWN_OK',r.stdout)

if __name__=='__main__':unittest.main()
