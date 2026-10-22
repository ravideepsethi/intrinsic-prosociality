"""Aggregate-only results, reused benchmarks, and 25/50/75/100 percent reports."""
from ul_common import *
import zipfile

def collect(root):
    tables={k:[] for k in ('B_estimates','B_placebo','B_entry','B_timing','B_balance','B_joint_balance','B_indicator','B_placebo_contrasts')}
    completed=[]
    for path in sorted((root/'fits').glob('*/result.json')):
        if not (path.parent/'_DONE.json').exists():continue
        done=u.load(path.parent/'_DONE.json');completed.append(public_stage(done));result=u.load(path)
        table='B_timing' if done['cohort']=='timing_common' else dict(S0='B_estimates',F50='B_entry',O50='B_placebo')[done['sample']]
        tables[table] += result['B_estimates']
        for key in ('B_balance','B_joint_balance','B_indicator'):tables[key]+=result.get(key,[])
    for path in sorted((root/'contrasts').glob('*/result.json')):
        if (path.parent/'_DONE.json').exists():tables['B_placebo_contrasts']+=u.load(path)
    return tables,completed

def verify_comparisons(tables,complete=False):
    old=u.load(prior.ROOT/'evidence/cutoff/B_estimates.json');checks=[]
    for row in tables['B_estimates']:
        if 'outcome' not in row:continue
        target=[v for v in old if v['history_cutoff']=='lag24h' and v['exposure_screen']==row['exposure_screen']
            and v['control_level']==row['control_level'] and v['outcome']==row['outcome'] and v['estimator']==row['estimator']]
        u.require(len(target)==1,'Missing archived receipt comparison')
        u.require(all(row[k]==target[0][k] for k in ('n','row_set_sha256')),'Receipt rerun changed the frozen cohort')
        checks.append(dict(sample='S0',screen=row['exposure_screen'],control_level=row['control_level'],
            outcome=row['outcome'],estimator=row['estimator'],same_rows_as_reviewed=True))
    for sample,table in [('F50','B_entry'),('O50','B_placebo')]:
        old=u.load(ROOT/'evidence/placebo'/(table+'.json'))
        for row in tables[table]:
            if 'outcome' not in row:continue
            target=[v for v in old if v['history_cutoff']=='lag24h' and v['control_level']==row['control_level'] and v['outcome']==row['outcome']]
            u.require(len(target)==1 and all(row[k]==target[0][k] for k in ('n','row_set_sha256')),'Comparison rerun changed frozen rows')
    for level in LEVELS:
        rows=[v for v in tables['B_timing'] if v['control_level']==level]
        if rows:
            u.require(len({(v['n'],v['row_set_sha256']) for v in rows})==1,'Timing comparisons have different rows')
            if complete:u.require({v['history_cutoff'] for v in rows}=={'all_time','before','after'},'Incomplete timing comparisons')
    return checks

def export(root,desktop,conf,progress,status,extra):
    folder=root/'report';folder.mkdir(parents=True,exist_ok=True)
    tables,completed=collect(root)
    finished=status=='CORE_COMPLETE_ORDINARY_MATERIAL_PENDING'
    checks=verify_comparisons(tables,finished)
    if finished:
        u.require(len(completed)==14,'Final report has an incomplete model plan')
        u.require(len(tables['B_placebo_contrasts'])==4,'Final report has incomplete RF contrasts')
    for name,rows in tables.items():r.write_rows(folder,name,rows)
    r.write_rows(folder,'receipt_reference',u.load(prior.ROOT/'evidence/cutoff/B_estimates.json'))
    for name in ('B_placebo','B_entry','B_placebo_contrasts','B_joint_balance'):
        r.write_rows(folder,name+'_reference',u.load(ROOT/'evidence/placebo'/(name+'.json')))
    r.io.js(folder/'same_row_checks.json',checks)
    summary=dict(version=VERSION,configuration_sha256=conf,status=status,progress_percent=progress,
        completed_new_models=len(completed),planned_new_models=14,completed_models=completed,
        baseline_configuration=u.R7_CONF,receipt_reference_configuration=prior.CUTOFF_CONF,
        placebo_reference_configuration=PE_CONF,api_requests=0,stockfish_searches=0,
        source_period='the existing authenticated 24 monthly donor partitions; no exposure-relative cutoff',
        inference=annotations(),**extra)
    r.io.js(folder/'summary.json',summary)
    (folder/'READ_RESULTS.txt').write_text(
        'Unrestricted leave-pair-out chooser leniency: read summary.json first.\n'
        'all_time includes every eligible cached grant/claim opportunity, before AND after the focal game.\n'
        'Every j-to-i donor decision is removed, including repeats in both time directions. The reverse-role game cannot enter j-as-chooser history.\n'
        'Author accounts remain excluded in both roles. Ordinary endings are not counted as refusals.\n'
        'The original 500-cell monthly cross-fitted state reference is fixed: both focal player folds were excluded in its training.\n'
        'Only donor eligibility changes. Historical n/expected-rate controls and all pre-exposure covariates remain unchanged.\n'
        'B_estimates: new full-time receipt IV, full and strict abs(material)<4 samples, X0 and ENV indicator.\n'
        'B_placebo: ordinary later kindness/reach. B_entry: focal entry, recipient disconnect, active timeout.\n'
        'B_timing: full-time/before/after IVs on the SAME S0 rows supported by both timing scores.\n'
        'before = donor event strictly before focal start; after = donor event strictly after focal cached anchor.\n'
        'Same-interval/tied donor events remain in the primary all-time score; the timing diagnostic omits them.\n'
        'Timing diagnostics condition on future history support and are selected-sample sensitivities, not new primary estimates.\n'
        'B_placebo_contrasts: new receipt minus ordinary RF, shared account/date covariance. This is not a corrected IV.\n'
        '*_reference tables are reused completed results, never silently re-estimated.\n'
        'No newly eligible exposure cohort is assembled. No completed material coverage audit is repeated.\n'
        'The ordinary material-restricted placebo remains pending; missing final positions are never coded neutral.\n'
        'The R7 single-score 2SLS/CR0 implementation is retained; this is NOT a certified UJIVE implementation.\n'
        'Own-pair direct score leakage is excluded. Later feedback, network dependence, and own-observation bias from regression residualization are NOT ruled out.\n'
        'Generated scores/nuisance are treated as fixed for inference; shared-account-OR-date CR0, fixed reference SD, nominal intervals.\n'
        'A stronger first stage, null placebo, or balanced material does not establish exclusion or remove selection.\n')
    manifest=[dict(path=p.name,sha256=u.sha(p),bytes=p.stat().st_size) for p in sorted(folder.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    r.io.js(folder/'REPORT_MANIFEST.json',manifest)
    desktop.mkdir(parents=True,exist_ok=True)
    target=desktop/f'IV_LEAVE_PAIR_OUT_REPORT_{conf[:12]}_{progress:03d}.zip';tmp=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.iterdir()):
            if path.is_file():z.write(path,path.name)
    os.replace(tmp,target);target.with_suffix('.zip.sha256').write_text(u.sha(target)+'  '+target.name+'\n')
    u.log(f'{progress}% CHECKPOINT_SAVED: {target}');return summary
