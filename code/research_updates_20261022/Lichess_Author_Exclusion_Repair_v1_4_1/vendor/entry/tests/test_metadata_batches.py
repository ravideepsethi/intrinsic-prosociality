import unittest,tempfile,sys,contextlib
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
import rebuild_metadata as md
import metadata_batches as mb
import metadata_reference_v102 as reference


def fixture(root,n=40):
    root=Path(root);(root/'PRIVATE/locally_eligible').mkdir(parents=True);(root/'report').mkdir()
    start=1710000000000;ids=[f'g{k:07}' for k in range(n)]
    query=root/'PRIVATE/locally_eligible/queries.parquet'
    pq.write_table(pa.table(dict(row_id=list(range(n)),game_id=ids,recipient_id=list(range(1,n+1)),opponent_id=list(range(101,101+n)),
        utc_ms=[start]*n,archive_start_ms=[start]*n,month_code=[4]*n,recipient_color=['white' if k%2 else 'black' for k in range(n)],
        speed_partition=['blitz']*n,previous_frame=[k%2==0 for k in range(n)])),query)
    original=[];duplicates=[];fresh=[]
    for k,gid in enumerate(ids):
        row={f.name:None for f in md.expansion.metadata_schema()}
        row.update(game_id=gid,source='friend' if k%4==1 else 'pool',status='resign',winner='white',
          api_start_ms=start,anchor_ms=start+1000,rated=True,variant='standard',speed='blitz',tc_base_s=180,tc_inc_s=0,
          white_username=f'w{k}',black_username=f'b{k}',white_rating=1500.,black_rating=1600.,record_errors='')
        if k>=n-3:
            original.append(row.copy());bad=row.copy();bad['api_start_ms']+=DAY;duplicates.append(bad)
        elif k%4==2:fresh.append(row.copy())
        else:
            if k%4==3:fresh.append(row.copy());row['black_rating']=None
            original.append(row.copy())
            if k%5==0:duplicates.append(row.copy())
    paths=[]
    for name,rows in [('metadata',original),('duplicates',duplicates),('fresh',fresh)]:
        p=root/(name+'.parquet');pq.write_table(pa.Table.from_pylist(rows,schema=md.expansion.metadata_schema()),p);paths.append(p)
    q=root/'quarantine.parquet';pq.write_table(pa.table(dict(game_id=ids[-3:])),q)
    return dict(metadata=list(map(str,paths[:2])),quarantine=[str(q)],source={}),paths[2]


def rows(path,keycol='game_id'):
    return pq.ParquetFile(path).read().sort_by(keycol).to_pylist()


class MetadataBatches(unittest.TestCase):
    def test_audit_matches_original_global_queries_and_resumes_without_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);b,fresh=fixture(root/'new');oldb,_=fixture(root/'old');a=SimpleNamespace(memory_gb=10.5,workers=1)
            expected=reference.plan(a,root/'old','unit',oldb)
            with patch.object(mb,'BUCKETS',4),patch.object(mb,'MAX_ROWS',8):
                actual=md.plan(a,root/'new','unit',b)
                before={p:sha(p) for p in (root/'new/PRIVATE/metadata_work').rglob('*.parquet')}
                stamp=(actual/'targets.parquet').stat().st_mtime_ns
                md.plan(a,root/'new','unit',b)
                self.assertEqual(stamp,(actual/'targets.parquet').stat().st_mtime_ns)
                self.assertEqual(before,{p:sha(p) for p in before})
            for name in ('known','dispositions','targets'):self.assertEqual(rows(actual/(name+'.parquet')),rows(expected/(name+'.parquet')))
            summary=load(actual/'summary.json');old=load(expected/'summary.json')
            for name in old:self.assertEqual(summary[name],old[name])
            self.assertGreater(summary['leaf_groups'],4)
            # A date conflict is still detected because buckets use game ID, not date.
            self.assertEqual(summary['metadata_counts']['CACHE_CONFLICT_OR_PRIOR_FLAG'],3)
            self.assertEqual(summary['known_quarantine_candidates'],3)

    def test_end_to_end_download_fill_and_reconciliation_match_original(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);b,fresh=fixture(root/'new');oldb,oldfresh=fixture(root/'old');a=SimpleNamespace(memory_gb=10.5,workers=1,project=root)
            # Preserve the old reconciliation query verbatim as an independent oracle.
            def exported(sql,target,folder,conf):
                folder.mkdir(parents=True);shutil.copyfile(oldfresh,folder/'downloaded_metadata.parquet')
                save(folder/'SUMMARY.json',dict(requested=pq.ParquetFile(target).metadata.num_rows))
            with patch.object(reference.download,'exclusive',return_value=contextlib.nullcontext()),\
                 patch.object(reference.download,'check_other_api_jobs'),patch.object(reference.metadata_http,'Client'),\
                 patch.object(reference.download,'process_batch',return_value=([],[],0,False)),\
                 patch.object(reference.download,'export_saved',side_effect=exported),patch.object(reference.cached_inputs,'identity_check'):
                reference.retrieve(a,root/'old','unit',oldb)
            with patch.object(mb,'BUCKETS',4),patch.object(mb,'MAX_ROWS',8),patch.object(mb.cached_inputs,'identity_check'):
                plan=md.plan(a,root/'new','unit',b);actual=mb.complete(a,root/'new','unit',b,plan,fresh)
                stamp=(actual/'queries.parquet').stat().st_mtime_ns
                mb.complete(a,root/'new','unit',b,plan,fresh)
                self.assertEqual(stamp,(actual/'queries.parquet').stat().st_mtime_ns)
            expected=root/'old/PRIVATE/metadata_complete'
            for name in ('metadata','queries','dispositions'):self.assertEqual(rows(actual/(name+'.parquet')),rows(expected/(name+'.parquet')))
            self.assertEqual(load(root/'new/report/metadata_completion.json')['new_unresolved_rows'],0)

    def test_memory_failure_splits_and_reuses_completed_groups_after_interruption(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);b,_=fixture(root);a=SimpleNamespace(memory_gb=10.5,workers=1);real=mb.audit_leaf;calls=[]
            def transient(*args,**kwargs):
                calls.append(1)
                if len(calls)==1:raise mb.duckdb.OutOfMemoryException('injected')
                if len(calls)==4:raise RuntimeError('simulated interruption')
                return real(*args,**kwargs)
            with patch.object(mb,'BUCKETS',2),patch.object(mb,'MAX_ROWS',100),patch.object(mb,'audit_leaf',side_effect=transient):
                with self.assertRaisesRegex(RuntimeError,'simulated interruption'):md.plan(a,root,'unit',b)
            completed=list((root/'PRIVATE/metadata_work/audit').glob('*/_DONE.json'));self.assertTrue(completed)
            stamps={p:p.stat().st_mtime_ns for p in completed}
            with patch.object(mb,'BUCKETS',2),patch.object(mb,'MAX_ROWS',100):md.plan(a,root,'unit',b)
            self.assertEqual(stamps,{p:p.stat().st_mtime_ns for p in stamps})
            self.assertTrue(list((root/'PRIVATE/metadata_work/audit_splits').glob('*/_DONE.json')))

    def test_unreturned_and_prior_flags_block_frames(self):
        for mode in ('unreturned','prior_flag'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                root=Path(td);b,fresh=fixture(root);a=SimpleNamespace(memory_gb=10.5,workers=1)
                if mode=='unreturned':pq.write_table(pq.read_table(fresh).slice(1),fresh)
                else:
                    p=Path(b['metadata'][0]);t=pq.read_table(p);d=t.to_pylist();d[0]['record_errors']='REVIEW_REQUIRED'
                    pq.write_table(pa.Table.from_pylist(d,schema=t.schema),p)
                    # Repeating a clean response must not silently clear the prior flag.
                    repeated=dict(d[0],record_errors='')
                    pq.write_table(pa.concat_tables([pq.read_table(fresh),pa.Table.from_pylist([repeated],schema=t.schema)]),fresh)
                with patch.object(mb,'BUCKETS',4),patch.object(mb.cached_inputs,'identity_check') as identity:
                    plan=md.plan(a,root,'unit',b)
                    with self.assertRaisesRegex(RuntimeError,'additional metadata rows remain unresolved'):mb.complete(a,root,'unit',b,plan,fresh)
                    identity.assert_not_called()
                self.assertFalse((root/'PRIVATE/metadata_complete/_DONE.json').exists())
                self.assertGreater(load(root/'report/metadata_completion.json')['new_unresolved_rows'],0)

    def test_fresh_conflict_and_tampered_leaf_are_rejected(self):
        for mode in ('conflict','tamper'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                root=Path(td);b,fresh=fixture(root);a=SimpleNamespace(memory_gb=10.5,workers=1)
                with patch.object(mb,'BUCKETS',4):
                    plan=md.plan(a,root,'unit',b)
                    if mode=='conflict':
                        t=pq.read_table(fresh);d=t.to_pylist();r=next(r for r in d if int(r['game_id'][1:])%4==3);r['white_rating']=1700.
                        pq.write_table(pa.Table.from_pylist(d,schema=t.schema),fresh);message='conflicts with cached'
                    else:
                        leaf=Path(load(plan/'leaves_PRIVATE.json')[0]['path']);(leaf/'known.parquet').write_bytes(b'changed');message='Input size changed|Input checksum changed'
                    with self.assertRaisesRegex(RuntimeError,message):mb.complete(a,root,'unit',b,plan,fresh)
                    self.assertFalse((root/'PRIVATE/metadata_complete/_DONE.json').exists())

    def test_empty_eligible_population_has_typed_outputs_and_no_requests(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);b,fresh=fixture(root);q=root/'PRIVATE/locally_eligible/queries.parquet'
            pq.write_table(pq.read_table(q).slice(0,0),q);a=SimpleNamespace(memory_gb=10.5,workers=1)
            with patch.object(mb,'BUCKETS',4),patch.object(md.metadata_http,'Client') as client,patch.object(mb.cached_inputs,'identity_check'):
                md.retrieve(a,root,'unit',b);client.assert_not_called()
            self.assertEqual(pq.ParquetFile(root/'PRIVATE/metadata_complete/queries.parquet').metadata.num_rows,0)

    def test_duplicate_eligible_games_and_changed_quarantine_fail_closed(self):
        for mode in ('duplicate','quarantine'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                root=Path(td);b,_=fixture(root);a=SimpleNamespace(memory_gb=10.5,workers=1)
                if mode=='duplicate':
                    p=root/'PRIVATE/locally_eligible/queries.parquet';t=pq.read_table(p)
                    pq.write_table(pa.concat_tables([t,t.slice(0,1)]),p);message='Duplicate or null'
                else:
                    pq.write_table(pa.table(dict(game_id=['q1','q2'])),b['quarantine'][0]);message='quarantine changed'
                with patch.object(mb,'BUCKETS',4),self.assertRaisesRegex(RuntimeError,message):md.plan(a,root,'unit',b)
                self.assertFalse((root/'PRIVATE/metadata_plan/_DONE.json').exists())


if __name__=='__main__':unittest.main()
