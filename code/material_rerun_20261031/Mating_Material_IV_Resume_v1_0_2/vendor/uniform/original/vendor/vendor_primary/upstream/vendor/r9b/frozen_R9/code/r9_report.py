"""Explicit aggregate allowlist: no account, game, row, or influence payloads."""
from r9_common import *
import zipfile

def collect(root,sd):
    names=['A_receipt','B_before','C_timing','C_paired_timing','D_placebo','D_receipt_minus_placebo','E_entry',
        'F_balance','F_joint_balance','G_implied_bias','H_figure5','learning','learning_contrasts','adoption_decomposition']
    tables={k:[] for k in names};complete=[]
    for path in sorted((root/'fits').glob('*/result.json')):
        if not (path.parent/'_DONE.json').exists():continue
        result=u.load(path);meta=result['estimates'][0];complete.append(dict(model=path.parent.name,**public(u.load(path.parent/'_DONE.json'))))
        if meta.get('score_mode')!='new' or meta.get('control_mode')!='matched':target='adoption_decomposition'
        elif meta.get('split'):target='learning'
        elif meta['sample'].startswith('F'):target='E_entry'
        elif meta['sample'].startswith('O'):target='D_placebo'
        elif meta['cohort']=='timing_common':target='C_timing'
        elif meta['score']=='B':target='B_before'
        else:target='A_receipt'
        for row in result['estimates']:
            tables[target].append(scaled(row,sd) if sd and row.get('estimator') in ('first_stage','reduced_form') else row)
        if target in ('A_receipt','D_placebo','E_entry'):
            tables['F_balance']+=result['balance'];tables['F_joint_balance']+=result['joint_balance']
        tables['H_figure5'] += [scaled(row,sd) if sd and row.get('record_type')=='linear_first_stage' else row for row in result['figure5']]
    for path in sorted((root/'contrasts').glob('*/result.json')):
        if not (path.parent/'_DONE.json').exists():continue
        rows=u.load(path)
        for row in rows:
            target='D_receipt_minus_placebo' if row['contrast']=='S0_minus_ordinary' else ('C_paired_timing' if row['contrast']=='after_minus_before' else 'learning_contrasts')
            tables[target].append(scaled(row,sd) if sd and row['estimator']!='2SLS' else row)
    for path in sorted((root/'calibration').glob('*/result.json')):
        if not (path.parent/'_DONE.json').exists():continue
        for row in u.load(path):
            v=scaled(row,sd) if sd else row
            ref=[x for x in tables['A_receipt'] if x['control_level']==row['control_level'] and x['cohort']=='full' and x.get('outcome')==row['outcome']
                and x.get('estimator') in ('first_stage','reduced_form')]
            u.require(len(ref)==1,'Missing RF/FS beside implied-bias row')
            v.update(observed_coefficient_pp=ref[0].get('coefficient_pp'),observed_standard_error_pp=ref[0].get('standard_error_pp'),
                implied_to_observed_ratio=row['coefficient']/ref[0]['coefficient'] if ref[0].get('coefficient') else None)
            if sd:v['conditional_fixed_rule_SE_pp']=100*sd*row['conditional_fixed_rule_SE']
            tables['G_implied_bias'].append(v)
    return tables,complete

def validate(tables,plan,root,phase):
    for job in plan:
        u.require((Path(job['output'])/'_DONE.json').exists(),'Final model missing: '+Path(job['output']).name)
    primary=[x for x in tables['A_receipt'] if x.get('estimator')=='2SLS' and x['cohort']=='full']
    u.require(len(primary)==2 and all(x['n']==2682329 for x in primary),'Full S0 receipt contract changed')
    neutral=[x for x in tables['A_receipt'] if x.get('estimator')=='2SLS' and x['cohort']=='neutral']
    u.require(len(neutral)==2 and all(x['n']==2452682 for x in neutral),'Neutral S0 contract changed')
    old_receipt=u.load(ROOT/'evidence/baseline/B_estimates.json')
    old_timing=u.load(ROOT/'evidence/baseline/B_timing.json')
    for row in primary+neutral:
        screen='all' if row['cohort']=='full' else 'neutral'
        ref=next(x for x in old_receipt if x.get('estimator')=='2SLS' and x['control_level']==row['control_level'] and x['exposure_screen']==screen)
        u.require(row['row_set_sha256']==ref['row_set_sha256'],'Frozen S0 row digest changed')
    for level in LEVELS:
        full=next(x for x in primary if x['control_level']==level)
        before=[x for x in tables['B_before'] if x['control_level']==level]
        u.require(before and all(x['n']==full['n'] and x['row_set_sha256']==full['row_set_sha256'] for x in before),'Before-only full S0 lost rows')
        timing=[x for x in tables['C_timing'] if x['control_level']==level]
        u.require({x['score'] for x in timing}=={'A','B','C'} and len({x['row_set_sha256'] for x in timing})==1,'Timing rows differ')
        ref=next(x for x in old_timing if x.get('estimator')=='2SLS' and x['control_level']==level)
        u.require(all(x['n']==ref['n'] and x['row_set_sha256']==ref['row_set_sha256'] for x in timing),'Timing cohort changed from baseline')
    u.require(len(tables['C_paired_timing'])==6 and len(tables['D_receipt_minus_placebo'])==4,'Required joint contrasts missing')
    u.require(len([x for x in tables['H_figure5'] if 'bin' in x])==20,'Figure 5 needs 20 bins')
    u.require(sum(x['rows'] for x in tables['H_figure5'] if 'bin' in x)==2682329,'Figure 5 rows differ')
    u.require(len(tables['G_implied_bias'])==4,'Implied-bias Y/D rows missing')
    u.require(len(tables['F_joint_balance'])==8,'Four frames by two control sets required for T30')
    for sample,label in [('F','E_entry'),('O','D_placebo')]:
        u.require(all(x['n']==phase['frame_rows'][sample] for x in tables[label]),'Comparison model row count changed')
        u.require(all(x['row_set_sha256']==phase['frame_row_sha256'][sample] for x in tables[label]),'Comparison model row digest changed')

def adoption(root):
    path=root/'fits/S0__full__A__X0_ENV_indicator/result.json'
    if not path.exists():return dict(status='PRIMARY_NOT_YET_FIT')
    row=next(x for x in u.load(path)['estimates'] if x.get('estimator')=='2SLS')
    beta=row.get('iv_coefficient_pp');se=row.get('iv_standard_error_pp')
    if beta is None or se is None:return dict(status='HOLD_UNSUPPORTED_PRIMARY',automatic_adoption=False)
    shift=beta-.281;trigger=abs(shift)>se/3
    result=dict(reference_2SLS_pp=.281,primary_2SLS_pp=beta,primary_SE_pp=se,shift_pp=shift,
        one_third_SE_pp=se/3,triggered=trigger,automatic_adoption=False,
        status='HOLD_FOR_SHIFT_REVIEW' if trigger else 'WITHIN_PREDECLARED_SHIFT_THRESHOLD')
    if trigger:
        oldrows=u.load(ROOT/'evidence/baseline/B_estimates.json')
        base=next(v for v in oldrows if v.get('estimator')=='2SLS' and v['control_level']=='X0_ENV_indicator' and v.get('exposure_screen')=='all')
        oldcontrol=root/'fits/decomp_new_score_old_controls__X0_ENV_indicator/result.json'
        oldscore=root/'fits/decomp_old_score_new_controls__X0_ENV_indicator/result.json'
        if oldcontrol.exists() and oldscore.exists():
            def iv(p):return next(v['iv_coefficient_pp'] for v in u.load(p)['estimates'] if v.get('estimator')=='2SLS')
            b00=base['iv_coefficient_pp'];b10=iv(oldcontrol);b01=iv(oldscore)
            result.update(exact_saved_baseline_pp=b00,score_change_alone_pp=b10-b00,control_change_alone_pp=b01-b00,
                interaction_pp=beta-b10-b01+b00,score_change_given_new_controls_pp=beta-b01,
                control_change_given_new_score_pp=beta-b10,
                decomposition_explains_shift_to_roundoff=abs((b10-b00)+(b01-b00)+(beta-b10-b01+b00)-(beta-b00))<1e-12,
                status='HOLD_SHIFT_DECOMPOSED_REVIEW_BEFORE_ADOPTION',
                explanation='Same-row 2x2 decomposition isolates donor-month adjustment, replaced history controls, and their interaction; inspect these rows before adoption.')
    return result

def export(root,desktop,conf,progress,status,extra,plan=()):
    folder=root/'report';folder.mkdir(parents=True,exist_ok=True)
    sdpath=root/'common_scale.json';sd=u.load(sdpath)['common_score_SD'] if sdpath.exists() else None
    tables,complete=collect(root,sd)
    if progress==100:validate(tables,plan,root,extra['comparison_frame'])
    for name,rows in tables.items():r.write_rows(folder,name,rows)
    for src,name in [(root/'baseline/model_reproduction.json','baseline_model_reproduction'),
        (root/'scores_combined/baseline_score_reproduction.json','baseline_score_reproduction'),
        (root/'scores_combined/diagnostics.json','I_score_diagnostics')]:
        if src.exists():r.write_rows(folder,name,u.load(src))
    gate=adoption(root)
    r.io.js(folder/'adoption_rule.json',gate)
    summary=dict(version=VERSION,configuration_sha256=conf,baseline_configuration=BASE_CONF,status=status,progress_percent=progress,
        completed_models=complete,completed_model_count=len(complete),common_score_SD=sd,legacy_score_SD=BRIDGE_SD,fixed_bridge_score_SD=FIXED_SD,
        primary_control_set='X0_ENV_indicator',secondary_control_set='X0',definition=DEFINITION,adoption_rule=gate,
        api_requests=0,stockfish_searches=0,aggregate_tables_only=True,**extra)
    r.io.js(folder/'summary.json',summary)
    r.write_rows(folder,'legacy_receipt_reference',u.load(ROOT/'evidence/baseline/B_estimates.json'))
    (folder/'READ_RESULTS.txt').write_text(
        'R9 CERTIFIED NUMERICAL RUN — read summary.json and adoption_rule.json first.\n'
        'Certification means input identity and numerical reproduction, not causal identification.\n'
        'A: all donor times. B: strictly before focal start. C: strictly after focal anchor. Every j-i pair decision is removed.\n'
        'A/B/C each replace the three history controls with their own donor count, distinct counterparts and expected rate. Counts retain log1p.\n'
        'State references retain frozen models/EB state-cell shrinkage and both-player fold exclusion, but use each donor event UTC month.\n'
        'Fallback: latest usable reference no later than donor month; earliest usable if none earlier. Counts and model mapping are in summary/diagnostics.\n'
        'Every slope in pp uses ONE common Score A residual SD in full S0 ENV-indicator. *_per_fixed_0_0594 is the requested 0.0594 bridge; *_per_legacy_SD additionally uses the exact old 0.059411690344000595.\n'
        'Native coefficient/SE columns retain probability per unit score. Covariance matrices in RF contrasts use those native units.\n'
        'IV and paired IV differences remain percentage points per receipt; AR is unchanged by score rescaling.\n'
        'Balance uses trait SD per each model native residual-score SD, with Holm across seven T30 traits within a frame/control set.\n'
        'Full B retains all S0 rows: if any donors lack support, report that specification unsupported instead of dropping or imputing rows.\n'
        'Paired timing and receipt-minus-placebo tests stack both equations with actual shared accounts and dates.\n'
        'G trains the 15-trait projection with FE plus the seven X0-NH controls (no ENV in training); only the trait component is used.\n'
        'G standard errors include uncertainty in the fitted trait coefficients. This is an observed-trait calibration, not identified bias.\n'
        'Figure 5: 20 equal-count bins; residual-receipt mean intervals use the shared CR0 conditional on fitted residuals/bins.\n'
        'Learning full chronology is the observed 24-month chooser-fair history before focal start, not lifetime history.\n'
        'The 90-day flag is the frozen R7 fair_90>0 flag, with its original cutoff. All splits are descriptive heterogeneity checks.\n'
        'The neutral material sample is exactly the archived 2,452,682-row strict abs(material)<4 screen; boundaries are not redefined.\n'
        'Full-period scores and their history controls can use post-focal events. The procedure is the frozen single-score 2SLS, not UJIVE.\n'
        'No manuscript changes or automatic adoption are performed. A triggered adoption rule requires review of the reported decomposition.\n')
    allowed=[p for p in folder.iterdir() if p.is_file() and p.name!='REPORT_MANIFEST.json']
    u.require(not any('PRIVATE' in p.name for p in allowed),'Private payload attempted in report')
    manifest=[dict(path=p.name,sha256=u.sha(p),bytes=p.stat().st_size) for p in sorted(allowed)]
    r.io.js(folder/'REPORT_MANIFEST.json',manifest)
    desktop.mkdir(parents=True,exist_ok=True);target=desktop/f'R9_CERTIFIED_REPORT_{conf[:12]}_{progress:03d}.zip'
    temp=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(allowed+[folder/'REPORT_MANIFEST.json']):z.write(p,p.name)
    os.replace(temp,target);target.with_suffix('.zip.sha256').write_text(u.sha(target)+'  '+target.name+'\n')
    u.log(f'{progress}% R9_CHECKPOINT_SAVED: {target}; status={status}')
    return summary
