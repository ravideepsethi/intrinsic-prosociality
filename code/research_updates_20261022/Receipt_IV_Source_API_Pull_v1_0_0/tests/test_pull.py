import gzip
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0,str(Path(__file__).parents[1]/'code'))
import common as C
import api_client as A
import records as R
import collect
import prepare
import finalize
import run


def target(gid='game0001',month='2025-11',winner='white'):
    return dict(game_id=gid,month=month,utc_ms=1761955200000,
                api_created_at_ms=None,expected_winner=winner)


def native(t,source='pool'):
    x=dict(id=t['game_id'],source=source,rated=True,variant='standard',speed='blitz',perf='blitz',
           createdAt=t['utc_ms']+123,lastMoveAt=t['utc_ms']+45000,status='timeout',
           players={'white':{'user':{'id':'fixture_white'},'rating':1501,'ratingDiff':4},
                    'black':{'user':{'id':'fixture_black'},'rating':1502,'ratingDiff':-4}},
           clock={'initial':180,'increment':2,'totalTime':260},clocks=[18000,18000,17925])
    if t['expected_winner'] is not None:x['winner']=t['expected_winner']
    return x


class Response(io.BytesIO):
    status=200
    headers={'Content-Type':'application/x-ndjson'}


class PartialResponse(Response):
    def __init__(self,data):super().__init__(data);self.lines=0
    def readline(self,*args):
        self.lines+=1
        if self.lines>1:raise http.client.IncompleteRead(b'')
        return super().readline(*args)


class Opener:
    def __init__(self,replies):self.replies=list(replies);self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        reply=self.replies.pop(0)
        if isinstance(reply,BaseException):raise reply
        if isinstance(reply,Response):return reply
        return Response(b''.join(json.dumps(x).encode()+b'\n' for x in reply))


def client(replies,waits=None):
    waits=[] if waits is None else waits
    return A.Client(opener=Opener(replies),sleeper=waits.append)


class PullTests(unittest.TestCase):
    def test_success_has_no_added_pause_and_clocks_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=target();waits=[];api=client([[native(t)]],waits)
            done,new=collect.collect_batch(Path(tmp)/'batch',[t],'binding',api,Path(tmp)/'auth')
            self.assertTrue(new);self.assertEqual(waits,[])
            rows=C.pq.read_table(Path(tmp)/'batch/metadata_PRIVATE.parquet').to_pylist()
            self.assertEqual(rows[0]['clocks_centiseconds'],[18000,18000,17925])
            self.assertEqual(rows[0]['record_status'],'validated_source')
            self.assertIn(b'game0001',api.opener.requests[0].data)
            self.assertIn('moves=false',api.opener.requests[0].full_url)
            self.assertEqual(done['rows'],1)

    def test_committed_batch_resumes_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=target();root=Path(tmp)/'batch';auth=Path(tmp)/'auth'
            collect.collect_batch(root,[t],'b',client([[native(t)]]),auth)
            api=client([])
            done,new=collect.collect_batch(root,[t],'b',api,auth)
            self.assertFalse(new);self.assertEqual(api.requests,0)
            self.assertEqual(done['status_counts'],{'validated_source':1})
            with self.assertRaises(RuntimeError):collect.collect_batch(root,[t],'changed',api,auth)

    def test_only_omitted_ids_are_retried_without_fixed_delay(self):
        with tempfile.TemporaryDirectory() as tmp:
            ts=[target('game0001'),target('game0002')];waits=[]
            api=client([[native(ts[0])],[native(ts[1])]],waits)
            done,_=collect.collect_batch(Path(tmp)/'batch',ts,'b',api,Path(tmp)/'auth')
            self.assertEqual([r.data for r in api.opener.requests],[b'game0001,game0002',b'game0002'])
            self.assertEqual(waits,[]);self.assertEqual(done['rows'],2)

    def test_partial_stream_and_restart_keep_received_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            ts=[target('game0001'),target('game0002')];root=Path(tmp)/'batch';auth=Path(tmp)/'auth'
            body=json.dumps(native(ts[0])).encode()+b'\n'
            api=client([PartialResponse(body),KeyboardInterrupt()])
            with self.assertRaises(KeyboardInterrupt):collect.collect_batch(root,ts,'b',api,auth)
            resumed=client([[native(ts[1])]])
            done,_=collect.collect_batch(root,ts,'b',resumed,auth)
            self.assertEqual(resumed.opener.requests[0].data,b'game0002')
            self.assertEqual(done['status_counts'],{'validated_source':2})

    def test_429_honors_retry_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=target();waits=[]
            error=urllib.error.HTTPError(C.ENDPOINT,429,'Too many',{'Retry-After':'75'},None)
            api=client([error,[native(t)]],waits)
            collect.collect_batch(Path(tmp)/'batch',[t],'b',api,Path(tmp)/'auth')
            self.assertEqual(waits,[75.0]);self.assertEqual(api.throttles,1)
            self.assertEqual(A.retry_seconds(429,None,0),60)

    def test_cooldown_survives_new_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cooldown.json';waits=[];t=target()
            C.write_json(path,{'next_request_after_unix':110.0})
            api=A.Client(opener=Opener([[native(t)]]),sleeper=waits.append,cooldown_path=path)
            with patch.object(A.time,'time',return_value=100.0):
                api.fetch([t['game_id']],Path(tmp)/'attempts','b')
            self.assertEqual(waits,[10.0])

    def test_final_network_failure_stops_without_sleeping_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=target();waits=[];cooldown=Path(tmp)/'cooldown.json'
            errors=[urllib.error.HTTPError(C.ENDPOINT,503,'Unavailable',{},None) for _ in range(2)]
            api=A.Client(opener=Opener(errors),sleeper=waits.append)
            # The injected sleeper records elapsed policy waits without delaying
            # this test. Defer is separately tested for persistence above.
            with patch.object(collect,'MAX_TRANSIENT_FAILURES',2),patch.object(api,'defer') as deferred:
                with self.assertRaises(A.PullStopped):
                    collect.collect_batch(Path(tmp)/'batch',[t],'b',api,Path(tmp)/'auth')
                self.assertEqual(waits,[5.0])
                self.assertEqual(deferred.call_args.args,(10.0,))

    def test_three_omissions_remain_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=target();waits=[];api=client([[],[],[]],waits)
            done,_=collect.collect_batch(Path(tmp)/'batch',[t],'b',api,Path(tmp)/'auth')
            self.assertEqual(done['status_counts'],{'not_returned_after_retries':1})
            self.assertEqual(api.requests,3);self.assertEqual(waits,[])

    def test_unexpected_and_duplicate_ids_stop_without_done(self):
        for returned in ([native(target('other001'))],[native(target()),native(target())]):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'batch'
                with self.assertRaises(A.PullStopped):collect.collect_batch(root,[target()],'b',client([returned]),Path(tmp)/'auth')
                self.assertFalse((root/'_DONE.json').exists())

    def test_invalid_metadata_is_never_validated_source(self):
        for key,value in [('createdAt',1),('winner','black'),('status','outoftime'),('rated',False),('variant','chess960')]:
            t=target();obj=native(t);obj[key]=value
            self.assertEqual(R.normalize(obj,t,'fixture')['record_status'],'returned_metadata_mismatch')
        t=target();obj=native(t);obj.pop('source')
        self.assertEqual(R.normalize(obj,t,'fixture')['record_status'],'returned_source_missing')

    def test_draw_omitted_winner_is_correct(self):
        t=target(winner=None);row=R.normalize(native(t),t,'fixture')
        self.assertEqual(row['record_status'],'validated_source')
        self.assertFalse(row['winner_field_present'])

    def test_completed_file_tampering_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=target();root=Path(tmp)/'batch';auth=Path(tmp)/'auth'
            collect.collect_batch(root,[t],'b',client([[native(t)]]),auth)
            p=root/'metadata_PRIVATE.parquet';p.write_bytes(p.read_bytes()+b'tampered')
            with self.assertRaises(RuntimeError):collect.collect_batch(root,[t],'b',client([]),auth)

    def test_complete_prepare_pull_supplement_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'project';work=project/'api_pull';work.mkdir(parents=True)
            base=project/'derived/replication_36m/receipt_iv_cohort_extension_v100_PRIVATE'
            source=base/'source/reduced/fixture';source.mkdir(parents=True)
            meta=base/'targets/fixture';meta.mkdir(parents=True)
            membership=base/'membership/fixture';membership.mkdir(parents=True)
            ts=[target('game0001','2025-11'),target('game0002','2025-12'),
                target('game0003','2026-02'),target('game0004','2026-02')]
            source_rows=[dict(game_id=t['game_id'],month=t['month'],source=None,source_status='missing',
                             source_provenance=None,evidence_rows=0,distinct_sources=0) for t in ts]
            sp=source/'source_by_game_PRIVATE.parquet';tp=meta/'targets_PRIVATE.parquet'
            C.pq.write_table(C.pa.Table.from_pylist(source_rows),sp)
            C.pq.write_table(C.pa.Table.from_pylist(ts),tp)
            C.write_json(source/'_DONE.json',{'files':[C.receipt(sp,source)],'inputs':[C.receipt(tp)]})
            mfiles=[]
            statuses={'game0001':'not_mutually_adjacent_observed',
                      'game0002':'mutual_adjacency_candidate_timing_unresolved',
                      'game0003':'left_boundary_unresolved','game0004':'not_mutually_adjacent_observed'}
            for month in C.MONTHS:
                mp=membership/f'membership/month={month}/membership_PRIVATE.parquet';mp.parent.mkdir(parents=True)
                rows=[dict(game_id=t['game_id'],month=month,source=None,source_status='missing',source_provenance=None,
                    previous_classification_status=statuses[t['game_id']],mutual_previous_same_pair=None,
                    pool_nonadjacent_eligible=None,final_iv_eligible=None) for t in ts if t['month']==month]
                C.pq.write_table(C.pa.Table.from_pylist(rows),mp);mfiles.append(C.receipt(mp,membership))
            C.write_json(membership/'_DONE.json',{'files':mfiles,'result':{'known_main_rows':50}})
            C.write_json(base/'READY_FOR_IV_COHORT_ASSEMBLY_PRIVATE.json',dict(
                code_signature=C.COHORT_CODE,status='MEMBERSHIP_AND_PAIR_EXCLUDED_SCORE_INPUTS_READY',
                source_root=str(source),membership_root=str(membership),
                receipts=[C.receipt(source/'_DONE.json'),C.receipt(membership/'_DONE.json')]))
            expected={'2025-11':1,'2025-12':1,'2026-02':2}
            with patch.object(prepare,'EXPECTED',expected),patch.object(finalize,'EXPECTED',expected):
                planroot,plan,contract=prepare.prepare(project,work,2)
                results=[]
                for month in C.MONTHS:
                    for index,rows in prepare.target_batches(planroot/(month+'.parquet')):
                        root=work/'batches'/month/str(index)
                        responses=[native(t,'lobby' if t['game_id']=='game0004' else 'pool') for t in rows]
                        done,_=collect.collect_batch(root,rows,plan['binding'],client([responses]),work/'authentication')
                        results.append(dict(root=str(root),done=done))
                result=finalize.finish(work,plan,contract,results,2)
                self.assertEqual(result['summary']['validated_source_rows'],4)
                self.assertEqual(result['summary']['additional_known_main_rows'],1)
                self.assertEqual(result['summary']['known_main_rows_after_supplement'],51)
                eligibility={}
                for p in result['membership_deltas']:
                    eligibility.update({r['game_id']:r['pool_nonadjacent_eligible'] for r in C.pq.read_table(p).to_pylist()})
                self.assertEqual(eligibility,{'game0001':True,'game0002':False,'game0003':None,'game0004':False})
                again=finalize.finish(work,plan,contract,results,2)
                self.assertEqual(again['binding'],result['binding'])
                _,reused,_=prepare.prepare(project,work,2)
                self.assertEqual(reused['binding'],plan['binding'])
                folder=project/'report';folder.mkdir();desktop=project/'desktop';desktop.mkdir()
                C.write_json(folder/'SUMMARY.json',result['summary'])
                archive=run.package_report(folder,desktop)
                with run.zipfile.ZipFile(archive) as z:
                    self.assertIsNone(z.testzip())
                    self.assertFalse(any(b'fixture_white' in z.read(n) for n in z.namelist()))


if __name__=='__main__':unittest.main()
