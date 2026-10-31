"""Memory-bounded implementation of the frozen checked FE solver.

Algorithm copied from env_numerics.py, unchanged summation, tolerance, scaling,
energy checks and final orthogonality certificate. Only buffer ownership differs:
the caller allocates a private Fortran matrix, so a second full copy is redundant.
The vendored reference remains unchanged and is used for equivalence tests.
"""
import platform
import time
import numpy as np

SOLVER = 'contiguous_sorted_group_means_owned_buffer_v1'
COV_BLOCK_BYTES = 384*1024**2


class AbsorptionError(RuntimeError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def _plan(values, n):
    values = np.asarray(values)
    if values.ndim != 1 or len(values) != n:
        raise ValueError('Fixed-effect labels must have one value per model row')
    if values.dtype.kind not in 'iu' or not np.isfinite(values).all():
        raise ValueError('Fixed-effect labels must be finite integers')
    _, codes = np.unique(values, return_inverse=True)
    codes = np.ascontiguousarray(codes, dtype=np.intp)
    order = np.argsort(codes, kind='stable')
    sorted_codes = codes[order]
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_codes)) + 1]
    counts = np.diff(np.r_[starts, n]).astype(np.float64)
    if len(counts) != int(codes.max()) + 1 or int(counts.sum()) != n or np.any(counts < 1):
        raise ValueError('Fixed-effect group accounting failed')
    return codes, order, starts, counts


def _group_means(column, plan, work):
    _, order, starts, counts = plan
    np.take(column, order, out=work)
    return np.add.reduceat(work, starts) / counts


def absorb_owned(matrix, groups, tol=1e-10, max_iter=1000, column_names=None, publish=None):
    start = time.monotonic()
    source = np.asarray(matrix, dtype=np.float64)
    if source.ndim != 2 or min(source.shape) < 1:
        raise ValueError('Absorption requires a nonempty two-dimensional matrix')
    n, p = source.shape
    if not groups or tol <= 0 or max_iter < 1:
        raise ValueError('Invalid absorption settings')
    names = list(column_names or ['column_' + str(k) for k in range(p)])
    if len(names) != p:
        raise ValueError('Absorption column names differ from matrix width')
    diag = dict(solver=SOLVER, status='RUNNING', rows=n, columns=p,
                numpy_version=np.__version__, platform=platform.system(),
                machine=platform.machine(), tolerance=tol, max_iterations=max_iter,
                group_summation='sorted_reduceat', column_storage='Fortran_contiguous',
                no_rows_removed=True, no_ridge=True, iteration=0)

    def emit():
        diag['elapsed_seconds'] = time.monotonic() - start
        if publish is not None:
            publish(dict(diag))

    def fail(reason):
        diag.update(status='FAILED', reason=reason)
        emit()
        raise AbsorptionError('Fixed-effect calculation failed: ' + reason, dict(diag))

    maxima = np.empty(p)
    for k in range(p):
        col = source[:, k]
        if not np.isfinite(col).all():
            diag['column'] = names[k]
            fail('NONFINITE_INPUT')
        maxima[k] = np.max(np.abs(col))
    scale = max(1., float(maxima.max()))
    # ldexp by a power of two avoids a new rounding error from arbitrary scaling.
    exponent = max(0, int(np.frexp(scale)[1]))
    threshold = tol * float(np.ldexp(scale, -exponent))
    if source.dtype != np.float64 or not source.flags.f_contiguous or not source.flags.owndata:
        raise ValueError('absorb_owned requires its own Fortran float64 allocation')
    a = source
    np.ldexp(a, -exponent, out=a)
    plans = [_plan(g, n) for g in groups]
    diag['group_sizes'] = [dict(groups=len(t[3]), smallest=int(t[3].min()),
                               largest=int(t[3].max())) for t in plans]
    diag['input_max_abs_by_column'] = dict(zip(names, maxima.tolist()))
    diag['power_of_two_exponent'] = exponent
    diag['absolute_tolerance_original_units'] = tol * scale
    original_energy = np.array([np.dot(a[:, k], a[:, k]) for k in range(p)])
    previous_energy = original_energy.copy()
    work = np.empty(n, dtype=np.float64)
    shift = np.empty(n, dtype=np.float64)
    emit()
    last_emit = time.monotonic()
    for it in range(1, max_iter + 1):
        diag['iteration'] = it
        biggest = 0.
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            try:
                for gi, plan in enumerate(plans):
                    diag['group_index'] = gi
                    for k in range(p):
                        diag['column'] = names[k]
                        means = _group_means(a[:, k], plan, work)
                        if not np.isfinite(means).all():
                            fail('NONFINITE_GROUP_MEAN')
                        biggest = max(biggest, float(np.max(np.abs(means))))
                        np.take(means, plan[0], out=shift)
                        np.subtract(a[:, k], shift, out=a[:, k])
                energy = np.array([np.dot(a[:, k], a[:, k]) for k in range(p)])
                if not np.isfinite(energy).all():
                    fail('NONFINITE_RESIDUAL')
                allowance = 1e-10 * np.maximum(original_energy, np.finfo(float).tiny)
                if np.any(energy > previous_energy + allowance):
                    k = int(np.argmax(energy - previous_energy - allowance))
                    diag['column'] = names[k]
                    fail('PROJECTION_INCREASED_SUM_OF_SQUARES')
                previous_energy = energy
            except FloatingPointError:
                fail('FLOATING_POINT_ERROR_IN_PROJECTION')
        diag['largest_removed_mean_original_units'] = float(np.ldexp(biggest, exponent))
        if time.monotonic() - last_emit >= 25:
            emit()
            last_emit = time.monotonic()
        if biggest > threshold:
            continue
        # Explicitly check all groups together after a full sweep; update size
        # alone is not a certificate that the residual is orthogonal to FEs.
        checks = []
        for plan in plans:
            checks.append(max(float(np.max(np.abs(_group_means(a[:, k], plan, work)))) for k in range(p)))
        if not np.isfinite(checks).all():
            fail('NONFINITE_FINAL_ORTHOGONALITY_CHECK')
        if max(checks) > threshold:
            continue
        with np.errstate(over='raise', invalid='raise'):
            try:
                np.ldexp(a, exponent, out=a)
            except FloatingPointError:
                fail('NONFINITE_RESTORED_RESIDUAL')
        if not all(np.isfinite(a[:, k]).all() for k in range(p)):
            fail('NONFINITE_RESTORED_RESIDUAL')
        diag.update(status='CONVERGED', iterations=it,
                    final_max_group_mean_original_units=[float(np.ldexp(x, exponent)) for x in checks],
                    final_to_initial_sum_of_squares=float(energy.sum()/original_energy.sum()) if original_energy.sum() else 0.)
        diag.pop('column', None)
        diag.pop('group_index', None)
        emit()
        return a, diag
    fail('ITERATION_LIMIT_WITHOUT_CERTIFIED_CONVERGENCE')


def shared_meat(score, codes, with_date=True):
    """Same dyadic OR date CR0, without the 2n-by-p duplicated score matrix.

    Keep one grouped-sum matrix alive at a time. In the two-role terms accumulate
    each role separately, then add. This changes only floating-point summation
    order; the account/pair/date inclusion-exclusion expression is unchanged.
    """
    score = np.asarray(score, dtype=float)
    if score.ndim == 1:
        score = score[:, None]
    n, p = score.shape
    result = np.zeros((p, p))
    terms = [('accounts', 1, True), ('pairs', -1, False)]
    if with_date:
        terms += [('dates', 1, False), ('account_dates', -1, True), ('pair_dates', 1, False)]
    for key, sign, both in terms:
        code = codes[key]
        size = int(code.max()) + 1
        def aggregate(start, stop):
            sums = np.empty((size, stop-start), dtype=float, order='F')
            for k in range(start, stop):
                sums[:, k-start] = np.bincount(code[:n], weights=score[:, k], minlength=size)
                if both:
                    sums[:, k-start] += np.bincount(code[n:], weights=score[:, k], minlength=size)
            return sums
        # A full n-group by 15-trait matrix can itself exceed a gigabyte.
        # Use <=4-column blocks when it exceeds 384 MiB; each block product is
        # the same group-sum outer product. No covariance approximation.
        if size*p*8 <= COV_BLOCK_BYTES:
            sums=aggregate(0,p);result+=sign*(sums.T@sums);del sums
        else:
            width=min(4,max(1,int(COV_BLOCK_BYTES//(size*8))))
            for left in range(0,p,width):
                end=min(p,left+width);a=aggregate(left,end)
                result[left:end,left:end]+=sign*(a.T@a)
                for right in range(0,left,width):
                    rend=min(p,right+width);b=aggregate(right,rend);v=sign*(a.T@b)
                    result[left:end,right:rend]+=v
                    result[right:rend,left:end]+=v.T
                    del b
                del a
    return result
