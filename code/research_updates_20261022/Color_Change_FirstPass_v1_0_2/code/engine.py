"""Chronological replay kernel. Expected runtime: 1-6 h for three months.
Optional Numba acceleration uses the authenticated production math functions;
no dependency is installed by this package. Five speed pools are independent.
"""
from __future__ import annotations
import inspect, math
import numpy as np
from common import CUTOFF_MS, ADVANTAGE, SCALE

INFLATE=None
UPDATE=None

def kernel(rd,sigma,games,last,ids_w,ids_b,elo_w,elo_b,utc,scores,obs_w,obs_b):
    n=len(utc)
    pre=np.empty((n,12),np.float64)
    for i in range(n):
        wi=ids_w[i]; bi=ids_b[i]; now=utc[i]
        if wi<0 or bi<0 or wi>=len(rd) or bi>=len(rd) or wi==bi:
            raise ValueError("Replay ID outside dictionary or self-player game")
        wr=INFLATE(np.float64(rd[wi]),np.float64(sigma[wi]),last[wi],now,.21436,45.,500.)
        br=INFLATE(np.float64(rd[bi]),np.float64(sigma[bi]),last[bi],now,.21436,45.,500.)
        ws=np.float64(sigma[wi]); bs=np.float64(sigma[bi])
        a=ADVANTAGE/2 if now>=CUTOFF_MS else 0.
        score=scores[i]/2.
        if scores[i]<0 or scores[i]>2: raise ValueError("Invalid result code")
        wp,wrd,wsg=UPDATE(elo_w[i],wr,ws,elo_b[i],br,score,.75,45.,500.,.1,a,-a)
        bp,brd,bsg=UPDATE(elo_b[i],br,bs,elo_w[i],wr,1-score,.75,45.,500.,.1,-a,a)
        pre[i,0]=wr; pre[i,1]=br; pre[i,2]=ws; pre[i,3]=bs
        pre[i,4]=games[wi]; pre[i,5]=games[bi]
        pre[i,6]=last[wi]; pre[i,7]=last[bi]
        pre[i,8]=wp; pre[i,9]=bp
        pre[i,10]=rd[wi]; pre[i,11]=rd[bi]
        if not (np.isnan(obs_w[i]) and np.isnan(obs_b[i])):
            rd[wi]=wrd; rd[bi]=brd; sigma[wi]=wsg; sigma[bi]=bsg
            games[wi]+=1; games[bi]+=1; last[wi]=now; last[bi]=now
    return pre

def configure(producer,allow_jit=True):
    global INFLATE,UPDATE
    INFLATE=producer.inflate_rd; UPDATE=producer.update_one
    if allow_jit:
        try:
            import numba
        except ImportError:
            return kernel,"python"
        # Compile exact function bodies from the source whose SHA was checked.
        # Numerical parity is tested before selecting this backend.
        env=dict(vars(producer))
        for name in ("g_phi","expected_score","volatility_update","inflate_rd","update_one"):
            exec(inspect.getsource(getattr(producer,name)),env)
            env[name]=numba.njit(cache=False)(env[name])
        INFLATE=env["inflate_rd"]; UPDATE=env["update_one"]
        accelerated=numba.njit(cache=False)(kernel)
        # Includes both-null, one-sided-null, repeated users and color cutoff.
        rng=np.random.default_rng(3917); n=1000; users=37
        w=rng.integers(0,users,n,dtype=np.int64)
        b=(w+rng.integers(1,users,n,dtype=np.int64))%users
        ts=np.arange(n,dtype=np.int64)*100000+CUTOFF_MS-50000000
        args=[w,b,rng.integers(700,2500,n).astype(float),rng.integers(700,2500,n).astype(float),ts,rng.integers(0,3,n,dtype=np.int8),np.ones(n),np.ones(n)]
        args[-1][::7]=np.nan; args[-2][::11]=np.nan
        def state(): return [np.full(users,85,np.float32),np.full(users,.09,np.float32),np.zeros(users,np.uint32),np.full(users,-1,np.int64)]
        sj=state(); got=accelerated(*sj,*args)
        INFLATE=producer.inflate_rd; UPDATE=producer.update_one
        sp=state(); expected=kernel(*sp,*args)
        if not np.allclose(got,expected,rtol=1e-11,atol=1e-8) or any(not np.allclose(x,y,rtol=1e-7,atol=1e-8) for x,y in zip(sj,sp)):
            raise RuntimeError("Accelerated replay disagrees with authenticated production math")
        INFLATE=env["inflate_rd"]; UPDATE=env["update_one"]
        return accelerated,"numba_verified"
    return kernel,"python"
