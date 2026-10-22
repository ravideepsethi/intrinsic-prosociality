"""Aggregate-only exports with explicit migration coverage and resumable checkpoints."""
from primary_common import *
import csv, shutil, zipfile

def figure(records,report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    bins=[r for r in records if 'bin' in r]
    require(len(bins)==20 and sum(r['rows'] for r in bins)==EXPECTED_N,'First-stage figure uses wrong cohort')
    line=next(r for r in records if r.get('record_type')=='linear_first_stage')
    x=np.array([r['mean_residual_score']/SD for r in bins]);y=np.array([r['mean_residual_receipt_pp'] for r in bins])
    lo=np.array([r['ci95_low_pp'] for r in bins]);hi=np.array([r['ci95_high_pp'] for r in bins])
    require(np.isfinite(np.r_[x,y,lo,hi]).all(),'Figure has unsupported covariance')
    slope=line['slope_receipt_pp_per_unit_residual_score']*SD
    plt.rcParams.update({'font.family':'DejaVu Serif','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig,ax=plt.subplots(figsize=(6.5,4.3),layout='constrained')
    grid=np.linspace(x.min()-.1,x.max()+.1,150);ax.plot(grid,slope*grid,color='#777777',lw=1.2,label=f'First stage: {slope:.2f} pp per reference SD')
    ax.errorbar(x,y,yerr=np.vstack([y-lo,hi-y]),fmt='o',color='#153e62',capsize=2,markersize=4,label='20 equal-count bins; 95% intervals')
    ax.axhline(0,color='#bbbbbb',lw=.7);ax.set_xlabel('Residual opponent score (fixed R9 reference SDs)');ax.set_ylabel('Residual receipt (percentage points)')
    ax.legend(frameon=False,fontsize=8)
    for ext in ('pdf','png','svg'):fig.savefig(report/('Figure5_total_decisions_five.'+ext),dpi=250)
    plt.close(fig)
    csv_out(report/'first_stage_bins.csv',[dict(bin=r['bin'],exposures=r['rows'],mean_residual_score=r['mean_residual_score'],mean_score_reference_sd=r['mean_residual_score']/SD,
             mean_residual_receipt_pp=r['mean_residual_receipt_pp'],ci_low_pp=r['ci95_low_pp'],ci_high_pp=r['ci95_high_pp']) for r in bins])
    (report/'Figure5_caption.txt').write_text(
        f'Opponent grant score and receipt of a draw. All {EXPECTED_N:,} rebuilt primary exposures. '
        'Twenty equal-count bins after residualizing Score A and receipt on the primary controls and fixed effects. '
        f'The horizontal axis uses the fixed R9 reference SD {SD:.17g}; the new native residual SD is {line["native_residual_score_SD"]:.17g}. '
        'Bars are 95% shared-account-OR-exposure-date CR0 intervals conditional on fitted residuals and bins. '
        f'The linear first stage is {slope:.8f} pp per reference SD. Residual means are not probabilities.\n')

def model_tables(run):
    tables={};fig=None;completed=0;planned=0
    def add(name,rows):
        # Frozen R9 producers carry extra AR fields. The requested output uses
        # Wald intervals only; retain private caches but omit AR export columns.
        tables.setdefault(name,[]).extend({k:v for k,v in row.items() if not k.startswith('AR')}
                                         for row in rows)
    for planfile in ('PRIMARY_PLAN.json','DIAGNOSTIC_PLAN.json'):
        p=run/'PRIVATE'/planfile
        if not p.exists():continue
        jobs=load(p);planned+=len(jobs)
        for job in jobs:
            out=Path(job['output']);path=out/'result.json'
            if not (out/'_DONE.json').exists() or not path.exists():continue
            frozen.r9_inputs.stage_file(path,job['conf']);completed+=1
            data=load(path);name=job['name'];engine=job['engine']
            if engine=='calibration':
                add('history_calibration',[dict(frozen.scaled(x,SD),sample='receipt_total5',provenance='Reestimated on rebuilt primary cohort') for x in data]);continue
            rows=data.get('estimates',[])
            if engine=='r9':
                rows=[frozen.scaled(x,SD) if x.get('estimator')!='2SLS' else x for x in rows]
                table='primary_iv' if name.startswith('primary_r9') else 'neutral_material' if name.startswith('neutral') else 'learning_splits' if name.startswith('learning') else 'timing_scores'
                add(table,rows);add('score_balance_seven',data.get('balance',[]));add('score_balance_joint',data.get('joint_balance',[]))
                if data.get('figure5'):fig=data['figure5']
            else:
                table='same_row_ols' if name.startswith('primary_ols') else 'exposure_hours' if name.startswith('hour_') else 'subgroup_first_stages' if name.startswith('subgroup_') else 'donor_region_models' if name.startswith('donor_') else 'exposure_specifications'
                if name.startswith('primary_ols'):rows=[x for x in rows if x.get('estimator')=='OLS']
                add(table,rows)
                add('score_balance_fifteen',data.get('balance',[]));add('score_balance_fifteen_joint',data.get('joint_balance',[]))
                add('complier_traits',data.get('compliers',[]));add('donor_region_first_stages' if name.startswith('donor_') else 'act_result_first_stages',data.get('first_stages',[]))
                add('act_result_contrasts',data.get('act_contrasts',[]));add('donor_region_system' if name.startswith('donor_') else 'act_result_system',data.get('system',[]))
    for planfile,table in [('TIMING_CONTRAST_PLAN.json','timing_contrasts'),('COMPARISON_CONTRAST_PLAN.json','receipt_minus_ordinary100')]:
        p=run/'PRIVATE'/planfile
        if not p.exists():continue
        for j in load(p):
            out=Path(j['output']);path=out/'result.json'
            if (out/'_DONE.json').exists() and path.exists():
                frozen.r9_inputs.stage_file(path,j['conf'])
                rows=load(path)
                add(table,[x if x.get('estimator')=='2SLS' else frozen.scaled(x,SD) for x in rows])
    for name,rows in tables.items():
        if rows:csv_out(run/'report'/(name+'.csv'),rows)
    if fig:
        p=run/'report/figure_source.json';ck=key(fig)
        old=load(p) if p.exists() else None
        if old!=fig or not (run/'report/Figure5_total_decisions_five.pdf').exists():
            save(p,fig);figure(fig,run/'report')
    return completed,planned

def export(a,run,conf,state,progress):
    report=run/'report';report.mkdir(parents=True,exist_ok=True)
    completed,planned=model_tables(run)
    done=all(state.get(s,{}).get('status')=='COMPLETE' for s in ('primary','wider','scores','features','diagnostics','comparisons'))
    status='RECEIPT_MIGRATION_COMPLETE_SEPARATE_POPULATIONS_FLAGGED' if done else 'CHECKPOINT_OR_STOPPED'
    migration=[
       dict(analysis='Receipt main, OLS, balance, control ladder, first-stage figure',status='UPDATED' if state.get('primary',{}).get('status')=='COMPLETE' else 'PENDING',population='Rebuilt all-time-five primary'),
       dict(analysis='Hours, exposure variants, subgroups, complier traits, timing, learning, donor regions, act/result, neutral material, history calibration',status='UPDATED' if state.get('diagnostics',{}).get('status')=='COMPLETE' else 'PENDING',population='New primary or explicitly defined derivatives'),
       dict(analysis='Receipt-minus-ordinary contrast',status='UPDATED' if state.get('comparisons',{}).get('status')=='COMPLETE' else 'PENDING',population='New receipt cohort versus separately certified O100; joint covariance recomputed'),
       dict(analysis='Ordinary-game and entry populations themselves',status='LEGACY_COMPARISON_POPULATIONS_RETAINED',population='O100/F100 have their own historical eligibility and cooldown construction; not rebuilt by this receipt runner'),
       dict(analysis='Patron IV',status='SEPARATE_MIGRATION_REQUIRED',population='Existing observed-badge sample derives from old S0; revised membership, coverage and design weights must be audited separately'),
       dict(analysis='Matched comparison and Section 4/R13a',status='UNAFFECTED_BY_THIS_RULE',population='Separate estimands and samples')]
    csv_out(report/'migration_status.csv',migration)
    summary=dict(status=status,configuration_sha256=conf,version=VERSION,progress_percent=progress,stages=state,
                 completed_models=completed,planned_models=planned,definition=DEFINITION,
                 all_IV_populations_rebuilt=False,aggregate_outputs_only=True)
    save(report/'STATUS.json',summary)
    (report/'README.txt').write_text((PACKAGE/'REPORT_METHODS.txt').read_text()+'\n\nEXECUTION STATUS\n'+json.dumps(summary,indent=2)+'\n')
    for n in ('cutoff_robustness.csv','cutoff_selection_counts.csv'):shutil.copy2(PACKAGE/'evidence'/n,report/('R12_'+n))
    forbidden={'game_id','recipient_id','opponent_id','chooser_id','username','person','fen','pgn'}
    files=[]
    for p in sorted(report.iterdir()):
        if not p.is_file() or p.name=='REPORT_MANIFEST.json':continue
        require(p.suffix in ('.csv','.json','.txt','.pdf','.png','.svg'),'Unexpected report artifact')
        if p.suffix=='.csv':
            with p.open() as f:require(not forbidden&set(next(csv.reader(f))),'Private identifier in aggregate CSV')
        files.append(p)
    save(report/'REPORT_MANIFEST.json',[dict(file=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in files])
    dest=a.result_dir/f'ALLTIME_IV_PRIMARY_{conf[:12]}_{progress:03}.zip';tmp=dest.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files+[report/'REPORT_MANIFEST.json']:z.write(p,'report/'+p.name)
        if (run/'run.log').exists():z.write(run/'run.log','run.log')
    os.replace(tmp,dest);Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    if (run/'run.log').exists():shutil.copy2(run/'run.log',a.result_dir/f'ALLTIME_IV_PRIMARY_{conf[:12]}.log')
    log('Aggregate checkpoint: '+str(dest))
    return dest
