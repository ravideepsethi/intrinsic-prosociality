"""Synthetic/oracle tests. These do not certify the unmounted production data."""
from __future__ import annotations
import contextlib,io,json,sqlite3,sys,tempfile,unittest,zipfile
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT/'vendor'),str(ROOT/'tests/original')]
from common import *
from history_logic import *
from project_history import build_month,identity_check
from references import build_references
import comparison_checkpoint as checkpoint
import run_iv_pilot as oracle
import sources
import run

def feature_table(month='2023-11',n=80):
    start=int(dt.datetime.fromisoformat(month+'-01').replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    k=np.arange(n,dtype=np.int64);j=k%20+1;i=k%23+100
    return pa.table(dict(game_id=[month+f'g{x:07d}' for x in k],utc_ms=start+k*1000,
        anchor_ms=start+k*1000+800,archive_ordinal=k,chooser_user_id=j,disconnected_user_id=i,
        chooser=[f'user{x}' for x in j],opponent=[f'user{x}' for x in i],
        color=['white' if x%2 else 'black' for x in k],speed=[SPEEDS[x%5] for x in k],
        rating=np.full(n,1500.),opp_rating=1500.+(k%7-3)*100,
        grant=(k%3==0).astype(float),timeout_chooser_win=k%3==1,
        cp=np.resize(np.array([-500.,-300.,-101.,-100.,0.,100.,299.,300.]),n),
        ply=(k%80).astype(float),tc_base_s=np.full(n,300.),tc_inc_s=np.full(n,3.),
        tournament_like_event=k%11==0))

def original_source(t):
    fields={'chooser_user_id':'chooser_user_id','disconnected_user_id':'disconnected_user_id',
        'api_last_move_at_ms':'anchor_ms','utc_ms':'utc_ms','archive_ordinal':'archive_ordinal',
        'game_id':'game_id','kind_draw':'grant','timeout_chooser_win':'timeout_chooser_win',
        'tc_base_s':'tc_base_s','tc_inc_s':'tc_inc_s','api_speed':'speed',
        'engine_eval_cp_disconnected':'cp','ply_count':'ply','chooser_elo':'rating','disconnected_elo':'opp_rating'}
    data={a:t[b] for a,b in fields.items()};data['kind_draw']=pa.array(arr(t,'grant',bool))
    data['fair_competitive']=pa.array(np.isfinite(arr(t,'cp'))&(arr(t,'cp')>=-100))
    return pa.table(data)

def write_fixture(root,month='2023-11',n=80,bridge=False,october=False):
    root.mkdir(parents=True,exist_ok=True);t=feature_table(month,n)
    base=t.select(['game_id','utc_ms','chooser','opponent','color','speed','rating','opp_rating','grant','cp','ply'])
    pq.write_table(base,root/'base.parquet')
    pq.write_table(pa.table(dict(game_id=t['game_id'],start_ms=t['utc_ms'],anchor_ms=t['anchor_ms'],
        valid_timing=np.ones(n,bool),competitive=arr(t,'cp')>=-100)),root/'anchors.parquet')
    s=original_source(t).append_column('outcome_kind_draw',t['grant']).append_column('tournament_like_event',t['tournament_like_event'])
    if october:
        s=s.drop(['timeout_chooser_win'])
        colors=t['color'].to_pylist();win=arr(t,'timeout_chooser_win');draw=~win
        s=s.append_column('api_status',pa.array(['timeout']*n)).append_column('api_draw',pa.array(draw))
        s=s.append_column('api_winner',pa.array([colors[k] if win[k] else None for k in range(n)],type=pa.string()))
        s=s.append_column('candidate_chooser_color_norm',t['color'])
    pq.write_table(s,root/'source.parquet')
    sourcepaths=[str(root/'source.parquet')]
    identity=[]
    if not bridge:
        white=np.array(t['color'].to_pylist())=='white'
        canonical=pa.table(dict(game_id=t['game_id'],utc_ms=t['utc_ms'],archive_ordinal=t['archive_ordinal'],
            white_id=np.where(white,arr(t,'chooser_user_id'),arr(t,'disconnected_user_id')),
            black_id=np.where(white,arr(t,'disconnected_user_id'),arr(t,'chooser_user_id')),
            white_elo=np.where(white,arr(t,'rating'),arr(t,'opp_rating')),
            black_elo=np.where(white,arr(t,'opp_rating'),arr(t,'rating'))))
        for speed in SPEEDS:
            q=root/(speed+'.parquet');p=canonical.filter(pa.array(np.array(t['speed'].to_pylist())==speed));pq.write_table(p,q)
            identity.append(dict(path=str(q),speed=speed,rows=len(p),mode='synthetic'))
    paths=[root/'base.parquet',root/'anchors.parquet',root/'source.parquet']+[Path(x['path']) for x in identity]
    inputs=[dict(**receipt(p),fingerprint=stamp(p)) for p in paths]
    job=dict(month=month,base=str(root/'base.parquet'),anchor_paths=[str(root/'anchors.parquet')],
        source_paths=sourcepaths,identity=identity,inputs=inputs,expected_rows=n,bridge=bridge,
        arm_adapter='october_api_winner' if october else 'stored_timeout_chooser_win',
        work=str(root/'work'),auth_root=str(root/'auth'),memory_mb=256,n_users=10000,code_sha='synthetic')
    return t,job

def refresh(job):
    job['inputs']=[dict(**receipt(r['path']),fingerprint=stamp(r['path'])) for r in job['inputs']]

def original_project(root,t):
    src=root/'oracle_input.parquet';pq.write_table(original_source(t),src)
    q=root/'cohort.parquet';pq.write_table(pa.table(dict(pilot_row=[0],recipient_id=[1],archive_start_ms=[int(STARTS[-1])])),q)
    out=root/'oracle_output'
    done=oracle.project_month(dict(path=str(src),cohort=str(q),output=str(out),shards=16,config_hash='synthetic',input_sha256=sha(src)))
    return out,done

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='iv_extension_test_');self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_original_projection_and_delta_oracle(self):
        t=feature_table(n=400)
        # Match original treatment of unavailable merit, ply, gap and correspondence.
        d=t.to_pydict();d['cp'][0]=None;d['ply'][1]=None;d['rating'][2]=None
        d['speed'][3]='correspondence';d['tc_base_s'][4]=0;t=pa.table(d)
        out,_=original_project(self.root,t);actual,shards=project_batch(t)
        for shard in range(16):
            expected=pq.ParquetFile(out/f'shard-{shard:02d}.parquet').read()
            self.assertTrue(actual.take(pa.array(np.flatnonzero(shards==shard))).equals(expected))
        n,s=empty_deltas(oracle.STARTS);add_deltas(n,s,actual,oracle.STARTS)
        with np.load(out/'reference_deltas.npz') as z:
            np.testing.assert_array_equal(n,z['n']);np.testing.assert_array_equal(s,z['s'])

    def test_required_null_and_bad_arms_rejected(self):
        for col,value in [('chooser_user_id',None),('anchor_ms',None),('grant',2.)]:
            d=feature_table(n=8).to_pydict();d[col][0]=value
            with self.assertRaises(RuntimeError):project_batch(pa.table(d))
        d=feature_table(n=8).to_pydict();d['timeout_chooser_win'][0]=True
        with self.assertRaises(RuntimeError):project_batch(pa.table(d))

    def test_strict_cutoff_and_both_role_folds(self):
        t=feature_table(n=3);d=t.to_pydict()
        cutoff=int(STARTS[5]-7*DAY)
        d['anchor_ms']=[cutoff-1,cutoff,cutoff+1];d['utc_ms']=[cutoff-5]*3
        d['grant']=[1.,0.,1.];d['timeout_chooser_win']=[False,True,False]
        h,_=project_batch(pa.table(d));n,s=empty_deltas();add_deltas(n,s,h)
        self.assertEqual(n[0,:6].sum(),1);self.assertEqual(n[0,6].sum(),2)
        z=np.zeros((2,2,4,4,500),np.int64);w=z.copy()
        z[0,0,0,2,0]=10;w[0,0,0,2,0]=10
        z[0,0,2,1,0]=10;w[0,0,2,1,0]=10
        z[0,0,2,3,0]=10
        model=num.expanding_reference(z,w)
        self.assertAlmostEqual(model[0,0,0,1,0],(50*(.5/11))/60)

    def test_month_build_old_bridge_exact_and_restart(self):
        t,j=write_fixture(self.root,bridge=True)
        r=build_month(j);out,_=original_project(self.root,t)
        c=connection(self.root/'spill',1,256)
        try:assert_same_projection(c,[Path(r['root'])/f'shard-{x:02d}.parquet' for x in range(16)],[out/f'shard-{x:02d}.parquet' for x in range(16)])
        finally:c.close()
        first=receipt(Path(r['root'])/'_DONE.json');r2=build_month(j)
        self.assertEqual(first,r2['receipt'])

    def test_added_month_roles_and_unknown_source_preserved(self):
        t,j=write_fixture(self.root,month='2026-01')
        s=pq.ParquetFile(j['source_paths'][0]).read().append_column('source',pa.array(['pool']*len(t)))
        pq.write_table(s,j['source_paths'][0]);refresh(j)
        r=build_month(j);f=pq.ParquetFile(Path(r['root'])/'opportunities_PRIVATE.parquet').read()
        for name in ['explicit_source_label','extended_pool_nonadjacent_eligible','final_iv_eligible']:
            self.assertEqual(f[name].null_count,len(t))
        np.testing.assert_array_equal(arr(f.sort_by('archive_ordinal'),'chooser_user_id'),arr(t,'chooser_user_id'))

    def test_shared_historical_source_semijoin(self):
        t,j=write_fixture(self.root,month='2025-11')
        src=pq.ParquetFile(j['source_paths'][0]).read();extra=src.slice(0,1).set_column(src.schema.get_field_index('game_id'),'game_id',pa.array(['different_month']))
        pq.write_table(pa.concat_tables([src,extra]),j['source_paths'][0]);refresh(j)
        self.assertEqual(build_month(j)['result']['rows'],len(t))

    def test_october_api_winner_adapter(self):
        t,j=write_fixture(self.root,month='2023-10',october=True)
        r=build_month(j);f=pq.ParquetFile(Path(r['root'])/'opportunities_PRIVATE.parquet').read().sort_by('archive_ordinal')
        np.testing.assert_array_equal(arr(f,'timeout_chooser_win'),arr(t,'timeout_chooser_win'))
        self.assertTrue(np.any((arr(f,'grant')==0)&~arr(f,'timeout_chooser_win')))

    def test_canonical_conflict_rejected(self):
        _,j=write_fixture(self.root,month='2026-01');p=Path(j['identity'][0]['path']);k=pq.ParquetFile(p).read().to_pydict();k['utc_ms'][0]+=1;pq.write_table(pa.table(k),p);refresh(j)
        with self.assertRaisesRegex(RuntimeError,'canonical role'):build_month(j)

    def test_duplicate_game_rejected(self):
        _,j=write_fixture(self.root,month='2026-01');p=Path(j['source_paths'][0]);t=pq.ParquetFile(p).read();pq.write_table(pa.concat_tables([t,t.slice(0,1)]),p);refresh(j)
        with self.assertRaisesRegex(RuntimeError,'nonunique'):build_month(j)

    def test_explicit_labels_conflict_rejected(self):
        _,j=write_fixture(self.root,month='2026-01');p=Path(j['source_paths'][0]);t=pq.ParquetFile(p).read();t=t.append_column('api_source',pa.array(['pool']*len(t))).append_column('lookup_source',pa.array(['friend']*len(t)));pq.write_table(t,p);refresh(j)
        with self.assertRaisesRegex(RuntimeError,'Conflicting'):build_month(j)

    def test_observed_binding_and_stage_tampering(self):
        p=self.root/'bytes';p.write_bytes(b'original');a=observed_binding(p,self.root/'auth');self.assertEqual(a,observed_binding(p,self.root/'auth'))
        p.write_bytes(b'changed!')
        with self.assertRaises(RuntimeError):observed_binding(p,self.root/'auth')
        _,j=write_fixture(self.root/'month',month='2026-01');r=build_month(j)
        q=Path(r['root'])/'shard-00.parquet';q.write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError):build_month(j)

    def test_identity_collision_rejected(self):
        records=[]
        for k,uid in enumerate([1,2]):
            root=self.root/str(k);root.mkdir();pq.write_table(pa.table(dict(username=['same'],user_id=[uid])),root/'identity_pairs_PRIVATE.parquet')
            write_json(root/'_DONE.json',dict(k=k));records.append(dict(root=str(root),receipt=receipt(root/'_DONE.json')))
        with self.assertRaisesRegex(RuntimeError,'namespace'):identity_check(records,self.root/'work',self.root/'auth',1,256,'test')

    def test_complete_extended_reference_pipeline_and_bridge(self):
        nrow=16;old=[];oldtables=[];results=[]
        for month in OLD_MONTHS:
            t=feature_table(month,nrow);oldtables.append(t);h,sh=project_batch(t);folder=self.root/month;folder.mkdir()
            for shard in range(16):
                p=folder/f'shard-{shard:02d}.parquet';pq.write_table(h.take(pa.array(np.flatnonzero(sh==shard))),p)
                old.append(dict(month=month,shard=shard,**receipt(p)))
        o,_=original_project(self.root,pa.concat_tables(oldtables));p=o/'reference_deltas.npz';deltas=[dict(**receipt(p),fingerprint=stamp(p))]
        for month in NEW_MONTHS:
            _,j=write_fixture(self.root/month,month,nrow);results.append(build_month(j))
        root,r=build_references(old,results,deltas,self.root/'ref',self.root/'auth','test',expected_total=32*nrow)
        self.assertEqual(r['result']['rows'],32*nrow);self.assertTrue(r['result']['bridge']['counts_equal'])
        oldmod=np.load(root/'reference_old_boundary.npy');extended=np.load(root/'reference_extended_boundary.npy')
        self.assertEqual(oldmod.shape,(2,32,4,4,500));self.assertTrue(np.isnan(oldmod[:,2]).all())
        self.assertTrue(np.isfinite(extended[:,2]).any())
        manifest=load(root/'HISTORY_INPUT_MANIFEST_PRIVATE.json');self.assertEqual(len(manifest['records']),512)
        self.assertIsNone(manifest['final_iv_eligible_n'])
        table([x['result'] for x in results],self.root/'aggregate_counts')
        self.assertEqual(pq.ParquetFile(self.root/'aggregate_counts.parquet').metadata.num_rows,8)
        bad=np.zeros((2,33,4,4,500),np.int64);pilot=np.zeros((2,25,4,4,500),np.int64);bad[0,2,0,0,0]=1
        with self.assertRaisesRegex(RuntimeError,'counts changed'):assert_reference_bridge(bad,bad,pilot,pilot)

    def test_checkpoint_is_read_only_and_not_certified(self):
        absent=checkpoint.inspect(self.root);self.assertFalse(absent['download_completion_certified'])
        root=self.root/checkpoint.STEM;inp=root/'inputs';inp.mkdir(parents=True)
        write_json(inp/'TRANSFER.json',dict(config_sha256=checkpoint.CONFIG,target_rows=300))
        write_json(inp/'DESIGN_FREEZE.json',dict(config_sha256=checkpoint.CONFIG))
        files=[dict(path=n,sha256=sha(inp/n)) for n in ['TRANSFER.json','DESIGN_FREEZE.json']]
        files.append(dict(path='targets.parquet',sha256='synthetic'))
        write_json(inp/'INPUT_MANIFEST.json',dict(config_sha256=checkpoint.CONFIG,files=files))
        p=root/'checkpoint.sqlite3'
        with sqlite3.connect(p) as db:
            db.executescript('CREATE TABLE meta(key TEXT,value TEXT); CREATE TABLE responses(batch INTEGER,pass INTEGER); CREATE TABLE batches(batch INTEGER,requested INTEGER,returned INTEGER,flagged INTEGER);')
            db.executemany('INSERT INTO meta VALUES (?,?)',[('config_sha256',checkpoint.CONFIG),('target_sha256','synthetic')])
            db.execute('INSERT INTO batches VALUES(0,300,298,0)');db.execute('INSERT INTO responses VALUES(0,0)')
        before=sha(p);r=checkpoint.inspect(self.root);self.assertEqual(sha(p),before)
        self.assertTrue(r['all_target_count_accounted']);self.assertFalse(r['download_completion_certified'])

    def test_public_return_whitelist(self):
        r=self.root/'REPORT';r.mkdir();write_json(r/'SUMMARY.json',dict(rows=50,new_effect=None))
        write_json(r/'identities_PRIVATE.json',dict(fake_id=1))
        with self.assertRaisesRegex(RuntimeError,'Unexpected file'):run.make_zip(r,self.root)
        (r/'identities_PRIVATE.json').unlink();z=run.make_zip(r,self.root)
        with zipfile.ZipFile(z) as f:self.assertEqual(set(f.namelist()),{'REPORT/SUMMARY.json','REPORT/RESULT_MANIFEST.json'})

    def test_frozen_asset_columns_cover_adapters(self):
        a=load(ROOT/'authority/history_feature_sources.json')
        for r in a:
            required={'game_id','outcome_kind_draw','tc_base_s','tc_inc_s','tournament_like_event'}
            required|=({'api_status','api_draw','api_winner','candidate_chooser_color_norm'} if r['month']=='2023-10' else {'timeout_chooser_win'})
            self.assertTrue(required<=set(r['columns']))
        self.assertEqual(len(load(ROOT/'authority/chronology_metadata.json')),25)

    def test_exact_finalized_cache_resolution_no_rerun(self):
        project=self.root/'project';authority=self.root/'authority';auth=self.root/'auth'
        month='2025-11';oldroot=project/sources.CACHE/'monthly'/month/'old_key';oldroot.mkdir(parents=True)
        oldfile=oldroot/'anchors_PRIVATE.parquet';pq.write_table(pa.table({'game_id':['synthetic']}),oldfile)
        oldname=str(ORIGINAL_PROJECT/oldfile.relative_to(project))
        oldentry=receipt(oldfile);oldentry['path']=oldname
        monthly=dict(anchor_files=[oldname],coverage=dict(month=month,opportunity_n=1))
        write_json(oldroot/'complete.json',dict(key='old_key',result=monthly,artifacts=[oldentry]))
        diagfile=project/'diagnostic.parquet';pq.write_table(pa.table({'game_id':['synthetic']}),diagfile)
        diagnostic=dict(kind='timing',month=month,private=dict(path=str(ORIGINAL_PROJECT/'diagnostic.parquet')))
        write_json(authority/'monthly_reuse.json',[dict(month=month,key='old_key',complete_sha256=sha(oldroot/'complete.json'))])
        write_json(authority/'diagnostic_reuse.json',[diagnostic]);write_json(authority/'pins.json',dict(v103_code_signature='pinned_code'))
        audit=dict(month=month,rows=1,restored_end_proxy_n=1)
        write_json(authority/'timing'/month/'timestamp_finalization.json',audit)
        inputs=[stamp(oldfile),stamp(diagfile)]
        key=hashlib.sha256(json.dumps(dict(code='pinned_code',diagnostic=diagnostic,monthly=monthly,inputs=inputs),sort_keys=True,default=str).encode()).hexdigest()
        final=project/sources.CACHE/'cached_finalizer_v103/timing'/month/key;final.mkdir(parents=True)
        ap=final/'anchors_PRIVATE.parquet';pq.write_table(pa.table({'game_id':['corrected']}),ap)
        e=receipt(ap);e['path']=str(ORIGINAL_PROJECT/ap.relative_to(project))
        write_json(final/'timestamp_finalization.json',audit)
        write_json(final/'complete.json',dict(key=key,inputs=inputs,result=dict(audit=audit,monthly=dict(anchor_files=[e['path']])),
            artifacts=[e],public_files=[dict(name='timestamp_finalization.json',sha256=sha(final/'timestamp_finalization.json'))]))
        with patch.object(sources,'AUTH',authority):
            paths,snapshots=sources.anchors(project,month,auth)
            self.assertEqual(paths,[str(ap)]);unchanged(snapshots)
            ap.write_bytes(b'corrupt')
            with self.assertRaises(RuntimeError):sources.anchors(project,month,auth)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if '--record' in sys.argv:
        write_json(ROOT/'VALIDATION.json',dict(scope='Synthetic and original-producer oracle tests; production Mac inputs not executed here',
            tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),passed=result.wasSuccessful(),
            python=sys.version.split()[0],duckdb=duckdb.__version__,numpy=np.__version__,pyarrow=pa.__version__,
            original_numerics_sha256=sha(ROOT/'vendor/iv_numerics.py'),original_projector_sha256=sha(ROOT/'tests/original/run_iv_pilot.py')))
    raise SystemExit(0 if result.wasSuccessful() else 1)
