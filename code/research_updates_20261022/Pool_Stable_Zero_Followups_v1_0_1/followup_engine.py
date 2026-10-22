"""Local polynomial FE moments and chooser-clustered influence functions.

No continuity or derivative equality is imposed. All nuisance terms and their
slopes are inherited from the stable-rating runner. State interactions apply to
the entire local polynomial, jump, and point-mass terms. Absorbed effects remain
chooser × board state, while uncertainty clusters across states by chooser.
"""
from __future__ import annotations
import json
import numpy as np
from scipy import sparse
from scipy.stats import t as student_t, f as fdist
from fe_engine import onehot, make_layout, solve
from surface_model import controls
from pooled_engine import absorption, states, within_crossproducts, STATES
from followup_specs import Spec, TERMS, SUPPORT

NUISANCE_SECTIONS = ('continuous', 'month', 'speed', 'board', 'k20', 'logk')


def nuisance_names(edges):
    names, sections = make_layout(edges)
    return [names[i] for k in NUISANCE_SECTIONS for i in sections[k]]


def nuisance_design(f, edges):
    original = dict(ply_count=f['ply'], chooser_pre_rd_v2=f['crd'],
                    disconnected_pre_rd_v2=f['drd'], chooser_pre_sigma_v2=f['cvol'],
                    disconnected_pre_sigma_v2=f['dvol'])
    parts = [sparse.csr_matrix(controls(original))]
    for k, levels in [('month', 24), ('speed', 5)]:
        parts.append(onehot(f[k].astype(int), levels)[:, 1:])
    board = np.searchsorted(np.arange(-600., 601., 50.), f['board'], side='right')
    parts.append(onehot(board, 26)[:, 1:])
    codes = np.searchsorted(edges['k20'], f['K'], side='left')
    parts.append(onehot(codes, len(edges['k20'])+1)[:, 1:])
    parts.append(sparse.csr_matrix(np.log(f['K'])[:, None]))
    X = sparse.hstack(parts, format='csr'); X.eliminate_zeros()
    return X


def core_terms(spec):
    return ['left_z', 'right_z', 'right_indicator', 'center_atom'] + (
        ['left_z_squared', 'right_z_squared'] if spec.degree == 2 else [])


def contexts(spec):
    return STATES if spec.scope == 'by_state' else ('pooled_competitive',)


def side_codes(x, spec):
    d = x-spec.center
    atom = np.abs(d) <= 1e-12*max(1., spec.h)
    return np.where(atom, 1, np.where(d < 0, 0, 2))


def window(original, spec, Z=None):
    before = np.abs(original[spec.axis]-spec.center) <= spec.h
    exact_tie = np.abs(original['gap']) <= 1e-12
    mask = before & ~exact_tie if spec.omit_ties else before
    ix = np.flatnonzero(mask)
    source = (int(before.sum()), int((before & exact_tie).sum()), len(ix))
    f = {k: v[ix] for k, v in original.items()}
    if not len(ix):
        return f, None, None, source
    a = absorption(f)
    keep = a['n'][a['u']] >= 2
    ix = ix[keep]
    f = {k: v[keep] for k, v in f.items()}
    if not len(ix):
        return f, None, None, source
    return f, absorption(f), (Z[ix] if Z is not None else None), source


def design(f, spec, Z):
    side = side_codes(f[spec.axis], spec)
    z = (f[spec.axis]-spec.center)/spec.h
    cols = [np.where(side == 0, z, 0), np.where(side == 2, z, 0), side == 2, side == 1]
    if spec.degree == 2:
        cols.extend([np.where(side == 0, z*z, 0), np.where(side == 2, z*z, 0)])
    core = np.column_stack(cols)
    if spec.scope == 'by_state':
        st = states(f['board'])
        core = np.column_stack([core*(st == j)[:, None] for j in range(3)])
    return sparse.hstack([sparse.csr_matrix(core), Z], format='csr'), side


def contrasts(spec, p):
    q = len(contexts(spec)); stride = len(core_terms(spec))
    R = np.zeros((q*len(TERMS), p)); labels = []
    for s, context in enumerate(contexts(spec)):
        off = s*stride; j = s*len(TERMS)
        R[j, off] = 1/spec.h
        R[j+1, off+1] = 1/spec.h
        R[j+2, off:off+2] = [-1/spec.h, 1/spec.h]
        R[j+3, off+2] = 1
        R[j+4, off+3] = 1
        labels.extend((context, term) for term in TERMS)
    return R, labels


class Moments:
    def __init__(self, edges, spec):
        self.edges = edges; self.spec = spec
        self.core_size = len(core_terms(spec))*len(contexts(spec))
        self.names = [f'{c}:{t}' for c in contexts(spec) for t in core_terms(spec)] + nuisance_names(edges)
        p = len(self.names); q = len(contexts(spec))
        self.S = np.zeros((p, p)); self.b = np.zeros(p)
        self.N = self.G = self.H = self.events = 0
        self.source_before_omit = self.source_ties = self.source_N = 0
        self.n = np.zeros((q, 3), dtype=np.int64)
        self.ev = np.zeros_like(self.n)
        self.month = np.zeros((q, 3, 24), dtype=np.int64)
        self.cross = np.zeros(q, dtype=np.int64)
        self.atom_cross = np.zeros(q, dtype=np.int64)
        self.group_G = np.zeros(q, dtype=np.int64)
        # Explicit displayed-rating support; ±501 are overflow categories.
        self.gap_hist = np.zeros((q, 3, 1003), dtype=np.int64)
        self.noninteger_gap = 0
        self.x_hist = np.zeros((q, 40), dtype=np.int64)

    def add(self, original, Z=None):
        if Z is None: Z = nuisance_design(original, self.edges)
        f, a, z, source = window(original, self.spec, Z)
        self.source_before_omit += source[0]; self.source_ties += source[1]; self.source_N += source[2]
        if not len(f['y']): return
        X, side = design(f, self.spec, z); y = f['y'].astype(float)
        S, b = within_crossproducts(X, y, a)
        self.S += S; self.b += b
        self.N += len(y); self.G += a['G']; self.H += a['H']; self.events += int(y.sum())
        grp = a['state'] if self.spec.scope == 'by_state' else np.zeros(len(y), dtype=int)
        np.add.at(self.n, (grp, side), 1)
        np.add.at(self.ev, (grp, side), f['y'])
        np.add.at(self.month, (grp, side, f['month'].astype(int)), 1)
        rounded = np.rint(f['gap'])
        self.noninteger_gap += int((np.abs(f['gap']-rounded) > 1e-8).sum())
        gapcode = np.clip(rounded, -501, 501).astype(int)+501
        np.add.at(self.gap_hist, (grp, side, gapcode), 1)
        xcode = np.clip(np.floor(((f[self.spec.axis]-self.spec.center)/self.spec.h+1)*20), 0, 39).astype(int)
        np.add.at(self.x_hist, (grp, xcode), 1)
        present = (a['A'] @ onehot(side, 3)).toarray() > 0
        for j in range(len(contexts(self.spec))):
            use = a['unit_state'] == j if self.spec.scope == 'by_state' else np.ones(a['H'], dtype=bool)
            cross = use & present[:, 0] & present[:, 2]
            atom_cross = use & present[:, 1] & (present[:, 0] | present[:, 2])
            self.cross[j] += int(np.count_nonzero(a['chooser_unit'] @ cross.astype(int)))
            self.atom_cross[j] += int(np.count_nonzero(a['chooser_unit'] @ atom_cross.astype(int)))
            self.group_G[j] += int(np.count_nonzero(a['chooser_unit'] @ use.astype(int)))

    def merge(self, other):
        if self.edges != other.edges or self.spec != other.spec:
            raise ValueError('Different moment specifications')
        for k in self.scalar_fields()+self.array_fields(): setattr(self, k, getattr(self, k)+getattr(other, k))

    @staticmethod
    def scalar_fields():
        return ('N', 'G', 'H', 'events', 'source_before_omit', 'source_ties', 'source_N', 'noninteger_gap')

    @staticmethod
    def array_fields():
        return ('S', 'b', 'n', 'ev', 'month', 'cross', 'atom_cross', 'group_G', 'gap_hist', 'x_hist')

    def save(self, path):
        meta = dict(edges=self.edges, spec=self.spec.dictionary(), **{k: int(getattr(self, k)) for k in self.scalar_fields()})
        np.savez_compressed(path, metadata=np.array(json.dumps(meta)), **{k: getattr(self, k) for k in self.array_fields()})

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z['metadata'])); obj = cls(meta.pop('edges'), Spec(**meta.pop('spec')))
            for k, v in meta.items(): setattr(obj, k, v)
            for k in obj.array_fields(): setattr(obj, k, z[k].copy())
        return obj


def fit(m):
    C = np.eye(len(m.b))[:m.core_size]
    R, labels = contrasts(m.spec, len(m.b))
    model = solve(m.S, m.b, np.vstack([C, R]))
    model.update(spec=m.spec, core_size=m.core_size, C=C, R=R, labels=labels,
                 estimates=C@model['beta'], projection=model['bread']@C.T,
                 contrast_identified=model['identified'][m.core_size:].copy(),
                 contrast_projection_error=model['projection_error'][m.core_size:].copy(),
                 identified=model['identified'][:m.core_size].copy(),
                 meat=np.zeros((m.core_size, m.core_size)), score_sum=np.zeros(m.core_size))
    model['normal_equation_relative_error'] = float(np.linalg.norm(m.S@model['beta']-m.b)/max(1, np.linalg.norm(m.b)))
    return model


def scores(original, edges, model, Z=None):
    if Z is None: Z = nuisance_design(original, edges)
    f, a, z, _ = window(original, model['spec'], Z)
    if not len(f['y']): return np.zeros(0, dtype=np.int64), np.zeros((0, model['core_size']))
    X, _ = design(f, model['spec'], z)
    e = f['y']-X@model['beta']
    e -= np.asarray(a['A']@e).ravel()[a['u']]/a['n'][a['u']]
    out = np.asarray((a['B']@X.multiply(e[:, None])) @ model['projection'])
    model['meat'] += out.T@out; model['score_sum'] += out.sum(axis=0)
    return f['chooser'][np.r_[True, f['chooser'][1:] != f['chooser'][:-1]]], out


def factor(m, model):
    denominator = m.N-m.H-model['rank']
    return m.G/(m.G-1)*(m.N-1)/denominator if m.G > 1 and denominator > 0 else None


def support(m, j, **settings):
    s = dict(SUPPORT, **settings)
    levels = np.count_nonzero(m.gap_hist[j, :, 1:-1], axis=1)
    common = (m.n[j, 0] >= s['min_n'] and m.n[j, 2] >= s['min_n']
              and m.cross[j] >= s['min_choosers']
              and (np.count_nonzero(m.month[j, [0, 2]], axis=1) >= s['min_months']).all()
              and (levels[[0, 2]] >= s['min_gap_levels']).all())
    atom = (common and m.n[j, 1] >= s['min_n'] and m.atom_cross[j] >= s['min_choosers']
            and np.count_nonzero(m.month[j, 1]) >= s['min_months'])
    return bool(common), bool(atom), levels


def inference(value, variance, df, ok):
    if not ok or not np.isfinite(variance):
        return dict(cluster_se_pp=None, ci95_low_pp=None, ci95_high_pp=None, p_two_sided=None)
    if variance < -1e-12: raise RuntimeError('Negative contrast variance')
    se = float(np.sqrt(max(0., variance))); critical = student_t.ppf(.975, df)
    p = float(2*student_t.sf(abs(value/se), df)) if se > 0 else (1. if value == 0 else 0.)
    return dict(cluster_se_pp=100*se, ci95_low_pp=100*(value-critical*se),
                ci95_high_pp=100*(value+critical*se), p_two_sided=p)


def wald(value, covariance, df, supported):
    if not supported or df <= 0 or not np.isfinite(covariance).all():
        return dict(status='insufficient_support_or_unidentified', p_cluster_F=None)
    V = (covariance+covariance.T)/2
    vals, vecs = np.linalg.eigh(V)
    keep = vals > max(float(vals.max(initial=0))*1e-10, 1e-18)
    rank = int(keep.sum())
    if rank != len(value):
        return dict(status='singular_restriction_covariance', restriction_rank=rank, p_cluster_F=None)
    W = float(np.sum((vecs[:, keep].T@value)**2/vals[keep]))
    return dict(status='estimated', restriction_rank=rank, Wald_statistic=W,
                F_statistic=W/rank, denominator_df=int(df), p_cluster_F=float(fdist.sf(W/rank, rank, df)))


def finish(m, model, **settings):
    correction = factor(m, model)
    V = model['meat']*correction if correction is not None else np.full_like(model['meat'], np.nan)
    R = model['R'][:, :m.core_size]; theta = R@model['estimates']; VR = R@V@R.T
    rows = []; supports = []
    for j, context in enumerate(contexts(m.spec)):
        common, atom, levels = support(m, j, **settings); supports.append(common)
        for t, term in enumerate(TERMS):
            i = j*len(TERMS)+t
            identified = bool(model['contrast_identified'][i] and correction is not None)
            ok = identified and (atom if t == 4 else common)
            row = dict(spec_id=m.spec.key, **m.spec.dictionary(), context=context, term=term,
                       status='estimated' if ok else 'insufficient_support' if identified else 'unidentified',
                       estimate_pp=100*float(theta[i]) if identified else None,
                       **inference(theta[i], VR[i, i], m.G-1, identified),
                       units='pp per axis unit' if t < 3 else 'pp',
                       n=m.N, events=m.events, chooser_clusters=m.G, absorbed_units=m.H,
                       context_n=int(m.n[j].sum()), context_choosers=int(m.group_G[j]),
                       source_window_before_tie_exclusion=m.source_before_omit,
                       source_window_after_tie_exclusion=m.source_N,
                       source_equal_rating_rows=m.source_ties,
                       singleton_rows_dropped=m.source_N-m.N,
                       left_n=int(m.n[j, 0]), center_n=int(m.n[j, 1]), right_n=int(m.n[j, 2]),
                       cross_cutoff_choosers=int(m.cross[j]), center_switching_choosers=int(m.atom_cross[j]),
                       left_gap_levels=int(levels[0]), right_gap_levels=int(levels[2]),
                       left_months=int(np.count_nonzero(m.month[j, 0])), right_months=int(np.count_nonzero(m.month[j, 2])),
                       rank=model['rank'], CR1_factor=correction, condition_number=model['condition_number'],
                       projection_error=float(model['contrast_projection_error'][i]),
                       normal_equation_relative_error=model['normal_equation_relative_error'], exploratory=True)
            if not ok: row['p_two_sided'] = None
            rows.append(row)
    tests = []
    if m.spec.scope == 'by_state':
        # Equal derivative changes across states: two independent restrictions.
        H = np.zeros((2, len(theta)))
        for j in range(2): H[j, (j+1)*len(TERMS)+2] = 1; H[j, 2] = -1
        required_levels = dict(SUPPORT, **settings)['min_gap_levels']
        common_levels = np.count_nonzero((m.gap_hist[:, :, 1:-1] > 0).all(axis=0), axis=1)
        shared = bool((common_levels[[0, 2]] >= required_levels).all())
        ok = all(supports) and shared and bool(model['contrast_identified'][[2, 7, 12]].all())
        tests.append(dict(spec_id=m.spec.key, **m.spec.dictionary(),
                          test='equal_kinks_across_board_states', null='The right-minus-left derivative changes are equal across all three board states.',
                          common_left_gap_levels=int(common_levels[0]), common_right_gap_levels=int(common_levels[2]),
                          **wald(H@theta, H@VR@H.T, m.G-1, ok)))
        # Pairwise differences use the same full cross-state clustered covariance.
        for first, second in [(0, 1), (0, 2), (1, 2)]:
            h = np.zeros(len(theta)); h[second*len(TERMS)+2] = 1; h[first*len(TERMS)+2] = -1
            common_pair = np.count_nonzero((m.gap_hist[[first, second], :, 1:-1] > 0).all(axis=0), axis=1)
            ok = bool(supports[first] and supports[second] and (common_pair[[0, 2]] >= required_levels).all()
                      and model['contrast_identified'][[first*5+2, second*5+2]].all())
            tests.append(dict(spec_id=m.spec.key, **m.spec.dictionary(),
                              test=f'kink_{STATES[second]}_minus_{STATES[first]}',
                              common_left_gap_levels=int(common_pair[0]), common_right_gap_levels=int(common_pair[2]),
                              status='estimated' if ok else 'insufficient_support_or_unidentified',
                              estimate_pp=100*float(h@theta) if ok else None,
                              **inference(h@theta, h@VR@h, m.G-1, ok)))
    return rows, tests, V


def polynomial_profile(m, model, V, points_per_side=41, **settings):
    rows = []; requests = []; stride = len(core_terms(m.spec))
    for j, context in enumerate(contexts(m.spec)):
        common, atom_ok, _ = support(m, j, **settings)
        for side in ('left', 'right', 'atom'):
            grid = np.linspace(-1, 0, points_per_side) if side == 'left' else np.linspace(0, 1, points_per_side) if side == 'right' else np.array([0.])
            for z in grid:
                c = np.zeros(m.core_size); off = j*stride
                if side == 'atom': c[off+3] = 1
                else:
                    right = side == 'right'; c[off+int(right)] = z
                    if right: c[off+2] = 1
                    if m.spec.degree == 2: c[off+4+int(right)] = z*z
                requests.append((context, side, z, c, atom_ok if side == 'atom' else common))
    # Check all linear prediction contrasts in one eigensolve.
    C = np.zeros((len(requests), len(m.b)))
    C[:, :m.core_size] = np.vstack([r[3] for r in requests])
    check = solve(m.S, m.b, C)
    for i, (context, side, z, c, supported) in enumerate(requests):
        ok = bool(check['identified'][i] and supported)
        value = float(c@model['estimates'])
        rows.append(dict(spec_id=m.spec.key, **m.spec.dictionary(), context=context, side=side,
                         x=float(m.spec.center+z*m.spec.h), status='estimated' if ok else 'insufficient_support_or_unidentified',
                         estimate_pp=100*value if ok else None,
                         **inference(value, c@V@c, m.G-1, ok),
                         normalization='difference from extrapolated left limit at cutoff'))
    return rows
