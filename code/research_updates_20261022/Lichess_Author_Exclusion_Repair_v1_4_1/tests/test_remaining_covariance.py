"""The original first/repeat fit is unchanged by covariance-only export."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT/'vendor/wave2b2a/source/c7r')]
from first_repeat_remaining import retain_covariance
import campaign1_nonprofile_common_v102 as common
import numpy as np

class CovarianceExportTest(unittest.TestCase):
    def test_original_arithmetic_and_joint_contrast(self):
        rng=np.random.default_rng(241);n=2400;groups=np.repeat(np.arange(200),12)
        fair=rng.integers(0,2,n).astype(float);repeat=rng.integers(0,2,n).astype(float)
        error=rng.normal(0,.1,n);y=.2*fair+.1*repeat-.05*fair*repeat+error+rng.normal(size=200)[groups]
        kwargs=dict(outcome=y,exposures={'fair':fair,'repeat':repeat,'fair_x_repeat':fair*repeat},numeric_controls={},fixed_effects={'chooser':groups},clusters=groups,row_ids=np.arange(n),specification={'model':'fixture'})
        before=common.fit_hdfe_cluster(**kwargs);original=retain_covariance(common)
        try:after=common.fit_hdfe_cluster(**kwargs)
        finally:common.fit_hdfe_cluster=original
        self.assertEqual(before,{k:v for k,v in after.items() if k not in ('covariance_terms','covariance_probability_units')})
        V=np.array(after['covariance_probability_units']);names=after['covariance_terms'];i=names.index('fair');j=names.index('fair_x_repeat')
        for r in after['results']:self.assertAlmostEqual(r['standard_error']**2,V[names.index(r['term']),names.index(r['term'])])
        self.assertNotAlmostEqual(V[i,i]+V[j,j]+2*V[i,j],V[i,i]+V[j,j],places=9)

if __name__=='__main__':unittest.main(verbosity=2)
