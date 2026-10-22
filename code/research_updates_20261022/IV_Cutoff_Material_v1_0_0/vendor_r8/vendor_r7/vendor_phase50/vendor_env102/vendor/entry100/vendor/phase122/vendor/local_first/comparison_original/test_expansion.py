#!/usr/bin/env python3
"""Offline denominator, provenance, nested-sampling, transport and restart tests."""
import contextlib, faulthandler, gzip, hashlib, io as streams, json, os, ssl, sqlite3, tempfile, unittest, zipfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import expansion_common as x
import cache_scan as cache
import prepare_expansion as prep
import download_expansion as dl
import metadata_http as http
import local_io as io

def input_table(n=40000):
    return pa.table(dict(game_id=[f'{i:08x}' for i in range(n)],utc_ms=np.arange(n,dtype=np.int64)*1000+int(x.core.STARTS[0]),
        archive_ordinal=np.arange(n,dtype=np.int64),white_id=np.arange(n,dtype=np.int64)+1,black_id=np.arange(n,dtype=np.int64)+100000))

def frame(n=40000):
    t=input_table(n);t=t.filter(pa.array(x.selected(t['game_id'].to_pylist())))
    return x.orient(t,'2023-11','blitz')

def game(row,**changes):
    obj=dict(id=row['game_id'],source='pool',status='resign',createdAt=row['utc_ms'],lastMoveAt=row['utc_ms']+60000,
        rated=True,variant='standard',speed='blitz',winner='white',clock=dict(initial=180,increment=0),
        players=dict(white=dict(user=dict(id='alice'),rating=1500),black=dict(user=dict(id='bob'),rating=1520)))
    obj.update(changes);return obj

class FakeClient:
    def __init__(self,rows,missing_once=False,never=None):
        self.rows={r['game_id']:r for r in rows};self.calls=[];self.missing_once=missing_once;self.never=never
    def get(self,ids):
        self.calls.append(list(ids));out=[]
        for k,g in enumerate(ids):
            if g==self.never or (self.missing_once and len(self.calls)==1 and k==0):continue
            out.append(json.dumps(game(self.rows[g])))
        return ('\n'.join(out)+'\n').encode()

class ExpansionTests(unittest.TestCase):
    def test_spawned_sampling_workers_and_checkpoint_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);t=input_table(8000);jobs=[]
            for k in range(2):
                part=t.slice(k*4000,4000);src=p/f'source{k}.parquet';io.table(src,part)
                jobs.append(dict(path=str(src),out=str(p/f'part{k}'),conf='spawn',month='2023-11',speed='blitz',
                    rows=len(part),original_sample_rows=int(x.selected(part['game_id'].to_pylist(),1024).sum()),
                    sha256=io.sha(src),signature=io.sig(src)))
            with contextlib.redirect_stdout(streams.StringIO()):
                results=io.mapped(prep.sample_job,jobs,2,'Synthetic workers')
            self.assertEqual(sum(r['scanned_rows'] for r in results),len(t))
            self.assertEqual(sum(r['sampled_rows'] for r in results),int(x.selected(t['game_id'].to_pylist()).sum()))
            self.assertEqual(results,[prep.sample_job(j) for j in jobs])

    def test_exact_nested_rule_and_original_color(self):
        ids=input_table()['game_id'].to_pylist();h=x.bits(ids)
        np.testing.assert_array_equal(h,np.array([x.scalar_bits(g) for g in ids],np.uint64))
        small=x.selected(ids,1024);large=x.selected(ids,32)
        self.assertFalse(np.any(small&~large));np.testing.assert_array_equal(large[::-1],x.selected(ids[::-1]))
        f=frame();hh=x.bits(f['game_id'].to_pylist())
        self.assertEqual(f['recipient_color'].to_pylist(),['white' if ((int(v)>>32)&1)==0 else 'black' for v in hh])
        self.assertEqual(sum(f['previous_frame'].to_pylist()),int(small.sum()))
        for m in [0,1,3,31]:
            with self.assertRaises(ValueError):x.selected(ids,m)
        for v in ['toolonggg',None,'bad id!!']:
            with self.assertRaises(ValueError):x.bits([v])

    def test_case_sensitive_ids_and_sha_rank(self):
        self.assertNotEqual(x.scalar_bits('AbCd0123'),x.scalar_bits('abcd0123'))
        f=frame(4000)
        for r in f.to_pylist():self.assertEqual(r['retrieval_rank'],hashlib.sha256(x.ORDER_SEED+r['game_id'].encode()).digest())

    def test_precision_target_uses_new_sample_and_two_sided_power(self):
        p=x.precision_plan();self.assertEqual(p['new_expected_multiplier'],31)
        self.assertAlmostEqual(p['projected_new_sample_SE_pp_per_reference_SD'],.028292388191929772/31**.5)
        self.assertGreater(p['projected_equivalence_power_at_zero'],.8);self.assertFalse(p['guaranteed_power'])

    def test_sample_checkpoint_reuse_and_changed_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);t=input_table();src=root/'source.parquet';io.table(src,t)
            j=dict(path=str(src),out=str(root/'sample'),conf='s',month='2023-11',speed='blitz',rows=len(t),
                original_sample_rows=int(x.selected(t['game_id'].to_pylist(),1024).sum()),sha256=io.sha(src),signature=io.sig(src))
            a=prep.sample_job(j);b=prep.sample_job(j);self.assertEqual(a,b)
            src.write_bytes(src.read_bytes()+b'changed')
            j['signature']=io.sig(src)
            with self.assertRaises(RuntimeError):prep.sample_job(j)

    def test_multifile_nesting_and_mismatched_orientation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);f=frame();old=f.filter(f['previous_frame']).select(x.FRAME_FIELDS)
            io.table(root/'a.parquet',f.slice(0,200));io.table(root/'b.parquet',f.slice(200));io.table(root/'old.parquet',old)
            _,r=prep.assemble_frame(root,'good',[root/'a.parquet',root/'b.parquet'],root/'old.parquet',1,len(old))
            self.assertEqual(r['frame_rows'],len(f));self.assertTrue(r['original_fields_reproduced'])
            bad=old.set_column(old.schema.get_field_index('recipient_id'),'recipient_id',old['opponent_id'])
            io.table(root/'bad.parquet',bad)
            with self.assertRaises(RuntimeError):prep.assemble_frame(root/'other','bad',[root/'a.parquet',root/'b.parquet'],root/'bad.parquet',1,len(old))

    def test_duplicate_game_ids_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);f=frame(5000);old=f.filter(f['previous_frame']).select(x.FRAME_FIELDS)
            io.table(p/'part.parquet',f);io.table(p/'old.parquet',old)
            with self.assertRaises(RuntimeError):prep.assemble_frame(p,'dup',[p/'part.parquet',p/'part.parquet'],p/'old.parquet',1,len(old))

    def test_cache_gzip_wrappers_normalized_and_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);f=frame();rows=[r for r in f.to_pylist() if not r['previous_frame']][:4]
            with gzip.open(p/'response.ndjson.gz','wb') as s:s.write(('\n'.join(json.dumps(game(r)) for r in rows[:2])+'\n').encode())
            (p/'batch.json').write_text(json.dumps({'games':[game(rows[2])]},indent=2))
            io.table(p/'metadata.parquet',pa.Table.from_pylist([x.normalize(game(rows[0],source='lobby'))],schema=x.metadata_schema()))
            (p/'ignored.partial.ndjson').write_text(json.dumps(game(rows[3])))
            rec=cache.inventory([p]);self.assertEqual(len(rec),3)
            r=cache.scan_group(dict(inputs=rec,out=str(p/'out'),conf='cache'))
            self.assertEqual(r['records'],4);self.assertEqual(r['cache_parse_gaps'],0)
            merged,_=prep.aggregate_cache(p,'cache',[p/'out/records.parquet'],1)
            table=io.read(merged/'metadata.parquet').to_pylist()
            bad=next(r for r in table if r['game_id']==rows[0]['game_id']);self.assertTrue(bad['cached_conflict_or_prior_flag'])

    def test_bad_cache_file_does_not_delete_targets(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'response.ndjson').write_bytes(b'{broken}\n')
            r=cache.scan_group(dict(inputs=cache.inventory([p]),out=str(p/'out'),conf='x'))
            self.assertEqual(r['cache_parse_gaps'],1);self.assertEqual(r['records'],0)

    def test_full_prepare_components_denominator_and_order(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);f=frame(18000);old=f.filter(f['previous_frame']).select(x.FRAME_FIELDS)
            io.table(p/'sample.parquet',f);io.table(p/'old.parquet',old)
            prep.assemble_frame(p,'x',[p/'sample.parquet'],p/'old.parquet',1,len(old))
            fresh=[r for r in f.to_pylist() if not r['previous_frame']]
            records=[x.normalize(game(fresh[0])),x.normalize(game(fresh[1],source='lobby')),
                     x.normalize(game(fresh[2])),x.normalize(game(fresh[2],source='lobby'))]
            io.table(p/'cache.parquet',pa.Table.from_pylist(records,schema=x.metadata_schema()))
            prep.aggregate_cache(p,'x',[p/'cache.parquet'],1)
            _,r=prep.plan_requests(p,'x',1)
            self.assertEqual(sum(r['status_counts'].values()),len(f));self.assertEqual(r['api_targets'],len(fresh)-2)
            target=io.read(p/'requests/targets.parquet')['game_id'].to_pylist()
            self.assertIn(fresh[2]['game_id'],target);self.assertNotIn(fresh[0]['game_id'],target)
            self.assertEqual(target,sorted(target,key=lambda s:(hashlib.sha256(x.ORDER_SEED+s.encode()).digest(),s)))
            self.assertFalse(set(target)&set(old['game_id'].to_pylist()))

    def test_pool_metadata_validation_matches_sql(self):
        rows=[r for r in frame().to_pylist() if not r['previous_frame']][:1];f=rows[0]
        self.assertEqual(x.metadata_errors(x.normalize(game(f)),f),[])
        self.assertIn('CREATED_TIME_FRAME_DISAGREEMENT',x.metadata_errors(x.normalize(game(f,createdAt=f['utc_ms']+1000)),f))
        self.assertIn('NOT_STANDARD',x.metadata_errors(x.normalize(game(f,variant='chess960')),f))
        self.assertEqual(x.metadata_errors(x.normalize({'id':f['game_id'],'source':'lobby'}),f),[])

    def test_request_resumption_and_nonreturn_accounting(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);rows=[r for r in frame().to_pylist() if not r['previous_frame']][:6]
            cli=FakeClient(rows,missing_once=True,never=rows[-1]['game_id']);db=dl.connect(p/'checkpoint.sqlite3','c','t')
            r=dl.process_batch(db,0,rows,cli);self.assertEqual(len(cli.calls),3)
            self.assertEqual(len(r[0]),5);self.assertEqual(len(r[1]),1);self.assertEqual(r[2],0)
            repeat=dl.process_batch(db,0,rows,cli);self.assertTrue(repeat[3]);self.assertEqual(len(cli.calls),3)
            with self.assertRaises(RuntimeError):dl.process_batch(db,0,rows[::-1],cli)
            db.close()

    def test_interruption_reuses_already_committed_response(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);rows=frame().to_pylist()[:4];ids=[r['game_id'] for r in rows];cli=FakeClient(rows)
            db=dl.connect(p/'db','c','t');dl.response(db,0,0,ids,cli);db.close()
            db=dl.connect(p/'db','c','t');result=dl.process_batch(db,0,rows,cli)
            self.assertEqual(len(cli.calls),1);self.assertEqual(len(result[0]),4);db.close()

    def test_saved_response_tamper_and_changed_config_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);rows=frame().to_pylist()[:3];cli=FakeClient(rows);db=dl.connect(p/'db','c','t')
            dl.process_batch(db,0,rows,cli)
            with db:db.execute('UPDATE responses SET raw_sha=?',('0'*64,))
            with self.assertRaises(RuntimeError):dl.process_batch(db,0,rows,cli)
            db.close()
            with self.assertRaises(RuntimeError):dl.connect(p/'db','wrong','t')

    def test_batches_independent_of_parquet_row_groups_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);rows=frame().to_pylist()[:601];self.assertEqual(len(rows),601)
            t=pa.Table.from_pylist([{n:r[n] for n in ['game_id','utc_ms','speed_partition']} for r in rows])
            pq.write_table(t,p/'targets.parquet',row_group_size=71)
            parts=list(dl.batches(p/'targets.parquet'));self.assertEqual(list(map(len,parts)),[300,300,1])
            cli=FakeClient(rows);db=dl.connect(p/'db','c','t')
            for k,b in enumerate(parts):dl.process_batch(db,k,b,cli)
            _,r=dl.export_saved(db,p/'targets.parquet',p/'finish','c')
            self.assertEqual(r['requested'],601);self.assertEqual(r['returned'],601);self.assertEqual(r['not_returned'],0)
            self.assertFalse(r['global_account_identity_verified']);db.close()

    def test_http_success_no_pause_429_retry_and_tls(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);now=[100.];sleeps=[];calls=[];ids=['abcdefgh']
            def sleep(s):sleeps.append(s);now[0]+=s
            class Reply:
                status=200;headers={'Content-Type':'application/x-ndjson'}
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def read(self,n):return b'{"id":"abcdefgh"}\n'
            def opener(req,**kw):
                calls.append(req)
                if len(calls)==1:raise urllib.error.HTTPError(http.URL,429,'limit',{'Retry-After':'91'},None)
                return Reply()
            c=http.Client(p/'cool.json',opener,sleep,lambda:now[0]);c.get(ids);self.assertEqual(sum(sleeps),91)
            c.get(ids);self.assertEqual(sum(sleeps),91)
            self.assertIn('moves=false',calls[-1].full_url);self.assertEqual(calls[-1].data,b'abcdefgh')
            with mock.patch.dict(os.environ,{'LICHESS_API_TOKEN':'test-secret-token'}):
                c.get(ids);self.assertNotIn('test-secret-token',(p/'cool.json').read_text())
            def fail(*a,**kw):raise ssl.SSLCertVerificationError('bad cert')
            c=http.Client(p/'tls.json',fail,sleep,lambda:now[0])
            with self.assertRaises(RuntimeError):c.get(ids)
            self.assertEqual(c.requests,1)

    def test_duplicate_unrequested_and_nonjson_response_rejected(self):
        for raw in [b'{"id":"abcdefgh"}\n{"id":"abcdefgh"}',b'{"id":"ABCDEFGH"}',b'<html>']:
            with self.assertRaises((ValueError,RuntimeError)):http.parse(raw,['abcdefgh'])

    def test_portable_archive_hashes_and_renamed_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);src=p/'src';src.mkdir();conf='a'*64
            io.table(src/'targets.parquet',pa.table({'game_id':['abcdefgh'],'utc_ms':[int(x.core.STARTS[0])],'speed_partition':['blitz']}))
            io.js(src/'DESIGN_FREEZE.json',dict(config_sha256=conf));io.js(src/'TRANSFER.json',dict(config_sha256=conf,target_rows=1))
            names=['targets.parquet','DESIGN_FREEZE.json','TRANSFER.json']
            io.js(src/'INPUT_MANIFEST.json',dict(config_sha256=conf,files=[dict(path=n,bytes=(src/n).stat().st_size,sha256=io.sha(src/n)) for n in names]))
            z=p/'CHOOSER_COMPARISON_EXPANSION_INPUT_aaaaaaaaaaaa_PRIVATE.zip';side=x.zip_files(src,z,names+['INPUT_MANIFEST.json'])
            side.rename(Path(str(side)+' 2'))
            root,got,rec=dl.unpack_input(z,p);self.assertEqual(got,conf);self.assertEqual(rec['target_rows'],1)
            self.assertTrue((root/'inputs/targets.parquet').is_file())
            with zipfile.ZipFile(p/'bad.zip','w') as zz:zz.writestr('../bad','no')
            (p/'bad.zip.sha256').write_text(io.sha(p/'bad.zip'))
            with self.assertRaises(RuntimeError):dl.unpack_input(p/'bad.zip',p,p/'bad.zip.sha256')

    def test_portable_download_resume_and_private_return_integration(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);src=p/'source';src.mkdir();conf='e'*64
            rows=frame(4000).to_pylist()[:7]
            io.table(src/'requests/targets.parquet',pa.Table.from_pylist([
                {n:r[n] for n in ('game_id','utc_ms','speed_partition')} for r in rows]))
            io.js(src/'DESIGN_FREEZE.json',dict(config_sha256=conf))
            archive=prep.portable(src,conf,p)
            class OfflineClient(FakeClient):
                http_seconds=0
                @property
                def requests(self):return len(self.calls)
            client=OfflineClient(rows,never=rows[-1]['game_id'])
            args=SimpleNamespace(mode='download',desktop=p,input=archive,checksum=None,project_root=p)
            with mock.patch.object(dl.http,'Client',return_value=client),mock.patch.object(dl,'check_other_api_jobs'), \
                 mock.patch.object(Path,'home',return_value=p/'home'),mock.patch.object(x,'require_disk'), \
                 contextlib.redirect_stdout(streams.StringIO()):
                dl.execute(args);n=len(client.calls);dl.execute(args)
                self.assertEqual(len(client.calls),n)
                args.mode='pack';dl.execute(args)
            root=p/f'CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_{conf[:12]}_PRIVATE'
            s=io.load(root/'finished/SUMMARY.json')
            self.assertEqual((s['requested'],s['returned'],s['not_returned']),(7,6,1))
            with zipfile.ZipFile(p/f'CHOOSER_COMPARISON_EXPANSION_RETURN_{conf[:12]}_PRIVATE.zip') as z:
                m=json.loads(z.read('RETURN_MANIFEST.json'));self.assertEqual(m['config_sha256'],conf)
                self.assertIn('checkpoint.sqlite3',z.namelist())
                for r in m['files']:
                    raw=z.read(r['path']);self.assertEqual(len(raw),r['bytes'])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(),r['sha256'])
            with zipfile.ZipFile(p/f'CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_REPORT_{conf[:12]}.zip') as z:
                self.assertEqual(json.loads(z.read('summary.json'))['returned'],6)
                for r in rows:self.assertNotIn(r['game_id'],z.read('summary.json').decode())

    def test_a1_api_guard_allows_only_verified_engine_phase(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);pkg=p/'A1_Trajectory_Build_v1_0_2';pkg.mkdir()
            script=pkg/'run_build.py';script.write_text('# synthetic A1 code\n')
            run=p/'derived/replication/a1_trajectory_build_v100_PRIVATE/run'
            io.js(run/'RUN_CONFIG.json',dict(code={'run_build.py':io.sha(script)}))
            process=SimpleNamespace(stdout=f'123456 python3 {script}\n')
            with mock.patch.object(dl.subprocess,'run',return_value=process):
                with self.assertRaises(RuntimeError):dl.check_other_api_jobs(p)
                io.js(run/'RECOVERY_COMPLETE.json',dict(complete=True));dl.check_other_api_jobs(p)
                script.write_text('# changed code\n')
                with self.assertRaises(RuntimeError):dl.check_other_api_jobs(p)

    def test_public_report_contains_aggregates_only(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);s=p/'report';s.mkdir();io.js(s/'summary.json',dict(rows=123,network_requests=0))
            z=p/'report.zip';x.report_zip(s,z)
            with zipfile.ZipFile(z) as zz:
                self.assertIsNone(zz.testzip());self.assertEqual(set(zz.namelist()),{'summary.json','REPORT_MANIFEST.json'})
                self.assertNotIn('game_id',zz.read('summary.json').decode())

if __name__=='__main__':
    faulthandler.dump_traceback_later(45,repeat=True)
    try:unittest.main(verbosity=2)
    finally:faulthandler.cancel_dump_traceback_later()
