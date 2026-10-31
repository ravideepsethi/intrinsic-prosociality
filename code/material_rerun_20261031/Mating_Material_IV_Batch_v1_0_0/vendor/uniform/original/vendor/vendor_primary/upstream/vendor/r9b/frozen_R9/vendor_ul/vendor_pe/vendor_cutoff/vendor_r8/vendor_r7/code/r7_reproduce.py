"""A numerical reproduction gate against full-precision archived results."""
from r7_common import *
from r7_models import estimate, select_sample
from phase50_models import checked_solver

def check_row(got,want,label,fields):
    for key in ('n','row_set_sha256'):
        if got.get(key)!=want.get(key):raise RuntimeError(label+' differs: '+key)
    for key in fields:
        if key not in want:continue
        if isinstance(want[key],(list,tuple)):
            if not np.allclose(got[key],want[key],rtol=2e-7,atol=2e-9):raise RuntimeError(label+' differs: '+key)
        elif not np.isclose(got.get(key,np.nan),want[key],rtol=2e-7,atol=2e-9):
            raise RuntimeError(label+' differs: '+key+' '+str((got.get(key),want[key])))

def run(binding,root,conf):
    paths={k:Path(v) for k,v in binding['paths'].items()}
    def build(tmp):
        records=[]
        expected=io.load(next((ROOT/'vendor_phase50').rglob('expanded_estimates.json')))
        d=load_fit_columns(paths['original']);spec=next(s for s in design.specifications() if s['name']=='main90_pooled')
        with checked_solver():legacy=stats.estimate(d,spec)
        for target in expected:
            if target.get('specification')!='main90_pooled':continue
            got=next(r for r in legacy['estimates'] if r['estimator']==target['estimator'])
            check_row(got,target,'Original Panel A '+target['estimator'],
                ['coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp','AR95_intervals_pp'])
            records.append(dict(check='original_'+target['estimator'],passed=True,n=got['n'],row_set_sha256=got['row_set_sha256']))
        fresh,_=estimate(d,'iv','S0_original',part_a=False)
        mapping={'first_stage_per_reference_SD':('first_stage','received'),'RF_kindness_per_reference_SD':('reduced_form','y'),
                 'RF_reach_per_reference_SD':('reduced_form','reached'),'2SLS':('2SLS','y')}
        for name,(est,outcome) in mapping.items():
            want=next(r for r in legacy['estimates'] if r['estimator']==name)
            got=next(r for r in fresh['B_estimates'] if r['estimator']==est and r['outcome']==outcome)
            check_row(got,want,'R7 adapter '+name,['coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp','AR95_intervals_pp'])
        oldjoint=next(r for r in legacy['joint_balance'] if r['test_set']=='recent_behavior')
        check_row(fresh['B_joint_balance'][0],oldjoint,'Original stacked balance',['wald_chi2','p_value_asymptotic'])
        for got in fresh['B_balance']:
            want=next(r for r in legacy['balance'] if r['trait']==got['trait'])
            check_row(got,want,'Original balance '+got['trait'],['coefficient','standard_error'])
        # Preserve the full-precision original balance result, which was not a
        # separate member of the delivered old estimate archive.
        io.js(tmp/'original_primary_balance.json',dict(source='frozen original producer recomputed on authenticated original rows',
            balance=legacy['balance'],joint_balance=legacy['joint_balance']))
        io.js(tmp/'original_panel_A.json',fresh)
        del d,legacy,fresh
        envtargets=io.load(ROOT/'evidence/environment/estimates.json');jointtargets=io.load(ROOT/'evidence/environment/joint_balance.json')
        d=select_sample(load_fit_columns(paths['receipt']),'comp_env')
        for level,oldlevel in [('XC','XC'),('XC_ENV','XC_both_rates')]:
            fresh,_=estimate(d,'iv','S0_CSE',level,part_a=False)
            for got in fresh['B_estimates']:
                want=next(r for r in envtargets if r.get('cohort')=='receipt_original_author_clean' and r.get('sample')=='competitive_and_environment_supported'
                    and r.get('instrument')=='pooled' and r.get('control_level')==oldlevel and r.get('estimator')==got['estimator'] and r.get('outcome')==got['outcome'])
                check_row(got,want,'ENV bridge '+level,['coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp','AR95_intervals_pp'])
            want=next(r for r in jointtargets if r.get('cohort')=='receipt_original_author_clean' and r.get('sample')=='competitive_and_environment_supported' and r.get('instrument')=='pooled' and r.get('control_level')==oldlevel)
            check_row(fresh['B_joint_balance'][0],want,'ENV joint balance',['wald_chi2','p_value_asymptotic'])
            records.append(dict(check='ENV_'+level,passed=True,n=len(d['row_id']),row_set_sha256=design.row_digest(d['row_id'])))
        del d,fresh
        targets=io.load(ROOT/'evidence/phase50/estimates.json')
        for kind in ('entry','ordinary'):
            d=load_fit_columns(paths[kind]);fresh,_=estimate(d,kind,'F50' if kind=='entry' else 'O50',part_a=False)
            for got in fresh['B_estimates']:
                want=next(r for r in targets if r.get('cohort')=='new_phase50' and r.get('family')==kind and r.get('outcome')==got['outcome'])
                check_row(got,want,'Phase50 '+kind+' '+got['outcome'],['coefficient_pp','standard_error_pp'])
            if kind=='entry':
                want=next(r for r in io.load(ROOT/'evidence/phase50/entry_joint_balance.json') if r.get('cohort')=='new_phase50')
                check_row(fresh['B_joint_balance'][0],want,'Phase50 joint balance',['wald_chi2','p_value_asymptotic'])
            records.append(dict(check=kind+'_phase50',passed=True,n=len(d['row_id']),row_set_sha256=design.row_digest(d['row_id'])))
            del d,fresh
        io.js(tmp/'checks.json',records)
        return dict(status='REPRODUCTION_GATE_PASSED',checks=len(records),original_rows=2682330,diagnostic_rows=2682329)
    return stable_stage(root,conf,build,list(paths.values()))
