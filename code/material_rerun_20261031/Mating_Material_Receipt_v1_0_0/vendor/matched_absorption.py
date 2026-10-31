"""Weighted FE projection by eliminating hour effects and solving a small system.

The matched cells and months together have few levels. Eliminating the disjoint
hour dummies leaves a small Schur complement, even with millions of rows.
No observations or FE columns are removed from the projection space.
"""
import time
import numpy as np
from scipy import sparse
from local_common import require, log


def absorb(matrix, weights, groups, tolerance=1e-10):
    z = np.asarray(matrix, dtype=float).copy()
    w = np.asarray(weights, dtype=float)
    require(len(groups) == 3, 'Schur projection expects cell, month, and hour')
    require(np.isfinite(z).all() and np.isfinite(w).all() and (w > 0).all(),
            'Invalid weighted projection input')
    codes = [np.unique(g, return_inverse=True)[1] for g in groups]
    counts = [int(c.max()) + 1 for c in codes]
    sums = [np.bincount(c, weights=w, minlength=n) for c, n in zip(codes, counts)]
    n0, n1, nh = counts
    ns = n0 + n1
    require(ns <= 4000, 'Matched cell/month system exceeds the bounded dense solver')
    log(f'Matched direct FE projection: {n0} cells, {n1} months, {nh} hours, {z.shape[1]} columns')
    c0, c1, ch = codes
    cross = sparse.coo_matrix((w, (c0, c1)), shape=(n0, n1)).tocsr()
    gram0 = sparse.bmat([[sparse.diags(sums[0]), cross],
                        [cross.T, sparse.diags(sums[1])]], format='csr')
    b = sparse.vstack([
        sparse.coo_matrix((w, (c0, ch)), shape=(n0, nh)).tocsr(),
        sparse.coo_matrix((w, (c1, ch)), shape=(n1, nh)).tocsr()], format='csr')
    gram = (gram0 - b.multiply(1 / sums[2]) @ b.T).toarray()
    scale = np.sqrt(np.concatenate(sums[:2]))
    norm = gram / scale[:, None] / scale[None, :]
    values, vectors = np.linalg.eigh((norm + norm.T) / 2)
    threshold = max(1e-12, float(values.max()) * 1e-12)
    require(float(values.min()) >= -100 * threshold, 'Indefinite matched FE Gram matrix')
    use = values > threshold
    # Null directions are redundant dummy parametrizations. Weighted residual
    # means below independently certify the full requested projection space.
    basis = vectors[:, use]
    inverse = values[use]
    del gram, gram0, norm, cross, vectors
    worst = 0.0
    refinements = 0
    start = time.monotonic()
    for j in range(z.shape[1]):
        column = z[:, j]
        for iteration in range(1, 5):
            hour_mean = np.bincount(ch, weights=w * column, minlength=nh) / sums[2]
            totals = np.concatenate([np.bincount(c, weights=w * column, minlength=n)
                                     for c, n in zip(codes[:2], counts[:2])])
            rhs = (totals - b @ hour_mean) / scale
            beta = (basis @ ((basis.T @ rhs) / inverse)) / scale if use.any() else np.zeros(ns)
            column -= beta[c0] + beta[n0 + c1]
            column -= np.bincount(ch, weights=w * column, minlength=nh)[ch] / sums[2][ch]
            error = max(float(np.max(np.abs(np.bincount(c, weights=w * column, minlength=n) / sw)))
                        for c, n, sw in zip(codes, counts, sums))
            if error <= tolerance:
                break
        require(error <= tolerance, f'Matched direct FE certification failed: column={j}, max_mean={error:.3e}')
        worst = max(worst, error)
        refinements = max(refinements, iteration)
        if (j + 1) % 5 == 0 or j + 1 == z.shape[1]:
            elapsed = time.monotonic() - start
            eta = elapsed * (z.shape[1] - j - 1) / (j + 1)
            log(f'Matched FE columns {j+1}/{z.shape[1]}; max weighted mean {worst:.3e}; projection ETA {eta/60:.1f} min')
    return z, refinements, worst
