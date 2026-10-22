import sys,unittest,tempfile,json,hashlib,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from common import *
import inputs,iv_stats as s,reporting,plots

def fixture(n=6000,seed=17):
    rng=np.random.default_rng(seed);comp=rng.uniform(-.025,.20,n);non=rng.uniform(-.01,.08,n)
    nc=rng.integers(3,40,n);nn=rng.integers(2,60,n);exp=rng.uniform(.01,.03,n)
    pooled=(nc*comp+nn*non)/(nc+nn)
    D=rng.random(n)<(.08+.5*comp+.12*non);R=rng.random(n)<.7
    Y=(rng.random(n)<(.06+.20*D))&R
    ids=np.arange(n)
    d=dict(row_id=ids,recipient_id=ids%1100,opponent_id=2000+ids%450,archive_start_ms=STARTS[3]+(ids%12)*3_600_000,
        month_code=np.full(n,3),tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n),recipient_rating=rng.normal(1500,180,n),
        opponent_rating=rng.normal(1510,180,n),pre_games_30d=rng.integers(1,250,n),y=Y,reached=R,received=D,
        n_7d=nc+nn,adjusted_7d=pooled,expected_7d=exp,counterparts_7d=nc+nn-1,
        comp_n=nc,non_n=nn,comp_z=comp,non_z=non,comp_expected=exp,non_expected=exp,
        comp_counterparts=nc-1,non_counterparts=nn-1,comp_grants=rng.binomial(nc,.08),non_grants=rng.binomial(nn,.02),
        non_clearly_worse_n=nn//2,speed=np.full(n,'blitz'))
    for days in (30,90):
        fair=rng.integers(0,30,n);kind=rng.binomial(fair,.04);dis=rng.integers(0,50,n);rec=rng.binomial(dis,.03)
        d.update({f'fair_{days}':fair,f'kind_{days}':kind,f'disconnect_{days}':dis,f'receipt_{days}':rec,f'claim_{days}':dis-rec})
    return d

class CompetitiveTests(unittest.TestCase):
    def test_heterogeneous_aggregate_parquet_preserves_optional_fields(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            rows=[dict(estimator='supported',estimate=.2),dict(estimator='unsupported',reason='LOW_SUPPORT')]
            tables(p,'results',rows)
            got=io.read(p/'results.parquet').to_pylist()
            self.assertEqual(got[1]['reason'],'LOW_SUPPORT')
            self.assertIsNone(got[0]['reason'])
            self.assertIsNone(got[1]['estimate'])

    def test_shared_covariance_independent_pairwise_oracle(self):
        rng=np.random.default_rng(1);n=45
        i=rng.integers(0,10,n);j=(i+rng.integers(1,10,n))%10;day=rng.integers(0,7,n);v=rng.normal(size=(n,4))
        adjacency=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(day[:,None]==day)
        expected=v.T@adjacency.astype(float)@v
        actual=fs.shared_meat(v,cmp.covariance_codes(i,j,day),True)
        np.testing.assert_allclose(actual,expected,atol=1e-12)

    def test_frozen_controls_match_explicit_dummy_matrix(self):
        d=fixture(600);xs,names,_,_,groups,_=oldstats.controls(d,True)
        Z,ys,_,_,meta=s.design(d,'X0',True,('pooled',))
        X=np.column_stack([np.ones(600)]+xs+[np.eye(int(g.max()+1))[g][:,1:] for g in [np.unique(v,return_inverse=True)[1] for v in groups]])
        T=np.column_stack([d['adjusted_7d'],d['received'],d['y'],d['reached']])
        oracle=T-X@np.linalg.lstsq(X,T,rcond=1e-11)[0]
        actual=np.column_stack([Z['pooled'],ys['received'],ys['y'],ys['reached']])
        np.testing.assert_allclose(actual,oracle,atol=2e-8)
        self.assertEqual(meta['controls'],names)

    def test_split_index_boundary_pair_fold_and_reconstruction(self):
        rng=np.random.default_rng(3);n=500
        cutoff=int(STARTS[4])-7*DAY
        cp=np.resize(np.array([-301,-300,-299,-101,-100,-99,0,100,101,299,300]),n)
        h=dict(j=rng.integers(1,9,n),i=rng.integers(20,40,n),t=cutoff+np.resize([-DAY,-1,0,1,DAY],n),
            y=rng.random(n)<.1,arm=np.ones(n,bool),cell=num.state_cells(cp,np.full(n,20),np.ones(n,int),np.zeros(n)))
        model=rng.uniform(.01,.08,(4,4,500));qj=np.array([1,2,3,4,5,6,7,8,9]);qi=np.array([20,21,22,23,24,25,26,27,28])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);io.table(p/'h.parquet',pa.table(h))
            job=dict(existing=str(p/'absent'),index_conf='fixture',parts=[str(p/'h.parquet')],memory=.5,output=str(p/'index'))
            r=inputs.build_index(job);self.assertFalse(r['reused']);idx=inputs.SplitIndex(r['path'])
            got={tag:idx.score(qj,qi,4,model,tag) for tag in ('all','comp','non','worse')}
            for tag,m in [('all',np.ones(n,bool)),('comp',cp>=-100),('non',cp< -100),('worse',cp<=-300)]:
                v=num.score_month(h['j'][m],h['i'][m],h['t'][m],h['y'][m],h['cell'][m],qj,qi,cutoff,model)
                for k,old in [('n','n'),('z','adjusted'),('expected','expected'),('counterparts','counterparts')]:
                    np.testing.assert_allclose(got[tag][k],v[old],equal_nan=True,atol=1e-13)
            np.testing.assert_array_equal(got['all']['n'],got['comp']['n']+got['non']['n'])
            modelall=np.stack([np.stack([model]*24)]*2);np.save(p/'reference.npy',modelall)
            query=dict(qid=np.arange(8),row_id=np.arange(8),cohort=np.zeros(8,int),opponent_id=qj[:8],recipient_id=qi[:8],month_code=np.full(8,4))
            for k,old in [('n_7d','n'),('adjusted_7d','z'),('expected_7d','expected'),('counterparts_7d','counterparts')]:query[k]=got['all'][old][:8]
            io.table(p/'q.parquet',pa.table(query))
            sj=dict(query=str(p/'q.parquet'),index=r['path'],reference=str(p/'reference.npy'),conf='fixture',output=str(p/'scores'))
            rr=inputs.score_job(sj);self.assertLess(rr['pooled_max_absolute_error'],1e-12)
            self.assertEqual(inputs.score_job(sj),rr)
            with (p/'scores/scores.parquet').open('ab') as f:f.write(b'changed')
            with self.assertRaises(RuntimeError):inputs.score_job(sj)

    def test_2sls_gmm_difference_and_scale_independent_oracle(self):
        rng=np.random.default_rng(7);n=4000;Z=rng.normal(size=(n,2));v=rng.normal(size=n)
        D=Z@np.array([.5,.2])+v;Y=.3*D+.5*v+rng.normal(size=n)
        meat=lambda a:np.atleast_2d(a).T@np.atleast_2d(a) if np.asarray(a).ndim==2 else np.array([[a@a]])
        r=s.joint_iv(Z,D,Y,Y,meat)
        fitted=Z@np.linalg.lstsq(Z,D,rcond=None)[0];b=float(fitted@Y)/(fitted@D)
        self.assertAlmostEqual(r['rows'][0]['estimate'],100*b,10)
        h=fitted*(Y-b*D)/(fitted@D);self.assertAlmostEqual(r['rows'][0]['se'],100*np.sqrt(h@h),10)
        moment=Z*(Y-b*D)[:,None];W=np.linalg.inv(moment.T@moment);a=Z.T@Y;t=Z.T@D
        bg=(t@W@a)/(t@W@t);J=(a-bg*t)@W@(a-bg*t)
        self.assertAlmostEqual(r['GMM_J']['J'],J,10)
        b1=(Z[:,0]@Y)/(Z[:,0]@D);b2=(Z[:,1]@Y)/(Z[:,1]@D)
        infl=Z[:,0]*(Y-b1*D)/(Z[:,0]@D)-Z[:,1]*(Y-b2*D)/(Z[:,1]@D)
        self.assertAlmostEqual(r['component_difference']['se'],100*np.sqrt(infl@infl),10)
        scaled=s.joint_iv(Z*np.array([.3,2]),D,Y,Y,meat)
        self.assertAlmostEqual(scaled['rows'][0]['estimate'],r['rows'][0]['estimate'],10)
        self.assertAlmostEqual(scaled['GMM_J']['J'],r['GMM_J']['J'],10)
        panel=s.scalar_panel(Z[:,0],D,Y,Y,meat,.2)
        fsr=next(x for x in panel['rows'] if x['estimator']=='First stage: receipt' and 'reference' in x['units'])
        ols=next(x for x in panel['rows'] if x['estimator']=='Same-row OLS')
        implied=next(x for x in panel['rows'] if x['estimator'].startswith('OLS-implied') and 'reference' in x['units'])
        self.assertAlmostEqual(implied['estimate'],fsr['estimate']*ols['estimate']/100,12)

    def test_ar_full_real_line_inversion_and_weak_tails(self):
        rng=np.random.default_rng(91);n=2000;Z=rng.normal(size=(n,2));D=.3*Z[:,0]+rng.normal(size=n);Y=.4*D+rng.normal(size=n)
        meat=lambda a:a.T@a
        ar=s.ar_two(Z,Y,D,meat);self.assertTrue(ar['supported'])
        def contains(ar,b):
            return any(((-math.inf if x['low_pp']=='-inf' else x['low_pp']/100)<=b<= (math.inf if x['high_pp']=='+inf' else x['high_pp']/100)) for x in ar['intervals'])
        for b in np.linspace(-2,2,151):
            m=Z*(Y-b*D)[:,None];g=m.sum(0);truth=g@np.linalg.solve(m.T@m,g)<=-2*np.log(.05)
            self.assertEqual(contains(ar,b),truth)
        weakD=D-Z@np.linalg.lstsq(Z,D,rcond=None)[0]
        weak=s.ar_two(Z,Y,weakD,meat);self.assertTrue(weak['unbounded'])
        self.assertTrue(contains(weak,1e8));self.assertTrue(contains(weak,-1e8))
        invalid=s.ar_two(Z,Y,D,lambda a:-(a.T@a));self.assertFalse(invalid['supported'])
        collinear=s.joint_iv(np.column_stack([Z[:,0],Z[:,0]]),D,Y,Y,meat)
        self.assertFalse(collinear['supported'])

    def test_common_row_controls_reference_scaling_and_tied_bins(self):
        d=fixture(5000);keep=d['comp_n']>=5;d=subset(d,keep)
        r=s.run_model(d,'S1','XC');self.assertEqual(r['n'],len(d['row_id']))
        self.assertEqual(set(r['footers']),{'pooled','comp'})
        for tag in ('pooled','comp'):
            raw=next(x for x in r['rows'] if x.get('instrument')==tag and x['estimator']=='First stage: receipt' and x['units']=='pp per raw score unit')
            sd=next(x for x in r['rows'] if x.get('instrument')==tag and x['estimator']=='First stage: receipt' and x['units']=='pp per reference residual SD')
            self.assertAlmostEqual(sd['estimate'],raw['estimate']*r['native_sds'][tag],12)
        z=np.r_[np.zeros(990),np.ones(10)];D=np.arange(1000)%2
        bins=s.bins(z,D,lambda a:np.array([[a@a]]),'comp')
        self.assertEqual(sum(x['n'] for x in bins),1000);self.assertTrue(all(x['n']>0 for x in bins))

    def test_parquet_pipeline_spawn_reports_and_resume(self):
        d=fixture(6000);p={k:v.copy() for k,v in d.items() if k not in ('received','speed')}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);assembled=root/'assembled';assembled.mkdir()
            io.table(assembled/'iv.parquet',pa.table(d));io.table(assembled/'placebo.parquet',pa.table(p))
            before=io.sha(assembled/'iv.parquet');reporting.descriptive(assembled,root/'descriptive','test')
            perf=[];jobs=[dict(module='iv_stats',function='model_job',input=str(assembled/'iv.parquet'),where=reporting.FILTERS[sample],
                output=str(root/'models'/(sample+'_'+family)),conf='test',sample=sample,family=family,memory=.5)
                for sample,family in [('S1','XC'),('S2','X0')]]
            results=mapped(jobs,2,'Synthetic integration',perf)
            for j,r in zip(jobs,results):self.assertEqual(s.model_job(j),r)
            # Finish every other statistical run with the same actual job entry points.
            refs=results[0]['native_sds'];rest=[]
            for sample,family,rich,bal in [('S2','XC',True,False),('S1','X0',True,False),('S1_3','XC',True,False),
                ('P1','XC',True,False),('S1','XC',False,True),('S2','XC',False,True)]:
                job=dict(module='iv_stats',function='model_job',input=str(assembled/('placebo.parquet' if sample=='P1' else 'iv.parquet')),
                    where=reporting.FILTERS['S1' if sample=='P1' else sample],output=str(root/'more'/(sample+family+str(rich))),
                    conf='test',sample=sample,family=family,rich=rich,balance_only=bal,reference_sds=refs,memory=.5)
                rest.append(s.model_job(job))
            results+=rest
            sj=dict(input=str(assembled/'iv.parquet'),output=str(root/'subgroup'),conf='test',reference_sd=refs['comp'],memory=.5,
                spec=dict(dimension='speed',label='blitz',where="speed='blitz'"))
            subgroup=s.subgroup_job(sj)
            dest=reporting.export(root,root/'desktop','f'*64,results,subgroup,perf,'SYNTHETIC_COMPLETE',time.monotonic())
            with zipfile.ZipFile(dest) as z:
                self.assertIsNone(z.testzip());manifest=json.loads(z.read('REPORT_MANIFEST.json'))
                for f in manifest:self.assertEqual(hashlib.sha256(z.read(f['path'])).hexdigest(),f['sha256'])
                self.assertTrue(any(n.endswith('.png') for n in z.namelist()))
                self.assertFalse(any('PRIVATE' in n for n in z.namelist()))
                self.assertTrue({'03_runA.csv','03_runB.csv','03_runC.csv','03_runD.csv','05_runF_balance.csv','06_runG_placebo.csv','07_runH_firststage_both.csv','08_runI_subgroups.csv'}<=set(z.namelist()))
            self.assertEqual(before,io.sha(assembled/'iv.parquet'))
            self.assertEqual(perf[0]['workers'],2)

    def test_missing_private_production_input_stops(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError,'PRIVATE_PRODUCTION_INPUTS_NOT_AVAILABLE'):inputs.authenticate(Path(td),2)

    def test_preparation_reproduction_and_role_safe_assembly(self):
        d=fixture(2500);d['archive_start_ms']=STARTS[4]+np.arange(2500)%12*3_600_000;d['month_code'][:]=4
        original={k:v.copy() for k,v in d.items() if k not in SPLIT_COLS}
        p={k:v.copy() for k,v in original.items() if k not in ('received','speed')}
        for name in ('eligible_main','history_complete','first_observed_pair','at_risk_90','ordinary_narrow','complete90'):p[name]=np.ones(2500,bool)
        expected=[]
        for name,family,values in [('main90_pooled','iv',original),('ordinary90_placebo','ordinary',p)]:
            expected+=oldstats.estimate(values,dict(name=name,family=family,rich=True,repeat=False,fe=False,balance=False))['estimates']
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);io.table(root/'source.parquet',pa.table(original));io.table(root/'comparison.parquet',pa.table(p))
            source=dict(spaced=str(root/'source.parquet'),comparison=str(root/'comparison.parquet'))
            prepared,info=inputs.prepare(source,root/'prepared','test',expected)
            self.assertEqual(info['iv_rows'],2500);self.assertEqual(info['placebo_rows'],2500)
            self.assertEqual(io.load(prepared/'reproduction.json')['status'],'ORIGINAL_IV_AND_PLACEBO_REPRODUCED')
            q=dict(qid=np.arange(5000),row_id=np.r_[d['row_id'],d['row_id']],cohort=np.r_[np.zeros(2500,int),np.ones(2500,int)])
            for k in SPLIT_COLS:q[k]=np.r_[d[k],d[k]]
            io.table(root/'scores.parquet',pa.table(q));assembled,_=inputs.assemble(prepared,[str(root/'scores.parquet')],root/'assembled','test',.5)
            out=arrays(io.read(assembled/'iv.parquet'))
            for k,v in original.items():np.testing.assert_array_equal(out[k],v)
            self.assertEqual(pq.ParquetFile(assembled/'placebo.parquet').metadata.num_rows,2500)
            altered=subset(original,np.arange(2499))
            with self.assertRaises(RuntimeError):inputs.reproduce(altered,'main90_pooled',expected)

if __name__=='__main__':unittest.main()
