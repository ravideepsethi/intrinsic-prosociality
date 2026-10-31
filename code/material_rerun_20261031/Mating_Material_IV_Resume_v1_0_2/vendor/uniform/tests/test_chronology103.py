import sys,unittest,tempfile,contextlib,io,shutil
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fast_bootstrap as c
import fast_chronology_repair as f
import fast_chronology_merge as m
import repair_chronology as old
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
sys.path.insert(0,str(c.FAST_ROOT/'original/vendor/tests'))
import test_chronology_repair as fixtures

def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.table(data),path);return path

def raw_fixture(root):
    D=c.DAY
    q=dict(row_id=[4398046511101,4398046511102,4398046511103,4398046511104],game_id=['focal001','focal002','focal003','focal004'],
        recipient_id=[1,3,1,8],opponent_id=[2,4,5,9],archive_start_ms=[100*D,100*D,101*D,105*D],previous_frame=[False]*4)
    source=dict(game_id=['older001','lower001','prior001','prior002','tie00001','tie00002','focal001','focal002','focal003','focal004'],
        utc_ms=[60*D,70*D,98*D,98*D,99*D,99*D,100*D,100*D,101*D,105*D],
        white_id=[1,1,2,4,3,3,1,3,1,8],black_id=[99,99,99,99,98,97,2,4,5,9])
    query=write(root/'queries.parquet',q);raw=write(root/'raw.parquet',source)
    prep,info=c.chron.previous.prepare_chronology(query,root/'prep','prepare',.5)
    job=dict(path=str(raw),signature=f.io.sig(raw),rows=len(source['game_id']),file_index=0,latest=info['latest_start'],
        people=str(prep/'people.parquet'),pairs=str(prep/'pairs.parquet'),focal=str(prep/'focal.parquet'),roles=str(prep/'roles.parquet'),
        memory=.5,conf='scan',output=str(root/'scan'))
    c.chron.chronology_job(job)
    return query,prep,job,q,source

class Chronology103(unittest.TestCase):
    def setUp(self):self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__()
    def tearDown(self):self.silence.__exit__(None,None,None)

    def test_native_partition_preserves_rows_large_ids_null_payloads_and_empty_files(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);data=pa.table(dict(sample_row=pa.array([0,2**50+1,2**63+5,2**64-1],type=pa.uint64()),payload=pa.array([1,None,3,None],type=pa.int64())))
            pq.write_table(data,r/'data.parquet');pq.write_table(data.slice(0,0),r/'empty.parquet')
            result=f.partition_files([r/'empty.parquet',r/'data.parquet'],'sample_row',r/'parts',buckets=4,batch_rows=2,group_rows=1,buffer_bytes=64,expected_rows=4)
            got=[]
            for p in (r/'parts').glob('bucket=*/data.parquet'):
                t=pq.ParquetFile(p).read();bucket=int(p.parent.name.split('=')[1]);self.assertTrue(all(x%4==bucket for x in t['sample_row'].to_pylist()));got.append(t)
            self.assertEqual(pa.concat_tables(got).sort_by('sample_row').to_pydict(),data.sort_by('sample_row').to_pydict())
            self.assertEqual(result['rows'],4)
            bad=data.set_column(0,'sample_row',pa.array([0,None,5,6],type=pa.uint64()));pq.write_table(bad,r/'bad.parquet')
            with self.assertRaisesRegex(RuntimeError,'Missing physical'):f.partition_files([r/'bad.parquet'],'sample_row',r/'reject',buckets=4)

    def test_null_audit_reads_values_if_statistics_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.parquet';pq.write_table(pa.table(dict(sample_row=pa.array([1,None,3],type=pa.int64()))),p,write_statistics=False)
            self.assertEqual(f.null_audit(p,['sample_row'])['nulls']['sample_row'],1)

    def test_strict_window_repair_matches_original_and_brute_force(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);query,prep,job,q,raw=raw_fixture(root)
            original=pq.read_table(Path(job['output'])/'candidates.parquet').sort_by([('sample_row','ascending'),('role','ascending')])
            # Force the independent repair engine even though this fixture is intact.
            repaired=f.repair_scan(job,root/'fixed','parent')
            result=pq.read_table(repaired/'candidates.parquet').sort_by([('sample_row','ascending'),('role','ascending')])
            self.assertEqual(result.to_pydict(),original.to_pydict())
            for row in result.to_pylist():
                k=q['row_id'].index(row['sample_row']);person=(q['recipient_id'] if row['role']==0 else q['opponent_id'])[k];t=q['archive_start_ms'][k]
                events=[e for e in range(len(raw['game_id'])) if raw['white_id'][e]==person or raw['black_id'][e]==person]
                prior=[e for e in events if raw['utc_ms'][e]<t];latest=max([raw['utc_ms'][e] for e in prior],default=None)
                self.assertEqual(row['prev_t'],latest)
                if latest is not None:self.assertEqual(row['prev_count'],sum(raw['utc_ms'][e]==latest for e in events))
                self.assertEqual(row['focal_time_count'],sum(raw['utc_ms'][e]==t for e in events))
                self.assertEqual(row['pre_games_30d'],sum(t-30*c.DAY<=raw['utc_ms'][e]<t for e in events) if row['role']==0 else 0)
            self.assertFalse(f.null_audit(repaired/'candidates.parquet',f.REQUIRED_CANDIDATES)['invalid'])

    def test_missing_physical_keys_reconstruct_only_affected_scan_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);query,prep,job,q,raw=raw_fixture(root)
            original=Path(job['output']);expected=pq.read_table(original/'candidates.parquet')
            broken=root/'broken';data=expected.to_pydict();data['sample_row'][0]=None
            def build(tmp):
                pq.write_table(pa.table(data,schema=expected.schema),tmp/'candidates.parquet');shutil.copyfile(original/'pairs.parquet',tmp/'pairs.parquet')
            c.stage(broken,job['conf'],build,[job[k] for k in ('path','people','pairs','focal','roles')])
            job0=dict(job,output=str(broken));before={p:(f.io.sig(p),c.sha(p)) for p in broken.iterdir() if p.is_file()}
            outputs=f.validated_parts([job,job0],root/'repairs','parent',root/'report')
            self.assertEqual(outputs[0],original);self.assertNotEqual(outputs[1],broken)
            order=[('sample_row','ascending'),('role','ascending')]
            self.assertEqual(pq.read_table(outputs[1]/'candidates.parquet').sort_by(order).to_pydict(),expected.sort_by(order).to_pydict())
            for p,record in before.items():self.assertEqual((f.io.sig(p),c.sha(p)),record)
            stats=c.load(root/'report/chronology_key_repair104.json');self.assertEqual(stats['repaired_scans'],1)
            with patch.object(f,'window_lookups',side_effect=AssertionError('Must reuse complete repair')):
                self.assertEqual(f.validated_parts([job,job0],root/'repairs','parent',root/'report'),outputs)

    def test_identified_old_error_requires_independent_raw_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);query,prep,job,q,raw=raw_fixture(root);original=Path(job['output'])
            data=pq.read_table(original/'candidates.parquet').to_pydict();data['pre_games_30d'][0]+=999
            def build(tmp):
                pq.write_table(pa.table(data),tmp/'candidates.parquet');shutil.copyfile(original/'pairs.parquet',tmp/'pairs.parquet')
            c.stage(root/'changed',job['conf'],build)
            result=f.repair_scan(dict(job,output=str(root/'changed')),root/'fixed','parent')
            audit=c.load(result/'repair_audit.json')['tables']['candidates']
            self.assertEqual(audit['identified_original_rows_differing'],1)
            self.assertTrue(audit['raw_verification']['passed'])
            self.assertEqual(audit['raw_verification']['candidate_rows_checked'],1)

    def test_merge_matches_frozen_and_reuses_completed_partitions(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixtures.fixture(root/'data')
            expected,_=old.previous.merge_chronology(q,prep,parts,root/'expected','unit',.5,1)
            # Build an old-format merge first; the new reader must accept its receipts.
            complete,_=old.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)
            before={p:(f.io.sig(p),c.sha(p)) for p in (root/'merge/partitioned').rglob('*') if p.is_file()}
            with patch.object(m,'partition_scan_files',side_effect=AssertionError('Completed partitions must not be rewritten')):
                got,_=m.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)
            self.assertEqual(pq.read_table(got/'features.parquet').to_pydict(),pq.read_table(expected/'features.parquet').to_pydict())
            for p,record in before.items():self.assertEqual((f.io.sig(p),c.sha(p)),record)
            fresh,_=m.bounded_merge(q,parts,root/'new','unit',memory=.5,buckets=4,max_queries=1,max_candidates=8)
            self.assertEqual(pq.read_table(fresh/'features.parquet').to_pydict(),pq.read_table(expected/'features.parquet').to_pydict())

    def test_resumes_after_old_partition_failure_without_rewriting_good_batch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,base=fixtures.fixture(root/'data');parts=[]
            for i in range(17):
                p=root/f'scan{i:02}';shutil.copytree(base[i%2],p);parts.append(p)
            partition=old.partition
            def fail(c,sql,path,**kw):
                if kw.get('label')=='Batch 2 candidates':raise RuntimeError('Null chronology partition bucket')
                return partition(c,sql,path,**kw)
            with patch.object(old,'partition',side_effect=fail),self.assertRaisesRegex(RuntimeError,'Null chronology'):
                old.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)
            good=root/'merge/partitioned/000';before={p:(f.io.sig(p),c.sha(p)) for p in good.rglob('*') if p.is_file()}
            expected,_=old.previous.merge_chronology(q,prep,parts,root/'expected','unit',.5,1)
            got,_=m.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)
            self.assertEqual(pq.read_table(got/'features.parquet').to_pydict(),pq.read_table(expected/'features.parquet').to_pydict())
            for p,record in before.items():self.assertEqual((f.io.sig(p),c.sha(p)),record)

    def test_full_comparison_chronology_route_uses_repair_and_native_merge(self):
        sys.path.insert(0,str(c.FAST_ROOT/'original/tests'))
        import test_uniform90 as fixture
        import fast_comparisons as comp
        with patch.object(fixture,'comp',comp):
            fixture.SelectionTests().test_new_comparison_chronology_scans_and_bounded_merge()

    def test_corrected_source_gets_separate_partition_and_downstream_checkpoints(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixtures.fixture(root/'data')
            oldout,_=old.bounded_merge(q,parts,root/'merge','unit',memory=.5,buckets=4)
            before={p:(f.io.sig(p),c.sha(p)) for p in (root/'merge').rglob('*') if p.is_file()}
            corrected=root/'corrected';shutil.copytree(parts[0],corrected)
            out,_=m.bounded_merge(q,[corrected,parts[1]],root/'merge','unit',memory=.5,buckets=4)
            self.assertNotEqual(out,oldout);self.assertIn('downstream_repaired103',str(out))
            self.assertEqual(pq.read_table(out/'features.parquet').to_pydict(),pq.read_table(oldout/'features.parquet').to_pydict())
            for p,record in before.items():self.assertEqual((f.io.sig(p),c.sha(p)),record)

if __name__=='__main__':unittest.main()
