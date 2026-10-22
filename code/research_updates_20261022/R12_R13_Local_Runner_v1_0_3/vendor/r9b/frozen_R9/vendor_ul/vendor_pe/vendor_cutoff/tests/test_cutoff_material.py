import sys,unittest,tempfile,math,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from iv_common import *
from iv_history import AsOf,segmented_cumsum,score,score_job,combine,prepare_queries
from iv_material import material_from_fen,neutral,attach
from run_iv import reproduction,report,run_scores
from unittest.mock import patch
import chess

def data(seed=532,n=5000,nq=80):
    rng=np.random.default_rng(seed)
    h=dict(j=rng.integers(1,15,n,dtype=np.int64),i=rng.integers(20,45,n,dtype=np.int64),
           t=rng.integers(STARTS[0],STARTS[7],n,dtype=np.int64),y=rng.binomial(1,.2,n),
           cell=rng.integers(0,500,n,dtype=np.int64))
    m=rng.integers(1,7,nq,dtype=np.int64)
    q=dict(row_id=np.arange(nq),opponent_id=rng.integers(1,16,nq,dtype=np.int64),
           recipient_id=rng.integers(20,46,nq,dtype=np.int64),month_code=m,
           archive_start_ms=np.asarray(STARTS)[m]+rng.integers(0,10*DAY,nq))
    ref=rng.uniform(.02,.95,(2,24,4,4,500))
    return h,q,ref

def brute(h,q,ref,tag):
    out={k:[] for k in ('n','counterparts','expected','adjusted')}
    for j,i,m,start in zip(q['opponent_id'],q['recipient_id'],q['month_code'],q['archive_start_ms']):
        cutoff=STARTS[m]-7*DAY if tag=='7d' else start-DAY
        use=(h['j']==j)&(h['i']!=i)&(h['t']<cutoff)
        n=int(use.sum());jf=int(r.num.user_hash(np.asarray([j]))[0]%np.uint64(4));rf=int(r.num.user_hash(np.asarray([i]))[0]%np.uint64(4))
        model=ref[0,m,jf,rf]
        expected=float(model[h['cell'][use]].mean()) if n and np.isfinite(model).all() else np.nan
        raw=float(h['y'][use].mean()) if n else np.nan
        for k,v in dict(n=n,counterparts=len(np.unique(h['i'][use])),expected=expected,adjusted=raw-expected).items():out[k].append(v)
    return {k:np.asarray(v) for k,v in out.items()}

class HistoryTests(unittest.TestCase):
    def test_segmented_prefix_accuracy(self):
        rng=np.random.default_rng(78)
        for n in (0,1,511,512,513,1024,30000):
            weights=rng.uniform(0,1,n);groups=np.cumsum(rng.random(n)<.02)
            got=segmented_cumsum(weights,groups)
            for g in np.unique(groups):
                ix=np.flatnonzero(groups==g)
                np.testing.assert_allclose(got[ix],np.cumsum(weights[ix]),rtol=1e-13,atol=1e-11)
        n=300000;weights=rng.uniform(0,1,n);got=segmented_cumsum(weights,np.zeros(n,int))
        self.assertLess(abs(got[-1]-math.fsum(weights)),1e-9)

    def test_asof_strict_ties_and_empty(self):
        a=AsOf([np.array([2,1,1,1])],np.array([8,4,4,7]),[np.array([1,1,1,2,3])],np.array([4,5,8,9,100]))
        np.testing.assert_array_equal(a.count,[0,2,3,1,0])
        np.testing.assert_allclose(a.sums(np.array([4,1,2,3])),[0,3,6,4,0])
        a=AsOf([np.array([],int)],np.array([],int),[np.array([1])],np.array([2]))
        np.testing.assert_array_equal(a.count,[0]);np.testing.assert_array_equal(a.sums([]),[0])

    def test_random_against_direct_and_original_producer(self):
        h,q,ref=data();got=score(h,q,ref)
        for tag in ('7d','24h'):
            for k,want in brute(h,q,ref,tag).items():
                np.testing.assert_allclose(got[tag][k],want,rtol=0,atol=2e-12,equal_nan=True)
        for m in np.unique(q['month_code']):
            use=q['month_code']==m
            old=r.num.score_month(h['j'],h['i'],h['t'],h['y'],h['cell'],q['opponent_id'][use],q['recipient_id'][use],STARTS[m]-7*DAY,ref[0,m])
            for k in ('n','counterparts','expected','adjusted'):
                np.testing.assert_allclose(got['7d'][k][use],old[k],atol=2e-12,equal_nan=True)

    def test_pair_exclusion_and_boundary(self):
        h,q,ref=data(n=500,nq=1);q['month_code'][:]=4;q['archive_start_ms'][:]=STARTS[4]+2*DAY
        cutoff=q['archive_start_ms'][0]-DAY;j=q['opponent_id'][0];i=q['recipient_id'][0]
        before=score(h,q,ref)
        for t,partner in [(cutoff-10,i),(cutoff,999),(cutoff+1,999)]:
            more={k:np.r_[v,dict(j=j,i=partner,t=t,y=1,cell=2)[k]] for k,v in h.items()}
            after=score(more,q,ref)
            for tag in before:
                for k in before[tag]:np.testing.assert_allclose(before[tag][k],after[tag][k],equal_nan=True)
        more={k:np.r_[v,dict(j=j,i=999,t=cutoff-1,y=1,cell=2)[k]] for k,v in h.items()}
        self.assertEqual(score(more,q,ref)['24h']['n'][0],before['24h']['n'][0]+1)

    def test_empty_reference_stays_missing(self):
        h,q,ref=data();ref[:]=np.nan;got=score(h,q,ref)
        self.assertTrue(np.isnan(got['24h']['adjusted']).all())
        self.assertTrue((got['24h']['n']>0).any())

    def test_history_job_resume_and_mutation_rejection(self):
        h,q,ref=data(n=5000,nq=12)
        s=int(r.num.user_hash(np.array([1]))[0]%np.uint64(16));h['j'][:]=1;q['opponent_id'][:]=1
        q['month_code'][:]=6;q['archive_start_ms'][:]=STARTS[6]+DAY
        h['arm']=np.ones(len(h['j']),bool);h['arm'][::8]=False
        authors=[20,21];keep=h['arm']&~np.isin(h['i'],authors)
        clean={k:v[keep] for k,v in h.items() if k!='arm'}
        old=score(clean,q,ref)['7d'];q.update({k+'_7d':v for k,v in old.items()})
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r.io.table(p/'h.parquet',pa.table(h));r.io.table(p/'q.parquet',pa.table(q));np.save(p/'ref.npy',ref)
            job=dict(parts=[dict(path=str(p/'h.parquet'),sha256=u.sha(p/'h.parquet'),rows=len(h['j']))],authors=authors,
                shard=s,queries=str(p/'q.parquet'),reference=str(p/'ref.npy'),output=str(p/'out'),conf='test')
            got=score_job(job);again=score_job(job)
            self.assertEqual(got['queries'],12);self.assertEqual(again['queries'],12)
            a=r.arrays(r.io.read(p/'out/scores.parquet'))
            np.testing.assert_allclose(a['adjusted_24h'],score(clean,q,ref)['24h']['adjusted'],atol=2e-12)
            q['archive_start_ms']+=1;r.io.table(p/'q.parquet',pa.table(q))
            with self.assertRaisesRegex(RuntimeError,'input changed'):score_job(job)

    def test_combine_identity_and_order(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r.io.table(p/'q.parquet',pa.table(dict(row_id=[1,2,3])))
            r.io.table(p/'s.parquet',pa.table(dict(row_id=[3,1,2],adjusted_24h=[.3,.1,.2])))
            path=combine([str(p/'s.parquet')],str(p/'q.parquet'),p/'out','test',1)
            np.testing.assert_array_equal(r.io.arr(r.io.read(path),'row_id'),[1,2,3])
            r.io.table(p/'bad.parquet',pa.table(dict(row_id=[1,1,3])))
            with self.assertRaisesRegex(RuntimeError,'identities differ'):combine([str(p/'bad.parquet')],str(p/'q.parquet'),p/'bad','test',1)

    def test_spawned_score_worker(self):
        h,q,ref=data(n=800,nq=8);h['j'][:]=1;q['opponent_id'][:]=1
        q['month_code'][:]=6;q['archive_start_ms'][:]=STARTS[6]+DAY
        q.update({k+'_7d':v for k,v in score(h,q,ref)['7d'].items()})
        h['arm']=np.ones(len(h['j']),bool)
        s=int(r.num.user_hash(np.array([1]))[0]%np.uint64(16))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r.io.table(p/'h.parquet',pa.table(h));r.io.table(p/'q.parquet',pa.table(q));np.save(p/'ref.npy',ref)
            job=dict(parts=[dict(path=str(p/'h.parquet'),sha256=u.sha(p/'h.parquet'),rows=len(h['j']))],authors=[99,100],
                shard=s,queries=str(p/'q.parquet'),reference=str(p/'ref.npy'),output=str(p/'out'),conf='spawn')
            self.assertEqual(run_scores([job],1,6)[0]['queries'],8)

class MaterialTests(unittest.TestCase):
    def test_strict_boundaries(self):
        for v in (-4,4,-5,5,None):self.assertFalse(neutral(v))
        for v in (-3,-2,-1,0,1,2,3):self.assertTrue(neutral(v))

    def test_final_material_and_ply(self):
        board=chess.Board();self.assertEqual(material_from_fen(board.fen(),0),(0,'valid'))
        for san in ('e4','d5','exd5'):board.push_san(san)
        self.assertEqual(material_from_fen(board.fen(),3),(1,'valid'))
        self.assertEqual(material_from_fen(board.fen(),2)[1],'ply_mismatch')
        self.assertEqual(material_from_fen(None,0)[1],'missing_fen')
        self.assertEqual(material_from_fen('bad',0)[1],'invalid_fen')
        self.assertEqual(material_from_fen('8/8/8/8/8/8/8/8 w - - 0 1',0)[1],'invalid_board')

    def test_promotions_values_and_endpoints(self):
        cases=[('7k/8/8/8/8/8/Q7/7K w - - 0 1',9),
               ('7k/8/8/8/8/8/Rp6/7K w - - 0 1',4),
               ('7k/8/8/8/8/8/rP6/7K w - - 0 1',-4)]
        for fen,want in cases:self.assertEqual(material_from_fen(fen,0),(want,'valid'))

    def test_authenticated_attachment_and_missing_source(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);q=dict(row_id=[0,1,2],game_id=['a','b','c'],recipient_id=[10,11,12],opponent_id=[20,21,22],
                anchor_ms=[100,200,300],received=[True,False,False],y=[False,True,False],reached=[True,True,False])
            s=dict(game_id=q['game_id'],disconnected_user_id=q['recipient_id'],chooser_user_id=q['opponent_id'],api_last_move_at_ms=q['anchor_ms'],
                kind_draw=q['received'],engine_eval_cp_disconnected=[0.,-100.,10.],ply_count=[0,0,0],
                fen_after_last_move=[chess.Board().fen(),'7k/8/8/8/8/8/Rp6/7K w - - 0 1',None])
            r.io.table(p/'q.parquet',pa.table(q));r.io.table(p/'s.parquet',pa.table(s));r.io.js(p/'manifest.json',{})
            with patch('iv_material.u.full_source_panels',return_value=([dict(path=str(p/'s.parquet'))],p/'manifest.json')):
                out,info=attach(str(p/'q.parquet'),p,p/'out','test',3)
            self.assertEqual(info['flow']['neutral']['rows'],1);self.assertEqual(info['flow']['observed']['rows'],2)
            self.assertIsNone(r.io.read(out)['material_white_minus_black'].to_pylist()[2])
            del s['fen_after_last_move'];r.io.table(p/'s_missing.parquet',pa.table(s))
            with patch('iv_material.u.full_source_panels',return_value=([dict(path=str(p/'s_missing.parquet'))],p/'manifest.json')):
                out,info=attach(str(p/'q.parquet'),p,p/'unavailable','test',3)
            self.assertIsNone(out);self.assertEqual(info['status'],'MATERIAL_SOURCE_UNAVAILABLE')

class AdapterTests(unittest.TestCase):
    def test_fit_controls_outcomes_unchanged_and_screen_rows(self):
        sys.path.insert(0,str(ROOT/'vendor_r8/vendor_r7/tests'))
        from test_r7 import fixture
        d=fixture(2800);n=len(d['row_id']);order=np.argsort(d['row_id']);d={k:v[order] for k,v in d.items()}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r.io.table(p/'input.parquet',pa.table(d))
            new=d['adjusted_7d']*1.05+.003
            r.io.table(p/'scores.parquet',pa.table(dict(row_id=d['row_id'],n_24h=np.full(n,100),adjusted_24h=new)))
            valid=np.ones(n,bool);keep=np.arange(n)%20!=0
            r.io.table(p/'mat.parquet',pa.table(dict(row_id=d['row_id'],material_valid=valid,material_neutral=keep)))
            captured=[]
            real=models.estimate
            def capture(a,*args,**kw):
                captured.append({k:v.copy() for k,v in a.items()})
                return real(a,*args,**kw)
            with patch('iv_common.models.estimate',side_effect=capture):
                fit(str(p/'input.parquet'),p/'fits/old','test','old_monthly',scores=str(p/'scores.parquet'))
                fit(str(p/'input.parquet'),p/'fits/new','test','lag24h',scores=str(p/'scores.parquet'))
                fit(str(p/'input.parquet'),p/'fits/neutral','test','lag24h','neutral',scores=str(p/'scores.parquet'),material=str(p/'mat.parquet'))
            self.assertEqual(len(captured),3)
            for k in captured[0]:
                if k!='adjusted_7d':np.testing.assert_array_equal(captured[0][k],captured[1][k])
            np.testing.assert_array_equal(captured[1]['adjusted_7d'],new)
            np.testing.assert_array_equal(captured[2]['row_id'],d['row_id'][keep])
            old=r.io.load(p/'fits/old/result.json')['B_estimates']
            latest=r.io.load(p/'fits/new/result.json')['B_estimates']
            iv0=next(v for v in old if v['estimator']=='2SLS');iv1=next(v for v in latest if v['estimator']=='2SLS')
            self.assertAlmostEqual(iv0['iv_coefficient_pp'],iv1['iv_coefficient_pp'],7)
            fit(str(p/'input.parquet'),p/'fits/new','test','lag24h',scores=str(p/'scores.parquet'))
            report(p,p/'desktop','testconfiguration','SYNTHETIC_ONLY',100,dict(synthetic=True))
            comparison=r.io.load(p/'report/comparison.json')
            self.assertEqual(len(comparison),3)
            self.assertTrue(all(v['same_row_pair_complete'] for v in comparison if v['exposure_screen']=='all'))

    def test_reproduction_target_logic(self):
        result={k:[v for v in r.io.load(ROOT/'evidence'/f'{k}.json') if v['sample']=='S0' and v['control_level']=='X0' and v['instrument']=='pooled']
                for k in ('B_estimates','B_balance','B_joint_balance')}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r.io.js(p/'result.json',result);self.assertEqual(len(reproduction(p)),12)
            result['B_estimates'][0]['coefficient_pp']+=1;r.io.js(p/'result.json',result)
            with self.assertRaises(RuntimeError):reproduction(p)

if __name__=='__main__':unittest.main()
