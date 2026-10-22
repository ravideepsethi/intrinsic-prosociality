"""Exact bounded-gamma projection of the scalar null-restricted score test.

The interval union is analytic, not a gamma grid approximation. CR0 is never
repaired to PSD. Gamma is a fixed sensitivity parameter, not a fitted control.
"""
import math
import numpy as np
import iv_numerics as num
from design import REFERENCE_SD,GAMMA_BOUNDS_PP
from followup_stats import CRIT

def merge(intervals):
    out=[]
    for a,b in sorted(intervals,key=lambda x:(x[0],x[1])):
        if a>b:continue
        if out and a<=out[-1][1]:out[-1][1]=max(out[-1][1],b)
        else:out.append([a,b])
    return out

def intersect(left,right):
    return merge([[max(a,c),min(b,d)] for a,b in left for c,d in right if max(a,c)<=min(b,d)])

def formatted(intervals,scale=100.):
    return [[('-inf' if a==-math.inf else scale*a),('+inf' if b==math.inf else scale*b)] for a,b in intervals]

def psd(M):
    return bool(np.isfinite(M).all() and np.linalg.eigvalsh(M).min()>=-1e-10*max(float(abs(M).max()),1e-30))

def ar_fixed(zy,zd,zz,M,g):
    c=CRIT**2
    return num.quadratic_set(zd**2-c*M[1,1],
        -2*(zy-g*zz)*zd+2*c*(M[0,1]-g*M[1,2]),
        (zy-g*zz)**2-c*(M[0,0]-2*g*M[0,2]+g*g*M[2,2]))

def ar_bounded(zy,zd,zz,M,lo,hi):
    if lo>hi:raise ValueError('Reversed gamma interval')
    if not psd(M):raise ValueError('NON_PSD_NULL_MOMENT_COVARIANCE_NOT_REPAIRED')
    out=ar_fixed(zy,zd,zz,M,lo)+ar_fixed(zy,zd,zz,M,hi)
    c=CRIT**2
    A=zz*zz-c*M[2,2]
    B0=-2*zy*zz+2*c*M[0,2]
    B1=2*zd*zz-2*c*M[1,2]
    # A concave/linear function achieves its minimum at a gamma endpoint.
    if A>0 and lo<hi:
        # Interior gamma minimizer is -(B0+B1*beta)/(2*A).
        region=intersect(num.quadratic_set(0.,B1,B0+2*A*lo),
                         num.quadratic_set(0.,-B1,-B0-2*A*hi))
        vertex=num.quadratic_set(zd*zd-c*M[1,1]-B1*B1/(4*A),
            -2*zy*zd+2*c*M[0,1]-B0*B1/(2*A),
            zy*zy-c*M[0,0]-B0*B0/(4*A))
        out+=intersect(vertex,region)
    return merge(out)

def first_nonnegative(intervals):
    values=[max(0.,a) for a,b in intervals if b>=0]
    return min(values) if values else None

def compute(y,d,z,meat):
    zz,zd,zy=float(z@z),float(z@d),float(z@y)
    if zz<=1e-20 or abs(zd)<=1e-15:
        return dict(supported=False,reason='NO_INSTRUMENT_VARIATION_OR_ZERO_FIRST_STAGE',fixed=[],bounds=[])
    M=meat(np.column_stack([z*y,z*d,z*z]));ok=psd(M)
    scale=100*REFERENCE_SD
    rho_pp=scale*zy/zz;pi_pp=scale*zd/zz
    result=dict(supported=ok,reference_score_sd=REFERENCE_SD,
        gamma_units='percentage points of Y per reference score SD',
        beta_units='percentage points of Y per receipt',
        method='Projection of null-restricted shared-account OR date CR0 score/AR acceptance over a fixed gamma interval; chi2_1 asymptotic.',
        point_zero_gamma_pp=rho_pp,first_stage_pp_per_reference_sd=pi_pp,
        null_moment_covariance_psd=ok,fixed=[],bounds=[])
    if not ok:
        result['reason']='NON_PSD_NULL_MOMENT_COVARIANCE_NOT_REPAIRED';return result
    # Include the exact new zero-effect tipping value and the rounded historical reference.
    grid=sorted(set([g for G in GAMMA_BOUNDS_PP for g in (-G,G)]+[rho_pp,.020386]))
    for gpp in grid:
        g=gpp/scale;b=(zy-g*zz)/zd
        vec=np.array([1.,-b,-g]);v=float(vec@M@vec)/(zd*zd)
        row=dict(gamma_pp=gpp,beta_pp=100*b,AR95_intervals_pp=formatted(ar_fixed(zy,zd,zz,M,g)),
            wald_supported=bool(v>0 and np.isfinite(v)))
        if row['wald_supported']:
            se=math.sqrt(v);row.update(standard_error_pp=100*se,ci_low_pp=100*(b-CRIT*se),ci_high_pp=100*(b+CRIT*se))
        else:row['wald_reason']='NONPOSITIVE_COVARIANCE_NOT_REPAIRED'
        result['fixed'].append(row)
    for Gpp in GAMMA_BOUNDS_PP:
        for label,lo_pp,hi_pp in [('symmetric',-Gpp,Gpp),('positive',0.,Gpp)]:
            intervals=ar_bounded(zy,zd,zz,M,lo_pp/scale,hi_pp/scale)
            ends=sorted(100*(zy-g*zz)/zd for g in (lo_pp/scale,hi_pp/scale))
            result['bounds'].append(dict(range=label,bound_pp=Gpp,gamma_low_pp=lo_pp,gamma_high_pp=hi_pp,
                point_identified_range_pp=ends,AR95_union_intervals_pp=formatted(intervals),
                AR95_unbounded=any(math.isinf(a) or math.isinf(b) for a,b in intervals),
                AR95_contains_zero=any(a<=0<=b for a,b in intervals)))
    zeros=num.quadratic_set(zz*zz-CRIT**2*M[2,2],-2*zy*zz+2*CRIT**2*M[0,2],zy*zy-CRIT**2*M[0,0])
    positive=first_nonnegative(zeros)
    symmetric=min([0. if a<=0<=b else min(abs(a),abs(b)) for a,b in zeros],default=None)
    result.update(gamma_accepting_zero_AR95_intervals_pp=formatted(zeros,scale),
        minimum_positive_gamma_for_zero_AR95_pp=None if positive is None else scale*positive,
        minimum_symmetric_bound_for_zero_AR95_pp=None if symmetric is None else scale*symmetric)
    return result
