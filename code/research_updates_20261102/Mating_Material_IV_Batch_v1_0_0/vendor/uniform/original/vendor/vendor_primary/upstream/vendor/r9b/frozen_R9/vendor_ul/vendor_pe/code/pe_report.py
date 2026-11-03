"""Aggregate-only, checksummed, resumable progress reports."""
from pe_common import *
import zipfile

def export(root, desktop, conf, progress, status, extra):
    folder=root/'report';folder.mkdir(parents=True,exist_ok=True)
    tables={name:[] for name in ('B_placebo','B_entry','B_balance','B_joint_balance','B_indicator','B_placebo_contrasts')}
    checks=[];completed=0
    for p in sorted((root/'fits').glob('*/result.json')):
        if not (p.parent/'_DONE.json').exists():continue
        result=u.load(p);done=u.load(p.parent/'_DONE.json');completed+=1
        if done['kind']=='receipt_influence':
            checks+=u.load(p.parent/'reproduction.json');continue
        sample=done['sample'];table='B_entry' if sample=='F50' else 'B_placebo'
        tables[table]+=result['B_estimates']
        for name in ('B_balance','B_joint_balance','B_indicator'):tables[name]+=result.get(name,[])
    for item in extra.get('archived_models',[]):
        sample=item['sample'];level=item['level'];result=u.load(item['path'])
        for name in ('B_estimates','B_balance','B_joint_balance','B_indicator'):
            table=('B_entry' if sample=='F50' else 'B_placebo') if name=='B_estimates' else name
            tables[table]+=[dict(row,history_cutoff='old_monthly',exposure_screen='all',result_reused=True)
                           for row in result.get(name,[])]
    oldpath=previous.ROOT/'vendor_r8/evidence/r7/B_placebo_contrasts.json'
    tables['B_placebo_contrasts'] += [dict(row,history_cutoff='old_monthly',exposure_screen='all',result_reused=True)
        for row in u.load(oldpath) if row['sample']=='S0_minus_O50' and row['control_level'] in LEVELS]
    for p in sorted((root/'contrasts').glob('*/result.json')):
        if (p.parent/'_DONE.json').exists():tables['B_placebo_contrasts']+=u.load(p)
    for name,rows in tables.items():r.write_rows(folder,name,rows)
    r.write_rows(folder,'receipt_reference',u.load(ROOT/'evidence/cutoff/B_estimates.json'))
    r.io.js(folder/'receipt_reconstruction_checks.json',checks)
    # Explicit whitelist: no source paths, accounts, game IDs, or influence rows.
    public={k:v for k,v in extra.items() if k not in ('archived_models',)}
    summary=dict(version=VERSION,configuration_sha256=conf,progress_percent=progress,status=status,
        completed_new_jobs=completed,receipt_IV_refitted=False,receipt_reference_configuration=CUTOFF_CONF,
        baseline_configuration=u.R7_CONF,core_F50_rows=7371688,core_O50_rows=4764089,
        generated_scores_treated_as_fixed=True,nominal_interim_inference=True,
        causal_identification_certified=False,**public)
    r.io.js(folder/'summary.json',summary)
    (folder/'READ_RESULTS.txt').write_text(
        'Updated IV placebo and entry diagnostics, fixed R7 exposure rows.\n'
        'Cumulative eligible grant/claim history strictly before exposure start minus 24 hours; whole pair and authors excluded.\n'
        'No rolling-24-hour history window. Ordinary games are not donor refusals. Original monthly nuisance models and controls are fixed.\n'
        'B_placebo: later kindness Y and reach in ordinary-ending O50; B_entry: entry, recipient disconnect, and active timeout in F50.\n'
        'Old-monthly rows are authenticated archived R7 results. Receipt IV estimates are reused from the reviewed cutoff/material run.\n'
        'Receipt RF residual/influence reconstruction is verified numerically before shared-account/date covariance contrasts.\n'
        'B_placebo_contrasts gives receipt RF minus ordinary RF, with a joint covariance CI; separate significance labels are not compared.\n'
        'All scales use the frozen pooled reference SD. SEs are shared-account-OR-date CR0 and treat the generated instrument as fixed.\n'
        'Material audit checks documented final FENs in existing Parquets. Missing positions are not neutral.\n'
        'Any ordinary material sensitivity uses strict abs(material)<4; no ordinary disconnected-player competitive-cp screen is claimed.\n'
        'Raw PGN/JSON replay is a separate unresolved coverage task if no usable position Parquet is present.\n'
        'Null placebos do not establish IV exclusion. Entry/exit associations, prior sorting, sanctions, and post-assignment selection remain relevant.\n')
    manifest=[dict(path=p.name,sha256=u.sha(p),bytes=p.stat().st_size) for p in sorted(folder.iterdir())
              if p.is_file() and p.name!='REPORT_MANIFEST.json']
    r.io.js(folder/'REPORT_MANIFEST.json',manifest)
    desktop.mkdir(parents=True,exist_ok=True)
    target=desktop/f'IV_PLACEBO_ENTRY_REPORT_{conf[:12]}_{progress:03d}.zip'
    temp=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.iterdir()):
            if p.is_file():z.write(p,p.name)
    os.replace(temp,target)
    target.with_suffix('.zip.sha256').write_text(u.sha(target)+'  '+target.name+'\n')
    u.log(f'{progress}% CHECKPOINT_SAVED: {target}')
    return summary
