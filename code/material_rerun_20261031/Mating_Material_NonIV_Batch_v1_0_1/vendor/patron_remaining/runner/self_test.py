"""Offline numerical checks and regression tests with the bundled public report."""
from __future__ import annotations
import ast, contextlib, hashlib, io, json, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
import duckdb, numpy as np, pandas as pd
from source import synthetic_fixture_v101 as fixture
from source import cache_builder_v101 as builder
from source import opportunity_models_v101 as original_op
from source import opportunity_models_cov_v100 as extended_op
from source import chooser_models_v101 as chooser
from source import postcertification_v100 as add
from source import wave3b1_helpers as h
from runner import families, opportunity, dyad
from runner import run as runner


class Tests(unittest.TestCase):
    def test_01_source_bindings_and_serialization_only_change(self):
        bindings=json.loads((ROOT/'authority/SOURCE_BINDINGS.json').read_text())
        for item in bindings:
            self.assertEqual(h.auth.sha256_file(ROOT/item['destination']),item['sha256'])
        old=ast.parse((ROOT/'source/opportunity_models_v101.py').read_text())
        new=ast.parse((ROOT/'source/opportunity_models_cov_v100.py').read_text())
        fn=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='fit_collapsed_model')
        del fn.body[-3:-1]
        self.assertEqual(ast.dump(old,include_attributes=False),ast.dump(new,include_attributes=False))
        for name in ['parquet_rows','_authenticate_bucket','authenticate_frequent_state']:
            a=ast.parse((ROOT/'source/wave2b2b1_preflight_original.py').read_text())
            b=ast.parse((ROOT/'source/dyad_auth.py').read_text())
            a=next(n for n in a.body if isinstance(n,ast.FunctionDef) and n.name==name)
            b=next(n for n in b.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(a,include_attributes=False),ast.dump(b,include_attributes=False))

    def test_02_collapsed_matches_expanded_ols_and_covariance(self):
        rng=np.random.default_rng(612)
        rows=[];expanded=[]
        for cluster in range(30):
            for x in [0,1]:
                n=int(rng.integers(2,8));k=int(rng.integers(0,n+1))
                rows.append({'cluster_code':cluster,'opportunities':n,'kind_draws':k,'x':x})
                expanded.extend((cluster,x,y) for y in [100.]*k+[0.]*(n-k))
        db=duckdb.connect();data=pd.DataFrame(rows);db.register('cells',data)
        kwargs=dict(table='cells',condition='TRUE',model_name='test',terms=[('1.0','intercept'),('x','x')],primary_terms=['x'])
        # Cross-batch cluster scores must also work for deliberately tiny batches.
        def batches(con,query,rows_per_batch=7):
            yield from con.execute(query).to_arrow_reader(batch_size=rows_per_batch)
        with patch.object(extended_op,'record_batches',batches):
            model,coef=extended_op.fit_collapsed_model(db,**kwargs)
        original,oldcoef=original_op.fit_collapsed_model(db,**kwargs)
        np.testing.assert_allclose(coef.coefficient_pp,oldcoef.coefficient_pp,rtol=1e-12)
        np.testing.assert_allclose(coef.se_pp,oldcoef.se_pp,rtol=1e-12)
        d=np.array(expanded);X=np.column_stack([np.ones(len(d)),d[:,1]]);y=d[:,2]
        inv=np.linalg.inv(X.T@X);beta=inv@X.T@y;r=y-X@beta
        hc=len(y)/(len(y)-2)*inv@(X.T@(X*r[:,None]**2))@inv
        scores=np.array([X[d[:,0]==g].T@r[d[:,0]==g] for g in range(30)])
        cr=(30/29)*((len(y)-1)/(len(y)-2))*inv@(scores.T@scores)@inv
        np.testing.assert_allclose(model['estimate_vector'],beta,rtol=1e-11)
        np.testing.assert_allclose(model['covariance_matrices']['HC1'],hc,rtol=1e-11)
        np.testing.assert_allclose(model['covariance_matrices']['CR1_chooser'],cr,rtol=1e-11)
        contrasts=opportunity.linear_combinations(model,[('level_at_one',{'intercept':1,'x':1})])
        a=np.ones(2)
        self.assertAlmostEqual(contrasts[1]['se_pp'],np.sqrt(a@cr@a),places=9)
        unavailable=opportunity.linear_combinations(model,[('bad',{'absent':1})])
        self.assertTrue(all(r['status'].startswith('not_estimable') for r in unavailable));db.close()

    def test_03_rematch_missing_slots_and_resume(self):
        frame=pd.DataFrame([{'matched_kind_chooser_id':str(g),'control_slot':s,'is_kind_role':int(s==0),
            'match_cell':'a' if g%2 else 'b','patron':int((g+s)%7==0),'patron_pp':100*int((g+s)%7==0)}
            for g in range(16) for s in range(4) if not(g==3 and s==2)])
        for rep in range(1,101):
            sample=chooser.deterministic_rematch(frame,rep)
            selected=sample[sample.matched_kind_chooser_id=='3']
            slot=h.common.deterministic_control_slot('3',rep)
            self.assertEqual(len(selected),0 if slot==2 else 2)
            self.assertTrue((sample.groupby('matched_kind_chooser_id').is_kind_role.sum()==1).all())
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);public=root/'public';public.mkdir()
            with contextlib.redirect_stdout(io.StringIO()):
                result=families.rematches(frame,{'all':[],'standardize':[]},root,'fixture',public,replicates=2)
            before={p:str(p.stat().st_mtime_ns) for p in root.rglob('fit.json')}
            with contextlib.redirect_stdout(io.StringIO()):
                families.rematches(frame,{'all':[],'standardize':[]},root,'fixture',public,replicates=2)
            self.assertEqual(before,{p:str(p.stat().st_mtime_ns) for p in root.rglob('fit.json')})
            self.assertEqual(result['models'],4)
            target=next(root.rglob('fit.json'));target.write_text('{}')
            with self.assertRaises(RuntimeError),contextlib.redirect_stdout(io.StringIO()):
                families.rematches(frame,{'all':[],'standardize':[]},root,'fixture',public,replicates=2)

    def test_04_full_synthetic_families_and_dyad_join(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);state=root/'state';state.mkdir();args=SimpleNamespace(project_root=root,threads=2,hash_workers=2,memory_limit='1GB')
            panel,users=fixture.build_panel(groups=80)
            panel['ply_count']=np.tile([0,4,5,10,11,20,21,40,41,80,81,120],len(panel)//12)
            panel.loc[0,'ply_count']=np.nan
            panel['game_id']=['game_'+str(i) for i in range(len(panel))]
            ids={n:i+1 for i,n in enumerate(sorted(panel.chooser_username_norm.unique()))}
            panel['chooser_user_id']=panel.chooser_username_norm.map(ids)
            panel['disconnected_user_id']=np.arange(len(panel))+1000
            snapshot=fixture.build_snapshot(panel,users)
            snap=root/'snapshot.parquet';snapshot.to_parquet(snap,index=False)
            p=root/'panel.parquet';panel.to_parquet(p,index=False)
            db=duckdb.connect();db.execute("SET threads=2")
            design=root/'design.parquet';builder.build_cache(db,{'snapshot':snap,'stage07_glob':p},design)
            inputs=root/'cells.parquet';qa=opportunity.build_cache(db,[p],snap,inputs)
            expected=panel[panel.chooser_username_norm.isin(snapshot[snapshot.returned].username_norm)]
            self.assertEqual(qa['opportunities'],len(expected));self.assertEqual(qa['kind_draws'],int(expected.kind_draw.sum()))
            public=root/'post';public.mkdir()
            post=families.postcertification(db,design,snap,inputs,state,'fixture',public)
            self.assertEqual(post['five_bin_models'],7);self.assertEqual(post['price_count_rate_models'],10)
            for ply,expected_models in [(False,3),(True,12)]:
                public=root/('ply' if ply else 'opportunity');public.mkdir()
                summary=opportunity.fit_families(db,inputs,snap,state,'fixture',public,ply=ply)
                self.assertEqual(summary['models'],expected_models)
            # Verify the additional collapse dimension leaves original row-level models unchanged.
            db.execute(f"CREATE TABLE collapsed_without_ply AS SELECT * EXCLUDE(ply_band,opportunities,kind_draws),sum(opportunities) opportunities,sum(kind_draws) kind_draws FROM opportunity_analysis GROUP BY ALL")
            controls=original_op.control_terms(db,'opportunity_analysis')
            name,condition,primary=opportunity.model_specs()[0]
            m,c=extended_op.fit_collapsed_model(db,table='collapsed_without_ply',condition=condition,model_name='comparison',terms=controls+primary,primary_terms=[a for _,a in primary])
            saved=json.loads((root/'opportunity/opportunity_models_and_covariance.json').read_text())[0]
            np.testing.assert_allclose(m['estimate_vector'],saved['estimate_vector'],atol=1e-7,rtol=1e-8)
            np.testing.assert_allclose(m['covariance_matrices']['CR1_chooser'],saved['covariance_matrices']['CR1_chooser'],atol=1e-7,rtol=1e-7)
            # Exercise the actual flag producer and frozen rematching with a tiny invariant-index fixture.
            old=root/'derived/replication/frequent_dyad_census_24m_v101_PRIVATE';old.mkdir(parents=True)
            pairs=pd.DataFrame({'pair_bucket':0,'low_id':panel.chooser_user_id,'high_id':panel.disconnected_user_id,
                                'pair_games_24m':np.resize([1,2,4,8],len(panel))})
            pairs=pairs[pairs.pair_games_24m>=2]
            for i in range(128):
                dest=old/f'frequent_pairs/pair_bucket={i:03d}/part-00000.parquet';dest.parent.mkdir(parents=True)
                (pairs if i==0 else pairs.iloc[:0]).to_parquet(dest,index=False)
            pd.DataFrame({'player_id':sorted(ids.values()),'maximum_pair_games_24m':8}).to_parquet(old/'frequent_players_private.parquet',index=False)
            public=root/'dyad';public.mkdir()
            sample={'month_records':[{'path':p}], 'authority':{'rows':len(panel),'kind_draws':int(panel.kind_draw.sum()),'fair_rows':int(panel.fair_competitive.sum())}}
            with patch.object(dyad.dyad_auth,'authenticate_frequent_state',return_value={'fixture':True}):
                result=dyad.run(args,sample,snap,state,'fixture',public)
            self.assertEqual(result['restrictions'],4)
            db.close()

    def test_05_ply_boundaries_and_missing(self):
        db=duckdb.connect();d=pd.DataFrame({'ply_count':[np.nan,4,5,10,11,20,21,40,41,80,81]});db.register('p',d)
        values=[r[0] for r in db.execute('SELECT '+opportunity.PLY_CASE+' FROM p').fetchall()]
        self.assertEqual(values,['missing','00_04','05_10','05_10','11_20','11_20','21_40','21_40','41_80','41_80','81_plus']);db.close()

    def test_06_result_manifest_and_private_exclusion(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);state=root/'state';stage=state/'inputs';stage.mkdir(parents=True)
            (stage/'secret_private.parquet').write_bytes(b'PRIVATE_ROW')
            (stage/'INPUT_QA.json').write_text('{"rows": 10}')
            (stage/'CHECKPOINT.json').write_text('{}')
            args=SimpleNamespace(project_root=root,transfer_dir=root/'desktop')
            zpath=runner.collect(args,state,'x'*64,{'fixture':True},{'inputs':{'fixture':True}})
            import zipfile
            with zipfile.ZipFile(zpath) as z:
                self.assertFalse(any(n.endswith('.parquet') for n in z.namelist()))
                manifest=next(n for n in z.namelist() if n.endswith('REPORT_FILE_HASHES.tsv'))
                prefix=manifest.rsplit('/',1)[0]+'/'
                import csv
                for row in csv.DictReader(io.StringIO(z.read(manifest).decode()),delimiter='\t'):
                    self.assertEqual(hashlib.sha256(z.read(prefix+row['relative_path'])).hexdigest(),row['sha256'])

    def test_07_c9_lock_queue_and_duplicate_patron_rejection(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);base=root/'patron'
            c9=root/'derived/replication/pool_main_reanalysis_v100_PRIVATE/c9_fresh_v100/runner.lock'
            c9.parent.mkdir(parents=True)
            with c9.open('a+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                def release(seconds):
                    self.assertEqual(seconds,30)
                    fcntl.flock(lock,fcntl.LOCK_UN)
                with patch.object(runner.time,'sleep',side_effect=release) as wait:
                    with runner.exclusive_run(base,root):
                        self.assertEqual(wait.call_count,1)
                        with self.assertRaises(BlockingIOError): fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        with self.assertRaisesRegex(RuntimeError,'already running'):
                            with runner.exclusive_run(base,root): pass
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(lock,fcntl.LOCK_UN)

    def test_08_authenticated_wave3b1_catalogue_and_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            reference=Path(temp)
            runner.verify_prior_report(reference)
            path=reference/'chooser_models.json'
            # Reproduce the reported error without weakening the authority loader.
            with self.assertRaisesRegex(RuntimeError,'Expected a JSON object'):
                h.auth.load_json(path)
            models=families.load_reference_models(path)
            self.assertEqual(len(models),34)
            coefficients=pd.read_csv(reference/'chooser_coefficients.csv')
            for suffix in ['01_match_cell_fe_only_HC1','08_all_controls_HC1']:
                name='main_fair_kind_1to3_'+suffix
                selected=[m for m in models if m['model']==name]
                self.assertEqual(len(selected),1)
                model=selected[0]
                self.assertEqual(model['n'],851131)
                self.assertEqual(model['covariance'],'HC1')
                self.assertEqual(model['requested_regressors'][0],'is_kind_role')
                self.assertEqual(len(coefficients[(coefficients.model==name)&
                                                  (coefficients.variable=='is_kind_role')]),1)
            for invalid in [{}, {'models':models}, [], [None], [models[0],1]]:
                path.write_text(json.dumps(invalid),encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError,'nonempty JSON list of model objects'):
                    families.load_reference_models(path)

    def test_09_core_reproduction_from_frozen_writer_and_resume(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);state=root/'state';reference=root/'reference'
            panel,users=fixture.build_panel(groups=80)
            snapshot=fixture.build_snapshot(panel,users)
            panel_path=root/'panel.parquet';panel.to_parquet(panel_path,index=False)
            snapshot_path=root/'snapshot.parquet';snapshot.to_parquet(snapshot_path,index=False)
            db=duckdb.connect();db.execute('SET threads=2')
            try:
                design=root/'design.parquet'
                builder.build_cache(db,{'snapshot':snapshot_path,'stage07_glob':panel_path},design)
                support=builder.build_support_receipt(db,design)
                frame=h.load_frames(db,design,snapshot_path)
                # The frozen Wave3B1 producer writes the actual catalogue format.
                h.main_models(frame,state/'prior','fixture-prior',reference,support)
                with self.assertRaisesRegex(RuntimeError,'Expected a JSON object'):
                    h.auth.load_json(reference/'chooser_models.json')
                public=root/'public';public.mkdir()
                returned=families.returned_frame(db,design,snapshot_path)
                data,main,groups=families.core_reproduction(
                    returned,state/'new','fixture-new',reference,public)
                checks=json.loads((public/'CORE_REPRODUCTION.json').read_text())
                self.assertEqual(len(checks),2)
                self.assertTrue(all(c['status']=='REPRODUCED' and c['n']==len(main) for c in checks))
                before={p:p.stat().st_mtime_ns for p in (state/'new').rglob('fit.json')}
                self.assertEqual(len(before),2)
                families.core_reproduction(returned,state/'new','fixture-new',reference,public)
                self.assertEqual(before,{p:p.stat().st_mtime_ns for p in (state/'new').rglob('fit.json')})
                # Keep the numerical gate active: changing a reference estimate fails.
                path=reference/'chooser_coefficients.csv'
                coefficients=pd.read_csv(path)
                mask=(coefficients.model==checks[0]['model'])&(coefficients.variable=='is_kind_role')
                self.assertEqual(int(mask.sum()),1)
                coefficients.loc[mask,'coefficient_pp']+=1
                coefficients.to_csv(path,index=False)
                with self.assertRaisesRegex(RuntimeError,'coefficient_pp did not reproduce'):
                    families.core_reproduction(returned,state/'new','fixture-new',reference,public)
            finally:
                db.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
