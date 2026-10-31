import sys,os,tempfile,unittest,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
import decision_inputs,exposures,features,models,model_kernel
from types import SimpleNamespace

class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.a=SimpleNamespace(workers=1,memory_gb=4.)
    def tearDown(self):self.temp.cleanup()
    def file(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.table(data),p,compression='zstd');return p
    def test_projection_adds_new_arm_preserves_anomaly_and_drops_event(self):
        start=int(c.phase_inputs.core.STARTS[1]);n=5
        orig=self.file('old.parquet',dict(j=[10]*n,i=[20,21,22,23,24],t=np.arange(n)+start,start=np.arange(n)+start-1,ord=np.arange(n),gid=['g000000'+str(k) for k in range(n)],y=[0,0,0,1,0],arm=[True,True,False,True,False],fair=[True]*n,rt=[True]*n,cell=[202]*n))
        keep=[0,2,3,4]
        material=self.file('m.parquet',dict(game_id=['g000000'+str(k) for k in keep],chooser_user_id=[10]*4,disconnected_user_id=[20+k for k in keep],api_last_move_at_ms=np.array(keep)+start,utc_ms=np.array(keep)+start-1,archive_ordinal=keep,kind_draw=[False,True,True,False],timeout_chooser_win=[True,False,False,False],fair_competitive=[True]*4,engine_eval_cp_disconnected=[0.]*4,ply_count=[5.]*4,disconnected_elo=[1500.]*4,chooser_elo=[1500.]*4))
        job=dict(material=str(material),rows=4,old=[dict(path=str(orig))],authors=[99,100],out=str(self.root/'project'),memory=1.,conf='test')
        result=decision_inputs.project_job(job)
        db=connect(self.root,1.)
        try:
            t=db.execute('SELECT gid,y,arm FROM '+c.parq(sorted((self.root/'project').glob('[0-9][0-9].parquet')))+' ORDER BY gid').fetchall()
            self.assertEqual(t,[('g0000000',False,True),('g0000002',True,True),('g0000003',True,True),('g0000004',False,False)])
        finally:db.close()
        self.assertEqual(rows(self.root/'project/removed.parquet'),1)
        self.assertEqual(rows(self.root/'project/relabeled.parquet'),1)
        decision_inputs.project_job(job) # sealed resume
        with material.open('ab') as f:f.write(b'x')
        with self.assertRaises(RuntimeError):decision_inputs.project_job(job)
    def test_reference_excludes_each_focal_fold_in_both_roles(self):
        n=np.zeros((1,2,4,4,2),np.int64);y=np.zeros_like(n)
        for j in range(4):
            for i in range(4):n[0,0,j,i]=[10,20];y[0,0,j,i]=[j,i]
        out=c.frozen.r.num.expanding_reference(n,y)
        keep=[2,3];nn=np.array([40,80]);ss=np.array([10,10]);pg=(ss.sum()+.5)/(nn.sum()+1)
        np.testing.assert_allclose(out[0,1,0,1],(ss+50*pg)/(nn+50))
        y2=y.copy();y2[0,0,0,:,:]=9;y2[0,0,:,1,:]=9
        np.testing.assert_allclose(c.frozen.r.num.expanding_reference(n,y2)[0,:,0,1],out[0,:,0,1])
    def test_alltime_new_donor_crosses_five_and_pair_never_counts(self):
        ref=np.full((2,24,4,4,500),.1);start=int(c.phase_inputs.core.STARTS[2]);q=dict(row_id=np.array([0]),recipient_id=np.array([22]),opponent_id=np.array([10]),month_code=np.array([2]))
        h=dict(j=np.array([10]*7),i=np.array([22,22,31,32,33,34,35]),t=np.arange(7)+start,y=np.array([1,1,0,0,0,0,1]),cell=np.array([202]*7))
        score,_=c.inputs.alltime(h,q,ref)
        self.assertEqual(score['n'][0],5);self.assertAlmostEqual(score['adjusted'][0],.1)
        before={k:v[:-1] for k,v in h.items()};old,_=c.inputs.alltime(before,q,ref);self.assertEqual(old['n'][0],4)
    def test_window_endpoints_and_next_choice_change(self):
        start=int(c.phase_inputs.core.STARTS[4]);anchor=start+1000
        q=self.file('query.parquet',dict(row_id=[0],game_id=['exposure'],recipient_id=[1],opponent_id=[2],archive_start_ms=[start],anchor_ms=[anchor]))
        times=np.array([start-97*DAY,start-90*DAY,start-7*DAY,start-1,start],np.int64)
        h=self.file('hist.parquet',dict(person=[1]*5,t=times,**{'clean_'+x:np.ones(5,np.int64) for x in ('fair','kind','disconnect','receipt','claim')}))
        f=self.file('future.parquet',dict(gid=['samepair','startedx','good0001','good0002'],j=[1]*4,i=[2,3,4,5],t=[anchor+1,anchor+2,anchor+3,anchor+4],start=[anchor+1,anchor-1,anchor+1,anchor+1],ord=[0,1,2,3],y=[True,True,False,True]))
        job=dict(queries=str(q),histories=[str(h)],futures=[str(f)],conf='windows',output=str(self.root/'out'))
        features.history_job(job);t=pq.read_table(self.root/'out/outcomes.parquet').to_pydict()
        self.assertEqual(t['fair_90'],[3]);self.assertEqual(t['legacy_fair_90'],[2]);self.assertEqual(t['recent_fair_90'],[0]);self.assertEqual(t['outcome_gid'],['good0001']);self.assertEqual(t['y'],[False])
        # Removing that decision changes the first later decision, not just Y's
        # label on a frozen endpoint.
        ft=pq.read_table(f);new=self.root/'new_future.parquet';pq.write_table(ft.filter(pa.array([True,True,False,True])),new)
        job.update(futures=[str(new)],output=str(self.root/'newout'));features.history_job(job)
        self.assertEqual(pq.read_table(self.root/'newout/outcomes.parquet')['y'].to_pylist(),[True])
    def test_spacing_precedes_followup_cut_and_can_admit_successor(self):
        person=np.array([1,1,1]);starts=np.array([100,100+30*DAY,100+100*DAY]);anchor=starts+10
        flags=c.primary.spacing_flags(person,starts,anchor,np.array([True,True,True]))
        self.assertEqual(flags['spaced90'].tolist(),[True,False,True])
        changed=c.primary.spacing_flags(person,starts,anchor,np.array([False,True,True]))
        self.assertEqual(changed['spaced90'].tolist(),[False,True,False])
        # An incomplete first row still starts the spacing window before cuts.
        self.assertEqual((flags['spaced90']&np.array([False,True,True])).tolist(),[False,False,True])
    def test_selection_three_and_five_preserve_row_alignment(self):
        start=int(c.phase_inputs.core.STARTS[5]);raw=self.file('raw.parquet',dict(row_id=[0,1,2,3],game_id=['a','b','c','d'],recipient_id=[1,1,2,3],opponent_id=[4,5,6,7],archive_start_ms=[start,start+DAY,start,start],anchor_ms=[start+1,start+DAY+1,start+1,start+1],complete90=[True]*4,history_window_complete=[True]*4,history90_complete=[True]*4,first_recipient=[True,False,True,True]))
        score=self.file('scores.parquet',dict(row_id=[0,1,2,3],n_A=[3,5,10,20],adjusted_A=[.1]*4,expected_A=[.1]*4,counterparts_A=[3,5,10,20]))
        src,sc=exposures.selection(self.a,self.root/'run','sel',raw,score)
        t=pq.read_table(src).to_pydict();self.assertEqual(t['row_id'],[0,1,2,3]);self.assertEqual(t['uniform_keep'],[False,True,True,True]);self.assertEqual(t['spaced90_n3'],[True,False,True,True]);self.assertEqual(t['spaced90_n5'],[False,True,True,True])
        np.testing.assert_array_equal(pq.read_table(src)['row_id'],pq.read_table(sc)['row_id'])
    def test_legacy_model_uses_own_history_and_score_controls(self):
        raw=self.file('source.parquet',dict(row_id=[0,1],pre_games_30d=[2,3],**{x+'_90':[99,98] for x in ('fair','kind','disconnect','receipt','claim')},**{'legacy_'+x+'_90':[7,8] for x in ('fair','kind','disconnect','receipt','claim')}))
        sc=self.file('s.parquet',dict(row_id=[0,1],n_B=[5,6],counterparts_B=[4,5],expected_B=[.02,.03],adjusted_B=[.04,.05]))
        a,b=models.sample(self.a,self.root/'r','own',raw,sc,'before',score='B',legacy=True)
        self.assertEqual(pq.read_table(a)['fair_90'].to_pylist(),[7,8]);self.assertEqual(pq.read_table(b)['n_A'].to_pylist(),[5,6])
    def test_first_flag_precedes_arm_and_observation(self):
        db=connect(self.root,1.);base=int(c.phase_inputs.core.STARTS[4])
        data=dict(game_id=['b','a','c'],chooser_user_id=[2,2,3],disconnected_user_id=[1,1,1],utc_ms=[base,base,base+1],api_last_move_at_ms=[base+2,base+2,base+2],archive_ordinal=[1,0,2],kind_draw=[False,False,True],timeout_chooser_win=[True,False,False],api_speed=['blitz']*3,tc_base_s=[300]*3,tc_inc_s=[0]*3,disconnected_elo=[1500.]*3,chooser_elo=[1500.]*3,disconnected_pre_rd_v2=[50.]*3,chooser_pre_rd_v2=[50.]*3,month=['2024-03']*3,fair_competitive=[True]*3,tournament_like_event=[False]*3)
        db.register('m',pa.table(data));d=db.execute(exposures.audit_logic.exposure_sql('m')).fetchdf();db.close()
        self.assertEqual(d.loc[d.first_recipient,'game_id'].tolist(),['a']);self.assertFalse(bool(d.loc[d.first_recipient,'arm_eligible'].iloc[0]))
    def test_full_scores_oracle_before_after_and_cross_state(self):
        start=int(c.phase_inputs.core.STARTS[3]);h=self.file('h.parquet',dict(j=np.array([10]*10),i=np.arange(20,30),t=start+np.arange(10),y=np.arange(10)%2==0,arm=[True]*10,cell=[202]*5+[2]*5))
        q=self.file('q.parquet',dict(row_id=[0],recipient_id=[21],opponent_id=[10],month_code=[3],archive_start_ms=[start+4],anchor_ms=[start+6]))
        ref=self.root/'reference.npy';np.save(ref,np.full((2,24,4,4,500),.1))
        exposures.score_job(dict(query=str(q),parts=[dict(path=str(h))],reference=str(ref),conf='scores',out=str(self.root/'sc')))
        t=pq.read_table(self.root/'sc/scores.parquet').to_pydict()
        self.assertEqual(t['n_A'],[9]);self.assertEqual(t['n_B'],[3]);self.assertEqual(t['n_C'],[3]);self.assertEqual(t['n_competitive'],[4]);self.assertEqual(t['n_noncompetitive'],[5])

if __name__=='__main__':unittest.main()
