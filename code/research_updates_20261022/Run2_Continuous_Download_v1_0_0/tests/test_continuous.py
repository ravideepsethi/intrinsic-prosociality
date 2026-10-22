import contextlib
import hashlib
import json
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from continuous_common import *
import continuous_common as common
import run_continuous as run
import checkpoint_75 as middle
from progress_eta import Progress


def api(gid,start=None):
    start=int(core.STARTS[4]) if start is None else int(start)
    return dict(id=gid,source='pool',status='mate',createdAt=start+123,lastMoveAt=start+100123,
        rated=True,variant='standard',speed='blitz',winner='white',clock=dict(initial=180,increment=0),
        players=dict(white=dict(user=dict(id='alice',name='Alice'),rating=1500),
                     black=dict(user=dict(id='bob',name='Bob'),rating=1510)))


class FakeClient:
    def __init__(self,starts=None,observer=None):
        self.requests=0;self.http_seconds=0.;self.calls=[];self.starts=starts or {};self.observer=observer
    def get(self,ids):
        if self.observer:self.observer(ids)
        self.requests+=1;self.calls.append(list(ids))
        return ('\n'.join(json.dumps(api(g,self.starts.get(g))) for g in ids)+'\n').encode()


def targets(path,ids):
    io.table(path,pa.table(dict(game_id=ids,utc_ms=[int(core.STARTS[4])]*len(ids),speed_partition=['blitz']*len(ids))))


def rank_ids(n,lo,hi,start=0):
    found=[];serial=start
    while len(found)<n:
        serial+=1;gid=f'{serial:08d}';h=hashlib.sha256(ex.ORDER_SEED+gid.encode()).digest()
        if lo<=int.from_bytes(h,'big')<hi:found.append((h,gid))
    return [g for _,g in sorted(found)],serial


class ETATests(unittest.TestCase):
    def test_resumed_ids_do_not_inflate_rate_and_both_etas_are_correct(self):
        clock=[0.];logs=[]
        p=Progress(1000,{25:1600,50:2200,75:2800,100:3400},10,logs.append,clock=lambda:clock[0])
        clock[0]=60
        self.assertEqual(p.snapshot()['rate'],10)
        p.advance(300)
        s=p.snapshot()
        self.assertEqual(s['rate'],5)
        self.assertEqual(s['next_seconds'],60)
        self.assertEqual(s['finish_seconds'],420)
        p.emit();self.assertIn('ETA next 25%',logs[-1]);self.assertIn('ETA finish 100%',logs[-1])
        self.assertIn('5.00 IDs/s (this run)',logs[-1])

    def test_export_pause_is_excluded_and_waits_update_eta(self):
        clock=[0.]
        p=Progress(0,{25:400,50:600,75:800,100:1000},10,lambda s:None,clock=lambda:clock[0])
        clock[0]=60;p.advance(300)
        with p.local_work('exporting'):
            clock[0]=660
            self.assertEqual(p.snapshot()['rate'],5)
        self.assertEqual(p.snapshot()['rate'],5)
        clock[0]=720
        self.assertEqual(p.snapshot()['rate'],2.5)
        p.report_done(25);self.assertEqual(p.snapshot()['next_percent'],50)

    def test_idle_heartbeat_shows_both_etas(self):
        logs=[]
        with Progress(0,{25:100,50:200,75:300,100:400},10,logs.append,interval=.01):
            time.sleep(.045)
        self.assertGreaterEqual(len(logs),2)
        self.assertTrue(all('ETA next 25%' in s and 'ETA finish 100%' in s for s in logs))


class SnapshotTests(unittest.TestCase):
    def test_boundary_batch_filters_excess_preserves_nonreturns_and_never_refetches(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            before,serial=rank_ids(301,1<<255,int.from_bytes(LIMIT75,'big'))
            after,_=rank_ids(309,int.from_bytes(LIMIT75,'big'),1<<256,serial)
            ids=before+after;target=td/'targets.parquet';targets(target,ids)
            db=dl.connect(td/'checkpoint.sqlite3','test',io.sha(target))
            class Missing(FakeClient):
                def get(self,requested):
                    self.calls.append(list(requested));self.requests+=1
                    return ('\n'.join(json.dumps(api(g)) for g in requested if g!=before[0])+'\n').encode()
            client=Missing()
            try:
                for k,rows in enumerate(dl.batches(target)):
                    if k==2:break
                    dl.process_batch(db,k,rows,client)
                self.assertTrue(middle.prefix_available(db,301))
                call_count=len(client.calls)
                result,receipt=middle.export_prefix(db,target,301,td/'snapshot','snapshot_conf')
                self.assertEqual(receipt['requested'],301);self.assertEqual(receipt['returned'],300)
                self.assertEqual(set(io.read(result/'downloaded_metadata.parquet')['game_id'].to_pylist()),set(before[1:]))
                self.assertEqual(io.read(result/'not_returned.parquet')['game_id'].to_pylist(),[before[0]])
                middle.export_prefix(db,target,301,td/'snapshot','snapshot_conf')
                self.assertEqual(len(client.calls),call_count)
                for k,rows in enumerate(dl.batches(target)):dl.process_batch(db,k,rows,client)
                self.assertEqual(client.calls[-1],ids[600:])
                full,_=dl.export_saved(db,target,td/'full','test')
                self.assertEqual(pq.ParquetFile(full/'downloaded_metadata.parquet').metadata.num_rows,609)
            finally:db.close()

    def test_missing_prefix_and_bad_rank_boundary_fail_before_export(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);before,serial=rank_ids(1,1<<255,int.from_bytes(LIMIT75,'big'))
            after,_=rank_ids(1,int.from_bytes(LIMIT75,'big'),1<<256,serial)
            target=td/'target.parquet';targets(target,after+before)
            db=dl.connect(td/'db','test',io.sha(target))
            try:
                with self.assertRaisesRegex(RuntimeError,'prefix'):
                    middle.export_prefix(db,target,1,td/'out','t')
                dl.process_batch(db,0,io.read(target).to_pylist(),FakeClient())
                with self.assertRaisesRegex(RuntimeError,'rank interval'):
                    middle.export_prefix(db,target,1,td/'out','t')
            finally:db.close()

    def test_zero_length_prefix_and_selection_use_exact_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);after,_=rank_ids(2,int.from_bytes(LIMIT75,'big'),1<<256)
            target=td/'target.parquet';targets(target,after)
            db=dl.connect(td/'db','test',io.sha(target))
            try:
                out,r=middle.export_prefix(db,target,0,td/'out','t')
                self.assertEqual(r['requested'],0)
                self.assertEqual(pq.ParquetFile(out/'downloaded_metadata.parquet').metadata.num_rows,0)
            finally:db.close()
            self.assertIn(LIMIT75.hex(),selection(75))
            self.assertIn('NOT f.previous_frame',selection(75))


def fixture(td):
    project=td/'project';desktop=td/'desktop';desktop.mkdir()
    config=dict(version='1.0.1',package_sha256=pc.UPSTREAM_PACKAGE_SHA)
    original_conf=io.cfgsha(config);plan_conf='fixture_plan'
    upstream=project/'upstream'/original_conf[:12];upstream.mkdir(parents=True);io.js(upstream/'config.json',config)
    ledgers=[];target_rows=[];chosen=[];starts={};serial=20000;cached=[];frame_rows=0
    scale=1<<256
    for m,month in enumerate(ex.MONTHS):
        rows=[]
        groups=[(0,1,0,scale),(10,1,0,scale//10),(25,1,scale//10,scale//4),
                (50,1,scale//4,scale//2),(75,17,scale//2,scale*3//4),(100,17,scale*3//4,scale),
                ('cache',1,scale//2,scale*3//4),('exclude',1,scale//2,scale*3//4),('nonpool',1,scale//2,scale*3//4)]
        for band,n,lo,hi in groups:
            ids,serial=rank_ids(n,lo,hi,serial)
            for gid in ids:
                starts[gid]=int(core.STARTS[m]);old=band==0
                disposition=('PREVIOUS_FRAME_REUSE' if old else 'LOCAL_POOL_METADATA_READY' if band=='cache'
                             else 'LOCAL_RULE_EXCLUSION' if band=='exclude' else 'EXPLICIT_NONPOOL' if band=='nonpool' else 'NEEDS_API')
                row=dict(game_id=gid,utc_ms=int(core.STARTS[m]),speed_partition='blitz',month=month,
                    retrieval_rank=hashlib.sha256(ex.ORDER_SEED+gid.encode()).digest(),previous_frame=old,
                    local_eligibility='EXCLUDED' if band=='exclude' else 'POTENTIALLY_ELIGIBLE',retrieval_disposition=disposition)
                rows.append(row)
                if not old:chosen.append(gid)
                if disposition=='NEEDS_API':target_rows.append({k:row[k] for k in ('game_id','utc_ms','speed_partition')})
                if band in ('cache','nonpool'):
                    raw=api(gid,starts[gid])
                    if band=='nonpool':raw['source']='friend'
                    cached.append(ex.normalize(raw))
        def write_month(out,rows=rows,month=month):
            io.table(out/'ledger.parquet',pa.Table.from_pylist(rows));return dict(month=month)
        stage,_=io.stage(upstream/'months'/month,plan_conf,write_month);ledgers.append(str(stage/'ledger.parquet'));frame_rows+=len(rows)
    def make_metadata(out):io.table(out/'metadata.parquet',pa.Table.from_pylist(cached,schema=ex.metadata_schema()))
    merged,_=io.stage(upstream/'merged',plan_conf,make_metadata)
    def make_index(out):np.save(out/'game_ids.npy',np.asarray(sorted(chosen),dtype='S8'));return dict(rows=len(chosen))
    io.stage(upstream/'candidate_index',original_conf,make_index)
    ready=upstream/'ready'
    manifest=dict(denominator=ledgers,merged_candidate_metadata=str(merged/'metadata.parquet'),
        target_file=str(ready/'targets.parquet'),original_cached_metadata='original.parquet',subsequent_requirements=['frozen estimates'])
    def make_ready(out):
        io.table(out/'targets.parquet',pa.Table.from_pylist(target_rows))
        io.js(out/'summary.json',dict(frame_rows=frame_rows,remaining_api_targets=len(target_rows)))
        io.js(out/'ANALYSIS_INPUTS_PRIVATE.json',manifest)
    io.stage(ready,plan_conf,make_ready)
    pointer=dict(root=str(upstream),ready=str(ready),config_sha256=plan_conf,merged_metadata=str(merged/'metadata.parquet'),
        eligibility_ledgers=ledgers,prior_nonreturns=[],original_api_snapshot=None)
    io.js(desktop/'RUN2_LOCAL_FIRST_LATEST_PRIVATE.json',pointer)
    io.js(upstream/'CACHE_INVENTORY_PRIVATE.json',dict(unconsumed=[]))
    a=SimpleNamespace(mode='download',project_root=project,desktop=desktop,plan=None,phase_pointer=None,
        workers=2,memory_gb=2,extra_sqlite=[],through=10,eta_seconds=30)
    patches=dict(UPSTREAM_RUN=upstream.name,UPSTREAM_PLAN=plan_conf,FRAME_ROWS=frame_rows,UPSTREAM_TARGETS=len(target_rows))
    return a,patches,starts,ledgers


class ContinuationTests(unittest.TestCase):
    def test_one_invocation_continues_past75_with_report_available_before_final_request(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);a,constants,starts,_=fixture(td);client=FakeClient(starts)
            with patch.multiple(pc,**constants),patch.multiple(legacy,**constants),patch.object(ex,'OLD_ROWS',21),\
                 patch.object(run.original_resume,'wait_for_other_collectors'),patch.object(dl,'check_other_api_jobs'),\
                 patch.object(run.http,'Client',return_value=client),patch.object(Path,'home',return_value=td/'home'):
                legacy.run(a)
                root=Path(io.load(a.desktop/'RUN2_PHASED_LATEST_PRIVATE.json')['root'])
                observed=[]
                def observe(ids):
                    if len(ids)==114:
                        observed.append((a.desktop/f'RUN2_PHASE_075_REPORT_{root.name}.zip').exists())
                client.observer=observe
                with patch.object(run,'publish',wraps=run.publish) as publisher:
                    run.run(a)
                    self.assertEqual([c.args[7] for c in publisher.call_args_list],[25,50,75,100])
                self.assertEqual(observed,[True])
                self.assertEqual(len(client.calls),6)
                self.assertTrue((a.desktop/f'RUN2_PHASE_100_REPORT_{root.name}.zip').is_file())

    def test_full_inherited_pipeline_reports_all_checkpoints_resumes_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);a,constants,starts,ledgers=fixture(td);client=FakeClient(starts)
            with patch.multiple(pc,**constants),patch.multiple(legacy,**constants),patch.object(ex,'OLD_ROWS',21),\
                 patch.object(run.original_resume,'wait_for_other_collectors'),patch.object(dl,'check_other_api_jobs'),\
                 patch.object(run.http,'Client',return_value=client),patch.object(Path,'home',return_value=td/'home'):
                legacy.run(a)
                root=Path(io.load(a.desktop/'RUN2_PHASED_LATEST_PRIVATE.json')['root'])
                old_hash=io.sha(root/'download/10/checkpoint.sqlite3')
                initial_calls=len(client.calls);self.assertEqual(initial_calls,1)
                original_publish=run.publish
                published=[]
                def stop_after75(*args,**kwargs):
                    result=original_publish(*args,**kwargs)
                    p=args[7];published.append(p)
                    if p==75:raise KeyboardInterrupt()
                    return result
                with patch.object(run,'publish',side_effect=stop_after75):
                    with self.assertRaises(KeyboardInterrupt):run.run(a)
                self.assertEqual(published,[25,50,75])
                self.assertFalse((a.desktop/f'RUN2_PHASE_100_REPORT_{root.name}.zip').exists())
                self.assertEqual(len(client.calls),5)
                self.assertTrue((a.desktop/f'RUN2_PHASE_075_REPORT_{root.name}.zip').exists())
                run.run(a)
                self.assertEqual(len(client.calls),6)
                flat=[g for batch in client.calls for g in batch]
                self.assertEqual(len(flat),len(set(flat)))
                self.assertEqual(io.sha(root/'download/10/checkpoint.sqlite3'),old_hash)
                expected={25:42,50:63,75:420,100:777}
                for p in CHECKPOINTS:
                    archive=a.desktop/f'RUN2_PHASE_{p:03}_REPORT_{root.name}.zip'
                    with zipfile.ZipFile(archive) as z:
                        s=json.loads(z.read('summary.json'))
                        self.assertEqual(s['requested'],expected[p]);self.assertEqual(s['returned'],expected[p])
                        self.assertEqual(s['through_percent'],p);self.assertFalse(s['behavioral_estimates_computed'])
                        for r in json.loads(z.read('REPORT_MANIFEST.json')):
                            self.assertEqual(hashlib.sha256(z.read(r['path'])).hexdigest(),r['sha256'])
                    if p==75:
                        self.assertEqual(s['cached_pool_rows'],21)
                        self.assertEqual(s['additional_frame_rows'],483)
                # Completion is idempotent, including reports and API usage.
                run.run(a);self.assertEqual(len(client.calls),6)
                # Existing 100% metadata does not double-count the 75% prefix.
                meta=io.load(root/'phase_results/100/ANALYSIS_INPUTS_PRIVATE.json')['merged_candidate_metadata']
                table=io.read(meta)
                self.assertEqual(len(table),819)
                self.assertEqual(set(table['metadata_records'].to_pylist()),{1})
                a.mode='status';run.run(a);self.assertEqual(len(client.calls),6)
                Path(ledgers[0]).write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'size|checksum'):run.run(a)
                self.assertEqual(len(client.calls),6)

    def test_continuous_wrapper_resumes_partial_request_without_refetch(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);target=td/'target.parquet';ids=['AbCd1234','Other001'];targets(target,ids)
            band=dict(target=target,total=2,done=0,sha256=io.sha(target),conf='test')
            class Interrupted(FakeClient):
                def get(self,requested):
                    self.requests+=1;self.calls.append(list(requested))
                    if self.requests==2:raise KeyboardInterrupt()
                    return (json.dumps(api(ids[0]))+'\n').encode()
            broken=Interrupted();good=FakeClient();addon=td/'addon';addon.mkdir()
            def tracker():return Progress(0,{25:2,50:2,75:2,100:2},10,lambda s:None)
            with patch.object(run.http,'Client',return_value=broken),patch.object(Path,'home',return_value=td/'home'):
                with self.assertRaises(KeyboardInterrupt):run.download_band(td/'root',addon,25,band,tracker())
            with patch.object(run.http,'Client',return_value=good),patch.object(Path,'home',return_value=td/'home'):
                run.download_band(td/'root',addon,25,band,tracker())
            self.assertEqual(good.calls,[[ids[1]]])
            self.assertEqual(io.load(td/'root/download/25/finished/SUMMARY.json')['returned'],2)


if __name__=='__main__':unittest.main()
