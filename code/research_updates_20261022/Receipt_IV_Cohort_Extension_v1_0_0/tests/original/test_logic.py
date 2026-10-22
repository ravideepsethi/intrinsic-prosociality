#!/usr/bin/env python3
"""Definition/SQL tests require only Python's standard library.

DuckDB integration tests are separate and run by the launcher before recovery.
"""
from __future__ import annotations
import random
import sqlite3
import unittest
from collections import defaultdict
from rematch_logic import side_query, census_query


def calculate(games, focal):
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE ev(game_id TEXT,utc_ms INTEGER,archive_ordinal INTEGER,user_id INTEGER,opponent_id INTEGER)')
    rows = [(g,t,i,a,b) for g,t,i,a,b in games] + [(g,t,i,b,a) for g,t,i,a,b in games]
    con.executemany('INSERT INTO ev VALUES (?,?,?,?,?)', rows)
    con.execute('CREATE TABLE targets(game_id TEXT,user_id INTEGER)')
    con.execute('CREATE TABLE f(game_id TEXT,p1 INTEGER,p2 INTEGER)')
    con.executemany('INSERT INTO f VALUES (?,?,?)', focal)
    con.executemany('INSERT INTO targets VALUES (?,?)', [(g,p) for g,a,b in focal for p in (a,b)])
    con.execute('CREATE TABLE sides AS '+side_query())
    result = {r['game_id']:dict(r) for r in con.execute(census_query())}
    con.close()
    return result


def reference(games, focal):
    per_user=defaultdict(list)
    for g,t,i,a,b in games:
        per_user[a].append((t,i,g,b))
        per_user[b].append((t,i,g,a))
    positions={}
    for u,ev in per_user.items():
        ev.sort()
        for k,e in enumerate(ev): positions[u,e[2]]=(ev,k)
    out={}
    for g,a,b in focal:
        locs=[positions.get((a,g)),positions.get((b,g))]
        valid=all(l is not None for l in locs)
        if valid:
            x,y=(l[0][l[1]] for l in locs)
            valid=x[0]==y[0] and x[3]==b and y[3]==a
        ans={'focal_mapping_ok':int(valid)}
        for prefix,step in [('previous',-1),('next',1)]:
            neighbors=[]; ambiguous=False
            for l in locs:
                if not l: neighbors.append(None); continue
                seq,k=l; n=k+step
                def at(j): return seq[j] if 0<=j<len(seq) else None
                e=at(k); v=at(n); v2=at(k+2*step)
                neighbors.append(v)
                for nearby in (at(k-1),at(k+1)):
                    if nearby and nearby[0]==e[0]: ambiguous=True
                if v and v2 and v[0]==v2[0]: ambiguous=True
            match=bool(valid and all(v is not None for v in neighbors)
                       and neighbors[0][2]==neighbors[1][2]
                       and neighbors[0][3]==b and neighbors[1][3]==a
                       and neighbors[0][0]==neighbors[1][0])
            ans[f'mutual_{prefix}_observed']=int(match)
            ans[f'{prefix}_start_order_ambiguous']=int(ambiguous)
            ans[f'mutual_{prefix}_same_pair']=None if not valid or ambiguous or any(v is None for v in neighbors) else int(match)
        out[g]=ans
    return out


class LogicTests(unittest.TestCase):
    def assert_reference(self, games, focal):
        got=calculate(games,focal); expected=reference(games,focal)
        self.assertEqual(set(got),set(expected))
        for g,row in expected.items():
            for k,v in row.items(): self.assertEqual(got[g][k],v,(g,k,v,got[g][k]))
        return got

    def test_chain_and_reversed_colors(self):
        games=[('g1',100,1,1,2),('g2',200,2,2,1),('g3',300,3,1,2)]
        r=self.assert_reference(games,[(g,a,b) for g,t,i,a,b in games])
        self.assertEqual(r['g2']['mutual_previous_same_pair'],1)
        self.assertEqual(r['g2']['mutual_next_same_pair'],1)
        self.assertIsNone(r['g1']['mutual_previous_same_pair'])
        self.assertIsNone(r['g3']['mutual_next_same_pair'])

    def test_intervening_nonfocal_game(self):
        games=[('g1',100,1,1,2),('other',150,2,1,3),('g2',200,3,1,2)]
        r=self.assert_reference(games,[('g2',1,2)])
        self.assertEqual(r['g2']['mutual_previous_same_pair'],0)

    def test_no_neighbors_and_missing_both_sides_retained(self):
        r=self.assert_reference([('g1',100,1,1,2)],[('g1',1,2),('absent',3,4)])
        self.assertEqual(len(r),2)
        self.assertIsNone(r['absent']['mutual_previous_same_pair'])
        self.assertEqual(r['absent']['focal_mapping_ok'],0)

    def test_equal_start_times_and_neighbor_ties(self):
        games=[('a',100,1,1,3),('b',100,2,1,2),('c',200,3,1,2),('d',300,4,1,2),('e',300,5,1,3)]
        r=self.assert_reference(games,[('c',1,2)])
        self.assertTrue(r['c']['mutual_previous_observed'])
        self.assertIsNone(r['c']['mutual_previous_same_pair'])
        self.assertTrue(r['c']['next_start_order_ambiguous'])

    def test_long_gap_is_only_an_adjacency_candidate(self):
        r=self.assert_reference([('a',1,1,1,2),('b',30*86400000,2,1,2)],[('b',1,2)])
        self.assertEqual(r['b']['previous_classification_status'],'mutual_adjacency_candidate_timing_unresolved')
        self.assertNotIn('is_rematch',r['b'])

    def test_inconsistent_focal_opponent(self):
        r=self.assert_reference([('a',100,1,1,2)],[('a',1,3)])
        self.assertEqual(r['a']['focal_mapping_ok'],0)
        self.assertIsNone(r['a']['mutual_next_same_pair'])

    def test_one_missing_neighbor_cannot_be_positive(self):
        con=sqlite3.connect(':memory:'); con.row_factory=sqlite3.Row
        con.execute('CREATE TABLE f(game_id TEXT,p1 INTEGER,p2 INTEGER)')
        con.execute("INSERT INTO f VALUES ('f',1,2)")
        con.execute('CREATE TABLE ev(game_id TEXT,utc_ms INTEGER,archive_ordinal INTEGER,user_id INTEGER,opponent_id INTEGER)')
        con.execute('CREATE TABLE targets(game_id TEXT,user_id INTEGER)')
        con.executemany('INSERT INTO ev VALUES (?,?,?,?,?)',[('p',10,1,1,2),('f',20,2,1,2),('f',20,2,2,1)])
        con.executemany('INSERT INTO targets VALUES (?,?)',[('f',1),('f',2)])
        con.execute('CREATE TABLE sides AS '+side_query())
        row=dict(con.execute(census_query()).fetchone())
        self.assertEqual(row['mutual_previous_observed'],0)
        self.assertIsNone(row['mutual_previous_same_pair'])
        con.close()

    def test_randomized_reference_equivalence(self):
        for seed in range(40):
            rng=random.Random(seed); games=[]; t=1000
            for i in range(140):
                a,b=rng.sample(range(1,14),2); t+=rng.choice([0,1,10,1000])
                games.append((f'g{i:05}',t,i,a,b))
            focal=[(g,a,b) for g,t,i,a,b in games if rng.random()<.6]
            focal.append(('absent',99,100))
            self.assert_reference(games,focal)

    def test_user_partition_equivalence_across_all_dates(self):
        games=[(f'g{i}',100+i,i,1+(i%7),10+(i%5)) for i in range(100)]
        focal=[(g,a,b) for g,t,i,a,b in games]
        whole=calculate(games,focal)
        # Independently partition every player side, not each game or each month.
        con=sqlite3.connect(':memory:'); con.row_factory=sqlite3.Row
        con.execute('CREATE TABLE f(game_id TEXT,p1 INTEGER,p2 INTEGER)')
        con.executemany('INSERT INTO f VALUES (?,?,?)',focal)
        all_sides=[]; side_cols=None
        for ub in range(8):
            con.execute('DROP TABLE IF EXISTS ev');con.execute('DROP TABLE IF EXISTS targets')
            con.execute('CREATE TABLE ev(game_id TEXT,utc_ms INTEGER,archive_ordinal INTEGER,user_id INTEGER,opponent_id INTEGER)')
            ev=[(g,t,i,u,v) for g,t,i,a,b in games for u,v in ((a,b),(b,a)) if u%8==ub]
            con.executemany('INSERT INTO ev VALUES (?,?,?,?,?)',ev)
            con.execute('CREATE TABLE targets(game_id TEXT,user_id INTEGER)')
            con.executemany('INSERT INTO targets VALUES (?,?)',[(g,u) for g,a,b in focal for u in (a,b) if u%8==ub])
            cur=con.execute(side_query()); side_cols=[d[0] for d in cur.description];all_sides.extend(cur.fetchall())
        con.execute('CREATE TABLE sides('+','.join(side_cols)+')')
        con.executemany('INSERT INTO sides VALUES ('+','.join('?' for _ in side_cols)+')',all_sides)
        rows={r['game_id']:dict(r) for r in con.execute(census_query())}
        self.assertEqual(rows,whole);con.close()

if __name__=='__main__': unittest.main(verbosity=2)
