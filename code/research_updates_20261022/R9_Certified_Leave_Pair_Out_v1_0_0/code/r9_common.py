"""R9 contracts; the baseline and its numerical producers remain unmodified."""
from pathlib import Path
import sys, os, json, math, time, hashlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor_baseline/code'))
import ul_common as old
from ul_common import u, r, np, pa, pq, models, DAY, heartbeat, runtime
import ul_scores, ul_models
import r7_math as rm
VERSION = '1.0.0'
BASELINE = '2a4e617b40bcadacd25887d2035027e4f7777cbe4c2af51b7a7aa7dde592db14'
PHASE75 = '9e46500403a4f3c1c011ec69b5677c295b2d094cca7bddd44f06e5c7ae6b7266'
LEVELS = ('X0_ENV_indicator', 'X0')
BRIDGE_SD = 0.0594
SPEC = dict(baseline=BASELINE, primary='X0_ENV_indicator', donor_month='UTC calendar month of donor event timestamp t',
    fallback='latest usable model no later than donor month, same two excluded folds; if none, p_hat=0 (no state adjustment)',
    minimum_donors=5, before='t < focal game start', after='t > focal anchor',
    donor_controls='frozen log1p(n), log1p(distinct counterparts), mean p_hat from A in every model except B uses its own B histories; C retains A controls',
    covariance='shared_account_OR_date_CR0', generated_scores_treated_as_fixed=True,
    bridge_SD=BRIDGE_SD, adoption_reference_pp=0.281, adoption_threshold='one third of NEW primary standard error')

def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);p=(ROOT/name).resolve()
        u.require(p.is_relative_to(ROOT),'Unsafe package member')
        r.io.checked(p,digest)

def certified(path, conf):
    path=Path(path)
    r.env_common.checked_stage_files(path.parent,conf,[path.name])
    return path

def stamp_stage(folder, conf):
    folder=Path(folder);d=u.load(folder/'_DONE.json')
    u.require(d['config_sha256']==conf,'Unexpected completed-stage configuration: '+str(folder))
    for x in d['files']:r.io.checked(folder/x['path'],x['sha256'],x.get('bytes'))
    return d

def compare_numbers(got,want,where='root',atol=2e-10,rtol=2e-8):
    """All coefficients/SEs (including trait and indicator rows), no rounded targets."""
    checks=[]
    if isinstance(want,dict):
        for k,v in want.items():
            if k in ('n','row_set_sha256','control_level','outcome','estimator','trait'):
                u.require(got.get(k)==v,'Baseline identity differs: '+where+'/'+k)
            numeric=('coefficient' in k or 'standard_error' in k or k.endswith('_SE') or k.endswith('_SE_pp'))
            if numeric and isinstance(v,(float,int)):
                x=got.get(k);u.require(x is not None and np.isclose(x,v,rtol=rtol,atol=atol),
                    'Baseline numerical mismatch: '+where+'/'+k+' '+str((x,v)))
                checks.append(dict(field=where+'/'+k,absolute_difference=abs(x-v),tolerance=atol+rtol*abs(v)))
            elif isinstance(v,(dict,list)):
                u.require(k in got,'Missing baseline table '+k)
                checks+=compare_numbers(got[k],v,where+'/'+k,atol,rtol)
    elif isinstance(want,list):
        u.require(len(got)==len(want),'Baseline table length differs: '+where)
        for i,(a,b) in enumerate(zip(got,want)):checks+=compare_numbers(a,b,where+'/'+str(i),atol,rtol)
    return checks

def scaled(fit, sd):
    out=dict(fit)
    for suffix,unit in [('primary_SD',sd),('fixed_0_0594',BRIDGE_SD)]:
        for key in ('coefficient','standard_error','ci_low','ci_high'):
            if key in fit:out[key+'_pp_per_'+suffix]=100*unit*fit[key]
        if 'standard_error' in fit:
            out['ci90_low_pp_per_'+suffix]=100*unit*(fit['coefficient']-1.6448536269514722*fit['standard_error'])
            out['ci90_high_pp_per_'+suffix]=100*unit*(fit['coefficient']+1.6448536269514722*fit['standard_error'])
    out.update(primary_score_SD=sd,fixed_bridge_SD=BRIDGE_SD)
    # Remove legacy ambiguous per-unit pp aliases from public R9 rows.
    for k in ('coefficient_pp','standard_error_pp','ci_low_pp','ci_high_pp','ci90_low_pp','ci90_high_pp'):out.pop(k,None)
    return out

def memmap_column(folder,name,values):
    p=Path(folder)/(name+'.npy');a=np.asarray(values)
    out=np.lib.format.open_memmap(p,mode='w+',dtype=a.dtype,shape=a.shape)
    out[:]=a;out.flush();return out
