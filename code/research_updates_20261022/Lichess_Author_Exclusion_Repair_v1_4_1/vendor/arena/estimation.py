"""Multiway within estimation, with checked projections and chooser clustering.

Group-mean projection is verified against the recovered Stage 08 kernel.
Alternating projections add the categorical controls in the arena test.
CR1 is G/(G-1), matching the recovered K/RD SQL estimators. No slope-only or
invented absorbed-degree-of-freedom correction is added.
"""
from __future__ import annotations

import time
import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from common import load_source, require, log

_kernel = None

def kernel():
    global _kernel
    if _kernel is None:
        _kernel = load_source('source/wave1/core/08_make_core_paper_results.py', 'arena_stage08_kernel')
    return _kernel

def codes(values):
    result, levels = pd.factorize(values, sort=False)
    require(np.all(result >= 0), 'Missing fixed-effect or cluster categories')
    return result.astype(np.int32), len(levels)

def absorb(matrix, effects, tol=1e-9, max_iter=2000):
    result = np.asarray(matrix, dtype=np.float64).copy()
    require(np.all(np.isfinite(result)), 'Nonfinite regression inputs')
    if not effects:
        return result, {'iterations':0, 'orthogonality':0.0, 'method':'none'}
    scales = np.maximum(np.std(result, axis=0), 1e-5)
    counts = [np.bincount(c, minlength=n) for c,n in effects]
    for iteration in range(1,max_iter+1):
        for (c,n), count in zip(effects,counts):
            for j in range(result.shape[1]):
                means = np.bincount(c, weights=result[:,j], minlength=n) / count
                result[:,j] -= means[c]
        # Check every absorbed group; small changes alone are not a convergence test.
        error = 0.0
        for (c,n), count in zip(effects,counts):
            for j in range(result.shape[1]):
                means = np.bincount(c, weights=result[:,j], minlength=n) / count
                error = max(error, float(np.max(np.abs(means)) / scales[j]))
        if error < tol:
            return result, {'iterations':iteration, 'orthogonality':error,
                            'method':'cyclic_exact_group_projections'}
        if iteration % 100 == 0:
            log(f'  FE projection iteration {iteration}: residual group mean={error:.3g}')
    raise RuntimeError(f'Fixed effects did not converge: residual group mean={error}; tolerance={tol}')

def fit(frame, targets, controls=(), effects=('chooser',), cluster='chooser'):
    started = time.time()
    names = list(targets) + list(controls)
    required = list(dict.fromkeys(['kind',cluster,*names,*effects]))
    require(not any(frame[k].isna().any() for k in required), 'Model sample includes missing values')
    y = frame['kind'].to_numpy(dtype=np.float64)
    x = frame[names].to_numpy(dtype=np.float64)
    require(np.all(np.isfinite(y)) and np.all(np.isfinite(x)), 'Nonfinite model values')
    cl, groups = codes(frame[cluster])
    fe = [codes(frame[k]) for k in effects]
    require(len(y)>len(names)+2 and groups>1, 'Too few rows or clusters')
    projected, diagnostics = absorb(np.column_stack((y,x)), fe)
    mean_kindness = float(np.mean(y))
    n_rows = len(y)
    del x, y
    yt, xt = projected[:,0], projected[:,1:]
    scales = np.sqrt(np.mean(xt*xt,axis=0))
    kept = scales > 1e-10
    dropped = [n for n,k in zip(names,kept) if not k]
    require(not (set(targets) & set(dropped)), 'Target absorbed/no identifying variation: '+str(dropped))
    kept_names = [n for n,k in zip(names,kept) if k]
    selected = xt if np.all(kept) else xt[:,kept]
    xz = selected / scales[kept]
    gram = xz.T @ xz
    eigenvalues = np.linalg.eigvalsh(gram)
    require(eigenvalues[0] > 1e-11 * eigenvalues[-1], 'Model is rank deficient or numerically unresolved')
    invz = np.linalg.inv(gram)
    beta = (invz @ (xz.T @ yt)) / scales[kept]
    del xz
    residual = yt - selected @ beta
    scores = np.column_stack([np.bincount(cl, weights=selected[:,j]*residual, minlength=groups)
                              for j in range(len(beta))])
    inverse = invz / scales[kept][:,None] / scales[kept][None,:]
    cov0 = inverse @ (scores.T @ scores) @ inverse
    covariance = cov0 * groups/(groups-1)
    stderr = np.sqrt(np.maximum(np.diag(covariance),0))
    quantile = student_t.ppf(.975,groups-1)
    output=[]
    for i,n in enumerate(kept_names):
        stat = beta[i]/stderr[i] if stderr[i]>0 else np.nan
        output.append({'term':n,'estimate_pp':100*beta[i],'se_pp':100*stderr[i],
          'ci_low_pp':100*(beta[i]-quantile*stderr[i]),'ci_high_pp':100*(beta[i]+quantile*stderr[i]),
          'p_value':2*student_t.sf(abs(stat),groups-1),'target':n in targets})
    return {'status':'ESTIMATED','n':n_rows,'clusters':groups,
      'fixed_effects':list(effects),'fe_levels':{k:n for k,(_,n) in zip(effects,fe)},
      'controls':list(controls),'targets':list(targets),'dropped_controls':dropped,
      'covariance_terms':kept_names,'covariance_probability_units':covariance,
      'coefficients':output,'cr1_factor':groups/(groups-1),'inference':'chooser-clustered CR1; t(G-1)',
      'condition_number_scaled':float(eigenvalues[-1]/eigenvalues[0]),
      'mean_kindness_pct':100*mean_kindness,'projection':diagnostics,'seconds':time.time()-started}

def linear_contrast(result, weights):
    names=result['covariance_terms']
    w=np.array([weights.get(n,0) for n in names],float)
    require(set(weights)<=set(names), 'Contrast includes an unidentified term')
    b=np.array([r['estimate_pp'] for r in result['coefficients']])
    estimate=float(w@b)
    se=100*np.sqrt(max(0,float(w@np.asarray(result['covariance_probability_units'])@w)))
    critical=student_t.ppf(.975,result['clusters']-1)
    return {'estimate_pp':estimate,'se_pp':se,'ci_low_pp':estimate-critical*se,
            'ci_high_pp':estimate+critical*se,
            'p_value':2*student_t.sf(abs(estimate/se),result['clusters']-1) if se else None}
