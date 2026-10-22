"""Independent numerical and data-contract tests; no production access."""
from __future__ import annotations

import io
import contextlib
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import numpy as np
import pandas as pd
import duckdb

from common import *
from estimation import fit, absorb, codes, kernel
from build import build_month
from support import next_fair_support
from validation import validate_source_masks, validate_opportunity_rows

class NumericalTests(unittest.TestCase):
    def test_multiway_matches_explicit_dummy_ols_and_cluster_covariance(self):
        rng=np.random.default_rng(70013);n=1700
        f=pd.DataFrame({'chooser':rng.integers(0,47,n),'calendar':rng.integers(0,9,n),
                        'state':rng.integers(0,15,n),'arena':rng.integers(0,2,n).astype(float),
                        'control':rng.normal(size=n)})
        f['kind']=.2-.037*f.arena+.05*f.control+rng.normal(size=47)[f.chooser]*.04+rng.normal(size=9)[f.calendar]*.03+rng.normal(0,.07,n)
        r=fit(f,['arena'],['control'],['chooser','calendar','state'])
        dummies=np.column_stack([pd.get_dummies(f[k],drop_first=True,dtype=float).to_numpy()
                                 for k in ('chooser','calendar','state')])
        x=np.column_stack([np.ones(n),f[['arena','control']].to_numpy(),dummies])
        y=f.kind.to_numpy();b=np.linalg.lstsq(x,y,rcond=None)[0];u=y-x@b
        inv=np.linalg.inv(x.T@x)
        scores=np.array([x[f.chooser==g].T@u[f.chooser==g] for g in sorted(f.chooser.unique())])
        v=47/46*inv@scores.T@scores@inv
        self.assertAlmostEqual(r['coefficients'][0]['estimate_pp']/100,b[1],places=10)
        np.testing.assert_allclose(r['covariance_probability_units'],v[1:3,1:3],rtol=1e-7,atol=1e-12)
        self.assertLess(r['projection']['orthogonality'],1e-9)

    def test_one_way_agrees_with_recovered_kernel(self):
        rng=np.random.default_rng(43);matrix=rng.normal(size=(1000,4));c=np.arange(1000)%53
        actual,_=absorb(matrix,[(c,53)])
        expected=kernel().demean_once(matrix,c,53)
        np.testing.assert_allclose(actual,expected,atol=1e-14)

    def test_unidentified_target_fails(self):
        f=pd.DataFrame({'chooser':np.repeat(np.arange(20),10),'kind':np.tile([0.,1.],100),'arena':1.})
        with self.assertRaisesRegex(RuntimeError,'absorbed'):
            fit(f,['arena'])

    def test_perfect_collinearity_fails(self):
        rng=np.random.default_rng(8);f=pd.DataFrame({'chooser':np.arange(400)%20,
          'kind':rng.normal(size=400),'arena':rng.integers(0,2,400)})
        f['duplicate']=f.arena*2
        with self.assertRaisesRegex(RuntimeError,'rank deficient'):
            fit(f,['arena'],['duplicate'])

    def test_missing_model_inputs_fail(self):
        f=pd.DataFrame({'chooser':[1,1,2,2,3,3],'kind':[0,1,0,1,0,1],'arena':[0,1,0,1,np.nan,1]})
        with self.assertRaisesRegex(RuntimeError,'missing'):
            fit(f,['arena'])

class DataTests(unittest.TestCase):
    def source_mask_fixture(self,con,auth):
        timestamps=['2023-11-01T00:30:00Z','2023-11-30T23:30:00Z',
          '2024-03-01T00:30:00Z','2024-03-31T23:30:00Z',
          '2024-07-01T00:30:00Z','2024-07-31T23:30:00Z',
          '2024-12-01T00:30:00Z','2024-12-31T23:30:00Z']
        records=[]
        for i,when in enumerate(timestamps):
            status=auth.STATUSES[i%4]
            candidate=status==auth.CANDIDATE
            records.append({'game_id':f't{i:07d}','month':when[:7],
              'p1':i+1,'p2':i+101,'focal_mapping_ok':True,
              'focal_start_ms':int(pd.Timestamp(when).timestamp()*1000),
              'source':'arena' if i%2 else 'pool','source_provenance':'synthetic_fixture',
              'previous_classification_status':status,
              'mutual_previous_same_pair':True if candidate else False if status==auth.NONADJACENT else None,
              'mutual_previous_observed':candidate,
              'previous_start_order_ambiguous':status==auth.AMBIGUOUS,
              'previous_game_id':f'p{i:07d}' if candidate else None})
        frame=pd.DataFrame(records)
        con.register('fixture',frame)
        con.execute('CREATE TEMP TABLE j AS SELECT * FROM fixture')
        con.execute('CREATE TEMP TABLE s AS SELECT game_id,month,source,source_provenance FROM j')
        previous=frame.groupby(['month','source','previous_classification_status']).size().reset_index(name='rows')
        previous=previous.rename(columns={'previous_classification_status':'classification_status'})
        return {'expected_counts':{'original':len(frame)},'previous':previous.to_dict('records')}

    def test_original_validator_reproduces_non_utc_month_failure(self):
        auth=load_source('source/auth/build_main_sample.py','arena_timezone_reproduction_test')
        con=duckdb.connect()
        try:
            plan=self.source_mask_fixture(con,auth)
            for zone in ('America/Toronto','America/Denver','Europe/Paris'):
                with self.subTest(zone=zone):
                    con.execute('SET TimeZone='+q(zone))
                    with self.assertRaisesRegex(ValueError,'4 invalid joined flag/identity/month rows'):
                        auth.mask_validation(con,plan)
            con.execute("SET TimeZone='UTC'")
            qa=auth.mask_validation(con,plan)
            self.assertEqual(qa['rows'],8)
            self.assertEqual(qa['invalid_joined_rows'],0)
        finally:con.close()

    def test_database_restores_utc_and_validates_boundary_rows(self):
        auth=load_source('source/auth/build_main_sample.py','arena_utc_connection_test')
        connect=duckdb.connect
        with tempfile.TemporaryDirectory(prefix='arena_timezone_test_') as t:
            for i,zone in enumerate(('America/Toronto','America/Denver','Europe/Paris','Asia/Kolkata','UTC')):
                with self.subTest(zone=zone):
                    def local_connection(*args,**kwargs):
                        con=connect(*args,**kwargs)
                        con.execute('SET TimeZone='+q(zone))
                        return con
                    with mock.patch.object(duckdb,'connect',side_effect=local_connection):
                        con,info=database(':memory:',1,'512MB',Path(t)/str(i)/'spill',with_timezone_info=True)
                    try:
                        self.assertEqual(info,{'inherited_timezone':zone,'active_timezone':'UTC'})
                        plan=self.source_mask_fixture(con,auth)
                        out=Path(t)/str(i)/'validation'
                        with contextlib.redirect_stdout(io.StringIO()):
                            qa=validate_source_masks(con,plan,auth,out,info)
                        audit=read_json(out/'source_month_timezone.json')
                        self.assertEqual(qa['invalid_joined_rows'],0)
                        self.assertEqual(audit['utc_month_mismatches'],0)
                        self.assertEqual(audit['inherited_month_mismatches'],0 if zone=='UTC' else 4)
                        self.assertEqual(read_json(out/'source_validation.json')['status'],'PASSED')
                    finally:con.close()

    def test_utc_fix_still_rejects_genuine_flag_and_month_errors(self):
        auth=load_source('source/auth/build_main_sample.py','arena_utc_rejection_test')
        with tempfile.TemporaryDirectory(prefix='arena_validation_failure_test_') as t:
            con,info=database(':memory:',1,'512MB',Path(t)/'spill',with_timezone_info=True)
            try:
                plan=self.source_mask_fixture(con,auth)
                con.execute("UPDATE j SET p2=p1 WHERE game_id='t0000000'")
                con.execute("UPDATE j SET month='1900-01' WHERE game_id='t0000007'")
                out=Path(t)/'validation'
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError,'2 invalid joined'):
                    validate_source_masks(con,plan,auth,out,info)
                report=read_json(out/'source_validation.json')
                self.assertEqual(report['status'],'FAILED')
                self.assertEqual(report['flag_failure_counts']['invalid_any'],2)
                self.assertEqual(report['flag_failure_counts']['same_player'],1)
                self.assertEqual(report['flag_failure_counts']['utc_month_mismatch'],1)
            finally:con.close()

    def test_frozen_board_boundaries(self):
        con=duckdb.connect();f=pd.DataFrame({'eval':[-300,-299,-101,-100,100,101,299,300]});con.register('f',f)
        self.assertEqual([x[0] for x in con.execute('SELECT '+board_case()+' AS bin FROM f').fetchall()],[4,3,3,2,2,1,1,0])
        con.close()

    def test_receipt_does_not_skip_pool_or_ambiguous_first_target(self):
        con=duckdb.connect()
        exposures=pd.DataFrame([
          ['expa0001',10,100,1.,'arena',True],['expa0002',20,200,0.,'arena',True],
          ['expa0003',30,300,1.,'arena',True],['expa0004',40,400,1.,'arena',True],
          ['expa0005',40,400,0.,'arena',True]],
          columns=['game_id','opponent','last_move_ms','kind','source','claimed'])
        targets=pd.DataFrame([
          ['trgt0001',10,110,'pool',NONADJACENT,1.,0],
          ['trgt0002',10,120,'arena',NONADJACENT,0.,0],
          ['trgt0003',20,210,'pool',NONADJACENT,0.,0],
          ['trgt0004',20,210,'arena',NONADJACENT,1.,0],
          ['trgt0005',20,220,'arena',NONADJACENT,1.,0],
          ['trgt0006',30,300,'pool',NONADJACENT,0.,0],
          ['trgt0007',30,310,'arena',NONADJACENT,0.,0]],
          columns=['game_id','chooser','start_ms','source','previous_status','kind','eval'])
        con.register('eligible',exposures);con.register('all_opps',targets)
        diag=next_fair_support(con)
        got=con.execute('SELECT recipient,target_source,target_id FROM next_targets ORDER BY recipient').fetchall()
        self.assertEqual(got,[(10,'pool','trgt0001'),(20,None,None),(30,'arena','trgt0007')])
        self.assertEqual(diag['ambiguous_earliest_target'],1)
        self.assertEqual(diag['exposures_after_tie_exclusion'],3)
        self.assertEqual(diag['same_start_as_exposure_last_move'],1)
        con.close()

    def fixture_month(self,root,month='2023-11'):
        sources=['arena']*4+['pool']*3+['friend'];n=len(sources)
        status=[NONADJACENT]*n;status[3]='left_boundary_unresolved';status[6]='mutual_adjacency_candidate_timing_unresolved'
        base=pd.DataFrame({'game_id':[f'g{i:07}' for i in range(n)],'month':month,
          'chooser_user_id':np.arange(n)+1,'disconnected_user_id':np.arange(n)+20,
          'chooser_username_norm':['user'+str(i) for i in range(n)],'utc_ms':np.arange(n)*1000+1700000000000,
          'api_last_move_at_ms':np.arange(n)*1000+1700000000500,'outcome_kind_draw':[True,False]*4,
          'timeout_chooser_win':[False,True]*4,'engine_eval_cp_disconnected':[0,-300,300,50,-100,101,-101,0],
          'engine_eval_is_mate':False,'ply_count':20,'api_speed':'blitz','time_control':'180+0',
          'tc_base_s':180.,'tc_inc_s':0.,'chooser_elo':1500,'disconnected_elo':1600,
          'chooser_pre_rd_v2':65.,'disconnected_pre_rd_v2':75.,'chooser_draw_payoff_v2':1.,
          'chooser_win_premium_v2':6.,'chooser_win_payoff_v2':7.,'chooser_clock_last_obs_s':30.,
          'disconnected_clock_last_obs_s':20.,'api_status':'timeout','api_rated':True,
          'sf100k_nodes_requested':100000,'kind_draw':[True,False]*4,'chooser_has_mating_material':True})
        join=pd.DataFrame({'game_id':base.game_id,'month':month,'p1':base.chooser_user_id,
          'p2':base.disconnected_user_id,'focal_start_ms':base.utc_ms,'source':sources,
          'previous_classification_status':status})
        p=root/'panel.parquet';base.to_parquet(p,index=False)
        jr=root/'joins'/('join_month='+month);jr.mkdir(parents=True);join.to_parquet(jr/'part.parquet',index=False)
        sc=[{'source':s,'rows':sources.count(s)} for s in sorted(set(sources))]
        cs=join.groupby(['source','previous_classification_status']).size().reset_index(name='rows')
        statuses=[{'source':r.source,'classification_status':r.previous_classification_status,'rows':int(r.rows)} for r in cs.itertuples()]
        m={'month':month,'panel_path':str(p),'expected_counts':{'original':n},'source_counts':sc,'statuses':statuses}
        return (m,str(root/'joins'),str(root/'run'),'SYNTHETIC_TEST_CONTRACT','512MB',1),base,join

    def test_month_conservation_orientation_and_resume_hash(self):
        with tempfile.TemporaryDirectory(prefix='arena_join_test_') as t:
            root=Path(t);task,base,join=self.fixture_month(root)
            result=build_month(task)
            self.assertEqual(result['arena'],{'n':3,'grants':2,'fair_n':2,'fair_grants':2})
            self.assertEqual(result,build_month(task))
            output=root/'run/private/months/month=2023-11/opportunities.parquet'
            got=pd.read_parquet(output)
            self.assertEqual(len(got),8)
            self.assertEqual(got.loc[got.source=='arena','previous_status'].value_counts()[NONADJACENT],3)
            with output.open('ab') as f:f.write(b'corrupt')
            with self.assertRaisesRegex(RuntimeError,'changed'):build_month(task)

    def test_swapped_orientation_fails(self):
        with tempfile.TemporaryDirectory(prefix='arena_bad_join_') as t:
            root=Path(t);task,base,join=self.fixture_month(root)
            join.loc[0,'p1']=int(join.loc[0,'p2'])
            join.to_parquet(root/'joins/join_month=2023-11/part.parquet',index=False)
            with self.assertRaisesRegex(RuntimeError,'orientation'):build_month(task)

    def test_wrong_timeout_fails(self):
        with tempfile.TemporaryDirectory(prefix='arena_wrong_status_') as t:
            root=Path(t);task,base,join=self.fixture_month(root)
            base.loc[0,'api_status']='outoftime';base.to_parquet(root/'panel.parquet',index=False)
            with self.assertRaisesRegex(RuntimeError,'Opportunity'):build_month(task)

    def test_missing_disconnected_clock_is_retained_in_both_outputs(self):
        with tempfile.TemporaryDirectory(prefix='arena_missing_clock_test_') as t:
            root=Path(t);task,base,join=self.fixture_month(root)
            base.loc[0,'disconnected_clock_last_obs_s']=np.nan
            base.to_parquet(root/'panel.parquet',index=False)
            result=build_month(task)
            self.assertEqual(result['arena'],{'n':3,'grants':2,'fair_n':2,'fair_grants':2})
            panel=root/'run/private/months/month=2023-11'
            narrow=pd.read_parquet(panel/'opportunities.parquet')
            wide=pd.read_parquet(panel/'analysis_panel.parquet')
            self.assertEqual(len(narrow),8);self.assertEqual(len(wide),3)
            self.assertTrue(pd.isna(narrow.loc[narrow.game_id=='g0000000','clock_opp'].iloc[0]))
            self.assertTrue(pd.isna(wide.loc[wide.game_id=='g0000000','disconnected_clock_last_obs_s'].iloc[0]))
            qa=read_json(root/'run/public/validation/opportunities_2023-11.json')
            self.assertEqual(qa['checks']['missing_disconnected_clock_rows'],1)
            self.assertEqual(qa['checks']['kind_draws_with_missing_clock'],1)
            self.assertEqual(qa['checks']['invalid_any'],0)

    def test_recorded_clock_floor_is_still_enforced(self):
        with tempfile.TemporaryDirectory(prefix='arena_clock_floor_test_') as t:
            root=Path(t);task,base,join=self.fixture_month(root)
            base.loc[0,'disconnected_clock_last_obs_s']=4.999
            base.loc[1,'disconnected_clock_last_obs_s']=5.0
            base.to_parquet(root/'panel.parquet',index=False)
            with self.assertRaisesRegex(RuntimeError,'clock_rule_failure_rows=1'):
                build_month(task)
            qa=read_json(root/'run/public/validation/opportunities_2023-11.json')
            self.assertEqual(qa['failed_conditions'],{'clock_rule_failure_rows':1})
            self.assertEqual(qa['checks']['recorded_clock_below_5_rows'],1)

    def test_opportunity_failure_names_every_failed_condition(self):
        with tempfile.TemporaryDirectory(prefix='arena_opportunity_diagnostic_test_') as t:
            root=Path(t);task,base,join=self.fixture_month(root)
            base.loc[0,'disconnected_clock_last_obs_s']=np.nan
            base.loc[1,'api_rated']=False
            base.loc[2,'sf100k_nodes_requested']=99999
            base.loc[4,'kind_draw']=False
            base.loc[6,'chooser_has_mating_material']=False
            base.to_parquet(root/'panel.parquet',index=False)
            with self.assertRaisesRegex(RuntimeError,'non_rated_rows=1'):
                build_month(task)
            qa=read_json(root/'run/public/validation/opportunities_2023-11.json')
            self.assertEqual(qa['failed_conditions'],{
              'non_rated_rows':1,'requested_nodes_mismatch_rows':1,
              'kind_alias_mismatch_rows':1,'kind_without_mating_material_rows':1})
            self.assertEqual(qa['checks']['invalid_any'],4)
            self.assertEqual(qa['checks']['missing_disconnected_clock_rows'],1)

    def test_clock_contract_sources_match_original_certification(self):
        contract=read_json(ROOT/'authority/OPPORTUNITY_CONTRACT.json')
        certificate=read_json(ROOT/'authority/STAGE07_CERTIFICATE.json')
        auth=load_source('source/auth/build_main_sample.py','arena_opportunity_certificate_test')
        self.assertEqual(sha(ROOT/'authority/STAGE07_CERTIFICATE.json'),auth.CERT_SHA)
        self.assertEqual(sha(ROOT/'source/certified/07_build_analysis_panel.py'),auth.CERT_PRODUCER)
        self.assertEqual(sha(ROOT/'source/certified/05_build_timeout_opportunity_panel.py'),
                         certificate['authority_sha256'][contract['stage05_producer_certificate_key']])
        self.assertTrue(contract['missing_disconnected_clock_allowed'])

    def test_original_authority_bundles_verify(self):
        module=load_source('source/auth/build_main_sample.py','arena_evidence_test')
        evidence=module.load_evidence(ROOT/'source/auth')
        self.assertEqual(len(evidence['panel_receipts']),24)
        self.assertEqual(sum(r['rows'] for r in evidence['previous'] if r['source']=='arena' and r['classification_status']==NONADJACENT),1892835)

    def test_full_new_analysis_integration(self):
        from analysis import suppression,structural,persistence
        from support import run_support
        with tempfile.TemporaryDirectory(prefix='arena_integration_test_') as t:
            root=Path(t);integration_fixture(root)
            with contextlib.redirect_stdout(io.StringIO()):
                suppression(root,'512MB',1)
                structural(root,'512MB',1)
                persistence(root,'512MB',1)
                run_support(root,root/'no_production_snapshot','512MB',1)
            result=read_json(root/'public/suppression/competitive_full.json')
            self.assertEqual(result['status'],'ESTIMATED')
            self.assertEqual(read_json(root/'public/support/patron_status.json')['status'],'SNAPSHOT_NOT_AVAILABLE')
            self.assertTrue((root/'public/support/receipt_transition_support.parquet').is_file())

def integration_fixture(root,n=12000):
    rng=np.random.default_rng(867535);months=[f'{y}-{m:02}' for y in [2023,2024,2025] for m in range(1,13)
       if '2023-11'<=f'{y}-{m:02}'<='2025-10']
    f=pd.DataFrame({'game_id':[f'z{i:07}' for i in range(n)],'month':rng.choice(months,n),
      'chooser':rng.integers(1,61,n),'opponent':rng.integers(1,61,n),'source':rng.choice(['pool','arena'],n,p=[.7,.3]),
      'previous_status':NONADJACENT,'kind':rng.binomial(1,.08,n).astype(float),
      'eval':rng.choice([-500,-180,0,180,500],n),'ply':rng.choice([2,6,8,10,16,30,60,100],n),
      'speed':'blitz','time_control':rng.choice(['180+0','180+2'],n),'tc_base_s':180.,'tc_inc_s':rng.choice([0.,2.],n),
      'rating':rng.integers(1400,1800,n).astype(float),'gap':rng.integers(-200,201,n).astype(float),
      'rd':rng.uniform(40,100,n),'opp_rd':rng.uniform(40,100,n),'premium':rng.uniform(5,15,n),
      'payoff':rng.uniform(-4,4,n),'clock_self':rng.uniform(5,170,n),'clock_opp':rng.uniform(5,170,n),
      'mate':False})
    f['username']='synth_'+f.chooser.astype(str)
    f['start_ms']=[int(pd.Timestamp(m+'-01',tz='UTC').timestamp()*1000)+i*100000 for i,m in enumerate(f.month)]
    f['last_move_ms']=f.start_ms+10000;f['claimed']=f.kind==0;f['win_payoff']=f.payoff+f.premium
    con=duckdb.connect();con.register('f',f)
    f=con.execute(f'SELECT *,{board_case()} AS board,{ply_case()} AS stage FROM f').fetchdf();con.close()
    p=root/'private/synthetic.parquet';p.parent.mkdir(parents=True);f.to_parquet(p,index=False)
    json_write(root/'private/BUILD.json',{'status':'SYNTHETIC_TEST_ONLY','contract':'SYNTHETIC_TEST_ONLY','narrow_paths':[str(p)]})
    return f

def run():
    started=time.time()
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():return 1
    print(f'ARENA_SELF_TEST_OK: {result.testsRun} tests; {time.time()-started:.2f}s',flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(run())
