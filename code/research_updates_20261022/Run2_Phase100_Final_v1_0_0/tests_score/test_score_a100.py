import sys,tempfile,unittest,copy
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from score_a100_common import *
import score_a100_report as report
from run_score_a100 import verify_same_score_rows,verify_env_overlap
sys.path.insert(0,str(PACKAGE/'vendor_r9_resume/frozen_R9/tests'))
import test_r9 as fixture

class FinalScoreTests(unittest.TestCase):
    def test_original_margin_is_scale_invariant(self):
        b=-.005711/(100*COMMON_SD);se=.005481/(100*COMMON_SD)
        row=dict(coefficient=b,standard_error=se,supported=True)
        got=report.placebo_precision(row)
        self.assertFalse(got['nominal_90CI_inside_original_margin'])
        self.assertAlmostEqual(got['equivalence_margin_pp_per_common_SD'],.015*COMMON_SD/.0594,15)
        native=report.placebo_precision(dict(coefficient=0.,standard_error=.0001,supported=True))
        self.assertTrue(native['nominal_90CI_inside_original_margin'])

    def test_band_identity_score_reuse_and_dependency_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,s=fixture.fixture(p,4000)
            r.io.table(p/'band.parquet',pa.table({k:v[3000:] for k,v in d.items()}))
            src,sc,info=select_band(p/'data.parquet',p/'scores.parquet',p/'band.parquet',p/'out','test',.5)
            self.assertEqual(info['rows'],1000)
            np.testing.assert_array_equal(col(src,'row_id'),d['row_id'][3000:])
            np.testing.assert_allclose(col(sc,'adjusted_A'),s['adjusted_A'][3000:])
            self.assertEqual(select_band(p/'data.parquet',p/'scores.parquet',p/'band.parquet',p/'out','test',.5)[2],info)
            bad={k:v[3000:].copy() for k,v in d.items()};bad['game_id'][0]='wrong'
            r.io.table(p/'bad.parquet',pa.table(bad))
            with self.assertRaisesRegex(RuntimeError,'identity differs'):
                select_band(p/'data.parquet',p/'scores.parquet',p/'bad.parquet',p/'badout','test',.5)
            with self.assertRaisesRegex(RuntimeError,'input changed'):
                select_band(p/'data.parquet',p/'scores.parquet',p/'bad.parquet',p/'out','test',.5)

    def test_score_rebinding_and_exact_environment_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,s=fixture.fixture(p,4000);cut=3000
            earlier={k:v[:cut].copy() for k,v in d.items()};earlier['row_id']+=10000
            oldscore={k:v[:cut].copy() for k,v in s.items()};oldscore['row_id']+=10000
            r.io.table(p/'oldmodel.parquet',pa.table(earlier));r.io.table(p/'oldscores.parquet',pa.table(oldscore))
            got=compare_score_overlap(p/'data.parquet',p/'scores.parquet',p/'oldmodel.parquet',p/'oldscores.parquet',p/'bridge','test',.5)
            self.assertEqual(got['rows_checked'],cut)
            env=verify_env_overlap(p/'data.parquet',p/'oldmodel.parquet',p/'envbridge','test',.5)
            self.assertTrue(env['all_environment_controls_reproduced'])
            copy_path=p/'same.parquet';r.io.table(copy_path,pa.table(s))
            self.assertTrue(verify_same_score_rows(p/'scores.parquet',copy_path,p/'samecheck','test',.5)['receipt_models_reusable'])
            oldscore['adjusted_A'][0]+=.001;r.io.table(p/'badscores.parquet',pa.table(oldscore))
            with self.assertRaisesRegex(RuntimeError,'score changed'):
                compare_score_overlap(p/'data.parquet',p/'scores.parquet',p/'oldmodel.parquet',p/'badscores.parquet',p/'badbridge','test',.5)
            earlier['environment_supported'][0]=~earlier['environment_supported'][0];r.io.table(p/'badenv.parquet',pa.table(earlier))
            with self.assertRaisesRegex(RuntimeError,'ENV values changed'):
                verify_env_overlap(p/'data.parquet',p/'badenv.parquet',p/'badenvcheck','test',.5)

    def test_real_spawned_final_fits_joint_contrasts_report_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d,s=fixture.fixture(p,12000);nold=9000;conf='synthetic'
            r.io.table(p/'previous.parquet',pa.table({k:v[:nold] for k,v in d.items()}))
            r.io.table(p/'previous_scores.parquet',pa.table({k:v[:nold] for k,v in s.items()}))
            r.io.table(p/'membership.parquet',pa.table({k:v[nold:] for k,v in d.items()}))
            band,bs,info=select_band(p/'data.parquet',p/'scores.parquet',p/'membership.parquet',p/'band',conf,.5)
            receipt={k:v.copy() for k,v in d.items()}
            receipt['y'][::10]=~receipt['y'][::10];receipt['reached'][::17]=~receipt['reached'][::17]
            r.io.table(p/'receipt.parquet',pa.table(receipt))
            oldfits={};oldjobs=[]
            for level in LEVELS:
                for sm,kind in [('F','entry'),('O','ordinary'),('S0','iv')]:
                    src,sc=(p/'receipt.parquet',p/'scores.parquet') if sm=='S0' else (p/'previous.parquet',p/'previous_scores.parquet')
                    out=p/'certified'/(sm+'__'+level);oldfits[(sm,level)]=out
                    oldjobs.append(fits.make_job(src,sc,out,conf,sm+'75' if sm!='S0' else sm,kind,level))
            runtime.mapped(fits.fit_job,oldjobs,3,11,'synthetic certified reference',1)
            plan=[]
            for label,src,sc in [('100',p/'data.parquet',p/'scores.parquet'),('75_100',band,bs)]:
                for sm,kind in [('F','entry'),('O','ordinary')]:
                    for level in LEVELS:plan.append(fits.make_job(src,sc,p/'fits'/(sm+label+'__'+level),conf,sm+label,kind,level))
            runtime.mapped(fits.fit_job,plan,3,11,'synthetic final comparisons',1)
            lookup={(j['sample'],j['level']):j['output'] for j in plan};contrasts=[]
            for level in LEVELS:
                contrasts.append(dict(left=str(oldfits[('S0',level)]),right=lookup[('O100',level)],label='S0_minus_ordinary100',outcomes=['y','reached'],
                    level=level,conf=conf,output=str(p/'contrasts'/('main_'+level)),memory_gb=2.))
                for sm,outs in [('F',['analysis_entry_90','recipient_disconnect_main','active_timeout']),('O',['y','reached'])]:
                    contrasts.append(dict(left=lookup[(sm+'75_100',level)],right=str(oldfits[(sm,level)]),label=sm+'_added75_100_minus_first75',outcomes=outs,
                        level=level,conf=conf,output=str(p/'contrasts'/(sm+'_'+level)),memory_gb=2.))
            runtime.mapped(fits.contrast_job,contrasts,3,11,'synthetic joint covariance',1)
            summary=report.export(p,p/'desktop',conf,'PHASE_100_SCORE_A_COMPLETE',{},oldfits,plan,contrasts)
            self.assertEqual(summary['completed_new_models'],8)
            self.assertFalse(summary['new_receipt_IV_estimated'])
            rows=u.load(p/'report/receipt_minus_ordinary.json')
            self.assertEqual(len(rows),4)
            for row in rows:
                V=np.array(row['covariance_matrix'])
                self.assertAlmostEqual(row['standard_error']**2,V[0,0]+V[1,1]-2*V[0,1],12)
                self.assertTrue(row['stacked_actual_accounts_and_dates'])
            # Shared players and dates give nonzero cross-equation covariance.
            self.assertTrue(all(abs(x['covariance_matrix'][0][1])>1e-12 for x in rows))
            with mock.patch.object(fits,'estimate',side_effect=AssertionError('must reuse completed Parquets')):
                for job in plan:fits.fit_job(job)
            with self.assertRaisesRegex(RuntimeError,'Eight comparison fits'):
                report.export(p,p/'desktop',conf,'PHASE_100_SCORE_A_COMPLETE',{},oldfits,plan[:-1],contrasts)

if __name__=='__main__':unittest.main()
