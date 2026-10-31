"""Exercise the production-scale failure mode: interleaved buckets and file growth."""
import unittest,tempfile,sys
from pathlib import Path
import fcntl
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
import repair_chronology as repair


class PartitionWriter(unittest.TestCase):
    def test_prior_active_runner_blocks_new_run_until_stopped(self):
        import run_rebuild
        with tempfile.TemporaryDirectory() as td:
            project=Path(td);old=project/'derived/replication/alltime_entry_placebo_v101_PRIVATE/old'
            current=project/'derived/replication/alltime_entry_placebo_v102_PRIVATE/new'
            old.mkdir(parents=True);current.mkdir(parents=True)
            with (old/'RUN.lock').open('a+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError,'still active'):
                    with run_rebuild.prior_runs_stopped(project,current):self.fail('Concurrent old run was allowed')
            with run_rebuild.prior_runs_stopped(project,current):pass

    def test_interleaved_rows_have_bounded_files_and_preserve_every_field(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=connection(root,.4)
            try:
                # More than one read batch, 128 interleaved buckets, duplicates,
                # nullable strings/integers and unsigned pair keys.
                c.execute('''CREATE TABLE original AS SELECT i%70001 AS row_id,
                    i%128 AS bucket, (4294967296::UBIGINT*(i%100000)+i)::UBIGINT AS pair_key,
                    CASE WHEN i%7=0 THEN NULL ELSE 'game_'||i::VARCHAR END AS game_id,
                    CASE WHEN i%3=0 THEN NULL ELSE i%10 END AS prev_t,
                    i%2=0 AS eligible FROM range(150000) t(i)''')
                info=repair.partition(c,'SELECT * FROM original',root/'parts',expected_rows=150000,
                    batch_rows=4096,group_rows=2048,buffer_bytes=1024*1024)
                paths=sorted((root/'parts').rglob('*.parquet'))
                self.assertEqual(len(paths),128)
                self.assertTrue(all(p.name=='data.parquet' for p in paths))
                self.assertEqual(info['rows'],150000)
                self.assertLessEqual(info['peak_buffered_arrow_bytes'],1024*1024+32768)
                c.execute('CREATE VIEW actual AS SELECT * FROM '+parq(paths))
                fields='row_id,pair_key,game_id,prev_t,eligible'
                sql=f'SELECT count(*) FROM ((SELECT {fields} FROM original EXCEPT ALL SELECT {fields} FROM actual) UNION ALL (SELECT {fields} FROM actual EXCEPT ALL SELECT {fields} FROM original))'
                self.assertEqual(c.execute(sql).fetchone()[0],0)
                for path in paths:
                    k=int(path.parent.name.split('=')[1]);t=pq.ParquetFile(path).read()
                    self.assertEqual(t.num_rows,info['bucket_rows'][str(k)])
                    # pair_key contains the original unaliased i in this fixture.
                    self.assertTrue(all((v%4294967296)%128==k for v in t['pair_key'].to_pylist()))
            finally:c.close()

    def test_sparse_empty_and_invalid_buckets(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=connection(root,.4)
            try:
                info=repair.partition(c,'SELECT 2 AS bucket,1 AS value WHERE FALSE',root/'empty',expected_rows=0)
                self.assertEqual((info['rows'],info['output_files']),(0,0))
                info=repair.partition(c,'SELECT 127 AS bucket,i AS value FROM range(10000) t(i)',root/'skew',expected_rows=10000,
                    group_rows=30,batch_rows=32,buffer_bytes=256)
                self.assertEqual(info['output_files'],1)
                self.assertEqual(pq.ParquetFile(root/'skew/bucket=127/data.parquet').metadata.num_rows,10000)
                for tag,expr in [('null','NULL::BIGINT'),('negative','-1'),('overflow','128')]:
                    with self.assertRaisesRegex(RuntimeError,'bucket'):
                        repair.partition(c,f'SELECT {expr} AS bucket,1 AS value',root/tag)
            finally:c.close()

    def test_wrong_input_count_cannot_seal_and_restart_rebuilds_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/'saved'
            def build(tmp,expected=10):
                c=connection(tmp,.4)
                try:return repair.partition(c,'SELECT i%2 AS bucket,i AS value FROM range(9) t(i)',tmp/'parts',expected_rows=expected)
                finally:c.close()
            with self.assertRaisesRegex(RuntimeError,'row count changed'):
                stage(out,'unit',build)
            self.assertFalse((out/'_DONE.json').exists())
            saved,info=stage(out,'unit',lambda tmp:build(tmp,9))
            self.assertEqual(info['rows'],9)
            stamp=(saved/'parts/bucket=0/data.parquet').stat().st_mtime_ns
            stage(out,'unit',lambda tmp:self.fail('Complete checkpoint was recomputed'))
            self.assertEqual((saved/'parts/bucket=0/data.parquet').stat().st_mtime_ns,stamp)


if __name__=='__main__':unittest.main()
