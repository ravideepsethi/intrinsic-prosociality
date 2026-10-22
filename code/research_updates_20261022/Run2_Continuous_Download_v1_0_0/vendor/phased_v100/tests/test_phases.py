import contextlib,hashlib,json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from phase_common import *
import sqlite_reuse as reuse
import run_phases as run
import metadata_http as http
import phase_common as pc
import original_resume

def api(gid,start=None,source='pool'):
    start=int(core.STARTS[4]) if start is None else int(start)
    return dict(id=gid,source=source,status='mate',createdAt=start+123,lastMoveAt=start+100123,
        rated=True,variant='standard',speed='blitz',winner='white',clock=dict(initial=180,increment=0),
        players=dict(white=dict(user=dict(id='alice',name='Alice'),rating=1500),
                     black=dict(user=dict(id='bob',name='Bob'),rating=1510)))

def targets(path,ids):
    io.table(path,pa.table(dict(game_id=ids,utc_ms=[int(core.STARTS[4])]*len(ids),speed_partition=['blitz']*len(ids))))

class FakeClient:
    def __init__(self,*args):self.requests=0;self.http_seconds=0.;self.calls=[]
    def get(self,ids):
        self.requests+=1;self.calls.append(list(ids))
        return ('\n'.join(json.dumps(api(g)) for g in ids)+'\n').encode()

class PhaseTests(unittest.TestCase):
    def test_exact_nested_boundaries_and_old_frame(self):
        self.assertEqual(phase_of(bytes(32)),10)
        for p,next_p in ((10,25),(25,50),(50,100)):
            t=threshold(p)
            self.assertEqual(phase_of((int.from_bytes(t,'big')-1).to_bytes(32,'big')),p)
            self.assertEqual(phase_of(t),next_p)
            self.assertEqual(phase_of(t,True),0)
        self.assertEqual(phase_of(bytes([255])*32),100)
        with tempfile.TemporaryDirectory() as td:
            c=io.conn(Path(td)/'spill',1,1)
            try:
                ranks=[bytes(32),threshold(10),threshold(25),threshold(50),bytes([255])*32]
                c.register('f',pa.table(dict(retrieval_rank=ranks*2,previous_frame=[False]*5+[True]*5)))
                got=c.execute('SELECT '+phase_sql()+' FROM f').fetchall()
                self.assertEqual([r[0] for r in got],[10,25,50,100,100,0,0,0,0,0])
            finally:c.close()

    def test_membership_includes_cached_excluded_nonpool_and_nonreturned(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);ids=[f'{i:08d}' for i in range(6)]
            dispositions=['NEEDS_API','LOCAL_POOL_METADATA_READY','LOCAL_RULE_EXCLUSION','EXPLICIT_NONPOOL','PRIOR_API_NONRETURN_GAP','PREVIOUS_FRAME_REUSE']
            frame=pa.table(dict(game_id=ids,utc_ms=[int(core.STARTS[4])]*6,speed_partition=['blitz']*6,
                retrieval_rank=[bytes(32)]*6,previous_frame=[False]*5+[True],retrieval_disposition=dispositions))
            io.table(td/'ledger.parquet',frame)
            job=dict(ledger=str(td/'ledger.parquet'),metadata=[],nonreturns=[],refresh_metadata=False,
                     month='2024-03',memory=1,conf='test',output=str(td/'out'))
            result=run.month_plan(job)
            self.assertEqual(sum(r['rows'] for r in result['counts'] if r['phase_percent']==10),5)
            self.assertEqual(io.read(td/'out/targets_10.parquet')['game_id'].to_pylist(),[ids[0]])
            self.assertEqual(run.month_plan(job)['rows'],6)

    def test_multiprocess_full_month_plan_and_cached_selection(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);ledgers=[];expected={p:[] for p in PHASES};n=0
            for m,month in enumerate(ex.MONTHS):
                rows=[]
                for k in range(24):
                    gid=f'{m*100+k:08d}';rank=hashlib.sha256(ex.ORDER_SEED+gid.encode()).digest()
                    old=k==0;disposition='PREVIOUS_FRAME_REUSE' if old else ('LOCAL_POOL_METADATA_READY' if k%3==0 else 'NEEDS_API')
                    rows.append(dict(game_id=gid,utc_ms=int(core.STARTS[m]),speed_partition='blitz',retrieval_rank=rank,
                                     previous_frame=old,retrieval_disposition=disposition))
                    if disposition=='NEEDS_API':expected[phase_of(rank)].append((rank,gid))
                path=td/(month+'.parquet');io.table(path,pa.Table.from_pylist(rows));ledgers.append(str(path));n+=len(rows)
            up=dict(ledgers=ledgers,summary=dict(remaining_api_targets=sum(map(len,expected.values()))))
            args=SimpleNamespace(workers=2,memory_gb=2)
            with patch.object(run,'FRAME_ROWS',n),patch.object(ex,'OLD_ROWS',21):
                plan,summary=run.build_plan(up,td/'run',args,'test',str(td/'unused.parquet'),[],False)
            self.assertEqual(summary['frame_rows'],504)
            for p in PHASES:
                self.assertEqual(io.read(plan/f'targets_{p}.parquet')['game_id'].to_pylist(),[g for h,g in sorted(expected[p])])
            self.assertEqual(summary['phases'][-1]['additional_frame_rows'],483)
            self.assertEqual(sum(r['cached_pool_rows'] for r in summary['phases'][-1:]),21*7)

    def test_fresh_sqlite_conflicts_do_not_disappear(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);gid='AbCd1234';frame=pa.table(dict(game_id=[gid],month=['2024-03'],utc_ms=[int(core.STARTS[4])],
                speed_partition=['blitz'],retrieval_rank=[bytes(32)],previous_frame=[False],local_eligibility=['POTENTIALLY_ELIGIBLE']))
            io.table(td/'frame.parquet',frame)
            for i,source in enumerate(('pool','friend')):
                io.table(td/f'm{i}.parquet',pa.Table.from_pylist([ex.normalize(api(gid,source=source))],schema=ex.metadata_schema()))
            merged,_=cache.aggregate([str(td/'m0.parquet'),str(td/'m1.parquet')],[str(td/'frame.parquet')],None,td/'merged','t',1,1)
            result=run.month_plan(dict(ledger=str(td/'frame.parquet'),metadata=[str(merged/'metadata.parquet')],nonreturns=[],
                refresh_metadata=True,memory=1,month='2024-03',conf='test',output=str(td/'out')))
            self.assertEqual(result['target_counts']['10'],1)
            self.assertTrue(io.read(merged/'metadata.parquet')['cached_conflict_or_prior_flag'][0].as_py())

class SQLiteTests(unittest.TestCase):
    def test_completed_partial_and_nonreturn_reuse_is_bound_and_readonly(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);ids=[f'{i:08d}' for i in range(601)];target=td/'targets.parquet';targets(target,ids)
            np.save(td/'index.npy',np.asarray(ids,dtype='S8'))
            db=dl.connect(td/'checkpoint.sqlite3',PREP_CONF,io.sha(target))
            class Missing(FakeClient):
                def get(self,requested):return ('\n'.join(json.dumps(api(g)) for g in requested if g!=ids[0])+'\n').encode()
            rows=io.read(target).to_pylist();dl.process_batch(db,0,rows[:300],Missing())
            dl.response(db,1,0,ids[300:600],Missing());db.close()
            before=io.sha(td/'checkpoint.sqlite3')
            rec=reuse.inspect_database(dict(path=str(td/'checkpoint.sqlite3'),targets=[str(target)]))
            self.assertEqual(rec['status'],'BOUND_API_CHECKPOINT')
            args=SimpleNamespace(workers=2)
            with patch.object(http.Client,'get',side_effect=AssertionError('Network forbidden')):
                parts,missing,audit=reuse.import_sources([rec],dict(index=str(td/'index.npy')),td/'reuse',args,'test')
            self.assertEqual(audit[0]['reused_records'],599)
            self.assertEqual(audit[0]['prior_nonreturns'],1)
            self.assertEqual(io.read(missing[0])['game_id'].to_pylist(),[ids[0]])
            self.assertEqual(io.sha(td/'checkpoint.sqlite3'),before)

    def test_tampered_response_or_target_binding_stops_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);target=td/'targets.parquet';targets(target,['AbCd1234']);np.save(td/'index.npy',np.asarray(['AbCd1234'],dtype='S8'))
            db=dl.connect(td/'checkpoint.sqlite3',PREP_CONF,io.sha(target));dl.process_batch(db,0,io.read(target).to_pylist(),FakeClient())
            db.execute("UPDATE responses SET raw_sha='wrong'");db.commit();db.close()
            rec=reuse.inspect_database(dict(path=str(td/'checkpoint.sqlite3'),targets=[str(target)]))
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                reuse.import_sources([rec],dict(index=str(td/'index.npy')),td/'reuse',SimpleNamespace(workers=1),'test')
            target.rename(td/'hidden.parquet')
            with self.assertRaisesRegex(RuntimeError,'matching target'):
                reuse.inspect_database(dict(path=str(td/'checkpoint.sqlite3'),targets=[]))

    def test_explicit_sqlite_fields_reused_and_unknown_source_not_inferred(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);dbpath=td/'cache.db'
            with contextlib.closing(sqlite3.connect(dbpath)) as db:
                db.execute('CREATE TABLE verified(game_id TEXT,api_source TEXT)')
                db.execute('INSERT INTO verified VALUES (?,?)',('AbCd1234','friend'))
                db.execute('CREATE TABLE unverified(game_id TEXT,source TEXT)')
                db.execute('INSERT INTO unverified VALUES (?,?)',('Other001','pool'));db.commit()
            rec=reuse.inspect_database(dict(path=str(dbpath),targets=[]))
            self.assertEqual(len(rec['tables']),1);self.assertEqual(rec['tables'][0]['mode'],'explicit_api_aliases')
            np.save(td/'index.npy',np.asarray(['AbCd1234','Other001'],dtype='S8'))
            parts,missing,audit=reuse.import_sources([rec],dict(index=str(td/'index.npy')),td/'reuse',SimpleNamespace(workers=2),'test')
            rows=io.read(parts[0]).to_pylist()
            self.assertEqual([r['game_id'] for r in rows],['AbCd1234']);self.assertEqual(rows[0]['source'],'friend')
            self.assertIsNone(rows[0]['anchor_ms'])

    def test_absent_unrelated_and_symlink_paths_are_reported(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);p=td/'unrelated.db'
            with contextlib.closing(sqlite3.connect(p)) as db:
                db.execute('CREATE TABLE counters(name TEXT,value INTEGER)');db.commit()
            alias=td/'alias.db';alias.symlink_to(p)
            self.assertEqual(reuse.inspect_database(dict(path=str(alias),targets=[]))['status'],'NO_SUPPORTED_API_METADATA_SCHEMA')
            self.assertEqual(reuse.inspect_database(dict(path=str(td/'missing.db'),targets=[]))['status'],'ABSENT')
            other=td/'another_engine.db';other.write_bytes(b'Not a SQLite database')
            self.assertEqual(reuse.inspect_database(dict(path=str(other),targets=[]))['status'],'NOT_A_SQLITE_DATABASE')

class DownloadTests(unittest.TestCase):
    def test_authenticated_pipeline_reuses_sqlite_and_stops_at_requested_phase(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);project=td/'project';desktop=td/'desktop';desktop.mkdir()
            config=dict(version='1.0.1',package_sha256=UPSTREAM_PACKAGE_SHA)
            original_conf=io.cfgsha(config);plan_conf='fixture_plan'
            upstream=project/'upstream'/original_conf[:12];upstream.mkdir(parents=True);io.js(upstream/'config.json',config)
            ledgers=[];target_rows=[];chosen=[];starts={};serial=10000
            for m,month in enumerate(ex.MONTHS):
                rows=[]
                for band in (0,10,25):
                    while True:
                        serial+=1;gid=f'{serial:08d}';rank=hashlib.sha256(ex.ORDER_SEED+gid.encode()).digest()
                        if band==0 or phase_of(rank)==band:break
                    starts[gid]=int(core.STARTS[m]);old=band==0
                    row=dict(game_id=gid,utc_ms=int(core.STARTS[m]),speed_partition='blitz',month=month,
                        retrieval_rank=rank,previous_frame=old,local_eligibility='POTENTIALLY_ELIGIBLE',
                        retrieval_disposition='PREVIOUS_FRAME_REUSE' if old else 'NEEDS_API')
                    rows.append(row)
                    if not old:target_rows.append({k:row[k] for k in ('game_id','utc_ms','speed_partition')});chosen.append(gid)
                def write_month(out,rows=rows,month=month):
                    io.table(out/'ledger.parquet',pa.Table.from_pylist(rows));return dict(month=month)
                stage,_=io.stage(upstream/'months'/month,plan_conf,write_month);ledgers.append(str(stage/'ledger.parquet'))
            def make_metadata(out):metadata_empty(out/'metadata.parquet')
            merged,_=io.stage(upstream/'merged',plan_conf,make_metadata)
            def make_index_fixture(out):np.save(out/'game_ids.npy',np.asarray(sorted(chosen),dtype='S8'));return dict(rows=len(chosen))
            io.stage(upstream/'candidate_index',original_conf,make_index_fixture)
            ready=upstream/'ready'
            manifest=dict(denominator=ledgers,merged_candidate_metadata=str(merged/'metadata.parquet'),
                target_file=str(ready/'targets.parquet'),original_cached_metadata='original.parquet',subsequent_requirements=['frozen estimates'])
            def make_ready(out):
                io.table(out/'targets.parquet',pa.Table.from_pylist(target_rows))
                io.js(out/'summary.json',dict(frame_rows=63,remaining_api_targets=42))
                io.js(out/'ANALYSIS_INPUTS_PRIVATE.json',manifest)
            io.stage(ready,plan_conf,make_ready)
            pointer=dict(root=str(upstream),ready=str(ready),config_sha256=plan_conf,merged_metadata=str(merged/'metadata.parquet'),
                eligibility_ledgers=ledgers,prior_nonreturns=[],original_api_snapshot=None)
            io.js(desktop/'RUN2_LOCAL_FIRST_LATEST_PRIVATE.json',pointer)
            source=td/'found.db'
            with contextlib.closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE metadata(game_id TEXT,api_source TEXT)')
                db.execute('INSERT INTO metadata VALUES (?,?)',(chosen[0],'friend'));db.commit()
            io.js(upstream/'CACHE_INVENTORY_PRIVATE.json',dict(unconsumed=[dict(path=str(source),reason='UNSUPPORTED_SQLITE_SCHEMA_NOT_USED')]))
            pkg=td/'package';pkg.mkdir();(pkg/'PACKAGE_MANIFEST.sha256').write_text('fixture')
            a=SimpleNamespace(mode='download',project_root=project,desktop=desktop,plan=None,workers=2,memory_gb=2,extra_sqlite=[],through=10)
            class Client(FakeClient):
                def get(self,ids):
                    self.requests+=1;self.calls.append(list(ids))
                    return ('\n'.join(json.dumps(api(g,starts[g])) for g in ids)+'\n').encode()
            client=Client()
            patched=dict(UPSTREAM_RUN=upstream.name,UPSTREAM_PLAN=plan_conf,FRAME_ROWS=63,UPSTREAM_TARGETS=42)
            with patch.multiple(pc,**patched),patch.multiple(run,**patched),patch.object(ex,'OLD_ROWS',21),\
                 patch.object(run,'verify_release'),patch.object(run,'PACKAGE',pkg),\
                 patch.object(original_resume,'wait_for_other_collectors'),patch.object(dl,'check_other_api_jobs'),\
                 patch.object(http,'Client',return_value=client),patch.object(Path,'home',return_value=td/'home'):
                run.run(a)
                first_calls=[g for batch in client.calls for g in batch]
                self.assertEqual(len(first_calls),20)
                self.assertTrue(all(phase_of(hashlib.sha256(ex.ORDER_SEED+g.encode()).digest())==10 for g in first_calls))
                a.through=25;run.run(a);run.run(a)
                self.assertEqual(len([g for batch in client.calls for g in batch]),41)
                self.assertNotIn(chosen[0],[g for batch in client.calls for g in batch])
                self.assertEqual(len(client.calls),2)
                # A changed upstream Parquet is rejected before another request.
                Path(ledgers[0]).write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'size|checksum'):
                    run.run(a)
                self.assertEqual(len(client.calls),2)

    def test_completed_band_resume_and_next_band_never_refetch(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);plan=td/'plan';plan.mkdir();first=[f'{i:08d}' for i in range(305)];second=['Next0001','Next0002']
            targets(plan/'targets_10.parquet',first);targets(plan/'targets_25.parquet',second)
            client=FakeClient();a=SimpleNamespace()
            with patch.object(http,'Client',return_value=client),patch.object(Path,'home',return_value=td/'home'):
                run.download_band(td/'run',plan,10,'test',a)
                run.download_band(td/'run',plan,10,'test',a)
                run.download_band(td/'run',plan,25,'test',a)
            self.assertEqual([g for batch in client.calls for g in batch],first+second)
            self.assertEqual(len(client.calls),3)

    def test_partial_response_survives_interruption_inside_batch(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);plan=td/'plan';plan.mkdir();ids=['AbCd1234','Other001'];targets(plan/'targets_10.parquet',ids)
            class Interrupted(FakeClient):
                def get(self,requested):
                    self.calls.append(list(requested));self.requests+=1
                    if self.requests==2:raise KeyboardInterrupt()
                    return (json.dumps(api(ids[0]))+'\n').encode()
            broken=Interrupted();good=FakeClient()
            with patch.object(http,'Client',return_value=broken),patch.object(Path,'home',return_value=td/'home'):
                with self.assertRaises(KeyboardInterrupt):run.download_band(td/'run',plan,10,'test',SimpleNamespace())
            with patch.object(http,'Client',return_value=good),patch.object(Path,'home',return_value=td/'home'):
                run.download_band(td/'run',plan,10,'test',SimpleNamespace())
            self.assertEqual(good.calls,[[ids[1]]])
            report=io.load(td/'run/download/10/finished/SUMMARY.json');self.assertEqual(report['returned'],2)

    def test_nonreturns_preserved_with_zero_new_calls_on_resume(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);plan=td/'plan';plan.mkdir();targets(plan/'targets_10.parquet',['AbCd1234'])
            class Missing(FakeClient):
                def get(self,ids):self.calls.append(ids);self.requests+=1;return b''
            client=Missing()
            with patch.object(http,'Client',return_value=client),patch.object(Path,'home',return_value=td/'home'):
                run.download_band(td/'run',plan,10,'test',SimpleNamespace())
                run.download_band(td/'run',plan,10,'test',SimpleNamespace())
            self.assertEqual(len(client.calls),3)
            self.assertEqual(io.read(td/'run/download/10/finished/not_returned.parquet')['game_id'].to_pylist(),['AbCd1234'])

    def test_cumulative_manifest_keeps_cached_rows_and_all_nonreturns(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);root=td/'run';plan=td/'plan';plan.mkdir();desktop=td/'desktop';desktop.mkdir()
            ids=['AbCd1234','Cache001'];ledger=td/'ledger.parquet'
            io.table(ledger,pa.table(dict(game_id=ids,month=['2024-03']*2,previous_frame=[False]*2,
                local_eligibility=['POTENTIALLY_ELIGIBLE']*2)))
            io.table(td/'cached.parquet',pa.Table.from_pylist([ex.normalize(api(ids[1]))],schema=ex.metadata_schema()))
            targets(plan/'targets_10.parquet',[ids[0]])
            with patch.object(http,'Client',return_value=FakeClient()),patch.object(Path,'home',return_value=td/'home'):
                run.download_band(root,plan,10,'test',SimpleNamespace())
            io.js(root/'SQLITE_AUDIT.json',[]);io.js(plan/'by_month.json',[dict(month='2024-03',phase_percent=10,disposition='NEEDS_API',rows=1)])
            state=dict(plan=str(plan),metadata=str(td/'cached.parquet'),nonreturns=[],summary=dict(phases=[dict(through_percent=10,cumulative_targets=1)]))
            up=dict(eligibility_ledgers=[str(ledger)],ledgers=[str(ledger)],manifest=dict(original_cached_metadata='original.parquet',subsequent_requirements=['frozen estimates']))
            result=run.publish_phase(up,state,root,SimpleNamespace(memory_gb=1,workers=1,desktop=desktop),'test',10)
            manifest=io.load(root/'phase_results/10/ANALYSIS_INPUTS_PRIVATE.json')
            self.assertEqual(sorted(io.read(manifest['merged_candidate_metadata'])['game_id'].to_pylist()),sorted(ids))
            self.assertIn('retrieval_rank',manifest['additional_frame_selection_sql'])
            self.assertFalse(result['behavioral_estimates_computed']);self.assertTrue(manifest['full_historical_and_prospective_anchor_stream_required'])

if __name__=='__main__':unittest.main()
