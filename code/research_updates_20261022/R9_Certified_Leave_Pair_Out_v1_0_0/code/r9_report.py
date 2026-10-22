"""Explicit aggregate allowlist; row scores and influence files never leave XT_Pro."""
from r9_common import *
import zipfile

def diagnostics(paths,scores,old_scores,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1);rows=[]
        try:
            for key in ('S0','F50','F'):
                c.execute('CREATE OR REPLACE VIEW s AS SELECT * FROM '+u.parq([scores[key]]))
                c.execute('CREATE OR REPLACE VIEW b AS SELECT row_id,adjusted_all_time FROM '+u.parq([old_scores[key]]))
                values=c.execute('''SELECT count(*),avg(n_A),median(n_A),sum(n_A),sum(cross_month_donors),
                    avg(cross_month_donors/n_A),sum(donors_after_anchor),avg(donors_after_anchor/n_A),
                    sum(fallback_donors_A),corr(adjusted_A,adjusted_all_time),sum(n_B<5),sum(n_B>=5 AND n_C>=5)
                    FROM s JOIN b USING(row_id)''').fetchone()
                n,mean,median,total,cross,avgcross,after,avgafter,fallback,corr,short,common=values
                rows.append(dict(sample=key,n=n,mean_donors=mean,median_donors=median,total_donor_focal_assignments=total,
                    cross_month_donor_assignments=cross,share_cross_month_donors=cross/total,mean_row_share_cross_month=avgcross,
                    donors_after_anchor_assignments=after,share_donors_after_anchor=after/total,mean_row_share_after_anchor=avgafter,
                    fallback_donor_assignments=fallback,share_fallback_donors=fallback/total,
                    correlation_A_old_score=corr,old_score_comparison='reproduced archived 2a4e617b40bc' if key!='F' else 'same old recipe recomputed on the selected larger frame; no archived old score exists for added rows',
                    before_fewer_than_five=short if key=='S0' else None,common_supported_rows=common if key=='S0' else None))
            c.execute('CREATE OR REPLACE VIEW s AS SELECT * FROM '+u.parq([scores['S0']]))
            for sample,tag,where in [('S0_full','B','TRUE'),('S0_common','B','n_B>=5 AND n_C>=5'),('S0_common','C','n_B>=5 AND n_C>=5')]:
                a=c.execute(f'SELECT avg(n_{tag}),median(n_{tag}),sum(fallback_donors_{tag}),sum(n_{tag}) FROM s WHERE {where}').fetchone()
                rows.append(dict(sample=sample,score=tag,mean_donors=a[0],median_donors=a[1],fallback_donor_assignments=a[2],total_donor_focal_assignments=a[3]))
        finally:r.finish_connection(c,tmp/'spill')
        r.io.js(tmp/'diagnostics.json',rows);return dict(rows=len(rows))
    return r.stable_stage(root,conf,build,list(scores.values())+list(old_scores.values()))[0]/'diagnostics.json'

def adoption(root):
    steps=[]
    oldrows=u.load(ROOT/'evidence/baseline/B_estimates.json')
    for level in LEVELS:
        b=next(x for x in oldrows if x['control_level']==level and x['exposure_screen']=='all' and x['estimator']=='2SLS')
        prior=b['iv_coefficient_pp'];steps.append(dict(control_level=level,step='0_baseline',iv_coefficient_pp=prior,iv_standard_error_pp=b['iv_standard_error_pp'],change_from_previous_pp=0.))
        for label,step in [('bridge_month__'+level,'1_donor_month_score_old_controls'),('A_full__'+level,'2_donor_month_score_rebuilt_controls')]:
            p=root/'fits'/label/'result.json'
            if not p.exists():continue
            row=next(x for x in u.load(p)['estimates'] if x['estimator']=='2SLS')
            value=row['iv_coefficient_pp'];steps.append(dict(control_level=level,step=step,iv_coefficient_pp=value,
                iv_standard_error_pp=row.get('iv_standard_error_pp'),change_from_previous_pp=value-prior));prior=value
    p=root/'fits/A_full__X0_ENV_indicator/result.json'
    if not p.exists():return dict(status='PENDING_PRIMARY_MODEL'),steps
    row=next(x for x in u.load(p)['estimates'] if x['estimator']=='2SLS');se=row.get('iv_standard_error_pp')
    if not se:return dict(status='REVIEW_REQUIRED_PRIMARY_INFERENCE_UNAVAILABLE'),steps
    diff=abs(row['iv_coefficient_pp']-.281);moved=diff>se/3
    complete=len(steps)==6
    return dict(status='REVIEW_REQUIRED_MATERIAL_MOVEMENT' if moved else 'WITHIN_PRESPECIFIED_MOVEMENT_THRESHOLD',
        primary_2SLS_pp=row['iv_coefficient_pp'],primary_SE_pp=se,reference_pp=.281,absolute_change_pp=diff,
        threshold_pp=se/3,exceeds_threshold=moved,decomposition_complete=complete,
        automatic_adoption=False,explanation='Sequential exact-row decomposition isolates donor-month prediction and rebuilt donor controls. The bridge_oldscore rows also hold the score fixed while changing controls, exposing interactions and order dependence. Log1p transforms remain frozen. These are numerical changes, not causal explanations.'),steps

def export(root,desktop,conf,progress,status,extra):
    folder=root/'report';folder.mkdir(parents=True,exist_ok=True)
    tables={k:[] for k in ('A_receipt','B_before_full','C_timing','D_placebo','E_entry','F_balance','F_joint_balance','G_implied_bias','H_figure5','learning','adoption_bridge','contrasts')}
    completed=0
    for p in sorted((root/'fits').glob('*/result.json')):
        if not (p.parent/'_DONE.json').exists():continue
        result=u.load(p);label=p.parent.name;completed+=1
        key=('adoption_bridge' if label.startswith('bridge_') else 'learning' if label.startswith('learning_') else
            'C_timing' if label.startswith('C_') else 'B_before_full' if label.startswith('B_') else
            'D_placebo' if label.startswith('D_') else 'E_entry' if label.startswith('E_') else 'A_receipt')
        tables[key]+=result['estimates'];tables['F_balance']+=result['balance'];tables['F_joint_balance']+=result['joint_balance']
        tables['G_implied_bias']+=result['implied_bias'];tables['H_figure5']+=result['figure5']
    for p in sorted((root/'contrasts').glob('*/result.json')):
        if (p.parent/'_DONE.json').exists():tables['contrasts']+=u.load(p)
    if progress==100:
        plan=u.load(root/'MODEL_PLAN_PRIVATE.json')
        u.require(completed==len(plan),'Final model plan incomplete')
        expected_contrasts=22 if extra.get('learning_split')=='both' else 10
        u.require(len(tables['contrasts'])==expected_contrasts,'Final contrast plan incomplete')
        u.require((root/'baseline_certification/certificate.json').exists(),'Baseline certificate missing')
    gate,decomposition=adoption(root)
    for key,rows in tables.items():
        rows.sort(key=lambda x:(x.get('sample',''),x.get('score',''),LEVELS.index(x['control_level']) if x.get('control_level') in LEVELS else 0,x.get('outcome',''),x.get('estimator','')))
        r.write_rows(folder,key,rows)
    r.write_rows(folder,'adoption_decomposition',decomposition)
    if (root/'score_diagnostics/diagnostics.json').exists():r.write_rows(folder,'I_score_diagnostics',u.load(root/'score_diagnostics/diagnostics.json'))
    if (root/'baseline_certification/certificate.json').exists():r.io.js(folder/'Step0_baseline_certificate.json',u.load(root/'baseline_certification/certificate.json'))
    public={k:v for k,v in extra.items() if k not in ('private_paths',)}
    summary=dict(version=VERSION,configuration_sha256=conf,status=status,progress_percent=progress,completed_models=completed,
        api_requests=0,stockfish_searches=0,baseline_run=BASELINE,specification=SPEC,adoption=gate,**public)
    r.io.js(folder/'summary.json',summary)
    (folder/'READ_RESULTS.txt').write_text(
        'R9 certified leave-pair-out: read summary.json and Step0_baseline_certificate.json first.\n'
        'ENV-indicator is primary; X0 is beside it. S0 full/neutral are frozen.\n'
        'A/B/C use all-time/before-start/after-anchor donor histories. A controls apply throughout except the specified B-own-controls exception; C uses A controls.\n'
        'Donor p_hat uses its event UTC month. Missing references use the latest earlier usable same-fold model; with none, p_hat=0, retaining the donor without adjustment. All affected assignments are counted.\n'
        'The requested log-count controls retain their exact baseline implementation, log(1+n) and log(1+distinct counterparts). Only their donor sets change.\n'
        'All score coefficients use one common S0-full A ENV residual-score SD, plus exactly 0.0594. 2SLS is pp per receipt; balance is trait SD per native residual-score SD.\n'
        'T30 is the frozen seven-trait set; Holm is within each seven-trait set.\n'
        'C after-minus-before and S0-minus-ordinary contrasts stack both equation influence functions under shared account/date covariance.\n'
        'G is trait-part-only in-sample calibration trained on standardized fifteen traits with FE and X0-NH. Its SE includes fitted-rule uncertainty. It is not identified bias.\n'
        'H contains only twenty equal-count bins; their conditional descriptive CIs do not propagate score or bin-construction uncertainty.\n'
        'Timing-common rows condition on future donor support. Full chronology learning flags are left-censored in November 2023; a learning difference alone does not establish passing on or exclusion.\n'
        'Phase 100 is used only if completed assembled frames with authenticated lineage are available at startup; a download-only checkpoint is not an analysis frame. Selection is frozen on resume.\n'
        'The final status can require adoption review even though all computations finished. No manuscript or prior run is changed.\n')
    # Only these explicitly generated report files enter the export, never arbitrary private stages/logs.
    allowed={k+ext for k in list(tables)+['adoption_decomposition','I_score_diagnostics'] for ext in ('.json','.csv','.parquet')}
    allowed|={'summary.json','READ_RESULTS.txt','Step0_baseline_certificate.json'}
    files=[folder/name for name in sorted(allowed) if (folder/name).is_file()]
    r.io.js(folder/'REPORT_MANIFEST.json',[dict(path=p.name,sha256=u.sha(p),bytes=p.stat().st_size) for p in files])
    target=desktop/f'R9_CERTIFIED_REPORT_{conf[:12]}_{progress:03}.zip';tmp=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[folder/'REPORT_MANIFEST.json']:z.write(p,p.name)
    os.replace(tmp,target);target.with_suffix('.zip.sha256').write_text(u.sha(target)+'  '+target.name+'\n')
    u.log(f'{progress}% CHECKPOINT_SAVED: {target}');return summary
