#!/usr/bin/env python3
"""Meaningful synthetic checks; does not touch the research panel or network."""
from __future__ import annotations
import json
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
import duckdb
from common import sha, one
from estimates import group_expression, make_cells, estimate_cells, standardize
from registry import parse_directory
from run_audience import load_profiles, register_streamers, build_base, configure

def fixture_db():
    db=duckdb.connect()
    db.execute('''CREATE TABLE base(chooser VARCHAR,opponent VARCHAR,y INTEGER,state INTEGER,
       ce INTEGER,de INTEGER,ply INTEGER,cc DOUBLE,dc DOUBLE,speed VARCHAR,month_index INTEGER,
       cs BOOLEAN,ds BOOLEAN,ct BOOLEAN,dt BOOLEAN,cb BOOLEAN,dbot BOOLEAN,cp BOOLEAN,dp BOOLEAN)''')
    rng=np.random.default_rng(12491)
    rows=[]
    # Each account appears on several occasions and can cross the elite threshold.
    for i in range(24):
        for j in range(120):
            state=j%3
            ce=1500 if j%5 else 2500
            de=ce+40
            cs=i%4==0
            ds=(j%11==0)
            ct=i%7==0
            p=.10 + .11*(state==1)+.035*cs+.03*(ce>=2400)+.08*(i%3==0)
            rows.append((f'fixture_{i}',f'opponent_{j%13}',int(rng.random()<p),state,
                         ce,de,20,40.,35.,'blitz',1,cs,ds,ct,False,False,False,i%2==0,j%2==0))
    db.executemany('INSERT INTO base VALUES('+','.join('?' for _ in range(19))+')',rows)
    return db

def dummy_fe(rows):
    # Independent row-level OLS, explicitly including all chooser indicators.
    ids=sorted(set(r[0] for r in rows))
    states={i:set() for i in ids}
    for uid,y,d in rows:states[uid].add(d)
    ids=[i for i in ids if states[i]=={0,1}]
    rows=[r for r in rows if r[0] in ids]
    index={uid:i for i,uid in enumerate(ids)}
    N,G=len(rows),len(ids)
    X=np.zeros((N,G+1));y=np.empty(N)
    for n,(uid,yi,d) in enumerate(rows):
        X[n,index[uid]]=1;X[n,-1]=d;y[n]=yi
    inv=np.linalg.inv(X.T@X)
    beta=inv@X.T@y
    residual=y-X@beta
    scores=np.zeros((G,G+1))
    for n,(uid,_,_) in enumerate(rows):scores[index[uid]]+=X[n]*residual[n]
    covariance=inv@scores.T@scores@inv*G/(G-1)*(N-1)/(N-G-1)
    return beta[-1],math.sqrt(covariance[-1,-1])

class AuditTests(unittest.TestCase):
    def test_fe_matches_explicit_dummy_ols(self):
        db=fixture_db()
        expr=group_expression(2400,'rating_directory_known_titles','either_player')
        make_cells(db,expr)
        N,K=db.execute('SELECT count(*),sum(y) FROM base').fetchone()
        s,e,c=estimate_cells(db,{'test':'synthetic'},N,K)
        for g in (0,1,2):
            rows=db.execute(f'SELECT chooser,y,state FROM base WHERE state IN(0,1) AND ({expr})={g}').fetchall()
            beta,se=dummy_fe(rows)
            r=next(x for x in e if x['group_code']==g and x['metric']=='chooser_fe_gradient')
            self.assertAlmostEqual(r['estimate']/100,beta,places=12)
            self.assertAlmostEqual(r['cluster_se']/100,se,places=12)
        self.assertEqual(sum(r['opportunities'] for r in s),N)
        self.assertEqual(sum(r['kind_draws'] for r in s),K)
        db.close()

    def test_raw_contrast_preserves_cross_group_account_covariance(self):
        db=fixture_db();expr=group_expression(2400,'rating_and_directory','either_player')
        make_cells(db,expr);N,K=db.execute('SELECT count(*),sum(y) FROM base').fetchone()
        _,_,contrasts=estimate_cells(db,{},N,K)
        row=next(r for r in contrasts if r['group_a']=='known_streamer' and r['metric']=='raw_gradient')
        data=db.execute(f'SELECT chooser,y,state,{expr} g FROM base WHERE state IN(0,1)').fetchall()
        scores={};gaps={}
        for g in (0,2):
            a=[r for r in data if r[3]==g];G=len(set(r[0] for r in a));N=len(a)
            nf=sum(r[2]==1 for r in a);nw=N-nf
            pf=sum(r[1] for r in a if r[2]==1)/nf
            pw=sum(r[1] for r in a if r[2]==0)/nw;gaps[g]=pf-pw
            fac=math.sqrt(G/(G-1)*(N-1)/(N-2))
            for uid,y,d,_ in a:
                influence=(y-pf)/nf if d==1 else -(y-pw)/nw
                scores[uid]=scores.get(uid,0)+(1 if g==2 else -1)*fac*influence
        self.assertAlmostEqual(row['difference_pp'],100*(gaps[2]-gaps[0]),places=12)
        self.assertAlmostEqual(row['cluster_se_pp'],100*math.sqrt(sum(v*v for v in scores.values())),places=12)
        db.close()

    def test_common_support_and_no_extrapolation(self):
        db=fixture_db();expr=group_expression(2400,'rating_and_directory','chooser')
        rows=standardize(db,expr,{},min_cell=2)
        self.assertEqual(rows[0]['status'],'no_common_support') # Elite ratings cannot match the remainder.
        streamer=rows[1]
        self.assertEqual(streamer['status'],'estimated')
        # At low ratings all control strata are identical in this fixture.
        raw=db.execute('''SELECT cs,state,avg(y) FROM base WHERE ce<2400 AND state IN(0,1)
                          GROUP BY cs,state''').fetchall()
        r={(bool(a),b):c for a,b,c in raw}
        target=(r[True,1]-r[True,0])-(r[False,1]-r[False,0])
        self.assertAlmostEqual(streamer['gradient_difference_pp'],100*target,places=12)
        db.close()

    def test_directory_parser_and_title(self):
        data=b'''<article class="streamer paginated"><a class="overlay" href="/streamer/Fake_Stream"></a>
           <span class="utitle">WGM</span></article>
           <a href="/streamer/edit">edit</a><a rel="next" href="/streamer?page=2&amp;requests=0">Next</a>'''
        p=parse_directory(data)
        self.assertEqual(p.users,{'fake_stream':'WGM'})
        self.assertEqual(p.next_url,'https://lichess.org/streamer?page=2&requests=0')
        with self.assertRaises(RuntimeError):
            parse_directory(b'<article class="streamer"></article><a rel="next" href="https://example.com/">bad</a>')

    def test_join_and_unknown_profile_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=duckdb.connect()
            db.execute('''CREATE TABLE source_profiles(username_norm VARCHAR,title VARCHAR,
                   returned BOOLEAN,queried_at_utc VARCHAR)''')
            db.execute("INSERT INTO source_profiles VALUES ('a1','WIM',true,'2026-08-01'),('a2','',true,'2026-08-01'),('a3',NULL,false,'2026-08-01')")
            profiles=root/'profiles.parquet'
            db.execute(f"COPY source_profiles TO '{profiles}' (FORMAT PARQUET)")
            src,info=load_profiles(db,[profiles]);self.assertEqual(info['returned_accounts'],2)
            register_streamers(db,{'op3':''})
            db.execute('''CREATE TABLE original(chooser_username_norm VARCHAR,disconnected_username_norm VARCHAR,
                kind_draw BOOLEAN,fair_competitive BOOLEAN,clearly_worse BOOLEAN,chooser_elo INTEGER,
                disconnected_elo INTEGER,ply_count INTEGER,api_speed VARCHAR,
                chooser_clock_last_obs_s DOUBLE,disconnected_clock_last_obs_s DOUBLE,game_id VARCHAR)''')
            db.execute("""INSERT INTO original VALUES ('a1','op1',true,true,false,1400,1500,20,'blitz',20,10,'game1'),
                 ('a2','op2',false,false,true,2500,2500,30,'blitz',40,20,'game2'),
                 ('a3','op3',false,true,false,1400,1500,10,'blitz',10,6,'game3')""")
            p=root/'source.parquet';db.execute(f"COPY original TO '{p}' (FORMAT PARQUET)")
            a={'month':'2023-11','rows':3,'sha256':sha(p)}
            build_base(db,[p],[a],root/'cache')
            rows={r[0]:r[1:] for r in db.execute('SELECT chooser,ct,cp,ds FROM base').fetchall()}
            self.assertEqual(rows['a1'],(True,True,False))
            self.assertEqual(rows['a2'],(False,True,False))
            self.assertEqual(rows['a3'],(False,False,True))
            expr=group_expression(2400,'rating_directory_known_titles','either_player')
            self.assertEqual(db.execute(f"SELECT {expr} FROM base WHERE chooser='a3'").fetchone()[0],2)
            db.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
