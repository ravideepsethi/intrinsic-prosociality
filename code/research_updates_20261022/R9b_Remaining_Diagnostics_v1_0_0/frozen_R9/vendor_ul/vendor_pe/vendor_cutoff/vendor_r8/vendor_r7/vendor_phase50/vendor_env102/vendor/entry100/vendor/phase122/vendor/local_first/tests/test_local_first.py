import sys,unittest,tempfile,json,gzip,hashlib,sqlite3,os,time,contextlib
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
PKG=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PKG/'code'))
from local_contract import *
import local_cache as cache
import prior_support as support
import run_local_first as run
import iv_numerics as num
import metadata_http as http

def api_object(gid,source='pool'):
    return dict(id=gid,source=source,status='mate',createdAt=int(core.STARTS[4])+123,
                lastMoveAt=int(core.STARTS[4])+100123,rated=True,variant='standard',speed='blitz',winner='white',
                clock=dict(initial=180,increment=0),players=dict(
                white=dict(user=dict(id='alice',name='Alice'),rating=1500),
                black=dict(user=dict(id='bob',name='Bob'),rating=1510)))

def gid_rows(n):
    # Selection/orientation are exactly the shipped inherited primitives.
    rows=[]
    for k in range(n*100):
        g=f'{k:08d}'
        if ex.selected([g])[0]:rows.append(g)
        if len(rows)==n:break
    return rows

@contextlib.contextmanager
def assert_sqlite_closed(test):
    """Keep references alive so success cannot rely on garbage-collection cleanup."""
    real_connect=sqlite3.connect;connections=[]
    def connect(*args,**kwargs):
        db=real_connect(*args,**kwargs);connections.append(db);return db
    with patch.object(sqlite3,'connect',side_effect=connect):
        try:
            yield
        finally:
            try:
                test.assertTrue(connections,'The test must exercise a database connection')
                for db in connections:
                    with test.assertRaisesRegex(sqlite3.ProgrammingError,'closed'):
                        db.execute('SELECT 1')
            finally:
                for db in connections:db.close()

class HistoryTests(unittest.TestCase):
    def test_full_shard_pipeline_and_field_preserving_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);shard=0
            chooser=next(i for i in range(10,1000) if num.user_hash([i])[0]%np.uint64(16)==shard)
            hist=td/'history.parquet'
            io.table(hist,pa.table(dict(j=[chooser]*13,i=list(range(1000,1013)),
                                      t=[int(core.STARTS[3])]*12+[int(core.STARTS[9])],arm=[True]*13)))
            val=td/'validation.parquet'
            io.table(val,pa.table(dict(row_id=[0],recipient_id=[1000],opponent_id=[chooser],month_code=[4],n_7d=[11])))
            paths=[];gids=gid_rows(21)
            for m,month in enumerate(ex.MONTHS):
                rw=((ex.bits([gids[m]])[0]>>np.uint64(32))&np.uint64(1))==0
                original=pa.table(dict(game_id=[gids[m]],utc_ms=[int(core.STARTS[m])],archive_ordinal=[m],
                     white_id=[1000 if rw else chooser],black_id=[chooser if rw else 1000]))
                t=ex.orient(original,month,'blitz');p=td/(month+'.parquet');io.table(p,t);paths.append(str(p))
            job=dict(histories=[str(hist)],queries=paths,validation=str(val),authors=[9997,9998],shard=shard,
                     memory=1,output=str(td/'counts'),conf='test')
            info=support.score_shard(job)
            self.assertEqual(info['rows'],21);self.assertEqual(info['cached_score_count_mismatches'],0)
            march=io.read(td/'counts/2024-03.parquet').to_pylist()[0]
            self.assertEqual(march['n7_author_clean'],11);self.assertEqual(march['local_eligibility'],'POTENTIALLY_ELIGIBLE')
            feb=io.read(td/'counts/2024-02.parquet').to_pylist()[0]
            self.assertEqual(feb['local_eligibility'],'INCOMPLETE_97D_HISTORY')
            a=support.assemble_month(dict(parts=[str(td/'counts/2024-03.parquet')],frame=paths[4],
                      memory=1,output=str(td/'assembled'),conf='test'))
            self.assertEqual(a['frame_fields_changed'],0)
            # Rerunning the actual worker must reuse its complete output.
            self.assertEqual(support.score_shard(job)['rows'],21)

    def test_count_matches_original_with_strict_ties_pair_leaveout_and_author_clean(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);rng=np.random.default_rng(928)
            n=5000;j=rng.integers(1,45,n);i=rng.integers(45,85,n)
            times=rng.integers(int(core.STARTS[0]),int(core.STARTS[10]),n)
            # Include a score-boundary tie, repeated pairs, non-arm decisions, and authors.
            times[:3]=core.STARTS[4]-7*core.DAY+np.array([-1,0,1])
            j[:3]=9;i[:3]=61
            arm=rng.random(n)>.15;arm[:3]=True;authors=[3,52]
            hist=td/'history.parquet';io.table(hist,pa.table(dict(j=j,i=i,t=times,arm=arm)))
            c=io.conn(td/'spill',1,1)
            try:
                support.build_counts(c,[hist],authors)
                for month in (0,1,4,9,20,23):
                    qj=np.r_[rng.integers(1,50,200),9,9];qi=np.r_[rng.integers(45,90,200),61,62]
                    q=pa.table(dict(opponent_id=qj,recipient_id=qi,month_code=[month]*len(qj),row_id=np.arange(len(qj))))
                    c.register('queries',q)
                    answer=c.execute(support.count_query('SELECT * FROM queries','q.month_code')+' ORDER BY row_id').to_arrow_table().to_pydict()
                    for clean,key in ((False,'n7_original'),(True,'n7_author_clean')):
                        use=arm.copy()
                        if clean:use &= ~np.isin(j,authors)&~np.isin(i,authors)
                        model=np.ones((4,4,500))*.03
                        truth=num.score_month(j[use],i[use],times[use],np.zeros(use.sum()),np.zeros(use.sum(),int),qj,qi,
                                              int(core.STARTS[month])-7*core.DAY,model)['n']
                        np.testing.assert_array_equal(answer[key],truth)
            finally:c.close()

    def test_missing_history_is_exclusion_only_after_complete_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);c=io.conn(td/'spill',1,1)
            try:
                with self.assertRaises(FileNotFoundError):support.build_counts(c,[td/'missing.parquet'],[8,9])
            finally:c.close()

    def test_partition_preserves_all_fixed_fields_and_orientation(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);gids=gid_rows(70);n=len(gids)
            base=pa.table(dict(game_id=gids,utc_ms=np.repeat(int(core.STARTS[4]),n),archive_ordinal=np.arange(n),white_id=np.arange(10,10+n),black_id=np.arange(1000,1000+n)))
            frame=ex.orient(base,'2024-03','blitz');path=td/'frame.parquet';io.table(path,frame)
            info=support.partition_month(dict(path=str(path),output=str(td/'out'),conf='test',month='2024-03'))
            self.assertEqual(info['rows'],n)
            t=pa.concat_tables([io.read(td/'out'/f'{s:02}.parquet') for s in range(16)])
            self.assertEqual(sorted(t.to_pylist(),key=lambda r:r['game_id']),sorted(frame.to_pylist(),key=lambda r:r['game_id']))
            bad=frame.set_column(frame.schema.get_field_index('recipient_id'),'recipient_id',frame['opponent_id'])
            io.table(td/'bad.parquet',bad)
            with self.assertRaisesRegex(RuntimeError,'orientation'):
                support.partition_month(dict(path=str(td/'bad.parquet'),output=str(td/'bad_out'),conf='test',month='2024-03'))

class CacheTests(unittest.TestCase):
    def test_partial_explicit_api_fields_merge_without_inventing_source(self):
        self.assertIsNone(cache.adapter(['game_id','source']))
        self.assertEqual(cache.adapter(['game_id','api_source']),'explicit_api_aliases')
        r=cache.normalized_flat(dict(game_id='AbCd1234',api_source='pool',api_status='mate'),'explicit_api_aliases')
        self.assertEqual(r['source'],'pool');self.assertIsNone(r['anchor_ms'])
        conflict=cache.normalized_flat(dict(game_id='AbCd1234',source='pool',api_source='friend'),'explicit_api_aliases')
        self.assertIsNone(conflict['source']);self.assertIn('CONFLICT_SOURCE',conflict['record_errors'])
        headers=cache.pgn_headers(dict(Site='https://lichess.org/AbCd1234',White='Alice',Black='BOB',WhiteElo='1500',BlackElo='1510',TimeControl='180+0',Event='Rated Blitz game'))
        self.assertEqual(headers['white_rating'],1500);self.assertEqual(headers['black_username'],'bob')
        for k in ('source','status','api_start_ms','anchor_ms'):self.assertIsNone(headers.get(k))

    def test_field_merge_preserves_conflicts_and_combines_partial_records(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);gids=['AbCd1234','aBCd1234','Other001']
            io.table(td/'eligible.parquet',pa.table(dict(game_id=gids,local_eligibility=['POTENTIALLY_ELIGIBLE']*3,previous_frame=[False]*3)))
            a=cache.normalized_flat(dict(game_id=gids[0],api_source='pool'),'explicit_api_aliases')
            b=ex.normalize(api_object(gids[0]));b['source']=None
            d=ex.normalize(api_object(gids[1]));e=ex.normalize(api_object(gids[1],'friend'))
            for n,rows in [('a',[a,d]),('b',[b,e])]:io.table(td/(n+'.parquet'),pa.Table.from_pylist(rows,schema=ex.metadata_schema()))
            root,info=cache.aggregate([str(td/'a.parquet'),str(td/'b.parquet')],[str(td/'eligible.parquet')],None,td/'out','t',1,1)
            records={r['game_id']:r for r in io.read(root/'metadata.parquet').to_pylist()}
            self.assertEqual(records[gids[0]]['source'],'pool');self.assertFalse(records[gids[0]]['cached_conflict_or_prior_flag'])
            self.assertIsNone(records[gids[1]]['source']);self.assertTrue(records[gids[1]]['cached_conflict_or_prior_flag'])
            self.assertEqual(len(records),2)

    def test_malformed_cache_cannot_partially_prove_nonpool(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);p=td/'export.ndjson';p.write_text(json.dumps(api_object('AbCd1234','friend'))+'\nBAD JSON\n')
            index=td/'ids.npy';np.save(index,np.array(['AbCd1234'],dtype='S8'))
            rec=dict(path=str(p),kind='raw',adapter='raw_api',signature=io.sig(p))
            info=cache.scan_group(dict(files=[rec],index=str(index),output=str(td/'out'),conf='test'))
            self.assertEqual(info['cache_parse_gaps'],1);self.assertEqual(io.read(td/'out/metadata.parquet').num_rows,0)

    def test_generic_parquet_filename_is_discovered_and_original_files_reused(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);project=td/'project';folder=project/'output'/'unusual_folder';folder.mkdir(parents=True)
            good=folder/'odd_name.parquet';io.table(good,pa.table(dict(game_id=['AbCd1234'],api_source=['pool'])))
            old=folder/'already_scanned.ndjson';old.write_text(json.dumps(api_object('Other001'))+'\n')
            os.utime(good,(1,1));os.utime(old,(1,1))
            inventory=td/'old.json';io.js(inventory,[dict(path=str(old),signature=io.sig(old))])
            result=cache.discover(project,td/'desktop',project/'new_output',inventory,2)
            self.assertEqual([r['path'] for r in result['files']],[str(good.resolve())])
            self.assertEqual(result['unchanged_original_cache_files_reused'],1)

    def test_symlinked_root_reuses_original_inventory_without_duplicate_files(self):
        # Reproduce macOS /var -> /private/var on every Unix test host.
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);real=td/'real';real.mkdir();alias=td/'alias';alias.symlink_to(real,target_is_directory=True)
            project=alias/'project';folder=project/'output';folder.mkdir(parents=True)
            good=folder/'odd_name.parquet';io.table(good,pa.table(dict(game_id=['AbCd1234'],api_source=['pool'])))
            old=folder/'already_scanned.ndjson';old.write_text(json.dumps(api_object('Other001'))+'\n')
            os.utime(good,(1,1));os.utime(old,(1,1))
            inventory=td/'old.json';io.js(inventory,[dict(path=str(old),signature=io.sig(old))])
            result=cache.discover(project,alias/'desktop',project/'new_output',inventory,2,
                                  extra_roots=[real/'project'/'output'])
            self.assertNotEqual(str(good),str(good.resolve()))
            self.assertEqual([r['path'] for r in result['files']],[str(good.resolve())])
            self.assertEqual(result['unchanged_original_cache_files_reused'],1)
            self.assertEqual(result['parquet_schemas_checked'],1)

    def test_sqlite_snapshot_and_original_status_close_success_and_binding_error(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);target=td/'targets.parquet';io.table(target,pa.table(dict(game_id=['AbCd1234'])))
            db=dl.connect(td/'checkpoint.sqlite3',PREP_CONF,io.sha(target));db.close()
            with assert_sqlite_closed(self):
                self.assertEqual(cache.sqlite_snapshot(td,target)['batches'],[])
                self.assertEqual(run.original_resume.counts(td)['accounted_ids'],0)
            with contextlib.closing(sqlite3.connect(td/'checkpoint.sqlite3')) as db:
                db.execute("UPDATE meta SET value='wrong' WHERE key='config_sha256'");db.commit()
            with assert_sqlite_closed(self):
                with self.assertRaisesRegex(RuntimeError,'bound'):
                    cache.sqlite_snapshot(td,target)
                with self.assertRaisesRegex(RuntimeError,'another fixed sample'):
                    run.original_resume.counts(td)

    def test_sqlite_completed_partial_and_nonreturn_reuse_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);gids=[f'{i:08d}' for i in range(601)]
            rows=[dict(game_id=g,utc_ms=int(core.STARTS[4]),speed_partition='blitz') for g in gids]
            target=td/'targets.parquet';io.table(target,pa.Table.from_pylist(rows));index=td/'ids.npy';np.save(index,np.asarray(gids,dtype='S8'))
            db=dl.connect(td/'checkpoint.sqlite3',PREP_CONF,io.sha(target))
            class Client:
                def get(self,ids):return ('\n'.join(json.dumps(api_object(g)) for g in ids if g!=gids[0])+'\n').encode()
            dl.process_batch(db,0,rows[:300],Client())
            # A successful saved response just before interruption of a second batch.
            dl.response(db,1,0,gids[300:600],Client());db.close()
            with assert_sqlite_closed(self):snapshot=cache.sqlite_snapshot(td,target)
            self.assertEqual(len(snapshot['batches']),1)
            with assert_sqlite_closed(self),patch.object(http.Client,'get',side_effect=AssertionError('network forbidden')):
                info=cache.sqlite_group(dict(db=str(td/'checkpoint.sqlite3'),target=str(target),index=str(index),batches=[0,1],output=str(td/'reuse'),conf='test'))
            self.assertEqual(info['reused_records'],599);self.assertEqual(info['prior_three_pass_nonreturns'],1)
            self.assertEqual(info['partial_batches_recovered'],1)
            self.assertEqual(io.read(td/'reuse/not_returned.parquet')['game_id'].to_pylist(),[gids[0]])

    def test_sqlite_tampered_response_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);rows=[dict(game_id='AbCd1234',utc_ms=int(core.STARTS[4]),speed_partition='blitz')]
            target=td/'targets.parquet';io.table(target,pa.Table.from_pylist(rows));np.save(td/'ids.npy',np.asarray(['AbCd1234'],dtype='S8'))
            db=dl.connect(td/'checkpoint.sqlite3',PREP_CONF,io.sha(target))
            class Client:
                def get(self,ids):return json.dumps(api_object(ids[0])).encode()+b'\n'
            dl.process_batch(db,0,rows,Client());db.execute("UPDATE responses SET raw_sha='bad'");db.commit();db.close()
            with assert_sqlite_closed(self):
                with self.assertRaisesRegex(RuntimeError,'checksum'):
                    cache.sqlite_group(dict(db=str(td/'checkpoint.sqlite3'),target=str(target),index=str(td/'ids.npy'),batches=[0],output=str(td/'reuse'),conf='test'))

class PlanTests(unittest.TestCase):
    def test_download_status_closes_after_success_and_query_error(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);ready=td/'ready';ready.mkdir();folder=td/'download';folder.mkdir()
            io.table(ready/'targets.parquet',pa.table(dict(game_id=['AbCd1234'])))
            db=dl.connect(folder/'checkpoint.sqlite3','test',io.sha(ready/'targets.parquet'));db.close()
            with assert_sqlite_closed(self):
                self.assertEqual(run.show_status(dict(ready=str(ready))),(1,0))
            with contextlib.closing(sqlite3.connect(folder/'checkpoint.sqlite3')) as db:
                db.execute('DROP TABLE batches');db.commit()
            with assert_sqlite_closed(self):
                with self.assertRaisesRegex(sqlite3.OperationalError,'no such table'):
                    run.show_status(dict(ready=str(ready)))

    def test_reduced_downloader_end_to_end_and_resume_without_duplicate_calls(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);root=td/'run';ready=root/'retrieval'/'plan'/'ready';ready.mkdir(parents=True)
            gid='AbCd1234'
            io.table(ready/'targets.parquet',pa.table(dict(game_id=[gid],utc_ms=[int(core.STARTS[4])],speed_partition=['blitz'])))
            io.table(root/'eligible.parquet',pa.table(dict(game_id=[gid],month=['2024-03'],previous_frame=[False],local_eligibility=['POTENTIALLY_ELIGIBLE'])))
            metadata_empty(root/'metadata.parquet');io.js(ready/'summary.json',dict(remaining_api_targets=1))
            io.js(ready/'ANALYSIS_INPUTS_PRIVATE.json',dict(frame_preserved=True))
            pointer=dict(root=str(root),ready=str(ready),config_sha256='test',original_api_snapshot=None,
                         eligibility_ledgers=[str(root/'eligible.parquet')],merged_metadata=str(root/'metadata.parquet'),prior_nonreturns=[])
            calls=[]
            class Client:
                def get(self,ids):calls.append(list(ids));return ('\n'.join(json.dumps(api_object(g)) for g in ids)+'\n').encode()
            desktop=td/'desktop';desktop.mkdir()
            a=SimpleNamespace(mode='download',project_root=td/'project',desktop=desktop,workers=2,memory_gb=2)
            with assert_sqlite_closed(self),patch.object(run,'verify_package'),patch.object(run,'load_plan',return_value=pointer),\
                 patch.object(run.original_resume,'wait_for_other_collectors'),patch.object(dl,'check_other_api_jobs'),\
                 patch.object(http,'Client',return_value=Client()),patch.object(Path,'home',return_value=td/'home'):
                run.download(a);run.download(a)
            self.assertEqual(calls,[[gid]])
            final=ready.parent/'download/ANALYSIS_INPUTS_PRIVATE.json';self.assertTrue(final.exists())
            self.assertFalse(io.load(final)['expanded_effects_estimated'])
            merged=io.read(io.load(final)['merged_candidate_metadata']).to_pylist()[0]
            self.assertEqual(merged['source'],'pool');self.assertFalse(merged['cached_conflict_or_prior_flag'])

    def test_multiprocess_complete_retrieval_plan_with_monthly_parquets(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);ledgers=[];metadata=[];original=[];expected=[]
            for m,month in enumerate(ex.MONTHS):
                g=f'{m:08d}';frame=dict(game_id=g,utc_ms=int(core.STARTS[m]),speed_partition='blitz',
                  month=month,previous_frame=False,retrieval_rank=bytes([20-m])*32,
                  local_eligibility='AUTHOR_GAME' if m==0 else 'POTENTIALLY_ELIGIBLE')
                p=td/(month+'.parquet');io.table(p,pa.Table.from_pylist([frame]));ledgers.append(str(p));original.append({k:frame[k] for k in ('game_id','utc_ms','speed_partition')})
                if m%3:
                    obj=api_object(g);obj['createdAt']=int(core.STARTS[m])+123;obj['lastMoveAt']=int(core.STARTS[m])+100123
                    metadata.append(ex.normalize(obj))
                elif m:expected.append(g)
            io.table(td/'existing.parquet',pa.Table.from_pylist(metadata,schema=ex.metadata_schema()))
            io.table(td/'original_targets.parquet',pa.Table.from_pylist(original))
            index,receipt=run.candidate_index(ledgers,td/'index','test',1,2)
            self.assertEqual(receipt['rows'],20)
            merged,_=cache.aggregate([str(td/'existing.parquet')],ledgers,index/'game_ids.npy',td/'merged','test',1,2)
            self.assertTrue((merged/'empty_metadata.parquet').exists())
            inputs=dict(original_targets=str(td/'original_targets.parquet'),frame=ledgers,cache=str(td/'existing.parquet'),lineage_sha256='test')
            with patch.object(run,'FRAME_ROWS',21),patch.object(run,'ORIGINAL_TARGETS',21):
                ready,summary=run.final_plan(ledgers,merged/'metadata.parquet',[],td/'plan','test',2,2,inputs)
            self.assertEqual(summary['frame_rows'],21);self.assertEqual(summary['remaining_api_targets'],len(expected))
            targets=io.read(ready/'targets.parquet')['game_id'].to_pylist()
            self.assertEqual(targets,list(reversed(expected)))
            self.assertTrue((ready/'ANALYSIS_INPUTS_PRIVATE.json').exists())

    def test_denominator_all_endings_and_ineligible_rows_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);gids=[f'{i:08d}' for i in range(9)]
            frame=pa.table(dict(game_id=gids,utc_ms=[int(core.STARTS[4])]*9,speed_partition=['blitz']*9,
                        local_eligibility=['AUTHOR_GAME','INCOMPLETE_97D_HISTORY','FEWER_THAN_FIVE_PRIOR_DECISIONS']+['POTENTIALLY_ELIGIBLE']*6,
                        previous_frame=[False]*3+[True]+[False]*5,retrieval_rank=[bytes([i])*32 for i in range(9)]))
            io.table(td/'ledger.parquet',frame)
            records=[]
            for k,status,source in [(4,'mate','friend'),(5,'timeout','pool'),(6,'outoftime','pool')]:
                r=ex.normalize(api_object(gids[k],source));r['status']=status;r['cached_conflict_or_prior_flag']=False;records.append(r)
            schema=ex.metadata_schema().append(pa.field('cached_conflict_or_prior_flag',pa.bool_()))
            io.table(td/'metadata.parquet',pa.Table.from_pylist(records,schema=schema))
            io.table(td/'absent.parquet',pa.table(dict(game_id=[gids[7]])))
            info=run.plan_month(dict(ledger=str(td/'ledger.parquet'),metadata=str(td/'metadata.parquet'),notreturned=[str(td/'absent.parquet')],month='2024-03',output=str(td/'plan'),conf='test',memory=1))
            self.assertEqual(info['rows'],9);self.assertEqual(info['counts']['LOCAL_RULE_EXCLUSION'],3)
            self.assertEqual(info['counts']['LOCAL_POOL_METADATA_READY'],2)
            self.assertEqual(info['counts']['PRIOR_API_NONRETURN_GAP'],1)
            self.assertEqual(io.read(td/'plan/targets.parquet')['game_id'].to_pylist(),[gids[8]])
            self.assertEqual(io.read(td/'plan/ledger.parquet').num_rows,9)

    def test_stage_resume_reuses_and_tampering_fails(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);calls=[]
            def produce(tmp):calls.append(True);(tmp/'payload.txt').write_text('valid');return dict(ok=True)
            stable_stage(td/'stage','fixed',produce);stable_stage(td/'stage','fixed',produce)
            self.assertEqual(len(calls),1)
            (td/'stage/payload.txt').write_text('bad')
            with self.assertRaisesRegex(RuntimeError,'size|checksum'):stable_stage(td/'stage','fixed',produce)

if __name__=='__main__':unittest.main()
