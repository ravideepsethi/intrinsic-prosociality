"""Independent numerical checks and integrated synthetic Parquet fixtures."""
import sys, tempfile, unittest, json
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from r9b_common import *
import r9b_models as model, r9b_inputs as inp, run_r9b

class NumericalTests(unittest.TestCase):
    def test_sparse_fallback_matches_explicit_dummy_regression(self):
        rng=np.random.default_rng(110);n=280
        groups=[rng.integers(0,22,n),rng.integers(0,17,n)]
        raw=rng.normal(size=(n,5));raw[:,0]+=groups[0]/4;raw[:,2]+=groups[1]/8
        original=raw.copy();v=np.array(raw,dtype=float,order='F',copy=True)
        frozen=model.absorb_owned
        with patch.object(model,'absorb_owned',side_effect=lambda a,g:frozen(a,g,max_iter=2)):
            got,_,info=model.project(v,groups,3)
        X=np.column_stack([np.eye(22)[groups[0]],np.eye(17)[groups[1]],original[:,3:]])
        expected=original[:,:3]-X@np.linalg.lstsq(X,original[:,:3],rcond=None)[0]
        np.testing.assert_allclose(got,expected,atol=2e-9)
        self.assertEqual(info['solver'],'MAP_then_sparse_normalized_LSMR')
    def test_2sls_and_hansen_against_independent_moments(self):
        rng=np.random.default_rng(13);n=2300;z=rng.normal(size=(n,2));d=z@np.array([.3,.7])+rng.normal(size=n)
        y=.4*d+.2*z[:,1]+rng.normal(size=n);meat=lambda a:a.T@a
        b,V,info=multi_iv(y,d,z,meat)
        dhat=z@np.linalg.lstsq(z,d,rcond=None)[0];ref=float(dhat@y)/float(dhat@d)
        influence=dhat*(y-ref*d)/float(dhat@d)
        self.assertAlmostEqual(b[0],ref,12);self.assertAlmostEqual(V[0,0],float(influence@influence),12)
        e=y-ref*d;S=np.einsum('ni,nj,n->ij',z,z,e*e);G=z.T@d;g=z.T@y
        W=np.linalg.inv(S);bg=float(G@W@g/(G@W@G));rr=g-G*bg
        self.assertAlmostEqual(info['Hansen_J']['statistic'],float(rr@W@rr),10)
        self.assertEqual(info['Hansen_J']['df'],1)

    def test_conditional_first_stage_uses_adjusted_residual(self):
        rng=np.random.default_rng(4);z=rng.normal(size=(3500,3));e=rng.normal(size=(3500,3));e[:,1]+=.6*e[:,0]
        d=z@np.array([[1,.5,.3],[.1,.9,.2],[.2,.2,.6]])+e
        got=first_stage_system(d,z,lambda a:np.atleast_2d(a.T@a))
        hat=z@np.linalg.lstsq(z,d,rcond=None)[0];u=d-hat
        for j in range(3):
            rest=[k for k in range(3) if k!=j];h=hat[:,rest]
            delta=np.linalg.lstsq(h,d[:,j],rcond=None)[0]
            _,_,vh=np.linalg.svd(h.T@z,full_matrices=True);direction=z@vh[-1]
            adjusted=u[:,j]-u[:,rest]@delta
            ref=(direction@d[:,j])**2/np.sum((direction*adjusted)**2)
            self.assertAlmostEqual(got[j]['conditional_F'],ref,8)

    def test_shared_covariance_brute_force_OR(self):
        rng=np.random.default_rng(91);n=140;i=rng.integers(0,40,n);j=rng.integers(40,70,n);j[:40]=np.arange(40)
        use=i==j;j[use]=71;dates=rng.integers(0,15,n);h=rng.normal(size=(n,3))
        code=r.stats.cmp.covariance_codes(i,j,dates);got=shared_meat(h,code,True)
        adjacent=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(dates[:,None]==dates)
        np.testing.assert_allclose(got,h.T@adjacent@h,atol=2e-10)

    def test_donor_partition_and_pair_exclusion(self):
        rng=np.random.default_rng(41);n=500;h=dict(j=rng.integers(1,12,n),i=rng.integers(15,40,n),
            t=np.datetime64('2024-03','ms').astype('int64')+rng.integers(0,110*DAY,n),y=rng.integers(0,2,n),cell=rng.integers(0,500,n))
        q=dict(row_id=np.arange(40),opponent_id=rng.integers(1,12,40),recipient_id=rng.integers(15,40,40),month_code=np.full(40,6))
        ref=rng.uniform(.01,.25,size=(2,24,4,4,500));ref[0,5]=np.nan
        for mask in [np.ones(n,bool),h['cell']//100>=2,h['cell']//100<2,np.zeros(n,bool)]:
            hh={k:v[mask] for k,v in h.items()};out,audit=inp.alltime(hh,q,ref)
            for ix in range(40):
                use=(hh['j']==q['opponent_id'][ix])&(hh['i']!=q['recipient_id'][ix]);count=int(use.sum())
                self.assertEqual(out['n'][ix],count);self.assertEqual(out['counterparts'][ix],len(np.unique(hh['i'][use])))
                if count:
                    months=inp.r9_scores.event_month(hh['t'][use]);jf=(r.num.user_hash(hh['j'][use])%4).astype(int)
                    rf=int(r.num.user_hash(q['recipient_id'][ix:ix+1])[0]%np.uint64(4));chosen=np.where(months==5,4,months)
                    expected=np.mean(hh['y'][use]-ref[0,chosen,jf,rf,hh['cell'][use]])
                    self.assertAlmostEqual(out['adjusted'][ix],expected,12)
                else:self.assertTrue(np.isnan(out['adjusted'][ix]))

class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);rng=np.random.default_rng(66);n=6000
        z=rng.normal(0,.05,n);D=(rng.uniform(size=n)<np.clip(.3+2*z,.03,.8)).astype(int)
        y=(rng.uniform(size=n)<.04+.05*D).astype(int)
        d=dict(row_id=np.arange(n),recipient_id=rng.integers(1,1700,n),opponent_id=rng.integers(2000,4000,n),
            month_code=np.full(n,8),tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n,dtype=int),
            archive_start_ms=np.datetime64('2024-07-01','ms').astype('int64')+rng.integers(0,10*DAY,n),
            recipient_rating=rng.normal(1500,160,n),opponent_rating=rng.normal(1500,160,n),
            pre_games_30d=rng.poisson(35,n),received=D,y=y,reached=np.maximum(y,(rng.uniform(size=n)<.7).astype(int)),
            environment_supported=rng.uniform(size=n)>.1,spaced90=np.ones(n,bool),spaced30=np.ones(n,bool),first_recipient=np.ones(n,bool))
        d['anchor_ms']=d['archive_start_ms']+rng.integers(5000,7000000,n)
        d['game_id']=np.array([f'{i:08}' for i in range(n)]);d['complete90']=np.ones(n,bool)
        for days in (30,90):
            d[f'fair_{days}']=rng.poisson(2,n);d[f'kind_{days}']=rng.binomial(d[f'fair_{days}'],.25)
            d[f'receipt_{days}']=rng.poisson(.2,n);d[f'claim_{days}']=rng.poisson(3,n)
            d[f'disconnect_{days}']=d[f'receipt_{days}']+d[f'claim_{days}']
        s=dict(row_id=d['row_id'])
        for tag in ['A','competitive','noncompetitive']:
            for key,values in [('n',rng.integers(6,250,n)),('counterparts',rng.integers(1,6,n)),('expected',rng.uniform(.01,.2,n)),
                ('adjusted',z if tag=='A' else z+rng.normal(0,.03,n))]:s[key+'_'+tag]=values
        for k,v in [('n_7d',s['n_A']),('counterparts_7d',s['counterparts_A']),('expected_7d',s['expected_A']),('adjusted_7d',z)]:d[k]=v
        for key in r.ENV:
            d[key]=rng.uniform(0,1,n);d[key][~d['environment_supported']]=np.nan
        act=dict(row_id=d['row_id'],giver_cost=rng.uniform(1,15,n),recipient_benefit=rng.uniform(1,15,n),giver_rd=rng.uniform(20,150,n),
            recipient_rd=rng.uniform(20,150,n),board_cp=rng.uniform(-100,700,n),ply=rng.integers(2,100,n),giver_clock=rng.uniform(0,200,n),
            recipient_clock=rng.uniform(0,200,n),chooser_color=np.where(rng.uniform(size=n)<.5,'white','black'))
        cls.source=cls.root/'source.parquet';cls.scores=cls.root/'scores.parquet';cls.act=cls.root/'act.parquet'
        for p,data in [(cls.source,d),(cls.scores,s),(cls.act,act)]:pq.write_table(pa.table(data),p,compression='zstd')
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def job(self,**kw):return dict(input=str(self.source),scores=str(self.scores),name='synthetic',level='X0_ENV_indicator',ols=True,**kw)
    def test_primary_matches_frozen_r9_and_OLS_direct(self):
        oldjob=r9_models.make_job(self.source,self.scores,self.root/'old','test','S0','iv','X0_ENV_indicator')
        old,_=r9_models.estimate(oldjob);new=model.estimate(self.job())
        for est,outcome in [('first_stage','received'),('reduced_form','y'),('reduced_form','reached'),('2SLS','y')]:
            a=next(x for x in old['estimates'] if x.get('estimator')==est and x.get('outcome')==outcome)
            b=next(x for x in new['estimates'] if x.get('estimator')==est and x.get('outcome')==outcome)
            for key in ['coefficient','standard_error']:
                self.assertAlmostEqual(a['iv_'+key if est=='2SLS' else key],b[key],10)
        v,groups,ids,meta,targets,extra=model.buffer(self.job());res,_,_=r9_models.project_buffer(v,groups,len(targets))
        y=res[:,targets.index('y')];d=res[:,targets.index('received')]
        got=next(x for x in new['estimates'] if x['estimator']=='OLS')
        self.assertAlmostEqual(got['coefficient'],float(d@y)/float(d@d),12)
    def test_all_fifteen_balance_and_recipient_FE(self):
        ans=model.estimate(self.job(rich=False,balance=True))
        self.assertEqual(len(ans['balance']),15);self.assertEqual(len(ans['joint_balance'][0]['traits']),15)
        self.assertTrue(all(x['multiplicity_family_size']==15 for x in ans['balance']))
        ans=model.estimate(self.job(repeat=True,fe=True,balance=True))
        self.assertEqual(len(ans['balance']),15);self.assertEqual(len(ans['joint_balance'][0]['traits']),7)
    def test_complier_ratio_and_negative_weights(self):
        ans=model.estimate(self.job(kind='compliers'))
        self.assertEqual(len(ans['compliers']),11)
        self.assertTrue(all(x['negative_weight_absolute_mass_over_signed_total']>0 for x in ans['compliers']))
        d=col(self.source,'received');t=col(self.source,'recipient_rating')
        v,groups,ids,meta,targets,extra=model.buffer(self.job(kind='compliers'))
        res,_,_=r9_models.project_buffer(v,groups,len(targets));z=res[:,0]
        got=next(x for x in ans['compliers'] if x['trait']=='recipient_rating')
        self.assertAlmostEqual(got['coefficient'],float(z@(d*t)/(z@d)),6)
    def test_hour_models_and_six_instrument_system(self):
        for hour in ['start','last_move']:
            got=model.estimate(self.job(hour=hour));self.assertEqual(len(got['estimates']),5)
        got=model.estimate(self.job(kind='act',act=str(self.act)))
        self.assertEqual(len(got['first_stages']),6);self.assertEqual(len(got['act_contrasts']),16)
        self.assertTrue(all(x['conditional_residual_adjusted'] for x in got['first_stages']))
        self.assertTrue(all('minimum_conditional_F' in x for x in got['act_contrasts']))
    def test_two_scores_and_supported_subgroup(self):
        got=model.estimate(self.job(kind='two_score',instruments=['competitive','noncompetitive'],support=[['competitive',5],['noncompetitive',5]]))
        self.assertEqual(len(got['first_stages']),3);self.assertEqual(got['system'][0]['Hansen_J']['df'],1)
        got=model.estimate(self.job(subgroup=['month',8]));self.assertEqual(len(got['estimates']),2)
    def test_result_roundtrip_and_resume(self):
        job=self.job(output=str(self.root/'roundtrip'),conf='fixture')
        model.fit_job(job);first=(Path(job['output'])/'result.json').read_bytes();model.fit_job(job)
        self.assertEqual(first,(Path(job['output'])/'result.json').read_bytes())
        self.assertNotIn('AR95',first.decode())

    def test_preparation_and_history_worker_contract(self):
        bound=dict(original=str(self.source),binding=dict(author_ids=[999999,999998]))
        prep=inp.prepare_source(bound,self.root/'prepared_fixture','fixture_preparation',11)
        prepared=prep/'source.parquet';queries=inp.query_shards(prepared,self.root/'shard_fixture','fixture_queries')
        self.assertEqual(sum(pq.ParquetFile(queries/f'{s:02}.parquet').metadata.num_rows for s in range(16)),6000)
        history=self.root/'hist.parquet';future=self.root/'future.parquet'
        pq.write_table(pa.table({k:pa.array([],type=pa.int64()) for k in ['person','t']+list(fast.audit.COUNTS)+['clean_'+k for k in fast.audit.COUNTS]}),history)
        pq.write_table(pa.table({k:pa.array([],type=pa.string() if k=='gid' else pa.bool_() if k=='y' else pa.int64()) for k in ['gid','j','i','t','start','ord','y']}),future)
        job=dict(queries=str(prep/'outcome_00.parquet'),authors=[999999,999998],memory=1.,conf='fixture_history',
            histories=[str(history)],futures=[str(future)],output=str(self.root/'history_fixture'))
        job=cache.attach(job,self.root/'fixture_cache','outcomes',dict(kind='fixture',code={}),0)
        fast.outcome_job(job)
        p=Path(job['output'])/'outcomes.parquet';self.assertTrue(p.exists())
        self.assertEqual(pq.ParquetFile(p).metadata.num_rows,pq.ParquetFile(job['queries']).metadata.num_rows)
        self.assertEqual(int(col(p,'received').sum()) if 'received' in pq.ParquetFile(p).schema_arrow.names else int(col(p,'receipt_90').sum()),0)

    def test_export_is_aggregate_only(self):
        root=self.root/'export_fixture';root.mkdir(exist_ok=True);desktop=self.root/'desktop';desktop.mkdir(exist_ok=True)
        job=self.job()
        job.update(name='primary90',output=str(root/'fits'/'primary90__X0_ENV_indicator'),conf='fixture_export')
        model.fit_job(job)
        run_r9b.export(root,desktop,'fixture_export',50,'PARTIAL_TEST',{},[job])
        import zipfile
        z=zipfile.ZipFile(next(desktop.glob('*.zip')))
        self.assertFalse(any('PRIVATE' in name or 'influence' in name for name in z.namelist()))
        self.assertEqual(len(json.loads(z.read('J1_OLS.json'))),1)
        manifest=json.loads(z.read('REPORT_MANIFEST.json'))
        for entry in manifest:self.assertEqual(hashlib.sha256(z.read(entry['path'])).hexdigest(),entry['sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
