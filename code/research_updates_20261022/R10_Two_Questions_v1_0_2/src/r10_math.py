"""R10 deterministic design and chooser-FE numerical primitives.

No sklearn, fixest, or external regressors. Uses NumPy only. The producer calls
these routines on complete chooser groups; individual identities are private.
"""
from __future__ import annotations
import math
import numpy as np

POSITION = ('clearly_worse', 'modestly_worse', 'roughly_equal', 'better', 'clearly_better')
STAGE = ('0_4', '5_6', '7_8', '9_10', '11_20', '21_40', '41_80', '81plus')
SPEED = ('ultrabullet', 'bullet', 'blitz', 'rapid', 'classical')
MONTHS = tuple(f'{y}-{m:02d}' for y in (2023, 2024, 2025) for m in range(1, 13)
               if (2023, 11) <= (y, m) <= (2025, 10))


def labels_all():
    names = [f'position_{z}' for z in POSITION[1:]]
    names += [f'stage_{z}' for z in STAGE[1:]]
    names += [f'speed_{z}' for z in SPEED[1:]]
    names += [f'month_{z}' for z in MONTHS[1:]]
    names += [
        'log_chooser_clock', 'chooser_clock_missing',
        'log_opponent_clock', 'opponent_clock_missing',
        'gap_negative_per100', 'gap_positive_per100',
        'log_kappa_centered', 'log_kappa_centered_sq',
        'log_chooser_rd_centered', 'log_chooser_rd_centered_sq',
        'log_opponent_rd_centered', 'log_opponent_rd_centered_sq',
    ]
    names += [f'stage_{z}_X_competitive' for z in STAGE[1:]]
    names += [f'stage_{z}_X_{q}' for q in SPEED[1:] for z in STAGE[1:]]
    assert len(names) == 85, len(names)
    return names

NAMES = labels_all()
INDEX = {s:i for i,s in enumerate(NAMES)}


def model_indices(model: int):
    if model not in (1, 2, 3, 4): raise ValueError('Expected model 1..4')
    selected = NAMES[:38] if model == 1 else NAMES[:50]
    if model == 3: selected += NAMES[50:57]
    if model == 4: selected += NAMES[57:85]
    return np.asarray([INDEX[s] for s in selected], dtype=np.int64), list(selected)


def position_categories(v):
    v = np.asarray(v, dtype=np.float64)
    return np.select([v <= -300, v <= -101, v <= 100, v <= 299], [0,1,2,3], default=4).astype(np.int8)


def stage_categories(ply):
    p = np.asarray(ply, dtype=np.int64)
    return np.select([p <= 4, p <= 6, p <= 8, p <= 10,
                      p <= 20, p <= 40, p <= 80], list(range(7)), default=7).astype(np.int8)


def construct_design(df):
    """DataFrame has normalized numeric + pos/stage/speed_i/month_i columns.

    Returns dense 85-feature array only for one bounded chunk, and outcome in pp.
    Clock missing values are imputed 0 with indicators; all other nulls fail.
    Continuous nuisance basis is recentered or rescaled without changing its span.
    """
    n=len(df)
    x=np.zeros((n,len(NAMES)),dtype=np.float64)
    pos=df['pos'].to_numpy(dtype=np.int8)
    stage=df['stage'].to_numpy(dtype=np.int8)
    sp=df['speed_i'].to_numpy(dtype=np.int8)
    mo=df['month_i'].to_numpy(dtype=np.int8)
    if np.any((pos<0)|(pos>4)|(stage<0)|(stage>7)|(sp<0)|(sp>4)|(mo<0)|(mo>23)):
        raise ValueError('Unknown category code in regression block')
    # Binary categorical terms
    for i in range(1,5): x[:,i-1]=(pos==i)
    for i in range(1,8): x[:,4+i-1]=(stage==i)
    for i in range(1,5): x[:,11+i-1]=(sp==i)
    for i in range(1,24): x[:,15+i-1]=(mo==i)
    # Continuous environment terms, with documented full-rank rescalings
    for side, start in (('clock_chooser',38),('clock_opponent',40)):
        raw=df[side].to_numpy(dtype=np.float64)
        missing=~np.isfinite(raw)
        if np.any(raw[~missing]<0): raise ValueError('Negative recorded clock')
        x[:,start]=np.log1p(np.where(missing,0,raw))
        x[:,start+1]=missing
    gap=df['gap'].to_numpy(dtype=np.float64)
    x[:,42]=np.minimum(np.clip(gap,-600,600),0)/100
    x[:,43]=np.maximum(np.clip(gap,-600,600),0)/100
    for col,start,offset,transform in [('kappa',44,2.5,'log1p'),
                                       ('rd_chooser',46,3.5,'log'),
                                       ('rd_opponent',48,3.5,'log')]:
        a=df[col].to_numpy(dtype=np.float64)
        if np.any(~np.isfinite(a)) or np.any(a<=0):
            raise ValueError('Invalid premium or rating deviation in regression data')
        u=(np.log1p(a) if transform=='log1p' else np.log(a))-offset
        x[:,start]=u; x[:,start+1]=u*u
    competitive=pos>=2
    for i in range(1,8):x[:,50+i-1]=(stage==i)&competitive
    for k in range(1,5):
        for i in range(1,8):x[:,57+(k-1)*7+(i-1)]=(stage==i)&(sp==k)
    y=100*df['grant'].to_numpy(dtype=np.float64)
    if np.any(~np.isfinite(x)) or np.any(~np.isfinite(y)):
        raise ValueError('Nonfinite regression input')
    return x,y


def account_starts(ids):
    ids=np.asarray(ids)
    if not len(ids):return np.empty(0,dtype=np.int64)
    return np.r_[0,np.flatnonzero(ids[1:]!=ids[:-1])+1]


def chooser_within(x,y,ids):
    starts=account_starts(ids)
    counts=np.diff(np.r_[starts,len(x)]).astype(np.int64)
    sx=np.add.reduceat(x,starts,axis=0)
    sy=np.add.reduceat(y,starts)
    xbar=sx/counts[:,None]
    ybar=sy/counts
    acc_i=np.repeat(np.arange(len(starts)),counts)
    return x-xbar[acc_i], y-ybar[acc_i], xbar,ybar,counts,starts,acc_i


def chooser_crossproducts(x,y,ids):
    starts=account_starts(ids)
    n=np.diff(np.r_[starts,len(y)]).astype(np.float64)
    sx=np.add.reduceat(x,starts,axis=0)
    sy=np.add.reduceat(y,starts)
    return x.T@x-(sx/np.sqrt(n)[:,None]).T@(sx/np.sqrt(n)[:,None]), \
           x.T@y-(sx/n[:,None]).T@sy, int(len(starts)), int(n[n>=2].sum())


def identified(sxx, labels, protected, tol=1e-9):
    """Discard only redundant nuisance regressors; protected columns fail closed."""
    sxx=np.asarray(sxx,dtype=float)
    sxx=(sxx+sxx.T)/2
    d=np.maximum(0,np.diag(sxx))
    scale=np.sqrt(np.where(d>0,d,1))
    corr=sxx/scale[:,None]/scale[None,:]
    p=len(labels)
    order=[i for i,s in enumerate(labels) if protected(s)]
    order += [i for i,s in enumerate(labels) if not protected(s)]
    keep=[]; omitted=[]
    for j in order:
        if d[j]<=0: frac=0.0
        elif not keep: frac=corr[j,j]
        else:
            k=corr[np.ix_(keep,keep)]; v=corr[keep,j]
            frac=float(corr[j,j]-v@np.linalg.lstsq(k,v,rcond=1e-10)[0])
        if frac<tol:
            if protected(labels[j]):
                raise ValueError(f'Focal R10 coefficient unidentified: {labels[j]} (relative residual variance {frac:.3g})')
            omitted.append({'term':labels[j],'residual_variance_fraction':max(0,frac)})
        else: keep.append(j)
    return np.array(sorted(keep),dtype=np.int64),omitted


def solve_gram(sxx,sxy):
    scale=np.sqrt(np.diag(sxx))
    if np.any(scale<=0): raise ValueError('nonpositive Gram diagonal')
    C=sxx/scale[:,None]/scale[None,:]
    C=(C+C.T)/2
    eigen=np.linalg.eigvalsh(C)
    if eigen[0]<=1e-11:
        raise ValueError(f'Gram matrix numerically singular: min standardized eigenvalue={eigen[0]:.3g}')
    Bscaled=np.linalg.solve(C,sxy/scale)
    b=Bscaled/scale
    Binv=np.linalg.inv(C)/scale[:,None]/scale[None,:]
    return b, (Binv+Binv.T)/2, float(eigen[0])


def stage_vector(model:int,group:int,stage:int,labels:list[str]):
    """Stage-specific regressor contribution, omitting all nonstage regressors."""
    out=np.zeros(len(labels))
    if stage==0:return out
    k=STAGE[stage]
    out[labels.index('stage_'+k)]=1
    if model==3 and group==1:out[labels.index('stage_'+k+'_X_competitive')]=1
    if model==4 and group>0:out[labels.index('stage_'+k+'_X_'+SPEED[group])]=1
    return out


def position_vector(pos:int,labels:list[str]):
    out=np.zeros(len(labels))
    if pos>0:out[labels.index('position_'+POSITION[pos])]=1
    return out


def p_value(est,se):
    if not np.isfinite(se) or se<=0:return None
    return float(math.erfc(abs(float(est/se))/math.sqrt(2)))


def contrast(beta,vcov,L):
    estimate=float(L@beta)
    var=float(L@vcov@L)
    if var < -1e-9:raise ValueError(f'Negative variance {var}')
    se=math.sqrt(max(0,var))
    return estimate,se,estimate-1.96*se,estimate+1.96*se,p_value(estimate,se)


def holm(pvalues):
    # Keep a family fixed in advance; missing p means untestable (fail upstream).
    if any(v is None for v in pvalues): raise ValueError('Cannot Holm-adjust missing p-value')
    n=len(pvalues); order=np.argsort(pvalues)
    out=np.empty(n,dtype=float);mx=0.0
    for rank,j in enumerate(order):
        mx=max(mx,(n-rank)*pvalues[j]);out[j]=min(1,mx)
    return out.tolist()


def rate_if_covariance(z_cross,weights,clusters):
    """From account score + accounting moment cross-product (no row-level output)."""
    return float((clusters/(clusters-1))*(weights@z_cross@weights))


def solve_gram_rank_aware(sxx, sxy, rank_tol=1e-9):
    """Rank-aware within-chooser least squares, preserving original regressors.

    A truncated eigendecomposition of the diagonally scaled Gram matrix gives
    one coefficient representation in the identified subspace. Individual
    coefficients/contrasts MUST pass is_estimable before being interpreted.
    """
    sxx=np.asarray(sxx,dtype=np.float64)
    sxx=(sxx+sxx.T)/2
    sxy=np.asarray(sxy,dtype=np.float64)
    if not (np.isfinite(sxx).all() and np.isfinite(sxy).all()):
        raise ValueError('Nonfinite R10 cross-product input')
    diag=np.diag(sxx)
    if np.any(diag < -1e-6):raise ValueError('Negative diagonal in Gram')
    scale=np.sqrt(np.maximum(0,diag))
    scale=np.where(scale>0,scale,1.)
    C=(sxx/scale[:,None])/scale[None,:]
    C=(C+C.T)/2
    eig, Q=np.linalg.eigh(C)
    largest=float(eig[-1])
    if largest<=0:raise ValueError('No identifiable regressors')
    if eig[0]< -largest*1e-7:raise ValueError('Gram has appreciable negative eigenvalue')
    positive=eig>largest*rank_tol
    if not positive.any():raise ValueError('No Gram eigenvalue exceeds threshold')
    ep=eig[positive]
    qp=Q[:,positive]
    invC=(qp/ep[None,:])@qp.T
    inv=(invC/scale[:,None])/scale[None,:]
    inv=(inv+inv.T)/2
    b=inv@sxy
    residual=sxx@b-sxy
    standardized_residual=np.linalg.norm(residual/scale)/(max(np.linalg.norm(sxy/scale),1e-30))
    if standardized_residual>2e-6:
        raise ValueError(f'Rank-aware LS normal-equation failure: {standardized_residual:.3g}')
    info={'rank':int(positive.sum()),'parameters':int(len(eig)),
          'smallest_identified_scaled_eigenvalue':float(ep[0]),
          'largest_scaled_eigenvalue':largest,
          'discarded_eigenvalues':[float(z) for z in eig[~positive]],
          'rank_tol_relative':rank_tol,
          'relative_normal_equation_error':float(standardized_residual)}
    return b,inv,info,{'scale':scale,'null_vectors':Q[:,~positive]}


def estimable_linear(L, identification, tol=1e-6):
    """Test whether L'b is unique over the null space of X' M_FE X.

    Null basis is in scaled coordinates. An unidentifiable contrast is never
    replaced with zero or a point estimate from a minimum-norm solution.
    """
    L=np.asarray(L,dtype=np.float64)
    scale=identification['scale']
    null=identification['null_vectors']
    if len(L)!=len(scale):raise ValueError('Contrast/dimension mismatch')
    z=L/scale
    norm=float(np.linalg.norm(z))
    if norm==0:return True,0.
    ratio=float(np.linalg.norm(null.T@z)/norm) if null.shape[1] else 0.
    return ratio<=tol,ratio
