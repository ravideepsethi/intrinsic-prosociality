import sys,tempfile,unittest,math,json
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'closeout'))
from closeout_common import *
import mechanism as mm,material as mat,recent_kernel as rk

class CloseoutTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=SimpleNamespace(workers=2,memory_gb=8,parent=self.root/'parent')
    def tearDown(self):self.tmp.cleanup()
    def ordinary(self,n=1200):
        r=np.random.default_rng(333);idx=np.arange(n);arm=r.random(n)<.25;arm[0]=True;reached=r.random(n)<.75
        ids=idx%80+1;opp=idx%77+101;future=idx%41+201
        data=dict(row_id=idx,game_id=['g%07d'%k for k in idx],recipient_color=np.where(idx%2,'white','black'),recipient_id=ids,opponent_id=opp,
          recipient_username=['p'+str(k) for k in ids],opponent_username=['p'+str(k) for k in opp],status=np.where(arm,'draw',np.where(idx%2,'mate','resign')),complete90=np.ones(n,bool),eligible_main=np.ones(n,bool),first_observed_pair=np.ones(n,bool),history_window_complete=np.ones(n,bool),
          y=(r.random(n)<(.05+.025*arm))&reached,reached=reached,outcome_opponent=np.where(reached,future,-1),outcome_start=np.where(reached,2*DAY,0),outcome_t=np.where(reached,2*DAY+100,0),outcome_gid=['f%07d'%k for k in idx],anchor_ms=np.full(n,DAY+100),archive_start_ms=np.full(n,DAY),month_code=np.zeros(n,int),tc_base_s=np.where(idx%3,300,180),tc_inc_s=np.zeros(n,int),
          recipient_rating=r.integers(1400,1599,n),opponent_rating=r.integers(1400,1599,n),fair_90=np.full(n,3),kind_90=np.zeros(n,int),disconnect_90=r.integers(0,5,n),receipt_90=r.integers(0,2,n),claim_90=r.integers(0,3,n),pre_games_90d=np.full(n,100))
        md={k:data[k] for k in ('game_id','status','anchor_ms','tc_base_s','tc_inc_s')}
        md.update(winner=[None if arm[k] else ('black' if data['recipient_color'][k]=='white' else 'white') for k in idx],white_username=[data['recipient_username'][k] if data['recipient_color'][k]=='white' else data['opponent_username'][k] for k in idx],black_username=[data['recipient_username'][k] if data['recipient_color'][k]=='black' else data['opponent_username'][k] for k in idx])
        sc=dict(row_id=idx,n_A=np.full(n,10),adjusted_A=r.normal(0,.04,n),expected_A=np.full(n,.02))
        paths={}
        for name,value in [('frame',data),('metadata',md),('frame_scores',sc)]:
            p=self.root/(name+'.parquet');pq.write_table(pa.table(value),p);paths[name]=str(p)
        return dict(paths=paths,authors=[9001,9002])
    def test_frame_identity_and_invalid_result_fail_closed(self):
        auth=self.ordinary();p=mm.prepare(self.a,self.root/'run','fixture',auth);self.assertEqual(rows(p),1200)
        md=pq.read_table(auth['paths']['metadata']).to_pydict();md['winner'][0]='white';pq.write_table(pa.table(md),auth['paths']['metadata'])
        with self.assertRaisesRegex(RuntimeError,'Invalid ordinary result'):mm.prepare(self.a,self.root/'bad','bad',auth)
    def test_timing_and_author_in_future_fail_closed(self):
        auth=self.ordinary();p=auth['paths']['frame'];d=pq.read_table(p).to_pydict();d['reached'][0]=True;d['outcome_opponent'][0]=9001;pq.write_table(pa.table(d),p)
        with self.assertRaisesRegex(RuntimeError,'Author'):mm.prepare(self.a,self.root/'bad','bad',auth)
        d['outcome_opponent'][0]=201;d['outcome_start'][0]=d['anchor_ms'][0];pq.write_table(pa.table(d),p)
        with self.assertRaisesRegex(RuntimeError,'future'):mm.prepare(self.a,self.root/'bad2','bad2',auth)
    def test_three_role_covariance_matches_pairwise_oracle(self):
        r=np.random.default_rng(8);n=60;actors=r.integers(1,14,(n,3));actors[::5,2]=-1;actors[1]=actors[0,::-1];actors[2]=[1,1,1];u=r.normal(size=(n,2))
        path=self.root/'if.parquet';pq.write_table(pa.table(dict(recipient_id=actors[:,0],opponent_id=actors[:,1],future_id=actors[:,2],if_y=u[:,0],if_reached=u[:,1])),path)
        dep=np.array([[bool(set(a[a>=0])&set(b[b>=0])) for b in actors] for a in actors])
        got,vr,g=mm.covariance(path,self.root/'cov',buckets=7)
        np.testing.assert_allclose(got,u.T@dep@u,atol=1e-10)
        rd=actors[:,0,None]==actors[None,:,0];np.testing.assert_allclose(vr,u.T@rd@u,atol=1e-10)
        self.assertEqual(g,len(np.unique(actors[:,0])))
    def test_overlap_fit_matches_dense_weighted_cell_fe_and_resume(self):
        auth=self.ordinary();source=mm.prepare(self.a,self.root/'run','fixture',auth)
        result=mm.fit(self.a,self.root/'run','fixture',source,'overlap')
        selected=pq.read_table(self.root/'run/PRIVATE/ordinary_models/overlap/selected.parquet').to_pydict()
        d={k:np.array(v) for k,v in selected.items()};w=d['weight'];arm=d['arm'];y=d['y'].astype(float)
        # Independent dense WLS oracle: recover the exact cell labels by row ID.
        base=pq.read_table(source).to_pydict();lookup={int(k):j for j,k in enumerate(base['row_id'])}
        tuples=[tuple(base[k][lookup[int(i)]] for k in mm.CELL) for i in d['row_id']]
        _,codes=np.unique(np.array(tuples),axis=0,return_inverse=True)
        X=np.column_stack([np.eye(codes.max()+1)[codes],arm]);sw=np.sqrt(w)
        bhat=np.linalg.lstsq(X*sw[:,None],y*sw,rcond=1e-12)[0];beta=bhat[-1]
        row=result['estimates'][0];self.assertAlmostEqual(row['estimate_pp'],beta*100,places=10)
        resid=y-X@bhat;bread=np.linalg.pinv((X*sw[:,None]).T@(X*sw[:,None]))
        ifbeta=(X@(bread[:,-1]))*w*resid
        actors=np.column_stack([d['recipient_id'],d['opponent_id'],np.where(d['reached'],d['outcome_opponent'],-1)])
        dep=np.array([[bool(set(a[a>=0])&set(b[b>=0])) for b in actors] for a in actors])
        wanted=ifbeta@dep@ifbeta*(len(y)-1)/(len(y)-X.shape[1])
        if wanted>0:self.assertAlmostEqual(row['standard_error_pp'],math.sqrt(wanted)*100,places=9)
        self.assertEqual(result,mm.fit(self.a,self.root/'run','fixture',source,'overlap'))
        for spec in ('exact_time_control','within_recipient'):
            other=mm.fit(self.a,self.root/'run','fixture',source,spec);self.assertEqual(other['status'],'COMPLETE')
    def test_material_exact_endpoints_both_sides_and_ply(self):
        import chess
        for fen,wanted in [('4k3/8/8/8/8/8/PPPP4/4K3 w - - 0 1',4),('4k3/pppp4/8/8/8/8/8/4K3 w - - 0 1',-4),('4k3/8/8/8/8/8/PPP5/4K3 w - - 0 1',3),('4k3/ppp5/8/8/8/8/8/4K3 w - - 0 1',-3)]:
            value,status=mat.material_from_fen(fen,0);self.assertEqual((value,status),(wanted,'valid'));self.assertEqual(mat.neutral(value),abs(wanted)<4)
        self.assertEqual(mat.material_from_fen(chess.STARTING_FEN,1)[1],'ply_mismatch')
        self.assertEqual(mat.material_from_fen(None,0)[1],'missing_fen')
        self.assertEqual(mat.material_from_fen('8/8/8/8/8/8/8/8 w - - 0 1',0)[1],'invalid_board')
    def test_recent_balance_retains_controls_and_matches_dense_fwl(self):
        sys.path.insert(0,str(ROOT/'frozen_iv/tests'));from test_estimators import fixture
        src,sc=fixture(self.root,n=2400);d=pq.read_table(src).to_pydict();r=np.random.default_rng(64);n=len(d['row_id'])
        d['pre_games_30d']=r.integers(2,150,n);d['recent_fair_90']=r.integers(0,5,n);d['recent_kind_90']=np.minimum(d['recent_fair_90'],r.integers(0,2,n))
        for name in ('disconnect','receipt','claim'):d['recent_'+name+'_90']=r.integers(0,4,n)
        pq.write_table(pa.table(d),src);work=self.root/'recent';work.mkdir();job=rk.job_for(self.root,'recent','recent',src,sc,legacy=True,recent_balance=True,recipient_fe=True);job.update(outcomes=[],iv=False)
        v,g,actors,targets,meta,e=rk.build_buffer(job,work)
        self.assertIn('kind_rate_90',meta['controls']);self.assertIn('log_volume_30',meta['controls']);self.assertEqual(len(targets),8)
        self.assertFalse(set(targets)&set(meta['controls']));self.assertTrue(meta['recipient_fe']);self.assertFalse(meta['balance_without_recipient_history_controls'])
        effects=[]
        for group in g:
            _,code=np.unique(group,return_inverse=True);effects.append(np.eye(code.max()+1)[code])
        width=len(targets);X=np.column_stack(effects+[v[:,width:]])
        want=v[:,:width]-X@np.linalg.lstsq(X,v[:,:width],rcond=1e-12)[0]
        got,rank,diag=rk.project(v.copy(order='F'),g,width,work)
        np.testing.assert_allclose(got,want,atol=3e-7,rtol=3e-7)
    def test_material_fit_and_recent_balance_end_to_end(self):
        sys.path.insert(0,str(ROOT/'frozen_iv/tests'));from test_estimators import fixture
        import model_kernel as kernel, balance
        src,sc=fixture(self.root,n=2400);d=pq.read_table(src).to_pydict();n=len(d['row_id']);rng=np.random.default_rng(712)
        d['pre_games_30d']=rng.integers(2,150,n);d['recent_fair_90']=rng.integers(0,5,n);d['recent_kind_90']=np.minimum(d['recent_fair_90'],rng.integers(0,2,n))
        for name in ('disconnect','receipt','claim'):d['recent_'+name+'_90']=rng.integers(0,4,n)
        pq.write_table(pa.table(d),src)
        parent=self.a.parent;job=kernel.job_for(parent,PARENT_CONF,'legacy_spaced',src,sc,legacy=True);kernel.fit(job)
        panels=[]
        for k in range(24):
            p=self.root/('panel%02d.parquet'%k);take=np.arange(n) if k==6 else np.array([],int)
            t=pa.table(dict(game_id=pa.array([d['game_id'][i] for i in take],type=pa.string()),
              fen_after_last_move=pa.array(['4k3/8/8/8/8/8/PPPP4/4K3 w - - 0 1' if i<100 else '4k3/8/8/8/8/8/PPP5/4K3 w - - 0 1' for i in take],type=pa.string()),
              ply_count=pa.array([0]*len(take),type=pa.int64()),chooser_user_id=pa.array([d['opponent_id'][i] for i in take],type=pa.int64()),disconnected_user_id=pa.array([d['recipient_id'][i] for i in take],type=pa.int64()),
              api_last_move_at_ms=pa.array([d['anchor_ms'][i] for i in take],type=pa.int64()),kind_draw=pa.array([d['received'][i] for i in take],type=pa.bool_()),engine_eval_cp_disconnected=pa.array([0.]*len(take),type=pa.float64())))
            pq.write_table(t,p);panels.append(dict(month=b.MONTHS[k],path=str(p)))
        auth=dict(paths=dict(spaced=str(src),spaced_scores=str(sc),repeated=str(src),repeated_scores=str(sc)),panels=panels)
        run=self.root/'run';mat.run_all(self.a,run,'integration',auth)
        screen=read(run/'report/MATERIAL_SCREEN.json');self.assertEqual(screen['rows_after'],2300)
        self.assertEqual(screen['rows_before'],2400)
        balance.run_all(self.a,run,'integration',auth)
        import csv
        with (run/'report/balance_joint.csv').open() as handle:joint=list(csv.DictReader(handle))
        self.assertEqual(len(joint),3)
        for row in joint:self.assertEqual(row['supported'],'True');self.assertEqual(int(row['df']),7)
        with (run/'report/model_estimates.csv').open() as handle:estimates=list(csv.DictReader(handle))
        for sample in ('spaced_recent_balance','spaced_noenv_recent_balance','repeated_FE_recent_balance'):
            tests=[r for r in estimates if r['sample']==sample];self.assertEqual(len(tests),7)
            ordered=sorted(tests,key=lambda r:float(r['p_value']));previous=0.
            for k,r in enumerate(ordered):
                previous=max(previous,min(1.,(7-k)*float(r['p_value'])))
                self.assertAlmostEqual(previous,float(r['p_Holm']),places=12)
        # Exercise the public manuscript export only after all three families
        # finish; its completion gates must read the actual estimator outputs.
        import paper_export
        mm.run_all(self.a,run,'integration',self.ordinary())
        paper_export.render(run)
        self.assertTrue((run/'report/manuscript_tables/closeout_tables.tex').is_file())
        check=read(run/'report/INTEGRATION_CHECKS.json')
        self.assertTrue(check['manuscript_not_yet_certified'])
        self.assertEqual(set(check['ordinary_largest_smd']),{'overlap','exact_time_control','within_recipient'})

    def test_negative_covariance_is_not_repaired(self):
        result=mm.infer(.01,-1.,[100,100,100],1000)
        self.assertIsNone(result['standard_error_pp']);self.assertNotEqual(result['inference_status'],'nominal_large_sample')
    def test_checkpoint_detects_input_change(self):
        p=self.root/'input.txt';p.write_text('first')
        out,_=stage(self.root/'stage','fixture',lambda tmp:(tmp/'x').write_text('done') and dict(ok=True),[p])
        p.write_text('other')
        with self.assertRaisesRegex(RuntimeError,'changed'):stage(self.root/'stage','fixture',lambda tmp:None,[p])

if __name__=='__main__':unittest.main()
