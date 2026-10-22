"""Numerical helpers for Lichess framework diagnostics; stdlib + numpy only."""
from __future__ import annotations
import math
import numpy as np

GROUPS = ('CO', 'BOTH', 'LO', 'NEI')


def spline(x):
    """4-df natural cubic spline on [-100,600], interior knots [0,100,300].

    Basis centered at x=0; this is a reparameterization of a natural cubic
    spline, with knots expressed in units of 100 centipawns.
    """
    z = np.asarray(x, dtype=np.float64) / 100.0
    z = np.clip(z, -1.0, 6.0)
    low, high = -1., 6.
    def d(t):
        return (np.maximum(z-t, 0.)**3 - np.maximum(z-high, 0.)**3)/(high-t)
    dx = d(low)
    out = np.column_stack([z, d(0.)-dx, d(1.)-dx, d(3.)-dx])
    zz = np.zeros((1,), dtype=np.float64)
    def dc(t):
        return (np.maximum(zz-t,0.)**3 - np.maximum(zz-high,0.)**3)/(high-t)
    anchor = np.array([0., *(dc(t)[0]-dc(low)[0] for t in (0.,1.,3.))])
    return out - anchor


def safe_lgamma_lookup(ys, k):
    # Avoid scipy dependency: integer y allows cached gamma-function differences.
    umax=int(np.max(ys)) if len(ys) else 0
    ys=np.asarray(ys, dtype=np.int64)
    if umax > 300000:
        raise ValueError('Unexpectedly large account grant count; investigate source.')
    seq=np.arange(umax+1)
    log_num=np.fromiter((math.lgamma(float(k)+int(a))-math.lgamma(float(k)) for a in seq),float,count=len(seq))
    log_fac=np.fromiter((math.lgamma(int(a)+1) for a in seq),float,count=len(seq))
    return log_num[ys]-log_fac[ys]


def gp_logpmf(y, exposure, k):
    y=np.asarray(y,dtype=np.int64)
    exposure=np.asarray(exposure,dtype=float)
    if not(np.all(exposure>0) and k>0):
        raise ValueError('exposure must be strictly positive and k>0')
    return (safe_lgamma_lookup(y,k) + k*(math.log(k)-np.log(k+exposure))
            + y*(np.log(exposure)-np.log(k+exposure)))


def zip_logpmf(y,exposure,k,gamma):
    if not 0<gamma<=1:
        raise ValueError('active-mixture probability outside (0,1]')
    lp=gp_logpmf(y,exposure,k)
    out=np.log(gamma)+lp
    zz=y==0
    if gamma<1:
        out[zz]=np.logaddexp(math.log1p(-gamma), out[zz])
    return out


def golden_optimize(fun, lo, hi, tol=1e-5, maxiter=100):
    """Univariate bounded maximization via golden-section search."""
    inv=(math.sqrt(5)-1)/2
    a,b=float(lo),float(hi)
    c=b-(b-a)*inv; d=a+(b-a)*inv
    fc=float(fun(c)); fd=float(fun(d))
    for _ in range(maxiter):
        if b-a<=tol: break
        if fc > fd:
            b,d,fd=d,c,fc
            c=b-(b-a)*inv; fc=float(fun(c))
        else:
            a,c,fc=c,d,fd
            d=a+(b-a)*inv; fd=float(fun(d))
    candidates=[(fc,c),(fd,d),(fun(lo),lo),(fun(hi),hi)]
    val,x=max(candidates,key=lambda z:z[0])
    return float(x),float(val)


def fit_gp_zip(y,exposure):
    """ML Gamma-Poisson and zero-inflated Gamma-Poisson.

    Pure numpy, no scipy. 1-d profile + EM updates for active share gamma.
    Evaluates likelihood on full accounts, not an account subsample.
    """
    y=np.asarray(y,dtype=np.int32); exposure=np.asarray(exposure,dtype=float)
    if not len(y): raise ValueError('no accounts supported')
    if np.any(y<0) or np.any(exposure<=0): raise ValueError('invalid counts/exposures')
    lo,hi=math.log(.01),math.log(1000.)
    fitlogk,base_ll=golden_optimize(lambda t: float(gp_logpmf(y,exposure,math.exp(t)).sum()),lo,hi)
    base_k=math.exp(fitlogk)
    best=(float(base_ll),base_k,1.)
    # EM/profile iterations. Start from several active shares for multimodality protection.
    for initial in (.25,.80):
        gamma=float(initial); k=float(base_k)
        for _ in range(14):
            # Given gamma, profile optimization over log(k).
            logk,ll=golden_optimize(lambda t: float(zip_logpmf(y,exposure,math.exp(t),gamma).sum()),lo,hi,tol=2e-3,maxiter=35)
            k=math.exp(logk)
            p0=np.exp(-k*np.log1p(exposure/k))
            z=y==0
            activeposterior=np.ones(len(y), dtype=float)
            activeposterior[z]=(gamma*p0[z])/((1-gamma)+gamma*p0[z])
            next_gamma=float(np.clip(activeposterior.mean(),1e-7,1-1e-7))
            if abs(next_gamma-gamma)<1e-5:
                gamma=next_gamma
                break
            gamma=next_gamma
        ll=float(zip_logpmf(y,exposure,k,gamma).sum())
        if ll>best[0]: best=(ll,k,gamma)
    llzip,kzip,gammazip=best
    lr=max(0.,2*(llzip-base_ll))
    # Null gamma=1 is the boundary: 0.5 chi2_0 + 0.5 chi2_1.
    p_boundary=0.5*math.erfc(math.sqrt(lr/2.)) if lr>0 else 1.
    result={
        'n_accounts':len(y), 'gp_k':base_k,'gp_log_likelihood':base_ll,
        'zip_k':kzip,'zip_gamma_active':gammazip,
        'zip_zero_mass':1-gammazip, 'zip_log_likelihood':llzip,
        'likelihood_ratio':lr,'boundary_lr_p':p_boundary,
    }
    # Conservative/transparent numerical observed-information Wald intervals,
    # not profile-likelihood intervals, for reporting diagnostic use only.
    if gammazip<.999999:
        t0=np.array([math.log(kzip), math.log(gammazip/(1-gammazip))],float)
        def ll(t):
            g=1/(1+math.exp(-float(np.clip(t[1],-30,30))))
            return float(zip_logpmf(y,exposure,math.exp(float(t[0])),g).sum())
        h=.003; H=np.zeros((2,2)); f0=ll(t0)
        for i in range(2):
            delta=np.zeros(2);delta[i]=h
            H[i,i]=(ll(t0+delta)-2*f0+ll(t0-delta))/(h*h)
        e1=np.array([h,h]); e2=np.array([h,-h])
        H[0,1]=H[1,0]=(ll(t0+e1)-ll(t0+e2)-ll(t0-e2)+ll(t0-e1))/(4*h*h)
        try:
            info=np.linalg.inv(-H)
            se_logit=math.sqrt(max(0.,float(info[1,1])))
            l=t0[1]-1.96*se_logit;u=t0[1]+1.96*se_logit
            expit=lambda a:1/(1+math.exp(-float(np.clip(a,-30,30))))
            result.update(gamma_wald95_lo=expit(l),gamma_wald95_hi=expit(u))
        except np.linalg.LinAlgError:
            result.update(gamma_wald95_lo=float('nan'),gamma_wald95_hi=float('nan'))
    else:
        result.update(gamma_wald95_lo=float('nan'),gamma_wald95_hi=1.)
    return result


def model_design(frame, months, speeds):
    """Full B design: chooser FE handled by within transform in fit_b.

    Includes group-specific payoff, spline, upper-tail and mate indicators,
    and stage-band indicators, plus common controls.
    """
    n=len(frame); g=frame['grp'].astype(str).to_numpy()
    rg=frame['rG'].to_numpy(dtype=float)
    v=frame['v'].to_numpy(dtype=float)
    spl=spline(v)
    high=((v>=600)&(v<9000)).astype(float)
    mate=(v>=9000).astype(float)
    stage=frame['stage'].astype(str).to_numpy()
    cols=[];labels=[]
    for gg in GROUPS:
        mask=(g==gg).astype(float)
        cols.append(mask*rg); labels.append(f'beta_{gg}_rG')
        for j in range(spl.shape[1]):
            cols.append(mask*spl[:,j]);labels.append(f'f_{gg}_{j}')
        cols.append(mask*high); labels.append(f'upper_{gg}')
        cols.append(mask*mate);labels.append(f'mate_{gg}')
        for st in ('21-40','41-80','81+'):
            cols.append(mask*(stage==st));labels.append(f'stage_{gg}_{st}')
    speedscol=frame['speed'].astype(str).to_numpy()
    monthscol=frame['month'].astype(str).to_numpy()
    for sp in speeds[1:]:
        cols.append((speedscol==sp).astype(float));labels.append(f'speed_{sp}')
    for mo in months[1:]:
        cols.append((monthscol==mo).astype(float));labels.append(f'month_{mo}')
    kappa=frame['kappa'].to_numpy(dtype=float)
    rd1=frame['rd_chooser'].to_numpy(dtype=float)
    rd2=frame['rd_opponent'].to_numpy(dtype=float)
    if np.any(kappa<=0) or np.any(rd1<=0) or np.any(rd2<=0):
        raise ValueError('nonpositive K/2 or RD; inspect main input')
    for key,z in [('log_kappa',np.log1p(kappa)),('log_rd_chooser',np.log(rd1)),('log_rd_opponent',np.log(rd2))]:
        cols.extend([z,z*z]);labels.extend([key,key+'_sq'])
    for key in ['clock_chooser','clock_opponent']:
        raw=frame[key].to_numpy(dtype=float)
        missing=~np.isfinite(raw)
        z=np.log1p(np.maximum(0.,np.where(missing,0.,raw)))
        cols.extend([z,missing.astype(float)]);labels.extend(['log_'+key,key+'_missing'])
    X=np.column_stack(cols)
    y=100*frame['grant'].to_numpy(dtype=float)
    return X,y,labels


def f_vector(value,grp,labels):
    ans=np.zeros(len(labels)); s=spline(np.array([value]))[0]
    for j in range(len(s)):
        ans[labels.index(f'f_{grp}_{j}')]=s[j]
    return ans


def starts_for_sorted_ids(ids):
    return np.r_[0,1+np.flatnonzero(ids[1:] != ids[:-1])]


def within_chunk_cross_products(X,y,ids):
    """Compute chooser-demeaned normal equations on a block of complete accounts."""
    starts=starts_for_sorted_ids(ids)
    count=np.diff(np.r_[starts,len(X)]).astype(float)
    sx=np.add.reduceat(X,starts,axis=0)
    sy=np.add.reduceat(y,starts)
    wx=sx/np.sqrt(count)[:,None]
    Sxx=X.T@X-wx.T@wx
    Sxy=X.T@y-(sx/count[:,None]).T@sy
    return Sxx,Sxy,len(starts)


def within_chunk_cluster_scores(X,y,ids,beta):
    starts=starts_for_sorted_ids(ids)
    count=np.diff(np.r_[starts,len(X)]).astype(float)
    r=y-X@beta
    sx=np.add.reduceat(X,starts,axis=0)
    sr=np.add.reduceat(r,starts)
    sxr=np.add.reduceat(X*r[:,None],starts,axis=0)
    U=sxr-(sx/count[:,None])*sr[:,None]
    return U.T@U, len(starts)


def choose_within_identified(sxx, labels, protected=None, relative_tol=1e-9):
    """Rank-select after within-person FWL using *scaled* Gram matrix.

    Protected focal columns must remain separately identified; redundant nuisance
    controls may be dropped.  Returns original indices, never rotates treatment
    coefficients.  Variance scaling avoids mistaking narrow-range regressors for
    zero variation in rating-point units.
    """
    sxx=np.asarray(sxx,dtype=np.float64)
    diag=np.maximum(0,np.diag(sxx))
    p=len(diag)
    if p!=len(labels):raise ValueError('Gram/labels mismatch')
    positive=diag>1e-13*np.max(diag) if p else np.zeros(0,dtype=bool)
    scale=np.sqrt(np.where(positive,diag,1))
    corr=sxx/scale[:,None]/scale[None,:]
    corr=(corr+corr.T)/2
    focal=[i for i,v in enumerate(labels) if (protected(v) if protected else False)]
    order=focal+[i for i in range(p) if i not in focal]
    keep=[];drop=[]
    for j in order:
        if not positive[j]:resid=0.0
        elif not keep:resid=max(0,float(corr[j,j]))
        else:
            kk=corr[np.ix_(keep,keep)]
            vec=corr[keep,j]
            resid=float(corr[j,j]-vec@np.linalg.lstsq(kk,vec,rcond=1e-11)[0])
        if resid < relative_tol:
            if j in focal:
                raise ValueError(f'FAIL CLOSED: focal coefficient not identified after account FE: {labels[j]}; residual fraction {resid:.4g}')
            drop.append({'regressor':labels[j],'residual_variance_fraction':max(0,resid),'why':'redundant or zero within-account variation'})
        else:keep.append(j)
    return sorted(keep),drop
