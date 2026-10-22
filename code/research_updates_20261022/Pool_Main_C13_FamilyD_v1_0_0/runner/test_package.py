from __future__ import annotations
import ast
import contextlib
import hashlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from runner import bind,common,family_d,models,pipeline,run


def fixture(path,users=180,days=40):
    rng=np.random.default_rng(240911)
    user=np.repeat(np.arange(users),days);day=np.tile(np.arange(days),users)
    n=len(user);band=(user//9+day//7)%4;speed=(user+day)%2
    rating=np.array([1400,1800,2200,2500])[band]+rng.uniform(-25,25,n)
    probability=.10+.06*np.sin(day/5)+.03*speed+.01*band
    kind=(rng.random(n)<probability).astype(np.int64)
    rows={'game_id':np.array([f'g{i:08d}' for i in range(n)]),
          'chooser_user_id':user.astype(np.int64),'chooser_username_norm':np.array([f'u{x}' for x in user]),
          'api_last_move_at_ms':1698796800000+day*86400000+(user%24)*3600000,
          'api_speed':np.where(speed==0,'blitz','rapid'),'chooser_elo':rating,
          'disconnected_elo':rating+rng.normal(0,150,n),'fair_competitive':np.ones(n,dtype=bool),
          'engine_eval_cp_disconnected':rng.choice([-80,0,80,300],n),
          'tournament_like_event':np.zeros(n,dtype=bool),'chooser_draw_payoff_v2':rng.normal(0,1,n),
          'chooser_win_premium_v2':rng.uniform(2,15,n),'chooser_clock_last_obs_s':rng.uniform(3,60,n),
          'disconnected_clock_last_obs_s':rng.uniform(5,60,n),'chooser_pre_rd_v2':rng.uniform(30,100,n),
          'disconnected_pre_rd_v2':rng.uniform(30,100,n),'outcome_kind_draw':kind}
    pq.write_table(pa.table(rows),path,compression='zstd')
    return n,int(kind.sum())


def bound_fixture(root,users=180,days=40):
    root.mkdir(parents=True,exist_ok=True)
    source=root/'panel.parquet';n,k=fixture(source,users,days)
    rendered,receipt=bind.render(fair_rows=n,fair_kind=k,all_rows=n,all_kind=k)
    c13,shared=bind.load_rendered(root/'execution',rendered)
    # A small fixture needs a scaled support threshold; the production constant stays 5000.
    c13.SUPPORT_THRESHOLD=5
    return c13,source,n,k


class Tests(unittest.TestCase):
    def test_01_original_source_self_tests_and_binding_only_changes_support_checks(self):
        original=bind.ROOT/'source'
        rendered={name:(original/name).read_text() for name in ('campaign1_c13_v104.py','campaign1_nonprofile_common_v102.py')}
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            c13,shared=bind.load_rendered(Path(tmp),rendered)
            shared.self_test();c13.self_test()
        new,receipt=bind.render()
        def bodies(text):
            return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
        for name in rendered:
            before=bodies(rendered[name]);after=bodies(new[name])
            differences={key for key in before if before[key]!=after[key]}
            self.assertEqual(differences,{'build_support_cache'} if name=='campaign1_c13_v104.py' else set())
        self.assertFalse(receipt['support_SQL_changed'])
        self.assertIn('EXPECTED_FAIR_ROWS = 15207423',new['campaign1_c13_v104.py'])
        self.assertIn('SUPPORT_THRESHOLD = 5_000',new['campaign1_c13_v104.py'])

    def test_02_real_family_sources_and_missing_members(self):
        table,receipt=family_d.reconcile()
        rows={r['member']:r for r in table}
        self.assertEqual(set(rows),{'C1','C2','C5','C6','C9'})
        self.assertEqual(receipt['missing_current_authorities'],['C1','C2','C5'])
        self.assertEqual(receipt['guaranteed_rejections'],['C6','C9'])
        self.assertAlmostEqual(rows['C6']['p_holm_conservative_upper_bound'],5*1.6653539481830944e-6)
        self.assertAlmostEqual(rows['C9']['p_holm_conservative_upper_bound'],.0016)
        for key in ('C1','C2','C5'):
            self.assertIsNone(rows[key]['p_raw_observed'])
            self.assertFalse(rows[key]['final_exact_Holm_p_available'])
        self.assertFalse(receipt['old_sample_p_values_used'])

    def test_03_holm_ties_cumulative_max_and_all_missing_completions(self):
        p={'C1':.01,'C2':.03,'C5':.04,'C6':.2,'C9':1.}
        r=family_d.holm(p)
        self.assertEqual([round(r[k]['adjusted_p'],8) for k in p],[.05,.12,.12,.4,1.])
        p={k:.01 for k in family_d.MEMBERS}
        self.assertTrue(all(abs(v['adjusted_p']-.05)<1e-12 for v in family_d.holm(p).values()))
        known={'C6':1.6653539481830944e-6,'C9':.0004}
        lower=family_d.holm({k:known.get(k,0.) for k in family_d.MEMBERS})
        upper=family_d.holm({k:known.get(k,1.) for k in family_d.MEMBERS})
        for values in itertools.product([0.,1e-7,.0002,.01,.2,1.],repeat=3):
            completed=family_d.holm({**known,**dict(zip(('C1','C2','C5'),values))})
            for key in known:
                self.assertLessEqual(lower[key]['adjusted_p'],completed[key]['adjusted_p'])
                self.assertGreaterEqual(upper[key]['adjusted_p'],completed[key]['adjusted_p'])
        with self.assertRaises(RuntimeError): family_d.holm({'C6':.01,'C9':.02})
        with self.assertRaises(RuntimeError): family_d.holm({k:float('nan') for k in family_d.MEMBERS})

    def test_04_lagged_leave_chooser_out_SQL_matches_independent_oracle(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);c13,source,n,k=bound_fixture(root,users=12,days=65)
            state=root/'state';state.mkdir()
            kw={'state':state,'threads':2,'memory_limit':'512MB','config_sha256':'a'*64}
            base,_=c13.build_base(stage07_paths=[source],**kw)
            daily=c13.build_daily_denominators(base=base,**kw)
            support,receipt=c13.build_support_cache(base=base,daily=daily,**kw)
            gate=pipeline.validate_support(c13,state,'a'*64,receipt)
            self.assertEqual(gate['primary_supported_rows'],receipt['primary_supported_rows'])
            self.assertFalse((state/'c13_kind_events_private.parquet').exists())
            kind=c13.build_kind_events(base=base,stage07_paths=[source],**kw)
            daily_k=c13.build_daily_kind(kind_events=kind,**kw)
            model=c13.build_model_cache(support=support,kind_events=kind,daily_kind=daily_k,**kw)
            frame=pq.ParquetFile(model).read().to_pydict()
            day=np.asarray(frame['decision_day_index']);who=np.asarray(frame['loo_chooser'])
            speed=np.asarray(frame['speed_code']);band=np.asarray(frame['chooser_rating_band']);y=np.asarray(frame['kind'])
            for i in range(n):
                other=(who!=who[i])&(speed==speed[i])
                for prefix,match in [('cell',other&(band==band[i])),('speed',other)]:
                    for length in (14,28,56):
                        mask=match&(day>=day[i]-length)&(day<=day[i]-1)
                        self.assertEqual(frame[f'{prefix}_other_n{length}'][i],int(mask.sum()))
                        self.assertEqual(frame[f'{prefix}_other_k{length}'][i],int(y[mask].sum()))
                        rate=frame[f'ambient_{prefix}_{length}'][i]
                        if mask.any(): self.assertAlmostEqual(rate,float(y[mask].mean()))
                        else: self.assertIsNone(rate)
                mask=other&(band==band[i])&(day>=day[i]-35)&(day<=day[i]-8)
                self.assertEqual(frame['cell_other_n28_washout7'][i],int(mask.sum()))
                self.assertEqual(frame['cell_other_k28_washout7'][i],int(y[mask].sum()))

    def test_05_full_family_reproduces_original_and_resumes_without_refitting(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);c13,source,n,k=bound_fixture(root)
            private=root/'state';public=root/'public';digest='c'*64
            original_kind=c13.build_kind_events
            def guarded_kind(**kwargs):
                gate=common.load_json(kwargs['state']/'C13_SUPPORT_GATE.json')
                self.assertEqual(gate['config_sha256'],digest)
                self.assertTrue((kwargs['state']/'NUMERATOR_READ_AUTHORIZATION.json').exists())
                return original_kind(**kwargs)
            with patch.object(c13,'build_kind_events',side_effect=guarded_kind):
                summary=pipeline.execute(c13,[source],private,public,digest,2,'512MB')
            self.assertEqual(summary['model_attempts_total'],19)
            self.assertTrue(summary['primary_estimable'])
            wrapped=common.load_json(public/'c13_results.json')
            frozen=c13.estimate(private/'c13_model_private.parquet')
            self.assertEqual(wrapped,frozen)
            paths=list((private/'model_checkpoints').glob('*.json'))
            self.assertEqual(len(paths),19)
            mtimes={p:p.stat().st_mtime_ns for p in paths}
            with patch.object(c13,'_fit',side_effect=AssertionError('Unexpected refit')):
                again=pipeline.execute(c13,[source],private,public,digest,2,'512MB')
            self.assertEqual(summary,again)
            self.assertEqual(mtimes,{p:p.stat().st_mtime_ns for p in paths})
            table,receipt=family_d.reconcile();run.family_files(public,table,receipt)
            run.seal(public,{'status':'SYNTHETIC_VALIDATION_ONLY'},digest)
            run.verify_public(public)
            self.assertFalse(any(p.suffix in ('.parquet','.npz','.npy') for p in public.rglob('*')))
            a=paths[0];record=common.load_json(a);record['result_sha256']='0'*64;common.atomic_json(a,record)
            with self.assertRaisesRegex(RuntimeError,'content hash mismatch'):
                models.estimate(c13,private/'c13_model_private.parquet',private/'model_checkpoints',digest,
                                common.load_json(private/'c13_model_receipt.json')['output_sha256'])

    def test_06_support_gate_and_interrupted_checkpoints_fail_safely(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);c13,source,n,k=bound_fixture(root,users=12,days=12)
            state=root/'state';state.mkdir()
            kw={'state':state,'threads':1,'memory_limit':'512MB','config_sha256':'d'*64}
            base,_=c13.build_base(stage07_paths=[source],**kw)
            daily=c13.build_daily_denominators(base=base,**kw)
            support,receipt=c13.build_support_cache(base=base,daily=daily,**kw)
            with self.assertRaisesRegex(RuntimeError,'not frozen'):
                pipeline.validate_support(c13,state,'d'*64,{**receipt,'ambient_kindness_numerator_read':True})
            with self.assertRaisesRegex(RuntimeError,'checkpoint mismatch'):
                c13.build_base(stage07_paths=[source],**{**kw,'config_sha256':'e'*64})
            one=state/'c13_kind_events_private.parquet';one.write_bytes(b'incomplete')
            moved=pipeline.preserve_incomplete(state)
            self.assertEqual(len(moved),1);self.assertFalse(one.exists())
            self.assertEqual((Path(moved[0]['preserved_at'])/one.name).read_bytes(),b'incomplete')

    def test_07_duplicate_and_shared_compute_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)
            with run.exclusive(project):
                with self.assertRaisesRegex(RuntimeError,'already running'):
                    with run.exclusive(project): pass
            shared=project/'derived/replication/pool_main_reanalysis_v100_PRIVATE/c9_fresh_v100/runner.lock'
            with shared.open('a+') as handle:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(run.time,'sleep',side_effect=RuntimeError('queue observed')):
                    with self.assertRaisesRegex(RuntimeError,'queue observed'):
                        with run.exclusive(project): pass


if __name__=='__main__': unittest.main()
