"""Numerical, session-construction, serialization, and restart checks."""
from __future__ import annotations
import ast
import contextlib
import csv
import io
import itertools
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from runner import common, run_c9


def fixture_b2(root, rows, users, grants):
    source = (run_c9.PACKAGE / "source/b2_reference.py").read_text()
    nodes = ast.parse(source)
    replacement = {"EXPECTED_ROWS": rows, "EXPECTED_CHOOSERS": users, "EXPECTED_KIND_DRAWS": grants}
    lines = source.splitlines(keepends=True)
    edits = []
    for node in nodes.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in replacement:
            edits.append((node.lineno-1, node.end_lineno, f"{node.targets[0].id} = {replacement[node.targets[0].id]}\n"))
    for first, last, text in sorted(edits, reverse=True):
        lines[first:last] = [text]
    file = root / "synthetic_b2.py"
    file.write_text("".join(lines))
    return file, common.load_source_module(file, "synthetic_b2")


class C9Tests(unittest.TestCase):
    def test_exact_conditional_law_by_enumeration(self):
        b2 = common.load_source_module(run_c9.PACKAGE / "source/b2_reference.py", "b2_reference")
        weights = np.array([0.2, 0.6, 1.5, 3.0, 7.0])
        selection = b2.conditional_selection_probabilities(np.log(weights), 2)
        combinations = list(itertools.combinations(range(5), 2))
        normalizer = sum(np.prod(weights[list(x)]) for x in combinations)
        total = 0.
        for chosen in combinations:
            probability = 1.
            remaining = 2
            for position in range(5):
                prob = 1. if remaining == 5-position else (selection[position, remaining] if remaining else 0.)
                probability *= prob if position in chosen else 1.-prob
                if position in chosen:
                    remaining -= 1
            self.assertAlmostEqual(probability, np.prod(weights[list(chosen)])/normalizer, places=13)
            total += probability
        self.assertAlmostEqual(total, 1., places=13)

    def test_pseudo_first_changes_partitions_and_boundary(self):
        c9 = run_c9.load_c9()
        c9.self_test()
        times = np.array([0, 0, 86400000, 604800000, 604800001], dtype=np.int64)
        choices = np.array([[1,0,1,0,0], [0,0,1,0,1]], dtype=bool)
        got = c9.c9_totals(times, np.array([1,1,2,3,3]), np.array(['blitz','blitz','rapid','blitz','rapid']), choices)
        self.assertEqual(got['b2_den'][0,1], 2)  # Same-time later sequence row counts, exactly 24h counts.
        self.assertEqual(got['b2_den'][0,2], 3)  # Exactly seven days counts; +1ms does not.
        self.assertEqual(got['b2_den'][1,2], 2)  # New simulated anchor changes the window.
        self.assertEqual(got['later7_num'][1], 1)
        self.assertEqual(got['same7_den'][0], 1)
        self.assertEqual(got['same7_den'][1], 0)

    def test_all_game_bridge_session_rules_and_csv(self):
        c9 = run_c9.load_c9()
        with tempfile.TemporaryDirectory(prefix='c9_sessions_test_') as temp:
            root = Path(temp)
            base = c9.PANEL_START_MS + 86400000
            starts = [base, base+40*60000, base+70*60000]
            b1 = root/'b1.parquet'
            panel = root/'panel.parquet'
            chron = root/'chron.parquet'
            pq.write_table(pa.table({
                'b1_row_id':[0,1,2], 'chooser_index':[0,0,0], 'sequence_index':[0,1,2],
                'utc_ms':[x+1000 for x in starts], 'current_eval_cp':[20.,30.,40.],
                'current_chooser_elo':[1600.,1600.,1600.], 'current_opponent_elo':[1500.,1500.,1500.],
                'current_ply_count':[12.,14.,16.], 'current_speed_code':[77,77,88],
                'kind_draw':[True,False,True]}), b1)
            panel_dict = {'game_id':['first','second','third'],'chooser_user_id':[100,100,100],
                'api_speed':['blitz','blitz','rapid'], 'api_last_move_at_ms':[x+1000 for x in starts],
                'utc_ms':starts, 'engine_eval_cp_disconnected':[20.,30.,40.], 'chooser_elo':[1600.,1600.,1600.],
                'disconnected_elo':[1500.,1500.,1500.], 'ply_count':[12.,14.,16.], 'kind_draw':[False,True,False]}
            pq.write_table(pa.table(panel_dict), panel)
            # Ordinary non-timeout game at minute 20 bridges a 40-minute opportunity gap.
            pq.write_table(pa.table({'white_id':[100]*4,'black_id':[999]*4,
                'game_id':['first','ordinary','second','third'],
                'utc_ms':[base,base+20*60000,base+40*60000,base+70*60000]}), chron)
            c9.EXPECTED_B1_ROWS = 3
            c9.EXPECTED_B1_CHOOSERS = 1
            con = c9.setup_duckdb(root/'spill', 1, '512MB')
            try:
                result = c9.b1_stage07_mapping(con,b1,[panel],root)
                self.assertFalse(result['mapping_uses_kind_draw'])
                self.assertEqual(result['selected_time_field'], 'api_last_move_at_ms')
                rows=[{'path':chron,'bytes':chron.stat().st_size,'rows':4,
                       'utc_ms_min':base,'utc_ms_max':base+70*60000}]
                cache, report = c9.build_session_cache(con,b1,root/'unused_prop',rows,root,root)
                table = pq.read_table(cache).to_pydict()
                self.assertEqual(table['session_id'], [1,1,2])  # Exactly 30 min starts a new session.
                self.assertEqual(table['speed'], ['blitz','blitz','rapid'])
                self.assertEqual(report['repeat_granter_all_game_rows'],4)
                c9.outcome_blind_support(b1,cache,root)
            finally:
                con.close()
            run_c9.write_csv(root/'publication.csv',[{'a':1},{'a':2,'primary_only':'C'}])
            with (root/'publication.csv').open(newline='') as f:
                saved = list(csv.DictReader(f))
            self.assertEqual(saved[1]['primary_only'],'C')
            self.assertEqual(saved[0]['primary_only'],'')

    def test_spawn_full_draw_reproduction_and_checkpoint_resume(self):
        c9 = run_c9.load_c9()
        with tempfile.TemporaryDirectory(prefix='c9_draw_test_') as temp:
            root=Path(temp)
            b1=root/'b1.parquet'; prop=root/'prop.parquet'; sess=root/'sessions.parquet'
            users=6; n=5; total=users*n
            chooser=np.repeat(np.arange(users,dtype=np.int64),n)
            sequence=np.tile(np.arange(n,dtype=np.int32),users)
            times=np.tile(np.array([0,600000,2400000,86400000,604800000],dtype=np.int64),users)+1700000000000
            kind=np.tile(np.array([0,1,0,1,0],dtype=bool),users)
            kind[:2*n]=True  # Guaranteed pooled support; remaining users have varying pseudo-first grants.
            sessions=np.concatenate([np.ones(n,dtype=np.int64),np.arange(n,dtype=np.int64)]+[np.array([1,1,2,3,4])]*4)
            speeds=np.array(['blitz']*5+['a','b','c','d','e']+['blitz','blitz','rapid','rapid','blitz']*4)
            pq.write_table(pa.table({'b1_row_id':np.arange(total,dtype=np.int64),'chooser_index':chooser,
                'sequence_index':sequence,'utc_ms':times,'kind_draw':kind,'current_draw_payoff':np.tile([-1.,0.,1.,-1.,1.],users)}),b1)
            pq.write_table(pa.table({'b1_row_id':np.arange(total,dtype=np.int64),'static_propensity':np.tile([.02,.1,.2,.4,.05],users)}),prop)
            pq.write_table(pa.table({'b1_row_id':np.arange(total,dtype=np.int64),'chooser_index':chooser,
                'sequence_index':sequence,'session_id':sessions,'speed':speeds}),sess)
            b2path,b2=fixture_b2(root,total,users,int(kind.sum()))
            state=root/'c9_state'; (state/'randomizations').mkdir(parents=True)
            with contextlib.redirect_stdout(io.StringIO()):
                simulated=c9.run_randomizations(b1,prop,sess,b2path,state,'synthetic-c9',2)
            data,probability=b2.load_inputs(b1,prop)
            reference=root/'reference'; (reference/'randomizations').mkdir(parents=True)
            expected_num=[];expected_den=[]
            for start in range(0,4999,250):
                stop=min(start+250,4999)
                batch=b2.simulate_batch(data=data, probability=probability,simulations=stop-start,
                     seed_components=[2026082201,start,stop],progress_label='synthetic')
                expected_num.append(batch['numerators']);expected_den.append(batch['denominators'])
                path=reference/'randomizations'/f'b2_{start:04d}_{stop-1:04d}.npz'
                np.savez_compressed(path,**batch)
                common.atomic_json(path.with_suffix('.json'),{'status':'DYNAMIC_B2_RANDOMIZATION_BATCH_OK',
                    'config_sha256':run_c9.SPEC['b2_config_sha256'],'start':start,'stop_exclusive':stop,
                    'seed_components':[2026082201,start,stop],'output_path':str(path),
                    'output_sha256':common.sha256_file(path),'output_bytes':path.stat().st_size})
            self.assertTrue(np.array_equal(simulated['b2_num'],np.concatenate(expected_num)))
            self.assertTrue(np.array_equal(simulated['b2_den'],np.concatenate(expected_den)))
            checked=run_c9.compare_b2_batches({'b2_state':reference},simulated,b2)
            self.assertEqual(checked['draws'],4999)
            first_hashes={p.name:common.sha256_file(p) for p in (state/'randomizations').iterdir()}
            with contextlib.redirect_stdout(io.StringIO()):
                again=c9.run_randomizations(b1,prop,sess,b2path,state,'synthetic-c9',2)
            self.assertTrue(np.array_equal(again['later7_num'],simulated['later7_num']))
            self.assertEqual(first_hashes,{p.name:common.sha256_file(p) for p in (state/'randomizations').iterdir()})
            bad={k:v.copy() for k,v in simulated.items()}
            bad['b2_num'][3,0]+=1
            with self.assertRaisesRegex(RuntimeError,'do not reproduce'):
                run_c9.compare_b2_batches({'b2_state':reference},bad,b2)
            run_c9.validate_partitions(simulated)
            observed=c9.observed_totals(data,sessions,speeds)
            run_c9.validate_partitions(observed)
            rows,contrasts,summary=c9.summarize_c9(observed,simulated)
            run_c9.write_csv(root/'c9_results.csv',rows)
            self.assertEqual(len(rows),4)
            self.assertEqual(len(contrasts),2)
            self.assertTrue(np.isfinite(summary['primary_excess_percentage_points']))
            with self.assertRaisesRegex(RuntimeError,'checkpoint mismatch'):
                path,receipt=c9.batch_checkpoint_paths(state,0,250)
                c9.authenticate_checkpoint(path,receipt,0,250,'different-scientific-config')


if __name__=='__main__':
    unittest.main(verbosity=2)
