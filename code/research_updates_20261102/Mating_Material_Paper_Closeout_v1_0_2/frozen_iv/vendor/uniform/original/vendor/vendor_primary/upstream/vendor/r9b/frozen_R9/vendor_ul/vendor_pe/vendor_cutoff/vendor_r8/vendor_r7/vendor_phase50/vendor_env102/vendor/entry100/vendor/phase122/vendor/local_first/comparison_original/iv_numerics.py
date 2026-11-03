"""Small, independently testable numerical routines for a single-score IV pilot.

No econometric identification is inferred by these routines. Inference treats
historical scores as fixed regressors, conditional on the recorded history.
Cluster covariance is CR0 (no undocumented degrees-of-freedom correction).
"""
from __future__ import annotations
import math
import numpy as np


def user_hash(x):
    """Stable SplitMix64 hash; Python's randomized hash is never used."""
    x = np.asarray(x, dtype=np.uint64).copy()
    with np.errstate(over='ignore'):
        x += np.uint64(0x9e3779b97f4a7c15)
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xbf58476d1ce4e5b9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94d049bb133111eb)
    return x ^ (x >> np.uint64(31))


def factor(*cols):
    if not cols: raise ValueError('No factor columns')
    n = len(cols[0])
    a = np.empty(n, dtype=[(f'v{k}', '<i8') for k in range(len(cols))])
    for k, v in enumerate(cols):
        if len(v) != n: raise ValueError('Unequal factor lengths')
        a[f'v{k}'] = v
    keys, code = np.unique(a, return_inverse=True)
    return keys, code.astype(np.int64)


def lookup(keys, queries):
    """Sorted structured or scalar lookup; absent keys return -1."""
    if not len(keys): return np.full(len(queries), -1, np.int64)
    p = np.searchsorted(keys, queries)
    ok = (p < len(keys))
    safe = np.minimum(p, len(keys)-1)
    ok &= keys[safe] == queries
    return np.where(ok, p, -1)


def take_zero(a, index):
    if not len(a): return np.zeros(len(index), dtype=a.dtype)
    return np.where(index >= 0, a[np.maximum(index, 0)], 0)


def state_cells(cp, ply, speed, gap):
    """500 fixed cells: five merit x four ply x five speed x five gap."""
    cp = np.asarray(cp, float)
    merit = np.select([cp <= -300, cp < -100, cp <= 100, cp < 300], [0, 1, 2, 3], default=4)
    pb = np.searchsorted(np.array([10, 30, 60]), ply, side='left')
    gb = np.searchsorted(np.array([-200, -100, 100, 200]), gap, side='left')
    return (((merit * 4 + pb) * 5 + speed) * 5 + gb).astype(np.int16)


def expanding_reference(deltas_n, deltas_s, strength=50.0):
    """As-of-month state means, excluding BOTH roles in the held-out folds.

    Input shape: lag x first-eligible-month x chooser-fold x recipient-fold x cell.
    Output: lag x month x focal-chooser-fold x focal-recipient-fold x cell.
    A fold pair is omitted from reference fitting, not from a chooser's own
    past outcomes (which supply the score). Empty references remain unavailable.
    """
    n = np.cumsum(deltas_n, axis=1)
    s = np.cumsum(deltas_s, axis=1)
    out = np.full_like(s, np.nan, dtype=float)
    K = n.shape[2]
    for jf in range(K):
        for rf in range(K):
            keep = [f for f in range(K) if f not in (jf, rf)]
            nn = n[:, :, keep, :, :][:, :, :, keep, :].sum(axis=(2, 3))
            ss = s[:, :, keep, :, :][:, :, :, keep, :].sum(axis=(2, 3))
            nt, st = nn.sum(axis=-1), ss.sum(axis=-1)
            # The tiny Jeffreys smoothing only applies to a NONEMPTY reference.
            pg = (st + 0.5) / (nt + 1.0)
            pred = (ss + strength * pg[..., None]) / (nn + strength)
            pred[nt == 0, :] = np.nan
            out[:, :, jf, rf, :] = pred
    return out


def score_month(hj, hi, ht, hy, hc, qj, qi, cutoff, model, folds=4):
    """Leave-all-pair-out raw and adjusted means at one PRESET time cutoff.

    The nuisance reference model is independently cross-fitted and fitted
    exclusively before the same cutoff. All outputs have the query-row order.
    """
    keep = np.asarray(ht) < cutoff  # strict: tied timestamps are NOT prior
    hj, hi, hy, hc = (np.asarray(a)[keep] for a in (hj, hi, hy, hc))
    nj = np.zeros(len(qj), np.int64)
    rate = np.full(len(qj), np.nan)
    pred = np.full(len(qj), np.nan)
    breadth = np.zeros(len(qj), np.int64)
    pair_removed = np.zeros(len(qj), np.int64)
    if not len(hj):
        return {'n': nj, 'raw': rate, 'adjusted': rate.copy(), 'expected': pred,
                'counterparts': breadth, 'pair_removed': pair_removed}
    jkeys, jinv = np.unique(hj, return_inverse=True)
    pkeys, pinv = factor(hj, hi)
    query_pairs = np.empty(len(qj), dtype=pkeys.dtype)
    query_pairs['v0'], query_pairs['v1'] = qj, qi
    ixj, ixp = lookup(jkeys, qj), lookup(pkeys, query_pairs)
    jn, pn = np.bincount(jinv), np.bincount(pinv)
    js = np.bincount(jinv, weights=hy, minlength=len(jkeys))
    ps = np.bincount(pinv, weights=hy, minlength=len(pkeys))
    nj = take_zero(jn, ixj) - take_zero(pn, ixp)
    pair_removed = take_zero(pn, ixp)
    ys = take_zero(js, ixj) - take_zero(ps, ixp)
    if np.any(nj < 0) or np.any(ys < 0) or np.any(ys > nj):
        raise ValueError('Invalid pair-excluded counts')
    good = nj > 0
    rate[good] = ys[good] / nj[good]
    breadth_by_j = np.bincount(np.searchsorted(jkeys, pkeys['v0']), minlength=len(jkeys))
    breadth = take_zero(breadth_by_j, ixj) - (ixp >= 0)
    hjf = (user_hash(hj) % np.uint64(folds)).astype(int)
    qrf = (user_hash(qi) % np.uint64(folds)).astype(int)
    qjf = (user_hash(qj) % np.uint64(folds)).astype(int)
    for rf in range(folds):
        rows = (qrf == rf) & good
        if not rows.any(): continue
        pr = model[hjf, rf, hc]
        # A reference can be unavailable in an early month. Do not fill it.
        valid_folds = np.array([np.isfinite(model[jf, rf]).all() for jf in range(folds)])
        valid_h = valid_folds[hjf]
        pclean = np.where(valid_h, pr, 0.0)
        jm = np.bincount(jinv, weights=pclean, minlength=len(jkeys))
        pm = np.bincount(pinv, weights=pclean, minlength=len(pkeys))
        value = take_zero(jm, ixj) - take_zero(pm, ixp)
        rows &= valid_folds[qjf]
        pred[rows] = value[rows] / nj[rows]
    return {'n': nj, 'raw': rate, 'adjusted': rate-pred, 'expected': pred,
            'counterparts': breadth, 'pair_removed': pair_removed}


def absorb(a, groups, tol=1e-10, max_iter=1000):
    """Alternating projections onto the orthogonal complement of additive FEs."""
    a = np.asarray(a, float).copy()
    if a.ndim != 2 or not np.isfinite(a).all(): raise ValueError('Invalid absorb matrix')
    codes = [np.unique(g, return_inverse=True)[1] for g in groups]
    counts = [np.bincount(g).astype(float) for g in codes]
    scale = max(1.0, float(np.max(np.abs(a))))
    for it in range(max_iter):
        biggest = 0.0
        for g, count in zip(codes, counts):
            for k in range(a.shape[1]):
                mean = np.bincount(g, weights=a[:, k], minlength=len(count)) / count
                biggest = max(biggest, float(np.max(np.abs(mean))))
                a[:, k] -= mean[g]
        if biggest <= tol * scale: return a, it+1
    raise RuntimeError(f'FE absorption did not converge in {max_iter} iterations')


def partial_out(a, groups, control_count):
    """Columns 0:control_count are controls; remaining columns are residualized."""
    a, iterations = absorb(a, groups)
    if control_count:
        x, v = a[:, :control_count], a[:, control_count:]
        gram = x.T @ x
        ev, U = np.linalg.eigh(gram)
        cutoff = max(float(np.max(ev)), 1.0) * 1e-11
        keep = ev > cutoff
        inv = (U[:, keep] / ev[keep]) @ U[:, keep].T
        v = v - x @ (inv @ (x.T @ v))
        rank = int(keep.sum())
    else: v, rank = a, 0
    return v, {'absorb_iterations': iterations, 'continuous_control_rank': rank}


def chi2_sf(value, df):
    if df < 1: return float('nan')
    if value < 0: return 1.0
    x = value / 2.0
    if x == 0: return 1.0
    if df % 2 == 0:
        k = df // 2
        terms = [math.exp(-x + j*math.log(x) - math.lgamma(j+1)) for j in range(k)]
        return min(1.0, sum(terms))
    ans = math.erfc(math.sqrt(x))
    s = 0.5
    for _ in range(df // 2):
        ans += math.exp(s*math.log(x) - x - math.lgamma(s+1))
        s += 1
    return min(1.0, ans)


def cluster_sums(score, groups):
    score = np.asarray(score, float)
    if score.ndim == 1: score = score[:, None]
    return [np.column_stack([np.bincount(g, weights=score[:, k]) for k in range(score.shape[1])])
            for g in groups]


def cluster_meat(score, groups):
    # Either one-way, or [chooser, exposure-date, chooser x date].
    sums = cluster_sums(score, groups)
    if len(sums) not in (1, 3): raise ValueError('Use one-way or two-way with intersection')
    V = sums[0].T @ sums[0]
    if len(sums) == 3: V += sums[1].T @ sums[1] - sums[2].T @ sums[2]
    return V


def cluster_codes(j, date=None):
    jcode = np.unique(j, return_inverse=True)[1]
    if date is None: return [jcode]
    dcode = np.unique(date, return_inverse=True)[1]
    _, joint = factor(j, date)
    return [jcode, dcode, joint]


def scalar_ols(y, x, groups):
    den = float(x @ x)
    if den <= 1e-20: return {'supported': False, 'reason': 'NO_RESIDUAL_VARIATION'}
    b = float(x @ y) / den
    var = float(cluster_meat(x*(y-b*x), groups)[0, 0]) / den**2
    if var <= 0 or not math.isfinite(var):
        return {'supported': False, 'coefficient': b, 'reason': 'NONPOSITIVE_CLUSTER_VARIANCE'}
    se = math.sqrt(var); stat = b/se
    return {'supported': True, 'coefficient': b, 'standard_error': se,
            'p_value_asymptotic': math.erfc(abs(stat)/math.sqrt(2)),
            'ci_low': b-1.959963984540054*se, 'ci_high': b+1.959963984540054*se,
            'wald_F_one_df': stat*stat}


def quadratic_set(A, B, C, tolerance=1e-12):
    """All real b satisfying A*b*b+B*b+C<=0. Never truncate a confidence set."""
    scale = max(abs(A), abs(B), abs(C), 1e-300)
    A, B, C = A/scale, B/scale, C/scale
    if abs(A) < tolerance:
        if abs(B) < tolerance:
            return [(-math.inf, math.inf)] if C <= tolerance else []
        r = -C/B
        return [(-math.inf, r)] if B > 0 else [(r, math.inf)]
    d = B*B - 4*A*C
    if d < -tolerance:
        return [] if A > 0 else [(-math.inf, math.inf)]
    d = max(d, 0.0)
    roots = sorted(((-B-math.sqrt(d))/(2*A), (-B+math.sqrt(d))/(2*A)))
    if A > 0: return [(roots[0], roots[1])]
    return [(-math.inf, roots[0]), (roots[1], math.inf)]


def iv_fit(y, d, z, groups):
    zz, zd, zy = float(z@z), float(z@d), float(z@y)
    if zz <= 1e-20: return {'supported': False, 'reason': 'NO_INSTRUMENT_VARIATION'}
    pi, rho = zd/zz, zy/zz
    ur, ud = y-rho*z, d-pi*z
    V = cluster_meat(np.column_stack([z*ur, z*ud]), groups)
    mineig = float(np.linalg.eigvalsh(V).min())
    psd = mineig >= -1e-10 * max(float(np.max(np.abs(V))), 1e-30)
    ans = {'supported': abs(zd)>1e-15, 'first_stage': scalar_ols(d, z, groups),
           'reduced_form': scalar_ols(y, z, groups),
           'AR_covariance_psd': bool(psd),
           'partial_first_stage_R2': zd**2/(zz*float(d@d)) if float(d@d)>0 else None}
    if not ans['supported']: ans['reason']='ZERO_FIRST_STAGE_COVARIANCE'
    else:
        b = zy/zd
        v = float(cluster_meat(z*(y-b*d), groups)[0,0])/zd**2
        ans['iv_coefficient'] = b
        if v > 0:
            se = math.sqrt(v)
            ans.update(iv_standard_error=se, iv_ci_low=b-1.959963984540054*se,
                       iv_ci_high=b+1.959963984540054*se)
        else: ans['iv_variance_reason']='NONPOSITIVE_CLUSTER_VARIANCE'
    if psd:
        critical = 3.841458820694124
        intervals = quadratic_set(zd**2-critical*V[1,1], -2*zy*zd+2*critical*V[0,1], zy**2-critical*V[0,0])
        ans['AR95_intervals'] = [[('-inf' if math.isinf(l) else float(l)),
                                ('+inf' if math.isinf(r) else float(r))] for l,r in intervals]
        ans['AR95_unbounded'] = any(math.isinf(l) or math.isinf(r) for l,r in intervals)
    else: ans['AR95_reason']='NON_PSD_TWO_WAY_CLUSTER_COVARIANCE_NOT_REPAIRED'
    return ans


def joint_balance(values, z, groups):
    zz = float(z@z)
    if zz <= 1e-20: return {'supported':False, 'reason':'NO_INSTRUMENT_VARIATION'}
    b = z@values/zz
    e = values - z[:,None]*b
    V = cluster_meat(z[:,None]*e,groups)/zz**2
    ev, U = np.linalg.eigh(V)
    cutoff = max(float(np.max(np.abs(ev))),1e-30)*1e-9
    if ev.min() < -cutoff: return {'supported':False,'reason':'NON_PSD_COVARIANCE'}
    keep = ev>cutoff
    if not keep.any(): return {'supported':False,'reason':'ZERO_RANK'}
    stat=float(np.sum((U[:,keep].T@b)**2/ev[keep]))
    return {'supported':True, 'wald_chi2':stat,'rank':int(keep.sum()),
            'p_value_asymptotic':chi2_sf(stat,int(keep.sum()))}
