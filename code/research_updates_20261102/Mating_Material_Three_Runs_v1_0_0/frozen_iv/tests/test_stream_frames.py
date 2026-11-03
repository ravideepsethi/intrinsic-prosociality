import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
import stream_frames as sf
import bounded_frames as bf
import features
from types import SimpleNamespace


class StreamFrameTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def file(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(data if isinstance(data,pa.Table) else pa.table(data),p,row_group_size=7)
        return p
    def oracle(self,sql,views):
        db=connect(self.root/'oracle',1.)
        try:
            for name,paths in views.items():view(db,name,paths)
            return db.execute(sql).fetch_arrow_table()
        finally:db.close()
    def equal(self,path,want):
        got=pq.read_table(path)
        self.assertEqual(got.schema.names,want.schema.names)
        self.assertEqual(got.to_pydict(),want.to_pydict())

    def test_interleaved_shards_exact_original_join_columns_nulls_and_replacements(self):
        ids=np.arange(73,dtype=np.int64)*5+2**42
        q=self.file('q.parquet',dict(row_id=ids,name=[None if i%5==0 else str(i) for i in range(73)],fair_90=np.zeros(73,dtype=np.int64),keep=ids/7))
        parts=[]
        for k in range(16):
            ix=np.arange(73)[np.arange(73)%16==k]
            parts.append(self.file(f'h{k}.parquet',dict(row_id=ids[ix],fair_90=ix.astype(np.int64),y=ix%2==0,outcome_gid=[None if i%3==0 else 'g'+str(i) for i in ix])))
        out=self.root/'out.parquet'
        sf.attach(q,parts,out,batch_rows=11,right_rows=3)
        want=self.oracle('SELECT q.* EXCLUDE(fair_90),h.* EXCLUDE(row_id) FROM q JOIN h USING(row_id) ORDER BY row_id',{'q':q,'h':parts})
        self.equal(out,want)

    def test_large_right_row_groups_are_normalized_without_changing_originals(self):
        ids=np.arange(75,dtype=np.int64)
        q=self.file('q.parquet',dict(row_id=ids,x=ids/17))
        parts=[]
        for k in range(3):
            subset=ids[ids%3==k];p=self.root/f'large{k}.parquet'
            pq.write_table(pa.table(dict(row_id=subset,y=subset/19)),p,row_group_size=100)
            parts.append(p)
        hashes=[sha(p) for p in parts]
        original=sf._attach_prepared
        inspected=[]
        def check(source,prepared,*args):
            for p in prepared:
                pf=pq.ParquetFile(p)
                self.assertTrue(all(pf.metadata.row_group(i).num_rows<=7 for i in range(pf.metadata.num_row_groups)))
                self.assertNotIn(p,parts)
            inspected.extend(prepared)
            return original(source,prepared,*args)
        with patch.object(sf,'MAX_RIGHT_ROW_GROUP_ROWS',7),patch.object(sf,'_attach_prepared',side_effect=check):
            sf.attach(q,parts,self.root/'normalized.parquet',batch_rows=11,right_rows=3)
        self.equal(self.root/'normalized.parquet',self.oracle('SELECT q.*,h.* EXCLUDE(row_id) FROM q JOIN h USING(row_id) ORDER BY row_id',{'q':q,'h':parts}))
        self.assertEqual([sha(p) for p in parts],hashes)
        self.assertTrue(inspected)
        self.assertTrue(all(not p.exists() for p in inspected))
        self.assertEqual(list(self.root.glob('.stream_inputs_*')),[])

    def test_many_shards_share_one_total_row_group_budget(self):
        ids=np.arange(256,dtype=np.int64)
        q=self.file('q.parquet',dict(row_id=ids))
        parts=[self.file(f'p{k}.parquet',dict(row_id=ids[ids%128==k],value=ids[ids%128==k]+7)) for k in range(128)]
        with patch.object(sf,'MAX_TOTAL_RIGHT_ROW_GROUP_ROWS',128):
            info=sf.attach(q,parts,self.root/'many.parquet')
        self.assertEqual(info['max_right_row_group_rows'],1)
        self.assertEqual(info['right_buffer_rows'],1)
        self.assertEqual(pq.read_table(self.root/'many.parquet')['value'].to_pylist(),(ids+7).tolist())

    def test_missing_duplicate_extra_and_unsorted_rows_block_atomic_output(self):
        q=self.file('q.parquet',dict(row_id=[1,3,5],x=[10,20,30]))
        cases=[[1,5],[1,3,3,5],[0,1,3,5],[1,3,5,7],[3,1,5]]
        for k,ids in enumerate(cases):
            h=self.file(f'h{k}.parquet',dict(row_id=ids,y=ids));out=self.root/f'out{k}.parquet'
            with self.subTest(ids=ids),self.assertRaises(RuntimeError):sf.attach(q,[h],out,batch_rows=2,right_rows=2)
            self.assertFalse(out.exists());self.assertFalse(out.with_name(out.name+'.stream_partial').exists())
        h1=self.file('a.parquet',dict(row_id=[1,3],y=[1,3]));h2=self.file('b.parquet',dict(row_id=[3,5],y=[3,5]))
        with self.assertRaises(RuntimeError):sf.attach(q,[h1,h2],self.root/'cross.parquet',batch_rows=2)

    def test_unsorted_left_and_duplicate_at_batch_boundary_rejected(self):
        h=self.file('h.parquet',dict(row_id=[1,2,3],y=[1,2,3]))
        for k,ids in enumerate([[2,1,3],[1,2,2]]):
            q=self.file(f'q{k}.parquet',dict(row_id=ids,x=ids))
            with self.assertRaises(RuntimeError):sf.attach(q,[h],self.root/f'x{k}.parquet',batch_rows=2)

    def test_null_id_and_mismatched_schema_rejected(self):
        q=self.file('q.parquet',dict(row_id=[1,2],x=[1,2]))
        null=self.file('null.parquet',dict(row_id=[1,None],y=[1,2]))
        with self.assertRaises(RuntimeError):sf.attach(q,[null],self.root/'nullout.parquet')
        a=self.file('a.parquet',dict(row_id=[1],y=[1]));b=self.file('b.parquet',dict(row_id=[2],y=['two']))
        with self.assertRaises(RuntimeError):sf.attach(q,[a,b],self.root/'badtypes.parquet')

    def test_empty_typed_frames_and_no_input_overwrite(self):
        q=self.file('q.parquet',pa.table({'row_id':pa.array([],pa.int64()),'x':pa.array([],pa.string())}))
        h=self.file('h.parquet',pa.table({'row_id':pa.array([],pa.int64()),'y':pa.array([],pa.bool_())}))
        sf.attach(q,[h],self.root/'out.parquet')
        self.assertEqual(pq.read_table(self.root/'out.parquet').schema.names,['row_id','x','y'])
        before=sha(q)
        with self.assertRaises(RuntimeError):sf.attach(q,[h],q)
        self.assertEqual(sha(q),before)

    def test_selection_and_anti_selection_exact_gapped_identity(self):
        q=self.file('q.parquet',dict(row_id=[1,3,5,7,9],x=[None,3,5,7,9]))
        ids=self.file('ids.parquet',dict(row_id=[3,9]))
        for invert,sql in [(False,'SELECT q.* FROM q SEMI JOIN ids USING(row_id) ORDER BY row_id'),(True,'SELECT q.* FROM q ANTI JOIN ids USING(row_id) ORDER BY row_id')]:
            out=self.root/f'{invert}.parquet';sf.select(q,out,ids=ids,invert=invert,batch_rows=2)
            self.equal(out,self.oracle(sql,{'q':q,'ids':ids}))
        projected=self.root/'projected.parquet'
        sf.select(q,projected,ids=ids,invert=True,columns=['row_id'],batch_rows=2)
        self.equal(projected,self.oracle('SELECT q.row_id FROM q ANTI JOIN ids USING(row_id) ORDER BY row_id',{'q':q,'ids':ids}))
        bad=self.file('bad.parquet',dict(row_id=[3,8]))
        with self.assertRaises(RuntimeError):sf.select(q,self.root/'badout.parquet',ids=bad,batch_rows=2)

    def test_predicate_retains_sql_null_semantics(self):
        import pyarrow.compute as pc
        q=self.file('q.parquet',dict(row_id=[1,2,3,4],ordinary_narrow=[True,True,None,False],complete90=[True,None,True,True]))
        out=self.root/'o.parquet';sf.select(q,out,predicate=lambda t:pc.and_kleene(t['ordinary_narrow'],t['complete90']),batch_rows=2)
        self.equal(out,self.oracle('SELECT * FROM q WHERE ordinary_narrow AND complete90 ORDER BY row_id',{'q':q}))

    def test_environment_attach_matches_frozen_sql_and_rejects_lost_rows(self):
        q=self.file('q.parquet',dict(row_id=[0,2,4],recipient_id=[7,8,7],opponent_id=[9,9,9],month_code=[0,0,1],name=['a',None,'c']))
        r=self.file('r.parquet',dict(person=[9,9,9],partner=[7,8,7],month_code=[0,0,1],environment_supported=[True,False,True],value=[.4,None,.6]))
        out,_=bf.environment_attach(q,r,self.root/'attach','env',1.)
        want=self.oracle('SELECT q.*,r.* EXCLUDE(person,partner,month_code) FROM q JOIN r ON q.opponent_id=r.person AND q.recipient_id=r.partner AND q.month_code=r.month_code ORDER BY row_id',{'q':q,'r':r})
        self.equal(out/'model.parquet',want)
        bad=self.file('r2.parquet',pq.read_table(r).slice(0,2))
        with self.assertRaises(RuntimeError):bf.environment_attach(q,bad,self.root/'badattach','badenv',1.)

    def fixture(self):
        n=30;ids=np.arange(n,dtype=np.int64);ix=ids[ids%3==0]
        end=int(c.phase_inputs.core.PANEL_END)
        q=self.file('source.parquet',dict(row_id=ids,game_id=['g'+str(i) for i in ids],recipient_id=ids+10,opponent_id=ids+100,
            status=['timeout' if i%3==0 else 'mate' for i in ids],active_timeout=ids%3==0,anchor_ms=end-90*DAY-(ids%2),
            ordinary_narrow=ids%3!=0,eligible_main=[True]*n,first_observed_pair=[True]*n,tc_base_s=[300]*n,history_window_complete=[True]*n))
        roles=self.file('roles.parquet',dict(row_id=ix,i=ix+10,j=ix+100,fair_competitive=[True]*len(ix),kind_draw=ix%2==0,timeout_chooser_win=ix%2!=0))
        raw=self.file('raw.parquet',dict(row_id=ix,game_id=['g'+str(i) for i in ix],recipient_id=ix+10))
        flags=self.file('flags.parquet',dict(row_id=ix,supported=[True]*len(ix),uniform_keep=ix%2!=0))
        scids=np.arange(-2,n+2,dtype=np.int64)
        scores=self.file('scores.parquet',dict(row_id=scids,n_A=[5]*len(scids),adjusted_A=scids/100,expected_A=[.02]*len(scids)))
        return q,roles,raw,flags,scores

    def test_comparison_labels_and_final_frames_match_original_sql(self):
        q,roles,raw,flags,scores=self.fixture();tmp=self.root/'labeled';tmp.mkdir()
        bf.label_frame(tmp,q,[roles],raw,flags,1.)
        sql=f'''SELECT q.*,coalesce(q.recipient_id=m.i,FALSE) recipient_disconnect_main,
            coalesce(q.recipient_id=m.i AND m.fair_competitive AND (m.kind_draw OR m.timeout_chooser_win),FALSE) recipient_fair_arm_main,
            coalesce(s.supported,FALSE) supported_receipt_entry,coalesce(s.uniform_keep,FALSE) analysis_entry_uniform90,
            q.anchor_ms+{90*DAY}<{int(c.phase_inputs.core.PANEL_END)} complete90
            FROM q LEFT JOIN m USING(row_id) LEFT JOIN (SELECT raw.game_id,raw.recipient_id,flags.supported,flags.uniform_keep FROM raw JOIN flags USING(row_id)) s
            ON q.game_id=s.game_id AND q.recipient_id=s.recipient_id ORDER BY q.row_id'''
        self.equal(tmp/'model.parquet',self.oracle(sql,{'q':q,'m':roles,'raw':raw,'flags':flags}))
        target=self.root/'finished';target.mkdir();bf.finish_frames(target,tmp/'model.parquet',scores,1.)
        for tag,where in [('F','TRUE'),('O','ordinary_narrow AND complete90')]:
            self.equal(target/(tag+'.parquet'),self.oracle('SELECT * FROM q WHERE '+where+' ORDER BY row_id',{'q':tmp/'model.parquet'}))
            self.equal(target/(tag+'_scores.parquet'),self.oracle('SELECT s.* FROM s JOIN q USING(row_id) WHERE '+where+' ORDER BY row_id',{'q':tmp/'model.parquet','s':scores}))

    def test_reuses_all_saved_history_shards_and_detects_changed_input(self):
        run=self.root/'run';(run/'report').mkdir(parents=True)
        n=32;ids=np.arange(n,dtype=np.int64);start=int(c.phase_inputs.core.STARTS[5])
        q=self.file('q.parquet',dict(row_id=ids,recipient_id=ids,opponent_id=ids+100,game_id=['g'+str(i) for i in ids],archive_start_ms=[start]*n,anchor_ms=[start+10]*n))
        prep=run/'PRIVATE/behavior_queries90'
        def prepare(tmp):
            table=pq.read_table(q)
            for k in range(16):pq.write_table(table.filter(pa.array(ids%16==k)),tmp/f'outcome_{k:02}.parquet')
            return dict(rows=n)
        stage(prep,'reuse',prepare,[q]);jobs=[]
        for k in range(16):
            output=run/'PRIVATE/behavior90/outcomes'/f'{k:02}';subset=ids[ids%16==k]
            def producer(tmp,subset=subset):
                table=pa.table(dict(row_id=subset,history_window_complete=[True]*len(subset),y=[False]*len(subset),reached=[False]*len(subset),outcome_t=np.zeros(len(subset),np.int64),outcome_start=np.zeros(len(subset),np.int64),outcome_opponent=np.full(len(subset),-1,np.int64),outcome_gid=['']*len(subset)))
                pq.write_table(table,tmp/'outcomes.parquet');return dict(rows=len(subset))
            stage(output,'reuse',producer,[prep/f'outcome_{k:02}.parquet'])
            jobs.append(dict(output=str(output)))
        hashes=[sha(Path(j['output'])/'outcomes.parquet') for j in jobs]
        def reuse_worker(fn,actual,workers,label):
            for job in actual:c.check_stage(Path(job['output'])/'outcomes.parquet','reuse')
        with patch.object(c.inputs,'outcome_jobs',return_value=jobs),patch.object(c,'mapped',side_effect=reuse_worker):
            out=features.behavior(SimpleNamespace(workers=2,memory_gb=4.),run,'reuse',{},q)
            self.assertEqual(rows(out),n)
            self.assertEqual([sha(Path(j['output'])/'outcomes.parquet') for j in jobs],hashes)
            again=features.behavior(SimpleNamespace(workers=2,memory_gb=4.),run,'reuse',{},q)
            self.assertEqual(sha(out),sha(again))
            with (Path(jobs[0]['output'])/'outcomes.parquet').open('ab') as handle:handle.write(b'changed')
            with self.assertRaises(RuntimeError):features.behavior(SimpleNamespace(workers=2,memory_gb=4.),run,'reuse',{},q)

    def test_saved_frame_gate_requires_metadata_and_all_16_history_outputs(self):
        import resume_guard
        run=self.root/'gate';cr=run/'comparisons';conf='gate'
        def meta(tmp):
            for name in ('queries','metadata','dispositions'):
                pq.write_table(pa.table(dict(row_id=np.arange(16,dtype=np.int64))),tmp/(name+'.parquet'))
        stage(cr/'PRIVATE/metadata_complete',conf,meta)
        save(cr/'report/METADATA_HOLD_RESOLUTION.json',dict(status='RESOLVED',configuration=conf,new_unresolved_rows=0))
        def queries(tmp):
            for k in range(16):pq.write_table(pa.table(dict(row_id=[k])),tmp/f'outcome_{k:02}.parquet')
        stage(cr/'PRIVATE/behavior_queries90',conf,queries)
        for k in range(16):
            stage(cr/'PRIVATE/behavior90/outcomes'/f'{k:02}',conf,
                  lambda tmp,k=k:pq.write_table(pa.table(dict(row_id=[k])),tmp/'outcomes.parquet'))
        for rel,name in [('behavior_combined90','features'),('factual_volume_90/combined','source')]:
            stage(cr/'PRIVATE'/rel,conf,lambda tmp,name=name:pq.write_table(pa.table(dict(row_id=np.arange(16))),tmp/(name+'.parquet')))
        def volume(tmp):
            pq.write_table(pa.table(dict(row_id=np.arange(15))),tmp/'known.parquet')
            pq.write_table(pa.table(dict(row_id=[15])),tmp/'missing.parquet')
        stage(cr/'PRIVATE/factual_volume_90/plan',conf,volume)
        for k in range(24):
            stage(cr/'PRIVATE/roles'/f'{k:02}',conf,lambda tmp:pq.write_table(pa.table(dict(row_id=[0])),tmp/'roles.parquet'))
        def labels(tmp):
            pq.write_table(pa.table(dict(row_id=np.arange(16))),tmp/'model.parquet')
            save(tmp/'counts.json',dict(entry=4))
        stage(cr/'PRIVATE/labeled90',conf,labels)
        authority=self.root/'authority/iv_batch_partial'
        save(authority/'VOLUME_90_V105.json',dict(reused=15,missing=1,total=16))
        save(authority/'ENTRY_LABEL_COUNTS_V105.json',dict(entry=4))
        with patch.object(resume_guard,'ROOT',self.root):
            resume_guard.validate_saved_frames(run,conf)
            (cr/'PRIVATE/behavior90/outcomes/15/outcomes.parquet').unlink()
            with self.assertRaises(Exception):resume_guard.validate_saved_frames(run,conf)


if __name__=='__main__':unittest.main()
