import json, tempfile, unittest, subprocess, sys, zipfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from validate_ratings import Moments, extract, process_month, exact_p99

def example():
    # Includes an observed zero, a missing observation, a black chooser,
    # a known chooser loss, and a prediction differing from its replay check.
    return pa.table(dict(
      chooser_color=['white','black','white','black','white','black'],
      outcome_kind_draw=[1,0,1,0,0,1],timeout_chooser_win=[0,1,0,1,0,0],timeout_chooser_loss=[0,0,0,0,1,0],
      chooser_has_mating_material=[True]*6,
      white_rating_diff_pgn=[0,-9,None,-5,-8,4],black_rating_diff_pgn=[0,9,None,5,8,-4],
      chooser_draw_payoff_v2=[.25,-2.,2.,-1.,1.,-3.5],chooser_win_payoff_v2=[4.,9.5,6.,4.,4.,3.],
      white_realized_pred_ratingdiff_v2=[.25,-8.,2.,-4.,-8.,4.],
      black_realized_pred_ratingdiff_v2=[.1,9.5,-2.,4.,8.,-3.4]))

class ValidationTests(unittest.TestCase):
    def test_roles_zero_null_and_loss(self):
        d=extract(example().to_batches()[0]);np.testing.assert_allclose(d['observed'],[0,9,np.nan,5,-8,-4],equal_nan=True)
        self.assertEqual(int(d['grant'].sum()),3);self.assertEqual(int(d['claim'].sum()),2)
        self.assertTrue(d['loss'][4]);self.assertEqual(d['action_payoff'][1],9.5)
    def test_stable_moments_against_direct_and_merge(self):
        rng=np.random.default_rng(42);x=1e8+rng.normal(size=317);y=x+rng.normal(size=317)*.3
        a=Moments();b=Moments();a.add(x[:150],y[:150]);b.add(x[150:],y[150:]);a.merge(b)
        r=a.result();self.assertAlmostEqual(r['correlation'],np.corrcoef(x,y)[0,1],places=8)
        self.assertAlmostEqual(r['mean_absolute_error'],np.abs(y-x).mean(),places=8)
        self.assertEqual(r['within_one_point_count'],int((np.abs(y-x)<=1).sum()))
    def test_exact_quantile_and_input_preservation(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);a=np.array([4.,0.,1.,9.,3.,6.]);a[:2].tofile(p/'a');a[2:].tofile(p/'b')
            old=(p/'a').read_bytes();self.assertEqual(exact_p99([p/'a',p/'b'],6,p),np.quantile(a,.99))
            self.assertEqual((p/'a').read_bytes(),old)
    def test_streamed_month_matches_direct_and_counts(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);pq.write_table(example(),p/'input.parquet');before=(p/'input.parquet').read_bytes()
            s=process_month(p/'input.parquet',p/'out',6,3,1,batch_rows=2)
            self.assertEqual(s['moments']['grant__action_payoff']['n'],2)
            self.assertEqual(s['missing']['grant__action_payoff']['missing_recorded'],1)
            r=Moments(**s['moments']['claim__action_payoff']).result()
            self.assertEqual(r['mean_absolute_error'],.75);self.assertEqual(r['within_one_point_pct'],100.)
            self.assertEqual((p/'input.parquet').read_bytes(),before)
    def test_bad_color_or_overlap_rejected(self):
        for col,values in [('chooser_color',['bad','black','white','black','white','black']),
                           ('timeout_chooser_win',[1,1,0,1,0,0])]:
            x=example().set_column(example().schema.get_field_index(col),col,pa.array(values))
            with self.assertRaises(RuntimeError):extract(x.to_batches()[0])
    def test_missing_columns_and_bad_census_rejected(self):
        with self.assertRaises(RuntimeError):extract(example().drop(['chooser_color']).to_batches()[0])
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);pq.write_table(example(),p/'input.parquet')
            with self.assertRaises(RuntimeError):process_month(p/'input.parquet',p/'out',6,2,1)
    def test_undefined_correlation_is_not_zero(self):
        a=Moments();a.add(np.ones(4),np.ones(4));self.assertIsNone(a.result()['correlation'])
        self.assertIsNone(Moments().result()['mean_absolute_error'])
    def test_missing_parent_returns_diagnostic_zip(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            cmd=[sys.executable,str(Path(__file__).resolve().parents[1]/'code/validate_ratings.py'),
                 '--project',str(p/'absent-project'),'--results',str(p/'results')]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            with zipfile.ZipFile(p/'results/RATING_VALIDATION_PREFLIGHT_RETURN.zip') as z:
                self.assertEqual(json.loads(z.read('STATUS.json'))['status'],'PREFLIGHT_PAUSED')
            self.assertFalse((p/'absent-project').exists())

if __name__=='__main__':unittest.main()
