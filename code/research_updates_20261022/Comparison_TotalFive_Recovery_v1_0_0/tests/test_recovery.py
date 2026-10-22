import unittest,tempfile,json,sys,types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import metadata_worker as m
import download_worker as d
import recovery_util as u
pa,pq=m.pa,m.pq

def meta(gid,**kw):
    r={f.name:None for f in m.ex.metadata_schema()}
    r.update(game_id=gid,source='pool',status='mate',api_start_ms=1700000000000,anchor_ms=1700000010000,rated=True,variant='standard',speed='blitz',winner='white',tc_base_s=180,tc_inc_s=0,white_username='alice',black_username='bob',white_rating=1500.,black_rating=1600.,record_errors='')
    r.update(kw);return r
def cached(path,rows):
    schema=pa.schema([f for f in m.ex.metadata_schema() if f.name!='record_errors']+[pa.field('cached_conflict_or_prior_flag',pa.bool_())])
    records=[]
    for r in rows:
        r=dict(r);flag=bool(r.pop('record_errors',''));r['cached_conflict_or_prior_flag']=flag;records.append(r)
    pq.write_table(pa.Table.from_pylist(records,schema=schema),path)
def api(gid):
    return dict(id=gid,source='pool',status='mate',createdAt=1700000000000,lastMoveAt=1700000010000,rated=True,variant='standard',speed='blitz',winner='white',clock=dict(initial=180,increment=0),players=dict(white=dict(user=dict(id='alice',name='Alice'),rating=1500),black=dict(user=dict(id='bob',name='Bob'),rating=1600)))

class RecoveryTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def conn(self):return m.io.conn(self.root/'spill',.2,1)
    def test_fieldwise_cache_merge_retains_conflicts(self):
        a=self.root/'a.parquet';b=self.root/'b.parquet'
        cached(a,[meta('Abcd0001',white_rating=None),meta('Abcd0002'),meta('Abcd0003',record_errors='prior')])
        cached(b,[meta('Abcd0001'),meta('Abcd0002',source='lobby'),meta('Abcd0003')])
        c=self.conn()
        try:
            r=c.execute(m.merge_sql(['SELECT * FROM '+m.io.parq([a]),'SELECT * FROM '+m.io.parq([b])])+' ORDER BY game_id').to_arrow_table().to_pylist()
            self.assertEqual(r[0]['white_rating'],1500);self.assertFalse(r[0]['cached_conflict_or_prior_flag'])
            self.assertIsNone(r[1]['source']);self.assertTrue(r[1]['cached_conflict_or_prior_flag']);self.assertTrue(r[2]['cached_conflict_or_prior_flag'])
        finally:c.close()
    def test_legacy_membership_no_longer_bypasses_metadata(self):
        a=self.root/'m.parquet';cached(a,[meta('Abcd0001')])
        c=self.conn()
        try:
            c.execute("CREATE VIEW f AS SELECT 'Abcd0001' game_id,TRUE previous_frame,1700000000000::BIGINT utc_ms,'blitz' speed_partition UNION ALL SELECT 'Abcd0002',TRUE,1700000000000,'blitz'")
            c.execute('CREATE VIEW m AS SELECT * FROM '+m.io.parq([a]))
            rows=c.execute('SELECT f.game_id,'+m.readiness()+' status FROM f LEFT JOIN m USING(game_id) ORDER BY 1').fetchall()
            self.assertEqual(rows,[('Abcd0001','CACHED_POOL_METADATA'),('Abcd0002','NO_CACHE')])
        finally:c.close()
    def test_month_cache_recovery_and_quarantine_are_explicit(self):
        source=self.root/'candidates.parquet';legacy=self.root/'legacy.parquet';cache=self.root/'cache.parquet';quarantine=self.root/'quarantine.parquet'
        pq.write_table(pa.table(dict(row_id=[1,2,3],game_id=['Abcd0001','Abcd0002','Abcd0003'],month=['2023-11']*3,utc_ms=[1700000000000]*3,speed_partition=['blitz']*3,previous_frame=[True,False,False],finite_A=[True]*3,at_risk_90=[True]*3,calendar_support=[True]*3)),source)
        pq.write_table(pa.Table.from_pylist([meta('Abcd0001')],schema=m.ex.metadata_schema()),legacy)
        cached(cache,[meta('Abcd0002',source='lobby')]);pq.write_table(pa.table(dict(game_id=['Abcd0003'])),quarantine)
        a=types.SimpleNamespace(conf='x',memory_gb=2.2)
        out,_=m.cache_month(a,'2023-11',source,legacy,[('cached',str(cache))],quarantine,self.root/'month')
        r={r['game_id']:r for r in pq.read_table(out/'dispositions.parquet').to_pylist()}
        self.assertEqual(r['Abcd0001']['metadata_status'],'CACHED_POOL_METADATA');self.assertTrue(r['Abcd0001']['previous_frame'])
        self.assertEqual(r['Abcd0002']['metadata_status'],'CACHED_NONPOOL');self.assertTrue(r['Abcd0003']['certified_quarantine'])
    def test_cooldown_boundary_and_pre_window_stream(self):
        start=1700000000000;anchor=start+1000
        risk=m.RiskIndex({'recipient_id':[1],'archive_start_ms':[start],'anchor_ms':[anchor]})
        r=risk.query({'recipient_id':[1,1,1,2], 'archive_start_ms':[anchor+90*m.DAY,anchor+90*m.DAY+1,anchor,anchor+100]})
        self.assertEqual(r['at_risk'].tolist(),[False,True,True,True]);self.assertTrue(r['anchor_tie'][2])
    def test_download_resume_only_retries_nonreturns(self):
        class Client:
            def __init__(self):self.calls=[]
            def get(self,ids):
                self.calls.append(ids);return ('\n'.join(json.dumps(api(g)) for g in ids if g=='Abcd0001')).encode()
        client=Client();rows=[dict(game_id=g,utc_ms=1700000000000,speed_partition='blitz') for g in ('Abcd0001','Abcd0002')]
        db=d.dl.connect(self.root/'db.sqlite3','conf','sha')
        try:
            nr,nm,flags,reused=d.dl.process_batch(db,0,rows,client)
            self.assertEqual(len(nr),1);self.assertEqual(nm,[dict(game_id='Abcd0002')]);self.assertFalse(reused);self.assertEqual(flags,0)
            self.assertEqual(client.calls,[['Abcd0001','Abcd0002'],['Abcd0002'],['Abcd0002']])
            d.dl.process_batch(db,0,rows,None);self.assertEqual(len(client.calls),3)
            with self.assertRaisesRegex(RuntimeError,'identity changed'):d.dl.process_batch(db,0,list(reversed(rows)),None)
        finally:db.close()
    def test_request_commit_survives_interruption(self):
        class Client:
            def get(self,ids):return json.dumps(api(ids[0])).encode()
        ids=['Abcd0001'];db=d.dl.connect(self.root/'db.sqlite3','conf','sha')
        try:
            d.dl.response(db,0,0,ids,Client())
            rows=[dict(game_id=ids[0],utc_ms=1700000000000,speed_partition='blitz')]
            class NoRequest:
                def get(self,ids):raise AssertionError('Committed request resent')
            d.dl.process_batch(db,0,rows,NoRequest())
        finally:db.close()
    def test_retry_and_invalid_response_contract(self):
        self.assertGreaterEqual(d.http.delay(429,{},0,0),60)
        self.assertEqual(d.http.delay(429,{'Retry-After':'180'},0,0),180)
        with self.assertRaises(RuntimeError):d.http.parse(b'{"id":"Xxxx0001"}', ['Abcd0001'])
        with self.assertRaises(RuntimeError):d.http.parse(b'{"id":"Abcd0001"}\n{"id":"Abcd0001"}', ['Abcd0001'])
    def test_chronology_first_pair_previous_and_author_games(self):
        t=1700000000000;q=self.root/'queries.parquet';source=self.root/'chron.parquet'
        pq.write_table(pa.table(dict(row_id=[1,2],game_id=['Abcd0001','Abcd0002'],archive_start_ms=[t,t+1000],recipient_id=[1,1],opponent_id=[2,2],previous_frame=[False,False])),q)
        # IDs 3/4 may be author IDs: factual chronology must retain those games.
        pq.write_table(pa.table(dict(game_id=['Prev0001','Prev0002','Abcd0001','Abcd0002'],utc_ms=[t-100000,t-50000,t,t+1000],white_id=[1,2,1,1],black_id=[3,4,2,2])),source)
        prepared,info=m.cached_chronology.prepare_chronology(q,self.root/'prep','x',.2)
        out=self.root/'part';job=dict(path=str(source),signature=m.io.sig(source),file_index=0,rows=4,people=str(prepared/'people.parquet'),pairs=str(prepared/'pairs.parquet'),focal=str(prepared/'focal.parquet'),latest=info['latest_start'],output=str(out),conf='x',memory=.2)
        m.cached_chronology.chronology_job(job)
        combined,_=m.cached_chronology.merge_chronology(q,prepared,[out],self.root/'combined','x',.2,1)
        r=sorted(pq.read_table(combined/'features.parquet').to_pylist(),key=lambda x:x['row_id'])
        self.assertTrue(r[0]['eligible_main']);self.assertTrue(r[0]['first_observed_pair']);self.assertEqual(r[0]['pre_games_30d'],1)
        self.assertFalse(r[1]['first_observed_pair']);self.assertFalse(r[1]['eligible_main'])
    def test_missing_metadata_remains_unknown_after_reconciliation(self):
        run=self.root/'run';(run/'PRIVATE').mkdir(parents=True);(run/'report').mkdir()
        a=types.SimpleNamespace(run=run,project=self.root,conf='x',memory_gb=2.2)
        folder=self.root/'month';folder.mkdir();cached(folder/'metadata.parquet',[])
        u.save(run/'PRIVATE/METADATA_PATHS.json',dict(months=[str(folder)]))
        u.save(run/'PRIVATE/SCORE_PATHS.json',dict(stream='stream'))
        q=self.root/'eligible.parquet'
        pq.write_table(pa.table(dict(row_id=[1,2],game_id=['Abcd0001','Abcd0002'],utc_ms=[1700000000000]*2,speed_partition=['blitz']*2,previous_frame=[False,False],metadata_status=['NO_CACHE']*2)),q)
        finished=self.root/'finished';finished.mkdir()
        pq.write_table(pa.Table.from_pylist([meta('Abcd0001')],schema=m.ex.metadata_schema()),finished/'downloaded_metadata.parquet')
        status=d.reconcile(a,dict(eligible_candidates=str(q),chronology='chron'),finished)
        self.assertEqual(status,'RECOVERY_COMPLETE_WITH_GAPS')
        info=u.load(run/'report/reconciliation.json')
        self.assertEqual(info['metadata_status_counts'],{'CACHED_POOL_METADATA':1,'NO_CACHE':1})
        self.assertFalse(u.load(run/'PRIVATE/CONTINUATION.json')['models_ready'])
    def test_full_chronology_stage_freezes_only_needed_requests(self):
        run=self.root/'run';(run/'PRIVATE').mkdir(parents=True);(run/'report').mkdir()
        a=types.SimpleNamespace(run=run,project=self.root,conf='x',memory_gb=2.2,workers=1)
        t=1700000000000;month=self.root/'month';month.mkdir();query=self.root/'query.parquet';chron=self.root/'chron.parquet'
        pq.write_table(pa.table(dict(row_id=[1,2,3],game_id=['Abcd0001','Abcd0002','Abcd0003'],utc_ms=[t,t+10,t+1000],speed_partition=['blitz']*3,recipient_id=[1,5,1],opponent_id=[2,6,2],previous_frame=[True,False,False],metadata_status=['CACHED_POOL_METADATA','NO_CACHE','NO_CACHE'],certified_quarantine=[False]*3,retrieval_rank=[b'1',b'2',b'3'])),month/'dispositions.parquet')
        pq.write_table(pa.table(dict(row_id=[1,2,3],game_id=['Abcd0001','Abcd0002','Abcd0003'],archive_start_ms=[t,t+10,t+1000],recipient_id=[1,5,1],opponent_id=[2,6,2],previous_frame=[False]*3)),query)
        pq.write_table(pa.table(dict(game_id=['Prev0001','Prev0002','Prev0003','Prev0004','Abcd0001','Abcd0002','Abcd0003'],utc_ms=[t-100000,t-50000,t-80000,t-70000,t,t+10,t+1000],white_id=[1,2,5,6,1,5,1],black_id=[3,4,7,8,2,6,2])),chron)
        u.save(run/'PRIVATE/METADATA_PATHS.json',dict(months=[str(month)],queries=str(query),chronology_rows=3))
        source=dict(path=str(chron),file_index=0,rows=7,signature=m.io.sig(chron),minimum=t-100000)
        with patch.object(m.cached_inputs,'research_inputs',return_value=dict(chron=[source])):m.chronology(a)
        plan=u.load(run/'PRIVATE/REQUEST_PLAN.json');self.assertEqual(plan['target_rows'],1)
        self.assertEqual(pq.read_table(plan['targets'])['game_id'].to_pylist(),['Abcd0002'])
        self.assertEqual(pq.ParquetFile(plan['eligible_candidates']).metadata.num_rows,2)
    def test_empty_return_exports_typed_parquet(self):
        target=self.root/'targets.parquet';pq.write_table(pa.table(dict(game_id=pa.array([],type=pa.string()),utc_ms=pa.array([],type=pa.int64()),speed_partition=pa.array([],type=pa.string()))),target)
        db=d.dl.connect(self.root/'db.sqlite3','conf',u.sha(target))
        try:
            folder,info=d.dl.export_saved(db,target,self.root/'finished','conf')
            self.assertEqual(info['requested'],0);self.assertEqual(pq.ParquetFile(folder/'downloaded_metadata.parquet').metadata.num_rows,0)
        finally:db.close()
    def test_no_private_parquet_in_return_archive(self):
        a=types.SimpleNamespace(run=self.root,desktop=self.root,conf='x'*64)
        (self.root/'report').mkdir();(self.root/'report/rows_PRIVATE.parquet').write_bytes(b'private')
        with self.assertRaisesRegex(RuntimeError,'Private file'):u.export(a,50,'test')
if __name__=='__main__':unittest.main()
