import tempfile, unittest
from fixture import *
from runner import execute, prepare
from run import archive


class PipelineTests(unittest.TestCase):
    def test_synthetic_pipeline_restart_privacy_and_checksum_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, work, ref, d = cache(tmp)
            public = work / 'public_results'
            first = execute(source, work, public, ref, 'SYNTHETIC_TEST_ONLY', threads=1, memory_mb=256, reps=1000)
            self.assertEqual(first['status'], 'PRE_POLICY_TRANSPORT_COMPLETE_POST_POLICY_TEST_OPEN')
            self.assertFalse(first['post_policy_outcomes_read'])
            self.assertEqual(first['fixed_fit_snapshots'], 16)
            original_inputs = {p: sha(p) for p in (source / 'analysis').glob('*.parquet')}
            job_hashes = {p: sha(p) for p in (work / 'jobs').glob('*.json')}
            second = execute(source, work, public, ref, 'SYNTHETIC_TEST_ONLY', threads=1, memory_mb=256, reps=1000)
            self.assertEqual(first, second)
            self.assertEqual(original_inputs, {p: sha(p) for p in original_inputs})
            self.assertEqual(job_hashes, {p: sha(p) for p in job_hashes})
            monthly = pd.read_csv(public / 'monthly_support.csv')
            self.assertEqual(int(monthly.grants.sum()), int(d.y.sum()))
            for p in public.glob('*.csv'):
                columns = pd.read_csv(p).columns
                self.assertFalse({'chooser', 'game_id', 'opponent'} & set(columns), p.name)
                self.assertNotIn('chooser_0,', p.read_text())
            p = pd.read_csv(public / 'pairwise_power.csv')
            self.assertTrue(len(p) > 0)
            self.assertTrue(p.conditional_planning_power.between(0, 1).all())
            self.assertFalse(p.actual_frozen_post_cohort.any())
            archive(public, Path(tmp) / 'project', Path(tmp) / 'desktop')
            self.assertEqual(len(list((Path(tmp) / 'desktop').glob('*.zip'))), 1)
            # A changed authenticated monthly file must fail before interpretation.
            corrupted = next(iter(original_inputs))
            with corrupted.open('ab') as f:
                f.write(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'size'):
                prepare(source, work, ref, threads=1, memory_mb=256)


if __name__ == '__main__':
    unittest.main()
