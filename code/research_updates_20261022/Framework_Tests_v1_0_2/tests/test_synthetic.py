"""Synthetic mathematical unit tests. No chess results are asserted here."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from methods import (spline,gp_logpmf,fit_gp_zip,model_design,
                     within_chunk_cross_products,within_chunk_cluster_scores,
                     starts_for_sorted_ids)

def test_spline():
 assert spline(np.array([0.])).shape==(1,4)
 assert np.max(np.abs(spline(np.array([0.]))))<1e-10
 assert np.isfinite(spline(np.linspace(-100,600,100))).all()
 # Natural second derivative vanishes outside the boundary knots.
 for center in (-1000,1000):
  v=spline(np.array([center-2,center,center+2]))
  assert np.max(abs(v[2]-2*v[1]+v[0])) < 1e-10

def test_gp():
 y=np.array([0,1,2],np.int32)
 e=np.array([.2,1.4,2.6],float)
 for k in (.05,.5,10.,900.):
  z=gp_logpmf(y,e,k)
  for i in range(3):
   yy=int(y[i]); E=e[i]
   manual=(__import__('math').lgamma(yy+k)-__import__('math').lgamma(k)-
    __import__('math').lgamma(yy+1)+ k*np.log(k/(k+E))+yy*np.log(E/(k+E)))
   assert abs(z[i]-manual)<1e-10

def test_mixture():
 rng=np.random.default_rng(13131)
 n=2500;e=rng.uniform(1,10,size=n)
 active=rng.random(n)<.65
 theta=np.where(active,rng.gamma(1.2,1/1.2,size=n),0)
 y=rng.poisson(theta*e)
 fit=fit_gp_zip(y,e)
 assert 0.35<fit['zip_gamma_active']<0.90,fit
 assert fit['zip_log_likelihood']>=fit['gp_log_likelihood']-1e-6,fit
 assert fit['boundary_lr_p']<.05,fit

def test_within():
 rng=np.random.default_rng(435)
 ng=40;n=120
 ids=np.repeat(np.arange(ng),3)
 X=rng.standard_normal((n,3))
 beta=np.array([1.,.2,-2.])
 fe=np.repeat(rng.standard_normal(ng),3)
 y=X@beta+fe+rng.normal(0,.1,n)
 xx,xy,G=within_chunk_cross_products(X,y,ids)
 assert G==ng
 xd=X.reshape(ng,3,3)-X.reshape(ng,3,3).mean(axis=1,keepdims=True)
 yd=y.reshape(ng,3)-y.reshape(ng,3).mean(axis=1,keepdims=True)
 np.testing.assert_allclose(xx,xd.reshape(n,3).T@xd.reshape(n,3),atol=1e-10)
 np.testing.assert_allclose(xy,xd.reshape(n,3).T@yd.reshape(n),atol=1e-10)
 bh=np.linalg.solve(xx,xy)
 meat,g=within_chunk_cluster_scores(X,y,ids,bh)
 scores=np.einsum('gij,gi->gj',xd,yd-np.einsum('gij,j->gi',xd,bh))
 np.testing.assert_allclose(meat,scores.T@scores,atol=1e-10)

if __name__=='__main__':
 for name,f in sorted(globals().copy().items()):
  if name.startswith('test_') and callable(f):
   f();print('PASS',name,flush=True)
