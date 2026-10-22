import tempfile,unittest
from fixture import *
from model_utils import fit_one
from design import design
from run import embed_nested,refit,replace_fold,archive
from stats import conditional_value
from analysis import evaluate,coefficient_rows,save_public_fit

class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=fixture(70);cls.d=cls.d[cls.d.regular&cls.d.rd.le(110)&cls.d.opp_rd.le(110)&cls.d.month.le('2024-10')]
        g=cls.d.groupby('chooser').y
        cls.d=cls.d[(g.transform('sum')>0)&(g.transform('sum')<g.transform('size'))]
        cls.nested=fit_one(cls.d,'strength',inference=False)
        assert cls.nested['status']=='ESTIMATED'
        X,names,_=design(cls.d,'strength_framing')
        cls.failed=dict(cls.nested,model='strength_framing',names=names,
            beta=embed_nested(cls.nested,names),status='OPTIMIZER_NOT_CONVERGED')

    def test_nested_embedding_preserves_likelihood(self):
        X,names,_=design(self.d,'strength_framing');b=embed_nested(self.nested,names)
        self.assertEqual(b[names.index('draw_frame')],0.)
        self.assertAlmostEqual(conditional_value(X,self.d.y,self.d.chooser,b),self.nested['loglik'],places=7)
        with self.assertRaisesRegex(RuntimeError,'nesting'):embed_nested(self.nested,names+['unexpected'])

    def test_refit_and_replace_only_failed_fold(self):
        f,attempts,ll=refit(self.d,self.nested,self.failed)
        self.assertEqual(f['status'],'ESTIMATED');self.assertLess(f['gradient_max'],2e-5)
        self.assertGreaterEqual(f['loglik'],ll-1e-5);self.assertLessEqual(len(attempts),3)
        test=fixture(70);test=test[test.regular&test.rd.le(110)&test.opp_rd.le(110)&test.month.between('2024-11','2025-04')]
        scores,cal=evaluate(informative(test),f,metadata(test),state='equal',fold=0,comparison='rd110_train_rd110_test')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);own=p/'models/equal/strength_framing';own.mkdir(parents=True)
            failedscores=[dict(x,loglik=np.nan,training_status='OPTIMIZER_NOT_CONVERGED') for x in scores]
            kept=[dict(x,fold=1,month='2025-'+str(int(x['month'][-2:])%6+5).zfill(2)) for x in scores]
            table(failedscores+kept,own/'heldout_scores.parquet')
            keepcal=[dict(x,fold=1) for x in cal];table(keepcal,own/'heldout_calibration.parquet')
            oldcoeff=coefficient_rows(f,state='equal',training='rd110',stage='fold0')
            keepcoeff=coefficient_rows(f,state='equal',training='rd110',stage='fold1')
            table(oldcoeff+keepcoeff,own/'coefficients.parquet')
            write(p/'MODEL_JOB_STATUS.json',[dict(state='equal',model='strength_framing',status='COMPLETE_WITH_FIT_FAILURES'),dict(state='equal',model='cost',status='COMPLETE')])
            untouched=p/'models/equal/cost/unchanged.json';write(untouched,dict(marker=123));before=sha(untouched)
            replace_fold(p,f,scores,cal)
            after=pd.read_parquet(own/'heldout_scores.parquet')
            self.assertEqual(len(after),12);self.assertTrue(np.isfinite(after.loglik).all())
            pd.testing.assert_frame_equal(after[after.fold.eq(1)].reset_index(drop=True),pd.DataFrame(kept),check_dtype=False)
            self.assertEqual(sha(untouched),before)
            self.assertNotIn('switcher_ids',read(own/'rd110_fold0_fit.json'))
            self.assertTrue(all(x['status']=='COMPLETE' for x in read(p/'MODEL_JOB_STATUS.json')))

    def test_wrong_training_population_stops(self):
        with self.assertRaisesRegex(RuntimeError,'population differs'):refit(self.d.iloc[:-1],self.nested,self.failed)

if __name__=='__main__':unittest.main()
