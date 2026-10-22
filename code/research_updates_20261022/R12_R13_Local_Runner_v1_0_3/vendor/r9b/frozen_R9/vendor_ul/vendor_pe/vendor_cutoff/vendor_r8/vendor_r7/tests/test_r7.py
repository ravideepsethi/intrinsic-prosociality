import sys,unittest,tempfile,copy,contextlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from r7_common import *
from r7_math import *
import r7_models,r7_inputs,r7_moves,r7_composition,r7_report,run_r7
sys.path.insert(0,str(ROOT/'vendor_phase50/vendor_env102/tests'))
from test_environment import model_data
from phase50_models import checked_solver

def fixture(n=6000):
    d=model_data(n);n=len(d['row_id']);rng=np.random.default_rng(81279)
    # Original upstream fixture has no zero-choice recipients. R7 needs all
    # fifteen independent history regressors, including availability indicators.
    for days in (30,90):
        fair=rng.poisson(3,n);fair[rng.random(n)<.2]=0
        d[f'fair_{days}']=fair;d[f'kind_{days}']=rng.binomial(fair,.17)
        for key in ('disconnect','receipt','claim'):d[f'{key}_{days}']=rng.poisson(2,n)
    d['pre_games_30d']=rng.poisson(20,n);d['complete']=np.ones(n,bool)
    d['ply_count']=np.full(n,8);d['engine_eval_cp_disconnected']=np.zeros(n)
    d['disconnected_clock_last_obs_s']=d['tc_base_s']*.5
    return d

class NumericalTests(unittest.TestCase):
    def test_same_frozen_estimator_and_AR(self):
        d=fixture();got,_=r7_models.estimate(d,'iv','fixture',part_a=False)
        spec=next(s for s in design.specifications() if s['name']=='main90_pooled')
        with checked_solver():old=stats.estimate(d,spec)
        for oldname,newname,outcome in [('first_stage_per_reference_SD','first_stage','received'),('RF_kindness_per_reference_SD','reduced_form','y'),('RF_reach_per_reference_SD','reduced_form','reached'),('2SLS','2SLS','y')]:
            a=next(v for v in old['estimates'] if v['estimator']==oldname)
            b=next(v for v in got['B_estimates'] if v['estimator']==newname and v['outcome']==outcome)
            for k in ('coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp'):
                if k in a:self.assertAlmostEqual(a[k],b[k],8)
            if 'AR95_intervals_pp' in a:np.testing.assert_allclose(a['AR95_intervals_pp'],b['AR95_intervals_pp'],atol=1e-7)
        want=next(v for v in old['joint_balance'] if v['test_set']=='recent_behavior')
        self.assertAlmostEqual(want['wald_chi2'],got['B_joint_balance'][0]['wald_chi2'],7)

    def test_dyadic_or_date_covariance_against_explicit_pair_indicator(self):
        rng=np.random.default_rng(319);n=65
        i=rng.integers(1,15,n);j=(i+rng.integers(1,14,n))%15+20
        # Cross-role shared accounts and unordered duplicate pairs.
        i[::4],j[::4]=j[::4].copy(),i[::4].copy();day=rng.integers(1,9,n);s=rng.normal(size=(n,3))
        H=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(day[:,None]==day)
        codes=stats.cmp.covariance_codes(i,j,day)
        np.testing.assert_allclose(stats.stats.shared_meat(s,codes,True),s.T@H@s,atol=1e-10)

    def test_A_joint_OLS_against_explicit_dummy_design(self):
        rng=np.random.default_rng(82);n=800
        g=rng.integers(0,8,n);x=rng.normal(size=(n,2));T=rng.normal(size=(n,4));y=T@np.array([.1,-.2,.3,.4])+g*.2+x[:,0]+rng.normal(size=n)
        residual,_=project(x,np.column_stack([T,y]),[g]);b,V,_,_=multi(residual[:,-1],residual[:,:4],lambda s:s.T@s)
        X=np.column_stack([np.eye(8)[g],x,T]);allb=np.linalg.lstsq(X,y,rcond=None)[0]
        np.testing.assert_allclose(b,allb[-4:],atol=1e-10)

    def test_A3_delta_influence_against_numerical_case_weight_derivative(self):
        rng=np.random.default_rng(188);n=160;T=rng.normal(size=(n,3));Y=T@np.array([.2,-.1,.3])+rng.normal(size=n);Z=T[:,0]*.3+rng.normal(size=n)
        x=np.empty((n,0));groups=[np.zeros(n,np.int64)];captured=[]
        def meat(s):captured.append(np.asarray(s).reshape(n,-1).copy());return captured[-1].T@captured[-1]
        fit=generated_index(T,Y,x,x,Z,groups,meat)
        influence=captured[0][:,0]
        def weighted(w):
            tm=np.average(T,axis=0,weights=w);ym=np.average(Y,weights=w);zm=np.average(Z,weights=w)
            t=T-tm;y=Y-ym;z=Z-zm
            b=np.linalg.solve(t.T@(w[:,None]*t),t.T@(w*y))
            return float((w*z)@(T@b))/float((w*z)@z)
        for k in (0,7,40,100):
            wp=np.ones(n);wm=np.ones(n);wp[k]+=1e-5;wm[k]-=1e-5
            derivative=(weighted(wp)-weighted(wm))/(2e-5)
            self.assertAlmostEqual(derivative,influence[k],7)
        self.assertTrue(fit['prediction_rule_uncertainty_included'])

    def test_joint_A_and_crossfit_output(self):
        d=fixture(6500);r,_=r7_models.estimate(d,'iv','fixture',part_a=True,calibration=True)
        self.assertEqual(len(r['A_joint_balance']),52)
        self.assertEqual(len(r['A_predicted_outcome']),8)
        for row in r['A_predicted_outcome']:
            self.assertTrue(row['prediction_rule_uncertainty_included'])
            self.assertAlmostEqual(row['coefficient_pp'],row['coefficient']*100*SD['pooled'])

    def test_crossfit_delta_against_weighted_refits(self):
        rng=np.random.default_rng(337);n=180;T=rng.normal(size=(n,3));x=rng.normal(size=(n,1));Y=T[:,0]*.4+x[:,0]+rng.normal(size=n);Z=T[:,0]*.2+rng.normal(size=n)
        i=np.arange(1,n+1);j=np.arange(301,301+n);groups=[np.zeros(n,np.int64)];captured=[]
        def meat(s):captured.append(np.asarray(s).reshape(n,-1).copy());return captured[-1].T@captured[-1]
        generated_index(T,Y,x,x,Z,groups,meat,'crossfit',i,j)
        influence=captured[0][:,0];fold=(num.user_hash(i)%np.uint64(4)).astype(int);ofold=(num.user_hash(j)%np.uint64(4)).astype(int)
        def weighted(w):
            pred=np.zeros(n)
            for f in range(4):
                use=(fold!=f)&(ofold!=f);test=fold==f;X=np.column_stack([np.ones(use.sum()),x[use],T[use]])
                b=np.linalg.solve(X.T@(w[use,None]*X),X.T@(w[use]*Y[use]));pred[test]=T[test]@b[-3:]
            X=np.column_stack([np.ones(n),x,Z]);b=np.linalg.solve(X.T@(w[:,None]*X),X.T@(w*pred));return b[-1]
        for k in (0,16,90,130):
            wp=np.ones(n);wm=np.ones(n);wp[k]+=1e-5;wm[k]-=1e-5
            self.assertAlmostEqual((weighted(wp)-weighted(wm))/(2e-5),influence[k],7)

    def test_indicator_does_not_mutate_missing_histories_and_XC_rejects_missing(self):
        d=fixture();d['environment_supported'][::7]=False
        for k in ENV:d[k][::7]=np.nan
        before={k:d[k].copy() for k in ENV};x,names,_,_=feature_design(d,'X0_ENV_indicator')
        self.assertTrue(np.isfinite(x).all());self.assertIn('env_supported',names)
        for k in ENV:np.testing.assert_equal(d[k],before[k])
        with self.assertRaisesRegex(RuntimeError,'ENV missing'):feature_design(d,'X0_ENV')
        selected=r7_models.select_sample(d,'env');self.assertEqual(len(selected['row_id']),int(d['environment_supported'].sum()))
        r1,_=r7_models.estimate(selected,'iv','env','X0',part_a=False)
        r2,_=r7_models.estimate(selected,'iv','env','X0_ENV',part_a=False)
        self.assertEqual(r1['B_estimates'][0]['row_set_sha256'],r2['B_estimates'][0]['row_set_sha256'])

    def test_repeated_membership_is_frozen_before_environment_subset(self):
        d=dict(row_id=np.arange(6),recipient_id=np.array([1,1,2,3,3,4]),environment_supported=np.array([1,0,1,1,0,1],bool))
        self.assertEqual(r7_models.select_sample(d,'repeat_env')['row_id'].tolist(),[0,3])

class MoveTests(unittest.TestCase):
    def test_net_material_replay_capture_exchange_promotion_and_final_ply(self):
        # Equal pawn exchange has zero NET material, though a recipient pawn fell.
        r=r7_moves.replay('e4 d5 exd5 Qxd5',4);self.assertEqual(r['net_material_change_4ply'],0)
        # After White gives up a queen, White is next to move and loses nine.
        r=r7_moves.replay('e4 e5 Qh5 Nc6 Qxf7+ Kxf7',6);self.assertEqual(r['net_material_change_4ply'],-8)
        fen='7k/P7/8/8/8/8/8/7K w - - 0 1'
        r=r7_moves.replay('a8=Q+',1,fen);self.assertEqual(r['net_material_change_4ply'],-8)
        with self.assertRaisesRegex(ValueError,'FINAL_PLY'):r7_moves.replay('e4 e5',3)
        with self.assertRaises(ValueError):r7_moves.replay('e4 e6 e5 e5',4)

    def test_missing_is_not_quiet_and_clock_units(self):
        d=dict(row_id=np.arange(4),ply_count=np.array([40,40,20,40]),net_material_change_4ply=np.array([np.nan,0,-3,0]),
           moves_available=np.array([False,True,True,True]),disconnected_clock_last_obs_s=np.array([50,10,np.nan,9.9]),
           tc_base_s=np.full(4,100),engine_eval_cp_disconnected=np.array([0,0,-350,np.nan]))
        c=r7_composition.classify(d)
        self.assertEqual(c['quiet'].tolist(),[False,True,False,False]);self.assertEqual(c['swing'].tolist(),[False,False,True,False])
        self.assertEqual(c['material_band'][0],'unavailable');self.assertEqual(c['merit_code'][3],'unavailable')

    def test_physical_move_cache_replay_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);io.table(p/'targets.parquet',pa.table(dict(game_id=['abcd1234'],ply_count=[4])))
            (p/'cache.ndjson').write_text(json.dumps(dict(id='abcd1234',players={},moves='e4 d5 exd5 Qxd5'))+'\n')
            j=dict(targets=str(p/'targets.parquet'),inputs=[dict(path=str(p/'cache.ndjson'),kind='json',signature=io.sig(p/'cache.ndjson'))],output=str(p/'out'),conf='fixture')
            r7_moves.move_job(j);old=io.sha(p/'out/moves.parquet');r7_moves.move_job(j);self.assertEqual(old,io.sha(p/'out/moves.parquet'))
            row=io.read(p/'out/moves.parquet').to_pylist()[0];self.assertTrue(row['valid']);self.assertEqual(row['net_material_change_4ply'],0)

class OperationalTests(unittest.TestCase):
    def test_new_ENV_requests_preserve_pair_month_keys(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            io.table(p/'input.parquet',pa.table(dict(recipient_id=[20,21,20,30],opponent_id=[10,10,10,10],month_code=[6,6,7,6])))
            io.table(p/'old.parquet',pa.table(dict(person=[10,10],partner=[20,21],month_code=[6,6])))
            req,info=r7_inputs.missing_requests([p/'input.parquet'],p/'old.parquet',p/'req','fixture',1)
            self.assertEqual(info['missing_requests'],2)
            rows=io.read(req/'requests.parquet').to_pylist()
            self.assertEqual([(r['person'],r['partner'],r['month_code']) for r in rows],[(10,20,7),(10,30,6)])
            r7_inputs.missing_requests([p/'input.parquet'],p/'old.parquet',p/'req','fixture',1)

    def test_spawned_F50_A4_and_competitive_bridge_models(self):
        from phase50_models import fit_map
        from performance_runtime import Runtime
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=fixture(4200);d['environment_supported'][::13]=False;d['complete'][::13]=False
            for name in ENV:d[name][::13]=np.nan
            io.table(p/'input.parquet',pa.table(d));paths={k:p/'input.parquet' for k in ('S0','F50','O50')}
            jobs=run_r7.plan(paths,p,'fixture')
            chosen=[j for j in jobs if (j['sample']=='F50' and j['level']=='X0_ENV_indicator') or
                    (j['sample']=='S0_CSE' and j['level']=='XC_ENV')]
            fit_map(r7_models.model_job,chosen,Runtime(p),2,6,'synthetic spawned R7',lambda:None)
            for j in chosen:self.assertTrue((Path(j['output'])/'_DONE.json').exists())
            entry=io.load(Path(chosen[1]['output'] if chosen[1]['sample']=='F50' else chosen[0]['output'])/'result.json')
            self.assertEqual({r['predicted_outcome'] for r in entry['A_predicted_outcome']},{'analysis_entry_90','recipient_disconnect_main','y'})

    def test_parquet_union_schema_and_job_restart_changed_input(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=fixture();io.table(p/'data.parquet',pa.table(d))
            j=dict(input=str(p/'data.parquet'),selection='',sample='S0',level='X0',instrument='pooled',kind='iv',part_a=False,influence=True,output=str(p/'fit'),conf='fixture')
            r7_models.model_job(j);digest=io.sha(p/'fit/result.json');r7_models.model_job(j)
            self.assertEqual(digest,io.sha(p/'fit/result.json'))
            write_rows(p,'union',[dict(a=1),dict(a=2,iv_coefficient_pp=.3)])
            self.assertIn('iv_coefficient_pp',io.read(p/'union.parquet').schema.names)
            with (p/'data.parquet').open('ab') as f:f.write(b'changed')
            with self.assertRaises(RuntimeError):r7_models.model_job(j)

    def test_plan_bridge_rows_and_separate_indicator(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);io.table(p/'data.parquet',pa.table(dict(row_id=[1,2])))
            paths={k:p/'data.parquet' for k in ('S0','F50','O50')};jobs=run_r7.plan(paths,p,'fixture')
            cse=[j for j in jobs if j['sample']=='S0_CSE']
            self.assertEqual({j['level'] for j in cse},{'X0','X0_ENV','XC','XC_ENV'})
            self.assertEqual({j['selection'] for j in cse},{'comp_env'})
            self.assertEqual(len({j['output'] for j in jobs}),len(jobs))

    def test_actual_joins_C_models_report_and_joint_placebo_contrast(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=fixture(3300);n=len(d['row_id']);paths={}
            # Real Parquets and ordinary/readout contrast, with shared accounts.
            for sample,kind in [('S0','iv'),('O50','ordinary'),('F50','entry')]:
                src=p/(sample+'.parquet');io.table(src,pa.table(d));paths[sample]=src
                if sample!='F50':
                    r7_models.model_job(dict(input=str(src),selection='',sample=sample,level='X0',instrument='pooled',kind=kind,
                        part_a=False,influence=True,output=str(p/'models'/sample),conf='fixture'))
            contrast=r7_models.contrast(p/'models/S0',p/'models/O50',{})
            self.assertAlmostEqual(contrast[0]['coefficient_pp'],0,12)
            # Identical regression samples/outcomes must have zero difference variance,
            # not the falsely positive sum of separate variances.
            self.assertLess(contrast[0].get('standard_error_pp',0),1e-10)
            panel=p/'panel.parquet';io.table(panel,pa.table(dict(game_id=d['game_id'],disconnected_user_id=d['recipient_id'],chooser_user_id=d['opponent_id'],
                ply_count=np.full(n,8),engine_eval_cp_disconnected=np.zeros(n),disconnected_clock_last_obs_s=d['tc_base_s']*.5,fair_competitive=np.ones(n,bool))))
            moves=p/'moves';moves.mkdir()
            io.table(moves/'records.parquet',pa.table(dict(game_id=d['game_id'],moves=['e4 d5 exd5 Qxd5 Nc3 Qd8 Nf3 Nf6']*n)))
            binding=dict(source=dict(panels=[dict(path=str(panel),sha256=io.sha(panel),bytes=panel.stat().st_size)]))
            class InlineRuntime:
                def save(self,row):pass
                def mapped(self,fn,jobs,workers,label):return [fn(j) for j in jobs]
            cpaths,info=r7_moves.prepare(paths,binding,p,p/'composition','fixture',3,1,InlineRuntime(),[moves])
            self.assertEqual(info['moves_available'],n)
            for sample,path in cpaths.items():
                r7_composition.job(dict(input=str(path),sample=sample,output=str(p/'models'/('C_'+sample)),conf='fixture'))
            summary=r7_report.export(p,p/'desktop','fixture','R7_ANALYSIS_COMPLETE',time.monotonic(),4)
            self.assertEqual(summary['status'],'R7_ANALYSIS_COMPLETE')
            self.assertTrue((p/'desktop/R7_ANALYSIS_REPORT_fixture.zip').exists())
            self.assertTrue(io.load(p/'report/C_entry_by_class.json'))

if __name__=='__main__':unittest.main()
