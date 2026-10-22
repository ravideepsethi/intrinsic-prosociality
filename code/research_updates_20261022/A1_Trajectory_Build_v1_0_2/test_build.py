"""Offline tests: no Lichess requests and no real Stockfish evaluations."""
from __future__ import annotations
import contextlib,copy,faulthandler,gzip,io as sio,json,multiprocessing as mp,os,ssl,sys,tempfile,threading,unittest,urllib.error,zipfile
from pathlib import Path
from unittest import mock
import chess,chess.engine
import pyarrow as pa
import local_io as io
import recover_logic as logic
import fetch_moves as fetch
import engine_jobs as engines
import run_build as run
import compact_plan


def fixture(i=0,color='white',moves=None):
    moves=moves or ('e4 e5 Nf3 Nc6 Bb5 a6' if color=='white' else 'e4 e5 Nf3 Nc6 Bb5 a6 Ba4')
    b=chess.Board()
    for san in moves.split():b.push_san(san)
    n=b.ply();own,boards=logic.required_positions(n,color);game_id=f'g{i:07d}'
    t={'cohort_row_id':i,'exposure_game_id':game_id,'game_id':game_id,'month':'2024-01','received_mercy':i%2==0,
       'a1_att_weight':1.0 if i%2==0 else .5,'primary_conditional_choice':i%3!=0,'complete_followup':True,
       'recipient_user_id':100+i,'exposure_chooser_user_id':1000+i,'disconnected_color':color,
       'api_created_at_ms':1700000000000+i,'api_last_move_at_ms':1700000020000+i,
       'ply_count':n,'fen_after_last_move':b.fen(),'recipient_move_plies':own,'board_plies':boards,
       'pilot_hash':io.cfgsha(game_id)}
    o={'id':game_id,'source':'pool','rated':True,'status':'timeout','variant':'standard',
       'createdAt':t['api_created_at_ms'],'lastMoveAt':t['api_last_move_at_ms'],
       'players':{'white':{'user':{'id':'private_white'}},'black':{'user':{'id':'private_black'}}},
       'moves':moves,'clocks':[30000-j*10 for j in range(n)],'clock':{'initial':300,'increment':2}}
    if not t['received_mercy']:o['winner']='black' if color=='white' else 'white'
    return t,o

class DummyResponse:
    status=200
    def __init__(self,raw):self.raw=raw
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.raw[:limit]

class FakeEngine:
    def __init__(self,nodes=100000,mate=False,bound=False):self.nodes=nodes;self.mate=mate;self.bound=bound;self.calls=[]
    def analyse(self,b,limit,game):
        self.calls.append((b.fen(),limit.nodes,game))
        return {'nodes':self.nodes,'depth':12,'score':chess.engine.PovScore(chess.engine.Mate(3) if self.mate else chess.engine.Cp(b.ply()*10),chess.WHITE),
                'lowerbound':self.bound}

FAKE_UCI='''import sys
for line in sys.stdin:
 s=line.strip()
 if s=='uci':
  print('id name Stockfish 18');print('option name Threads type spin default 1 min 1 max 16');print('option name Hash type spin default 16 min 1 max 1024');print('uciok',flush=True)
 elif s=='isready':print('readyok',flush=True)
 elif s.startswith('go '):
  assert s=='go nodes 100000',s
  print('info depth 10 nodes 100000 score cp 12',flush=True);print('bestmove 0000',flush=True)
 elif s=='quit':break
'''

def batch_then_join_threads(job,command):
    """Exercise Python 3.13's thread-first shutdown order on every Python."""
    engines.prepare_worker(command)
    engines.evaluate_unit(job)
    # Deliberately precedes multiprocessing/atexit finalizers. This would hang
    # indefinitely with a live python-chess engine thread from the old runner.
    threading._shutdown()

class BuildTests(unittest.TestCase):
    def test_replay_both_colors_and_target_board_plan(self):
        for color in ('white','black'):
            t,o=fixture(color=color);g,p=logic.validated_game(o,t)
            self.assertEqual([r['board_ply'] for r in p],t['board_plies']);self.assertEqual(g['status'],'VERIFIED')
            self.assertEqual(g['clock_status'],'COMPLETE')

    def test_castling_en_passant_and_promotions(self):
        for moves in ('e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7','e4 a6 e5 d5 exd6 exd6',
                      'a4 h5 a5 h4 a6 h3 axb7 hxg2 bxa8=Q gxh1=Q'):
            t,o=fixture(moves=moves);g,p=logic.validated_game(o,t)
            self.assertTrue(p);self.assertFalse(g['no_capture_observed'] if 'exd6' in moves else False)

    def test_identity_state_and_arm_disagreements_fail(self):
        t,o=fixture()
        for key,value in [('id','wrong000'),('source','lobby'),('status','outoftime'),('createdAt',1),
                          ('lastMoveAt',1),('winner','white'),('variant','chess960'),('initialFen','invalid')]:
            bad={**o,key:value}
            with self.assertRaises(logic.RecordProblem):logic.validated_game(bad,t)
        bad={**t,'fen_after_last_move':chess.STARTING_FEN}
        with self.assertRaisesRegex(logic.RecordProblem,'FINAL_FEN'):logic.validated_game(o,bad)

    def test_moves_missing_truncated_illegal_and_extra(self):
        t,o=fixture()
        for moves in (None,'e4 e5','e4 e5 Nf3 Nc6 Bb5 nonsense',o['moves']+' Ba4'):
            with self.assertRaises(logic.RecordProblem):logic.validated_game({**o,'moves':moves},t)

    def test_missing_clocks_does_not_discard_valid_boards(self):
        t,o=fixture()
        for clocks,status in [(None,'MISSING'),([100],'LENGTH_OR_VALUE_MISMATCH'),([True]*6,'LENGTH_OR_VALUE_MISMATCH')]:
            g,p=logic.validated_game({**o,'clocks':clocks},t)
            self.assertEqual(g['clock_status'],status);self.assertIsNone(g['recipient_last_clock_api_units']);self.assertEqual(len(p),4)

    def test_nonreturn_and_invalid_keep_original_rows_and_weights(self):
        a,oa=fixture(0);b,ob=fixture(1);c,oc=fixture(2);oc['status']='outoftime'
        games,positions=logic.replay_records([a,b,c],{oa['id']:oa,oc['id']:oc})
        self.assertEqual(games.num_rows,3);self.assertEqual(games['status'].to_pylist(),['VERIFIED','NONRETURN','STATUS_MISMATCH'])
        self.assertEqual(games['a1_att_weight'].to_pylist(),[1,.5,1]);self.assertEqual(positions.num_rows,4)

    def test_raw_clock_values_preserved_without_inventing_think_time(self):
        t,o=fixture();g,_=logic.validated_game(o,t)
        self.assertEqual(g['recipient_move_1_clock_after_api_units'],o['clocks'][4])
        self.assertEqual(g['recipient_move_1_clock_previous_api_units'],o['clocks'][2])
        self.assertNotIn('think_time',g);self.assertNotIn('finishedAt',g)

    def test_response_duplicate_unrequested_and_malformed_rejected(self):
        _,o=fixture();line=json.dumps(o).encode()
        self.assertEqual(len(fetch.parse_response(line,[o['id']])),1)
        for raw,ids in [(line+b'\n'+line,[o['id']]),(line,['wrong000']),(b'{',[]),(b'[]',[])]:
            with self.assertRaises(RuntimeError):fetch.parse_response(raw,ids)

    def test_request_flags_and_no_success_pause(self):
        _,o=fixture();calls=[];sleeps=[]
        def opener(req,**kwargs):calls.append(req);return DummyResponse(json.dumps(o).encode())
        client=fetch.Client(opener,sleeps.append);client.get([o['id']])
        self.assertEqual(sleeps,[]);self.assertIn('moves=true',calls[0].full_url);self.assertIn('clocks=true',calls[0].full_url)
        self.assertEqual(calls[0].get_method(),'POST');self.assertEqual(calls[0].data,o['id'].encode())
        self.assertEqual(client.context.verify_mode,ssl.CERT_REQUIRED);self.assertTrue(client.context.check_hostname)

    def test_429_cooldown_and_server_retry_after(self):
        _,o=fixture();calls=[];sleeps=[]
        def opener(req,**kwargs):
            calls.append(1)
            if len(calls)==1:raise urllib.error.HTTPError(fetch.URL,429,'Too many',{'Retry-After':'91'},sio.BytesIO())
            return DummyResponse(json.dumps(o).encode())
        c=fetch.Client(opener,sleeps.append);c.get([o['id']])
        self.assertEqual(sum(sleeps),91);self.assertEqual(c.requests,2)
        self.assertGreaterEqual(fetch.retry_delay(429,{},0),60)
        self.assertEqual(fetch.retry_delay(503,{'Retry-After':'Thu, 01 Jan 1970 00:02:00 GMT'},0,now=0),120)

    def test_tls_and_permission_errors_not_retried(self):
        _,o=fixture()
        for error in [urllib.error.URLError(ssl.SSLCertVerificationError('fixture')),
                      urllib.error.HTTPError(fetch.URL,403,'No',{},sio.BytesIO())]:
            sleeps=[];c=fetch.Client(mock.Mock(side_effect=error),sleeps.append)
            with self.assertRaises(RuntimeError):c.get([o['id']])
            self.assertEqual(sleeps,[])

    def test_resume_requests_only_missing_ids_and_detects_tamper(self):
        a,oa=fixture(0);b,ob=fixture(1)
        client=mock.Mock();client.get.side_effect=[json.dumps(oa).encode(),json.dumps(ob).encode()]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);found=fetch.recover_unit(p,[a,b],'x',client)
            self.assertEqual(len(found),2);self.assertEqual(client.get.call_args_list[1].args[0],[ob['id']])
            client.get.reset_mock();fetch.recover_unit(p,[a,b],'x',client);client.get.assert_not_called()
            (p/'pass_0/response_PRIVATE.ndjson.gz').write_bytes(b'corrupt')
            with self.assertRaises(RuntimeError):fetch.recover_unit(p,[a,b],'x',client)

    def test_short_budget_mates_bounds_and_perspective(self):
        t,o=fixture();g,rows=logic.validated_game(o,t)
        e=FakeEngine();white=engines.score_position(rows[0],e);black=engines.score_position({**rows[0],'recipient_color':'black'},e)
        self.assertEqual(white['cp_recipient'],-black['cp_recipient']);self.assertEqual(e.calls[0][1],100000)
        short=engines.score_position(rows[0],FakeEngine(nodes=123));self.assertEqual(short['status'],'SCORED_BELOW_REQUESTED_NODES')
        mate=engines.score_position(rows[0],FakeEngine(mate=True));self.assertIsNone(mate['cp_recipient']);self.assertEqual(mate['mate_recipient'],3)
        bound=engines.score_position(rows[0],FakeEngine(bound=True));self.assertEqual(bound['status'],'BOUNDED_SCORE');self.assertIsNone(bound['cp_recipient'])

    def test_features_cp_direction_and_mate_missingness(self):
        t,o=fixture();g,rows=logic.validated_game(o,t);scores=[engines.score_position(r,FakeEngine()) for r in rows]
        f=engines.game_features([g],scores)[0]
        self.assertEqual(f['recipient_move_1_cp_change'],10);self.assertEqual(f['recipient_move_1_cp_loss'],-10)
        scores[-1]['cp_recipient']=None;scores[-1]['mate_recipient']=3
        f=engines.game_features([g],scores)[0];self.assertIsNone(f['recipient_move_1_cp_loss']);self.assertTrue(f['recipient_move_1_has_mate_score'])

    def test_cache_reuses_scores_without_reusing_game_identity(self):
        t,o=fixture();_,rows=logic.validated_game(o,t);e=FakeEngine();engines.SCORE_CACHE.clear()
        with mock.patch.object(engines,'ENGINE',e):
            first=engines.cached_score(rows[0]);second=engines.cached_score({**rows[0],'cohort_row_id':99,'exposure_game_id':'other000'})
        self.assertEqual(len(e.calls),1);self.assertEqual(second['cohort_row_id'],99);self.assertFalse(second['search_executed'])
        self.assertEqual(first['cp_recipient'],second['cp_recipient']);engines.SCORE_CACHE.clear()

    def test_plan_units_have_exact_denominator_and_no_duplicates(self):
        targets=[fixture(i)[0] for i in range(303)]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);source=p/'targets.parquet';io.table(source,pa.Table.from_pylist(targets));(p/'plan').mkdir()
            r=run.build_plan(p/'plan',[source],{'target_rows':303,'requested_board_positions':1212})
            self.assertEqual(r,{'rows':303,'units':2});units=io.load(p/'plan/units.json');self.assertEqual([x['rows'] for x in units],[300,3])
            io.table(source,pa.Table.from_pylist(targets+[targets[0]]));(p/'bad').mkdir()
            with self.assertRaises(RuntimeError):run.build_plan(p/'bad',[source],{'target_rows':304,'requested_board_positions':1216})

    def test_monthly_plan_preserves_exact_batch_order_and_boundaries(self):
        targets=[fixture(i)[0] for i in range(903)]
        for i,row in enumerate(targets):row['optional_probe']=None if i%3 else .25
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);sources=[];expected=[];offset=0
            schema=pa.Table.from_pylist(targets[:3]).schema
            for month_index,size in enumerate((601,0,302)):
                rows=list(reversed(targets[offset:offset+size]));offset+=size
                source=p/f'source_{month_index}.parquet'
                io.table(source,pa.Table.from_pylist(rows,schema=schema));sources.append(source)
                ordered=sorted(rows,key=lambda r:(r['pilot_hash'],r['exposure_game_id']))
                expected.extend(ordered[i:i+300] for i in range(0,len(ordered),300))
            plan=p/'plan';plan.mkdir()
            run.build_plan(plan,sources,{'target_rows':903,'requested_board_positions':3612})
            units=io.load(plan/'units.json')
            self.assertEqual([u['rows'] for u in units],[300,300,1,300,2])
            self.assertEqual(len(list(plan.glob('*.parquet'))),2)
            self.assertFalse(list(plan.glob('unit_*.parquet')))
            with compact_plan.Reader(plan) as reader,\
                 mock.patch.object(io,'checked',wraps=io.checked) as checked:
                actual=[reader.read(unit).to_pylist() for unit in units]
                self.assertEqual(checked.call_count,2)
            self.assertEqual(actual,expected)

    def test_compact_snapshot_rejects_wrong_batch_and_file_change(self):
        targets=[fixture(i)[0] for i in range(603)]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);source=p/'targets.parquet';io.table(source,pa.Table.from_pylist(targets))
            plan=p/'plan';plan.mkdir()
            run.build_plan(plan,[source],{'target_rows':603,'requested_board_positions':2412})
            units=io.load(plan/'units.json')
            with compact_plan.Reader(plan) as reader:
                reader.read(units[0])
                with self.assertRaisesRegex(RuntimeError,'batch values changed'):
                    reader.read({**units[1],'row_group':0})
                with self.assertRaisesRegex(RuntimeError,'row-group index'):
                    reader.read({**units[0],'row_group':-1})
                file=plan/units[0]['target_path'];rows=io.read(file).to_pylist()
                rows[0]['a1_att_weight']=999.0
                compact_plan.write_month(file,pa.Table.from_pylist(rows))
                with self.assertRaisesRegex(RuntimeError,'snapshot changed'):
                    reader.read(units[1])
            with compact_plan.Reader(plan) as reader:
                with self.assertRaises(RuntimeError):reader.read(units[0])

    def test_compact_plan_reuses_original_full_move_response(self):
        targets=[];records={}
        for i in range(4):target,record=fixture(i);targets.append(target);records[record['id']]=record
        ordered=sorted(targets,key=lambda r:(r['pilot_hash'],r['exposure_game_id']))
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);flat=p/'flat';flat.mkdir();path=flat/'unit_00000.parquet'
            io.table(path,pa.Table.from_pylist(ordered))
            old={'unit':'unit_00000','target_path':path.name,'sha256':io.sha(path),'rows':4}
            first=p/'first';first.mkdir();client=mock.Mock()
            client.get.return_value=b'\n'.join(json.dumps(o).encode() for o in records.values())
            run.replay_unit(first,old,flat,'old',client);self.assertEqual(client.get.call_count,1)
            plan=p/'compact';plan.mkdir()
            run.build_plan(plan,[path],{'target_rows':4,'requested_board_positions':16})
            new=io.load(plan/'units.json')[0];second=p/'second';second.mkdir()
            client.get.reset_mock()
            _,summary=run.replay_unit(second,new,plan,'new',client)
            self.assertEqual(summary['verified'],4);client.get.assert_not_called()

    def test_replay_unit_full_checkpoint_and_reuse(self):
        targets=[];records={}
        for i in range(4):t,o=fixture(i);targets.append(t);records[o['id']]=o
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);plan=p/'plan';plan.mkdir();root=p/'run';root.mkdir();path=plan/'u.parquet';io.table(path,pa.Table.from_pylist(targets))
            unit={'unit':'u','target_path':'u.parquet','sha256':io.sha(path),'rows':4}
            client=mock.Mock();client.get.return_value=b'\n'.join(json.dumps(o).encode() for o in records.values())
            dest,summary=run.replay_unit(root,unit,plan,'x',client);self.assertEqual(summary['verified'],4)
            client.get.reset_mock();run.replay_unit(root,unit,plan,'x',client);client.get.assert_not_called()
            # A new code/config version can still reuse exact full-move responses.
            other=p/'another_run';other.mkdir();run.replay_unit(other,unit,plan,'new_code',client);client.get.assert_not_called()

    def test_engine_unit_protocol_assembly_balance_and_restart(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);fake=p/'fake.py';fake.write_text(FAKE_UCI);replay=p/'replay';replay.mkdir()
            ts=[];records={}
            for i in range(6):target,o=fixture(i);ts.append(target);records[o['id']]=o
            games,positions=logic.replay_records(ts,records);io.table(replay/'games_PRIVATE.parquet',games);io.table(replay/'positions_PRIVATE.parquet',positions)
            engines.init_engine([sys.executable,str(fake)])
            try:
                dest,stats=engines.evaluate_unit((str(replay),str(p/'engine'),'conf'))
                self.assertEqual(stats['games'],6);self.assertEqual(stats['positions'],24)
                self.assertEqual(stats['score_statuses'],{'SCORED':24})
                self.assertLess(stats['engine_searches_executed'],24)
            finally:engines.close_engine()
            # Completed checkpoint needs no live engine.
            engines.evaluate_unit((str(replay),str(p/'engine'),'conf'))
            (p/'final').mkdir();r=run.assemble(p/'final',[Path(dest)],6);self.assertEqual(r['rows'],6)
            saved=io.read(p/'final/trajectory_features_PRIVATE.parquet');self.assertEqual(saved.num_rows,6)
            self.assertTrue((p/'final/trajectory_balance.csv').is_file())

    def test_checkpoint_configuration_and_tamper_guards(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'x';io.stage(root,'one',lambda out:(out/'a').write_text('x') and {})
            with self.assertRaises(RuntimeError):io.complete(root,'two')
            (root/'a').write_text('changed')
            with self.assertRaises(RuntimeError):io.complete(root,'one')

    def test_batch_returns_before_thread_shutdown_without_exit_hooks(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);fake=p/'fake.py';fake.write_text(FAKE_UCI)
            replay=p/'replay';replay.mkdir();target,record=fixture()
            games,positions=logic.replay_records([target],{record['id']:record})
            io.table(replay/'games_PRIVATE.parquet',games)
            io.table(replay/'positions_PRIVATE.parquet',positions)
            process=mp.get_context('spawn').Process(target=batch_then_join_threads,
                args=((str(replay),str(p/'engine'),'cleanup'),[sys.executable,str(fake)]))
            process.start()
            try:
                process.join(20)
                self.assertFalse(process.is_alive(),'Engine thread prevented worker shutdown')
                self.assertEqual(process.exitcode,0)
                self.assertEqual(io.load(p/'engine/summary.json')['positions'],4)
            finally:
                if process.is_alive():process.terminate();process.join(5)
                if process.is_alive():process.kill();process.join(5)
                process.close()

    def test_batch_exception_closes_engine_and_retry_can_finish(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);fake=p/'fake.py';fake.write_text(FAKE_UCI)
            replay=p/'replay';replay.mkdir();target,record=fixture()
            games,positions=logic.replay_records([target],{record['id']:record})
            io.table(replay/'games_PRIVATE.parquet',games)
            io.table(replay/'positions_PRIVATE.parquet',positions)
            engines.prepare_worker([sys.executable,str(fake)])
            opened=[];real_open=chess.engine.SimpleEngine.popen_uci
            def capture(*a,**kw):
                engine=real_open(*a,**kw);opened.append(engine);return engine
            job=(str(replay),str(p/'engine'),'cleanup_failure')
            with mock.patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=capture),\
                 mock.patch.object(engines,'game_features',side_effect=RuntimeError('synthetic failure')):
                with self.assertRaisesRegex(RuntimeError,'synthetic failure'):engines.evaluate_unit(job)
            self.assertEqual(len(opened),1);self.assertIsNone(engines.ENGINE)
            self.assertEqual(opened[0].returncode.result(timeout=2),0)
            self.assertFalse((p/'engine/_DONE.json').exists())
            # Worker-local scores still cache across batches; no exit hook is
            # needed for cleanup and a fresh checkpoint can be completed.
            _,result=engines.evaluate_unit(job)
            self.assertEqual(result['positions'],4);self.assertIsNone(engines.ENGINE)

    def test_authentication_and_changed_target_detection(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);project=base/'project';project.mkdir();package=base/'package';(package/'evidence').mkdir(parents=True)
            view=project/run.VIEW_REL;config={'fixture':'authenticated'};conf=io.cfgsha(config)
            prep=project/run.PREP_REL/conf[:16];prep.mkdir(parents=True);io.js(prep/'RUN_CONFIG.json',config)
            definitions={'core_success_sha256':'output/dynamic_prosociality_core_v102/POOL_MAIN_WAVE2B1_CORE/_SUCCESS.json',
                'core_summary_sha256':'output/dynamic_prosociality_core_v102/POOL_MAIN_WAVE2B1_CORE/summary.json',
                'a1_private_sha256':'derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet',
                'a1_producer_sha256':'replication_package/code/10c_estimate_dynamic_prosociality_core.py'}
            lineage={}
            for key,relative in definitions.items():
                path=view/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(key.encode());lineage[key]=io.sha(path)
            authority={'status':'A1_PREPARATION_COMPLETE','config_sha256':conf,'lineage':lineage}
            io.js(package/'evidence/SUMMARY.json',authority);io.js(prep/'_SUCCESS.json',authority)
            target,_=fixture();month={'month':'2024-01','rows':1,'requested_board_positions':4}
            expected={'target_rows':1,'requested_board_positions':4,'monthly':[month]}
            io.js(package/'evidence/trajectory_targets_summary.json',expected);io.js(prep/'targets/target_summary.json',expected)
            item={'month':'2024-01','relative_path':'fixture','sha256':'test'}
            io.js(package/'evidence/main_sample_report.json',{'panel_outputs':[item]})
            def create(out):
                io.table(out/'targets_PRIVATE.parquet',pa.Table.from_pylist([target]))
                io.js(out/'target_summary.json',{k:v for k,v in month.items() if k!='month'})
            dest=prep/'targets/month_2024-01';io.stage(dest,io.cfgsha([conf,item]),create)
            with mock.patch.object(run,'PACKAGE',package):
                found=run.authenticate(project);self.assertEqual(found[3]['target_rows'],1)
                (dest/'targets_PRIVATE.parquet').write_bytes(b'changed')
                with self.assertRaises(RuntimeError):run.authenticate(project)

    def test_full_execute_parallel_workers_and_resume(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);project=p/'project';project.mkdir();desktop=p/'desktop';desktop.mkdir()
            fake=p/'fake_stockfish';fake.write_text('#!'+sys.executable+'\n'+FAKE_UCI);fake.chmod(0o700)
            targets=[];records={}
            for i in range(303):a,o=fixture(i);targets.append(a);records[o['id']]=o
            source=p/'targets.parquet';io.table(source,pa.Table.from_pylist(targets))
            expected={'target_rows':303,'requested_board_positions':1212}
            authority={'config_sha256':'synthetic','lineage':{'synthetic':'offline'}}
            inputs=(p,[source],[{'sha256':io.sha(source),'rows':4}],expected,authority)
            client=fetch.Client(lambda req,**kw:DummyResponse(b'\n'.join(json.dumps(records[k]).encode() for k in req.data.decode().split(','))),lambda _:None)
            # Exercise the actual engine probe/protocol, with an explicit fixture hash.
            real_probe=engines.probe
            def probe(path,unused):return real_probe(path,io.sha(fake))
            args=__import__('argparse').Namespace(project_root=project,desktop=desktop,stockfish=str(fake),workers=2)
            with contextlib.redirect_stdout(sio.StringIO()),mock.patch.object(run,'authenticate',return_value=inputs),mock.patch.object(fetch,'Client',return_value=client),mock.patch.object(engines,'probe',side_effect=probe):
                run.execute(args);first=client.requests;self.assertEqual(first,2)
                run.execute(args);self.assertEqual(client.requests,first)
            complete=list((project/run.OUT_REL).glob('*/_SUCCESS.json'));self.assertEqual(len(complete),1)
            summary=io.load(complete[0]);self.assertEqual(summary['status'],'A1_TRAJECTORY_BUILD_COMPLETE')
            self.assertEqual(summary['engine']['positions'],1212);self.assertFalse(summary['new_treatment_effects_estimated'])

    def test_aggregate_report_contains_no_private_rows(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'secret_PRIVATE').write_text('PRIVATE_NAME')
            with contextlib.redirect_stdout(sio.StringIO()):run.report(p,p,{'status':'TEST'})
            z=next(p.glob('*.zip'));self.assertEqual(io.sha(z),Path(str(z)+'.sha256').read_text().split()[0])
            with zipfile.ZipFile(z) as archive:
                self.assertIsNone(archive.testzip())
                for n in archive.namelist():self.assertNotIn(b'PRIVATE_NAME',archive.read(n))
                entries=json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('REPORT_MANIFEST.json'))))
                import hashlib
                root=archive.namelist()[0].split('/')[0]
                for r in entries:self.assertEqual(hashlib.sha256(archive.read(root+'/'+r['path'])).hexdigest(),r['sha256'])

if __name__=='__main__':
    faulthandler.enable()
    faulthandler.dump_traceback_later(45,repeat=True)
    try:unittest.main(verbosity=2)
    finally:faulthandler.cancel_dump_traceback_later()
