"""Same OLS projections, with bounded temporary allocations and owned matrices.

No ridge, row changes, tolerance changes, or covariance changes. All full
matrices are float64. Tall fitted-value temporaries are limited to 65,536 rows.
"""
import numpy as np
import iv_numerics as num

BLOCK = 65536


def stack_columns(columns):
    if not columns:
        raise ValueError('No model columns')
    n = len(columns[0])
    a = np.empty((n, len(columns)), dtype=np.float64, order='F')
    for k, col in enumerate(columns):
        if np.asarray(col).ndim != 1 or len(col) != n:
            raise ValueError('Model column lengths differ')
        a[:, k] = col
    return a


def _inverse(gram):
    ev, u = np.linalg.eigh(gram)
    keep = ev > max(float(ev.max()), 1.) * 1e-11
    return (u[:, keep] / ev[keep]) @ u[:, keep].T, int(keep.sum())


def partial_out_owned(a, groups, control_count):
    """Consume an owned matrix; return a compact residual matrix."""
    a, iterations = num.absorb(a, groups)
    if not control_count:
        return a, dict(absorb_iterations=iterations, continuous_control_rank=0)
    x, v = a[:, :control_count], a[:, control_count:]
    inv, rank = _inverse(x.T @ x)
    beta = inv @ (x.T @ v)
    # v belongs exclusively to this estimator. Do not allocate a second NxP fit.
    for start in range(0, len(a), BLOCK):
        stop = start + BLOCK
        v[start:stop] -= x[start:stop] @ beta
    out = np.array(v, dtype=np.float64, order='F', copy=True)
    return out, dict(absorb_iterations=iterations, continuous_control_rank=rank)


def residualize_columns(absorbed, kcontrols, indices):
    """Reuse the same absorbed matrix for the frozen entry control ladder."""
    v = absorbed[:, kcontrols:]
    if not indices:
        return v, 0
    # Every current ladder level is a prefix. Retain a general checked fallback.
    if indices == list(range(len(indices))):
        x = absorbed[:, :len(indices)]
    else:
        x = absorbed[:, indices]
    inv, rank = _inverse(x.T @ x)
    beta = inv @ (x.T @ v)
    out = np.array(v, dtype=np.float64, order='F', copy=True)
    for start in range(0, len(v), BLOCK):
        stop = start + BLOCK
        out[start:stop] -= x[start:stop] @ beta
    return out, rank
