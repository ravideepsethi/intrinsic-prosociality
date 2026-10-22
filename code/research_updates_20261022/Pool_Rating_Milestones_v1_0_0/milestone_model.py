"""Frozen exploratory round-rating design; no data-dependent threshold search."""
from __future__ import annotations
import numpy as np
from scipy import sparse
from fe_core import onehot

VERSION = '1.0.0'
THRESHOLDS = list(range(500, 3001, 100))
MONTHS = [f'{y}-{m:02d}' for y in range(2023, 2026) for m in range(1, 13)
          if '2023-11' <= f'{y}-{m:02d}' <= '2025-10']
SPEEDS = ['ultrabullet', 'bullet', 'blitz', 'rapid', 'classical']
PROFILE_EDGES = np.arange(-25., 26., 5.)
PROFILE_REFERENCE = 7  # +10 through +14; last bin includes +25.


def specifications():
    common = dict(offset=0, width=25, stable=False, no1500=False,
                  late=False, safe=False, rounding='continuous', mode='crossings')
    changes = [
        ('hundreds_primary', {}),
        ('hundreds_width15', dict(width=15)),
        ('hundreds_width40', dict(width=40)),
        ('hundreds_established', dict(stable=True)),
        ('hundreds_established_no1500', dict(stable=True, no1500=True)),
        ('hundreds_past_ply10', dict(late=True)),
        ('hundreds_rounding_safe', dict(safe=True)),
        ('hundreds_nearest_integer', dict(rounding='nearest_integer')),
        ('fifties_comparison', dict(offset=50)),
        ('offset37_placebo', dict(offset=37)),
        ('offset73_placebo', dict(offset=73)),
        ('hundreds_by_threshold', dict(mode='by_threshold')),
        ('hundreds_distance_profile', dict(mode='profile')),
    ]
    return [dict(common, key=key, **patch) for key, patch in changes]


def milestone_geometry(frame, offset=0, rounding='continuous'):
    """Closest threshold; windows <=40 give at most one threshold per row.

    R is the displayed pre-game integer. R+payoff is reconstructed, NOT an
    observed or exactly recovered counterfactual displayed post-game rating.
    """
    r = frame['rating'].astype(float)
    target = 100 * np.floor((r - offset + 50) / 100) + offset
    d = r - target
    qd = r + frame['payoff'] - target
    qw = r + frame['win'] - target
    if rounding == 'nearest_integer':
        # Explicit half-up approximation for the displayed POST rating.
        qd = np.floor(r + frame['payoff'] + .5) - target
        qw = np.floor(r + frame['win'] + .5) - target
    separates_actions = (qd < 0) & (qw >= 0)
    lc = (d >= 0) & separates_actions
    gc = (d < 0) & separates_actions
    return target, d, qd, qw, lc, gc


def select(frame, spec):
    target, d, qd, qw, _, _ = milestone_geometry(frame, spec['offset'])
    keep = (target >= 500) & (target <= 3000) & (np.abs(d) <= spec['width'])
    if spec['stable']:
        keep &= (frame['crd'] <= 100) & (frame['drd'] <= 100)
    if spec['no1500']:
        keep &= target != 1500
    if spec['late']:
        keep &= frame['ply'] > 10
    if spec['safe']:
        # Remove rows whose draw OR claim classification can change under a
        # +/- half-point perturbation of the reconstructed post-game rating.
        keep &= (np.abs(qd) > .5) & (np.abs(qw) > .5)
    return keep


def target_names(spec):
    if spec['mode'] == 'crossings':
        return ['loss_crossing', 'gain_crossing']
    if spec['mode'] == 'by_threshold':
        return [f'{action}_{t}' for action in ('loss_crossing','gain_crossing') for t in THRESHOLDS]
    return [f'distance_{int(lo)}_to_{int(hi)}' for lo, hi in zip(PROFILE_EDGES[:-1], PROFILE_EDGES[1:])]


def common_design(f):
    """Sparse controls shared by all specifications; no outcome-derived terms."""
    n = len(f['y']); names=[]; arrays=[]; sparse_parts=[]
    def number(name, x):
        names.append(name); arrays.append(np.asarray(x, dtype=float))
    def spline(name, x, knots):
        number(name, x)
        for j,k in enumerate(knots): number(f'{name}_hinge{j}', np.maximum(x-k, 0))
    spline('gap100', np.clip(f['gap'], -1000, 1000)/100, [-4,-2,-1,0,1,2,4])
    spline('asinh_draw5', np.arcsinh(f['payoff']/5), np.arcsinh(np.array([-15,-5,0,5,15])/5))
    for name, x in [('log_K', np.log(f['K'])), ('log_ply', np.log1p(f['ply'])),
                    ('log_chooser_RD', np.log(f['crd'])), ('log_opponent_RD', np.log(f['drd'])),
                    ('log_chooser_vol', np.log(f['cvol'])), ('log_opponent_vol', np.log(f['dvol']))]:
        number(name, x); number(name+'_squared', x*x)
    for k in ('cclock','dclock','base_s','increment_s'):
        good = np.isfinite(f[k]) & (f[k] >= 0)
        number('log1p_'+k, np.log1p(np.where(good,f[k],0)))
        number(k+'_missing', (~good).astype(float))
    number('chooser_white', f['white'])
    number('board_cp100', np.clip(f['board'], -100, 600)/100)
    number('board_cp100_squared', (np.clip(f['board'], -100, 600)/100)**2)
    sparse_parts.append(sparse.csr_matrix(np.column_stack(arrays)))
    for key, codes, levels in [
        ('month',f['month'].astype(int),24),
        ('speed',f['speed'].astype(int),5),
        ('plyband',np.searchsorted([4,10,20,40,80],f['ply'],side='left'),6),
        ('board50',np.searchsorted(np.arange(-50.,601.,50.),f['board'],side='right'),15),
    ]:
        sparse_parts.append(onehot(codes, levels)[:,1:])
        names.extend(f'{key}_{j}' for j in range(1,levels))
    X=sparse.hstack(sparse_parts,format='csr'); X.eliminate_zeros()
    return X,names


def design(f, spec, common=None):
    target,d,qd,qw,lc,gc=milestone_geometry(f,spec['offset'],spec['rounding'])
    n=len(d); names=target_names(spec)
    if spec['mode']=='crossings':
        Z=sparse.csr_matrix(np.column_stack([lc,gc]).astype(float))
    elif spec['mode']=='by_threshold':
        code=((target-500)/100).astype(int)
        indicators=onehot(code,len(THRESHOLDS))
        Z=sparse.hstack([indicators.multiply(lc[:,None]),indicators.multiply(gc[:,None])],format='csr')
    else:
        bins=np.searchsorted(PROFILE_EDGES,d,side='right')-1
        bins=np.clip(bins,0,len(PROFILE_EDGES)-2)
        Z=onehot(bins,len(PROFILE_EDGES)-1)
    parts=[Z]
    if common is None: common=common_design(f)
    parts.append(common[0]); names+=common[1]
    code=((target-spec['offset'])/100).astype(int)-5
    parts.append(onehot(code,len(THRESHOLDS))[:,1:])
    names += [f'threshold_{t+spec["offset"]}' for t in THRESHOLDS[1:]]
    if spec['mode']!='profile':
        x=d/25; below=np.minimum(x,0); above=np.maximum(x,0)
        parts.append(sparse.csr_matrix(np.column_stack([d>=0,below,above,below**2,above**2])))
        names+=['above_milestone','distance_below','distance_above','distance_below_sq','distance_above_sq']
    X=sparse.hstack(parts,format='csr');X.eliminate_zeros()
    q=Z.shape[1]; C=np.zeros((q,X.shape[1]));C[:,:q]=np.eye(q)
    if spec['mode']=='profile': C[:,PROFILE_REFERENCE]-=1
    return X,C,Z,names


def raw_cell_codes(f):
    target,d,qd,qw,lc,gc=milestone_geometry(f)
    keep=(target>=500)&(target<=3000)&(np.abs(d)<=25)
    return keep,target,d,lc,gc
