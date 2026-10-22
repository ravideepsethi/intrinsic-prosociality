import unittest,tempfile,sys,contextlib,io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uniform_common as c
import uniform_features as f
import uniform_models as m
import uniform_candidates as candidates
import uniform_comparisons as comp
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

def write(p,data):
    p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.table(data),p);return p

class TemporalTests(unittest.TestCase):
    def test_history_exact_boundaries_absent_people_and_repeated_queries(self):
        D=c.DAY;person=np.array([1,1,1,1,1,2]);t=np.array([9,10,95,99,100,99])*D
        values=np.array([100,1,2,4,1000,8]);qp=np.array([1,1,2,3]);qt=np.array([100,100,100,100])*D
        np.testing.assert_array_equal(f.history90(person,t,values,qp,qt),[7,7,8,0])

    def test_volume_against_brute_force(self):
        rng=np.random.default_rng(8);D=c.DAY
        qp=rng.integers(1,15,200);qt=rng.integers(90,120,200)*D;qp[:3]=1;qt[:3]=100*D
        t=np.r_[rng.integers(0,130,1000)*D,10*D,100*D];w=rng.integers(1,20,len(t));b=w+20;w[-2:]=1
        keys=f.moments(qp,qt);order=np.argsort(keys,kind='stable');delta=np.zeros(len(qp)+1,np.int64)
        f.accumulate90(t,w,b,keys[order],np.unique(qp),delta)
        got=np.empty(len(qp),np.int64);got[order]=np.cumsum(delta[:-1])
        want=np.array([np.sum(((w==p)|(b==p))&(t>=s-90*D)&(t<s)) for p,s in zip(qp,qt)])
        np.testing.assert_array_equal(got,want)

    def test_behavior_worker_authors_timing_and_reused_future_choice(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=int(c.phase_inputs.core.STARTS[0]);start=base+100*c.DAY;anchor=start+100
            q=write(root/'q.parquet',dict(row_id=[1,2,3],game_id=['EXPOSE01','EXPOSE02','EXPOSE03'],recipient_id=[1,1,2],opponent_id=[20,21,30],archive_start_ms=[start,start+10,start],anchor_ms=[anchor,anchor+10,anchor]))
            h=dict(person=[1,1,1,1,2],t=[start-90*c.DAY,start-1,start,start+10,start-1])
            for x in ('fair','kind','disconnect','receipt','claim'):h['clean_'+x]=[1,2,50,100,4]
            hist=write(root/'h.parquet',h)
            future=write(root/'future.parquet',dict(gid=['EARLY001','AUTHOR01','SAMEPAIR','COMMON01','BOUNDARY','TOOLATE1'],j=[1,1,1,1,2,2],i=[88,901,20,89,31,31],t=[anchor+20,anchor+30,anchor+40,anchor+50,anchor+90*c.DAY,anchor+90*c.DAY+1],start=[anchor,anchor+1,anchor+2,anchor+11,anchor+1,anchor+1],ord=[1,2,3,4,5,6],y=[True,True,False,True,True,False]))
            job=dict(queries=str(q),histories=[str(hist)],futures=[str(future)],authors=[901,902],output=str(root/'result'),conf='test90')
            f.behavior_job(job);got=pq.read_table(root/'result/outcomes.parquet').to_pydict()
            self.assertEqual(got['fair_90'],[3,52,4])
            # SAMEPAIR starts before query 2's anchor, so both rows use COMMON01.
            self.assertEqual(got['outcome_gid'],['COMMON01','COMMON01','BOUNDARY'])
            self.assertEqual(got['y'],[True,True,True])
            first=c.sha(root/'result/outcomes.parquet');f.behavior_job(job);self.assertEqual(first,c.sha(root/'result/outcomes.parquet'))
            # Repeated recipient rows may legitimately reuse exactly one outcome.
            qs={k:np.array(v) for k,v in pq.read_table(q).to_pydict().items()};qs['opponent_id'][1]=20
            hh={k:np.array(v) for k,v in pq.read_table(future).to_pydict().items()};mask=hh['i']!=901;hh={k:v[mask] for k,v in hh.items()}
            result=c.fast.sorted_later_outcomes(hh,qs);self.assertEqual(list(result['outcome_gid'][:2]),['COMMON01','COMMON01'])

    def test_volume_worker_resume_and_signature_guard(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);q=r/'q';q.mkdir();D=c.DAY
            keys=f.moments(np.array([1,1]),np.array([100,101])*D)
            for name,v in [('keys',keys),('order',np.array([0,1])),('people',np.array([1]))]:np.save(q/(name+'.npy'),v)
            c.save(q/'meta.json',dict(minimum=100*D,maximum=101*D))
            p=write(r/'chron.parquet',dict(utc_ms=[9*D,10*D,100*D,101*D],white_id=[1]*4,black_id=[2]*4))
            record=dict(path=str(p),signature=c.frozen.r.io.sig(p),rows=4)
            job=dict(record=record,query=str(q),out=str(r/'part.npz'),key='volume90')
            f.volume_job(job)
            with np.load(job['out']) as z:np.testing.assert_array_equal(z['value'],[1,1])
            f.volume_job(job)
            record['signature']=[0,0]
            with self.assertRaisesRegex(RuntimeError,'signature'):f.volume_job(job)

class SelectionTests(unittest.TestCase):
    def test_seven_early_days_are_separate_from_spacing(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);start=int(c.phase_inputs.core.STARTS[0]);days=np.array([89,90,96,97,98,99,100]);n=len(days)
            raw=write(r/'raw.parquet',dict(row_id=list(range(n)),recipient_id=[1,1,2,3,3,901,4],opponent_id=[20]*n,archive_start_ms=start+days*c.DAY,anchor_ms=start+days*c.DAY+100,complete90=[True]*n,spaced30=[False]*n,spaced90=[False]*n,first_recipient=[False]*n))
            old=write(r/'oldflags.parquet',dict(row_id=list(range(n)),supported=[True]*6+[False],observation_complete=days>=97,keep=[False,False,False,True,True,True,False],first_recipient=[False]*n,spaced30=[True]*n,spaced90=[False,True,True,True,False,False,False]))
            legacy=write(r/'legacy.parquet',dict(row_id=[3]))
            b=dict(raw=str(raw),primary=str(legacy),bound={'binding':{'author_ids':[901,902]}})
            a=SimpleNamespace(memory_gb=11)
            with patch.object(c.primary,'build_selection',return_value=old):out=c.receipt_selection(a,r,'select90',b)
            got=pq.read_table(out).to_pydict();self.assertEqual(got['row_id'],[1,2,3,4]);self.assertEqual(sum(got['legacy_primary']),1)
            counts={x['sample']:x['exposures'] for x in c.load(r/'PRIVATE/selection90/counts.json')}
            self.assertEqual(counts['calendar_only_added_unspaced'],2);self.assertEqual(counts['uniform90_unspaced_full_calendar'],4)

    def test_comparison_candidates_remove_cooldown_and_old_prior_support(self):
        with tempfile.TemporaryDirectory() as td,contextlib.redirect_stdout(io.StringIO()):
            r=Path(td);start=int(c.phase_inputs.core.STARTS[0]);n=7
            p=write(r/'ledger.parquet',dict(game_id=[f'GAME{k:04}' for k in range(n)],recipient_id=[1,1,1,2,901,3,4],opponent_id=[20]*n,
                utc_ms=start+np.array([89,90,91,100,100,100,100])*c.DAY,month=['2024-02']*n,recipient_color=['white']*n,
                speed_partition=['blitz']*n,previous_frame=[False]*5+[True,False],n7_author_clean=[0]*n))
            ref=r/'ref';ref.write_text('fixture')
            b=dict(local={'ledgers':[str(p)]},primary={'bound':{'binding':{'author_ids':[901,902]},'reference':str(ref),'parts':[]}})
            a=SimpleNamespace(memory_gb=11,workers=1)
            def fake_score(job):
                q=pq.read_table(job['query']).to_pydict();ids=q['row_id'];write(Path(job['out']),dict(row_id=ids,n_A=[5 if k!=4398046511111 else 4 for k in ids],adjusted_A=[.1]*len(ids),expected_A=[.4]*len(ids)))
            def serial(fn,jobs,workers,label):return [fn(j) for j in jobs]
            with patch.object(c.cache_auth,'FRAME_ROWS',n),patch.object(candidates,'mapped',serial),patch.object(candidates.cutoffs,'donor_job',fake_score):
                candidates.candidates(a,r,'candidate90',b)
            q=pq.read_table(r/'PRIVATE/supported/queries.parquet').to_pydict()
            self.assertEqual(q['game_id'],['GAME0001','GAME0002','GAME0003'])
            self.assertEqual(q['legacy_prior_count'],[0,0,0])
            self.assertEqual(q['at_risk_90'],[True,True,True])

    def test_new_comparison_chronology_scans_and_bounded_merge(self):
        with tempfile.TemporaryDirectory() as td,contextlib.redirect_stdout(io.StringIO()):
            r=Path(td);oldq=r/'oldq';oldx=r/'oldx';base=int(c.phase_inputs.core.STARTS[0]);days=np.array([100,101,102]);ids=np.array([10,11,12])
            qdata=dict(row_id=ids,game_id=['FOCAL001','FOCAL002','FOCAL003'],recipient_id=[1,1,5],opponent_id=[2,3,6],archive_start_ms=base+days*c.DAY,previous_frame=[False]*3)
            query=write(r/'PRIVATE/supported/queries.parquet',qdata)
            write(oldq/'PRIVATE/supported/queries.parquet',{k:np.array(v)[:1] for k,v in qdata.items()})
            write(oldx/'PRIVATE/chronology/features.parquet',dict(row_id=[10],previous_classification_status=['KNOWN'],eligible_main=[True],first_observed_pair=[True],pre_games_30d=[2]))
            chronfile=write(r/'chron.parquet',dict(game_id=['PRIOR001','PRIOR002','PRIOR003','PRIOR004','FOCAL001','FOCAL002','FOCAL003'],
                utc_ms=base+np.array([95,96,97,98,100,101,102])*c.DAY,white_id=[1,3,5,6,1,1,5],black_id=[7,8,9,10,2,3,6]))
            record=dict(path=str(chronfile),signature=c.frozen.r.io.sig(chronfile),rows=7,file_index=0,minimum=base+95*c.DAY,maximum=base+102*c.DAY)
            b=dict(legacy_candidate_run=str(oldq),legacy_chronology_run=str(oldx),source={'chron':[record]})
            def serial(fn,jobs,workers,label):return [fn(j) for j in jobs]
            with patch.object(comp,'mapped',serial):comp.chronology90(SimpleNamespace(memory_gb=11,workers=1),r,'chron90',b)
            out=pq.read_table(r/'PRIVATE/locally_eligible/queries.parquet').to_pydict()
            self.assertEqual(out['row_id'],[10,11,12]);self.assertEqual(out['first_observed_pair'],[True]*3)
            self.assertEqual(c.load(r/'report/chronology90.json')['missing'],2)

    def test_comparison_labels_keep_multiple_receipts_and_ordinary_frame(self):
        import rebuild_frames
        with tempfile.TemporaryDirectory() as td,contextlib.redirect_stdout(io.StringIO()):
            root=Path(td);r=root/'comparison';receipt=root/'receipt';start=int(c.phase_inputs.core.STARTS[0])+150*c.DAY
            games=['MAIN0001','MAIN0002','ORDINARY','NOMAIN01','CHOOSER1'];n=5
            source=write(r/'PRIVATE/metadata_complete/queries.parquet',dict(row_id=[1,2,3,4,5],game_id=games,
                recipient_id=[101,101,102,103,201],opponent_id=[201,202,203,204,104],archive_start_ms=[start+k*1000 for k in range(n)],anchor_ms=[start+100+k*1000 for k in range(n)],
                status=['timeout','timeout','mate','timeout','timeout'],active_timeout=[True,True,False,True,True],ordinary_narrow=[False,False,True,False,False],
                eligible_main=[True]*n,first_observed_pair=[True]*n,tc_base_s=[180]*n,history_window_complete=[True]*n,y=[True,False,True,False,True],reached=[True]*n))
            keys=root/'future';write(keys/'keys.parquet',dict(game_id=['MAIN0001','MAIN0002','CHOOSER1'],i=[101,101,104],j=[201,202,201],fair_competitive=[True]*3,kind_draw=[True,False,True],timeout_chooser_win=[False,True,False]))
            raw=write(root/'raw.parquet',dict(row_id=[10,11,12],game_id=['MAIN0001','MAIN0002','CHOOSER1'],recipient_id=[101,101,104]))
            write(receipt/'PRIVATE/selection90/flags.parquet',dict(row_id=[10,11,12],supported=[True]*3,uniform_keep=[True]*3))
            write(r/'PRIVATE/supported/scores.parquet',dict(row_id=[1,2,3,4,5],n_A=[5]*n,adjusted_A=[.1]*n,expected_A=[.4]*n))
            b=dict(primary={'raw':str(raw),'bound':{'features':{'futures':[str(keys)],'main_conf':'m'}}})
            def serial(fn,jobs,workers,label):return [fn(j) for j in jobs]
            with patch.object(comp.features90,'behavior',side_effect=lambda a,r,c,b,s:s),patch.object(comp.features90,'volume',side_effect=lambda a,r,c,b,s:s),patch.object(comp,'check_stage',side_effect=lambda p,c:p),patch.object(comp,'mapped',serial),patch.object(rebuild_frames,'pool_rates',return_value=root/'dummy'),patch.object(comp.primary,'environment',side_effect=lambda a,r,c,b,s:s):
                comp.frames90(SimpleNamespace(memory_gb=11,workers=1),r,'frames90',b,receipt)
            frame=pq.read_table(r/'PRIVATE/frames90/F.parquet').to_pydict()
            self.assertEqual(frame['analysis_entry_uniform90'],[True,True,False,False,False])
            self.assertEqual(pq.read_table(r/'PRIVATE/frames90/O.parquet').column('game_id').to_pylist(),['ORDINARY'])

def synthetic(root,n=2400):
    rng=np.random.default_rng(42);start=int(c.phase_inputs.core.STARTS[0])+150*c.DAY
    z=rng.normal(0,.08,n);D=rng.random(n)<np.clip(.5+2*z,.05,.95)
    fair=rng.poisson(10,n);kind=np.array([rng.binomial(int(x),.2) for x in fair])
    q=dict(row_id=np.arange(n),recipient_id=rng.integers(1,101,n),opponent_id=rng.integers(501,601,n),received=D,
        y=rng.random(n)<(.1+.07*D),reached=rng.random(n)<.5,recipient_rating=rng.normal(1600,80,n),opponent_rating=rng.normal(1600,80,n),
        month_code=np.zeros(n,np.int64),tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n,np.int64),archive_start_ms=start+rng.integers(0,30*24,n)*3600000,
        fair_90=fair,kind_90=kind,disconnect_90=rng.poisson(4,n),receipt_90=rng.poisson(2,n),claim_90=rng.poisson(2,n),pre_games_30d=rng.poisson(50,n),
        pre_games_90d=rng.poisson(150,n),environment_supported=np.ones(n,bool))
    for name in ('fair','kind','disconnect','receipt','claim'):q[name+'_30']=q[name+'_90']//2
    for name in c.frozen.r.ENV:q[name]=rng.random(n)
    scores=dict(row_id=np.arange(n),n_A=rng.integers(5,100,n),counterparts_A=rng.integers(3,20,n),expected_A=rng.uniform(.2,.8,n),adjusted_A=z)
    return write(root/'source.parquet',q),write(root/'scores.parquet',scores)

class ModelTests(unittest.TestCase):
    def test_design_and_legacy_fit_reproduce_frozen_estimator(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            root=Path(td);src,scores=synthetic(root);job=m.job_for(root,'model90','legacy',src,scores,legacy=True)
            work=root/'matrix';work.mkdir();v,g,actors,targets,meta,events=m.build_buffer(job,work)
            old=c.models.buffer(dict(name='test',input=str(src),scores=str(scores),candidate='all',rich=True,level='X0_ENV_indicator',balance=False,instruments=['A']))
            np.testing.assert_allclose(v,old[0],rtol=1e-12,atol=1e-12)
            for a,b in zip(g,old[1]):np.testing.assert_array_equal(a,b)
            del v,old
            reference=c.iv.iv_fit(src,scores,c.frozen.r.X0+c.frozen.r.ENV+['env_supported'])
            cov=m.covariance
            with patch.object(m,'covariance',side_effect=lambda p,cols,r,mem:cov(p,cols,r,mem,buckets=4)):
                m.fit(job);m.fit(job)
            got={x['term']:x for x in c.load(Path(job['output'])/'result.json')['estimates']}
            for term,field in [('first_stage','first_stage'),('rf_y','reduced_form'),('iv_y','iv')]:
                self.assertAlmostEqual(got[term]['coefficient'],reference[field],places=7)
                self.assertAlmostEqual(got[term]['standard_error'],reference[field+'_se'],places=7)

    def test_uniform_controls_and_nonmechanical_balance(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,scores=synthetic(root)
            for balance in (False,True):
                work=root/str(balance);work.mkdir();job=m.job_for(root,'x','uniform',src,scores,balance=balance)
                v,g,actors,targets,meta,e=m.build_buffer(job,work)
                self.assertNotIn('log_volume_30',meta['controls'])
                if balance:self.assertFalse(set(c.TRAITS90)&set(meta['controls']));self.assertIn('log_volume_90',targets)
                else:self.assertIn('log_volume_90',meta['controls'])
                self.assertTrue(np.isfinite(v).all())

    def test_covariance_matches_pairwise_or_rule_with_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as td,contextlib.redirect_stdout(io.StringIO()):
            r=Path(td);rng=np.random.default_rng(3);n=60
            i=rng.integers(1,7,n);j=rng.integers(11,17,n);dates=rng.integers(1,5,n);score=rng.normal(size=(n,3))
            # Include the same observation twice as happens in stacked contrasts.
            i=np.r_[i,i[:4]];j=np.r_[j,j[:4]];dates=np.r_[dates,dates[:4]];score=np.vstack([score,score[:4]])
            path=write(r/'influence.parquet',dict(recipient_id=i,opponent_id=j,date=dates,a=score[:,0],b=score[:,1],c=score[:,2]))
            related=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(dates[:,None]==dates)
            want=score.T@related@score;got=m.covariance(path,['a','b','c'],r/'cov',.1,buckets=4)
            np.testing.assert_allclose(got,want,atol=1e-10)
            np.testing.assert_allclose(m.covariance(path,['a','b','c'],r/'cov',.1,buckets=4),want,atol=1e-10)

    def test_invalid_variance_is_not_clipped(self):
        self.assertFalse(m.inference90(.2,-1)['supported']);self.assertIsNone(m.inference90(.2,0)['standard_error'])

if __name__=='__main__':unittest.main()
