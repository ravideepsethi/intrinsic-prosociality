import contextlib
import hashlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fast_bootstrap as c
import fast_chronology_merge as merge
import fast_chronology_parallel as parallel
from fast_digest_cache import DigestCache
import merge_v104_reference as prior
import test_chronology103 as fixture
import pyarrow as pa
import pyarrow.parquet as pq


def snapshot(root):
    return {p:(p.stat().st_mtime_ns,c.sha(p)) for p in Path(root).rglob('*')
            if p.is_file() and '.partial_' not in str(p) and 'spill' not in p.parts}


class Chronology105(unittest.TestCase):
    def setUp(self):
        self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__()

    def tearDown(self):self.silence.__exit__(None,None,None)

    def assert_snapshot(self, before):
        for p,old in before.items():self.assertEqual((p.stat().st_mtime_ns,c.sha(p)),old,str(p))

    def expected(self, q, prep, parts, root):
        out,_=prior.previous.merge_chronology(q,prep,parts,root,'unit',.5,1)
        return pq.read_table(out/'features.parquet').sort_by('row_id').to_pydict()

    def test_18gib_12cpu_policy_reserves_total_and_parallelizes(self):
        p=parallel.policy(4,workers=12,budget=13.5,cores=12)
        self.assertEqual((p['workers'],p['threads_per_worker']),(3,4))
        self.assertLessEqual(p['estimated_reserved_gib'],13.5)
        self.assertEqual(parallel.policy(4,workers=1,budget=13.5,cores=12)['workers'],1)
        self.assertEqual(parallel.policy(4,workers=12,budget=6,cores=12)['workers'],1)

    def test_partial_v104_resume_keeps_every_sealed_leaf_and_exact_order(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture.fixtures.fixture(root/'data')
            expected=self.expected(q,prep,parts,root/'expected');calls=[];original=prior.stage
            def interrupt(target,*args,**kwargs):
                if Path(target).parent.name=='classified':
                    calls.append(target)
                    if len(calls)==4:raise RuntimeError('simulated stop mid-group')
                return original(target,*args,**kwargs)
            with patch.object(prior,'stage',interrupt),self.assertRaisesRegex(RuntimeError,'simulated stop'):
                prior.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4,max_queries=1)
            before=snapshot(root/'merge');built=[];build=parallel.build_leaf
            def spy(*args):built.append((args[3],args[4]));return build(*args)
            with patch.object(merge,'partition_scan_files',side_effect=AssertionError('Must reuse partitions')),patch.object(parallel,'build_leaf',spy):
                out,stats=merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4,max_queries=1)
            self.assertEqual(len(built),5);self.assertEqual(stats['reused_classification_leaves'],3)
            self.assertEqual(pq.read_table(out/'features.parquet').to_pydict(),expected)
            self.assert_snapshot(before)
            after=snapshot(root/'merge')
            with patch.object(parallel,'prepare_candidates',side_effect=AssertionError('Complete merge must not reread candidates')):
                merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4,max_queries=100)
            self.assert_snapshot(after)

    def test_complete_v104_checkpoints_are_reused_without_classification(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture.fixtures.fixture(root/'data')
            out,_=prior.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4,max_queries=1)
            before=snapshot(root/'merge')
            with patch.object(parallel,'classify_bucket',side_effect=AssertionError('Completed work must not rerun')):
                got,_=merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)
            self.assertEqual(got,out);self.assert_snapshot(before)

    def test_parallel_connections_produce_frozen_results(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture.fixtures.fixture(root/'data')
            expected=self.expected(q,prep,parts,root/'expected')
            barrier=threading.Barrier(3);guard=threading.Lock();thread_ids=set();calls=[]
            prepare=parallel.prepare_candidates
            def concurrent(conn,plan):
                with guard:
                    calls.append(1);ordinal=len(calls);thread_ids.add(threading.get_ident())
                if ordinal<=3:barrier.wait(timeout=15)
                return prepare(conn,plan)
            resources=parallel.policy(.5,workers=3,budget=13.5,cores=6)
            with patch.object(parallel,'policy',return_value=resources),patch.object(parallel,'prepare_candidates',concurrent):
                out,stats=merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4,max_queries=1)
            self.assertGreaterEqual(len(thread_ids),3);self.assertEqual(len(calls),4)
            self.assertEqual(stats['workers'],3)
            self.assertEqual(pq.read_table(out/'features.parquet').to_pydict(),expected)

    def test_memory_retry_seals_children_and_reuses_old_oom_descendants(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture.fixtures.fixture(root/'data')
            expected=self.expected(q,prep,parts,root/'expected');original=prior.previous.rebuild.adjacency_final_sql
            calls=[]
            def once(*args):
                calls.append(1)
                if len(calls)==1:raise prior.duckdb.OutOfMemoryException('test old OOM')
                return original(*args)
            with patch.object(prior.previous.rebuild,'adjacency_final_sql',once):
                prior.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=2)
            before=snapshot(root/'merge')
            with patch.object(parallel,'prepare_candidates',side_effect=AssertionError('Old smaller leaves must reuse')):
                out,_=merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=2)
            self.assertEqual(pq.read_table(out/'features.parquet').to_pydict(),expected);self.assert_snapshot(before)
            build=parallel.build_leaf;failed=[]
            def fail_leaf(*args):
                if args[3]==2 and not failed:
                    failed.append(1);raise prior.duckdb.OutOfMemoryException('test new OOM')
                return build(*args)
            with patch.object(parallel,'build_leaf',fail_leaf):
                new,stats=merge.bounded_merge(q,parts,root/'new','unit',memory=.5,buckets=2)
            self.assertGreater(stats['leaf_groups'],2)
            self.assertEqual(pq.read_table(new/'features.parquet').to_pydict(),expected)

    def test_materialization_oom_falls_back_to_bounded_reads(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture.fixtures.fixture(root/'data')
            expected=self.expected(q,prep,parts,root/'expected')
            with patch.object(parallel,'prepare_candidates',side_effect=prior.duckdb.OutOfMemoryException('test table spill')):
                out,stats=merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4,max_queries=1)
            self.assertEqual(stats['bounded_read_fallback_groups'],4)
            self.assertEqual(pq.read_table(out/'features.parquet').to_pydict(),expected)

    def test_completed_scan_reuse_never_calls_raw_producer_and_rejects_source_change(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,job,_,_=fixture.raw_fixture(root)
            before=snapshot(Path(job['output']))
            with patch.object(parallel,'mapped',side_effect=AssertionError('No new raw scan')):
                parallel.resume_scans([job],3)
            self.assert_snapshot(before)
            os.utime(job['path'],ns=(Path(job['path']).stat().st_atime_ns,Path(job['path']).stat().st_mtime_ns+1000000))
            with self.assertRaisesRegex(RuntimeError,'Chronology changed'):parallel.resume_scans([job],3)

    def test_same_size_tampered_sealed_leaf_is_rejected_after_previous_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture.fixtures.fixture(root/'data')
            merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)
            target=next((root/'merge/classified').glob('*/features.parquet'));stamp=target.stat()
            data=bytearray(target.read_bytes());data[12]^=1;target.write_bytes(data)
            os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            with self.assertRaisesRegex(RuntimeError,'checksum changed'):
                merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)

    def test_large_unsigned_ids_and_missing_candidate_bucket(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture.fixtures.fixture(root/'data')
            def shift(path,name,drop=False):
                t=pq.ParquetFile(path).read()
                if drop:t=t.filter(pa.compute.not_equal(t[name],100))
                ids=pa.array([int(x)+2**63 for x in t[name].to_pylist()],type=pa.uint64())
                t=t.set_column(t.schema.get_field_index(name),name,ids);pq.write_table(t,path)
            shift(q,'row_id')
            for part in parts:shift(part/'candidates.parquet','sample_row',True)
            expected=self.expected(q,prep,parts,root/'expected')
            out,_=merge.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=128)
            self.assertEqual(pq.read_table(out/'features.parquet').to_pydict(),expected)


class Digest105(unittest.TestCase):
    def test_concurrent_same_file_hashes_once_and_ctime_invalidates_preserved_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'data';p.write_bytes(b'aaaa');calls=[]
            def digest(path):calls.append(path);return hashlib.sha256(path.read_bytes()).hexdigest()
            cache=DigestCache(digest)
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(cache,[p]*24))
            self.assertEqual(len(calls),1);self.assertEqual(len(set(results)),1)
            before=p.stat();p.write_bytes(b'bbbb');os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
            self.assertNotEqual(cache(p),results[0]);self.assertEqual(len(calls),2)

    def test_mutation_during_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'data';p.write_bytes(b'aaaa')
            def changing(path):
                result=hashlib.sha256(path.read_bytes()).hexdigest();path.write_bytes(b'bbbb');return result
            with self.assertRaisesRegex(RuntimeError,'changed while hashing'):DigestCache(changing)(p)


if __name__=='__main__':unittest.main()
