"""Opportunity-weighted LPM with absorbed chooser effects and exact cluster scores.

No dense N-by-number-of-choosers array is constructed. Full-model residual
degrees of freedom include the absorbed chooser effects. Only the target
coefficient and its uncertainty are reported.
"""
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
import math
import numpy as np
from scipy import sparse, stats
from common import require

CATS = ['month', 'speed', 'rating_tier', 'board_bin', 'ply_bin', 'gap_bin']
NUMS = ['payoff10', 'premium10', 'crd100', 'drd100', 'log_cc', 'log_dc', 'cc_missing', 'dc_missing']

def matrix(data, cats, nums):
    n = len(data['y'])
    rr = [np.arange(n)]
    cc = [np.zeros(n, dtype=int)]
    vv = [np.asarray(data['same'], float)]
    levels = {}
    names = ['same_country']
    k = 1
    for name in cats:
        values = np.asarray(data[name], str)
        lev, codes = np.unique(values, return_inverse=True)
        levels[name] = lev.tolist()
        mask = codes > 0
        rr.append(np.flatnonzero(mask))
        cc.append(k + codes[mask] - 1)
        vv.append(np.ones(mask.sum()))
        names.extend(name + ':' + v for v in lev[1:])
        k += len(lev) - 1
    for name in nums:
        values = np.asarray(data[name], float)
        require(np.isfinite(values).all(), 'Missing/nonfinite numeric covariate: ' + name)
        rr.append(np.arange(n))
        cc.append(np.full(n, k))
        vv.append(values)
        names.append(name)
        k += 1
    X = sparse.csr_matrix((np.concatenate(vv), (np.concatenate(rr), np.concatenate(cc))), shape=(n, k))
    return X, levels, names

def inference(beta, variance, df):
    if variance is None or variance <= 0 or not math.isfinite(variance) or df < 1:
        return dict(status='NONPOSITIVE_VARIANCE_OR_INSUFFICIENT_CLUSTERS', variance=variance)
    se = math.sqrt(variance)
    critical = float(stats.t.ppf(.975, df))
    return dict(status='ESTIMATED', standard_error_pp=100*se,
                ci_low_pp=100*(beta-critical*se), ci_high_pp=100*(beta+critical*se),
                p_value=float(2*stats.t.sf(abs(beta/se), df)), df=int(df))

def fit(data, cats, nums, switchers_only=False):
    d = {k: np.asarray(v) for k, v in data.items()}
    n0 = len(d['y'])
    if n0 == 0:
        return dict(status='NO_ELIGIBLE_ROWS', eligible_n=0)
    require(np.isin(d['y'], [0, 1]).all() and np.isin(d['same'], [0, 1]).all(), 'Nonbinary outcome/treatment')
    require(all(len(v) == n0 for v in d.values()), 'Array lengths differ')
    _, original_groups = np.unique(d['chooser'], return_inverse=True)
    counts0 = np.bincount(original_groups)
    sums0 = np.bincount(original_groups, weights=d['same'])
    switchers0 = (sums0 > 0) & (sums0 < counts0)
    mask = counts0[original_groups] > 1
    if switchers_only:
        mask &= switchers0[original_groups]
    d = {k: v[mask] for k, v in d.items()}
    n = len(d['y'])
    base = dict(eligible_n=n0, eligible_choosers=len(counts0),
                eligible_switchers=int(switchers0.sum()), dropped_singleton_rows=int((counts0 == 1).sum()),
                switchers_only=switchers_only, estimation_n=n)
    if n < 3:
        return dict(**base, status='INSUFFICIENT_ROWS')
    users, groups = np.unique(d['chooser'], return_inverse=True)
    g = len(users)
    counts = np.bincount(groups).astype(float)
    y = np.asarray(d['y'], float)
    treatment = np.asarray(d['same'], float)
    ysum = np.bincount(groups, weights=y)
    ts = np.bincount(groups, weights=treatment)
    switchers = (ts > 0) & (ts < counts)
    outcome_switchers = (ysum > 0) & (ysum < counts)
    w = ts * (counts-ts) / counts
    base.update(choosers=g, grants=int(y.sum()), same_opportunities=int(treatment.sum()),
                different_opportunities=int(n-treatment.sum()), same_grants=int(y[treatment == 1].sum()),
                different_grants=int(y[treatment == 0].sum()), same_country_switchers=int(switchers.sum()),
                outcome_switchers=int(outcome_switchers.sum()),
                switchers_with_outcome_variation=int((switchers & outcome_switchers).sum()),
                simple_within_weight=float(w.sum()),
                simple_within_weight_never_grant_share=float(w[ysum == 0].sum()/w.sum()) if w.sum() else None)
    X, levels, names = matrix(d, cats, nums)
    D = sparse.csr_matrix((np.ones(n), (groups, np.arange(n))), shape=(g, n))
    sx = (D @ X).tocsr()
    meanx = sx.multiply((1/counts)[:, None]).tocsr()
    A = (X.T @ X - sx.T @ meanx).toarray()
    A = (A + A.T)/2
    b = np.asarray(X.T @ y - sx.T @ (ysum/counts)).ravel()
    diag = np.diag(A)
    # Remove columns with effectively zero within-group sum of squares.
    # Normalize the remaining cross-product matrix before rank detection.
    active = diag > 1e-12
    if not active[0]:
        return dict(**base, status='TARGET_NOT_IDENTIFIED', reason='No within-chooser same-country variation')
    ix = np.flatnonzero(active)
    scale = np.sqrt(diag[ix])
    Z = A[np.ix_(ix, ix)]/np.outer(scale, scale)
    eig, V = np.linalg.eigh(Z)
    require(eig.min() > -1e-7, 'Within cross-product matrix is materially indefinite')
    threshold = max(1e-11, float(eig.max())*1e-10)
    keep = eig > threshold
    rank = int(keep.sum())
    if float(np.sum(V[0, ~keep]**2)) > 1e-8:
        return dict(**base, status='TARGET_NOT_IDENTIFIED', reason='Same-country indicator absorbed by controls')
    bread = (V[:, keep]/eig[keep]) @ V[:, keep].T / np.outer(scale, scale)
    beta = np.zeros(X.shape[1])
    beta[ix] = bread @ b[ix]
    target_bread = np.zeros(X.shape[1])
    target_bread[ix] = bread[0]
    residual = y - np.asarray(X @ beta).ravel() - (ysum/counts - np.asarray(meanx @ beta).ravel())[groups]
    influence = (np.asarray(X @ target_bread).ravel() - np.asarray(meanx @ target_bread).ravel()[groups]) * residual
    residual_df = n - g - rank
    if residual_df <= 0 or g < 2:
        return dict(**base, status='INSUFFICIENT_RESIDUAL_DF', residual_df=residual_df)
    # Conventional CR1 with the rank of the complete model, including alpha_i.
    df_factor = (n-1)/residual_df
    def variance(codes):
        scores = np.bincount(codes, weights=influence)
        clusters = len(scores)
        return (float(scores @ scores) * clusters/(clusters-1) * df_factor if clusters > 1 else None), clusters
    vc, gc = variance(groups)
    _, recipient_groups = np.unique(d['recipient'], return_inverse=True)
    vr, gr = variance(recipient_groups)
    _, pair_groups = np.unique(np.column_stack((d['chooser'], d['recipient'])), axis=0, return_inverse=True)
    vp, gp = variance(pair_groups)
    two_way = vc + vr - vp if vr is not None and vp is not None else None
    result = dict(**base, status='ESTIMATED', coefficient_pp=100*float(beta[0]),
                  chooser_cluster=inference(float(beta[0]), vc, gc-1),
                  recipient_cluster=inference(float(beta[0]), vr, gr-1),
                  two_way_cluster=inference(float(beta[0]), two_way, min(gc, gr)-1),
                  variance_components=dict(chooser=vc, recipient=vr, chooser_recipient_pair=vp, two_way=two_way),
                  recipient_clusters=gr, pair_clusters=gp, within_rank=rank, full_model_rank=g+rank,
                  residual_df=residual_df, cr1_df_factor=df_factor,
                  normalized_eigenvalue_min_retained=float(eig[keep].min()),
                  normalized_condition_number=float(eig[keep].max()/eig[keep].min()),
                  max_chooser_residual_sum=float(np.max(np.abs(np.bincount(groups, weights=residual)))),
                  cats=cats, nums=nums, categorical_levels=levels,
                  invariant_columns=[names[i] for i in np.flatnonzero(~active)],
                  se_method='CR1 with full-model rank including absorbed chooser effects; all months pooled',
                  warning='Unweighted association among acquired flag setters; not a population or causal effect')
    require(result['max_chooser_residual_sum'] < 1e-6, 'Chooser absorption residual check failed')
    return result
