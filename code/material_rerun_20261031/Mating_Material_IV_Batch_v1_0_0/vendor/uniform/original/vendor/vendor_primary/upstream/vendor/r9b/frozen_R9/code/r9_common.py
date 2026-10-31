"""R9 contracts; every upstream producer remains byte-for-byte unchanged."""
from pathlib import Path
import sys, os, json, math, time, hashlib, gc
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor_ul/code'))
import ul_common as old
from ul_common import u, r, np, pa, pq, models, runtime, DAY, heartbeat
import r7_math as m7
from r7_memory import absorb_owned, shared_meat
VERSION = '1.0.0'
BASE_CONF = '2a4e617b40bcadacd25887d2035027e4f7777cbe4c2af51b7a7aa7dde592db14'
PHASE75_CONF = '9e46500403a4f3c1c011ec69b5677c295b2d094cca7bddd44f06e5c7ae6b7266'
LEVELS = ('X0_ENV_indicator', 'X0')
BRIDGE_SD = float(r.SD['pooled'])
FIXED_SD = .0594
FRAME = {'S0':0, 'F':2}  # F50 and O are verified subsets: no duplicate query scan.
DEFINITION = dict(primary='all donor times, j chooser, every j-i decision removed',
    reference='donor event UTC month; frozen held-out-both-player-fold models',
    reference_fallback='latest usable month at or before donor month; earliest usable only when no earlier model exists',
    controls='log1p donor count, log1p distinct counterparts, donor mean expected rate; own donor set for A/B/C',
    before='donor decision time strictly before focal game start',
    after='donor decision time strictly after focal anchor',
    scaling='one common A residual SD from S0 full ENV-indicator, plus exact legacy SD',
    covariance='shared_account_OR_date_CR0; generated score treated as fixed',
    baseline_tolerance=dict(atol=2e-10,rtol=1e-8),
    author_exclusion='both roles, donor and analysis frames', minimum_donors=5)

def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1); p=(ROOT/name).resolve()
        u.require(p.is_relative_to(ROOT), 'Unsafe package member')
        r.io.checked(p,digest)

def stage_file(path, conf):
    path=Path(path);old.prior.check_stage(path.parent,conf,[path.name]);return path

def col(path,name):
    return r.io.arr(r.io.read(path,[name]),name)

def public(info):
    return {k:v for k,v in info.items() if k not in ('files','dependencies','inputs')}

def assert_close(actual, expected, label, atol=2e-10, rtol=1e-8):
    """Compare the entire nested numerical result, not just headline rows."""
    stats=dict(numbers_checked=0,maximum_absolute_difference=0.)
    def walk(a,b,key):
        if isinstance(b,dict):
            u.require(isinstance(a,dict) and set(a)==set(b),label+' result schema changed: '+key)
            for k in b:walk(a[k],b[k],key+'/'+k)
        elif isinstance(b,list):
            u.require(isinstance(a,list) and len(a)==len(b),label+' result length changed: '+key)
            for k,(aa,bb) in enumerate(zip(a,b)):walk(aa,bb,key+'/'+str(k))
        elif isinstance(b,(int,float)) and not isinstance(b,bool):
            u.require(isinstance(a,(int,float)) and np.isclose(a,b,atol=atol,rtol=rtol,equal_nan=True),
                label+' numerical replay failed: '+key)
            stats['numbers_checked']+=1
            stats['maximum_absolute_difference']=max(stats['maximum_absolute_difference'],abs(a-b))
        else:u.require(a==b,label+' categorical replay failed: '+key)
    walk(actual,expected,'');return stats

def scaled(row,sd):
    """Native coefficient/SE retained; pp fields use one declared SD everywhere."""
    out=dict(row,reference_score_SD=sd,legacy_score_SD=BRIDGE_SD,fixed_bridge_score_SD=FIXED_SD,
             units='percentage points per common Score A residual SD')
    for key in ('coefficient','standard_error','ci_low','ci_high'):
        if row.get(key) is not None:
            out[key+'_pp']=100*sd*row[key]
            out[key+'_pp_per_legacy_SD']=100*BRIDGE_SD*row[key]
            out[key+'_pp_per_fixed_0_0594']=100*FIXED_SD*row[key]
    if row.get('standard_error') is not None:
        for side,sign in [('low',-1),('high',1)]:
            v=row['coefficient']+sign*1.6448536269514722*row['standard_error']
            out['ci90_'+side+'_pp']=100*sd*v
            out['ci90_'+side+'_pp_per_legacy_SD']=100*BRIDGE_SD*v
            out['ci90_'+side+'_pp_per_fixed_0_0594']=100*FIXED_SD*v
    base=row.get('outcome_mean_pp')
    if base:
        out['relative_percent_of_outcome_mean']=100*out['coefficient_pp']/base
        out['relative_percent_of_outcome_mean_per_legacy_SD']=100*out['coefficient_pp_per_legacy_SD']/base
        out['relative_percent_of_outcome_mean_per_fixed_0_0594']=100*out['coefficient_pp_per_fixed_0_0594']/base
    return out
