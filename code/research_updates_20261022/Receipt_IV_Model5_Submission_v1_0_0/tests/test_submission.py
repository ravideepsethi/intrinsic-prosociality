import sys,unittest,tempfile,contextlib,io,zipfile,hashlib,json,csv,os,fcntl
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import supp_core as s
import run_supplements as runner
import finalize_submission as final
import numpy as np
from types import SimpleNamespace
import pyarrow as pa
import pyarrow.parquet as pq
sys.path.insert(0,str(ROOT/'vendor/original/tests'))
from test_uniform90 import synthetic

def quiet():return contextlib.redirect_stdout(io.StringIO())

def dense_residual(base,groups,w):
    # Independent simultaneous dummy-variable weighted least squares, not the
    # alternating projection/FWL implementation being tested.
    blocks=[base[:,6:]]
    for g in groups:
        _,inv=np.unique(g,return_inverse=True);blocks.append(np.eye(inv.max()+1)[inv])
    X=np.column_stack(blocks);sw=np.sqrt(w)
    b=np.linalg.lstsq(sw[:,None]*X,sw[:,None]*base[:,:6],rcond=1e-12)[0]
    return base[:,:6]-X@b

def direct_cov(actors,influence):
    i,j,d=[actors[k] for k in ('recipient_id','opponent_id','date')]
    related=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(d[:,None]==d)
    return influence.T@related@influence

def csv_bytes(rows):
    f=io.StringIO();names=list(dict.fromkeys(k for r in rows for k in r));w=csv.DictWriter(f,fieldnames=names);w.writeheader();w.writerows(rows)
    return f.getvalue().encode()

def parent_public():
    r=dict(sample='uniform_unspaced',term='iv_y',n=s.EXPECTED_N,recipients=s.EXPECTED_PEOPLE,
        row_set_sha256=s.EXPECTED_ROWS,coefficient=.3246734093460897,standard_error=.05641077060922318,
        p_value=8.6e-9,units='percentage points per receipt',supported=True)
    comp=[]
    for sample,outs in [('uniform_F',['analysis_entry_uniform90','recipient_disconnect_main','active_timeout']),('uniform_O',['y','reached'])]:
        for outcome in outs:comp.append(dict(r,sample=sample,term='rf_'+outcome,outcome=outcome,coefficient=.001,standard_error=.003,p_value=.738))
        for trait in s.c.TRAITS90:comp.append(dict(r,sample=sample+'_balance',term='balance_'+trait,outcome=trait,p_Holm_8=1.))
    status=dict(status='COMPLETE',milestone_percent=100,configuration_sha256=s.EXPECTED_CONF,rule=s.c.RULE90,
        receipt_models_complete=True,expanded_entry_and_placebo_complete=True)
    files={'receipt/STATUS.json':json.dumps(status).encode(),'receipt/model_estimates.csv':csv_bytes([r]),
        'receipt/legacy_reproduction.json':b'{"passed":true}',
        'receipt/balance_joint.csv':csv_bytes([dict(sample='uniform_unspaced_balance',supported=True,p_value=3.6e-6)]),
        'receipt/overlap_audit.json':json.dumps(dict(max_exposures_per_repeat_recipient=444,rows_from_repeat_recipients=9008379,
            rows_sharing_a_future_choice=4746043,next_retained_exposure_starts_before_outcome_game=3374050)).encode(),
        'comparisons/model_estimates.csv':csv_bytes(comp),'comparisons/balance_joint.csv':csv_bytes([dict(sample='uniform_F_balance',supported=True,p_value=.5)]),
        'comparisons/receipt_minus_ordinary.csv':b'term,coefficient\nrf_y,.02\n',
        'comparisons/comparison_frame_counts.csv':b'frame,rows\nF,15000000\nO,10000000\n',
        'comparisons/ordinary_equivalence.json':b'{"equivalent":true}'}
    return files

def parent_zip(path,files,corrupt_member=False):
    records=[dict(path=k,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for k,b in files.items()]
    with zipfile.ZipFile(path,'w') as z:
        for k,b in files.items():z.writestr(k,b+(b' ' if corrupt_member and k.endswith('STATUS.json') else b''))
        z.writestr('REPORT_MANIFEST.json',json.dumps(records));z.writestr('run.log','private-path-not-exported')
    path.with_suffix('.zip.sha256').write_text(s.sha(path)+'  '+path.name+'\n')

class Numerics(unittest.TestCase):
    def test_recipient_weights_counts_and_scale(self):
        p=np.array([1,2,2,3,3,3,3]);w,n=s.recipient_weights(p)
        np.testing.assert_array_equal(n,[1,2,4]);np.testing.assert_allclose(w,[1,.5,.5,.25,.25,.25,.25])
        summary,hist,q,t=s.counts_report(n)
        self.assertEqual(summary['rows'],7);self.assertEqual(summary['repeat_recipient_row_share'],6/7)
        self.assertEqual(sum(r['rows'] for r in hist),7);self.assertEqual(q[2]['exposures'],2)
        self.assertEqual(t[0]['rows'],6)

    def test_weighted_FE_FWL_IV_OLS_S5_against_dense_dummy_oracle(self):
        with tempfile.TemporaryDirectory() as td,quiet():
            root=Path(td);src,sc=synthetic(root);design=root/'design'
            s.prepare_design(src,sc,design,False);info=s.load(design/'design.json')
            base=np.memmap(design/'base.dat',dtype='float64',mode='r',shape=(info['n'],info['p']),order='F').copy()
            groups=[np.load(design/f'group{k}.npy') for k in range(3)]
            weights=np.load(design/'weights.npy')
            for weighted in (False,True):
                w=weights if weighted else np.ones(len(base));got=s.project_design(design,root/str(weighted),weighted)
                oracle=dense_residual(base,groups,w);np.testing.assert_allclose(got,oracle,rtol=2e-8,atol=5e-9)
                terms=s.compute_terms(got,w);z,d,y=oracle[:,:3].T
                expected={'first_stage':(w*z)@d/((w*z)@z),'rf_y':(w*z)@y/((w*z)@z),
                    'iv_y':(w*z)@y/((w*z)@d),'ols_y':(w*d)@y/((w*d)@d),
                    's5_mu1':(w*z)@oracle[:,4]/((w*z)@d),'s5_mu0':-((w*z)@oracle[:,5])/((w*z)@d)}
                for t in terms:
                    if t['term'] in expected:self.assertAlmostEqual(t['sign']*t['beta'],expected[t['term']],places=9)
                scaled=s.compute_terms(got,w*7)
                np.testing.assert_allclose(s.influences(got,terms,w),s.influences(got,scaled,w*7),rtol=1e-10,atol=1e-12)
                self.assertAlmostEqual(expected['s5_mu1']-expected['s5_mu0'],expected['iv_y'],places=12)
                # Product outcomes were formed from raw binary variables before projection.
                np.testing.assert_allclose(base[:,4]+base[:,5],base[:,2],atol=0)
                self.assertGreater(np.max(np.abs(oracle[:,4]-oracle[:,1]*oracle[:,2])),.01)

    def test_joint_covariance_matches_pairwise_with_role_overlap_and_duplicates(self):
        with tempfile.TemporaryDirectory() as td,quiet():
            root=Path(td);rng=np.random.default_rng(12);n=80
            i=rng.integers(1,12,n);j=rng.integers(1,12,n);j=np.where(j==i,20,j);d=rng.integers(1,8,n)
            i=np.r_[i,i[:5]];j=np.r_[j,j[:5]];d=np.r_[d,d[:5]];n=len(i)
            actors=dict(row_id=np.arange(n),recipient_id=i,opponent_id=j,date=d)
            vals=rng.normal(size=(n,6));cols=['u_a','u_b','u_c','w_a','w_b','w_c']
            for name,start in [('left',0),('right',3)]:pq.write_table(pa.table(dict(actors,**{cols[k]:vals[:,k] for k in range(start,start+3)})),root/(name+'.parquet'))
            s.merge_influences(root/'left.parquet',root/'right.parquet',root/'joint.parquet')
            got=s.covariance(root/'joint.parquet',cols,root/'cov',buckets=4)
            np.testing.assert_allclose(got,direct_cov(actors,vals),atol=1e-10)
            np.testing.assert_allclose(s.covariance(root/'joint.parquet',cols,root/'cov',buckets=4),got,atol=1e-12)
            bad=pq.read_table(root/'right.parquet').to_pydict();bad['row_id'][0]=-1;pq.write_table(pa.table(bad),root/'bad.parquet')
            with self.assertRaisesRegex(RuntimeError,'align'):s.merge_influences(root/'left.parquet',root/'bad.parquet',root/'out.parquet')

    def test_frozen_baseline_full_fit_and_standard_errors(self):
        with tempfile.TemporaryDirectory() as td,quiet():
            root=Path(td);src,sc=synthetic(root)
            import uniform_models
            job=uniform_models.job_for(root,'test','uniform_unspaced',src,sc)
            s.old.fit(job);ref=s.load(Path(job['output'])/'result.json')
            design=root/'design';s.prepare_design(src,sc,design,False);terms=s.fit(design,root/'fit',False)
            V=s.covariance(root/'fit/influence.parquet',['u_'+t['term'] for t in terms],root/'cov',buckets=4)
            rows=s.result_rows(terms,V,s.load(design/'design.json')['meta'],'test',False)
            self.assertTrue(s.baseline_gate(rows,ref)['passed'])
            bad=[dict(r) for r in rows];bad[0]['coefficient']+=.01
            with self.assertRaisesRegex(RuntimeError,'replay failed'):s.baseline_gate(bad,ref)
            self.assertFalse(s.old.inference90(.1,-1)['supported'])

class Contracts(unittest.TestCase):
    def test_full_runner_final_bundle_and_resume(self):
        with tempfile.TemporaryDirectory() as td,quiet():
            root=Path(td).resolve();src,sc=synthetic(root)
            import uniform_models
            job=uniform_models.job_for(root,'fixture','uniform_unspaced',src,sc);s.old.fit(job)
            baseline=Path(job['output'])/'result.json';ref=s.load(baseline);meta=ref['estimates'][0]
            paths=dict(source=src,scores=sc,baseline=baseline)
            binding=dict(parent_root=str(root/'parent'),project=str(root/'project'),configuration_sha256=s.EXPECTED_CONF,
                inputs={k:dict(path=str(v),sha256=s.sha(v),signature=s.signature(v)) for k,v in paths.items()})
            public=parent_public();public['receipt/model_estimates.csv']=csv_bytes(ref['estimates'])
            people=pq.read_table(src,columns=['recipient_id'])['recipient_id'].to_numpy();_,counts=s.recipient_weights(people)
            public['receipt/overlap_audit.json']=json.dumps(dict(max_exposures_per_repeat_recipient=int(counts.max()),
                rows_from_repeat_recipients=int(counts[counts>1].sum()),rows_sharing_a_future_choice=0,
                next_retained_exposure_starts_before_outcome_game=0)).encode()
            a=SimpleNamespace(parent_root=root/'parent',work_dir=root/'work',result_dir=root/'results',parent_report=None,preflight_only=False)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(runner,'verify_package',return_value='fixture-package'))
                stack.enter_context(patch.object(runner,'authenticate',return_value=binding))
                stack.enter_context(patch.object(final,'wait_parent',return_value=(public,dict(sha256='fixture'))))
                for module in (s,runner,final):
                    for key,value in [('EXPECTED_N',meta['n']),('EXPECTED_PEOPLE',meta['recipients']),('EXPECTED_ROWS',meta['row_set_sha256'])]:
                        stack.enter_context(patch.object(module,key,value))
                self.assertEqual(runner.execute(a),0)
                zips=list(a.result_dir.glob('*_100.zip'));self.assertEqual(len(zips),1)
                with zipfile.ZipFile(zips[0]) as z:
                    status=json.loads(z.read('report/STATUS.json'));self.assertTrue(status['all_agreed_analyses_complete'])
                    self.assertEqual(status['status'],'COMPLETE');self.assertIn('report/tables/main_iv_and_ols.tex',z.namelist())
                    self.assertFalse(any('PRIVATE' in n or n.endswith('.parquet') for n in z.namelist()))
                with patch.object(runner,'fit',side_effect=AssertionError('Completed fits must not rerun')):
                    self.assertEqual(runner.execute(a),0)

    def test_snapshot_is_read_only_with_parent_lock_and_stage_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();parent=root/'parent';parent.mkdir();p=parent/'data';p.write_bytes(b'completed data')
            before=s.signature(p);rec=dict(path=str(p),signature=before,sha256=s.sha(p))
            with (parent/'RUN.lock').open('a+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p.chmod(0o444)
                runner.copy_verified(rec,root/'snapshot')
                self.assertEqual(s.signature(p),before);self.assertEqual(s.sha(p),rec['sha256'])
            with quiet():
                runner.stage(root/'own','conf',lambda tmp:(tmp/'x').write_text('valid'))
                runner.stage(root/'own','conf',lambda tmp:self.fail('Should reuse'))
            (root/'own/x').write_text('bad')
            with self.assertRaisesRegex(RuntimeError,'damaged'):runner.completed(root/'own','conf')

    def test_model_dependency_receipts_authenticate_unstaged_feature_file(self):
        with tempfile.TemporaryDirectory() as td,quiet():
            root=Path(td).resolve();config=dict(version='1.0.0',rule=s.c.RULE90,
                manifest_sha256=s.sha(ROOT/'vendor/original/PACKAGE_MANIFEST.sha256'),project=str(root/'project'))
            conf=s.c.key(config);parent=root/conf[:12];parent.mkdir();s.save(parent/'config.json',config)
            source=parent/'unstaged_source';source.write_bytes(b'source');scores=parent/'scores';scores.write_bytes(b'scores')
            output=parent/'model';ref=dict(estimates=[dict(term='iv_y',n=s.EXPECTED_N,recipients=s.EXPECTED_PEOPLE,
                row_set_sha256=s.EXPECTED_ROWS,coefficient=.3246734093460897,standard_error=.05641077060922318)])
            s.c.stage(output,conf,lambda tmp:s.save(tmp/'result.json',ref),[source,scores])
            job=dict(name='uniform_unspaced',conf=conf,level='X0_ENV_indicator',outcomes=['received','y','reached'],iv=True,input=str(source),scores=str(scores),output=str(output))
            s.save(parent/'PRIVATE/MODEL_PLAN90.json',[job]);s.save(parent/'PRIVATE/STATE.json',dict(receipt_models=dict(status='COMPLETE'),comparison_models=dict(status='RUNNING')))
            s.save(parent/'report/legacy_reproduction.json',dict(passed=True))
            with patch.object(runner,'EXPECTED_CONF',conf):
                binding=runner.authenticate(parent);self.assertEqual(binding['comparison_status'],'RUNNING')
                source.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'differs'):runner.authenticate(parent)

    def test_parent_100_hashes_completeness_and_report_assembly(self):
        with tempfile.TemporaryDirectory() as td,quiet():
            root=Path(td);path=root/'parent.zip';files=parent_public();parent_zip(path,files)
            public,prov=final.verified_parent(path);self.assertNotIn('run.log',public)
            report=root/'report';report.mkdir()
            s.save(report/'recipient_summary.json',dict(rows=s.EXPECTED_N,recipients=s.EXPECTED_PEOPLE,
                max_exposures=444,one_exposure_recipients=727803,repeat_recipient_row_share=9008379/s.EXPECTED_N))
            s.save(report/'baseline_reproduction.json',dict(passed=True))
            for name in ('rows_per_recipient','recipient_quantiles','recipient_thresholds','contrasts'):(report/(name+'.csv')).write_text('test\n')
            row=dict(n=s.EXPECTED_N,recipients=s.EXPECTED_PEOPLE,coefficient=.3,standard_error=.06,p_value=.001,supported=True)
            results=dict(rows=[dict(row,sample='model5_unweighted',term='iv_y'),dict(row,sample='model5_unweighted',term='ols_y'),dict(row,sample='S1_recipient_weighted',term='iv_y')],contrasts=[],
                S5=dict(mu1=dict(coefficient=.01),mu0=dict(coefficient=.007),identity_probability=.003))
            done=final.assemble(report,public,prov,results);self.assertTrue(done['all_agreed_analyses_complete'])
            self.assertTrue((report/'tables/main_iv_and_ols.tex').exists());self.assertIn('joint balance rejects',str(done['interpretation_flags']))
            parent_zip(path,files,True)
            with self.assertRaisesRegex(RuntimeError,'checksum'):final.verified_parent(path)
            status=json.loads(files['receipt/STATUS.json']);status['milestone_percent']=75;files['receipt/STATUS.json']=json.dumps(status).encode();parent_zip(path,files)
            with self.assertRaisesRegex(RuntimeError,'not complete'):final.verified_parent(path)

    def test_cannot_mark_complete_before_parent_report_and_wait_resumes(self):
        with tempfile.TemporaryDirectory() as td,quiet():
            root=Path(td);run=root/'run';run.mkdir()
            with self.assertRaisesRegex(RuntimeError,'Cannot mark'):runner.checkpoint(run,root,100,'COMPLETE')
            path=root/'pending.zip';calls=[]
            with patch.object(final.time,'sleep',side_effect=lambda _:parent_zip(path,parent_public())):
                public,prov=final.wait_parent(path,root,calls.append,interval=0)
            self.assertEqual(len(calls),1);self.assertEqual(prov['configuration_sha256'],s.EXPECTED_CONF)

if __name__=='__main__':unittest.main()
