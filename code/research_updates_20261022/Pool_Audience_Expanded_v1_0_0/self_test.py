#!/usr/bin/env python3
"""Independent OLS/cluster-sandwich and end-to-end tests using fake accounts."""
import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
import zipfile
import duckdb
import numpy as np
from common import qs,sha
from metadata import PROFILE_REL,DIRECTORY_REL,load_profiles,discover_profiles,load_directory
from analysis import PANEL_REL,build_base,mark,stage_expression,STAGES,SCOPES
from run_expanded import execute

def fixture(root):
    db=duckdb.connect();rng=np.random.default_rng(281793)
    records=[]
    # Some accounts never grant; accounts and their opponents have differing metadata coverage.
    for i in range(48):
        for j in range(72):
            state=j%3
            ce=1500+100*(i%5) if j%5 else 2500
            de=1550 if j%7 else 2450
            p=.06+.18*(state==1)+.04*(i%3==0)
            y=int(i!=0 and rng.random()<p)
            records.append((f'c{i}',f'o{j%18}',y,state==1,state==0,ce,de,f'g{i}_{j}'))
    db.execute('''CREATE TABLE p(chooser_username_norm VARCHAR,disconnected_username_norm VARCHAR,
      kind_draw BOOLEAN,fair_competitive BOOLEAN,clearly_worse BOOLEAN,
      chooser_elo INTEGER,disconnected_elo INTEGER,game_id VARCHAR)''')
    db.executemany('INSERT INTO p VALUES (?,?,?,?,?,?,?,?)',records)
    month='2023-11';panel=root/PANEL_REL/f'month={month}'/'analysis_panel.parquet'
    panel.parent.mkdir(parents=True);db.execute(f'COPY p TO {qs(panel)} (FORMAT PARQUET)')
    keys={r[0] for r in records}
    expected={
      'opportunities':len(records),'kind_draws':sum(r[2] for r in records),
      'chooser_accounts':len(keys),'granting_accounts':len({r[0] for r in records if r[2]}),
      'competitive_granting_accounts':len({r[0] for r in records if r[2] and r[3]})}
    for name,index in [('competitive',3),('clearly_worse',4)]:
        a=[r for r in records if r[index]]
        expected[name+'_opportunities']=len(a)
        expected[name+'_kind_draws']=sum(r[2] for r in a)
        b=[r for r in a if r[5]<1600]
        expected['below1600_'+name+'_opportunities']=len(b)
        expected['below1600_'+name+'_kind_draws']=sum(r[2] for r in b)
    pa={'repository_commit':'SYNTHETIC','monthly_inputs':[{'month':month,'bytes':panel.stat().st_size,
        'rows':len(records),'sha256':sha(panel)}],'expected_counts':expected}
    db.execute('''CREATE TABLE profiles(username_norm VARCHAR,returned BOOLEAN,queried_at_utc VARCHAR,
      raw_user_json VARCHAR,title VARCHAR,profile_bio VARCHAR,profile_links VARCHAR,play_time_tv_seconds BIGINT)''')
    prows=[];objects=[]
    for uid in [f'c{i}' for i in range(48) if i%4!=3]+[f'o{i}' for i in range(18) if i%3!=2]:
        i=int(uid[1:]);title='FM' if i%13==1 else 'BOT' if uid=='c22' else ''
        bio='https://www.youtube.com/@synthetic' if i%9==2 else ''
        tv=None if i%4==0 else (7200 if i%5==2 else 0)
        obj={'id':uid,'profile':{'bio':bio}}
        if title:obj['title']=title
        if tv is not None:obj['playTime']={'total':100000,'tv':tv}
        objects.append((uid,title,bio,tv))
        prows.append((uid,True,'2026-08-20',json.dumps(obj),title or None,bio,'',tv))
    prows.append(('failed',False,'2026-08-20',None,None,None,None,None))
    db.executemany('INSERT INTO profiles VALUES (?,?,?,?,?,?,?,?)',prows)
    profile=root/PROFILE_REL;profile.parent.mkdir(parents=True)
    db.execute(f'COPY profiles TO {qs(profile)} (FORMAT PARQUET)')
    ps={'returned_distinct_accounts':len(objects),'known_chess_title_accounts':sum(x[1]=='FM' for x in objects),
      'lm_title_accounts':0,'bot_accounts':sum(x[1]=='BOT' for x in objects),
      'accounts_with_streamer_field':0,'accounts_with_streaming_field':0,
      'accounts_with_structured_streamer_channel':0,'accounts_ever_observed_streaming_true':0,
      'positive_streamer_accounts':0,'channel_link_candidate_accounts':sum(bool(x[2]) for x in objects),
      'candidate_only_accounts':sum(bool(x[2]) for x in objects),
      'accounts_with_positive_recorded_tv_time':sum(x[3] is not None and x[3]>0 for x in objects),
      'accounts_with_multiple_profile_rows':0}
    pq={'saved_rows':len(prows),'returned_rows':len(objects),'explicitly_unreturned_rows':1,
      'unknown_return_status_rows':0,'returned_rows_without_raw_object':0,'normalized_raw_title_disagreements':0}
    directory=root/DIRECTORY_REL;directory.mkdir(parents=True)
    html=directory/'page_0001.html'
    html.write_text('<div class="streamer-list"><article class="streamer paginated">'
      '<a class="overlay" href="/streamer/c5"></a></article></div>')
    registry_hash=hashlib.sha256(json.dumps([['c5','']],separators=(',',':')).encode()).hexdigest()
    directory_info={'pages':[{'file':html.name,'sha256':sha(html)}],'unique_users':1,
       'pagination_completed':True,'started_utc':'2026-09-16','completed_utc':'2026-09-16'}
    (directory/'directory_manifest.json').write_text(json.dumps(directory_info))
    ma={'profile_source_receipts':[{'filename':profile.name,'sha256':sha(profile),'bytes':profile.stat().st_size}],
        'profile_summary':ps,'profile_quality':pq,
        'directory':{'registry_sha256':registry_hash,'directory_accounts':1}}
    known_titles={x[0] for x in objects if x[1]=='FM'}
    known_bots={x[0] for x in objects if x[1]=='BOT'}
    groups={'not_flagged_by_available_sources':{'opportunities':0,'kind_draws':0},
            'positive_audience_proxy':{'opportunities':0,'kind_draws':0}}
    for c,d,y,f,w,ce,de,gid in records:
        if c in known_bots or d in known_bots: continue
        flag=ce>=2400 or de>=2400 or c in known_titles or d in known_titles or c=='c5' or d=='c5'
        target=groups['positive_audience_proxy' if flag else 'not_flagged_by_available_sources']
        target['opportunities']+=1;target['kind_draws']+=y
    ma['original_primary_groups']=groups
    db.close()
    return pa,ma

def explicit_fe(rows):
    states={}
    for uid,y,d in rows:states.setdefault(uid,set()).add(d)
    ids=sorted(k for k,v in states.items() if v=={0,1})
    rows=[r for r in rows if r[0] in ids];index={v:i for i,v in enumerate(ids)}
    N,G=len(rows),len(ids)
    if G<2: return None
    X=np.zeros((N,G+1));y=np.empty(N)
    for n,(uid,yi,d) in enumerate(rows):X[n,index[uid]]=1;X[n,-1]=d;y[n]=yi
    bread=np.linalg.inv(X.T@X);beta=bread@X.T@y;residual=y-X@beta
    scores=np.zeros((G,G+1))
    for n,(uid,_,_) in enumerate(rows):scores[index[uid]]+=X[n]*residual[n]
    cov=bread@scores.T@scores@bread*G/(G-1)*(N-1)/(N-G-1)
    return beta[-1],math.sqrt(cov[-1,-1]),N,G

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.pa,cls.ma=fixture(cls.root)
        cls.cache=cls.root/'private_cache';cls.out=cls.root/'RESULTS_SYNTHETIC'
        with contextlib.redirect_stdout(io.StringIO()):
            cls.payload=execute(cls.root,cls.out,cls.cache,2,2,panel_authority=cls.pa,metadata_authority=cls.ma)
        cls.db=duckdb.connect()
        cache=Path(cls.payload['private_cache_directory'])
        cls.db.execute(f'CREATE VIEW base AS SELECT * FROM read_parquet({qs(cache/"2023-11.parquet")})')

    @classmethod
    def tearDownClass(cls): cls.db.close();cls.tmp.cleanup()

    def test_01_numeric_tv_missing_and_zero_are_separate(self):
        db=self.db
        self.assertEqual(db.execute("SELECT DISTINCT cp,ctv_known,ctv_seconds,ctv FROM base WHERE chooser='c0'").fetchone(),(True,False,None,False))
        self.assertEqual(db.execute("SELECT DISTINCT cp,ctv_known,ctv_seconds,ctv FROM base WHERE chooser='c1'").fetchone(),(True,True,0,False))
        self.assertEqual(db.execute("SELECT DISTINCT cp,ctv_known FROM base WHERE chooser='c3'").fetchone(),(False,False))
        self.assertEqual(db.execute("SELECT DISTINCT ctv_known,ctv_seconds,ctv FROM base WHERE chooser='c2'").fetchone(),(True,7200,True))

    def test_02_both_players_and_nested_exclusions(self):
        mark(self.db,2400)
        rows=self.db.execute('SELECT '+','.join('('+stage_expression(s)+')' for s in STAGES)+' FROM marked').fetchall()
        for a,b,c in rows:
            if a==1:self.assertEqual((b,c),(1,1))
            if b==1:self.assertEqual(c,1)
        for column in ('ct','dt','cs','ds','cl','dl','ctv','dtv'):
            stage='01_elite_title_streamer' if column in ('ct','dt','cs','ds') else '02_add_profile_links' if column in ('cl','dl') else '03_add_recorded_tv'
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM marked WHERE NOT invalid AND {column} AND ({stage_expression(stage)})<>1').fetchone()[0],0)
        self.assertGreater(self.db.execute(f'SELECT count(*) FROM marked WHERE NOT cp AND NOT dp AND ({stage_expression("03_add_recorded_tv")})=0').fetchone()[0],0)

    def test_03_fe_matches_explicit_row_level_dummy_ols(self):
        mark(self.db,2400)
        targets=[r for r in self.payload['estimates'] if r['threshold']==2400 and
          r['metadata_scope']=='all_available_metadata' and r['metric']=='chooser_fe_gradient']
        for r in targets:
            rows=self.db.execute(f'SELECT chooser,y,state FROM marked WHERE state IN (0,1) AND ({stage_expression(r["stage"])})={r["group_code"]}').fetchall()
            expected=explicit_fe(rows)
            if expected is None:continue
            b,se,n,g=expected
            self.assertAlmostEqual(r['estimate']/100,b,places=11)
            self.assertAlmostEqual(r['cluster_se']/100,se,places=11)
            self.assertEqual((r['n'],r['chooser_clusters']),(n,g))
        # The never-granting account c0 is a valid identifying chooser.
        self.assertEqual(self.db.execute("SELECT max(y),count(DISTINCT state) FROM base WHERE chooser='c0' AND state IN (0,1)").fetchone(),(0,2))

    def test_04_raw_contrast_retains_shared_chooser_covariance(self):
        mark(self.db,2400);stage='03_add_recorded_tv';expr=stage_expression(stage)
        r=next(x for x in self.payload['between_flag_groups'] if x['threshold']==2400 and
          x['metadata_scope']=='all_available_metadata' and x['stage']==stage and x['metric']=='raw_gradient')
        rows=self.db.execute(f'SELECT chooser,y,state,{expr} g FROM marked WHERE state IN(0,1)').fetchall()
        scores={};gaps={}
        for g in (0,1):
            a=[x for x in rows if x[3]==g];G=len({x[0] for x in a});N=len(a)
            nf=sum(x[2]==1 for x in a);nw=N-nf
            pf=sum(x[1] for x in a if x[2]==1)/nf;pw=sum(x[1] for x in a if x[2]==0)/nw
            gaps[g]=pf-pw;fac=math.sqrt(G/(G-1)*(N-1)/(N-2))
            for uid,y,d,_ in a:
                z=(y-pf)/nf if d==1 else -(y-pw)/nw
                scores[uid]=scores.get(uid,0)+(1 if g==1 else -1)*fac*z
        self.assertAlmostEqual(r['difference_pp']/100,gaps[1]-gaps[0],places=12)
        self.assertAlmostEqual(r['cluster_se_pp']/100,math.sqrt(sum(x*x for x in scores.values())),places=12)

    def test_05_aggregates_and_export_integrity(self):
        p=self.payload;N=p['sample_qa']['opportunities'];K=p['sample_qa']['kind_draws']
        self.assertEqual(p['original_audience_reproduction'],'exact_counts_reproduced')
        self.assertEqual(sum(r['n'] for r in p['flag_overlap']),N)
        self.assertEqual(sum(r['k'] for r in p['flag_overlap']),K)
        self.assertEqual(sum(r['chooser_accounts'] for r in p['metadata_coverage_by_chooser']),48)
        for line in (self.out/'SHA256SUMS.txt').read_text().splitlines():
            digest,name=line.split('  ',1);self.assertEqual(sha(self.out/name),digest)
        with zipfile.ZipFile(self.out.with_suffix('.zip')) as z:
            self.assertIsNone(z.testzip())
            self.assertFalse(any(name.endswith('.parquet') or name.endswith('.html') for name in z.namelist()))
        text=(self.out/'RESULTS.json').read_text()
        self.assertNotIn('"chooser":',text)
        for name in ('audience_exclusion_robustness.pdf','audience_exclusion_robustness.png'):
            self.assertGreater((self.out/name).stat().st_size,1000)

    def test_06_resume_and_corruption_detection(self):
        cache=Path(self.payload['private_cache_directory']);p=cache/'2023-11.parquet'
        before=(sha(p),p.stat().st_mtime_ns)
        with contextlib.redirect_stdout(io.StringIO()):
            again=execute(self.root,self.root/'RESULTS_RESUMED',self.cache,2,2,
              panel_authority=self.pa,metadata_authority=self.ma)
        self.assertEqual(before,(sha(p),p.stat().st_mtime_ns))
        for a,b in zip(self.payload['summary'],again['summary']):
            self.assertEqual(set(a),set(b))
            for k in a:
                if isinstance(a[k],float): self.assertAlmostEqual(a[k],b[k],places=11)
                else: self.assertEqual(a[k],b[k])
        stamp=cache/'2023-11.json';original=stamp.read_text();bad=json.loads(original);bad['sha256']='0'*64
        stamp.write_text(json.dumps(bad))
        db=duckdb.connect()
        try:
            with self.assertRaises(ValueError):
                build_base(db,[self.root/PANEL_REL/'month=2023-11'/'analysis_panel.parquet'],self.pa['monthly_inputs'],cache)
        finally:stamp.write_text(original);db.close()
        altered=json.loads(json.dumps(self.ma));altered['profile_source_receipts'][0]['sha256']='0'*64
        with self.assertRaises(FileNotFoundError):discover_profiles(self.root,altered)
        html=self.root/DIRECTORY_REL/'page_0001.html';saved=html.read_bytes();html.write_bytes(saved+b'changed')
        db=duckdb.connect()
        try:
            with self.assertRaises(ValueError):load_directory(db,self.root,self.ma)
        finally:html.write_bytes(saved);db.close()

if __name__=='__main__': unittest.main(verbosity=2)
