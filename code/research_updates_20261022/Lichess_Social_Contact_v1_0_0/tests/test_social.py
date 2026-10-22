import sys,tempfile,unittest,io,math,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from core import *
import prepare,acquire,contact,run_social

def target(k=1,y=True,j=10):
    start=START+10*DAY
    return dict(gid=f'g{k}',qid=k,j=j,i=100+k,pair_key=int(pairs([j],[100+k])[0]),start=start,anchor=start+60000,
      y=y,cp=0.,speed=2,month=0,rating=1500.,opp_rating=1520.,rd=50.,opp_rd=50.,cost=5.,draw_payoff=0.,
      clock=100.,opp_clock=100.,ply=20.,jvolume=50,ivolume=40,base=300.,inc=0.,repeat=False,same_start_other_games=0,
      meet30=0,meet90=0,meet180=0,giver_name='giver'+str(j),recipient_name='recipient'+str(k))

def game(t,gid=None,at=None,source='pool',rated=True):
    return dict(id=gid or t['gid'],createdAt=t['start'] if at is None else at,lastMoveAt=t['anchor'],rated=rated,source=source,
      status='draw',variant='standard',speed='blitz',players={'white':{'user':{'id':t['giver_name']}},'black':{'user':{'id':t['recipient_name']}}})

class SocialTests(unittest.TestCase):
    def test_api_query_has_both_modes_and_no_truncation(self):
        p=acquire.request_spec(target())['parameters']
        self.assertNotIn('rated',p);self.assertNotIn('max',p);self.assertNotIn('perfType',p);self.assertEqual(p['vs'],'recipient1')
    def test_local_chronology_crosscheck_and_duplicates(self):
        t=target();g=game(t);g['createdAt']+=321
        rows,qa=acquire.normalize([g,g],t,{t['gid']:t['start']})
        self.assertEqual(len(rows),1);self.assertEqual(qa['duplicate_rows'],1)
        with self.assertRaises(acquire.PairUnavailable):acquire.normalize([g],t,{t['gid']:t['start'],'missing':t['start']+DAY})
        bad=game(t);bad['players']['black']['user']['id']='someone_else'
        with self.assertRaises(acquire.PairUnavailable):acquire.normalize([bad],t,{t['gid']:t['start']})
    def test_timing_modes_source_and_persistence(self):
        t=target();raw=[game(t),game(t,'prior',t['start']-DAY,'friend',False),game(t,'tie',t['anchor'],'friend',False),
          game(t,'later',t['anchor']+DAY,'friend',False),game(t,'late',t['anchor']+9*DAY,'pool',True)]
        gg,_=acquire.normalize(raw,t,{t['gid']:t['start']});o=contact.outcomes(t,gg)
        self.assertEqual(o['pre90_casual_lo'],1);self.assertEqual(o['post7_casual_nonpool_lo'],1)
        self.assertEqual(o['post30_games'],2);self.assertEqual(o['post90_two_days_lo'],1);self.assertEqual(o['post90_span7days_lo'],1)
        self.assertEqual(o['late7to90_nonpool_lo'],0);self.assertEqual(o['late7to90_pool_source_lo'],1)
    def test_unknown_source_and_unavailable_not_zero(self):
        t=target();gg,_=acquire.normalize([game(t),game(t,'later',t['anchor']+DAY,None,False)],t,{t['gid']:t['start']})
        o=contact.outcomes(t,gg)
        self.assertEqual((o['post90_nonpool_lo'],o['post90_nonpool_hi']),(0,1))
        self.assertEqual((o['post90_casual_lo'],o['post90_casual_hi']),(1,1))
        o=contact.outcomes(t,None);self.assertFalse(o['history_available']);self.assertEqual((o['post90_all_lo'],o['post90_all_hi']),(0,1));self.assertIsNone(o['post90_games'])
    def test_aborted_import_and_focal_excluded(self):
        t=target();g=game(t,'abort',t['anchor']+DAY,'friend',False);g['status']='aborted'
        gg,_=acquire.normalize([game(t),g,game(t,'import',t['anchor']+DAY,'import',False)],t,{t['gid']:t['start']})
        self.assertEqual(contact.outcomes(t,gg)['post90_all_lo'],0)
    def test_sampling_holds_chooser_fixed_and_ignores_future(self):
        rows=[]
        for j in range(10,15):rows += [target(j*2,True,j),target(j*2+1,False,j)]
        rows += [dict(target(99),repeat=True),dict(target(100),anchor=END-DAY,start=END-2*DAY)]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pq.write_table(pa.Table.from_pylist(rows),root/'f.parquet')
            meta=prepare.matched_targets(root/'f.parquet',root/'a',3,1,512);rr=pq.ParquetFile(root/'a/selected.parquet').read().to_pylist()
            self.assertEqual(meta['selected_sets'],3)
            for a,b in zip(rr[::2],rr[1::2]):self.assertEqual(a['j'],b['j']);self.assertTrue(a['y']);self.assertFalse(b['y'])
            for r in rows:r['meet90']=99;r['meet180']=500
            pq.write_table(pa.Table.from_pylist(rows),root/'f2.parquet');prepare.matched_targets(root/'f2.parquet',root/'b',3,1,512)
            r2=pq.ParquetFile(root/'b/selected.parquet').read(columns=['gid']).to_pylist()
            self.assertEqual([r['gid'] for r in rr],[r['gid'] for r in r2])
            self.assertEqual(prepare.matched_targets(root/'f.parquet',root/'a',3,1,512)['selected_sets'],3)
    def test_paired_estimator_and_cluster_variance(self):
        rng=np.random.default_rng(77);y=rng.integers(-1,2,1000).astype(float);j=np.arange(1000)
        ans=contact.paired_fit(y,j)
        self.assertAlmostEqual(ans['estimate'],y.mean());self.assertAlmostEqual(ans['se'],y.std(ddof=1)/np.sqrt(len(y)))
        x=rng.normal(size=(1000,2));ans=contact.paired_fit(y,j,x)
        self.assertAlmostEqual(ans['estimate'],np.linalg.lstsq(np.column_stack([np.ones(1000),x]),y,rcond=None)[0][0])
        self.assertFalse(contact.paired_fit(np.zeros(100),np.arange(100))['supported'])
    def test_per_pair_checkpoint_avoids_reacquisition(self):
        t=target()
        class Fake:
            n=0
            def get(self,url):self.n+=1;return [game(t)]
        client=Fake()
        with tempfile.TemporaryDirectory() as td:
            _,a=acquire.acquire_one(t,{t['gid']:t['start']},td,client)
            _,b=acquire.acquire_one(t,{t['gid']:t['start']},td,client)
            self.assertEqual(client.n,1);self.assertFalse(a['reused']);self.assertTrue(b['reused'])
    def test_rate_limit_retry(self):
        calls=[];sleeps=[]
        class Response:
            status=200;headers={'Content-Type':'application/x-ndjson'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def __iter__(self):return iter([b'{"ok":true}\n'])
        def opener(req,timeout):
            calls.append(req)
            if len(calls)==1:raise urllib.error.HTTPError(req.full_url,429,'limit',{'Retry-After':'61'},None)
            return Response()
        client=acquire.Client(opener=opener,sleeper=sleeps.append)
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(client.get('https://lichess.org/api/test'),[{'ok':True}])
        self.assertIn(61,sleeps);self.assertEqual(client.requests,2)
    def test_orchestrator_with_names_expected_games_and_resume(self):
        from unittest.mock import patch
        import argparse
        with tempfile.TemporaryDirectory() as td,contextlib.redirect_stdout(io.StringIO()):
            root=Path(td);rr=[target(1,True,10),target(2,False,10),target(3,True,11),target(4,False,11)]
            pq.write_table(pa.Table.from_pylist([{k:v for k,v in r.items() if k not in ('giver_name','recipient_name')} for r in rr]),root/'features.parquet')
            pp=[dict(game_id=r['gid'],chooser_user_id=r['j'],disconnected_user_id=r['i'],chooser_username_norm=r['giver_name'],disconnected_username_norm=r['recipient_name']) for r in rr]
            pq.write_table(pa.Table.from_pylist(pp),root/'panels.parquet')
            ee=[dict(gid=r['gid'],pair_key=r['pair_key'],t=r['start']) for r in rr]
            pq.write_table(pa.Table.from_pylist(ee),root/'events.parquet')
            parent=dict(features=str(root/'features.parquet'),events=str(root/'events.parquet'),panels=[dict(path=str(root/'panels.parquet'),fingerprint=stamp(root/'panels.parquet'))])
            class FakeClient:
                def __init__(self):self.requests=0
                def get(self,url):
                    self.requests+=1
                    name=acquire.urllib.parse.parse_qs(acquire.urllib.parse.urlparse(url).query)['vs'][0]
                    return [game(next(r for r in rr if r['recipient_name']==name))]
            args=argparse.Namespace(project_root=str(root/'project'),desktop=str(root/'desktop'),max_sets=2,workers=1,memory_mb=512,retry_unavailable=False)
            with patch.object(run_social,'verify_release',return_value='synthetic'),patch.object(prepare,'parent_run',return_value=parent),patch.object(acquire,'Client',FakeClient):
                run_social.execute(args);run_social.execute(args)
            report=next((root/'project/derived/replication/social_contact_v100_PRIVATE').glob('*/report/SUMMARY.json'))
            result=load(report);self.assertEqual(result['successful_histories'],4);self.assertEqual(result['api_requests'],0)
            self.assertFalse(result['parent_history_rescanned'])
    def test_full_report_bounds_and_export_privacy(self):
        rows=[]
        for j in range(100):
            for arm in (True,False):
                t=target(j*2+int(arm),arm,j+1);t['match_id']=str(j)
                raw=[game(t)]
                if (j%3==0 and arm) or (j%5==0 and not arm):raw.append(game(t,'later',t['anchor']+DAY,'friend',False))
                gg,_=acquire.normalize(raw,t,{t['gid']:t['start']})
                rows.append(dict(**t,**contact.outcomes(t,None if j==0 and arm else gg)))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);res=contact.analyze(rows,root/'report');self.assertEqual(res['failed_histories'],1)
            import csv,zipfile
            with (root/'report/contact_rates_and_missing_bounds.csv').open() as f:rates=list(csv.DictReader(f))
            x=next(r for r in rates if r['cohort']=='all_matched' and r['outcome']=='post90_casual')
            self.assertGreater(float(x['contact_after_grant_upper_pct']),float(x['contact_after_grant_lower_pct']))
            (root/'report/private.parquet').write_bytes(b'private')
            with contextlib.redirect_stdout(io.StringIO()):run_social.export(root/'report',root/'exports','test','TEST')
            with zipfile.ZipFile(next((root/'exports').glob('*.zip'))) as z:self.assertNotIn('private.parquet',z.namelist())

if __name__=='__main__':unittest.main()
