"""Aggregate-only reports, partial progress, and explicit interpretation bounds."""
from common import *
from numerics import holm
import shutil,zipfile

def csvread(path):
    if not Path(path).is_file():return []
    with Path(path).open() as f:return list(csv.DictReader(f))

def assemble(work,desktop,key,status,failure=None):
    work=Path(work);out=work/'report';out.mkdir(parents=True,exist_ok=True)
    sample=[];balance=[];metadata=[]
    for p in sorted((work/'audits').glob('*')):
        if not checkpoint_ok(p,key):continue
        sample+=csvread(p/'sample.csv');balance+=csvread(p/'balance.csv');metadata.append(read(p/'summary.json'))
    csvwrite(out/'00_sample.csv',sample);csvwrite(out/'00_stake_balance.csv',balance)
    archived=[]
    for r in csvread(PACKAGE/'authority/secondary_dose_estimates.csv'):
        r.update(status='PREVIOUSLY_OBSERVED_EXPLORATORY',source='Receipt_Mechanisms_v1_0_1');archived.append(r)
    csvwrite(out/'00_archived_benchmark.csv',archived)
    rows=[];models=[];cov=[]
    for p in sorted((work/'models').glob('*')):
        if not checkpoint_ok(p,key):continue
        models.append(read(p/'summary.json'));rows+=csvread(p/'estimates.csv');cov+=csvread(p/'covariance.csv')
        if (p/'tercile_support.csv').exists():shutil.copyfile(p/'tercile_support.csv',out/'01_test1_tercile_support.csv')
    focal=[next((r for r in rows if r.get('model')=='joint' and r.get('outcome')=='y' and r.get('term')==t),None)
      for t in ('received_x_giver_cost_5','ahead_minus_equal')]
    if any(r is not None for r in focal):
        adjusted=holm([float(r['p_two_sided']) if r is not None and r.get('p_two_sided') else None for r in focal])
        for r,p in zip(focal,adjusted):
            if r is not None:r['holm_p_family2']=p;r['multiplicity_family']='two focal Y contrasts; exploratory after prior related results'
    csvwrite(out/'01_joint_model.csv',[r for r in rows if r.get('model')=='joint'])
    csvwrite(out/'01_test1_terciles.csv',[r for r in rows if r.get('model')=='terciles'])
    csvwrite(out/'01_test1_sensitivity.csv',[r for r in rows if r.get('model') in ('drop_cost','drop_benefit','rd110')])
    csvwrite(out/'02_test2_contrasts.csv',[r for r in rows if r.get('term') in ('equal','ahead_minus_equal') or r.get('term','').startswith('received_band_')])
    csvwrite(out/'02_test2_within.csv',[r for r in rows if r.get('model')=='within'])
    csvwrite(out/'joint_covariances.csv',cov)
    ivroot=work/'secondary_iv';ivs=None
    if checkpoint_ok(ivroot,key):
        ivs=read(ivroot/'summary.json')
        for src,dest in [('estimates.csv','03_iv.csv'),('first_stages.csv','03_iv_first_stages.csv'),('reduced_forms.csv','03_iv_reduced_forms.csv'),('covariance.csv','03_iv_joint_covariances.csv')]:
            if (ivroot/src).exists():shutil.copyfile(ivroot/src,out/dest)
    summary=dict(status=status,version=VERSION,run_key=key,samples=metadata,models=models,estimates=rows,secondary_iv=ivs,
      original_IV_modified=False,mechanism_identified=False,network_requests=0,stockfish_searches=0,
      exploratory_after_related_results=True,failure=failure)
    write(out/'summary.json',summary)
    lines=['RECEIPT COHORT TESTS: READ THE POSITION PROFILE FIRST',
      'Status: '+status,'',
      'Two focal Y statistics: ahead-minus-equal and receipt x giver cost. Cost-related results were previously viewed.',
      'The new specification was frozen in this package before these new fits. This is not an independent preregistered confirmation.',
      'Y and reached are estimated on the same complete 90-day sample. Y=0 for nonreachers. Do not condition on reaching.',
      'Point estimates, SEs and intervals use percentage points. Cost slopes are per five rating points; IQR contrasts are also shown.',
      'The primary model jointly adjusts both stakes and position. Near equal is [-100,100), from the recipient perspective.',
      'The pooled equal effect uses all-exposure band shares. Its comparison with >=300 cp uses the joint covariance.',
      'Primary OLS covariance: any shared account across three roles, finite-sample adjusted; no date clustering.',
      'Secondary IV covariance: the original shared exposure account OR exposure-date CR0; explicitly a different rule.',
      'The IV control/FE definition is pinned to the authenticated source excerpt, with explicit predecision stake/position additions.',
      'Every treatment interaction is instrumented. The pooled leniency score is excluded from the IV controls.',
      'Conditional first-stage F values diagnose rank weakness. They do not establish exclusion or a psychological mechanism.',
      'IV intervals are nominal, not weak-instrument robust. Weak or unstable IV results cannot establish effect heterogeneity.',
      '', 'INTERPRETATION',
      'A tightly estimated nonpositive ahead-minus-equal contrast would weigh against a resentment story requiring a larger response when ahead.',
      'A nonsignificant or merely negative point estimate does not establish that conclusion. Assess the positive effects the interval still allows.',
      'Even a negative contrast does not eliminate state-independent resentment, selection, or other mechanisms and does not establish gratitude.',
      'A positive contrast is compatible with resentment, gratitude respecting deserved outcomes, and relief from an unexpected loss.',
      'The ordinary draw-loss comparison is useful evidence of a small association in ordinary games; it cannot by itself exclude result effects here.',
      'High claim frequency describes behavior, not recipients\' expectations or entitlement. Forced draws are not an automatically settling design.',
      'All tables retain support/rank flags and both outcomes. No headline sentence is changed automatically.',
      'Holm p-values apply only to the two focal Y contrasts in the new joint OLS model. Displayed 95% intervals remain nominal.',
      'Do not replace a focal estimate by whichever sensitivity looks favorable. No covariate, outcome or history is reconstructed.', '']
    for r in [focal[1],focal[0]]:
        if r is not None:
            lines.append(str(r.get('term'))+': '+str(r.get('estimate_pp'))+' pp; 95% CI ['+str(r.get('ci95_low_pp'))+', '+str(r.get('ci95_high_pp'))+']; Holm p='+str(r.get('holm_p_family2')))
    if failure:lines.append('Failure: '+failure)
    (out/'READ_RESULTS.txt').write_text('\n'.join(lines)+'\n')
    for name in ('ANALYSIS_PLAN.md','IMPLEMENTATION.txt'):shutil.copyfile(PACKAGE/name,out/name)
    write(out/'REPORT_MANIFEST.json',[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in sorted(out.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json'])
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True);z=desktop/f'RECEIPT_COHORT_TESTS_REPORT_{key[:12]}.zip';tmp=z.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(out.iterdir()):
            if p.is_file():archive.write(p,p.name)
    os.replace(tmp,z);z.with_suffix('.zip.sha256').write_text(sha(z)+'  '+z.name+'\n');log('RETURN_ZIP: '+str(z));return z
