import unittest,tempfile,sys,shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
import repair_chronology as repair


def fixture(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    q=dict(row_id=list(range(100,108)),game_id=[f'focal{k:03}' for k in range(8)],recipient_id=list(range(1,17,2)),opponent_id=list(range(2,18,2)),archive_start_ms=[100000]*8,previous_frame=[False]*8)
    query=root/'queries.parquet';pq.write_table(pa.table(q),query)
    prep=root/'prepared';prep.mkdir();pq.write_table(pa.table({'sample_row':[100]}),prep/'roles.parquet')
    parts=[]
    schema=pa.schema([('sample_row',pa.int64()),('role',pa.int32()),('prev_t',pa.int64()),('prev_count',pa.int64()),('prev_gid',pa.string()),('prev_opponent',pa.int64()),('focal_time_count',pa.int64()),('focal_matches',pa.int64()),('pre_games_30d',pa.int64())])
    for k in range(2):
        p=root/f'part{k}';p.mkdir();parts.append(p);rows=[];pairs=[]
        for index,rowid in enumerate(q['row_id']):
            i,j=q['recipient_id'][index],q['opponent_id'][index]
            pairs.append(dict(pair_key=i*4294967296+j,first_t=90000 if index in (1,7) and k else 100000))
            for role in (0,1):
                t=99990 if k==0 or index==3 else 99980
                r=dict(sample_row=rowid,role=role,prev_t=t,prev_count=1,prev_gid=f'prev{index}{role}{k}',prev_opponent=100+role,
                  focal_time_count=1 if k==0 else 0,focal_matches=1 if k==0 else 0,pre_games_30d=2+k if role==0 else 0)
                if index==1 and k==0:r.update(prev_gid='mutual00',prev_opponent=j if role==0 else i)
                if index==2 and k==0 and role==0:r['prev_count']=2
                if index==4 and k==0 and role==0:r['focal_time_count']=2
                if index==5 and role==1:r.update(prev_t=None,prev_count=None,prev_gid=None,prev_opponent=None)
                if index==6 and k==1:r.update(focal_time_count=1,focal_matches=1)
                rows.append(r)
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),p/'candidates.parquet');pq.write_table(pa.Table.from_pylist(pairs),p/'pairs.parquet')
    return query,prep,parts

class Repair(unittest.TestCase):
    def test_multiple_input_batches_preserve_sums_and_do_not_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,base=fixture(root/'data');parts=[]
            for k in range(17):
                dest=root/f'scan{k:02}';shutil.copytree(base[k%2],dest);parts.append(dest)
            expected,_=repair.previous.merge_chronology(q,prep,parts,root/'old','unit',.4,1)
            new,info=repair.bounded_merge(q,parts,root/'new','unit',memory=.4,buckets=4)
            self.assertEqual(pq.read_table(new/'features.parquet').sort_by('row_id').to_pydict(),
                pq.read_table(expected/'features.parquet').sort_by('row_id').to_pydict())
            self.assertEqual(len(list((root/'new/partitioned').glob('*/_DONE.json'))),2)
            self.assertEqual(info['partition_rows'],17*24)
            self.assertLessEqual(info['partition_files'],2*2*4)

    def test_actual_cached_and_scanned_chronology_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture(root/'data');parent=root/'parent';run=root/'newrun';fr=root/'frames'
            (parent/'PRIVATE/supported').mkdir(parents=True);(run/'PRIVATE').mkdir(parents=True);(run/'report').mkdir();(fr/'chronology').mkdir(parents=True)
            (parent/'RUN.lock').touch();shutil.copyfile(q,parent/'PRIVATE/supported/queries.parquet')
            sources=[dict(file_index=k,rows=16,minimum=0) for k in range(2)]
            definition=dict(kind='first_pair_predecessor_volume_v1',source=dict(files=sources),code={Path(chron.__file__).name:sha(chron.__file__)})
            oldkey=repair.io.cfgsha(definition);cache_root=parent/'PRIVATE/feature_cache/chronology'/oldkey/'all';cache_root.mkdir(parents=True)
            save(cache_root/'definition.json',definition);save(fr/'chronology/_DONE.json',dict(cache_definition_sha256=oldkey))
            def known(tmp):
                pq.write_table(pa.table(dict(game_id=['focal000'],recipient_id=[1],opponent_id=[2],archive_start_ms=[100000],
                  previous_classification_status=[repair.previous.rebuild.NONADJ],eligible_main=[True],first_observed_pair=[True],pre_games_30d=[5])),tmp/'records.parquet')
            repair.io.stage(cache_root/'blocks/known',oldkey,known)
            b=dict(candidate_run=str(parent),frame_root=str(fr),source=dict(chron=sources));a=SimpleNamespace(memory_gb=10.5,workers=1)
            plan,info,_=repair.cache_plan(a,run,'unit',b);self.assertEqual((info['cache_hits'],info['computed_rows']),(1,7))
            ck=repair.io.cfgsha([oldkey,sha(plan/'missing.parquet')])
            for k,p in enumerate(parts):
                def build(tmp,k=k,p=p):
                    t=pq.read_table(p/'candidates.parquet');t=t.filter(pa.compute.not_equal(t['sample_row'],100));pq.write_table(t,tmp/'candidates.parquet')
                    shutil.copyfile(p/'pairs.parquet',tmp/'pairs.parquet');return dict(file_index=k,input_rows=16)
                repair.io.stage(parent/'PRIVATE/chron_parts'/ck[:16]/f'{k:04}',ck,build)
            with patch.object(chron,'chronology_job',side_effect=AssertionError('Raw scan must never run')):
                repair.run_chronology(a,run,'unit',b)
            self.assertEqual(pq.read_table(run/'PRIVATE/locally_eligible/queries.parquet')['row_id'].to_pylist(),[100])
            self.assertEqual(load(run/'report/chronology_reuse.json')['rows'],8)

    def test_partitioned_merge_matches_frozen_ties_boundaries_pairs_and_volume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture(root/'data')
            expected,_=repair.previous.merge_chronology(q,prep,parts,root/'old','unit',.4,1)
            new,info=repair.bounded_merge(q,parts,root/'new','unit',memory=.4,buckets=4,max_queries=1,max_candidates=8)
            expected=pq.read_table(expected/'features.parquet').sort_by('row_id');got=pq.read_table(new/'features.parquet').sort_by('row_id')
            self.assertEqual(got.to_pydict(),expected.to_pydict());self.assertEqual(info['leaf_groups'],8)
            self.assertEqual(set(got['previous_classification_status'].to_pylist()),{'not_mutually_adjacent_observed','mutual_adjacency_candidate_timing_unresolved','ambiguous_start_order','left_boundary_unresolved','unmapped_or_inconsistent_focal'})
            self.assertEqual(got['pre_games_30d'].to_pylist(),[5]*8)
            stamp=(new/'features.parquet').stat().st_mtime_ns
            repair.bounded_merge(q,parts,root/'new','unit',memory=.4,buckets=4,max_queries=1,max_candidates=8)
            self.assertEqual((new/'features.parquet').stat().st_mtime_ns,stamp)

    def test_merge_splits_and_recovers_from_memory_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture(root/'data');original=repair.previous.rebuild.adjacency_final_sql;calls=[]
            def fail_once(*args):
                calls.append(1)
                if len(calls)==1:raise repair.duckdb.OutOfMemoryException('injected regression check')
                return original(*args)
            with patch.object(repair.previous.rebuild,'adjacency_final_sql',side_effect=fail_once):
                out,info=repair.bounded_merge(q,parts,root/'new','unit',memory=.4,buckets=2,max_queries=100,max_candidates=100)
            self.assertGreater(info['leaf_groups'],2);self.assertEqual(pq.ParquetFile(out/'features.parquet').metadata.num_rows,8)

    def test_exact_scan_reuse_and_query_bridge_reject_changed_rows_and_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q,prep,parts=fixture(root/'data');oldkey='definition';parent=root/'parent'
            ck=repair.io.cfgsha([oldkey,sha(q)]);sources=[]
            for k,part in enumerate(parts):
                dest=parent/'PRIVATE/chron_parts'/ck[:16]/f'{k:04}'
                def build(tmp,part=part,k=k):
                    for name in ('candidates.parquet','pairs.parquet'):shutil.copyfile(part/name,tmp/name)
                    return dict(file_index=k,input_rows=16)
                repair.io.stage(dest,ck,build);sources.append(dict(file_index=k,rows=16,minimum=0))
            got,info=repair.choose_scan_set(parent,q,oldkey,sources,root/'verify')
            self.assertEqual(len(got),2);self.assertEqual(info['raw_game_scans_started'],0);self.assertFalse(info['exact_query_row_bridge_used'])
            prior=parent/'PRIVATE/chronology.partial_fixture/missing.parquet';prior.parent.mkdir();shutil.copyfile(q,prior)
            other=root/'other.parquet';pq.write_table(pq.read_table(q),other,compression='gzip')
            _,info=repair.choose_scan_set(parent,other,oldkey,sources,root/'verify')
            self.assertTrue(info['exact_query_row_bridge_used'])
            bad=root/'bad.parquet';t=pq.read_table(q);t=t.set_column(t.schema.get_field_index('recipient_id'),'recipient_id',pa.array([99]+list(range(3,17,2))));pq.write_table(t,bad)
            with self.assertRaisesRegex(RuntimeError,'No completed scan set'):repair.choose_scan_set(parent,bad,oldkey,sources,root/'verify')
            (got[0]/'pairs.parquet').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'Input size changed|Input checksum changed'):repair.choose_scan_set(parent,q,oldkey,sources,root/'verify')

if __name__=='__main__':unittest.main()
