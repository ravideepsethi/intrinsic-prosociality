"""Integration tests of on-disk moments, G1 optimization, UCI I/O and aggregate export."""
import json,os,sys,tempfile,unittest,zipfile,chess
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'code'),str(Path(__file__).resolve().parent)]
from test_core import fixture
from g_common import *
import g_fe
from g_design import *
from g_outcome import *
from g_engine import evaluate_chunk
from g_reports import fill_unrun,write_results

class PipelineTests(unittest.TestCase):
    def test_mnl_fit_and_game_bootstrap(self):
        d=fixture(200,35);d['vf']*=3;d['stm']=np.arange(len(d))%2;d['test']=~d.train;d['weight']=1.
        d['outcome']=np.random.default_rng(44).integers(0,3,len(d));d['ply_bin']=ply_bin(d.ply)
        with tempfile.TemporaryDirectory() as td:
            m=fit_outcome(d,td,maxiter=300);p=predict_chunks(m,d);np.testing.assert_allclose(p.sum(1),1,atol=1e-12)
            counts=bootstrap_games(d,8)
            for _,ix in d.groupby(['speed','ply_bin']).indices.items():self.assertEqual(counts[ix].sum(),len(ix))
            n=fit_outcome(d,td,multiplicity=counts,warm=m,maxiter=300)
            self.assertGreater(np.max(np.abs(p-predict_chunks(n,d))),1e-5)
    def test_secondary_monotone_and_coherent(self):
        d=fixture(80,30);d['vf']*=3;d['test']=~d.train;d['weight']=1.;d['outcome']=np.random.default_rng(31).integers(0,3,len(d))
        with tempfile.TemporaryDirectory() as td:
            m=fit_outcome(d,td,'sequential');x=pd.DataFrame([d.iloc[0]]*60);x['vf']=np.linspace(-1500,1500,60)
            p=m.predict(x);self.assertTrue((np.diff(p[:,0])>=-1e-12).all());self.assertTrue((np.diff(p[:,2])<=1e-12).all());np.testing.assert_allclose(p.sum(1),1,atol=1e-12)
    def test_disk_moments(self):
        # Scale the block count only in this synthetic test; all production runs have exactly 2,000.
        original_blocks=g_fe.BLOCKS;original_layout=g_fe.account_layout
        def small(d):
            start,count,index,block=original_layout(d);return start,count,index,block%20
        g_fe.BLOCKS=20;g_fe.account_layout=small
        try:
            d=fixture(80,30);d['vf']*=3;d['board']=-d.vf
            class Model:
                def predict(self,z):
                    p=expit(z.vf.to_numpy()/400-z.dr.to_numpy()/2000);return np.column_stack([.9*p,np.full(len(z),.1),.9*(1-p)])
            model=Model();p=model.predict(d);knots=dict(knots=index_knots(p[d.train,0]),score_knots=index_knots(p[d.train,0]+.5*p[d.train,1]))
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'data.parquet';atomic_parquet(d,path)
                stores=g_fe.build_moments([path],model,knots,Path(td)/'moments');fit=stores['MR'].fit()
                X=g2_design(d,'MR',p[:,0],p[:,0]+.5*p[:,1],knots['knots'],knots['score_knots'])[0]
                zt,_,train,_,_=g_fe.within_forms(d,X);direct=g_fe.solve(zt[train].T@zt[train])
                np.testing.assert_allclose(fit['train']['beta'],direct['beta'],atol=1e-8)
                direct_loss=g_fe.quadratic(zt[~train].T@zt[~train],direct['beta'])/(~train).sum();self.assertAlmostEqual(fit['brier'],direct_loss,places=10)
                for m,s in stores.items():self.assertTrue(np.isfinite(s.fit()['brier']))
        finally:g_fe.BLOCKS=original_blocks;g_fe.account_layout=original_layout
    def test_uci_orientation(self):
        with tempfile.TemporaryDirectory() as td:
            fake=Path(td)/'fake_uci'
            fake.write_text('#!'+sys.executable+'\n'+'''import sys,chess
b=chess.Board()
for line in sys.stdin:
 s=line.strip()
 if s=='uci':
  print('id name Test engine');print('option name Hash type spin default 16 min 1 max 2048');print('option name Threads type spin default 1 min 1 max 10');print('uciok',flush=True)
 elif s=='isready':print('readyok',flush=True)
 elif s.startswith('position fen '):b=chess.Board(s[len('position fen '):])
 elif s.startswith('go '):
  score='mate 0' if b.is_checkmate() else 'cp 50'
  print('info depth 10 nodes 100000 score '+score)
  print('bestmove '+('0000' if b.is_game_over() else next(iter(b.legal_moves)).uci()),flush=True)
 elif s=='quit':break
''');fake.chmod(0o700)
            b=chess.Board();b.push_san('e4')
            config=dict(sf100k_threads=1,sf100k_hash_mb=16,sf100k_nodes_requested=100000,sf100k_eval_method='uci_go_nodes')
            rows,seconds=evaluate_chunk(dict(engine=str(fake),config=config,perspective='white',rows=[dict(game_id='AbCd1234',fen=b.fen())]))
            self.assertEqual(rows[0]['vf'],-50);self.assertEqual(rows[0]['nodes'],100000)
    def test_aggregate_export(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);run=root/'run';run.mkdir();(run/'report').mkdir();(run/'RUN.log').write_text('Synthetic test log only\n')
            fill_unrun(run,'Synthetic gate');out=package(run,root,'TEST','SYNTHETIC')
            with zipfile.ZipFile(out) as z:
                self.assertTrue('report/STATUS.json' in z.namelist());self.assertFalse(any('PRIVATE' in x for x in z.namelist()))
                self.assertEqual(json.loads(z.read('report/STATUS.json'))['status'],'SYNTHETIC')
            self.assertEqual(out.with_suffix('.zip.sha256').read_text().split()[0],sha(out))
            out=package(run,root,'TEST','SYNTHETIC_RESUME')
            with zipfile.ZipFile(out) as z:
                self.assertEqual(len(z.namelist()),len(set(z.namelist())))
                for line in z.read('report/REPORT_SHA256SUMS.txt').decode().splitlines():
                    digest_value,name=line.split('  ',1)
                    self.assertEqual(digest_value,hashlib.sha256(z.read('report/'+name)).hexdigest())
            with self.assertRaises(GateError):table(run/'report','leak',[dict(game_id='AbCd1234')],{})
    def test_final_report_writer(self):
        point={'M0:gain':0.,'MR:gain':.002,'MU:gain':.002,'MRU:gain':.0021,'MRprime:gain':.002,'MRUprime:gain':.0021,
            'A_raw':.0001,'A_omega':.0001,'D10':-.00011,'D25':-.000425,'S_R':.002/.0021,'S':1.,
            'primeA_raw':.0001,'primeA_omega':.0001,'primeD10':-.00011,'primeD25':-.000425,'primeS_R':.002/.0021,'primeS':1.,
            'Xr:0':100.,'X_w:0:100:0':100.,'X_eq:0:100:0':120.,'within:MRU:gain':.01}
        for label in ['gap_competitive','gap_clearly_worse','clock_competitive']:
            for model in ['MR','MU','MRprime']:point[model+':'+label]=.02
            point['difference:'+label]=0.
        for name in ['MRU:gain','D10','D25']:point['logloss:'+name]=point[name]
        records=[dict(family=i//10,inner=i%10,statistics=dict(point)) for i in range(100)]
        exchange_info=dict(R=1.,draws=np.ones(100),slope=1.,slope_draws=np.ones(100),intercept=0.,intercept_draws=np.zeros(100),status='resolved',cells=[0],coverage=1.)
        exchange_info.update(eiv_slope=1.,eiv_slope_draws=np.ones(100),eiv_reliability=1.,eiv_centered_error_variance=0.)
        mc=[dict(statistic=n,simulation_resolved=True) for n in ['MRU:gain','D10','D25','MRUprime:gain','primeD10','primeD25','R','difference:gap_competitive','difference:gap_clearly_worse','difference:clock_competitive']]
        with tempfile.TemporaryDirectory() as td:
            run=Path(td);(run/'report').mkdir();save(run/'g1/fit/META.json',dict(meta=dict(N=1000,source_months=['2023-11'],ending_status_coverage='Synthetic only')))
            write_results(run,point,records,exchange_info,mc,'synthetic',{'M0':dict(counts=np.array([30,10,40,5]))},pd.DataFrame(dict(cell=[0],N=[40])))
            self.assertEqual(len(list((run/'report').glob('*.pdf'))),3)
            reading=load(run/'report/READING.json');self.assertEqual(reading['categories']['exchange_rate'],'similar')

if __name__=='__main__':unittest.main(verbosity=2)
