import sys,tempfile,unittest,contextlib
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from phase50_common import *
import phase50_models as model
import phase50_inputs as inputs
import phase50_report as report
sys.path.insert(0,str(UPSTREAM/'tests'))
from test_phase_analysis import entry_model
from performance_runtime import Runtime

class ModelTests(unittest.TestCase):
    def data(self):
        d=entry_model(4000);rng=np.random.default_rng(12)
        d.update(comp_adjusted_7d=d['adjusted_7d']+rng.normal(0,.03,4000),comp_n_7d=np.full(4000,8),comp_expected_7d=rng.uniform(.01,.05,4000),comp_counterparts_7d=np.full(4000,7))
        previous=np.ones(4000,bool)
        for k in ENTRY_COLUMNS:
            previous=previous & (rng.random(4000)<.7);d[k]=previous.copy()
        # The estimator uses four fields; the Parquet contract also carries all score audit fields.
        for k in SCORE_COLS:
            if 'comp_'+k not in d:d['comp_'+k]=d[k].copy()
        return d

    def test_projected_primary_checked_solver_matches_legacy(self):
        d=self.data()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'input.parquet';io.table(src,pa.table(d))
            for family in SPECS:
                want=stats.estimate(d,SPECS[family])['estimates']
                job=dict(sample=str(src),family=family,cohort='test',conf='test',output=str(root/'models'/family))
                model.primary_job(job);got=io.load(Path(job['output'])/'result.json')
                self.assertTrue(got['numerics']);self.assertEqual(got['numerics'][0]['status'],'CONVERGED')
                for a,b in zip(want,got['estimates']):
                    self.assertEqual(a['events'],b['events']);self.assertAlmostEqual(a['coefficient_pp'],b['coefficient_pp'],9);self.assertAlmostEqual(a['standard_error_pp'],b['standard_error_pp'],9)
                with mock.patch.object(stats,'estimate',side_effect=AssertionError('must reuse')):model.primary_job(job)

    def test_real_spawned_competitive_fits_and_memory_gate(self):
        d=self.data()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'input.parquet';io.table(src,pa.table(d));runtime=Runtime(root)
            job=dict(input=str(src),family='XC',tail='all_supported',cutoff=.13,cohort='test',conf='test',memory_estimate_gb=.9,output=str(root/'secondary_models/test'))
            model.fit_map(model.secondary_job,[job],runtime,2,4,'synthetic spawned fit',lambda:None)
            rows=io.load(Path(job['output'])/'result.json')['estimates']
            self.assertEqual(len(rows),4)
            with self.assertRaisesRegex(RuntimeError,'budget'):
                model.fit_map(model.secondary_job,[dict(job,memory_estimate_gb=20)],runtime,2,4,'too large',lambda:None)
            new=dict(job,output=str(root/'entry_comp_models/test'))
            model.fit_map(model.entry_comp_job,[new],runtime,2,4,'synthetic spawned entry',lambda:None)
            self.assertTrue(io.load(Path(new['output'])/'result.json')['estimates'])

    def test_checked_solver_rejects_nonfinite_and_retains_legacy_function(self):
        before=num.absorb
        with self.assertRaises(RuntimeError):
            with model.checked_solver():num.absorb(np.array([[1.,np.nan],[2.,3.]]),[np.array([1,1])])
        self.assertIs(before,num.absorb)

    def test_tail_cutoff_is_frozen_and_parquet_is_projected(self):
        d=self.data();n=len(d['row_id'])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);split=root/'split'
            scores={'row_id':d['row_id'],**{k:d[k] for k in model.entry_common.COMP_COLUMNS}}
            sp=root/'scores.parquet';io.table(sp,pa.table(scores))
            base={k:v for k,v in d.items() if k not in model.entry_common.COMP_COLUMNS}
            base['unused_large_string']=['do_not_load']*n
            for c in COHORTS:io.table(split/('ordinary_'+c+'.parquet'),pa.table(base))
            out,info=model.competitive_prepare(split,[sp],root/'prepared','test',.5,'ordinary')
            frozen=io.load(ENTRY/'evidence/secondary_scale.json')['upper_5pct_raw_competitive_cutoff']
            self.assertEqual(info['tail_cutoff'],frozen)
            self.assertNotIn('unused_large_string',pq.ParquetFile(out/'new_phase50.parquet').schema_arrow.names)
            self.assertEqual(pq.ParquetFile(out/'new_phase50.parquet').metadata.num_rows,n)

    def test_original_cache_definition_unchanged(self):
        import entry_common,checkpoint_secondary
        modules=[UPSTREAM/'code'/x for x in ('performance_histories.py','performance_cache.py')]
        # Definitions use file contents/name, never extraction path or phase label.
        a=model.cache.definition('fixture',dict(value=1),modules)
        b=model.cache.definition('fixture',dict(value=1),[Path(checkpoint_secondary.__file__).parent/x.name for x in modules])
        self.assertEqual(a,b)

if __name__=='__main__':unittest.main()
