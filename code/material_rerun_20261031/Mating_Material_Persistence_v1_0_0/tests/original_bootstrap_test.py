#!/usr/bin/env python3
"""Checks the bootstrap's weighting, paired histories, ratios and transitions."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import bootstrap_table3 as b
import numpy as np
import pandas as pd

def literal_cor(x,y,w=None):
    if w is None:return np.corrcoef(x,y)[0,1]
    dx=x-np.average(x,weights=w);dy=y-np.average(y,weights=w)
    return np.sum(w*dx*dy)/np.sqrt(np.sum(w*dx*dx)*np.sum(w*dy*dy))

def run():
    rng=np.random.default_rng(5411);n=1200
    d=pd.DataFrame()
    propensity=rng.beta(.5,3,n)
    for suffix in ['c1','c2','l1','l2']:
        d['n_'+suffix]=rng.integers(4,60,n)
        p=propensity*(1 if suffix.startswith('c') else .35)
        d['y_'+suffix]=rng.binomial(d['n_'+suffix],p)
    ma=b.matrix_a(d);mb=b.matrix_b(d)
    for panel,matrix,decode in [(0,ma,b.decode_a),(1,mb,b.decode_b)]:
        for rep in range(8):
            rr=np.random.default_rng(np.random.SeedSequence([171,panel,rep]))
            idx=rr.integers(0,n,n);sample=d.iloc[idx]
            via=b.draw_stat(matrix,panel,171,rep)
            literal=decode((b.matrix_a(sample) if panel==0 else b.matrix_b(sample)).sum(axis=0))
            np.testing.assert_allclose(via,literal,rtol=2e-12,atol=2e-12)
            if panel==0:
                x=(sample.y_c1/sample.n_c1).to_numpy();y=(sample.y_c2/sample.n_c2).to_numpy()
                w=(sample.n_c1+sample.n_c2).to_numpy()
                np.testing.assert_allclose(via[:2],[literal_cor(x,y),literal_cor(x,y,w)],rtol=2e-12)
                prior=sample.y_c1>0
                p0=100*sample.loc[~prior,'y_c2'].sum()/sample.loc[~prior,'n_c2'].sum()
                p1=100*sample.loc[prior,'y_c2'].sum()/sample.loc[prior,'n_c2'].sum()
                np.testing.assert_allclose(via[2:],[p0,p1,p1/p0])
            else:
                np.testing.assert_allclose(via[8:].reshape(4,4).sum(axis=1),100)
                r=[(sample['y_'+s]/sample['n_'+s]).to_numpy() for s in ['c1','c2','l1','l2']]
                np.testing.assert_allclose(via[:4],[literal_cor(r[0],r[1]),literal_cor(r[2],r[3]),
                    literal_cor(r[0],r[3]),literal_cor(r[2],r[1])])
                np.testing.assert_allclose(via[4:6],via[2:4]/np.sqrt(via[0]*via[1]))
                g1=b.group(sample.y_c1,sample.y_l1);g2=b.group(sample.y_c2,sample.y_l2)
                cells=np.array([[np.sum((g1==i)&(g2==j)) for j in range(4)] for i in range(4)])
                np.testing.assert_allclose(via[8:].reshape(4,4),100*cells/cells.sum(axis=1)[:,None])
    try:b.correlation(np.zeros(6))
    except ValueError:pass
    else:raise AssertionError('Undefined correlation was not rejected')
    print('BOOTSTRAP_KERNEL_TESTS_OK: literal account resampling, weights, ratios, correlations and transitions')

if __name__=='__main__':run()
