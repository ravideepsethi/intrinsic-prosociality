import sys,tempfile,unittest,json,hashlib,contextlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from cached_common import *
import checkpoint_inputs as cp
import checkpoint_secondary as sec
import checkpoint_reporting as report
import test_phase_analysis as base
import test_cached as fixture
import performance_histories as fast

class Checkpoint25Tests(unittest.TestCase):
    def test_quarantine_cannot_expand_beyond_reviewed_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);coverage=root/'coverage';quarantine=root/'quarantine'
            io.table(quarantine/'frame_record_PRIVATE.parquet',pa.table(dict(game_id=['reviewed'])))
            empty=pa.table(dict(game_id=pa.array([],pa.string()),disposition=pa.array([],pa.string())))
            for month in ex.MONTHS:
                io.table(coverage/month/'unresolved_PRIVATE.parquet',empty)
                io.table(coverage/month/'pool.parquet',pa.table(dict(game_id=pa.array([],pa.string()))))
            bad=coverage/'2024-04/unresolved_PRIVATE.parquet'
            io.table(bad,pa.table(dict(game_id=['reviewed'],disposition=['CACHE_CONFLICT_OR_PRIOR_FLAG'])))
            with mock.patch.object(cp.recovery,'reuse_v101_quarantine',return_value=True):
                cp.check_quarantine(None,None,dict(phase10={}),coverage,quarantine,'test',.5)
                io.table(bad,pa.table(dict(game_id=['reviewed','new_flag'],disposition=['CACHE_CONFLICT_OR_PRIOR_FLAG']*2)))
                with self.assertRaisesRegex(RuntimeError,'Additional or changed'):
                    cp.check_quarantine(None,None,dict(phase10={}),coverage,quarantine,'test',.5)
                io.table(bad,pa.table(dict(game_id=['different_id'],disposition=['CACHE_CONFLICT_OR_PRIOR_FLAG'])))
                with self.assertRaisesRegex(RuntimeError,'Additional or changed'):
                    cp.check_quarantine(None,None,dict(phase10={}),coverage,quarantine,'test',.5)

    def test_completed_publication_only_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);phase=root/'phase';result=phase/'phase_results/25';conf='synthetic-phase';up=dict(ledgers=['a','b'],manifest=dict(original_cached_metadata='cached'))
            row=dict(through_percent=25,cumulative_targets=5,incremental_targets=3,additional_frame_rows=9)
            io.js(phase/'plan/summary.json',dict(phases=[row]));io.table(phase/'plan/targets_25.parquet',pa.table(dict(game_id=['g1','g2','g3'])))
            target=phase/'plan/targets_25.parquet'
            io.stage(phase/'download/25/finished',io.cfgsha([conf,25,io.sha(target)]),lambda tmp:dict(requested=3))
            io.stage(result/'merged',io.cfgsha([conf,25]),lambda tmp:io.table(tmp/'metadata.parquet',pa.table(dict(game_id=['g1']))))
            manifest=dict(through_percent=25,fixed_denominator=up['ledgers'],upstream_manifest=up['manifest'],additional_frame_selection_sql=selection_sql(25),merged_candidate_metadata=str(result/'merged/metadata.parquet'),original_cached_metadata='cached',full_historical_and_prospective_anchor_stream_required=True,all_frame_rows_preserved=True,final_sample_and_rules_unchanged=True)
            io.js(result/'ANALYSIS_INPUTS_PRIVATE.json',manifest)
            io.js(result/'report/summary.json',dict(row,requested=5,all_requested_ids_accounted=True))
            q=result/'report/summary.json';io.js(result/'report/REPORT_MANIFEST.json',[dict(path=q.name,sha256=io.sha(q),bytes=q.stat().st_size)])
            auth=io.load(PACKAGE/'evidence/checkpoint_authority.json');controller=io.cfgsha(dict(version='1.0.0',package_sha256=auth['continuous_package_sha'],inherited_config=conf,checkpoints=[25,50,75,100]))
            marker=phase/'continuous_v100'/controller[:12]/'REPORT_025_DONE.json'
            old=dict(root=str(phase),config_sha256=conf)
            with mock.patch.object(cp.old,'authenticate_phase',return_value=old):
                with self.assertRaisesRegex(RuntimeError,'publication marker'):cp.authenticate_checkpoint(SimpleNamespace(),up)
                io.js(marker,dict(controller_conf=controller,inputs_sha256=io.sha(result/'ANALYSIS_INPUTS_PRIVATE.json'),manifest_sha256=io.sha(result/'report/REPORT_MANIFEST.json')))
                got=cp.authenticate_checkpoint(SimpleNamespace(),up);self.assertEqual(got['summary']['additional_frame_rows'],9)
                io.js(phase/'LATEST_ANALYSIS_PRIVATE.json',dict(through_percent=100,manifest='must-not-read'))
                self.assertEqual(cp.authenticate_checkpoint(SimpleNamespace(),up),got)
                with (result/'merged/metadata.parquet').open('ab') as f:f.write(b'tampered')
                with self.assertRaises(RuntimeError):cp.authenticate_checkpoint(SimpleNamespace(),up)

    def test_25_coverage_exact_hash_boundary_and_no_ending_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ranks=[bytes(32),threshold(10),((1<<256)*25//100-1).to_bytes(32,'big'),threshold(25),bytes([255])*32]
            rows=[];meta=[]
            for k,rank in enumerate(ranks):
                rows.append(dict(game_id=f'G{k:07}',utc_ms=fixture.T,speed_partition='blitz',retrieval_rank=rank,previous_frame=False,local_eligibility='POTENTIALLY_ELIGIBLE',recipient_color='white',recipient_id=k,opponent_id=100+k,n7_author_clean=6))
                meta.append(dict(game_id=f'G{k:07}',source='pool',status=['mate','resign','timeout','draw','stalemate'][k],api_start_ms=fixture.T,anchor_ms=fixture.T+1,rated=True,variant='standard',speed='blitz',tc_base_s=180,tc_inc_s=0,white_username='w',black_username='b',white_rating=1500.,black_rating=1500.,winner='white',cached_conflict_or_prior_flag=False))
            ledger=fixture.put(root,'ledger.parquet',pa.Table.from_pylist(rows));metadata=fixture.put(root,'metadata.parquet',pa.Table.from_pylist(meta))
            result=cp.coverage_job(dict(ledger=ledger,metadata=[metadata],month=MONTHS[6],memory=.5,conf='test',output=str(root/'coverage')))
            self.assertEqual(result['selected_frame_rows'],3);self.assertEqual(result['ordinary_rows'],2)
            self.assertEqual(io.read(root/'coverage/pool.parquet')['status'].to_pylist(),['mate','resign','timeout'])
            self.assertEqual(pq.ParquetFile(root/'coverage/membership_PRIVATE.parquet').metadata.num_rows,3)

    def test_nested_split_rebinds_ids_and_checks_every_feature(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);assembled=root/'assembled';prior=root/'prior';ranks=[bytes(32),threshold(10),((1<<256)*25//100-1).to_bytes(32,'big')]
            m=fixture.put(root,'membership.parquet',dict(game_id=['a','b','c'],retrieval_rank=ranks))
            for f in ('ordinary','entry'):
                d=dict(row_id=np.array([100,200,300]),game_id=['a','b','c'],y=[True,False,True],adjusted_7d=[.01,.02,.03])
                io.table(assembled/(f+'_new_phase25.parquet'),pa.table(d));io.table(assembled/(f+'_pooled.parquet'),pa.table(d))
                old=pa.table(dict(row_id=[1],game_id=['old'],y=[False],adjusted_7d=[.04]))
                io.table(assembled/(f+'_old_author_clean.parquet'),old);io.table(prior/'assembled'/(f+'_old_author_clean.parquet'),old)
                io.table(prior/'assembled'/(f+'_new_phase10.parquet'),pa.table(dict(row_id=[8],game_id=['a'],y=[True],adjusted_7d=[.01])))
            out,info=cp.split_samples(assembled,[m],dict(root=str(prior)),root/'split','test',.5)
            self.assertEqual(io.read(out/'ordinary_increment_10_25.parquet')['game_id'].to_pylist(),['b','c'])
            self.assertTrue(io.load(out/'bridge.json')['checks'][0]['game_identity_and_all_features_reproduced'])
            self.assertEqual(cp.split_samples(assembled,[m],dict(root=str(prior)),root/'split','test',.5)[1],info)
            io.table(prior/'assembled/ordinary_new_phase10.parquet',pa.table(dict(row_id=[8],game_id=['a'],y=[False],adjusted_7d=[.01])))
            with self.assertRaisesRegex(RuntimeError,'features changed'):cp.split_samples(assembled,[m],dict(root=str(prior)),root/'bad','test',.5)

    def test_competitive_history_matches_original_author_clean_oracle(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rng=np.random.default_rng(7);n=700;cut=STARTS[6]-7*DAY
            cps=np.resize([-301,-300,-299,-101,-100,-99,0,100,101,300],n)
            h=dict(j=rng.integers(1,8,n),i=rng.integers(20,40,n),cell=num.state_cells(cps,np.full(n,20),np.ones(n,int),np.zeros(n)),t=cut+np.resize([-DAY,-1,0,1],n),y=rng.random(n)<.1,arm=np.ones(n,bool))
            hp=fixture.put(root,'h.parquet',h);ij=dict(parts=[hp],memory=.5,conf='index',output=str(root/'index'))
            fast.score_index_job(ij);idx=fast.ScoreIndex(root/'index');ids=[7,39];qj=np.arange(1,7);qi=np.arange(20,26)
            model=rng.uniform(.01,.05,(4,4,500));ref=root/'reference';ref.mkdir();np.save(ref/'clean.npy',np.stack([np.stack([model]*24)]*2))
            sc=idx.score(qj,qi,6,model,ids);q=dict(row_id=np.arange(6),game_id=[f'G{k:07}' for k in range(6)],recipient_id=qi,opponent_id=qj,archive_start_ms=np.full(6,STARTS[6]),anchor_ms=np.full(6,STARTS[6]+1),month_code=np.full(6,6),previous_frame=np.zeros(6,bool),**sc)
            qp=fixture.put(root,'q.parquet',q);definition=dict(synthetic=True)
            j=cache_job=dict(queries=qp,index=str(root/'index'),index_job=ij,reference=str(ref),authors=ids,memory=.5,conf='test',output=str(root/'scores'))
            j=sec.cache.attach(j,root/'cache','comp',definition,0);sec.score_job(j)
            got=arrays(io.read(root/'scores/scores.parquet'));keep=(cps>=-100)&~authors.author_mask(h['j'],h['i'],ids)
            want=num.score_month(h['j'][keep],h['i'][keep],h['t'][keep],h['y'][keep],h['cell'][keep],qj,qi,cut,model)
            for k,v in [('n_7d','n'),('adjusted_7d','adjusted'),('expected_7d','expected'),('counterparts_7d','counterparts')]:np.testing.assert_allclose(got['comp_'+k],want[v],equal_nan=True,atol=1e-12)
            with mock.patch.object(fast.ScoreIndex,'score',side_effect=AssertionError('must reuse')):sec.score_job(j)

    def test_secondary_X0_matches_frozen_OLS_and_XC_common_controls(self):
        d=base.entry_model(4000);rng=np.random.default_rng(3)
        d.update(comp_adjusted_7d=d['adjusted_7d']+rng.normal(0,.03,4000),comp_n_7d=np.full(4000,8),comp_expected_7d=rng.uniform(.01,.05,4000),comp_counterparts_7d=np.full(4000,7))
        got=sec.estimate(d,'X0','test','all_supported');want=stats.estimate(d,sec.SPECS['ordinary'])['estimates']
        for r in want:
            g=next(x for x in got if x['instrument']=='pooled' and x['outcome']==r['outcome'])
            self.assertAlmostEqual(g['coefficient_pp'],r['coefficient_pp'],10);self.assertAlmostEqual(g['standard_error_pp'],r['standard_error_pp'],10)
        xc=sec.estimate(d,'XC','test','all_supported')
        self.assertEqual(xc[0]['controls'],xc[-1]['controls']);self.assertEqual(xc[0]['row_set_sha256'],xc[-1]['row_set_sha256'])
        self.assertTrue(all(x['secondary'] for x in xc))

if __name__=='__main__':unittest.main()
