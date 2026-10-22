"""Test F synthetic checks. No empirical Lichess estimates are generated here."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
import pandas as pd
from run_f import (rate,wcor,year_group,transition_rows,pair_correlations,
                   p2_rates,weighted_wls,design,normal_p)


def test_groups():
    a=year_group([0,1,0,3,0],[0,0,2,1,0])
    assert a.tolist()==['NEI','CO','LO','BOTH','NEI']
    tab=pd.DataFrame({'y_c1':[0,1,0,3], 'y_l1':[0,0,1,2],
                      'y_c2':[1,0,1,0], 'y_l2':[0,1,1,0]})
    out=pd.DataFrame(transition_rows(tab,'synthetic'))
    assert int(out.accounts.sum())==4
    assert out[out.p1_group=='NEI'].accounts.sum()==1
    assert out[(out.p1_group=='LO')&(out.p2_group=='BOTH')].accounts.iloc[0]==1


def test_wcor():
    a=np.array([1,2,3]);b=np.array([3,2,1]);w=np.array([1,4,1])
    assert abs(wcor(a,b)+1)<1e-12
    assert abs(wcor(a,a,w)-1)<1e-12
    assert np.isnan(wcor([0,0,0],[1,2,3]))
    np.testing.assert_allclose(rate([0,1,3],[0,2,3]),[np.nan,.5,1],equal_nan=True)


def make_df():
    rng=np.random.default_rng(91)
    n=600
    df=pd.DataFrame({'n_c1':rng.integers(4,100,n),'n_l1':rng.integers(4,100,n),
                     'n_c2':rng.integers(4,100,n),'n_l2':rng.integers(4,100,n)})
    df['n_m1']=rng.integers(0,30,n)
    df['n_m2']=rng.integers(0,30,n)
    df['y_m1']=rng.binomial(df.n_m1,.017)
    df['y_m2']=rng.binomial(df.n_m2,.017)
    df['y_c1']=rng.binomial(df.n_c1,.035)
    df['y_l1']=rng.binomial(df.n_l1,.009)
    # Use targeted effect: C1 affects C2 more than L2, L1 affects L2 more than C2.
    ec=(df.y_c1>0).to_numpy();el=(df.y_l1>0).to_numpy()
    df['y_c2']=rng.binomial(df.n_c2,np.clip(.03+.03*ec+.002*el,.01,.25))
    df['y_l2']=rng.binomial(df.n_l2,np.clip(.007+.01*el+.001*ec,.001,.25))
    for reg in ('c','l'):
        df['mean_rating_'+reg+'2']=rng.normal(1600,220,n)
        df['mean_gap_'+reg+'2']=rng.normal(0,70,n)
        df['mean_vclip_'+reg+'2']=rng.normal(25 if reg=='c' else -400,80,n)
        df['mean_ply_'+reg+'2']=rng.normal(39,8,n)
        sp=rng.dirichlet([2,3,5,2,1],size=n)
        for idx, speed in enumerate(('ultrabullet','bullet','blitz','rapid','classical')):
            df['share_'+speed+'_'+reg+'2']=sp[:,idx]
    for reg in ('c','l'):
        for yr in (1,2):
            df[f'n_late_{reg}{yr}']=df[f'n_{reg}{yr}']//2
            df[f'y_late_{reg}{yr}']=df[f'y_{reg}{yr}']//2
    return df


def test_correlations():
    df=make_df()
    out=pair_correlations(df,4,'test')
    assert len(out)==4 and all(row['accounts']==len(df) for row in out)
    assert any(r['period1_state']=='c' and r['period2_state']=='c' for r in out)
    rr=p2_rates(df,'test')
    assert len(rr)==12
    assert all(z['P2_opportunities']>=0 for z in rr)


def test_regression():
    df=make_df()
    fits={}
    for s in ('c','l'):
        X,y,w,names=design(df,s)
        beta,V,scores,bread=weighted_wls(X,y,w)
        assert 'P1_ever_C' in names and 'P1_ever_L' in names
        assert len(beta)==len(names)
        assert np.isfinite(beta).all() and np.diag(V).min()>=-1e-8
        np.testing.assert_allclose(beta,np.linalg.lstsq(X*np.sqrt(w[:,None]),y*np.sqrt(w),rcond=None)[0],rtol=1e-7,atol=1e-7)
        fits[s]=(scores,bread)
        X,y,w,names=design(df,s,continuous=True)
        weighted_wls(X,y,w)
    cross=fits['c'][1]@(fits['c'][0].T@fits['l'][0])@fits['l'][1]
    assert cross.shape[0]>0 and np.isfinite(cross).all()
    assert abs(normal_p(0)-1)<1e-12


if __name__=='__main__':
    for name,fun in list(globals().items()):
        if name.startswith('test_') and callable(fun):
            fun();print('PASS',name,flush=True)
