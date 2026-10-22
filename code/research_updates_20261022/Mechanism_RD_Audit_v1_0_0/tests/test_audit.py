import itertools,tempfile,unittest
from fixture import *
from inputs import prepare_state,authenticate_source
from analysis import evaluate,score_diagnostics,coefficient_rows
from stats import groups,conditional_kernel,conditional_value
from design import design,MODELS
from reporting import score_comparisons,training_comparisons,repair_original_counts,collapsed_curves

class AuditTests(unittest.TestCase):
    def test_exact_conditional_probabilities(self):
        eta=np.array([-.7,.4,.9,1.2]);y=np.array([0.,1.,0.,1.])
        ll,r=conditional_kernel(eta,y,np.array([0]),np.array([4]))
        outcomes=np.array([a for a in itertools.product([0.,1.],repeat=4) if sum(a)==2])
        weights=np.exp(outcomes@eta);weights/=weights.sum()
        self.assertAlmostEqual(ll[0],np.log(weights[np.all(outcomes==y,axis=1)][0]),places=12)
        np.testing.assert_allclose(y-r,weights@outcomes,atol=1e-12)

    def test_preparation_restriction_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);d=fixture(25);src=p/'source.parquet';frame(d,src);before=sha(src)
            result=prepare_state([src],'equal',p/'work',p/'report','synthetic-key',2,256)
            capped=d[d.regular & d.rd.le(110) & d.opp_rd.le(110)]
            self.assertEqual(result['cohorts']['rd110']['meta']['n'],len(capped))
            self.assertEqual(result['cohorts']['original']['meta']['n'],int(d.regular.sum()))
            for cohort,c in result['cohorts'].items():
                for f in c['folds']:
                    train=pd.read_parquet(f['train_path']);test=pd.read_parquet(f['test_path'])
                    self.assertTrue(train.month.le(f['train_end']).all())
                    self.assertTrue(test.month.between(f['test_start'],f['test_end']).all())
                    a=test.groupby(['chooser','month']).y.agg(['sum','count'])
                    self.assertTrue(((a['sum']>0)&(a['sum']<a['count'])).all())
                    self.assertGreater(len(a),0)
                    if cohort=='rd110':self.assertTrue((test.rd.le(110)&test.opp_rd.le(110)).all())
            stamps={f['path']:Path(f['path']).stat().st_mtime_ns for f in result['files']}
            self.assertEqual(result,prepare_state([src],'equal',p/'work',p/'report','synthetic-key',2,256))
            self.assertEqual(stamps,{f:Path(f).stat().st_mtime_ns for f in stamps})
            self.assertEqual(before,sha(src))
            with self.assertRaisesRegex(RuntimeError,'inputs changed'):
                prepare_state([src],'equal',p/'work',p/'report','wrong-key',2,256)

    def test_cached_receipt_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'source';d=fixture(4)
            write(source/'RUN_IDENTITY.json',dict(package_sha256='source-code'))
            for month,x in d.groupby('month'):
                f=source/'analysis'/(month+'.parquet');frame(x,f);done(f,'fixture')
            paths,ledger=authenticate_source(source,p/'work',dict(source_package_sha256='source-code'))
            self.assertEqual(len(paths),24);self.assertEqual(len(ledger),24)
            with open(paths[0],'ab') as f:f.write(b'tamper')
            with self.assertRaisesRegex(RuntimeError,'Input size differs'):
                authenticate_source(source,p/'work',dict(source_package_sha256='source-code'))

    def test_scoring_and_rd_score_partition(self):
        d=fixture(20);X,names,_=design(d,'strength');b=np.zeros(X.shape[1]);b[names.index('strength_3')]=.2
        f=dict(status='ESTIMATED',model='strength',curvature=.5,names=names,beta=b)
        allrows,cal=evaluate(informative(d),f,metadata(d))
        expected=0
        for month,x in d.groupby('month'):
            xx,_,_=design(x,'strength');expected+=conditional_value(xx,x.y,x.chooser,b)
        self.assertAlmostEqual(sum(x['loglik'] for x in allrows),expected,places=9)
        c=pd.DataFrame(cal);self.assertAlmostEqual(c.observed_grants.sum(),c.predicted_grants.sum(),places=8)
        f.update(n=len(d),grants=int(d.y.sum()),accounts=d.chooser.nunique(),loglik=conditional_value(X,d.y,d.chooser,b))
        diag=pd.DataFrame(score_diagnostics(d,f))
        order,st,en=groups(d.chooser);_,res=conditional_kernel(X[order]@b,d.y.to_numpy(float)[order],st,en)
        for term,z in diag.groupby('term'):
            self.assertAlmostEqual(z.signed_score.sum(),X[order,names.index(term)]@res,places=8)
            if z.centered_regressor_ss.sum()>0:self.assertAlmostEqual(z.centered_regressor_ss_share.sum(),1,places=9)
            if z.absolute_row_score.sum()>0:self.assertAlmostEqual(z.absolute_row_score_share.sum(),1,places=9)

    def test_fit_failure_preserves_common_support(self):
        d=fixture(5);d=d[d.month.ge('2024-11')];meta=metadata(d)
        labels=dict(state='equal',fold=0)
        fail=dict(status='OPTIMIZER_NOT_CONVERGED',model='cost')
        a,_=evaluate(d,fail,meta,comparison='original_train_rd110_test',**labels)
        b,_=evaluate(d,fail,meta,comparison='rd110_train_rd110_test',**labels)
        scores=pd.DataFrame(a+b);j,s=training_comparisons(scores)
        self.assertTrue(j.refitting_gain.isna().all());self.assertTrue(s.mean_month_gain.isna().all())
        rows,status=score_comparisons(scores)
        self.assertEqual(rows,[]);self.assertTrue(all(x['status']=='FIT_FAILURE' for x in status))

    def test_zero_information_does_not_select(self):
        rows=[]
        for m in MODELS:
            for month in MONTHS[-12:]:rows.append(dict(state='equal',comparison='toy',model=m,month=month,
                loglik=0.,informative_groups=0,training_status='ESTIMATED'))
        out,s=score_comparisons(pd.DataFrame(rows))
        self.assertEqual(out,[]);self.assertEqual(s[0]['status'],'INSUFFICIENT_COMMON_VALIDATION')

    def test_boundary_labels_and_curve_deduplication(self):
        f=dict(status='ESTIMATED',model='cost',names=['a','b'],beta=np.array([0.,2.]),cov=np.eye(2),
            identified=np.ones(2,bool),boundary=np.array([True,False]))
        r=coefficient_rows(f);self.assertTrue(r[0]['constrained_boundary']);self.assertTrue(np.isnan(r[1]['se']))
        d=pd.DataFrame(dict(model=['a','a','b','b'],gap=[-100,100,-100,100],value=[-.2,.3,-.2,.3]))
        collapsed=collapsed_curves(d,'value');self.assertEqual(len(collapsed),1)
        np.testing.assert_array_equal(collapsed[0]['data'].value,[-.2,.3])

    def test_original_count_correction_leaves_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);repair_original_counts(p)
            paths=list((p/'prior_reporting_corrections').glob('*.parquet'));self.assertEqual(len(paths),4)
            for path in paths:
                old=pd.read_parquet(ROOT/'authority'/path.name.replace('_corrected',''));new=pd.read_parquet(path)
                np.testing.assert_array_equal(old.grants/100,new.grants)
                pd.testing.assert_frame_equal(old.drop(columns='grants'),new.drop(columns=['grants','scope_note']))

if __name__=='__main__':unittest.main()
