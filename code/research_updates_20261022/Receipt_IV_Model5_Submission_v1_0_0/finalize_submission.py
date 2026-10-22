"""Verify the completed parent report and assemble the agreed submission tables."""
from supp_core import *
import zipfile, csv, io
from pathlib import PurePosixPath

REQUIRED_PARENT = ['receipt/STATUS.json','receipt/model_estimates.csv','receipt/balance_joint.csv',
 'receipt/legacy_reproduction.json','receipt/overlap_audit.json',
 'comparisons/model_estimates.csv','comparisons/balance_joint.csv',
 'comparisons/receipt_minus_ordinary.csv','comparisons/ordinary_equivalence.json',
 'comparisons/comparison_frame_counts.csv']

def parse_csv(data):return list(csv.DictReader(io.StringIO(data.decode())))
def truth(x):return x is True or str(x).lower()=='true'
def number(x):return None if x is None or x=='' else float(x)

def verified_parent(path):
    """Read aggregate members only; reject 075, changed scientific rules, or bad hashes."""
    path=Path(path);before=signature(path);side=path.with_suffix('.zip.sha256')
    digest=sha(path);require(side.read_text().split()[0]==digest,'Parent 100 ZIP checksum mismatch')
    with zipfile.ZipFile(path) as z:
        names=z.namelist();require(len(names)==len(set(names)),'Duplicate parent ZIP entries')
        records=json.loads(z.read('REPORT_MANIFEST.json'));public={}
        for r in records:
            key=r['path'];p=PurePosixPath(key)
            require(not p.is_absolute() and '..' not in p.parts and p.parts[0] in ('receipt','comparisons'),'Unsafe parent report member')
            require(key not in public,'Duplicate parent manifest entry')
            b=z.read(key);require(len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256'],'Parent member checksum mismatch: '+key)
            public[key]=b
        require(all(k in public for k in REQUIRED_PARENT),'Parent 100 report missing required analyses')
        require(set(public)=={n for n in names if n.startswith(('receipt/','comparisons/')) and not n.endswith('/')},'Unmanifested parent aggregate member')
    require(signature(path)==before,'Parent report changed while reading')
    status=json.loads(public['receipt/STATUS.json'])
    require(status['status']=='COMPLETE' and status['milestone_percent']==100 and
        status['receipt_models_complete'] and status['expanded_entry_and_placebo_complete'],'Parent entry/placebo report is not complete')
    require(status['configuration_sha256']==EXPECTED_CONF and status['rule']==c.RULE90,'Parent scientific configuration changed')
    require(json.loads(public['receipt/legacy_reproduction.json'])['passed'],'Parent legacy replay did not pass')
    receipt=parse_csv(public['receipt/model_estimates.csv'])
    rows=[r for r in receipt if r['sample']=='uniform_unspaced' and r['term']=='iv_y']
    require(len(rows)==1,'Expected one parent Model 5 IV estimate');r=rows[0]
    require(int(r['n'])==EXPECTED_N and int(r['recipients'])==EXPECTED_PEOPLE and r['row_set_sha256']==EXPECTED_ROWS,'Parent 100 Model 5 sample changed')
    require(np.isclose(float(r['coefficient']),.3246734093460897,rtol=2e-10,atol=2e-10) and
            np.isclose(float(r['standard_error']),.05641077060922318,rtol=2e-10,atol=2e-10),'Parent 100 differs from verified Model 5 result')
    comparison=parse_csv(public['comparisons/model_estimates.csv'])
    wanted={'uniform_F':{'rf_analysis_entry_uniform90','rf_recipient_disconnect_main','rf_active_timeout'},
            'uniform_O':{'rf_y','rf_reached'}}
    for sample,terms in wanted.items():
        found=[r for r in comparison if r['sample']==sample]
        require({r['term'] for r in found}==terms and len(found)==len(terms),'Incomplete parent comparison estimates: '+sample)
        require(all(int(r['n'])>=2000 and np.isfinite(float(r['coefficient'])) for r in found),'Invalid parent comparison estimate')
    for sample in ['uniform_F_balance','uniform_O_balance']:
        require(sum(r['sample']==sample and r['term'].startswith('balance_') for r in comparison)==8,'Missing eight-trait comparison balance: '+sample)
    return public,dict(zip_name=path.name,sha256=digest,configuration_sha256=EXPECTED_CONF,verified_manifest_members=len(public))

def wait_parent(path,parent,notify_wait,interval=45):
    """Wait without retaining design arrays; a resumed parent is picked up automatically."""
    path=Path(path);parent=Path(parent);started=time.monotonic();last=None
    while not (path.is_file() and path.with_suffix('.zip.sha256').is_file()):
        statefile=parent/'PRIVATE/STATE.json';state=load(statefile) if statefile.exists() else {}
        problem=[k+': '+str(v.get('status')) for k,v in state.items() if isinstance(v,dict) and v.get('status') in ('FAILED','INTERRUPTED')]
        message=('Parent needs to resume after '+', '.join(problem)+'. Completed supplements are retained; waiting for its 100 report.'
                 if problem else 'Supplements complete. Waiting for the existing entry/placebo job to produce its verified 100 report.')
        if message!=last:notify_wait(message);last=message
        log(message+f' Waiting {int((time.monotonic()-started)/60)} min; checking every {interval}s.');time.sleep(interval)
    return verified_parent(path)

def write_csv(path,rows):
    names=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names);w.writeheader();w.writerows(rows)

def fmt(x,digits=4):
    v=number(x)
    return '--' if v is None else (f'{v:.3g}' if abs(v)<.0001 and v!=0 else f'{v:.{digits}f}')

def tex_escape(s):
    return str(s).replace('\\',r'\textbackslash{}').replace('_',r'\_').replace('%',r'\%').replace('&',r'\&').replace('#',r'\#')

def tex_table(path,rows,title,note):
    lines=[r'\begin{table}[htbp]',r'\centering',r'\caption{'+tex_escape(title)+'}',
        r'\small\setlength{\tabcolsep}{3pt}',r'\begin{tabular}{p{0.45\linewidth}rrrr}',r'\hline',r'Specification & Estimate & SE & $p$ & Rows \\',r'\hline']
    for r in rows:
        lines.append(tex_escape(r['label'])+' & '+fmt(r.get('coefficient'))+' & '+fmt(r.get('standard_error'))+' & '+fmt(r.get('p_value'))+' & '+format(int(r['n']),',')+r' \\')
    lines += [r'\hline',r'\end{tabular}',r'\par\smallskip',r'\begin{minipage}{0.98\linewidth}\footnotesize '+tex_escape(note)+r'\end{minipage}',r'\end{table}']
    path.write_text('\n'.join(lines)+'\n')

def assemble(report,public,provenance,supplements):
    report=Path(report);tables=report/'tables';tables.mkdir(exist_ok=True)
    parent=report/'parent100';parent.mkdir(exist_ok=True)
    for key,value in public.items():
        dest=parent/key;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(value)
    save(report/'parent_100_authentication.json',provenance)
    receipt=parse_csv(public['receipt/model_estimates.csv']);comparison=parse_csv(public['comparisons/model_estimates.csv'])
    rows=supplements['rows'];main=[]
    labels={'legacy_spaced':'Legacy spaced IV','uniform_same_rows':'Uniform 90, same rows IV',
      'uniform_spaced':'Uniform 90, spaced IV','uniform_unspaced_old_calendar':'Uniform 90, old calendar IV',
      'uniform_unspaced':'Model 5: all eligible exposures IV','uniform_unspaced_no_recipient_history':'No recipient-history controls IV'}
    for r in receipt:
        if r['term']=='iv_y':main.append(dict(r,label=labels.get(r['sample'],r['sample'])))
    for sample,term,label in [('S1_recipient_weighted','iv_y','S1: equal total weight per recipient IV'),('model5_unweighted','ols_y','S4: OLS, Model 5 rows and controls')]:
        rr=next(r for r in rows if r['sample']==sample and r['term']==term);main.append(dict(rr,label=label))
    # Nested metadata are useful in the raw supplement CSV, but publication tables use scalars.
    keys=['label','sample','term','n','recipients','coefficient','standard_error','ci95_low','ci95_high','p_value','units','supported']
    flat=[{k:r.get(k) for k in keys} for r in main];write_csv(tables/'main_iv_and_ols.csv',flat)
    note='All estimates are percentage points per receipt. Shared-account-OR-exposure-date CR0 standard errors; generated scores treated as fixed. S1 uses 1/n_i in the fixed effects, controls, moments and influence functions. It changes the weighting, not the retained rows. No recipient fixed effect is added.'
    tex_table(tables/'main_iv_and_ols.tex',flat,'IV and OLS estimates',note)
    comp=[]
    for r in comparison:
        if r['sample'] in ('uniform_F','uniform_O'):
            comp.append({**{k:r.get(k) for k in keys},'label':r['sample']+': '+r['outcome']})
    write_csv(tables/'entry_and_placebo.csv',comp)
    tex_table(tables/'entry_and_placebo.tex',comp,'Expanded entry and ordinary-game placebo',
        'Reduced-form coefficients are percentage points per fixed reference Score A SD (0.04979005187533171). Shared-account-OR-exposure-date CR0 standard errors. The ordinary-game equivalence test and receipt-minus-ordinary contrasts are supplied in parent100/comparisons.')
    balance=[r for r in receipt+comparison if r['term'].startswith('balance_')]
    bkeys=['sample','outcome','n','coefficient','standard_error','p_value','p_Holm_8','units','supported']
    write_csv(tables/'balance.csv',[{k:r.get(k) for k in bkeys} for r in balance])
    for filename in ('rows_per_recipient.csv','recipient_quantiles.csv','recipient_thresholds.csv','contrasts.csv'):
        (tables/filename).write_bytes((report/filename).read_bytes())
    counts=load(report/'recipient_summary.json');overlap=json.loads(public['receipt/overlap_audit.json'])
    require(counts['rows']==EXPECTED_N and counts['recipients']==EXPECTED_PEOPLE,'Recipient-count report sample mismatch')
    require(counts['max_exposures']==overlap['max_exposures_per_repeat_recipient'] and
      counts['rows']-counts['one_exposure_recipients']==overlap['rows_from_repeat_recipients'],'S7 disagrees with parent overlap audit')
    diagnostics=supplements['S5'];flags=[]
    for r in rows:
        if not truth(r['supported']):flags.append(r['sample']+'/'+r['term']+': nonpositive/nonfinite CR0 variance; inference is unavailable, not repaired.')
    for r in comparison:
        if r['sample'] in ('uniform_F','uniform_O') and not truth(r['supported']):flags.append(r['sample']+'/'+r['term']+': parent inference unsupported.')
    for family in ('receipt','comparisons'):
        for r in parse_csv(public[family+'/balance_joint.csv']):
            if not truth(r.get('supported')):flags.append(r['sample']+': joint balance inference unsupported.')
            elif number(r.get('p_value')) is not None and float(r['p_value'])<.05:flags.append(r['sample']+': joint balance rejects at 5%; report magnitude and adjusted individual tests, not a claim of exact balance.')
    for r in comparison:
        if r['sample'] in ('uniform_F','uniform_O') and number(r.get('p_value')) is not None and float(r['p_value'])<.05:
            flags.append(r['sample']+'/'+r['term']+': reduced form differs from zero at 5%; interpret in the paper.')
    equivalence=json.loads(public['comparisons/ordinary_equivalence.json'])
    if not equivalence.get('equivalent'):flags.append('Ordinary-game equivalence is not established at the inherited margin; do not interpret a nonsignificant coefficient as proof of zero.')
    for r in supplements['contrasts']:
        if not truth(r['supported']):flags.append(r['contrast']+'/'+r['term']+': contrast inference unsupported.')
        elif r['contrast']=='recipient_weighted_minus_Model5' and r['term']=='iv_y' and r['p_value']<.05:
            flags.append('S1 and exposure-weighted IV differ at 5% using the joint covariance; discuss the weighting sensitivity.')
    for name in ('mu1','mu0'):
        if not 0<=diagnostics[name]['coefficient']<=1:flags.append('S5 '+name+' is outside [0,1]; report the diagnostic as estimated, without clipping or a monotonicity claim.')
    completion=dict(status='COMPLETE',all_agreed_analyses_complete=True,
       scope=['expanded entry','ordinary-game placebo','S1 recipient-weighted IV','S4 same-frame OLS','S5 optional transformed-outcome diagnostics','S7 recipient counts'],
       baseline_reproduction=load(report/'baseline_reproduction.json'),parent_report=provenance,
       interpretation_flags=flags,scope_is_exhaustive=True,automatic_additional_analyses=False,
       note='All agreed computations and tables are complete. Interpretation flags do not launch more analyses; completion does not certify causal identification or replace manuscript editing.')
    save(report/'COMPLETION.json',completion)
    s1=next(r for r in rows if r['sample']=='S1_recipient_weighted' and r['term']=='iv_y')
    ols=next(r for r in rows if r['term']=='ols_y');iv=next(r for r in rows if r['sample']=='model5_unweighted' and r['term']=='iv_y')
    lines=['AGREED PRE-SUBMISSION COMPUTATIONS COMPLETE','',
      f"Model 5: {EXPECTED_N:,} exposures from {EXPECTED_PEOPLE:,} recipients.",
      f"IV: {fmt(iv['coefficient'])} pp (SE {fmt(iv['standard_error'])}).",
      f"S1 recipient-weighted IV: {fmt(s1['coefficient'])} pp (SE {fmt(s1['standard_error'])}).",
      f"S4 same-frame OLS: {fmt(ols['coefficient'])} pp (SE {fmt(ols['standard_error'])}).",'',
      'Expanded entry and ordinary-game placebo estimates: tables/entry_and_placebo.csv and .tex.',
      'Their equivalence and dependent-sample contrasts are preserved in parent100/comparisons.',
      f"S7: {100*counts['repeat_recipient_row_share']:.3f}% of exposure rows belong to repeat recipients; maximum {counts['max_exposures']} rows for one recipient.",
      f"{overlap['rows_sharing_a_future_choice']:,} rows share a future choice with another retained exposure; {overlap['next_retained_exposure_starts_before_outcome_game']:,} have a later retained exposure before the outcome game starts.",
      'All eligible rows are retained with no spacing. Histories use [game start minus 90 days, game start), with no seven-day gap; the existing complete-follow-up rule remains.',
      f"S5 (probability units): mu1={fmt(diagnostics['mu1']['coefficient'],6)}, mu0={fmt(diagnostics['mu0']['coefficient'],6)}; mu1-mu0={fmt(diagnostics['identity_probability'],6)} = IV(pp)/100.",
      'S5 is a transformed-outcome diagnostic. Values in [0,1] and the algebraic identity do not establish monotonicity or validate the instrument.',
      'A null reaching-a-choice estimate does not prove absence of row creation. The no-recipient-history specification does not bound the effect of dropping a single control.',
      '', 'INTERPRETATION FLAGS']
    lines += ['- '+f for f in flags] or ['- None under the stated descriptive thresholds.']
    lines += ['', 'No further code stage is required for the agreed submission scope. Update the manuscript from the supplied tables and discuss the reported flags. S2/S3/S6/S8 and a first-row specification are not added.']
    (report/'READ_RESULTS_FIRST.txt').write_text('\n'.join(lines)+'\n')
    return completion
