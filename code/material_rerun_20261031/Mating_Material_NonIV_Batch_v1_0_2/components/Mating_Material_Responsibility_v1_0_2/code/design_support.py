"""Exact zero-information directions, certified from the original X'X shards.

No rank threshold is added. A column qualifies only when every within-chooser
sum of squares and its entire cross-product row are exactly zero. Nonzero
aliased columns remain in the full covariance comparison.
"""
from util import *
import numpy as np


def certify(paths, specs, fits, row_support, output):
    supports = {r['model']: r for r in row_support}
    records = []
    for j, (spec, fit) in enumerate(zip(specs, fits)):
        k = len(fit['names'])
        diagonal = np.zeros(k)
        cross_max = np.zeros(k)
        for path in paths:
            with np.load(path, allow_pickle=False) as z:
                xx = z[f'm{j}_xx']
            require(xx.shape == (k, k) and np.isfinite(xx).all(), 'Invalid design moments')
            require((np.diag(xx) >= 0).all(), 'Negative within sum of squares')
            diagonal += np.diag(xx)
            cross_max = np.maximum(cross_max, np.max(np.abs(xx), axis=1))
        zeros = np.flatnonzero(diagonal == 0)
        require((cross_max[zeros] == 0).all(), 'Zero norm with nonzero cross products')
        records.append(dict(model=spec['name'], terms=fit['names'],
            within_sum_squares=diagonal.tolist(),
            exact_zero_terms=[fit['names'][i] for i in zeros],
            row_set_sha256=supports[spec['name']]['row_set_sha256'],
            source='Original first-pass within-chooser cross products, all shards',
            numerical_zero_threshold=0))
    save(output, records)
    return records


def exact_zero_indices(record, names, row_hash, actual_status, archived_status):
    require(record['terms'] == names, 'Design support order differs')
    require(record['row_set_sha256'] == row_hash, 'Design support sample differs')
    require(record['numerical_zero_threshold'] == 0, 'Design support used a tolerance')
    ss = np.asarray(record['within_sum_squares'], float)
    require(ss.shape == (len(names),) and np.isfinite(ss).all() and (ss >= 0).all(),
            'Invalid within sum of squares')
    indices = np.flatnonzero(ss == 0)
    require(record['exact_zero_terms'] == [names[i] for i in indices],
            'Design support zero-column inventory differs')
    for i in indices:
        require(actual_status[names[i]] == archived_status[names[i]] == 'NOT_ESTIMABLE',
                'A reported estimable term cannot be exempted: ' + names[i])
    return indices


def canonical_covariance_comparison(actual, expected, names, zeros, compare):
    """Compare the canonical representative; preserve the unmodified verdict.

    An exactly zero column is an independent null coordinate. Its covariance
    row has no identified meaning; the canonical inverse has a zero row there.
    The raw matrices remain in the report. Every other entry, including entries
    between nonzero but aliased columns, keeps the original tolerance.
    """
    raw = compare(actual, expected, names)
    a = np.array(actual, dtype=float, copy=True)
    b = np.array(expected, dtype=float, copy=True)
    # Gross corruption of a null coordinate must still fail. This checks only
    # that the discarded entries are small at the matrix's scale; it never
    # substitutes for the exact design proof or changes a retained entry.
    overall = max(float(np.max(np.abs(a))), float(np.max(np.abs(b))), 1.)
    null_limit = 2e-8 + 2e-7 * overall
    if len(zeros):
        require(max(float(np.max(np.abs(a[zeros]))), float(np.max(np.abs(b[zeros]))))
                <= null_limit, 'Gross covariance error in an exact-zero design coordinate')
        a[zeros, :] = 0.; a[:, zeros] = 0.
        b[zeros, :] = 0.; b[:, zeros] = 0.
    checked = compare(a, b, names)
    return dict(checked, raw_passed=raw['passed'],
        raw_max_absolute_difference=raw['max_absolute_difference'],
        raw_max_tolerance_ratio=raw['max_tolerance_ratio'],
        exact_zero_columns=len(zeros),
        canonicalization='Only columns with exactly zero within-chooser information; raw matrices retained',
        retained_entry_tolerances_changed=False)
