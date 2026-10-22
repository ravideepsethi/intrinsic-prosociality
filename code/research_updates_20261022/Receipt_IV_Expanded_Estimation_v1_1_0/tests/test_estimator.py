"""Numerical, sampling, provenance and actual pipeline fixtures; no private data."""
import contextlib,io,json,math,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
os.environ['OPENBLAS_NUM_THREADS']='1'
PKG=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PKG/'code'),str(PKG/'vendor')]
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import common,contracts,design,prepare,model,sensitivity,run
import expanded_stats,followup_stats,comparison_core,iv_numerics

def fixture(n=4800,extra=32):
    assert n%2==0 and n>=2400
    rng=np.random.default_rng(18112025);m=n+extra;ix=np.arange(m);people=n//2
    start=np.full(m,1709251200000,dtype=np.int64)+(ix%people%80)*common.DAY
    start[people:n]=1751328000000+(ix[people:n]%20)*common.DAY
    start[n-1200:n-800]=1754784000000+(ix[n-1200:n-800]%5)*common.DAY
    start[n-800:n-400]=1757894400000+(ix[n-800:n-400]%10)*common.DAY
    start[n-400:n]=1764547200000+(ix[n-400:n]%30)*common.DAY
    anchor=start+60000
    anchor[n-800]=design.COLOR_LO-90*common.DAY
    anchor[n-401]=design.MECHANICS_GUARD-90*common.DAY
    anchor[n-402]=design.COLOR_LO
    anchor[n-400]=design.COLOR_HI
    anchor[n:]=design.ENDPOINT-90*common.DAY
    start[[n-800,n-401,n-402,n-400]]=anchor[[n-800,n-401,n-402,n-400]]-60000
    start[n:]=anchor[n:]-60000
    complete=anchor+90*common.DAY<design.ENDPOINT
    z=rng.normal(0,.08,m)
    received=rng.random(m)<np.clip(.3+2*z,.02,.9)
    reached=rng.random(m)<.75
    reached[n-700]=False
    reached[n-450:n-448]=True
    y=(rng.random(m)<(.12+.2*received))&reached
    q=dict(row_id=ix,game_id=np.array([f'g{k:07d}' for k in ix]),recipient_id=ix%people+1,
        opponent_id=rng.integers(10000,13000,m,dtype=np.int64),archive_start_ms=start,anchor_ms=anchor,
        archive_ordinal=ix,received=received,y=y,reached=reached,
        outcome_gid=np.array([f'o{k:07d}' if reached[k] else '' for k in ix]),
        outcome_start=np.where(reached,anchor+common.DAY,-1),outcome_t=np.where(reached,anchor+common.DAY+60000,-1),
        complete90=complete,recipient_rating=rng.integers(1200,1700,m).astype(float),
        opponent_rating=rng.integers(1200,1700,m).astype(float),tc_base_s=np.full(m,180),tc_inc_s=np.zeros(m,int),
        pre_games_30d=rng.poisson(30,m),month_code=np.zeros(m,np.int64),index_color_white=ix%2)
    q['outcome_t'][n-450:n-448]=[design.COLOR_LO,design.COLOR_HI-1]
    q['outcome_start'][n-450:n-448]=q['outcome_t'][n-450:n-448]-60000
    q['outcome_opponent']=np.where(reached,q['opponent_id']+10000,-1)
    for days in (90,30):
        q[f'fair_{days}']=rng.poisson(15,m);q[f'kind_{days}']=rng.binomial(q[f'fair_{days}'],.15)
        q[f'disconnect_{days}']=rng.poisson(6,m);q[f'receipt_{days}']=rng.binomial(q[f'disconnect_{days}'],.2)
        q[f'claim_{days}']=q[f'disconnect_{days}']-q[f'receipt_{days}']
    for lag in (7,30):
        q[f'n_{lag}d']=rng.integers(5 if lag==7 else 0,25,m)
        q[f'adjusted_{lag}d']=z if lag==7 else z+rng.normal(0,.02,m)
        q[f'expected_{lag}d']=rng.uniform(.08,.2,m)
        q[f'counterparts_{lag}d']=np.maximum(q[f'n_{lag}d']-2,0)
    months=np.array([common.dt.datetime.fromtimestamp(t/1000,common.dt.timezone.utc).strftime('%Y-%m') for t in start])
    q['month_code']=np.array([(int(x[:4])-2023)*12+int(x[5:])-11 for x in months])
    phase=np.where(q['outcome_t']<design.COLOR_LO,'pre',
        np.where(q['outcome_t']>=design.COLOR_HI,'post','implementation_bracket'))
    phase=np.where(reached,phase,'no_observed_later_choice')
    later_color=np.where(reached,np.where(ix%3==0,'black','white'),'')
    interaction=np.array([None if not reached[k] or phase[k]=='implementation_bracket'
        else int(later_color[k]=='white' and phase[k]=='post') for k in ix],object)
    source={k:v for k,v in q.items() if k not in ('y','complete90','month_code','index_color_white')}
    source.update(month=months,y_calendar=np.array([y[k] if complete[k] else None for k in ix],object),
        index_chooser_color=np.where(q['index_color_white']==1,'white','black'),
        calendar_primary_7d_floor5=complete,calendar_common5_10=(q['n_7d']>=10)&complete,
        history_window_complete=np.ones(m,bool),complete90_data=complete,
        outcome_membership_ambiguous=np.zeros(m,bool),later_choice_is_identified=reached,
        outcome_color=later_color,later_choice_policy_period=phase,later_white_x_post=interaction,
        support_30d_floor5=q['n_30d']>=5,support_30d_floor10=q['n_30d']>=10)
    pre=(anchor[:n]+90*common.DAY<design.COLOR_LO)
    post=anchor[:n]>=design.COLOR_HI
    expected=dict(first_pair=m,calendar_primary=n,primary=n,common10=int((q['n_7d'][:n]>=10).sum()),
        lag30_common5=int((q['n_30d'][:n]>=5).sum()),
        lag30_common10=int(((q['n_7d'][:n]>=10)&(q['n_30d'][:n]>=10)).sum()),
        reached=int(reached[:n].sum()),nonreached=int((~reached[:n]).sum()),historical=n-1200,
        precolor=int(pre.sum()),color_post=int(post.sum()),color_spanning=int((~pre&~post).sum()),
        mechanics_guard=int((anchor[:n]+90*common.DAY<design.MECHANICS_GUARD).sum()),
        later_post=int((phase[:n]=='post').sum()),later_bracket=int((phase[:n]=='implementation_bracket').sum()))
    return q,source,expected

class Numerics(unittest.TestCase):
    def test_shared_covariance_matches_literal_dependency_graph(self):
        i=np.array([1,2,4,1,6,2]);j=np.array([2,3,5,2,7,4]);date=np.array([1,1,2,3,3,4])
        S=np.arange(18).reshape(6,3)/7-.5
        adjacency=np.array([[bool({i[a],j[a]}&{i[b],j[b]}) or date[a]==date[b] for b in range(6)] for a in range(6)])
        actual=followup_stats.shared_meat(S,comparison_core.covariance_codes(i,j,date))
        np.testing.assert_allclose(actual,S.T@adjacency@S,rtol=1e-12,atol=1e-12)

    def test_inherited_estimator_identity(self):
        q,_,_=fixture();d={k:v[:4800] for k,v in q.items()}
        spec=dict(name='identity',family='iv',sample='primary',lag=7,rich=True,fe=False,repeat=False,balance=True)
        old=expanded_stats.estimate(d,spec);new=model.estimate(d,spec)
        for a,b in zip(old['estimates'],new['estimates']):
            self.assertEqual(a.get('estimator'),b.get('estimator'))
            for k in ('coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp','partial_first_stage_R2'):
                if k in a:self.assertAlmostEqual(a[k],b[k],places=10)
            if 'AR95_intervals_pp' in a:self.assertEqual(a['AR95_intervals_pp'],b['AR95_intervals_pp'])
        for a,b in zip(old['balance'],new['balance']):
            self.assertEqual(a.get('reason'),b.get('reason'))
            if a.get('supported'):self.assertAlmostEqual(a['p_value_asymptotic'],b['p_value_asymptotic'],places=10)

    def test_lag_adapter_changes_only_declared_opponent_history_fields(self):
        q,_,_=fixture();keep=(q['n_30d']>=5)&(q['row_id']<4800)
        d={k:v[keep] for k,v in q.items()};adapted=dict(d)
        for col in ('n','adjusted','expected','counterparts'):adapted[col+'_7d']=d[col+'_30d']
        s=dict(name='lag',sample='lag_common',family='iv',lag=30,rich=True,fe=False,repeat=False,balance=False)
        old=expanded_stats.estimate(adapted,s);new=model.estimate(d,s)
        for a,b in zip(old['estimates'],new['estimates']):
            for k in ('coefficient_pp','iv_coefficient_pp','standard_error_pp','iv_standard_error_pp'):
                if k in a:self.assertAlmostEqual(a[k],b[k],places=10)

    def test_month_color_adjustment_matches_independent_dense_regression(self):
        q,_,_=fixture();d={k:v[:4800] for k,v in q.items()}
        d['index_color_white']=np.random.default_rng(822).integers(0,2,4800)
        spec=dict(name='color_dense',sample='primary',family='iv',lag=7,rich=True,
            fe=False,repeat=False,balance=False,color_month_fe=True)
        fitted={r['estimator']:r for r in model.estimate(d,spec)['estimates']}
        xs,_,_,_,groups,_=expanded_stats.controls(d,True)
        # Independent dummy-matrix construction, not the production FE absorber.
        pairs=np.column_stack([d['month_code'],d['index_color_white']])
        _,pair_codes=np.unique(pairs,axis=0,return_inverse=True)
        columns=list(xs)
        for g in groups+[pair_codes]:
            columns.extend((g==v).astype(float) for v in np.unique(g))
        X=np.column_stack(columns)
        W=np.column_stack([d['adjusted_7d'],d['received'],d['y']]).astype(float)
        z,t,y=(W-X@np.linalg.lstsq(X,W,rcond=1e-11)[0]).T
        self.assertAlmostEqual(fitted['first_stage_per_reference_SD']['coefficient_pp'],
            100*design.REFERENCE_SD*(z@t)/(z@z),places=7)
        self.assertAlmostEqual(fitted['RF_kindness_per_reference_SD']['coefficient_pp'],
            100*design.REFERENCE_SD*(z@y)/(z@z),places=7)
        self.assertAlmostEqual(fitted['2SLS']['iv_coefficient_pp'],100*(z@y)/(z@t),places=7)

    def test_realized_policy_metadata_cannot_change_controls_or_fit(self):
        q,_,_=fixture();d={k:v[:4800] for k,v in q.items()}
        spec=dict(name='no_future_controls',sample='primary',family='iv',lag=7,rich=True,
            fe=False,repeat=False,balance=False,color_month_fe=True)
        before=model.estimate(d,spec)
        changed=dict(d,outcome_color=np.full(4800,'black'),
            later_choice_policy_period=np.full(4800,'post'),later_white_x_post=np.ones(4800))
        after=model.estimate(changed,spec)
        self.assertEqual(before,after)
        self.assertFalse(any('later' in k or 'reached' in k for k in before['design']['continuous_controls']))

    def test_missing_index_color_is_not_filled_from_later_choice(self):
        q,_,_=fixture();d={k:v[:4800] for k,v in q.items() if k!='index_color_white'}
        d['outcome_color']=np.full(4800,'white')
        spec=dict(name='missing_color',sample='primary',family='iv',lag=7,rich=True,
            fe=False,repeat=False,balance=False,color_month_fe=True)
        with self.assertRaisesRegex(RuntimeError,'Assigned index color missing'):
            model.estimate(d,spec)

    def test_bounded_ar_matches_direct_minimization(self):
        rng=np.random.default_rng(32)
        for trial in range(20):
            X=rng.normal(size=(3,3));M=X@X.T*(1 if trial<10 else 500)
            zy,zd,zz=2.,8.,100.;lo,hi=-.04,.04;c=followup_stats.CRIT**2
            intervals=sensitivity.ar_bounded(zy,zd,zz,M,lo,hi)
            A=zz*zz-c*M[2,2]
            for beta in np.linspace(-2,2,401):
                choices=[lo,hi]
                if A>0:
                    g=((zy-beta*zd)*zz-c*(M[0,2]-beta*M[1,2]))/A
                    choices.append(float(np.clip(g,lo,hi)))
                vals=[]
                for g in choices:
                    w=np.array([1.,-beta,-g]);vals.append((zy-beta*zd-g*zz)**2-c*(w@M@w))
                if abs(min(vals))>1e-8:
                    self.assertEqual(min(vals)<=0,any(a<=beta<=b for a,b in intervals))

    def test_bounded_zero_equals_fixed_ar_and_rejects_indefinite(self):
        M=np.diag([3.,4.,5.])
        self.assertEqual(sensitivity.ar_bounded(2,8,100,M,0,0),sensitivity.merge(sensitivity.ar_fixed(2,8,100,M,0)))
        with self.assertRaises(ValueError):sensitivity.ar_bounded(2,8,100,np.diag([3,-1,5]),-.1,.1)

    def test_empty_unbounded_and_disconnected_sets_survive(self):
        self.assertEqual(sensitivity.formatted([[-math.inf,-1],[2,math.inf]]),[['-inf',-100.],[200.,'+inf']])
        self.assertEqual(sensitivity.merge([]),[])
        self.assertEqual(sensitivity.merge([[-math.inf,0],[0,math.inf]]),[[-math.inf,math.inf]])

    def test_tipping_point_uses_new_reduced_form(self):
        rng=np.random.default_rng(123);z=rng.normal(size=500);d=.5*z+rng.normal(size=500);y=.2*d+.01*z+rng.normal(size=500)
        meat=lambda s:s.T@s
        r=sensitivity.compute(y,d,z,meat)
        self.assertTrue(r['supported'])
        t=[x for x in r['fixed'] if x['gamma_pp']==r['point_zero_gamma_pp']][0]
        self.assertAlmostEqual(t['beta_pp'],0,places=10)
        self.assertAlmostEqual(r['point_zero_gamma_pp'],100*design.REFERENCE_SD*(z@y)/(z@z))

class ContractsAndPipeline(unittest.TestCase):
    def test_full_pipeline_authentication_selection_fits_and_resume(self):
        q,s,expected=fixture();n=expected['primary']
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder)/'project';desktop=Path(folder)/'desktop';desktop.mkdir();project.mkdir()
            authdir=Path(folder)/'authority';authdir.mkdir()
            for f in contracts.AUTH.glob('*'):
                if f.is_file(): (authdir/f.name).write_bytes(f.read_bytes())
            summary=common.load(authdir/'reviewed_state_SUMMARY.json')
            summary.update(first_pair_rows=expected['first_pair'],calendar_primary_rows=expected['calendar_primary'],
                calendar_common5_10_rows=int(s['calendar_common5_10'].sum()),primary_RD_rows_restored=0,
                primary_missing_RD_rows=0,primary_nonreachers_retained=expected['nonreached'])
            common.write_json(authdir/'reviewed_state_SUMMARY.json',summary)
            state=project/'derived/replication_36m/receipt_iv_state_diagnostics_v100_PRIVATE';state.mkdir(parents=True)
            paths=[];receipts=[]
            for k in range(16):
                d=state/f'bucket{k:02d}';d.mkdir();p=d/'analysis_enriched_PRIVATE.parquet'
                keep=np.arange(len(s['row_id']))%16==k
                pq.write_table(pa.table({col:val[keep] for col,val in s.items()}),p)
                rr=common.receipt(p);rr['path']=p.name
                common.write_json(d/'_DONE.json',dict(files=[rr],result=dict(rows=int(keep.sum()))))
                paths.append(str(p));receipts.append(contracts.snap(d/'_DONE.json'))
            diag=state/'diagnostics';diag.mkdir();cp=diag/'CUTOFF_SAMPLE_COUNTS.csv'
            cp.write_bytes((authdir/'reviewed_state_CUTOFF_SAMPLE_COUNTS.csv').read_bytes())
            common.write_json(diag/'_DONE.json',dict(result=summary,files=[]))
            mp=state/'ENRICHED_MANIFEST_PRIVATE.json'
            common.write_json(mp,dict(code_signature=contracts.STATE_CODE,account_policy=contracts.ACCOUNT_POLICY,
                analysis_paths=paths,receipts=receipts,diagnostics_root=str(diag),diagnostics_receipt=contracts.snap(diag/'_DONE.json')))
            common.write_json(state/'READY_FOR_IV_SPECIFICATION_PRIVATE.json',dict(status=summary['status'],
                account_policy=contracts.ACCOUNT_POLICY,manifest=str(mp),manifest_receipt=contracts.snap(mp)))
            hp=project/contracts.HISTORICAL_RELATIVE;hp.parent.mkdir(parents=True)
            old={k:v[:expected['historical']].copy() for k,v in q.items()}
            pq.write_table(pa.table(old),hp)
            # In production absolute authorities use /Volumes/XT_Pro. The fixture
            # uses the same receipt chain with its temporary project root.
            with patch.object(common,'ORIGINAL_PROJECT',project),patch.object(contracts,'AUTH',authdir),\
                 patch.dict(design.EXPECTED,expected),patch.object(contracts,'HISTORICAL_SHA',common.sha(hp)),\
                 patch.object(contracts,'HISTORICAL_BYTES',hp.stat().st_size),\
                 patch.object(contracts,'verify_package'),patch.object(model,'check_historical',return_value={'passed':True,'fixture_only':True}):
                with contextlib.redirect_stdout(io.StringIO()):
                    result=run.main(['--project-root',str(project),'--desktop',str(desktop),'--workers','2','--memory-gb','4'])
                if result:
                    errors=list((project/'output').rglob('ERRORS.json'))
                    self.fail('Full pipeline failed: '+str([common.load(p) for p in errors]))
                report=next((project/'output').glob('receipt_iv_expanded_estimation_v110/*'))
                counts=common.load(report/'SAMPLE_ACCOUNTING.json')
                self.assertEqual(counts['primary_rows'],n)
                self.assertEqual(counts['nonreached_rows'],expected['nonreached'])
                self.assertEqual(counts['samples']['later_calendar'],1200)
                self.assertEqual(counts['later_color_bracket_rows'],2)
                self.assertEqual(counts['later_post_color_rows'],expected['later_post'])
                for key in ('precolor','mechanics_guard','color_spanning','color_post'):
                    self.assertEqual(counts['samples'][key],expected[key])
                summary=common.load(report/'SUMMARY.json')
                self.assertEqual(summary['models_completed'],len(design.specifications()))
                self.assertFalse(summary['color_based_primary_censor'])
                accounts=common.load(report/'MODEL_ACCOUNTING.json')
                self.assertEqual(accounts['calendar90_primary']['rows'],n)
                self.assertEqual(accounts['calendar90_primary']['row_set_sha256'],accounts['calendar90_legacy_controls']['row_set_sha256'])
                self.assertEqual(accounts['calendar90_lag_common_7d']['row_set_sha256'],accounts['calendar90_lag_common_30d']['row_set_sha256'])
                selection=next((project/'derived/replication_36m/receipt_iv_expanded_estimation_v110_PRIVATE').rglob('primary_PRIVATE.parquet'))
                saved=pq.read_table(selection,columns=['row_id','y','reached']).to_pydict()
                self.assertEqual(saved['row_id'],list(range(n)))
                self.assertFalse(saved['reached'][n-700])
                self.assertFalse(saved['y'][n-700])
                zip_path=next(desktop.glob('*.zip'))
                with zipfile.ZipFile(zip_path) as z:
                    self.assertIsNone(z.testzip())
                    self.assertFalse(any('PRIVATE' in x for x in z.namelist()))
                with patch.object(model,'estimate',side_effect=AssertionError('Cached models must not be refitted')):
                    with contextlib.redirect_stdout(io.StringIO()):
                        rerun=run.main(['--project-root',str(project),'--desktop',str(desktop),'--workers','2','--memory-gb','4'])
                    self.assertEqual(rerun,0)
                # Byte mutation with unchanged expected receipt is rejected.
                p=Path(paths[0]);p.write_bytes(p.read_bytes()+b'changed')
                with self.assertRaises(RuntimeError):contracts.authenticate(project,project/'mutation_audit')

    def test_historical_gate_checks_estimates_not_only_count(self):
        r=dict(sample_accounting=dict(rows=design.EXPECTED['historical']),estimates=[])
        self.assertFalse(model.check_historical(r)['passed'])

    def test_package_manifest_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'code').mkdir();(p/'vendor').mkdir()
            (p/'code/a.py').write_text('original')
            (p/'PACKAGE_MANIFEST.sha256').write_text(common.sha(p/'code/a.py')+'  code/a.py\n')
            (p/'code/a.py').write_text('changed')
            with patch.object(contracts,'PACKAGE',p):
                with self.assertRaises(RuntimeError):contracts.verify_package()

    def test_stage_reuses_completed_work_but_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);inp=p/'input';inp.write_text('a');snaps=[contracts.snap(inp)]
            def build(tmp):(tmp/'done.txt').write_text('done');return {'n':1}
            common.stage(p/'stage','key',snaps,build,p/'auth')
            common.stage(p/'stage','key',snaps,lambda _:self.fail('Unexpected rerun'),p/'auth')
            inp.write_text('b')
            with self.assertRaises(RuntimeError):common.stage(p/'stage','key',snaps,build,p/'auth')

    def test_private_exports_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);report=p/'report';report.mkdir();(report/'rows_PRIVATE.parquet').write_bytes(b'x')
            with self.assertRaises(RuntimeError):run.export_report(report,p)

if __name__=='__main__':unittest.main()
