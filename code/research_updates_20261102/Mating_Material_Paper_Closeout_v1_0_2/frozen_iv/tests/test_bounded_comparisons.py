"""Exact SQL oracles, fault injection, and restart checks for the OOM repair."""
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'code'))
from bootstrap import *
import bounded_comparisons as bc
import resume_guard


class BoundedComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.run = self.root/'run'; self.conf = c.key('synthetic chronology repair')
    def tearDown(self): self.temp.cleanup()
    def file(self, name, data):
        p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table(data), p, row_group_size=3)
        return p
    def queries(self, name, ids):
        ids = np.asarray(ids, dtype=np.int64)
        return self.file(name, dict(row_id=ids, game_id=pa.array(['g'+str(i) for i in ids], type=pa.string()),
             recipient_id=ids%3, opponent_id=ids%5+10, archive_start_ms=ids+10000,
             payload=pa.array(['x'+str(i) for i in ids], type=pa.string())))
    def facts(self, name, ids):
        ids = np.asarray(ids, dtype=np.int64)
        return self.file(name, dict(row_id=ids, eligible_main=ids%3!=0,
                         first_observed_pair=ids%4!=0, prior_t=ids-7))
    def data(self):
        # Removal, addition, empty gaps, and boundaries; input order may differ.
        q = self.queries('q.parquet', [100,101,102,105,109,110,120,121])
        oq = self.queries('oq.parquet', [121,120,110,109,105,102,100,99])
        ox = self.facts('ox.parquet', [99,100,102,105,109,110,120,121])
        return q, oq, ox
    def oracle(self, sql, sources, target):
        db = connect(self.root/'oracle')
        try:
            for name, source in sources.items(): view(db, name, source)
            copy(db, sql, target)
        finally: db.close()
    def equal(self, a, b):
        self.assertTrue(pq.read_table(a).equals(pq.read_table(b)), (a,b))

    def test_reuse_and_eligibility_exact_original_SQL(self):
        q, oq, ox = self.data()
        out, info = bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5,memory=.3)
        self.assertEqual({k:info[k] for k in ('rows','reused','missing')},dict(rows=8,reused=7,missing=1))
        self.oracle('SELECT q.row_id,ox.* EXCLUDE(row_id) FROM q JOIN oq USING(row_id) JOIN ox USING(row_id) ORDER BY row_id',
                    dict(q=q,oq=oq,ox=ox),self.root/'want_hits.parquet')
        self.oracle('SELECT q.* FROM q ANTI JOIN oq USING(row_id) ORDER BY row_id',
                    dict(q=q,oq=oq),self.root/'want_missing.parquet')
        self.equal(out/'hits.parquet',self.root/'want_hits.parquet')
        self.equal(out/'missing.parquet',self.root/'want_missing.parquet')
        new = self.facts('new.parquet',[101]); parts=[out/'hits.parquet',new]
        final,meta=bc.eligible_queries(self.run,self.conf,q,parts,width=5,memory=.3)
        self.oracle('SELECT q.*,x.* EXCLUDE(row_id) FROM q JOIN x USING(row_id) WHERE eligible_main AND first_observed_pair ORDER BY row_id',
                    dict(q=q,x=parts),self.root/'want_eligible.parquet')
        self.equal(final/'queries.parquet',self.root/'want_eligible.parquet')
        self.assertEqual(meta['rows'],rows(self.root/'want_eligible.parquet'))

    def test_identity_mismatch_blocks_reuse(self):
        q,oq,ox=self.data(); t=pq.read_table(oq).to_pydict();t['game_id'][0]='wrong'
        self.file('oq.parquet',t)
        with self.assertRaisesRegex(RuntimeError,'identity/history/outcome mismatch'):
            bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5)
        self.assertFalse((self.run/'PRIVATE/chronology_plan90/_DONE.json').exists())

    def test_missing_extra_and_duplicate_old_features_block(self):
        for label,ids in [('missing',[100]),('extra',[99,100,102,105,109,110,120,121,180]),
                          ('duplicate',[99,100,102,105,109,110,120,121,121])]:
            with self.subTest(label=label):
                q,oq,_=self.data();ox=self.facts(label+'.parquet',ids)
                with self.assertRaises(RuntimeError):bc.reuse_plan(self.root/label,self.conf,q,oq,ox,width=5)

    def test_duplicate_queries_and_null_keys_block(self):
        q,oq,ox=self.data()
        bad=self.queries('duplicate_q.parquet',[100,100])
        with self.assertRaisesRegex(RuntimeError,'Duplicate row IDs'):
            bc.reuse_plan(self.root/'dup',self.conf,bad,oq,ox,width=5)
        bad=self.file('null_q.parquet',dict(row_id=pa.array([100,None],type=pa.int64())))
        with self.assertRaisesRegex(RuntimeError,'Null chronology row IDs'):
            bc.reuse_plan(self.root/'null',self.conf,bad,oq,ox,width=5)

    def test_final_exact_coverage_checks_old_only_ranges(self):
        q=self.queries('q.parquet',[100,101])
        for label,ids in [('missing',[100]),('extra',[100,101,150]),('duplicate',[100,101,101])]:
            with self.subTest(label=label):
                facts=self.facts(label+'.parquet',ids)
                with self.assertRaises(RuntimeError):
                    bc.eligible_queries(self.root/label,self.conf,q,[facts],width=5)

    def test_empty_frames_and_no_reuse_keep_typed_schema(self):
        for empty in (True,False):
            q=self.queries('q.parquet',[] if empty else [100,101])
            oq=self.queries('oq.parquet',[]);ox=self.facts('ox.parquet',[])
            out,info=bc.reuse_plan(self.root/str(empty),self.conf,q,oq,ox,width=5)
            self.assertEqual({k:info[k] for k in ('rows','reused','missing')},dict(rows=0 if empty else 2,reused=0,missing=0 if empty else 2))
            self.assertEqual(pq.ParquetFile(out/'hits.parquet').schema_arrow,pq.ParquetFile(ox).schema_arrow)
            self.equal(out/'missing.parquet',q)

    def test_chunk_resume_after_assembly_failure(self):
        q,oq,ox=self.data()
        with patch.object(bc,'append_sorted',side_effect=RuntimeError('interruption')):
            with self.assertRaisesRegex(RuntimeError,'interruption'):
                bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5)
        files=list((self.run/'PRIVATE/chronology_plan102_parts').rglob('hits.parquet'))
        self.assertTrue(files); mtimes={p:p.stat().st_mtime_ns for p in files}
        with patch.object(bc,'materialize',side_effect=AssertionError('completed chunk reran')):
            out,info=bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5)
        self.assertEqual(mtimes,{p:p.stat().st_mtime_ns for p in files})
        self.assertEqual(info['rows'],8)
        with patch.object(bc,'ranges_for',side_effect=AssertionError('completed stage reran')):
            self.assertEqual(bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5),(out,info))

    def test_corrupt_chunk_and_final_output_rejected(self):
        q,oq,ox=self.data()
        with patch.object(bc,'append_sorted',side_effect=RuntimeError('interruption')):
            with self.assertRaises(RuntimeError):bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5)
        p=next((self.run/'PRIVATE/chronology_plan102_parts').rglob('hits.parquet'))
        with p.open('ab') as f:f.write(b'corruption')
        with self.assertRaises(RuntimeError):bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5)
        other=self.root/'other';out,_=bc.reuse_plan(other,self.conf,q,oq,ox,width=5)
        with (out/'hits.parquet').open('ab') as f:f.write(b'corruption')
        with self.assertRaises(RuntimeError):bc.reuse_plan(other,self.conf,q,oq,ox,width=5)

    def test_changed_source_signature_rejected(self):
        q,oq,ox=self.data();bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5)
        pq.write_table(pq.read_table(ox),ox)
        with self.assertRaisesRegex(RuntimeError,'Checkpoint input changed'):
            bc.reuse_plan(self.run,self.conf,q,oq,ox,width=5)

    def test_streaming_assembly_rejects_cross_chunk_overlap(self):
        a=self.facts('a.parquet',[1,2]);b=self.facts('b.parquet',[2,3])
        with self.assertRaisesRegex(RuntimeError,'overlap'):
            bc.append_sorted([a,b],self.root/'out.parquet',4)

    def test_each_materialized_table_is_bounded(self):
        ids=np.arange(2**42,2**42+1000,dtype=np.int64)
        q=self.queries('q.parquet',ids);oq=self.queries('oq.parquet',ids[:-1]);ox=self.facts('ox.parquet',ids[:-1])
        actual=bc.materialize;counts=[]
        def observe(*args):
            n=actual(*args);counts.append(n);self.assertLessEqual(n,127);return n
        with patch.object(bc,'materialize',side_effect=observe):
            out,info=bc.reuse_plan(self.run,self.conf,q,oq,ox,width=127,memory=.2)
        self.assertEqual(len(counts),24);self.assertEqual(info['missing'],1)

    def test_complete_workflow_reuses_original_missing_row_scanner(self):
        import fast_comparisons as fc
        q,oq,ox=self.data()
        target=self.run/'PRIVATE/supported';target.mkdir(parents=True)
        import shutil
        shutil.copy2(q,target/'queries.parquet')
        old=self.root/'old';(old/'PRIVATE/supported').mkdir(parents=True)
        shutil.copy2(oq,old/'PRIVATE/supported/queries.parquet')
        cache=self.root/'cache';(cache/'PRIVATE/chronology').mkdir(parents=True)
        shutil.copy2(ox,cache/'PRIVATE/chronology/features.parquet')
        fresh=self.root/'fresh';self.facts('fresh/features.parquet',[101])
        binding=dict(legacy_candidate_run=str(old),legacy_chronology_run=str(cache),
                     source=dict(chron=[dict(file_index=1,minimum=None)]))
        with patch.object(bc.c,'check_stage',side_effect=lambda p,k:p),\
             patch.object(fc.chron.previous,'prepare_chronology',return_value=(self.root/'prep',dict(latest_start=20000))),\
             patch('fast_chronology_parallel.resume_scans') as scan,\
             patch('fast_chronology_repair.validated_parts',return_value=[]) as validated,\
             patch('fast_chronology_merge.bounded_merge',return_value=(fresh,{})) as merge:
            bc.chronology90(SimpleNamespace(workers=10),self.run,self.conf,binding)
        scan.assert_called_once();validated.assert_called_once();merge.assert_called_once()
        info=read(self.run/'report/chronology90.json')
        self.assertEqual({k:info[k] for k in ('rows','reused','missing')},dict(rows=8,reused=7,missing=1))
        self.assertTrue((self.run/'PRIVATE/locally_eligible/_DONE.json').exists())

    def test_completed_comparison_reports_are_also_authenticated(self):
        auth=self.root/'authority';auth.mkdir();p=self.run/'comparisons/report/support.json'
        save(p,dict(rows=123));save(auth/'REPORT_MANIFEST.json',
            [dict(path='comparisons/support.json',bytes=p.stat().st_size,sha256=sha(p))])
        self.assertEqual(resume_guard.verify_reports(self.run,auth),1)
        save(p,dict(rows=124))
        with self.assertRaisesRegex(RuntimeError,'Completed result changed'):
            resume_guard.verify_reports(self.run,auth)


if __name__ == '__main__': unittest.main()
