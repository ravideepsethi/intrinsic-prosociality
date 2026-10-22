"""Small algebraic tests of the new nesting and regional score accounting."""
import numpy as np
import pandas as pd
from scipy import sparse
from challenge import expand_level, paired_score
from model import components, objective

def main():
    d=dict(X=sparse.csr_matrix([[0.],[1.],[1.],[0.],[1.],[0.]]),
           ids=np.array([0,0,1,1,2,2]), F=np.array([0.,1.,0.,1.,0.,1.]),
           n=np.array([4.,5.,3.,6.,7.,8.]),g=np.array([0.,1.,0.,0.,1.,2.]),N=3)
    v=np.r_[[-6.,-3.,-1.],1.4,.2,np.log(np.array([.08,.02])/.9)]
    fit=dict(K=3,parameters=v.tolist())
    original=components(v,d,3,False)[2]
    for K in [4,5]:
        for split in range(3):
            expanded=expand_level(fit,K,split)
            assert len(expanded)==2*K+1
            assert np.allclose(components(expanded,d,K,False)[2],original,atol=1e-12)
            assert abs(objective(expanded,d,K,False)[0]-objective(v,d,3,False)[0])<1e-12
    df=pd.DataFrame(dict(n=d['n'],g=d['g']))
    a=np.array([.1,.2,.3,.4,.5,.6]);b=a*.8
    allrow=paired_score(a,b,df,d['ids'],np.ones(6,bool),3)
    pieces=[paired_score(a,b,df,d['ids'],d['F']==f,3) for f in [0,1]]
    assert abs(sum(r['gain']*r['opportunities'] for r in pieces)/df.n.sum()-allrow['gain'])<1e-12
    assert abs(allrow['grant_contribution']+allrow['nongrant_contribution']-allrow['gain'])<1e-12
    lossdiff=d['g']*np.log(b/a)+(d['n']-d['g'])*np.log((1-b)/(1-a))
    accountdiff=np.array([lossdiff[d['ids']==i].sum() for i in range(3)])
    count=np.array([d['n'][d['ids']==i].sum() for i in range(3)])
    expected=np.sqrt(3/2*np.sum((accountdiff-allrow['gain']*count)**2))/count.sum()
    assert abs(expected-allrow['conditional_cluster_SE'])<1e-12
    assert paired_score(a,b,df,d['ids'],np.zeros(6,bool),3) is None
    print('PASS: exact K4/K5 nesting, parameter counts, score decomposition, clustered SE.')

if __name__=='__main__':main()
