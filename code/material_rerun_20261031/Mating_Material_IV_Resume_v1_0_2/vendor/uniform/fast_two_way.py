"""Two-factor FE absorption by a sparse, normalized Schur complement.

Only the numerical solver changes. One gauge is fixed in each connected
component; no observation or fixed-effect span is removed. Final residuals
must satisfy the original group-mean tolerance and energy certificate.
"""
from fast_bootstrap import np, require, log
import concurrent.futures as cf
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import LinearOperator, cg


def absorb(v, plans, threads, tolerance):
    require(len(plans) == 2, 'Schur absorption requires exactly two FE factors')
    n, p = v.shape
    a, b = plans[0][0], plans[1][0]
    na, nb = plans[0][3], plans[1][3]
    C = sparse.coo_matrix((np.ones(n), (a, b)), shape=(len(na), len(nb))).tocsr()
    graph = sparse.bmat([[None, C], [C.T, None]], format='csr')
    components, labels = connected_components(graph, directed=False)
    del graph
    lb = labels[len(na):]
    # Fix the best-supported hour in each component. This is just a gauge:
    # its level is absorbed by the other factor in that component.
    order = np.lexsort((-nb, lb))
    anchors = order[np.r_[True, np.diff(lb[order]) != 0]]
    require(len(anchors) == components, 'FE component accounting differs')
    free = np.ones(len(nb), dtype=bool); free[anchors] = False
    inv_a, inv_b = 1 / np.sqrt(na), 1 / np.sqrt(nb)
    R = C.multiply(inv_a[:, None]).multiply(inv_b[None, :]).tocsr()[:, free]
    del C
    RT = R.T.tocsr()
    diagonal = 1 - np.asarray(R.power(2).sum(axis=0)).ravel()
    require(np.all(diagonal > 0), 'Nonpositive free Schur diagonal')
    count = int(free.sum())
    operator = LinearOperator((count, count), matvec=lambda x: x - RT @ (R @ x), dtype=float)
    preconditioner = LinearOperator((count, count), matvec=lambda x: x / diagonal, dtype=float)
    log(f'Two-way FE: {len(na):,} cells, {len(nb):,} hours, {components} components; sparse Schur solve')

    def column(k):
        y = np.array(v[:, k], dtype=float, copy=True)
        require(np.isfinite(y).all(), 'Nonfinite two-way FE input')
        energy0 = float(y @ y)
        total_iterations = 0
        # Refinement uses the actual residual group means, not the solver's
        # internal stopping flag, as the accuracy certificate.
        for refinement in range(4):
            means_a = np.bincount(a, weights=y, minlength=len(na)) / na
            y -= means_a[a]
            rhs = (np.bincount(b, weights=y, minlength=len(nb)) * inv_b)[free]
            theta = np.zeros(len(nb))
            if count and np.max(np.abs(rhs)) > 0:
                iterations = [0]
                def tick(_): iterations[0] += 1
                solution, info = cg(operator, rhs, M=preconditioner,
                    rtol=1e-13, atol=0., maxiter=max(2000, 4 * count), callback=tick)
                total_iterations += iterations[0]
                require(info >= 0 and np.isfinite(solution).all(), 'Schur CG numerical breakdown')
                theta[free] = solution
            beta = theta * inv_b
            fitted_b = beta[b]
            # Keep A exactly absorbed while removing the fitted B component.
            y -= fitted_b - (np.bincount(a, weights=fitted_b, minlength=len(na)) / na)[a]
            error = max(float(np.max(np.abs(np.bincount(g, weights=y, minlength=len(t)) / t)))
                        for g, t in ((a, na), (b, nb)))
            require(np.isfinite(error), 'Nonfinite Schur orthogonality')
            if error <= tolerance:
                energy = float(y @ y)
                require(energy <= energy0 + 1e-10 * max(energy0, np.finfo(float).tiny),
                        'FE projection increased squared norm')
                v[:, k] = y
                return dict(iterations=total_iterations, orthogonality=error,
                            refinements=refinement + 1)
        raise RuntimeError(f'Two-way FE orthogonality failed: column {k}, error {error:.3g}, tolerance {tolerance:.3g}')

    with cf.ThreadPoolExecutor(max_workers=threads) as pool:
        results = list(pool.map(column, range(p)))
    return results, dict(components=components, first_groups=len(na), second_groups=len(nb),
                        free_second_groups=count, nnz=int(R.nnz), gauge='one_second_factor_per_component')
