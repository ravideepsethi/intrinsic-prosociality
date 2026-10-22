"""Exercise the real chronology reader with the bound R9 record schema."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from local_common import DAY, key, load, save, seal, snapshot
import cutoffs
import followup_logic as vol


class CutoffVolumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.people=np.array([22,11,11,33,11,22],np.int64)
        self.starts=np.array([110,100,100,100,140,100],np.int64)*DAY
        self.events=[
            (50*DAY,11,22), (70*DAY-1,11,22), (70*DAY,11,22),
            (99*DAY,22,11), (100*DAY,11,22), (100*DAY+1,11,33),
            (109*DAY,22,44), (110*DAY,11,22), (140*DAY,11,22),
            (150*DAY,11,22), (99*DAY,11,None), (99*DAY,None,11),
            (None,11,22), (0,11,22), (99*DAY,11,11),
        ]
        self.expected=np.array([
            sum(t is not None and t>0 and w is not None and b is not None
                and w>=0 and b>=0 and w!=b and start-30*DAY<=t<start
                and person in (w,b) for t,w,b in self.events)
            for person,start in zip(self.people,self.starts)],np.int64)
        self.query=self.root/'query';self.query.mkdir()
        keys,order,people=vol.volume_plan(self.people,self.starts)
        for name,value in [('keys',keys),('order',order),('people',people)]:
            np.save(self.query/(name+'.npy'),value,allow_pickle=False)
        save(self.query/'meta.json',dict(minimum=int(self.starts.min()),maximum=int(self.starts.max())))

    def record(self,name,events=None,statistics=True):
        events=self.events if events is None else events
        p=self.root/(name+'.parquet')
        table=pa.table({field:pa.array([r[i] for r in events],pa.int64())
                        for i,field in enumerate(['utc_ms','white_id','black_id'])})
        pq.write_table(table,p,row_group_size=3,write_statistics=statistics)
        # Exact layout produced by cached_inputs.research_inputs after its
        # canonical-manifest size/rows/row-groups and schema checks.
        return dict(path=str(p),file_index=0,rows=len(events),
                    signature=cutoffs.frozen.r.io.sig(p),minimum=None)

    def job(self,record,name):
        return dict(input=record,query=str(self.query),out=str(self.root/(name+'.npz')),
                    key=key(['fixture',record]))

    def test_worker_counts_boundaries_both_roles_and_repeated_queries(self):
        for statistics in [True,False]:
            with self.subTest(statistics=statistics):
                record=self.record('chron_'+str(statistics),statistics=statistics)
                self.assertNotIn('bytes',record)
                job=self.job(record,'result_'+str(statistics))
                with np.load(cutoffs.volume_job(job),allow_pickle=False) as z:
                    np.testing.assert_array_equal(z['value'],self.expected)

    def test_worker_cache_reuses_output_and_checks_current_signature(self):
        record=self.record('chron');job=self.job(record,'result')
        out=Path(cutoffs.volume_job(job));before=snapshot(out)
        with patch.object(vol,'accumulate_volume',side_effect=AssertionError('Cache rescanned')):
            self.assertEqual(cutoffs.volume_job(job),str(out))
        self.assertEqual(snapshot(out),before)
        p=Path(record['path']);s=p.stat();os.utime(p,ns=(s.st_atime_ns,s.st_mtime_ns+1000000))
        with self.assertRaisesRegex(RuntimeError,'signature changed'):
            cutoffs.volume_job(job)

    def test_metadata_mismatch_and_missing_signature_are_rejected(self):
        record=self.record('chron')
        bad_records=[
            (dict(record,signature=[record['signature'][0]+1,record['signature'][1]]),'signature changed'),
            (dict(record,signature=[record['signature'][0],record['signature'][1]+1]),'signature changed'),
            (dict(record,rows=record['rows']+1),'row count changed'),
            ({k:v for k,v in record.items() if k!='signature'},'lacks .* signature'),
        ]
        for i,(bad,message) in enumerate(bad_records):
            with self.subTest(i=i),self.assertRaisesRegex(RuntimeError,message):
                cutoffs.volume_job(self.job(bad,'bad_'+str(i)))
        self.assertFalse(list(self.root.glob('bad_*.npz')))

    def test_input_change_during_scan_does_not_commit_a_checkpoint(self):
        record=self.record('chron');job=self.job(record,'result')
        original=vol.accumulate_volume
        def mutate(*args):
            original(*args)
            p=Path(record['path']);s=p.stat();os.utime(p,ns=(s.st_atime_ns,s.st_mtime_ns+1000000))
        with patch.object(vol,'accumulate_volume',side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError,'changed during volume scan'):
                cutoffs.volume_job(job)
        self.assertFalse(Path(job['out']).exists())

    def test_add_volume_spawn_join_and_resume_preserve_old_counts(self):
        records=[self.record('chron_a',self.events[:7]),self.record('chron_b',self.events[7:])]
        root=self.root/'cutoffs';root.mkdir()
        ids=np.arange(1,len(self.people)+1,dtype=np.int64)
        source=self.root/'source.parquet';old=self.root/'old.parquet'
        pq.write_table(pa.table(dict(row_id=ids,recipient_id=self.people,
            archive_start_ms=self.starts,pre_games_30d=np.full(len(ids),-999))),source)
        pq.write_table(pa.table(dict(row_id=[1],pre_games_30d=[321])),old)
        bound=dict(original=str(old),binding=dict(source=dict(chron=records)))
        args=SimpleNamespace(workers=2,memory_gb=4)
        out=cutoffs.add_volume(args,bound,source,root,'fixture')
        expected=self.expected.copy();expected[0]=321
        np.testing.assert_array_equal(pq.read_table(out)['pre_games_30d'].to_numpy(),expected)
        before=snapshot(out)
        self.assertEqual(cutoffs.add_volume(args,bound,source,root,'fixture'),out)
        self.assertEqual(snapshot(out),before)
        self.assertEqual(len(list((root/'volume_parts').glob('*.npz'))),2)

    def test_merged_history_resume_preserves_inputs_and_rejects_corruption(self):
        root=self.root/'cutoffs';root.mkdir()
        merged=root/'clean_features.parquet'
        pq.write_table(pa.table(dict(row_id=[1,2],y=[0,1])),merged)
        seal(merged,'fixture')
        queries=root/'outcome_queries';queries.mkdir()
        p=queries/'outcome_00.parquet';pq.write_table(pa.table(dict(row_id=[1])),p)
        before=snapshot(p)
        with patch.object(cutoffs.inputs,'outcome_jobs',side_effect=AssertionError('Histories rerun')):
            self.assertEqual(cutoffs.clean_features(None,{},None,root,'fixture'),merged)
        self.assertEqual(snapshot(p),before)
        with merged.open('ab') as f:f.write(b'corruption')
        with self.assertRaisesRegex(RuntimeError,'checksum changed'):
            cutoffs.clean_features(None,{},None,root,'fixture')


if __name__=='__main__':unittest.main(verbosity=2)
