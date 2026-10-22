"""Regressions must survive singular nuisance composition without changing targets.

Tests use synthetic accounts only; no empirical estimate asserted.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from test_f_synthetic import make_df
from run_f import design, weighted_wls, cross_predict, keep_identified_covariates
import tempfile


def test_nuisance_speed_collinearity():
    df=make_df()
    for state in ('c','l'):
        # All users have zero ultrabullet share: other shares sum to exactly 1.
        s=sum(df['share_'+speed+'_'+state+'2'] for speed in ('bullet','blitz','rapid','classical'))
        for speed in ('bullet','blitz','rapid','classical'):
            df['share_'+speed+'_'+state+'2']/=s
        for continuous in (False,True):
            X,y,w,names,dropped=design(df,state,continuous=continuous,return_drops=True)
            assert len(dropped)==1, dropped
            assert dropped[0]['dropped_covariate']=='P2_classical_share_standardized',dropped
            beta,vcov,_,_=weighted_wls(X,y,w)
            assert all(target in names for target in ('P1_competitive_rate_pp','P1_lost_rate_pp') if continuous) if continuous else all(
                target in names for target in ('P1_ever_C','P1_ever_L','P1_both_interaction'))
            np.testing.assert_allclose(beta,
                np.linalg.lstsq(X*np.sqrt(w[:,None]), y*np.sqrt(w),rcond=None)[0],
                atol=1e-9,rtol=1e-9)
            assert np.all(np.isfinite(vcov))
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)
        result=cross_predict(df,path)
        assert len(result)==16
        assert len((path/'tabF5_collinearity_audit.csv').read_text().splitlines())==5


def test_dropped_controls_do_not_rotate_targets():
    rng=np.random.default_rng(5)
    n=1000
    z=rng.normal(size=n);f=rng.normal(size=n)
    X=np.column_stack([np.ones(n),z,f,rng.normal(size=n), np.ones(n)*4])
    Xr,names,dropped=keep_identified_covariates(X,np.ones(n),['constant','target1','target2','noise','duplicate_constant'],3)
    assert names==['constant','target1','target2','noise']
    assert len(dropped)==1 and dropped[0]['dropped_covariate']=='duplicate_constant'
    # Exact focal co-linearity must NOT be repaired by removing a target.
    try:
        keep_identified_covariates(np.column_stack([np.ones(n),z,2*z,f]),np.ones(n),
                                   ['constant','target1','target2','noise'],3)
    except ValueError as e:
        assert 'focal year-one predictor' in str(e)
    else:
        raise AssertionError('unidentified focal predictor accepted')


if __name__=='__main__':
    for name,fun in list(globals().items()):
        if name.startswith('test_') and callable(fun):
            fun(); print('PASS',name,flush=True)
